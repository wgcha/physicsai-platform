# 계약: 결과 컨투어 기본 표시 = 3D 뷰어 · 변수표와 컨투어 1:1 배치 (④⑤⑥)

> 상태: **확정**(2026-10-22, 사용자 결정 Q1~Q3). 릴리스 **v0.2.9**. 기준: def0517(v0.2.8), migration HEAD `0021_uploads`. 이 계약은 migration 없음. 단 C3D-13(CPU 대기열 이동)은 v0.2.9 대기열 분리([job-queues.md](job-queues.md), `0022_job_queues`, 다른 브랜치)가 병합된 뒤 통합 단계에서 적용한다.
> 상위: [geometry-view.md](geometry-view.md) §13(결과 3D 컨투어 — `POST /contour3d`·`CONTOUR_3D`·`ContourViewer`), phase3 §15(컨투어 PNG·영상 캡처)·§18 D3-61(⑥ 마무리 배치·같은 범례)·§19(⑤ 결과분석)·§21.3.11(FEM 검증 컨투어 탭), [upload-report.md](upload-report.md) §9(HTML 보고서). 충돌 시 이 문서 우선(④⑤⑥ 결과 컨투어 표시·배치 한정). geometry-view §13.6 "진입"(그림/영상 옆 3D 탭·버튼)은 ④⑤⑥에서 이 문서로 대체되고, ① run 표(GV-C3)는 그대로다.
> ID 규칙: 결정 `C3D-n`, 시험 `V-C3D-n`, 변경 메모 `C3D-Cn`.

## 0. 한 줄 요약

④ 예측·⑤ 결과분석·⑥ 최적화에서 결과 컨투어 자리의 기본을 PNG·영상에서 **3D 컨투어 뷰어**로 바꾼다. PNG·영상은 없애지 않고 **[그림/영상] 창**(대화상자)에서 보고·받고·다시 캡처한다(보고서는 계속 PNG). WebGL 불가·기능 꺼짐·3D 실패 때는 지금처럼 PNG·영상이 그 자리에 바로 나온다. 변수표 카드와 결과 컨투어 카드는 **같은 줄 1:1**(2560×1440 기준 각 약 1,180 px)로 놓아 컨투어 보기를 키운다. 3D는 계속 "열 때 생성"이고, **컨투어 칸이 화면에 보이는 것 = 여는 것**으로 본다(해석·예측 완료 시 자동 생성은 여전히 없음).

## 1. 현재 위치(def0517 코드 확인)

| 화면 | 변수표 카드(12열 기준 폭) | 결과 컨투어 | 3D |
|---|---|---|---|
| ④ 단일 예측 `PredictWorkspace` | 템플릿 `c6`→8칸 + 진행 `c3`→4칸 | 아래 결과 카드(12칸) 안 `.result-grid` 왼쪽 = `ContourMedia`(PNG·영상) | `ContourPanel` 버튼(접힘, 열면 생성)이 PNG 아래 |
| ④ 준비된 입력 `PreparedPredictCard` · 실행 결과 `PredictRunView` | 입력 카드 12칸 | 같은 `PredictResultCard` | 같음 |
| ④ 일괄 결과 `BatchResult` | 결과 표 `c6`→8칸 | `BatchRunPanel`(DOE #n) `c3`→**4칸**에 `ContourMedia` | **없음** |
| ④ FEM 검증 `VerifyDetail` 컨투어 탭 | – | `ContourCompare`(예측 \| FEM PNG 두 열) | FEM 쪽만 `ContourPanel` 버튼 |
| ⑤ 결과분석 `StageAnalysis` | 결과 표 `AnalysisTable` `c6`→8칸 | **컨투어 자리 없음** — 오른쪽 `c3`→4칸 = 응답 그래프 탭 카드 | 없음 |
| ⑥ 내장 최적화 `SurrogateResult` | 최적안—기준안 대비 표 `c8`→8칸 + 결과 요약 4칸 | 아래 `ContourCompareCard`(12칸, 기준안·최적안 `ContourMedia` 두 열, D3-61 같은 범례) | 없음 |
| ⑥ HyperStudy 레거시 `OptResult` | – | 컨투어 없음(예측 h3d 없음) | 없음 |

- 12열 격자 `design/grid.css`: 작업 영역(`.workgrid`)은 ≥1280에서 `c9→12`, `c6→8`, `c3→4`로 환산하므로 지금은 **6칸(절반)을 만들 클래스가 없다**. 1280 미만은 6열(대부분 전체 폭).
- ⑥ FINAL(D3-61): 기준안·최적안 `final.baseline.job_id`·`final.best.job_id` = 하위 **PREDICT** 작업 → `PREDICT_H3D {job_id}`로 그대로 3D 원본이 된다(API 변경 없음). 단 워커 `surrogate_final._final_plan`은 **컨투어 캡처 미구성이면 FINAL 배치를 만들지 않는다**(SKIPPED) — 이때는 3D 원본도 없다(§6.2).
- `POST /contour3d`는 h3d 확인 뒤 곧바로 `require_power` → 읽기 사용자(member)는 캐시가 있어도 3D를 못 본다. 사용자별 동시 생성 상한 `geometry.view.max_queued_per_user`(기본 2, 넘으면 429 `PREVIEW_BUSY`). `CONTOUR_3D`는 **LIGHT 레인(동시 1, 환경 점검·다시 캡처와 공유)**이고 job-queues JQ-8·JQ-11은 LIGHT를 그대로 둔다(CPU 레인 아님).
- ⑤ DOE 결과 표(`GET /train-does/{id}/result-table`) 행에는 h3d 경로가 없다. `GET /train-does/{id}/runs`의 `TrainRun.h3d_rel`(GV-C3)이 있다. 일괄 배치 행은 `job_id`가 있다.

## 2. 결정 요약(C3D-1~C3D-12)

| ID | 결정 | 근거 |
|---|---|---|
| C3D-1 | ④⑤⑥ 결과 컨투어 자리의 **기본 = 3D 뷰어**(`ContourViewer`). PNG·영상은 같은 카드 머리의 **[그림/영상]** 버튼 → 대화상자(§4) | 사용자 요청 |
| C3D-2 | **폴백**: `features.contour3d=false`·WebGL 불가 → 지금처럼 PNG·영상이 그 자리에 인라인(버튼 없음, 요청 없음). 3D 결과 FAIL·작업 실패 → 사유 한 줄 + PNG·영상 인라인 + [다시](인프라 실패만) | geometry-view §7.4·§13.6 기존 규칙 유지 |
| C3D-3 | **생성 정책 A(확정 Q1)**: 3D 칸이 **뷰포트에 처음 들어올 때** 그 원본으로 `POST /contour3d` 1회(캐시 적중이면 즉시 표시). 해석·예측·FINAL 완료 시 서버 자동 생성은 **하지 않는다**(2026-10-20 "열 때 생성" 유지 — 기본 표시가 되었으므로 "칸이 보임 = 엶") | §5 비교 |
| C3D-4 | ④ 일괄·⑤ 행 선택은 **0.8 s 머무름** 뒤 요청(키보드로 훑을 때 요청 폭주 방지). 이전 행 요청은 자동 취소하지 않는다(캐시 행은 사용자 간 공유 — 남의 요청을 끊지 않음, 취소는 대기 화면 [취소]) | 부하·공유 캐시 |
| C3D-5 | 429 `PREVIEW_BUSY`면 "앞선 3D 생성이 끝나면 이어서 요청합니다" + 칸이 보이는 동안 3 s마다 재요청. 대기 화면·실패 화면에도 [그림/영상] 버튼(PNG는 바로 볼 수 있게) | 첫 생성 대기(수 분) 동안 공백 방지 |
| C3D-6 | **읽기 사용자**: `POST /contour3d`의 캐시 적중은 로그인(member) 허용, 미적중일 때만 power 필요(403 `PERMISSION_DENIED`, 작업 생성 없음). member는 적중 → 3D, 403 → PNG 인라인 + "3D는 실행 권한이 있는 사용자가 한 번 열면 볼 수 있습니다" | 결과 화면은 member도 봄. 적중은 새 작업 없음 |
| C3D-7 | **비교 모드**(⑥ 기준안·최적안, ④ FEM 검증 예측·FEM): 뷰어 2개 나란히 + 시점 연결(기본 켬) + 공통 범례 1개 + 공용 시간 슬라이더·재생·변형 배율(§3.3) | 사용자 요청(⑥ 나란히) |
| C3D-8 | 공통 범례 = 두 manifest `range`의 합집합 `[min(a,b), max(a,b)]`(실제 필드 범위). 조건: 두 `display`(field·comp·avgmode)와 `unit`이 같음, 아니면 개별 + "결과 종류가 달라 범례를 따로 씁니다". D3-61 `final.legend`(목적값 기반, PNG용)는 3D에 쓰지 않는다 | 3D는 만든 뒤 실제 범위를 알 수 있음(D3-61 보강이 못 하던 것) |
| C3D-9 | **1:1 배치**: 같은 줄의 변수표 카드와 결과 컨투어 카드는 각각 새 격자 클래스 `c-half`(≥1280 12열 중 6칸, <1280 6열 전체 = 세로 쌓기, 순서 변수표 → 컨투어). 3D 보기 높이 `--c3d-h: clamp(420px, calc(100vh - 320px), 960px)`, 같은 줄 변수표는 이 높이를 넘으면 내부 스크롤(머리글 고정) | 사용자 요청, 기준 2560×1440 라이트 |
| C3D-10 | **⑤ 결과분석 컨투어 자리 신설(확정 Q2)**: 결과 표 옆 **별도 "결과 컨투어" 카드**(선택 행 = 기존 `selected`), 결과 표 : 결과 컨투어 = 1:1(`c-half`), 응답 그래프 카드는 그 아래 줄(12칸)로 내린다. 요청은 C3D-3·4 그대로(카드가 보일 때, 행 선택은 0.8 s 머문 뒤) | 사용자 결정 — ④⑥과 같은 배치 원칙(변수표 \| 컨투어 1:1) |
| C3D-13 | **`CONTOUR_3D`를 LIGHT 레인에서 v0.2.9 CPU 대기열로 이동(확정 Q3)**: C3_* step 전부 CPU 구간(동시 `worker.queues.cpu.max_concurrent` 기본 4 + 여유 메모리 문). 환경 점검·`CONTOUR_RECAPTURE`는 LIGHT 유지. job-queues 병합 후 통합 단계에서 적용(§6.4) | 사용자 결정 — 자동 요청이 LIGHT 동시 1을 막는 문제(R1) 해소 |
| C3D-11 | ⑥ FINAL: 캡처 미구성이어도 `contour3d` 사용 가능하면 **캡처 없이** FINAL 배치(기준안·최적안 2행 예측)를 등록 → 3D 비교 원본 확보. 다중 baseline·대리모델만 모드는 지금처럼 SKIPPED | 3D 기본인데 원본이 없는 경우 제거(예측 2회 추가) |
| C3D-12 | **보고서 영향 없음**: HTML 보고서(report_html)는 계속 PNG(마무리 캡처·FEM 캡처) data URI. 3D 산출물(`_cache/contour3d`)은 보고서에 넣지 않는다. migration·새 job_type·새 설정 키 없음 | upload-report §9 "3D는 정적 이미지만" 유지 |

## 3. 화면별 규칙(Impl-Frontend)

### 3.1 공통 부품

| 부품 | 역할 |
|---|---|
| `ContourSlot`(신규) | 입력 `{source: Contour3dCreate \| null, media: ReactNode}`. C3D-2 판정 → 3D(`ContourBody`, 자동 요청 C3D-3~5) 또는 `media` 인라인. 카드 머리 aside용 [그림/영상] 버튼을 함께 낸다(3D일 때만) |
| `ContourCompare3D`(신규) | 입력 `{left:{label, source}, right:{label, source}, media}`. 두 `useContour3d` + 두 뷰어 + 공용 조작(§3.3) |
| `MediaDialog`(신규) | [그림/영상] 대화상자. 본문 = 지금 인라인으로 쓰던 PNG 부품 그대로(`ContourMedia` / `ContourCompare` / 두 `ContourMedia`). 폭 `min(1400px, 92vw)`, Esc·닫기, 열 때 첫 버튼 포커스·닫으면 원래 버튼으로 복귀 |
| `ContourViewer`(수정) | 제어 모드 props(선택): `frame`(외부 지정 프레임), `legend`(외부 범례 `[min,max]`), `scale`, `camera`·`onCamera`. 없으면 지금처럼 단독 동작. 비교 모드에서는 내부 슬라이더·범례·배율 줄을 숨긴다 |
| `ContourSceneApi`(수정, `threeScene.ts`) | `getCamera()`·`setCamera(state)`·`onCameraChange(cb)`·`fitBox(box)` 추가(state = position·target·up·zoom). 새 three 모듈 없음(§7.1 허용 목록 불변) |
| `useContour3d`(수정) | `auto`(뷰포트 진입 시 1회, IntersectionObserver threshold 0), 머무름 지연, 429 재요청, 403(member 미적중) 상태 노출 |

- 3D 칸 이름: "결과 컨투어"(카드 제목). 버튼 문구: "그림/영상". 그 밖 새 문구는 C3D-2·5·6·8의 한 줄씩만.
- 같은 화면에서 3D 뷰어 수 ≤ 2(WebGL 컨텍스트·GPU 메모리). 카드가 언마운트·접히면 `dispose()`.

### 3.2 화면별

| 화면 | 배치(≥1280, 12열) | 3D 원본 | [그림/영상] 창 본문 |
|---|---|---|---|
| ④ 단일 예측 | 1줄: [템플릿(변수표) `c-half`] [결과 컨투어 `c-half`]. 2줄: [결과 12칸] = 결과 머리·입력 경로·[커브 \| 응답값] 1:1·결과 목록 트리·입력파일 받기. **진행 카드는 결과 컨투어 카드로 합친다**: 예측 성공 전에는 그 자리에 기존 진행 단계(`PredictSteps`/`PredictChain`), 성공 후 3D(진행 단계는 카드 아래 접힌 "진행" 한 줄) | `PREDICT_H3D {job_id}` | `ContourMedia`(방향·영상·받기·다시 캡처) |
| ④ 준비된 입력·실행 결과 | [입력 카드 `c-half`] [결과 컨투어 `c-half`] → [결과 12칸] (같은 분리: `PredictContourCard` + 컨투어를 뺀 `PredictResultCard`) | 같음 | 같음 |
| ④ 일괄 결과 | [결과 표 `c-half`] [DOE #n `c-half`: 3D + 결과 목록 트리 + 버튼 줄]. "결과분석" 카드는 없애고 "⑤ 결과분석에서 열기"를 결과 표 카드 aside 링크로 | 선택 행 `PREDICT_H3D {row.job_id}`(C3D-4 머무름) | `ContourMedia`(방향은 지금처럼 행을 바꿔도 유지) |
| ④ FEM 검증 컨투어 탭 | 카드 12칸 그대로(옆 변수표 없음), 탭 안 `ContourCompare3D` | 왼쪽 예측 `PREDICT_H3D {fv.links.predict_job_id}`(null이면 FEM 단독 뷰어 1개), 오른쪽 FEM `SOLVER_H3D {fem_verification_id}` | `ContourCompare`(기존 PNG 두 열·범례 한 줄) |
| ⑤ 결과분석(결과 표 탭) | 1줄: [결과 표 `c-half`] [결과 컨투어 `c-half`(별도 카드)]. 2줄: [응답 그래프 12칸, 탭 = 변수–응답·설계공간 지도·영향도·커브(기존 그대로)]. 비교 출처가 있어도 컨투어는 기본 출처의 선택 행 하나 | 일괄: `PREDICT_H3D {row.job_id}`(어댑터 `fromBatch`가 `RtRow.job_id` 선택 필드를 채움). DOE: `SOLVER_H3D {study_id, h3d_rel}` — `h3d_rel`은 `GET /train-does/{id}/runs`를 페이지(≤200)로 끝까지 읽어 `run_key→h3d_rel` 맵(DOE마다 1회, 화면 메모리). `h3d_rel` null·행 실패 → "이 run은 결과 h3d가 없습니다" | 일괄: `ContourMedia`. DOE: PNG 없음 → 버튼 숨김 |
| ⑥ 내장 최적화(EGO·GA·NSGA-II, 단일·다목적) | 결과 요약 → 12칸 한 줄(타일 가로 배치). 다음 줄: [최적안—기준안 대비(변수표) `c-half`] [컨투어 비교 `c-half` = `ContourCompare3D` 기준안 \| 최적안(다목적은 "추천점")]. aside = 범례 문구(C3D-8) + [그림/영상] + FEM 검증 버튼(기존) | `final.baseline.job_id`·`final.best.job_id` → `PREDICT_H3D` | 기존 두 `ContourMedia`(같은 범례 D3-61·방향 공유) |
| ⑥ HyperStudy 레거시 | **변경 없음**(예측 h3d·컨투어 자리 없음) | – | – |

- ⑥ `final.status`가 DONE이 아니면 지금 문구 그대로(PENDING 진행 문구·SKIPPED 사유). C3D-11로 캡처 없이 만든 FINAL은 3D만 보이고 [그림/영상] 창은 기존 "캡처 없음" 문구.
- ① run 표 3D 버튼(GV-C3)·형상 뷰(§7.2 `gv-split`)는 **바꾸지 않는다**.

### 3.3 비교 모드

| 항목 | 규칙 |
|---|---|
| 배치 | 카드 안 2열(각 `minmax(0,1fr)`), 각 뷰어 `aspect-ratio: 1/1`·`max-height: var(--c3d-h)`, 열 머리 = 라벨 + 목적 값·변수 요약(⑥ 기존 `so-contour-head` 내용). 카드 폭 < 900 px면 세로 쌓기 |
| 생성 | 두 원본을 동시에 요청(사용자 상한 2와 맞음). 한쪽만 준비되면 그쪽부터 표시, 다른 쪽은 대기 화면 |
| 시점 연결 | 체크 "시점 연결"(기본 켬). 한쪽 OrbitControls 변경 → 다른 쪽 `setCamera`(재귀 방지 플래그). 처음 맞춤 = 두 메시 bbox 합집합으로 같은 카메라 |
| 범례 | 세그먼트 [공통 \| 개별], 기본 공통(C3D-8). 범례 막대는 공통일 때 1개(두 뷰어 아래), 개별일 때 각자. 프레임별 범례는 비교 모드에서 쓰지 않음 |
| 시간 | 공용 슬라이더·재생·이전/다음. 두 `frames.count`가 같고 각 `time` 차 ≤ 1e-9·max(\|t\|)이면 같은 인덱스, 아니면 왼쪽 프레임 시간에 가장 가까운 오른쪽 프레임(순수 함수 `pairFrame`) |
| 변형 배율 | 공용(둘 중 `has_disp`인 쪽에만 적용) |

## 4. [그림/영상] 창

- 3D 칸이 기본일 때만 버튼이 있다(폴백 화면은 PNG가 이미 인라인). 대기·실패 화면에서도 보인다(C3D-5).
- 내용은 기존 부품 그대로: 방향 선택, 이미지/영상 토글, 이미지·영상 받기, 다시 캡처(power, 기존 `CaptureRequest`). 새 API 없음.
- 보고서용 그림은 지금처럼 HTML 보고서 버튼(⑤⑥) 또는 이 창의 "받기"로 얻는다.

## 5. 생성 요청 정책 — 대안 비교

| 안 | 동작 | 장점 | 단점 | 판정 |
|---|---|---|---|---|
| **A. 칸이 보이면 자동 요청** | 뷰포트 진입 1회 + 머무름 0.8 s(행 선택) + 429 재요청 | 기본 표시 요구와 일치, 캐시 적중은 즉시. 서버 변경 거의 없음 | 첫 생성 수 분 대기(그동안 [그림/영상]), 행을 많이 훑으면 CPU 대기열·hw 라이선스 사용 증가 | **채택(Q1)** |
| B. 버튼 1회 | 칸에는 안내 + [3D 만들기], 캐시 있으면 바로 3D | 부하 최소 | 매번 클릭, "기본 3D" 체감 약함(지금과 거의 같음) | 기각 |
| C. ⑥ FINAL 완료 시 미리 생성 | 완료 훅이 `CONTOUR_3D` 2건 등록 | ⑥ 첫 진입 즉시 | 2026-10-20 "열 때 생성" 결정의 예외, 안 보는 결과도 생성, 연쇄 금지 규칙(§13.5 "PREDICT·DOE에 연쇄하지 않는다") 위반 | 기각(A로 충분 — ⑥은 2건뿐) |

대기열·캐시 영향(A 기준):

- 레인(C3D-13): `CONTOUR_3D`는 v0.2.9 **CPU 대기열**(동시 기본 4 + 여유 메모리 문)에서 실행한다. 환경 점검·다시 캡처는 LIGHT(동시 1)에 남아 3D 생성과 서로 막지 않는다. CPU 대기열은 원래 순번 FIFO라 ④ 일괄·DOE의 CPU 구간과 순서를 다툰다(R9).
- 부하 상한: 사용자당 동시 2(기존), 같은 원본은 캐시 키로 합쳐짐(중복 작업 없음), 칸이 안 보이면 요청 없음.
- 캐시: 기존 7일·합산 2 GiB. 120k 노드·50 프레임이면 항목당 약 0.1 GiB → 약 20건에서 오래된 것부터 삭제된다. 현장은 `geometry.view.cache.max_total_bytes`를 디스크 여유에 맞게 올리라고 관리자 문서에 안내(기본값은 바꾸지 않음, R2).

## 6. API·백엔드 변경(Impl-Backend, 최소)

### 6.1 `POST /contour3d` 권한 순서(C3D-6)

- 순서: 설정 확인(409) → 원본 확인(404·409) → **캐시 적중(DONE)이면 로그인(member 이상)으로 200** → QUEUED·RUNNING 행이 있으면 member에게도 202(진행 공유, 새 작업 없음) → 그 밖(새 생성)은 power(403 `PERMISSION_DENIED`, `required: "power"`) → 사용자 상한(429).
- `POST /contour3d/{id}/cancel`은 power 그대로. 응답 모양·openapi 스키마 불변(설명 문구만 갱신). x-mcp 표시 변경 없음.

### 6.2 ⑥ FINAL 배치 조건(C3D-11, `worker/.../surrogate_final.py` `_final_plan`)

- 지금: 캡처 미구성 → `SKIPPED`. 변경: 캡처 미구성이고 `contour3d_missing(settings)`의 두 목록이 모두 비어 있으면 `PENDING` + 배치 params `capture.enabled=false`, `legend=None`, `legend_note="컨투어 캡처 미구성 — 3D로만 비교"`. 둘 다 없으면 지금처럼 SKIPPED(사유 그대로).
- 다중 baseline·최적안 없음·대리모델만 모드의 SKIPPED는 그대로. 상태·`final` JSONB 키·종료 훅 불변(migration 없음).

### 6.4 `CONTOUR_3D` CPU 대기열 이동(C3D-13, 통합 단계 — job-queues 병합 후)

- `JOB_TYPES["CONTOUR_3D"]`의 `JobTypeDef.lane`을 `LIGHT` → `SLOT`(job-queues JQ-11: SLOT = 구간 레인). GPU step이 없으므로 `queues.initial_lane` = CPU이고 C3_PREP·C3_REGISTER(INTERNAL)·C3_EXTRACT·C3_CONVERT(LOCAL, hw 배치·변환) 모두 CPU 슬롯 하나로 끝난다(전환 없음). step·가중치·`NO_RETRY_JOB_TYPES`·`notify_success=False`·캐시 규칙 불변.
- **job-queues JQ-8과의 관계**: JQ-8 "LIGHT·PREVIEW 레인은 그대로"의 예외 1건 — `CONTOUR_3D`만 CPU 레인으로 옮기고, 환경 점검·`CONTOUR_RECAPTURE` 등 나머지 LIGHT 종류와 PREVIEW(`GEOM_PREVIEW`)는 그대로다. job-queues §3.2 "추출·캡처 = CPU" 표에 `C3_EXTRACT·C3_CONVERT`가 더해지는 것과 같다. job-queues.md 본문 수정은 그 브랜치와 통합할 때 한다(이 브랜치에는 없음 — 변경 메모 C3D-C1).
- 영향: `jobs.lane` 생성값 CPU, 화면은 CPU 대기열에 "결과 3D 컨투어"로 보임(가벼운 작업 묶음에서 빠짐), MCP `job_kinds.lane_info`는 레지스트리에서 자동 생성(손 변경 없음), `POST /contour3d` 사용자 상한 2·429 불변.
- 순서 주의: job-queues 병합 **전**에 lane을 SLOT으로 바꾸면 전역 슬롯 1개를 쥐게 되므로 금지. 통합 단계에서 job-queues 병합 직후 같은 커밋 묶음으로 적용한다.

### 6.3 변경 없음(명시)

`CONTOUR_3D` 단계·캐시 키·산출물·Range, `result-table` API(⑤ DOE `h3d_rel`은 프런트가 기존 `/train-does/{id}/runs`로 얻음), 보고서(report_html), 캡처(phase3 §15), 설정 키, migration, MCP 도구·`JOB_KINDS`·`SUMMARIES`.

## 7. 시험(V-C3D-n) — `scripts/test-all`(Linux), jsdom은 WebGL 목

| ID | 내용 |
|---|---|
| V-C3D-1 | 기본 표시: 기능 켬·WebGL 목·power → ④ 단일·준비·실행 결과·일괄·⑥에서 결과 컨투어 칸 = 3D(대기 화면/뷰어), PNG 인라인 없음, 카드 aside에 [그림/영상] |
| V-C3D-2 | 폴백: WebGL 불가 또는 `features.contour3d=false` → `ContourMedia` 인라인, [그림/영상] 없음, `POST /contour3d` 0회(기존 PNG 시험 무수정 통과) |
| V-C3D-3 | [그림/영상] 대화상자: 기존 PNG 부품(방향·영상·받기·다시 캡처 power만) 렌더, Esc·닫기·포커스 복귀, ⑥은 두 열 같은 방향 |
| V-C3D-4 | 자동 요청: 칸이 뷰포트에 들어올 때만 1회(IntersectionObserver 목), 다시 마운트 시 200 적중이면 대기 화면 없이 뷰어 |
| V-C3D-5 | 머무름: ④ 일괄·⑤에서 0.8 s 안에 행 3번 바꾸면 마지막 행만 POST, 이전 요청 취소 호출 0회 |
| V-C3D-6 | 429 → 안내 문구 + 3 s 뒤 재요청 → 202 → 뷰어. 대기·실패 화면에 [그림/영상] |
| V-C3D-7 | 백엔드 권한: member 적중 200(작업 0건), member 진행 중 202(작업 추가 0), member 미적중 403 `PERMISSION_DENIED`(작업·행 0건), power 미적중 202. 프런트 member 403 → PNG 인라인 + 안내 한 줄 |
| V-C3D-8 | 비교 순수 함수: 공통 범례 = range 합집합, display·unit 다르면 개별 + 문구, `pairFrame`(같은 개수 = 인덱스, 다르면 최근접 시간), 시점 연결 켬/끔(재귀 없음) |
| V-C3D-9 | ⑥: `final.baseline/best.job_id`로 POST 2건, 다목적 라벨 "추천점", final DONE 아님 → 기존 문구. FEM 검증: 예측·FEM 두 원본, `links.predict_job_id` null → FEM 단독 |
| V-C3D-10 | ⑤ 결과 컨투어 카드: 결과 표 옆 `c-half`, 응답 그래프 카드는 아래 줄 12칸(탭 4개 불변). 일괄 → `PREDICT_H3D {job_id}`, DOE → runs 페이지 순회 맵으로 `SOLVER_H3D {study_id, h3d_rel}`, `h3d_rel` null → 안내, 행 선택 0.8 s 머무름 |
| V-C3D-11 | 배치: ≥1280에서 변수표·컨투어 카드 `c-half`(span 6), <1280 전체 폭·변수표 먼저(CSS 규칙 정적 검사 + 클래스 검사), ④ 일괄 "결과분석" 카드 제거·aside 링크, ④ 단일 진행 카드 없음(진행 단계는 컨투어 카드 안) |
| V-C3D-12 | 워커 FINAL: 캡처 미구성 + contour3d 구성 → FINAL 배치 등록(`capture.enabled=false`, `legend_note`), 둘 다 미구성 → SKIPPED(기존 사유), 다중 baseline·대리모델만 → SKIPPED 불변 |
| V-C3D-13 | 보고서 불변: report_html 골든·시험 무수정 통과(3D 산출물 참조 0) |
| V-C3D-14 | 3D 실패 폴백: 결과 FAIL(`CONTOUR3D_TOO_LARGE`) → 사유 + PNG 인라인([다시] 없음), 작업 FAILED → 사유 + [다시] + PNG 인라인 |
| V-C3D-15 | 불변: ⑥ HyperStudy 레거시 화면·① run 표 3D 버튼·형상 뷰 `gv-split` 시험 무수정 통과, 빌드본 외부 URL 0(GV-C3) |
| V-C3D-17 | 레인(통합 단계): `CONTOUR_3D` 생성 시 `jobs.lane = CPU`, CPU 동시 상한·메모리 문 적용, 실행 중 LIGHT 작업(환경 점검)이 있어도 3D 수령, 3D 실행 중에도 LIGHT 수령, 전환(T17) 0회, job-queues 병합 전 브랜치에서는 LIGHT 유지(lane 시험 분기) |
| V-C3D-16 | 현장(2560×1440 라이트): ④ 단일·일괄, ⑤, ⑥ 화면 캡처로 1:1·3D 기본·[그림/영상] 확인, 첫 생성 소요·캐시 적중 즉시 표시 기록 |

## 8. 구현 분해(소유 비중첩)

| 담당 | 범위 |
|---|---|
| Impl-Backend | §6.1 `services/contour3d_api.py` 권한 순서 + 시험, §6.2 `surrogate_final.py` + `worker/tests/test_surrogate_flow.py`, openapi 설명 갱신. 작음 — 프런트보다 먼저 병합. §6.4 lane 변경(`job_types.py` 한 줄 + V-C3D-17)은 job-queues 병합 후 통합 단계 |
| Impl-Frontend | §3 전부(`ContourSlot`·`ContourCompare3D`·`MediaDialog`, `ContourViewer`·`threeScene`·`useContour3d` 수정, `design/grid.css` `c-half`, ④⑤⑥ 화면 배치), 시험·목, `frontend-dist` 재생성 |
| Plan | 관리자 문서 캐시 용량 안내 한 줄(구현 병합 때) |

순서: BE(권한·FINAL) → FE. v0.2.9 job-queues와 파일 겹침 없음(같은 버전 안 병렬 가능, `frontend-dist`만 FE 순차).

## 9. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | (해소 — C3D-13) LIGHT 동시 1에 자동 요청이 몰려 환경 점검·다시 캡처·3D가 서로 기다림 | `CONTOUR_3D`를 CPU 대기열(동시 4)로 옮겨 LIGHT와 분리. 칸이 보일 때만·머무름·사용자 상한 2·캐시 공유는 유지 |
| R2 | 캐시 2 GiB에서 자주 지워져 재생성 반복 | 관리자 안내로 용량 상향, `last_access_at` 갱신(적중 touch) 유지 |
| R3 | hw 배치 라이선스 사용 증가 | 정책 A의 요청 조건, 필요 시 B로 전환은 프런트 한 곳(`useContour3d.auto`) |
| R4 | 첫 화면이 대기 화면이 됨(지금은 PNG 즉시) | 대기 화면에 [그림/영상], 진행·예상 시간 표시(기존) |
| R5 | 1:1로 변수표가 좁아짐(⑤ 열 많은 결과 표, ⑥ 범위 막대) | 표 내부 가로 스크롤·머리글 고정, 1280 미만은 쌓기 |
| R6 | 비교 모드 뷰어 2개의 GPU·메모리(최대 30만 노드 ×2) | 화면당 뷰어 ≤ 2, 프레임 캐시 8, 언마운트 dispose |
| R7 | 예측 h3d와 FEM h3d의 결과 종류 이름이 달라 공통 범례 불가 | C3D-8 개별 범례 + 문구 |
| R8 | C3D-11로 ⑥ 종료 시 예측 2회 추가(GPU) | 캡처 미구성 현장만, 2행 고정 |
| R9 | CPU 대기열 FIFO라 ④ 일괄·DOE CPU 구간이 많으면 3D 첫 생성이 늦어짐, hw 추출 메모리가 CPU 동시 4에 더해짐 | 대기 화면 진행·예상 시간·[그림/영상], 여유 메모리 문(`cpu.min_free_memory_gb`), 현장 소요 V-C3D-16 기록 후 필요 시 우선순위 별도 결정 |

## 10. 미결(사용자 확인)

| # | 질문 | 임시 결정 |
|---|---|---|
| Q1 | 생성 정책 | **확정(2026-10-22)**: A — 칸이 보이면 자동 요청, 행 선택은 0.8 s 머문 뒤(C3D-3·4) |
| Q2 | ⑤ 결과분석 컨투어 자리 | **확정(2026-10-22)**: 결과 표 옆 별도 카드 1:1(`c-half`), 응답 그래프 카드는 아래 줄(C3D-10) |
| Q3 | `CONTOUR_3D` 레인 | **확정(2026-10-22)**: LIGHT → v0.2.9 CPU 대기열(동시 4), 환경 점검은 LIGHT 유지(C3D-13·§6.4) |

## 변경 메모

(구현 중 계약과 다르게 해야 하면 `C3D-Cn`으로 기록하고 Plan 확인을 받는다.)

- **C3D-C1(2026-10-22, job-queues.md 반영 대기 — 통합 단계)**: job-queues.md(feat/job-queues 브랜치)에 다음을 더한다 — JQ-8에 "예외: `CONTOUR_3D`는 CPU 레인(contour3d-default C3D-13), 환경 점검·`CONTOUR_RECAPTURE` 등 나머지 LIGHT는 유지", §3.2 추출·캡처 행에 `C3_EXTRACT`·`C3_CONVERT`, §3.3 "LIGHT·PREVIEW 종류" 행에서 `CONTOUR_3D` 제외(CPU, 전환 없음). 이 브랜치에는 job-queues.md가 없어 본문을 고치지 않는다.
- **C3D-C2(2026-10-22, v0.2.9 2차 통합 — C3D-C1 반영 완료)**: `job_types.py`의 `CONTOUR_3D` lane SLOT(CPU 대기열)은 job-queues 1차 통합에서 이미 적용돼 있어 이 브랜치의 LIGHT 전제(§2 현황 서술)는 통합본에 해당하지 않는다. job-queues.md JQ-8·§3.2·§3.3과 geometry-view.md §13.5·GV-C4에 반영했고, V-C3D-17은 `backend/tests/test_job_queues_api.py`의 `test_contour3d_runs_in_cpu_queue_not_light`·`test_contour3d_cpu_slot_does_not_block_light_and_has_no_transition`으로 충족한다.
