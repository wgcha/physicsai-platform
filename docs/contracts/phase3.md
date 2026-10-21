# 계약: PhysicsAI 플랫폼 3차

작성: Plan, 2026-10-10. 기준: 브랜치 `claude/phase3`, 커밋 `ad41635`(리팩터링 R0~R11·F1~F4 완료, CI 녹색).
우선순위: **이 문서 > [phase2.md](phase2.md) > [platform.md](platform.md)**. 파일 위치는 [architecture.md](../architecture.md)가 우선(구조 지도·레이어 규칙 §4.2).
사용자 부재 중 작성 — 사용자 확인이 필요한 결정은 "(가정)"으로 표시하고 §9 가정 목록에 모은다.

---

## 0. 기준선

- 1차 변경 메모 B1~B26, 2차 변경 메모 C1~C19·P1, 리팩터링 결과(architecture.md §1)를 3차 기준선으로 본다.
- 1·2차 Verifier 체크리스트(V-*, V2-*) 전체가 회귀 기준(V3-REG-1).

## 1. 한 줄 요약

빠진 UI(작업 재시도·Study 보관/보관 해제·이름 변경)를 채우고(S1), 같은 Study의 모델 2~5개를 loss 곡선·평가 점수로 비교하는 화면을 만들고(S2), Study 폴더 용량을 워커 경량 작업으로 계산해 사용자가 고른 산출물 범주를 `_backup`으로 옮기는 정리 기능을 넣고(S3), HPC 게이트웨이·회수 경로 해석을 의존성 없는 별도 패키지 `simdash_adapters`로 분리한다(S4, 동작 불변).

## 2. 범위

### 2.1 3차 범위

| ID | 항목 | 백엔드 변경 | 프런트 변경 | DB |
|---|---|---|---|---|
| S1 | 작업 재시도 버튼, Study 보관·보관 해제, Study 이름 변경 | 작음(`POST /studies/{id}/unarchive`, `study.json` 제목 갱신) | Study 관리 화면, `JobInline` 재시도 | 없음 |
| S2 | 모델 비교(loss 겹치기·점수 표·메타·Final 연계) | **없음**(기존 API로 충분) | ③-5 카드 확장 | 없음 |
| S3 | Study 용량 계산·정리(`_backup` 이동) | job_type 2개, `GET /studies/{id}/storage`, 설정 키 | Study 관리 화면 용량·정리 | **migration 0004**(`jobs.stage` 0 허용) |
| S4 | 공통 어댑터 패키지 `packages/simdash_adapters` | 이동·얇은 호환층 | 없음 | 없음 |

### 2.2 3차 비범위

- 대시보드 연동(대시보드가 `simdash_adapters`를 쓰는 것 포함), main 병합, 예측 결과 웹 3D 뷰어(2026-10-09 보류 유지).
- `_backup` 비우기(삭제) 기능 — **만들지 않는다**(결정). 사용자가 탐색기에서 직접 삭제한다(§5.9 매뉴얼 문구).
- 산출물 **삭제** API 일체. 정리는 이동만.
- F5(목 서버 분할), H1~H8 보류 항목(architecture.md §1.5, refactor-plan.md §4).
- S3 범주 밖 폴더: `01_train/doe/**`(HyperStudy 작업 폴더), `01_train/results/**`(해석 결과 — ② 원천, `train_runs.result_rel`이 가리킴), `02_import/**`, `03_dataset/**`(평가 psdata 필요), `03_model/models/**`, `04_params/**`, `05_opt/**`. 크기는 표시하지만 정리 대상 범주로는 넣지 않는다(4차 후보, §10 U3-4).

### 2.3 1·2차 계약에서 바뀌는 규칙(이 문서 우선)

| # | 기존 | 3차 |
|---|---|---|
| R3-1 | 1차 §6.6 `jobs.stage` 1~5(`ck_jobs_stage`) | **0~5**. 0 = Study 관리 작업(S3 두 유형). `stage_status`(1차 §10.3, C15)는 1~5만 계속 계산(0은 스텝퍼에 나타나지 않음) |
| R3-2 | 1차 §10.5 보관된 Study는 작업 생성 409 `STUDY_ARCHIVED` | 예외: `STUDY_STORAGE_SCAN`·`STUDY_CLEANUP`은 보관된 Study에서도 생성 가능(가정 A3-3) |
| R3-3 | 1차 §13.1 모든 작업 시작/완료 알림 | `STUDY_STORAGE_SCAN`은 `JOB_STARTED`·`JOB_SUCCEEDED`·`MY_TURN_NEXT` 알림을 만들지 않는다(`JOB_FAILED`만). `JobTypeDef.notify_success=False`(가정 A3-6) |
| R3-4 | 1차 §10.5 작업 생성 사전조건 | Study에 비종료 `STUDY_CLEANUP`이 있으면 **모든** 작업 생성(`STUDY_STORAGE_SCAN` 포함)·재시도와 `PUT /studies/{id}/final-model` 409 `STUDY_CLEANUP_RUNNING`(D3-24) |
| R3-5 | 1차 §10.5 로그 없음 404 `LOG_NOT_FOUND` "로그가 아직 없습니다" | 코드 그대로, **종료된 작업**이면 문구 "로그 파일이 없습니다. Study 정리로 `_backup` 폴더에 옮겨졌을 수 있습니다" |
| R3-6 | B16 input.zip 폴더 없음 409 `INPUT_NOT_READY` "입력 파일 폴더가 없습니다" | 코드 그대로, `RAD_ASSEMBLE` 성공 후 폴더가 없으면 문구 "입력 파일 폴더가 없습니다. Study 정리로 `_backup` 폴더에 옮겨졌을 수 있습니다", `Job.input_display_path`는 폴더가 있을 때만 값 |
| R3-7 | 1차 §6.3 `datasets.package_rel`은 내보내기 후 유지 | S3 정리로 `03_package/<dataset_id>/`를 옮기면 `package_rel=NULL`(→ `package_ready=false`, ③-2 다시 실행 가능) |
| R3-8 | 1차 §12.2 프로토콜 위치 `backend/physicsai_core/hpc/gateway.py` | 정의는 `packages/simdash_adapters/src/simdash_adapters/hpc/`, `physicsai_core.hpc.*`는 재노출 호환층(§6). 모양·동작 불변 |
| R3-9 | 3차 §24 원안(S19 ④ GPU 동시 예측 — 대기열 1번과 같은 배치의 하위 PREDICT를 슬롯 점유 중에도 동반 실행하는 단일 슬롯 FIFO 예외) | **철회(2026-10-20, 사용자 결정, D3-67)**. 예외를 두지 않고 1·2차 단일 슬롯 FIFO 원칙을 그대로 유지한다(④ 일괄 예측 하위 PREDICT는 SLOT 대기열에서 1개씩 실행) |

---

## 3. S1 빠진 UI — 작업 재시도, Study 보관·보관 해제, 이름 변경

### 3.1 현황(코드 확인)

| 기능 | API | 권한·조건(현재 구현) | UI |
|---|---|---|---|
| 작업 재시도 | `POST /jobs/{id}/retry {from_step?}` → `201 Job` (`routers/jobs.py`, `services/jobs.retry_job`) | 본인 작업: power, 남의 작업: 전역 관리자. 상태 `FAILED`·`CANCELED`·`INTERRUPTED`만(아니면 409 `JOB_NOT_RETRYABLE`), Study `ACTIVE`(409 `STUDY_ARCHIVED`), 설정 정상(503 `CONFIG_INVALID`), 같은 유형 활성 작업 있으면 409 `STUDY_JOB_BUSY`. `from_step` 기본 = 첫 실패/취소 step, `TD_SOLVE`·`PREDICT_VERIFY`는 항상 1. `Job.can_retry`가 이미 응답에 있음 | **없음**(`api.retryJob`만 정의) |
| 보관 | `POST /studies/{id}/archive` → `Study` | power, 비종료 작업 있으면 409 `STUDY_HAS_ACTIVE_JOB`, 이미 보관이면 그대로(멱등) | **없음**(목록에 "보관" 글자, Study 화면 경고 상자만) |
| 보관 해제 | 없음 | — | 없음 |
| 이름 변경 | `PATCH /studies/{id} {version, title}` → `Study` (title 1~120자) | power, CAS(409 `VERSION_CONFLICT`). 폴더명은 원래 바뀌지 않음 | **없음** |

### 3.2 API

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `POST /jobs/{id}/retry` | 기존 그대로 | 기존 | 기존 | 기존 + 409 `STUDY_CLEANUP_RUNNING`(R3-4) |
| `POST /studies/{id}/archive` | 기존 그대로 | – | `Study` | 기존 |
| **`POST /studies/{id}/unarchive`**(신규) | power(Study 프로젝트) | 본문 없음 | `200 Study`(`status="ACTIVE"`) | 404 `NOT_FOUND`, 403 `PERMISSION_DENIED`, 409 `STUDY_FOLDER_MISSING`("AI 루트에서 Study 폴더를 찾을 수 없습니다" — `<ai_root>/<folder_name>`이 디렉터리가 아니면). 이미 `ACTIVE`면 그대로 200(멱등, archive와 대칭). 감사 `STUDY_UNARCHIVE` |
| `PATCH /studies/{id}` | 기존 그대로 | 기존 `{version, title}` | `Study` | 기존. **추가 동작**: DB 갱신 뒤 `<study>/study.json`의 `title`을 원자적 재작성(임시 파일 + `os.replace`). 파일 쓰기 실패는 API 실패가 아니다(DB가 정본, 운영 로그 WARNING). 보관된 Study도 이름 변경 허용(가정 A3-1) |

- 라우터 함수 이름: `unarchive_study`(→ operationId `unarchive_study_physicsai_api_studies__study_id__unarchive_post`). 기존 함수 이름은 바꾸지 않는다(architecture.md §0).
- `can_retry` 계산(`services/common.can_retry`)에 Study `ACTIVE` 조건을 **더하지 않는다**(응답 모양 불변). 프런트가 `study.status`로 함께 판단한다.

### 3.3 DB

변경 없음. `studies.status` CHECK(`ACTIVE`·`ARCHIVED`) 그대로.

### 3.4 UI

**Study 관리 화면(신규 라우트)** `/physicsai/p/:projectId/s/:studyId/manage` → `pages/StudyManage.tsx`. 진입: Study 화면 상단(스텝퍼 오른쪽) "Study 관리" 링크, Study 목록 행의 "관리" 링크. 구성(위→아래): ① 기본 정보(이름 변경·폴더 경로·상태), ② 보관, ③ 용량·정리(S3, §5.7). 권한 없는 사용자(`can_execute=false`)는 조회만, 버튼 대신 "조회 전용" 문구.

| 요소 | 위치 | 동작·문구 |
|---|---|---|
| 이름 변경 | 관리 화면 ① | 표시 이름 입력(1~120자) + "저장". 아래 회색 문구 "폴더 이름 `{folder_name}`은 바뀌지 않습니다(표시 이름만 변경)". 409 `VERSION_CONFLICT` → "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요" + 자동 재조회. 확인 대화상자 없음 |
| 보관 | 관리 화면 ②, Study 목록 행 "보관" | 확인 대화상자: 제목 "Study 보관", 본문 "‘{title}’ Study를 보관할까요?\n보관하면 새 작업을 실행할 수 없습니다(조회와 용량 정리는 가능). 파일은 그대로 남고, 나중에 보관 해제할 수 있습니다." 버튼 "보관"(주)·"취소". 409 `STUDY_HAS_ACTIVE_JOB` → 서버 문구 그대로 |
| 보관 해제 | 같은 자리(상태가 `ARCHIVED`일 때) | 확인 대화상자: 제목 "보관 해제", 본문 "‘{title}’ Study를 다시 사용 중으로 바꿀까요? 작업을 다시 실행할 수 있게 됩니다." 버튼 "보관 해제"·"취소". 409 `STUDY_FOLDER_MISSING` → 서버 문구 |
| Study 목록 상태 필터 | `pages/StudyList.tsx` 제목 옆 | 탭 "사용 중"(기본, `status=ACTIVE`)·"보관"·"전체"(가정 A3-2). 선택은 `localStorage`(try/catch) |
| 보관 Study 경고 상자 | `pages/StudyPage.tsx` 기존 | 문구에 링크 추가: "보관된 Study입니다. 실행할 수 없습니다. [보관 해제]"(power만 링크, 관리 화면으로 이동) |
| **재시도** | `components/ui.tsx` `JobInline`(모든 단계 카드·상세가 공유) | `job.can_retry && study.status === "ACTIVE"`일 때 실패 사유 옆 "재시도" 버튼(`btn small`). 확인 대화상자: 제목 "작업 재시도", 본문 "‘{작업 표시명}’을 다시 실행할까요?\n{시작 지점}부터 새 작업으로 대기열에 등록됩니다. 이전 작업 기록은 그대로 남습니다." 시작 지점 = 첫 `FAILED`·`CANCELED`·`PENDING`·`RUNNING` step의 `{step_no}. {label}`, `TD_SOLVE`·`PREDICT_VERIFY`는 "처음(1단계)". 버튼 "재시도"·"취소". 성공 시 새 작업으로 카드 갱신(`useLatestJob`의 재조회 호출), 실패 시 버튼 아래 오류 문구(`errorMessage`) |

- 공용 확인 대화상자 컴포넌트 `components/ConfirmDialog.tsx`(신규): `role="dialog"`, `aria-modal`, 초점 가두기, Esc=취소, 주 버튼 중복 클릭 방지(요청 중 비활성). S1·S3가 같이 쓴다.
- 재시도 버튼은 큐 패널(활성 작업만 표시)에는 두지 않는다.

### 3.5 시험·Verifier

| ID | 기준 | 방법 |
|---|---|---|
| V3-S1-1 | unarchive: power 200·멱등, viewer 403, 폴더 없음 409 `STUDY_FOLDER_MISSING`, 감사 행 `STUDY_UNARCHIVE`, 보관→해제 후 작업 생성 가능 | API(`backend/tests/common/test_study_manage.py`) |
| V3-S1-2 | PATCH title이 `study.json`을 갱신, `study.json` 쓰기 실패(읽기 전용 모의)에도 200·DB 갱신, 보관 Study 이름 변경 200 | API |
| V3-S1-3 | 재시도 버튼 표시 조건(`can_retry`×Study 상태), 확인 대화상자 문구의 시작 지점(일반·`TD_SOLVE`), 성공 시 `POST /jobs/{id}/retry` 1회 호출 후 새 작업 표시, 409 문구 표시 | 프런트(`__tests__/manage.test.tsx` `describe("V3-S1-3 재시도")`) |
| V3-S1-4 | 관리 화면: 이름 변경 저장·VERSION_CONFLICT 문구, 보관/보관 해제 대화상자 문구·호출, 권한 없으면 버튼 없음, 목록 필터 기본 "사용 중" | 프런트 |
| V3-S1-5 | 목(`mock/manage.ts`)에 unarchive 추가, `mockContract.test.ts`가 새 operationId를 포함 | 프런트 |

### 3.6 구현 분해

- **Backend**: `backend/physicsai_api/routers/studies.py`(`unarchive_study` 추가), `services/studies.py`(`unarchive_study`, `patch_study`의 `study.json` 갱신 — 쓰기는 `physicsai_core.fileutil.write_json` 재사용, 원자적이 아니면 임시+`os.replace` 헬퍼 추가), `physicsai_core/db/repositories/studies.py`(변경 없음 예상: `update_cas(status=…)` 재사용), `backend/openapi.json`·`backend/tests/data/operation_ids.txt` 갱신, 시험 `backend/tests/common/test_study_manage.py`(신규).
- **Frontend**: `api/endpoints.ts`(`unarchiveStudy`, `patchStudy`, `archiveStudy` — 없으면 추가), `api/generated/schema.d.ts` 재생성, `app/App.tsx`(라우트 `manage`), `pages/StudyManage.tsx`(신규), `pages/StudyList.tsx`(필터·행 링크·보관 버튼), `pages/StudyPage.tsx`(관리 링크·경고 상자 링크), `components/ConfirmDialog.tsx`(신규), `components/ui.tsx`(`JobInline` 재시도), `mock/manage.ts`(신규) + `mock/server.ts` 위임 1곳, `__tests__/manage.test.tsx`(신규).

---

## 4. S2 모델 비교

### 4.1 데이터 확인 결과(새 API 없음)

| 필요한 값 | 출처(기존) |
|---|---|
| loss 곡선 `[[epoch, loss], …]`(≤ `training_log.max_curve_points`, 첫·마지막·최소점 보존 다운샘플) | DB `models.loss_curve`(JSONB) → `GET /models/{id}`(목록 `GET /studies/{id}/models`는 곡선 제외, `curve_points`만) |
| 평가 점수 `{status, metrics:{name:number}, score_rel}` | `Model.eval_score`, `eval_status` |
| 등록일·epoch 수·최종/최소 loss·로그 상태 | `Model.registered_at`, `epochs_total`, `last_epoch`, `final_loss`, `min_loss`, `min_loss_epoch`, `log_status` |
| 데이터셋 | `Model.dataset_id` → `GET /datasets/{id}`(`h3d_count`, `train_count`, `eval_count`, `seed`, `holdout_ratio`, `created_at`) |
| Final 여부·지정 | `Model.is_final`, `PUT /studies/{id}/final-model` |

결정: **새 API를 만들지 않는다.** 선택 2~5개 × `GET /models/{id}`(이미 `EvaluateCard.useModelDetails`가 같은 방식) + 서로 다른 `dataset_id` 수만큼 `GET /datasets/{id}`. 최대 10요청, 곡선 5×2000점 ≈ 수백 KB로 충분히 작다. 지표의 "좋은 방향"은 서버에 없으므로 프런트 규칙(§4.3)으로 정한다.

### 4.2 API·DB

변경 없음. (향후 Study 모델이 수십 개 이상에서 동시 비교가 필요해지면 `GET /studies/{id}/models/compare?ids=`를 검토 — 지금은 만들지 않음.)

### 4.3 UI — ③-5 "평가 · Final 지정" 카드 확장(`stages/stage3/EvaluateCard.tsx`)

| 요소 | 사양 |
|---|---|
| 선택 열 | 모델 표 첫 열에 체크박스 "비교"(접근성 이름 "{name} v{version} 비교 선택"). `ACTIVE` 모델만(기존 표가 `ARCHIVED` 숨김), `INVALID`는 비활성. 5개 선택 후 나머지는 비활성 + title "최대 5개까지 비교할 수 있습니다" |
| 비교 버튼 | 표 위 오른쪽 "선택 비교 (N)" — N<2면 비활성(title "2개 이상 선택하세요"). 누르면 표 아래 `ModelCompare` 패널(카드 폭 전체), "닫기"로 접음. 선택 해제는 "선택 지우기" 링크 |
| 곡선 겹치기 | 기존 `components/Chart.tsx`(`lines[]`, `logY`) 재사용. x축 "epoch", y축 "loss", **로그 스케일 토글**(기본 켬, 체크박스 "로그 스케일"; 0 이하 값이 있으면 토글 비활성 + 문구 "0 이하 loss가 있어 선형 축으로 표시"). 범례 = `{name} v{version}`(+`label` 있으면 괄호), 색은 모델 순서대로 CSS 변수 `--series-1`~`--series-5`(라이트·다크 대비 확인). 각 곡선의 최소점에 작은 원. 곡선 없는 모델(`curve_points=0`)은 범례에 "곡선 없음(로그 없음/형식 미확인)" 회색 |
| 점수 표 | 행 = 지표, 열 = 선택 모델(선택 순서). 행 순서: `final_loss`("최종 loss"), `min_loss`("최소 loss"), 그 뒤 `eval_score.metrics` 키 합집합(사전순). 값 없음 "—", `eval_status≠DONE`이면 열 머리에 "평가 전"/"평가 실패", `eval_score.status=UNRECOGNIZED`면 "점수 형식 미확인" |
| 최고 강조 | 행마다 최고값 셀을 굵게 + 배경 강조 + `aria-label` 끝에 "(최고)". 방향: loss 두 행은 **낮을수록 좋음 고정**. metrics 행은 기본 낮을수록 좋음(오차 지표 가정 A3-4), 행 머리의 "↓ 낮을수록"/"↑ 높을수록" 토글로 바꿀 수 있고 지표 이름별로 `localStorage`(`physicsai.metricDirection.<name>`, try/catch)에 기억. 동률이면 모두 강조, 값이 1개 이하인 행은 강조 없음 |
| 메타 행 | 표 아래 별도 묶음: 등록일(로컬 날짜·시각), 등록자, epoch 수(`last_epoch`/`epochs_total`, 예 "1500/1500"), 최소 loss epoch, 데이터셋(`dataset_id` 앞 8자 + "학습 {train_count} · 평가 {eval_count}", 없으면 "없음(평가 불가)"), 로그 상태 |
| 데이터셋 경고 | 선택 모델의 `dataset_id`가 2종 이상이면 표 위 주의 문구 "평가 데이터셋이 서로 다릅니다 — 점수를 직접 비교하기 어렵습니다" |
| Final 연계 | 각 열 머리에 Final 배지 또는 "Final 지정" 버튼(power, `ACTIVE`) — 기존 `setFinal` 흐름 재사용(대화상자 없음, 기존 ③-5와 같음). 지정 후 모델 목록·Study 재조회, 비교 패널은 유지 |
| 로딩·오류 | 상세 조회 중 "불러오는 중…", 개별 모델 404면 그 열에 "모델을 찾을 수 없습니다" |

순수 함수는 `stages/stage3/compare.ts`로 분리해 단위 시험한다: `metricRows(models)`, `bestIndices(values, direction)`, `seriesFor(models)`, `canUseLog(models)`.

### 4.4 시험·Verifier

| ID | 기준 | 방법 |
|---|---|---|
| V3-S2-1 | 선택 2~5 제약(1개 비활성 버튼, 6번째 체크박스 비활성), 비교 패널 열기 시 `GET /models/{id}` 선택 수만큼 + 서로 다른 데이터셋 수만큼 `GET /datasets/{id}`만 호출(`recordCalls`) | 프런트(`__tests__/compare.test.tsx`) |
| V3-S2-2 | `bestIndices`: 낮을수록/높을수록·동률·값 1개·`null` 섞임, `metricRows`: 합집합·순서·`UNRECOGNIZED` | 단위(vitest, `compare.ts`) |
| V3-S2-3 | 로그 토글: 기본 켬, 0 이하 값 있으면 비활성 문구, 곡선 없는 모델 범례 문구 | 프런트 |
| V3-S2-4 | 데이터셋 다름 경고, 열 머리 Final 지정 → `PUT /studies/{id}/final-model` 1회 후 배지 이동 | 프런트 |
| V3-S2-5 | 목 데이터에 metrics가 다른 모델 3개·곡선 없는 모델 1개 존재(`mock/data.ts` 시드 추가 — ID 생성 순서 보존을 위해 **기존 시드 뒤에** 추가) | 프런트 |

### 4.5 구현 분해

- **Backend**: 없음.
- **Frontend**: `stages/stage3/EvaluateCard.tsx`(선택 열·버튼, `useModelDetails` 재사용), `stages/stage3/ModelCompare.tsx`(신규: 차트·점수 표·메타), `stages/stage3/compare.ts`(신규), `components/Chart.tsx`(필요 시 시리즈 색 클래스 prop만 추가 — 기존 호출 모양 유지), `styles.css`(`--series-*`, 비교 표 — 기존 선택자 순서 건드리지 않고 파일 끝에 추가, H6), `mock/data.ts`(시드 뒤 추가), `__tests__/compare.test.tsx`(신규).

---

## 5. S3 Study 용량 표시·정리

### 5.1 결정 요약

- 용량 계산은 **워커 경량 작업**(job_type `STUDY_STORAGE_SCAN`, LIGHT 레인, stage 0). 이유: 네트워크 공유 드라이브의 큰 Study는 스캔에 분 단위가 걸릴 수 있어 API 요청 안에서 계산하지 않는다. 작업 레일을 쓰면 lease·중단 회수·진행률·로그·관리자 취소가 이미 있다(2차 환경 점검은 Study 비소속이라 전용 테이블을 썼지만 이것은 Study 소속).
- **캐시** = 그 Study의 가장 최근 `SUCCEEDED` 스캔 작업의 `jobs.result`(경로·크기·개수만 — DB 규칙 준수). "다시 계산" = 새 스캔 작업.
- 정리는 job_type `STUDY_CLEANUP`(LIGHT, stage 0). **미리보기는 스캔 결과**(범주별 항목 목록·총량)를 그대로 보여 주고, 정리 작업은 그 스캔 ID를 받아 실행 시점에 보호 규칙을 다시 검사한 항목만 옮긴다.
- 이동 위치: 기존 백업 규칙과 같은 `_backup/<UTC yyyyMMddTHHmmssZ>_<cleanup job_id>/<원래 상대경로>`(1차 §15.1 — 요청의 `_backup/<날짜>`를 기존 형식으로 구체화). 같은 Study 폴더 안이라 `os.replace`(이름 바꾸기)로 즉시 이동. **삭제 호출 없음**.
- 권한: 스캔·정리 모두 **power(Study 실행 권한자)**(가정 A3-5). 조회(`GET /studies/{id}/storage`)는 로그인 사용자 전원.

### 5.2 job_type

| job_type | stage | lane | 표시명 | step(kind, weight) |
|---|---|---|---|---|
| `STUDY_STORAGE_SCAN` | 0 | LIGHT | "용량 계산" | `SS_WALK`(INTERNAL 90), `SS_CLASSIFY`(INTERNAL 10) |
| `STUDY_CLEANUP` | 0 | LIGHT | "Study 정리" | `SC_VALIDATE`(INTERNAL 5), `SC_MOVE`(INTERNAL 90), `SC_RECORD`(INTERNAL 5) |

`stage_label`은 "관리". `ux_jobs_study_type_active`로 Study당 유형별 활성 1개(기존 409 `STUDY_JOB_BUSY`). 두 유형 모두 `can_retry=false`(재시도 대신 새로 실행 — `retry_job`이 409 `JOB_NOT_RETRYABLE` "이 작업은 재시도 대신 새로 실행하세요").

**params**(알 수 없는 키 422, 1차 §10.6):

- `STUDY_STORAGE_SCAN`: `{}`.
- `STUDY_CLEANUP`: `{scan_job_id: str, categories: [CategoryKey, …](1~6개, 중복 금지)}`.

**사전조건**(409 `PREREQUISITE_MISSING` 형식 또는 개별 코드):

| 유형 | 조건 | 오류 |
|---|---|---|
| SCAN | 설정 정상 | 503 `CONFIG_INVALID` |
| CLEANUP | `scan_job_id`가 이 Study의 `STUDY_STORAGE_SCAN`이고 `SUCCEEDED`이며 **가장 최근** 성공 스캔 | 409 `STORAGE_SCAN_STALE` "용량 계산 결과가 최신이 아닙니다. 다시 계산한 뒤 정리하세요" |
| CLEANUP | 스캔이 낡지 않음(§5.4 `stale=false`) | 409 `STORAGE_SCAN_STALE` |
| CLEANUP | Study에 비종료 작업 없음(SCAN 포함) | 409 `STUDY_HAS_ACTIVE_JOB` "대기 중이거나 실행 중인 작업이 있어 정리할 수 없습니다" |
| CLEANUP | 선택 범주의 스캔 항목 합계 ≥ 1 | 422 `INPUT_INVALID` `loc:["categories"]` "옮길 항목이 없습니다" |

### 5.3 스캔(`SS_WALK`, `SS_CLASSIFY`)

- 대상: `<ai_root>/<folder_name>` 전체. `os.scandir` 재귀, **링크·junction·reparse point는 따라가지 않고 개수만** 센다(`skipped_links`). 권한 오류·사라진 파일은 건너뛰고 `errors` 증가(작업 실패 아님).
- 진행률: 항목 1만 개마다 `progress_label="{n}개 확인"`(전체 수를 모르므로 `progress_pct`는 `SS_WALK` 동안 비움), `ctx.checkpoint()`로 취소 반영.
- 상한: 항목 `study_storage.max_entries`(기본 2,000,000)에 닿으면 멈추고 `partial=true` + 경고 `STORAGE_SCAN_PARTIAL`(작업은 SUCCEEDED). partial 스캔으로는 정리 불가(409 `STORAGE_SCAN_STALE`과 같은 문구에 "(부분 스캔)" 추가 — 코드 `STORAGE_SCAN_PARTIAL`).
- 집계(모두 바이트·개수):
  - `folders`: 최상위 이름별 합계 — `00_inbox`, `01_train`, `02_import`, `02_preview`, `02_curated`, `03_dataset`, `03_package`, `03_model`, `04_params`, `04_predict`, `05_opt`, `logs`, `_backup`, `(기타)`(위에 없는 최상위 항목, `study.json` 포함). UI는 단계로 묶어 표시(①=`01_*`, ②=`02_*`, ③=`03_*`, ④=`04_*`, ⑤=`05_*`, 공통=`logs`·`00_inbox`·`(기타)`, 백업=`_backup`).
  - `top_files`: 큰 파일 상위 `study_storage.top_files`(기본 20) `{rel, bytes, modified_at}`. `_backup` 하위 포함(표시에 "백업" 표지).
  - `backup_bytes`/`backup_files`: `_backup` 합계(= `folders["_backup"]`, 편의 필드).
  - `categories`: §5.5 범주별 이동 후보 항목(`SS_CLASSIFY`가 DB와 대조해 보호 규칙 적용). 범주당 항목 ≤ `study_storage.max_items_per_category`(기본 500, 큰 것부터), 넘으면 `truncated=true`(정리는 목록에 있는 항목만 — 다시 계산 후 반복).
- 결과는 `jobs.result`에 §5.6 `StorageScan` 모양으로 저장(파일 본문 없음). 크기 예: 범주 6 × 500항목 × ~150B ≈ 450 KB 상한.

### 5.4 낡음(stale) 판정

`GET /studies/{id}/storage`와 CLEANUP 사전조건이 같은 함수(`stage0`이 아닌 공통 서비스 `services/study_storage.py`의 `is_stale`)를 쓴다. 다음 중 하나면 `stale=true`, `stale_reason`에 한국어 사유:

1. 스캔 `started_at` 이후 종료된 **다른 유형** 작업이 있음("스캔 뒤 작업 {n}개가 끝났습니다").
2. 지금 비종료 작업(스캔 자신 제외)이 있음("실행 중인 작업이 있습니다").
3. 스캔 뒤 끝난 `STUDY_CLEANUP`이 있음(1에 포함).
4. 스캔이 `study_storage.stale_after_hours`(기본 24)보다 오래됨("계산한 지 24시간이 지났습니다") (가정 A3-7).

### 5.5 정리 범주와 보호 규칙

**항상 보호(어떤 범주에도 들어가지 않음)**: `03_model/models/**`(등록 모델 원본 복사본 — Final 포함 전부), `03_dataset/**`, `04_params/**`, `00_inbox/**`, `study.json`, `_backup/**`, `<ai_root>/_platform`, 링크·reparse point가 들어 있는 항목(항목 단위로 제외 + 경고), 비종료 작업의 폴더(사전조건으로 0개 보장, `SC_VALIDATE`가 재확인), 정리 작업 자신의 `logs/<job_id>/`.

| CategoryKey | 표시명 | 항목 단위 | 후보 조건(DB 대조) | 옮긴 뒤 영향(화면에 미리 안내) |
|---|---|---|---|---|
| `PACKAGE_PSDATA` | 학습 패키지 사본(psdata) | `03_package/<dataset_id>/` | `datasets.package_rel`이 이 폴더인 데이터셋 | `package_rel=NULL`(R3-7). ③-2 "학습 패키지 내보내기"로 다시 만들 수 있음 |
| `SCORE_PREDICTIONS` | 평가 예측 psdata | `03_model/score/<model_id>/<job_id>/predictions.psdata`(파일) | 종료된 EVALUATE 작업. **제외**: Final 모델의 최신 평가(`models.eval_job_id`) | 점수(DB)·`.psscr`는 그대로. 다시 평가하면 새로 생김 |
| `CURATED_H3D` | 정리된 h3d(②) | `02_curated/<curation_id>/CURATED_DATA/` | `curations`의 READY 행 | `file_list.json`은 남음. 이 큐레이션으로 ③-1 데이터셋을 **새로** 만들 수 없음(입력 없음 → `DATASET_CREATE` 실패). 항목 비고 "데이터셋 {n}개가 이 큐레이션으로 만들어짐" |
| `PREDICT_INPUT` | 예측 Radioss 입력(④) | `04_predict/<root_job_id>/INPUT/`, `04_predict/<root_job_id>/verify/<attempt>/input/` | 종료된 PREDICT·PREDICT_VERIFY(재시도 묶음은 root 기준) | "입력파일 받기"(input.zip)·PBS 검증 재실행 불가(R3-6). PREDICT_VERIFY 생성 시 INPUT 없으면 409 `PREREQUISITE_MISSING` `missing:["PREDICT_INPUT"]`(신규 키). 결과·컨투어는 그대로 |
| `PREVIEW_OUTPUT` | ② 미리보기 산출 | `02_preview/<job_id>/` | 종료된 `CU_H3D_PREVIEW`·`CU_T01_PREVIEW`. **제외**: 유형별 최신 성공 1개 | 지난 미리보기 화면은 "결과 파일 없음". 다시 실행하면 새로 생김 |
| `JOB_LOGS` | 작업 로그 | `logs/<job_id>/` | 종료 후 `study_storage.log_min_age_days`(기본 30)일 지난 작업. **제외**: (Study, job_type)별 최신 작업, 실패·중단 작업 중 최근 `study_storage.keep_failed_logs`(기본 10)개 | 로그 보기·오류 묶음의 로그 부분 없음(R3-5). 오류 묶음은 로그 없음을 `manifest.json`에 표시 |

- 항목 비고 `note`(한국어, ≤120자)와 참조 ID `ref_id`(dataset/model/curation/job id)를 함께 저장한다.
- 범주는 위 6개로 고정(열거형). 추가는 계약 변경.

### 5.6 API·스키마

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| **`GET /studies/{id}/storage`**(신규) | 로그인 | – | `StorageReport` | 404 |
| `POST /studies/{id}/jobs` `job_type="STUDY_STORAGE_SCAN"` | power | `{}` | `201 Job` | 409 `STUDY_JOB_BUSY`, 503 `CONFIG_INVALID` |
| `POST /studies/{id}/jobs` `job_type="STUDY_CLEANUP"` | power | `{scan_job_id, categories}` | `201 Job` | §5.2 표, 409 `STUDY_JOB_BUSY` |

라우터 함수 이름 `get_study_storage`(신규 파일 `routers/study_storage.py`, 태그 `studies`). `JobType` Literal(`schemas/jobs.py`)에 두 유형 추가.

```text
StorageReport {
  study_id: str
  scan: StorageScan | null                 # 최근 SUCCEEDED 스캔(없으면 null)
  stale: bool, stale_reason: str | null    # §5.4 (scan null이면 stale=true, "아직 계산하지 않았습니다")
  active_scan_job_id: str | null           # 비종료 SCAN
  active_cleanup_job_id: str | null        # 비종료 CLEANUP
  last_cleanup: CleanupSummary | null      # 최근 종료 CLEANUP
  study_display_path: str | null           # B17
  backup_display_path: str | null          # <study>\_backup (B17, 탐색기 붙여넣기용)
}
StorageScan {
  job_id: str, started_at: datetime, finished_at: datetime, partial: bool,
  total_bytes: int, total_files: int, skipped_links: int, errors: int,
  backup_bytes: int, backup_files: int,
  folders: [{key: str, bytes: int, files: int}],
  top_files: [{rel: str, bytes: int, modified_at: datetime, in_backup: bool}],
  categories: [{key: CategoryKey, label: str, total_bytes: int, item_count: int, truncated: bool,
                items: [{rel: str, bytes: int, files: int, ref_id: str | null, note: str | null}]}]
}
CleanupSummary {
  job_id: str, state: str, finished_at: datetime | null, categories: [CategoryKey],
  moved_count: int, moved_bytes: int, skipped_count: int, backup_rel: str | null, backup_display_path: str | null
}
```

`rel`은 Study 기준 `/` 구분 상대경로(절대경로 금지 규칙 유지, 표시용 절대경로는 `*_display_path`만).

### 5.7 정리 실행(`SC_*`)

| step | 처리 |
|---|---|
| `SC_VALIDATE` | 스캔 결과에서 선택 범주 항목을 읽고, 실행 시점에 §5.5 후보 조건·항상 보호 규칙을 **다시** 검사(DB 재조회, 경로 `resolve_in_study`, 링크 재확인). 조건이 바뀐 항목은 `skipped`(사유). 비종료 작업이 생겼으면 실패 `PREREQUISITE_MISSING`. 대상 0개면 실패 `INPUT_INVALID` "옮길 항목이 없습니다" |
| `SC_MOVE` | 항목마다 `paths.backup_existing`과 같은 규칙(`_backup/<stamp>_<job_id>/<rel>`, 덮어쓰지 않고 `~N`)으로 `os.replace`. **항목 단위로 실패를 모은다**: 잠김 등 `OSError` → 그 항목 `skipped`(사유 "파일이 사용 중") 후 계속. 항목 사이 `checkpoint()`(관리자 취소 시 남은 항목 미이동, 이미 옮긴 것은 그대로). 진행률 = 옮긴 항목 수/전체 |
| `SC_RECORD` | `_backup/<stamp>_<job_id>/CLEANUP_MANIFEST.json`(작업 ID·실행자·시각·범주·항목 `{rel, bytes, category}`·되돌리는 법 한 줄) 작성. DB: 옮긴 `PACKAGE_PSDATA`의 `datasets.package_rel=NULL`. `jobs.result` = `CleanupSummary` 필드 + `moved:[{rel, bytes, category}]`(≤ 범주×500) + `skipped:[{rel, reason}]`. 전부 실패면 작업 FAILED `OUTPUT_LOCKED`, 일부 실패면 SUCCEEDED + 경고 `PARTIAL_OUTPUT` |

- 알림: 기존 `JOB_SUCCEEDED`/`JOB_FAILED`(등록자), 본문에 "{n}개 항목, {크기} 이동"(`_title` 확장).
- 감사: 작업 생성 감사(`JOB_CREATE`) 그대로 + `SC_RECORD`가 `STUDY_CLEANUP` 감사 행(범주·개수·바이트).
- 실행 중 다른 작업 생성 차단은 R3-4.

### 5.8 UI — Study 관리 화면 ③ "용량·정리"(`pages/StudyManage.tsx` 안 `StorageSection`)

| 요소 | 사양 |
|---|---|
| 요약 줄 | "전체 {크기} · 파일 {n}개 · 백업 {크기}" + "계산 시각 {상대 시각}" + 낡음이면 주의 문구 `stale_reason`. 스캔 없음이면 "아직 계산하지 않았습니다" |
| 다시 계산 | 버튼 "다시 계산"(power). 실행 중이면 `JobInline`(진행 라벨 "{n}개 확인"). 끝나면 자동 재조회(`usePolling`, 실행 중에만 3초) |
| 단계별 막대 | ①~⑤·공통·백업 가로 막대(크기 비례, 수치 라벨 병기 — 색만으로 의미 전달 금지). 펼치면 `folders` 세부 |
| 큰 파일 | 상위 20 표: 상대경로(말줄임 + title 전체), 크기, 수정 시각, "백업" 표지 |
| 정리 | 범주 체크박스 6개: 표시명 + "{item_count}개 · {total_bytes}"(0개면 비활성) + 영향 안내 한 줄(§5.5 마지막 열 요약). 아래 **미리보기**: 선택 범주의 항목 표(범주·상대경로·크기·비고, 범주별 접기, `truncated`면 "상위 500개만 표시·이동됩니다"), 총량 "선택 {n}개 · {크기}" |
| 정리 버튼 | "백업 폴더로 옮기기"(power, `stale=false`·항목 ≥1·활성 작업 없음일 때만, 아니면 비활성 + 사유 title). 확인 대화상자: 제목 "Study 정리", 본문 "선택한 {n}개 항목({크기})을 `_backup` 폴더로 옮깁니다. 파일은 삭제되지 않습니다.\n옮기는 동안 이 Study에서 다른 작업을 실행할 수 없습니다.\n{선택 범주의 영향 안내 목록}" 버튼 "옮기기"·"취소" |
| 결과 | `last_cleanup`: "{시각} · {n}개 {크기} 이동 · 건너뜀 {m}개" + 백업 폴더 표시 경로(복사 버튼) + 건너뜀 사유 펼치기 |
| `_backup` 안내 | 회색 문구(항상): "`_backup` 폴더는 앱에서 비우지 않습니다. 필요 없으면 탐색기에서 직접 삭제하세요. 되돌리려면 `_backup/<시각>_<작업ID>/` 아래 파일을 원래 위치로 옮기면 됩니다." |
| 보관 Study | 계산·정리 모두 가능(R3-2) |

### 5.9 설정(`config/platform.example.yaml`, 새 절 `study_storage`)

| 키 | 기본 | 검증 |
|---|---|---|
| `study_storage.max_entries` | 2000000 | 1000~50000000 |
| `study_storage.top_files` | 20 | 1~200 |
| `study_storage.max_items_per_category` | 500 | 10~5000 |
| `study_storage.log_min_age_days` | 30 | 0~3650 |
| `study_storage.keep_failed_logs` | 10 | 0~1000 |
| `study_storage.stale_after_hours` | 24 | 1~720 |

절이 없으면 기본값(기능 비활성 아님). 사용자 매뉴얼(`docs/manual/`)에 §5.8 `_backup` 안내 문구와 되돌리는 법을 Plan이 추가한다(3차 구현 완료 후).

### 5.10 DB — migration `0004_study_manage`

- `jobs`: `ck_jobs_stage`를 `stage BETWEEN 0 AND 5`로 교체(명시적 DDL, 0002·0003 방식). 다른 테이블·컬럼 변경 없음(스캔·정리 결과는 `jobs.result`, 데이터셋은 기존 `package_rel` 갱신).
- `MIGRATION_HEAD = "0004_study_manage"`, downgrade는 RuntimeError(기존 규칙).
- `notifications`·`audit_events`·`artifacts` CHECK 변경 없음(새 이벤트 없음, `audit_events.action`은 CHECK 없음).

### 5.11 시험·Verifier

| ID | 기준 | 방법 |
|---|---|---|
| V3-DB-1 | 빈 PG `upgrade head`(0001→0004), `MIGRATION_HEAD`, stage 0 행 삽입 성공·-1·6 거부, downgrade RuntimeError | PG |
| V3-S3-1 | 스캔: 폴더별 합계·top N·`_backup` 합계가 `tmp_path` 픽스처 트리와 정확히 일치, 링크 미추적·`skipped_links`, 권한 오류 `errors`, `max_entries` → partial+경고 | 워커(`worker/tests/stage0_manage/test_storage_scan.py`) |
| V3-S3-2 | 범주 분류: §5.5 표 각 행의 후보·제외 조건(Final 최신 평가 제외, 최신 미리보기 제외, 로그 나이·유형별 최신·실패 보존, 03_model/models·03_dataset·04_params 항상 제외), 항목 상한·`truncated` | 워커 |
| V3-S3-3 | 낡음 판정 4규칙, CLEANUP 사전조건 각 오류 코드(`STORAGE_SCAN_STALE`, `STORAGE_SCAN_PARTIAL`, `STUDY_HAS_ACTIVE_JOB`, `INPUT_INVALID`), 권한(viewer 403) | API |
| V3-S3-4 | 정리: `_backup/<stamp>_<job_id>/<rel>`로 이동·원래 위치 없음·삭제 호출 0(정적 시험 `test_static_security`의 삭제 금지 규칙 유지), 매니페스트 내용, `package_rel=NULL`, 실행 시점 재검사로 바뀐 항목 건너뜀, 잠금 모의(`os.replace` 예외) → 항목 건너뜀·PARTIAL_OUTPUT, 전부 실패 → FAILED `OUTPUT_LOCKED`, 취소 시 남은 항목 미이동 | 워커 |
| V3-S3-5 | R3-4: CLEANUP 활성 중 SCAN 포함 모든 작업 생성·재시도와 Final 지정 409 `STUDY_CLEANUP_RUNNING`(D3-24). R3-2: 보관 Study에서 SCAN·CLEANUP 생성 가능, 다른 유형 409 `STUDY_ARCHIVED` | API |
| V3-S3-6 | R3-5·R3-6 문구, `input_display_path` 폴더 없으면 null, PREDICT_VERIFY `missing:["PREDICT_INPUT"]`, 오류 묶음이 로그 없음을 표시 | API |
| V3-S3-7 | R3-3: 스캔 성공 시 알림 0건, 실패 시 `JOB_FAILED` 1건, 정리 성공 알림 본문 "{n}개 항목" | API·워커 |
| V3-S3-8 | `GET /studies/{id}/storage` 모양 = §5.6, 절대경로는 `*_display_path`만, `rel`에 `..` 없음 | API |
| V3-S3-9 | 설정 §5.9 기본값·범위 검증, 절 없을 때 기본 | 단위(`backend/tests/common/test_config.py` 확장) |
| V3-S3-10 | UI: 범주 체크 → 미리보기 총량, 비활성 사유(stale·활성 작업·0개), 확인 대화상자 문구에 영향 안내 포함, 실행 시 `POST /studies/{id}/jobs {job_type:"STUDY_CLEANUP", params:{scan_job_id, categories}}` 1회, `_backup` 안내 문구 항상 표시 | 프런트(`__tests__/manage.test.tsx` `describe("V3-S3-10 …")`) |
| V3-S3-11 | 실제 Windows: 열린 파일이 있는 항목 건너뜀, 매핑 드라이브·UNC AI 루트에서 이동, 탐색기에서 `_backup` 삭제 후 다음 스캔 반영 | 수동(e2e-checklist.md E3-S3, Plan이 추가) |

### 5.12 구현 분해

- **Backend**
  - `migrations/versions/0004_study_manage.py`, `backend/physicsai_core/db/tables.py`(CHECK), `db/__init__.py`(`MIGRATION_HEAD`).
  - `backend/physicsai_core/job_types.py`: 두 유형, `JobTypeDef.notify_success: bool = True` 필드, `stage_label` "관리".
  - `backend/physicsai_core/study_storage/`(신규 공통 패키지 — 단계 패키지가 아님, architecture.md §4.1 표에 "Study 관리(stage 0)" 행 추가 필요): `categories.py`(CategoryKey 열거·표시명·영향 문구 — API·워커 공용), `scan.py`(트리 걷기·집계 순수 함수, 링크 판정은 `paths` 재사용), `classify.py`(DB 행 + 트리 → 범주 항목, 보호 규칙), `stale.py`(낡음 판정).
  - `backend/physicsai_core/db/repositories/jobs.py`: `latest_succeeded(conn, study_id, job_type)`, `finished_after(conn, study_id, ts, exclude_types)`, `has_active_of_type`. `repositories/datasets.py`: `clear_package(conn, dataset_id)`. `repositories/notifications.py`: `notify_success=False`면 시작·성공·차례 알림 생략, 정리 본문.
  - `backend/physicsai_core/config/schema.py`·`validate.py`: `StudyStorageCfg`(§5.9). `config/platform.example.yaml`.
  - `backend/physicsai_api/schemas/study_storage.py`(신규: `StorageReport`, `StorageScan`, `CleanupSummary` 등 — `schemas/__init__` 재노출), `schemas/jobs.py`(`JobType`).
  - `backend/physicsai_api/services/study_storage.py`(신규: 보고서 조립·`is_stale` 호출), `services/job_params/study_manage.py`(신규: 두 유형 params 모델·`prepare`·사전조건, `job_params/__init__` 병합), `services/jobs.py`(R3-2 예외, R3-4 검사 — `create_job`·`retry_job`, 두 유형 `JOB_NOT_RETRYABLE`), `services/common.py`(`can_retry` 두 유형 false, `input_display_path` 폴더 존재 확인), `services/jobs.read_log`(R3-5 문구), `services/jobs.input_zip`(R3-6 문구), `services/job_params/stage4_predict.py`(PREDICT_VERIFY `PREDICT_INPUT`), `services/error_bundle.py`·`core/error_bundle.py`(로그 없음 표시).
  - `backend/physicsai_api/routers/study_storage.py`(신규) + `main.py` 등록.
  - `worker/physicsai_worker/steps/stage0_manage/{__init__,storage_scan,cleanup}.py`(신규, `HANDLERS` 병합 — `test_step_registry`가 job_types와 대조).
  - `backend/openapi.json`, `backend/tests/data/operation_ids.txt`, 시험 `backend/tests/common/test_study_storage_api.py`, `worker/tests/stage0_manage/test_storage_scan.py`·`test_cleanup.py`, `backend/tests/common/test_layering.py`(새 패키지 규칙 5 대상에 `study_storage`를 공통으로 등록).
- **Frontend**: `api/endpoints.ts`(`studyStorage`), `api/types.ts`(`JobType` 확장 반영, `CategoryKey`), `pages/StudyManage.tsx`(`StorageSection` — 120줄을 넘으면 `pages/manage/StorageSection.tsx`·`CleanupPreview.tsx`로 분리), `lib/format.ts`(`fmtBytes` 없으면 추가, 단계 묶음 상수), `components/ConfirmDialog.tsx`(S1과 공유), `mock/manage.ts`(스캔 진행·결과·정리 흉내), `__tests__/manage.test.tsx`.

---

## 6. S4 공통 어댑터 패키지 `simdash_adapters`

### 6.1 목표·범위

- 현재 `backend/physicsai_core/hpc/`(`gateway.py` 77, `command.py` 207, `none.py` 17, `adapter.py` 21줄)와 회수 경로 해석(`worker/…/steps/stage1_train_data/solve.py::_remote_result_dir`, `hpc/command.map_path`)을 저장소 안 별도 배포 단위로 옮긴다.
- **드라이브 접근 인터페이스(StorageProvider 등)는 현재 코드에 없다**(코드 확인: `collect_mode` `drive`는 `shared_folder` 별칭으로 경로 계산 + 워커의 안정성 대기·`copy_file`만). 새 추상화를 만들지 않고, **순수 경로 해석 함수만** 패키지로 옮긴다. 안정성 대기·복사 루프(`ctx.checkpoint`, `fileutil.copy_file` 의존)는 워커에 남긴다.
- 동작 불변: `backend/openapi.json` 바이트 동일, operationId 스냅샷 동일, 설정 YAML 키·검증 메시지 동일, `test_hpc.py`·`test_stage1_train.py` 무수정 통과(정적 시험 경로 조정만 허용 — §6.6).
- 대시보드 연동은 범위 밖. 대시보드는 나중에 같은 wheel을 설치해 쓸 수 있다(공개 API가 플랫폼 설정 객체에 의존하지 않도록 설계).

### 6.2 패키지 배치

```text
packages/simdash_adapters/
  pyproject.toml              # name="simdash-adapters", version, requires-python=">=3.11", dependencies=[]
  CHANGELOG.md
  src/simdash_adapters/
    __init__.py               # __version__, 공개 이름 재노출(__all__)
    py.typed
    pathstr.py                # fwd(path), is_abs_path_str(p) — 순수 문자열 규칙
    hpc/
      __init__.py
      types.py                # HpcState, HpcAvailability, HpcSubmitSpec, HpcSubmitResult, HpcStatus, HpcGatewayError, HpcJobGateway(Protocol)
      config.py               # CommandConfig, HpcDefaults (frozen dataclass, from_obj/from_mapping)
      command.py              # CommandHpcGateway, validate_command_config, render_argv, PLACEHOLDERS·정규식 상수
      none.py                 # NoneHpcGateway
      adapter.py              # AdapterHpcGateway(자리)
      factory.py              # make_gateway(mode, command=None, defaults=None, env_factory=None, logger=None)
    transfer/
      __init__.py
      config.py               # PathMapEntry, TransferConfig (frozen dataclass, from_obj/from_mapping)
      paths.py                # map_path(path, path_map), resolve_collect_dirs(...)
  tests/                      # 패키지 자체 시험(플랫폼·PG 없이 실행)
```

### 6.3 공개 API(`simdash_adapters.__all__`, 이 목록 밖은 비공개)

| 이름 | 내용 | 원래 위치 |
|---|---|---|
| `__version__` | `"0.1.0"` | — |
| `HpcState`, `HpcAvailability`, `HpcSubmitSpec`, `HpcSubmitResult`, `HpcStatus`, `HpcGatewayError`, `HpcJobGateway` | 1차 §12.2 모양 그대로(필드·순서·Literal 값·오류 코드 집합) | `core/hpc/gateway.py` |
| `CommandConfig` | `submit/status/cancel: tuple[str,…]`, `allowed_executables`, `job_id_regex`, `state_regex`, `exit_code_regex`, `not_found_regex`, `state_map`, `submit_timeout_s`, `status_timeout_s`, `cancel_timeout_s` — `from_obj(o)`(속성 읽기, 플랫폼 pydantic `HpcCommandCfg`를 그대로 넘길 수 있음), `from_mapping(d)` | 새 이름(키는 `hpc.command.*`와 1:1) |
| `HpcDefaults` | `queue`, `ncpus`, `walltime` | `hpc.defaults.*` |
| `validate_command_config(cfg) -> list[str]` | 문제 목록(한국어 문구 **그대로**) | `core/hpc/command.py` |
| `render_argv(cfg, key, values) -> list[str]` | 명령 템플릿 렌더러(placeholder 화이트리스트·값 검사 `_check_value` 규칙 그대로) | `CommandHpcGateway.render` |
| `CommandHpcGateway(cfg, defaults, env_factory=None, logger=None)` | submit/status/cancel. `subprocess`는 메서드 안에서 import(현행) | `core/hpc/command.py` |
| `NoneHpcGateway`, `AdapterHpcGateway` | 문구 그대로 | `core/hpc/none.py`, `adapter.py` |
| `make_gateway(mode, …)` | `"none"`·`"command"`·`"adapter"` → 인스턴스(알 수 없는 값은 none, 현행 `get_hpc_gateway`와 같음) | `get_hpc_gateway`의 분기 |
| `PathMapEntry`, `TransferConfig` | `collect_mode`, `collect_root_remote`, `collect_root_local`, `path_map` | `hpc.transfer.*` |
| `map_path(path, path_map)` | 현행 그대로(첫 일치 접두, 대소문자 무시) | `core/hpc/command.map_path` |
| `resolve_collect_dirs(transfer, *, study_folder, doe_id, run_key, local_result_dir) -> tuple[str, str \| None]` | (PBS result_dir, 회수할 로컬 경로 \| None=in_place) | `solve.py::_remote_result_dir` 본문 |
| `fwd`, `is_abs_path_str` | 현행 그대로 | `core/commands.fwd`, `core/config/rules.is_abs_path_str` |

설계 규칙:

- **의존성 0**: 표준 라이브러리만(`dataclasses`, `typing`, `re`, `string`, `os`, `logging`, 메서드 안 `subprocess`). pydantic·SQLAlchemy·`physicsai_*` import 금지(시험으로 강제, §6.6).
- **설정 스키마**: YAML 키의 단일 출처는 계속 플랫폼 `physicsai_core/config/schema.py`(pydantic). 패키지는 같은 키 이름의 frozen dataclass와 `from_obj`/`from_mapping` 변환만 가진다. 플랫폼은 `CommandConfig.from_obj(settings.hpc.command)`로 넘긴다. 기본값은 패키지 dataclass에 두지 않는다(필수 인자) — 기본값이 두 곳에서 갈라지지 않게.
- **환경변수**: 자식 환경은 호출자가 `env_factory`로 준다(플랫폼 `child_env` 허용목록 그대로). 패키지는 환경을 읽지 않는다.
- **마스킹 비의존**: 패키지는 마스킹하지 않는다. `HpcGatewayError` 메시지(stderr ≤300자)와 `raw_stdout`(≤4 KiB)은 원문이고, 저장·로그 전에 **호출자가** 마스킹한다(플랫폼은 현행대로 step 로그 `Masker`·운영 로그 `MaskingFilter` 적용). 공개 문서(패키지 README 대신 docstring)에 명시.
- **로깅**: 기본 로거 `simdash_adapters.hpc.command`. 플랫폼 호환층은 `logger=logging.getLogger("physicsai_core.hpc.command")`를 넘겨 로그 이름 불변.
- 사용자 문구(한국어) 그대로. 패키지가 다른 제품(대시보드)에서 쓰여도 문구는 한국어(사내 전용).

### 6.4 플랫폼 쪽 호환층(동작 불변 장치)

| 파일 | 변경 후 |
|---|---|
| `backend/physicsai_core/hpc/gateway.py` | 타입 재노출(`from simdash_adapters.hpc.types import *`) + `get_hpc_gateway(settings)`(설정 읽기·`child_env`·`PHYSICSAI_HPC_GATEWAY` 우선순위는 플랫폼 몫으로 남기고 `make_gateway` 호출) |
| `backend/physicsai_core/hpc/command.py` | `CommandHpcGateway(hpc, env_factory=None)` 얇은 클래스(현 시그니처 유지 — `test_hpc.py`가 `CommandHpcGateway(lc.settings.hpc)`로 생성): `hpc.command`·`hpc.defaults`를 변환해 패키지 클래스로 위임, 로거 이름 전달. `validate_command_config(hpc)`(현 시그니처: `hpc` 받음) → 패키지 함수에 `hpc.command` 변환 전달. `map_path` 재노출 |
| `backend/physicsai_core/hpc/none.py`, `adapter.py` | 재노출 |
| `backend/physicsai_core/commands.py` `fwd`, `config/rules.py` `is_abs_path_str` | 패키지 함수 재노출(같은 객체). 내용이 한 글자라도 다르면 재노출하지 않고 차이를 변경 메모로 보고 |
| `worker/…/steps/stage1_train_data/solve.py` | `_remote_result_dir`가 `resolve_collect_dirs(TransferConfig.from_obj(t), …)` 호출(반환값 동일) |

### 6.5 버전 정책·배포

- **SemVer**. 초기 `0.1.0`. 0.x 동안: 공개 API(§6.3) 모양 변경 = minor 올림, 동작 수정·문구 외 내부 변경 = patch. `1.0.0`은 대시보드가 실제로 쓰기 시작할 때(별도 결정).
- 단일 출처: `pyproject.toml`의 `version`과 `__version__` 일치(시험). 변경 시 `CHANGELOG.md`에 한 줄.
- 플랫폼 의존 선언: 루트 `pyproject.toml` `dependencies`에 `"simdash-adapters==0.1.0"`(정확 고정 — 같은 저장소라 함께 올린다). `[tool.pytest.ini_options] pythonpath`에 `packages/simdash_adapters/src` 추가, `testpaths`에 `packages/simdash_adapters/tests` 추가(설치 없이 시험 가능).
- 개발 설치: `scripts/dev-setup`(또는 기존 설치 스크립트)에서 `pip install -e packages/simdash_adapters` 후 플랫폼 설치.
- **오프라인 배포**: `deploy/collect-offline.{sh,ps1}`가 `pip wheel --no-deps packages/simdash_adapters -w <bundle>/wheels`로 `simdash_adapters-0.1.0-py3-none-any.whl`을 만들어 묶음에 넣고, `simdash-adapters==0.1.0`은 PyPI용 `deploy/requirements.lock`에 넣지 않고 로컬 전용 `deploy/requirements.local.lock`에 고정해 `pip download --no-index --find-links <bundle>/wheels`로만 확인한다(PyPI 이름 선점 차단, D3-27). `deploy/install.ps1`·`update.ps1`은 기존처럼 `--no-index --find-links <bundle>/wheels`로 설치(추가 인자 없음). wheel은 순수 Python(`py3-none-any`) — Windows·Linux 공용.
- CI: Linux·Windows 잡에서 패키지 시험 함께 실행(`scripts/test-all*`가 pytest 한 번으로 포함).
- 소유권: `packages/**`는 Impl-Backend. AGENTS.md 역할 표 갱신 완료(`packages/**`·`.github/**` → Impl-Backend, 메인 승인, A3-8).

### 6.6 시험·Verifier

| ID | 기준 | 방법 |
|---|---|---|
| V3-S4-1 | `backend/openapi.json` 재생성 바이트 동일, `operation_ids.txt` 동일, 설정 시험(`test_config`, `test_ops_config`) 무수정 통과 | 기존 시험 |
| V3-S4-2 | `worker/tests/runtime/test_hpc.py` 무수정 통과(단 `test_adapter_imports_nothing`의 파일 경로는 패키지 `hpc/adapter.py`로 바꾸는 것 허용 — 검사 범위가 줄지 않을 때만), `test_stage1_train.py` 회수 모드 시험(V2-TD-6) 통과 | 기존 시험 |
| V3-S4-3 | 패키지 시험(`packages/simdash_adapters/tests/`): 플랫폼·PG 없이 실행, `validate_command_config` 문구 골든(현행 문구와 동일), `render_argv` 값 검사 각 규칙, `CommandHpcGateway`를 가짜 `qsub`(기존 `backend/tests/fake_tools`의 PBS 가짜를 패키지 시험용 최소 사본으로)로 submit/status/cancel, `map_path`·`resolve_collect_dirs` 표 시험, `make_gateway` 분기 | 단위 |
| V3-S4-4 | 정적: 패키지의 모든 import가 표준 라이브러리(허용 목록) — `physicsai_*`·pydantic·sqlalchemy 없음, 모듈 최상위에 `subprocess` import 없음, `__version__` = pyproject version, `__all__` = §6.3 목록 | 정적(`packages/simdash_adapters/tests/test_static.py`) |
| V3-S4-5 | 레이어: `test_layering`에 규칙 7 "`simdash_adapters`는 `physicsai_*`를 import하지 않는다" 추가, `physicsai_api`가 `simdash_adapters.hpc.command`를 import하지 않음(API는 `availability()`만 — 1차 §12.2) | 정적 |
| V3-S4-6 | `pip wheel` 산출 wheel 이름 `simdash_adapters-0.1.0-py3-none-any.whl`, 빈 venv에 wheel만 설치 후 `python -c "import simdash_adapters; print(simdash_adapters.__version__)"` | CI(Linux) |
| V3-S4-7 | 오프라인 묶음에 wheel 포함·`requirements.lock`에 어댑터 없음·`requirements.local.lock` 고정·install이 `--no-index`로 설치 | 정적(`deploy` 내용 시험) + 수동(Windows, e2e-checklist) |

### 6.7 구현 분해(Backend만)

1. `packages/simdash_adapters/**` 생성(코드는 현행에서 **이동**, 내용 수정은 import 경로와 설정 변환 진입점만).
2. `backend/physicsai_core/hpc/*` 호환층, `commands.fwd`·`config/rules.is_abs_path_str` 재노출, `worker/…/steps/stage1_train_data/solve.py` 호출 변경.
3. 루트 `pyproject.toml`, `scripts/test-all.{sh,ps1}`(필요 시), `deploy/collect-offline.{sh,ps1}`, `deploy/requirements.lock`·`deploy/requirements.local.lock`(D3-27), `scripts/dev-setup.{sh,ps1}`, `.github/workflows/ci.yml`(wheel 시험 V3-S4-6).
4. `backend/tests/common/test_layering.py`(규칙 7), 패키지 시험.
5. 커밋 단위: (a) 패키지 생성+시험, (b) 플랫폼이 패키지 사용(호환층) — 이 커밋에서 openapi·operationId diff 0 확인, (c) 배포·CI.

---

## 7. 공통: 프런트 라우트·목·순서

- 라우트 추가: `/physicsai/p/:projectId/s/:studyId/manage`(S1·S3). 스텝퍼 1~5 라우트는 그대로.
- 목: 3차 핸들러는 `frontend/src/mock/manage.ts`(신규)에 두고 `mock/server.ts`의 라우팅 1곳에서 위임(F5 보류 — `phase2.ts`에 넣지 않는다). 목 ID는 기존 공유 카운터를 쓰되 **시드 생성 뒤**에만 만든다.
- 순서: ① Backend S4(동작 불변, 독립) → ② Backend S1·S3(migration 0004, openapi 갱신) → ③ Frontend 타입 재생성 → S1·S3 화면. **Frontend S2는 백엔드 변경이 없어 ①과 동시에 시작 가능.**
- API 모양이 이 문서와 달라야 하면 이 문서 끝 "변경 메모"에 D3-n으로 남기고 Plan 확인 요청.

## 8. Verifier 공통

| ID | 기준 | 방법 |
|---|---|---|
| V3-REG-1 | 1·2차 체크리스트(V-*, V2-*) 전체 회귀 — 시험 이름이 바뀐 항목은 V-ID로 대조 | 전체 |
| V3-REG-2 | `scripts/test-all` Linux 통과(Altair 없음, PG 있음), Windows CI 녹색, windows skip은 통과로 치지 않음 | CI |
| V3-SEC-1 | 플랫폼 코드 삭제 호출 0(정리 기능 포함), SPDM·`_platform` 경로가 정리 후보에 나타나지 않음, 외부 명령 추가 없음(S3는 파일 이동만) | 정적·단위 |
| V3-DOC-1 | architecture.md §1 지도에 3차 새 파일(`study_storage/`, `steps/stage0_manage/`, `routers/study_storage.py`, `pages/StudyManage.tsx`, `packages/simdash_adapters`) 반영 — 구현 완료 후 Plan | 문서 |

## 9. 가정 목록(사용자 부재 중 결정 — 확인 요청)

| # | 가정 | 근거 |
|---|---|---|
| A3-1 | 보관된 Study도 이름 변경 허용, PATCH가 `study.json` 제목도 갱신(실패해도 API 성공) | 현 PATCH가 상태를 보지 않음, `study.json`은 사람용 메타 |
| A3-2 | Study 목록 기본 필터 = "사용 중"(보관은 탭으로) | 보관 Study가 쌓일수록 목록이 길어짐 |
| A3-3 | 보관된 Study에서도 용량 계산·정리 가능 | "보관 후 정리"가 가장 흔한 흐름일 것 |
| A3-4 | 평가 지표의 좋은 방향 기본 = 낮을수록 좋음(오차 지표), 사용자가 지표별로 바꾸고 브라우저에 기억 | 점수 파서가 지표 의미를 모름(1차 §8.7), 서버 설정 추가보다 단순 |
| A3-5 | 용량 계산·정리 권한 = Study 실행 권한(power). 전역 관리자 전용 아님 | 삭제가 아닌 이동(되돌릴 수 있음), 확인 대화상자·감사 기록 |
| A3-6 | 용량 계산 작업은 성공 알림을 만들지 않음(실패만) | 짧고 잦은 작업의 알림 소음 |
| A3-7 | 스캔 결과 유효 시간 24시간(설정) | 사용자가 탐색기로 파일을 바꿔도 DB가 모름 |
| A3-8 | `packages/**`·`.github/**` 소유 = Impl-Backend — 2026-10-11 메인 승인, AGENTS.md 갱신 완료(가정 해소) | 이번 지시가 `docs/**`만 허용 |
| A3-9 | 정리 범주 6개 고정, `01_train/doe`·`01_train/results`·`02_import`는 3차 범주에서 제외 | DB가 그 경로를 가리킴(run 결과·가져오기 기록) — 옮기면 ①②화면·재실행이 깨짐 |
| A3-10 | 모델 비교는 새 API 없이 `GET /models/{id}` 반복 | 최대 5개, 데이터가 이미 DB·API에 있음 |

## 10. 리스크·미확정

| # | 내용 | 대응 |
|---|---|---|
| U3-1 | 워커 light 스레드는 1개 — 큰 Study 스캔·정리가 길면 같은 레인의 `MODEL_REGISTER`·`PACKAGE_EXPORT`가 기다린다 | 진행 라벨 표시, 관리자 취소, `max_entries` 상한. 실제 시간은 E2E에서 측정(V3-S3-11) |
| U3-2 | Windows에서 열린 파일이 있는 폴더는 `os.replace` 실패 | 항목 단위 건너뜀 + 사유(§5.7) |
| U3-3 | 사용자가 탐색기로 `_backup`에서 되돌린 경우 DB(`package_rel=NULL`)와 어긋남 | 되돌린 패키지는 ③-2 재실행으로 다시 등록(안내 문구) |
| U3-4 | 가장 큰 폴더(`01_train/results`, `01_train/doe`)가 정리 범주에 없음 | 크기는 보이므로 사용자가 판단, 4차에서 DB 참조 정리 규칙과 함께 결정 |
| U3-5 | 스캔 결과 JSON 크기(범주 6×500항목) | 상한 설정, 넘으면 `truncated` |

---

## 11. S6 ④ 예측 원본 일치·준비된 입력 예측 (Plan, 2026-10-15)

목표: 서버(Altair 2026.1)에서 ④ 예측이 원본과 같은 흐름으로 **한 번에 성공**(시연 최우선)하고, 원본 `3_PHYSICS_AI` "예측"(준비된 입력 + 모델 → edspy)을 ④의 입력 방식으로 추가한다. 원본은 읽기 전용 참고(`OPEN_SOURCE_physics_ai_platform`)이며 저장소에 복사하지 않는다. 사용자 확인: 원본 프로그램은 모든 기능이 정상 동작했다.

### 11.1 원본 예측 흐름(근거)

| 원본 기능 | 외부 호출(argv) | cwd·env | 입력 → 출력 | 성공 판정·후처리 |
|---|---|---|---|---|
| ③ 단독 예측 `3_PHYSICS_AI/FUNC/5_predict.py` | `[edspy.bat, --physicsai, --predict-write, <out>.h3d, --model, <psmdl>, --input-file, <input>, (--hooks-dir=<d>)]` (:55-66) | cwd 없음(:121), env 추가 없음 | 입력 `*.rad`/`*.hm`(GUI `5_gui_predict.py:80`), 출력 이름 사용자 지정(:90-91), 기존 출력 삭제(:100-113) | rc≠0 예외(:50-51), 출력 없으면 경고만(:123-127). 미리보기·커브 없음 |
| ⑤ 기준 Predict+Preview `4_OPTIMIZATION/FUNC/1_physicsai_opti.py:281-340` | `[cmd, /c, edspy.bat, --physicsai, --predict-write, RESULT/<stem>_pred.h3d, --model, <psmdl>, --input-file, INPUT/<starter>]` (:308-316) | cwd `PREDICT/INPUT`(:322), env `EDS_TNS_ACTVN_CHCKPT=1`(:318-319) | `RADIOSS_ASSEM_DIR` 직계 `*.rad`·`*.inc` 중 `eps_mesh*` 아닌 것 → `PREDICT/INPUT`(:294-305). starter = `*_0000.rad`(eps_mesh 제외) 정확히 1개(GUI :427-445) | h3d 존재(:325-329). 커브 = RESULT 첫 `*.xy`/`*.xydata`(:331-333). 미리보기 `[hw.exe, -clientconfig, hwpost.dat, -b, -tcl, BATCHRUN_preview_pred_h3d.tcl, -input, <h3d>, -output, H3D_PREVIEW.json]`(:230-231), cwd PREDICT |
| ⑤ 최적화 체인(HyperStudy, `hst_physicsai_optimization_core` pyd) | m_1 SimLab `SimLab.bat -auto <렌더 .py> -nographics` · m_2 HyperMesh `hw.exe -clientconfig hwfepre.dat -b -tcl BATCHRUN_create_include_node_elem.tcl <EPS_mesh_0000.rad> <104_replace_node_elem.inc> <RENUM_INIT.csv>` · m_3 PhysicsAI(HST 내장) · m_4 HyperView TCL | HyperStudy run 폴더 | tpl → `EPS_mesh_0000.rad`(tpl:110) → include(번호 재지정, 기본 3000001) → `<stem>_pred.h3d/.xydata` | pyd 문자열("-auto ${filepath} -nographics", "-clientconfig hwfepre.dat -b -tcl", "104_replace_node_elem", "../RENUM_INIT.csv"), include TCL 해독: 인자 [simlab 출력, include 출력, csv], 로그 cwd `log_batch.txt`, 끝 표식 "COMPLETE HM BATCHRUN" |
| tpl 생성 `1_CREATE_TRAINING_DATA/FUNC/1_create_tpl_file.py:127-193` | — | — | `dir_file_prt = r"./<cad>"`(상대, :135-139), `NewValue="{var_i, %3i}"`(:168-173) | SimLab cwd에 CAD 사본 필요 |

미리보기 TCL 해독: 이미지 없음, JSON `{"h3d","num_time_step","subcases":[{"id","label","datatypes":[{"name","format","binding","components","layers"}]}]}`.

### 11.2 미확정 항목 결론

| # | 결론 | 서버 1회 확인(E4-0) |
|---|---|---|
| U2 | **확정**. 렌더 = `<tpl stem>.py`(`simlab_parametered_mesh.py`), `SimLab.bat -auto <py> -nographics`, cwd = CAD 사본 폴더, 형상 갱신·메싱·내보내기 1회(tpl:43-169) | SimLab 성공 시 rc 메모(판정은 출력 파일 기준) |
| U3 | **원본 근거 확정, 이름은 서버 확인**. 새 메시 = HyperMesh TCL이 `EPS_mesh_0000.rad` → `104_replace_node_elem.inc`(번호는 조립 폴더 `RENUM_INIT.csv`). starter는 이 include를 `#include`, 조립 폴더에 기준본 존재 | E4-0-2. 다르면 `predict.mesh_include_name`·`commands.mesh`만 교체 |
| U4 | **해소**. 이미지 없음 | — |
| U7 | **확정**. pscfg 불필요(5_predict.py:55-66, opti:310-316) | — |
| U9 | 미확정(HyperStudy Templex 내부) | E4-0-6 |

### 11.3 원본 대비 차이와 조치

| 순위 | 현재 플랫폼 | 원본 | 조치 |
|---|---|---|---|
| P1-a | RAD_ASSEMBLE이 `geom/eps_mesh*`를 INPUT으로 복사 → `EPS_mesh_0000.rad`가 `*_0000.rad`에 걸려 starter 2개 → INPUT_INVALID | 복사·starter 모두 eps_mesh 제외 | eps_mesh 복사 폐지, starter 셈에서 제외(대소문자 무시) |
| P1-b | MESH 기본 null → 새 메시가 starter에 연결 안 됨 → 기준 메시로 예측(조용한 오답) | m_2 include 변환 후 교체 | MESH = 원본 m_2, RAD_ASSEMBLE이 새 include로 교체, 없으면 실패 |
| P1-c | 폴더 등록이 `EPS_mesh_0000.rad`를 starter로 셈, `RENUM_INIT.csv` 미복사 | 조립 폴더에 둘 다 있음 | §15.4 갱신 |
| P2 | GEOM_UPDATE 성공 = rc 0, 출력 미확인 | SimLab rc 무시(1_create_tpl_file.py:76-93) | 출력 파일 기준 판정 |
| P2 | 가짜 SimLab이 `eps_mesh_1.inc`, 시험 starter가 그것을 include | 실제 `EPS_mesh_0000.rad`/`104_replace_node_elem.inc` | 가짜 도구·시험 데이터 실제화 |
| P3 | 가짜 hw 미리보기 JSON `{subcases:[{name}]}` | §11.1 형식 | 가짜 도구 수정(화면 파서는 두 형식 모두 수용) |
| — | 원본 단독 예측 없음 | 있음 | §11.5 |

### 11.4 parametric(기존 체인) 보정 — platform.md §8.9 대체

| step | 변경 후 |
|---|---|
| TPL_RENDER | 그대로. 출력 `P/geom/{predict.rendered_script_name}` |
| GEOM_UPDATE | 템플릿 그대로, cwd `P/geom`. **성공 = `P/geom/{predict.simlab_mesh_name}`(기본 `EPS_mesh_0000.rad`) 존재·크기>0**. rc≠0 + 출력 있음 → 성공 + 경고 `EXIT_NONZERO_IGNORED`. 출력 없음 → `OUTPUT_MISSING`(rc≠0이면 `EXIT_NONZERO`) |
| MESH | 원본 m_2. 템플릿 `mesh` 기본 `["{hw}","-clientconfig","hwfepre.dat","-b","-tcl","{include_tcl}","{simlab_mesh}","{mesh_inc}","{renum_csv}"]`, cwd `P/geom`. `{include_tcl}`=`resources.hypermesh_include_tcl`, `{simlab_mesh}`=`P/geom/{simlab_mesh_name}`, `{mesh_inc}`=`P/geom/{predict.mesh_include_name}`, `{renum_csv}`=`S/radioss_assem/{predict.renum_csv_name}`(없어도 경로 전달, 경고 `RENUM_CSV_MISSING`). 성공 = `{mesh_inc}` 존재·크기>0(rc 규칙은 GEOM_UPDATE와 같음). `P/geom/log_batch.txt`를 step 로그에 덧붙이고 `predict.mesh_log_complete_marker` 없으면 경고 `MESH_LOG_INCOMPLETE`. 템플릿 null → SKIPPED(SimLab이 include를 직접 쓰는 변형) |
| RAD_ASSEMBLE | ① `S/radioss_assem/` 직계 `*.rad`·`*.inc` 중 `eps_mesh`로 시작하지 않고 `{mesh_include_name}`(대소문자 무시)이 아닌 것 → `P/INPUT/`. ② `P/geom/{mesh_include_name}` → `P/INPUT/`(MESH가 SKIPPED면 SimLab cwd에서 같은 이름을 찾음). **없으면 `OUTPUT_MISSING` "새 메시 include(…)가 없습니다"**. ③ starter = `starter_glob` 일치·eps_mesh 아님 정확히 1개. ④ 조립 폴더에 include 기준본이 없었으면 경고 `MESH_INCLUDE_NOT_IN_ASSEM`. ⑤ `rad_assemble` 템플릿 그대로(선택). `predict.mesh_output_glob` 폐지 |
| EDSPY_PREDICT 이후 | 그대로(원본 opti:306-340), pscfg 미전달 |

§9.2 `mesh` 허용 placeholder = `{hw} {simlab} {include_tcl} {simlab_mesh} {mesh_inc} {renum_csv} {work_dir} {rendered_script} {cad_file}`. `mesh`가 `{include_tcl}`을 쓰는데 `resources.hypermesh_include_tcl`이 비었거나 `geom_update` null이면 `features.predict_parametric=false` + `config.warnings`. parametric 작업 생성 시 `predict_parametric=false`면 409 `TEMPLATE_NOT_CONFIGURED`. `features.predict`(edspy_predict·contour_preview)는 prepared 모드 조건.

§15.4 `radioss_assem/`: 직계 `*.rad`·`*.inc`·`{renum_csv_name}`. `eps_mesh`로 시작하는 파일은 **무시**(starter로 세지 않고 복사 안 함). `RENUM_INIT.csv`가 있으면 복사(없어도 등록 성공). include 기준본이 없으면 등록 성공, ④ 실행 시 경고. `from-train`도 csv 복사.

### 11.5 준비된 입력 예측(`input_mode: "prepared"`)

원본 ③ 단독 예측 + ⑤ 기준 Predict 동작: 사용자가 준비한 Radioss starter(또는 `.hm`)로 Final(또는 지정) 모델 예측 → 미리보기·커브·(가능하면) 응답 표.

params(§10.6 PREDICT 대체):
```jsonc
// parametric(기본, input_mode 생략 시 = 기존 호환)
{"input_mode":"parametric","param_set_id":null,"model_id":null,"values":{"THK_1":4.0},"value_source":"manual","source_run_key":null,"input_path":null}
// prepared
{"input_mode":"prepared","input_path":"E:/…/case_A/Face_Drop_0000.rad","model_id":null,"param_set_id":null}
```
- 검증(422 `INVALID_PARAMS`): parametric → `value_source` 필수·`input_path` 금지. prepared → `input_path` 필수, `values` 비어 있음, `value_source`·`source_run_key` null.
- `input_path`: `check_user_path`, 허용 루트 = `allowed_roots(imports=True)`. 공백·cmd 메타문자·링크·`_backup`·`_platform` 거부(`PATH_OUTSIDE_ROOT`/`PATH_UNSAFE`/`PATH_NOT_FOUND`). 파일이면 확장자 ∈ `predict.prepared_input_exts`(기본 `[".rad",".hm"]`), starter = 그 파일(eps_mesh 파일이어도). 폴더면 직계 `starter_glob` 일치 파일 중 — 1개면 그것, 여러 개면 `eps_mesh`로 시작하지 않는 것이 정확히 1개일 때 그것, 아니면 `STARTER_COUNT`(메시지에 후보 목록, D3-44).
- 복사 대상: `.rad` 파일 또는 폴더 → 그 폴더 직계 `*.rad`·`*.inc` **전부**(eps_mesh 포함 — starter가 `eps_mesh*.inc`를 include할 수 있음, 하위 폴더 무시, D3-44). `.hm` → 그 파일만. eps_mesh 제외는 parametric(§11.4, 조립 폴더의 이전 형상 메시)에만 적용. 각 파일명 `file_safety_problem` 통과, 개수 ≤ `predict.prepared_max_files`(500), 합계 ≤ `predict.prepared_max_total_bytes`(2 GiB).
- 위반 → 422 `PREDICT_INPUT_INVALID` "준비된 입력을 쓸 수 없습니다" + `problems:[{code,message}]`, code ∈ `INPUT_EXT`·`STARTER_COUNT`·`FILE_NAME_UNSAFE`·`TOO_MANY_FILES`·`TOO_LARGE`.
- 사전조건: ACTIVE 모델(기본 Final, 없으면 409 `FINAL_MODEL_REQUIRED`), `features.predict`. **파라미터 세트 불필요**: 지정 시 존재해야 함(409 `PREREQUISITE_MISSING` PARAM_SET), 미지정이면 현재 세트를 응답 목록용으로만 사용.
- 저장 params: `{input_mode, input_path(정규화), input_kind:"file"|"dir", starter_name, model_id, param_set_id|null}`.

step 동작(체인·step 수 불변, migration 없음):

| step | prepared |
|---|---|
| PR_PREP | 모델 sha256 확인, `input_path` 재검사(바뀌면 `INPUT_CHANGED`), `P/params.json`. result `{model_id, param_set_id, input_mode, input_path, values:{}, applied_values:{}, out_of_range:[], nearest:null}` |
| TPL_RENDER·GEOM_UPDATE·MESH | SKIPPED "준비된 입력 — 해당 없음" |
| RAD_ASSEMBLE | 복사 대상 → `P/INPUT/`(원본 읽기만). starter = 지정 파일 또는 폴더 규칙. `rad_assemble` 미실행. result `starter` |
| EDSPY_PREDICT·CONTOUR_PREVIEW·CURVE_PICK | 그대로 |
| RESPONSE_EXTRACT | 세트에 responses + 템플릿 있으면 실행, 아니면 SKIPPED |
| RESPONSE_TABLE | 세트에 responses 있으면 행 = responses, `nearest_measured`·`diff_pct` null. 없으면 SKIPPED, `response_table=[]` |

PREDICT_VERIFY·input.zip·정리·재시도는 `P/INPUT` 기준이라 그대로.

API: `POST /studies/{id}/paths/inspect`에 `purpose:"PREDICT_INPUT"`(파일·폴더) → `{kind, starter:[names], starter_ok, rad:[≤50], inc_count, file_count, total_bytes, subdir_count, starter_hints:[≤10], problems:[{code,message}]}`(`subdir_count`는 D3-43, `starter_hints`는 D3-44 — 폴더 직계 starter 0개일 때 1단계 하위 폴더의 `starter_glob` 일치 파일 상대경로, 읽기만·복사·실행에 안 씀). `/status` `features.predict_parametric`. `backend/openapi.json` 갱신.

화면(최소 UI): ④ 맨 위 "입력 방식" 토글 1개 — `파라미터로 형상 생성`(기본) / `준비된 입력 파일`(선택은 localStorage `physicsai.stage4.inputMode`, try/catch). 준비된 입력에서는 파라미터 세트 카드·입력 표를 숨기고 카드 1개: 경로 입력 + "확인"(요약 한 줄 "✓ starter <이름> · rad N · inc M"(starter 정상일 때 ✓), 문제는 회색 문구, 하위 폴더가 있을 때만 회색 참고 문구 — D3-43, starter 0개 + `starter_hints`면 "하위 폴더에 starter 후보가 있습니다: case1\\xxx_0000.rad — 그 폴더나 파일 경로를 입력하세요"(후보 클릭 → 입력란을 그 파일 절대경로로) — D3-44) / 모델(기본 Final) / "예측 실행" + "PBS 검증 해석"(기존 규칙). 결과는 기존 컴포넌트 재사용. 파라미터 세트가 없어도 토글·카드 표시. `predict_parametric=false`면 첫 선택지 비활성 + 툴팁 "형상 갱신 설정 필요(관리자)".

### 11.6 시험·Verifier(V3-S6-*)

| ID | 기준 |
|---|---|
| V3-S6-1 | parametric 골든 argv·cwd: GEOM_UPDATE `[simlab,-auto,P/geom/simlab_parametered_mesh.py,-nographics]`, MESH `[hw,-clientconfig,hwfepre.dat,-b,-tcl,<tcl>,P/geom/EPS_mesh_0000.rad,P/geom/104_replace_node_elem.inc,S/radioss_assem/RENUM_INIT.csv]`, cwd 둘 다 `P/geom` |
| V3-S6-2 | INPUT에 starter·새 include(내용이 geom 산출물) 있고 `EPS_mesh*`(대소문자 변형 포함) 없음, starter 1개 |
| V3-S6-3 | 새 include 없음 → RAD_ASSEMBLE `OUTPUT_MISSING`. MESH null + SimLab이 include 직접 작성 → 성공 |
| V3-S6-4 | rc≠0 + 출력 → 성공 + `EXIT_NONZERO_IGNORED`. rc 0 + 출력 없음 → `OUTPUT_MISSING` |
| V3-S6-5 | csv 없음 → `RENUM_CSV_MISSING`, 로그 표식 없음 → `MESH_LOG_INCOMPLETE` |
| V3-S6-6 | 폴더 등록: `EPS_mesh_0000.rad` 있어도 starter 1개로 성공, csv 복사. from-train도 csv 복사 |
| V3-S6-7 | prepared 파일·폴더·`.hm`: 복사 규칙, step 2~4 SKIPPED, edspy `--input-file P/INPUT/<starter>`, 미리보기·커브. 원본 폴더 목록·mtime 불변 |
| V3-S6-8 | prepared 응답 표: 세트 없음 → SKIPPED·`[]`; 세트+response_extract → predicted만, nearest null |
| V3-S6-9 | 경로 거부(루트 밖·공백·메타문자·`_backup`·링크), allowed_import_roots 허용, 파일명 메타문자, starter 0/2개, 크기 한도 |
| V3-S6-10 | params 조합 검증, input_mode 생략 = parametric(기존 시험 무수정 통과), prepared는 geom_update null·세트 없음에서도 생성 |
| V3-S6-11 | prepared → PREDICT_VERIFY·input.zip·재시도(RAD_ASSEMBLE부터) 동작 |
| V3-S6-12 | inspect `PREDICT_INPUT` 응답 모양, openapi·타입 재생성 일치 |
| V3-S6-13 | 화면: 토글 유지, prepared 요청 body, 세트 없이 카드, parametric 회귀 없음, `predict_parametric=false` 비활성 |
| V3-S6-14 | 가짜 도구 실제 형식: fake_simlab은 렌더 스크립트의 `dir_file_export`(기본 `EPS_mesh_0000.rad`)를 cwd에 작성, 상대 CAD 없으면 rc 2(모드 `nonzero_with_output` 추가). fake_hw HyperMesh 형태(`-clientconfig hwfepre.dat -b -tcl X a b c`)는 a 확인 후 b와 cwd `log_batch.txt`("COMPLETE HM BATCHRUN") 작성(모드 `fail`·`no_output`·`no_marker`). 미리보기 JSON §11.1 형식 |

### 11.7 구현 분해(파일 소유 비중첩)

- **Impl-Backend**: `backend/physicsai_api/services/job_params/stage4_predict.py`, `services/path_inspect.py`, `services/stage4_predict.py`, `physicsai_core/commands.py`, `physicsai_core/features.py`, `physicsai_core/config/{schema_stages.py,validate.py}`, `physicsai_core/stage4_predict/param_sets.py`, 신규 `physicsai_core/stage4_predict/prepared_input.py`(`plan_copy(path, settings) -> (kind, starter, files[], problems[])`, API·워커 공용), `backend/openapi.json`, `config/platform.example.yaml`, `backend/tests/support_inputs.py`, backend 시험(V3-S6-6·9·10·12).
- **Impl-Worker**: `worker/physicsai_worker/steps/stage4_predict/predict.py`(300줄 넘으면 `predict_inputs.py` 분리), `worker/physicsai_worker/step_process.py`(`allow_nonzero_exit`), `backend/tests/fake_tools/{fake_simlab,fake_hw}`, `worker/tests/e2e/test_e2e_chain.py`, 신규 `worker/tests/stage4_predict/`(V3-S6-1~5·7·8·11·14).
- **Impl-Frontend**: `frontend/src/stages/stage4/{Stage4.tsx, PreparedPredictCard.tsx(신규), PredictResult.tsx}`, `frontend/src/mock/{jobs.ts, stage4Prepared.ts(신규)}`, 타입 재생성, 시험(V3-S6-13).

### 11.8 설정 기본값(`config/platform.example.yaml`)

```yaml
predict:
  rendered_script_name: simlab_parametered_mesh.py   # U2 확정
  simlab_mesh_name: EPS_mesh_0000.rad                # 원본 tpl:110 dir_file_export
  mesh_include_name: 104_replace_node_elem.inc       # 원본 m_2 출력(U3) — E4-0-2 확인
  renum_csv_name: RENUM_INIT.csv
  mesh_log_complete_marker: "COMPLETE HM BATCHRUN"
  starter_glob: "*_0000.rad"
  prepared_input_exts: [".rad", ".hm"]
  prepared_max_files: 500
  prepared_max_total_bytes: 2147483648
commands:
  geom_update: ["{simlab}", "-auto", "{rendered_script}", "-nographics"]
  mesh: ["{hw}", "-clientconfig", "hwfepre.dat", "-b", "-tcl", "{include_tcl}", "{simlab_mesh}", "{mesh_inc}", "{renum_csv}"]
```
기존 설정의 `predict.mesh_output_glob`은 무시하고 `config.warnings`에 "폐지" 표시(오류 아님). `deploy/setup_config.py` 병합 시 사용자가 바꾸지 않은 이전 기본값(`mesh: null`, `mesh_output_glob`)은 새 기본으로 갱신.

### 11.9 리스크

| # | 내용 | 대응 |
|---|---|---|
| U3-6 | include 이름·csv 위치가 pyd 문자열 조각 근거 | E4-0-2, 설정값만 교체 |
| U3-7 | SimLab·hw rc 의미 미확인 | 출력 파일 기준 판정 |
| U3-8 | prepared 입력이 하위 폴더·절대경로를 include하면 복사본에서 깨짐(원본도 직계만) | 확인 화면 "직계 파일만 복사" 문구 |
| U3-9 | 원본 ⑤ m_3는 HST 내장 PhysicsAI라 edspy CLI와 미세 차이 가능 | 시연 영향 없음 |


## 12. S7 서버 경로 탐색 (2026-10-16, D3-46)

- API(읽기 전용, 이름·종류·크기·mtime만 — 파일 내용·업로드·쓰기 없음): `GET /fs/roots` → `{roots:[{key,label,path}], inbox_share_hint}`(`ai_root`·`inbox`(폴더가 있고 경로 규칙 통과 시만, AI 루트 하위 바로가기)·`import_<i>`(`allowed_import_roots`)). `GET /fs/list?path=&exts=` → `{path, parent, entries:[{name,type:"dir"|"file",size?,mtime}], truncated}`.
- 권한: 어느 프로젝트든 power 이상 또는 전역 관리자(아니면 403 `PERMISSION_DENIED`, `required:"power"`). 로그에는 경로·항목 수만.
- 검증: `check_user_path(path, allowed_roots(imports=True), expect="dir")` + UNC 거부(`PATH_UNSAFE`). 링크·junction·숨김/시스템 속성·`.`으로 시작·`_backup`·`_platform`(대소문자 무시) 제외, 폴더 먼저·이름순, 최대 500개(`truncated`). `exts`는 `.rad,.inc` 형식 ≤20개(아니면 422 `INVALID_PARAMS`), 파일에만 적용. 허용 루트 자체면 `parent=null`. 읽기 실패 422 `PATH_UNREADABLE`.
- 설정: `storage.inbox_dir`(기본 `inbox`, AI 루트 기준 상대 — 절대경로·공백·`..`·`_backup`·`_platform` 불가), `storage.inbox_share_hint`(화면 안내용 공유 경로, 표시만·≤260자).
- 화면: `PathPickerDialog`·`BrowseButton`. `PathInput`이 용도별(`BROWSE_OF`)로 "찾아보기"를 자동 부착(AI 루트만 허용하는 용도는 `aiOnly` — 추가 허용 폴더 숨김). 처음 위치 = 입력란 값(또는 그 폴더) → 마지막 위치(localStorage) → 받은 파일 → 첫 루트. ④ 준비된 입력·파라미터 세트 discover 입력란도 같은 버튼(discover는 imports=True라 `aiOnly` 아님).
- 배포: `setup_config.py write`가 `<ai_root>/<inbox_dir>`를 없으면 만든다. `setup.ps1`·`update-repo.ps1`이 `Get-SmbShare`로 조회만(관리자 권한 없이, 실패 시 빈 목록) 해 Path가 inbox인 공유를 `\\<COMPUTERNAME>\<공유>`로 `inbox_share_hint`에 채운다(비어 있을 때만 — 사용자 값 보존). 공유 생성은 관리자 1회 작업(admin.md "공유 폴더 설정").

## 13. S8 파라미터 세트 자동 구성 (2026-10-16, D3-47)

- API: `POST /studies/{id}/param-sets/discover {path, tpl?}`(power, 허용 루트 `imports=True`, 읽기만·워커 없음) → tpl·CAD·조립 폴더 후보, `selected_tpl`, parameters(파일 또는 tpl에서 생성)·samples/responses, `problems`·`notes`. 등록은 `POST /studies/{id}/param-sets {mode:"discover", path, choice:{tpl,cad,radioss_assem}, label}` — 후보가 1개면 choice 생략 가능.
- 탐색 규칙: 링크·숨김·`_backup`·`_platform`·HyperStudy run 폴더(`train_data.result_run_dir_regex`) 제외, `param_set.discover_max_depth`(4)·`discover_max_entries`(5000, 넘으면 `SCAN_TRUNCATED`)·`discover_tpl_max_bytes`(1 MiB). tpl = `{parameter(…)}` 블록이 있는 `*.tpl`(생성 tpl 이름 우선, `TEMAPLATE_`/`TEMPLATE_` 빈 틀은 마지막). CAD = tpl `dir_file_prt` 파일명(대소문자 무시, tpl 폴더 우선, 없으면 `cad_extensions`). 조립 폴더 = starter(`starter_glob`, eps_mesh 제외) 정확히 1개, eps_mesh·RENUM csv 동반 > 이름에 radioss/assem > 얕은 곳.
- 등록: 고른 후보를 §15.4 구조(tpl·`cad/`·parameters·`radioss_assem/`(eps_mesh 제외 `.rad`·`.inc`·RENUM csv))로 모아 기존 `validate_folder`·`write_normalized`로 `04_params/<id>`에 등록. 원본 위치는 읽기만. **등록 사본만** tpl의 CAD 경로를 `dir_file_prt = r"./<CAD 파일명>"`으로 다시 쓴다(원본 `1_create_tpl_file.py:135-139`와 같은 방식, 안내 `TPL_CAD_PATH_REWRITE`). 복사 총량 > `param_set.max_total_bytes`면 `PARAM_SET_TOO_LARGE`.
- 세트 이름: `param_sets.label`(≤120자, migration `0006_param_set_label`), 모든 등록 방식에서 지정, `PATCH /param-sets/{id} {label}`(감사 `PARAM_SET_UPDATE`). 화면 `ParamSetCard` "프로젝트 폴더에서 찾기"(기본)·이름 입력·이름 변경, `ParamSetDiscoverForm`(후보 여러 개면 드롭다운, 자동 선택 없음).

## 14. S9 템플릿 예측·DOE 일괄 예측 (Plan, 2026-10-16, D3-49)

목표: ④ 맨 위 "입력 방식" 3가지 — **템플릿 값 입력(A)** / **일괄 예측(DOE)(B)** / **준비된 입력 파일**(§11.5 그대로). 템플릿 = 이름 붙은 파라미터 세트(§13 `label`). 조립 폴더는 템플릿의 **선택 항목**이고, 없으면 m1 메시(`EPS_mesh_0000.rad`)를 그대로 예측 입력으로 쓴다(`input_kind: "mesh_only"`). B는 조합 N개를 만들어 run 폴더마다 입력을 동시 생성하고 하위 예측을 대기열 1슬롯으로 순서대로 돌려 비교 표·응답 그래프·커브 겹쳐보기를 만든다. 응답(Max stress 등) 추출을 원본 ⑤ m_4 방식으로 **기본 활성화**한다(§14.6, U8 해소). 시안: `docs/design/predict-ui/01_Main.png`~`04_BatchResult.png`. 1·2·3차 원칙(단일 슬롯 FIFO, 제한기, `shell=False`, 설정만, 원본·SPDM 읽기만, AI 루트만, `_backup`, 한국어, 필수 UI) 유지.

### 14.1 용어 대응표(원본 확인)

| 사용자 용어 | 원본 ① `hst_gen_radioss_core`(학습데이터) | 원본 ⑤ `hst_physicsai_optimization_core` | 플랫폼 A(PREDICT step) | 플랫폼 B(run 폴더) |
|---|---|---|---|---|
| m1 형상·메시 | `m_1` SimLab `-auto <렌더 .py> -nographics` → `EPS_mesh_0000.rad`(tpl:110 `dir_file_export`) | `m_1` 같음 | TPL_RENDER + GEOM_UPDATE(`P/geom`) | `run__N/m_1/` |
| m2 include 변환 | `m_2` HyperMesh `BATCHRUN_create_include_node_elem.tcl` → `104_replace_node_elem.inc`(+`log_batch.txt`) | `m_2` 같음 | MESH | `run__N/m_2/` |
| m3 조립 rad | `m_3` 조립 폴더 rad·inc + 새 include → starter `*_0000.rad`(진행 표식 `Finished run (k), model (m_3)` FUNC:59-61, fake_hstbatch `m_3/<starter>`) | **`m_3` = HST 내장 PhysicsAI 예측**, `m_4` = HyperView 응답 | RAD_ASSEMBLE(`P/INPUT`) | `run__N/m_3/` |
| 예측 | — | `m_3` | EDSPY_PREDICT 이후 | 하위 `PREDICT` 작업 |

사용자 m1~m3 = 원본 ① 정의와 같다. ⑤의 `m_3`(예측)와 이름이 겹치므로 화면·문서에서 "m3"는 항상 ① 의미(조립 rad)로 쓴다.

### 14.2 결정 요약

| # | 결정 | 근거 |
|---|---|---|
| K1 | 템플릿 = `param_sets` 행(새 엔터티 없음). `input_kind` 열 추가, `assem_rel`·`starter_name` NULL 허용 | §13 label·discover 재사용 |
| K2 | mesh_only 체인: MESH **SKIPPED**, RAD_ASSEMBLE은 **복사만**(SKIPPED 아님) — `P/INPUT` 불변식(PREDICT_VERIFY·input.zip·재시도·정리) 유지 | §11.4·D3-36 |
| K3 | B 조합은 **플랫폼이 미리 계산**(LHS·표·① DOE) → 미리보기·DOE 번호 고정. 입력 생성은 **hstbatch 대신 플랫폼 동시 실행기**로 ①과 같은 m_1→m_2→m_3를 run 폴더마다 실행 | 원본 DOE 유형은 FullFact·FracFact·LHS·Sobol 4개(`DATA_doe_design_type.json`)뿐, pyd에 지정 행렬 입력 경로 없음 → CSV·① 재사용·미리보기 불가. 재사용: run 폴더 이름·`m_N` 배치, `train_data.max_multi_execution`, `hst_run_label` 진행 문구, §11.4 명령 템플릿·판정, `samples.csv` 형식 |
| K4 | B 작업 구성 = **부모 `PREDICT_BATCH`(입력 생성) + run별 하위 `PREDICT`(`input_mode:"prepared"`)** | 아래 비교 |
| K5 | 응답 정의 = 템플릿(`param_sets.responses[].spec`)에 ⑤ `OPTIMIZE.responses` 형식(H3D만) 재사용, 추출 = 원본 `H3D_StaticMinMax_to_CSV_FAST.tcl` 그대로 | 원본 ⑤ GUI:13-14 "RESPONSES → H3D_REQUESTS.txt → m_4에서 TCL이 값 추출" |
| K6 | B 오른쪽 칸 = 컨투어 대신 **응답 그래프**(변수 1개 → 2D 점+선, 2개 → 3D) + **커브 겹쳐보기** | 사용자 결정 2026-10-16(컨투어 이미지 없음, U4) |

| 관점 | 부모 + 하위 PREDICT(선택) | 단일 작업 내 반복 |
|---|---|---|
| 대기열 | 생성만 슬롯 점유, 하위는 연속 `queue_seq`로 FIFO 합류 — 대기열 화면에 "대기 12" 그대로 보임 | 35분+ 슬롯 독점, 내부 진행만 보임 |
| 취소 | 배치 취소 = 부모 + 비종료 하위 일괄(API 1개), 행 1개만 취소도 기존 API | 전체 아니면 불가 |
| 재시도 | 기존 `/jobs/{id}/retry`가 run 단위로 동작(RAD_ASSEMBLE부터), "실패만 다시" = 반복 호출 | 실패 run 선별 재실행 로직 새로 필요 |
| 알림 | 하위 알림 억제 + 배치 완료 1건(새 이벤트) | 1건(자연) |
| 재사용 | 결과 화면·컨투어·커브·PBS 검증(`predict_job_id`)·input.zip·오류 묶음·정리 범주 무수정 | 전부 run 차원으로 재작성 |

### 14.3 데이터 모델 — migration `0007_predict_batch`(head 0006 → 0007, `MIGRATION_HEAD` 갱신)

- `param_sets`: `input_kind VARCHAR(16) NOT NULL DEFAULT 'assembly'` CHECK `('mesh_only','assembly')`(기존 행 = assembly), `assem_rel`·`starter_name` NULL 허용(CHECK: assembly ⇒ 둘 다 NOT NULL).
- `predict_batches`: `id PK, study_id FK, batch_no INT`(Study별 1부터, UNIQUE(study_id,batch_no), 표시 `B-003`), `job_id FK jobs`(최신 부모), `param_set_id FK, model_id FK, input_kind, source_kind`(`LHS`|`TABLE`|`TRAIN_DOE`), `source_meta JSONB`(LHS `{count,seed,ranges}`·TABLE `{row_count}`·TRAIN_DOE `{doe_id}` — 표 본문 저장 안 함), `multi_execution INT, run_count INT, dir_rel`(`04_batch/B-003`), `status`(`GENERATING`|`PREDICTING`|`DONE`|`FAILED`|`CANCELED`), `created_by, created_by_name, created_at, finished_at`.
- `predict_batch_runs`: PK(`batch_id, doe_no`), `run_key`(UNIQUE per batch), `values JSONB`(입력), `applied_values JSONB`(정수 반영), `out_of_range JSONB`(이름 목록), `gen_state`(`PENDING`|`RUNNING`|`DONE`|`FAILED`), `gen_code, gen_message`, `input_rel`(assembly `run__N/m_3`, mesh_only `run__N/m_1/<simlab_mesh_name>`), `predict_job_id FK jobs NULL`(재시도 시 새 작업으로 갱신), `responses JSONB NULL`(`{name: 예측값}` — 하위 종료 시 복사, 수치만).
- `notifications.ck_notifications_event`에 `'PREDICT_BATCH_DONE'` 추가.

폴더 `B = <study>/04_batch/B-003/`: `batch.json`(템플릿·모델·출처·행), `samples.csv`(`doe_no,run_key,<파라미터…>` 반영값 — 파일 이름이 모두 같으므로 **폴더 ↔ 번호 ↔ 값**을 디스크에도 남김), `run__00001/{m_1,m_2,m_3}/`. run_key = `run__{doe_no:05d}`, 단 TRAIN_DOE는 doe_no = ① run 번호(`run__00014` → 14, 폴더도 같은 이름).

### 14.4 A — 템플릿 등록·값 입력

- 등록(§13 확장): `choice.radioss_assem`을 **명시적 `null`** → mesh_only. 키 생략 시 후보 1개 → assembly, 0개 → mesh_only(+`notes` `MESH_ONLY` "조립 폴더 없음 — m1 메시로 바로 예측합니다"), 2개 이상 → 기존 422. 폴더 등록(`{path}`)도 `radioss_assem/` 없으면 mesh_only. from-train은 항상 assembly. tpl `dir_file_export` 값 ≠ `predict.simlab_mesh_name`이면 경고 `SIMLAB_EXPORT_NAME`(등록은 성공). 권한은 기존(power), 화면 문구만 "관리자가 등록".
- `ParamSet` 응답에 `input_kind`, `assem_rel|null`, `starter_name|null`. `/status` `features.predict_mesh_only` = `geom_update` 구성(include TCL 불필요). mesh_only 세트로 parametric 생성 시 이 값이 false면 409 `TEMPLATE_NOT_CONFIGURED`, assembly는 기존 `predict_parametric`.
- PREDICT params 불변(`param_set_id` = 고른 템플릿, 생략 시 현재 세트). 서버가 `input_kind`를 params에 확정 기록(B8). mesh_only step:

| step | mesh_only |
|---|---|
| PR_PREP·TPL_RENDER | 그대로(CAD → `P/geom`, 렌더 → `P/geom/simlab_parametered_mesh.py`) |
| GEOM_UPDATE | 그대로. 성공 = `P/geom/EPS_mesh_0000.rad` 존재·크기>0 |
| MESH | **SKIPPED** "쿠션 단독 템플릿 — 메시 연결 불필요"(`commands.mesh` 설정과 무관) |
| RAD_ASSEMBLE | `P/INPUT` 비우기(_backup, D3-36) → `P/geom` 직계 `*.rad`·`*.inc` → `P/INPUT`. starter = `{simlab_mesh_name}`(없으면 `OUTPUT_MISSING`). `rad_assemble` 미실행, csv 무관 |
| EDSPY_PREDICT | `[…, --predict-write, P/RESULT/EPS_mesh_0000_pred.h3d, --model, <psmdl>, --input-file, P/INPUT/EPS_mesh_0000.rad]`, cwd `P/INPUT`, env 그대로 |
| 이후 | 그대로 |

### 14.5 B — 일괄 예측

조합 계산(공용 `physicsai_core/stage4_predict/batch_matrix.py`, 미리보기·작업 생성·워커가 같은 결과):

| source.kind | 입력 | 규칙 |
|---|---|---|
| `lhs` | `count`(2~`predict_batch.max_runs`), `seed`(정수, 기본 1), `ranges{name:[lo,hi]}`(생략 = 세트 min·max) | `random.Random(seed)`: 파라미터마다 층 순열 `perm`, 값 = `lo + (perm[i] + u)/n·(hi−lo)`(u는 같은 RNG, 파라미터 순서 = 세트 순서). 정수 형식은 `predict.integer_rounding` → `applied_values`. `lo<hi` 유한, 학습 범위 밖 허용(`out_of_range`) |
| `table` | `text`(붙여넣기·CSV 내용, ≤ `predict_batch.table_max_bytes`) | 구분자 탭/쉼표 자동, BOM 허용, 첫 줄 헤더 = 파라미터 이름 전부(순서 무관, 선택 열 `doe`는 무시), 행 1~max_runs, doe_no = 행 순서 1.. |
| `train_doe` | `doe_id`(같은 Study, READY, `sample_status` PARSED/PARTIAL) | `samples.csv` 행 전부, 파라미터 이름 집합 = 템플릿 이름 집합(아니면 `DOE_PARAM_MISMATCH`), doe_no = run 번호 |

job_type `PREDICT_BATCH`(stage 4, SLOT, 표시 "일괄 예측 입력 생성", `notify_success=False`):

| step | kind | 처리 |
|---|---|---|
| BP_PREP | INTERNAL 3 | 모델·세트 sha256, `B` 생성, run마다 `m_1/`에 CAD 사본 + 렌더 스크립트(`tpl_render`, 반영값), `batch.json`·`samples.csv`. 재실행이면 `gen_state≠DONE` run 폴더만 `_backup` 후 다시 |
| BP_GEN | LOCAL 90 | 새 `run_parallel`: `gen_state≠DONE` run을 doe_no 순으로 최대 `multi_execution`개 동시. run마다 순차 m_1 GEOM_UPDATE(cwd `m_1`) → assembly면 m_2 MESH(`{simlab_mesh}`=`m_1/EPS_mesh_0000.rad`, `{mesh_inc}`=`m_2/<mesh_include_name>`, `{renum_csv}`=`S/radioss_assem/…`, cwd `m_2`) → m_3 조립(RAD_ASSEMBLE ①~④ 규칙, 대상 `m_3`). 판정·경고는 §11.4와 같음. 마지막에 `prepared_input.plan_copy(input_rel)`로 하위 입력 검사. run 실패 → `gen_state=FAILED`(code·message)·계속. 성공 0 → 첫 실패 코드로 FAILED, 일부 실패 → `PARTIAL_OUTPUT`. 진행 = 완료 수/N, 라벨 `hst_run_label` + " · 실패 F" |
| BP_ENQUEUE | INTERNAL 2 | `gen_state=DONE`이고 `predict_job_id` 없는 run마다 하위 `PREDICT`를 **한 트랜잭션에서 doe_no 순으로** 생성(QUEUED, 연속 queue_seq, created_by = 부모 등록자). params `{"input_mode":"prepared","input_path":"<B/run__N/m_3 또는 m_1/EPS_mesh_0000.rad 절대경로>","model_id","param_set_id","batch_run":{"batch_id","doe_no"}}`. 배치 `PREDICTING` |

- 동시 실행·제한기: `run_parallel`의 프로세스는 **같은 제한 그룹**(Windows Job Object 1개 — hstbatch `-multiexec`가 자식들을 한 Job에 담는 것과 같음)에 들어가 작업 1개 한도(CPU·메모리)를 나눠 쓴다. 취소·lease 상실 시 그룹 전체 종료. POSIX·null 제한기는 프로세스별 한도(메모리 = 한도/M).
- 하위 PREDICT: §11.5 prepared 그대로 + `batch_run`(API 생성 요청에 넣으면 422 `INVALID_PARAMS` — 워커만). PR_PREP이 `values`·`applied_values`·`out_of_range`를 run 행에서 채워 result에 기록(nearest null). 알림 `JOB_STARTED`·`JOB_SUCCEEDED`·`JOB_FAILED`·`MY_TURN_NEXT` 억제.
- 종료 훅(`job_end._side_effects_on_end`): 하위 종료 시 `responses` 복사, 배치의 모든 run이 종료(생성 실패 포함)면 `DONE` + `PREDICT_BATCH_DONE` 1건 "일괄 예측 B-003 완료 — 완료 18 · 실패 2". 하위 재시도(`on_retry`)는 `predict_job_id`를 새 작업으로 바꾸고 배치를 `PREDICTING`으로 되돌림. 부모 실패 → `FAILED`(기존 `JOB_FAILED` 알림), 부모 재시도 → `GENERATING`.
- 작업 목록: `JobSummary.batch: {id, label:"B-003", doe_no}|null`(params에서 계산).

### 14.6 응답 추출 활성화(원본 ⑤ m_4 방식, U8·U35 해소)

원본 TCL(tbcload, 리터럴 해독 결과): 스크립트 **자기 폴더**에서 `H3D_REQUESTS.txt`(UTF-8, `#` 줄 무시, 필드 `|` 구분)를 읽고, 같은 폴더의 `*_pred.h3d`(없으면 `*.h3d`) 전부를 HyperView로 열어 요청마다 subcase·datatype·component·layer 컨투어를 걸고 "Static MinMax Result" 측정으로 전 프레임 최소·최대를 읽어 `RESPONSES.txt`(머리 `# RESPONSES.txt generated …`, 값 줄 `RESP:<key>=%20.10e`, key = `<NAME>_MIN`·`<NAME>_MAX`, 실패 줄 `RESP:<NAME>=NO_VALUE|OPEN_ERROR|DATATYPE_ERR|HANDLE_ERR`)와 `RESPONSES.log`를 쓴다. 요청 줄 필드 순서는 로그 문구(`Request '<NAME>' : subcase= type= comp= layer=`)로 보아 `NAME|SUBCASE|DATATYPE|COMPONENT|LAYER`(E4-9-5 확인).

- 응답 정의(템플릿): `param_sets.responses = [{"name":"MaxStress","unit":"MPa","spec":{"source":"H3D","subcase":1,"datatype":"Stress","component":"vonMises","layer":"","stat":"MAX"}}]`. 검증 = phase2 §6.12 RESPONSES 규칙의 H3D 부분(name 정규식·대소문자 무시 중복 금지·`|` 금지·stat `MAX|MIN|ABSMAX`, subcase ≥1), goal·bound 없음. component는 layer처럼 선택(없으면 "", 요청 줄 빈 필드 `NAME|1|CornerStress||`, D3-54). XYDATA는 후속. 정규화본 `04_params/<id>/responses.json`도 같은 내용으로 다시 쓴다(원자적, `original/` 불변). 기존 `resp:` 실측 열 이름은 지울 수 없음(422 `RESPONSE_IN_USE`).
- `commands.response_extract` **기본값** `["{hw}","-clientconfig","hwpost.dat","-b","-tcl","{extract_tcl}"]`(새 placeholder `{extract_tcl}`, 기존 placeholder 유지). 템플릿에 `{extract_tcl}`이 있으면 새 방식, 없으면 기존 방식(`{out_csv}` 직접 작성) 그대로. `features.predict_responses` = 템플릿 구성 + `resources.extract_minmax_tcl` 존재.
- RESPONSE_EXTRACT(새 방식): 응답 정의 없으면 SKIPPED. `P/RESULT/`에 TCL 사본(원본 ⑤처럼 작업 폴더로 복사, FUNC:360-366)·`H3D_REQUESTS.txt` 작성(이전 `RESPONSES.*`는 `_backup`), cwd `P/RESULT`(h3d는 `<stem>_pred.h3d` 1개). 성공 = `RESPONSES.txt` 존재. stat 적용: MAX = `_MAX`, MIN = `_MIN`, ABSMAX = max(|min|,|max|), 실패 줄·없음 = null + 경고 `RESPONSE_NO_VALUE`(이름·사유). 결과를 `P/responses_pred.csv`(`name,value`)로 써서 RESPONSE_TABLE은 무수정. `RESPONSES.log`는 step 로그에 덧붙임.
- PV_EXTRACT·①-6 `RESPONSE_EXTRACT_RUNS`도 같은 방식, 대상 폴더에 `*.h3d`가 정확히 1개일 때만(아니면 그 대상 SKIPPED + 경고 `RESP_H3D_AMBIGUOUS`).
- 화면(템플릿 관리, `ParamSetCard` 안 "응답" 절): 표(이름·subcase·datatype·component·layer·stat·단위) + "응답 추가"(콤보는 기존 `GET /studies/{id}/optimize/response-candidates` — 최근 성공 PREDICT의 `H3D_PREVIEW.json`; 없으면 회색 "예측을 한 번 실행하면 목록이 채워집니다" + 직접 입력) + 행 삭제 + "저장". 등록 직후에는 비어 있어도 된다(첫 예측 뒤 설정).

### 14.7 API(`backend/openapi.json` 갱신)

```jsonc
// 미리보기(동기, 워커 없음, member 이상) POST /studies/{id}/predict-batches/preview
{"param_set_id":"ps-1","source":{"kind":"lhs","count":20,"seed":1,"ranges":{"THK_1":[2.0,5.0]}}}
// → 200
{"input_kind":"assembly","count":20,"estimate_min":35,   // 최근 성공 PREDICT 5개 중앙값×N, 없으면 null
 "rows":[{"doe_no":1,"run_key":"run__00001","values":{"THK_1":2.31,"RIB_N":5.6},"applied_values":{"THK_1":2.31,"RIB_N":6},"out_of_range":[]}],
 "problems":[]}                                           // {code,message,row?}
// 생성: 기존 POST /studies/{id}/jobs (power)
{"job_type":"PREDICT_BATCH","params":{"param_set_id":"ps-1","model_id":null,"multi_execution":4,
 "source":{"kind":"table","text":"THK_1\tTHK_2\tRIB_H\tRIB_N\n3.0\t2.5\t1.2\t5\n"}}}
// → 201 Job, params에 batch_id·batch_no 확정 기록
// 조회 GET /studies/{id}/predict-batches → [{id,label,status,run_count,created_at,created_by_name}]
// GET /predict-batches/{bid}
{"id":"…","label":"B-003","status":"PREDICTING","dir":"E:\\…\\04_batch\\B-003","input_kind":"assembly",
 "param_set":{"id":"ps-1","label":"쿠션 v1"},"model":{"id":"m-2","name":"cushion_TNS v1"},"job_id":"…","multi_execution":4,
 "gen":{"total":20,"done":20,"failed":0,"running":0,"waiting":0},
 "predict":{"running":1,"queued":12,"succeeded":7,"failed":0,"canceled":0},
 "parameters":["THK_1","THK_2","RIB_H","RIB_N"],"responses":[{"name":"MaxStress","unit":"MPa"}],
 "rows":[{"doe_no":7,"run_key":"run__00007","folder":"E:\\…\\B-003\\run__00007","values":{…},"applied_values":{…},
          "out_of_range":[],"state":"SUCCEEDED","code":null,"message":null,"job_id":"…","responses":{"MaxStress":152.3}}]}
// state ∈ GEN_PENDING|GENERATING|GEN_FAILED|QUEUED|RUNNING|SUCCEEDED|FAILED|CANCELED (화면: 생성 대기·생성 중·생성 실패·예측 대기·실행 중·완료·실패·취소)
// GET /predict-batches/{bid}/table.csv → UTF-8 BOM, 헤더 doe_no,run_key,folder,<파라미터>,<응답>,state
// POST /predict-batches/{bid}/cancel (power, 등록자 또는 관리자) → 202 배치. 부모·비종료 하위 전부 취소, 멱등
// POST /predict-batches/{bid}/retry-failed (power) → 201 {"parent_job_id":…|null,"retried_job_ids":[…]}
//   생성 실패 run이 있으면 부모 PREDICT_BATCH 새 작업({"batch_id"}만), 실패·취소·중단 하위는 기존 retry
// GET /predict-batches/{bid}/curves?name=&max_points=500 → 완료 run의 curve.json에서 같은 이름 계열 1개씩
{"names":["Node 100 / X"],"name":"Node 100 / X","truncated":false,"downsampled":true,
 "series":[{"doe_no":7,"run_key":"run__00007","x":[…],"y":[…]}]}   // name 생략 = 첫 run의 첫 계열
// PUT /param-sets/{id}/responses (power, 감사 PARAM_SET_UPDATE) {"responses":[{name,unit,spec}]} → 200 ParamSet
```
커브 상한: run ≤ `predict_batch.curve_max_runs`(200, 넘으면 doe_no 앞쪽만 + `truncated`), 계열당 점 ≤ `max_points`(≤2000) — 구간별 최소·최대 보존 다운샘플.

오류: 422 `INVALID_PARAMS`(모양) · 422 `BATCH_SOURCE_INVALID` + `problems[{code,row?,message}]`(code ∈ `TABLE_HEADER`·`TABLE_VALUE`·`TEXT_TOO_LARGE`·`TOO_MANY_ROWS`·`TOO_FEW_ROWS`·`RANGE_INVALID`·`DOE_PARAM_MISMATCH`) · 409 `DOE_NOT_READY`·`SAMPLES_MISSING`(기존) · 409 `TEMPLATE_NOT_CONFIGURED` · 409 `FINAL_MODEL_REQUIRED` · 409 `PREREQUISITE_MISSING`(PARAM_SET) · 409 `BATCH_ACTIVE`(retry-failed 때 부모 진행 중) · 404 `BATCH_NOT_FOUND` · 422 `RESPONSE_INVALID` + problems · 422 `RESPONSE_IN_USE`. 워커 run 코드: `OUTPUT_MISSING`·`EXIT_NONZERO`·`RESOURCE_LIMIT`·`STARTER_COUNT`·`RESOURCE_MISSING`.

설정(`config/platform.example.yaml` 새 절): `predict_batch: {max_runs: 200, table_max_bytes: 1048576, dir_name: "04_batch", curve_max_runs: 200}`. 동시 수 상한은 `train_data.max_multi_execution` 재사용. `commands.response_extract` 기본값 변경은 `deploy/setup_config.py`가 사용자가 바꾸지 않은 이전 기본(null)일 때만 갱신(D3-33 방식).

### 14.8 화면 계약(시안 기준, 필수 UI만)

- **입력 방식**(01·03): 세그먼트 3개 `템플릿 값 입력`(기본)·`일괄 예측(DOE)`·`준비된 입력 파일` + 오른쪽 회색 한 줄 설명. localStorage `physicsai.stage4.inputMode` = `template|batch|prepared`(옛 값 `parametric` → `template`, try/catch). `predict_parametric`·`predict_mesh_only`가 모두 false면 앞 두 개 비활성 + 툴팁 "형상 갱신 설정 필요(관리자)".
- **A**(01): "형상 템플릿" 드롭다운 `<label> — <설명> N개 파라미터`, 옆 회색 `tpl · CAD · 조립 폴더 포함 · MM-DD 등록` 또는 `조립 폴더 없음(메시 단독)`. 표·참고 문구·공칭값·학습 run 불러오기·모델·"예측 실행"은 기존(§8.8). 오른쪽 **진행 4단**: 1 형상 생성(SimLab)=PR_PREP~GEOM_UPDATE · 2 메시 연결(HyperMesh)=MESH·RAD_ASSEMBLE(mesh_only면 "건너뜀") · 3 예측(PhysicsAI)=EDSPY_PREDICT · 4 결과 정리=나머지. 상태 문구 완료(소요)·실행 중·대기·실패.
- **템플릿 등록**(02): §13 `ParamSetDiscoverForm`의 조립 폴더 드롭다운 끝에 `(없음 — 쿠션 단독 메시로 예측)`. 후보 0개면 회색 "조립 폴더 없음 — 메시 단독 템플릿으로 등록됩니다".
- **B 설정**(03): ① 템플릿 + 조합 만들기 라디오 3개(범위·개수 LHS: 파라미터 최소·최대 표, 조합 수·시드, "조합 만들기" / 표 붙여넣기·CSV: 텍스트 영역 / ① 학습 DOE: READY DOE 드롭다운) → `preview`. ② 조합 미리보기 표(DOE #·입력 폴더·파라미터, 처음 20행 + "… N개 더", 범위 밖 값 옆 작은 회색 점, problems는 회색 줄). ③ 실행 방식 3칸 안내(고정 문구) + 동시 실행 수(1~`max_multi_execution`, 기본 `min(4, 상한)`) + 모델·예상 소요 + "입력 생성 + 일괄 예측 실행" 1개.
- **B 결과**(04, 라우트 `/studies/:id/stage4/batch/:batchId`): 위 3칸 — 입력 생성 `done / total`(동시 M · 소요 · 실패 F), 예측 `실행 중 · 대기 · 완료` + 막대(대기열 1슬롯), 파일 위치(`dir` + 고정 안내 "파일 이름은 모두 같고 폴더 번호로 구분합니다"). 결과 표: DOE # · 폴더 · 파라미터 · 응답 · 상태, 정렬 드롭다운(응답별 낮은/높은 순, DOE #), "CSV 받기", 진행 중 5초 폴링. 실패 행은 회색 사유 + `다시 실행`(기존 retry). 표 위 `실패만 다시 실행`(실패가 있을 때)·`일괄 취소`(진행 중일 때). 응답 정의 없음·`predict_responses=false`면 응답 열 대신 회색 "응답 추출 미구성".
- **B 오른쪽 칸**(04의 컨투어 자리 대체): ① **응답 그래프** — 결과 표 머리의 파라미터 열·응답 열 이름을 눌러 선택 표시(토글). 변수 1 + 응답 1 → 2D 점+선(x = 반영값, 점 = DOE run, x 정렬 선, 선택 run 강조, 점 클릭 = 행 선택, 자체 SVG). 변수 2 + 응답 1 → 3D(x·y = 변수, z = 응답 산점, 체크 "보간면"(기본 끔) = Delaunay 삼각면). 그 밖 조합 → 회색 "변수 1~2개와 응답 1개를 고르세요". WebGL이 없으면 "3D 그래프를 표시할 수 없습니다(WebGL 없음)". ② **커브 겹쳐보기** — `curves` API, 모든 run 선을 흐리게(불투명 0.25), 표·그래프에서 고른 run만 진하게, 계열 이름 드롭다운(여러 개일 때만). ③ 선택 run 머리 `DOE #N · run_key` + 버튼 `경로 복사`·`단일 예측으로 열기`(컨투어 결과 목록은 여기서)·`PBS 검증 해석`.
- 3D 라이브러리: **`plotly.js-gl3d-dist-min@2.35.2`**(npm 의존성, 정확 고정, 동적 import로 별도 청크 → `frontend-dist` 포함, CDN 없음). 비교: three.js는 축·눈금·라벨을 직접 구현해야 하고, echarts+echarts-gl은 두 패키지·용량이 더 크며 Delaunay 면이 없다 — plotly는 `scatter3d`+`mesh3d`(`delaunayaxis:"z"`)로 요구를 그대로 충족.

### 14.9 시험·Verifier(V3-S9-*)

| ID | 기준 |
|---|---|
| V3-S9-1 | 0007 up: 기존 세트 `assembly`, CHECK(assembly ⇒ assem·starter), 새 테이블·알림 이벤트, `MIGRATION_HEAD` |
| V3-S9-2 | 등록: 조립 0개 → mesh_only+`MESH_ONLY`, 명시 null, 후보 1개 생략 = assembly, 폴더 등록 무조립, from-train assembly, `SIMLAB_EXPORT_NAME` 경고 |
| V3-S9-3 | mesh_only 골든: GEOM_UPDATE argv·cwd, MESH SKIPPED(`commands.mesh` 있어도), INPUT = `{EPS_mesh_0000.rad}`, edspy `--input-file P/INPUT/EPS_mesh_0000.rad`·`--predict-write P/RESULT/EPS_mesh_0000_pred.h3d`·cwd `P/INPUT`, 재시도·input.zip·PREDICT_VERIFY 동작 |
| V3-S9-4 | assembly 회귀: V3-S6-1~14 무수정 통과, `features.predict_mesh_only` 조건 |
| V3-S9-5 | `batch_matrix` 골든: LHS(seed 1, n=4) 값 고정·층마다 1개·정수 반영·`out_of_range`, 표(탭·쉼표·BOM·열 순서·`doe` 열·행 번호 오류), train_doe(doe_no = run 번호, PARTIAL) |
| V3-S9-6 | 미리보기 행 = 작업 생성 후 `predict_batch_runs`(결정적), batch_no 연번·`B-003` 폴더 |
| V3-S9-7 | BP_GEN(가짜 도구): 관측 동시 수 ≤ M 이고 M≥2에서 2 이상, `run__N/m_1·m_2·m_3`·`samples.csv`·`batch.json`, mesh_only는 m_1만, 일부 실패 `PARTIAL_OUTPUT`·전부 실패 FAILED, 재실행은 실패 run만 |
| V3-S9-8 | 취소: BP_GEN 중 그룹 프로세스 전부 종료(잔존 없음)·`CANCELED`, 예측 중 대기 하위 `CANCELED`·실행 중 취소 요청, 멱등 |
| V3-S9-9 | BP_ENQUEUE: 하위가 doe_no 순 연속 queue_seq, params(`prepared`·`batch_run`·`input_path` ⊂ `B`), API의 `batch_run` 422 |
| V3-S9-10 | 알림: 하위 0건, 완료 1건(문구·수), 부모 실패 `JOB_FAILED` |
| V3-S9-11 | 종료 훅·재시도: `responses` 복사, 하위 retry → `predict_job_id` 갱신·`PREDICTING`, `retry-failed`(부모·하위·`BATCH_ACTIVE`) |
| V3-S9-12 | API: 행 짝(doe_no·run_key·folder·values·responses·state) 일치, CSV BOM·헤더, 권한(조회 member, 생성·취소 power), 404, openapi·타입 재생성 |
| V3-S9-13 | 제한기 그룹: Windows(가짜 kernel32) Job 1개에 N프로세스·한도 1배, POSIX 메모리 한도/M |
| V3-S9-14 | 화면: 입력 방식 3개·옛 값 이전, 템플릿 드롭다운·mesh_only 표시, 진행 4단(건너뜀), B 3방식 미리보기·실행 body, 결과 표 정렬·CSV·행 선택·버튼, 목 |
| V3-S9-15 | e2e(가짜 도구): mesh_only·assembly 각 3 run 배치 → 생성 → 하위 예측 3개 → DONE·표 |
| V3-S9-16 | 응답 추출: `H3D_REQUESTS.txt` 골든(필드 순서·`#` 머리), TCL 사본·cwd `P/RESULT`·argv, `RESPONSES.txt` 파싱(MAX·MIN·ABSMAX·NO_VALUE → null+경고), `responses_pred.csv`, 옛 `{out_csv}` 템플릿 호환, PV_EXTRACT h3d 2개 → SKIPPED. 가짜 hw 모드 `minmax`(요청 읽고 결정적 RESP 줄 작성) |
| V3-S9-17 | `PUT /param-sets/{id}/responses` 검증·`responses.json` 재작성·`RESPONSE_IN_USE`, 화면 응답 추가(후보 있음·없음) |
| V3-S9-18 | `curves` API: 계열 선택·run 상한·점 다운샘플(최소·최대 보존)·미완료 run 제외. 화면: 변수/응답 선택 조합별 2D·3D·경고, 선택 run 강조(표↔그래프↔커브), plotly 청크 분리·`frontend-dist` 포함 |

### 14.10 구현 분해(파일 소유 비중첩, 병렬 순서)

- **P0 Impl-Backend(선행 1커밋)**: `migrations/0007_predict_batch.py`, `db/tables/{model_data.py, predict_batch.py(신규), execution.py, __init__.py}`, `job_types.py`(`PREDICT_BATCH`), `stage4_predict/batch_matrix.py`(신규), `config/{schema_stages.py, schema_hpc.py, validate.py}`·`commands.py`(`{extract_tcl}`·기본값)·`config/platform.example.yaml`·`deploy/setup_config.py`, `db/repositories/predict_batches.py`(신규: 생성·행 갱신·하위 일괄 생성·완료 판정). 시험 V3-S9-1·5.
- **P1(P0 뒤 병렬)**
  - Impl-Backend(API): `services/job_params/stage4_predict.py`, `services/predict_batches.py`(신규), `routers/predict_batches.py`(신규), `schemas/stage4_predict.py`, `services/stage4_predict.py`·`stage4_predict/{param_discover.py, param_sets.py, param_set_files.py}`(mesh_only), `stage4_predict/responses.py`(신규: 응답 정의 검증·요청 줄 작성·`RESPONSES.txt` 파싱 — API·워커 공용), `routers/param_sets.py`(PUT responses), `features.py`, `db/repositories/{job_end.py, notifications.py, jobs.py}`(훅·억제·`JobSummary.batch`), `backend/openapi.json`, 시험 V3-S9-2·6·9(API 부분)·10·11·12·17·18(API).
  - Impl-Worker: `steps/stage4_predict/{batch.py(신규), predict_inputs.py, predict.py}`, `steps/__init__.py`(HANDLERS), `steps/common.py`(`hst_run_label` 이동, `doe_gen.py`는 재노출), `step_process.py`(`run_parallel`), `limiter/{base,windows_job,posix,null}.py`(그룹), `executor.py`(여러 프로세스 취소), `steps/stage4_predict/verify.py`·`steps/stage1_train_data/resp_extract.py`(새 응답 방식), `backend/tests/fake_tools/{fake_simlab,fake_hw}`(동시 실행 기록 `FAKE_TOOL_TRACE`, hw `minmax` 모드), 시험 V3-S9-3·7·8·9(워커)·13·15·16.
  - Impl-Frontend(목 먼저): `stages/stage4/{Stage4.tsx, InputModeTabs.tsx, TemplatePicker.tsx, PredictSteps.tsx}`(신규 3), `stages/stage4/batch/{BatchSetup.tsx, BatchPreview.tsx, BatchResult.tsx, batchTable.ts, ResponsePlot2D.tsx, ResponsePlot3D.tsx(plotly 동적 import), CurveOverlay.tsx}`(신규), `stages/stage4/ResponseDefs.tsx`(신규, 템플릿 응답 절), `components/ParamSetDiscoverForm.tsx`, 라우트, `package.json`(plotly 고정), `mock/predictBatch.ts`(신규)·`mock/jobs.ts`, 시험 V3-S9-14·17·18(화면), `frontend-dist`.
- **P2**: 프런트 타입 재생성(openapi 후) → e2e(V3-S9-15) → Verifier.

### 14.11 리스크·서버 1회 확인(E4-9)

| # | 내용 | 확인·대응 |
|---|---|---|
| E4-9-1 | **edspy가 SimLab 메시 `EPS_mesh_0000.rad`(제어 카드 없는 메시 단독)를 `--input-file`로 받는지** | 쿠션 단독 모델로 원본 ③ 단독 예측(`5_predict.py`)에 그 파일 지정 1회 → h3d 생성 확인. 실패면 mesh_only 보류(템플릿 등록은 유지, 409 안내) |
| E4-9-2 | SimLab·HyperMesh 배치 동시 M개(라이선스·같은 CAD 이름 다른 cwd) | M=2·4로 ① DOE(`-multiexec`)와 같은 조건 확인(E2-1-4·U21). 상한은 설정 |
| E4-9-3 | Job Object 하나에 SimLab.bat(cmd) 자식 포함 여부(BREAKAWAY) | 작업 관리자에서 그룹 CPU 한도 확인 |
| E4-9-4 | (선택) `hst_gen_radioss_core`가 지정 행렬 DOE를 받는지 | 받으면 생성기를 hstbatch로 바꾸는 후속 검토(계약 변경 필요) |
| E4-9-5 | 응답 TCL 실행 방식(`hw -clientconfig hwpost.dat -b -tcl`로 되는지)·`H3D_REQUESTS.txt` 필드 순서 | 원본 ⑤ DOE 1회 실행 후 run의 `m_4` 폴더에서 `H3D_REQUESTS.txt`·`RESPONSES.txt` 확인, 같은 파일로 플랫폼 명령 1회. 다르면 `commands.response_extract` 설정과 `responses.py` 필드 순서 상수 1곳(변경 메모) |
| R-1 | 응답은 템플릿에 정의해야 채워짐(첫 예측 뒤 설정) | 없으면 "응답 추출 미구성", 커브는 표시 |
| R-4 | 3D(WebGL) 미지원 PC·plotly 청크 용량(~1 MB gz 수준) | 동적 import(3D 고를 때만), 실패 문구 |
| R-2 | `04_batch/**`는 S3 정리 범주 밖(크기만 표시) | 4차 후보(§2.2와 같은 취급) |
| R-3 | N개 하위가 대기열을 길게 점유 | FIFO 원칙 유지, 관리자 대기열 이동(기존)으로 조정. `max_runs` 200 |

## 15. S10 컨투어 캡처 (사용자 결정 2026-10-16, D3-52)

목표: 예측(A 템플릿 값 입력·B 일괄 예측 하위·준비된 입력 모두)이 끝나면 **HyperView 배치로 방향별 컨투어 스크린샷(PNG)과 애니메이션 동영상**을 저장하고, 사용자가 목록에서 방향을 골라 보고 내려받는다. §14.2 K6(B 오른쪽 칸 컨투어 없음)은 그대로 두고, B 행에는 방향 목록(`media_views`)만 더한다. 1·2·3차 원칙(제한기, `shell=False`, 설정만, AI 루트만, `_backup`, 한국어) 유지.

### 15.1 TCL 리소스

- `resources/hyperview/contour_capture.tcl` = 사용자 제공 TCL(이슈 #2, HyperView 26.1 GUI·`hw -b -tcl` 확인). 동작은 그대로, 바꾼 곳 두 가지: (a) "사용자 설정" 블록 → `source [file join [file dirname [info script]] capture_settings.tcl]`, (b) 저장부 → `VIEWS` 반복(h3d는 한 번 열고 방향마다 `hwc view orientation $VIEW | view fit` → `<view>.png` → `<view>.<VID_EXT>`) + 끝에 `capture_result.txt` 작성 후 `exit`. 배치에서 멈추지 않게 2절 오류의 `return` 앞에도 결과 작성 + `exit`.
- `capture_settings.tcl`(작업마다 플랫폼 생성): `H3D_PATH OUTDIR FIELD DCOMP AVGMODE USE_LAST LEGMIN LEGMAX SAVE_VIDEO VID_EXT COMPS VIEWS`. 값은 Tcl 큰따옴표 리터럴(`\ " $ [ ] { } ;` 백슬래시, ASCII 밖 문자는 `\uXXXX` — 파일은 ASCII라 HyperView 시스템 인코딩과 무관), 경로는 `/` 표기.
- `capture_result.txt`(UTF-8): `# capture_result 1` / `STATUS=OK|SAVE_ERROR|OPEN_ERROR|HANDLE_ERROR` / `MESSAGE=…`(선택) / 방향마다 `VIEW=<view>|<image 1|0>|<view>.png|<video 1|0|->|<view>.<ext>|<오류>`.

### 15.2 실행(step `CONTOUR_CAPTURE`)

| 작업 | 위치 | cwd(= OUTDIR) | 실패 |
|---|---|---|---|
| `PREDICT` 맨 끝(LOCAL 8, 제한기 안) | `steps/stage4_predict/capture.py` | `P/RESULT/media/`(재실행이면 `_backup`) | **경고 `CAPTURE_FAILED`만**, 예측은 성공 |
| `CONTOUR_RECAPTURE`(LIGHT, 새 job_type, step 1개 LOCAL) | 같은 모듈 | `P/RESULT/media_recapture/<재캡처 작업 id>/` | 이미지 0개면 작업 실패 `CAPTURE_FAILED`, 일부면 경고 |

- 명령 `commands.contour_capture` 기본 `["{hw}","-clientconfig","hwpost.dat","-b","-tcl","{capture_tcl}"]`(새 placeholder `{capture_tcl}` = cwd에 복사한 TCL, `/` 표기). 설정 파일에 키가 없으면 이 기본값.
- 판정 = 방향별 `<view>.png` 존재·크기>0(동영상은 선택), `capture_result.txt`는 오류 문구용. 종료코드 무시(`allow_nonzero_exit`). `capture.timeout_s`를 넘으면 이 step이 프로세스 트리를 끝내고 "시간 초과"(공통 실행기에는 시간 한도 없음 — platform.md §8.4 유지).
- 미구성(`capture.enabled=false` 또는 템플릿 null) → SKIPPED, result `capture.status="SKIPPED"`. 실행 파일·TCL 없음·h3d 없음 → (PREDICT) 경고.
- 산출물: kind `CONTOUR_IMAGE`(image/png, 상한 `ui.max_artifact_bytes`)·`CONTOUR_VIDEO`(`video/mp4`·`video/x-msvideo`·`image/gif`, 상한 `capture.max_video_bytes`, 넘으면 경고 `CAPTURE_VIDEO_TOO_LARGE`·등록 안 함), `artifacts.meta = {"view"}`.
- result: `media: [{view, image_artifact_id, video_artifact_id|null}]`, `capture: {status OK|PARTIAL|FAILED|SKIPPED, views, display(최종), field_source, video, video_ext, dir_rel, message, failed_views}`. 재캡처는 원래 예측의 result를 고치지 않고 자기 result에 남긴다(조회 때 방향별 덮어쓰기).

### 15.3 표시 설정(display)

`{field, component, avgmode(""|simple|maximum|minimum|difference), comps[], legend:{mode:"auto"|"fixed", min, max}, views[]}` — 모든 키 선택. 결정 순서(뒤가 우선, 층이 field를 정하면 component도 그 층 값): config(`capture.default_field`, `capture.views`) → 템플릿 응답 정의 중 spec이 있는 첫 항목의 datatype/component → 템플릿 `param_sets.display`(`PUT /param-sets/{id}/display`) → B 배치 params `display`(배치 단위 범례 fixed로 run끼리 비교) → 예측 params `display`(A·준비된 입력, 선택) → 재캡처 요청. 마지막에 component가 비었고 field가 `capture.default_field`이면 `capture.default_component`(기본 vonMises, D3-54). 문자 검사: field·component·comps에 `" { } [ ] $ \ ;`·제어문자 금지, 64자 이내, fixed는 min<max.

### 15.4 API

```jsonc
// GET /jobs/{id}/media (로그인) — PREDICT만(아니면 404)
{"job_id":"j1","status":"OK","message":null,"field_source":"config","video_ext":"mp4",
 "display":{"field":"CornerStress","component":"vonMises","avgmode":"","comps":[],"legend":{"mode":"auto","min":null,"max":null},"views":["iso","front","top","right"]},
 "items":[{"view":"iso","label":"등각","job_id":"j1",
           "image":{"artifact_id":"a1","content_type":"image/png","size":2311,"url":"/physicsai/api/artifacts/a1/media","download_url":"/physicsai/api/artifacts/a1/media?download=true"},
           "video":{"artifact_id":"a2","content_type":"video/mp4","size":1048576,"url":"…/a2/media","download_url":"…/a2/media?download=true"}}],
 "recapture":null,"capture_enabled":true,"can_recapture":true}
// GET /artifacts/{aid}/media[?download=true] (로그인) — CONTOUR_* 만. Range(단일) → 206 + Content-Range, 범위 밖 416,
//   여러 범위 → 200 전체. Accept-Ranges: bytes, Content-Type 정확히, 상한 초과 413 ARTIFACT_TOO_LARGE
// POST /jobs/{id}/capture {views?, display?} (power) → 201 Job(CONTOUR_RECAPTURE). 409 PREREQUISITE_MISSING(SUCCEEDED_PREDICT·PREDICT_H3D)
//   · RECAPTURE_ACTIVE(같은 예측 진행 중) · CAPTURE_NOT_CONFIGURED{missing}
// PUT /param-sets/{id}/display {display|null} (power, 감사 PARAM_SET_UPDATE) → 200 ParamSet(+display)
// GET /predict-batches/{bid} 행에 media_views: ["iso", …]
```

### 15.5 설정·DB

- `capture: {enabled: true, views: [iso, front, top, right], video: true, video_ext: mp4, use_last: true, default_field: "CornerStress", default_component: "vonMises", timeout_s: 1800, max_video_bytes: 209715200, estimate_image_mb: 0.3, estimate_video_mb: 1, estimate_sec_per_view: 20, estimate_sec_per_video: 40}`(estimate_* = 일괄 예측 "캡처 예상" 가정값, `/status.capture.estimate`), `resources.contour_capture_tcl`(빈 값 = 저장소 리소스, `deploy/setup.ps1`이 git 폴더 경로로 채움), `features.contour_capture` = 템플릿 + `altair.hw_exe_path` + `capture.enabled` + TCL 파일.
- migration `0008_contour_capture`: artifacts kind CHECK + `meta JSONB`, `param_sets.display JSONB`, `ux_jobs_study_type_active`에서 CONTOUR_RECAPTURE 제외(예측마다 재캡처 — 같은 예측 중복은 409).

### 15.6 시험·서버 확인

시험(V3-S10): settings 생성(이스케이프·공백·한글 경로 → ASCII, 가짜 hw 왕복, tclsh 있으면 실제 TCL을 흉내 hwc로 실행), 골든 argv·cwd, 방향별 산출물·meta, 실패 모드(fail·open_error·one_fail·no_manifest·no_video)는 경고만, 시간 초과, 동영상 상한, 표시 설정 결정 순서, API Range(206·Content-Range·416)·413·권한(401·403), 재캡처(LIGHT·409·실패), B `media_views`·배치 범례. 가짜 hw 캡처 모드(`fake_hw_capture.py`, `FAKE_TOOL_MODE_CAPTURE`).
서버 1회 확인(E4-10): ① `hw -clientconfig hwpost.dat -b -tcl <media>/contour_capture.tcl`에서 `info script`가 경로를 돌려주는지(빈 값이면 cwd 기준이라 동작은 같음) ② 배치에서 `exit`로 HyperView가 끝나는지 ③ 방향마다 `save animation page` 뒤 프레임 되돌림·동영상 인코더(mp4) ④ 한글·공백이 든 h3d 경로 ⑤ 4방향 + 동영상 소요(기본 `timeout_s` 1800 적정성).

## 16. S11 SCX 잡 제출 (사용자 결정 2026-10-17, D3-57)

목표: ① `TD_SOLVE`와 ④ `PREDICT_VERIFY`가 새 HPC 게이트웨이 모드 `scx`로 Siemens Simcenter X(SCX)에 Radioss를 제출한다. 입력 폴더를 SCX 드라이브의 새 잡 폴더에 올리고(STAGE_IN) → 제출 → 상태 조회 → 결과를 드라이브에서 내려받아 기존 `result_dir`에 놓는다. 그 뒤 등록·추출 step은 그대로. 1·2·3차 원칙(설정만·하드코딩 없음, AI 루트만 쓰기, 삭제 없음, 한국어) 유지.

### 16.1 결정(사용자, 구속)

| # | 결정 | 계약 반영 |
|---|---|---|
| U1 | 토큰·계정은 **대시보드 SCX 연결을 같이 쓴다**("같이 써") | PhysicsAI는 어댑터를 import·실행하지 않는다. 대시보드가 유일한 어댑터 소유자이고 loopback 전용 "SCX relay" HTTP API를 연다 — 전체 계약 `docs/contracts/scx_relay.md`(대시보드 사본 `simdashboard/docs/features/scx-relay.md`). 이유: refresh token 회전 + 대시보드의 단일 프로세스 워커 잠금(`dashboard.lock`) — 같은 토큰으로 워커 두 개면 한쪽 토큰이 무효가 된다 |
| U2 | 드라이브 기준 `/Users/vd.dashboard`(공용 계정 홈) → `<프로젝트>/<잡 폴더>/`, 잡 폴더는 항상 새로, 삭제 없음 | §16.3. 기준은 설정 `hpc.scx.drive_base`(기본 `"~"` = 홈) |
| U3 | ①·④ 모두 `scx` 모드 | §16.4·§16.5 |

### 16.2 구성 요소

```
PhysicsAI 워커 ── HTTP(127.0.0.1, X-SCX-Relay-Key) ──▶ 대시보드 /internal/scx-relay/v1 ──▶ WorkerDriveGateway(단일) ──▶ SCX
  ScxHpcGateway(simdash_adapters.hpc.scx)                 mkdirs·files(대기열 경유)·list·files(다운로드)
  ScxRelayClient(표준 라이브러리 http.client만)            jobs/radioss·jobs/{id}·terminate·submissions/{rid}/resolve·health
```

- relay 엔드포인트(요약, 상세·오류 코드표는 scx_relay.md §5·§7): `GET /health`, `POST /mkdirs`(대기열 MKDIR, 멱등), `POST /files?dir&name`(스트리밍 본문 + `X-Content-SHA256` + `X-Request-Id` → 202 묶음, 대기열 MKDIR+FILE), `GET /batches/{id}`, `GET /list?path`, `GET /files?path&max_bytes`(스트리밍 다운로드 + `X-Content-SHA256`), `POST /jobs/radioss`(같은 `request_id` replay는 어댑터 재호출 없음), `GET /jobs/{id}`, `POST /jobs/{id}/terminate`, `POST /submissions/{rid}/resolve`.
- 업로드는 **대시보드 업로드 대기열 경유(비동기)**: 큰 `.rad`를 요청 스레드에 붙잡지 않고, 기존 재시도·`AUTH_REQUIRED` 일시정지·덮어쓰기 금지·관리 화면을 그대로 쓴다. PhysicsAI는 묶음 상태를 폴링한다.
- 다운로드는 **relay가 스트리밍하고 PhysicsAI가 자기 AI 루트 안에 쓴다**(relay는 PhysicsAI 폴더에 쓰지 않고, PhysicsAI는 대시보드 폴더를 읽지 않음 — 양쪽 경로 규칙 유지).
- 패키지 규칙 유지: `simdash_adapters`는 표준 라이브러리만 import(R3-8) → relay 클라이언트는 `http.client`(리다이렉트 따르지 않음, 시간 한도 필수).

### 16.3 드라이브 경로·이름

- 표기: 내부 값은 **공용 계정 홈 기준 상대 경로**(어댑터 `drive_root="~"` 관례, relay API 경로). 설정 `hpc.scx.drive_base`는 `"~"`(= 홈) 또는 `"~/<상대>"`만 허용 → 내부 기준 `""` 또는 `<상대>`. 화면·로그 표시는 `hpc.scx.home_display`(기본 `/Users/vd.dashboard`) + `/` + 상대 경로(표시 전용, 계산에 쓰지 않음).
- 잡 폴더 = `<기준>/<프로젝트>/<잡 이름>`:
  - 프로젝트 = Study 폴더 이름 `studies.folder_name`을 정규화: NFC → `[A-Za-z0-9_-]` 밖 문자는 `_` → `_` 연속은 하나로 → 앞뒤 `_`·`-` 제거 → 64자 자름 → 비면 `study`. Windows 예약 이름(`CON PRN AUX NUL COM1-9 LPT1-9`, 대소문자 무시)이면 앞에 `s_`. (현재 `folder_name` CHECK `^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$`이라 대부분 그대로.)
  - ① 잡 이름 `01_D-<NNN>_<run_key>_<ts>` 예 `cushion/01_D-003_run__00012_20261017T105700/`. `D-<NNN>` = 그 Study의 `train_does`를 `(created_at, id)` 순으로 센 1부터의 번호(3자리 0 채움, 1000 이상은 그대로).
  - ④ 잡 이름 `04_V-<NNN>_<ts>` 예 `cushion/04_V-007_20261017T105700/`. `V-<NNN>` = 그 Study의 `PREDICT_VERIFY` 작업을 `(created_at, id)` 순으로 센 이 작업의 번호.
  - `<ts>` = HPC_SUBMIT step 시작 시 워커 현지 시각 `%Y%m%dT%H%M%S`(한 작업의 run들은 같은 값).
  - 번호·시각은 HPC_SUBMIT에서 한 번 계산해 `hpc_jobs.remote_dir`에 고정(뒤에 다시 계산하지 않음).
- 검사: 프로젝트·잡 폴더 구간은 `^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$`, 파일 이름은 입력 파일 이름 그대로(§16.4 2번 규칙), 전체 ≤ 1024자. relay도 같은 규칙과 SPDM 루트 금지를 다시 검사한다(scx_relay.md §4).
- **항상 새 폴더**: 잡 폴더를 `list`(부모)로 확인해 이미 있으면 `_2`…`_9`를 붙이고, 그래도 있으면 step 실패 `SCX_REMOTE_DIR_EXISTS`. 기존 폴더를 재사용·덮어쓰지 않는다. 같은 작업 안 재요청은 멱등(`request_id`)이라 새 폴더를 만들지 않는다.
- **SPDM 마스터 루트 보호(P1, 예외 없음)**: 잡 폴더는 `SIMDASH_SCX_DRIVE_ROOT`와 같거나 그 안일 수 없다. PhysicsAI는 `/health`의 `forbidden_prefixes`로 미리 검사해(작업 실패 `SCX_PATH_NOT_ALLOWED`, 프로젝트 이름이 SPDM 루트 첫 구간과 같을 때 포함), relay가 최종 거부(403 `PATH_NOT_ALLOWED`). 이를 허용하는 설정은 두지 않는다.

### 16.4 흐름(step 키는 바꾸지 않음)

step 정의·작업 유형·재시도 시작 지점은 그대로다(`TS_PREP → HPC_SUBMIT → COLLECT → TS_REGISTER`, `PV_PREP → HPC_SUBMIT → COLLECT → PV_EXTRACT → PV_TABLE`). `scx` 모드에서 HPC_SUBMIT·COLLECT 안쪽만 달라진다(공통 헬퍼 `worker/physicsai_worker/steps/_scx.py`). 다른 모드(`none`·`command`)의 동작은 불변.

**HPC_SUBMIT — 단계 A: STAGE_IN (모든 run 먼저)**
1. `gw.health()` — `job_api=false` → 실패 `HPC_SUBMIT_FAILED` "대시보드 어댑터에 잡 API 없음(v0.3.0 이상 필요)", `writes_active=false` → "대시보드 드라이브 쓰기 꺼짐", 연결 실패 → `HPC_SUBMIT_FAILED`(UNAVAILABLE).
2. run마다(④는 1개) 입력 폴더 = ① `train_runs.input_rel`, ④ `V/input`. 올릴 파일 = **직속 정규 파일 중 `hpc.scx.stage_patterns`(기본 `["*.rad","*.inc","*.csv"]`) 일치**, 링크·reparse·`_backup` 제외, 하위 폴더는 올리지 않음(하위 폴더에 패턴 파일이 있으면 경고 `SCX_SUBDIR_SKIPPED`). 파일 이름 검사(제어문자·`/\:` 금지, ≤255자), 파일 크기 ≤ `/health.max_upload_bytes`, run 합계 ≤ `hpc.scx.max_stage_bytes`. 위반 → 실패 `INPUT_INVALID`.
3. `hpc_jobs` 행을 먼저 삽입: `state=SUBMITTING`, `gateway_mode="scx"`, `remote_dir`, `request_id = "pai-" + hpc_jobs.id`, `staged = {files:[{name,size,sha256}]}`. (①은 run 상태 바꾸지 않음.)
4. `POST /mkdirs`(잡 폴더) → 파일마다 `POST /files`(`X-Request-Id = <request_id>:f:<name>`) → 묶음이 모두 `DONE`일 때까지 `GET /batches`를 `hpc.scx.stage_poll_s`(기본 5) 간격으로 폴링(`ctx.checkpoint()`로 취소 반영, 진행률 = 끝난 바이트/전체). `PAUSED`(대시보드 재로그인 필요)는 로그 한 줄 남기고 계속 기다림. `hpc.scx.stage_timeout_s`(기본 7200) 초과 또는 `CONFLICT`·`FAILED`·`CANCELLED`·`PARTIAL` → 실패 `SCX_STAGE_IN_FAILED`(그 행 `FAILED`, 드라이브에 올라간 것은 그대로 둠 — 삭제 없음). STAGE_IN 실패는 **아직 아무것도 제출하지 않았으므로 취소할 것이 없다**.

**HPC_SUBMIT — 단계 B: 제출 (run 순서대로)**
5. 요청: `input_path = <잡 폴더>/<starter>`(① `train_runs.starter_name`, ④ 원 예측 result의 `starter`). `engine_paths` = starter가 `<base>_0000.rad`이고 올린 파일에 `<base>_0001.rad`가 있으면 그 1개, 아니면 빈 배열. `additional_paths` = `hpc.scx.list_additional_paths`(기본 true)이면 올린 나머지 파일 전부(starter·engine 제외, 이름순), false면 빈 배열(폴더 전체를 서버가 쓴다고 가정). 둘 다 서버 확인 E4-11-4·5. 자원 = `hpc.scx.{appliance, version, ncpu, memory_gb, queue_type, run_type, mpi, single_precision}`, 작업 params `hpc.ncpus`가 있으면 ncpu를 덮어씀(`queue`·`walltime`은 scx에서 무시하고 로그 한 줄).
6. `POST /jobs/radioss`(`request_id` = 행의 값). 전송 오류·시간 초과·`SUBMISSION_IN_PROGRESS`이면 **같은 request_id로** `hpc.scx.submit_replay_attempts`(기본 3)회까지 `hpc.scx.submit_replay_wait_s`(기본 10) 간격 replay — relay가 어댑터를 다시 부르지 않으므로 중복 제출이 아니다.
7. 결과:
   - 성공 → 행 `QUEUED`, `external_job_id`, `submitted_at`, `output_path`/`output_rel`(있으면). ①은 run `SUBMITTED`(기존과 같음).
   - **`SUBMISSION_UNKNOWN`**(relay 409, 또는 replay를 다 써도 응답 없음) → 행 `state=UNKNOWN`, `submission_unknown=true`, `external_job_id=NULL`, error_message "SCX 제출 결과를 알 수 없습니다 — SCX에서 확인 필요". ①은 run `SUBMITTED`로 두고 `hpc_job_id` 연결. **자동 재제출 없음, 이미 제출한 다른 run 자동 취소 없음.** 남은 run은 제출하지 않고(행도 만들지 않음) result `not_submitted`에 기록 + 경고 `SCX_NOT_SUBMITTED`. 작업 attention `HPC_SUBMISSION_UNKNOWN` + 알림 `HPC_SUBMISSION_UNKNOWN`(등록자). 그 뒤 `EnterWaitingHpc`(행이 하나라도 있으므로).
   - 그 밖 오류(relay가 확정 실패로 돌려준 코드: `INVALID_PATH`·`PATH_NOT_ALLOWED`·`NOT_FOUND`·`FORBIDDEN`·`DRIVE_AUTH_REQUIRED`·`JOB_API_UNAVAILABLE`·`SCX_JOB_ERROR`·`INVALID_REQUEST` 등) → 행 `FAILED`, 그 다음은 기존 규칙(phase2 §6.5): 이미 제출한 run을 `terminate`로 취소 시도 + `HPC_SUBMIT_FAILED`. (확정 실패에서만 형제 취소. UNKNOWN에서는 하지 않음.)

**대기(WAITING_HPC) — 폴러**: §16.6 표. 주기 = `hpc.scx.poll_interval_s`(null이면 `hpc.poll_interval_s`).

**COLLECT (scx)**
8. `SUCCEEDED` 행마다 `output_rel`(없으면 마지막 `GET /jobs/{id}`로 다시 받음) → 없으면 그 run 회수 실패 "SCX 결과 위치 없음"(`SCX_OUTPUT_MISSING`). 있으면 `GET /list`를 깊이 `hpc.scx.collect_max_depth`(기본 2)까지 재귀(항목 합계 ≤ 20000), 파일 이름이 `hpc.transfer.collect_patterns` 중 하나와 맞는 것만.
9. 파일마다 크기 ≤ min(`hpc.scx.max_download_bytes`, `hpc.transfer.max_collect_bytes`, `/health.max_download_bytes`) — 넘으면 그 run 회수 실패. `GET /files` → `<result_dir>/<상대 경로>.part`에 쓰며 sha256 계산 → `X-Content-SHA256`·길이 일치하면 `os.replace`로 최종 이름, 불일치면 `.part`를 남기지 않고 1회 다시, 그래도 틀리면 회수 실패. `result_dir` = ① `01_train/results/<doe>/<run>`(TS_PREP가 `_backup` 처리·생성), ④ `V/result`. 경로 결합은 `ctx.abs` 기준 안쪽만(`..`·절대·링크 거부).
10. 완료 잡이므로 기존 "10초 간격 2회 불변" 안정성 대기는 하지 않는다. 기록·부분 실패·`COLLECT_FAILED` 규칙, `collect_state`, ① `collected_runs`/`TS_REGISTER`, ④ `PV_EXTRACT`(h3d 정확히 1개 규칙)는 그대로.

**취소**: 작업 취소 → 폴러가 행마다 `terminate`(기존 경로) → 성공 `CANCELED`, 실패 `CANCEL_REQUESTED` 유지·`HPC_CANCEL_FAILED`(기존). `external_job_id`가 없는 `UNKNOWN` 행은 원격 호출 없이 `CANCELED` + error_message "원격 잡 확인 불가 — SCX에서 직접 확인하세요"(`submission_unknown`은 true로 남김) + 작업 경고.

### 16.5 결과 모름(SUBMISSION_UNKNOWN) — 사용자 조치

- 표시: `GET /jobs/{id}/hpc-jobs` 행에 `submission_unknown`, `remote_dir`(표시 경로), `request_id`, `resolve_pending`, `error_message`. 화면(후속 프런트 작업)은 "확인 필요" 배지와 조치 3개.
- API: `POST /jobs/{id}/hpc-jobs/{hid}/resolve` (power 이상, 작업 취소와 같은 소유자·관리자 규칙, 감사 `HPC_RESOLVE`) 본문 `{"action": "recheck" | "attach" | "mark_not_submitted", "external_job_id"?: str(attach만, 1~128자, 제어문자 금지), "version": int}` → 202 `HpcJob`(`resolve_pending:true`). 오류: 409 `HPC_NOT_UNKNOWN`(행이 UNKNOWN·submission_unknown 아님) · 409 `HPC_RESOLVE_PENDING` · 409 `VERSION_CONFLICT` · 422 `INVALID_PARAMS`.
- API는 게이트웨이를 부르지 않는다(platform.md §12.2 "API는 availability()만"). 요청을 `hpc_jobs.resolve_request`에 적고 **워커 폴러가 다음 주기에 처리**:
  - `recheck`: 같은 request_id로 `POST /jobs/radioss` replay(어댑터 재호출 없음) → relay가 `SUBMITTED`를 돌려주면 그 job_id로 `QUEUED`(정상 진행), 여전히 `SUBMISSION_UNKNOWN`이면 그대로 + 알림 문구 "아직 확인 불가".
  - `attach`: 사용자가 SCX 화면에서 찾은 잡 ID → relay `POST /submissions/{rid}/resolve {attach, job_id}`(relay가 `get_job`으로 존재 확인·중복 거부) → 성공 시 행 `QUEUED`/상태값, `external_job_id`, `submission_unknown=false`. 실패면 행 그대로 + `error_message`에 이유.
  - `mark_not_submitted`: 사용자가 SCX에 잡이 없음을 확인 → relay `resolve {abandon}`(relay 실패여도 PhysicsAI 쪽은 진행, 경고 기록) → 행 `FAILED`, error_message "제출되지 않음(사용자 확인)". ① run `SOLVE_FAILED` → 기존 "실패 run 다시 제출"(새 `TD_SOLVE`, 새 잡 폴더)로 재제출. ④는 작업이 T13/T10b 규칙으로 끝나고 검증을 새로 실행.
  - 처리 후 `resolved_by`·`resolved_at` 기록, `resolve_request` 비움, 남은 UNKNOWN 행이 없으면 attention 해제.
- 자동 처리 없음: UNKNOWN 행은 `lost_after_polls`·`max_unreachable_minutes`로 LOST·실패가 되지 않는다(폴러가 `external_job_id IS NULL` 행은 상태 조회를 건너뜀). 작업은 사용자가 조치하거나 취소할 때까지 WAITING_HPC에 머문다.
- 주의 문구(화면·API 설명): "SCX에 잡이 실제로 있는데 '제출 안 됨'으로 표시하면 같은 해석이 두 번 돌 수 있습니다(폴더는 따로)."

### 16.6 상태 매핑

| 출처 | 값 | `hpc_jobs.state` | 비고 |
|---|---|---|---|
| HPC_SUBMIT | 행 삽입(제출 전) | `SUBMITTING` | 워커 중단 후 남은 `SUBMITTING`은 housekeeping이 `UNKNOWN`+`submission_unknown`으로(결과를 모름) |
| `POST /jobs/radioss` | 201/200 | `QUEUED` | `external_job_id` 기록 |
| 〃 | 409 `SUBMISSION_UNKNOWN`·replay 소진 | `UNKNOWN` + `submission_unknown=true` | §16.5 |
| 〃 | 확정 오류 | `FAILED` | 형제 취소(기존) |
| `GET /jobs/{id}`.status | `Queued` | `QUEUED` | |
| 〃 | `Running` | `RUNNING` | |
| 〃 | `Completed` | `SUCCEEDED` | `HpcStatus(state="FINISHED", outcome="SUCCEEDED")` |
| 〃 | `Failed` | `FAILED` | `outcome="FAILED"`, `error_message` = JobInfo.error_message(마스킹·500자) |
| 〃 | `Aborted` | 행이 `CANCEL_REQUESTED`면 `CANCELED`, 아니면 `FAILED` | 문구 "SCX에서 중단됨" |
| 〃 | 그 밖 문자열 | 상태 유지, `unknown_count`+1 → `lost_after_polls`면 `LOST` | `external_state_raw`에 원문 |
| relay | 404 `SCX_JOB_NOT_FOUND` | 위와 같음(UNKNOWN 계수) | PBS의 "not_found → 끝남" 규칙은 scx에 쓰지 않음(`not_found=false`) |
| relay | 연결 실패·5xx·`DRIVE_AUTH_REQUIRED`·`DRIVE_BUSY` 등 | 상태 유지 | `HpcGatewayError(UNAVAILABLE)` → 기존 `hpc_unreachable_since`·`max_unreachable_minutes`(문구에 "대시보드 SCX 연결 확인") |
| relay | 404 `JOB_NOT_FOUND`(relay 기록에 없음) | 상태 유지, error_message | 설정·DB 불일치 — UNAVAILABLE과 같이 처리 |

`collect_state`(`NONE→PENDING→COLLECTING→COLLECTED|FAILED`)와 `hpc_terminal_transition`(T10·T10b·T13)은 그대로. `UNKNOWN`은 종료 상태가 아니므로 작업이 기다린다.

### 16.7 게이트웨이 확장(`simdash_adapters.hpc`, platform.md §12.5)

- `HpcAvailability.mode`에 `"scx"`, `HpcGatewayError.code`에 `"SUBMISSION_UNKNOWN"` 추가. `HpcStatus`에 선택 필드 `outcome: Literal["SUCCEEDED","FAILED"] | None = None`, `output_path: str | None = None`, `output_rel: str | None = None`, `error_message: str | None = None`(기본값 있어 기존 생성 코드 불변). 폴러: `FINISHED`에서 `outcome`이 있으면 그것을, 없으면 기존 exit_code 규칙.
- `ScxHpcGateway`는 `HpcJobGateway`(availability·submit·status·cancel)를 구현하고 scx 전용 메서드를 더한다: `health()`, `ensure_new_dir(parent, name) -> str`, `mkdirs(rel, request_id)`, `upload(local_path, rel_dir, name, sha256, request_id) -> batch_id`, `batch(batch_id)`, `submit_radioss(req: ScxRadiossRequest) -> ScxSubmitOutcome`, `list(rel, max_entries)`, `download(rel, dst_local, max_bytes) -> (size, sha256)`, `resolve(request_id, action, job_id=None)`. 범용 `submit(spec)`은 scx에서 `NOT_CONFIGURED`("scx 모드는 단계 A·B 흐름으로 제출")를 낸다 — step이 `availability().mode == "scx"`로 분기.
- `availability()`: 설정 검증(아래) + 비밀 파일 읽힘 → `configured=true`. 네트워크 health는 TTL `hpc.scx.health_ttl_s`(기본 30)·시간 한도 3초로 캐시해 message에만 반영("SCX(대시보드 연결)" / "대시보드 연결 확인 실패(일시)" / "대시보드 어댑터에 잡 API 없음" — 마지막은 `configured=false`). 일시 장애로 작업 생성을 막지 않는다.

### 16.8 설정(`hpc.scx`, 기본값은 스키마 한 곳)

| 키 | 기본 | 검증 |
|---|---|---|
| `hpc.gateway` | `none` | `none | command | adapter | scx`(환경변수 `PHYSICSAI_HPC_GATEWAY` 우선, 기존) |
| `relay_url` | `""`(scx면 필수) | `http://127.0.0.1:<port>` · `http://[::1]:<port>` · `http://localhost:<port>`만(경로·쿼리·사용자 정보 없음). 클라이언트가 `/internal/scx-relay/v1`을 붙임 |
| `secret_file` | `""` = `<런타임>/secrets/scx_relay_key` | 파일 한 줄 base64url 43~128자. 없거나 형식 틀리면 `configured=false`(사유에 경로만, 값 없음) |
| `drive_base` | `"~"` | `"~"` 또는 `"~/<상대>"`(§4 규칙) |
| `home_display` | `/Users/vd.dashboard` | 표시 전용 |
| `appliance` | `""`(필수) | 1~128자, 제어문자 금지(E4-11-1) |
| `version` | `""`(필수) | 1~128자(E4-11-2) |
| `ncpu` | `16` | 1~4096 |
| `memory_gb` | `null` | null 또는 1~65536 |
| `queue_type` | `implicit` | 1~64자 |
| `run_type` | `both - use starter and engine files` | 1~128자 |
| `mpi` | `Pure MPI`(S20 보강 1) | 1~128자 |
| `single_precision` | `false` | bool |
| `poll_interval_s` | `null`(= `hpc.poll_interval_s`) | null 또는 10~3600 |
| `max_download_bytes` | `21474836480` | 1 MiB~2^40 |
| `stage_patterns` | `["*.rad","*.inc","*.csv"]` | 1~32개 fnmatch, `/\` 금지 |
| `list_additional_paths` | `true` | bool(E4-11-4) |
| `max_stage_bytes` | `21474836480` | 1 MiB~2^40 |
| `stage_poll_s` / `stage_timeout_s` | `5` / `7200` | 1~60 / 60~86400 |
| `submit_replay_attempts` / `submit_replay_wait_s` | `3` / `10` | 0~10 / 1~120 |
| `http_timeout_s` / `transfer_timeout_s` | `30` / `3600` | 요청 1개(파일 전송 제외) / 파일 1개 전송 |
| `collect_max_depth` | `2` | 0~5 |
| `health_ttl_s` | `30` | 0~600 |

`deploy/setup_config.py`는 `hpc.scx` 절이 없을 때만 주석 달린 기본 절을 보충(값 덮어쓰기 없음). 비밀 파일은 설치 스크립트가 만들지 않는다 — 관리자가 한 번 만든 같은 값을 대시보드 `SIMDASH_SCX_RELAY_SECRET_FILE`과 PhysicsAI `secret_file`에 넣는다(admin.md에 생성 명령·ACL 안내, 실제 값은 어떤 문서·git에도 두지 않음).

### 16.9 DB — migration `0009_scx_gateway`

- `hpc_jobs` 열 추가: `remote_dir VARCHAR(1024)`, `request_id VARCHAR(128)`(부분 유일 `WHERE request_id IS NOT NULL`), `staged JSONB`, `output_path VARCHAR(1024)`, `output_rel VARCHAR(1024)`, `submission_unknown BOOLEAN NOT NULL DEFAULT false`, `resolve_request JSONB`, `resolved_by VARCHAR`, `resolved_at TIMESTAMPTZ`. 상태 CHECK는 그대로(`UNKNOWN` 이미 있음).
- `notifications` event CHECK에 `HPC_SUBMISSION_UNKNOWN` 추가.
- 응답 `HpcJob`에 `gateway_mode`, `remote_dir`(표시 경로), `output_path`, `submission_unknown`, `resolve_pending`, `error_message` 추가(선택 필드, 기존 클라이언트 영향 없음).

### 16.10 안전

1. **SPDM 루트 쓰기 금지**(§16.3, 양쪽 검사, 예외 설정 없음). 드라이브 삭제·이동·덮어쓰기 없음 — PhysicsAI 클라이언트에 그런 메서드가 없다(정적 시험).
2. **경로 검증 양쪽**: PhysicsAI(이름·깊이·길이·기준 안·금지 접두) → relay(`validate_drive_rel_path` + 범위 + 금지). 로컬 쓰기는 `ctx.abs` 기준 안, `.part` → `os.replace`, 링크 거부.
3. **비밀**: 헤더 `X-SCX-Relay-Key`만, URL·쿼리·로그·오류 묶음(`error_bundle`)·설정 요약에 값 없음. 워커 기동 때 값을 로그 마스킹 목록에 등록. 설정 요약은 `secret_file` 경로와 `present: true|false`만. 저장소·문서에는 실제 값을 두지 않는다.
4. **loopback 전용**: `relay_url` 검증(§16.8) + relay 쪽 client 주소·프록시 헤더 검사 + `/internal` 경로가 프록시 대상 아님.
5. **제출 중복 방지**: `request_id` = `pai-<hpc_jobs.id>`(행 먼저 삽입), replay만 자동, 새 제출은 새 행·새 폴더.
6. relay `error_message`·`JobInfo.error_message`는 PhysicsAI 쪽에서도 마스킹(기존 hpc 마스킹 함수) 후 500자.

### 16.11 서버 확인(E4-11, 사용자)

| # | 확인 | 방법 | 다르면 |
|---|---|---|---|
| E4-11-1 | Radioss appliance 이름 | SCX 화면·HPC_SDK 예제에서 Radioss 제출 시 appliance 값 | `hpc.scx.appliance` |
| E4-11-2 | version 문자열(예 `2026.1`인지 `Radioss 2026.1`인지) | 같은 곳 | `hpc.scx.version` |
| E4-11-3 | `input_path`가 받는 표기(상대 `cushion/…` / `~/cushion/…` / `/Users/vd.dashboard/cushion/…`) | 테스트 폴더 1개로 relay 표기 3가지 제출 | 대시보드 `SIMDASH_SCX_RELAY_JOB_PATH_FORM` |
| E4-11-4 | include(`*.inc`·`RENUM_INIT.csv`)를 `additional_paths`에 꼭 넣어야 하는지(아니면 폴더째 복사되는지) | include 있는 run 1개를 true/false로 각각 | `hpc.scx.list_additional_paths` |
| E4-11-5 | `run_type` "both"에서 engine(`_0001.rad`)을 `engine_paths`로 줘야 하는지 | 같은 시험 | step 규칙(변경 메모) |
| E4-11-6 | 결과 위치: `JobInfo.output_path` 표기와 위치(잡 폴더 안/서버 작업 폴더), `list_dir`·`download_to`로 읽히는지, 하위 폴더 깊이 | 완료 잡 1개 | relay output_rel 변환·`collect_max_depth` |
| E4-11-7 | 상태 문자열 전체(Queued·Running·Completed·Failed·Aborted 외 값 여부, 대소문자) | 대기·실행·완료·실패·중단 각 1회 | §16.6 표 |
| E4-11-8 | `terminate_job`: 대기·실행·완료 잡에서 동작과 이후 상태(Aborted?) | 시험 잡 | 취소 처리 |
| E4-11-9 | 대시보드에 설치된 어댑터 버전 ≥ 0.3.0이고 `WorkerDriveGateway`가 잡 API를 노출하는지, `SUBMISSION_UNKNOWN` 코드 값 | relay `/health`의 `job_api`·`adapter_version` | 어댑터 업데이트 |
| E4-11-10 | `ncpu`·`memory_gb`·`queue_type`·`mpi` 허용 값 | SCX 화면 | 설정 |
| E4-11-11 | 1 GB 이상 `.rad` 업로드·10 GB h3d 다운로드 소요와 그동안 대시보드 화면 반응(워커 1개 공유) | 시험 | `SIMDASH_SCX_MAX_CONCURRENCY`·운영 시간대 |
| E4-11-12 | 결과 파일 이름이 `collect_patterns`(`*.h3d`·`*T01`·`*_0000.out`·`*_0001.out`)와 맞는지 | 완료 잡 목록 | `hpc.transfer.collect_patterns` |

### 16.12 시험

**PhysicsAI**(Linux, Altair·대시보드 없이): 가짜 relay `packages/simdash_adapters/tests/fake_scx_relay.py` — `http.server`를 127.0.0.1 임의 포트에 띄워 scx_relay.md §5를 임시 폴더("드라이브")로 흉내(키 검사, 묶음 상태 진행, replay 기록, 주입: `SUBMISSION_UNKNOWN`·응답 끊김·`BUSY`·`PAUSED`·`CONFLICT`·상태 시퀀스·해시 불일치·`job_api=false`). `backend/tests`는 같은 가짜를 fixture로 재사용.
1. 설정: relay_url loopback 외 거부, secret_file 없음/형식 → configured=false(값 비노출), drive_base 표기, 필수 appliance·version.
2. 이름: 프로젝트 정규화(예약어·빈 값·64자), D-/V- 번호, ts 고정, `_2` 접미, 1024자, SPDM 접두 거부.
3. STAGE_IN: 패턴·링크·하위 폴더 경고·크기 상한·sha·묶음 PAUSED 대기·시간 초과·CONFLICT 실패(제출 0건).
4. 제출: engine 판정, additional_paths(true/false), params ncpus, replay(전송 끊김 → 같은 request_id, 가짜 relay 어댑터 호출 1회), 확정 실패 → 형제 terminate(기존), **SUBMISSION_UNKNOWN → 형제 취소 없음·남은 run 미제출·attention·알림·WAITING_HPC**.
5. 폴러: §16.6 표 전부, UNKNOWN 행 조회 건너뜀·LOST 안 됨, Aborted/CANCEL_REQUESTED → CANCELED, 연결 실패 → hpc_unreachable_since.
6. resolve API: 권한(401·403), 409 3종, 202 → 폴러 처리 recheck/attach/mark_not_submitted, 감사 행, ① run 상태·재제출 경로, ④ 종료 전이.
7. COLLECT: 패턴·깊이·크기 상한·sha 불일치 재시도·`.part` 미잔존·output_rel 없음 실패, ① 부분 회수(T10b)·④ h3d 1개.
8. 취소: terminate, UNKNOWN 행 로컬 CANCELED + 경고.
9. 정적: `simdash_adapters`가 표준 라이브러리만 import, scx 클라이언트에 delete·move·overwrite 계열 이름 없음, 비밀 값이 로그·error_bundle에 없음(caplog). migration 0009 PG 왕복(upgrade만).
**대시보드**: scx_relay.md §8.

### 16.13 파일 소유(병렬 구현 2개 — 겹치는 파일 없음)

| 에이전트 | 저장소 | 파일 |
|---|---|---|
| **Impl-Relay** | simdashboard(브랜치 `claude/scx-drive`에서 새 브랜치) | scx_relay.md §9 목록만. PhysicsAI 저장소는 읽기만 |
| **Impl-SCX**(PhysicsAI 백엔드) | physicsai-platform `claude/phase3` | 새: `packages/simdash_adapters/src/simdash_adapters/hpc/scx.py`·`scx_client.py`·`scx_naming.py`, `packages/simdash_adapters/tests/fake_scx_relay.py`·`test_scx_*.py`, `migrations/versions/0009_scx_gateway.py`, `worker/physicsai_worker/steps/_scx.py`, `backend/tests/test_scx_*.py`. 수정: `packages/simdash_adapters/src/simdash_adapters/hpc/types.py`·`factory.py`·`__init__.py`, `backend/physicsai_core/hpc/gateway.py`, `backend/physicsai_core/config/schema_hpc.py`·`validate.py`·`runtime.py`, `backend/physicsai_core/db/tables/execution.py`, `backend/physicsai_core/db/repositories/hpc.py`, `backend/physicsai_core/state_machine.py`(필요 시), `worker/physicsai_worker/hpc_poller.py`·`housekeeping.py`, `worker/physicsai_worker/steps/stage1_train_data/solve.py`, `worker/physicsai_worker/steps/stage4_predict/verify.py`, `backend/physicsai_api/routers/jobs.py`, `backend/physicsai_api/schemas/jobs.py`, `openapi` 산출물, `deploy/setup_config.py`, `docs/admin.md`(scx 절), 설정 예시 파일 |
| (후속) Impl-Frontend | physicsai-platform `frontend/**` | "확인 필요" 배지·조치 3개·원격 폴더 표시. 이번 두 에이전트는 `frontend/**`를 건드리지 않음 |

인터페이스 고정점: relay HTTP 계약(scx_relay.md) — 양쪽은 서로의 코드를 import하지 않고 이 문서와 각자의 가짜(대시보드 `drive_fakes.py` 잡 API, PhysicsAI `fake_scx_relay.py`)로 시험한다.

### 16.14 리스크

- **어댑터 워커 1개 공유**: 큰 업로드·다운로드 동안 대시보드 화면의 드라이브 읽기가 늦어진다(다운로드는 BACKGROUND 우선순위, 업로드는 대기열 순서). E4-11-11.
- **서버 임시 공간 이중 사용**: 업로드·다운로드가 대시보드 `SIMDASH_SCX_STAGING_DIR`를 거친다(파일 크기 + 1 GiB 여유 검사).
- relay 쓰기는 `SIMDASH_DRIVE_WRITES_ENABLED=true` + SPDM 루트 설정(대기열 동작)에 묶인다. 대시보드 재로그인 필요(`AUTH_REQUIRED`)면 대시보드 자체 업로드와 함께 멈춘다.
- **결과 위치 미확인**(E4-11-6): output_path가 드라이브 경로가 아니면 회수 방식을 다시 정해야 한다.
- SUBMISSION_UNKNOWN은 사람 조치 전까지 작업이 WAITING_HPC에 남고, "제출 안 됨"을 잘못 고르면 중복 해석이 생긴다.
- 공용 계정 홈 바로 아래에 프로젝트 폴더를 만들므로 같은 이름의 다른 용도 폴더가 있으면 그 안에 잡 폴더가 생긴다(덮어쓰기는 없음). 필요하면 `drive_base: "~/physicsai"`로 바꿀 수 있다.
- 비밀 교체는 두 앱 재시작이 필요하다. 대시보드 migration 번호(0044)는 다른 브랜치와 충돌할 수 있어 구현 때 다음 번호로.

---

## 17~24. S12~S19 (2026-10-17~20) — 별도 계약 파일에서 이관

S12~S19 계약은 phase3.md에 다른 작업의 미커밋 변경이 있어 `s12_s13.md`·`s14_analysis.md`·`s15_sampling.md`·`s16_voc.md`·`s17_multiobj.md`·`s18_doe_parallel.md`·`s19_followup.md`로 따로 두었다. 2026-10-20 문서 이관(D)으로 **본문 요지와 변경 메모(D3-59~D3-67)를 이 문서로 옮겼다.** 이 문서가 기준이고, 알고리즘 상세·표·시험 전체 목록·파일 소유 표는 각 계약 파일 원문(각 절 머리 링크)에 남긴다(파일은 지우지 않음, 맨 위에 이관 안내 한 줄). 번호·용어는 위 절과 같다(§14 일괄 예측, §15 캡처, D3-51·D3-53·D3-54 규칙). 화면 번호는 S14 이후 ④ 예측 · ⑤ 결과분석 · ⑥ 최적화이고, S12·S13 원문의 "⑤ 최적화"는 구 번호다(내부 코드 경로·URL `/stage/5`·`jobs.stage`는 그대로).

migration 순서: 0010 `surrogate_opt`(S13) → 0011 `surrogate_final`(S13 D3-61) → 0012 `sampling_kinds`(S15) → 0013 `fem_verify`(S16) → 0014 `multiobj`(S17) → 0015 `doe_platform_gen`(S18). S14·S19는 migration 없음(`MIGRATION_HEAD` = `0015_doe_platform_gen`).

> native 계약(별도 파일 유지, 2026-10-20 병합): [geometry-engine.md](geometry-engine.md)(native 형상 엔진 paicad, migration `0016_geometry_engine`), [shell-morph.md](shell-morph.md)(쉘 판금 비드), [geometry-view.md](geometry-view.md)(3D 가시화·결과 3D 컨투어, migration `0017`), [opt-native.md](opt-native.md)(⑥ HyperStudy 독립·GA·NSGA-II). 병합본 `MIGRATION_HEAD`는 native `0017`이며, 이 절의 0010~0015 순서는 그대로다.

## 17. S12 DOE 설계공간 지도 (사용자 결정 2026-10-17, D3-59)

원문: [s12_s13.md](s12_s13.md) §17. 새 DB·새 작업·새 의존성 없음.

목표: 일괄 예측 결과의 그래프 카드에 탭 `변수–응답` · `설계공간 지도`(S14 이후 ⑤ 결과분석으로 이동, §19). run마다 변수 벡터(반영값)를 PLS(기본)·PCA 2차원 투영 또는 평행 좌표로 펼치고 점·선 색 = 고른 값(기본 `curve:max`). 표·커브 겹쳐보기와 같은 선택 모델(`selected` = doe_no).

| # | 결정 | 근거 |
|---|---|---|
| M1 | run별 대표값은 **백엔드** `GET /predict-batches/{bid}/design-map`(프로세스 LRU)에서 계산. 완료 run의 `curve.json`(≤ 20000점)·`RESPONSES.txt`를 한 번 읽어 모든 계열의 max·min·\|max\|와 모든 RESP 키를 run당 수십 숫자로 요약 | 프런트 `curves` API는 계열 1개·run 상한·2000점 다운샘플이고 RESP 원값이 없다. 값 선택 변경은 왕복 없음. S13 목적함수도 같은 요약 재사용 |
| M2 | PCA(Jacobi)·PLS(NIPALS PLS1 2성분)·평행 좌표는 **프런트 TS** (n ≤ 200, p ≲ 20) | 색 값을 바꿀 때마다 즉시 재적합. 백엔드에 numpy를 더하지 않음 |
| M3 | 변수 = 템플릿 파라미터 전부, 값 = 반영값(`applied_values`), 유효 run 기준 z-점수(ddof=1) | 단위가 다른 변수를 같은 무게로 |
| M4 | 기본 색 값 `curve:max`(첫 계열). 그 밖 `curve:min`·`curve:absmax`·`resp:<NAME>_MIN\|_MAX`, `RESPONSES.txt`가 없는 옛 run은 `tbl:<name>` | 사용자 결정 |

**지표 id 문법(S12·S13 공용, ASCII fullmatch)**: `curve:max\|min\|absmax`(+별도 `series`, 생략 = 첫 계열), `resp:<NAME>_MIN\|_MAX`(`P/RESULT/RESPONSES.txt`), `tbl:<name>`(RESPONSES.txt 성공 run이 하나도 없을 때만). 정규식 `run_metrics.METRIC_RE`. S17에서 `perf:<NAME>` 추가(§22).

**공용 모듈** `physicsai_core/stage4_predict/run_metrics.py`: `RunFiles`·`RunMetrics`(`curve`: 계열별 max/min/absmax/x_at_max/x_at_min/n, `resp`), `locate_run_files(conn, study_root, job)`(Study 밖·링크 거부), `load_run_metrics`(파일별 LRU 2048개, 키 = 경로·mtime_ns·크기), `metric_value`, `curve_stats`(NaN·길이 불일치 계열 제외, 계열 ≤ 50). `curve.json` > `ui.max_artifact_bytes`면 커브 없음.

**API** `GET /predict-batches/{bid}/design-map`(member 이상, 404 `BATCH_NOT_FOUND`, `no-store`): `parameters`(템플릿 순서·min·max·integer), `series`, `metrics`(curve는 계열 ≥ 1일 때만, resp는 성공 run에 키가 있을 때만 사전순), `runs`(doe_no 순, 성공 아닌 run은 `curve`·`resp`·`tbl` null), `counts{total,succeeded,no_curve,no_resp}`. 프런트는 `succeeded`·`status`가 바뀔 때만 다시 받는다.

**계산 규칙(요지)**: 유효 run = SUCCEEDED + 값 유한. 유효 변수 = 표준편차 > 1e-12·max(1,\|평균\|)(상수 변수는 PCA·PLS에서 제외, 평행 좌표엔 평평한 축). PCA 축 `PC1 (X 분산 41.2%)`, PLS 축 `PLS1 (X 28% · 값 63%)`(X % = 설명한 표준화 변수 분산, 값 % = 설명한 색 값 분산), 부호 규칙 고정(PLS: corr(t, y) ≥ 0). 바이플롯 화살표 = 구조 상관. 평행 좌표는 값 축 브러싱(범위 밖 불투명 0.12). 경계 6종(유효 run < 3, 유효 변수 0·1, y 상수 → PCA로, 2성분 없음, 값 전부 같음)은 회색 안내 문구.

**화면**: 탭 선택 `physicsai.stage4.batchGraphTab`, 지도 설정 `physicsai.stage4.designMap`(method·metric·series·arrows)을 localStorage에(try/catch). 자체 SVG, viridis 연속 색 + 세로 색 막대, 점 클릭 = `setSelected(doe_no)`. 커브 지표를 고르면 커브 겹쳐보기 계열도 연동.

시험 V3-S12-1~5(run_metrics 골든·API·`linalg.ts` numpy 참조 골든 1e-6·경계 표·화면). 서버 확인 E4-12-4(PLS·PCA 축 %·점↔표·커브 최대 일치)·E4-12-5(200 run 첫 로드 < 5 s, 재로드 캐시).

## 18. S13 쿠션만 최적화 — 플랫폼 내장 대리모델 최적화 (사용자 결정 2026-10-17, D3-60·D3-61)

원문: [s12_s13.md](s12_s13.md) §18. 화면 번호는 S14 이후 ⑥ 최적화.

> 후속(2026-10-20): ⑥ 기본 = 내장, 원본(HyperStudy) 모드는 레거시 선택 기능, 알고리즘 `ga`·`nsga2`·검증 방식 `none`·범주 `baseline`은 [opt-native.md](opt-native.md)를 따른다(native 세트 엔진 게이트는 [geometry-engine.md](geometry-engine.md) §7.5·§7.7).

목표: 최적화에 모드 `플랫폼 내장(쿠션만 가능)`(기본) | `원본 최적화(조립 필요)`. 내장 모드는 HyperStudy 대신 **④ 일괄 예측 체인(§14)**으로 설계를 평가하므로 mesh_only·assembly 템플릿 모두 동작한다. 흐름: 탐색(새 DOE 배치 N개 또는 완료 배치 재사용) → 대리모델 적합(GP/Kriging 기본, RBF 선택) → 범위·제약 안에서 후보 k개 → **실제 예측 체인(PREDICT_BATCH + 하위 PREDICT)으로 검증** → 개선 < tol 또는 최대 반복까지 반복. 기본 3회 × 4후보. 원본 모드는 mesh_only 템플릿이면 명확한 문구로 막는다(이슈 #4).

| # | 결정 |
|---|---|
| O1 | 검증 = PREDICT_BATCH 재사용(후보 k개를 `source.kind:"table"`로 만든 배치). 새 예측 경로 없음 |
| O2 | 반복 제어 = **종료 훅 연쇄**: 배치 DONE → `job_end`가 다음 `SURROGATE_OPT` 반복 작업(SLOT, INTERNAL step만)을 대기열에 넣음. 기다리는 동안 슬롯 미점유(부모 대기 점유는 1슬롯에서 자식과 교착) |
| O3 | 목적·제약 값 = §17 지표 id, 계산은 `run_metrics` |
| O4 | 계산은 워커 INTERNAL step의 **numpy·scipy**(새 런타임 의존성, 사용자 확인 대상). scikit-learn 미사용 |
| O5 | 범위는 템플릿 학습 범위 안만(lo = hi는 고정 변수) |
| O6 | 탐색·검증 배치의 컨투어 캡처 기본 끔(체크 "검증 run 컨투어 캡처"), 최적점은 끝난 뒤 재캡처(§15) |
| O7 | Study당 진행 중 내장 최적화 1개(부분 유일 인덱스) |

**의존성**: `numpy>=2.0,<3`·`scipy>=1.13,<2`를 `pyproject.toml`·`deploy/requirements.lock`(구현: numpy 2.4.6·scipy 1.17.1)에 추가. import는 `stage5_optimize/surrogate/*` 안 지연 import, API 프로세스는 numpy를 불러오지 않는다(S15 Sobol 미리보기만 예외, §20). `features.optimize_builtin` = numpy·scipy 있음 + `surrogate_opt.enabled` + 예측 기능. 없으면 그 기능만 꺼짐(`missing`에 사유).

**DB** migration `0010_surrogate_opt`: `surrogate_opts`(`SO-001` 번호, `settings` JSONB, `status` EXPLORING→FITTING→VERIFYING→DONE\|FAILED\|CANCELED, `best`, `stop_reason`, `dir_rel`), `surrogate_opt_iters`(PK(opt_id, iter_no), `kind` EXPLORE\|REUSE\|VERIFY, `batch_id`, `fit`·`candidates` JSONB, `best_value`·`improvement_rel`). 알림 이벤트 `SURROGATE_OPT_DONE`. `ux_jobs_study_type_active` WHERE에 "최적화 소유 PREDICT_BATCH 제외" 추가(수동 배치와 동시 대기 허용). 폴더 `05_opt/surrogate/SO-001/`(`opt.json`·`iter_NN/{dataset.csv,surrogate.json,loo.csv,candidates.csv}`·`convergence.csv`·`verified_runs.csv`·`summary.json`).

**작업** job_type `SURROGATE_OPT`(stage 5, SLOT, `notify_success=False`, `POST /jobs`로 생성 불가 422):

| step | kind(무게) | 처리 |
|---|---|---|
| SO_COLLECT | INTERNAL 10 | 반복 0..r−1 배치의 성공 run에서 목적·제약 값 수집·같은 설계 평균·실패 설계 목록·`dataset.csv`·정지 판정 |
| SO_FIT | INTERNAL 45 | 대리모델 적합 + LOO(제약마다 모델 1개) |
| SO_PROPOSE | INTERNAL 35 | 후보 k개 |
| SO_NEXT | INTERNAL 10 | 계속이면 한 트랜잭션(Study FOR UPDATE)에서 검증 PREDICT_BATCH 부모 + run 행 + iters 행 등록, 마무리면 파일 3개·best·알림 |

**알고리즘(요지)**: 입력 [0,1] 정규화, max는 부호 반전. GP = 상수 평균 + Matérn 5/2 ARD + nugget, 집중 로그우도 L-BFGS-B(시작점 `gp_restarts` 8), Cholesky 실패 시 jitter 3회 뒤 RBF(경고 `GP_FALLBACK_RBF`), LOO 닫힌 식. RBF = cubic + 1차 다항, Rippa LOO. 품질 `loo_rmse`·`loo_nrmse`·`q2`(≥ 0.9 좋음 · 0.7~0.9 보통 · < 0.7 낮음)·`pred_vs_verified_mae`. 후보: ① 활용(예측 평균 최소, 제약 위반 벌점) ② 나머지 k−1 = EI × PoF 최대 + kriging believer(RBF는 평균 최소 + 거리 ≥ 0.1). 탐색기 `differential_evolution(seed = seed·1000 + r, integrality)`. 정지: `CONVERGED`(improvement_rel < tol_rel, r ≥ 2)·`MAX_ITER`·`NO_NEW_CANDIDATE`, 실패 `VERIFY_ALL_FAILED`·`TOO_FEW_POINTS`(max(5, d_free+2))·`SURROGATE_TIMEOUT`(`fit_timeout_s` 600). 같은 자료·설정·시드 → 같은 후보.

**API**: `POST /studies/{id}/surrogate-opts/preview`(동기), `POST /studies/{id}/surrogate-opts`(power), `GET /studies/{id}/surrogate-opts`, `GET /surrogate-opts/{oid}`, `GET …/runs.csv`, `POST …/cancel`(멱등), `POST …/resume`(FAILED만). 검증 422 `SURROGATE_OPT_INVALID` + problems(`BOUNDS_INVALID`·`BOUNDS_OUT_OF_RANGE`·`TOO_MANY_VARIABLES`·`NO_FREE_VARIABLE`·`EXPLORE_TOO_FEW`·`EXPLORE_TOO_MANY`·`METRIC_UNKNOWN`·`CONSTRAINT_INVALID`·`ITERATIONS_RANGE`·`CANDIDATES_RANGE`). 409 `SURROGATE_OPT_ACTIVE`·`BATCH_NOT_REUSABLE`(reason NOT_DONE\|TEMPLATE_MISMATCH\|MODEL_MISMATCH)·`FINAL_MODEL_REQUIRED`·`FEATURE_NOT_AVAILABLE`·`TEMPLATE_NOT_CONFIGURED`·`SURROGATE_OPT_NOT_RESUMABLE`, 404 `SURROGATE_OPT_NOT_FOUND`. 최적화 소유 배치에 일괄 취소·`retry-failed` → 409 `BATCH_OWNED_BY_OPT`. `/status`에 `features.optimize_builtin`·`surrogate_opt{defaults,max_*}`.

**훅·알림**: 배치 DONE + 진행 중 opt → `PREDICT_BATCH_DONE` 생략, 반복 작업 r+1 투입. 소유 배치 부모 실패 → opt FAILED `BATCH_FAILED`, 반복 작업 실패 → `ROUND_FAILED`, 취소는 opt를 먼저 CANCELED로 둔 뒤 같은 트랜잭션에서 반복 작업·배치 취소. 완료 알림 `SURROGATE_OPT_DONE` 1건. `best`는 **검증된**(실제 예측 체인) 설계만, 대리모델 최적값은 `summary.json` 참고용.

**이슈 #4**: 원본 OPTIMIZE를 mesh_only(또는 `assem_rel`·`starter_name` 없음) 템플릿으로 생성·재시도하면 409 `TEMPLATE_ASSEMBLY_REQUIRED`, 워커 `op_prep`도 경로 조합 전에 같은 코드로 실패(TypeError 제거).

**설정** `surrogate_opt`: `enabled`·`dir_name`·`max_variables` 20·`max_iterations` 10·`max_candidates` 10·`default_iterations` 3·`default_candidates` 4·`default_tol_rel` 0.01·`default_surrogate` gp·`gp_restarts` 8·`de_maxiter` 200·`de_popsize` 15·`fit_timeout_s` 600, 구현에서 `blas_threads` 4 추가(D3-60 구현 메모).

**화면(⑥)**: 모드 세그먼트(`physicsai.stage5.mode`), 서브 탭 `실행 목록`|`새 최적화`, 결과 `/p/:projectId/s/:studyId/stage/5/surrogate/:optId`(POLL 5초): 최적 설계 카드·수렴 그래프·대리모델 품질 표·검증 run 표(CSV)·파일 위치. 

**D3-61 결과 보강(migration `0011_surrogate_final`)**: 정지 시 컨투어 캡처가 구성돼 있으면 opt를 바로 DONE으로 두지 않고 `FINALIZING` — 최적화 소유 PREDICT_BATCH 1개(source table 2행: doe 1 = 기준안 nominal, doe 2 = 최적안, 캡처 켬, 같은 범례)를 iters `kind FINAL`로 등록. 배치 DONE → 훅이 DONE + 알림. `surrogate_opts.final` JSONB(`status` PENDING\|DONE\|SKIPPED\|FAILED\|CANCELED, `legend`, `baseline_values`, `notice` …). 화면: 최적안 대 기준안 카드·결과 요약 타일·컨투어 비교(같은 범례)·수렴 그래프에 기준안 수평선.

시험 V3-S13-1~9(0010·수학 골든·SO_COLLECT/NEXT·훅·API·이슈 #4·가짜 도구 e2e·화면). 서버 확인 E4-12-1~6(numpy·scipy 설치, 이슈 #4 재현 안 됨, 새 DOE 12 + 3×4, 재사용, 취소, §17 E4-12-4·5).

리스크: numpy·scipy wheel ~55 MB(없으면 기능만 꺼짐); 대리모델의 대리모델 → 최적 설계는 FEM 검증(§21) 권장; 예측 잡음·적은 탐색 run이면 품질 낮음(기본 탐색 수 max(10, 4·d_free)); 소요 = 검증 run 수 × 수 분; BLAS가 순간 여러 코어를 씀.

## 19. S14 ⑤ 결과분석 (사용자 결정 2026-10-17, D3-62)

원문: [s14_analysis.md](s14_analysis.md) §19. migration·새 의존성·새 job_type 없음.

> 후속(2026-10-20): ⑤ 탭 "등가성 판정"(두 결과 집합 비교, 허용오차 레시피·판정 이력, job `EQ_CHECK`)은 [equiv-check.md](equiv-check.md)를 따른다.

목표: 화면 단계를 ④ 예측 · **⑤ 결과분석(신설)** · ⑥ 최적화(기존 ⑤)로 재편(①~③ 불변). ⑤는 "결과 표"(run마다 파라미터 + 응답)를 받아 설계공간 지도·영향도·변수–응답 그래프·커브 겹쳐보기를 보여 준다.

| # | 결정 |
|---|---|
| A1 | 표시 번호·라벨·메뉴 순서만 변경. **URL 숫자·`jobs.stage`·`stage_label` 값·job_type·내부 코드 경로·e2e 기존 번호 유지**. 사용자에게 보이는 `stage_label`(대기열·알림)은 프런트가 job_type → 새 표시 번호로 매핑 |
| A2 | 공통 입력 = 프런트 `ResultTable` 1종(source `solver`\|`predict`, parameters, responses, 선택 meta `engine_version`·`baseline_id`·`scene`, rows[run_id·no·state·params·responses·curve], counts). 두 출처를 같은 모양으로 변환해 같은 분석 컴포넌트에 넣음 |
| A3 | 출처 (a) 일괄 예측 배치는 **API 신설 없음** — 기존 `GET /predict-batches/{bid}`·`design-map`·`curves`를 `analysis/adapters/fromBatch.ts`가 변환 |
| A4 | 출처 (b) 해석 DOE는 새 읽기 전용 API `GET /train-does/{doe_id}/result-table`(`samples_rel`·`responses_rel` CSV 읽기, DB 쓰기 없음, LRU, `no-store`, 행 상한 `train_data.max_runs`). 오류 404 `DOE_NOT_FOUND`·`SAMPLES_MISSING`, 409 `DOE_NOT_READY` |
| A5 | 영향도는 프런트 TS 순수 함수: **PRCC**(순위 기반 편상관, 동순위 평균 순위, 역행렬 특이면 "계산 불가")·**표준화 회귀계수(SRC)** + R²(< 0.7이면 회색 안내) |
| A6 | solver vs predict 겹쳐 보기는 **파라미터 이름 집합이 같을 때만**(다르면 비활성 + 차이 이름 안내). 공통 응답만 선택 가능, 색 막대는 합집합 범위 |
| A7 | ④ 배치 결과의 분석 탭은 "⑤ 결과분석에서 열기" 링크 카드로 대체(표·선택 run·경로 복사·단일 예측으로 열기는 ④에 유지) |

**메뉴**: ① 학습데이터 생성 · ② 데이터 정리 · ③ 데이터셋·모델 · ④ 예측(구 "단일 예측": 단일·일괄·준비된 입력) · **⑤ 결과분석(신규 라우트 `/stage/analysis`, 쿼리 `?source=batch&id=` \| `?source=doe&id=`)** · ⑥ 최적화(`/stage/5` 유지). 스텝퍼 표시 순서 `[1,2,3,4,analysis,5]`, 배지 1~6. 알림 링크: `PREDICT_BATCH_DONE` → ④ 배치, `SURROGATE_OPT_DONE` → ⑥ 결과.

**화면**: 머리 출처 세그먼트 `일괄 예측 결과(예측)` | `해석 DOE 결과(해석)` + 드롭다운 + `비교 추가`(`physicsai.analysis.source`). 탭 `변수–응답` · `설계공간 지도` · `영향도` · `커브`(출처 a만). 분석 컴포넌트는 `stages/stage4/batch/*` → `analysis/viz/*`로 이동(계산 규칙·`linalg.ts` 무수정).

시험 V3-S14-1~7(result-table API·`influence.ts` 골든 1e-6·메뉴 6버튼·어댑터·화면·겹쳐 보기·회귀). 서버 확인은 신규 **`E5A-*`**(기존 E4·E5 번호 유지): E5A-1~5(메뉴 순서·배치 출처 값 일치·해석 DOE 영향도·겹쳐 보기·비 LHS/응답 없음 안내).

리스크: 번호 이중 체계(표시 ⑤ 결과분석·⑥ 최적화 대 URL/코드 5 = 최적화), 6버튼 스텝퍼 폭, 분석 컴포넌트 이동 시 시험·스크린샷 경로, 비 LHS·작은 n의 PRCC 신뢰. 미결(권고 채택): `/stage/analysis`로 한 것, `engine_version`·`baseline_id`·`scene` 실제 출처(현재 null 허용), 영향도 허용 범위(S15에서 등급화), 대리모델 Sobol 후속.

## 20. S15 표본 방식 추가 (사용자 결정 2026-10-18, D3-63)

원문: [s15_sampling.md](s15_sampling.md) §20. migration `0012_sampling_kinds`(CHECK 확장만). 새 작업·새 라우트·새 의존성 없음(scipy는 S13에서 이미 의존성).

목표: ④ 일괄 예측에 표본 방식 7개(최적화 LHS, Sobol, 전체 요인, 부분 요인 2수준, Plackett–Burman, Box–Behnken, CCD)를 추가한다. ①·④ 선택창에 방식 설명문과 추천 기본값을 두고, 배치·DOE에 표본 방식을 기록해 ⑤ 영향도를 **정식·참고·비활성**으로 나눈다.

| # | 결정 |
|---|---|
| S1 | ①은 HyperStudy `doe_type` 정의 파일의 4개(FullFact·FracFact·LatinHyperCube·Sobol)를 그대로 보여 준다. pyd가 그 밖의 value를 받는지 확인할 수 없어 새 방식은 ①에 넣지 않음(→ S18에서 플랫폼 생성으로 해결, §23) |
| S2 | ④ 새 kind 7개 `lhs_opt`·`sobol`·`fullfact`·`fracfact`·`pb`·`bbd`·`ccd`. 기존 `lhs`·`table`·`train_doe` 무변경 |
| S3 | **④ 기본 = 최적화 LHS(maximin)** — run 수 자유, 1차원 층화 유지, 상관 작음, AI 학습·대리모델 겸용 |
| S4 | **① 기본 = LatinHyperCube**(설정 `train_data.recommended_doe_type`, 기본 `TYPE_LATINHYPERCUBE`) |
| S5 | 알고리즘은 결정적. Sobol 외는 순수 Python(`random.Random(seed)`), Sobol만 `scipy.stats.qmc.Sobol`을 `physicsai_core/sampling/qmc.py`에서 지연 import(S13의 "API는 numpy 미적재"의 **유일한 예외**) |
| S6 | DB는 `predict_batches.source_kind` CHECK만 확장, 방식 인자는 기존 `source_meta` JSONB. ① DB 변경 없음 |
| S7 | 영향도 등급 `influence_class` = `formal`\|`reference`\|`off`는 **서버가 정함**(n 조건은 s14 그대로: ①은 서버, ④는 프런트) |
| S8·S9 | BBD·CCD 중심점 1개 고정(AI 예측은 같은 입력이면 같은 값). CCD는 면중심(기본)·내접만(외접은 범위 밖) |
| S10 | 설명문은 계약에 고정한 한국어 문구, 프런트 `lib/sampling.ts` 한 곳(서버는 `desc_id`만) |

**방식 목록**(드롭다운 묶음): 공간 채움 — `lhs_opt`(최적화 LHS, 추천)·`sobol`·`lhs`("LHS(무작위 층화)"로 개명); 요인 설계 — `fullfact`·`fracfact`·`pb`; 2차 응답면 — `bbd`·`ccd`; 직접 지정 — `table`·`train_doe`. 설명 상자 4줄(용도 / 장단점 / 영향도·AI 학습 / run 수·제약)과 권장 run 수는 프런트가 계산.

**알고리즘(요지)**: 활성 변수 = lo < hi(고정 변수는 설계에서 빼고 note `FIXED_EXCLUDED`). 코드값 −1/0/+1 → lo/(lo+hi)/2/hi. 품질 `source_meta.quality`(`min_dist`·`max_abs_corr`)는 lhs 계열·sobol만.

| kind | 요약 |
|---|---|
| `lhs_opt` | 후보 5개 LHS 중 점수 최소 + 열 내 교환 2000회(`maximin`: Σd^−15 / `corr`: Σr²), 층 유지, n ≤ 200·k = 20이 수 초 |
| `sobol` | run 수 2^m(4~128), 스크램블, `fast_forward(offset)`, 이어서 추가 `continue_from`(같은 Study·SOBOL·템플릿·활성 변수 일치, 이전 구간 재생성 대조 → 어긋나면 `SEQUENCE_MISMATCH`), 이어서 추가 개수는 `offset`을 나누어떨어지게 |
| `fullfact` | 변수별 수준 2~10(기본 2), 사전식(마지막 변수가 가장 빠름), 정수 변수는 서로 다른 정수 수준, run = ΠL ≤ R |
| `fracfact` | 2수준 해상도 IV·V, 변수 2~11, Montgomery 표 기반 생성자 표(해상도 계산으로 검증), "전체" 칸은 `FULL_FACTORIAL_USED` |
| `pb` | 크기 N = {q+1 (q 소수, q ≡ 3 mod 4)} ∪ {2^m} 중 N ≥ k+1 최소, Paley 순환/Sylvester |
| `bbd` | 변수 ≥ 3, 쌍 방식(활성 쌍마다 4행) + 중심 1행, run = 2k(k−1)+1, k ≥ 6이면 `BBD_PAIRWISE` |
| `ccd` | 변수 2~11, 요인부(k ≤ 4 전체, ≥ 5 해상도 V) + 축점 + 중심 1, `face`(α=1)\|`inscribed`(α=F^(1/4)) |

run 수 표(R = 200, k = 활성 변수): fracfact IV/V = k3: 8/8, k4: 8/16, k5: 16/16, k6: 16/32, k7: 16/64, k8: 16/64, k9: 32/128, k10: 32/128, k11: 32/128; pb = 8(k ≤ 7)·12(k 8~11); bbd = 13·25·41·61·85·113·145·181(k 3~10, k = 11은 221 > R); ccd = 15·25·27·45·79·81·147·149·151(k 3~11); lhs 권장 10×k, sobol 권장 10×k 이상 최소 2^m(최대 128).

**API(새 라우트 없음)**: `BatchSource` union에 7개 추가, 미리보기 응답에 `notes[]`·`sampling{kind,method,desc_id,label,influence_class,influence_note,recommended_count,meta}`, 배치 상세·목록에 `sampling`, `GET /train/doe-types`에 `desc_id`·`recommended`·`influence_class`, `result-table`에 `sampling`·`influence_class`·`influence_note`(`influence_ok` = class ≠ off). problems 추가: `COUNT_NOT_POW2`·`CONTINUE_INVALID`·`SEQUENCE_MISMATCH`·`LEVELS_INVALID`·`DESIGN_UNSUPPORTED`·`GENERATOR_UNAVAILABLE`. notes: `FIXED_EXCLUDED`·`FULL_FACTORIAL_USED`·`BBD_PAIRWISE`·`DUPLICATE_ROWS`·`SEQUENCE_CONTINUED`·`INFLUENCE_TOO_FEW`.

**영향도 등급(s14 규칙 대체)**: ④ `LHS`·`LHS_OPT`·`SOBOL`·`FULLFACT` = formal. `FRACFACT`(해상도 IV·V 문구)·`PB`·`BBD`·`CCD`·`TABLE` = reference(교락·곡률·표본 분포 불명 사유 문구 회색 한 줄). `TRAIN_DOE` = ① 유형 규칙. 최적화 소유 `EXPLORE` = kind대로, `VERIFY`·`FINAL` = reference(최적점 근처 표본). ① `TYPE_LATINHYPERCUBE`·`TYPE_SOBOL`·`TYPE_FULLFACT` = formal, `TYPE_FRACFACT` = reference(RESOLUTION 3 문구 별도), 그 밖 reference. off = 응답 없음·유효 run < max(5, p+2). 계산 `sampling/registry.py` `batch_influence`·`doe_influence`(순수 함수). s14의 "LHS가 아닌 해석 DOE는 영향도 비활성"·`NOT_LHS_TEXT`는 폐지.

**화면**: ④ B 설정 = 방식 드롭다운 1개 + 설명 상자(추천 배지) + 방식별 입력(LHS 계열 범위·개수·시드·기준, Sobol run 수 2^m·이전 Sobol 배치에 이어서 추가, 전체 요인 수준 열, 해상도·α 세그먼트), 미리보기 위 `실제 run N개 · <방식>` + quality + notes. ④ 배치 결과 머리 `표본: <label> · <요약>`. ① DoeGenCard 기본 = `recommended`, 설명 상자. ⑤ 출처 드롭다운 라벨에 방식.

시험 V3-S15-1~15(골든·성질·0012·API·프런트 `lib/sampling.ts` 문구 픽스처 글자 단위 일치). 서버 확인 E4-13-1~4(최적화 LHS 20·Sobol 이어서 추가·BBD/부분 요인 참고 문구·미리보기 2초 안), E1-8-1(① 기본 LatinHyperCube), E1-8-2(선택: pyd가 정의 파일 밖 value를 받는지 — S18 결정으로 취소).

리스크: scipy 버전 차이(Sobol — 만든 값은 DB에 있고 이어서 추가만 대조, 시험은 성질로), API 프로세스의 scipy 적재(0.3~1초·수십 MB), 정수 변수 중복 행(`DUPLICATE_ROWS`), 2수준 설계의 PRCC는 거칠어 참고용. 미결 처리(사용자 2026-10-18 "일단 가보자고"): ①은 4개 유형 유지(후속 → S18), API Sobol 지연 import 허용, ④ 기본 최적화 LHS, 부분 요인 V 참고용, BBD k ≥ 6 쌍 방식.

## 21. S16 VOC 반영 — 단일 예측 실행 목록·조립 FEM 검증·영상 (사용자 VOC 2026-10-19, D3-64)

원문: [s16_voc.md](s16_voc.md) §21. migration `0013_fem_verify`(V2만).

| 묶음 | 요지 |
|---|---|
| V1 | ④ 단일 예측 **실행 목록**(새 DB 없음): jobs 행(params·result)으로 `GET /studies/{id}/predict-runs`(mode·state 필터, 커서 `X-Next-Cursor`)·`GET /predict-runs/{job_id}`(`routers/jobs.py`). 일괄 하위 제외, 재시도 묶음은 최신 1행(`attempts`). 화면 하위 탭 `새 예측`\|`실행 목록`(`physicsai.stage4.singleTab`), 행 선택 = `?job=` 확장 `PredictRunView`(입력·경로 카드 + 기존 결과 카드). 404 `NOT_PREDICT_RUN` |
| V2 | **조립 상태 FEM 검증**: 새 job_type `FEM_VERIFY`(SLOT, stage 4). 예측 결과와 조립 전체 Radioss 해석을 비교 |
| V3 | **영상 저장·표시**: 저장 실패 원인 노출, 선택적 ffmpeg 변환(≤ 1 MiB 목표), 재생 실패 대체 표시 |

**V2 결정**: F1 `PREDICT_VERIFY`는 작업 유형·API·기록을 유지하고 화면 버튼만 "FEM 검증"으로 대체. F2 메시 교체 = 기존 m_2(`commands.mesh`)·`assemble_into` 재사용. F3 제출 = 기존 `HpcJobGateway`(PBS command / scx) — step 키·폴러·상태 매핑·SUBMISSION_UNKNOWN 규칙(§16) 그대로, SCX 잡 폴더 `04_FV-NNN_<ts>`(`scx_naming.fem_verify_job_name`). F4 DB `fem_verifications`. F5 같은 설계점의 성공한 예측이 없으면 **동반 PREDICT**를 같은 트랜잭션에서 만들고 성공 시 `job_end` 훅이 FEM_VERIFY를 넣음(슬롯 미점유 대기). F6 조립 원본 3종 `predict_input`(예측 입력이 조립 상태일 때만)·`train_doe`(① DOE `assem_rel`)·`custom`(허용 루트 + `storage.spdm_roots` 읽기만) — `F/a<n>/assem/`에 **스냅숏 복사**(하드링크 금지). F7 컨투어 두 쪽 같은 범례(요청 fixed, 아니면 `__FV_LEGEND` 요청 줄로 두 h3d의 min·max 합집합). F8 FEM 결과 필드 이름은 `fem_verify.field_map`·요청 `fem.field`로 매핑. F9 활성 유일 인덱스에서 FEM_VERIFY·동반 PREDICT 제외(Study당 동시 `max_active` 4, 같은 예측 + 같은 조립 원본 중복은 409 `FEM_VERIFY_ACTIVE`). F10 재시도: 실패 step ≤ COLLECT면 1단계부터(새 시도 `a<n+1>`·새 원격 폴더), 이후면 그 step부터.

**출처 4종**: `predict_job`·`batch_run`·`values`(템플릿 값; 같은 세트·모델·`applied_values` 일치 성공 예측 재사용, 없으면 동반 PREDICT)·`opt_design`(`best`\|`final_optimum`\|`surrogate_optimum`\|`run`). 폴더 `04_verify/FV-003/a<n>/{mesh,assem,input,result,extract,curves,media,compare.json,responses_fem.csv}` + `verify.json`.

| step | kind(무게) | 처리 |
|---|---|---|
| FV_PREP | INTERNAL 3 | 검증 행·예측 확인, 시도 폴더, 메시 원천·조립 원본 재검사(`INPUT_CHANGED`)·스냅숏 |
| FV_MESH | LOCAL 5 | reuse면 SKIPPED, rebuild면 m_2(§11.4 판정 그대로) |
| FV_ASSEMBLE | INTERNAL 2 | `assemble_into` → starter(eps_mesh면 `INPUT_INVALID`) |
| HPC_SUBMIT·HPC_WAIT·COLLECT | 5·55·10 | PREDICT_VERIFY와 공통 헬퍼 `_verify_hpc.py`(동작·골든 불변) |
| FV_EXTRACT | LOCAL 6 | 응답 MIN·MAX·판정값·`diff_pct`(\|fem\| ≤ `zero_tol`이면 null). mesh_only면 경고 `FEM_RESPONSE_WHOLE_MODEL` |
| FV_CURVE | LOCAL 5 | 모델 데이터셋 큐레이션 → 최신 `CU_T01_CURVES` → SKIPPED, 예측 `curve.json` 계열과 이름 짝(정확 → 대소문자·공백 무시) |
| FV_CAPTURE | LOCAL 8 | §15 `run_capture(extra_meta)` 재사용, **실패는 경고 `CAPTURE_FAILED`만** |
| FV_COMPARE | INTERNAL 1 | `compare.json`·`responses_fem.csv`·`summary`(수치만) |

**DB 0013**: `fem_verifications`(`fv_no`·`source_kind`·`source_ref`·`predict_job_id`·`companion`·`assem_kind`·`input_mode` reuse\|rebuild·`status` WAITING_PREDICT\|RUNNING\|DONE\|FAILED\|CANCELED·`summary` JSONB·`failure_*`·`dir_rel`), 활성 인덱스 제외 조건, 알림 `FEM_VERIFY_DONE`.

**API**(`routers/fem_verify.py`): `POST /studies/{id}/fem-verifications[/preview]`(power), 목록(`predict_job_id`·`batch_id`·`opt_id`·`status` 필터)·상세·`/media`·`/curves`·`/table.csv`, `POST …/cancel`(멱등)·`/rerun`(FAILED·CANCELED만, 409 `FEM_VERIFY_NOT_RERUNNABLE`). `paths/inspect` `purpose:"FEM_ASSEMBLY"`, `GET /fs/roots?include_spdm=true`(SPDM 루트 읽기 전용). 422 `FEM_VERIFY_INVALID` + problems(`SOURCE_NOT_FOUND`·`PREDICT_NOT_SUCCEEDED`·`MESH_MISSING`·`INPUT_MESH_ONLY`·`ASSEMBLY_REQUIRED`·`ASSEM_STARTER_COUNT`·`ASSEM_TOO_LARGE`·`FILE_NAME_UNSAFE` …), 409 `HPC_NOT_CONFIGURED`·`TEMPLATE_NOT_CONFIGURED`·`FEATURE_NOT_AVAILABLE`·`FEM_VERIFY_ACTIVE`·`FEM_VERIFY_LIMIT`. `/status.features.fem_verify`(·`fem_verify_rebuild`). 종료 훅 `fem_verify_on_job_end`(동반 예측 성공 → FEM_VERIFY 생성, 실패 → `PREDICT_FAILED`, 멱등), 감사 `FEM_VERIFY_CREATE`·`CANCEL`·`RERUN`.

**설정** `fem_verify`: `enabled`·`dir_name` `04_verify`·`max_active` 4·`field_map` {}·`legend_subcase` 1·`auto_isolate_cushion` true·`zero_tol` 1e-12·`max_assem_files` 500·`max_assem_bytes` 2 GiB·`include_scan_max_bytes` 16 MiB·`max_pred_h3d_copy_bytes` 4 GiB.

**화면**: 진입 버튼 "FEM 검증" 5곳(④ 단일 결과·④ 일괄 선택 run·⑤ 예측 출처 행·⑥ 최적 설계/마무리/대리 최적/검증 run). 라우트 `/stage/4/verify`(목록, `?new=1`)·`/stage/4/verify/:fvId`(상세: 진행 4단·`ScxJobStatus`·탭 `응답`\|`커브`\|`컨투어`\|`입력·경로`).

**V3 영상**: TCL이 저장 뒤 파일 존재·크기 확인(`VID_SCOPE` page\|window), 방향별 실패는 작업당 경고 1건 `CAPTURE_VIDEO_FAILED` + media `video_error`. 선택적 ffmpeg 변환 `capture.ffmpeg.{exe,probe_exe,args,probe_args,ladder,timeout_s}`(비어 있으면 건너뜀, H.264·yuv420p·`+faststart`, 목표 `capture.video_target_bytes` 1 MiB까지 `ladder` 단계 재인코딩, 원본 `media/raw/` 보존, 초과 시 `CAPTURE_VIDEO_OVER_TARGET`, 변환 실패 `CAPTURE_VIDEO_TRANSCODE_FAILED`, 재생 불가 코덱 `CAPTURE_VIDEO_NOT_PLAYABLE`). avi는 `allow_avi: false`면 설정 경고 + 실제 mp4 저장. 프런트 `components/MediaVideo.tsx`: gif → `<img>`, avi·`playable=false`·재생 오류 → "브라우저가 이 형식을 재생하지 못합니다 — 받기". `/status.capture`에 `video_target_bytes`·`transcode`·`video_ext_effective`.

시험 V3-S16-1~26. 서버 확인 E4-14-H1, F1~F8(조립 입력·FEM 필드 이름·부품 격리·범례·커브 이름·SCX·SPDM 읽기만·응답 상식 범위), V1~V7(영상 로그·크기·ffprobe 코덱·설정·브라우저 오류·libx264·page 대 window).

리스크: 예측 h3d 대 Radioss h3d 필드 이름 불일치(`field_map`), mesh_only 비교는 조립 전체 값(경고 + 컨투어 부품 격리), 커브 이름 대응 끊김(unmatched 표시), FEM 1건이 수 시간(슬롯 미점유), 예측 h3d 사본 수백 MB, ffmpeg 번들 안 함(경로만 설정), 원격 `04_V-NNN`(PV)과 `04_FV-NNN`(FV) 공존. 미결 9(응답 쿠션 한정 TCL, `field_map` 기본값, 커브 수동 매핑, 일괄 FEM 검증, PREDICT_VERIFY 폐지 시점, ffmpeg 표준화, `video_scope` 기본, SPDM 조립 원본 정책, `04_verify` 정리 범주).

## 22. S17 성능 정의·다목적 내장 최적화 (사용자 VOC·결정 2026-10-19, D3-65)

원문: [s17_multiobj.md](s17_multiobj.md) §22. migration `0014_multiobj`(Revises 0013). 새 런타임 의존성 없음(numpy·scipy는 §18에서 추가).

> 후속(2026-10-20): 알고리즘 `ga`·`nsga2`, 검증 방식 `none`, 범주 `baseline`, HyperStudy 레거시화는 [opt-native.md](opt-native.md)를 따른다. P7 "NSGA-II를 직접 구현하지 않는다"는 opt-native.md ON-6으로 대체된다.

VOC: "쿠션 최적화(내장)에서 원본처럼 성능 정의하고 성능을 목적 또는 제약에 넣을 수 있게. 멀티목적 기능도." 결정: 멀티목적은 **파레토 전선을 보여 주고 사용자가 고르는 것이 기본**, 화면 가중치 슬라이더로 가중합 추천점을 강조, 고른 해는 예측 검증과 FEM 검증(§21)으로 보낼 수 있어야 한다.

| # | 결정 |
|---|---|
| P1 | **성능 = 템플릿 응답 정의(`param_sets.responses`) 확장**(새 테이블 없음). 행 `{name, unit, spec}`의 `spec.source`에 `CURVE`를 추가(H3D는 원본 NAME\|SUBCASE\|DATATYPE\|COMPONENT\|LAYER + stat). ⑥에서 편집하면 기존 `PUT /param-sets/{id}/responses`. 화면 이름만 "성능" |
| P2 | **역할(목적·제약·관찰)은 `surrogate_opts.settings`에만**(템플릿에 넣지 않음) |
| P3 | 지표 id **`perf:<NAME>`**(stat 적용 값, `METRIC_RE`·프런트 `METRIC_PATTERN` 확장). `curve:`·`resp:`·`tbl:`은 계속 받고 화면은 `perf:`만 씀 |
| P4 | 값 계산 순수 함수 `stage4_predict/performance.py`(`PerfDef`·`perf_defs`·`perf_value`·`perf_label`)를 API·워커가 공용 |
| P5 | H3D 성능은 run 폴더 `H3D_REQUESTS.txt` 줄과 정의를 비교, 다르면 null + 사유 `SPEC_CHANGED`. 진행 중 최적화가 쓰는 성능의 정의 변경·삭제는 409 `PERF_IN_USE_BY_OPT`(단위만 바꾸기는 허용). `RunMetrics.requests` 추가 |
| P6 | 다목적은 **`SURROGATE_OPT` 확장**(같은 4 step, `settings.objectives` 길이로 분기). 새 job_type은 `PB_RESP_EXTRACT` 1개뿐 |
| P7 | 다목적 후보 = 예측 전선(Das–Dennis 격자 + 증강 Chebyshev + DE) + HVI 활용 1개 + ParEGO(EI×PoF) k−1개. numpy·scipy만 |
| P8 | 비지배·HV·가중 추천은 표준 라이브러리 전용 `surrogate/pareto.py`(API 프로세스 numpy 미적재 원칙) |
| P9 | **검증된 해(실제 예측 체인 값)와 대리모델 예측 전선을 엄격히 구분**. 추천·`best`·FINAL은 검증된 해에서만 |
| P10 | 고른 해의 예측 검증 = 최적화 소유 추가 검증 배치(iters kind `EXTRA`). FEM 검증은 §21 API |

**성능 정의·추출**: CURVE spec은 `{source, series, stat}`(series null = 첫 계열, stat `MAX\|MIN\|ABSMAX`). 사유 코드 `SPEC_CHANGED`·`NOT_EXTRACTED`·`NO_VALUE`·`NO_CURVE`·`SERIES_MISSING`(`REASON_TEXT` 한국어). ④ RESPONSE_EXTRACT는 H3D(TCL) 추출 뒤 CURVE 값을 `curve.json`에서 채워 `responses_pred.csv`에 모두 씀(CURVE만이면 TCL 미실행). ①-6·PV는 CURVE를 조용히 건너뜀(`SILENT_REASONS`). 끝난 배치의 H3D 성능 다시 추출 = 새 job `PB_RESP_EXTRACT`(stage 4, SLOT, `notify_success=True`): `PX_PREP`(INTERNAL 5) → `RESPONSE_EXTRACT_RUNS`(LOCAL 90, run마다 `_backup` 후 재추출) → `PX_TABLE`(INTERNAL 5, `predict_batch_runs.responses` 갱신). `POST /predict-batches/{bid}/extract-responses`(power). 409 `BATCH_NOT_DONE`·`BATCH_OWNED_BY_OPT`·`FEATURE_NOT_AVAILABLE`·`STUDY_JOB_BUSY`, 422 `NO_H3D_PERFORMANCE`. 하위 PREDICT의 `result.response_table`은 갱신하지 않음(미결 3).

**최적화 문제 정의**: 요청 `objectives`(1~3, min\|max)·`constraints`(≤ 5, `<=`·`>=`·`range`, `==` 없음)·`observe`(≤ 10)·`weights`(선택 → **ON-C4: 목적 2개 이상이면 필수, 방향 `sense`도 필수 — 비면 422 `OPT_CRITERIA_REQUIRED`, [opt-native.md](opt-native.md) ON-C4**). 단수 `objective`도 받음(`settings.objective = objectives[0]` 계속 기록). `settings`에 `mode`(single\|multi)·`performances`(참조 성능 정의 스냅숏) 추가. problems 신규: `OBJECTIVES_RANGE`·`OBJECTIVE_DUPLICATE`·`OBJECTIVES_CONFLICT`·`OBSERVE_INVALID`·`WEIGHTS_INVALID`·`PERF_UNDEFINED`·`PERF_MISSING_IN_BATCH`(action `extract`)·`PERF_EXTRACT_UNAVAILABLE`, `CONSTRAINT_INVALID` 확장. 재사용 최소 점 판정은 모든 목적·제약 값이 있는 성공 run 수로 계산.

**다목적 알고리즘(m = 2·3, m = 1은 §18 그대로)**:
- 내부는 모두 최소화(sign 통일). **HV 정규화 틀**은 r = 1의 SO_COLLECT에서 탐색 자료로 1회 확정(`surrogate_opts.hv_frame`, 이후 불변), 기준점 R = 1 + `mo_ref_offset` = 1.1.
- SO_FIT: 목적마다·제약마다 GP 1개(실패하면 그 모델만 RBF + `GP_FALLBACK_RBF`). `fit.per_objective`로 목적별 품질.
- SO_PROPOSE 1단계 예측 전선: 가중 격자 W(m = 2 → 11개, m = 3 → 28개, 사전순)마다 증강 Chebyshev(ρ `mo_rho` 0.05) + 제약 위반 벌점을 `_de`로 최소화 → 예측 만족(PoF ≥ 0.5)이고 μ 기준 비지배인 점. `iter_NN/predicted_front.csv`, DB `predicted_front`(≤ 28점).
- 2단계 후보: c₁ = 예측 전선 점 중 HVI 최대(모두 0이면 목적 공간 최대 최소거리). c₂… = ParEGO(가중치 순열 `default_rng(seed·1000 + r)`, 반복 간 비중복, y_w 위에 GP 적합 후 EI×PoF를 DE로 최대화, `range` PoF = Φ((hi−μ)/σ) − Φ((lo−μ)/σ)). RBF면 ParEGO 대신 s_w 최소 + 거리 규칙. 후보 기록에 `role`(hvi\|parego\|rbf)·`weight`·`predicted_objectives`·`predicted_std`.
- 구현 보강(D3-65 보강 3): 3목적은 HVI 후보 ⌈k·`mo_hvi_share_m3`⌉개(0.5, 하나씩 전선에 더하며 재순위), 나머지는 ParEGO 획득값 × exp(−`mo_front_prox_m3`(6.0)·예측 전선 정규화 거리).
- `pareto.py`: `dominates`·`nondominated`·`hypervolume`(m = 2 스윕, m = 3 슬라이스, 정확)·`hv_improvement`·`normalize`·`recommend`. 골든 HV 2D 0.37, 3D 0.256.
- 수렴: HV_t(검증 만족 설계, 고정 틀) 개선율 < `tol_rel`이면 `CONVERGED`(r ≥ 2). `iters`에 `hv`·`front_size`·`improvement_rel`. 정지·실패 코드는 §18과 같음(`TOO_FEW_POINTS`는 목적·제약 모두 있는 점 기준). 시드 식(예측 전선 DE `seed·100000 + r·1000 + j`, ParEGO 재시작 +500+j, DE +700+j)은 원문 §22.5.7. 반복당 GP ≤ 17개·DE ≤ 37회, 기본 규모 1분 이내 목표.

**가중 추천점(§22.6, 화면 슬라이더·FINAL·알림 공용)**: w̄ = u/Σu(Σu = 0이면 균등), 검증 파레토 해 안에서 목적별 0(최선)~1(최악)로 정규화한 g의 가중합 S의 최소가 추천. 동점은 g₁ 작은 쪽 → (iter_no, doe_no). 예측 전선 점은 점수만 표시하고 추천 대상 아님. 골든 표는 `backend/tests/data/s17_recommend.json`(D3-65 보강 3 ②: f₂ max 행 정정 S_A 0.0·S_B 0.4236·S_C 0.7153·S_D 1.0, 추천 A). `best`·FINAL·알림은 생성 시 `settings.weights`, 슬라이더는 localStorage만.

**결과·추가 검증·FINAL**: 검증 파레토 해 = 최적화의 모든 검증 run(EXPLORE·REUSE·VERIFY·EXTRA, FINAL 제외) 중 만족 유효 설계의 비지배 집합(API가 `pareto.py`로 매번 계산, 같은 설계 평균, 키 `"<iter_no>:<doe_no>"`). 예측 전선 = 마지막 반복의 `predicted_front`("대리모델 예측(미검증)"). `POST /surrogate-opts/{oid}/verify`(power, 등록자 또는 관리자): 1 ≤ 점 ≤ `max_extra_points`(10), DONE만(409 `SURROGATE_OPT_NOT_DONE`), 진행 중 EXTRA가 있으면 409 `SURROGATE_OPT_EXTRA_ACTIVE`, 범위 밖 422(`BOUNDS_OUT_OF_RANGE`)·점 수 초과 422 `EXTRA_POINTS_RANGE` → 최적화 소유 PREDICT_BATCH(source table) + iters kind `EXTRA`를 한 트랜잭션에서 생성. 종료 훅은 EXTRA면 반복 작업을 넣지 않고 기존 `PREDICT_BATCH_DONE` 알림이 나감(`BATCH_OWNED_BY_OPT` 가드 대상 아님). FINAL 2행 = 기준안 + 가중 추천점. 다목적 알림: "내장 최적화 SO-002 완료 — 파레토 해 6개 · HV 0.712 · 추천 … (반복 3 · 검증 12 run)". FEM 검증 연동: `POST /studies/{id}/fem-verifications` + `source:{kind:"opt_design", opt_id, pick:"run", iter_no, doe_no}`(검증된 해만, `features.fem_verify`, 예측 전선 점은 비활성 "먼저 예측 검증").

**DB(0014)**: `surrogate_opt_iters`의 kind CHECK에 `EXTRA`, 열 `hv`·`front_size`·`predicted_front`(JSONB ≤ 28점), `surrogate_opts.hv_frame` JSONB. downgrade는 EXTRA 행이 있으면 실패(데이터 보존). `PB_RESP_EXTRACT`는 코드만 추가(jobs에 job_type CHECK 없음).

**API 요약**: 상세 `GET /surrogate-opts/{oid}`에 `mode`·`objectives`·`constraints_def`·`observe`·`weights`·`pareto{hv, frame, front, recommended_key, predicted_iter, predicted}`·`hv_history`·`runs[].{objectives, observed, reason, on_front, kind}`·`can_verify_more` 추가(단일 목적은 `pareto`·`hv_history` null, 기존 키 유지). 미리보기에 `mode`·`performances[]`. `runs.csv`는 `objective_1..m`·제약·`obs:<label>`·`reason` 열. `/status.surrogate_opt`에 `max_objectives`·`max_observe`·`max_extra_points`. 설정 `surrogate_opt.{max_objectives 3, max_observe 10, max_extra_points 10, mo_lattice_h2 10, mo_lattice_h3 6, mo_de_maxiter 100, mo_rho 0.05, mo_ref_offset 0.1, mo_gp_restarts 4}` + 구현 추가 `mo_hvi_share_m3`·`mo_front_prox_m3`.

**화면(⑥ 내장 모드)**: 새 최적화 카드의 목적·제약 입력을 **"성능" 표 1개**(이름·출처 H3D\|커브·Subcase·DataType·Component·Layer·Stat·단위·역할·값·재사용 시 `값 있는 run n/N`)로 교체. 역할 = 사용 안 함 / 목적 최소·최대 / 제약 ≤·≥·범위 / 관찰. 정의 편집 + `성능 정의 저장(템플릿)`(저장 전에는 역할 지정 불가), `PERF_MISSING_IN_BATCH`면 행에 `성능 다시 추출` 버튼. 목적 ≥ 2이면 가중치 슬라이더(생성 시 값). 결과(`/stage/5/surrogate/:optId`): 단일 목적은 기존 화면(관찰 열 추가), 다목적은 파레토 카드(2목적 산점도, 3목적 쌍 그림 3개 — 지배 점 흐림·위반 ×·예측 전선 속 빈 점 토글·가중 추천 링) → 가중치 카드(슬라이더 `physicsai.stage6.weights.<optId>`) → 파레토 표(단일 예측으로 열기 / 선택 해 예측 검증 / FEM 검증 / CSV) → HV 그래프 → 목적별 품질 표 → 최적안 대 기준안 → 검증 run 표(EXTRA는 반복 "추가") → 파일 위치. 기준안 ◇는 생략(API에 다목적 기준안 값 없음).

시험 V3-S17-1~13(0014·성능 정의 검증·`perf_value` 골든·추출 경로·`pareto.py` 골든·해석 전선 HV 근사(ZDT1 0.87667·DTLZ2 0.80740, 허용 0.04)·다목적 수학(ZDT1 0.80·ZDT2 0.70·DTLZ2 0.70, 루프는 `slow` 마커)·SO_COLLECT·가중 추천 골든(Python·TS 공용 픽스처)·API·화면·e2e). 서버 확인 E4-17-1~7(성능 2개 정의·재사용 다시 추출·2목적 12 + 3×4·반복당 < 60 s·예측 전선 점 검증·FEM 검증·409 문구).

리스크·미결: 목적별 GP는 n < 4·d이면 전선 품질 낮음(탐색 run 늘리기 안내), HV 틀 고정으로 개선율 과장 가능, 가중합은 오목 전선 해를 못 고름(표에서 직접 선택이 기본), 템플릿 성능 추가 시 ④ 예측마다 HyperView 추출 증가, 다시 추출은 하위 PREDICT 결과 표 미갱신(미결 3), 병합 순서 S16 → S17 고정. 미결: 3목적 평행 좌표 추가 여부, 실패·취소 최적화의 EXTRA 허용, 수렴 "1회 대 연속 2회".

## 23. S18 ① 학습 DOE 플랫폼 동시 생성 (사용자 VOC·결정 2026-10-19, D3-66)

원문: [s18_doe_parallel.md](s18_doe_parallel.md) §23. migration `0015_doe_platform_gen`(Revises 0014). 새 의존성·라우트·job_type 없음.

> 후속(2026-10-20): 생성 방식 `hyperstudy`(`features.train_doe`)는 레거시 선택 기능(미설정 시 화면에서 숨김 — [opt-native.md](opt-native.md) §4). native ①-3 DOE는 생성 방식 `platform`의 한 경로(LHS(native)만 — [geometry-engine.md](geometry-engine.md) §7.3.3).

VOC: "① DOE 생성할 때 웹에선 동시 실행이라 표시되는데 실제로는 순차로 돈다. 4개 정도는 동시로 실행하게 해 줘." 결정: S15 §20.3 안 B 채택 — ① 학습 DOE 생성을 플랫폼 실행기로 옮긴다. "어차피 native(자체 형상 엔진, 프로젝트 문서 `contracts/geometry-engine.md`)로 바꿀 거니 HyperStudy에 힘쓰지 말자" → hstbatch 모드는 코드 무변경 **호환 모드로 표시만**, 플랫폼 모드는 ④ BP_GEN 체인·`run_parallel`·S15 sampling을 재사용해 **최소 변경으로 동시 생성**, 원본 출력 일치는 DG_SCAN·TD_SOLVE·큐레이션이 동작하는 파일·폴더 규칙만, 형상 생성은 나중에 native로 바꿔 끼울 **경계 한 곳**.

원인 추정(서버 확인 전): 원본 앱도 `hstbatch -multiexec M`을 쓰며, pyd 안의 입력 생성(SimLab m_1·HyperMesh m_2)은 run마다 순차로 도는 것으로 보인다. 화면의 "실행 중 4"는 `HstRunTracker`가 run 폴더 수로 계산한 값이라 실제 프로세스 수가 아니다.

| # | 결정 |
|---|---|
| G1 | job_type `TD_DOE_GEN`과 step 키 3개(DG_PREP·HST_GEN_RADIOSS·DG_SCAN)·가중 유지. `HST_GEN_RADIOSS`가 `train_does.generator`로 분기(HYPERSTUDY = 기존 hstbatch, PLATFORM = `run_parallel`). 표시 라벨만 "입력 생성(run별)" |
| G2 | run별 체인 m_1 GEOM_UPDATE → m_2 MESH → m_3 조립을 ④ `batch._gen_one`에서 공용 `worker/physicsai_worker/steps/run_chain.py`로 추출(④ 동작 불변, V3-S9-7 무수정 통과) |
| G3 | 형상 생성 경계 = `run_chain.geometry_update(...)` 한 함수(출력 = `{predict.simlab_mesh_name}` 경로). D3-66 보강: 교체 단위는 `build_run_inputs` 수준도 가능(엔진 선택은 `run_chain.select_engine`, 이번엔 altair만) |
| G4 | 표본 = S15 `build_matrix`(8 kind, `ranges`·`continue_from`·`table`·`train_doe` 제외). 범위는 ①-2 표, 상한 `train_data.platform_max_runs` |
| G5 | API는 검증·run 수만(`lhs_opt`는 같은 count·seed의 `lhs`로 대신 검증). 실제 행은 워커 DG_PREP이 계산해 `train_doe_points`에 저장 |
| G6 | migration 0015: `train_does.generator`(HYPERSTUDY\|PLATFORM)·`sampling` JSONB, 새 `train_doe_points`(run별 `gen_state` PENDING\|RUNNING\|DONE\|FAILED, `values`·`applied_values`, 수치·상태만). 플랫폼 DOE의 `doe_type` = 방식 이름(`LHS_OPT` 등), `options` = 표본 입력값 → `doe_influence`가 `batch_influence`로 등급 계산 |
| G7 | run 폴더 규칙은 다운스트림에 필요한 것만: `D/{train_data.platform_run_root}/run__{n:05d}/{m_1,m_2,m_3}`, `input_rel` = m_3, starter = m_3 직계 `starter_glob` 일치·eps_mesh 아님 정확히 1개 |
| G8 | 동시 수 M = 사용자 입력(1~`max_multi_execution`, 화면 기본 `platform_parallel_default` 4). 자식 전부가 제한기 그룹 1개(Windows Job Object 1개)를 나눠 씀. 라이선스는 자동 감지하지 않고 안내만 |
| G9 | `on_run_failure` = `fail`(기본: 모든 run 시도 후 실패가 있으면 `GEN_PARTIAL_FAILED`, 재시도는 실패·미완료 run만) \| `continue`(성공 run만 등록, 경고 `PARTIAL_OUTPUT`) |
| G10 | API 기본은 하위호환: `generator` 생략 시 `sampling`이 있으면 platform, 없으면 hyperstudy. 화면 기본 = `train_data.doe_generator_default`(platform) |

**다운스트림 규칙(코드에서 역으로 확정)**: DG_SCAN은 `D/{run_dir_glob}`(이름 = run_key)와 starter 1개로 `input_rel`을 정하고, TD_SOLVE·SCX는 input_rel 직계 파일을 쓰며, RI_SCAN은 폴더 이름 `^run__\d+$`, ④ `train_doe`는 `D/samples.csv`(`run_key,<파라미터…>`, PARSED)를 본다. 플랫폼 모드는 samples.csv를 DB `applied_values`로 직접 쓰고, HyperStudy 전용 파일(유형 json·include TCL·런처·`INPUT_HST_RUN.json`)은 만들지 않는다. `D/doe.json`을 새로 기록. 구현 메모(이슈 #7): `train_data.run_dir_glob`은 목록(기본 `["approaches/doe_*/run__*","*/approaches/doe_*/run__*"]`, 옛 문자열 기본은 자동 정규화), 0건이면 `*/` 재탐색, 같은 run_key 중복 폴더는 제외 + 경고.

**API**: `POST /studies/{id}/jobs`(`TD_DOE_GEN`) params 확장 — platform `{generator, sampling{kind,count,seed,criterion…}, multi_execution, on_run_failure, radioss_assem_path}`, hyperstudy는 기존 그대로. 금지 조합 422, 플랫폼 조합 오류는 422 `DOE_SAMPLING_INVALID` + problems(S15 코드, 상한은 `platform_max_runs`), notes는 작업 생성 `warnings`. 응답: `TrainDoe.generator`·`sampling{kind,label,desc_id,meta}`·`gen{total,pending,running,done,failed}`, result-table `sampling`(`td_<kind>`), `/status.limits.configured`에 `doe_generator_default`·`doe_platform_parallel_default`(= min(설정, max_multi_execution))·`doe_platform_max_runs`, `features.train_doe_platform`(템플릿 `geom_update` + altair `simlab_path`, HyperStudy 자원 불필요).

**step 처리(키·가중 불변)**: DG_PREP은 platform이면 표본을 계산해 `train_doe_points`에 삽입하고 `doe.json`을 쓴다(tpl sha가 바뀌면 전부 PENDING + `TPL_CHANGED_REGEN`). `gen_platform`(`steps/stage1_train_data/doe_platform_gen.py`)은 DONE이 아닌 행을 `run_parallel`로 M개 동시 실행해 run마다 `run_chain.build_run_inputs`를 호출, 진행 라벨 "입력 생성 실행 n · 대기 …". DG_SCAN은 DONE 행만 검사해 `samples.csv`·runs.json·`train_runs`·READY. 취소는 그룹 종료 + RUNNING 행 PENDING(워커 + `job_end` 훅 `reset_running_points`). 재시도는 같은 tpl이면 DONE run 유지.

**설정**: `train_data.doe_generator_default` platform · `platform_parallel_default` 4 · `platform_max_runs` 500 · `platform_run_root` `approaches/doe_1`(`run_dir_glob`과 일치 검증, 검증은 `validate_stages.py`).

**화면(①-3 `DoeGenCard`)**: 생성 방식 세그먼트 `플랫폼 생성(동시 실행)` | `원본 HyperStudy(호환)`(저장하지 않음). 플랫폼은 방식 드롭다운 8개(추천 `lhs_opt`)·방식별 입력·`실제 run N개`·설명 상자(`td_<kind>`)·동시 실행 수·체크 `실패한 run이 있어도 성공한 run으로 DOE 완료`. HyperStudy 모드는 기존 UI + 회색 줄(`HS_NOTE` 새 문구, "호환 모드 — hstbatch -multiexec로 실행합니다. 실제 동시 실행 수는 HyperStudy가 정하며 입력 생성이 run마다 순차로 될 수 있습니다."). 결과 줄에 `생성 완료 d · 실패 f / 전체 t`. 지원 범위 밖이어도 실행을 막지 않고 서버 422 problems를 표시.

시험 V3-S18-1~10(동시 실행 하한은 가짜 SimLab barrier로 결정적으로 증명, 상한은 trace 구간, **시각 비율 단언 없음**). 서버 확인 E1-9-1~5(동시 수 감시·결과 회수·자원·취소·선택으로 hstbatch 관찰).

리스크: 라이선스(동시 4가 한도를 넘으면 run 실패 → 동시 수를 낮춰 재시도), 그룹 Job Object의 공유 메모리 한도, 같은 CAD 동시 실행 시 SimLab 프로필 충돌(④ E4-9-2와 같은 조건), 플랫폼 표본 값은 HyperStudy와 다름, 정수 형식 중복 행, lhs_opt 큰 n(워커에서 수십 초), native 출력이 단일 rad가 아니면 경계 재정의. 미결: 화면 기본 platform, 실패 기본 `fail`, ① mesh_only 비범위, 상한 500, hstbatch 숨길 시점, 레거시 4종 자동 매핑 생략.

## 24. S19 후속 — GPU 조회 실패 대응·⑤ perf 서버 계산 (사용자 승인 2026-10-19, D3-67)

원문: [s19_followup.md](s19_followup.md) §24. **migration 없음**(head `0015_doe_platform_gen` 유지), 새 job_type·step·라우트 없음.

> **철회(2026-10-20, 사용자 결정)**: 원 계약의 "④ 일괄 예측 하위 PREDICT의 GPU 동시 실행(GPU 동시 예측)"은 구현 중 철회됐다. 이 문서는 그 내용을 옮기지 않는다. ④ 일괄 예측은 S18과 같이 SLOT 단일 FIFO로 1개씩 예측한다. §2.3 R3-9 참고.

유지된 범위 두 가지:

**(1) GPU 조회 실패 대응(B-GPU·F-GPU)**
- 조회는 새 워커 스레드 `worker/physicsai_worker/gpu_monitor.py` `GpuMonitor`가 맡고, 하트비트(`heartbeat_once`)는 nvidia-smi를 직접 실행하지 않고 **캐시**를 읽는다(조회가 막혀도 온라인 판정이 흔들리지 않음). 환경 점검 `gpu.detect`는 직접 조회하되 같은 제한 시간을 쓴다.
- 설정(`WorkerCfg`, 검증 `config/validate_gpu.py`, 예시 yaml은 주석): `worker.gpu_query_timeout_s` 15(1~120, 요약·환경 점검 공통) · `worker.gpu_backoff_after` 3(1~100) · `worker.gpu_backoff_max_s` 300(0 또는 `resource_sample_interval_s`~3600, 0 = 늘리지 않음). 시간 초과 문구 `nvidia-smi 응답 시간 초과({n}초): {exe}`.
- 간격: 연속 실패 k회 < `gpu_backoff_after`면 base(`resource_sample_interval_s`), 아니면 `min(gpu_backoff_max_s, base × 2^(k − after + 1))`. base 10·after 3이면 10·10·20·40·80·160·300…, 성공하면 k = 0.
- 진단 로그(워커 로그 `physicsai_worker`, **상태 전이 때만 1줄**, 작업 로그·DB에는 쓰지 않음): OK → ERROR WARNING `GPU 조회 실패(ERROR): … — 회복될 때까지 같은 실패는 기록하지 않습니다` / 시작 → NOT_FOUND INFO / 실패 종류 변경 WARNING / k = after 순간 WARNING `GPU 조회 연속 k회 실패 — 조회 간격을 늘립니다(최대 N초)` / 회복 INFO `GPU 조회 회복: <GPU 이름> n개(실패 k회, 경과)`.
- API(`/resources`, 모두 선택): 기존 `gpu_status`·`gpu_message` 재사용 + `gpu_fail_streak`·`gpu_sampled_at`·`gpu_next_query_at`(지연 중일 때만). 옛 워커 표본은 null.
- 화면: 자원 칩의 `title`이 ERROR·NOT_FOUND이면 `GPU 조회 실패 — <gpu_message>`(NOT_FOUND는 `GPU 없음 — `), 연속 2회 이상이면 `(연속 N회 · 다음 조회 HH:mm:ss)` 추가(순수 함수 `shell/gpuText.ts` `gpuFailTip`·`gpuStreakText`). 서랍 `WorkerResourcePanel`에 회색 줄(`gpu-message`, 연속 실패 줄)을 보이게 둔다.

**(2) ⑤ `perf:` 지표 서버 계산(B-PERF·F-PERF)** — D3-65 보강 3 ⑤ 해소
- `GET /predict-batches/{bid}/design-map`이 `performance.perf_value`로 `perf:` 값을 계산한다. 성공 run마다 `runs[].perf{name: 값\|null}`·`perf_reason{name: 사유 코드}`. 옛 추출 run(H3D `NOT_EXTRACTED`)만 결과 표 값으로 대체(CURVE는 대체 없음). 성공이 아닌 run은 null.
- 스키마(기본값 있음, 기존 응답 하위호환): `metrics[].spec_changed`(perf 지표, 성공 run 중 SPEC_CHANGED 수), `counts.spec_changed`(SPEC_CHANGED 성능이 있는 성공 run 수), `reason_text{코드: 한국어}`. 지표 순서는 curve → resp → tbl → **perf(끝)**, 값이 있는 run이 1개 이상인 성능만 목록에 둔다(저장된 선택·기본 지표 불변). 파일 추가 읽기 없음(`load_run_metrics` LRU 재사용).
- 프런트: `perfColumns.ts`의 `perfValue`·`withPerfMetrics`를 삭제하고 `fromBatch.ts`가 서버 값을 사용(design-map 실패 시 결과 표 값). 결과 표 칸 `title`에 사유, SPEC_CHANGED 칸은 `—` 옆 회색 "정의 변경", `counts.spec_changed > 0`이면 안내 줄("성능 정의가 바뀐 뒤 다시 추출하지 않은 run N개는 성능 값이 비어 있습니다 — ⑥ 최적화 설정의 성능 표에서 '다시 추출'").

시험 V3-S19-1(설정)·2(제한 시간, 가짜 nvidia-smi hang)·3(`GpuMonitor` 로그 전이·간격 수열)·4(`/resources`)·12(design-map perf)·13(프런트). V3-S19-5~10(동시 예측 시험)은 철회로 무효. V3-S19-11 예외 1건: V-SM-6 `test_no_timeout_key_in_schema`는 `worker.gpu_query_timeout_s`를 제외(작업 실행 시간 한도 없음이라는 취지는 유지, V3-S9 시험 무수정). 서버 확인 E0-8-1~3(GPU 조회, e2e-checklist). E4-19 블록은 철회되고 perf 확인만 E5A-6으로 남긴다.

다음 계약 없이 처리한 항목: S16 minor 4건(M0), 문구·시험·그림 정리, 300줄 초과 파일 분할과 `batch_matrix`의 sampling 이동(R-B·R-F, `docs/refactor-plan.md` §8), 문서 이관(이 절).

## 변경 메모(D3-n) — 구현 중 계약과 다르게/구체화한 곳(Plan 확인 요청)

- **D3-1 (S1, §3.4 재시도 시작 지점 표시명)**: `JobStep`에는 표시명(label)이 없다(API 모양 불변 유지). 시작 지점 문구는 `{step_no}. {표시명}`에서 표시명을 해당 step이 `Job.current_step_key`와 같으면 `current_step_label`(실패 작업은 실패한 step이 current), 아니면 `step_key`로 쓴다. 첫 재개 step이 1이면 "처음(1단계)". 구현 `frontend/src/components/JobRetryButton.tsx` `retryStartText`. (Plan 승인)
- **D3-2 (S1, §3.4 재시도 후 카드 갱신)**: `JobInline`은 `useLatestJob`의 `track`을 받지 않으므로(호출처 56곳), 재시도 성공 시 `hooks/jobRetried.ts`의 구독(`emitJobRetried(이전 id, 새 작업)`)으로 알리고, 이전 작업을 추적 중이던 `useLatestJob`이 새 작업으로 갈아탄다. 재시도 버튼은 Study 문맥(`StudyProvider`) 밖에서는 보이지 않는다(`study.status` 판단 불가). (Plan 승인)
- **D3-3 (S1, §3.2 retry 409 `STUDY_CLEANUP_RUNNING`)**: R3-4는 S3(`STUDY_CLEANUP` job_type)가 생길 때 함께 넣는다. S1 단계에서는 retry 동작 변경 없음. (Plan 승인 — S3에서 D3-9·D3-24로 이행 완료)
- **D3-4 (S1, §3.2 `study.json` 갱신)**: 기존 `study.json`을 읽어 `title`만 바꿔 쓴다(읽기 실패·형식 오류면 `id`·`project_id`·`title`로 새로 씀). 원자적 쓰기는 `physicsai_core.fileutil.write_json_atomic`(같은 폴더 `.study.json.tmp` + `os.replace`, 삭제 호출 없음 — 쓰기 실패 시 임시 파일이 남을 수 있음). 보관 해제가 이미 `ACTIVE`인 Study에 대해서는 감사 행을 남기지 않는다(멱등, 상태 변화 없음). (Plan 승인 — 임시 파일 방식은 D3-21로 대체: 고정 이름 `.study.json.tmp` 폐지)
- **D3-5 (S1, §3.4 목록·목)**: Study 목록 필터 선택은 `localStorage` 키 `physicsai.studyList.filter`. 목 `GET /jobs/{id}`의 `can_retry`를 서버와 같게 `CANCELED`도 포함하고 본인 작업은 power 이상일 때만으로 맞췄다. 기존 "보관된 Study 포함" 체크박스는 탭으로 대체. (Plan 승인)
- **D3-6 (S2, §4.3 구현 구체화)**: ① 프런트에 `api.dataset(id)`(`GET /datasets/{id}`, 기존 백엔드 API)와 목 라우트를 추가했다(API 모양 불변). ② 계열 색 `--series-1~5`는 흰 배경 대비 ≥ 4:1로 정했고, 앱에 다크 테마가 없어 다크 대비는 해당 없음(다크 테마 도입 시 재정의). ③ 열 머리 상태는 `NONE` "평가 전"·`RUNNING` "평가 중"·`FAILED` "평가 실패"·`UNRECOGNIZED` "점수 형식 미확인"; metrics 값은 `eval_status=DONE`이고 `eval_score.status=PARSED`일 때만 표에 쓴다. ④ 색 번호는 선택 순서(곡선 없는 모델도 번호 차지 — 표 열과 색 일치). ⑤ 열 머리 Final 배지는 `study.final_model_id` 기준, "해제"는 기존 모델 표에만 둔다. ⑥ 메타는 점수 표 아래 별도 표("모델 메타"), 데이터셋 조회 실패면 "{앞 8자} (조회 실패)". ⑦ 목 시드: `ds-0a7c41e2`(READY)·`m-4`(TNS v3, RMSE 추가, 다른 데이터셋)·`m-5`(MLP, MaxErr)를 기존 시드 뒤에 추가. ⑧ 스크린샷 `npm run screenshots:phase3` → `screenshots/phase3/stage3_compare_*.png`. (Plan 승인 — 다크 테마 도입 시 `--series-*` 대비 재정의)
- **D3-7 (S3, §5.12 파일 위치)**: ① 저장소 조회 함수는 `repositories/jobs.py`(이미 300줄 초과) 대신 신규 `repositories/study_manage.py`(`latest_succeeded`·`latest_finished`·`active_of_type`·`has_active_of_type`·`has_active_except`·`finished_after`·`study_refs`). `datasets.clear_package`는 계약대로. ② `fmt_bytes`(알림 본문)는 `study_storage/categories.py`. ③ 프런트 시험은 `manage.test.tsx`가 300줄을 넘지 않도록 `__tests__/manageStorage.test.tsx`(`describe("V3-S3-10 …")`)로 분리, 화면은 `pages/manage/{StorageSection,StorageBars,CleanupPreview}.tsx`·`storage.ts`, 목은 `mock/manageStorage.ts`(`manage.ts`가 위임, `server.finish`가 `manage.storage.onFinish` 호출). ④ `test_layering`에 규칙 5 시험 추가(core `stageN_*`·`study_storage`, 워커 `steps/stageN_*`·`stage0_manage` 사이 단계 간 import 금지). (Plan 승인)
- **D3-8 (S3, §5.6 응답 모양 추가)**: `StorageCategory.impact`(영향 안내 한 줄 — UI 체크박스·확인 대화상자용, `categories.CATEGORY_IMPACTS`), `CleanupSummary.skipped: [CleanupSkip{rel, reason}]`(§5.8 "건너뜀 사유 펼치기"). 409 `STORAGE_SCAN_STALE`이 §5.4 규칙에 걸리면 `detail.stale_reason`을 함께 준다. 범주의 `item_count`·`total_bytes`는 **목록에 담긴 항목(≤ `max_items_per_category`) 기준** = 실제로 옮길 양. (Plan 승인 — `CleanupSkip`은 `rel`·`reason`만, D3-22 결정 참조)
- **D3-9 (S3, §5.2·R3-4 검사 순서)**: `create_job`·`retry_job` 공용 `job_params.study_manage.study_gate`: 보관 Study(관리 두 유형 예외) → 비종료 `STUDY_CLEANUP`이 있으면 SCAN 외 전부(정리 자신 포함) 409 `STUDY_CLEANUP_RUNNING`. CLEANUP 사전조건 순서: 최신 성공 스캔 여부(`STORAGE_SCAN_STALE`) → 부분 스캔(`STORAGE_SCAN_PARTIAL`, 문구 끝 "(부분 스캔)") → 비종료 작업(`STUDY_HAS_ACTIVE_JOB`) → §5.4 낡음(`STORAGE_SCAN_STALE`) → 항목 합계(422 `INPUT_INVALID` `loc:["params","categories"]`). 관리 유형 재시도는 상태 검사 뒤 409 `JOB_NOT_RETRYABLE` "이 작업은 재시도 대신 새로 실행하세요". (Plan 승인 — 단 "SCAN 외 전부"는 D3-24로 대체: 정리 실행 중에는 SCAN도 409)
- **D3-10 (S3, §5.4 구체화)**: 규칙 1 = `finished_at > 스캔 started_at`인 SCAN 외 유형 종료 작업 수, 규칙 4 기준 시각 = 스캔 `finished_at`. 보고서와 사전조건이 `services/study_storage.is_stale`(→ core `stale.stale_reason`)을 같이 쓴다. (Plan 승인)
- **D3-11 (S3, §5.5 분류 구체화)**: 후보는 DB 행이 가리키는 경로만(고아 폴더 제외). `SCORE_PREDICTIONS` 폴더 = EVALUATE 재시도 묶음 root, Final 제외 = `root(models.eval_job_id)`. `PREVIEW_OUTPUT` 보존 = 유형별 `finished_at` 최신 SUCCEEDED의 root. `PREDICT_INPUT`은 그 예측 root의 PREDICT·PREDICT_VERIFY가 모두 종료일 때만. `JOB_LOGS` "유형별 최신"은 `created_at` 기준, 실패 보존은 FAILED·INTERRUPTED를 `finished_at` 최신순. 링크가 든 항목은 빼고 경고 `LINK_SKIPPED`, 읽기 오류가 있으면 경고 `STORAGE_SCAN_ERRORS`. (Plan 승인)
- **D3-12 (S3, §5.3·§5.7 실행 구체화)**: step 사이 중간 결과는 그 작업 로그 폴더의 `storage_items.json`(SS_WALK→SS_CLASSIFY)·`cleanup_plan.json`(SC_VALIDATE→SC_MOVE), 경로·크기만. `PACKAGE_PSDATA`의 `package_rel=NULL`은 항목을 옮긴 **직후** 기록(취소돼도 DB·파일 일치). 취소 시 이미 옮긴 항목으로 `CLEANUP_MANIFEST.json`·`result`를 남기고 CANCELED. 이동 실패 시 `backup_existing`이 만든 빈 `_backup` 하위 폴더가 남을 수 있다(삭제 호출 금지). `jobs.result`에 `planned_count` 추가. (Plan 승인)
- **D3-13 (S3, 알림·감사·오류 묶음)**: `notify_job`은 `notify_success=False` 유형의 `JOB_STARTED`·`JOB_SUCCEEDED`·`MY_TURN_NEXT`에서 `None`을 돌려준다. 정리 성공 본문 "{n}개 항목, {크기} 이동"(1024 단위). 감사 `STUDY_CLEANUP`은 워커가 쓰므로 `user_id`=작업 등록자, `username`=NULL. 오류 묶음에 `manifest.json`(`job_id`, `logs_present`, `logs_note`)을 항상 넣는다. R3-5·R3-6 문구의 `_backup`은 사용자 문구라 백틱 없이 쓴다. (Plan 승인)
- **D3-14 (S3, §5.8 UI 구체화)**: 실행 중 재조회 주기는 `STORAGE_POLL.ms`(3000, 시험에서 단축). 권한 없으면 "다시 계산" 대신 "계산·정리: 실행 권한(power 이상)이 필요합니다"(S1 "조회 전용" 문구와 구분). 큰 파일 표는 상위 `top_files`개 전부, "백업" 표지는 `storage-tag`. stage 0 작업 알림을 누르면 관리 화면으로 이동, 대기열 배지 title "Study 관리". 목 레인은 두 유형 LIGHT. (Plan 승인)
- **D3-15 (S4, §6.3 공개 API 구체화)**: ① `CommandConfig`의 `submit`·`status`·`cancel`은 목록·튜플이면 `tuple`로 바꾸고 그 밖의 값(문자열·None)은 그대로 둔다 — 검증이 현행과 같은 "…는 문자열 배열이어야 합니다"를 내도록(검증은 `list|tuple` 허용). `allowed_executables`는 `tuple`, `state_map`은 읽기 전용 매핑. ② `validate_command_config`·`render_argv`·`CommandHpcGateway`는 `CommandConfig` 또는 같은 속성을 가진 객체(→ `from_obj`)를 받는다. `render_argv`는 설정 문제가 있으면 `NOT_CONFIGURED` "PBS 명령 설정 오류"(게이트웨이 `render`와 같음). ③ `make_gateway("command")`에 `command`·`defaults`가 없으면 `ValueError`. ④ `fwd`·`is_abs_path_str`는 현행과 내용이 같아 같은 객체로 재노출(차이 없음). ⑤ 값 검사 정규식·`PLACEHOLDERS` 상수는 `simdash_adapters.hpc.command` 모듈 속성(비공개, `__all__` 밖)이며 `physicsai_core.hpc.command`가 같은 이름으로 재노출. 문구 골든은 이전 코드(c15346f)와 대조해 동일 확인. (Plan 승인)
- **D3-16 (S4, §6.4 호환층)**: `get_hpc_gateway`는 모든 모드를 `make_gateway`로 만든다 — command 모드는 패키지 `CommandHpcGateway` 인스턴스(로거 `physicsai_core.hpc.command`, `child_env` 허용목록 `env_factory`)이고, 플랫폼 `CommandHpcGateway(hpc, env_factory=None)`는 기존 호출처(시험)용 얇은 하위 클래스(`.hpc` 속성 유지). 이 클래스로 `isinstance` 판정하는 코드는 없다. `PHYSICSAI_HPC_GATEWAY` 우선순위는 현행대로 설정 로더(`config/loader.py`)에 있다. `solve._remote_result_dir`는 `resolve_collect_dirs`에 `local_result_dir=_R(…)`를 넘기므로 shared_folder·drive 모드에서도 `_R`(고정 상대경로 `resolve_in_study`, 부수효과 없음)을 계산한다 — 반환값 동일. (Plan 승인)
- **D3-17 (S4, §6.5 배포·개발 경로)**: ① `simdash-adapters`는 PyPI에 없으므로 `collect-offline.{sh,ps1}`는 어댑터 wheel을 **먼저** `dist/wheels`에 만들고 lock 내려받기에 `--find-links dist/wheels`를 붙인다(로컬 파일 후보가 인덱스보다 앞섬). CI(linux·windows)와 `scripts/dev-setup.{sh,ps1}`(신규)는 `./packages/simdash_adapters`를 lock보다 먼저 설치한다(이미 설치된 것은 lock 설치가 인덱스를 보지 않음 — 확인). ② 설치 없이 저장소에서 도는 경로에 `packages/simdash_adapters/src`를 `PYTHONPATH`로 추가: `scripts/_env.{sh,ps1}`, `deploy/demo/demo_setup.py`(`_child_env`), `deploy/demo/{start,stop}-demo.ps1`, `worker/tests/e2e/test_demo_e2e.py`. `start-demo.ps1` 저장소 모드 안내 문구는 `scripts\dev-setup.ps1`로. ③ V3-S4-6은 `scripts/check-adapters-wheel.sh`(소스 사본에서 wheel 생성 → 빈 venv에 `--no-index` 설치 → 저장소 밖에서 import·버전 확인), CI linux 단계로 실행. windows 잡은 묶음에 wheel 파일이 있는지 확인. ④ `.gitignore`에 `packages/*/build/`. ⑤ AGENTS.md 역할 표(`packages/**` → Impl-Backend)는 A3-8대로 Plan 갱신 대기. (Plan 승인 — ①의 lock·`--find-links` 방식은 D3-27로 대체. ⑤ AGENTS.md 역할 표 갱신 완료: `packages/**`·`.github/**` → Impl-Backend, 메인 승인)
- **D3-18 (S4, §6.6 시험)**: ① 패키지 시험의 가짜 PBS는 `tests/fake_pbs.py` 하나(`sys.executable fake_pbs.py qsub|qstat|qdel`) — argv[0]이 `python` 절대경로라 Windows `.exe` 런처 없이 양쪽에서 돈다. 공용 값은 `conftest.py` 픽스처로만(importlib 모드). ② `test_hpc.py`·`test_stage1_train.py` 무수정(`test_adapter_imports_nothing`은 core `hpc/adapter.py` 재노출 파일을 그대로 검사하고, 패키지 쪽은 `test_static.test_no_dynamic_import_or_exec`가 같은 규칙을 모든 소스에 적용 — 범위 축소 없음). ③ `test_static_security`·`test_phase2_units`의 `CODE_DIRS`에 `packages/simdash_adapters/src` 추가(옮긴 코드도 shell·삭제·pickle·exec 검사). ④ `test_layering` 규칙 7: 패키지가 `physicsai_*`·표준 라이브러리 밖을 import하지 않음, `physicsai_api`가 `simdash_adapters.hpc.command`와 `physicsai_core.hpc.command`를 import하지 않음. ⑤ 신규 `backend/tests/common/test_adapters_compat.py`: 재노출 객체 동일성·로거 이름·`env_factory`·루트 `pyproject` 정확 고정·pytest 경로·lock·collect-offline 순서(dry-run)·dev 경로·CI(V3-S4-7 정적 부분). (Plan 승인)
- **D3-19 (겸사, 300줄 규칙)**: `services/jobs.py`(350줄)에서 산출물·HPC 행·input.zip(`list_artifacts`·`artifact_file`·`list_hpc_jobs`·`ZIP_CHUNK`·`_ZipSink`·`input_zip`)을 `services/job_files.py`로 옮기고 `_require_job`→`common.require_job`, `MOVED_HINT`→`common.MOVED_HINT`. 라우터(`artifacts.py`, `jobs.py`의 `hpc_jobs`)와 `services/error_bundle.py`의 import만 바뀜 — 라우터 함수 이름 그대로라 `openapi.json` 바이트 동일·operationId 동일. (Plan 승인)
- **D3-20 (Verifier 결함 1, 이름 변경)**: `patch_study`의 `study.json` 제목 갱신은 Study 폴더가 있고 링크가 아닐 때만 한다. 없으면 폴더를 만들지 않고 운영 로그 WARNING("Study 폴더 없음")만 남기며 API는 200. `write_json_atomic`도 폴더를 만들지 않는다(D3-21). 보관 해제의 `STUDY_FOLDER_MISSING` 409는 그대로(시험 `test_patch_title_without_folder_does_not_create_it`). (Plan 승인)
- **D3-21 (Verifier 결함 2, 원자적 쓰기)**: `fileutil.write_json_atomic` = 같은 폴더 `tempfile.mkstemp`(무작위 이름, `O_CREAT|O_EXCL`) → 기존 파일 권한 유지(새 파일 0644) → `os.replace`. 대상·폴더가 링크(symlink·junction)면 `StepFailure(PATH_UNSAFE)`, 폴더 생성 없음, 삭제 호출 없음(쓰기 실패 시 `.<이름>.*.tmp`가 남을 수 있음 — D3-4의 고정 이름 `.study.json.tmp`는 더 쓰지 않는다). `paths.assert_writable(path, *, allow_final_link=False)`가 마지막 요소 링크를 거부하고(보호 루트 등록 여부와 무관), 링크 자체를 옮기는 `backup_existing`만 `allow_final_link=True`. (Plan 승인)
- **D3-22 (Verifier 결함 3, SC_VALIDATE)**: 항목마다 ① 경로 문자열이 Study 안인지(정규화 비교) ② `lexists` ③ 링크(항목·상위·하위) ④ 마지막으로 `resolve_in_study` 순서로 검사하고, ①·③·④ 실패는 작업 실패가 아니라 그 항목만 건너뜀(코드 `LINK_OR_OUTSIDE`, 문구 "링크가 들어 있어 옮기지 않았습니다"/"Study 폴더 밖 경로라 옮기지 않았습니다"). 건너뜀 항목에 `code`(`CHANGED`·`MISSING`·`LINK_OR_OUTSIDE`·`PATH_OUTSIDE`·`LOCKED`)를 `jobs.result.skipped[]`와 매니페스트에 함께 기록 — API `CleanupSkip`은 `rel`·`reason` 그대로(openapi 불변, `code`는 응답에서 무시됨). 응답에 코드를 노출할지는 Plan 결정 요청. (Plan 결정: 응답에 사유 코드를 **노출하지 않음(문구만)** — `CleanupSkip{rel, reason}` 유지, openapi 불변. `code`는 `jobs.result.skipped[]`·`CLEANUP_MANIFEST.json`에만 남겨 오류 묶음·운영 진단용으로 쓴다. 나머지 Plan 승인)
- **D3-23 (Verifier 결함 4, SC_MOVE)**: 이동 직전 경로 탈출·링크 재확인(`LINK_OR_OUTSIDE`), `backup_existing`의 `OUTPUT_LOCKED`·`OSError` = `LOCKED` "파일이 사용 중", 그 밖의 `StepFailure`(Study 밖 `INTERNAL_ERROR`, 보호 경로 `PATH_UNSAFE`) = `PATH_OUTSIDE` "Study 폴더 밖 경로라 옮기지 않았습니다". (Plan 승인)
- **D3-24 (Verifier 결함 5, R3-4 조정)**: 비종료(QUEUED·RUNNING) `STUDY_CLEANUP`이 있으면 **스캔(`STUDY_STORAGE_SCAN`) 생성도** 409 `STUDY_CLEANUP_RUNNING`(R3-4의 스캔 예외 폐지), `PUT /studies/{id}/final-model`도 같은 409(`job_params.study_manage.require_no_cleanup`, 권한 검사 뒤). 프런트 목(`mock/manageStorage.ts`)·화면 안내는 Frontend 반영 필요(이번 범위 밖). (Plan 승인 — 본문 R3-4·V3-S3-5 갱신. **Frontend 지시**: `mock/manageStorage.ts`가 정리 활성 중 SCAN 생성·`PUT /studies/{id}/final-model`에 409 `STUDY_CLEANUP_RUNNING`을 내도록 맞추고, 정리 실행 중 "다시 계산"·Final 지정 버튼을 비활성화하고 "정리 중에는 할 수 없습니다" 안내, 409 수신 시 서버 문구 표시. 시험 함께)
- **D3-25 (Verifier 결함 6, 경합)**: `create_job`·`retry_job`은 Study 행을 `SELECT … FOR UPDATE`(`studies_repo.require(…, for_update=True)`)로 잠근 뒤 `study_gate`·사전조건·삽입을 한 트랜잭션에서 한다 — 같은 Study의 동시 생성(정리 vs 다른 작업)이 직렬화된다. (Plan 승인)
- **D3-26 (Verifier 결함 7, 호환)**: `physicsai_core.hpc.none`·`adapter`가 예전처럼 `HpcAvailability`·`HpcGatewayError`·`HpcStatus`·`HpcSubmitResult`·`HpcSubmitSpec`(+ adapter `_MSG`)를, `hpc.command`가 같은 값 형식과 `fwd`·`is_abs_path_str`·`_check_value`·`_norm_exe`를 재노출. (Plan 승인)
- **D3-27 (Verifier 결함 8, PyPI 이름 선점 차단 — §6.5 조정)**: `deploy/requirements.lock`에서 `simdash-adapters` 줄을 빼고(PyPI에서 받는 외부 의존성만) 새 `deploy/requirements.local.lock`(`simdash-adapters==0.1.0`)에 고정. `collect-offline.{sh,ps1}`: 어댑터 wheel 생성 → `pip download --no-index --find-links dist/wheels -r deploy/requirements.local.lock …`(로컬 wheel만으로 고정 확인) → `pip download -r deploy/requirements.lock …`(D3-17의 `--find-links` 제거). 설치는 그대로 `--no-index`. CI·`dev-setup`은 패키지를 저장소 소스로 먼저 설치. 남은 위험: 패키지를 먼저 설치하지 않고 루트에서 `pip install .`을 하면 의존성 `simdash-adapters`를 인덱스에서 찾는다 — `scripts/dev-setup`을 쓰도록 안내. **admin.md §2.2·architecture.md §1.6의 lock 설명은 Plan 갱신 필요**(이번 지시가 docs 수정 금지). (Plan 승인 — 본문 §6.5·V3-S4-7, admin.md §2.2·§2.9, architecture.md §1.6 갱신 완료)
- **2026-10-13 환경 버전 변경**(decisions.md 2026-10-13, 사용자 결정): 실행 환경은 대시보드와 동일하게 Python 3.12.13·PostgreSQL 18(같은 인스턴스 별도 DB)·Node 22.23.2. 본문에 옛 버전 언급은 없음 — 어댑터 wheel·외부 의존성 wheel(§6.5)은 win_amd64·cp312 기준, 버전 확인·`dashboard_root` 기본값 규칙은 admin.md §2.1·§2.3·§14
- **D3-28 (S5, 운영 정적 서빙)**: 새 설정 `server.frontend_root`(기본 `null` = 서빙 안 함, 상대경로는 설정 오류) — 대시보드 Vite가 `/physicsai` 전체를 rewrite 없이 백엔드로 넘기는 운영 구성에서 백엔드가 `/physicsai/`를 직접 서빙(`physicsai_api/frontend_static.py`, 시연 `demo.frontend_root`도 같은 규칙·우선). 규칙: `/physicsai` → 308, `/physicsai/api*`는 라우트 매치 제외(기존 JSON 404·405 유지), 탈출(`..`·절대경로·드라이브, 인코딩 포함)·빌드 폴더 밖 링크 404(시연도 — 이전 시연은 index.html로 돌려줬음), 없는 경로 `index.html`(no-cache), `assets/` immutable, 인증 없음. 폴더·`index.html`이 없어도 기동하고 환경 점검 API 항목 `server.frontend_root`(CONFIG, OK/WARN/SKIP)로 알림 — openapi 불변.
  `setup_config.py`가 `server.frontend_root = <caddy_frontend_root>`(기본 `<git>/.runtime/frontend`)를 키가 없을 때만 보충, `setup.ps1`·`update-repo.ps1` 끝 안내는 공용 `Write-PhysicsAIConnectGuide`(대시보드 `.env` `VITE_PHYSICSAI_TARGET`·`SIMDASH_PHYSICSAI_ENABLED`, Caddy는 대안). admin.md §2.6 갱신. **Plan 확인 요청**: architecture.md 파일 표에 `frontend_static.py` 추가.
- **D3-29 (Plan, 2026-10-15, S6 신설)**: 원본 ④ 흐름 재추적으로 platform.md §8.9의 U2·U3·U4·U7을 해소(§11.2), 시연을 막는 P1 3건(eps_mesh starter 중복, HyperMesh m_2 누락, 폴더 등록 eps_mesh·csv) 수정 규칙과 준비된 입력 예측(`input_mode`)을 §11에 정함. platform.md §19 U2·U3·U4·U7 → phase3 §11.2.
- **D3-30 (S6, 메인 결정 — §11.5 경로 확인 응답·기능 조건)**: `paths/inspect` `purpose:"PREDICT_INPUT"` 응답은 기존 `PathInspectResponse` 모양 그대로 — `kind`·`starter`·`starter_ok`·`rad`·`inc_count`·`file_count`·`total_bytes`는 `summary` 안, `problems`는 최상위(기존 규칙). 경로 자체 위반(루트 밖·공백·메타문자·링크·`_backup`·없음)은 다른 용도와 같이 422 `PATH_*`. `features.predict` = `edspy_predict`·`contour_preview`만, `geom_update`(+ `mesh`가 `{include_tcl}`을 쓰면 `resources.hypermesh_include_tcl`)는 `features.predict_parametric` 조건. (메인 결정)
- **D3-31 (S6, §11.5 구현 구체화)**: ① parametric 저장 params에 `input_mode:"parametric"`을 더한다(기존 키 그대로, 옛 작업은 키 없음 = parametric). prepared 초기 `result`에 `input_mode`. ② `.rad` 파일 지정 시 starter = 지정 파일(같은 폴더에 다른 `*_0000.rad`가 있어도), 복사는 그 폴더 직계 `*.rad`·`*.inc`(eps_mesh 제외). `eps_mesh*` 파일을 지정하면 `STARTER_COUNT`. 링크 파일은 `FILE_NAME_UNSAFE`("링크 파일은 쓸 수 없습니다"). ③ PR_PREP·RAD_ASSEMBLE이 같은 규칙으로 다시 검사해 문제·`kind`·`starter`가 등록 때와 다르면 `INPUT_CHANGED`. ④ parametric 409: `geom_update` null은 기존 문구(`template:"geom_update"`), 그 밖의 `predict_parametric` 누락은 "형상 갱신 설정 필요(관리자): …" + `missing`. 설정 경고: `geom_update` null 또는 include TCL 자원 누락 시 `config.warnings` 1건. ⑤ `predict.mesh_output_glob`은 기존 설정 호환을 위해 스키마에 남기고(None) 값이 있으면 경고 "폐지된 키". ⑥ `PV_EXTRACT`는 원 예측에 파라미터 세트가 없으면 SKIPPED.
- **D3-32 (S6, §11.4 구현 구체화)**: ① GEOM_UPDATE·MESH는 실행 전에 판정 대상 출력(`{simlab_mesh_name}`, `{mesh_include_name}`, `log_batch.txt`)을 `_backup`으로 옮긴다(재시도가 이전 산출로 성공 판정되지 않게). `run_local(allow_nonzero_exit=True)`에서도 메모리 한도 종료는 `RESOURCE_LIMIT`. ② MESH 템플릿이 `{include_tcl}`을 쓰는데 자원 파일이 없으면 `RESOURCE_MISSING`. `log_batch.txt`는 마지막 5000줄을 step 로그에 덧붙인다. ③ RAD_ASSEMBLE starter 셈은 이번에 복사한 파일 기준(INPUT에 남은 이전 시도 파일 무시). ④ ① TD_DOE_GEN의 조립 사본(`01_train/radioss_assem/<doe>`)에도 `{renum_csv_name}`을 복사한다 — from-train csv의 출처. 이 변경 전 DOE는 csv가 없어 ④ 실행 때 `RENUM_CSV_MISSING` 경고.
- **D3-33 (S6, V3-S6-14·설치)**: ① 가짜 도구: fake_simlab 모드 `with_include`(include 직접 작성, 이름 `FAKE_SIMLAB_INCLUDE`), fake_hw HyperMesh 형태 모드는 `FAKE_TOOL_MODE_HM`(> `FAKE_TOOL_MODE_HW`)로 컨투어 미리보기와 분리, `nonzero_with_output` 추가. 시험 기본 설정·시연 설정(`platform.demo.yaml`)의 `commands.mesh` = 새 기본(e2e·시연이 MESH를 실제로 거침), 시연 seed는 실제 이름(`104_replace_node_elem.inc`·`RENUM_INIT.csv`·`EPS_mesh_0000.rad`)과 준비된 입력 예시 `import/prepared_case`. ② `deploy/setup_config.py`: S6 이전 설정(`predict.mesh_include_name` 없음)에서만 한 번 — `commands.mesh: null`(또는 `commands` 절에 키 없음) → 예시 값, `predict.mesh_output_glob: "eps_mesh*"` → 줄 삭제, `predict.mesh_include_name`(예시 값)을 넣어 갱신 표시. 이후 재실행은 사용자가 고친 값(`mesh: null` 포함)을 건드리지 않는다. 다른 값으로 바꾼 키는 처음부터 보존.
- **D3-34 (메인 결정, 경로 대소문자)**: `check_user_path`의 `_backup`(어느 깊이든)·`_platform`(루트 직계) 판정과 `check_dataset_input`의 산출 폴더 판정을 `casefold` 비교로(Windows `_BACKUP`·`_Platform`·`03_Model` 우회 차단). 모든 호출부(경로 확인·작업 생성·워커 재검사)에 그대로 적용.
- **D3-35 (메인 결정, 파일 이름 문자)**: `paths.name_unsafe_chars`: 기준 폴더 아래 이름(파일·하위 폴더)은 제어·서식 문자, 공백류(전각·NBSP 포함), `& | < > ^ % ! "`에 더해 `; , = ( ) '`도 거부(영숫자·`_`·`-`·`.`·한글 허용). `file_safety_problem`(준비된 입력·③-1 h3d)과 파라미터 세트 CAD·`radioss_assem` 파일에 적용, 문구 "파일 이름에 쓸 수 없는 문자(…)가 있습니다". 기준 폴더 자체는 기존 경로 규칙(`check_user_path`)만.
- **D3-36 (메인 결정, RAD_ASSEMBLE 재시도)**: RAD_ASSEMBLE(parametric·prepared) 시작 시 비어 있지 않은 `P/INPUT`을 통째로 `_backup/<stamp>_<job>/04_predict/<ws>/INPUT`으로 옮기고 새로 채운다(원본 opti:290-292는 비움 — 플랫폼은 삭제 대신 이동). 재시도 때 이전 시도 파일·S6 이전 작업 `EPS_mesh*` 잔존 방지.
- **D3-37 (메인 결정, EDSPY_PREDICT 판정)**: 원본 ⑤ 기준 Predict(opti:323-329)처럼 `RESULT/<stem>_pred.h3d` 존재·크기>0이면 성공 — rc≠0은 경고 `EXIT_NONZERO_IGNORED`, `commands_log_error_patterns` 일치는 경고 `LOG_ERROR_PATTERN`(실패 아님). h3d 없음 → rc≠0이면 `EXIT_NONZERO`, 아니면 `OUTPUT_MISSING`. 다른 edspy step의 `LOG_ERROR_DETECTED`는 그대로.
- **D3-38 (메인 결정, 대시보드 링크)**: `auth.dashboard_public_login_url`을 운영 대시보드 웹 경로로 — `deploy/setup_config.py`가 대시보드 `.env`의 `WINDOWS_WEB_BASE_PATH`(없으면 `/home/`, 앞뒤 `/` 보정)를 넣는다(키가 없거나 이전 기본값 `/`일 때만, 사용자 값 보존). `dashboard-env.ps1`이 `WebBasePath`를 읽어 setup·update-repo가 입력으로 넘긴다. 프런트 상단 "대시보드로"도 같은 값(`/status.auth.login_url`, 로그인 안내와 공유). 포트는 같은 origin이라 무관.
- **D3-39 (메인 결정, 원클릭 업데이트·EPERM)**: `update-repo.ps1`은 인자·질문 없이 한 번(값은 `.runtime\deploy.json`) — 대기열은 항상 DB 직접(대시보드 세션 토큰 질문 삭제, `update.ps1`·`setup.ps1` 공용), 작업이 있으면 안내 후 중단(`-Force` 유지). 프런트 `npm ci`·`npm run build`는 파이프·리다이렉트 없이 콘솔 그대로(`Invoke-PhysicsAINpm` — PowerShell 파이프면 esbuild `spawn EPERM`), 실패 시 10초 뒤 1회 재실행. migration 전 실패면 이전 프런트 복구·작업 2개 재시작. 끝은 성공/실패 + 접속 주소 한 줄(대시보드 `.env` `WINDOWS_WEB_PORT`, 기본 80).
- **D3-40 (사용자 결정 2026-10-15, 빌드본 포함·원클릭)**: "호환성 높게, 원클릭, 경로 지정 없음" — 사내 서버의 보안 정책(`.bat` 차단, esbuild `spawn EPERM`). 저장소 루트 `frontend-dist/`에 `vite build` 결과와 `BUILD_INFO.json`(`source_hash`·`built_at` UTC·`vite_version`·`node_version`)을 커밋한다. `source_hash` = `frontend/`의 `index.html`·`package.json`·`package-lock.json`·`vite.config.*`·`tsconfig*.json` + `src/**`·`public/**`를 `/` 상대경로 서수 정렬, 내용 CRLF→LF 후 파일별 sha256, `"경로\0hex\n"`을 이은 UTF-8의 sha256(구현: `scripts/frontend_source_hash.py` = `deploy/node-select.ps1` `Get-PhysicsAIFrontendSourceHash`, 동일성 시험). 생성은 `scripts/build-frontend-dist`(Linux, `npm ci` → `npm run build` → 교체). `scripts/test-all`·CI는 해시가 다르면 실패("frontend-dist가 최신이 아닙니다: scripts/build-frontend-dist 실행 후 커밋"). `setup.ps1`·`update-repo.ps1`·`collect-offline.{ps1,sh}`는 해시가 같으면 그대로 배치(Node 선택·npm 단계 없음 — 기존 `_backup` 이동 규칙 유지), 다르거나 없을 때만 기존 빌드 경로(Node도 없으면 빌드본 갱신 요청·Node 설치 안내). 묶음 `install.ps1`·`update.ps1`은 묶음의 빌드본(`frontend\`)을 그대로 배치. `update-repo.ps1`은 스스로 `git pull --ff-only`(추적 파일 로컬 변경이면 안내 후 중단, 분리된 HEAD·추적 브랜치 없음이면 pull 없이 현재 커밋, 새 커밋이면 새 스크립트로 `-SkipPull` 재실행) — 사용자는 인자 없이 `powershell -NoProfile -ExecutionPolicy Bypass -File <git>\deploy\update-repo.ps1` 한 줄. 끝 줄은 "업데이트 성공/실패 — 접속: …".
- **D3-41 (사용자 결정 2026-10-15, 관리자 권한 제거)**: 대시보드처럼 일반 PowerShell. 머신 환경변수를 쓰지 않는다 — DB URL은 `<런타임>\secrets\database_url`(BOM·줄바꿈 없음, `icacls` 상속 해제 + 현재 사용자·SYSTEM 모든 권한, 실행 계정이 다르면 읽기 — 실패는 경고), 설정은 `<런타임>\config\platform.yaml`(묶음은 `--config <config_path>`). 작업 스케줄러는 현재 사용자 `-LogonType Interactive -RunLevel Limited`, 인자 `-m physicsai_api.serve|physicsai_worker --runtime "<런타임>" [--config "<설정>"]`(비밀값 없음). 로더 `physicsai_core.config.runtime.apply_runtime` 우선순위: 프로세스에 직접 준 환경변수(머신 환경변수에서 물려받은 값과 다를 때) > `--config` > 런타임 파일 > 이전 머신 환경변수(런타임 파일이 없을 때만). 이전 설치 이전: setup·update-repo·update가 머신 환경변수 DB URL을 런타임 파일로 옮김(머신 환경변수는 지우지 않음 — 안내 한 줄), 작업 인자가 `--runtime` 방식이 아니면 `Interactive`는 다시 등록(`Background`는 비밀번호 필요 — 안내만). 관리자 확인(`IsInRole`) 삭제. 기존 작업이 관리자 소유라 중지·등록이 거부되면 "처음 한 번만 관리자 PowerShell로 update-repo.ps1을 실행하세요" 후 중단(중지 거부는 바꾼 것 없음), 등록 때 실행 계정에 작업 모든 권한(FA)을 더해 이후 일반 PowerShell로 관리. `-RunMode Background`만 관리자 권한이 필요할 수 있음(그 옵션에서만 안내). DB 생성(PostgreSQL 관리자 비밀번호)은 그대로.
- **D3-42 (Verifier 지적, 업데이트 실패 시 작업 정의)**: `update-repo.ps1`·`update.ps1`은 작업 인자 갱신(`--runtime` 다시 등록, `Update-PhysicsAITaskRegistration`)을 venv 갱신·프런트 배치가 끝난 뒤(migration 직전)로 옮긴다 — 그 전 단계(pip·프런트)가 실패하면 작업 정의는 이전 그대로라 이전 코드(`--runtime`을 모르는 argparse)가 이전 인자로 다시 시작된다(`update.ps1`은 실패 안내에 작업 등록을 바꿨는지 표시). `update-repo.ps1`의 git은 자격 증명을 묻지 않는다(`GIT_TERMINAL_PROMPT=0`·`GCM_INTERACTIVE=never`·`-c credential.interactive=never` — 인증 실패는 기다리지 않고 "바꾼 것 없음"으로 중단), `safe.directory`는 `*` 대신 이 저장소 경로만. 관리자 실행 안내는 "지금과 같은 사용자 계정으로 PowerShell을 '관리자 권한으로 실행'"(비밀 폴더 ACL·작업 등록이 현재 사용자 기준).
- **D3-43 (사용자 결정 2026-10-16, pscfg 선택)**: 모델 등록 시 `.pscfg`는 0개 또는 1개(근거 U7: 원본 단독 예측 `5_predict.py:55-66`·평가 `4_testing.py:62`·최적화 예측 명령에 pscfg 인자 없음 — HPC에서 학습한 `.psmdl`만으로 예측). platform.md §8.6 MR_VALIDATE·§17 inspect: `*.pscfg` 2개 이상만 `INPUT_INVALID`/`PSCFG_COUNT`(모호), 1개면 기존대로 복사·sha256. migration `0005_pscfg_optional`: `models.pscfg_rel`·`pscfg_sha256` NULL 허용(기존 행 보존, `MIGRATION_HEAD` 갱신). 무결성 재계산은 pscfg가 있을 때만. `{model_pscfg}`를 쓰는 `edspy_score`·`edspy_predict` + pscfg 없는 모델 → EVALUATE·PREDICT 생성 409 `PSCFG_REQUIRED`("이 명령 설정은 .pscfg가 필요합니다 — pscfg가 있는 모델을 등록하거나 설정에서 {model_pscfg}를 빼세요", 워커도 같은 문구 `INPUT_INVALID`) — 기본 템플릿은 pscfg 미사용이라 영향 없음. 패키지 안내문·③ 화면 문구는 "선택(있으면 함께 보관)". 같은 묶음(사용자 혼동 해소): `PREDICT_INPUT` summary에 `subdir_count`(복사 대상 폴더의 직계 하위 폴더 수, `.hm`이면 0) — 화면은 `subdir_count>0`일 때만 회색 "하위 폴더 N개는 복사하지 않습니다(이 폴더의 .rad·.inc만 사용)"(항상 보이던 "직계 파일만 복사" 문구 삭제), starter 정상이면 요약 "✓ starter <이름> · rad N · inc M".
- **D3-44 (사용자 결정 2026-10-16, 준비된 입력 eps_mesh 포함·starter 안내)**: ① prepared 복사 대상 = 지정 폴더(또는 `.rad`의 폴더) 직계 `*.rad`·`*.inc` **전부**(eps_mesh 포함 — 사용자가 준비한 starter가 `eps_mesh*.inc` 등을 include할 수 있어 제외하면 입력이 깨진다). starter 판정: 파일 지정 = 그 파일(D3-31 ②의 "eps_mesh 파일 지정 → `STARTER_COUNT`" 폐지), 폴더 지정 = `starter_glob` 일치 파일이 1개면 그것, 여러 개면 eps_mesh로 시작하지 않는 것이 정확히 1개일 때 그것, 아니면 `STARTER_COUNT`(메시지 "starter(<glob>)가 정확히 1개 있어야 합니다(현재 N개: a, b)"). 공용 `prepared_input.plan_copy` 하나로 작업 생성 검증·inspect·PR_PREP·RAD_ASSEMBLE가 같은 결과. **parametric은 eps_mesh 제외 유지**(조립 폴더의 기존 `EPS_mesh*`는 이전 형상 — 원본 opti:294-305, V3-S6-2·6). ② inspect `PREDICT_INPUT` summary `starter_hints`: 폴더 입력의 직계 starter 후보가 0개일 때만 1단계 하위 폴더(링크·`_backup`·`_platform`·안전하지 않은 이름 제외)에서 같은 판정 규칙의 후보를 상대경로(OS 구분자)로 최대 10개, 그 밖엔 `[]`. 안내 전용(작업 생성·워커는 쓰지 않음 — 그 폴더는 여전히 `STARTER_COUNT`). 화면: 0개 + 힌트 → 회색 "하위 폴더에 starter 후보가 있습니다: <후보…> — 그 폴더나 파일 경로를 입력하세요", 후보 클릭 = 입력란을 `normalized_path` + 구분자 + 후보(그 파일 절대경로)로 채움(다시 "확인" 필요).
- **D3-45 (사용자 요청 2026-10-16, GPU 사용률 표시)**: 워커 GPU 조회는 `worker.gpu_query` 첫 인자가 비었거나(null 포함) 찾을 수 없으면 `resources.gpu_query_candidates`(기본 `["nvidia-smi", "%SystemRoot%\\System32\\nvidia-smi.exe", "%ProgramFiles%\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe"]`)를 순서대로 찾는다 — 이름만이면 PATH, `%VAR%`·`${VAR}`는 환경변수 확장(정의 안 된 변수의 후보는 건너뜀), gpu_query 인자(첫 인자 뒤)가 없으면 기본 `--query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits`. 기존처럼 제한기 밖·타임아웃 5초·`shell=False`. 스냅샷(`worker_heartbeats.resources`, `GET /resources`)에 `gpu_status: "OK"|"NOT_FOUND"|"ERROR"`·`gpu_message`(OK = 실행 파일, NOT_FOUND = 시도 목록, ERROR = 종료코드·시간 초과·출력 형식) 추가(이전 표본은 null). 환경 점검 `gpu.detect`도 같은 탐색(WARN 문구 "GPU를 찾지 못했습니다 — <gpu_message>", detail `gpu_status`·`exe`). `worker.gpu_query` 키가 없을 때의 설정 경고는 "자동 탐색" 안내로 바뀐다. 예시 YAML `gpu_query` 첫 인자는 `nvidia-smi`(경로 하드코딩 없음). 화면 `WorkerResourcePanel`: GPU 목록이 비면 숨기지 않고 회색 한 줄 — NOT_FOUND "GPU 정보 없음 — nvidia-smi를 찾지 못했습니다", ERROR "GPU 정보 없음 — nvidia-smi 실행에 실패했습니다"(title = `gpu_message`), 그 밖 "GPU 정보 없음".
- **D3-46 (사용자 결정 2026-10-16, 서버 경로 탐색·받은 파일 폴더)**: 다른 PC의 파일은 서버 공유 `physicsai-inbox`(쓰기)에 복사한 뒤 화면 "찾아보기"로 고른다(업로드 없음) — §12. `GET /fs/roots`·`/fs/list`, 권한 = 어느 프로젝트든 power 이상 또는 전역 관리자, `storage.inbox_dir`·`inbox_share_hint`, 배포가 inbox 생성·SMB 공유 조회로 힌트 채움(공유 생성은 관리자 1회, admin.md).
- **D3-47 (사용자 요청 2026-10-16, 파라미터 세트 자동 구성·이름)**: §13. 프로젝트 폴더 1개에서 tpl·CAD·조립 폴더·파라미터를 찾아 구성(`param_discover.py`), 등록 사본만 CAD 경로 `./<CAD>`로 재작성, `param_sets.label` + `PATCH /param-sets/{id}`. migration head `0006_param_set_label`.
- **D3-48 (사용자 보고 2026-10-16, DOE 동시 실행 표시)**: ①-3 DoeGenCard의 동시 실행 수를 고급 밖 기본 표시(1~`/status` `limits.configured.max_multi_execution` = `train_data.max_multi_execution`). 워커 `hst_gen_radioss`의 `HstRunTracker`가 완료 = `Finished run` 로그 집합(순서 무관), 시작 = run 폴더 수(2초 간격)로 집계해 진행 라벨 "실행 중 R · 대기 W · 완료 K/N (동시 M)", 진행률은 완료 수 기준(원본 FUNC:93-98). 병렬 실행 경로·Job Object 제한기는 변경 없음.
- **D3-49 (사용자 결정 2026-10-16, S9 템플릿 예측·DOE 일괄 예측·응답 추출)**: §14. 입력 방식 3개(템플릿 값 입력·일괄 예측(DOE)·준비된 입력), 템플릿 = `param_sets`(+`input_kind` mesh_only|assembly, 조립 폴더 선택), B = 부모 `PREDICT_BATCH`(플랫폼 동시 실행기로 m_1~m_3) + run별 하위 `PREDICT`(prepared), 응답 추출 원본 ⑤ m_4 TCL 기본 활성(U8·U35 해소), B 응답 그래프(2D·3D plotly)·커브 겹쳐보기. migration `0007_predict_batch`, 서버 확인 E4-9-1~5.
- **D3-50 (Verifier 지적 반영 2026-10-16, S7·S8 경로·이름 보강)**: 표시 이름(label)은 제어·서식·줄 구분 문자(Cc·Cf·Cs·Zl·Zp — NUL·줄바꿈·탭·U+202E 등)를 422로 거부(`naming.label_problem` — 스키마 `Label`·서비스 `_label` 공통, 폴더·discover·①→④ 등록과 PATCH, 등록은 사본 생성 전 검사). 등록 정규화본은 `logs/_paramset_tmp/<tmp>.out`에서 DB 트랜잭션 안에서 `04_params/<id>`로 이동하고 insert·commit 실패 시 `logs/_paramset_tmp`로 되돌린다(이번 요청이 만든 미등록 사본이라 삭제 없이 되돌림, 04_params 고아 없음). discover 등록 복사는 원본마다 복사 직전 재검사(요소 링크·junction 없음, realpath가 프로젝트 폴더 안 — 조립 폴더는 listdir 전)·열린 핸들 기준 복사(O_NOFOLLOW + 연 파일과 lstat의 파일 ID 일치), 바뀌면 422 `PATH_UNSAFE`/409 `SOURCE_CHANGED`. `check_user_path`(모든 사용자 경로)·입력 트리 이름·`storage.inbox_dir`·배포 inbox 생성은 요소 안 `:`(ADS·드라이브 상대)·끝 마침표/공백을 거부(배포는 `_backup`·`_platform`도 mkdir 전 거부). tpl CAD 경로 재작성은 원본 바이트의 첫 일치 줄만(BOM·CRLF 유지). 조립 폴더 복사 판정을 `assem_files`로 공통화(planned_bytes = 복사량), discover는 Study 산출 폴더(04_params·logs·01_train/tpl 등) 안을 찾지 않음(`STUDY_OUTPUT_SKIPPED`·`STUDY_OUTPUT_DIR`), 보관 Study의 PATCH는 409.
- **D3-51 (S9 P1 API 구체화, Plan 확인 요청)**: ① PREDICT params의 템플릿 종류 키는 `template_kind`(`assembly|mesh_only`, §14.4 B8의 `input_kind` 대신 — prepared의 `input_kind` `file|dir`와 겹치지 않게). PREDICT_BATCH 저장 params = `{batch_id, batch_no, param_set_id, model_id, multi_execution, template_kind, source:{kind, …출처 요약}}`(표 본문 없음, run 값은 `predict_batch_runs`). `multi_execution`은 필수(1~`train_data.max_multi_execution`, 넘으면 422 `INVALID_PARAMS`). `retry-failed`가 만드는 재생성 부모 params = `{batch_id, batch_no}`(§14.7의 `{batch_id}` + 표시용 `batch_no`), 하위 `batch_run`에도 `batch_no` 추가(판정은 `batch_id`·`doe_no`만). ② 하위 PREDICT 알림은 `JOB_CANCELED`·`JOB_INTERRUPTED` 포함 **전부** 억제(V3-S9-10 "하위 0건" — 일괄 취소 때 N건 방지). 일괄 취소는 배치를 먼저 `CANCELED`로 두므로 `PREDICT_BATCH_DONE`은 오지 않는다. 종료 훅 `job_end.batch_on_job_end`(모든 종료 경로가 `_side_effects_on_end`에서 호출): 재시도로 바뀐 이전 하위의 종료는 무시, 부모 실패·중단 → `FAILED`, 취소 → `CANCELED`. ③ 응답 정의 행의 `spec: null` 허용(추출 정의 없음 — 실측 `resp:` 열 이름 유지용), 실측 열 이름은 NAME 규칙이 옛 규칙이어도 그대로 허용. 검증은 새 공용 `stage4_predict/response_defs.py`(`responses.py`는 요청 줄·`RESPONSES.txt` 파싱만). `PUT`은 DB `param_sets.responses`(spec 포함)와 `04_params/<id>/responses.json`을 같은 트랜잭션에서 갱신, Study 폴더가 없으면 409 `PARAM_SET_FILES_MISSING`. 폴더 등록 때의 `responses.json` spec은 DB에 넣지 않는다(기존대로 이름·단위만). ④ 미리보기 조합 문제는 200 `problems`, 생성은 422 `BATCH_SOURCE_INVALID`. 모양 오류(kind·필드·추가 키)는 둘 다 422 `INVALID_PARAMS`. ⑤ `ParamSet`에 `input_kind`·`assem_rel|null`·`warnings[]`(등록 응답만, `SIMLAB_EXPORT_NAME`) — 새 설정 `param_set.tpl_export_regex`(기본 `dir_file_export\s*=\s*r?"[^"]*"`, 정규식 하드코딩 금지 규칙). discover는 조립 폴더 0개를 문제(`ASSEM_NOT_FOUND`) 대신 `notes` `MESH_ONLY`로(starter 여러 개 폴더 안내를 덧붙임), `choice.radioss_assem`에 없는 이름은 후보 0개여도 `CHOICE_INVALID`. ⑥ `PredictBatch` 응답에 `source_kind`·`created_at`·`created_by_name`·`finished_at`·`can_cancel`·`can_retry_failed` 추가. 행 `code`·`message` = 생성 실패면 `gen_code`·`gen_message`, 하위 실패·취소면 작업 `failure_code`·`failure_message`. CSV 파라미터 열은 반영값(`applied_values`), 줄끝 CRLF. 실패만 다시: 대상 없으면 409 `JOB_NOT_RETRYABLE`, 하위 재시도는 배치 권한(power)으로 — 하위 등록자 검사 없음. 일괄 취소 권한 거부 = 403 `PERMISSION_DENIED`(`required:"owner_or_global_admin"`). ⑦ 커브 `max_points`는 2~2000(그 밖 422), 계열 이름 목록 = 완료 run(상한 안) 계열의 첫 등장 순.
- **D3-52 (사용자 결정 2026-10-16, S10 컨투어 캡처)**: §15. 구현에서 정한 것: ① 재캡처는 원래 예측 result를 고치지 않고 `CONTOUR_RECAPTURE` 작업 result에 남기며 `GET /jobs/{id}/media`가 방향별로 덮어써 보여 준다(파일은 `RESULT/media_recapture/<id>/`, 원래 `RESULT/media/` 보존). ② 파일 제공은 기존 `/artifacts/{id}/content`를 바꾸지 않고 새 `/artifacts/{id}/media`(CONTOUR_* 전용, Range). ③ TCL 2절 오류의 `return` 앞에 결과 작성 + `exit`를 넣었다(배치에서 멈춤 방지 — 그 밖 동작 불변). 방향마다 3절 기준 프레임으로 되돌린다(앞 방향 동영상이 프레임을 옮김). ④ `capture.timeout_s`는 캡처 step 안에서만 적용(공통 실행기 시간 한도 없음 유지, V-SM-6 정적 검사 대상 파일 무수정). ⑤ 배치 display는 그 배치의 첫 `PREDICT_BATCH` 작업 params에서 읽는다(실패만 다시의 재생성 부모 params에는 없음 — BP_ENQUEUE 무수정). ⑥ wheel 설치라 패키지 위치에서 저장소 리소스를 못 찾으므로 `deploy/setup_config.py`가 `resources.contour_capture_tcl`을 git 폴더 경로로 채운다(비었거나 없을 때만). ⑦ 같은 Study의 재캡처 동시 대기 허용(0008 index), 같은 예측 중복만 409 `RECAPTURE_ACTIVE`.
- **D3-53 (Verifier 권고 반영 2026-10-16, S9·S10)**: ① 컨투어 표시 설정 문자열(field·component·comps, 열거형 avgmode·views·legend.mode 포함)과 `capture.default_field`에 `|`(hwc 명령 구분자)·제어문자 금지(응답 정의는 이미 `|` 거부), 워커가 settings 작성 전 한 번 더 검증. ② 새 정규식(`batch_matrix.RUN_KEY_RE`·`_BATCH_DIR_RE`·미디어 `_RANGE`·`response_defs.NAME_RE`·`responses._RESP_RE`)은 `fullmatch` + ASCII 숫자 `[0-9]`. ③ 미디어 Range: 끝<시작 등 문법 오류는 무시하고 200 전체, 만족 불가(시작≥크기·`bytes=-0`·빈 파일)만 416. 공유 회계 그룹(Windows Job 1개)의 run별 RESOURCE_LIMIT는 그룹 메모리 표본(0.5초)으로 잡은 도달 구간이 그 run 실행 구간과 겹칠 때만 — 다른 run도 겹치거나 시작 전 도달 가능하면 문구 "작업 묶음이 메모리 한도에 도달한 적 있음(이 run의 원인인지 불확실)", 겹치지 않으면 종료코드 그대로(호출자 EXIT_NONZERO). ④ PREDICT_BATCH params `capture{enabled(기본 true), views?(기본 템플릿 display.views → config capture.views), video?(기본 config capture.video)}` — 저장 params에 그대로(기본과 같으면 키 없음), 하위 CONTOUR_CAPTURE가 따름(enabled false → SKIPPED "일괄 예측 설정에서 컨투어 캡처를 껐습니다", 재캡처 기본 방향·동영상도 배치 옵션). `/status.capture{views, video, video_ext}` 추가(B 설정 화면 기본값). B 설정 "컨투어 캡처"·방향·"영상 포함" 체크 + 예상 참고 1줄(run × 방향, 장당 0.3 MB·영상 5 MB·방향 20초·영상 40초 가정). ⑤ (사용자 요청) `capture.default_field` 기본 "Von Mises" → **"CornerStress"**(PhysicsAI 예측 h3d 응력, `hwc result scalar load type=CornerStress`, 성분 없음 — 스키마·예시·시연 설정). `deploy/setup_config.py`는 기존 설정 값이 이전 기본 "Von Mises"이면 1회 갱신하고 줄 끝 주석 `setup.ps1 D3-53` 표시를 남겨 이후 사용자 값(다시 고른 Von Mises 포함)을 보존. 템플릿 "컨투어 표시"(결과 종류·성분)와 "응답 추가"(datatype·component)는 입력란 + `<datalist>` 후보로 목록에 없어도 직접 입력(후보 없으면 placeholder CornerStress, 안내 "예측 결과 목록이 없으면 직접 입력하세요(예: CornerStress)"). ⑥ (사용자 요청) ④ 일괄 예측 모드에 서브 탭 "실행 목록" | "새 일괄 예측" — 실행 목록 = 이 Study의 배치 전부(진행·완료·실패·취소, 최신순: 번호·템플릿·조합 수·상태 집계·첫 응답 최소~최대·시작 시각), 행 → `…/stage/4/batch/:id`. `PredictBatchSummary`에 `param_set`·`gen`·`predict`·`response_summary{name,unit,min,max,count}` 추가. 기본 탭 = 진행 중 배치가 있으면 실행 목록, 없으면 마지막 선택(`physicsai.stage4.batchTab`, 없으면 새 일괄 예측), 실행하면 결과 화면으로 가고 다음 기본 탭은 실행 목록. 결과 화면 "← 실행 목록", 부모 PREDICT_BATCH 알림 클릭 → 결과 화면.
- **D3-54 (사용자 결정 2026-10-17, S9·S10)**: ① 템플릿 응답 정의 spec.component = 선택 항목 — ⑤ OPTIMIZE.responses의 layer 규칙과 같게(키 없음 = "", 값은 문자열·결과 이름 필드 문자·`|` 금지·200자), 요청 줄은 빈 필드(`NAME|1|CornerStress||`, ⑤ m_4가 빈 LAYER를 쓰는 방식과 동일), 화면 "응답 추가" 성분 비움 허용(placeholder "없음"). ⑤ 자체(validate_responses·ResponseTable)는 component 필수 그대로(바꾸지 않음). ② `capture.default_component`(기본 "vonMises", 사용자 확인: CornerStress 성분) — 최종 표시 설정 component가 비었고 field가 `capture.default_field`이면 DCOMP로 전달(TCL은 실패 시 type만 재시도). setup.ps1은 capture 절에 키가 없을 때만 1회 보충(줄 끝 "setup.ps1 D3-54"), 사용자 값(빈 값 포함) 보존. 컨투어 표시·응답 추가 폼은 결과 종류 CornerStress일 때 성분 후보 vonMises. ③ 일괄 예측 "캡처 예상" 가정값을 config `capture.estimate_image_mb 0.3·estimate_video_mb 1(기존 5)·estimate_sec_per_view 20·estimate_sec_per_video 40`으로 옮기고 `/status.capture.estimate`(+default_field·default_component)로 화면에 전달, 문구 "가정값 기준 참고" 유지.
- **D3-55 (사용자 결정 2026-10-17, 화면 톤·레이아웃 A)**: 2026-10-14 스위스 격자 결정을 대체 — PhysicsAI 화면 톤앤매너를 대시보드와 같게(시안 ToneDark·ToneLightDrawer 승인). ① 색: 대시보드 `theme.css` 다크·라이트 변수 세트를 이름·값 그대로 `[data-theme]`로(기본 dark), 빨강 강조·1px 바둑판 격자선·IBM Plex 제거. 글꼴 Pretendard(npm `pretendard@1.3.9` dynamic-subset 번들, CDN 없음, 대시보드와 같은 스택). 12열 격자는 카드형(radius 12·border·shadow·gap 16, 높이 내용대로). ② 테마 동기화: 같은 origin의 localStorage `simdashboard.workspace.theme.v1`(`dark`|`light`) → 레거시 `vd-workbench-theme` → `dark`(접근 실패도 dark), `storage` 이벤트로 대시보드 변경을 따라감. PhysicsAI는 저장하지 않고 자체 토글도 두지 않음. ③ 레이아웃 A: 우측 고정 열(대기열·워커 자원·모델) 제거, 작업 영역 12열 전체(화면 컴포넌트의 9열 기준 span을 `.workgrid`에서 12열로 환산 9→12·6→8·3→4). 상단 바에 상태 칩 2개("대기열 실행 R · 대기 W" — R = 로컬 슬롯+가벼운 작업 실행 수, W = 대기 수, 내 작업 실행 중이면 accent 강조 / "CPU x% · RAM a/b · GPU y%" — GPU 없으면 "GPU —", 워커 오프라인이면 "워커 오프라인"). 칩 → 오른쪽 서랍(폭 420, 겹쳐 열림, body 포털, `aria-modal`·`aria-expanded`, 포커스 트랩, Esc·바깥 클릭 닫기, 칩으로 포커스 복귀): 실행 대기열 상세(관리 버튼 권한 그대로)·워커 자원 상세. 대기열·자원 폴링은 칩과 서랍이 함께 쓰는 1곳(Study 화면에서만, 기존 주기). 모델 목록·Final 지정은 ③ 화면 카드(③-5 옆 4열)로, ④는 기존 "모델: <이름> vN Final · 다른 모델" 줄 유지. 단계 탐색은 큰 번호 01~05 대신 단계 버튼 ①~⑤(현재 = accent 테두리·selected 바탕, 최근 작업 상태 점 success/accent/danger). ④ 상태 배지(완료·실행 중·대기·실패·취소)는 pill, 버튼 주요 = accent 채움·보조 = 테두리, 차트는 `--color-chart-series-*`(단일 선 series-1, 고른 점 series-2). 상단 바가 `backdrop-filter`를 쓰므로 알림 서랍도 body 포털로 옮김. API·문구·동작 불변(서랍 안 구획 이름 "실행 대기열"·"워커 자원", ③ 카드 "모델 목록" 유지). 시험: designRules 갱신(토큰·대비 4.5:1 계산), tone.test(테마 3경우·칩→서랍·③ 모델·④ 우측 열 없음·단계 버튼).
- **D3-56 (사용자 요청 2026-10-17, 단계 버튼 강조)**: D3-55 단계 버튼 ①~⑤를 보강 — ① 가로: 스텝퍼를 내용 폭 5등분 격자(`repeat(5, minmax(0, 1fr))`, gap 8, radius 8)로 꽉 채우고 "Study 관리"는 같은 줄 오른쪽 끝 작은 버튼(`.stepper-row` = `1fr auto` 격자, 단계 폭을 줄이지 않을 만큼 작음). ② 세로: 최소 높이 52(`--step-h`), 글자 15px(`--font-step`/`--font-step-strong`, 현재 단계 600·accent 테두리 2겹·selected 바탕), 상태 점은 오른쪽 끝. ③ 번호: Pretendard에서 원 문자 ①~⑤가 작게(⊙처럼) 보여 숫자 배지(원 26px, 숫자 1~5, `aria-hidden`; 현재 단계는 accent 채움·`--color-text-on-accent`)로 바꾸고, 읽기용 이름은 sr-only 원 문자로 "① 학습데이터 생성" 그대로. 경로바의 원 문자는 그대로(범위 밖). ④ 좁은 화면: 1280 이하 페이지 가로 스크롤 없음, ≤1100에서 단계 최소 폭 170·스텝퍼 안에서만 가로 스크롤(약 1030 미만), 한글은 `keep-all`로 단어 단위 줄바꿈. API·문구·동작 불변. 시험: tone.test(5칸 격자·숫자 배지·aria-current·Study 관리 같은 줄, CSS 토큰 52/15). 스크린샷 tone 모드에 ④(stage4) 추가.
- **D3-57 (사용자 결정 2026-10-17, S11 SCX 잡 제출 — Plan)**: §16, 대시보드 쪽 계약 `docs/contracts/scx_relay.md`. ① 토큰 공유: PhysicsAI는 어댑터를 실행하지 않고 대시보드 loopback relay(`/internal/scx-relay/v1`, 헤더 `X-SCX-Relay-Key` 공유 비밀 파일·`hmac.compare_digest`·프록시 헤더 거부, 기본 꺼짐 `SIMDASH_SCX_RELAY_ENABLED`)를 부른다. ② 드라이브 `~`(= `/Users/vd.dashboard`, `hpc.scx.drive_base`) `/<Study 폴더 이름 정규화>/<01_D-NNN_<run>_<ts> | 04_V-NNN_<ts>>`, 항상 새 폴더(`_2`…`_9`), SPDM 루트(`SIMDASH_SCX_DRIVE_ROOT`) 안 쓰기 금지(예외 설정 없음), 삭제·이동·덮어쓰기 없음. ③ step 키 불변 — HPC_SUBMIT 안에서 단계 A STAGE_IN(모든 run 업로드 완료 후) → 단계 B 제출, COLLECT는 relay list·스트리밍 다운로드(`.part`→`os.replace`, sha256 확인). 업로드는 대시보드 업로드 대기열 경유(비동기 묶음 폴링). ④ `SUBMISSION_UNKNOWN` → `hpc_jobs.state=UNKNOWN`·`submission_unknown`, 자동 재제출·형제 자동 취소 없음, 남은 run 미제출, attention·알림 `HPC_SUBMISSION_UNKNOWN`, 사용자 조치 `POST /jobs/{id}/hpc-jobs/{hid}/resolve` recheck·attach·mark_not_submitted(워커가 처리). 같은 `request_id`(`pai-<hpc_jobs.id>`) replay만 자동(relay가 어댑터를 다시 부르지 않음). 확정 실패는 기존 형제 취소 유지. ⑤ 게이트웨이 확장: mode `scx`, 오류 코드 `SUBMISSION_UNKNOWN`, `HpcStatus.outcome·output_path·output_rel·error_message`(선택), 범용 `submit()`은 scx에서 `NOT_CONFIGURED`. migration `0009_scx_gateway`(hpc_jobs 9열 + 알림 이벤트). ⑥ Plan 가정(확인 요청): include는 `additional_paths`에 모두 나열(`list_additional_paths: true`), engine = `<base>_0001.rad` 있으면 `engine_paths`, 경로 표기 `rel`, output_path는 드라이브 경로 — E4-11-3~6에서 확인. D-/V- 번호는 DB 순번 계산(새 열 없음), 시각은 워커 현지 시각. 프런트 "확인 필요" 화면은 후속 작업.
- **D3-57 구현 메모(Impl-SCX, 2026-10-17 — Plan 확인 요청)**: ① §16.4 단계 A가 모든 run 행을 업로드 전에 넣으므로 결과 모름·확정 실패 뒤 "남은 run"은 행을 만들지 않는 대신 이미 있는 행을 `CANCELED`·`staged.phase=not_submitted`(문구 "제출하지 않음(앞 run …)")로 둔다 — 종료 판정(T10·T10b·T13)에서 실패로 세지 않고, `submitted` 수·T10b 총수에서 뺀다. ② 업로드 `X-Request-Id`는 `<request_id>:f:<순번>`(올릴 파일 이름순 1부터) — 파일 이름(비ASCII·공백·괄호·긴 이름)은 relay 헤더 규칙 `^[A-Za-z0-9_.:\-]{1,128}$`에 맞지 않을 수 있어 이름은 쿼리 `name`(UTF-8 퍼센트 인코딩)에만 둔다. ③ resolve 권한 = 재시도 규칙(작업 등록자는 power 이상, 그 밖은 전역 관리자). 작업이 `WAITING_HPC`가 아니면 `mark_not_submitted`만(그 밖 409 `HPC_RESOLVE_NOT_ALLOWED`). ④ 회수: Windows 예약 이름(CON·NUL…)·`?*<>"|:`·끝 마침표/공백·대소문자만 다른 경로·폴더/파일 이름 충돌은 그 run 회수 실패(`PATH_UNSAFE`), 로컬 쓰기 오류도 run 단위 실패. `.part`는 `<이름>.<임의>.part`(tempfile — 실패·취소 시 자동 정리). ⑤ 워커 중단으로 남은 `SUBMITTING` 행은 제출 단계였으면 `UNKNOWN`+submission_unknown, 업로드 단계(`phase=stage_in`)였으면 `FAILED`. ⑥ 금지 접두는 상대·`~/`·절대(`home_display` 기준) 표기를 모두 인식하고, 드라이브 목록 조회 전에 먼저 검사한다.
- **D3-58 (Impl-Frontend 2026-10-17, S11 SCX 화면 — §16.5 "후속 프런트", 필수 요소만)**: ① `npm run gen:api`(openapi = D3-57 구현 커밋) — `HpcJob` scx 필드·`HpcResolveRequest`, `api.hpcJobs`·`api.resolveHpcJob`(version = 행 version). ② 표시 조건: `/status.hpc.mode == "scx"`일 때만 `GET /jobs/{id}/hpc-jobs`를 읽고(작업 version이 바뀔 때 + 작업이 끝나지 않았으면 `poll_job_waiting_hpc_ms` 주기), 행 `gateway_mode == "scx"`만 scx로 표시 — PBS(command)·none 화면 불변. ③ ①-4 run 표(최신 TD_SOLVE 작업의 행을 run_key·최신 attempt로 연결): 열 "잡 ID"·"드라이브 폴더"(잡 폴더 마지막 구간, 전체 표시 경로는 title, 복사 버튼 — 입력 칸 없음), 상태 괄호에 게이트웨이 중립 단계(SUBMITTING=업로드 중 → 대기 → 실행 → 완료 → 결과 회수 중·결과 회수됨). `UNKNOWN`+`submission_unknown` 행은 상태 칸 "확인 필요" 배지(warning pill) + 바로 아래 줄에 "제출 응답이 끊겨 제출 여부를 모릅니다. 드라이브/SCX에서 확인 후 선택하세요" + 조치 3개(다시 확인=recheck / "SCX 잡 ID" 입력 + 잡 ID 연결=attach(빈 값이면 비활성) / 제출 안 됨으로 처리=mark_not_submitted, 확인 대화상자에 §16.5 주의 문구). 202 응답 행으로 바꿔 "조치 요청됨 — 다음 확인 때 처리합니다"(버튼 숨김), 409(VERSION_CONFLICT·HPC_RESOLVE_PENDING·HPC_NOT_UNKNOWN·HPC_RESOLVE_NOT_ALLOWED)는 문구 + 행 다시 읽기. 조치 버튼은 실행 권한(power) 화면에만, 최종 권한은 API. ④ ④ "PBS 검증 해석" 버튼은 mode scx면 "검증 해석(SCX)", 검증 작업 아래 SCX 잡 ID·단계·잡 폴더(복사)·결과 위치(output_path가 잡 폴더와 다를 때만), 결과 모름이면 배지·잡 폴더·같은 조치. ⑤ 주의 코드 `HPC_SUBMISSION_UNKNOWN` 문구 "SCX 제출 확인 필요". ⑥ 목 `?hpc=scx[&scx=unknown]`(MockOptions `hpcMode`·`scxUnknown`, hpc-jobs·resolve 라우트, 다음 tick에 조치 처리), 스크린샷 `node scripts/screenshots.mjs scx`. 시험: scx.test(단계 글자·배지·폴더·조치 3개·409·PBS 불변·④), mockContract(hpc-jobs·resolve 응답). **Plan 확인 요청**: ①-4 카드 제목·"PBS 제출"·작업 상태 "PBS 대기"·요약 "PBS n/m 완료"는 범위 밖이라 그대로. D3-57 구현 메모 ①의 미제출 행(`CANCELED`·`staged.phase=not_submitted`)은 응답에 phase가 없어 "취소됨"으로 보인다 — `HpcJob`에 phase(또는 not_submitted 표시)를 내주면 "제출 안 함"으로 구분 가능.
- **D3-59 (사용자 결정 2026-10-17, S12 DOE 설계공간 지도 — Plan)**: §17. ④ 일괄 예측 결과 그래프 카드에 탭 [변수–응답] [설계공간 지도](S14 이후 ⑤ 결과분석). ① run별 대표값(커브 max·min·\|max\|, RESP `_MIN`·`_MAX`, 옛 방식 표 값)은 **백엔드** `GET /predict-batches/{bid}/design-map`에서 계산(파일별 LRU, 새 DB·설정 없음) — 프런트 `curves` 응답은 계열 1개·다운샘플·run 상한이라 계열 전환마다 재요청이 필요하고 RESP 원값이 없기 때문. ② PCA·PLS(NIPALS PLS1 2성분)·평행 좌표는 **프런트 TS**(n ≤ 200, p ≲ 20, 색 값 변경 시 즉시 재적합). ③ 변수 = 반영값, 유효 run 기준 z-점수(ddof=1), 상수 변수 제외, 축 % 정의(PCA = X 분산, PLS = X 분산 %·값 분산 %), 구조 상관 바이플롯, viridis. ④ 지표 id 문법과 공용 모듈 `stage4_predict/run_metrics.py`는 S13 목적함수와 공용. ⑤ 커브 지표 계열을 커브 겹쳐보기와 연동. 새 의존성 없음.
- **D3-59 구현 메모 (2026-10-17)**: 생성 파일(`backend/openapi.json`·`schema.d.ts`·`frontend-dist/**`)은 먼저 병합한 쪽 기준으로 재생성(S13은 그 위로 rebase 후 재생성). 목록 밖 수정: `test_openapi.py`(라우트 목록)·`operation_ids.txt`·`screenshots.mjs`(`designmap` 모드). `BatchResult.tsx` 352줄(300줄 규칙 초과) → 후속 분할(R-F). 평행 좌표 브러싱은 마우스 이벤트, `metric_value`는 문법 밖 id에 ValueError, `tbl:*`는 값이 하나라도 있는 템플릿 응답만.
- **D3-60 (사용자 결정 2026-10-17, S13 쿠션만 최적화 + 이슈 #4 — Plan)**: §18. 모드 `플랫폼 내장(쿠션만 가능)`(기본) | `원본 최적화(조립 필요)`. ① 내장 = 탐색(새 DOE 배치 또는 재사용) → GP(Matérn 5/2 ARD)·RBF(cubic) 적합·LOO → 후보 k개(활용 1 + EI×PoF kriging believer, 정수 변수 `integrality`) → **PREDICT_BATCH(source table)로 실제 예측 체인 검증** → 개선 < tol_rel(1%) 또는 반복 3까지(기본 3 × 4). ② 반복 제어는 종료 훅 연쇄: 배치 DONE → `job_end`가 `SURROGATE_OPT`(SLOT, SO_COLLECT·SO_FIT·SO_PROPOSE·SO_NEXT, INTERNAL) 투입 — 기다리는 동안 슬롯 미점유. ③ migration `0010_surrogate_opt`(Study당 진행 중 1개, 알림 `SURROGATE_OPT_DONE`, 활성 인덱스에서 최적화 소유 PREDICT_BATCH 제외). ④ **새 런타임 의존성 numpy·scipy**(지연 import, 없으면 `features.optimize_builtin=false`) — 사용자 확인 대상. ⑤ 범위는 학습 범위 안만, 검증 배치 캡처 기본 끔, 소유 배치의 배치 단위 취소·실패만 다시는 409 `BATCH_OWNED_BY_OPT`. ⑥ 이슈 #4: 원본 OPTIMIZE를 mesh_only 템플릿으로 생성·재시도하면 409 `TEMPLATE_ASSEMBLY_REQUIRED`, 워커 `op_prep`도 같은 코드로 실패(TypeError 제거).
- **D3-60 구현 메모 (2026-10-17)**: ① 설치 판정은 `sys.path` 패키지 폴더 확인(`surrogate.missing_modules`, V2-LCH-1 정적 시험이 importlib 금지). 고정 numpy 2.4.6·scipy 1.17.1. ② 설정 `surrogate_opt.blas_threads`(4, 바꾸면 워커 재시작 뒤 적용), problems `TOL_RANGE`·`MULTI_EXECUTION_RANGE`, 상세 `runs`, 경고 `OBJECTIVE_CONSTANT`. ③ `resume`은 반복 작업을 step 1부터 재시도(검증 배치가 이미 등록돼 있으면 VERIFYING으로 복원), SO_NEXT는 같은 반복 행 재사용(멱등), 반복 작업의 `/jobs/{id}/retry`는 409, 훅 실패는 로그만, 소유 배치 부모 취소 시 opt `FAILED BATCH_FAILED`(이어서 실행 가능), 소유 작업은 `JOB_CANCELED` 알림 없음, `opt.json`은 `_backup` 후 다시 씀.
- **D3-61 (사용자 요청 2026-10-17, S13 결과 화면 보강)**: 내장 최적화 결과에 최적안 대 기준안 카드·결과 요약 타일·컨투어 비교(같은 범례)·수렴 그래프 기준안 수평선. **마무리 캡처 배치**: 정지 시 캡처가 구성돼 있으면 opt를 `FINALIZING`으로 두고 최적화 소유 PREDICT_BATCH 1개(table 2행: 기준안 nominal + 최적안, 캡처 켬)를 iters `kind FINAL`로 등록, 배치 DONE → 훅이 DONE + 알림. 캡처 미구성이면 바로 DONE + `final.status SKIPPED`, 마무리 부모 실패·취소면 DONE 유지 + `final.status FAILED|CANCELED`, 캡처 도구 실패는 DONE. migration **`0011_surrogate_final`**(`surrogate_opts.final` JSONB, 상태 `FINALIZING`, iters kind `FINAL`). 상세 `final{…}`·`parameters[]`·`progress_text`; `runs`·`iterations`·runs.csv는 FINAL 제외.
- **D3-61 보강 (Verifier 2026-10-17)**: 같은 범례는 목적이 컨투어 결과 종류(템플릿 display field)의 RESP 값일 때만(범위 0 ~ max(기준안 예측, 최적값) × 1.05). 그 밖이면 범례 없이 이미지마다 자동 + `final.legend_note`. `complete_final`은 savepoint로 실패는 로그만.
- **D3-62 (사용자 결정 2026-10-17, S14 화면 단계 재편·⑤ 결과분석 — Plan)**: §19. ① 화면 단계 ④ 예측 · ⑤ 결과분석(신설) · ⑥ 최적화(기존 ⑤). 내부 코드 경로·job 이름·DB·URL 숫자·e2e 기존 번호는 유지하고 메뉴 순서·표시 번호·라벨만 프런트에서 변경(신규 라우트 `/stage/analysis`). ② 입력 = `ResultTable`(source solver\|predict). 출처 (a) 일괄 예측 배치(기존 API), (b) 해석 DOE(새 읽기 전용 `GET /train-does/{doe_id}/result-table`). ③ 분석 = PLS·PCA·커브 강조 재사용 + 영향도(PRCC·SRC), 대리모델 Sobol 비범위. ④ solver vs predict 겹쳐 보기는 파라미터 이름 집합이 같을 때만. ⑤ 시험 V3-S14-*, 서버 확인 E5A-*.
- **D3-62 구현 메모 (2026-10-18, 사용자 승인 "추천대로")**: `rows[].state`는 `train_runs.state` 원값(프런트가 정규화), `type`은 doe_type 원값, 행 상한 `train_data.max_runs`, 단위는 DOE `parameters_snapshot`, samples 없음·Study 밖·링크면 404 `SAMPLES_MISSING`. 겹쳐 보기 응답 선택은 두 표 공통 응답만. 영향도 행렬 특이 시 전체 "계산 불가". 해석 결과 폴더 직접 지정은 보류.
- **D3-63 (사용자 결정 2026-10-18, S15 표본 방식 추가 — Plan)**: §20. ① ④ `source.kind`에 `lhs_opt`·`sobol`(scipy 지연 import)·`fullfact`·`fracfact`·`pb`·`bbd`·`ccd` 추가, 미리보기·생성·워커가 같은 행. ② ④ 기본 = 최적화 LHS, ① 기본 = LatinHyperCube(`train_data.recommended_doe_type`), 선택창 설명문. ③ ①은 정의 파일 4개 유형 유지(새 방식은 ④ 전용 → S18에서 ① 플랫폼 생성으로 해소). ④ migration `0012_sampling_kinds`(CHECK 확장), 방식 인자는 `source_meta`. ⑤ 영향도 등급 formal/reference/off를 서버가 정함(`influence_ok` = class ≠ off, s14 "LHS가 아닌 해석 DOE 비활성" 폐지). ⑥ 새 라우트 없음. ⑦ S13 "API 프로세스 numpy 미적재"는 Sobol(`sampling/qmc.py`)만 예외. ⑧ 시험 V3-S15-1~15, 서버 확인 E4-13·E1-8. 미결 처리(사용자 "일단 가보자고"): ①은 4개 유형 유지, 나머지 계약 기본안 채택.
- **D3-63 구현 메모 (2026-10-18)**: 기존 `lhs`는 V3-S9-5 골든 유지를 위해 `quality`를 저장하지 않고 응답에서 계산. `FIXED_EXCLUDED`·`DUPLICATE_ROWS`·`INFLUENCE_TOO_FEW`는 새 7종에만. `CONTINUE_INVALID` 사유 추가. 이어서 추가 권장 run·문구 = `offset & -offset`. `lhs_opt` seed ≥ 0. influence 모양 `{ok, cls, note, reason}`. fracfact k = 2·3에서 IV 요청 시 IV 문구(확인 대기).
- **D3-64 (사용자 VOC 2026-10-19, S16 — Plan)**: §21. ① V1 ④ 단일 예측 실행 목록(새 DB 없이 jobs로 `GET /studies/{id}/predict-runs`·`/predict-runs/{job_id}`, 일괄 하위 제외, 재시도 묶음은 최신 1행). ② V2 조립 FEM 검증: 새 job_type `FEM_VERIFY`(FV_PREP·FV_MESH·FV_ASSEMBLE·HPC_SUBMIT·HPC_WAIT·COLLECT·FV_EXTRACT·FV_CURVE·FV_CAPTURE·FV_COMPARE). 메시 교체는 기존 m_2·`assemble_into` 재사용, 제출은 기존 게이트웨이(PBS·SCX, SUBMISSION_UNKNOWN 규칙 그대로, 잡 폴더 `04_FV-NNN_<ts>`). 출처 4종, 같은 설계점 예측이 없으면 동반 PREDICT + 종료 훅 연쇄, 조립 원본 3종(스냅숏 복사), 비교 = 응답 MIN/MAX·오차%·T01 커브·컨투어 같은 범례, `fem_verify.field_map`. 재시도는 해석 전 실패면 처음부터(새 시도), 후처리 실패면 그 step부터. ③ migration `0013_fem_verify`(`fem_verifications`, 활성 인덱스에서 FEM_VERIFY·동반 PREDICT 제외, Study당 `max_active` 4, 알림 `FEM_VERIFY_DONE`). ④ PREDICT_VERIFY는 유형·API·기록 유지 + 화면 버튼만 "FEM 검증"으로 대체, HPC 헬퍼는 `_verify_hpc.py`로 공유(동작 불변). ⑤ V3 영상: TCL이 저장 뒤 존재·크기 확인(`VID_SCOPE`), 경고 `CAPTURE_VIDEO_FAILED`·`video_error`, 선택적 ffmpeg 변환(목표 1 MiB, 원본 `media/raw/` 보존), 프런트 `MediaVideo`. ⑥ 시험 V3-S16-1~26, 서버 확인 E4-14-H1·F1~F8·V1~V7.
- **D3-64 구현 메모 (2026-10-19)**: TCL은 VID_SCOPE 값이 있을 때만 page/window 분기(기존 골든 유지). 영상 상한 초과는 `video_error` + 기존 `CAPTURE_VIDEO_TOO_LARGE`로만. `FvCompareRow`에 min/max_diff(_pct), 커브 짝은 `compare.curve.pairs`. 목록 밖 수정: `core/fs_browse.py`(SPDM 목록)·`schemas/studies.py`(FEM_ASSEMBLY)·`step_process.py`(파생 영상 템플릿)·`config/loader.py`·`schemas/jobs.py`·`study_job.py`(활성 인덱스). 후속 minor 4건(Windows 예약어 검사, reuse verify.json sha256, 동반 예측 출처 중복·retry 시 max_active 재검사, 옛 PREDICT_VERIFY SCX 확인 필요 조치 UI)은 S19 M0에서 처리.
- **D3-65 (사용자 VOC·결정 2026-10-19, S17 성능 정의·다목적 내장 최적화 — Plan)**: §22. ① 성능 = 템플릿 응답 정의 확장(새 테이블 없음): H3D + 새 `source:"CURVE"`(계열·stat), 진행 중 최적화가 쓰는 성능의 정의 변경·삭제는 409 `PERF_IN_USE_BY_OPT`. ② 지표 `perf:<NAME>`과 공용 순수 함수 `performance.py`, H3D는 `H3D_REQUESTS.txt` 줄과 비교해 다르면 `SPEC_CHANGED`(null), `RunMetrics.requests` 추가. ③ ④ RESPONSE_EXTRACT가 CURVE 값을 채움(CURVE만이면 TCL 미실행), ①-6·PV는 CURVE를 조용히 건너뜀, 끝난 배치의 H3D 성능 다시 추출은 새 job `PB_RESP_EXTRACT`(`POST /predict-batches/{bid}/extract-responses`). ④ 역할: 목적 1~3·제약 ≤ 5(≤·≥·range, `==` 없음)·관찰 ≤ 10을 `settings`에만, 성능 정의는 스냅숏, 단수 `objective` 호환. ⑤ 다목적은 `SURROGATE_OPT` 확장(목적별 GP, 예측 전선 = 격자 증강 Chebyshev + DE, 후보 = HVI + ParEGO, HV 고정 틀(기준점 1.1) 정확 HV 수렴). ⑥ 결과: 검증 파레토 해와 예측 전선을 구분, 가중 추천(0~1 정규화 가중합 최소, 골든 §22.6), 해 선택 → 단일 예측 / 추가 검증 배치(`POST /surrogate-opts/{oid}/verify`, iters `EXTRA`) / FEM 검증, FINAL 2행 = 기준안 + 가중 추천점. ⑦ migration `0014_multiobj`. ⑧ 설정 `surrogate_opt.{max_objectives, max_observe, max_extra_points, mo_*}`. ⑨ 시험 V3-S17-1~13, 서버 확인 E4-17. 파일 소유는 Impl-Backend / Impl-Frontend로 나누고 `services/surrogate_opts.py`는 300줄 규칙에 맞춰 problem·pareto 서비스로 분리.
- **D3-65 보강 (메인, 2026-10-19)**: FEM 검증 연동 placeholder를 S16 확정 API로 교체 — `POST /studies/{id}/fem-verifications` + `source:{kind:"opt_design", opt_id, pick:"run", iter_no, doe_no}`, 가용 여부 `/status.features.fem_verify`. 병합 순서 S16 → S17 고정.
- **D3-65 보강 2 (사용자 2026-10-19 "추천대로")**: ⑤ 결과분석 영향도·변수–응답·설계공간 지도의 응답 선택지에 커브 대표값(`curve:max\|min\|absmax` + 계열)과 성능(`perf:<NAME>`)을 포함. 출처 (a)는 design-map 지표 값을 결과 표 열로 싣고(`fromBatch`), 출처 (b)는 기존 응답만. 응답 열이 모두 비면 off 사유에 "④ 템플릿에 성능을 정의하거나 커브 대표값을 고르세요"를 덧붙임. 서버 변경 없음.
- **D3-65 보강 3 (구현·Verifier 판정, 2026-10-19)**: ① 3목적 후보 배분 변경 — HVI 후보 ⌈k·`mo_hvi_share_m3`⌉개(0.5), 나머지 ParEGO 획득값 × exp(−`mo_front_prox_m3`(6.0)·예측 전선 정규화 거리)(원안 DTLZ2 0.666 미달 → 변경 후 시드1 0.734). ② §22.6 골든 5행(f₂ max) 정정(정답 `backend/tests/data/s17_recommend.json`). ③ V3-S17-6 DTLZ2 231점 HV는 이산 점 정확 HV 0.76909 → 허용오차 0.04. ④ 동시 생성 409는 `STUDY_JOB_BUSY`, `PB_RESP_EXTRACT`는 TCL 추출 방식에서만, 추가 검증 점 수 초과 422 `EXTRA_POINTS_RANGE`, EXTRA 배치는 최적화 소유 아님. ⑤ ⑤ 결과분석 `perf:` 클라이언트 계산의 SPEC_CHANGED 미감지 한계 → S19에서 서버 계산으로 해소(§24). ⑥ V3-S13-9 설정 화면 시험은 성능 표 교체로 수정(결과 화면 시험 무수정). ⑦ 기준안 ◇ 생략, ⑤ 커브 열 12계열 × 3 상한. ⑧ V3-S17-7 루프는 `slow` 마커(기본 test-all은 ZDT1 시드1). 후속: 300줄 초과 파일 분할(R-B·R-F).
- **D3-66 (사용자 VOC·결정 2026-10-19, S18 ① 학습 DOE 플랫폼 동시 생성 — Plan)**: §23. ① S15 §20.3 안 B 채택 — `TD_DOE_GEN`에 생성 방식 `platform`(화면 기본)·`hyperstudy`(호환, 코드 무변경). job_type·step 키 3개·가중 유지, `HST_GEN_RADIOSS`가 `train_does.generator`로 분기하고 라벨만 "입력 생성(run별)". API 기본: `generator` 생략 → `sampling` 유무로 판단. ② 플랫폼 표본 = S15 `build_matrix` 8 kind, 범위 = ①-2 표, 상한 `train_data.platform_max_runs`(500), API는 검증·run 수만(422 `DOE_SAMPLING_INVALID`), 워커 DG_PREP이 행을 `train_doe_points`에 저장하고 `doe.json` 기록. ③ run마다 m_1→m_2→m_3을 `run_parallel`로 최대 M개 동시 실행(기본 4, 상한 `max_multi_execution`, Job Object 1개). 체인은 ④ `_gen_one`에서 공용 `steps/run_chain.py`로 추출(④ 동작 불변), 형상 생성 경계 = `run_chain.geometry_update` 한 함수(native 교체 지점). ④ 원본 일치는 다운스트림 규칙만(`D/{platform_run_root}/run__NNNNN/{m_1,m_2,m_3}`, input_rel = m_3, samples.csv = 반영값 PARSED). ⑤ 실패 `on_run_failure` = `fail`(기본, `GEN_PARTIAL_FAILED`, 재시도 = 실패 run만) \| `continue`(`PARTIAL_OUTPUT`), 취소 = 그룹 종료 + RUNNING 행 PENDING. ⑥ migration `0015_doe_platform_gen`(`train_does.generator`·`sampling`, 새 `train_doe_points`). ⑦ API: `TrainDoe.generator`·`sampling`·`gen`, result-table `sampling`, `/status` 설정 3개·`features.train_doe_platform`. ⑧ 화면: 방식 세그먼트·8개 드롭다운·`td_*` 설명·동시 수·실패 처리 체크, HyperStudy 모드는 기존 UI + 호환 회색 줄. ⑨ 사용자 추가 결정(native 전환 예정)으로 hstbatch 개선·HyperStudy 식별자 조사(S15 E1-8-2)·레거시 4종 매핑·① mesh_only는 비범위. ⑩ 시험 V3-S18-1~10(가짜 SimLab barrier로 동시 실행 하한을 결정적으로 증명, 시각 비율 단언 없음), 서버 확인 E1-9-1~5.
- **D3-66 보강 (메인, 2026-10-19)**: 프로젝트 문서 `contracts/geometry-engine.md`(native = paicad, 공칭 메시 모핑, TD_DOE_GEN native 모드)와 대조 — native 엔진은 SimLab 메시를 거치지 않을 수 있어 교체 경계를 `geometry_update`뿐 아니라 `run_chain.build_run_inputs`(m_1 → m_2 → m_3) 단위로도 바꿔 끼울 수 있게 둔다(엔진 선택은 `run_chain.select_engine`, 이번엔 altair만). R-8 해소 방향.
- **D3-66 구현 메모 (2026-10-19, Verifier 판정)**: 이슈 #7 포함 — `train_data.run_dir_glob`은 목록(기본 `["approaches/doe_*/run__*","*/approaches/doe_*/run__*"]`, 옛 문자열 기본은 자동 정규화), 0건이면 `*/` 재탐색(상위 `setup_*` 공칭 run 제외), 같은 run_key 중복 폴더는 제외 + 경고. 층 규칙상 `sampling/matrix.py`(batch_matrix 재노출)·`run_chain.mesh_preflight` 추가(후속: batch_matrix를 sampling으로 이동 → R-B). 설정 검증은 `validate_stages.py`, `build_run_inputs(param_set=)`, `limits.configured.doe_platform_parallel_default` = min(설정, max_multi_execution). 프런트: 지원 범위 밖이어도 실행 허용·서버 422 problems 표시. 후속(Low): td_sobol 2줄 최대값, lhs 대체 검증 notes 차이, `TPL_CHANGED_REGEN` 시 표본 값 유지, TrainDoe 목록 N+1 조회.
- **D3-67 (사용자 승인 2026-10-19, S19 후속 — Plan)**: §24. ① GPU 조회: `worker.gpu_query_timeout_s`(15)·`gpu_backoff_after`(3)·`gpu_backoff_max_s`(300). 조회는 `GpuMonitor` 스레드가 하고 하트비트는 캐시를 쓴다. 워커 로그는 상태 전이 때만 1줄. `/resources`는 `gpu_status`·`gpu_message`를 재사용하고 `gpu_fail_streak`·`gpu_sampled_at`·`gpu_next_query_at`를 추가. 칩 툴팁·서랍에 실패 원인을 표시. ② ⑤ `perf:`는 design-map이 서버에서 `performance.perf_value`로 계산(`runs[].perf`·`perf_reason`, `metrics[].spec_changed`, `counts.spec_changed`, `reason_text`), 옛 추출 run(H3D `NOT_EXTRACTED`)만 결과 표 값으로 대체, 지표 순서는 기존 뒤에 perf. 프런트 `perfValue`·`withPerfMetrics` 제거 + 칸 사유 표시(D3-65 보강 3 ⑤ 해소). ③ migration 없음(head 0015 유지), 새 job_type·step·라우트 없음. ④ 시험 V3-S19, 서버 확인 E0-8-1~3. ⑤ 계약 없는 승인 항목(S16 minor 4건·문구·시험·그림 = M0, 300줄 분할·`batch_matrix` sampling 이동 = R-B·R-F, 문서 이관 = D)은 §24.11 순서에 둔다. 분할은 기능 변경과 Verifier 뒤 마지막.
- **D3-67 구현 반영 (2026-10-20)**: ⑥ **④ GPU 동시 예측 철회** — 사용자 결정. 원 계약의 동시 예측 설계·관련 설정·시험·서버 확인(E4-19)은 무효이고 이 문서에 옮기지 않는다. ④는 S18과 같이 SLOT 단일 FIFO로 1개씩 예측한다(§2.3 R3-9). 구현 중 Verifier가 동시 OOM 교착(High)과 free/프로세스별 조회 시차로 인한 과입장(Medium)을 찾았고 난도 대비 효용이 낮아 걷어냈다. 유지 범위는 GPU 조회 제한 시간·원인 표시(B-GPU·F-GPU)와 perf 서버 계산(B-PERF·F-PERF). ⑦ V3-S19-11 예외 1건: V-SM-6 `test_no_timeout_key_in_schema`는 `worker.gpu_query_timeout_s`를 제외(작업 실행 시간 한도 없음이라는 취지는 유지, V3-S9 시험 무수정).

## 변경 메모 (Plan, 2026-10-21 — D3-46 대체)

- D3-46·§12의 "공유 `physicsai-inbox`에 복사 후 찾아보기(업로드 없음)"는 [upload-report.md](upload-report.md)의 브라우저 업로드로 대체(사용자: "공유폴더 안돼"). `/fs/roots`의 `inbox` 루트·`storage.inbox_dir`은 호환용 유지, `inbox_share_hint` 안내 문구는 화면에서 내림. `/fs/roots`에 `upload` 루트 추가, `/fs/list`는 `.part` 숨김. `/fs/*` 자체는 계속 읽기 전용.
