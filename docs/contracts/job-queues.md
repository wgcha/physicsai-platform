# 계약: 작업 대기열 분리 — GPU 1개씩 · CPU 한도 안 병렬 · 구간별 슬롯 전환

> 상태: **계약 초안**(2026-10-22, Plan). 사용자 결정 반영: 혼합 작업은 구간별 분리(GPU 구간만 GPU 슬롯으로 직렬화), GPU 자원 = PhysicsAI 예측(추론)뿐. 릴리스 배정은 메인 확정 대기(제안 v0.2.9, [roadmap.md](../roadmap.md)).
> 기준: v0.2.8(863bfe0), migration HEAD `0021_uploads`. 상위: platform.md §7(상태 머신)·§11(워커)·§16.2(대기열 패널), phase3 §14.5(`run_parallel`), geometry-view §6.2(PREVIEW 레인), mcp.md(도구 호환). **충돌 시 이 문서 우선**(대기열·슬롯 한정). 2026-10-07 "로컬 실행 슬롯은 전역 1개" 결정을 대체한다.
> ID 규칙: 결정 `JQ-n`, 시험 `V-JQ-n`, 변경 메모 `JQ-Cn`.
> 사용자 요구 원문: "gpu작업만 1개씩 하고 cpu작업들은 대기 없이 자원안에서 계속 받아라. 각 작업 대기열을 분리하고 보여주는것도 따로 보여줘"

## 0. 한 줄 요약

전역 슬롯 1개(SLOT 레인 FIFO)를 **GPU 슬롯 1개 + CPU 슬롯 N개**로 나눈다. 슬롯은 **작업이 아니라 step 구간**에 붙는다 — 작업은 다음 step의 자원 종류가 바뀌는 경계에서 지금 슬롯을 **반납하고** 다른 대기열에 원래 순번으로 다시 선다. 한 작업은 어느 순간에도 슬롯을 **최대 1개만** 쥔다. 화면·API는 GPU 대기열과 CPU 대기열을 따로 보여 준다.

## 1. 현재 구조(코드 확인, 863bfe0)

| 항목 | 현재 | 위치 |
|---|---|---|
| 워커 | 프로세스 1개(`InstanceLock` `state/physicsai-worker.lock`), 작업 스케줄러 `PhysicsAI-Worker`(`-m physicsai_worker`) | `lockfile.py`, `deploy/install-common.ps1:412` |
| 스레드 | `slot`(1) · `light`(1, 환경 점검 겸) · `preview0..k`(`geometry.view.max_concurrent`) · `hpc`(회수) · `heartbeat` · `housekeeping` · `gpu`(GpuMonitor) | `runtime.py` `start()` |
| 수령 | 폴링 `claim_interval_s`(2초). SLOT = `worker_slot`(id=1 단일 행) `FOR UPDATE` + generation CAS + 대상 `SKIP LOCKED`. LIGHT = 실행 중 LIGHT 0건일 때. PREVIEW = `pg_advisory_xact_lock(7317017)` + 실행 수 < 상한 | `job_lease.py` |
| 레인 | `JobTypeDef.lane` = SLOT·LIGHT·PREVIEW, 생성 시 `jobs.lane`에 고정. `ck_jobs_holds_slot`: `holds_slot = (RUNNING AND lane='SLOT')` | `job_types.py`, `tables/study_job.py` |
| 슬롯 해제 | step 종류 HPC_WAIT·COLLECT는 슬롯 없음(T5 → WAITING_HPC, 회수 후 T14 → QUEUED 맨 뒤) | `executor._run_steps`, `job_lease_end.release` |
| 자원 한도 | LOCAL 프로세스마다 Windows Job Object(코어 `max_logical_cores` 32·메모리 `max_memory_gb` 64·BELOW_NORMAL·KILL_ON_JOB_CLOSE), `run_parallel`은 Job 1개 공유. GPU 무제한 | `limiter/windows_job.py`, `limits.py` |
| 실행 중 추적 | `Worker.current_executor` 1개(하트비트 회계·종료 시 keeper 정지) | `runtime.py`, `executor.py` |
| API | `GET /queue` `{slot, running, queued, light{running,queued}, waiting_hpc, collecting}`, `POST /queue/{id}/move`(SLOT만, 전역 관리자). MCP 도구 `queue`·`system_status`(`slot_holder_job_id`)·`job_kinds.lane_info`(`uses_global_slot`)·plan `queue_ahead` | `services/jobs.queue_view`, `schemas/shell.py`, `mcp/*` |
| 화면 | 상단 칩 "대기열 실행 a · 대기 b" → 상태 서랍 `QueuePanel`(실행 중 1·대기·가벼운 작업·PBS) | `shell/RunStatus.tsx`, `panels/QueuePanel.tsx` |
| GPU 조회 | S19 `GpuMonitor`(nvidia-smi 캐시, `worker.gpu_query_timeout_s`·`gpu_backoff_*`) — 표시용, 스케줄링에는 안 씀 | `gpu_monitor.py` |
| 배포 | `update-repo.ps1`: 활성 작업 검사(`jobs.state IN (QUEUED,RUNNING,WAITING_HPC,COLLECTING)` — 레인 무관) → 작업 중지 → migration → 시작 | `install-common.ps1:572·580` |
| 대시보드 연동 | 대시보드는 PhysicsAI 대기열을 표시하지 않는다(DB 직접 활성 작업 수만, D3-39). 변경 없음 | – |

**학습 경로**: 서버 GPU에서 학습을 돌리는 코드 경로는 **없다**. ③-2 `PACKAGE_EXPORT`는 HPC용 `edspy --train` 명령 **안내문만** 쓰고(`steps/stage3_model/package.py`), `MODEL_REGISTER`는 복사·로그 해석뿐이다(2026-10-08 결정 "HPC 학습은 사용자가 직접"). → 질문 후보로만 남김(§11).

## 2. 결정 요약(JQ-1~JQ-14)

| ID | 결정 |
|---|---|
| JQ-1 | **자원 종류는 step 단위**: `StepDef.res ∈ {cpu, gpu, none}`. GPU = PhysicsAI 추론 step만(§3.1). 그 밖 LOCAL·HPC_SUBMIT = cpu, INTERNAL = none(중립 — 지금 쥔 슬롯에서 실행), HPC_WAIT·COLLECT = 슬롯 없음(기존) |
| JQ-2 | **GPU 동시 1 고정**(설정 키 없음 — 설정으로 늘릴 수 없다). 근거: 서버 GPU 메모리 초과 이력(input-kind P2), S19 동시 예측 철회(2026-10-20) |
| JQ-3 | 혼합 작업 = **구간별 슬롯 전환**(사용자 결정, §4 비교). 경계에서 새 전이 **T17 `RUNNING → QUEUED`**(lane = 다음 구간)로 슬롯·lease를 반납하고 다시 선다 |
| JQ-4 | **한 작업은 슬롯을 최대 1개**만 쥔다. GPU를 기다리는 동안 CPU 슬롯을 **반납**한다(§5 — 교착·기아 근거) |
| JQ-5 | 재진입 순번 = **원래 등록 순번**(`jobs.queue_origin_seq`, T1에서 고정). 재진입 작업은 뒤에 등록된 작업보다 앞에 선다. T14(PBS 회수 후)는 2026-10-07 결정대로 맨 뒤 유지 |
| JQ-6 | CPU 슬롯 = 개수 상한 `worker.queues.cpu.max_concurrent`(기본 **4**, 1~16, 2026-10-22 사용자 결정) + 수령 시 여유 메모리 문 `cpu.min_free_memory_gb`(기본 8). 넘으면 CPU 대기열에서 대기 |
| JQ-7 | 전체 자원 상한 = 워커 **부모 Job Object**(기존 `max_logical_cores`·`max_memory_gb`), step Job Object는 그 안에 중첩. 중첩 불가 시 작업당 몫(코어·메모리 ÷ (N+1))으로 폴백 + 환경 점검 경고 |
| JQ-8 | LIGHT·PREVIEW 레인은 **그대로**(CPU 상한에 세지 않음). 화면에서는 CPU 대기열 아래 "가벼운 작업"으로 묶어 표시. **변경 메모(2026-10-22 사용자 결정)**: `CONTOUR_3D`(C3_* step)는 LIGHT가 아니라 **CPU 대기열**(구간 레인 SLOT, 동시 `cpu.max_concurrent`에 센다)에서 실행한다 — 환경 점검·그 밖 LIGHT 종류는 LIGHT 유지. migration 0022가 대기 중인 옛 LIGHT `CONTOUR_3D` 행을 CPU로 옮긴다(downgrade는 되돌림). `geometry-view.md` §13.5의 "LIGHT 레인" 서술은 v0.2.9 2차 통합에서 CPU 대기열로 고쳤다(contour3d-default C3D-13·C3D-C1) |
| JQ-9 | 워커 프로세스 1개 유지. 스레드: `gpu-slot`(1) + `cpu-slot0..N-1`. GPU 구간은 `gpu-slot` 스레드에서만 실행(프로세스 안 이중 직렬화) |
| JQ-10 | DB: `jobs.lane` = **현재 대기열**(`CPU|GPU|LIGHT|PREVIEW`), `worker_slot`(id=1)은 **GPU 슬롯**으로 재사용, `holds_slot = (RUNNING AND lane='GPU')`. migration `0022_job_queues` |
| JQ-11 | `JobTypeDef.lane`(정적 분류 SLOT·LIGHT·PREVIEW)은 바꾸지 않는다 — SLOT = "구간 레인(CPU·GPU 전환)". 용어집·MCP 레지스트리 변경 최소 |
| JQ-12 | `GET /queue`에 `gpu`·`cpu` 객체 **추가**(기존 필드는 deprecated로 유지 → MCP 도구 이름 불변) |
| JQ-13 | 순서 이동은 **같은 대기열 안에서만**(GPU·CPU 각각). 다른 대기열 작업은 409 `JOB_NOT_QUEUED` |
| JQ-14 | 알림: `JOB_STARTED`·`MY_TURN_NEXT`는 작업당 1회(첫 시작 전만). T17 재진입은 알림 없음 |

## 3. 자원 분류

### 3.1 GPU step(추론) — 전부 3개

| step | job_type | 근거 | 비고 |
|---|---|---|---|
| `EDSPY_PREDICT` | PREDICT(단건·④ 일괄 하위·⑥ 검증 하위) | PhysicsAI 예측(추론) | 핵심 대상 |
| `EDSPY_SCORE` | EVALUATE(③-5) | 평가용 psdata 전체를 모델로 추론(2026-10-08 "로컬 GPU 평가") | **추론으로 해석해 GPU**(사용자 기준 "예측(추론)"). 질문 후보 Q2 |
| `HST_OPTIMIZE` | OPTIMIZE(⑤ HyperStudy 레거시) | HyperStudy가 반복마다 원본 런처(pyd)로 edspy 예측을 직접 실행 — 플랫폼이 반복 사이에 끼어들 수 없음 | **예외: step 전체가 GPU**(§4.3). ⑥ 기본은 SURROGATE_OPT(opt-native ON-2) |

### 3.2 CPU step(나머지 전부 — 사용자 결정 "그 밖 모든 단계는 CPU")

| 묶음 | step(대표) | 실제 자원 |
|---|---|---|
| 형상·메시·조립 | `GEOM_UPDATE`·`MESH`(NX·SimLab 또는 paicad), `SIMLAB_EXTRACT`, `NP_EXTRACT`·`NP_TAG`·`NP_VIEW`·`BL_MAP`·`TX_VIEW`, `FV_MESH` | CPU·메모리, Altair 라이선스(SimLab) |
| DOE·입력 생성 | `HST_GEN_RADIOSS`(①-3, 플랫폼 생성은 `run_parallel` M개), `BP_GEN`(④ 일괄, `run_parallel`) | CPU 다중 프로세스 |
| 추출·캡처 | `RESPONSE_EXTRACT(_RUNS)`·`CONTOUR_PREVIEW`·`CONTOUR_CAPTURE`·`C3_EXTRACT`·`C3_CONVERT`(`CONTOUR_3D`, contour3d-default C3D-13)·`PV_EXTRACT`·`FV_EXTRACT`·`FV_CURVE`·`FV_CAPTURE`·`EQ_EXTRACT`·`HW_*`·`HVTRANS_CURATE` | HyperView·hvtrans(라이선스), 캡처는 OpenGL — GPU 메모리 소량 가능(리스크 R6) |
| 데이터셋 | `EDSPY_DATASET_TRAIN`·`EDSPY_DATASET_EVAL` | edspy 전처리(h3d → psdata), 모델 추론 없음 → CPU. 서버 실측으로 CUDA 사용 여부 확인(V-JQ-15) |
| PBS·SCX 제출 | `HPC_SUBMIT`(PREDICT_VERIFY·FEM_VERIFY·TD_SOLVE) | 원격 해석 — 로컬은 제출만. 대기·회수는 슬롯 없음(기존) |
| 영상 변환 등 기타 LOCAL | `video_transcode` 등 | CPU |

INTERNAL(none): `*_PREP`·`*_REGISTER`·`*_TABLE`, `SO_FIT`·`SO_PROPOSE`(numpy·scipy), `EQ_COMPUTE`, `DS_SCAN` 등 — 지금 쥔 슬롯(CPU 또는 GPU)에서 그대로 실행한다. 작업 시작 시 첫 구간이 INTERNAL만이면 CPU.

### 3.3 job_type별 구간 흐름

| job_type | 구간(→ = 슬롯 전환) | 초기 대기열 |
|---|---|---|
| PREDICT(일반) | CPU[PR_PREP·TPL·GEOM·MESH·RAD] → **GPU[EDSPY_PREDICT]** → CPU[CONTOUR_PREVIEW·CURVE·RESPONSE·TABLE·CAPTURE] | CPU |
| PREDICT(prepared, ④ 일괄·⑥ 하위) | CPU[PR_PREP(복사 검사)] → **GPU** → CPU | CPU(아래 주) |
| PREDICT_BATCH(④ 일괄) | CPU[BP_PREP·BP_GEN·BP_ENQUEUE] — 하위 PREDICT가 각자 GPU 구간을 가진다. FEM 검증(FEM_VERIFY)은 CPU+PBS | CPU |
| SURROGATE_OPT(⑥ 내장) | CPU(전부 INTERNAL). 반복마다 예측은 검증 PREDICT_BATCH의 하위 PREDICT가 **GPU 구간에서만** 슬롯을 잡았다 놓는다 | CPU |
| EVALUATE | **GPU[EV_PREP·EDSPY_SCORE·EV_PARSE]**(준비·해석은 짧은 INTERNAL) | GPU(아래 예외) |
| OPTIMIZE(레거시) | **GPU[OP_PREP·HST_OPTIMIZE·OP_SUMMARY]** | GPU |
| FEM_VERIFY·PREDICT_VERIFY·TD_SOLVE | CPU → PBS 대기(슬롯 없음) → 회수 → CPU(T14) | CPU |
| 그 밖 SLOT 종류 전부 | CPU | CPU |
| LIGHT·PREVIEW 종류(`CONTOUR_3D` 제외 — CPU, 전환 없음. PREVIEW = `GEOM_PREVIEW`·`ASM_MATCH`, 3차 통합 확인) | 기존 레인 그대로 | LIGHT·PREVIEW |

- **초기 대기열 규칙**(core 한 곳 `physicsai_core/queues.py` `initial_lane(job_type, params, resume_from_step)`): 기본 **CPU**(첫 구간의 INTERNAL·준비 복사는 CPU 슬롯에서 — GPU를 준비 작업에 쓰지 않는다). 예외 = 작업이 "짧은 INTERNAL + GPU step 1개 + 짧은 INTERNAL"로만 된 EVALUATE·OPTIMIZE는 GPU로 시작(전환 2회 절약, `queues.GPU_START_TYPES` 상수). 재개(`resume_from_step`)면 재개 step 기준으로 같은 규칙.
- prepared PREDICT의 `GEOM_UPDATE`·`MESH` 건너뛰기는 실행 중 판정(`StepSkipped`)이므로 전환 판정은 **res = cpu인 step을 만나도 그 step이 건너뛰기 대상이면 전환하지 않는다** — `queues.skip_without_slot(job, step_key)`(params만 보는 순수 함수, prepared PREDICT의 GEOM_UPDATE·MESH = true)를 executor가 먼저 부른다.
- **현장 보정 설정** `worker.queues.step_resource: {STEP_KEY: cpu|gpu}`(기본 `{}`): 실측으로 분류가 틀렸을 때(예: 캡처가 GPU 메모리를 크게 씀) 코드 릴리스 없이 바꾼다. 검증: 알려진 LOCAL step 키만, 값은 `cpu|gpu`, HPC_* 키 거부.

## 4. 혼합 작업 처리 — 대안 비교

| 대안 | 내용 | 장점 | 단점 | 판정 |
|---|---|---|---|---|
| A. 작업 전체를 GPU로 | GPU step이 하나라도 있는 job_type = GPU 대기열 | 구현 최소, GPU 1 확실 | PREDICT 시간의 대부분(형상·메시·추출·캡처)이 GPU 대기열을 막음 → ④ 일괄·⑥ 처리량이 지금과 같음. 요구("CPU는 GPU 때문에 대기 없이") 위반 | 기각(사용자 결정) |
| **B. GPU 구간만 GPU 슬롯(경계 전환, DB 영속)** | step 경계에서 T17로 슬롯 반납·다른 대기열 재진입 | 하위 PREDICT들이 **파이프라인**(GPU는 추론만 연달아, 앞 작업의 추출·캡처는 CPU 슬롯에서 병렬). 크래시 복구·순번 표시가 기존 대기열 장치 그대로. job_type·결과·종료 훅·MCP 종류 불변 | 전환마다 수령 지연(≤ `claim_interval_s`), 상태 머신 전이 1개 추가, PREDICT가 화면에서 대기열을 옮겨 다님 | **권고·채택** |
| B'. 프로세스 안 GPU 잠금(CPU 슬롯을 쥔 채 대기) | 워커 메모리 세마포어로 GPU 구간만 직렬화 | 코드 변경 작음 | GPU 대기자가 CPU 슬롯을 점유 → CPU 기아(§5), 대기 순번이 DB·화면에 없음, 크래시 시 순서 유실 | 기각 |
| C. 하위 작업 분할 | PREDICT → PREP(cpu)·INFER(gpu)·POST(cpu) 별도 job | 대기열 모델 단순(작업 = 단일 자원) | 새 job_type 3개·종료 훅·결과 병합·재시도·MCP `JOB_KINDS`·작업 목록 3배, ④·⑥ 집계 회귀 범위 큼 | 기각 |

### 4.3 예외 — HyperStudy 레거시 OPTIMIZE

`HST_OPTIMIZE`는 외부 프로세스 하나(HyperStudy) 안에서 예측을 반복한다. 반복 사이에 슬롯을 놓으려면 원본 런처(pyd, 플랫폼이 import·수정하지 않음 — AGENTS 보안)를 바꿔야 하므로 **step 전체가 GPU 슬롯**을 쥔다. 사용자 결정의 "⑥ 최적화: 반복마다 예측 호출만 GPU"는 ⑥ 기본 경로인 SURROGATE_OPT(§3.3)에서 그대로 충족된다. 화면 GPU 대기열 행에 "HyperStudy 최적화(전체 GPU)" 표시. 앞으로 step 안에서 예측을 반복하는 기능(opt-direct 등)은 **하위 PREDICT 작업 또는 별도 GPU step으로 나눠야 한다**(step 안 GPU 잠금 API는 만들지 않는다 — §5 hold-and-wait 금지).

## 5. GPU 대기 중 CPU 슬롯: 반납(권고·채택)

| 관점 | 쥔 채 대기(hold) | **반납 후 재진입(release, 채택)** |
|---|---|---|
| 교착 | GPU 보유 작업이 다음 CPU 구간에서 CPU 슬롯을 기다리고, CPU 슬롯 N개를 GPU 대기자들이 쥐고 있으면 **순환 대기 → 교착**(GPU 보유자가 GPU를 쥔 채 CPU를 기다리는 구현이면 필연). GPU를 먼저 놓게 해도 hold-and-wait 자체는 남음 | 한 작업이 슬롯 ≤ 1 → Coffman의 **점유·대기 조건이 없어 교착 불가** |
| CPU 기아 | ④ 일괄 하위 50개가 CPU 슬롯을 쥐고 GPU를 기다리면 DOE·추출 등 순수 CPU 작업이 **GPU 때문에** 무기한 대기 → 사용자 요구 위반 | GPU 대기자는 CPU 슬롯을 쓰지 않음 → CPU 작업은 GPU와 무관하게 CPU 한도 안에서 바로 실행 |
| GPU 유휴 | GPU 보유자가 후처리 CPU 슬롯을 기다리는 동안 GPU 놀림 | 추론이 끝나면 즉시 GPU 반납 → 다음 추론 바로 시작 |
| GPU 기아 | – | GPU 대기열 FIFO(`queue_origin_seq`), GPU 보유 구간은 추론 step뿐이라 짧음. 순수 GPU 작업(OPTIMIZE 레거시)이 길면 그동안 대기(R4) |
| 비용 | 전환 없음 | 전환당 수령 1회(≤ 2초) + 후처리가 CPU 대기열에서 기다릴 수 있음(원래 순번이라 새 작업보다 앞) |

규칙: (1) executor는 다음 실행 step의 필요 종류가 지금 쥔 슬롯과 다르면 그 step을 시작하지 않고 T17로 반납한다(그 step은 PENDING 유지). (2) GPU 슬롯 수령 문에서 CPU 슬롯을 함께 확인하지 않는다(독립). (3) step 안에서 다른 종류의 슬롯을 요청하는 경로는 없다.

## 6. 수령·잠금 설계

### 6.1 수령

| 대기열 | 수령 함수(`job_lease.py`) | 직렬화 | 조건 |
|---|---|---|---|
| GPU | `claim_gpu` = 기존 `claim_slot`의 이름·대상만 바꿈(`worker_slot` id=1 `FOR UPDATE` + generation CAS) | 행 잠금 + CAS | 슬롯 비었거나 만료(만료면 보유 작업 T9), 대상 `lane='GPU' AND QUEUED` 최소 `queue_seq` `SKIP LOCKED` |
| CPU | `claim_cpu(max_concurrent)` | `pg_advisory_xact_lock(CPU_CLAIM_LOCK = 7_317_018)` | `count(RUNNING AND lane='CPU') < max_concurrent`, 워커 측 `psutil.virtual_memory().available ≥ min_free_memory_gb`(호출 전 검사, 0이면 생략), 대상 최소 `queue_seq` |
| LIGHT·PREVIEW·COLLECTING | 기존 그대로 | 기존 | 기존 |

- 수령 결과에 `lane`이 있으므로 executor는 지금 쥔 종류를 안다. lease·renew·reap는 기존 CAS lease 그대로(GPU는 `slot=True`로 `worker_slot`도 갱신).
- **T17 전이**(`state_machine`: `(RUNNING, QUEUED): "T17"` — T14와 다른 출발 상태라 충돌 없음): `release(…, next_state=QUEUED, next_lane=…)` — `lane = next_lane`, `queue_seq = queue_origin_seq`, `queued_at = now()`, `holds_slot=false`, lease 비움, GPU였다면 `worker_slot` 비움, 알림 없음, `progress_pct`·step 기록 유지. `queue_origin_seq`는 T1에서 `queue_seq`와 같은 값으로 저장하고 바꾸지 않는다(순서 이동 때만 갱신, §8.2).
- `queue_seq`는 unique가 아니고 QUEUED일 때만 값이 있으므로(`ck_jobs_queue_seq`) 원래 값 재사용이 가능하다. 같은 값 충돌은 없다(작업당 1개).

### 6.2 워커 스레드·실행기

- `start()`: `gpu-slot` 스레드 1개 + `cpu-slot{i}` 스레드 `max_concurrent`개. 설정 변경 감지(`check_config_change`) 시 상한이 커지면 스레드를 그만큼 더 띄우고, 작아지면 남는 스레드는 수령 문(개수 검사)에서 걸러져 쉰다(실행 중 작업은 끝까지).
- `Worker.current_executor`(1개) → `Worker.executors: dict[job_id, Executor]`(잠금 보호). 하트비트 회계는 전부를 돌며 작업별 `{job_id, cpu_time_s, peak_memory_gb}` 목록, `stop()`은 모든 keeper를 멈춘다. PREVIEW 비추적 규칙은 유지.
- GPU 구간은 `gpu-slot` 스레드에서만 실행: CPU 스레드가 수령한 작업이 GPU step을 만나면 T17로 반납하고, GPU 스레드가 다시 수령한다. 워커가 1개(InstanceLock)이고 GPU 스레드가 1개이므로 **DB 슬롯 + 프로세스 안 단일 스레드**로 이중 보장(lease가 hang으로 만료돼 리퍼가 슬롯을 비워도, 같은 워커의 GPU 스레드는 앞 executor가 끝나기 전에는 새 작업을 받지 않음).
- 부모 Job Object(Windows, `worker.queues.total_cap: true` 기본): 워커 시작 시 1개 생성(코어 cpu_rate·메모리 = `limits_from_settings`), step Job Object(기존)는 프로세스를 부모에 먼저 넣고 자식 Job에 넣어 **중첩**(Windows 8/Server 2012+). 실패하면 작업당 몫 = 코어 `max(1, floor(cores/(N+1)))`·메모리 `max_memory_gb/(N+1)`로 폴백하고 환경 점검 `worker.job_nesting` WARN. POSIX(dev)는 작업당 몫. `run_parallel` 그룹은 작업 1개분 한도를 나눠 쓰는 기존 규칙 유지.

### 6.3 크래시 복구·호환

| 경우 | 처리 |
|---|---|
| 워커 사망(GPU 구간) | KILL_ON_JOB_CLOSE로 edspy 종료, lease 만료 → 리퍼 T9 INTERRUPTED, `worker_slot` 비움(기존) |
| 워커 사망(CPU 구간) | lease 만료 → T9. CPU 개수는 RUNNING 행 수라 자동 회복 |
| T17 직후 사망 | 작업은 QUEUED(다음 구간 대기열)에 영속 — 재시작 후 그대로 수령 |
| 재시도·`resume_from_step` | `initial_lane`이 재개 step 기준으로 계산 |
| 취소(재진입 대기 중) | 기존 T3(QUEUED → CANCELED), 남은 step CANCELED, 종료 훅(일괄 집계) 실행 — V-JQ-12 |
| 옛 워커 + 새 DB | 옛 코드는 `lane='SLOT'`만 수령 → **아무것도 받지 않음**(안전 실패). update-repo가 작업 중지 후 migration하므로 정상 경로에서는 발생 안 함 |
| update-repo 활성 작업 검사 | 상태 기준(레인 무관)이라 **변경 없음**. T17 대기 작업도 QUEUED로 세어진다. `-Force`로 올리면 실행 중 작업은 migration이 레인을 옮기고(§7) 재시작 후 lease 만료로 INTERRUPTED(기존 안내 문구 그대로) |

## 7. DB — migration `0022_job_queues`(down_revision `0021_uploads`)

1. `jobs.queue_origin_seq BIGINT NULL` 추가. 백필: QUEUED 행 = `queue_seq`, 그 밖 NULL(시작 후 T17 없이 끝난 옛 행은 필요 없음). 새 작업은 T1에서 채움. 재진입 시 NULL이면 새 `nextval`(옛 진행 중 작업 대비).
2. `ck_jobs_lane` 교체: `lane IN ('CPU','GPU','LIGHT','PREVIEW')`.
3. 데이터 변환(`lane='SLOT'` 행): migration 파일 안 정적 표 `GPU_STEPS = {'EDSPY_PREDICT','EDSPY_SCORE','HST_OPTIMIZE'}`(core import 금지 — migration 자립).
   - 비종결(QUEUED·WAITING_HPC·COLLECTING): 첫 PENDING step 중 LOCAL·HPC_SUBMIT의 키가 GPU_STEPS면 `GPU`, 아니면 `CPU`(EVALUATE·OPTIMIZE의 INTERNAL 선행 규칙 포함).
   - RUNNING(`-Force`일 때만 존재): RUNNING step 키 기준. `CPU`가 되면 `holds_slot=false`로 바꾸고 `worker_slot`을 비운다(lease는 남아 재시작 후 만료 → T9).
   - 종결: job_type이 EVALUATE·OPTIMIZE면 `GPU`, 그 밖 `CPU`(이력 표시용).
4. `ck_jobs_holds_slot` 교체: `holds_slot = (state = 'RUNNING' AND lane = 'GPU')`.
5. 인덱스 `ix_jobs_state_lane_seq` 그대로. `worker_slot` 표 이름·제약 그대로(의미만 GPU 슬롯 — 표 주석 갱신).
6. downgrade: `CPU|GPU → SLOT`, 제약 원복, `queue_origin_seq` 삭제. RUNNING인 CPU·GPU 행이 2개 이상이면 "실행 중 작업이 여럿이라 이전 구조로 되돌릴 수 없습니다 — 작업을 멈춘 뒤 다시 실행하세요"로 중단.

## 8. API·화면·MCP

### 8.1 `GET /queue` 응답(추가 필드, 기존 필드 유지)

```text
{
  "gpu": {"limit": 1, "running": [JobSummary], "queued": [JobSummary], "since": "…"},
  "cpu": {"limit": 3, "running": [JobSummary], "queued": [JobSummary], "min_free_memory_gb": 8, "memory_gate": "ok|low|null"},
  "light": {"running": JobSummary|null, "queued": [JobSummary]},
  "waiting_hpc": [JobSummary], "collecting": [JobSummary],
  "slot": {"holder_job_id": "…", "since": "…"},
  "running": JobSummary|null, "queued": [JobSummary]
}
```

- `gpu.running` 길이 ≤ 1, `cpu.running` ≤ `limit`(설정을 줄인 직후에는 잠시 넘을 수 있음 — 화면은 그대로 표시). 대기 목록은 `queue_seq` 순, `JobSummary.queue_position`은 **자기 대기열 안 순번**(1부터).
- `JobSummary.lane` 값 = `CPU|GPU|LIGHT|PREVIEW`(OpenAPI enum에 `SLOT`은 deprecated로 남김 — 내보내지 않음). 새 선택 필드 `resumed: bool`(T17로 재진입한 대기 = 진행률 > 0).
- `memory_gate` = 워커 마지막 하트비트의 여유 메모리 판정(`low`면 CPU 대기 사유 표시). 워커 표본 없으면 null.
- **deprecated**(다음 깨지는 릴리스에서 `queue_v2`로 정리): `slot` = GPU 슬롯, `running` = `gpu.running[0] ?? cpu.running[0] ?? null`, `queued` = GPU·CPU 대기를 `queue_seq` 순으로 합친 목록. 의미가 넓어질 뿐 모양은 같으므로 MCP 도구 `queue`는 **이름 불변**(mcp.md MR-12 — 필드 추가만).
- `POST /queue/{job_id}/move`: 대상 작업의 현재 대기열(GPU 또는 CPU) 안에서 이동. LIGHT·PREVIEW·실행 중은 409 `JOB_NOT_QUEUED`("대기 중인 GPU·CPU 작업만 순서를 바꿀 수 있습니다"). 이동은 그 대기열 QUEUED 전부를 잠그고 `queue_seq`와 `queue_origin_seq`를 함께 다시 부여(이후 재진입에도 바뀐 순서 유지). 권한(전역 관리자)·CSRF·감사 그대로.
- `/resources`: `job`(기존, = GPU 작업 우선 1건) 유지 + `jobs: [{job_id, lane, cpu_time_s, peak_memory_gb}]`, `limits`에 `cpu_max_concurrent`·`total_cap`(`nested|share|off`) 추가(모두 선택).

### 8.2 화면(필수 요소만)

- 상단 칩: `GPU 실행 a · 대기 b | CPU 실행 c/N · 대기 d`(내 작업 실행 중이면 기존 강조). 좁은 폭에서는 `GPU a/b · CPU c/d`.
- 상태 서랍 `QueuePanel` = 두 구역을 위아래로 분리:
  1. **GPU 대기열** — 머리말 `1개씩 · 대기 n건`. 실행 중(최대 1행: 진행률·경과·현재 step) / 대기(순번).
  2. **CPU 대기열** — 머리말 `동시 N개 · 실행 r · 대기 n건`(메모리 문 `low`면 `· 여유 메모리 부족으로 대기`). 실행 중(최대 N행) / 대기(순번). 그 아래 기존 "가벼운 작업(슬롯 불필요)"·"PBS 대기·회수" 소구역 유지(있을 때만).
- 행 요소(기존 재사용): 순번 또는 상태 점, 단계 배지, 작업명(작업 화면 링크), Study·등록자, 내 작업 표시, 실행 중 진행률, 전역 관리자 ▲▼·취소. 재진입 대기 행은 `이어서 · 40%` 한 마디만 추가. 그 밖 새 요소 없음.
- 작업 화면 상태 문구: QUEUED + `resumed`이면 "GPU 대기 중(예측 차례 대기)" / "CPU 대기 중(후처리 대기)".

### 8.3 MCP·기타 소비자

| 대상 | 변경 |
|---|---|
| `system_status`(`GET /mcp/system`) | `queue_head`(GPU·CPU 합친 앞 5개) 유지, `slot_holder_job_id`(= GPU) 유지, 추가 `gpu_holder_job_id`·`cpu_running`·`cpu_limit` |
| `job_kinds.lane_info` | `{lane, uses_global_slot}` 유지(`uses_global_slot` = 그 종류에 GPU step이 있음, deprecated), 추가 `segments: ["cpu","gpu","cpu"]` |
| plan `queue_ahead` | 초기 대기열(`initial_lane`)의 대기 수 |
| 용어집 | `JobTypeDef.lane` 불변. 새 용어 `GPU 대기열`·`CPU 대기열`·`구간 전환` `ko` 각 1줄 |
| 알림 `recompute_my_turn` | GPU·CPU 각각: 그 대기열이 가득(GPU 보유 중 / CPU = 상한)일 때 1번 작업에 `MY_TURN_NEXT`, 단 `started_at IS NULL`인 작업만 |
| 대시보드 | 변경 없음 |

## 9. 설정(`worker.queues`, 예시 yaml은 주석)

| 키 | 기본 | 범위·검증 | 근거 |
|---|---|---|---|
| `worker.queues.cpu.max_concurrent` | **4**(사용자 결정 Q1) | 정수 1~16 | 코어: 유효 32코어에서 SimLab·HyperView 1세션이 실측상 몇 코어 수준이고 DOE·일괄 생성은 작업 안에서 이미 `run_parallel` M개 → 동시 3 + GPU 작업 1이 32코어 안. 메모리: 메싱 8~16 GB × 3 ≤ 64 GB 상한. **라이선스**: Altair 유닛(SimLab·HyperView·HyperStudy) 동시 사용 수가 미확인 → 보수적 3(Q1) |
| `worker.queues.cpu.min_free_memory_gb` | 8 | 0 이상(0 = 검사 안 함), `max_memory_gb` 미만 | 메싱 1건 최소치. GPU 수령에는 적용 안 함 |
| `worker.queues.total_cap` | true | bool | §6.2 부모 Job Object. false면 작업당 몫 |
| `worker.queues.step_resource` | `{}` | 알려진 LOCAL step 키 → `cpu|gpu` | §3.3 현장 보정 |
| (GPU 동시 수) | 1 고정 | **키 없음** — `worker.queues.gpu`가 있으면 검증 오류("GPU 작업은 동시에 1개만 실행합니다") | JQ-2 |

검증은 `config/validate_queues.py`(validate.py가 1줄로 호출 — S19 `validate_gpu.py` 관례), 설정 변경은 재시작 없이 다음 수령부터.

## 10. 시험(V-JQ-n) — `scripts/test-all`(Linux·PostgreSQL), 가짜 도구 사용

| ID | 내용 |
|---|---|
| V-JQ-1 | 정적: 모든 LOCAL·HPC_SUBMIT step에 `res`가 있고 GPU 집합 = {EDSPY_PREDICT, EDSPY_SCORE, HST_OPTIMIZE}. 새 job_type이 `res`를 빠뜨리면 실패(`test_step_registry` 확장) |
| V-JQ-2 | `initial_lane`·`skip_without_slot`: PREDICT 일반·prepared → CPU(prepared는 GEOM_UPDATE·MESH에서 전환 없음), EVALUATE·OPTIMIZE → GPU, 그 밖 SLOT → CPU, `resume_from_step` 반영, `step_resource` 덮어쓰기 |
| V-JQ-3 | **GPU 동시성**: Worker 2개(InstanceLock 우회, 같은 DB) × GPU 수령 스레드 8개가 GPU 작업 40건을 동시에 수령·실행(가짜 edspy 0.2초) — 표본 추적에서 `RUNNING AND lane='GPU'` 항상 ≤ 1, `worker_slot` 보유자와 일치, 모두 SUCCEEDED |
| V-JQ-4 | **CPU 상한**: `max_concurrent=3`, CPU 작업 12건, 수령 스레드 6개 동시 — RUNNING CPU 최대 3·최소 한 번은 3 도달, advisory lock 없이 돌리면(시험용 우회) 초과가 재현됨을 대조 |
| V-JQ-5 | **CPU는 GPU를 기다리지 않음**: GPU 작업 실행 중(가짜 edspy 5초) + GPU 대기 5건 상태에서 TD_DOE_GEN·TD_EXTRACT_PARAMS가 `claim_interval_s` 2회 안에 RUNNING |
| V-JQ-6 | **구간 전환**: PREDICT 1건 — lane 이력 CPU → GPU → CPU, T17 2회, QUEUED 동안 lease·`holds_slot` 없음, EDSPY 종료 직후 GPU 슬롯 해제(다음 GPU 작업 즉시 수령), 결과·step 기록이 전환 없는 실행과 같음 |
| V-JQ-7 | **슬롯 ≤ 1·교착 없음**: `max_concurrent=1`에서 PREDICT 4건 + DOE 1건 + EVALUATE 1건이 제한 시간(60초) 안에 모두 끝남, 계측으로 한 작업이 두 슬롯을 동시에 쥔 적 없음 |
| V-JQ-8 | **순번**: 재진입 작업이 뒤에 등록된 작업보다 앞(`queue_origin_seq`), T14는 맨 뒤(회귀). 같은 대기열 이동 → 재진입 후에도 순서 유지, 다른 대기열·LIGHT 이동 409 |
| V-JQ-9 | **④ 일괄 파이프라인**: 하위 PREDICT 6건(prepared) — 어느 순간에도 GPU 실행 ≤ 1, 한 하위의 추출·캡처와 다음 하위의 추론이 겹치는 구간이 존재, 배치 집계(`batch_on_job_end`) 정상. ⑥ SURROGATE_OPT 1반복도 같은 성질 |
| V-JQ-10 | **크래시 복구**: GPU 구간·CPU 구간·T17 직후 각각 워커 사망 모사(`claim_only`·keeper pause) → 리퍼 T9·슬롯·개수 회복, T17 대기 작업은 재시작 후 이어서 실행 |
| V-JQ-11 | **migration 0022**: 픽스처(SLOT QUEUED PREDICT@EDSPY·DOE·EVALUATE, WAITING_HPC TD_SOLVE, RUNNING 2건, 종결 행) up → lane·holds_slot·worker_slot·origin_seq 기대값, 제약 위반 0. 옛 `claim_slot`(lane='SLOT') 질의가 0건. downgrade 원복·RUNNING 2건이면 중단 메시지 |
| V-JQ-12 | 재진입 대기 중 취소 → step CANCELED·종료 훅 실행, 알림 `JOB_STARTED`·`MY_TURN_NEXT` 작업당 1회(재진입 시 없음) |
| V-JQ-13 | 메모리 문: 가짜 `available` < `min_free_memory_gb` → CPU 수령 0·GPU 수령 정상·`/queue cpu.memory_gate = low`. 설정 검증(`max_concurrent` 0·17, `worker.queues.gpu` 존재, 모르는 step 키) 오류 |
| V-JQ-14 | API·MCP: `/queue` gpu·cpu 분리·자기 대기열 순번·deprecated 필드 값, `backend/openapi.json` 갱신, MCP 생성기 `--check` 통과(새 도구 이름 없음, V-MCP-9 회귀), `system_status` 추가 필드, `/resources.jobs` |
| V-JQ-15 | 프런트(`__tests__/queue`): 두 구역·칩 문구·관리자 ▲▼가 각 구역 안에서만·`resumed` 표시·빈 상태, mock 엔진이 구간 전환을 흉내 |
| V-JQ-16 | **서버 확인(E, Windows 현장 — Linux 시험을 대체하지 않음)**: ④ 일괄 20 run + ① DOE 동시 실행 중 `nvidia-smi --query-compute-apps` 1초 표본에서 edspy 프로세스 항상 ≤ 1, GPU 메모리 초과 0. 부모 Job Object 중첩 성공(`total_cap = nested`). DATASET_CREATE 실행 중 GPU 프로세스 0(CPU 분류 확인 — 있으면 `step_resource`로 gpu) |

## 11. 리스크·미결

| ID | 리스크 | 대응 |
|---|---|---|
| R1 | Altair 라이선스 유닛 부족(CPU 동시 3 + 작업 안 `run_parallel` M) → LICENSE 실패 | 기본 3(Q1), 실패 코드 그대로 노출. 라이선스 그룹 상한은 범위 밖(필요 시 후속 `cpu.altair_max_concurrent`) |
| R2 | 메모리 합계 초과 시 임의 작업의 할당 실패 | 부모 Job Object로 총량 고정 + 수령 메모리 문. 실패는 기존 `MEMORY_LIMIT` 경로 |
| R3 | 부모 Job Object 중첩이 현장(작업 스케줄러 세션·정책)에서 거부 | 작업당 몫 폴백 + 환경 점검 WARN, V-JQ-16 |
| R4 | 레거시 OPTIMIZE(HyperStudy)가 GPU를 수 시간 독점 → 예측 대기 | §4.3 예외 명시·화면 표시. ⑥ 기본은 SURROGATE_OPT |
| R5 | EDSPY_SCORE를 GPU로 둔 해석이 사용자 의도와 다를 수 있음 | Q2. `step_resource`로 즉시 변경 가능 |
| R6 | HyperView 캡처(OpenGL)·edspy 데이터셋이 GPU 메모리를 일부 사용 | CPU 분류 유지, V-JQ-16 실측, 필요 시 `step_resource` |
| R7 | 서버 밖 GPU 사용(수동 edspy 등)은 슬롯이 모름 | 범위 밖. 운영 안내 |
| R8 | 단건 예측 지연: 후처리가 CPU 대기열에서 기다림 | 원래 순번 재진입(JQ-5)으로 새 작업보다 앞. 전환당 ≤ 2초 |
| R9 | `current_executor` 단일 가정이 여러 곳(하트비트·stop·자원 표본) | §6.2 목록화, V-JQ-10·14 |
| R10 | AI 루트 디스크 I/O 경합(동시 복사·메싱) | 관찰 후 조정(설정 상한 낮추기) |
| R11 | deprecated `running`·`queued` 의미 확장을 읽는 외부 스크립트 | 모양 불변, 문서·openapi description에 명시 |

**결정(2026-10-22 사용자)**: Q1 CPU 동시 기본 4 · Q2 EDSPY_SCORE는 GPU · Q3 HST_OPTIMIZE는 step 전체 GPU 점유 예외. (원 질문 후보:) Q1 CPU 동시 기본값(3) — 서버 Altair 라이선스 여유에 맞춰 2·4로? · Q2 ③-5 평가(EDSPY_SCORE)를 추론으로 보아 GPU 대기열로 보낼지 · Q3 HyperStudy 레거시 최적화는 step 전체 GPU 점유(예외)로 둘지, 아니면 GPU 대기열 대신 실행 자체를 막을지. (서버 GPU 학습 경로는 없음 — §1, 질문 불필요)

## 12. 변경 범위·소유

| 소유 | 파일(예정) |
|---|---|
| Impl-Backend(core) | `job_types.py`(`StepDef.res`), 새 `queues.py`(`initial_lane`·`skip_without_slot`·`step_res`), `state_machine.py`(T17), `db/tables/study_job.py`(제약·컬럼), `repositories/job_lease.py`(`claim_gpu`·`claim_cpu`), `job_lease_end.py`(`release(next_lane)`), `jobs.py`(insert lane·origin, `move_in_queue` 대기열별), `queue.py`, `notifications.py`(대기열별 차례), `config/schema.py`·새 `validate_queues.py`, `limits.py`(작업당 몫) |
| Impl-Backend(worker) | `runtime.py`(스레드·`executors`), `executor.py`(경계 전환), `limiter/windows_job*.py`(부모 Job·중첩), `env_check.py`(`worker.job_nesting`), `resources.py`(작업 목록) |
| Impl-Backend(API·MCP) | `services/jobs.queue_view`·`move_job`, `schemas/shell.py`, `services/common.job_summary`(`resumed`), `services/mcp.system_status`, `mcp/job_kinds.lane_info`·`queue_ahead`, `mcp/glossary.py`, `backend/openapi.json` |
| Impl-Backend(migration·배포) | `migrations/versions/0022_job_queues.py`. `deploy/*.ps1` **변경 없음**(활성 작업 검사 레인 무관), 예시 설정 주석만(`config/`) |
| Impl-Frontend | `panels/QueuePanel.tsx`, `shell/RunStatus.tsx`(칩·`queueCounts`), `api/types.ts`, `mock/engine.ts`·`ops.ts`, `__tests__/queue`, `frontend-dist/` 재생성 |
| Plan | 이 문서, platform.md §7.2·§7.3·§11·§16.2에 "job-queues.md로 대체" 변경 메모, architecture.md §1 갱신(구현 후) |

병합 순서: BE-JQ1(core·migration·API) → BE-JQ2(워커 스레드·전환·부모 Job)는 **같은 브랜치에서 순차, 중간 상태 병합 금지**(migration 뒤 옛 워커 코드는 아무것도 받지 않음) → FE → Verifier(V-JQ-1~15) → 현장 V-JQ-16.

## 변경 메모

- JQ-C0(2026-10-22): 초안. 사용자 결정 반영 — 구간별 분리(생성 CPU·예측 GPU·FEM 검증 CPU), GPU = PhysicsAI 추론뿐, GPU 대기 중 CPU 슬롯 반납(교착·기아 근거 §5).
