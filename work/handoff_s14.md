# 위임: S14 화면 단계 재편 (④ 예측 · ⑤ 결과분석 신설 · ⑥ 최적화) — 저장소 /home/claude/pai-phase3, 브랜치 claude/phase3
목적: 계약 docs/contracts/s14_analysis.md(§19, D3-62)를 구현한다. 먼저 이 문서와 s12_s13.md §17(지표·run_metrics·design-map)을 읽는다. 계약과 다르게 해야 하면 구현 전에 Plan에 요청(문서는 Plan만 수정).
불변: 내부 코드 경로(stage4_predict·stage5_optimize)·job_type/이름·DB·URL 숫자(/stage/4, /stage/5)·기존 e2e 번호. 바꾸는 것은 메뉴 순서·표시 번호·라벨(프런트)뿐. migration·새 의존성 없음.
순서: (1) Impl-Backend와 Impl-Frontend를 병렬 시작 — 파일 겹침 없음(§19.8), API 모양은 §19.5로 고정.
 - Impl-Backend: GET /train-does/{doe_id}/result-table(읽기 전용, 파일 본문 DB 저장 금지, LRU·no-store는 §17.4와 같음, 오류 404 DOE_NOT_FOUND·SAMPLES_MISSING·409 DOE_NOT_READY), 시험 V3-S14-1, backend/openapi.json 갱신(+ test_openapi 라우트·operation_ids 스냅샷).
 - Impl-Frontend: §19.8 전부 — 6버튼 메뉴·라벨(④ 예측/⑤ 결과분석/⑥ 최적화), 라우트 /stage/analysis, ⑤ 화면, 분석 컴포넌트 ④→⑤ 이동(계산 무수정), 영향도(PRCC·SRC), 겹쳐 보기(이름 집합 같을 때만), stage_label 표시 매핑, 시험 V3-S14-2~6. openapi 병합 전에는 목 라우트, 병합 후 npm run gen:api 1회.
 (2) 둘 다 끝나면 Verifier: V3-S14-1~7 + V3-S12·S13·REG 회귀 판정(수정 없음).
완료 기준: scripts/test-all 통과(Linux, 가짜 도구), frontend/ 변경 시 scripts/build-frontend-dist로 frontend-dist/ 재생성해 같은 변경에 포함(test-all이 최신 검사), 계약 밖 파일 수정은 목록으로 보고. 커밋은 지시 전까지 금지.
반환(≤20줄): 변경 파일, 계약과 달라진 점(변경 메모 요청), 시험 결과(수·통과), 리스크, 미결, E5A 서버 확인 항목 준비 여부.
