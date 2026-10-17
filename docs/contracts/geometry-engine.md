# 계약: native 형상 엔진(R1 모핑) — `paicad`

> Plan 2026-10-17. 구현 에이전트는 **이 문서만 보고** 구현한다. 절 번호·용어·원칙은 [platform.md](platform.md)·[phase2.md](phase2.md)·[phase3.md](phase3.md)를 따르고, 이 문서가 바꾸는 규칙은 §2.3에 모았다(이 문서 우선). 기준선: `claude/phase3` a1ac614, migration head `0011_surrogate_final` → 이 문서는 `0012_geometry_engine`부터. 결정 번호는 `GE-n`(phase3 D3-xx와 겹치지 않게).

## 0. 한 줄 요약

NX·SimLab·HyperMesh 없이, 조립 폴더(`radioss_assem/`)의 기준 쿠션 메시(`104_replace_node_elem.inc` 기준본)의 **노드·요소 ID·연결·요소 수를 그대로 두고 `/NODE` 좌표만** 바꿔 형상 파라미터 변경을 반영하는 엔진. CAD 갱신은 공칭 STEP에 OCCT push/pull을 매번 새로 적용하고, 메시는 B-rep 대응(꼭짓점·엣지·면·내부)으로 모핑한 뒤 검사(파라미터 재측정·편차·품질·간섭·tie)를 통과한 샘플만 기존과 같은 이름·형식의 include로 쓴다. 이후 조립(`assemble_into`, m_3)·예측·DOE·②③은 그대로다. 실행은 별도 프로세스 CLI `paicad`(신규 패키지 `packages/paicad`)이고, 플랫폼은 `commands.paicad_*` argv 템플릿으로만 호출한다.

---

## 1. 목적·범위

### 1.1 목적

1. Altair(NX·SimLab·HyperMesh·HyperStudy) 라이선스·실행 없이 ①-1 파라미터 추출, ①-3 학습데이터 입력 생성, ④ 예측(값 입력·일괄 예측), ⑤ 내장 최적화(④ 일괄 예측 체인 사용)를 돌린다.
2. 기존 tie·RBE·접촉 정의가 노드 ID를 참조하므로 **번호를 바꾸지 않는** 방식(R1)으로 조립 rad를 그대로 재사용한다.
3. 기존 파일 계약(`parameter_extracted.xml`, `104_replace_node_elem.inc`, `run__N/{m_1,m_2,m_3}`, `samples.csv`, paramitem)을 지켜 ②③⑤ 코드 변경을 없앤다.

### 1.2 범위(1차 native)

| 항목 | 범위 |
|---|---|
| 요소 | 쿠션 **솔리드 tetra4(`/TETRA4`)만** |
| 위상 | 변화 없음(면·엣지·꼭짓점 수와 인접 관계가 공칭과 같아야 함) |
| 피처 | 두께(평행 대향면, 구배 허용), 포켓 깊이·폭, 리브 두께·높이, 구멍 반경·위치, 필렛 반경, 대칭 그룹 |
| 입력 CAD | 공칭 STEP 1파일(다중 바디, 바디 이름 = component 이름, OCCT XDE) 또는 component별 STEP 파일(파일명 = component 이름) |
| 메시 | 조립 폴더 기준본 include의 쿠션 부분, `RENUM_INIT.csv`(part,node_start,elem_start) 행 = component |
| 출력 | 기준본과 이름·형식이 같은 include(`predict.mesh_include_name`), `/NODE` 블록 좌표 필드만 다름 |
| 플랫폼 연동 | ①-1 추출, ①-3 DOE(LHS), ④ 템플릿 값 입력(A)·일괄 예측(B), ⑤ 내장 최적화(B 경유, 자동) |

### 1.3 비범위

- 쉘(`/SHELL`·`/SH3N`) 형상 모핑 → 단계 5(선택, §11). (`/PROP/TYPE1` 쉘 두께 파라미터는 **범위 포함** — 단계 3S, §11.1.)
- 위상 변화(구멍 추가·삭제, 리브 개수 변경), 번호 재지정(renumber), tetra10·hexa. 재메싱은 1차 비범위(모핑 실패 시 재메시 폴백은 조건부 후속 옵션, §11.2). `/PROP/TYPE9·10·11`(SH_ORTH·COMP·SANDW) 두께는 비범위(`props scan`에서 '미지원' 표시만).
- 제품(TV 세트) 메시 변경 — 제품은 읽기만(간섭 검사용).
- `mesh_only` 템플릿(조립 폴더 없음)의 native — 기준 메시가 없으므로 미지원(§15 Q6). native 세트는 항상 `input_kind = assembly`.
- ⑤ 원본 HyperStudy 최적화(`OPTIMIZE`)의 native — 원본은 tpl·SimLab 고정. native 세트로 생성하면 409(§7.6).
- 엔진 혼용(같은 데이터셋·모델에 altair·native 샘플 섞기) — 금지(§7.7).

### 1.4 원칙(1·2·3차 유지)

외부 명령은 워커에서만 `shell=False` 인자 배열, 경로·명령·허용오차 기본값은 설정에서만, SPDM master·원본 프로젝트 폴더는 읽기만, 산출물은 AI 루트에만, 기존 산출물은 삭제·덮어쓰기 대신 `_backup` 이동, 사용자 문구 한국어, DB에는 경로·상태·수치 요약만. **플랫폼 프로세스(API·워커)는 `paicad`·OCP를 import하지 않는다**(원본 pyd와 같은 격리, 결과 JSON만 읽음).

**기존 Altair 경로 동작 불변(GE-11)**: native는 신규 구현인 별도 모듈(`packages/paicad` + 플랫폼 native 분기)이며, 기존 Altair 경로와 같은 것은 겉(외부 인터페이스 — 출력 파일 이름·폴더 레이아웃·`parameter_extracted.xml` 호환·m_3 조립 입력)뿐이다. altair 세트의 코드 경로·설정 기본값·출력은 바꾸지 않고, 기존 코드 수정은 §16 분기 지점(`engine == "native"`일 때만 다른 경로)으로 한정한다.

---

## 2. 용어·기존 규칙 변경

### 2.1 용어

| 용어 | 뜻 |
|---|---|
| 엔진(engine) | `altair`(기존 SimLab/HyperMesh 체인) \| `native`(이 문서) |
| 공칭 STEP | 파라미터 공칭값 형상. `S/cad/<model>.step`(단일) 또는 `S/cad/parts/<COMP>.step`(component별) |
| 기준본(baseline) | 조립 폴더의 `{predict.mesh_include_name}`(기본 `104_replace_node_elem.inc`). 공칭 형상의 메시 |
| component | `RENUM_INIT.csv` 한 행 = 쿠션 바디 1개 = 기준본 안 요소 ID 구간 |
| 경계 노드 | tetra4 면 중 한 요소에만 속한 면(외피)의 노드 |
| tag | 경계 노드를 B-rep 꼭짓점/엣지/면에, 나머지를 내부로 분류(param_set당 1회) |
| extract | 공칭 STEP에서 피처를 인식해 파라미터·면 서명·기준면·가능 범위·대칭 그룹을 만든다 |
| update | 공칭 STEP에 샘플 값을 push/pull로 적용해 샘플 B-rep을 만든다(샘플마다, 항상 공칭에서 시작) |
| morph | 샘플 B-rep에 맞춰 기준본 노드 좌표를 옮긴다 |
| check | 모핑 메시를 검사하고, 통과하면 include를 쓴다 |
| native 준비본 | tag·extract 결과 폴더 `native/`(§4.2) |
| 면 서명 | 면 식별 정보 `{surface, normal|axis, centroid, area, bbox}` — 위상 순서가 바뀌어도 면을 다시 찾기 위함 |
| 샘플 스킵 | check(또는 update) 실패 → 그 샘플만 실패로 기록하고 나머지는 계속 |

경로 약어: `S` = `<study>/04_params/<param_set_id>/`, `P` = `<study>/04_predict/<job_id>/`, `B` = `<study>/04_batch/B-xxx/`, `X` = `<study>/01_train/extract/<job_id>/`, `D` = `<study>/01_train/doe/<doe_id>/`, `R` = run 폴더(`B/run__N` 또는 `D/approaches/native_lhs/run__N`).

### 2.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| GE-1 | 방식 R1: 기준본의 ID·연결·요소 수 고정, `/NODE` 좌표만 변경, renumber·메셔 불사용 | tie·RBE 유지, 사용자 합의 |
| GE-2 | 별도 프로세스 CLI `paicad`(packages/paicad), 플랫폼은 `commands.paicad_*` 템플릿 + `TEMPLATE_SPECS` placeholder로만 호출, 성공 판정은 출력 파일 이름 | 기존 외부 도구 규약(admin.md §5) 재사용, OCP 격리 |
| GE-3 | 기존 job_type·step 키를 **그대로** 쓰고 핸들러가 엔진으로 분기. 새 job_type은 ④ native 세트 준비 `PARAM_SET_NATIVE` 1개 | ②③⑤·배치 훅·재시도·정리 범주 무수정 |
| GE-4 | 파라미터 계약은 `parameter_extracted.xml` 호환 + `parameter_features.json` + 피처별 PNG | ①-1 TX_PARSE 재사용 |
| GE-5 | 검사 실패는 샘플 스킵 + 사유 코드(`GEOM_*`) 기록 | 사용자 합의 |
| GE-6 | 엔진은 `geometry.engine`(기본값) → `param_sets.engine`·`train_does.engine`·`train_setups.engine`에 생성 시 확정, 데이터셋·모델은 엔진별 분리 | 혼용 금지 |
| GE-7 | 검사 기준 고급 옵션: 기본값 `geometry.defaults`, 세트별 덮어쓰기 `param_sets.geom_options`, 사용값은 run 폴더 `options.json` | 사용자 합의 |
| GE-8 | 두께 기준면 기본 규칙 = 제품·타 바디 접촉면 고정, 반대 면 이동(확정 대기) | 사용자 합의(확정 대기) |
| GE-9 | 정수 반올림(`%3i`) 없음 — native 세트는 tpl이 없어 `tpl_params=[]` → `applied_values = values` | 두께 연속값 |
| GE-10 | 의존: cadquery-ocp(Windows cp312 wheel), numpy, scipy — 오프라인 묶음 포함 | 사용자 합의 |
| GE-11 | native는 신규 별도 모듈, Altair 경로와는 외부 인터페이스만 같음. 기존 코드는 분기 지점만 최소 변경, altair 동작 불변(§1.4·§16) | 사용자 결정 |
| GE-12 | paicad SemVer(0.x) + `CHANGELOG.md`, 출력 `schema_version`은 엔진 버전과 별도, 모든 출력·DB에 사용 버전 기록(§17) | 사용자 결정 |

### 2.3 기존 계약에서 바뀌는 규칙(이 문서 우선)

| 기존 | 변경 |
|---|---|
| admin.md §5.2 argv[0] 실행 파일 placeholder 6개(Altair) | `{paicad}` 추가(설정 `geometry.paicad_path`). **`{paicad}`는 `paicad_*` 키에서만, `paicad_*` 키의 argv[0]은 `{paicad}`만** |
| phase3 §11.4 GEOM_UPDATE·MESH: `commands.geom_update` null → 409/실패 | native 세트는 `geom_update`·`mesh` 템플릿을 보지 않음. 대신 `paicad_update`·`paicad_morph`·`paicad_check` 필요(§7.2) |
| phase3 §11.4 `MESH_INCLUDE_NOT_IN_ASSEM`(경고) | native는 **오류**(`BASELINE_INC_MISSING`, 등록 단계에서) |
| platform.md §15.4 세트 폴더: tpl 필수, `cad/` 정확히 1파일, `cad_extensions` `.prt` | native 세트: tpl 없음, `cad/` = STEP 1개 또는 `cad/parts/*.step` ≥1, 확장자 `geometry.step_extensions`, `native/` 필수(§4.2) |
| `param_sets.tpl_rel NOT NULL` | NULL 허용, CHECK `engine='native' OR tpl_rel IS NOT NULL`(§7.5) |
| phase2 §6.4 TD_DOE_GEN = HyperStudy | native DOE는 플랫폼 LHS + 동시 실행기(§7.3.3) |
| platform.md §7.4 실패 코드 목록 | `GEOM_*` 코드 추가(§6.5) |

---

## 3. 전체 흐름

```text
[param_set·DOE당 1회]                                   [샘플마다]
 공칭 STEP ─┬─ paicad extract ─→ parameter_extracted.xml   values.json
            │                   parameter_features.json        │
            │                   features/*.png                 ▼
            └─ paicad tag ─────→ tag.json + tag_nodes.npz ─→ paicad update ─→ sample.brep, update.json
 기준본 inc ─┘ (RENUM_INIT.csv,                               │
 조립 폴더       조립 폴더=접촉 판정)                           ▼
                                                     paicad morph ─→ morphed.inc, morph.json
                                                              │
                                                              ▼
                                                     paicad check ─→ check.json
                                                              │ PASS일 때만
                                                              ▼
                                                     {mesh_include_name}  ─→ 기존 assemble_into(m_3) ─→ 예측·해석
```

| 플랫폼 기능 | altair(기존) | native |
|---|---|---|
| ①-1 `TD_EXTRACT_PARAMS` | SimLab 추출 → xml | `paicad extract` → xml + features + PNG |
| ①-2 tpl 생성 | 있음 | 없음(409 `ENGINE_NATIVE_NO_TPL`) — 파라미터 표 저장만 |
| ①-3 `TD_DOE_GEN` | HyperStudy(FullFact·FracFact·LHS·Sobol) | 플랫폼 LHS + `paicad tag` 1회 + run마다 `paicad run` |
| ④ 세트 등록 | 동기 API | 작업 `PARAM_SET_NATIVE`(extract·tag 필요) 또는 ①→④ from-train(동기, 준비본 복사) |
| ④ `PREDICT`(A) | TPL_RENDER·GEOM_UPDATE(SimLab)·MESH(HyperMesh) | TPL_RENDER(values.json)·GEOM_UPDATE(update)·MESH(morph+check) |
| ④ `PREDICT_BATCH`(B) | run마다 m_1 SimLab·m_2 HyperMesh·m_3 | run마다 m_1 update·m_2 morph+check·m_3 |
| ⑤ 내장 최적화 | B 경유 | B 경유(자동) |
| ⑤ 원본 최적화 | HyperStudy | 409 `ENGINE_NATIVE_UNSUPPORTED` |

---

## 4. 입출력 파일 계약

모든 JSON은 UTF-8(BOM 없음), `schema_version: 1`, 길이 단위 mm, 각도 deg. paicad·플랫폼이 쓰는 native JSON(보고·준비본·옵션 사용값·`SKIPPED.json`)은 최상위에 `engine: "native"`·`engine_version: "<paicad 버전>"`도 둔다(§17.3 — 아래 예시에서 생략돼도 필수). 플랫폼은 JSON을 `geometry.max_report_bytes`(기본 4 MiB) 이하만 읽고, 넘거나 형식이 틀리면 `INPUT_INVALID`. 좌표·ID는 기준본의 mm-ton-s 그대로(변환 없음).

### 4.1 입력

| 파일 | 위치(native 세트) | 형식·규칙 |
|---|---|---|
| 공칭 STEP(단일) | `S/cad/<model>.step` | AP203/AP214/AP242. 솔리드 바디 ≥1. 바디 이름 = XDE 라벨 이름(`TDataStd_Name`). 확장자 `geometry.step_extensions`(기본 `[".step", ".stp"]`, 대소문자 무시) |
| 공칭 STEP(component별) | `S/cad/parts/<COMP>.step` | 파일마다 솔리드 정확히 1개. 파일명 stem = component 이름. 이때 `S/cad/` 직계에는 STEP을 두지 않음 |
| 바디 대응 덮어쓰기(선택) | `S/cad/body_map.json` | `{"schema_version":1,"map":{"<STEP 바디 이름 또는 파일 stem>":"<RENUM part>"}}` |
| 기준본 | `S/radioss_assem/{predict.mesh_include_name}` | Radioss 고정폭 입력. 쿠션 요소는 `/TETRA4/<part_id>` 블록, 노드는 `/NODE` 블록 |
| 번호 표 | `S/radioss_assem/{predict.renum_csv_name}` | CSV 헤더 `part,node_start,elem_start`(대소문자·공백 무시, BOM 허용), 행 = component. **native 필수**(없으면 `RENUM_CSV_MISSING` 오류) |
| 조립 나머지 | `S/radioss_assem/*.rad, *.inc` | 제품 메시·tie(`/INTER/TYPE2`) 정의. 간섭·tie 검사용으로 읽기만 |
| 샘플 값 | `values.json`(§4.4) | 플랫폼이 작성 |
| 옵션 | `options.json`(§4.9) | 플랫폼이 작성(사용값) |

component 대응 규칙(tag·extract 공통, 순서대로 첫 일치):

1. `body_map.json`의 명시 대응.
2. 바디 이름 == `part`(정확).
3. 대소문자 무시 일치.
4. 정규화 일치: 영숫자 외 문자를 `_`로, 연속 `_` 하나로, 앞뒤 `_` 제거, 대문자.

남는 바디·남는 part가 있으면 `GEOM_BODY_MAP_FAILED`(메시지에 양쪽 목록 최대 10개). 다중 바디 STEP에 이름이 없는 바디(XDE 라벨 없음)가 있으면 같은 코드 + "바디 이름이 없습니다 — component별 STEP 파일 방식(cad/parts/)을 쓰세요".

component의 요소·노드 집합:

- `RENUM_INIT.csv` 행을 `elem_start` 오름차순으로 정렬, 행 k의 요소 ID 구간 = `[elem_start_k, elem_start_{k+1})`(마지막 행은 기준본 최대 요소 ID까지).
- 노드 집합 = 그 구간 요소가 참조하는 노드. 노드 ID가 `[node_start_k, node_start_{k+1})` 밖이면 경고 `RENUM_NODE_RANGE`(오류 아님).
- 구간 요소 중 `/TETRA4`가 아닌 것이 있으면 `GEOM_UNSUPPORTED_ELEMENT`.
- 두 component가 노드를 공유하면(등각 메시) 모핑 때 한 연결 성분으로 함께 푼다(§6.3).

### 4.2 native 준비본 `native/`

| 경로 | 생성 | 내용 |
|---|---|---|
| `native/prep.json` | 플랫폼(준비 step 끝) | `{schema_version, engine:"native", engine_version, ocp_version, inputs:{step:{rel,sha256}|{parts:[{rel,sha256}]}, baseline_inc:{name,sha256}, renum_csv:{name,sha256}, body_map:{rel,sha256}|null}, tag_options_sha256, created_at, job_id}` |
| `native/extract/parameter_extracted.xml` | `paicad extract` | §4.3 |
| `native/extract/parameter_features.json` | `paicad extract` | §4.3 |
| `native/extract/features/<NAME>.png` | `paicad extract` | 피처별 하이라이트(§4.3) |
| `native/tag/tag.json`, `native/tag/tag_nodes.npz` | `paicad tag` | §4.5 |
| `native/options.json` | 플랫폼 | 준비에 쓴 tag 옵션(§4.9의 `tag` 절) |

준비본 유효성(PREDICT·BATCH·DOE의 준비 step이 검사): `prep.json`의 입력 sha256이 현재 파일과 같고, 현재 유효 옵션의 `tag` 절 sha256 == `tag_options_sha256`. 다르면 작업 생성 409 `GEOM_PREP_STALE`(워커 재검사 실패는 `INPUT_CHANGED`).

### 4.3 extract 출력

`parameter_extracted.xml` — 원본 SimLab 형식 호환(phase2 §6.2 TX_PARSE·`train_params.read_extracted_xml`이 그대로 읽음):

```xml
<?xml version="1.0" encoding="utf-8"?>
<Root>
  <Model Name="model.step">
    <Parameter><Name>CUSH_L_THK_1</Name><Value>12.5 mm</Value></Parameter>
    <Parameter><Name>CUSH_L_POCKET_D_1</Name><Value>8 mm</Value></Parameter>
  </Model>
</Root>
```

- 파라미터 = 대칭 그룹 대표만(구성원은 같은 값을 따름). 순서 = component(RENUM 행 순) → 피처 종류(§6.2 표 순) → 면 서명 centroid(x,y,z 사전순).
- 이름 = `<COMP>_<TYPE>_<k>`(정규화 component 이름, k는 같은 component·종류 안 1부터). 64자 넘으면 component 부분을 줄이고 `~<4자 해시>`. 규칙 `^[A-Za-z_][A-Za-z0-9_]{0,63}$`(`NAME_RE`) 위반이 없게 만든다.
- 값은 `repr(float)` 최단 표기 + `" mm"`(각도 피처는 없음 — 필렛은 반경 mm).
- DOCTYPE·ENTITY 없음.

`parameter_features.json`:

```json
{
  "schema_version": 1,
  "engine": "native",
  "engine_version": "0.1.0",
  "unit_system": "mm-ton-s",
  "cad": {"mode": "single", "files": [{"rel": "cad/model.step", "sha256": "…"}], "body_map": "xde"},
  "bodies": [
    {"body": "CUSH_L", "part": "CUSH_L", "renum_row": 1, "volume": 812345.2, "bbox": [0, 0, 0, 120, 80, 60], "faces": 42, "edges": 120, "vertices": 80}
  ],
  "features": [
    {
      "name": "CUSH_L_THK_1",
      "type": "THICKNESS",
      "body": "CUSH_L",
      "nominal": 12.5,
      "unit": "mm",
      "range": {"min": 11.875, "max": 13.125, "ratio": 0.05},
      "feasible": {"min": 6.2, "max": 18.0, "limited_by": "CUSH_L_POCKET_D_1"},
      "faces": {"moving": ["F12"], "fixed": ["F7"]},
      "face_signatures": {
        "F12": {"surface": "PLANE", "normal": [0, 0, 1], "centroid": [60, 40, 12.5], "area": 9600.0, "bbox": [0, 0, 12.5, 120, 80, 12.5]},
        "F7":  {"surface": "PLANE", "normal": [0, 0, -1], "centroid": [60, 40, 0], "area": 9600.0, "bbox": [0, 0, 0, 120, 80, 0]}
      },
      "draft_deg": 0.0,
      "ref": {"rule": "contact_fixed", "face": "F7", "reason": "제품 접촉면", "confirmed": false},
      "measure": {"method": "face_distance", "faces": ["F12", "F7"]},
      "group": "G1",
      "png": "features/CUSH_L_THK_1.png"
    }
  ],
  "groups": [
    {"id": "G1", "kind": "MIRROR", "plane": {"point": [200, 0, 0], "normal": [1, 0, 0]}, "parameter": "CUSH_L_THK_1", "members": ["CUSH_L_THK_1", "CUSH_R_THK_1"]}
  ],
  "warnings": [{"code": "REF_AMBIGUOUS", "feature": "CUSH_L_RIB_T_2", "message": "두 면이 모두 접촉면이라 기준면을 면적 큰 쪽으로 정했습니다"}]
}
```

| 필드 | 규칙 |
|---|---|
| `F<k>` | 바디별 `TopExp::MapShapes(FACE)` 순서 1-기반. 같은 STEP·같은 OCP 버전이면 안정. 다르면 `face_signatures`로 다시 찾는다 |
| `range` | 기본 = 공칭 × (1 ∓ `train_data.param_default_range_ratio`)(기본 0.05, 기존과 같음). `feasible` 안으로 자름 |
| `feasible` | 위상 불변을 보장하는 대략 범위(인접 피처·벽 두께 > 0 기준, 보수적). 정보용. 샘플 값이 밖이면 update가 시도는 하되 실패 가능 |
| `ref.confirmed` | 기준면 규칙 확정 전에는 false(§15 Q2). 화면에 "기준면 자동" 표시 |
| `png` | 800×600 PNG, 바디 회색 반투명 + 이동 면 주황 + 고정 면 파랑 + 치수선. 오프스크린 렌더 실패 시 PNG 없음 + 경고 `PNG_RENDER_FAILED`(extract는 성공) |
| `measure` | check (a) 재측정 방법. `face_distance`(평행면 평균 거리), `hole_radius`(원통 피팅), `hole_center`(원통 축 투영), `pocket_depth`, `pocket_width`, `rib_height`, `fillet_radius` |

### 4.4 `values.json`(플랫폼 → paicad)

```json
{"schema_version": 1, "values": {"CUSH_L_THK_1": 12.9, "CUSH_L_POCKET_D_1": 7.6}, "source": {"kind": "predict|batch|doe", "id": "…", "doe_no": 3}}
```

- 키 집합 = `parameter_features.json`의 그룹 대표 + 그룹 없는 피처 이름 전부. 빠진 이름은 공칭값. 모르는 이름은 `GEOM_INPUT_INVALID`.
- 플랫폼은 값을 반올림하지 않는다(GE-9).

### 4.5 tag 출력

`tag.json`:

```json
{
  "schema_version": 1, "status": "OK", "code": null, "message": null,
  "baseline_inc": {"name": "104_replace_node_elem.inc", "sha256": "…"},
  "tolerance": {"abs_mm": 0.05, "rel": 1.0e-4},
  "match_ratio": 0.9993,
  "parts": [
    {"part": "CUSH_L", "body": "CUSH_L", "elem_range": [3000001, 3041230], "nodes": 9120, "boundary_nodes": 4210,
     "classified": {"vertex": 80, "edge": 610, "face": 3518, "interior": 4910, "unmatched": 2},
     "dist_mm": {"mean": 0.003, "max": 0.041}, "tol_mm": 0.05}
  ],
  "contacts": [{"part": "CUSH_L", "face": "F7", "with": "PRODUCT", "nodes": 412}, {"part": "CUSH_L", "face": "F31", "with": "CUSH_R:F9", "nodes": 60}],
  "files": {"nodes": "tag_nodes.npz"},
  "warnings": []
}
```

`tag_nodes.npz`(numpy, paicad만 읽음): `node_id:int64[n]`, `part:int32[n]`(parts 인덱스), `kind:int8[n]`(0 내부, 1 면, 2 엣지, 3 꼭짓점, -1 미일치), `entity:int32[n]`(면 F·엣지 E·꼭짓점 V 번호, 내부 -1), `uv:float64[n,2]`(면: 정규화 (u,v) ∈ [0,1]², 엣지: (t,0) 호 길이 정규화, 그 밖 0), `dist:float64[n]`.

### 4.6 update 출력(`--out-dir`)

| 파일 | 내용 |
|---|---|
| `sample.brep` | OCCT 네이티브 BRep(compound, 바디 순서 = `bodies` 순서) |
| `face_map.json` | 바디별 공칭 면·엣지·꼭짓점 → 샘플 번호 `{"CUSH_L": {"F": {"1": 1, …}, "E": {…}, "V": {…}}}` |
| `update.json` | 아래 |
| `paicad.log` | 실행 로그 |

```json
{"schema_version": 1, "status": "OK", "code": null, "category": null, "message": null,
 "values": {"CUSH_L_THK_1": 12.9},
 "applied": [{"name": "CUSH_L_THK_1", "nominal": 12.5, "value": 12.9, "delta": 0.4, "op": "PRISM", "moved": ["F12"], "fixed": ["F7"], "ref_rule": "contact_fixed", "members": ["CUSH_R_THK_1"]}],
 "topology": {"same_as_nominal": true, "counts": {"CUSH_L": {"nominal": [42, 120, 80], "sample": [42, 120, 80]}}},
 "elapsed_s": 1.8}
```

실패 시 `status: "FAIL"`, `code`·`category`·`message`(영문 기술 메시지, §18.4) 채움, `sample.brep`·`face_map.json` 없음.

### 4.7 morph 출력(`--out-dir`)

| 파일 | 내용 |
|---|---|
| `morphed.inc` | 기준본과 바이트 단위로 같고 `/NODE` 좌표 필드만 다른 후보 include(§6.4 쓰기 규칙) |
| `morph.json` | `{schema_version, status, code, category, message, max_disp_mm, parts:[{part, moved_nodes, max_disp_mm, solver:{method, iterations, rel_residual}}], elapsed_s}` |

### 4.8 check 출력

| 파일 | 내용 |
|---|---|
| `check.json`(`--out-dir`) | 아래 |
| `--out-inc` 경로 | PASS일 때만 `morphed.inc` 내용을 이 이름으로 씀(= `{mesh_include_name}`). FAIL이면 만들지 않음 |

```json
{
  "schema_version": 1, "status": "PASS", "code": null, "category": null, "message": null,
  "checks": {
    "param":        {"status": "PASS", "items": [{"name": "CUSH_L_THK_1", "input": 12.9, "measured": 12.897, "err": 0.003, "tol": 0.129}]},
    "deviation":    {"status": "PASS", "max_mm": 0.012, "tol_mm": 0.05, "worst_node": 3001234},
    "quality":      {"status": "PASS", "inverted": 0, "min_scaled_jacobian": 0.31, "baseline_min_scaled_jacobian": 0.33,
                     "max_aspect": 6.2, "baseline_max_aspect": 5.9, "min_edge_mm": 0.82, "baseline_min_edge_mm": 0.90, "dt_ratio": 0.91},
    "interference": {"status": "PASS", "body_body_max_mm": 0.0, "product_max_mm": 0.0, "pairs": []},
    "tie":          {"status": "PASS", "interfaces": [{"id": 12, "dsearch_mm": 1.0, "max_gap_mm": 0.21, "failed_nodes": 0}]}
  },
  "options": {"…": "사용값"},
  "out_inc": "104_replace_node_elem.inc",
  "elapsed_s": 6.4
}
```

`status`: 항목별 `PASS|FAIL|NOT_EVALUATED`. 최상위는 FAIL 항목이 하나라도 있으면 FAIL, `code`는 §6.5 우선순위의 첫 실패.

### 4.9 옵션 `options.json`(geom_options)

```json
{
  "schema_version": 1,
  "tag":          {"tol_abs_mm": 0.05, "tol_rel": 1.0e-4, "min_match_ratio": 0.98, "contact_mm": 0.1, "contact_min_ratio": 0.2},
  "morph":        {"poisson": 0.3, "solver_rtol": 1.0e-8, "solver_maxiter": 5000},
  "quality":      {"min_scaled_jacobian": 0.2, "max_aspect": 10.0, "min_edge_ratio": 0.8, "relative_to_baseline": true},
  "deviation":    {"boundary_max_mm": 0.05, "param_abs_mm": 0.05, "param_rel": 0.01},
  "interference": {"body_mm": 0.01, "product_mm": 0.05},
  "tie":          {"default_dsearch_mm": null, "required": true},
  "thickness_ref": "contact_fixed"
}
```

- 유효 옵션 = `geometry.defaults`(설정) ← `param_sets.geom_options`(세트 덮어쓰기, 부분 객체) 깊은 병합. 범위: 허용오차 > 0 유한, `0 < min_scaled_jacobian ≤ 1`, `max_aspect ≥ 1`, `0 < min_edge_ratio ≤ 1`, `0 ≤ poisson < 0.5`, `thickness_ref ∈ {contact_fixed, larger_area_fixed}`. 위반은 API 422 `GEOM_OPTIONS_INVALID`(problems 목록).
- 고급 옵션 UI에서 바꾸는 절 = `quality`·`interference`·`deviation`(+`tie.required`). `tag` 절 변경은 준비본 재생성 필요(§7.4).
- 작업이 쓴 유효 옵션은 `P/geom/options.json`, `R/options.json`, `D/native/options_run.json`에 기록(사용값 고정). 이 세 파일에는 최상위 `engine`·`engine_version`(작업 준비 step에서 `paicad version --json`으로 읽은 값)을 함께 쓴다 — 병합·범위 검사 대상 아님, `param_sets.geom_options` 입력에 오면 422 `GEOM_OPTIONS_INVALID`.

---

## 5. `paicad` CLI 명세

### 5.1 패키지

| 항목 | 값 |
|---|---|
| 위치 | `packages/paicad/`(`pyproject.toml`, `src/paicad/`, `tests/`, `CHANGELOG.md`) — `packages/simdash_adapters`와 같은 배치 |
| 배포 이름·버전 | `paicad==0.1.0`(루트 `pyproject.toml` 의존에 정확 고정, `deploy/requirements.local.lock`). 버전 단일 출처·올림 규칙은 §17 |
| 진입점 | `[project.scripts] paicad = "paicad.cli:main"`(Windows `Scripts\paicad.exe`) |
| 의존 | `cadquery-ocp`(cp312 win_amd64 wheel이 있는 버전으로 Impl이 고정, 7.7 이상), `numpy>=2,<3`, `scipy>=1.13,<2`(기존 lock 버전 공유). 그 밖 금지 |
| 모듈 경계 | `paicad.brep`(OCP 사용 — STEP 읽기·XDE·피처·push/pull·투영·렌더), `paicad.mesh`(Radioss 읽기·쓰기, numpy만), `paicad.morph`·`paicad.check`(numpy·scipy + `brep` 인터페이스), `paicad.cli`. `mesh`·`morph`·`check`는 B-rep을 `SurfaceLike`/`CurveLike` 프로토콜(`eval(u,v)`, `project(p)`, `classify(u,v)`, `bounds()`)로만 쓴다 → 해석적 평면·원통 구현으로 OCP 없이 시험 가능 |
| 플랫폼 import | 금지(physicsai_core·api·worker 어디서도). 플랫폼은 결과 JSON만 읽는다(`physicsai_core/geometry/reports.py`, 표준 라이브러리만). 독립성 규칙 전체는 §18 |

### 5.2 공통 규약

- 인자는 `--name value` 두 토큰(`=` 사용 안 함 — `.bat` 경유 시 구분자 문제 회피). 경로는 절대경로, 공백·cmd 메타문자 없음(플랫폼 `check_value`가 보장).
- **쓰기**: `--out-dir`(및 `--out-inc`)에만. `--out-dir`이 없으면 만든다. **출력 파일이 이미 있으면 덮어쓰지 않고 종료코드 3 `GEOM_OUTPUT_EXISTS`**(플랫폼이 실행 전 `outputs_to_backup`으로 `_backup` 이동). 삭제 호출 없음. 입력은 읽기 전용으로 연다.
- 임시 파일은 `--out-dir/.tmp_<pid>/` 안에서 만들고 끝에 같은 볼륨 `os.replace`로 최종 이름. 실패 시 임시 폴더는 남긴다(플랫폼 정리 범주가 처리).
- stdout: 진행 줄 `PAICAD PROGRESS <0~100> <영문 메시지>`(§18.4, 화면 한국어 표시는 플랫폼 매핑), 마지막 줄 `PAICAD RESULT <status> <code|-> <보고 JSON 파일 이름>`. stderr: 경고·traceback. 모든 출력 UTF-8.
- 로그: `--out-dir/paicad.log`(stdout·stderr 사본 + 입력 sha256·버전·옵션).
- 스레드: `--threads N`(기본 환경변수 `PAICAD_THREADS`, 없으면 4). numpy/BLAS 스레드는 플랫폼이 `geometry.env`로 지정.
- 결정성: 같은 입력·옵션·버전이면 같은 출력(난수 없음, 정렬 고정).
- 시간 제한은 플랫폼(`geometry.timeout_s`)이 건다. paicad는 SIGINT/CTRL_BREAK에 130으로 끝난다.

### 5.3 하위 명령

| 명령 | 인자(필수 **굵게**) | 출력(성공 판정 파일) |
|---|---|---|
| `paicad version` | `--json` | stdout JSON `{"paicad":"0.1.0","ocp":"7.x","numpy":"…","scipy":"…","python":"3.12.x"}` |
| `paicad --version` | (최상위 옵션) | stdout 한 줄 `paicad 0.1.0`, 종료코드 0(§17.1) |
| `paicad extract` | **`--cad`**(STEP 파일 또는 `cad/parts` 폴더), **`--out-dir`**, `--body-map`, `--renum-csv`(있으면 component 순서·대응 검사), `--options`, `--no-png` | `parameter_extracted.xml`, `parameter_features.json`(성공 = 둘 다 존재 + xml 파라미터 ≥1), `features/*.png` |
| `paicad tag` | **`--cad`**, **`--features`**, **`--baseline-inc`**, **`--renum-csv`**, **`--assem-dir`**, **`--out-dir`**, `--body-map`, `--options` | `tag.json`(`status: OK`), `tag_nodes.npz` |
| `paicad update` | **`--cad`**, **`--features`**, **`--values`**, **`--out-dir`**, `--tag-dir`(기준면 접촉 정보), `--body-map`, `--options` | `update.json`(`status: OK`), `sample.brep`, `face_map.json` |
| `paicad morph` | **`--baseline-inc`**, **`--tag-dir`**, **`--features`**, **`--update-dir`**, **`--out-dir`**, `--options` | `morph.json`(`status: OK`), `morphed.inc` |
| `paicad check` | **`--baseline-inc`**, **`--morph-dir`**, **`--update-dir`**, **`--tag-dir`**, **`--features`**, **`--values`**, **`--assem-dir`**, **`--renum-csv`**, **`--out-dir`**, **`--out-inc`**, `--options` | `check.json`(`status: PASS`) + `--out-inc` 파일 |
| `paicad props scan` (단계 3S, §11.1) | **`--assem-dir`**, **`--out-dir`**, `--options` | `props.json`(PROP 목록, 성공 = 존재) |
| `paicad props apply` (단계 3S) | **`--assem-dir`**(run 폴더 INPUT 복사본), **`--values`**, **`--props`**(`props.json`), **`--out-dir`** | `props_apply.json`(`status: OK`) + 수정된 PROP 정의 파일 사본(원본 불변) |
| `paicad run` | update·morph·check 인자 합집합 + **`--update-dir`**, **`--morph-dir`**, **`--check-dir`**(각 단계 `--out-dir`), **`--out-inc`** | 각 단계 출력 + `--out-inc`. 한 단계가 FAIL이면 뒤 단계는 실행하지 않음(보고 파일 없음) |

`--features`·`--tag-dir`는 native 준비본의 파일·폴더. `--assem-dir`은 기준본이 들어 있는 조립 폴더(기준본 자신은 제품 메시 수집에서 제외).

### 5.4 종료코드

| 코드 | 뜻 | 보고 JSON |
|---|---|---|
| 0 | 성공(PASS/OK) | 있음 |
| 2 | 인자 오류(argparse) | 없음 |
| 3 | 입력 오류 `GEOM_INPUT_INVALID`·`GEOM_OUTPUT_EXISTS`·`RENUM_CSV_MISSING` | 가능하면 있음 |
| 10 | CAD 생성 불가(update FAIL) | `update.json` |
| 11 | 검사 실패(check FAIL) 또는 모핑 실패(morph FAIL) | `check.json`/`morph.json` |
| 12 | tag 실패 | `tag.json` |
| 13 | extract 결과 없음 `GEOM_EXTRACT_EMPTY` | `parameter_features.json`(features 빈 배열) |
| 20 | 내부 오류 `GEOM_INTERNAL`(예외 traceback은 stderr·로그) | 가능하면 있음 |
| 130 | 중단 | 없음 |

플랫폼 판정은 **출력 파일 우선**(§7.2): 성공 파일이 있고 보고 `status`가 OK/PASS면 성공(종료코드 ≠0이면 경고 `EXIT_NONZERO_IGNORED`). 보고 JSON이 FAIL이면 그 `code`로 실패. 보고 JSON이 없으면 종료코드 ≠0 → `EXIT_NONZERO`, 0 → `OUTPUT_MISSING`.

---

## 6. 알고리즘 계약

허용오차 기본값은 모두 §4.9 `options.json`(설정 `geometry.defaults`). `L_body` = 바디 bbox 대각선, `tol = max(tol_abs_mm, tol_rel · L_body)`.

### 6.1 tag

입력: 공칭 B-rep, `parameter_features.json`(바디 대응), 기준본, RENUM 표, 조립 폴더. 출력: §4.5.

1. 기준본에서 component별 tetra4 요소·노드를 만든다(§4.1). 외피 삼각형 = 요소 면 중 1회만 나오는 면(노드 정렬 키로 계수). 경계 노드 = 외피 삼각형의 노드.
2. 경계 노드마다 해당 바디에 대해 거리 계산(OCP `BRepExtrema_DistShapeShape` 또는 면별 `GeomAPI_ProjectPointOnSurf` + 분류기, 바디 bbox + tol 밖 면은 건너뜀):
   - 꼭짓점까지 ≤ tol → `kind=3`(가장 가까운 꼭짓점).
   - 아니면 엣지까지 ≤ tol → `kind=2`, `t` = 호 길이 정규화 매개변수.
   - 아니면 면까지 ≤ tol이고 투영점이 면 안(`BRepClass_FaceClassifier` IN/ON) → `kind=1`, `uv` = 면 매개변수 영역(`BRepTools::UVBounds`)으로 정규화.
   - 아니면 `kind=-1`(미일치).
3. 일관성: 외피 삼각형의 세 노드가 서로 다른 면(kind=1)에 붙으면 그 삼각형 노드를 공통 엣지로 재분류 시도. 꼭짓점 V마다 kind=3 노드가 정확히 1개가 아니면 가장 가까운 노드 1개만 kind=3, 나머지는 엣지로.
4. `match_ratio` = (경계 노드 − 미일치) / 경계 노드. **`match_ratio < min_match_ratio`(기본 0.98) → `GEOM_BASELINE_MISMATCH`**(메시지에 평균·최대 거리와 "공칭 STEP과 기준 메시 좌표가 맞지 않습니다 — 원점·단위·형상 차이 확인"). 자동 정렬(강체 맞춤)은 하지 않는다(§15 Q1). 미일치 노드가 남아도 비율을 넘으면 OK + 경고 `TAG_UNMATCHED`, 미일치 노드는 morph에서 이웃 경계 변위를 받는 "자유 경계"로 취급(내부와 같게 풀림).
5. 내부 노드 `kind=0`.
6. 접촉(`contacts`): 면 F의 kind=1 노드 중 제품 외피(조립 폴더 나머지 메시, §6.5 수집 규칙) 또는 다른 쿠션 바디 면까지 거리 ≤ `tag.contact_mm`(기본 0.1)인 노드가 그 면 노드의 `tag.contact_min_ratio`(기본 0.2) 이상 → 접촉면. 기준면 규칙(§6.2)과 간섭 판정(공칭 접촉 면 쌍 구분)에 쓴다.

실패 코드: `GEOM_BODY_MAP_FAILED`, `GEOM_UNSUPPORTED_ELEMENT`, `GEOM_BASELINE_MISMATCH`, `GEOM_TAG_FAILED`(그 밖).

### 6.2 extract(피처 인식)

| 종류(`type`) | 인식 규칙 | 기본 이동(push/pull) | 재측정(`measure`) |
|---|---|---|---|
| `THICKNESS` | 평면 쌍, 법선 반대(각 ≤ 180°±`draft_max_deg` 기본 3°), 서로 투영 겹침 ≥ 50%, 거리 = 공칭 | 비고정 면을 법선 방향 Δ | 두 면 노드 평균 거리 |
| `POCKET_DEPTH` | 오목 루프(내부 벽 면들 + 바닥 평면), 바닥이 입구 평면과 평행 | 바닥 면 Δ | 바닥 ↔ 입구 평면 거리 |
| `POCKET_WIDTH` | 같은 포켓의 대향 벽 평면 쌍 | 한쪽 벽(기준면 규칙) Δ | 벽 거리 |
| `RIB_THICKNESS` | 볼록 돌출, 대향 측면 평면 쌍 거리 < 높이 | 한쪽 측면 Δ | 측면 거리 |
| `RIB_HEIGHT` | 같은 리브 윗면 ↔ 밑 평면 | 윗면 Δ | 윗면 ↔ 기준 평면 거리 |
| `HOLE_RADIUS` | 원통 면(닫힌 360°), 축이 관통 방향 | 원통 반경 변경(오프셋) | 원통 피팅 반경 |
| `HOLE_POS_U`/`HOLE_POS_V` | 원통 축의 위치(기준 = 바디 bbox 최소 모서리, 축에 수직인 두 주축) | 원통·인접 면 평행 이동 | 축 위치 |
| `FILLET_RADIUS` | 원통/토러스 블렌드 면(접선 연속, 각 < 180°) | 반경 재블렌드(`BRepFilletAPI_MakeFillet` 재적용) | 피팅 반경 |

- **대칭 그룹**: 같은 종류 피처 쌍이 바디 bbox 중심을 지나는 x·y·z 평면 또는 바디 간 공통 평면에 대해 면 서명이 거울(centroid 거울 거리 ≤ tol, 면적 차 ≤ 1%, 공칭 차 ≤ tol)이면 `MIRROR` 그룹. 여러 바디(좌·우 쿠션)에 걸칠 수 있음. 대표 = 이름 정렬 첫째.
- **기준면 규칙**(`thickness_ref`, 확정 대기 GE-8): `contact_fixed` = 쌍 중 접촉면(제품·타 바디, `tag.json.contacts`)인 면 고정, 반대 면 이동. 둘 다 접촉이거나 둘 다 아니면 면적 큰 면 고정 + 경고 `REF_AMBIGUOUS`. `larger_area_fixed` = 항상 면적 큰 면 고정. extract는 tag보다 먼저 돌아 접촉 정보가 없으므로 features.json의 `ref`·`faces`는 `larger_area_fixed` 기준 잠정값(`ref.confirmed=false`)이다. **update는 `--tag-dir`가 주어지면 `contact_fixed` 규칙으로 기준면을 다시 고른다**(features.json은 바꾸지 않음, 실제 사용 기준면은 `update.json.applied[].moved`·`fixed`에 기록, check (a) 재측정은 방향과 무관). `--tag-dir` 없이 `contact_fixed`면 `larger_area_fixed`로 대체 + 경고 `REF_NO_CONTACT_INFO`.
- `feasible`: 이동 면이 다른 면과 만나기 전 최대 Δ(인접 면 거리, 벽 두께 > 0.5 mm)를 보수적으로 추정.
- 인식 실패한 면은 무시(피처 없음). 피처가 0개면 `GEOM_EXTRACT_EMPTY`.

### 6.3 update

1. 매 샘플 **공칭 B-rep에서 시작**(누적 금지). 바디별로 피처를 정해진 순서(§4.3 이름 순서, 그룹 구성원 포함)로 적용.
2. 이동 Δ = 값 − 공칭(그룹 구성원은 대표 값). 평면 이동은 `BRepFeat_MakePrism`(fuse/cut 모드는 Δ 부호로) 또는 동등한 면 오프셋(`BRepOffsetAPI_MakeOffsetShape` 면 지정), 원통 반경·필렛은 해당 OCCT 연산. 연산마다 `BRepBuilderAPI_MakeShape::Modified/Generated` 이력으로 face_map을 갱신.
3. 결과 검사: `BRepCheck_Analyzer` 유효, 바디마다 솔리드 1개, 면·엣지·꼭짓점 수 = 공칭, 공칭 면마다 대응 샘플 면 1개(이력 우선, 실패 시 면 서명: 같은 surface 종류, 법선 각 ≤ 1°, centroid 거리 ≤ |Δ|+tol). 위반 → `GEOM_TOPOLOGY_CHANGED`(category `CAD_FAILED`). OCCT 예외·무효 형상 → `GEOM_CAD_FAILED`.
4. 바디-바디 형상 간섭(공칭에서 접촉이 아니던 면이 겹침)은 여기서 보지 않는다 — check (d)에서 메시로 판정.

### 6.4 morph

1. 경계 노드 목표 위치:
   - 꼭짓점(kind 3): 대응 샘플 꼭짓점 좌표.
   - 엣지(kind 2): 대응 샘플 엣지에서 같은 호 길이 정규화 `t` 위치.
   - 면(kind 1): 대응 샘플 면에서 정규화 `(u,v)` → 매개변수 영역으로 되돌려 평가. **평가점이 면 밖(분류기 OUT)이거나 면의 내부 와이어(구멍 경계)가 이동한 면이면 대체 규칙**: 그 면의 노드는 면 경계(엣지·꼭짓점) 노드 변위를 경계조건으로 면 위 외피 삼각망에서 조화(라플라스, cotangent 가중) 보간 → 결과를 샘플 면에 투영. 투영 실패 → `GEOM_MORPH_FAILED`.
   - 미일치(kind -1): 자유(내부처럼 풂).
2. 내부: 연결 성분마다 선형 정적 탄성 1회. tetra4 상수 변형률 요소, 요소 강성 `E_e = E0 · V̄ / V_e`(작은 요소일수록 단단 → 국부 찌그러짐 방지), `ν = morph.poisson`(0.3). 경계 노드 변위 고정(Dirichlet), 하중 0. 해법: `scipy.sparse.linalg.cg`(Jacobi 전처리, `rtol=solver_rtol`, `maxiter=solver_maxiter`), 미수렴이면 자유도 ≤ 300 000이면 `spsolve`로 재시도, 그래도 실패 → `GEOM_MORPH_FAILED`(category QUALITY).
3. 좌표 = 기준본 좌표 + 변위. component 밖 노드(제품 등 기준본에 같이 있는 노드)는 그대로.
4. include 쓰기(`morphed.inc`) — **원본 고정폭 형식 보존**:
   - 기준본을 바이트로 읽고 줄 끝(`\r\n`/`\n`)·인코딩(ASCII/latin-1 통과)을 보존. `/NODE` 키워드 줄부터 다음 `/`로 시작하는 줄 전까지가 노드 블록. `#`·`$` 주석 줄은 그대로.
   - 데이터 줄: Radioss 표준 폭 `I10, F20, F20, F20`(id·X·Y·Z)을 기본으로 하되 **줄마다 실제 필드 경계를 감지**(공백 분리 토큰의 끝 열). 이동한 노드는 X·Y·Z 필드만 같은 폭·오른쪽 정렬로 다시 쓴다. 값 서식: 폭 w에 들어가는 가장 많은 유효숫자의 `%.{p}g`(최소 p=7), 들어가지 않으면 지수 표기, 그래도 안 되면 `GEOM_INC_FORMAT`. 이동량 0인 노드 줄은 원문 그대로.
   - 그 밖의 줄(`/TETRA4`, `/PART`, `/PROP` 등)은 원문 그대로. 요소 수·ID·연결 불변을 쓰기 후 다시 읽어 확인(불일치 → `GEOM_INTERNAL`).

### 6.5 check

입력: 기준본, `morphed.inc`, 샘플 B-rep, features, values, tag, 조립 폴더. 모든 항목을 평가(단락 없음) 후 `check.json`.

| 항목 | 방법 | 기본 기준 | 실패 코드 |
|---|---|---|---|
| (a) 파라미터 재측정 | `measure` 방법으로 **모핑 메시**(경계 노드)에서 값 측정 | `|측정−입력| ≤ max(param_abs_mm, param_rel·|입력|)` | `GEOM_PARAM_MISMATCH` |
| (b) 경계 편차 | 경계 노드(kind 1~3) ↔ 대응 샘플 엔티티 최대 거리 | ≤ `boundary_max_mm`(0.05) | `GEOM_DEVIATION` |
| (c) 품질 | 요소별 scaled Jacobian(꼭짓점 4곳 `√2·6V/(|e1||e2||e3|)` 중 최소, 정사면체 1), aspect = 최장 엣지 / (2√6 · 내접 구 반지름)(정사면체 1), 최소 엣지 길이, 반전(부피 ≤ 0) | 반전 0, `min_scaled_jacobian ≥ 0.2`, `max_aspect ≤ 10`, `min_edge ≥ min_edge_ratio × 기준본 min_edge`. `relative_to_baseline=true`면 기준본이 이미 기준 밖인 요소는 "기준본 값보다 나빠지지 않음"(Jacobian ≥ 0.9×기준본, aspect ≤ 1.1×기준본)으로 판정. `dt_ratio` = 모핑 min_edge / 기준본 min_edge(시간 간격 비 추정, 정보) | `GEOM_QUALITY` |
| (d) 간섭 | 바디-바디: 모핑 외피 노드가 다른 쿠션 바디 tetra 안에 깊이 > `body_mm`로 들어감(공칭 접촉 면 쌍은 깊이 > `body_mm`일 때만). 제품: 조립 폴더 나머지 메시(쉘 중립면 ± 두께/2, 솔리드 외피)에 대한 외피 노드 관통 깊이 > `product_mm` | 관통 없음 | `GEOM_INTERFERENCE` |
| (e) tie | 조립 폴더 `/INTER/TYPE2`에서 쿠션 노드가 secondary(또는 main 면)인 인터페이스마다, secondary 노드 ↔ main 면 투영 거리 ≤ `Dsearch`(카드 값, 0·공백이면 `tie.default_dsearch_mm`, 그것도 null이면 그 인터페이스 공칭 최대 거리 × 1.5) | 투영 실패 노드 0 | `GEOM_TIE_PROJECTION` |

- `/INTER/TYPE2`·`/GRNOD`·`/SURF` 해석에 실패하면 (e) `NOT_EVALUATED` + 경고 `TIE_PARSE_SKIPPED`. `tie.required=true`(기본)여도 해석 실패는 실패가 아니라 경고(§15 Q7에서 확정).
- 제품 메시 수집: 조립 폴더 `*.rad`·`*.inc`(기준본 제외)의 `/NODE`·`/SHELL`·`/SH3N`·`/BRICK`·`/TETRA4`·`/TETRA10`·`/PENTA6`. 쿠션 bbox + 10 mm 밖 요소는 버림. KD-tree(`scipy.spatial.cKDTree`)로 근방 탐색.

**실패 코드 표**(`category`는 화면·DOE 기록용 사유 묶음. §18.4: paicad는 `code`·`category`와 영문 기술 `message`만 낸다. 아래 한국어 사유는 **플랫폼의 code→한국어 매핑 표준 문구**이며 화면에 표시하는 쪽은 플랫폼):

| code | category | 한국어 사유(플랫폼 표시 문구) | 발생 | 종료코드 |
|---|---|---|---|---|
| `GEOM_CAD_FAILED` | `CAD_FAILED` | CAD 생성 불가 | update | 10 |
| `GEOM_TOPOLOGY_CHANGED` | `CAD_FAILED` | CAD 생성 불가(위상 변화: 면 수 n→m) | update | 10 |
| `GEOM_INTERFERENCE` | `INTERFERENCE` | 간섭 | check (d) | 11 |
| `GEOM_QUALITY` | `QUALITY` | 품질 미달 | check (c) | 11 |
| `GEOM_MORPH_FAILED` | `QUALITY` | 품질 미달(모핑 해 실패) | morph | 11 |
| `GEOM_DEVIATION` | `DEVIATION` | 편차 초과(경계 최대 x mm) | check (b) | 11 |
| `GEOM_PARAM_MISMATCH` | `DEVIATION` | 편차 초과(파라미터 재측정) | check (a) | 11 |
| `GEOM_TIE_PROJECTION` | `TIE` | tie 투영 실패 | check (e) | 11 |
| `GEOM_BODY_MAP_FAILED` | `PREP` | 바디–component 대응 실패 | extract·tag | 12 |
| `GEOM_BASELINE_MISMATCH` | `PREP` | 공칭 STEP과 기준 메시 불일치 | tag | 12 |
| `GEOM_UNSUPPORTED_ELEMENT` | `PREP` | tetra4가 아닌 쿠션 요소 | tag | 12 |
| `GEOM_TAG_FAILED` | `PREP` | 경계 분류 실패 | tag | 12 |
| `GEOM_EXTRACT_EMPTY` | `PREP` | 인식된 피처 없음 | extract | 13 |
| `GEOM_INPUT_INVALID`·`GEOM_OUTPUT_EXISTS`·`RENUM_CSV_MISSING` | `INPUT` | 입력 오류 | 전부 | 3 |
| `PROP_OVERRIDDEN_BY_ELEMENT` | `PROP` | 쉘 두께 무효(요소별 두께가 PROP을 덮어씀) | props apply (3S) | 11 |
| `PROP_THICKNESS_INVALID` | `PROP` | 쉘 두께 ≤ 0 또는 범위 밖 | props apply (3S) | 11 |
| `PROP_NOT_FOUND` | `PROP` | 지정한 PROP ID·필드를 찾지 못함(형식 변종 포함) | props apply (3S) | 11 |
| `ID_RANGE_OVERFLOW` | `PREP` | 재메시 노드·요소 번호가 RENUM_INIT 범위 간격 초과(후속 옵션 §11.2, 1차 미구현) | remesh | 11 |
| `GEOM_INC_FORMAT` | `INTERNAL` | include 고정폭 형식 보존 불가 | morph | 20 |
| `GEOM_INTERNAL` | `INTERNAL` | 내부 오류 | 전부 | 20 |

경고(실패 아님, `props.json`·`props_apply.json`·run 기록): `PROP_SHARED_BY_PARTS`(한 PROP을 여러 PART가 공유 — 전부 바뀜을 사용 PART 목록과 함께 표시), `PROP_UNSUPPORTED_TYPE`(TYPE9/10/11 발견, '미지원'). 새 코드의 category `PROP`은 화면·DOE에서 "쉘 두께 적용 실패"로 묶는다.

check 최상위 `code` 우선순위(사용자 사유 순서): `INTERFERENCE` → `QUALITY` → `DEVIATION`(`GEOM_DEVIATION` → `GEOM_PARAM_MISMATCH`) → `TIE`. message = 첫 실패 사유 + " 외 k건"(있으면).

---

## 7. 플랫폼 연동

### 7.1 설정(`config/platform.example.yaml`, 새 절 `geometry` + `commands` 키)

```yaml
geometry:                          # native 형상 엔진(contracts/geometry-engine.md). 절이 없으면 아래 기본값
  engine: altair                   # altair | native — 새 파라미터 세트·①-1 추출·①-3 DOE의 기본 엔진(화면 기본 선택)
  paicad_path: ""                  # 빈 값 = 워커 Python(sys.executable) 폴더의 Scripts\paicad.exe(Windows)·bin/paicad(그 외)
  step_extensions: [".step", ".stp"]
  max_report_bytes: 4194304        # paicad 보고 JSON 읽기 상한
  progress_regex: '^PAICAD PROGRESS (?P<pct>[0-9.]+) (?P<msg>.*)$'
  timeout_s: {extract: 1800, tag: 1800, update: 600, morph: 1800, check: 1800, run: 3600}   # null = 없음
  env:                             # paicad 자식 프로세스 추가 환경변수(허용목록 외 전달은 이것뿐)
    OMP_NUM_THREADS: "4"
    OPENBLAS_NUM_THREADS: "4"
    PAICAD_THREADS: "4"
  defaults:                        # §4.9 options.json 기본값(세트별 덮어쓰기 param_sets.geom_options)
    tag: {tol_abs_mm: 0.05, tol_rel: 1.0e-4, min_match_ratio: 0.98, contact_mm: 0.1, contact_min_ratio: 0.2}
    morph: {poisson: 0.3, solver_rtol: 1.0e-8, solver_maxiter: 5000}
    quality: {min_scaled_jacobian: 0.2, max_aspect: 10.0, min_edge_ratio: 0.8, relative_to_baseline: true}
    deviation: {boundary_max_mm: 0.05, param_abs_mm: 0.05, param_rel: 0.01}
    interference: {body_mm: 0.01, product_mm: 0.05}
    tie: {default_dsearch_mm: null, required: true}
    thickness_ref: contact_fixed

commands:
  paicad_extract: ["{paicad}", "extract", "--cad", "{cad_input}", "--renum-csv", "{renum_csv}", "--options", "{options_json}", "--out-dir", "{out_dir}"]
  paicad_tag: ["{paicad}", "tag", "--cad", "{cad_input}", "--features", "{features_json}", "--baseline-inc", "{baseline_inc}", "--renum-csv", "{renum_csv}", "--assem-dir", "{assem_dir}", "--options", "{options_json}", "--out-dir", "{out_dir}"]
  paicad_update: ["{paicad}", "update", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}", "--tag-dir", "{tag_dir}", "--options", "{options_json}", "--out-dir", "{update_dir}"]
  paicad_morph: ["{paicad}", "morph", "--baseline-inc", "{baseline_inc}", "--tag-dir", "{tag_dir}", "--features", "{features_json}", "--update-dir", "{update_dir}", "--options", "{options_json}", "--out-dir", "{morph_dir}"]
  paicad_check: ["{paicad}", "check", "--baseline-inc", "{baseline_inc}", "--morph-dir", "{morph_dir}", "--update-dir", "{update_dir}", "--tag-dir", "{tag_dir}", "--features", "{features_json}", "--values", "{values_json}", "--assem-dir", "{assem_dir}", "--renum-csv", "{renum_csv}", "--options", "{options_json}", "--out-dir", "{check_dir}", "--out-inc", "{out_inc}"]
  paicad_run: ["{paicad}", "run", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}", "--baseline-inc", "{baseline_inc}", "--tag-dir", "{tag_dir}", "--assem-dir", "{assem_dir}", "--renum-csv", "{renum_csv}", "--options", "{options_json}", "--update-dir", "{update_dir}", "--morph-dir", "{morph_dir}", "--check-dir", "{check_dir}", "--out-inc", "{out_inc}"]
  paicad_version: ["{paicad}", "version", "--json"]
```

- 코드 기본값 = 위 예시 값(null 아님 — 외부 도구 의존이 없으므로). null이면 그 기능만 꺼짐(`features.geometry_native=false`).
- `{cad_input}` `--body-map`은 `S/cad/body_map.json`이 있을 때 워커가 argv 끝에 `["--body-map", <경로>]`를 덧붙인다(템플릿 밖, 값 검사 동일).

`TEMPLATE_SPECS`(`physicsai_core/commands.py`) 추가 — 모두 `required=False`, 토큰 없음, 경로 표기 `os`:

| 키 | 허용 placeholder | cwd |
|---|---|---|
| `paicad_extract` | `paicad, cad_input, renum_csv, options_json, out_dir` | `out_dir` |
| `paicad_tag` | `paicad, cad_input, features_json, baseline_inc, renum_csv, assem_dir, options_json, out_dir` | `out_dir` |
| `paicad_update` | `paicad, cad_input, features_json, values_json, tag_dir, options_json, update_dir` | `update_dir` |
| `paicad_morph` | `paicad, baseline_inc, tag_dir, features_json, update_dir, options_json, morph_dir` | `morph_dir` |
| `paicad_check` | `paicad, baseline_inc, morph_dir, update_dir, tag_dir, features_json, values_json, assem_dir, renum_csv, options_json, check_dir, out_inc` | `check_dir` |
| `paicad_run` | 위 update·morph·check 합집합 + `cad_input` | 샘플 폴더(R 또는 `P/geom`) |
| `paicad_version` | `paicad` | 워커 임시 폴더 |

`EXECUTABLE_PLACEHOLDERS`에 `"paicad": "paicad_path"` 추가, 실행 파일 표는 `effective_altair` 대신 `effective_executables(settings)`(= altair 표 + `paicad_path` 파생값). `validate_template`: `paicad_*` 키의 argv[0]은 `{paicad}`만, 그 밖 키에서 `{paicad}` 금지. 값 검사(`check_value`)는 기존 그대로(`paicad.exe`는 `.bat`이 아니므로 `; , = ( )` 추가 거부 없음).

`/status`: `features.geometry_native` = `paicad_update`·`paicad_morph`·`paicad_check`(또는 `paicad_run`) 비null + 실행 파일 존재. `geometry: {engine_default, native_available, reason|null}`. `config.warnings`: `geometry.engine=native`인데 `native_available=false` → "기본 엔진 native를 쓸 수 없습니다 — paicad 설치 확인".

환경 점검(phase2 §9 A, 워커 부분): 항목 `paicad_version` — 템플릿 실행, stdout JSON 파싱, 표시 "paicad 0.1.0 · OCP 7.x". 실패는 그 항목만 경고.

### 7.2 공통 실행 규칙(워커, `worker/physicsai_worker/steps/geometry_native.py` 신규 공용)

- `run_local(<key>, values, cwd, outputs_to_backup=[보고 JSON·성공 파일·--out-inc], allow_nonzero_exit=True, check_log_errors=False, env_add=geometry.env, poll_hook=진행 정규식, timeout=geometry.timeout_s.<명령>)`.
- 판정 `judge_paicad(rc, report_path, success_paths)`: §5.4 규칙. 보고 FAIL → `StepFailure(code, message)`(code = 보고의 `GEOM_*`). 일괄·DOE에서는 예외 대신 run 실패로 기록.
- 보고 JSON은 `physicsai_core/geometry/reports.py`(신규, 표준 라이브러리)로 읽고 키 존재·타입만 검사.
- 각 단계 로그: `paicad.log` 꼬리 4 KiB를 step 로그에 덧붙임.
- 성공한 단계의 주요 수치(`check.json`의 min Jacobian·max deviation·elapsed)는 PREDICT `result.geometry`에 요약(수치만).

### 7.3 job step 체인 변경(키 불변, 엔진 분기)

엔진 확정: 작업 생성 시 서버가 params에 `engine`을 기록(B8 방식). PREDICT·PREDICT_BATCH = 세트 `engine`, TD_EXTRACT_PARAMS = 요청 `engine`(기본 `geometry.engine`), TD_DOE_GEN = `train_setups.engine`. 화면 step 이름은 `STEP_LABELS_NATIVE`(native일 때 덮어쓰기): `SIMLAB_EXTRACT`→"형상 피처 추출", `HST_GEN_RADIOSS`→"형상 모핑 입력 생성", `TPL_RENDER`→"샘플 값 작성", `GEOM_UPDATE`→"CAD 갱신", `MESH`→"메시 모핑·검사". `current_step_label`은 작업 params의 `engine`으로 고른다.

#### 7.3.1 ①-1 `TD_EXTRACT_PARAMS`(native)

params `{cad_path, engine:"native"}`. `X` 동일.

| step | native 처리 | 성공 판정 |
|---|---|---|
| TX_PREP | 확장자 ∈ `geometry.step_extensions`(아니면 `INPUT_INVALID`), `01_train/cad/<파일>` 복사·sha256(기존). 런처 없음 | |
| SIMLAB_EXTRACT | `paicad_extract`, `{cad_input}`=`01_train/cad/<파일>`, `{renum_csv}`=없으면 인자 쌍째 생략, `{options_json}`=`X/options.json`, `{out_dir}`=`X` | `X/parameter_extracted.xml` + `X/parameter_features.json`, 보고 정상 |
| TX_PARSE | 기존 그대로(xml → `train_setups.parameters`, ±5%). 추가: `train_setups.engine='native'`, `features_rel` = `01_train/extract/<job>/parameter_features.json`, PNG를 artifact `FEATURE_PNG`로 등록 | 기존 |

`{renum_csv}` 생략 규칙: 템플릿 요소가 정확히 `"--renum-csv", "{renum_csv}"` 쌍이면 값이 없을 때 쌍을 뺀다(이 키·이 쌍 한정, 일반 규칙 아님).

#### 7.3.2 ①-2 파라미터 표

`train_setups.engine='native'`: `PUT /train/params` 동일(min·max·use 편집, `format`은 무시·저장만). `POST /train/tpl` → 409 `ENGINE_NATIVE_NO_TPL` "native 엔진은 tpl이 필요 없습니다 — 파라미터 표 저장 후 DOE를 만드세요". tpl 상태 표시 대신 "피처 n개 · 하이라이트 보기".

#### 7.3.3 ①-3 `TD_DOE_GEN`(native) — 단계 4

params `{doe_label, num_runs(2~train_data.max_runs), seed?(정수, 기본 1), multi_execution?, radioss_assem_path, engine:"native"}`. `options`는 받지 않음(있으면 422). `train_does.doe_type='NATIVE_LHS'`, `options={"seed":…}`, `engine='native'`, 사전조건: 파라미터 표 저장(use ≥1) + `features_rel` 존재(tpl 불필요).

| step | native 처리 | 성공 판정 |
|---|---|---|
| DG_PREP | ① 조립 폴더 → `01_train/radioss_assem/<doe_id>/`(기존, RENUM csv 포함). 기준본 없음 → `INPUT_INVALID` "조립 폴더에 기준 메시(104_replace_node_elem.inc)가 없습니다", RENUM csv 없음 → `INPUT_INVALID`. ② `D/cad/` STEP 사본(+ body_map), `D/native/extract/` ← ①-1 산출(xml·features·PNG) 복사, `D/native/options.json`(유효 옵션, 기본값만 — ①에는 세트가 없음). ③ 조합 = `batch_matrix.lhs_values(use 파라미터 이름(표 순서), {name:(min,max)}, num_runs, seed)` → `D/doe_matrix.csv`(`doe_no,run_key,<이름…>`). INPUT_HST_RUN.json·런처 없음. ④ `parameters_snapshot`, `tpl_sha256=NULL` | |
| HST_GEN_RADIOSS | ① `paicad_tag`(cwd `D/native/tag`, `{features_json}`=`D/native/extract/parameter_features.json`, `{baseline_inc}`=`A/<mesh_include_name>`, `{assem_dir}`=`A`) → 실패면 step 실패(코드 그대로). `D/native/prep.json` 작성. ② run마다(`ctx.run_parallel`, 최대 `multi_execution`, doe_no 순) §7.3.6 샘플 생성(R = `D/approaches/native_lhs/run__{doe_no:05d}`). 진행 = 완료 수/N, 라벨 "run k/N 완료 · 스킵 F" | 성공 run ≥1(0 → 첫 실패 코드로 실패), 일부 실패 → 경고 `PARTIAL_OUTPUT` |
| DG_SCAN | 기존 그대로(`run_dir_glob` 기본 `approaches/*/run__*`가 그대로 맞음, starter는 `m_3`에서만 나옴). 추가: run 폴더의 `SKIPPED.json`을 읽어 `skipped_runs`에 `{run_key, reason:<code>, category, message}`로 넣음(기존 `RUN_INPUT_INVALID` 대신). samples 추출기 `paramitem`이 `m_1/native_params.xml`을 읽음(§7.3.6) | 기존 |

#### 7.3.4 ④ 세트 등록(native) — 새 job_type `PARAM_SET_NATIVE`

`JOB_TYPES["PARAM_SET_NATIVE"] = JobTypeDef("PARAM_SET_NATIVE", 4, "SLOT", "형상 준비(native)", (NP_PREP INTERNAL 5, NP_EXTRACT LOCAL 30, NP_TAG LOCAL 60, NP_REGISTER INTERNAL 5), "④", notify_success=True)`. STEP_LABELS: NP_PREP "준비 파일 모으기", NP_EXTRACT "형상 피처 추출", NP_TAG "경계 노드 분류", NP_REGISTER "템플릿 등록".

생성 경로:

1. 신규: `POST /studies/{id}/param-sets {mode:"discover", path, choice:{cad, radioss_assem}, label, engine:"native", geom_options?}` → **202 `{job_id}`**(altair는 기존 201 그대로). params `{mode:"new", path, choice, label, geom_options}`.
2. 다시 준비: `POST /param-sets/{id}/native-prepare` → 202(params `{mode:"reprep", param_set_id}`) — tag 옵션 변경·입력 교체 후.

| step | 처리 |
|---|---|
| NP_PREP | new: discover(native 규칙, §7.4)를 다시 실행해 고른 후보 확인 → 임시 폴더 `<study>/logs/_paramset_tmp/<job_id>/`에 `cad/`(STEP 또는 `parts/`·body_map), `radioss_assem/`(eps_mesh 제외 rad·inc·RENUM csv, 기준본 필수), 프로젝트 폴더의 `parameter_features.json`·`parameter_extracted.xml`(같은 폴더에 둘 다 있을 때만, 있으면 NP_EXTRACT 생략), `native/options.json`(유효 옵션) 복사(원본 재검사·핸들 기준 복사 — phase3 D3-50과 같음). reprep: `S/native/`를 `_backup` 이동 후 `S/native/extract/`만 되살림(이전 extract 재사용), 대상 = `S` |
| NP_EXTRACT | `paicad_extract`(out `T/native/extract`). 생략 조건이면 SKIPPED "준비된 피처 파일 사용" |
| NP_TAG | `paicad_tag`(out `T/native/tag`) |
| NP_REGISTER | new: `parameters.json` = features 대표 파라미터 `{name, nominal, min:range.min, max:range.max, unit:"mm"}`(프로젝트 폴더에 `parameters.json`이 있고 이름 집합이 같으면 그 min·max 사용, 다르면 `PARAM_FEATURE_MISMATCH` 실패). `native/prep.json` 작성. 검증 `validate_folder(..., engine="native")`(§7.4) → 등록(`engine='native'`, `tpl_rel=NULL`, `tpl_params=[]`, `cad_file_name`=STEP 파일명 또는 `"parts/"`, `input_kind='assembly'`, `geom_options`, `label`) → `os.replace(T, 04_params/<id>)`. reprep: 파라미터 이름 집합이 이전과 다르면 `PARAM_FEATURE_MISMATCH` 실패(세트 불변), 같으면 `prep.json`만 갱신. PNG artifact `FEATURE_PNG` 등록 |

①→④ from-train(phase2 §6.13): DOE `engine='native'`이면 `D/cad/`→`cad/`, `A/`→`radioss_assem/`, `D/native/`→`native/`(prep.json 경로를 S 기준으로 다시 씀) 복사, tpl 없음. 동기 그대로(paicad 실행 없음).

#### 7.3.5 ④ `PREDICT`(A, native) — 단계 3

| step | native 처리 | 성공 판정 |
|---|---|---|
| PR_PREP | 기존 + 준비본 유효성(§4.2, 실패 `INPUT_CHANGED`) + `P/geom/options.json`(유효 옵션) | |
| TPL_RENDER | tpl 렌더 대신 `P/geom/values.json`(§4.4) 작성. CAD 사본 없음(paicad가 `S/cad` 읽기) | 파일 작성 |
| GEOM_UPDATE | `paicad_update`, `{update_dir}`=`P/geom/update`, `{tag_dir}`=`S/native/tag`, `{features_json}`=`S/native/extract/parameter_features.json`, `{cad_input}`=`S/cad/<STEP>` 또는 `S/cad/parts` | `update.json` OK + `sample.brep` |
| MESH | `paicad_morph`(`{morph_dir}`=`P/geom/morph`) → `paicad_check`(`{check_dir}`=`P/geom/check`, `{out_inc}`=`P/geom/{mesh_include_name}`) 순차. `template_kind`·`commands.mesh`와 무관 | `P/geom/{mesh_include_name}` + `check.json` PASS |
| RAD_ASSEMBLE | **기존 `_assemble_parametric` 그대로**(조립 폴더 사본 − 기준본 + 새 include → `P/INPUT`) | 기존 |
| 이후 | 그대로 | |

`geom_update` 핸들러의 `commands.geom_update is None` 검사, MESH의 `template_kind == mesh_only`/`commands.mesh is None` SKIPPED는 native에서 건너뛴다(먼저 엔진 분기).

#### 7.3.6 샘플 생성 공용(①-3 run·④ 일괄 run) — `R`

| 위치 | 내용 |
|---|---|
| `R/options.json` | 유효 옵션(사용값) |
| `R/m_1/values.json` | §4.4(`source.kind` batch|doe, `doe_no`) |
| `R/m_1/native_params.xml` | paramitem 호환: 줄마다 `   <paramitem Name="<이름>" NewValue="<값 repr>" Value="<공칭>"/>`, 루트 `<Parameters Value="">…</Parameters>` — 기존 `train_data.paramitem_regex`·`rendered_tpl_exts`(`.xml`)로 추출됨 |
| `R/m_1/update/` | update 출력 |
| `R/m_2/morph/`, `R/m_2/check/` | morph·check 출력 |
| `R/m_2/{mesh_include_name}` | PASS일 때만 |
| `R/m_3/` | `assemble_into(settings, A 또는 S/radioss_assem, R/m_2/<inc>, R/m_3)` — 기존 함수 그대로 |
| `R/SKIPPED.json` | 실패 시 `{schema_version:1, code, category, message, step:"update|morph|check", report:"m_2/check/check.json"}` |

실행: `paicad_run`이 비null이면 1회(cwd R), 아니면 update → morph → check 순차. 실패(보고 FAIL) → `SKIPPED.json` 작성 + run 실패(일괄: `predict_batch_runs.gen_state=FAILED, gen_code=<GEOM_*>, gen_message=<message>`), m_3는 만들지 않음. 플랫폼 오류(실행 파일 없음 등)는 기존처럼 그 코드로 run 실패.

#### 7.3.7 ④ `PREDICT_BATCH`(B, native) — 단계 4

| step | native 처리 |
|---|---|
| BP_PREP | 기존 + 준비본 유효성. run마다 CAD 사본·렌더 대신 `m_1/values.json`·`native_params.xml`·`R/options.json`. `batch.json`에 `engine:"native"` |
| BP_GEN | run마다 §7.3.6(`commands.geom_update` null 검사 건너뜀). 마지막 `prepared_input.plan_copy` 검사 기존 그대로 |
| BP_ENQUEUE | 그대로 |

⑤ 내장 최적화(`SURROGATE_OPT`)는 B를 만들 뿐이라 자동으로 native. 생성 실패 run(스킵)은 기존 규칙대로 후보에서 빠짐.

### 7.4 파라미터 세트 탐색·검증(native)

- `param_discover.discover(root, settings, engine="native")`: tpl을 찾지 않음. CAD 후보 = `geometry.step_extensions` 파일(단일) 또는 이름이 `parts`인 폴더 안 STEP ≥1(component별). 조립 폴더 후보 = 기존 규칙 + **기준본 `{mesh_include_name}` 존재 필수**, 없으면 후보 아님(`problems` `BASELINE_INC_MISSING`). RENUM csv 없음 → `RENUM_CSV_MISSING`(problem). `parameter_features.json`·`parameter_extracted.xml` 동반 여부를 `notes`로.
- `validate_folder(folder, ..., engine="native")`: tpl 검사 생략, `cad/` 규칙(§2.3), `radioss_assem/` 필수 + 기준본·RENUM csv 필수, `native/prep.json`·`native/extract/parameter_features.json`·`native/tag/tag.json` 필수(`NATIVE_PREP_MISSING`), parameters 이름 집합 = features 대표 이름 집합(`PARAM_FEATURE_MISMATCH`).
- `PATCH /param-sets/{id} {geom_options}`: 부분 객체 저장(감사 `PARAM_SET_UPDATE`). `tag` 절이 바뀌면 응답 `native.prep_status="STALE"` + 안내 "경계 분류 기준이 바뀌어 형상 준비를 다시 해야 합니다". altair 세트에 보내면 422.

### 7.5 DB — migration `0012_geometry_engine`(head 0011 → 0012, `MIGRATION_HEAD` 갱신)

| 테이블 | 변경 |
|---|---|
| `param_sets` | `engine VARCHAR(16) NOT NULL DEFAULT 'altair'` CHECK `('altair','native')`; `geom_options JSONB NULL`(덮어쓰기만, 기본값 아님); `tpl_rel` NULL 허용 + CHECK `ck_param_sets_tpl_engine`: `engine='native' OR tpl_rel IS NOT NULL`; CHECK `ck_param_sets_native_assembly`: `engine<>'native' OR input_kind='assembly'` |
| `train_setups` | `engine VARCHAR(16) NOT NULL DEFAULT 'altair'`; `features_rel VARCHAR NULL` |
| `train_does` | `engine VARCHAR(16) NOT NULL DEFAULT 'altair'`; `geom_options JSONB NULL`(사용값 사본) |
| `datasets` | `engine VARCHAR(16) NULL`(NULL = 모름) |
| `param_sets`·`train_does`·`predict_batch_runs`·`datasets` | `engine_version VARCHAR(32) NULL`(paicad 버전, altair·모름 = NULL, §17.3) |
| `models` | `engine VARCHAR(16) NULL` |
| `artifacts` | kind 목록에 `FEATURE_PNG`(CHECK가 있으면 추가) |

기존 행은 모두 `altair`/NULL. 다운그레이드는 기존 정책(거부)과 같음.

### 7.6 API 변경 요약(`backend/openapi.json` 갱신 — Backend)

| API | 변경 |
|---|---|
| `GET /status` | `features.geometry_native`, `geometry{engine_default, native_available, reason}` |
| `POST /studies/{id}/param-sets/discover` | 요청 `engine?`(기본 `geometry.engine`). native는 §7.4 후보 |
| `POST /studies/{id}/param-sets` | `engine:"native"` → 202 `{job_id}`(`PARAM_SET_NATIVE`). `geometry_native=false`면 409 `GEOM_NATIVE_UNAVAILABLE` |
| `PATCH /param-sets/{id}` | `geom_options` 추가 |
| `POST /param-sets/{id}/native-prepare` | 신규, 202 |
| `ParamSet` 응답 | `engine`, `geom_options`(덮어쓰기), `geom_options_effective`, `native:{prep_status: READY|STALE|MISSING, feature_count, features:[{name,type,body,nominal,min,max,group,ref_confirmed,png_artifact_id}]}`|null |
| `GET /param-sets/{id}/features` | 신규. `parameter_features.json` 요약(위 `features` + groups + warnings). PNG는 기존 `/artifacts/{id}/media` |
| `POST /jobs` TD_EXTRACT_PARAMS | params `engine?` |
| `POST /jobs` TD_DOE_GEN | native: `seed?`, `options` 금지 |
| `POST /train/tpl` | native → 409 `ENGINE_NATIVE_NO_TPL` |
| `POST /jobs` OPTIMIZE(원본) | native 세트 → 409 `ENGINE_NATIVE_UNSUPPORTED` "원본 최적화는 SimLab 템플릿에서만 — 플랫폼 내장 최적화를 쓰세요" |
| PREDICT·PREDICT_BATCH·SURROGATE 생성 | native 세트: `geometry_native=false` → 409 `GEOM_NATIVE_UNAVAILABLE`, 준비본 STALE/MISSING → 409 `GEOM_PREP_STALE`, 엔진 불일치 → 409 `ENGINE_MISMATCH`(§7.7) |
| 배치 run 응답 | `gen_code`가 `GEOM_*`면 `gen_category`(§6.5 category) 추가 |
| DOE 상세 `skipped_runs[]` | `category` 추가 |

### 7.7 엔진 분리(혼용 금지)

- `datasets.engine`: DATASET_CREATE의 `input_path`가 `01_train/doe/<doe_id>` 아래(또는 결과 회수 폴더가 특정 DOE 소속)면 그 DOE의 engine. 수집한 h3d가 서로 다른 엔진 DOE에 걸치면 422 `ENGINE_MIXED` "altair·native 학습데이터를 한 데이터셋에 섞을 수 없습니다". 판별 불가면 NULL.
- `models.engine`: 등록 시 `dataset_id`가 있으면 그 데이터셋 engine, 없으면 NULL.
- PREDICT·PREDICT_BATCH·SURROGATE_OPT 생성: 모델 engine이 NULL이 아니고 세트 engine과 다르면 409 `ENGINE_MISMATCH` "모델(native)과 템플릿(altair)의 형상 엔진이 다릅니다". NULL이면 통과 + 작업 경고 `ENGINE_UNKNOWN`.
- 화면: 데이터셋·모델·세트 목록에 엔진 배지(`SimLab`/`native`).

### 7.8 배포·시험

- `deploy/collect-offline.ps1`·`.sh`: `pip wheel packages/paicad --no-deps -w dist/wheels` 추가(simdash_adapters와 같은 방식), `deploy/requirements.lock`에 `cadquery-ocp==<고정>`(win_amd64 cp312 `--only-binary`), `requirements.local.lock`에 `paicad==0.1.0`. numpy·scipy는 기존 lock 공유. `docs/manual/admin.md` §2.2 묶음 크기 안내 갱신(Plan 후속).
- 루트 `pyproject.toml`: 의존 `paicad==0.1.0`, pytest `testpaths`·`pythonpath`에 `packages/paicad/tests`·`packages/paicad/src`.
- 플랫폼 시험: `backend/tests/fake_tools/fake_paicad`(Python 스크립트) — 하위 명령별로 보고 JSON·성공 파일을 쓰고, 환경변수 `FAKE_PAICAD_FAIL=<cmd>:<code>`로 실패 보고를 흉내. 플랫폼 쪽 시험은 OCP 없이 돈다.
- paicad 시험: `mesh`·`morph`·`check`는 해석적 B-rep 대역(평면·원통)과 작은 합성 tetra 메시(저장소 안 생성 스크립트, 1 MB 미만)로 OCP 없이. `brep`·통합 시험은 OCP 필요 — Linux 개발 환경에 `cadquery-ocp` manylinux wheel을 설치해 `scripts/test-all`에서 실제로 돈다(skip을 통과로 치지 않음, AGENTS.md). 합성 STEP은 시험이 OCP로 생성(저장소에 STEP 파일 넣지 않음).
- 계층 시험(architecture R0): `physicsai_core`·`physicsai_api`·`physicsai_worker`에서 `paicad`·`OCP` import 금지 검사 추가.

---

## 8. UI 변경 최소안(Impl-Frontend)

| 위치 | 변경 |
|---|---|
| ④ `ParamSetCard`·`ParamSetDiscoverForm` | "형상 엔진" 2단 선택 [SimLab | native](기본 `/status.geometry.engine_default`, native 불가면 비활성 + 사유). native: tpl 칸 숨김, CAD 후보 = STEP, 조립 폴더 필수 안내 "기준 메시 104_replace_node_elem.inc 필요". 등록 = 작업 진행 표시(기존 작업 진행 컴포넌트) |
| ④ 세트 상세 | 피처 표(이름·종류·바디·공칭·범위·그룹·기준면 "자동") + 행 클릭 시 하이라이트 PNG. 준비 상태 배지 READY/STALE(+ "형상 준비 다시" 버튼) |
| ④ 세트 상세 "검사 기준(고급)" | **접힘 1개**. 품질(min Jacobian·max aspect·min edge 비), 간섭(바디·제품 mm), 편차(경계 mm·파라미터 abs/rel), tie 필수 여부. 칸 placeholder = 기본값, 저장 = `PATCH geom_options`, "기본값으로" = 해당 키 제거 |
| ④ 일괄 예측 결과 표 | 생성 실패 행 사유 칸에 category 배지(CAD 생성 불가/간섭/품질 미달/편차 초과/tie 투영 실패) + message |
| ①-1 | 엔진 선택(같은 2단), native는 STEP만 |
| ①-2 | native: tpl 생성 버튼 숨김, "피처 n개 · 하이라이트 보기" |
| ①-3 | native: DOE 유형 고정 "LHS(native)" + run 수·seed·동시 실행 수. 결과 run 표의 스킵 행에 category |
| ③ 데이터셋·모델, ⑤ | 엔진 배지. `ENGINE_*` 오류 문구 표시 |
| 작업 목록 | native step 이름(`STEP_LABELS_NATIVE`) |

새 화면 없음, 시안 없음(필수 UI만).

---

## 9. 단계별 산출물·완료 기준

| 단계 | 산출물 | 완료 기준 |
|---|---|---|
| **0 골든 세트** | 서버 AI 루트 `golden/geometry/G1/`: `nominal.step`(다중 바디) 또는 `parts/*.step`, `radioss_assem/`(starter·기준본·RENUM csv·제품 inc), `samples/S1~S3/`(NX로 파라미터 바꾼 `sample.step` + `values.json` + SimLab 메시 `EPS_mesh_0000.rad` + m_2 include + Radioss 결과 h3d/T01), `README.txt`(파라미터·값·단위·출처). 저장소에는 합성 소형 세트 생성 스크립트(`packages/paicad/tests/data/make_synthetic.py`)만 | 사용자가 G1 폴더 준비 확인, §15 Q1(좌표 일치)·Q3(inc 헤더) 답 확보 |
| **1 tag+extract** | `paicad version/extract/tag`, `paicad.mesh` 읽기·쓰기(무변경 왕복), ①-1 native, `PARAM_SET_NATIVE`·discover·validate native, migration 0012, `/status`·환경 점검, UI(엔진 선택·피처 표·PNG), fake_paicad | G1: 바디 대응 100%, `match_ratio ≥ 0.98`, 피처 목록을 사용자가 확인(누락·오인식 목록 기록). 무변경 왕복 include = 기준본과 바이트 동일. `scripts/test-all` 통과 |
| **2 update+morph+inc** | `paicad update/morph`, 고정폭 쓰기, face_map | G1 S1~S3: update B-rep vs NX `sample.step` 면별 최대 거리 ≤ 0.01 mm·부피 차 ≤ 0.1%. 모핑 메시 경계 노드 ↔ NX 형상 최대 거리 ≤ 0.05 mm. 출력 include diff = `/NODE` 좌표 필드만. 반전 요소 0 |
| **3 check+스킵** | `paicad check/run`, 실패 코드, PREDICT(A) native 체인, 고급 옵션 저장·사용값 기록, UI 고급 옵션 | 5개 실패 유형마다 의도적 실패 샘플(합성)로 코드·사유 확인. G1 S1~S3 PREDICT(A) native 성공·예측 h3d 생성. `P/geom/options.json`에 사용값 |
| **4 DOE native** | ①-3 native(LHS·tag 1회·run 병렬·SKIPPED.json·paramitem), ④ PREDICT_BATCH native, ⑤ 내장 최적화 경유 확인, 엔진 분리(datasets·models·409) | G1 LHS 20 run: 스킵률·사유 표, ② h3d 미리보기·③ 데이터셋 생성이 코드 변경 없이 run 폴더를 찾음, `samples.csv`(paramitem) 값 = `doe_matrix.csv`. 혼용 시 422/409 |
| **3S 쉘 두께**(단계 3과 병행 가능, CAD 불필요) | `paicad props scan/apply`, 파라미터 표 병합(extract 결과 + PROP), 두께만 있는 param_set 허용, UI 표 행, 합성 시험 | 합성 조립 rad(공유 PROP·요소별 두께·TYPE9 포함)로 `PROP_OVERRIDDEN_BY_ELEMENT`·`PROP_THICKNESS_INVALID`·공유 경고·'미지원' 표시 확인, 출력 diff = 해당 PROP 두께 필드만, 원본·SPDM 불변 |
| **5 (선택) 쉘 형상** | 쉘 형상 모핑 | 별도 계약 |
| (후속 옵션) 재메시 폴백 | §11.2, 1차 미구현 | 조건·절차는 §11.2 |

---

## 10. 검증 계획

1. **골든 형상 비교**(단계 2·3): G1 샘플마다 (a) native 샘플 B-rep ↔ NX STEP 면별 Hausdorff, (b) native 모핑 메시 경계 ↔ NX STEP 거리, (c) 바디 부피·표면적 차, (d) native 메시 ↔ SimLab 메시(위상 다름) 외피 Hausdorff ≤ 메시 크기 0.25배. 표로 기록(`golden/geometry/G1/report_native.csv`).
2. **Radioss 응답 동등**(단계 3): 같은 조립 rad로 (i) SimLab 메시(m_2 include) (ii) native include를 각각 Radioss 해석(사용자 PBS/SCX). 비교 지표: 쿠션 최대 von Mises·최대 변형률, 제품 최대 가속도(T01), 내부 에너지 최대, 시간 이력 NRMSE. 기준(제안): 피크 차 ≤ 5%, NRMSE ≤ 5%, 시간 간격 비(dt) 차 ≤ 10%. 기준 밖이면 원인(메시 품질·형상 차) 분석 후 허용오차 조정 제안.
3. **PhysicsAI 예측 동등**(단계 4): G1 학습 모델로 (i)·(ii) 입력 예측 비교 — 응답 차가 학습 오차 수준인지 확인(정보).
4. **회귀**: altair 경로 시험 전부 통과(엔진 기본값 altair), fake_paicad 시험, paicad 단위·통합 시험.
5. **결정성**: 같은 입력 2회 실행 → `morphed.inc` 바이트 동일.

---

## 11. 단계 3S(쉘 두께, 확정) · 단계 5(선택) · 후속 옵션 경계

### 11.1 단계 3S — 쉘 두께 파라미터 (이번 범위 포함, 결정 2026-10-17)

- **대상**: 조립 폴더 `/PROP/TYPE1`(SHELL)의 두께 필드만. `/PROP/TYPE9·10·11`(SH_ORTH·COMP·SANDW)은 비범위 — 발견되면 `props.json`에 `supported=false`(`PROP_UNSUPPORTED_TYPE`)로 목록에만 표시, 선택 불가.
- **발견**: `paicad props scan`이 조립 rad/inc를 읽어 PROP ID·제목·현재 두께·사용 PART 목록·정의 파일(조립 폴더 상대 경로)을 `props.json`(JSON)으로 출력. 사용자가 선택, 범위 기본 ±5%(기존과 동일, min·max 편집). PROP 정의 위치(기준본 헤더 vs 조립 rad)는 scan이 조립 폴더 전체에서 찾으므로 위치에 무관(Q3·Q4 해소).
- **파라미터 표**: 이름 `<PROP_TITLE 정규화>_SHELL_T`(제목 없으면 `PROP<ID>_SHELL_T`, 충돌 시 ID 접미), `parameter_extracted.xml` 호환(Root/Model/Parameter/Name,Value) 유지. extract 결과(형상)와 PROP 행을 **하나의 파라미터 표**로 합친다(`parameter_features.json`에는 넣지 않고 `props.json`을 별도 입력으로 병합, 표의 `source = prop`).
- **적용**: run 폴더 INPUT의 **복사본**에서 해당 PROP 카드의 두께 필드만 §6.4 고정폭 형식을 보존하며 교체(`props apply`). 원본 조립 폴더·SPDM 불변. 노드 inc(R1 모핑)와 독립 — 형상 파라미터 없이 쉘 두께만 있는 param_set 허용(이때 tag·update·morph·check 생략).
- **검사(실패 시 샘플 스킵 + 코드)**: (i) 한 PROP을 여러 PART가 공유 → 경고 `PROP_SHARED_BY_PARTS`(전체 PART 표시, 실패 아님). (ii) `/SHELL` 요소 줄에 요소별 두께가 0이 아니면 PROP 변경이 무효 → `PROP_OVERRIDDEN_BY_ELEMENT` 실패(scan에서도 사전 표시). (iii) 두께 ≤ 0 → `PROP_THICKNESS_INVALID`.
- **영향(리스크)**: 쉘 두께 변경은 접촉 gap(두께 기반 Igap)·Δt·질량을 바꿀 수 있어 응답 변화에 형상 외 효과가 섞임(§12).
- **altair 경로 적용은 미결**(GE-11 원칙상 1차 native만, §15 Q13).

### 11.2 모핑 실패 시 재메시 폴백 (조건부 후속 옵션, 1차 미구현)

- 1차: 모핑 실패는 스킵(기존 합의 유지).
- **허용 조건**: 단계 0 ID 참조 스캐너가 해당 쿠션 component에 대해 tie/RBE/명시적 노드·세그먼트 집합 참조 0건일 때만. 참조가 있으면 재메시해도 집합 소속이 깨지므로 R2 번들 재생성이 필요 — 비범위.
- **절차**: 재메시 결과를 run 폴더 하위 `remesh/`에 저장 → component 시작번호(`RENUM_INIT`)로 renumber → 노드·요소 수가 범위 간격을 넘는지 검사(넘으면 `ID_RANGE_OVERFLOW` 실패) → 해석 케이스 저장. run 메타에 `mesh_origin: morph|remesh` 기록, 데이터셋 화면에서 구분 표시(위상 상이 샘플 혼재 경고). 메셔(Netgen 등)는 그때 결정.
- R1 원칙(GE-1, renumber·메셔 불사용)의 예외이므로 구현 전 별도 계약 절·GE-C 메모로 Plan 확인.

### 11.3 단계 5(선택)

- 쉘 형상 모핑: 면 노드 매핑만(내부 해 없음), 품질 = 쉘 Jacobian·warpage. 별도 계약.

---

## 12. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| 공칭 STEP과 기준 메시 좌표 불일치(원점·단위·디피처링) | tag 실패 → native 불가 | 단계 0에서 확인(Q1), `GEOM_BASELINE_MISMATCH`로 조기 차단, 자동 정렬 안 함 |
| OCCT push/pull이 위상을 바꿈(면 병합·분할, 필렛 소멸) | CAD 생성 불가 스킵 증가 | `feasible` 범위, 위상 검사, 범위 기본 ±5% |
| 피처 오인식(구배·곡면 쿠션) | 잘못된 파라미터 | PNG 하이라이트로 사용자 확인, 재측정 (a) |
| 대변형 시 메시 찌그러짐 | 품질 미달 스킵 | 1/V 강성, 품질 검사, ±5% 범위 |
| 고정폭 형식 변종(긴 형식, 탭, 자유 형식) | 쓰기 실패 | 줄별 필드 감지, `GEOM_INC_FORMAT`로 차단, 무변경 왕복 시험 |
| tie·접촉 정의 해석 실패 | (e) 미평가 | `NOT_EVALUATED` 경고, Q7 |
| 제품 메시가 큼(수백만 노드) | check 느림 | bbox 자르기 + KD-tree, `timeout_s` |
| cadquery-ocp wheel 크기·Windows DLL(VC 런타임) | 설치 실패 | 오프라인 묶음 포함, 환경 점검 `paicad_version`, 대시보드 PC VC 런타임 확인 |
| 같은 STEP이라도 OCP 버전 바뀌면 면 번호 변경 | 준비본 무효 | `prep.json.ocp_version` 비교 → STALE, 면 서명으로 재식별 |
| 엔진 혼용으로 모델 오용 | 조용한 오답 | DB 엔진 기록 + 409/422 |
| 기준면 규칙 미확정 | 두께 변경 방향 오류 | `ref.confirmed=false` 표시, Q2 확정 후 기본값 변경(설정만) |
| 쉘 두께 변경(3S)이 접촉 gap(Igap)·Δt·질량을 바꿈 | 응답 변화에 형상 외 효과 혼입, Δt 감소로 해석 시간 증가 | run 기록에 두께 값 저장, 공유 PROP 경고, 범위 ±5% |
| 재메시 폴백(후속) 샘플 혼재 | 위상 상이 샘플이 데이터셋 품질 저하 | `mesh_origin` 기록·구분 표시·혼재 경고 |

---

## 13. 구현 분해(파일 소유 비중첩)

| 담당 | 파일 |
|---|---|
| Impl-Geom (paicad) | `packages/paicad/**` 전부 |
| Impl-Backend B(플랫폼) | `physicsai_core/commands.py`(spec·실행 파일), `config/schema*.py`·`platform.example.yaml`, `physicsai_core/geometry/`(reports·options 병합), `stage4_predict/param_discover.py`·`param_sets.py`, `job_types.py`, `migrations/versions/0012_geometry_engine.py`, `db/tables/*`, `worker/.../steps/geometry_native.py`·`stage4_predict/{predict_inputs,batch,param_set_native}.py`·`stage1_train_data/{extract,doe_gen}.py`, API 서비스·라우터·openapi, fake_paicad, deploy |
| Impl-Backend(검사) | `scripts/test-all.sh`·`.ps1`(+ 필요 시 `scripts/check_paicad_version.py`): `packages/paicad` 변경 시 `__version__` 변경 + CHANGELOG 최상단 항목 버전 == `__version__` + 루트 고정·lock 일치(§17.5). A의 첫 커밋 전에 넣는다 |
| Impl-Backend(검사, §18) | 같은 `scripts/test-all`에 "paicad에서 플랫폼 모듈(`physicsai_core`·`backend`·`worker`·`physicsai_worker`) import 금지 검사"(AST로 `packages/paicad/src`·`tests` 스캔) + `pytest packages/paicad` 단독 실행 단계 + 플랫폼 고유 파일명·경로 하드코딩 검사 + 라이선스 고지 파일 존재 검사 |
| Impl-Frontend | §8 |
| 순서 | A 단계 1 → B 단계 1(fake로 병행) → A 2 → A 3 + B 3 → B 4 → 프런트(단계 1·3·4 화면). 단계 3S(`props scan/apply`: A, 파라미터 표 병합·두께만 param_set·fake_paicad: B, UI 행: 프런트)는 단계 3과 병행 가능(CAD 불필요) |

---

## 14. Verifier 체크리스트(V-GE-*)

- V-GE-1 `paicad_*` 키 검증: argv[0] `{paicad}`만, 다른 키에 `{paicad}` 거부, 허용 placeholder 밖 거부.
- V-GE-2 플랫폼 패키지에서 `paicad`·`OCP` import 없음(계층 시험).
- V-GE-3 paicad가 출력 존재 시 덮어쓰지 않음(3 `GEOM_OUTPUT_EXISTS`), 워커는 실행 전 `_backup` 이동.
- V-GE-4 무변경 왕복 include 바이트 동일, 변경 시 `/NODE` 좌표 필드 외 diff 없음.
- V-GE-5 PREDICT native: TPL_RENDER→values.json, GEOM_UPDATE/MESH 판정, RAD_ASSEMBLE 기존 규칙, 실패 시 step 코드 = `GEOM_*`.
- V-GE-6 일괄·DOE: 실패 run `gen_code`/`SKIPPED.json`·category, 나머지 run 계속, 성공 0이면 작업 실패.
- V-GE-7 DOE native run 폴더가 `run_dir_glob` 기본값에 맞고 paramitem 추출 값 = 행렬 값.
- V-GE-8 엔진 혼용 409/422, altair 기존 시험 전부 통과.
- V-GE-9 고급 옵션 저장·병합·범위 검사, 사용값 `options.json` 기록, tag 절 변경 시 STALE.
- V-GE-10 migration 0012 업그레이드·기존 행 기본값·CHECK.
- V-GE-15 쉘 두께(§11.1): TYPE1만 적용·TYPE9/10/11 '미지원' 표시, 출력 diff = 지정 PROP 두께 필드만(고정폭 보존), 원본·SPDM 불변, 공유 PROP 경고, 요소별 두께 → `PROP_OVERRIDDEN_BY_ELEMENT`, 두께 ≤0 → `PROP_THICKNESS_INVALID`, 두께만 있는 param_set 동작, 파라미터 표 병합·XML 호환, altair 경로 무변경.
- V-GE-11 버전(§17): `packages/paicad` 변경 커밋마다 `__version__` 올림·CHANGELOG 최상단 항목 일치(test-all 검사 존재·통과), native JSON·옵션 사용값·DB에 `engine_version` 기록, 출력 include에 버전 주석 없음.
- V-GE-12 altair 경로 불변(§1.4·§16): 기존 altair 시험 무수정 통과, 분기 지점 밖 altair 코드 diff 없음.
- V-GE-13 독립성(§18.1·18.5): `packages/paicad`가 `physicsai_core`·`backend`·`worker`·`physicsai_worker`를 import하지 않음(검사 존재·통과, 위반 주입 시 실패 확인), 플랫폼 패키지·DB·`platform.yaml` 없이 `pytest packages/paicad` 단독 통과, 자체 `pyproject.toml`·`CHANGELOG.md`·제3자 라이선스 고지 파일 존재.
- V-GE-14 paicad 내 플랫폼 고유 파일명·경로 하드코딩 없음(§18.1): `predict.*` 출력 파일 이름(`104_replace_node_elem.inc`·`RENUM_INIT.csv` 등)·플랫폼 폴더 레이아웃(`radioss_assem/` 등)이 `src/`에 리터럴로 없음(시험 fixture·문서 예시 제외), 모두 CLI 인자·입력 JSON 경유. paicad 메시지는 영문(한국어 문자 없음, §18.4).

---

## 15. 미결 사항(사용자 확인 필요)

| # | 질문 | 임시 결정(이 문서 기본값) |
|---|---|---|
| Q1 | 공칭 STEP과 기준 메시(SimLab `EPS_mesh` → m_2 include) 좌표가 같은 원점·단위·형상인가? SimLab 디피처링(작은 필렛 제거 등)이 있나? | 일치 가정. 불일치는 `GEOM_BASELINE_MISMATCH`로 차단(자동 정렬 없음). 디피처링된 면은 피처에서 제외 |
| Q2 | 두께 기준면 규칙: 제품·타 바디 접촉면 고정, 반대 면 이동이 맞나? 둘 다 접촉/둘 다 비접촉일 때는? | `contact_fixed` + 동률이면 면적 큰 면 고정, `ref.confirmed=false` |
| Q3 | `104_replace_node_elem.inc` 헤더에 `/PART`·`/PROP`(·`/MAT`)가 포함되나, 아니면 노드·요소만인가? | R1은 `/NODE`만 바꾸므로 무관하게 원문 보존. 3S는 조립 폴더 전체 scan이라 무관 |
| Q4 | ~~쉘 두께 `/PROP/SHELL`을 파라미터 범위에 넣나? PROP 정의 위치?~~ | **해결(2026-10-17)**: TYPE1 두께 포함(단계 3S, §11.1), 위치는 `props scan`이 조립 폴더에서 발견, TYPE9/10/11 비범위 |
| Q13 | 쉘 두께(3S)를 altair 경로에도 적용하나? 모핑 실패 재메시 폴백(§11.2)을 언제·어떤 메셔로? | altair 미적용(GE-11, 1차 native만). 재메시는 후속 옵션, 미구현 |
| Q5 | `RENUM_INIT.csv` 실제 형식이 `part,node_start,elem_start`이고 part = 쿠션 component 이름인가(코드에는 파일 이름만 있음)? 쿠션 외 part 행이 있나? | 사용자 진술대로. 쿠션 외 행은 STEP 바디가 없으면 `GEOM_BODY_MAP_FAILED` — 있으면 `body_map.json`에 `"<part>": null`(고정) 지원 여부 결정 필요 |
| Q6 | `mesh_only` 템플릿(조립 폴더 없음)도 native가 필요한가? | 미지원(기준 메시 없음). 필요하면 세트에 `baseline/EPS_mesh_0000.rad`를 두는 변형을 별도 결정 |
| Q7 | tie 정의 해석 실패 시 실패(엄격)로 할지 경고로 할지, 기본 dsearch 값 | 경고(`NOT_EVALUATED`), 기본 dsearch = 공칭 최대 거리 × 1.5 |
| Q8 | 품질·편차 기본 기준값(min Jacobian 0.2, aspect 10, 경계 0.05 mm, 파라미터 1%)이 사내 메시 기준과 맞나? | 표 값 |
| Q9 | 대칭 그룹을 자동으로 묶을지, 사용자가 풀 수 있어야 하는지 | 자동, 풀기 UI 없음(후속) |
| Q10 | cadquery-ocp 고정 버전과 사내 보안 승인(wheel 출처 PyPI) | Impl이 cp312 win_amd64 wheel 확인 후 고정, 사용자 승인 필요 |
| Q11 | 같은 native 데이터셋에 paicad MINOR가 다른 run이 섞일 때 경고로 충분한가, 차단(422)해야 하나? 모델 등록·예측 때 모델의 `engine_version`과 현재 paicad MINOR가 다르면? | 데이터셋 경고 `ENGINE_VERSION_MIXED`(차단 아님, §17.4). 예측 시 비교는 1차 없음 |
| Q12 | 출력 include에 `# paicad x.y.z` 주석 줄을 허용할지(추적 편의 vs 바이트 동일 원칙) | 불허(§17.3). 허용하려면 V-GE-4·§6.4 예외 규칙을 함께 고쳐야 함 |

---

## 16. native 분기 지점(최소 변경 — Plan 확인 결과)

원칙(GE-11, §1.4): 아래는 **기존 코드 리팩터링 대상이 아니라** native가 끼어드는 분기 지점이다. 각 지점은 `engine == "native"`일 때만 새 경로(native 전용 모듈·함수)로 보내고, altair 경로의 코드·기본값·출력·오류 코드는 그대로 둔다. 공용 함수를 일반화·재구성해야 하면 구현 전 변경 메모(`GE-C*`)로 Plan 확인. 판정: altair 기존 시험 무수정 통과(V-GE-8).

1. `commands.py` `EXECUTABLE_PLACEHOLDERS`·`effective_altair`(Altair 6종) → **추가만**: `{paicad}` 항목, `effective_executables` = 기존 `effective_altair` 결과 + `paicad_path`. `effective_altair`의 이름·반환은 유지(기존 호출부 무수정, §7.1).
2. `predict_inputs.geom_update`·`batch.bp_gen`의 `commands.geom_update is None` 검사, `features.predict_parametric` → 핸들러 **맨 앞** 엔진 분기 1곳에서 native 함수(`param_set_native`·`geometry_native`)로 위임, altair 본문 불변(§7.3.5·7.3.7).
3. `param_sets.validate_folder`·`param_discover.discover` → `engine` 인자(기본 `"altair"`) 추가, native면 별도 함수로 위임(tpl·`.prt` 규칙은 altair 그대로). DB `param_sets.tpl_rel NOT NULL` → migration으로 NULL 허용 + CHECK(altair 행은 여전히 NOT NULL 강제, §7.4·7.5).
4. `assemble_into` → **무수정 호출**. 기준본 부재 오류는 native 등록·검증 단계(`BASELINE_INC_MISSING`)에서 먼저 막고, `assemble_into`의 경고(`MESH_INCLUDE_NOT_IN_ASSEM`) 동작은 그대로.
5. `RENUM_INIT.csv` 내용 형식은 코드·문서 어디에도 정의되지 않음(파일 이름과 TCL 전달뿐) → native만 읽는다(altair는 계속 TCL에 이름만 전달). 형식 → Q5.
6. `docs/manual/admin.md` §4.3 `predict` 표에 폐지된 `predict.mesh_output_glob`가 남아 있고 `commands.mesh` 기본값을 null로, §5.3 `geom_update`·`mesh` 성공 판정을 phase3 §11.4 이전 내용으로 적고 있음 → 코드 분기 아님. 이 계약과 별개로 Plan 후속 정정 대상.
7. 워커 자식 환경 허용목록(B19)에 스레드 변수 없음 → 허용목록은 바꾸지 않고 native 실행에만 `geometry.env`로 전달(§7.1).

---

## 17. 버전·변경 이력

### 17.1 paicad 버전

| 항목 | 규칙 |
|---|---|
| 체계 | SemVer, `0.1.0`부터(0.x 동안은 아래 MINOR/PATCH 기준만, MAJOR는 1.0 이후) |
| 단일 출처 | `packages/paicad/src/paicad/__init__.py`의 `__version__ = "x.y.z"`(문자열 리터럴 1줄, 이 모듈은 OCP·numpy를 최상위 import하지 않음). `packages/paicad/pyproject.toml`은 `[project] dynamic = ["version"]` + `[tool.setuptools.dynamic] version = {attr = "paicad.__version__"}`로만 참조(정적 `version =` 금지) |
| 노출 | `paicad --version` → `paicad x.y.z`, `paicad version --json`의 `paicad` 값(§5.3), `paicad.log` 머리줄 |
| 플랫폼 고정 | 루트 `pyproject.toml` `paicad==x.y.z`·`deploy/requirements.local.lock`은 `__version__`과 같아야 함(§17.5 검사) |

### 17.2 변경 규칙

- `packages/paicad/**` 를 바꾸는 **커밋마다** `__version__`을 올리고 `packages/paicad/CHANGELOG.md` 최상단에 항목을 추가한다(같은 커밋).
- 항목 형식:

  ```markdown
  ## 0.2.0 — 2026-10-20
  - 변경: <무엇을 바꿨나>
  - 영향: <출력 형상·좌표·판정이 달라질 수 있나 / 결과 불변>
  - 계약: geometry-engine.md §6.4 (해당 없으면 "없음")
  ```

- 올림 기준:

| 단계 | 기준 | 예 |
|---|---|---|
| MAJOR(1.0 이후) | 출력 호환 깨짐(출력 파일 이름·필수 키·CLI 인자·종료코드 의미 변경) | `check.json` 필수 키 삭제 |
| MINOR | 같은 입력·옵션에서 출력 결과(형상·좌표·판정)가 달라질 수 있는 변경. 0.x에서는 호환 깨짐도 MINOR(+CHANGELOG "영향"에 `호환 깨짐` 명시, `schema_version` 올림) | 모핑 강성 식, 피처 인식 규칙, 검사 기본값 |
| PATCH | 결과 불변 수정(같은 입력 → `morphed.inc`·보고 수치 바이트 동일) | 로그 문구, 성능, 리팩터링, 시험 추가 |

- 결정성(§5.2 "같은 입력·옵션·버전이면 같은 출력")의 "버전" = 이 `__version__`. PATCH 올림 시 §10 결정성 시험의 기준 출력이 바뀌면 PATCH가 아니다(MINOR로 올림).

### 17.3 출력 스키마 버전·기록 위치

- `schema_version`(정수)은 **JSON 파일 형식** 버전으로 엔진 버전과 별도다. 키 추가(선택 키)는 그대로, 키 삭제·의미 변경·필수 키 추가 시 올린다. 플랫폼 `physicsai_core/geometry/reports.py`는 아는 `schema_version`만 읽고 모르면 `INPUT_INVALID`.

| 위치 | 기록 |
|---|---|
| paicad JSON 출력 전부(`tag.json`·`parameter_features.json`·`update.json`·`morph.json`·`check.json`, `run` 요약) | 최상위 `schema_version`, `engine:"native"`, `engine_version:"<__version__>"`(paicad가 씀) |
| 플랫폼이 쓰는 native JSON(`native/prep.json`, `R/SKIPPED.json`, `values.json`) | 같은 세 키. `engine_version`은 그 작업 준비 step의 `paicad version --json` 값 |
| run·작업 폴더 옵션 사용값(`P/geom/options.json`, `R/options.json`, `D/native/options_run.json`) | `engine`·`engine_version`(§4.9) |
| `B/batch.json`(§7.3.7) | `engine:"native"` + `engine_version`. DOE(`D`)는 `D/native/prep.json`·`options_run.json`으로 충분(새 메타 파일 없음) |
| 출력 include(`morphed.inc`, `R/m_2/{mesh_include_name}`) | **버전 주석 불허**(1차). §6.4 "기준본과 바이트 동일, `/NODE` 좌표 필드만 다름"·V-GE-4 무변경 왕복 바이트 동일과 충돌하므로 첫 줄 `# paicad x.y.z` 등 줄 추가·변경 금지. 버전 추적은 같은 폴더의 `check.json`·`R/options.json`으로 한다 |
| DB(migration 0012, §7.5) | `param_sets.engine_version`(준비본 생성 시), `train_does.engine_version`, `predict_batch_runs.engine_version`(run 생성 시), `datasets.engine_version`(단일이면 그 값, 섞이면 NULL + 경고) — `VARCHAR(32) NULL`, altair 행은 NULL |
| 준비본 유효성(§4.2) | `prep.json.engine_version`의 MAJOR.MINOR가 현재 paicad와 다르면 `prep_status=STALE`(PATCH 차이는 READY) |

### 17.4 데이터셋 혼용 판정(기본값, 미결 Q11)

- 엔진 혼용(altair·native)은 §7.7대로 422.
- 같은 engine(native) 안에서 `engine_version`의 **MINOR가 다른 run이 섞이면 경고**(차단 아님): DATASET_CREATE 작업 경고 `ENGINE_VERSION_MIXED` "형상 엔진 버전이 다른 학습데이터가 섞였습니다(0.2.x, 0.3.x) — 형상 결과가 다를 수 있습니다", `datasets.engine_version=NULL`. PATCH만 다르면 경고 없음. 버전 판별 불가(NULL)는 경고 없이 통과.

### 17.5 검증·플랫폼 쪽 버전

- `scripts/test-all` 검사(Impl-Backend, §13): (1) `packages/paicad/**` 가 비교 기준과 다르면 `__version__`도 달라야 함 — 비교 기준: 작업 트리에 `packages/paicad` 변경이 있으면 `HEAD`, 없으면 `HEAD~1`(CI는 PR base). (2) 항상: CHANGELOG 최상단 `## x.y.z — YYYY-MM-DD` 의 버전 == `__version__`, `pyproject.toml`에 정적 `version` 없음, 루트 `paicad==` 고정·`requirements.local.lock` == `__version__`. 실패 메시지 한국어.
- 플랫폼 쪽 native 연동 코드(backend·worker의 native 분기, `physicsai_core/geometry/`)는 별도 버전을 두지 않고 기존 플랫폼 버전(루트 `pyproject.toml`)을 따른다. 대신 native 분기 동작을 바꾸면 `docs/decisions.md`에 1줄 기록(Plan에 요청).

---

## 18. 독립성(향후 분리 대비)

결정(2026-10-17): paicad는 향후 독립 플랫폼(별도 저장소·제품)으로 분리될 가능성을 염두에 두고 개발한다. 지금은 physicsai-platform 안의 엔진(`packages/paicad`)으로 운영한다.

### 18.1 의존 방향
- paicad → 플랫폼 방향 의존 금지: `physicsai_core`·`backend`·`worker` import 금지, DB·`platform.yaml` 직접 읽기 금지.
- 플랫폼 고유 값(출력 파일 이름 `predict.*`, 폴더 경로, 옵션)은 CLI 인자·입력 JSON으로만 받는다. paicad 내부 하드코딩 금지(§5.3 `--baseline-inc`·`--out-inc`·`--renum-csv`·`--assem-dir`이 그 통로). §4·§5의 예시 값은 문서 예시일 뿐 기본값이 아니다.

### 18.2 경계
입출력은 **파일 + CLI + 버전 있는 JSON 스키마**(§4, §17.3 `schema_version`)뿐이다. 프로세스 내 호출·공유 메모리·공유 모듈 없음.

### 18.3 솔버 writer 플러그인
- `packages/paicad/src/paicad/writers/` 레지스트리 인터페이스: 입력 = 노드 좌표 갱신 결과(노드 ID→새 좌표, 기준 파일 경로), 출력 = 솔버 입력 파일. 선택은 CLI 인자(`--solver`, 기본 `radioss`)·입력 JSON.
- 1차는 Radioss만 구현(§6.4 바이트 보존 규칙). LS-DYNA·Abaqus는 **비범위**(인터페이스만, 구현·시험 없음).

### 18.4 메시지
paicad는 실패 코드(§6.5 표)와 **영문 기술 메시지**만 낸다(`message`·`PAICAD PROGRESS`·로그). 사용자 표시 한국어 문구는 플랫폼이 code→문구 매핑으로 만든다(AGENTS.md 한국어 규칙은 플랫폼 쪽에서 충족).

### 18.5 패키지 자립
자체 `pyproject.toml`, 자체 테스트(플랫폼 없이 `pytest packages/paicad` 단독 실행), 자체 버전·CHANGELOG(§17), 제3자 라이선스 고지 파일(`packages/paicad/THIRD_PARTY_NOTICES.md`: OCCT LGPL·cadquery-ocp·numpy·scipy 등) 포함.

### 18.6 강제
§13 검사 행(import 금지·단독 테스트·하드코딩·고지 파일), §14 V-GE-13·V-GE-14.

### 18.7 분리 시점 기준(결정 기록용, 하나라도 충족 시 분리 검토)
(1) 쿠션 외 2종 이상 대상 검증, (2) 다른 조직의 플랫폼 외 사용 요청, (3) 솔버 2종 이상 지원.

---

## 변경 메모

(구현 중 계약과 다르게 해야 하면 여기에 `GE-C1~`로 기록하고 Plan 확인을 받는다.)
