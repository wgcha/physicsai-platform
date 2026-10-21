# 계약: Native 템플릿 변수 정의(선택·범위) — 학습 변수와 독립

> 상태: 확정(2026-10-21, 사용자 결정 D1~D5 반영). 상위 계약 [geometry-engine.md](geometry-engine.md)(GE, 변경 메모 GE-C18), ⑥ 규칙은 [opt-native.md](opt-native.md)·phase3 §18(O5), ④ 일괄은 phase3 §14·§20(S15). 충돌 시 이 문서 우선(Native 경로 한정). 기준 커밋 4c0192c(`feat/r1-v023`). **구현 반영: v0.2.4 통합본 `feat/r1-v024` 8206870**(변경 메모 NV-C1).
> ID 규칙: 결정 `NV-n`, 시험 `V-NV-n`, 변경 메모 `NV-Cn`.

## 0. 한 줄 요약

Native 템플릿(④ 파라미터 세트, `engine='native'`)의 **변수 구성(사용할 피처)과 범위(하한·상한)를 사용자가 새로 정한다**. 세트 상세 표에서 기본 정의를 저장(리비전 기록)하고, ⑥ 내장 최적화와 ④ 일괄 예측에서도 그 자리에서 추가·제외·범위 변경을 한다. 범위는 막지 않고 **학습 범위 밖 = "학습 형상 분포 밖 — 외삽 주의"**, **모핑 가능 범위(feasible) 밖 = "모핑 실패 가능"** 경고만 낸다. 실행마다 사용한 변수 정의를 스냅숏으로 남겨 나중에 세트를 고쳐도 과거 배치·최적화는 그대로 재현된다. Altair 경로는 바꾸지 않는다.

## 1. 배경·범위

### 1.1 사용자 근거(원문, 2026-10-21)

"native는 변수 선택및 범위를 새로 정할수 있게해. 왜냐하면 형상학습을 위해 형상파라미터를 사용하지만, 예측모델은 형상이 입력이라 파라미터 의존성이 없어."

- 예측 모델 입력은 형상(메시)이다. 형상 파라미터는 형상을 만드는 수단일 뿐 모델 입력 열이 아니므로, 템플릿 변수 구성·범위는 ①-2 학습 변수·범위와 독립이어도 예측은 성립한다(학습 분포 밖이면 정확도만 떨어짐 → 경고).
- 현재 문제(코드 확인, 4c0192c):
  - 12변수 템플릿에서 4변수만 쓰려면 ①에서 4변수 DOE를 새로 만들고 "① 결과로 만들기"(from-train)로 세트를 다시 등록해야 한다(세트 변수 = `param_sets.parameters`·`S/parameters.json`, 편집 API 없음).
  - ⑥ `surrogate_opt_space._bounds`는 범위가 세트 min·max 밖이면 422 `BOUNDS_OUT_OF_RANGE`("학습 범위 안이어야")로 막는다. 이때 "학습 범위"는 실제로는 **세트 범위**다(폴더 등록 Native 세트는 피처 기본 ±5%/±5 mm일 뿐 학습과 무관).
  - ④ 일괄 `ranges`는 세트 밖도 허용하지만 변수 추가·제외는 못 한다(제외 = 세트 min = max일 때만 고정).

### 1.2 사용자 결정(확정)

| # | 결정 |
|---|---|
| D1 | 편집 위치: ④ Native 세트 상세 변수 표(사용·하한·상한, 위치형 mm)로 기본 정의 + ⑥ 내장 최적화·④ 일괄 예측에서 그 자리에서 변수 추가·제외·범위 변경 |
| D2 | 범위 규칙(Native만): 학습 데이터 범위 밖 = 경고 "학습 형상 분포 밖 — 외삽 주의", envelope(feasible) 밖 = 경고 "모핑 실패 가능", 실패 run은 기존대로 스킵. 차단 없음 |
| D3 | 범위: Native 한정. Altair(SimLab·NX·HyperStudy) 경로는 코드·UI·동작 무변경(경계 시험 포함) |
| D4(Q1) | ⑥·④ 일괄에서 고친 내용은 그 실행에만 적용(스냅숏 기록), 세트 정의는 ④ 상세에서만 변경 |
| D5(Q2) | 공칭을 포함하지 않는 범위 허용 + 경고 `VAR_NOMINAL_OUTSIDE`, Native 폴더 검증에서만 `min ≤ nominal ≤ max` 검사 해제 |

### 1.3 범위 / 비범위

| 범위 | 비범위(후속) |
|---|---|
| Native 단일 baseline 세트(solid·shell)의 형상 변수 정의 편집·리비전 | 다중 baseline 세트(`param_map.json`)의 추가·제외·정의 편집(NV-9) |
| ⑥ `SURROGATE_OPT`(+opt-direct가 같은 `normalize`를 쓰면 그대로 적용) 변수 추가·제외·범위, 경고 전환 | ④ 단건 예측(PREDICT A) 화면 변경 — 세트 정의를 그대로 따름(§7.4) |
| ④ `PREDICT_BATCH`(표본 방식 전부) 변수 추가·제외·범위 | 쉘 두께 PROP 행 선택(기존 `PUT /props` 소관 — 여기선 범위·제외만. PROP 행은 `ps.parameters`의 `source:"prop"` 행으로 ⑥·④ 일괄 표에 실행 변수로 나온다, §7.2·§7.3) |
| ①-3 DOE(세트 기준, `doe_native_set`)가 세트 정의를 스냅숏으로 사용 | 학습 범위 강제 제약, 외삽 정도 정량화(거리 지표) |
| 학습 범위 출처 해석(모델 → 데이터셋 → ① DOE) | paicad 변경(불필요 — §9) |

## 2. 결정 요약(NV-1~NV-12)

| ID | 결정 |
|---|---|
| NV-1 | **변수 풀(pool)** = 세트 피처 파일의 그룹 대표 + 그룹 없는 피처(GE §4.4 `values.json` 키 집합, `features_view.representative_params`와 같은 규칙, 쉘은 `shell_rows` 기본 대상 component). 추출 조건(EF-12)은 풀을 정하고, 이 기능은 **풀 안에서 선택·범위만** 정한다 → 등록 후 추출 조건 불변 규칙과 충돌 없음 |
| NV-2 | **세트 정의(현재값)** = 기존 `S/parameters.json` + DB `param_sets.parameters`(선택된 행만, 형식 불변). 기존 소비자(일괄 조합·⑥·단건·①-3)가 고치지 않고 새 정의를 따른다. 제외 변수는 행이 없으므로 `values.json`에서 빠져 **공칭**(GE §4.4 "빠진 이름은 공칭") |
| NV-3 | **리비전** = `S/vars/vars.json`(현재 리비전 메타) + `S/vars/history/rev_<NNNN>.json`(불변). `S/native/` 밖에 둔다(`native-prepare`가 `S/native/`를 `_backup`으로 옮기므로). 파일 없음 = 리비전 0(등록 정의) |
| NV-4 | **실행 스냅숏**: Native 실행(④ 일괄·⑥·①-3 세트 DOE)은 생성 시 쓴 변수 정의 전체를 기존 JSONB 열/작업 params에 기록하고, 워커·조회는 스냅숏이 있으면 `ps["parameters"]` 대신 그것을 쓴다(재시도·재개·조회 재현). migration 없음 |
| NV-5 | ⑥·④ 그 자리 편집 = 요청 선택 필드 `vars: {add?: [이름], exclude?: [이름]}` + 기존 `bounds`/`source.ranges`. 유효 변수 = (세트 정의 − exclude) + add. 세트 정의는 바꾸지 않는다(D4 확정) |
| NV-6 | **제외 ≠ 고정**: 고정 = 하한 = 상한(값 지정, 변수 목록·결과 표에 남음), 제외 = 변수 목록에서 빠지고 공칭 유지(결과 표에 없음) |
| NV-7 | 범위 규칙(Native): 유한·하한 ≤ 상한만 검사. 학습 범위·feasible 밖은 경고(`VAR_OUT_OF_TRAIN`·`VAR_OUT_OF_FEASIBLE`), `BOUNDS_OUT_OF_RANGE`는 Native에서 내지 않음(서버·프런트) |
| NV-8 | **학습 범위 출처**(§5) = 모델 → `dataset_id` → 데이터셋 `source_path`의 ① DOE(`dataset_engine._doe_ids`) → `train_does.parameters_snapshot`. 모델·데이터셋에는 파라미터 범위 메타가 없음(코드 확인). 추적 불가면 외삽 경고 생략 + 안내 1줄 |
| NV-9 | 다중 baseline 세트: 정의 편집 409, `vars` 422(선례: `PUT /props` "다중 baseline 세트는 형상 파라미터를 뺄 수 없습니다"). 범위 경고 전환(NV-7)은 적용 |
| NV-10 | 공칭이 범위 밖인 정의 허용(D5 확정). Native 폴더 검증만 `min ≤ nominal ≤ max` 검사를 끈다(Altair 검증 불변) |
| NV-11 | Altair 세트에 `vars`가 오면 422 `NATIVE_VARS_UNSUPPORTED`(요청 검증 1곳), 정의 API는 422. 그 밖 Altair 코드·화면 diff 없음 |
| NV-12 | paicad·DB 스키마 변경 없음. 파일(`S/vars/`) + 기존 JSONB 열(`param_sets.parameters`, `predict_batches.source_meta`, `surrogate_opts.settings`, `jobs.params`)만 |

## 3. 세트 변수 정의(저장·스키마·리비전)

### 3.1 구분: 피처 값 vs 사용자 정의

| 종류 | 출처 | 바뀌는가 |
|---|---|---|
| 공칭 `nominal`, 기본 범위 `range`, `feasible{min,max,source:estimate\|envelope}`, `ref_locked`, 종류·바디·그룹 | `S/native/extract/parameter_features.json`(paicad) | 재추출(새 세트)·envelope 반영 때만. 이 기능은 **읽기만** |
| 풀 | 위 파일 + `geom_options` 대칭 분리(`symmetry_split`) | 위와 같음 |
| **사용자 정의**: 사용 여부(행 있음/없음)·하한·상한 | `S/parameters.json`·`param_sets.parameters`(현재) + `S/vars/`(리비전) | `PUT /param-sets/{id}/variables` |

### 3.2 `S/vars/vars.json`·`history/rev_<NNNN>.json`

```json
{"schema_version": 1, "revision": 3, "parent_revision": 2,
 "saved_at": "2026-10-21T09:12:00+00:00", "saved_by": "u123", "saved_by_name": "홍길동",
 "features_sha256": "…", "engine_version": "0.11.0",
 "variables": [{"name": "CUSH_L_THK_1", "min": 10.0, "max": 16.0},
               {"name": "CUSH_L_RIB_U_1", "min": 40.0, "max": 52.0}]}
```

- `variables` = 형상 행만(쉘 두께 PROP 행 `source: "prop"`은 `PUT /props` 소관 — 저장 시 기존 PROP 행을 그대로 뒤에 붙임). 순서 = 풀 순서(피처 파일 순, 결정적).
- 첫 저장 때 `history/rev_0000.json`을 현재 `parameters.json` 형상 행으로 먼저 쓴다(`parent_revision: null`, `saved_by_name: "등록"`) → 등록 정의도 되살릴 수 있다.
- 저장 순서(API 한 요청, `PUT /props`와 같은 패턴): ① `history/rev_<n>.json` 새 파일(덮어쓰기 금지 — 있으면 409) ② `parameters.json`·`vars.json` 원자 쓰기 ③ 같은 트랜잭션에서 `ps_repo.set_values(parameters=rows)` + 감사 `PARAM_SET_UPDATE`(detail `{vars_revision, names, count}`). ③ 실패 시 ②를 이전 내용으로 되씀(①은 남겨도 무해 — 다음 저장은 `max(history)+1`). 원래 `vars.json`이 없었으면 지우지 않고(삭제 금지) **리비전 0 스텁** `{"schema_version": 1, "revision": 0, "parent_revision": null}`으로 되쓴다(파일 없음과 같은 뜻 = 리비전 0). `parameters.json`은 이전 바이트로 되씀.
- `parameters.json` 행 = `{name, nominal, min, max, unit}`(형식 불변, `nominal`·`unit`은 피처에서). 기존 행에 다른 키(`source`·`baselines`)가 있으면 보존.
- `features_sha256` = 저장 시 피처 파일 해시. 조회 때 다르면 응답 `stale_names`(풀에 없는 정의 이름)를 계산해 보여 주고, 저장 시 그 이름은 422 `VAR_UNKNOWN`.
- 삭제 API 없음. 리비전 파일은 사용자 산출물 규칙(삭제 금지)을 따른다.

### 3.3 추출 조건(EF)과의 관계

- EF-12: 추출 조건은 세트 등록 때 1회 정해 **피처 집합(=풀)**을 만든다. 이 기능은 풀을 바꾸지 않는다(재추출 없음, `extract_filter` 입력 없음).
- 풀 밖 변수가 필요하면 EF 규칙대로 새 세트(다른 추출 조건)로 등록한다. 화면 안내: "목록에 없는 변수는 추출 조건을 바꿔 새 템플릿으로 등록하세요".
- EF가 바꾼 NP_REGISTER(필터 있으면 features `range`로 표 생성·`PARAMS_JSON_IGNORED`)는 리비전 0의 내용만 정하며, 이 계약과 겹치지 않는다.
- reprep(`native-prepare`) 이름 검사(`np_register._register_reprep`)를 **같음 → 포함**으로 바꾼다: 세트 정의 형상 이름 ⊆ 다시 만든 풀이면 통과, 아니면 `PARAM_FEATURE_MISMATCH`(현재 from-train 세트 부분집합도 같은 검사에 걸리는 잠재 결함을 함께 해소). `S/vars/`는 reprep 백업 대상이 아니다.

### 3.4 검증 규칙(세트 정의)

| 검사 | 결과 |
|---|---|
| 이름 ∈ 풀 | 아니면 problem `VAR_UNKNOWN` "'{이름}'은 이 템플릿의 형상 변수가 아닙니다" |
| 중복 | `VAR_DUPLICATE` |
| min·max 유한, min ≤ max | `VAR_RANGE_INVALID` "하한·상한은 유한한 숫자이고 하한 ≤ 상한이어야 합니다" |
| 형상 행 0개 + PROP 행 0개 | `VARS_EMPTY` "변수를 하나 이상 고르세요" |
| 공칭이 범위 밖 | 허용(NV-10) — 경고 `VAR_NOMINAL_OUTSIDE` |
| feasible 밖·`ref_locked` 사용 | 경고 `VAR_OUT_OF_FEASIBLE`·`VAR_REF_LOCKED` |

- 오류 → 422 `NATIVE_VARS_INVALID` + problems `[{code, name?, message}]`. 경고는 응답 `warnings`(저장됨).
- `validate_native_folder`(Native만)는 `_load_parameters(..., require_nominal_inside=False)`로 호출(Altair `validate_folder` 기본값 True 그대로).

## 4. 실행 스냅숏(재현)

### 4.1 모양(`vars`, 모든 기록 위치 공통)

```json
{"schema_version": 1, "set_revision": 3, "edited": true,
 "variables": [{"name": "CUSH_L_THK_1", "nominal": 12.5, "min": 10.0, "max": 16.0, "unit": "mm", "origin": "set",
                "train": {"min": 11.875, "max": 13.125}, "feasible": {"min": 6.2, "max": 18.0, "source": "envelope"}},
               {"name": "CUSH_L_RIB_U_1", "nominal": 46.0, "min": 41.0, "max": 51.0, "unit": "mm", "origin": "added",
                "train": null, "feasible": {"min": 43.5, "max": 49.0, "source": "estimate"}}],
 "excluded": ["CUSH_L_FILLET_R_2"],
 "train_source": {"model_id": "…", "dataset_id": "…", "doe_ids": ["…"]}}
```

- `variables[].min/max` = 이 실행의 **기준 범위**(세트 정의 또는 추가 변수의 피처 기본 `range`). 실행별 덮어쓰기는 기존 필드(⑥ `settings.bounds`, ④ `source.ranges`)에 그대로 둔다.
- `train`·`feasible`·`train_source`는 표시·경고 재현용(값 계산에 쓰지 않음). 학습 범위 모름 = `train: null`, `train_source: null`.
- PROP·다중 baseline 행(`source`·`baselines` 키)은 그대로 복사한다.
- 크기 상한: 변수 ≤ 풀 크기(실물 수십~백여 개), 수치만 — DB 규칙(수치 요약) 범위.

### 4.2 기록 위치·소비

| 실행 | 기록 | 소비(스냅숏 우선, 없으면 기존 `ps["parameters"]` — 이전 기록 호환) |
|---|---|---|
| ④ `PREDICT_BATCH`(사용자·⑥ 소유 모두) | `predict_batches.source_meta.vars` + job params `vars` | API 조합(`build_matrix_for`), 워커 `batch_native.bp_prep`(names·`nominals`·`batch.json` `parameters`), 배치 상세·곡선·CSV·⑤ 분석의 변수 열 |
| ⑥ `SURROGATE_OPT` | `surrogate_opts.settings.vars` | 워커 `surrogate.py`(검증 조합 names·`build_matrix_for`)·`surrogate_final.py`(기준안 공칭·names)·재개·추가 검증, 조회 `surrogate_opts_view` |
| ①-3 `TD_DOE_GEN`(`param_set_id`, `doe_native_set`) | job params `vars`(세트 정의, 그 자리 편집 없음) → 결과는 기존 `train_does.parameters_snapshot` | 워커 `doe_native_set`의 `params = list(ps["parameters"])` 두 곳 |

- 공용 순수 함수(신규 `physicsai_core/geometry/native_vars.py`, 표준 라이브러리만): `pool(doc, geom_options, kind, component)`, `effective(set_rows, pool, add, exclude, train, feasible) -> vars`, `apply(ps, vars) -> ps'`(`parameters`만 `vars.variables`로 바꾼 사본), `warn_rows(vars, bounds) -> notes`. 워커·API는 `apply` 결과를 기존 함수에 넘긴다(기존 함수 시그니처 불변).
- 세트 정의를 실행 중에 고쳐도 진행 중·재시도·재개 작업은 스냅숏을 쓴다(정의 편집은 작업 상태와 무관하게 허용, 잠금 없음).

## 5. 학습 범위(정의 출처)

### 5.1 코드 확인 결과

- `models`·`datasets` 테이블에 파라미터 범위 열·메타 없음(`model_data.py`). `models.dataset_id`(NULL 가능), `datasets.source_path`(③-1 입력 폴더)만 있다.
- `dataset_engine._doe_ids(root, source_path)`가 `01_train/results/<doe_id>`·`01_train/doe/<doe_id>` 소속을 판별한다(그 폴더 자체면 전체 DOE).
- `train_does.parameters_snapshot` = DOE에 쓴 변수 `{name, nominal, min, max, unit}`(다중 baseline DOE는 지시·원-핫 행 포함). Native DOE 폴더 `D/native/extract/parameter_features.json`이 있다.

### 5.2 규칙(`native_vars.train_ranges(conn, root, model) -> {name: {min,max}|None}, source|None`)

1. 모델 `dataset_id` 없음 → 모름. 데이터셋의 `_doe_ids` = None(판별 불가) → 모름.
2. 대상 DOE = 그 id(또는 전체) 중 `status = READY`·`engine = native`. 0개 → 모름.
3. 이름마다 DOE별 구간: snapshot에 있으면 `[min, max]`, 없고 그 DOE 피처 대표 이름에 있으면 `[nominal_D, nominal_D]`(학습 때 공칭 고정 = 그 변수를 움직이면 외삽), 둘 다 없으면 그 DOE는 판단 불가 → 이름 결과 `None`.
4. **동일 피처 확인**: 이름이 같아도 추출 조건이 다르면 번호(`k`)가 다른 피처를 가리킬 수 있다(EF-3 재번호). 세트 피처와 DOE 피처의 `type`·`body`가 같고 `|nominal_S − nominal_D| ≤ 1e-6·max(1,|nominal|)`일 때만 사용, 아니면 `None` + note `TRAIN_RANGE_UNMATCHED`.
5. 여러 DOE = 구간 합집합(min의 최소, max의 최대). snapshot의 `__na`·`baseline__*` 등 풀 밖 이름은 무시.
6. 모름(`source = None`)이면 `VAR_OUT_OF_TRAIN` 경고를 내지 않고 note `TRAIN_RANGE_UNKNOWN` "모델의 학습 범위를 알 수 없어 외삽 경고를 생략합니다(모델의 데이터셋이 ① DOE 결과가 아님)" 1줄. 이름별 `None`도 그 이름만 생략.

- 비교 허용오차: 학습 범위 `1e-9·max(1,|x|)`, feasible `1e-9`(프런트 `exceedsFeasible`와 같음). feasible은 있는 쪽만 비교(min·max 각각 null 허용).
- ④ 세트 상세(모델 없음)는 학습 범위를 보이지 않는다(모델별로 다르므로). ⑥·④ 일괄은 고른 모델 기준.

### 5.3 일괄 행 `out_of_range`의 의미(Native)

- Native 배치의 `predict_batch_runs.out_of_range`(이름 목록, 화면 "학습 범위 밖" 점)는 **학습 범위 기준**으로 계산한다(모름이면 빈 목록). Altair는 기존(세트 범위) 그대로. 근거: 화면 문구가 이미 "학습 범위 밖"이고, Native 세트 범위는 이제 사용자 정의라 학습과 무관.
- feasible 밖 run은 행 열을 늘리지 않고 notes 요약 "모핑 가능 범위 밖 값이 있는 run n개 — 형상 생성 실패(스킵) 가능".

## 6. API(추가적·하위호환)

### 6.1 세트 정의

| API | 내용 |
|---|---|
| `GET /param-sets/{id}/variables?model_id=` | 응답 `NativeVars`(아래). Native만(Altair 422 `NATIVE_VARS_UNSUPPORTED`). `model_id` 있으면 `train` 채움(같은 Study 모델, 없으면 404 기존 코드) |
| `PUT /param-sets/{id}/variables` | 본문 `{base_revision: int, variables: [{name, min, max}]}`(형상 행 전체 교체). 권한 = `require_writable`(403). 응답 `NativeVars`(갱신본) + `warnings`. 422 `NATIVE_VARS_INVALID`(problems §3.4), 409 `NATIVE_VARS_CONFLICT`(base_revision ≠ 현재, "다른 사용자가 먼저 저장했습니다 — 새로 불러온 뒤 다시 저장하세요"), 409 `NATIVE_VARS_MULTI_UNSUPPORTED`(다중 baseline), 409 `NATIVE_VARS_GEOMETRY_OFF`(쉘 세트에서 `PUT /props`로 형상 행을 끈 상태 — "쉘 두께 설정에서 형상 파라미터를 켠 뒤 편집하세요") |
| `ParamSet.native` | `vars_revision: int`(0 = 등록 정의), `vars_count: int`(형상 행 수) 추가 |

`NativeVars`:

```json
{"revision": 3, "features_sha256": "…", "editable": true, "reason": null,
 "variables": [{"name": "CUSH_L_THK_1", "min": 10.0, "max": 16.0}],
 "pool": [{"name": "CUSH_L_THK_1", "type": "THICKNESS", "body": "CUSH_L", "nominal": 12.5, "unit": "mm", "position": false,
           "default_range": {"min": 11.875, "max": 13.125}, "feasible": {"min": 6.2, "max": 18.0, "source": "envelope"},
           "ref_locked": false, "group": "G1", "train": {"min": 11.875, "max": 13.125}}],
 "stale_names": [], "train_source": {"model_id": "…", "dataset_id": "…", "doe_ids": ["…"]},
 "notes": [{"code": "TRAIN_RANGE_UNKNOWN", "message": "…"}],
 "history": [{"revision": 3, "saved_at": "…", "saved_by_name": "홍길동", "count": 6}]}
```

- `editable=false`이면 `reason`(다중 baseline·형상 행 꺼짐·Altair). `history`는 최근 20개 요약, 특정 리비전 본문은 `GET …/variables?revision=n`(`variables`만 그 리비전, 되살리기는 화면이 그 값으로 PUT).

### 6.2 ⑥ 내장 최적화(`POST /studies/{id}/surrogate-opts[/preview]`)

- 요청 `SurrogateOptCreate.vars?: {add?: string[], exclude?: string[]}`(extra 금지, 각 ≤ 풀 크기, 중복 불가).
- Native `normalize`(분기 1곳 — `engine_of(ps) == "native"`):
  1. 유효 변수 = (세트 정의 − exclude) + add(세트 순서 뒤에 풀 순서). add 이름 ∉ 풀 또는 이미 세트 정의 → `BOUNDS_INVALID`(field `vars.add`), exclude ∉ 세트 정의 → `BOUNDS_INVALID`(field `vars.exclude`). 다중 baseline에 `vars` → problem `NATIVE_VARS_MULTI_UNSUPPORTED`.
  2. `bounds` 키 ∈ 유효 변수(아니면 기존 `BOUNDS_INVALID`), 생략 = 기준 범위(세트 정의, 추가 변수는 피처 `range`).
  3. 유한·하한 ≤ 상한 검사만. **`BOUNDS_OUT_OF_RANGE` 미발행**. 경고 = 미리보기 응답 `var_notes`·생성 응답(`SurrogateOptSummary.warnings`)에 `{code, name, message}`: `VAR_OUT_OF_TRAIN` "'{이름}' 학습 형상 분포 밖 — 외삽 주의(학습 {a}~{b})", `VAR_OUT_OF_FEASIBLE` "'{이름}' 모핑 실패 가능(모핑 가능 {a}~{b})", `VAR_REF_LOCKED`, `TRAIN_RANGE_UNKNOWN`·`TRAIN_RANGE_UNMATCHED`.
  4. 미리보기 응답 `var_rows: [{name, origin, nominal, base:{min,max}, train, feasible, unit, position}]`(표 초기화용), `excluded: [이름]`.
  5. 생성 시 `settings.vars`(§4.1), `settings.names`·`bounds`는 유효 변수 기준(기존 키 그대로).
- 추가 검증(`POST /surrogate-opts/{oid}/verify`): Native는 점이 `settings.bounds` 밖이어도 422 대신 경고(`VAR_OUT_OF_BOUNDS` "최적화 범위 밖 점")·위 경고. 점의 키 = `settings.vars` 이름(아니면 기존 422).
- Altair: 동작 무변경. `vars`가 오면 problem `NATIVE_VARS_UNSUPPORTED` "변수 추가·제외는 Native 템플릿에서만 쓸 수 있습니다".

### 6.3 ④ 일괄 예측(`POST /jobs` `PREDICT_BATCH`·미리보기)

- `PredictBatchParams.vars?`(§6.2와 같은 스키마). Native:
  - 유효 변수 계산·오류는 §6.2와 같음(problem 코드 `RANGE_INVALID` field `vars.*` — 일괄 기존 코드 체계). `source.ranges` 키 ∈ 유효 변수, 생략 = 기준 범위. `ranges`의 기존 규칙(lo < hi) 그대로, 고정은 기준 범위 min = max일 때(기존).
  - `table`: 헤더 = 유효 변수 이름 전부(기존 "템플릿 이름 전부" 규칙을 유효 변수로).
  - `train_doe`: ① DOE 재생이므로 `vars`를 받지 않는다(오면 problem `RANGE_INVALID` "① 학습 DOE 재사용에는 변수 추가·제외를 쓸 수 없습니다"). 유효 변수 = DOE 헤더 이름(⊆ 풀이어야 — 풀 밖 이름이 있으면 problem `RANGE_INVALID`) — 세트 정의와 달라도 됨. note `VARS_FROM_DOE` "① DOE의 변수 구성을 그대로 씁니다". 다중 baseline 세트에 `vars`가 오면 표본 방식과 무관하게 problem `RANGE_INVALID`(NV-9, 일괄 코드 체계 — ⑥의 `NATIVE_VARS_MULTI_UNSUPPORTED`와 다름).
  - `sobol continue_from`: 이전 배치 `source_meta.vars`의 이름과 유효 변수가 다르면 기존 이어 붙이기 불가 problem(같은 규칙).
  - 미리보기 `PredictBatchPreview`에 `var_rows`·`excluded` 추가, 경고는 기존 `notes`에 §6.2 코드로 — **notes 항목은 `{code, message}`만**(기존 모양 유지, `name` 키 없음 — 변수 이름은 message 문구 안. ⑥ `var_notes`의 `{code, name, message}`와 다름). 행 `out_of_range`는 §5.3.
  - 생성 시 `source_meta.vars`(§4.1).
- 다중 baseline: `vars` → `RANGE_INVALID`(NV-9), 경고 전환은 적용. Altair: `vars` → 422 `NATIVE_VARS_UNSUPPORTED`, 그 밖 무변경.
- 배치 상세 응답에 `vars`(스냅숏, Native만, 없으면 null).

### 6.4 그 밖

- ①-3 `TD_DOE_GEN`(`param_set_id`): API가 세트 정의로 `vars`를 만들어 job params에 기록(요청 필드 추가 없음).
- ④ 단건 `PREDICT`: 변경 없음(세트 정의 = `ps.parameters`를 따름). "학습 범위 밖" 판정은 기존(세트 범위) — §11 R5.
- `backend/openapi.json`·`frontend/src/api/schema.d.ts` 갱신(Backend → Frontend 순서, AGENTS.md).

### 6.5 코드 표

| 코드 | 종류 | 문구(한국어) |
|---|---|---|
| `NATIVE_VARS_UNSUPPORTED` | 422 / problem | 변수 추가·제외는 Native 템플릿에서만 쓸 수 있습니다 |
| `NATIVE_VARS_INVALID` | 422(+problems `VAR_UNKNOWN`·`VAR_DUPLICATE`·`VAR_RANGE_INVALID`·`VARS_EMPTY`) | 변수 정의가 올바르지 않습니다 |
| `NATIVE_VARS_CONFLICT` | 409 | 다른 사용자가 먼저 저장했습니다 — 새로 불러온 뒤 다시 저장하세요 |
| `NATIVE_VARS_MULTI_UNSUPPORTED` | 409 / problem | 다중 baseline 템플릿은 변수 추가·제외를 아직 지원하지 않습니다 |
| `NATIVE_VARS_GEOMETRY_OFF` | 409 | 쉘 두께 설정에서 형상 파라미터를 켠 뒤 편집하세요 |
| `VAR_OUT_OF_TRAIN` | 경고 | 학습 형상 분포 밖 — 외삽 주의 |
| `VAR_OUT_OF_FEASIBLE` | 경고 | 모핑 실패 가능 |
| `VAR_OUT_OF_BOUNDS` | 경고(⑥ 추가 검증) | 최적화 범위 밖 점입니다 |
| `VAR_REF_LOCKED` | 경고 | 양면 접촉 피처 — 형상 생성이 실패할 수 있습니다 |
| `VAR_NOMINAL_OUTSIDE` | 경고 | 공칭이 범위 밖입니다(기준안은 범위 밖 점으로 표시) |
| `TRAIN_RANGE_UNKNOWN` / `TRAIN_RANGE_UNMATCHED` / `VARS_FROM_DOE` | 안내 | §5.2·§6.3 |

### 6.6 MCP 표기(mcp.md §8·§15 확장 규칙 — 릴리스 v0.2.4 동반)

| 대상 | `x-mcp` | 비고 |
|---|---|---|
| `GET /param-sets/{id}/variables` | `{"tool":"get_native_vars","risk":"read","confirm":"never","version":1,"summary_en":"Native template variable definition (used vars, ranges, pool, training range)","summary_ko":"Native 템플릿 변수 정의 조회(사용 변수·범위·풀·학습 범위)"}` | 요청 인자 `id`·`model_id`·`revision` 설명·예시 필수(V-MCP-6), 응답이 커지면 `history`는 최근 20개 그대로(64 KiB 이하) |
| `PUT /param-sets/{id}/variables` | `{"exclude":"웹 전용 편집"}` | 세트 정의 변경은 사람이 ④ 상세에서만(D4) |
| `SurrogateOptCreate.vars`·`PredictBatchParams.vars` | 별도 표기 없음 | mcp `JOB_KINDS` `surrogate_opt`·`predict_batch`의 `params_model`이 기존 요청 모델을 그대로 쓰므로 자동 포함(새 선택 인자 = 호환 변경, `kind_version` 불변). 도구 입력에서는 `params_json` 안(mcp §9.2) |
| 요약 `param_set` | – | mcp `SUMMARIES` `param_set`의 파라미터 목록은 스냅숏/세트 정의(`vars_revision`) 기준, `facts.vars_revision`·`facts.vars_count` 추가(구현 반영) |

- 병합 순서와 무관하게 위 표기를 이 계약 구현 커밋에 넣는다(`openapi_extra` — MCP 병합 전에는 무해한 확장 키). MCP가 먼저 병합됐다면 V-MCP-6 정적 시험이 누락을 잡는다. 두 operation은 mcp 동결 목록 `LEGACY_UNMARKED`에 넣지 않는다.

## 7. UI(후보 A — 필수 요소만, v0.2.2 표 + 3D 창 레이아웃 재사용)

### 7.1 ④ Native 세트 상세 `FeatureTable`(`NativeDetail.tsx`)

- 기존 `ViewSplit`(표 왼쪽·3D 오른쪽, 표 높이 = 3D 높이) 그대로. 표는 공용 `NativeVarsTable`(§7.2, 학습 범위 열 숨김). 열(구현 순서): **사용(체크)** · 이름 · 종류 · 바디 · 공칭 · 모핑 가능 범위 · **하한** · **상한** · 대칭 그룹 · 기준면 · 경고 — 모핑 가능 범위가 하한·상한 **앞**(입력 전에 한계를 보게). 기존 "범위" 문자열 열은 하한·상한 입력으로 대체.
- 편집 권한(`canEdit`)·`editable`일 때만 입력, 아니면 읽기 표시 + `reason`. 체크 해제 행은 회색(`unused`), 입력 비활성(값은 유지 — 다시 켜면 그 값, 처음 켜면 피처 기본 `range`).
- 위치형(`isPositionType`, RIB_POS 포함): 하한·상한 = 절대 좌표 mm 입력, 옆에 공칭 대비 Δ(작은 회색 "−5.0 / +5.0"). 치수형: mm 값.
- 행 경고 pill: feasible 밖 "모핑 실패 가능"(기존 `exceedsFeasible` 재사용), `ref_locked` 사용 "양면 접촉", 공칭 범위 밖 "공칭 밖".
- 표 머리줄: "변수 정의 rev {n} · 사용 {k}/{풀}" + [저장](변경 있을 때만 활성) + [되돌리기]. 저장 실패 문구 = 서버 problems. 409 충돌이면 "새로 불러오기" 버튼.
- 3D 창 `userRanges` = 편집 중 값(미저장 포함) → 치수선·미리보기가 즉시 반영. 3D 면 클릭 → 행 선택(기존).
- extract-filter의 "적용 조건: …" 줄(EF §8)은 이 머리줄 바로 위.

### 7.2 ⑥ `SurrogateSetup` "④ 변수 범위" 카드(Native 템플릿일 때만)

- 공용 표 `NativeVarsTable`(신규, `stages/stage4/geometry/`)을 쓴다: 열(구현 순서) **사용** · 변수 · 종류 · 공칭 · **학습 범위** · **모핑 가능 범위** · 하한 · 상한 · 고정 · 경고(학습 범위·모핑 가능 범위가 하한·상한 앞, ④ 일괄도 같은 순서 — 일괄은 머리 "파라미터·최소·최대", 완전요인은 "수준" 열 추가). 초기값 = 미리보기 `var_rows`(세트 정의) + 쉘 세트는 PROP 행(`ps.parameters`의 `source:"prop"` — 풀에 없지만 실행 변수, 범위·제외만, `vars.exclude`로 제외)을 뒤에 붙인다(④ 일괄 표도 같음).
- 표 아래 "변수 추가" 선택 상자(풀 − 현재, 종류·바디 표시) → 행 추가(`origin: added`, 하한·상한 = 피처 기본 범위). 추가 행은 [빼기], 세트 행은 사용 체크 해제 = 제외. 고정 체크는 기존 의미(하한 = 상한).
- 카드 aside: Native "범위 자유 · 학습 범위·모핑 가능 범위 밖은 경고 · 하한 = 상한이면 고정"(Altair는 기존 "학습 범위 안만 …" 그대로).
- 프런트 `soRules.ts`의 "학습 범위 {a}~{b} 안" 행 오류는 Native에서 끄고 경고 문구로(서버 `var_notes`를 그대로 표시). 학습 범위 모름이면 열 값 "모름" + 카드 아래 안내 1줄.
- 결과 카드(`ResultCards` "범위(학습)" 열 막대): **v0.2.4 구현은 현재 세트 범위(`min`·`max`) 기준**이다. `settings.vars.variables[].train` 기준(없으면 막대 생략)으로 바꾸는 것은 **후속**(roadmap 후속 항목 — NV-C1).

### 7.3 ④ 일괄 `BatchSetup`·`SamplingPicker`(Native일 때만)

- 범위 표(파라미터 · 최소 · 최대 · [수준])를 `NativeVarsTable`로 교체(+ 사용·학습 범위·모핑 가능 범위·경고 열, "변수 추가"). `table` 방식은 붙여넣기 안내의 헤더 목록을 유효 변수로, `train_doe` 방식은 변수 표 숨김 + "① DOE의 변수 구성을 그대로 씁니다".
- 미리보기 notes에 경고 표시(기존 notes 영역), 행 "학습 범위 밖" 점은 §5.3 기준.
- Altair 템플릿 화면·컴포넌트 무변경(분기 = `ps.engine === "native"` 1곳씩).

새 화면·시안 없음. `frontend-dist` 재생성 함께 커밋(AGENTS.md).

## 8. 마이그레이션

- DB 스키마 변경·migration 없음(`MIGRATION_HEAD` 불변). 새 데이터는 파일(`S/vars/`)과 기존 JSONB 열(`source_meta`·`settings`·`jobs.params`)에만.
- 기존 세트: `S/vars/` 없음 = 리비전 0, 동작 동일. 기존 배치·최적화: 스냅숏 없음 = 기존 경로(`ps["parameters"]`).
- 설정 키 추가 없음.

## 9. 구현 분해(파일 소유 비중첩)

| 담당 | 범위·파일 | 순서 |
|---|---|---|
| Impl-Geom | **불필요**(paicad 변경 없음 — 빠진 이름 = 공칭은 GE §4.4 기존 동작, feasible은 피처 파일 기존 키) | — |
| Impl-Backend | 신규 `physicsai_core/geometry/native_vars.py`(pool·effective·apply·warn_rows·train_ranges 순수부, 시험), `stage4_predict/param_set_files.py`(`_load_parameters` 인자 `require_nominal_inside`)·`param_set_native.py`(Native 검증에서 False), 신규 `physicsai_api/services/native_vars_api.py`(GET·PUT, 리비전 파일, 감사)·`routers/param_sets.py`(2 경로)·`param_set_native_api.enrich`(`vars_revision`·`vars_count`), `services/surrogate_opt_space._bounds`·`surrogate_opt_problem.normalize`(Native 분기·`settings.vars`)·`surrogate_opt_pareto`(추가 검증 경고), `services/job_params/stage4_batch.py`(`vars`·`source_meta.vars`·`train_doe` 규칙)·`sampling/matrix_rows`(out_of_range 기준 주입 인자), `job_params/stage1_native.py`(세트 DOE `vars`), 조회(`predict_batches_info`·`predict_batches_curves`·`surrogate_opts_view`·`design_map`의 변수 열 = 스냅숏 우선), 워커 `stage4_predict/batch_native.py`·`stage5_optimize/surrogate.py`·`surrogate_final.py`·`stage1_train_data/doe_native_set.py`(`apply`), `stage4_predict/np_register._register_reprep`(⊆ 검사)·`_params_from_features` 풀 규칙을 core로 이동, schemas·`backend/openapi.json`, 시험 | extract-filter Backend 병합 **뒤** 착수(§10) |
| Impl-Frontend | `stages/stage4/geometry/NativeDetail.tsx`(FeatureTable 편집·저장), 신규 `stages/stage4/geometry/NativeVarsTable.tsx`·`lib/nativeVars.ts`(경고 계산 = 서버와 같은 허용오차), `stages/stage5/surrogate/SurrogateSetup.tsx`·`soRules.ts`·`ResultCards.tsx`, `stages/stage4/batch/SamplingPicker.tsx`·`BatchSetup.tsx`, `api`(schema.d.ts 재생성)·`mock/surrogateOptCreate.ts`·일괄 mock, 시험, `frontend-dist` | openapi 갱신 뒤 |
| Plan | D4·D5(Q1·Q2) 확정 반영 완료(2026-10-21), 구현 차이는 NV-C* | — |

## 10. 진행 중 작업과의 충돌 지점

| 작업 | 겹치는 파일 | 처리 |
|---|---|---|
| extract-filter 구현(`feat/r1-v023`, Backend·Frontend 미착수/진행) | `param_set_native_api.py`(enrich: `native.extract_filter` vs `vars_revision`), `schemas`·`openapi.json`·`schema.d.ts`(ParamSet.native·NativeFeatures), 워커 `np_register.py`(EF: NP_REGISTER 행 생성·`PARAMS_JSON_IGNORED` / NV: reprep ⊆·풀 이동), `NativeDetail.tsx` FeatureTable 머리줄, `lib/geometry.ts`(`isPositionType`에 RIB_POS — NV가 사용) | **EF 먼저 병합 → NV는 그 위에서 착수**(같은 브랜치 순차 또는 rebase). openapi 재생성은 순차 |
| opt-direct(`feat/r1-directopt`, 계약만) | `surrogate_opt_space._bounds`·`normalize`·`SurrogateSetup.tsx` | direct도 `normalize`를 쓰므로 NV 규칙이 그대로 적용됨(direct `solver` 평가자의 ① DOE 표 헤더 = `settings.vars` 이름). 늦게 병합하는 쪽이 rebase. migration 번호 경쟁(0019)은 NV와 무관 |

## 11. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 학습 범위 추적 실패(데이터셋을 ① 밖 폴더로 만든 모델)로 외삽 경고가 안 나옴 | `TRAIN_RANGE_UNKNOWN` 안내를 표·미리보기에 항상 표시, "모름" 열 값 |
| R2 | 추출 조건이 다른 세트·DOE 사이 이름 충돌(`k` 재번호)로 엉뚱한 학습 범위 | §5.2-4 동일 피처 확인(type·body·공칭) |
| R3 | `ps["parameters"]`를 직접 읽는 소비자 누락 → 스냅숏과 다른 변수로 재시도·조회 | §9 파일 목록 + V-NV-3(정의 편집 후 재시도·재개·조회 비교) + 정적 검사(구현: `backend/tests/test_native_vars_core.py` — `backend/physicsai_api`·`physicsai_core`·`worker/physicsai_worker`의 `ps["parameters"]` 직접 읽기 **개수를 파일별로 고정**(`ALLOWED` = {파일: 개수}, 늘거나 줄면 실패 → 검토 후 갱신) + Native 실행 경로 8파일이 `nv.apply(ps, nv.vars_of(…))`를 쓰는지 문자열 검사) |
| R4 | 넓은 범위 → 모핑 실패 스킵 급증, ⑥ 탐색 run 낭비 | feasible 경고·스킵 수 표시(기존), envelope 측정 권장 문구 |
| R5 | ④ 단건 예측의 "학습 범위 밖"은 여전히 세트 범위 기준(이름과 의미 불일치) | 후속(단건도 모델 학습 범위 기준으로) — 이번 비범위 |
| R6 | 공칭이 범위 밖인 정의(NV-10)에서 ⑥ 기준안(공칭)·LHS 범위 해석 혼동 | `VAR_NOMINAL_OUTSIDE` 경고, 기준안 "범위 밖" 표시 |
| R7 | 동시 편집 덮어쓰기 | `base_revision` 409 |
| R8 | EF·opt-direct와 같은 파일 동시 수정 | §10 순서 |

## 12. 검증 기준(V-NV-*)

- **V-NV-1 정의 저장·리비전**: PUT → `S/vars/vars.json`·`history/rev_0000`(첫 저장)·`rev_<n>` 생성, `parameters.json` = DB `param_sets.parameters` = 선택 형상 행(+ 기존 PROP 행 보존, 풀 순서), 감사 `PARAM_SET_UPDATE`. `base_revision` 불일치 409, 오류 problems 4종, `?revision=n` 조회, `ParamSet.native.vars_revision`. `native-prepare` 후 `S/vars/` 유지, 부분집합 세트 reprep 통과·풀 밖 이름이면 `PARAM_FEATURE_MISMATCH`.
- **V-NV-2 공칭 밖 허용**(D5): Native 폴더 검증 통과·경고, Altair `_load_parameters` 기존 시험 무수정 통과.
- **V-NV-3 재현**: ④ 일괄·⑥ 생성 → 세트 정의 편집(이름·범위 변경) → 배치 재시도·⑥ 재개·추가 검증·조회(배치 상세 열·CSV·⑤ 분석)가 스냅숏 이름·범위를 씀. run `values.json` 키 = 스냅숏 변수(제외 변수 없음 → 공칭). 스냅숏 없는 이전 기록은 기존 동작.
- **V-NV-4 ⑥ Native**: `vars.add`·`exclude`·`bounds`(학습·feasible 밖 포함) → `BOUNDS_OUT_OF_RANGE` 없음, `var_notes` 코드·문구, `settings.vars`, 고정(하한 = 상한)과 제외 구분(names·결과 표), 추가 검증 범위 밖 경고. 다중 baseline에 `vars` → problem.
- **V-NV-5 ④ 일괄 Native**: `vars` 없음·정의 미편집이면 lhs·S15 7종 조합이 변경 전과 같은 seed에서 행 값 동일(out_of_range 제외), add·exclude·ranges 반영, `table` 헤더 = 유효 변수, `train_doe` = DOE 헤더(`vars` 거부·`VARS_FROM_DOE`), `out_of_range` = 학습 범위 기준, notes 경고.
- **V-NV-6 학습 범위**: 데이터셋 → DOE 합집합, DOE에 없는 변수 = [공칭, 공칭], 피처 불일치 → `None`+`TRAIN_RANGE_UNMATCHED`, `dataset_id` 없음·판별 불가·altair DOE → `TRAIN_RANGE_UNKNOWN` 1줄·`VAR_OUT_OF_TRAIN` 0건.
- **V-NV-7 ①-3 세트 DOE**: job params `vars` 기록, 생성 후 정의 편집해도 워커가 스냅숏 범위로 LHS.
- **V-NV-8 Altair 무변경(D3)**: Altair 기존 시험 무수정 통과, Altair ⑥ 범위 밖 = 기존 422 `BOUNDS_OUT_OF_RANGE`, Altair 요청의 `vars` → `NATIVE_VARS_UNSUPPORTED`, 정의 API 422, 분기 지점 밖 Altair 코드·화면 diff 없음(GE V-GE-12 방식).
- **V-NV-9 UI**: 세트 상세 사용·하한·상한 편집·저장·되돌리기·충돌 안내, 위치형 Δ 표시, 3D 치수선이 편집 값 반영, ⑥·일괄 표 추가·제외·학습 범위·모핑 가능 범위 열·경고, Altair 화면 그대로, 문구 한국어, `frontend-dist` 최신.
- **V-NV-10**: `scripts/test-all` 통과, migration 없음(`MIGRATION_HEAD` 불변).

## 13. 사용자 결정(2026-10-21 확정)

| # | 질문 | 결정 |
|---|---|---|
| Q1 → D4 | ⑥·④ 그 자리 편집을 세트 정의에도 저장하나? | 그 실행에만 적용(스냅숏 기록), 세트 정의는 ④ 상세에서만 바꿈 |
| Q2 → D5 | 공칭을 포함하지 않는 범위(예: 공칭 12.5, 14~18) 허용? | 허용 + 경고 `VAR_NOMINAL_OUTSIDE`, Native 폴더 검증에서만 `min ≤ nominal ≤ max` 해제(Altair 검증 불변) |

## 변경 메모

(구현 중 계약과 달라지면 `NV-C1~`로 기록하고 Plan 확인.)

- **NV-C0**(2026-10-21, Plan — 릴리스 배정): v0.2.4에 MCP 기능([mcp.md](mcp.md))과 함께 포함([roadmap.md](../roadmap.md)). §6.6 MCP 표기 추가. migration 없음 유지(v0.2.4의 migration은 `0020_mcp`뿐).
- **NV-C1**(2026-10-21, Plan — v0.2.4 구현 반영, 기준 `feat/r1-v024` 8206870): ① ④ 일괄 미리보기 `notes`는 `{code, message}`만(이름은 문구 안, §6.3). ② ④ `train_doe`에 `vars`·DOE 헤더의 풀 밖 이름·다중 baseline 세트의 `vars` → problem `RANGE_INVALID`(§6.3). ③ R3 정적 시험은 `ps["parameters"]` 직접 읽기 개수를 파일별로 고정(`test_native_vars_core.py` `ALLOWED`, §11). ④ 정의 저장 ③단계 실패 롤백 시 원래 없던 `vars.json`은 리비전 0 스텁으로 되씀(삭제 금지, §3.2). ⑤ 프런트 열 순서: 모핑 가능 범위(⑥·일괄은 학습 범위 포함)가 하한·상한 앞(§7.1·§7.2). ⑥ `ResultCards` "범위(학습)" 막대는 현재 세트 범위 기준 — 학습 범위 기준 전환은 후속(§7.2, roadmap). ⑦ 쉘 PROP 행(`ps.parameters` `source:"prop"`)은 ⑥·④ 일괄 표에 실행 변수로 포함(범위·제외만, §1.3·§7.2).
