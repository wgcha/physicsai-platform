# 계약: S19 후속 — GPU 조회 실패 대응·일괄 예측 GPU 동시 예측·⑤ perf 서버 계산 — phase3 §24

> 이 문서는 phase3.md §24와 변경 메모 D3-67입니다. s15~s18과 같은 사정으로 별도 파일(`docs/contracts/s19_followup.md`)로 두며, 이번 순서의 문서 이관(D)에서 phase3.md 본문과 변경 메모 목록으로 옮깁니다. 절 번호·용어·원칙은 phase3.md §11.5(prepared)·§14.5(④ B·`run_parallel`·종료 훅)·D3-37(예측 성공 = h3d)·D3-45(GPU 조회 탐색)·D3-53(그룹 메모리 판정), [s16_voc.md](s16_voc.md) §21(실행 목록 V1·FEM 검증), [s17_multiobj.md](s17_multiobj.md) §22(성능 `perf:`·`performance.perf_value`)를 따릅니다.
>
> 기준선은 `claude/phase3` 93ebf34(S18, migration head `0015_doe_platform_gen`)입니다. **이번 문서는 migration이 없습니다**(0016은 다음 계약에 남깁니다).

## 24. S19 후속 (사용자 승인 2026-10-19, D3-67)

사용자 승인 항목(2026-10-19) 가운데 계약이 필요한 3건입니다.
- (1) GPU 조회 실패 대응
- (2) ④ 일괄 예측의 예측 단계 동시 실행
- (3) ⑤ `perf:` 지표 서버 계산

계약 없이 고치는 승인 항목은 S16 minor 4건, 문구·시험·그림 정리, 300줄 초과 파일 분할과 `batch_matrix`의 sampling 이동, 문서 이관입니다. 이들은 §24.11 순서·소유 표에만 넣어 충돌을 막습니다.

1·2·3차 원칙(제한기, `shell=False`, 설정만, AI 루트만, `_backup`, 한국어, 필수 UI, DB에는 수치·상태만, 원본 pyd를 플랫폼 프로세스에서 import 금지)은 그대로입니다. **단일 슬롯 FIFO 원칙은 §24.4.2의 레인 예외 하나만 더합니다**(§24.2 Q3).

### 24.1 범위 / 비범위

| 범위 | 비범위(후속) |
|---|---|
| GPU 조회 제한 시간 설정화, 실패 원인을 칩 툴팁·서랍에 표시, 진단 로그(전이 때만), 연속 실패 시 조회 간격 늘리기 | GPU 여러 장 분산(레인은 `gpu_index` 1장만 봅니다), MIG |
| 같은 배치 하위 PREDICT를 GPU 메모리에 따라 최대 N개 동시 실행(GPU 레인) | 단일 PREDICT·FEM_VERIFY 동반 PREDICT·EVALUATE 등 다른 GPU 작업의 동시 실행 |
| 실측 GPU 메모리 기록(`result.gpu`), 메모리 부족 시 대기, 조회 실패 시 동시 1 폴백, OOM 자동 1회 단독 재실행 | 라이선스 자동 감지, 워커 여러 대(다른 호스트)의 레인 협조 |
| design-map `perf:` 지표·값·사유(SPEC_CHANGED) 서버 계산, 프런트 계산 제거 | SO_COLLECT의 옛 run 결과 표 대체(미결 3) |

### 24.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| Q1 | GPU 조회는 새 `worker/physicsai_worker/gpu_monitor.py` `GpuMonitor` 스레드가 맡습니다. 하트비트·레인·환경 점검은 이 캐시를 읽습니다. 환경 점검 `gpu.detect`는 지금처럼 직접 조회하되 같은 제한 시간을 씁니다. | 제한 시간이 15초면 하트비트 스레드가 막혀 온라인 판정(3×10초)이 흔들립니다. 레인은 2초 간격 표본이 필요합니다. |
| Q2 | API는 기존 `gpu_status`·`gpu_message`를 재사용합니다. 추가 필드는 `gpu_fail_streak`·`gpu_sampled_at`·`gpu_next_query_at`·`gpu_lane` 4개(모두 선택)입니다. | 사용자 승인: 기존 필드 재사용. 툴팁에 "연속 N회·다음 조회 시각"이 필요합니다. |
| Q3 | ④ 동시 예측 = **(b) GPU 레인**(§24.4.1 비교). 원칙 예외는 "대기열 1번이 실행 중인 배치와 같은 배치의 하위 PREDICT이면 슬롯 점유 중에도 동반 실행" 하나입니다. | 하위 PREDICT 작업 단위(§14.5 K4)를 유지하는 유일한 안입니다. FIFO 순서는 그대로입니다(대기열 1번만 동반). |
| Q4 | 레인이 실행 중이면 워커의 슬롯 스레드는 claim하지 않습니다(**배수**). DB `claim_slot`도 "RUNNING SLOT 작업이 있으면 같은 배치 하위만" 받습니다. | 학습·입력 생성 등 무거운 작업이 동반 예측과 겹치지 않게 합니다. |
| Q5 | 동시 실행 판단은 두 문입니다. (가) **동반 claim 문** = GPU 표본 정상 + 빈 메모리 − 예약 ≥ 예상 + 여유. (나) **EDSPY 입장 문** = 다른 레인 작업이 GPU 사용 구간에 없거나 (가)와 같은 조건(자기 제외). | 리더는 claim 문을 거치지 않고, 표본이 오래될 수도 있습니다. EDSPY 직전에 다시 확인해야 메모리가 겹치지 않습니다. 단독이면 항상 입장해 진행을 보장합니다. |
| Q6 | 예상 메모리 = 같은 배치 하위의 실측 최대 → 없으면 같은 Study·같은 모델의 최근 20개 PREDICT 실측 최대 → 없으면 `gpu_estimate_default_mb`(6144). 실측은 `nvidia-smi --query-compute-apps=pid,used_memory`로 내 프로세스 트리를 합산하고, 안 되면(Windows WDDM `[N/A]`) 단독 구간의 전체 사용량 차분을 씁니다. | 사용자 지정 방식입니다. 동시 구간의 차분은 귀속할 수 없어 기록하지 않습니다. |
| Q7 | GPU 조회가 실패하거나 표본이 오래되면(3×`gpu_poll_s` 초과) 동반 claim을 하지 않습니다. 이미 실행 중인 레인 작업의 EDSPY는 단독으로만 입장합니다(= GPU 동시 1). | 사용자 승인: 조회 실패 시 동시 1 폴백. |
| Q8 | OOM = EDSPY 결과 h3d가 없고, 종료코드가 `oom_exit_codes`에 있거나 로그 줄이 `oom_patterns`에 맞는 경우입니다. 그 run의 EDSPY 구간에 다른 레인 작업이 GPU를 쓰고 있었으면 **같은 작업 안에서 단독 입장 후 EDSPY를 1회 다시 실행**합니다. 그 세션은 SINGLE로 전환합니다. | 작업 id가 그대로라 `predict_job_id`·재시도 체인·배치 훅이 바뀌지 않습니다. 같은 배치에서 OOM이 반복되지 않게 합니다. h3d가 있으면 D3-37대로 성공입니다. |
| Q9 | 제한기: 레인 세션마다 `limiter.open_group(limits, size=N)` 그룹 1개를 엽니다(Windows Job Object 1개, POSIX 프로세스별 메모리/N). 레인 작업의 모든 LOCAL 프로세스가 여기에 들어가고, 메모리 한도 판정은 D3-53 구간 판정을 씁니다. | §14.5 `run_parallel` 규칙과 같습니다(작업 1개분 한도를 나눠 씀). |
| Q10 | 레인이 꺼진 상태(`predict_parallel_max` = 1)는 현재 동작과 바이트 단위로 같습니다(세션 없음, 프로세스마다 자기 Job). | 회귀 0, 서버에서 즉시 끌 수 있습니다. |
| Q11 | design-map `perf:`는 서버가 `performance.perf_value`로 계산합니다. RESPONSES.txt가 없는 옛 추출 run(H3D `NOT_EXTRACTED`)만 결과 표 값으로 대체합니다. | 대리모델·미리보기와 같은 함수를 씁니다. SPEC_CHANGED는 서버만 감지할 수 있습니다. 옛 배치의 ⑤ 화면 값이 바뀌지 않습니다. |
| Q12 | 지표 순서는 curve → resp → tbl → **perf(끝)**이고, perf는 값 있는 run이 1개 이상일 때만 목록에 둡니다. | 현재 프런트 합성 결과와 같아 저장된 선택(`readPrefs`)·기본 지표가 바뀌지 않습니다. |
| Q13 | migration은 없습니다. GPU 실측은 하위 PREDICT `jobs.result.gpu`(JSON 수치), 레인 상태는 워커 메모리, 조회는 `predict_batch_runs.predict_job_id` → `jobs`입니다. | DB에는 수치·상태만 둡니다. 기존 인덱스(PK·`ix_jobs_study_created`)로 충분합니다. |
| Q14 | 새 실패 코드는 `GPU_OOM`, 새 경고는 `GPU_OOM_RETRIED`입니다. 그 밖의 코드는 기존 그대로입니다. | 최소 변경입니다. |

### 24.3 (1) GPU 조회 실패 대응

**제한 시간**:
- `resources.query_gpu_status(..., timeout_s=)` 인자를 추가하고, 기본은 `settings.worker.gpu_query_timeout_s`(15)입니다. `GPU_TIMEOUT_S` 상수는 함수 기본값으로만 남깁니다.
- 시간 초과 문구는 `nvidia-smi 응답 시간 초과({n}초): {exe}`이고, n은 설정값입니다.
- 환경 점검 `env_check.gpu_item`도 같은 설정을 씁니다.

**`GpuMonitor`(신규, 워커 스레드 `gpu`)**:
- `poll_once()`: 요약 조회(기존 `GPU_QUERY_ARGS`)를 합니다. 레인 활성 + 직전 OK이면 `predict_batch.gpu_apps_query_args`로 프로세스별 조회도 합니다(같은 실행 파일, 같은 제한 시간, `shell=False`, 제한기 밖).
- 결과 캐시 `{gpus, status, message, exe, sampled_at, fail_streak, next_query_at, apps: {pid: mb}|None}`를 잠금으로 보호합니다. 프로세스별 값이 `[N/A]`이거나 파싱 실패면 `apps = None`입니다.
- 간격: 레인 활성이고 OK면 `gpu_poll_s`, 아니면 `worker.resource_sample_interval_s`(= base)입니다.
- 연속 실패 k회의 간격: k < `gpu_backoff_after`면 base, 아니면 `min(gpu_backoff_max_s, base × 2^(k − after + 1))`입니다. `gpu_backoff_max_s` = 0이면 지연하지 않습니다. 성공하면 k = 0입니다.
- 예: base 10, after 3이면 10·10·20·40·80·160·300…입니다.
- `heartbeat_once`는 `resources.sample(...)` 대신 `monitor.snapshot()`의 GPU 부분으로 표본을 만들고 nvidia-smi를 실행하지 않습니다.
- `sample()` 결과 키: `gpu`, `gpu_status`, `gpu_message`(OK = 실행 파일 경로, 기존과 같음), `gpu_fail_streak`, `gpu_sampled_at`, `gpu_next_query_at`(지연 중일 때만, 아니면 null), `gpu_lane`(§24.4.8).

**진단 로그(워커 로그 `physicsai_worker`, 상태 전이 때만 1줄)**:

| 전이 | 수준 | 문구 |
|---|---|---|
| OK(또는 시작) → ERROR | WARNING | `GPU 조회 실패(ERROR): <message> — 회복될 때까지 같은 실패는 기록하지 않습니다` |
| 시작 → NOT_FOUND | INFO | `GPU 조회 불가(NOT_FOUND): <message>` |
| 실패 중 종류 변경(NOT_FOUND ↔ ERROR) | WARNING | `GPU 조회 상태 변경(<이전> → <지금>): <message>` |
| k = after가 되는 순간 | WARNING | `GPU 조회 연속 <k>회 실패 — 조회 간격을 늘립니다(최대 <max>초)` |
| 실패 → OK | INFO | `GPU 조회 회복: <GPU 이름> <n>개(실패 <k>회, <경과>)` |

같은 상태가 반복되면 기록하지 않습니다(작업 로그·DB에도 쓰지 않음).

**화면(Impl-Frontend)**:
- 상단 자원 칩: `gpu_status`가 ERROR·NOT_FOUND이면 `title`을 다음처럼 바꿉니다. OK이면 기존 `워커 자원 열기`입니다. 칩 문구(`GPU —`)는 그대로입니다.
  - `GPU 조회 실패 — <gpu_message>`
  - streak ≥ 2이면 `(연속 N회 · 다음 조회 HH:mm:ss)`를 덧붙이고, 다음 조회 시각이 없으면 `· …`를 뺍니다.
  - NOT_FOUND의 앞말은 `GPU 없음 — `입니다.
- 서랍 `WorkerResourcePanel`: `gpuNoneText` 아래에 회색 줄 2개를 **보이게** 둡니다(지금은 title에만 있음).
  - `data-testid="gpu-message"`: gpu_message
  - streak ≥ 2일 때: `연속 N회 실패 · 다음 조회 HH:mm:ss`
- 순수 함수 `gpuFailTip(r)`를 `shell/gpuText.ts`(신규)에 둡니다.

### 24.4 (2) ④ 일괄 예측 GPU 동시 예측

#### 24.4.1 설계 비교

| 관점 | (a) 하위 PREDICT를 새 step `BP_PREDICT`로 묶음(`run_parallel` 안 EDSPY→RESPONSE_EXTRACT→CONTOUR_CAPTURE 체인) | **(b) GPU 레인(채택)** |
|---|---|---|
| §14.5 하위 PREDICT·`predict_job_id` | run별 작업이 사라집니다. 결과 화면·`/jobs/{id}/media`·curve.json 위치(`locate_run_files(job)`)·input.zip·오류 묶음을 run 차원으로 다시 쓰거나 가짜 작업 행이 필요합니다. | 그대로(작업 1개 = run 1개) |
| job_end 배치 훅·`PREDICT_BATCH_DONE` | `on_child_end`·`mark_done_if_complete`·SO `on_batch_done` 연쇄를 부모 기준으로 재작성해야 합니다. | 그대로. 동시 종료는 배치 행 `FOR UPDATE`로 직렬화되어 DONE·알림이 1건입니다(기존 잠금, V3-S19-6에서 고정). |
| SURROGATE_OPT(§18)·PB_RESP_EXTRACT(§22)·FEM_VERIFY 출처(`batch_run` → 예측 작업)·design-map | 출처 모델 변경 | 무수정(SO 배치도 레인 이득) |
| 실행 목록 V1·행 재시도·행 취소·`retry-failed` | 행 단위 재시도·취소를 새로 구현 | 무수정 |
| 슬롯·FIFO | 부모가 배치 내내 슬롯 독점(§14.2 K4가 기각한 형태), 대기열에 하위가 보이지 않음 | 대기열 1번이 같은 배치일 때만 동반, 다른 작업 순서 유지 |
| PREDICT step 코드 | EDSPY~CAPTURE 7 step을 `ParallelRunner` 판으로 이식 | EDSPY 1 step에 입장 문·측정·OOM 훅 |
| 변경 위치 | step 이식 + 훅·API·화면 대량 | DB claim 함수 1개 + drain 규칙, 워커 실행기·레인 모듈, 제한기 그룹 재사용 |

(b)는 동시성(리스·세션 상태) 위험이 있어 V3-S19-5~10으로 고정합니다.

#### 24.4.2 레인 대상·세션

- **레인 대상** = `job_type = 'PREDICT'` + `lane = 'SLOT'` + `params.batch_run` 있음(`pb_repo.batch_run_ref`). 그 밖(단일 예측, FEM_VERIFY 동반 PREDICT, PREDICT_BATCH 등)은 지금과 같습니다.
- **N** = `predict_batch.predict_parallel_max`(기본 2, 1 = 기능 끔)이고, 리더를 포함한 수입니다.
- **레인 세션**(워커 메모리, `worker/physicsai_worker/gpu_lane.py` `GpuLaneSession`):
  - `batch_id`
  - `members`: 실행기 집합
  - `group`: 제한기 그룹
  - `mode`: `PARALLEL` | `SINGLE`
  - `single_reason`: `GPU_QUERY` | `GPU_OOM` | null
  - `peaks{job_id: mb}`, `est_db`: 세션 시작 때 1회 조회
- 세션은 첫 레인 대상 claim(N ≥ 2) 때 열립니다. 마지막 멤버가 끝나면 `close_group`(KILL_ON_JOB_CLOSE)으로 닫습니다.
- 워커는 세션을 동시에 1개만 둡니다.

#### 24.4.3 claim 규칙

| 경로 | 규칙 |
|---|---|
| 슬롯 스레드 `run_once_slot` | 세션이 활성이면 **claim하지 않고 None**입니다. 아니면 기존 `claim_slot`입니다. claim한 작업이 레인 대상이고 N ≥ 2이면 세션을 열고 `Executor(..., slot_holder=True, lane=session)`로 실행합니다. |
| 레인 스레드 `run_once_lane`(신규 루프 `gpu-lane`, 간격 min(`claim_interval_s`, `gpu_poll_s`)) | 세션이 있고, mode PARALLEL이고, members < N이고, **동반 claim 문**(§24.4.4)이 참일 때만 DB `claim_lane`을 부릅니다. claim하면 멤버 스레드(`lane-<id8>`)에서 `Executor(..., slot_holder=<claim 결과>, lane=session).run()`입니다. |
| DB `job_lease.claim_lane(conn, worker_id, ttl_s, batch_id, env_snapshot) -> (job, is_holder) \| None` | ① `worker_slot` 행 `FOR UPDATE`(claim_slot과 직렬화). ② **대기열 1번** = `state=QUEUED AND lane=SLOT AND cancel_requested_at IS NULL ORDER BY queue_seq LIMIT 1 FOR UPDATE`(skip_locked 없이 — 1번을 건너뛰지 않음). ③ 1번이 PREDICT이고 `params->'batch_run'->>'batch_id' = batch_id`이고, 같은 배치의 RUNNING 작업 중 `lease_owner_id = worker_id`가 1개 이상이어야 합니다. 아니면 None. ④ 슬롯 lease가 비었거나 만료(만료면 claim_slot과 같은 정리)면 holder로 claim(worker_slot 갱신, `is_holder=True`)하고, 슬롯이 살아 있으면 동반(worker_slot 무변경, `is_holder=False`)입니다. ⑤ 작업 행: `state=RUNNING, holds_slot=TRUE`(CHECK `ck_jobs_holds_slot` 충족), `queue_seq=NULL`, `started_at=coalesce`, lease(`lease_generation = 작업 값 + 1`). `_mark_started`·`notify_job(JOB_STARTED)`(하위는 기존대로 억제)·`recompute_my_turn`. ⑥ CAS 실패 → `ClaimRace` |
| DB `claim_slot` 배수 규칙(추가) | target을 고른 뒤 `RUNNING AND lane=SLOT` 작업이 있으면 그 작업들의 `batch_run.batch_id`가 모두 B이고 target이 같은 B 하위일 때만 진행하고, 아니면 None입니다. 다른 워커 프로세스가 있어도 무거운 작업이 동반 예측과 겹치지 않습니다. |
| lease 갱신 | `LeaseKeeper(slot=slot_holder)`입니다(기존 `holds_slot` 대신). 동반 멤버의 `renew(slot=False)`는 작업 lease만 갱신합니다. `release`·리퍼·`_interrupt`는 무수정입니다(`worker_slot` 정리는 token·holder 일치일 때만). |

리더가 끝나고 동반 멤버가 남으면 worker_slot은 빕니다. 다음 같은 배치 하위는 레인 스레드가 claim하고(슬롯이 비었으므로 holder가 됨), 다른 작업은 세션이 끝날 때까지 기다립니다.

#### 24.4.4 GPU 문·예상·측정

공통 값(`gpu_lane.gate(...)`, 순수 함수 — 시험에서 표로 검증):
- `fresh` = monitor 상태 OK이고 `now − sampled_at ≤ 3 × gpu_poll_s`이고 `gpu_index < len(gpus)`
- `free` = `mem_total_mb − mem_used_mb`(gpus[gpu_index])
- `est` = 예상(MB), `margin` = `gpu_margin_mb`
- `reserve` = Σ(아직 EDSPY_PREDICT를 끝내지 않은 다른 멤버 j) max(0, est − observed_j). observed_j = j가 GPU 사용 구간에 있고 프로세스별 측정이 있을 때 그 현재 MB, 아니면 0(보수적).

**동반 claim 문**: `fresh` ∧ mode = PARALLEL ∧ members < N ∧ `free − reserve(전 멤버) ≥ est + margin`입니다. `fresh`가 거짓이면 mode는 그대로 두고 claim만 막습니다. 이때 `gpu_lane.single_reason = "GPU_QUERY"`로 표시합니다(일시 상태).

**EDSPY 입장 문**(`edspy_gpu.admit`, 레인 멤버의 EDSPY_PREDICT 시작 직전):
1. 다른 멤버가 GPU 사용 구간에 없으면 즉시 입장합니다.
2. 아니면 `fresh` ∧ mode = PARALLEL ∧ `free − reserve(자기 제외) ≥ est + margin`일 때 입장합니다.
3. 그 밖에는 `gpu_poll_s`마다 다시 확인합니다. 대기 중에는 매번 취소·lease 상실을 확인하고(`Cancelled`·`LeaseLost`), 진행 라벨을 표시하며, 작업 로그에 `[GPU] 메모리 대기 …`를 작업당 1회 남깁니다.
4. GPU 사용 구간 = 입장부터 EDSPY 프로세스 종료(OOM 재실행 포함)까지입니다.

**예상 `estimate(session)`**: 다음 중 첫 번째로 값이 있는 것을 씁니다.
1. max(`est_db.batch`, session.peaks 값)
   - `est_db.batch` = 같은 배치 run들의 `predict_job_id` → `jobs.result->'gpu'->>'peak_mb'` 최대
2. `est_db.model` = 같은 Study에서 `job_type='PREDICT' AND params->>'model_id' = 이 배치 model_id AND result->'gpu'->'peak_mb' 있음`인 작업을 `created_at` 최신순 20개 본 최대
3. `gpu_estimate_default_mb`

조회는 새 저장소 `db/repositories/predict_gpu.py` `gpu_peaks(conn, batch_id, study_id, model_id, limit=20) -> {"batch": mb|None, "model": mb|None}`이고, 세션 시작 때 1회 부릅니다.

**측정**:
- 레인 활성 중 monitor가 `gpu_poll_s`마다 프로세스별 조회를 합니다.
- 멤버가 GPU 사용 구간이면 `executor.current_proc.pid`와 그 자손(psutil `children(recursive=True)`) pid의 `used_memory` 합 = observed입니다. 최대를 peak로 둡니다(method `process`).
- `apps`가 None이면 method `total_diff`입니다. baseline = 입장 시각의 `mem_used_mb`, peak = 구간 최대 used − baseline이고, **구간 내내 GPU 사용 멤버가 자기뿐일 때만** 유효합니다. 아니면 peak null(method null).
- EDSPY_PREDICT 끝에 `ctx.patch_result({"gpu": {...}})`를 기록합니다. 필드:
  - `peak_mb`: int|null
  - `method`: `"process"|"total_diff"|null`
  - `concurrent_max`: 구간 중 GPU 사용 멤버 수 최대
  - `waited_s`
  - `oom_retried`: bool
  - `estimate_mb`
- peak가 있으면 `session.peaks`에 넣습니다.
- 레인 밖 PREDICT(N = 1 포함)는 `result.gpu`를 쓰지 않습니다.

#### 24.4.5 OOM 감지·자동 재실행

`steps/stage4_predict/edspy_gpu.py`(신규)의 `run_predict(ctx, values, *, cwd, pred, outputs_to_backup, env_add) -> rc`가 `predict.py edspy_predict`의 `ctx.run_local("edspy_predict", …)` 호출을 감쌉니다.
- 레인 멤버가 아니면 지금 호출 그대로입니다.
- `predict.py`는 이 한 줄과 import만 바뀝니다. 판정 `_judge_output`·D3-37 경고는 그대로입니다.

절차:
1. `admit`(§24.4.4) → `run_local(..., line_hook=<oom 패턴 검사>)`
2. 판정: `pred` h3d 없음 ∧ (rc ∈ `oom_exit_codes` ∨ 로그 줄이 `oom_patterns` 중 하나에 맞음(대소문자 무시 `re.search`)) = OOM
3. OOM이고 `concurrent_max ≥ 2`이고 아직 재실행하지 않았으면:
   - `session.mode = SINGLE`, `single_reason = "GPU_OOM"`
   - 워커 로그 1줄 `GPU 메모리 부족 — 배치 B-003 동시 예측을 단독으로 전환합니다(run__00002)`
   - 경고 `GPU_OOM_RETRIED` "GPU 메모리 부족으로 다른 예측과 동시에 실행하던 예측을 단독으로 1회 다시 실행했습니다"
   - **단독 입장**(다른 GPU 사용 멤버가 0일 때까지 대기, 라벨 "GPU 단독 실행 대기 — 메모리 부족 후 재실행") 후 같은 argv로 1회 다시 실행(`outputs_to_backup=[pred]`)
   - `oom_retried = True`
4. 재실행에서도 OOM이거나 처음부터 단독(`concurrent_max` = 1)이었으면 `StepFailure("GPU_OOM", "GPU 메모리가 부족해 예측하지 못했습니다(단독 실행에서도 부족) — 다른 GPU 프로그램 또는 모델·입력 크기를 확인하세요")`입니다.
5. OOM이 아닌 실패는 기존 판정입니다.

SINGLE 세션: 동반 claim 문이 거짓이 되고, 입장은 단독만 허용합니다. 세션이 끝나면 해제되고, 다음 세션은 PARALLEL로 시작합니다.

#### 24.4.6 제한기(Job Object)·취소·재시도·lease

- **그룹**:
  - 세션이 열릴 때 `limiter.open_group(worker.limits, size=N)`을 엽니다.
  - `Executor.lane_group`이 있으면 `step_process.run_local`이 `limiter.launch(..., group=lane_group)`로 실행합니다(멤버의 모든 LOCAL step).
  - 실행 구간을 `group.run_started/run_ended`로 기록합니다.
  - 세션 감시(GpuLaneSession 내부 스레드, `MEMORY_SAMPLE_S` 0.5초)가 `group_accounting` → `note_memory`를 합니다.
  - rc ≠ 0이고 `memory_verdict`가 `exact`면 기존 RESOURCE_LIMIT 문구입니다. `uncertain`이면 RESOURCE_LIMIT "작업 메모리 한도(X GB)에 도달해 종료되었습니다 — 동시에 실행 중인 다른 예측과 한도를 나눠 써 원인이 불확실합니다"입니다. None이면 메모리 사유가 아닙니다(rc 판정 계속).
  - `limiter.close(proc)`는 그룹 안 프로세스를 닫지 않습니다(기존).
- **취소**:
  - 멤버별로 기존 `cancel_requested` 폴링을 합니다. 입장 대기 루프도 같은 간격으로 확인합니다.
  - 그 멤버 프로세스만 `limiter.terminate(proc)`(그룹 안 단일 종료, 기존)합니다.
  - 일괄 취소(`/predict-batches/{bid}/cancel`)는 무수정이고, 각 멤버가 각자 종료합니다.
  - 세션이 비면 그룹을 닫습니다.
- **lease 상실**: 그 멤버의 `_on_lost`는 자기 `current_proc`만 종료합니다. **레인 그룹은 `current_group`에 넣지 않습니다**(세션 전체 종료 금지).
- **재시도**: 무수정입니다(`/jobs/{id}/retry`·`retry-failed`). 새 작업은 대기열 끝에 서고, 1번이 되면 같은 규칙을 탑니다. OOM 자동 재실행은 같은 작업 안 1회뿐입니다.
- **워커 중지**: `Worker.executors`(신규 집합, 잠금) 전체의 keeper를 `paused`합니다. `current_executor`는 슬롯 holder 실행기로 유지합니다(기존 시험 호환).
- **하트비트 `resources.job`**: holder 실행기(없으면 첫 멤버)의 회계를 씁니다. 레인 그룹이면 `group_accounting(lane_group)`입니다.

#### 24.4.7 진행 표시

- 하위 PREDICT EDSPY_PREDICT 라벨:
  - 대기 중: `GPU 메모리 대기 — 필요 {est+margin:.1f} GB · 여유 {free−reserve:.1f} GB`
  - 단독 대기: `GPU 단독 실행 대기 — 다른 예측이 GPU 사용 중`
  - 조회 불가: `GPU 단독 실행 대기 — GPU 조회 불가`
  - 실행 중: 기존(edspy 마지막 줄)
- `GET /queue`:
  - `running` = worker_slot holder 작업입니다(없으면 RUNNING SLOT 중 `started_at`이 가장 이른 작업, 결정적).
  - 새 `running_parallel: JobSummary[]` = 나머지 RUNNING SLOT 작업(started_at 순)입니다.
- 화면:
  - 대기열 칩 `실행` 수 = running + running_parallel + light입니다.
  - 대기열 서랍은 실행 중을 목록으로 표시합니다.
- ④ B 결과(`BatchResult`) "예측" 카드 aside:
  - N ≥ 2이면 `동시 최대 N(GPU 메모리 여유에 따라)`, N = 1이면 기존 `대기열 1슬롯`입니다.
  - N = `/status.limits.configured.predict_parallel_max`입니다.
  - 카드 본문 `실행 중 · 대기 · 완료`는 기존 `predict` 집계(여러 개 실행이 이미 반영)입니다.
- ④ B 설정(`BatchSetup`) 문구(N ≥ 2):
  - 228행 → `GPU 메모리 여유에 따라 최대 N개 동시`
  - 279행 → "입력 생성은 동시 실행으로 빠르게, 예측은 GPU 메모리 여유에 따라 같은 배치끼리 최대 N개 동시에 실행합니다. 다른 사용자 작업의 대기열 순서는 바뀌지 않습니다."
  - N = 1이면 기존 문구입니다.
- 서랍 `WorkerResourcePanel`의 `gpu_lane` 줄:
  - `GPU 동시 예측 B-003 — 실행 2 / 최대 2 · 예상 5.0 GB/run`
  - SINGLE이면 `… — 단독 실행(GPU 조회 불가 | GPU 메모리 부족 후)`

#### 24.4.8 API(`backend/openapi.json` 갱신, 새 라우트·operationId 없음)

```jsonc
// GET /resources 추가 키(모두 선택 — 옛 워커 표본은 null)
{"gpu_fail_streak":0,"gpu_sampled_at":"…","gpu_next_query_at":null,
 "gpu_lane":{"batch_id":"…","batch_label":"B-003","running":2,"gpu_active":1,"max":2,
             "mode":"PARALLEL","single_reason":null,"estimate_mb":5012,"free_mb":38120}}   // 세션 없으면 null
// GET /queue 추가
{"running":{…holder…},"running_parallel":[{…JobSummary…}], …기존…}
// GET /status limits.configured 추가
{"predict_parallel_max":2}
```

하위 PREDICT `result.gpu`(§24.4.4)는 기존 자유 JSON result입니다(스키마 변경 없음). 실패 코드 `GPU_OOM`·경고 `GPU_OOM_RETRIED`는 문서와 `lib/format.ts` 표시 문구에 추가합니다.

### 24.5 (3) ⑤ `perf:` 지표 서버 계산(`GET /predict-batches/{bid}/design-map`)

- `services/design_map.py`: `perfs = performance.perf_defs(ps.responses)`
- 성공 run(파일 위치 있음)마다 `m = load_run_metrics(...)`(기존 LRU, `requests` 포함)를 읽습니다. 이름마다:
  1. `v, why = performance.perf_value(d, m)`
  2. `why == "NOT_EXTRACTED"`이고 `d.source == "H3D"`이고 결과 표 값 `r.responses[name]`이 유한하면 `v = 표 값, why = None`(옛 추출 방식 run, Q11)
  3. `run.perf[name] = v`. v가 null이면 `run.perf_reason[name] = why`
- 성공이 아닌 run은 `perf = null`, `perf_reason = null`입니다.
- 스키마(`schemas/predict_batch.py`, 모두 기본값 있음 — 기존 응답 하위호환):
  - `DesignMapRun.perf: dict[str, float | None] | None`, `perf_reason: dict[str, str] | None`
  - `DesignMapMetric.spec_changed: int | None`(perf 지표만, 성공 run 중 SPEC_CHANGED 수)
  - `DesignMapCounts.spec_changed: int = 0`(SPEC_CHANGED 성능이 1개 이상인 성공 run 수)
  - `DesignMap.reason_text: dict[str, str] = {}`(응답에 나온 사유 코드 → `responses.REASON_TEXT` 한국어)
- `metrics`: 기존 curve → resp → tbl 뒤에 `{id: "perf:<NAME>", label: perf_label(d), unit: d.unit or null, needs_series: false, spec_changed}`를 붙입니다(템플릿 순서, 값 있는 run ≥ 1인 성능만, Q12).
- 시간: 파일 추가 읽기는 없습니다(`requests`는 이미 `load_run_metrics`가 읽음). 성능 계산은 run × 성능 수만큼 순수 함수 호출입니다.

**프런트 계산 제거 계획(Impl-Frontend)**:

| 파일 | 변경 |
|---|---|
| `analysis/perfColumns.ts` | `perfValue`·`withPerfMetrics`·`PerfDesignRun`·`STAT_KEY`와 perfRules import를 **삭제**합니다. `NO_RESP_HINT`·`MAX_CURVE_SERIES`·`CURVE_STATS`·`curveColumn`·`curveColumns`·`curveValue`만 남기고, 머리 주석을 "커브 열 규칙(성능 값은 서버 design-map)"으로 바꿉니다. |
| `analysis/adapters/fromBatch.ts` | 성능 정의가 있는 열의 값 = `dm.runs[doe].perf[name]`입니다. dm이 null(design-map 실패)이면 결과 표 값입니다. 추가 성능 열 = dm `metrics` 중 `perf:` id이면서 `b.responses`에 없는 이름입니다. 행 `why[name] = perf_reason`, `rt.designMap = dm`(합성 없음). `dm.counts.spec_changed > 0`이면 `rt.notes`에 "성능 정의가 바뀐 뒤 다시 추출하지 않은 run N개는 성능 값이 비어 있습니다 — ⑥ 최적화 설정의 성능 표에서 '다시 추출'"을 넣습니다. |
| `analysis/resultTable.ts` | `RtRow.why?: Record<string, string>`(null 값 사유 코드)와 `ResultTable.reasonText?`(dm.reason_text)를 추가합니다. |
| `stages/stageAnalysis/AnalysisTable.tsx` | null 칸에 `title` = reasonText[why]를 표시하고, SPEC_CHANGED 칸은 `—` 옆에 회색 "정의 변경"을 표시합니다. |
| `analysis/viz/designMap/designMapData.ts` | `runValue`의 perf 분기는 그대로 둡니다(`run.perf`를 이제 서버가 줌). 주석만 고칩니다. |

### 24.6 설정(기본값은 스키마 한 곳, `config/platform.example.yaml`에 주석 한 줄씩)

| 키 | 기본 | 범위·검증 | 설명 |
|---|---|---|---|
| `worker.gpu_query_timeout_s` | 15 | 1~120 | nvidia-smi 조회 제한 시간(요약·프로세스별·환경 점검 공통) |
| `worker.gpu_backoff_after` | 3 | 1~100 | 연속 실패가 이 횟수부터 간격을 두 배씩 |
| `worker.gpu_backoff_max_s` | 300 | 0 또는 `resource_sample_interval_s`~3600 | 늘린 간격 상한, 0 = 늘리지 않음 |
| `predict_batch.predict_parallel_max` | 2 | 1~8 | 같은 배치 하위 예측 동시 최대(리더 포함), 1 = 레인 끔(현재 동작) |
| `predict_batch.gpu_estimate_default_mb` | 6144 | 256~1048576 | 실측이 없을 때 run 1개 예상 GPU 메모리 |
| `predict_batch.gpu_margin_mb` | 1024 | 0~1048576 | 시작 조건 여유 |
| `predict_batch.gpu_index` | 0 | ≥ 0 | 판단에 쓰는 GPU 순번(nvidia-smi 출력 순서) |
| `predict_batch.gpu_poll_s` | 2 | 0.5~30 | 레인 활성 중 GPU 표본·입장 재확인 간격 |
| `predict_batch.gpu_apps_query_args` | `["--query-compute-apps=pid,used_memory","--format=csv,noheader,nounits"]` | 비지 않은 문자열 배열 | 프로세스별 GPU 메모리 조회 인자(실행 파일은 GPU 조회와 같음) |
| `predict_batch.oom_exit_codes` | `[]` | 정수 배열 | OOM으로 볼 종료코드(서버 확인 E4-19-5 뒤 채움) |
| `predict_batch.oom_patterns` | `["CUDA out of memory","CUDA error: out of memory","CUBLAS_STATUS_ALLOC_FAILED","cudaErrorMemoryAllocation","OutOfMemoryError"]` | 각 정규식 컴파일 가능(아니면 설정 오류 `predict_batch.oom_patterns[i]`) | OOM 로그 문구(대소문자 무시 search) |

검증은 새 `backend/physicsai_core/config/validate_gpu.py` `check(s, add)`이고, `validate.py`에서 1줄로 호출합니다(validate.py는 R 분할 대상이라 본문을 늘리지 않음). `/status.limits.configured.predict_parallel_max`를 추가합니다.

### 24.7 DB

변경 없음(migration 없음, `MIGRATION_HEAD` = `0015_doe_platform_gen` 유지).
- 새 저장소 함수(조회만): `db/repositories/predict_gpu.py` `gpu_peaks`
- `job_lease.py`: `claim_lane` 추가, `claim_slot` 배수 규칙 추가
- `queue_view` 정렬

기존 CHECK(`ck_jobs_holds_slot`·`ck_jobs_lease_*`·`ck_worker_slot_*`)를 모두 지킵니다(V3-S19-5).

### 24.8 job·step

- job_type·step 키·가중·라벨 무변경.
- 이번에 바뀌는 처리: PREDICT `EDSPY_PREDICT` 내부(입장 문·측정·OOM — 레인 멤버만), 워커 claim(`run_once_slot` 배수, `run_once_lane` 신규), `Executor(slot_holder, lane)`, `run_local` 그룹 실행.
- 종료 훅(`job_end`·`batch_on_job_end`)·`on_retry`·알림 억제는 무수정입니다.

### 24.9 시험(V3-S19-*)

원칙(S18과 같음): 동시 실행은 시각 비율로 단언하지 않습니다.
- 하한은 가짜 edspy barrier로 결정적으로 증명합니다.
- 상한·비겹침은 `FAKE_TOOL_TRACE` 구간으로 확인합니다.
- barrier·대기 상한은 60초 이상입니다.

e2e는 `Worker.start()`를 짧은 간격(`claim_interval_s` 0.2, `gpu_poll_s` 0.5)으로 실제 스레드로 돌리고, DB를 상한 120초로 폴링합니다.

가짜 도구(`backend/tests/fake_tools/`):

`fake_nvidia_smi`:
- `FAKE_NVIDIA_SMI_STATE=<dir>`이 없으면 기존 출력 그대로입니다(기존 시험 무수정).
- 있으면 `<dir>/gpu.json`(`name,total_mb,base_used_mb,util`)과 `<dir>/procs/<pid>`(MB, 살아 있는 pid만)를 읽어 used = base + Σ로 출력합니다.
- `--query-compute-apps` 인자면 `pid, mb` 줄을 출력합니다. `FAKE_NVIDIA_SMI_APPS=na`면 `pid, [N/A]`입니다.
- `FAKE_TOOL_MODE_NVIDIA=hang`이면 3600초 대기합니다.

`fake_edspy`(예측 모드만):
- `FAKE_TOOL_TRACE` 시작·끝 기록(fake_simlab과 같은 형식)
- `FAKE_GPU_STATE=<dir>` + `FAKE_EDSPY_GPU_MB=n`: 실행 중 `<dir>/procs/<자기 pid>`를 두고 끝에서 지웁니다.
- `FAKE_EDSPY_BARRIER=<dir>:<n>`: 형식은 S18 fake_simlab과 같고, `FAKE_EDSPY_BARRIER_TIMEOUT_S` 기본 90입니다. 초과하면 "barrier timeout" 출력, 종료코드 9, h3d 없음입니다.
- `FAKE_EDSPY_OOM_MATCH=<--input-file 부분 문자열>` + `FAKE_EDSPY_OOM_STATE=<dir>`: 일치하는 첫 실행만 "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB"를 출력하고 종료코드 1, h3d 없음입니다.
- `FAKE_EDSPY_OOM_ALWAYS=1`: 항상 OOM입니다.

| ID | 기준 |
|---|---|
| V3-S19-1 | 설정: 새 키 11개 기본값·범위 오류 문구, `oom_patterns` 정규식 오류 키 경로, `gpu_backoff_max_s` 0 허용·base 미만 거부, 예시 yaml 주석, `/status.limits.configured.predict_parallel_max` |
| V3-S19-2 | 제한 시간: 가짜 nvidia-smi `hang` + `gpu_query_timeout_s` = 1 → ERROR "응답 시간 초과(1초)"가 5초 안에 나옴. 환경 점검 `gpu.detect`도 같은 설정. `query_gpu_status(timeout_s=)` 기본 = 설정 |
| V3-S19-3 | `GpuMonitor`(조회 함수·시계 주입): 결과 OK,ERR,ERR,ERR,ERR,ERR,OK → caplog의 WARNING 2줄(첫 실패·연속 3회)과 INFO 1줄(회복), 같은 실패 반복은 기록 없음. NOT_FOUND→ERROR 전이 1줄. 간격 수열(base 10, after 3, max 300) 10,10,20,40,80,…,300, 회복하면 base. max 0이면 고정. `hang` 중 `heartbeat_once` < 1초(캐시 사용) |
| V3-S19-4 | `/resources`: `gpu_fail_streak`·`gpu_sampled_at`·`gpu_next_query_at`·`gpu_lane` 통과, 옛 표본(키 없음) null, OK일 때 `gpu_message` = 실행 파일(기존), openapi 갱신·`operation_ids.txt` 불변 |
| V3-S19-5 | DB claim: `claim_lane` — 1번이 다른 배치·다른 유형·취소 요청이면 None, 같은 배치라도 이 워커 소유 RUNNING 형제가 없으면 None, 슬롯 비었으면 holder(worker_slot 갱신)·살았으면 동반(worker_slot 무변경, `holds_slot` TRUE). `claim_slot` 배수(동반 실행 중 + 1번이 다른 작업 → None, 같은 배치 → 진행). 동반 `renew(slot=False)` 성공, `release` 시 worker_slot 무변경, 리퍼가 동반을 INTERRUPTED로, CHECK 위반 없음. `/queue` running = holder·`running_parallel` 정렬 |
| V3-S19-6 | **동시 2 증명**(mesh_only 배치 2 run, N = 2, nvidia-smi total 49140·base 1000, edspy GPU 5000 MB, barrier n = 2): 하위 2개 모두 SUCCEEDED(순차면 barrier timeout → 실패), `result.gpu` = `{peak_mb: 5000, method: "process", concurrent_max: 2}`, trace 동시 최대 ≤ 2, 배치 DONE·`PREDICT_BATCH_DONE` 정확히 1건(동시 종료), `responses` 복사 2행. Windows 가짜 kernel32: 레인 그룹 Job 1개에 두 작업 프로세스, 세션 종료 시 CloseHandle 1회 |
| V3-S19-7 | **메모리 부족 대기**(total 12000·base 1000·edspy 5000, 기본 예상 6144·여유 1024, 2 run, N = 2): 둘 다 SUCCEEDED, EDSPY trace 구간 비겹침, 워커 로그 "동반 실행 대기" 1회(억제). 순수 함수 `gate`·`admit` 표 시험(free·est·margin·reserve·stale·status·mode·members 조합 12가지 이상) |
| V3-S19-8 | **조회 실패 폴백**(`FAKE_TOOL_MODE_NVIDIA=fail`, 2 run, N = 2): 둘째 하위의 `started_at` ≥ 첫째의 `finished_at`(동반 claim 없음), EDSPY 비겹침, `/resources.gpu_lane.single_reason` = `GPU_QUERY`. `predict_parallel_max` = 1이면 세션·레인 스레드 claim 없음, `run_local`이 그룹 없이 실행(기존 경로) |
| V3-S19-9 | **OOM 재실행**(시험 6 조건 + `FAKE_EDSPY_OOM_MATCH=run__00002`, 3 run): run 2 SUCCEEDED + 경고 `GPU_OOM_RETRIED`, `result.gpu.oom_retried` = true, edspy 기록상 run 2가 2회 실행되고 두 번째 구간은 다른 EDSPY와 비겹침, 그 뒤 run 3의 EDSPY도 비겹침(SINGLE). 단독 OOM(`FAKE_EDSPY_OOM_ALWAYS`, N = 2·1 run) → FAILED `GPU_OOM`, 재실행 없음. h3d 있음 + OOM 문구 → 성공 + 기존 `LOG_ERROR_PATTERN` 경고(D3-37). `oom_exit_codes=[3]` + 패턴 없는 rc 3 → OOM 판정 |
| V3-S19-10 | 취소·lease: 입장 대기 중 멤버 취소 → 10초 안 CANCELED, 다른 멤버 영향 없음. edspy `hang` 멤버 취소 → 그 pid·손자 종료(psutil), 다른 멤버 SUCCEEDED. 일괄 취소 → 전부 종료·배치 CANCELED. 멤버 lease 상실(keeper paused) → 그 프로세스만 종료·그룹 유지. 공유 그룹 메모리 도달(가짜 회계) → `uncertain` 문구 RESOURCE_LIMIT |
| V3-S19-11 | 회귀: V3-S9-*·V3-S13·V3-S16·V3-S17·V3-S18 시험 **무수정 통과**(기본 N = 2, 기존 시험은 `run_once_slot`만 구동). `worker/tests/runtime/test_queue_lease.py`·`test_lease.py` 무수정 |
| V3-S19-12 | design-map perf: H3D·CURVE 값 = `performance.perf_value`, SPEC_CHANGED → null + `perf_reason` + `metrics[].spec_changed` + `counts.spec_changed` + `reason_text`, NOT_EXTRACTED + 표 값 → 표 값(H3D만, CURVE는 대체 없음), 성공 아닌 run null, 지표 순서·값 없는 성능 제외, 파일 추가 읽기 0(LRU `cache_info`), 기존 키·값 불변(S12 시험 무수정), openapi |
| V3-S19-13 | 프런트: `gpuFailTip`(ERROR·NOT_FOUND·streak·다음 시각·OK면 null), 칩 title·서랍 `gpu-message`·레인 줄, `queueCounts`에 `running_parallel`, 대기열 서랍 여러 실행, B 설정·결과 문구(N = 1·2), `fromBatch`가 서버 perf 사용(dm null → 표 값), `why` → 칸 title·"정의 변경", notes 문구, `perfColumns`에 `perfValue`·`withPerfMetrics` export 없음(정적 시험), 목(`mock/ops.ts`·`predictBatch.ts`·대기열 목) + `mockContract`, `npm run gen:api`, `frontend-dist` 최신, `scripts/test-all` 통과 |

### 24.10 서버 확인(사용자)

**E0-8 GPU 조회**:

| ID | 확인 |
|---|---|
| E0-8-1 | 평소 상태: 자원 칩 툴팁 = `워커 자원 열기`, 서랍 GPU 막대 정상, 워커 로그에 GPU 줄 없음 |
| E0-8-2 | `worker.gpu_query`를 없는 경로(`["C:/nope/nvidia-smi.exe"]`)로 바꾸고 `resources.gpu_query_candidates`를 `[]`로 임시 변경 → 칩 툴팁 `GPU 없음 — nvidia-smi를 찾지 못했습니다(…)`, 서랍 회색 줄, 워커 로그 1줄, 3회 뒤 "간격을 늘립니다" 1줄·툴팁 다음 조회 시각이 점점 멀어짐 → 원복 → 회복 1줄 |
| E0-8-3 | 이전에 보던 "GPU 조회 실패"가 다시 나면 툴팁 문구·연속 횟수·워커 로그 시각을 기록합니다(15초 초과 응답인지, 종료코드인지 판별 → 필요하면 `gpu_query_timeout_s` 조정) |

**E4-19 일괄 예측 동시 예측·perf**:

| ID | 확인 |
|---|---|
| E4-19-1 | 기존 템플릿·Final 모델로 일괄 예측 8 run(N = 2). 감시 명령으로 edspy 2개가 동시에 GPU 메모리를 쓰는지, 대기열 칩 "실행 2", 서랍 `GPU 동시 예측 … 실행 2 / 최대 2` 확인. 하위 작업 상세 result `gpu.method`(process 또는 total_diff)·`peak_mb` 기록 |
| E4-19-2 | 같은 입력으로 `predict_parallel_max: 1` 배치와 응답 값 비교(같아야 함), 총 소요 비교 |
| E4-19-3 | 동시 2에서 라이선스 오류 없음(하위 작업 로그 `licens` 검색 — edspy·HyperView 응답 추출·캡처). 오류가 나면 N = 1로 되돌리고 보고(R-1) |
| E4-19-4 | 동시 실행 중 일괄 취소 → 30초 안에 감시 출력의 edspy 0개 |
| E4-19-5 | (선택) OOM 문구 채집: `gpu_estimate_default_mb: 1`, `gpu_margin_mb: 0`, N = 4로 큰 모델 배치 → OOM이 나면 edspy 로그의 실제 문구·종료코드를 기록해 `oom_patterns`·`oom_exit_codes`에 반영(원복 필수). 경고 `GPU_OOM_RETRIED`·단독 재실행 확인 |
| E4-19-6 | ⑤ 결과분석: 기존 배치의 성능 열 값이 S18과 같은지, 템플릿 성능 정의(subcase 등)를 바꾼 뒤 "정의 변경" 표시·안내 줄 → ⑥ 성능 표 "다시 추출" 후 값 복귀 |

감시 명령(PowerShell, 2초 간격, `Ctrl+C`로 종료):
```powershell
$log = "$env:TEMP\gpu_lane.csv"; "time,gpu,apps" | Out-File $log -Encoding utf8
while ($true) {
  $g = (& nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader) -join ' '
  $a = (& nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader) -join ' ; '
  "{0},{1},{2}" -f (Get-Date -Format HH:mm:ss), $g, $a | Add-Content $log; Start-Sleep 2 }
```

### 24.11 파일 소유·순서(AGENTS.md 역할 표 — Backend·Frontend 겹침 없음)

**순서**:

| 단계 | 묶음 | 담당 | 선행 | 병렬 |
|---|---|---|---|---|
| 0 | **M0** S16 minor 4건(조립 파일 예약어 검사, reuse verify.json sha256, 동반 예측 출처 중복·FEM_VERIFY retry max_active 재검사, 옛 PREDICT_VERIFY SCX 확인 필요 조치 UI) + 문구·시험·그림 정리(td_sobol 2줄, analysisScreen waitFor, ParetoPlot) — **작업 트리에 미커밋 16파일로 진행 중** | Backend·Frontend | — | 먼저 커밋(아래 묶음이 `services/jobs.py`·`s17Screens.test.tsx`를 함께 고침) |
| 1 | Plan: 이 문서 저장 | 메인 | — | — |
| 2 | **B-PERF** | Backend A | M0 | B-GPU와 병렬 |
| 2 | **B-GPU** | Backend B | M0 | B-PERF와 병렬 |
| 2 | **F-PERF·F-GPU**(목 먼저) | Frontend | M0 | B와 병렬, openapi 커밋 뒤 타입 맞춤 |
| 3 | **B-LANE** | Backend B | B-GPU | — |
| 3 | **F-LANE**(목 먼저) | Frontend | F-GPU | B-LANE openapi 뒤 맞춤 |
| 4 | Verifier V3-S19 → 서버 확인 E0-8·E4-19 | Verifier·사용자 | 2·3 | — |
| 5 | **R-B** 300줄 분할 + `batch_matrix` → sampling 이동 | Backend | 4 | R-F·D와 병렬 |
| 5 | **R-F** 300줄 분할 | Frontend | 4 | R-B·D와 병렬 |
| 5 | **D** 문서 이관(s12_s13·s14~s19 → phase3.md 본문·변경 메모, 링크 갱신) | Plan | 4 | R과 병렬(docs만) |

`backend/openapi.json`·`operation_ids.txt`는 생성 파일입니다. B-PERF·B-GPU를 병렬로 할 때는 나중에 병합하는 쪽이 **다시 생성**합니다(수동 병합 금지). 프런트는 그 뒤 `gen:api`와 `frontend-dist`를 같은 커밋에서 갱신합니다.

**파일**:

| 묶음 | 파일 |
|---|---|
| **B-PERF** | 수정: `backend/physicsai_api/services/design_map.py`, `backend/physicsai_api/schemas/predict_batch.py`(DesignMap 4필드), `backend/openapi.json`. 새: `backend/tests/test_s19_design_map_perf.py`(V3-S19-12) |
| **B-GPU** | 새: `worker/physicsai_worker/gpu_monitor.py`, `backend/physicsai_core/config/validate_gpu.py`, `worker/tests/ops/test_s19_gpu_monitor.py`, `backend/tests/test_s19_resources_api.py`. 수정: `worker/physicsai_worker/resources.py`(timeout 인자·apps 조회 함수), `worker/physicsai_worker/runtime.py`(monitor 시작·하트비트 캐시), `worker/physicsai_worker/env_check.py`(timeout), `backend/physicsai_core/config/schema.py`(WorkerCfg 3키), `backend/physicsai_core/config/validate.py`(호출 1줄), `config/platform.example.yaml`, `backend/physicsai_api/schemas/shell.py`(ResourcesResponse 3필드), `backend/tests/fake_tools/fake_nvidia_smi`(상태 폴더·apps·hang), `backend/openapi.json`(V3-S19-1 일부·2·3·4) |
| **B-LANE** | 새: `worker/physicsai_worker/gpu_lane.py`(세션·gate·admit·레인 스레드 mixin `GpuLaneMixin` — runtime.py 300줄 방지), `worker/physicsai_worker/steps/stage4_predict/edspy_gpu.py`, `backend/physicsai_core/db/repositories/predict_gpu.py`, `worker/tests/stage4_predict/test_s19_lane.py`·`test_s19_lane_e2e.py`, `worker/tests/runtime/test_s19_claim_lane.py`. 수정: `backend/physicsai_core/db/repositories/job_lease.py`(`claim_lane`·배수), `worker/physicsai_worker/{runtime.py, executor.py, step_process.py}`, `worker/physicsai_worker/steps/stage4_predict/predict.py`(호출 1줄), `backend/physicsai_core/config/{schema_stages.py(PredictBatchCfg 8키), validate_gpu.py}`, `config/platform.example.yaml`, `backend/physicsai_api/services/jobs.py`(`queue_view`), `backend/physicsai_api/services/system.py`(limits.configured), `backend/physicsai_api/schemas/shell.py`(QueueResponse·`GpuLaneInfo`), `backend/tests/fake_tools/{fake_edspy, fake_nvidia_smi}`, `backend/openapi.json` (V3-S19-1 나머지·5~11) |
| **F-GPU** | 새: `frontend/src/shell/gpuText.ts`, `frontend/src/__tests__/s19Gpu.test.tsx`. 수정: `frontend/src/shell/RunStatus.tsx`(칩 title), `frontend/src/panels/WorkerResourcePanel.tsx`(메시지·연속 줄), `frontend/src/mock/ops.ts` |
| **F-LANE** | 수정: `frontend/src/shell/RunStatus.tsx`(`queueCounts`), `frontend/src/panels/{QueuePanel.tsx, WorkerResourcePanel.tsx}`(레인 줄), `frontend/src/stages/stage4/batch/{BatchSetup.tsx, BatchResult.tsx}`(문구), `frontend/src/lib/format.ts`(`GPU_OOM`·`GPU_OOM_RETRIED` 문구), 대기열·배치 목(`frontend/src/mock/*` 해당 파일), 시험 `frontend/src/__tests__/{queue.test.tsx, predictBatch.test.tsx, s19Gpu.test.tsx}` |
| **F-PERF** | 수정: `frontend/src/analysis/{perfColumns.ts, resultTable.ts}`, `frontend/src/analysis/adapters/fromBatch.ts`, `frontend/src/analysis/viz/designMap/designMapData.ts`(주석), `frontend/src/stages/stageAnalysis/AnalysisTable.tsx`, `frontend/src/mock/predictBatch.ts`(design-map perf), 시험 `frontend/src/__tests__/{s17Screens.test.tsx, analysisAdapters.test.ts}` |
| F 공통(각 묶음 커밋마다) | `frontend/src/api/generated/schema.d.ts`(`npm run gen:api`), `mockContract.test.ts`, `frontend-dist/**` |
| **R-B**(동작 불변, refactor-plan R12 규칙 — 재노출로 import 경로 유지, openapi 바이트 동일, 시험 무수정) | `stage4_predict/batch_matrix.py`(759) → `physicsai_core/sampling/` 아래로 이동 + `batch_matrix.py` 재노출(`sampling/matrix.py` 재노출 정리), `services/fem_verify.py`(649), `steps/stage5_optimize/surrogate.py`(614), `stage4_predict/param_discover.py`(592), `steps/_scx.py`(529), `surrogate/mo_infill.py`(503), `fem_compare.py`(455), `surrogate/dataset.py`(441), `services/predict_batches.py`(419), `surrogate/infill.py`(396), `schemas/surrogate_opt.py`(383), `commands.py`(367), `schemas/predict_batch.py`, `services/surrogate_opts.py`, `paths.py`, `services/stage4_predict.py`, `step_parallel.py`, `capture.py`, `repositories/surrogate_opts.py`, `limiter/windows_job.py`, `schemas/fem_verify.py`, `sampling/designs.py`, `config/validate.py`, `services/surrogate_opt_problem.py`, `steps/stage4_predict/predict.py`, 그리고 S19로 300줄을 넘긴 파일. `db/schema_0001.py`(migration 스냅숏)는 제외 |
| **R-F** | `frontend/src/stages/stage4/batch/BatchResult.tsx`, `frontend/src/lib/sampling.ts`, `frontend/src/api/types.ts`, `frontend/src/mock/{predictBatch.ts, femVerify.ts, surrogateOpt.ts, sampling.ts, server.ts}`(F5 규칙), S19로 300줄을 넘긴 파일 |
| **Plan(D 포함)** | 이 문서, phase3.md(§2.3에 레인 예외 한 줄 + 본문 이관), `docs/architecture.md`(gpu_monitor·gpu_lane·edspy_gpu·predict_gpu·claim_lane), `docs/e2e-checklist.md`(E0-8·E4-19), `docs/manual/admin.md`(설정 11개·GPU 로그 해석·N = 1로 끄기), `docs/manual/user.md`(일괄 예측 동시 실행·성능 "정의 변경"), `docs/refactor-plan.md`(R-B·R-F 기록) |

인터페이스 고정점: §24.4.8·§24.5 응답 모양, §24.6 설정 키, `claim_lane` 서명·반환, `result.gpu` 키. Frontend는 목으로 먼저 시작합니다.

### 24.12 리스크

- **R-1 edspy·HyperView 라이선스**: PhysicsAI 예측·HyperView 배치가 실행마다 라이선스를 쓰면 동시 2에서 라이선스 실패가 날 수 있습니다. 이는 OOM이 아니라 일반 실패로 나타납니다. 대응: E4-19-3, 설정 N = 1로 즉시 원복. 자동 감지는 하지 않습니다.
- **R-2 Windows WDDM 프로세스별 메모리 `[N/A]`**: 이 경우 total_diff만 쓰고, 처음부터 동시에 돌면 측정이 없어 예상이 기본 6 GB로 남습니다(보수적). E4-19-1에서 method를 기록합니다.
- **R-3 CUDA 메모리 반환 지연·할당 단편화**: EDSPY 종료 직후 free 값이 늦게 회복될 수 있습니다. `gpu_margin_mb`와 OOM 1회 단독 재실행으로 흡수합니다.
- **R-4 공유 Job Object**: 동시 2개가 작업 1개분 메모리 한도를 나눠 씁니다. 도달하면 `uncertain` 문구입니다. 관리자는 `worker.max_memory_gb`를 조정합니다.
- **R-5 FIFO 체감**: 레인이 끝날 때까지(배수) 다른 사용자 작업이 1번이어도 기다립니다. 최대 대기 = 실행 중 동반 작업 1개의 남은 시간입니다. 관리자 대기열 이동은 레인 동반을 끊습니다(1번만 동반하므로).
- **R-6 워커 여러 대**: 다른 호스트의 워커는 이 워커의 GPU 문을 모릅니다. 배수 규칙(DB)만 지켜지므로 단일 워커 전제를 유지합니다(현행과 같음).
- **R-7 옛 run 대체(Q11)**: design-map은 옛 추출 run에 결과 표 값을 쓰고, SO_COLLECT는 쓰지 않습니다. 옛 배치를 최적화에 재사용하면 성능 값 수가 ⑤ 화면과 다를 수 있습니다(미결 3).
- **R-8 환경 점검 지연**: `gpu.detect`가 최대 15초 걸릴 수 있습니다(light 스레드, 영향 작음).
- **R-9 OOM 문구 다양성**: 실제 edspy 문구가 기본 패턴과 다르면 OOM으로 판정하지 못하고 일반 실패가 됩니다. E4-19-5에서 채집해 설정에 반영합니다.

### 24.13 미결(사용자 확인 대상)

1. 동시 수 기본 2·상한 8과 기본 예상 6 GB·여유 1 GB가 적당한지(A6000 48 GB 기준).
2. 단일 PREDICT·FEM_VERIFY 동반 PREDICT·EVALUATE 등 다른 GPU 작업까지 레인을 넓힐지(현재 비범위).
3. SO_COLLECT도 design-map처럼 옛 run에 결과 표 값을 대체할지(현재 엄격 = `perf_value`만).
4. OOM 재실행이 실패하면 지금처럼 FAILED(`GPU_OOM`)로 끝낼지, 대기열 재시도를 자동으로 만들지.
5. 조회 지연(backoff)을 기본 켜 둘지(`gpu_backoff_max_s` 300).
6. ④ B 결과에 "GPU 대기 n" 집계를 따로 보일지(현재는 하위 작업 라벨로만 표시).

## 변경 메모(이 문서분 — phase3.md 변경 메모 목록으로 옮김)

- **D3-67 (사용자 승인 2026-10-19, S19 후속 — Plan)**: §24.
  - ① GPU 조회: `worker.gpu_query_timeout_s`(15)·`gpu_backoff_after`(3)·`gpu_backoff_max_s`(300)를 둡니다. 조회는 `GpuMonitor` 스레드가 하고 하트비트는 캐시를 씁니다. 워커 로그는 상태 전이 때만 1줄입니다. `/resources`는 `gpu_status`·`gpu_message`를 재사용하고 `gpu_fail_streak`·`gpu_sampled_at`·`gpu_next_query_at`를 추가합니다. 칩 툴팁·서랍에 실패 원인을 표시합니다.
  - ② ④ 일괄 예측 하위 PREDICT의 GPU 동시 실행 = **GPU 레인**입니다((a) 단일 step 묶음 기각 — §14.5 하위 작업·종료 훅·SO·FEM 검증·V1 호환). 대기열 1번이 실행 중 배치와 같은 배치 하위일 때만 `claim_lane`으로 동반하고, 최대 `predict_batch.predict_parallel_max`(2)개입니다. 레인 중에는 다른 작업을 claim하지 않습니다(워커 + DB `claim_slot` 배수 규칙). 단일 슬롯 FIFO 원칙에 이 예외 하나를 더합니다(phase3 §2.3에 기록).
  - ③ 시작 조건은 동반 claim 문 + EDSPY 입장 문(빈 메모리 − 예약 ≥ 예상 + `gpu_margin_mb`)입니다. 예상 = 같은 배치 → 같은 모델 실측 최대 → `gpu_estimate_default_mb`(6144)입니다. 실측은 `--query-compute-apps` 프로세스 트리 합, 안 되면 단독 구간 전체 차분이고 `jobs.result.gpu`에 기록합니다. 조회 실패·오래된 표본이면 동반 없음 = 동시 1입니다.
  - ④ OOM(h3d 없음 ∧ `oom_exit_codes`/`oom_patterns`)이 동시 실행 중에 나면 같은 작업 안에서 단독으로 1회 다시 실행하고(경고 `GPU_OOM_RETRIED`) 세션을 SINGLE로 바꿉니다. 단독에서 나면 `GPU_OOM` 실패입니다.
  - ⑤ 제한기: 세션마다 그룹 1개(Windows Job Object 1개)이고, D3-53 구간 판정을 씁니다. 취소·lease 상실은 멤버별이고 그룹은 마지막 멤버 뒤에 닫습니다. 재시도·종료 훅·알림은 무수정입니다. `/queue.running_parallel`, `/status.limits.configured.predict_parallel_max`, `/resources.gpu_lane`을 추가합니다.
  - ⑥ ⑤ `perf:`는 design-map이 서버에서 `performance.perf_value`로 계산합니다(`runs[].perf`·`perf_reason`, `metrics[].spec_changed`, `counts.spec_changed`, `reason_text`). 옛 추출 run(H3D `NOT_EXTRACTED`)만 결과 표 값으로 대체합니다. 지표 순서는 기존 뒤에 perf입니다. 프런트 `perfValue`·`withPerfMetrics`를 제거하고 칸 사유 표시를 더합니다(D3-65 보강 3 ⑤ 해소).
  - ⑦ migration 없음(head 0015 유지), 새 job_type·step·라우트 없음. 새 설정 11개, 실패 코드 `GPU_OOM`.
  - ⑧ 시험 V3-S19-1~13(가짜 edspy barrier·GPU 상태 폴더·OOM 1회, 시각 비율 단언 없음), 서버 확인 E0-8-1~3·E4-19-1~6.
  - ⑨ 계약 없는 승인 항목(S16 minor 4건·문구·시험·그림 = M0 진행 중, 300줄 분할·batch_matrix sampling 이동 = R-B·R-F, 문서 이관 = D)은 §24.11 순서에 둡니다. 분할은 기능 변경과 Verifier 뒤 마지막입니다.
- 2026-10-20 구현 반영 변경:
  - ⑩ **④ GPU 동시 예측(B-LANE·F-LANE) 철회** — 사용자 결정. §24.4(레인)·§24.6 predict_batch 8키·V3-S19-5~10·E4-19는 무효입니다. ④는 S18과 같이 SLOT 단일 FIFO로 1개씩 예측합니다. 구현 중 Verifier가 동시 OOM 교착(High)과 free/프로세스별 조회 시차로 인한 과입장(Medium)을 찾았고, 난도 대비 효용이 낮아 걷어냈습니다. 유지 범위는 ① GPU 조회 제한 시간·원인 표시(B-GPU·F-GPU)와 ⑥ perf 서버 계산(B-PERF·F-PERF)입니다.
  - ⑪ V3-S19-11 예외 1건: V-SM-6 `test_no_timeout_key_in_schema`는 `worker.gpu_query_timeout_s`를 제외합니다(작업 실행 시간 한도 없음이라는 취지는 유지). V3-S9 시험은 무수정입니다.
