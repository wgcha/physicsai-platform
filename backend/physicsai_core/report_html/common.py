"""대상별 렌더러 공용 도우미: 공통 머리 표(입력 요약), 값 목록 표시, 표·그림 크기 규칙."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..stage4_predict.input_kind import text_of
from .page import Raw, badge, esc, finite, fmt

SENSE_TEXT = {"min": "최소화", "max": "최대화"}
OP_TEXT = {"<=": "≤", ">=": "≥"}
STATUS_TEXT = {"DONE": "완료", "FAILED": "실패", "CANCELED": "취소됨", "EXPLORING": "탐색 중", "FITTING": "학습 중",
               "VERIFYING": "검증 중", "FINALIZING": "마무리 중", "SUCCEEDED": "성공", "RUNNING": "실행 중",
               "PENDING": "대기", "QUEUED": "대기"}


def study_meta(study: Mapping[str, Any], generated_by: str | None, target_label: str, target_id: str) -> list[tuple[str, Any]]:
    """① 머리(§9.3 공통 틀): Study·프로젝트·대상·생성 정보."""
    return [("Study", f"{study.get('title') or study.get('folder_name') or ''} ({study.get('folder_name') or ''})"),
            ("프로젝트", str(study.get("project_id") or "—")),
            ("대상", f"{target_label} · {str(target_id)[:8]}"),
            ("생성자", generated_by or "—")]


def engine_text(eng: Mapping[str, Any] | None) -> str:
    e = eng or {}
    if e.get("engine") == "native":
        kind = {"shell": "쉘", "solid": "솔리드"}.get(str(e.get("kind") or ""), "")
        ver = f" · paicad {e['version']}" if e.get("version") else ""
        return f"Native 형상 엔진{(' · ' + kind) if kind else ''}{ver}"
    if e.get("engine") == "altair":
        return "Altair(SimLab)"
    return "—"


def param_set_text(ps: Mapping[str, Any] | None) -> str:
    p = ps or {}
    bits = [str(p.get("label") or p.get("id") or "—")]
    kind = p.get("input") or {"assembly": "assembly", "mesh_only": "cushion"}.get(str(p.get("input_kind") or ""))  # 실행 값 우선(input-kind.md §10)
    if kind in ("assembly", "cushion"):
        bits.append(f"입력: {text_of(kind)}")
    return " · ".join(bits)


def model_text(m: Mapping[str, Any] | None) -> str:
    x = m or {}
    if not x:
        return "—"
    name = str(x.get("name") or x.get("id") or "—")
    if x.get("version") is not None:
        name += f" v{x['version']}"
    bits = [name]
    if x.get("label"):
        bits.append(f"라벨 {x['label']}")
    bits.append("Final" if x.get("is_final") else "Final 아님")
    if finite(x.get("eval_score")):
        bits.append(f"평가 점수 {fmt(x['eval_score'])}")
    return " · ".join(bits)


def values_text(values: Mapping[str, Any] | None, names: Sequence[str] | None = None, limit: int = 8) -> str:
    v = values or {}
    keys = [n for n in (names or list(v)) if n in v]
    s = ", ".join(f"{k}={fmt(v[k], 5)}" for k in keys[:limit])
    return s + (f" 외 {len(keys) - limit}개" if len(keys) > limit else "")


def verdict_badge(ok: bool | None, yes: str = "통과", no: str = "미달") -> Raw:
    if ok is None:
        return Raw(badge("—", "na"))
    return Raw(badge(yes if ok else no, "pass" if ok else "fail"))


def metric_name(metric: str, series: str | None = None) -> str:
    return f"{metric} @ {series}" if series else metric


def con_key(c: Mapping[str, Any]) -> str:
    """제약 키(⑥ best.constraints의 키): `metric@series` 또는 `metric`."""
    return f"{c['metric']}@{c['series']}" if c.get("series") else str(c["metric"])


def con_text(c: Mapping[str, Any]) -> str:
    if c.get("op") == "range":
        return f"{fmt(c.get('lo'))} ~ {fmt(c.get('hi'))}"
    return f"{OP_TEXT.get(str(c.get('op')), c.get('op'))} {fmt(c.get('value'))}"


def esc_list(items: Sequence[Any]) -> str:
    return ", ".join(esc(i) for i in items)
