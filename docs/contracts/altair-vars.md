# 계약: Altair 템플릿 변수 공간(전체 파라미터 tpl · 변수 정의) — 학습 변수와 독립

> 상태: 확정 초안(2026-10-22, 사용자 결정). 릴리스 **v0.2.8**([roadmap.md](../roadmap.md), v0.2.7 [input-kind.md](input-kind.md) 배포 후). 기준: v0.2.6(5b965fe) + v0.2.7.
> 상위: phase2 §6.3(①-2 tpl 생성), phase3 §14·§18, [native-vars.md](native-vars.md)(같은 API·리비전·스냅숏 — 이 문서는 그것을 Altair로 넓히는 차이만 적는다). 충돌 시 이 문서 우선(Altair 변수 한정).
> ID 규칙: 결정 `AV-n`, 시험 `V-AV-n`, 변경 메모 `AV-Cn`.

## 0. 한 줄 요약

①-2가 **CAD 전체 파라미터를 담은 tpl**을 만든다(사용 = ① DOE 범위, 미사용 = 공칭 고정). ① DOE는 사용 파라미터만 표본을 뽑아 **결과가 지금과 같다**. 이 tpl로 만든 ④ Altair 템플릿은 Native와 같은 변수 정의(사용·하한·상한, 리비전·실행 스냅숏)와 ⑥·④ 일괄 그 자리 편집을 쓴다(P1 "데이터 생성 DOE와 최적화 DOE는 독립 변수 공간"). 옛 템플릿(사용 파라미터만 담은 부분 tpl)은 편집 불가 + 재생성 안내.

## 1. 배경

- P1(2026-10-22): 데이터 생성 DOE와 최적화 DOE는 독립 변수 공간. 예측 모델 입력은 형상이라 템플릿 변수는 학습 변수와 달라도 된다(native-vars §1.1과 같은 근거).
- 현재(코드 확인): `train_tpl.generate`는 사용 파라미터만 두 블록(`{parameter(var_i, …)}`·`<paramitem …>`)에 쓰고 미사용은 뺀다(가정 A-5). ④ Altair 템플릿의 변수 = tpl 선언 = ① 사용 파라미터뿐이라, ⑥·④에서 다른 파라미터를 움직이려면 ①부터 다시 해야 한다. ⑥ Altair 범위는 세트 범위 밖이면 422 `BOUNDS_OUT_OF_RANGE`, `vars`는 422 `NATIVE_VARS_UNSUPPORTED`(NV-11).
- 사용자 결정(2026-10-22): ①-2 tpl을 CAD 전체 파라미터 포함으로 생성("사용"은 ① DOE에서만 의미, 미사용은 공칭 고정). 기존 Altair 템플릿은 재생성해야 변수 선택 가능.

## 2. 결정 요약(AV-1~AV-12)

| ID | 결정 |
|---|---|
| AV-1 | ①-2 tpl = ①-1 표의 **유효한 모든 행**(`with_validity` 통과)을 표 순서로 `var_1…var_N` 선언·참조. 사용 행 `parameter(var_i, name, nominal, min, max)`(DOE 범위), 미사용 행 `parameter(var_i, name, nominal, nominal, nominal)`(공칭 고정). paramitem은 모든 행 `NewValue="{var_i, fmt}"` |
| AV-2 | 유효하지 않은 미사용 행은 tpl에서 빼고 note `TPL_PARAM_SKIPPED`(이름 목록). 유효하지 않은 **사용** 행은 지금처럼 422 |
| AV-3 | **범위 표지**: 생성 tpl의 parameter 블록 바로 뒤에 Python 주석 한 줄 `# physicsai-tpl scope=full v=1`(SimLab 스크립트·HyperStudy 모두 주석으로 무시). 이 줄이 있는 tpl = 전체 tpl, 없으면 부분 tpl(옛 것·사용자 수작업) |
| AV-4 | 스냅숏 `train_setups.tpl_params`(JSONB, 형식 확장) 행에 `used: bool`·`table_min`·`table_max`(①-1 표 값 — 미사용 행의 ④ 기본 범위 출처) 추가. 기존 행(키 없음) = 사용 |
| AV-5 | **① DOE 불변**: 표본은 사용 행만(`parameters_snapshot` = 사용 행 그대로), 렌더 값 = 표본 ∪ {미사용: 공칭}. 점 표·스냅숏·run 수가 v0.2.7과 같고, 렌더 스크립트 차이는 미사용 paramitem 줄(값 = `fmt % 공칭`) 및 표지 주석 줄뿐 |
| AV-6 | 공칭 표기 손실 방지: 미사용 행에서 `fmt % 공칭`을 다시 읽은 값이 공칭과 다르면(상대 1e-9 초과) 그 행은 paramitem `NewValue`를 **원래 `Value` 문자열 그대로**(변수 참조 없음)로 쓰고 선언에서 뺀다 + note `TPL_NOMINAL_FORMAT_LOSS`. 이 행은 ④ 풀에 들어가지 않는다 |
| AV-7 | HyperStudy 레거시 ① DOE(`train_doe` hstbatch, 설정 시에만)는 `D/simlab_parametered_mesh.tpl` = **사용 뷰**(미사용 선언 제거·참조를 `fmt % 공칭` 문자로 치환 — `train_tpl.used_view`)를 받고 전체 tpl은 `D/simlab_parametered_mesh.full.tpl`로 둔다. 플랫폼 DOE는 `D/<TPL_NAME>` = 전체 tpl |
| AV-8 | ④ Altair 템플릿 **풀** = tpl 선언(전체 tpl이면 CAD 전체 파라미터). 세트 정의·리비전·실행 스냅숏·API는 native-vars §3·§4·§6과 같음(`S/vars/`, `param_sets.parameters`, `predict_batches.source_meta.vars`, `surrogate_opts.settings.vars`). 제외·풀 밖 행 = 렌더 시 공칭 |
| AV-9 | 범위 규칙(전체 tpl Altair): native-vars NV-7과 같게 경고만(`VAR_OUT_OF_TRAIN`·`VAR_NOMINAL_OUTSIDE`), `BOUNDS_OUT_OF_RANGE` 미발행. feasible·ref_locked 없음. 형상 생성 실패(SimLab)는 기존대로 run 실패·스킵 |
| AV-10 | 경계 코드: 부분 tpl Altair에 `vars`·정의 PUT → 422 `TPL_SCOPE_PARTIAL`("옛 tpl(사용 파라미터만) — ①-2에서 tpl을 다시 생성해 새 템플릿으로 등록하세요"). 부분 tpl 템플릿의 그 밖 동작(범위 = 세트 범위, `BOUNDS_OUT_OF_RANGE`)은 **무변경**. `NATIVE_VARS_UNSUPPORTED`는 이 릴리스부터 발행하지 않음(코드 표에 "v0.2.8 폐지 — `TPL_SCOPE_PARTIAL`로 대체" 기록) |
| AV-11 | 기존 READY ① DOE의 업그레이드: ①-2 tpl을 다시 생성(전체)해도 기존 DOE 폴더 tpl은 그대로. "① 결과로 만들기"(Altair from-train)에 `tpl_source: "doe" \| "current"` 추가 — `current` = 현재 ①-2 전체 tpl을 쓰되 `used_view(current)`의 선언(이름·공칭·범위)이 그 DOE 스냅숏과 같을 때만(아니면 409 `TPL_DOE_MISMATCH`). DOE를 다시 돌리지 않고 전체 tpl 템플릿을 얻는다 |
| AV-12 | DB migration 없음(JSONB·파일만). Native 동작 무변경 |

## 3. ①-2 tpl 생성 규칙(`physicsai_core/stage1_train_data/train_tpl.py`)

- `generate(template_text, rows, cad_file_name, rules)`: `rows` = ①-1 표 유효 행 전부 `[{name, nominal, min, max, format, used}]`. 사용 행은 표 범위, 미사용 행은 `min = max = nominal`. 결과 앞부분 = parameter 블록 → 표지 줄(AV-3) → marker 이하 원문. paramitem 블록 규칙·anchor·빈 줄 정리는 현행.
- `validate_generated(text, rows)`: 선언 이름 집합 = tpl에 넣은 행(AV-2·AV-6 제외분 빼고)과 같음, 형식·참조 검사 현행.
- `used_view(full_text, used_names, nominal_by_name)`: 미사용 선언 줄 제거, 그 변수 참조 `{var_i, fmt}` → `fmt % 공칭`. 결과는 v0.2.7 생성 tpl과 **선언·참조 집합이 같다**(V-AV-2).
- 감사 `TRAIN_TPL_GENERATE` detail에 `{used, total, skipped}`.
- 화면 ①-2: "tpl에 전체 {N}개 파라미터 포함(사용 {k}개 = DOE 범위, 나머지 공칭 고정)" 1줄 + note 목록. 사용 체크의 뜻 aside "사용 = 학습 데이터(DOE)에서 움직일 파라미터. 예측·최적화 변수는 ④ 템플릿에서 따로 정합니다".

## 4. ① DOE(불변 확인)

| 경로 | 변경 |
|---|---|
| 플랫폼 DOE(`doe_platform_gen`) | `D/<TPL_NAME>` = 전체 tpl 사본(sha 검사 현행). run 렌더 `render_tpl(text, values ∪ 미사용 공칭, applied ∪ 미사용 공칭)` — 공용 도우미 `train_tpl.fill_nominal(decl, values)` |
| 레거시 hstbatch DOE(`doe_gen`) | AV-7(사용 뷰 + `.full.tpl`) — HyperStudy 입력의 변수 집합·범위 불변 |
| 표본·스냅숏 | `doe_platform.build`·`parameters_snapshot` = 사용 행(현행 `tp.used`) |
| ①-3 run 결과 | 형상: 미사용 paramitem이 공칭 값을 다시 넣을 뿐(SimLab 결과 동일 가정 — V-AV-3 fake + 현장 1회 확인) |

## 5. ④ Altair 템플릿 변수 정의

### 5.1 풀·정의

- 풀(`physicsai_core/geometry/native_vars.pool`을 엔진 무관 `template_vars.pool(ps, S)`로 일반화 — Native는 현행 규칙, Altair는 아래): tpl 선언 행 `{name, nominal, unit, integer(fmt가 i·d), default_range}`. `default_range` = 세트 `tpl_params[].table_min/max`(from-train) → 없으면 선언 범위(사용 행), 선언이 고정(min = max)이고 표 값도 없으면 `[nominal, nominal]` + 행 표시 "범위를 입력하세요".
- 템플릿 응답 `ParamSet.vars_scope: "full" | "partial" | null`(Altair만, 표지 줄 판정) + `vars_revision`·`vars_count`(Native와 같은 키, native-vars §6.1).
- 정의 저장(`PUT /param-sets/{id}/variables`): 전체 tpl Altair 허용(native-vars §3.2 저장 순서·리비전·감사 그대로). 검증 = native-vars §3.4에서 feasible·ref_locked 줄 제외 + 정수 형식 행은 하한·상한 정수(아니면 `VAR_RANGE_INVALID` "정수 파라미터는 정수 범위여야 합니다").
- 폴더 검증: 전체 tpl Altair는 `_load_parameters(..., require_nominal_inside=False)`(D5와 같게), 부분 tpl은 현행 True.

### 5.2 실행(⑥·④ 일괄·④ 단건·①-3 세트 DOE 없음)

- ⑥ `SurrogateOptCreate.vars`·④ `PredictBatchParams.vars`: 전체 tpl Altair 허용, 규칙·스냅숏·경고는 native-vars §6.2·§6.3(Altair 문구 동일, feasible 경고 없음). 학습 범위 출처는 native-vars §5.2를 Altair DOE까지 넓힌다(단계 2의 `engine = native` 조건 제거, 동일 피처 확인 = 이름 같고 공칭 차 ≤ 1e-6·max(1,|공칭|)).
- 워커 렌더(단건 `tpl_render`, 일괄 `bp_prep`, ⑥ 소유 배치): 값 = 실행 변수 값 ∪ 풀의 나머지 공칭(`fill_nominal`) → `render_tpl`. 정수 반올림은 기존 `integer_rounding`.
- ④ 단건 PREDICT: 화면 변화 없음(세트 정의를 따름), 렌더만 `fill_nominal`.
- `train_doe` 표본(④ 일괄 ① DOE 재사용): DOE 헤더 ⊆ 풀이면 허용(native-vars §6.3과 같음).

### 5.3 옛 템플릿(부분 tpl) 처리

- ④ 상세 변수 표: 읽기 전용 + 안내 "옛 tpl(① 사용 파라미터만 포함) — 변수 추가·제외는 ①-2에서 tpl을 다시 생성한 뒤 '① 결과로 만들기(현재 tpl 사용)' 또는 폴더 등록으로 새 템플릿을 만드세요"(AV-11 링크).
- ⑥·④ 일괄: 범위 표는 현행 Altair(세트 범위 안만), 변수 추가 상자 숨김, `vars` → 422 `TPL_SCOPE_PARTIAL`.
- 기존 실행·배치·최적화 기록은 무변경(스냅숏 없음 = 현행 경로).

## 6. API 요약

| API | 변경 |
|---|---|
| `GET /param-sets/{id}/variables` | Altair 허용(부분 tpl은 `editable: false`, `reason: "TPL_SCOPE_PARTIAL"`). 응답 `NativeVars` 모양 그대로(이름 유지 — 호환), `pool[].type/body/feasible/group` = null, `engine` 추가 |
| `PUT /param-sets/{id}/variables` | 전체 tpl Altair 허용, 부분 tpl 422 `TPL_SCOPE_PARTIAL` |
| `ParamSet` | `vars_scope`(Altair), Altair도 `vars_revision`·`vars_count` |
| `POST /studies/{id}/param-sets/from-train`(Altair) | `tpl_source?: "doe"\|"current"`(기본 `doe` — 현행), 409 `TPL_DOE_MISMATCH` |
| ①-2 tpl 생성 응답 | `tpl_summary: {total, used, skipped:[이름], format_loss:[이름]}` |

- MCP: `get_native_vars` 도구가 Altair 템플릿에도 동작(새 도구 없음, 설명 문구에 "Native·Altair(전체 tpl)" — `x-mcp.version` 그대로, 설명 변경만). `vars` 입력은 기존 `params_model` 자동 포함. `SUMMARIES` `param_set` facts에 `vars_scope`.
- 코드 표 추가: `TPL_SCOPE_PARTIAL`(422/problem), `TPL_DOE_MISMATCH`(409), `TPL_PARAM_SKIPPED`·`TPL_NOMINAL_FORMAT_LOSS`(note). `NATIVE_VARS_UNSUPPORTED` 폐지(AV-10).

## 7. UI

- ④ Altair 세트 상세: 기존 tpl 파라미터 표를 공용 `NativeVarsTable`(이름 유지, 엔진 열 분기)로 — 열 사용·이름·공칭·학습 범위(⑥·일괄만)·하한·상한·고정·경고(종류·바디·모핑 가능 범위·기준면 열 숨김). 머리줄 "변수 정의 rev {n} · 사용 {k}/{풀}" + 저장·되돌리기(native-vars §7.1과 같음).
- ⑥ `SurrogateSetup`·④ `BatchSetup`: Altair 전체 tpl이면 Native와 같은 카드(aside "범위 자유 · 학습 범위 밖은 경고"), 부분 tpl이면 현행 + 안내 1줄.
- ①-2: §3 문구. 새 화면 없음, `frontend-dist` 함께 커밋.

## 8. 구현 분해·병렬

| 담당 | 범위 | 순서 |
|---|---|---|
| Impl-Geom | 불필요 | — |
| Impl-Backend #1(①) | `train_tpl.generate`·`validate_generated`·`used_view`·`fill_nominal`, `services/stage1_train_data.py`(①-2 rows·스냅숏·감사·요약), 워커 `doe_platform_gen`(렌더 fill)·`doe_gen`(사용 뷰 + `.full.tpl`), 시험(V-AV-1~3) | #2와 병렬 |
| Impl-Backend #2(④·⑥) | `geometry/native_vars.py` → 엔진 무관 풀·`train_ranges` Altair 확장, `native_vars_api`(Altair 허용·scope 판정), `param_set_files._load_parameters` 인자, from-train `tpl_source`, `surrogate_opt_space`·`surrogate_opt_problem`·`job_params/stage4_batch`(Altair 전체 tpl 분기, `TPL_SCOPE_PARTIAL`), 워커 `predict.tpl_render`·`batch.bp_prep`(fill_nominal + 스냅숏 `nv.apply`), 조회 열, MCP 설명·SUMMARIES, openapi, 시험(V-AV-4~8) | #1이 만든 `fill_nominal`만 의존(먼저 병합하거나 같은 브랜치 순차) |
| Impl-Frontend | ④ Altair 상세 표·⑥·일괄 카드 분기·①-2 문구·from-train 선택, schema·mock·`frontend-dist` | openapi 뒤 |

## 9. 검증(V-AV-*)

- **V-AV-1 생성**: ①-1 표 12행(사용 4) → tpl 선언 12개(사용 4 = 표 범위, 미사용 8 = min = max = 공칭), paramitem 12줄, 표지 줄 1개, 무효 미사용 행 `TPL_PARAM_SKIPPED`, 표기 손실 행 `TPL_NOMINAL_FORMAT_LOSS`(리터럴 Value, 선언 없음).
- **V-AV-2 사용 뷰**: `used_view(전체)`의 선언·참조 집합 = v0.2.7 `generate(사용 행)`과 같음(레거시 hstbatch 입력 불변).
- **V-AV-3 ① DOE 불변**: 같은 seed·설정으로 v0.2.7 대비 `train_doe_points` 값·`parameters_snapshot`·run 수 동일, 렌더 스크립트 차이는 미사용 paramitem 줄뿐이며 각 값 = `fmt % 공칭`.
- **V-AV-4 풀·정의**: 전체 tpl Altair 세트 GET 풀 = 선언 12개, PUT 리비전·`parameters.json`·DB 갱신, 정수 범위 검사, 부분 tpl → `editable:false`·PUT 422 `TPL_SCOPE_PARTIAL`.
- **V-AV-5 실행**: ⑥·④ 일괄에서 `vars.add`(미사용이던 파라미터)·exclude·범위(학습 밖 포함) → 경고만, run 렌더 값 = 실행 값 ∪ 공칭, 스냅숏 재현(native-vars V-NV-3 방식).
- **V-AV-6 학습 범위**: Altair DOE 기반 모델 → `train` 채움(사용 행 = DOE 범위, 미사용 행 = [공칭, 공칭] — 움직이면 외삽 경고).
- **V-AV-7 업그레이드**: 기존 READY DOE + ①-2 재생성 → from-train `tpl_source: current` 성공(전체 tpl 세트), 사용 행이 다르면 409 `TPL_DOE_MISMATCH`.
- **V-AV-8 무변경**: 부분 tpl Altair·Native 기존 시험 무수정 통과, 부분 tpl ⑥ 범위 밖 = 기존 `BOUNDS_OUT_OF_RANGE`, `scripts/test-all` 통과, migration 없음.

## 10. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 미사용 파라미터를 SimLab에 공칭으로 다시 넣는 것이 넣지 않은 것과 형상이 다를 수 있음(파라미터 간 의존·재생성 순서) | V-AV-3 + 현장 1회(같은 값 run의 메시 노드 수·부피 비교), 다르면 AV-6처럼 리터럴 Value 쓰기로 전환(설정 없이 계약 변경) |
| R2 | ①-1 표의 미사용 행 범위가 비어 ④에서 범위를 처음부터 입력해야 함 | `table_min/max` 승계, 없으면 "범위를 입력하세요" |
| R3 | 미사용 파라미터를 움직이면 학습 분포 밖(외삽) | `VAR_OUT_OF_TRAIN`(학습 범위 = [공칭, 공칭]) 경고 |
| R4 | `NATIVE_VARS_UNSUPPORTED`에 의존한 외부 클라이언트 | 코드 표·RELEASES에 대체 코드 명시 |

## 변경 메모

(구현 중 계약과 달라지면 `AV-C1~`로 기록하고 Plan 확인.)
