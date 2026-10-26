# 계약: native ①-1 추출 조건(찾을 종류·조건) + 리브 위치 파라미터(RIB_POS)

> 상태: 확정(2026-10-21, U1~U3 사용자 결정 반영). 상위 계약 [geometry-engine.md](geometry-engine.md)(GE) — 이 문서가 바꾸는 GE 규칙은 §2.3에 모았고 GE 변경 메모 GE-C16에 연결한다. 충돌 시 이 문서 우선.

## 0. 한 줄 요약

native 파라미터 추출(①-1 `TD_EXTRACT_PARAMS`·④ native 세트 등록 `PARAM_SET_NATIVE`) 전에 사용자가 **찾을 종류(그룹 체크)와 조건(mm 하한·범위)**을 정하면, paicad `extract`가 그 조건을 **탐색 단계에서 먼저 적용해 계산 자체를 건너뛰고**(결과 후처리 필터 아님) 선택 종류만 PNG를 그린다. 위치 그룹에는 새 자동 종류 **리브 위치 `RIB_POS_U`/`RIB_POS_V`**(인식된 리브의 측면+윗면 평행 이동)를 추가한다. 조건을 주지 않으면(필터 없음) 현재 동작·출력과 바이트 단위로 같다.

## 1. 목적·범위

### 1.1 배경(사용자 요청 2026-10-21)

- 원문: "파라미터 추출전 미리 종류를 선택하게 하자, 두께 위치, 필렛 (> 몇 mm 이상) 이렇게 조건 정해놓고 찾는범위를 좁히게 하는거지. 사용자가".
- 실물 쿠션 STEP에서 extract 5분+: 두께 후보 = 남은 평면 쌍 O(n²) × 쌍마다 겹침 판정(면당 12×12=144점 OCC 투영 2회 + 내부 판정 16점), 피처별 PNG(Python 소프트웨어 래스터, GE-C11 ⑥).
- 결과에 두께·필렛만 나오고 리브 위치 변수가 없음(현재 종류 9개 — GE §6.2, `features.py` `TYPE_ORDER`). 리브 측면 구배가 `extract.draft_max_deg`(3°)를 넘거나 리브 모서리에 블렌드(필렛)가 있으면 리브로 인식되지 않는다(§9 R1).

### 1.2 범위

- paicad `extract`: `options.json` `extract.filter`(§4) 해석, 조기 제외(§5), 통계 파일 `extract_stats.json`(§7), 새 종류 `RIB_POS_U`/`RIB_POS_V`의 인식·update·morph·check·sweep·view·map(§3).
- 플랫폼: ①-1 `TD_EXTRACT_PARAMS`(native·solid) job params `extract_filter`, API·openapi, 사용 조건 기록(`train_setups.extract_filter`), ①-2 "적용 조건" 표시, 진행 로그 요약(§6·§7). **④ native 세트 등록 `PARAM_SET_NATIVE`**(신규 등록·baseline 추가·from-train 승계, §6.7).
- UI: ①-1 `CadExtractCard`·④ `ParamSetDiscoverForm`(native일 때만) "찾을 종류" 체크 + "조건(선택)" 접힘(§8).

### 1.3 비범위

- **altair(SimLab·NX) 경로 전부 — 변경 금지(U3, 사용자 원문 "내가 요청하는건 native 한정이야. simlab은 건들지마")**: altair 추출·세트 등록 핸들러·워커·설정·화면 무변경. 유일한 접점은 요청 검증에서 `extract_filter`가 오면 422 `EXTRACT_FILTER_UNSUPPORTED`로 거부하는 것뿐이며 altair 화면에는 체크박스를 노출하지 않는다.
- 쉘(`kind=shell`) 비드 추출·쉘 세트 — 필터 거부(§6.3).
- 기존 native 세트의 추출 조건 변경(제자리 재추출) — 새 세트로 등록(§6.7).
- 블렌드(필렛) 붙은 리브·포켓 인식, 구배 큰 리브 전용 인식 규칙 — 후속 계약(§9 R1, 진단 카운터만 이번에 추가).
- PNG 래스터 자체의 속도 개선, 무필터 경로 성능 최적화 — 별도 진행 중인 features.py 성능 작업 소관.

### 1.4 원칙

- **사용자가 기준을 정함**: 서버·설정에 필터 기본값을 두지 않는다(`geometry.defaults.extract.filter` 불허, §6.4). UI 프리셋 기본 체크는 제안이며 사용자 확정(U1).
- **하위호환**: `extract.filter` 없음 = 현행 동작·출력 바이트 동일(GE §17.2 결정성). 새 종류 RIB_POS는 필터가 있을 때만 생성.
- **부분집합 불변식(EF-INV)**: 같은 `draft_max_deg`에서 필터 결과의 피처 집합은 "전 종류·조건 없음" 결과(이하 R_all)의 부분집합이다(§5.1). 필터는 인식 규칙을 바꾸지 않고 탐색 범위만 줄인다. 구배 허용각은 필터가 아니라 인식 조건이므로 이 불변식의 기준을 바꾼다(§4.3).

## 2. 용어·결정

### 2.1 용어

| 용어 | 뜻 |
|---|---|
| 그룹 | UI·job params의 사용자 용어 단위(5개, §3.1). 플랫폼이 종류(type) 목록으로 바꿔 paicad에 넘긴다 |
| 종류(type) | paicad 피처 종류(`THICKNESS` 등 11개 = 기존 9 + `RIB_POS_U/V`) |
| 조건 | 그룹별 선택 입력 수치(mm·mm²·°). 비면 미사용 |
| 조기 제외 | 조건으로 결과에 못 들어갈 후보를 비싼 계산(겹침 투영·내부 판정·PNG) 전에 버리는 것 |
| 개시 면 | 두께 쌍 탐색을 시작하는 면(조건을 만족하는 평면만, §5.2) |

### 2.2 결정 요약(EF-1~EF-10)

| ID | 결정 |
|---|---|
| EF-1 | 새 문서로 분리(GE는 1165줄, 같은 형식의 geometry-view·shell-morph 선례). GE에는 포인터·GE-C16만 |
| EF-2 | paicad 입력은 종류(type) 목록 + 조건, 그룹↔종류 매핑은 플랫폼(`physicsai_core/geometry/extract_filter.py`) — paicad 어휘 독립(GE §18) |
| EF-3 | 필터 의미 = R_all의 부분집합(EF-INV). 이름 번호 `k`는 필터 후 남은 것끼리 다시 매김(§5.1) |
| EF-4 | 조건은 계산 전에 적용(§5 표) — 선택 안 한 종류는 그 종류만의 비싼 단계 0회, 제외 피처 PNG 0장 |
| EF-5 | RIB_POS는 필터 있을 때만(`types`에 포함) 생성, `TYPE_ORDER` **맨 뒤**에 붙여 기존 종류의 순서·이름·그룹 id 불변 |
| EF-6 | RIB_POS 값·기준은 HOLE_POS 규칙 재사용: 값 = 바디 bbox 최소 기준 좌표, 이동 기준 `position_ref`(기본 `nearest_fixed`), 범위 절대 ±`position_range_mm`, envelope `--pos-steps` |
| EF-7 | 구배 허용각 `draft_max_deg`는 ①-1 "조건 > 고급"에 노출(기본 접힘, placeholder = 유효 기본값). 바꾸면 모든 종류 인식이 달라질 수 있다는 안내 문구 |
| EF-8 | 사용 조건은 `parameter_features.json` `filter`(정규화 사본)·`train_setups.extract_filter`(DB)·job params에 기록, ①-2 "적용 조건" 표시 |
| EF-9 | 통계 `extract_stats.json`은 필터 유무와 관계없이 항상 씀(새 파일 — 기존 파일 바이트 불변). 시간 필드만 비결정 |
| EF-10 | 재추출 시 기존 표 처리 = 확인 창 후 덮어쓰기(이전 표 백업, 기존 TX_PARSE 동작) — 사용자 확정 U2 |
| EF-11 | 적용 범위 = native 경로 전체(①-1 + ④ `PARAM_SET_NATIVE`), altair 경로 무변경(U3) |
| EF-12 | ④ 세트의 추출 조건은 세트 등록 때 1회 정하고 바꾸지 않음(파라미터 이름 집합·DOE·모델 일관성). 기록은 세트의 `native/extract/parameter_features.json` `filter`(DB 열 없음), baseline 추가는 같은 조건 강제 |

### 2.3 GE에서 바뀌거나 더해지는 규칙(이 문서 우선)

- GE §4.3: 피처 종류 약어에 `RIB_U`·`RIB_V` 추가. `parameter_features.json` 최상위 선택 키 `filter`(필터 있을 때만), `measure.method`에 `rib_center` 추가. `schema_version` 1 유지(선택 키 추가).
- GE §4.2·§5.3: `paicad extract` 출력에 `extract_stats.json` 추가(성공 판정 파일 아님).
- GE §4.9: `extract.filter` 선택 절(§4). `param_sets.geom_options`에 `extract.filter`가 오면 422 `GEOM_OPTIONS_INVALID`("추출 조건은 geom_options가 아니라 등록 요청의 extract_filter로 정합니다") — 조건은 검사 옵션이 아니라 등록 입력이다.
- GE §6.2: 종류 표에 `RIB_POS_U/V` 행(§3.2). 위치형(`POSITION_TYPES`) = HOLE_POS_U/V + RIB_POS_U/V(범위 mm·sweep mm 단계·`positions[]`).
- GE §6.3 단계 4: 리브 위치 이동은 `AXIS_SHIFT`와 같은 평면 내 이동으로 충돌 사전 검사 대상(리브 발자국 와이어 = 기존 `BOUNDARY_OVERLAP` 범위).
- GE §7.3.1: params `{cad_path, engine:"native", kind?, extract_filter?}`.
- GE §7.3.4: `POST /studies/{id}/param-sets`(native) 요청·params에 `extract_filter?`, NP_PREP 준비 피처 파일 생략 규칙·NP_EXTRACT·`add_baseline` 조건 승계(§6.7).

## 3. 종류 그룹·RIB_POS

### 3.1 그룹 ↔ 종류 매핑(UI 체크박스, 사용자 용어)

| 그룹 키(`groups[]`) | 화면 문구 | 종류(type) | 그룹 조건(§4.2) |
|---|---|---|---|
| `thickness` | 두께 | `THICKNESS`·`RIB_THICKNESS`·`POCKET_WIDTH` | 두께 범위, 최소 면 면적 |
| `height` | 높이·깊이 | `RIB_HEIGHT`·`POCKET_DEPTH` | 높이·깊이 범위 |
| `position` | 위치(구멍·리브) | `HOLE_POS_U`·`HOLE_POS_V`·**`RIB_POS_U`·`RIB_POS_V`(신규)** | 위치 대상 최소 크기 |
| `hole_radius` | 구멍 반경 | `HOLE_RADIUS` | 반경 하한 |
| `fillet` | 필렛 | `FILLET_RADIUS` | 반경 하한 |

- 매핑 단일 출처: 플랫폼 `physicsai_core/geometry/extract_filter.py`의 `GROUP_TYPES`(표준 라이브러리만). 프런트는 그룹 키·문구만 안다.
- 종류 표시 문구(프런트 `lib/geometry.ts`): `RIB_POS_U` "리브 위치 U", `RIB_POS_V` "리브 위치 V". `isPositionType`에 포함.

### 3.2 `RIB_POS_U`/`RIB_POS_V`(약어 `RIB_U`/`RIB_V`)

| 항목 | 규칙 |
|---|---|
| 인식 | GE §6.2 리브 인식(`_find_protrusions(+1)`: 윗면 cap·측면 lats·밑면 base)으로 **이미 인식된 리브만**. 밑면 법선이 전역 축 하나와 1° 이내(HOLE_POS와 같은 `cos1`)일 때만, U·V = 나머지 두 전역 축(오름차순, HOLE_POS와 같음). 축 a마다 **법선이 +a·−a 방향(각 ≤ `draft_max_deg`)인 측면이 각각 정확히 1개**면 그 축의 RIB_POS 1개 생성(L자 등 측면이 여러 개면 그 축은 생성 안 함, 통계 사유 `shape`) |
| 공칭 값 | 두 측면(+a·−a)의 중심 평면 좌표(각 면 centroid의 a 성분 평균) − 바디 bbox 최소[a]. HOLE_POS(`axis_point[a] − bb[a]`)와 같은 bbox 기준 |
| 피처 면 | `faces` = cap + lats 전부 + base, `moving` = cap + lats, `fixed` = base. `axis` 키 기록(HOLE_POS와 같음) |
| 범위 | 위치형 절대 mm: 공칭 ∓ `extract.position_range_mm`(기본 5.0), `feasible` 안으로 자름 |
| feasible | 리브 발자국(측면 bbox의 a 구간)에서 ±a 방향으로 (i) a에 수직이고 영역이 겹치는 평면(벽·다른 리브 측면)까지 거리 − `WALL_MIN_MM`(0.5) (ii) base 면 외곽 bbox 경계까지 거리 − 0.5 중 작은 값. `limited_by` = 그 면의 소유 피처(없으면 null) |
| update | `op = "AXIS_SHIFT"`(기존 값 재사용). Δ = 값 − 공칭, moving 면 집합 전부를 a 방향으로 Δ 평행 이동(`FaceMove.translate`에 누적 — 같은 샘플의 RIB_THICKNESS 측면 이동·RIB_HEIGHT 윗면 이동과 벡터 합). base 면 surface 불변·내부 와이어(발자국) 재계산(위상 보존 재구성, GE-C7). 적용 순서 = 평면 이동(THK·POCKET·RIB_T·RIB_H) 뒤, 구멍·필렛과 같은 단계(GE §6.3 단계 4 위치 처리)에서 HOLE_POS와 같은 반복 규칙 |
| 위치 기준 | `position_ref`: `nearest_fixed`(기본) = a에 수직인 **이번 샘플에서 움직이지 않는 가장 가까운 평면**(리브 자신의 면 제외, 동률이면 면적 큰 면)까지 거리 유지 — 벽 두께가 바뀌어도 리브는 그 고정 면을 따른다. `proportional` = 바디 길이 비례. 고정 면이 없으면 경고 `POS_REF_NO_FIXED_FACE` + 비례(HOLE_POS와 같음) |
| update.json | `positions[]`에 HOLE_POS와 같은 키(`name, body, axis, mode, ref_face, expected_measured`) — 스키마 변경 없음 |
| 충돌 사전 검사 | 기존 `collision.py` `BOUNDARY_OVERLAP`(base 면 위 발자국 와이어 ↔ 구멍·포켓 입구·다른 리브 발자국·외곽 와이어)·`WALL_PENETRATION`(측면 ↔ 마주 보는 벽) 그대로 적용 → `GEOM_FEATURE_COLLISION`(종료 10) |
| morph | 새 규칙 없음. cap·lats 노드 = 면 UV 대응, base 면은 "내부 와이어가 이동한 면" → GE §6.4 1. 대체 규칙(면 경계 변위 경계조건 조화 보간 → 투영) |
| check (a) 재측정 | `measure.method = "rib_center"`: 모핑 메시에서 +a·−a 측면 노드로 평면 맞춤 → 중심 평면 좌표 − 모핑 바디 bbox 최소[a], 비교 대상 = `positions[].expected_measured`(HOLE_POS와 같음) |
| 대칭 그룹 | GE §6.2 MIRROR 규칙 그대로(같은 종류끼리, 공칭 차 ≤ tol). HOLE_POS와 같이 별도 처리 없음 |
| envelope | `paicad morph --sweep`의 위치형 단계 `--pos-steps`(mm) 대상, 행 `unit: "mm"` |
| 다중 baseline map | `paramap` 종류 범주 `position`(HOLE_POS와 같음) |
| view | `view_manifest.json` 치수선 = 두 측면 중심 평면 ↔ `ref_face`(공칭은 bbox 최소면) a 방향 선분. PNG 치수선 같은 규칙 |
| 순서·이름 | `TYPE_ORDER` 맨 뒤(`… FILLET_RADIUS, RIB_POS_U, RIB_POS_V`), 이름 `<COMP>_RIB_U_<k>`·`<COMP>_RIB_V_<k>` |

`POSITION_TYPES` 상수는 paicad 안 한 곳(`features.py`)에서만 정의하고 `update`·`sweep`·`view/manifest`·`paramap`이 import한다(현재 `view/manifest.py`에 중복 정의 — 통합).

## 4. `options.json` `extract.filter`(paicad 입력)

### 4.1 스키마

```json
"extract": {
  "draft_max_deg": 3.0, "overlap_min": 0.5, "range_ratio": 0.05, "sample_grid": 12, "position_range_mm": 5.0,
  "filter": {
    "types": ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH", "HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V", "FILLET_RADIUS"],
    "thickness_mm": {"min": 2.0, "max": 30.0},
    "height_mm": null,
    "face_area_min_mm2": 50.0,
    "position_min_size_mm": 3.0,
    "hole_radius_min_mm": null,
    "fillet_radius_min_mm": 1.0
  }
}
```

- `filter` 없음 또는 `null` = 필터 없음(현행, RIB_POS 미생성).
- 키는 모두 필수가 아니다(빠진 조건 키 = null = 미사용). `thickness_mm`·`height_mm`는 `{min, max}` 각각 null 허용(한쪽만 지정 가능).

### 4.2 조건 정의·적용 대상

| 키 | 단위 | 적용 종류 | 남기는 조건 |
|---|---|---|---|
| `thickness_mm` | mm | THICKNESS·RIB_THICKNESS·POCKET_WIDTH | min ≤ 공칭 ≤ max |
| `face_area_min_mm2` | mm² | THICKNESS·RIB_THICKNESS·POCKET_WIDTH | 쌍의 두 면 면적 모두 ≥ 값 |
| `height_mm` | mm | RIB_HEIGHT·POCKET_DEPTH | min ≤ 공칭 ≤ max |
| `position_min_size_mm` | mm | HOLE_POS_U/V: 구멍 지름(2r) ≥ 값 · RIB_POS_U/V: 리브 윗면의 밑면 평면 내 bbox 두 변 중 짧은 변 ≥ 값 | |
| `hole_radius_min_mm` | mm | HOLE_RADIUS | r ≥ 값 |
| `fillet_radius_min_mm` | mm | FILLET_RADIUS | r ≥ 값(원통 반경·토러스 작은 반경) |

- 경계값 비교는 반올림 전 값으로 하고 `≥`·`≤`는 포함(허용오차 1e-9 mm).
- `types`에 없는 종류의 조건은 효과 없음(플랫폼이 정규화 때 제거, §6.2).

### 4.3 고급: 구배 허용각

- 기존 키 `extract.draft_max_deg`(GE §4.9, 범위 (0, 45))를 그대로 쓴다(필터 절에 중복 키 두지 않음). ①-1 UI "고급"에서 바꾸면 플랫폼이 이 키에 쓴다.
- 인식 조건이므로 필터 없이도 의미가 있고 부분집합 불변식의 기준(R_all)을 바꾼다. 화면 안내: "리브 측면 구배가 이 값보다 크면 리브로 인식되지 않습니다. 바꾸면 모든 종류의 인식 결과가 달라질 수 있습니다."

### 4.4 검증(paicad, `options.load`)

위반 → `GEOM_INPUT_INVALID`(종료 3, 영문 메시지에 위반 키 목록): `types` 빈 배열·중복·모르는 종류 이름, `filter`·범위 객체 안 모르는 키(GE-C10 모르는 키 거부), 수치가 유한 양수 아님(`min`은 ≥ 0 허용), `min > max`. update·morph·check·tag도 같은 `options.json`을 읽을 수 있으므로 `filter`를 검증만 하고 무시한다.

## 5. 조기 제외(속도 계약)

### 5.1 부분집합 불변식 EF-INV

필터 F의 결과 피처 = R_all(같은 CAD·같은 나머지 옵션, `types` = 전 11종·조건 없음)의 피처 중 `type ∈ F.types`이고 §4.2 조건을 만족하는 것과 정확히 같다(비교 = 종류·면 서명·공칭·`range`·`feasible.min/max`·`draft_deg`·`ref`). 달라도 되는 것: 이름 번호 `k`(남은 것끼리 재번호), 그룹 id(남은 그룹끼리 재번호), `feasible.limited_by`(소유 피처가 제외되면 null), 대칭 그룹 구성원(제외된 구성원은 빠지고 1개만 남으면 그룹 해제). R_all에서 RIB_POS 항목을 빼면 필터 없음 출력과 같다(`limited_by`가 RIB_POS를 가리키는 경우·최상위 `filter` 키 제외).

### 5.2 단계별 조기 제외

| 단계(현행 `recognize_body` 순) | 비용 | 조기 제외 규칙 |
|---|---|---|
| 원통·토러스 분류(구멍·필렛) | 낮음(위상·해석값) | HOLE_RADIUS·HOLE_POS·FILLET 중 선택된 것만 Feature 생성. r·지름 조건 미달은 생성 전에 버림. 셋 다 미선택이면 루프 생략 |
| 리브·포켓 위상 인식 | 낮음(위상) | THICKNESS·RIB_*·POCKET_* 중 하나라도 선택이면 **항상 실행**(리브·포켓 면 `claimed`가 두께 후보에서 빠지는 규칙을 지키기 위함 — EF-INV). 높이·깊이·위치 최소 크기 조건은 Feature 생성 전에 판정 |
| 리브 두께·포켓 폭 쌍 판정 | 중(쌍마다 겹침 투영) | 그 종류 미선택이면 쌍 판정 0회. 선택이면 값싼 기하 판정(반평행·재료 쪽·거리 `d`) 뒤 `thickness_mm` 범위 밖·`face_area_min_mm2` 미달 쌍은 **겹침 판정 전에** 버림 |
| 두께(남은 평면 상호 최근접 쌍) | **높음**(O(n²) 쌍 × 겹침 투영 2회 + 내부 판정) | 미선택이면 블록 전체 생략. 선택이면 (1) **개시 면** = 면적 ≥ `face_area_min_mm2`인 평면만. (2) 개시 면 a마다 값싼 기하 판정을 통과한 상대를 `d` 오름차순(동률은 현행 열거 순)으로 보며 겹침 판정 — 첫 통과가 a의 최근접 b. `d > thickness_mm.max`에 이르면 중단(a 출력 없음). (3) b가 조건(면적·`d ≥ min`) 미달이면 a 출력 없음. (4) 상호성 확인 = b에서 같은 방식으로 `d(a,b)`까지만 탐색. 작은 면은 개시 면이 아니며, 개시 면보다 가까운 상대로 나올 때만 판정된다(R_all과 같은 최근접 판정을 유지하면서 판정 횟수를 줄임). 쌍 판정 결과는 (작은 id, 큰 id)로 캐시해 쌍마다 최대 1회, 호출 인자 순서는 현행과 같게(면 순서 오름차순) |
| 대칭 그룹·feasible·range | 낮음 | 남은 피처에만 |
| PNG | **높음**(피처마다 래스터) | 남은 피처만 렌더. 남은 피처가 없는 바디는 삼각분할(`triangulate`)도 하지 않음. 제외 종류 PNG 0장 |

- 겹침 판정의 필요조건 사전 검사(평면 내 bbox 겹침 등, 보수적 여유)는 결과 불변일 때만 허용(성능 작업과 공유 규칙).
- 성능 작업이 무필터 경로에 같은 지연(lazy) 탐색을 먼저 넣으면, 필터는 개시 면 집합·중단 거리만 더한다. 어느 쪽이든 관측 기준은 §7 카운터와 V-EF-3.
- 필터로 피처가 0개면 기존 `GEOM_EXTRACT_EMPTY`(종료 13). 플랫폼 문구(필터 있을 때): "조건에 맞는 피처가 없습니다 — 찾을 종류·조건을 넓혀 보세요".

## 6. 전달 경로(플랫폼)

### 6.1 job params·API

- `POST /jobs` `TD_EXTRACT_PARAMS`(④는 §6.7): `TdExtractParams`에 선택 필드 `extract_filter`(생략 = 현행). 서버가 정규화한 값을 params에 기록.

```json
{"cad_path": "...", "engine": "native", "extract_filter": {
  "groups": ["thickness", "position", "fillet"],
  "conditions": {"thickness_mm": {"min": 2, "max": 30}, "face_area_min_mm2": 50, "position_min_size_mm": 3, "fillet_radius_min_mm": 1},
  "draft_max_deg": null}}
```

- 스키마(openapi `ExtractFilter`, extra 금지): `groups` = 위 5개 키 중 1개 이상·중복 없음, `conditions` = §4.2 키(모두 선택, null 허용), `draft_max_deg` = null 또는 (0, 45).
- 검증 오류 422 `EXTRACT_FILTER_INVALID`(problems `[{key, message}]`, 한국어): 그룹 0개 "찾을 종류를 하나 이상 고르세요", 음수·0 "0보다 큰 값을 넣으세요", min > max "최솟값이 최댓값보다 큽니다", 구배 범위 밖 "구배 허용각은 0°보다 크고 45°보다 작아야 합니다".
- 422 `EXTRACT_FILTER_UNSUPPORTED` "찾을 종류 선택은 native 솔리드 추출에서만 쓸 수 있습니다": 엔진 altair(요청 생략 시 `geometry.engine` 해석 결과 기준) 또는 `kind: "shell"`.
- `GET /train/setup`(`TrainSetup` 응답): `extract_filter`(정규화 사본 | null), `extract_summary`(§7.2 요약 | null) 추가.

### 6.2 정규화·options.json 작성(워커 `extract_native.tx_prep`)

1. `GROUP_TYPES`로 `groups` → `types`(표 §3.1 순서, 정렬 고정).
2. 선택하지 않은 그룹의 조건 키 제거, null 키 제거(정규화본 = 기록·표시 기준).
3. `X/options.json` = 유효 옵션(`geometry.defaults`) + `extract.filter`(types + 남은 조건) + `draft_max_deg`가 있으면 `extract.draft_max_deg` 덮어쓰기.
4. `extract_filter` 없으면 `extract.filter`를 쓰지 않는다(현행 파일과 같음).
5. 백업 목록(`run_paicad backup=`)에 `extract_stats.json` 추가.

### 6.3 우선순위

`extract_filter.draft_max_deg` > `geometry.defaults.extract.draft_max_deg` > paicad 기본(3.0). `extract.filter`는 job params(①-1 `TD_EXTRACT_PARAMS`·④ `PARAM_SET_NATIVE`)에서만 온다: `geometry.defaults.extract.filter`가 설정에 있으면 무시하고 `config.warnings` "geometry.defaults.extract.filter는 쓰지 않습니다 — 추출 조건은 추출·세트 등록 때 사용자가 정합니다". `param_sets.geom_options.extract.filter`는 422 `GEOM_OPTIONS_INVALID`.

### 6.4 기록·표시

- DB: `train_setups.extract_filter JSONB NULL`(정규화본, null = 필터 없음). migration = 구현 시 HEAD 다음 번호(현재 HEAD `0018_equiv_check` → `0019_extract_filter` 예정), 다운그레이드 정책 기존과 같음.
- TX_PARSE: `train_setups.extract_filter` 저장(필터 없으면 null로 덮어씀), job result `extract_summary`.
- 파일: `parameter_features.json` 최상위 `filter`(paicad가 사용값 사본: types·조건·`draft_max_deg`), `X/options.json`. ①-3 DOE는 `D/native/extract/` 복사본의 `filter`로 추적(새 메타 없음).
- ①-2 파라미터 표 머리줄: "적용 조건: 두께 2~30 mm · 면적 ≥ 50 mm² · 위치 최소 3 mm · 필렛 r ≥ 1 mm · 구배 3°(기본)" / 필터 없음이면 "적용 조건: 전체(조건 없음)". 선택 안 한 그룹은 "제외: 높이·깊이, 구멍 반경".

### 6.5 다른 조건으로 재추출

- 서버 동작은 현행 그대로: TX_PARSE가 표를 새로 쓰고 이전 `01_train/params.json`은 백업(phase2 TX_PARSE).
- UI: 파라미터 표가 있으면 실행 전 확인 창 "기존 파라미터 표(n개, 적용 조건: …)를 새 추출 결과로 바꿉니다. 직접 고친 범위·사용 여부는 새 표에 옮겨지지 않으며 이전 표는 백업됩니다. 계속할까요?" [바꾸기]/[취소]. (대안 = 이름·종류·공칭이 같은 행의 min·max·use 승계 — U2)

### 6.7 ④ native 세트 등록(`PARAM_SET_NATIVE`, U3)

| 경로 | 규칙 |
|---|---|
| 신규 `POST /studies/{id}/param-sets`(`engine:"native"`, solid) | 요청 선택 필드 `extract_filter`(§6.1과 같은 `ExtractFilter` 스키마·검증·422 코드). 서버가 정규화해 job params `{mode:"new", …, extract_filter}`에 기록. altair 요청에 오면 422 `EXTRACT_FILTER_UNSUPPORTED`(altair 처리 경로에 들어가기 전, 그 밖 altair 동작 불변). 쉘 세트도 같은 422 |
| NP_PREP | `extract_filter`가 있으면 프로젝트 폴더의 `parameter_features.json`·`parameter_extracted.xml`을 복사하지 않아 NP_EXTRACT를 **항상 실행**(로그 "추출 조건이 지정되어 준비된 피처 파일을 쓰지 않습니다"). 프로젝트 폴더 `parameters.json`도 쓰지 않고 features `range`로 표를 만든다(경고 `PARAMS_JSON_IGNORED` "추출 조건이 지정되어 폴더의 parameters.json 범위를 쓰지 않았습니다" — 조건으로 이름 집합이 달라져 `PARAM_FEATURE_MISMATCH`가 나는 것을 피함). `T/native/options.json`(유효 옵션)에 `extract.filter`·`draft_max_deg`를 §6.2와 같은 방식으로 씀(`tag` 절 sha256은 영향 없음 → STALE 판정 불변). 없으면 현행 |
| NP_EXTRACT | 위 options로 `paicad_extract`(out `T/native/extract`), 백업 목록에 `extract_stats.json`. 진행 요약은 §7.2와 같은 한국어 로그(작업 result `extract_summary`) |
| 기록 | 세트 조건의 단일 출처 = `S/native/extract/parameter_features.json` `filter`(paicad 사용값 사본). DB 열·migration 없음. `ParamSet` 응답 `native.extract_filter`(features JSON에서 읽은 정규화본 \| null), `GET /param-sets/{id}/features` 응답에도 `filter` |
| 조건 변경·재등록 | 기존 세트는 조건을 바꾸지 않는다: `native-prepare`(reprep)는 기존 extract를 재사용하므로 `extract_filter`를 받지 않음(오면 422 `EXTRACT_FILTER_INVALID` "등록된 세트의 추출 조건은 바꿀 수 없습니다 — 새 세트로 등록하세요"). 조건을 바꾸려면 새 세트로 등록(기존 세트·DOE·모델 불변, 사용자 산출물 삭제 없음) |
| baseline 추가(4B `add_baseline`) | 새 baseline의 NP_EXTRACT는 **세트 기준 baseline의 `filter`를 그대로** 쓴다(매칭 대상 종류 집합 일치). 요청에 `extract_filter`를 받지 않음(오면 422 `EXTRACT_FILTER_INVALID`). 기준 baseline에 `filter`가 없으면 새 baseline도 필터 없음 |
| ①→④ from-train | `D/native/extract/` 복사로 ①-1 조건이 그대로 승계(paicad 실행 없음, 변경 없음) |
| discover 화면 | `POST …/param-sets/discover`는 변경 없음(조건은 등록 요청에만) |

## 7. 진행 로그·리포트

### 7.1 `extract_stats.json`(paicad, 항상 작성)

```json
{"schema_version": 1, "engine": "native", "engine_version": "…", "filter_applied": true,
 "bodies": [{"body": "CUSH_L", "faces": 412, "planes": 300,
   "types": {
     "THICKNESS": {"selected": true, "initiators": 120, "pair_tests": 180, "kept": 12,
                   "excluded": {"face_area": 180, "thickness_range": 9, "not_mutual": 21}, "elapsed_s": 41.3},
     "HOLE_RADIUS": {"selected": false},
     "FILLET_RADIUS": {"selected": true, "candidates": 30, "kept": 4, "excluded": {"fillet_radius_min": 26}, "elapsed_s": 0.01}},
   "rib_rejects": {"cap_not_convex": 14, "lateral_not_plane": 6, "lateral_draft": 3, "base_mismatch": 2}}],
 "png": {"rendered": 20, "elapsed_s": 8.2},
 "elapsed_s": {"load": 3.1, "recognize": 60.2, "finalize": 1.0, "png": 8.2, "total": 72.5}}
```

- `selected: false` 종류는 후보 수를 세지 않는다(세는 것 자체가 비용). `pair_tests` = 실제 겹침 판정 호출 수(속도 시험 기준).
- `rib_rejects`: 리브 후보(윗면 후보 평면)가 탈락한 첫 사유별 수 — 실물에서 "리브 변수 없음" 원인 진단용(§9 R1). `selftest_report.json`에도 바디별 합계를 넣는다.
- 키 세부는 구현 기준. 플랫폼은 `types.*.selected/kept/excluded(합계)/elapsed_s`, `png`, `elapsed_s.total`, `rib_rejects`에만 의존. 시간 필드만 비결정(결정성 비교 대상 아님).
- stdout `PAICAD PROGRESS`는 종류 단계마다 1줄(영문, 예 `PAICAD PROGRESS 40 CUSH_L thickness: 180 tests, 12 kept`).

### 7.2 플랫폼 요약(TX_PARSE 로그·`extract_summary`)

- 작업 로그(한국어, 종류별 1줄): "두께: 판정 180 · 채택 12 · 제외 210(면적 180, 범위 9, 비상호 21) · 41.3초", "구멍 반경: 건너뜀(선택 안 함)", "하이라이트 PNG 20장 · 8.2초 · 전체 72.5초", 리브 후보 탈락이 있으면 "리브 후보 탈락 25(윗면 볼록 아님 14, 측면 곡면 6, 측면 구배 3, 밑면 불일치 2)".
- `extract_summary` = `{types:{<type>:{selected, kept, excluded}}, png_rendered, elapsed_s, rib_rejects}`(수치만, DB 규칙). `extract_stats.json` 없음(구버전 paicad·fake)이면 null, 경고 없음.

## 8. UI(①-1 `CadExtractCard`·④ `ParamSetDiscoverForm`, 후보 A — 필수 요소만)

- 표시 조건: 엔진 native이고 형상 종류 solid일 때만. altair·쉘이면 기존 화면 그대로(altair 화면·컴포넌트 무변경, U3).
- 공용 컴포넌트 `ExtractFilterFields`를 ①-1·④ 등록 폼이 같이 쓴다(아래 칸·문구 동일).
- "찾을 종류" 체크박스 한 줄: 두께 · 높이·깊이 · 위치(구멍·리브) · 구멍 반경 · 필렛. 0개면 실행 버튼 비활성 + "찾을 종류를 하나 이상 고르세요".
- "조건(선택)" 접힘 1개(기본 닫힘), 체크한 그룹 칸만 보임, placeholder "비우면 조건 없음":
  - 두께: "두께 범위 (mm)" [최소]~[최대], "최소 면 면적 (mm²)"
  - 높이·깊이: "높이·깊이 범위 (mm)" [최소]~[최대]
  - 위치: "최소 크기 (mm) — 구멍 지름·리브 폭"
  - 구멍 반경: "반경 하한 r ≥ (mm)"
  - 필렛: "반경 하한 r ≥ (mm)"
  - "고급" 소접힘: "구배 허용각 (°)" placeholder = 유효 기본값, §4.3 안내 문구
- 초기값(U1 확정): 그 Study의 `train_setups.extract_filter`(마지막 사용 조건)가 있으면 그것, 없으면 프리셋 = 다섯 그룹 모두 체크·조건 빈칸. ①-1·④ 모두 같은 규칙. native solid에서는 항상 `extract_filter`를 보낸다(모두 체크·빈칸 = R_all = 현행 + 리브 위치).
- ④ 세트 상세 피처 표 머리줄: "적용 조건: …"(§6.4 문구, `native.extract_filter`) + "조건을 바꾸려면 새 세트로 등록하세요". ④ 등록 폼에서 준비된 피처 파일이 있는 폴더를 고르면 안내 "추출 조건을 쓰면 준비된 피처 파일 대신 다시 추출합니다".
- 입력 검사는 §6.1 문구를 그대로 화면에서도 보여 준다. 재추출 확인 창 §6.5(U2 확정, ①-1만 — ④ 신규 등록은 기존 표를 덮지 않음). ①-2 "적용 조건" 줄 §6.4.
- 새 화면·시안 없음. `frontend-dist` 재생성 함께 커밋(AGENTS.md).

## 9. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 실물 리브가 모서리 블렌드(필렛)·큰 구배로 아예 리브로 인식되지 않으면 RIB_POS도 없음(구배각 노출만으로는 블렌드 리브 해결 안 됨) | `rib_rejects` 진단 카운터를 selftest로 현장 회신 → 사유가 블렌드면 블렌드 체인을 건너뛰는 리브 인식을 후속 계약으로 |
| R2 | 지연 탐색의 동률(1e-9) 처리·호출 순서 차이로 R_all과 결과 차이 → 부분집합 불변식·하위호환 바이트 깨짐 | V-EF-1·V-EF-2를 가상 쿠션 + 부하 합성 + 동률 합성(같은 거리 상대 2개)으로 시험 |
| R3 | features.py 동시 수정(성능 작업 진행 중) 충돌 | Impl-Geom은 성능 작업 병합 뒤 순차 착수(§11), 그 커밋의 결과를 새 골든 기준으로 삼음 |
| R4 | RIB_POS 이동 시 base 면 대체 규칙(조화 보간)에 의존 → 큰 이동에서 품질 미달·경계 편차 | envelope `--pos-steps`로 한계 측정, 기본 범위 ±5 mm·`feasible` 경고 |
| R5 | 조건을 좁히면 사용자가 필요한 변수를 놓침(예: 면적 하한이 얇은 벽 제외) | ①-2 "적용 조건"·제외 수 요약 표시, 재추출 경로 |
| R6 | 필렛 r 하한으로 작은 필렛을 빼도 형상에는 남아 update 위상 변화 위험은 그대로 | 정보 — 필터는 변수 선택일 뿐 디피처링 아님(GE §18.8 로드맵) |
| R7 | `extract_stats.json` 새 출력 → 출력 존재 시 종료 3 규칙 | 워커 백업 목록에 추가(§6.2-5), fake_paicad 동일 |

## 10. 검증 기준(V-EF-*)

- **V-EF-1 하위호환**: `extract.filter` 없는 `options.json`으로 가상 쿠션·기존 골든 extract → `parameter_extracted.xml`·`parameter_features.json`·PNG가 변경 전(성능 작업 병합 커밋) 출력과 바이트 동일, RIB_POS 없음. 플랫폼: `extract_filter` 생략 요청 → `X/options.json`에 `filter` 키 없음, 기존 ①-1 시험 무수정 통과.
- **V-EF-2 부분집합(EF-INV)**: 가상 쿠션·부하 합성에서 그룹 5개 단독·조건 6개 단독·조합 3가지 이상 → 결과 = R_all을 §5.1 비교 키로 거른 것과 정확히 같음. R_all에서 RIB_POS를 빼면 필터 없음 출력과 같음(§5.1 예외만). 동률 합성 케이스 포함.
- **V-EF-3 조기 제외**: `extract_stats.json`(또는 커널 호출 계수 대역) 기준 — THICKNESS 미선택 → 두께 `pair_tests` 0, RIB_THICKNESS·POCKET_WIDTH 미선택 → 그 쌍 판정 0, `face_area_min_mm2` → 면적 미달 면은 개시 면이 아님(`initiators` = 면적 이상 평면 수), `thickness_mm.max` → 개시 면별로 `d > max` 상대 판정 0, 필렛·구멍 조건 미달 Feature 미생성, 제외 종류 PNG 0장·남은 피처 없는 바디 `triangulate` 0회.
- **V-EF-4 RIB_POS 정답 비교**(build123d 가상 쿠션, 리브를 U·V로 ±2·±5 mm 옮긴 변형형 = 정답): update B-rep ↔ 정답 면별 최대 거리 ≤ 0.01 mm·부피 차 ≤ 0.1%, 모핑 경계 노드 ↔ 정답 ≤ 0.05 mm, check (a) `rib_center` 재측정 ≤ `param_abs_mm`, 반전 0. 추가: THICKNESS로 벽이 움직여도 `nearest_fixed` 고정 면 거리 유지, RIB_THICKNESS+RIB_POS 동시 변경, 리브 → 구멍 겹침·base 밖 이동 → `GEOM_FEATURE_COLLISION`, 측면 여러 개(L자) 리브 → 그 축 미생성, sweep `unit: "mm"` 행, 같은 입력 2회 `morphed.inc` 바이트 동일.
- **V-EF-5 속도**: 부하 합성(평면 ≥ 200개 바디 — 작은 보스·홈 격자 + 큰 두께 쌍 수 개) — `face_area_min_mm2`+`thickness_mm` 필터 시 두께 `pair_tests` ≤ 무필터의 50%, THICKNESS 미선택 시 0, PNG 장수 = 남은 피처 수. 시간은 기록만(판정은 호출 수로, CI 안정).
- **V-EF-6 검증·오류**: paicad 모르는 종류·키·빈 types·min>max·음수 → 종료 3 `GEOM_INPUT_INVALID`. 플랫폼 422 `EXTRACT_FILTER_INVALID`(problems 한국어)·`EXTRACT_FILTER_UNSUPPORTED`(altair·shell), `geom_options.extract.filter` 422 `GEOM_OPTIONS_INVALID`, `geometry.defaults.extract.filter` → `config.warnings` + 무시. 필터로 0개 → `GEOM_EXTRACT_EMPTY` + 필터 안내 문구.
- **V-EF-7 기록·표시**: 정규화(미선택 그룹 조건 제거) 후 params·`X/options.json`·features `filter`·`train_setups.extract_filter` 일치, `GET /train/setup` `extract_filter`·`extract_summary`, ①-2 "적용 조건" 문구, 재추출 확인 창, 로그 한국어 요약, fake_paicad가 `filter`를 반영(types 밖 피처 미출력)·`extract_stats.json` 작성.
- **V-EF-8 UI**: native solid에서만 체크·접힘 표시, 문구 한국어, 0개 선택 시 버튼 비활성, `frontend-dist` 최신.
- **V-EF-9 위치형 통합**: `POSITION_TYPES` 단일 정의, `paramap` 범주 position, view 치수선, 범위 절대 mm.
- **V-EF-11 ④ native**: 등록 요청 `extract_filter` → NP_PREP가 준비 피처 파일·`parameters.json` 미사용(`PARAMS_JSON_IGNORED`)·NP_EXTRACT 실행, `S/native/extract/parameter_features.json` `filter` = 정규화본, `ParamSet.native.extract_filter`·features 응답 `filter`, reprep·baselines 요청의 `extract_filter` 422, `add_baseline` NP_EXTRACT options의 `filter` = 기준 baseline 값, from-train 승계, `tag_options_sha256`·STALE 판정 불변, 필터 없는 등록은 현행과 같음.
- **V-EF-12 altair 무변경(U3)**: altair 기존 시험 무수정 통과, altair 요청의 `extract_filter`는 422 `EXTRACT_FILTER_UNSUPPORTED`, 분기 지점(요청 검증 1곳) 밖 altair 코드·설정·화면 diff 없음(GE V-GE-12와 같은 방식).
- **V-EF-10 버전**: paicad MINOR 올림 + CHANGELOG(영향: 필터 없음은 결과 불변, 필터·RIB_POS 신규), `scripts/test-all` 통과.

## 11. 구현 분해(파일 소유 비중첩)

| 담당 | 범위·파일 | 순서 |
|---|---|---|
| Impl-Geom | `packages/paicad/**`: `features.py`(필터·조기 제외·지연 탐색·RIB_POS 인식·`POSITION_TYPES` 단일화·`rib_rejects`), `extract.py`(필터 사본·`extract_stats.json`·PNG 범위), `options.py`(스키마·검증), `update.py`(RIB_POS `AXIS_SHIFT`·`positions[]`), `measure.py`(`rib_center`), `collision.py`(발자국 이동 반영 확인), `sweep.py`·`view/manifest.py`·`render.py`(치수선)·`paramap.py`·`selftest.py`(`rib_rejects` 합계)·`cli.py`(도움말), 시험(가상 쿠션 RIB_POS 변형형·부하 합성·동률 합성), `__version__`·CHANGELOG | **features.py 성능 작업 병합 뒤** 착수. G1(필터·조기 제외·stats) → G2(RIB_POS 인식~check·sweep) 를 한 MINOR로 배포 |
| Impl-Backend | `backend/physicsai_core/geometry/extract_filter.py`(신규: `GROUP_TYPES`·정규화·검증), `geometry/options.py`(`geom_options.extract.filter` 거부·defaults 경고), `services/job_params/stage1_train_data.py`(`TdExtractParams.extract_filter`·422 코드), **④: param-sets 생성 요청 스키마·서비스(`extract_filter`, altair·shell 422, reprep·baselines 422), 워커 `stage4_predict/param_set_native.py`(NP_PREP 준비 파일·parameters.json 생략 규칙·options `filter`·NP_EXTRACT 백업·요약, add_baseline 조건 승계), `ParamSet`·features 응답 `extract_filter`/`filter`(features JSON에서 읽음)**, `schemas/stage1_train_data.py`(`TrainSetup.extract_filter`·`extract_summary`), `worker/.../stage1_train_data/extract_native.py`·`extract.py`(options 작성·백업·TX_PARSE 기록·요약 로그), `migrations/versions/0019_extract_filter.py`(HEAD 다음)·`db/tables`, `backend/openapi.json`, `backend/tests/fake_tools/fake_paicad`(filter·stats), 시험 | Geom과 병행(fake로), API 모양 먼저 openapi 갱신 |
| Impl-Frontend | `frontend/src/stages/stage1/CadExtractCard.tsx`, 신규 공용 `ExtractFilterFields.tsx`, ④ `ParamSetDiscoverForm`(native일 때만)·세트 상세 피처 표 머리줄, ①-2 표 머리줄(파라미터 표 카드), `lib/geometry.ts`(RIB_POS 문구·`isPositionType`), API 타입·mock·시험, `frontend-dist` | openapi 갱신 뒤 |
| Plan | U1~U3 확정 반영 완료(2026-10-21), 구현 차이는 EF-C*(EF-C1 = paicad 0.11.0 해석) | — |

## 12. 사용자 결정(2026-10-21 확정)

| # | 질문 | 결정 |
|---|---|---|
| U1 | "찾을 종류" 처음 기본 체크와 조건 | 다섯 그룹 모두 체크·조건 빈칸(= 현행 결과 + 리브 위치), 이후는 Study의 마지막 사용 조건을 미리 채움(①-1·④ 공통) |
| U2 | 다른 조건으로 재추출할 때 기존 파라미터 표 | 확인 창 후 덮어쓰기(이전 표 백업, 현행 서버 동작) |
| U3 | 적용 범위 | 원문 "내가 요청하는건 native 한정이야. simlab은 건들지마" → native 경로 전체(①-1 + ④ `PARAM_SET_NATIVE`, §6.7), altair(SimLab·NX) 코드·UI·설정 변경 금지(필터 요청은 422만) |

## 변경 메모

(구현 중 계약과 달라지면 `EF-C1~`로 기록하고 Plan 확인.)

- **EF-C1**(2026-10-21, paicad 0.11.0 구현 bef0b30 `feat/r1-efgeom` — 구현 해석 확정, Plan 확인):
  1. **동률 창(§5.2·§5.1·R2)**: THICKNESS 지연 탐색에서 `d` 차이 1e-9 mm 이내는 동률로 보고 **낮은 면 index(현행 열거 순) 우선**. 상대 간격이 1e-9~2e-9 mm로 이어진 **연쇄 동률**에서만 전수 탐색(R_all 무필터 알고리즘)과 최근접 선택이 다를 수 있으며 이는 EF-INV의 **허용 예외**다(실물 CAD 좌표 정밀도에서 사실상 발생 없음). V-EF-2 동률 합성은 단일 동률(같은 거리 상대 2개)로 판정.
  2. **RIB_THICKNESS+RIB_POS 동시 변경(§3.2 update·check)**: 리브 중심 기대값(`positions[].expected_measured`) = 공칭 + RIB_THICKNESS 측면 이동에 따른 중심 평면 변위 + Δ(벡터 합). check (a) `rib_center`는 이 값과 비교.
  3. **RIB_POS `feasible.limited_by`(§3.2)**: ±a 두 방향 중 **여유가 더 좁은 쪽**을 제한한 면의 소유 피처(없으면 null).
  4. **L자 리브(V-EF-4)**: 꺾인 L자 리브는 기존 인식기(`_find_protrusions`)에서 리브가 아니므로 RIB_POS 시험 대상이 아니다. "한 방향 측면이 2개 이상이면 그 축 미생성(통계 `shape`)" 규칙은 **한쪽 측면을 소각(0.6°, `draft_max_deg` 이내)으로 꺾은 리브**로 시험한다(V-EF-4 "측면 여러 개(L자)"를 이것으로 대체).
  5. **산출물(§6.2-5·§6.4·§7.1·R7)** — CLI 인자 변화 없음:
     - `extract_stats.json`은 필터 유무와 무관하게 **항상 새로 쓴다** → 워커 출력 보호(백업 목록) 대상(§6.2-5·§6.7 NP_EXTRACT, fake_paicad 동일).
     - `parameter_features.json` 최상위 `filter` = 입력 `extract.filter` 사본 + `draft_max_deg`(유효값). 필터 없음이면 키 없음(V-EF-1).
     - 통계 종류별 계수: THICKNESS = `initiators`·`pair_tests`, RIB_THICKNESS·POCKET_WIDTH = `candidates`·`pair_tests`, 그 밖 종류 = `candidates`. 공통 `selected`·`kept`·`excluded{사유:수}`·`elapsed_s`.
     - `excluded` 사유 키: `face_area`·`thickness_range`·`not_mutual`·`no_overlap`·`not_thinner_than_height`(RIB_THICKNESS)·`height_range`·`hole_radius_min`·`fillet_radius_min`·`position_min_size`·`shape`·`base_axis`(위치형 밑면 축 비정렬).
     - `rib_rejects` 7키: `cap_inner_wire`·`cap_not_convex`·`lateral_not_plane`·`lateral_draft`·`lateral_count`·`base_mismatch`·`height_not_positive`(키 정렬 출력). §7.2 한국어 표기 제안: 윗면 내부 구멍·윗면 볼록 아님·측면 곡면·측면 구배·측면 3개 미만·밑면 불일치·높이 0 이하. `excluded` 추가 키 표기: 겹침 없음·높이보다 두꺼움·최소 크기·측면 형상·축 비정렬. 모르는 키는 원문 키로 표시(플랫폼은 키 집합에 의존하지 않음, §7.1).
     - stdout `PAICAD PROGRESS`는 **바디별** 종류 단계 줄(§7.1 예 형식). `selftest_report.json`에 `extract.rib_rejects`(바디 합계).
  6. **측정(V-EF-5 참고, 시간은 기록만)**: 부하 쿠션 1,662면에서 §4.1 예시 필터로 두께 겹침 판정 5,331→221회(≈4%), 전체 extract 251~377 s → 140~145 s, THICKNESS 미선택 81~95 s.
- **EF-C2**(2026-10-21, v0.2.3 구현 — 메인 판단·사용자 승인 UI): ① ④ Native 세트 등록은 "추출 조건 적용(새로 추출)" 체크 **기본 해제** — 해제면 `extract_filter` 미전송(기존 폴더 피처·parameters.json 사용), 체크 시 §6.7 규칙(§8 "항상 전송"을 대체, ①-1은 항상 전송 유지). ② 재시도 단계 라벨 SIMLAB_EXTRACT = "Altair 파라미터 추출"(백엔드 job_types와 통일, 표시 문구만 — V-EF-12 동작 경계 불변). ③ 라이트 테마 대비 토큰(`--color-row-selected`, `--color-text-secondary`, 다크 값 불변). ④ ①-1 카드 전폭 4줄 배치(`ExtractFilterFields wide`).
- **EF-C3**(2026-10-26 확정 — [rib-gap.md](rib-gap.md) §2.3): 그룹 `rib_pitch`("리브 간격(피치)", 종류 `RIB_PITCH_U/V`, 조건 없음, `position` 뒤) 추가 → 그룹 6·종류 13. EF-INV의 R_all은 "같은 RIB_PITCH 선택 여부"의 전 종류·조건 없음 결과로 정의(RIB_PITCH 선택 시 열 소속 리브의 같은 축 RIB_POS 미생성 — 홀수 열 가운데 리브만 유지 — 은 정의상 예외, RIB_PITCH는 면 소유자·`claimed`에 영향 없음). 열 모드 가운데 리브 RIB_POS `expected_measured` = 공칭 + Δ(EF-C1-2의 두께 중심 변위 가산 없음). U1 프리셋: 새 Study는 6개 모두 체크, 마지막 사용 조건이 있는 Study는 그 값(키 없으면 미체크).
