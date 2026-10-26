# 계약: native 리브 간격(피치) 파라미터(RIB_PITCH) — 두께는 그대로 두고 리브 간 거리를 하나씩 조절

> 상태: **확정**(2026-10-26, 사용자 결정 Q1~Q3 반영 — §12). 릴리스 **v0.2.11**(같은 버전의 DOE 그리드 미리보기 doe-preview.md와 함께, 리브 간격은 migration 없음). 상위 계약: [geometry-engine.md](geometry-engine.md)(GE), [extract-filter.md](extract-filter.md)(EF). 이 문서가 바꾸는 GE·EF 규칙은 §2.3에 모았고 GE 변경 메모 GE-C23·EF 변경 메모 EF-C3에 연결한다. 충돌하면 이 문서가 우선한다. 변경 메모 번호는 RG-C1부터 쓴다.

## 0. 한 줄 요약

paicad `extract`가 같은 방향으로 나란히 선 **독립 돌출 리브**를 **리브 열**로 묶고, 이웃 리브의 **중심 간 거리(피치)**를 간격마다 독립 변수 `RIB_PITCH_U_k`/`RIB_PITCH_V_k`로 만든다. 열의 **가운데 리브는 고정**한다(리브 수가 짝수면 가운데 두 리브 중심의 중점을 고정). 피치 k를 바꾸면 그 바깥쪽(가운데에서 먼 쪽)에 있는 리브 전부가 **강체 평행 이동**한다. 리브마다 윗면과 측면 전부를 같은 벡터로 옮기므로 리브 두께는 정확히 유지되며, update에서 두께가 변하지 않았는지 검사한다. 노드 ID는 그대로 두고(R1) 모핑한다. 추출 조건에서 "리브 간격(피치)"을 고르지 않으면 현재 출력과 바이트 단위로 같다.

## 1. 배경·원인

### 1.1 사용자 요청(2026-10-26)

- 원문: "형상파라미터 정의할때 리브간 거리는 잘 안되더라고. 리브가 일정두께를 유지한채 각 거리를 조절하려고해."
- 결정(2026-10-26): Q1 간격 값 = 리브 중심 간 거리(피치). Q2 고정 리브 = 가운데 리브. Q3 칸막이 리브(양끝이 외벽에 붙은 리브)는 제외하고 독립 돌출 리브만 대상으로 한다.

### 1.2 현재 동작(v0.2.10 = fb644a1, paicad 0.13.0)

리브 관련 변수는 RIB_THICKNESS(한쪽 측면만 Δ), RIB_HEIGHT(윗면 Δ), RIB_POS_U/V(EF §3.2, 윗면과 측면을 평행 이동하며 값은 바디 bbox 최소에서 잰 중심 좌표) 세 가지다. **간격 자체를 나타내는 변수는 없다.**

### 1.3 "잘 안 되는" 원인 추정(코드 근거. 이 작업 환경에는 OCP가 없어 실행 확인은 하지 못함)

| # | 원인 | 코드 근거 | 증상 |
|---|---|---|---|
| C1 | 간격 = 두 위치 값의 차 | `features._rib_pos`: 값 = 측면 중심 − bbox 최소 | 간격 하나를 바꾸려면 변수 두 개를 함께 움직여야 한다. 리브 하나를 옮기면 양옆 간격이 동시에 바뀐다 |
| C2 | 범위·여유를 이웃이 공칭에 있다고 가정하고 리브마다 따로 계산 | `_rib_pos_feasible`: 이웃 리브 측면까지 거리 − 0.5 mm, 범위 ±`position_range_mm`(5 mm) | DOE에서 이웃 두 리브가 서로 다가가면 각각은 범위 안이어도 발자국이 겹친다 → `BOUNDARY_OVERLAP` → `GEOM_FEATURE_COLLISION`(종료 10)으로 샘플 실패 |
| C3 | 위치 기준이 샘플마다 바뀜 | `update.nearest_fixed_face`: "이번 샘플에서 움직이지 않는" 가장 가까운 면을 기준으로 삼음(`rib_shifted` 제외) | sweep에서는 이웃 리브 측면, DOE에서는 벽이 기준이 된다. 벽 THICKNESS가 함께 바뀌면 간격이 의도와 다르게 변한다 |
| C4 | 간격을 두께 계열 변수로 바꾸면 두께가 함께 변함 | `update.plan_body` 단계 3: RIB_THICKNESS·POCKET_WIDTH·THICKNESS는 `pair_ref`가 고른 **한쪽 면만** 이동. 포켓 벽은 `claimed`라 홈 사이 벽에는 두께 변수가 없음 | 간격을 바꾸면 이웃 리브 두께가 바뀐다. "일정 두께 유지"와 충돌한다 |
| C5 | 리브 인식 범위가 좁음 | `_find_protrusions(+1)`: 윗면 외곽 엣지가 전부 볼록이고 측면 바깥 엣지가 **밑면 하나에만** 오목 | 칸막이 리브(`cap_not_convex`·`base_mismatch`), 격자(`base_mismatch`), 블렌드가 있거나 구배 > 3°인 리브(EF R1)는 리브가 아니다. 이번 범위에서도 제외한다(Q3). 사유는 `extract_stats.json` `rib_rejects`로 계속 보여 준다 |
| C6 | 공칭이 같으면 대칭 그룹으로 묶임 | GE §6.2 MIRROR | 등간격 열의 피치 k와 n−k가 한 그룹으로 묶일 수 있다 → 같은 열 안에서는 그룹화를 금지한다(RG-3) |

시험 fixture로 확인한 것: 가상 쿠션(`tests/data/make_synthetic.py`)은 바디마다 U 방향 리브가 2개뿐이고 그 사이에 포켓이 있어 간격 시험용이 아니다. 새 fixture를 만든다(§10).

### 1.4 쿠션 리브 배치 유형

| 유형 | 모양 | 이 계약 |
|---|---|---|
| T1 평행 독립 리브 열 | 밑면에서 솟은 직사각 리브가 한 방향으로 나란히 섬 | **범위** |
| T2 칸막이 리브 열 | 한쪽 끝이나 양끝이 외벽 안쪽 면에 붙은 리브 | **제외**(Q3). 인식되지 않으며 사유는 `rib_rejects`(`cap_not_convex`·`base_mismatch`)로 보인다 |
| T3 홈 사이 벽 | 위에서 판 포켓 사이 벽이 리브 역할 | 후속 |
| T4 격자 | U·V 리브 교차 | 후속(교차 측면 분할 면 재구성 규칙 필요) |
| T5 바디 경계와의 관계 | 열 양 끝 리브 ↔ 외벽(또는 밑면 끝) 거리 | 변수가 아닌 **끝 여유**. 양 끝(−a·+a)이 각각 바깥쪽 누적 변화를 흡수하고, 범위 상한의 근거가 된다(§5) |
| T6 엇갈린 배치 | 한쪽 이웃 후보가 2개 이상 | 그 지점에서 열을 끊음(`row_branch`) |

### 1.5 범위·비범위

- 범위: paicad `extract`(열 인식·RIB_PITCH·`rib_rows`), `update`(열 강체 이동·두께 불변 검사), `morph`(새 알고리즘 없음), `check`(피치·두께 재측정, 열 영역 품질 보고), `sweep`, `view`, `paramap`. 플랫폼에서는 추출 조건 그룹 `rib_pitch`, 변수 표(①-2·④), 경고, 문구, fake_paicad, MCP 용어집.
- 비범위: T2·T3·T4, altair(SimLab·NX) 경로(EF U3와 같음), 쉘, 재메시, 리브 개수 변경(다중 baseline GE-13).

## 2. 용어·결정

### 2.1 용어

| 용어 | 뜻 |
|---|---|
| 리브 열(row) | 같은 바디, 같은 밑면, 같은 두께 축 a에서 이웃 관계로 사슬처럼 이어진 독립 돌출 리브 2개 이상. a 오름차순으로 r_1..r_n, 피치는 p_1..p_{n−1} |
| 두께 축 a | 리브 윗면의, 밑면 평면 안 bbox에서 짧은 변 방향(전역 축). 다른 쪽 축 b는 리브 길이 방향 |
| 리브 중심 c_i | r_i의 −a 측면과 +a 측면 centroid a 성분의 평균(RIB_POS `rib_center`와 같은 정의, bbox 빼기 없음) |
| 피치 p_k | c_{k+1} − c_k(이웃 리브 중심 간 a 방향 거리) |
| 빈 간격 g_k | 맞보는 측면 사이 거리 = p_k − (t_k + t_{k+1})/2. 변수가 아니며 표시와 검사에만 쓴다 |
| 기준(anchor) | 홀수 n: 가운데 리브 r_m(m = (n+1)/2)의 중심. 짝수 n: 가운데 두 리브 r_h·r_{h+1}(h = n/2) 중심의 중점 M |
| 바깥쪽 리브 | 피치 p_k를 기준으로 기준의 반대쪽에 있는 리브들. p_k가 바뀌면 이들이 함께 이동한다 |
| 끝 여유 R⁻·R⁺ | 열 양 끝 리브의 바깥 측면에서 a 방향으로 다음 장애물(a에 수직이고 발자국 영역과 겹치는 평면, 또는 밑면 bbox 경계)까지 거리 − `WALL_MIN_MM`(0.5) |

### 2.2 결정(RG-1~RG-11)

| ID | 결정 |
|---|---|
| RG-1 | 새 종류 `RIB_PITCH_U`·`RIB_PITCH_V`(약어 = 종류 이름, 이름 예 `CUSH_L_RIB_PITCH_U_1`). `TYPE_ORDER` 맨 뒤(`… RIB_POS_U, RIB_POS_V, RIB_PITCH_U, RIB_PITCH_V`)에 두며, 필터 `types`에 있을 때만 생성한다 |
| RG-2 | 값 = **피치**(중심 간 거리, Q1). `measure.method = "rib_pitch"`. 같은 샘플에서 리브 두께가 바뀌면 피치는 유지되고 **빈 간격 g가 바뀐다**(g = p − 두께 반합) |
| RG-3 | 피치마다 독립 변수. **같은 열 안에서는 대칭 그룹을 만들지 않는다.** 바디 간(L↔R) 대칭은 기존 규칙(가운데 기준은 대칭에서 그대로 대응) |
| RG-4 | 고정 규칙 = **가운데 고정 + 양쪽 바깥으로 누적 이동**(Q2). 옵션 `rib_gap.anchor` = `center`(**기본**)·`first`·`last`. extract 때 열마다 정해 features에 기록하며, update는 그 기록만 따른다 |
| RG-5 | 강체 평행 이동: 리브의 moving 면(윗면 + 측면 전부)에 같은 a 방향 벡터를 더한다. 밑면 surface는 그대로 두고 발자국 와이어만 다시 계산한다(GE-C7). 열 소속 리브의 두께 변화(RIB_THICKNESS 등)는 **중심을 유지한 채 양쪽으로 ½씩** 반영된다(사슬이 중심을 정하므로). rebuild 뒤 피치·두께를 재측정해 `body_tol`을 넘으면 실패한다 |
| RG-6 | RIB_POS와의 관계 = **배타**. 같은 축의 RIB_PITCH를 고르면 열 소속 리브의 그 축 RIB_POS는 **홀수 열의 가운데 리브만 남긴다**(통계 사유 `row_member`). 남은 RIB_POS는 열 전체를 평행 이동한다. 짝수 열은 RIB_POS를 남기지 않으므로 열 전체를 옮기는 변수가 없다. RIB_PITCH를 고르지 않으면 현행과 같다 |
| RG-7 | 범위는 절대 mm로, 공칭 ∓ `extract.position_range_mm`. **하한 = (t⁰_k + t⁰_{k+1})/2 + `rib_gap.min_gap_mm`**(기본 1.0). 상한은 바깥쪽 끝 여유를 같은 쪽 피치 수로 나눈 **공동 안전값**이다. update는 샘플 두께 t′로 하한을 다시 검사한다(§4.3·§5) |
| RG-8 | 모핑 알고리즘은 바꾸지 않는다. check에 피치·두께 재측정과 열 영역 품질 보고를 더하며, 합격 기준은 기존 `quality`를 쓴다 |
| RG-9 | 조건 키는 없다(행 완전성). 열 구성은 `position_min_size_mm`의 영향을 받지 않는다 |
| RG-10 | 화면: ①-1 추출 조건에 새 그룹 `rib_pitch` "리브 간격(피치)"을 "위치(구멍·리브)" 바로 뒤에 둔다. 변수 표는 mm 길이로, 3D 치수선은 기존 `linear`를 재사용한다 |
| RG-11 | paicad **0.14.0**(MINOR), 릴리스 **v0.2.11**. DB·migration 없음. API 모양은 `ExtractFilter.groups` 열거값 1개 추가뿐이다 |

옵션 절 이름은 `rib_gap`(options.json `rib_gap{anchor, min_gap_mm, slender_min, overlap_min}`)이다. `min_gap_mm`이 빈 간격 하한이라서 이렇게 둔다. 계약 파일 이름도 rib-gap.md를 유지한다.

### 2.3 GE·EF에서 바뀌거나 더해지는 규칙(이 문서 우선)

- GE §4.3: 약어 `RIB_PITCH_U`·`RIB_PITCH_V`, `measure.method`에 `rib_pitch`, `parameter_features.json` 최상위 선택 키 `rib_rows`(RIB_PITCH가 있을 때만), 피처 선택 키 `row`. `schema_version`은 1을 유지한다.
- GE §4.6: `update.json` 가산 키 `rib_rows[]`, `applied[].op` 값 `RIB_ROW_SHIFT`, `ref_rule` 값 `row_anchor`.
- GE §6.2: 종류 표에 RIB_PITCH 행. MIRROR는 같은 `row.id`끼리 묶지 않는다.
- GE §6.3: 단계 3(그룹 피처)과 단계 4(위치) 사이에 **단계 3.5 열 이동**을 넣는다. 열 이동 면은 HOLE_POS·RIB_POS의 `nearest_fixed` 기준에서 제외한다. 충돌 사전 검사에 kind `RIB_PITCH_MIN`을 추가한다.
- GE §6.5: check (a) `rib_pitch` 항목·`rib_row_thickness` 파생 항목, (c) 보고 키 `quality.rib_rows[]`.
- EF §3.1: 그룹 `rib_pitch`(종류 `RIB_PITCH_U`·`RIB_PITCH_V`, 조건 없음) → 그룹 6개, 종류 13개.
- EF §3.2·EF-C1-2: 열 모드의 가운데 리브 RIB_POS는 `expected_measured` = 공칭 + Δ다(두께 이동에 따른 중심 변위를 더하지 않음 — 열에서는 두께가 중심 기준 대칭이므로).
- EF §5.1 EF-INV: 기준 결과 R_all은 "같은 RIB_PITCH 선택 여부"에서 전 종류·조건 없음으로 정의한다. RIB_PITCH를 고른 결과에서 열 소속 RIB_POS가 빠지는 것은 정의상 예외다. RIB_PITCH 피처는 면 소유자가 되지 않고 `claimed`를 바꾸지 않는다.

## 3. 열 인식(extract)

### 3.1 리브 후보(독립 돌출 리브만)

1. `_find_protrusions(+1)`로 인식된 리브(cap·lats·base)만 대상이다. 칸막이·격자·블렌드 리브는 기존처럼 리브가 아니며 사유는 `rib_rejects`에 남는다(Q3).
2. 밑면 법선이 전역 축 k와 1° 이내여야 한다(RIB_POS와 같은 `cos1`). 아니면 `base_axis`.
3. 두께 축 a = 나머지 두 축 가운데 cap bbox 변이 짧은 쪽. 긴 변 / 짧은 변 < `rib_gap.slender_min`(기본 1.5)이면 기둥형(`not_slender`).
4. 법선이 +a인 측면과 −a인 측면(각 ≤ `draft_max_deg`)이 각각 정확히 1개여야 한다(RIB_POS `shape` 규칙). 아니면 `shape`.

### 3.2 이웃·열 구성

- r_j가 r_i의 +a 이웃이 되는 조건: (i) 같은 바디, 같은 밑면 id, 같은 a (ii) r_j −a 측면 centroid[a] > r_i +a 측면 centroid[a] + 1e-6 (iii) 두 리브 측면의 b 구간이 겹치는 길이 ≥ `rib_gap.overlap_min`(기본 0.5) × 짧은 리브 길이 (iv) 두 면 사이 띠(a 구간 × 겹친 b 구간)에 a에 수직인 다른 평면이 영역을 겹쳐 들어 있지 않음. 조건을 만족하는 후보 가운데 가장 가까운 것을 이웃으로 정한다.
- 분기: +a 이웃 후보가 같은 거리(1e-6 이내)로 2개 이상이거나, 한 리브가 둘 이상의 리브에게 이웃으로 선택되면 그 연결을 모두 끊는다(`row_branch`).
- 열 = 연결된 리브 2개 이상의 최대 사슬. 열 id = `<U|V><번호>`이며, 번호는 바디 안에서 (축, 첫 리브 a 좌표, b 좌표) 오름차순. 피치 이름의 k는 바디·종류 안에서 (열 번호, 열 내 순서) 순으로 매긴다.
- 통계 `types.RIB_PITCH_*`: `candidates`, `kept`, `excluded{base_axis, not_slender, shape, row_branch, row_single}`. `types.RIB_POS_*.excluded.row_member` = 열 소속이라 빠진 RIB_POS 수.

### 3.3 기준·대칭

- `center`(기본): 홀수 n → m = (n+1)/2, `anchor: "rib:<m>"`. 짝수 n → h = n/2, `anchor: "mid:<h>"`(r_h·r_{h+1} 중심의 중점 M 고정). `first` → `"rib:1"`, `last` → `"rib:<n>"`.
- 바디 간 대칭: `center`는 대칭에서 그대로 대응하므로 추가 규칙이 없다. `first`·`last`이고 짝 열(다른 바디, 같은 a, 같은 n, 리브 중심이 MIRROR 평면에 대해 tol 안에서 대칭)의 대칭 평면이 a에 수직이면, 짝 열의 기준은 대표 열 기준의 대칭 짝이다(n+1−m).
- RIB_PITCH MIRROR: 같은 `row.id` 쌍은 후보에서 뺀다. 바디 간 짝 열의 피치끼리는 기존 `_is_mirror` 판정을 쓴다.

### 3.4 출력(`parameter_features.json`)

```json
"rib_rows": [
  {"id": "U1", "body": "CUSH_L", "axis": "x", "base": "F3", "anchor": "rib:3",
   "ribs": [{"index": 1, "cap": "F21", "minus": "F22", "plus": "F24", "moving": ["F21","F22","F23","F24","F25"],
             "thickness": 6.0, "center": 28.0}],
   "end_room_mm": {"minus": 12.4, "plus": 18.0}, "end_limited_by": {"minus": "CUSH_L_THK_2", "plus": null},
   "face_signatures": {"F21": "…"}}
]
```

- 피처 RIB_PITCH: `nominal` = p_k, `faces` = r_k·r_{k+1}의 cap·측면 + 밑면, `measure.faces` = [r_k −a, r_k +a, r_{k+1} −a, r_{k+1} +a 측면], `measure.method = "rib_pitch"`, `axis`, `faces.moving` = 바깥쪽 리브 전부의 moving 면, `faces.fixed` = [밑면], `row = {"id": "U1", "k": 1, "n": 5}`.

## 4. 값·update

### 4.1 기호

공칭 리브 중심 c_i, 두께 t⁰_i, 단계 1~3에서 이미 정해진 측면 이동의 a 성분 τ⁻_i·τ⁺_i(`T[face][a]`)를 쓴다. 샘플 두께는 t′_i = t⁰_i + τ⁺_i − τ⁻_i, 두께 이동에 따른 중심 변위는 τ̄_i = (τ⁻_i + τ⁺_i)/2, 공칭 피치는 p⁰_k, 샘플 피치는 p_k다. 리브 i의 목표 중심 c′_i와 강체 이동량 s_i를 구한다.

### 4.2 열 이동(단계 3.5)

1. 기준 중심
   - 홀수(`rib:m`): c′_m = c_m + Δpos(가운데 리브 RIB_POS의 값 − 공칭, 없거나 공칭이면 0).
   - 짝수(`mid:h`): c′_h = M − p_h/2, c′_{h+1} = M + p_h/2, M = (c_h + c_{h+1})/2(공칭, 고정).
   - `first`·`last`: c′_m = c_m + Δpos(m = 1 또는 n).
2. 바깥쪽 누적(양쪽)
   - +a 쪽: c′_i = c′_{i−1} + p_{i−1}  (기준 다음 리브부터 i = n까지)
   - −a 쪽: c′_i = c′_{i+1} − p_i  (기준 앞 리브부터 i = 1까지)
3. 강체 이동: s_i = c′_i − c_i − τ̄_i. 리브 i의 moving 면마다 `add(face, s_i·e_a)`를 한다. 결과 중심은 c′_i(정확)이고 두께는 t′_i이며, 두께 변화는 중심 기준 대칭이다.
4. 열 이동 면은 축 a의 `rib_shifted`에 넣는다(HOLE_POS·RIB_POS의 `nearest_fixed` 기준에서 제외).
5. `applied[]`: RIB_PITCH마다 `op: "RIB_ROW_SHIFT"`, `moved` = 이 피치 때문에 움직인 바깥쪽 면, `fixed` = [밑면], `ref_rule: "row_anchor"`.
6. 방어 규칙: features에 열 소속이지만 남기지 않은 RIB_POS(수작업 파일 등)가 있고 그 값이 공칭과 다르면 → `GEOM_INPUT_INVALID`(종료 3) "RIB_PITCH_POS_CONFLICT: rib position and rib pitch on the same row".

### 4.3 사전 검사·두께 불변 검사

- 사전 검사(rebuild 전): 빈 간격 g′_k = p_k − (t′_k + t′_{k+1})/2 < `rib_gap.min_gap_mm` − 1e-9이면 collision kind `RIB_PITCH_MIN` → `GEOM_FEATURE_COLLISION`(종료 10, 메시지에 피치 이름·피치·빈 간격). 즉 샘플 두께로 하한을 다시 잰다. 기존 `BOUNDARY_OVERLAP`·`WALL_PENETRATION`도 그대로 적용한다(양 끝 리브의 벽 통과 포함).
- 사후 검사(rebuild 뒤 `sample.brep`): 열마다 각 피치·리브 두께를 측면 centroid로 재측정한다. |오차| > `options.body_tol`이면 `GEOM_CAD_FAILED`(종료 10) "rib row drift: <name> expected … measured …".
- `update.json` `rib_rows[]` = `{id, body, axis, anchor, ribs[{index, shift_mm, center_expected, thickness_expected, thickness_measured}], pitches[{name, value, measured, gap}], end_room_mm{minus, plus}}`(사후, `gap` = 빈 간격). 가산 키다.

### 4.4 피치를 쓸 때 주의(문구·문서에 반영)

- 피치는 두께와 독립적이다. 같은 샘플에서 RIB_THICKNESS를 키우면 피치는 그대로이고 **빈 간격이 두께 증가의 절반씩 양쪽에서 줄어든다**. 빈 간격 하한은 update에서 샘플 두께로 검사한다(§4.3).
- 화면 툴팁: "리브 간격 = 이웃 리브 중심 사이 거리(피치). 두께를 함께 바꾸면 리브 사이 빈 틈이 달라집니다."

## 5. 범위·feasible·envelope

- 쪽 배정: 기준보다 +a 쪽에 있는 피치는 R⁺를, −a 쪽 피치는 R⁻를 쓴다. 짝수 열의 가운데 피치 p_h는 양쪽에 ½씩 쓴다(가중 ½). 홀수 열에서는 m 앞의 p_1..p_{m−1}이 −a 쪽, p_m..p_{n−1}이 +a 쪽이다.
- `feasible`(변수 하나만 바꿀 때): min = (t⁰_k + t⁰_{k+1})/2 + `min_gap_mm`. max = p⁰ + R_side(가운데 피치는 p⁰ + 2·min(R⁻, R⁺)). `limited_by`는 그 쪽 끝 장애물 면의 소유 피처(없으면 null).
- `range`(공동 안전): 쪽마다 가중치 합 W(바깥 피치 1, 가운데 피치 ½)를 구하고 u = R_side / W로 둔다. 범위 = [max(min, p⁰ − P), p⁰ + min(P, u_side)](가운데 피치는 min(P, u⁻, u⁺)). P = `position_range_mm`이다. 범위 안의 어떤 조합이든 양 끝 리브가 장애물에 닿지 않는다. 피치를 줄이는 방향은 가운데로 당기므로 끝 여유를 쓰지 않는다.
- 플랫폼 경고(차단 없음) `RIB_PITCH_JOINT_RANGE`(변수 표 저장 시, ①-2·④ native-vars):
  - 한쪽 Σ(가중치 × (상한 − 공칭)) > 그 쪽 끝 여유: "같은 리브 열(U1)의 +쪽 피치 상한 합이 끝 여유 18.0 mm를 넘습니다 — 일부 샘플이 형상 생성에 실패할 수 있습니다".
  - 이웃 두 리브의 RIB_THICKNESS 상한 반합 + `min_gap_mm` > 피치 하한: "리브 두께 상한에서 빈 간격이 최소 간격보다 작아질 수 있습니다".
  - 가운데 RIB_POS와 피치를 함께 쓰면서 |RIB_POS 범위| + 쪽 증가 합 > 끝 여유이면 같은 경고.
  - 양 끝 리브의 RIB_THICKNESS 증가 ½도 끝 여유를 쓰므로 합산한다.
- 남는 위험: 밑면 위 구멍·포켓 입구가 이동 경로에 있으면 `BOUNDARY_OVERLAP`이 날 수 있다(샘플 실패 경로 그대로).
- sweep: RIB_PITCH는 mm 단계 계열(`--pos-steps`), 행 `unit: "mm"`. 단계마다 피치 하나만 바꾸며, envelope 행에 §6 열 영역 품질 요약을 붙인다.
- 상수: `features.py`에 `RIB_PITCH_TYPES`, `ABS_RANGE_TYPES = POSITION_TYPES + RIB_PITCH_TYPES`(절대 mm 범위·mm sweep)를 정의한다. `POSITION_TYPES`에는 넣지 않는다.

## 6. morph·check

- morph: 새 규칙 없음. cap·측면 노드는 면 UV 대응으로 움직이고, 밑면은 발자국(내부 와이어)이 이동한 면이므로 GE §6.4-1 대체 규칙을 쓴다. 리브 사이 바닥은 a 방향으로 대략 g′/g⁰ 비율로 늘거나 줄고, 양 끝 여유 영역이 바깥쪽 누적 변화를 흡수한다. 노드 ID·요소 연결은 바뀌지 않는다(R1).
- check (a):
  - `rib_pitch` 항목: 모핑 메시에서 각 리브의 ±a 측면 외피 삼각형 면적 가중 centroid[a] 평균으로 중심을 구하고, 이웃 중심 차를 값과 비교한다(`deviation.param_abs_mm`).
  - 파생 항목 `kind: "rib_row_thickness"`(이름 `<body>:<row id>:<index>`): 이동한 리브마다 측면 centroid 차를 `thickness_expected`와 비교하며 같은 허용오차를 쓴다. FAIL이면 param도 FAIL이다.
- check (c): 합격 기준은 기존 `quality` 그대로다. 보고 키 `checks.quality.rib_rows[]` = 빈 간격 영역과 양 끝 여유 영역마다 `{name|end_minus|end_plus, elems, ratio(g′/g⁰ 또는 끝 여유 비), min_edge_ratio, max_aspect, min_stretch, dt_ratio, status}`. 영역 = 요소 centroid가 맞보는 두 측면(모핑 후) 사이 a 구간과 겹친 b 구간 안에 있고 cap 높이 아래에 있는 요소다. 전체 판정은 바꾸지 않고 어느 간격이 품질을 깨는지 귀속만 한다.
- 지침: 기준 메시에서 빈 간격 압축비 g′/g⁰ < 0.8이면 `min_edge_ratio` 0.8에 걸리기 쉽다. 한계는 envelope로 잰다.

## 7. view(geometry-view 재사용)

- `view_manifest.json` RIB_PITCH: `dimension.kind: "linear"`, `p0` = r_k 중심 평면 위 점(두 리브 b 겹침 구간 중앙, 높이 중앙), `p1` = p0를 r_{k+1} 중심 평면에 a 방향으로 투영한 점, `value` = 값. `faces.moving` = 바깥쪽 리브 면(미리보기는 `update.json.applied[].moved`), `fixed` = [밑면], `other` = measure 면. 선택 키 `row {id, k, n}`.
- PNG 치수선도 같은 두 점으로 그린다. 프런트는 그리는 코드를 바꾸지 않으며(linear), 표 행을 선택하면 바깥쪽 리브 전부가 하이라이트된다.

## 8. 플랫폼·화면

| 위치 | 변경 |
|---|---|
| `physicsai_core/geometry/extract_filter.py` | `GROUP_TYPES["rib_pitch"] = ("RIB_PITCH_U", "RIB_PITCH_V")`(`position` 뒤), `GROUP_LABELS` "리브 간격(피치)", 조건 없음, `TYPE_LABELS` "리브 피치 U/V", `EXCLUDED_LABELS` `not_slender` "기둥형", `row_branch` "열 분기", `row_single` "이웃 없음", `row_member` "간격 열 소속" |
| openapi `ExtractFilter.groups` | 열거값 `rib_pitch` 추가. `GET …/features`는 `rib_rows`를 그대로 전달한다(스키마가 extra를 막으면 선택 필드로 추가) |
| ①-1·④ `ExtractFilterFields` | 체크박스 "리브 간격(피치)"를 "위치(구멍·리브)" 바로 뒤에 둔다. 도움말: "같은 방향으로 나란한 독립 리브의 중심 간 거리(리브 두께 유지, 가운데 리브 고정). 고르면 열의 가운데 리브만 위치 변수로 남습니다. 벽에 붙은 리브·격자는 대상이 아닙니다." 프리셋(U1): 새 Study는 6개 모두 체크, 마지막 사용 조건이 있는 Study는 그 값(키가 없으면 미체크) |
| ①-2·④ 변수 표(native-vars) | RIB_PITCH는 길이 mm(좌표 아님, `isPositionType` 아님)로, 하한·상한 절대 mm와 공칭 대비 Δ를 보인다. 행 툴팁 "열 U1 · 피치 2/4 · 가운데 리브 3 고정 · 빈 간격 14.0 mm" + §4.4 문구. 경고 `RIB_PITCH_JOINT_RANGE`. "적용 조건" 줄에 "리브 간격(피치)" |
| `lib/geometry.ts` | 종류 문구, `isPitchType`, 절대 mm 범위 판정에 RIB_PITCH |
| MCP 용어집 | `RIB_PITCH_U`·`RIB_PITCH_V` `ko` 한 줄씩(정적 시험) |
| fake_paicad | `types`에 RIB_PITCH 허용, 합성 피치 피처·`rib_rows` 출력 |
| DB | 변경 없음 |

## 9. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 실물 리브가 칸막이·격자·블렌드형이면(C5) 피치 변수가 0개 | 제외 범위임을 도움말에 안내. `rib_rejects`·`row_*` 통계를 selftest로 회신받아 후속 계약(T2·T4) 판단 |
| R2 | 양 끝 여유 영역이 바깥쪽 누적 변화를 흡수해 품질이 먼저 깨짐 | §6 열 영역 보고로 귀속, `range` 공동 안전값, envelope |
| R3 | 큰 이동에서 밑면 조화 보간 품질 미달(EF R4) | 기본 범위 ±5 mm, envelope, 필요하면 후속으로 국부 영역 해(쉘 `morph.region` 선례) |
| R4 | 두께와 피치를 함께 쓰면 빈 간격이 작아져 샘플 실패 | update 사전 검사 `RIB_PITCH_MIN`, 플랫폼 경고(두께 상한 반합), 툴팁 |
| R5 | 짝수 열에는 열 전체 이동 변수가 없음 | 문서화(RG-6). 필요하면 후속으로 `mid` 이동 변수 |
| R6 | RIB_PITCH를 고르면 열 소속 RIB_POS가 사라져 혼동 | 도움말, "적용 조건" 표시, 기존 Study 프리셋은 미체크 유지 |
| R7 | 구멍·포켓이 이동 경로에 있으면 범위 안에서도 충돌 | 기존 `GEOM_FEATURE_COLLISION` 경로, feasible 안내 |

## 10. 시험(V-RG-*)

합성 fixture `tests/data/make_ribrow.py`(build123d): 밑판 위에 a 방향 평행 독립 리브 3개(홀수)와 4·5개(짝수·홀수) 열(두께 6, 피치 공칭 서로 다름), 같은 바디 V 방향 열 1개, 양 끝 장애물(벽), L/R 대칭 바디 쌍, 칸막이형 변형 1개(제외 확인용), 구멍 1개(경로 충돌용). 정답 = 리브를 정답 좌표로 다시 만든 형상.

- **V-RG-1 하위호환**: `types`에 RIB_PITCH가 없으면 가상 쿠션·기존 골든 extract가 0.13.0과 바이트 동일하고 `rib_rows`가 없다. 기존 `test_rib_pos.py`·`test_extract_filter.py`를 수정 없이 통과한다.
- **V-RG-2 인식**: 3·4·5개 열 → 피치 2·3·4개, 이름·순서·`row`·`rib_rows`·`anchor`(`rib:2`·`mid:2`·`rib:3`)가 정답과 일치. 기둥형·꺾인 측면·엇갈린 배치 → `not_slender`·`shape`·`row_branch`. 열 사이에 벽 → 열 분리. 칸막이 리브 → 열 없음 + `rib_rejects` 사유. 열 소속 RIB_POS 미생성(홀수 가운데만 유지). EF-INV(같은 RIB_PITCH 선택 여부 기준)·결정성.
- **V-RG-3 update 정답**: 피치마다 +3·−3 mm 단독, 여러 피치 동시(±), 홀수·짝수 center, first·last → B-rep 면별 최대 거리 ≤ 0.01 mm, 부피 차 ≤ 0.1 %, 모든 리브 두께 변화 ≤ 1e-6 mm, 기준(가운데 리브 중심·짝수 중점 M) 이동 0, 짝수 가운데 피치 변화는 양쪽에 ½씩. RIB_THICKNESS 동시 변경 → 피치 = 값, 두께 = 값, 빈 간격 = 피치 − 두께 반합(중심 기준 대칭). 가운데 RIB_POS → 열 전체 이동, `expected_measured` = 공칭 + Δ.
- **V-RG-4 충돌·오류**: 피치 하한 미만, 그리고 두께 증가로 빈 간격 < `min_gap_mm` → `RIB_PITCH_MIN` 종료 10. 끝 여유 초과(+·− 각각) → `WALL_PENETRATION`/`BOUNDARY_OVERLAP` 종료 10. 구멍 경로 → `BOUNDARY_OVERLAP`. 수작업 RIB_POS 충돌 → `GEOM_INPUT_INVALID` 종료 3. 사후 drift 주입(fake kernel) → `GEOM_CAD_FAILED`.
- **V-RG-5 morph·check**: 노드 ID·요소 연결 불변, 경계 노드 ↔ 정답 ≤ 0.05 mm, 반전 0, check (a) `rib_pitch`·`rib_row_thickness` 오차 ≤ `param_abs_mm`, (c) `quality.rib_rows[]` 영역 키(간격·`end_minus`·`end_plus`)·비율 정답. 같은 입력 2회 `morphed.inc` 바이트 동일.
- **V-RG-6 범위·sweep**: `range` 공동 안전(양쪽 피치 모두 상한일 때 충돌 없음 — 실제 update로 확인), 하한 = 두께 반합 + min_gap, `feasible`, sweep `unit: "mm"`·열 품질 요약.
- **V-RG-7 대칭**: 같은 열 피치는 그룹 없음. L/R 짝 열 피치는 그룹이고 그룹 값 적용 결과가 대칭(center·first 각각).
- **V-RG-8 view**: 치수선 p0·p1이 두 리브 중심 평면 위에 있고 |p1−p0| = 값, `faces.moving` = 바깥쪽 리브.
- **V-RG-9 플랫폼**: 그룹 `rib_pitch` 정규화·422 검증, openapi, fake_paicad, ①-2·④ 표 mm·툴팁(빈 간격 표시), `RIB_PITCH_JOINT_RANGE` 세 경우, 용어집 정적 시험, `frontend-dist` 최신, altair 무변경.
- **V-RG-10 버전**: paicad 0.14.0 + CHANGELOG(영향: RIB_PITCH 미선택은 결과 불변), `scripts/test-all` 통과.

## 11. 변경 범위·구현 분해(v0.2.11)

| 담당 | 범위·파일 | 순서 |
|---|---|---|
| Impl-Geom(paicad **0.14.0**) | `features.py`(열 인식·RIB_PITCH·`rib_rows`·열 소속 RIB_POS 제거·기준 결정·`RIB_PITCH_TYPES`·`ABS_RANGE_TYPES`·MIRROR 같은 열 제외·통계), `extract.py`(마무리 순서·`rib_rows`), `options.py`(`rib_gap{anchor 기본 center, min_gap_mm, slender_min, overlap_min}` 검증, filter 종류 13), `update.py`(단계 3.5·`RIB_ROW_SHIFT`·사후 검사·가운데 RIB_POS 기대값), `collision.py`(`RIB_PITCH_MIN`), `measure.py`(`rib_pitch`), `check.py`·`quality.py`(파생 두께·`quality.rib_rows`), `sweep.py`·`view/manifest.py`·`render.py`·`paramap.py`(범주 `rib_pitch`)·`selftest.py`, 시험(`make_ribrow.py`·`test_rib_pitch.py`), `__version__`·CHANGELOG | 먼저 착수 |
| Impl-Backend | `geometry/extract_filter.py`, `schemas`(ExtractFilter 열거값·`rib_rows` 통과), native-vars 저장 경고(`RIB_PITCH_JOINT_RANGE`), `backend/openapi.json`, MCP 용어집, `fake_tools/fake_paicad`, 시험. migration 없음(v0.2.11의 `0025_doe_preview`는 doe-preview 소관, 이 기능과 무관) | Geom과 병행(fake), openapi 먼저(doe-preview와 openapi 재생성 순차) |
| Impl-Frontend | `ExtractFilterFields`, `lib/geometry.ts`·`lib/extractFilter.ts`, ①-2·④ 변수 표(mm·툴팁·경고), mock·시험, `frontend-dist` | openapi 갱신 뒤 |
| 설정 | 새 설정 키 없음. `geometry.defaults.rib_gap`으로 기본값 덮어쓰기만 허용(인식 옵션 — `extract.filter`와 다름) | — |

## 12. 사용자 결정(2026-10-26 확정)

| # | 질문 | 결정 |
|---|---|---|
| Q1 | 간격 값 정의 | **리브 중심 간 거리(피치)**. 변수 `RIB_PITCH_U/V`, `rib_pitch`, 하한 = 인접 두께 반합 + `min_gap_mm`, 두께를 함께 바꾸면 빈 간격이 바뀜 |
| Q2 | 고정 리브 | **가운데 리브**(짝수는 가운데 두 리브 중심의 중점). 옵션 `center`(기본)·`first`·`last`, 끝 여유는 양 끝 기준 |
| Q3 | 칸막이 리브 | **제외**(독립 돌출 리브만). 격자·홈 사이 벽도 후속. 인식 범위 밖 사유는 `rib_rejects`로 표시 유지 |

## 변경 메모

(구현 중 계약과 달라지면 `RG-C1~`로 기록하고 Plan 확인.)

- 2026-10-26 구현 통합 반영(RG-C, paicad 0.14.0 CHANGELOG의 "구현 해석"을 계약에 올림 — 실제 paicad 출력과 백엔드 파서를 `backend/tests/test_rib_pitch_real.py`로 대조):
  - **RG-C1 first·last 기준의 RIB_POS 대상**: 열 소속 RIB_POS는 **기준 리브**만 남긴다(`excluded.row_member`로 나머지 제외). 기준 리브는 center에서 RG-6 그대로(홀수 열 가운데 리브 `rib:m`, 짝수 열은 없음), `first`·`last`에서는 §4.2의 Δpos가 맞도록 1번·n번 리브(`rib:1`·`rib:n`)다. 그래서 `first`·`last`에서는 짝수 열도 RIB_POS 1개가 남아 열 전체를 옮긴다. features `rib_rows[].anchor`는 항상 `rib:<m>` 또는 `mid:<h>` 형태다(`first`·`last`도 `rib:1`·`rib:n`으로 기록, 실제 출력 확인).
  - **RG-C2 열 이웃 띠 검사는 높이를 보지 않는다**: 이웃 판정의 "띠 안에 a에 수직인 다른 평면 없음" 검사는 리브 높이와 무관하게 평면을 찾는다. 리브 사이 바닥 포켓 벽처럼 낮은 벽도 열을 끊는다(§2.1 열 정의·T5 "벽으로 열 분리"의 구현 범위 = 높이 불문). 열 id(`U1`·`V1`…)는 **바디마다 다시 매겨지므로** 바디가 다른 두 열이 같은 id를 가질 수 있다 — 소비자(플랫폼 `rib_rows` 조회·`RIB_PITCH_JOINT_RANGE` 묶음, 화면 툴팁)는 `(body, id)`로 열을 구분한다.
  - **RG-C3 `RIB_PITCH_MIN` 공칭 예외**: 사전 검사 collision kind `RIB_PITCH_MIN`(샘플 두께로 빈 간격 < `min_gap_mm`)은, 공칭 빈 간격이 이미 `min_gap_mm` 미만이면 **공칭보다 줄어드는 경우에만** 낸다(공칭 그대로는 통과). paicad 보고 코드는 `GEOM_FEATURE_COLLISION`이고 kind만 `RIB_PITCH_MIN`이다. 플랫폼 변수 표 저장 경고 코드는 별개로 `RIB_PITCH_JOINT_RANGE`(차단 없음)이며 화면은 두 코드 문구를 모두 가진다.
  - **RG-C4 V-RG-1 어휘 단언**: 기존 `tests/test_extract_filter.py`의 `TYPE_ORDER` 어휘 단언 1줄은 새 종류가 끝에 붙으므로(`… RIB_POS_U, RIB_POS_V, RIB_PITCH_U, RIB_PITCH_V`) 갱신했다. 그 밖의 기존 시험은 무수정 통과, RIB_PITCH 미선택 출력은 0.13.0과 바이트 동일(V-RG-1 판정은 이 어휘 단언 1줄을 제외한 기존 시험·출력 동일로 읽는다).
  - 부가(변경 없음): `quality.rib_rows[]`에 `row` 키, 통계 RIB_PITCH `kept` = 피치 수(제외 사유는 리브 수). 피처 `range.mm`은 `±` 폭(숫자), 피치 변수 풀 노출은 대칭 그룹 대표만이다.
