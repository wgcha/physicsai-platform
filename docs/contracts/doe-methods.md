# 계약: DOE 표본 방식 확장·지점 통일 (doe-methods, DM-C*)

작성: Plan, 2026-10-22. 요구(원문): "doe생성할때 왜 lhs만 되지???? 여러개 추가하자." 기준 커밋 def0517(migration HEAD `0021_uploads`).
선행 계약: [s15_sampling.md](s15_sampling.md)(phase3 §20, 표본 방식 알고리즘·문구 — 이 문서가 다시 쓰지 않음), phase3 §23(S18 ① 플랫폼 DOE), [geometry-engine.md](geometry-engine.md) §7.3.3·§7.3.8(native DOE·다중 baseline), [s12_s13.md](s12_s13.md) §18·[s17_multiobj.md](s17_multiobj.md)(⑥ 탐색), [native-vars.md](native-vars.md), [altair-vars.md](altair-vars.md), [mcp.md](mcp.md) §9.2·§15.
릴리스: v0.2.9(v0.2.8 배포 뒤, 같은 버전에 대기열 분리·조립 매칭과 함께). migration `0023_doe_methods` 1개(CHECK 확장만, down_revision `0022_job_queues`). 새 라우트·새 job_type·새 런타임 의존성 없음.

## 1. 조사 결과 — 왜 LHS만 되나

S15(D3-63)·S18(D3-66)로 표본 방식 8개(+표·재사용)는 이미 공용 코드(`physicsai_core/sampling/*`, `build_matrix`)에 있다. **Altair ①-3 플랫폼 생성과 ④ 단일 baseline 일괄 예측에는 노출**돼 있고, 아래 지점만 LHS로 막혀 있다.

| 지점 | 지금 지원 | LHS 고정 위치(원인) |
|---|---|---|
| ①-3 Altair · HyperStudy(레거시) | 정의 파일 4유형(`TYPE_LATINHYPERCUBE`·`TYPE_SOBOL`·`TYPE_FULLFACT`·`TYPE_FRACFACT`) | 해당 없음(S15 S1, 이 계약 비범위) |
| ①-3 Altair · 플랫폼 생성 | `lhs_opt`(기본)·`sobol`·`lhs`·`fullfact`·`fracfact`·`pb`·`bbd`·`ccd`·`train_doe` | 없음(`doe_platform.KINDS`) |
| **①-3 Native**(①-1 Native 추출·세트 기준 단일 baseline) | `lhs`·`train_doe`만 | 화면 `DoeGenCard.NativeFields`: 드롭다운 값 `lhs` 고정·나머지 `disabled`("Native 형상 엔진 DOE는 플랫폼 생성 LHS만 됩니다"), `doeGenParams.buildNativeParams`가 `sampling:{kind:"lhs"}` 고정 / API `job_params/stage1_native._native_doe_common`이 lhs 밖 422 `DESIGN_UNSUPPORTED` / 워커 `doe_native.py`·`doe_native_set.py`가 `lhs_values` 직접 호출(`build_matrix` 미사용) — geometry-engine §7.3.3이 "플랫폼 LHS"로 정의한 뒤 S18 통합 때 열지 않음 |
| **①-3 Native 다중 baseline** | `lhs`(층화)만 | `baselines_table.stratified_lhs`에 `lhs_values`를 넘김(§7.3.8) |
| ④ 일괄 예측 단일 baseline(Altair·Native) | 위 8개 + `table` + `train_doe` | 없음 |
| **④ 다중 baseline 세트** | `lhs`(층화)만 | `stage4_predict/batch_multi.build_multi_matrix`가 lhs 밖 `MULTI_BASELINE_SOURCE` |
| **⑥ 내장 최적화 탐색(새 DOE)** | `lhs`만 | 스키마 `SoExploreNew{kind:"new", count, seed}`에 방식 필드 없음, `services/surrogate_opts._explore_batch`가 `lhs_values` 직접 호출 — S15 §20.1 비범위("⑥ 탐색 배치는 현재 LHS 유지") |
| MCP 도구 | 백엔드 스키마 그대로(①·④는 이미 다종, Native·⑥은 위 제약 그대로) | `mcp/job_kinds.py` 설명 "seed: native LHS 난수 시드" |

부수 발견: ① 영향도 등급 `registry.doe_influence`가 `NATIVE_LHS`를 몰라 "표본 방식을 알 수 없어 참고용"으로 낸다(DM-C9에서 바로잡음).

구현·의존성: 무작위 LHS·최적화 LHS = Python 표준 `random`(버전 간 재현), Sobol = `scipy.stats.qmc.Sobol`(지연 import 1곳 `sampling/qmc.py`), 요인·PB·BBD·CCD = 순수 Python. scipy(`>=1.13,<2`)·numpy는 이미 `pyproject.toml`·`deploy/requirements.lock`·오프라인 묶음에 있다. **새 방식도 이 범위 안에서만 만든다**(DM-C3).

## 2. 결정(DM-C*)

| # | 결정 | 근거 |
|---|---|---|
| DM-C1 | **공용 정의 1곳**: `physicsai_core/sampling/registry.py`에 `METHODS`(기존) + 지점별 허용 목록 `SITE_KINDS`(§3)를 둔다. 요청 스키마의 kind 유니언·검증·화면 목록·MCP 설명이 모두 이것을 따른다. 방식별 입력 키 이름(`count`·`seed`·`criterion`·`levels`·`resolution`·`alpha`·`text`·`doe_id`)은 모든 지점에서 같다 | 사용자 요구 "여러 개 추가" + 지점마다 따로 막힌 원인 제거 |
| DM-C2 | **Native ①-3을 Altair 플랫폼 생성과 같은 목록으로 연다**(단일 baseline). 표본 행은 `doe_platform.build`(= `build_matrix`)로 만든다. 단 `lhs`(요청 생략·`{num_runs, seed}`·`sampling:{kind:"lhs"}`)는 **지금 경로(`lhs_values` 직접) 그대로** | 원인 1순위. lhs 골든 불변(DM-C8) |
| DM-C3 | **새 방식 3개**: `halton`(스크램블 Halton QMC), `random`(균일 랜덤), ①의 `table`(사용자 표 CSV). 후보 중 D-최적·다구치·Hammersley·MELS·정규분포 몬테카를로는 넣지 않는다(§4.2) | 변수 수십 개에서 실용적이고 run 수가 자유로운 공간 채움 방식 보강 + 외부에서 만든 설계 가져오기. 새 의존성 없음 |
| DM-C4 | **다중 baseline(①·④·⑥)은 층화 구조를 유지하고 층 안 생성기만 바꾼다**: `lhs`·`lhs_opt`·`halton`·`random` 허용. `sobol`(층별 run 수가 2의 거듭제곱이 아님)·요인·응답면·`table`·`train_doe`는 422/problem `DESIGN_UNSUPPORTED` "다중 baseline 세트는 baseline별 층화라 LHS·최적화 LHS·Halton·균일 랜덤만 됩니다" | `stratified_lhs`가 이미 생성기 함수를 인자로 받음(층 seed = `seed`+층 번호 규칙 그대로) |
| DM-C5 | **⑥ 탐색 새 DOE에 방식 선택 추가**: `explore:{kind:"new", count?, seed, method?, criterion?}`. `method` ∈ `lhs`(기본·생략)·`lhs_opt`·`sobol`·`halton`·`random`. 요인·응답면·표는 ⑥ 탐색에 넣지 않는다(재사용 배치로 대신: ④에서 만들고 `explore.kind:"reuse"`) | `kind`는 이미 new/reuse 구분에 쓰여 이름을 바꿀 수 없음. ⑥ 탐색은 대리모델 초기 표본이라 공간 채움만 필요 |
| DM-C6 | **상한은 기존 설정 그대로**(새 설정 키 없음): ① Altair 플랫폼 `train_data.platform_max_runs`(500), ① Native `lhs` = `train_data.max_runs`(기존 2~2000 유지), ① Native 그 밖 방식 = `train_data.platform_max_runs`, ④·⑥ = `predict_batch.max_runs`(200). 실행 전 "실제 run N개"를 항상 보이고 상한 초과는 막는다(`TOO_MANY_ROWS`, 상한값이 문구에 나옴). 별도 소프트 경고 문턱은 두지 않는다 | Native lhs 수용 범위 회귀 방지. 해석 run 비용은 실제 run 수 표시 + MCP plan→confirm로 충분 |
| DM-C7 | **SimLab·HyperStudy 실행 로직은 바꾸지 않는다**. 표본 생성(행 계산)만 플랫폼 공통 부분으로 바꾼다. 형상 생성(paicad)·조립·solve·rad 생성은 `doe_matrix.csv` 행을 그대로 받는다 | 사용자 지시(SimLab 경로 불변) |
| DM-C8 | **결과 불변**: ① Altair 플랫폼 8종·④ 기존 10종·HyperStudy 4유형의 행·meta·doe_type, ① Native `lhs`의 행(`lhs_values` 소비 순서)·`doe_type='NATIVE_LHS'`·`doe_label='LHS(Native)'`·`options={seed(,param_set_id)}`·`sampling=null`·응답 `sampling=null`, 다중 baseline `lhs` 층화 행, ⑥ `method` 생략 시 탐색 배치(`source_kind='LHS'`, meta `{count, seed, ranges}`, 같은 값)가 def0517과 같다. 화면 기본값도 그대로: ①-3 Altair 플랫폼·④ = `lhs_opt`, ①-3 Native·⑥ = `lhs` | 사용자 요구(기본값·seed 결과 불변) |
| DM-C9 | ⑤ 영향도 등급: `HALTON`·`RANDOM` = formal, ① `TABLE` = reference(기존 ④ TABLE 문구), `NATIVE_LHS` = formal(부수 발견 수정 — 표본 값은 그대로, ⑤ 표시만 바뀜) | 둘 다 균일 분포 공간 채움(SRC·PRCC 전제 충족). NATIVE_LHS는 LHS |
| DM-C10 | **UI 원칙**: 지점마다 방식 드롭다운 1개 + 그 방식에 필요한 칸만. 지금 변수 수에서 만들 수 없는 방식은 목록에 회색 "— 변수 k개에서 불가"(선택 불가)로 둔다. 설명 상자는 S15 §20.4 규칙(4줄) 그대로 | 사용자 원칙(필수 UI만) |

## 3. 지점별 허용 목록 `SITE_KINDS`(DM-C1)

| site id | 지점 | 허용 kind(드롭다운 순서) | 화면 기본 |
|---|---|---|---|
| `train_platform` | ①-3 Altair 플랫폼 생성 | `lhs_opt` `sobol` `halton` `lhs` `random` · `fullfact` `fracfact` `pb` · `bbd` `ccd` · `table` `train_doe` | `lhs_opt` |
| `train_native` | ①-3 Native 단일 baseline | `train_platform`과 같음 | `lhs`(사용자 확정 2026-10-22) |
| `train_native_multi` | ①-3 Native 다중 baseline | `lhs_opt` `halton` `lhs` `random` | `lhs` |
| `batch` | ④ 단일 baseline(Altair·Native, 조립·쿠션) | `lhs_opt` `sobol` `halton` `lhs` `random` · `fullfact` `fracfact` `pb` · `bbd` `ccd` · `table` `train_doe` | `lhs_opt` |
| `batch_multi` | ④ 다중 baseline | `train_native_multi`와 같음 | `lhs` |
| `opt_explore` | ⑥ 탐색 새 DOE(단일·다중 baseline 공통; 다중이면 `sobol` 제외) | `lhs` `lhs_opt` `sobol` `halton` `random` | `lhs` |

- 묶음 머리(S15 §20.4): 공간 채움 / 요인 설계 / 2차 응답면 / 직접 지정. `halton`은 `sobol` 뒤, `random`은 `lhs` 뒤.
- 백엔드 정적 시험: `openapi.json`의 지점별 kind enum(①·④ 요청 스키마, ⑥ `method`) = `SITE_KINDS`. 프런트 `lib/samplingKinds.ts`에 같은 표(`SITE_KINDS`)를 두고 `schema.d.ts` 유니언과 타입 시험으로 맞춘다.

## 4. 방식 정의

### 4.1 새 방식(S15 §20.5.1 공통 규칙 적용: 활성 변수·`FIXED_EXCLUDED`·코드값→값·정수 `applied_values`·`DUPLICATE_ROWS`·`INFLUENCE_TOO_FEW`·quality)

| kind | DB `source_kind`/`doe_type` | 표시 이름 | 입력·검증 | 생성(결정적) | meta |
|---|---|---|---|---|---|
| `halton` | `HALTON` | Halton(스크램블 QMC) | `count` 2~상한(정수), `seed` 0~4294967295(기본 1). k = 0이면 `DESIGN_UNSUPPORTED` | `sampling/qmc.py`에 `halton_unit(k, count, seed)` 추가: `Halton(d=k, scramble=True, <kw>=numpy.random.default_rng(seed)).random(count)`, `<kw>` 판정·경고 억제·import 실패(`GENERATOR_UNAVAILABLE`)는 Sobol과 같은 함수 공유. 이어서 추가 없음 | `{count, seed, ranges, scramble: true, generator: "scipy <버전>", active, fixed, quality}` |
| `random` | `RANDOM` | 균일 랜덤 | `count` 2~상한, `seed` 0 이상(기본 1) | `rng = random.Random(seed)`; i = 0..n−1마다 활성 변수 순서로 `u = rng.random()`(행 우선) | `{count, seed, ranges, active, fixed, quality}` |
| `table`(① 신규 지점) | `TABLE` | 표 붙여넣기 / CSV | `text` ≤ `predict_batch.table_max_bytes`, 머리줄 = ①-2 사용 파라미터(Native는 세트 변수) 이름 전부(순서 무관), 행 2~상한, 값 유한. **①은 값이 ①-2(세트) min~max 밖이면 problem `TABLE_OUT_OF_RANGE`**(사용자 확정 2026-10-22) "'{name}' 값 {v}가 학습 범위 {lo}~{hi} 밖입니다"(④는 기존대로 `out_of_range` 표시·허용) | 기존 `_table` 파서 그대로(브라우저가 파일을 읽어 `text`로 보냄 — 업로드 라우트 아님, 기존 ④와 같음) | 기존 ④ table meta |

- 설명문(S15 §20.4 형식, 문구 확정):
  - `halton` 1. 저불일치 수열로 공간을 고르게 채웁니다. Sobol과 달리 run 수가 자유롭습니다. 2. 변수가 아주 많으면(수십 개) 뒤쪽 변수끼리 상관이 생길 수 있어 스크램블을 씁니다. 나중에 점을 이어 붙일 수는 없습니다. 3. 영향도: 정식. AI 학습·대리모델에 쓸 수 있습니다. 4. run 수: 자유. 권장 10 × 변수 수.
  - `random` 1. 범위 안에서 균일하게 무작위로 뽑습니다. 2. 가장 단순하지만 점이 몰리거나 빈 곳이 생길 수 있습니다(LHS 계열이 보완). 비교·검증용으로 씁니다. 3. 영향도: 정식. 4. run 수: 자유. 권장 10 × 변수 수.
  - ① `table` 1. 직접 만든 설계표(CSV)를 그대로 run으로 씁니다. 2. 첫 줄은 사용 파라미터 이름 전부, 값은 학습 범위 안이어야 합니다. 3. 영향도: 참고용(표본 분포를 알 수 없음). 4. run 수: 표의 행 수.
- 권장 run(`registry.recommended_count`): `halton`·`random` = `lhs`와 같은 식.

### 4.2 넣지 않는 후보(근거)

| 후보 | 근거 |
|---|---|
| D-최적 | 모형식·후보점 집합이 필요하고 AI 학습 표본과 목적이 다름. 계산 무거움 |
| 다구치 직교배열 | 2수준은 `fracfact`·`pb`로, 혼합 수준은 `fullfact`로 대신 |
| Hammersley | run 수를 먼저 정해야 하고 Halton과 성질이 겹침 |
| MELS·scipy LHS 최적화(`random-cd`) | `lhs_opt`(maximin·corr)가 같은 목적. 결과 재현성 기준이 다른 구현을 둘 둘 이유 없음 |
| 정규분포 등 몬테카를로 | 변수별 분포 입력 UI가 추가로 필요 — DOE(학습 범위 채움) 목적 밖 |

### 4.3 방식별 파라미터·run 수·변수 수(k) 실용 범위

| kind | 화면 칸 | run 수 | k 제약 / 많은 변수(k ≥ 12) |
|---|---|---|---|
| `lhs`·`random`·`halton` | run 수, 시드 | 입력값(2~상한) | 제한 없음 — 많은 변수에 권장 |
| `lhs_opt` | run 수, 시드, 기준(최소 거리·상관 최소) | 입력값 | 제한 없음. n·k가 크면 생성 시간 증가(리스크 R2) |
| `sobol` | run 수(2^m 목록), 시드(④만 이어서 추가) | 2^m(4~상한) | 제한 없음 |
| `fullfact` | 변수별 수준(2~10) | ΠL(실시간 표시, 상한 초과 막음) | k가 크면 2^k로도 폭증 — 회색 처리 기준 = 모든 수준 2일 때도 2^k > 상한 |
| `fracfact` | 해상도 V·IV | 표(S15 §20.5.9) | k 2~11 |
| `pb` | 없음 | N ≥ k+1 | k ≥ 2, N ≤ 상한 |
| `bbd` | 없음 | 2k(k−1)+1 | k ≥ 3, run ≤ 상한(R=200 → k ≤ 10, R=500 → k ≤ 16) |
| `ccd` | α 면중심·내접 | S15 §20.5.9 | k 2~11 |
| `table` | 표 붙여넣기 / CSV 파일 선택 | 행 수 | — |
| `train_doe` | 재사용 DOE 선택 | 원본 행 수 | 이름 집합 같음(기존) |

정수·이산 파라미터: S15 §20.5.1 그대로(설계 값 → `predict.integer_rounding` 반영값, `fullfact`는 정수 수준). Native 세트 변수에 정수 형식이 없으면 반영값 = 설계 값. 범주형(다중 baseline `baseline`)은 층화(DM-C4)로만 다룬다.

## 5. 지점별 변경(API·워커·화면)

### 5.1 ①-3 Native(`TD_DOE_GEN`, engine native)
- **API** `job_params/stage1_native._native_doe_common`: `sampling.kind ∈ SITE_KINDS[train_native]`(다중 baseline 세트면 `train_native_multi`). `lhs`·생략은 기존 분기 그대로(DM-C8). 그 밖은 `doe_platform.check(sampling, setup, cfg)`로 검증 — 입력 표는 ①-1 Native 추출이면 ①-2 사용 행(`design_inputs`), 세트 기준이면 `design_inputs_from_params(ps.parameters)`. 상한은 DM-C6. 문제는 기존과 같이 422 `DOE_SAMPLING_INVALID`(problems).
- **작업 params·DB**(`after_insert`): lhs 밖 kind는 `doe_type = METHODS[kind][0]`(예 `HALTON`), `doe_label = "<표시 이름>(Native)"`, `options = 정규화 입력(+param_set_id)`, `sampling = {kind, input, meta: null}`, `engine='native'`, `generator='PLATFORM'`. `seed` 열 규칙: count·seed가 있는 kind만 params `seed` 기록.
- **워커** `doe_native.py`·`doe_native_set.py`(단계 DG_PREP 상당 ③ 조합): kind가 `lhs`/없음 → 지금 코드. `train_doe` → `reuse_matrix`(지금). 그 밖 → `doe_platform.build(...)` 행의 `applied_values`를 `doe_matrix.csv`에 쓰고 `train_does.sampling.meta`를 채움. 다중 baseline → `stratified_lhs(..., gen, ...)`에 kind별 생성기(`lhs_values` | lhs_opt 단위 → 값 | halton | random)를 넘김(함수 이름 `stratified_lhs`는 유지, 층 seed 규칙 불변). 이후 형상 생성·조립·SimLab 미사용 경로·solve는 무변경(DM-C7).
- **응답** `doe_out._platform_out`: native이고 `doe_type='NATIVE_LHS'`이면 지금처럼 `sampling: null`. 그 밖 native는 플랫폼과 같은 `sampling{kind,label,desc_id,meta}`, `gen: null`(native는 run별 점 표 없음 — 기존).
- **화면** `DoeGenCard.NativeFields`: 고정 select·`NATIVE_ONLY_LHS` 안내를 지우고 `DoePlatformFields`(Altair 플랫폼과 같은 드롭다운·칸)를 쓴다. 기본 `lhs`, 라벨은 공용 표시 이름. 다중 baseline이면 `train_native_multi` 밖 항목은 회색 + 사유(DM-C4 문구), 층화 안내 줄은 유지. `buildNativeParams`는 `lhs`일 때 지금 body(`sampling:{kind:"lhs",count,seed}`) 그대로, 그 밖은 `buildSampling` 결과.

### 5.2 ①-3 Altair 플랫폼
- `doe_platform.KINDS`·`_DEFAULTS`에 `halton{count, seed=1}`·`random{count, seed=1}`·`table{text}` 추가. `table` 검사 `TABLE_OUT_OF_RANGE`(①만). HyperStudy 모드·정의 파일·hstbatch·SimLab 단계는 손대지 않는다.
- `check`의 대체 검증 규칙(`lhs_opt` → 같은 count·seed `lhs`)은 그대로. `halton`은 실제 생성으로 검증(가벼움).

### 5.3 ④ 일괄 예측
- `build_matrix`에 `halton`·`random` 분기(§4.1). 단일 baseline 화면 목록에 두 항목 추가, 칸은 run 수·시드·범위 표(LHS 계열과 같음).
- 다중 baseline `build_multi_matrix`: `lhs`만 → `SITE_KINDS[batch_multi]`(DM-C4). 그 밖은 기존 code `MULTI_BASELINE_SOURCE`, 문구를 DM-C4로 바꿈.

### 5.4 ⑥ 내장 최적화 탐색
- 스키마 `SoExploreNew`: `method: Literal[lhs, lhs_opt, sobol, halton, random] = "lhs"`, `criterion: Literal[maximin, corr] | None`(lhs_opt만, 그 밖이면 422). `count` 생략 기본값 = 기존 식, `sobol`이면 그 값 이상 가장 작은 2^m(≤ 상한, 넘으면 상한 이하 최대 2^m).
- `_explore_batch`: `method == "lhs"` → 지금 코드 그대로. 그 밖 → 같은 단위 설계 함수로 `st["bounds"]` 값 행을 만들고 기존 표 경로(`build_matrix_for({"kind":"table"})`, 정수 반영·`oor_parameters` 그대로) → `source_kind = METHODS[method][0]`, `source_meta` = §4.1·S15 meta. 다중 baseline은 `build_multi_matrix`(DM-C4, `sobol` 제외).
- `settings.explore`에 `method`(생략 시 저장하지 않음 → 기존 행 불변). 보고서 `report_html/opt.py` 탐색 문구 "새 탐색 LHS"를 "새 탐색 <표시 이름>"으로.
- 화면 `SurrogateSetup` ② 탐색: "새 DOE"일 때 방식 드롭다운 1개(기본 LHS) + run 수 + 시드(+ 최적화 LHS 기준 세그먼트). Sobol이면 run 수 칸 안내 "2의 거듭제곱".

### 5.5 MCP·DB·문서
- MCP: 도구 입력은 OpenAPI에서 나오므로 스키마 변경으로 자동 반영(이식 가능 부분집합 — enum만 추가). `mcp/job_kinds.py` 설명 갱신: `sampling` "플랫폼 표본 방식 {kind: lhs_opt|sobol|halton|lhs|random|fullfact|fracfact|pb|bbd|ccd|table|train_doe, …} — platform·native 공통", `seed` "native lhs 전용 옛 입력(sampling.seed 권장)". `generated/job_kinds.json` 재생성. 용어집에 새 약어 없음(방식 이름은 엔티티 아님).
- DB: migration `0023_doe_methods`(down_revision `0022_job_queues` — 같은 v0.2.9의 대기열 분리): `ck_predict_batches_source_kind`에 `'HALTON','RANDOM'` 추가(기존 행 무변경, downgrade RuntimeError 관례). `train_does.doe_type`은 제약 없는 문자열 — 변경 없음. `registry.PLATFORM_DOE_TYPES`에 `HALTON`·`RANDOM`·`TABLE` 포함.
- 화면 공용: `lib/samplingKinds.ts`(`SITE_KINDS`, 묶음 순서), `lib/samplingDescs.ts`(§4.1 설명문), `lib/samplingRuns.ts`(권장 run). 빌드본 `frontend-dist/` 함께 커밋.

## 6. 시험(V-DM-*)

| # | 항목 | 판정 |
|---|---|---|
| V-DM-1 | Native `lhs` 골든: 요청 3모양(생략·`{num_runs,seed}`·`sampling:{kind:"lhs"}`)의 `doe_matrix.csv`·`doe_type`·`doe_label`·`options`·`sampling`·응답이 def0517 고정 기대값과 같음(단일·세트·다중 baseline 각각) | 바이트 동일 |
| V-DM-2 | Native 새 지점: `train_native` 각 kind(10종)의 워커 행 = 같은 입력의 `doe_platform.build` 행, API check run 수 = 워커 행 수, `train_does.sampling.meta` 기록, 응답 `sampling.kind` | 전 kind 통과 |
| V-DM-3 | 다중 baseline(①·④·⑥): `lhs` 층화 골든 불변, `lhs_opt`·`halton`·`random`은 층별 개수 차 ≤ 1·같은 seed 같은 행, `sobol`·요인·응답면·표 → `DESIGN_UNSUPPORTED`/`MULTI_BASELINE_SOURCE`(DM-C4 문구) | 통과 |
| V-DM-4 | `halton`: 범위 안, 같은 (k,count,seed,scipy 버전) 같은 값, scipy 직접 호출과 일치, `<kw>` 판정 공유, import 실패 흉내 → `GENERATOR_UNAVAILABLE`. `random`: 골든(표준 `random`), 행 우선 소비 순서 | 통과 |
| V-DM-5 | ① `table`: 머리줄 불일치·값 비유한·크기 초과·행 수(2~상한)·`TABLE_OUT_OF_RANGE`(Altair·Native 모두), ④ table은 기존대로 범위 밖 허용 | 통과 |
| V-DM-6 | 기존 골든 무수정 통과: V3-S9-5(④ lhs), V3-S15-*(새 7종), V3-S18-*(① 플랫폼 8종), ④ 기본 `lhs_opt`, Altair HyperStudy 4유형 params body(V3-S18-10) | 무수정 통과 |
| V-DM-7 | ⑥: `method` 생략 요청의 탐색 배치(`source_kind`, meta, 값)·`settings` 저장본이 def0517과 같음. 각 method의 `source_kind`·meta, `sobol` count 2^m 검사·기본값, `criterion` 오용 422 | 통과 |
| V-DM-8 | `SITE_KINDS` 일치: openapi 지점별 enum = registry(백엔드 정적 시험), 프런트 `SITE_KINDS` = `schema.d.ts` 유니언(타입 시험), 화면 기본값(①-3 Altair·④ `lhs_opt`, ①-3 Native·⑥ `lhs`) | 통과 |
| V-DM-9 | 화면: 각 지점 드롭다운 1개 + kind별 칸만(§4.3), 변수 수 밖 방식 회색 + "— 변수 k개에서 불가", Native 화면에 "LHS만" 문구 없음, 실제 run N개 표시 | 통과 |
| V-DM-10 | ⑤ 영향도: `HALTON`·`RANDOM` formal, ① `TABLE` reference, `NATIVE_LHS` formal, 기존 등급 표(S15 §20.7) 무변경 | 통과 |
| V-DM-11 | MCP: `job_kinds.json` 재생성 차이 = 설명·enum만, 도구 스키마 이식 가능 부분집합 시험(mcp.md §15) 통과, native DOE plan(`sampling.kind=halton`) → confirm → run | 통과 |
| V-DM-12 | 범위 보호: SimLab·HyperStudy 실행 모듈(hstbatch·SimLab 단계·정의 파일) diff 0, 새 의존성 0(`pyproject.toml`·`requirements.lock` 무변경), migration 1개 | 검사 |
| V-DM-13 | 성능 기록: `lhs_opt` n=500·k=30, `halton` n=500·k=50 생성 시간(워커). `lhs_opt`가 60초를 넘으면 리스크 R2 조치를 Plan에 보고 | 측정·보고 |

`scripts/test-all` 통과가 완료 조건(Linux, Altair 없음 — 가짜 도구).

## 7. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | Native 새 kind 경로가 `lhs` 분기를 건드려 골든이 바뀜 | lhs 분기를 먼저 고정 시험(V-DM-1) 후 새 분기만 추가 |
| R2 | `lhs_opt`는 순수 Python 교환 탐색(T=2000) — ① 상한 500·변수 수십 개에서 수십 초 가능 | 워커(DG_PREP)라 API 무영향(API check는 lhs 대체 검증). V-DM-13 측정, 넘치면 알고리즘 상수가 아닌 구현 최적화만(결과 동결) |
| R3 | `sobol`·`halton`은 scipy 버전이 바뀌면 값이 달라짐 | meta `generator` 기록(기존 Sobol과 같음). 오프라인 묶음 scipy 버전 고정(`requirements.lock`) |
| R4 | `halton`은 변수가 매우 많으면(수십 개 이상) 뒤쪽 차원 상관 | 스크램블 고정, quality(`max_abs_corr`) 표시, 설명문에 명시 |
| R5 | 표 붙여넣기(`text`)가 업로드 규칙(분할 업로드만)과 충돌한다는 오해 | 파일 업로드가 아니라 기존 ④와 같은 JSON 본문 문자열(≤1 MiB), 서버에 파일로 저장하지 않음 |
| R6 | `0023_doe_methods`는 `0022_job_queues`(대기열 분리) 뒤에만 적용 가능 — 대기열 분리가 늦으면 체인이 막힘 | roadmap §2 체인 고정(0022 → 0023), 대기열 분리 병합 후 BE 착수 또는 같은 브랜치 순차 |
| R7 | opt-direct(별도 브랜치 계약)의 초기 DOE가 따로 LHS를 정할 수 있음 | opt-direct 병합 시 `SITE_KINDS`에 site 추가로 맞춤(후속 변경 메모) |

## 8. 파일 소유(겹침 없음)

- Impl-Backend: `physicsai_core/sampling/{registry,qmc,matrix,matrix_basic 또는 새 matrix_more}.py`, `stage1_train_data/doe_platform.py`, `stage4_predict/batch_multi.py`, `geometry/baselines_table.py`(생성기 인자 일반화만), `physicsai_api/schemas/{stage1_train_data,surrogate_opt_req,predict_batch_source}.py`, `services/job_params/{stage1_native,stage1_train_data}.py`, `services/{stage1_train_data,surrogate_opts,surrogate_opt_problem}.py`, `report_html/opt.py`, `mcp/job_kinds.py`·`generated/job_kinds.json`, `db/tables/predict_batch.py`, `migrations/versions/0023_doe_methods.py`, 워커 `steps/stage1_train_data/doe_native{,_set}.py`, `backend/openapi.json`, 시험.
- Impl-Frontend: `stages/stage1/{DoeGenCard.tsx,DoePlatformFields.tsx,doeGenParams.ts}`, `stages/stage4/batch/{SamplingPicker,samplingSource}`, `stages/stage5/surrogate/SurrogateSetup.tsx`, `lib/sampling*.ts`, mock·시험, `frontend-dist/`.
- 순서: 계약(이 문서) → BE(registry·새 kind → ① Native → ④ 다중 → ⑥ → openapi·MCP) → FE → Verifier(V-DM-1~13).

## 9. 미결 처리(사용자 확정 2026-10-22)

- Q1 확정: ① 표(CSV) 값이 ①-2(세트) 학습 범위 밖이면 막는다 — problem `TABLE_OUT_OF_RANGE`(§4.1, V-DM-5). ④ table은 기존대로 `out_of_range` 표시·허용.
- Q2 확정: ①-3 Native 화면 기본 방식은 `lhs` 유지(DM-C8, §3). Altair 플랫폼·④ 기본 `lhs_opt`도 그대로.
- migration 번호: `0022_job_queues`(대기열 분리, 같은 v0.2.9)가 먼저이므로 이 계약은 `0023_doe_methods`(down_revision `0022_job_queues`).

## 변경 메모
- 2026-10-22 작성(Plan). geometry-engine.md §7.3.3 "native = 플랫폼 LHS"를 GE-C20으로 대체, s15_sampling.md §20.1 비범위 "⑥ 탐색 LHS 유지"를 이 문서 DM-C5로 대체.
- 2026-10-22 사용자 확정 반영: Q1(① 표 범위 밖 막음)·Q2(Native 기본 lhs) 확정, migration `0022_doe_methods` → `0023_doe_methods`(down_revision `0022_job_queues`), v0.2.9 = 대기열 분리·DOE 방식·조립 매칭.
