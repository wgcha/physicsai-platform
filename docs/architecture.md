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
| 외부에서 부르는 진입점 | `physicsai_core.config.load_config`(`deploy/install-common.ps1` `Get-PhysicsAIBackendPort`, `deploy/setup_config.py` `validate`), `python -m physicsai_api.serve`, `python -m physicsai_worker`, `physicsai_api.export_openapi.render`·`build_openapi`(`scripts/test-all.sh:10`, `scripts/test-all.ps1:7`) |
| `backend/tests/fake_tools/` 위치 | `deploy/collect-offline.sh:37`, `deploy/collect-offline.ps1:130`, `deploy/demo/demo_setup.py:67`이 이 경로를 쓴다 |

허용: 파일 이동·분리·이름 변경으로 **import 경로만** 바뀌는 것, 죽은 코드 삭제, 같은 동작의 중복을 한 함수로 합치는 것(값·순서·문구가 같을 때만).

---

## 1. 현재 구조 지도

백엔드·워커·시험(§1.1~§1.4)은 리팩터링 R0~R11 실행 후 기준(브랜치 `claude/phase3`, 커밋 `e125e68`)에 R12(300줄 분할, refactor-plan.md §6) 반영, 프런트(§1.5)는 F1~F4 실행 후 기준(커밋 `ad41635`), 스크립트(§1.6)는 기준 커밋 `b4f7817` 그대로. 줄 수는 `wc -l` 기준. "단계"는 ①학습데이터 생성 ②데이터 정리 ③데이터셋·모델 ④단일 예측 ⑤최적화, "공통"은 단계 무관. 리팩터링 전 위치·문제는 §2·§3(근거)과 refactor-plan.md에 남긴다.

### 1.1 `backend/physicsai_core` (공용 라이브러리)

| 위치 | 줄 | 단계 | 책임 |
|---|---:|---|---|
| `config/` | 1,081 | 공통 | `schema.py`(197: Settings 조립·server·database·auth·storage(`spdm_roots`)·altair·resources·worker 절·키 상수·ConfigIssue·LoadedConfig), `_model.py`(9: 기반 `_M`), `schema_stages.py`(124: ①~⑤ 단계 절), `schema_hpc.py`(79: commands·hpc 절), `schema_ops.py`(79: notifications·ui·demo·logging·env_check·study_storage·error_bundle 절, `ENV_PROBE_TOOLS`·`DEFAULT_LOG_ERROR_PATTERNS`), `rules.py`(39: 경로 문자열 규칙·`_compile`, `is_abs_path_str`는 `simdash_adapters` 재노출), `validate.py`(235: `validate_settings`), `validate_stages.py`(77: `_validate_phase2`, 3차 `_validate_phase3` — `study_storage` 범위, `StudyStorageCfg`), `loader.py`(99: `load_config`·`load_config_dict`·`absent_keys`·`config_warnings`), `derived.py`(43: Altair 파생·`effective_altair`·`redacted_settings`), `__init__`(87: 공개 이름 전부 재노출 — `from physicsai_core.config import …` 경로 불변) |
| `paths.py` | 277 | 공통 | 경로 검사(§17.3, B20·B23), `allowed_roots(settings, imports=)`, Study 경로, 백업 이동, 표시 경로. `path_links`의 이름 재노출 |
| `path_links.py` | 56 | 공통 | ← `paths.py`(R12): 링크·junction(reparse) 판정 `is_link_or_reparse`, Windows 예약 이름, `real`·`is_under`·`_real_parent` |
| `masking.py` | 65 | 공통 | `Masker`(step 로그), `BundleMasker`·`SECRET_ENV_PATTERNS`(오류 묶음·운영 로그), `bundle_masker(settings)` |
| `naming.py` | 9 | 공통 | ①·④ 공용 이름 규칙 `NAME_RE`·`RUN_KEY_RE`·`TPL_NAME`(`stage4_predict/param_sets`가 import해 속성 유지) |
| `commands.py`(274, `fwd`는 `simdash_adapters` 재노출), `job_types.py`(218), `tpl_render.py`(56), `childenv.py`, `errors.py`, `fileutil.py`, `limits.py`, `logsetup.py`, `state_machine.py`, `features.py` | | 공통 | `fileutil.write_json_atomic`(3차 S1: 임시 파일 + `os.replace`) |
| `env_check.py`(47), `error_bundle.py`(110) | | 공통(운영) | 환경 점검 항목·오류 묶음 항목 생성(마스커는 `masking.py`) |
| `parsers/` | | 공통 | `log_errors.py`(21: `ErrorDetector`), `name_value.py`(20: `read_name_value_csv`, ①·④ 공용) |
| `hpc/` | 81 | 공통 | **호환층**(3차 S4, 정의는 `packages/simdash_adapters` §1.7). `gateway.py`(타입 재노출 + `get_hpc_gateway(settings)`: 설정 읽기·`child_env`·로거 이름 `physicsai_core.hpc.command`를 넘겨 `make_gateway` 호출), `command.py`(`CommandHpcGateway(hpc, env_factory=None)` 얇은 하위 클래스·`validate_command_config(hpc)`·`map_path` 재노출), `none.py`·`adapter.py`(재노출) |
| `db/tables/`(675), `db/schema_0001.py`(396), `db/engine.py` | | 공통 | SQLAlchemy Core 메타데이터. `tables/`(← `tables.py`, R12): `_base`(단일 `metadata`·`TS`·`ID`·`job_queue_seq`·`TERMINAL_STATES`), `study_job`(studies·jobs), `model_data`(datasets·models·param_sets), `execution`(job_steps·artifacts·notifications·worker_slot·worker_heartbeats·hpc_jobs), `stage1_train_data`, `stage2_curation`, `stage5_optimize`, `ops`(env_checks·audit_events). `__init__`가 원래 정의 순서대로 import해 재노출(`metadata.tables` 순서·`from ..tables import x` 불변). `schema_0001.py`는 1차 동결본이라 분할 예외(파일 머리 주석) |
| `db/repositories/jobs.py` | 270 | 공통 | 작업 생성·조회(`list_with_study_title`, `succeeded_predicts`, `latest_by_stage`)·취소·대기열 이동 |
| `db/repositories/job_end.py` | 46 | 공통 | ← `jobs.py`(R12): 종료 부수효과 `_side_effects_on_end`(엔터티 저장소 `fail_*` 지연 호출). jobs·job_lease_end·hpc가 import |
| `db/repositories/job_lease.py` | 204 | 공통 | claim(SLOT·LIGHT·COLLECTING)/renew(CAS lease)·`ClaimRace`. 아래 두 파일의 이름을 재노출(`lease_repo.release`·`job_lease.LeaseLost` 경로 불변). 의존은 job_lease → job_lease_end → lease_guard → jobs 한 방향 |
| `db/repositories/job_lease_end.py` | 174 | 공통 | ← `job_lease.py`(R12): `release`·`continue_running`, 리퍼 `reap_expired`·`_interrupt`(T9) |
| `db/repositories/lease_guard.py` | 64 | 공통 | ← `job_lease.py`(R12): `LeaseLost`, `assert_lease`, lease 토큰으로 지키는 `step_update`/`job_update`/`patch_result`/`add_warning` |
| `db/repositories/system.py` | 17 | 공통(운영) | `ping`, `migration_version`(헬스 체크) |
| `db/repositories/*.py` 나머지 | 21–176 | 엔터티별 | `hpc.list_for_job_with_elapsed`·`get_many`, `studies.set_final_model`, `train.set_tpl_generated`, `{train,curations,spdm_imports}.set_building_job` 포함 |
| `stage1_train_data/` | | ① | `train_params.py`(233), `train_tpl.py`(84), `doe_types.py`(94), `doe_samples.py`(162) |
| `stage2_curation/` | | ② | `curation.py`(253), `spdm.py`(214) |
| `stage3_model/` | | ③ | `dataset_split.py`(73), `loss.py`(140), `score.py`(26) |
| `stage4_predict/` | | ④ | `param_sets.py`(148: `validate_folder`·`write_normalized`·`read_samples`, `ParamSetFolder`·`naming` 이름 재노출), `param_set_files.py`(207, ← `param_sets.py` R12: `ParamSetFolder`·parameters/responses/samples 읽기), `nearest.py`(82), `xydata.py`(67), `prepared_input.py`(3차 S6: 준비된 입력 예측 경로 검사 `check_path`·복사 계획 `plan_copy`·경로 확인 요약 `summary`, eps_mesh 판정 `is_mesh_file` — API·워커 공용) |
| `stage5_optimize/` | | ⑤ | `optimize.py`(278) |
| `study_storage/` | 397 | 공통(Study 관리, 3차 S3) | 단계 패키지 아님(단계를 import하지 않음, `test_layering` 규칙 5). `categories.py`(범주·표시명·영향 문구·폴더 묶음·항목 패턴·항상 보호 `is_protected`·`fmt_bytes`), `scan.py`(트리 걷기·집계 `walk`, 링크 미추적), `classify.py`(`StudyRefs`·`candidates`·`classify` — 스캔 분류와 정리 재검사 공용), `stale.py`(`stale_reason`) |
| `db/repositories/study_manage.py` | 87 | 공통(3차 S3) | `latest_succeeded`·`latest_finished`·`active_of_type`·`has_active_of_type`·`has_active_except`·`finished_after`·`study_refs`(분류 입력). `datasets.clear_package`. `jobs.py`가 300줄을 넘어 별도 파일(D3-7) |

### 1.2 `backend/physicsai_api` (FastAPI)

| 위치 | 줄 | 단계 | 책임 |
|---|---:|---|---|
| `routers/*.py` 15개 | 17–86 | 자원별 | 파일·함수 이름 그대로(operationId 동결). 서비스 호출만, SQL·`physicsai_core.db` 없음(`test_layering` 규칙 3) |
| `schemas/` | 970 | 전 단계 | `common`(44), `shell`(199), `jobs`(126), `studies`(68), `stage1_train_data`(148), `stage2_curation`(78), `stage3_model`(78), `stage4_predict`(106), `stage5_optimize`(62), `ops`(46). `__init__`가 전부 재노출(`S.Name` 불변) |
| `services/jobs.py` | 218 | 전 단계 | 작업 생성 오케스트레이션(`job_params` 호출)·조회·로그·취소·재시도·대기열 |
| `services/job_files.py` | 142 | 전 단계 | ← `jobs.py`(3차, 300줄 규칙): 산출물 목록·내려받기(`list_artifacts`·`artifact_file`), HPC 행(`list_hpc_jobs`), ④ input.zip 스트리밍(`input_zip`·`_ZipSink`·`ZIP_CHUNK` — `error_bundle.py`도 사용). 라우터 `artifacts.py`·`jobs.py`(`hpc_jobs`)가 호출(라우터 함수 이름 불변 → operationId 불변). `require_job`·`MOVED_HINT`는 `common.py` |
| `services/job_params/` | 812 | 전 단계 | `base.py`(48: `_P`, `HpcOverrides`, `prerequisite_missing`, `invalid_errors`(1차 형식), `invalid_at`(2차 형식), `check_feature`), `stage1_train_data.py`(181), `stage2_curation.py`(209, `resolve_source`), `stage3_model.py`(146, DATASET_CREATE 생성·재시도 후처리 포함), `stage4_predict.py`(92), `stage5_optimize.py`(84), `__init__.py`(52: `PARAM_MODELS` 병합, `parse_params`, `prepare`(check_feature 먼저)·`after_insert`·`on_retry` 디스패치) |
| `services/studies.py` | 149 | 공통 | Study 목록·조회·생성·수정(+`study.json` 제목 동기화)·보관·보관 해제(3차 S1), 단계 상태 |
| `services/path_inspect.py` | 165 | ①②③④ | 경로 확인(1차 용도 + 2차 용도), `inspect_model_folder`, `starters_in` |
| `services/stage1_train_data.py`(208), `stage2_curation.py`(131), `stage3_model.py`(103), `stage4_predict.py`(229), `stage5_optimize.py`(88) | | 단계별 | ① 파라미터 표·tpl·DOE·run, ② 원천·큐레이션·가져오기 조회, ③ 데이터셋·모델·Final, ④ 파라미터 세트·샘플·예측 확인·①→④, ⑤ 최적화 조회·응답 후보 |
| `services/common.py`(217), `system.py`(132), `env_checks.py`(152), `error_bundle.py`(95) | | 공통·운영 | raw SQL 없음(`test_layering` 규칙 4, 예외 0) |
| `services/study_storage.py`(74), `services/job_params/study_manage.py`(82), `routers/study_storage.py`, `schemas/study_storage.py` | | 공통(3차 S3) | 용량 보고서·`is_stale`, 관리 작업 params·사전조건, `study_gate`(R3-2 보관 예외·R3-4 정리 중 409 — `create_job`·`retry_job` 공용), `GET /studies/{id}/storage`(`get_study_storage`) |
| `auth.py`(205), `main.py`(133), `context.py`, `deps.py`, `demo.py`(164), `serve.py`, `export_openapi.py` | | 공통 | |

### 1.3 `worker/physicsai_worker`

| 위치 | 줄 | 단계 | 책임 |
|---|---:|---|---|
| `executor.py` | 198 | 공통 | `LeaseKeeper`, `Executor`(step 체인 실행). `StepContext`를 import해 모듈 속성으로 둔다(시험 monkeypatch 대상) |
| `step_context.py` | 149 | 공통 | `StepContext(StepProcessMixin)`: 경로·로그·진행률·산출물·결과·경고(로거 이름 `physicsai_worker.executor` 유지) |
| `step_process.py` | 264 | 공통 | ← `step_context.py`(R12): `StepProcessMixin` — `render`·`run_local`·`run_fanout`·`checkpoint_cancel`. 상속이라 `StepContext.run_local` monkeypatch가 `run_fanout`에도 적용 |
| `signals.py` | 17 | 공통 | 제어 예외 `Cancelled`, `StepSkipped`, `EnterWaitingHpc` |
| `runtime.py`(268, `Worker(HpcPollerMixin)`), `hpc_poller.py`(120, ← `runtime.py` R12: `poll_hpc_once`·`RUN_STATE_BY_HPC`, 로거 `physicsai_worker`), `env_check.py`(236), `limiter/`, `resources.py`, `housekeeping.py`, `lockfile.py`, `__main__.py` | | 공통 | (`claim.py` 삭제) |
| `steps/__init__.py`, `common.py`, `launcher.py`, `_collect.py`(`COLLECT_STABLE_INTERVAL_S`) | | 공통 | `HANDLERS` = 다섯 단계 패키지 병합(`test_step_registry`가 job_types와 대조) |
| `steps/stage1_train_data/` | 781 | ① | `_shared.py`(74: `TPL_REL`·`TPL_NAME`·`_doe`·`_D`·`_R`·`_match_files`·`_summary`·`_write_collected_json`), `extract.py`(①-1), `doe_gen.py`(①-3), `solve.py`(①-4), `result_import.py`(①-5), `resp_extract.py`(①-6) |
| `steps/stage2_curation/` | 461 | ② | `source.py`(원천 루트·대상 수집·큐레이션 등록 공용), `preview.py`(②-1·②-3), `h3d_curate.py`(②-2), `t01_curves.py`(②-4), `spdm_import.py`(G) |
| `steps/stage3_model/` | | ③ | `dataset.py`, `package.py`, `model_register.py`, `evaluate.py` |
| `steps/stage4_predict/` | | ④ | `predict.py`(228), `predict_inputs.py`(3차 S6: GEOM_UPDATE·MESH 출력 파일 판정, RAD_ASSEMBLE(parametric 새 include·prepared 복사), 입력 방식 분기 도우미), `verify.py`(158) |
| `steps/stage5_optimize/` | | ⑤ | `optimize.py`(158) |
| `steps/stage0_manage/` | 241 | Study 관리(3차 S3) | `storage_scan.py`(SS_WALK·SS_CLASSIFY, 중간 결과 `logs/<job>/storage_items.json`), `cleanup.py`(SC_VALIDATE·SC_MOVE·SC_RECORD, 계획 `logs/<job>/cleanup_plan.json`, `paths.backup_existing` 항목 단위 이동·삭제 없음) |

steps는 `executor`·`runtime`을 import하지 않는다(`test_layering` 규칙 6, 예외 0). `HANDLERS` = 다섯 단계 + `stage0_manage`. 단계 간 step import 없음(`map_path` → `core/hpc/command`(= `simdash_adapters.map_path`), `read_name_value_csv` → `core/parsers/name_value`). ①-4 회수 경로는 `solve._remote_result_dir`가 `simdash_adapters.resolve_collect_dirs(TransferConfig.from_obj(…))`에 위임(안정성 대기·복사 루프는 워커에 남음).

### 1.4 시험

| 위치 | 내용 |
|---|---|
| `backend/tests/physicsai_test_support.py`(100), `support_*.py`, `conftest.py`, `fake_tools/`, `data/` | 공용 픽스처(R12 분할): `support_base`(REPO·FAKE_TOOLS·IS_WINDOWS·LIMITER·sys.path), `support_db`(임시 PG·`engine`), `support_tools`(가짜 도구·1차 설정), `support_app`(가짜 대시보드·`client`·`worker_factory`·`H`·`API`), `support_inputs`(입력 폴더), `support_resources`(원본 반입 자원·명령 템플릿·`p2_env`). `physicsai_test_support`는 pytest 훅과 전부 재노출(conftest `import *`·시험 import 경로 불변). `fake_tools/`는 배포 시연 모드 공유 §0. `data/operation_ids.txt` = operationId 스냅샷 |
| `backend/tests/helpers_stage1.py` | ← `phase2_helpers.py`(① 시험 보조) |
| `backend/tests/helpers_api.py`, `helpers_queue.py` | R12: API 시험 공용(`_study`·`_sid`·`_job`·`_model`·헤더), 대기열·lease 워커 시험 공용(`_dataset_job`·`_state`) |
| `backend/tests/common/` | `test_adapters_compat`(3차 S4: 호환층 같은 객체·로거 이름·의존 고정·배포 내용, V3-S4-1·7), `test_config`, `test_ops_config`, `test_logsetup`, `test_auth`, `test_db_schema`, `test_db_phase2_schema`(← `test_phase2_db`), `test_openapi`, `test_openapi_operation_ids`(신규), `test_static_security`, `test_layering`(신규, §4.2 규칙 1·2·3·4·6), `test_study_manage`(3차 S1: 보관 해제·`study.json` 제목, V3-S1-1·2), `test_study_storage_api`(3차 S3: V3-S3-3·5·6·8), `test_db_study_manage`(V3-DB-1), `test_config_stages`(← `test_phase2_units` R12: V2-CFG-1·2, V2-CMD-1·2). `test_layering`에 규칙 5 추가(단계 패키지 간 import 금지, `study_storage`·`stage0_manage` 포함), 규칙 7 추가(3차 S4). `test_static_security`·`test_phase2_units`의 정적 검사 범위(`CODE_DIRS`)에 `packages/simdash_adapters/src` 포함. `helpers_manage.py`(S3 DB 행 도우미, 워커 시험 공용) |
| `backend/tests/` 루트 | `test_api`(권한·Study·params) + `test_api_models`(③·④) + `test_api_predict_inputs`(3차 S6 V3-S6-6·9·10·12) + `test_api_ops`(알림·로그·산출물), `test_core_units` + `test_core_stage_units`(단계 core 파서·분할·최근접·tpl), `test_phase2_units`(tpl 골든·상태 머신·정적·배포) — R12 함수 단위 분할(H3 일부 해제). 그대로: `test_demo`, `test_phase2_api`, `test_verifier_fixes` |
| `worker/tests/runtime/` | `test_queue_lease`(V-SM-2~4) + `test_lease`(V-LS-1~3) + `test_step_failures`(V-SM-5·6, V-CMD-5·7, V-DS-2) ← R12, `test_limiter`, `test_windows_job`, `test_hpc`(+ PREDICT_INPUT), `test_step_registry`(신규) |
| `worker/tests/stage0_manage/` | `test_storage_scan`(V3-S3-1·2·7), `test_cleanup`(V3-S3-4·7) |
| `worker/tests/stage1_train_data/{test_stage1_train(①-1~①-3·회수 모드 V2-TD-6),test_stage1_solve(①-4),test_stage1_results(①-5·①-6·F)}.py`+`conftest.py`(`pbs_state`·`p2_pbs`), `stage2_curation/{test_stage2_curation,test_stage2_spdm_import}.py`(R12 분할), `stage5_optimize/test_stage5_optimize.py`, `stage4_predict/{test_predict_parametric,test_predict_prepared}.py`+`conftest.py`(`predict_env`, 3차 S6 V3-S6-1~5·7·8·11·14), `ops/test_ops_admin.py`, `e2e/{test_e2e_chain,test_demo_e2e}.py` | ← `test_phase2_{train,curation,optimize,admin}.py`, e2e 2개 |
| `worker/tests/` 루트 | 보류(H3): `test_phase2_fixes`, `test_verifier_fixes_worker` |
| `packages/simdash_adapters/tests/` | 패키지 단독 시험(플랫폼·PG 없이): `test_static`(표준 라이브러리 허용 목록·최상위 `subprocess` 없음·버전 단일 출처·`__all__` 고정, V3-S4-4), `test_command`(문구 골든·`render_argv` 값 규칙·가짜 PBS `fake_pbs.py`로 submit/status/cancel·`make_gateway`), `test_transfer`(`map_path`·`resolve_collect_dirs` 표). 루트 pytest `testpaths`에 포함 |
| 정적 시험의 경로 | `test_phase2_units.py` SPDM 검사는 저장소 상대경로로 정확히 대조(`core/stage2_curation/spdm.py`, `core/config/{schema,validate}.py`, `api/services/{job_params/stage2_curation,path_inspect}.py`, `worker/steps/stage2_curation/spdm_import.py` 등), `test_static_security.py` timeout 검사는 `executor.py`+`step_context.py`+`step_process.py`(R12), `test_hpc.py`는 `REPO` 기준, COLLECT 간격 monkeypatch 대상은 `physicsai_worker.steps._collect` |

### 1.5 `frontend/src` (F1~F4 실행 후, 커밋 `ad41635`. 약 10,500줄, 생성물 제외)

| 위치 | 줄 | 단계 | 책임 |
|---|---:|---|---|
| `api/` | client 147, endpoints 137, types 261, generated | 공통 | 경계 양호: 화면 코드에 `fetch` 없음, `mock`은 `main.tsx` 동적 import와 `test/render.tsx`만 |
| `app/`, `pages/`, `panels/`, `shell/`, `components/`, `lib/` | | 공통 | 그대로. `shell/useOpenJob.ts`는 `hooks/`로 이동(F3) |
| `hooks/` | 16–99 | 공통 | `useArtifact`, `useJobRunner`, `useLatestJob`, `useNotifications`, `useOpenJob`(← `shell/`), `usePolling`, `jobRetried.ts`(3차 S1: 재시도로 생긴 새 작업을 `useLatestJob`이 이어받는 구독) |
| `components/ConfirmDialog.tsx`(99), `JobRetryButton.tsx`(63), `StudyArchiveDialog.tsx`(44) | | 공통 | 3차 S1: 공용 확인 대화상자, `JobInline` 재시도 버튼(`retryStartText`), Study 보관·보관 해제 대화상자(목록·관리 화면 공용) |
| `pages/StudyManage.tsx` | 183 | 공통 | 3차 S1: Study 관리 화면(`/p/:projectId/s/:studyId/manage`) ① 기본 정보(이름 변경) ② 보관 ③ 용량·정리(S3, `pages/manage/`) |
| `pages/manage/` | 384 | 공통(3차 S3) | `StorageSection.tsx`(보고서·다시 계산·실행 중 3초 재조회 `STORAGE_POLL`·최근 정리·`_backup` 안내), `StorageBars.tsx`(단계별 막대·큰 파일 표), `CleanupPreview.tsx`(범주 선택·미리보기·확인 대화상자), `storage.ts`(묶음·합계·비활성 사유·확인 문구 순수 함수) |
| `stages/stage1/` | 22–188 | ① | `Stage1`(조립 23), `TrainContext`(90), `CadExtractCard`(64)·`ParamTableCard`(188, `rowIssue`)·`DoeGenCard`(154, `defaultOptions`·`OptionInput`) ← `TrainCards.tsx`, `DoePicker`(22)·`RunStateBar`(37)·`RunTable`(95)·`SolveCard`(119, `PBS_NONE_TEXT`)·`ResultCollectCard`(100)·`RunResponseCard`(83) ← `SolveCards.tsx` |
| `stages/stage2/` | 29–224 | ② | `Stage2`, `CurationContext`, `Sources`(201, `SpdmSummary` — `pages/ImportLanding`이 import하는 유일한 단계 간 import), `H3dPreviewCard`(64, `useH3dPreview`)·`H3dCurateCard`(191, `PartList`)·`CurationResult`(44)·`CurationFileList`(40) ← `H3dCards.tsx`, `T01Cards`(224, 유지) |
| `stages/stage3/` | 16–273 | ③ | `Stage3`(16), `DatasetCards`(273, 유지), `ModelRegisterCard`(132, `LogStatusText`·`NAME_RE`)·`EvaluateCard`(233, `useModelDetails`, 비교 선택 열) ← `ModelCards.tsx`. 3차 S2: `ModelCompare`(91, 상세·데이터셋 조회)·`ModelCompareChart`(56, 곡선 겹치기·범례)·`ModelCompareTable`(143, 점수·메타 표)·`compare.ts`(135, 순수 함수) |
| `stages/stage4/` | 14–257 | ④ | `Stage4`(조립 14), `ParamSetCard`(192, `FromTrainForm` 포함)·`useSamples.ts`(27)·`PredictWorkspace`(257) ← `Stage4.tsx`, `ParamInputs`(207)·`PredictResult`(129) 유지 |
| `stages/stage5/` | 37–205 | ⑤ | `Stage5`(조립·상태 49), `rules.ts`(37: `activeRules`·`cleanResponses`·`METHOD_DEFAULTS`), `OptInputCard`(50), `OptRunCard`(121), `OptResult`(205, `HistoryChart`·`toTable`·`fileEntries`) ← `Stage5.tsx`, `ResponseTable`(197) 유지 |
| `__tests__/` | 26–133 | 단계별 | `stepper`(V2-FE-1·FeatureGate), `stage1`·`stage2`·`stage5`·`ops`·`links` ← `phase2.test.tsx`, `stage3`·`stage4` ← `stages.test.tsx`, 나머지(`shell`, `permissions`, `queue`, `notifications`, `usePolling`, `mockContract`) 그대로. 3차: `manage`(V3-S1-3·4), `compare`(V3-S2-1~5), `manageStorage`(V3-S3-10 — `manage.test.tsx`가 300줄을 넘지 않게 분리, D3-7). `describe`·`it` 이름(V-ID)과 시험 수(100) 동일 |
| `test/` | | 공통 | `render.tsx`, `setup.ts`, `recordCalls.ts`(신규, F4: 목 서버 `handle` 호출 기록 — 여러 시험 파일 공용) |
| `mock/server.ts` | 262 | 전 단계 | 1차 공유 상태(`MockServer`: 작업·산출물·알림 배열, `nid` 공유 카운터, 시드 순서)·알림·권한·**라우터 등록 `ROUTES`(한 곳, 순서 = 원래 `handle`의 if 순서)**·`createMockFetch`. `export type { MockResp }` 재노출 |
| `mock/route.ts` | 40 | 공통 | `MockResp`·`err`·`ok`·`RouteCtx`·`Route`·`needPower`·`needAdmin`(라우트 모듈 공용) |
| `mock/phase2.ts` | 167 | ①②⑤ | 2차 공유 상태(`Phase2Mock`: setups·does·runs·curations·opts·envChecks 등, 시험이 `s.p2.*`로 접근)·시드 순서 조립·`feature`/`status`/`summaryExtra`·작업 훅 분배(`precheck`·`onCreate`·`finish`·`tick`)·2차 경로 검사 `inspect`. `STAGE_LABEL` 등 재노출 |
| `mock/stage1.ts`(198)·`stage1Jobs.ts`(199), `stage2.ts`(210), `stage5.ts`(139) | | ①②⑤ | 단계별 시드·출력 변환·작업 훅·라우트(`trainRoutes`·`curationRoutes`·`optimizeRoutes`). ①은 라우트·시드·파라미터 표(`stage1`)와 작업 훅·PBS run tick(`stage1Jobs`)으로 나눔 |
| `mock/stage3.ts`(83), `stage4.ts`(108), `studies.ts`(101), `jobs.ts`(129), `engine.ts`(86), `ops.ts`(214) | | ③④·공통 | ③ 데이터셋·모델 출력·완료·§10.4 라우트, ④ 예측 결과·`check`·① 결과 파라미터 세트·완료·파라미터 세트 라우트, §10.3 Study 라우트(needPower 위치·404 그대로 한 함수), §10.5 작업(요약·생성·로그·라우트), 진행 엔진(대기열·`tick`·완료 분배), 운영(§10.2 me·상태·대기열·자원, §10.7 알림, 환경 점검 시드·진행·라우트) |
| `mock/data.ts`(7) ← `base.ts`(30)·`steps.ts`(185)·`seed.ts`(177)·`fixtures.ts`(64)·`catalog.ts`(74), `install.ts` | | 공통 | `data.ts`는 옛 import 경로용 재노출만. 기초 값(rng·iso·사용자·프로젝트), step 체인·`makeSteps`·`baseJob`, 1차 시드·가짜 응답, 산출물 본문, 2차 공용 상수(`STAGE_LABEL`·`FEATURE_MISSING`·`FEATURE_OF`·`DOE_TYPES`) |
| `mock/manage.ts` | 96 | 공통 | 3차 목 핸들러(PATCH study·archive·unarchive·retry), `server.ts` `ROUTES`에서 위임 |
| `mock/manageStorage.ts` | 162 | 공통 | 3차 S3 목(`StorageMock`: 보고서·스캔/정리 작업 생성·사전조건·종료 결과). `engine.ts`의 완료 처리가 `manage.storage.onFinish`를 부른다(스캔은 성공 알림 없음) |
| `design/` | 523 | 공통 | 스위스 격자 디자인 체계(2026-10-14, 기준 시안 `docs/design/swiss-grid-mockup.html`): `tokens.css`(색 paper·cell·ink·ink-2·ink-3·rule·rule-soft·red + 채도 낮춘 상태색 ok·warn·bad, 라이트·다크 = `prefers-color-scheme`과 `[data-theme]` 두 곳, 글자 역할 4단계 `--font-d/t/b/r`, 간격 8px 배수, `--row` 176px·`--rule-w` 1px, 모서리·그림자 전역 0), `typography.css`(유틸 `.D .T .B .R`, tabular-nums), `fonts.css`(IBM Plex Sans latin·IBM Plex Sans KR korean 400/500/600 woff2를 `@fontsource` npm에서 번들 — OFL-1.1, CDN 없음), `grid.css`(`.grid` 12열·1280 미만 6열·720 미만 2열 auto, `.cell`·`.c2~c12`·`.cell.rail`), `Grid.tsx`(`Grid`·`Cell`(머리 제목+참조 번호 → 본문 → 발 참조 설명·버튼, 내용 높이로 span 행 수 n 자동, 칸 높이 = n×176 + (n−1)px)·`Rail`/`RailSlot`(대기열·워커 자원·모델 칸을 10~12열에 1행부터 쌓음)). `components/ui.tsx` `Card`는 `Cell` 래퍼(`span`·`rows`·`foot`) |
| `styles.css` | 16 | 공통 | import 허브만: `design/{fonts,tokens,typography,grid}.css` → `styles/{base,controls,shell,overlays,cells,tables,chart,stages,stages-predict,panels}.css`(95–271줄, 화면별 규칙 — font-size·border-radius·box-shadow 없음, `__tests__/designRules.test.ts`가 정적 검사) |

**F5(목 서버 분할, 2026-10-11 실행)**: 이전 보류 사유(공유 상태·`nid` 생성 순서)는 상태를 옮기지 않고 해결했다 — 상태는 그대로 `MockServer`·`Phase2Mock` 필드에 두고(시험의 `s.p2.setups`·`s.p2.opts`·`s.p2.summaryExtra` 교체·`server.handle` 교체가 그대로 동작), 단계 모듈은 그 인스턴스를 인자로 받는 함수다. 시드는 원래 순서(1차 시드 → `seedJobs` → ① → SPDM·② → ⑤ → 환경 점검)로 호출해 목 ID가 같다. 라우트는 `server.ts` `ROUTES` 한 곳에 원래 우선순위대로 등록(예: 2차 `param-sets/from-train`이 §10.3 `param-sets`보다 먼저). 검증은 refactor-plan.md §7.

### 1.6 `scripts`, `deploy`, `config`, `migrations`

- `scripts/`: 얇은 래퍼(4–17줄) + `ci_annotate.py`. 정리 불필요. 3차 S4: `_env.{sh,ps1}`의 `PYTHONPATH`에 `packages/simdash_adapters/src` 추가, `dev-setup.{sh,ps1}`(신규, 개발 설치 표준: `pip install -e packages/simdash_adapters` → `pip install -r deploy/requirements.lock` + pytest. 패키지를 먼저 설치하지 않고 루트에서 `pip install .`을 하면 `simdash-adapters`를 인덱스에서 찾으므로 이 스크립트를 쓴다, D3-27), `check-adapters-wheel.sh`(V3-S4-6: wheel 이름·빈 venv 설치·import).
- 오프라인 묶음(3차 S4, D3-27): `collect-offline.{sh,ps1}`가 ① `pip wheel packages/simdash_adapters --no-deps -w dist/wheels` ② `pip download --no-index --find-links dist/wheels -r deploy/requirements.local.lock …`(로컬 wheel만으로 `simdash-adapters==0.1.0` 고정 확인) ③ `pip download -r deploy/requirements.lock …`(PyPI 외부 의존성만, `--find-links` 없음) 순서. lock 두 개: `deploy/requirements.lock` = PyPI에서 받는 외부 의존성(어댑터 없음 — 이름 선점 차단), `deploy/requirements.local.lock` = 저장소 안 패키지 고정(PyPI에서 받지 않음). 설치(`install.ps1`·`update.ps1`·`start-demo.ps1`)는 변경 없음(`--no-index --find-links wheels physicsai-platform`이 의존성으로 함께 설치). 시험 `test_adapters_compat`가 순서·내용 대조.
- 실행 환경(2026-10-13): **대시보드와 동일** — Python 3.12.13(`.python-version`, `pyproject` `requires-python>=3.12`, lock은 cp312 win_amd64), Node 22.23.2(`.node-version`, `frontend/package.json` `engines`), PostgreSQL 18(대시보드와 같은 인스턴스에 별도 DB·역할). `deploy/dashboard-env.ps1`(`Get-DashboardRuntimeDefaults`·`Merge-DashboardDefaults`)이 `deploy.json` `dashboard_root`·`start-demo.ps1 -DashboardRoot`의 기본값(대시보드 `.env` `POSTGRES_BIN`, `DATABASE_URL` host·port만, `.tools\python\cpython-3.12.*`)을 만든다 — `install.ps1`·`update.ps1`·`demo/start-demo.ps1`이 dot-source. 시험 PG bin은 `backend/tests/support_db.py` `_find_pg_bin`(`PHYSICSAI_TEST_PGBIN` → `PG_BIN` → `PGBIN` → `/usr/lib/postgresql/<최신>/bin` → PATH).
- git 폴더 설치(GitHub #1): `deploy/setup.ps1`(설치·재실행 안전)·`deploy/update-repo.ps1`(git pull 뒤 갱신) → 런타임 `<git>/.runtime/`(git 제외: venv·frontend·config/platform.yaml·deploy.json·logs·_backup). 설정 계획·작성은 `deploy/setup_config.py`(기존 값 보존·빠진 키 보충, Altair 상대 배치는 `config/platform.example.yaml`, 자원 상대경로는 `deploy/RESOURCES.txt`에서 읽음). DB·머신 환경변수·alembic·작업 스케줄러·health·대기열 확인은 `deploy/install-common.ps1` 공용 함수(묶음 `install.ps1`·`update.ps1`도 사용), Node 22 선택·프런트 빌드는 `deploy/node-select.ps1`(`collect-offline.ps1`도 사용). 시험 `backend/tests/test_setup_repo.py` + CI windows "git 폴더 설치" 단계.
- `deploy/`: Windows 배포 ps1·bat + `demo/demo_setup.py`(227: CLI 진입점·`up`/`down`, `physicsai_*`를 최상위 import하지 않음) + R12 분할 `demo_common.py`(경로·상수·공용 함수), `demo_init.py`(`init`: 가짜 도구·자원·설정), `demo_seed.py`(`seed`), `demo_db.py`(`db-up`/`db-down`). 같은 폴더 모듈을 import하므로 `sys.dont_write_bytecode = True`(deploy/ 아래 `__pycache__` 금지 — 정적 시험이 deploy/ 파일을 텍스트로 읽는다). 시험 `test_demo.py`·`test_phase2_units.py`가 내용 검사(`demo_setup.py`의 `"packages" / "simdash_adapters" / "src"` 포함).
- `migrations/versions/`: `0001_initial`(1차 동결본)·`0002_phase2`·`0003_hpc_cancel_failed`·`0004_study_manage`(3차 S3: `jobs.stage` 0 허용, phase3.md §5.10). `MIGRATION_HEAD = "0004_study_manage"`(`physicsai_core/db/__init__.py`), downgrade는 RuntimeError.
- `config/`: `platform.example.yaml`(271), `platform.demo.yaml`(118, `demo_setup.py`가 채우는 템플릿). 스키마의 **단일 출처는 `physicsai_core/config/schema.py`**(리팩터링 전 `config.py`)(코어 안 다른 설정 `BaseModel` 없음). 프런트 `mock/catalog.ts` `FEATURE_MISSING`은 `features.py`의 목 사본(목 계약 시험 대상, 의도된 중복).

### 1.7 `packages/simdash_adapters` (3차 S4, 공통 어댑터 패키지)

별도 배포 단위(`simdash-adapters`, wheel `simdash_adapters-<ver>-py3-none-any.whl`). 표준 라이브러리만 쓰고 플랫폼을 모른다(규칙 7). 공개 API는 `simdash_adapters.__all__`(phase3.md §6.3)뿐이고 `tests/test_static.py`가 고정한다. 버전은 `pyproject.toml` = `__version__`(SemVer, 0.x 동안 공개 API 모양 변경 = minor), `CHANGELOG.md`에 한 줄. 플랫폼 루트 `pyproject.toml`이 `simdash-adapters==<ver>`로 정확 고정한다.

| 위치 | 줄 | 책임 |
|---|---:|---|
| `src/simdash_adapters/__init__.py` | 37 | `__version__`, 공개 이름 재노출(`__all__`) |
| `pathstr.py` | 16 | `fwd`, `is_abs_path_str`(플랫폼 `commands.fwd`·`config.rules.is_abs_path_str`가 같은 객체를 재노출) |
| `hpc/types.py` | 64 | `HpcState`·`HpcAvailability`·`HpcSubmitSpec`·`HpcSubmitResult`·`HpcStatus`·`HpcGatewayError`·`HpcJobGateway`(1차 §12.2 모양) |
| `hpc/config.py` | 70 | `CommandConfig`·`HpcDefaults`(frozen, 기본값 없음, `from_obj`/`from_mapping`) |
| `hpc/command.py` | 220 | `validate_command_config`(문구 그대로), `render_argv`, `CommandHpcGateway(cfg, defaults, env_factory, logger)`(메서드 안 `subprocess`, 마스킹 없음 — 호출자 몫) |
| `hpc/none.py`, `hpc/adapter.py`, `hpc/factory.py` | | `NoneHpcGateway`, `AdapterHpcGateway`(자리), `make_gateway(mode, …)`(알 수 없는 값 → none) |
| `transfer/config.py`, `transfer/paths.py` | | `PathMapEntry`·`TransferConfig`, `map_path`, `resolve_collect_dirs`(①-4 PBS result_dir·회수 로컬 경로) |
| `tests/` | | 패키지 단독 시험(§1.4) |

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
| Study 관리(stage 0, 3차 S3) | core `study_storage`(공통 — 단계 패키지 아님), 워커 `steps/stage0_manage` | `STUDY_STORAGE_SCAN`, `STUDY_CLEANUP` | `pages/manage` |

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
5. 단계 패키지(`stageN_*`)는 공통과 자기 단계만 import한다. 단계 간 공유가 필요하면 공통으로 올린다(3차 S3부터 `test_layering` 규칙 5로 강제: core `stageN_*`·`study_storage`, 워커 `steps/stageN_*`·`stage0_manage`). 예외: `stage4_predict` 가 `stage1_train_data` 결과(DOE)로 파라미터 세트를 만드는 F 흐름은 **core 저장소/공통 모듈**을 통해서만.
6. 워커 `steps/**`는 `executor`·`runtime`을 import하지 않는다(제어 예외는 `signals`, 상수는 `steps/_collect.py`).
7. 공통 어댑터 패키지 `simdash_adapters`(`packages/simdash_adapters/src`)는 `physicsai_*`를 import하지 않고 표준 라이브러리만 쓴다. `physicsai_api`는 command 게이트웨이 모듈(`simdash_adapters.hpc.command`·`physicsai_core.hpc.command`)을 import하지 않는다(3차 S4부터 `test_layering` 규칙 7, 패키지 쪽은 `tests/test_static.py`).

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
  design/    tokens.css, typography.css, fonts.css, grid.css, Grid.tsx   (스위스 격자, 2026-10-14)
  styles/    base, controls, shell, overlays, cells, tables, chart, stages, stages-predict, panels .css  ← styles.css(이제 import 허브)
  stages/
    stage1/  Stage1.tsx, TrainContext.tsx, CadExtractCard.tsx, ParamTableCard.tsx, DoeGenCard.tsx,
             DoePicker.tsx, RunStateBar.tsx, RunTable.tsx, SolveCard.tsx, ResultCollectCard.tsx, RunResponseCard.tsx
    stage2/  Stage2.tsx, CurationContext.tsx, Sources.tsx, H3dPreviewCard.tsx, H3dCurateCard.tsx,
             CurationResult.tsx, CurationFileList.tsx, T01Cards.tsx
    stage3/  Stage3.tsx, DatasetCards.tsx, ModelRegisterCard.tsx, EvaluateCard.tsx
    stage4/  Stage4.tsx(조립), ParamSetCard.tsx(+FromTrainForm), PredictWorkspace.tsx, useSamples.ts, ParamInputs.tsx, PredictResult.tsx
    stage5/  Stage5.tsx(조립), rules.ts(activeRules, cleanResponses), OptInputCard.tsx, OptRunCard.tsx, OptResult.tsx(+HistoryChart), ResponseTable.tsx
  mock/      server.ts(공유 상태·ROUTES 등록), route.ts, phase2.ts(2차 공유 상태), stage1.ts, stage1Jobs.ts, stage2.ts, stage3.ts, stage4.ts, stage5.ts,
             studies.ts, jobs.ts, engine.ts, ops.ts, manage.ts, manageStorage.ts, data.ts(재노출) ← base·steps·seed·fixtures·catalog, install.ts  (F5, §1.5)
  __tests__/ shell, permissions, queue, notifications, usePolling, mockContract (그대로)
             stage1.test.tsx, stage2.test.tsx, stage5.test.tsx, ops.test.tsx, links.test.tsx ← phase2.test.tsx 분할
             stage3.test.tsx, stage4.test.tsx ← stages.test.tsx 분할
```

---

## 6. 계약 파일 표와의 관계

platform.md §21과 phase2.md §19의 파일 표는 소유권 경계(`backend/**`, `worker/**`, `frontend/**`)를 정하는 데 계속 쓰고, **개별 파일 위치는 이 문서가 우선**한다(각 계약 "변경 메모"에 기록). 리팩터링 단계가 끝날 때마다 Impl 에이전트는 §1 표가 달라진 부분을 Plan에 알리고, Plan이 이 문서 §1을 갱신한다.
