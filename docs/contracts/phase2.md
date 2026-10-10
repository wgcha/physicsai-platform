# 계약: PhysicsAI 플랫폼 2차

- 상태: 확정 (2026-10-08) — 구현 전 계약. 사용자 부재 중 작성했으므로 해석이 갈리는 곳은 **"가정 A-n"**으로 표기하고 §17 미확정(U17~)에 모은다
- 대상: Impl-Backend, Impl-Frontend, Verifier. 1차 계약 [platform.md](platform.md)와 **함께** 읽는다. 이 문서가 1차와 다르게 말하는 곳은 이 문서가 우선한다(§2.3에 목록)
- 원칙: **Altair 실제 실행 확인 없이 독립적으로 구현·자동 시험할 수 있는 범위만** 넣는다. 원본으로 확인되지 않는 인자·파일 이름·출력 형식은 설정 템플릿·플러그형 파서로 두고 "사내 확인 후 교체"로 표시한다
- 근거: 원본 데스크톱 앱 `OPEN_SOURCE_physics_ai_platform` Ver.0.0.6(이하 "원본"). 인용은 `파일:줄`. 업로드본에 **없는** 원본 파일(§17 U19): `CONFIG/TEMPLATE/TEMAPLATE_simlab_parametered_mesh.tpl`, `CONFIG/BATCHRUN/BATCHRUN_create_include_node_elem.tcl`, `BATCHRUN_preview_h3d.tcl`, `BATCHRUN_preview_hg.tcl`, `H3D_StaticMinMax_to_CSV_FAST.tcl`, `BUILD_PYD/*.pyd`. 반입본 위치는 설정으로만 받는다
- 결정 기록: [../decisions.md](../decisions.md), 사용자 현장 확인: [../e2e-checklist.md](../e2e-checklist.md)

---

## 0. 1차 기준선

- 2차는 **1차 계약 본문 + 변경 메모 B1~B26 전부가 유효하다**는 전제에서 시작한다(Plan이 B1~B26을 모두 수용 — 1차 구현·검수 결과와 일치). 1차 본문은 수정하지 않고, 2차에서 바뀌는 1차 규칙은 §2.3에만 적는다.
- 2차가 특히 재사용하는 1차 구현: 작업 유형 표(`physicsai_core/job_types.py`), step 핸들러 등록부(`worker/physicsai_worker/steps/__init__.py`), 템플릿 검증·펼침(`physicsai_core/commands.py`), 경로 검사·백업 이동(`paths.py`, B20·B21·B23), 자식 환경 허용목록(`childenv.py`, B19), HPC 게이트웨이·폴러(`hpc/`, `runtime.py`), COLLECT `in_place`(`steps/verify.py`), 산출물 등록·내려받기(id 기반, B18), zip 스트리밍(B16), 표시 경로(B17), 재시도 규칙(B9), 알림 생성기.

---

## 1. 한 줄 요약

2차는 ① 학습데이터 생성(CAD 파라미터 추출 → 파라미터 표·tpl → DOE+Radioss 입력 → PBS 해석 또는 수동 해석 결과 지정 → 결과 회수), ② 데이터 정리(h3d·T01 미리보기, hvtrans 큐레이션, 곡선 추출), ⑤ 최적화(HyperStudy+PhysicsAI)를 1차의 **작업·step 체인·명령 템플릿·대기열·알림** 위에 얹고, ① 결과로 ④ 파라미터 세트를 자동 생성하며, SPDM 읽기 전용 가져오기, 관리자 환경 점검, 오류 묶음 다운로드, Windows 폐쇄망 배포 스크립트를 더한다.

---

## 2. 범위

### 2.1 2차 범위

| 기호 | 기능 | 형태 | 절 |
|---|---|---|---|
| A | 환경 점검(전역 관리자) | 전용 테이블 + API 부분 즉시 + 워커 부분 비동기 | §9 |
| B | 오류 묶음 다운로드 | zip 스트리밍 API | §10 |
| C | ① 학습데이터 생성 ①-1~①-5 | 작업 5종 + 동기 API 2개 | §6.2~§6.6 |
| D | ② 데이터 정리 | 작업 4종 | §6.7~§6.10 |
| E | ⑤ 최적화 | 작업 1종 | §6.12 |
| F | ① 결과 → ④ 파라미터 세트 자동 생성 | 동기 API | §6.13 |
| G | SPDM 읽기 전용 가져오기 + 딥링크 | 작업 1종 + 프런트 경로 | §6.11, §12.7 |
| H | Windows 폐쇄망 배포 `deploy/` | 스크립트(실제 Windows 실행 **미검증**) | §11 |
| I | 알림 이벤트·대기열 표시 확장 | 기존 알림·대기열 확장 | §7.3, §12.9 |

### 2.2 2차 비범위(3차 이후 또는 별도 결정)

- `.pscfg` 템플릿 생성, 플랫폼의 학습(`--train`) 실행(1차와 동일하게 없음)
- 원본 ⑤의 "Predict + Preview" 버튼 — ④ 단일 예측이 대신한다(가정 A-1)
- HpcJobGateway `adapter` 모드 구현(자리만 유지)
- 응답값 추출 TCL 신규 작성(U8 유지), 컨투어 이미지 신규 렌더 TCL(U4 유지)
- 다중 슬롯·원격 워커, 모바일 UI

### 2.3 1차 계약에서 바뀌는 규칙(이 문서 우선)

| 1차 위치 | 2차 규칙 |
|---|---|
| §3.2, §16.2 스텝퍼 | ①②⑤ 활성화. "2차에서 제공 예정" 안내 제거. 기능에 필요한 설정·자원이 비어 있으면 해당 카드에 "관리자 설정 필요 — <키>" 문구와 버튼 비활성(§12.1 `features`, §14.1) |
| §9.1 argv[0] | 실행 파일 placeholder에 `{hstpy}`(→ `altair.hstpy_path`, §8.1) 추가. **Windows에서 argv[0]은 `os.path.normpath`로 `\` 구분자 변환**(원본 `2_DATA_CURATION/FUNC/1_curate_h3d.py:230-233` "hvtrans는 실행 파일 경로가 슬래시면 리더를 못 찾음", 원본 `1_physicsai_opti.py:310` `_norm`) — 1차 템플릿에도 적용 |
| §11.3·§8.3 LOCAL step | "LOCAL step = 외부 프로그램 1회"에 **팬아웃 LOCAL**(같은 템플릿을 대상 파일마다 순차 실행, §4.3) 추가 |
| §12.4·§14.3 회수 | `collect_mode`에 `shared_folder`·`drive` 허용(§6.5). 같은 작업 안 여러 run(hpc_job) 제출·회수 |
| §7.2 T10 | ①-4 `TD_SOLVE`만 "일부 run 실패 시 성공 run 회수" 전이 T10b 추가(§7.1) |
| §17.1 argv[0] 목록 | 환경 점검의 Job Object 자체 시험용 `[sys.executable, "-I", "-c", "pass"]`(고정 인자) 추가(§9.3) |
| §17.7 SPDM | "읽기도 없음" → **`storage.spdm_roots` 하위 읽기 전용 가져오기(G)만 허용**. 쓰기는 계속 0 |
| §8.4 `DATASET_CREATE` params | `curation_id` 선택 키 추가(②큐레이션 출력을 입력으로, §6.8) |
| B23 ③-1 입력 제한 | 거부 목록에 `01_train/extract`·`01_train/doe`·`01_train/tpl`·`02_preview`·`05_opt` 추가. `01_train/results`·`02_import`·`02_curated/*/CURATED_DATA`는 허용 |
| §6.8 artifact kind, §6.9 notification event | 값 추가(§5) |
| §15.4 파라미터 세트 | 폴더 등록 외에 ① 결과에서 생성(F) — 같은 검증기를 통과해야 등록 |
| §5.3 권한 표 | 환경 점검 = 전역 관리자, 오류 묶음 = 작업 등록자 본인 또는 전역 관리자(§10.1) |

---

## 3. 용어 추가

| 용어 | 뜻 |
|---|---|
| 런처(launcher) | 원본 `CONFIG/BATCHRUN/BATCHRUN_*.py` 중 첫 줄이 `# Generated launcher;`인 파일. 작업 폴더의 컴파일 코어(`<core>*.pyd`)를 `importlib.import_module`한다(원본 `BATCHRUN_hst_gen_radioss_input.py:1-12`). **SimLab·hstbatch·hstpy의 Python이 실행**하고 플랫폼 프로세스는 import하지 않는다 |
| pyd 코어 | 원본 `BUILD_PYD/<core>*.pyd`(`get_parameter_from_cad_core`, `hst_gen_radioss_core`, `hst_physicsai_optimization_core`). 위치는 설정 `resources.pyd_dir` |
| 학습 설정(train setup) | Study당 1개. ①-1 추출 결과와 ①-2 파라미터 표·tpl 상태(`train_setups`) |
| DOE(학습 DOE) | ①-3 실행 1회 = HyperStudy 작업 폴더 1개(`train_does`). run 목록(`train_runs`)과 샘플 표(`samples.csv`)를 가진다 |
| run_key | DOE run 폴더 이름(예 `run__00001`). 1차 정규식 `^[A-Za-z0-9_\-]{1,64}$` |
| 큐레이션 | ② 결과 묶음 1개(`curations`). 종류 `H3D`(hvtrans) / `T01`(곡선) |
| 원천(source) | ② 입력 위치. `TRAIN_DOE`(①-5 회수 결과) / `SPDM_IMPORT`(G 가져오기) / `FOLDER`(AI 루트 하위 경로) |
| 팬아웃 LOCAL | 대상 목록마다 같은 템플릿을 순차 실행하는 LOCAL step(§4.3) |
| 플랫폼 폴더 | `<ai_root>/_platform/` — Study가 아닌 플랫폼 산출(환경 점검 보고서·쓰기 시험). Study 폴더 이름은 `_`로 시작할 수 없어 겹치지 않는다 |

---

## 4. 공통 설계(1차 패턴 재사용)

### 4.1 새 기능의 기본 형태

- 외부 프로그램이 필요한 일은 **작업(job) + step 체인**(§6), 파일이 작고 외부 프로그램이 없는 일은 **동기 API**(1차 파라미터 세트 등록과 같은 방식). 동기 API도 사용자 산출물을 덮어쓸 때는 1차 백업 이동(`backup_existing`)을 쓴다.
- 작업 유형은 `JOB_TYPES`에 추가, step은 `HANDLERS[(job_type, step_key)]`로 등록, argv는 `commands.<key>` 템플릿으로만 만든다. 작업 폴더 기준은 1차 B9(재시도 체인의 최초 작업 id) 그대로.
- 새 엔터티 응답에는 B17처럼 표시 전용 `*_display_path`를 넣는다(요청 입력으로 받지 않음).

### 4.2 BATCHRUN 런처 실행 규약(①-1, ①-3, ⑤)

원본 `__sync_python_batch_to_workspace`(`1_CREATE_TRAINING_DATA/GUI/1_gui_create_tpl_file.py:159-189`)와 `_copy_python_batch`(`4_OPTIMIZATION/FUNC/1_physicsai_opti.py:135-158`)를 워커 INTERNAL 함수 `stage_launcher(launcher_key, work_dir)`로 재구현한다.

```text
script = resources.batchrun_dir / resources.launchers[key].script        # 예 BATCHRUN_hst_gen_radioss_input.py
core   = resources.launchers[key].core                                    # 예 hst_gen_radioss_core
1. script 존재 확인. 첫 줄(utf-8-sig)이 "# Generated launcher;"로 시작하면 compiled = true
2. compiled면 resources.pyd_dir 에서 glob("<core>*.pyd") 일반 파일이 정확히 1개여야 함
   0개·2개 이상 → step FAILED RESOURCE_MISSING("pyd가 정확히 1개가 아닙니다: N개")
3. 작업 폴더에 같은 이름으로 복사(shutil.copyfile, 기존 파일은 백업 이동). pyd·script의 sha256을 step outputs.files에 기록
4. 반환: 작업 폴더 안 런처 절대경로
```

- 플랫폼 코드(`physicsai_*`)는 pyd를 import하거나 런처 본문을 실행하지 않는다(정적 시험 V2-SEC-2). 런처 내용은 바꾸지 않고 그대로 복사한다.
- 런처 이름·코어 이름은 코드에 박지 않고 설정 `resources.launchers`(§8.2)에서 읽는다.

### 4.3 팬아웃 LOCAL step

②의 hvtrans 큐레이션, ①-6 run 응답 추출처럼 **대상 파일마다 같은 명령**을 돌리는 step. 원본 `execute_curate_batch`(`2_DATA_CURATION/FUNC/1_curate_h3d.py:229-318`)의 "실패해도 다음 파일 계속 → 요약" 동작을 따른다.

```text
targets = step 준비 단계가 만든 목록 [{target_id, values:{placeholder: 값}}]
for k, t in enumerate(targets, 1):
    취소 플래그 확인(→ T8)
    argv = expand(template_key, t.values)          # 1차 §9.1 값 검사는 대상마다
    step 로그에 "=== [k/n] <target_id> ===" 머리줄 후 출력 스트리밍(오류 정규식은 템플릿별 설정, §8.3)
    limiter.launch → 종료 → accounting 누적(peak = 최댓값, cpu_time = 합)
    성공 판정(템플릿별) → ok 목록 / 실패 목록(target_id, exit_code, 사유)
    progress_pct = k / n × 100
commands 파일 logs/<job_id>/step_<NN>_<key>.commands.jsonl 에 대상별 {target_id, argv, cwd, exit_code}
job_steps.command = {argv: 첫 대상 argv, cwd, env_added, invocations: n, commands_rel: "logs/…jsonl"}
판정: 성공 0개 → step FAILED(첫 실패의 코드). 일부 실패 → step SUCCEEDED + 작업 warnings [{code:"PARTIAL_OUTPUT", message:"n개 중 m개 실패"}]
```

- 동시 실행 없음(원본 `MULTI_EXECUTION` ThreadPool은 쓰지 않는다 — 슬롯 1개·Job Object 1개 원칙, 가정 A-2).
- 시간 한도 없음(1차 V-SM-6 유지).

### 4.4 원천(source) 해석(②, ⑤ 외 공통)

`source` 객체 = `{"kind": "TRAIN_DOE", "doe_id": str}` | `{"kind": "SPDM_IMPORT", "import_id": str}` | `{"kind": "FOLDER", "path": str}`.

| kind | 루트 | 기대 run 목록 |
|---|---|---|
| TRAIN_DOE | `<study>/01_train/results/<doe_id>/` | 그 DOE의 `train_runs` 전부(누락 표시 기준) |
| SPDM_IMPORT | `<study>/02_import/<import_id>/` | 없음 |
| FOLDER | 사용자가 준 경로(AI 루트 하위, 1차 §17.3 검사 + B23 확장 목록 거부) | 없음 |

파일 수집: 루트 아래 재귀, h3d는 `*.h3d`(대소문자 무시), T01은 이름이 `T01`로 끝나는 파일(원본 `2_gui_curate_t0.py:344-375` `fname.endswith("T01")`). 정렬·링크 거부·`_backup` 제외. 파일별 "run 폴더 이름"은 원본 `__compute_run_folder_names`(`2_DATA_CURATION/GUI/1_gui_curate_h3d.py:471-495`, T01은 `2_gui_curate_t0.py:399-422`) 규칙을 그대로 재구현: 파일 바로 위 폴더부터 위로 올라가며 그 레벨 이름만으로 서로 구분되는 첫 레벨의 폴더 이름, 어느 레벨로도 구분 안 되면 파일 stem.

---

## 5. 데이터 모델(migration `0002_phase2`)

`migrations/versions/0002_phase2.py` — **명시적 DDL**(B14: 0001 이후는 명시적 DDL). downgrade는 0001처럼 `RuntimeError`. `physicsai_core.db.MIGRATION_HEAD = "0002_phase2"` 상수를 두고 alembic 스크립트 head와 같은지 시험(V2-DB-1). 공통 규칙(UUID 문자열, TIMESTAMPTZ, `*_rel` = Study 기준 상대경로, 파일 본문 금지, JSONB는 Pydantic 검증 후 저장)은 1차 §6.1 그대로.

### 5.1 `train_setups` (①-1, ①-2 — Study당 1행)

| 컬럼 | 타입·제약 | 설명 |
|---|---|---|
| id | VARCHAR(36) PK | |
| study_id | FK studies, UNIQUE | |
| cad_source_path | VARCHAR NULL | 사용자가 지정한 CAD 파일(표시용) |
| cad_file_name | VARCHAR NULL | `01_train/cad/<이름>` |
| cad_sha256 | VARCHAR(64) NULL | |
| extract_job_id | FK jobs NULL | 최근 성공 `TD_EXTRACT_PARAMS` |
| parameters | JSONB NOT NULL DEFAULT `'[]'` | `[TrainParam]` (§5.1.1) — 정의 수치 요약이므로 허용 |
| tpl_rel | VARCHAR NULL | `01_train/tpl/simlab_parametered_mesh.tpl` |
| tpl_sha256 / tpl_generated_at | NULL | |
| tpl_params | JSONB NULL | 생성 시점 사용 파라미터 스냅샷 `[{var, name, format}]` |
| tpl_warnings | JSONB NOT NULL DEFAULT `'[]'` | `[{code, message}]` |
| updated_by / updated_by_name / updated_at | | |
| version | BIGINT NOT NULL DEFAULT 1 | 낙관적 동시성 |

#### 5.1.1 `TrainParam`

```jsonc
{"name": "THK_1",          // 추출값 그대로(불변). 1차 파라미터 정규식 불일치면 valid=false
 "raw_nominal": "3 mm",    // XML 원문(표시용, ≤64자)
 "nominal": 3.0,           // 숫자 변환 실패면 null → use 불가
 "min": 2.85, "max": 3.15, // 기본 = round(nominal × (1 ∓ train_data.param_default_range_ratio), 4) (원본 GUI:295-302, ratio 0.05)
 "use": true,              // 사용 여부(원본에 없는 2차 추가 열). 기본 = valid
 "format": "%3i",          // tpl NewValue 형식. 기본 train_data.param_default_format(원본 1_create_tpl_file.py:171 "%3i")
 "unit": "mm",             // 자유 문자열 ≤16, 기본 ""
 "valid": true, "problems": []}   // 서버가 계산(이름 정규식·숫자·범위)
```

### 5.2 `train_does` (①-3)

| 컬럼 | 설명 |
|---|---|
| id PK, study_id FK, job_id FK jobs | 만든 `TD_DOE_GEN` |
| doe_label / doe_type | DOE 유형 표시명(`LatinHyperCube`)·값(`TYPE_LATINHYPERCUBE`) — `DATA_doe_design_type.json` 키·`value` |
| num_runs_requested | INT NULL(`runs_editable=false` 유형은 NULL — HyperStudy가 결정) |
| options | JSONB `{key: value}` (`DOE_METHOD_OPTIONS`) |
| multi_execution | INT |
| radioss_assem_source_path | 사용자가 지정한 조립 폴더(표시용) |
| dir_rel | `01_train/doe/<id>/` (= HyperStudy `DIR_WORK`) |
| assem_rel | `01_train/radioss_assem/<id>/` |
| parameters_snapshot | JSONB — 생성 시점 사용 파라미터 `[{name, nominal, min, max, format, unit}]` |
| tpl_sha256 | 사용한 tpl |
| run_count | INT NULL |
| sample_status | `PARSED` \| `PARTIAL` \| `MISSING` \| `PENDING` |
| samples_rel | `01_train/doe/<id>/samples.csv` NULL |
| responses_rel | `01_train/doe/<id>/run_responses.csv` NULL (①-6) |
| status | `BUILDING` \| `READY` \| `FAILED` |
| created_by / created_by_name / created_at | |

### 5.3 `train_runs`

| 컬럼 | 설명 |
|---|---|
| id PK, doe_id FK train_does | `UNIQUE(doe_id, run_key)` |
| run_key | |
| input_rel | starter가 있는 폴더(Study 기준) |
| starter_name | |
| state | `GENERATED` \| `SUBMITTED` \| `SOLVED` \| `SOLVE_FAILED` \| `COLLECTED` \| `COLLECT_FAILED` |
| last_job_id | FK jobs NULL(최근 제출·회수 작업) |
| hpc_job_id | FK hpc_jobs NULL |
| result_rel | `01_train/results/<doe_id>/<run_key>/` NULL |
| result_summary | JSONB NULL `{h3d: int, t01: int, files: int, total_bytes: int}` |
| updated_at | |

인덱스 `(doe_id, state)`.

### 5.4 `curations` (②)

| 컬럼 | 설명 |
|---|---|
| id PK, study_id FK, job_id FK | `CU_H3D_CURATE` 또는 `CU_T01_CURVES` |
| kind | `H3D` \| `T01` |
| source | JSONB(§4.4 source 객체, FOLDER면 정규화 경로 문자열) |
| preview_job_id | FK jobs NULL |
| selection | JSONB — H3D: `{items:[{datatype, component}], parts:{shell:[int], solid:[int], rbody:[int]}, time_increment, time_steps_count}` / T01: `{curves:[{type, request, component}]}` |
| output_rel | H3D `02_curated/<id>/CURATED_DATA/`, T01 `02_curated/<id>/CURVES/` |
| file_list_rel | `02_curated/<id>/file_list.json` |
| target_count / ok_count / failed_count | INT |
| missing_runs | JSONB `[run_key]` (TRAIN_DOE 원천만, 최대 5000개) |
| status | `BUILDING` \| `READY` \| `FAILED` |
| created_by / created_by_name / created_at | |

### 5.5 `spdm_imports` (G)

`id, study_id, job_id, spdm_path(표시용 원문), dest_rel(02_import/<id>/), file_count, total_bytes, renamed_count, manifest_rel, status(BUILDING|READY|FAILED), created_by, created_by_name, created_at`.

### 5.6 `optimizations` (⑤)

| 컬럼 | 설명 |
|---|---|
| id PK, study_id FK, job_id FK | `OPTIMIZE` |
| approach | `OPT` \| `DOE` |
| opt_method | `ARSM` \| `GRSM` \| `SQP` (DOE면 저장은 하되 무의미) |
| max_designs | INT |
| model_id FK models / param_set_id FK param_sets | |
| study_folder | HyperStudy Study 폴더 이름 |
| dir_rel | `05_opt/<job_id>/` |
| runs_started | INT NULL(진행 중 최대 run 번호) |
| responses | JSONB — RESPONSES 표(정의 요약) |
| summary_status | `NONE` \| `PARSED` \| `UNRECOGNIZED` |
| summary_meta | JSONB NULL `{parser, file_rel, row_count, columns:[≤50]}` (표 본문은 파일 `summary.json`에만) |
| file_count | INT NULL |
| status | `RUNNING` \| `DONE` \| `FAILED` |
| created_by / created_by_name / created_at | |

### 5.7 `env_checks` (A)

| 컬럼 | 설명 |
|---|---|
| id PK | |
| state | `PENDING` \| `RUNNING` \| `DONE` \| `FAILED` \| `EXPIRED` |
| requested_by / requested_by_name / created_at | |
| expires_at | `created_at + env_check.expire_s`. 이 시각 이후 워커는 결과를 쓰지 못함 |
| worker_id / started_at / finished_at | NULL |
| api_items | JSONB `[EnvCheckItem]`(API가 생성 시 채움) |
| worker_items | JSONB NULL `[EnvCheckItem]` |
| summary | JSONB `{ok, warn, fail, skip}` |
| report_rel | VARCHAR NULL — **AI 루트 기준** `_platform/env_checks/<id>/report.json` |
| failure_message | VARCHAR(500) NULL |

부분 unique: `UNIQUE((true)) WHERE state IN ('PENDING','RUNNING')` → 동시 1건(위반 시 409 `ENV_CHECK_BUSY`). `EnvCheckItem.message` ≤200자, `detail`은 작은 객체(경로·크기·mtime·exit_code·지연 ms 등). 프로그램 출력 꼬리는 DB에 넣지 않고 보고서 파일에만.

### 5.8 기존 테이블 변경

| 테이블 | 변경 |
|---|---|
| `param_sets` | `origin VARCHAR NOT NULL DEFAULT 'FOLDER'` CHECK `origin IN ('FOLDER','TRAIN_DOE')`, `train_doe_id FK train_does NULL` |
| `artifacts` | kind CHECK에 `CURATION_CFG`(text/plain), `FILE_LIST`(application/json), `DOE_SAMPLES`(text/csv), `RUN_CONFIG`(application/json — `INPUT_HST_RUN.json`), `OPT_SUMMARY`(application/json), `OPT_FILE`(화이트리스트 형식) 추가. 1차 `PREVIEW_JSON`·`CURVE_JSON`은 ②⑤에서도 재사용 |
| `notifications` | event CHECK에 `HPC_PARTIAL_FAILED`, `ENV_CHECK_DONE` 추가 |
| `jobs` | 변경 없음(job_type은 문자열, stage CHECK 1~5 이미 허용) |
| `hpc_jobs` | 변경 없음(`run_key`로 다중 run 구분). 인덱스 `(job_id, state)` 추가 |

---

## 6. 작업 유형과 step 체인

### 6.1 목록(2차 추가)

| job_type | 단계 | lane | 화면 버튼 | step 체인 |
|---|---|---|---|---|
| `TD_EXTRACT_PARAMS` | ①-1 | SLOT | "파라미터 추출" | TX_PREP → SIMLAB_EXTRACT → TX_PARSE |
| `TD_DOE_GEN` | ①-3 | SLOT | "입력 생성" | DG_PREP → HST_GEN_RADIOSS → DG_SCAN |
| `TD_SOLVE` | ①-4 | SLOT | "PBS 제출" | TS_PREP → HPC_SUBMIT → HPC_WAIT → COLLECT → TS_REGISTER |
| `TD_RESULT_IMPORT` | ①-5 | LIGHT | "결과 가져오기" | RI_SCAN → RI_COPY → RI_REGISTER |
| `TD_RESP_EXTRACT` | ①-6(선택) | SLOT | "run 응답 추출" | RX_PREP → RESPONSE_EXTRACT_RUNS(팬아웃) → RX_TABLE |
| `CU_H3D_PREVIEW` | ②-1 | SLOT | "h3d 미리보기" | CP_PREP → HW_PREVIEW_H3D → CP_PARSE |
| `CU_H3D_CURATE` | ②-2 | SLOT | "큐레이션 실행" | HC_PREP → HVTRANS_CURATE(팬아웃) → HC_REGISTER |
| `CU_T01_PREVIEW` | ②-3 | SLOT | "T01 미리보기" | TP_PREP → HW_PREVIEW_T01 → TP_PARSE |
| `CU_T01_CURVES` | ②-4 | SLOT | "곡선 추출" | TC_PREP → HW_CURVE_EXPORT → TC_REGISTER |
| `SPDM_IMPORT` | ②-0 | LIGHT | "가져오기" | SI_SCAN → SI_COPY → SI_REGISTER |
| `OPTIMIZE` | ⑤ | SLOT | "최적화 실행"(DOE면 "DOE 실행") | OP_PREP → HST_OPTIMIZE → OP_SUMMARY |

①-2(파라미터 표 저장·tpl 생성)와 F(① 결과 → 파라미터 세트)는 동기 API(§6.3·§12.5, §6.13·§12.9). 1차 부분 unique(같은 Study·job_type 비종료 1개)는 그대로 적용.

### 6.1.1 사전조건(없으면 409 `PREREQUISITE_MISSING` + `missing:[...]`, 1차 §8.2 형식)

| 작업 | 사전조건 |
|---|---|
| 모든 2차 작업 | 1차 공통(Study ACTIVE, 설정 유효) + 필요한 템플릿이 null이 아님(409 `TEMPLATE_NOT_CONFIGURED`) + 필요한 `resources.*`·`altair.*` 값이 비어 있지 않음(409 `RESOURCE_NOT_CONFIGURED`, `missing:[키]`) |
| `TD_EXTRACT_PARAMS` | `cad_path`가 AI 루트 또는 `allowed_import_roots` 하위 **파일**, 확장자 ∈ `train_data.cad_extensions`(기본 `[".prt"]`, 원본 GUI:103). 템플릿 `simlab_extract_params`, 자원 `batchrun_dir`·`pyd_dir`·`launchers.extract_params` |
| `TD_DOE_GEN` | `train_setups.tpl_rel` 있음(409 `TPL_REQUIRED`) + tpl 생성 후 파라미터 표가 바뀌지 않음(`tpl_params` 일치, 아니면 409 `TPL_STALE`) + `radioss_assem_path` 폴더(AI 루트·허용 루트 하위)에 `predict.starter_glob` 정확히 1개(원본 `1_gui_physicsai_opti.py:427-445` 규칙: `eps_mesh`로 시작하는 파일 제외) + 자원 `doe_design_type_json`·`hypermesh_include_tcl`·`launchers.gen_radioss` |
| `TD_SOLVE` | DOE `READY` + 대상 run ≥1 + `HpcJobGateway.availability().configured`(아니면 409 `HPC_NOT_CONFIGURED`) |
| `TD_RESULT_IMPORT` | DOE `READY` + `source_path`(AI 루트·허용 루트·`hpc.transfer.collect_root_local` 하위 폴더) |
| `TD_RESP_EXTRACT` | DOE에 `COLLECTED` run ≥1 + 템플릿 `response_extract` |
| `CU_H3D_PREVIEW`, `CU_T01_PREVIEW` | 원천에 대상 파일 ≥1 + 자원 `preview_h3d_tcl` / `preview_hg_tcl` |
| `CU_H3D_CURATE` | `preview_job_id`가 같은 Study의 `SUCCEEDED` `CU_H3D_PREVIEW`(아니면 409 `CURATION_PREVIEW_REQUIRED`) + selection 유효 |
| `CU_T01_CURVES` | curves ≥1 + 자원 `curate_hg_tcl` |
| `SPDM_IMPORT` | `storage.spdm_roots` 비어 있지 않음(아니면 409 `SPDM_IMPORT_DISABLED`) + 경로가 SPDM 루트 하위(§13.3) |
| `OPTIMIZE` | 파라미터 세트(current 또는 지정) + `ACTIVE` 모델(기본 Final, 없으면 409 `FINAL_MODEL_REQUIRED`) + RESPONSES 유효 + 자원 `hypermesh_include_tcl`·`extract_minmax_tcl`·`launchers.optimization` + `altair.hstpy_path`(파생 포함, §8.1) |

### 6.2 ①-1 `TD_EXTRACT_PARAMS`

`params`: `{cad_path: str}`. 작업 폴더 `X = <study>/01_train/extract/<job_id>/`.

| step_key | kind | 처리 | 가중 | 성공 판정 |
|---|---|---|---|---|
| TX_PREP | INTERNAL | CAD를 `01_train/cad/<파일명>`으로 복사(기존 파일은 백업 이동) + sha256. `X` 생성, `stage_launcher("extract_params", X)`(§4.2) | 5 | |
| SIMLAB_EXTRACT | LOCAL | 템플릿 `simlab_extract_params`, `{launcher}`=X의 런처, `{cad_file}`=`01_train/cad/<파일>`, `{xml_out}`=`X/parameter_extracted.xml`(원본 GUI:239 이름), cwd `X`. 진행률 = `X/<런처 stem>_LogFile.txt`에서 `train_data.extract_progress_token`(기본 `Passed`) 개수 / `extract_progress_total`(기본 4) × 100, 상한 99(원본 `1_create_tpl_file.py:8-21,28-30,51`). 로그 파일은 2초마다 읽음 | 85 | 종료코드 0 + xml 존재(원본 FUNC는 종료코드를 보지 않음 — 2차는 판정 추가, 가정 A-3) |
| TX_PARSE | INTERNAL | 원본 `get_model_parameters`(`1_create_tpl_file.py:99-125`) 재구현: 루트 아래 `Model/Parameter`의 `Name`·`Value` 텍스트, 값에서 `mm`·`MM` 제거 후 strip. XML은 크기 ≤ `train_data.max_xml_bytes`(기본 4 MiB), `<!DOCTYPE`·`<!ENTITY` 포함 시 거부(`INPUT_INVALID`). 결과로 `train_setups.parameters`를 **새로 작성**(이전 표는 `01_train/params.json`과 함께 백업 이동), `cad_*`·`extract_job_id` 갱신, tpl 상태 초기화(`tpl_rel` 유지, `tpl_params=null` → TPL_STALE) | 10 | 파라미터 ≥1(0개면 `OUTPUT_MISSING`) |

결과 `result`: `{param_count, valid_count, cad_file_name}`. 실패 로그 확인용 `X/*_LogFile.txt`는 step 로그 끝에 꼬리 2 KiB를 덧붙인다.

### 6.3 ①-2 파라미터 표·tpl 생성(동기 API)

- 저장 `PUT /studies/{id}/train/params` — 이름·`raw_nominal`·`nominal`은 바꿀 수 없다(추출값). 사용자가 바꾸는 값: `min, max, use, format, unit`.
- 검증(`use=true` 행): `valid`, `nominal` 숫자, `min < max`, `min ≤ nominal ≤ max`, `format` ∈ `%[-0-9.]*[idfeEgG]`(1차 §15.4), 사용 행 ≥1. `format`이 정수형(`i`/`d`)인데 `min`·`max`·`nominal` 중 비정수가 있으면 **경고** `TPL_INTEGER_FORMAT`("정수 형식(%3i)이라 HyperStudy 샘플 값이 정수로 반영됩니다: THK_1")(오류 아님, U23).
- 저장 시 사람용 사본 `01_train/params.json`(`{schema_version:1, parameters:[…]}`)도 쓴다(기존 파일 백업 이동).
- tpl 생성 `POST /studies/{id}/train/tpl {version}` — 원본 `update_parameter_file`(`1_create_tpl_file.py:127-193`)을 **우리 코드로 재구현**(`physicsai_core/train_tpl.py`):

```text
입력: 원본 템플릿 = resources.simlab_tpl_template(원본 CONFIG/TEMPLATE/TEMAPLATE_simlab_parametered_mesh.tpl 반입본)
      → 01_train/tpl/TEMAPLATE_simlab_parametered_mesh.tpl 로 복사(원본 GUI:353-354 "세션 사본" 동작)
      사용 파라미터 P = [use=true 행, 표 순서]
1. text = 파일(utf-8) 읽기 → text.lstrip('\ufeff\r\n\t ')                                   (:130-132)
2. re.sub(train_data.tpl_prt_regex, 'dir_file_prt = r"./<cad 파일명>"', text)             (:135-139)
      기본 정규식 'dir_file_prt\s*=\s*r"[^"]*"'
3. 기존 '{parameter(...)}' 줄 제거: re.sub(train_data.tpl_parameter_line_regex, '', text)   (:153-157)
      기본 '(?m)^[^\n]*\{parameter\(.*?\)\}[^\n]*\n?'
4. marker = train_data.tpl_marker(기본 '#' + '*'×63) 위치 pos. 없으면 422 TPL_TEMPLATE_INVALID   (:159-162)
   text = "\n".join('{parameter(var_i, "<name>", <nominal>, <min>, <max>)}' for i, p in enumerate(P, 1)) + "\n" + text[pos:]
5. 기존 '<paramitem …/>' 줄 제거(기본 '(?m)^[^\n]*<paramitem[^>]*/>[^\n]*\n?')               (:177-181)
6. anchor = '<Parameters Value="">' 가 없으면 422 TPL_TEMPLATE_INVALID(원본은 조용히 무시 — 2차는 오류, 가정 A-4)
   anchor 뒤에 '\n' + "\n".join('   <paramitem Name="<name>" NewValue="{var_i, <format>}" Value="<nominal>"/>') (:166-186)
7. re.sub(r'\n\s*\n\s*\n+', '\n\n', text)                                                   (:188)
8. 01_train/tpl/simlab_parametered_mesh.tpl 에 utf-8로 쓰기(기존 파일 백업 이동)             (GUI:356)
수 표기: 정수값 실수는 "3", 그 외 repr(float) 최단 표기("2.85"). 원본은 표 문자열을 그대로 씀
```

- **사용하지 않는 파라미터는 두 블록 모두에서 뺀다** → SimLab에서 CAD 공칭값이 유지된다고 가정(가정 A-5, U37).
- 생성 후 `tpl_params=[{var:"var_i", name, format}]`, `tpl_sha256`, 경고를 저장. 생성된 tpl은 1차 §15.4 검증기(파라미터 이름 집합 일치, `{VAR, FMT}` 형식)를 통과해야 한다(실패 시 422 `TPL_TEMPLATE_INVALID` + problems).
- 원본 GUI는 ±5% 기본 범위와 정수 형식 `%3i`를 고정했다. 2차는 같은 기본값을 설정으로 두고 행마다 바꿀 수 있게 한다.

### 6.4 ①-3 `TD_DOE_GEN`

`params`: `{doe_label: str, num_runs?: int(2~train_data.max_runs), options: {key: value}, multi_execution?: int(1~train_data.max_multi_execution, 기본 1), radioss_assem_path: str}`. 작업 생성 시 `train_does` 행(`BUILDING`)을 만들고 `doe_id`를 `params`에 확정 기록(B8 방식). `D = <study>/01_train/doe/<doe_id>/`.

DOE 유형 정의는 `resources.doe_design_type_json`(원본 `CONFIG/DATA/DATA_doe_design_type.json`)을 읽어 검증한다: 최상위 `{label: {value, default_runs, runs_editable, fields:[{key, label, type: combo|int|bool, items?, default, min?, max?}]}}`(원본 GUI:205-294). `num_runs`는 `runs_editable=true`일 때만 받고(없으면 `default_runs`), false면 422(원본 GUI:213-227 "자동 계산됨"). `options` 키 집합 = fields 키 집합, combo는 items 중 하나, int는 [min,max], bool은 bool.

| step_key | kind | 처리 | 가중 | 성공 판정 |
|---|---|---|---|---|
| DG_PREP | INTERNAL | ① `radioss_assem_path`의 직계 `*.rad`·`*.inc` → `01_train/radioss_assem/<doe_id>/` 복사(원본 GUI는 원래 경로를 그대로 넘김 — 2차는 Study 사본, 가정 A-6). ② `D`에 복사: `simlab_parametered_mesh.tpl`, CAD 사본, `DATA_doe_design_type.json`(원본 GUI:196-203), `BATCHRUN_create_include_node_elem.tcl`(=`resources.hypermesh_include_tcl`, 원본 GUI:368-370), `stage_launcher("gen_radioss", D)`. ③ `D/INPUT_HST_RUN.json` 작성 — **키는 원본 GUI:410-424 그대로**: `HST_EXECUTABLE`(=hyperstudy_path, `/` 구분), `ALTAIR_PATHS`(altair 5키 `hyperstudy_path, simlab_path, edspy_path, hw_exe_path, hvtrans_exe_path` → `/` 구분), `DOE_NUM_RUNS`(runs_editable=false면 `default_runs` — 원본 :407 "참고용"), `DIR_WORK`(=`D`), `CAD_PARAM`(=`D/<CAD>` 사본), `RADIOSS_ASSEM_DIR`(=`01_train/radioss_assem/<doe_id>`), `DOE_TYPE`(=value), `DOE_METHOD_OPTIONS`, `MULTI_EXECUTION`. 경로는 모두 절대경로 `/` 구분(원본 `.replace("\\","/")`). `RUN_CONFIG` artifact 등록. ④ `parameters_snapshot`, `tpl_sha256` 기록 | 5 | |
| HST_GEN_RADIOSS | LOCAL | 템플릿 `hst_gen_radioss`, `{multi_execution}`, `{launcher}`(=`D/` 런처, `/` 구분 — 원본 GUI:445), cwd `D`(원본 FUNC:46-55 `cwd=dir_work`). 진행률: 줄마다 `train_data.hst_progress_regex`(기본 원본 `Finished run\s*\(\s*(?P<run>\d+)\s*\),\s*model\s*\(\s*m_?3\s*\)`, FUNC:59-61) 일치 시 `min(10 + run/total×85, 95)`(FUNC:93-98), total = `num_runs_requested`; NULL이면 진행률 NULL + 라벨 "run N 완료". 오류 정규식 = `train_data.hst_log_error_patterns`(기본 원본 FUNC:64-71의 4개 대안: `^\s*\d+\s+Error\s*:`, `Traceback \(most recent call last\):`, `^\s*\[ERROR\]`, `^\s*(?:FileNotFoundError|RuntimeError|ValueError|OSError|PermissionError|ImportError|TypeError|AttributeError|NameError|SyntaxError)\s*:`) — 일치하면 종료코드 0이어도 `LOG_ERROR_DETECTED`(원본 FUNC:103-117) | 85 | 종료코드 0 + 오류 줄 없음 |
| DG_SCAN | INTERNAL | ① run 폴더 = `D` 아래 `train_data.run_dir_glob`(기본 `approaches/*/run__*`, **U17**) 일치 폴더, 이름순. 각 run 폴더 안 재귀로 `predict.starter_glob` 일치(이름이 `eps_mesh`로 시작하는 것 제외) 정확히 1개 → `input_rel`=그 폴더, `starter_name`. 0개·2개 이상인 run은 `train_runs`에 넣지 않고 경고 목록(`RUN_INPUT_INVALID`). run_key = run 폴더 이름(1차 run_key 정규식 불일치 시 경고 후 제외). ② 샘플 표 추출기 `train_data.samples_extractor`(§6.4.1) → `D/samples.csv`(헤더 `run_key,<사용 파라미터 이름…>`), `DOE_SAMPLES` artifact. ③ `D/runs.json` = `[{run_key, input_rel, starter_name}]`. ④ `train_runs` 삽입(`GENERATED`), `train_does.run_count`, `sample_status`, `status=READY` | 10 | run ≥1(0개 → `OUTPUT_MISSING` "Radioss 입력 run 폴더를 찾지 못했습니다 — 설정 train_data.run_dir_glob 확인") |

결과 `result`: `{doe_id, run_count, sample_status, skipped_runs:[{run_key|dir, reason}]}`. 실패 시 `train_does.status=FAILED`.

#### 6.4.1 DOE 샘플 표 추출기(플러그형)

DOE 샘플 값(HyperStudy가 정한 run별 파라미터 값)의 출력 위치·형식은 원본 코드(pyd)로 확인되지 않는다(U18). 추출기를 설정으로 고른다.

| 이름 | 동작 | 근거 |
|---|---|---|
| `paramitem`(기본) | 각 run 폴더 아래 `train_data.rendered_tpl_glob`(기본 `**/*`, 파일당 ≤ `train_data.samples_scan_max_bytes` 기본 1 MiB, 확장자 `train_data.rendered_tpl_exts` 기본 `[".py", ".tcl", ".txt", ".xml", ""]`) 파일에서 `train_data.paramitem_regex`(기본 `<paramitem\s+Name="(?P<name>[^"]+)"\s+NewValue="(?P<value>[^"]*)"`) 일치 줄을 읽는다. 사용 파라미터 이름이 모두 숫자 값으로 나오는 **첫 파일** 채택. `NewValue`에 `{var_`가 남아 있으면 미렌더로 보고 건너뜀 | 우리 tpl이 쓰는 `<paramitem Name=… NewValue="{var_i, %3i}"…/>`(원본 `1_create_tpl_file.py:168-173`)를 HyperStudy가 값으로 치환한다는 점에서 유도. 값은 **SimLab에 실제 반영된 값**(정수 형식이면 정수) |
| `csv` | `D` 아래 `train_data.samples_csv_glob`(기본 null) 첫 파일. 헤더에 run 열(`train_data.samples_csv_run_column`, 기본 `run_key`)과 파라미터 이름(또는 `var_i`) 열 | HyperStudy 내보내기 파일 형식 미확인 |
| `none` | 추출 안 함 → `sample_status=MISSING` | |

일부 run만 값이 나오면 `PARTIAL`(그 run은 samples.csv에서 빠지고 경고). 샘플 표가 없어도 ①-4~②는 진행 가능, F(§6.13)만 409 `SAMPLES_MISSING`.

### 6.5 ①-4 `TD_SOLVE` (PBS 해석 제출)

`params`: `{doe_id: str, run_keys?: [str] | null, hpc?: {queue?, ncpus?, walltime?}, on_run_failure?: "collect_partial" | "fail"(기본 collect_partial)}`. `run_keys` null = 상태가 `GENERATED`·`SOLVE_FAILED`·`COLLECT_FAILED`인 run 전부. 대상 ≤ `train_data.max_runs_per_submit`(기본 500, 초과 422). 결과 폴더 `R(run) = <study>/01_train/results/<doe_id>/<run_key>/`.

| step_key | kind | 처리 |
|---|---|---|
| TS_PREP | INTERNAL | 대상 run 확정(`result.run_keys`), 각 `R(run)`이 있으면 백업 이동 후 생성. `attempt = 이 DOE의 이전 TD_SOLVE 수 + 1` |
| HPC_SUBMIT | HPC_SUBMIT | run마다 `HpcSubmitSpec{job_name=<study>_<doe8>_<run_key>_a<n>(정규화·64자), run_key, input_file=<input_rel>/<starter>, input_dir=<input_rel>, result_dir=결과 위치(아래), …}`(path_map 적용) → `hpc_jobs` 1행씩, `train_runs.state=SUBMITTED`. **하나라도 제출 실패하면** 남은 제출 중지 → 이미 제출한 것은 gateway `cancel`(실패는 경고) → step FAILED `HPC_SUBMIT_FAILED`. 모두 성공하면 T5(슬롯·lease 해제) |
| HPC_WAIT | HPC_WAIT | 1차 폴러 그대로(작업의 비종료 hpc_jobs 전부 조회). run 종료마다 `train_runs.state` = `SOLVED`/`SOLVE_FAILED` |
| COLLECT | COLLECT | 성공 run마다 `collect_mode`별 회수(아래). run별 실패는 `COLLECT_FAILED`로 기록하고 계속, 성공 0개면 1차 규칙(3회 재시도 후 `COLLECT_FAILED`) |
| TS_REGISTER | INTERNAL | `train_runs.result_rel`·`result_summary`·`COLLECTED`, `01_train/results/<doe_id>/collected.json`, 결과 `{submitted, solved, failed, collected}` |

결과 위치·회수(`hpc.transfer.collect_mode`, 1차 §12.4 확장):

| 모드 | PBS `result_dir` | COLLECT 동작 |
|---|---|---|
| `in_place`(1차) | `R(run)`(path_map 적용) | `R(run)`의 `collect_patterns` 일치 파일이 존재하고 크기·mtime이 10초 간격 2회 연속 불변(1차 그대로) |
| `shared_folder` | `<collect_root_remote>/<study>/<doe_id>/<run_key>/` | 같은 위치의 로컬 경로 `<collect_root_local>/…`에서 안정 확인 후 `collect_patterns` 일치 파일을 `R(run)`으로 **복사**(`shutil.copyfile` 1 MiB 버퍼, 파일당 ≤ `max_collect_bytes`). 원본은 지우지 않는다 |
| `drive` | `shared_folder`와 같음 | **`shared_folder`의 별칭**(루트가 네트워크 드라이브 문자일 뿐 동작 동일 — 가정 A-7, U36) |

`collect_root_local`은 읽기 전용 루트로 다룬다: 절대경로, 존재, 공백·메타문자 없음, SPDM 루트와 비중첩, AI 루트와 같거나 안팎으로 겹치지 않음.

`HpcJobGateway` 모드가 `none`이면 ①-4 버튼 비활성 + 안내 "PBS 연결 안 됨 — DOE 입력 폴더를 직접 해석한 뒤 ①-5에서 결과 폴더를 지정하세요"와 DOE 폴더 표시 경로(복사 버튼).

### 6.6 ①-5 결과 회수 — 자동(TD_SOLVE COLLECT) 또는 `TD_RESULT_IMPORT`

`TD_RESULT_IMPORT` `params`: `{doe_id: str, source_path: str}`. PBS 미연결이거나 사용자가 다른 곳에서 해석한 결과를 가져올 때.

| step_key | kind | 처리 |
|---|---|---|
| RI_SCAN | INTERNAL | `source_path` 아래 깊이 ≤ `train_data.result_match_depth`(기본 3)의 폴더 중 이름이 `train_data.result_run_dir_regex`(기본 `^(?P<run_key>run__\d+)$`, 대소문자 무시) 일치하고 `run_key`가 이 DOE에 있는 것 → 매칭. 같은 run_key 폴더가 2개 이상이면 그 run은 `INPUT_INVALID` 목록. 매칭 0개 → `INPUT_INVALID`("run 폴더를 찾지 못했습니다") + 발견한 하위 폴더 이름 최대 20개 |
| RI_COPY | INTERNAL | 매칭 run마다 폴더 직계·하위의 `hpc.transfer.collect_patterns` 일치 파일을 `R(run)`(기존은 백업 이동)으로 복사, 하위 구조 유지. 링크 거부. 진행률 = 바이트 |
| RI_REGISTER | INTERNAL | `train_runs` → `COLLECTED`(+summary), `collected.json` 갱신, 결과 `{matched, copied_files, total_bytes, unmatched_dirs:[≤20], missing_runs:[≤5000]}` |

### 6.6.1 ①-6 `TD_RESP_EXTRACT`(선택)

run별 응답값(④ 응답 표의 실측 열, F의 `resp:` 열)을 만드는 선택 작업. 1차 U8과 같은 이유로 **기본 비활성**(`response_extract` 템플릿 null → 409 `TEMPLATE_NOT_CONFIGURED`).

`params`: `{doe_id, responses: [{name, unit, spec}]}`(이름 정규식 1차 §10.6). RX_PREP: `D/responses.json` 작성, 대상 = `COLLECTED` run의 `R(run)` 첫 `*.h3d`(이름순). RESPONSE_EXTRACT_RUNS: 팬아웃(§4.3) 템플릿 `response_extract`(1차 키 재사용, `{pred_h3d}`·`{pred_h3d_fwd}` = 대상 h3d, `{responses_json}`, `{out_csv}` = `R(run)/responses_run.csv`, `{work_dir}` = `R(run)`), 성공 = 종료코드 0 + out_csv 존재. RX_TABLE: `D/run_responses.csv`(`run_key,<응답 이름…>`), `train_does.responses_rel`.

### 6.7 ②-1 `CU_H3D_PREVIEW`

`params`: `{source: Source, sample_file?: str(원천 루트 기준 상대경로)}`. 작업 폴더 `W = <study>/02_preview/<job_id>/`.

| step_key | kind | 처리 |
|---|---|---|
| CP_PREP | INTERNAL | 원천 h3d 수집(§4.4), 대상 1개 = `sample_file` 또는 첫 파일(이름순). `W` 생성 |
| HW_PREVIEW_H3D | LOCAL | 템플릿 `h3d_preview`, `{preview_tcl}`=`resources.preview_h3d_tcl`(원본 `BATCHRUN_preview_h3d.tcl`, 원본 GUI:47), `{h3d}`(`/` 구분), `{result_json}`=`W/PREVIEW_H3D.json`(원본 GUI:51, `/` 구분), cwd `W`. 성공 = 종료코드 0 + json 존재(원본 `1_curate_h3d.py:60`). 원본처럼 콘솔 로그는 step 로그로 대체 |
| CP_PARSE | INTERNAL | json 검증: 키 `datatype_info:{DataType:[comp…]}`, `lst_cid_shell|lst_cid_solid|lst_cid_rbody:[id…]`, `num_time_step:int`(원본 GUI:362-407). 각 component에 원본 `to_cfg_datacomp`(GUI:711-734: 단어 1개 그대로, 2개면 첫 단어, 3개 이상·`Extreme`로 시작 → 사용 불가)를 적용한 `usable` 목록을 함께 저장한 `W/preview_summary.json` → 둘 다 `PREVIEW_JSON` artifact. 결과 `{sample_file, datatype_count, part_counts:{shell,solid,rbody}, num_time_step, source_file_count}` |

### 6.8 ②-2 `CU_H3D_CURATE`

`params`:

```jsonc
{"source": {"kind": "TRAIN_DOE", "doe_id": "…"},
 "preview_job_id": "…",
 "selection": {"items": [{"datatype": "Stress", "component": "vonMises"}],   // Displacement 행은 무시(항상 자동 추가)
               "parts": {"shell": [1, 2], "solid": [], "rbody": []},
               "time_increment": 1},                                          // ≥1
 "exclude_files": ["run__00003/m_3/x.h3d"]}                                   // 원천 루트 기준(원본 표의 체크 해제)
```

검증: items의 datatype ∈ 미리보기 `datatype_info` 키, component ∈ 그 datatype의 `usable`, 중복 없음, items ≥1(원본도 표가 비면 오류, GUI:737-740 — Displacement 행만 있는 경우도 ≥1로 인정). parts id ∈ 미리보기 목록. `num_time_step ≥ 1`. 작업 생성 시 `curations` 행(`BUILDING`). `C = <study>/02_curated/<curation_id>/`.

| step_key | kind | 처리 |
|---|---|---|
| HC_PREP | INTERNAL | ① `C/work/CURATE_H3D.cfg` 작성 — 원본 `__create_hvtrans_config`(GUI:736-842) 재구현(아래). `CURATION_CFG` artifact. ② 대상 = 원천 h3d − exclude, run 폴더 이름(§4.4), 출력 `C/CURATED_DATA/<run_folder>/<h3d 파일명>`(원본 GUI:665-681). 출력 폴더 이미 있으면 백업 이동(원본 `__clear_folder_contents` 삭제는 쓰지 않음) |
| HVTRANS_CURATE | LOCAL 팬아웃 | 템플릿 `hvtrans_curate`, `{cfg}`·`{h3d}`·`{out_h3d}`는 **OS 기본 구분자**(원본 `1_curate_h3d.py:261-266` `os.path.normpath`), cwd `C/work`. 대상별 성공 = 종료코드 0 + 출력 존재(원본 :298) |
| HC_REGISTER | INTERNAL | `C/file_list.json` = `[{run_folder, run_key?, input_rel, output_rel?, size?, ok, exit_code?}]` → `FILE_LIST` artifact. TRAIN_DOE 원천이면 `missing_runs` = DOE run_key 중 출력이 하나도 없는 run. `curations` READY + counts. 결과 `{curation_id, target_count, ok_count, failed_count, missing_run_count, output_display_path}` |

hvtrans cfg 생성 규칙(원본 GUI:736-842 그대로):

```text
time_steps = range(1, num_time_step + 1, time_increment)                 (GUI:327-336)
request_lines = ["<DataType>|<comp>" for items(표 순서) if DataType != "Displacement"] + ["Displacement"]
datatype_order = items에 나온 DataType 순서(Displacement 제외)
lines = ["BeginParts"]
  shell 있으면 "    BeginPool:Shell", 각 id "        <id>", "    EndPool"  (Solid, Rbody 동일 순서)
lines += ["EndParts", "BeginSubcase:1"]
  각 step: "    BeginSimulation:<step>", 각 req "        <req>", "    EndSimulation"
lines += ["EndSubcase"]
ExtendedInfo: datatype_order마다 "{1 0 1 <all>}"(all = 그 DataType의 usable 개수 >0 이고 선택 개수 == usable 개수면 1, 아니면 0) + 마지막 "{1 0 1 1}"
lines += ["ExtendedInfo: " + " ".join(groups)]
본문 = "\n".join(lines) + "\n"
```

②-2 완료 후 ③-1 카드의 기본 입력이 "최근 READY H3D 큐레이션"이 된다. `DATASET_CREATE` `params.curation_id`를 주면 `input_path` = `C/CURATED_DATA`(둘 다 주면 422).

### 6.9 ②-3 `CU_T01_PREVIEW`

`params`: `{source, sample_file?}`. 작업 폴더 `W = 02_preview/<job_id>/`. HW_PREVIEW_T01(LOCAL): 템플릿 `t01_preview`, `{preview_tcl}`=`resources.preview_hg_tcl`(원본 `BATCHRUN_preview_hg.tcl`, GUI:34), `{t01}`(`/`), `{result_json}`=`W/PREVIEW_T01.json`(원본 GUI:37), cwd `W`. 성공 = 종료코드 0 + json 존재. TP_PARSE: 키 `dataTypes:[{name, requests:[{name, components:[…]}]}]` 검증(원본 GUI:259-289) → `PREVIEW_JSON` artifact.

### 6.10 ②-4 `CU_T01_CURVES`

`params`: `{source, curves: [{type, request, component}], exclude_files?: []}`. `C = 02_curated/<curation_id>/`.

| step_key | kind | 처리 |
|---|---|---|
| TC_PREP | INTERNAL | `C/work/INPUT_CURATE_CURVE.json` = 원본 `__create_input_json`(GUI:459-532) 형식 `{"curves":[{"yDataType","yRequest","yComponent"}], "jobs":[{"inputFile","outputFile"}]}`, `outputFile` = `C/CURVES/<run_folder>/<base>_curves.json`(base = 파일명에서 끝 `T01` 제거), 경로 `/` 구분. 출력 폴더 미리 생성 |
| HW_CURVE_EXPORT | LOCAL | 템플릿 `t01_curve_export`, `{curate_tcl}`=`resources.curate_hg_tcl`(원본 `BATCHRUN_curate_hg.tcl` — 업로드본에 있음), `{config_json}`(`/`), cwd `C/work`. 성공 = 종료코드 0(원본 `2_curate_t0.py:228`). 한 번의 hw 호출이 모든 job 처리 |
| TC_REGISTER | INTERNAL | job별 `outputFile` 존재 확인 → `file_list.json`(없는 것은 `ok=false`), 성공 0개면 FAILED `OUTPUT_MISSING`. 첫 출력이 `ui.max_artifact_bytes` 이하면 `CURVE_JSON` artifact로 등록(형식 미확인 U27 — 화면은 `series`가 있으면 그래프, 없으면 JSON 트리) |

### 6.11 ②-0 `SPDM_IMPORT` (G)

`params`: `{spdm_path: str}`. `I = <study>/02_import/<import_id>/`.

| step_key | kind | 처리 |
|---|---|---|
| SI_SCAN | INTERNAL | §13.3 경로 검사(SPDM 루트) 재확인. 재귀로 `spdm_import.patterns`(기본 `["*.h3d", "*T01"]`, 대소문자 무시) 일치 일반 파일 수집(링크·reparse 거부, 디렉터리 링크는 따라가지 않음). 개수 ≤ `spdm_import.max_files`, 총량 ≤ `spdm_import.max_total_bytes`, AI 루트 여유 공간 ≥ 총량 × 1.1(아니면 `INPUT_INVALID`). 상대경로의 구성요소에 공백·cmd 메타문자·제어문자·Windows 예약 이름이 있으면 `_`로 바꾼 이름을 정한다(충돌 시 `~N`) |
| SI_COPY | INTERNAL | 원본은 `open(path, "rb")`로만 연다. `I/<정리된 상대경로>`로 복사(`shutil.copyfileobj` 1 MiB, **하드링크·심볼릭 링크·`os.replace`·`copy2`(메타데이터 쓰기) 금지**), 대상 mtime만 `os.utime(대상)`으로 원본 값 설정. 진행률 = 바이트. 취소 확인 = 1 MiB마다 |
| SI_REGISTER | INTERNAL | `I/import_manifest.json` = `{spdm_path, imported_at, files:[{source_rel, dest_rel, size, renamed}]}` → `FILE_LIST` artifact. `spdm_imports` READY |

SPDM 쪽에는 어떤 쓰기도 없다(파일 생성·이름 변경·속성 변경·잠금 파일 0). 정적 시험·동적 시험 §20 V2-SPDM-1~3.

### 6.12 ⑤ `OPTIMIZE`

`params`:

```jsonc
{"param_set_id": null, "model_id": null,            // 기본 current / Final (확정값 저장, B8)
 "approach": "OPT",                                 // OPT | DOE (원본 GUI:117-120)
 "opt_method": "ARSM",                              // ARSM | GRSM | SQP (원본 GUI:106)
 "max_designs": 25,                                 // 1~100000 (원본 GUI:273-275). SQP는 "Maximum Iterations" 라벨
 "run_nominal": true,                               // 원본 GUI:278-279 기본 true
 "study_folder": "HST_PHYSICSAI_OPTIMIZATION",      // ^[A-Za-z0-9_\-]{1,64}$ (원본 GUI:851-855)
 "opt_settings": {"abs_convergence": 0.001, "rel_convergence": 1.0, "dv_convergence": 0.001},  // 1e-6~1000, dv는 0~1000 (원본 GUI:286-311)
 "on_failed": "IGNORE",                             // IGNORE | TERMINATE (원본 GUI:886)
 "responses": [ {"name": "MAX_VM", "source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises",
                 "layer": "", "stat": "MAX", "goal": "MINIMIZE"},
                {"name": "DISP_X", "source": "XYDATA", "request": "Node 100", "component": "X",
                 "stat": "ABSMAX", "goal": "CONSTRAINT", "bound": "<=", "value": 5.0} ]}
```

RESPONSES 검증(원본 GUI:709-735, 766-792): name `^[A-Za-z][A-Za-z0-9_]*$` ≤64, 대소문자 무시 중복 금지; source `H3D`(subcase int ≥1, datatype, component, layer — 빈 문자열 허용) | `XYDATA`(request, component); 모든 문자열에 `|` 금지; stat `MAX|MIN|ABSMAX`; goal `NONE|MINIMIZE|MAXIMIZE|CONSTRAINT`; CONSTRAINT면 bound `<=|>=|==`·value 유한 숫자 필수, 그 외 goal이면 bound·value 제거; approach=OPT면 MINIMIZE/MAXIMIZE ≥1(아니면 422 `OBJECTIVE_REQUIRED`); 행 ≥1. 메서드별 기본값(원본 GUI:110-114 `METHOD_DEFAULTS`: ARSM 25·dv 0.001, GRSM 50, SQP 25·dv 0.0)은 프런트가 메서드 변경 시 채운다. 사용 가능 표시(원본 GUI:799-811): abs·rel은 OPT+ARSM만, dv는 OPT+ARSM/SQP, on_failed는 OPT — 비활성이어도 값은 JSON에 그대로 보낸다(원본 동작).

작업 폴더 `O = <study>/05_opt/<job_id>/`(= `DIR_WORK`), 입력 원천 `S = 04_params/<param_set_id>/`.

| step_key | kind | 처리 | 가중 |
|---|---|---|---|
| OP_PREP | INTERNAL | 모델 sha256 재확인(1차 §8.3). `O/<study_folder>`가 이미 있으면 백업 이동(원본은 확인 후 삭제 GUI:916-924 → 2차는 이동). `stage_launcher("optimization", O)`, `resources.extract_minmax_tcl`을 `O/`로 복사(원본 FUNC:360-366). `O/INPUT_HST_RUN.json` 작성(아래 키 **전부**, 원본 GUI:859-889 + FUNC:364-368) → `RUN_CONFIG` artifact. `optimizations` 행 `RUNNING` | 3 |
| HST_OPTIMIZE | LOCAL | 템플릿 `hst_optimization`(기본 `["@cmd_c", "{hstpy}", "{launcher}"]`, 원본 FUNC:120-122), `{launcher}` OS 구분자(원본 `_norm`), cwd `O`, env 추가 = `optimize.env`(기본 `EDS_TNS_ACTVN_CHCKPT=1`) + `ALTAIR_HOME=<altair_home>`(원본 FUNC:111-117). 진행: 줄마다 `optimize.progress_regex`(기본 원본 FUNC:384 `Started\s+run\s+\(\s*(?P<run>\d+)\s*\),\s*model\s+\(\s*m_1\s*\)`) → `runs_started = max`, 라벨 "run N 시작"; approach=OPT면 `progress_pct = min(N / max_designs × 100, 99)`, DOE면 NULL(총수 미상, 원본 FUNC:381-383 주석). **오류 정규식은 적용하지 않는다**(원본은 종료코드만 판정 FUNC:397-403, 실패 평가 무시 설정과 충돌 방지 — 가정 A-8). 일치 줄 수만 `result.log_error_lines`로 기록 | 90 |
| OP_SUMMARY | INTERNAL | ① `O/<study_folder>` 재귀 파일 목록(≤ `optimize.max_listed_files`) → `O/file_list.json` `FILE_LIST` artifact. ② `optimize.viewable_globs`(기본 `["*.csv", "*.txt", "*.json", "*.log"]`) 일치 + 크기 ≤ `ui.max_artifact_bytes`인 파일 최대 `optimize.max_viewable_files`(기본 200)개를 `OPT_FILE` artifact로 등록. ③ 요약 파서 `optimize.summary_parsers`(§6.12.1) 순서대로 적용 → 첫 성공을 `O/summary.json` `OPT_SUMMARY` artifact, `summary_status=PARSED`, 없으면 `UNRECOGNIZED`. `optimizations` DONE | 7 |

`INPUT_HST_RUN.json`(RUN_CONFIG) 키 — 원본 인용, 값 출처:

| 키 | 값 |
|---|---|
| `ALTAIR_HOME` | `altair.altair_home`(빈 값이면 hstpy 폴더의 `../../..`, 원본 GUI:420-422) `/` 구분 |
| `DIR_WORK` | `O` |
| `STUDY_FOLDER` | `params.study_folder` |
| `CAD_PARAM` | `S/cad/<CAD>` |
| `TPL_FILE` | `S/simlab_parametered_mesh.tpl` |
| `HYPERMESH_TCL` | `resources.hypermesh_include_tcl`(원본 `BATCHRUN_create_include_node_elem.tcl`) |
| `RADIOSS_ASSEM_DIR` | `S/radioss_assem` |
| `PHYSICSAI_INPUT_FILE` | `S/radioss_assem/<starter>` |
| `PHYSICSAI_MODEL` | 모델 등록 복사본 `.psmdl` |
| `PREDICTED_H3D` / `PREDICTED_XYDATA` | `<starter stem>_pred.h3d` / `<starter stem>_pred.xydata` (원본 GUI:869-870) |
| `HYPERVIEW_TCL` | `O/<extract_minmax_tcl 파일명>` (원본 FUNC:365 작업 폴더 복사본) |
| `ALTAIR_PATHS` | `{"simlab_path": altair.simlab_path}` (원본 GUI:872 — simlab만) |
| `PHYSICSAI_OVERRIDE_ENV` | `false` (원본 GUI:873) |
| `RUN_NOMINAL` | `params.run_nominal` |
| `APPROACH` / `OPT_METHOD` / `MAX_DESIGNS` | params |
| `OPT_SETTINGS` | `{"ABS_CONVERGENCE", "REL_CONVERGENCE", "DV_CONVERGENCE"}` |
| `ON_FAILED` | `"IGNORE"` \| `"TERMINATE"` |
| `RESPONSES` | 검증된 행을 원본 키 대문자로: `NAME, SOURCE, STAT, GOAL, COMPONENT` + H3D `SUBCASE, DATATYPE, LAYER` / XYDATA `REQUEST` + CONSTRAINT `BOUND, VALUE` (원본 GUI:742-792) |

경로는 모두 절대경로 `/` 구분. 업로드본 예시 `CONFIG/BATCHRUN/INPUT_HST_RUN.json`의 `MAX_STRAIN`·`MAX_FORCE`는 구버전 키로 보고 쓰지 않는다(GUI가 만들지 않음, 가정 A-9).

#### 6.12.1 결과 요약 파서(플러그형, U28)

`optimize.summary_parsers: [{name, glob, kind, max_rows?}]`(기본 `[]`). `kind`: `csv_table`(첫 일치 CSV → `{columns, rows ≤ max_rows(기본 1000)}`), `json_passthrough`(첫 일치 JSON을 크기 상한 안에서 그대로). DB에는 `summary_meta`만. 파서가 없거나 실패하면 화면에 "결과 요약 형식 미확인 — 원본 파일 목록을 확인하세요"와 파일 목록·보기 가능한 파일 링크.

#### 6.12.2 응답 후보(동기 API)

`GET /studies/{id}/optimize/response-candidates?model_id=` — 같은 Study의 최근 `SUCCEEDED` `PREDICT`(모델 일치 우선, 없으면 아무 모델)의 `H3D_PREVIEW.json`(1차 §8.9 `PREVIEW_JSON`)과 `curve.json`에서 콤보 목록을 만든다: h3d `{subcases:[{id, label, datatypes:[{name, components, layers, format}]}]}`(원본 `_load_preview` GUI:547-574 구조), xydata `{requests:{name:[component]}}`. 미리보기가 원본 형식과 다르면 가능한 키만, 없으면 `null` → 화면은 "④에서 예측을 한 번 실행하면 목록이 채워집니다" + **직접 입력 허용**(원본은 XYDATA만 직접 입력 허용 — 2차는 둘 다, 가정 A-10).

### 6.13 F — ① 결과로 ④ 파라미터 세트 만들기(동기 API)

`POST /studies/{id}/param-sets/from-train {doe_id, runs?: "collected" | "all"(기본 collected), unit_system?: str}`:

```text
1. DOE READY, sample_status ∈ {PARSED, PARTIAL}(아니면 409 SAMPLES_MISSING), runs=collected면 COLLECTED run ≥1(409 DOE_NOT_READY)
2. 임시 폴더 <study>/logs/_paramset_tmp/<uuid>/ 에 1차 §15.4 폴더 구조를 만든다
   parameters.json  : parameters_snapshot(사용 파라미터)의 {name, nominal, min, max, unit}, unit_system
   samples.csv      : samples.csv에서 대상 run 행만 + run_responses.csv가 있으면 resp:<이름> 열 병합
   responses.json   : ①-6 responses.json이 있으면 그대로, 없으면 {"responses": []}
   cad/<CAD>        : 01_train/cad 사본
   simlab_parametered_mesh.tpl : DOE에 쓴 tpl(D/ 사본)
   radioss_assem/   : 01_train/radioss_assem/<doe_id>/
3. 1차 파라미터 세트 검증기·등록 함수를 그대로 호출(정규화본·original/ 사본·is_current 전환, 총량 상한)
4. param_sets.origin='TRAIN_DOE', train_doe_id=doe_id, source_path="① DOE <doe_id 앞 8자>"(표시용)
5. 임시 폴더는 원래 위치에서 os.replace로 04_params/<id>/로 옮긴다(삭제 호출 없음)
```

1차 CSV/JSON 폴더 등록 경로(`POST /studies/{id}/param-sets {path}`)는 그대로 유지한다.

---

## 7. 상태 머신 영향

### 7.1 작업 전이 추가

| # | 전이 | 주체 | 조건·부수효과 |
|---|---|---|---|
| T10b | `WAITING_HPC` → `COLLECTING` | HPC 폴러 | **`TD_SOLVE`이고 `on_run_failure=collect_partial`**, 모든 hpc_job 종료, 성공 ≥1, 실패(FAILED·LOST) ≥1. `attention_code=HPC_RUN_FAILED` 유지, 작업 warnings `HPC_PARTIAL_FAILED`, 알림 `HPC_PARTIAL_FAILED` |

- 모두 실패이거나 `on_run_failure=fail`이면 1차 T13(`HPC_RUN_FAILED`).
- 다중 run 취소(T12)·연결 실패(T13 `HPC_UNREACHABLE`)는 1차 그대로 작업의 hpc_job 전부에 적용.
- 재시도(B9): `TD_SOLVE`는 항상 TS_PREP부터 새 attempt(PBS 제출 재사용 안 함). `run_keys`를 원 작업 값 그대로 쓰되, null이었으면 재시도 시점의 미완료 run으로 다시 계산.
- 그 밖의 2차 작업은 1차 전이 표만 쓴다(HPC 없음). 상태 머신 표 시험(V-SM-1)에 T10b 추가.

### 7.2 엔터티 상태

| 엔터티 | 상태 흐름 |
|---|---|
| `train_does` | 생성 `BUILDING` → DG_SCAN 성공 `READY` / 작업 실패·취소·중단 `FAILED` |
| `train_runs` | `GENERATED` → `SUBMITTED` → `SOLVED`/`SOLVE_FAILED` → `COLLECTED`/`COLLECT_FAILED`. `TD_RESULT_IMPORT`는 어떤 상태에서든 `COLLECTED`로. 재제출 대상 = `GENERATED|SOLVE_FAILED|COLLECT_FAILED` |
| `curations`, `spdm_imports` | `BUILDING` → `READY` / `FAILED` |
| `optimizations` | `RUNNING` → `DONE` / `FAILED` |
| `env_checks` | §9.4 |

### 7.3 알림(I)

| event | 발생 | 수신자 | title 예 |
|---|---|---|---|
| `JOB_STARTED`·`JOB_SUCCEEDED`·`JOB_FAILED`·`JOB_CANCELED`·`JOB_INTERRUPTED`·`MY_TURN_NEXT` | 1차 그대로, 2차 작업 유형 포함 | 등록자 | "완료: DOE·Radioss 입력 생성 (cushion)", "실패: 큐레이션 (cushion) — EXIT_NONZERO", "완료: 최적화 (cushion)" |
| `HPC_COLLECTED` | T14·T15(①-4 포함) | 등록자 | "PBS 결과 회수 완료 — 30개 중 29개 회수" |
| `HPC_PARTIAL_FAILED` (신규) | T10b | 등록자 | "PBS 해석 일부 실패 — 30개 중 1개 실패, 나머지 회수 진행" |
| `ENV_CHECK_DONE` (신규) | env check `DONE`·`FAILED`·`EXPIRED` | 요청한 관리자 | "환경 점검 완료 — 실패 2 · 경고 1" (job_id·study_id NULL, 클릭 시 환경 점검 화면) |

title의 작업 표시명은 `job_label()`(§6.1 "화면 버튼"과 같은 한국어 이름: 파라미터 추출, DOE·Radioss 입력 생성, PBS 해석, 결과 가져오기, run 응답 추출, h3d 미리보기, 큐레이션, T01 미리보기, 곡선 추출, SPDM 가져오기, 최적화).

---

## 8. 명령 템플릿·설정

### 8.1 템플릿 키 추가(1차 §9.2 확장)

| 키 | 사용 step | 허용 placeholder | 기본값(원본 인용) | 상태 |
|---|---|---|---|---|
| `simlab_extract_params` | SIMLAB_EXTRACT | `{simlab} {launcher} {cad_file} {xml_out}` | `["{simlab}", "-auto", "{launcher}", "{cad_file}", "{xml_out}", "-nographics"]` — `1_CREATE_TRAINING_DATA/FUNC/1_create_tpl_file.py:45` | 확정(원본) |
| `hst_gen_radioss` | HST_GEN_RADIOSS | `{hstbatch} {multi_execution} {launcher}` | `["{hstbatch}", "-multiexec", "{multi_execution}", "-pyfile", "{launcher}"]` — `2_run_hst_gen_rad_input.py:39` | 확정(원본) |
| `h3d_preview` | HW_PREVIEW_H3D | `{hw} {preview_tcl} {h3d} {result_json}` | `["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{preview_tcl}", "-h3d", "{h3d}", "-result", "{result_json}"]` — `2_DATA_CURATION/FUNC/1_curate_h3d.py:29-36` | 확정(원본) |
| `hvtrans_curate` | HVTRANS_CURATE | `{hvtrans} {cfg} {h3d} {out_h3d}` | `["{hvtrans}", "-c", "{cfg}", "{h3d}", "{h3d}", "-o", "{out_h3d}", "-z0"]` — `1_curate_h3d.py:267-273` | 확정(원본) |
| `t01_preview` | HW_PREVIEW_T01 | `{hw} {preview_tcl} {t01} {result_json}` | `["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{preview_tcl}", "-input", "{t01}", "-output", "{result_json}"]` — `2_DATA_CURATION/FUNC/2_curate_t0.py:37-45` | 확정(원본) |
| `t01_curve_export` | HW_CURVE_EXPORT | `{hw} {curate_tcl} {config_json}` | `["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{curate_tcl}", "-config", "{config_json}"]` — `2_curate_t0.py:198-205` | 확정(원본) |
| `hst_optimization` | HST_OPTIMIZE | `{hstpy} {launcher}` + `@cmd_c` | `["@cmd_c", "{hstpy}", "{launcher}"]` — `4_OPTIMIZATION/FUNC/1_physicsai_opti.py:120-122` | 확정(원본) |
| `response_extract`(1차) | + RESPONSE_EXTRACT_RUNS | 1차와 같음 | null | 미확인(U8) |

- 실행 파일 placeholder 추가: `{hstpy}` → `altair.hstpy_path`. 값이 비면 `dirname(altair.hyperstudy_path)/hstpy.bat`(원본 GUI:409-418), `altair.altair_home`이 비면 `<hstpy 폴더>/../../..`(원본 GUI:420-422)로 파생. 파생 규칙은 코드에 두되 경로 문자열은 설정값에서만 시작한다.
- 확정 템플릿(위 표 "확정")은 null 허용(1차의 "확정 템플릿 null 금지"와 달리 **2차 키는 null이면 그 기능만 비활성**) — 1차 사용자가 2차 기능 없이 운영할 수 있게(가정 A-11). 예시 YAML에는 원본 기본값을 넣는다.
- 값 표기: `{launcher}`(hst_gen_radioss)·`{h3d}`·`{result_json}`·`{t01}`·`{curate_tcl}`·`{config_json}`·`{preview_tcl}`(h3d/t01) = `/` 구분(원본 GUI가 `replace("\\","/")`), `{cfg}`·`{h3d}`·`{out_h3d}`(hvtrans)·`{launcher}`(simlab_extract·hst_optimization)·`{cad_file}`·`{xml_out}` = OS 기본(원본 `os.path.abspath`/`normpath`). 템플릿별 표기 규칙은 `commands.py`의 키별 사양 표에 둔다.
- `.bat` 실행(`SimLab.bat`, `hstpy.bat`)은 B24(치환 값에 `; , = ( )` 추가 거부)가 그대로 적용된다.

### 8.2 설정 YAML 추가 키(`config/platform.example.yaml`에 반영 — Impl-Backend)

```yaml
altair:
  hstpy_path: ""        # 빈 값 = hyperstudy_path 폴더의 hstpy.bat (원본 4_OPTIMIZATION/GUI:409-418)
  altair_home: ""       # 빈 값 = hstpy 폴더/../../.. (원본 GUI:420-422)

resources:              # 원본 반입본 위치. 절대경로·공백/메타문자 없음. 값이 있으면 존재해야 함(prod). 빈 값 = 그 기능 비활성
  preview_pred_h3d_tcl: "D:/physicsai/resources/BATCHRUN/BATCHRUN_preview_pred_h3d.tcl"   # 1차
  batchrun_dir: "D:/physicsai/resources/BATCHRUN"          # 원본 CONFIG/BATCHRUN (런처 .py)
  pyd_dir: "D:/physicsai/resources/BUILD_PYD"              # 원본 BUILD_PYD (*.pyd) — 업로드본에 없음(U19)
  simlab_tpl_template: "D:/physicsai/resources/TEMPLATE/TEMAPLATE_simlab_parametered_mesh.tpl"   # 업로드본에 없음(U19)
  doe_design_type_json: "D:/physicsai/resources/DATA/DATA_doe_design_type.json"
  hypermesh_include_tcl: "D:/physicsai/resources/BATCHRUN/BATCHRUN_create_include_node_elem.tcl"  # 업로드본에 없음(U19)
  preview_h3d_tcl: "D:/physicsai/resources/BATCHRUN/BATCHRUN_preview_h3d.tcl"     # 업로드본에 없음(U19)
  preview_hg_tcl: "D:/physicsai/resources/BATCHRUN/BATCHRUN_preview_hg.tcl"       # 업로드본에 없음(U19)
  curate_hg_tcl: "D:/physicsai/resources/BATCHRUN/BATCHRUN_curate_hg.tcl"
  extract_minmax_tcl: "D:/physicsai/resources/BATCHRUN/H3D_StaticMinMax_to_CSV_FAST.tcl"   # 업로드본에 없음(U8·U19)
  launchers:
    extract_params: {script: BATCHRUN_get_parameter_from_cad.py, core: get_parameter_from_cad_core}
    gen_radioss:    {script: BATCHRUN_hst_gen_radioss_input.py,   core: hst_gen_radioss_core}
    optimization:   {script: BATCHRUN_hst_physicsai_optimization.py, core: hst_physicsai_optimization_core}

storage:
  spdm_roots: []        # 1차 키. 2차부터 이 하위가 SPDM 가져오기 허용 범위(읽기 전용)

train_data:
  cad_extensions: [".prt"]
  max_xml_bytes: 4194304
  extract_progress_token: "Passed"          # 원본 1_create_tpl_file.py:18
  extract_progress_total: 4                 # 원본 :51
  param_default_range_ratio: 0.05           # 원본 1_gui_create_tpl_file.py:299-300
  param_default_format: "%3i"               # 원본 1_create_tpl_file.py:171
  tpl_marker: "#***************************************************************"     # 원본 :159
  tpl_prt_regex: 'dir_file_prt\s*=\s*r"[^"]*"'
  tpl_parameter_line_regex: '(?m)^[^\n]*\{parameter\(.*?\)\}[^\n]*\n?'
  tpl_paramitem_line_regex: '(?m)^[^\n]*<paramitem[^>]*/>[^\n]*\n?'
  max_runs: 2000
  max_multi_execution: 8
  hst_progress_regex: 'Finished run\s*\(\s*(?P<run>\d+)\s*\),\s*model\s*\(\s*m_?3\s*\)'   # 원본 2_run_hst_gen_rad_input.py:59-61
  hst_log_error_patterns:                   # 원본 :64-71
    - '^\s*\d+\s+Error\s*:'
    - 'Traceback \(most recent call last\):'
    - '^\s*\[ERROR\]'
    - '^\s*(?:FileNotFoundError|RuntimeError|ValueError|OSError|PermissionError|ImportError|TypeError|AttributeError|NameError|SyntaxError)\s*:'
  run_dir_glob: "approaches/*/run__*"       # 사내 확인 후 교체(U17)
  samples_extractor: paramitem              # paramitem | csv | none (U18)
  rendered_tpl_glob: "**/*"
  rendered_tpl_exts: [".py", ".tcl", ".txt", ".xml", ""]
  samples_scan_max_bytes: 1048576
  paramitem_regex: '<paramitem\s+Name="(?P<name>[^"]+)"\s+NewValue="(?P<value>[^"]*)"'
  samples_csv_glob: null
  samples_csv_run_column: run_key
  max_runs_per_submit: 500
  result_run_dir_regex: '^(?P<run_key>run__\d+)$'   # 사내 확인 후 교체(U25)
  result_match_depth: 3

hpc:
  transfer:
    collect_mode: in_place          # in_place | shared_folder | drive(= shared_folder 별칭)
    collect_root_local: ""          # shared_folder/drive: 이 PC에서 읽는 결과 루트(읽기 전용)
    collect_root_remote: ""         # 같은 루트의 PBS 노드 경로

curation:
  max_files: 20000

spdm_import:
  patterns: ["*.h3d", "*T01"]
  max_files: 20000
  max_total_bytes: 536870912000     # 500 GiB

optimize:
  default_study_folder: HST_PHYSICSAI_OPTIMIZATION   # 원본 GUI:847
  env: {EDS_TNS_ACTVN_CHCKPT: "1"}                   # 원본 1_physicsai_opti.py:113
  progress_regex: 'Started\s+run\s+\(\s*(?P<run>\d+)\s*\),\s*model\s+\(\s*m_1\s*\)'   # 원본 :384
  max_listed_files: 5000
  viewable_globs: ["*.csv", "*.txt", "*.json", "*.log"]
  max_viewable_files: 200
  summary_parsers: []               # 형식 미확정(U28)

env_check:
  probe_timeout_s: 60               # 점검용 짧은 실행만의 상한(작업 step 시간 한도 아님 — V-SM-6 대상 아님)
  expire_s: 900
  min_free_gb: 50
  probes:                           # 짧은 실행 argv. null = 존재·실행 가능 확인만(기본). 인자는 사내 확인 후(U32)
    edspy: null
    simlab: null
    hw: null
    hstbatch: null
    hvtrans: null
    hstpy: null

error_bundle:
  log_tail_bytes: 262144            # 로그 파일당 꼬리 상한
  max_total_bytes: 20971520         # zip 전체(압축 전) 상한

commands:                           # §8.1 기본값(원본 인용)
  simlab_extract_params: ["{simlab}", "-auto", "{launcher}", "{cad_file}", "{xml_out}", "-nographics"]
  hst_gen_radioss: ["{hstbatch}", "-multiexec", "{multi_execution}", "-pyfile", "{launcher}"]
  h3d_preview: ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{preview_tcl}", "-h3d", "{h3d}", "-result", "{result_json}"]
  hvtrans_curate: ["{hvtrans}", "-c", "{cfg}", "{h3d}", "{h3d}", "-o", "{out_h3d}", "-z0"]
  t01_preview: ["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{preview_tcl}", "-input", "{t01}", "-output", "{result_json}"]
  t01_curve_export: ["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{curate_tcl}", "-config", "{config_json}"]
  hst_optimization: ["@cmd_c", "{hstpy}", "{launcher}"]
```

검증 규칙 추가(1차 §14.3 확장): `resources.*` 비었거나 절대경로·공백/메타 없음·prod면 존재, `launchers.*.script` 파일명만(`/`·`\` 없음, `.py`), `core` `^[A-Za-z_][A-Za-z0-9_]*$`; 정규식 키 컴파일 + 필수 그룹(`hst_progress_regex`·`progress_regex`: `run`, `paramitem_regex`: `name`·`value`, `result_run_dir_regex`: `run_key`); `max_multi_execution` 1~64; `env_check.probes.<tool>` argv[0]이 그 도구 placeholder이고 다른 placeholder 없음; `collect_mode=shared_folder|drive`면 두 루트 필수·비중첩; `optimize.summary_parsers[].kind` 값. 알 수 없는 키 거부(1차 유지).

### 8.3 오류 정규식 적용 표

| step | 적용 |
|---|---|
| SIMLAB_EXTRACT, HW_PREVIEW_*, HVTRANS_CURATE, HW_CURVE_EXPORT, RESPONSE_EXTRACT_RUNS | 없음(원본도 종료코드·출력 존재만 판정) |
| HST_GEN_RADIOSS | `train_data.hst_log_error_patterns` |
| HST_OPTIMIZE | 없음(줄 수만 기록, 가정 A-8) |
| 1차 edspy step | 1차 `commands_log_error_patterns` 그대로 |

---

## 9. A. 환경 점검

### 9.1 실행 위치 결정

**하이브리드**: API는 실행 파일을 실행하지 않는다(1차 §4.3, V-SEC-3) → 외부 프로그램·파일 시스템·Job Object가 필요한 항목은 **워커**, DB·대시보드·설정·HPC 모드처럼 API가 이미 가진 정보는 **API가 요청 즉시** 채운다. 작업 대기열(`jobs`)은 쓰지 않는다(Study 소속이 아니고 슬롯을 잡을 필요가 없는 짧은 점검 — 가정 A-12). 워커는 `light` 스레드에서 LIGHT 작업이 없을 때 `env_checks`를 claim한다.

### 9.2 API 부분(`POST /admin/env-checks` 안에서 동기, 각 항목 타임아웃은 기존 설정값)

| key | category | 판정 |
|---|---|---|
| `config.valid` | CONFIG | 설정 검증 오류 0 → OK, 아니면 FAIL(오류 키 목록) |
| `db.connection` | DATABASE | `SELECT 1` 성공·지연 ms |
| `db.migration_head` | DATABASE | `alembic_version.version_num == MIGRATION_HEAD` → OK, 다르면 FAIL `{current, head}` |
| `auth.dashboard` | AUTH | `auth.mode=dashboard`: 요청자 토큰으로 introspection 재호출(캐시 우회) 200 → OK `{latency_ms}`, 그 밖은 FAIL(1차 §5.2 매핑 코드). `dev_static` → SKIP "개발 모드" |
| `auth.projects` | AUTH | 대시보드 `GET /api/projects` 200 → OK `{count}` |
| `hpc.gateway` | HPC | `availability()` — `none` → WARN "PBS 연결 안 됨", configured → OK, 설정 오류 → FAIL |
| `worker.heartbeat` | WORKER | 최신 heartbeat 나이 ≤ 3×interval → OK `{worker_id, age_s, limiter}`, 아니면 FAIL "워커 오프라인 — 워커 항목은 실행되지 않습니다" |

### 9.3 워커 부분

| key | category | 판정 |
|---|---|---|
| `altair.<key>` (`hyperstudy_path, simlab_path, edspy_path, hw_exe_path, hvtrans_exe_path, hstpy_path`) | EXECUTABLE | 빈 값 → WARN "미설정"; 파일 존재 + Windows: 확장자 ∈ `PATHEXT` + 읽기 가능 / POSIX: `os.access(X_OK)` → OK `{path, size, mtime}`; 없음 → FAIL |
| `probe.<tool>` | EXECUTABLE | `env_check.probes.<tool>` null → SKIP "존재 확인만(인자 미확인)"; 있으면 **제한기 안에서** 실행, `probe_timeout_s` 초과 시 트리 종료 → FAIL "시간 초과"; 종료코드 0 → OK `{exit_code, duration_ms}`. 출력 꼬리 4 KiB(마스킹)는 보고서 파일에만 |
| `resource.<key>` | RESOURCE | `resources.*` 각각(launchers는 script 존재 + compiled면 pyd 정확히 1개) — 빈 값 WARN "미설정(해당 기능 비활성)", 없음 FAIL |
| `storage.ai_root.write` | STORAGE | `<ai_root>/_platform/env_check_tmp/` 생성(없으면) → `tempfile.NamedTemporaryFile(dir=그 폴더, delete=True)`로 1 KiB 쓰기·fsync·닫기(자동 삭제) → OK. **명시적 삭제 호출 없음**(1차 V-CMD-7 허용 목록 유지) |
| `storage.ai_root.free` | STORAGE | 여유 ≥ `env_check.min_free_gb` OK, 아니면 WARN |
| `storage.roots_overlap` | STORAGE | ai_root·allowed_import_roots·collect_root_local과 spdm_roots 비중첩 재확인 |
| `storage.spdm_roots` | STORAGE | 각 루트 존재·읽기 가능(`os.listdir` 1회) → OK, 비었으면 SKIP |
| `worker.limiter` | WORKER | `{name, cpu_cap_enforced}` — `windows_job` OK, `posix` WARN "CPU 상한 미적용(비Windows)", `null` WARN |
| `worker.job_object` | WORKER | Windows: 제한기로 `[sys.executable, "-I", "-c", "pass"]` 실행 → `IsProcessInJob` true + `QueryInformationJobObject`로 CPU rate·메모리 한도·KILL_ON_JOB_CLOSE 확인 → OK `{cpu_rate, memory_gb, priority}`; 비Windows → SKIP "Windows 아님" |
| `gpu.detect` | GPU | `worker.gpu_query` 실행 결과 GPU ≥1 → OK `[{name, memory_total_mb}]`, 0개·실패 → WARN |

보고서: `<ai_root>/_platform/env_checks/<id>/report.json`(API+워커 항목 전체 + 프로브 출력 꼬리). `report_rel`은 AI 루트 기준.

### 9.4 `env_checks` 상태

```text
POST(API, 전역 관리자) → PENDING(api_items 채움, expires_at 설정)  — 진행 중 건이 있으면 409 ENV_CHECK_BUSY
워커 claim: UPDATE … SET state='RUNNING', worker_id, started_at WHERE id=? AND state='PENDING' AND expires_at > now()
워커 완료: UPDATE … SET state='DONE', worker_items, summary, report_rel, finished_at WHERE id=? AND state='RUNNING' AND worker_id=? AND expires_at > now()
워커 예외: 같은 조건으로 state='FAILED', failure_message
만료: housekeeping(리퍼 주기)이 PENDING·RUNNING 이고 expires_at < now() → EXPIRED. API GET도 같은 조건이면 EXPIRED로 표시
DONE·FAILED·EXPIRED → ENV_CHECK_DONE 알림(요청자)
```

summary는 api_items + worker_items 상태 합계. 워커 오프라인이면 API 항목만 있는 채로 EXPIRED가 된다.

---

## 10. B. 오류 묶음 다운로드

### 10.1 권한·조건

- `GET /jobs/{job_id}/error-bundle.zip` — **작업 등록자 본인 또는 전역 관리자**(가정 A-13). 이유: 묶음에는 1차에서 전역 관리자에게만 보이는 step 명령 스냅샷(`?include=commands`)과 설정 요약이 들어가므로 "조회 가능자 전원"은 넓다. 본인 작업의 명령은 본인이 실행을 요청한 내용이라 공개해도 위험이 작다. 판정 순서 1차 §5.3(401 → 404 → 403 `PERMISSION_DENIED` `required:"owner_or_global_admin"` → 409).
- 대상 상태: `FAILED`·`CANCELED`·`INTERRUPTED`, 또는 `attention_code`가 있는 비종료 작업. 그 밖은 409 `ERROR_BUNDLE_NOT_AVAILABLE`.
- 감사 이벤트 `ERROR_BUNDLE_DOWNLOAD`.

### 10.2 내용(zip 안 고정 경로)

| 경로 | 내용 |
|---|---|
| `README.txt` | 생성 시각(UTC), 작업 id·유형·상태·실패 코드, 파일 설명(한국어) |
| `job.json` | `Job` 응답 모양(params·result·warnings·steps·failure·env_snapshot·retry_of) |
| `steps/step_<NN>_<key>.command.json` | step `command`(argv·cwd·env_added) + 팬아웃이면 commands.jsonl 앞 200줄 |
| `logs/job.log.tail.txt`, `logs/step_<NN>_<key>.log.tail.txt` | 꼬리 ≤ `error_bundle.log_tail_bytes`(UTF-8 경계 보정, 첫 줄에 "앞 N 바이트 생략") |
| `hpc_jobs.json` | 있으면 `GET /jobs/{id}/hpc-jobs` 모양 |
| `config_summary.json` | `redacted_settings`(1차 `/admin/config`) — DB URL·비밀은 원래 제외 + 아래 마스킹 재적용 |
| `environment.json` | app 버전, Python 버전, OS, `MIGRATION_HEAD`, `altair.version_label`, 실행 파일별 `{exists, size, mtime}`, 최신 heartbeat `{worker_id, limiter, effective_limits, gpu}` |
| `env_check_latest.json` | 최근 `DONE` 환경 점검의 summary·items(없으면 `null`) |

마스킹(모든 텍스트에 적용): 1차 `logging.mask_patterns` + 고정 규칙 — `postgres(ql)?(\+\w+)?://[^@\s]+@` → `…://***@`, `Bearer\s+\S+` → `Bearer ***`, `<auth.cookie_name>=\S+` → `=***`, 환경변수 이름이 `*PASSWORD*`·`*SECRET*`·`*TOKEN*`·`PG*`·`database.url_env`인 값 → `***`(B19 제외 목록과 같은 규칙).

### 10.3 전송

- B16과 같은 zip 스트리밍(deflate, zip64, 1 MiB 단위, 전체 적재 없음). `Content-Disposition: attachment; filename="<study>_<job8>_error_bundle.zip"`.
- 압축 전 누적 ≥ `error_bundle.max_total_bytes`이면 남은 로그 항목을 넣지 않고 `TRUNCATED.txt`(생략 목록) 추가. Study의 h3d·psdata 등 산출물 파일은 넣지 않는다(로그·JSON만).

---

## 11. H. 배포(`deploy/` — Windows 폐쇄망, **실제 Windows 실행 미검증**)

### 11.1 서비스 등록 방식 결정

NSSM 미사용 전제에서 후보는 (가) pywin32 서비스 래퍼, (나) 작업 스케줄러(`Register-ScheduledTask`). **(나)를 택한다**(가정 A-14):
- 추가 의존성 없음(pywin32는 설치 후 스크립트·DLL 등록이 필요하고 1차가 "pywin32 미사용"으로 정함).
- 부팅 시 시작(`-AtStartup`), 실패 재시작(`RestartCount 999`, `RestartInterval 1분`), **`ExecutionTimeLimit` = 0(무제한) 필수**(기본 72시간이면 장시간 작업 중 워커가 종료됨), `MultipleInstances IgnoreNew`(워커 단일 인스턴스 잠금과 이중 보호).
- 종료 시 `Stop-ScheduledTask`가 프로세스를 끝내면 Job Object `KILL_ON_JOB_CLOSE`로 자식 트리가 함께 정리된다(1차 §11.1).
- 실행 계정은 설치 매개변수(`-ServiceUser`, 기본 `NT AUTHORITY\SYSTEM` 아님 — AI 루트·Altair 라이선스 접근 권한이 있는 지정 계정). "로그온 여부와 관계없이 실행"이면 세션 0에서 돌므로 HyperWorks·SimLab 배치 동작은 U11·U31로 E2E 확인. `-RunMode Interactive`(로그온 사용자 세션에서 실행) 선택지도 둔다.

### 11.2 파일

| 파일 | 내용 |
|---|---|
| `deploy/deploy.example.json` | 설치 매개변수 예시: `install_root`, `python_exe`, `pg_bin`, `pg_host`, `pg_port`, `db_name`(`physicsai`), `db_role`(`physicsai_app`), `config_path`, `service_user`, `run_mode`, `backend_port`(8100), `caddy_frontend_root`. **경로 문자열은 이 파일과 매개변수에만**(스크립트 본문에 `Program Files` 금지) |
| `deploy/collect-offline.sh` / `.ps1` | **인터넷 되는 준비 PC**에서: `pip download -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.13 -d dist/wheels`, `pip wheel . --no-deps -w dist/wheels`(우리 패키지), `npm ci && npm run build`(frontend) → `dist/frontend`, `migrations/`·`config/platform.example.yaml`·`deploy/`·리소스 안내문을 묶어 `physicsai-offline-<version>.zip`. `--dry-run`은 실행할 명령만 출력 |
| `deploy/requirements.lock` | 런타임 의존성 고정 버전(pyproject 하한을 만족하는 정확 버전). 생성 방법은 스크립트 주석 |
| `deploy/install.ps1` + `install.bat` | bat은 `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*`만. ps1: ① 관리자 권한·Python 3.13 확인(`python_exe`) ② `<install_root>\venv` 생성, `pip install --no-index --find-links wheels physicsai-platform` ③ `frontend\dist` 배치 ④ `config_path`가 없을 때만 예시 복사(있으면 그대로) ⑤ DB: `psql`로 역할·DB가 없을 때만 생성(`CREATE ROLE … LOGIN PASSWORD`, `CREATE DATABASE physicsai OWNER …`), 비밀번호는 `Read-Host -AsSecureString`으로 받아 **명령 인자 대신 `PGPASSWORD` 프로세스 환경**으로만 전달·로그 미기록 ⑥ 시스템 환경변수 `PHYSICSAI_CONFIG`, `PHYSICSAI_DATABASE_URL`(머신 범위) 설정 ⑦ `alembic upgrade head` ⑧ 작업 2개 등록(`PhysicsAI-Backend`: `venv\Scripts\python.exe -m physicsai_api.serve`, `PhysicsAI-Worker`: `venv\Scripts\python.exe -m physicsai_worker`) ⑨ 시작 후 `GET http://127.0.0.1:<port>/physicsai/api/health` 확인 ⑩ Caddy 스니펫 출력 위치 안내 |
| `deploy/update.ps1` + `update.bat` | ① `GET /physicsai/api/queue`로 실행 중 작업이 있으면 중단(`-Force`면 경고 후 진행 — 실행 중 작업은 lease 만료 후 `INTERRUPTED`) ② 작업 2개 중지 ③ 기존 `venv`·`frontend\dist`를 `<install_root>\_backup\<UTC>`로 **이동**(삭제 없음) ④ 새 wheel 설치·프런트 배치 ⑤ `alembic upgrade head` ⑥ 시작·health 확인 ⑦ 실패 시 백업으로 되돌리는 방법 안내(자동 되돌림 없음) |
| `deploy/caddy/physicsai.caddy` | 대시보드 Caddyfile catch-all `handle` **앞**에 넣을 스니펫(1차 §20 D1): `redir /physicsai /physicsai/ 308`, `handle /physicsai/api/* { reverse_proxy 127.0.0.1:{$PHYSICSAI_PORT:8100} }`, `handle /physicsai/* { root * {$PHYSICSAI_FRONTEND_ROOT}; uri strip_prefix /physicsai; try_files {path} /index.html; file_server }` |
| `deploy/uninstall-tasks.ps1` | 작업 등록 해제만(파일·DB 삭제 없음) |

- 원본 반입 자원(§8.2 `resources.*`)은 설치 스크립트가 다루지 않는다 — 관리자가 `D:/physicsai/resources/` 등에 두고 설정에 적는다(라이선스·사내 배포물).
- Linux 자동 시험(§15)은 `deploy.example.json` 스키마, 스크립트가 참조하는 키 일치, `collect-offline.sh --dry-run` 출력, 금지 문자열(`Program Files`, 평문 비밀번호 인자) 부재만 확인한다. PowerShell 실행은 하지 않는다(가능하면 `pwsh -NoProfile -Command "& { [ScriptBlock]::Create((Get-Content …)) }"` 구문 검사, `pwsh` 없으면 **미수행**으로 기록).

---

## 12. REST API(접두 `/physicsai/api`, 1차 §10.1 공통 규칙 그대로)

### 12.1 상태·셸 확장

| 메서드·경로 | 권한 | 응답 변경 |
|---|---|---|
| `GET /status` | 로그인 | 추가: `altair[]`에 `hstpy_path`(파생 포함), `resources:[{key, configured, ok}]`, `features:{train_extract, train_tpl, train_doe, train_solve, train_import, train_resp, curation_h3d, curation_t01, spdm_import, optimize}`(각 `{enabled: bool, missing:[키]}` — 필요 템플릿·자원·altair 키 기준), `hpc.collect_mode`, `env_check:{latest_id, latest_state, finished_at, fail, warn}`(전역 관리자에게만 값, 그 외 null) |
| `GET /queue` | 로그인 | `JobSummary` 확장(§12.9) |

### 12.2 환경 점검(A)

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `POST /admin/env-checks` | 전역 관리자 | – | `202 EnvCheck` | 409 `ENV_CHECK_BUSY` |
| `GET /admin/env-checks?limit=&cursor=` | 전역 관리자 | – | `EnvCheckSummary[]`(+`X-Next-Cursor`, B2) | |
| `GET /admin/env-checks/latest` | 전역 관리자 | – | `EnvCheck` | 404 `NOT_FOUND` |
| `GET /admin/env-checks/{id}` | 전역 관리자 | – | `EnvCheck` | 404 |

```text
EnvCheckItem    = {key, category: "CONFIG"|"DATABASE"|"AUTH"|"HPC"|"WORKER"|"EXECUTABLE"|"RESOURCE"|"STORAGE"|"GPU",
                   label, status: "OK"|"WARN"|"FAIL"|"SKIP"|"PENDING", message, source: "API"|"WORKER", detail: object|null}
EnvCheckSummary = {id, state, requested_by_name, created_at, finished_at, summary: {ok, warn, fail, skip}}
EnvCheck        = EnvCheckSummary + {started_at, expires_at, worker_id, items: [EnvCheckItem], failure_message, report_display_path}
```

워커 항목은 claim 전에는 `status=PENDING`인 자리 항목으로 돌려준다(키 목록 고정, §9.3).

### 12.3 오류 묶음(B)

| `GET /jobs/{id}/error-bundle.zip` | 본인·전역 관리자 | – | zip 스트림 | 403, 404, 409 `ERROR_BUNDLE_NOT_AVAILABLE` |

`Job`에 `can_download_error_bundle: bool` 추가.

### 12.4 경로 확인 확장(1차 `POST /studies/{id}/paths/inspect`)

`purpose` 추가와 요약:

| purpose | 허용 루트 | 대상 | summary |
|---|---|---|---|
| `CAD_FILE` | AI 루트, allowed_import_roots | **파일** | `{file_name, size, extension_ok}` |
| `RADIOSS_ASSEM` | AI 루트, allowed_import_roots | 폴더 | `{rad:[≤50], inc_count, starter:[names], starter_ok}` |
| `RESULT_FOLDER` | AI 루트, allowed_import_roots, collect_root_local | 폴더 | `{doe_id?, matched_runs, unmatched_dirs:[≤20], file_count}` (요청에 `doe_id` 선택 키) |
| `CURATION_INPUT` | AI 루트(B23 확장 목록 거부) | 폴더 | `{h3d_count, t01_count, run_folders:[≤20]}` |
| `SPDM_IMPORT` | `storage.spdm_roots` | 폴더 | `{h3d_count, t01_count, total_bytes, renamed_count, sample_files:[≤10]}` |

SPDM 경로는 공백을 허용한다(읽기만 하고 argv에 넣지 않음 — 복사 시 이름 정리, §6.11). 그 밖의 1차 §17.3 검사는 동일.

### 12.5 ① 학습데이터

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `GET /studies/{id}/train` | 로그인 | – | `TrainSetup` | |
| `PUT /studies/{id}/train/params` | power | `{version, parameters:[{name, min, max, use, format?, unit?}]}` (모든 행, 이름으로 대응) | `TrainSetup` | 409 `VERSION_CONFLICT`, 409 `TRAIN_PARAMS_REQUIRED`(추출 전), 422 `TRAIN_PARAMS_INVALID` + `problems:[{name, code, message}]` |
| `POST /studies/{id}/train/tpl` | power | `{version}` | `TrainSetup` | 409 `TRAIN_PARAMS_REQUIRED`, `RESOURCE_NOT_CONFIGURED`, `VERSION_CONFLICT`; 422 `TPL_TEMPLATE_INVALID` + problems |
| `GET /train/doe-types` | 로그인 | – | `DoeType[]` | 409 `RESOURCE_NOT_CONFIGURED`, 503 `CONFIG_INVALID`(json 형식 오류) |
| `GET /studies/{id}/train/does` | 로그인 | – | `TrainDoe[]` | |
| `GET /train-does/{id}` | 로그인 | – | `TrainDoe` | |
| `GET /train-does/{id}/runs?state=&limit=&cursor=` | 로그인 | – | `TrainRun[]` | |
| `GET /train-does/{id}/samples?limit=&cursor=` | 로그인 | – | 1차 `/param-sets/{id}/samples` 모양 `{columns, rows:[{run_key, values, measured}], next_cursor}` | 404 `SAMPLES_MISSING` |

```text
TrainParam  = §5.1.1 (+ 서버 계산 valid, problems)
TrainSetup  = {study_id, cad: {source_path, file_name, sha256, display_path}|null, extract_job_id,
               parameters: [TrainParam], used_count,
               tpl: {generated_at, sha256, display_path, params: [{var, name, format}], warnings: [{code, message}], stale: bool}|null,
               version, updated_by_name, updated_at}
DoeType     = {label, value, default_runs, runs_editable, fields: [{key, label, type: "combo"|"int"|"bool", items?, default, min?, max?}]}
TrainDoe    = {id, study_id, job_id, status, doe_label, doe_type, num_runs_requested, options, multi_execution,
               radioss_assem_source_path, run_count, sample_status, collected_count, solve_failed_count, has_run_responses,
               dir_display_path, results_display_path, created_by_name, created_at,
               run_state_counts: {GENERATED, SUBMITTED, SOLVED, SOLVE_FAILED, COLLECTED, COLLECT_FAILED}}
TrainRun    = {run_key, state, starter_name, input_display_path,
               hpc: {external_job_id, state, attempt_no}|null, result: {h3d, t01, files, total_bytes}|null, updated_at}
```

### 12.6 ② 데이터 정리

| 메서드·경로 | 권한 | 응답 |
|---|---|---|
| `GET /studies/{id}/curation-sources` | 로그인 | `[{kind:"TRAIN_DOE"|"SPDM_IMPORT", ref_id, label, display_path, h3d_count, t01_count, runs_expected|null, created_at}]` (READY인 DOE 중 COLLECTED ≥1, READY 가져오기) |
| `GET /studies/{id}/curations?kind=` | 로그인 | `Curation[]` |
| `GET /curations/{id}` | 로그인 | `Curation` |
| `GET /curations/{id}/files?ok=&limit=&cursor=` | 로그인 | `{items:[{run_folder, run_key, input_name, output_name, size, ok, exit_code}], next_cursor}` (file_list.json에서) |
| `GET /studies/{id}/spdm-imports` | 로그인 | `SpdmImport[]` |

```text
Curation   = {id, study_id, job_id, kind, status, source: Source, source_label, preview_job_id, selection,
              target_count, ok_count, failed_count, missing_runs: [run_key], output_display_path,
              used_by_dataset_ids: [id], created_by_name, created_at}
SpdmImport = {id, study_id, job_id, status, spdm_path, file_count, total_bytes, renamed_count, dest_display_path, created_by_name, created_at}
```

미리보기 결과는 작업 산출물(`GET /jobs/{id}/artifacts` → kind `PREVIEW_JSON` 2개: 원문, `preview_summary.json`)로 받는다(B18).

### 12.7 G. 딥링크

- 프런트 경로 `/physicsai/import?spdm_path=<URL 인코딩 절대경로>[&project_id=<id>]`. **링크를 여는 것만으로 작업을 만들지 않는다**(사용자가 Study를 고르고 "가져오기"를 눌러야 함 — CSRF 성격 방지).
- 화면: 경로 표시 + `paths/inspect(SPDM_IMPORT)` 요약 → 프로젝트(쿼리값 기본) → Study 선택 또는 "새 Study" → "가져오기"(power) → 생성된 작업으로 ② 단계 이동, 원천에 그 가져오기를 선택.
- 대시보드 측 요구사항(§18 D8).

### 12.8 ⑤ 최적화

| 메서드·경로 | 권한 | 응답 |
|---|---|---|
| `GET /studies/{id}/optimizations` | 로그인 | `Optimization[]` |
| `GET /optimizations/{id}` | 로그인 | `Optimization` |
| `GET /studies/{id}/optimize/response-candidates?model_id=` | 로그인 | `{source_job_id|null, h3d: {subcases:[{id, label, datatypes:[{name, components:[], layers:[], format}]}]}|null, xydata: {requests:{name:[component]}}|null}` |

```text
Optimization = {id, study_id, job_id, status, approach, opt_method, max_designs, model_id, model_name, param_set_id,
                study_folder, runs_started, responses, summary_status, summary_meta, summary_artifact_id|null,
                file_count, file_list_artifact_id|null, folder_display_path, created_by_name, created_at}
```

### 12.9 작업 생성·대기열 확장

- `POST /studies/{id}/jobs`의 `job_type`에 §6.1 11종 추가, `params` 스키마 §12.10. 오류 코드 추가: 409 `RESOURCE_NOT_CONFIGURED`(+`missing`), `TPL_REQUIRED`, `TPL_STALE`, `DOE_NOT_READY`, `SAMPLES_MISSING`, `CURATION_PREVIEW_REQUIRED`, `SPDM_IMPORT_DISABLED`; 422 `DOE_TYPE_UNKNOWN`, `DOE_OPTIONS_INVALID`, `RESPONSES_INVALID`(+`problems`), `OBJECTIVE_REQUIRED`, `SELECTION_INVALID`.
- `JobSummary` 추가 필드: `stage_label`(예 "①-3"), `current_step_key`, `current_step_label`(한국어), `hpc_summary: {total, queued, running, succeeded, failed, collected}|null`(hpc_job이 있는 작업만).
- `GET /queue`: `waiting_hpc[]`·`collecting[]` 항목에 `hpc_summary`. 우측 패널은 PBS 대기 항목을 "PBS 12/30 완료 · 실패 1"로 표시.
- F: `POST /studies/{id}/param-sets/from-train` (power) `{doe_id, runs?, unit_system?}` → `201 ParamSet`(1차 모양 + `origin`, `train_doe_id`); 409 `DOE_NOT_READY`·`SAMPLES_MISSING`, 422 `PARAM_SET_INVALID`.
- 1차 `ParamSet`·`Dataset`에 각각 `origin`·`train_doe_id`, `curation_id` 필드 추가(없으면 null).

### 12.10 작업 `params` 스키마 요약(알 수 없는 키 422, 1차 §10.6 규칙)

```jsonc
// TD_EXTRACT_PARAMS
{"cad_path": "E:/shared/AI_WORK/cushion/00_inbox/cad/cushion_parametric_modeling.prt"}
// TD_DOE_GEN
{"doe_label": "LatinHyperCube", "num_runs": 30, "options": {"RANDOM_SEED": 1}, "multi_execution": 2,
 "radioss_assem_path": "E:/shared/AI_WORK/cushion/00_inbox/radioss_assem"}
// TD_SOLVE
{"doe_id": "…", "run_keys": null, "hpc": {"queue": null, "ncpus": null, "walltime": null}, "on_run_failure": "collect_partial"}
// TD_RESULT_IMPORT
{"doe_id": "…", "source_path": "E:/shared/AI_WORK/cushion/00_inbox/pbs_results"}
// TD_RESP_EXTRACT
{"doe_id": "…", "responses": [{"name": "MaxStress", "unit": "MPa", "spec": {}}]}
// CU_H3D_PREVIEW / CU_T01_PREVIEW
{"source": {"kind": "TRAIN_DOE", "doe_id": "…"}, "sample_file": null}
// CU_H3D_CURATE
{"source": {"kind": "SPDM_IMPORT", "import_id": "…"}, "preview_job_id": "…",
 "selection": {"items": [{"datatype": "Stress", "component": "vonMises"}], "parts": {"shell": [1], "solid": [], "rbody": []}, "time_increment": 2},
 "exclude_files": []}
// CU_T01_CURVES
{"source": {"kind": "FOLDER", "path": "E:/shared/AI_WORK/cushion/00_inbox/t01"},
 "curves": [{"type": "Rigid Body", "request": "RBODY 1", "component": "F-Mag"}], "exclude_files": []}
// SPDM_IMPORT
{"spdm_path": "\\\\spdm\\master\\PRJ01\\Case_0012\\Scene_03"}
// OPTIMIZE — §6.12
// DATASET_CREATE (1차 + 선택 키)
{"curation_id": "…", "holdout_ratio": 0.1}
```

---

## 13. 폴더 스키마 추가·보안 경로 규칙

### 13.1 Study 폴더(1차 §15.1에 추가)

```text
<study_folder>/
  01_train/
    cad/<CAD 파일>
    params.json                               # ①-2 사람용 사본
    extract/<job_id>/  BATCHRUN_get_parameter_from_cad.py, get_parameter_from_cad_core*.pyd,
                       parameter_extracted.xml, BATCHRUN_get_parameter_from_cad_LogFile.txt
    tpl/TEMAPLATE_simlab_parametered_mesh.tpl, simlab_parametered_mesh.tpl
    radioss_assem/<doe_id>/*.rad, *.inc
    doe/<doe_id>/      # = HyperStudy DIR_WORK
      INPUT_HST_RUN.json, DATA_doe_design_type.json, BATCHRUN_hst_gen_radioss_input.py, hst_gen_radioss_core*.pyd,
      BATCHRUN_create_include_node_elem.tcl, simlab_parametered_mesh.tpl, <CAD 사본>,
      <HyperStudy 산출: approaches/*/run__*/… — 구조 미확인 U17>,
      runs.json, samples.csv, responses.json, run_responses.csv
    results/<doe_id>/<run_key>/*.h3d, *T01, *.out …, responses_run.csv
    results/<doe_id>/collected.json
  02_import/<import_id>/<정리된 상대 구조>, import_manifest.json
  02_preview/<job_id>/PREVIEW_H3D.json | PREVIEW_T01.json, preview_summary.json
  02_curated/<curation_id>/
    work/CURATE_H3D.cfg | INPUT_CURATE_CURVE.json
    CURATED_DATA/<run_folder>/<h3d>           # H3D (원본 CURATED_FOLDER_NAME)
    CURVES/<run_folder>/<base>_curves.json    # T01
    file_list.json
  05_opt/<job_id>/
    INPUT_HST_RUN.json, BATCHRUN_hst_physicsai_optimization.py, hst_physicsai_optimization_core*.pyd,
    H3D_StaticMinMax_to_CSV_FAST.tcl, <STUDY_FOLDER>/…, file_list.json, summary.json
  logs/_paramset_tmp/<uuid>/                  # F 조립 임시(완료 시 04_params로 os.replace)
```

### 13.2 AI 루트 플랫폼 폴더

```text
<ai_root>/_platform/
  env_checks/<check_id>/report.json
  env_check_tmp/                              # 쓰기 시험 전용(tempfile 자동 삭제)
```

`_platform`은 사용자 입력 경로로 지정할 수 없다(1차 §17.3 검사에 `<ai_root>/_platform` 하위 거부 추가 → `PATH_UNSAFE`).

### 13.3 SPDM 경로 검사(G 전용)

- 입력은 절대경로(드라이브·UNC), ≤400자, 제어문자 금지. **공백·한글 허용**, cmd 메타문자는 허용하되 복사 대상 이름에서 정리(§6.11).
- `realpath` 후 `storage.spdm_roots` 중 하나의 하위(설정값·realpath 두 형태 비교, B20), 구성요소 링크·junction 거부, `..` 잔존 금지. 실패 코드 1차와 같음(`PATH_OUTSIDE_ROOT`/`PATH_UNSAFE`/`PATH_NOT_FOUND`).
- SPDM 경로 접근 코드는 `physicsai_core/spdm.py` 한 곳(읽기 함수: `scan`, `open_read`)만. 다른 모듈은 SPDM 경로에 대해 쓰기 함수를 호출할 수 없게 경로 검사기에 `kind="spdm_read"`를 두고, 쓰기 헬퍼(`backup_existing`, `copy_into_study`)는 SPDM 하위 경로를 받으면 예외.

### 13.4 B23 확장(③-1·② FOLDER 입력 거부 목록)

`STUDY_OUTPUT_DIRS` = 1차 목록 + `01_train/extract`, `01_train/doe`, `01_train/tpl`, `01_train/radioss_assem`, `02_preview`, `05_opt`, `logs`. ③-1은 `02_curated/*/CURATED_DATA`·`01_train/results`·`02_import` 하위를 허용한다.

---

## 14. UI(1차 §16 원칙 유지: 하위 단계 카드 1개 = 주 실행 버튼 1개, 필수 입력만, 선택 입력은 "고급" 접힘)

### 14.1 공통

- 스텝퍼 ①②⑤ 활성. 카드의 기능이 `/status.features.<x>.enabled=false`면 버튼 비활성 + 회색 문구 "관리자 설정 필요: <missing 키 1~3개>"(일반 사용자에게 키 이름을 보여도 됨 — 관리자에게 전달용).
- 실패한 작업 상태 옆에 "오류 묶음 받기"(본인·전역 관리자에게만, `can_download_error_bundle`).
- 우측 대기열 패널: 작업마다 단계 배지(①~⑤) + `current_step_label`; PBS 대기는 `hpc_summary` 한 줄. 
- 상단 바 사용자 메뉴에 **전역 관리자에게만** "관리 > 환경 점검". `/status.env_check.fail > 0`이면 메뉴 옆 작은 빨간 점.

### 14.2 ① 학습데이터 생성(`/stage/1`)

| 카드 | 입력 | 버튼 | 결과 표시 |
|---|---|---|---|
| ①-1 CAD 파라미터 추출 | CAD 파일 경로(PathInput + "확인" → `CAD_FILE`) | "파라미터 추출" | 추출 개수, CAD 이름·시각 |
| ①-2 파라미터 표 | 표: **사용**(체크) · 이름 · 공칭(읽기 전용) · 하한 · 상한. 고급: 형식(기본 `%3i`)·단위 열 표시. 행 문제는 행 끝 작은 회색 문구 | "tpl 생성"(PUT 저장 → POST 생성 순서, 저장 실패 시 생성 안 함) | "tpl 생성됨 · 사용 12개 · 시각", 경고 문구(정수 형식 등), `stale`이면 "표가 바뀌었습니다 — tpl을 다시 생성하세요" |
| ①-3 DOE·Radioss 입력 | Radioss 조립 폴더(PathInput + `RADIOSS_ASSEM` 확인: starter 표시), DOE 유형(select), run 수(runs_editable=false면 비활성 "자동 계산(HyperStudy 결정)"), 유형별 옵션(fields로 동적 생성). 고급: 동시 실행 수 | "입력 생성" | run 수, 샘플 표 상태(PARSED/PARTIAL/MISSING 문구), DOE 폴더 경로(복사) |
| ①-4 PBS 해석 | DOE 선택(기본 최신 READY). 고급: queue·ncpus·walltime, 실패 시 동작 | "PBS 제출"(hpc none이면 비활성 + 안내 §6.5) | run 상태 막대(GENERATED/SUBMITTED/SOLVED/실패/COLLECTED 개수), "run 목록" 접힘 표 |
| ①-5 결과 회수 | 자동 회수 상태 문구(collect_mode). 결과 폴더 경로(PathInput + `RESULT_FOLDER` 확인: 매칭 run 수) | "결과 가져오기" | 회수 n/전체, 누락 run 목록(접힘) |
| ①-6 run 응답 추출(선택, 기본 접힘) | 응답 정의 표(이름·단위·spec JSON) | "run 응답 추출" | 추출 run 수 |

①-5 아래 안내 한 줄: "회수한 결과는 ② 데이터 정리의 원천으로, 파라미터·샘플은 ④ '①결과로 만들기'에 쓰입니다."

### 14.3 ② 데이터 정리(`/stage/2`)

상단 **원천 선택**(라디오): ① DOE 결과(목록) / SPDM 가져오기(목록) / 폴더 경로(PathInput + `CURATION_INPUT` 확인). 선택한 원천의 h3d·T01 개수와 기대 run 수 표시.

| 카드 | 입력 | 버튼 | 결과 |
|---|---|---|---|
| ②-0 SPDM 가져오기 | SPDM 경로(PathInput + `SPDM_IMPORT` 확인: 개수·총량·이름 정리 수) | "가져오기" | 가져오기 목록 |
| ②-1 h3d 구조 미리보기 | 고급: 대표 파일 선택 | "h3d 미리보기" | DataType 수, Part 수(shell/solid/rbody), Time Step 수 |
| ②-2 h3d 큐레이션 | ① DataType·Component 추가 표(콤보는 미리보기 `usable`만, Displacement는 "항상 포함" 고정 표시) ② Part 다중 선택 목록 3개(비우면 전체 — BeginParts 빈 블록, 원본 동작) ③ Time step 간격 + "Steps (N개): 1, 3, 5 …" 미리보기(80자 자름, 원본 GUI:338-348) ④ 파일 목록 체크(기본 전부, 누락 run 강조 없이 아래 목록) | "큐레이션 실행" | 성공 n/전체, 실패 파일·누락 run(접힘), 출력 폴더 경로, "③-1 입력으로 사용됨" 문구 |
| ②-3 T01 미리보기 | 고급: 대표 파일 | "T01 미리보기" | Type/Request/Component 트리 |
| ②-4 T01 곡선 추출 | Type → Request → Component 콤보로 곡선 행 추가, 파일 목록 체크 | "곡선 추출" | 출력 파일 수, 첫 곡선 미리보기(`series` 있으면 SVG 선 그래프, 없으면 JSON 트리 + "곡선 형식 미확인") |

### 14.4 ③·④ 변경

- ③-1: 입력 기본값 = 최근 READY H3D 큐레이션("② 큐레이션 결과 사용 · 2026-10-08 · 29개") + "다른 폴더 지정" 전환.
- ④ 파라미터 세트 카드: "폴더 등록"과 나란히 **"① 결과로 만들기"**(DOE 선택 + 대상 run: 회수된 run(기본)/전체) — 카드의 주 버튼은 선택된 방식 하나만 보인다.

### 14.5 ⑤ 최적화(`/stage/5`)

| 카드 | 내용 |
|---|---|
| ⑤-1 입력 | 파라미터 세트(현재) 요약, 모델(기본 Final, 고급: 다른 ACTIVE 모델). Final 없으면 "Final 모델을 먼저 지정하세요" |
| ⑤-2 응답 | 원본 표 열 그대로: Name · Source · Subcase · DataType/Request · Component · Layer · Stat · Goal · Bound · Value (원본 GUI:100-101). 추가 행 입력줄: Source(H3D/XYDATA) → Subcase → DataType → Component/Layer 콤보(후보 API), Stat, Name(기본 제안 = DataType 대문자화 24자, 원본 GUI:640-647) → "추가". Goal≠CONSTRAINT면 Bound·Value 회색 비활성(원본 GUI:657-668) |
| ⑤-3 실행 | Approach(OPT/DOE), Opt Method(OPT일 때만), "Number of Evaluations"(SQP면 "Maximum Iterations"), "Nominal run 먼저 실행"(기본 체크). 고급: Study 폴더 이름, Absolute/Relative(%)/Design Variable Convergence, On Failed Evaluation(활성 규칙 §6.12). 버튼 1개 "최적화 실행"/"DOE 실행" |
| ⑤-4 결과 | 진행 "run 12 / 25 시작"(DOE면 "run 12 시작"), 완료 후 요약 표(PARSED) 또는 "결과 요약 형식 미확인 — 원본 파일 목록을 확인하세요" + 파일 목록(보기 가능 파일은 클릭 시 텍스트/CSV 보기), 폴더 경로 복사 |

### 14.6 환경 점검 화면(`/physicsai/admin/env-check`, 전역 관리자)

- "점검 실행" 버튼 1개(진행 중이면 비활성 + "점검 중…"), 2초 폴링(`GET /admin/env-checks/{id}`), 완료 시 토스트(알림).
- 결과 표: 범주별 묶음 · 항목 · 결과(OK 녹색 점/WARN 노랑/FAIL 빨강/SKIP 회색/PENDING 회전) · 메시지 · 세부(접힘 JSON). 상단 요약 "실패 2 · 경고 1 · 정상 18 · 건너뜀 6", 보고서 파일 경로(복사).
- 아래 이력 20건(시각·요청자·요약), 클릭 시 그 결과.
- 비관리자가 URL로 들어오면 "관리자 전용입니다".

### 14.7 프런트 라우트 추가

`/physicsai/admin/env-check`, `/physicsai/import`(§12.7). 1차 `stage/:n`은 1~5 모두 실제 화면.

---

## 15. 보안(1차 §17에 추가)

1. 외부 실행은 계속 워커만, `shell=False` argv. 새 argv[0]: `{hstpy}`(설정·파생), 환경 점검 자체 시험 `sys.executable`(고정 인자 `-I -c pass`, 사용자 입력 없음). 환경 점검 프로브 argv[0]은 해당 도구 placeholder뿐.
2. pyd·런처: 플랫폼 프로세스는 import·실행하지 않는다. 복사 대상 이름은 설정의 파일명만(경로 구분자 불가), 원본은 `resources.*` 절대경로에서만.
3. XML(①-1)은 크기 상한 + DOCTYPE·ENTITY 거부 후 `xml.etree.ElementTree`로 파싱. JSON(미리보기·DOE 유형)은 크기 ≤ `ui.max_artifact_bytes` 확인 후 파싱, 스키마 검증.
4. SPDM: 읽기 전용 모듈 하나(§13.3), 쓰기 0(V2-SPDM-1~3). 딥링크는 작업을 자동 생성하지 않는다.
5. 오류 묶음: 권한 §10.1, 마스킹 §10.2, 토큰·DB URL·쿠키 값 미포함(V2-EB-2).
6. 환경 점검: 쓰기 시험은 `_platform/env_check_tmp/`에서 `tempfile` 자동 삭제만(명시적 삭제 호출 0 유지). 보고서·DB에 비밀 없음.
7. 배포 스크립트: 비밀번호를 명령 인자·로그·파일에 남기지 않음(프로세스 환경변수만), DB URL은 머신 환경변수(관리자만 읽기). 스크립트 본문에 설치 경로 하드코딩 없음(`deploy.example.json`).
8. 감사 이벤트 추가: `TRAIN_PARAMS_UPDATE`, `TRAIN_TPL_GENERATE`, `PARAM_SET_FROM_TRAIN`, `ENV_CHECK_RUN`, `ERROR_BUNDLE_DOWNLOAD`(작업 생성은 1차대로 `JOB_CREATE`에 포함).
9. 업로드 엔드포인트 0개 유지(CAD·결과·SPDM 모두 경로 지정).

---

## 16. 시험(Altair 없는 Linux) — fake tools 추가

### 16.1 `backend/tests/fake_tools/` 추가·확장(Impl-Backend)

공통: 1차 규약(`FAKE_TOOL_MODE`, `FAKE_TOOL_DELAY_S`, `FAKE_TOOL_RECORD` JSON lines). 도구별 모드 변수 `FAKE_TOOL_MODE_<TOOL>` 우선(1차 fake_hw 방식).

| 파일 | 흉내 | `ok` 동작 | 그 밖의 모드 |
|---|---|---|---|
| `fake_simlab`(확장) | SimLab.bat 추출 | `-auto L CAD XML -nographics`(인자 6개): L·CAD 존재 확인, L과 같은 폴더에 `get_parameter_from_cad_core*.pyd` 존재 확인(없으면 종료코드 4), `<L stem>_LogFile.txt`에 `Passed` 4줄(0.2초 간격), XML `<Root><Model><Parameter><Name>THK_1</Name><Value>3 mm</Value></Parameter><Parameter><Name>RIB_H</Name><Value>12.5</Value></Parameter><Parameter><Name>bad name</Name><Value>x</Value></Parameter></Model></Root>` | `fail`, `hang`(+자식), `no_output`, `bad_xml`(DOCTYPE 포함) |
| `fake_hstbatch`(신규) | hstbatch.exe | `-multiexec N -pyfile L`: cwd의 `INPUT_HST_RUN.json` 읽어 필수 키 확인(없으면 종료코드 5), 런처·pyd 확인, `DOE_NUM_RUNS`개 run에 대해 `approaches/doe_1/run__0000k/m_3/<assem starter 이름>` + `m_1/simlab_parametered_mesh.py`(사용 파라미터마다 `<paramitem Name="X" NewValue="<값>" …/>`, 값은 [min,max] 결정적 분포) 생성, 줄 `Finished run (k), model (m_3)` 출력 | `fail`, `error_log`(종료코드 0 + `ImportError: …`), `no_runs`, `partial_samples`(run 1개는 paramitem 없음), `hang` |
| `fake_hstpy`(신규) | hstpy.bat | `L`: cwd `INPUT_HST_RUN.json` 필수 키 **전부**(§6.12 표) 확인, env `ALTAIR_HOME`·`EDS_TNS_ACTVN_CHCKPT=1` 확인(없으면 종료코드 3), `STUDY_FOLDER/` 아래 `opt_summary.csv`(헤더+3행)·`run_log.txt` 생성, `Started run (k), model (m_1)`을 `MAX_DESIGNS`까지 출력 | `fail`, `hang`, `error_lines`(종료코드 0 + `Error:` 줄 — 실패 아님 확인용) |
| `fake_hw`(확장) | hw.exe | 1차 동작 유지 + `-h3d H -result J` → J에 `{"datatype_info":{"Stress":["vonMises","P1 (major)","Max Abs Principal"],"Displacement":["X","Y","Z","Mag"]},"lst_cid_shell":[1,2],"lst_cid_solid":[3],"lst_cid_rbody":[],"num_time_step":5}`; `-b -c -tcl X -input T -output J` → `{"dataTypes":[{"name":"Rigid Body","requests":[{"name":"RBODY 1","components":["F-Mag"]}]}]}`; `-b -c -tcl X -config C` → C의 jobs마다 outputFile에 `{"series":[{"name":"F-Mag","x":[0,1],"y":[0,2]}]}` | `fail`, `skip_one`(curve export에서 첫 job 출력 안 만듦), `no_output` |
| `fake_hvtrans`(신규) | hvtrans.exe | `-c CFG IN IN -o OUT -z0`: CFG 존재·`BeginParts` 포함 확인, OUT에 IN 앞 1 KiB + 표식 쓰기 | `fail`, `fail_match`(`FAKE_FAIL_MATCH` 문자열이 IN에 있으면 종료코드 1) |
| `fake_pyd` 픽스처 | pyd | 시험이 `pyd_dir`에 `<core>.cp313-win_amd64.pyd`(임의 바이트) 생성. "0개·2개" 경우도 픽스처로 | |
| `fake_qsub`/`fake_qstat`/`fake_qdel`(확장) | PBS | 제출마다 다른 id(`12345.pbs01`, `12346.pbs01`…), 상태 파일을 id별로 | `exit1_one`(특정 run_key가 job_name에 있으면 Exit_status 1) |
| SPDM 픽스처 | SPDM 트리 | `tmp/spdm/PRJ/Case 01/Scene&1/a.h3d`, `b_T01`, `c.txt`, 링크 1개 | 시험 전후 트리 스냅샷(이름·크기·mtime·권한) 비교 + `builtins.open`·`os.*` 쓰기 계열 감시 |

### 16.2 시험 환경 규칙

- 1차 §18.2 그대로(PG 필수, skip ≠ 통과). 2차 Windows 전용 시험(`worker.job_object` 자체 시험, 배포 ps1 실행)은 `@pytest.mark.windows` → Linux에서 "미수행".
- 배포: `pwsh`가 있으면 구문 검사, 없으면 미수행 기록.

---

## 17. 리스크·미확정(1차 U1~U16에 이어)

| # | 항목 | 영향 | 2차 처리 | 해소 방법 |
|---|---|---|---|---|
| U17 | `hst_gen_radioss_core` 산출 구조(run 폴더 위치·이름 `approaches/*/run__*`, starter·include가 run 폴더 안에 모두 있는지), CAD 상대경로(`./<cad>`) 해석 위치 | ①-3·①-4 | `train_data.run_dir_glob`, DIR_WORK에 CAD 사본 | E2-1-4 |
| U18 | DOE 샘플 값 위치·형식 — 렌더링된 tpl의 `paramitem NewValue` 파싱 가능 여부 | F, ④ 최근접 run | 플러그형 추출기(paramitem 기본/csv/none) | E2-1-5 |
| U19 | 업로드본에 없는 원본 파일(tpl 템플릿, include TCL, preview_h3d/hg TCL, MinMax TCL, BUILD_PYD) | ①②⑤ 실행 | `resources.*` 설정, 비면 기능 비활성 | 원본 배포본 반입 후 설정 |
| U20 | SimLab 추출 진행 표식(`Passed` 4개)·XML 형식(`Model/Parameter/Name·Value`) | ①-1 진행률·파싱 | 원본 규칙 이식, 표식은 설정 | E2-1-1 |
| U21 | `hstbatch -multiexec N`과 Job Object 한도(CPU hard cap·메모리), HyperStudy가 띄우는 SimLab·HyperMesh의 BREAKAWAY 여부 | ①-3 실패·성능 | 기본 N=1, 상한 설정 | E2-1-4, U11 |
| U22 | `runs_editable=false` DOE 유형(FullFact/FracFact)의 실제 run 수 | ①-3 진행률 | 진행률 NULL + run 번호 라벨 | E2-1-4 |
| U23 | `%3i` 정수 형식: 연속 DOE 값의 정수 반영(실수 파라미터라면 형식 변경 필요) | 학습 데이터 품질 | 행별 format + 경고, 샘플은 반영값 | E2-1-3 |
| U24 | PBS 다중 run 제출 방식(run마다 qsub vs 배열 job), 결과 폴더 구조·`collect_patterns` | ①-4 | run마다 제출, 설정 템플릿 | E6-1(1차) + E2-1-6 |
| U25 | 수동 해석 결과 폴더의 run 매칭 규칙(폴더 이름 = run_key) | ①-5 | `result_run_dir_regex` 설정 | E2-1-7 |
| U26 | hvtrans cfg 문법·지원 component·`-z0` 의미 | ②-2 | 원본 규칙 그대로 이식 | E2-2-2 |
| U27 | `BATCHRUN_curate_hg.tcl` 출력(`*_curves.json`) 형식(TCL bytecode) | ②-4 그래프 | best effort(`series`), 아니면 JSON 트리 | E2-2-4 |
| U28 | ⑤ 결과 요약 파일 형식 | ⑤ 결과 표 | 플러그형 파서 + 파일 목록 | E2-5-3 |
| U29 | ⑤ 진행 총수: OPT는 MAX_DESIGNS 상한으로 근사, DOE는 미상. 진행 정규식의 `m_1` 고정 | ⑤ 진행률 | 상한 99%, DOE indeterminate | E2-5-2 |
| U30 | SPDM Case/Scene 폴더 구조, 파일 이름의 공백·한글·메타문자 비율 | G | 이름 정리 + manifest | E2-6-1 |
| U31 | 작업 스케줄러 백그라운드(세션 0)에서 HyperWorks·SimLab·hstbatch 배치 동작, 서비스 계정 라이선스 접근 | H 운영 | `-RunMode Interactive` 선택지 | E2-0-3 |
| U32 | 각 Altair 도구의 버전/도움말 인자 | A 프로브 | 기본 존재 확인만 | 사내 확인 후 `env_check.probes` |
| U33 | 오류 묶음 권한 범위(본인+관리자) | B | 가정 A-13 | 사용자 확인 |
| U34 | 대시보드 Case/Scene 화면의 SPDM 절대경로 보유 여부·링크 위치 | G 딥링크 | D8 요구사항으로만 기록 | 대시보드 측 |
| U35 | run별 응답 추출 방법(U8 연장) | ①-6, F `resp:` 열 | 템플릿 null → 비활성 | TCL 확보 후 |
| U36 | 작업 지시의 회수 모드 "드라이브"의 정확한 뜻 | ①-5 | `drive` = `shared_folder` 별칭 + 수동 폴더 지정(`TD_RESULT_IMPORT`) | 사용자 확인 |
| U37 | ①-2 "사용 안 함" 파라미터를 tpl에서 빼면 CAD 공칭값이 유지되는지 | ①-3 형상 | 두 블록에서 제외 | E2-1-3 |

---

## 18. 대시보드 측 요구사항 추가(1차 §20에 이어)

| # | 구분 | 내용 |
|---|---|---|
| D8 | 선택(편의) | Case/Scene 화면에 "AI 학습 데이터로 보내기" 링크: `window.open('/physicsai/import?spdm_path=' + encodeURIComponent(<SPDM 절대경로>) + '&project_id=' + <프로젝트 id>)`. 경로는 PhysicsAI 서버에서 접근 가능한 SPDM 경로(드라이브 문자 또는 UNC)여야 하며 PhysicsAI `storage.spdm_roots` 하위여야 한다. 대시보드는 SPDM 경로를 PhysicsAI에 보내기만 하고 파일을 옮기지 않는다 |
| D9 | 운영 | D1 Caddy 스니펫은 `deploy/caddy/physicsai.caddy`를 기준으로 반영(`redir /physicsai /physicsai/ 308` 포함) |

---

## 19. 구현 분해와 파일 소유권

AGENTS.md 역할표에 `deploy/**`를 Impl-Backend 소유로 추가한다(이번 Plan 변경). 순서: Backend가 migration·스키마·`openapi.json`을 먼저 커밋 → Frontend 타입 생성 → 화면. API 모양이 이 문서와 달라야 하면 phase2.md 끝 "변경 메모"에 B2-n으로 남기고 Plan 확인 요청(1차 B 메모 방식).

### 19.1 Impl-Backend

| 경로 | 내용 |
|---|---|
| `migrations/versions/0002_phase2.py` | §5 DDL, downgrade RuntimeError |
| `backend/physicsai_core/db/tables.py`, `db/__init__.py`(`MIGRATION_HEAD`) | 새 테이블·컬럼·CHECK |
| `backend/physicsai_core/db/repositories/{train,curations,spdm_imports,optimizations,env_checks}.py` | CRUD·상태 CAS |
| `backend/physicsai_core/config.py` | §8.2 키·검증, 2차 템플릿 null 허용 규칙, `hstpy`·`altair_home` 파생 |
| `backend/physicsai_core/commands.py` | §8.1 템플릿 사양·`{hstpy}`, Windows argv[0] normpath, 키별 경로 표기 |
| `backend/physicsai_core/job_types.py` | §6.1 11종 |
| `backend/physicsai_core/state_machine.py` | T10b |
| `backend/physicsai_core/train_tpl.py` | §6.3 tpl 재구현·검증 |
| `backend/physicsai_core/train_params.py` | XML 파싱, 기본 범위, 표 검증 |
| `backend/physicsai_core/doe_types.py` | DATA_doe_design_type.json 검증·options 검증 |
| `backend/physicsai_core/doe_samples.py` | 추출기 paramitem/csv/none |
| `backend/physicsai_core/curation.py` | run 폴더 이름, `to_cfg_datacomp`, hvtrans cfg 생성, INPUT_CURATE_CURVE.json |
| `backend/physicsai_core/optimize.py` | RESPONSES 검증, RUN_CONFIG 작성, 요약 파서 |
| `backend/physicsai_core/spdm.py` | SPDM 경로 검사·읽기 전용 스캔 |
| `backend/physicsai_core/paths.py` | `_platform`·B23 확장·SPDM 쓰기 차단 |
| `backend/physicsai_core/error_bundle.py` | 묶음 항목 생성·마스킹(스트리밍은 B16 헬퍼 재사용) |
| `backend/physicsai_core/hpc/` | 다중 run 제출 헬퍼, collect_mode shared_folder/drive 검증 |
| `backend/physicsai_core/notifications.py` | 새 이벤트·제목 |
| `backend/physicsai_api/routers/{train.py, curations.py, optimize.py, env_checks.py, spdm.py}` + 기존 `jobs.py`(error-bundle), `param_sets.py`(from-train), `studies.py`(inspect purpose), `status.py`, `queue.py` | §12 |
| `backend/physicsai_api/schemas/`, `services/` | §12 모델·use case |
| `backend/openapi.json` | 재생성 |
| `worker/physicsai_worker/steps/{train.py, curation.py, spdm_import.py, optimize.py}`, `steps/launcher.py`(§4.2), `executor.py`(팬아웃 §4.3), `runtime.py`(T10b, 다중 run 회수, env check claim), `env_check.py`(§9.3), `steps/verify.py`(COLLECT 모드 일반화) | |
| `backend/tests/fake_tools/` | §16.1 |
| `backend/tests/`, `worker/tests/` | V2-* 시험 |
| `config/platform.example.yaml` | §8.2 |
| `deploy/**`, `scripts/test-all*` | §11, 배포 정적 시험 포함 |

### 19.2 Impl-Frontend

| 경로 | 내용 |
|---|---|
| `frontend/src/api/` | 타입 재생성, 엔드포인트(§12) |
| `frontend/src/shell/StageStepper.tsx` | ①②⑤ 활성 |
| `frontend/src/shell/TopBar.tsx`, `panels/QueuePanel.tsx` | 관리 메뉴·점, 단계 배지·hpc_summary |
| `frontend/src/stages/stage1/` | `CadExtractCard`, `ParamTableCard`, `DoeGenCard`(동적 옵션), `SolveCard`, `ResultCollectCard`, `RunResponseCard`, `RunStateBar`, `RunTable` |
| `frontend/src/stages/stage2/` | `SourcePicker`, `SpdmImportCard`, `H3dPreviewCard`, `H3dCurateCard`(DataType/Component 표·Part 목록·time step), `T01PreviewCard`, `T01CurvesCard`, `CurationFileList` |
| `frontend/src/stages/stage3/` | ③-1 입력 기본값(큐레이션) |
| `frontend/src/stages/stage4/` | "① 결과로 만들기" |
| `frontend/src/stages/stage5/` | `OptInputCard`, `ResponseTable`, `ResponseAddRow`, `OptRunCard`, `OptResult`(요약표·파일 목록·텍스트/CSV 보기) |
| `frontend/src/pages/AdminEnvCheck.tsx`, `pages/ImportLanding.tsx` | §14.6, §12.7 |
| `frontend/src/components/` | `FeatureGate`(설정 필요 문구), `ErrorBundleButton`, `JsonTree`, `CsvView` |
| `frontend/src/mock/` | 2차 목 데이터·서버 |
| `frontend/src/__tests__/` | V2-FE-* |

---

## 20. Verifier 체크리스트(V2-*)

1차 §22 규칙(자동 시험 이름 또는 수동 증적, windows skip = 미수행)과 1차 V-* 회귀 전체(V-REG-1)를 함께 본다.

| ID | 기준 | 방법 |
|---|---|---|
| V2-DB-1 | 빈 PG에 `upgrade head`(0001→0002) 성공, `MIGRATION_HEAD` = 스크립트 head, downgrade RuntimeError | PG |
| V2-DB-2 | 새 CHECK·unique: artifacts kind, notifications event, `param_sets.origin`, `env_checks` 동시 1건, `train_runs(doe_id, run_key)` | PG |
| V2-DB-3 | 새 JSONB 컬럼 스키마가 §5와 일치, 샘플 값·로그 본문 컬럼 없음(1차 V-DB-4 확장) | 단위 |
| V2-CFG-1 | §8.2 검증 실패 사례(정규식 그룹, launchers 이름, collect 루트 누락·겹침, probes argv[0]) + 2차 템플릿 null 허용·1차 확정 템플릿 null 금지 유지 | 단위 |
| V2-CFG-2 | `hstpy_path`·`altair_home` 파생 규칙(빈 값/지정 값) | 단위 |
| V2-CMD-1 | §8.1 기본 템플릿 펼침이 원본 인용 argv와 정확히 일치(골든: fake 기록), 키별 경로 표기(`/` vs OS) | 가짜 도구 |
| V2-CMD-2 | Windows argv[0] normpath(단위: `os.name` 모의), `.bat` 템플릿에 B24 적용(SimLab·hstpy) | 단위 |
| V2-CMD-3 | 팬아웃 LOCAL: 대상별 실행·로그 머리줄·commands.jsonl·일부 실패 → SUCCEEDED+`PARTIAL_OUTPUT`·전부 실패 → FAILED·취소 시 다음 대상 미실행 | 가짜 도구 |
| V2-LCH-1 | 런처 준비: compiled 판정, pyd 0개·2개 → `RESOURCE_MISSING`, 복사·sha256 기록, 플랫폼 코드에 pyd import·런처 실행 없음(정적) | 단위·정적 |
| V2-TD-1 | ①-1: 추출 체인, 진행률(`Passed` 개수), XML 파싱(mm 제거·비숫자 nominal·이름 정규식 불일치 → valid=false), DOCTYPE 거부, 기존 표 백업 | 가짜 도구 |
| V2-TD-2 | ①-2: 저장 검증(min<max, 범위, format, 사용 ≥1), 정수 형식 경고, VERSION_CONFLICT | API |
| V2-TD-3 | ①-2 tpl 재구현 골든: 원본 `update_parameter_file`과 같은 입력에서 같은 출력(사용 행만 다르게 한 경우 포함 — 원본 함수 사본을 시험 데이터로 둔 비교), marker·anchor 없음 422, 생성 tpl이 1차 §15.4 검증 통과, 표 변경 후 `TPL_STALE` | 단위·API |
| V2-TD-4 | ①-3: DOE 유형 json 검증·options 검증·runs_editable 규칙, INPUT_HST_RUN.json 키 집합 = 원본 GUI:410-424(정확히), assem 사본·자원 복사, 진행률 정규식, 오류 정규식 → `LOG_ERROR_DETECTED`, run 스캔(starter 0·2개 run 제외 경고), samples paramitem/PARTIAL/csv/none | 가짜 도구 |
| V2-TD-5 | ①-4: run별 hpc_job 제출, 제출 중 실패 시 이미 제출분 cancel + `HPC_SUBMIT_FAILED`, 폴러 다중 run, T10b(일부 실패 → 회수 + 알림 `HPC_PARTIAL_FAILED`), 전부 실패 T13, `on_run_failure=fail`, 재시도 대상 run 계산 | 가짜 도구(PBS) |
| V2-TD-6 | 회수 모드: in_place 안정 확인, shared_folder·drive 복사(원본 미삭제), 루트 겹침 설정 오류 | 가짜 도구 |
| V2-TD-7 | ①-5 `TD_RESULT_IMPORT`: run 매칭·중복 폴더·매칭 0 오류·패턴 복사·누락 run 목록, gateway none에서 ①-4 버튼 409 `HPC_NOT_CONFIGURED`·①-5 동작 | 가짜 도구·API |
| V2-TD-8 | ①-6: 템플릿 null 409, 설정 시 팬아웃·run_responses.csv | 가짜 도구 |
| V2-F-1 | F: 파라미터 세트 생성(정의·샘플·resp 열·cad·tpl·assem), 1차 검증기 통과, `origin`·`train_doe_id`, SAMPLES_MISSING·DOE_NOT_READY, 임시 폴더는 이동(삭제 호출 0), 1차 폴더 등록 경로 회귀 | API |
| V2-CU-1 | ②-1/②-3: 미리보기 체인, JSON 키 검증, `to_cfg_datacomp` 규칙(1·2·3단어·Extreme) | 단위·가짜 도구 |
| V2-CU-2 | ②-2: hvtrans cfg 골든(원본 `__create_hvtrans_config` 사본과 같은 입력 → 같은 텍스트: Parts 블록 유무, time step 간격, Displacement 자동 추가, ExtendedInfo all 플래그), run 폴더 이름 규칙 골든, 팬아웃 일부 실패, 누락 run, 출력 폴더 백업 | 단위·가짜 도구 |
| V2-CU-3 | ②-4: INPUT_CURATE_CURVE.json 형식 골든, 한 번 호출, 출력 누락 표시, CURVE_JSON 등록 | 가짜 도구 |
| V2-CU-4 | ③-1 `curation_id` 입력(둘 다 주면 422), B23 확장 목록 거부·허용 | API |
| V2-SPDM-1 | SPDM 경로 검사: 루트 밖·링크·`..` 거부, 공백 허용, spdm_roots 비면 409 | API |
| V2-SPDM-2 | 가져오기 후 SPDM 트리 스냅샷 불변(이름·크기·mtime·권한), 쓰기 계열 호출 0(감시), 하드링크 아님(`st_ino`·`st_nlink`), 이름 정리·manifest | 가짜 트리 |
| V2-SPDM-3 | 정적: SPDM 경로를 다루는 모듈이 `spdm.py` 하나, 쓰기 헬퍼가 SPDM 경로에서 예외 | 정적·단위 |
| V2-OP-1 | ⑤ RESPONSES 검증 전 사례(이름·중복·`|`·CONSTRAINT·OPT 목적 필수·비제약 행 BOUND/VALUE 제거) | 단위 |
| V2-OP-2 | INPUT_HST_RUN.json 키 집합 = §6.12 표(원본 GUI:859-889 + HYPERVIEW_TCL 복사본), env `ALTAIR_HOME`·`EDS_TNS_ACTVN_CHCKPT=1`, `@cmd_c`, Final 기본·sha256 확인, 기존 Study 폴더 백업 | 가짜 도구 |
| V2-OP-3 | 진행률: OPT `run/max_designs`(상한 99), DOE NULL+라벨, 오류 줄이 있어도 종료코드 0이면 성공 | 가짜 도구 |
| V2-OP-4 | 결과: 파일 목록·OPT_FILE 등록 상한·요약 파서 PARSED/UNRECOGNIZED, 응답 후보 API(PREDICT 미리보기 있음/없음) | 가짜 도구·API |
| V2-EC-1 | 환경 점검 권한(전역 관리자만), 동시 1건 409, API 항목(config·DB·head 불일치·대시보드 200/401/타임아웃·hpc·heartbeat) | API(가짜 대시보드) |
| V2-EC-2 | 워커 항목: 실행 파일 존재/없음/빈 값, 프로브 null SKIP·설정 시 실행·시간 초과 트리 종료, 자원 파일·pyd 개수, 쓰기 시험(tempfile, 남는 파일 0), 여유 공간, GPU(fake_nvidia_smi ok/fail), limiter, job_object 비Windows SKIP | 가짜 도구 |
| V2-EC-3 | 상태: PENDING→RUNNING→DONE, 만료 EXPIRED(워커 미기동), 만료 후 워커 쓰기 거부, `ENV_CHECK_DONE` 알림 | PG |
| V2-EC-4 | Windows Job Object 자체 시험(IsProcessInJob·한도 값) | windows |
| V2-EB-1 | 오류 묶음 권한(본인 OK, 타인 403, 관리자 OK, 비실패 409), zip 항목 목록·꼬리 상한·TRUNCATED, 스트리밍(메모리 적재 없음 — 큰 로그로 확인) | API |
| V2-EB-2 | 마스킹: DB URL·Bearer·쿠키·비밀 환경변수 값이 zip 어디에도 없음(검색), lease_token 없음 | API |
| V2-HPC-1 | 1차 V-HPC 회귀 + 다중 run 상태 매핑, `hpc_summary` 집계 | 가짜 도구 |
| V2-NT-1 | 2차 작업 유형 알림 제목·`HPC_PARTIAL_FAILED`·`ENV_CHECK_DONE`·`HPC_COLLECTED` 본문(n/m) | PG |
| V2-API-1 | §12 오류 코드·HTTP 상태, 새 스키마가 openapi.json에 있고 프런트 생성 타입 컴파일 | API·CI |
| V2-API-2 | `/status.features` 판정(키 비우면 enabled=false + missing) | API |
| V2-SEC-1 | 1차 V-SEC 전부 회귀(업로드 0, pickle 0, API subprocess 0, 삭제 호출 허용 목록 0개 유지) | 정적 |
| V2-SEC-2 | pyd·런처를 플랫폼이 import·exec하지 않음, XML DOCTYPE 거부, `_platform` 경로 사용자 입력 거부 | 정적·단위 |
| V2-SEC-3 | 새 코드·`deploy/` 스크립트에 `Program Files`·Altair 경로 하드코딩 없음(예시 설정 제외), 평문 비밀번호 인자 없음 | 정적 |
| V2-DEP-1 | `deploy/` 파일 존재, `deploy.example.json` 스키마, 스크립트가 참조하는 키 = 예시 키, `collect-offline.sh --dry-run` 출력, 작업 등록에 `ExecutionTimeLimit` 0 지정 문자열 존재 | 정적 |
| V2-DEP-2 | PowerShell 구문 검사(`pwsh` 있을 때), 실제 Windows 설치·업데이트·서비스 동작 | `pwsh`/windows → 없으면 미수행 + 사용자 E2E |
| V2-FE-1 | 스텝퍼 ①②⑤ 활성, FeatureGate 문구·버튼 비활성 | 컴포넌트 |
| V2-FE-2 | ①: 카드 6개, 파라미터 표 편집·사용 체크·tpl 생성 순서(PUT 실패 시 POST 없음)·stale 문구, DOE 동적 옵션(combo/int/bool)·runs_editable, PBS none 안내, run 상태 막대 | 컴포넌트 |
| V2-FE-3 | ②: 원천 선택, Displacement 고정 표시, usable만 콤보, time step 미리보기(80자), 파일 체크·누락 run, 곡선 그래프/JSON 트리 분기 | 컴포넌트 |
| V2-FE-4 | ⑤: 응답 표 열·Goal별 Bound/Value 비활성, 메서드 기본값 적용, 라벨 SQP 전환, 활성 규칙, 진행 문구 OPT/DOE, 요약 없음 문구 | 컴포넌트 |
| V2-FE-5 | 환경 점검 화면(관리자만, 폴링, 결과 표·이력), 비관리자 차단, 관리 메뉴 점 | 컴포넌트 |
| V2-FE-6 | 오류 묶음 버튼 표시 조건, 딥링크 화면(자동 실행 없음·프로젝트 기본값), ③-1 큐레이션 기본 입력, ④ "① 결과로 만들기", 대기열 단계 배지·hpc_summary | 컴포넌트 |
| V2-REG-1 | `scripts/test-all` 전체 통과(1차 + 2차, Linux, PG) | CI |
| V2-E2E-1 | 사용자 E2E 2차 항목 결과 기록(미수행은 "미수행") | 사용자 증적 |

---

## 21. 가정 목록(사용자 부재 중 결정 — 확인 요청)

| # | 가정 | 근거 |
|---|---|---|
| A-1 | 원본 ⑤의 Predict+Preview는 ④가 대신, ⑤는 DOE/최적화만 | 1차 ④가 같은 체인을 이미 구현 |
| A-2 | 팬아웃 LOCAL은 순차 실행(원본 MULTI_EXECUTION 스레드 병렬 미사용) | 슬롯 1개·Job Object 단위 자원 제한 |
| A-3 | SIMLAB_EXTRACT 성공 = 종료코드 0 + XML 존재(원본은 종료코드 미판정) | 실패를 조용히 넘기지 않기 |
| A-4 | tpl anchor `<Parameters Value="">` 없으면 오류(원본은 무시) | 형상 변수 누락 방지 |
| A-5 | 사용 안 함 파라미터는 tpl 두 블록에서 제외 | 원본에 사용 여부 열 없음, 최소 변경(U37) |
| A-6 | ①-3은 Radioss 조립 폴더를 Study로 복사한 사본을 HyperStudy에 넘김 | SPDM·원본 폴더 보호, 재현성 |
| A-7 | 회수 모드 `drive` = `shared_folder` 별칭 + 수동 결과 폴더 지정 작업 별도 | 작업 지시 문구 해석(U36) |
| A-8 | ⑤ HST_OPTIMIZE는 오류 정규식 미적용(종료코드만) | 원본 동작, 실패 평가 무시 설정과 충돌 |
| A-9 | 업로드본 `INPUT_HST_RUN.json`의 `MAX_STRAIN`·`MAX_FORCE`는 구버전 키로 미사용 | 원본 GUI가 만들지 않음 |
| A-10 | ⑤ 응답 후보가 없으면 H3D·XYDATA 모두 직접 입력 허용 | ④ 예측 없이도 ⑤ 사용 가능 |
| A-11 | 2차 템플릿·자원은 null/빈 값 허용(그 기능만 비활성) | 1차만 운영하는 설치를 깨지 않기 |
| A-12 | 환경 점검은 작업 대기열이 아닌 전용 테이블 + 워커 light 스레드 | Study 비소속·짧은 점검 |
| A-13 | 오류 묶음은 작업 등록자 본인과 전역 관리자만 | 명령 스냅샷·설정 요약 포함(U33) |
| A-14 | Windows 서비스 등록은 작업 스케줄러(Register-ScheduledTask) | NSSM·pywin32 미사용, 의존성 0 |

---

## 변경 메모(C1~) — Impl-Backend 구현 중 계약과 다르게/구체화한 곳(Plan 확인 요청)

| # | 위치 | 내용 |
|---|---|---|
| C1 | §5, B14 | `0001_initial`이 `tables.py`를 쓰면 2차 테이블까지 0001에서 생겨 0002가 실패 → 1차 스키마 동결본 `physicsai_core/db/schema_0001.py`를 만들어 0001이 그것을 쓴다(DDL 동일). `tables.py` = 현재 스키마, 시험이 migration 결과와 `compare_metadata`로 일치 확인 |
| C2 | §6.8, §12.9 `Dataset.curation_id` | `datasets`에 컬럼을 추가하지 않고 `DATASET_CREATE` 작업 `params.curation_id`에서 계산(§5.8에 datasets 변경이 없어서). `curation_id`를 주면 저장 params의 `input_path` = `02_curated/<id>/CURATED_DATA` 절대경로(B8 확정 기록), 둘 다/둘 다 없음 422 `INVALID_PARAMS` |
| C3 | §6.13 F | 조립 폴더 `radioss_assem/`에서 `eps_mesh`로 시작하고 `predict.starter_glob`에 맞는 파일(SimLab 메시 starter)은 빼고 복사 — 1차 검증기의 "starter 정확히 1개"와 충돌(원본 ⑤도 `eps_mesh*` 제외, GUI:427-445) |
| C4 | §7.1 T10b | T10과 (from,to) 쌍이 같아 전이 표 키로 구분 불가 → `state_machine.CONDITIONAL_TRANSITIONS["T10b"]` + `hpc_terminal_transition()`(T10/T10b/T13 판정)으로 두고 `check_transition`은 `T10`을 돌려준다. T10b 시 `result.submitted/failed` 기록(알림 본문 n/m용) |
| C5 | §12.10 저장 params(B8 방식) | 서버가 확정 기록하는 키 추가: `TD_DOE_GEN` → `doe_id`·`doe_type`(value)·`default_runs`(runs_editable=false일 때 `DOE_NUM_RUNS`), `CU_H3D_CURATE`·`CU_T01_CURVES` → `curation_id`, `SPDM_IMPORT` → `import_id`(정규화 경로), `OPTIMIZE` → `optimization_id`·`study_folder`(기본값)·`opt_settings`. 엔터티 행은 작업 생성 트랜잭션에서 `BUILDING`(train_does·curations·spdm_imports), `optimizations` 행은 OP_PREP에서 `RUNNING`으로 만든다 |
| C6 | §6.1.1 오류 코드 | DOE가 없거나 READY가 아니면(TD_SOLVE·TD_RESULT_IMPORT·TD_RESP_EXTRACT·② TRAIN_DOE 원천) 409 `DOE_NOT_READY`. runs_editable=false 유형에 `num_runs`를 주면 422 `DOE_OPTIONS_INVALID`. 원천 파일 0개 409 `PREREQUISITE_MISSING`(`missing:["SOURCE_FILES"]`), Radioss starter 개수 오류 409 `PREREQUISITE_MISSING`(`["RADIOSS_STARTER"]`), 재제출 대상 0개 `["SUBMITTABLE_RUN"]`, ①-6 회수 run 0개 `["COLLECTED_RUN"]`. 미리보기 JSON 형식 오류는 step 실패 `OUTPUT_MISSING`(메시지에 형식 오류) |
| C7 | §11.2 update.ps1 ① | `GET /physicsai/api/queue`는 로그인이 필요 → 대시보드 세션 토큰을 `Read-Host -AsSecureString`으로 받아 Bearer로 호출, 토큰이 없으면 머신 환경변수 DB URL을 `PG*` 프로세스 환경으로만 넘겨 `psql`로 `jobs` 비종료 건수 + 진행 중 `env_checks`(PENDING·RUNNING) 건수 확인(비밀번호는 명령 인자에 없음). 관리자 토큰이면 `GET /admin/env-checks/latest`도 확인. install.ps1의 `CREATE ROLE`은 같은 psql 세션에서 `SET log_statement='none'`·`log_min_error_statement='panic'`·`log_min_duration_statement=-1` 뒤 실행(비밀번호가 서버 로그에 남지 않게, superuser 세션 SET) |
| C8 | §6.11 SI_SCAN | 대상 목록은 DB가 아닌 `logs/<job_id>/spdm_plan.json`(작업 로그 폴더)에 둔다(최대 2만 개 경로라 job.result에 넣지 않음). 복사 대상 상대경로는 지정한 SPDM 경로 **아래** 기준(지정 폴더 이름 자체는 포함 안 함) |
| C9 | §8.2 `resources.launchers` | 기본값을 원본 이름 3개로 둔다(예시 YAML과 같음). 알 수 없는 런처 키는 설정 오류 |
| C10 | §12.1 `/status.env_check` | 전역 관리자가 아니면 `null`, 관리자인데 점검 이력이 없으면 값이 모두 null인 객체 |
| C11 | §12.9 `hpc_summary` | `queued` = SUBMITTING·QUEUED·UNKNOWN, `running` = RUNNING·CANCEL_REQUESTED, `failed` = FAILED·LOST, `collected` = collect_state COLLECTED(①-4 COLLECT가 기록) |
| C12 | §10.2 마스킹 | 고정 규칙에 더해 `database.url_env`·`*PASSWORD*`·`*SECRET*`·`*TOKEN*`·`PG*` 환경변수의 **값 문자열 자체**(4자 이상)도 `***`로 치환(로그에 URL 전체가 찍힌 경우 대비)와 그 **JSON 이스케이프 형태**도 치환. DB URL 규칙은 계약 그대로 `postgres(ql)?(\+\w+)?://[^@\s]+@`. 환경 점검 프로브 출력 꼬리에도 같은 마스킹 적용(출력 수집은 꼬리 64K자 상한, 마스킹 후 4KiB로 자름) |
| C13 | §6.6 RI_SCAN·§12.4 RESULT_FOLDER | `result_run_dir_regex`의 `run_key` 그룹을 DOE run_key와 **대소문자 무시**로 대응(`RUN__00002` → `run__00002`). 대소문자 무시는 `run_key` 그룹에만 — 그룹 밖 접두·접미부는 정확히 일치해야 함. 같은 run에 폴더가 여러 개(대소문자만 다른 경우 포함)면 그 run은 제외 + 경고 `RUN_FOLDER_DUPLICATE`(폴더 목록), 모든 매칭이 중복이면 `INPUT_INVALID`(중복 run 목록) |
| C14 | §6.7·§6.12 산출물 형식(프런트 가정과 대조) | `02_preview/<job>/preview_summary.json`(H3D) = `{datatypes:[{name, components, usable}], parts:{shell,solid,rbody}, num_time_step, sample_file, source_file_count, files:[{rel, run_folder, size}]}`(`files`는 원천 루트 기준). T01 미리보기는 원문 `PREVIEW_T01.json` 1개만(요약 파일 없음). FILE_LIST는 종류마다 다름: ⑤ `file_list.json` = `{root, files:[{rel, size}], truncated}`(프런트 가정과 같음), ② `file_list.json` = 배열 `[{run_folder, run_key, input_rel, output_rel, size, ok, exit_code}]`(화면은 `GET /curations/{id}/files` 사용 권장), G `import_manifest.json` = `{spdm_path, imported_at, files:[{source_rel, dest_rel, size, renamed}]}`. ⑤ `summary.json` = csv_table이면 `{parser, kind, file_rel, columns, rows}`(rows는 문자열 배열의 배열), json_passthrough면 `{parser, kind, file_rel, data}`. run별 취소 API 없음(작업 전체 취소) |
| C15 | 1차 §10.3 `stage_status`(B4), 메인 결정 | `GET /studies/{id}`의 `stage_status`에 `"1"`·`"2"`·`"5"` 키 추가 — 기존 `"3"`·`"4"`와 같은 모양 `{latest_job_id, latest_job_type, latest_state}`, 각 단계(`jobs.stage`) 최근 작업 기준: ①=TD_* 계열, ②=CU_*·SPDM_IMPORT, ⑤=OPTIMIZE |
| C16 | §6.10·§6.12 이름 필드 | ⑤ RESPONSES의 `datatype`·`component`·`layer`·`request`, ②-4 `curves[].type·request·component`, ②-2 `selection.items[].datatype·component`는 허용 문자 화이트리스트 `[\w 공백 _ - . / ( ) : +]`(≤200자)만 — 줄바꿈·제어문자·`"`·`$`·`[ ]`·`{ }`·`;`·`|`는 422(`RESPONSES_INVALID`·`INVALID_PARAMS`). 값이 TCL·hvtrans cfg·JSON 해석기로 넘어가기 때문 |
| C17 | §6.11 SI_COPY(TOCTOU) | SI_SCAN이 파일별 (st_dev, st_ino)·크기·mtime을 계획 파일에 기록. 열 때 상위 구성요소·파일의 링크/reparse 재검사 → `O_RDONLY|O_NOFOLLOW`(가능 OS)로 열고 fd의 fstat를 경로 lstat·스캔 기록과 대조(일반 파일만), 다르면 step 실패 `INPUT_CHANGED`. **한계**: Windows는 O_NOFOLLOW가 없어 reparse 검사 후 열기 + 열린 핸들의 파일 인덱스·볼륨 번호 대조로 대신하며, 상위 **폴더**를 검사 직후·열기 직전에 junction으로 바꾸는 경합은 완전히 막지 못한다(열린 파일이 스캔 때 파일과 같은지 inode 대조로 탐지) |
| C18 | §7.1 T12, §7.3 알림 | 대기 중 취소에서 PBS 취소 명령이 실패하면 그 hpc_job을 `CANCELED`로 적지 않고 `CANCEL_REQUESTED` + `error_message`로 두며, 작업은 `WAITING_HPC` + `attention_code=HPC_CANCEL_FAILED`, 알림 `HPC_CANCEL_FAILED`(1회, 등록자). 폴러가 매 주기 취소를 다시 시도(관리자 재요청도 그대로 유효)하고 모두 성공하면 T12. 이벤트 추가로 migration `0003_hpc_cancel_failed`(notifications.event CHECK), `MIGRATION_HEAD`=`0003_hpc_cancel_failed`. PBS `exit_code_regex`가 숫자가 아닌 값을 잡으면 그 조회는 `UNKNOWN`(로그 경고, `lost_after_polls` 규칙) |
| C19 | §15.3 XML | DOCTYPE·ENTITY 거부를 문자열 검사가 아닌 파서(expat `StartDoctypeDeclHandler`·`EntityDeclHandler`·외부 엔티티 핸들러)에서 처리 — UTF-8/16·BOM·XML 선언 인코딩과 무관. expat이 모르는 인코딩(UTF-32 등)은 형식 오류 `INPUT_INVALID` |
| C20 | §12.9 `JobSummary` | `attention_code`(nullable) 추가 — 1차 `Job`에만 있던 값을 `GET /queue`·`GET /jobs` 요약에도 실어 대기열 패널이 T10b(`HPC_RUN_FAILED`)·취소 실패(`HPC_CANCEL_FAILED`) 주의 표시를 할 수 있게 |
| C21 | 운영 준비(2026-10-09, 메인 결정) | 시연 모드 추가: 설정 `demo.enabled`·`demo.frontend_root`, `auth.mode: demo`(`demo.enabled` 필요), `demo.enabled`는 `profile=dev` && `server.host=127.0.0.1`일 때만, 시연 로그인은 루프백 요청만. `deploy/demo/`(start/stop-demo), `config/platform.demo.yaml`, 오프라인 묶음에 포함. 설치 무인화 `install.ps1 -PasswordsFromEnv -NoStart`(`PHYSICSAI_INSTALL_PG_ADMIN_PASSWORD`·`_DB_PASSWORD`·`_SERVICE_PASSWORD` 프로세스 환경변수). 운영 절차는 docs/manual/admin.md §14 |
| C22 | §11.2 `deploy.json` | `backend_port` 삭제 — 백엔드 포트는 `platform.yaml` `server.port` 하나에서만 읽는다(install·update의 health 확인, Caddy `PHYSICSAI_PORT` 안내 모두 이 값) |
| C23 | 1차 §14.2 설정 스키마 | 예약(미사용) 키 `server.base_path`·`hpc.transfer.stage_in`·`hpc.adapter.module`: 예시 YAML에서 제거, 스키마에는 호환용으로 남기고 값이 있으면 경고(`/status.config.warnings`). 경로 접두 `/physicsai`는 코드 고정 |
| C24 | 1차 §8.3 오류 정규식 | `commands_log_error_patterns`는 **edspy step에만** 적용(계약 본문 준수로 복귀 — 이전 구현은 1차 LOCAL step 전부에 적용). ①-3은 `train_data.hst_log_error_patterns` 그대로 |
| C25 | 1차 §14.3 "확정 템플릿 null 금지", phase2 §12.1 | 설정 파일에 키가 **아예 없으면**(예시 일부만 복사) 오류가 아니라 해당 기능만 비활성: `commands.*` 누락 → 그 기능 `features.<x>.enabled=false` + 작업 생성 409 `TEMPLATE_NOT_CONFIGURED`, `hpc.command` 누락(gateway=command) → PBS 미구성, `worker.gpu_query` 누락 → GPU 표시 없음. 1차 확정 템플릿에 **명시적 null**은 계속 설정 오류. `/status`에 `config.warnings:[key]`와 `features.dataset_create`·`evaluate`·`predict`(1차 확정 템플릿 기준) 추가 |
| C26 | 1차 §11·운영 로그 | 백엔드·워커 회전 파일 로그: 설정 `logging.dir`(빈 값 = 작업 폴더 `./logs` = 설치본 `<install_root>\logs`, AI 루트·SPDM 밖), `logging.max_mb`(기본 20), `logging.backups`(기본 10) → `backend.log`·`worker.log`. 모든 레코드에 오류 묶음과 같은 마스킹. 폴더 생성 실패 시 콘솔만(기동 계속). 시연은 추가로 `*.out.log`(표준 출력) |
| C27 | 배포 호환성 | `migrations/alembic.ini`를 ASCII 전용으로(Windows 로캘 인코딩으로 읽혀 깨지는 문제). `install.bat`·`update.bat`·`start-demo.bat`·`stop-demo.bat`에서 `PSModulePath`를 비우고 Windows PowerShell 5.1 실행(pwsh 7에서 불러도 5.1 기본 모듈 사용) |
| C28 | 검증(CI) | `.github/workflows/ci.yml`: linux(test-all + collect-offline dry-run), windows(`-m windows` skip=실패 → pytest 전체 → ps1 구문 검사 pwsh 7·5.1 → collect-offline 실제 → install 실제 설치·작업 등록 확인·해제 → 시연 원클릭). V-JO-1~3, V2-EC-4, V2-DEP-1·2의 Windows 부분은 CI 러너 결과로 증적(러너 기준). 실패 로그는 `scripts/ci_annotate.py`로 `::error` 주석 |

## 변경 메모(Plan, 2026-10-10 — 소스 구조 정리)

| # | 위치 | 내용 |
|---|---|---|
| P1 | 1차 §21.1·§21.2, 이 문서 §19.1·§19.2 파일 표 | 동작 불변 리팩터링([refactor-plan.md](../refactor-plan.md))으로 파일 위치가 바뀐다. 파일 표는 **소유권 경계**(`backend/**`·`worker/**`·`frontend/**`) 기준으로만 유효하고, 개별 파일 위치는 [architecture.md](../architecture.md)가 우선한다. `worker/physicsai_worker/claim.py`(미사용 shim)는 삭제한다. 공개 API·openapi·DB·설정 키·job_type·step_key는 바뀌지 않는다 |
