# 소스 구조 지도와 목표 구조

작성: Plan, 2026-10-10. 기준 커밋 `b4f7817`(브랜치 `claude/phase3`, CI 녹색).
목적: 1·2차와 운영 준비가 여러 에이전트에 의해 빠르게 쌓이면서 고르지 않게 된 소스 배치를 **동작을 바꾸지 않고** 단계별로 찾고 고치기 쉽게 정리한다.
실행 순서와 커밋 단위는 [refactor-plan.md](refactor-plan.md)에 적었다. 이 문서는 "지금 어디에 무엇이 있나"와 "어디로 옮기나"를 다룬다.

---

## 0. 동결 목록(리팩터링에서 바꾸지 않는 것)

| 대상 | 이유·확인 방법 |
|---|---|
| HTTP 경로·메서드·요청/응답 모양 | `backend/openapi.json` 재생성 결과가 바이트 단위로 같아야 한다 |
| **라우터 함수 이름** | FastAPI 기본 `operationId` = `<함수 이름>_<경로>_<메서드>`(예: `admin_config_physicsai_api_admin_config_get`). 함수 이름을 바꾸면 openapi와 프런트 생성 타입이 바뀐다 |
| `schemas`의 Pydantic 클래스 이름 | openapi `components.schemas` 키 |
| DB 스키마·migration(`migrations/**`, `db/tables.py`의 테이블·컬럼·CHECK) | `MIGRATION_HEAD`, `test_phase2_db.py` |
| 설정 YAML 키, `config/*.yaml` | `test_config.py`, `test_ops_config.py`, 예시 YAML 시험 |
| job_type, step_key, 오류 코드, 사용자 문구 | `job_types.py` 표, 워커 `HANDLERS` 키 집합 |
| 외부에서 부르는 진입점 | `physicsai_core.config.load_config`(`deploy/install.ps1:51`, `deploy/update.ps1:21`), `python -m physicsai_api.serve`, `python -m physicsai_worker`, `physicsai_api.export_openapi.render`·`build_openapi`(`scripts/test-all.sh:10`, `scripts/test-all.ps1:7`) |
| `backend/tests/fake_tools/` 위치 | `deploy/collect-offline.sh:33`, `deploy/collect-offline.ps1:33`, `deploy/demo/demo_setup.py:67`이 이 경로를 쓴다 |

허용: 파일 이동·분리·이름 변경으로 **import 경로만** 바뀌는 것, 죽은 코드 삭제, 같은 동작의 중복을 한 함수로 합치는 것(값·순서·문구가 같을 때만).

---

## 1. 현재 구조 지도

백엔드·워커·시험(§1.1~§1.4)은 리팩터링 R0~R11 실행 후 기준(브랜치 `claude/phase3`, 커밋 `e125e68`), 프런트·스크립트(§1.5~§1.6)는 기준 커밋 `b4f7817` 그대로. 줄 수는 `wc -l` 기준. "단계"는 ①학습데이터 생성 ②데이터 정리 ③데이터셋·모델 ④단일 예측 ⑤최적화, "공통"은 단계 무관. 리팩터링 전 위치·문제는 §2·§3(근거)과 refactor-plan.md에 남긴다.

### 1.1 `backend/physicsai_core` (공용 라이브러리)

| 위치 | 줄 | 단계 | 책임 |
|---|---:|---|---|
| `config/` | 999 | 공통 | `schema.py`(424: Settings·*Cfg·키 상수·ConfigIssue·LoadedConfig), `rules.py`(41: 경로 문자열 규칙·`_compile`), `validate.py`(235: `validate_settings`), `validate_stages.py`(77: `_validate_phase2`), `loader.py`(99: `load_config`·`load_config_dict`·`absent_keys`·`config_warnings`), `derived.py`(43: Altair 파생·`effective_altair`·`redacted_settings`), `__init__`(80: 공개 이름 전부 재노출 — `from physicsai_core.config import …` 경로 불변) |
| `paths.py` | 307 | 공통 | 경로 검사(§17.3, B20·B23), `allowed_roots(settings, imports=)`, `is_under`, Study 경로, 백업 이동, 표시 경로 |
| `masking.py` | 65 | 공통 | `Masker`(step 로그), `BundleMasker`·`SECRET_ENV_PATTERNS`(오류 묶음·운영 로그), `bundle_masker(settings)` |
| `naming.py` | 9 | 공통 | ①·④ 공용 이름 규칙 `NAME_RE`·`RUN_KEY_RE`·`TPL_NAME`(`stage4_predict/param_sets`가 import해 속성 유지) |
| `commands.py`(277), `job_types.py`(218), `tpl_render.py`(56), `childenv.py`, `errors.py`, `fileutil.py`, `limits.py`, `logsetup.py`, `state_machine.py`, `features.py` | | 공통 | |
| `env_check.py`(47), `error_bundle.py`(110) | | 공통(운영) | 환경 점검 항목·오류 묶음 항목 생성(마스커는 `masking.py`) |
| `parsers/` | | 공통 | `log_errors.py`(21: `ErrorDetector`), `name_value.py`(20: `read_name_value_csv`, ①·④ 공용) |
| `hpc/` | | 공통 | PBS 게이트웨이(`gateway`, `command`(+`map_path`), `adapter`, `none`) |
| `db/tables.py`(575), `db/schema_0001.py`(393), `db/engine.py` | | 공통 | SQLAlchemy Core 메타데이터 |
| `db/repositories/jobs.py` | 312 | 공통 | 작업 생성·조회(`list_with_study_title`, `succeeded_predicts`, `latest_by_stage`)·종료 부수효과(엔터티 저장소 `fail_*` 호출)·취소·대기열 이동 |
| `db/repositories/job_lease.py` | 391 | 공통 | claim/renew/release(CAS lease)·리퍼·`LeaseLost`·`ClaimRace`·lease 토큰으로 지키는 `step_update`/`job_update`/`patch_result`/`add_warning`. 의존은 job_lease → jobs 한 방향 |
| `db/repositories/system.py` | 17 | 공통(운영) | `ping`, `migration_version`(헬스 체크) |
| `db/repositories/*.py` 나머지 | 21–176 | 엔터티별 | `hpc.list_for_job_with_elapsed`·`get_many`, `studies.set_final_model`, `train.set_tpl_generated`, `{train,curations,spdm_imports}.set_building_job` 포함 |
| `stage1_train_data/` | | ① | `train_params.py`(233), `train_tpl.py`(84), `doe_types.py`(94), `doe_samples.py`(162) |
| `stage2_curation/` | | ② | `curation.py`(253), `spdm.py`(214) |
| `stage3_model/` | | ③ | `dataset_split.py`(73), `loss.py`(140), `score.py`(26) |
| `stage4_predict/` | | ④ | `param_sets.py`(345), `nearest.py`(82), `xydata.py`(67) |
| `stage5_optimize/` | | ⑤ | `optimize.py`(278) |

### 1.2 `backend/physicsai_api` (FastAPI)

| 위치 | 줄 | 단계 | 책임 |
|---|---:|---|---|
| `routers/*.py` 15개 | 17–86 | 자원별 | 파일·함수 이름 그대로(operationId 동결). 서비스 호출만, SQL·`physicsai_core.db` 없음(`test_layering` 규칙 3) |
| `schemas/` | 970 | 전 단계 | `common`(44), `shell`(199), `jobs`(126), `studies`(68), `stage1_train_data`(148), `stage2_curation`(78), `stage3_model`(78), `stage4_predict`(106), `stage5_optimize`(62), `ops`(46). `__init__`가 전부 재노출(`S.Name` 불변) |
| `services/jobs.py` | 347 | 전 단계 | 작업 생성 오케스트레이션(`job_params` 호출)·조회·로그·취소·재시도·대기열·산출물·HPC·input.zip |
| `services/job_params/` | 812 | 전 단계 | `base.py`(48: `_P`, `HpcOverrides`, `prerequisite_missing`, `invalid_errors`(1차 형식), `invalid_at`(2차 형식), `check_feature`), `stage1_train_data.py`(181), `stage2_curation.py`(209, `resolve_source`), `stage3_model.py`(146, DATASET_CREATE 생성·재시도 후처리 포함), `stage4_predict.py`(92), `stage5_optimize.py`(84), `__init__.py`(52: `PARAM_MODELS` 병합, `parse_params`, `prepare`(check_feature 먼저)·`after_insert`·`on_retry` 디스패치) |
| `services/studies.py` | 111 | 공통 | Study 목록·조회·생성·수정·보관, 단계 상태 |
| `services/path_inspect.py` | 165 | ①②③④ | 경로 확인(1차 용도 + 2차 용도), `inspect_model_folder`, `starters_in` |
| `services/stage1_train_data.py`(208), `stage2_curation.py`(131), `stage3_model.py`(103), `stage4_predict.py`(229), `stage5_optimize.py`(88) | | 단계별 | ① 파라미터 표·tpl·DOE·run, ② 원천·큐레이션·가져오기 조회, ③ 데이터셋·모델·Final, ④ 파라미터 세트·샘플·예측 확인·①→④, ⑤ 최적화 조회·응답 후보 |
| `services/common.py`(217), `system.py`(132), `env_checks.py`(152), `error_bundle.py`(95) | | 공통·운영 | raw SQL 없음(`test_layering` 규칙 4, 예외 0) |
| `auth.py`(205), `main.py`(133), `context.py`, `deps.py`, `demo.py`(164), `serve.py`, `export_openapi.py` | | 공통 | |

### 1.3 `worker/physicsai_worker`

| 위치 | 줄 | 단계 | 책임 |
|---|---:|---|---|
| `executor.py` | 198 | 공통 | `LeaseKeeper`, `Executor`(step 체인 실행). `StepContext`를 import해 모듈 속성으로 둔다(시험 monkeypatch 대상) |
| `step_context.py` | 383 | 공통 | `StepContext`: 경로·로그·진행률·산출물·`run_local`·`run_fanout`(로거 이름 `physicsai_worker.executor` 유지) |
| `signals.py` | 17 | 공통 | 제어 예외 `Cancelled`, `StepSkipped`, `EnterWaitingHpc` |
| `runtime.py`(369), `env_check.py`(236), `limiter/`, `resources.py`, `housekeeping.py`, `lockfile.py`, `__main__.py` | | 공통 | (`claim.py` 삭제) |
| `steps/__init__.py`, `common.py`, `launcher.py`, `_collect.py`(`COLLECT_STABLE_INTERVAL_S`) | | 공통 | `HANDLERS` = 다섯 단계 패키지 병합(`test_step_registry`가 job_types와 대조) |
| `steps/stage1_train_data/` | 781 | ① | `_shared.py`(74: `TPL_REL`·`TPL_NAME`·`_doe`·`_D`·`_R`·`_match_files`·`_summary`·`_write_collected_json`), `extract.py`(①-1), `doe_gen.py`(①-3), `solve.py`(①-4), `result_import.py`(①-5), `resp_extract.py`(①-6) |
| `steps/stage2_curation/` | 461 | ② | `source.py`(원천 루트·대상 수집·큐레이션 등록 공용), `preview.py`(②-1·②-3), `h3d_curate.py`(②-2), `t01_curves.py`(②-4), `spdm_import.py`(G) |
| `steps/stage3_model/` | | ③ | `dataset.py`, `package.py`, `model_register.py`, `evaluate.py` |
| `steps/stage4_predict/` | | ④ | `predict.py`(248), `verify.py`(157) |
| `steps/stage5_optimize/` | | ⑤ | `optimize.py`(158) |

steps는 `executor`·`runtime`을 import하지 않는다(`test_layering` 규칙 6, 예외 0). 단계 간 step import 없음(`map_path` → `core/hpc/command`, `read_name_value_csv` → `core/parsers/name_value`).

### 1.4 시험

| 위치 | 내용 |
|---|---|
| `backend/tests/physicsai_test_support.py`(677), `conftest.py`, `fake_tools/`, `data/` | 그대로(공용 픽스처, 배포 시연 모드 공유 §0). `data/operation_ids.txt` = operationId 스냅샷 |
| `backend/tests/helpers_stage1.py` | ← `phase2_helpers.py`(① 시험 보조) |
| `backend/tests/common/` | `test_config`, `test_ops_config`, `test_logsetup`, `test_auth`, `test_db_schema`, `test_db_phase2_schema`(← `test_phase2_db`), `test_openapi`, `test_openapi_operation_ids`(신규), `test_static_security`, `test_layering`(신규, §4.2 규칙 1·2·3·4·6) |
| `backend/tests/` 루트 | 여러 주제 혼합으로 보류(H3): `test_api`, `test_core_units`, `test_demo`, `test_phase2_api`, `test_phase2_units`, `test_verifier_fixes` |
| `worker/tests/runtime/` | `test_queue_lease`, `test_limiter`, `test_windows_job`, `test_hpc`, `test_step_registry`(신규) |
| `worker/tests/stage1_train_data/test_stage1_train.py`, `stage2_curation/test_stage2_curation.py`, `stage5_optimize/test_stage5_optimize.py`, `ops/test_ops_admin.py`, `e2e/{test_e2e_chain,test_demo_e2e}.py` | ← `test_phase2_{train,curation,optimize,admin}.py`, e2e 2개 |
| `worker/tests/` 루트 | 보류(H3): `test_phase2_fixes`, `test_verifier_fixes_worker` |
| 정적 시험의 경로 | `test_phase2_units.py` SPDM 검사는 저장소 상대경로로 정확히 대조(`core/stage2_curation/spdm.py`, `core/config/{schema,validate}.py`, `api/services/{job_params/stage2_curation,path_inspect}.py`, `worker/steps/stage2_curation/spdm_import.py` 등), `test_static_security.py` timeout 검사는 `executor.py`+`step_context.py`, `test_hpc.py`는 `REPO` 기준, COLLECT 간격 monkeypatch 대상은 `physicsai_worker.steps._collect` |

### 1.5 `frontend/src` (7,900줄 남짓, 생성물 제외)

| 위치 | 줄 | 문제 |
|---|---:|---|
| `api/`(client 147, endpoints 137, types 261, generated) | | 경계 양호: 화면 코드에 `fetch` 없음, `mock`은 `main.tsx:10` 동적 import와 `test/render.tsx`만 |
| `stages/stage4/Stage4.tsx` | **477** | `ParamSetCard`(17) + `FromTrainForm`(133) + `useSamples`(202) + `PredictWorkspace`(225) + `Stage4`(469) |
| `stages/stage5/Stage5.tsx` | **447** | `activeRules`·`cleanResponses`(35–50) + `OptInputCard`(51) + `OptRunCard`(99) + `HistoryChart`(236) + `OptResult`(291) + `Stage5`(411) |
| `stages/stage1/SolveCards.tsx` | 430 | `DoePicker`·`RunStateBar`·`RunTable`·`SolveCard`·`ResultCollectCard`·`RunResponseCard` 6개 |
| `stages/stage1/TrainCards.tsx` | 391 | `CadExtractCard`·`ParamTableCard`·`DoeGenCard` |
| `stages/stage2/H3dCards.tsx`(327), `stages/stage3/ModelCards.tsx`(319), `DatasetCards.tsx`(273) | | 카드 여러 개가 한 파일. phase2.md §19.2 파일 표(`CadExtractCard`, `SolveCard`, …)는 카드별 파일을 전제 |
| `mock/phase2.ts`(965), `mock/server.ts`(798), `mock/data.ts`(426) | | 이력 기준 이름, 단계 경계 없음 |
| `__tests__/phase2.test.tsx` | 495 | `describe`는 이미 단계별(V2-FE-2 ①, -3 ②, -4 ⑤, -5 환경 점검, -6 연결) — 파일만 이력 기준 |
| `shell/useOpenJob.ts` | 27 | 훅이 `shell/`에 있음 |
| `styles.css` | 2,076 | 전역 한 파일 |
| 단계 간 import | | `pages/ImportLanding.tsx:8` → `stages/stage2/Sources`(`SpdmSummary`) 1건뿐 — 양호 |

### 1.6 `scripts`, `deploy`, `config`

- `scripts/`: 얇은 래퍼(4–17줄) + `ci_annotate.py`. 정리 불필요.
- `deploy/`: Windows 배포 ps1·bat + `demo/demo_setup.py`(574, 단일 CLI 스크립트, `physicsai_*`를 import하지 않음). 정리 대상 아님(시험 `test_demo.py`·`test_phase2_units.py:340–399`가 내용 검사).
- `config/`: `platform.example.yaml`(271), `platform.demo.yaml`(118, `demo_setup.py`가 채우는 템플릿). 스키마의 **단일 출처는 `physicsai_core/config/schema.py`**(리팩터링 전 `config.py`)(코어 안 다른 설정 `BaseModel` 없음). 프런트 `mock/phase2.ts:55` `FEATURE_MISSING`은 `features.py`의 목 사본(목 계약 시험 대상, 의도된 중복).

---

## 2. 의존 방향 점검 결과

리팩터링 전(`b4f7817`) 점검 결과. 위반은 R1~R5에서 모두 없앴고 지금은 `backend/tests/common/test_layering.py`가 규칙 1·2·3·4·6을 예외 없이 강제한다.

| 규칙 | 결과 | 근거 |
|---|---|---|
| core → api/worker import 금지 | 위반 없음 | `grep -rn "physicsai_(api|worker)" backend/physicsai_core` 0건 |
| api ↔ worker 상호 import 금지 | 위반 없음 | 0건 |
| 라우터에 SQL 금지 | 위반 없음 | `test_static_security.py:87` |
| 서비스는 저장소만 통해 DB 접근 | **위반 6곳** | `services/jobs.py:22,286–297,488–500`, `optimize.py:16,76–77`, `phase2_params.py:24,438–446`, `studies.py:22,58–60`, `train.py:182–187`, `env_checks.py:33–35`(헬스 체크) |
| 워커 step → executor 역참조 | **숨은 순환** | `steps/{verify.py:16, predict.py:21, train.py:26}`가 `..executor`에서 예외를 import, `executor.py:165`는 순환을 피하려고 `from .steps import HANDLERS`를 함수 안에서 import |
| step → runtime 역참조 | **위반 2곳** | `steps/train.py:451`, `steps/verify.py:95`가 상수 하나 때문에 `runtime`을 지역 import |
| step ↔ step(단계 간) | **3곳** | `steps/train.py:29`(① → ④ `predict.read_name_value_csv`), `steps/train.py:30`(① → ④ `verify._map_path`, 비공개 이름), `steps/verify.py:17` |
| core 비공개 이름 외부 사용 | 2곳 | `spdm.py:19`가 `paths._under`, `runtime.py:28`이 `jobs._ClaimRace` |

---

## 3. 주요 문제(근거)

| # | 문제 | 근거 |
|---|---|---|
| P1 | ① 워커 step 22개가 한 파일 | `worker/physicsai_worker/steps/train.py` 717줄, 작업 5종(`HANDLERS` 700–717) |
| P2 | job params·사전조건이 "1차/2차"로 쪼개져 두 파일에 중복 | `services/jobs.py:52`·`phase2_params.py:37` `_P` 중복, `HpcOverrides` 중복(`jobs.py:103`·`phase2_params.py:41`), `_missing` 중복(`jobs.py:138`·`phase2_params.py:188`), `_invalid` 시그니처 다른 동명 함수(`jobs.py:127`·`phase2_params.py:192`), run_key 정규식 3벌(`jobs.py:45` `RUN_KEY_RE`, `phase2_params.py:34` `RUN_KEY_PATTERN`, `param_sets.RUN_KEY_RE`), 단계별 if 사슬 2개(`jobs.py:145–249`, `phase2_params.py:267–406`) |
| P3 | 서비스 파일이 단계와 어긋남 | `services/studies.py` 485줄에 ③·④·F, 이력 이름 `phase2_params.py`·`inspect2.py` |
| P4 | 서비스에 raw SQL·테이블 직접 import | §2 표 6곳 |
| P5 | `executor.py`가 실행기·step 컨텍스트·프로세스 실행·제어 예외를 모두 가짐 + 숨은 순환 | `executor.py` 574줄, §2 |
| P6 | 마스킹 구현 3벌·생성 코드 3벌, 위치 부적절 | `parsers/log_errors.py:24` `Masker`(패턴만, step 로그), `error_bundle.py:20` `BundleMasker`(패턴+고정 규칙+환경 비밀), `logsetup.py:22` `MaskingFilter`. `BundleMasker(s.logging.mask_patterns, s.auth.cookie_name, s.database.url_env)` 동일 생성식이 `logsetup.py:68`, `services/error_bundle.py:67`, `worker/env_check.py:217` |
| P7 | 경로 허용 루트 목록·Study 상대경로 문자열 산재 | `[ai_root, *allowed_import_roots]` 11곳(`services/inspect2.py:36,43,52`, `phase2_params.py:273,283,331`, `jobs.py:183`, `steps/train.py:75,168,552`, `steps/model_register.py:35`). `"0N_xxx/..."` 리터럴 61개·18파일(최다 `steps/train.py` 12, `phase2_params.py` 8). 원천 루트 해석 3벌(`core/curation.py:24 source_root_rel`, `services/phase2_params.py:220–236`, `services/curations.py:45`) |
| P8 | 죽은 코드·중복 | 미사용: `repositories/{curations.py:35, train.py:73, spdm_imports.py:33, optimizations.py:37}` `fail_building_*`/`fail_running_opt` — 같은 UPDATE가 `repositories/jobs.py:184–196`에 인라인 중복. `fileutil.copy_into_study`(55), `config.default_config_path`(470)·`Profile`(897), `state_machine.is_terminal`(77), `job_types.PHASE2_JOB_TYPES`(180), `optimize.STUDY_FOLDER_RE/METHODS/APPROACHES`(22–27), `spdm.CMD_META`(22), `repositories/jobs.TERMINAL_SQL`(41), `repositories/optimizations.opt_for_job`(24), `repositories/train.latest_ready_doe`(129), `repositories/env_checks.FINAL`(19), `worker/claim.py`. `executor._sha256`(566) = `fileutil.sha256_file`(21) |
| P9 | 큰 단일 파일 | `config.py` 897, `schemas/__init__.py` 854, `repositories/jobs.py` 653, `physicsai_test_support.py` 677, 프런트 `Stage4.tsx` 477·`Stage5.tsx` 447·`SolveCards.tsx` 430, `mock/phase2.ts` 965·`mock/server.ts` 798 |
| P10 | 이력 기준 이름(phase2·verifier_fixes) | 서비스 2개, 시험 8개, 프런트 목·시험 2개 — 단계로 찾을 수 없음 |

부수 발견(동작 변경이라 리팩터링 범위 밖, 별도 결정 필요): `core/error_bundle.py:117`가 `os.path.realpath(p).startswith(os.path.realpath(study_root))`로 Study 하위 여부를 판정 — 접두 비교라 `…/abc`와 `…/abc2`를 구분하지 못한다. `paths._under`로 바꾸는 것은 동작 수정이므로 Impl-Backend 별도 커밋(버그 수정 + 시험)으로 처리한다. → 처리됨: `d457f4d`(`is_under(real(p), real(study_root))`, 회귀 시험 `test_core_units::test_error_bundle_commands_head_requires_path_inside_study`).

---

## 4. 명명 규칙

### 4.1 단계 ↔ 이름

| 단계 | 패키지·폴더 이름 | job_type | 프런트 폴더 |
|---|---|---|---|
| ① 학습데이터 생성 | `stage1_train_data` | `TD_*` | `stages/stage1` |
| ② 데이터 정리(+G SPDM 가져오기) | `stage2_curation` | `CU_*`, `SPDM_IMPORT` | `stages/stage2` |
| ③ 데이터셋·모델 | `stage3_model` | `DATASET_CREATE`, `PACKAGE_EXPORT`, `MODEL_REGISTER`, `EVALUATE` | `stages/stage3` |
| ④ 단일 예측(+F ①→④ 파라미터 세트) | `stage4_predict` | `PREDICT`, `PREDICT_VERIFY` | `stages/stage4` |
| ⑤ 최적화 | `stage5_optimize` | `OPTIMIZE` | `stages/stage5` |
| 운영(환경 점검·오류 묶음·관리) | `ops` | — | `pages/AdminEnvCheck` |

- 단계 패키지 안의 파일은 하위 단계 **의미**로 이름 짓고 모듈 docstring 첫 줄에 번호를 쓴다: `"""①-3 TD_DOE_GEN: DOE·Radioss 입력 생성(phase2 §6.4)."""`.
- `phase2`, `p2`, `2`(예: `inspect2`), `fixes`, `verifier_fixes` 같은 **이력 이름은 쓰지 않는다**.
- 시험 파일: `test_<단계 또는 공통 주제>_<대상>.py`(예: `test_stage1_doe_gen.py`, `test_common_paths.py`).

### 4.2 레이어 규칙(R0에서 시험으로 강제)

```
frontend ──HTTP──▶ physicsai_api ──▶ physicsai_core ◀── physicsai_worker
                    routers → services → core.db.repositories → core.db.tables
```

1. `physicsai_core`는 `physicsai_api`·`physicsai_worker`를 import하지 않는다.
2. `physicsai_api`와 `physicsai_worker`는 서로 import하지 않는다.
3. `routers`는 `services`·`schemas`·`deps`만 쓰고 SQL·`physicsai_core.db`를 모른다(기존 시험).
4. `services`는 `sqlalchemy`·`physicsai_core.db.tables`를 import하지 않는다(저장소 함수만). 예외 없음(R5 이후). R5 전까지는 현재 위반 파일 목록을 허용 목록으로 고정(늘어나면 실패).
5. 단계 패키지(`stageN_*`)는 공통과 자기 단계만 import한다. 단계 간 공유가 필요하면 공통으로 올린다. 예외: `stage4_predict` 가 `stage1_train_data` 결과(DOE)로 파라미터 세트를 만드는 F 흐름은 **core 저장소/공통 모듈**을 통해서만.
6. 워커 `steps/**`는 `executor`·`runtime`을 import하지 않는다(제어 예외는 `signals`, 상수는 `steps/_collect.py`).

---

## 5. 목표 구조

이름 옆 `←`는 현재 위치. 표시 없는 파일은 그대로.

### 5.1 `backend/physicsai_core`

```
physicsai_core/
  config/                      ← config.py (패키지로; __init__가 기존 공개 이름 전부 재노출 → import 경로 불변)
    __init__.py
    schema.py                  ← config.py:22–440 (Settings와 *Cfg)
    loader.py                  ← 441–560 (load_config, load_config_dict, absent_keys, config_warnings, 경로 문자열 헬퍼)
    validate.py                ← 569–786 (validate_settings, _compile)
    validate_stages.py         ← 787–860 (_validate_phase2 — 함수 이름은 유지, 파일 이름만 단계 기준)
    derived.py                 ← 861–897 (derived_hstpy_path, derived_altair_home, effective_altair, redacted_settings)
  paths.py                     (+ allowed_roots(settings, *, imports) 헬퍼, _under → is_under 공개)
  masking.py                   ← parsers/log_errors.Masker + error_bundle.BundleMasker + bundle_masker(settings) 팩토리
  commands.py, childenv.py, errors.py, fileutil.py, limits.py, logsetup.py,
  state_machine.py, job_types.py, features.py, env_check.py, error_bundle.py, tpl_render.py
  parsers/log_errors.py        (ErrorDetector만), parsers/name_value.py ← steps/predict.read_name_value_csv
  hpc/                         (+ command.map_path ← steps/verify._map_path)
  db/
    tables.py, schema_0001.py, engine.py
    repositories/
      jobs.py                  (CRUD·조회·대기열·취소·이동, 종료 부수효과는 엔터티 저장소 함수 호출)
      job_lease.py             ← jobs.py claim_*/renew/release/reap_expired/_interrupt/assert_lease/LeaseLost/ClaimRace
      … (엔터티별 그대로)
  stage1_train_data/           ← train_params.py, train_tpl.py, doe_types.py, doe_samples.py
  stage2_curation/             ← curation.py, spdm.py
  stage3_model/                ← dataset_split.py, parsers/loss.py, parsers/score.py
  stage4_predict/              ← param_sets.py, nearest.py, parsers/xydata.py
  stage5_optimize/             ← optimize.py
```

`tpl_render.py`는 ①(`train_tpl`)과 ④(`param_sets`, 예측 step)가 함께 쓰므로 공통에 남긴다. ①이 ④ 모듈에서 가져다 쓰는 이름(`param_sets.NAME_RE`·`TPL_NAME`·`RUN_KEY_RE`)은 공통 `naming.py`로 올리고 `param_sets.py`는 그것을 import한다(규칙 4.2-5: 단계 간 직접 import 금지). 값은 그대로 옮긴다.

### 5.2 `backend/physicsai_api`

```
physicsai_api/
  routers/                     (파일·함수 이름 그대로 — operationId 동결. import 대상 서비스만 바뀜)
  schemas/
    __init__.py                (from .x import * 재노출; 라우터의 `S.Name` 사용 불변)
    common.py                  ← Req, Resp, ErrorBody, ErrorResponse, Health, Me, Project
    shell.py                   ← Status*, Queue*, Resource*, Gpu*, Notification*, AdminConfig
    jobs.py                    ← JobSummary, JobStep, Job, JobCreate, RetryRequest, LogChunk, Artifact, HpcJob, HpcSummary
    studies.py                 ← Study*, PathInspect*, PathProblem
    stage1_train_data.py       ← TrainParam*, TrainCad, TrainTpl, TrainSetup, DoeField, DoeType, RunStateCounts, TrainDoe, TrainRun*
    stage2_curation.py         ← SourceRef, CurationSource, Curation, CurationFile*, SpdmImport
    stage3_model.py            ← Dataset, Model, ModelPatch, FinalModelRequest, StudyDetail
    stage4_predict.py          ← ParamSet*, Parameter, ResponseDef, TplParam, SampleRow, SamplesPage, PredictCheck*, OutOfRange, Rounded, Nearest
    stage5_optimize.py         ← Optimization, Candidate*, ResponseCandidates
    ops.py                     ← EnvCheck*
  services/
    common.py, system.py
    studies.py                 (Study CRUD + inspect_path; inspect2.py 흡수 → 이름 path_inspect.py로 분리 가능)
    path_inspect.py            ← studies.py:136–201 + inspect2.py
    jobs.py                    (생성 오케스트레이션·조회·로그·취소·재시도·대기열·산출물·HPC·input.zip)
    job_params/
      __init__.py              (PARAM_MODELS 병합, prepare/after_insert/on_retry 디스패치)
      base.py                  ← _P, HpcOverrides, missing(), invalid_errors(), invalid_at(), parse_params()
      stage1_train_data.py     ← phase2_params TD_* 모델·prepare 분기
      stage2_curation.py       ← CU_*·SPDM_IMPORT 모델·분기, resolve_source
      stage3_model.py          ← jobs.py DATASET_CREATE/PACKAGE_EXPORT/MODEL_REGISTER/EVALUATE 모델·분기
      stage4_predict.py        ← jobs.py PREDICT/PREDICT_VERIFY 모델·분기
      stage5_optimize.py       ← OPTIMIZE 모델·분기
    stage1_train_data.py       ← services/train.py
    stage2_curation.py         ← services/curations.py
    stage3_model.py            ← studies.py:202–287 (datasets, models, final)
    stage4_predict.py          ← studies.py:288–485 (param sets, samples, predict_check, from_train)
    stage5_optimize.py         ← services/optimize.py
    ops_env_checks.py, ops_error_bundle.py ← env_checks.py, error_bundle.py (이름 변경은 선택)
```

### 5.3 `worker/physicsai_worker`

```
physicsai_worker/
  signals.py                   ← executor.py:41–54 (Cancelled, StepSkipped, EnterWaitingHpc)
  executor.py                  (LeaseKeeper, Executor; StepContext를 import해 재노출 — 시험 monkeypatch 대상 유지)
  step_context.py              ← executor.py:216–565
  runtime.py, env_check.py, limiter/, resources.py, housekeeping.py, lockfile.py, __main__.py
  (claim.py 삭제)
  steps/
    __init__.py                (HANDLERS 병합; 키 집합 불변)
    common.py, launcher.py
    _collect.py                ← COLLECT_STABLE_INTERVAL_S + verify.collect·train.ts_collect의 대기 루프(동작 그대로 두 함수 유지)
    stage1_train_data/
      extract.py               ← train.py tx_prep, simlab_extract, tx_parse (①-1)
      doe_gen.py               ← dg_prep, hst_gen_radioss, _find_starter, dg_scan (①-3)
      solve.py                 ← ts_prep, ts_submit, ts_collect, ts_register, _match_files, _summary (①-4)
      result_import.py         ← ri_scan, ri_copy, ri_register (①-5)
      resp_extract.py          ← rx_prep, rx_extract, rx_table (①-6)
      _shared.py               ← _setup, _doe, _tail, _X, _D, _R, TPL_REL, TPL_NAME
    stage2_curation/
      source.py                ← curation.source_root, _collect
      preview.py, h3d_curate.py, t01_curves.py ← curation.py 분할
      spdm_import.py           ← steps/spdm_import.py
    stage3_model/  dataset.py, package.py, model_register.py, evaluate.py
    stage4_predict/ predict.py, verify.py
    stage5_optimize/ optimize.py
```

### 5.4 시험

```
backend/tests/
  conftest.py, physicsai_test_support.py (그대로), fake_tools/ (그대로)
  helpers_stage1.py            ← phase2_helpers.py
  common/   test_config.py, test_ops_config.py, test_logsetup.py, test_auth.py, test_db_schema.py,
            test_phase2_db.py→test_db_phase2_schema.py, test_openapi.py, test_static_security.py, test_layering.py(신규)
  …        (단계별 폴더는 파일을 통째로 옮길 수 있는 것만; 여러 단계가 섞인 test_api.py·test_core_units.py·
            test_phase2_units.py·test_verifier_fixes.py의 함수 단위 분할은 보류)
worker/tests/
  runtime/  test_queue_lease.py, test_limiter.py, test_windows_job.py, test_hpc.py
  stage1_train_data/ test_phase2_train.py→test_stage1_train.py
  stage2_curation/   test_phase2_curation.py→test_stage2_curation.py
  stage5_optimize/   test_phase2_optimize.py→test_stage5_optimize.py
  ops/      test_phase2_admin.py→test_ops_admin.py
  e2e/      test_e2e_chain.py, test_demo_e2e.py
  (test_phase2_fixes.py, test_verifier_fixes_worker.py: 여러 주제 혼합 → 보류)
```

### 5.5 `frontend/src`

```
src/
  api/, app/, pages/, panels/, shell/, components/, lib/   (그대로)
  hooks/useOpenJob.ts          ← shell/useOpenJob.ts
  stages/
    stage1/  Stage1.tsx, TrainContext.tsx, CadExtractCard.tsx, ParamTableCard.tsx, DoeGenCard.tsx,
             DoePicker.tsx, RunStateBar.tsx, RunTable.tsx, SolveCard.tsx, ResultCollectCard.tsx, RunResponseCard.tsx
    stage2/  Stage2.tsx, CurationContext.tsx, Sources.tsx, H3dPreviewCard.tsx, H3dCurateCard.tsx,
             CurationResult.tsx, CurationFileList.tsx, T01Cards.tsx
    stage3/  Stage3.tsx, DatasetCards.tsx, ModelRegisterCard.tsx, EvaluateCard.tsx
    stage4/  Stage4.tsx(조립), ParamSetCard.tsx(+FromTrainForm), PredictWorkspace.tsx, useSamples.ts, ParamInputs.tsx, PredictResult.tsx
    stage5/  Stage5.tsx(조립), rules.ts(activeRules, cleanResponses), OptInputCard.tsx, OptRunCard.tsx, OptResult.tsx(+HistoryChart), ResponseTable.tsx
  mock/      server.ts(라우팅·공통), data.ts, install.ts, stage1.ts, stage2.ts, stage5.ts, ops.ts ← phase2.ts 분할
  __tests__/ shell, permissions, queue, notifications, usePolling, mockContract (그대로)
             stage1.test.tsx, stage2.test.tsx, stage5.test.tsx, ops.test.tsx, links.test.tsx ← phase2.test.tsx 분할
             stage3.test.tsx, stage4.test.tsx ← stages.test.tsx 분할
```

---

## 6. 계약 파일 표와의 관계

platform.md §21과 phase2.md §19의 파일 표는 소유권 경계(`backend/**`, `worker/**`, `frontend/**`)를 정하는 데 계속 쓰고, **개별 파일 위치는 이 문서가 우선**한다(각 계약 "변경 메모"에 기록). 리팩터링 단계가 끝날 때마다 Impl 에이전트는 §1 표가 달라진 부분을 Plan에 알리고, Plan이 이 문서 §1을 갱신한다.
