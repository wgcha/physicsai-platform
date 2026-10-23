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
| E2-0-3 | (배포) 준비 PC에서 `deploy\collect-offline` 실행 → 묶음 zip. 폐쇄망 PC에서 `deploy\install.bat` 실행(대시보드와 같은 실행 환경: Python 3.12.13·PostgreSQL 18 같은 인스턴스 — `deploy.json` `dashboard_root`로 대시보드 `.env`·`.tools`에서 `pg_bin`·`pg_host`·`pg_port`·`python_exe` 기본값, 출력에 대시보드 DB 사용자·비밀번호 없음): venv·wheel 설치, DB 역할·DB 생성(재실행 시 건너뜀), `alembic upgrade head`, 작업 스케줄러에 `PhysicsAI-Backend`·`PhysicsAI-Worker` 등록(실행 시간 제한 없음 확인), 재부팅 후 자동 기동, `/physicsai/api/health` 응답(U31) | CI 검증됨(러너 기준), 실제 PC에서 재확인 선택 | CI windows 잡: collect-offline 실제 실행, install.bat 무인 설치(-PasswordsFromEnv -NoStart, Interactive)·DB 생성·migration·작업 등록(PT0S·999·IgnoreNew)·health·해제. **재부팅 자동 기동·Background(세션 0)·실제 서비스 계정은 미검증 → 실제 PC에서 확인** |
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
| E0-8-1 | (3차 S19, phase3 §24) 평소 상태: 상단 자원 칩 툴팁 = `워커 자원 열기`, 서랍 GPU 막대 정상, 워커 로그에 GPU 조회 줄 없음 | | |
| E0-8-2 | `worker.gpu_query`를 없는 경로(`["C:/nope/nvidia-smi.exe"]`)로, `resources.gpu_query_candidates`를 `[]`로 임시 변경 → 칩 툴팁 `GPU 없음 — nvidia-smi를 찾지 못했습니다(…)`, 서랍에 같은 원인 회색 줄, 워커 로그에 전이 1줄. 연속 3회째에 "조회 간격을 늘립니다" 1줄이 나오고 툴팁의 `다음 조회` 시각이 점점 멀어짐(10·10·20·40·80… 최대 `gpu_backoff_max_s`). 원복하면 "GPU 조회 회복" 1줄, 툴팁이 평소로 돌아옴. **끝나면 두 설정을 반드시 원복** | | |
| E0-8-3 | 이전에 보던 "GPU 조회 실패"가 다시 나면 칩 툴팁 문구·연속 횟수와 워커 로그 시각을 기록한다. 응답이 15초를 넘겼는지(`응답 시간 초과(15초)`) 종료코드/실행 파일 문제인지 구분 → 시간 초과면 `worker.gpu_query_timeout_s`를 올려 재확인 | | |

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

### E4-0. 시연 전 — 예측 1회 성공까지 (phase3 §11)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E4-0-1 | 관리>환경 점검 통과: `altair.edspy_path`·`simlab_path`·`hw_exe_path`, `resources.preview_pred_h3d_tcl`·`hypermesh_include_tcl` 존재, `/status` `features.predict`·`predict_parametric` = true, 워커 online, Study에 Final 모델 지정 | | |
| E4-0-2 | (U3 1회 확인) 원본 앱이 만든 HyperStudy run 폴더(`…\run__00001\`)에서 `m_1\`에 렌더 `.py`·`EPS_mesh_0000.rad`, `m_2\`에 `104_replace_node_elem.inc`·`log_batch.txt`(끝 `COMPLETE HM BATCHRUN`). 조립 폴더에서 `findstr /i "#include" *_0000.rad` → include 이름, `RENUM_INIT.csv` 위치. 다르면 `predict.mesh_include_name`·`commands.mesh` 수정 후 워커 재시작 | | |
| E4-0-3 | (가장 빠른 확인) ④ 입력 방식 "준비된 입력 파일" → 학습에 쓴 조립 폴더(기준 starter) → "확인"에서 starter 1개 → "예측 실행": `04_predict\<job>\RESULT\<stem>_pred.h3d` 생성, 결과 목록 표시, `.xy` 있으면 커브. 원본 ⑤ "Predict + Preview" 결과와 HyperView에서 비교 | | |
| E4-0-4 | "파라미터로 형상 생성"에서 공칭값 실행: `geom\simlab_parametered_mesh.py`, `geom\EPS_mesh_0000.rad`, `geom\104_replace_node_elem.inc`, `geom\log_batch.txt`, `INPUT\`에 eps_mesh 없음·새 include. 경고 메모. 결과가 E4-0-3과 거의 같음 | | |
| E4-0-5 | 값을 바꿔 1회 더: `INPUT\104_replace_node_elem.inc`가 공칭과 다름(`fc /b`), 예측 최대값 달라짐. 단계별 소요 시간 메모 | | |
| E4-0-6 | (U9) ① run 렌더 `.py`의 `NewValue`와 HST 설계값(비정수) 비교 → `predict.integer_rounding` | | |
| E4-0-7 | 시연 직전: 대기열 비어 있음, 라이선스 응답, E4-0-4 성공 작업을 남겨 두어 실시간 실행이 늦으면 그 결과를 보여 줌 | | |

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

# 3차 항목 (S12~S19, 2026-10-20 문서 이관)

- 계약: [phase3.md](contracts/phase3.md) §17~§24. 아래는 S14~S19의 서버 확인 항목이다. S9~S13의 서버 확인(E4-9~E4-12-*)은 각 계약 원문([s12_s13.md](contracts/s12_s13.md) 등)에 있고 1차 E4-9·E4-10과 번호가 겹친다 — 위 표와 혼동하지 않도록 이 표에는 옮기지 않았다. GPU 조회(E0-8)는 위 E0 표에 있다.
- ④ 일괄 예측의 GPU 동시 예측(원 계약 S19 §24.4, 서버 확인 `E4-19-1~5`)은 **철회**되어 이 체크리스트에 항목이 없다. 그 블록의 ⑤ 성능 확인 1건만 E5A-6으로 남겼다.
- ID 규칙: 기존 E4·E5 번호는 유지하고 3차 신규는 계약 ID를 그대로 쓴다. 결과 칸 기록 방식은 위와 같다.

## E5A. ⑤ 결과분석 (S14 §19, S19 §24)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E5A-1 | 메뉴 ①~⑥ 순서·라벨(④ 예측 · ⑤ 결과분석 · ⑥ 최적화), ④ 예측·⑥ 최적화 기존 흐름 회귀, 작업 대기열·알림에서 최적화가 "⑥"으로 표시 | | |
| E5A-2 | 완료된 일괄 예측 배치를 ⑤에서 열어 설계공간 지도·변수–응답·커브 겹쳐보기가 ④에서 보던 것과 같은 값 | | |
| E5A-3 | 실제 해석 DOE(LHS, 응답 있음)를 ⑤에서 열어 결과 표 값이 ① samples/responses와 일치, 영향도(PRCC·SRC)가 표시되고 부호·순위가 상식과 맞음, 200 run 첫 로드 시간 기록 | | |
| E5A-4 | 같은 템플릿의 해석 DOE + 예측 배치를 겹쳐 보기(해석 대 예측), 파라미터 이름이 다른 쌍은 비활성 + 안내 | | |
| E5A-5 | 표본 방식별 영향도 등급: 비 LHS DOE는 비활성이 아니라 "정식/참고" 표시(S15), 응답 없는 DOE에서 안내 | | |
| E5A-6 | (S19) 기존 배치의 성능(`perf:`) 열 값이 이전과 같은지 확인. 템플릿 성능 정의(subcase 등)를 바꾼 뒤 그 배치를 ⑤에서 열면 해당 칸이 `—` + 회색 "정의 변경", 표 위 안내 줄. ⑥ 최적화 설정의 성능 표에서 "성능 다시 추출" 실행 후 값이 돌아옴 | | |

## E4-13. ④ 표본 방식 (S15 §20) · E1-8. ① 기본 유형

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E4-13-1 | ④ 최적화 LHS 20개(기본 선택 확인) → 생성·예측 완료 → ⑤ 영향도 정식 표시 | | |
| E4-13-2 | ④ Sobol 16개 → 같은 템플릿에서 이어서 추가 16개 → 두 배치 값이 겹치지 않고 미리보기 notes "합치면 32개". ⑤에서 두 배치 겹쳐 보기 | | |
| E4-13-3 | ④ Box–Behnken(변수 3) 13 run, 부분 요인 IV → ⑤ 영향도 "참고용" 문구 | | |
| E4-13-4 | 미리보기 응답 시간: 최적화 LHS 200개·Sobol 128개(서버 PC에서 첫 호출 포함 2초 안 목표), 서버 scipy 버전 = lock(1.17.1) | | |
| E1-8-1 | ① DOE 생성 화면 기본 = LatinHyperCube·설명문 표시(S18 이후에는 E1-9의 "플랫폼 생성"이 화면 기본), Sobol DOE를 ⑤에서 열면 영향도 정식 | | |
| E1-8-2 | (취소) HyperStudy 정의 파일 밖 유형 value 확인은 S18 결정(① 플랫폼 생성 채택)으로 취소 | 취소 | |

## E4-14. ④ 실행 목록·FEM 검증·영상 (S16 §21)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E4-14-H1 | 실행 목록에 과거 단일 예측(옛 작업 포함)이 나오고 일괄 하위는 없음. 행을 고르면 컨투어·커브·응답·입력값·경로가 보임 | | |
| E4-14-F1 | mesh_only 예측 → ① DOE 조립으로 FEM 검증: `04_verify\FV-001\a1\input`에 starter + 새 include, `EPS_mesh*` 없음, starter가 include를 참조(경고 없음) | | |
| E4-14-F2 | FEM h3d 결과 이름(예측 `CornerStress`에 해당하는 이름)·성분을 HyperView에서 확인 → 다르면 `fem_verify.field_map` | | |
| E4-14-F3 | 캡처 TCL이 /PART id로 부품을 격리하는지(이름이어야 하는지) — FEM 쪽 이미지. 안 되면 `auto_isolate_cushion=false` 또는 부품 이름 입력 | | |
| E4-14-F4 | 범례 min·max: FEM h3d에서 `__FV_LEGEND` subcase 1이 값을 내는지(`F/a1/result/RESPONSES.txt`), 아니면 `fem_verify.legend_subcase` | | |
| E4-14-F5 | FEM T01 커브 이름이 예측 curve.json 계열 이름과 맞는지(상세 커브 탭 unmatched 목록) | | |
| E4-14-F6 | SCX: 잡 폴더 `04_FV-001_<ts>`, 업로드 파일(rad·inc·csv), 회수 h3d·T01 | | |
| E4-14-F7 | custom 조립을 SPDM 경로로 지정: 원본 폴더 mtime·파일 수 불변, 스냅숏만 생김 | | |
| E4-14-F8 | 응답 MIN·MAX 비교값이 상식 범위(mesh_only이면 조립 전체 값인지 확인) | | |
| E4-14-V1 | 작업 로그에서 방향마다 `SUCCESS: 동영상 저장 완료` / `ERROR: 동영상 저장 실패` / `ERROR: 동영상 파일 없음` 중 무엇이 찍히는지, `capture_result.txt` VIEW 줄 video 값 | | |
| E4-14-V2 | `RESULT\media\iso.mp4`(또는 설정 확장자) 존재·크기 | | |
| E4-14-V3 | `ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt,width,height -of default=nw=1 iso.mp4` → h264·yuv420p인지 | | |
| E4-14-V4 | 설정값 `capture.video`·`video_ext`·`max_video_bytes`·`video_target_bytes` 확인(`/status`·platform.yaml) | | |
| E4-14-V5 | 브라우저: 네트워크 `/artifacts/<id>/media` 206·Content-Type, 콘솔 media error(code 4 = 형식 미지원) | | |
| E4-14-V6 | ffmpeg 가용성: `ffmpeg -hide_banner -encoders`에 libx264(없으면 `h264_mf`·`libopenh264`로 `capture.ffmpeg.args` 교체), 수동 변환 1회 크기 ≤ 1 MB 여부 | | |
| E4-14-V7 | `hwc save animation window` 대 `page` — 배치에서 어느 쪽이 파일을 만드는지 → `capture.video_scope` | | |

## E4-17. ⑥ 성능 정의·다목적 내장 최적화 (S17 §22)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E4-17-1 | ⑥ 내장 모드에서 쿠션 템플릿에 성능 2개 정의: H3D `CornerStress` MAX, 커브 `AccelPeak` ABSMAX. 저장 → ④ 단일 예측 1회 → 결과 표에 두 값이 나오고 커브 값이 HyperGraph 최대와 같은지 | | |
| E4-17-2 | 기존 완료 배치(정의 전 예측)를 재사용 → `PERF_MISSING_IN_BATCH` → `성능 다시 추출` → 값 채워짐. 하위 run 폴더 `_backup`에 옛 RESPONSES가 남는지 | | |
| E4-17-3 | 2목적(CornerStress 최소 · AccelPeak 최소) + 제약 1개(범위), 새 DOE 12 + 3×4 실행. 파레토 산점도·예측 전선·HV 그래프, 가중치 슬라이더 3가지(50/50·80/20·20/80)에서 추천 이동, 마무리 컨투어(기준안 대 추천점), 총 소요 기록 | | |
| E4-17-4 | 반복당 SO_FIT + SO_PROPOSE 시간 기록(목표 < 60 s). 3목적 1회(관찰 1개 포함)도 실행 | | |
| E4-17-5 | 파레토 표에서 예측 전선 점 2개 → `선택 해 예측 검증`(캡처 포함) → 결과가 표에 반영되고 컨투어가 받아지는지 | | |
| E4-17-6 | 검증 해 1개 → `FEM 검증`(S16 구성 시) → FEM 검증 작업이 생성되는지 | | |
| E4-17-7 | 진행 중 최적화가 쓰는 성능의 정의 변경 시도 → 409 문구("내장 최적화 SO-00n이 이 성능을 쓰고 있어 정의를 바꿀 수 없습니다") 확인 | | |

## E1-9. ① 학습 DOE 플랫폼 동시 생성 (S18 §23)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E1-9-1 | 플랫폼 생성, run 8·동시 4. 실행 중 아래 감시 명령으로 SimLab·HyperMesh 동시 수가 4 근처로 유지되는지 확인. 작업 상세 step 라벨 "실행 중 4 · …"와 `parallel.peak_processes` = 4 | | |
| E1-9-2 | 결과: DOE READY 8 run, ①-4 PBS/SCX 제출 2 run → 결과 회수 → ② 큐레이션 1 run 성공. ④ "① 학습 DOE 재사용" 미리보기 행 = 8 | | |
| E1-9-3 | 자원: 동시 4에서 라이선스 오류 없음(step 로그에서 `licens` 검색), 작업 회계 최대 메모리, 총 소요(같은 run 수의 hstbatch 기록이 있으면 비교). 오류가 나면 동시 수를 낮추고 `worker.max_memory_gb`·라이선스를 확인 | | |
| E1-9-4 | 취소: 생성 중 취소 → 30초 안에 감시 출력 0, 재시도 → 남은 run만 생성 | | |
| E1-9-5 | (선택, VOC 원인 기록용) 원본 HyperStudy(호환) 모드 run 8·multiexec 4를 같은 감시 명령으로 관찰해 실제 동시 수를 기록. 결과와 무관하게 동작은 바뀌지 않음 | | |

E1-9 감시 명령(PowerShell, 2초 간격, `Ctrl+C`로 종료):

```powershell
$log = "$env:TEMP\doe_conc.csv"; "time,simlab,hypermesh" | Out-File $log -Encoding utf8
while ($true) {
  $p  = Get-CimInstance Win32_Process | Where-Object { $_.Name -ne 'cmd.exe' -and $_.CommandLine }
  $sl = ($p | Where-Object { $_.CommandLine -match '-auto' -and $_.CommandLine -match 'simlab_parametered_mesh' }).Count
  $hm = ($p | Where-Object { $_.CommandLine -match 'BATCHRUN_create_include_node_elem' }).Count
  "{0},{1},{2}" -f (Get-Date -Format HH:mm:ss), $sl, $hm | Add-Content $log; Start-Sleep 2 }
```

# v0.2.4 항목 (MCP, 2026-10-21 — [mcp.md](contracts/mcp.md) §17·§21)

## E7. MCP 클라이언트 연결 (V-MCP-15·16·19·20 현장)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E7-1 | 묶음 설치·`update-repo` 후 서버 venv `physicsai-mcp --version`, `mcp.enabled: true`에서 `/status` `features.mcp`·`mcp_http` true, 끄면 `/physicsai/mcp` 404 | | |
| E7-2 | 웹 "내 API 토큰" 발급(read·run, 만료 입력 최대 30), 평문 1회 표시, 폐기 후 401 | | |
| E7-3 | 대시보드 Vite 경유(그리고 Caddy 설치면 Caddy 경유) HTTP `ping`·`whoami` 성공 | | |
| E7-4 | Claude Code: HTTP(`.mcp.json`)·stdio 각각 `ping` → `get_summary`(Study 1개) | | |
| E7-5 | Codex CLI: HTTP(`bearer_token_env_var`)·stdio 각각 `ping` → `list_studies` | | |
| E7-6 | Gemini CLI: HTTP(`httpUrl`+`headers`)·stdio(토큰 파일) 각각 `ping`, 도구 목록 로딩 시 스키마 거부 0 | | |
| E7-7 | run 토큰으로 `plan_job`(predict_batch 작은 run 수) → 사람 확인 → `run_job` → `job_status` → `cancel_job`, 관리자 `list_audit`에 행 | | |
| E7-8 | 사용자 PC stdio 설치(묶음 wheels, `--no-index`) 후 `physicsai-mcp --check` | | |

## E8. v0.2.7 예측 입력 종류(쿠션)·AI 연결(MCP) 페이지 (input-kind V-IK-10, mcp V-MCP-21~26 현장)

- [ ] ⑥ 내장 최적화를 같은 템플릿·모델로 "쿠션 입력"으로 1회 실행 — 서버 GPU 메모리 초과 없이 탐색·검증 배치 완료, 하위 예측 starter = `run__N/m_1/EPS_mesh_0000.rad`.
- [ ] Altair 조립 가능 템플릿 ④ 단건 쿠션 예측: MESH 생략·RAD_ASSEMBLE "쿠션 입력 복사", `EPS_mesh_0000_pred.h3d` 생성, 결과 `predict_input` 파일 1개.
- [ ] Native solid 템플릿 ④ 단건 쿠션 예측: `P/geom/EPS_mesh_0000.rad`(paicad `cushion write`)로 edspy 예측 성공(예측기 읽기 확인 — input-kind R1), `cushion.json` 경고 확인.
- [ ] 쿠션 결과의 FEM 검증 미리보기: 조립 원본 기본 "템플릿 조립 폴더", reuse 불가 문구.
- [ ] AI 연결(MCP) 페이지: 발급 전 자리표시자 → 발급 후 토큰 채움, 4개 탭 중 실제 쓰는 도구 1개 이상 복사 설정으로 연결해 `ping`, 연결 시험 버튼 정상, `mcp.public_url` 미설정 시 "짐작" 표시.

## E9. v0.2.10 결과 3D 컨투어 현장 보정 (contour3d-field V-C3F-17)

- [ ] 쿠션 입력 예측 h3d(약 97만 노드, 22프레임) 3D 생성: 결과 OK, manifest `limits.nodes`(외부 면 노드 실측)·`mesh.bytes`·`frames.record_bytes`·`disp` 유무 기록, 변위가 없으면 경고 `CONTOUR3D_DISP_UNAVAILABLE`와 배율 컨트롤 숨김 확인.
- [ ] FEM 결과 h3d(50프레임, `max_frames: 55`): 50프레임 전부(재샘플 없음), 변위 파일 생성, 배율 켬 시 변위 Range 시작·지연 기록.
- [ ] 추출·변환 소요 시간과 변환 피크 메모리(작업 로그·작업 관리자) 기록 — 목표 변환 ≤ 10분·≤ 1.5 GB.
- [ ] 사무용 PC 브라우저: 첫 표시(LOD) ≤ 2 s·전체 해상도 전환 ≤ 5 s·프레임 전환 ≤ 0.3 s(100 Mbps 기준) 실측, 회전 fps(LOD·전체), 극값 마커 값 = 범례 최대값.
- [ ] 조립 결과 h3d + 표시 부품 이름: `SCOPE=COMPS`(26.1 `hvSel Add "displayed"` 동작) 또는 `SCOPE=ALL` + 경고 확인. `hvResult GetDataTypeList` 출력 기록.
- [ ] 상한 초과 재현(`max_nodes`를 일시적으로 낮춤): 칸 사유 "외부 면 노드 N개 > 상한 M" 표시, 상한 복구 후 같은 결과가 자동 재생성(캐시 FAIL 미반환).
- [ ] `contour_extract.tcl` 단독 실행: 안내 문구 출력 후 종료. 결과 FAIL 캐시 폴더의 `extract/`에서 재실행 가능.
