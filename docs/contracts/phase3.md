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
- `input_path`: `check_user_path`, 허용 루트 = `allowed_roots(imports=True)`. 공백·cmd 메타문자·링크·`_backup`·`_platform` 거부(`PATH_OUTSIDE_ROOT`/`PATH_UNSAFE`/`PATH_NOT_FOUND`). 파일이면 확장자 ∈ `predict.prepared_input_exts`(기본 `[".rad",".hm"]`). 폴더면 직계 `starter_glob` 일치·eps_mesh 아님 정확히 1개.
- 복사 대상: `.rad` 파일 또는 폴더 → 그 폴더 직계 `*.rad`·`*.inc`(eps_mesh 제외, 하위 폴더 무시). `.hm` → 그 파일만. 각 파일명 `file_safety_problem` 통과, 개수 ≤ `predict.prepared_max_files`(500), 합계 ≤ `predict.prepared_max_total_bytes`(2 GiB).
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

API: `POST /studies/{id}/paths/inspect`에 `purpose:"PREDICT_INPUT"`(파일·폴더) → `{kind, starter:[names], starter_ok, rad:[≤50], inc_count, file_count, total_bytes, problems:[{code,message}]}`. `/status` `features.predict_parametric`. `backend/openapi.json` 갱신.

화면(최소 UI): ④ 맨 위 "입력 방식" 토글 1개 — `파라미터로 형상 생성`(기본) / `준비된 입력 파일`(선택은 localStorage `physicsai.stage4.inputMode`, try/catch). 준비된 입력에서는 파라미터 세트 카드·입력 표를 숨기고 카드 1개: 경로 입력 + "확인"(요약 한 줄 "starter · rad N · inc M", 문제는 회색 문구, "직계 파일만 복사" 참고 문구) / 모델(기본 Final) / "예측 실행" + "PBS 검증 해석"(기존 규칙). 결과는 기존 컴포넌트 재사용. 파라미터 세트가 없어도 토글·카드 표시. `predict_parametric=false`면 첫 선택지 비활성 + 툴팁 "형상 갱신 설정 필요(관리자)".

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
- **D3-28 (Plan, 2026-10-15, S6 신설)**: 원본 ④ 흐름 재추적으로 platform.md §8.9의 U2·U3·U4·U7을 해소(§11.2), 시연을 막는 P1 3건(eps_mesh starter 중복, HyperMesh m_2 누락, 폴더 등록 eps_mesh·csv) 수정 규칙과 준비된 입력 예측(`input_mode`)을 §11에 정함. platform.md §19 U2·U3·U4·U7 → phase3 §11.2.
