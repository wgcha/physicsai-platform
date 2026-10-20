# 계약: ⑥ 대리모델 없는 직접 최적화 — opt-direct

작성: Plan, 2026-10-21. 기준: 브랜치 `feat/r1-directopt` 18dc408(`MIGRATION_HEAD` = `0018_equiv_check`).
우선순위: **이 문서 > [opt-native.md](opt-native.md) > [s17_multiobj.md](s17_multiobj.md)(phase3 §22) > [s12_s13.md](s12_s13.md)(§18) > [phase3.md](phase3.md)**. 형상 생성은 [geometry-engine.md](geometry-engine.md)(§7.3.6~§7.3.8), 해석 제출은 phase2 §6.4(①-4 TD_SOLVE)·[s20_scx_version.md](s20_scx_version.md)를 따른다. 1·2·3차 원칙(단일 슬롯 FIFO, 설정만, AI 루트만, `_backup`, 한국어, 필수 UI, DB에는 수치 요약만)은 그대로다.
ID 규칙: 결정 `OD-n`, 시험 `V-OD-n`, 변경 메모 `OD-Cn`.

## 0. 사용자 요청(2026-10-21)

1. **대리모델 없이 하는 유전 최적화**: GA·NSGA-II 집단을 대리모델이 아니라 실제 평가 체인으로 평가한다(opt-native §15 미결 1의 해소).
2. **대리모델 없는 직접 최적화 기법**(국소·무미분)을 함께 추가한다.

## 1. 현황(코드 확인, 18dc408)

| # | 위치 | 내용 | 이 계약의 처리 |
|---|---|---|---|
| C1 | `surrogate/evo.py`·`evo_ops.py`·`evo_sort.py` | GA·NSGA-II 연산자(경계 SBX·다항 변이·정수·범주·제약 지배·비지배 정렬·crowding). `evo.run`은 동기 루프(`evaluate(X)` 콜백, rng 1개) | 연산자 **import만**, 파일 변경 금지(OD-4) |
| C2 | `SURROGATE_OPT` 반복 작업 + 소유 `PREDICT_BATCH` + 종료 훅 `surrogate_opts.on_batch_done` | 반복 r 작업이 배치를 등록하고, 배치 DONE이면 훅이 r+1 작업을 넣는다(슬롯은 반복 작업 동안만) | 같은 패턴으로 **세대 = 배치**(OD-3) |
| C3 | ④ `PREDICT_BATCH` BP_GEN(`run_parallel`, 동시 = min(배치 `multi_execution`, `train_data.max_multi_execution`)) → 하위 PREDICT(전역 SLOT FIFO, 1개씩) → RESPONSE_EXTRACT(`response_tcl`·CURVE `perf_value`) | native = `batch_native.gen_one`(paicad), altair = `run_chain` | `predict` 평가자(§5.1) |
| C4 | ① `TD_DOE_GEN`(platform·native, `sampling.kind = table`) → `TD_SOLVE`(PBS·SCX, HPC_WAIT 슬롯 미점유) → `TD_RESP_EXTRACT`(①-6, **CURVE 성능은 조용히 건너뜀** — s17 §22.3 `SILENT_REASONS`) | 사용자가 단계마다 실행 | `solver` 평가자(§5.2), 단계 연결은 종료 훅 |
| C5 | `surrogate_opt_iters.kind` CHECK(EXPLORE·REUSE·VERIFY·FINAL·EXTRA), `batch_id` NOT NULL, `surrogate_opts.model_id` NOT NULL, status 7종 | 세대 행·해석 DOE 연결·일시정지를 담을 수 없음 | migration `0019_opt_direct`(§9) |
| C6 | `_estimate_min`(최근 성공 PREDICT 중앙값 × 수) | 미리보기 예상 시간 | 비용 미리보기에 재사용(§8.3) |

## 2. 범위 / 비범위

| 범위 | 비범위(후속) |
|---|---|
| 평가 방식 `surrogate`(기존) · `direct`, 평가자 `predict` · `solver` | 대리모델+직접 혼합(예: 직접 평가 결과로 GP 재적합) |
| 알고리즘 6종(§4), 세대 단위 배치 평가, 예산·캐시·실패 처리·일시정지/재개·진행 표시 | CMA-ES·MOEA/D·NSGA-III·베이지안 국소(TuRBO), 4목적 이상 |
| 결과 = S17 계열 + 평가 run 링크, 해석 평가 확인 단계 | 최적화 간 캐시 공유(같은 최적화 안만) |
| MCP 공통 작업 계약 등록 **표시**(§8.5) | MCP 서버 구현(별 브랜치 mcp-ready.md, 의존 없음) |

## 3. 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| OD-1 | `settings.method` = `surrogate`(생략 시, 기존 동작 바이트 동일) · `direct`. `direct`는 매 후보를 **평가자로 직접 평가**하고 대리모델(GP·RBF)을 만들지 않는다. | 사용자 요청. 기존 행·요청 하위 호환 |
| OD-2 | 평가자 `predict`(기본: 형상 생성 → PhysicsAI 예측 → 응답) · `solver`(형상 생성 → Radioss 해석 → 응답, 고비용·선택). `solver`는 기존 ①-3·①-4·①-6 경로를 **그대로 재사용**하고 새 HPC 코드를 만들지 않는다. | 제출·회수·SCX 버전·SUBMISSION_UNKNOWN 규칙을 한 곳에 유지 |
| OD-3 | **세대(반복) = 배치 1개**. 반복 작업 `DIRECT_OPT`(새 job_type, SLOT, 짧음)가 ask → 배치 등록, 배치(또는 해석 체인) 종료 훅이 다음 작업을 넣어 tell. 슬롯은 반복 작업 동안만 잡는다. | C2 패턴. 세대 사이에 다른 사용자 작업이 끼어들 수 있다(공정성) |
| OD-4 | 알고리즘은 **ask/tell 순수 함수**(`stage5_optimize/direct/`)로 numpy·scipy만 쓴다. GA·NSGA-II는 C1 연산자를 import해 쓰고 `evo.py`·`evo_ops.py`·`evo_sort.py`·`algo.py`는 고치지 않는다. | 기존 ego·ga·nsga2 회귀 0(V-OD-12). 새 런타임 의존 0(ON-6과 같음) |
| OD-5 | 결정성: 세대 g의 난수 = `np.random.default_rng([seed, g, 0xD1])`(재개해도 같은 값). tell은 결과 도착 순서가 아니라 **eval_no 순**으로 받는다. NM·PS는 난수 없음, COBYLA는 scipy 결정적 + 재생(§4.6). | 일시정지·재개해도 중단 없는 실행과 같은 이력(V-OD-9) |
| OD-6 | 예산 `max_evals`는 **사용자 입력 필수**(기본값 없음, 422 `OPT_BUDGET_REQUIRED`), `max_hours`는 선택(설정 기본 predict 24 h · solver 72 h). 서버 상한 `max_evals_cap`(predict 2000 · solver 200). | 비용이 평가 수에 비례(예측 1건 수 분, 해석 1건 수 시간). 사용자 요청 "필수 또는 보수적 기본" |
| OD-7 | 캐시 키 = **반영값**(정수 반올림·tpl 서식·범주·N/A 마스크 뒤 `BatchRow.values`) + baseline id의 정규 JSON sha256. 캐시 적중은 예산에 세지 않는다. 범위 = 같은 최적화(재개 포함). | tpl 서식이 다른 x를 같은 형상으로 만든다. 중복 평가 낭비 방지 |
| OD-8 | 형상 생성·예측·해석·응답 추출 실패(설계 원인) = **실행 불가**(CV = `CV_FAIL` 1e6, 목적 +∞) 후 캐시. 인프라 원인(취소·워커 재시작·HPC 미도달·`SUBMISSION_UNKNOWN`·라이선스)은 실행 불가로 치지 않고 자동 재시도 `infra_retry`(1)회 → 그래도 실패면 **일시정지**(PAUSED, 사유). | 인프라 장애가 설계 공간을 오염시키지 않게 |
| OD-9 | 응답·기준은 ON-C4 그대로 사용자 결정(자동 지정 금지, 422 `OPT_CRITERIA_REQUIRED`). 하이퍼파라미터 기본값은 유지(§4.7). | 사용자 결정(2026-10-20) |
| OD-10 | `solver` 생성은 **확인 단계 필수**: 미리보기가 `confirm_token`(본문 정규화본 HMAC, 10분)을 주고, 생성은 그 토큰이 있어야 한다(없거나 불일치 409 `SOLVER_CONFIRM_REQUIRED`). | 고비용 작업 dry-run+확인(decisions 2026-10-20 MCP 백로그와 같은 모양) |

## 4. 알고리즘(`backend/physicsai_core/stage5_optimize/direct/`)

### 4.1 목록·지원 범위

| algorithm | 계열 | 목적 수 | 변수 | 제약 처리 | 세대 배치 크기 |
|---|---|---|---|---|---|
| `ga_direct` | 집단 | 1 | 연속·정수·범주 | 제약 지배(ON-5) | 자식 N(첫 세대 N) |
| `nsga2_direct` | 집단 | 2·3 | 연속·정수·범주 | 제약 지배 + 비지배 정렬 | 자식 N |
| `de_direct` | 집단 | 1 | 연속·정수·범주 | Deb 규칙(시도 vs 목표) | 시도 N |
| `nelder_mead` | 국소·무미분 | 1 | 연속만 | `dominance`(기본) · `penalty` | n+1 → 1~4(추측 배치) / 수축 n |
| `pattern_search` | 국소·무미분 | 1 | 연속만 | `dominance`(기본) · `penalty` | 2n(전체 폴) + 패턴 이동 1 |
| `cobyla` | 국소·무미분 | 1 | 연속만 | 제약 직접(선형 근사) | 1(순차) |

- 목적 수 불일치 = 422 `SURROGATE_OPT_INVALID` problems `ALGORITHM_MISMATCH`. 국소 알고리즘에 자유 정수·범주 변수(다중 baseline 위상 `baseline` 포함) = `VARIABLE_KIND_UNSUPPORTED`("정수·범주 변수는 GA·NSGA-II·DE만 지원합니다 — 고정하거나 알고리즘을 바꾸세요"). 범위 분할 다중 baseline(연속)은 전부 허용(NO_COVER = 생성 실패 → OD-8).
- 공간·정규화: 연속·정수 [0,1] 정규화, 범주 수준 인덱스(opt-native §6.2, `evo_space.Space` 재사용). 국소 알고리즘의 스텝·허용오차는 정규화 단위다. tpl 서식으로 양자화된 변수의 서식 간격이 Δ_min·tol_x보다 크면 미리보기 경고 `QUANTIZED_VARIABLE`.
- 목적·제약 값(공통 `direct/problem.py`): 목적은 부호 통일(max → −f). 제약 위반 CV = Σ_c viol_c / s_c(viol은 §22.4.3, range 포함). **s_c = max(|경계|, 1e-12)**(range는 max(|lo|,|hi|,hi−lo)); |경계| < 1e-12이면 첫 세대 평가값 표준편차(하한 1e-12)로 정해 체크포인트에 고정. 실행 가능 = CV ≤ 1e-9.

### 4.2 `ga_direct`·`nsga2_direct`

- opt-native §6.2~§6.4의 유전자·초기 집단(LHS + 범주 층화)·선택·교차·변이·중복 제거·생존(GA (μ+λ) 엘리트, NSGA-II 비지배 정렬 + crowding)을 그대로 쓴다. 차이는 다음뿐이다.
  - 평가 = 평가자(배치), 난수 = OD-5 세대별 rng.
  - 초기 집단 주입: 선택 `seed_runs`(같은 Study 재사용 배치·①DOE의 run 중 사용자가 고른 것, 값 있는 성공 run, ≤ ⌈0.25·N⌉)는 평가값을 그대로 쓰고 다시 평가하지 않는다.
  - 마지막 세대가 남은 예산보다 크면 자식 앞쪽(생성 순) 남은 수만 평가하고 생존은 그 자식으로 한다(결정적).
  - 정지: 예산(`BUDGET_EVALS`·`BUDGET_TIME`) · `generations` 도달(`MAX_GEN`) · 정체 `stall_generations`세대(GA 최선 상대 개선 < 1e-9, NSGA-II 평가 HV 상대 개선 < 1e-6, `STALL`).
- NSGA-II HV 틀: 첫 세대 실행 가능 점(없으면 전체)의 ideal·nadir로 정해 `surrogate_opts.hv_frame`에 고정, R = 1 + `mo_ref_offset`(S17 §22.5.1과 같은 형식).

### 4.3 `de_direct`

- DE/rand/1/bin: 목표 i마다 서로 다르고 i가 아닌 r1·r2·r3(rng), v = x_r1 + F·(x_r2 − x_r3)(정규화 공간), 이항 교차(CR, j_rand 1개 보장), 경계 밖은 **목표와 경계 사이 중점**으로 되돌림.
- 정수: 원 단위 반올림·자름(`round_x`). 범주: 수준 인덱스를 연속으로 다룬 뒤 반올림·[0, L−1] 자름.
- 선택: 시도 u_i가 목표 x_i를 제약 지배하거나 같으면 교체(Deb 규칙). 세대 = 시도 N개 배치.
- 정지: 예산 · `generations` · 정체(최선 상대 개선 < 1e-9가 `stall_generations`).

### 4.4 `nelder_mead`

- 초기 단체: 시작점 x0와 x0 + h·e_i(h = `initial_step`, 경계를 넘으면 −h) = n+1점 배치.
- 계수: Gao–Han 적응형(α=1, β=1+2/n, γ=0.75−1/(2n), δ=1−1/n). 순서 키 = `dominance`면 (CV>0, CV, f, 인덱스), `penalty`면 f̃ + ρ·CV(f̃ = f / max(|f(x0)|, 1e-12), x0 평가 뒤 고정).
- **추측 배치**(`speculative: true`, 기본): 한 반복에 반사·확장·바깥 수축·안쪽 수축 4점을 한 배치로 평가한 뒤 표준 NM 규칙으로 하나를 채택한다(대기 왕복 수를 최대 2 → 1로). false면 표준 순차(1점씩). 수축 실패 시 축소 n점 배치.
- 점은 [0,1]로 자른다(투영). 정지: 단체 지름(정규화 ∞-노름) < `tol_x` 그리고 꼭짓점 f 범위 < `tol_f`·max(1,|f_best|) → `CONVERGED`, 또는 예산.

### 4.5 `pattern_search`(압축 좌표 탐색 + Hooke–Jeeves 패턴 이동)

- 폴: 현재점 x_k에서 x_k ± Δ·e_i(경계 밖은 경계로 투영, 중복은 캐시) **2n점 전체 폴**을 한 배치로. `pattern_move: true`면 직전 성공 방향의 패턴점 x_k + (x_k − x_{k−1})을 같은 배치에 더한다.
- 비교: `dominance`(제약 지배, 동률 = 앞 인덱스) 또는 `penalty`. 개선 점 중 최선으로 이동(Δ 유지, `expand` > 1이면 Δ·expand, 상한 0.5). 개선 없으면 Δ ← Δ·`contract`.
- 정지: Δ < `delta_min` → `CONVERGED`, 또는 예산.

### 4.6 `cobyla`

- `scipy.optimize.minimize(method="COBYLA")`를 정규화 공간에서 쓴다(bounds [0,1], 제약 g_c(x) = −viol_c/s_c ≥ 0, 목적 f̃ = f/max(|f(x0)|,1e-12), `rhobeg`·`tol = rhoend`, `maxiter` = 남은 예산).
- **재생(replay) 방식**: scipy는 콜백형이라 세대 사이를 넘길 수 없다. 반복 작업마다 x0부터 다시 실행하고, 평가 요청이 캐시에 있으면 그 값을, 없으면 그 점을 내보내며 중단한다(배치 크기 1). COBYLA는 결정적이므로 같은 궤적이 재현된다. 재생 비용(수학 계산만)은 반복당 ms 단위다.
- 체크포인트에 scipy 버전을 기록한다. 재개 시 버전이 다르면 경고 `COBYLA_VERSION_CHANGED`와 함께 **현재 최선점을 새 x0로** 재시작한다(이전 평가는 캐시로 유지).
- 실패 평가: f̃ = (지금까지 최악 f̃) + 10, 모든 g_c = −1e3(위반)으로 돌려준다.
- 정지: scipy 종료(`CONVERGED`) 또는 예산. 순차라 평가당 대기 왕복 1회 — 미리보기에 "순차 평가(동시 1)" 표시.

### 4.7 기본 하이퍼파라미터(사용자 변경 가능, 설정 `surrogate_opt.direct` 한 곳)

| 알고리즘 | 키·기본값 | 허용 범위 |
|---|---|---|
| `ga_direct` | `pop_size` clamp(4·n_g, 12, 40) 짝수, `generations` null(= ⌊(max_evals − N)/N⌋), `crossover_prob` 0.9, `mutation_prob` null(1/n_g), `eta_c` 15, `eta_m` 20, `stall_generations` 10 | pop 4~200 짝수, gen 1~500 |
| `nsga2_direct` | `pop_size` clamp(⌈max(20, 6·n_g)/4⌉·4, 20, 60), 목적 3이면 max(식, 40), `generations` null(같은 식), `eta_c` 20, `eta_m` 20, 나머지 GA와 같음 | pop 8~200 4의 배수 |
| `de_direct` | `pop_size` clamp(5·n_g, 10, 40), `F` 0.5, `CR` 0.9, `generations` null, `stall_generations` 10 | pop 4~200, F 0~2, CR 0~1 |
| `nelder_mead` | `initial_step` 0.1, `speculative` true, `tol_x` 1e-3, `tol_f` 1e-6, `constraint_handling` dominance, `penalty_rho` 100 | step 1e-4~0.5 |
| `pattern_search` | `delta0` 0.25, `delta_min` 1e-3, `contract` 0.5, `expand` 1.0, `pattern_move` true, `constraint_handling` dominance, `penalty_rho` 100 | delta 1e-6~0.5, contract 0.1~0.9, expand 1~2 |
| `cobyla` | `rhobeg` 0.25, `rhoend` 1e-3 | rhoend < rhobeg ≤ 0.5 |
| 국소 공통 | `start` = `nominal`(세트 공칭값, 범위 밖이면 투영 + 경고) · `best_seed`(seed_runs 최선) · `{값}` | — |

- 모르는 키·범위 밖 = `ALGO_OPTIONS_INVALID`. 세대 크기 > `max_batch_size`(100) 또는 > `train_data.max_runs_per_submit`(solver) = `BATCH_TOO_LARGE`.
- 국소 알고리즘의 2n·n+1 배치가 남은 예산보다 크면 시작하지 않는다(422 `BUDGET_TOO_SMALL`, 최소 = n+1 또는 2n+1).

### 4.8 ask/tell 인터페이스(구현 규칙)

```python
class DirectAlgo(Protocol):          # direct/base.py
    def init(problem, space, options, seed) -> State          # JSON 직렬화 가능(np 배열은 list)
    def ask(state, gen) -> list[Proposal]                      # Proposal = {x(원 단위), role, tag}
    def tell(state, gen, results: list[EvalResult]) -> State   # results는 eval_no 순, 캐시 적중 포함
    def done(state) -> str | None                              # stop 코드 또는 None
```

- 상태는 JSON(`state.json`)과 숫자 배열 `.npz`(`allow_pickle=False`)로만 저장한다. pickle 금지.
- `bench.py`에 시험용 해석 함수(Rosenbrock·Rastrigin·ZDT1·G06·제약 이차식)와 동기 구동기 `run_sync(algo, f, budget)`를 둔다(시험·벤치마크 전용, API 프로세스 미import).

## 5. 평가자

### 5.1 `predict`(기본)

- 세대 g의 배치 = 최적화 소유 `PREDICT_BATCH`(source table, iter kind `GEN`). native 세트 = `batch_native.gen_one`(paicad, 다중 baseline 배정 준비본), altair = `run_chain` → 하위 PREDICT(edspy) → RESPONSE_EXTRACT(`response_tcl`·CURVE `perf_value`). opt-native §5 (b) `loop`의 검증 배치와 **같은 생성 함수**(`so_repo.create_opt_batch`, kind만 다름)를 쓴다.
- 동시 실행: 형상 생성 = min(요청 `multi_execution`(기본 `train_data.platform_parallel_default`), `train_data.max_multi_execution`). 예측 = 전역 SLOT FIFO(1개씩, 하위는 doe_no 순 연속 queue_seq — 기존 `enqueue_children`).
- 응답 원천 = `predict_batch_runs.responses`(기존 SO_COLLECT `collect_points` 재사용).
- 필요 features: `optimize_direct_predict` = `optimize_builtin` ∧ (세트 엔진에 맞는 `predict_parametric`|`predict_mesh_only`|`geometry_native`) ∧ (H3D 성능이 있으면 `predict_responses`). HyperStudy 키 비참조(V-ON-1 불변식 유지).

### 5.2 `solver`(고비용·선택)

- 세대 g = ①DOE 1개(`train_does`, generator = 세트 엔진에 맞는 `platform`|native, `sampling = {kind:"table", meta:{origin:"opt_direct", opt_id, gen}}`) → 종료 훅이 이어서 `TD_SOLVE`(그 DOE 생성 성공 run 전부, 요청 `settings.solver` = ①-4 요청과 같은 키 — PBS queue·walltime·ncpu 또는 SCX `version`·`np`, S20) → `TD_RESP_EXTRACT`(①-6) → 다음 `DIRECT_OPT`.
- 연결 훅: `job_end`에서 DOE `sampling.meta.origin == "opt_direct"`인 `TD_DOE_GEN`·`TD_SOLVE`·`TD_RESP_EXTRACT` 종료를 `direct_opts.on_train_job_end`로 넘긴다(그 밖 ① 작업 동작 불변). HPC 대기는 슬롯을 점유하지 않는다(기존).
- 응답 원천 = `train_runs` 응답 표(①-6). **CURVE 성능은 해석 결과에 없다**(C4) → 목적·제약·관찰에 CURVE 성능이 있으면 422 `PERF_UNAVAILABLE_FOR_SOLVER`.
- 실패 판정: 생성 실패·Radioss 오류 종료·결과 없음·응답 비어 있음 = 설계 실패(OD-8). `SUBMISSION_UNKNOWN`·HPC 미도달·제출 거부·취소 = 인프라.
- 해석 run은 ① DOE 목록에 배지 "⑥ 직접 최적화 SO-00n · 세대 g"로 보인다. ③ 데이터셋 기본 선택에서는 제외한다(사용자가 고르면 포함 — 미결 1).
- 필요 features: `optimize_direct_solver` = `optimize_builtin` ∧ `train_solve` ∧ (`train_doe_platform`|`geometry_native`) ∧ `train_resp`.

### 5.3 공통 평가 관리

- **예산**: `evals_used` = 실제 평가 수(실패 포함, 캐시 적중·seed_runs 제외). 세대를 등록하기 전에 남은 예산으로 배치를 자르거나(집단형) 시작하지 않는다(국소). 시간 = 생성 이후 경과(PAUSED 구간 제외)를 **반복 작업 시작 때** 판정한다(진행 중 배치는 끝까지 둔다).
- **캐시**(OD-7): `direct/evals.csv`가 원본(eval_no, gen, hash, 변수…, 응답…, F…, CV, status OK|FAILED, code, cache_of, extrapolated, run_link). 같은 해시가 앞 세대에 있으면 배치에 넣지 않고 그 결과를 쓴다. 같은 배치 안 중복은 첫 것만 평가한다.
- **실패 비율**: 한 세대 설계 실패 비율 > `max_fail_ratio`(0.5)이면 일시정지 `FAIL_RATIO`("세대 g의 실패가 많습니다 — 범위·형상 설정을 확인하세요").
- **외삽 표시**(predict만): 학습 데이터셋 입력까지 정규화 최소 거리 > `extrapolation_warn_dist`(0.2)이면 `extrapolated: true`. 결과의 최선·전선 점에 배지, 진행 화면에 개수.
- **진행 표시**: `progress_text` "세대 7/20 · 평가 128/400(캐시 12 · 실패 3) · 최선 0.4312" / 다목적 "… · 전선 9점 · HV 0.712". 세대마다 `surrogate_opt_iters`(kind GEN)에 `best_value`·`best_feasible`·`improvement_rel`·`hv`·`front_size` 기록(기존 열).
- **일시정지·재개**: `POST /surrogate-opts/{oid}/pause` → `direct.pause_requested = true`, 진행 중 배치가 끝나면 다음 작업 대신 PAUSED. `POST …/resume`은 PAUSED·FAILED(direct)에서 마지막 체크포인트로 잇는다(본문 선택 `budget` — 늘리기만 허용). 체크포인트 = 매 tell 뒤 `direct/state.json`(원자 쓰기, gen·알고리즘 상태·s_c·hv_frame·f 기준·scipy/numpy 버전·evals.csv sha256). 등록됐지만 끝나지 않은 배치는 멱등하게 그대로 기다린다(so_next의 `prev` 규칙과 같음). 취소(CANCELED)는 기존대로 재개 불가.

## 6. 응답·기준(OD-9)

- 본문의 `objectives`·`constraints`·`observe`·`weights`·`sense`·제약 경계는 S17 §22.4.1·ON-C4 규칙 그대로다. 빈 항목 = 422 `OPT_CRITERIA_REQUIRED`(+missing), 워커도 같은 검사(`criteria.settings_missing`). 화면은 값 제안·자동 채움 없이 직접 입력.
- `nsga2_direct`의 `weights`는 결과 추천점(§22.6)에만 쓴다(필수 — ON-C4).
- `best` = 평가된 설계 중 기존 규칙(만족 최선, 없으면 위반 최소). 모든 점이 평가자 값이므로 S17 P9 "검증된 해에서만"을 만족한다. 단 `predict` 값은 **예측값**이므로 결과 화면은 "예측 평가" / "해석 평가"로 구분 표시한다.

## 7. 결과 형식(S17 계열)

- 폴더 `O = <study>/05_opt/surrogate/SO-00n/`(기존 번호 공유): `opt.json`, `summary.json`, `convergence.csv`, `verified_runs.csv`(= 평가 성공 run), 그리고 `direct/{state.json, state.npz, evals.csv, algo_history.csv, front.csv(다목적 평가 전선), gen_NNN/{ask.csv, tell.csv}}`. 재실행 세대는 `gen_NNN/`을 `_backup` 후 다시.
- `algo_history.csv`: gen, evals_used, evals_cached, n_failed, n_feasible, best(단일) | front_size·hv(다목적), step(Δ·단체 지름·rho — 국소만).
- DB `surrogate_opt_iters`(kind GEN, iter_no = g): `candidates` = 그 세대 제안(values, role ∈ {`direct`, `nm_reflect`, `nm_expand`, `nm_contract_out`, `nm_contract_in`, `nm_shrink`, `ps_poll`, `ps_pattern`, `cobyla`}, eval_no, cache_hit, state OK|FAILED|CACHED), `fit = {algo:{name, options, evaluator, evals_used, evals_cached, stop|null}}`. 세대당 최대 `max_batch_size` 행.
- `surrogate_opts.best`·`stop_reason`(`BUDGET_EVALS`·`BUDGET_TIME`·`MAX_GEN`·`STALL`·`CONVERGED`·`NO_NEW_CANDIDATE`)·`hv_frame`·새 `direct` JSONB(§9).
- `GET /surrogate-opts/{oid}/runs.csv`에 열 `gen, eval_no, cache_hit, evaluator, run_link`(predict = `B-00n/run__N`, solver = `<DOE 표시>/run__N`) 추가. 상세 `iterations[]`에 `batch_id`|`doe_id` 링크.
- FINAL 캡처(D3-61): `predict`면 기존과 같이 최선·추천점 캡처, `solver`면 SKIPPED(사유 "해석 결과는 ①에서 확인"). 추가 검증 `POST …/verify`(§22.7 EXTRA)는 `predict` 직접 결과에도 쓴다.

## 8. API·UI·MCP

### 8.1 본문(미리보기·생성, `backend/openapi.json` 갱신, 새 라우트는 pause 1개)

```jsonc
{"method":"surrogate"|"direct",                       // 생략 = surrogate(기존)
 "evaluator":"predict"|"solver",                       // direct만, 생략 = predict
 "algorithm":"ga_direct"|"nsga2_direct"|"de_direct"|"nelder_mead"|"pattern_search"|"cobyla",
 "algo_options":{…},                                   // §4.7, null·생략 = 기본
 "budget":{"max_evals":400,"max_hours":null},          // direct 필수(max_evals)
 "start":"nominal"|"best_seed"|{"T1":2.0},             // 국소만
 "seed_runs":[{"batch_id":"…","run_key":"run__3"}],    // 선택
 "solver":{…①-4 요청 키…},                             // evaluator=solver 필수
 "confirm_token":"…",                                  // evaluator=solver 생성 필수
 "model_id":"…",                                       // predict 필수, solver면 무시(null 저장)
 …objectives·constraints·observe·weights·bounds·seed·multi_execution(기존)}
// direct에서 explore·iterations·candidates·tol_rel·surrogate·verification은 보내면 DIRECT_FIELD_INVALID
// 미리보기 응답 추가: method, evaluator, algorithm, algo_options(기본 채움), batch_plan{first, per_gen, n_gen_est, sequential:bool},
//   estimate{per_eval_min|null, per_gen_min|null, total_h|null, basis:"최근 PREDICT 8건 중앙값 3.2분" | "이력 없음"}, confirm_token(solver)
// 상세 추가: settings.{method,evaluator,budget,…}, direct{gen, evals_used, evals_cached, n_failed, pause_requested, paused_reason, elapsed_s},
//   status "PAUSED", progress_text(§5.3)
// /status.surrogate_opt 추가: methods, direct{algorithms_by_kind, algo_defaults, max_evals_cap{predict,solver}, default_max_hours, evaluators_enabled{predict,solver}}
```

- problems(422 `SURROGATE_OPT_INVALID`) 추가: `METHOD_INVALID`, `EVALUATOR_INVALID`, `EVALUATOR_UNAVAILABLE`(features), `ALGORITHM_INVALID`(방식별 목록 밖), `ALGORITHM_MISMATCH`, `VARIABLE_KIND_UNSUPPORTED`, `ALGO_OPTIONS_INVALID`, `OPT_BUDGET_REQUIRED`, `BUDGET_INVALID`(cap 초과·비양수), `BUDGET_TOO_SMALL`, `BATCH_TOO_LARGE`, `PERF_UNAVAILABLE_FOR_SOLVER`, `DIRECT_FIELD_INVALID`, `SOLVER_SETTINGS_INVALID`(①-4 검사 재사용). 409 `SOLVER_CONFIRM_REQUIRED`, `SURROGATE_OPT_NOT_PAUSABLE`, `SURROGATE_OPT_NOT_RESUMABLE`(기존 코드 확장).
- 권한: 기존과 같다(생성·재개 power, 일시정지·취소 power + 등록자 또는 관리자).

### 8.2 화면(⑥ 내장 설정 카드, 필수 UI만)

- **평가 방식** 라디오: `대리모델(기존)` · `직접 평가(예측)` · `직접 평가(해석)`. 비활성 평가자는 회색 + `missing` 사유.
- **알고리즘** 드롭다운이 방식에 따라 바뀐다: 대리모델 = EGO·GA·NSGA-II(opt-native §10), 직접 = GA·NSGA-II·DE·Nelder–Mead·패턴 탐색·COBYLA. 목적 수·변수 종류로 맞지 않으면 비활성 + 툴팁, 무효가 되면 첫 유효 항목으로 되돌리고 회색 한 줄.
- 직접 방식이면 반복·후보·탐색 입력을 숨기고 **예산** 칸(최대 평가 수 필수 — 빈 칸이면 시작 비활성, 최대 시간 선택)과 국소 알고리즘의 시작점 선택을 보인다. 고급 옵션은 `<details>`(§4.7).
- **예상 비용 미리보기** 한 줄: "평가 400건 · 세대 약 20 · 1건 약 3.2분(최근 예측 8건 중앙값) → 약 21시간" / 해석은 "세대 약 10 · 세대당 약 4시간(최근 해석 중앙값) → 약 40시간 · HPC 코어 시간 …". 이력 없으면 "추정 불가".
- **해석 직접 평가 확인 대화상자**(필수): 평가 수·세대 수·예상 시간·큐 또는 SCX 버전·np를 보여 주고 `확인하고 시작`을 눌러야 `confirm_token`과 함께 생성한다.
- **진행 화면**(결과 화면 상단): `progress_text`, 세대별 최선 추이(단일) 또는 HV 추이·평가 전선(다목적, S17 카드 재사용), 평가 run 목록 링크(배치·DOE), 버튼 `일시정지`·`이어서 실행`(PAUSED·FAILED), 외삽·실패 개수 배지.

### 8.3 비용 추정식

- predict: per_gen = ⌈n_gen_batch/M⌉·t_geom + n_gen_batch·t_pred(t_pred = `_estimate_min` 중앙값, t_geom = 최근 BP_GEN run 중앙값, 없으면 0으로 두고 basis에 표시). total = Σ 세대.
- solver: per_gen = t_doe + t_hpc(최근 같은 Study `TD_SOLVE` run 벽시계 중앙값) + t_resp. 세대 내 run은 동시 제출이므로 run 수에 비례하지 않는다고 본다(큐 혼잡은 추정 밖 — 문구로 명시).

### 8.4 job·step

- 새 job_type `DIRECT_OPT`(stage 5, SLOT, "직접 최적화 반복"): `OD_COLLECT`(INTERNAL 20: 앞 세대 결과 수집·실패 판정·캐시 반영) → `OD_STEP`(INTERNAL 60: tell → done 판정 → ask, 체크포인트) → `OD_NEXT`(INTERNAL 20: 배치 또는 DOE 등록, 또는 마무리·일시정지). BLAS 스레드 상한은 `surrogate_opt.blas_threads`.
- 종료 훅: `surrogate_opts.on_batch_done`에 kind `GEN` 분기 추가, `direct_opts.on_train_job_end`(§5.2) 신설. POST /jobs로는 만들 수 없다(최적화 API만).

### 8.5 MCP 공통 작업 계약

- `DIRECT_OPT`(직접 최적화 생성)를 JOB_KINDS **heavy** 등록 대상으로 표시한다: dry-run = 미리보기(§8.1, 예상 비용), 확인 = `confirm_token`(solver는 필수, predict도 MCP 경로에서는 heavy 규칙을 따름). 규칙 이름·모양은 별 브랜치 mcp-ready.md를 참고만 하고 이 계약의 구현은 그 코드에 의존하지 않는다(병합 시 그쪽 목록에 한 줄 추가).

## 9. DB·설정

- migration `0019_opt_direct`(Revises `0018_equiv_check`; 병합 순서에 따라 번호만 조정):
  - `surrogate_opt_iters.kind` CHECK에 `GEN` 추가, `batch_id` NULL 허용 + `doe_id`(FK `train_does`, NULL) 추가 + CHECK `(batch_id IS NOT NULL) <> (doe_id IS NOT NULL)`, `ix_surrogate_opt_iters_doe`.
  - `surrogate_opts.status` CHECK에 `PAUSED` 추가(활성 유일 인덱스에는 넣지 않음 — 재개 시 다른 활성 최적화가 있으면 409 `SURROGATE_OPT_ACTIVE`), `model_id` NULL 허용(API가 predict면 필수 검사), `direct` JSONB(NULL) 추가.
  - downgrade: GEN 행·PAUSED·`model_id` NULL 행이 있으면 거부(데이터 보호, 0017 규칙과 같음).
- 설정 `surrogate_opt.direct`(기본값은 `config/schema_stages.py` 한 곳, `validate_so.py`가 범위 검사, 예시 yaml 키마다 주석): `enabled: true, max_evals_cap_predict: 2000, max_evals_cap_solver: 200, default_max_hours_predict: 24, default_max_hours_solver: 72, max_batch_size: 100, max_fail_ratio: 0.5, infra_retry: 1, extrapolation_warn_dist: 0.2, confirm_ttl_s: 600` + §4.7 알고리즘 기본값. `deploy/setup_config.py` 변경 없음(배포 파일은 추가만 — ON-C3).

## 10. 시험·완료 기준

| ID | 기준 |
|---|---|
| V-OD-1 | 단위: ask/tell 상태 JSON 왕복 동일, 캐시 키(서식·정수 반올림·N/A 마스크 뒤 같은 값 → 같은 해시, baseline 다르면 다름), s_c 규칙(경계 0 → 첫 세대 표준편차 고정), 실패 평가 CV_FAIL·목적 +∞, DE 경계 중점 복귀·정수·범주 유효, NM 계수·추측 배치 채택 규칙 골든, PS 폴 2n+패턴점·투영 |
| V-OD-2 | 국소 벤치마크(`bench.run_sync`, 시험 전용 허용오차): **Rosenbrock** d=2, x0 = (−1.2, 1), 범위 [−2,2]² — `nelder_mead`(tol_x 1e-8, 예산 1000) ‖x−1‖∞ ≤ 1e-3, `pattern_search`(delta_min 1e-6, 예산 3000) ≤ 1e-2, `cobyla`(rhoend 1e-6, 예산 1000) ≤ 1e-3. d=5 `nelder_mead`(예산 5000) f ≤ 1e-2 |
| V-OD-3 | 집단 벤치마크(시드 1~5): **Rastrigin** d=2 `ga_direct`(N=40, 예산 4000) ‖x‖∞ ≤ 0.05(4/5), `de_direct`(N=20, 예산 4000) 같은 기준(4/5); d=5 `de_direct`(N=40, 예산 12000) f ≤ 2.0(3/5). **ZDT1** d=30 `nsga2_direct`(N=100, 예산 25100) HV(R=1.1) ≥ 0.97 × 0.87667(4/5, V-ON-5와 같은 수준), d=6(N=40, 예산 2000) HV 비 ≥ 0.90(4/5) |
| V-OD-4 | 제약: **G06** `ga_direct`(N=40, 예산 4000) 실행 가능 + f ≤ 0.95·f*(4/5, ON-C1과 같은 기준), `cobyla`(x0 = (14.5, 5), 예산 300) 실행 가능(CV ≤ 1e-6) + |f/f* − 1| ≤ 1e-3. 이차식 min (x−2)²+(y−1)² s.t. x+y ≤ 2: `nelder_mead`·`pattern_search`(dominance·penalty 각각) ‖x − (1.5, 0.5)‖∞ ≤ 1e-2 |
| V-OD-5 | 혼합 정수·범주(opt-native V-ON-6 함수) `ga_direct`·`de_direct` → n=3·k=B·\|x−0.37\| ≤ 1e-3(5/5). 국소 알고리즘 + 자유 정수 → 422 `VARIABLE_KIND_UNSUPPORTED` |
| V-OD-6 | 평가 관리(가짜 평가자): 캐시 적중이 예산에 안 셈·같은 배치 중복 1회 평가, `max_evals` 정확히 지킴(마지막 세대 잘림 결정적), 시간 예산 세대 경계 판정, 설계 실패 → 실행 불가 + 재제안 없음, 인프라 실패 → 재시도 1회 → PAUSED, 실패 비율 > 0.5 → PAUSED `FAIL_RATIO` |
| V-OD-7 | 결정성: 같은 입력·시드 → `evals.csv`·`algo_history.csv` 바이트 동일, 다른 시드 → 다름, 결과 도착 순서를 섞어도 동일 |
| V-OD-8 | API: problems 14종·409 3종, `OPT_CRITERIA_REQUIRED` 동일 적용, solver 토큰 없음·만료·본문 변경 → 409, method 생략 → 기존 경로, `/status.surrogate_opt.direct`, openapi·타입 재생성 |
| V-OD-9 | 일시정지·재개: 세대 3에서 pause → PAUSED, resume → 끝까지; 결과가 중단 없는 실행과 바이트 동일. 등록된 배치가 있는 채 워커 재시작 → 멱등 재개. 예산 늘려 재개. COBYLA scipy 버전 불일치 → 경고 + 최선점 재시작 |
| V-OD-10 | E2E predict(가짜 paicad·edspy, native 세트): `ga_direct` 단일(N=6, 예산 18)·`nsga2_direct` 2목적(N=8, 예산 24)·`nelder_mead`(예산 10)이 DONE, 세대마다 소유 배치 1개·iter GEN, runs.csv 링크, 진행 문구, 실행 argv에 hstbatch·hstpy 0건 |
| V-OD-11 | E2E solver(가짜 HPC — PBS·SCX 각 1, platform 생성): `pattern_search`(예산 9)가 TD_DOE_GEN → TD_SOLVE → TD_RESP_EXTRACT → DIRECT_OPT로 연결돼 DONE, DOE `origin` 배지·③ 기본 선택 제외, CURVE 성능 → 422, `SUBMISSION_UNKNOWN` → 인프라 처리, FINAL SKIPPED |
| V-OD-12 | 회귀 0: `evo.py`·`evo_ops.py`·`evo_sort.py`·`algo.py` git diff 없음(정적 시험), 기존 V3-S13-*·V3-S17-*·V-ON-* 무수정 통과, ego·ga·nsga2 후보 골든 바이트 동일 |
| V-OD-13 | 화면: 평가 방식 전환 시 알고리즘 목록·입력 숨김, 예산 빈 칸 시작 비활성, 비용 미리보기 문구, 해석 확인 대화상자 없이는 요청 안 나감, 진행 화면·일시정지/이어서 버튼, 목 라우트, 기존 화면 시험 무수정 |

- 벤치마크 기준값은 구현 때 측정한다. 미달이면 기준을 낮추지 않고 원인부터 확인한 뒤 변경 메모(OD-Cn)로 보고한다(ON-C1과 같은 규칙).
- 완료 = `scripts/test-all` 통과 + V-OD-1~13 + Verifier 판정 + 서버 확인 E-OD(쿠션 단일 `ga_direct` 예측 예산 40 → 진행·일시정지·재개 확인, 해석 `pattern_search` 예산 5는 사용자 판단으로 선택).

### 10.1 Verifier 체크(V-OD-* 판정 시 함께 확인)

1. 대리모델 코드(`gp.py`·`rbf.py`·`infill*`)를 direct 경로가 import하지 않는다.
2. 알고리즘·응답 기준에 자동 기본값이 없다(ON-C4) — 방향·임계값·가중치·예산 `max_evals`.
3. solver 생성 경로가 토큰 검사를 우회하지 않는다(API·서비스 단위 시험).
4. 상태 저장에 pickle이 없다(`allow_pickle=False`, json).
5. 외부 명령은 워커에서만, 새 HPC 코드 없이 ①-4 함수 재사용.
6. DB에는 수치·경로만(`candidates` ≤ `max_batch_size`, 곡선·파일 본문 없음).

## 11. 파일 소유·순서

| 에이전트 | 파일 |
|---|---|
| **Impl-Backend** | 새: `backend/physicsai_core/stage5_optimize/direct/{__init__, base, problem, cache, budget, state, ga, de, nelder_mead, pattern, cobyla, bench}.py`, `worker/physicsai_worker/steps/stage5_optimize/{direct.py, direct_eval.py}`, `backend/physicsai_core/db/repositories/direct_opts.py`, `migrations/versions/0019_opt_direct.py`, 시험 `backend/tests/test_od_*.py`·`worker/tests/test_od_*.py`. 수정: `job_types.py`, `features.py`(2키), `db/tables/surrogate_opt.py`, `db/__init__.py`(HEAD), `db/repositories/surrogate_opts.py`(GEN 분기), job_end 훅(train 분기), `config/{schema_stages.py, validate_so.py, platform.example.yaml}`(추가만), `physicsai_api/{services/surrogate_opts.py, services/surrogate_opt_problem.py, schemas/surrogate_opt.py, routers/surrogate_opts.py(pause), services/system.py}`, ① DOE 목록·③ 데이터셋 기본 선택 제외(origin), `backend/openapi.json` |
| **Impl-Frontend** | 수정: `stages/stage5/surrogate/{SurrogateSetup.tsx, soRules.ts, SurrogateResult.tsx, ResultCards.tsx, AlgoOptions.tsx}`, 새 `stages/stage5/surrogate/{EvalMethod.tsx, DirectBudget.tsx, DirectProgress.tsx, SolverConfirm.tsx}`, ① DOE 목록 배지, `api/{surrogateOpt.ts, generated/schema.d.ts}`, `mock/surrogateOpt.ts`, `__tests__/od*.test.tsx`, `frontend-dist/**` |
| **Plan** | 이 문서, `docs/manual/admin.md`(direct 설정 키·오류 코드) |

순서: **B1** `direct/` 알고리즘 + 벤치마크(V-OD-1~5·7, 순수, 병렬 가능) → **B2** migration·DIRECT_OPT·predict 평가자·예산·캐시·일시정지(V-OD-6·9·10) → **B3** solver 연결·토큰(V-OD-8·11) → **F1** 목 기반 화면(V-OD-13) → openapi 병합 후 재생성 → **E** V-OD-12 → Verifier → E-OD.

## 12. 리스크

- **R-1 평가 비용 폭증**: 집단형은 예측 수백 건(예: N=20 × 20세대 = 400건 × 3분 ≈ 20시간), 해석은 세대마다 HPC 시간이다. `max_evals` 필수·서버 cap·시간 상한·비용 미리보기·해석 확인 단계·캐시로 막는다. 예측 하위 작업이 전역 슬롯을 오래 점유하므로 세대 사이에 다른 작업이 끼어들게 둔다(OD-3).
- **R-2 예측 모델 외삽**: 직접 평가는 학습 범위 밖의 "좋아 보이는" 예측값으로 수렴할 수 있다. 외삽 배지(§5.3), 범위 기본 = 세트 범위, 결과 화면 "예측 평가" 표기, 최선점 `선택 해 예측 검증`/FEM 검증 안내로 완화한다. 학습 범위 강제 제약은 후속.
- **R-3 국소 알고리즘 한계**: NM·PS·COBYLA는 국소해·노이즈(메시 변화로 응답이 계단형)에 약하다. tpl 양자화 경고, 기본 dominance 처리, 결과에 시작점·정지 사유 표시. COBYLA는 순차라 왕복 지연이 크다(미리보기 "순차" 표시).
- **R-4 COBYLA 재생 의존**: scipy 내부 결정성에 기댄다. 버전 기록·불일치 시 재시작으로 대응(V-OD-9).
- **R-5 migration 번호 충돌**: 다른 브랜치가 0019를 먼저 쓰면 병합 때 번호만 바꾼다(Revises 사슬 확인).
- **R-6 벤치마크 불안정**: 기준은 측정 전 값이다(§10 규칙).

## 13. 미결(사용자 확인 대상)

1. `solver` 평가 run을 ③ 학습 데이터에 **기본 포함**할지. 기본안은 제외(선택 시 포함) — 최적점 주변에 몰린 자료가 학습 분포를 치우치게 할 수 있음.
2. 예산 상한 기본값 확정: cap predict 2000·solver 200, 시간 기본 predict 24 h·solver 72 h.
3. `predict` 직접 결과의 최선점을 끝날 때 **해석 1회 자동 확인**(FEM_VERIFY 연결)할지. 기본안은 수동(결과 화면 버튼).

## 변경 메모(OD-Cn)

(없음)
