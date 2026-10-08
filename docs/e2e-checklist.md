# 사용자 E2E 체크리스트 (Altair PC)

- 대상: Altair 2026.1과 GPU가 있는 Windows Server(대시보드와 같은 PC)
- 목적: 자동 시험(Linux, 가짜 도구)으로 확인할 수 없는 실제 동작과 계약 미확정 항목(U1~U16, [platform.md §19](contracts/platform.md#19-리스크미확정)) 확인
- 기록: 각 항목 결과 칸에 `통과` / `실패(내용)` / `미수행`과 날짜를 적고, 확인한 실제 값(명령 출력, 파일 이름)은 "메모"에 남긴다. 미확정 항목 결과는 Plan에 전달해 계약·설정을 갱신한다.

## E0. 준비

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E0-1 | PostgreSQL에 DB `physicsai`·전용 계정 생성, `PHYSICSAI_DATABASE_URL` 설정, `scripts\dev-db-init.ps1` 성공 | | |
| E0-2 | `config\platform.yaml` 작성: `ai_root`(공백 없음), `altair.*` 5개 실제 경로, `resources.preview_pred_h3d_tcl`, `profile: prod`. 백엔드 기동 로그에 설정 오류 없음 | | |
| E0-3 | `scripts\dev-backend.ps1`, `dev-worker.ps1`, `dev-frontend.ps1` 기동. `/physicsai/api/status`에서 worker online, altair 5개 ok, limiter `windows_job` | | |
| E0-4 | 대시보드(`http://127.0.0.1:5173` 또는 운영 주소)에 로그인 후 `http://127.0.0.1:5174/physicsai/` 접속 → 로그인 없이 내 이름·역할 표시(U14) | | |
| E0-5 | 로그아웃 상태에서 접속 → "대시보드에서 로그인" 안내 | | |
| E0-6 | general 계정: 조회만 가능, 실행 버튼 비활성. power 계정: 실행 가능, 대기열 취소 버튼 없음. 전역 관리자: 순서 이동·취소 가능 | | |
| E0-7 | `ai_root`를 매핑 드라이브(예 `E:` → `\\서버\share`) 또는 `subst`로 만든 드라이브로 두고: 드라이브 문자 경로와 UNC·실경로 형태 입력이 모두 "확인" 통과, 데이터셋 생성·산출물 내려받기·`_backup` 이동 정상, 화면 표시 경로(`*_display_path`)를 탐색기에 붙여넣어 열림. dedup 볼륨이면 일반 파일이 링크로 거부되지 않음 | | |

## E1. 워커 자원 제한(Job Object)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E1-1 | 실행 중 edspy 프로세스와 그 자식(python 등)이 같은 Job에 속함(Process Explorer → Job 탭) | | |
| E1-2 | Job의 CPU rate 제한(hard cap)·메모리 한도 64 GB·우선순위 Below Normal 확인 | | |
| E1-3 | 64코어 이상 PC라면 작업 관리자 CPU 사용률이 약 `32/전체 코어` 비율 이하로 유지 | | |
| E1-4 | GPU 사용량 제한 없음(nvidia-smi로 사용률 확인), 우측 패널 GPU 막대 표시 | | |
| E1-5 | 관리자 취소 → 2초 안팎에 프로세스 트리 전체 종료, 작업 `CANCELED`, 등록자에게 알림 | | |
| E1-6 | 실행 중 워커 창 강제 종료 → 자식 프로세스 모두 종료, 약 1분 후 작업 `INTERRUPTED`(WORKER_LOST) | | |
| E1-7 | Altair 런처가 Job 밖으로 빠져나가지 않음(BREAKAWAY 오류 없음)(U11) | | |

## E3. ③ 데이터셋·모델

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E3-1 | AI 루트 하위 h3d 폴더 지정 → "확인" 요약 개수가 실제와 일치. 한 run 폴더에 h3d가 여러 개인지 확인해 `split_group` 기본값 판단(U12) | | |
| E3-2 | "데이터셋 생성" → `03_dataset/<id>/train|eval/dataset.psdata` 생성(≥1 MiB), `split.json`의 eval이 약 10%, 같은 seed 재실행 시 같은 분할 | | |
| E3-3 | "학습 패키지 내보내기" → `03_package/<id>/dataset_train.psdata`, `COMMANDS.txt`. 패키지 폴더를 HPC에서 읽을 수 있고 하드링크 파일이 정상 동작(U15) | | |
| E3-4 | HPC에서 `COMMANDS.txt` 명령으로 학습(플랫폼 밖). 로그를 `train.log`로 저장 | | |
| E3-5 | 모델 폴더 등록 → loss 곡선·epoch 수·최종/최소 loss 표시. 로그 형식이 다르면 "로그 형식 미확인" 표시 후 실제 로그 몇 줄을 메모(U5) | | |
| E3-6 | "평가" → `.psscr`·`predictions.psdata` 생성, 평가 데이터가 홀드아웃(eval psdata)인지 step 명령에서 확인. edspy 출력의 점수 줄을 메모(U6) | | |
| E3-7 | 같은 모델 재평가 시 이전 psscr이 `_backup`으로 이동 | | |
| E3-8 | Final 지정·재지정, 우측 패널 Final 배지 | | |

## E4. ④ 단일 예측

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E4-1 | 파라미터 세트 폴더(parameters.json, samples.csv, responses.json, cad/, tpl, radioss_assem/) 등록 성공. tpl 변수와 파라미터 이름 불일치 시 거부 | | |
| E4-2 | 입력 값 채우기: 공칭 / 학습 run 불러오기 / 직접 입력. 범위 밖 값 → 작은 문구 "학습 범위 밖 · 최근접 run_xxxx". 비정수 값의 정수 반영이 HST 학습 때와 같은 규칙인지(반올림/절삭)(U9) | | |
| E4-3 | TPL_RENDER 결과 파일(`04_predict/<job>/geom/…`)이 SimLab에서 실행 가능한 형식인지, `geom_update` 기본 명령으로 형상 갱신+메싱이 되는지. 안 되면 실제 명령·파일 이름 메모(U2) | | |
| E4-4 | SimLab 출력 메시 파일 이름(`eps_mesh*`?)과 starter의 include 연결 확인, `INPUT/`의 조립 결과로 Radioss 입력이 완전한지(U3) | | |
| E4-5 | EDSPY_PREDICT → `RESULT/<stem>_pred.h3d` 생성, `.xy`/`.xydata` 생성 여부 | | |
| E4-6 | CONTOUR_PREVIEW 출력: `H3D_PREVIEW.json` 외에 이미지 파일이 생기는지(U4). 화면에 결과 목록 또는 이미지 표시 | | |
| E4-7 | 응답값 표: 최근접 run 실측 열(samples.csv `resp:` 열) 표시. 예측 열은 `response_extract` 미구성 시 "추출 미구성"(U8) | | |
| E4-8 | HyperView에서 `_pred.h3d`를 열어 응력 MPa·변위 mm 등 단위계(mm-ton-s)가 기대와 같은지 | | |
| E4-9 | "PBS 검증 해석" 버튼이 hpc `none`에서 비활성 + 안내 | | |
| E4-10 | 평가·예측 시 edspy에 pscfg가 필요한지(경고·오류 여부)(U7) | | |

## E5. 대기열·알림·화면

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E5-1 | 두 사용자가 연달아 작업 등록 → 대기 순번 1·2, FIFO 실행. 다음 차례가 되면 "다음 차례입니다" 알림 | | |
| E5-2 | 전역 관리자가 대기 순서 변경 → 실행 순서 반영 | | |
| E5-3 | 시작/완료/실패 토스트(우하단), 벨 미읽음 수, 알림 이력 읽음 처리 | | |
| E5-4 | 32인치 4K(3840×2160, 배율 100%·150%)에서 가로 스크롤 없음, 우측 패널·표·차트가 읽기 좋은 크기 | | |
| E5-5 | ①②⑤ 스텝 클릭 시 "2차에서 제공 예정" 안내만 | | |
| E5-6 | AI 루트 밖·SPDM 경로를 입력하면 거부, SPDM 폴더에 파일이 생기지 않음 | | |

## E6. (2차 준비, 선택) PBS 명령 확인

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E6-1 | 사내 PBS 제출·상태·취소 명령, job id 출력 형식, 상태 문자, 종료코드 표기, 이 PC 경로 ↔ 노드 경로 대응을 메모(U1) | | |
