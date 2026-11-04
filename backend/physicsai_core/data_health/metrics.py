"""지표 레지스트리·임계값 스냅숏·① 해석 건전성 판정(data-health.md §3.1, DH-8·DH-12).

`METRICS: dict[id, MetricDef(kind, source, judge)]` — 필드 PCA(kind `field_pca`, DH_FIELD step)는 같은 레지스트리에 등록만 하면 같은
견고 z 판정에 합류한다(비범위, 확장 지점). 판정 기준 숫자는 설정 `data_health` 한 곳에서만 읽는다(여기 상수 없음).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# kind: sound_abs(절대 임계, 분포 무관) | consistency(데이터셋 일관성 위반) | zscore(일반·견고 z + kNN) | field_pca(확장 자리, 미사용)
KIND_SOUND, KIND_CONSISTENCY, KIND_ZSCORE, KIND_FIELD_PCA = "sound_abs", "consistency", "zscore", "field_pca"
GROUP_SOUND, GROUP_CONSISTENCY, GROUP_ATTR, GROUP_RESP = "sound", "consistency", "attr", "resp"
TERM_NORMAL = "NORMAL"


@dataclass(frozen=True)
class MetricDef:
    id: str
    label: str
    unit: str
    group: str
    kind: str
    source: str   # out_tail | starter_out | t01_curves | rad_h3d | mesh | responses | field
    judge: str    # abs_max | term | frames | t_last | robust


METRICS: dict[str, MetricDef] = {}


def register(m: MetricDef) -> MetricDef:
    METRICS[m.id] = m
    return m


for _m in (
    MetricDef("term", "종료 상태", "", GROUP_SOUND, KIND_SOUND, "out_tail", "term"),
    MetricDef("energy_err_pct", "에너지 오차", "%", GROUP_SOUND, KIND_SOUND, "out_tail", "abs_max"),
    MetricDef("added_mass", "추가 질량 비", "", GROUP_SOUND, KIND_SOUND, "out_tail", "abs_max"),
    MetricDef("hg_ratio", "hourglass 에너지 비", "", GROUP_SOUND, KIND_SOUND, "t01_curves", "abs_max"),
    MetricDef("contact_ratio", "접촉 에너지 비", "", GROUP_SOUND, KIND_SOUND, "t01_curves", "abs_max"),
    MetricDef("frames", "h3d 프레임 수", "", GROUP_CONSISTENCY, KIND_CONSISTENCY, "rad_h3d", "frames"),
    MetricDef("t_last", "마지막 해석 시각", "", GROUP_CONSISTENCY, KIND_CONSISTENCY, "rad_h3d", "t_last"),
    MetricDef("bbox_dx", "쿠션 bbox X 치수", "mm", GROUP_ATTR, KIND_ZSCORE, "mesh", "robust"),
    MetricDef("bbox_dy", "쿠션 bbox Y 치수", "mm", GROUP_ATTR, KIND_ZSCORE, "mesh", "robust"),
    MetricDef("bbox_dz", "쿠션 bbox Z 치수", "mm", GROUP_ATTR, KIND_ZSCORE, "mesh", "robust"),
    MetricDef("cog_x", "쿠션 무게중심 X", "mm", GROUP_ATTR, KIND_ZSCORE, "mesh", "robust"),
    MetricDef("cog_y", "쿠션 무게중심 Y", "mm", GROUP_ATTR, KIND_ZSCORE, "mesh", "robust"),
    MetricDef("cog_z", "쿠션 무게중심 Z", "mm", GROUP_ATTR, KIND_ZSCORE, "mesh", "robust"),
    MetricDef("volume", "쿠션 부피", "mm³", GROUP_ATTR, KIND_ZSCORE, "mesh", "robust"),
    MetricDef("mass_total", "모델 총질량(starter)", "", GROUP_ATTR, KIND_ZSCORE, "starter_out", "robust"),
):
    register(_m)

SOUND_IDS = tuple(m.id for m in METRICS.values() if m.kind == KIND_SOUND)
CONSISTENCY_IDS = tuple(m.id for m in METRICS.values() if m.kind == KIND_CONSISTENCY)
MESH_ATTR_IDS = tuple(m.id for m in METRICS.values() if m.source == "mesh")
FRAME_IDS = ("frames", "t_last")


def resp_metric(name: str, unit: str = "") -> MetricDef:
    """스칼라 응답 `resp:<name>` — 등록하지 않는 동적 지표(응답 목록은 작업마다 다르다)."""
    return MetricDef(f"resp:{name}", f"응답 {name}", unit, GROUP_RESP, KIND_ZSCORE, "responses", "robust")


def zscore_metrics(resp_defs: list[MetricDef], *, attrs: bool = True) -> list[MetricDef]:
    base = [m for m in METRICS.values() if m.kind == KIND_ZSCORE and (attrs or m.source not in ("mesh", "starter_out"))]
    return base + list(resp_defs)


def thresholds_snapshot(d: Any) -> dict[str, Any]:
    """작업 시점의 판정 기준(설정 `data_health`) 스냅숏 — inputs.json·jobs.result.thresholds·화면 읽기 전용 표시."""
    keys = ("min_n", "knn_min_n", "knn_k", "sigma_z", "robust_z", "knn_z", "energy_error_pct_max", "added_mass_ratio_max",
            "hourglass_ratio_max", "contact_ratio_max", "t_end_tol", "expected_frames", "expected_t_end")
    return {k: getattr(d, k) for k in keys}


@dataclass(frozen=True)
class SoundResult:
    id: str
    status: str            # OK | FAIL | NA
    value: Any = None
    limit: float | None = None
    code: str | None = None      # FAIL이면 SOUND_<ID>, NA이면 사유
    message: str | None = None


def _na(mid: str, reason: str | None) -> SoundResult:
    return SoundResult(mid, "NA", None, None, reason, None)


def judge_sound(values: Mapping[str, Any], na: Mapping[str, str], d: Any) -> dict[str, SoundResult]:
    """① 건전성(절대 임계). values·na = 원값·결측 사유(지표 id 키). NA는 FAIL이 아니다."""
    out: dict[str, SoundResult] = {}
    t = values.get("term")
    if t is None:
        out["term"] = _na("term", na.get("term"))
    elif t == TERM_NORMAL:
        out["term"] = SoundResult("term", "OK", t)
    else:
        why = "오류 종료" if t == "ERROR" else "종료 표지 없음(중단·잘림)"
        out["term"] = SoundResult("term", "FAIL", t, None, "SOUND_TERM", f"정상 종료 아님 — {why}")
    specs = (
        ("energy_err_pct", d.energy_error_pct_max, True, "에너지 오차", "%"),
        ("added_mass", d.added_mass_ratio_max, False, "추가 질량 비", ""),
        ("hg_ratio", d.hourglass_ratio_max, False, "hourglass 에너지 비", ""),
        ("contact_ratio", d.contact_ratio_max, False, "접촉 에너지 비", ""),
    )
    for mid, lim, use_abs, label, unit in specs:
        v = values.get(mid)
        if v is None:
            out[mid] = _na(mid, na.get(mid))
            continue
        over = (abs(v) if use_abs else v) > lim
        msg = f"{label} {v:g}{unit}가 기준 {'±' if use_abs else ''}{lim:g}{unit}을 넘음" if over else None
        out[mid] = SoundResult(mid, "FAIL" if over else "OK", v, lim, f"SOUND_{mid.upper()}" if over else None, msg)
    return out
