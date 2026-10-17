# 계약: S14 화면 단계 재편 — ④ 예측 · ⑤ 결과분석(신설) · ⑥ 최적화 — phase3 §19

> 이 문서는 phase3.md §19와 변경 메모 D3-62다. s12_s13.md와 같은 사정(phase3.md 미커밋 변경)으로 별도 파일로 두며, 다음 Plan 커밋에서 phase3.md 본문과 변경 메모 목록으로 옮기고 이 파일은 한 줄 포인터로 줄인다. 절 번호·용어·원칙은 phase3.md·[s12_s13.md](s12_s13.md)와 같다(§14 일괄 예측, §17 지표 문법·`run_metrics`·design-map, §18 내장 최적화 그대로). 사용자 결정 2026-10-17(D3-62). **migration 없음.**

## 19. S14 ⑤ 결과분석 (사용자 결정 2026-10-17, D3-62)

목표: 화면 단계를 ④ 예측 · ⑤ 결과분석(신설) · ⑥ 최적화(기존 ⑤)로 재편한다. ①~③ 불변. ⑤는 **"결과 표"**(run마다 파라미터 + 응답)를 입력으로 받아 설계공간 지도·영향도·변수–응답 그래프·커브 겹쳐보기를 보여 준다. 1·2·3차 원칙(설정만, AI 루트 읽기, 한국어, 필수 UI, 파일 본문 DB 저장 금지) 유지. 새 DB·새 작업·새 의존성 없음.

### 19.1 범위 / 비범위

| 범위 | 비범위 |
|---|---|
| 메뉴 순서·표시 번호·라벨 변경(프런트만) | 내부 코드 경로(`stage4_predict`, `stage5_optimize` 등)·job_type·job 이름·DB·`jobs.stage` 값·URL 숫자(`/stage/4`·`/stage/5`)·e2e 기존 번호 변경 |
| 출처 (a) 기존 일괄 예측 배치 결과: s12_s13 분석 기능(변수–응답 그래프·커브 겹쳐보기·설계공간 지도)을 ④ 배치 결과에서 ⑤로 **이동**, 기존 API 재사용 | 새 해석·예측 실행, 새 job_type |
| 출처 (b) 해석 DOE 결과: ① train DOE run들의 파라미터 + 응답 → 새 읽기 전용 API 1개 | 대리모델 기반 Sobol(⑥ 또는 후속) |
| 영향도 표: 해석 DOE(LHS)는 PRCC·표준화 회귀계수 | 영향도 표를 임의 표(비 LHS)의 정밀 통계 검정으로 보장하는 것 |
| 두 출처 겹쳐 보기(solver vs predict) | 서로 다른 파라미터 이름 집합의 자동 매핑 |

### 19.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| A1 | 표시 번호·라벨·메뉴 순서만 변경. **URL 숫자·`jobs.stage`·`stage_label` 값·job_type 유지** | 사용자 결정(코드 경로·DB·e2e 번호 유지). 단 사용자에게 보이는 `stage_label`(QueuePanel·알림)은 표시 시 프런트가 job_type→새 표시 번호로 매핑(§19.3) |
| A2 | 공통 입력 = **결과 표** 1종(§19.4). 두 출처는 같은 모양으로 변환해 같은 분석 컴포넌트에 넣는다 | 분석 코드 1벌, 출처 추가 용이 |
| A3 | 출처 (a)는 **API 신설 없음** — 기존 `GET /predict-batches/{bid}`(결과 표)·`design-map`·`curves`를 프런트 어댑터가 결과 표로 변환 | 사용자 결정(기존 API 재사용) |
| A4 | 출처 (b)용 **새 API 1개**: `GET /train-does/{doe_id}/result-table`(§19.5). 파일 본문 DB 저장 금지·캐시 정책은 s12_s13 §17.4와 동일(프로세스 LRU, `no-store`) | 사용자 결정. ① train DOE는 `train_does.samples_rel`·`responses_rel` CSV(§5 `doe_samples`)가 이미 디스크에 있고 `GET /train-does/{id}/samples`는 페이지(≤ 200) 단위라 분석용 전체 표에 맞지 않음 |
| A5 | 영향도는 **프런트 TS 순수 함수**(PRCC·표준화 회귀계수, n ≤ 수백·p ≤ ~20) — 백엔드 numpy 불필요(s12_s13 M2와 같은 이유) | 새 의존성 없음 |
| A6 | solver vs predict 겹쳐 보기는 **파라미터 이름 집합이 같을 때만**. 다르면 비활성 + 안내 | 사용자 결정 |
| A7 | ④ 배치 결과의 분석 탭은 제거하지 않고 "⑤ 결과분석에서 열기" 링크로 대체(표·선택 run·경로 복사·단일 예측으로 열기·PBS 검증 해석은 ④에 남음) | 실행 결과 확인(④)과 분석(⑤)의 분리 + 기존 사용 흐름 보존 |

### 19.3 메뉴·번호 매핑(구 → 신)

| 구(표시) | 신(표시) | 라벨 | URL(불변) | 내부 경로(불변) |
|---|---|---|---|---|
| ① | ① | 학습데이터 생성 | `/stage/1` | `stage1_train_data` |
| ② | ② | 데이터 정리 | `/stage/2` | `stage2_*` |
| ③ | ③ | 데이터셋·모델 | `/stage/3` | `stage3_*` |
| ④ | ④ | **예측**(기존 "단일 예측"에서 개명 — 단일·일괄·준비된 입력) | `/stage/4`(`…/batch/:batchId` 유지) | `stage4_predict` |
| — | **⑤** | **결과분석**(신설) | **신규 `/stage/analysis`** | 프런트 전용(`stages/stageAnalysis/`) |
| ⑤ | **⑥** | **최적화**(내장·원본, §18) | `/stage/5`(`…/surrogate/:optId` 유지) | `stage5_optimize` |

- 신규 라우트 `…/s/:studyId/stage/analysis`(+ 선택 쿼리 `?source=batch&id=<batchId>` · `?source=doe&id=<doeId>`). 숫자 URL을 쓰지 않는 이유: `/stage/5`는 기존 북마크·알림 링크(`hooks/useOpenJob.ts`)·e2e가 최적화를 가리킨다. 단계 탐색(`StageStepper`)은 표시 순서 `[1,2,3,4,analysis,5]`, 번호 배지 1~6, 읽기용 이름 "⑤ 결과분석" · "⑥ 최적화".
- 작업 `stage_label`(QueuePanel·알림): `OPTIMIZE`·`SURROGATE_OPT` "⑤" → 표시만 "⑥", 나머지 불변(`STAGE_MARK`를 표시용 매핑 함수로 분리, 서버 값 불변).
- 문구 갱신(사용자 표시): "⑤ 최적화"→"⑥ 최적화"(안내·링크·토스트 문구, s12_s13 §18.10의 "⑤ 실행 목록" 등), phase3 §17.6 "④ 설계공간 지도" → ⑤. 본 문서 이후 계약의 "⑤"는 결과분석, 최적화는 "⑥"로 쓴다(s12_s13.md §18의 "⑤"는 구 번호 = 최적화).
- 알림 링크(`PREDICT_BATCH_DONE`)는 계속 ④ 배치 결과로, `SURROGATE_OPT_DONE`은 ⑥ 결과로(URL 불변).

### 19.4 결과 표 스키마(프런트 공통 타입 `ResultTable`)

```jsonc
{
  "source": "solver",                    // "solver" | "predict"
  "origin": {"kind":"train_doe","id":"doe-uuid","label":"DOE-001"},   // kind: train_doe | predict_batch ; label: 표시용(DOE-001 · B-003)
  "parameters":[{"name":"THK_1","integer":false,"min":2.0,"max":5.0,"unit":"mm"},
                {"name":"RIB_N","integer":true,"min":3,"max":8,"unit":null}],   // 순서 = 템플릿/샘플 표 순서. min·max는 모르면 null(표의 min·max로 대체)
  "responses":[{"name":"MaxStress","unit":"MPa"},{"name":"Disp","unit":"mm"}],
  "meta":{"engine_version":null,"baseline_id":null,"scene":null},          // 선택. 없으면 null (아래 규칙)
  "rows":[{"run_id":"run__00014","no":14,"state":"SUCCEEDED",
           "params":{"THK_1":2.31,"RIB_N":6},          // 출처 predict = 반영값(applied_values), solver = samples.csv 값
           "responses":{"MaxStress":151.9,"Disp":null}, // 없음·실패·비유한 = null
           "curve":null}],                              // predict 출처만(design-map 요약, §17.4 run.curve), solver는 null
  "counts":{"total":50,"usable":47,"no_response":3}
}
```
- `source = solver`: ① train DOE(해석기가 낸 값), `predict`: ④ 일괄 예측 배치(AI 예측값). `run_id` = 출처의 `run_key`(`run__00014`), `no` = doe_no/run 번호.
- 출처 id: solver = `train_does.id`·`DOE-001`(표시 번호 규칙은 기존 DOE 목록 그대로), predict = `batch_id`·`B-003`.
- 선택 메타: `engine_version`(AI 엔진 버전 문자열 — predict: 배치 모델의 등록 메타에 있으면 채움, 없으면 null), `baseline_id`(기준안 식별자 — 이번 계약은 필드만 두고 항상 null 허용), `scene`(해석 scene 이름 — 알 수 있을 때만). **메타 null이어도 분석은 동작**한다(화면은 "—").
- 파라미터 이름·단위는 solver = DOE 샘플 표 열 + 연결된 param_set(있으면) , predict = 배치의 템플릿. 응답 이름은 solver = `responses_rel` 열, predict = 템플릿 응답 정의 + `design-map`의 `resp:*`·`curve:*` 지표(§17.2)를 `responses`에 `resp:<NAME>_MAX` 형태로 펴지 않고 **원본 응답 이름만** 사용(커브 지표는 지도 색 값 선택기에서만).
- 출처 (a) 변환 규칙(프런트 `analysis/adapters/fromBatch.ts`): `GET /predict-batches/{bid}`의 run 표(`applied_values`·`responses`)·`GET …/design-map`의 `runs[].curve`로 채운다. state가 SUCCEEDED가 아니면 `responses` 전부 null.

### 19.5 API(`backend/openapi.json` 갱신 — 1개 신설)

```jsonc
// GET /train-does/{doe_id}/result-table   (로그인 member 이상, 읽기 전용)
// → 200
{"doe_id":"…","label":"DOE-001","study_id":"…","type":"LHS",              // 해석 DOE 유형(train/doe-types id). LHS 아니면 influence_ok=false
 "parameters":[{"name":"THK_1","integer":false,"min":2.0,"max":5.0,"unit":null}],   // 샘플 표 열 순서, min·max = 표의 최솟값·최댓값(템플릿 범위 모르면)
 "responses":[{"name":"MaxStress","unit":null}],                            // responses_rel 열(없으면 [])
 "meta":{"engine_version":null,"baseline_id":null,"scene":null},
 "rows":[{"run_id":"run__00014","no":14,"state":"SUCCEEDED","params":{"THK_1":2.31},"responses":{"MaxStress":151.9}}],
 "counts":{"total":50,"usable":47,"no_response":3},
 "influence_ok":true,"notes":[]}                                            // notes: 한국어 안내(예: "응답 파일이 없습니다")
```
- 읽는 곳: 기존 `doe_samples.read_samples_csv`(samples_rel·responses_rel, `resolve_in_study`로 Study 밖·링크 거부) + 각 run state는 `train_runs`(기존 행). 응답 열은 `measured`와 같은 값. **DB에는 아무것도 쓰지 않는다**(파일 본문 DB 저장 금지).
- 캐시·처리: s12_s13 §17.4와 같다 — 동기(스레드 풀), 프로세스 안 LRU(키 = 경로·mtime_ns·크기), `Cache-Control: no-store`. 프런트는 `doe.sample_status`·`doe.state`가 바뀔 때만 다시 받는다. 행 상한 `train_data.max_runs`(없으면 `predict_batch.max_runs` 200과 같은 값 재사용, 넘으면 앞 N행 + notes "앞 N행만 표시").
- 오류(전부 한국어): 401, 404 `DOE_NOT_FOUND`, 404 `SAMPLES_MISSING` "DOE 샘플 표가 없습니다"(기존 코드 재사용), 409 `DOE_NOT_READY`(`sample_status`가 `MISSING`·`PENDING`) "아직 샘플 표가 준비되지 않았습니다", 422 없음(쿼리 없음). 응답이 없는 DOE는 200 + `responses=[]` + notes(영향도·PLS 불가는 프런트가 안내).
- `influence_ok` = `type`이 LHS이고 n_usable ≥ max(5, p+2). 아니면 영향도 표는 비활성 + 사유 문구(§19.6).
- 출처 (a)는 신설 없음(§19.2 A3). 기존 `GET /predict-batches/{bid}`·`/design-map`·`/curves` 그대로.

### 19.6 분석 기능

| 기능 | 출처 | 비고 |
|---|---|---|
| 변수–응답 그래프(2D·3D) | (a)(b) | 기존 `ResponsePlot2D`·`3D`를 결과 표 입력으로 일반화 |
| 설계공간 지도(PLS 기본·PCA·평행 좌표) | (a)(b) | s12_s13 §17.5 계산 규칙 그대로(`linalg.ts` 재사용·무수정 목표). 색 값 = 응답 이름(출처 b), (a)는 §17.2 지표 전체 |
| 커브 강조·겹쳐보기 | (a) 전용 | (b)는 커브 파일이 없어 탭 숨김 |
| **영향도 표(신규)** | (b) 기본, (a) 가능(안내) | 아래 |
| 두 출처 겹쳐 보기(신규) | 둘 다 선택 | 아래 |

**영향도 표(프런트 `analysis/influence.ts`, 순수 함수, 색 값(응답) 1개마다)**
- **PRCC**(Partial Rank Correlation Coefficient): 모든 열(변수 + 응답)을 순위(동순위는 평균 순위)로 바꾸고, 변수 j마다 "나머지 변수를 통제한 순위 부분상관" = 상관행렬 R(순위 기준)의 역행렬 P에 대해 ρ_j = −P_{j,y}/√(P_jj·P_yy). 유의성은 보고하지 않는다(값만, 정렬은 |ρ| 내림차순). 행렬 특이(공선·n 부족)면 해당 열 "계산 불가".
- **표준화 회귀계수(SRC)**: 변수·응답을 z-점수(ddof=1)로 표준화한 OLS(절편 포함) 계수 β_j. 추가로 R²를 한 줄로 표기(R² < 0.7이면 회색 "선형 근사가 약합니다 — PRCC·지도를 함께 보세요").
- 표 열: `변수 | PRCC | SRC | |PRCC| 막대`. 같은 변수에서 PRCC와 SRC 부호가 다르면 ⚠ 아이콘 없이 회색 "부호 불일치" 한 줄(필수만).
- 사용 가능 조건: `influence_ok`(출처 b) 또는 (a)에서 유효 run ≥ max(5, p+2). 출처 (a)가 LHS 배치(`source.kind:"lhs"`)가 아니면 "LHS가 아닌 표 — 참고용" 회색 안내. **LHS가 아닌 해석 DOE(FullFact·Sobol 등)는 영향도 비활성** + "영향도는 LHS DOE에서만 제공합니다".
- **비범위**: 대리모델 기반 Sobol 지수(⑥ 또는 후속 계약에서). 계약 문서에 "후속"만 기록, UI에 자리 두지 않음.

**두 출처 겹쳐 보기**
- 출처 슬롯 2개 `기본`·`비교`(비교 선택 사항). 같은 Study의 DOE 목록(READY)·완료 배치 목록 드롭다운. 두 표의 **파라미터 이름 집합이 같을 때만** 활성(이름 대소문자 구분, 순서 무관). 다르면 "파라미터 이름이 달라 겹쳐 볼 수 없습니다 — 다른 쪽에만 있음: X, Y" 회색 + 비교 슬롯 비활성.
- 겹침 표시: 변수–응답 2D 그래프에서 solver = 속 빈 원, predict = 채운 점(범례 2개), 설계공간 지도·평행 좌표는 점 모양·선 스타일로 구분(색 = 값, 같은 색 막대 범위 = 두 표 합집합). 같은 응답 이름이 양쪽에 있을 때만 응답 선택 가능(공통 응답 0이면 비활성 + 안내). 영향도 표는 겹치지 않고 슬롯별 두 표 나란히(선택 사항, 필수 아님).
- 두 출처 모두 `meta`가 있으면 머리 칩에 `engine_version`·`baseline_id`·`scene`을 그대로 표시(둘이 다르면 회색 "메타 다름" 한 줄).

### 19.7 화면(⑤ 결과분석, 필수 UI만)

- 머리: 출처 세그먼트 `일괄 예측 결과(예측)` | `해석 DOE 결과(해석)` + 출처 드롭다운(라벨·run 수·날짜) + `비교 추가`(§19.6). 마지막 선택은 localStorage `physicsai.analysis.source`(try/catch). 쿼리가 있으면 쿼리 우선.
- 본문 탭: `변수–응답` · `설계공간 지도` · `영향도` · `커브`(출처 a만). 결과 표(행 선택·열 선택 = s12_s13 §14.8·§17.6 선택 모델 `selected = run no`)를 왼쪽 칸, 탭 그래프를 오른쪽 칸(④ 배치 결과의 레이아웃 그대로 이동). 상태가 없으면 빈 상태 안내 "④에서 일괄 예측을 실행하거나 ①에서 해석 DOE 결과를 만드세요".
- ④ 배치 결과: 그래프 카드 → "분석은 ⑤ 결과분석에서 보세요" 링크 카드(`/stage/analysis?source=batch&id=<batchId>`)로 교체.

### 19.8 프런트 변경 목록(파일 경로 수준, Impl-Frontend 소유)

| 구분 | 파일 |
|---|---|
| 메뉴·라벨·표시 번호 | `frontend/src/lib/format.ts`(`STAGES`: n·path·name, 표시 순서·번호·라벨, `STAGE_MARK` → `stageMark(job)` 표시 매핑), `frontend/src/shell/StageStepper.tsx`(6버튼·배지 1~6), `frontend/src/styles/shell.css`·`design/tokens.css`(5등분 → 6등분·최소 폭), `frontend/src/panels/QueuePanel.tsx`(`stage_label` 표시 매핑), `frontend/src/mock/catalog.ts`(표시 라벨, 서버 값 불변) |
| 라우팅 | `frontend/src/app/App.tsx`(`/stage/analysis` 라우트), `frontend/src/pages/StudyPage.tsx`(stage 검증에 `analysis` 허용·단계명 조회 변경) |
| ⑤ 화면(새) | `frontend/src/stages/stageAnalysis/{StageAnalysis.tsx, SourcePicker.tsx, AnalysisTabs.tsx, CompareSlot.tsx}`, `frontend/src/analysis/{resultTable.ts(타입), adapters/{fromBatch.ts, fromDoe.ts}, influence.ts(PRCC·SRC), compare.ts(이름 집합 판정·합집합 범위)}`, `frontend/src/api/analysis.ts`(타입+`getDoeResultTable`; `api/index.ts`·`endpoints.ts` 손대지 않음), `frontend/src/styles/analysis.css` |
| 분석 컴포넌트 이동 | `frontend/src/stages/stage4/batch/{BatchGraphTabs.tsx, CurveOverlay.tsx, ResponsePlot2D.tsx, ResponsePlot3D.tsx, designMap/*}` → `frontend/src/analysis/viz/*`(입력을 `ResultTable`로 일반화; 이동 후 import 갱신, 계산 규칙·`linalg.ts` 무수정). `BatchResult.tsx`는 그래프 카드 대신 ⑤ 링크 카드(+ 300줄 규칙 분할 후속 가능) |
| ⑥(구 ⑤) 문구 | `frontend/src/stages/stage5/{Stage5.tsx, OptModeTabs.tsx, surrogate/*}`의 "⑤"·"④ 일괄 예측…" 문구, `frontend/src/hooks/useOpenJob.ts`(링크 불변 확인) |
| ④ 문구 | `frontend/src/stages/stage4/Stage4.tsx`·`InputModeTabs.tsx`("단일 예측" → "예측") |
| 목·시험 | `frontend/src/mock/{predictBatch.ts, trainDoe.ts(또는 stage1.ts)}`(result-table 목 라우트), `frontend/src/__tests__/{tone.test.tsx(단계 6개), analysis*.test.tsx, fixtures/influenceGolden.json}` + 이동한 designMap 시험 import 갱신 |
| 생성 파일 | `frontend/src/api/generated/schema.d.ts`(`npm run gen:api`), `frontend-dist/**`(`scripts/build-frontend-dist` — 프런트 변경 커밋과 함께) |

백엔드(Impl-Backend 소유): `backend/physicsai_api/routers/train.py`(GET `/train-does/{doe_id}/result-table` 1개), `backend/physicsai_api/services/stage1_train_data.py`(또는 새 `services/doe_result_table.py`), `backend/physicsai_api/schemas/stage1_train_data.py`(`DoeResultTable` 모델), `backend/tests/test_doe_result_table_api.py`, `backend/openapi.json`, `backend/tests/common/test_openapi.py`·`backend/tests/data/operation_ids.txt`(라우트·operationId 스냅샷).

### 19.9 시험(V3-S14-*, 서버 확인은 E5A-*)

기존 e2e 번호(E4-*, E5-* 등)는 의미·번호 모두 유지(E5-5 "①②⑤ 스텝 클릭" 등 옛 문구는 표시 번호만 읽는 방식으로 두고 새 번호 체계로 고치지 않는다). 신규는 **`E5A-*`**(결과분석 = 표시 ⑤, 내부 번호와 구분하려고 A 접미).

| ID | 기준 |
|---|---|
| V3-S14-1 | API `result-table`: 모양(§19.5), 샘플 표만(응답 없음)·응답 있음·실패 run null·부분 PARSED, 행 상한 notes, `influence_ok`(LHS 여부·n 조건), 오류 404 `DOE_NOT_FOUND`·`SAMPLES_MISSING`·409 `DOE_NOT_READY`, 권한(401·member 200), Study 밖 경로·링크 거부, **DB 쓰기 없음**(트랜잭션 행 수 불변), LRU(같은 파일 두 번 읽지 않음·mtime 변경 시 다시), `no-store`, openapi·타입 재생성 |
| V3-S14-2 | `influence.ts` 골든(고정 자료 numpy·scipy 참조값 JSON 픽스처, 허용 1e-6): PRCC(동순위 평균 순위), SRC·R², 특이 행렬 "계산 불가", n < p+2 비활성 |
| V3-S14-3 | 메뉴: 6버튼 순서·번호 배지 1~6·읽기용 이름("⑤ 결과분석"·"⑥ 최적화"), URL `/stage/4`·`/stage/5` 불변 + `/stage/analysis`, `stage_label` 표시 매핑(서버 값 ⑤ → 표시 ⑥, 서버 값 불변), 알림 링크 유지(`PREDICT_BATCH_DONE`→④ 배치, `SURROGATE_OPT_DONE`→⑥ 결과), 좁은 화면 스텝퍼 가로 스크롤 규칙 유지 |
| V3-S14-4 | 어댑터: `fromBatch`(applied_values·실패 run null·curve 요약), `fromDoe`(solver), 메타 null 허용, 두 출처 같은 `ResultTable` 모양 |
| V3-S14-5 | 화면: 출처 전환·저장, 빈 상태 문구, 탭(커브는 출처 b에서 숨김), 영향도 비활성 문구(비 LHS·n 부족), 이동한 변수–응답·설계공간 지도·커브 겹쳐보기 기존 시험(V3-S12-3~5)이 입력만 바꿔 **그대로 통과**, ④ 배치 결과의 ⑤ 링크 카드 |
| V3-S14-6 | 겹쳐 보기: 이름 집합 같음(순서 무관) 활성·다름 비활성 + 차이 이름 안내·공통 응답 0 비활성·범례(속 빈/채운)·색 막대 합집합 범위·메타 다름 한 줄 |
| V3-S14-7 | 회귀: `scripts/test-all` 전체 통과, 기존 e2e 번호·내부 경로(`stage4_predict`·`stage5_optimize`)·job_type·migration head 불변 |

서버 확인(사용자, E5A):

| ID | 확인 |
|---|---|
| E5A-1 | 메뉴 ①~⑥ 순서·라벨, ④ 예측·⑥ 최적화 기존 흐름 회귀(작업 대기열 "⑥" 표시) |
| E5A-2 | 완료된 일괄 예측 배치를 ⑤에서 열어 설계공간 지도·변수–응답·커브 겹쳐보기가 ④에서 보던 것과 같은 값 |
| E5A-3 | 실제 해석 DOE(LHS, 응답 있음)를 ⑤에서 열어 결과 표 값이 ① samples/responses와 일치, 영향도(PRCC·SRC)가 표시되고 부호·순위가 상식과 맞음, 200 run 첫 로드 시간 |
| E5A-4 | 같은 템플릿의 해석 DOE + 예측 배치를 겹쳐 보기(solver vs predict), 이름이 다른 쌍은 비활성 안내 |
| E5A-5 | 비 LHS DOE에서 영향도 비활성, 응답 없는 DOE에서 안내 |

### 19.10 역할 분담

| 역할 | 일 |
|---|---|
| Impl-Backend | `result-table` API(§19.5)·시험 V3-S14-1·openapi 갱신. 새 의존성·migration 없음 |
| Impl-Frontend | §19.8 전부(메뉴·라우트·⑤ 화면·분석 컴포넌트 이동·영향도·겹쳐 보기·문구)·시험 V3-S14-2~6·타입 재생성·`frontend-dist/` 재생성. **순서**: Backend openapi가 병합되기 전에는 목 라우트로 진행, `gen:api`는 Backend 병합 후 1회 |
| Verifier | V3-S14-1~7 판정 + 기존 V3-S12·S13·REG 회귀(수정 없음), 이동한 컴포넌트가 계산 규칙을 바꾸지 않았는지 골든 대조 |
| Plan | 변경 메모 요청 수신·phase3.md 반영·E5A 체크리스트 `docs/e2e-checklist.md` 추가 |

Backend·Frontend는 겹치는 파일이 없어 병렬 가능(API 모양은 이 문서 §19.5로 고정). 생성 파일(`openapi.json`·`schema.d.ts`·`frontend-dist/**`)은 Backend 먼저 병합 → Frontend가 그 위에서 재생성.

### 19.11 리스크

- **번호 이중 체계**: 표시 ⑤(결과분석)·⑥(최적화) vs URL/코드의 5(최적화). 혼동 방지: URL·코드 주석은 "내부 5 = 표시 ⑥"을 명시, 문서는 이 절 이후 표시 번호 기준. 기존 문서·매뉴얼의 "⑤ 최적화" 표기가 남을 수 있음(매뉴얼 갱신은 Plan 후속).
- **스텝퍼 폭**: 6버튼은 5등분보다 좁아 최소 폭(170px) 규칙에서 가로 스크롤 한계가 커진다(D3-56). 라벨 길이 확인 필요.
- **분석 컴포넌트 이동**: s12 시험·스크린샷 스크립트(`frontend/scripts/screenshots.mjs`) 경로 변경. 계산 코드는 무수정 이동으로 한정(회귀 위험 최소화).
- **PRCC 해석**: 표본 수가 작거나 LHS가 아니면 신뢰 낮음 — 값만 보이고 유의성 없음. SRC는 비선형 응답에서 R² 낮음.
- 해석 DOE 응답 열 단위·템플릿 범위가 없을 수 있음(단위 null, min·max는 표 값).

### 19.12 미결(사용자 확인 대상)

1. 신규 라우트를 `/stage/analysis`로 했다(숫자 URL 충돌 회피). 숫자 URL로 맞추려면 `/stage/5` 의미 변경 + 기존 링크·북마크 이전이 필요 — 이대로 둘지.
2. `engine_version`·`baseline_id`·`scene`의 **실제 출처**: 현재 DB·파일에 대응하는 확정 필드가 없다(전부 null 허용으로 시작). 어떤 값을 채울지·어디서 올지 후속 결정.
3. 출처 (a) 배치 결과 표의 영향도 허용 여부(LHS 아님 → 참고용 안내로 허용)와 ④ 배치 결과의 분석 탭을 링크로 완전히 대체할지(현 계약은 대체).
4. 해석 DOE 응답 값의 의미: `responses_rel`이 ① 해석 후 추출 응답인지(예: H3D 최대) — 현 코드 기준 `measured`와 동일하게 취급. 단위 표시 규칙 확인 필요.
5. 영향도 후속(대리모델 Sobol)을 ⑥에 둘지 ⑤ 확장으로 둘지.

## 변경 메모(이 문서분 — phase3.md 변경 메모 목록으로 옮김)

- **D3-62 (사용자 결정 2026-10-17, S14 화면 단계 재편·⑤ 결과분석 — Plan)**: §19. ① 화면 단계 ④ 예측 · ⑤ 결과분석(신설) · ⑥ 최적화(기존 ⑤), ①~③ 불변. 내부 코드 경로·job 이름·DB·URL 숫자·e2e 기존 번호는 유지하고 메뉴 순서·표시 번호·라벨만 프런트에서 변경(신규 라우트 `/stage/analysis`). ② ⑤ 입력 = 결과 표(run_id·파라미터·응답·source solver|predict·출처 id·선택 메타). 출처 (a) 기존 일괄 예측 배치(s12 분석 기능을 ④→⑤ 이동, 기존 API 재사용), (b) 해석 DOE 결과(새 읽기 전용 API `GET /train-does/{doe_id}/result-table`, 파일 본문 DB 저장 금지, 캐시는 §17.4와 같음). ③ 분석 = PLS·PCA·커브 강조 재사용 + 영향도 표(해석 DOE LHS의 PRCC·표준화 회귀계수), 대리모델 Sobol은 비범위. ④ solver vs predict 겹쳐 보기는 파라미터 이름 집합이 같을 때만. ⑤ 시험 V3-S14-*, 서버 확인 E5A-*(기존 번호 유지).
