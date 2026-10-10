# 동작 불변 리팩터링 실행 계획

작성: Plan, 2026-10-10. 구조 지도·목표 구조·동결 목록은 [architecture.md](architecture.md) §0·§5. 근거(파일:라인)는 architecture.md §1~§3.

## 0. 원칙

1. **동작 불변.** 공개 API·openapi 경로·라우터 함수 이름(operationId)·스키마 클래스 이름·DB 스키마·설정 키·job_type/step_key·오류 코드·사용자 문구를 바꾸지 않는다. 바뀌는 것은 파일 위치와 import 경로뿐이다. 중복 제거는 "값·순서·문구가 같은 코드"를 한 곳으로 모을 때만 한다.
2. **한 단계 = 한 커밋(필요하면 같은 단계 안에서 2~3개).** 각 커밋은 단독으로 `scripts/test-all.sh`를 통과해야 한다(AGENTS.md 커밋 규칙).
3. **이동 커밋에 로직 수정을 섞지 않는다.** 파일 이동은 `git mv` 후 import만 고치는 커밋으로 남겨 `git log --follow`·리뷰가 쉽게 한다. 이동 중 발견한 버그는 메모만 하고 별도 커밋.
4. **시험은 약화하지 않는다.** 정적 시험이 파일 경로·이름을 하드코딩한 곳(architecture.md §1.4 표)은 같은 커밋에서 **새 경로로 정확히 바꾼다**(허용 목록을 넓히거나 검사 대상을 빼지 않는다).
5. **re-export shim은 패키지 `__init__` 재노출에만 쓴다**(`config/`, `schemas/`). 그 밖의 이동은 호출부 import를 고친다. 옛 경로에 빈 shim 모듈을 남기지 않는다.
6. 소유: 백엔드 단계(R*)는 Impl-Backend, 프런트 단계(F*)는 Impl-Frontend. 두 계열은 **파일이 겹치지 않으므로 병렬 진행 가능**(백엔드는 openapi.json을 바꾸지 않으므로 프런트 `generated/`도 그대로).

## 1. 단계 공통 검증

백엔드 단계(R*) 커밋 전:

```bash
scripts/test-all.sh                                   # pytest(백엔드·워커·PG) + openapi 최신 여부 + 프런트 vitest·tsc
python -m physicsai_api.export_openapi && git diff --exit-code backend/openapi.json   # openapi 바이트 동일
git diff --stat -M HEAD                               # 이동이 rename(R100에 가까움)으로 잡히는지 확인
python -m pytest -q --collect-only | tail -1          # 수집된 시험 개수가 직전 커밋과 같거나 많음(줄면 실패)
```

프런트 단계(F*) 커밋 전:

```bash
cd frontend && npm run gen:api && git diff --exit-code src/api/generated/schema.d.ts   # 생성 타입 불변
npm test && npm run lint && npm run build && npm run build:mock
npx vitest run --reporter=dot | tail -3              # 시험 개수가 줄지 않음
```

R0에서 추가하는 기준선 시험(이후 모든 단계에서 자동 확인):

- `test_layering.py` — architecture.md §4.2 규칙 1·2·3·6을 AST로 검사. 규칙 4(서비스 SQL 금지)는 현재 위반 파일을 **고정 허용 목록**으로 시작해 R5에서 빈 목록으로 줄인다.
- `test_step_registry.py` — `HANDLERS` 키 집합이 `job_types.JOB_TYPES`의 (job_type, step_key) 전체와 정확히 같다(누락·잉여 0). 이동 중 등록 누락을 잡는다.
- `test_openapi_operation_ids.py` — 현재 operationId 목록 스냅샷과 같다(라우터 함수 이름 변경 방지; 기존 openapi 동일성 검사의 실패 원인을 더 분명히 보여 준다).

## 2. 단계 목록

우선순위: **1순위** = 이번에 실행, **2순위** = 1순위 완료 후 여유가 있으면 실행, **보류** = 이번 범위에서 하지 않음(§4).

| ID | 내용 | 소유 | 순위 | 선행 | 병렬 |
|---|---|---|---|---|---|
| R0 | 안전망 시험 3종 추가 | Backend | 1 | — | F* 전부와 병렬 |
| R1 | 죽은 코드 삭제·작은 중복 제거 | Backend | 1 | R0 | F*와 병렬 |
| R2 | 워커 실행기 분리(`signals`·`step_context`), step→executor/runtime 역참조 제거, step 간 공유 헬퍼 core로 | Backend | 1 | R1 | F*와 병렬 |
| R3 | 워커 steps 단계별 패키지 + `steps/train.py`·`curation.py` 분할 | Backend | 1 | R2 | F*와 병렬 |
| R4 | API job params·사전조건을 `services/job_params/` 단계별로, 서비스 파일 단계 이름으로 재배치 | Backend | 1 | R1 | R2·R3과 **파일 비중첩 → 병렬 가능**(같은 에이전트면 순차) |
| R5 | 서비스 raw SQL → 저장소 함수, 레이어 규칙 4 허용 목록 비우기 | Backend | 1 | R4 | F*와 병렬 |
| R6 | 마스킹·허용 루트 공통화(`core/masking.py`, `paths.allowed_roots`) | Backend | 1 | R2(워커 import 충돌 회피) | F*와 병렬 |
| R7 | `schemas/__init__.py` 도메인별 분할(재노출) | Backend | 2 | R4 | R6과 병렬 가능 |
| R8 | `config.py` → `config/` 패키지(재노출) | Backend | 2 | R0 | R7과 병렬 가능 |
| R9 | `repositories/jobs.py` → `jobs.py` + `job_lease.py` | Backend | 2 | R5 | — |
| R10 | core 단계 패키지(`stage1_train_data/` …) + `naming.py` | Backend | 2 | R3·R4 | — |
| R11 | 백엔드·워커 시험 파일 폴더·이름 정리(통째 이동만) | Backend | 2 | R3·R10 | — |
| F1 | ① 카드 파일 분할(`TrainCards`·`SolveCards`) | Frontend | 1 | — | R*와 병렬, F2·F3와 병렬 |
| F2 | ④·⑤ 큰 화면 분할(`Stage4`·`Stage5`) | Frontend | 1 | — | R*와 병렬 |
| F3 | ②·③ 카드 파일 분할(`H3dCards`·`ModelCards`) + `useOpenJob` → `hooks/` | Frontend | 1 | — | R*와 병렬 |
| F4 | 프런트 시험 파일 단계별 분할 | Frontend | 1 | F1·F2·F3 | R*와 병렬 |
| F5 | 목 서버 단계별 분할(`mock/phase2.ts`) | Frontend | 2 | F4 | R*와 병렬 |

1순위 합계: 백엔드 R0~R6(7단계), 프런트 F1~F4(4단계).

## 3. 단계 상세

### R0 안전망 시험 (1순위)

- 추가: `backend/tests/test_layering.py`, `worker/tests/test_step_registry.py`, `backend/tests/test_openapi_operation_ids.py`(스냅샷은 시험 파일 안 상수 또는 `backend/tests/data/operation_ids.txt`).
- import 변경: 없음. 코드 변경: 없음.
- 위험: 규칙 4 허용 목록을 넓게 잡으면 의미가 없다 → 현재 위반 6개 파일(`services/{jobs,optimize,phase2_params,studies,train,env_checks}.py`)만.
- 검증: §1 + 의도적 위반(임시로 core에서 `physicsai_api` import) 시 실패하는지 로컬 확인 후 되돌림.

### R1 죽은 코드·작은 중복 (1순위)

| 변경 | 근거 | 비고 |
|---|---|---|
| `repositories/jobs.py:184–196` 인라인 UPDATE 4개를 `train.fail_building_doe`·`curations.fail_building_curation`·`spdm_imports.fail_building_import`·`optimizations.fail_running_opt` 호출로 교체 | 같은 조건·값의 중복, 해당 함수들은 현재 미사용 | WHERE·SET 값이 정확히 같은지 줄 단위 대조. 같은 `conn`·순서 유지 |
| 삭제: `fileutil.copy_into_study`, `config.default_config_path`, `config.Profile`, `state_machine.is_terminal`, `job_types.PHASE2_JOB_TYPES`, `optimize.STUDY_FOLDER_RE`·`METHODS`·`APPROACHES`, `spdm.CMD_META`, `repositories/jobs.TERMINAL_SQL`, `repositories/optimizations.opt_for_job`, `repositories/train.latest_ready_doe`, `repositories/env_checks.FINAL` | 저장소·deploy·scripts·시험 전체에서 정의 외 참조 0(커밋 직전 `git grep -w <이름>`으로 재확인) | 하나라도 참조가 생겼으면 남긴다 |
| 삭제: `worker/physicsai_worker/claim.py` | import 0 | platform.md §21.1 파일 표 언급 → 변경 메모로 처리(Plan 기록 완료) |
| `executor._sha256` → `fileutil.sha256_file` | 같은 알고리즘·같은 hex 출력 | 청크 크기만 다를 수 있음(결과 동일). `checkpoint` 인자 없이 호출 |
| `paths._under` → `paths.is_under`(공개 이름), `spdm.py:19` import 수정 | 비공개 이름 외부 사용 | 모듈 안 호출부 모두 rename |
| `repositories/jobs._ClaimRace` → `ClaimRace`, `runtime.py:28` 수정 | 비공개 이름 외부 사용 | |

- 위험: 낮음. 미사용 판정 오류 → `git grep`·`pytest` 로 확인.

### R2 워커 실행기 분리 (1순위)

| 이동/분리 | 바뀌는 import |
|---|---|
| `executor.py:41–54` → `physicsai_worker/signals.py`(`Cancelled`, `StepSkipped`, `EnterWaitingHpc`) | `steps/verify.py:16`, `steps/predict.py:21`, `steps/train.py:26` → `from ..signals import …`. `executor.py`는 `signals`를 import(재노출 불필요 — 시험은 이 이름을 executor에서 가져오지 않는지 `git grep` 확인) |
| `executor.py:216–565` → `physicsai_worker/step_context.py`(`StepContext`) | `executor.py`가 `from .step_context import StepContext`(모듈 속성으로 남아 `test_phase2_admin.py:223–234`의 `ex_mod.StepContext.run_local` monkeypatch가 같은 클래스 객체를 바꾼다) |
| `runtime.COLLECT_STABLE_INTERVAL_S`(40) → `steps/_collect.py` | `steps/train.py:451,473,476`, `steps/verify.py:95,114,117` → `from . import _collect` 후 `_collect.COLLECT_STABLE_INTERVAL_S`(모듈 속성으로 읽어 monkeypatch 유효). `worker/tests/test_hpc.py:128` monkeypatch 대상을 `physicsai_worker.steps._collect`로 변경 |
| `steps/verify._map_path` → `physicsai_core/hpc/command.py` `map_path` | `steps/verify.py`, `steps/train.py:30,360,384–385` |
| `steps/predict.read_name_value_csv` → `physicsai_core/parsers/name_value.py` | `steps/predict.py`, `steps/train.py:29`, `steps/verify.py:17` |
| `executor.py:165` 지역 import `from .steps import HANDLERS`는 유지(순환 제거 후에도 지연 로딩은 무해). 정리 여부는 구현자 판단 |

- 위험: monkeypatch 대상이 바뀌어 시험이 실제 지연을 쓰면 시간 초과 → 시험 시간이 이전과 비슷한지 확인(`pytest --durations=10`).
- `test_static_security.py:83`(`executor.py`에 `STEP_TIMEOUT`·`timeout_s` 없음) — `run_local`이 `step_context.py`로 옮겨지므로 **검사 대상에 `step_context.py`를 추가**(executor.py 검사도 유지).
- 검증: §1 + `test_layering` 규칙 6(steps → executor/runtime 금지)을 이 커밋에서 활성화.

### R3 워커 steps 단계별 패키지 (1순위)

- 이동(`git mv` + 분할): architecture.md §5.3 트리 그대로. `steps/train.py`(717) → `stage1_train_data/{extract,doe_gen,solve,result_import,resp_extract,_shared}.py`, `steps/curation.py`(323) → `stage2_curation/{source,preview,h3d_curate,t01_curves}.py`, 나머지는 파일 통째 이동.
- 각 하위 모듈은 자기 `HANDLERS` 조각을 두고, `stageN/__init__.py`가 합치며, `steps/__init__.py`가 다섯 패키지 + 공통을 합친다. 병합 순서는 키 충돌이 없으므로 무관하지만 R0 `test_step_registry`로 키 집합 동일 확인.
- 바뀌는 import: `worker/tests/*`의 `from physicsai_worker.steps import package` → `from physicsai_worker.steps.stage3_model import package`. `backend/tests/test_phase2_units.py:318`의 `"worker/physicsai_worker/steps/spdm_import.py"` → `"worker/physicsai_worker/steps/stage2_curation/spdm_import.py"`(basename 허용 목록 310은 `spdm_import.py` 그대로라 변경 불필요).
- 위험: (1) `_shared` 헬퍼의 비공개 이름(`_doe`, `_R` 등)을 여러 하위 모듈이 쓰게 됨 → `_shared.py` 안에서는 밑줄 없는 이름으로 바꿔도 되지만 **동작 코드는 복사하지 말고 import**. (2) 모듈 전역 상태 없음 확인(현재 없음).
- 검증: §1 + `git diff -M --stat`로 `train.py`의 줄이 새 파일들 합과 같은지(삭제·추가 줄 수 대조).

### R4 API job params·서비스 재배치 (1순위)

1. `services/job_params/` 신설(architecture.md §5.2):
   - `base.py`: `_P`, `HpcOverrides`(두 정의가 필드·정규식·범위까지 같음을 확인 후 하나로), `missing()`(두 `_missing` 동일), `invalid_errors()`(= `jobs._invalid`), `invalid_at()`(= `phase2_params._invalid`) — **두 `_invalid`는 시그니처·출력이 달라 합치지 않고 이름만 구분**, `parse_params()`(= `jobs._parse_params`). run_key 정규식은 R10 전까지 `param_sets.RUN_KEY_RE` 하나를 참조(값 같음 확인).
   - `stage3_model.py`·`stage4_predict.py`: `jobs.py:52–125` 모델과 `_prepare`(145–249)의 해당 분기. `P2.check_feature` 호출 위치(1차 분기 앞)는 디스패처에서 그대로 유지.
   - `stage1_train_data.py`·`stage2_curation.py`·`stage5_optimize.py`: `phase2_params.py` 모델과 `prepare`·`after_insert`·`on_retry` 분기.
   - `__init__.py`: `PARAM_MODELS` 병합(키 집합 불변), `prepare(ctx, conn, study, job_type, p)`가 job_type → 단계 모듈 표로 분기. `create_job`의 `DATASET_CREATE` 후처리(`jobs.py:263–274`)는 `stage3_model.after_insert`로 옮기고 호출 순서(insert_job → after_insert → audit) 유지.
2. 서비스 파일 재배치: `train.py`→`stage1_train_data.py`, `curations.py`→`stage2_curation.py`, `optimize.py`→`stage5_optimize.py`, `studies.py:202–287`→`stage3_model.py`, `studies.py:288–485`→`stage4_predict.py`, `studies.py:136–201`+`inspect2.py`→`path_inspect.py`, `phase2_params.py` 삭제(내용은 1로 이동).
3. 라우터: **파일·함수 이름 그대로**, `from ..services import X as svc` 줄만 수정. 한 라우터가 두 서비스 모듈을 쓰게 되면(`routers/studies.py`: studies + path_inspect) 별칭 두 개.
- 바뀌는 import: `routers/*.py` 약 8개, `services/jobs.py`, `services/*` 상호 import, 시험 `from physicsai_api.services.common`(1건, 그대로).
- 정적 시험: `test_phase2_units.py:310–318`의 `phase2_params.py`·`inspect2.py`(basename 허용 + 상대경로 검사) → 새 파일(`job_params/stage2_curation.py`, `path_inspect.py` 등 `spdm_roots`·`spdm.check_spdm_path`를 실제로 쓰는 파일)로 **정확히 교체**.
- 위험: 중간. (1) 검증 순서가 바뀌면 같은 요청에 다른 오류 코드가 나올 수 있음 → 분기 본문은 잘라 붙이기만. (2) 지역 import(`jobs.py:157`, `studies.py:274,386`, `train.py:182–184`)는 그대로 옮기고 정리는 R5. (3) `test_api.py::test_job_params_validation`, `test_phase2_api.py::test_phase2_job_permissions_and_errors`가 오류 응답 본문을 비교하는지 확인.
- 검증: §1(특히 openapi 동일) + `git grep -n "phase2_params\|inspect2"` 0건(문서 제외).

### R5 서비스 raw SQL → 저장소 (1순위)

| 위치 | 옮길 곳 |
|---|---|
| `services/jobs.py:286–297`(list_jobs 조인·필터·페이지) | `repositories/jobs.list_with_study_title(conn, …)` |
| `services/jobs.py:488–500`(HPC 경과 시간) | `repositories/hpc.list_for_job_with_elapsed(conn, job_id)` |
| `services/stage5_optimize.py`(← optimize.py:76–77) | `repositories/jobs.succeeded_predicts(conn, study_id)` |
| `services/studies.py:58–60`(`_stage_status`) | `repositories/jobs.latest_by_type(conn, study_id)` |
| `services/stage3_model.py`(← studies.py:274 `func.now()`) | `repositories/studies.set_final_model(conn, …)` 안에서 `func.now()` |
| `services/stage1_train_data.py`(← train.py:126 `func.now()`, 182–187 hpc_jobs 조회) | `repositories/train.set_tpl_generated(...)`, `repositories/hpc.get_many(conn, ids)` |
| `services/job_params/*`(← phase2_params.py:438–446 on_retry UPDATE) | `repositories/{train,curations,spdm_imports}.set_building_job(conn, id, job_id)` |
| `services/env_checks.py:33–35`(`select 1`, `alembic_version`) | `db/engine.py` 또는 `repositories/system.py` `ping(conn)`, `migration_version(conn)` |

- SQL 문장·정렬·LIMIT·잠금(`for_update`) 그대로 옮김. 반환 형태(dict 키) 동일.
- R0 레이어 규칙 4 허용 목록을 **빈 목록**으로.
- 위험: 낮음~중간(행 → dict 변환 차이). 검증: §1 + 해당 API 시험(`test_api.py` 페이지·대기열, `test_phase2_api.py::test_stage_status_phase2_keys`).

### R6 마스킹·허용 루트 공통화 (1순위)

| 변경 | 바뀌는 import |
|---|---|
| `core/masking.py` 신설: `Masker`(← `parsers/log_errors.py:24`), `BundleMasker`·`SECRET_ENV_PATTERNS`(← `error_bundle.py:15–40`), `bundle_masker(settings) -> BundleMasker`(3곳의 동일 생성식) | `executor.py`/`step_context.py`(Masker), `logsetup.py:16,68`, `services/error_bundle.py:19,67`, `worker/env_check.py:34,217`, `core/error_bundle.py:96`(타입), 시험(`test_phase2_fixes.py::test_masker_contract_rule_and_json_escape`, `test_phase2_admin.py::test_bundle_masker_rules`, `test_logsetup.py`) |
| `paths.allowed_roots(settings, *, imports: bool) -> list[str]` = `[ai_root]` 또는 `[ai_root, *allowed_import_roots]` | architecture.md P7의 11곳. 순서(ai_root 먼저) 유지 |
| 원천 루트: `services/job_params/stage2_curation.resolve_source`·`services/stage2_curation.py`(←curations.py:45)가 `core/curation.source_root_rel`을 쓰도록 | 문자열 값 동일 확인 |

- **두 마스커의 규칙을 하나로 합치지 않는다**(step 로그 마스커에 환경 비밀·쿠키 규칙을 더하는 것은 동작 변경 — 보류 H4).
- 위험: 낮음. 검증: §1 + 마스킹 시험 3개 이름으로 개별 실행.

### R7 `schemas` 분할 (2순위)

- `schemas/__init__.py`(854) → architecture.md §5.2의 10개 모듈. `__init__.py`는 `from .common import *` … 형태로 전부 재노출하고 각 모듈에 `__all__`. 클래스 이름·필드·`model_config` 그대로, 상호 참조(예: `Job`이 `JobStep` 사용)는 모듈 간 import.
- 라우터의 `from .. import schemas as S` / `S.Name` 사용 불변 → 라우터 수정 0.
- 위험: 전방 참조 문자열(`"Model"` 등)이 다른 모듈로 가면 Pydantic 해석 실패 → import 순서·`model_rebuild()` 필요 여부 확인. openapi 동일성으로 검출.

### R8 `config` 패키지화 (2순위)

- `config.py` → `config/{__init__,schema,loader,validate,validate_stages,derived}.py`. `__init__`는 **현재 모듈의 모든 최상위 이름**(밑줄 이름 중 외부 사용분 포함: `git grep "from physicsai_core.config import"`로 목록 확정)을 재노출.
- 정적 시험: `test_phase2_units.py:310`의 basename `"config.py"` → `spdm_roots`를 실제로 포함하는 새 파일 basename(`schema.py`, `validate_stages.py` 등)으로 **정확히 교체**. 일반적인 `"schema.py"`가 다른 패키지에서 우연히 허용되지 않도록, 이 검사를 상대경로 비교로 바꾸는 것도 허용(검사 범위가 줄지 않을 때만).
- 위험: 순환 import(검증이 스키마를, 로더가 검증을 사용) → schema ← validate ← loader 단방향으로.
- 검증: §1 + `deploy/install.ps1:51`과 같은 한 줄 명령 `python -c "from physicsai_core.config import load_config"` 성공.

### R9 `repositories/jobs.py` 분할 (2순위)

- `claim_slot`·`claim_light`·`claim_collecting`·`renew`·`assert_lease`·`release`·`continue_running`·`reap_expired`·`_interrupt`·`_lease_values`·`_mark_started`·`_lease_guard`·`LeaseLost`·`ClaimRace` → `repositories/job_lease.py`. `step_update`·`job_update`·`patch_result`·`add_warning`(lease 토큰 검사 사용)은 `job_lease.py`로(lease 가드와 같은 곳).
- 바뀌는 import: `worker/runtime.py`, `worker/executor.py`·`step_context.py`, `steps/*`(jobs_repo.patch_result 등 사용처), `worker/tests/test_queue_lease.py` 등. 호출부 수가 많으므로 `jobs_repo.` → `lease_repo.` 치환 후 `git grep`으로 잔여 확인.
- 위험: 중간(핵심 동시성 코드). SQL·CAS 조건은 한 글자도 바꾸지 않는다. 검증: §1 + `worker/tests/test_queue_lease.py` 반복 5회.

### R10 core 단계 패키지 (2순위)

- architecture.md §5.1 `stage1_train_data/`~`stage5_optimize/` + `naming.py`. 파일 통째 이동, 내용 무수정(단 `NAME_RE`·`TPL_NAME`·`RUN_KEY_RE`는 `naming.py`로 옮기고 `param_sets.py`가 import).
- 바뀌는 import: API 서비스 약 10개, 워커 steps 약 12개, 시험 약 20줄(`from physicsai_core.train_params` 3, `optimize` 3, `train_tpl` 2, `dataset_split` 2, `parsers.*` 3, `tpl_render` 1, `doe_types` 1 …).
- 정적 시험: `test_phase2_units.py:321` `REPO/"backend"/"physicsai_core"/"spdm.py"` → `…/stage2_curation/spdm.py`. `worker/tests/test_hpc.py:60`는 `hpc/`가 그대로라 변경 없음.
- 위험: 낮음(기계적), 범위 넓음. R3·R4 이후에 해야 import 수정이 한 번으로 끝난다.

### R11 시험 파일 정리 (2순위)

- architecture.md §5.4. **파일 통째 이동·이름 변경만**(함수 분할 없음). 하위 폴더에 `__init__.py` 두지 않음(`--import-mode=importlib`), 루트 `conftest.py`가 하위 폴더에도 적용됨을 확인.
- 고칠 곳: `worker/tests/test_hpc.py:60` `parents[2]` → 폴더 깊이에 맞게(또는 `physicsai_test_support.REPO` 사용), `phase2_helpers` import 6곳.
- 검증: 수집 시험 개수 동일(`--collect-only`), Windows CI `-m windows` 수집 개수 동일.

### F1 ① 카드 파일 분할 (1순위)

- `stages/stage1/TrainCards.tsx`(391) → `CadExtractCard.tsx`, `ParamTableCard.tsx`(+`rowIssue`), `DoeGenCard.tsx`(+`defaultOptions`, `OptionInput`).
- `stages/stage1/SolveCards.tsx`(430) → `DoePicker.tsx`, `RunStateBar.tsx`, `RunTable.tsx`, `SolveCard.tsx`, `ResultCollectCard.tsx`, `RunResponseCard.tsx`.
- 바뀌는 import: `Stage1.tsx:2–3`, `__tests__/phase2.test.tsx:11`(`PBS_NONE_TEXT` ← `../stages/stage1/SolveCards`, 상수는 `SolveCard.tsx`로).
- 위험: 낮음. 검증: §1 프런트 + `npm run screenshots:phase2`(가능하면) 전후 비교.

### F2 ④·⑤ 화면 분할 (1순위)

- `Stage4.tsx`(477) → `ParamSetCard.tsx`(17–200, `FromTrainForm` 포함), `useSamples.ts`(202–224), `PredictWorkspace.tsx`(225–468), `Stage4.tsx`(조립, `MAX_SAMPLE_ROWS`는 쓰는 파일로).
- `Stage5.tsx`(447) → `rules.ts`(`activeRules`·`cleanResponses`, 35–50), `OptInputCard.tsx`, `OptRunCard.tsx`, `OptResult.tsx`(+`HistoryChart`, `toTable`, `fileEntries`), `Stage5.tsx`(조립·상태).
- 바뀌는 import: `__tests__/phase2.test.tsx:13`(`METHOD_DEFAULTS`, `activeRules` ← `../stages/stage5/Stage5`) → 둘 다 `rules.ts`로 옮기고 시험 import 수정.
- 위험: 낮음~중간(상태 끌어올림이 이미 `Stage5`에 있음 — props 그대로 전달). `useEffect` 의존성 배열을 바꾸지 않는다.

### F3 ②·③ 카드 분할 + 훅 위치 (1순위)

- `stage2/H3dCards.tsx`(327) → `H3dPreviewCard.tsx`(+`useH3dPreview`), `H3dCurateCard.tsx`(+`PartList`), `CurationResult.tsx`, `CurationFileList.tsx`. `T01Cards.tsx`(224)는 유지.
- `stage3/ModelCards.tsx`(319) → `ModelRegisterCard.tsx`(+`LogStatusText`, `NAME_RE`), `EvaluateCard.tsx`(+`useModelDetails`).
- `shell/useOpenJob.ts` → `hooks/useOpenJob.ts`(import 수정: `shell/*`, `panels/*` 사용처).
- 위험: 낮음.

### F4 프런트 시험 단계별 분할 (1순위)

- `__tests__/phase2.test.tsx`(495)의 `describe` 블록을 그대로 옮김: 26–76 → `stepper.test.tsx`(V2-FE-1·FeatureGate), 77–187 → `stage1.test.tsx`, 188–253 → `stage2.test.tsx`, 254–331 → `stage5.test.tsx`, 332–390 → `ops.test.tsx`, 391–495 → `links.test.tsx`. 공용 준비 코드(1–25)는 `test/` 보조 파일로.
- `__tests__/stages.test.tsx` → `stage3.test.tsx`(5–45), `stage4.test.tsx`(46–107).
- `describe` 이름(V-ID) 그대로 — Verifier 체크리스트가 V-ID로 찾는다.
- 검증: 시험 개수 동일.

### F5 목 서버 분할 (2순위)

- `mock/phase2.ts`(965, `Phase2Mock`) → `mock/stage1.ts`, `mock/stage2.ts`, `mock/stage5.ts`, `mock/ops.ts` + 공용 상수(`STAGE_LABEL`, `FEATURE_MISSING`, `DOE_TYPES`)는 `mock/data.ts`로. `mock/server.ts`의 `handle`(475~) 라우팅은 유지하고 위임 대상만 교체.
- 위험: 중간(목 상태 공유). `mockContract.test.ts`(목 ↔ openapi) + `npm run build:mock` + `dev:mock` 수동 확인.

## 4. 보류 항목(이번 범위에서 하지 않음)

| ID | 항목 | 보류 이유 |
|---|---|---|
| H1 | Study 상대경로 리터럴 61개를 `core/study_layout.py` 함수로 | 같은 경로가 끝 `/` 유무가 다르게 저장된다(예: `steps/train.py:534`·`:630`의 `result_rel=f"01_train/results/{id}/{rk}/"` vs `:320` 끝 `/` 없음). DB에 저장되는 값이라 함수화 중 실수하면 데이터 형태가 바뀐다. R10 이후 별도 계획으로 |
| H2 | `backend/tests/fake_tools/` 이동(예: `tests/fixtures/`) | 배포 스크립트 3곳과 CI(`ci.yml:167`)가 경로 의존 — 배포 변경이 됨 |
| H3 | 여러 주제가 섞인 시험 파일의 함수 단위 분할(`test_api.py`, `test_core_units.py`, `test_phase2_units.py`, `test_verifier_fixes*.py`, `test_phase2_fixes.py`), `physicsai_test_support.py` 분할 | 효과 대비 변경량 큼, fixture 노출 경로(`from physicsai_test_support import *`) 의존 |
| H4 | `Masker`와 `BundleMasker` 규칙 통합 | step 로그에 새 마스킹 규칙이 적용되는 **동작 변경**. 계약 결정 필요 |
| H5 | `verify.collect`와 `ts_collect`의 안정성 대기 루프 통합 | 수집 범위가 다름(평면 vs 재귀·링크 제외) — 합치면 동작 변경 |
| H6 | `styles.css`(2,076) 분할 | 선택자 순서·우선순위가 바뀌면 화면이 달라짐. 자동 시각 회귀 시험 없음 |
| H7 | `usePathField` 등 폼 상태 공용 훅(`path`/`ok` 쌍 6곳) | 카드마다 검증 흐름이 조금씩 달라 공용화가 곧 동작 변경 위험 |
| H8 | 라우터 파일을 단계 이름으로 변경 | 라우터 파일 이름은 동작과 무관하지만 operationId·태그 혼동 위험 대비 이득 작음(서비스가 단계 이름이면 충분) |
| H9 | `core/error_bundle.py:117` 접두 비교(`startswith`) 수정 | 버그 수정 = 동작 변경. 리팩터링과 분리해 Impl-Backend 별도 커밋(시험 포함)으로 즉시 처리 권장 |

## 5. 완료 후

- Impl 에이전트는 단계마다 커밋 해시와 "옮긴 파일 → 새 위치" 목록을 보고하고, Plan이 architecture.md §1 지도를 갱신한다.
- Verifier: platform.md §22·phase2.md §20 체크리스트를 전체 재판정(시험 이름이 바뀐 항목은 V-ID로 대조), openapi·생성 타입 diff 0을 증적으로 남긴다.
