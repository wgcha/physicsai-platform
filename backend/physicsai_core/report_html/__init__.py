"""HTML 결과 요약 보고서 렌더러(upload-report.md §9) — DB·HTTP 없이 일반 dict·dataclass 입력만 받는 순수 함수 모음.

- `page`: 공통 틀·표·inline SVG 그래프·크기 예산(esl `esl/report/html.py` 방식 이식, 외부 자원 0).
- `influence`: ⑤ 영향도(PRCC·SRC) numpy 계산 — 프런트 `analysis/influence.ts`와 같은 값(V-RP-4).
- `opt`(⑥ 내장·레거시)·`analysis`(⑤ 결과 표)·`equiv`(⑤ 등가성)는 대상별 본문.
원천 읽기(기존 서비스 함수 호출)는 `physicsai_api/services/reports*.py`가 맡는다.
"""
