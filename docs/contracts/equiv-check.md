# 계약: ⑤ 결과분석 — 해석 등가성 판정(레시피·이력) — equiv-check

작성: Plan, 2026-10-20. 기준: 브랜치 `feat/r1-equiv` 9059beb(phase3 S19까지 + native 형상 엔진·형상 뷰 계약).
우선순위: **이 문서 > [phase3.md](phase3.md) §19(S14 ⑤ 결과분석)·§21(S16 FEM 검증)·§22(S17 성능 정의)**. 형상 엔진 현장 검증은 [geometry-engine.md](geometry-engine.md) §10을 따른다.
ID 규칙: 결정 `EQ-n`, 시험 `V-EQ-n`, 변경 메모 `EQ-Cn`.

## 0. 사용자 결정(2026-10-20)

1. 해석 등가성 판정의 **허용오차는 시스템이 기본값을 제안하되, 사용자가 정의하고 "레시피"로 저장·불러오기**한다.
2. 판정 결과는 **이력**으로 남겨 나중에 참고한다(이력에서 그때 쓴 레시피를 다시 불러올 수 있어야 한다).

## 1. 용도·범위

- **용도**: 두 결과 집합 A(기준)·B(비교)를 쌍으로 맞춰 지표별 차이를 허용오차로 판정하고 종합 판정(통과·미달·판정 불가)을 낸다.
- **1차 대상**: 같은 형상의 기준 해석(SimLab/altair 메시) 대 native(모핑 메시) 해석 — geometry-engine.md §10.2 "Radioss 응답 동등"(현장 인수)과 native-rollout 현장 검증 (c) 항목이 이 기능으로 판정한다.
- **일반화**: 같은 기능으로 해석 대 해석, 해석 대 예측, 예측 대 예측도 비교한다(출처 종류만 다름).
- **비범위**: 자동 허용오차 산정(통계적 공차 설계), 판정 결과로 다른 작업을 자동 차단·승인하는 게이트, 결과 파일 반출, 단위 자동 환산.

### 1.1 기존 기능 재사용(코드·계약 확인)

| 필요 | 재사용 대상 | 근거 |
|---|---|---|
| 결과 집합 표 | ⑤ `ResultTable`(source `solver`\|`predict`), `GET /train-does/{id}/result-table`, `GET /predict-batches/{bid}`·`design-map`·`curves` | phase3 §19 A2~A4 |
| 스칼라 지표 정의 | **성능 정의** `param_sets.responses` 행 `{name, unit, spec}`(H3D `NAME\|SUBCASE\|DATATYPE\|COMPONENT\|LAYER`+stat, CURVE `{series, stat}`), 값 계산 `stage4_predict/performance.py` `perf_value`, 사유 코드 `SPEC_CHANGED`·`NOT_EXTRACTED`·`NO_VALUE`·`NO_CURVE`·`SERIES_MISSING` | phase3 §22 P1·P3·P4 |
| H3D 값 추출 | `response_tcl.extract_in_folder`(`H3D_REQUESTS.txt` → `RESPONSES.txt`), 같은 요청이면 기존 `RESPONSES.txt` 재사용 | phase3 §14.6, §21.3.6 |
| 해석 run 응답 | ①-6 `TD_RESP_EXTRACT`(`R(run)/responses_run.csv`, `D/run_responses.csv` = `responses_rel`) | phase2 §6.6.1 |
| 곡선 | 예측 `curve.json`(CURVE_PICK), 해석 T01 = 템플릿 `t01_curve_export` + `xydata` 파서, 계열 짝짓기(정확 → 대소문자·공백 무시) | phase2 §6.10, phase3 §21.3.6 FV_CURVE |
| 비교 식 | FEM 검증 `diff_pct = diff/\|ref\|×100`, `\|ref\| ≤ zero_tol`이면 null "기준값 0" | phase3 §21.3.6 |
| 겹쳐 보기 | ⑤ 두 출처 겹쳐 보기(파라미터 이름 집합 같을 때만) | phase3 §19 A6 |

**기존 "레시피" 개념은 없다**(docs 전체 검색 0건). 가장 가까운 선례는 S17 최적화 `settings.performances`(참조 성능 정의 스냅숏)이며, 이 계약의 이력 스냅숏도 같은 방식이다.

## 2. 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| EQ-1 | **지표 원천 = 기존 성능 정의·추출 경로**. 레시피 지표는 `perf:<NAME>` 참조(Study 템플릿의 성능 정의로 해석) 또는 같은 문법의 인라인 spec(H3D·CURVE)만 쓴다. 새 원천은 곡선 상관(`curve_corr`)과 메시 부피(`mesh_volume`) 2종뿐 | 정의 이중화 방지, `perf_value` 공용 |
| EQ-2 | 레시피 = 지표 목록 + 지표별 허용오차 + 필수/참고 + 쌍 집계 규칙 + 종합 규칙. **시스템 기본(읽기 전용, 설정 한 곳)** + **사용자 레시피(DB, 버전 증가·소프트 삭제)** | 사용자 결정 1 |
| EQ-3 | 범위 `study`(그 Study에서만) \| `global`(모든 Study에서 보임). 레시피에는 정의·수치만 있고 결과 데이터는 없다 | 사용자 결정 |
| EQ-4 | 판정은 새 job `EQ_CHECK` 1종으로만 실행(값이 모두 있어도 job — 이력 생성 경로 단일화). 없는 값만 추출 | 이력 일관성 |
| EQ-5 | **이력 = DB `eq_checks` 행 + 폴더**. 행에 레시피 스냅숏 전체(해석된 binding 포함)·버전·대상·종합 판정·지표별 집계 수치. 쌍×지표 값과 곡선은 파일 | AGENTS "DB에는 경로·상태·수치 요약만" |
| EQ-6 | 원본 run 폴더·SPDM에는 쓰지 않는다. 추출은 판정 폴더 `E/extract/` 안에서만 | AGENTS SPDM 보호, FV 선례 |
| EQ-7 | 판정은 **A를 기준**으로 한다(차이 = B − A, 상대 = 차이/\|A\|) | FEM 검증 식과 같은 방향(기준 = 해석) |

## 3. 레시피

### 3.1 모양(JSON, DB `eq_recipes.definition`과 이력 스냅숏 공통)

```jsonc
{"schema_version": 1,
 "metrics": [
  {"id": "accel_peak", "label": "가속도 피크", "kind": "scalar",
   "source": {"type": "perf", "perf": "ACC_T01"},          // 또는 {"type":"h3d", name, subcase, datatype, component, layer, stat}
                                                            //      {"type":"curve", series, stat, t01?:{type,request,component}}
                                                            //      null = "연결 필요"(시스템 기본의 빈 슬롯)
   "tol": {"rel_pct": 5.0, "abs": null}, "required": true},
  {"id": "accel_corr", "label": "가속도 곡선 상관", "kind": "curve_corr",
   "source": {"type": "curve", "series": null, "t01": null}, "tol": {"corr_min": 0.95}, "required": true},
  {"id": "volume_diff", "label": "쿠션 부피 차", "kind": "mesh_volume",
   "source": {"type": "mesh_volume", "parts": "cushion"}, "tol": {"rel_pct": 0.1}, "required": true}],
 "pair_rule": {"mode": "all"},                               // all | min_ratio(+ "ratio": 0.9)
 "verdict_rule": "required_all"}                             // 1차는 이것만(필수 전부 통과)
```

- `id` ASCII `^[a-z][a-z0-9_]{0,31}$`(레시피 안 유일), `label` 한국어 ≤ 40자, 지표 수 ≤ `equiv_check.max_metrics`(20).
- `kind`: `scalar`(H3D·CURVE stat 값) \| `curve_corr`(시간 곡선 Pearson r) \| `mesh_volume`(쿠션 메시 부피). `curve_nrmse`(NRMSE %, 하한 없음·상한 `nrmse_max_pct`)는 선택 지표로 둔다(기본 레시피에는 없음).
- `tol`: `scalar`·`mesh_volume`은 `rel_pct`·`abs` 중 하나 이상(둘 다 있으면 **어느 하나 만족이면 통과** — 기준값이 0 근처일 때 abs가 보호), `curve_corr`은 `corr_min`(0~1), `curve_nrmse`는 `nrmse_max_pct`. 음수·NaN은 `TOL_INVALID`.
- `source.type = "perf"`는 실행 시 **양쪽 결과 집합 템플릿의 같은 이름 성능 정의**로 해석한다. 두 쪽 spec이 다르면 경고 `EQ_SPEC_DIFFERS`(비차단), 단위가 다르면 경고 `EQ_UNIT_DIFFERS`(환산 안 함). 한쪽에 없으면 그 지표 `NA`(사유 `PERF_UNDEFINED`).
- `curve`의 `t01`은 해석 쪽 T01 추출 요청. null이면 FV_CURVE 규칙 ①②(모델 데이터셋 큐레이션 → Study 최신 `CU_T01_CURVES` params)로 정한다. `series` null = 첫 계열(S17 CURVE 규칙).
- `mesh_volume`의 `parts`: `"cushion"`(템플릿 `cushion_part_ids`) 또는 part id 목록.

### 3.2 시스템 기본 레시피(제안값, 읽기 전용)

설정 `equiv_check.system_recipe`(기본값은 설정 스키마 한 곳, 관리자만 변경, `system_version` 정수)로 둔다. 키 `sys:default`. 모델마다 응답 이름이 달라 **source는 비어 있고(연결 필요)** 실행 화면에서 성능 정의를 연결한다.

| id | 지표 | kind | 허용오차 | 구분(제안) |
|---|---|---|---|---|
| `accel_peak` | 가속도 피크 | scalar | rel 5% | 필수 |
| `cushion_deform` | 쿠션 최대 변형 | scalar | rel 5% | 필수 |
| `ie_max` | 내부 에너지 최대 | scalar | rel 5% | 필수 |
| `ke_max` | 운동 에너지 최대 | scalar | rel 5% | 필수 |
| `stress_peak` | 응력 피크 | scalar | rel 10% | 참고(메시 민감 — 미결 Q2) |
| `contact_peak` | 접촉력 피크 | scalar | rel 10% | 참고(미결 Q2) |
| `accel_corr` | 가속도 곡선 상관 | curve_corr | r ≥ 0.95 | 필수 |
| `volume_diff` | 쿠션 부피 차 | mesh_volume | rel 0.1% | 필수 |

geometry-engine.md §10.2의 제안 기준(피크 5%·NRMSE 5%·dt 10%)은 이 기본 레시피로 대체한다(NRMSE는 선택 지표 `curve_nrmse`로 추가 가능).

### 3.3 사용자 레시피 생명주기

- **복제**: 시스템 기본·다른 레시피·이력 스냅숏에서 복제 → 새 `recipe_key`, `version` 1, `parent`(원본 key·version) 기록.
- **편집**: 같은 `recipe_key`에 `version + 1` 새 행(이전 버전 행은 불변). 요청에 `base_version` 필수, 최신과 다르면 409 `EQ_RECIPE_VERSION_CONFLICT`.
- **이름·설명**: 이름 ≤ 60자, 설명 ≤ 500자. 활성 레시피 중 같은 범위(같은 Study 또는 global)에서 이름 중복 409 `EQ_RECIPE_NAME_TAKEN`.
- **삭제 = 소프트 삭제**: key 단위로 `deleted_at`·`deleted_by` 기록, 목록·선택에서 숨김. 이력의 스냅숏·참조는 그대로(이력 화면은 "삭제된 레시피" 표시). 되살리기는 관리자 API만(`POST …/restore`).
- **불러오기 후 1회 사용**: 편집 내용을 저장하지 않고 실행 가능(`adhoc`) — 이력에는 원본 key·version + `modified: true` + 스냅숏 전체가 남는다.
- **권한**: 읽기 = Study 멤버(global은 로그인 사용자 전부). 생성·편집·삭제 = `power` 이상, global의 편집·삭제는 작성자 또는 `admin`. 시스템 기본은 수정·삭제 불가 409 `EQ_RECIPE_READONLY`.

## 4. 판정 실행

### 4.1 결과 집합(side) 종류

| kind | 참조 | run 단위·이름 | 응답·곡선 위치 |
|---|---|---|---|
| `train_doe` | `doe_id` | `train_runs`(run_key) | `R(run)` h3d·T01, `responses_run.csv` |
| `predict_batch` | `batch_id` | 배치 run(run 번호) | `P/RESULT/RESPONSES.txt`·`curve.json` |
| `fem_verify` | `fv_id`(+시도) | 1 run | `F/a<n>/result` h3d·T01 |
| `folder` | 경로 목록(허용 루트 + `storage.spdm_roots` 읽기만, 링크 거부) | 폴더 1개 = run 1개(이름 = 폴더 이름) | 폴더 직계 `*.h3d`·`*T01` 정확히 1개, 선택 `params.json` |

`folder`는 geometry-engine §10.2처럼 플랫폼 밖에서 돌린 SimLab 메시·native 메시 해석 결과를 그대로 비교하기 위한 출처다(읽기만, 사본은 판정 폴더에).

### 4.2 쌍 매칭(`pairing.mode`)

- `by_name`(기본): run 이름 정확 일치 → 대소문자 무시.
- `by_params`: 두 쪽 파라미터 이름 집합이 같을 때만(다르면 problems `PARAM_SET_MISMATCH` + 차이 이름 — ⑤ A6과 같은 규칙). 연속 값은 상대 `equiv_check.param_match_rel_tol`(1e-6, 0이면 절대 1e-12) 이내, 정수·범주는 정확 일치. 한 점에 여러 run이면 가장 작은 번호 1개.
- `manual`: `[{a, b}]` 목록.
- 쌍 수 1 ≤ n ≤ `equiv_check.max_pairs`(200). 짝 없는 run은 `unmatched_a`·`unmatched_b`(이름만)로 보여 주고 판정에서 뺀다. 성공(SUCCEEDED·COLLECTED)이 아닌 run의 쌍은 모든 지표 `NA`(사유 `RUN_NOT_SUCCEEDED`).

### 4.3 지표 계산

- **scalar**: 값 = `perf_value`(H3D·CURVE, stat 적용). diff = B − A, rel_pct = diff/\|A\|×100(\|A\| ≤ `zero_tol` 1e-12면 null). 통과 = (rel_pct ≤ tol.rel_pct) 또는 (\|diff\| ≤ tol.abs)(주어진 것만). 둘 다 계산 불가면 `NA`.
- **curve_corr / curve_nrmse**: 두 곡선의 공통 시간 구간 [max(t0), min(t_end)]을 `equiv_check.curve_points`(1000)점 균일 격자로 선형 보간 → Pearson r(분산 0이면 `NA` "평탄 곡선"), NRMSE = RMS(B−A)/(max(A)−min(A))×100. 공통 구간이 짧은 쪽 길이의 `equiv_check.curve_min_overlap`(0.9) 미만이면 경고 `EQ_CURVE_SHORT_OVERLAP`. 계열 짝이 없으면 `NA`(`SERIES_MISSING`).
- **mesh_volume**: run 입력 메시 include에서 대상 part 솔리드 요소 부피 합(tetra4·tetra10은 꼭짓점 4개 사면체, hexa8은 사면체 5분할; 그 밖 요소형은 경고 `EQ_VOLUME_ELEM_SKIPPED`). 해석 쪽 = run 입력 폴더(`input_rel`/m_3 또는 native `104_*.inc`), 예측 쪽 = 예측 입력 메시. 없으면 `NA`(`MESH_MISSING`). 판정 식은 scalar와 같다.
- 지표 상태: `PASS` \| `FAIL` \| `NA`(사유 코드). 사유 문구는 기존 `REASON_TEXT`에 추가(한국어).

### 4.4 집계·종합 판정

- **지표 집계(쌍 전체)**: `pair_rule.mode = all` → 모든 판정 가능 쌍 PASS면 PASS, 하나라도 FAIL이면 FAIL; `min_ratio` → PASS 쌍 비율 ≥ ratio면 PASS. 판정 가능 쌍이 0이면 `NA`. 판정 가능 쌍 중 일부가 `NA`면 경고 `EQ_PARTIAL_PAIRS`.
- **종합**(`required_all`): 필수 지표 하나라도 FAIL → **미달(FAIL)**, 필수 전부 PASS → **통과(PASS)**, 그 밖(필수 중 NA 존재) → **판정 불가(INCOMPLETE)**. 참고 지표는 종합에 영향 없음(결과에 "참고 미달 n" 표시).
- 집계 수치(지표마다): `n_pairs`, `n_pass`, `n_fail`, `n_na`, `a_mean`, `b_mean`, `max_abs_rel_pct`, `max_abs_diff`, `min_corr`(curve 종류), `worst_pair`(이름).

### 4.5 job `EQ_CHECK`

stage 4(표시 "⑤ 결과분석", phase3 A1 매핑 규칙), lane SLOT(HyperView·T01 추출 라이선스), 알림 `EQ_CHECK_DONE`("등가성 판정 EQ-003 통과 — 필수 6/6 · 참고 미달 1 · 쌍 12").

| step | kind(무게) | 처리 |
|---|---|---|
| EQ_PREP | INTERNAL 5 | 대상 재확인, 쌍 확정, binding 해석, 스냅숏 `recipe.json`·`pairs.json` 작성, 필요한 추출 목록 계산 |
| EQ_EXTRACT | LOCAL 60 | 없는 값만: H3D = `response_tcl.extract_in_folder`(작업 폴더 `E/extract/<side>/<run>/`, 원본 h3d는 사본 — 합계 > `equiv_check.max_extract_copy_bytes`(20 GiB)면 EQ_PREP에서 실패 `EQ_EXTRACT_TOO_LARGE` + 안내 "①-6 run 응답 추출 또는 ④ 성능 다시 추출을 먼저 실행하면 사본 없이 재사용합니다"), T01 = `t01_curve_export` 1회 호출(입력은 원본 경로 읽기, 출력만 `E/extract/`). 추출 실패는 그 값 `NA` + 경고 1건. 추출할 것이 없으면 SKIPPED |
| EQ_COMPUTE | INTERNAL 30 | 지표 계산(§4.3), `metrics.csv`, `curves/<pair_no>/<metric_id>.json`(보간 A·B, ≤ 1000점) |
| EQ_REPORT | INTERNAL 5 | 집계·종합(§4.4), `result.json`, `eq_checks.summary`·`verdict` 기록 |

- 재사용 규칙(추출 생략): 예측 `RESPONSES.txt`는 같은 폴더 `H3D_REQUESTS.txt`가 같은 요청일 때(S16 규칙), 해석 `responses_run.csv`는 `D/responses.json`의 같은 이름 spec이 일치할 때, 곡선은 예측 `curve.json`. 그 밖은 추출.
- 동시 실행: Study당 활성 `equiv_check.max_active`(2), 초과 409 `EQ_CHECK_LIMIT`. 취소는 기존 `/jobs/{id}/cancel`(상태 CANCELED, 이력 행은 남음). 재시도는 기존 작업 재시도(같은 스냅숏, 폴더 `_backup` 후 다시).

## 5. 저장

### 5.1 DB — migration `00NN_equiv_check`(번호는 **구현 시 HEAD 다음**, 이 문서 작성 시 예상 0018)

**`eq_recipes`**(버전마다 1행): `id` UUID PK · `recipe_key` UUID(버전 묶음) · `version` INT · `scope` `study`\|`global` CHECK · `study_id` FK NULL(scope=study면 NOT NULL CHECK) · `name` · `description` · `definition` JSONB(§3.1, 정의·수치만) · `parent_key`·`parent_version` NULL · `created_by`·`created_at` · `deleted_at`·`deleted_by` NULL. UNIQUE(`recipe_key`, `version`). 활성 이름 유일은 부분 인덱스(scope·study_id·lower(name), `deleted_at IS NULL`, 최신 버전만 — 서비스 층에서 최신 판정).

**`eq_checks`**(판정 이력, 추가만): `id` UUID PK · `study_id` FK · `eq_no` INT(Study별 `EQ-001`) · `job_id` FK · `recipe_key`·`recipe_version` NULL(adhoc 신규는 NULL) · `recipe_source` `system`\|`user`\|`adhoc` · `modified` BOOL · `recipe_snapshot` JSONB(§3.1 + 해석된 binding·양쪽 spec·시스템 기본이면 `system_version`) · `side_a`·`side_b` JSONB(`{kind, ref, label}`) · `pairing` JSONB(`{mode, n_pairs, n_unmatched_a, n_unmatched_b}`) · `status` `RUNNING`\|`DONE`\|`FAILED`\|`CANCELED` · `verdict` `PASS`\|`FAIL`\|`INCOMPLETE` NULL · `summary` JSONB(§4.4 지표별 집계 수치·경고 수만) · `note` TEXT NULL(≤ 500자, 사용자 메모 — 유일하게 사후 수정 가능) · `dir_rel` · `created_by`·`created_at`·`finished_at`. 이력 행은 삭제 API 없음(Study 보관·정리 규칙을 따름).

downgrade는 두 테이블에 행이 없을 때만(있으면 거부 — 데이터 보존, S17 0014 선례).

### 5.2 파일 — `E = <study>/{equiv_check.dir_name}/EQ-NNN/`(기본 `05_equiv`)

`recipe.json`(스냅숏) · `pairs.json`(쌍·미매칭) · `metrics.csv`(`pair_no,a_run,b_run,metric_id,a,b,diff,rel_pct,corr,status,reason`) · `curves/<pair_no>/<metric_id>.json` · `extract/<a|b>/<run>/`(추출 작업 폴더) · `result.json`. 사용자 산출물 규칙(삭제 대신 `_backup`)을 따르고 S3 용량 화면에서는 `05_equiv` 폴더 합계로 보인다(정리 범주 추가는 비범위).

### 5.3 설정 `equiv_check`(기본값은 설정 스키마 한 곳)

`enabled` true · `dir_name` `05_equiv` · `max_pairs` 200 · `max_metrics` 20 · `max_active` 2 · `curve_points` 1000 · `curve_min_overlap` 0.9 · `zero_tol` 1e-12 · `param_match_rel_tol` 1e-6 · `max_extract_copy_bytes` 20 GiB · `system_recipe`(§3.2, `system_version` 1). `/status.features.equiv_check`(항상 사용 가능) · `equiv_check_extract`(hw·`curate_hg_tcl` 자원 있을 때 — 없으면 추출이 필요한 지표만 `NA` + 경고 `EQ_EXTRACT_UNAVAILABLE`).

## 6. API(`backend/openapi.json` 갱신, 새 `routers/equiv_check.py`)

| 메서드·경로 | 권한 | 요지 |
|---|---|---|
| `GET /equiv/recipes?study_id=` | member | 시스템 기본 + global + 그 Study 레시피의 최신 활성 버전 목록(`key, version, name, scope, metrics_count, updated_at, readonly`) |
| `GET /equiv/recipes/{key}[?version=n]` · `GET …/{key}/versions` | member | 정의·버전 이력(삭제된 key도 이력용으로 조회 가능, `deleted:true`) |
| `POST /equiv/recipes` | power | 생성: `{name, description, scope, study_id?, definition}` 또는 `clone_from:{key, version}` 또는 `from_check: eq_id`(스냅숏 복제) → 201 `{key, version:1}` |
| `PUT /equiv/recipes/{key}` | power(global은 작성자·admin) | `{base_version, name?, description?, definition}` → 새 버전 |
| `DELETE /equiv/recipes/{key}` · `POST …/{key}/restore` | power(global 작성자·admin) · admin | 소프트 삭제·되살리기(멱등) |
| `POST /studies/{id}/equiv-checks/preview` | member | DB 쓰기 없음: 쌍 매칭 결과·binding 해석·추출 필요 수·사본 예상 바이트·problems |
| `POST /studies/{id}/equiv-checks` | power | `{side_a, side_b, pairing, recipe:{key, version} \| recipe_inline:{definition, base?:{key,version}}, bindings?, note?}` → 202 `{eq_id, eq_no, job_id}` |
| `GET /studies/{id}/equiv-checks` | member | 이력 목록(필터 `side_kind`·`side_ref`·`verdict`·`recipe_key`, 커서 `X-Next-Cursor`) |
| `GET /equiv-checks/{eq_id}` | member | 행 + 스냅숏 + `metrics.csv` 요약 표(파일 읽기, LRU, `no-store`) |
| `GET /equiv-checks/{eq_id}/curves?pair=&metric=` · `/table.csv` | member | 곡선 A·B · 원표 받기 |
| `PATCH /equiv-checks/{eq_id}` | 작성자·admin | `note`만 |

오류(한국어): 404 `EQ_RECIPE_NOT_FOUND`·`EQ_CHECK_NOT_FOUND`, 409 `EQ_RECIPE_READONLY`·`EQ_RECIPE_VERSION_CONFLICT`·`EQ_RECIPE_NAME_TAKEN`·`EQ_CHECK_LIMIT`·`FEATURE_NOT_AVAILABLE`, 422 `EQ_RECIPE_INVALID`(problems `METRIC_ID_INVALID`·`METRIC_DUPLICATE`·`METRICS_RANGE`·`TOL_INVALID`·`SOURCE_INVALID`·`KIND_SOURCE_MISMATCH`), 422 `EQ_CHECK_INVALID`(problems `SIDE_NOT_FOUND`·`SIDE_NOT_READY`·`FOLDER_OUTSIDE_ROOTS`·`PARAM_SET_MISMATCH`·`NO_PAIRS`·`PAIRS_RANGE`·`METRIC_UNBOUND`(필수 지표 source null — 참고로 바꾸거나 연결)·`EQ_EXTRACT_TOO_LARGE`). 감사 `EQ_RECIPE_CREATE`·`UPDATE`·`DELETE`·`RESTORE`, `EQ_CHECK_CREATE`.

## 7. 화면(⑤ 결과분석 탭 "등가성 판정", 필수 UI만)

라우트 `/stage/analysis?tab=equiv[&eq=<id>]`. 기존 탭(변수–응답·설계공간 지도·영향도·커브) 옆에 추가. 위에서 아래로:

1. **비교 대상**: A(기준)·B(비교) 선택 — 기본은 ⑤ 머리 출처 = A, `비교 추가` 출처 = B. 종류 4가지(§4.1), `folder`는 기존 서버 경로 탐색(S7) 재사용. 쌍 방식 세그먼트 `이름` \| `파라미터 값` \| `직접 지정` + 미리보기 결과(쌍 n · 짝 없음 a/b 목록).
2. **레시피**: 드롭다운(시스템 기본 / 이 Study / 전역 — 이름 · v번호) + `편집`(접힘). 편집 표 = 지표 행(사용 체크·이름·종류·원천 연결(성능 정의 드롭다운 또는 직접 spec)·상대 %·절대값·상관 하한·필수/참고). 버튼 `이번만 사용` · `새 버전 저장` · `다른 이름으로 저장`(범위 Study/전역, 설명) · `삭제`. 연결 필요 행은 노란 표시, 필수 + 미연결이면 실행 비활성.
3. **실행**: `판정 실행` → 작업 진행(대기열 공통 컴포넌트).
4. **결과**: 종합 배지 `통과`(녹)·`미달`(적)·`판정 불가`(회) + 한 줄(필수 n/N · 참고 미달 k · 쌍 수 · 레시피 이름 vN(수정됨)). 지표 표(지표·A 평균·B 평균·최대 상대차·최대 절대차·상관 최소·허용·통과 쌍 n/N·상태·필수/참고), 행 펼치면 쌍별 값. 쌍 선택 → **곡선 겹쳐 그림**(A 실선·B 점선, r·NRMSE 표시). `table.csv` 받기.
5. **이력**: 목록(EQ-번호·시각·사용자·A/B 라벨·레시피 이름 v·판정·메모) → `열기`(결과 다시 보기) · `이 레시피 불러오기`(스냅숏을 편집기에 적재, 원 레시피가 더 새 버전이면 "현재 v5 · 이력 v3" 안내).

localStorage `physicsai.analysis.equiv.recipe`(마지막 선택). 문구 전부 한국어.

## 8. 연동

- **native-rollout 현장 검증 (c)**: 같은 형상의 SimLab 메시 해석(A)과 native 모핑 메시 해석(B)을 이 기능으로 판정하고, 회신은 **판정 번호(EQ-NNN)·종합 판정·지표 집계 수치**만(결과 파일 반출 없음 — geometry-engine §9 현장 인수 원칙). 기본 레시피 또는 현장 레시피 이름·버전을 함께 기록한다.
- **FEM 검증(§21)**: FEM 검증 상세에 `등가성 판정으로 열기`(A = `fem_verify`, B = 원 예측) 링크만 추가. FV 자체 비교 규칙은 바꾸지 않는다.
- ⑥ 최적화·④ 예측 동작 불변.

## 9. 시험·완료 기준

| ID | 내용 |
|---|---|
| V-EQ-1 | migration up/down(행 있으면 down 거부)·`MIGRATION_HEAD` 갱신·CHECK(scope·status·verdict) |
| V-EQ-2 | 레시피 검증 골든: id 규칙·중복·지표 수 상한·tol 음수/NaN·kind–source 불일치 → problems 코드 |
| V-EQ-3 | 생명주기: 복제(parent 기록)·편집 버전 증가(이전 행 불변)·`base_version` 충돌 409·이름 중복 409·소프트 삭제 후 목록 숨김·이력 스냅숏 불변·restore·시스템 기본 수정 409 |
| V-EQ-4 | 권한: general 생성 403, global 타인 편집 403, admin 허용, study 레시피 다른 Study에서 안 보임 |
| V-EQ-5 | 쌍 매칭: by_name(대소문자)·by_params(rel tol·정수 정확·중복 점 최소 번호)·이름 집합 다름 `PARAM_SET_MISMATCH`·manual·상한 |
| V-EQ-6 | 지표 수학 골든(Python 순수 함수, 1e-9): rel/abs OR 규칙·`zero_tol`·Pearson(보간·공통 구간·평탄 곡선 NA)·NRMSE·사면체 부피(단위 정사면체·hexa 5분할)·집계 all/min_ratio·종합 PASS/FAIL/INCOMPLETE |
| V-EQ-7 | EQ_EXTRACT: 재사용 조건(같은 `H3D_REQUESTS.txt`·같은 spec)에서 추출 0회, 아니면 가짜 hw `minmax`·가짜 `t01_curve_export`로 `E/extract/`에만 출력, **원본 run 폴더 mtime·내용 불변**, 사본 상한 초과 `EQ_EXTRACT_TOO_LARGE` |
| V-EQ-8 | 결과 집합 4종 각각(train_doe·predict_batch·fem_verify·folder)으로 end-to-end 1회(가짜 도구), folder 허용 루트 밖·링크 거부 |
| V-EQ-9 | **DB에 파일 본문 없음**: `summary`·`recipe_snapshot` 크기 상한(≤ 64 KiB)·쌍별 값은 `metrics.csv`에만 |
| V-EQ-10 | API 계약: preview DB 무쓰기, 생성 202, 이력 필터·커서, curves·table.csv, note PATCH 외 수정 불가, 오류 한국어 |
| V-EQ-11 | 화면: 탭 표시·레시피 드롭다운 3그룹·편집 접힘·미연결 필수 시 실행 비활성·결과 배지·곡선 겹쳐 그림·이력 → 레시피 불러오기(스냅숏 적재)·빌드본 최신 |
| V-EQ-12 | 회귀: ⑤ 기존 탭·S14/S16/S17 시험 무수정 통과, `scripts/test-all` 통과 |

완료 기준: V-EQ-1~12 통과 + 서버 확인 **E5A-EQ-1~3**(사용자): ① 같은 해석 결과를 A·B 양쪽에 넣으면 모든 지표 차 0·r = 1·통과, ② 실물 SimLab 대 native 1쌍(현장, 수치만 회신), ③ 해석 DOE 대 일괄 예측 by_params 판정과 ⑤ 겹쳐 보기 값 일치.

## 10. 파일 소유(AGENTS.md 역할 표, 겹침 없음)

| 역할 | 파일 |
|---|---|
| Impl-Backend(API) | `migrations/versions/00NN_equiv_check.py`, `db/tables.py`, `backend/physicsai_core/equiv/{recipes.py, metrics.py, pairing.py}`(순수 함수 — 워커 공용), `routers/equiv_check.py`, `schemas/equiv_check.py`, `services/equiv_check.py`, `config` 스키마·예시 yaml, `openapi.json` |
| Impl-Backend(워커) | `worker/physicsai_worker/steps/analysis/equiv_check.py`(4 step), HANDLERS 등록, `run_metrics` 폴더 지정 인자(기존 동작 불변) |
| Impl-Frontend | `frontend/src/analysis/equiv/*`(탭·레시피 편집기·결과·이력), `analysis` 라우트 탭 추가, `frontend-dist/` |

## 11. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| 응력·접촉력 피크는 메시(SimLab 대 모핑) 차이에 민감 | 같은 형상이어도 10% 초과 가능 | 기본 참고 지표, 원인 분석 후 레시피 조정(geometry-engine §10.2 취지) |
| 해석 h3d 사본(쌍 수 × 수백 MB) | 디스크·시간 | 상한·preview 예상 바이트, ①-6/PB_RESP_EXTRACT 선행 시 재사용 |
| `perf` 이름이 두 템플릿(altair·native)에서 다른 spec | 다른 양을 비교 | `EQ_SPEC_DIFFERS` 경고·스냅숏에 양쪽 spec 기록 |
| 메시 부피 원천(include 파싱)과 SimLab 보고 부피 차 | 0.1% 기준에 오판 | 요소형 미지원 경고, 미결 Q3 |
| 곡선 시간 축 차(출력 간격·종료 시각) | r 저하 | 공통 구간 보간·짧은 겹침 경고 |
| 판정 통과를 "모든 조건 등가"로 오해 | 잘못된 확신 | 결과 줄에 레시피 이름·버전·필수 지표 수 상시 표시 |

## 12. 미결(사용자 확인)

- **Q1** 다건 쌍 비교용 "같은 표본표" 생성 경로: native ①-3은 LHS(native)만, S18 플랫폼 DOE는 `table` 표본 제외라 altair DOE와 native DOE를 같은 점으로 만들 방법이 없다. 1차는 `folder`·`fem_verify`·`by_name`(소수 run)로 판정하고, 다건이 필요하면 ①-3에 "다른 DOE의 표본표 사용" 추가 여부를 결정.
- **Q2** 기본 레시피에서 응력 피크·접촉력 피크를 참고(제안)로 둘지 필수로 둘지.
- **Q3** 부피 차 원천: 메시 include 직접 적분(제안) 대 starter 출력 질량(밀도 같을 때 부피 비와 같음) 대 paicad check 보고값.

## 변경 메모(EQ-Cn)

- **EQ-C1**(2026-10-21, 구현 f589d87·d95446f·⑤ 화면 — 사용자 확정 반영 + 구현 차이):
  1. **실행 가능한 레시피(확정)**: 시스템 기본(`sys:default`)은 읽기 전용 제안값이며 **그대로 실행할 수 없다** — `recipe:{key:"sys:default"}` 또는 `recipe_inline.base = sys:default`는 422 `EQ_CHECK_INVALID`(problem `RECIPE_NOT_CONFIRMED`, "복제해 확인한 레시피로 실행"). 판정은 사용자가 복제·확인한 레시피(`user`, 그 레시피를 base로 한 1회용 수정 포함)와 base 없는 1회용 정의(`adhoc`)만. 화면은 시스템 기본 선택 시 실행·`이번만 사용` 비활성 + 안내. 이로써 `eq_checks.recipe_source = system`은 새 행에서 생기지 않는다(값·CHECK는 호환 위해 유지).
  2. **응답 연결(확정)**: 필수/참고 구분·허용오차는 사용자가 레시피에서 정하고, **사용 중인 지표는 필수·참고 모두** 응답(source)이 연결돼야 실행된다(null이면 422 `METRIC_UNBOUND`, §3.2 "참고는 미연결이어도 실행" 대체). `mesh_volume`은 예외(아래 3의 기본 원천).
  3. **부피 원천(Q3 확정)**: `source.origin` = `mesh`(기본, include 직접 적분) \| `starter_mass`(starter 출력 TOTAL MASS) \| `paicad`(check 보고값) — 레시피에서 선택.
  4. **표본표 재사용(Q1 확정)**: ①-3에 `sampling.kind = train_doe`(같은 Study READY DOE의 표본표, 파라미터 이름 집합 같을 때만, run 이름 유지 → `by_name` 쌍 키). 불일치·미준비 422 `DOE_SAMPLING_INVALID`.
  5. 구현 차이: (a) `by_name`에서 양쪽 run이 1개씩이면 이름이 달라도 그 둘을 쌍으로 본다(fem_verify·단일 폴더), (b) `curve_corr`·`curve_nrmse`도 `perf`(CURVE 성능 정의) 원천 허용, (c) 설정 `equiv_check.snapshot_max_bytes`(64 KiB, V-EQ-9) 추가, (d) problems 코드 추가 `RECIPE_REQUIRED`·`RECIPE_NOT_CONFIRMED`·`LABEL_INVALID`·`RULE_INVALID`·`SNAPSHOT_TOO_LARGE`, 경고 `EQ_CURVE_DEFS_MISSING`·`FOLDER_FILES`, (e) 화면: ⑤ 머리에 탭 `결과 표·그래프`(기존 4탭 묶음) \| `등가성 판정`, 메모는 실행 시 입력 + 결과 화면에서 작성자·관리자만 수정(PATCH note).
