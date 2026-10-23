# 계약: 조립 매칭(STEP 바디 ↔ 조립 component) — Native 솔리드의 renum.csv·기준본 파일 요구 제거

> 상태: **확정**(2026-10-22, Plan — 초안 7a8bfcd + 사용자 답변 Q1~Q3 반영, AM-C1). 릴리스 **v0.2.9**(paicad **0.13.0**, 이 계약은 migration 없음 — v0.2.9의 `0022_job_queues`는 대기열 분리 몫, [roadmap.md](../roadmap.md)). 기준 커밋 def0517(v0.2.8 진행 중, migration HEAD `0021_uploads`, paicad 0.12.0).
> 상위: [geometry-engine.md](geometry-engine.md)(GE, R1 모핑·§4.1 component 대응·§6.1 tag·§6.4 쓰기 형식), [shell-morph.md](shell-morph.md)(SM, `/PART` 기반 대응 선례), [geometry-view.md](geometry-view.md)(GV, 3D 뷰어·FE GLB), [input-kind.md](input-kind.md)(IK, `paicad cushion write`), [native-vars.md](native-vars.md)(변수 정의 — 영향 없음), [upload-report.md](upload-report.md)(조립 폴더 업로드). 이 문서가 바꾸는 규칙은 §2.3(이 문서 우선).
> ID 규칙: 결정 `AM-n`, 시험 `V-AM-n`, 변경 메모 `AM-Cn`.

## 0. 한 줄 요약

Native 솔리드 흐름(①-3 DOE, ④ 세트 등록)에서 조립 폴더에 `RENUM_INIT.csv`와 기준본 파일(`104_replace_node_elem.inc` 등 **어떤 파일 이름도**)을 요구하지 않는다. starter에서 **include 트리 전체**를 읽어 `/PART`·요소·노드를 어느 파일에 있든 모으고, 사용자가 **STEP 바디(행) ↔ 조립 component(옆 열 드롭다운)** 매칭 표(추천으로 미리 채움)를 확인·수정해 저장(확정)한다. **component 외곽 노드 좌표 ↔ CAD B-rep 경계면 거리 검사**는 고급 옵션이며 저장의 조건이 아니다(AM-C3). 기준본 = **매칭된 PART id의 노드·요소 집합**이고, 모핑 결과는 조립 사본에서 그 노드 ID가 있는 **모든 파일의 해당 `/NODE` 줄 좌표 필드만** 바꿔 쓴다(R1: 노드 ID 불변, 열 폭 유지, 다른 줄 바이트 동일). 쿠션 단독 rad도 같은 수집 결과로 만든다.

---

## 1. 배경·범위

### 1.1 사용자 근거(원문, 2026-10-22)

> "stp파일 올리고 파라미터 생성햇고 파라미터 선택햇어. 조립파일 올렷어. renum.csv랑 baseline.inc를 원하네. 이런거 없게 하려고 native인데. 차라리 조립폴더에서 component 목록 확인하고 거기에서 내가 해당 step파일과 동일한 조립내 component와 step파일 내 compound랑 매칭하게해. compound 목록이 뜨고 옆 열에 조립목록내 component선택해 매칭하는거지. 거기서 외곽 노드 좌표랑 캐드 경계면과 일치하는지 체크도하고."

답변(2026-10-22): 실제 조립은 `101_parts.inc`(`/PART`, 요소 형식, `/INTER/TYPE2` 등, 노드·요소 세트)와 `102_parts_node_element.inc`(노드·요소)로 나뉜다. "파일이름으로 픽스하지 말고 결국 전체 읽어야 할 듯. 파일 저장 구성이 어떻게 될지 모르니까."

### 1.2 현재 동작(코드 확인, def0517)

| 파일 | 출처(원래 흐름) | Native에서 하는 일 | 요구 위치 |
|---|---|---|---|
| `RENUM_INIT.csv`(`predict.renum_csv_name`) | Altair 흐름에서 HyperMesh include TCL(`commands.mesh`, `{renum_csv}`)이 SimLab 쿠션 메시(`EPS_mesh_0000.rad`)의 노드·요소 번호를 component별 예약 구간으로 재지정할 때 쓰는 **사용자 준비 표**(`part,node_start,elem_start`) | 기준본 TETRA4 요소를 `elem_start` 구간으로 잘라 component(이름·순서)를 만든다(GE §4.1, `paicad/mesh/radioss.py: components()`). 바디 ↔ component 이름 대응, 파라미터 순서, `cushion write`의 쿠션 요소 선택 | API `job_params/stage1_native.py: native_doe_gen`(409 `PREREQUISITE_MISSING` missing `RENUM_CSV`), 워커 `doe_native.dg_prep`(`INPUT_INVALID`), `param_discover_native.py`(problems `RENUM_CSV_MISSING`), paicad `tag`·`check`·`run`·`selftest`·`cushion write`·`view preview --fe`(필수 인자 `--renum-csv`) |
| `104_replace_node_elem.inc`(`predict.mesh_include_name`) | Altair 흐름 m_2(HyperMesh 변환)의 **산출물** = 공칭 형상 쿠션 메시 include(노드·요소만 — GE Q3) | R1 기준본: tag 대상 노드·요소, morph가 `/NODE` 좌표만 바꿔 같은 이름으로 다시 쓰는 파일, 조립(`assemble_into`)에서 이 이름의 파일을 새 include로 통째 교체 | 같은 위치(missing `BASELINE_INC`·`BASELINE_INC_MISSING`), 프런트 `NATIVE_ASSEM_TEXT`·`BASELINE_INC_MISSING` 문구, `assembly_sources`·`assemble_into` |

결론: 두 파일 모두 SimLab/HyperMesh 체인의 입력·산출물이다. Native에 실제로 필요한 것은 ① 어느 요소·노드가 어느 쿠션 바디인지 ② 그 노드 좌표를 어디서 고쳐 쓰는지뿐이다. ①은 요소 블록 머리 `/TETRA4/<part_id>`와 `/PART/<id>` 제목으로 얻고, ②는 include 트리에서 노드 ID가 정의된 줄을 찾아서 얻는다. 파일 이름에는 기대지 않는다.

### 1.3 범위 / 비범위

| 범위 | 비범위 |
|---|---|
| Native **솔리드**(TETRA4) ①-3 DOE(①-1 추출 기준)·④ 세트 등록(새 Native 템플릿 STEP)·①→④ from-train, 그 뒤 ④ 단건·일괄·⑥ 내장·쿠션 rad(IK) | Altair 경로(GE-11, 무변경), 쉘 경로(이미 `/PART` 기반), 다중 baseline(4B — 기존 RENUM 방식 유지, §7), TETRA10·HEXA(GE §1.3) |
| include 트리 전체 수집, 매칭 표(추천 + 사용자 확정), 경계 일치 검사, 3D 불일치 표시, 다중 파일 `/NODE` 줄 갱신, 파싱 캐시 | 자동 정렬(강체 맞춤·스케일 보정) — 감지·안내 후 차단(AM-5) |
| RENUM 구간·기준본 파일 대체 알고리즘, `mesh_include_name` 의존 전수 제거(매칭 세트), 기존 renum 세트 호환 | 재메시·번호 재지정(GE-1) |

---

## 2. 용어·결정

### 2.1 용어

| 용어 | 뜻 |
|---|---|
| 바디(compound 행) | 공칭 STEP의 이름 있는 솔리드 = `parameter_features.json` `bodies[]` 한 항목(GE §4.3). 사용자가 말한 "compound" 행. 이름 없는 바디는 GE §4.1처럼 오류 |
| component | 조립의 `/PART/<pid>`(제목 = `/PART` 다음 줄). 요소 블록 `/<KW>/<pid>`로 소속을 정한다 |
| include 트리 | starter(조립 폴더 직계 `predict.starter_glob` 정확히 1개, IK-C1 판별 규칙)에서 `#include` 연쇄로 닿는 모든 파일(상대 경로, 하위 폴더 허용). 수집·digest·복사의 단위 |
| 매칭 행 | `{body, pids[]}`. 바디 1개 ↔ component ≥1개(AM-4) |
| 기준 메시(쿠션 집합) | 매칭된 모든 pid의 **TETRA4 요소 + 그 노드** 집합. 파일과 무관(AM-1). RENUM 방식의 기준본 자리 |
| 노드 위치표 | 기준 메시 노드마다 정의된 파일·줄(`node_id → (rel, line_no)`). 쓰기의 근거 |
| 노드 패치 | 모핑 PASS 결과 `node_patch.npz`(`node_id:int64[n]`, `xyz:float64[n,3]`) — 매칭 세트의 출력(include 파일 대신) |
| 외곽 노드 | 매칭 행 요소 합집합의 외피(한 요소에만 속한 면) 노드 |
| 매칭 묶음 | `<study>/asm_match/<match_id>/` — 목록·초안·검사·확정본 |

### 2.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| AM-1 | 기준본 = **매칭 PART id의 노드·요소 집합**. component 정의 = `/PART` id 집합(매칭 표). `RENUM_INIT.csv` 요구와 **파일 이름 의존 전부** 제거 | 사용자 원문·답변 Q1 |
| AM-2 | 매칭은 **추천은 초안, 확정은 사용자**(GE-13과 같은 원칙). 저장 = 확정. ~~저장 전 경계 검사 PASS 필수~~ → **경계 검사는 선택(고급)**, 불합격·낡음은 경고만(AM-C3, 2026-10-23) | 오매칭 시 학습데이터 전체 오염 → 추천 알고리즘으로 충분(사용자 결정) |
| AM-3 | 경계 검사 허용오차 = tag와 **같은 값·같은 식**(`geometry.defaults.tag`: `tol = max(tol_abs_mm 0.05, tol_rel 1e-4 · L_body)`, `match_ratio ≥ min_match_ratio 0.98`). 새 허용오차 키 없음 | 검사 PASS면 tag의 `GEOM_BASELINE_MISMATCH`가 나지 않음을 보장(단일 출처) |
| AM-4 | 바디 1 ↔ component N(1:N) 허용(요소 합집합 = 한 component), component 1 ↔ 바디 N 금지, component는 한 행에만 | CAD 1바디가 메시에서 여러 PART로 나뉘는 경우 수용 |
| AM-5 | 좌표계·단위 차이는 **감지·안내하고 진행을 막는다**(`ASM_OFFSET_SUSPECT`·`ASM_UNIT_SUSPECT`는 FAIL 행의 진단, 저장 불가). 자동 보정·사용자 보정 적용 없음 | **사용자 확정 Q2**, GE Q1 유지 |
| AM-6 | 노드 ID·요소·연결 불변, 매칭 pid 노드의 좌표만 변경. 조립 사본에서 그 노드가 정의된 **모든 파일의 해당 `/NODE` 줄 좌표 필드만** 바꾸고(GE §6.4 형식·열 폭), 다른 줄·다른 파일은 바이트 동일 | **사용자 확정 Q1**, GE-1 |
| AM-7 | 수집 = starter include 트리 **전체**. `/PART`·요소·노드가 어느 파일에 있든, 쿠션 노드·요소가 다른 PART와 같은 파일에 섞여 있든 허용. 쿠션이 여러 파일에 나뉘어도 FAIL 아님 | 사용자 확정 Q1("파일 저장 구성이 어떻게 될지 모름") |
| AM-8 | 매칭 PART 노드를 **매칭 안 된 PART 요소가 참조하면 FAIL 유지**(`ASM_SHARED_NODES`), 보고에 공유 노드 수와 상대 PART(id·제목·노드 수)를 낸다 | R1이 다른 component를 바꾸지 않음, 사용자 확정 Q1 |
| AM-9 | paicad 기존 명령은 메시 출처를 두 방식 중 하나로 받는다: 기존 `--baseline-inc`+`--renum-csv` **또는** `--asm-match`+`--assem-dir`(§6.1). 기존 argv 그대로 유효 | GE-C10 동결 인자 호환 |
| AM-10 | 플랫폼은 설정 템플릿을 고치지 않고 정해진 인자 쌍을 바꿔 끼운다(§6.2, GE §7.3.1 쌍 규칙과 같은 방식) | 관리자 설정 변경 없이 배포 |
| AM-11 | 대용량 조립은 **스트리밍 파싱 + 파일 sha256 기준 캐시**(`<study>/_cache/asm_parse/`)로 대응 | 사용자 확정 Q1(대용량 리스크 대응) |
| AM-12 | 저장 위치 = Study 아래 `asm_match/<match_id>/`, 소비자(DOE·세트)는 확정본을 자기 폴더로 복사·sha256 기록. **이 계약의 DB 변경 없음**(상태는 파일 + 작업 행) | SPDM 쓰기 금지 |
| AM-13 | 기존 RENUM 세트·DOE는 그대로 동작. 새 요청은 `asm_match_id`가 있으면 매칭 경로, 없으면 기존 검사(두 파일 모두 있을 때만) | 호환 |

### 2.3 기존 계약에서 바뀌는 규칙(이 문서 우선)

| 기존 | 변경 |
|---|---|
| GE §4.1 번호 표 "native 필수(`RENUM_CSV_MISSING`)" | 매칭 세트는 불필요. component 요소 집합 = 매칭 행 pid들의 `/TETRA4/<pid>` 블록 합집합(§5.1) |
| GE §4.1 기준본 `S/radioss_assem/{predict.mesh_include_name}` 고정 파일 | 매칭 세트는 기준 메시 = 매칭 pid 노드·요소 집합(파일 무관, §5.2). `{mesh_include_name}` 출력 파일을 만들지 않고 노드 패치를 낸다 |
| GE §6.4 morph·check 출력 = 기준본과 같은 이름·형식의 include 1개 | 매칭 세트는 노드 패치 → `paicad asm write`가 조립 사본의 해당 `/NODE` 줄만 고침(§5.4) |
| phase3 §11.4 `assemble_into`(직계 파일 복사 + `mesh_include_name` 파일 교체) | 매칭 세트는 include 트리 복사(상대 경로 유지) + 노드 줄 갱신(§5.4). 교체할 파일 이름 없음 |
| GE §2.3 `MESH_INCLUDE_NOT_IN_ASSEM` → native 오류 `BASELINE_INC_MISSING` | 매칭 세트에는 적용하지 않음 |
| GE §4.1 바디 대응 규칙 1~4·`body_map.json` | 매칭 세트는 `asm_match.json`이 유일한 대응. `body_map.json`이 함께 있으면 무시 + 경고 `BODY_MAP_IGNORED` |
| GE §6.5 간섭 대상 = 기준본 파일 제외 전 조립(직계 파일) | 매칭 세트는 include 트리 전체에서 **매칭 pid 요소만 제외**(같은 파일 안 다른 PART는 제품으로 포함) |
| IK §5.2 `cushion write --inc`(모핑 include에서 쿠션 추출) | 매칭 세트는 include 트리 수집 결과 + 노드 패치로 작성(§5.5) |
| GV §2.3 레인 `PREVIEW` 허용 명령 | `paicad_asm_parts`·`paicad_asm_check` 추가 |
| `stage1_native.native_doe_gen` missing `BASELINE_INC`·`RENUM_CSV` | `asm_match_id`가 없고 두 파일도 없으면 missing `["ASM_MATCH"]`(§6.4) |

---

## 3. 흐름·화면

### 3.1 흐름

```text
①-1 STEP 업로드·추출(기존) → ①-2 파라미터 선택(기존)
  → [조립 매칭 카드] 조립 폴더 지정(경로 또는 업로드 RADIOSS_ASSEM)
      → 작업 ASM_MATCH(mode=parts): paicad asm parts(include 트리 수집·캐시) → component 목록 + 추천
      → 매칭 표(추천 자동 채움) 확인·편집 → "저장"(PUT rows + confirm) → asm_match.json 확정
      (고급·선택: "검사" → 작업 ASM_MATCH(mode=check): paicad asm check — 시간 제한 없음·취소 가능, 불합격은 경고만, AM-C3)
  → ①-3 DOE(asm_match_id) → dg_prep: include 트리 사본 + D/cad/asm_match.json → tag(--asm-match)
      → run마다 update → morph → check(PASS = node_patch.npz) → paicad asm write(조립 사본 노드 줄 갱신)
④ "새 Native 템플릿(STEP)": 등록 폼에서 STEP·조립 폴더 지정 → 같은 매칭 카드(바디 목록은 STEP에서 직접) → PARAM_SET_NATIVE(asm_match_id)
```

renum.csv와 어떤 기준본 파일 이름도 어느 단계에서 묻지 않는다.

### 3.2 매칭 표(필수 요소만, 라이트 테마, 2560×1440 기준)

위치: ① 화면 `ParamTableCard` 아래·`DoeGenCard` 위 새 카드 "조립 매칭"(Native 솔리드일 때만), ④ 등록 폼의 조립 폴더 칸 아래 같은 컴포넌트. 카드 폭 = 기존 카드 폭, 표 60% · 3D 창 40%(GV 뷰어 재사용).

| 열 | 내용 |
|---|---|
| STEP 바디 | 이름 · 부피(cm³, 유효 3자리) · bbox 크기(mm, `X×Y×Z`) |
| 조립 component | 드롭다운(검색 가능): `PART id · 제목 · TETRA4 n개`(추천 점수순, 추천 항목에 "추천" 표지). 행 안 "+ component"로 1:N 추가(칩), "매칭 안 함" 항목 |
| 판정 | 검사 전 `—`, 이후 `일치`/`불일치`/`검사 필요`(행 변경 시) |
| 거리 | `최대 x.xxx · p95 x.xxx mm · 일치율 99.6%`(검사 후) |

- 카드 머리: 조립 폴더 경로 · starter 이름 · "파일 12개 · component 213개(TETRA4 4개)" · 단추 `추천 적용` `검사` `저장`.
- 표 아래 한 줄: "매칭하지 않은 component 209개는 바꾸지 않습니다(간섭 검사 대상)".
- 드롭다운은 TETRA4만 가진 PART만 선택 가능, 그 밖은 회색 + 사유("TETRA4가 아님: /SHELL 1200개"). 다른 행에서 고른 PART는 회색("CUSH_R 행에서 사용").
- "매칭 안 함": 그 바디에 `use=true` 파라미터가 있으면 선택 불가(사유 "선택한 파라미터 N개가 이 바디에 있습니다"). 매칭 안 한 바디는 tag·morph 대상에서 빠진다.
- 행 클릭 → 3D 창: CAD 바디 반투명 + 외곽 노드 표면을 거리 색 맵(`_DIST_MM`, 0 ~ tol 녹색, tol 초과 빨강), 불일치 노드 상위 N개 점 표시. 실패 행은 실패 코드 문구를 표 아래에 한 줄씩(공유 노드는 "PART 2001(PRODUCT_TIE) 등과 노드 37개 공유").
- 원점·단위 진단이 있으면 그 행 아래에 "CAD가 조립보다 X 10.0 mm 어긋나 있습니다 — CAD를 조립과 같은 원점·mm로 다시 내보내세요"(저장 불가, AM-5).
- 단추 상태: `저장` = 모든 행이 선택 또는 "매칭 안 함" + 매칭 행 ≥1(검사 불필요, AM-C3). `검사`(고급 접힘 안) = 같은 조건. DOE `생성` 단추 사유 문구에 "조립 매칭을 저장하세요" 추가. (v0.2.9 원안 "저장 = 마지막 검사 PASS"는 AM-C3으로 폐지)

---

## 4. 파일 계약

모든 JSON은 GE §4 공통 규칙(UTF-8, `schema_version: 1`, `engine`·`engine_version`, mm-ton-s, 변환 없음, `geometry.max_report_bytes` 이하).

### 4.1 매칭 묶음 `<study>/asm_match/<match_id>/`

| 경로 | 작성 | 내용 |
|---|---|---|
| `match.json` | 플랫폼 | `{schema_version, match_id, state, source:{kind:"train"\|"path", cad_rel, features_rel\|null}, assem:{path(표시용), digest}, rows:[…], excluded_bodies:[…], rows_sha256, last_check:{seq, status, rows_sha256}\|null, created_by, created_at, updated_at}` — 초안·상태 |
| `parts/asm_parts.json` | `paicad asm parts` | §4.2 |
| `check/<seq>/asm_check.json`, `check/<seq>/match_fe.glb`, `check/<seq>/worst_<body>.npz` | `paicad asm check` | §4.3. 최신 seq만 표시 |
| `asm_match.json` | 플랫폼(confirm) | §4.4 확정본(소비자가 복사) |

`state`: `SCANNING → DRAFT → CHECKING → CHECKED → CONFIRMED`, 실패 `FAILED`(목록 작업 실패), 입력 변경 `STALE`. 확정 후 행을 바꾸면 새 `match_id`(확정본 불변).

`assem.digest` = include 트리 파일의 (상대 경로, sha256)을 경로순 정렬한 목록의 sha256(`"sha256:<hex>"`). 트리 밖 파일은 넣지 않는다.

include 해석 규칙: `#include <경로>` 줄(대소문자 무시, 앞 공백 허용), 경로는 그 줄이 있는 파일의 폴더 기준, `/`·`\` 모두 허용. 조립 폴더 밖(realpath 기준)·링크 → FAIL `ASM_INCLUDE_OUTSIDE`, 대상 없음 → `ASM_INCLUDE_MISSING`, 순환 → `GEOM_INPUT_INVALID`. 트리에 없는 직계 `*.rad`·`*.inc`는 읽지 않고 경고 `ASM_FILE_UNUSED`(개수·최대 10개 이름).

### 4.2 `asm_parts.json`

```json
{"schema_version":1,"engine":"native","engine_version":"0.13.0","status":"OK","code":null,"message":null,
 "assem":{"digest":"sha256:…","starter":"MODEL_0000.rad",
          "tree":[{"rel":"MODEL_0000.rad","sha256":"…","includes":["101_parts.inc","102_parts_node_element.inc"]},
                  {"rel":"101_parts.inc","sha256":"…","includes":[]},{"rel":"102_parts_node_element.inc","sha256":"…","includes":[]}],
          "cache":{"hits":2,"misses":1}},
 "bodies":[{"body":"CUSH_L","volume":812345.2,"bbox":[0,0,0,120,80,60]}],
 "parts":[{"pid":3000001,"title":"CUSH_L","def_file":"101_parts.inc","elem_files":["102_parts_node_element.inc"],
           "node_files":["102_parts_node_element.inc"],"elems":{"TETRA4":41230},"nodes":9120,
           "volume":811902.7,"bbox":[0,0,0,120,80,60],"solid_ok":true}],
 "recommend":[{"body":"CUSH_L","pids":[3000001],"score":0.97,"basis":{"bbox_iou":0.99,"volume_ratio":0.999,"name":1.0,"renum":false}}],
 "warnings":[]}
```

- `parts`: 요소를 가진 모든 PART. `def_file` = `/PART` 카드 파일(없으면 `null`, 제목 `""`, 화면 `PART:<id>`), `elem_files`·`node_files` = 그 PART 요소·노드가 정의된 파일들(여러 개 가능). `solid_ok` = 요소가 TETRA4만. `volume` = TETRA4 부피 합(mm³), 그 밖 PART는 `null`. 개수 상한 `asm_match.max_parts`(넘으면 `ASM_TOO_MANY_PARTS`).
- `bodies`: `--features`면 그 파일의 `bodies`(OCP 불필요), `--cad`면 STEP을 읽어 같은 모양.
- `recommend`(바디마다 최대 1행, 1:1 초안): 하드 게이트(bbox 중심 거리 ≤ 0.1·바디 bbox 대각선, 부피비 ≥ 0.8) 통과 쌍에 `S = 0.6·bbox_iou + 0.3·volume_ratio + 0.1·name`(name: 정규화 일치 1, 포함 0.5, 그 밖 0 — GE §4.1 정규화), 헝가리안 최대 합, `S < asm_match.recommend_min_score`(기본 0.6)면 추천 없음. 조립 폴더에 `{predict.renum_csv_name}`이 있으면 RENUM 구간 ∩ pid 대응을 `score 1.0, basis.renum: true`로 우선(호환 편의, 확정은 여전히 사용자).
- 실패: starter 0·2개 이상 `GEOM_INPUT_INVALID`(IK-C1 판별 규칙), include 오류(§4.1), TETRA4 PART 0개 `ASM_NO_SOLID_PART`.

### 4.3 `asm_check.json`

```json
{"schema_version":1,"engine":"native","engine_version":"0.13.0","status":"PASS","code":null,"message":null,
 "rows_sha256":"…","assem":{"digest":"sha256:…","node_files":[{"rel":"102_parts_node_element.inc","nodes":18240}],"elem_files":["102_parts_node_element.inc"]},
 "tolerance":{"abs_mm":0.05,"rel":1.0e-4,"min_match_ratio":0.98},
 "rows":[{"body":"CUSH_L","pids":[3000001],"status":"PASS","code":null,
          "skin_nodes":4210,"match_ratio":0.9995,"tol_mm":0.05,
          "dist_mm":{"mean":0.003,"p95":0.011,"p99":0.019,"max":0.041},
          "bbox_delta_mm":[0.0,0.0,0.0,0.01,0.0,0.0],
          "faces":{"total":42,"uncovered":[]},
          "shared":{"nodes":0,"parts":[]},
          "worst":{"count":2,"file":"worst_CUSH_L.npz"},
          "suggest":null}],
 "file_checks":{"shared_nodes":0,"duplicate_node_defs":0,"duplicate_parts":[]},
 "glb":{"file":"match_fe.glb","sha256":"…"},"warnings":[],"elapsed_s":4.2}
```

판정 규칙:

1. 행 요소 집합 = include 트리 전체에서 pid들의 `/TETRA4/<pid>` 블록 합집합(블록이 여러 파일에 나뉘어도 합침). 다른 키워드 요소가 있으면 행 FAIL `GEOM_UNSUPPORTED_ELEMENT`.
2. 외곽 노드 = 합집합 외피 노드(GE `skin_triangles`). 노드 좌표는 노드 위치표의 정의 줄에서 읽는다(파일 무관). 거리 = 노드 → 바디 B-rep 최근접(GE §6.1 tag의 꼭짓점·엣지·면 분류와 **같은 코드**). `tol`·`match_ratio` 정의 = GE §6.1 4번.
3. 행 PASS ⇔ `match_ratio ≥ min_match_ratio` 이고 `shared.nodes == 0`. 거리 FAIL = `ASM_BOUNDARY_MISMATCH`(문구 "외곽 노드가 CAD 경계면과 맞지 않습니다 — 일치율 x%, 최대 y mm").
4. 공유 노드(AM-8): 행 노드를 매칭 안 된 PART의 요소(1D·쉘·솔리드 블록 모두)가 참조하면 행 FAIL `ASM_SHARED_NODES`, `shared = {nodes: 개수, parts: [{pid, title, nodes}]}`(노드 수 내림차순 최대 20개). `/INTER`·`/RBE*`·`/GRNOD` 등 정의 참조는 공유로 세지 않는다(GE §6.5 tie 검사 대상).
5. 면 덮임: B-rep 면 중 tol 안 노드가 0개인 면 → `faces.uncovered`(면 번호 `F<k>`·그 면을 쓰는 피처 이름), 경고 `ASM_FACE_UNCOVERED`(판정 불변).
6. 좌표계·단위 진단(거리 FAIL 행, **차단**, AM-5): `s` = 외피 bbox 대각선 / 바디 bbox 대각선. `|s/k − 1| ≤ 0.01`인 `k ∈ {1000, 0.001, 25.4, 1/25.4, 10, 0.1}` → `suggest:{code:"ASM_UNIT_SUSPECT", factor:k}`. `|s − 1| ≤ 0.01`이면 bbox 중심 차 `t`만큼 옮겨 다시 재고 `match_ratio_after ≥ min_match_ratio`면 `suggest:{code:"ASM_OFFSET_SUSPECT", translate_mm:[dx,dy,dz], match_ratio_after}`. 회전은 감지하지 않는다. 행 판정은 FAIL 그대로이며 보정 적용 경로는 없다 — 문구 "CAD를 조립과 같은 원점·mm로 다시 내보내세요".
7. 같은 노드 ID가 트리 안에서 두 번 이상 정의되면 전체 FAIL `GEOM_INPUT_INVALID`(`duplicate_node_defs`, 최대 10개 ID·파일). 쿠션 노드·요소가 여러 파일에 나뉘거나 다른 PART와 같은 파일에 있는 것은 FAIL이 아니다(AM-7).
8. 경고 `ASM_DUPLICATE_PART`: 서로 다른 행의 외피가 같은 위치(bbox 일치 + 외피 노드 90% 이상 서로 tol 안).
9. 전체 PASS ⇔ 모든 매칭 행 PASS + 7 통과. 매칭 안 함 행은 판정 제외.
10. `match_fe.glb`: GV §4.1 FE GLB 구조 재사용(노드 = 행 바디 이름, 외피 삼각형, 속성 `POSITION`·`NORMAL`·`_DIST_MM`·`_ELEM_ID`). `worst_<body>.npz`: 거리 상위 `asm_match.worst_nodes`(기본 2000)개 `node_id·xyz·dist`.

### 4.4 확정본 `asm_match.json`

```json
{"schema_version":1,"engine":"native","engine_version":"0.13.0","match_id":"…",
 "cad":{"rel":"model.step","sha256":"…"},"features_sha256":"…|null","unit_system":"mm-ton-s",
 "assem":{"digest":"sha256:…","starter":"MODEL_0000.rad","node_files":["102_parts_node_element.inc"]},
 "rows":[{"body":"CUSH_L","pids":[3000001],"titles":["CUSH_L"]},{"body":"CUSH_R","pids":[3000002,3000003],"titles":["CUSH_R_A","CUSH_R_B"]}],
 "excluded_bodies":[],
 "check":{"seq":3,"sha256":"<asm_check.json sha256>","rows_sha256":"…","match_ratio_min":0.9991,"dist_max_mm":0.041},
 "confirmed_by":"user","confirmed_at":"2026-10-22T…Z"}
```

- 행 순서 = `bodies` 순서(= 파라미터 이름 순서, GE §4.3 "component 순" 대체). component 이름 = **바디 이름**(①-1 추출이 RENUM 없이 바디 이름을 쓰므로 파라미터 이름 불변).
- `assem.node_files`는 정보용. 실제 쓰기 위치는 매번 노드 위치표로 다시 정한다(파일 이름에 기대지 않음).

---

## 5. 내부 대체 알고리즘(RENUM·기준본 역할)

### 5.1 수집(스트리밍·캐시, AM-7·AM-11)

- 파서는 include 트리 파일을 한 줄씩 읽는다(파일 전체를 메모리에 올리지 않음). 1차 색인: 키워드 블록(`/NODE`·요소 `/<KW>/<pid>`·`/PART`·`/PROP`·`/MAT`) 위치, 요소 ID·연결, 노드 ID → (파일, 줄 번호, 바이트 오프셋). 좌표는 필요한 노드(매칭 pid 노드 + 간섭 검사용 bbox 주변)만 읽는다.
- 캐시: 파일마다 `<cache_dir>/<sha256>.idx.npz`(색인, paicad만 읽음, 형식은 Impl-Geom, `schema_version`·`engine_version` 포함 — 다르면 무시하고 재생성). 키 = 파일 내용 sha256이라 이름·위치가 바뀌어도 재사용, 내용이 바뀌면 자동 무효. 플랫폼은 `<study>/_cache/asm_parse/`를 `--cache-dir`로 넘기고 기존 `_cache` 정리 규칙을 따른다(지워도 재생성).
- 고정폭·자유 형식 줄 모두 읽는다(GE `_node`·`_ints` 규칙).

### 5.2 component·기준 메시(RENUM·기준본 대체)

`components_from_match(index, match)` → 행마다 `Component(part=body, row=k, elem_range=(min,max), tet_ids, tets, node_ids)` — 기존 `Component` 형식 그대로(`elem_range`는 정보용). 요소 집합 = pid TETRA4 블록 합집합, 노드 = 그 요소가 참조하는 노드. 기준 메시 = 모든 행의 합. `RENUM_NODE_RANGE` 경고 없음. 두 행이 노드를 공유하면 GE §4.1처럼 한 연결 성분으로 푼다. tag·morph·check 내부 코드는 `Component` 목록과 기준 좌표만 받으므로 알고리즘 무변경.

check (b) 편차·(c) 품질은 매칭 행 요소만, (d) 간섭은 include 트리 전체에서 매칭 pid 요소를 뺀 나머지(같은 파일 안 다른 PART 포함), (e) tie는 트리 전체의 `/INTER/TYPE2`·집합 정의로 기존과 같다.

### 5.3 노드 ID·다른 component 불변(AM-6·AM-8)

- 바뀌는 바이트 = 조립 사본에서 매칭 pid 노드가 정의된 `/NODE` 줄의 좌표 필드뿐(파일이 몇 개든). 노드 ID·요소·연결·다른 PART 노드·`/PART`·`/INTER` 등은 바이트 동일.
- 공유 노드는 검사 단계에서 차단되므로 다른 PART 노드가 움직이는 경우는 없다.

### 5.4 쓰기·조립(파일 통째 교체 폐지)

- check PASS 출력 = `node_patch.npz`(매칭 노드 전부의 새 좌표). 작업 경로: ④ `P/geom/node_patch.npz`, 일괄·DOE `R/m_2/node_patch.npz`·`R/_paicad/node_patch.npz`. 매칭 세트는 `{mesh_include_name}` 파일을 만들지 않는다.
- 새 명령 `paicad asm write --assem-dir <원본 또는 세트 사본> --asm-match --patch --out-dir <조립 사본> [--cache-dir]`: include 트리 파일을 상대 경로 그대로 `--out-dir`에 쓰되, 패치 노드의 정의 줄만 GE §6.4 형식(필드 폭·정렬·유효 7자리 이상, 줄 끝 문자 유지)으로 좌표를 바꾼다. 나머지 줄·패치 노드가 없는 파일은 바이트 동일 복사. `asm_write.json`에 `{files:[{rel, changed_lines}], nodes_written}`. 패치 노드 중 정의 줄이 없는 것이 있으면 `ASM_MATCH_INVALID`.
- 플랫폼 `assemble_into`(④ m_3, ①-3 FLAT run 직계)는 매칭 세트일 때 `paicad asm write`를 부르고, 트리 밖 직계 파일은 복사하지 않는다(트리가 해석 입력의 전부). starter는 트리 뿌리 이름 그대로.
- 형상 값이 없으면(공칭 실행) 패치 없이 트리 사본만 만든다(바이트 동일).

### 5.5 쿠션 단독 rad(IK)

`paicad cushion write --asm-match --assem-dir --out-dir --out-rad [--patch]`: include 트리 수집 결과에서 매칭 pid의 `/PART`·참조 `/PROP`·`/MAT`(어느 파일에 있든 첫 정의), 쿠션 노드 줄(패치가 있으면 좌표 필드만 바꿈, ID 유지), `/TETRA4/<pid>` 블록을 IK §5.2 순서로 한 파일에 쓴다. starter `/BEGIN`·출력 규칙은 IK §5.2·IK-C1 그대로.

### 5.6 tag 보고

`tag.json` 추가 키(가산): `asm_match:{sha256}|null`, `parts[].pids`(매칭 세트), `baseline_inc: null`, `parts[].renum_row: null`. 매칭 세트의 tag가 `GEOM_BASELINE_MISMATCH`를 내면 문구 끝에 "조립 매칭 검사를 다시 하세요".

---

## 6. CLI·API·설정

### 6.1 paicad(Impl-Geom, 0.13.0 MINOR)

| 명령 | 인자(굵게 = 필수) | 성공 판정 파일 |
|---|---|---|
| `paicad asm parts` | **`--assem-dir`**, **`--out-dir`**, `--features`(①, OCP 없이) 또는 `--cad`(④, 둘 중 하나 필수), `--renum-csv`(있으면 추천 보조), `--cache-dir`, `--options` | `asm_parts.json`(`status: OK`) |
| `paicad asm check` | **`--cad`**, **`--assem-dir`**, **`--match`**(`{rows, excluded_bodies}` JSON), **`--out-dir`**, `--features`, `--cache-dir`, `--options`(tag 절), `--no-glb` | `asm_check.json`(존재 = 성공, 내용 `status` PASS/FAIL) |
| `paicad asm write` | **`--assem-dir`**, **`--asm-match`**, **`--out-dir`**, `--patch`(없으면 바이트 동일 사본), `--cache-dir` | `asm_write.json`(`status: OK`) |
| `tag`·`morph`·`check`·`run`·`selftest`·`cushion write`·`view preview --fe` | 메시 출처 = 방식 L(기존: `--baseline-inc` + `--renum-csv`, `cushion write`는 `--inc` + `--renum-csv`) **또는** 방식 M(`--asm-match` + `--assem-dir`, `--cache-dir` 선택). 정확히 한 방식(섞이면 `GEOM_INPUT_INVALID`). 방식 M의 `check`·`run`은 `--out-inc` 대신 **`--out-patch`**, `cushion write`는 `--inc` 대신 선택 `--patch` | 방식 L은 기존과 같음. 방식 M은 `--out-patch` 파일(PASS일 때만) |
| `extract` | `--renum-csv` \| `--asm-match` 선택(있으면 순서·대응 검사) | 기존과 같음 |

- 방식 M에서 morph는 `morph/node_xyz.npz`(기준 메시 노드 전부의 새 좌표)와 `morph.json`을 낸다(`morphed.inc` 없음). check는 이 파일과 기준 좌표를 비교한다.
- 종료코드: GE §5.4 + `asm check` FAIL용 새 코드 `EXIT_ASM`(값은 Impl-Geom이 GE §5.4 표에 추가). 실패 코드: `ASM_BOUNDARY_MISMATCH`·`ASM_SHARED_NODES`·`ASM_INCLUDE_OUTSIDE`·`ASM_INCLUDE_MISSING`·`ASM_NO_SOLID_PART`·`ASM_TOO_MANY_PARTS`·`ASM_MATCH_INVALID`(확정본 형식·pid 없음·digest 불일치·패치 노드 정의 없음), 경고 `ASM_FACE_UNCOVERED`·`ASM_DUPLICATE_PART`·`ASM_FILE_UNUSED`·`BODY_MAP_IGNORED`, 진단 `ASM_UNIT_SUSPECT`·`ASM_OFFSET_SUSPECT`. (`ASM_SPLIT_FILES`·`ASM_FILE_NOT_INCLUDED`는 폐지 — AM-C1.)
- 방식 M에서 paicad는 `--assem-dir`의 include 트리 digest를 다시 계산해 확정본과 다르면 `ASM_MATCH_INVALID`.
- 파서: `shell/assem.py: read_assembly`와 같은 규칙을 include 트리·스트리밍·캐시로 공용화(쉘 경로 출력은 불변이어야 함 — 기존 SM 시험 유지). numpy만(OCP 없음).

### 6.2 설정(Impl-Backend, `config/platform.example.yaml` 추가만)

```yaml
asm_match:
  enabled: true
  max_parts: 5000
  recommend_min_score: 0.6
  worst_nodes: 2000
  timeout_s: 600            # asm parts(목록 읽기) 1회 상한(초)
  check_timeout_s: null     # asm check(경계 검사) 1회 상한(초), null = 상한 없음(AM-C3)
commands:
  paicad_asm_parts: ["{paicad}", "asm", "parts", "--assem-dir", "{assem_dir}", "--features", "{features_json}", "--renum-csv", "{renum_csv}", "--cache-dir", "{asm_cache_dir}", "--options", "{options_json}", "--out-dir", "{out_dir}"]
  paicad_asm_check: ["{paicad}", "asm", "check", "--cad", "{cad_input}", "--features", "{features_json}", "--assem-dir", "{assem_dir}", "--match", "{match_rows_json}", "--cache-dir", "{asm_cache_dir}", "--options", "{options_json}", "--out-dir", "{out_dir}"]
  paicad_asm_write: ["{paicad}", "asm", "write", "--assem-dir", "{assem_dir}", "--asm-match", "{asm_match}", "--patch", "{node_patch}", "--cache-dir", "{asm_cache_dir}", "--out-dir", "{out_dir}"]
```

- `TEMPLATE_SPECS`: 세 키 `required=False`, argv[0] = `{paicad}`(V-GE-1). 새 placeholder `match_rows_json`·`asm_match`·`asm_cache_dir`·`node_patch`·`out_patch`. ④ 경로(`--cad`)는 `"--features","{features_json}"` 쌍을 `"--cad","{cad_input}"`으로, 공칭 실행은 `"--patch","{node_patch}"` 쌍을 생략. `{renum_csv}` 없으면 쌍 생략(GE §7.3.1).
- **쌍 치환(AM-10)** — 매칭 세트·DOE의 기존 `paicad_*` 템플릿: `"--renum-csv","{renum_csv}"` → `"--asm-match","{asm_match}"`, `"--baseline-inc","{baseline_inc}"` → `"--assem-dir","{assem_dir}"`(이미 `--assem-dir`이 있으면 쌍 삭제), `"--out-inc","{out_inc}"` → `"--out-patch","{out_patch}"`, `cushion write`의 `"--inc","{cushion_inc}"` → `"--patch","{node_patch}"`(공칭이면 삭제), 끝에 `"--cache-dir","{asm_cache_dir}"` 추가. 관리자 설정 변경 불필요.
- 허용오차는 `geometry.defaults.tag`(AM-3). 키 null·`enabled: false` → API 409 `TEMPLATE_NOT_CONFIGURED`("관리자 설정 필요: commands.paicad_asm_parts").

### 6.3 API(Backend, `backend/openapi.json` 갱신 → 프런트)

| 메서드·경로 | 본문 | 응답 |
|---|---|---|
| `POST /studies/{sid}/asm-matches` | `{radioss_assem_path, cad:{kind:"train"}\|{kind:"path", path}}` | 202 `{match_id, job_id}`(작업 `ASM_MATCH` mode parts). 422 경로 규칙, 409 `PREREQUISITE_MISSING`(train인데 ①-1 Native 추출 없음) |
| `GET /asm-matches/{id}` | – | `AsmMatch = {match_id, study_id, state, source, assem:{display_path, digest, starter, files}, bodies[], parts[], recommend[], rows[], excluded_bodies[], check:{seq, status, rows_sha256, rows:[요약·shared·suggest], file_checks, glb_url}\|null, confirmed:{sha256, confirmed_at}\|null, stale_reason\|null}` |
| `PUT /asm-matches/{id}/rows` | `{rows:[{body, pids:[int]}], excluded_bodies:[str]}` | 200 `AsmMatch`(state DRAFT, check 무효). 422 `ASM_ROW_INVALID`(+`body`, 사유: 모르는 바디·pid, pid 중복, `solid_ok=false`, 바디 누락, use 파라미터가 있는 바디 제외), 409 `ASM_MATCH_CONFIRMED` |
| `POST /asm-matches/{id}/check` | – | 202 `{job_id}`(mode check). 409 `ASM_ROWS_INCOMPLETE` |
| `POST /asm-matches/{id}/confirm` | – | 200 `AsmMatch`(CONFIRMED, 검사 불필요 — AM-C3). 409 `ASM_ROWS_INCOMPLETE`·`ASM_MATCH_STALE`(조립 트리·STEP·피처 sha 변경)·`ASM_MATCH_BUSY`, 422 `ASM_ROW_INVALID`. ~~409 `ASM_CHECK_REQUIRED`~~ 폐지. 검사를 실행했는데 FAIL·낡음이면 응답 `warnings`에 `ASM_CHECK_FAILED_WARN`·`ASM_CHECK_STALE_WARN` |
| `POST /asm-matches/{id}/cancel` | – | 202 `AsmMatch`. 진행 중(대기·실행) ASM_MATCH 작업 취소(power). 없으면 409 `JOB_TERMINAL`. AM-C3 가산 |

- 쓰기: Study 프로젝트 power 이상 + CSRF(쿠키) 또는 `pai_` Bearer(x-mcp 도구). `x-mcp`: 5개 모두 도구(`asm_match_create`·`asm_match_get`·`asm_match_set_rows`·`asm_match_check`·`asm_match_confirm`), 검사 GLB 미디어는 기존 artifacts media 경로(새 kind `ASM_MATCH_GLB`, `x-mcp.exclude` 이진). 용어집 `ko`: "조립 매칭", `ASM_*` 코드.
- 작업: 새 job_type **`ASM_MATCH`**(`JOB_KINDS` 등록, `SUMMARIES`에 `asm_match` 엔티티), 레인 `PREVIEW`(전역 슬롯 미사용 — v0.2.9 대기열 분리 계약이 레인을 바꾸면 그 계약을 따름), step `AM_PARTS` 또는 `AM_CHECK`(params.mode), 타임아웃 = AM_PARTS `asm_match.timeout_s`(600), AM_CHECK `asm_match.check_timeout_s`(기본 null = 없음, AM-C3). 결과 요약(DB `jobs.result`)은 상태·개수·`match_ratio_min`·`dist_max_mm`·`shared_nodes`만.
- **이 계약의 DB 변경 없음**(AM-12): 매칭 상태는 `match.json`, 소비자는 `jobs.params`에 `asm_match_id`·`asm_match_sha256`, 세트·DOE 폴더 `prep.json`에 기록.

### 6.4 소비자 변경(Backend·Worker)

| 위치 | 변경 |
|---|---|
| `native_doe_gen`(①-3) | params `asm_match_id` 선택. 있으면 CONFIRMED·`source.kind=train`·STEP/피처 sha 현재와 같음·`radioss_assem_path`의 트리 digest = 확정본 digest(아니면 409 `ASM_MATCH_STALE`), 기준본·RENUM 검사 생략. 없으면 기존 검사(두 파일 모두 있으면 통과), 하나라도 없으면 409 `PREREQUISITE_MISSING` missing `["ASM_MATCH"]` 문구 "조립 매칭을 저장하세요" |
| `doe_native.dg_prep` | 매칭 DOE는 **include 트리**를 상대 경로 그대로 A로 복사(직계 `*.rad`·`*.inc` 규칙 대신), A의 digest = 확정본 digest 확인(`INPUT_CHANGED`), `D/cad/asm_match.json` 복사, `body_map.json` 복사 생략 |
| `PARAM_SET_NATIVE`(④) | params `asm_match_id`(source path, cad sha = 세트 STEP). `S/radioss_assem/`에 트리 복사, `S/cad/asm_match.json` 복사, NP_TAG가 방식 M. `param_discover_native`: `asm_match_id`가 있으면 `BASELINE_INC_MISSING`·`RENUM_CSV_MISSING` problems 제외 |
| from-train(①→④) | `D/cad/asm_match.json` → `S/cad/asm_match.json`, 트리 사본 복사 |
| `prep.json`(GE §4.2) | `inputs.asm_match:{rel:"cad/asm_match.json", sha256}\|null`(키 없음 = null), `inputs.assem_digest`(트리), 매칭 세트는 `baseline_inc: null`·`renum_csv: null`. 유효성에 `asm_match` sha·`assem_digest` 포함(다르면 `GEOM_PREP_STALE`) |
| `native_inputs`·`run_paicad` | 쌍 치환(§6.2), `{asm_cache_dir}` = `<study>/_cache/asm_parse/` |
| `assembly_sources`·`assemble_into` | 매칭 세트는 `paicad_asm_write`(§5.4). 결과 판정 = `asm_write.json` OK + starter 존재 |
| **`mesh_include_name` 의존 전수 점검(구현 항목)** | 매칭 세트에서 파일 이름 의존을 모두 없앤다. 최소 목록(def0517 grep): `predict_native.py`(MESH 출력·`new_inc`), `geometry_sample.py`(m_2 출력·쿠션 include 선택), `run_chain.py`, `geometry_native.py`(`baseline_inc`·`renum_csv` 값), `np_register.py`·`param_set_native_train.py`·`param_set_baselines_api.py`·`param_set_native_api.py`·`stage4_predict.py`·`path_inspect.py`(prep·검증 인자), `doe_native.py`·`stage1_native.py`(검사), `predict_inputs.py`(`assembly_sources`·`assemble_into`·`cushion_into`), `fem_verify.py`·`fem_assembly.py`(native 조립 사본에서 이름으로 찾음), `equiv/sides.py`(`mesh_inc` 탐색), 프런트 `ParamSetDiscoverForm.tsx`·`lib/geometry.ts` 문구. 대체 규칙: 산출 확인은 `node_patch.npz`·`asm_write.json`, 메시 위치가 필요한 곳은 `asm_match.json` + 트리. Backend가 점검 표를 PR 본문에 남긴다 |

### 6.5 프런트(Impl-Frontend)

새 컴포넌트 `AsmMatchCard`(①·④ 공용): 조립 폴더 입력(기존 경로 입력 + 업로드 purpose `RADIOSS_ASSEM` 재사용 — 하위 폴더 포함 업로드), 매칭 표(§3.2), 3D 창(GV 뷰어 FE 모드, 색 맵 속성 `_DIST_MM` 선택 지원), 상태 폴링(기존 작업 폴링). `DoeGenCard`(native, 세트 기준 아님)는 확정된 `asm_match_id`를 params에 넣고, 없으면 생성 불가 사유 표시. `NATIVE_ASSEM_TEXT`("기준 메시 104_… 필요")는 매칭 경로에서 "조립 매칭 필요"로 바뀐다. 문구 한국어.

---

## 7. 호환

1. **기존 RENUM 세트·DOE**: `prep.json`에 `asm_match` 없음 → 방식 L(기존 인자·기존 기준본 이름·include 통째 교체) 그대로. paicad 0.13.0이 기존 argv를 그대로 받으므로 준비본 재생성 불필요(엔진 MINOR 차이 경고만, GE §17).
2. **RENUM 파일이 있는 새 조립 폴더**: 매칭 카드가 RENUM 대응을 추천으로 채운다(§4.2). 매칭 없이 DOE를 만들면(API·MCP) 기존 검사로 통과 — 화면은 항상 매칭 카드를 쓴다.
3. **다중 baseline(4B)**: 1차는 RENUM 방식만. `asm_match_id`와 `BL_MAP`을 함께 쓰면 409 `ASM_MATCH_UNSUPPORTED`("다중 baseline은 아직 조립 매칭을 지원하지 않습니다").
4. **쉘 세트**: 무관(`asm_match_id`를 주면 422). 공용화한 파서로 쉘 출력이 바뀌면 안 된다(SM 시험).
5. **Altair**: 무변경(GE-11).
6. 데이터셋·모델: 매칭 세트와 RENUM 세트는 같은 엔진(native)이라 섞을 수 있다(같은 메시면 해석 입력 바이트 동일 — V-AM-6).

---

## 8. 시험(V-AM-n)

| # | 내용 | 소유 |
|---|---|---|
| V-AM-1 | 합성 조립(사용자 구성 재현: starter → `101_parts.inc`(`/PART`·`/INTER/TYPE2`·세트) + `102_parts_node_element.inc`(쿠션 2개 + 제품 노드·요소 섞임), 하위 폴더 include 1개): `asm parts --features`가 트리·PART·`def_file`·`elem_files`·`node_files`·TETRA4 수·부피를 맞게 내고 OCP를 import하지 않음. 트리 밖 파일 → `ASM_FILE_UNUSED` | Geom |
| V-AM-2 | 추천: 이름이 달라도 bbox·부피로 정답, 좌우 대칭 쌍 뒤바뀌지 않음, RENUM 있으면 `basis.renum` | Geom |
| V-AM-3 | 공칭 일치 → PASS(`dist_mm.max ≤ tol`), 좌우 바꿔 매칭 → FAIL `ASM_BOUNDARY_MISMATCH` | Geom |
| V-AM-4 | 쿠션 +10 mm 이동 → FAIL + `ASM_OFFSET_SUSPECT [10,0,0]`, m 단위(×0.001) → `ASM_UNIT_SUSPECT 0.001`. 두 경우 검사 결과는 FAIL이며, confirm은 허용되고 `ASM_CHECK_FAILED_WARN`(AM-C3, 원안의 confirm 409 폐지) | Geom·Backend |
| V-AM-5 | 쿠션 노드·요소가 두 파일에 나뉨 → PASS(FAIL 아님). 제품 요소와 노드 공유 → FAIL `ASM_SHARED_NODES` + `shared.nodes`·상대 PART 목록. 노드 중복 정의·include 밖·없음·순환 각 코드. 비TETRA4 PART, 1:N 등각 합집합 PASS·비등각 FAIL | Geom |
| V-AM-6 | 동등성: 단일 파일·pid = RENUM 구간인 합성 케이스에서 방식 M(`asm write` 결과 파일)과 방식 L(morphed include 교체 결과)의 해석 입력이 바이트 동일, tag_nodes·check 수치 동일, cushion rad 바이트 동일 | Geom |
| V-AM-7 | 다중 파일 쓰기: 쿠션 노드가 두 파일에 나뉘고 제품 노드와 같은 파일에 섞인 경우 `asm write` 후 바뀐 바이트 = 패치 노드 줄의 좌표 필드뿐(열 폭·줄 끝 유지), 다른 줄·다른 파일 바이트 동일, 노드 ID 불변, 공칭(패치 없음) 사본은 전체 바이트 동일 | Geom |
| V-AM-8 | 캐시: 두 번째 `asm parts`·`check`는 캐시 적중(`cache.hits`), 파일 1개 내용 변경 시 그 파일만 미스, 다른 이름으로 같은 내용 복사 시 적중, 캐시 삭제 후 같은 결과 | Geom |
| V-AM-9 | API: rows 검증 422 각 사유, check 없이 confirm 200(AM-C3)·FAIL 검사 뒤 confirm 200 + `ASM_CHECK_FAILED_WARN`·낡은 검사 + `ASM_CHECK_STALE_WARN`·행 미완성 409 `ASM_ROWS_INCOMPLETE`, 트리 파일 수정 후 confirm·DOE 409 `ASM_MATCH_STALE`, DOE(asm_match_id, RENUM·기준본 없음) 202, 둘 다 없으면 409 missing `ASM_MATCH`, 4B 409 | Backend |
| V-AM-10 | 워커 가짜 도구(`fake_paicad asm parts/check/write`, 방식 M 인자): ASM_MATCH 작업·쌍 치환 argv·트리 복사·`node_patch.npz` 판정·`prep.json inputs.asm_match`·`GEOM_PREP_STALE`. 매칭 세트 경로에서 `mesh_include_name` 파일을 찾지 않음(정적 점검 + 시험) | Backend |
| V-AM-11 | 기존 RENUM 세트 PREDICT·BATCH·DOE·FEM 검증 회귀(argv·산출 불변) | Backend |
| V-AM-12 | MCP 정적 시험: 새 API x-mcp, `ASM_MATCH` JOB_KINDS·SUMMARIES, 용어집 ko | Backend |
| V-AM-13 | 프런트: 표 렌더·드롭다운 회색 사유·"매칭 안 함" 제한·검사 후 판정·공유 노드·원점 안내 문구·저장 단추 상태·DOE 사유 문구, 2560×1440 라이트 스냅숏 | Frontend |

---

## 9. 리스크

| 리스크 | 대응 |
|---|---|
| 대형 조립(수백 MB) 파싱 시간·메모리 | 스트리밍 1차 색인 + 필요한 노드만 좌표 보관 + 파일 sha256 캐시(AM-11, V-AM-8), `timeout_s`, 진행 줄 |
| `mesh_include_name` 이름 가정 코드 누락(FEM 검증·등가성 판정·쿠션 입력) | §6.4 전수 점검 표(구현 항목) + V-AM-10 정적 점검 |
| 다중 파일 `/NODE` 줄 갱신의 형식 손상 | GE §6.4 쓰기 규칙 재사용, 줄 단위 바이트 비교 시험(V-AM-7) |
| 회전된 좌표계 | 감지 못 함 → `ASM_BOUNDARY_MISMATCH`로만 드러남 |
| 원점·단위 불일치(SimLab 밖에서 만든 조립에서 흔함) | 감지·안내 후 차단(AM-5) — CAD 재내보내기 필요, 사용자 확정 |
| 추천 오매칭 | 확정은 사용자, 저장 전 검사 필수, 좌우 뒤바뀜은 거리로 FAIL |
| 0.05 mm가 다른 메셔의 노드 좌표 정밀도보다 엄격 | 고정폭 7자리 기준 1 m 좌표 정밀도 ≈ 1e-4 mm로 충분. 실패 시 `geometry.defaults.tag` 조정(세트 옵션) |
| include 트리가 조립 폴더 밖(공용 재질 라이브러리 등)을 가리킴 | `ASM_INCLUDE_OUTSIDE`로 차단 — 필요한 파일을 조립 폴더 안에 두도록 안내 |
| 쉘 경로 파서 공용화로 쉘 결과 변화 | SM 기존 시험 유지, 출력 바이트 비교 |

## 10. 사용자 확정(2026-10-22)

| # | 질문 | 확정 |
|---|---|---|
| Q1 | 쿠션 노드·요소가 한 파일에 있나? | 아니다(`101_parts.inc` = `/PART`·요소 형식·`/INTER`·세트, `102_parts_node_element.inc` = 노드·요소). **파일 이름에 기대지 않고 include 트리 전체를 읽는다**, 분할 FAIL 폐지, 다중 파일 `/NODE` 줄 갱신, 공유 노드 FAIL 유지(수·상대 PART 보고), 스트리밍·캐시(AM-1·AM-6~8·AM-11) |
| Q2 | 원점·단위 차이 보정 허용? | 안내만 하고 진행을 막는다(AM-5) |
| Q3 | 릴리스 | **v0.2.9**에 대기열 분리(`0022_job_queues`)·DOE 방식·조립 매칭을 함께 넣는다(roadmap) |

## 변경 메모

(구현 중 계약과 달라지면 `AM-C2~`로 기록하고 Plan 확인.)

- **AM-C1**(2026-10-22, 사용자 답변 Q1~Q3): 기준본 = 매칭 PART id 노드·요소 집합(파일 이름 의존 전부 제거), include 트리 전체 수집(쿠션이 여러 파일·다른 PART와 같은 파일이어도 허용), `ASM_SPLIT_FILES`·`ASM_FILE_NOT_INCLUDED` 폐지 → `ASM_INCLUDE_OUTSIDE`·`ASM_INCLUDE_MISSING`·`ASM_FILE_UNUSED`, 출력 = 노드 패치 + 새 명령 `paicad asm write`(조립 사본의 해당 `/NODE` 줄 좌표만 갱신, include 통째 교체 폐지), 쿠션 rad도 트리 수집 결과로, 공유 노드 FAIL 유지 + 수·상대 PART 보고, 스트리밍·sha 캐시, 원점·단위는 안내 후 차단 확정, 릴리스 v0.2.9(대기열 분리·DOE 방식과 함께), `mesh_include_name` 의존 전수 점검을 구현 항목으로.
- **AM-C2**(2026-10-22, Impl-Backend 구현 중 확정 — 계약 §6.3·§6.4 보완, Plan 확인 요청): 계약과 달라지거나 계약이 비워 둔 부분을 구현대로 기록한다.
  1. **쓰기 주체(§4.1)**: `match.json`·`check/<seq>/match_rows.json`(= `--match` 입력)·`asm_match.json`은 **API만** 쓴다. 워커(ASM_MATCH)는 `parts/`·`check/<seq>/`의 paicad 산출물만 쓰고 `options_run.json`(paicad `--options`)을 쓴다 — 경쟁 없음. `last_check`는 `match.json`에 저장하지 않고 `check/<seq>/asm_check.json`에서 계산한다. 쓰기 직렬화 = Study 행 잠금(`for update`).
  2. **`rows_sha256`**: `match_rows.json`(= API가 쓴 정규 JSON `{"rows":[{body,pids}],"excluded_bodies":[…]}` UTF-8, 키 정렬·공백 없음 — 저장 때 서버가 정규화: 행·제외 = 바디 순서, `pids` 정렬·중복 제거) **바이트 전체**의 sha256 hex(접두사 없음). paicad `asm check`가 보고에 적는 값과 같다. 행을 순서만 바꿔 저장해도 같은 값이면 검사는 유효(`check.current=true`).
  3. **종료코드·카테고리**: `asm check` FAIL(rows 있는 `asm_check.json`) = **15 `EXIT_ASM`**, 카테고리 `ASM`(GE §5.4 표에 추가, 한국어 문구 `geometry/messages.py`). 행이 있는 FAIL은 **데이터**라 작업은 SUCCEEDED·결과 status FAIL(확정 불가 `ASM_CHECK_REQUIRED`). 보고 없음·행 없는 FAIL(조립 트리 오류 `ASM_INCLUDE_*`·STEP 읽기 실패)은 작업 FAILED(failure_code = paicad 코드). `asm_parts.json`이 FAIL이면 목록 없음 = 상태 `FAILED`.
  4. **같은 파일 두 번 include = `GEOM_INPUT_INVALID`**(순환과 같은 코드, 문구 "두 번 include"). 플랫폼 `geometry/asm_tree.py`와 paicad `mesh/asmtree.py`의 digest는 시험(`test_tree_digest_matches_paicad`)으로 동일성을 고정한다(starter 판별·`#include` 규칙·링크·밖·누락 코드 포함).
  5. **`asm_write.json` 위치**: `paicad asm write --out-dir <임시>`의 **out-dir 직계**(조립 사본 파일들과 같은 폴더). 플랫폼은 임시 폴더에 쓰게 하고 보고 `files[].rel`만 목적지(DOE run 직계·④ `P/INPUT`·일괄 `m_3`)로 옮긴다(트리 밖·보고 파일은 옮기지 않음). 성공 판정 = 보고 status OK + `assem.starter`가 `files[]`에 있음. `--out-dir`은 조립 폴더 안이면 안 된다(paicad 검사).
  6. **`--options`의 `asm_match` 절**: `{max_parts, recommend_min_score, worst_nodes}` ← `settings.asm_match`(기본 5000·0.6·2000, `timeout_s` 600은 플랫폼 전용 시간 상한). paicad `options.validate_asm`과 같은 키.
  7. **레인·v0.2.9 대기열 분리와의 관계**: ASM_MATCH = `lane PREVIEW`(전역 슬롯 미사용, `claim_preview`는 레인 기준이라 job_type 목록을 따로 두지 않음). 대기열 분리 계약이 레인 이름·동시 수를 바꾸면 `job_types.py`의 `lane` 한 필드만 바꾼다. PREVIEW 허용 명령 목록에 `paicad_asm_parts`·`paicad_asm_check` 추가(`paicad_asm_write`는 DOE·예측 슬롯 작업 안에서만). Study당 활성 ASM_MATCH 1개(`ux_jobs_study_type_active`, 409 `STUDY_JOB_BUSY`). 일반 작업 생성 API로는 만들 수 없고(`PARAM_MODELS`에 없음), 알림 없음(silent)·기본 숨김·재시도 불가. step = `AM_PREP`·`AM_PARTS`·`AM_CHECK`·`AM_REGISTER`(모드에 안 맞는 step은 SKIPPED).
  8. **검사 GLB**: 새 artifacts.kind(`ASM_MATCH_GLB`)는 DB CHECK 변경(migration)이 필요해 **기존 `GEOM_PREVIEW_FE_GLB`를 재사용**(이 계약 DB 변경 없음 유지). `rel_path`가 `asm_match/<id>/check/<seq>/`로 시작하는 것이 그 검사의 GLB이며 `/artifacts/{id}/media`로 서빙(`check.glb_artifact_id`·`check.glb_url`).
  9. **API 가산(응답 필드는 가산만, 기존 필드 불변)**: `AsmMatch`에 `last_job{id,mode,state,failure_code,failure_message,progress_pct,progress_label}`·`warnings`·`rows_complete`·`use_bodies`(① 출처에서 use=true 파라미터가 있는 바디 — "매칭 안 함" 불가 바디, 피처의 `body` 필드와 사용 파라미터로 서버가 계산)·`created_at`·`updated_at`, `check`에 `current`·`glb_artifact_id`·`glb_url`·`rows[].worst.points[{node_id, xyz[3], dist_mm}]`(거리 내림차순 상위 `asm_match.worst_nodes`점, paicad `worst_<body>.npz`에서 읽음). **목록 API 1개 추가**: `GET /studies/{id}/asm-matches?source=train|path&latest=true&limit=` → `{items:[AsmMatch…]}` 최신순(MCP 도구 `asm_match_list`) — 화면이 ①의 마지막 매칭을 다시 찾기 위해 필요(계약 5개 + 1).
  10. **오류 코드 가산**: `ASM_MATCH_BUSY`(진행 중 쓰기)·`ASM_ROW_INVALID`(422, `problems[].code` ∈ UNKNOWN_BODY·BODY_DUPLICATE·UNKNOWN_PID·PID_DUPLICATE·NOT_SOLID·BODY_MISSING·USE_PARAM·ROWS_EMPTY, `problems[].body`)·`ASM_ROWS_INCOMPLETE`(검사 시작 409)·`ASM_MATCH_UNSUPPORTED`(쉘 세트 422 · 다중 baseline 409 · parts 폴더 STEP 422 · 조립 매칭 세트의 FEM 검증 재조립 problems). 소비자 게이트 오류: 확정본 없음 = 409 `PREREQUISITE_MISSING`(missing `["ASM_MATCH"]`, 문구 "조립 매칭을 먼저 하세요 …"), 입력 변경·출처 불일치 = 409 `ASM_MATCH_STALE`. 새 요청에서 매칭이 없고 기준본·RENUM도 없을 때만 위 문구(기존 방식의 "기준 메시·번호 표" 문구는 기존 방식에서만).
  11. **STALE 판정**: 조립 include 트리 digest·STEP sha256·피처 파일 sha256 중 하나라도 매칭 때와 다르면 `STALE`(목록 작업 중이 아닐 때). 소비자는 확정본 digest와 **소비 시점의 조립 폴더 트리 digest**를 비교한다(`radioss_assem_path`가 다른 폴더여도 내용이 같으면 통과).
  12. **④ 등록 필드 위치**: `POST /studies/{id}/param-sets` 본문에 `asm_match_id`(native 솔리드 신규 등록만, `source.kind=path` 확정본·STEP sha = 매칭 STEP·STEP 파일 1개), `POST …/param-sets/discover` 본문에 `asm_match: true`(조립 폴더 후보에서 `BASELINE_INC_MISSING`·`RENUM_CSV_MISSING` 제외). 작업 params `asm_match_id`·`asm_match_sha256`(서버가 확정본에서 다시 읽어 기록). ①-3은 `TD_DOE_GEN` params `asm_match_id`(`source.kind=train`). from-train은 D가 매칭 DOE면 트리·`cad/asm_match.json`을 그대로 복사.
  13. **저장소**: `<study>/asm_match/<id>/{match.json, parts/, check/<seq>/, asm_match.json}`, 파싱 캐시 `<study>/_cache/asm_parse/`. **`_cache/asm_parse`는 자동 정리 대상이 아니다**(housekeeping은 알려진 캐시 테이블만 정리) — 지워도 재생성되므로 관리자가 수동 삭제 가능. SPDM 쓰기 없음(`asm_match`는 `PROTECTED_PREFIXES`에 포함). 매칭 묶음 → Study 조회는 `jobs.params.match_id`(DB 변경 없음).
  14. **방식 판별**: 세트·DOE 폴더의 `cad/asm_match.json` 유무(`geometry/asm_match.is_matched`). 있으면 `native_inputs`의 `baseline_inc`·`renum_csv`는 빈 값, `body_map` 없음(경고 `BODY_MAP_IGNORED`), `asm_match` 경로가 채워져 `commands_asm.expand`가 §6.2 쌍 치환·`{asm_cache_dir}`를 적용한다. 방식 L(없음)은 argv 불변(시험 `test_legacy_template_unchanged_without_asm_match`).
  15. **FEM 검증**: 조립 매칭 예측의 입력 재사용(reuse)은 `INPUT`의 include 트리(하위 폴더)를 상대 경로째 복사. 조립 다시 만들기(rebuild)는 1차 미지원 → 미리보기 problems `ASM_MATCH_UNSUPPORTED`(생성 422). equiv 비교는 매칭 run에서 `Run.mesh_tree`(조립 폴더)·`mesh_parts`(매칭 PART id)로 부피를 읽는다.
- **AM-C3**(2026-10-23, 사용자 결정 — v0.2.10): "step바디랑 조립 component랑 추천 적용하고 사용자가 저장하게 하자. 검사는 고급으로 옵션으로 하게하자. 추천 알고리즘으로도 충분한듯해. … 작업시간 600초 초과로 실패하는데 이거 제한 풀어. 600초씩이나 걸릴 거면 고급옵션으로 하자는 거야"(현장: GitHub 이슈 #9, AM_CHECK `paicad asm check`가 COMPOUND_2에서 `GEOM_TIMEOUT 600초`로 실패). AM-2·§3.2·§6.3·V-AM-4·V-AM-9의 "검사 PASS 필수"를 폐지한다.
  1. **확정(confirm)에 검사가 필요 없다**: `ASM_CHECK_REQUIRED` 409 폐지. 확정 조건 = 행 완전성(`rows_complete`, 저장된 행의 `ASM_ROW_INVALID` 재검증: use_bodies·N:1 금지·TETRA4) + `ASM_MATCH_STALE`(조립 트리·STEP·피처 변경) + 작업 중 아님(`ASM_MATCH_BUSY`). 행이 미완성이면 409 `ASM_ROWS_INCOMPLETE`. 검사를 실행했다면 마지막 검사가 FAIL → `ASM_CHECK_FAILED_WARN`, 현재 행·조립과 다름 → `ASM_CHECK_STALE_WARN`을 응답 `warnings`(`[{code, message}]`)에 남기고 확정은 허용한다. 확정 뒤 GET에도 같은 경고가 유지된다(확정 전에는 화면이 `check`를 직접 보인다). 확정본 `asm_match.json`의 `check`는 검사를 실행한 적이 없으면 `null`, 있으면 `{seq, sha256, rows_sha256, status, current, match_ratio_min, dist_max_mm}`(`status`·`current` 가산).
  2. **하류는 검사를 요구하지 않는다**: ①-3 DOE·④ 등록의 게이트(`asm_match_gate.require_confirmed/require_for_set`)는 원래 "확정본 + 입력 불변"만 본다(변경 없음). 하류 형상 생성(tag·morph·check, 방식 M)은 확정 행(pid 집합)으로 동작하며 검사는 사전 진단일 뿐이다.
  3. **추천 자동 적용(프런트)**: 목록 읽기 작업이 끝나 서버 행이 비어 있으면 `recommend`를 화면 행 초안으로 바로 채운다(서버가 `match.json`에 쓰지 않음 — AM-C2 1 쓰기 주체 유지). 추천이 없는 바디는 사용자가 고른다. 사용자는 확인·수정 후 [저장]만 누르면 되고, [저장]은 바뀐 표를 PUT rows로 저장한 뒤 confirm한다. [추천 적용]은 초안을 추천으로 다시 채우는 용도로 유지.
  4. **검사 시간 제한 없음**: 설정 `asm_match.check_timeout_s: float | null`(기본 **null = 상한 없음**) 추가, AM_CHECK만 이 값을 쓴다. `asm_match.timeout_s`(600)는 AM_PARTS(목록 읽기)만 유지한다 — 근거: 목록 읽기는 스트리밍 1차 색인 + sha 캐시(AM-11)로 정상이면 짧고(검사처럼 B-rep 최근접 거리 계산이 없음) 600초 초과는 멈춤·입력 오류 신호이며, 현장 실패는 검사에서만 났다. 상한을 주고 싶은 현장은 `check_timeout_s`에 양수를 쓴다(0 이하는 설정 오류). `geometry.timeout_s.check`(paicad_check·cushion write·asm write)는 asm check에 적용되지 않으며 바꾸지 않는다.
  5. **취소는 항상 가능**: 워커 공통 취소 확인(`worker.cancel_check_interval_s`)이 프로세스 트리를 종료한다. 작업 취소 API(`POST /jobs/{id}/cancel`)는 관리자 전용이라 power 사용자가 쓸 수 있게 **`POST /asm-matches/{id}/cancel`**(202 `AsmMatch`, 진행 중 ASM_MATCH 작업 대기·실행 모두 취소, 없으면 409 `JOB_TERMINAL`, 감사 `ASM_MATCH_CANCEL`)을 가산한다. MCP는 도구를 늘리지 않고(`x-mcp.exclude`) `cancel_job`(같은 토큰이 만든 작업)을 쓴다. 취소된 검사는 `check/<seq>`에 `asm_check.json`이 없어 결과로 읽히지 않고 표(행)는 그대로다.
  6. **화면**: `AsmMatchCard` 기본 흐름 = 조립 폴더 → [목록 읽기] → 추천 자동 채움 → [저장]. [검사]·검사 결과(판정·거리 열, 실패 줄, 3D 거리 색)는 "고급 — 경계 검사(선택)" 접힘(기본 접힘, 검사를 시작하거나 진행 중 검사를 복원하면 펼침) 안으로 옮겼다. 고급에는 "오래 걸릴 수 있음(대형 모델은 수십 분)" 안내, 진행률(`JobInline`)과 [취소]. 검사 FAIL·낡음은 카드에 경고 한 줄(`asm-check-warning`)을 보이되 [저장]은 막지 않는다. ①-3 "조립 매칭 사용 중" 한 줄은 유지.
  7. **호환**: 응답 필드는 가산만(`warnings` 코드 2종, 확정본 `check` null 허용·키 가산). 기존 확정본(검사 PASS 포함)은 그대로 유효. 소비자(DOE·세트 복사)는 확정본의 `check`를 읽지 않는다.


### `mesh_include_name` 의존 전수 점검 결과(§6.4, 구현)

| 위치 | 매칭 세트(방식 M) 처리 |
|---|---|
| `predict_native.py`(MESH·`_cushion_write`·`rad_assemble`) | 출력 = `P/geom/node_patch.npz`(`--out-patch`), 조립 = `geometry_asm.assemble_matched`(`P/INPUT`), 쿠션 = `--patch` |
| `geometry_sample.py`(`generate_sample`·`write_cushion_rad`) | `m_2/node_patch.npz`, 조립 `m_3`/R 직계 = 트리 사본 + `asm write`, 실패 시 `SKIPPED.json` step `assemble` |
| `geometry_native.py`(`native_inputs`·`base_values`·`run_paicad`) | `baseline_inc`·`renum_csv` 빈 값, `asm_match`·`assem_dir` 전달, `{asm_cache_dir}` 주입 |
| `geometry_cushion.py` | `node_patch` 값(없으면 공칭) |
| `doe_native.py`·`doe_native_set.py`·`stage1_native.py` | 매칭 트리·확정본 복사(digest 확인 `INPUT_CHANGED`), 기준본·RENUM 검사 생략, 없으면 409 `ASM_MATCH` |
| `np_register.py`·`prep.py`(`input_hashes`·`prep_state`) | `inputs.asm_match{rel,sha256}`·`assem_digest`, STALE 문구에 "조립 매칭" |
| `param_set_native.py`(core `validate_native_folder`)·`param_discover_native.py` | 번호 표·기준본 요구 생략, `copy_sources_native(matched)` = 트리 복사 |
| `param_set_native_train.py`(from-train) | 매칭 DOE의 트리·확정본 복사 |
| `param_set_baselines_api.py`·`stage4_native.py`(4B) | 409 `ASM_MATCH_UNSUPPORTED` |
| `fem_verify.py`·`fem_verify_plan.py`·`fem_assembly.py` | reuse = 트리 재귀 복사, rebuild = problems |
| `equiv/sides.py`·`compute.py`·`volume.py` | `mesh_tree`·`mesh_parts`·`read_tree` |
| `run_chain.py`·`predict_inputs.py`(`assembly_sources`·`assemble_into`) | Altair·방식 L 경로 전용(방식 M은 호출하지 않음) — 변경 없음 |
| `geom_preview.py`·`np_view` | 값 전달만 `native_inputs` 경유(방식 M이면 `--asm-match` 쌍 치환) — 코드 변경 없음 |

정적 점검: 방식 M 전용 모듈(`asm_tree`·`asm_match`·`commands_asm`·`asm_match_api`·`asm_match_gate`·`geometry_asm`·워커 `asm_match`)은 `mesh_include_name`을 코드에서 쓰지 않는다(`test_matched_path_modules_do_not_depend_on_include_file_names`). 프런트 문구(`ParamSetDiscoverForm.tsx`·`lib/geometry.ts`)는 Impl-Frontend 몫.
