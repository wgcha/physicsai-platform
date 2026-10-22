# 계약: 조립 매칭(STEP 바디 ↔ 조립 component) — Native 솔리드의 renum.csv·기준본 이름 요구 제거

> 상태: 초안(2026-10-22, Plan). 릴리스 제안 **v0.2.9**(paicad **0.13.0**, migration 없음 — [roadmap.md](../roadmap.md)). 기준 커밋 def0517(v0.2.8 진행 중, migration HEAD `0021_uploads`, paicad 0.12.0).
> 상위: [geometry-engine.md](geometry-engine.md)(GE, R1 모핑·§4.1 component 대응·§6.1 tag), [shell-morph.md](shell-morph.md)(SM, `/PART` 기반 대응·`assem_digest` 선례), [geometry-view.md](geometry-view.md)(GV, 3D 뷰어·FE GLB), [input-kind.md](input-kind.md)(IK, `paicad cushion write`), [native-vars.md](native-vars.md)(변수 정의 — 영향 없음), [upload-report.md](upload-report.md)(조립 폴더 업로드). 이 문서가 바꾸는 규칙은 §2.3(이 문서 우선).
> ID 규칙: 결정 `AM-n`, 시험 `V-AM-n`, 변경 메모 `AM-Cn`.

## 0. 한 줄 요약

Native 솔리드 흐름(①-3 DOE, ④ 세트 등록)에서 조립 폴더에 `RENUM_INIT.csv`와 이름이 고정된 기준본 `104_replace_node_elem.inc`를 **요구하지 않는다**. 대신 조립 폴더에서 component(`/PART`) 목록을 자동으로 뽑고, 사용자가 **STEP 바디(행) ↔ 조립 component(옆 열 드롭다운)** 매칭 표를 확정하며, 저장 전에 **component 외곽 노드 좌표 ↔ CAD B-rep 경계면 거리 검사**를 통과해야 한다. 확정된 매칭(`asm_match.json`)이 RENUM 요소 구간(component 분할)과 기준본 파일(쿠션 메시 위치)을 대신하며, 이후 tag·morph·check·DOE·예측·쿠션 rad는 R1(노드 ID 불변, `/NODE` 좌표만 변경) 그대로다.

---

## 1. 배경·범위

### 1.1 사용자 근거(원문, 2026-10-22)

> "stp파일 올리고 파라미터 생성햇고 파라미터 선택햇어. 조립파일 올렷어. renum.csv랑 baseline.inc를 원하네. 이런거 없게 하려고 native인데. 차라리 조립폴더에서 component 목록 확인하고 거기에서 내가 해당 step파일과 동일한 조립내 component와 step파일 내 compound랑 매칭하게해. compound 목록이 뜨고 옆 열에 조립목록내 component선택해 매칭하는거지. 거기서 외곽 노드 좌표랑 캐드 경계면과 일치하는지 체크도하고."

### 1.2 현재 동작(코드 확인, def0517)

| 파일 | 출처(원래 흐름) | Native에서 하는 일 | 요구 위치 |
|---|---|---|---|
| `RENUM_INIT.csv`(`predict.renum_csv_name`) | Altair 흐름에서 HyperMesh include TCL(`commands.mesh`, `{renum_csv}`)이 SimLab 쿠션 메시(`EPS_mesh_0000.rad`)의 노드·요소 번호를 component별 예약 구간으로 재지정할 때 쓰는 **사용자 준비 표**(`part,node_start,elem_start`) | 기준본 TETRA4 요소를 `elem_start` 구간으로 잘라 component(이름·순서)를 만든다(GE §4.1, `paicad/mesh/radioss.py: components()`). 바디 ↔ component 이름 대응(GE §4.1 규칙 1~4), 파라미터 순서(RENUM 행 순), `cushion write`의 쿠션 요소 선택 | API `job_params/stage1_native.py: native_doe_gen`(409 `PREREQUISITE_MISSING` missing `RENUM_CSV`), 워커 `doe_native.dg_prep`(`INPUT_INVALID`), `param_discover_native.py`(problems `RENUM_CSV_MISSING`), paicad `tag`·`check`·`run`·`selftest`·`cushion write`·`view preview --fe`(필수 인자 `--renum-csv`) |
| `104_replace_node_elem.inc`(`predict.mesh_include_name`) | Altair 흐름 m_2(HyperMesh 변환)의 **산출물** = 공칭 형상 쿠션 메시 include(노드·요소만, `/PART`·`/PROP` 없음 — GE Q3) | R1 기준본: tag 대상 노드·요소, morph가 `/NODE` 좌표만 바꿔 같은 이름으로 다시 쓰는 파일, 조립(`assemble_into`)에서 이 이름의 파일을 새 include로 교체 | 같은 위치(missing `BASELINE_INC`·`BASELINE_INC_MISSING`), 프런트 `NATIVE_ASSEM_TEXT`·`BASELINE_INC_MISSING` 문구, `assembly_sources`·`assemble_into`(이름으로 교체) |

결론: 두 파일 모두 SimLab/HyperMesh 체인의 입력·산출물이며, Native가 실제로 필요한 정보는 ① 어느 요소가 어느 쿠션 바디인지 ② 쿠션 메시가 어느 파일에 있는지 두 가지뿐이다. ①은 요소 블록 머리 `/TETRA4/<part_id>`와 `/PART/<id>` 제목으로, ②는 그 PART의 노드·요소를 정의한 파일을 찾아서 얻는다. 쉘 경로(SM §4.1)는 이미 이 방식이다(`shell/assem.py: read_assembly`, `shell/cad.py: correspond` — `PART:<id>`).

### 1.3 범위 / 비범위

| 범위 | 비범위 |
|---|---|
| Native **솔리드**(TETRA4) ①-3 DOE(①-1 추출 기준)·④ 세트 등록(새 Native 템플릿 STEP)·①→④ from-train, 그 뒤 ④ 단건·일괄·⑥ 내장·쿠션 rad(IK) | Altair 경로(GE-11, 무변경), 쉘 경로(이미 `/PART` 기반), 다중 baseline(4B — 기존 RENUM 방식 유지, §7.3), TETRA10·HEXA(GE §1.3) |
| 조립 폴더 component 목록 추출, 매칭 표(추천 + 사용자 확정), 경계 일치 검사, 3D 불일치 표시 | 자동 정렬(강체 맞춤·스케일 보정) — 감지·안내만(GE Q1 유지) |
| RENUM 구간·기준본 이름 대체 알고리즘, 기존 renum 세트 호환 | 재메시·번호 재지정(GE-1) |

---

## 2. 용어·결정

### 2.1 용어

| 용어 | 뜻 |
|---|---|
| 바디(compound 행) | 공칭 STEP의 이름 있는 솔리드 = `parameter_features.json` `bodies[]` 한 항목(GE §4.3). 사용자가 말한 "compound" 행. 이름 없는 바디는 GE §4.1처럼 오류 |
| component | 조립 폴더의 `/PART/<pid>`(제목 = `/PART` 다음 줄). 요소 블록 `/<KW>/<pid>`로 소속을 정한다 |
| 매칭 행 | `{body, pids[]}`. 바디 1개 ↔ component ≥1개(§3.2) |
| 쿠션 파일(`cushion_file`) | 매칭된 모든 pid의 노드·요소를 정의한 조립 폴더 직계 파일 1개. RENUM 방식의 기준본 자리 |
| 외곽 노드 | 매칭 행 요소 합집합의 외피(한 요소에만 속한 면, GE §2.1 경계 노드)의 노드 |
| 매칭 묶음 | `<study>/asm_match/<match_id>/` — 목록·초안·검사·확정본 |

### 2.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| AM-1 | Native 솔리드의 component 정의 = **`/PART` id 집합**(매칭 표), 기준본 = **쿠션 파일 자동 탐지**(이름 무관). `RENUM_INIT.csv`·`104_replace_node_elem.inc` 이름 요구 제거 | 사용자 원문, SM 선례 |
| AM-2 | 매칭은 **추천은 초안, 확정은 사용자**(GE-13과 같은 원칙). 저장 = 확정이며 저장 전 경계 검사 PASS 필수 | 오매칭 시 학습데이터 전체 오염 |
| AM-3 | 경계 검사 허용오차 = tag와 **같은 값·같은 식**(`geometry.defaults.tag`: `tol = max(tol_abs_mm 0.05, tol_rel 1e-4 · L_body)`, `match_ratio ≥ min_match_ratio 0.98`). 새 허용오차 키 없음 | 검사 PASS면 tag의 `GEOM_BASELINE_MISMATCH`가 나지 않음을 보장(단일 출처) |
| AM-4 | 바디 1 ↔ component N(1:N) 허용(요소 합집합 = 한 component), component 1 ↔ 바디 N 금지, component는 한 행에만 | CAD 1바디가 메시에서 여러 PART로 나뉘는 경우 수용. PART 하나를 바디별로 나눌 근거 없음 |
| AM-5 | 좌표계·단위 차이는 **감지·안내만**(`ASM_OFFSET_SUSPECT`·`ASM_UNIT_SUSPECT`), 자동 보정 없음 | GE Q1(자동 정렬 없음) 유지 |
| AM-6 | 노드 ID·요소·연결 불변, 매칭 pid의 노드 좌표만 변경. 쿠션 파일의 다른 줄·다른 파일은 바이트 동일 | GE-1, tie·RBE 참조 유지 |
| AM-7 | paicad 기존 명령은 `--renum-csv`와 **배타 대안** `--asm-match`를 받는다(정확히 하나). 기존 argv 그대로 유효 | GE-C10 동결 인자 호환 |
| AM-8 | 플랫폼은 설정 템플릿을 고치지 않고 `"--renum-csv","{renum_csv}"` 쌍을 `"--asm-match","{asm_match}"`로 바꿔 끼운다(GE §7.3.1 쌍 규칙과 같은 방식) | 관리자 설정 변경 없이 배포 |
| AM-9 | 저장 위치 = Study 아래 `asm_match/<match_id>/`, 소비자(DOE·세트)는 확정본을 자기 폴더로 복사·sha256 기록. **DB 변경 없음**(상태는 파일 + 작업 행) | SPDM 쓰기 금지, migration 없음 |
| AM-10 | 기존 RENUM 세트·DOE는 그대로 동작. 새 요청은 `asm_match_id`가 있으면 매칭 경로, 없으면 기존 검사(두 파일 모두 있을 때만) | 호환 |

### 2.3 기존 계약에서 바뀌는 규칙(이 문서 우선)

| 기존 | 변경 |
|---|---|
| GE §4.1 번호 표 "native 필수(`RENUM_CSV_MISSING`)" | 매칭 세트는 불필요. component 요소 집합 = 매칭 행 pid들의 `/TETRA4/<pid>` 블록 합집합(§5.1) |
| GE §4.1 기준본 `S/radioss_assem/{predict.mesh_include_name}` 고정 이름 | 매칭 세트는 `S/radioss_assem/<cushion_file>`(이름 무관, §5.2). 출력 include의 작업 이름은 계속 `predict.mesh_include_name`, 조립 사본에서만 `cushion_file` 이름으로 놓임(§5.4) |
| GE §2.3 `MESH_INCLUDE_NOT_IN_ASSEM` → native 오류 `BASELINE_INC_MISSING` | 매칭 세트에는 적용하지 않음(쿠션 파일은 검사가 보장) |
| GE §4.1 바디 대응 규칙 1~4·`body_map.json` | 매칭 세트는 `asm_match.json`이 유일한 대응. `body_map.json`이 함께 있으면 무시 + 경고 `BODY_MAP_IGNORED` |
| GE §6.5 간섭 대상 = 기준본 파일 제외 전 조립 | 매칭 세트는 **매칭 pid 요소만 제외**(쿠션 파일 안 다른 PART는 제품으로 포함) |
| GV §2.3 레인 `PREVIEW` 허용 명령(`paicad_view_preview`·`paicad_shell_view_preview`) | `paicad_asm_parts`·`paicad_asm_check` 추가 |
| `stage1_native.native_doe_gen` missing `BASELINE_INC`·`RENUM_CSV` | `asm_match_id`가 없고 두 파일도 없으면 missing `["ASM_MATCH"]`(§6.4) |

---

## 3. 흐름·화면

### 3.1 흐름

```text
①-1 STEP 업로드·추출(기존) → ①-2 파라미터 선택(기존)
  → [조립 매칭 카드] 조립 폴더 지정(경로 또는 업로드 RADIOSS_ASSEM)
      → 작업 ASM_MATCH(mode=parts): paicad asm parts → component 목록 + 추천
      → 매칭 표 편집(PUT rows) → "검사" → 작업 ASM_MATCH(mode=check): paicad asm check
      → PASS → "저장"(confirm) → asm_match.json 확정
  → ①-3 DOE(asm_match_id) → dg_prep: 조립 사본 + D/cad/asm_match.json → tag(--asm-match) → run마다 paicad run
④ "새 Native 템플릿(STEP)": 등록 폼에서 STEP·조립 폴더 지정 → 같은 매칭 카드(바디 목록은 STEP에서 직접) → PARAM_SET_NATIVE(asm_match_id)
```

renum.csv·`104_replace_node_elem.inc`는 어느 단계에서도 묻지 않는다.

### 3.2 매칭 표(필수 요소만, 라이트 테마, 2560×1440 기준)

위치: ① 화면 `ParamTableCard` 아래·`DoeGenCard` 위 새 카드 "조립 매칭"(Native 솔리드일 때만), ④ 등록 폼의 조립 폴더 칸 아래 같은 컴포넌트. 카드 폭 = 기존 카드 폭, 표 + 오른쪽 3D 창(GV 뷰어 재사용, 표 60% · 3D 40%).

| 열 | 내용 |
|---|---|
| STEP 바디 | 이름 · 부피(cm³, 유효 3자리) · bbox 크기(mm, `X×Y×Z`) |
| 조립 component | 드롭다운(검색 가능): `PART id · 제목 · TETRA4 n개`(추천 점수순, 추천 항목에 "추천" 표지). 행 안 "+ component"로 1:N 추가(칩), "매칭 안 함" 항목 |
| 판정 | 검사 전 `—`, 이후 `일치`/`불일치`/`검사 필요`(행 변경 시) |
| 거리 | `최대 x.xxx · p95 x.xxx mm · 일치율 99.6%`(검사 후) |

- 카드 머리: 조립 폴더 경로 · starter 이름 · "component 213개(TETRA4 4개)" · 단추 `추천 적용` `검사` `저장`.
- 표 아래 한 줄: "매칭하지 않은 component 209개는 바꾸지 않습니다(간섭 검사 대상)".
- 드롭다운은 TETRA4만 가진 PART만 선택 가능, 그 밖은 회색 + 사유("TETRA4가 아님: /SHELL 1200개"). 다른 행에서 고른 PART는 회색("CUSH_R 행에서 사용").
- "매칭 안 함": 그 바디에 `use=true` 파라미터가 있으면 선택 불가(사유 "선택한 파라미터 N개가 이 바디에 있습니다"). 매칭 안 한 바디는 tag·morph 대상에서 빠진다.
- 행 클릭 → 3D 창: CAD 바디 반투명 + 외곽 노드 표면을 거리 색 맵(`_DIST_MM`, 0 ~ tol 녹색, tol 초과 빨강), 불일치 노드 상위 N개 점 표시. 검사 실패 행은 실패 코드 문구를 표 아래에 한 줄씩.
- 단추 상태: `검사` = 모든 행이 선택 또는 "매칭 안 함" + 매칭 행 ≥1. `저장` = 마지막 검사 PASS + 그 뒤 행·입력 변경 없음. DOE `생성` 단추 사유 문구에 "조립 매칭을 저장하세요" 추가.

---

## 4. 파일 계약

모든 JSON은 GE §4 공통 규칙(UTF-8, `schema_version: 1`, `engine`·`engine_version`, mm-ton-s, 변환 없음, `geometry.max_report_bytes` 이하).

### 4.1 매칭 묶음 `<study>/asm_match/<match_id>/`

| 경로 | 작성 | 내용 |
|---|---|---|
| `match.json` | 플랫폼 | `{schema_version, match_id, state, source:{kind:"train"\|"path", cad_rel, features_rel\|null}, assem:{path(표시용), digest}, rows:[…], rows_sha256, last_check:{seq, status, rows_sha256}\|null, created_by, created_at, updated_at}` — 초안·상태 |
| `parts/asm_parts.json` | `paicad asm parts` | §4.2 |
| `check/<seq>/asm_check.json`, `check/<seq>/match_fe.glb` | `paicad asm check` | §4.3. 이전 seq는 `_backup` 이동 대신 유지(작음), 최신만 표시 |
| `asm_match.json` | 플랫폼(confirm) | §4.4 확정본(소비자가 복사) |

`state`: `SCANNING → DRAFT → CHECKING → CHECKED → CONFIRMED`, 실패 `FAILED`(목록 작업 실패), 입력 변경 `STALE`. 확정 후 행을 바꾸면 새 `match_id`(확정본 불변).

`assem.digest` = SM §4.2 `inputs.assem_digest`와 같은 정의(조립 폴더 `*.rad`·`*.inc` 상대 경로·sha256 정렬 목록의 sha256), 단 대상은 **직계 파일**(`assembly_sources` 복사 규칙과 같게, `eps_mesh*` 제외).

### 4.2 `asm_parts.json`

```json
{"schema_version":1,"engine":"native","engine_version":"0.13.0","status":"OK","code":null,"message":null,
 "assem":{"digest":"sha256:…","starter":"MODEL_0000.rad","files":12,"includes":{"MODEL_0000.rad":["104_replace_node_elem.inc","product.inc"]}},
 "bodies":[{"body":"CUSH_L","volume":812345.2,"bbox":[0,0,0,120,80,60]}],
 "parts":[{"pid":3000001,"title":"CUSH_L","file":"104_replace_node_elem.inc","node_files":["104_replace_node_elem.inc"],
           "elems":{"TETRA4":41230},"nodes":9120,"volume":811902.7,"bbox":[0,0,0,120,80,60],"solid_ok":true}],
 "recommend":[{"body":"CUSH_L","pids":[3000001],"score":0.97,"basis":{"bbox_iou":0.99,"volume_ratio":0.999,"name":1.0,"renum":false}}],
 "warnings":[]}
```

- `parts`: 요소를 가진 모든 PART(제목 없는 PART는 `title:""`, 화면 `PART:<id>`). `solid_ok` = 요소가 TETRA4만. `volume` = TETRA4 부피 합(mm³), 그 밖 PART는 `null`. 개수 상한 `asm_match.max_parts`(넘으면 `ASM_TOO_MANY_PARTS`).
- `bodies`: `--features`면 그 파일의 `bodies`(OCP 불필요), `--cad`면 STEP을 읽어 같은 모양.
- `recommend`(바디마다 최대 1행, 1:1 초안): 하드 게이트(bbox 중심 거리 ≤ 0.1·바디 bbox 대각선, 부피비 ≥ 0.8) 통과 쌍에 `S = 0.6·bbox_iou + 0.3·volume_ratio + 0.1·name`(name: 정규화 일치 1, 포함 0.5, 그 밖 0 — GE §4.1 정규화), 헝가리안 최대 합, `S < asm_match.recommend_min_score`(기본 0.6)면 추천 없음. 조립 폴더에 `{predict.renum_csv_name}`이 있으면 RENUM 구간 ∩ pid로 얻은 대응을 `score 1.0, basis.renum: true`로 우선(호환 편의, 확정은 여전히 사용자).
- 실패: 조립 폴더 starter 0·2개 이상 `GEOM_INPUT_INVALID`(IK-C1 판별 규칙과 같음), TETRA4 PART 0개 `ASM_NO_SOLID_PART`.

### 4.3 `asm_check.json`

```json
{"schema_version":1,"engine":"native","engine_version":"0.13.0","status":"PASS","code":null,"message":null,
 "rows_sha256":"…","assem":{"digest":"sha256:…","cushion_file":"104_replace_node_elem.inc","cushion_file_sha256":"…","included_from":"MODEL_0000.rad"},
 "tolerance":{"abs_mm":0.05,"rel":1.0e-4,"min_match_ratio":0.98},
 "rows":[{"body":"CUSH_L","pids":[3000001],"status":"PASS","code":null,
          "skin_nodes":4210,"match_ratio":0.9995,"tol_mm":0.05,
          "dist_mm":{"mean":0.003,"p95":0.011,"p99":0.019,"max":0.041},
          "bbox_delta_mm":[0.0,0.0,0.0,0.01,0.0,0.0],
          "faces":{"total":42,"uncovered":[]},
          "worst":{"count":2,"file":"worst_CUSH_L.npz"},
          "suggest":null}],
 "file_checks":{"split_files":[],"shared_nodes":0,"duplicate_parts":[]},
 "glb":{"file":"match_fe.glb","sha256":"…"},"warnings":[],"elapsed_s":4.2}
```

판정 규칙:

1. 행 요소 집합 = pid들의 `/TETRA4/<pid>` 합집합. 다른 키워드 요소가 있으면 행 FAIL `GEOM_UNSUPPORTED_ELEMENT`.
2. 외곽 노드 = 합집합 외피 노드(GE `skin_triangles`). 거리 = 노드 → 바디 B-rep 최근접(GE §6.1 tag의 꼭짓점·엣지·면 분류와 **같은 코드**). `tol`·`match_ratio` 정의 = GE §6.1 4번.
3. 행 PASS ⇔ `match_ratio ≥ min_match_ratio`. 아니면 FAIL `ASM_BOUNDARY_MISMATCH`(문구 "외곽 노드가 CAD 경계면과 맞지 않습니다 — 일치율 x%, 최대 y mm").
4. 면 덮임: B-rep 면 중 tol 안 노드가 0개인 면 → `faces.uncovered`(면 번호 `F<k>`·그 면을 쓰는 피처 이름), 경고 `ASM_FACE_UNCOVERED`(판정 불변 — 모핑에서 그 면을 움직일 노드가 없음을 알림).
5. 좌표계·단위 진단(FAIL 행만, 정보): `s` = 외피 bbox 대각선 / 바디 bbox 대각선. `|s/k − 1| ≤ 0.01`인 `k ∈ {1000, 0.001, 25.4, 1/25.4, 10, 0.1}` → `suggest:{code:"ASM_UNIT_SUSPECT", factor:k}`. `|s − 1| ≤ 0.01`이면 bbox 중심 차 `t`만큼 옮겨 다시 재고 `match_ratio_after ≥ min_match_ratio`면 `suggest:{code:"ASM_OFFSET_SUSPECT", translate_mm:[dx,dy,dz], match_ratio_after}`. 회전은 감지하지 않는다. 보정은 하지 않는다(AM-5) — 문구 "CAD를 조립과 같은 원점·mm로 다시 내보내세요".
6. 파일 검사(전체 FAIL, `status: FAIL`):
   - `ASM_SPLIT_FILES`: 매칭 pid들의 요소 또는 그 노드 정의가 직계 파일 2개 이상에 걸침(목록 최대 10개).
   - `ASM_SHARED_NODES`: 매칭 pid 노드를 매칭 안 된 PART의 요소(1D·RBE 포함 요소 블록)가 참조(개수·PART 최대 10개). R1이 다른 component를 바꾸지 않게 하기 위함. tie(`/INTER/TYPE2`)·`/RBE*` 등 정의 참조는 해당 없음(GE §6.5 tie 검사 대상).
   - `ASM_FILE_NOT_INCLUDED`: 쿠션 파일이 starter에서 `#include` 연쇄로 닿지 않음(쿠션 파일 = starter 자체는 허용).
   - 같은 노드 ID 중복 정의 `GEOM_INPUT_INVALID`.
7. 경고 `ASM_DUPLICATE_PART`: 서로 다른 행의 외피가 같은 위치(대칭이 아닌 중복 메시) — bbox 일치 + 외피 노드 90% 이상 서로 tol 안.
8. 전체 PASS ⇔ 모든 매칭 행 PASS + 파일 검사 통과. 매칭 안 함 행은 판정 제외.
9. `match_fe.glb`: GV §4.1 FE GLB 구조 재사용(노드 = 행 바디 이름, 외피 삼각형, 속성 `POSITION`·`NORMAL`·`_DIST_MM`(노드 거리)·`_ELEM_ID`). `worst_*.npz`: 거리 상위 `asm_match.worst_nodes`(기본 2000)개 `node_id·xyz·dist`(paicad·플랫폼 변환기만 읽음, 프런트에는 manifest 요약 + GLB).

### 4.4 확정본 `asm_match.json`

```json
{"schema_version":1,"engine":"native","engine_version":"0.13.0","match_id":"…",
 "cad":{"rel":"model.step","sha256":"…"},"features_sha256":"…|null","unit_system":"mm-ton-s",
 "assem":{"digest":"sha256:…","starter":"MODEL_0000.rad","cushion_file":"104_replace_node_elem.inc","cushion_file_sha256":"…"},
 "rows":[{"body":"CUSH_L","pids":[3000001],"titles":["CUSH_L"]},{"body":"CUSH_R","pids":[3000002,3000003],"titles":["CUSH_R_A","CUSH_R_B"]}],
 "excluded_bodies":[],
 "check":{"seq":3,"sha256":"<asm_check.json sha256>","rows_sha256":"…","match_ratio_min":0.9991,"dist_max_mm":0.041},
 "confirmed_by":"user","confirmed_at":"2026-10-22T…Z"}
```

- 행 순서 = `bodies` 순서(= 파라미터 이름 순서, GE §4.3 "component 순" 대체). component 이름 = **바디 이름**(①-1 추출이 RENUM 없이 바디 이름을 쓰므로 파라미터 이름 불변).
- 플랫폼은 이 파일을 읽어 `{baseline_inc}` = `<조립 사본>/<cushion_file>`을 정하고, paicad는 `rows`·`excluded_bodies`·`assem.cushion_file`만 쓴다.

---

## 5. 내부 대체 알고리즘(RENUM·기준본 역할)

### 5.1 component 분할(RENUM 대체)

`components_from_match(mesh, match)` → 행마다 `Component(part=body, row=k, elem_range=(min,max), tet_ids, tets, node_ids)` — 기존 `Component` 형식 그대로(`elem_range`는 정보용). 요소 집합 = pid TETRA4 블록 합집합. RENUM의 `RENUM_NODE_RANGE` 경고는 없다. 두 행이 노드를 공유하면 GE §4.1처럼 한 연결 성분으로 푼다. 이후 tag·morph·check 내부 코드는 `Component` 목록만 받으므로 무변경.

### 5.2 기준본(쿠션 파일) 대체

- `asm check`가 쿠션 파일을 정해 확정본에 기록(§4.3 6). paicad `--baseline-inc`에는 그 파일을 넘긴다(인자 계약 불변).
- 쿠션 파일에 다른 PART(제품 등)가 함께 있어도 된다: morph는 매칭 pid 노드 줄의 좌표 필드만 바꾸고 나머지 바이트는 그대로(GE §6.4 쓰기 규칙). starter 자체가 쿠션 파일이어도 같다.
- check (b) 편차·(c) 품질은 매칭 행 요소만, (d) 간섭은 "매칭 pid 요소를 뺀 조립 전체"(쿠션 파일 안 다른 PART 포함), (e) tie는 기존과 같다.

### 5.3 노드 ID·다른 component 불변(AM-6)

- 바뀌는 바이트 = 쿠션 파일의 매칭 pid 노드 `/NODE` 줄 좌표 필드뿐. 다른 파일은 복사만. 매칭 안 한 바디·PART는 좌표도 그대로.
- 공유 노드는 §4.3 6에서 사전 차단되므로 morph가 다른 PART 노드를 움직이는 경우는 없다.

### 5.4 조립·쿠션 rad

- 작업 산출 이름은 그대로 `predict.mesh_include_name`(`P/geom/`·`R/m_2/`·`R/_paicad/` — 기존 경로·판정 무변경).
- `assemble_into`(④ m_3, ①-3 FLAT run 직계)는 매칭 세트일 때 **교체 대상 이름 = `cushion_file`**: 조립 사본에서 `cushion_file`을 빼고 새 include를 `cushion_file` 이름으로 놓는다. `cushion_file == mesh_include_name`이면 오늘 동작과 같다.
- `paicad cushion write --asm-match`: 쿠션 요소 = 매칭 행 pid 합집합(RENUM 구간 대신), 출력·IK §5.2 규칙 무변경. 쿠션 단독 rad의 `/PART`·`/PROP`·`/MAT`은 매칭 pid 기준으로 찾는다.

### 5.5 tag 보고

`tag.json` 추가 키(가산): `asm_match:{sha256}|null`, `parts[].pids`(매칭 세트), `parts[].renum_row`는 `null`. 매칭 세트의 tag가 `GEOM_BASELINE_MISMATCH`를 내면 문구 끝에 "조립 매칭 검사를 다시 하세요".

---

## 6. CLI·API·설정

### 6.1 paicad(Impl-Geom, 0.13.0 MINOR)

| 명령 | 인자(굵게 = 필수) | 성공 판정 파일 |
|---|---|---|
| `paicad asm parts` | **`--assem-dir`**, **`--out-dir`**, `--features`(①, OCP 없이) 또는 `--cad`(④, 둘 중 하나 필수), `--renum-csv`(있으면 추천 보조), `--options` | `asm_parts.json`(`status: OK`) |
| `paicad asm check` | **`--cad`**, **`--assem-dir`**, **`--match`**(rows JSON = `match.json`의 `{rows, excluded_bodies}`), **`--out-dir`**, `--features`, `--options`(tag 절 사용), `--no-glb` | `asm_check.json`(존재 = 성공, 내용 `status` PASS/FAIL) |
| `tag`·`check`·`run`·`selftest`·`cushion write`·`view preview --fe` | 기존 `--renum-csv` 자리에 **배타 그룹** `--renum-csv` \| `--asm-match`(정확히 하나) | 기존과 같음 |
| `extract` | `--renum-csv` \| `--asm-match` 선택(있으면 순서·대응 검사) | 기존과 같음 |

- 종료코드: GE §5.4 + `asm check` FAIL은 판정 파일을 쓰고 0이 아닌 새 코드 `EXIT_ASM`(값은 Impl-Geom이 GE §5.4 표에 추가). 실패 코드: `ASM_BOUNDARY_MISMATCH`·`ASM_SPLIT_FILES`·`ASM_SHARED_NODES`·`ASM_FILE_NOT_INCLUDED`·`ASM_NO_SOLID_PART`·`ASM_TOO_MANY_PARTS`·`ASM_MATCH_INVALID`(확정본 형식·pid 없음·digest 불일치), 경고 `ASM_FACE_UNCOVERED`·`ASM_DUPLICATE_PART`·`BODY_MAP_IGNORED`, 진단 `ASM_UNIT_SUSPECT`·`ASM_OFFSET_SUSPECT`.
- `--asm-match` 사용 시 paicad는 `assem.digest`·`cushion_file_sha256`을 다시 계산해 다르면 `ASM_MATCH_INVALID`.
- 조립 파서는 `shell/assem.py: read_assembly`를 솔리드에도 쓰게 공용화(직계 파일 모드 추가)하거나 같은 규칙의 새 모듈 — Impl-Geom 선택, numpy만(OCP 없음).

### 6.2 설정(Impl-Backend, `config/platform.example.yaml` 추가만)

```yaml
asm_match:
  enabled: true
  max_parts: 5000
  recommend_min_score: 0.6
  worst_nodes: 2000
  timeout_s: 600
commands:
  paicad_asm_parts: ["{paicad}", "asm", "parts", "--assem-dir", "{assem_dir}", "--features", "{features_json}", "--renum-csv", "{renum_csv}", "--options", "{options_json}", "--out-dir", "{out_dir}"]
  paicad_asm_check: ["{paicad}", "asm", "check", "--cad", "{cad_input}", "--features", "{features_json}", "--assem-dir", "{assem_dir}", "--match", "{match_rows_json}", "--options", "{options_json}", "--out-dir", "{out_dir}"]
```

- `TEMPLATE_SPECS`: 두 키 `required=False`, argv[0] = `{paicad}`(V-GE-1). 새 placeholder `match_rows_json`, `asm_match`. ④ 경로(`--cad`)는 `"--features","{features_json}"` 쌍을 `"--cad","{cad_input}"`으로 바꿔 끼운다(같은 쌍 규칙). `{renum_csv}` 없으면 쌍 생략(GE §7.3.1).
- **쌍 치환(AM-8)**: 매칭 세트·DOE의 모든 `paicad_*` 템플릿에서 정확히 `"--renum-csv","{renum_csv}"` 쌍을 `"--asm-match","{asm_match}"`로 바꾼다. `{baseline_inc}` = 조립 사본의 `cushion_file`.
- 허용오차는 `geometry.defaults.tag`(AM-3). 키 null·`enabled: false` → API 409 `TEMPLATE_NOT_CONFIGURED`("관리자 설정 필요: commands.paicad_asm_parts").

### 6.3 API(Backend, `backend/openapi.json` 갱신 → 프런트)

| 메서드·경로 | 본문 | 응답 |
|---|---|---|
| `POST /studies/{sid}/asm-matches` | `{radioss_assem_path, cad:{kind:"train"}\|{kind:"path", path}}` | 202 `{match_id, job_id}`(작업 `ASM_MATCH` mode parts). 422 경로 규칙, 409 `PREREQUISITE_MISSING`(train인데 ①-1 Native 추출 없음) |
| `GET /asm-matches/{id}` | – | `AsmMatch = {match_id, study_id, state, source, assem:{display_path, digest, starter}, bodies[], parts[], recommend[], rows[], check:{seq, status, rows_sha256, rows:[요약], file_checks, glb_url}\|null, confirmed:{sha256, confirmed_at}\|null, stale_reason\|null}` |
| `PUT /asm-matches/{id}/rows` | `{rows:[{body, pids:[int]}], excluded_bodies:[str]}` | 200 `AsmMatch`(state DRAFT, check 무효). 422 `ASM_ROW_INVALID`(+`body`, 사유: 모르는 바디·pid, pid 중복, `solid_ok=false`, 바디 누락, use 파라미터가 있는 바디 제외), 409 `ASM_MATCH_CONFIRMED` |
| `POST /asm-matches/{id}/check` | – | 202 `{job_id}`(mode check). 409 `ASM_ROWS_INCOMPLETE` |
| `POST /asm-matches/{id}/confirm` | – | 200 `AsmMatch`(CONFIRMED). 409 `ASM_CHECK_REQUIRED`(마지막 검사 없음·FAIL·rows 다름)·`ASM_MATCH_STALE`(조립·STEP·피처 sha 변경) |

- 쓰기: Study 프로젝트 power 이상 + CSRF(쿠키) 또는 `pai_` Bearer(x-mcp 도구). `x-mcp`: 5개 모두 도구(`asm_match_create`·`asm_match_get`·`asm_match_set_rows`·`asm_match_check`·`asm_match_confirm`), 검사 GLB 미디어는 기존 artifacts media 경로(새 kind `ASM_MATCH_GLB`, `x-mcp.exclude` 이진). 용어집 `ko`: "조립 매칭", `ASM_*` 코드.
- 작업: 새 job_type **`ASM_MATCH`**(`JOB_KINDS` 등록, `SUMMARIES`에 `asm_match` 엔티티), 레인 `PREVIEW`(전역 슬롯 미사용), step `AM_PARTS` 또는 `AM_CHECK`(params.mode), 타임아웃 `asm_match.timeout_s`. 결과 요약(DB `jobs.result`)은 상태·개수·`match_ratio_min`·`dist_max_mm`만.
- **DB 변경 없음**(AM-9): 매칭 상태는 `match.json`, 소비자는 `jobs.params`에 `asm_match_id`·`asm_match_sha256`, 세트·DOE 폴더 `prep.json`에 기록.

### 6.4 소비자 변경(Backend·Worker)

| 위치 | 변경 |
|---|---|
| `native_doe_gen`(①-3) | params `asm_match_id` 선택. 있으면 CONFIRMED·`source.kind=train`·STEP/피처 sha 현재와 같음·`radioss_assem_path`의 digest = 확정본 digest(아니면 409 `ASM_MATCH_STALE`), 기준본·RENUM 검사 생략. 없으면 기존 검사(두 파일 모두 있으면 통과), 하나라도 없으면 409 `PREREQUISITE_MISSING` missing `["ASM_MATCH"]` 문구 "조립 매칭을 저장하세요" |
| `doe_native.dg_prep` | 조립 사본 A 생성 뒤 A의 digest = 확정본 digest 확인(`INPUT_CHANGED`), `D/cad/asm_match.json` 복사, `body_map.json` 복사 생략 |
| `PARAM_SET_NATIVE`(④) | params `asm_match_id`(source path, cad sha = 세트 STEP). `S/cad/asm_match.json` 복사, NP_TAG가 `--asm-match`. `param_discover_native`: `asm_match_id`가 있으면 `BASELINE_INC_MISSING`·`RENUM_CSV_MISSING` problems 제외 |
| from-train(①→④) | `D/cad/asm_match.json` → `S/cad/asm_match.json` 복사 |
| `prep.json`(GE §4.2) | `inputs.asm_match:{rel:"cad/asm_match.json", sha256}\|null`(키 없음 = null), 매칭 세트는 `baseline_inc.name = cushion_file`, `renum_csv: null`. 유효성에 `asm_match` sha 포함(다르면 `GEOM_PREP_STALE`) |
| `native_inputs`·`run_paicad` | 쌍 치환(§6.2), `{baseline_inc}` = 쿠션 파일 |
| `assembly_sources`·`assemble_into` | 인자 `replace_name`(기본 `mesh_include_name`, 매칭 세트 = `cushion_file`) |
| `mesh_include_name`로 파일을 찾는 그 밖 코드(`fem_verify`·`equiv/sides`·`np_register`) | 작업 산출 이름은 그대로라 대부분 무변경. 조립 사본(`INPUT`·`R` 직계)에서 이 이름으로 찾는 곳은 `cushion_file`을 쓰도록 전수 점검(Backend) |

### 6.5 프런트(Impl-Frontend)

새 컴포넌트 `AsmMatchCard`(①·④ 공용): 조립 폴더 입력(기존 경로 입력 + 업로드 purpose `RADIOSS_ASSEM` 재사용), 매칭 표(§3.2), 3D 창(GV 뷰어 FE 모드, 색 맵 속성 `_DIST_MM` 선택 지원), 상태 폴링(기존 작업 폴링). `DoeGenCard`(native, 세트 기준 아님)는 확정된 `asm_match_id`를 params에 넣고, 없으면 생성 불가 사유 표시. `NATIVE_ASSEM_TEXT`("기준 메시 104_… 필요")는 매칭 경로에서 "조립 매칭 필요"로 바뀐다. 문구 한국어.

---

## 7. 호환

1. **기존 RENUM 세트·DOE**: `prep.json`에 `asm_match` 없음 → 기존 인자(`--renum-csv`)·기존 기준본 이름 그대로. paicad 0.13.0이 기존 argv를 그대로 받으므로 준비본 재생성 불필요(엔진 MINOR 차이 경고만, GE §17).
2. **RENUM 파일이 있는 새 조립 폴더**: 매칭 카드가 RENUM 대응을 추천으로 채운다(§4.2). 사용자가 매칭 없이 DOE를 만들면(API·MCP) 기존 검사로 통과 — 화면은 항상 매칭 카드를 쓴다.
3. **다중 baseline(4B)**: 1차는 RENUM 방식만. `asm_match_id`와 `BL_MAP`을 함께 쓰면 409 `ASM_MATCH_UNSUPPORTED`("다중 baseline은 아직 조립 매칭을 지원하지 않습니다").
4. **쉘 세트**: 무관(이미 `/PART` 기반, `asm_match_id`를 주면 422).
5. **Altair**: 무변경(GE-11).
6. 데이터셋·모델: 매칭 세트와 RENUM 세트는 같은 엔진(native)이라 섞을 수 있다(형상 결과가 같으면 바이트 동일 — V-AM-6).

---

## 8. 시험(V-AM-n)

| # | 내용 | 소유 |
|---|---|---|
| V-AM-1 | 합성 조립(gmsh 쿠션 2개 + 제품 쉘 + `/PART` 카드는 starter, 노드·요소는 별도 inc): `asm parts --features`가 PART·제목·파일·TETRA4 수·부피를 맞게 내고 OCP를 import하지 않음 | Geom |
| V-AM-2 | 추천: 이름이 달라도 bbox·부피로 정답, 좌우 대칭 쌍 뒤바뀌지 않음, RENUM 있으면 `basis.renum` | Geom |
| V-AM-3 | 공칭 일치 → PASS(`dist_mm.max ≤ tol`), 좌우 바꿔 매칭 → FAIL `ASM_BOUNDARY_MISMATCH` | Geom |
| V-AM-4 | 쿠션 +10 mm 이동 → FAIL + `ASM_OFFSET_SUSPECT [10,0,0]`·`match_ratio_after ≥ 0.98`, m 단위(×0.001) → `ASM_UNIT_SUSPECT 0.001` | Geom |
| V-AM-5 | `ASM_SPLIT_FILES`·`ASM_SHARED_NODES`·`ASM_FILE_NOT_INCLUDED`·비TETRA4 PART·1:N 등각 합집합 PASS·1:N 비등각 FAIL | Geom |
| V-AM-6 | 동등성: pid = RENUM 구간인 합성 케이스에서 `--asm-match`와 `--renum-csv`의 tag_nodes·morph include·check.json 수치·cushion rad가 바이트 동일 | Geom |
| V-AM-7 | 쿠션 파일 이름 ≠ `mesh_include_name`(예 `cushion_v3.inc`, 제품 PART 동거): morph 후 바뀐 바이트 = 매칭 노드 좌표 필드뿐, 조립 사본에 `cushion_v3.inc`로 놓이고 다른 파일 바이트 동일 | Geom·Backend |
| V-AM-8 | API: rows 검증 422 각 사유, check 없이 confirm 409 `ASM_CHECK_REQUIRED`, 조립 파일 수정 후 confirm·DOE 409 `ASM_MATCH_STALE`, DOE(asm_match_id, RENUM·기준본 없음) 202, 둘 다 없으면 409 missing `ASM_MATCH`, 4B 409 | Backend |
| V-AM-9 | 워커 가짜 도구(`fake_paicad asm parts/check`)로 ASM_MATCH 작업·쌍 치환 argv·`prep.json inputs.asm_match`·`GEOM_PREP_STALE` | Backend |
| V-AM-10 | 기존 RENUM 세트 PREDICT·BATCH·DOE 회귀(argv 불변) | Backend |
| V-AM-11 | MCP 정적 시험: 새 API x-mcp, `ASM_MATCH` JOB_KINDS·SUMMARIES, 용어집 ko | Backend |
| V-AM-12 | 프런트: 표 렌더·드롭다운 회색 사유·"매칭 안 함" 제한·검사 후 판정·저장 단추 상태·DOE 사유 문구, 2560×1440 라이트 스냅숏 | Frontend |

---

## 9. 리스크

| 리스크 | 대응 |
|---|---|
| 대형 조립(수백 MB) 파싱 시간·메모리 | 직계 파일만, 노드는 필요한 pid만 좌표 보관(1차 스캔은 블록 머리·ID만), `timeout_s`, 진행 줄 |
| 쿠션 노드가 공용 노드 파일에 있는 조립(요소와 노드 파일 분리) | 1차 `ASM_SPLIT_FILES`로 차단 — 실제 조립 형태 확인 필요(§10 Q1) |
| CAD와 메시 원점·단위 불일치(SimLab 밖에서 만든 조립에서 흔함) | 감지·안내만(AM-5). 보정 허용 여부 §10 Q2 |
| 회전된 좌표계 | 감지 못 함 → `ASM_BOUNDARY_MISMATCH`로만 드러남 |
| `mesh_include_name` 이름 가정 코드 누락(FEM 검증·등가성 판정이 조립 사본에서 이름으로 찾음) | §6.4 전수 점검 + V-AM-7 |
| 추천 오매칭 | 확정은 사용자, 저장 전 검사 필수, 좌우 뒤바뀜은 거리로 FAIL |
| 0.05 mm가 다른 메셔(HyperMesh 직접 등)의 노드 좌표 정밀도보다 엄격 | 고정폭 7자리 기준 1 m 좌표 정밀도 ≈ 1e-4 mm로 충분. 실패 시 `geometry.defaults.tag` 조정(세트 옵션) |
| 쿠션 파일에 제품 노드가 섞이면 morph 쓰기 대상 파일이 커짐 | 좌표 필드만 바꾸므로 정확성 문제 없음, 크기·시간만 |

## 10. 미결 사항(사용자 확인)

| # | 질문 | 임시 결정 |
|---|---|---|
| Q1 | 실제 조립 폴더에서 쿠션 PART의 노드와 요소가 **한 파일**에 있는가(예: 노드 전체가 공용 `nodes.inc`)? | 한 파일 필수(`ASM_SPLIT_FILES`). 아니라면 다중 파일 쓰기(노드 파일·요소 파일 각각 좌표만 변경)로 확장 |
| Q2 | 원점·단위 차이가 감지되면 사용자가 "이 이동/배율 적용"으로 CAD 쪽을 보정해 진행하게 할까? | 안내만(GE Q1 유지), CAD 재내보내기 |
| Q3 | 릴리스: v0.2.8에 넣을지 v0.2.9로 둘지 | v0.2.9(paicad 0.13.0, migration 없음) |

## 변경 메모

(구현 중 계약과 달라지면 `AM-C1~`로 기록하고 Plan 확인.)
