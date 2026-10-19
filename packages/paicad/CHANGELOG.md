# paicad 변경 기록

버전 정책: geometry-engine.md §17. `src/paicad/__init__.py`의 `__version__`이 단일 출처이고, `packages/paicad/**` 를 바꾸는 커밋마다 버전을 올리고 이 파일 최상단에 항목을 추가한다.

## 0.2.0 — 2026-10-19
- 변경: 단계 2 구현. `paicad update`(공칭 B-rep에서 매번 시작, 면 push/pull = 위상 보존 면 오프셋: 새 면 곡면 → 엣지·꼭짓점 재계산 → 같은 위상으로 재조립, face_map 항등, 기준면 규칙 ①②③을 `--tag-dir` 접촉으로 재적용·대칭 묶음/분리, 리브·포켓은 기준면을 따라 강체 이동, 평면–평면 블렌드(필렛)는 이동 면에 접선 유지, 구멍 위치는 bbox 최소 모서리 기준 보정, OCCT 실패·무효·자기교차 → `GEOM_CAD_FAILED`/`GEOM_TOPOLOGY_CHANGED` 종료코드 10, `applied[].op` = `FACE_OFFSET`/`CYLINDER_RADIUS`/`AXIS_SHIFT`/`REBLEND`), `paicad morph`(꼭짓점·엣지 호장 정규화·면 정규화 (u,v) 목표, 대체 규칙 = 면 위 cotangent 조화 보간 + 샘플 면 투영, 내부 = 연결 성분별 의사탄성 1회(E∝V̄/V_e, ν, CG+Jacobi → spsolve), `/NODE` 좌표 필드만 교체·쓰기 후 ID·연결·요소 수 재확인, |변위| ≤ 1e-6 mm는 0 처리), `paicad check`((a) 재측정 (b) 경계 편차 (c) tetra stretch·경계 삼각형 aspect·최소 엣지·Δt 비·반전·baseline 상대 판정·`BASELINE_QUALITY_BELOW` (d) 바디–바디·제품 간섭 (e) `/INTER/TYPE2` tie(`/GRNOD/NODE`·`/SURF/SEG`, 없으면 SKIPPED), PASS일 때만 `--out-inc`), `paicad morph --sweep`(1D 스윕, 연속 실패 중단, `envelope.json`·`envelope.csv`·`feasible`(source envelope/estimate, sweep_id) 반영한 `parameter_features.json` 사본, `--keep-steps`). kernel: `move_faces`·`save_brep`·`load_brep`, `eval_edge`·`classify_face_uv`·`distance`(OCP는 계속 `kernel/`만). 시험: build123d 변형형 정답 비교(피처 타입별 ±), 무변경 바이트 동일, 결정성, 실패 경로, 가짜 커널 morph/check.
- 영향: 출력 추가(update/morph/check/sweep). extract·tag 결과 불변. 보고 JSON `engine_version` 0.2.0. `face_map.json` 바디 항목에 선택 키 `uv_fallback`(정규화 (u,v) 매핑이 무효인 면 = 매개변수화 교체 또는 내부 와이어의 정규화 위치 변화)
- 계약: geometry-engine.md §4.6·§4.7·§4.8·§5.3·§6.3·§6.4·§6.5·§9 단계 2·§11.2·§17

## 0.1.0 — 2026-10-19
- 변경: 최초 구현(단계 0(a)·1). 패키지 골격(pyproject src 레이아웃·동적 버전·`test` extra, CLI `paicad --version`/`version --json`/`extract`/`tag`, 공통 규약: 종료코드·`PAICAD PROGRESS/RESULT` 줄·`paicad.log`·덮어쓰기 금지·`.tmp_<pid>` 경유 쓰기·`engine_version`/`schema_version`), `kernel/` OCCT 어댑터(STEP·XDE 바디 이름, 면·엣지·인접·볼록성, 면 (u,v) 평가·점 투영, 엣지 투영, 솔리드 내부 판정 — 경계 밖은 중립 타입만) + 가짜 커널용 Protocol, Radioss `/NODE`·요소 블록 읽기·RENUM 표·component 분할·외피 삼각형·좌표만 바꾸는 고정폭 쓰기(무변경 왕복 바이트 동일), 바디–component 대응 규칙, 피처 인식(THICKNESS·POCKET_DEPTH/WIDTH·RIB_THICKNESS/HEIGHT·HOLE_RADIUS/POS_U/POS_V·FILLET_RADIUS), 기준면 규칙 ①②③·`larger_area_fixed`·override, MIRROR 대칭 묶음, `feasible` 보수 추정(정보용), tag 노드 분류·일관성 보정·접촉면 검출. 시험: build123d·gmsh 가상 쿠션 골든 생성기(`tests/data/make_synthetic.py`)와 단위·통합 시험.
- 영향: 최초 버전(비교 대상 없음). 피처 하이라이트 PNG는 미구현 — `--no-png`가 없으면 경고 `PNG_RENDER_FAILED`, `png: null`.
- 계약: geometry-engine.md §4.3·§4.5·§5·§6.1·§6.2·§9 단계 0(a)·1·§17·§18
