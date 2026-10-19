# 계약: 형상 3D 가시화·파라미터 미리보기 — `paicad view`

> Plan 2026-10-19. 기준선 `feat/r1-view-docs` 74799fa. 상위 계약은 [geometry-engine.md](geometry-engine.md)(이하 **GE**)와 [shell-morph.md](shell-morph.md)(이하 **SM**)이며, 이 문서가 정하지 않은 규칙(경로 약어 `S`·`P`·`R`, JSON 공통 규약, 쓰기·임시 파일·stdout 규약, 결정성, 버전, 독립성, 커널 격리)은 GE·SM 그대로다. 이 문서가 GE·SM·platform·phase3를 바꾸거나 더하는 규칙은 §2.3에 모았다(가시화 범위에서는 이 문서 우선). 결정 번호는 `GV-n`, 검사는 `V-GV-n`.

## 0. 한 줄 요약

native 세트(솔리드 쿠션·쉘 chassis_rear 비드)의 **공칭 B-rep을 GLB(glTF 2.0 바이너리)로 테셀레이션**하고(삼각형마다 B-rep `face_id`, 바디별 노드), 피처별 면 목록·치수선 주석을 `view_manifest.json`으로 낸다. 사용자가 값을 바꾸면 **`paicad view preview`**가 update(형상 갱신)만 돌려 변경 형상 GLB + 면별 변위(색 맵)를 내고, 선택하면 morph·check까지 돌려 모핑된 FE 메시 표면 GLB와 실패 코드를 낸다. 플랫폼은 짧은 미리보기 작업(`GEOM_PREVIEW`, 전용 레인 `PREVIEW`, 결과 캐시)과 기존 artifacts media 경로로 제공하고, 프런트는 three.js(npm 번들, CDN 금지)로 파라미터 표 ↔ 3D 면 하이라이트·치수선(양방향 선택), 공칭(반투명)·변경 형상 겹쳐 보기, 변위 색 맵, 실패 사유를 보여 준다. 기존 PNG 썸네일은 WebGL 미지원 환경용으로 유지한다.

---

## 1. 목적·범위

### 1.1 목적

1. 사용자가 형상 파라미터가 **CAD의 어느 면·어느 치수인지** 눈으로 확인한다(피처 오인식 발견 포함).
2. 값을 바꾸기 전에 **형상이 어떻게 변하는지**(그리고 만들 수 없는 값인지)를 수 초 안에 본다 — DOE·예측 전에 범위를 정하는 근거.

### 1.2 범위

| 항목 | 범위 |
|---|---|
| 대상 세트 | `engine=native` param_set, `kind=solid`(GE)·`kind=shell`(SM). altair 세트는 PNG·표만(409 `VIEW_NATIVE_ONLY`) |
| 공칭 가시화 | 바디별 B-rep 테셀레이션 GLB + B-rep 엣지 선 + `view_manifest.json`(면 목록·피처 면·치수선·범위·envelope) |
| 미리보기 | update만(기본) → 변경 형상 GLB + 면별 변위. 선택 `fe=check` → morph + check, FE 메시 표면 GLB + 검사 결과 |
| 플랫폼 | ④ 세트 상세의 3D 보기. 준비 step `NP_VIEW`(공칭), 작업 `GEOM_PREVIEW`(미리보기), 캐시, API |
| 화면 | ④ 세트 상세의 기존 피처 표 옆 3D 패널(새 화면 없음) |

### 1.3 비범위

- ①-1·①-2 학습 단계 파라미터 표의 3D 보기(1차는 ④ 세트 상세만, §13 Q3). 일괄 예측·DOE run별 3D 보기.
- 3S 쉘 두께(`/PROP/TYPE1`) 행의 3D 표현(두께 렌더링 없음 — 표에서만, 3D 대응 "없음" 표시).
- 미리보기 결과를 해석 입력으로 쓰기(미리보기는 include를 쓰지 않음, §5.3).
- glTF 압축 확장(Draco·meshopt)·텍스처·환경맵, 측정 도구(임의 두 점 거리), 단면 보기, 애니메이션(공칭→변경 모핑 연속 재생).
- 다중 baseline(4B) baseline별 3D 비교(기본 baseline만 표시).

### 1.4 원칙

GE §1.4·§18(플랫폼 import 금지, 파일+CLI+버전 JSON 경계, 영문 메시지, 결정적 출력, `kernel/` 밖 OCP 금지)과 AGENTS.md(외부 명령은 워커만, 경로·명령은 설정, 사용자 문구 한국어, DB에는 경로·상태·수치만)를 그대로 따른다. 기존 솔리드·쉘 명령(`extract`·`update`·`morph`·`check`·`run`·`shell *`)의 인자·출력·동작은 바꾸지 않는다(GE-C10·SM-2 동결 보호). 프런트는 폐쇄망 배치(서버에 Node 없음, `frontend-dist/` 빌드본)라 외부 URL·CDN·런타임 다운로드를 쓰지 않는다.

---

## 2. 용어·결정

### 2.1 용어

| 용어 | 뜻 |
|---|---|
| 공칭 뷰(view) | 공칭 B-rep의 GLB + manifest. 세트 준비 때 1회 생성(`S/native/view/`) |
| 미리보기(preview) | 값 집합 1개에 대한 변경 B-rep GLB(+ 선택 FE GLB) + manifest. 캐시에 저장 |
| face_id | 바디 안 B-rep 면 번호 `F<k>`(GE §4.3, `TopExp::MapShapes(FACE)` 1-기반). GLB에서는 정수 k, 바디는 노드로 구분 |
| 치수 주석(dimension) | 피처 값을 보여 주는 치수선: 시작점 `p0`, 끝점 `p1`, 라벨 위치, 값, 단위 |
| 변위(disp) | 미리보기 꼭짓점의 공칭 형상까지 거리(B-rep) 또는 FE 노드의 기준본 대비 이동 크기(mm) |
| 캐시 | 미리보기 산출물. **플랫폼 임시 산출물**(사용자 산출물 아님, 언제든 입력에서 재생성 가능) — 자동 삭제 허용(§6.6) |
| 테셀레이션 허용오차 | `linear_mm`(현 길이 편차)·`angular_deg`(각 편차). LOD는 이 값으로 정한다 |

### 2.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| GV-1 | 형식 = **GLB(glTF 2.0 바이너리)**: 바디별 노드, 삼각형 정점 속성 `_FACE_ID`, 엣지 선 노드, 확장 없음, 좌표 mm·Z-up(manifest 명시). 대안 자체 JSON+바이너리는 기각 | three.js `GLTFLoader` 표준 지원(추가 의존 없음), 한 파일·바이너리 압축성, 노드 계층 = 바디, 사용자 정의 속성(`_` 접두)이 표준 허용, 외부 도구로 열어 확인 가능 |
| GV-2 | CLI = 새 그룹 `paicad view {export,preview}`·`paicad shell view {export,preview}`(extract 부산물 아님) | extract 출력·인자 동결(GE-C10), extract는 tag 전이라 FE·접촉 정보 없음, 뷰 실패가 추출을 실패시키지 않게 분리 |
| GV-3 | 미리보기 = update만(기본, 목표 수 초) + 선택 `fe=check`(morph+check). include·`--out-inc`를 절대 쓰지 않음 | 사용자 요청(속도), 미리보기 결과가 해석 입력에 섞이지 않게 |
| GV-4 | 뷰 옵션은 별도 파일 `view_options.json`(`--view-options`), 기존 `options.json` 스키마 불변 | GE-C10 "options 모르는 키 거부" 유지 |
| GV-5 | GLB·manifest 작성은 paicad 순수 Python(`struct`·`json`·numpy) — 새 런타임 의존 없음 | GE §5.1 "그 밖 의존 금지" |
| GV-6 | 플랫폼: 공칭 뷰 = `PARAM_SET_NATIVE` 새 step `NP_VIEW`(실패는 경고), 미리보기 = 새 job_type `GEOM_PREVIEW`(새 레인 `PREVIEW`, 전역 슬롯 미사용, 동시 실행 제한·짧은 타임아웃), 캐시 키 = 세트·준비본·값·fe·engine_version 해시 | DOE가 전역 슬롯을 몇 시간 쥐어도 미리보기는 수 초 안에 돌아야 함 |
| GV-7 | 산출물 제공 = 기존 artifacts(`/artifacts/{id}/media` GLB, `/artifacts/{id}/content` manifest), kind 5종 추가 | 이름·경로 기반 새 다운로드 엔드포인트 금지(platform B18) |
| GV-8 | 캐시 = `<study>/_cache/geom_preview/`의 플랫폼 임시 산출물, housekeeping이 기간·총량 기준 **삭제**(`_backup` 이동 아님). 사용자 산출물 삭제 금지 규칙과 별개로 정의 | 재생성 가능·고유 데이터 없음, 슬라이더 조작마다 쌓여 이동 보관은 의미 없음 |
| GV-9 | 프런트 = three.js npm 의존(정확 버전 고정) + `three/examples/jsm`의 `GLTFLoader`·`OrbitControls`·`CSS2DRenderer`만, 동적 import로 별도 청크(plotly와 같은 방식). WebGL 불가 시 기존 PNG | 폐쇄망·CDN 금지, 첫 화면 번들 영향 최소 |
| GV-10 | 미리보기 실패(형상 생성 불가 등)는 **작업 성공 + 결과 FAIL**로 캐시(같은 입력 = 같은 실패), 인프라 오류(시간 초과·실행 파일 없음)만 작업 실패·캐시 안 함 | 결정적 실패는 다시 돌릴 이유 없음, 화면은 실패 사유를 결과로 표시 |

### 2.3 기존 계약에서 바뀌거나 더해지는 규칙(이 문서 우선)

| 기존 | 변경 |
|---|---|
| GE §5.3 하위 명령·SM §5.2 | `paicad view export/preview`, `paicad shell view export/preview` 추가(§5). 기존 명령 불변 |
| GE §5.4 종료코드 | **14** 추가 = 뷰 출력 실패(`VIEW_TESSELLATION_FAILED`·`VIEW_TOO_LARGE`) |
| GE §6.5·SM §6.7 실패 코드 표 | `VIEW_*` 코드·category `VIEW` 추가(§5.5). 미리보기는 기존 `GEOM_*`·`SHELL_*` 코드를 그대로 전달 |
| GE §7.3.4 `PARAM_SET_NATIVE` step | NP_TAG 뒤 `NP_VIEW`(LOCAL, weight 5) 추가 — 실패는 step 경고 `VIEW_EXPORT_FAILED`, 작업은 계속(SM §8.2 쉘 체인도 같음) |
| GE §4.2·SM §4.2 `native/` | `native/view/{view.glb, view_manifest.json, paicad.log}` 추가, `prep.json`에 선택 키 `view{status, sha256, tess, engine_version}`. **준비본 유효성(READY/STALE) 판정에는 넣지 않음** |
| platform.md §2 레인 `SLOT`·`LIGHT` | 레인 **`PREVIEW`** 추가: 전역 슬롯을 잡지 않고 `geometry.view.max_concurrent`만큼 동시 실행, 허용 외부 명령은 `paicad_view_preview`·`paicad_shell_view_preview`뿐(§6.2) |
| platform.md §6.8 artifacts kind | `GEOM_VIEW_GLB`·`GEOM_VIEW_MANIFEST`·`GEOM_PREVIEW_GLB`·`GEOM_PREVIEW_FE_GLB`·`GEOM_PREVIEW_MANIFEST` 추가. content-type `model/gltf-binary` 추가 |
| phase3 §15.4 `/artifacts/{id}/media` = CONTOUR_* 만(GE에서 `FEATURE_PNG` 추가) | `GEOM_*_GLB` 3종 추가(Range 규칙 동일). manifest는 기존 `/content`(application/json) |
| phase3 `ux_jobs_study_type_active`(Study·유형별 활성 1개) | `GEOM_PREVIEW` 제외(동시 제한은 §6.4가 담당) |
| phase3 §5.5 정리 범주·AGENTS.md "사용자 산출물 삭제 금지" | `<study>/_cache/`는 정리 범주에 넣지 않고(범주 6개 불변) housekeeping이 삭제(§6.6). `_cache/` 밖은 기존 규칙 그대로 |
| GE §7.5 migration head 0015 | migration **`0016_geom_view`**(§6.7) |

---

## 3. 전체 흐름

```text
[세트 준비 1회: PARAM_SET_NATIVE]
 NP_EXTRACT ─ NP_TAG ─ NP_VIEW: paicad (shell) view export ─→ S/native/view/{view.glb, view_manifest.json}
                                                                  │ artifacts GEOM_VIEW_GLB·_MANIFEST
[화면: ④ 세트 상세]                                                ▼
 피처 표 ◀──── 양방향 선택 ────▶ 3D 뷰어(three.js): 면 하이라이트·치수선·바디 표시/숨김
   │ 값 입력·슬라이더 → [미리보기]
   ▼
 POST /param-sets/{id}/previews {values, fe}
   ├ 캐시 적중 → 200 결과(즉시)
   └ 미적중 → 202 → GEOM_PREVIEW(레인 PREVIEW): paicad (shell) view preview
                       update(→ 실패면 코드) ─ 테셀레이션·변위 ─ [fe=check: morph ─ check]
                     → <study>/_cache/geom_preview/<key>/{preview.glb, preview_fe.glb?, preview_manifest.json}
   ▼
 뷰어: 공칭(반투명) + 변경 형상(변위 색 맵) [+ FE 메시] / 실패 배지·사유·관련 피처 빨강
```

---

## 4. 출력 파일 계약

JSON 공통 규약은 GE §4 머리말(UTF-8·`schema_version`·mm·deg·`engine`·`engine_version`)과 같다. manifest 최상위에 `kind: "solid"|"shell"`. 파일 이름은 솔리드·쉘 공통이다(스키마가 같고 `kind`로 구분 — SM의 `shell_*` 분리는 보고 스키마가 다를 때의 규칙이며 여기는 하나의 스키마).

### 4.1 GLB 구조(`view.glb`·`preview.glb`)

| 항목 | 규칙 |
|---|---|
| 형식 | glTF 2.0 바이너리(GLB): 헤더 + JSON 청크 + BIN 청크 1개, 4바이트 정렬(JSON 공백·BIN 0 채움). `extensionsUsed`·`extensionsRequired` 없음. `asset = {"version":"2.0","generator":"paicad <ver>"}` |
| 좌표·단위 | **mm, CAD 좌표 그대로(Z-up)**, 변환 행렬 없음. glTF 관례(m·Y-up)와 다르므로 manifest `unit:"mm"`·`up_axis:"Z"`와 루트 노드 `extras` 같은 값. 뷰어가 카메라 up = Z로 둔다 |
| 노드 | 루트 `paicad_view` 아래 바디마다 노드 2개: `<body>`(면 메시) · `<body>.edges`(B-rep 엣지 선, `view_options.edges=false`면 없음). 순서 = features `bodies`(솔리드)·`parts`(쉘) 순서 |
| 면 메시 | primitive 1개, mode TRIANGLES. 속성 `POSITION`(FLOAT VEC3, min·max 필수), `NORMAL`(FLOAT VEC3, 면 surface 법선 — 면 안에서 매끈, 면 경계에서 분리), **`_FACE_ID`**(UNSIGNED_SHORT, 면 수 > 65535면 UNSIGNED_INT, SCALAR, 값 = k), 미리보기만 **`_DISP_MM`**(FLOAT SCALAR, §4.4). indices UNSIGNED_INT(정점 < 65536이면 UNSIGNED_SHORT) |
| 정점 공유 | 면 사이에서 정점을 공유하지 않는다(삼각형 세 정점의 `_FACE_ID`가 항상 같음) |
| 삼각형 순서 | `_FACE_ID` 오름차순으로 연속 배치, 면 안에서는 테셀레이터 출력 순서. 면 k의 삼각형 구간 `[first, count]`을 manifest `faces[].tri`에 기록(하이라이트를 정점 탐색 없이 그룹으로 처리) |
| 엣지 선 | mode LINES, `POSITION` + `_EDGE_ID`(엣지 번호 `E<k>`의 k) |
| 재질 | 바디마다 기본 회색 재질 1개(`doubleSided` = 쉘 true·솔리드 false), 텍스처 없음. 뷰어가 재질을 덮어씀 |
| 결정성 | 테셀레이션 단일 스레드(OCCT `BRepMesh_IncrementalMesh` InParallel = false), JSON 청크 키 순서 고정·공백 없음, 시각·경로·난수 없음 → 같은 입력·옵션·버전이면 **바이트 동일** |

FE GLB(`preview_fe.glb`): 노드 = 모핑 대상 component(솔리드 `<part>`, 쉘 `<title>` 또는 `PART:<id>`) + 선택 `<part>.edges`(요소 엣지, `fe_edges`). 솔리드 = tetra4 외피 삼각형(GE §6.1 외피 정의), 쉘 = `/SHELL`(대각선 n1–n3으로 2분할, n3=n4는 1개)·`/SH3N`. 속성 `POSITION`(모핑 좌표)·`NORMAL`(정점 평균)·`_DISP_MM`(노드 이동 크기)·`_ELEM_ID`(UNSIGNED_INT, 요소 ID — 표시용). 정점 = 노드(공유), 같은 결정성 규칙.

### 4.2 `view_manifest.json`(공칭)

```json
{
  "schema_version": 1, "kind": "solid", "engine": "native", "engine_version": "0.9.0",
  "mode": "nominal", "status": "OK", "code": null, "category": null, "message": null,
  "unit": "mm", "up_axis": "Z",
  "source": {"cad": [{"rel": "model.step", "sha256": "…"}], "features_sha256": "…", "fixed_digest": null},
  "glb": {"file": "view.glb", "sha256": "…", "bytes": 812345, "triangles": 120344, "vertices": 361032},
  "tess": {"linear_mm": 0.1, "angular_deg": 20.0, "coarsened": 0},
  "bbox": [0, 0, 0, 400, 80, 60],
  "bodies": [
    {"body": "CUSH_L", "node": "CUSH_L", "edges_node": "CUSH_L.edges",
     "faces": [{"id": "F1", "surface": "PLANE", "tri": [0, 124], "area": 9600.0}, {"id": "F2", "surface": "CYLINDER", "tri": [124, 380], "area": 1130.9}]}
  ],
  "features": [
    {"name": "CUSH_L_THK_1", "parameter": "CUSH_L_THK_1", "type": "THICKNESS", "body": "CUSH_L",
     "nominal": 12.5, "value": 12.5, "unit": "mm",
     "range": {"min": 11.875, "max": 13.125}, "feasible": {"min": 6.2, "max": 18.0, "source": "envelope"},
     "faces": {"moving": ["F12"], "fixed": ["F7"], "other": []},
     "dimension": {"kind": "linear", "p0": [60, 40, 0], "p1": [60, 40, 12.5], "label": [70, 40, 6.25], "value": 12.5, "unit": "mm", "geom_len": 12.5}},
    {"name": "CUSH_R_THK_1", "parameter": "CUSH_L_THK_1", "type": "THICKNESS", "body": "CUSH_R", "…": "그룹 구성원 — 같은 구조"}
  ],
  "fixed_clusters": [],
  "warnings": []
}
```

| 필드 | 규칙 |
|---|---|
| `features[]` | features JSON의 **모든 피처**(대칭 그룹 구성원 포함). `parameter` = 파라미터 표 행 이름(그룹 대표, 분리 시 자기 이름). 표 행 선택 시 `parameter`가 같은 항목 전부를 하이라이트 |
| `nominal`·`range`·`feasible` | features JSON 값을 그대로 복사(같은 float). `feasible.source` = `estimate`\|`envelope`(GE §11.2). 뷰어 슬라이더 범위의 근거 |
| `value` | 공칭 뷰 = `nominal`, 미리보기 = 입력 값(그룹 구성원은 대표 값) |
| `faces` | 솔리드: `moving`·`fixed` = features `faces`(update `--tag-dir`로 기준면이 바뀌면 미리보기 manifest는 `update.json.applied[].moved/fixed` 사용), `other` = 측정에 쓰는 나머지 면. 쉘: `moving` = 비드 `bottom`+`flanks`+`fillets_*`, `fixed` = `[base_face]`, `other` = [] |
| `dimension.kind` | `linear`(두께·깊이·폭·높이) \| `radius`(구멍·필렛) \| `position`(HOLE_U/V·BEAD_U/V — `p0` = 기준 고정 면/엣지 위 점, `p1` = 축·비드 중심) |
| `dimension.p0`·`p1` | 그 피처 `measure` 방법(GE §4.3 `measure`, SM §6.3)과 같은 기준의 대표 두 점: 선형 = 고정 면 centroid의 대향 면 투영 쌍, 반경 = 축 중간점과 면 위 점, 위치 = 기준 면(엣지) 위 최근접점과 축(중심). `label` = 두 점 중점에서 바디 bbox 바깥쪽으로 `0.05·L_body` 이동한 점 |
| `dimension.value` | **= `value`(공칭 뷰는 extract 공칭과 같은 float)**. 표시 값의 출처는 항상 features·values이며 `geom_len`(=|p1−p0|)은 정보용. `|geom_len − value| > tol`(구배·곡면 등)이면 경고 `VIEW_DIM_APPROX`(표시 유지) |
| `fixed_clusters` | 쉘만(`--fixed-dir` 있을 때): `shell_scan.json.fixed.clusters` 복사(`id, center, radius_mm, kinds, nodes`). 솔리드·고정 정보 없음 = `[]` |
| `warnings` | `VIEW_COARSENED`(크기 상한으로 허용오차를 키움, `tess.coarsened` = 횟수), `VIEW_DIM_APPROX`, `VIEW_FACE_EMPTY`(삼각형 0개인 퇴화 면, `face`) |

### 4.3 `preview_manifest.json`(미리보기)

§4.2 스키마 + 아래 키. `mode: "preview"`.

```json
{
  "schema_version": 1, "kind": "solid", "mode": "preview",
  "status": "OK", "code": null, "category": null, "message": null,
  "values": {"CUSH_L_THK_1": 12.9},
  "nominal_ref": {"view_sha256": "…", "tess": {"linear_mm": 0.1, "angular_deg": 20.0}},
  "glb": {"file": "preview.glb", "sha256": "…", "bytes": 813002, "triangles": 120344, "vertices": 361032},
  "disp": {"attribute": "_DISP_MM", "max_mm": 0.4, "by_face": {"CUSH_L": {"F12": {"max": 0.4, "mean": 0.4, "change": "geometry"}, "F3": {"max": 0.0, "mean": 0.0, "change": "boundary"}}}},
  "fe": {"mode": "check", "status": "PASS", "code": null, "category": null,
         "glb": {"file": "preview_fe.glb", "sha256": "…", "bytes": 402113}, "max_disp_mm": 0.41,
         "quality": {"min_stretch": 0.31, "max_aspect": 6.2, "edge_ratio": 0.92, "dt_ratio": 0.91}},
  "reports": {"update": "update/update.json", "morph": "morph/morph.json", "check": "check/check.json"},
  "failure": null,
  "timing": {"update_s": 1.2, "tess_s": 0.3, "morph_s": null, "check_s": null, "total_s": 2.1}
}
```

| 필드 | 규칙 |
|---|---|
| `status`·`code`·`category` | 실행한 단계(update → morph → check)의 **첫 실패**. update FAIL이면 `glb: null`·`disp: null`, morph/check FAIL이면 `glb` 있음 + `fe.status`·`fe.code`. 코드는 GE §6.5·SM §6.7 그대로(`GEOM_FEATURE_COLLISION`·`GEOM_TOPOLOGY_CHANGED`·`GEOM_QUALITY`·`SHELL_FIXED_REGION_VIOLATION` …) |
| `reports` | 같은 폴더 안 하위 폴더에 기존 형식 그대로 쓴 보고(`update.json`/`shell_update.json` 등, 스키마 GE §4.6~4.8·SM §4.7~4.9). 실행 안 한 단계는 null |
| `disp.by_face[*].change` | `geometry`(surface 변경) \| `boundary`(경계만 변경) \| `none`. 솔리드는 `update.json.applied[].moved`와 변위로, 쉘은 `shell_update.json.changed`로 정함 |
| `failure` | 실패 시 화면 표시 보조(선택 키): `features[]`(충돌 두 피처 = `update.json.collisions`, 그 밖 실패 원인 피처), `clusters[]`(쉘 고정 침범 클러스터 id), `points[]`(`{xyz, label}` — check 편차 최악 노드 좌표 등). 없으면 null |
| `fe` | `fe=off`면 `{"mode": "off"}`만. `fe=morph`는 morph까지(검사 없음, `fe.status` = morph 결과) |
| `nominal_ref` | 겹쳐 보기 기준 공칭 뷰 sha256·허용오차. 미리보기는 이 허용오차로 테셀레이션(같은 정점 밀도) |
| `timing` | 단계별 경과(초, 소수 1자리). 속도 목표 확인용. **결정성 예외**: `timing`만 실행마다 다를 수 있음(바이트 동일 비교에서 `timing` 키 제외, GLB는 바이트 동일) |

### 4.4 변위 정의

- B-rep(`_DISP_MM`, `by_face`): 미리보기 정점마다 **같은 face_id 공칭 면까지 거리**(kernel 투영, 실패 시 공칭 바디 전체 거리) — 면 위 미끄러짐은 0으로 보이는 "형상 편차"다. |변위| ≤ 1e-6 mm는 0(GE-C7과 같음).
- FE(`preview_fe.glb`): 노드마다 `|모핑 좌표 − 기준본 좌표|`(실제 노드 이동).
- 색 맵 범위는 뷰어가 0 ~ `max_mm`(또는 FE `max_disp_mm`)로 둔다.

### 4.5 `view_options.json`(`--view-options`, 플랫폼 작성 = 설정 `geometry.view`의 사용값)

```json
{"schema_version": 1,
 "tess": {"linear_mm": 0.1, "angular_deg": 20.0},
 "max_triangles": 500000, "max_glb_bytes": 16777216, "coarsen_steps": 3,
 "edges": true, "fe_edges": true}
```

- 범위: `linear_mm` (0, 10], `angular_deg` [5, 45], `max_triangles` ≥ 1000, `max_glb_bytes` ≤ 플랫폼 `ui.max_artifact_bytes`(플랫폼이 검사), `coarsen_steps` 0~5. 모르는 키 거부(GE-C10 준용). 없으면 위 기본값.
- **크기 상한·LOD**: 테셀레이션 결과 삼각형 > `max_triangles` 또는 GLB > `max_glb_bytes`이면 `linear_mm`·`angular_deg`를 2배(각도 상한 45)로 키워 다시 테셀레이션, 최대 `coarsen_steps`회(경고 `VIEW_COARSENED`). 그래도 넘으면 FAIL `VIEW_TOO_LARGE`. 키운 값은 `tess`에 기록하고 미리보기는 `nominal_ref.tess`를 그대로 쓴다(겹쳐 보기 정합). FE GLB는 노드·요소 고정이라 LOD 없음 — 상한 초과 시 `fe_edges`를 빼고, 그래도 넘으면 `fe.status` FAIL `VIEW_TOO_LARGE`(형상 GLB는 유지).

---

## 5. CLI

공통 규약 GE §5.2(인자 두 토큰, `--out-dir`에만 쓰기, 기존 출력 있으면 3 `GEOM_OUTPUT_EXISTS`, 임시 폴더, `PAICAD PROGRESS`/`PAICAD RESULT` 줄, `paicad.log`, `--threads`). 필수 **굵게**.

### 5.1 하위 명령

| 명령 | 인자 | 출력(성공 판정) |
|---|---|---|
| `paicad view export` | **`--cad`**, **`--features`**(`parameter_features.json`), **`--out-dir`**, `--body-map`, `--view-options` | `view_manifest.json`(`status: OK`) + `view.glb` |
| `paicad view preview` | **`--cad`**, **`--features`**, **`--values`**, **`--out-dir`**, `--tag-dir`(기준면 규칙, GE §6.2), `--body-map`, `--options`(geom options — update·morph·check 동작), `--view-options`, `--nominal-manifest`(공칭 `view_manifest.json` — `nominal_ref`·`tess` 출처, 없으면 `--view-options` 값), `--fe off\|morph\|check`(기본 `off`), FE일 때 필수: `--baseline-inc`·`--renum-csv`·`--assem-dir`(그리고 `--tag-dir`) | `preview_manifest.json`(존재 = 성공 판정 파일, 내용 `status` OK/FAIL) + update OK면 `preview.glb` + FE면 `preview_fe.glb`. 하위 `update/`·`morph/`·`check/`에 기존 형식 보고 |
| `paicad shell view export` | **`--cad`**, **`--features`**(`shell_features.json`), **`--out-dir`**, `--fixed-dir`(고정 클러스터 표시), `--body-map`, `--view-options` | 위와 같음(`kind: "shell"`) |
| `paicad shell view preview` | **`--cad`**, **`--features`**, **`--values`**, **`--out-dir`**, `--fixed-dir`(고정 사전 검사 — SM §4.7, 플랫폼은 항상 넘김), `--body-map`, `--options`(쉘 options), `--view-options`, `--nominal-manifest`, `--fe off\|morph\|check`, FE일 때 필수: `--assem-dir`·`--tag-dir`·`--fixed-dir`, 선택 `--thickness` | 위와 같음. 하위 `update/shell_update.json`·`morph/shell_morph.json`·`check/shell_check.json` |

### 5.2 동작 규칙

1. preview는 update·morph·check를 **같은 프로세스 안에서** 기존 구현 함수로 실행한다(프로세스·OCP 적재 1회 — 속도). 결과는 같은 CLI(`paicad update` 등)로 돌린 것과 같은 B-rep·좌표여야 한다(V-GV-6).
2. check는 `fe=check`일 때만, `--out-inc`/`--out-files-dir`에 해당하는 출력은 **만들지 않는다**(morph 후보 `morphed.inc`·`files/`도 쓰지 않음 — 좌표는 메모리에서 GLB로만). 미리보기 폴더에는 solver include가 없다.
3. 앞 단계 FAIL이면 뒤 단계는 실행하지 않는다(GE §5.3 run과 같음). update OK·FE FAIL이면 `preview.glb`는 쓴다.
4. FE 인자 누락(`--fe` ≠ off인데 필수 인자 없음)은 종료코드 2.
5. 결정성: GE §5.2. 같은 입력·옵션·버전이면 GLB·manifest(`timing` 제외) 바이트 동일.

### 5.3 kernel·독립성

- 테셀레이션·엣지 이산화·면 투영(변위)은 `kernel/` 인터페이스(GE §18.9)로만: `tessellate(body, linear_mm, angular_deg) -> (positions float64[n,3], normals, triangles int64[m,3], face_ids int32[m])`, `edge_polylines(body, …)`, `distance_to_face(points, body, face_id)`. 경계 밖은 numpy·정수·float만.
- GLB writer `paicad.view.gltf`, manifest·치수 계산 `paicad.view.manifest`는 numpy만(가짜 커널로 OCCT 없이 시험).
- 플랫폼 파일명·경로 하드코딩 없음(`view_manifest.json` 등은 paicad 자신의 출력 이름 — `update.json`과 같은 지위). 메시지 영문(GE §18.4).

### 5.4 종료코드(GE §5.4에 더함)

| 코드 | 명령 | 뜻 |
|---|---|---|
| 0 | export·preview | export 성공 / preview 결과 OK |
| 3 | 전부 | 입력 오류(`GEOM_INPUT_INVALID` — 모르는 파라미터·비유한 값, `GEOM_OUTPUT_EXISTS`) |
| 10 | preview | update FAIL(manifest `status: FAIL`, `code` = update 코드) |
| 11 | preview | morph·check FAIL(`fe.code`) |
| 14 | export·preview | 뷰 출력 실패 `VIEW_TESSELLATION_FAILED`·`VIEW_TOO_LARGE` |
| 20 | 전부 | 내부 오류 |

### 5.5 실패 코드(추가분)

| code | category | 한국어 사유(플랫폼 표시 문구) | 발생 | 종료코드 |
|---|---|---|---|---|
| `VIEW_TESSELLATION_FAILED` | `VIEW` | 3D 형상 변환 실패 | export·preview | 14 |
| `VIEW_TOO_LARGE` | `VIEW` | 3D 형상이 너무 큼(표시 허용오차를 키우세요) | export·preview | 14 |
| `VIEW_EXPORT_FAILED` | `VIEW` | 3D 보기를 만들지 못함(그림으로 표시) — step 경고 | 플랫폼 NP_VIEW | — |
| `VIEW_NATIVE_ONLY` | `INPUT` | 3D 미리보기는 native 템플릿에서만 쓸 수 있습니다 | 플랫폼 API 409 | — |
| `VIEW_UNAVAILABLE` | `INPUT` | 3D 미리보기를 쓸 수 없습니다 — paicad 뷰 명령 설정 확인 | 플랫폼 API 409 | — |
| `PREVIEW_BUSY` | `INPUT` | 미리보기가 많이 대기 중입니다 — 잠시 후 다시 시도하세요 | 플랫폼 API 429 | — |
| `ARTIFACT_EXPIRED` | `INPUT` | 미리보기 파일이 정리되었습니다 — 다시 미리보기 하세요 | 플랫폼 API 410 | — |
| `VIEW_PREVIEW_TIMEOUT` | `VIEW` | 미리보기 시간 초과 | 플랫폼 GV_RUN | — |

---

## 6. 플랫폼 연동

### 6.1 설정(`config/platform.example.yaml`)

```yaml
geometry:
  view:                               # 절이 없으면 아래 기본값
    enabled: true
    tess: {linear_mm: 0.1, angular_deg: 20.0}
    max_triangles: 500000
    max_glb_bytes: 16777216           # ≤ ui.max_artifact_bytes(20 MiB) — 넘으면 config.warnings + 그 값으로 자름
    max_concurrent: 1                 # PREVIEW 레인 동시 실행 수(전역)
    max_queued_per_user: 2            # 사용자별 대기+실행 미리보기 상한(넘으면 429 PREVIEW_BUSY)
    threads: 2                        # 미리보기 paicad --threads(진행 중 DOE와 CPU 공유)
    timeout_s: {export: 300, preview: 60, preview_fe: 300}
    cache: {retention_days: 7, max_total_bytes: 2147483648, purge_interval_h: 6}
commands:
  paicad_view_export: ["{paicad}", "view", "export", "--cad", "{cad_input}", "--features", "{features_json}", "--view-options", "{view_options_json}", "--out-dir", "{out_dir}"]
  paicad_view_preview: ["{paicad}", "view", "preview", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}", "--tag-dir", "{tag_dir}", "--options", "{options_json}", "--view-options", "{view_options_json}", "--nominal-manifest", "{nominal_manifest}", "--fe", "{fe_mode}", "--baseline-inc", "{baseline_inc}", "--renum-csv", "{renum_csv}", "--assem-dir", "{assem_dir}", "--threads", "{threads}", "--out-dir", "{out_dir}"]
  paicad_shell_view_export: ["{paicad}", "shell", "view", "export", "--cad", "{cad_input}", "--features", "{features_json}", "--fixed-dir", "{fixed_dir}", "--view-options", "{view_options_json}", "--out-dir", "{out_dir}"]
  paicad_shell_view_preview: ["{paicad}", "shell", "view", "preview", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}", "--fixed-dir", "{fixed_dir}", "--tag-dir", "{tag_dir}", "--assem-dir", "{assem_dir}", "--options", "{options_json}", "--view-options", "{view_options_json}", "--nominal-manifest", "{nominal_manifest}", "--fe", "{fe_mode}", "--threads", "{threads}", "--out-dir", "{out_dir}"]
```

- `TEMPLATE_SPECS`: 4개 키 모두 `required=False`, argv[0] = `{paicad}`(V-GE-1). 새 placeholder `view_options_json`·`nominal_manifest`(선택 쌍 — 공칭 뷰가 없으면 `"--nominal-manifest","{nominal_manifest}"` 쌍 생략, GE §7.3.1 `{renum_csv}` 방식)·`fe_mode`(`off|morph|check` 허용목록)·`threads`(정수), `{body_map}`은 GE §7.1처럼 argv 끝에 덧붙임. 그 밖 placeholder는 GE §7.1·SM §8.1 이름.
- `/status`: `features.geometry_view` = `geometry.view.enabled` + `paicad_view_export`·`paicad_view_preview` 비null + 실행 파일 존재, `features.geometry_view_shell` = 쉘 두 키 기준.

### 6.2 레인 `PREVIEW`(워커)

- 워커에 PREVIEW 실행기 추가: `jobs.lane='PREVIEW'` 작업만 잡고, 실행 중 PREVIEW 작업 수 < `max_concurrent`일 때 최소 `queue_seq` claim(전역 `worker_slot` 행을 쓰지 않음, lease 규칙은 기존과 같음).
- 허용 step: GV_PREP·GV_REGISTER(INTERNAL), GV_RUN(LOCAL — `paicad_view_preview`·`paicad_shell_view_preview`만). 다른 명령 키를 PREVIEW 레인에서 실행하면 `StepFailure(INTERNAL)`(정적 시험으로도 확인).
- 제한기: 기존 제한기(Windows Job Object·POSIX·null)를 작업별로 적용, 메모리 한도는 기존 작업 한도 설정을 그대로 사용. 취소·lease 상실 시 프로세스 종료.

### 6.3 `NP_VIEW`(공칭 뷰, `PARAM_SET_NATIVE`)

| step | 처리 | 판정 |
|---|---|---|
| NP_VIEW (LOCAL 5, NP_TAG 뒤·BL_MAP 앞) | solid: `paicad_view_export`(`{out_dir}`=`T/native/view`), shell: `paicad_shell_view_export`(`{fixed_dir}`=`T/native/fixed`). `view_options.json` = 설정 사용값(`T/native/view/view_options.json`) | `view_manifest.json` OK + `view.glb` → step 결과 `view = {status:"READY", sha256, tess, engine_version}`(NP_REGISTER가 `prep.json.view`에 기록). 실패·명령 null이면 step SUCCEEDED + 경고 `VIEW_EXPORT_FAILED`(사유), `view = {status:"FAILED"\|"MISSING"}` — **작업은 계속** |
| NP_REGISTER | 기존 + artifacts `GEOM_VIEW_GLB`(model/gltf-binary)·`GEOM_VIEW_MANIFEST`(application/json) 등록(`rel_path` = `04_params/<id>/native/view/…`) | 기존 |

- reprep(`native-prepare`)은 `native/`를 `_backup` 이동하므로 NP_VIEW가 다시 만든다. from-train(동기, paicad 없음)은 `D/native/view/`가 있으면 복사, 없으면 MISSING.
- 기존(이 기능 전) 세트·MISSING·FAILED: 화면은 PNG를 보이고 [3D 보기 만들기] = 값 전부 공칭인 미리보기 요청(§6.4, 캐시) — 그 결과 manifest(`mode: preview`, 변위 0)를 공칭 뷰로 쓴다. 04_params에는 쓰지 않는다.

### 6.4 `GEOM_PREVIEW` 작업

`JOB_TYPES["GEOM_PREVIEW"] = JobTypeDef("GEOM_PREVIEW", 4, "PREVIEW", "형상 미리보기", (GV_PREP INTERNAL 5, GV_RUN LOCAL 90, GV_REGISTER INTERNAL 5), "④", notify_success=False)`, `can_retry=false`(새로 요청), 알림 없음(실패 포함 — 화면이 폴링으로 표시), 작업 목록 화면에서 기본 숨김(필터 "미리보기 포함").

params `{param_set_id, preview_id, values, fe: "off"|"check"|"morph"}`. 화면은 `off`·`check`만 쓴다(`morph`는 진단용).

| step | 처리 |
|---|---|
| GV_PREP | 준비본 READY 재확인(`INPUT_CHANGED`), 캐시 폴더 `C = <study>/_cache/geom_preview/<key[0:2]>/<key>/` 생성(이미 있으면 `C`를 지우고 새로 — 캐시라 이동 아님), `C/values.json`(GE §4.4, 빠진 이름은 공칭으로 채움, `source.kind:"preview"`), `C/options.json`(유효 geom options), `C/view_options.json` |
| GV_RUN | kind별 preview 명령, `{out_dir}`=`C/out`, `{nominal_manifest}`=`S/native/view/view_manifest.json`(있을 때), `{tag_dir}`=`S/native/tag`, `{fixed_dir}`=`S/native/fixed`, timeout = `fe=off`면 `timeout_s.preview` 아니면 `preview_fe` |
| GV_REGISTER | 판정(아래) → artifacts `GEOM_PREVIEW_GLB`·`GEOM_PREVIEW_FE_GLB`(있을 때)·`GEOM_PREVIEW_MANIFEST` 등록, `geom_previews` 행 갱신 |

판정(GE §5.4 출력 파일 우선 규칙의 변형): `preview_manifest.json`이 있고 `status ∈ {OK, FAIL}`이며 FAIL의 category가 `VIEW`·`INPUT`·`INTERNAL`이 아니면 **작업 SUCCEEDED**(결과 FAIL도 성공, GV-10) → `geom_previews.status = DONE`, `result_status`·`code`·`category` 기록, 캐시 유효. 그 밖(manifest 없음·시간 초과 `VIEW_PREVIEW_TIMEOUT`·`VIEW_*`·내부 오류)은 작업 FAILED → `geom_previews.status = FAILED`(캐시로 쓰지 않음, 다음 요청 때 새로 실행).

**캐시 키** = sha256(정규 JSON — 키 정렬·공백 없음·float는 `repr(float(v))`):
`{param_set_id, kind, prep_digest, view_tess, values(대표 파라미터 전부, 빠진 값은 공칭), fe, engine_version}`
- `prep_digest` = `prep.json`의 입력 sha256들 + `tag_options_sha256` + 유효 geom options 전체 sha256(검사 기준이 바뀌면 FE 결과가 바뀜) + (쉘) `fixed_digest`.
- `engine_version` = 워커가 보고한 현재 paicad 버전(`worker_heartbeats.resources.paicad_version`, 환경 점검 `paicad_version` 결과). 모르면 캐시 조회를 하지 않고 항상 새 작업.

**동시·중복 규칙**

1. 같은 키가 DONE이면 작업 없이 즉시 반환(`cache_hit: true`, `last_access_at` 갱신).
2. 같은 키가 QUEUED·RUNNING이면 그 미리보기를 반환(작업 중복 생성 없음).
3. 새 요청 시 **같은 사용자·같은 세트의 QUEUED(아직 시작 안 한) 미리보기는 취소**(최신 값 우선, 취소된 행 `CANCELED`). RUNNING은 끝까지 둔다.
4. 사용자별 QUEUED+RUNNING ≥ `max_queued_per_user`면 429 `PREVIEW_BUSY`.
5. R3-4(정리 작업 중 작업 생성 409)·보관 Study 409는 그대로 적용.

### 6.5 API(`backend/openapi.json` 갱신 — Backend)

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `GET /param-sets/{id}/view` | 로그인 | – | `GeomView` | 404 |
| `POST /param-sets/{id}/previews` | power | `{values: {name: number}, fe?: "off"\|"check"}` | 200 `GeomPreview`(캐시 적중) \| 202 `GeomPreview`(QUEUED/RUNNING, `job_id`) | 409 `VIEW_NATIVE_ONLY`·`GEOM_PREP_STALE`·`GEOM_NATIVE_UNAVAILABLE`·`VIEW_UNAVAILABLE`(`features.geometry_view[_shell]=false`)·`STUDY_CLEANUP_RUNNING`, 422 `INPUT_INVALID`(모르는 이름·비유한 값, `loc:["values", name]`), 429 `PREVIEW_BUSY` |
| `GET /previews/{preview_id}` | 로그인 | – | `GeomPreview` | 404 |
| `GET /artifacts/{id}/media` | 로그인 | – | GLB(`model/gltf-binary`, Range 지원 — phase3 §15.4 규칙) | 404, 410 `ARTIFACT_EXPIRED`(캐시 삭제됨) |
| `GET /artifacts/{id}/content` | 로그인 | – | manifest JSON | 404, 410 `ARTIFACT_EXPIRED` |

```jsonc
// GeomView
{"param_set_id":"p1","kind":"solid","status":"READY|MISSING|FAILED","reason":null,
 "glb_artifact_id":"a1","manifest_artifact_id":"a2","tess":{"linear_mm":0.1,"angular_deg":20.0},"engine_version":"0.9.0",
 "available":true,"preview_available":true}           // available = features.geometry_view[_shell]
// GeomPreview
{"id":"gp1","param_set_id":"p1","job_id":"j1","status":"QUEUED|RUNNING|DONE|FAILED|CANCELED|EXPIRED","cache_hit":false,
 "values":{"CUSH_L_THK_1":12.9},"fe":"off",
 "result_status":"OK|FAIL|null","code":null,"category":null,"message_ko":null,     // message_ko = code→한국어 매핑(GE §6.5·SM §6.7·§5.5)
 "fe_status":null,"fe_code":null,
 "glb_artifact_id":"a3","fe_glb_artifact_id":null,"manifest_artifact_id":"a4",
 "timing":{"total_s":2.1},"created_at":"…","finished_at":"…"}
```

- 화면 폴링: `GET /previews/{id}` 0.5 s 간격(실행 중), 종료 상태에서 멈춤.
- `ParamSet` 응답 `native`에 `view_status`(READY|MISSING|FAILED) 추가(선택 필드).

### 6.6 캐시 정리(플랫폼 임시 산출물)

- 위치 `<study>/_cache/geom_preview/`. **사용자 산출물이 아니다**: 입력(세트·값·버전)에서 언제든 재생성되며 고유 데이터가 없다. 그래서 `_backup` 이동 대신 삭제한다(GV-8). `_cache/` 밖에는 이 규칙을 쓰지 않는다.
- 워커 housekeeping(`cache.purge_interval_h`마다): ① `last_access_at < now − retention_days`인 DONE·FAILED·CANCELED 항목 삭제 ② AI 루트 전체 캐시 합계 > `max_total_bytes`면 `last_access_at` 오래된 순으로 삭제. QUEUED·RUNNING 항목과 그 폴더는 건너뜀. 삭제 = 폴더 실경로가 `<study>/_cache/geom_preview/` 아래이고 링크·reparse point가 없는지 확인 후 제거, `artifacts` 행 삭제, `geom_previews.status = EXPIRED`(행 유지 — 요약만).
- STUDY_STORAGE_SCAN은 `_cache/`를 총량에 "플랫폼 임시(자동 정리)" 1줄로 포함하되 정리 범주(phase3 §5.5, 6개 고정)에는 넣지 않는다. Study 보관·삭제 정책은 기존 그대로.

### 6.7 DB — migration `0016_geom_view`(head 0015 → 0016)

| 대상 | 변경 |
|---|---|
| `jobs` | `lane` CHECK에 `'PREVIEW'` 추가. `ux_jobs_study_type_active` WHERE에 `AND job_type <> 'GEOM_PREVIEW'`(기존 제외 조건 유지) |
| `artifacts` | kind CHECK에 5종(§2.3) 추가 |
| `geom_previews`(신규) | `id UUID PK, study_id FK, param_set_id FK, cache_key CHAR(64) NOT NULL, job_id FK NULL, created_by, status VARCHAR(12) CHECK(QUEUED,RUNNING,DONE,FAILED,CANCELED,EXPIRED), fe VARCHAR(8), values JSONB, engine_version VARCHAR(32), result_status VARCHAR(8) NULL, code VARCHAR(64) NULL, category VARCHAR(16) NULL, fe_status, fe_code, glb_artifact_id, fe_glb_artifact_id, manifest_artifact_id, bytes BIGINT, timing JSONB, created_at, finished_at, last_access_at`. 부분 unique `(cache_key) WHERE status IN ('QUEUED','RUNNING','DONE')`, 인덱스 `(created_by, status)`, `(last_access_at)` |

`values`는 파라미터 이름→숫자(수치 요약)이며 파일 본문이 아니다.

### 6.8 시험(플랫폼)

- `backend/tests/fake_tools/fake_paicad`에 `view export`·`view preview`·`shell view …` 추가: 작은 합성 GLB(삼각형 2개 바디 2개)·manifest를 쓰고, `FAKE_PAICAD_FAIL=view_preview:GEOM_FEATURE_COLLISION`이면 manifest FAIL(종료코드 10), `…:VIEW_TOO_LARGE`면 14, `FAKE_PAICAD_SLEEP_S`로 시간 초과 흉내.
- 시험: 캐시 적중·중복 반환·QUEUED 취소·429·레인 동시 수·전역 슬롯 점유 중에도 미리보기 실행·FAIL 결과 캐시·인프라 실패 비캐시·housekeeping 삭제 범위(경로 탈출·링크 거부)·410.

---

## 7. 화면(Impl-Frontend)

### 7.1 의존·번들

- `three`를 `dependencies`에 **정확 버전 고정**(계약 반영 시점 최신 안정판, `package-lock.json` 포함), `@types/three`는 devDependencies. 사용 모듈 = `three` 코어 + `three/examples/jsm/loaders/GLTFLoader.js`·`controls/OrbitControls.js`·`renderers/CSS2DRenderer.js`. `DRACOLoader`·`KTX2Loader`·`RGBELoader` 등 디코더·외부 파일을 요구하는 모듈 금지.
- **동적 import**로 3D 패널을 열 때만 적재(`ResponsePlot3D`의 plotly와 같은 방식) → 별도 청크. 첫 화면(`index-*.js`) 증가 ≤ 20 KB(min) 목표.
- 번들 영향 기록: Impl-Frontend가 `scripts/build-frontend-dist` 후 three 청크 크기(min·gzip)와 `index` 청크 증감을 커밋 본문에 적고 Plan이 이 문서 변경 메모에 옮긴다. 예상 three 청크 ≈ 0.6~0.8 MB(min). `vite.config.ts`의 `chunkSizeWarningLimit`(600)는 바꾸지 않는다(경고만, plotly 선례).
- 네트워크: GLB·manifest는 `/physicsai/api/artifacts/…`로만 받는다. 외부 URL·CDN·폰트·환경맵 요청 0건(V-GV-11). 웹 워커 미사용.

### 7.2 배치(④ 세트 상세, native만)

기존 피처 표(GE §8) 오른쪽의 PNG 영역을 **[3D | 그림] 2단 전환**으로 바꾼다(기본 3D, WebGL 불가·`view.status ≠ READY`·`available=false`면 그림). 새 화면·새 메뉴 없음.

| 요소 | 내용 |
|---|---|
| 3D 패널 | 회전·이동·확대(OrbitControls, up = Z), [맞춤] 버튼 1개, 바디 목록 체크박스(표시/숨김) |
| 표 → 3D | 행 선택 시 `parameter`가 같은 피처의 `moving` 면 주황·`fixed` 면 파랑(PNG와 같은 색), 나머지 회색 반투명, 치수선(`p0`–`p1` 선 + 양끝 표시 + 라벨 "12.5 mm", CSS2D) |
| 3D → 표 | 면 클릭(raycast → 삼각형 → `_FACE_ID`) → 그 면을 쓰는 피처의 행 선택·표 스크롤. 여러 피처가 같은 면이면 작은 선택 목록(행 이름) 표시. 피처 없는 면 클릭은 선택 해제 |
| 쉘 | 양면 렌더, 고정 클러스터 = 파랑 원(중심·반경), `BEAD_FIXED_OVERLAP` 행은 기존 배지 유지 |
| PROP(3S) 행 | 3D 대응 없음 — 선택해도 하이라이트 없음, 패널에 "3D 대응 없음(쉘 두께)" |

### 7.3 미리보기

| 요소 | 내용 |
|---|---|
| 값 입력 | 선택 행에 숫자 입력 + 슬라이더. 슬라이더 범위 = `feasible`(없으면 `range`), 그 위에 `range`(사용자 범위) 띠와 `feasible.source`("envelope 측정"/"추정") 표시. `feasible` 밖 값은 입력 허용 + 경고 문구("모핑 가능 범위 밖 — 실패할 수 있음") |
| 실행 | **[미리보기] 버튼 1개**(슬라이더 이동만으로는 요청하지 않음), 옆에 체크 "FE 메시·검사 포함"(`fe=check`, 기본 끔, "느림" 안내). 여러 행 값을 바꾼 뒤 한 번에 실행 가능, [공칭으로] 버튼 |
| 진행 | 대기/실행 중 표시(경과 초), 새 요청은 이전 대기 요청을 대체(§6.4-3) |
| 결과 OK | 공칭 = 회색 반투명(opacity 0.25), 변경 형상 = 불투명 + 변위 색 맵(`_DISP_MM`, 0~max 범례 mm), 치수선은 미리보기 값. FE 포함이면 [형상 \| FE 메시] 전환, FE는 요소 엣지 선 + 노드 변위 색 |
| 결과 FAIL | 패널 위 배지(category 배지 문구 = GE §8 일괄 예측 표와 같은 묶음 + `VIEW`·`FIXED`) + `message_ko`. `failure.features` 피처 면은 빨강, `failure.clusters`는 빨강 원, `failure.points`는 빨강 점. update FAIL이면 공칭만 표시. FE FAIL이면 형상은 표시하고 FE 탭에 사유 |
| 작업 실패 | "미리보기를 만들지 못했습니다 — {사유}" + [다시] |

### 7.4 WebGL 미지원·성능

- 시작 시 WebGL2 → WebGL1 컨텍스트 생성 시도, 실패면 그림 탭 고정 + 문구 "이 환경에서는 3D 보기를 쓸 수 없습니다(WebGL 미지원) — 그림으로 표시합니다". 미리보기는 결과 수치(상태·코드·최대 변위)만 표로 표시.
- 컨텍스트 손실(`webglcontextlost`) 시 같은 대체. 패널을 닫으면 geometry·material·renderer `dispose()`.
- 렌더는 요청 시(onDemand — 조작·데이터 변경 때만), 픽셀 비 ≤ 2.
- jsdom 시험: three를 적재하지 않고 선택 상태·manifest 해석(행↔면 매핑, 슬라이더 범위, 실패 표시)을 순수 함수로 분리해 시험. 목(`dev:mock`)은 작은 합성 GLB(≤ 100 KB) + manifest 1쌍과 성공·실패 미리보기 응답.

---

## 8. 단계별 산출물·완료 기준

개발 환경 골든 = GE §9 (a) 가상 쿠션, SM §9.1 가상 판금 `SM1`(build123d 변형형이 정답). 저장소에 GLB·STEP·메시 파일을 넣지 않고 시험이 생성한다(목 GLB 1개 제외 — 프런트 fixture, ≤ 100 KB).

| 단계 | 산출물 | 완료 기준 |
|---|---|---|
| **GV-1 공칭 뷰(솔리드)** | `paicad view export`, `paicad.view.{gltf,manifest}`, `kernel` 테셀레이션·엣지·투영 | 가상 쿠션: ① **face_id 정확** — 모든 삼각형 중심 ↔ `_FACE_ID` B-rep 면 거리 ≤ `linear_mm` + 0.01 mm, 다른 면이 더 가까운(> 0.01 mm 차) 삼각형 0개, 모든 면에 삼각형 ≥ 1(퇴화 면은 `VIEW_FACE_EMPTY`), `faces[].tri` 구간 = `_FACE_ID` 연속 구간 ② **치수 값 = extract 공칭**(`dimension.value == features.nominal`, float 동일) ·`geom_len` 오차 ≤ tol(구배 피처는 `VIEW_DIM_APPROX`) ③ glTF 검증(구조·정렬·accessor min/max — 시험 내 검사 함수) ④ 2회 실행 바이트 동일 ⑤ 상한을 작게 주면 `VIEW_COARSENED`/`VIEW_TOO_LARGE` |
| **GV-2 플랫폼·뷰어(공칭)** | NP_VIEW, artifacts·`GET /view`, migration 0016(artifacts·lane), 뷰어(표↔면·치수선·바디 토글·그림 전환·WebGL 대체), three 번들·크기 기록 | fake_paicad로 세트 준비 → `view_status READY`·artifact 2개, NP_VIEW 실패해도 세트 등록 성공·경고, 프런트 시험(행 선택 → 하이라이트 면 집합, 면 → 행, 다중 피처 면 목록, PROP 행 대응 없음, WebGL 불가 → 그림), 빌드본 외부 URL 0건 |
| **GV-3 미리보기(update)** | `paicad view preview`(fe off), `GEOM_PREVIEW`·레인 PREVIEW·캐시·`geom_previews`·API·housekeeping, 화면 미리보기·겹쳐 보기·색 맵·실패 표시 | 가상 쿠션 변형형(두께 +10%, 구멍 위치 +3 mm, 반경 +10%): ① **미리보기 GLB ↔ build123d 변형형** 정점 거리 최대 ≤ `linear_mm` + 0.01 mm, 변형형 표면 표본점 ↔ GLB 최대 ≤ 같은 값(양방향) ② `by_face` 이동 면 `max` = |Δ| ± 1e-3 mm, 고정 면 0 ③ preview B-rep = `paicad update` 단독 실행 `sample.brep`와 같은 형상(면별 거리 0) ④ 충돌 값 → `status FAIL`·`GEOM_FEATURE_COLLISION`·`failure.features` 두 피처, 작업 SUCCEEDED·캐시됨 ⑤ **속도**: 단일 파라미터 fe off 전체(프로세스 시작 포함) 가상 쿠션 목표 ≤ 5 s(개발 PC, `timing.total_s` 기록), CI 시험 한도 15 s ⑥ 플랫폼 §6.8 시험 통과 |
| **GV-4 FE 미리보기** | `--fe morph\|check`, `preview_fe.glb`, 화면 FE 탭 | FE GLB 노드 좌표 = `paicad morph` 단독 `morphed.inc` 좌표(바이트 비교 아님, 수치 ≤ 1e-6 mm), 외피 삼각형 수 = tag 외피 수, `_DISP_MM` = 노드 이동 크기, 품질 실패 값 → `fe.code GEOM_QUALITY`·형상 GLB 유지, 미리보기 폴더에 include 없음, 속도 목표(가상 쿠션 ≤ 30 s) 기록 |
| **GV-5 쉘** | `paicad shell view export/preview`(+FE), NP_VIEW 쉘 분기, 화면 쉘 표시 | `SM1`: GV-1·GV-3·GV-4 기준을 쉘에 적용(깊이 ±10%·위치 ±3 mm·폭 ±10% 변형형), 고정 클러스터 = `shell_scan` 클러스터, 침범 값 → `SHELL_FIXED_REGION_VIOLATION`·`failure.clusters`, FE GLB 삼각형 수 = quad×2 + tri |
| 현장 인수 | 실물 세트로 NP_VIEW·미리보기 실행 | 실물 쿠션·chassis_rear: 삼각형 수·GLB 크기·`coarsened`·`timing` 수치와 화면 확인 결과(face 하이라이트 일치 여부)만 회신(형상 파일 반출 없음) |

순서: GV-1 → GV-2 → GV-3 → GV-4, GV-5는 GV-3 이후 병행 가능(SM 4C-1 완료 전제).

---

## 9. Verifier 체크리스트(V-GV-*)

- V-GV-1 기존 동결 보호: 솔리드·쉘 기존 명령 인자·보고 스키마·시험 무수정 통과, `options.json`에 뷰 키 없음(`view_options.json` 분리).
- V-GV-2 GLB 구조: glTF 2.0·확장 없음·4바이트 정렬·accessor min/max, 바디별 노드·`.edges` 노드, `_FACE_ID` 삼각형 내 동일·면 간 정점 비공유·오름차순 연속, `faces[].tri` 일치, mm·Z-up 명시.
- V-GV-3 face_id 정확(§8 GV-1 ①), 퇴화 면 경고.
- V-GV-4 치수: `dimension.value` = features 공칭(공칭 뷰)·입력 값(미리보기), kind별 두 점 정의, `VIEW_DIM_APPROX`.
- V-GV-5 결정성: export GLB·manifest, preview GLB·manifest(`timing` 제외) 2회 바이트 동일.
- V-GV-6 미리보기 일치: preview 형상 = `paicad update` 단독 결과, FE 좌표 = `paicad morph` 단독 결과, 변형형 정답 비교(§8 GV-3 ①②).
- V-GV-7 미리보기 안전: 미리보기 폴더에 `.inc`·`files/`·`--out-inc` 산출 없음, 실패 코드 전달(GE §6.5·SM §6.7 코드 그대로), update FAIL 시 GLB 없음·FE FAIL 시 형상 GLB 있음.
- V-GV-8 크기·LOD: `max_triangles`·`max_glb_bytes` 초과 → 거칠게 재시도·`VIEW_COARSENED`·최종 `VIEW_TOO_LARGE`(14), 미리보기는 `nominal_ref.tess` 사용.
- V-GV-9 독립성·커널: `kernel/` 밖 OCP import 0, 새 런타임 의존 없음(pyproject 의존 목록 불변), 플랫폼 import·파일명 하드코딩 없음, 메시지 영문, 변경마다 `__version__`·CHANGELOG(GE V-GE-11·13·14·19).
- V-GV-10 플랫폼 작업: NP_VIEW 실패 = 경고·작업 계속, 레인 PREVIEW가 전역 슬롯 점유 중에도 실행·`max_concurrent` 준수·허용 명령 외 거부, 캐시 키 구성(값·fe·버전·prep·옵션 변경 시 다른 키), 적중·중복·QUEUED 대체·429, FAIL 결과 캐시·인프라 실패 비캐시, `ux_jobs_study_type_active` 제외, migration 0016.
- V-GV-11 프런트: three 정확 버전 고정·lock 포함, 동적 import 별도 청크, `frontend-dist/`에 외부 URL(`http://`·`https://` 외부 호스트, CDN) 0건, 금지 로더 미사용, 번들 크기 기록 존재, 빌드본 최신(test-all).
- V-GV-12 화면: 행↔면 양방향 선택, 바디 토글, 슬라이더 범위 = feasible·range 띠·범위 밖 경고, [미리보기] 버튼으로만 요청, 겹쳐 보기·색 맵 범례, 실패 배지·한국어 사유·빨강 표시, WebGL 불가·컨텍스트 손실 → 그림 대체, PNG 유지.
- V-GV-13 캐시 정리: 기간·총량 삭제, 활성 항목 보호, `_cache/geom_preview/` 밖·링크 경로 거부, artifacts 삭제·`EXPIRED`·410, 정리 범주 6개 불변, 사용자 산출물(`_cache/` 밖) 삭제 0건.
- V-GV-14 쉘: 양면, 고정 클러스터 표시, `SHELL_FIXED_REGION_VIOLATION` 전달·클러스터 강조, FE 삼각 분할 규칙.

---

## 10. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| 대형 모델(실물 chassis 곡면·작은 필렛 다수)로 삼각형·GLB 과대 | 브라우저 느림·메모리, artifact 상한 초과 | `max_triangles`·`max_glb_bytes`·자동 거칠게(LOD), onDemand 렌더, 현장 수치 회신으로 기본값 조정 |
| 사내 PC WebGL 미지원·원격 데스크톱 소프트웨어 렌더 | 3D 불가·매우 느림 | PNG 대체 유지, 미리보기 결과 수치 표시, 컨텍스트 손실 처리 |
| 미리보기와 DOE가 같은 PC CPU 공유 | DOE 지연·미리보기 수 초 목표 미달 | `max_concurrent` 1·`threads` 2 기본, 레인 분리(전역 슬롯 대기 없음), `timing` 기록(§13 Q1) |
| OCP 적재 시간(Windows 1~2 s)·update 시간 | "수 초" 목표 초과 | 한 프로세스 실행, 캐시, 측정 후 상시 프로세스는 후속 검토(1차 비범위) |
| 테셀레이션 결정성(OCCT 버전·스레드) | 바이트 동일 시험 불안정 | 단일 스레드 고정, OCP 고정 버전(GE §5.1), 바이트 비교 실패 시 원인 기록 |
| float32 좌표 정밀도(큰 좌표값) | 미세 변위 표시 오차 | mm 좌표·조립 원점 근처 쿠션·chassis 크기(≤ 2 m)에서 ≈ 1e-4 mm, 변위는 `_DISP_MM`(계산값)으로 표시 |
| B-rep 면 위 변위가 "면 편차"라 미끄러짐을 0으로 보임 | 사용자가 이동량을 오해 | 범례에 "공칭 형상과의 거리" 명시, 실제 노드 이동은 FE 탭 |
| 미리보기 PASS ≠ DOE 샘플 PASS(fe off는 검사 없음) | 오해 | 화면 문구 "형상만 — 검사 생략", 검사 포함 옵션 |
| 캐시 디스크 증가 | 용량 | 기간·총량 삭제, 스캔에 표시 |
| three 버전 갱신·라이선스 | 유지보수 | 정확 고정, MIT 고지(프런트 제3자 고지에 추가 — Impl-Frontend) |

---

## 11. 구현 분해(파일 소유 비중첩)

| 담당 | 파일 |
|---|---|
| Impl-Geom | `packages/paicad/src/paicad/view/{__init__,gltf,manifest,preview}.py`, `kernel/` 테셀레이션·엣지·투영 함수, `cli.py` 하위 명령, `tests/test_view_*.py`, CHANGELOG·`__version__`(MINOR) |
| Impl-Backend | `config`·`TEMPLATE_SPECS`·`/status`, `physicsai_core/geometry/view_reports.py`(표준 라이브러리), 워커 PREVIEW 실행기·`steps/geometry_view.py`·NP_VIEW·housekeeping, `routers/param_sets.py`·`previews.py`·artifacts media, migration `0016_geom_view`, `fake_paicad` 확장, `backend/openapi.json` |
| Impl-Frontend | `frontend/package.json`(three·@types/three), `src/stages/stage4/geomview/{GeomViewer.tsx, viewerCore.ts, selection.ts, PreviewPanel.tsx, useGeomPreview.ts}`, 세트 상세 연결, 목·시험, `frontend-dist/` 재생성 |

---

## 12. 독립성·커널 격리·버전(GE 준용)

- GE §18 전부. 뷰 기능은 paicad MINOR 올림(새 출력), `view_manifest`·`preview_manifest` `schema_version` 1부터(GE §17.3 규칙), CHANGELOG "계약"에 `geometry-view.md §n`.
- 플랫폼 쪽 버전은 플랫폼 버전을 따르고 동작 변경은 `docs/decisions.md` 1줄(GE §17.5).

---

## 13. 미결 사항

| # | 질문 | 임시 결정(이 문서 기본값) |
|---|---|---|
| Q1 | DOE·일괄 예측이 같은 PC에서 돌고 있을 때도 미리보기를 허용하나, 동시 실행 수는? | 허용, 전역 `max_concurrent` 1·`threads` 2(설정 변경 가능) |
| Q2 | 캐시 보관 기본값(기간·총량)이 적절한가? | 7일·AI 루트 합계 2 GiB, LRU 삭제 |
| Q3 | ①-1·①-2 학습 단계 파라미터 표에도 3D 보기를 넣나? | 1차는 ④ 세트 상세만(학습 단계는 PNG 유지), 요청 시 같은 뷰어 재사용으로 후속 |

---

## 변경 메모

(구현 중 계약과 다르게 해야 하면 여기에 `GV-C1~`로 기록하고 Plan 확인을 받는다. three 청크 크기 측정값도 여기에 기록.)
