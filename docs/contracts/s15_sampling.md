> **phase3.md §20(변경 메모 D3-63)로 이관됨(2026-10-20).** 기준은 phase3.md이고, 이 파일은 상세 원문(알고리즘·표·시험 목록·파일 소유)으로 남긴다.

# 계약: S15 표본 방식 추가 — phase3 §20

> 이 문서는 phase3.md §20과 변경 메모 D3-63입니다. s12_s13.md·s14_analysis.md와 같은 이유(phase3.md 미커밋 변경)로 별도 파일로 둡니다. 다음 Plan 커밋에서 phase3.md 본문과 변경 메모 목록으로 옮깁니다. 절 번호·용어·원칙은 phase3.md·[s12_s13.md](s12_s13.md)·[s14_analysis.md](s14_analysis.md)를 따릅니다(§14 일괄 예측, §17 지표·design-map, §18 내장 최적화, §19 ⑤ 결과분석). 사용자 결정 2026-10-18(D3-63). **선행 조건**: S14(D3-62) 작업 트리 변경이 커밋된 뒤 시작합니다. **migration 1개**(`0012_sampling_kinds`, CHECK 확장만).

## 20. S15 표본 방식 추가 (사용자 결정 2026-10-18, D3-63)

목표: ④ 일괄 예측에 표본 방식 7개를 추가합니다(최적화 LHS, Sobol, 전체 요인, 부분 요인 2수준, Plackett–Burman, Box–Behnken, CCD). ①·④ 선택창에는 고를 때마다 방식 설명문을 보여 주고, 기본값은 추천 방식으로 둡니다. 배치·DOE에 표본 방식을 기록하고, ⑤ 영향도를 방식에 따라 정식·참고용으로 나눕니다. 1·2·3차 원칙(설정만, 한국어, 필수 UI, 파일 본문 DB 저장 금지, 원본·SPDM 읽기만, `shell=False`)은 그대로 유지합니다. 새 작업 종류·새 라우트·새 런타임 의존성은 없습니다(scipy는 S13에서 이미 의존성).

### 20.1 범위 / 비범위

| 범위 | 비범위(후속) |
|---|---|
| ④ `source.kind` 7종 추가(§20.5), 미리보기·작업 생성·워커가 같은 행을 씀(기존 원칙) | ⑤ 주효과·교호작용 그림 |
| ④ Sobol 이어서 추가(같은 시드·같은 범위, 새 배치로) | 대리모델 기반 Sobol 지수 |
| ①·④ 방식 선택창 설명문·추천 기본값(§20.4) | ① DOE를 플랫폼 표로 생성(§20.3 안 B, S16 후보) |
| ① DOE 유형 목록에 설명 id·추천·영향도 등급 추가(HyperStudy 유형은 정의 파일 그대로) | ①에 정의 파일 밖 HyperStudy 유형 추가(서버 확인 E1-8 뒤 관리자가 파일 편집) |
| 배치·DOE 표본 방식 기록 → ⑤ 영향도 정식·참고·비활성(§20.7) | 이어서 추가한 배치 여러 개를 ⑤에서 하나로 합쳐 분석 |
| | ⑥ 내장 최적화 탐색 배치에 최적화 LHS 적용(현재 LHS 유지) |
| | CCD 외접(회전형, 범위 밖 축점) |

### 20.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| S1 | ①은 **HyperStudy doe_type 목록을 그대로 보여 준다**(정의 파일의 4개). 새 방식은 ①에 넣지 않음 | §20.3 — pyd가 받는 value는 정의 파일의 4개만 확인됨, 지정 행렬 입력 경로 없음 |
| S2 | ④ 새 kind 7개: `lhs_opt`·`sobol`·`fullfact`·`fracfact`(해상도 IV·V)·`pb`·`bbd`·`ccd`. 기존 `lhs`·`table`·`train_doe`는 그대로 | 사용자 결정. 플랫폼이 표를 계산하는 기존 구조(§14.5 K3) 그대로 |
| S3 | **④ 기본 = 최적화 LHS(maximin)** | run 수 자유(기존 기본 20과 맞음, 2^m 제약 없음), 1차원 층화 유지 → 영향도 정식, 상관이 작아 SRC 조건수 안정, AI 학습·대리모델 겸용. Sobol은 run을 단계적으로 늘릴 때 추천(설명문에 명시) |
| S4 | **① 기본 = LatinHyperCube**(설정 `train_data.recommended_doe_type`, 기본 `TYPE_LATINHYPERCUBE`) | ①에서 확인된 유형 중 run 수가 자유롭고 s14 영향도 정식. 최적화 LHS는 ①에 없음. HyperStudy Sobol은 기본 Scramble=false. 현재 화면은 목록 첫 항목(FullFact)이 기본이라 바로잡음 |
| S5 | 알고리즘은 **결정적**. Sobol 외에는 순수 Python(`random.Random(seed)`), Sobol만 `scipy.stats.qmc.Sobol`을 **함수 안 지연 import**(`physicsai_core/sampling/qmc.py` 한 곳) | 사용자 허용(scipy 이미 의존성). LHS 계열을 순수 Python으로 두면 버전 차이가 없고 API 프로세스에서 numpy를 피함. S13 §18.2 "API는 numpy를 불러오지 않는다"는 **Sobol 미리보기·생성 때만 예외**(D3-63) |
| S6 | DB: `predict_batches.source_kind` CHECK만 확장(migration `0012_sampling_kinds`), 방식 인자는 기존 `source_meta` JSONB. ① DB 변경 없음 | §20.8 — CHECK 때문에 새 값을 넣으려면 migration이 필요. 메타만 쓰는 안(TABLE + meta.method)은 기존 의미(TABLE = 직접 표)와 어긋나 기각 |
| S7 | 영향도 등급 `influence_class` = `formal`(정식) / `reference`(참고, 회색 안내) / `off`(비활성, 사유). **등급은 서버가 정함**, n 조건은 s14 그대로(①은 서버, ④는 프런트) | s14 원칙("LHS 판정은 서버 `influence_ok`만")을 방식 전체로 넓힘 |
| S8 | 2차 설계(BBD·CCD) 중심점은 **1개 고정** | AI 예측은 같은 입력이면 같은 값이라 반복이 의미 없음 |
| S9 | CCD는 면중심(기본)·내접만 제공 | 외접(회전형)은 축점이 범위 밖 → AI 학습 범위 밖 예측 |
| S10 | 설명문은 계약에 고정한 한국어 문구(§20.4). 프런트 상수 1곳, 서버는 `desc_id`만 줌 | 문구 1벌, 서버·프런트 중복 없음 |

### 20.3 ① 구조 판단(근거)

현재 흐름(코드 확인):
- `GET /train/doe-types` → `physicsai_core/stage1_train_data/doe_types.load_doe_types(resources.doe_design_type_json)` → 원본 `CONFIG/DATA/DATA_doe_design_type.json` 그대로.
- `TD_DOE_GEN` params에 `doe_type` = 고른 항목의 `value`, `options` = fields 값(`services/job_params/stage1_train_data.py`). 워커 `DG_PREP`가 `INPUT_HST_RUN.json`에 `DOE_TYPE`·`DOE_METHOD_OPTIONS`를 쓰고, `HST_GEN_RADIOSS`가 `hstbatch -multiexec M -pyfile BATCHRUN_hst_gen_radioss_input.py`를 실행합니다. 런처는 `hst_gen_radioss_core` pyd만 import하고, DOE 생성은 pyd 안 HyperStudy가 합니다. `DG_SCAN`은 HyperStudy가 만든 run 폴더에서 샘플 값을 뽑습니다(`doe_samples.extract`).
- 원본 정의 파일의 실제 id(업로드본 `CONFIG/DATA/DATA_doe_design_type.json`, 시험 사본 `backend/tests/support_resources.py`와 같음):

| label | value | run 수 | options |
|---|---|---|---|
| FullFact | `TYPE_FULLFACT` | HyperStudy 결정(`runs_editable=false`) | 없음 |
| FracFact | `TYPE_FRACFACT` | HyperStudy 결정 | `RESOLUTION` combo `3`·`4`·`5`(기본 3) |
| LatinHyperCube | `TYPE_LATINHYPERCUBE` | 자유(기본 7) | `RANDOM_SEED` int 0~10000(기본 1) |
| Sobol | `TYPE_SOBOL` | 자유(기본 7) | `SEQUENCE_OFFSET` int(기본 1), `SCRAMBLE` bool(기본 false), `SEED` int(기본 0) |

- pyd 문자열은 난독화되어 이 4개 밖의 value(Hammersley·MELS·Box-Behnken·CCD·Plackett-Burman 등)를 받는지 **확인할 수 없습니다**. 추측으로 목록에 넣지 않습니다.

| 안 | 내용 | 판단 |
|---|---|---|
| **A(채택)** | 정의 파일 목록을 그대로 보여 주고, 확인된 4개 value에 설명 id·추천·영향도 등급만 붙임. 사이트 관리자가 파일에 항목을 더하면(E1-8로 pyd 지원을 확인한 뒤) 일반 설명문으로 표시 | 현 구조 무변경, 원본 일치, 위험 없음 |
| B(후속) | ① 생성을 ④ `BP_GEN`처럼 플랫폼 동시 실행기(m_1→m_2→m_3)로 바꾸고 플랫폼이 계산한 표를 사용 → ①도 7개 방식 사용 가능 | `TD_DOE_GEN` step·run 폴더·`DG_SCAN`·원본 일치 판정을 다시 써야 하는 큰 변경. S16 후보(§20.17-1) |

### 20.4 방식 목록·설명문(문구 확정)

**④ 선택창 순서·묶음**(드롭다운 1개, 묶음 머리는 선택 불가 회색):

| 묶음 | kind(API) | DB `source_kind` | 표시 이름 | desc_id | 추천 |
|---|---|---|---|---|---|
| 공간 채움(AI 학습·대리모델) | `lhs_opt` | `LHS_OPT` | 최적화 LHS | `lhs_opt` | **추천** |
| | `sobol` | `SOBOL` | Sobol(스크램블 QMC) | `sobol` | |
| | `lhs` | `LHS` | LHS(무작위 층화) | `lhs` | |
| 요인 설계(경향·선별) | `fullfact` | `FULLFACT` | 전체 요인 | `fullfact` | |
| | `fracfact` | `FRACFACT` | 부분 요인(2수준) | `fracfact` | |
| | `pb` | `PB` | Plackett–Burman | `pb` | |
| 2차 응답면 | `bbd` | `BBD` | Box–Behnken | `bbd` | |
| | `ccd` | `CCD` | 중심 합성(CCD) | `ccd` | |
| 직접 지정 | `table` | `TABLE` | 표 붙여넣기 / CSV | `table` | |
| | `train_doe` | `TRAIN_DOE` | ① 학습 DOE 그대로 재사용 | `train_doe` | |

기존 라벨 "범위·개수로 자동(LHS)"은 "LHS(무작위 층화)"로 바꿉니다.

**① 설명 id**(value → desc_id): `TYPE_LATINHYPERCUBE`→`hs_lhs`(추천 기본, 설정), `TYPE_SOBOL`→`hs_sobol`, `TYPE_FULLFACT`→`hs_fullfact`, `TYPE_FRACFACT`→`hs_fracfact`, 그 밖 → `null`(일반 문구).

**설명문**(선택창 아래 상자, 4줄: 용도 / 장단점 / 영향도·AI 학습 / run 수·제약. 추천 방식은 이름 옆에 `추천` 배지). 문구는 아래 그대로 씁니다(`k` = 범위가 있는 변수 수, 화면에서는 실제 값으로 바꿔 "권장 40" 식으로 계산값을 덧붙임).

`lhs_opt` — 최적화 LHS
1. 범위를 고르게 채우는 표본입니다. AI 학습·대리모델·영향도에 두루 맞아 기본으로 추천합니다.
2. 일반 LHS를 다시 배치해 점 사이 최소 거리를 넓히거나(기본) 변수끼리의 상관을 줄입니다. 나중에 점을 이어 붙일 수는 없습니다.
3. 영향도: 정식(PRCC·SRC). 상관이 작아 영향도 순위가 안정적입니다.
4. run 수: 자유(2~200). 권장 10 × 변수 수(최소 변수 수 + 2).

`sobol` — Sobol(스크램블 QMC)
1. 저불일치 수열로 공간을 균일하게 채웁니다. 같은 시드로 나중에 run을 이어서 추가할 수 있습니다.
2. 균형을 지키려면 run 수가 2의 거듭제곱(4·8·16·32·64·128)이어야 합니다. run이 적으면 최적화 LHS보다 덜 고를 수 있습니다.
3. 영향도: 정식. AI 학습·대리모델 표본을 단계적으로 늘려 갈 때 추천합니다.
4. run 수: 2^m. 권장 = 10 × 변수 수 이상인 가장 작은 2^m(최대 128). 이어서 추가는 기존 개수만큼(합계 2배) 권장.

`lhs` — LHS(무작위 층화)
1. 변수마다 범위를 n칸으로 나눠 칸마다 1점씩 무작위로 뽑는 기본 표본입니다.
2. 빠르고 run 수가 자유롭지만 무작위라 점이 몰리거나 변수끼리 상관이 생길 수 있습니다(최적화 LHS가 보완).
3. 영향도: 정식. AI 학습에 쓸 수 있습니다.
4. run 수: 자유(2~200). 권장 10 × 변수 수.

`fullfact` — 전체 요인
1. 변수마다 수준 수를 정해 모든 조합을 계산합니다. 변수 2~4개의 경향을 격자로 볼 때 씁니다.
2. 주효과·교호작용을 빠짐없이 보지만 run 수가 수준 수의 곱으로 급격히 늘고, 격자 사이가 비어 AI 학습 표본으로는 비효율적입니다.
3. 영향도: 정식.
4. run 수 = 수준 수의 곱(최대 200). 수준 2~10, 정수 변수는 범위 안 정수 개수까지.

`fracfact` — 부분 요인(2수준)
1. 최소·최대 2수준만 써서 변수가 많을 때 중요한 변수를 적은 run으로 거릅니다(선별용).
2. 해상도 V는 주효과·2인자 교호작용이 서로 섞이지 않고, 해상도 IV는 주효과는 깨끗하지만 2인자 교호작용끼리 섞입니다(교락).
3. 영향도: 참고용(교락 안내). 양 끝값만 쓰므로 AI 학습 표본으로는 맞지 않습니다.
4. run 수 = 2^(k−p): IV 8~32, V 4~128(변수 2~11개). 부분 요인이 필요 없는 변수 수에서는 전체 2수준 요인이 됩니다.

`pb` — Plackett–Burman
1. 변수가 아주 많을 때 가장 적은 run으로 주효과만 거르는 2수준 선별 설계입니다.
2. run 수가 변수 수 + 1 근처로 가장 적지만, 주효과가 2인자 교호작용과 부분적으로 섞입니다.
3. 영향도: 참고용(교락 안내). AI 학습 표본으로는 맞지 않습니다.
4. run 수 = 변수 수 + 1 이상인 가장 작은 크기(8·12·16·20·24·32·44·48…). 변수 2개 이상.

`bbd` — Box–Behnken
1. 최소·중간·최대 3수준의 2차 응답면 설계입니다. 모든 변수가 동시에 극값인 꼭짓점 조합을 피합니다.
2. 곡률(2차 효과)을 적은 run으로 보지만 공간 내부가 비어 AI 학습 표본으로는 부족합니다. 변수 3개 이상이 필요합니다.
3. 영향도: 참고용(2차 설계 — 곡률 효과는 선형 영향도에 작게 보일 수 있음).
4. run 수 = 2·k·(k−1) + 1(중심점 1개 — AI 예측은 같은 입력이면 같은 값이라 반복하지 않음). 변수 3~10개.

`ccd` — 중심 합성(CCD)
1. 2수준 요인점 + 축점 + 중심점으로 2차 응답면을 맞추는 고전 설계입니다.
2. 면중심(기본)은 3수준으로 범위 안이고, 내접은 5수준으로 요인점이 범위 안쪽으로 줄어듭니다. 범위 밖으로 나가는 외접은 AI 학습 범위를 벗어나 제공하지 않습니다.
3. 영향도: 참고용(2차 설계 안내). AI 학습 표본으로는 부족합니다.
4. run 수 = 요인점(변수 4개 이하 2^k, 5개 이상 해상도 V 부분 요인) + 2k + 1. 변수 2~11개.

`table` — 표 붙여넣기 / CSV
1. 직접 정한 조합(엑셀 붙여넣기·CSV)을 그대로 예측합니다.
2. 원하는 점을 정확히 넣을 수 있지만, 표본이 어떻게 퍼져 있는지 플랫폼은 알 수 없습니다.
3. 영향도: 참고용.
4. run 수 = 표 행 수(1~200). 첫 줄 = 파라미터 이름.

`train_doe` — ① 학습 DOE 그대로 재사용
1. ① 학습 DOE와 같은 점을 AI로 예측해 해석 결과와 1:1로 비교(검증)합니다.
2. 해석값과 바로 겹쳐 볼 수 있지만 run 수·점 위치는 ① DOE를 따릅니다.
3. 영향도: ① DOE 방식을 따름(LHS·Sobol·전체 요인 = 정식, 부분 요인 = 참고용).
4. run 수 = ① DOE run 수(최대 200). 파라미터 이름이 템플릿과 같아야 합니다.

`hs_lhs` — LatinHyperCube(①)
1. 학습 데이터 기본 추천입니다. HyperStudy LHS로 범위를 고르게 층화합니다.
2. run 수를 자유롭게 정하고 Random Seed로 같은 표본을 다시 만듭니다. 무작위라 점이 일부 몰릴 수 있습니다.
3. 영향도: 정식. AI 학습에 적합합니다.
4. run 수: 권장 10 × 변수 수(해석 비용이 크면 최소 변수 수 + 2).

`hs_sobol` — Sobol(①)
1. HyperStudy Sobol 수열로 공간을 균일하게 채웁니다.
2. Scramble을 켜면 격자 무늬가 줄어듭니다(권장). Sequence Offset·Seed로 같은 표본을 다시 만듭니다.
3. 영향도: 정식. AI 학습에 적합합니다.
4. run 수: 자유, 가능하면 2의 거듭제곱(16·32·64…). 권장 10 × 변수 수 이상.

`hs_fullfact` — FullFact(①)
1. 모든 수준 조합을 해석합니다. 변수가 적을 때 경향을 확인하는 용도입니다.
2. run 수는 HyperStudy가 변수 수준으로 정하고 변수가 늘면 급격히 늘어납니다. 격자라 학습 표본으로는 비효율적입니다.
3. 영향도: 정식.
4. run 수: HyperStudy가 결정(화면에서 지정 불가).

`hs_fracfact` — FracFact(①)
1. 2수준 부분 요인으로 중요한 변수를 거르는 선별용입니다.
2. Resolution 3은 주효과가 2인자 교호작용과 섞이고, 4는 2인자 교호작용끼리, 5는 3인자 이상과만 섞입니다.
3. 영향도: 참고용(교락 안내). AI 학습 표본으로는 맞지 않습니다.
4. run 수: HyperStudy가 결정(Resolution에 따라).

`null`(설명 없는 ① 유형):
1. 원본 DOE 유형 정의 파일에 있는 방식입니다.
2. 이 방식의 설명은 등록되지 않았습니다.
3. 영향도: 참고용.
4. run 수: 정의 파일 설정을 따릅니다.

① 선택창 아래 고정 회색 한 줄: "최적화 LHS·Box–Behnken·CCD·Plackett–Burman은 ④ 일괄 예측에서만 고를 수 있습니다(① 해석 DOE는 HyperStudy 유형 정의 파일의 방식만)."

**권장 run 수 계산식**(프런트 `recommendedCount`, 미리보기 응답 `sampling.recommended_count`와 같은 값; `R` = `predict_batch.max_runs`):
- `lhs`·`lhs_opt`: `min(R, max(10, 10·k))`
- `sobol`: `10·k` 이상인 가장 작은 2^m(m ≥ 2). 그 값이 R보다 크면 R 이하의 가장 큰 2^m
- 그 밖 kind: `null`(run 수가 설계로 정해짐)
- ①: `hs_lhs`·`hs_sobol`은 `10·k`(① 상한 `train_data.max_runs`), 나머지는 `null`

### 20.5 알고리즘(결정적)

#### 20.5.1 공통 규칙
- **변수**: 템플릿(`param_sets.parameters`) 순서. 범위 = `ranges[name]`(생략하면 세트 min·max, 검증은 기존 `RANGE_INVALID`: 유한하고 lo < hi). **활성 변수** = lo < hi인 변수(순서 유지, 개수 `k`). **고정 변수**(세트 min = max)는 모든 행에 그 값을 넣고, 설계 차원에서 빼며 note `FIXED_EXCLUDED`를 냅니다. 기존 `lhs` kind는 이 규칙을 적용하지 않고 지금 그대로 둡니다(V3-S9-5 골든 불변).
- `k = 0`이면 새 7개 kind는 모두 problem `DESIGN_UNSUPPORTED` "범위가 있는 변수가 없습니다"를 냅니다.
- **결정성**: 같은 (템플릿 파라미터·순서, source 전체, 설정 `predict_batch.max_runs`·`predict.integer_rounding`)에서는 같은 `rows`가 나옵니다. Sobol은 여기에 **같은 scipy 버전**이 조건으로 붙습니다. 무작위는 `lhs`·`lhs_opt` = `random.Random(seed)`(Python 표준, 버전 간 재현), `sobol` = `numpy.random.default_rng(seed)`을 scipy에 넘깁니다. 요인·PB·BBD·CCD는 무작위가 없습니다.
- **코드값 → 값**(요인·PB·BBD·CCD): c = −1 → `lo`, c = +1 → `hi`, c = 0 → `(lo+hi)/2`(정확히 이 식), 그 밖 c → `(lo+hi)/2 + c·(hi−lo)/2`. 단위 값 u ∈ [0,1](LHS 계열·Sobol) → `lo + u·(hi−lo)`.
- **범위 밖**: 설계가 만든 값은 항상 배치 `ranges` 안에 있습니다(외접 CCD를 빼서 보장). `ranges`가 세트 범위를 넘으면 기존과 같이 `out_of_range`로 표시하고 허용합니다.
- **정수 변수**(tpl 정수 형식): `values` = 설계 값, `applied_values` = 기존 `nearest.applied_values`(`predict.integer_rounding`) — 기존과 같습니다. 단 `fullfact`는 수준 값을 처음부터 서로 다른 정수로 만듭니다(§20.5.4). 반영값이 같은 행이 생기면 note `DUPLICATE_ROWS`(중복 수)를 내고, 행은 지우지 않습니다.
- **행 순서·번호**: `doe_no` = 설계 순서 1.., `run_key` = `run__{doe_no:05d}`(기존 규칙). Sobol을 이어서 추가할 때도 배치 안 번호는 1부터이고, 수열 위치는 `source_meta.offset`에 둡니다.
- `count < max(5, p+2)`(p = 템플릿 파라미터 수, ⑤ 기준과 같음)이면 note `INFLUENCE_TOO_FEW` "run이 m개보다 적어 ⑤ 영향도는 계산되지 않습니다"를 냅니다.
- 품질 지표(`source_meta.quality`, `lhs`·`lhs_opt`·`sobol`만, 나머지는 없음): `min_dist` = 단위 좌표(활성 변수) 점 사이 최소 유클리드 거리 / √k, `max_abs_corr` = 활성 변수 쌍 Pearson 상관 절댓값 최대(k < 2면 0). 둘 다 소수 4자리로 반올림합니다.

#### 20.5.2 `lhs_opt` 최적화 LHS
입력: `count` n(2~R), `seed`(정수, 기본 1), `ranges`, `criterion` ∈ `maximin`(기본) | `corr`.
1. `rng = random.Random(seed)`.
2. 후보 C = 5개를 차례로 만듭니다. 후보마다 활성 변수 순서대로 `perm = list(range(n)); rng.shuffle(perm)`, 이어서 i = 0..n−1마다 `u = rng.random()`, `U[i][j] = (perm[i] + u)/n`(기존 `lhs_values`와 같은 소비 순서).
3. 점수(작을수록 좋음):
   - `maximin`: S = Σ_{i<l} d_il^(−15). d_il은 단위 좌표 유클리드 거리이고, d = 0이 있으면 S = +inf.
   - `corr`: S = Σ_{j<m} r_jm²(활성 열 Pearson).
   후보 중 S가 **엄격히 더 작은** 것을 차례로 고릅니다(같으면 앞 후보).
4. 열 내 교환 T = 2000회(k ≤ 1이면 0회): `j = rng.randrange(k); a = rng.randrange(n); b = rng.randrange(n−1); if b >= a: b += 1`. `U[a][j]`와 `U[b][j]`를 바꾸고, 새 S < 이전 S이면 받아들이고 아니면 되돌립니다. 열 안 교환이라 층(칸마다 1점)은 유지됩니다.
5. 값 = `lo + U·(hi−lo)`.
- 증분 계산(교환한 두 행에 걸린 쌍만 다시 계산, 500회마다 S 전체 재계산)은 구현 1곳(`sampling/designs.py`)에 고정하고 골든 시험으로 동결합니다. 성능 기준(참고): n = 200·k = 20에서 2초 안. 시험은 10초 상한만 둡니다.
- meta: `{count, seed, ranges, criterion, candidates: 5, iterations: 2000, active, fixed, quality}`.

#### 20.5.3 `sobol` Sobol(스크램블)
입력: `count`, `seed`(0~4294967295, 생략하면 1), `ranges`, `continue_from`(배치 id | null).
- `count` ∈ {2^m : m ≥ 2, 2^m ≤ R}이 아니면 problem `COUNT_NOT_POW2` "Sobol은 run 수가 2의 거듭제곱이어야 합니다(4·8·16·32·64·128)".
- 생성(`physicsai_core/sampling/qmc.py`, 지연 import):
  ```
  eng = Sobol(d=k, scramble=True, <kw>=numpy.random.default_rng(seed))
  eng.fast_forward(offset)
  U = eng.random(count)
  ```
  `<kw>`는 생성자 시그니처에 `rng`가 있으면 `rng`, 없으면 `seed`입니다(scipy 1.13~1.x 호환, 판정 1곳). scipy `UserWarning`(균형 경고)은 이 함수 안에서만 무시합니다. import에 실패하면 problem `GENERATOR_UNAVAILABLE` "표본 계산 모듈(scipy)을 불러올 수 없습니다 — 관리자에게 문의하세요".
- 새 수열이면 `offset = 0`입니다.
- **이어서 추가**(`continue_from` = 이전 배치 P):
  - 조건: P가 같은 Study이고 `source_kind = SOBOL`, 같은 `param_set_id`, 지금 활성 변수 목록(이름·순서)이 P의 `meta.active`와 같음. body에 `seed`·`ranges`를 함께 주면 안 됩니다(P의 값을 그대로 씀). 어긋나면 problem `CONTINUE_INVALID`(사유 문구 각각 — "Sobol 배치가 아닙니다", "다른 템플릿의 배치입니다", "변수 구성이 다릅니다", "이어서 추가는 이전 배치의 시드·범위를 그대로 씁니다").
  - `offset = P.offset + P.count`. `offset % count ≠ 0`이면 `CONTINUE_INVALID` "이어서 추가할 run 수는 {offset}을 나누어떨어지게 하는 2의 거듭제곱이어야 합니다(권장 {offset})". 합계가 2의 거듭제곱이면 note `SEQUENCE_CONTINUED` "B-003과 합치면 32개(균형 유지)"를 내고, 아니면 같은 note에 "(합계는 균형 아님)"을 붙입니다.
  - 대조: P의 구간 `[P.offset, P.offset + P.count)`를 같은 방법으로 다시 만들어, P run 행 `values`의 활성 변수와 |차| ≤ 1e-9·(hi−lo)인지 확인합니다. 어긋나면 problem `SEQUENCE_MISMATCH` "이전 배치를 같은 수열로 다시 만들 수 없습니다(계산 라이브러리 버전 차이) — 새 Sobol 배치로 시작하세요".
  - 이어서 추가한 배치를 다시 이어서 추가할 수 있습니다.
- meta: `{count, m, seed, ranges, scramble: true, offset, continue_from: {batch_id, label}|null, generator: "scipy <버전>", active, fixed, quality}`.

#### 20.5.4 `fullfact` 전체 요인
입력: `levels{name: int}`(생략한 활성 변수 = 2), `ranges`.
- 수준 L은 2~10입니다. 활성 변수가 아닌 이름이거나 범위 밖이면 problem `LEVELS_INVALID`. 고정 변수는 L = 1(입력 무시, `FIXED_EXCLUDED`).
- 실수 변수의 수준 값 = `lo + t·(hi−lo)`, t = i/(L−1), i = 0..L−1(i = 0 → lo, i = L−1 → hi 정확).
- 정수 변수의 수준 값 = 같은 식에 `predict.integer_rounding`을 적용한 정수. 서로 다른 값이 L개가 아니면(L > 범위 안 정수 개수) `LEVELS_INVALID` "'{name}'은 정수 변수라 {lo}~{hi}에서 최대 {M}수준입니다".
- 행 = 활성 변수 순서의 사전식 곱(`itertools.product` 순서, **마지막 변수가 가장 빨리 바뀜**). run = ΠL > R이면 `TOO_MANY_ROWS` "전체 요인 run 수 N개가 상한 R개를 넘습니다 — 수준 수를 줄이세요".
- meta: `{levels(활성 전부), ranges, active, fixed}`.

#### 20.5.5 `fracfact` 부분 요인 2수준
입력: `resolution` ∈ {4, 5}(기본 5), `ranges`. k가 2보다 작거나 11보다 크면 `DESIGN_UNSUPPORTED` "부분 요인은 범위가 있는 변수 2~11개에서만 만들 수 있습니다".
- 문자: 활성 변수 순서대로 A B C D E F G H J K L(I는 건너뜀).
- 기본 요인 r개를 Yates 순서로 둡니다: run i = 0..2^r−1, 기본 요인 b(0부터)의 수준 = `+1 if (i >> b) & 1 else −1`(첫 요인이 가장 빨리 바뀜). 생성 요인 = 생성자 문자 열들의 곱.
- 생성자 표(Montgomery 표 8.14 기준, 정의 관계로 해상도를 계산해 검증함):

| k | 해상도 IV: r, 생성자 (run) | 해상도 V: r, 생성자 (run) |
|---|---|---|
| 2 | 전체 2² (4) | 전체 2² (4) |
| 3 | 전체 2³ (8) | 전체 2³ (8) |
| 4 | 3, D=ABC (8) | 전체 2⁴ (16) |
| 5 | 4, E=ABCD (16) | 4, E=ABCD (16) |
| 6 | 4, E=ABC F=BCD (16) | 5, F=ABCDE (32) |
| 7 | 4, E=ABC F=BCD G=ACD (16) | 6, G=ABCDEF (64) |
| 8 | 4, E=BCD F=ACD G=ABC H=ABD (16) | 6, G=ABCD H=ABEF (64) |
| 9 | 5, F=BCDE G=ACDE H=ABDE J=ABCE (32) | 7, H=ACDFG J=BCEFG (128) |
| 10 | 5, F=ABCD G=ABCE H=ABDE J=ACDE K=BCDE (32) | 7, H=ABCG J=BCDE K=ACDF (128) |
| 11 | 5, F=ABC G=BCD H=CDE J=ACD K=ADE L=BDE (32) | 7, H=ABCG J=BCDE K=ACDF L=ABCDEFG (128) |

- "전체" 칸은 note `FULL_FACTORIAL_USED` "변수 k개에서는 부분 요인 대신 전체 2수준 요인(2^k)을 씁니다". 시험이 표의 해상도 ≥ 요청 해상도를 계산으로 확인하고, 실패하면 표를 고치고 변경 메모를 남깁니다.
- meta: `{resolution, letters: {A: "THK_1", …}, generators: ["E=ABCD"], runs, full: bool, ranges, active, fixed}`.

#### 20.5.6 `pb` Plackett–Burman
k가 2보다 작으면 `DESIGN_UNSUPPORTED`.
- 크기 N = 집합 {q+1 : q 소수, q ≡ 3 (mod 4), q+1 ≥ 8} ∪ {2^m : m ≥ 3}에서 N ≥ k+1인 가장 작은 값입니다(N ≤ R, 넘으면 `TOO_MANY_ROWS`). R = 200까지의 집합은 8, 12, 16, 20, 24, 32, 44, 48, 60, 64, 68, 72, 80, 84, 104, 108, 128, 132, 140, 152, 164, 168, 180, 192, 200입니다.
- **Paley 순환**(N−1 = q가 위 조건의 소수일 때 우선): `g[0] = +1`, j = 1..q−1에서 `g[j] = +1 if j가 mod q 이차잉여 else −1`. 행 i = 0..q−1의 열 j = `g[(j − i) mod q]`, 마지막 행은 전부 −1. N = 12의 첫 행은 고전 PB `+ + − + + + − − − + −`와 같습니다.
- **Sylvester**(그 밖, N = 2^m): H₁ = [1], H₂ₙ = [[H, H], [H, −H]]. 첫 열(전부 +1)을 빼고 자연 순서로 씁니다.
- 앞쪽 k개 열을 활성 변수 순서로 씁니다.
- meta: `{runs: N, construction: "paley"|"sylvester", ranges, active, fixed}`.

#### 20.5.7 `bbd` Box–Behnken(쌍 방식)
k가 3보다 작으면 `DESIGN_UNSUPPORTED` "Box–Behnken은 범위가 있는 변수가 3개 이상이어야 합니다".
- 활성 변수 쌍 (i < j)을 사전식 순서로, 쌍마다 4행 (i, j) = (−,−), (+,−), (−,+), (+,+)를 둡니다(나머지 0). 마지막에 중심 1행(전부 0)을 둡니다.
- run = 2k(k−1)+1 > R이면 `TOO_MANY_ROWS`(k = 11 → 221).
- k ≥ 6이면 note `BBD_PAIRWISE` "변수 6개 이상은 쌍 방식 Box–Behnken입니다(표준 블록 설계보다 run이 많습니다)". k = 3~5는 표준 BBD에서 중심점만 1개로 줄인 것과 같습니다.
- meta: `{center: 1, pairwise: k >= 6, ranges, active, fixed}`.

#### 20.5.8 `ccd` 중심 합성
입력: `alpha` ∈ `face`(기본) | `inscribed`. k가 2보다 작거나 11보다 크면 `DESIGN_UNSUPPORTED`.
- 요인부 F: k ≤ 4이면 전체 2^k(Yates), k ≥ 5이면 §20.5.5 해상도 V 표의 설계. F = 요인부 run 수.
- `face`: α = 1, 요인점 ±1, 축점 ±1(3수준).
- `inscribed`: α = F^(1/4), 요인점 ±1/α, 축점 ±1(5수준, 모두 범위 안).
- 순서: 요인부(Yates) → 축점(활성 변수 순서대로 (−1 at j), (+1 at j)) → 중심 1행.
- meta: `{alpha_kind, alpha, factorial: "full"|"fracV", generators, center: 1, ranges, active, fixed}`.

#### 20.5.9 run 수 표(k = 활성 변수 수, R = 200) — 프런트·백엔드 시험 공용 기준

| k | fracfact IV | fracfact V | pb | bbd | ccd | sobol 권장 | lhs·lhs_opt 권장 |
|---|---|---|---|---|---|---|---|
| 2 | 4 | 4 | 8 | — | 9 | 32 | 20 |
| 3 | 8 | 8 | 8 | 13 | 15 | 32 | 30 |
| 4 | 8 | 16 | 8 | 25 | 25 | 64 | 40 |
| 5 | 16 | 16 | 8 | 41 | 27 | 64 | 50 |
| 6 | 16 | 32 | 8 | 61 | 45 | 64 | 60 |
| 7 | 16 | 64 | 8 | 85 | 79 | 128 | 70 |
| 8 | 16 | 64 | 12 | 113 | 81 | 128 | 80 |
| 9 | 32 | 128 | 12 | 145 | 147 | 128 | 90 |
| 10 | 32 | 128 | 12 | 181 | 149 | 128 | 100 |
| 11 | 32 | 128 | 12 | — (221 > R) | 151 | 128 | 110 |

(`fullfact` = ΠL, 예: 3⁴ = 81.)

### 20.6 API(`backend/openapi.json` 갱신 — 새 라우트·operationId 없음)

**요청 스키마**(`schemas/predict_batch.py`, `BatchSource` discriminated union `kind`에 7개 추가. 기존 3개 무변경):

```jsonc
{"kind":"lhs_opt","count":20,"seed":1,"ranges":{"THK_1":[2.0,5.0]},"criterion":"maximin"}  // criterion: maximin|corr(기본 maximin)
{"kind":"sobol","count":32,"seed":1,"ranges":null,"continue_from":null}                    // seed 0~4294967295|null(=1), continue_from = batch id(≤64자)|null
{"kind":"fullfact","levels":{"THK_1":3,"RIB_N":2},"ranges":null}                           // levels 값 1~10 모양 검사(활성·범위 판정은 problems)
{"kind":"fracfact","resolution":5,"ranges":null}                                           // resolution: 4|5(기본 5)
{"kind":"pb","ranges":null}
{"kind":"bbd","ranges":null}
{"kind":"ccd","alpha":"face","ranges":null}                                                // alpha: face|inscribed(기본 face)
```
- 모양 오류(모르는 kind, 형식, resolution 3, alpha 다른 값, seed 음수)는 422 `INVALID_PARAMS`(기존). 조합 문제는 `problems`(미리보기 200 / 생성 422 `BATCH_SOURCE_INVALID`) — 기존과 같습니다.
- 같은 union을 `POST /studies/{id}/jobs`(`PREDICT_BATCH`) `params.source`에도 씁니다. 저장 params `source` = `{"kind", **source_meta}`(표 본문 없음, 기존 규칙). 저장 params는 다시 검증하지 않습니다(TABLE과 같음).

**미리보기 응답**(`POST /studies/{id}/predict-batches/preview`) — 필드 추가:

```jsonc
{"input_kind":"assembly","count":32,"estimate_min":56,"rows":[…],"problems":[],
 "notes":[{"code":"SEQUENCE_CONTINUED","message":"B-003과 합치면 32개(균형 유지)"}],      // 막지 않는 안내(신규)
 "sampling":{"kind":"sobol","method":"SOBOL","desc_id":"sobol","label":"Sobol(스크램블 QMC)",
             "influence_class":"formal","influence_note":null,"recommended_count":64,
             "meta":{"count":16,"m":4,"seed":1,"offset":16,"continue_from":{"batch_id":"…","label":"B-003"},
                     "generator":"scipy 1.17.1","ranges":{…},"active":["THK_1","THK_2"],"fixed":[],
                     "quality":{"min_dist":0.21,"max_abs_corr":0.08}}}}
```
- `count` = 실제 run 수(= `rows` 길이, 기존 필드). problems가 있어도 `sampling`은 채우고, `meta`는 계산된 만큼만 넣습니다.

**배치 상세**(`GET /predict-batches/{bid}`): `sampling`(위와 같은 모양, `recommended_count`는 null)을 추가합니다. `influence_class`·`influence_note`는 §20.7에 따라 서버가 계산하고, 기존 행(LHS·TABLE·TRAIN_DOE)에도 kind로 계산합니다. `source_kind` 필드는 유지합니다.

**배치 목록**(`GET /studies/{id}/predict-batches`): `PredictBatchSummary.sampling: {kind, method, label, count, seed|null, offset|null} | null`을 추가합니다. Sobol 이어서 추가 후보 고르기와 ⑤ 출처 드롭다운 라벨에 씁니다.

**① DOE 유형**(`GET /train/doe-types`): `DoeType`에 `desc_id: str|null`, `recommended: bool`(value == `train_data.recommended_doe_type`인 항목 하나), `influence_class: "formal"|"reference"`를 추가합니다.

**① 결과 표**(`GET /train-does/{doe_id}/result-table`, s14 §19.5) — 필드 추가와 의미 확장:

```jsonc
{…,"type":"TYPE_FRACFACT",
 "sampling":{"method":"TYPE_FRACFACT","label":"FracFact","desc_id":"hs_fracfact","options":{"RESOLUTION":"4"}},
 "influence_class":"reference",                    // formal|reference|off
 "influence_note":"부분 요인(해상도 IV) — …",       // reference·off 문구, formal은 null
 "influence_ok":true}                              // = influence_class != "off"(확장, §20.7)
```

### 20.7 영향도 등급(s14 §19.5·§19.6과의 관계)

| 출처·방식 | 등급 | `influence_note`(reference 문구 확정) |
|---|---|---|
| ④ `LHS`·`LHS_OPT`·`SOBOL`·`FULLFACT` | formal | null |
| ④ `TRAIN_DOE` | ① DOE `doe_type`으로 아래 ① 규칙(`source_meta.doe_id`로 조회). DOE가 없으면 reference | DOE 없음: "원본 ① DOE 정보를 찾을 수 없어 영향도는 참고용입니다" |
| ④ `TABLE` | reference | "직접 만든 표 — 표본 분포를 알 수 없어 영향도는 참고용입니다" |
| ④ `FRACFACT` | reference | 해상도 IV: "부분 요인(해상도 IV) — 2인자 교호작용끼리 교락되어 영향도는 참고용입니다(주효과는 2인자 교호작용과 교락 없음)". 해상도 V(전체 2수준 포함): "부분 요인(해상도 V) — 3인자 이상 교호작용과 교락되어 영향도는 참고용입니다" |
| ④ `PB` | reference | "Plackett–Burman — 주효과가 2인자 교호작용과 부분적으로 교락되어 영향도는 참고용입니다" |
| ④ `BBD`·`CCD` | reference | "2차 응답면 설계 — 점이 중심·모서리에 몰려 곡률 효과가 선형 영향도에 작게 보일 수 있어 참고용입니다. 변수–응답 그래프로 확인하세요" |
| ④ 최적화 소유 `EXPLORE` 배치 | 그 배치 kind대로(현재 LHS → formal) | — |
| ④ 최적화 소유 `VERIFY`·`FINAL` 배치 | reference(kind보다 우선) | "최적화 검증 배치 — 최적점 근처에 모인 표본이라 영향도는 참고용입니다" |
| ④ 재사용(`REUSE`) 배치 | 그 배치 kind대로(소유가 아님) | — |
| ① `TYPE_LATINHYPERCUBE`·`TYPE_SOBOL`·`TYPE_FULLFACT` | formal | null |
| ① `TYPE_FRACFACT` | reference | `options.RESOLUTION` 3: "부분 요인(해상도 III) — 주효과가 2인자 교호작용과 교락되어 영향도는 참고용입니다", 4·5는 ④ 문구와 같음 |
| ① 그 밖 value | reference | "표본 방식을 알 수 없어 영향도는 참고용입니다" |

- **off(비활성)**, s14 조건을 그대로 둡니다:
  - ①은 서버가 판정합니다. 응답 없음 → "응답이 없어 영향도를 계산할 수 없습니다", 유효 run < max(5, p+2) → "영향도에는 유효 run이 m개 이상 필요합니다(현재 n개)". off일 때 `influence_note`는 이 사유입니다.
  - ④는 프런트가 n·응답을 판정합니다(s14 `fromBatch` 그대로). 서버 `sampling.influence_class`는 formal·reference만 줍니다.
- **s14에서 바뀌는 규칙**(D3-63):
  1. §19.5 "`influence_ok` = type이 LHS이고 n 조건" → "`influence_ok` = `influence_class` ≠ off". ① Sobol·FullFact DOE도 영향도가 정식으로 켜지고, FracFact는 참고용으로 켜집니다.
  2. §19.6 "LHS가 아닌 해석 DOE는 영향도 비활성" → 위 등급 표로 바꿉니다.
  3. §19.6 출처 (a) "LHS 배치가 아니면 'LHS가 아닌 표 — 참고용'" → 서버 `sampling.influence_class`·`influence_note`를 따릅니다. 프런트 상수 `NOT_LHS_TEXT`·`REF_ONLY_TEXT`는 없앱니다.
- 계산 위치: `physicsai_core/sampling/registry.py`의 `batch_influence(source_kind, source_meta, owned_kind, train_doe_type, train_doe_options)`, `doe_influence(doe_type, options)`(순수 함수, 문구 상수 1곳).
- 화면(⑤): formal은 표만, reference는 표 위 회색 한 줄 `influence_note`, off는 표 없이 사유만 보여 줍니다. 계산(PRCC·SRC)은 s14 그대로입니다.

### 20.8 DB

- **migration `0012_sampling_kinds`**(Revises `0011_surrogate_final`, `MIGRATION_HEAD` 갱신):
  - `ck_predict_batches_source_kind`를 지우고 `source_kind IN ('LHS','LHS_OPT','SOBOL','FULLFACT','FRACFACT','PB','BBD','CCD','TABLE','TRAIN_DOE')`로 다시 만듭니다.
  - 열 길이 `String(16)`은 그대로 둡니다(최장 `TRAIN_DOE`). 기존 행 데이터는 바꾸지 않습니다. downgrade는 RuntimeError(기존 관례)입니다.
  - `db/tables/predict_batch.py`의 `BATCH_SOURCE_KINDS`·CHECK를 같이 바꿉니다.
- 방식 인자·품질·이어서 추가 정보는 기존 `predict_batches.source_meta` JSONB에 둡니다(§20.5 각 meta). 새 열은 없습니다. run 값은 기존 `predict_batch_runs.values`에 있습니다(이어서 추가 대조에 씀).
- ①: `train_does.doe_type`·`options`가 이미 있어 **변경이 없습니다**.
- 검토한 대안(기각): migration 없이 `source_kind = 'TABLE'` + `source_meta.method`. 기존 TABLE의 의미(직접 표)·⑥ `create_opt_batch`의 kind 매핑·s14 프런트 판정과 어긋나 오판 위험이 큽니다.

### 20.9 문제·안내 코드

problems(막음, `BatchProblem.code`) — 기존 `TABLE_HEADER`·`TABLE_VALUE`·`TEXT_TOO_LARGE`·`TOO_MANY_ROWS`·`TOO_FEW_ROWS`·`RANGE_INVALID`·`DOE_PARAM_MISMATCH`에 더해:

| code | 상황 | 문구(예) |
|---|---|---|
| `COUNT_NOT_POW2` | Sobol run 수 | "Sobol은 run 수가 2의 거듭제곱이어야 합니다(4·8·16·32·64·128)" |
| `CONTINUE_INVALID` | 이어서 추가 조건 | §20.5.3 사유별 |
| `SEQUENCE_MISMATCH` | 이전 블록 재생성 불일치 | §20.5.3 |
| `LEVELS_INVALID` | 전체 요인 수준 | "'RIB_N'은 정수 변수라 3~5에서 최대 3수준입니다" / "'X'는 범위가 있는 변수가 아닙니다" / "수준은 2~10입니다" |
| `DESIGN_UNSUPPORTED` | 변수 수가 방식 지원 범위 밖, k = 0 | 방식별 문구(§20.5) |
| `GENERATOR_UNAVAILABLE` | scipy import 실패 | §20.5.3 |
| `VAR_RANGE_INVALID` | 정수 형식 파라미터의 범위·표 값이 정수가 아님(native-vars.md §5 정수 규칙, `nearest.INT_RANGE_CODE`) | "정수 파라미터는 정수 범위여야 합니다" |

notes(막지 않음, 신규 `BatchNote.code`): `FIXED_EXCLUDED`("고정 변수 X·Y는 설계에서 빼고 고정값을 씁니다"), `FULL_FACTORIAL_USED`, `BBD_PAIRWISE`, `DUPLICATE_ROWS`("정수 반올림 뒤 같은 조합이 N개 있습니다 — 같은 예측이 반복됩니다"), `SEQUENCE_CONTINUED`, `INFLUENCE_TOO_FEW`.

### 20.10 화면(필수 UI만)

- **④ B 설정**(`BatchSetup`): 기존 라디오 3개를 **방식 드롭다운 1개**(§20.4 묶음·순서)와 그 아래 **설명 상자**(4줄, 추천 배지, 고를 때마다 바뀜, 권장 run 계산값 덧붙임)로 바꿉니다. 처음 열면 `lhs_opt`(추천)이고 localStorage에 저장하지 않습니다. 방식별 입력:
  - LHS 계열: 범위 표 + 조합 수(기본 = 권장 계산값) + 시드(+ 최적화 LHS 기준 세그먼트 `최소 거리`(기본)·`상관 최소`).
  - Sobol: 범위 표 + run 수 드롭다운(2^m ≤ R, 기본 = 권장) + 시드 + 체크 `이전 Sobol 배치에 이어서 추가`. 켜면 같은 템플릿 Sobol 배치 드롭다운(`B-003 · 16개 · 시드 1`)이 나오고, 범위·시드 입력은 이전 값을 보여 주며 비활성, run 수 기본 = 이전 합계.
  - 전체 요인: 범위 표에 `수준` 열(2~10, 기본 3^k ≤ R이면 3, 아니면 2) + 곱 run 수 표시.
  - 부분 요인: 해상도 세그먼트 `V`(기본)·`IV`. CCD: α 세그먼트 `면중심`(기본)·`내접`. PB·BBD: 범위 표만.
  - 표·① DOE: 기존 그대로.

  미리보기 결과 위에 `실제 run N개 · <방식 이름>` + `sampling.meta.quality`(있으면 "최소 거리 0.21 · 최대 상관 0.08") + notes 회색 줄을 둡니다. problems는 기존처럼 보여 줍니다.
- **④ 배치 결과**(`BatchResult` 머리): 한 줄 `표본: <label> · <요약>`(예 "Sobol 16개 · 시드 1 · B-003에 이어서", "부분 요인 해상도 IV · 16개").
- **① DOE 생성**(`DoeGenCard`): 드롭다운 기본 = `recommended` 항목(없으면 첫 항목 — 기존). 아래 설명 상자(desc_id 문구, null이면 일반 문구) + 고정 회색 한 줄(§20.4). 옵션 입력은 기존 그대로입니다.
- **⑤**: 영향도 탭은 §20.7에 따라 표시합니다. 출처 드롭다운 라벨에 방식을 덧붙입니다(`B-003 · Sobol · 32 run · 10-18`, `DOE-001 · LatinHyperCube · 50 run`).

### 20.11 설정

- `train_data.recommended_doe_type: str = "TYPE_LATINHYPERCUBE"`(빈 문자열 = 추천 없음 → 첫 항목). 기본값은 스키마 한 곳(`physicsai_core/config/schema_stages.py`)에 두고, `config/platform.example.yaml`에 주석 한 줄을 둡니다. 검증은 문자열이면 됩니다(정의 파일에 없는 값이면 추천 없음).
- 새 상한은 없습니다. `predict_batch.max_runs`(200)를 모든 kind에 씁니다. lhs_opt의 C·T, Sobol 최소 m 등은 알고리즘 상수(계약 고정)입니다.

### 20.12 시험(V3-S15-*)

| ID | 기준 |
|---|---|
| V3-S15-1 | `lhs_opt` 골든(n = 6·k = 2·seed 1, maximin·corr 각각 값 JSON 고정, 허용 1e-12) + 성질: 같은 seed 두 번 같음, 다른 seed 다름, 열마다 칸당 1점, 최종 점수 ≤ 후보 최선 점수, `quality` 값, n = 200·k = 20 10초 안 |
| V3-S15-2 | `sobol`: 같은 입력 두 번 같음, n = 2^m에서 열마다 1/n 칸당 1점, 이어서 추가 = 처음 2n개 생성의 뒤 n개와 같음, `COUNT_NOT_POW2`, `offset % count`, `CONTINUE_INVALID` 4사유, `SEQUENCE_MISMATCH`(저장 값 변조), `GENERATOR_UNAVAILABLE`(import 실패 흉내), `rng`/`seed` 키워드 두 분기(시그니처 흉내), 경고가 밖으로 새지 않음, meta.generator |
| V3-S15-3 | `fullfact`: 사전식 순서(마지막 변수가 가장 빠름), run = ΠL, 끝값 정확(lo·hi), 정수 변수 서로 다른 정수 수준·`LEVELS_INVALID`(초과·모르는 이름·범위), `TOO_MANY_ROWS`, 고정 변수 + `FIXED_EXCLUDED` |
| V3-S15-4 | `fracfact`: 표 15칸 모두 정의 관계로 해상도 ≥ 요청 계산 확인, 열 균형·쌍 직교, run 수 = §20.5.9, Yates 순서, `FULL_FACTORIAL_USED`, k = 1·12 `DESIGN_UNSUPPORTED`, meta letters·generators |
| V3-S15-5 | `pb`: k = 2~47 크기 = 규칙, 모든 N ≤ 200에서 XᵀX = N·I, N = 12 첫 행 = `++-+++---+-`, construction paley/sylvester |
| V3-S15-6 | `bbd`·`ccd`: run 수 = §20.5.9, k 한계(`DESIGN_UNSUPPORTED`·`TOO_MANY_ROWS`), 수준 집합(BBD 3, CCF 3, CCI 5), 모든 값 ∈ [lo, hi], 중심 행 마지막, `BBD_PAIRWISE`, 정수 변수 `DUPLICATE_ROWS` |
| V3-S15-7 | `batch_matrix` 분기: kind → `source_kind` 10개, kind별 `source_meta` 키, 미리보기 행 = 작업 생성 뒤 `predict_batch_runs`(7개 kind 모두), `INFLUENCE_TOO_FEW`, **기존 `lhs`·`table`·`train_doe` 골든(V3-S9-5) 무변경** |
| V3-S15-8 | API: preview `sampling`·`notes`·`count`·`recommended_count`, 모양 422(모르는 kind·resolution 3·alpha 오류·seed 음수), 작업 생성 → DB `source_kind` 새 값, 상세 `sampling.influence_class`(kind별·소유 EXPLORE formal·VERIFY reference·TRAIN_DOE가 ① 유형 따름·DOE 없음 reference), 목록 `sampling`, Sobol 이어서 추가 생성 끝까지, openapi 재생성, `operation_ids.txt` 불변 |
| V3-S15-9 | migration 0012: 새 kind 10개 허용·`'FOO'` 거부, 기존 행 보존, `MIGRATION_HEAD`, downgrade 거부 |
| V3-S15-10 | ① `doe-types`: 4개 value의 desc_id, `recommended`(기본 LHS, 설정 `TYPE_SOBOL`, 없는 값 → 아무것도 아님), `influence_class`. `result-table`: LHS·Sobol·FullFact formal, FracFact reference + RESOLUTION별 문구, 모르는 유형 reference, 응답 없음·n 부족 off + 사유, `influence_ok` = class ≠ off, V3-S14-1 나머지 그대로 |
| V3-S15-11 | 프런트 `lib/sampling.ts`: 모든 desc_id 문구 4줄·빈 줄 없음·§20.4와 글자 단위 일치(픽스처), `expectedRuns`·`recommendedCount` = §20.5.9 표(픽스처 `fixtures/samplingRuns.json`, 계약 표를 옮긴 것) |
| V3-S15-12 | ④ 화면: 드롭다운 묶음·순서, 기본 최적화 LHS + 추천 배지, 고를 때마다 설명 바뀜, 방식별 입력(Sobol run 수 선택·이어서 추가 후보 필터·입력 비활성, 전체 요인 수준·곱, 해상도, α), kind별 요청 body, 미리보기 run 수·quality·notes, 배치 결과 머리 한 줄, 목 |
| V3-S15-13 | ① 화면: 기본 = recommended(없으면 첫 항목), desc_id 설명·null 일반 문구, 회색 한 줄, 목 |
| V3-S15-14 | ⑤: formal 안내 없음 / reference 회색 `influence_note` / off 사유, `fromBatch`가 `sampling.influence_class` 사용, `fromDoe`가 `influence_class` 사용, 출처 라벨에 방식, V3-S14-2·4·5·6 회귀 통과 |
| V3-S15-15 | 회귀: `scripts/test-all` 전체, 워커 시험 무변경 통과(워커 코드 변경 없음), ⑥ 내장 최적화 시험(V3-S13-*) 무변경, 프런트 빌드본 최신 |

### 20.13 서버 확인(사용자)

| ID | 확인 |
|---|---|
| E4-13-1 | ④ 최적화 LHS 20개(기본 선택 확인) → 생성·예측 완료 → ⑤ 영향도 정식 표시 |
| E4-13-2 | ④ Sobol 16개 → 같은 템플릿에서 이어서 추가 16개 → 두 배치 값이 겹치지 않고 미리보기 notes "합치면 32개". ⑤에서 두 배치 겹쳐 보기 |
| E4-13-3 | ④ BBD(변수 3) 13 run·부분 요인 IV → ⑤ 영향도 참고용 문구 |
| E4-13-4 | 미리보기 응답 시간: 최적화 LHS 200개·Sobol 128개(서버 PC에서 첫 호출 포함 2초 안 목표), 서버 scipy 버전 = lock(1.17.1) |
| E1-8-1 | ① DOE 생성 화면 기본 = LatinHyperCube·설명문 표시, Sobol DOE를 ⑤에서 열면 영향도 정식 |
| E1-8-2 | (선택, 미결 1 판단용) 원본 앱·HyperStudy 문서로 `hst_gen_radioss_core`가 정의 파일 밖 value(Hammersley·MELS·Box-Behnken·CCD·Plackett-Burman)를 받는지 확인. 시험 DOE 1회는 관리자가 정의 파일 사본에 항목 1개를 넣고 실행해 hstbatch 로그를 봅니다 |

### 20.14 파일 소유(겹침 없음)

**Impl-Backend**
- 신규 `backend/physicsai_core/sampling/{__init__.py, registry.py(방식 목록·라벨·desc_id·등급·문구 상수·권장 run), designs.py(lhs_opt·fullfact·bbd·ccd·공통 코드값 변환·quality), fractional.py(생성자 표·Yates·해상도 계산·PB 생성), qmc.py(Sobol 지연 import·키워드 호환·경고 처리)}`
- `backend/physicsai_core/stage4_predict/batch_matrix.py`(kind 분기·`SOURCE_KINDS`·`PROBLEM_CODES`·`BatchMatrix.notes`·이전 배치 인자)
- `backend/physicsai_core/db/tables/predict_batch.py`, `backend/physicsai_core/db/__init__.py`(`MIGRATION_HEAD`), `migrations/versions/0012_sampling_kinds.py`, `backend/physicsai_core/db/repositories/predict_batches.py`(이전 배치 run 값 읽기 — 필요 시)
- `backend/physicsai_core/config/schema_stages.py`(`recommended_doe_type`), `config/platform.example.yaml`
- `backend/physicsai_api/schemas/predict_batch.py`, `backend/physicsai_api/schemas/stage1_train_data.py`
- `backend/physicsai_api/services/job_params/stage4_batch.py`(이어서 추가 조회), `backend/physicsai_api/services/predict_batches.py`(preview·상세·목록 `sampling`), `backend/physicsai_api/services/stage1_train_data.py`(doe-types 꾸밈), `backend/physicsai_api/services/doe_result_table.py`(등급)
- `backend/openapi.json`, `backend/tests/common/test_openapi.py`(스냅샷이 스키마 이름을 볼 때만)
- 시험: 신규 `backend/tests/test_sampling_designs.py`(V3-S15-1~6)·`test_sampling_api.py`(8·10)·`test_sampling_db.py`(9), 기존 `test_batch_matrix.py`(7)·`test_doe_result_table_api.py`(influence_ok 의미 갱신)·`fixtures`(lhs_opt 골든 JSON)
- 워커(`worker/**`) 변경 없음

**Impl-Frontend**
- 신규 `frontend/src/lib/sampling.ts`(라벨·묶음·설명문 §20.4·추천·`expectedRuns`·`recommendedCount`), `frontend/src/components/SamplingDescription.tsx`(①·④ 공용 설명 상자), `frontend/src/stages/stage4/batch/{SamplingPicker.tsx(드롭다운 + 방식별 입력), samplingSource.ts(화면 상태 → BatchSource, 순수)}`
- 수정: `frontend/src/stages/stage4/batch/{BatchSetup.tsx, BatchPreview.tsx(run 수·quality·notes), BatchResult.tsx(머리 한 줄)}`, `frontend/src/stages/stage1/DoeGenCard.tsx`, `frontend/src/api/types.ts`(union·새 타입), `frontend/src/analysis/{resultTable.ts(influence.class·note), influence.ts(문구 상수 정리), adapters/fromBatch.ts, adapters/fromDoe.ts}`, `frontend/src/stages/stageAnalysis/{InfluencePanel.tsx, SourcePicker.tsx}`
- 목: `frontend/src/mock/{predictBatch.ts, stage1.ts, trainDoe.ts}`
- 시험: 신규 `frontend/src/__tests__/sampling.test.ts` + `fixtures/samplingRuns.json`·`fixtures/samplingText.json`, 수정 `predictBatch.test.tsx`·`stage1.test.tsx`·`analysisAdapters.test.ts`·`analysisScreen.test.tsx`·`mockContract.test.ts`
- 생성 파일: `frontend/src/api/generated/schema.d.ts`(`npm run gen:api`), `frontend-dist/**`(`scripts/build-frontend-dist`, 프런트 커밋에 함께)

**Plan**: phase3.md §14.5 표에 §20 포인터, s14_analysis.md §19.5·§19.6 규칙 교체 표시, `docs/architecture.md`(`physicsai_core/sampling/`·migration 0012), `docs/e2e-checklist.md`(E4-13·E1-8), 관리자 매뉴얼(`recommended_doe_type`·정의 파일 항목 추가 안내).

**Verifier**: V3-S15-1~15 + V3-S9·S12·S13·S14 회귀(수정 없음). 부분 요인 표·PB 직교를 독립 계산으로 다시 확인합니다.

### 20.15 순서

1. S14 커밋(선행).
2. Backend P0(1커밋): `sampling/*`·`batch_matrix`·migration 0012·테이블 상수, 시험 V3-S15-1~7·9.
3. Backend P1: 스키마·서비스·설정·openapi, 시험 8·10. 이와 병렬로 Frontend가 목 라우트로 화면·lib·⑤ 진행(11~14). API 모양은 §20.6으로 고정합니다.
4. Backend 병합 뒤 Frontend `gen:api` 1회 → `frontend-dist` → V3-S15-15 → Verifier.

### 20.16 리스크

- **scipy 버전 차이(Sobol)**: 스크램블 결과가 버전마다 다를 수 있습니다. 대응:
  - 만든 배치 값은 DB에 있어 재현이 필요 없고, 이어서 추가만 다시 만든 값을 대조합니다(`SEQUENCE_MISMATCH`).
  - 시험은 고정값 대신 성질로 봅니다(skip 없음). 개발 PC 1.18.1과 lock 1.17.1이 다르다는 점은 meta.generator로 남깁니다.
- **API 프로세스 scipy 적재**: Sobol 첫 미리보기에서 0.3~1초·수십 MB가 듭니다. S13의 "API는 numpy를 부르지 않음" 원칙에 대한 유일한 예외로 `qmc.py` 한 곳에만 둡니다. 원치 않으면 순수 Python Sobol(방향수 표 + 스크램블)로 바꿀 수 있습니다(미결 2).
- **최적화 LHS 미리보기 시간**: 순수 Python 동기 계산입니다. T·C를 고정하고 n ≤ 200으로 상한을 둡니다.
- **2수준·2차 설계 점이 범위 경계에 몰림**: 학습 범위 경계(꼭짓점)는 AI 예측 신뢰가 낮을 수 있습니다. 설명문에 "AI 학습 표본으로는 맞지 않습니다"를 명시했습니다.
- **정수 변수**: BBD·CCD 중간값·CCI ±1/α를 반올림하면 수준이 겹쳐 중복 행이 생길 수 있습니다(`DUPLICATE_ROWS` 안내, 막지 않음).
- **2수준 설계의 PRCC**: 순위 동점이 많아 PRCC가 거칩니다. 그래서 참고용입니다(전체 요인은 사용자 결정으로 정식).
- **라벨 변경**: "범위·개수로 자동(LHS)" 문구를 쓰는 기존 프런트 시험·e2e 문구를 함께 고쳐야 합니다.
- **①의 한계**: ①은 새 방식을 쓸 수 없습니다. 사용자가 기대한 범위보다 좁으므로 미결 1을 결정해야 합니다.

### 20.17 미결(사용자 확인 대상)

1. **① 새 방식 지원 경로**:
   - (A) 원본 정의 파일에 HyperStudy 유형을 추가 — pyd가 받는 value를 확인해야 합니다(E1-8-2).
   - (B) ① 생성을 플랫폼 실행기 + 플랫폼 표로 전환 — S16 후보. 원본 일치 판정·`DG_SCAN` 재작성이 필요합니다.

   현 계약은 둘 다 하지 않습니다.
2. API 프로세스의 scipy 지연 import(Sobol만)를 허용할지, 순수 Python Sobol로 갈지.
3. ④ 기본값을 최적화 LHS(계약)로 할지 Sobol로 할지(메인 의견은 둘 다 후보).
4. 부분 요인 해상도 V를 정식으로 올릴지(현재 참고용 — 주효과·2인자 교호작용이 깨끗해 정식 근거도 있음).
5. BBD 변수 6개 이상을 쌍 방식(run 많음)으로 둘지, 표준 블록(BIBD) 표를 넣을지.
6. 이어서 추가한 Sobol 배치를 ⑤에서 합쳐 하나의 결과 표로 분석하는 기능(후속).
7. ⑥ 탐색 배치(EXPLORE)를 최적화 LHS로 바꿀지(후속, §18 변경).

## 변경 메모(이 문서분 — phase3.md 변경 메모 목록으로 옮김)

- **D3-63 (사용자 결정 2026-10-18, S15 표본 방식 추가 — Plan)**: §20.
  1. ④ 일괄 예측 `source.kind`에 `lhs_opt`(최적화 LHS, maximin/상관 최소, 순수 Python 결정적)·`sobol`(스크램블, `scipy.stats.qmc` 지연 import, 2^m, 같은 시드·범위로 이어서 추가 + 재생성 대조)·`fullfact`(변수별 수준)·`fracfact`(2수준 해상도 IV·V, 검증한 생성자 표)·`pb`(Paley 순환/Sylvester)·`bbd`(쌍 방식, 중심 1)·`ccd`(면중심·내접, 중심 1)를 추가합니다. 미리보기·생성·워커가 같은 행을 씁니다.
  2. ④ 기본 = 최적화 LHS, ① 기본 = LatinHyperCube(설정 `train_data.recommended_doe_type`). 선택창 설명문(§20.4 문구 확정)을 둡니다.
  3. ①은 원본 pyd가 HyperStudy로 생성하는 구조라 정의 파일(`DATA_doe_design_type.json`) 4개 유형을 그대로 두고 설명 id·추천·등급만 붙입니다. 새 방식은 ④ 전용이고, ① 플랫폼 표 생성은 S16 후보입니다.
  4. DB: `predict_batches.source_kind` CHECK 확장 migration `0012_sampling_kinds`, 방식 인자는 `source_meta`. ① DB 변경은 없습니다.
  5. 영향도 등급 formal/reference/off를 서버가 정합니다(§20.7). s14 §19.5 `influence_ok` = class ≠ off로 확장하고, §19.6 "LHS가 아닌 해석 DOE 비활성"·"LHS가 아닌 표 — 참고용"을 등급 표로 바꿉니다. 최적화 VERIFY·FINAL 배치는 참고용입니다.
  6. API: 새 라우트 없음. 요청 union 확장, preview `sampling`·`notes`, 상세·목록 `sampling`, doe-types `desc_id`·`recommended`·`influence_class`, result-table `influence_class`·`influence_note`·`sampling`.
  7. S13 §18.2 "API 프로세스 numpy 미적재"는 Sobol 계산(`physicsai_core/sampling/qmc.py`)만 예외입니다.
  8. 시험 V3-S15-1~15, 서버 확인 E4-13·E1-8.

### 20.18 미결 처리(사용자 2026-10-18 "일단 가보자고")
- 미결 1: ①은 이번에 4개 유형 유지. HyperStudy 매뉴얼상 Hammersley·MELS·Box-Behnken·CCD·Plackett-Burman·D-Optimal·Taguchi·Run Matrix를 지원 — 내부 식별자는 서버 설치 폴더에서 확인 후 정의 파일 추가(E1-8-2). Run Matrix가 원본 pyd로 가능하면 안 B(플랫폼 표 → ①)를 S16에서 우선 검토.
- 미결 2~5: 계약 기본안 채택(API Sobol 지연 import 허용, ④ 기본 최적화 LHS, 부분 요인 V 참고용, BBD k≥6 쌍 방식).
- **D3-63 구현 메모 (2026-10-18, Verifier 판정 반영)**: 기존 `lhs`는 V3-S9-5 골든 유지를 위해 `quality`를 DB에 저장하지 않고 응답에서 계산, `FIXED_EXCLUDED`·`DUPLICATE_ROWS`·`INFLUENCE_TOO_FEW`는 새 7종에만 적용. `CONTINUE_INVALID` 사유 추가 "이어서 추가할 이전 배치를 찾을 수 없습니다". 이어서 추가 권장 run·문구 = `offset & -offset`(offset이 2^m이면 계약과 같음; R 초과 연쇄는 후속). `lhs_opt` seed ≥ 0(음수 422). 프런트는 새 7종 `ranges`를 고친 변수만 보냄(없으면 null). ⑤ influence 모양 `{ok, cls, note, reason}`. migration 0012에 따라 `worker/tests/ops/test_ops_admin.py` head 문자열만 갱신(워커 코드 무변경). fracfact k=2·3에서 IV 요청 시 IV 문구 사용(확인 대기).
- **2026-10-22 doe-methods 반영**: §20.1 비범위 "⑥ 내장 최적화 탐색 배치에 최적화 LHS 적용(현재 LHS 유지)"는 [doe-methods.md](doe-methods.md) DM-C5(⑥ `explore.method`, 기본 `lhs` 불변)로 대체. 새 kind `halton`·`random`(④·①·⑥)과 ① `table`은 같은 문서 §4.1, `source_kind` CHECK 확장은 migration `0023_doe_methods`.
