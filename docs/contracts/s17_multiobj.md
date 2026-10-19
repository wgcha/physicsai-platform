# 계약: S17 성능 정의·다목적 내장 최적화 — phase3 §22

> 이 문서는 phase3.md §22와 변경 메모 D3-65입니다. s12_s13.md·s14_analysis.md·s15_sampling.md와 같은 사정으로 별도 파일로 두며, 다음 Plan 커밋에서 phase3.md 본문과 변경 메모 목록으로 옮깁니다. 절 번호·용어·원칙은 phase3.md, [s12_s13.md](s12_s13.md)(§17 지표·`run_metrics`, §18 내장 최적화, D3-60·D3-61), [s14_analysis.md](s14_analysis.md)(표시 번호: ⑤ 결과분석, ⑥ 최적화 = 내부 stage 5·URL `/stage/5`)와 같습니다.
>
> 기준선은 `claude/phase3` df8fc77(S15 0012까지)입니다. **S16(§21, migration 0013, D3-64)이 먼저 병합되어야 합니다.** 이 문서의 migration은 `0014_multiobj`(Revises = S16의 0013 revision id)입니다.

## 22. S17 성능 정의·다목적 내장 최적화 (사용자 VOC·결정 2026-10-19, D3-65)

사용자 VOC(2026-10-19): "쿠션 최적화(내장)에서 원본처럼 성능 정의하고 성능을 목적 또는 제약에 넣을 수 있게. 멀티목적 기능도."

사용자 결정:
- 멀티목적 결과는 파레토 전선을 보여 주고 사용자가 고르는 것이 기본이다.
- 가중합도 필요하다. 화면의 가중치 슬라이더로 전선 위 추천점(가중합 기준)을 강조한다.
- 고른 해는 예측 검증과 FEM 검증(S16)으로 보낼 수 있어야 한다.

1·2·3차 원칙(단일 슬롯 FIFO, 설정만, AI 루트만, `_backup`, 한국어, 필수 UI, DB에는 수치 요약만)은 그대로 유지합니다. **새 런타임 의존성은 없습니다**(numpy·scipy는 §18.2에서 이미 추가).

### 22.1 범위 / 비범위

| 범위 | 비범위(후속) |
|---|---|
| 템플릿 성능 정의: H3D(원본 형식) + CURVE(커브 대표값) | XYDATA(원본 `request`·`component`) 직접 추출 — CURVE가 curve.json 계열로 대신함 |
| 지표 `perf:<NAME>`, 값 계산 공용 함수, 정의 변경 감지 | ⑤ 결과분석·설계공간 지도의 `perf:` 지표 목록(후속, API는 `metric_value`만으로 바로 가능) |
| ⑥ 내장 최적화의 역할: 목적 1~3 · 제약 ≤/≥/범위 · 관찰 | 원본(HyperStudy) 모드 화면·검증 규칙 변경 |
| 다목적: 목적별 GP, 예측 전선, HVI·ParEGO 후보, HV 수렴 | qNEHVI·EHVI 정확 적분, 4목적 이상 |
| 결과: 파레토 해(검증 / 예측 구분), 2목적 산점도, 3목적 쌍 그림, 가중 추천, 해 선택 → 단일 예측·추가 검증 배치·FEM 검증(S16) | 평행 좌표(3목적) — 쌍 그림만 |
| 끝난 배치의 H3D 성능 다시 추출(`PB_RESP_EXTRACT`) | 다시 추출 시 하위 PREDICT의 `result.response_table`·`responses.json` 갱신(배치 표만 갱신, §22.17 R-5) |

### 22.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| P1 | **성능 = 템플릿 응답 정의(`param_sets.responses`) 확장.** 새 DB 테이블은 없습니다. 행 `{name, unit, spec}`의 spec.source에 `CURVE`를 추가합니다. ⑥ 화면에서 편집하면 기존 `PUT /param-sets/{id}/responses`로 저장합니다. | 템플릿 응답은 이미 원본 ⑤ RESPONSES의 H3D 부분과 같은 형식이고(§14.6 K5), 추출은 예측 시점(RESPONSE_EXTRACT)에 템플릿 정의로 일어납니다. 최적화마다 별도 정의를 두면 탐색·검증 배치의 하위 PREDICT가 그 정의를 추출하지 못합니다. ④ 결과 표와 ⑤ 결과분석도 같은 정의를 공유합니다. |
| P2 | **역할(목적·제약·관찰)은 최적화 설정(`surrogate_opts.settings`)에만** 둡니다. 원본의 goal·bound·value에 해당하며 템플릿에는 넣지 않습니다. | 같은 템플릿으로 목적이 다른 최적화를 여러 번 돌립니다. 원본도 goal은 최적화 실행마다 지정합니다. |
| P3 | 지표 id **`perf:<NAME>`** = 템플릿 성능 값(stat 적용)입니다. 기존 `curve:`·`resp:`·`tbl:`은 계속 받고, 화면은 `perf:`만 씁니다. | 원본의 ABSMAX는 `resp:`의 `_MIN`·`_MAX`로 나타낼 수 없습니다. 성능 이름 하나로 목적·제약·표·CSV가 일치합니다. |
| P4 | 성능 값 계산은 **순수 함수 1개**(`stage4_predict/performance.py`)를 API(미리보기·상세·runs.csv), 워커(SO_COLLECT·RESPONSE_EXTRACT의 CURVE 값·PB_RESP_EXTRACT)가 함께 씁니다. | 화면·CSV·대리모델 학습 값이 어긋나지 않게 하기 위함입니다. |
| P5 | H3D 성능은 **run 폴더의 `H3D_REQUESTS.txt` 줄과 정의를 비교**합니다. 다르면 null + 사유 `SPEC_CHANGED`입니다. 진행 중 최적화가 쓰는 성능의 정의 변경은 409입니다. | `RESPONSES.txt`에는 키(`<NAME>_MAX`)만 있어 정의를 바꾸면 옛 값이 새 정의 값처럼 보입니다. 요청 파일은 같은 폴더에 이미 있습니다(§14.6). |
| P6 | 다목적은 **`SURROGATE_OPT` 확장**입니다(같은 4 step, `settings.objectives` 길이로 분기). 새 job_type은 `PB_RESP_EXTRACT` 1개뿐입니다. | 탐색 → 적합 → 후보 → 검증 배치 연쇄, 종료 훅, 취소·이어서 실행, FINAL 캡처가 모두 같습니다. 새 job_type을 만들면 §18.7 훅과 D3-60·61 멱등 규칙을 복제해야 합니다. |
| P7 | 다목적 후보는 **예측 전선(격자 Chebyshev + DE) + HVI 활용 1개 + ParEGO(EI×PoF) k−1개**이며 numpy·scipy만 씁니다. | 기존 GP·EI·PoF·`_de`(integrality) 코드를 그대로 재사용합니다. ParEGO는 반복마다 다른 가중치를 배정해 전선 전체로 후보를 나눕니다. EHVI 정확 적분(3목적)과 NSGA-II를 직접 구현하지 않습니다. |
| P8 | 비지배 판정·HV·가중 추천은 **표준 라이브러리 전용 `pareto.py`**에 둡니다(API 프로세스는 numpy를 불러오지 않는다, §18.2). | 추가 검증(EXTRA) run이 생기면 API가 전선을 다시 계산합니다. 최대 수백 점이므로 O(n²)로 충분합니다. |
| P9 | 결과의 **검증된 해(실제 예측 체인 값)와 대리모델 예측 전선을 엄격히 구분**합니다. 추천·`best`·FINAL은 검증된 해에서만 고릅니다. | §18.7 "best는 검증된 설계만" 원칙과 같습니다. |
| P10 | 고른 해의 예측 검증은 **최적화 소유 추가 검증 배치(iters kind `EXTRA`)**로 합니다. 결과가 같은 최적화의 파레토 표로 돌아옵니다. FEM 검증은 S16 API를 호출합니다(이름은 placeholder). | 사용자가 ④에서 따로 배치를 만들면 결과가 최적화와 연결되지 않습니다. |

### 22.3 성능 정의

#### 22.3.1 형식(템플릿 응답 행 확장 — `response_defs.validate_response_defs`)

```jsonc
// H3D — 원본 ⑤ RESPONSES H3D 부분 그대로(§14.6, D3-54). 요청 줄 NAME|SUBCASE|DATATYPE|COMPONENT|LAYER
{"name":"CornerStress","unit":"MPa","spec":{"source":"H3D","subcase":1,"datatype":"CornerStress","component":"","layer":"","stat":"MAX"}}
// CURVE — 새 형식: 예측 run의 curve.json(§8.9 CURVE_PICK) 계열 1개의 대표값
{"name":"AccelPeak","unit":"g","spec":{"source":"CURVE","series":"Node 100 / X","stat":"ABSMAX"}}
// spec null — 기존 그대로(이름·단위만, 추출 정의 없음)
```

- `SOURCES = ("H3D", "CURVE")`. CURVE spec 키는 `{source, series, stat}` 전부입니다. 그 밖의 키는 `RESPONSE_INVALID`입니다.
  - `series`: 문자열 또는 null. null = 그 run의 첫 계열(`run_metrics.metric_value` 규칙). 문자열이면 1~200자, 제어문자·`|` 금지. 한글·공백·`/`·`:`는 허용합니다(계열 이름은 TCL로 넘어가지 않음).
  - `stat`: `MAX|MIN|ABSMAX`. ABSMAX = curve_stats의 `absmax`.
- 이름·단위·중복 규칙·`MAX_RESPONSES`(100)·`RESPONSE_IN_USE`는 기존과 같습니다.
- 화면 표시 이름은 "성능"입니다. API·DB 이름은 `responses` 그대로 둡니다(개명 없음).
- `PUT /param-sets/{id}/responses`의 추가 검사: **진행 중**(`SO_ACTIVE`) 내장 최적화가 `settings.performances`에 스냅샷한 이름에 대해 다음을 하면 409 `PERF_IN_USE_BY_OPT` "내장 최적화 SO-00n이 이 성능을 쓰고 있어 정의를 바꿀 수 없습니다 — 끝난 뒤 바꾸세요"입니다.
  - spec을 바꾸는 경우(정규화본 비교)
  - 행을 지우는 경우
  - 단위만 바뀌는 것은 허용합니다.

#### 22.3.2 지표 id

- `run_metrics.METRIC_RE`에 `|perf:[A-Za-z][A-Za-z0-9_]{0,63}`를 추가합니다(ASCII, fullmatch).
- 프런트·스키마의 `METRIC_PATTERN`도 같이 바꿉니다.
- `perf:<NAME>`의 `<NAME>`은 템플릿 성능 이름입니다. 대소문자는 정확히 일치해야 합니다.
- 기존 대체 응답 이름(`response_defs.NAME_RE` 밖, 실측 열 유지용)은 `perf:` 목록에 나오지 않습니다(`tbl:`과 같은 규칙).

#### 22.3.3 값 계산 — `backend/physicsai_core/stage4_predict/performance.py`(신규, 순수 + run_metrics 재사용)

```python
@dataclass(frozen=True)
class PerfDef: name: str; unit: str; source: str; spec: Mapping[str, Any]   # source "H3D"|"CURVE"
def perf_defs(ps_responses: Sequence[Mapping]) -> dict[str, PerfDef]        # spec 있는 행만, 순서 유지
def perf_value(d: PerfDef, m: RunMetrics) -> tuple[float | None, str | None]  # (값, 사유)
def perf_label(d: PerfDef) -> str      # "CornerStress (MAX)" · "AccelPeak (커브 |최대|, Node 100 / X)"
```

H3D:
1. `m.requests`(아래)에 이름이 있으면 그 줄의 (SUBCASE, DATATYPE, COMPONENT, LAYER)를 정의와 비교합니다. 비교는 공백을 제거하고 대소문자를 구분합니다. 다르면 `(None, "SPEC_CHANGED")`입니다.
2. `m.requests`가 None이면(요청 파일 없음, 옛 run) 비교 없이 진행합니다.
3. stat을 적용합니다. 규칙은 `responses.apply_stat`와 같습니다: MAX = `_MAX`, MIN = `_MIN`, ABSMAX = max(|min|, |max|).
4. 값이 없으면 사유는 `NO_VALUE`(RESPONSES는 있으나 키 없음) 또는 `NOT_EXTRACTED`(RESPONSES.txt 없음)입니다.

CURVE:
1. `m.curve`가 None이면 `(None, "NO_CURVE")`입니다.
2. 계열이 없으면 `(None, "SERIES_MISSING")`입니다.
3. stat → `max|min|absmax` 키 값입니다.

`run_metrics` 변경:
- `RunMetrics`에 `requests: dict[str, tuple[str, str, str, str]] | None` 필드를 추가합니다.
- `load_run_metrics`가 `result_dir/H3D_REQUESTS.txt`를 같은 LRU 규칙(경로·mtime·크기)으로 읽습니다(`#` 줄 무시, `responses.REQUEST_FIELDS` 순서로 분해).
- `metric_value(..., perfs: Mapping[str, PerfDef] | None = None)`: `perf:` id인데 perfs가 None이거나 이름이 없으면 None입니다.
- 사유가 필요한 호출부(SO_COLLECT·미리보기)는 `perf_value`를 직접 씁니다.

사유 문구(`REASON_TEXT`에 추가):
- `SPEC_CHANGED`: "정의가 바뀐 뒤 추출하지 않음 — 다시 추출 필요"
- `NOT_EXTRACTED`: "추출 결과 없음"
- `NO_CURVE`: "커브 없음"
- `SERIES_MISSING`: "커브 계열 없음"

#### 22.3.4 예측 시 추출 경로(RESPONSE_EXTRACT — 정의된 성능을 모두)

- `responses.h3d_request`: spec.source가 `CURVE`면 `(None, "CURVE")`를 돌려줍니다. `SILENT_REASONS`에 `CURVE`를 추가합니다(경고 없음). ①-6 `RESPONSE_EXTRACT_RUNS`·PV_EXTRACT는 그래서 CURVE 성능을 경고 없이 비워 둡니다(해석 결과에는 curve.json이 없음).
- ④ `predict.response_extract`(TCL 방식):
  1. H3D 성능을 기존대로 추출합니다.
  2. 그 뒤 CURVE 성능을 `P/curve.json`(CURVE_PICK 산출)에서 `performance.perf_value`로 계산해 `values`에 채웁니다. 값이 없으면 사유를 그대로 남기고 경고 `RESPONSE_NO_VALUE`를 냅니다.
  3. `responses_pred.csv`에 모두 씁니다. → RESPONSE_TABLE·`predict_batch_runs.responses` 복사(§14.5)는 수정하지 않습니다.
- 정의가 CURVE뿐이면 TCL을 실행하지 않습니다(H3D 요청 0개 → TCL 단계 건너뜀, `H3D_REQUESTS.txt`도 쓰지 않음).
- `{out_csv}` 옛 방식(TCL 아님)은 CURVE 값만 같은 방식으로 덧붙입니다.

#### 22.3.5 끝난 배치의 성능 다시 추출 — job `PB_RESP_EXTRACT`

목적: 재사용 배치에 나중에 정의한 H3D 성능 값을 채웁니다. CURVE 성능은 curve.json에서 바로 계산되므로 다시 추출이 필요 없습니다.

- job_type 정의:
  - stage 4, lane SLOT(HyperView 라이선스, ①-6 TD_RESP_EXTRACT와 같음)
  - 표시 "일괄 예측 성능 다시 추출", stage_label "④", `notify_success=True`
  - 알림은 기존 `JOB_SUCCEEDED`이고 새 이벤트는 없습니다.
- params `{"batch_id"}`. 서버가 `param_set_id`와 H3D 성능 이름 목록을 확정 기록합니다.

| step | kind(무게) | 처리 |
|---|---|---|
| PX_PREP | INTERNAL 5 | 대상 = 배치의 SUCCEEDED run 중 `locate_run_files`의 `result_dir`가 있고 `responses.h3d_candidates`가 정확히 1개인 run. 아닌 run은 경고 `RESP_H3D_AMBIGUOUS`/`RUN_RESULT_MISSING`으로 건너뜁니다. 대상 0개면 FAILED `INPUT_INVALID` |
| RESPONSE_EXTRACT_RUNS | LOCAL 90 | 핸들러 키 `("PB_RESP_EXTRACT","RESPONSE_EXTRACT_RUNS")`(①-6 핸들러와 별개, `response_tcl.extract_in_folder` 재사용). run마다 순서대로 다음을 합니다. ① 기존 `H3D_REQUESTS.txt`·`RESPONSES.*`·`responses_pred.csv`를 `_backup`으로 옮깁니다. ② 현재 템플릿 H3D 성능 전부로 추출합니다. ③ CURVE 값을 포함해 `responses_pred.csv`를 다시 씁니다. run 실패는 경고만 남기고 계속합니다. 진행 = 완료/대상. 취소 checkpoint는 run 사이에 둡니다. |
| PX_TABLE | INTERNAL 5 | `predict_batch_runs.responses`를 성공 run 값으로 갱신합니다(name → 값, 수치만). `result.summary {targets, extracted, failed}`를 기록합니다. |

- API: `POST /predict-batches/{bid}/extract-responses`(power) → 201 Job.
- 오류:
  - 409 `BATCH_NOT_DONE`(배치 DONE 아님)
  - 409 `BATCH_OWNED_BY_OPT`(진행 중 최적화 소유 배치. 끝난 최적화 소유면 허용)
  - 409 `FEATURE_NOT_AVAILABLE`(`features.predict_responses` false)
  - 422 `NO_H3D_PERFORMANCE`(템플릿에 H3D 성능 없음)
  - Study당 진행 중 1개(기존 `ux_jobs_study_type_active`) → 409 `JOB_ACTIVE`(기존 코드)
- 다시 추출한 값은 `run_metrics` LRU가 mtime으로 다시 읽습니다. 하위 PREDICT의 `result.response_table`은 갱신하지 않습니다(R-5).

### 22.4 최적화 문제 정의(역할)

#### 22.4.1 요청 본문(생성·미리보기 공용 — §18.6 확장)

```jsonc
{"param_set_id":"ps-1","model_id":null,
 "explore":{"kind":"new","count":20,"seed":1} | {"kind":"reuse","batch_id":"…"},
 "objectives":[{"metric":"perf:CornerStress","series":null,"sense":"min"},
               {"metric":"perf:AccelPeak","series":null,"sense":"min"}],          // 1~3개
 "constraints":[{"metric":"perf:Disp","series":null,"op":"<=","value":12.0},
                {"metric":"perf:RibForce","series":null,"op":"range","lo":30.0,"hi":60.0}],  // ≤ 5개
 "observe":[{"metric":"perf:RibStress","series":null}],                           // ≤ 10개, 값만 기록·표시
 "weights":[0.5,0.5],                                                             // 선택, 목적 수와 같은 길이, ≥0, 합>0 — FINAL 추천·알림용
 "bounds":{…},"surrogate":"gp","iterations":3,"candidates":4,"tol_rel":0.01,"seed":1,"multi_execution":4,"capture":false}
```

호환:
- 기존 단수 `objective`도 받습니다(`objectives` 생략 시 `[objective]`).
- 둘 다 오면 problems `OBJECTIVES_CONFLICT`입니다.
- `op`는 `<=|>=|range`입니다. `range`는 `lo<hi` 유한, 나머지는 `value` 유한이어야 합니다. 원본의 `==`는 받지 않습니다(화면은 "범위"로 안내, 등식은 대리모델에서 만족 확률이 0).

#### 22.4.2 정규화·검증(`services/surrogate_opts._normalize` 확장)

- 허용 지표 = 새 DOE면 `{perf:<NAME> | 템플릿 spec 있는 성능} ∪ 기존 _new_metrics`입니다. 재사용이면 기존 규칙에 `perf:<NAME>`(그 배치 성공 run 중 값 있는 run이 1개 이상)을 더합니다.
- 새 DOE에서 H3D 성능을 쓰는데 `features.predict_responses`가 false면 `PERF_EXTRACT_UNAVAILABLE`입니다.
- problems 코드(기존 + 신규):

| 코드 | 조건 |
|---|---|
| `OBJECTIVES_RANGE` | 목적 0개 또는 > `max_objectives`(3) |
| `OBJECTIVE_DUPLICATE` | 같은 (metric, series)가 목적·제약·관찰 사이에 겹침(목적끼리, 목적=제약 포함) |
| `OBJECTIVES_CONFLICT` | `objective`와 `objectives`를 함께 보냄 |
| `CONSTRAINT_INVALID` | 기존 + `range`의 lo ≥ hi·비유한, `value` 누락 |
| `OBSERVE_INVALID` | 관찰 > `max_observe`(10) 또는 허용 밖 지표 |
| `WEIGHTS_INVALID` | 길이 ≠ 목적 수, 음수·비유한, 합 0 |
| `PERF_UNDEFINED` | `perf:<NAME>`이 템플릿에 없거나 spec null |
| `PERF_MISSING_IN_BATCH` | 재사용 배치에서 그 성능 값이 있는 성공 run < 최소 점 수. problem에 `action:"extract"`·`batch_id`를 붙임(화면 "성능 다시 추출" 버튼) |
| `PERF_EXTRACT_UNAVAILABLE` | 위 |

- 재사용의 최소 점 판정(§18.6 `EXPLORE_TOO_FEW`)은 **모든 목적·제약 값이 있는** 성공 run 수로 셉니다.
- 저장 `settings` 키:
  - 기존 키 유지 + `objectives`, `observe`, `weights`(정규화 w̄, 생략 시 균등)
  - `mode`(`single`|`multi` = 목적 수 1|≥2)
  - `performances`: 참조한 `perf:` 이름의 정의 스냅샷 `{NAME: {unit, spec}}`
- 하위 호환을 위해 **`settings.objective` = `objectives[0]`도 계속 씁니다.** 기존 단일 목적 코드·`shared_legend`·알림이 그대로 동작합니다.
- 0014 이전 행(objectives 없음)은 읽는 쪽이 `[objective]`로 해석합니다.
- 미리보기 응답 추가:
  - `mode`
  - `performances:[{id:"perf:CornerStress", name, unit, source:"H3D"|"CURVE", stat, label, available:n|null, total:n|null, spec_changed:n|null}]`(available 등은 재사용일 때만)
  - `max_total_runs`·`estimate_min`은 기존 식

#### 22.4.3 자료 모델(`surrogate/dataset.py` 확장, 표준 라이브러리)

- `Problem`:
  - `objectives: list[Objective(metric, series, sense)]`, `observe: list[Metric]`, `weights: list[float]`, `performances`
  - `sense`·`sign()`은 `objectives[0]`을 따릅니다(단일 경로 무수정).
  - `signs() -> list[float]`
- `Constraint`에 `op="range"`, `lo`, `hi`를 둡니다.
  - 위반량 = max(0, lo − v) + max(0, v − hi)
  - 만족 = 위반 ≤ FEAS_TOL·max(1, |경계|)
- `Point`:
  - `objectives: list[float|None]`, `objective = objectives[0]`(호환 property), `observed: dict[str, float|None]`, `reasons: dict[str,str]`(값 없는 지표 사유)
  - `valid` = SUCCEEDED + 모든 목적·제약 값 있음. 관찰 값은 없어도 됩니다.
- `Design`에 `objectives: list[float]`를 둡니다(같은 설계 평균).
- `dataset.csv`·`runs.csv` 열:
  - 단일은 기존 그대로(`objective`)
  - 다목적은 `objective_1..objective_m`
  - 그 뒤 제약 열, 관찰 열(`obs:<label>`)
  - 사유 열 `reason`(값 없는 지표의 첫 사유)

### 22.5 다목적 알고리즘(`physicsai_core/stage5_optimize/surrogate/mo_infill.py` 신규 — numpy·scipy, `pareto.py` 신규 — 표준 라이브러리)

m = 목적 수(2·3)입니다. m = 1이면 이 절을 쓰지 않고 §18.5 그대로입니다(EI×PoF, kriging believer).

#### 22.5.1 공통 표기

- 부호 통일: 내부에서는 모든 목적을 최소화로 둡니다. f_i ← sign_i·f_i, sign = −1(max)·+1(min).
- **HV 정규화 틀**(고정, `hv_frame`): 반복 작업 r = 1의 SO_COLLECT에서 반복 0(탐색·재사용) 유효 설계로 1회 정합니다.
  - 기준 집합 = 제약 만족 유효 설계가 2개 이상이면 그것들, 아니면 유효 설계 전부
  - z*_i = min f_i, z^nad_i = max f_i, Δ_i = z^nad_i − z*_i. Δ_i ≤ 1e-12·max(1, |z*_i|)이면 Δ_i = max(1e-12, |z*_i|, 1)
  - f̂_i = (f_i − z*_i)/Δ_i
  - 기준점 R = (1 + `mo_ref_offset`)·**1** = 1.1
  - `surrogate_opts.hv_frame = {ideal:[z*], nadir:[z^nad], ref_offset:0.1, signs:[…]}`(원 단위 부호 통일 값)에 저장하고, `opt.json`에도 기록합니다.
  - 재시도·이어서 실행에서도 바꾸지 않습니다(이미 있으면 재사용).
- **작업 정규화**(ParEGO·예측 전선용, 반복마다): 지금까지 유효 설계로 같은 식(ideal·nadir 매 반복 갱신) → f̃.

#### 22.5.2 대리모델(SO_FIT)

- 목적마다 GP 1개를 둡니다(§18.5와 같은 Matérn 5/2 ARD, 집중 우도, restarts = `gp_restarts`). 제약마다 1개를 둡니다(`range`도 모델 1개).
- RBF 선택 시 모두 RBF입니다.
- GP 실패 → 그 모델만 RBF + 경고 `GP_FALLBACK_RBF`(목적 이름 포함)입니다.
- 품질 `fit`:
  - 첫 목적 요약(기존 키, 화면 호환) + `per_objective:[{metric, kind, n_train, loo_rmse, loo_nrmse, q2, pred_vs_verified_mae}]`
  - 등급 규칙(§18.5)은 목적마다 적용합니다.
- 진행 문구: "대리모델 학습(GP) · 목적 2/2 · 재시작 3/8".
- 저장: `iter_NN/surrogate.json`(목적별·제약별 모델, `FitResult` 확장 `objectives:[Scaled]`), `loo.csv`(열 `model,i,y,loo_mean,loo_std`).

#### 22.5.3 예측 전선(SO_PROPOSE 1단계)

- 가중 격자 W = Das–Dennis 단체 격자입니다.
  - m=2: H=`mo_lattice_h2`(10) → 11개, w = (j/10, 1 − j/10)
  - m=3: H=`mo_lattice_h3`(6) → 28개
  - 순서는 사전순으로 고정합니다.
- 각 w에 대해 다음을 최소화합니다.
  - 증강 Chebyshev: s_w(x) = max_i w_i·μ̃_i(x) + ρ·Σ_i w_i·μ̃_i(x), ρ = `mo_rho`(0.05), μ̃ = 작업 정규화한 GP 평균
  - 그 합에 + `PENALTY`(1e3)·Σ_c 예측 위반량_c/σ_c(제약 GP 평균, 제약 자료 표준편차로 나눔)
  - 탐색기 `_de`(기존 helper, integrality, `maxiter = mo_de_maxiter`(100), popsize = `de_popsize`, seed 식 §22.5.7)
- 풀 P = 격자 해들입니다. 같은 설계(§18.4 규칙)는 합칩니다.
- **예측 전선** = P 중 예측 만족(모든 제약 PoF ≥ 0.5)이고 μ 기준 비지배인 점입니다.
- 저장: `iter_NN/predicted_front.csv`(변수·μ_i·σ_i·PoF), DB `surrogate_opt_iters.predicted_front`(≤ 28점, `[{values, mean:[…], std:[…], pof}]`, 원 단위·원 부호).
- 진행 문구: "예측 전선 7/11".

#### 22.5.4 후보 k개 배분(SO_PROPOSE 2단계)

1. **c₁ — 전선 확장 활용**
   - 검증 전선 F = 지금까지 제약 만족 유효 설계의 비지배 집합(HV 틀 f̂)입니다.
   - 예측 전선 점 p마다 HVI(p) = HV(F ∪ {μ̂(p)}) − HV(F)(R = 1.1)를 계산하고, 최대인 점을 고릅니다.
   - 모든 HVI ≤ 1e-12면, 목적 공간(f̂)에서 F까지 최소 거리가 최대인 점을 고릅니다.
   - 기존 설계·실패 설계와 같은 설계면 다음 순위로 넘어갑니다.
2. **c₂…c_k — ParEGO**(GP일 때)
   - 가중치 배정: 순열 π_r = `default_rng(seed·1000 + r).permutation(len(W))`. 앞 반복에서 쓴 가중치(`opt.json` `used_weights`)를 건너뛰고 순서대로 k−1개를 고릅니다. 다 쓰면 used를 비우고 다시 시작합니다. 전선 양 끝과 가운데가 반복마다 고르게 배정됩니다.
   - 각 w에 대해 다음을 합니다.
     - y_w = s_w(f̃(design))(검증 유효 설계 전부, 위반 설계도 포함, 실제 값)
     - y_w에 GP를 새로 적합합니다(restarts = `mo_gp_restarts`(4)).
     - EI(y_w; min y_w(만족 설계 중, 없으면 전체)) × Π PoF_c를 DE로 최대화합니다(§18.5 `_ei` 재사용).
     - `range` PoF = Φ((hi−μ)/σ) − Φ((lo−μ)/σ)입니다.
   - 기존·이미 고른 후보와 같은 설계면 그 w의 DE 최종 집단에서 다음 순위를 고르고, 없으면 다음 가중치로 넘어갑니다.
   - RBF일 때는 ParEGO 대신 s_w(RBF 평균) 최소 + §18.5 RBF 거리 규칙(0.1 → 0.0125까지 반감)을 씁니다.
3. 후보 기록 `candidates`: 기존 키에 다음을 더합니다.
   - `role:"hvi"|"parego"|"rbf"`, `weight:[…]|null`, `predicted_objectives:[μ_i 원 단위]`, `predicted_std:[σ_i]`, `acq`
   - `predicted` = `predicted_objectives[0]`(호환)
4. 새 후보 0개 → 정지 `NO_NEW_CANDIDATE`(기존)입니다.
5. 진행 문구: "후보 2/4".

#### 22.5.5 비지배·HV(`pareto.py`, 표준 라이브러리, 최소화 기준)

```python
def dominates(a, b) -> bool             # ∀i a_i ≤ b_i 이고 ∃j a_j < b_j
def nondominated(points: Sequence[Sequence[float]]) -> list[int]   # O(n²m), 같은 벡터는 앞 인덱스만 남김, 입력 순서 유지
def hypervolume(points, ref) -> float   # m=2·3 정확, 그 밖 ValueError
def hv_improvement(front, p, ref) -> float
def normalize(f, ideal, nadir) -> list[float]
def recommend(front_obj, signs, weights) -> tuple[int, list[float]]   # §22.6, (인덱스, 점수)
```

- 기준점을 엄격히 지배하지 않는 점(어떤 i에서 f̂_i ≥ R_i)은 HV 계산에서 제외합니다.
- m=2: f̂₁ 오름차순(동점은 f̂₂ 오름차순)으로 비지배 점만 남깁니다. HV = Σ_k (R₁ − a_k)·(b_{k−1} − b_k), b₀ = R₂.
- m=3: f̂₃ 오름차순으로 정렬하고 k = 1..n에 대해 슬라이스 두께 t_k = (f̂₃의 k+1번째 또는 R₃) − f̂₃ₖ, 면적 = 앞 k개 점의 (f̂₁, f̂₂) 2D HV입니다. HV = Σ t_k·면적_k. O(n² log n).

#### 22.5.6 수렴·정지(SO_COLLECT, 다목적)

- HV_t = 반복 0..t 검증(EXTRA·FINAL 제외)의 만족 유효 설계(같은 설계 평균)의 HV(고정 틀)입니다.
- `surrogate_opt_iters`에 `hv`, `front_size`, `improvement_rel`(HV 기준)을 기록합니다. `best_value`는 null, `best_feasible` = front_size > 0입니다.
- improvement_rel_t:
  - HV_{t−1} > 0이면 (HV_t − HV_{t−1})/HV_{t−1}
  - 아니면 null(계속)
- 정지 규칙은 기존과 같습니다.
  - `CONVERGED`: improvement_rel < tol_rel(r ≥ 2, null이 아닐 때)
  - `MAX_ITER`, `NO_NEW_CANDIDATE`
  - `VERIFY_ALL_FAILED`, `TOO_FEW_POINTS`(최소 점 = max(5, d_free+2), 모든 목적·제약 값 있는 점 기준)
  - `SURROGATE_TIMEOUT`(SO_FIT+SO_PROPOSE 합 `fit_timeout_s`)
- `surrogate_opts.best`(다목적) = §22.6 추천점(settings.weights, 검증된 전선 중)입니다. 키:
  - 기존 + `objectives:{metric: 값}`, `weights:[…]`, `score`
  - `objective` = 첫 목적 값(호환)
- 만족 해가 없으면 best = 위반량 최소 설계(`feasible:false`, 기존과 같음)입니다.

#### 22.5.7 결정성(시드)

| 용도 | 시드 |
|---|---|
| GP 재시작 LHS(목적 i·제약 c) | 기존 식 + i·17 + c·31(목적·제약별 서로 다름) |
| 예측 전선 DE(가중 j) | seed·100000 + r·1000 + j |
| ParEGO 가중치 순열 | seed·1000 + r |
| ParEGO GP 재시작(가중 j) | seed·100000 + r·1000 + 500 + j |
| ParEGO DE(가중 j) | seed·100000 + r·1000 + 700 + j |

같은 자료·설정·시드면 같은 후보입니다(같은 서버·같은 numpy/scipy 기준, BLAS 부동소수 차이는 보장하지 않음 — §18.5와 같음). 시드와 `used_weights`는 `opt.json`·`surrogate.json`에 기록합니다.

#### 22.5.8 계산량 상한

- 반복 1회 GP 적합 수 = m + c + (k−1) ≤ 3 + 5 + 9 = 17입니다.
- DE 실행 수 = |W| + (k−1) ≤ 28 + 9입니다.
- 기본(m=2, c≤2, k=4, n≤60, d≤8)으로 서버 1분 이내를 목표로 합니다(E4-17-4에서 측정). 상한 초과는 `SURROGATE_TIMEOUT`입니다.

### 22.6 가중 추천점(화면 슬라이더·FINAL·알림 공용 — 계산식 고정)

입력: 검증된 파레토 해 집합 F(§22.7 front, 같은 설계 평균, 원 단위 f_{j,i}, j = 해, i = 목적), sense_i, 슬라이더 가중치 u_i ≥ 0.

1. w̄_i = u_i / Σu입니다. Σu = 0이면 w̄_i = 1/m입니다.
2. 목적마다 F 안에서 lo_i = min_j f_{j,i}, hi_i = max_j f_{j,i}입니다.
   - min이면 g_{j,i} = (f_{j,i} − lo_i)/(hi_i − lo_i)
   - max이면 g_{j,i} = (hi_i − f_{j,i})/(hi_i − lo_i)
   - hi_i − lo_i ≤ 1e-12·max(1, |lo_i|)이면 g_{j,i} = 0
   - 0 = 그 목적에서 전선 내 최선, 1 = 최악
3. 점수 S_j = Σ_i w̄_i·g_{j,i}입니다. **추천 = argmin S_j**입니다.
4. 동점(|ΔS| ≤ 1e-12)은 g_{j,1} 작은 쪽 → (iter_no, doe_no) 작은 쪽 순으로 정합니다.
5. 예측 전선 점(미검증)에도 같은 lo·hi(검증 전선 기준)로 S를 계산해 표시만 합니다(0~1 밖일 수 있음). **추천 대상은 아닙니다.**
6. 툴팁 문구: "가중합 점수 = Σ 가중치 × (전선 안에서 0=최선·1=최악으로 맞춘 목적 값). 가중합은 전선의 오목한 부분의 해를 고를 수 없어 파레토 표에서 직접 고르는 것이 기본입니다."

골든(목적 2개 모두 min, F = A(1,9) · B(3,4) · C(6,2) · D(10,1); g: A(0, 1) · B(0.2222, 0.375) · C(0.5556, 0.125) · D(1, 0)):

| u | S_A | S_B | S_C | S_D | 추천 |
|---|---|---|---|---|---|
| (50,50) | 0.5 | 0.2986 | 0.3403 | 0.5 | B |
| (80,20) | 0.2 | 0.2528 | 0.4694 | 0.8 | A |
| (20,80) | 0.8 | 0.3444 | 0.2111 | 0.2 | D |
| (0,0) | = (50,50) | | | | B |
| f₂를 max로 바꾸고 (50,50) | 0.0 | 0.7361 | 0.7153 | 0.5 | A |

FINAL·`best`는 `settings.weights`(생성 시 값, 기본 균등)를 씁니다. 화면 슬라이더는 저장하지 않습니다(localStorage만, §22.12).

### 22.7 결과·추가 검증·FINAL·S16 연동

- **검증된 파레토 해(front)**:
  - 대상 = 해당 최적화의 모든 검증 run(EXPLORE·REUSE·VERIFY·**EXTRA**, FINAL 제외) 중 만족 유효 설계(같은 설계 평균, 키 = 그 설계의 첫 run `"<iter_no>:<doe_no>"`)의 비지배 집합
  - API가 상세 요청 때 `pareto.py`로 계산합니다(EXTRA run이 늘면 바로 반영). front HV는 `hv_frame`으로 계산합니다.
- **예측 전선** = 마지막 반복의 `predicted_front`입니다. "대리모델 예측(미검증)"으로 늘 구분해 표시합니다.
- **추가 검증(EXTRA)** `POST /surrogate-opts/{oid}/verify`(power, 등록자 또는 관리자):
  - 본문 `{"points":[{"values":{"THK_1":2.4,…}}], "capture":false}`, 1 ≤ 점 수 ≤ `max_extra_points`(10)
  - 조건: opt `DONE`만(아니면 409 `SURROGATE_OPT_NOT_DONE`), 진행 중 EXTRA 배치가 없어야 함(409 `SURROGATE_OPT_EXTRA_ACTIVE`), 값은 opt bounds 안(422 `SURROGATE_OPT_INVALID` + `BOUNDS_OUT_OF_RANGE`)
  - 고정 변수는 고정값을 쓰고, 정수는 `batch_matrix` 반영 규칙을 따릅니다.
  - 생성: 최적화 소유 PREDICT_BATCH(source table, `capture.enabled = capture`, params `surrogate_opt:{id, opt_no, iter_no, extra:true}`) + iters(`iter_no = max+1`, kind `EXTRA`)를 한 트랜잭션(Study FOR UPDATE)에서 만듭니다. opt 상태는 DONE 그대로입니다.
  - 종료 훅 `on_batch_done`: kind EXTRA면 반복 작업을 넣지 않고 False를 돌려줍니다 → 기존 `PREDICT_BATCH_DONE` 알림이 그대로 갑니다.
  - EXTRA 배치는 `BATCH_OWNED_BY_OPT` 가드 대상이 아닙니다(opt가 끝났으므로 ④ 배치 취소·실패만 다시가 정상 동작).
  - 이미 검증된 해를 다시 보내는 것도 허용합니다(예: 컨투어 캡처 목적, capture=true).
  - → 201 `{"batch_id","batch_label","job_id","iter_no"}`
- **FINAL(D3-61) 다목적**:
  - 2행 = doe 1 기준안 + doe 2 **가중 추천점**(settings.weights)
  - 같은 범례 규칙(D3-61 보강)은 `objectives[0]`에 적용합니다. `perf:<NAME>`도 H3D이고 datatype = 컨투어 field이며 stat MAX·ABSMAX면 같은 범례 대상입니다(`shared_legend` 확장).
  - 다른 해의 컨투어는 추가 검증(capture=true)으로 받습니다.
- **알림**(다목적): "내장 최적화 SO-002 완료 — 파레토 해 6개 · HV 0.712 · 추천 CornerStress 132.4 / AccelPeak 41.0 (반복 3 · 검증 12 run)". 단일 목적은 기존 문구 그대로입니다.
- **S16 FEM 검증 연동**(placeholder — S16 계약 §21 확정 이름으로 교체, Plan이 D3-65 보강으로 고정):
  - 화면 버튼 `FEM 검증`: 선택한 **검증된** 해 1개의 `job_id`(하위 PREDICT, `input_mode:"prepared"`, `batch_run` 있음)로 S16 생성 API `POST /studies/{id}/fem-verifications`를 `source:{kind:"opt_design", opt_id, pick:"run", iter_no, doe_no}`로 부릅니다(S16 §21.3.2 — batch run의 prepared PREDICT도 출처로 받음).
  - 사용 가능 여부는 `/status.features.fem_verify`(S16 §21 확정)이고, false면 비활성 + 툴팁(사유)입니다.
  - S16과 맞출 것:
    - ① S16 입력이 batch run의 prepared PREDICT(mesh_only 쿠션 예측)를 받는지. 받지 않으면 "단일 예측으로 열기 → 그 결과에서 FEM 검증" 2단계로 바꿉니다.
    - ② 응답이 Job인지
    - ③ 권한(power)
  - 예측 전선 점(미검증)은 FEM 검증 대상이 아닙니다(버튼 비활성, "먼저 예측 검증").

### 22.8 DB — migration `0014_multiobj`(Revises S16 `0013_*`, `MIGRATION_HEAD` 갱신)

- `surrogate_opt_iters`:
  - `ck_surrogate_opt_iters_kind`에 `'EXTRA'`를 추가합니다.
  - 열 `hv FLOAT NULL`, `front_size INTEGER NULL`, `predicted_front JSONB NULL`(수치만, ≤ 28점)을 추가합니다.
- `surrogate_opts`: 열 `hv_frame JSONB NULL`을 추가합니다.
- 기존 행은 변경하지 않습니다(단일 목적, NULL).
- downgrade: EXTRA 행이 있으면 실패 메시지를 냅니다(데이터 보존). 없으면 열·CHECK를 되돌립니다.
- job_type `PB_RESP_EXTRACT`는 코드만 추가합니다(jobs에 job_type CHECK 없음 — 0010 확인). `ux_jobs_study_type_active`가 그대로 Study당 1개를 보장합니다.
- 새 알림 이벤트는 없습니다.

### 22.9 작업·step 변경 요약

| job | 변경 |
|---|---|
| `SURROGATE_OPT` | step 키·무게 불변. SO_COLLECT: 목적·제약·관찰 값을 `perf_value` 포함 계산, r=1에서 `hv_frame` 확정, 다목적 HV 기록·정지. SO_FIT: 목적별 모델. SO_PROPOSE: m≥2면 §22.5.3·§22.5.4. SO_NEXT: 다목적 best = 추천점, 알림 문구, FINAL 2행 = 기준안 + 추천점 |
| `PREDICT`(④) | RESPONSE_EXTRACT에서 CURVE 성능 값 채움(§22.3.4). step 불변 |
| `PB_RESP_EXTRACT`(신규) | §22.3.5 |
| `TD_RESP_EXTRACT`·`PREDICT_VERIFY` | CURVE 성능은 조용히 건너뜀(`SILENT_REASONS`) |

### 22.10 API(`backend/openapi.json` 갱신)

```jsonc
// 미리보기·생성: §22.4.1 본문. 미리보기 응답 + {"mode":"multi","performances":[…]}
// 상세 GET /surrogate-opts/{oid} — 기존 키 유지 + 아래
{"mode":"multi",
 "objectives":[{"metric":"perf:CornerStress","series":null,"sense":"min","label":"CornerStress (MAX)","unit":"MPa"},
               {"metric":"perf:AccelPeak","series":null,"sense":"min","label":"AccelPeak (커브 |최대|, Node 100 / X)","unit":"g"}],
 "constraints_def":[{"metric":"perf:Disp","op":"<=","value":12.0,"lo":null,"hi":null,"label":"…","unit":"mm"}],
 "observe":[{"metric":"perf:RibStress","label":"…","unit":"MPa"}],
 "weights":[0.5,0.5],
 "pareto":{"hv":0.712,"frame":{"ideal":[120.1,35.2],"nadir":[171.0,58.9],"ref_offset":0.1},
           "front":[{"key":"2:3","iter_no":2,"doe_no":3,"run_key":"run__00003","job_id":"…","batch_label":"B-015",
                     "values":{…},"objectives":[132.4,41.0],"constraints":{"perf:Disp":10.2},"observed":{"perf:RibStress":88.0}}],
           "recommended_key":"2:3",                       // settings.weights 기준(§22.6)
           "predicted_iter":3,
           "predicted":[{"values":{…},"mean":[128.0,43.5],"std":[3.1,1.2],"pof":0.93}]},
 "hv_history":[{"iter_no":0,"hv":0.41,"front_size":3,"improvement_rel":null},{"iter_no":1,"hv":0.63,"front_size":5,"improvement_rel":0.537}],
 "runs":[{…기존, "objective":132.4, "objectives":[132.4,41.0], "observed":{…}, "reason":null, "on_front":true, "kind":"VERIFY"|"EXTRA"|…}],
 "can_verify_more":true}
// 단일 목적: mode "single", pareto·hv_history null, 나머지 기존과 같음(objectives 1개, constraints_def·observe 채움)
// GET /surrogate-opts/{oid}/runs.csv — §22.4.3 열
// POST /surrogate-opts/{oid}/verify — §22.7
// POST /predict-batches/{bid}/extract-responses — §22.3.5
// PUT /param-sets/{id}/responses — CURVE spec·409 PERF_IN_USE_BY_OPT(§22.3.1)
```

- 이미 쓰던 상세 키 `constraints`(run별 값 표시용)와 이름이 겹치지 않도록 정의는 `constraints_def`로 둡니다.
- `iterations[].fit.per_objective`, `iterations[].hv`·`front_size`, `iterations[].candidates[].{role, weight, predicted_objectives, predicted_std}`를 추가합니다.
- `/status.surrogate_opt`에 `max_objectives`, `max_observe`, `max_extra_points`를 추가합니다.
- 권한은 §18.6과 같습니다(조회 member, 생성·추가 검증·다시 추출 power, 취소는 등록자 또는 관리자).
- 응답 크기: runs ≤ 탐색 200 + 반복 10×10 + EXTRA. front는 같은 설계 평균이라 runs보다 작습니다.

### 22.11 설정(`config/platform.example.yaml` `surrogate_opt` 절 추가, 기본값은 스키마 한 곳)

`max_objectives: 3, max_observe: 10, max_extra_points: 10, mo_lattice_h2: 10, mo_lattice_h3: 6, mo_de_maxiter: 100, mo_rho: 0.05, mo_ref_offset: 0.1, mo_gp_restarts: 4`

검증 규칙:
- `max_objectives`는 1~3입니다.
- lattice H는 2~20입니다.
- ρ는 0~1입니다.
- ref_offset은 0.01~1입니다.

`deploy/setup_config.py`는 변경하지 않습니다.

### 22.12 화면(⑥ 최적화 — 내장 모드, 필수 UI만, D3-55·56 톤)

**새 최적화 카드** — §18.10 ③ 목적·④ 제약을 **"성능" 표 1개**로 바꿉니다. 다른 단계(템플릿·모델, 탐색, 변수 범위, 설정, 미리보기)는 그대로입니다.

- 열: 이름 · 출처(`H3D`·`커브`) · Subcase · DataType(커브면 계열) · Component · Layer · Stat · 단위 · **역할** · **값** · (재사용일 때) `값 있는 run n/N`
  - 원본 ⑥ 원본 모드 `ResponseTable` 열 순서를 따르며 Goal·Bound·Value 자리에 역할·값이 옵니다.
- 역할 드롭다운: `사용 안 함`(기본) · `목적 최소` · `목적 최대` · `제약 ≤` · `제약 ≥` · `제약 범위` · `관찰`
  - 값 칸은 제약 ≤·≥면 숫자 1개, 범위면 하한~상한 2개입니다.
- 정의 편집:
  - 행 추가(콤보는 기존 `response-candidates`: H3D datatype·component·layer, 커브 계열은 `xydata`·최근 예측 계열, 없으면 직접 입력)
  - 행 삭제, `성능 정의 저장(템플릿)` 버튼(power, `PUT /param-sets/{id}/responses`) — 저장 전에는 역할을 고를 수 없습니다(회색 "저장된 성능만 역할 지정").
  - `PERF_IN_USE_BY_OPT`는 문구를 그대로 표시합니다.
- 재사용 배치에서 `PERF_MISSING_IN_BATCH`(action extract)면 그 행에 회색 사유 + `성능 다시 추출` 버튼 → `extract-responses` → 작업 진행을 기존 대기열 표시로 보여 줍니다.
- 목적 2개 이상이면 표 아래 **가중치**(목적마다 0~100 슬라이더, 기본 균등) + 회색 한 줄 "다목적: 파레토 전선을 찾고, 가중치는 마무리 캡처할 추천점에만 씁니다(결과 화면에서 바꿀 수 있음)"을 둡니다.
- 미리보기 한 줄에 `목적 2개(다목적)`를 덧붙입니다.
- 문구 규칙: 역할 오류는 problems 코드 문구를 그대로 씁니다. 목적 4개 이상은 드롭다운에서 막습니다.

**결과**(라우트 불변 `/stage/5/surrogate/:optId`):
- 단일 목적: 기존 화면 그대로입니다. 목적 라벨은 성능 라벨, 관찰 열이 추가됩니다.
- 다목적: 위에서부터 다음 순서입니다.
  1. 상태 칸(기존)
  2. **파레토 카드**
     - 2목적: 산점도(자체 SVG). x = 목적 1, y = 목적 2, 원 단위, 축 라벨에 "↓ 좋음"/"↑ 좋음". 점 표시:
       - 검증 run 전부: 지배된 점은 회색 불투명 0.3, 제약 위반은 회색 ×
       - **검증 파레토 해**: accent 채움 + 계단선
       - **예측 전선**: 속 빈 점 + 점선, 토글 "대리모델 예측 전선"(기본 켬)
       - 기준안(FINAL baseline 있으면): ◇
       - **가중 추천점**: 굵은 링
       - 클릭 = 선택(표와 공유)
     - 3목적: **쌍 그림 3개**(f₁–f₂, f₁–f₃, f₂–f₃, 같은 표시 규칙, 선택 공유). 평행 좌표는 없습니다.
  3. **가중치 카드**
     - 목적마다 슬라이더(0~100, step 5, 초기값 = settings.weights×100)와 정규화 % 표시
     - "가중합 추천: B-015 DOE #3 · 점수 0.21" + 계산식 툴팁(§22.6 문구)
     - 슬라이더를 바꾸면 추천 링이 즉시 이동합니다(서버 왕복 없음).
     - localStorage `physicsai.stage6.weights.<optId>`(try/catch, 길이 다르면 무시), `기본값으로` 버튼
  4. **파레토 표**
     - 행 = 검증 파레토 해(+ 토글 켜면 예측 전선 행, 회색 기울임 "예측(미검증)")
     - 열: 선택 체크 · 출처 · 반복·배치·DOE # · 변수 · 목적들 · 제약 · 관찰 · 가중 점수 · 순위
     - 정렬은 점수 오름차순이 기본이고, 추천 행을 강조합니다.
     - 선택 동작 버튼:
       - `단일 예측으로 열기`: 검증 해 1개(기존 동작)
       - `선택 해 예측 검증`: 1~10개, 검증·예측 행 모두, 체크 "컨투어 캡처 포함" → `verify`. 결과 배치 링크와 "검증이 끝나면 이 표에 반영됩니다"를 표시하고, 진행 중이면 버튼을 비활성화합니다.
       - `FEM 검증`: 검증 해 1개, §22.7 placeholder
     - `CSV 받기`(runs.csv)
  5. **HV 그래프**(자체 SVG): x = 반복, y = HV, 점 옆 개선율 %, 수렴 기준 문구. 기존 수렴 그래프를 대신합니다.
  6. **대리모델 품질 표**(목적별 행)
  7. **최적안 — 기준안 대비 / 결과 요약 / 컨투어 비교**: D3-61 카드는 대상만 "추천점"으로 바꿔 그대로 씁니다.
  8. **검증 run 표**: 목적·관찰 열 추가, EXTRA는 반복 칸 "추가"
  9. 파일 위치

색은 D3-55 변수만 씁니다. accent = 파레토 해, `--color-text-muted` = 지배된 점입니다. 새 라이브러리는 없습니다.

### 22.13 시험(V3-S17-*)

| ID | 기준 |
|---|---|
| V3-S17-1 | 0014 up/down: iters kind EXTRA·새 열, opts `hv_frame`, 기존 행 보존, `MIGRATION_HEAD`, EXTRA 행 있을 때 downgrade 실패 |
| V3-S17-2 | 성능 정의 검증: CURVE spec(series null·문자열·`|`·제어문자·200자, stat), H3D 회귀, `PERF_IN_USE_BY_OPT`(spec 변경·삭제 409, 단위만 200, 끝난 opt면 200) |
| V3-S17-3 | `performance.perf_value` 골든: H3D MAX·MIN·ABSMAX, `SPEC_CHANGED`(요청 줄 다름)·요청 파일 없음 → 비교 생략, `NOT_EXTRACTED`·`NO_VALUE`, CURVE max·min·absmax·series null = 첫 계열·`SERIES_MISSING`·`NO_CURVE`. `METRIC_RE`의 `perf:`(fullmatch·비ASCII 거부), `run_metrics` LRU에 `H3D_REQUESTS.txt` 포함(mtime 변경 시 다시 읽음) |
| V3-S17-4 | 추출 경로: ④ RESPONSE_EXTRACT가 H3D(TCL 가짜 hw `minmax`)+CURVE 값을 `responses_pred.csv`에 모두 씀, CURVE만이면 TCL 미실행, ①-6·PV는 CURVE 조용히 건너뜀(경고 없음). `PB_RESP_EXTRACT` e2e(가짜 도구): `_backup` 이동·새 RESPONSES·`predict_batch_runs.responses` 갱신·h3d 2개 run 건너뜀·API 409 4종·422 |
| V3-S17-5 | `pareto.py` 골든(1e-12): 비지배(같은 벡터 앞 인덱스, 입력 순서 유지). HV 2D {(0.2,0.8),(0.5,0.5),(0.8,0.2)} R=(1,1) → **0.37**. HV 3D {(0.2,0.6,0.6),(0.6,0.2,0.6),(0.6,0.6,0.2)} R=(1,1,1) → **0.256**. 기준점 밖·지배된 점 무시, 무작위 5점 3D HV = 포함–배제 직접 계산, HVI = 차 |
| V3-S17-6 | 해석 전선 HV 근사: ZDT1 참 전선 101점 R=1.1 → 0.87667 ± 0.01. DTLZ2(3목적) 구면 전선 균일 231점 R=1.1 → 1.331 − π/6 = 0.80740 ± 0.02 |
| V3-S17-7 | 다목적 수학(numpy·scipy 있는 시험 환경, 실제 작업 없이 해석 함수를 평가기로 쓰는 루프 helper `mo_infill.run_offline` — 시험 전용): ZDT1(d=3, 탐색 12 + 4×4), ZDT2(비볼록, d=3), DTLZ2(m=3, d=4, 탐색 16 + 4×4). 검증 HV/참 HV ≥ **ZDT1 0.80 · ZDT2 0.70 · DTLZ2 0.70**(시드 1), 같은 예산의 LHS만 쓴 HV보다 큼(시드 1~5 중 4개 이상). 기준값은 구현 때 측정해 미달이면 Plan에 변경 메모로 보고합니다(기준을 낮추지 않고 원인부터 확인) |
| V3-S17-8 | 다목적 세부: 격자 크기 11·28·사전순, 증강 Chebyshev 값 골든, c₁ HVI 선택·HVI 0이면 거리 규칙, ParEGO 가중치 배정(반복 간 겹치지 않음·소진 후 재시작), `range` PoF·위반량, 정수 변수 후보 정수, 고정 변수, sense max 혼합, 중복·실패 설계 재제안 없음, RBF 경로, 같은 시드 같은 후보·다른 시드 다른 후보, GP 실패 → 그 목적만 RBF 경고 |
| V3-S17-9 | SO_COLLECT 다목적: `hv_frame` r=1 확정·재시도 시 불변, iters hv·front_size·improvement_rel(HV_{t−1}=0 → null), 정지 4종·`TOO_FEW_POINTS`(목적·제약 모두 있는 점 기준), 관찰 값 없음은 유효성에 영향 없음, dataset.csv·runs.csv 열(단일 = 기존 그대로) |
| V3-S17-10 | §22.6 가중 추천 골든 표 5행(Python `pareto.recommend`와 TS `pareto.ts`가 같은 표). 동점 규칙, 예측 점 점수(범위 밖 허용)·추천 제외 |
| V3-S17-11 | API: 본문 호환(단수 `objective`만 → 기존 동작·저장 settings에 objectives 1개 + objective), problems 신규 코드 전부, `PERF_MISSING_IN_BATCH` action, 상세 `pareto`·`hv_history`·runs 확장, 단일 목적 응답 회귀(V3-S13-6 무수정 통과), `verify`(DONE만·EXTRA 진행 중 409·범위·10개 상한·한 트랜잭션·종료 훅에서 반복 작업 없음 + `PREDICT_BATCH_DONE` 1건·EXTRA run이 front에 반영), EXTRA 배치 cancel/retry-failed 허용, FINAL 2행 = 기준안 + 추천점, 다목적 알림 문구, openapi·타입 재생성 |
| V3-S17-12 | 화면: 성능 표(정의 편집·저장·저장 전 역할 비활성·역할별 값 칸·재사용 n/N·다시 추출 버튼), 가중치 입력(다목적만), 요청 본문. 결과: 2목적 산점도(지배 흐림·위반 ×·예측 속 빈 점 토글·추천 링·클릭 선택↔표), 3목적 쌍 그림 3개, 슬라이더 → 추천 이동·localStorage·기본값, 파레토 표 정렬·예측 행 표시·버튼 조건(FEM은 검증 1개 + feature), verify 요청 본문, HV 그래프, 품질 표 목적별, 단일 목적 화면 회귀(V3-S13-9 무수정), 목 라우트 |
| V3-S17-13 | e2e(가짜 도구, mesh_only): 2목적(perf H3D + perf CURVE) 탐색 6 → 2×2 → FINAL → DONE, front ≥ 1, 추가 검증 2점 → front 갱신. 가짜 hw `minmax`·가짜 curve 값은 흐름만 확인(품질은 V3-S17-7) |

### 22.14 서버 확인(E4-17, 사용자)

1. ⑥ 내장 모드에서 쿠션 템플릿에 성능 2개를 정의합니다: H3D `CornerStress` MAX, 커브 `AccelPeak` ABSMAX. 저장 → ④ 단일 예측 1회 → 결과 표에 두 값이 나오는지, 커브 값이 HyperGraph 최대와 같은지 확인합니다.
2. 기존 완료 배치(정의 전 예측)를 재사용 → `PERF_MISSING_IN_BATCH` → `성능 다시 추출` → 값 채워짐 확인. 하위 run 폴더 `_backup`에 옛 RESPONSES가 남는지 확인합니다.
3. 2목적(CornerStress 최소 · AccelPeak 최소) + 제약 1개(범위), 새 DOE 12 + 3×4를 실행합니다. 파레토 산점도·예측 전선·HV 그래프, 슬라이더 3가지(50/50·80/20·20/80)에서 추천 이동, FINAL 컨투어(기준안 vs 추천점)를 확인하고 총 소요를 기록합니다.
4. 반복당 SO_FIT+SO_PROPOSE 시간을 기록합니다(목표 < 60 s, §22.5.8). 3목적 1회도 실행합니다(관찰 1개 포함).
5. 파레토 표에서 예측 전선 점 2개 → `선택 해 예측 검증`(캡처 포함) → 결과가 표에 반영되고 컨투어가 받아지는지 확인합니다.
6. 검증 해 1개 → `FEM 검증`(S16 구성 시) → S16 작업이 생성되는지 확인합니다.
7. 진행 중 최적화가 쓰는 성능의 정의 변경 시도 → 409 문구를 확인합니다.

### 22.15 파일 소유(AGENTS.md 역할 표 — Impl-Backend / Impl-Frontend, 겹침 없음)

| 에이전트 | 파일 |
|---|---|
| **Impl-Backend** | 새: `migrations/versions/0014_multiobj.py`, `backend/physicsai_core/stage4_predict/performance.py`, `backend/physicsai_core/stage5_optimize/surrogate/{pareto.py, mo_infill.py}`, `backend/physicsai_api/services/surrogate_opt_problem.py`(`_normalize`를 여기로 분리 — `surrogate_opts.py` 484줄, 300줄 규칙), `backend/physicsai_api/services/surrogate_opt_pareto.py`(상세 front·추천·hv_history), `worker/physicsai_worker/steps/stage4_predict/batch_resp.py`(PB_RESP_EXTRACT), 시험 `backend/tests/test_s17_*.py`·`worker/tests/test_s17_*.py`·`backend/tests/data/s17_*.json`(골든). 수정: `backend/physicsai_core/stage4_predict/{response_defs.py, responses.py, run_metrics.py}`, `backend/physicsai_core/stage5_optimize/surrogate/{dataset.py, infill.py}`, `backend/physicsai_core/db/{__init__.py(MIGRATION_HEAD), tables/surrogate_opt.py, repositories/surrogate_opts.py, repositories/job_end.py}`, `backend/physicsai_core/job_types.py`(PB_RESP_EXTRACT·step 라벨 PX_PREP·PX_TABLE), `backend/physicsai_core/features.py`, `config/{schema_stages.py, validate.py}`, `config/platform.example.yaml`, `backend/physicsai_api/{services/surrogate_opts.py, schemas/surrogate_opt.py, routers/surrogate_opts.py, services/predict_batches.py, routers/predict_batches.py, schemas/predict_batch.py, services/param_sets.py 또는 응답 저장 서비스(PERF_IN_USE_BY_OPT), services/system.py, schemas/shell.py, schemas/jobs.py(JobType)}`, `worker/physicsai_worker/steps/{__init__.py, stage4_predict/predict.py, stage5_optimize/surrogate.py}`, `backend/openapi.json`, `backend/tests/data/operation_ids.txt`·`backend/tests/common/test_openapi.py`(라우트 목록), 기존 시험의 migration head·기능 목록, `docs/manual/admin.md`는 Plan 소유(아래) |
| **Impl-Frontend** | 새: `frontend/src/stages/stage5/surrogate/{PerfTable.tsx, perfRules.ts, WeightSliders.tsx, ParetoCard.tsx, ParetoPlot.tsx, PairPlots.tsx, ParetoTable.tsx, HvChart.tsx, pareto.ts}`, `frontend/src/__tests__/s17*.test.tsx`·`__tests__/fixtures/s17Recommend.json`(§22.6 표). 수정: `frontend/src/stages/stage5/surrogate/{SurrogateSetup.tsx, SurrogateResult.tsx, soRules.ts, ResultCards.tsx}`, `frontend/src/stages/stage4/ResponseDefs.tsx`(CURVE 출처 — ④ 템플릿 응답 절도 같은 형식), `frontend/src/api/{surrogateOpt.ts, endpoints.ts(extract-responses 1개), types.ts(JobType PB_RESP_EXTRACT)}`, `frontend/src/api/generated/schema.d.ts`(재생성), `frontend/src/lib/format.ts`(job 라벨), `frontend/src/mock/{surrogateOpt.ts, predictBatch.ts, jobs.ts, steps.ts, catalog.ts}`, `frontend/src/styles/surrogateOpt.css`, `frontend-dist/**`(빌드본) |
| **Plan** | 이 문서, phase3.md 이동, `docs/manual/admin.md`(설정·PB_RESP_EXTRACT·오류 코드) |

- 인터페이스 고정점:
  - §22.3.3 `performance.py` 서명
  - §22.5.5 `pareto.py` 서명
  - §22.10 상세 응답 모양
- Frontend는 목으로 먼저 시작하고, Backend의 openapi 커밋 후 `npm run gen:api`로 맞춥니다.
- `pareto.ts`는 `pareto.py`와 같은 골든 표(V3-S17-10)를 각자 픽스처로 커밋합니다. 값은 이 문서 §22.6이 기준입니다.

### 22.16 순서

1. **B0**: Impl-Backend — 0014 + `performance.py` + `pareto.py` + run_metrics·response_defs·responses + 시험 V3-S17-1~3·5·6 (1커밋)
2. **B1**:
   - Backend: 추출 경로·PB_RESP_EXTRACT(V3-S17-4)
   - Backend: 다목적 알고리즘·SO_* 분기(V3-S17-7~9)
   - Backend: API·verify·openapi(V3-S17-11)
3. **F1**(B0 뒤, 목 기반 병렬): 성능 표·가중치 입력·결과 카드(V3-S17-10·12) → openapi 병합 후 재생성
4. **E**: e2e V3-S17-13 → Verifier → 서버 확인 E4-17

S16 연동 버튼은 S16 API가 확정되면 Plan이 placeholder 이름을 교체(D3-65 보강)하고 Frontend가 반영합니다. 그 전에는 feature false로 비활성입니다.

### 22.17 리스크

- **R-1 대리모델 위의 대리모델 + 다목적 예산**: 목적별 GP는 n이 작으면(< 4·d) 전선 품질이 낮습니다. 기본 탐색 수 max(10, 4·d_free)를 유지하고, 다목적이면 미리보기에 회색 "다목적은 탐색 run을 늘리면 전선이 안정됩니다"를 표시합니다.
- **R-2 HV 틀 고정**: 탐색 범위 밖으로 크게 개선된 해는 HV 기여가 정규화상 커져 개선율이 과장될 수 있습니다(수렴이 늦어질 뿐 잘못된 정지는 아님). 기준점 밖 점은 HV에 기여하지 않으므로, 탐색 자료가 극단적으로 나쁘면 HV 초기값이 0일 수 있습니다(→ improvement null, 계속 진행).
- **R-3 가중합의 한계**: 오목한 전선 부분은 어떤 가중치로도 추천되지 않습니다. 툴팁과 "파레토 표에서 직접 고르기 기본"으로 안내합니다.
- **R-4 템플릿 공유**: ⑥에서 성능을 추가하면 이후 ④ 예측마다 HyperView 추출 항목이 늘어 소요가 늘어납니다. 진행 중 최적화의 성능 정의 변경은 409로 막습니다.
- **R-5 다시 추출 범위**: `PB_RESP_EXTRACT`는 배치 표(`predict_batch_runs.responses`)와 run 폴더 파일만 갱신하고, 하위 PREDICT의 `result.response_table`은 예측 당시 값으로 남습니다(④ 단일 결과 화면과 배치 표가 다를 수 있음). 후속 결정 대상입니다(미결 3).
- **R-6 계산 시간**: 3목적 + 제약 5 + 후보 10이면 반복당 GP 17개·DE 37회입니다. `fit_timeout_s`(600) 안에 들지 못하면 `SURROGATE_TIMEOUT`이고, 설정(`mo_de_maxiter`·`mo_gp_restarts`)으로 조정합니다.
- **R-7 S16 의존**: migration 0014는 S16의 0013 위에 놓입니다. S16 병합이 늦어지면 0014의 `down_revision`을 0012로 바꾸고 S16이 다시 순서를 맞춰야 하므로, **병합 순서를 S16 → S17로 고정**합니다.
- **R-8 3D HV 정확도·성능**: O(n² log n), n(전선) ≤ 수백이면 ms 수준입니다. API 상세 요청마다 다시 계산합니다(5초 폴링 × 전선 계산). 진행 중에만 폴링하므로 허용합니다.

### 22.18 미결(사용자 확인 대상)

1. 3목적 표시: 쌍 그림만 둘지, 평행 좌표(S12 컴포넌트 재사용)도 추가할지 — 기본은 쌍 그림만입니다.
2. 추가 검증(EXTRA)을 최적화가 **실패·취소**된 경우에도 허용할지 — 기본은 DONE만입니다.
3. `PB_RESP_EXTRACT` 때 하위 PREDICT 결과 표(`result.response_table`)도 갱신할지(R-5) — 기본은 갱신하지 않습니다.
4. 다목적 수렴을 "HV 개선 < tol 1회"(기본, 단일 목적과 같음)로 둘지 "연속 2회"로 둘지.
5. ⑤ 결과분석·설계공간 지도의 지표 목록에 `perf:`를 넣는 후속을 언제 할지.
6. FEM 검증 입력 단위(S16과 맞춤 — §22.7 ①~③).

## 변경 메모(이 문서분 — phase3.md 변경 메모 목록으로 옮김)

- **D3-65 (사용자 VOC·결정 2026-10-19, S17 성능 정의·다목적 내장 최적화 — Plan)**: §22.
  - ① **성능 = 템플릿 응답 정의 확장**(새 테이블 없음): H3D(원본 NAME|SUBCASE|DATATYPE|COMPONENT|LAYER + stat) + 새 `source:"CURVE"`(계열·stat). ⑥에서 편집하면 `PUT /param-sets/{id}/responses`로 저장합니다. 진행 중 최적화가 쓰는 성능의 정의 변경·삭제는 409 `PERF_IN_USE_BY_OPT`입니다.
  - ② 지표 `perf:<NAME>`(stat 적용 값)과 공용 순수 함수 `stage4_predict/performance.py`를 둡니다. H3D는 run의 `H3D_REQUESTS.txt` 줄과 비교해 다르면 `SPEC_CHANGED`(null)입니다. `RunMetrics.requests`를 추가합니다(LRU 동일).
  - ③ 추출: ④ RESPONSE_EXTRACT가 CURVE 값을 curve.json에서 채워 `responses_pred.csv`에 모든 성능을 씁니다(CURVE만이면 TCL 미실행). ①-6·PV는 CURVE를 조용히 건너뜁니다. 끝난 배치의 H3D 성능 다시 추출은 새 job `PB_RESP_EXTRACT`(SLOT, PX_PREP·RESPONSE_EXTRACT_RUNS·PX_TABLE, `POST /predict-batches/{bid}/extract-responses`)입니다.
  - ④ 역할: 목적 1~3(min·max)·제약 ≤5(≤·≥·range, `==` 없음)·관찰 ≤10을 `settings`에만 둡니다. 성능 정의는 스냅샷합니다. 단수 `objective` 호환(`settings.objective = objectives[0]` 계속 기록)이며, 단일 목적은 §18.5 EI×PoF를 그대로 씁니다.
  - ⑤ 다목적(`SURROGATE_OPT` 확장, 새 job_type 아님):
    - 목적별 GP
    - 예측 전선 = Das–Dennis 격자(11·28) 증강 Chebyshev(ρ 0.05) + DE(integrality)
    - 후보 c₁ = 예측 전선 HVI 최대(0이면 거리 규칙), c₂… = ParEGO(가중치 순열 배정, 반복 간 비중복, EI×PoF, range PoF)
    - HV는 탐색 자료로 고정한 정규화 틀(기준점 1.1)의 정확 HV(2D 스윕·3D 슬라이스)이고, 수렴은 HV 개선율 < tol_rel입니다.
    - 시드 식은 §22.5.7입니다. numpy·scipy만 쓰고 새 의존성은 없습니다.
  - ⑥ 결과:
    - 검증된 파레토 해(API가 `pareto.py`로 매번 계산, EXTRA 포함)와 예측 전선을 구분합니다.
    - 가중 추천 = 전선 내 0~1 정규화 가중합 최소입니다(식·동점·골든 §22.6). best·FINAL·알림은 생성 시 가중치를 쓰고, 화면 슬라이더는 localStorage만 씁니다.
    - 2목적 산점도·3목적 쌍 그림·HV 그래프·파레토 표를 둡니다.
    - 해 선택 → 단일 예측으로 열기 / 추가 검증 배치(`POST /surrogate-opts/{oid}/verify`, iters kind `EXTRA`, DONE만, 캡처 선택, 결과가 전선에 반영, 일반 배치 알림) / FEM 검증(S16 `POST /studies/{id}/fem-verifications`(source `opt_design`)·`features.fem_verify`)
    - FINAL 2행 = 기준안 + 가중 추천점
  - ⑦ migration `0014_multiobj`(Revises S16 0013): iters kind `EXTRA`·`hv`·`front_size`·`predicted_front`, opts `hv_frame`.
  - ⑧ 설정 `surrogate_opt.{max_objectives 3, max_observe 10, max_extra_points 10, mo_lattice_h2 10, mo_lattice_h3 6, mo_de_maxiter 100, mo_rho 0.05, mo_ref_offset 0.1, mo_gp_restarts 4}`.
  - ⑨ 시험 V3-S17-1~13(HV 골든 0.37·0.256, ZDT1 0.87667·DTLZ2 0.80740 근사, ZDT1·ZDT2·DTLZ2 루프 HV 비율·LHS 대비 우위, 가중 추천 골든 Python·TS 공용), 서버 확인 E4-17. 파일 소유는 Impl-Backend / Impl-Frontend(§22.15)이고 `services/surrogate_opts.py`는 300줄 규칙에 맞춰 problem·pareto 서비스로 분리합니다.

- **D3-65 보강 (메인, 2026-10-19)**: FEM 검증 연동 placeholder를 S16 확정 API로 교체 — `POST /studies/{id}/fem-verifications` + `source:{kind:"opt_design", opt_id, pick:"run", iter_no, doe_no}`(검증된 해), 가용 여부 `/status.features.fem_verify`. §22.7 ①(prepared PREDICT 출처 수용)은 S16 §21.3.2 `opt_design`·`batch_run`으로 충족, 응답은 S16 생성 응답 모양을 따른다. 병합 순서 S16 → S17 고정.
