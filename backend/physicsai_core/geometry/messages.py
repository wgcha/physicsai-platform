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
    "PROP_OVERRIDDEN_BY_PART": ("PROP", "쉘 두께 무효(/PART 카드 두께가 PROP을 덮어씀)"),
    "PROP_THICKNESS_INVALID": ("PROP", "쉘 두께 ≤ 0 또는 범위 밖"),
    "PROP_NOT_FOUND": ("PROP", "지정한 PROP ID·필드를 찾지 못함"),
    "PARAM_NAME_CONFLICT": ("INPUT", "공통 변수 이름 충돌"),
    "PARAM_MAP_UNCONFIRMED": ("INPUT", "다중 baseline 매칭표가 확정되지 않았습니다"),
    "BASELINE_NO_COVER": ("BASELINE", "덮는 기준본 없음(baseline 범위 밖)"),
    "GEOM_INC_FORMAT": ("INTERNAL", "include 고정폭 형식 보존 불가"),
    "GEOM_INTERNAL": ("INTERNAL", "내부 오류"),
    "GEOM_TIMEOUT": ("INTERNAL", "시간 초과"),  # 플랫폼 시간 제한(geometry.timeout_s) — paicad 코드 아님
    # ---- 쉘 판금 모핑(shell-morph.md §6.7) ----
    "SHELL_FIXED_REGION_VIOLATION": ("FIXED", "고정 영역(tie·RBE2) 침범"),
    "SHELL_FIXED_PARSE_FAILED": ("PREP", "고정 정의(tie·RBE2) 해석 실패"),
    "SHELL_UNSUPPORTED_ELEMENT": ("PREP", "쉘(/SHELL·/SH3N)이 아닌 요소"),
    "SHELL_BODY_NOT_SHEET": ("PREP", "중립면(시트) STEP이 아님 — 판재 솔리드는 후속 지원"),
    "SHELL_PART_NOT_FOUND": ("INPUT", "지정한 쉘 PART를 찾지 못함"),
    "GEOM_KIND_MIXED": ("INPUT", "솔리드(쿠션)와 쉘(판금) 형상 파라미터는 한 세트에 함께 쓸 수 없습니다"),
    # ---- 3D 가시화(geometry-view.md §5.5) ----
    "VIEW_TESSELLATION_FAILED": ("VIEW", "3D 형상 변환 실패"),
    "VIEW_TOO_LARGE": ("VIEW", "3D 형상이 너무 큼(표시 허용오차를 키우세요)"),
    "VIEW_EXPORT_FAILED": ("VIEW", "3D 보기를 만들지 못함(그림으로 표시)"),
    "VIEW_NATIVE_ONLY": ("INPUT", "3D 미리보기는 Native 템플릿에서만 쓸 수 있습니다"),
    "VIEW_UNAVAILABLE": ("INPUT", "3D 미리보기를 쓸 수 없습니다 — paicad 뷰 명령 설정 확인"),
    "PREVIEW_BUSY": ("INPUT", "미리보기가 많이 대기 중입니다 — 잠시 후 다시 시도하세요"),
    "ARTIFACT_EXPIRED": ("INPUT", "미리보기 파일이 정리되었습니다 — 다시 미리보기 하세요"),
    "VIEW_PREVIEW_TIMEOUT": ("VIEW", "미리보기 시간 초과"),
    # ---- 쿠션 입력 rad(input-kind.md §5.2): 경고 코드 ----
    "CUSHION_PART_DEF_MISSING": ("INPUT", "쿠션 부품 정의(PART·PROP·MAT) 일부를 조립 폴더에서 찾지 못했습니다"),
}
CATEGORY_LABELS: dict[str, str] = {
    "CAD_FAILED": "CAD 생성 불가", "INTERFERENCE": "간섭", "QUALITY": "품질 미달", "DEVIATION": "편차 초과", "TIE": "tie 투영 실패",
    "PREP": "형상 준비 실패", "INPUT": "입력 오류", "PROP": "쉘 두께 적용 실패", "BASELINE": "baseline 범위 밖", "INTERNAL": "내부 오류",
    "FIXED": "고정 영역 침범", "VIEW": "3D 보기 실패",
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
