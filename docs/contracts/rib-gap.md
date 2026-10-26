# 계약: native 리브 간격 파라미터(RIB_GAP) — 두께는 그대로 두고 간격을 하나씩 조절

> 상태: **초안**(2026-10-26, 사용자 결정 Q1~Q3 대기 — §12). 상위 계약: [geometry-engine.md](geometry-engine.md)(GE), [extract-filter.md](extract-filter.md)(EF). 이 문서가 바꾸는 GE·EF 규칙은 §2.3에 모았고 GE 변경 메모 GE-C23·EF 변경 메모 EF-C3에 연결한다. 충돌하면 이 문서가 우선한다. 변경 메모 번호는 RG-C1부터 쓴다.

## 0. 한 줄 요약

paicad `extract`가 같은 방향으로 나란히 선 리브들을 **리브 열**로 묶고, 이웃한 리브 사이의 **맞보는 측면 간 거리(clear gap)**를 간격마다 독립 변수 `RIB_GAP_U_k`/`RIB_GAP_V_k`로 만든다. 열의 **기준 리브는 고정**하고(기본값은 좌표가 가장 작은 첫 리브), 간격 k를 바꾸면 그 하류(기준 리브 반대쪽)에 있는 리브 전부가 **강체 평행 이동**한다. 리브마다 윗면과 측면 전부를 같은 벡터로 옮기므로 리브 두께는 정확히 유지된다. update에서 두께가 변하지 않았는지 검사한다. 노드 ID는 그대로 두고(R1) 모핑한다. 추출 조건에서 "리브 간격"을 고르지 않으면 현재 출력과 바이트 단위로 같다.

## 1. 배경·원인

### 1.1 사용자 요청(2026-10-26)

- 원문: "형상파라미터 정의할때 리브간 거리는 잘 안되더라고. 리브가 일정두께를 유지한채 각 거리를 조절하려고해."

### 1.2 현재 동작(v0.2.10 = fb644a1, paicad 0.13.0)

리브 관련 변수는 RIB_THICKNESS(한쪽 측면만 Δ), RIB_HEIGHT(윗면 Δ), RIB_POS_U/V(EF §3.2, 윗면과 측면을 평행 이동하며 값은 바디 bbox 최소에서 잰 중심 좌표) 세 가지다. **간격 자체를 나타내는 변수는 없다.**

### 1.3 "잘 안 되는" 원인 추정(코드 근거. 이 작업 환경에는 OCP가 없어 실행 확인은 하지 못함)

| # | 원인 | 코드 근거 | 증상 |
|---|---|---|---|
| C1 | 간격 = 두 위치 값의 차 | `features._rib_pos`: 값 = 측면 중심 − bbox 최소. 간격 변수는 없음 | 간격 하나를 바꾸려면 변수 두 개를 함께 움직여야 한다. 리브 하나를 옮기면 양옆 간격이 동시에 바뀌어 "각 거리"를 독립적으로 정할 수 없다 |
| C2 | 범위·여유를 이웃이 공칭에 있다고 가정하고 계산 | `_rib_pos_feasible`: 이웃 리브 측면까지 거리 − 0.5 mm를 리브마다 따로 계산. 범위는 ±`position_range_mm`(5 mm) | DOE에서 이웃한 두 리브가 서로 다가가면, 각각은 범위 안이어도 합치면 발자국이 겹친다 → `collision.BOUNDARY_OVERLAP` → `GEOM_FEATURE_COLLISION`(종료 10)으로 샘플이 실패한다. 범위를 좁히면 탐색 폭을 잃는다 |
| C3 | 위치 기준이 샘플마다 바뀜 | `update.nearest_fixed_face`: "이번 샘플에서 움직이지 않는" 가장 가까운 면을 기준으로 삼고, 리브 위치 이동 면은 제외(`rib_shifted`) | 한 변수 sweep에서는 이웃 리브 측면이, DOE에서는 벽이 기준이 된다. 벽 THICKNESS가 함께 바뀌면 리브마다 따라가는 면이 달라 간격이 의도와 다르게 변한다 |
| C4 | 간격을 두께 계열 변수로 바꾸면 두께가 함께 변함 | `update.plan_body` 단계 3: RIB_THICKNESS·POCKET_WIDTH·THICKNESS는 `pair_ref`가 고른 **한쪽 면만** 이동. 포켓 벽은 `claimed` 대상이라, 위에서 판 홈 사이 벽에는 두께 변수가 없고 POCKET_WIDTH만 있음 | 간격을 바꾸면 이웃 리브의 두께가 반드시 바뀐다. 사용자가 말한 "일정 두께 유지"와 정면으로 충돌한다 |
| C5 | 리브 인식 범위가 좁음 | `_find_protrusions(+1)`의 리브 조건: 윗면 외곽 엣지가 전부 볼록하고, 측면의 바깥 엣지가 **밑면 하나에만** 오목하게 붙음 | 다음 리브는 리브로 인식되지 않아 RIB_POS·RIB_THICKNESS 자체가 없다. (a) 양끝이 외벽에 붙은 칸막이 리브(끝 엣지가 오목 → `cap_not_convex`·`base_mismatch`) (b) U·V가 교차하는 격자(교차부 측면끼리 오목 → `base_mismatch`) (c) 모서리 블렌드가 있거나 구배가 3°를 넘는 리브(EF R1). 실물의 "안 됨"이 이 경우라면 간격 변수만으로는 해결되지 않는다 — `extract_stats.json` `rib_rejects`로 확인한다 |
| C6 | 공칭이 같으면 대칭 그룹으로 묶임 | GE §6.2 MIRROR(같은 종류, 공칭 차 ≤ tol) | 위치는 공칭이 서로 달라 거의 영향이 없다. 하지만 간격 변수를 그대로 넣으면 등간격 열의 간격 k와 n−k가 한 그룹으로 묶인다 → 이 계약에서는 같은 열 안의 그룹화를 금지한다(RG-3) |

시험 fixture로 확인한 것: 가상 쿠션(`tests/data/make_synthetic.py`)은 바디마다 U 방향 리브가 2개뿐이고 그 사이에 포켓이 있다. `test_rib_pos.py`는 리브 1개만 옮기며, V 방향은 리브 4개가 MIRROR 한 그룹이다. 간격 시험에 맞는 fixture가 아니므로 새로 만든다(§10).

### 1.4 쿠션 리브 배치 유형

| 유형 | 모양 | 이 계약 |
|---|---|---|
| T1 평행 독립 리브 열 | 바닥(밑면)에서 솟은 직사각 리브가 한 방향으로 나란히 섬 | **범위**(현재 인식기로 인식됨) |
| T2 칸막이 리브 열 | 한쪽 끝이나 양끝이 외벽 안쪽 면에 붙은 리브 | **Q3에 따라 범위**(인식 확장 §3.3) |
| T3 홈 사이 벽 | 위에서 판 포켓이 나란하고, 포켓 사이 벽이 리브 역할 | 후속(같은 열 모델로 확장 가능. 간격 = 포켓 폭으로 재정의해야 함) |
| T4 격자 | U·V 리브가 교차 | 비범위. 교차 리브를 옮기면 분할된 교차 측면의 길이가 바뀌어 별도 재구성 규칙이 필요(후속) |
| T5 바디 경계와의 관계 | 열 끝 리브 ↔ 외벽(또는 밑면 끝)의 거리 | 변수가 아니라 **끝 여유**. 고정 규칙에 따라 누적 변화를 흡수하고 범위 상한의 근거가 된다(§5) |
| T6 엇갈린 배치 | 한쪽 이웃 후보가 2개 이상 | 그 지점에서 열을 끊는다(통계 `row_branch`) |

### 1.5 범위·비범위

- 범위: paicad `extract`(열 인식·RIB_GAP·`rib_rows`), `update`(열 강체 이동·두께 불변 검사), `morph`(새 알고리즘 없음), `check`(간격·두께 재측정, 열 영역 품질 보고), `sweep`, `view`, `paramap`. 플랫폼에서는 추출 조건 그룹 `rib_gap`, 변수 표(①-2·④), 경고, 문구, fake_paicad, MCP 용어집.
- 비범위: T3·T4, altair(SimLab·NX) 경로(EF U3와 같음), 쉘, 재메시, 리브 개수 변경(위상 변형은 다중 baseline GE-13).

## 2. 용어·결정

### 2.1 용어

| 용어 | 뜻 |
|---|---|
| 리브 열(row) | 같은 바디, 같은 밑면, 같은 두께 축 a에서 이웃 관계로 사슬처럼 이어진 리브 2개 이상. 리브는 a 오름차순으로 r_1..r_n, 간격은 g_1..g_{n−1} |
| 두께 축 a | 리브 윗면의, 밑면 평면 안 bbox에서 짧은 변 방향(전역 축). 다른 쪽 축 b는 리브 길이 방향 |
| 간격 g_k | r_k의 +a 측면과 r_{k+1}의 −a 측면 사이의 a 방향 거리(각 면 centroid a 성분의 차) = clear gap |
| 기준 리브(anchor) | 열에서 간격 변화로 움직이지 않는 리브(짝수 열의 center 모드에서는 가운데 간격의 중심 평면) |
| 하류 리브 | 간격 g_k를 기준으로 기준 리브의 반대쪽에 있는 리브들. g_k가 바뀌면 이들이 함께 이동한다 |
| 끝 여유 R | 열 끝 리브의 바깥 측면에서 a 방향으로 다음 장애물(a에 수직인 평면 중 발자국 영역과 겹치는 것, 또는 밑면 bbox 경계)까지 거리 − `WALL_MIN_MM`(0.5) |

### 2.2 결정(RG-1~RG-11)

| ID | 결정 |
|---|---|
| RG-1 | 새 종류 `RIB_GAP_U`·`RIB_GAP_V`(약어 = 종류 이름, 이름 예 `CUSH_L_RIB_GAP_U_1`). `TYPE_ORDER` 맨 뒤(`… RIB_POS_U, RIB_POS_V, RIB_GAP_U, RIB_GAP_V`)에 두어 기존 종류의 순서·이름·그룹 id는 바뀌지 않는다. 필터 `types`에 들어 있을 때만 생성한다 |
| RG-2 | 값 = **clear gap**(권고, Q1). 비교는 §4.4 |
| RG-3 | 간격마다 독립 변수. **같은 열 안에서는 대칭 그룹을 만들지 않는다.** 바디 간(L↔R) 대칭은 기존 규칙을 따르고, 짝 열의 기준 리브는 대표 열 기준 리브의 대칭 짝으로 한다(§3.4) |
| RG-4 | 고정 규칙 = **열의 첫 리브(a 최소) 고정 + 하류 누적 이동**(권고, Q2). 옵션 `rib_gap.anchor` = `first`(기본)·`center`·`last`. extract 때 열마다 정해 features에 기록하며, update는 그 기록만 따른다 |
| RG-5 | 이동은 강체 평행 이동이다. 리브의 moving 면(윗면 + 측면 전부)에 같은 a 방향 벡터를 더한다(같은 샘플의 RIB_THICKNESS·RIB_HEIGHT·THICKNESS 이동과 벡터 합). 밑면 surface는 그대로이고 발자국 와이어만 다시 계산한다(GE-C7). rebuild 뒤 간격·두께를 재측정해 `body_tol`을 넘으면 실패한다(§4.3) |
| RG-6 | RIB_POS와의 관계 = **배타**. 같은 축의 RIB_GAP을 고르면 열 소속 리브 가운데 **기준 리브가 아닌 것의 그 축 RIB_POS는 만들지 않는다**(통계 사유 `row_member`). 기준 리브의 RIB_POS는 남고, 그 값을 바꾸면 **열 전체**가 평행 이동한다. RIB_GAP을 고르지 않으면 RIB_POS는 현행과 같다(기존 세트 호환) |
| RG-7 | 범위는 절대 mm로, 공칭 ∓ `extract.position_range_mm`. 하한은 `rib_gap.min_gap_mm`(기본 1.0)보다 작아지지 않는다. 상한은 **열 공동 안전값**(끝 여유를 하류 간격 수로 균등 배분)으로 자른다. `feasible`은 변수 하나만 바꿀 때의 여유다(§5) |
| RG-8 | 모핑 알고리즘은 바꾸지 않는다(밑면·끝 면은 GE §6.4 대체 규칙). check에 간격·두께 재측정 항목과 열 영역 품질 보고를 더한다. 합격·불합격 기준값은 기존 `quality`를 그대로 쓴다(§6) |
| RG-9 | 조건 키는 없다. 간격 크기 하한 같은 필터를 두지 않는데, 열의 일부 간격만 빠지면 사슬이 끊기기 때문이다(행 완전성). 열 구성은 `position_min_size_mm`의 영향을 받지 않는다 |
| RG-10 | 화면: ①-1 추출 조건에 새 그룹 `rib_gap` "리브 간격"을 "위치(구멍·리브)" 바로 뒤에 둔다. ①-2·④ 변수 표에서는 mm 길이로 표시하고, 3D 치수선은 기존 `linear`를 재사용한다(§7·§8) |
| RG-11 | paicad **0.14.0**(MINOR). DB·migration 없음. API 모양은 `ExtractFilter.groups` 열거값 1개 추가뿐이다 |

### 2.3 GE·EF에서 바뀌거나 더해지는 규칙(이 문서 우선)

- GE §4.3: 약어 `RIB_GAP_U`·`RIB_GAP_V`, `measure.method`에 `rib_gap`, `parameter_features.json` 최상위 선택 키 `rib_rows`(RIB_GAP이 있을 때만), 피처 선택 키 `row`. `schema_version`은 1을 유지한다(선택 키 추가).
- GE §4.6: `update.json` 가산 키 `rib_rows[]`, `applied[].op` 값 `RIB_ROW_SHIFT`, `ref_rule` 값 `row_anchor`.
- GE §6.2: 종류 표에 RIB_GAP 행. MIRROR는 같은 `row.id`끼리 묶지 않는다.
- GE §6.3: 단계 3(그룹 피처)과 단계 4(위치) 사이에 **단계 3.5 열 이동**을 넣는다. 열 이동 면은 HOLE_POS·RIB_POS의 `nearest_fixed` 기준에서 제외한다(`rib_shifted`와 같은 규칙). 충돌 사전 검사에 kind `RIB_GAP_MIN`을 추가한다.
- GE §6.5: check (a) `rib_gap` 항목·`rib_row_thickness` 파생 항목, (c) 보고 키 `quality.rib_rows[]`.
- EF §3.1: 그룹 `rib_gap`(종류 `RIB_GAP_U`·`RIB_GAP_V`, 조건 없음) → 그룹 6개, 종류 13개.
- EF §5.1 EF-INV: 기준 결과 R_all은 "같은 RIB_GAP 선택 여부"에서 전 종류·조건 없음으로 정의한다. RIB_GAP을 고른 결과에서 비기준 RIB_POS가 빠지는 것은 정의상 예외다. RIB_GAP 피처는 면 소유자(`face_owner`)가 되지 않고 `claimed`를 바꾸지 않는다 → 다른 종류의 결과·`limited_by`는 변하지 않는다.

## 3. 열 인식(extract)

### 3.1 리브 후보

1. T1: `_find_protrusions(+1)`로 인식된 리브(cap·lats·base). 칸막이 리브(T2)는 Q3가 "포함"일 때 §3.3을 따른다.
2. 밑면 법선이 전역 축 k와 1° 이내여야 한다(RIB_POS와 같은 `cos1`). 아니면 제외하고 사유 `base_axis`.
3. 두께 축 a = 나머지 두 축 가운데 cap bbox 변이 짧은 쪽. 긴 변 / 짧은 변 < `rib_gap.slender_min`(기본 1.5)이면 기둥형으로 보고 제외(`not_slender`).
4. a 방향으로 법선이 +a인 측면과 −a인 측면(각 ≤ `draft_max_deg`)이 각각 정확히 1개여야 한다(RIB_POS `shape` 규칙과 같음). 아니면 `shape`.

### 3.2 이웃·열 구성

- r_j가 r_i의 +a 이웃이 되는 조건: (i) 같은 바디, 같은 밑면 id, 같은 a (ii) r_j −a 측면 centroid[a] > r_i +a 측면 centroid[a] + 1e-6 (iii) 두 리브 측면의 b 구간이 겹치는 길이 ≥ `rib_gap.overlap_min`(기본 0.5) × 짧은 리브 길이 (iv) 두 면 사이 띠(a 구간 × 겹친 b 구간)에 a에 수직인 다른 평면(벽·포켓 벽·다른 리브 측면)이 영역을 겹쳐 들어 있지 않음. 조건을 만족하는 후보 가운데 a 거리가 가장 가까운 것을 이웃으로 정한다.
- 분기: 한 리브의 +a 이웃 후보가 같은 거리(1e-6 이내)로 2개 이상이거나, 한 리브가 둘 이상의 리브에게 +a 이웃으로 선택되면 그 연결을 모두 끊는다(`row_branch`).
- 열 = 연결로 이어진 리브 2개 이상의 최대 사슬. 열 id = `<U|V><번호>`이며, 번호는 바디 안에서 (축, 첫 리브 a 좌표, b 좌표) 오름차순으로 매긴다. 간격 이름의 번호 k는 바디·종류 안에서 (열 번호, 열 내 순서) 순으로 매긴다(`make_name` 규칙).
- 통계(`extract_stats.json` `types.RIB_GAP_*`): `candidates`(후보 리브 수), `kept`(간격 수), `excluded{base_axis, not_slender, shape, row_branch, row_single}`(`row_single` = 이웃이 없는 리브). `types.RIB_POS_*.excluded.row_member` = 열 소속이라 빠진 RIB_POS 수.

### 3.3 칸막이 리브 인식(T2 — Q3 "포함"일 때)

- 조건: cap은 내부 와이어가 없는 평면이다. cap 외곽 엣지는 ±a 측면과는 볼록, **끝 면**과는 오목이어야 한다. 끝 면 = 법선이 ±b(구배 ≤ `draft_max_deg`)인 평면이고 이 리브의 측면이 아닌 면이며, 1개 또는 2개다. 측면은 ±a 평면 정확히 2개이고, 그 나머지 엣지는 밑면 또는 끝 면에만 오목하게 붙어야 한다. 밑면은 cap과 평행한 평면 1개다.
- moving = cap + 측면 2개, hosts = 밑면 + 끝 면. 끝 면 위의 리브 단면은 끝 면 와이어(외곽 와이어의 노치 또는 내부 와이어)로 남고, 밑면과 같은 방식(GE §6.4 대체 규칙)으로 모핑한다.
- **기존 결과는 바꾸지 않는다.** 칸막이 리브는 `claimed`에 넣지 않으므로, 지금 그 측면 쌍에서 나오는 THICKNESS는 그대로 남는다. RIB_THICKNESS·RIB_HEIGHT·RIB_POS도 만들지 않으며, 열 구성에만 쓴다. 같은 샘플에서 그 THICKNESS가 바뀌면 §4.2의 τ로 반영한다.
- 통계 `rib_rejects`에는 영향이 없다(T1 판정 뒤 별도 패스). `types.RIB_GAP_*.partition_ribs` = 칸막이 리브 수.

### 3.4 기준 리브·대칭

- `first`: m = 1. `last`: m = n. `center`: n이 홀수면 m = (n+1)/2, 짝수면 가운데 간격 g_{n/2}의 중심 평면을 고정하고 그 간격의 변화를 양쪽에 ½씩 나눈다(`anchor: "gap:<n/2>"`).
- 바디 간 대칭: extract 마무리 단계에서 대칭 그룹을 판정하기 **전에** 열 짝을 찾는다. 짝 = 다른 바디, 같은 a, 같은 n이고 리브 중심이 기존 MIRROR 평면(bbox 중심 평면·공통 바디 사이 평면)에 대해 tol 안에서 대칭인 열이다. 짝 열의 기준은 대칭 평면이 a에 수직이면 n+1−m, 아니면 m이다. 비기준 RIB_POS를 빼는 작업은 이 결정 뒤에 한다.
- RIB_GAP의 MIRROR 그룹: 같은 `row.id` 쌍은 후보에서 뺀다. 바디 간 짝 열의 간격끼리는 기존 `_is_mirror` 판정을 그대로 쓴다.

### 3.5 출력(`parameter_features.json`)

```json
"rib_rows": [
  {"id": "U1", "body": "CUSH_L", "axis": "x", "base": "F3", "anchor": 1, "kind": "protrusion",
   "ribs": [{"index": 1, "cap": "F21", "minus": "F22", "plus": "F24", "moving": ["F21","F22","F23","F24","F25"], "hosts": ["F3"],
             "thickness": 6.0, "center": 28.0}],
   "end_room_mm": {"minus": 12.4, "plus": 18.0}, "end_limited_by": {"minus": "CUSH_L_THK_2", "plus": null},
   "face_signatures": {"F21": "…"}}
]
```

- 피처 RIB_GAP: `nominal` = g_k, `faces` = r_k·r_{k+1}의 cap·측면 + 밑면, `measure.faces` = [r_k +a 측면, r_{k+1} −a 측면], `measure.method = "rib_gap"`, `axis`, `faces.moving` = 하류 리브 전부의 moving 면, `faces.fixed` = [밑면], `row = {"id": "U1", "k": 1, "n": 5}`.
- `kind` = `protrusion`(T1) | `partition`(T2). 한 열에 두 종류가 섞여도 되고, 리브별 `kind`는 선택 키로 둔다.

## 4. 값·update

### 4.1 기호

열 리브 i의 공칭 측면 좌표를 x⁻_i, x⁺_i(centroid[a]), 단계 1~3에서 이미 정해진 그 면의 a 방향 이동을 τ⁻_i, τ⁺_i(`T[face][a]`, RIB_THICKNESS·THICKNESS 등)로 쓴다. 공칭 간격은 g⁰_k, 샘플 값은 g_k, 리브 i의 강체 이동량은 s_i다.

### 4.2 열 이동(단계 3.5)

- 기준: s_m = 기준 리브 RIB_POS가 정한 이동(기존 §3.2 규칙, 없거나 공칭이면 0). center·짝수 모드에서는 가운데 간격 g_c의 변화 Δ_c를 r_c에 −½Δ_c, r_{c+1}에 +½Δ_c로 나눈 것을 기점으로 삼는다.
- 하류(+a): s_i = s_{i−1} + τ⁺_{i−1} + (g_{i−1} − g⁰_{i−1}) − τ⁻_i  (i = m+1..n)
- 상류(−a): s_i = s_{i+1} + τ⁻_{i+1} − (g_i − g⁰_i) − τ⁺_i  (i = m−1..1)
- 결과: 간격 = g_k(정확), 리브 두께 = t⁰_i + τ⁺_i − τ⁻_i(두께 변수가 바뀌지 않으면 t⁰_i 그대로).
- 리브 i의 moving 면마다 `add(face, s_i·e_a)`. 열 이동 면은 축 a의 `rib_shifted`에 넣는다.
- `applied[]`: RIB_GAP마다 `op: "RIB_ROW_SHIFT"`, `moved` = 이 간격 때문에 움직인 하류 면, `fixed` = [밑면], `ref_rule: "row_anchor"`.
- 방어 규칙: features에 비기준 리브의 RIB_POS가 남아 있고(수작업 파일 등) 그 값이 공칭과 다르면서 같은 열·축의 RIB_GAP이 있으면 → `GEOM_INPUT_INVALID`(종료 3) "RIB_GAP_POS_CONFLICT: rib position and rib gap on the same row".

### 4.3 사전 검사·두께 불변 검사

- 사전 검사(rebuild 전): g_k < `rib_gap.min_gap_mm` − 1e-9이면 collision kind `RIB_GAP_MIN` → `GEOM_FEATURE_COLLISION`(종료 10, 메시지에 간격 이름·값). 기존 `BOUNDARY_OVERLAP`(발자국끼리 겹침, 외곽 와이어·구멍·포켓 입구 침범)와 `WALL_PENETRATION`(끝 리브 측면이 벽을 통과)도 그대로 적용한다.
- 사후 검사(rebuild 뒤 `sample.brep`): 열마다 각 간격·리브 두께를 맞보는 측면 centroid로 재측정한다. |오차| > `options.body_tol`이면 `GEOM_CAD_FAILED`(종료 10) "rib row drift: <name> expected … measured …".
- `update.json` `rib_rows[]` = `{id, body, axis, anchor, ribs[{index, shift_mm, thickness_expected, thickness_measured}], gaps[{name, value, measured}], end_room_mm{minus, plus}}`(사후 끝 여유). 가산 키이므로 스키마 버전은 그대로 둔다.

### 4.4 값 정의 비교(Q1)

| 안 | 값 | 장점 | 단점 |
|---|---|---|---|
| **A clear gap(권고)** | 맞보는 측면 사이 거리 | 설계자가 도면에서 재는 "리브 간 거리"와 같다. 같은 샘플에서 두께가 바뀌어도 간격 값이 그대로 유지되고, 하한(최소 간격)이 바로 보인다 | 구배가 있는 측면이면 centroid(높이 중간) 기준 값이 된다 |
| B 피치 | 이웃 리브 중심 간 거리 | 금형 피치 표기와 같고, 두께 변화가 양쪽에 대칭으로 나뉜다 | 두께와 함께 바뀌면 실제 틈이 값에서 바로 보이지 않고, 최소 간격을 검사하려면 두께를 다시 빼야 한다 |
| C 경계 기준 위치 | 열 첫 리브에서 각 리브까지 거리 | 위치형과 비슷하다 | 하나를 바꾸면 사이 간격 둘이 함께 변한다(C1 재발) |

### 4.5 고정 규칙 비교(Q2)

| 안 | 동작 | 장점 | 단점 |
|---|---|---|---|
| **first(권고)** | 첫 리브(a 최소) 고정, 변화는 + 끝 여유가 흡수 | 간격마다 영향이 한쪽으로만 가서 예측하기 쉽다. 구현과 시험이 가장 단순하다 | 대칭 배치를 유지하기 어렵고 + 끝 여유 영역이 가장 많이 압축·신장된다 |
| center | 가운데 리브(짝수 열은 가운데 간격 중심) 고정 | 대칭 배치에 맞고 변화가 양 끝에 나뉜다 | 간격 k가 어느 쪽 리브를 미는지 사용자가 기억해야 한다 |
| 바디 경계 유지 | 양 끝 여유를 고정하고 간격 합을 보존 | 외곽 치수를 유지한다 | 간격이 n−1개 중 n−2개만 독립이어서 "각 거리" 요구와 맞지 않는다 → 기각 |

## 5. 범위·feasible·envelope

- `feasible`(변수 하나만 바꿀 때): min = `rib_gap.min_gap_mm`, max = g⁰ + R_side. R_side는 그 간격이 미는 쪽의 끝 여유다(`first`이면 + 끝, center이면 그 간격 쪽 끝, 짝수 center의 가운데 간격이면 min(R⁻, R⁺)×2). `limited_by`는 끝 장애물 면의 소유 피처(없으면 null)다.
- `range`(공동 안전): [max(min_gap, g⁰ − P), g⁰ + min(P, R_side / m_side)]. P = `position_range_mm`, m_side = 같은 쪽 끝 여유를 쓰는 간격 수(짝수 center 가운데 간격은 ½ 가중). 범위 안의 어떤 조합이든 열 끝이 장애물에 닿지 않는다. 간격을 줄이는 방향은 사슬 안에서만 움직이므로 끝 여유를 쓰지 않는다.
- 남는 위험: 밑면 위 구멍·포켓 입구가 이동 경로에 있으면 범위 안이라도 `BOUNDARY_OVERLAP`이 날 수 있다(샘플 실패 경로 그대로). 기준 리브 RIB_POS와 동시에 바뀌면 끝 여유를 함께 쓰므로 경고 대상이다(아래).
- 플랫폼 경고(차단 없음) `RIB_GAP_JOINT_RANGE`: 변수 표 저장(①-2·④ native-vars) 때 같은 열에서 Σ(상한 − 공칭)(하류 쪽) > R_side이거나, 기준 RIB_POS와 RIB_GAP을 함께 쓰는데 |RIB_POS 범위| + 간격 증가 합 > 끝 여유이면 "같은 리브 열(U1)의 간격 상한 합이 끝 여유 18.0 mm를 넘습니다 — 일부 샘플이 형상 생성에 실패할 수 있습니다".
- sweep: RIB_GAP은 mm 단계 계열(`--pos-steps`)을 쓰고 행은 `unit: "mm"`. 단계마다 간격 하나만 바꾼다. envelope 보고서 행에 §6의 열 영역 품질 요약을 붙인다.
- 상수: `features.py`에 `RIB_GAP_TYPES`와 `ABS_RANGE_TYPES = POSITION_TYPES + RIB_GAP_TYPES`(절대 mm 범위·mm sweep)를 정의한다. `POSITION_TYPES`(bbox 좌표 의미·위치 치수선)에는 RIB_GAP을 넣지 않는다.

## 6. morph·check

- morph: 새 규칙 없음. cap·측면 노드는 면 UV 대응으로 움직이고, 밑면(+ 칸막이 끝 면)은 "내부·외곽 와이어가 이동한 면"이므로 GE §6.4-1 대체 규칙(경계 변위 조화 보간 → 투영)을 쓴다. 간격 사이 바닥은 a 방향으로 대략 g/g⁰ 비율로 늘거나 줄고, 끝 여유 영역이 누적 변화를 흡수한다. 노드 ID·요소 연결은 바뀌지 않는다(R1).
- check (a):
  - `rib_gap` 항목: 모핑 메시에서 두 측면의 외피 삼각형 면적 가중 centroid[a] 차를 구해 값과 비교한다(`deviation.param_abs_mm`).
  - 파생 항목 `kind: "rib_row_thickness"`(이름 `<body>:<row id>:<index>`): 이동한 리브마다 ±a 측면 centroid 차를 `update.json` `thickness_expected`와 비교한다. 같은 허용오차를 쓰며, FAIL이면 param 검사도 FAIL이다.
- check (c): 합격 기준은 기존 `quality`(min_stretch 0.1·max_aspect 10·min_edge_ratio 0.8·dt_ratio_min 0.8) 그대로다. 보고 키 `checks.quality.rib_rows[]` = 간격 영역과 끝 여유 영역마다 `{name|end, elems, ratio(= g/g⁰ 또는 끝 여유 비), min_edge_ratio, max_aspect, min_stretch, dt_ratio, status}`. 영역 = 요소 centroid가 맞보는 두 측면(모핑 후) 사이의 a 구간과 겹친 b 구간 안에 있고, 법선 방향으로 cap 높이 아래에 있는 요소다. 전체 판정은 바꾸지 않고, 어느 간격이 품질을 깨는지 귀속만 한다.
- 지침(문구·문서): 기준 메시에서 간격 압축비 g/g⁰ < 0.8이면 `min_edge_ratio` 0.8에 걸리기 쉽다. 실제 한계는 envelope로 잰다.

## 7. view(geometry-view 재사용)

- `view_manifest.json` `features[]`의 RIB_GAP: `dimension.kind: "linear"`, `p0` = r_k +a 측면 위 점(두 면 b 겹침 구간 중앙, 높이 중앙), `p1` = p0를 r_{k+1} −a 측면에 a 방향으로 투영한 점, `value` = 값. `faces.moving` = 하류 리브 면(미리보기는 `update.json.applied[].moved`), `fixed` = [밑면], `other` = measure 면. 선택 키 `row {id, k, n}`.
- PNG 치수선도 같은 두 점으로 그린다. 프런트는 그리는 코드를 바꾸지 않는다(기존 linear). 표 행을 선택하면 하류 리브 전부가 하이라이트되어 "이 간격을 바꾸면 무엇이 움직이는지" 보인다.

## 8. 플랫폼·화면

| 위치 | 변경 |
|---|---|
| `physicsai_core/geometry/extract_filter.py` | `GROUP_TYPES["rib_gap"] = ("RIB_GAP_U", "RIB_GAP_V")`(순서는 `position` 뒤), `GROUP_LABELS` "리브 간격", 조건 없음, `TYPE_LABELS` "리브 간격 U/V", `EXCLUDED_LABELS` `not_slender` "기둥형", `row_branch` "열 분기", `row_single` "이웃 없음", `row_member` "간격 열 소속" |
| openapi `ExtractFilter.groups` | 열거값 `rib_gap` 추가(그 밖 모양 불변). `GET …/features`는 `rib_rows`를 그대로 전달한다(features JSON 통과 — 스키마가 extra를 막고 있으면 선택 필드로 추가) |
| ①-1·④ `ExtractFilterFields` | 체크박스 "리브 간격"을 "위치(구멍·리브)" 바로 뒤에 둔다. 도움말: "같은 방향으로 나란한 리브 사이 거리(리브 두께 유지). 고르면 열의 첫 리브만 위치 변수로 남습니다." 프리셋(U1): 새 Study는 6개 모두 체크, 마지막 사용 조건이 있는 Study는 그 값(키가 없으면 미체크 → 기존 결과 그대로) |
| ①-2·④ 변수 표(native-vars) | RIB_GAP은 길이 mm(좌표 아님, `isPositionType` 아님)로, 하한·상한은 절대 mm, 옆에 공칭 대비 Δ. 행 툴팁 "열 U1 · 간격 2/4 · 기준 리브 1". 경고 `RIB_GAP_JOINT_RANGE`(§5). ①-2 "적용 조건" 줄에 "리브 간격" |
| `lib/geometry.ts` | 종류 문구, `isGapType`, `ABS_RANGE` 판정에 RIB_GAP |
| MCP 용어집 | `RIB_GAP_U`·`RIB_GAP_V` `ko` 한 줄씩(정적 시험, AGENTS.md MCP 대응) |
| fake_paicad | `types`에 RIB_GAP 허용, 합성 간격 피처·`rib_rows` 출력(플랫폼 시험용) |
| DB | 변경 없음(`train_setups.extract_filter` JSONB에 그룹 키만 늘어남) |

## 9. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 실물 리브가 칸막이·격자·블렌드형이라 인식되지 않으면(C5) 간격 변수가 0개 | Q3로 범위 확정. `rib_rejects`·`row_*` 통계를 selftest로 회신받고, 격자·블렌드는 후속 계약 |
| R2 | 끝 여유 영역이 누적 변화를 흡수해 품질이 먼저 깨짐(`first`) | §6 열 영역 보고로 귀속, `range` 공동 안전값, envelope 측정, Q2에서 center 선택 가능 |
| R3 | 큰 간격 변화에서 밑면 조화 보간 품질 미달(EF R4와 같은 근원) | 기본 범위 ±5 mm, envelope `--pos-steps`, 필요하면 후속으로 국부 영역 해(쉘 `morph.region` 선례) |
| R4 | 칸막이 리브의 끝 면 와이어(외곽 노치) 재구성이 위상 보존 rebuild에서 실패 | V-RG-6 fixture로 먼저 확인. 실패하면 T2를 후속으로 미루고 Q3 결정을 다시 확인 |
| R5 | 바디 간 짝 열의 기준 리브 대응이 틀어지면 L/R 비대칭 | §3.4 짝 판정 → 기준 대칭, V-RG-8 |
| R6 | RIB_GAP을 고르면 비기준 RIB_POS가 사라져 기존 Study 사용자가 혼동 | 도움말 문구, ①-2 "적용 조건" 표시, 기존 Study 프리셋은 미체크 유지 |
| R7 | 구멍·포켓이 이동 경로에 있으면 범위 안에서도 충돌 | 기존 `GEOM_FEATURE_COLLISION` 실패 경로(DOE 샘플 실패로 기록), feasible 문구에 안내 |

## 10. 시험(V-RG-*)

합성 fixture `tests/data/make_ribrow.py`(build123d): 밑판 위에 a 방향 평행 리브 3개와 5개 열(두께 6, 간격 공칭 20·15·25·…), 같은 바디 V 방향 열 1개, 끝 여유 장애물(벽) 1개, L/R 대칭 바디 쌍, 선택으로 칸막이형 변형(양끝 벽 연결)과 구멍 1개(경로 충돌용). 정답 = 리브를 정답 좌표로 다시 만든 형상.

- **V-RG-1 하위호환**: `types`에 RIB_GAP이 없으면 가상 쿠션·기존 골든 extract 결과가 0.13.0과 바이트 동일하고 `rib_rows` 키가 없다. 기존 `test_rib_pos.py`·`test_extract_filter.py`를 수정 없이 통과한다.
- **V-RG-2 인식**: 3·5개 열 → 간격 2·4개, 이름·순서·`row`·`rib_rows` 정답과 일치. 기둥형·L자(꺾인 측면)·엇갈린 배치 → 각각 `not_slender`·`shape`·`row_branch`. 열 사이에 벽 → 열 분리. 비기준 RIB_POS 미생성(`row_member`)·기준 RIB_POS 유지. EF-INV(같은 RIB_GAP 선택 여부 기준)·결정성(2회 바이트 동일).
- **V-RG-3 update 정답**: 간격마다 +3·−3 mm 단독, 여러 간격 동시(±), center·last 모드 → B-rep 면별 최대 거리 ≤ 0.01 mm, 부피 차 ≤ 0.1 %, 모든 리브 두께 변화 ≤ 1e-6 mm(두께 불변), 기준 리브 이동 0. RIB_THICKNESS 동시 변경 시 간격 = 값·두께 = 값.
- **V-RG-4 충돌·오류**: g < `min_gap_mm` → `RIB_GAP_MIN` 종료 10. 끝 여유 초과 → `WALL_PENETRATION`/`BOUNDARY_OVERLAP` 종료 10. 구멍 경로 → `BOUNDARY_OVERLAP`. 수작업 features의 RIB_POS+RIB_GAP 동시 변경 → `GEOM_INPUT_INVALID` 종료 3. 사후 두께 drift 주입(fake kernel) → `GEOM_CAD_FAILED`.
- **V-RG-5 morph·check**: 노드 ID·요소 연결 불변(`morphed.inc` 좌표 줄 외 바이트 동일), 경계 노드 ↔ 정답 ≤ 0.05 mm, 반전 0, check (a) `rib_gap`·`rib_row_thickness` 오차 ≤ `param_abs_mm`, (c) `quality.rib_rows[]` 영역 키·비율 정답(g/g⁰). 같은 입력 2회 `morphed.inc` 바이트 동일.
- **V-RG-6 칸막이(Q3 포함 시)**: 양끝 벽 연결 열에서 간격 변경 → 정답 비교(V-RG-3 기준), 기존 THICKNESS 피처 유지, 끝 면 `uv_fallback`.
- **V-RG-7 범위·sweep**: `range` 공동 안전(하류 간격 모두 상한일 때 충돌 없음 — 실제 update로 확인), `feasible` 단독, sweep `unit: "mm"` 행·열 품질 요약.
- **V-RG-8 대칭**: 같은 열 간격은 그룹 없음. L/R 짝 열 간격은 그룹이고 짝 열 기준 = 대칭 짝, 그룹 값 적용 결과가 대칭.
- **V-RG-9 view**: 치수선 p0·p1이 맞보는 측면 위에 있고 |p1−p0| = 값(tol), `faces.moving` = 하류 리브.
- **V-RG-10 플랫폼**: 그룹 `rib_gap` 정규화·422 검증, `ExtractFilter` openapi, fake_paicad 반영, ①-2·④ 표 RIB_GAP mm·툴팁, `RIB_GAP_JOINT_RANGE` 경고, 용어집 정적 시험, `frontend-dist` 최신, altair 무변경(V-EF-12 방식).
- **V-RG-11 버전**: paicad 0.14.0 + CHANGELOG(영향: RIB_GAP 미선택은 결과 불변), `scripts/test-all` 통과.

## 11. 변경 범위·구현 분해

| 담당 | 범위·파일 | 순서 |
|---|---|---|
| Impl-Geom(paicad **0.14.0**) | `features.py`(열 인식 §3, 칸막이 인식 §3.3, RIB_GAP, `rib_rows`, 비기준 RIB_POS 제거·짝 열 기준, `RIB_GAP_TYPES`·`ABS_RANGE_TYPES`, MIRROR 같은 열 제외, 통계), `extract.py`(마무리 단계 순서·`rib_rows` 출력), `options.py`(`rib_gap{anchor, min_gap_mm, slender_min, overlap_min}` 검증, filter 종류 13), `update.py`(단계 3.5·`RIB_ROW_SHIFT`·사후 검사·`update.json rib_rows`), `collision.py`(`RIB_GAP_MIN`), `measure.py`(`rib_gap`), `check.py`·`quality.py`(파생 두께 항목·`quality.rib_rows`), `sweep.py`·`view/manifest.py`·`render.py`(치수선)·`paramap.py`(범주 `rib_gap`)·`selftest.py`(열 통계), 시험(`make_ribrow.py`·`test_rib_gap.py`), `__version__`·CHANGELOG | 먼저 착수 |
| Impl-Backend | `geometry/extract_filter.py`, `schemas`(ExtractFilter 열거값·features `rib_rows` 통과), native-vars 저장 검증(`RIB_GAP_JOINT_RANGE`), `backend/openapi.json`, MCP 용어집, `fake_tools/fake_paicad`, 시험. migration 없음 | Geom과 병행(fake 사용). openapi 먼저 |
| Impl-Frontend | `ExtractFilterFields`(체크박스·도움말), `lib/geometry.ts`·`lib/extractFilter.ts`, ①-2·④ 변수 표(mm·툴팁·경고), mock·시험, `frontend-dist` | openapi 갱신 뒤 |
| 릴리스 | v0.2.10 다음 버전에 배정(roadmap). 설정 키 없음(`geometry.defaults.rib_gap`로 기본값 덮어쓰기만 허용 — `extract.filter`와 달리 인식 옵션) | 사용자 결정 뒤 |

## 12. 사용자 결정(대기 — 결과가 바뀌는 것만)

| # | 질문 | 권고(기본값) | 바뀌는 것 |
|---|---|---|---|
| Q1 | "리브 간 거리" 값을 맞보는 면 사이 거리(clear gap)로 할지, 리브 중심 간 거리(피치)로 할지 | clear gap | 변수 값·범위·최소 간격 검사·치수선 위치 |
| Q2 | 간격을 바꿀 때 고정할 리브: 첫 리브(한쪽 끝)인지 가운데 리브인지 | 첫 리브(`first`). 대칭 배치를 유지하려면 center | 어느 리브가 움직이는지, 끝 여유를 어떻게 소비하는지, 범위 상한 |
| Q3 | 실물 리브 형태: 바닥에서 솟은 독립 리브만인지, 양끝이 외벽에 붙은 칸막이 리브도 있는지(격자·홈 사이 벽은 후속) | 둘 다 포함(칸막이 인식 확장 §3.3) | 인식 대상·구현 규모(T2 미포함이면 §3.3·V-RG-6 삭제) |

## 변경 메모

(구현 중 계약과 달라지면 `RG-C1~`로 기록하고 Plan 확인.)
