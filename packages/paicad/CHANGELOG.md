# paicad 변경 기록

버전 정책: geometry-engine.md §17. `src/paicad/__init__.py`의 `__version__`이 단일 출처이고, `packages/paicad/**` 를 바꾸는 커밋마다 버전을 올리고 이 파일 최상단에 항목을 추가한다.

## 0.1.0 — 2026-10-19
- 변경: 최초 구현(단계 0(a)·1). 패키지 골격(pyproject src 레이아웃·동적 버전·`test` extra, CLI `paicad --version`/`version --json`/`extract`/`tag`, 공통 규약: 종료코드·`PAICAD PROGRESS/RESULT` 줄·`paicad.log`·덮어쓰기 금지·`.tmp_<pid>` 경유 쓰기·`engine_version`/`schema_version`), `kernel/` OCCT 어댑터(STEP·XDE 바디 이름, 면·엣지·인접·볼록성, 면 (u,v) 평가·점 투영, 엣지 투영, 솔리드 내부 판정 — 경계 밖은 중립 타입만) + 가짜 커널용 Protocol, Radioss `/NODE`·요소 블록 읽기·RENUM 표·component 분할·외피 삼각형·좌표만 바꾸는 고정폭 쓰기(무변경 왕복 바이트 동일), 바디–component 대응 규칙, 피처 인식(THICKNESS·POCKET_DEPTH/WIDTH·RIB_THICKNESS/HEIGHT·HOLE_RADIUS/POS_U/POS_V·FILLET_RADIUS), 기준면 규칙 ①②③·`larger_area_fixed`·override, MIRROR 대칭 묶음, `feasible` 보수 추정(정보용), tag 노드 분류·일관성 보정·접촉면 검출. 시험: build123d·gmsh 가상 쿠션 골든 생성기(`tests/data/make_synthetic.py`)와 단위·통합 시험.
- 영향: 최초 버전(비교 대상 없음). 피처 하이라이트 PNG는 미구현 — `--no-png`가 없으면 경고 `PNG_RENDER_FAILED`, `png: null`.
- 계약: geometry-engine.md §4.3·§4.5·§5·§6.1·§6.2·§9 단계 0(a)·1·§17·§18
