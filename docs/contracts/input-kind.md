# 계약: 예측 입력 종류(조립·쿠션) — 실행 단위 선택 · 데이터 생성은 조립만

> 상태: 확정 초안(2026-10-22, 사용자 원칙 P1~P3). 릴리스 **v0.2.7**([roadmap.md](../roadmap.md)). 기준 커밋 5b965fe(배포된 v0.2.6, migration HEAD `0021_uploads`).
> 상위: phase3 §11.4·§14.3·§14.4(템플릿 입력 종류 mesh_only)·§14.5(일괄)·§21.3(FEM 검증), [geometry-engine.md](geometry-engine.md)(native 체인, 변경 메모 GE-C19), [native-vars.md](native-vars.md)(변수 정의), [opt-native.md](opt-native.md)(⑥ 내장). 충돌 시 이 문서 우선(입력 종류 한정).
> ID 규칙: 결정 `IK-n`, 시험 `V-IK-n`, 변경 메모 `IK-Cn`.

## 0. 한 줄 요약

④ 예측(단건·일괄)과 ⑥ 내장 최적화에서 **실행마다 입력 종류 `input: "assembly" | "cushion"`을 고른다**. 쿠션 입력은 조립(m_3)을 만들지 않고 **쿠션 메시 rad 하나**(Altair = SimLab 산출 `EPS_mesh_0000.rad`, Native = 모핑 후 쿠션 바디만 쓴 같은 이름의 rad)를 예측 모델에 넣어 서버 GPU 메모리 초과를 피한다. 모델은 형상 입력이라 조립 데이터로 학습한 모델에 쿠션 입력을 그대로 넣는다(모델 분리 없음). ① 데이터 생성·③ 학습은 **조립만**(P3). 내부 저장값은 기존 열·키(`input_kind`/`template_kind` = `assembly|mesh_only`)를 재사용해 **migration 없음**.

## 1. 사용자 원칙(2026-10-22, 원문 요지)

| # | 원칙 |
|---|---|
| P1 | "데이터 생성 단계의 DOE랑 최적화에서 하는 DOE는 독립적인 변수 공간이어야 한다." → Native는 native-vars(v0.2.4)로 충족, Altair는 [altair-vars.md](altair-vars.md)(v0.2.8) |
| P2 | "최적화는 쿠션 입력과 조립 입력 구분 필요." 현장: ⑥ 예측이 m_3(조립 rad)를 가져가 예측 → 서버 GPU 메모리 초과. 쿠션 입력이면 m_1(SimLab 산출 EPS 쿠션 rad)로 예측. 조립 데이터로 학습한 모델에 쿠션 입력을 넣어도 된다(형상 입력, 입력 폭이 넓음) — 모델 분리 불필요 |
| P3 | "데이터 생성·학습은 조립만." |
| Native | "이전 데이터 생성 변수를 가져오든, 최적화에서 STEP을 받아 새로 변수를 선언하든. 여기도 조립과 쿠션 구분하고, 입력을 쿠션으로 하면 모핑한 다음 쿠션 입력 rad 파일만 만들어 최적화 예측 모델에 넣어야 한다." |

## 2. 현황(코드 확인, 5b965fe)

- 템플릿 종류는 이미 있다: `param_sets.input_kind ∈ {assembly, mesh_only}`(mesh_only = `radioss_assem/` 없이 SimLab 메시로 바로 예측, phase3 §14.4). Native 세트는 DB 제약 `ck_param_sets_native_assembly`로 항상 assembly.
- 실행 쪽 저장 위치도 이미 있다: `predict_batches.input_kind`·`surrogate_opts.input_kind`(CHECK `mesh_only|assembly`), 단건 `PREDICT` job params `template_kind`(서버 확정 기록, `predict_inputs.template_kind`가 params 우선으로 읽음). **지금은 셋 다 템플릿 종류를 그대로 복사**(`job_params/stage4_predict.template_kind(ps)`) — 사용자가 고를 수 없다.
- mesh_only 체인(Altair): 단건 `MESH` SKIPPED(`MESH_ONLY_SKIP`), `RAD_ASSEMBLE` = `mesh_only_into`(P/geom 직계 `*.rad`·`*.inc`를 P/INPUT으로 **복사만**, starter = `predict.simlab_mesh_name`), `EDSPY_PREDICT`가 `P/INPUT/<starter>`로 예측 → `RESULT/<stem>_pred.h3d`. 일괄 `run_chain.build_run_inputs(assembly=False)`는 m_1 형상 갱신 뒤 바로 `m_1/{simlab_mesh_name}` 반환(m_2·m_3 없음), `input_rel_for` = `run__N/m_1/EPS_mesh_0000.rad`, 하위 PREDICT(prepared, 파일 입력).
- Native 체인: 단건 `GEOM_UPDATE` = `paicad update`, `MESH` = `paicad morph` → `paicad check`(PASS면 `P/geom/{mesh_include_name}`), `RAD_ASSEMBLE` = `predict_native.rad_assemble`(조립 사본 + 모핑 include). 일괄 `geometry_sample.generate_sample(..., assemble=True)`가 m_1(update)·m_2(morph·check·include)·m_3(조립). `assemble=False` 인자는 이미 있다. 쿠션만 쓰는 rad를 만드는 기능은 **없다**(native 등록은 `eps_mesh*`를 조립 사본에서 뺀다 — `param_set_native.py`·`param_set_native_train.py`).
- FEM 검증(`FEM_VERIFY`)은 쿠션 메시뿐인 예측 입력을 이미 다룬다: "예측 입력 그대로(reuse)"는 `INPUT_MESH_ONLY`로 막고, **재조립(rebuild)** — 조립 원본(`train_doe`·`custom`) + 메시 교체(Altair `FV_MESH` include 변환, Native는 모핑 include 그대로 — `_rebuild_checks` `mesh_native`) — 으로 검증한다. `auto_isolate_cushion`은 mesh_only일 때 메시 include의 `/PART` id로 컨투어 대상 부품을 자동 지정, 응답은 경고 `FEM_RESPONSE_WHOLE_MODEL`.
- ①-3 DOE는 조립 폴더 필수(`job_params/stage1_train_data.py`·`stage1_native.py` "조립 폴더 경로가 필요합니다", 세트 기준 DOE는 세트의 조립 폴더). 데이터셋 출처는 `datasets.source_path`(① DOE 판별 = `dataset_engine._doe_ids`).

## 3. 결정 요약(IK-1~IK-14)

| ID | 결정 |
|---|---|
| IK-1 | **실행 단위 입력 종류** = 요청 선택 필드 `input: "assembly" \| "cushion"`(④ 단건 `PredictParams`, ④ 일괄 `PredictBatchParams`, ⑥ `SurrogateOptCreate`). 생략 = 템플릿이 조립 가능하면 `assembly`(하위호환), 쿠션만 가능하면 `cushion` |
| IK-2 | **저장은 기존 열·키 재사용**: `cushion` ↔ 내부 값 `mesh_only`, `assembly` ↔ `assembly`. 일괄 `predict_batches.input_kind`, ⑥ `surrogate_opts.input_kind`(→ ⑥ 소유 배치 `template_kind`), 단건 job params `template_kind`. DB 스키마·CHECK·migration 변경 없음(`MIGRATION_HEAD` = `0021_uploads` 유지) |
| IK-3 | **템플릿 능력** `input_capability`(조회 계산값, 저장 안 함): Altair assembly → `[assembly, cushion]`, Altair mesh_only → `[cushion]`, Native solid(단일·다중 baseline) → `[assembly, cushion]`(단, `commands.paicad_cushion_write` 미설정이면 `[assembly]` + 사유), Native 쉘(판금 비드)·쉘 두께 전용 → `[assembly]`(쿠션 바디 없음) |
| IK-4 | **Altair 쿠션 = 기존 mesh_only 경로와 같은 코드**(일원화): 템플릿 종류 대신 실행의 `template_kind`로 분기. 조립 가능 템플릿을 쿠션으로 돌려도 mesh_only 템플릿과 같은 단계·산출물·예측 입력 |
| IK-5 | **Native 쿠션** = 모핑(`morph`→`check` PASS) 뒤 새 paicad 명령 `paicad cushion write`로 **쿠션 바디만의 Radioss rad**(노드·요소 ID 유지)를 `predict.simlab_mesh_name`(기본 `EPS_mesh_0000.rad`) 이름으로 쓴다 → 예측 입력. 조립(m_3·inc 교체·`commands.rad_assemble`) 없음 |
| IK-6 | 쿠션 rad 이름을 두 엔진 모두 `predict.simlab_mesh_name`으로 통일 → `input_rel_for`·`is_mesh_file`(eps_mesh 판정)·FEM `input_is_assembly`·`<stem>_pred.h3d` 이름 규칙이 그대로 맞는다 |
| IK-7 | 쿠션 rad의 바디 범위 = 세트 `RENUM_INIT.csv`의 component 전부(= native 모핑 대상 쿠션 바디, GE §4.1 — tetra 쿠션 바디만 component가 될 수 있음). 기준 쿠션 메시 = 세트 `radioss_assem/{mesh_include_name}`(native 등록 필수 파일). 별도 EPS 메시·업로드 불필요 |
| IK-8 | **FEM 검증**: 쿠션 실행도 재조립(rebuild)으로 검증 가능(기존 mesh_only 동작 유지 — 비활성 아님), reuse는 기존 `INPUT_MESH_ONLY`. 조립 가능 템플릿의 쿠션 실행은 새 조립 원본 `assembly.kind: "template"`(그 템플릿의 `radioss_assem/` = 조립 입력 실행이 쓸 조립과 같음)을 기본으로 고른다(§8) |
| IK-9 | 쿠션 선택은 ④·⑥에만. ① 데이터 생성·③ 학습은 조립만(P3) — ①-3 조립 폴더 필수 유지(코드 확인 §2), ① 화면에 "조립 기준" 표시, ③ 데이터셋 출처 표시(§9) |
| IK-10 | 표시: 템플릿 배지(조립 가능 / 쿠션만), 실행 목록·상세·결과·HTML 보고서·MCP 요약에 입력 종류(`input`) |
| IK-11 | 오류·경고 코드: 422/problem `INPUT_KIND_UNSUPPORTED`(템플릿이 그 입력을 못 함), 경고 `INPUT_CUSHION_RESPONSES`(쿠션 입력은 쿠션 메시 결과만), 409 `TEMPLATE_NOT_CONFIGURED`(기존 — native 쿠션 명령 미설정) |
| IK-12 | Native 변수 출처 두 가지: (a) ①-1/①-2 데이터 생성 세트에서 가져오기(현행 "① 결과로 만들기"), (b) ⑥ 화면 "새 Native 템플릿(STEP)" 링크 → ④ 세트 등록(기존 `PARAM_SET_NATIVE`·업로드 탭 재사용). 둘 다 native-vars로 변수·범위를 학습과 독립 선택(§7) |
| IK-13 | HyperStudy 레거시 `optimize`·④ prepared(준비된 입력)에는 `input`을 받지 않는다(prepared는 starter가 결정 — 표시만 판정) |
| IK-14 | 앞서 검토한 "Native m_1 rad + Altair 변수 대응표"는 **폐기**(P1·P2로 불필요 — decisions 2026-10-22) |

## 4. 체인별 단계 처리

### 4.1 ④ 단건 `PREDICT`(단계 키 불변: PR_PREP → TPL_RENDER → GEOM_UPDATE → MESH → RAD_ASSEMBLE → EDSPY_PREDICT → …)

| 단계 | Altair assembly | Altair cushion(= mesh_only) | Native assembly | Native cushion |
|---|---|---|---|---|
| PR_PREP | 현행 | 현행 mesh_only(조립 폴더 검사 생략). result `template_kind: "mesh_only"`, `input: "cushion"` | 현행 | 현행 + `commands.paicad_cushion_write` 확인(없으면 `TEMPLATE_NOT_CONFIGURED`). result `template_kind: "mesh_only"`(지금 하드코딩된 `"assembly"`를 params 값으로) |
| TPL_RENDER | 현행 | 현행 | values.json | values.json |
| GEOM_UPDATE | SimLab → `P/geom/EPS_mesh_0000.rad` | 같음(이 파일이 예측 입력) | `paicad update` | `paicad update` |
| MESH | m_2 HyperMesh include 변환 | **SKIPPED**(`MESH_ONLY_SKIP` 문구를 "쿠션 입력 — 메시 연결 불필요"로) | `paicad morph`→`check` → `P/geom/{mesh_include_name}` | `morph`→`check` PASS 뒤 **`paicad cushion write`** → `P/geom/{simlab_mesh_name}`(+ `P/geom/cushion/cushion.json`) |
| RAD_ASSEMBLE | 조립 사본 + 새 include, `commands.rad_assemble` | **복사만**(기존 `mesh_only_into`: P/geom 직계 `*.rad`·`*.inc` → P/INPUT, starter = `EPS_mesh_0000.rad`), `commands.rad_assemble` 실행 안 함 | `predict_native.rad_assemble` | **복사만**: `P/geom/{simlab_mesh_name}` **한 파일**만 P/INPUT으로(모핑 include는 복사 안 함), starter = 그 이름 |
| EDSPY_PREDICT | starter = 조립 starter | starter = `EPS_mesh_0000.rad` | 조립 starter | `EPS_mesh_0000.rad` |

- 화면 단계 이름: 쿠션 실행이면 `RAD_ASSEMBLE` = "쿠션 입력 복사"(`STEP_LABELS`에 입력 종류별 덮어쓰기 1곳 — `step_label(key, engine, input)`).
- RAD_ASSEMBLE을 SKIPPED로 두지 않는 이유: EDSPY는 `P/INPUT` 기준으로 실행되고(cwd·starter 경로), 기존 mesh_only가 이미 복사 방식이다(동작 일원화).
- 쿠션 실행 결과(`jobs.result`)에 `predict_input: {"input": "cushion", "starter": "EPS_mesh_0000.rad", "bytes": n, "files": 1}`을 기록(조립도 같은 키, `files`·`bytes` = P/INPUT 합계) — V-IK 검사와 화면 표시용, 수치만.

### 4.2 ④ 일괄 `PREDICT_BATCH`(BP_PREP → BP_GEN → BP_ENQUEUE, run 폴더 `run__N/m_1~m_3`)

| | Altair | Native |
|---|---|---|
| assembly | 현행 m_1 → m_2 → m_3, `input_rel` = `run__N/m_3` | 현행 `generate_sample(assemble=True)` |
| cushion | 현행 mesh_only 경로(`build_run_inputs(assembly=False)`), m_2·m_3 없음, `input_rel` = `run__N/m_1/EPS_mesh_0000.rad` | `generate_sample(assemble=False)`(m_1 update, m_2 morph·check·include) → `paicad cushion write`(`--out-dir run__N/m_2/cushion`, `--out-rad run__N/m_1/EPS_mesh_0000.rad`), m_3 없음, `input_rel` 규칙 동일 |

- BP_PREP: Altair 조립 폴더 검사는 `b["input_kind"] != mesh_only`일 때만(현행 그대로 — 이제 배치 값이 요청에서 온다). Native는 쿠션이면 명령 설정 확인.
- 하위 입력 검사 `check_child_input`(공용)은 쿠션이면 `m_1/EPS_mesh_0000.rad`(파일 입력 — `plan_copy`가 m_1 직계 `*.rad`·`*.inc`를 복사. Native m_1에는 values.json·native_params.xml·update/만 있으므로 쿠션 rad 하나).
- 쉘 두께 값(3S, `source: prop`)이 있는 세트는 쿠션 불가(IK-3 — PROP는 조립 쪽에 적용되는 값). 다중 baseline solid는 run별 배정 baseline의 include·조립 폴더로 쓴다(`inps[bid]`).
- `batch.json` `input_kind` 기존 키 그대로(+ `input` 표시값).

### 4.3 ⑥ 내장 최적화 `SURROGATE_OPT`

- `SurrogateOptCreate.input`(IK-1) → `normalize`가 IK-3 능력 검사 후 `surrogate_opts.input_kind`에 내부 값 저장 → 탐색·검증 루프가 만드는 ⑥ 소유 `PREDICT_BATCH`의 `template_kind`(기존 `surrogate_opts_write`)로 전달 → §4.2. 추가 검증(`POST /surrogate-opts/{oid}/verify`)·재개도 같은 값.
- 미리보기 응답에 `input`·`input_capability`, 쿠션이면 note `INPUT_CUSHION_RESPONSES` "쿠션 입력은 쿠션 메시의 예측 결과만 있습니다 — 제품(조립) 부품 기준 응답은 비거나 실패할 수 있습니다".
- ⑥ 결과에서 단건 예측·FEM 검증으로 넘길 때 입력 종류를 승계(단건 `input` 기본값 = 그 최적화의 입력 종류).

### 4.4 그 밖의 체인

- ④ prepared(준비된 입력): `input` 오면 problem `INPUT_KIND_UNSUPPORTED`(field `input`, "준비된 입력은 starter로 입력 종류가 정해집니다"). 표시 `input` = starter가 eps_mesh면 `cushion`, 아니면 `assembly`(판정 함수 공용 — `is_mesh_file`).
- HyperStudy 레거시 `optimize`: `input` 받지 않음(오면 `INPUT_KIND_UNSUPPORTED`), 동작 무변경.
- ⑤ 결과분석·등가성: 배치·최적화의 `input`을 열로만 표시(계산 무변경).

## 5. paicad — `paicad cushion write`(Impl-Geom, paicad 0.12.0)

필요 판단: **필요**. native 등록은 SimLab EPS 메시를 갖지 않고(조립 사본에서 `eps_mesh*` 제외), 모핑 결과는 기준 include의 노드 좌표만 바꾼 `104_replace_node_elem.inc`(starter 아님)다. 예측기가 읽는 독립 starter rad는 Radioss 카드(`/BEGIN`·`/PART`·`/PROP`·`/MAT`)를 조립 폴더에서 골라 붙여야 하므로 Radioss 쓰기 규칙(GE §6.4 바이트 보존)·writer 레지스트리(GE §18.3)를 가진 paicad에 둔다(플랫폼은 paicad를 import하지 않음).

### 5.1 CLI

| 명령 | 인자(필수 **굵게**) | 출력(성공 판정) |
|---|---|---|
| `paicad cushion write` | **`--inc`**(모핑 PASS include, 형상 값 없음이면 기준본), **`--renum-csv`**, **`--assem-dir`**, **`--out-dir`**, **`--out-rad`**, `--solver`(기본 `radioss`), `--options` | `cushion.json`(`status: OK`, `--out-dir`) + `--out-rad` 파일 |

- 공통 규약 GE §5.2 그대로: `--name value`, 출력이 있으면 종료코드 3 `GEOM_OUTPUT_EXISTS`(플랫폼이 실행 전 `_backup`), 임시 파일 → `os.replace`, 입력 읽기 전용, `PAICAD RESULT` 줄, 결정적 출력.
- 설정 키(Impl-Backend, `config/platform.example.yaml` 추가만): `commands.paicad_cushion_write: ["{paicad}", "cushion", "write", "--inc", "{cushion_inc}", "--renum-csv", "{renum_csv}", "--assem-dir", "{assem_dir}", "--out-dir", "{cushion_dir}", "--out-rad", "{cushion_rad}"]`. null = Native 쿠션 비활성(IK-3 사유 "관리자 설정 필요: commands.paicad_cushion_write").

### 5.2 `--out-rad` 내용(Radioss 고정폭 starter, 기존 EPS_mesh rad와 같은 구조 — 단일 파일, `#include` 없음)

| 순서 | 블록 | 출처·규칙 |
|---|---|---|
| 1 | `#RADIOSS STARTER` 주석 1줄 + `/BEGIN` 카드 | `--assem-dir` starter(`starter_glob` 1개, eps_mesh 제외)의 `/BEGIN` 카드(다음 `/` 카드 전까지)를 바이트 그대로. 실행 이름 줄만 `--out-rad` stem으로 바꾼다. 없으면 `GEOM_INPUT_INVALID` |
| 2 | `/PART/<pid>`(쿠션 part) + 참조 `/PROP/…/<id>`·`/MAT/…/<id>` | `--inc` → `--assem-dir` 직계 `*.rad`·`*.inc`(eps_mesh·`--inc`와 같은 이름 제외, 파일 이름 순) 순서로 찾은 **첫 정의**를 바이트 그대로. 못 찾으면 경고 `CUSHION_PART_DEF_MISSING`(이름 목록)이고 그 카드 없이 계속 |
| 3 | `/NODE` | 쿠션 요소가 참조하는 노드만(`--inc` 순서), 줄은 `--inc`의 줄 그대로(좌표 = 모핑 결과, **ID 유지**) |
| 4 | `/TETRA4/<pid>` 블록 | `--inc`에서 쿠션 component 요소 구간(GE §4.1 RENUM 규칙)의 블록을 바이트 그대로(**ID 유지**) |
| 5 | `/END` | |

- 쿠션 범위 밖 카드(`/GRNOD`·`/SURF`·`/INTER` 등 제품과 얽힌 집합)는 쓰지 않는다.
- `cushion.json` = `{schema_version:1, engine:"native", engine_version, status, code, category, message, out_rad, node_count, elem_count, bytes, parts:[{part, nodes, elems, part_def:bool}], begin_from, def_sources:[이름], warnings:[{code,message}], elapsed_s}`(수치·이름만).
- 실패 코드는 GE §5.4·§6.5의 기존 범주(`GEOM_INPUT_INVALID`·`GEOM_UNSUPPORTED_ELEMENT`·`GEOM_INTERNAL`)를 쓰고 새 종료코드는 만들지 않는다. 플랫폼 한국어 문구 매핑에 경고 2개(`CUSHION_PART_DEF_MISSING` "쿠션 부품 정의(PART·PROP·MAT) 일부를 조립 폴더에서 찾지 못했습니다", 요약 경고) 추가.
- 시험(paicad `tests/`): 합성 조립(starter·material.inc·기준 include·RENUM)에서 노드·요소 ID·좌표가 include와 같음, 제품 노드 0개, 카드 순서, 출력 존재 시 3, 결정성(두 번 실행 바이트 동일).
- `__version__` 0.11.0 → **0.12.0**, CHANGELOG 항목(AGENTS.md paicad 버전 규칙). 기존 명령 바이트 동작 불변.

## 6. API·DB·MCP

### 6.1 요청·응답(추가적·하위호환)

| 대상 | 변경 |
|---|---|
| `PredictParams`(④ 단건, parametric) | `input?: "assembly"\|"cushion"` → 서버가 `template_kind` 확정 기록(현행 키). 능력 밖이면 problem `INPUT_KIND_UNSUPPORTED`. 쿠션 + Altair면 `require_template_features(cfg, "mesh_only")`(geom_update만), Native면 cushion 명령 검사 |
| `PredictBatchParams`(④ 일괄)·미리보기 | `input?` → `predict_batches.input_kind`. 미리보기 응답 `input_kind`(현행) + `input`·`input_capability`·쿠션 note |
| `SurrogateOptCreate`(⑥)·미리보기 | `input?` → `surrogate_opts.input_kind`. 미리보기 `input`·`input_capability`·`INPUT_CUSHION_RESPONSES` |
| `ParamSet` | `input_capability: ["assembly","cushion"]` + `input_capability_reason: str\|null`(계산값) |
| 조회(배치 상세·목록, ⑥ 상세·목록, 단건 `predict_runs`, FEM 검증 `design`) | `input: "assembly"\|"cushion"` 추가(기존 `input_kind`는 유지 — 단건 `predict_runs.template.input_kind`는 템플릿 값이므로 실행 값 `input`을 따로 둔다: job params `template_kind` → result → 템플릿 순) |
| FEM 검증 `assembly.kind` | `"template"` 추가(§8) |

- 내부 값 변환은 한 곳(`physicsai_core/stage4_predict/input_kind.py` 신규 순수 함수: `to_internal(input)`, `to_public(input_kind)`, `capability(ps, settings) -> (list, reason)`, `of_prepared(starter)`).
- `backend/openapi.json`·`frontend/src/api/schema.d.ts` 갱신(Backend → Frontend).

### 6.2 DB

- migration **없음**. 쓰는 곳 = 기존 열 `predict_batches.input_kind`·`surrogate_opts.input_kind`(CHECK `mesh_only|assembly` 그대로), `jobs.params.template_kind`, `jobs.result.predict_input`. 템플릿 `param_sets.input_kind`·제약(`ck_param_sets_native_assembly` 포함) 무변경 — 템플릿 종류와 실행 입력 종류는 다른 개념(템플릿 = 능력, 실행 = 선택).
- 이후 migration이 필요해지면 `0022_*`(down_revision `0021_uploads`)로 Plan에 먼저 알린다.

### 6.3 MCP

- 새 operation 없음. `input`은 mcp `JOB_KINDS`의 `predict`·`predict_batch`·`surrogate_opt` `params_model`(기존 요청 모델)에 **자동 포함**(새 선택 인자 = 호환 변경, `kind_version` 불변 — native-vars §6.6과 같은 규칙). 도구 입력에서는 `params_json` 안(mcp §9.2).
- `SUMMARIES` `predict_batch`·`surrogate_opt`·`predict` facts에 `input` 추가, `param_set` facts에 `input_capability`. 용어집(`ko`) 한 줄씩: `input`(예측 입력 종류: 조립/쿠션), `cushion`(쿠션 메시 rad 하나로 예측 — 조립 없음).

### 6.4 코드 표

| 코드 | 종류 | 문구(한국어) |
|---|---|---|
| `INPUT_KIND_UNSUPPORTED` | 422 / problem(field `input`) | 이 템플릿은 {조립\|쿠션} 입력을 쓸 수 없습니다({사유}) — 사유: 쿠션만 가능한 템플릿(조립 폴더 없음) / 쉘 템플릿에는 쿠션 바디가 없습니다 / 쉘 두께 값이 있는 템플릿은 조립 입력만 / 준비된 입력은 starter로 정해집니다 / HyperStudy 최적화는 입력 종류를 고를 수 없습니다 |
| `TEMPLATE_NOT_CONFIGURED` | 409(기존) | 관리자 설정 필요: commands.paicad_cushion_write |
| `INPUT_CUSHION_RESPONSES` | 경고·note | 쿠션 입력은 쿠션 메시의 예측 결과만 있습니다 — 제품(조립) 부품 기준 응답은 비거나 실패할 수 있습니다 |
| `CUSHION_PART_DEF_MISSING` | 경고(작업) | 쿠션 부품 정의(PART·PROP·MAT) 일부를 조립 폴더에서 찾지 못했습니다: {이름} |

- 기존 "조립 폴더가 없는 템플릿(메시 단독)입니다 — 조립 체인으로 예측할 수 없습니다"(워커 `INPUT_INVALID`)는 API 검증(`INPUT_KIND_UNSUPPORTED`)이 먼저 막고, 워커 문구는 방어용으로 남긴다.

## 7. Native 변수 출처·기준 쿠션 메시

| 출처 | 진입 | 변수·범위 |
|---|---|---|
| (a) 데이터 생성 세트에서 가져오기 | ④ "① 결과로 만들기"(현행 from-train, `param_set_native_train`) | 세트 정의 = DOE 스냅숏(리비전 0) → ④ 상세·⑥·④ 일괄에서 native-vars로 독립 편집(P1) |
| (b) 최적화에서 STEP으로 새로 | ⑥ 템플릿 고르기 옆 링크 **"새 Native 템플릿(STEP)"** → ④ 세트 등록 화면(Native, 업로드 탭 "내 PC에서 올리기 \| 서버 경로" 재사용)으로 이동, 등록 성공 후 ⑥으로 돌아오면 그 세트 선택(쿼리 `?return=surrogate&param_set_id=`) | 등록 정의(피처 기본 범위) → native-vars 편집. 새 API 없음 |

- 쿠션 입력에 필요한 기준 쿠션 메시 = 세트 `radioss_assem/{mesh_include_name}`(+ `RENUM_INIT.csv`·starter·조립 나머지). Native 등록 필수 파일과 같아 **추가 업로드·추가 등록 규칙 없음**, 기존 Native 세트(solid)도 재등록 없이 쿠션 입력 가능. SimLab `EPS_mesh*.rad`는 쓰지 않는다(SimLab 번호 체계라 모핑 include와 ID가 다름, 등록 사본에서도 제외됨).
- 조립 폴더 없이 쿠션 STEP + 쿠션 메시만으로 Native 템플릿을 만드는 것은 비범위(tag·tie·간섭 검사가 조립 폴더를 씀) — 후속 후보.

## 8. FEM 검증과의 관계

- 쿠션 실행 = 출처의 `template_kind`가 `mesh_only` → 기존 mesh_only 규칙 그대로: reuse 불가(`INPUT_MESH_ONLY`), 재조립 가능, `auto_isolate_cushion`(메시 include `/PART` id 자동 컨투어 대상), 경고 `FEM_RESPONSE_WHOLE_MODEL`. Native 쿠션 실행은 모핑 include(`P/geom/{mesh_include_name}` 또는 `run__N/m_2/{mesh_include_name}`)를 재조립에 쓰므로 메시 변환 명령 불필요(기존 `mesh_native` 경로, `fem_assembly.mesh_source_rel` 무변경).
- 새 조립 원본 `assembly.kind: "template"`: 출처 템플릿의 `radioss_assem/`(`ps.assem_rel`). 조립 가능 템플릿의 쿠션 실행에서 **기본값**(이전 기본 "최근 READY ① DOE"보다 우선 — 조립 입력 실행과 같은 조립이 보장됨). mesh_only 템플릿은 `assem_rel`이 없어 기존 기본(① DOE) 유지. 화면 라벨 "템플릿 조립 폴더". `ASSEM_KIND`에 `TEMPLATE` 추가.
- 쿠션 실행을 FEM 검증에서 막지 않는 이유: 기존 mesh_only 템플릿 검증이 이미 이 경로로 동작한다(비활성화하면 회귀). 막기를 원하면 사용자 확인 Q1(§13).

## 9. P3 — 데이터 생성·학습은 조립만(표시)

- ① 학습 데이터 화면 머리(①-1·①-2·①-3 공통 단계 머리줄)에 배지 "조립 기준"과 aside "데이터 생성·학습은 조립 입력으로만 합니다. 쿠션 입력은 ④ 예측·⑥ 최적화에서 고릅니다". ①-3 조립 폴더 입력은 필수 유지(코드 확인 §2, 문구만 "조립 폴더(필수)").
- ③ 데이터셋 목록·상세: "출처" 열 = `① DOE D-00n(조립)` / `① DOE 여러 개(조립)` / `외부 폴더` (판정 = `dataset_engine._doe_ids`, 응답 `source_doe: {doe_ids, label}|null` 추가 — 계산값, DB 무변경). ③ 모델 상세는 데이터셋 출처를 그대로 표시.
- 쿠션/조립 선택 UI는 ④(단건·일괄)·⑥에만 둔다(①·③ 화면에 선택 없음 — 정적 시험으로 확인).

## 10. UI

- 템플릿 배지(④ 템플릿 목록·상세, ⑥·④ 템플릿 선택 상자): "조립·쿠션"(능력 2개) / "쿠션만" / "조립만"(Native 쉘) — `input_capability`, 사유는 툴팁.
- 입력 종류 선택(④ 단건 실행 카드, ④ 일괄 설정, ⑥ 설정의 템플릿 카드 바로 아래): 라디오 "조립 입력(m_3, 전체 모델)" / "쿠션 입력(쿠션 rad만 — GPU 메모리 적음)". 능력 밖 항목은 비활성 + 사유. 기본 = IK-1. 쿠션 선택 시 `INPUT_CUSHION_RESPONSES` 안내 1줄.
- 실행 목록(④ 단건·일괄, ⑥)에 "입력" 열(조립/쿠션), 상세 머리줄·결과 카드에 같은 배지, 단건 결과에 `predict_input`(파일 수·크기).
- HTML 보고서(⑤·⑥, upload-report §9): 설계 요약 줄에 "입력: 조립|쿠션"(`report_html/common.py`의 기존 `input_kind` 표기 "조립 폴더/메시 단독"을 실행 값 기준 "조립 입력/쿠션 입력"으로).
- Altair 화면도 같은 컴포넌트(엔진 무관). 새 화면 없음, `frontend-dist` 함께 커밋.

## 11. 구현 분해·병렬

| 담당 | 범위 | 순서 |
|---|---|---|
| Impl-Geom | `packages/paicad`: `cushion write`(cli·writers/radioss 재사용·mesh 읽기), 시험, 0.12.0·CHANGELOG | **병렬**(독립) |
| Impl-Backend #1 | core `stage4_predict/input_kind.py`, API `job_params/stage4_predict.py`·`stage4_batch.py`·`surrogate_opt_problem.py`(input → 내부 값·능력 검사·note), 조회(`predict_runs`·`predict_batches_info`·`surrogate_opts_view`·`fem_verify_view`·`reports_common`·`report_html/common.py`), `ParamSet.input_capability`, FEM `assembly.kind: template`(`fem_verify_req`·`fem_verify_plan`·`fem_verify_sources`), ③ `source_doe`, MCP `SUMMARIES`·용어집, openapi, 시험 | #2와 병렬(파일 비중첩) |
| Impl-Backend #2 | 워커 `predict_native.py`(PR_PREP template_kind·MESH 뒤 cushion write)·`predict_inputs.rad_assemble`(native 쿠션 한 파일 복사)·`batch_native.gen_one`(assemble=False + cushion write)·`geometry_native`(명령 키·문구 매핑)·`job_types.step_label`(입력별 라벨)·config `commands.paicad_cushion_write`·fake_paicad `cushion write`, `result.predict_input`, 시험 | paicad CLI 계약만 있으면 fake로 병렬 |
| Impl-Frontend | 배지·입력 선택(④ 단건·일괄·⑥)·목록 열·결과·⑥ "새 Native 템플릿(STEP)" 링크·①"조립 기준"·③ 출처, schema.d.ts, mock, `frontend-dist` | BE openapi 뒤 |

- 병합: paicad → BE#1 → BE#2 → FE(openapi·schema 재생성 순차). v0.2.7의 MCP "AI 연결" 페이지([mcp.md](mcp.md) MR-C3)는 BE#1과 `openapi.json`·`config/schema*`만 겹침 → 같은 릴리스 브랜치에서 순차 rebase.

## 12. 검증(V-IK-*)

- **V-IK-1 하위호환**: `input` 없는 요청 = 변경 전과 같은 `template_kind`·배치·⑥ `input_kind`, 기존 시험 무수정 통과, migration 없음(`MIGRATION_HEAD` = `0021_uploads`).
- **V-IK-2 Altair 쿠션 일원화**: 조립 가능 템플릿 + `input: cushion` 단건 = mesh_only 템플릿 단건과 단계 상태(MESH SKIPPED, RAD_ASSEMBLE 복사만, `commands.rad_assemble` 미실행)·P/INPUT 파일 목록·starter·`<stem>_pred.h3d`가 같다(fake_simlab·fake_edspy).
- **V-IK-3 일괄 쿠션**: Altair·Native 쿠션 배치에서 run마다 m_3 없음, `input_rel` = `run__N/m_1/EPS_mesh_0000.rad`, 하위 PREDICT starter = 그 파일, Native는 m_2에 모핑 include·`cushion/cushion.json` 존재.
- **V-IK-4 예측 입력 검사(GPU 메모리 대리 지표)**: 쿠션 실행의 EDSPY 입력 = P/INPUT 파일 1개(이름 `predict.simlab_mesh_name`), `result.predict_input.bytes` = 그 크기 < 같은 값 조립 실행 P/INPUT 합계, 조립 starter·조립 include가 P/INPUT에 없음, fake_edspy가 받은 `--starter`가 그 파일.
- **V-IK-5 Native 쿠션 rad**: fake/실제 paicad 산출 rad의 `/NODE` ID·좌표 = 모핑 include의 쿠션 노드(제품 노드 0), 요소 ID·연결 = include 쿠션 블록, `/BEGIN` 존재·`/END` 끝, 단일 파일(`#include` 0). paicad 시험(§5.2) 통과, 0.12.0·CHANGELOG.
- **V-IK-6 능력·오류**: mesh_only 템플릿 + assembly → `INPUT_KIND_UNSUPPORTED`, Native 쉘·쉘 두께 값 세트 + cushion → 같은 코드, prepared·레거시 optimize + `input` → 같은 코드, `paicad_cushion_write` null + Native cushion → 409 `TEMPLATE_NOT_CONFIGURED`·`input_capability` 사유.
- **V-IK-7 ⑥**: `input: cushion` → `surrogate_opts.input_kind = mesh_only`, 소유 배치 전부 mesh_only, 추가 검증·재개도 같음, 미리보기 note `INPUT_CUSHION_RESPONSES`.
- **V-IK-8 FEM**: 쿠션 출처 reuse → `INPUT_MESH_ONLY`, 조립 가능 템플릿 쿠션 출처 기본 `assembly.kind = template`(경로 = `ps.assem_rel`), Native 쿠션 rebuild가 모핑 include 사용, mesh_only 템플릿 기존 시험 무수정.
- **V-IK-9 표시**: 배치·⑥·단건 조회 `input`, `ParamSet.input_capability`, HTML 보고서 "입력: 쿠션", MCP 요약 facts `input`, ①·③ 화면에 입력 선택 없음·"조립 기준"·출처 열, 문구 한국어, `frontend-dist` 최신.
- **V-IK-10**: `scripts/test-all` 통과. 현장(e2e-checklist 추가): 실물 ⑥ 쿠션 입력 1회 — GPU 메모리 초과 없이 예측 완료, Native 쿠션 rad로 edspy 예측 성공(예측기 읽기 확인).

## 13. 리스크·미결

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 예측기(edspy)가 Native 쿠션 rad(조립 번호 체계 ID, 조립에서 가져온 PART·PROP·MAT)를 SimLab EPS rad와 다르게 읽을 수 있음 | V-IK-10 현장 확인을 v0.2.7 합격 조건으로, 실패 시 `cushion write` 출력 규칙만 고침(플랫폼 무변경) |
| R2 | ⑥ 목적·제약이 제품(조립) 부품 응답이면 쿠션 입력 결과에 값이 없음 | 경고 `INPUT_CUSHION_RESPONSES`, 응답 추출 실패는 기존 규칙(run 실패·결측) — 사용자 확인 Q2 |
| R3 | 조립 데이터로 학습한 모델의 쿠션 입력 정확도 | 사용자 판단(P2) — 표시만, 차단 없음 |
| R4 | `input_kind`(내부) vs `input`(공개) 두 이름 혼동 | 변환 한 곳(§6.1), 공개 API·화면은 `input`만 새로 씀 |

- **Q1**(사용자 확인 — 차단 아님): 쿠션 실행의 FEM 검증 — 계약 기본은 **재조립으로 허용**(기존 mesh_only 동작, 기본 조립 원본 = 템플릿 조립 폴더). 비활성을 원하면 `FEM_VERIFY` 계획에서 쿠션 출처를 problem으로 막는 한 줄 변경.
- **Q2**(사용자 확인 — 차단 아님): ⑥ 쿠션 입력에서 쓰는 목적·제약 응답이 쿠션 부품 기준인지(제품 가속도 등 조립 부품 응답이면 쿠션 입력으로는 값이 없음). 회신 없으면 경고만.

## 변경 메모

(구현 중 계약과 달라지면 `IK-C1~`로 기록하고 Plan 확인.)
