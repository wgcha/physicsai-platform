# 계약: ③ 데이터 점검 — 학습 run 이상치 제외 추천 (data-health, DH-*)

작성: Plan, 2026-11-03(**확정** — 범위·판정·적용 위치·추천만은 사용자 결정, 나머지는 기본값 채택). 결정 번호 `DH-n`, 검사 `V-DH-n`, 변경 메모 `DH-Cn`.
기준: v0.2.15(be21319, migration HEAD `0025_doe_preview`, paicad 0.14.1). 릴리스: **v0.2.16**, migration `0026_data_health`(down_revision `0025_doe_preview`). paicad 변경 없음.
상위 계약(여기서 다시 쓰지 않는 규칙은 그대로): [platform.md](platform.md) §8.4(③-1 DATASET_CREATE), [phase2.md](phase2.md) §6.6.1(①-6 `TD_RESP_EXTRACT`)·§6.7~§6.10(② 큐레이션·`exclude_files`), [job-queues.md](job-queues.md)(JQ-1 자원 종류), [equiv-check.md](equiv-check.md)(run 해석·`mesh_volume`·`starter_mass`·응답 재사용 규칙), [asm-match.md](asm-match.md) §6.4(조립 매칭 run의 쿠션 PART), [mcp.md](mcp.md) §15(정적 시험).

## 0. 한 줄 요약

③-1 데이터셋 생성 카드에서 **[데이터 점검]**을 누르면 CPU 대기열 작업 `DATA_HEALTH`가 입력 h3d 폴더의 run마다 ① 해석 건전성(정상 종료·에너지 오차·추가 질량·선택적으로 hourglass/접촉 에너지 비) ② 응답·모델 속성(쿠션 bbox 치수·CoG·부피, 모델 총질량)의 일반 Z(3σ)와 견고 z(중앙값·MAD) ③ 파라미터 공간 kNN 이웃 대비 튐을 계산한다. **판정은 견고 기준**(①은 절대 임계)이며 결과는 추천 표(사유·점수)로만 보여 준다. 사용자가 표에서 고른 run만 `DATASET_CREATE.exclude_files`로 빠진다(자동 제외 없음). h3d 추출·Altair 라이선스는 쓰지 않는다.

---

## 1. 조사 결과(재사용 근거)

| 항목 | 현재 코드 | 이 계약에서의 쓰임 |
|---|---|---|
| ③-1 입력·수집 | `DatasetCreateParams{input_path|curation_id}` → DS_SCAN `collect_h3d(root, exclude)`(`stage3_model/dataset_split.py`) | 점검 대상 run 집합 = DS_SCAN과 **같은 함수**로 수집한 h3d |
| ③-1 run 제외 | **없음**(DS_SCAN은 전부 사용) | 새 선택 키 `exclude_files` 추가(DH-10) |
| ② run 제외 | `CU_H3D_CURATE`·`CU_T01_CURVES`의 `exclude_files`(원천 루트 기준 상대경로, `/` 구분, 정확 일치) | 같은 이름·의미를 ③에 그대로 씀 |
| h3d → run_key | 큐레이션 `02_curated/<cid>/file_list.json` 항목 `{run_key, output_rel}`(원천 TRAIN_DOE), 직접 입력이면 `curation.run_key_of`(결과 루트 바로 아래 폴더) | run 해석(§4.1) |
| run 입력·결과·파라미터 | `equiv/sides._train_doe`: `samples.csv`/points → `Run.params`, `R(run)`=`01_train/results/<doe>/<run_key>`, `mesh_inc`(`predict.mesh_include_name`, altair·native 같은 이름 — GE §2 항목 3), 조립 매칭 run은 `mesh_tree`+`mesh_parts` | 그대로 호출(복사 구현 금지) |
| 메시 부피 | `equiv/volume.py` `read_include`·`read_tree`·`resolve_parts("cushion")`·`part_volume`(TETRA·BRICK·PENTA, 크기 상한 `fem_verify.include_scan_max_bytes × 16`) | 같은 파서·상한으로 부피·bbox·CoG(§3.3) |
| 총질량 | `equiv/compute._volume(origin="starter_mass")`: `*_0000.out`/`.sty`에서 `TOTAL MASS` 정규식, **파일 끝까지 줄 단위 읽음** | 공용 함수로 옮기고 읽기 바이트 상한 추가(DH-9) |
| 응답 | ①-6 `R(run)/responses_run.csv`(이름,값) + `D/responses.json`(spec), 재사용 조건 = 같은 이름 spec 일치(equiv-check §4.2) | 재사용만, 추출 안 함(DH-3) |
| 해석 출력 | TD_SOLVE 회수 패턴 `["*.h3d","*T01","*_0000.out","*_0001.out"]`(`hpc.collect_patterns`) → `R(run)` | 정상 종료·에너지·추가 질량(§3.1) |
| 정상 종료 판정 | **기존 코드 없음**(TD_RESULT_IMPORT는 파일 존재만 봄) | 새 공용 파서(꼬리만) |
| 꼬리 읽기 | `error_bundle.read_tail(path, limit)` | 그대로 사용 |
| T01 에너지 곡선 | T01 바이너리 직접 파서 **없음**. ②-4 `CU_T01_CURVES`가 HyperGraph로 `CURVES/<run_folder>/<base>_curves.json` 생성(형식 U27, `series` 있으면 사용) | 있으면 재사용, 없으면 NA(DH-8) |
| 형상 엔진 | `dataset_engine.detect`(altair/native 혼합 422) | 그대로(점검도 혼합 금지) |
| paicad 측정 | `_paicad/update/update.json` `bodies[].volume·bbox`(CAD 기준), CoG 없음 | **사용 안 함**(DH-14) |

## 2. 결정(DH-*)

| ID | 결정 | 근거 |
|---|---|---|
| DH-1 | 적용 위치 = **③-1 데이터셋 생성만**. 결과는 **추천만** — 데이터셋·파일을 바꾸지 않고, 사용자가 표에서 고른 run만 다음 DATASET_CREATE에서 빠진다. 기본 선택 없음(추천 행은 강조만), [추천 항목 선택] 버튼은 사용자가 누를 때만 | 사용자 결정 3·4 |
| DH-2 | 실행 = **비동기 job `DATA_HEALTH`**(stage 3, lane SLOT → CPU 대기열, step 전부 INTERNAL). 동기 API 아님 | run N개마다 include 메시(수~수십 MB)·출력 꼬리를 공유 드라이브에서 읽어 N=300이면 수 분 — HTTP 제한 시간·취소·진행률·로그가 필요. INTERNAL만이라 GPU 무관, JQ-1(INTERNAL = 중립, 시작 구간 CPU) 그대로 |
| DH-3 | **h3d 추출 없음**(HyperView/HyperGraph 실행 0회). 응답은 ①-6 `responses_run.csv` 재사용만, 없으면 그 지표 NA + 안내 경고 `DH_RESP_NOT_EXTRACTED`("①-6 run 응답 추출을 먼저 실행하면 응답 지표를 함께 봅니다") | Altair 라이선스·시간 소비 없음. 무거운 추출이 필요한 지표는 DH-12 확장 지점에서 기존 추출 재사용 조건으로만 |
| DH-4 | 지표 = §3 표(① 건전성 6, ② Z 대상 = 스칼라 응답 R개 + 모델 속성 8개, ③ kNN = ② 대상 전부) | 사용자 결정 1 |
| DH-5 | ② 지표마다 **일반 z와 견고 z를 둘 다 계산·표시**, **추천 판정은 견고 z와 kNN 점수**(일반 3σ는 표시·"3σ만" 태그). 임계값은 설정 `data_health` **한 곳** | 사용자 결정 2. 일반 3σ는 이상치 자신이 평균·σ를 끌어 가려지는(masking) 문제 — 견고 기준이 안정 |
| DH-6 | 파라미터 공간 튐 = **kNN 국소 중앙값 잔차**(LOO 회귀 잔차 아님) | §3.4 근거: 낙하 응답의 바닥 닿음 같은 비선형·국소 급변을 전역 회귀가 잔차로 오인, 2차 회귀는 n ≥ p(p+3)/2(+1) 필요(p=10 → 66), kNN은 모델 가정 없음·numpy만·O(n²p) |
| DH-7 | 표본 수 규칙: 유효 값 n < `min_n`(8)이면 그 지표 Z·견고 z 생략(`SKIP_SMALL_N`), n < `knn_min_n`(12)이면 kNN 생략. 생략은 판정에 쓰지 않고 표에 "표본 부족" | 사용자 예시 규칙. kNN k=5는 이웃 밖 여유가 필요 |
| DH-8 | ① 건전성은 **절대 임계**(분포 무관) — 정상 종료 아님·임계 초과면 추천. hourglass/접촉 에너지 비는 ②-4 곡선 JSON이 이미 있고 설정 `t01_series`가 지정된 경우만, 그 밖 NA(`T01_CURVE_NONE`) | 비정상 종료 run은 1개만 있어도 제외 대상(분포 판정 부적합). T01 바이너리 파서 없음 → 새 파서는 비범위 |
| DH-9 | Radioss 출력은 **꼬리·요약만**: engine `*_0001.out`은 끝 `out_tail_bytes`(256 KiB)만, starter `*_0000.out`은 앞에서부터 줄 단위로 읽다 `TOTAL MASS` 첫 일치에서 멈추고 `starter_scan_max_bytes`(64 MiB) 넘으면 NA(`OUT_TOO_LARGE`). 정규식은 설정 | 결과 파일 본문 대량 읽기 금지(요구), 정규식 하드코딩 금지(AGENTS) |
| DH-10 | run 식별·제외 단위 = **입력 루트 기준 h3d 상대경로**(`/`). DATASET_CREATE에 선택 키 `exclude_files`(②와 같은 이름·정확 일치)와 `health_job_id`(기록용) 추가. DS_SCAN이 수집 후 제외 | ② 기존 규칙과 같게. split_group=parent_dir여도 파일 단위 |
| DH-11 | 저장: DB = `jobs.result` 요약 + `datasets.excluded_count`·`health_job_id`(migration 0026). run별 상세는 파일 `03_dataset/_health/<job_id>/`. 새 결과 테이블 없음 | AGENTS "DB에는 경로·상태·수치 요약만" |
| DH-12 | 필드 PCA(h3d 결과장 주성분 이상치)는 **비범위**. 확장 지점만: 지표 레지스트리 kind `field_pca`, LOCAL step `DH_FIELD`(res=cpu) 자리, 입력은 ② 큐레이션 h3d(이미 추출된 것만), PCA 점수는 같은 견고 z 판정에 합류 | 사용자 결정 1-④ |
| DH-13 | MCP: `DATA_HEALTH`는 `MCP_JOB_EXCLUDED`(사유 "③ 데이터셋 사람 판단 단계 — DATASET_CREATE와 같음"), 새 GET API는 `x-mcp.exclude` 같은 사유. 용어집 `ko` 등록 | mcp.md §5.1 기존 분류와 일관 |
| DH-14 | 모델 속성 원천 = **입력 메시 include**(altair·native 공통). paicad `update.json`은 쓰지 않음 | 두 엔진이 같은 정의(메시 기준)여야 한 분포에서 비교 가능. CAD bbox ≠ 메시 bbox, CoG 없음, altair run에는 없음 |
| DH-15 | 대상 엔진 혼합 금지(`dataset_engine.detect` 그대로 422 `ENGINE_MIXED`). DOE 연결이 없는 입력(외부 FOLDER·SPDM_IMPORT)은 **제한 모드**: ①만(출력 파일이 h3d 옆에 있을 때), 경고 `DH_NO_DOE_LINK` | 파라미터·응답·메시 위치를 알 수 없음 |
| DH-16 | Study당 활성 `DATA_HEALTH` 1개(초과 409 `DATA_HEALTH_ACTIVE`). 재시도 허용(같은 params, 폴더 `_backup` 후 다시) | 같은 입력 중복 점검 방지 |

## 3. 지표 정의

표기: run i의 지표 값 `x_i`, 유효 값 집합 V(결측·비유한 제외), n = |V|. 모든 계산은 numpy(float64). 새 패키지 없음.

### 3.1 ① 해석 건전성(절대 임계, run마다)

| id | 원천 | 정의 | 판정(설정 키) | 결측 |
|---|---|---|---|---|
| `term` | `R(run)` 재귀 `data_health.engine_out_glob`(`*_0001.out`) 정확히 1개, 꼬리 | `normal_regex` 일치 → `NORMAL`, `error_regex` 일치 → `ERROR`, 둘 다 없음 → `UNKNOWN`(중단·잘림) | `NORMAL` 아니면 FAIL | 파일 0개 `OUT_MISSING`, 2개 이상 `OUT_AMBIGUOUS` → FAIL 아님, NA + 표시 |
| `energy_err_pct` | 같은 꼬리의 **마지막** 사이클 줄(`cycle_regex`, 이름 그룹 `err`) | ERROR 열(%, 부호 그대로) | `|값| > energy_error_pct_max`(10.0) | 사이클 줄 없음 NA |
| `added_mass` | 같은 줄 그룹 `mas` | MAS.ERR(추가 질량/초기 질량, 무차원) | `> added_mass_ratio_max`(0.05) | NA |
| `hg_ratio` | ②-4 `CURVES/<run_folder>/*_curves.json`(같은 Study, run_key로 대응, 최신 READY T01 큐레이션) series `t01_series.hourglass`·`.internal` | `max_t HE(t) / max_t IE(t)` | `> hourglass_ratio_max`(0.10) | 곡선·series 없음 또는 `t01_series` null → NA `T01_CURVE_NONE` |
| `contact_ratio` | 같음, `.contact` | `max_t CE(t) / max_t IE(t)` | `> contact_ratio_max`(0.10) | NA |
| `mass_total` | `R(run)`→입력 폴더 순서로 `starter_out_glob`(`*_0000.out`, `*_0000.sty`) | `TOTAL MASS` 첫 일치(기존 `_MASS_RE`) | ①에서는 판정 없음 → ② Z 대상 | NA `MASS_SOURCE_MISSING`·`OUT_TOO_LARGE` |

- `IE` 최대값 ≤ `zero_tol`이면 비 NA(`IE_ZERO`). 판정 FAIL 1개 이상 → run 추천, 사유 코드 `SOUND_<ID>`.
- 정규식 기본값(설정 예시에 둠, Backend가 실제 출력 픽스처로 확인): `normal_regex: "NORMAL TERMINATION"`, `error_regex: "ERROR TERMINATION"`, `cycle_regex`는 ERROR 열(`%` 접미 허용)과 MAS.ERR 열을 이름 그룹으로 잡는 한 줄 패턴. 대소문자 무시.

### 3.2 ② Z 대상 지표와 일반·견고 z

Z 대상: 스칼라 응답 `resp:<name>`(R개, `D/responses.json`의 CURVE 종류 제외 — equiv/S17 `SILENT_REASONS`와 같음) + 모델 속성 `bbox_dx·bbox_dy·bbox_dz`, `cog_x·cog_y·cog_z`, `volume`, `mass_total`. 사용자는 응답 부분집합을 고를 수 있다(params `responses`, 기본 전부).

- 일반 z(표시만): `z_i = (x_i − mean_V) / std_V`, `std` = 표본 표준편차(ddof=1). `std_V = 0` → z = 0.
- 견고 z(판정): `zr_i = (x_i − med_V) / (1.4826 · MAD_V)`, `MAD_V = med_V(|x − med_V|)`.
  - `MAD_V = 0`이면 `1.2533 · MeanAD_V`(평균 절대 편차)로 대신, 그것도 0이면 zr = 0(전부 같은 값).
- 3σ 태그: `|z| > sigma_z`(3.0). 추천 사유: `|zr| > robust_z`(3.5), 코드 `ROBUST_Z`.
- 결측: 그 run의 그 지표만 NA(사유 코드 보존), 분포 계산에서 제외. 다른 지표 판정은 그대로.
- n < `min_n` → 지표 전체 `SKIP_SMALL_N`(z·zr 비움).

### 3.3 모델 속성 계산(쿠션 기준)

- 메시: `Run.mesh_inc`면 `read_include`, 조립 매칭 run이면 `read_tree(mesh_tree)` + `resolve_parts("cushion", mesh_parts)`(equiv `mesh_volume`과 같은 경로·상한). 기준 include는 쿠션 메시만이므로 `parts=None` = 솔리드 전체 = 쿠션.
- 대상 요소 = 쿠션 PART의 솔리드 요소(TETRA4·TETRA10·BRICK·PENTA6 — `part_volume`가 지원하는 형). 대상 노드 = 그 요소의 노드 합집합.
- `bbox_d*` = 대상 노드 좌표 최대 − 최소(전역 축). `volume` = Σ 요소 부피(`part_volume` 그대로). `cog_*` = Σ(요소 부피 × 요소 중심) / volume(균일 밀도 가정 — 쿠션 단일 재료).
- 솔리드 요소 0개(쉘 쿠션 등) → 셋 다 NA `NO_SOLID` + 경고 1건. 미지원 요소형은 `EQ_VOLUME_ELEM_SKIPPED`와 같은 문구로 경고.
- 회전·정렬 이상은 bbox 치수와 CoG의 견고 z가 잡는다(Altair 방식과 같음).
- 캐시: `03_dataset/_health/_attrs/<sha256(abs path|size|mtime_ns)>.json`(include 1개당), 같은 서명이면 다시 파싱하지 않는다. 조립 트리는 트리 파일 서명 전체로 키.

### 3.4 ③ 파라미터 공간 kNN 튐(DH-6)

- 입력: `Run.params`(DOE 사용 파라미터). 정규화 `u = (p − min)/(max − min)`, min·max = `parameters_snapshot`(없으면 표본 범위). max = min인 파라미터는 뺀다. 정수 변수도 같은 방식.
- 지표마다 유효 run끼리 유클리드 거리, 이웃 = 자기 제외 가까운 `k = min(knn_k(5), n − 1)`개(동률 = run 이름순).
- 잔차 `r_i = x_i − med(x_N(i))`, 점수 `s_i = r_i / (1.4826 · MAD(r))`(MAD 0 대체 규칙 §3.2와 같음). 추천 사유: `|s_i| > knn_z`(3.5), 코드 `KNN_JUMP`.
- 파라미터가 run마다 다른 이름 집합(여러 DOE 혼합)이면 kNN 전부 생략 + 경고 `DH_PARAMS_MIXED`. 파라미터 결측 run은 그 run만 생략.
- 근거·한계: 중앙값이라 이웃 중 이상치 2개까지 견딤. 고차원(p ≳ 15)·희소 DOE에서 이웃이 멀어 민감도가 떨어짐, 경계 run은 한쪽 이웃만 가짐 → 표에 이웃 평균 거리(정규화) 표시, 판정 규칙은 그대로.

### 3.5 run 판정·점수

- `recommended = (① FAIL 1개 이상) or (어느 지표든 ROBUST_Z) or (어느 지표든 KNN_JUMP)`.
- `score = max(① FAIL 있으면 1 + FAIL 개수, max_m |zr_m|/robust_z, max_m |s_m|/knn_z)` — 1 초과면 추천. 표 기본 정렬 = score 내림차순.
- 사유 = `[{code, metric, value, z, zr, s, message}]`, `message` 한국어 예: "응답 MAX_ACC 견고 z 4.2(값 51.3, 중앙값 35.1, MAD 2.6)", "정상 종료 아님 — 오류 종료", "이웃 대비 튐 VOLUME 점수 −5.1".
- `sigma_only` = 3σ 태그는 있으나 추천 아님 → 표시만(태그 "3σ만").

## 4. 원천·run 해석

### 4.1 run 집합

1. 입력 해석은 DATASET_CREATE와 같다(`input_path` 또는 `curation_id` → 경로, `check_user_path`·`check_dataset_input`, `collect_h3d`). 파일 수 < `dataset.min_h3d_files`도 그대로 실패.
2. run_key 대응: 큐레이션 입력(원천 TRAIN_DOE) = `file_list.json`의 `output_rel` → `run_key`·`doe_id`(큐레이션 `source.doe_id`). 직접 입력이 `01_train/results/<doe_id>[/...]` 아래 = `run_key_of`(DOE 하나) 또는 `results/` 자체면 첫 폴더 = doe_id, 둘째 = run_key. 그 밖 = DOE 연결 없음(DH-15).
3. DOE마다 `equiv.sides.resolve_side(..., {"kind":"train_doe","doe_id":…})` 1회 → run_key로 `Run`(params·result_dir·mesh_inc/tree) 대응. 대응 못 한 h3d는 행은 남기고 ②③ NA(`RUN_UNLINKED`).
4. 제한 모드: ①의 `.out` 탐색 폴더 = h3d가 있는 폴더(재귀 없음).

### 4.2 재사용 규칙

| 값 | 재사용 조건 | 아니면 |
|---|---|---|
| 응답 | `R(run)/responses_run.csv` 있음 + `D/responses.json`의 같은 이름 spec(equiv-check 재사용 규칙) | NA `RESP_NOT_EXTRACTED`(추출 안 함) |
| hg/접촉 비 | 같은 Study 최신 READY `T01` 큐레이션의 run 곡선 JSON + `t01_series` 설정 | NA |
| 모델 속성 | §3.3 캐시 서명 일치 | include 파싱 |
| 이전 점검 | 재사용 안 함(매번 계산, 속성 캐시만 공유) | – |

## 5. 작업 `DATA_HEALTH`

`JobTypeDef("DATA_HEALTH", 3, "SLOT", "데이터 점검", steps, "③-1", notify_success=False)`. 기능 게이트 = `dataset_create`와 같은 기능(`features.py` 매핑).

| step | kind(무게) | 처리 |
|---|---|---|
| DH_PREP | INTERNAL 5 | 입력 해석·h3d 수집(§4.1), DOE 해석, 지표 목록·임계값 스냅숏 → `inputs.json` |
| DH_SCAN | INTERNAL 70 | run마다 ①(꼬리)·총질량·모델 속성·응답 읽기 → `runs_raw.csv`. 진행률 = run 수, 취소 확인 = run마다. run 하나의 읽기 실패는 그 값 NA + 경고(작업은 계속) |
| DH_SCORE | INTERNAL 20 | §3.2~§3.5 → `runs.csv`·`report.json` |
| DH_REPORT | INTERNAL 5 | `jobs.result` 요약(§6.1), artifact 등록 `DATA_HEALTH_REPORT`(report.json)·`DATA_HEALTH_CSV`(runs.csv) |

- 전부 INTERNAL → JQ-1상 자원 중립, 첫 구간 CPU 대기열(`cpu.max_concurrent`에 셈). `res`를 정할 LOCAL step 없음(정적 시험 통과).
- 확장 지점(DH-12): `DH_FIELD`(LOCAL, res=cpu)를 DH_SCAN 뒤에 넣을 수 있게 지표 레지스트리 `METRICS: dict[id, MetricDef(kind, source, judge)]`로 구현.
- 실패: run 0개·입력 경로 오류 = 기존 DATASET_CREATE와 같은 코드(`INPUT_INVALID`). 지표 전부 NA여도 작업은 SUCCEEDED(경고로 알림).

## 6. 저장

### 6.1 DB

- `jobs.result`(요약만): `{input_path, curation_id?, doe_ids[], engine?, n_runs, n_recommended, n_sigma_only, n_sound_fail, n_na_by_metric{}, metrics_used[], thresholds{}, limited:bool, report_rel, csv_rel, warnings[]}` — run별 값 금지.
- migration `0026_data_health`: `datasets`에 `excluded_count INT NOT NULL DEFAULT 0`, `health_job_id UUID NULL REFERENCES jobs(id) ON DELETE SET NULL`. downgrade = 두 열 삭제.

### 6.2 파일 — `<study>/03_dataset/_health/<job_id>/`

| 파일 | 내용 |
|---|---|
| `inputs.json` | params, 임계값 스냅숏, 대상 h3d 목록(상대경로), DOE·param 정의 요약 |
| `runs_raw.csv` | `file_rel,run_key,doe_id,<지표 원값…>,<지표>_na` |
| `runs.csv` | 위 + 지표별 `z`·`zr`·`s`, `recommended,score,sigma_only,reasons`(코드 `;` 연결) — 사용자 내려받기용 |
| `report.json` | 화면용: `{summary, metrics:[{id,label,unit,group,n,mean,std,median,mad,skipped}], runs:[{file_rel,run_key,recommended,score,sigma_only,sound{},values{id:{v,z,zr,s,na}},reasons[]}]}`. 크기 > `ui.max_artifact_bytes`면 `runs`를 score 상위 `data_health.report_max_rows`(2000)로 자르고 `truncated:true` |
| `_attrs/`(상위 `_health/_attrs/`) | §3.3 캐시 |

- `_health`는 DS_SCAN 수집 대상이 아니다(입력은 `01_train`·`02_curated`, `check_dataset_input`이 Study 산출 폴더 제외). 재시도 시 기존 폴더는 `_backup` 이동.

## 7. DATASET_CREATE 변경(DH-10)

- params 추가: `exclude_files: list[str] = []`(입력 루트 기준, `\`→`/` 정규화, 최대 `dataset.max_exclude`(5000)), `health_job_id: str | None`.
- 사전조건: `health_job_id`가 있으면 같은 Study·`DATA_HEALTH`·SUCCEEDED·`result.input_path`가 이번 입력 경로와 같음, 아니면 422 `DH_INPUT_MISMATCH`("데이터 점검 대상과 데이터셋 입력 폴더가 다릅니다"). `exclude_files`는 점검 없이도 허용(사용자 판단).
- DS_SCAN: 수집 후 `exclude_files` 정확 일치 제거 → 남은 수로 `min_h3d_files`·분할 검사(기존 문구). 목록에 있으나 수집되지 않은 항목 → 경고 `DS_EXCLUDE_NOT_FOUND`(개수·앞 10개). 전부 제외 → `INPUT_INVALID` "제외 후 대상 h3d가 없습니다"(② 문구와 같음).
- 산출: `03_dataset/<id>/excluded.json` = `{health_job_id, files:[{file_rel, recommended, score, reason_codes}]}`(점검 결과에 없는 파일은 `recommended:null`), `split.json`에 `excluded`(목록) 추가, `datasets.excluded_count`·`health_job_id` 기록. `DS_REGISTER` result에 `excluded_count`.
- 점검 작업은 데이터셋·입력 파일을 바꾸지 않는다(자동 제외 없음).

## 8. API(`backend/openapi.json` — Backend)

| 메서드·경로 | 내용 | 권한 |
|---|---|---|
| `POST /studies/{sid}/jobs` `job_type=DATA_HEALTH` | params `{input_path?|curation_id?, responses?: [name], attrs?: bool(기본 true)}` — input 규칙은 DATASET_CREATE와 같음(둘 중 하나). 응답 기존 `Job` | 기존(power 이상 + CSRF) |
| `GET /jobs/{job_id}/data-health` | `report.json` 내용(`DataHealthReport` 스키마). 작업이 DATA_HEALTH 아님 404, 미완료 409 `REPORT_NOT_READY`(기존 코드 재사용), 파일 없음 404 `REPORT_MISSING` | Study 조회 권한. `x-mcp.exclude`(DH-13) |
| `GET /jobs?study_id=&job_type=DATA_HEALTH&limit=1` | 최근 점검(기존 API) | 기존 |
| `Dataset` 스키마 | `excluded_count: int`, `health_job_id: str|null` 추가 | – |
| `DatasetCreateParams` | `exclude_files`, `health_job_id` 추가 | – |

내려받기는 기존 artifact 경로(`DATA_HEALTH_CSV`).

## 9. 화면(Impl-Frontend)

원칙: 필수 UI만, 2560×1440 한 화면(스크롤은 표 내부만), 라이트 테마, 한국어.

- `DatasetCreateCard`(③-1) 아래 줄: **[데이터 점검]** 버튼(현재 입력 기준으로 DATA_HEALTH 실행, 기능 게이트·권한 같음) + 상태 한 줄("최근 점검 11-03 14:20 · 추천 3 / 120"). 입력을 바꾸면 이전 점검은 "다른 입력" 표시, 제외 선택 초기화.
- 결과 카드 `DataHealthCard`(span 12, ③-1 아래):
  - 머리 한 줄: run 수 · 추천 수 · 3σ만 수 · 건전성 FAIL 수 · NA 많은 지표 · 임계값(견고 z 3.5 / kNN 3.5 / 3σ 3.0, 읽기 전용) · 경고 배지(`DH_RESP_NOT_EXTRACTED`·`DH_NO_DOE_LINK`·`DH_PARAMS_MIXED`).
  - 표(최대 높이 고정·내부 스크롤, 기본 필터 [추천만] 켬): `선택 | run(file_rel, run_key) | 추천 | 점수 | 사유(첫 2개 + "외 n") | 종료 | 에너지 오차% | 추가 질량 | 최대 견고 z(지표) | 3σ` . 행 펼치면 지표 전부(값·z·견고 z·kNN 점수·NA 사유).
  - 동작: [추천 항목 선택], [선택 해제], [CSV 내려받기]. **기본 선택 없음**. 하단 "제외 n개 — 데이터셋 생성에 반영" 문구.
- 데이터셋 생성 제출 시 선택된 `exclude_files`와 `health_job_id`를 params에 넣는다. 데이터셋 목록 행에 "제외 n" 표시.
- 문구는 한국어, 코드값은 툴팁으로만.

## 10. 설정(`config/platform.example.yaml` — Backend)

```yaml
data_health:
  min_n: 8                    # Z·견고 z 최소 유효 표본
  knn_min_n: 12
  knn_k: 5
  sigma_z: 3.0                # 일반 3σ(표시만)
  robust_z: 3.5               # 판정(Iglewicz–Hoaglin 수정 z 권장값)
  knn_z: 3.5                  # 판정
  energy_error_pct_max: 10.0
  added_mass_ratio_max: 0.05
  hourglass_ratio_max: 0.10
  contact_ratio_max: 0.10
  zero_tol: 1.0e-12
  engine_out_glob: "*_0001.out"
  starter_out_glob: ["*_0000.out", "*_0000.sty"]
  out_tail_bytes: 262144
  starter_scan_max_bytes: 67108864
  normal_regex: "NORMAL TERMINATION"
  error_regex: "ERROR TERMINATION"
  cycle_regex: "…"            # 이름 그룹 err, mas (Backend가 픽스처로 확정)
  t01_series: null            # {internal, hourglass, contact} — 현장 확인 전 null(= NA)
  report_max_rows: 2000
dataset:
  max_exclude: 5000
```

검증(validate): 임계값 > 0, `min_n ≥ 3`, `knn_min_n > knn_k ≥ 1`, 정규식 컴파일.

## 11. 시험(V-DH-*)

| ID | 내용 | 종류 |
|---|---|---|
| V-DH-1 | 통계: 일반 z(ddof=1)·견고 z, MAD=0 → MeanAD 대체, 전부 같은 값 zr=0, NaN·None 제외, n<8 `SKIP_SMALL_N` | 단위 |
| V-DH-2 | kNN: 매끈한 함수 + 스파이크 1개 → 그 run만 `KNN_JUMP`, 바닥 닿음형 급변(국소 계단)은 오판 없음, k 조정(n−1), 동률 정렬, snapshot 정규화, 혼합 파라미터 생략, n<12 생략 | 단위 |
| V-DH-3 | engine out 꼬리: NORMAL/ERROR/없음(UNKNOWN), 마지막 사이클 줄 err·mas, 파일 > 꼬리 상한에서 읽은 바이트 ≤ `out_tail_bytes`, 0개·2개 NA, 정규식 설정값 사용 | 단위 |
| V-DH-4 | starter 총질량: 첫 일치에서 중단, 상한 초과 NA, equiv `starter_mass` 회귀 결과 불변 | 단위·회귀 |
| V-DH-5 | 모델 속성: 알려진 사면체·육면체 메시의 bbox·부피·CoG, 조립 매칭 run(mesh_tree + parts), include 없음 NA, 쉘만 `NO_SOLID`, 캐시 서명 일치 시 재파싱 0회 | 단위 |
| V-DH-6 | run 해석: 큐레이션 file_list run_key, `results/<doe>` 직접, `results/` 전체(DOE 2개), 외부 폴더 제한 모드 + `DH_NO_DOE_LINK`, 엔진 혼합 422 | 워커 |
| V-DH-7 | 응답: spec 일치 시 재사용, 불일치·없음 NA + `DH_RESP_NOT_EXTRACTED`, CURVE 제외, **외부 도구 실행 0회**(가짜 도구 호출 기록) | 워커 |
| V-DH-8 | 판정: 견고 기준만 추천, "3σ만"은 비추천, ① FAIL 추천, score 정렬, 사유 한국어·코드, hg/접촉 비는 곡선 JSON + `t01_series` 있을 때만 | 워커 |
| V-DH-9 | 작업: step 4개 INTERNAL, CPU 대기열 시작, 진행률·취소(run 경계), 재시도 `_backup`, Study 활성 1개 409 `DATA_HEALTH_ACTIVE`, 기능 게이트 | 워커·API |
| V-DH-10 | DATASET_CREATE: `exclude_files` 제거 후 분할, 없는 항목 경고, 전부 제외 실패, 제외 후 `min_h3d_files`, `health_job_id` 입력 불일치 422, `excluded.json`·`split.json.excluded`·`excluded_count`, 점검 작업이 데이터셋을 바꾸지 않음 | 워커·API |
| V-DH-11 | API: `/jobs/{id}/data-health` 권한·404·409, 크기 상한 시 `truncated`, OpenAPI `x-mcp.exclude`, `MCP_JOB_EXCLUDED`·용어집 정적 시험 통과 | API·정적 |
| V-DH-12 | 저장: `jobs.result`에 run별 값 없음(키 집합 검사), 파일 위치 `03_dataset/_health/<job_id>/`, DS_SCAN이 `_health`를 수집하지 않음 | 워커 |
| V-DH-13 | migration 0026 up/down(기존 datasets 행 excluded_count=0) | migration |
| V-DH-14 | 화면(jsdom): 버튼·표·[추천만] 필터·**기본 선택 없음**·[추천 항목 선택]·제출 params에 `exclude_files`·`health_job_id`, 입력 변경 시 선택 초기화, 한국어 문구, 표 최대 높이(1440 한 화면) | 프런트 |
| V-DH-15 | 성능 기록(비차단): 합성 run 300개 × include 5 MB에서 DH_SCAN 시간·캐시 재실행 시간 RELEASES에 기록 | 측정 |

## 12. 파일 소유(겹침 없음)

| 역할 | 범위 |
|---|---|
| Impl-Backend | 신규 `backend/physicsai_core/data_health/{__init__,metrics,stats,knn,attrs,sources,report}.py`, 신규 `backend/physicsai_core/parsers/radioss_out.py`(꼬리·사이클 줄·starter 총질량), `equiv/compute.py`(총질량을 공용 함수 호출로 — 동작 불변), `job_types.py`, `features.py`, `config/schema*.py`·`validate_stages.py`, `config/platform.example.yaml`, 워커 신규 `worker/physicsai_worker/steps/stage3_model/data_health.py` + 등록, `steps/stage3_model/dataset.py`(DS_SCAN 제외·excluded.json), `services/job_params/stage3_model.py`, 라우터·서비스·스키마(`Dataset`·`DataHealthReport`), `datasets` repository, `backend/openapi.json`, MCP 제외 목록·용어집, `migrations/versions/0026_data_health.py`, 시험 V-DH-1~13·15, `RELEASES.md`·`pyproject.toml` 0.2.16 |
| Impl-Frontend | `frontend/src/stages/stage3/DatasetCards.tsx`(버튼·제외 반영·목록 "제외 n"), 신규 `frontend/src/stages/stage3/health/{DataHealthCard.tsx,healthModel.ts}`, `api` 클라이언트·타입, mock(`mock/stage3.ts`·`server.ts`·`catalog.ts`), 시험 V-DH-14, `frontend-dist/` |
| 순서 | 계약 확정 → BE(openapi 포함) → FE → Verifier(V-DH-1~15) |

## 13. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| Radioss 출력 형식 차이(버전·MPI 분할 `_0001.out` 여러 개) | 판정 UNKNOWN 남발 | 정규식 설정, 2개 이상은 NA(FAIL 아님), 현장 픽스처로 Backend 확정 |
| 응답 미추출이 흔함(①-6 기본 비활성) | ②③이 속성만으로 축소 | 경고·안내 문구, 속성·건전성만으로도 동작 |
| 다중 비교 거짓 양성(지표 ~15개 × run) | 정상 run 추천 | 견고 z 3.5·kNN 3.5, 추천만(사람 확인), 사유 표시 |
| 소표본·고차원 DOE에서 kNN 둔감 | 튐 놓침 | 이웃 거리 표시, n·p 규칙, 견고 z와 병행 |
| 쉘 쿠션(shell-morph) | 부피·CoG NA | `NO_SOLID` 경고, 쉘 요소 bbox/CoG는 후속 |
| 총질량이 제품 포함 전체 | 쿠션 변화 희석 | 라벨 "모델 총질량(starter)", 쿠션 부피가 주 지표 |
| include 파싱 시간(공유 드라이브) | 점검 수 분 | 비동기·진행률·서명 캐시, V-DH-15 측정 |
| 정상 범위 비선형 응답(바닥 닿음 등)이 견고 z 꼬리로 보임 | 오추천 | kNN 사유와 함께 보여 사용자 판단, 자동 제외 없음 |

## 14. 미결

- U-DH-1: ① 임계 기본값(에너지 오차 10%, 추가 질량 0.05, hg/접촉 0.10)의 사내 기준 — 현장 확인 전 기본값 사용.
- U-DH-2: 견고 판정 임계 3.5(문헌 권장) vs 3.0(Altair 3σ와 수치 맞춤) — 기본 3.5, 설정 한 줄로 변경.
- U-DH-3: `t01_series` 실제 series 이름(②-4 곡선 JSON 형식 U27 미확인) — 확인 전 null(hg/접촉 비 NA).
- U-DH-4: 일반 z의 σ를 Altair GUI가 모집단(ddof=0)으로 쓰는지 — 기본 ddof=1, 확인되면 맞춤(n ≥ 8에서 차이 ≤ 7%).
- U-DH-5: 필드 PCA(DH-12) 착수 시점·입력(② 큐레이션 h3d 필드 선택).

## 변경 메모

- (없음)
