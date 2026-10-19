# 계약: S16 VOC 반영 — 단일 예측 실행 목록·조립 FEM 검증 비교·영상 저장/표시 — phase3 §21

> 이 문서는 phase3.md §21과 변경 메모 D3-64다. s12_s13.md·s14_analysis.md·s15_sampling.md와 같은 사정으로 별도 파일(`docs/contracts/s16_voc.md`)로 두며, 다음 Plan 커밋에서 phase3.md 본문과 변경 메모 목록으로 옮긴다. 절 번호·용어·원칙은 phase3.md(§11 예측 체인, §14 일괄 예측, §15 캡처, §16 SCX)·s12_s13.md(§17·§18)·s14_analysis.md(§19, 표시 번호 ⑤ 결과분석·⑥ 최적화)·s15_sampling.md(§20)를 따른다. 사용자 VOC 2026-10-19(D3-64). **migration 1개**(`0013_fem_verify`, V2만). 1·2·3차 원칙(단일 슬롯 FIFO, 제한기, `shell=False`, 설정만·하드코딩 금지, 원본·SPDM 읽기만, AI 루트만 쓰기, 삭제 없이 `_backup`, 한국어, 필수 UI, 파일 본문 DB 저장 금지)은 그대로 유지한다.

## 21. S16 VOC 반영 (사용자 VOC 2026-10-19, D3-64)

### 21.0 범위 / 비범위

| 범위 | 비범위(별도 계약·후속) |
|---|---|
| V1 ④ 단일 예측 실행 목록(이력) 탭 + 선택 시 결과(컨투어·커브·응답·입력값·경로) | 멀티 목적 최적화, 성능 정의(별도 계약) |
| V2 조립 상태 FEM 검증 해석과 예측 비교(출처 4종, 조립 원본 3종, PBS·SCX 제출, 응답·커브·컨투어 비교) | 여러 설계점을 한 번에 검증(파레토 집합 일괄) — 설계점마다 1건씩 만든다(§21.9 미결 4) |
| V3 영상 저장 실패 원인 노출, 선택적 ffmpeg 변환(≤ 1 MiB 목표), 재생 실패 대체 표시, 서버 확인 항목 | 웹 3D 뷰어(2026-10-09 보류 유지), 새 영상 코덱 라이브러리 번들 |
| PREDICT_VERIFY 화면 버튼을 FEM 검증으로 대체(작업 유형·API 유지) | PREDICT_VERIFY 작업 유형 삭제(§21.9 미결 5) |
| | `04_verify/**`를 S3 정리 범주에 넣는 것(§14.11 R-2와 같은 취급 — 크기만 표시) |

### 21.1 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| H1 | V1은 **새 DB 없음**. jobs 행의 params·result와 param_sets·models 조회로 실행 목록을 만든다. 새 읽기 API 2개는 `routers/jobs.py`에 둔다 | 예측 이력은 이미 PREDICT 작업으로 남아 있다(입력값·적용값·starter·응답 표·media·curve). main.py·schemas/__init__를 건드리지 않아 V2와 병렬 진행 |
| H2 | 목록 대상 = 그 Study의 `PREDICT` 중 일괄 예측 하위(`params.batch_run`)를 뺀 것. 재시도 묶음은 **최신 시도 1행**(`attempts` 수 표시) | 일괄 예측은 ④ 배치 화면에 이미 있다. 재시도는 같은 폴더(root)를 쓰므로 1행이 자연스럽다 |
| H3 | 선택 화면은 기존 `?job=<id>`(OpenedJob)를 확장한 `PredictRunView`. 새 라우트 없음 | 일괄 예측의 "단일 예측으로 열기"와 같은 화면을 함께 씀 |
| F1 | V2 = 새 job_type **`FEM_VERIFY`**("조립 FEM 검증", stage 4, SLOT). PREDICT_VERIFY는 **유지(호환)**하고, 화면 버튼만 FEM 검증으로 대체 | 기존 작업 기록·재시도·시험(V3-S6-11·V3-S9-3)을 그대로 보존. FEM_VERIFY `predict_input` 방식이 PREDICT_VERIFY의 상위 집합 |
| F2 | 메시 교체 = 기존 m_2(`commands.mesh`, include TCL, RENUM csv) + `assemble_into`(RAD_ASSEMBLE ①~④) **재사용**. 새 외부 도구 없음 | 사용자 지정. 원본 일치 판정 규칙(§11.4)을 그대로 이어받음 |
| F3 | 제출 = 기존 `HpcJobGateway`(command=PBS / scx). HPC_SUBMIT·HPC_WAIT·COLLECT step 키·폴러·상태 매핑·SUBMISSION_UNKNOWN 규칙(§16.4~§16.6)을 그대로 쓴다 | 사용자 결정 "새 실행기 없음" |
| F4 | **DB 테이블 `fem_verifications`**(migration 0013) | ① 동반 예측이 끝난 뒤 종료 훅이 FEM_VERIFY를 넣으려면 대기 중 검증을 찾을 기록이 필요 ② ④·⑤·⑥ 출처별 목록·FV 번호·비교 요약을 파일 없이 보여 줌. 수치·경로·상태만 저장 |
| F5 | 같은 설계점의 성공한 예측이 없으면 **동반 PREDICT**(parametric)를 같은 트랜잭션에서 만들고, 그 예측이 SUCCEEDED로 끝나면 `job_end` 훅이 FEM_VERIFY를 넣는다(슬롯 미점유 대기, §18 O2와 같은 패턴) | 예측과 FEM이 같은 SimLab 메시를 쓰도록 보장. 조립 템플릿이면 예측 INPUT을 그대로 해석(같은 입력) |
| F6 | 조립 원본 3종: `predict_input`(예측 입력이 조립 상태일 때만) · `train_doe`(① DOE `assem_rel`) · `custom`(경로 선택기, `allowed_roots(imports=True)` + `storage.spdm_roots`, 읽기만). 선택한 원본은 `F/a<n>/assem/`에 **스냅숏 복사**(하드링크 금지) | SPDM 보호, 해석 중 원본이 바뀌는 것 방지, 재현성 |
| F7 | 컨투어 비교 = **같은 범례**: 요청이 fixed면 그 값, 아니면 응답 TCL(§14.6) 요청 줄 `__FV_LEGEND`로 두 h3d의 min·max를 읽어 합집합 범위. 두 h3d 모두 FV_CAPTURE에서 같은 표시 설정으로 캡처(예측 원래 media는 고치지 않음) | 사용자 요구 "같은 범례; FEM h3d에도 캡처 TCL 적용". 새 TCL 없이 기존 MinMax TCL 재사용 |
| F8 | FEM 결과 필드 이름은 예측 h3d와 다를 수 있다 → 설정 `fem_verify.field_map`(예측 필드 → FEM 필드)과 요청 `fem.field`로 덮어쓴다 | 예측 h3d 필드(`CornerStress` 등)는 큐레이션 이름일 수 있음(E4-14-F2) |
| F9 | FEM_VERIFY는 활성 작업 유일 인덱스에서 **제외**(Study당 동시 `fem_verify.max_active` 4건, 같은 예측+같은 조립 원본 중복은 409). 동반 PREDICT도 제외 | HPC 대기(수 시간) 동안 다른 설계점 검증·일반 예측을 막지 않음 |
| F10 | 재시도: 첫 실패 step이 COLLECT 이하면 1단계부터(새 시도 폴더 `a<n+1>`, 새 원격 폴더), FV_EXTRACT 이후면 그 step부터(같은 시도 폴더, 해석 결과 재사용) | B9 "HPC 제출 재사용 안 함" 유지 + 수 시간짜리 해석을 후처리 실패 때문에 다시 돌리지 않음 |
| M1 | TCL: `save animation`이 성공을 보고해도 파일이 없거나 0바이트면 `video=0` + 오류 "파일이 만들어지지 않았습니다". 저장 범위 `VID_SCOPE`(page·window, 기본 page = 현재 동작) | 증상 미상 — 현재는 조용히 사라짐(capture.py:136-155) |
| M2 | 워커: 동영상을 켰는데 등록되지 않은 방향이 있으면 작업당 경고 1건 `CAPTURE_VIDEO_FAILED`(방향별 원인) + media API `video_error` | 원인 문구를 사용자가 볼 수 있게 |
| M3 | 선택적 ffmpeg: `capture.ffmpeg.exe`가 비어 있으면 건너뛴다. 있으면 모든 영상을 H.264·yuv420p·`+faststart` mp4로 변환하고, `capture.video_target_bytes`(1 MiB)를 넘으면 단계표(`ladder`)대로 크기·crf·fps를 낮춰 다시 인코딩. 원본은 `media/raw/`에 보존(삭제 없음) | 브라우저 재생 호환 + 사용자 요구 ≤ 1 MB. 하드코딩 금지(경로·인자 모두 설정) |
| M4 | avi는 **기본 금지**: `video_ext: avi`이면서 `capture.allow_avi=false`면 설정 경고 + 실제 저장은 mp4(`effective_video_ext`). 설정 오류(503)로 만들지 않음 | 기존 설치를 작업 불가로 만들지 않기 위함 |
| M5 | 프런트 `components/MediaVideo.tsx`: `<video>`/`<source>` onError → "브라우저가 이 형식을 재생하지 못합니다 — 받기", gif → `<img>`, avi·`playable=false` → 재생 시도 없이 안내 + 받기 | 현재 ContourMedia.tsx:163-164는 실패 대체 없음 |

### 21.2 V1 — ④ 단일 예측 실행 목록

#### 21.2.1 데이터(새 DB 없음)

- 대상 행: `jobs.job_type='PREDICT' AND study_id=? AND (params->'batch_run') IS NULL AND NOT EXISTS(retry_of_job_id = 이 행의 id인 jobs)`(재시도된 이전 시도 숨김). 정렬 `(created_at DESC, id DESC)`, 커서 = 마지막 행의 `created_at|id`(기존 `/jobs`처럼 `X-Next-Cursor` 헤더).
- 행 값의 출처: params(`input_mode` 없음 = parametric, `param_set_id`, `model_id`, `values`, `value_source`, `input_path`, `template_kind`, `display`), result(`applied_values`, `out_of_range`, `nearest`, `starter`, `response_table`, `media`, `capture.status`, `curve_artifact_id`, `pred_h3d_rel`, `warnings`), 재시도 수 = `retry_of_job_id` 사슬 길이(최대 50까지만 따라감), `root_job_id`(폴더 `04_predict/<root>`).
- 입력 방식 표시: `template`(parametric) | `prepared`. `origin`: `manual` | `fem_verify`(params에 `fem_verify_id`가 있으면 — V2 동반 예측. V2 전에는 항상 manual).
- 응답 요약: `response_table`의 앞쪽 최대 5개 `{name, unit, predicted}`.
- PREDICT_VERIFY 요약(기존): 이 예측을 가리키는 최신 PREDICT_VERIFY `{job_id, state}` 1개(있을 때). V2 FEM 검증 요약은 V1 API에 넣지 않는다(화면이 V2 API로 따로 조회 — 병렬 진행 조건).
- DB에는 아무것도 쓰지 않는다. 파일은 읽지 않는다(경로 존재 확인만).

#### 21.2.2 API(`backend/openapi.json` 갱신, `routers/jobs.py`에 추가)

```jsonc
// GET /studies/{study_id}/predict-runs?mode=all|template|prepared&state=&limit=50&cursor=   (로그인 member 이상)
// → 200 [PredictRunSummary], 헤더 X-Next-Cursor(다음 페이지가 있을 때)
[{"job_id":"j9","root_job_id":"j7","attempts":2,"state":"SUCCEEDED","origin":"manual",
"created_at":"…","started_at":"…","finished_at":"…","duration_s":512,"created_by_name":"차완기",
"input_mode":"template",                                   // template | prepared
"template":{"id":"ps-1","label":"쿠션 v1","input_kind":"mesh_only"},   // prepared + 세트 없음 = null
"model":{"id":"m-2","name":"cushion_TNS","version":3},
"values":{"THK_1":4.0},"applied_values":{"THK_1":4.0},"out_of_range":[],
"input_path":null,"starter":"EPS_mesh_0000.rad",
"responses":[{"name":"MaxStress","unit":"MPa","predicted":152.3}],
"capture":{"status":"OK","views":["iso","front","top","right"]},       // 캡처 없음 = null
"has_curve":true,"warnings_count":1,
"failure":null,                                              // {code,message} — 실패·취소 시 첫 실패 step
"verify":{"job_id":"v3","state":"SUCCEEDED"}}]             // 기존 PREDICT_VERIFY만, 없으면 null
// GET /predict-runs/{job_id}   (member) — PredictRunSummary + 아래
{"…":"…", "nearest":{"run_key":"run__00014","distance":0.12},
 "response_table":[{"name","unit","predicted","nearest_measured","diff_pct"}],
 "paths":{"dir":"E:\\AI\\cushion\\04_predict\\j7","input_dir":"…\\INPUT","result_dir":"…\\RESULT",
        "pred_h3d":"…\\RESULT\\EPS_mesh_0000_pred.h3d","media_dir":"…\\RESULT\\media","geom_dir":"…\\geom"},  // 폴더·파일이 없으면 그 키 null
 "display":{…}}                                                // result.capture.display(있으면)
```
- `mode`: template = `input_mode` 없음 또는 parametric, prepared = prepared. `state`: 쉼표 구분 job state(QUEUED,RUNNING,SUCCEEDED,FAILED,CANCELED,INTERRUPTED,WAITING_HPC). 모르는 값은 422 `INVALID_PARAMS`.
- 404 `JOB_NOT_FOUND`(없음·다른 Study 권한), 404 `NOT_PREDICT_RUN`("단일 예측 작업이 아닙니다" — 일괄 하위·다른 유형). 일괄 하위의 상세는 기존 `/jobs/{id}`와 `?job=` 화면을 쓴다.
- 경로 표시는 기존 `input_display_path`와 같은 OS 표기(절대경로). Study 정리로 `_backup`에 간 폴더는 null.

#### 21.2.3 화면(필수 UI만, D3-55/56 톤)

- ④ 입력 방식 `템플릿 값 입력`·`준비된 입력 파일` 아래에 하위 탭 `새 예측 | 실행 목록`(`stages/stage4/history/SingleTabs.tsx`). localStorage `physicsai.stage4.singleTab` = `new|list`(try/catch). 기본: 진행 중(QUEUED·RUNNING) PREDICT가 있으면 실행 목록, 없으면 마지막 선택, 그것도 없으면 새 예측. `일괄 예측(DOE)`은 기존 하위 탭 그대로.
- **실행 목록**(카드 1개, 표): `시작 · 입력 방식 · 템플릿/입력 파일 · 값(앞 3개 "THK_1=4.0 · RIB_N=6 …") · 응답(첫 응답 값 단위) · 상태(배지, 재시도면 "2회차") · 소요`. 머리에 필터 세그먼트 `전체 | 템플릿 | 준비된 입력`(기본 = 현재 입력 방식). 아래 `더 보기`(커서). 진행 중 행이 있으면 `POLL.batch`(5초) 폴링. 빈 상태 "아직 실행한 예측이 없습니다". 행 클릭 → `?job=<job_id>`.
- **실행 결과**(`PredictRunView`, 기존 OpenedJob 대체): 머리 `예측 · MM-DD HH:mm · <템플릿 label 또는 입력 파일 이름>` + `← 실행 목록`(일괄 하위면 기존 `← 일괄 예측 결과`) / 카드 `입력·경로`(표 `파라미터 | 입력값 | 반영값 | 범위 밖`, 모델, starter, `paths` 각 줄 + `경로 복사`) / 기존 `PredictResultCard`(컨투어 `ContourMedia`·커브·응답 표·입력파일 받기) 무수정 재사용 / 검증 버튼 줄(V2 전에는 기존 `usePredictVerify`, V2 뒤에는 "FEM 검증").
- 문구: 탭 `새 예측`·`실행 목록`, 상태 배지는 기존 `JobInline` 상태 문구.

### 21.3 V2 — 조립 상태 FEM 검증과 예측 비교

#### 21.3.1 용어·흐름

```
출처(④ 예측 run · ④ 배치 run · 템플릿 값 · ⑥ 내장 최적화 설계점)
└─ 해석(resolve): 비교할 PREDICT 작업 P(있으면 재사용, 없으면 동반 PREDICT 생성 → 종료 훅 대기)
     └─ FEM_VERIFY:  메시(P의 SimLab EPS_mesh_0000.rad) ──m_2──▶ 104_replace_node_elem.inc
                      조립 원본 스냅숏 + 새 include ──RAD_ASSEMBLE──▶ F/a<n>/input(starter)
                      └─ HPC(PBS|SCX) 해석 → 회수(F/a<n>/result/*.h3d, *T01)
                      └─ 응답 추출(예측·FEM) · 커브(T01) · 컨투어(같은 범례 두 쪽) → compare.json
```
- 폴더 `F = <study>/04_verify/FV-003/`(설정 `fem_verify.dir_name`), 시도 `F/a<n>/`(n = 1부터, 1단계부터 다시 하면 n+1). 내부: `mesh/`(SimLab 메시 사본·m_2 출력·`log_batch.txt`), `assem/`(조립 원본 스냅숏), `input/`(해석 입력), `result/`(회수), `extract/{pred,fem}/`, `curves/`, `media/{pred,fem}/`, `compare.json`, `responses_fem.csv`. `F/verify.json`(출처·설계점·모델 sha256·조립 원본 경로와 파일 sha256 목록). 같은 시도 안에서 다시 쓰는 파일·폴더는 `_backup`으로 옮긴 뒤 쓴다.
- "FEM" = 조립 상태 Radioss 해석(사용자 용어). 화면 표기 "FEM 검증".

#### 21.3.2 출처 해석(서비스 `physicsai_api/services/fem_verify_sources.py`)

| source.kind | 입력 | 비교 대상 P | 메시 원천(재조립용) | 비고 |
|---|---|---|---|---|
| `predict_job` | `job_id`(PREDICT, 같은 Study) | 그 작업(SUCCEEDED 필요, 아니면 problem `PREDICT_NOT_SUCCEEDED`) | parametric: `04_predict/<root>/geom/{simlab_mesh_name}` · 일괄 하위(prepared+batch_run): `B/run__N/m_1/{simlab_mesh_name}` · 그 밖 prepared: 없음 | 일괄 하위 작업 id도 받는다 |
| `batch_run` | `batch_id`, `doe_no` | run의 `predict_job_id`(SUCCEEDED 필요) | `B/run__N/m_1/{simlab_mesh_name}` | ⑤ 결과분석 예측 출처 행 |
| `values` | `param_set_id`, `values`(전 파라미터), `model_id?`, `reuse_existing`(기본 true), `origin?`(`{kind:"optimize", job_id}` 표시용) | 같은 세트·같은 모델·`applied_values` 모두 같은(\|Δ\| ≤ 1e-9) 성공 parametric PREDICT 중 최신(INPUT·geom 폴더가 있을 때) → 재사용, 없거나 `reuse_existing=false` → **동반 PREDICT** | 동반 예측의 geom | 검증 규칙 = PREDICT parametric과 같음(422 `INVALID_PARAMS`), 범위 밖 허용(경고 `OUT_OF_RANGE`) |
| `opt_design` | `opt_id`, `pick` = `best` \| `final_optimum` \| `surrogate_optimum` \| `run`(+ `iter_no`, `doe_no`) | best·run → 해당 배치 run(위 batch_run), final_optimum → FINAL 배치 doe 2(D3-61), surrogate_optimum(검증 안 된 대리모델 최적, `summary.json`) → values 규칙 | 위와 같음 | 원본 최적화(OPTIMIZE) 결과 행은 프런트가 `values` + `origin`으로 보냄 |

- 해석 결과는 `fem_verifications.source_ref`(id·라벨·값 수치만)와 `predict_job_id`에 고정된다(뒤에 다시 해석하지 않음).
- 동반 PREDICT params = §11.5 parametric 저장 형식 + 서버 전용 키 `fem_verify_id`(API `POST /jobs`의 PREDICT에 넣으면 422 `INVALID_PARAMS`). 알림 `JOB_STARTED`·`JOB_SUCCEEDED`·`MY_TURN_NEXT`는 억제하고 `JOB_FAILED`는 유지.

#### 21.3.3 조립 원본(`physicsai_core/stage4_predict/fem_assembly.py` — API·워커 공용, 순수 파일 검사)

| assembly.kind | 허용 조건 | 원본 폴더 | 입력 방식 |
|---|---|---|---|
| `predict_input` | P의 INPUT starter가 eps_mesh 파일이 **아님**(조립 템플릿·조립 배치·조립 상태 준비된 입력). 아니면 problem `INPUT_MESH_ONLY` "이 예측 입력은 쿠션 메시뿐이라 그대로 해석할 수 없습니다 — 조립 원본을 고르세요" | `04_predict/<root>/INPUT`(일괄 하위도 자기 INPUT) | `reuse`(FV_MESH SKIPPED, INPUT 직속 파일 복사 = PREDICT_VERIFY와 같음) |
| `train_doe` | 같은 Study의 `train_does` READY. 파라미터 이름 집합이 템플릿과 다르면 경고 `DOE_PARAM_MISMATCH`(막지 않음 — 조립 폴더만 씀) | `S/<train_does.assem_rel>` | `rebuild` |
| `custom` | 경로 = 폴더, `check_user_path(allowed_roots(imports=True))` 또는 `spdm.check_spdm_path(storage.spdm_roots)`. `_backup`·`_platform`·링크·공백·메타문자 거부(PATH_*) | 사용자 지정(읽기만) | `rebuild` |

- 기본값: P 입력이 조립 상태면 `predict_input`, 아니면 Study의 최신 READY `train_doe`(없으면 필수 선택 — problem `ASSEMBLY_REQUIRED`).
- `rebuild`는 메시 원천이 있어야 한다(없으면 `MESH_MISSING` "예측 폴더에 형상 메시가 없습니다(정리됨 또는 준비된 입력)"). `commands.mesh` 또는 include TCL이 없으면 409 `TEMPLATE_NOT_CONFIGURED`(§11.4 문구 재사용). `commands.mesh`에 `{rendered_script}`·`{cad_file}`이 있으면 problem `MESH_TEMPLATE_PLACEHOLDER`.
- 조립 폴더 검사(`plan_assembly(path, settings)` → `{files[], starter, rad[≤50], inc_count, renum_csv: bool, include_baseline: bool, include_referenced: bool|null, total_bytes, file_count, problems[], warnings[]}`):
- 복사 대상 = `assembly_sources` 규칙(직계 `*.rad`·`*.inc` 중 eps_mesh·include 기준본 아닌 것) + `{renum_csv_name}`(있으면).
- starter = `starter_glob` 일치·eps_mesh 아님 **정확히 1개**(아니면 `ASSEM_STARTER_COUNT` + 후보 목록).
- 파일명 `file_safety_problem`(`FILE_NAME_UNSAFE`), 개수 ≤ `fem_verify.max_assem_files`(500), 합계 ≤ `fem_verify.max_assem_bytes`(2 GiB)(`ASSEM_TOO_MANY_FILES`·`ASSEM_TOO_LARGE`).
- 경고: csv 없음 `RENUM_CSV_MISSING` · include 기준본 없음 `MESH_INCLUDE_NOT_IN_ASSEM` · 참조 없음 `MESH_INCLUDE_NOT_REFERENCED`. 참조 검사는 크기 ≤ `fem_verify.include_scan_max_bytes`(16 MiB)인 직계 rad·inc를 줄 단위로 읽어 `#include` 줄에 `{mesh_include_name}`(대소문자 무시)이 있는지 본다. 그보다 큰 파일만 있으면 `null`(검사 안 함).
- FV_PREP이 같은 함수로 다시 검사하고, 결과가 생성 때와 다르면(파일 목록·크기·mtime) `INPUT_CHANGED`. 그 뒤 `F/a<n>/assem/`으로 복사한다(원본 mtime 불변. SPDM 원본은 §6.11 규칙대로 O_NOFOLLOW·열린 파일 대조).

#### 21.3.4 DB — migration `0013_fem_verify`(Revises `0012_sampling_kinds`, `MIGRATION_HEAD` 갱신)

- `fem_verifications`:
- 식별: `id PK`, `study_id FK`, `fv_no INT`(Study별 1부터, UNIQUE(study_id, fv_no), 표시 `FV-003`).
- 출처: `source_kind VARCHAR(16)` CHECK `IN ('PREDICT_JOB','BATCH_RUN','VALUES','OPT_DESIGN')`, `source_ref JSONB NOT NULL`(id·라벨·pick·values 수치만).
- 예측: `predict_job_id FK jobs NULL`(동반이면 생성 직후 채움, 재시도 시 갱신), `companion BOOLEAN NOT NULL DEFAULT false`, `param_set_id FK NULL`, `model_id FK NULL`, `template_kind VARCHAR(16) NULL`.
- 조립: `assem_kind VARCHAR(16)` CHECK `IN ('PREDICT_INPUT','TRAIN_DOE','CUSTOM')`, `assem_ref JSONB`(`{doe_id}` 또는 `{path}` 정규화본), `input_mode VARCHAR(8)` CHECK `IN ('reuse','rebuild')`, `options JSONB`(fem field·comps·display·hpc 정규화본).
- 실행: `job_id FK jobs NULL`(최신 FEM_VERIFY), `attempt_no INT NOT NULL DEFAULT 0`, `status VARCHAR(16)` CHECK `IN ('WAITING_PREDICT','RUNNING','DONE','FAILED','CANCELED')`, `summary JSONB NULL`(수치만: §21.3.6 요약), `failure_code VARCHAR(32) NULL`, `failure_message VARCHAR(500) NULL`, `dir_rel VARCHAR`.
- 기록: `created_by, created_by_name, created_at, finished_at`.
- 인덱스 `(study_id, created_at DESC)`, `(predict_job_id)`.
- `ux_jobs_study_type_active` WHERE에 `AND job_type <> 'FEM_VERIFY' AND NOT (job_type = 'PREDICT' AND (params -> 'fem_verify_id') IS NOT NULL)` 추가(기존 제외 조건 유지).
- `notifications.ck_notifications_event`에 `'FEM_VERIFY_DONE'` 추가. artifacts kind CHECK는 그대로(CONTOUR_IMAGE·CONTOUR_VIDEO·CURVE_JSON 재사용, `meta = {view, side:"pred"|"fem", fv_id}`).
- downgrade는 RuntimeError(관례).

#### 21.3.5 작업·step — job_type `FEM_VERIFY`

`JobTypeDef("FEM_VERIFY", 4, "SLOT", "조립 FEM 검증", …, "④", notify_success=False)`. `POST /jobs`로는 만들 수 없다(422 `INVALID_PARAMS` job_type) — 검증 API·종료 훅만 만든다. params `{"fem_verify_id","fv_no","hpc":{queue,ncpus,walltime}|null}`.

| # | step | kind(무게) | 처리 |
|---|---|---|---|
| 1 | FV_PREP | INTERNAL 3 | 검증 행·P(SUCCEEDED) 확인. 시도 번호 = 행 `attempt_no + 1`(행 갱신), `F/a<n>/` 생성. `verify.json` 작성(첫 시도. 이후는 `_backup` 후 갱신). rebuild면 메시 원천 → `mesh/{simlab_mesh_name}` 복사 + 조립 원본 재검사(§21.3.3) → `assem/` 스냅숏. reuse면 P/INPUT 직속 파일 → `input/`(이름 검사), starter = P result `starter`. 메시 include의 `/PART/<id>` 머리 줄(최대 200개)을 읽어 `cushion_part_ids`를 result에 둔다. result `{fv_rel, attempt, input_mode, starter?, mesh_rel?, assem_files[], cushion_part_ids[]}` |
| 2 | FV_MESH | LOCAL 5 | reuse → SKIPPED "예측 입력 재사용". rebuild → `run_local("mesh", {hw, include_tcl, simlab_mesh:F/a/mesh/EPS_mesh_0000.rad, mesh_inc:F/a/mesh/{mesh_include_name}, renum_csv:F/a/assem/{renum_csv_name}, work_dir:F/a/mesh}, cwd=F/a/mesh, allow_nonzero_exit=True)`. 판정·경고는 §11.4 MESH(`mesh_preflight`·`judge_output`·`mesh_log_warning`, `log_batch.txt` 덧붙임) 그대로 |
| 3 | FV_ASSEMBLE | INTERNAL 2 | reuse → 할 일 없음(1에서 복사), starter 확인만. rebuild → `input/`을 비운 뒤(`_backup`) `assemble_into(settings, F/a/assem, F/a/mesh/{inc}, F/a/input)` → starter·경고. `commands.rad_assemble` 있으면 §11.4처럼 실행. 결과 starter가 eps_mesh면 `INPUT_INVALID` |
| 4 | HPC_SUBMIT | HPC_SUBMIT 5 | PREDICT_VERIFY와 같은 공통 헬퍼(§21.3.7). run_key `verify`, input_dir `F/a/input`, result_dir `F/a/result` |
| 5 | HPC_WAIT | HPC_WAIT 55 | 폴러(기존) |
| 6 | COLLECT | COLLECT 10 | PREDICT_VERIFY와 같음(command = in_place 안정성 대기, scx = relay 다운로드) |
| 7 | FV_EXTRACT | LOCAL 6 | §21.3.6 응답·범례 추출. 응답 정의 없고 범례 fixed면 SKIPPED |
| 8 | FV_CURVE | LOCAL 5 | §21.3.6 커브. 정의·T01·`resources.curate_hg_tcl` 중 하나라도 없으면 SKIPPED(사유) |
| 9 | FV_CAPTURE | LOCAL 8 | §21.3.6 컨투어 두 쪽. 캡처 미구성 → SKIPPED. **실패는 경고 `CAPTURE_FAILED`만**(작업 성공 유지) |
| 10 | FV_COMPARE | INTERNAL 1 | `compare.json`·`responses_fem.csv`·검증 행 `summary` 기록. result `compare`(요약) |

- FV_EXTRACT·FV_CURVE의 도구 실패는 경고(`RESPONSE_EXTRACT_FAILED`·`FEM_CURVE_FAILED`)이고 값은 비운다. 회수 h3d가 없으면(COLLECT 성공인데 h3d 0개) FV_EXTRACT `OUTPUT_MISSING`.
- 재시도(`/jobs/{id}/retry`·`/fem-verifications/{id}/rerun`): `from_step` 기본 = 첫 실패 step. 그것이 ≤ 6이면 강제로 1(새 시도, 새 원격 폴더), ≥ 7이면 그 step부터(이전 step SKIPPED "이전 작업 산출물 재사용", 시도 번호·`fv_rel`은 행의 `attempt_no`로 이어받음). `services/jobs.py`의 PREDICT_VERIFY·TD_SOLVE 규칙 옆에 추가.

#### 21.3.6 비교 규칙

**응답(FV_EXTRACT)** — §14.6 TCL 방식 재사용(`response_tcl.extract_in_folder`, 요청 줄 `NAME|SUBCASE|DATATYPE|COMPONENT|LAYER`):
- 요청 = 템플릿(P의 `param_set_id`) 응답 정의 전부 + 범례용 `__FV_LEGEND|{fem_verify.legend_subcase}|<field>|<component>|`. 범례 요청은 legend fixed면 생략. `__FV_LEGEND`는 예약 이름이며, 같은 이름의 사용자 응답이 있으면 `__FV_LEGEND2`.
- FEM 쪽: datatype = `fem.field`(요청) → `fem_verify.field_map[datatype]` → 원래 값. 범례 줄 field도 같은 규칙. cwd = `F/a/result`(h3d 정확히 1개, 아니면 경고 `RESP_H3D_AMBIGUOUS` + FEM 값 null).
- 예측 쪽: P의 `RESULT/RESPONSES.txt`가 있고 같은 폴더 `H3D_REQUESTS.txt`가 이번 요청(범례 줄 제외)과 같으면 그 값을 쓴다. 아니면 `F/a/extract/pred/`에 예측 h3d 사본(≤ `fem_verify.max_pred_h3d_copy_bytes` 4 GiB, 넘으면 경고 `PRED_H3D_TOO_LARGE`·값 null)을 두고 같은 TCL로 추출한다. 예측 폴더에는 쓰지 않는다.
- 값: 응답마다 `pred_min, pred_max, fem_min, fem_max`(RESPONSES.txt 원값), stat 적용값 `pred_value, fem_value`(MAX·MIN·ABSMAX), `diff = pred − fem`, `diff_pct = diff / |fem| × 100`. `|fem| ≤ fem_verify.zero_tol`(1e-12)이면 null + 사유 "기준값 0". MIN·MAX 행 각각도 같은 식으로 계산한다.
- 템플릿이 mesh_only이면 경고 `FEM_RESPONSE_WHOLE_MODEL` "FEM 응답은 조립 전체 모델의 최솟값·최댓값입니다(쿠션만 한정 불가) — 컨투어를 함께 보세요"(§21.9 미결 1).

**커브(FV_CURVE)**:
- 커브 정의 출처: ① 모델의 데이터셋 → 그 데이터셋 params의 `curation_id`(T01 큐레이션)의 params `curves` ② 없으면 Study의 최신 성공 `CU_T01_CURVES` params `curves` ③ 둘 다 없으면 SKIPPED "커브 정의 없음 — 커브 비교 생략".
- 대상 = `F/a/result`의 `*T01` 정확히 1개(아니면 SKIPPED + 경고). `curation.curve_input_json`으로 job 1개짜리 설정을 `F/a/curves/INPUT_CURATE_CURVE.json`에 쓰고 `run_local("t01_curve_export", {curate_tcl, config_json}, cwd=F/a/curves, check_log_errors=False)` → `F/a/curves/fem_curve.*` → `xydata` 파서로 `fem_curve.json`.
- 짝짓기: 예측 `04_predict/<root>/curve.json` 계열 이름과 정확히 같으면 짝, 아니면 대소문자·공백 무시로 다시 맞춤. 짝 없는 계열은 `unmatched_pred`·`unmatched_fem`에 이름만 둔다.

**컨투어(FV_CAPTURE)** — §15 `run_capture` 재사용(V3의 `extra_meta` 인자):
- 표시 설정 = `display_for(P)`(§15.3 순서) → 요청 `display` 덮어쓰기. 범례: 요청이 fixed면 그 값. 아니면 FV_EXTRACT `__FV_LEGEND`의 두 쪽 min·max 합집합(둘 다 유한·min < max일 때만) → `legend.source="minmax"`. 그것도 안 되면 auto + `legend_note` "범례를 맞추지 못했습니다 — 이미지마다 자동 범례"(사유).
- 예측 쪽: P의 예측 h3d → `F/a/media/pred/`(예측 원래 `RESULT/media`는 불변).
- FEM 쪽: 회수 h3d → `F/a/media/fem/`. field는 위 매핑. comps = 요청 `fem.comps` → (mesh_only이고 `fem_verify.auto_isolate_cushion`) `cushion_part_ids` → 없음.
- artifacts는 이 FEM_VERIFY 작업 id로 등록하고 meta에 `side`·`fv_id`를 둔다. 동영상은 V3 규칙(경고·변환)을 그대로 따른다.

**요약(`fem_verifications.summary`, 수치만)**: `{attempt, responses:[{name, unit, stat, pred_value, fem_value, diff_pct}], max_abs_diff_pct, worst:name|null, curve:{status, matched, names≤20}, media:{pred_status, fem_status, legend:{mode,min,max,source}}, warnings_count}`.

#### 21.3.7 HPC·SCX(규칙 그대로)

- 공통 헬퍼 분리: 현 `steps/stage4_predict/verify.py`의 `hpc_submit`·`_hpc_submit_scx`·`collect`·`_collect_scx` 몸체를 `steps/stage4_predict/_verify_hpc.py`로 옮겨 `(ctx, input_dir, result_dir, starter, job_name)`을 받게 한다. PREDICT_VERIFY는 같은 인자로 호출한다(동작·골든·로그 문구 불변, V3-S6-11·§16 시험 무수정 통과).
- command(PBS): `HpcSubmitSpec(job_name=<study>_fv<NNN>_a<n>(정규화·64자), run_key="verify", input_file=F/a/input/<starter>, input_dir, result_dir=F/a/result, queue/ncpus/walltime = params.hpc)`(path_map 적용).
- scx: 잡 이름 `04_FV-<NNN>_<ts>`(NNN = `fv_no` 3자리, `simdash_adapters.hpc.scx_naming.fem_verify_job_name(fv_no, ts)` 신설). 프로젝트·`_2`… 접미·SPDM 루트 금지·stage_patterns·replay·**SUBMISSION_UNKNOWN(자동 재제출·자동 취소 없음, attention·알림, 사용자 조치 3개)**·상태 매핑·COLLECT는 §16.3~§16.6 그대로. "제출 안 됨으로 처리" → 작업이 T13으로 끝나고 검증 FAILED "제출되지 않음(사용자 확인)" → 사용자가 `다시 실행`(새 시도·새 폴더).
- 취소: 기존 `/jobs/{id}/cancel` 경로(terminate, UNKNOWN 행 로컬 CANCELED + 경고) 그대로.

#### 21.3.8 API(`backend/openapi.json` 갱신, 새 `routers/fem_verify.py`)

```jsonc
// 미리보기(동기, 저장 없음, power) POST /studies/{id}/fem-verifications/preview  — 생성과 같은 본문
// 생성(power) POST /studies/{id}/fem-verifications
{"source":{"kind":"predict_job","job_id":"j9"}
      | {"kind":"batch_run","batch_id":"b3","doe_no":7}
      | {"kind":"values","param_set_id":"ps-1","model_id":null,"values":{"THK_1":3.2,"RIB_N":5},"reuse_existing":true,"origin":null}
      | {"kind":"opt_design","opt_id":"so1","pick":"best"},          // run이면 iter_no·doe_no 필수
 "assembly":{"kind":"predict_input"} | {"kind":"train_doe","doe_id":"d1"} | {"kind":"custom","path":"E:\\SPDM\\…\\assem_v2"} | null,   // null = 기본(§21.3.3)
 "fem":{"field":null,"component":null,"comps":null},                 // 선택. comps ≤ 50개, 각 64자, §15.3 금지 문자 규칙
 "display":{"views":["iso","front"],"legend":{"mode":"auto"}} | null, // §15.3 검증 재사용
 "hpc":{"queue":null,"ncpus":null,"walltime":null} | null}
// preview → 200
{"source_label":"④ 예측 10-19 14:02","design":{"param_set":{"id","label","input_kind"},"model":{"id","name","version"},
"values":{…},"applied_values":{…},"out_of_range":[]},
 "predict":{"job_id":"j9"|null,"state":"SUCCEEDED"|null,"reuse":true,"will_run":false},
 "input_mode":"rebuild","mesh":{"path":"E:\\…\\geom\\EPS_mesh_0000.rad","available":true},
 "assembly":{"kind":"train_doe","label":"DOE-001","path":"E:\\…\\01_train\\…\\radioss_assem","starter":"Face_Drop_0000.rad",
           "rad":["…"],"inc_count":12,"renum_csv":true,"include_baseline":true,"include_referenced":true,"file_count":31,"total_bytes":182736451},
 "fem_field":"CornerStress","comps_auto":["3000001"],"hpc_mode":"scx",
 "problems":[],"warnings":[{"code":"FEM_RESPONSE_WHOLE_MODEL","message":"…"}]}
// create → 201 FemVerification(상세와 같은 모양). 동반 예측이면 status WAITING_PREDICT + predict.job_id(QUEUED), 아니면 RUNNING + job(QUEUED)
// 목록(member) GET /studies/{id}/fem-verifications?predict_job_id=&batch_id=&opt_id=&status=&limit=50&cursor=
//   → [{id,label,status,source_label,source_kind,links,max_abs_diff_pct,worst,created_at,created_by_name,finished_at}] + X-Next-Cursor
// 상세(member) GET /fem-verifications/{fid}
{"id":"…","label":"FV-003","status":"RUNNING","status_text":"해석 대기(SCX)",
 "source":{"kind":"BATCH_RUN","label":"B-003 DOE #7"},"links":{"predict_job_id":"…","batch_id":"…","doe_no":7,"opt_id":null},
 "design":{…preview와 같음},"predict":{"job_id":"…","state":"SUCCEEDED","companion":false},
 "assembly":{"kind":"CUSTOM","label":"직접 지정","path":"E:\\…","snapshot_dir":"E:\\…\\04_verify\\FV-003\\a1\\assem"},
 "input_mode":"rebuild","attempt_no":1,"dir":"E:\\…\\04_verify\\FV-003",
 "paths":{"input_dir":"…\\a1\\input","result_dir":"…\\a1\\result","starter":"Face_Drop_0000.rad","remote_dir":"/Users/vd.dashboard/cushion/04_FV-003_20261019T101500"|null},
 "job":{JobSummary}|null,
 "compare":null | {"responses":[{"name","unit","stat","pred_min","pred_max","fem_min","fem_max","pred_value","fem_value","diff","diff_pct","note"}],
                 "max_abs_diff_pct":7.2,"worst":"MaxStress",
                 "legend":{"mode":"fixed","min":0,"max":312.5,"source":"minmax","note":null},
                 "curve":{"status":"OK|SKIPPED|FAILED","message":null,"names":["Node 100 / X"],"unmatched_pred":[],"unmatched_fem":[]},
                 "media":{"pred_status":"OK","fem_status":"PARTIAL"}},
 "warnings":[{code,message}],"failure":{code,message}|null,"can_cancel":true,"can_rerun":false,
 "created_at":"…","created_by_name":"…","finished_at":null}
// 컨투어(member) GET /fem-verifications/{fid}/media
{"status":"OK","display":{…},"legend":{…},"items":[{"view":"iso","label":"등각",
 "pred":{"image":MediaFile,"video":MediaFile|null,"video_error":null}|null,
 "fem":{"image":MediaFile,"video":MediaFile|null,"video_error":"…"}|null}]}       // MediaFile = §15.4 + V3 필드
// 커브(member) GET /fem-verifications/{fid}/curves?name=&max_points=500
{"names":["…"],"name":"…","pred":{"x":[…],"y":[…]}|null,"fem":{"x":[…],"y":[…]}|null,"downsampled":true}   // 다운샘플 = §14.7 규칙
// 표(member) GET /fem-verifications/{fid}/table.csv → UTF-8 BOM, name,unit,stat,pred_min,pred_max,fem_min,fem_max,pred_value,fem_value,diff,diff_pct
// 취소(power, 등록자·관리자) POST /fem-verifications/{fid}/cancel → 202 상세. WAITING_PREDICT면 동반 예측 취소, RUNNING이면 FEM_VERIFY 취소. 멱등
// 다시 실행(power) POST /fem-verifications/{fid}/rerun → 201 상세. FAILED·CANCELED만(아니면 409 FEM_VERIFY_NOT_RERUNNABLE).
//   동반 예측 실패면 그 예측 retry, 그 밖은 FEM_VERIFY retry(§21.3.5 재시도 규칙)
```
- 경로 확인: `POST /studies/{id}/paths/inspect`에 `purpose:"FEM_ASSEMBLY"`(power) → `plan_assembly` 요약(위 `assembly` 모양 + `problems`). 허용 루트는 §21.3.3.
- 경로 탐색: `GET /fs/roots?include_spdm=true` → `storage.spdm_roots`마다 `{key:"spdm_<i>", label:"SPDM <i>(읽기 전용)", path}` 추가. `GET /fs/list`는 SPDM 루트 아래도 이름·종류·크기·mtime만 돌려준다(쓰기 없음, 권한 규칙 §12 그대로).
- 오류(한국어):
- 422: `INVALID_PARAMS`(모양), `FEM_VERIFY_INVALID` + `problems[{code,message}]`. code ∈ `SOURCE_NOT_FOUND`·`PREDICT_NOT_SUCCEEDED`·`MESH_MISSING`·`INPUT_MESH_ONLY`·`PREPARED_NOT_SUPPORTED`·`ASSEMBLY_REQUIRED`·`ASSEM_STARTER_COUNT`·`ASSEM_TOO_LARGE`·`ASSEM_TOO_MANY_FILES`·`FILE_NAME_UNSAFE`·`DOE_NOT_READY`·`MESH_TEMPLATE_PLACEHOLDER`·`OPT_DESIGN_UNAVAILABLE`. 경로 오류는 `PATH_*`.
- 409: `HPC_NOT_CONFIGURED`, `TEMPLATE_NOT_CONFIGURED`, `FEATURE_NOT_AVAILABLE`(`fem_verify`), `FINAL_MODEL_REQUIRED`, `FEM_VERIFY_ACTIVE`("같은 예측·같은 조립 원본의 검증이 진행 중입니다"), `FEM_VERIFY_LIMIT`("진행 중인 FEM 검증이 N건입니다(상한 M)"), `FEM_VERIFY_NOT_RERUNNABLE`, `STUDY_ARCHIVED`.
- 404: `FEM_VERIFY_NOT_FOUND`.
- `/status.features.fem_verify` = `fem_verify.enabled` + HPC `configured`. `/status.features.fem_verify_rebuild` = 위 + mesh 템플릿·include TCL(§11.4 `predict_parametric` 중 mesh 조건).
- `JobSummary`·`Job`은 모양 불변. FEM_VERIFY 작업은 `stage_label "④"`, 표시명 "조립 FEM 검증".

#### 21.3.9 종료 훅·알림·감사

- `job_end._side_effects_on_end`에 `fem_verify_on_job_end` 추가(savepoint, 실패는 로그만):
- PREDICT(params `fem_verify_id`) SUCCEEDED → 같은 트랜잭션에서 FEM_VERIFY(QUEUED, created_by = 검증 등록자) 생성, 검증 `RUNNING`·`job_id`. FAILED·INTERRUPTED → 검증 `FAILED` `PREDICT_FAILED`("함께 실행한 예측이 실패했습니다"), CANCELED → `CANCELED`.
- PREDICT 재시도(`on_retry`) → 검증 `predict_job_id` 갱신·`WAITING_PREDICT`.
- FEM_VERIFY SUCCEEDED → 검증 `DONE`·`summary`·`finished_at` + 알림 `FEM_VERIFY_DONE` 1건(등록자) "FEM 검증 FV-003 완료 — 최대 오차 7.2% (MaxStress)"(응답 없음이면 "— 응답 비교 없음"). FAILED·INTERRUPTED → `FAILED`(code·message = 첫 실패 step, 기존 `JOB_FAILED` 알림 유지). CANCELED → `CANCELED`. FEM_VERIFY 재시도 → `job_id` 갱신·`RUNNING`.
- 검증이 이미 종료 상태면 훅은 아무것도 하지 않는다(멱등).
- 감사: 생성 `FEM_VERIFY_CREATE`, 취소 `FEM_VERIFY_CANCEL`, 다시 실행 `FEM_VERIFY_RERUN`(audit action 문자열, 기존 감사 테이블).
- 생성은 Study 행 `SELECT … FOR UPDATE`(D3-25) 안에서 `fv_no` 채번 → 활성 수·중복 검사 → 행 + 작업(동반 PREDICT 또는 FEM_VERIFY) 삽입을 한 트랜잭션으로 한다.

#### 21.3.10 설정(`config/platform.example.yaml` 새 절, 기본값은 스키마 한 곳 `physicsai_core/config/schema_fem_verify.py`)

```yaml
fem_verify:                       # ④ 조립 FEM 검증(phase3 §21 S16)
enabled: true
dir_name: "04_verify"
max_active: 4                   # Study당 진행 중(WAITING_PREDICT·RUNNING) 상한, 1~20
field_map: {}                   # 예측 h3d 결과 이름 → FEM h3d 결과 이름(예: {"CornerStress": "Element Stresses (2D & 3D)"}) — E4-14-F2
legend_subcase: 1               # 범례 min·max 요청 subcase(≥1)
auto_isolate_cushion: true      # mesh_only면 FEM 컨투어를 include의 /PART id로 격리(E4-14-F3)
zero_tol: 1.0e-12
max_assem_files: 500
max_assem_bytes: 2147483648
include_scan_max_bytes: 16777216
max_pred_h3d_copy_bytes: 4294967296
```
검증: field_map 키·값은 §15.3 문자 규칙(64자, `" { } [ ] $ \ ; |`·제어문자 금지), 수치는 범위 검사. `deploy/setup_config.py`는 변경하지 않는다(키가 없으면 스키마 기본값).

#### 21.3.11 화면(필수 UI만, D3-55/56 톤)

- 라우트: `/p/:projectId/s/:studyId/stage/4/verify`(목록, `?new=1&kind=…&…`이면 새 검증 카드) · `/stage/4/verify/:fvId`(상세). `StudyPage`가 `verify`·`fvId`를 허용한다(stage 4만). 경로 표시는 `④ 예측 › FEM 검증 › FV-003`. ④ 입력 방식 줄 오른쪽에 작은 링크 `FEM 검증 목록`.
- **진입 버튼 "FEM 검증"**(`useFemVerifyButton`, 기능 꺼짐이면 비활성 + 툴팁 "해석 연결 안 됨(관리자 설정 필요)"):
- ④ 단일 예측 결과(`predictRun.tsx` — 기존 "PBS 검증 해석"·"검증 해석(SCX)" 버튼을 대체, PredictWorkspace·PreparedPredictCard·PredictRunView 공통) → `kind=predict_job`.
- ④ 일괄 예측 결과 선택 run → `batch_run`.
- ⑤ 결과분석 표 선택 행(예측 출처만, 해석 출처에서는 숨김) → `batch_run`.
- ⑥ 내장 최적화 결과: 최적 설계 카드 → `opt_design best`, 컨투어 비교 카드 → `final_optimum`, "대리모델 예측 최적안(미검증)" → `surrogate_optimum`, 검증 run 표 행 → `run`.
- 이미 이 대상의 검증이 있으면 버튼 옆에 회색 `FV-003 · 완료 · 최대 오차 7.2%` 링크(목록 API 필터로 조회).
- **새 검증 카드**: ① 검증 대상(출처 라벨·템플릿·모델·설계점 표, 예측 상태 문구 "기존 예측 사용 — 10-19 14:02" 또는 "같은 값의 예측이 없어 예측을 먼저 실행합니다") ② 조립 원본 라디오 3개 — `예측 입력 그대로`(조립 상태일 때만 활성, 아니면 회색 "쿠션 메시만 있는 예측입니다") · `① DOE 조립 폴더`(READY DOE 드롭다운 `DOE-001 · MM-DD`) · `직접 지정`(경로 입력 + `찾아보기`(SPDM 루트 포함) + `확인` → "✓ starter X · rad N · inc M · RENUM 있음", 경고는 회색 줄) ③ 고급(접힘): FEM 결과 이름(기본 = 매핑 결과), 격리 부품(자동 목록 표시·편집), 방향, 범례(자동 맞춤 / 고정 min·max), CPU 수 ④ `preview` problems·warnings 회색 줄 + 버튼 `FEM 검증 실행`(PBS면 "FEM 검증 실행(PBS)", scx면 "(SCX)").
- **상세**: 머리 `FV-003 · 상태 · 출처 링크(예측 결과/배치 행/최적화)` + 진행 4단(1 조립 입력 만들기 = FV_PREP~FV_ASSEMBLE, 2 해석 = HPC_SUBMIT~HPC_WAIT, 3 결과 회수 = COLLECT, 4 비교 정리 = 나머지. 동반 예측 대기 중이면 0단 "예측 실행 중"이 앞에 붙음) + scx면 기존 `ScxJobStatus`(확인 필요 배지·조치 3개) + `취소`(진행 중)·`다시 실행`(실패·취소). 탭:
- `응답`: 표 `응답 | 구분(MIN/MAX/판정값) | 예측 | FEM | 차이 | 오차%`, 판정값 행 굵게, 오차 % 절댓값 내림차순 정렬 선택, `CSV 받기`, 경고 회색.
- `커브`: 계열 드롭다운(여러 개일 때), 예측 = 실선, FEM = 점선(범례 2개), 짝 없음 회색 목록, SKIPPED 사유.
- `컨투어`: 두 열 `예측 | FEM`, 방향 버튼 공유, 영상 토글 공유(V3 `MediaVideo`), 범례 한 줄 "같은 범례 0 ~ 312.5 (두 결과 최대·최소)" 또는 `legend_note`, 이미지·영상 받기.
- `입력·경로`: input_dir·starter·조립 원본 경로·스냅숏·원격 폴더·회수 파일 + `경로 복사`.
- **목록**: 표 `FV # · 출처 · 설계점(앞 3개) · 상태 · 최대 오차% · 시작 · 등록자`, 진행 중 5초 폴링, 행 → 상세.
- ⑥ 내장 최적화 설정·결과의 "PBS 검증 해석 안내" 문구는 "FEM 검증 버튼으로 조립 상태 해석과 비교할 수 있습니다"로 바꾼다. 알림 `FEM_VERIFY_DONE` 링크 → 상세.

#### 21.3.12 PREDICT_VERIFY와의 관계(정리)

| 항목 | 결정 |
|---|---|
| 작업 유형·step·API 생성 | 유지(호환). openapi 설명에 "구식 — 화면은 FEM_VERIFY(§21) 사용" 표기 |
| 화면 버튼 | 대체(④ 단일·일괄, ⑥ 안내 모두 "FEM 검증") |
| 기존 기록 | 예측 결과 응답 표의 "PBS 검증" 열은 PREDICT_VERIFY 결과가 있을 때만 계속 표시(PredictResult 무수정) |
| 코드 | HPC 헬퍼를 `_verify_hpc.py`로 공유. PV 골든·문구 불변 |
| 원격 이름 | PV `04_V-NNN`(불변), FV `04_FV-NNN` |

### 21.4 V3 — 영상 저장·표시

#### 21.4.1 현재 코드 근거

- `resources/hyperview/contour_capture.tcl:158` `hwc save animation page "$vid_path"` — 형식 인자 없음. catch가 성공이면 파일 확인 없이 `vid_state 1`.
- `worker/.../capture.py:136-155` — PNG가 있으면 영상 파일이 없거나 0바이트여도 조용히 넘어가고, 경고는 상한 초과(`CAPTURE_VIDEO_TOO_LARGE`)일 때만 낸다.
- HyperView mp4가 H.264·yuv420p가 아니면(예: MPEG-4 Part 2) Chrome·Edge에서 재생되지 않는다. avi는 브라우저가 재생하지 못한다.
- `frontend/src/stages/stage4/ContourMedia.tsx:163-164` `<video>`에 onError·대체 표시가 없다.
- `capture.max_video_bytes` 기본 209715200(200 MiB)은 등록·제공 상한일 뿐이다. 사용자 목표 ≤ 1 MB는 새 `video_target_bytes`로 구분한다.

#### 21.4.2 TCL 변경(동작 추가만)

- `capture_settings.tcl`에 `VID_SCOPE`(page|window, 설정 `capture.video_scope`, 기본 page)를 넣는다. 저장 명령은 `hwc save animation $VID_SCOPE "$vid_path"`.
- 저장 catch가 성공이어도 `file exists` 그리고 `file size > 0`이 아니면 `vid_state 0`, 오류 "video: 파일이 만들어지지 않았습니다(HyperView 성공 보고)", 로그 `ERROR: 동영상 파일 없음 - <경로>`.
- 기존 로그 문구(`SUCCESS: 동영상 저장 완료`, `ERROR: 동영상 저장 실패`)는 그대로 둔다(서버 확인용).

#### 21.4.3 워커(`steps/stage4_predict/capture.py`, 새 `steps/stage4_predict/video_transcode.py`)

- `run_capture(..., extra_meta: dict | None = None)`: artifacts meta = `{"view"} ∪ extra_meta`(V2 `side`·`fv_id`). 반환에 `video_failed:[{view, reason}]`을 추가한다.
- 동영상 판정(save_video일 때 방향마다):
- 파일 없음·0바이트 → 원인 = manifest `error` → (vid_state 1이면) "파일이 만들어지지 않았습니다(HyperView 성공 보고)" → 시간 초과 → "동영상 파일 없음(종료코드 rc)".
- 상한 초과 → 기존 `CAPTURE_VIDEO_TOO_LARGE`(원인에도 기록).
- 실패 방향이 1개 이상이면 작업당 경고 1건 `CAPTURE_VIDEO_FAILED` "동영상 저장 실패 k/N 방향: iso: <원인>; …"(300자). result `media[].video_error`.
- 이미지 판정·`CAPTURE_FAILED` 규칙은 불변.
- 변환(`capture.ffmpeg.exe`가 비어 있지 않을 때, 방향마다):
1. HyperView 산출 `<view>.<ext>`를 `media/raw/<view>.<ext>`로 이동(`_backup`이 아니라 같은 media 폴더 안 하위 폴더, 삭제 없음).
2. 단계표 `ladder`를 차례로 `run_local("video_transcode", {video_in, video_out:<logs/<job>/tmp>/<view>.try<k>.mp4, scale, crf, fps}, cwd=media, allow_nonzero_exit=False, check_log_errors=False)`로 실행(제한기 안, `capture.ffmpeg.timeout_s` 넘으면 종료). 결과가 ≤ `video_target_bytes`인 첫 단계를 고른다.
3. 고른 파일을 `media/<view>.mp4`로 `os.replace`. 모든 단계가 목표를 넘으면 가장 작은 것을 쓰고 경고 `CAPTURE_VIDEO_OVER_TARGET` "영상이 목표 크기(1.0 MB)를 넘습니다: iso 1.8 MB"(작업당 1건).
4. 시도 파일은 작업 임시 폴더(삭제 허용 예외 §8.3)에만 둔다.
5. 변환 실패(rc≠0·출력 없음) → 원본을 그대로 등록(원본 형식이 mp4·gif일 때. avi는 등록하되 `playable=false`) + 경고 `CAPTURE_VIDEO_TRANSCODE_FAILED`(원인).
6. 등록 content_type = `video/mp4`, meta `{transcoded:true, raw_rel, codec:"h264", pix_fmt:"yuv420p", playable:true}`.
- 변환 없음(exe 빈 값): 등록은 기존과 같다. 크기 > target이면 경고 `CAPTURE_VIDEO_OVER_TARGET`. `probe_exe`가 있으면 `run_local("video_probe", …)` 출력(`codec_name=`·`pix_fmt=`)을 meta에 기록한다. mp4인데 h264·yuv420p가 아니면 `playable=false` + 경고 `CAPTURE_VIDEO_NOT_PLAYABLE` "브라우저가 재생하지 못할 수 있는 코덱(<codec>) — ffmpeg 변환을 설정하세요". avi는 항상 `playable=false`, gif는 `playable=true`. probe가 없으면 `playable=null`(avi 제외).

#### 21.4.4 설정(`capture` 절 확장, `schema_capture.py`)

```yaml
capture:
video_ext: "mp4"                # mp4 | gif | avi(allow_avi: true일 때만 — 아니면 config 경고 + 실제 mp4)
allow_avi: false
video_scope: "page"             # page | window — TCL `hwc save animation <scope>`(E4-14-V7)
video_target_bytes: 1048576     # 표시용 영상 목표 크기(1 MiB). 변환이 있으면 이 크기 이하가 될 때까지 단계 재인코딩
max_video_bytes: 209715200      # (기존) 등록·제공 상한
ffmpeg:
  exe: ""                       # ffmpeg 실행 파일 절대경로. 빈 값 = 변환 안 함
  probe_exe: ""                 # ffprobe 절대경로(선택). 빈 값 = 코덱 확인 안 함
  args: ["-hide_banner","-loglevel","error","-y","-i","{video_in}","-an",
         "-vf","scale=trunc(iw*{scale}/2)*2:trunc(ih*{scale}/2)*2,fps={fps}",
         "-c:v","libx264","-preset","veryfast","-crf","{crf}","-pix_fmt","yuv420p","-movflags","+faststart","{video_out}"]
  probe_args: ["-v","error","-select_streams","v:0","-show_entries","stream=codec_name,pix_fmt","-of","default=nw=1","{video_in}"]
  ladder: [{scale: 1.0, crf: 28, fps: 15}, {scale: 0.75, crf: 30, fps: 12}, {scale: 0.5, crf: 32, fps: 10}, {scale: 0.5, crf: 38, fps: 8}]
  timeout_s: 300
```
- `physicsai_core.commands`: 파생 템플릿 `video_transcode = ["{ffmpeg}", *capture.ffmpeg.args]`, `video_probe = ["{ffprobe}", *capture.ffmpeg.probe_args]`. 실행 파일 placeholder `{ffmpeg}`·`{ffprobe}`(= exe 경로), 값 placeholder `{video_in} {video_out} {scale} {crf} {fps}`. `args`에는 `{video_in}`·`{video_out}`이 각 1회 있어야 한다.
- 검증:
- exe·probe_exe: 빈 값 또는 절대경로·공백·메타문자 없음(파일 없음은 config 경고 + `/status.capture.transcode=false`).
- args: 1~64개, 각 ≤ 256자, 제어문자 금지, 허용 placeholder만.
- ladder: 1~8개, scale 0.1~1.0, crf 0~51, fps 1~60.
- video_scope ∈ {page, window}. video_target_bytes 64 KiB~max_video_bytes.
- `video_ext=avi` + `allow_avi=false` → `config.warnings` "avi는 브라우저에서 재생할 수 없어 mp4로 저장합니다(capture.allow_avi)".
- `deploy/setup_config.py`: `capture.ffmpeg` 절이 없을 때만 주석 달린 기본 절을 보충(값 덮어쓰기 없음).
- `/status.capture`에 `{video_target_bytes, transcode: bool, video_ext_effective}` 추가.

#### 21.4.5 API(`GET /jobs/{id}/media`, FV media 공통 `MediaFile`)

- `MediaFile`에 선택 필드 `playable: bool|null`, `codec: str|null`, `transcoded: bool = false` 추가.
- `MediaItem`에 `video_error: str|null` 추가(result `media[].video_error` 또는 capture `failed`에서).
- 기존 클라이언트는 영향이 없다(선택 필드). `/artifacts/{id}/media`는 불변.

#### 21.4.6 프런트

- 새 `components/MediaVideo.tsx` `{file: MediaFile, poster?, label, downloadName}`:
- `content_type`가 `image/gif` → `<img>`.
- `video/x-msvideo` 또는 `playable===false` → 재생 시도 없이 `<p class="muted small">브라우저가 이 형식을 재생하지 못합니다 — <a download>받기</a></p>`.
- 그 밖 → `<video controls preload="metadata">` + `<source>`. `<video onError>`·마지막 `<source onError>`·`loadedmetadata` 전 `error` 이벤트 → 같은 안내로 바꾼다(포스터 이미지는 남김).
- `ContourMedia.tsx`: 영상 칸을 `MediaVideo`로 바꾼다. 영상 버튼이 비활성일 때 `video_error`가 있으면 title·회색 문구 "영상 없음 — <원인>". 문구 상수는 `MEDIA_TEXT.VIDEO_UNPLAYABLE = "브라우저가 이 형식을 재생하지 못합니다 — 받기"`.
- V2 컨투어 비교도 같은 컴포넌트를 쓴다.

#### 21.4.7 서버 확인 항목(사용자 — E4-14-V*, §21.6에 포함)

로그 문구, 파일 존재·크기, ffprobe 코덱, 설정값, 브라우저 네트워크·콘솔, ffmpeg 가용성(libx264), page/window 범위 시험.

### 21.5 시험(V3-S16-*)

| ID | 기준 |
|---|---|
| V3-S16-1 | V1 API 목록: 일괄 하위 제외, 재시도 묶음 최신 1행·`attempts`, `mode`·`state` 필터·422, 커서(`X-Next-Cursor`)로 중복·누락 없음, `input_mode` 없는 옛 작업 = template, prepared 필드(`input_path`·`starter`), `origin`(`fem_verify_id` 있으면 fem_verify), 응답 요약 ≤ 5, PREDICT_VERIFY 요약, 권한(401·member 200), DB 쓰기 0 |
| V3-S16-2 | V1 상세: `paths`(있는 것만, 정리된 폴더 null)·`response_table`·`nearest`·`display`, 404 `JOB_NOT_FOUND`·`NOT_PREDICT_RUN`(일괄 하위·다른 유형), openapi·operationId 스냅샷 |
| V3-S16-3 | V1 화면: 하위 탭 2개·localStorage·기본 탭 규칙(진행 중 → 목록), 목록 열·필터·더 보기·폴링, 행 → `?job=`, `PredictRunView` 입력·경로 카드·경로 복사·기존 결과 카드, 일괄 하위는 `← 일괄 예측 결과`, 목 |
| V3-S16-4 | migration 0013: 테이블·CHECK 4종·인덱스, 활성 인덱스에서 FEM_VERIFY·동반 PREDICT 제외(일반 PREDICT 2개는 여전히 거부), 알림 이벤트, `MIGRATION_HEAD`, downgrade 거부 |
| V3-S16-5 | 출처 해석: predict_job(parametric mesh_only·assembly·일괄 하위·prepared 비배치), batch_run, values(재사용 일치 1e-9·다른 모델 → 동반·`reuse_existing=false`·INPUT 정리됨 → 동반), opt_design(best·final_optimum·surrogate_optimum → values·run, FINAL 없음 `OPT_DESIGN_UNAVAILABLE`), problems 코드 |
| V3-S16-6 | 조립 원본: predict_input 허용/`INPUT_MESH_ONLY`, train_doe READY·`DOE_NOT_READY`·`DOE_PARAM_MISMATCH` 경고, custom(AI 루트·import 루트·SPDM 루트 허용, 밖·`_backup`·링크·공백 거부), starter 0/2개, 크기·개수 한도, csv·기준본·참조 경고(참조 검사 크기 한도 → null), 원본 목록·mtime 불변 |
| V3-S16-7 | API: preview 모양·저장 없음, create 201(동반 → WAITING_PREDICT·동반 PREDICT QUEUED와 params `fem_verify_id`, 아니면 RUNNING·FEM_VERIFY QUEUED), 한 트랜잭션·fv_no 연번, 409(`HPC_NOT_CONFIGURED`·`TEMPLATE_NOT_CONFIGURED`·`FEM_VERIFY_ACTIVE`·`FEM_VERIFY_LIMIT`·`FINAL_MODEL_REQUIRED`), `POST /jobs` FEM_VERIFY 422, PREDICT params `fem_verify_id` 422, 권한(조회 member·생성 power·취소 등록자/관리자), 감사 행 |
| V3-S16-8 | 워커 rebuild 골든: FV_MESH argv `[hw,-clientconfig,hwfepre.dat,-b,-tcl,<tcl>,F/a1/mesh/EPS_mesh_0000.rad,F/a1/mesh/104_replace_node_elem.inc,F/a1/assem/RENUM_INIT.csv]`·cwd `F/a1/mesh`, FV_ASSEMBLE INPUT = 조립 사본 + 새 include(내용 = m_2 산출)·`EPS_mesh*` 없음·starter 1개, `cushion_part_ids`, reuse는 FV_MESH SKIPPED·INPUT = 예측 INPUT 사본, `INPUT_CHANGED`(생성 뒤 원본 변경), 예측 폴더 무변경 |
| V3-S16-9 | HPC: command spec(job_name·input·result 경로·path_map·hpc 덮어쓰기), scx 잡 이름 `04_FV-003_<ts>`·`_2` 접미·SPDM 거부, SUBMISSION_UNKNOWN → WAITING_HPC·자동 재제출 없음·attention·알림, resolve 3종 뒤 상태, 취소(terminate·UNKNOWN 로컬 CANCELED), PREDICT_VERIFY 골든·로그 문구 불변(`_verify_hpc` 분리 회귀) |
| V3-S16-10 | FV_EXTRACT: `H3D_REQUESTS.txt` 골든(FEM datatype = `fem.field` > `field_map` > 원래, `__FV_LEGEND` 줄·이름 충돌 `__FV_LEGEND2`), 예측 RESPONSES 재사용 조건/사본 추출(예측 폴더 쓰기 0)·`PRED_H3D_TOO_LARGE`, MIN·MAX·판정값·`diff_pct`·`zero_tol` null, `FEM_RESPONSE_WHOLE_MODEL`, h3d 2개 → `RESP_H3D_AMBIGUOUS`, 도구 실패 경고 |
| V3-S16-11 | FV_CURVE: 정의 출처 순서(모델 데이터셋 큐레이션 → 최신 CU_T01_CURVES → SKIPPED), T01 0/2개 SKIPPED, `t01_curve_export` argv·cwd, 이름 짝(정확 → 대소문자·공백 무시)·unmatched |
| V3-S16-12 | FV_CAPTURE: 범례 결정(요청 fixed / minmax 합집합 / auto + note), 두 쪽 같은 display·FEM field 매핑·comps(요청 > 자동 > 없음), 출력 폴더 `media/pred`·`media/fem`, artifacts meta `side`·`fv_id`, 예측 원래 media 불변, 실패는 경고·작업 성공 |
| V3-S16-13 | FV_COMPARE: `compare.json`·`responses_fem.csv`·검증 `summary`(수치만, 파일 본문 없음)·`max_abs_diff_pct`·worst |
| V3-S16-14 | 종료 훅: 동반 예측 성공 → FEM_VERIFY 생성(등록자)·RUNNING, 실패 → FAILED `PREDICT_FAILED`, 취소 → CANCELED, 동반 예측 retry → WAITING_PREDICT·predict_job_id 갱신, FEM_VERIFY 성공 → DONE·알림 1건 문구, 실패 → FAILED(`JOB_FAILED` 유지), 멱등(종료된 검증), 동반 예측 알림 억제 |
| V3-S16-15 | 재시도: 실패 step ≤ 6 → from 1·새 시도 `a2`·새 원격 폴더, ≥ 7 → 그 step·같은 시도, `rerun` 분기(동반 예측 실패 → 예측 retry)·409 `FEM_VERIFY_NOT_RERUNNABLE`, `cancel` 멱등(WAITING_PREDICT·RUNNING) |
| V3-S16-16 | 조회 API: 목록 필터(predict_job_id·batch_id·opt_id·status)·커서, 상세 모양(§21.3.8), media(두 쪽·video_error), curves(다운샘플·짝 없음 null), table.csv BOM·헤더, 404 |
| V3-S16-17 | `paths/inspect FEM_ASSEMBLY`·`/fs/roots?include_spdm=true`(SPDM 루트 표시, 미설정이면 없음)·`/fs/list` SPDM 읽기, 쓰기 0 |
| V3-S16-18 | V2 화면: 진입 버튼 5곳(④ 단일·④ 일괄·⑤ 예측 출처 행만·⑥ 최적/마무리/대리 최적/검증 run)·기능 꺼짐 툴팁·기존 검증 링크, 새 검증 카드(조립 라디오 활성 조건·경로 확인 요약·고급·preview problems·body), 상세 진행 단계(동반 0단)·탭 4개·ScxJobStatus·취소/다시 실행, 목록·폴링, 알림 링크, 목 |
| V3-S16-19 | e2e(가짜 도구): mesh_only 템플릿 값 → FEM 검증(values, train_doe 조립) → 동반 예측 → FEM_VERIFY(가짜 PBS command 게이트웨이 in_place, 가짜 hw `minmax`·캡처) → DONE·비교 표·두 쪽 컨투어. assembly 예측 → predict_input FEM 검증. scx 가짜 relay 1회 |
| V3-S16-20 | TCL(V3): `VID_SCOPE` 설정 작성·이스케이프, 저장 성공 보고 + 파일 없음 → video 0·오류 문구(tclsh 흉내 hwc로 실행, tclsh 없으면 문자열 골든) |
| V3-S16-21 | 워커 영상 판정: `CAPTURE_VIDEO_FAILED` 1건·원인 순서(manifest 오류 / 성공 보고 + 파일 없음 / 시간 초과 / 0바이트)·`media[].video_error`, 이미지 규칙 불변, `extra_meta` |
| V3-S16-22 | 변환(가짜 ffmpeg `fake_ffmpeg`: 단계별 크기 모드·실패 모드, 가짜 ffprobe): 단계 선택(첫 ≤ target)·전부 초과 → 최소 + `CAPTURE_VIDEO_OVER_TARGET`, raw 보존·시도 파일은 작업 임시 폴더만, 실패 → 원본 등록 + `CAPTURE_VIDEO_TRANSCODE_FAILED`, argv(`shell=False`, placeholder 치환)·시간 한도, exe 빈 값 → 건너뜀, probe meta·`playable`·`CAPTURE_VIDEO_NOT_PLAYABLE` |
| V3-S16-23 | 설정: ffmpeg 절 검증(경로·args placeholder·ladder 범위·target), avi + allow_avi=false → 경고·실제 mp4, video_scope, `/status.capture` 새 필드, setup_config 보충만 |
| V3-S16-24 | media API: `playable`·`codec`·`transcoded`·`video_error` 필드, 기존 응답 호환 |
| V3-S16-25 | 프런트 `MediaVideo`: gif → img, avi·playable false → 안내 + 받기(video 요소 없음), video error 이벤트(video·source) → 안내 전환, 포스터 유지, ContourMedia `video_error` 문구 |
| V3-S16-26 | 회귀: `scripts/test-all` 전체, V3-S6·S9·S10·S11·S12·S13·S14·S15 시험 무수정 통과(메시지·골든 변경 없음), 프런트 빌드본 최신, migration head 0013 |

### 21.6 서버 확인(사용자 — E4-14-*)

| ID | 확인 | 방법 | 다르면 |
|---|---|---|---|
| E4-14-H1 | 실행 목록에 과거 단일 예측(옛 작업 포함)이 나오고 일괄 하위는 없음. 행을 고르면 컨투어·커브·응답·입력값·경로가 보임 | ④ 템플릿 값 입력 → 실행 목록 | 변경 메모 |
| E4-14-F1 | mesh_only 예측 → ① DOE 조립으로 FEM 검증: `04_verify\FV-001\a1\input`에 starter + 새 `104_replace_node_elem.inc`, `EPS_mesh*` 없음. starter가 include를 참조(경고 없음) | 폴더 확인 + 해석 로그 | `predict.mesh_include_name`·조립 폴더 |
| E4-14-F2 | FEM h3d 결과 이름(예측 `CornerStress`에 해당하는 이름)·성분 | HyperView에서 FEM h3d 열어 결과 목록 확인 | `fem_verify.field_map` |
| E4-14-F3 | 캡처 TCL `hwc show component "<id>"`가 /PART id로 격리되는지(이름이어야 하는지) | FEM 컨투어 FEM 쪽 이미지 | `auto_isolate_cushion=false` 또는 comps 이름 입력 |
| E4-14-F4 | 범례 min·max: FEM h3d에서 `__FV_LEGEND` subcase 1이 값을 내는지 | `F/a1/result/RESPONSES.txt` | `fem_verify.legend_subcase` |
| E4-14-F5 | FEM T01 커브 이름이 예측 curve.json 계열 이름과 맞는지 | 상세 커브 탭 unmatched 목록 | 미결 3 |
| E4-14-F6 | SCX: 잡 폴더 `04_FV-001_<ts>`, 업로드 파일(rad·inc·csv), 회수 h3d·T01 | SCX 화면·드라이브 | `hpc.scx.*` |
| E4-14-F7 | custom 조립을 SPDM 경로로 지정: 원본 폴더 mtime·파일 수 불변, 스냅숏만 생김 | 탐색기 | — |
| E4-14-F8 | 응답 MIN·MAX 비교값이 상식 범위(조립 전체 값인지 확인) | 응답 탭 | 미결 1 |
| E4-14-V1 | 작업 로그에서 방향마다 `SUCCESS: 동영상 저장 완료` / `ERROR: 동영상 저장 실패` / `ERROR: 동영상 파일 없음` 중 무엇이 찍히는지, `capture_result.txt` VIEW 줄 video 값 | 작업 로그·`RESULT\media\capture_result.txt` | — |
| E4-14-V2 | `RESULT\media\iso.mp4`(또는 설정 확장자) 존재·크기 | 탐색기 | — |
| E4-14-V3 | 코덱: `ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt,width,height -of default=nw=1 iso.mp4` → h264·yuv420p인지 | 서버 PC | ffmpeg 변환 설정 |
| E4-14-V4 | 설정값 `capture.video`·`video_ext`·`max_video_bytes`(200 MiB 기본)·`video_target_bytes` | `/status`·platform.yaml | — |
| E4-14-V5 | 브라우저: 네트워크 `/artifacts/<id>/media` 206·Content-Type, 콘솔 media error(code 4 = 형식 미지원) | 개발자 도구 | — |
| E4-14-V6 | ffmpeg 가용성: `ffmpeg -hide_banner -encoders`에 libx264(없으면 `h264_mf`·`libopenh264`로 args 교체), 수동 변환 1회 크기 ≤ 1 MB 여부 | 서버 PC | `capture.ffmpeg.args`·`ladder` |
| E4-14-V7 | `hwc save animation window` 대 `page` — 배치에서 어느 쪽이 파일을 만드는지 | HyperView Tcl 콘솔·배치 1회 | `capture.video_scope` |

### 21.7 파일 소유·순서(Impl-Backend ↔ Impl-Frontend 겹침 없음)

**Impl-Backend**(트랙별. 같은 역할 안의 공유 파일은 아래 순서로 병합하고 다시 생성)

| 트랙 | 파일 |
|---|---|
| BE-V3 | `resources/hyperview/contour_capture.tcl`, `backend/physicsai_core/config/schema_capture.py`, `backend/physicsai_core/stage4_predict/contour_capture.py`(VID_SCOPE·effective ext), `backend/physicsai_core/commands.py`(`video_transcode`·`video_probe`·placeholder), `backend/physicsai_core/config/validate.py`(capture 경고 — 필요 시), `worker/physicsai_worker/steps/stage4_predict/capture.py`, 신규 `worker/physicsai_worker/steps/stage4_predict/video_transcode.py`, `backend/physicsai_api/services/contour_capture.py`, `backend/physicsai_api/schemas/contour_capture.py`, `backend/physicsai_api/schemas/shell.py`·`services/system.py`(`/status.capture`), `config/platform.example.yaml`(capture 절), `deploy/setup_config.py`(capture.ffmpeg 보충), 신규 `backend/tests/fake_tools/{fake_ffmpeg,fake_ffprobe}`·`fake_hw_capture.py`(no_file 모드), 시험 V3-S16-20~24 |
| BE-V1 | `backend/physicsai_api/routers/jobs.py`(라우트 2개), 신규 `backend/physicsai_api/services/predict_runs.py`, 신규 `backend/physicsai_api/schemas/predict_runs.py`(라우터가 직접 import — `schemas/__init__` 무수정), 신규 `backend/tests/test_predict_runs_api.py`, 시험 V3-S16-1·2 |
| BE-V2 P0 | 신규 `migrations/versions/0013_fem_verify.py`, 신규 `backend/physicsai_core/db/tables/fem_verify.py`, `db/tables/__init__.py`, `db/tables/execution.py`(알림 CHECK), `db/__init__.py`(`MIGRATION_HEAD`), `backend/physicsai_core/job_types.py`, 신규 `db/repositories/fem_verifications.py`, 신규 `config/schema_fem_verify.py`, `config/schema.py`(절 등록), `features.py`, `config/platform.example.yaml`(fem_verify 절 — BE-V3 뒤), 신규 `stage4_predict/fem_assembly.py`, `packages/simdash_adapters/src/simdash_adapters/hpc/scx_naming.py`(+ 시험), 시험 V3-S16-4·6(함수) |
| BE-V2 P1(API) | 신규 `backend/physicsai_api/routers/fem_verify.py`·`services/fem_verify.py`·`services/fem_verify_sources.py`·`schemas/fem_verify.py`, `backend/physicsai_api/main.py`(라우터 등록), `schemas/jobs.py`(job type 목록), `services/job_params/__init__.py`·`stage4_predict.py`(FEM_VERIFY 422·`fem_verify_id` 422·on_retry), `services/jobs.py`(재시도 규칙), `services/common.py`(can_retry), `services/path_inspect.py`(FEM_ASSEMBLY), `schemas/fs.py`·`routers/fs.py`·`services/fs_browse.py`(include_spdm), `db/repositories/job_end.py`·`notifications.py`(훅·억제), 시험 V3-S16-5·7·14~17 |
| BE-V2 P2(워커) | 신규 `worker/physicsai_worker/steps/stage4_predict/{fem_verify.py, fem_compare.py, _verify_hpc.py}`, `verify.py`(헬퍼 호출로 축소), `steps/stage4_predict/__init__.py`·`steps/__init__.py`(HANDLERS), `steps/response_tcl.py`(datatype 덮어쓰기 인자 — 필요 시), `worker/tests/e2e/`(V3-S16-19), 시험 V3-S16-8~13 |
| 생성·스냅숏 | `backend/openapi.json`, `backend/tests/data/operation_ids.txt`, `backend/tests/common/test_openapi.py` — 병합 순서 V3 → V1 → V2마다 다시 생성 |

**Impl-Frontend**

| 트랙 | 파일 |
|---|---|
| FE-V3 | 신규 `frontend/src/components/MediaVideo.tsx`, `frontend/src/stages/stage4/ContourMedia.tsx`, `frontend/src/api/types.ts`(MediaFile·MediaItem 필드), `frontend/src/mock/capture.ts`, 시험 `__tests__/mediaVideo.test.tsx`(+ 기존 contour 시험 갱신) |
| FE-V1 | `frontend/src/stages/stage4/Stage4.tsx`(OpenedJob → PredictRunView, 하위 탭), 신규 `stages/stage4/history/{SingleTabs.tsx, PredictRunList.tsx, PredictRunView.tsx, RunInputsCard.tsx, runListText.ts}`, 신규 `api/predictRuns.ts`, 신규 `mock/predictRuns.ts`, `mock/server.ts`(등록 1줄 — V1 먼저), 시험 `__tests__/stage4History.test.tsx` |
| FE-V2 | `app/App.tsx`, `pages/StudyPage.tsx`, 신규 `stages/stage4/verify/{VerifyList.tsx, VerifyNew.tsx, VerifyDetail.tsx, AssemblySourcePicker.tsx, ResponseCompareTable.tsx, CurveCompare.tsx, ContourCompare.tsx, useFemVerifyButton.tsx, verifyRules.ts}`, 신규 `api/femVerify.ts`, 신규 `mock/femVerify.ts`, `mock/server.ts`(V1 뒤 1줄), `stages/stage4/predictRun.tsx`, `stages/stage4/InputModeTabs.tsx`(목록 링크), `stages/stage4/batch/BatchResult.tsx`, `stages/stageAnalysis/AnalysisTable.tsx`, `stages/stage5/surrogate/{ResultCards.tsx, SurrogateSetup.tsx}`, `hooks/useOpenJob.ts`, `lib/format.ts`(FEM_VERIFY 라벨), `components/PathPickerDialog.tsx`(include_spdm), 시험 `__tests__/femVerify*.test.tsx` + 버튼 문구가 바뀐 `stage4.test.tsx`·`stage4Prepared.test.tsx`·`scx.test.tsx`·`surrogate.test.tsx`·`permissions.test.tsx` |
| 생성 | `frontend/src/api/generated/schema.d.ts`(`npm run gen:api`, Backend 병합마다), `frontend-dist/**`(`scripts/build-frontend-dist`, 프런트 커밋에 함께) |

**순서**
1. Plan: 이 문서 커밋.
2. 병렬: BE-V3 · BE-V1 · BE-V2 P0 / FE-V3 · FE-V1(목 라우트로 먼저).
3. BE-V2 P1(P0 뒤). BE-V2 P2(P0 뒤 + **BE-V3 병합 뒤** — `run_capture(extra_meta)`·변환 사용). FE-V2(FE-V1 병합 뒤, 목으로 시작).
4. 병합 순서 V3 → V1 → V2. 매번 openapi → `gen:api` → `frontend-dist` 재생성.
5. Verifier: V3-S16-1~26 + 회귀. Plan: phase3.md 이관, `docs/architecture.md`(04_verify·fem_verify 모듈·migration 0013), `docs/e2e-checklist.md`(E4-14), 관리자 매뉴얼(`fem_verify`·`capture.ffmpeg`·avi).

### 21.8 리스크

- **필드 이름 불일치**(예측 h3d 대 Radioss h3d): 매핑이 틀리면 FEM 응답·컨투어가 비어 있다. → `field_map`·요청 `fem.field`로 대응하고, NO_VALUE는 경고로 보여 준다(E4-14-F2).
- **mesh_only 비교의 의미**: 예측은 쿠션 단독, FEM은 조립 전체다. 응답 MinMax TCL은 부품 한정이 없어 전체 모델 값이 될 수 있다(`FEM_RESPONSE_WHOLE_MODEL`). 컨투어는 부품 격리로 보완한다(E4-14-F3).
- **커브 정의 추적**: 모델 → 데이터셋 → 큐레이션 연결이 params 계산이라 끊길 수 있다. 그때는 최신 T01 큐레이션 정의로 대신하고, 이름이 맞지 않으면 unmatched로 보인다.
- **해석 비용·대기**: FEM 1건이 수 시간 걸리고 Study당 4건까지 동시에 돈다. HPC 대기는 슬롯을 잡지 않는다. 후처리 실패는 해석을 다시 하지 않고 재시도한다(F10).
- **예측 h3d 사본**: 응답 재추출 때 수백 MB를 복사할 수 있다(상한 설정, 기존 RESPONSES 재사용 우선).
- **SPDM 조립 원본**: 스냅숏 복사 중 원본 교체(TOCTOU) — §6.11 규칙(열린 파일 대조)을 재사용한다.
- **ffmpeg 배포·라이선스**: libx264가 없는 빌드가 있다(E4-14-V6). 플랫폼은 번들하지 않고 경로만 설정한다. 변환이 없으면 1 MB 목표는 경고만 낸다.
- **번호 체계**: 원격 `04_V-NNN`(PV)과 `04_FV-NNN`(FV)이 공존한다. 화면 문구는 "FEM 검증"으로 통일한다.
- **버튼 문구 변경**으로 기존 프런트 시험·e2e 문구 수정이 필요하다(FE-V2 목록에 포함).

### 21.9 미결(사용자 확인 대상)

1. FEM 응답을 쿠션 부품으로만 한정할지: MinMax TCL에 부품 집합 인자를 추가(원본 TCL 수정 필요)할지, 전체 모델 값 + 경고로 둘지(현 계약).
2. `fem_verify.field_map` 기본값: 서버 확인(E4-14-F2) 뒤 예시 설정에 실제 이름을 넣을지.
3. 커브 이름 대응이 맞지 않을 때(E4-14-F5) 수동 매핑 UI를 둘지(현 계약은 unmatched 표시만).
4. 여러 설계점(파레토·검증 run 여러 개)을 한 번에 검증 요청하는 "일괄 FEM 검증"(현 계약은 1건씩, 동시 4건).
5. PREDICT_VERIFY 작업 유형 폐지 시점(현 계약은 유지·화면만 대체).
6. ffmpeg를 서버 표준 도구로 둘지(관리자 설치) — 없으면 영상은 원본 형식 그대로.
7. `capture.video_scope` 기본값(page 유지 대 window) — E4-14-V7 결과로 결정.
8. 조립 원본 `custom`에 SPDM을 허용한 것(읽기·스냅숏 복사만)이 사내 정책에 맞는지.
9. `04_verify/**`를 S3 정리 범주에 넣을지(현 계약은 크기만 표시, §14.11 R-2와 같은 취급).

## 변경 메모(이 문서분 — phase3.md 변경 메모 목록으로 옮김)

- **D3-64 (사용자 VOC 2026-10-19, S16 — Plan)**: §21.
1. V1 ④ 단일 예측 실행 목록: 새 DB 없이 PREDICT 작업(params·result)으로 `GET /studies/{id}/predict-runs`·`GET /predict-runs/{job_id}`(라우트는 `routers/jobs.py`). 일괄 하위 제외, 재시도 묶음은 최신 1행. 화면은 ④ 템플릿·준비된 입력에 하위 탭 `새 예측 | 실행 목록`, 선택 = `?job=` 화면 확장(`PredictRunView`: 입력·경로 카드 + 기존 결과 카드).
2. V2 조립 FEM 검증: 새 job_type `FEM_VERIFY`(FV_PREP·FV_MESH·FV_ASSEMBLE·HPC_SUBMIT·HPC_WAIT·COLLECT·FV_EXTRACT·FV_CURVE·FV_CAPTURE·FV_COMPARE). 메시 교체는 기존 m_2·`assemble_into` 재사용, 제출은 기존 게이트웨이(PBS·SCX, SUBMISSION_UNKNOWN 규칙 그대로, 잡 폴더 `04_FV-NNN_<ts>`). 출처 4종(예측 작업·배치 run·템플릿 값·내장 최적화 설계점). 같은 설계점 예측이 없으면 동반 PREDICT + 종료 훅 연쇄. 조립 원본 3종(예측 입력 그대로·① DOE 조립 폴더·직접 지정(허용 루트·SPDM 읽기, 스냅숏 복사)). 비교 = 응답 MIN/MAX·오차%, T01 커브 겹쳐보기, 컨투어 두 쪽 같은 범례(MinMax TCL `__FV_LEGEND`). FEM 필드 이름 매핑 설정 `fem_verify.field_map`. 재시도는 해석 전 실패면 처음부터(새 시도), 후처리 실패면 그 step부터.
3. DB migration `0013_fem_verify`: `fem_verifications`, 활성 유일 인덱스에서 FEM_VERIFY·동반 PREDICT 제외(Study당 동시 `max_active` 4), 알림 `FEM_VERIFY_DONE`.
4. PREDICT_VERIFY는 작업 유형·API·기록을 유지하고 화면 버튼만 "FEM 검증"으로 대체. HPC 헬퍼를 `_verify_hpc.py`로 공유(동작 불변).
5. V3 영상: TCL이 저장 후 파일 존재·크기를 확인(`VID_SCOPE` page|window). 워커 경고 `CAPTURE_VIDEO_FAILED`(원인)·`video_error`. 선택적 ffmpeg 변환(`capture.ffmpeg.exe·args·ladder`, H.264·yuv420p·faststart, 목표 `video_target_bytes` 1 MiB까지 단계 재인코딩, 원본 `media/raw/` 보존, 시도 파일은 작업 임시 폴더). ffprobe로 `playable`. avi는 `allow_avi=false`면 경고 + mp4 저장. 프런트 `MediaVideo`(재생 실패 → "브라우저가 이 형식을 재생하지 못합니다 — 받기", gif → img).
6. 시험 V3-S16-1~26, 서버 확인 E4-14-H1·F1~F8·V1~V7. 파일 소유 §21.7(병합 순서 V3 → V1 → V2, BE-V2 워커는 BE-V3 뒤).

### Critical Files for Implementation
- /home/claude/physicsai-platform/worker/physicsai_worker/steps/stage4_predict/verify.py
- /home/claude/physicsai-platform/worker/physicsai_worker/steps/stage4_predict/predict_inputs.py
- /home/claude/physicsai-platform/worker/physicsai_worker/steps/stage4_predict/capture.py
- /home/claude/physicsai-platform/resources/hyperview/contour_capture.tcl
- /home/claude/physicsai-platform/frontend/src/stages/stage4/ContourMedia.tsx
- /home/claude/physicsai-platform/backend/physicsai_api/services/job_params/stage4_predict.py
- /home/claude/physicsai-platform/backend/physicsai_core/db/repositories/job_end.py- **D3-64 구현 메모 (2026-10-19, Verifier 판정 반영)**: TCL은 VID_SCOPE 값이 있을 때만 page/window 분기(기존 골든 유지). 영상 상한 초과는 video_error + 기존 `CAPTURE_VIDEO_TOO_LARGE`로만(CAPTURE_VIDEO_FAILED 건수 제외). `FvCompareRow`에 min/max_diff(_pct) 추가, 커브 짝은 `compare.curve.pairs`. 목록 밖 수정: core/fs_browse.py(SPDM 목록·check_spdm_dir), schemas/studies.py(FEM_ASSEMBLY), step_process.py(파생 영상 템플릿), config/loader.py(capture 경고), schemas/jobs.py(PREDICT_VERIFY 구식 표기), study_job.py(활성 인덱스). 후속(minor): 조립 파일 이름 Windows 예약어 검사, reuse 모드 verify.json sha256, 동반 예측 출처 중복 검사·FEM_VERIFY retry 시 max_active 재검사, 옛 PREDICT_VERIFY SCX 확인 필요 조치 UI 복구.
