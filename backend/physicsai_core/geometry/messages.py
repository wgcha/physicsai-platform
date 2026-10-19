"""paicad 실패 코드 → 한국어 표시 문구·category(geometry-engine.md §6.5 표, §18.4).

paicad는 `code`·`category`·영문 기술 메시지만 낸다. 사용자에게 보이는 한국어는 이 표로 플랫폼이 만든다.
"""

from __future__ import annotations

import re

# code → (category, 한국어 표준 문구)
CODE_TABLE: dict[str, tuple[str, str]] = {
    "GEOM_CAD_FAILED": ("CAD_FAILED", "CAD 생성 불가"),
    "GEOM_TOPOLOGY_CHANGED": ("CAD_FAILED", "CAD 생성 불가(위상 변화)"),
    "GEOM_FEATURE_COLLISION": ("CAD_FAILED", "CAD 생성 불가(피처 간 충돌: 구멍↔리브 등)"),
    "GEOM_INTERFERENCE": ("INTERFERENCE", "간섭"),
    "GEOM_QUALITY": ("QUALITY", "품질 미달"),
    "GEOM_MORPH_FAILED": ("QUALITY", "품질 미달(모핑 해 실패)"),
    "GEOM_DEVIATION": ("DEVIATION", "편차 초과"),
    "GEOM_PARAM_MISMATCH": ("DEVIATION", "편차 초과(파라미터 재측정)"),
    "GEOM_TIE_PROJECTION": ("TIE", "tie 투영 실패"),
    "GEOM_BODY_MAP_FAILED": ("PREP", "바디–component 대응 실패"),
    "GEOM_BASELINE_MISMATCH": ("PREP", "공칭 STEP과 기준 메시 불일치"),
    "GEOM_UNSUPPORTED_ELEMENT": ("PREP", "tetra4가 아닌 쿠션 요소"),
    "GEOM_TAG_FAILED": ("PREP", "경계 분류 실패"),
    "GEOM_EXTRACT_EMPTY": ("PREP", "인식된 피처 없음"),
    "GEOM_INPUT_INVALID": ("INPUT", "입력 오류"),
    "GEOM_OUTPUT_EXISTS": ("INPUT", "입력 오류(출력이 이미 있음)"),
    "RENUM_CSV_MISSING": ("INPUT", "입력 오류(번호 재지정 표 RENUM csv 없음)"),
    "PROP_OVERRIDDEN_BY_ELEMENT": ("PROP", "쉘 두께 무효(요소별 두께가 PROP을 덮어씀)"),
    "PROP_THICKNESS_INVALID": ("PROP", "쉘 두께 ≤ 0 또는 범위 밖"),
    "PROP_NOT_FOUND": ("PROP", "지정한 PROP ID·필드를 찾지 못함"),
    "PARAM_NAME_CONFLICT": ("INPUT", "공통 변수 이름 충돌"),
    "PARAM_MAP_UNCONFIRMED": ("INPUT", "다중 baseline 매칭표가 확정되지 않았습니다"),
    "BASELINE_NO_COVER": ("BASELINE", "덮는 기준본 없음(baseline 범위 밖)"),
    "GEOM_INC_FORMAT": ("INTERNAL", "include 고정폭 형식 보존 불가"),
    "GEOM_INTERNAL": ("INTERNAL", "내부 오류"),
    "GEOM_TIMEOUT": ("INTERNAL", "시간 초과"),  # 플랫폼 시간 제한(geometry.timeout_s) — paicad 코드 아님
}
CATEGORY_LABELS: dict[str, str] = {
    "CAD_FAILED": "CAD 생성 불가", "INTERFERENCE": "간섭", "QUALITY": "품질 미달", "DEVIATION": "편차 초과", "TIE": "tie 투영 실패",
    "PREP": "형상 준비 실패", "INPUT": "입력 오류", "PROP": "쉘 두께 적용 실패", "BASELINE": "baseline 범위 밖", "INTERNAL": "내부 오류",
}
MAX_MESSAGE = 500  # job_steps.failure_message / predict_batch_runs.gen_message 한도
_MM_RE = re.compile(r"boundary deviation\s+([0-9]+(?:\.[0-9]+)?)\s*mm")
_FACES_RE = re.compile(r"([0-9]+)\s*(?:->|→|to)\s*([0-9]+)")


def category_of(code: str | None, report_category: str | None = None) -> str | None:
    if report_category:
        return report_category
    row = CODE_TABLE.get(code or "")
    return row[0] if row else None


def label_of(code: str | None) -> str:
    row = CODE_TABLE.get(code or "")
    return row[1] if row else (code or "알 수 없는 오류")


def korean_message(code: str | None, english: str | None = None) -> str:
    """표준 문구 + (영문 기술 메시지 일부). 위상 변화의 면 수·편차 최대 mm는 영문에서 숫자만 뽑아 덧붙인다(없으면 생략)."""
    base = label_of(code)
    eng = (english or "").strip()
    if code == "GEOM_TOPOLOGY_CHANGED":
        m = _FACES_RE.search(eng)
        if m:
            base = f"CAD 생성 불가(위상 변화: 면 수 {m.group(1)}→{m.group(2)})"
    elif code == "GEOM_DEVIATION":
        m = _MM_RE.search(eng)
        if m:
            base = f"편차 초과(경계 최대 {m.group(1)} mm)"
    if eng:
        base = f"{base} — {eng}"
    return base[:MAX_MESSAGE]
