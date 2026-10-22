"""표본 방식 목록·라벨·설명 id·영향도 등급·권장 run 수(phase3 §20.4·§20.7, D3-63) — 순수 함수, 문구 상수 1곳.

등급 `influence_class`: formal(정식) / reference(참고용, 회색 안내) / off(비활성 — ①이 서버에서 사유와 함께 정함).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# API kind → (DB source_kind, 표시 이름, desc_id) — §20.4 표 순서
METHODS: dict[str, tuple[str, str, str]] = {
    "lhs_opt": ("LHS_OPT", "최적화 LHS", "lhs_opt"),
    "sobol": ("SOBOL", "Sobol(스크램블 QMC)", "sobol"),
    "halton": ("HALTON", "Halton(스크램블 QMC)", "halton"),  # doe-methods.md DM-C3
    "lhs": ("LHS", "LHS(무작위 층화)", "lhs"),
    "random": ("RANDOM", "균일 랜덤", "random"),  # DM-C3
    "fullfact": ("FULLFACT", "전체 요인", "fullfact"),
    "fracfact": ("FRACFACT", "부분 요인(2수준)", "fracfact"),
    "pb": ("PB", "Plackett–Burman", "pb"),
    "bbd": ("BBD", "Box–Behnken", "bbd"),
    "ccd": ("CCD", "중심 합성(CCD)", "ccd"),
    "table": ("TABLE", "표 붙여넣기 / CSV", "table"),
    "train_doe": ("TRAIN_DOE", "① 학습 DOE 그대로 재사용", "train_doe"),
}
SOURCE_KINDS: dict[str, str] = {k: v[0] for k, v in METHODS.items()}  # API kind → DB source_kind
KIND_OF_SOURCE: dict[str, str] = {v: k for k, v in SOURCE_KINDS.items()}  # DB source_kind → API kind
NEW_KINDS = ("lhs_opt", "sobol", "fullfact", "fracfact", "pb", "bbd", "ccd")
# ① 플랫폼 DOE 생성 방식(phase3 §23.4·§23.9, S18 + DM-C3) — §20.4 순서에서 table·train_doe를 뺀 10개. desc_id = "td_<kind>"
PLATFORM_KINDS = tuple(k for k in METHODS if k not in ("table", "train_doe"))
# train_does.doe_type(플랫폼) = ④ source_kind와 같은 글자. ① 표(TABLE)도 플랫폼 DOE 유형이다(DM-C9)
PLATFORM_DOE_TYPES = tuple(METHODS[k][0] for k in PLATFORM_KINDS) + (METHODS["table"][0],)

# doe-methods.md DM-C1·§3: 지점별 허용 목록(드롭다운 순서). 요청 스키마의 kind 유니언·검증·화면·MCP 설명의 단일 출처
_FULL_SITE = ("lhs_opt", "sobol", "halton", "lhs", "random", "fullfact", "fracfact", "pb", "bbd", "ccd", "table", "train_doe")
_MULTI_SITE = ("lhs_opt", "halton", "lhs", "random")  # DM-C4: baseline별 층화에 쓸 수 있는 층 안 생성기
SITE_KINDS: dict[str, tuple[str, ...]] = {
    "train_platform": _FULL_SITE,  # ①-3 Altair 플랫폼 생성
    "train_native": _FULL_SITE,  # ①-3 Native 단일 baseline
    "train_native_multi": _MULTI_SITE,  # ①-3 Native 다중 baseline
    "batch": _FULL_SITE,  # ④ 단일 baseline
    "batch_multi": _MULTI_SITE,  # ④ 다중 baseline
    "opt_explore": ("lhs", "lhs_opt", "sobol", "halton", "random"),  # ⑥ 탐색 새 DOE(다중 baseline이면 sobol 제외)
}
SITE_DEFAULT: dict[str, str] = {"train_platform": "lhs_opt", "train_native": "lhs", "train_native_multi": "lhs", "batch": "lhs_opt",
                                "batch_multi": "lhs", "opt_explore": "lhs"}
MULTI_UNSUPPORTED_MESSAGE = "다중 baseline 세트는 baseline별 층화라 LHS·최적화 LHS·Halton·균일 랜덤만 됩니다"  # DM-C4

# ① value → desc_id (그 밖 → None = 일반 문구)
DOE_DESC_IDS = {"TYPE_LATINHYPERCUBE": "hs_lhs", "TYPE_SOBOL": "hs_sobol", "TYPE_FULLFACT": "hs_fullfact",
                "TYPE_FRACFACT": "hs_fracfact"}
DOE_FORMAL_TYPES = ("TYPE_LATINHYPERCUBE", "TYPE_SOBOL", "TYPE_FULLFACT")

FORMAL, REFERENCE, OFF = "formal", "reference", "off"
DOE_TYPE_NATIVE_LHS = "NATIVE_LHS"  # ①-3 Native 플랫폼 LHS(geometry-engine.md §7.3.3)

NOTE_TABLE = "직접 만든 표 — 표본 분포를 알 수 없어 영향도는 참고용입니다"
NOTE_FRAC_IV = "부분 요인(해상도 IV) — 2인자 교호작용끼리 교락되어 영향도는 참고용입니다(주효과는 2인자 교호작용과 교락 없음)"
NOTE_FRAC_V = "부분 요인(해상도 V) — 3인자 이상 교호작용과 교락되어 영향도는 참고용입니다"
NOTE_FRAC_III = "부분 요인(해상도 III) — 주효과가 2인자 교호작용과 교락되어 영향도는 참고용입니다"
NOTE_FRAC_ANY = "부분 요인 — 교락되어 영향도는 참고용입니다"
NOTE_PB = "Plackett–Burman — 주효과가 2인자 교호작용과 부분적으로 교락되어 영향도는 참고용입니다"
NOTE_RSM = ("2차 응답면 설계 — 점이 중심·모서리에 몰려 곡률 효과가 선형 영향도에 작게 보일 수 있어 참고용입니다. "
            "변수–응답 그래프로 확인하세요")
NOTE_VERIFY = "최적화 검증 배치 — 최적점 근처에 모인 표본이라 영향도는 참고용입니다"
NOTE_NO_DOE = "원본 ① DOE 정보를 찾을 수 없어 영향도는 참고용입니다"
NOTE_UNKNOWN_DOE = "표본 방식을 알 수 없어 영향도는 참고용입니다"
NOTE_NO_RESPONSE = "응답이 없어 영향도를 계산할 수 없습니다"


def note_too_few_usable(need: int, have: int) -> str:
    return f"영향도에는 유효 run이 {need}개 이상 필요합니다(현재 {have}개)"


def method_info(kind: str) -> tuple[str, str, str]:
    """(DB source_kind, 표시 이름, desc_id). 모르는 kind는 KeyError."""
    return METHODS[kind]


def kind_of_source(source_kind: str) -> str | None:
    """DB source_kind → API kind (모르면 None)."""
    return KIND_OF_SOURCE.get(source_kind)


def recommended_count(kind: str, k: int, max_runs: int) -> int | None:
    """④ 권장 run 수(§20.4 계산식, k = 범위가 있는 변수 수). 설계로 run 수가 정해지는 kind는 None."""
    if kind in ("lhs", "lhs_opt", "halton", "random"):  # DM-C3: halton·random = lhs와 같은 식
        return min(max_runs, max(10, 10 * k))
    if kind == "sobol":
        target, p = 10 * k, 4
        while p < target:
            p *= 2
        if p <= max_runs:
            return p
        p = 4
        while p * 2 <= max_runs:
            p *= 2
        return p
    return None


def _frac_note(resolution: Any) -> str:
    return {4: NOTE_FRAC_IV, 5: NOTE_FRAC_V}.get(resolution, NOTE_FRAC_ANY)


def _as_int(v: Any) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def platform_desc_id(kind: str) -> str:
    """① 플랫폼 DOE 설명 id(§23.10): td_<kind>."""
    return f"td_{kind}"


def doe_influence(doe_type: str | None, options: Mapping[str, Any] | None) -> tuple[str, str | None]:
    """① DOE 유형(+옵션) → (class, note). off는 호출부가 응답·n 조건으로 정한다.
    플랫폼 생성 DOE(doe_type = LHS_OPT 등 ④ source_kind 글자, §23.4)는 ④ 배치와 같은 규칙(batch_influence)."""
    if doe_type == DOE_TYPE_NATIVE_LHS:  # DM-C9: Native 플랫폼 LHS = formal(표본 값은 그대로)
        return FORMAL, None
    if doe_type in PLATFORM_DOE_TYPES:
        return batch_influence(doe_type, options)
    if doe_type in DOE_FORMAL_TYPES:
        return FORMAL, None
    if doe_type == "TYPE_FRACFACT":
        res = _as_int((options or {}).get("RESOLUTION"))
        return REFERENCE, NOTE_FRAC_III if res == 3 else _frac_note(res)
    return REFERENCE, NOTE_UNKNOWN_DOE


def batch_influence(source_kind: str, source_meta: Mapping[str, Any] | None, owned_kind: str | None = None,
                    train_doe_type: str | None = None,
                    train_doe_options: Mapping[str, Any] | None = None) -> tuple[str, str | None]:
    """④ 배치 → (class, note) (formal | reference). owned_kind = 최적화 소유 반복 kind(EXPLORE·VERIFY·FINAL) 또는 None."""
    if owned_kind in ("VERIFY", "FINAL"):
        return REFERENCE, NOTE_VERIFY
    meta = source_meta or {}
    if source_kind in ("LHS", "LHS_OPT", "SOBOL", "HALTON", "RANDOM", "FULLFACT"):  # DM-C9: HALTON·RANDOM = 균일 분포 공간 채움
        return FORMAL, None
    if source_kind == "FRACFACT":
        return REFERENCE, _frac_note(meta.get("resolution"))
    if source_kind == "PB":
        return REFERENCE, NOTE_PB
    if source_kind in ("BBD", "CCD"):
        return REFERENCE, NOTE_RSM
    if source_kind == "TRAIN_DOE":
        if train_doe_type is None:
            return REFERENCE, NOTE_NO_DOE
        return doe_influence(train_doe_type, train_doe_options)
    return REFERENCE, NOTE_TABLE  # TABLE·그 밖
