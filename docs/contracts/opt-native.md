# 계약: ⑥ 최적화 HyperStudy 독립 · 유전 알고리즘(GA · NSGA-II) — opt-native

작성: Plan, 2026-10-20. 기준: 브랜치 `feat/r1-opt` 4c03804(= `claude/phase3` db5fb68 S19 계약까지 + native 형상 엔진, `MIGRATION_HEAD` = `0016_geometry_engine`).
우선순위: **이 문서 > [s17_multiobj.md](s17_multiobj.md)(phase3 §22) > [s12_s13.md](s12_s13.md)(§18) > [phase3.md](phase3.md)**. 형상 엔진 쪽은 [geometry-engine.md](geometry-engine.md)(§7.3.8 다중 baseline, §7.5 엔진 게이트)를 따른다. 1·2·3차 원칙(단일 슬롯 FIFO, 설정만, AI 루트만, `_backup`, 한국어, 필수 UI, DB에는 수치 요약만)은 그대로다.
ID 규칙: 결정 `ON-n`, 시험 `V-ON-n`, 변경 메모 `ON-Cn`.

## 0. 사용자 결정(2026-10-20)

1. **최적화를 HyperStudy에서 완전히 독립**시킨다. HyperStudy(hstbatch·hstpy)가 설치되지 않은 PC에서도 ①~⑥ 전 기능이 동작해야 한다. 기존 hstbatch·hstpy 경로는 **레거시 선택 기능**(설정했을 때만 켜짐)으로 남기고, 기본은 플랫폼 내장이다.
2. ⑥ 내장 최적화에 **유전 알고리즘**을 추가한다: GA(단일 목적)와 NSGA-II(다목적).

## 1. 현황(코드 확인, 4c03804)

### 1.1 HyperStudy 의존 지점

| # | 위치 | 내용 | 이 계약의 처리 |
|---|---|---|---|
| H1 | `features.py` `optimize` = `FeatureReq(("hst_optimization",), ("hstpy_path","simlab_path"), (include·extract TCL·batchrun·pyd), ("optimization",))` | ⑥ 원본 최적화(job `OPTIMIZE`, `steps/stage5_optimize/optimize.py`, `core/stage5_optimize/optimize.py` RUN_CONFIG `ALTAIR_HOME`) | 레거시(§4) |
| H2 | `features.py` `train_doe` = `hst_gen_radioss` + `hyperstudy_path` + launcher `gen_radioss` | ①-3 생성 방식 `hyperstudy`(S18 `generator: hyperstudy`) | 레거시(§4). 기본은 이미 `platform`(`train_data.doe_generator_default`) |
| H3 | `config/derived.py` `derived_hstpy_path`·`derived_altair_home` | hstpy·ALTAIR_HOME 파생(H1에서만 사용) | 변경 없음 |
| H4 | `env_check.ALTAIR_CHECK_KEYS`에 `hyperstudy_path`·`hstpy_path`, `ENV_PROBE_TOOLS`에 `hstbatch`·`hstpy` | 비어 있으면 워커 점검이 `WARN "미설정"` | 레거시 키는 `SKIP`(§4.3) |
| H5 | `deploy/setup_config.py` `ALTAIR_TOOL_KEYS`에 `hyperstudy_path` | 설치 시 자동 탐지 | 탐지는 유지, 못 찾아도 경고 없음 |
| H6 | 프런트 `Stage5.tsx`(내장 비활성이면 `original`로 떨어짐), `OptRunCard` `FeatureGate optimize`, `DoeGenCard` `FeatureGate train_doe` | 미설치 PC에서 비활성 탭·옵션이 보임 | 레거시 숨김(§4.4) |

### 1.2 이미 HyperStudy와 무관한 경로

- ⑥ 내장 최적화(S13 §18 + S17 §22): job `SURROGATE_OPT`(SO_COLLECT·SO_FIT·SO_PROPOSE·SO_NEXT), 대리모델 GP/RBF, 단일 목적 EI×PoF + kriging believer, 다목적 예측 전선(Chebyshev + DE) + HVI + ParEGO, HV 수렴. numpy·scipy만 쓴다. `features.optimize_builtin`은 HyperStudy 키를 보지 않는다.
- 후보 검증 = 최적화 소유 `PREDICT_BATCH`(source table). BP_GEN은 native 세트면 `batch_native.gen_one`(paicad), 그 밖은 S18 `run_chain.build_run_inputs`(SimLab·HM 명령)로 형상·메시를 만든다. 그 뒤 하위 PREDICT가 edspy 예측 → `response_tcl`·`performance.perf_value`로 응답을 뽑는다. hstpy를 거치지 않는다.
- ① DOE: S18 `platform` 생성 + native `doe_native`.

### 1.3 빈칸(이 계약이 채움)

1. 레거시 기능이 미설치 PC에서도 "미구성"·`WARN`·비활성 버튼으로 노출된다(H4·H6).
2. 알고리즘이 EGO 계열 하나뿐이다. S17 P7에는 "NSGA-II를 직접 구현하지 않는다"고 되어 있는데, 이 계약이 그 결정을 **대체**한다.
3. 검증 루프가 항상 켜져 있어 대리모델만으로 빠르게 탐색하는 방법이 없다.
4. 이산 변수는 정수(tpl `%Ni`)만 지원한다. 다중 baseline 세트는 409 `MULTI_BASELINE_UNSUPPORTED`로 막혀 있다(`surrogate_opt_problem._no_multi_baseline`).

## 2. 범위 / 비범위

| 범위 | 비범위(후속) |
|---|---|
| HyperStudy 미설치 시 레거시 2기능만 꺼지고 나머지 features 전부 활성, 상태·점검·화면 정리 | 레거시 경로(OPTIMIZE·hstbatch DOE)의 코드 삭제·동작 변경 |
| `algorithm` = `ego`(기존) · `ga` · `nsga2`, 고급 옵션 | 대리모델 없이 GA 집단을 예측 체인으로 직접 평가(세대 = 배치) — 미결 1 |
| 검증 방식 `loop`(기존) · `none`(대리모델만) | MOEA/D·NSGA-III·CMA-ES, 4목적 이상 |
| 제약 지배, 정수·범주 변수(다중 baseline 위상 `baseline`), 쉘 비드 개수 등 정수 파라미터 | 쉘 형상 파라미터 정의 자체(geometry-engine 단계 5 별도 계약) |
| 결과 형식 = S17 계열(예측 전선·HV·후보 role 확장), migration 없음 | 새 job_type·새 테이블 |

## 3. 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| ON-1 | `train_doe`(hstbatch)와 `optimize`(hstpy)는 **레거시 기능**이다. `/status.features[k].legacy = true`로 표시하고, 미설정이면 화면에서 숨기며 점검은 `SKIP`으로 둔다. 그 밖의 기능 판정은 HyperStudy 키를 참조하지 않는다(정적 시험). | 사용자 결정 1. 설정한 사이트(기존 사용자)의 동작은 그대로 둔다 |
| ON-2 | ⑥ 기본 = 플랫폼 내장(`SURROGATE_OPT`). 새 job_type·step 키·migration은 만들지 않는다. 알고리즘과 검증 방식은 `settings`의 키로 분기한다. | S17 P6과 같은 이유다(종료 훅·취소·이어서 실행·FINAL 재사용). `MIGRATION_HEAD` 0016을 유지해 병합 충돌을 피한다 |
| ON-3 | GA·NSGA-II는 **대리모델 위의 내부 탐색기**다. 기존 DE(`_de`)와 Chebyshev 격자 자리에 들어간다. 후보 k개는 그 결과에서 고르고, 실제 평가는 기존 검증 배치(`loop`)가 맡는다. | 예측 1건이 수 분이라 GA 집단(수천 평가)을 예측 체인으로 직접 돌릴 수 없다. 대리모델 평가는 벡터화로 ms 단위다 |
| ON-4 | 검증 방식 `none` = 탐색(또는 재사용) 자료로 1회 적합 → 알고리즘 → 미검증 후보·예측 전선만 내고 끝난다(`stop_reason` `SURROGATE_ONLY`). 고른 해는 기존 추가 검증(§22.7 EXTRA)으로 보낸다. | 사용자 요구 "(b) 후보 검증 루프는 선택". `best`는 검증된 설계에서만 고른다는 S17 P9 원칙을 유지한다 |
| ON-5 | 제약은 **제약 지배**(Deb 2000)로 처리하고, 위반량은 S17 벌점과 같은 정규화를 쓴다. | 벌점 계수 조정이 필요 없고, GA와 NSGA-II에 같은 규칙을 적용할 수 있다 |
| ON-6 | **numpy만으로 직접 구현**한다(`surrogate/evo.py`). pymoo·DEAP·Platypus는 쓰지 않는다(§6.8). | 새 런타임 의존이 0이다. 결정성·정수·범주 처리를 직접 통제할 수 있다 |
| ON-7 | 결정성: 알고리즘의 난수는 반복마다 `default_rng` 1개에서만 뽑는다(§6.2). 같은 자료·설정·시드면 같은 집단과 같은 후보가 나온다. | S17 §22.5.7과 같은 보장 수준이다 |
| ON-8 | 범주 변수 `baseline`(다중 baseline 위상 변형)을 지원한다. 그러려면 매칭표가 `confirmed`여야 한다. 대리모델 입력 인코딩은 학습 입력 규칙(§7.3.8: 원-핫 + `__na` 지시 열·0 대체)과 같아야 한다. | 사용자 요구(이산 변수). 409 `MULTI_BASELINE_UNSUPPORTED`는 조건부로 해제한다 |

## 4. HyperStudy 독립

### 4.1 기능 판정(`physicsai_core/features.py`)

- `LEGACY_FEATURES = frozenset({"train_doe", "optimize"})`를 추가한다. FeatureReq 내용은 바꾸지 않는다.
- 불변식(정적 시험 V-ON-1): `LEGACY_FEATURES` 밖의 `FEATURES`·`JOB_FEATURE`·`_SPECIAL_MISSING` 판정은 다음을 참조하지 않는다.
  - altair `hyperstudy_path`·`hstpy_path`·`altair_home`
  - 템플릿 `hst_gen_radioss`·`hst_optimization`
  - launcher `gen_radioss`·`optimization`
- `JOB_FEATURE["OPTIMIZE"]`는 그대로 둔다. 레거시 작업 생성 시 사전조건은 기존과 같다.

### 4.2 `/status`

- `FeatureState`에 `legacy: bool`(기본 false)을 추가한다. `LEGACY_FEATURES`이면 true이고, `enabled`·`missing`은 기존 규칙을 따른다.
- `/status.surrogate_opt`에 다음을 추가한다(§9).
  - `algorithms: ["ego","ga","nsga2"]`
  - `algo_defaults{ga:{…}, nsga2:{…}}`
  - `ga_max_evals`
  - `verifications: ["loop","none"]`

### 4.3 환경 점검·설정

- 워커 `_exec_item`: 키가 `hyperstudy_path`·`hstpy_path`이고 값이 비어 있으면 `SKIP "선택(레거시 HyperStudy) — 미설정"`이다. 나머지 키의 빈 값은 기존대로 `WARN`이다.
- 프로브 `hstbatch`·`hstpy`: argv가 설정됐어도 실행 파일 경로가 비어 있으면 `SKIP`(같은 문구)이다. 경로가 있는데 파일이 없으면 기존대로 `FAIL`이다.
- `config/platform.example.yaml`: `hyperstudy_path`의 예시 값을 `""`로 바꾸고 주석 "선택(레거시). 비우면 ①-3 HyperStudy 생성·⑥ 원본 최적화만 꺼짐"을 단다. `hst_*` 명령 템플릿은 유지한다(실행 파일이 없으면 기능이 꺼짐).
- `deploy/setup_config.py`: 자동 탐지는 유지한다. hstbatch를 못 찾으면 정보 줄 "HyperStudy 없음 — 레거시 기능만 꺼집니다"를 내고 경고·실패는 내지 않는다.
- `validate.py`는 변경하지 않는다(값이 있을 때만 검사).

### 4.4 화면

- ⑥ 모드 탭(`OptModeTabs`):
  - 탭 이름은 `플랫폼 내장`(기본) · `원본 최적화(HyperStudy·레거시)`이다.
  - `features.optimize.enabled = false`이면 원본 탭을 **숨긴다**.
  - 내장이 비활성이어도 `original`로 떨어지지 않고, 내장 탭에 `missing` 사유를 표시한다.
  - localStorage 값이 `original`인데 원본 탭이 숨겨졌으면 `builtin`으로 바꾼다.
- ①-3 `DoeGenCard`: `features.train_doe.enabled = false`이면 생성 방식 `HyperStudy`를 숨긴다(플랫폼만 남음). 켜져 있으면 라벨을 `HyperStudy(레거시)`로 바꾼다.
- 기존 OPTIMIZE 작업 결과·작업 목록 표시는 그대로 둔다(숨김은 생성 UI에만 적용).

## 5. ⑥ 내장 최적화 구조

```
탐색(새 DOE 배치 | 재사용) ─▶ [반복 r] SO_COLLECT ─▶ SO_FIT(GP/RBF) ─▶ SO_PROPOSE(algorithm) ─▶ SO_NEXT
                                    ▲                                                    │
                                    └──── verification=loop: 검증 PREDICT_BATCH(k개) ◀───┘
                                          verification=none: r=1에서 마무리(SURROGATE_ONLY)
```

- (a) **대리모델 기반**: 단일·다목적, 제약(≤·≥·range), 관찰은 S17과 같다. SO_PROPOSE만 `settings.algorithm`으로 분기한다.
  - `ego`: 기존 §18.5·§22.5 그대로(바이트 동일 회귀)
  - `ga`: §6.3
  - `nsga2`: §6.4
- (b) **후보 검증 루프(선택)**:
  - `loop`(기본): 기존과 같다. 검증 배치의 형상·메시는 다음 경로를 따른다.
    - native 세트: `batch_native.gen_one`(paicad run, 다중 baseline이면 배정 baseline 준비본)
    - altair 세트: S18 `run_chain`(SimLab `geom_update`·HM `mesh` 명령)
    - 그 뒤 하위 PREDICT(edspy) → RESPONSE_EXTRACT(`response_tcl`·CURVE 성능)
  - hstpy·hstbatch 명령은 어느 경로에서도 실행되지 않는다(V-ON-12).
  - `none`(ON-4)의 흐름:
    1. 반복 작업 r=1에서 SO_COLLECT → SO_FIT → SO_PROPOSE를 실행한다.
    2. SO_NEXT는 검증 배치를 만들지 않고 마무리한다.
       - opt `DONE`, `stop_reason "SURROGATE_ONLY"`(VARCHAR(32) 안, migration 없음)
       - `best` = 탐색·재사용 run 중 기존 규칙의 최선(검증됨)
       - 후보는 `candidates`에 `state:"UNVERIFIED"`로 남긴다.
       - 다목적이면 `predicted_front`를 기록한다. 단일 목적이면 `summary.json.surrogate_optimum`과 `fit.algo.surrogate_optimum`에 남긴다.
       - FINAL 캡처(D3-61)는 건너뛴다.
       - 알림 문구: "내장 최적화 SO-00n 완료(대리모델만) — 미검증 후보 k개, 결과 화면에서 예측 검증하세요".
  - "최종 후보만 1회 검증"은 `loop` + `iterations: 1`로 표현한다(별도 모드 없음).

## 6. 알고리즘

### 6.1 선택 규칙

| algorithm | 목적 수 | 내부 탐색 | 후보 선택 |
|---|---|---|---|
| `ego`(기본, 생략 시) | 1 | DE(EI×PoF, kriging believer) — §18.5 | 기존 |
| `ego` | 2·3 | Chebyshev 격자 + DE, HVI + ParEGO — §22.5 | 기존 |
| `ga` | 1만 | GA(§6.3)로 대리모델 평균 최소화 | §6.5 |
| `nsga2` | 2·3만 | NSGA-II(§6.4)로 대리모델 평균 다목적 | §6.5 |

목적 수와 맞지 않으면 422 `SURROGATE_OPT_INVALID` problems `ALGORITHM_MISMATCH`이다("GA는 단일 목적, NSGA-II는 다목적 전용입니다").

### 6.2 공통

- **유전자**: 자유 변수(고정 제외)를 순서대로 놓는다.
  - 연속·정수는 범위로 [0,1] 정규화한다(기존 `normalize`).
  - 범주는 수준 인덱스 {0..L−1}이다.
  - 정수는 변이 뒤 원 단위에서 반올림하고 [⌈lo⌉, ⌊hi⌋]로 자른다(기존 `round_x`).
  - n_g = 유전자 수.
- **평가**: 집단 전체를 한 번에 대리모델에 넣는다(벡터화). 값은 다음과 같다.
  - 목적: 단일은 표준화한 μ(부호 통일), 다목적은 작업 정규화 μ̃(§22.5.1)
  - 제약 위반 CV(x) = Σ_c viol_c(μ_c(x)) / s_c. s_c = 제약 자료 표준편차, 하한 1e-12·max(1, |경계|). viol은 §22.4.3과 같다(range 포함).
  - 실행 가능 = CV ≤ 1e-9
  - 다중 baseline 범위 분할 세트에서 `assign_baseline`이 None인 점은 CV += 1(덮지 못하는 구간 회피)이다.
- **제약 지배** a ≺ b: (CV_a = 0 ∧ CV_b > 0) ∨ (CV_a > 0 ∧ CV_b > 0 ∧ CV_a < CV_b) ∨ (둘 다 0 ∧ 목적 지배: 단일 f_a < f_b, 다목적 `pareto.dominates`).
- **초기 집단**(N개):
  - 연속·정수는 `gp.lhs_unit`(시드 rng)로 만든다.
  - 범주는 i mod L로 층화한 뒤 rng로 섞는다.
  - 검증된 설계 중 제약 지배 상위 ⌈0.1·N⌉개를 앞에 넣는다(시드 주입, 같은 설계는 1개).
- **변이 연산자**:
  - 선택: 이진 토너먼트(rng로 고른 두 개체 비교. 동률이면 GA는 앞 인덱스, NSGA-II는 crowding 큰 쪽 → 앞 인덱스)
  - 교차: 쌍마다 확률 p_c. 연속·정수 유전자는 유전자마다 0.5 확률로 **경계 SBX**(Deb–Agrawal, η_c)를 적용하고, 범주는 균등 교차(0.5 교환)한다.
  - 변이: 유전자마다 확률 p_m(기본 1/n_g). 연속·정수는 **경계 다항 변이**(η_m), 범주는 다른 수준 하나로 균등 교체한다.
- **중복 제거**: 생존 선택 전에 유효값(정수 반올림·범주·N/A 마스크 뒤 값)이 같은 개체는 앞 것만 남긴다.
- **난수**: 반복 r의 `rng = np.random.default_rng(seed·100000 + r·1000 + 900)` 하나에서 고정 순서로 뽑는다. 범주 수준별 DE(§7)는 `seed·100000 + r·1000 + 800 + level`이다. S17 표(500+j·700+j, j < 28)와 겹치지 않는다. 시드는 `opt.json`·`surrogate.json`에 기록한다.
- **취소**: 세대마다 `ctx.checkpoint()`. 진행 문구는 "후보 탐색(GA 세대 40/150)" 또는 "(NSGA-II 세대 80/200)"이다.
- **시간**: SO_FIT+SO_PROPOSE 합계에 기존 `fit_timeout_s`를 적용한다(초과 시 `SURROGATE_TIMEOUT`).

### 6.3 GA(단일 목적)

- 생존: (μ+λ) 엘리트. 부모 N + 자식 N을 합쳐 중복을 제거하고, (실행 가능 우선, CV 오름차순, f 오름차순, 인덱스)로 정렬해 앞 N개를 남긴다.
- 정지: `generations`에 도달하거나 정체로 멈춘다(`STALL`). 정체 = 최선 개체(제약 지배 기준)의 상대 개선 < 1e-9가 `ga_stall_generations`(30)세대 연속.
- 기록: 세대마다 `gen, evals, n_feasible, best_pred, mean_pred`.

### 6.4 NSGA-II(다목적, m = 2·3)

- 생존:
  1. 합친 2N에 대해 **제약 지배 기준 빠른 비지배 정렬**을 한다.
  2. 앞 front부터 채운다. 넘치는 front는 **crowding distance**(front 안 목적별 min–max 정규화, 경계 = ∞) 내림차순(동률은 인덱스)으로 자른다.
- 정지: `generations`에 도달하거나 정체(`STALL`). 정체 = rank-1 실행 가능 집합의 HV(작업 정규화 μ̃, R = 1 + `mo_ref_offset`, `pareto.hypervolume`)의 상대 개선 < 1e-6이 `ga_stall_generations`세대 연속.
- 기록: 세대마다 `gen, evals, n_feasible, front_size, hv_pred`.

### 6.5 후보 k개 선택(`ga`·`nsga2`)

이 절의 공통 규칙:
- 기존 설계(성공·실패)·이미 고른 후보와 같은 설계는 건너뛴다(기존 `is_dup`).
- 거리 규칙 = 정규화 거리(연속·정수 차 + 범주 불일치 1, √n_g로 나눔) ≥ 0.1이다. 못 채우면 반으로 줄여 0.0125까지(§18.5 RBF 규칙과 같음).
- 새 후보가 0개면 기존대로 `NO_NEW_CANDIDATE`이다.

- **GA**:
  - c₁(`role:"ga"`) = 최종 집단의 최선 개체(제약 지배 기준)
  - c₂…c_k:
    - GP면 `role:"ga_ei"`. 보관 집합 A(모든 세대 생존 개체의 합집합, 유효값 기준 중복 제거, 상한 `ga_archive_max` 5000 — 넘으면 늦은 세대 우선)를 EI×PoF(§18.5 `_ei`, fmin = 검증된 만족 설계 최선, 없으면 전체 최선)로 정렬해 거리 규칙대로 고른다.
    - RBF면 `role:"ga_div"`. 평균 오름차순 + 거리 규칙이다.
- **NSGA-II**:
  - 예측 전선 P = 최종 집단의 rank-1이면서 CV = 0인 점이다. 실행 가능한 점이 없으면 rank-1 중 CV 최소인 점들이다.
  - c₁ = §22.5.4-1 규칙(HV 틀 f̂ 기준 HVI 최대, 모두 ≤ 1e-12면 F까지 목적 공간 최소 거리 최대)이다.
  - c₂…c_k = **순차 HVI**: 고른 점의 μ̂를 F에 더한 뒤 남은 P에서 다시 HVI 최대를 고른다(같은 대체 규칙 + 거리 규칙).
  - 모든 후보의 role은 `"nsga2"`이다. P가 k보다 작으면 rank-2부터 crowding 순으로 채운다.
- 후보 기록 키는 S17과 같다: `values, predicted_objectives, predicted_std, acq`(HVI 또는 EI×PoF, 없으면 null), `weight: null`, `role`.

### 6.6 출력(모든 algorithm 공통 형식 — S17 계열)

- `iter_NN/algo_history.csv`: §6.3·§6.4의 세대 기록이다. `ego`는 쓰지 않는다.
- `iter_NN/final_population.csv`: 변수…, `mu_1..m, sd_1..m, cv, rank, crowding`이다(GA는 rank·crowding 빈칸).
- 다목적 `iter_NN/predicted_front.csv`·DB `surrogate_opt_iters.predicted_front`는 S17 형식 그대로다.
  - NSGA-II의 P가 28점을 넘으면 DB에는 28점만 둔다. 목적별 극점을 먼저 넣고, 나머지는 μ̃ 공간 탐욕 max-min 거리로 고른다(결정적).
  - CSV에는 P 전부를 둔다.
- `surrogate_opt_iters.fit`(JSONB)에 `algo` 키를 추가한다: `{name, pop_size, generations, generations_run, evals, stop:"MAX_GEN"|"STALL", seed, best_pred|null, hv_pred|null, surrogate_optimum|null}`. `ego`면 `{name:"ego"}`만 둔다. migration은 없다.
- **검증 수렴 지표는 알고리즘과 무관하게 같다**: 단일 = `best_value`·`improvement_rel`(§18.5), 다목적 = `hv`·`front_size`·`hv_history`(§22.5.6, 고정 `hv_frame`).
- `summary.json`·`opt.json`에 `algorithm`, `algo_options`(기본값을 채운 사용값), `verification`을 기록한다.

### 6.7 기본 하이퍼파라미터·계산량

| 키 | GA | NSGA-II | 허용 범위 |
|---|---|---|---|
| `pop_size` | clamp(10·n_g, 40, 200), 짝수 | clamp(⌈max(100, 10·n_g)/4⌉·4, 100, 400) | 8~1000, 짝수(NSGA-II는 4의 배수) |
| `generations` | 150 | 200 | 1~2000 |
| `crossover_prob` p_c | 0.9 | 0.9 | 0~1 |
| `mutation_prob` p_m | 1/n_g | 1/n_g | 0~1 또는 null(= 1/n_g) |
| `eta_c` | 15 | 20 | 1~100 |
| `eta_m` | 20 | 20 | 1~100 |

- `pop_size × generations ≤ ga_max_evals`(100 000)이고, 넘으면 `ALGO_OPTIONS_INVALID`이다.
- 기본 계산량(NSGA-II 100×200 = 2만 평가 × 목적·제약 GP ≤ 8개, n ≤ 60)의 목표는 반복당 SO_PROPOSE 30초 이내다(E-ON 서버 확인에서 측정).

### 6.8 구현 의존 결정(ON-6)

| 후보 | 라이선스 | 판단 |
|---|---|---|
| **직접 구현(numpy)** | — | **채택.** SBX·다항 변이·비지배 정렬·crowding을 합쳐 약 400줄이다. 새 wheel이 0개이고, 결정성(단일 rng)·정수·범주·제약 지배·S17 자료 모델을 직접 맞출 수 있다 |
| pymoo(0.6.x) | Apache-2.0(문제 없음) | 불채택. 전이 의존(matplotlib·autograd·cma·alive-progress·dill·Deprecated)과 컴파일 확장 때문에 오프라인 묶음·사내 보안 검사 대상이 늘고, numpy 2 고정과 맞춰야 한다. 범주 변수·결정성 동작을 감싸는 코드가 결국 필요하다 |
| DEAP | LGPL-3.0 | 불채택. 동봉 배포 시 고지·교체 가능성 의무가 붙고, 기능상 이점이 없다 |
| Platypus | GPL-3.0 | 불채택(라이선스) |

- 코드 위치: `physicsai_core/stage5_optimize/surrogate/evo.py`(순수 numpy, 대리모델을 모름 — 평가 함수 `f(X) -> (F, CV)`를 받는다). import는 S13 규칙대로 surrogate 패키지 안 지연 import이고, API 프로세스는 불러오지 않는다.
- `scipy`는 기존 GP·DE에만 쓴다. `evo.py`는 numpy만 쓴다.

## 7. 이산 변수

- **정수**: tpl `%Ni`(altair)·native 정수 파라미터(예: 쉘 비드 개수 — 단계 5 계약이 정수 파라미터로 정의하면 추가 작업 없이 적용). `ego`는 기존 `integrality`, GA·NSGA-II는 §6.2 반올림을 쓴다.
- **범주 `baseline`(다중 baseline 위상 변형, geometry-engine §7.3.8 (a))**:
  - 조건: 매칭표 `status: confirmed`(아니면 기존 409 `PARAM_MAP_UNCONFIRMED`). 조건을 만족하면 `MULTI_BASELINE_UNSUPPORTED`를 해제한다.
  - 수준 = 매칭표 baseline id 순서이다. 요청 `levels:{"baseline":[…]}`로 수준을 줄일 수 있고, 1개면 고정이다. 수준 수 > `max_levels`(8)이면 `TOO_MANY_LEVELS`이다.
  - N/A 변수: 그 수준에서 비활성인 공통 변수는 유효값에서 지운다. 대리모델 입력은 **학습 입력 규칙과 같은 인코딩**(공통 변수 + baseline 원-핫 + `<이름>__na` 지시 열, 값 0 대체)이다. 순수 함수 `surrogate/encoding.py` 하나를 SO_FIT·SO_PROPOSE·미리보기가 함께 쓴다.
  - `ego` + 범주: 수준마다 DE를 따로 돌려(같은 획득 함수) 합친다. 다목적 Chebyshev 격자도 수준별로 돌린 뒤 합쳐 비지배를 거른다.
- **범위 분할(§7.3.8 (b))**: 변수는 연속(전 baseline 범위 합집합)이다. 검증 run의 baseline 배정은 기존 `assign_baseline`이 한다. 덮지 못하는 점은 §6.2 CV 벌점으로 피하고, 그래도 생기면 run이 `BASELINE_NO_COVER`로 생성 실패 → "실패 설계"(다시 제안하지 않음)가 된다.
- 검증 배치: source table에 `baseline` 열(문자열 id, 위상 변형 세트에서만)과 N/A 빈칸을 허용한다. 배치 `source_meta.multi_baseline`은 ④ 다중 baseline 배치와 같은 형식이다(`batch_native` 경로를 재사용하고, table 파서만 확장).
- 탐색 새 DOE는 다중 baseline이면 §7.3.8 층화 LHS를 쓴다(④ 다중 baseline 배치 생성 경로와 같음).

## 8. API(`backend/openapi.json` 갱신, 새 라우트 없음)

```jsonc
// 미리보기·생성 본문(§22.4.1 확장) — 아래 키는 모두 선택
{"algorithm":"ego"|"ga"|"nsga2",                 // 생략 = "ego"
 "algo_options":{"pop_size":null,"generations":null,"crossover_prob":null,
                 "mutation_prob":null,"eta_c":null,"eta_m":null},   // null·생략 = §6.7 기본
 "verification":"loop"|"none",                   // 생략 = "loop"
 "levels":{"baseline":["bl_r4","bl_r6"]},        // 다중 baseline 위상 세트만
 …기존 키}
// 미리보기 응답 추가: "algorithm","algo_options"(기본 채운 값),"verification","variables_kind":{"RIB_N":"integer","baseline":"categorical"}
//   verification "none"이면 max_total_runs = 탐색 수(재사용 0), estimate_min은 탐색만
// 상세 추가: settings.{algorithm,algo_options,verification}, iterations[].fit.algo, candidates[].role ∈ 기존 ∪ {"ga","ga_ei","ga_div","nsga2"},
//   candidates[].state "UNVERIFIED"(none), stop_reason "SURROGATE_ONLY", progress_text "반복 2/3 · 후보 탐색(NSGA-II 세대 80/200)"
// /status.features[k].legacy, /status.surrogate_opt.{algorithms,algo_defaults,ga_max_evals,verifications,max_levels}
```

- 새 problems 코드(422 `SURROGATE_OPT_INVALID`):

| 코드 | 조건 |
|---|---|
| `ALGORITHM_INVALID` | algorithm이 목록 밖 |
| `ALGORITHM_MISMATCH` | §6.1 |
| `ALGO_OPTIONS_INVALID` | §6.7 범위, 모르는 키, `ga_max_evals` 초과, `ego`인데 algo_options가 비어 있지 않음 |
| `VERIFICATION_INVALID` | 목록 밖 |
| `LEVELS_INVALID` | baseline이 아닌 키, 매칭표에 없는 id, 빈 목록 |
| `TOO_MANY_LEVELS` | §7 |

- `verification: "none"`이면 `iterations`·`tol_rel`은 무시하고 저장 시 `iterations = 1`로 둔다. `candidates`는 미검증 후보 수로 쓴다.
- 하위 호환: 새 키가 없는 요청·기존 행의 settings는 `ego`·`loop`로 읽는다. 동작은 S17과 바이트 동일이다.
- 추가 검증 `POST /surrogate-opts/{oid}/verify`(§22.7)는 단일 목적·`none`에도 그대로 쓴다(opt DONE).

## 9. 설정(`surrogate_opt` 절, 기본값은 `config/schema_stages.py` `SurrogateOptCfg` 한 곳)

`default_algorithm: ego, ga_pop_size: null, ga_generations: 150, nsga2_pop_size: null, nsga2_generations: 200, ga_crossover_prob: 0.9, ga_eta_c: 15, nsga2_eta_c: 20, ga_eta_m: 20, ga_stall_generations: 30, ga_archive_max: 5000, ga_max_evals: 100000, max_levels: 8`(null = §6.7 식). `validate.py`는 §6.7 범위를 검사한다. 예시 yaml에는 키마다 주석 한 줄을 단다. `deploy/setup_config.py`는 변경하지 않는다.

## 10. 화면(⑥ 내장 — 새 최적화 카드 ⑥ 설정, 필수 UI만)

- **알고리즘** 드롭다운: `대리모델 EGO(기본)` · `유전 알고리즘 GA` · `NSGA-II`.
  - 목적 수에 맞지 않는 항목은 비활성 + 툴팁("GA는 단일 목적 전용" / "NSGA-II는 목적 2개 이상").
  - 목적 수가 바뀌어 선택이 무효가 되면 `ego`로 되돌리고 회색 한 줄로 알린다.
- **검증 방식** 라디오: `반복 검증(기본)` · `대리모델만(검증 없음)`. 후자를 고르면 반복·개선 기준 입력을 숨기고, 회색 한 줄 "예측 run 없이 대리모델로만 탐색합니다. 결과의 후보는 미검증이며 '선택 해 예측 검증'으로 확인하세요"를 표시한다.
- **고급 옵션**(`<details>` 기본 접힘, GA·NSGA-II일 때만): 집단 크기·세대 수·교차 확률·변이 확률(빈칸 = 1/n)·η_c·η_m, 자리표시자 = `/status` 기본값, `기본값으로` 버튼. 클라이언트 범위 검사는 §6.7과 같고, 서버 problems 문구를 그대로 표시한다.
- 다중 baseline 위상 세트: 변수 범위 표에 `baseline` 행(수준 체크박스)을 둔다. N/A 변수는 수준별 회색 "N/A" 표시다.
- 결과 화면:
  - 상태 칸에 `알고리즘: NSGA-II · 세대 200(정체 종료 142)`
  - 품질 표에 열 `탐색기`(algo.name·generations_run·stop)
  - 파일 위치에 `algo_history.csv`
  - `none`이면 파레토/최적 카드 제목에 "대리모델 예측(미검증)" 배지를 달고, 후보 표의 `선택 해 예측 검증`을 강조한다.
  - 새 그래프는 없다(예측 전선·HV는 S17 카드).
- 레거시 숨김은 §4.4.

## 11. DB·job·step

- migration 없음(`MIGRATION_HEAD` 0016 유지). 새 값은 JSONB 키(`settings`·`fit.algo`·`candidates[].role/state`)와 `stop_reason` 문자열 `SURROGATE_ONLY`뿐이다.
- job_type·step 키·무게는 변경하지 않는다. SO_PROPOSE 진행 문구만 §6.2를 따른다.

## 12. 시험·완료 기준

| ID | 기준 |
|---|---|
| V-ON-1 | 정적: `LEGACY_FEATURES` 밖 판정이 §4.1 키를 참조하지 않음(FeatureReq·special missing 함수 소스 검사). `/status.features[k].legacy`가 정확히 2개 |
| V-ON-2 | **HyperStudy 미설정 설정**(altair `hyperstudy_path`·`hstpy_path` = "", `hst_*` 명령 null, launcher `gen_radioss`·`optimization` 없음, fake hstbatch·hstpy 미배치) + 가짜 도구: `train_doe`·`optimize`만 false·legacy, 나머지 features 전부 true(가짜 도구로 구성 가능한 전부 — `train_extract`·`train_doe_platform`·`train_resp`·curation·dataset·evaluate·predict·predict_parametric·predict_mesh_only·predict_responses·contour_capture·optimize_builtin·geometry_native·fem_verify(HPC 가짜)) |
| V-ON-3 | 점검: 레거시 키 빈 값 → `SKIP` 문구, 다른 빈 키 → `WARN` 불변, 레거시 경로 있으나 파일 없음 → `FAIL` 불변, 프로브 SKIP. 화면: 원본 탭·HyperStudy 생성 옵션 숨김/표시·레거시 라벨, localStorage `original` → builtin 보정 |
| V-ON-4 | `evo.py` 연산자: 경계 SBX·다항 변이가 범위를 벗어나지 않음, 정수 유전자는 항상 정수, 범주 교차·변이 수준 유효, 제약 지배 비교 표 골든(6경우), 빠른 비지배 정렬 = O(n²) 직접 판정, crowding 골든(경계 ∞) |
| V-ON-5 | 다목적 벤치마크(대리모델 없이 해석 함수 직접 평가, NSGA-II 기본 연산자, 시드 1~5 중 4개 이상): **ZDT1**(d=30, N=100, G=250) HV(R=1.1) ≥ 0.97 × 0.87667, **ZDT2**(d=30) ≥ 0.95 × 0.54333, **DTLZ2**(m=3, d=12, N=100, G=250) ≥ 0.88 × 0.80740, **SRN**(제약 2개, N=100, G=200) 최종 rank-1 전부 실행 가능 + 해석 전선(x₁ = −2.5, x₂ ∈ [2.5, 14.79], 1001점) 대비 HV 비 ≥ 0.95 |
| V-ON-6 | 단일 목적 벤치마크(GA, 시드 1~5): **Rastrigin** d=2(N=50, G=200) ‖x‖∞ ≤ 0.05(4/5 이상), d=5(N=100, G=300) f ≤ 1.0(3/5 이상). **제약** G06(N=100, G=300) 실행 가능 + f ≤ 0.99·f*(f* = −6961.81388, 4/5 이상). **혼합 정수·범주** f = (x−0.37)² + (n−3)² + c[k](c = {A:0.5, B:0, C:0.2}) → n=3·k=B·\|x−0.37\| ≤ 1e-3(5/5) |
| V-ON-7 | 결정성: 같은 입력·시드 → 최종 집단·history·후보가 `array_equal`, 다른 시드 → 다름. 2회 실행 `algo_history.csv` 바이트 동일 |
| V-ON-8 | 대리모델 루프(시험 전용 `mo_infill.run_offline` 확장, V3-S17-7과 같은 예산): `nsga2`로 ZDT1·ZDT2·DTLZ2 검증 HV/참 HV ≥ 0.80·0.70·0.70(시드 1). `ga`로 Branin(정규화, 탐색 10 + 3×4) 검증 최선 ≤ 0.42(참 최소 0.397887), 같은 예산 LHS만보다 좋음(시드 1~5 중 4개 이상). 제약 문제에서 후보 PoF·CV 기록 |
| V-ON-9 | 후보 선택(§6.5): GA c₁ = 최종 최선, ga_ei·ga_div 거리 규칙·반감, NSGA-II 순차 HVI·대체 규칙·P < k 채우기, 중복·실패 설계 재제안 없음, 예측 전선 28점 축약 결정성 |
| V-ON-10 | API·흐름: problems 6종, 하위 호환(키 없음 → ego·loop, **기존 V3-S13-*·V3-S17-* 시험 무수정 통과**, ego 후보 골든 바이트 동일), `verification:"none"` → 배치 1개(탐색)·반복 작업 1개·DONE·`SURROGATE_ONLY`·best = 탐색 최선·후보 UNVERIFIED·FINAL 없음·알림 문구, 이어서 EXTRA verify 동작. openapi·타입 재생성 |
| V-ON-11 | 다중 baseline: 미확정 409 유지, 확정 위상 세트 → `baseline` 범주 변수·`levels`·N/A 마스크, 인코딩 = 학습 입력 인코딩(같은 함수 출력 비교), 검증 table `baseline` 열 → run `values.json`의 `baseline_id`, 범위 분할 세트의 NO_COVER 점 회피·생성 실패 시 실패 설계 처리, `ego` 수준별 DE |
| V-ON-12 | e2e(가짜 도구, V-ON-2 설정): ① 플랫폼 DOE(altair 가짜 SimLab)·native DOE(fake_paicad) → ③ 데이터셋·학습(가짜 edspy) → ④ 예측 → ⑤ 결과 표 → ⑥ `ga` 단일(mesh_only)·`nsga2` 2목적(native 세트)·`none` 1회가 DONE. 실행 argv 기록에 `hstbatch`·`hstpy`가 0건 |
| V-ON-13 | 화면: 알고리즘 드롭다운 비활성 규칙·자동 되돌림, 검증 방식 전환 시 입력 숨김, 고급 옵션 접힘·기본값·범위 문구, 요청 본문, 결과 상태 칸·품질 표 열·미검증 배지, 목 라우트, 단일·다목적 기존 화면 시험(V3-S13-9·V3-S17-12) 무수정 통과 |

- 벤치마크 기준값은 구현 때 측정한다. 미달이면 기준을 낮추지 않고 원인부터 확인한 뒤 Plan에 변경 메모(ON-Cn)로 보고한다(S17 V3-S17-7과 같은 규칙).
- 완료 = `scripts/test-all` 통과 + V-ON-1~13 + Verifier 판정 + 서버 확인 E-ON(아래).

### 12.1 서버 확인 E-ON(사용자)

1. HyperStudy 경로를 비운 설정으로 재기동 → `/status` 레거시 2개만 꺼짐, 환경 점검 SKIP 문구, ①·⑥에서 HyperStudy 항목이 숨겨지는지 확인한다.
2. 쿠션 2목적 `nsga2` 새 DOE 12 + 3×4 → 예측 전선·HV 그래프, 반복당 SO_PROPOSE 시간(목표 < 30 s)을 확인한다.
3. 단일 목적 `ga` + 정수 변수 1개, `none` 1회 → 미검증 후보 → 예측 검증 2점을 확인한다.
4. (다중 baseline 세트가 있으면) 위상 `baseline` 범주 포함 1회.

## 13. 파일 소유·순서(AGENTS.md 역할 표)

| 에이전트 | 파일 |
|---|---|
| **Impl-Backend** | 새: `backend/physicsai_core/stage5_optimize/surrogate/{evo.py, encoding.py}`, 시험 `backend/tests/test_on_*.py`·`worker/tests/test_on_*.py`. 수정: `features.py`, `config/{schema_stages.py, validate.py}`, `config/platform.example.yaml`, `stage5_optimize/surrogate/{dataset.py, infill.py, mo_infill.py}`, `physicsai_api/{services/surrogate_opt_problem.py, services/surrogate_opts.py, schemas/surrogate_opt.py, schemas/shell.py, services/system.py}`, `worker/physicsai_worker/{env_check.py, steps/stage5_optimize/surrogate.py, steps/stage5_optimize/surrogate_mo.py, steps/stage4_predict/batch_native.py}`(table `baseline` 열), `backend/physicsai_core/stage4_predict/batch_matrix.py`(table 파서 — `baseline` 열은 다중 baseline 세트 전용), `deploy/setup_config.py`(정보 줄), `backend/openapi.json` |
| **Impl-Frontend** | 수정: `frontend/src/stages/stage5/{Stage5.tsx, OptModeTabs.tsx}`, `stages/stage5/surrogate/{SurrogateSetup.tsx, soRules.ts, SurrogateResult.tsx, ResultCards.tsx}`, 새 `stages/stage5/surrogate/AlgoOptions.tsx`, `stages/stage1/DoeGenCard.tsx`, `api/{surrogateOpt.ts, generated/schema.d.ts}`, `mock/{surrogateOpt.ts, phase2.ts}`, `__tests__/on*.test.tsx`, `frontend-dist/**` |
| **Plan** | 이 문서, `docs/manual/admin.md`(레거시 설정·알고리즘 설정 키·오류 코드) |

순서:
1. **B0**: features legacy·점검·status(V-ON-1~3 백엔드 부분)
2. **B1**: `evo.py` + 벤치마크(V-ON-4~7, 순수, 병렬 가능)
3. **B2**: SO_PROPOSE 분기·후보 선택·`none`·API(V-ON-8~10)
4. **B3**: 범주 baseline(V-ON-11)
5. **F1**: 목 기반 화면(V-ON-3 화면·13) → openapi 병합 후 재생성
6. **E**: V-ON-12 → Verifier → E-ON

## 14. 리스크

- **R-1 대리모델 과신**: GA·NSGA-II는 μ만 최소화하므로 대리모델 오차가 큰 영역으로 몰릴 수 있다. GA는 c₂ 이후를 EI×PoF로, NSGA-II는 HVI로 뽑아 완화하고, `loop` 검증을 기본으로 둔다. `none` 결과는 늘 "미검증"으로 표시한다.
- **R-2 벤치마크 불안정**: DTLZ2·G06 기준은 구현 측정 전 값이다. 미달 시 변경 메모로 보고한다(기준을 임의로 낮추지 않음).
- **R-3 범주 + GP**: 원-핫 입력의 Matérn ARD는 수준 간 상관을 거칠게 모델링한다. 수준별 자료가 적으면 Q²가 낮다. 탐색 수 기본값 max(10, 4·d_free)에 수준 수 L을 곱한 값을 미리보기에서 권장한다.
- **R-4 레거시 숨김**: 기존에 HyperStudy를 쓰던 사이트에서 경로가 빠지면 탭이 사라져 혼란스러울 수 있다. 환경 점검 SKIP 문구와 관리자 매뉴얼로 안내한다.
- **R-5 계산 시간**: 3목적 + 제약 5 + N=400×G=250이면 반복당 GP 평가 8×10⁵점이다. `ga_max_evals`·`fit_timeout_s`로 막는다.
- **R-6 결정성 범위**: 같은 서버·같은 numpy 버전 기준이고, BLAS 부동소수 차이는 보장 밖이다(S17과 같음).

## 15. 미결(사용자 확인 대상)

1. GA **직접 평가 모드**(대리모델 없이 집단을 예측 체인으로 평가, 세대 = 검증 배치)를 후속으로 넣을지. 기본은 비범위다(집단 40 × 세대 20 = 예측 800건).
2. 레거시 기능이 미설정일 때 화면에서 **숨길지**(기본) **비활성으로 보일지**.
3. 다중 baseline **범위 분할** 세트도 이번에 포함할지. 기본은 포함(연속 + NO_COVER 회피)이고, 위상 변형만으로 줄이는 안도 있다.

## 변경 메모(ON-Cn)

- (없음)
