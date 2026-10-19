# 계약: S18 ① 학습 DOE 플랫폼 동시 생성 — phase3 §23

> 이 문서는 phase3.md §23과 변경 메모 D3-66입니다. s15~s17과 같은 사정으로 별도 파일로 두며, 다음 Plan 커밋에서 phase3.md 본문과 변경 메모 목록으로 옮깁니다. 절 번호·용어·원칙은 phase2.md §6.4(TD_DOE_GEN), phase3.md §11.4(GEOM_UPDATE·MESH·RAD_ASSEMBLE 판정), §14.5(④ BP_GEN·`run_parallel`), [s15_sampling.md](s15_sampling.md) §20(표본 방식·설명문)을 따릅니다.
>
> 기준선은 `claude/phase3` a5c6696(S17, migration head `0014_multiobj`)입니다. 이 문서의 migration은 `0015_doe_platform_gen`(Revises `0014_multiobj`)입니다.

## 23. S18 ① 학습 DOE 플랫폼 동시 생성 (사용자 VOC·결정 2026-10-19, D3-66)

사용자 VOC(2026-10-19): "① DOE 생성할 때 웹에선 동시 실행이라 표시되는데 실제로는 순차로 돈다. 4개 정도는 동시로 실행하게 해 줘."

사용자 결정(2026-10-19):
- S15 §20.3 안 B를 채택합니다. ① 학습 DOE 생성을 플랫폼 실행기로 옮깁니다.
- "어차피 native(자체 형상 엔진, 프로젝트 문서 `contracts/geometry-engine.md` 방향)로 바꿀 거니 HyperStudy에 힘쓰지 말자." 그래서 이번 범위는 다음으로 줄입니다.
  1. hstbatch 모드는 현재 코드 그대로 두고 **호환 모드로 표시만** 합니다.
  2. 플랫폼 모드는 ④ BP_GEN 체인·`run_parallel`·S15 sampling을 최대한 재사용해 **최소 변경으로 4개 동시 생성**합니다.
  3. 원본 HyperStudy 출력과의 일치는 **DG_SCAN·TD_SOLVE·큐레이션이 동작하는 데 필요한 파일·폴더 규칙만** 지킵니다.
  4. 형상 생성(GEOM_UPDATE)은 나중에 native 엔진으로 **바꿔 끼울 수 있게 경계를 한 곳으로** 정리합니다(이번에 native 구현은 하지 않음).

원인 추정(서버 확인 전): 원본 앱도 `hstbatch -multiexec M`을 씁니다. `-multiexec`는 HyperStudy 평가 단계의 병렬 수이고, pyd 안의 입력 생성(SimLab m_1·HyperMesh m_2)은 run마다 순차로 도는 것으로 보입니다. 화면의 "실행 중 4"는 `HstRunTracker`가 **run 폴더 수**로 계산한 값이라 실제 프로세스 수가 아닙니다(`worker/tests/stage1_train_data/test_doe_multiexec.py`가 이 동작을 고정). 이번에는 이 추정을 바로잡는 작업을 하지 않고, 플랫폼 모드를 기본으로 바꿔 해결합니다. hstbatch 쪽 확인은 선택 1항목(E1-9-5)만 둡니다.

1·2·3차 원칙(단일 슬롯 FIFO, 제한기, `shell=False`, 설정만, AI 루트만, `_backup`, 한국어, 필수 UI, DB에는 수치·상태만, 원본 pyd를 플랫폼 프로세스에서 import 금지)은 그대로입니다. 새 런타임 의존성·새 라우트·새 job_type은 없습니다.

### 23.1 범위 / 비범위

| 범위 | 비범위(후속) |
|---|---|
| ①-3 생성 방식 `platform`(기본)·`hyperstudy`(호환, 무변경) | hstbatch 모드 개선(진행 라벨·동시 수 보정), HyperStudy 유형 식별자 조사(S15 E1-8-2 취소) |
| 플랫폼 표본 8종(S15 `build_matrix` 재사용) | HyperStudy 4종 → 플랫폼 방식 자동 매핑(같은 시드여도 값이 달라 의미가 적음) |
| run마다 m_1→m_2→m_3을 최대 M개 동시에 실행(`run_parallel`, Job Object 1개) | 쿠션 단독(mesh_only) ① DOE — ①은 조립 폴더 필수 유지(미결 3) |
| run 폴더·samples.csv·runs.json을 DG_SCAN·TD_SOLVE·RI_SCAN·큐레이션 규칙에 맞춤 | HyperStudy 출력 파일 전체 재현(hstx·approach 정의 파일 등) |
| 실패 run만 재시도, 취소(그룹 종료), 진행 라벨(실행 중·대기·완료·실패) | 미리보기 API(① 표본 표를 작업 전에 보여 주는 라우트) |
| 형상 생성 경계 한 곳(`run_chain.geometry_update`) | native 형상 엔진 구현 |
| migration 0015(생성 방식·표본 기록, run별 생성 상태) | 이어서 추가(Sobol continue), 범위 덮어쓰기(①은 ①-2 표 범위만) |

### 23.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| G1 | **job_type `TD_DOE_GEN`과 step 키 3개를 유지**합니다. `HST_GEN_RADIOSS` 처리기가 `train_does.generator`로 분기합니다(HYPERSTUDY = 기존 hstbatch, PLATFORM = `run_parallel`). 표시 라벨만 "HyperStudy 입력 생성" → **"입력 생성(run별)"**로 바꿉니다. | step을 추가하면 재시도 step 번호(`resume_from_step`)·진행 가중이 어긋나고, 건너뛴 step 때문에 진행률이 85% 튑니다. 새 job_type을 만들면 같은 Study에서 두 생성이 동시에 돌 수 있고 프런트 runner·기능 판정을 복제해야 합니다. 키 이름은 내부 식별자일 뿐이라 화면 라벨만 바꿉니다. |
| G2 | run별 체인 m_1 GEOM_UPDATE → m_2 MESH → m_3 조립은 ④ `batch._gen_one`에서 **공용 `worker/physicsai_worker/steps/run_chain.py`로 추출**하고, ④·① 모두 이것을 씁니다. ④ 동작은 바뀌지 않습니다. | 최소 변경으로 재사용합니다. 판정·경고(§11.4 `judge_output`·`mesh_preflight`·`mesh_log_warning`·`assemble_into`)는 이미 공용입니다. |
| G3 | 형상 생성 경계 = `run_chain.geometry_update(runner, settings, *, work_dir, rendered_script, cad_file) -> str`(성공 = `work_dir/{predict.simlab_mesh_name}` 경로) **한 함수**입니다. ④ 단일 예측 GEOM_UPDATE(`predict_inputs.geom_update`)도 같은 함수의 `ctx` 판을 씁니다(§23.6). | native 엔진으로 바꿀 때 고칠 곳이 한 군데여야 합니다. |
| G4 | 표본 = S15 `build_matrix(source, parameters=①-2 사용 행, tpl_params=train_setups.tpl_params, max_runs=train_data.platform_max_runs, integer_rounding=predict.integer_rounding)`. kind 8종이고 `ranges`·`continue_from`·`table`·`train_doe`는 받지 않습니다. | 결정적·시험 완료 코드를 재사용합니다. ①의 범위는 이미 ①-2 표에 있습니다. |
| G5 | API(작업 생성)는 검증과 run 수 계산만 합니다. `lhs_opt`는 같은 count·seed의 `lhs`로 대신 검증합니다. 실제 행은 **워커 DG_PREP**이 계산해 `train_doe_points`에 저장합니다. | lhs_opt n=500은 순수 Python으로 수 초~수십 초라 동기 API에 맞지 않습니다. 결정적이라 API와 워커의 run 수는 같습니다(V3-S18-1). |
| G6 | DB는 migration `0015_doe_platform_gen`입니다. `train_does.generator`·`sampling`을 추가하고, run별 생성 상태 테이블 `train_doe_points`를 새로 만듭니다. 플랫폼 DOE의 `doe_type` = 방식 이름(`LHS_OPT` 등 ④ `source_kind`와 같은 글자), `options` = 정규화한 표본 입력값입니다. | 실패 run만 다시 만들려면 run별 상태가 필요합니다(④ `predict_batch_runs`와 같은 방식). `doe_type`·`options`를 ④와 같은 글자로 두면 영향도 등급(S15 §20.7)을 `batch_influence`로 그대로 계산합니다. |
| G7 | run 폴더 규칙은 다운스트림에 필요한 것만 둡니다: `D/{train_data.platform_run_root}/run__{n:05d}/{m_1,m_2,m_3}`, `input_rel` = m_3, starter = m_3 직계 `starter_glob` 일치·eps_mesh 아님 정확히 1개. | DG_SCAN(`run_dir_glob`, 이름 = run_key), TD_SOLVE·SCX(`input_rel`·`starter_name`·직계 rad/inc), RI_SCAN(`result_run_dir_regex` = 폴더 이름), ④ `train_doe`(samples.csv)가 보는 것이 전부입니다. |
| G8 | 동시 수 M = 사용자 입력(1~`train_data.max_multi_execution`, 화면 기본 `train_data.platform_parallel_default` = 4)입니다. 모든 자식이 제한기 그룹 1개(Windows Job Object 1개)를 나눠 씁니다. 라이선스 동시 수는 자동 감지하지 않고 입력 안내만 합니다. | ④와 같습니다(§14.5). |
| G9 | run 실패 처리 `on_run_failure` = `fail`(기본) \| `continue`. `fail`이면 모든 run을 시도한 뒤 실패가 있으면 step FAILED `GEN_PARTIAL_FAILED`이고, 재시도하면 실패·미완료 run만 다시 만듭니다. `continue`이면 성공한 run만 등록하고 경고 `PARTIAL_OUTPUT`을 냅니다. | 학습 데이터는 계획한 표본이 다 있는 것이 기본입니다. 원본(hstbatch)도 오류 줄이 있으면 작업 실패입니다. |
| G10 | API 기본값은 하위호환입니다. `generator`를 생략하면 `sampling`이 있을 때 platform, 없을 때 hyperstudy입니다(기존 호출·시험 무변경). 화면 기본 = 설정 `train_data.doe_generator_default`(= `platform`)입니다. | 기존 API 사용자와 V2 시험을 깨지 않습니다. |

### 23.3 다운스트림이 요구하는 파일·폴더 규칙(코드에서 역으로 확정)

| 소비자(코드) | 요구 | 플랫폼 모드가 만드는 것 |
|---|---|---|
| DG_SCAN(`doe_gen.dg_scan`) | `D/{run_dir_glob}`(기본 `approaches/*/run__*`) 일치 폴더, 이름 = run_key(`RUN_KEY_RE`), 폴더 안 재귀 `starter_glob` 일치(eps_mesh 제외) 정확히 1개 → `input_rel` = 그 파일의 폴더 | `D/approaches/doe_1/run__00001/m_3/<starter>` — `platform_run_root`는 `run_dir_glob`과 일치해야 함(설정 검증) |
| `train_runs`·runs.json | `{run_key, input_rel, starter_name}` | input_rel = `01_train/doe/<id>/approaches/doe_1/run__NNNNN/m_3` |
| TD_SOLVE(`solve.py`)·SCX(`_scx.py`) | `input_dir` = input_rel, `input_file` = input_rel/starter. SCX는 input_dir **직계** 파일을 나열하고 `<base>_0001.rad`를 engine으로 씀 | m_3 = 조립 폴더 직계 rad·inc(eps_mesh·include 기준본 제외 — `assemble_into`) + 새 include. engine `_0001.rad`가 조립 폴더에 있으면 그대로 복사됨 |
| RI_SCAN(①-5) | 결과 폴더 이름 `result_run_dir_regex`(`^run__\d+$`) | run_key = `run__{n:05d}`(④ `batch_matrix.run_key_for`) |
| 큐레이션(②)·①-6 | `01_train/results/<doe>/<run_key>/`(TD_SOLVE 산출) — 생성 폴더와 무관 | 영향 없음 |
| ④ `train_doe` 출처·F(①→파라미터 세트) | `D/samples.csv` 헤더 `run_key,<사용 파라미터 이름…>`, `sample_status` PARSED/PARTIAL | DG_SCAN이 DB `applied_values`(SimLab에 실제 들어간 값 = paramitem 추출 값과 같은 의미)로 직접 작성, PARSED |
| ①→④ 파라미터 세트(`register_param_set_from_train`)·S16 FEM 검증 | `01_train/radioss_assem/<doe_id>/`(+`RENUM_INIT.csv`) | DG_PREP ①(기존 코드) 그대로 |
| 진행 정규식·hstbatch 런처·`INPUT_HST_RUN.json`·`DATA_doe_design_type.json`·include TCL 사본 | hyperstudy 모드만 | **만들지 않음** |

run 폴더 내용(④ B와 같음):
- `m_1/`: CAD 사본, `{predict.rendered_script_name}`(렌더 tpl), `{predict.simlab_mesh_name}`
- `m_2/`: `{predict.mesh_include_name}`, `log_batch.txt` — `commands.mesh`가 null이면 m_2를 만들지 않고 include는 m_1에 생김
- `m_3/`: 조립 사본 + include

`D` 바로 아래에는 `simlab_parametered_mesh.tpl`·CAD 사본(기존 DG_PREP ②의 앞 두 항목), `doe.json`(신규, §23.5), `samples.csv`·`runs.json`(DG_SCAN)이 있습니다.

### 23.4 API — `POST /studies/{id}/jobs`(`TD_DOE_GEN`) params 확장(새 라우트·operationId 없음)

```jsonc
// 플랫폼(화면 기본)
{"generator":"platform",
 "sampling":{"kind":"lhs_opt","count":40,"seed":1,"criterion":"maximin"},
 "multi_execution":4,"radioss_assem_path":"E:/…/radioss_assem","on_run_failure":"fail"}
// 원본 HyperStudy(호환 — 기존과 같음, generator 생략 가능)
{"generator":"hyperstudy","doe_label":"LatinHyperCube","num_runs":30,"options":{"RANDOM_SEED":7},
 "multi_execution":2,"radioss_assem_path":"…"}
```

`sampling` 형식(`schemas/stage1_train_data.py` 새 discriminated union `TrainSampling`, 추가 키 금지):

| kind | 필드 |
|---|---|
| `lhs`·`lhs_opt` | `count` int ≥ 2, `seed` int ≥ 0(기본 1). lhs_opt만 `criterion` `maximin`(기본) \| `corr` |
| `sobol` | `count` int ≥ 4, `seed` 0~4294967295(기본 1) |
| `fullfact` | `levels{name: 1..10}`(생략한 변수 = 2) |
| `fracfact` | `resolution` 4 \| 5(기본 5) |
| `pb`·`bbd` | 없음 |
| `ccd` | `alpha` `face`(기본) \| `inscribed` |

검증(422 `INVALID_PARAMS`, 기존 오류 모양):
- `generator`가 생략되면 `sampling` 유무로 정합니다(G10).
- platform: `sampling` 필수, `doe_label`·`num_runs`·`options` 금지.
- hyperstudy: `sampling`·`on_run_failure` 금지.
- `radioss_assem_path`는 두 방식 모두 필수입니다(기존 starter 1개 검사 그대로).
- `multi_execution`: platform 생략 시 `min(platform_parallel_default, max_multi_execution)`, hyperstudy 생략 시 1(기존). 범위 1~`max_multi_execution`.

플랫폼 조합 검증:
- `services/job_params/stage1_train_data.py` → 새 순수 모듈 `physicsai_core/stage1_train_data/doe_platform.check(sampling, setup, settings)`.
- 처리: `build_matrix`를 부르되 `lhs_opt`는 `{kind:"lhs", count, seed}`로 대신합니다.
- 결과: problems가 있으면 **422 `DOE_SAMPLING_INVALID`** + `problems:[{code, message}]`. 코드는 S15 §20.9 그대로(`TOO_MANY_ROWS`·`TOO_FEW_ROWS`·`COUNT_NOT_POW2`·`LEVELS_INVALID`·`DESIGN_UNSUPPORTED`·`GENERATOR_UNAVAILABLE`)이고, 문구의 상한은 `platform_max_runs`입니다.
- notes(`FIXED_EXCLUDED`·`FULL_FACTORIAL_USED`·`BBD_PAIRWISE`·`DUPLICATE_ROWS`·`INFLUENCE_TOO_FEW`)는 작업 생성 `warnings`로 보냅니다.
- 사전조건(409)은 기존 `TPL_REQUIRED`·`TPL_STALE`·`PREREQUISITE_MISSING(RADIOSS_STARTER)` 그대로에 기능 판정을 방식별로 더합니다(§23.8).

서버가 확정 기록하는 params(B8):
- platform: `{generator:"platform", doe_id, doe_label:<방식 표시 이름>, doe_type:<LHS_OPT…>, sampling:<정규화 입력>, num_runs:<예상 run 수>, multi_execution, on_run_failure, radioss_assem_path}`
- hyperstudy: 기존 키 + `generator:"hyperstudy"`

`train_does` 행(`after_insert`):

| 열 | hyperstudy | platform |
|---|---|---|
| `generator` | `HYPERSTUDY` | `PLATFORM` |
| `doe_label` | 정의 파일 키 | S15 §20.4 표시 이름(예 "최적화 LHS") |
| `doe_type` | value(`TYPE_…`) | `LHS`·`LHS_OPT`·`SOBOL`·`FULLFACT`·`FRACFACT`·`PB`·`BBD`·`CCD` |
| `options` | DOE_METHOD_OPTIONS | 정규화한 `sampling`에서 kind를 뺀 값(예 `{"count":40,"seed":1,"criterion":"maximin"}`) |
| `num_runs_requested` | 기존 | 예상 run 수(설계가 정하는 방식도 미리 알 수 있음) |
| `sampling` | NULL | `{kind, input, meta: null}` → DG_PREP이 `meta`(§20.5 각 meta + quality)를 채움 |

응답 확장(`backend/openapi.json` 갱신):
- `TrainDoe`(목록·상세)에 `generator: "platform"|"hyperstudy"`, `sampling: {kind, label, desc_id, meta}|null`, `gen: {total, pending, running, done, failed}|null`(platform만, `train_doe_points` 집계)을 추가합니다.
- `GET /train-does/{id}/result-table`의 `sampling`(S15 §20.6): platform이면 `{method:<doe_type>, label, desc_id:"td_<kind>", options}`.
- `/status.limits.configured`에 `doe_generator_default`·`doe_platform_parallel_default`·`doe_platform_max_runs`를 추가하고, `/status.features`에 `train_doe_platform`을 추가합니다.

영향도 등급(S15 §20.7): `sampling/registry.doe_influence(doe_type, options)`에 한 분기를 더합니다. `doe_type`이 플랫폼 방식 이름이면 `batch_influence(doe_type, options)`(fracfact 해상도는 `options.resolution`)를 씁니다. 호출부(`doe_result_table`·④ TRAIN_DOE)는 바뀌지 않습니다.

### 23.5 step 처리(`TD_DOE_GEN`, 키·가중 불변)

| step | hyperstudy | platform |
|---|---|---|
| DG_PREP | 기존 그대로 | ① 조립 사본(기존). ② `D`에 tpl·CAD 사본(기존 앞 두 항목). DOE 유형 json·include TCL·런처·`INPUT_HST_RUN.json`은 **만들지 않음**. ③ 표본: `train_doe_points`가 비었으면 `doe_platform.build(sampling, setup, settings)` → 행 삽입(PENDING), `train_does.sampling.meta`·`num_runs_requested` = 행 수. notes → `ctx.add_warning`. 행이 이미 있고 `train_does.tpl_sha256` ≠ 지금 tpl sha면 전부 PENDING + 경고 `TPL_CHANGED_REGEN`. 그 밖에는 행 유지(재시도). ④ `D/doe.json` = `{doe_id, generator, sampling:{kind, label, input, meta}, parameters:[이름…], run_root, rows:[{doe_no, run_key, values, applied_values}]}`(이전 파일 `_backup`). ⑤ `parameters_snapshot`·`tpl_sha256`(기존) |
| HST_GEN_RADIOSS(라벨 "입력 생성(run별)") | **기존 코드 그대로**(hstbatch, `HstRunTracker` 라벨 포함) | 새 `steps/stage1_train_data/doe_platform_gen.py` `gen_platform(ctx)`: ① `commands.geom_update` null → `TEMPLATE_NOT_CONFIGURED`. `commands.mesh`가 있으면 `mesh_preflight`(include TCL 없음 → `RESOURCE_MISSING`, 한 번만). ② `FAILED`·`RUNNING` 행 → PENDING. ③ todo = DONE이 아닌 행(doe_no 순). 없으면 `StepSkipped("생성할 run 없음 — 모두 생성됨")`. ④ `M = min(train_does.multi_execution, max_multi_execution)` → `ctx.run_parallel(todo, gen_one, item_id=run_key, max_parallel=M, label)`. ⑤ gen_one(run): RUNNING → run 폴더가 있으면 `fs_lock` 안에서 `_backup` → `m_1` 만들기·CAD 복사·`render_tpl(tpl, values, applied_values)`를 `{rendered_script_name}`으로 → `run_chain.build_run_inputs(runner, s, run_dir, cad_file, assem_dir=A, assembly=True)` → m_3 반환 → `prepared_input.plan_copy(m_3)` 문제 없으면 DONE. ⑥ 실패 행 FAILED(code·message). 경고는 코드별 1건(`run_chain.aggregate_warnings`). ⑦ G9 판정: 실패가 N개면 첫 실패 코드로 FAILED. 일부 실패 + `fail`이면 `GEN_PARTIAL_FAILED` "run N개 중 F개 입력 생성 실패(첫 실패 run__00003: …) — 재시도하면 실패한 run만 다시 만듭니다". `continue`이면 경고 `PARTIAL_OUTPUT`. ⑧ 취소·lease 상실 → RUNNING 행 PENDING(④ bp_gen과 같은 except 처리). result `{gen_done, gen_failed[:200], multi_execution}`, `outputs.parallel`(기존 `peak_processes`·`commands_rel`) |
| DG_SCAN | 기존 그대로 | DONE 행만 run_key 순으로 봅니다. run 폴더 m_3에서 starter 1개(`starter_glob`, eps_mesh 제외)를 확인하고, 없거나 2개 이상이면 `RUN_INPUT_INVALID` 경고 후 제외합니다. `samples.csv` = `doe_samples.write_samples_csv(D/samples.csv, names, [{run_key, values: applied_values}])`, `sample_status` = PARSED(DONE이 아닌 run이 있으면 PARTIAL). runs.json·`train_runs` 삽입·READY(기존). run 0개 → `OUTPUT_MISSING` |

- 진행 라벨(platform) = `"입력 생성 " + hst_run_label(running, waiting, done+failed, total, M) + (" · 실패 F" if F)`. ④ bp_gen 라벨과 같은 함수입니다. 진행률은 (완료+실패)/전체입니다.
- 취소: 기존 `/jobs/{id}/cancel` → `run_parallel`이 그룹 전체(프로세스 트리)를 종료합니다.
- 종료 훅: `job_end`의 TD_DOE_GEN 분기에 `train_repo.reset_running_points(doe_id)`(RUNNING → PENDING)를 더합니다. 워커가 쓰지 못한 lease 상실·리퍼 경로를 위한 것입니다.
- 재시도(기존 `on_retry` → DOE BUILDING): 기본 시작 step = 실패 step(HST_GEN_RADIOSS)이므로 DONE run은 그대로 두고 나머지만 다시 만듭니다. `from_step=1`이어도 같은 tpl이면 점은 유지됩니다(결정적).

### 23.6 공용 체인과 형상 생성 경계(`worker/physicsai_worker/steps/run_chain.py`, 신규)

```python
def geometry_update(runner, settings, *, work_dir: str, rendered_script: str, cad_file: str) -> str:
    """형상 생성 경계(native 엔진 교체 지점, D3-66). 입력: work_dir 안의 렌더 스크립트·CAD 사본.
    출력: work_dir/{predict.simlab_mesh_name} 경로(판정 통과). 지금 = 템플릿 'geom_update'(SimLab -auto).
    실패 = StepFailure(EXIT_NONZERO|OUTPUT_MISSING), rc≠0 + 출력 있음 = 경고 EXIT_NONZERO_IGNORED(§11.4)."""

def build_run_inputs(runner, settings, *, run_dir: str, cad_file_name: str, assem_dir: str | None,
                     assembly: bool) -> str:
    """m_1 geometry_update → (assembly) m_2 MESH(commands.mesh null이면 SimLab include) → m_3 assemble_into.
    반환 = 예측/해석 입력 경로(assembly: m_3 폴더, mesh_only: m_1/{simlab_mesh_name}) — ④ _gen_one과 같은 규칙."""

def aggregate_warnings(ctx, outcomes) -> None   # batch._aggregate_warnings 이동
```

- `runner`는 `ParallelRunner` 또는 같은 `run(template_key, values, cwd=, outputs_to_backup=)`·`warn`·`last_line`을 가진 단일 실행 어댑터입니다. ④ 단일 예측 `predict_inputs.geom_update`는 `ctx`를 감싼 어댑터로 `geometry_update`를 호출하게 바꿉니다(동작 불변 — 판정은 이미 `judge_output`).
- ④ `batch._gen_one`은 `build_run_inputs(..., assem_dir=S/radioss_assem, assembly=input_kind != "mesh_only")`를 부르도록 바꿉니다. **V3-S9-7 시험을 수정 없이 통과**해야 합니다.
- native 엔진은 이번 범위 밖입니다. 교체 때는 `geometry_update` 본문(템플릿 키 또는 엔진 호출)만 바꾸고 출력 계약(`{simlab_mesh_name}` 경로)을 유지합니다. 그 밖의 형상 명령 호출(`ctx.run_local("geom_update"…)`·`runner.run("geom_update"…)`)은 이 함수 밖에 남기지 않습니다(정적 검사 V3-S18-8).

### 23.7 DB — migration `0015_doe_platform_gen`(Revises `0014_multiobj`, `MIGRATION_HEAD` 갱신)

- `train_does`:
  - `generator VARCHAR(16) NOT NULL DEFAULT 'HYPERSTUDY'` + CHECK `ck_train_does_generator`(`'HYPERSTUDY','PLATFORM'`)
  - `sampling JSONB NULL`
  - 기존 행은 HYPERSTUDY·NULL입니다.
- 새 `train_doe_points`: `doe_id FK train_does NOT NULL`, `doe_no INT NOT NULL`, `run_key VARCHAR(64) NOT NULL`, `values JSONB NOT NULL`, `applied_values JSONB NOT NULL`, `gen_state VARCHAR(16) NOT NULL DEFAULT 'PENDING'` CHECK(`'PENDING','RUNNING','DONE','FAILED'`), `gen_code VARCHAR(64) NULL`, `gen_message VARCHAR(480) NULL`, `updated_at`.
  - PK(`doe_id`,`doe_no`), UNIQUE(`doe_id`,`run_key`), INDEX(`doe_id`,`gen_state`).
  - 수치·상태만 담고 파일 본문은 없습니다.
- downgrade: `PLATFORM` 행이 있으면 RuntimeError(데이터 보존)이고, 없으면 테이블·열을 지웁니다(S17 관례).
- 저장소 `db/repositories/train.py`: `insert_points`, `points(doe_id, states=None)`, `set_point`, `reset_points(doe_id, from_states)`, `reset_running_points`, `point_counts`. `insert_doe`가 `generator`·`sampling`을 받습니다.

### 23.8 설정·기능(기본값은 스키마 한 곳 `config/schema_stages.py` `TrainDataCfg`, 예시 yaml에 주석 한 줄씩)

| 키 | 기본 | 설명 |
|---|---|---|
| `train_data.doe_generator_default` | `"platform"` | ①-3 화면 기본 방식(`platform`\|`hyperstudy`). API 기본은 G10 |
| `train_data.platform_parallel_default` | `4` | 화면 동시 수 기본(실제 = min(값, `max_multi_execution`)) |
| `train_data.platform_max_runs` | `500` | 플랫폼 표본 run 상한(≤ `max_runs`, 아니면 설정 오류) |
| `train_data.platform_run_root` | `"approaches/doe_1"` | run 폴더 상위(상대, `..`·절대 금지). `<root>/run__00001`이 `run_dir_glob`(fnmatch)과 맞지 않으면 설정 오류 |

기능 `features.train_doe_platform` = 템플릿 `geom_update` + altair `simlab_path`. `commands.mesh`가 `{include_tcl}`을 쓰면 `resources.hypermesh_include_tcl`, `{hw}`를 쓰면 `altair.hw_exe_path`도 필요합니다(`predict_parametric_missing`과 같은 방식). HyperStudy 자원(`hst_gen_radioss`·`hyperstudy_path`·`doe_design_type_json`·런처)은 필요 없습니다.
- `JOB_FEATURE["TD_DOE_GEN"]` = 빈 요구로 두고, `prepare()`가 방식별로 `train_doe` / `train_doe_platform`을 확인합니다(409 `TEMPLATE_NOT_CONFIGURED`·`RESOURCE_NOT_CONFIGURED` + `missing`).

### 23.9 화면(①-3 `DoeGenCard`, 필수 UI만, D3-55/56 톤)

- **생성 방식** 세그먼트 `플랫폼 생성(동시 실행)` | `원본 HyperStudy(호환)`. 기본 = `/status.limits.configured.doe_generator_default`이고 저장하지 않습니다. 실행 버튼의 FeatureGate는 방식별로 `train_doe_platform` / `train_doe`입니다.
- **플랫폼** 입력:
  - 방식 드롭다운: S15 §20.4 ④ 묶음·순서에서 `table`·`train_doe`를 뺀 8개입니다. 기본 `lhs_opt` + 추천 배지입니다.
  - 방식별 입력: lhs·lhs_opt는 run 수(기본 = 권장)·시드, lhs_opt는 기준 세그먼트를 더합니다. sobol은 run 수 2^m 드롭다운(≤ 상한)·시드, fullfact는 사용 변수별 수준(기본 3^k ≤ 상한이면 3, 아니면 2), fracfact는 해상도 V/IV, ccd는 α입니다.
  - 아래에 `실제 run N개`(`expectedRuns`, `lib/sampling.ts` 재사용, R = `doe_platform_max_runs`)를 표시하고, null이면 "변수 수가 이 방식의 지원 범위 밖"을 표시합니다.
  - 설명 상자 `SamplingDescription id="td_<kind>"`(§23.10) + 권장값 계산 문구를 둡니다.
  - 동시 실행 수(1~max, 기본 `doe_platform_parallel_default`), 힌트 "run마다 SimLab·HyperMesh를 동시에 실행합니다 — Altair 라이선스와 메모리 한도 안에서 정하세요".
  - 체크 `실패한 run이 있어도 성공한 run으로 DOE 완료`(기본 끔 = `fail`).
  - 422 `DOE_SAMPLING_INVALID`이면 problems 문구를 목록으로 보여 줍니다.
- **HyperStudy(호환)**: 기존 입력·동작 그대로입니다. S15 회색 줄 `HS_NOTE`는 "최적화 LHS·Box–Behnken·CCD·Plackett–Burman은 '플랫폼 생성'에서 고를 수 있습니다(원본 HyperStudy 방식은 유형 정의 파일의 방식만)."로 바꿉니다. 회색 줄 하나를 더합니다: "호환 모드 — hstbatch -multiexec로 실행합니다. 실제 동시 실행 수는 HyperStudy가 정하며 입력 생성이 run마다 순차로 될 수 있습니다."
- **결과 줄**: `<doe_label> · <플랫폼|HyperStudy> · run N개 · 상태`. platform이면 `gen`이 있을 때 `· 생성 완료 d · 실패 f / 전체 t`를 덧붙입니다.
- 실행 중 진행은 기존 작업 패널의 step 라벨(§23.5)입니다.

### 23.10 ① 설명문(desc_id `td_<kind>` — S15 §20.4 ④ 문구를 쓰고 아래 줄만 바꿈, 프런트 `lib/sampling.ts` 한 곳)

| desc_id | 바꾸는 줄 | 문구 |
|---|---|---|
| `td_lhs` | 4 | run 수: 자유(2 이상, 상한은 입력란에 표시). 권장 10 × 변수 수. |
| `td_lhs_opt` | 4 | run 수: 자유(2 이상, 상한은 입력란에 표시). 권장 10 × 변수 수(최소 변수 수 + 2). run이 많으면 생성 준비에 수십 초 걸릴 수 있습니다. |
| `td_sobol` | 1 | 저불일치 수열로 공간을 균일하게 채웁니다(스크램블, 같은 시드로 같은 표본). |
| `td_sobol` | 3 | 영향도: 정식. AI 학습에 적합합니다. |
| `td_sobol` | 4 | run 수: 2^m(4·8·16·32·64·128·256). 권장 = 10 × 변수 수 이상인 가장 작은 2^m. |
| `td_fullfact` | 4 | run 수 = 수준 수의 곱(상한 이내). 수준 2~10, 정수 변수는 범위 안 정수 개수까지. |
| `td_bbd` | 4 | run 수 = 2·k·(k−1) + 1(중심점 1개 — 같은 입력의 해석은 같은 결과라 반복하지 않음). 변수 3개 이상. |
| `td_fracfact`·`td_pb`·`td_ccd` | — | ④ 문구 그대로 |

권장 run 수 = `registry.recommended_count(kind, k, platform_max_runs)`(프런트 `recommendedCount`와 같은 식, R만 다름)입니다. k = ①-2 사용 행 수입니다(①-2 검증상 모두 min < max).

### 23.11 시험(V3-S18-*)

원칙(Windows CI 교훈): 동시 실행은 **시각 비율로 단언하지 않습니다.**
- 하한은 가짜 SimLab barrier로 결정적으로 증명합니다.
- 상한은 trace 구간으로 확인합니다(실행기가 M개 넘게 띄우지 않으므로 항상 참).
- barrier·대기 제한은 60초 이상으로 넉넉하게 둡니다.

가짜 도구 추가(`backend/tests/fake_tools/fake_simlab`): `FAKE_SIMLAB_BARRIER=<폴더>:<n>`. 형상 갱신 실행마다 `<폴더>/<pid>`를 만들고, 파일이 n개 이상이 될 때까지 기다립니다. `FAKE_SIMLAB_BARRIER_TIMEOUT_S`(기본 90)를 넘으면 "barrier timeout"을 출력하고 종료코드 9로 끝납니다.

| ID | 기준 |
|---|---|
| V3-S18-1 | `doe_platform.check`/`build`: 8 kind × k = 2~11에서 check의 run 수 = build 행 수, lhs_opt 대체 검증(count·seed 오류 동일), `platform_max_runs` 상한 문구, problems·notes 코드, ①-2 표 → parameters/tpl_params 변환(정수 형식 → applied_values) |
| V3-S18-2 | API: generator 추론(생략 + sampling → platform, 생략 + doe_label → hyperstudy·기존 V2 시험 무변경), 금지 조합 422 5종, 422 `DOE_SAMPLING_INVALID` problems, 생성 warnings(notes), 저장 params(B8), `train_does` 열(generator·doe_type·options·num_runs_requested·sampling), multi_execution 기본·상한, 기능 판정(platform은 geom_update·simlab만, hyperstudy 자원 없어도 생성 가능 / 반대도) |
| V3-S18-3 | migration 0015: 열 기본값·CHECK, 새 테이블 PK·UNIQUE·CHECK, 기존 행 보존, `MIGRATION_HEAD`, PLATFORM 행 있으면 downgrade 실패(`worker/tests/ops/test_ops_admin.py` head 문자열 갱신) |
| V3-S18-4 | 워커 e2e(가짜 simlab·hw, assembly, N = 4, M = 4, barrier n = 4): 성공 = 4개가 실제로 동시에 떠 있었음(순차면 barrier timeout으로 실패). 폴더 `D/approaches/doe_1/run__0000k/{m_1,m_2,m_3}` 내용(④ V3-S9-7과 같은 목록), HyperStudy 파일(json·TCL·런처·INPUT_HST_RUN.json) 없음, `doe.json`, DG_SCAN `train_runs` 4개(input_rel = m_3, starter), `samples.csv` 헤더·값 = DB applied_values, PARSED, `outputs.parallel.max_parallel` = 4, step 라벨 "(동시 4)" |
| V3-S18-5 | 상한: N = 6, M = 2, `FAKE_TOOL_TRACE` → `_peak_concurrency` ≤ 2(하한 단언 없음). `max_multi_execution` = 1이면 M = 1 |
| V3-S18-6 | 실패: `FAKE_SIMLAB_FAIL_MATCH=run__00003`, `fail` → 작업 FAILED `GEN_PARTIAL_FAILED`, 행 상태(DONE 3·FAILED 1), DOE FAILED → 환경변수 지우고 재시도 → simlab 기록상 run__00003만 다시 실행, DOE READY 4개. `continue` → READY 3개 + `PARTIAL_OUTPUT`·samples.csv 3행 |
| V3-S18-7 | 취소: 가짜 simlab `hang`, M = 2 → 취소 요청 → 30초 안에 trace의 pid·손자 pid 전부 종료(psutil), 작업 CANCELED, RUNNING 행 0개(PENDING) |
| V3-S18-8 | 경계: ④ V3-S9-7·S9 나머지 시험 무수정 통과(`run_chain` 추출). 정적 검사 — `worker/physicsai_worker/**`에서 문자열 `"geom_update"`로 명령을 실행하는 곳은 `run_chain.py` 한 파일뿐 |
| V3-S18-9 | 다운스트림: 플랫폼 DOE로 TD_SOLVE(가짜 qsub) 제출 argv의 input_file·input_dir = m_3, ④ `train_doe` 출처 미리보기 행 = samples.csv, result-table `sampling`(`td_lhs_opt`)·영향도(lhs_opt formal, pb reference), `TrainDoe.generator`·`gen` 집계. hyperstudy 회귀 = 기존 stage1 시험 무수정(라벨 시험 `test_doe_multiexec.py` 포함) |
| V3-S18-10 | 프런트: 방식 세그먼트 기본(status 값), FeatureGate 방식별, 8개 드롭다운·추천, 방식별 요청 body(platform/hyperstudy 각각, hyperstudy body 기존과 동일), `td_*` 설명문 줄 단위 픽스처(`fixtures/samplingText.json`에 추가), 실제 run 수, 동시 수 기본·상한, 실패 처리 체크 → `on_run_failure`, 422 problems 표시, `HS_NOTE` 새 문구·호환 회색 줄, 결과 줄 `gen`, 목(`mock/stage1.ts`·`stage1Jobs.ts` platform DOE), `mockContract`, openapi 재생성·`operation_ids.txt` 불변, `frontend-dist` 최신, `scripts/test-all` 통과 |

### 23.12 서버 확인(E1-9, 사용자)

| ID | 확인 |
|---|---|
| E1-9-1 | 플랫폼 생성, run 8·동시 4. 실행 중 아래 감시 명령으로 SimLab·HyperMesh 동시 수가 4 근처로 유지되는지 봅니다. 작업 상세의 step 라벨 "실행 중 4 · …"와 `parallel.peak_processes` = 4를 확인합니다 |
| E1-9-2 | 결과: DOE READY 8 run, ①-4 PBS/SCX 제출 2 run → 결과 회수 → ② 큐레이션 1 run 성공. ④ "① 학습 DOE 재사용" 미리보기 행 = 8 |
| E1-9-3 | 자원: 동시 4에서 라이선스 오류 없음(step 로그에서 `licens` 검색), 작업 회계 최대 메모리, 총 소요(같은 run 수의 hstbatch 기록이 있으면 비교). 오류가 나면 동시 수를 낮추고 `worker.max_memory_gb`·라이선스를 확인합니다 |
| E1-9-4 | 취소: 생성 중 취소 → 30초 안에 감시 출력 0, 재시도 → 남은 run만 생성 |
| E1-9-5 | (선택, VOC 원인 기록용) 원본 HyperStudy 모드 run 8·multiexec 4를 같은 감시 명령으로 관찰해 동시 수를 기록합니다. 결과와 무관하게 이번 작업은 바뀌지 않습니다 |

감시 명령(PowerShell, 2초 간격, `Ctrl+C`로 종료):
```powershell
$log = "$env:TEMP\doe_conc.csv"; "time,simlab,hypermesh" | Out-File $log -Encoding utf8
while ($true) {
  $p  = Get-CimInstance Win32_Process | Where-Object { $_.Name -ne 'cmd.exe' -and $_.CommandLine }
  $sl = ($p | Where-Object { $_.CommandLine -match '-auto' -and $_.CommandLine -match 'simlab_parametered_mesh' }).Count
  $hm = ($p | Where-Object { $_.CommandLine -match 'BATCHRUN_create_include_node_elem' }).Count
  "{0},{1},{2}" -f (Get-Date -Format HH:mm:ss), $sl, $hm | Add-Content $log; Start-Sleep 2 }
```

### 23.13 파일 소유(AGENTS.md 역할 표 — 겹침 없음)

| 에이전트 | 파일 |
|---|---|
| **Impl-Backend** | 새: `migrations/versions/0015_doe_platform_gen.py`, `backend/physicsai_core/stage1_train_data/doe_platform.py`, `worker/physicsai_worker/steps/run_chain.py`, `worker/physicsai_worker/steps/stage1_train_data/doe_platform_gen.py`, 시험 `backend/tests/test_s18_*.py`·`worker/tests/stage1_train_data/test_s18_*.py`. 수정: `backend/physicsai_core/db/{__init__.py, tables/stage1_train_data.py, repositories/train.py, repositories/job_end.py}`, `backend/physicsai_core/{job_types.py(step 라벨), features.py, sampling/registry.py(doe_influence 분기)}`, `backend/physicsai_core/config/{schema_stages.py, validate.py}`, `config/platform.example.yaml`, `backend/physicsai_api/{schemas/stage1_train_data.py, services/job_params/stage1_train_data.py, services/stage1_train_data.py, services/doe_result_table.py, services/system.py}`, `worker/physicsai_worker/steps/stage1_train_data/doe_gen.py`(dg_prep·dispatch·dg_scan 분기만, hstbatch 경로 무수정), `worker/physicsai_worker/steps/stage4_predict/{batch.py, predict_inputs.py}`(run_chain 사용, 동작 불변), `backend/tests/fake_tools/fake_simlab`(barrier), `backend/openapi.json`, `worker/tests/ops/test_ops_admin.py`(head 문자열) |
| **Impl-Frontend** | 새: `frontend/src/stages/stage1/{DoePlatformFields.tsx, doeGenParams.ts(화면 상태 → params, 순수)}`, `frontend/src/__tests__/s18DoeGen.test.tsx`. 수정: `frontend/src/stages/stage1/DoeGenCard.tsx`, `frontend/src/lib/sampling.ts`(`td_*`·`HS_NOTE`·①용 R), `frontend/src/api/types.ts`, `frontend/src/api/generated/schema.d.ts`(`npm run gen:api`), `frontend/src/mock/{stage1.ts, stage1Jobs.ts, steps.ts(라벨)}`, `frontend/src/lib/format.ts`(step 라벨 쓰면), 기존 시험 `stage1.test.tsx`·`sampling.test.ts`·`fixtures/samplingText.json`·`mockContract.test.ts`, `frontend-dist/**` |
| **Plan** | 이 문서·phase3.md 이동, s15 §20.2 S1·§20.17-1 상태 갱신(안 B 채택), `docs/architecture.md`(run_chain·0015), `docs/e2e-checklist.md`(E1-9), `docs/manual/admin.md`·`user.md`(설정 4개·생성 방식) |

인터페이스 고정점: §23.4 params·응답 모양, §23.6 서명, §23.3 폴더 규칙. Frontend는 목으로 먼저 시작하고 openapi 커밋 뒤 맞춥니다.

### 23.14 순서

1. **B0**(1커밋): `run_chain` 추출 + ④ 전환(동작 불변), V3-S18-8 + V3-S9 회귀
2. **B1**: 0015 + `doe_platform.py` + API(params·응답·status·기능) + openapi, V3-S18-1~3
3. **B2**: 워커 dg_prep·gen_platform·dg_scan + 가짜 simlab barrier, V3-S18-4~7·9
4. **F1**(B1 openapi 뒤, 목 기반은 B0와 병렬 가능): V3-S18-10
5. Verifier → 서버 확인 E1-9

### 23.15 리스크

- **R-1 다운스트림 일치**: HyperStudy run 폴더에 다른 파일이 있어도, 플랫폼 결과는 §23.3 규칙만 맞추면 DG_SCAN·TD_SOLVE·SCX·RI_SCAN·큐레이션이 동작합니다(코드 근거). 남는 위험은 원본 m_3 구성이 조립 사본 + include와 다른 경우인데, ④ BP_GEN·S6 예측이 같은 규칙으로 서버에서 동작했으므로 낮습니다(E1-9-2로 확인).
- **R-2 라이선스**: SimLab·HyperMesh 배치가 실행마다 라이선스(HWU)를 씁니다. 동시 4가 한도를 넘으면 run 실패(종료코드·출력 없음)로 나타나고, `fail` 기본이라 작업 실패 → 동시 수를 낮춰 재시도하면 실패분만 다시 만듭니다. 자동 감지는 하지 않습니다.
- **R-3 Job Object 공유 한도**: 그룹이 작업 1개분 CPU·메모리 한도를 나눠 씁니다. SimLab 4개가 메모리 한도에 닿으면 `RESOURCE_LIMIT`(D3-53 판정)입니다. CPU 상한이 낮으면 동시 실행 이득이 줄어듭니다. 관리자는 `worker.max_memory_gb`·코어 설정을 조정합니다(E1-9-3).
- **R-4 같은 CAD를 다른 cwd에서 동시 실행**: SimLab의 사용자 임시·프로필 충돌 가능성은 ④ E4-9-2와 같은 조건입니다. ④가 서버에서 동시 4로 성공했다면 같습니다.
- **R-5 표본 값 차이**: 같은 "LHS·시드 7"이라도 플랫폼과 HyperStudy의 값은 다릅니다. 기존 HyperStudy DOE는 그대로 남고, 새 DOE는 `generator`로 구분해 표시합니다.
- **R-6 정수 형식 기본(`%3i`)**: ±5% 기본 범위에서는 반올림 후 중복 행이 많을 수 있습니다(`DUPLICATE_ROWS` 안내, 막지 않음 — 기존 HyperStudy도 같음).
- **R-7 lhs_opt 큰 n**: DG_PREP에서 n = 500·k = 20이면 수십 초가 걸릴 수 있습니다(워커, 진행 라벨 "표본 계산"). API는 검증만 합니다.
- **R-8 native 교체**: native 엔진의 출력이 단일 rad가 아니면 `geometry_update` 계약(출력 경로 1개)과 m_2 MESH 입력을 다시 정해야 합니다. 이번에는 경계만 둡니다.

### 23.16 미결(사용자 확인 대상)

1. 화면 기본 방식 = 플랫폼(설정 `doe_generator_default`)으로 둘지.
2. run 실패 기본 = `fail`(재시도로 채움)로 둘지, `continue`로 둘지.
3. ① 쿠션 단독(mesh_only, 조립 폴더 없이 SimLab 메시를 해석 입력으로) — 이번 비범위. native 엔진 단계에서 함께 검토할지.
4. 플랫폼 run 상한 500으로 충분한지.
5. hstbatch 호환 모드를 언제 화면에서 숨길지(native 전환 시점 제안).
6. HyperStudy 4종 → 플랫폼 자동 매핑(기존 API 호출을 플랫폼으로 돌리기)이 필요한지 — 현재 안은 생략(hyperstudy 그대로)입니다.

## 변경 메모(이 문서분 — phase3.md 변경 메모 목록으로 옮김)

- **D3-66 (사용자 VOC·결정 2026-10-19, S18 ① 학습 DOE 플랫폼 동시 생성 — Plan)**: §23.
  - ① S15 §20.3 안 B를 채택합니다. ① `TD_DOE_GEN`에 생성 방식 `platform`(화면 기본)·`hyperstudy`(호환, 코드 무변경)를 둡니다. job_type·step 키 3개·가중은 그대로이고, `HST_GEN_RADIOSS`가 `train_does.generator`로 분기하며 라벨만 "입력 생성(run별)"로 바꿉니다. API 기본: `generator` 생략 → `sampling` 유무로 판단(기존 호출 무변경).
  - ② 플랫폼 표본 = S15 `build_matrix` 8 kind(lhs_opt 추천)입니다. 범위 = ①-2 표, 상한 `train_data.platform_max_runs`(500)입니다. API는 검증·run 수만(lhs_opt는 lhs로 대신 검증, 422 `DOE_SAMPLING_INVALID`), 워커 DG_PREP이 행을 계산해 `train_doe_points`에 저장하고 `doe.json`을 씁니다.
  - ③ run마다 m_1→m_2→m_3을 `run_parallel`로 최대 M개 동시에 실행합니다(사용자 입력, 기본 `platform_parallel_default` 4, 상한 `max_multi_execution`, Job Object 1개). 체인은 ④ `_gen_one`에서 공용 `steps/run_chain.py`로 추출합니다(④ 동작 불변). 형상 생성 경계는 `run_chain.geometry_update` 한 함수입니다(native 교체 지점, 출력 = `{simlab_mesh_name}` 경로).
  - ④ 원본 일치는 다운스트림 규칙만 둡니다: `D/{platform_run_root 기본 approaches/doe_1}/run__NNNNN/{m_1,m_2,m_3}`(run_dir_glob과 일치 검증), input_rel = m_3, samples.csv = DB 반영값(DG_SCAN 직접 작성, PARSED). HyperStudy 런처·json·TCL은 만들지 않습니다.
  - ⑤ 실패 `on_run_failure` = `fail`(기본, `GEN_PARTIAL_FAILED`, 재시도 = 실패·미완료 run만) | `continue`(`PARTIAL_OUTPUT`). 취소 = 그룹 종료 + RUNNING 행 PENDING(워커 + 종료 훅).
  - ⑥ migration `0015_doe_platform_gen`: `train_does.generator`(HYPERSTUDY|PLATFORM)·`sampling` JSONB, 새 `train_doe_points`. 플랫폼 DOE의 `doe_type` = 방식 이름(`LHS_OPT`…), `options` = 표본 입력값이고, `doe_influence`가 `batch_influence`로 등급을 계산합니다.
  - ⑦ API: `TrainDoe.generator`·`sampling`·`gen`, result-table `sampling`(desc_id `td_<kind>`), `/status.limits.configured` 3개·`features.train_doe_platform`. 새 라우트 없습니다.
  - ⑧ 화면: ①-3 방식 세그먼트·방식 드롭다운·`td_*` 설명(§23.10 줄 덮어쓰기)·동시 수·실패 처리 체크. HyperStudy 모드는 기존 UI + 호환 회색 줄입니다. S15 `HS_NOTE` 문구를 바꾸고, S15 §20.2 S1("①은 HyperStudy 4종만")은 호환 모드에만 적용합니다.
  - ⑨ 사용자 추가 결정(native 전환 예정)에 따라 hstbatch 개선·HyperStudy 식별자 조사(S15 E1-8-2)·원본 동작 재현·레거시 4종 매핑·① mesh_only를 비범위로 둡니다.
  - ⑩ 시험 V3-S18-1~10(가짜 SimLab barrier로 동시 실행 하한을 결정적으로 증명, 상한은 trace, 시각 비율 단언 없음), 서버 확인 E1-9-1~5(hstbatch 관찰은 선택).

- **D3-66 보강 (메인, 2026-10-19)**: 프로젝트 문서 `contracts/geometry-engine.md`(native = paicad, 공칭 메시 모핑, TD_DOE_GEN native 모드 `seed?`·`options` 금지)와 대조 — native 엔진은 SimLab 메시를 거치지 않고 메시를 직접 만들 수 있으므로, 교체 경계는 `geometry_update`만이 아니라 `run_chain.build_run_inputs`(m_1 형상 → m_2 include → m_3 조립) 단위에서도 바꿔 끼울 수 있게 둔다(엔진별 구현 선택은 한 곳 `run_chain.select_engine(settings, param_set)`, 이번엔 altair만). R-8 해소 방향.
