# 계약: 쉘 형상 모핑(단계 4C, 판금 비드) — `paicad shell`

> Plan 2026-10-19. 기준선 `feat/r1-shell-docs` 13e68b8(paicad 0.7.0). 상위 계약은 [geometry-engine.md](geometry-engine.md)(이하 **GE**)이며, 이 문서가 정하지 않은 규칙(경로 약어 `S`·`P`·`R`·`D`, JSON 공통 규약, 쓰기·임시 파일·stdout 규약, 버전·독립성·커널 격리)은 GE 그대로다. 이 문서가 GE를 바꾸거나 더하는 규칙은 §2.3에 모았다(쉘 범위에서는 이 문서 우선). 결정 번호는 `SM-n`. GE §9 단계 표 "5 (선택) 쉘 형상"·GE §11.3은 이 문서(단계 4C)로 구체화된다.

## 0. 한 줄 요약

조립 폴더의 쉘 부품(예: TV `chassis_rear` 판금) 메시에서 **노드·요소 ID·연결·요소 수를 그대로 두고 `/NODE` 좌표만** 바꿔 비드(bead) 깊이·위치·폭 변경을 반영한다(솔리드 R1과 같은 원칙). 입력 CAD는 **중립면(mid-surface) STEP**, 쉘 노드는 모두 중립면 위에 있으므로 태깅은 솔리드 경계 태깅과 같다(내부 노드 없음). tie(`/INTER/TYPE2`)·`/RBE2`가 참조하는 노드는 **고정 노드**로 묶어 움직이지 않고, 주변 전이 영역에서 변위를 0으로 수렴시키며, 고정 노드를 움직여야 하는 값은 `SHELL_FIXED_REGION_VIOLATION`으로 스킵한다. 출력은 원본 include와 이름·형식이 같은 파일 사본(바뀐 `/NODE` 좌표 필드만 다름)이고 기존 m_3 조립을 재사용한다. CLI는 별도 하위명령 그룹 `paicad shell <verb>`.

---

## 1. 목적·범위

### 1.1 목적

1. 판금 쉘 부품의 비드 형상 파라미터를 Altair 없이 학습데이터·예측·최적화 입력으로 쓴다(GE §1.1과 같은 플랫폼 기능).
2. tie·RBE2·접촉 정의가 쉘 노드 ID를 참조하므로 번호를 바꾸지 않는다(R1). 체결부(tie·RBE2) 형상은 바꾸지 않는다.
3. 기존 파일 계약(`parameter_extracted.xml`, `run__N/{m_1,m_2,m_3}`, paramitem, `SKIPPED.json`)을 지켜 ②③⑤ 코드 변경을 없앤다.

### 1.2 범위(4C)

| 항목 | 범위 |
|---|---|
| 요소 | 쉘 `/SHELL`(4절점, n3=n4 퇴화 사각형은 삼각형 취급)·`/SH3N`(3절점)만. quad 위주 + tri 혼합 |
| 대상 부품 | Radioss `/PART`(part_id·제목) 단위. 중립면 STEP의 시트 바디 1개 = `/PART` 1개(§4.1 대응 규칙) |
| 입력 CAD | **중립면 STEP**(시트 바디: `TopoDS_Shell`/면 집합, AP203/214/242, XDE 이름) — 단일 파일 또는 `cad/parts/<TITLE>.step` |
| 파라미터 | 비드 **깊이(`BEAD_D`) > 위치(`BEAD_U`·`BEAD_V`) > 개수 > 폭(`BEAD_W`)** 우선순위(구현 순서). 깊이·위치·폭은 연속 파라미터, 개수는 위상 변화라 다중 baseline(GE §11.4)으로 — 이 문서는 인터페이스·매칭 규칙만(§7.2) |
| 위상 | 샘플 B-rep의 면·엣지·꼭짓점 수·인접 관계 = 공칭(위상 보존 면 재구성, GE §6.3 GE-C7) |
| 고정 | tie·RBE2(+ 기본 포함 RBE3·RBODY·BCS·타 part 공유 노드, §6.1) 노드 집합 고정 + 전이 영역 |
| 출력 | 쉘 part 노드가 들어 있는 조립 폴더 파일의 사본(같은 상대 경로·이름·형식, `/NODE` 좌표 필드만 다름). 노드가 바뀌지 않은 파일은 쓰지 않음 |
| 메시(가상 골든) | 평균 요소 길이 3 mm, quad 위주 + tri 일부(gmsh recombine, §9.1) |
| 플랫폼 | native 세트 `kind=shell`, ①-1·①-3 DOE·④ PREDICT(A)·PREDICT_BATCH(B)·⑤ 내장 최적화(B 경유). 3S 쉘 두께와 동시 사용 |

### 1.3 비범위

- 판재 **솔리드** STEP 입력(대향 면 쌍 → 중립면 추출) — 후속 옵션(§12 로드맵). 4C는 시트 바디가 아니면 `SHELL_BODY_NOT_SHEET`.
- 비드 개수의 단일 baseline 내 변경(위상 변화), 비드 길이·플랭크 각·필렛 반경 파라미터, 플랜지 높이·각도, 구멍·버링·엠보 문자, 열린 비드(판 가장자리까지 이어진 비드).
- 곡면 기준면 위 비드의 위치·폭 변경(깊이만 허용, §6.3).
- 한 param_set에서 **솔리드(쿠션) 형상 파라미터와 쉘 형상 파라미터 혼합** — 1차 비범위(§12 Q3). 쉘 형상 + 3S 쉘 두께 조합은 범위 포함.
- 재메시·renumber(GE와 같음). `/SHELL16`·`/TRIA`(2D)·두꺼운 쉘 등 다른 요소.
- altair 경로 적용(GE-11 원칙).

### 1.4 원칙

GE §1.4 전부(외부 명령은 워커만·`shell=False`, 설정에서만 경로·명령, SPDM·원본 읽기만, 산출물 AI 루트, `_backup` 이동, 한국어 사용자 문구, 플랫폼은 paicad·OCP import 금지)와 GE-1(R1)을 쉘에 그대로 적용한다. 기존 솔리드 경로(`paicad extract/tag/update/morph/check/run`)의 인자·출력·동작은 바꾸지 않는다(SM-2).

---

## 2. 용어·결정

### 2.1 용어

| 용어 | 뜻 |
|---|---|
| 중립면(mid-surface) | 판재 두께 중심면. 쉘 요소 노드가 놓이는 면. STEP에서는 두께 없는 시트 바디 |
| 쉘 component | 모핑 대상 `/PART` 1개(part_id·제목) = 중립면 STEP 시트 바디 1개 |
| 기준면(base face) | 비드를 둘러싼 판의 일반 면(비드 입구 루프를 내부 와이어로 가짐). 기본은 평면 |
| 비드(bead) | 기준면 위의 오목(deboss)·볼록(emboss) 영역. B-rep에서 **필렛으로 둘러싸인** 면 묶음: 상단 필렛 링(기준면↔플랭크) + 플랭크 + 하단 필렛 링(플랭크↔바닥) + 바닥. 닫힌 루프로 기준면에서 분리되어야 함 |
| 바닥(bottom) | 비드의 기준면과 평행(±`draft_max_deg`)한 면. 깊이 = 바닥↔기준면 거리 |
| 플랭크(flank) | 바닥과 기준면을 잇는 측벽(평면·원뿔·선직면), 기준면과 각 `min_flank_deg`(10°)~90° |
| 필렛 링 | 플랭크 양끝의 블렌드 면 열(원통·토러스·B-spline, 접선 연속). 반경은 변경하지 않음(재블렌드 시 유지) |
| 선형 비드 / 원형 비드 | 바닥 면 주축 비(PCA 장단축 비) ≥ 1.2 → 선형(축 = 장축), 미만 → 원형 |
| sense | `deboss`(기준면 법선 반대쪽으로 들어감) \| `emboss`(법선 쪽으로 나옴). 깊이는 항상 양수 크기 |
| 고정 노드 | 쉘 component 노드 중 tie·RBE2 등 다른 정의가 참조하는 노드(§6.1). 좌표 변경 금지 |
| 체결 영역 | 고정 노드와 그 전이 영역을 합친 메시 영역(나사 구멍 RBE2 스파이더, tie 접합 띠 등) |
| 전이 영역 | 고정 노드에서 메시 측지 거리 < `fixed.transition_mm`인 노드. 면내(접선) 변위를 0으로 수렴 |
| 형상 변경 면 / 경계 변경 면 | update 결과 surface가 바뀐 면 / surface는 같고 경계(와이어)만 바뀐 면(위치·폭 변경 시 기준면) |

### 2.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| SM-1 | R1을 쉘로 확장: 쉘 component의 노드·요소 ID·연결·요소 수 고정, `/NODE` 좌표만 변경, 출력은 원본과 같은 상대 경로·이름·형식의 파일 사본 → 기존 m_3 조립 재사용 + 사본 덮어쓰기 | tie·RBE2 유지, 사용자 확정 2026-10-19 |
| SM-2 | CLI = 별도 하위명령 그룹 `paicad shell {fixed-scan,extract,tag,update,morph,check,run,selftest}`(`--kind shell` 옵션 아님, §5.1) | 솔리드 CLI·스키마 동결(GE-C10) 보호, 필수 인자·보고 스키마가 다름 |
| SM-3 | 입력 CAD = 중립면 STEP 우선, 판재 솔리드 STEP은 후속 옵션 | 쉘 노드가 면 위에 바로 놓여 태깅이 솔리드 경계와 같음, 사용자 확정 |
| SM-4 | 파라미터 우선순위 깊이 > 위치 > 개수 > 폭. 위치는 절대 mm(`position_range_mm` 준용, 기준 = 가장 가까운 고정 엣지), 깊이·폭은 ±%(`range_ratio`) | 사용자 확정, GE §4.3·§6.2 위치형 규칙 준용 |
| SM-5 | tie·RBE2 영역 제외(고정): 조립 폴더 스캔으로 고정 노드 집합 → 모핑 Dirichlet 0 + 전이 영역 수렴, 고정 노드를 움직여야 하는 값은 `SHELL_FIXED_REGION_VIOLATION` 스킵, 비드가 고정 영역과 겹치면 extract 후보 경고 | 사용자 확정 |
| SM-6 | 쉘 품질 = warpage·skew·aspect·Jacobian(절대) + 최소 엣지 비·Δt 비(baseline 대비 상대, 0.8/0.8) + 반전, `relative_to_baseline` 판정 GE §6.5 준용 | 솔리드 Q8 결정과 같은 구조 |
| SM-7 | 비드 개수 = 다중 baseline(GE §11.4) 위상 변형 용도, **비드 단위 매칭**(한 비드의 D·U·V·W 행은 한 묶음) | 사용자 확정(개수는 위상 변화) |
| SM-8 | 개발 골든 = build123d 가상 판금(비드 여러 개·플랜지·체결 영역) + gmsh 쉘 메시(3 mm, quad 위주 + tri), 현장 = `paicad shell selftest` 수치 요약 | 실물 반출 불가(GE §9 단계 0과 같음) |
| SM-9 | 플랫폼 연동 최소: 엔진 `native` 그대로, 세트 형상 종류 `kind=shell`은 `native/prep.json`에 기록(DB migration 없음), 명령 키 `paicad_shell_*` 추가, job_type·step 키 불변 | GE-3·GE-11 원칙 |

### 2.3 GE에서 바뀌거나 더해지는 규칙(쉘 범위, 이 문서 우선)

| GE 규칙 | 쉘(`kind=shell`) |
|---|---|
| §1.3 쉘 형상 모핑 비범위·§11.3 단계 5(선택) | 단계 4C로 범위 포함(이 문서) |
| §4.1 component = `RENUM_INIT.csv` 행, 기준본 = `{mesh_include_name}` | component = `/PART`(part_id·제목), 기준 메시 = 조립 폴더 안 해당 part 요소·노드가 있는 파일들(RENUM csv·`{mesh_include_name}` 불필요) |
| §4.8 PASS 출력 = `--out-inc` 1파일 | PASS 출력 = `--out-files-dir` 아래 상대 경로 사본 n개(§4.9) |
| §4.9 options 절(솔리드) | 쉘 전용 스키마(§4.10, `kind:"shell"`). 솔리드 명령에 쉘 options를 주면 기존 모르는 키 거부(GE-C10) 그대로 |
| §5.2 쓰기 위치 = `--out-dir`·`--out-inc` | 쉘 check·run은 `--out-dir`·`--out-files-dir`. 그 밖 규약(덮어쓰기 금지·임시 폴더·stdout·결정성) 동일 |
| §6.4 내부 노드 탄성 해 | 내부 노드 없음. 면내 매핑 + 면내 평활화(§6.5) |
| §6.5 품질(tetra stretch·aspect) | 쉘 품질 지표(§6.6) |
| §6.5 실패 코드 표 | `SHELL_*` 코드·category `FIXED` 추가(§6.7) |
| §7.4 native 등록 시 `BASELINE_INC_MISSING`·`RENUM_CSV_MISSING` | 쉘 세트에는 적용하지 않음. 대신 바디↔`/PART` 대응·쉘 요소 여부를 NP_EXTRACT에서 검사 |
| §7.1 `geometry.defaults` | 쉘은 `geometry.shell_defaults`(§8.1). 솔리드 기본값 불변 |

---

## 3. 전체 흐름

```text
[param_set·DOE당 1회]                                          [샘플마다]
 중립면 STEP ─┬─ shell extract ─→ parameter_extracted.xml         values.json
 (시트 바디)  │   (--assem-dir) ─→ shell_features.json(parts·beads)     │
              │                   features/*.png, 고정 겹침 경고      ▼
 조립 폴더 ───┼─ shell fixed-scan ─→ shell_scan.json + fixed_nodes.npz ─→ shell update ─→ sample.brep, face_map.json, shell_update.json
              │   (--features의 parts)                    │  (고정 사전 검사)      │
              └─ shell tag ────────→ shell_tag.json + shell_tag_nodes.npz         ▼
                                                                  shell morph ─→ files/<rel>(후보), shell_morph.json
                                                                           │
                                                                           ▼
                                                                  shell check ─→ shell_check.json
                                                                           │ PASS일 때만
                                                                           ▼
                                                     --out-files-dir/<rel> ─→ m_3: 기존 조립 사본 + 같은 상대 경로 덮어쓰기 (+3S props apply)
```

| 플랫폼 기능 | native 솔리드(GE) | native 쉘(이 문서) |
|---|---|---|
| ①-1 추출 | `paicad extract` | `paicad shell extract`(`--assem-dir` 없음 → 대응·고정 경고는 DOE 준비 때) |
| ④ 세트 준비 `PARAM_SET_NATIVE` | NP_EXTRACT·NP_TAG | NP_EXTRACT = shell extract, NP_TAG = shell fixed-scan → shell tag(step 키 불변) |
| ④ PREDICT(A) | update·morph·check | shell update·morph·check, RAD_ASSEMBLE 뒤 사본 덮어쓰기 |
| ①-3 DOE·④ 일괄 | run마다 `paicad run` | run마다 `paicad shell run` |
| 다중 baseline(4B) | 리브 수 등 | 비드 개수(비드 단위 매칭, §7.2) |

---

## 4. 입출력 파일 계약

JSON 공통 규약은 GE §4 머리말과 같다(UTF-8·`schema_version`·mm·deg·`engine`·`engine_version`·`max_report_bytes`). 쉘 보고 JSON은 최상위에 `kind: "shell"`을 추가로 둔다. 쉘 JSON의 `schema_version`은 쉘 파일 형식별로 1부터 센다(GE §17.3 규칙 준용).

### 4.1 입력

| 파일 | 위치(쉘 세트) | 형식·규칙 |
|---|---|---|
| 중립면 STEP(단일) | `S/cad/<model>.step` | 시트 바디 ≥1(솔리드 바디가 있으면 `SHELL_BODY_NOT_SHEET`). 바디 이름 = XDE 라벨 |
| 중립면 STEP(부품별) | `S/cad/parts/<TITLE>.step` | 파일마다 시트 바디 1개, stem = `/PART` 제목 |
| 바디 대응 덮어쓰기(선택) | `S/cad/body_map.json` | GE §4.1과 같은 형식, 값 = `/PART` 제목 또는 `"PART:<part_id>"`(제목 중복 시) |
| 조립 폴더 | `S/radioss_assem/*.rad, *.inc` | 쉘 part의 `/PART`·`/SHELL`·`/SH3N`·`/NODE`와 고정 판정 대상(`/INTER/TYPE2`·`/RBE2`·`/RBE3`·`/RBODY`·`/BCS`·`/GRNOD`·`/SURF`). 읽기만 |
| 샘플 값 | `values.json`(GE §4.4 형식) | 키 = 쉘 피처 대표 이름 |
| 옵션 | `options.json`(§4.10) | 플랫폼 작성(사용값) |
| 판 두께(선택) | `--thickness` JSON `{"schema_version":1,"parts":{"<part_id>":t}}` | check 간섭용. 없으면 `/PROP/TYPE1` 공칭 두께. 3S로 그 part 두께가 샘플마다 바뀌면 플랫폼이 샘플 값으로 작성 |

바디↔component 대응 규칙: GE §4.1 1~4단계와 같되 대상 = 조립 폴더에서 `/SHELL`·`/SH3N` 요소를 가진 `/PART`의 제목. 남는 바디 → `GEOM_BODY_MAP_FAILED`. 쉘 part는 남아도 됨(모핑 대상 아님). 대응된 part가 쉘 외 요소를 가지면 `SHELL_UNSUPPORTED_ELEMENT`.

쉘 component 노드 집합 = 그 part의 `/SHELL`·`/SH3N` 요소가 참조하는 노드. `/NODE` 정의가 여러 파일에 흩어져 있어도 된다(파일별로 사본 출력, §4.9).

### 4.2 native 준비본 `native/`(쉘)

| 경로 | 생성 | 내용 |
|---|---|---|
| `native/prep.json` | 플랫폼 | GE §4.2 키 + `kind:"shell"`, `inputs.assem_digest`(조립 폴더 `*.rad`·`*.inc` 상대 경로·sha256 정렬 목록의 sha256), `fixed_digest`(= `shell_scan.json.fixed.digest`). `baseline_inc`·`renum_csv`는 `null`. `kind` 키가 없으면 `solid`(기존 준비본 호환) |
| `native/extract/parameter_extracted.xml` | `shell extract` | GE §4.3 형식 그대로(TX_PARSE 호환) |
| `native/extract/shell_features.json` | `shell extract` | §4.4 |
| `native/extract/features/<NAME>.png` | `shell extract` | 비드 면 주황, 고정 노드 파랑 점, 치수선 |
| `native/fixed/shell_scan.json`, `fixed_nodes.npz` | `shell fixed-scan` | §4.3 |
| `native/tag/shell_tag.json`, `shell_tag_nodes.npz` | `shell tag` | §4.6 |
| `native/options.json` | 플랫폼 | 준비에 쓴 `tag`·`fixed` 절 |

유효성: GE §4.2 규칙 + `assem_digest`가 현재 조립 폴더와 같고 `tag`·`fixed` 절 sha256이 같아야 READY, 아니면 `GEOM_PREP_STALE`.

### 4.3 fixed-scan 출력 `shell_scan.json`

```json
{
  "schema_version": 1, "kind": "shell", "engine": "native", "engine_version": "0.8.0",
  "status": "OK", "code": null, "message": null,
  "candidates": [
    {"part_id": 2001, "title": "CHASSIS_REAR", "n_shell": 41230, "n_sh3n": 1820, "n_other": 0, "nodes": 43011,
     "files": ["inc/chassis.inc"], "prop": {"id": 31, "type": 1, "thickness": 0.8}}
  ],
  "parts": [2001],
  "fixed": {
    "digest": "sha256:…", "total": 1320,
    "by_kind": {"INTER_TYPE2_SECONDARY": 410, "INTER_TYPE2_MAIN": 96, "RBE2": 640, "RBE3": 0, "RBODY": 0, "BCS": 0, "SHARED": 174},
    "refs": [
      {"kind": "INTER_TYPE2_SECONDARY", "id": 12, "title": "TIE_BRKT", "file": "inc/ties.inc", "nodes": 410, "dsearch_mm": 1.0},
      {"kind": "RBE2", "id": 501, "title": "SCREW_1", "file": "inc/rbe.inc", "nodes": 18, "independent": 900001}
    ],
    "clusters": [{"id": 1, "nodes": 18, "center": [102.0, 40.5, 0.0], "radius_mm": 4.1, "kinds": ["RBE2"]}]
  },
  "files": {"nodes": "fixed_nodes.npz"},
  "warnings": [{"code": "FIXED_SHARED_NODES", "part_id": 2001, "nodes": 174, "with_parts": [2002]}]
}
```

- `--parts`/`--features` 없이 실행하면 `candidates`만 채우고 `parts: []`, `fixed: null`(목록 모드 — 진단·UI 확인용). 있으면 그 part의 고정 집합 계산.
- `fixed_nodes.npz`(paicad만 읽음): `node_id:int64[n]`, `part:int32[n]`, `kind_mask:int16[n]`(비트 = `by_kind` 순서), `cluster:int32[n]`, `xyz:float64[n,3]`(기준 좌표).
- `clusters` = 고정 노드의 메시 연결 성분(extract 겹침 판정·PNG 표시용, 좌표는 수치 요약).

### 4.4 extract 출력 `shell_features.json`

`parameter_extracted.xml`은 GE §4.3 그대로(순서 = component(part 제목 정렬) → 피처 종류(D·U·V·W) → 비드 중심 사전순, 이름 = `<COMP>_<TYPE>_<k>`, `k`는 같은 component·종류 안 순번이 아니라 **비드 번호**(같은 비드의 D·U·V·W가 같은 k), NAME_RE·64자 규칙 GE-C1 동일). 피처 약어: `BEAD_D`(깊이)·`BEAD_U`·`BEAD_V`(위치)·`BEAD_W`(폭).

```json
{
  "schema_version": 1, "kind": "shell", "engine": "native", "engine_version": "0.8.0",
  "unit_system": "mm-ton-s",
  "cad": {"mode": "single", "files": [{"rel": "chassis_mid.step", "sha256": "…"}], "body_map": "xde"},
  "parts": [{"body": "CHASSIS_REAR", "part_id": 2001, "title": "CHASSIS_REAR", "faces": 64, "edges": 210, "vertices": 150, "area": 118000.0, "bbox": [0,0,0,400,300,15]}],
  "beads": [
    {"id": "CHASSIS_REAR_B1", "k": 1, "body": "CHASSIS_REAR", "shape": "linear", "sense": "deboss",
     "base_face": "F1", "bottom": ["F20"], "flanks": ["F16","F17","F18","F19"], "fillets_top": ["F8","F9","F10","F11"], "fillets_bottom": ["F12","F13","F14","F15"],
     "center": [120.0, 80.0, -2.0], "axis": [1, 0, 0], "normal": [0, 0, 1],
     "nominal": {"depth": 4.0, "width": 12.0, "length": 80.0, "flank_deg": 60.0},
     "fixed_overlap": "none", "fixed_clearance_mm": 22.4}
  ],
  "features": [
    {"name": "CHASSIS_REAR_BEAD_D_1", "type": "BEAD_DEPTH", "bead": "CHASSIS_REAR_B1", "body": "CHASSIS_REAR",
     "nominal": 4.0, "unit": "mm", "range": {"min": 3.8, "max": 4.2, "ratio": 0.05},
     "feasible": {"min": 1.2, "max": 6.9, "limited_by": "bottom_width", "source": "estimate"},
     "op": {"mode": "keep_angle"}, "measure": {"method": "bead_depth"}, "group": null, "use_default": true,
     "png": "features/CHASSIS_REAR_BEAD_D_1.png"},
    {"name": "CHASSIS_REAR_BEAD_U_1", "type": "BEAD_POS_U", "bead": "CHASSIS_REAR_B1", "body": "CHASSIS_REAR",
     "nominal": 35.0, "unit": "mm", "range": {"min": 30.0, "max": 40.0, "abs_mm": 5.0},
     "ref": {"rule": "nearest_fixed_edge", "edge": "E3", "axis": [1, 0, 0]},
     "feasible": {"min": 18.0, "max": 52.0, "limited_by": "fixed_region:1", "source": "estimate"},
     "measure": {"method": "bead_center"}, "group": null, "use_default": true}
  ],
  "groups": [],
  "fixed": {"available": true, "digest": "sha256:…", "transition_mm": 6.0},
  "warnings": [{"code": "BEAD_NEAR_FIXED", "feature": "CHASSIS_REAR_BEAD_W_3", "message": "bead region within transition zone of fixed cluster 2"}]
}
```

| 필드 | 규칙 |
|---|---|
| `range` | 깊이·폭 = 공칭 × (1 ∓ `extract.range_ratio`), 위치 = 공칭 ∓ `extract.position_range_mm`(절대 mm), 모두 `feasible`로 자름(GE §4.3 준용) |
| `fixed_overlap` | `inside`(비드 영역 = 비드 면 + 상단 필렛 바깥 경계에 고정 노드) → 경고 `BEAD_FIXED_OVERLAP`, 그 비드 피처 전부 `use_default:false`(깊이·폭 변경 시 항상 침범) \| `transition`(비드 영역이 전이 영역과 겹침) → 경고 `BEAD_NEAR_FIXED`, `use_default:true` \| `none` \| `unknown`(`--assem-dir` 없음, 경고 `FIXED_INFO_MISSING`) |
| `feasible` | 깊이: keep_angle에서 바닥 폭 ≥ 2×하단 필렛 반경 + 1 mm, 최소 깊이 ≥ 상·하단 필렛 반경 합으로 위상 유지. 위치: 입구 루프가 기준면 안·다른 피처와 `land_min_mm`(2 mm) 이상·고정 클러스터 전이 영역 밖. 폭: 입구 루프가 같은 조건, 바닥 폭 > 2×하단 필렛 반경. `limited_by`에 제한 원인(`fixed_region:<cluster>`·피처 이름·`bottom_width`·`base_boundary`) |
| `groups` | 대칭 그룹(GE §6.2 MIRROR 규칙을 비드 단위로, 그룹 구성원 = 같은 종류 피처). 기본 묶음·`symmetry_split` 동일 |
| `use_default` | 파라미터 표의 기본 `use` 값(플랫폼이 표 초기값으로 사용) |

### 4.5 values.json

GE §4.4와 같다. 키 = 쉘 피처 대표 이름(3S 두께 값은 기존대로 `props_values.json`에 따로).

### 4.6 tag 출력

`shell_tag.json`: GE §4.5 키 구조 + 아래 차이.

```json
{"schema_version": 1, "kind": "shell", "status": "OK", "code": null, "message": null,
 "tolerance": {"abs_mm": 0.05, "rel": 1.0e-4}, "match_ratio": 0.9991,
 "parts": [{"part_id": 2001, "body": "CHASSIS_REAR", "nodes": 43011, "elements": {"quad": 41230, "tri": 1820},
            "classified": {"vertex": 150, "edge": 3120, "face": 39701, "unmatched": 40},
            "fixed": 1320, "transition": 2210, "dist_mm": {"mean": 0.002, "max": 0.044}}],
 "files": {"nodes": "shell_tag_nodes.npz"}, "fixed_digest": "sha256:…", "warnings": []}
```

`shell_tag_nodes.npz`: GE §4.5 배열(`node_id`·`part`·`kind`(1 면·2 엣지·3 꼭짓점·-1 미일치, **0 없음**)·`entity`·`uv`·`dist`) + `fixed:bool[n]`, `geo_dist_fixed:float64[n]`(고정 집합까지 메시 측지 거리, 고정 = 0, 연결 없음 = inf).

### 4.7 update 출력(`--out-dir`)

`sample.brep`·`face_map.json`(항등, GE §4.6)·`paicad.log` + `shell_update.json`:

```json
{"schema_version": 1, "kind": "shell", "status": "OK", "code": null, "category": null, "message": null,
 "values": {"CHASSIS_REAR_BEAD_D_1": 4.2},
 "applied": [{"name": "CHASSIS_REAR_BEAD_D_1", "bead": "CHASSIS_REAR_B1", "nominal": 4.0, "value": 4.2, "delta": 0.2,
              "op": "BEAD_DEPTH", "mode": "keep_angle", "members": []}],
 "positions": [{"name": "CHASSIS_REAR_BEAD_U_1", "body": "CHASSIS_REAR", "axis": "U", "mode": "nearest_fixed_edge", "ref_edge": "E3", "expected_measured": 35.0}],
 "changed": {"CHASSIS_REAR": {"geometry": ["F12","F13","F14","F15","F16","F17","F18","F19","F20"], "boundary_only": [], "edges": ["E40","E41"], "vertices": []}},
 "fixed_precheck": {"status": "PASS", "violations": 0},
 "collisions": [],
 "topology": {"same_as_nominal": true, "counts": {"CHASSIS_REAR": {"nominal": [64,210,150], "sample": [64,210,150]}}},
 "elapsed_s": 1.1}
```

- `op` ∈ `BEAD_DEPTH`·`BEAD_TRANSLATE`·`BEAD_WIDTH`. `changed`는 morph가 면별 규칙(§6.5)을 고르는 입력(필수).
- `fixed_precheck`: `--fixed-dir`가 있을 때만 `PASS|FAIL`, 없으면 `NOT_EVALUATED`. FAIL이면 최상위 FAIL `SHELL_FIXED_REGION_VIOLATION`(category `FIXED`), `sample.brep` 없음.

### 4.8 morph 출력(`--out-dir`)

| 파일 | 내용 |
|---|---|
| `files/<rel>` | 쉘 노드가 바뀐 조립 폴더 파일마다 사본(`<rel>` = `--assem-dir` 기준 상대 경로, 원본과 바이트 동일하고 `/NODE` 좌표 필드만 다름, §4.11) |
| `shell_morph.json` | `{schema_version, kind, status, code, category, message, max_disp_mm, files:[{rel, sha256_in, sha256_out, moved_nodes}], parts:[{part_id, moved_nodes, max_disp_mm, fixed_max_disp_mm, faces:{uv_map:n, in_surface:n, unchanged:n}, solver:{method, iterations, rel_residual}}], elapsed_s}` |

`fixed_max_disp_mm`는 항상 0이어야 한다(고정 노드 Dirichlet, §6.5). 0이 아니면 `GEOM_INTERNAL`.

### 4.9 check 출력

| 파일 | 내용 |
|---|---|
| `shell_check.json`(`--out-dir`) | 아래 |
| `--out-files-dir/<rel>` | PASS일 때만 morph의 `files/<rel>`을 같은 상대 경로로 씀. FAIL이면 아무것도 쓰지 않음 |

```json
{"schema_version": 1, "kind": "shell", "status": "PASS", "code": null, "category": null, "message": null,
 "checks": {
   "fixed":        {"status": "PASS", "moved_fixed_nodes": 0, "max_mm": 0.0},
   "param":        {"status": "PASS", "items": [{"name": "CHASSIS_REAR_BEAD_D_1", "input": 4.2, "measured": 4.197, "err": 0.003, "tol": 0.05}]},
   "deviation":    {"status": "PASS", "max_mm": 0.011, "tol_mm": 0.05, "worst_node": 2004512},
   "quality":      {"status": "PASS", "inverted": 0, "max_warpage_deg": 6.1, "baseline_max_warpage_deg": 5.8, "max_skew_deg": 41.0, "baseline_max_skew_deg": 40.2,
                    "max_aspect": 3.4, "baseline_max_aspect": 3.3, "min_jacobian": 0.71, "baseline_min_jacobian": 0.72,
                    "min_edge_mm": 1.21, "baseline_min_edge_mm": 1.30, "edge_ratio": 0.93, "dt_ratio": 0.92, "baseline_status": "PASS"},
   "interference": {"status": "PASS", "max_penetration_mm": 0.0, "pairs": []},
   "tie":          {"status": "PASS", "interfaces": [{"id": 12, "dsearch_mm": 1.0, "max_gap_mm": 0.0, "failed_nodes": 0}]}
 },
 "warnings": [], "options": {"…": "사용값"},
 "out_files": ["inc/chassis.inc"], "elapsed_s": 3.2}
```

### 4.10 옵션 `options.json`(쉘)

```json
{
  "schema_version": 1, "kind": "shell",
  "tag":          {"tol_abs_mm": 0.05, "tol_rel": 1.0e-4, "min_match_ratio": 0.98},
  "fixed":        {"kinds": ["INTER_TYPE2", "RBE2", "RBE3", "RBODY", "BCS", "SHARED"], "required": true, "transition_mm": 6.0, "tol_mm": 0.001},
  "morph":        {"smoother": "elastic", "poisson": 0.3, "relax_iters": 3, "solver_rtol": 1.0e-8, "solver_maxiter": 5000},
  "quality":      {"max_warpage_deg": 15.0, "max_skew_deg": 60.0, "max_aspect": 5.0, "min_jacobian": 0.6,
                   "min_edge_ratio": 0.8, "dt_ratio_min": 0.8, "min_edge_mm": null, "relative_to_baseline": true},
  "deviation":    {"boundary_max_mm": 0.05, "param_abs_mm": 0.05, "param_rel": 0.01},
  "interference": {"product_mm": 0.05},
  "tie":          {"default_dsearch_mm": null, "required": true},
  "extract":      {"range_ratio": 0.05, "position_range_mm": 5.0, "draft_max_deg": 3.0, "min_flank_deg": 10.0, "min_depth_mm": 0.5, "land_min_mm": 2.0, "linear_aspect": 1.2},
  "bead":         {"depth_mode": "keep_angle", "position_ref": "nearest_fixed_edge"},
  "symmetry_split": []
}
```

- 범위: `fixed.kinds` ⊆ 위 6종이고 `INTER_TYPE2`·`RBE2` 필수 포함(사용자 확정 대상, 빼면 422), `transition_mm ≥ 0`(0 = 전이 없음), `tol_mm > 0`, `smoother ∈ {elastic, laplacian}`, `relax_iters` 0~50, 각도 기준 0~90(warpage 0~45), `max_aspect ≥ 1`, `0 < min_jacobian ≤ 1`, 비율 (0,1], `depth_mode ∈ {keep_angle, keep_bottom}`, `position_ref ∈ {nearest_fixed_edge, proportional}`. 모르는 키 거부(GE-C10 준용).
- 고급 옵션 UI에서 바꾸는 절 = `quality`·`deviation`·`interference`·`tie.required`·`fixed.transition_mm`·`extract.position_range_mm`·`bead`. `tag`·`fixed`(transition 제외) 변경은 준비본 재생성(STALE).
- 사용값 기록 위치·`engine`/`engine_version` 규칙은 GE §4.9와 같다.

### 4.11 include 쓰기(쉘)

GE §6.4-4의 고정폭 보존 규칙을 파일마다 그대로 적용한다: 바이트·줄 끝·인코딩 보존, `/NODE` 블록 데이터 줄의 X·Y·Z 필드만 같은 폭으로 다시 씀, 이동량 0 노드(고정 노드 포함) 줄은 원문 그대로, 그 밖 줄(`/SHELL`·`/SH3N`·`/PART`·`/PROP`·`/INTER`·`/RBE2` 등) 원문 그대로, 쓰기 후 다시 읽어 요소 수·ID·연결 불변 확인. 형식 보존 불가 → `GEOM_INC_FORMAT`. 쉘 노드가 하나도 안 바뀐 파일은 출력하지 않는다(무변경 샘플이면 `files: []`, check PASS + `out_files: []`).

---

## 5. CLI

### 5.1 결정: 하위명령 그룹 `paicad shell <verb>`(SM-2)

| 후보 | 판단 |
|---|---|
| 기존 명령 + `--kind shell` | 기각. ① 솔리드 명령의 필수 인자(`--baseline-inc`·`--renum-csv`)와 보고 스키마는 Verifier 판정으로 동결(GE-C10)됐는데 `--kind`가 들어가면 인자 필수 여부가 조건부가 되어 argparse 계약·V-GE 시험을 다시 써야 함 ② 같은 보고 파일 이름에 두 스키마가 섞여 플랫폼 `reports.py` 판정이 모호 ③ 쉘 변경이 솔리드 결과를 바꿀 위험(PATCH/MINOR 판단도 섞임) |
| **`paicad shell <verb>`** | **채택**. 솔리드 경로 무수정(GE-11 정신), 필수 인자를 argparse로 강제, 보고 파일 이름이 `shell_*.json`으로 분리되어 플랫폼이 이름으로 스키마 선택, 명령 키 `paicad_shell_*`로 기능 on/off(`/status`) 독립. 기존 그룹 명령(`props scan`·`props apply`) 선례와 같은 모양. 내부 모듈(mesh 읽기·쓰기·writer·kernel·tie 해석)은 공유 |

### 5.2 하위 명령

공통 규약은 GE §5.2(쓰기 위치만 §2.3 변경). 필수 **굵게**.

| 명령 | 인자 | 출력(성공 판정) |
|---|---|---|
| `paicad shell fixed-scan` | **`--assem-dir`**, **`--out-dir`**, `--parts`(콤마 part_id) 또는 `--features`(`shell_features.json`의 `parts`), `--options` | `shell_scan.json`(`status: OK`), 고정 계산 시 `fixed_nodes.npz` |
| `paicad shell extract` | **`--cad`**, **`--out-dir`**, `--assem-dir`(대응 검사·고정 겹침 경고, fixed-scan과 같은 모듈로 계산), `--body-map`, `--options`, `--no-png` | `parameter_extracted.xml` + `shell_features.json`(파라미터 ≥1) |
| `paicad shell tag` | **`--cad`**, **`--features`**, **`--assem-dir`**, **`--fixed-dir`**, **`--out-dir`**, `--body-map`, `--options` | `shell_tag.json`(`status: OK`) + `shell_tag_nodes.npz` |
| `paicad shell update` | **`--cad`**, **`--features`**, **`--values`**, **`--out-dir`**, `--fixed-dir`(고정 사전 검사), `--body-map`, `--options` | `shell_update.json`(`status: OK`) + `sample.brep` + `face_map.json` |
| `paicad shell morph` | **`--assem-dir`**, **`--tag-dir`**, **`--fixed-dir`**, **`--features`**, **`--update-dir`**, **`--out-dir`**, `--solver`(기본 `radioss`), `--options` | `shell_morph.json`(`status: OK`) + `files/` |
| `paicad shell morph --sweep` | morph 인자 + **`--sweep`**, `--steps`(깊이·폭 %, 기본 `5,10,20,30,40,50`), `--pos-steps`(mm, 기본 `1,2,3,5,8,10`), `--params`, `--stop-after-fail`(2), `--check on\|off`, `--keep-steps` | `envelope.json`·`envelope.csv`·`report_envelope.md`(§7.1) |
| `paicad shell check` | **`--assem-dir`**, **`--morph-dir`**, **`--update-dir`**, **`--tag-dir`**, **`--fixed-dir`**, **`--features`**, **`--values`**, **`--out-dir`**, **`--out-files-dir`**, `--thickness`, `--options` | `shell_check.json`(`status: PASS`) + `--out-files-dir` 사본 |
| `paicad shell run` | update·morph·check 인자 합집합 + **`--update-dir`**·**`--morph-dir`**·**`--check-dir`**·**`--out-files-dir`** | 각 단계 출력 + `shell_run.json`(`--check-dir`, 단계별 status·elapsed). 앞 단계 FAIL이면 중단(GE §5.3 run과 같음) |
| `paicad shell selftest` | **`--cad`**, **`--assem-dir`**, **`--out-dir`**, 선택 `--variant-cad`·`--variant-values`(현장 변경형 중립면 STEP과 그 값 — update 비교), `--envelope-*` | `selftest_report.json`·`.md`(수치 요약만, CAD·메시 본문·좌표 배열 없음, GE §5.3.1 준용) |

`paicad map`(4B)은 그대로 쓰되 입력 features가 `kind:"shell"`이면 §7.2 비드 단위 규칙을 적용한다.

### 5.3 종료코드

GE §5.4 표 그대로: 0 성공, 2 인자, 3 입력(`GEOM_INPUT_INVALID`·`GEOM_OUTPUT_EXISTS`·`SHELL_PART_NOT_FOUND`), 10 update FAIL(`SHELL_FIXED_REGION_VIOLATION` 사전 검사 포함), 11 morph·check FAIL, 12 준비 실패(tag·**fixed-scan**), 13 extract 결과 없음, 20 내부, 130 중단. 플랫폼 판정은 출력 파일 우선(GE §5.4).

---

## 6. 알고리즘 계약

허용오차·기본값은 §4.10. `tol = max(tol_abs_mm, tol_rel · L_body)`(GE §6과 같음).

### 6.1 fixed-scan(고정 노드 집합)

1. 조립 폴더 `*.rad`·`*.inc` 전체에서 `/PART`·`/SHELL`·`/SH3N`·`/NODE`와 아래 정의를 읽는다(파일 수집은 3S `props scan`과 같은 규칙, 고정폭·자유 형식 모두).
2. 집합 정의 해석: `/GRNOD/NODE`·`/GRNOD/PART`·`/GRNOD/GRNOD`(중첩), `/SURF/PART`·`/SURF/SEG`·`/SURF/SURF`. 그 밖 유형(`/GRNOD/BOX` 등)은 미지원 → 아래 7.
3. 대상 part 노드 집합 N에 대해 종류별 고정:
   - `INTER_TYPE2_SECONDARY`: `/INTER/TYPE2`의 secondary 노드 집합 ∩ N.
   - `INTER_TYPE2_MAIN`: main 면이 N의 요소 세그먼트를 포함하면, secondary 노드가 `Dsearch`(0·공백이면 `tie.default_dsearch_mm`, null이면 공칭 최대 투영 거리 × 1.5, GE §6.5(e)와 같음) 안으로 투영되는 세그먼트의 노드.
   - `RBE2`: 독립 노드·종속 노드(`/GRNOD`) ∩ N. `RBE3`·`RBODY`: 참조 노드 ∩ N. `BCS`: 경계조건 노드 집합 ∩ N.
   - `SHARED`: N 중 대상 part 밖 요소(다른 part의 `/SHELL`·`/SH3N`·`/BRICK`·`/TETRA4`·`/BEAM`·`/SPRING` 등)도 참조하는 노드 + 경고 `FIXED_SHARED_NODES`.
   - `fixed.kinds`에서 뺀 종류는 계산만 하고 고정하지 않음(경고 `FIXED_KIND_SKIPPED`, 수치는 보고).
4. 고정 집합 F = 활성 종류 합집합. `digest` = 정렬한 노드 ID 목록의 sha256. 클러스터 = F의 메시 인접 연결 성분.
5. 대상 part 요소 중 `/SHELL`·`/SH3N`이 아닌 것 → `SHELL_UNSUPPORTED_ELEMENT`. 지정 part 없음 → `SHELL_PART_NOT_FOUND`.
6. 결정성: 같은 입력 → 같은 `digest`.
7. 해석 실패(미지원 집합 유형, 참조 ID 없음, 형식 오류): `fixed.required=true`(기본) → `SHELL_FIXED_PARSE_FAILED`(종료 12, 메시지에 정의 종류·ID·파일), `false` → 그 정의만 건너뜀 + 경고 `FIXED_PARSE_SKIPPED`(고정 누락 위험 표시).

### 6.2 tag

GE §6.1 1~4를 쉘에 적용한다.

1. 대상 노드 = 쉘 component의 **모든** 노드(쉘은 외피·내부 구분 없음, `kind=0` 없음).
2. 노드마다 바디에 대해 꼭짓점 → 엣지 → 면 순으로 `tol` 이내 판정(GE §6.1-2). 엣지는 자유 엣지(판 외곽·구멍)와 면 사이 엣지(필렛 접선 경계 포함) 모두.
3. 일관성: 한 요소의 노드들이 공유 엣지 없는 서로 다른 면에 붙으면 공통 엣지로 재분류 시도(GE §6.1-3). 메시가 필렛 접선 엣지를 따르지 않는(요소가 엣지를 가로지르는) 비율이 엣지별 50%를 넘으면 경고 `TAG_EDGE_NOT_RESPECTED`(실패 아님 — 노드별 면 매핑으로 처리, 품질 위험).
4. `match_ratio < min_match_ratio` → `GEOM_BASELINE_MISMATCH`(메시지에 "메시가 중립면 위에 있지 않습니다 — 오프셋 쉘·외피 메시인지 확인"). 미일치 노드는 자유(§6.5에서 이웃 보간).
5. `--fixed-dir`의 F를 노드 배열에 표시하고, 측지 거리 `geo_dist_fixed`를 메시 엣지 길이 가중 Dijkstra로 계산(전이 영역 판정용). `shell_tag.json.fixed_digest` ≠ 준비본 `fixed_digest`이면 `GEOM_INPUT_INVALID`.

실패 코드: `GEOM_BODY_MAP_FAILED`, `SHELL_UNSUPPORTED_ELEMENT`, `GEOM_BASELINE_MISMATCH`, `GEOM_TAG_FAILED`.

### 6.3 extract(비드 인식)

1. 바디가 시트(면 집합, 닫힌 솔리드 아님)인지 확인 → 아니면 `SHELL_BODY_NOT_SHEET`.
2. 면 인접 그래프(커널 `face adjacency`)를 만든다. 엣지마다 공유 면 수(1 = 자유 엣지)와 이면각·접선 연속 여부를 기록.
3. **기준면 후보**: 평면 면 중 내부 와이어를 가진 면. 내부 와이어가 자유 엣지로만 되어 있으면 구멍(비드 아님, 피처 없음), 이웃 면과 공유된 엣지면 비드 후보 루프.
4. **비드 판정**(루프 안쪽 면 묶음 R, 루프에서 바깥으로 넘지 않는 연결 성분):
   - R의 첫 링 = 루프와 접한 면들이 모두 블렌드(원통·토러스·B-spline, 루프 엣지에서 접선 연속) → 상단 필렛 링.
   - 다음 링 = 플랭크(평면·원뿔·선직면, 기준면과 각 ∈ [`min_flank_deg`, 90°]) → 하단 필렛 링(블렌드) → 바닥(평면, 기준면과 평행 ±`draft_max_deg`, 정확히 1면).
   - 깊이 = 바닥 ↔ 기준면 거리 ≥ `min_depth_mm`. sense = (바닥 중심 − 기준면)·기준면 법선 부호.
   - 바닥이 여러 면·비평행, 플랭크 각 범위 밖, R 안에 구멍·다른 비드(중첩) → 경고 `BEAD_IRREGULAR`(피처 없음). 루프가 닫히지 않음(판 가장자리 도달) → `BEAD_OPEN_UNSUPPORTED`.
   - 선형/원형: 바닥 면 PCA 장단축 비 ≥ `linear_aspect`(1.2) → 선형(축 = 장축), 아니면 원형.
5. 파라미터 정의(비드마다):

| 종류 | 값 정의 | 변경 연산(update) | 재측정(check) |
|---|---|---|---|
| `BEAD_DEPTH`(`BEAD_D`) | 바닥 면 ↔ 기준면 거리(중립면 기준) | 바닥 면을 기준면 법선 방향으로 Δ 이동(sense 쪽이 +). `keep_angle`(기본): 플랭크는 자기 surface 위에서 연장·재트림, 입구 루프·상단 필렛 불변, 바닥 크기 변화. `keep_bottom`: 바닥 크기 유지, 플랭크 선직면 재구성(각 변화). 필렛 반경 유지 재블렌드 | 바닥 노드 평균 평면 ↔ 기준면 노드(입구 루프 바깥 링 2요소 폭, 전이·고정 제외) 평면 거리 |
| `BEAD_POS_U`·`BEAD_POS_V`(`BEAD_U`·`BEAD_V`) | 비드 중심(바닥 면 중심을 기준면에 투영)에서 축 방향으로 **가장 가까운 고정 엣지**까지 거리. 고정 엣지 = 기준면 외곽 와이어·구멍·플랜지 굽힘 경계 중 그 샘플에서 변하지 않는 직선 엣지로 축과 수직(±10°), 동률이면 긴 엣지. 축 U = 선형 비드 장축의 기준면 투영(원형은 기준면에 투영 길이가 가장 큰 전역 축, x→y→z 순), V = 법선 × U | 비드 전체(R 전체 + 입구 루프)를 기준면 안에서 축 방향 Δ 평행 이동. 기준면은 경계 변경 면 | 바닥 노드 중심의 기준면 투영 ↔ 기준 엣지 거리, 비교 = `shell_update.json.positions[].expected_measured` |
| `BEAD_WIDTH`(`BEAD_W`) | 깊이 절반 높이에서 대향 플랭크 사이 거리(선형 = 축 수직 방향, 원형 = 지름) | 플랭크를 면내에서 바깥(+)/안쪽으로 Δ/2씩 대칭 이동(깊이·플랭크 각 유지), 선형 비드 끝단 블렌드 반경은 Δ/2만큼 변경, 바닥·입구 루프·필렛 재구성 | 깊이 절반 평면과 플랭크 노드 교선 사이 거리(최소제곱) |

   - 기준면이 평면이 아니면 그 비드는 `BEAD_D`만 만들고 경고 `BEAD_POS_UNSUPPORTED`(위치·폭 없음).
   - `position_ref: proportional`(대안): 기준면 bbox 길이 비례 위치(GE §6.2 준용).
6. **고정 영역 겹침**(`--assem-dir`가 있을 때): §6.1과 같은 모듈로 F를 구하고, 비드 영역(R + 상단 필렛 바깥 경계)까지 노드 거리 ≤ `tol` → `inside`, ≤ `fixed.transition_mm` → `transition`(§4.4 `fixed_overlap`). `feasible` 추정은 위치·폭이 전이 영역에 닿기 전까지로 자른다.
7. 피처 0개 → `GEOM_EXTRACT_EMPTY`.

### 6.4 update

1. 매 샘플 공칭에서 시작, 비드별로 D → W → U/V 순서로 적용(같은 비드의 깊이·폭을 먼저 정하고 마지막에 이동). 위상 보존 면 재구성(GE §6.3 GE-C7과 같은 방식, `face_map` 항등), |Δ| ≤ 1e-6 mm는 0.
2. 충돌 사전 검사(GE §6.3-4 준용): 변경 후 입구 루프(바깥으로 `land_min_mm` 여유)가 다른 비드 루프·구멍·기준면 외곽·플랜지 굽힘 경계와 겹침, 바닥 폭 ≤ 2×하단 필렛 반경, 깊이 < 필렛 반경 합 → `GEOM_FEATURE_COLLISION`(category `CAD_FAILED`, 종료 10).
3. **고정 사전 검사**(`--fixed-dir`가 있을 때): 고정 노드 중 (a) 공칭에서 형상 변경 대상 면(이번 샘플 `changed.geometry`) 위에 있거나 (b) 이동·확장 후 비드 영역(샘플 R + 입구 루프)에 들어가는 노드가 있으면 `SHELL_FIXED_REGION_VIOLATION`(category `FIXED`, 종료 10, message에 피처 이름·클러스터 id·노드 수). 경계 변경 면(기준면)의 고정 노드는 그 면 surface가 그대로이므로 위반 아님.
4. 결과 검사: `BRepCheck_Analyzer` 유효, 바디마다 시트 1개, 면·엣지·꼭짓점 수·자유 엣지 수 = 공칭 → 위반 `GEOM_TOPOLOGY_CHANGED`, 예외 `GEOM_CAD_FAILED`.
5. `changed`: surface가 바뀐 면(`geometry`), surface 같고 와이어만 바뀐 면(`boundary_only`), 바뀐 엣지·꼭짓점을 기록.

### 6.5 morph

입력: tag(노드 분류·F·측지 거리), update(`sample.brep`·`changed`), 조립 폴더. 노드 변위 d를 면 단위로 정한다(쉘은 내부 해 없음).

1. **고정 노드**(F): d = 0(Dirichlet). 목표 위치(아래 2)가 기준 좌표와 `fixed.tol_mm` 넘게 다르면 → `SHELL_FIXED_REGION_VIOLATION`(category `FIXED`, 종료 11). 사전 검사(§6.4-3)를 통과해도 메시 기준 최종 판정은 여기.
2. **목표 위치**(고정 아님):
   - 꼭짓점·엣지 노드: 대응 샘플 꼭짓점·엣지의 같은 정규화 `t`(GE §6.4-1). 변하지 않은 엣지 → d = 0.
   - **변경 없는 면**(형상·경계 모두 불변): d = 0.
   - **형상 변경 면**(`changed.geometry`): (u,v) 정규화 매핑(GE §6.4-1 면 규칙). 평가점이 면 밖이거나 투영 실패면 아래 면내 해 규칙으로 대체.
   - **경계 변경 면**(`changed.boundary_only`, 위치·폭 변경 때 기준면): **면내 해** — 그 면의 메시 패치에서 면 경계 노드(엣지·꼭짓점 목표), 고정 노드(0), 패치 외곽에서 경계 변경이 없는 엣지 노드(0)를 Dirichlet로 두고 면내 2D 문제를 푼 뒤 샘플 면에 투영. `smoother=elastic`(기본): 국소 평면 좌표(평면 = 그 평면, 곡면 = 면 중심 계량으로 스케일한 uv)에서 평면 응력 선형 탄성, 삼각형 CST / 사각형 Q4, 요소 강성 `E_e = E0·Ā/A_e`(작은 요소일수록 단단, GE §6.4-2와 같은 취지), `ν = morph.poisson`. `laplacian`: cotangent 가중 조화 보간. 해법·재시도·실패 → GE §6.4-2와 같음(`GEOM_MORPH_FAILED`).
   - 미일치 노드: 이웃 노드 변위의 면내 해(자유 노드) 후 가장 가까운 샘플 면에 투영.
3. **전이 영역**: 변경 없는 면·경계 변경 면의 노드 중 `0 < geo_dist_fixed < transition_mm`인 노드는 접선 변위에 `s(r) = 3r² − 2r³`(r = geo_dist_fixed / transition_mm)를 곱한다(면 위 유지, 투영 재실시). 형상 변경 면 노드는 형상 정확도를 위해 감쇠하지 않는다(그 대신 §6.4-3·§6.5-1이 침범을 막고, 급구배는 품질 검사가 잡는다).
4. **면내 평활화**: 형상 변경 면 노드에 접선 Laplacian 이완 `relax_iters`회(가중 0.5, 매회 샘플 면 재투영, 엣지·꼭짓점·고정·전이 노드 제외). 0이면 생략.
5. 좌표 = 기준 + d. 쉘 component 밖 노드 불변. 쓰기 = §4.11.

### 6.6 check

입력: 조립 폴더, morph 결과, 샘플 B-rep, features, values, tag, F. 모든 항목 평가 후 `shell_check.json`.

| 항목 | 방법 | 기본 기준 | 실패 코드 |
|---|---|---|---|
| (f) 고정 | 고정 노드 출력 좌표 = 기준 좌표(줄 바이트 동일) | 이동 0 | `SHELL_FIXED_REGION_VIOLATION` |
| (a) 재측정 | §6.3 표 `measure`(모핑 메시 노드). 위치 = `expected_measured` 비교 | `\|측정−기대\| ≤ max(param_abs_mm, param_rel·\|기대\|)` | `GEOM_PARAM_MISMATCH` |
| (b) 경계 편차 | 분류 노드(kind 1~3) ↔ 대응 샘플 엔티티 최대 거리 | ≤ `boundary_max_mm`(0.05) | `GEOM_DEVIATION` |
| (c) 품질 | 아래 정의, component별 | 반전 0, warpage ≤ 15°, skew ≤ 60°, aspect ≤ 5, Jacobian ≥ 0.6, `edge_ratio ≥ 0.8`, `dt_ratio ≥ 0.8`, (`min_edge_mm` 지정 시 추가 하한). `relative_to_baseline=true`면 baseline이 이미 절대 기준 밖인 요소는 "나빠지지 않음"(warpage ≤ 기준본+2°, skew ≤ 1.1×, aspect ≤ 1.1×, Jacobian ≥ 0.9×)으로 판정 | `GEOM_QUALITY` |
| (d) 간섭 | 이동 노드(\|d\| > tol)만: 다른 part 외피(쉘 중립면 ± t/2, 솔리드 외피)와 간격 < (t_self + t_other)/2 − `product_mm`이고 baseline에서 같은 노드가 그렇지 않았던 경우. 두께 = `--thickness` 또는 `/PROP/TYPE1`. 수집 범위 = 쉘 part bbox + 10 mm, KD-tree(GE §6.5 수집 규칙) | 새 관통 없음 | `GEOM_INTERFERENCE` |
| (e) tie | GE §6.5(e) 그대로(쉘 노드가 secondary·main인 `/INTER/TYPE2`). 고정 덕분에 원래 통과해야 함 — 안전 확인. 대상 0건이면 `SKIPPED` | 투영 실패 0 | `GEOM_TIE_PROJECTION` |

품질 정의(요소 국소 평면 기준, HyperMesh 2D 관례에 맞춤 — §12 Q2):

| 지표 | 정의 |
|---|---|
| warpage | 사각형을 두 대각선으로 각각 나눈 두 삼각형 법선 사이 각 중 큰 값(deg). 삼각형 0 |
| skew | 사각형: 90° − (대변 중점을 잇는 두 선 사이 최소각). 삼각형: 각 꼭짓점→대변 중점 벡터와 나머지 두 변 중점을 잇는 벡터 사이 각의 90° 편차 최댓값 |
| aspect | 최장 엣지 / 최단 엣지(사각형·삼각형) |
| Jacobian | 사각형: 네 모서리 det J의 최솟값 / 중심 det J(국소 평면 이중선형 사상). 삼각형 1.0 |
| 반전 | 요소 법선이 baseline 같은 요소 법선과 반대(내적 ≤ 0) 또는 사각형 det J ≤ 0 |
| `edge_ratio` | component 최소 엣지 / baseline 최소 엣지 |
| `dt_ratio` | 쉘 특성 길이 h(사각형 = 면적 / 최장(엣지·대각선), 삼각형 = 2·면적 / 최장 엣지)의 component 최솟값 비(모핑 / baseline). Δt ∝ h(재료 불변) |

- baseline 평가: 공칭 메시를 같은 기준으로 평가해 `baseline_status`(절대 기준 warpage·skew·aspect·Jacobian 미달일 때만 FAIL) → 경고 `BASELINE_QUALITY_BELOW`(비차단, GE §6.5와 같음, 완화는 사용자 선택).
- 비유한 지표 처리·`NOT_EVALUATED` 규칙은 GE §4.8과 같다.
- 최상위 `code` 우선순위: `FIXED` → `INTERFERENCE` → `QUALITY` → `DEVIATION`(`GEOM_DEVIATION` → `GEOM_PARAM_MISMATCH`) → `TIE`.

### 6.7 실패·경고 코드(추가분 — 그 밖은 GE §6.5 표 그대로 사용)

| code | category | 플랫폼 표시 문구(한국어 매핑) | 발생 | 종료코드 |
|---|---|---|---|---|
| `SHELL_FIXED_REGION_VIOLATION` | `FIXED` | 고정 영역(tie·RBE2) 침범 | update 사전 검사·morph·check (f) | 10 / 11 |
| `SHELL_FIXED_PARSE_FAILED` | `PREP` | 고정 정의(tie·RBE2) 해석 실패 | fixed-scan·extract | 12 |
| `SHELL_UNSUPPORTED_ELEMENT` | `PREP` | 쉘(/SHELL·/SH3N)이 아닌 요소 | fixed-scan·tag | 12 |
| `SHELL_BODY_NOT_SHEET` | `PREP` | 중립면(시트) STEP이 아님 — 판재 솔리드는 후속 지원 | extract·tag | 12 |
| `SHELL_PART_NOT_FOUND` | `INPUT` | 지정한 쉘 PART를 찾지 못함 | fixed-scan | 3 |

재사용 코드: `GEOM_CAD_FAILED`·`GEOM_TOPOLOGY_CHANGED`·`GEOM_FEATURE_COLLISION`(update), `GEOM_MORPH_FAILED`·`GEOM_INC_FORMAT`(morph), `GEOM_QUALITY`·`GEOM_DEVIATION`·`GEOM_PARAM_MISMATCH`·`GEOM_INTERFERENCE`·`GEOM_TIE_PROJECTION`(check), `GEOM_BODY_MAP_FAILED`·`GEOM_BASELINE_MISMATCH`·`GEOM_TAG_FAILED`·`GEOM_EXTRACT_EMPTY`(준비), `GEOM_INPUT_INVALID`·`GEOM_OUTPUT_EXISTS`·`GEOM_INTERNAL`.

경고(실패 아님): `BEAD_FIXED_OVERLAP`·`BEAD_NEAR_FIXED`·`BEAD_IRREGULAR`·`BEAD_OPEN_UNSUPPORTED`·`BEAD_POS_UNSUPPORTED`·`FIXED_INFO_MISSING`·`FIXED_SHARED_NODES`·`FIXED_KIND_SKIPPED`·`FIXED_PARSE_SKIPPED`·`TAG_EDGE_NOT_RESPECTED`·`TAG_UNMATCHED`·`BASELINE_QUALITY_BELOW`. category `FIXED`는 화면·DOE에서 "고정 영역 침범"으로 묶는다.

---

## 7. envelope · 다중 baseline(개수)

### 7.1 envelope(모핑 한계)

GE §11.2를 그대로 따른다(1D 스윕, 각 단계 update→morph→check, `envelope.json`·csv `schema_version` 2 행 구조, `feasible`에 `source: envelope` 반영, 범위 초과는 UI 경고만).

| 파라미터 | 단계 단위 | 기본 단계 |
|---|---|---|
| `BEAD_D` 깊이 | `%`(행에 `delta_mm` 선택 키 추가 — 깊이 mm 변화량) | ±5·10·20·30·40·50 % |
| `BEAD_U`·`BEAD_V` 위치 | `mm` | ±1·2·3·5·8·10 mm |
| `BEAD_W` 폭 | `%` | ±5·10·20·30·40·50 % |

첫 실패가 `SHELL_FIXED_REGION_VIOLATION`이면 요약에 `limited_by: "fixed"`를 남겨(선택 키) 체결 영역이 한계를 정했음을 보인다. 가상 판금 envelope 보고서는 `packages/paicad/tests/golden/geometry/SM1/`(GE §11.2 G1과 같은 재생성·바이트 동일 규칙).

### 7.2 비드 개수 — 다중 baseline 매칭(인터페이스·규칙만)

- **구조**: GE §4.10·§7.3.8·§11.4 그대로, `usage: "topology"`. baseline마다 중립면 STEP + 그 비드 개수의 쉘 메시가 든 조립 폴더(tie·RBE2 정의도 그 메시 기준으로 사용자가 준비) + `native/{extract,fixed,tag}`. 범주형 `baseline`이 개수 수준을 대표한다(연속 `BEAD_N` 변수 없음, `baseline.json.nominal`에 정보용 `"<COMP>_BEAD_COUNT"`).
- **비드 단위 매칭**: `paicad map`은 features `kind:"shell"`이면 매칭 단위를 **비드**로 한다. 비드 a(baseline 1)·b(baseline 2) 쌍마다:
  - 하드 게이트: 같은 component(part 제목), 같은 `shape`(linear/circular)·`sense`, 기준면 법선 각 ≤ `axis_deg`(10°), 선형이면 축 각 ≤ 10°(방향 무관, 0°/180° 동일).
  - 점수 `S = w_pos·S_pos + w_dim·S_dim + w_ori·S_ori + w_nbr·S_nbr`(가중치·σ·등급 경계는 GE §11.4 기본값·`map` 옵션 그대로): `S_pos` = component bbox 정규화 비드 중심 거리의 `exp(-(d/σ)²)`, `S_dim` = 깊이·폭·길이 각각 GE 식의 평균, `S_ori` = 축(원형은 기준면 법선) 각, `S_nbr` = 반경 2×폭 안 이웃(다른 비드·구멍·고정 클러스터) 종류 다중집합 Jaccard.
  - baseline 쌍마다 헝가리안 할당, 등급 `recommend`/`check`/`unmatched`(판정 아님, 사용자 확정 필수 — GE §4.10 그대로).
- **행 묶음**: 한 비드의 `BEAD_D`·`BEAD_U`·`BEAD_V`·`BEAD_W` 행은 `common[].group = "bead:<row-group>"`(선택 키, `schema_version` 불변)으로 묶고, 같은 group 행의 `decision.map`은 같은 비드 대응이어야 한다(불일치 → PUT 422 `GEOM_INPUT_INVALID`). UI의 수락·변경·분리는 group 단위로 적용.
- 비드가 적은 baseline에서 대응 없는 비드의 행 = N/A(결측 지시 열 + 0 대체, GE §7.3.8). 대칭 그룹은 그룹 단위 매칭(GE §11.4).
- 4C 범위에서 구현하는 것은 이 규칙의 `paicad map` 확장과 합성 시험(§9 4C-3)이다. 플랫폼 4B 경로는 변경 없음.

---

## 8. 플랫폼 연동 최소안

### 8.1 설정·명령

- `geometry.shell_defaults`: §4.10 기본값(절 없으면 코드 기본값 = §4.10 예시). 솔리드 `geometry.defaults` 불변.
- `geometry.timeout_s`에 `shell_*` 키 추가(없으면 같은 이름 솔리드 값).
- `commands` 추가(모두 `required=False`, argv[0] = `{paicad}`, V-GE-1 적용): `paicad_shell_fixed_scan`·`paicad_shell_extract`·`paicad_shell_tag`·`paicad_shell_update`·`paicad_shell_morph`·`paicad_shell_check`·`paicad_shell_run`. 새 placeholder: `fixed_dir`, `out_files_dir`, `thickness_json`(선택 쌍 — 값 없으면 `"--thickness","{thickness_json}"` 쌍 생략, GE §7.3.1 `{renum_csv}` 규칙과 같은 방식). 그 밖 placeholder는 GE §7.1 이름 재사용.
- `/status`: `features.geometry_native_shell` = `paicad_shell_update`·`_morph`·`_check`(또는 `_run`) 비null + 실행 파일 존재.

### 8.2 job step(키 불변, `kind` 분기)

- 세트 kind: 등록 요청 `kind: "solid"|"shell"`(기본 `solid`) → `native/prep.json.kind`. DB 열 추가 없음(migration 없음). 세트 상세 API 응답에 `native.kind`(prep.json에서 읽음).
- `PARAM_SET_NATIVE`(kind=shell): NP_PREP(조립 폴더·CAD 복사, `BASELINE_INC_MISSING`·`RENUM_CSV_MISSING` 검사 생략) → NP_EXTRACT(`paicad_shell_extract --assem-dir`) → NP_TAG(`paicad_shell_fixed_scan --features` → `paicad_shell_tag`) → BL_MAP(다중일 때만) → NP_REGISTER. 등록 검증(`validate_folder` native shell): §4.2 파일 존재(`NATIVE_PREP_MISSING`), 파라미터 이름 집합 = features 대표 이름 집합.
- ①-1 `TD_EXTRACT_PARAMS`(params `kind:"shell"`): `paicad_shell_extract`(조립 폴더 없음 → `fixed_overlap: unknown`). ①-3 DG_PREP·HST_GEN_RADIOSS: tag 자리에서 fixed-scan → tag(조립 폴더 사본 `A` 기준), 이때 extract 경고를 다시 계산할 필요는 없음(DOE 결과 run 표에 `FIXED` category로 드러남).
- PREDICT(A): TPL_RENDER(values.json) → GEOM_UPDATE(`paicad_shell_update --fixed-dir S/native/fixed`) → MESH(`paicad_shell_morph` → `paicad_shell_check`, `{out_files_dir}`=`P/geom/shell_files`) → RAD_ASSEMBLE(아래 8.3).
- 일괄·DOE run(GE §7.3.6): `R/m_1/{values.json, native_params.xml, update/}`, `R/m_2/{morph/, check/, shell_files/<rel>}`, `R/m_3`(8.3), 실패 `R/SKIPPED.json`(`step` 동일, `report:"m_2/check/shell_check.json"`). `paicad_shell_run`이 있으면 1회, 없으면 순차.

### 8.3 m_3 조립 재사용

1. 조립 사본 생성은 기존 경로 그대로(쉘 형상만 있는 세트는 3S 두께만 세트와 같은 "조립 폴더 사본" 경로, 솔리드 기준본 교체 없음).
2. PASS 출력 `shell_files/<rel>`을 사본의 같은 상대 경로에 덮어쓴다(3S `geometry_props` overlay와 같은 방식, 원본·SPDM 불변).
3. 3S 쉘 두께가 있으면 그 뒤에 `props apply`(쉘 overlay가 반영된 사본 기준). 쉘 모핑은 `/NODE` 필드만, 3S는 `/PROP` 두께 필드만 바꾸므로 같은 파일이어도 순차 적용으로 합쳐진다.

### 8.4 3S 쉘 두께와 동시 사용

- 파라미터 표 = 쉘 피처(`source = shell`) + PROP 행(`source = prop`) 병합(GE §11.1 규칙), XML 호환 유지. 두께만·형상만·둘 다 모두 허용.
- 모핑 대상 part의 PROP이 3S 파라미터이면 플랫폼이 샘플 두께로 `--thickness` JSON을 써서 check (d) 간섭에 반영.
- 실패 우선: 쉘 형상 check FAIL이면 props apply를 하지 않음(run 스킵, 코드 = 쉘 코드).

### 8.5 UI 변경 최소

| 위치 | 변경 |
|---|---|
| ④ 세트 등록·①-1 | native 선택 시 "대상" 2단 [쿠션 솔리드 \| 쉘 판금(비드)](기본 솔리드, `geometry_native_shell=false`면 비활성+사유). 쉘: CAD 후보 = 중립면 STEP, 안내 "중립면 STEP 바디 이름 = Radioss PART 제목" |
| ④ 세트 상세 피처 표 | 기존 표 재사용: 종류(비드 깊이·위치 U/V·폭), 고정 겹침 배지(`BEAD_FIXED_OVERLAP` "체결 영역과 겹침 — 기본 사용 안 함", `BEAD_NEAR_FIXED`), PNG(비드 주황·고정 노드 파랑) |
| 검사 기준(고급) 접힘 | kind=shell이면 품질 칸이 warpage·skew·aspect·Jacobian·엣지 비·Δt 비, + 전이 폭(mm)·깊이 변경 방식(`keep_angle`/`keep_bottom`)·위치 기준 |
| 일괄·DOE 결과 표 | category 배지에 "고정 영역 침범"(`FIXED`) 추가 |

새 화면 없음. 다중 baseline 매칭표는 group 단위 동작만 추가(§7.2).

가시화(3D 보기·파라미터 미리보기, `paicad shell view`) → [geometry-view.md](geometry-view.md).

### 8.6 엔진 분리·버전

엔진은 `native` 그대로(혼용 규칙 GE §7.7). 같은 데이터셋에 solid·shell 세트 run이 섞이는 경우는 세트가 달라 발생하지 않는다(데이터셋 = DOE 1개). `engine_version` 기록 GE §17.3 그대로.

---

## 9. 단계별 산출물·완료 기준

### 9.1 개발 환경 가상 골든(SM-8)

- 생성 스크립트 `packages/paicad/tests/data/make_synthetic_shell.py`(저장소에 STEP·메시 파일 없음, build123d·gmsh는 `test` extra — GE §5.1 고정 규칙).
- 가상 판금 `SM1`: 평판 400×300 중립면(시트 바디 `CHASSIS_REAR`), 양쪽 장변 플랜지(굽힘 반경 3, 높이 15), 비드 5개 — 선형 deboss 2(깊이 4, 폭 12, 길이 80, 플랭크 60°, 필렛 2), 원형 emboss 1(지름 30, 깊이 3), 고정 영역 근처 선형 1(전이 영역 겹침 = `BEAD_NEAR_FIXED`), 나사 구멍 RBE2 스파이더를 덮는 원형 1(`BEAD_FIXED_OVERLAP`). 나사 구멍 Ø4 ×6(RBE2), 가짜 브래킷 쉘 part와 `/INTER/TYPE2` tie 띠 1, 공유 노드 1구간.
- 메시: gmsh 2D, 평균 3 mm(min 1, 곡률 기반 세분), `RecombineAll`(Blossom) → quad 위주 + tri 일부, B-rep 엣지 존중. 합성 조립 폴더 = 쉘 part inc(`/NODE`·`/SHELL`·`/SH3N`)·`/PART`·`/PROP/TYPE1`·`/RBE2`·`/GRNOD`·`/SURF`·`/INTER/TYPE2`·가짜 starter.
- 정답: 같은 스크립트로 파라미터만 바꾼 변형형(깊이 ±10%, 위치 ±3 mm, 폭 ±10%, 고정 침범 값 1개)을 만들어 비교.

### 9.2 단계(구현 순서 = 우선순위)

| 단계 | 산출물 | 완료 기준 |
|---|---|---|
| 4C-0 골든·키트 | `make_synthetic_shell.py`, `shell selftest` 초안, 쉘 inc 무변경 왕복 | 합성 세트 생성 결정적, 무변경 왕복 바이트 동일, selftest 리포트에 본문·좌표 배열 없음 |
| 4C-1 깊이(prep+모핑) | `shell fixed-scan/extract/tag/update/morph/check/run`(BEAD_D), 쉘 품질 지표 | 고정 집합 = 정답 노드 집합(종류별 수 일치), 비드 인식 = 정답 5개(누락·오인식 0)·겹침 경고 2종 정확, `match_ratio ≥ 0.98`, 깊이 변형형: update B-rep ↔ 정답 면별 최대 거리 ≤ 0.01 mm·면적 차 ≤ 0.1%, 모핑 노드 ↔ 정답 면 최대 ≤ 0.05 mm, 재측정 오차 ≤ max(0.05 mm, 1%), 고정 노드 줄 바이트 동일, 출력 diff = 쉘 노드 파일의 `/NODE` 좌표 필드만, 반전 0·baseline PASS, 침범 값 → `SHELL_FIXED_REGION_VIOLATION`, 같은 입력 2회 바이트 동일 |
| 4C-2 위치 | BEAD_U/V(`nearest_fixed_edge`·`proportional`), 경계 변경 면 면내 해·전이 영역 | 위치 변형형 위 기준 동일 + 기준 엣지 거리 유지 시험, 전이 영역 노드 접선 변위 감쇠 확인, 비드↔구멍·외곽 충돌 `GEOM_FEATURE_COLLISION` |
| 4C-플랫폼 | `paicad_shell_*` 명령·`kind=shell` 분기·m_3 overlay·3S 병행·UI 최소·fake_paicad shell | PREDICT(A)·DOE(LHS 20 run)·일괄이 fake 경유 성공, 스킵 표에 `FIXED` category, 3S 두께와 동시 run에서 두 변경이 같은 사본에 반영, 솔리드 세트 기존 시험 무수정 통과 |
| 4C-3 개수(매칭) | `paicad map` 비드 단위 확장, group 행 | 합성 2 baseline(비드 4개/5개): 정답 비드 대응률 100%·남는 비드 N/A, group 불일치 422, 단일 baseline·솔리드 4B 시험 불변 |
| 4C-4 폭 | BEAD_W | 폭 변형형 위 기준 동일, 끝단 블렌드 반경 변화 확인 |
| 4C-env | `shell morph --sweep`, `golden/geometry/SM1/` 보고서 | 전 파라미터 envelope 완료·`feasible` 반영·2회 바이트 동일, 고정 한계 `limited_by: fixed` 표시 |
| 현장 인수 | `paicad shell selftest` 실물 실행 | 실물 part 대응 100%·`match_ratio`·고정 노드 수·비드 인식 건수·품질 baseline 수치·(변경형 제공 시) update 면별 거리 수치 회신 |

---

## 10. Verifier 체크리스트(V-SM-*)

- V-SM-1 솔리드 경로 불변: `paicad extract/tag/update/morph/check/run` 인자·보고 스키마·시험 무수정 통과, 솔리드 options에 쉘 절이 오면 기존 거부.
- V-SM-2 CLI: `paicad shell` 하위명령 8종 필수 인자 argparse 강제(누락 = 2), 출력 존재 시 3 `GEOM_OUTPUT_EXISTS`, 쓰기는 `--out-dir`·`--out-files-dir`만.
- V-SM-3 R1: 출력 사본 diff = `/NODE` 좌표 필드만, 요소 수·ID·연결 불변, 무변경 왕복 바이트 동일, 노드 안 바뀐 파일 미출력.
- V-SM-4 고정: 종류별(`INTER_TYPE2` secondary/main·`RBE2`·`RBE3`·`RBODY`·`BCS`·`SHARED`) 합성 정답과 일치, 고정 노드 줄 바이트 동일, `digest` 결정적, 미지원 집합 유형 → `required=true`면 `SHELL_FIXED_PARSE_FAILED`.
- V-SM-5 침범: 고정 노드를 움직이게 하는 값 → update 사전 검사 또는 morph/check에서 `SHELL_FIXED_REGION_VIOLATION`(category `FIXED`), run 스킵·나머지 run 계속.
- V-SM-6 전이: `transition_mm` 안 노드의 접선 변위가 `s(r)`로 감쇠, 0이면 감쇠 없음, 형상 변경 면 노드는 감쇠 안 함.
- V-SM-7 extract: 비드 인식(바닥·플랭크·필렛 링·sense·linear/circular), 구멍과 비드 구분, `BEAD_FIXED_OVERLAP` → `use_default:false`, `BEAD_NEAR_FIXED`, 곡면 기준면 → 깊이만, 이름 규칙(같은 비드 같은 k), XML TX_PARSE 호환.
- V-SM-8 tag: kind 0 없음, `match_ratio` 게이트, 오프셋 메시 → `GEOM_BASELINE_MISMATCH`, 측지 거리 계산.
- V-SM-9 파라미터 정확도: 깊이·위치·폭 변형형 기준(§9.2) 충족, 위치 = 가장 가까운 고정 엣지 거리 유지.
- V-SM-10 품질: warpage·skew·aspect·Jacobian 정의대로 계산(단위 시험: 평면 정사각형 = 0°·0°·1·1), 기본값·상대 판정·`BASELINE_QUALITY_BELOW` 비차단·`dt_ratio` 정의.
- V-SM-11 envelope: 단위(깊이·폭 `%`, 위치 `mm`)·`delta_mm`·`limited_by`·`feasible` 반영·바이트 동일.
- V-SM-12 다중 baseline 비드 단위 매칭: 게이트·점수·헝가리안·group 행·group 불일치 422·N/A, 솔리드 4B 시험 불변.
- V-SM-13 플랫폼: `paicad_shell_*` 키 V-GE-1 검증, `kind` = prep.json(없으면 solid), migration 없음, m_3 overlay 후 props apply 순서, 쉘 세트 등록에서 `BASELINE_INC_MISSING`·`RENUM_CSV_MISSING` 미적용, `/status.features.geometry_native_shell`.
- V-SM-14 독립성·커널·버전: GE V-GE-11·13·14·19 그대로(쉘 코드 포함 — `kernel/` 밖 OCP import 0, 플랫폼 파일명 하드코딩 없음, 영문 메시지, 변경마다 `__version__`·CHANGELOG).
- V-SM-15 골든·키트: 저장소에 STEP·메시 없음, 합성 생성 결정적, selftest 리포트에 본문·좌표 배열 없음.

---

## 11. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| 실물 쉘 메시가 중립면이 아닌 외피·오프셋 메시 | tag 실패 → 쉘 native 불가 | `GEOM_BASELINE_MISMATCH` 조기 차단·현장 키트로 확인(§12 Q1), 오프셋 대응은 후속 |
| 실물 메시가 필렛 접선 엣지를 따르지 않음(작은 필렛 병합) | 노드별 면 매핑으로 요소가 꺾여 품질 저하 | `TAG_EDGE_NOT_RESPECTED` 경고·품질 검사·envelope로 한계 측정 |
| 고정 정의 해석 누락(`/GRNOD/BOX`, 자유 형식 변종, include 계층) | 고정 노드가 움직여 tie·RBE2 파손이 조용히 발생 | 엄격 기본(`required=true` 실패), check (e) tie 재확인, 합성 시험에 형식 변종 |
| 공유 노드·RBE3 등 보수적 고정이 많음 | 모핑 가능 비드 감소 | 종류별 수치 보고·`fixed.kinds`로 조정(`INTER_TYPE2`·`RBE2`는 필수) |
| 쉘 품질 기준이 사내 기준과 다름 | 과도·과소 스킵 | 기본값 제안·고급 옵션, 현장 baseline 수치 회신(§12 Q2) |
| 대형 제품 inc(모든 노드가 한 파일) | 사본 출력 크기·시간 증가 | 바뀐 파일만 출력, 줄 단위 스트리밍 쓰기, `timeout_s` |
| 비드 깊이 증가로 인접 부품과 간섭·두께 변경(3S)과 상호작용 | 응답에 간섭·두께 효과 혼입 | check (d) 두께 반영(`--thickness`), run 기록 |
| 깊이 변경 시 플랭크 요소 늘어남(Δt·aspect) | 품질 미달 스킵 | 면내 평활화·envelope·`feasible` |
| 판재 솔리드 STEP만 있는 현장 | 쉘 native 불가 | `SHELL_BODY_NOT_SHEET` 안내, 중립면 추출은 후속 옵션 |

---

## 12. 미결 사항

| # | 질문 | 임시 결정(이 문서 기본값) |
|---|---|---|
| Q1 | ~~실물 쉘 메시는 중립면 위 노드인가, 바디 이름을 `/PART` 제목과 맞출 수 있나?~~ | **해결(2026-10-19 사용자 확정)**: 중립면 위 노드, 이름 일치 가능. 대상 부품은 표준화되어 `chassis_rear`로 고정 — 기본 대상 component 이름 `chassis_rear`(설정 `shell.default_component`, 변경 가능), 바디 이름 불일치 시 `body_map.json` 우회 유지 |
| Q2 | ~~쉘 품질 기본값이 사내 HyperMesh 기준과 맞나?~~ | **해결(2026-10-19 사용자 확정)**: warpage 15°·skew 60°·aspect 5·Jacobian 0.6(절대), 엣지·Δt 비 0.8(상대) 확정 |
| Q3 | ~~쿠션 솔리드와 쉘 비드를 한 param_set에서 함께 바꾸나?~~ | **해결(2026-10-19 사용자 확정)**: 함께 바꾸지 않음 — 한 param_set은 솔리드 또는 쉘(+3S 두께) 중 하나(혼합 비범위 확정) |
| Q4 | (비차단) 고정 종류 기본 포함 RBE3·RBODY·BCS·공유 노드가 적절한가? | 보수적으로 포함, 옵션으로 제외 가능 |
| Q5 | (비차단) 깊이 변경 기본 방식 `keep_angle`(입구 고정·플랭크 각 유지·바닥 크기 변화) vs `keep_bottom` | `keep_angle`(솔리드 FACE_OFFSET과 같은 거동), 고급 옵션 |

로드맵(비범위): 판재 솔리드 STEP → 중립면 추출(대향 면 쌍 평균면·두께 맵, 쉘 두께 일관성 검사), 비드 길이·플랭크 각·필렛 반경 파라미터, 플랜지 높이·각, 곡면 기준면 위치 이동.

---

## 13. 독립성·커널 격리·버전(GE 준용)

- 독립성: GE §18 전부(플랫폼 import 금지, 파일명·경로는 CLI 인자·JSON으로만 — 쉘은 `--assem-dir`·`--out-files-dir`·`--fixed-dir`가 통로, 메시지 영문, writer 레지스트리).
- 커널 격리: GE §18.9. 비드 인식·면 인접·면 재구성·투영은 `kernel/` 인터페이스로만, 경계 밖은 중립 타입. 면내 해·품질 지표·고정 스캔은 numpy·scipy(가짜 커널로 OCCT 없이 시험).
- 버전: GE §17. 쉘 기능 추가는 MINOR(결과 변화), 쉘 보고 JSON `schema_version`은 파일별 1부터, CHANGELOG "계약"에 `shell-morph.md §n`.

---

## 변경 메모

(구현 중 계약과 다르게 해야 하면 여기에 `SM-C1~`로 기록하고 Plan 확인을 받는다.)
