# 사용자 E2E 체크리스트 (Altair PC)

- 대상: Altair 2026.1과 GPU가 있는 Windows Server(대시보드와 같은 PC)
- 목적: 자동 시험(Linux, 가짜 도구)으로 확인할 수 없는 실제 동작과 계약 미확정 항목(U1~U16, [platform.md §19](contracts/platform.md#19-리스크미확정)) 확인
- CI: 결과 칸에 "CI 검증됨(러너 기준), 실제 PC에서 재확인 선택"이 적힌 항목은 GitHub Actions windows 잡(깨끗한 Windows 러너, Altair 없음·가짜 도구)에서 자동 확인된 것이다(관리자 매뉴얼 §14-1). 운영 PC 고유 조건(실제 Altair·코어 수·서비스 계정·세션 0)에서 다시 보려면 같은 항목을 수행해 덮어쓴다.
- 기록: 각 항목 결과 칸에 `통과` / `실패(내용)` / `미수행`과 날짜를 적고, 확인한 실제 값(명령 출력, 파일 이름)은 "메모"에 남긴다. 미확정 항목 결과는 Plan에 전달해 계약·설정을 갱신한다.

## 2차 (먼저 수행 — 환경 점검부터)

- 계약: [phase2.md](contracts/phase2.md). 미확정 U17~U37([§17](contracts/phase2.md#17-리스크미확정)) 확인이 목적이다. 1차 E0~E6이 끝난 PC(또는 2차 배포 스크립트로 새로 설치한 PC)에서 수행한다.
- 원본 반입 자원: `CONFIG/BATCHRUN`(런처 .py·TCL), `CONFIG/TEMPLATE/TEMAPLATE_simlab_parametered_mesh.tpl`, `CONFIG/DATA/DATA_doe_design_type.json`, `BUILD_PYD/*.pyd`, `H3D_StaticMinMax_to_CSV_FAST.tcl`을 서버 폴더에 두고 `config/platform.yaml`의 `resources.*`에 적는다(업로드본에 없던 파일 포함, U19).

### E2-0. 환경 점검·배포

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E2-0-1 | **전역 관리자로 "관리 > 환경 점검" → "점검 실행"**. 결과 표의 실패·경고를 모두 메모하고, 실패가 남아 있으면 아래 항목 전에 설정을 고친다(실행 파일 6개 존재, 자원 파일·pyd 각 1개, AI 루트 쓰기, DB head `0003_hpc_cancel_failed`(phase2 C18), 대시보드 인증, 워커 heartbeat, limiter `windows_job`, Job Object 적용, GPU 감지, PBS 모드) | | |
| E2-0-2 | 환경 점검 후 `<ai_root>\_platform\env_check_tmp\`에 남은 파일이 없음, `_platform\env_checks\<id>\report.json` 생성 | | |
| E2-0-3 | (배포) 준비 PC에서 `deploy\collect-offline` 실행 → 묶음 zip. 폐쇄망 PC에서 `deploy\install.bat` 실행: venv·wheel 설치, DB 역할·DB 생성(재실행 시 건너뜀), `alembic upgrade head`, 작업 스케줄러에 `PhysicsAI-Backend`·`PhysicsAI-Worker` 등록(실행 시간 제한 없음 확인), 재부팅 후 자동 기동, `/physicsai/api/health` 응답(U31) | CI 검증됨(러너 기준), 실제 PC에서 재확인 선택 | CI windows 잡: collect-offline 실제 실행, install.bat 무인 설치(-PasswordsFromEnv -NoStart, Interactive)·DB 생성·migration·작업 등록(PT0S·999·IgnoreNew)·health·해제. **재부팅 자동 기동·Background(세션 0)·실제 서비스 계정은 미검증 → 실제 PC에서 확인** |
| E2-0-4 | 작업 스케줄러 백그라운드(세션 0) 실행에서 SimLab·hw·hstbatch 배치가 정상 동작하는지(안 되면 `-RunMode Interactive`로 재등록 후 비교)(U31·U11) | | |
| E2-0-5 | 대시보드 Caddyfile에 `deploy\caddy\physicsai.caddy` 스니펫 반영 후 운영 주소 `/physicsai/` 접속·로그인 공유 | | |
| E2-0-6 | `deploy\update.bat` 실행: 실행 중 작업이 있으면 중단 안내, 기존 venv·frontend가 `_backup`으로 이동, 업데이트 후 health 정상 | | |
| E2-0-7 | (선택) 각 Altair 도구의 버전/도움말 인자를 확인해 `env_check.probes`에 넣고 재점검(U32) | | |
| E2-0-8 | (선택) 시연 모드 원클릭: `deploy\demo\start-demo.bat` → `http://127.0.0.1:8190/` 시연 로그인 → ①-1 실행 성공 → `stop-demo.bat`(관리자 매뉴얼 §14) | CI 검증됨(러너 기준), 실제 PC에서 재확인 선택 | CI windows 잡 "시연 모드 원클릭" |

### E2-1. ① 학습데이터 생성

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E2-1-1 | ①-1 CAD(.prt) 경로 → "파라미터 추출": SimLab 진행률이 오르고(`Passed` 표식, U20) 파라미터 표가 채워짐. `01_train\extract\<job>\parameter_extracted.xml` 형식 메모 | | |
| E2-1-2 | ①-2 표 편집(사용 체크·하한·상한) → "tpl 생성": `01_train\tpl\simlab_parametered_mesh.tpl`이 원본 앱으로 만든 tpl과 같은 구조인지(parameter 줄·paramitem 줄·`dir_file_prt`) 비교 | | |
| E2-1-3 | 사용 안 함 파라미터가 형상에서 CAD 공칭값으로 유지되는지(U37), `%3i` 정수 반영으로 실수 파라미터가 깨지지 않는지(U23) | | |
| E2-1-4 | ①-3 DOE 유형·run 수·동시 실행 → "입력 생성": hstbatch 진행(`Finished run (N), model (m_3)`), run 폴더 위치가 `approaches\*\run__*`인지, run마다 starter 1개·include가 같은 폴더에 있는지(U17), FullFact/FracFact의 실제 run 수(U22), `-multiexec` 2 이상에서 Job Object 한도 안 동작(U21) | | |
| E2-1-5 | 샘플 표 상태(PARSED/PARTIAL/MISSING)와 `samples.csv` 값이 HyperStudy의 실제 run 값과 같은지(U18). 다르면 HyperStudy 내보내기 파일 위치 메모 | | |
| E2-1-6 | ①-4 (PBS 설정 시) "PBS 제출": run마다 job 제출, 상태 표시, 일부 실패 시 나머지 회수·알림(U24). PBS `none`이면 버튼 비활성 + 안내 | | |
| E2-1-7 | ①-5 수동 해석 결과 폴더 지정 → "결과 가져오기": run 폴더 이름 매칭(U25), `01_train\results\<doe>\<run>\`에 h3d·T01 복사, 누락 run 표시 | | |
| E2-1-8 | ④ "① 결과로 만들기" → 파라미터 세트 등록, 학습 run 불러오기·최근접 run이 DOE 값과 일치 | | |

### E2-2. ② 데이터 정리

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E2-2-1 | 원천 = ① DOE 결과 → "h3d 미리보기": DataType·Component·Part·Time Step 목록이 원본 앱과 같음 | | |
| E2-2-2 | 성분·Part·time step 간격 선택 → "큐레이션 실행": `02_curated\<id>\CURATED_DATA\<run>\*.h3d` 생성, 크기가 줄었는지, HyperView에서 선택 성분만 있는지(U26) | | |
| E2-2-3 | ③-1 기본 입력이 큐레이션 결과로 채워지고 데이터셋 생성 성공 | | |
| E2-2-4 | T01 미리보기 → 곡선 선택 → "곡선 추출": `*_curves.json` 생성·형식 메모(U27), 화면 그래프 또는 JSON 트리 | | |

### E2-5. ⑤ 최적화

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E2-5-1 | ④ 예측 1회 후 ⑤ 응답 후보 콤보가 채워짐, 응답 표 작성(목적 1개 + 제약 1개) | | |
| E2-5-2 | "최적화 실행"(ARSM): `05_opt\<job>\INPUT_HST_RUN.json`이 원본 앱 생성본과 키·값이 같음, 진행 "run N / 25"(U29), 완료 | | |
| E2-5-3 | 결과 폴더 파일 목록 표시, 요약 파일 형식 메모 → 파서 설정 요청(U28). DOE approach도 1회 | | |

### E2-6. SPDM 가져오기·오류 묶음·알림

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E2-6-1 | SPDM Case/Scene 폴더 경로 → "가져오기": `02_import\<id>\`에 h3d·T01 복사, 공백·특수문자 이름 정리 목록(U30). **SPDM 폴더에 새 파일·변경 없음**(가져오기 전후 폴더 목록·수정 시각 비교) | | |
| E2-6-2 | 딥링크 `/physicsai/import?spdm_path=…` 열기 → 자동 실행 없이 Study 선택 화면(D8은 대시보드 쪽 구현 후) | | |
| E2-6-3 | 실패한 작업에서 "오류 묶음 받기"(본인·관리자만 보임) → zip 안 로그 꼬리·명령·설정 요약, DB 비밀번호·토큰 없음 | | |
| E2-6-4 | ①②⑤ 완료·실패 토스트, PBS 일부 실패 알림, 환경 점검 완료 알림, 대기열의 단계 배지·PBS run 집계 | | |

---

# 1차 항목

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
| E1-1 | 실행 중 edspy 프로세스와 그 자식(python 등)이 같은 Job에 속함(Process Explorer → Job 탭) | CI 검증됨(러너 기준), 실제 PC에서 재확인 선택 | V-JO-2(손자 프로세스 IsProcessInJob) |
| E1-2 | Job의 CPU rate 제한(hard cap)·메모리 한도 64 GB·우선순위 Below Normal 확인 | CI 검증됨(러너 기준), 실제 PC에서 재확인 선택 | V-JO-1(CPU rate hard cap·BELOW_NORMAL·JobMemoryLimit·KILL_ON_JOB_CLOSE 조회). 운영 값(64 GB 등)은 실제 PC에서 |
| E1-3 | 64코어 이상 PC라면 작업 관리자 CPU 사용률이 약 `32/전체 코어` 비율 이하로 유지 | CI 검증됨(러너 기준), 실제 PC에서 재확인 선택 | V-JO-1 실측: CPU rate 20% → 21~24%(러너) |
| E1-4 | GPU 사용량 제한 없음(nvidia-smi로 사용률 확인), 우측 패널 GPU 막대 표시 | | |
| E1-5 | 관리자 취소 → 2초 안팎에 프로세스 트리 전체 종료, 작업 `CANCELED`, 등록자에게 알림 | CI 검증됨(러너 기준), 실제 PC에서 재확인 선택 | V-JO-3(TerminateJobObject 트리 종료) |
| E1-6 | 실행 중 워커 창 강제 종료 → 자식 프로세스 모두 종료, 약 1분 후 작업 `INTERRUPTED`(WORKER_LOST) | CI 검증됨(러너 기준), 실제 PC에서 재확인 선택 | V-JO-3(워커 강제 종료 시 KILL_ON_JOB_CLOSE) |
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
