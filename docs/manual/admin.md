# PhysicsAI 플랫폼 관리자 매뉴얼

- 대상: 플랫폼을 설치·운영하는 서버 관리자, 전역 관리자(대시보드 `is_global_admin`)
- 기준: 저장소 `claude/ops` 브랜치(2026-10-09), 패키지 버전 `0.1.0`, DB migration head `0003_hpc_cancel_failed`
- 근거 문서: 계약 [platform.md](../contracts/platform.md)(1차), [phase2.md](../contracts/phase2.md)(2차, 우선), [결정 기록](../decisions.md), [E2E 체크리스트](../e2e-checklist.md). 이 매뉴얼과 계약이 다르면 계약이 우선이고, 계약과 코드가 다르면 부록 C에 적었다.
- 사용자용 설명은 [사용자 매뉴얼](user.md)을 본다.
- native 형상 엔진 브랜치의 병행 설치·현장 검증·전환·롤백은 [native-rollout.md](native-rollout.md)를 본다.

> 배포 스크립트(`deploy/`)는 **실제 Windows에서 실행 검증되지 않았다**(phase2 §11). 첫 설치는 E2E 체크리스트 E2-0-3~E2-0-6을 함께 기록하면서 진행한다.

---

## 1. 구성 개요

### 1.1 구성 요소

| 구성 요소 | 실행 형태 | 역할 | 기본 위치·포트 |
|---|---|---|---|
| 프런트엔드 | 정적 파일(Vite build) | 화면. 기본 경로 `/physicsai/`. 백엔드가 직접 서빙(`server.frontend_root`, §2.6.1) 또는 Caddy(§2.6.2) | git 폴더 설치 `<git>\.runtime\frontend`, 묶음 `<install_root>\frontend\dist`(= `deploy.json`의 `caddy_frontend_root`) |
| 백엔드(API) | `python -m physicsai_api.serve`(uvicorn) | 입력 검증·권한·작업 생성·조회. **외부 프로그램을 실행하지 않는다** | `127.0.0.1:8100`, 접두 `/physicsai/api` |
| 워커 | `python -m physicsai_worker` | 대기열 claim, Altair·PBS 명령 실행(Job Object 안), HPC 폴링·회수, 환경 점검 워커 항목, 알림 정리 | PC당 1개(잠금 파일 `worker.state_dir/physicsai-worker.lock`) |
| DB | PostgreSQL(대시보드 DB와 **별도** DB `physicsai`) | 작업·상태·경로·수치 요약. 파일 본문은 저장하지 않음 | `127.0.0.1:5432` |
| 산출물 | 파일 시스템 | Study 폴더(AI 루트 아래), 환경 점검 보고서(`_platform`) | `storage.ai_root` |

```text
브라우저 ── http://<대시보드 주소>/physicsai/…   (같은 origin → 대시보드 세션 쿠키가 함께 전송)
   │
대시보드 Vite 서버(start.ps1) ─┬─ /physicsai, /physicsai/*  → PhysicsAI 백엔드 127.0.0.1:8100(경로 그대로, §2.6.1)
                               │     백엔드: /physicsai/api/* → API, 그 밖 → 프런트 정적 파일(server.frontend_root)
                               └─ 그 밖             → 대시보드(기존)
(대안) Caddy(대시보드 것) ─┬─ /physicsai/api/* → 백엔드, /physicsai/* → 프런트 정적 파일(§2.6.2)
                           └─ 그 밖            → 대시보드(기존)
PhysicsAI 백엔드 ── GET /api/auth/me, /api/projects ──▶ 대시보드 백엔드(루프백, 예 127.0.0.1:8000)
       │
PostgreSQL `physicsai`  ◀── claim/renew/release ──  physicsai_worker ── Job Object ── edspy·SimLab·hw·hvtrans·hstbatch·hstpy
                                                         └── qsub/qstat/qdel(PBS, 설정 시)
```

### 1.2 대시보드와의 관계

- **같은 Windows Server PC**에서 대시보드와 나란히 돈다. 대시보드 코드는 바꾸지 않는다. 대시보드 `.env`에 두 줄(`VITE_PHYSICSAI_TARGET`, `SIMDASH_PHYSICSAI_ENABLED`)만 넣는다(§2.6.1). Caddy를 쓰는 설치는 대신 Caddyfile에 PhysicsAI용 `handle` 블록 2개를 추가한다(§2.6.2).
- **로그인 공유**: 사용자는 대시보드에서 로그인한다. 같은 주소(origin)이므로 쿠키 `analysis_canvas_session`이 `/physicsai/` 요청에도 붙고, PhysicsAI 백엔드는 이 토큰으로 대시보드 `GET /api/auth/me`를 호출해 사용자·역할을 확인한다(결과 30초 캐시). 로그아웃은 대시보드에서 한다. 토큰 값은 로그·DB에 남기지 않는다.
- **프로젝트**: Study는 대시보드 프로젝트 1개에 속한다. 프로젝트 목록은 대시보드 `GET /api/projects`에서 가져온다.
- **권한**: 대시보드 역할을 그대로 쓴다(DB에 역할을 복제하지 않음).

| 동작 | 허용 |
|---|---|
| 조회(모든 화면·로그·산출물) | 로그인한 모든 ACTIVE 사용자(프로젝트 비멤버 포함) |
| 실행(Study 생성, 작업 등록, Final 지정, 파라미터 세트 등록 등) | 그 프로젝트 역할 `power`·`admin` |
| 대기열 관리(순서 변경·취소), 남의 작업 재시도, 관리 조회(`/admin/*`), 환경 점검 | **전역 관리자**(`is_global_admin`) |
| 오류 묶음 받기 | 작업 등록자 본인 또는 전역 관리자 |

- 대시보드가 내려가면 PhysicsAI 화면은 503 `DASHBOARD_UNREACHABLE`가 된다(인증을 확인할 수 없음).

### 1.3 경로 `/physicsai/`

- 백엔드 라우트 접두 `/physicsai/api`와 프런트 base `/physicsai/`는 **코드에 고정**이다. `server.base_path`는 예약(미사용) 키라 써도 경로가 바뀌지 않고 경고만 나온다(§4.4).
- 대시보드 Vite 프록시는 `/physicsai` 전체를 접두 그대로 백엔드로 넘기고, 백엔드가 `/physicsai/api/*`는 API로, 그 밖은 `server.frontend_root`의 정적 파일(없는 경로는 `index.html`)로 응답한다(§2.6.1). Caddy를 쓰면 `/physicsai/api/*`만 백엔드로 넘기고 프런트는 Caddy가 `uri strip_prefix /physicsai` 후 정적 파일을 준다(§2.6.2).

---

## 2. 설치

설치 방식은 둘이다. **대시보드와 같은 PC에 인터넷(사내 프록시 포함)이 되면 §2.0 git 폴더 설치를 쓴다**(권장). §2.2~§2.4의 오프라인 묶음 방식은 인터넷이 안 되는 **폐쇄망 서버용**이다. §2.1 준비물·§2.5~§2.8은 두 방식 공통이다.

### 2.0 같은 PC·git 폴더 설치(권장)

저장소를 받은 git 폴더에 그대로 설치한다(묶음·압축 없음). **일반 Windows PowerShell**(관리자 권한 불필요 — 대시보드와 같게)에서:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\VD_SIMULATION_WEB\physicsai-platform\deploy\setup.ps1       # 설치(다시 실행해도 안전)
powershell -NoProfile -ExecutionPolicy Bypass -File E:\VD_SIMULATION_WEB\physicsai-platform\deploy\update-repo.ps1 # 업데이트(§3.0, git pull 포함)
```

- **관리자 권한이 필요 없다**(phase3 D3-41): 머신 환경변수를 쓰지 않는다. DB 접속 정보(앱 비밀번호 포함 URL)는 `.runtime\secrets\database_url` 한 파일에 두고 상속을 끊어 **현재 사용자·SYSTEM만** 읽게 한다(`icacls` — 실패하면 경고만). 설정은 `.runtime\config\platform.yaml`. 작업 스케줄러 작업은 현재 사용자 `Interactive`·`Limited`로 등록하고, 백엔드·워커는 실행 인자 `--runtime <git>\.runtime`(파일 경로만 — 비밀값은 인자·로그에 없음)으로 두 파일을 찾는다.
- **Node·npm이 필요 없다**(phase3 D3-40): 저장소에 빌드된 화면 `frontend-dist\`가 들어 있고, `BUILD_INFO.json`의 `source_hash`가 현재 프런트 소스와 같으면 그대로 `.runtime\frontend`로 복사한다(esbuild `spawn EPERM` 같은 사내 보안 정책 문제와 무관). 해시가 다르거나 빌드본이 없을 때만 Node 22로 직접 빌드한다(Node도 없으면 "개발 쪽에 `scripts/build-frontend-dist` 실행·커밋 요청 또는 Node 22 설치" 안내).
- `.bat` 실행이 보안 정책으로 막혀도("액세스가 거부되었습니다") 위처럼 `.ps1`을 `-File`로 직접 실행하면 된다(이 프로세스에만 Bypass).
- 이전 설치(관리자 권한, 머신 환경변수 `PHYSICSAI_CONFIG`·`PHYSICSAI_DATABASE_URL`)는 값을 **읽어서** 런타임 파일로 옮긴다. 머신 환경변수는 지우지 않는다(지우려면 관리자 필요 — 화면에 한 줄 안내, 선택 사항). 옮긴 뒤에는 머신 환경변수가 있어도 런타임 파일이 우선이다.
- **묻는 것**(Enter = 괄호 안 기본값): 대시보드 폴더(`<git 폴더의 부모>\simdashboard`), AI 루트(`<git 폴더의 부모>\physicsai-data`), 원본 앱 폴더(Enter = 건너뜀 → `resources.*` 비움, 그 기능만 비활성), 확인 표 뒤 `Y/N`, 비밀번호 2개(PostgreSQL `postgres` 관리자·앱 역할 `physicsai_app` — 이미 설치돼 있고 접속되면 묻지 않음). `Background` 모드면 실행 계정 비밀번호를 한 번 더 묻는다.
- 인자로 줄 수도 있다: `-DashboardRoot`, `-AiRoot`, `-OriginalAppRoot`, `-AltairRoot`(Altair 설치 위치가 기본과 다를 때), `-PythonExe`, `-ServiceUser`(기본 현재 사용자), `-RunMode Interactive|Background`(기본 `Interactive`), `-NonInteractive`(묻지 않음·확인 표 생략 — 비밀번호는 `-PasswordsFromEnv`), `-NoStart`, `-Force`.
- **Python·Node**: 대시보드 고정 Python 3.12(`<대시보드>\.tools\python\cpython-3.12.*`)·Node 22(`<대시보드>\.tools\node-v22.*-win-x64`)를 먼저 쓴다. 후보를 실제로 실행해 확인하므로 PATH 첫 `python`이 망가진 pyenv shim이어도 건너뛴다(§2.2와 같은 규칙). 대시보드 Python에는 아무것도 설치하지 않는다.
- **PostgreSQL**: 대시보드 `.env`의 `POSTGRES_BIN`과 `DATABASE_URL`의 host·port만 읽는다(예 `127.0.0.1:5434`, 비밀번호·사용자명은 읽지 않음). 같은 인스턴스에 DB `physicsai`·역할 `physicsai_app`을 **없을 때만** 만든다.
- **Altair**: `-AltairRoot` → 레지스트리(설치 프로그램 목록의 Altair 설치 위치) → `$env:ProgramFiles\Altair\<버전>` 순으로 찾아 실행 파일 5개가 가장 많이(같으면 최신 버전) 있는 곳을 쓴다. 실행 파일의 상대 위치는 `config/platform.example.yaml`의 `altair.*`에서 읽는다. 못 찾으면 `altair.*`를 비워 두고 경고한다(Altair 기능만 비활성).
- **원본 앱 자원**: `deploy/RESOURCES.txt` 표의 상대경로(`CONFIG/BATCHRUN`, `BUILD_PYD`, `CONFIG/TEMPLATE/…`, `CONFIG/DATA/…`)로 원본 앱 폴더 하위를 확인하고, 없으면 같은 이름 파일을 깊이 4까지 찾는다. 못 찾은 키는 빈 값(그 기능만 비활성). `resources.preview_pred_h3d_tcl`은 `profile: prod`에서 필수라 비어 있으면 워커가 시작되지 않는다(확인 표에 경고).

| 단계 | 내용 |
|---|---|
| ① | Python 3.12 선택(관리자 권한 확인 없음) |
| ② | 런타임 폴더 `<git>\.runtime\`(git 제외 — `git pull`과 충돌 없음): `venv`, `frontend`(배치), `config\platform.yaml`, `secrets\database_url`, `deploy.json`, `logs`, `state`, `_backup` |
| ③ | `.runtime\venv`에 `deploy\requirements.lock` → `packages\simdash_adapters` → 플랫폼 패키지 **일반 설치**(editable 아님 — 업데이트 때 다시 설치). 사내 pip 설정(`pip.ini`·`PIP_INDEX_URL`)·프록시(`HTTPS_PROXY`)는 그대로 쓴다 |
| ④ | 설정 계획(`deploy\setup_config.py`): `deploy.json`·`platform.yaml`을 **새로 만들거나, 있으면 보존하고 빠진 키만 보충**(사용자가 고친 값은 덮어쓰지 않음, 비어 있는 자원·Altair 경로는 찾은 값으로 채움). 새 설정: `profile: prod`, `server.port: 8100`, `server.frontend_root`(= `.runtime\frontend` — 백엔드가 `/physicsai/` 직접 서빙. 키가 없을 때만 보충, 사용자가 바꾼 값·`null`은 유지), `storage.ai_root`(폴더 생성), `resources.*`, `altair.*`, `hpc.gateway: none`, `worker` 기본값(예시 값) |
| ⑤ | 확인 표(위치·Python·PostgreSQL·AI 루트·자원 n/10·Altair n/5·설정 처리) → `Y/N` |
| ⑥ | 이미 설치돼 있으면 대기열 확인(실행 중 작업이 있으면 중단, `-Force`) → 작업 중지 → venv 패키지 갱신. 바뀌는 기존 파일은 먼저 `.runtime\_backup\<UTC>\`로 복사. 프런트 배치: 저장소 빌드본 `frontend-dist`가 소스와 같으면 그대로 복사(Node·npm 없음), 다를 때만 Node 22로 빌드(`npm ci`는 `package-lock.json`이 바뀔 때만) → `.runtime\frontend`(이전 것은 `_backup`) |
| ⑦ | DB 역할·DB(없을 때만) → DB 접속 정보 파일 `.runtime\secrets\database_url`(현재 사용자·SYSTEM만 읽기) → `alembic upgrade head` → 작업 스케줄러 `PhysicsAI-Backend`·`PhysicsAI-Worker`(현재 사용자 `Interactive`·`Limited`, 인자 `--runtime <git>\.runtime`, 작업 폴더 `.runtime`, 설정은 §2.5) → 시작·health. 묶음 `install.ps1`과 같은 공용 함수(`deploy\install-common.ps1`) |
| ⑧ | 접속 연결 안내(§2.6.1): 대시보드 `.env`에 `VITE_PHYSICSAI_TARGET=http://127.0.0.1:<server.port>`·`SIMDASH_PHYSICSAI_ENABLED=true`(대시보드 재시작, 이미 있으면 "이미 들어 있음"), 접속 주소 `http://<대시보드 주소>/physicsai/`. Caddy를 쓰는 설치는 `deploy\caddy\physicsai.caddy`(§2.6.2) |

- **기존 묶음 설치 이어받기**: 머신 환경변수 `PHYSICSAI_CONFIG`나 작업 스케줄러가 다른 `install_root`를 가리키면 감지한다(읽기만). 그 `platform.yaml`을 `.runtime\config`로 **복사**해 이어받고(원본 그대로, 빠진 키만 보충), 같은 DB 연결(머신 환경변수 URL이 접속되면 비밀번호를 묻지 않음 — 값은 `.runtime\secrets\database_url`로)을 이어 쓰며, 기존 작업 정의를 `.runtime\_backup\<UTC>\tasks\*.xml`로 남긴 뒤 이 git 폴더의 venv로 다시 등록한다. 옛 설치 폴더는 지우지 않는다(확인 후 직접 정리, Caddy를 쓰면 `PHYSICSAI_FRONTEND_ROOT`도 새 위치로).
- 설정은 `.runtime\config\platform.yaml`에서 직접 고친다(§4). 다시 실행하거나 업데이트해도 덮어쓰지 않는다. 고친 뒤 `Stop-ScheduledTask`/`Start-ScheduledTask PhysicsAI-Worker`(백엔드도).
- 로그: `.runtime\logs\backend.log`·`worker.log`(작업 폴더 기준 `./logs`).
- Caddy가 없는 대시보드 구성(대시보드 `start.ps1`의 Vite 서버만 쓰는 경우)이 기본이다: 대시보드 Vite가 `/physicsai`를 백엔드로 넘기고 백엔드가 프런트를 서빙한다(§2.6.1). 같은 주소라 대시보드 로그인이 공유된다.

### 2.1 준비물

| 항목 | 내용 |
|---|---|
| OS | Windows Server(대시보드와 같은 PC), 일반 PowerShell(관리자 권한 불필요. `-RunMode Background` 작업 등록만 관리자 권한이 필요할 수 있음) |
| 실행 환경 | **대시보드와 동일**: Python **3.12.13**, PostgreSQL **18**, Node **22.23.2**(저장소 `.python-version`·`.node-version`, 대시보드와 같은 값) |
| Python | **3.12**(3.12.13 권장 — 대시보드 고정 런타임 `<대시보드>\.tools\python\cpython-3.12.13-windows-x86_64-none\python.exe`를 그대로 써도 된다). 경로는 `deploy.json`의 `python_exe` 또는 `dashboard_root`. 3.12가 아니면 설치 중단 |
| PostgreSQL | **18** — 대시보드가 쓰는 **같은 인스턴스에 별도 DB(`physicsai`)·역할(`physicsai_app`)**. `postgres` 관리자 비밀번호를 알고 있음(`pg_bin`에 `psql.exe`). 서버가 18이 아니면 설치는 계속하되 경고 |
| Node | **보통 필요 없음** — 저장소에 빌드본 `frontend-dist`가 들어 있다(§2.0). 빌드본이 소스와 다를 때만(개발 중 커밋 등) 22.23.2로 `npm ci && npm run build`. 대시보드 고정 Node(`<대시보드>\.tools\node-v22.23.2-win-x64`)를 후보로 쓴다 |
| Caddy | 대시보드가 쓰는 Caddy(설정 파일 수정 권한) |
| Altair 2026.1 | HyperStudy·SimLab·PhysicsAI(edspy)·HyperWorks(hw)·hvtrans 설치·라이선스 |
| 실행 계정 | `NT AUTHORITY\SYSTEM`이 아닌 지정 계정(예 `CORP\svc_physicsai`). AI 루트 읽기·쓰기, Altair 라이선스 접근 권한 |
| AI 루트 | 산출물 폴더(예 `E:/shared/AI_WORK`). **SPDM master 밖**, 경로에 공백·`& | < > ^ % ! "` 금지 |
| 원본 반입 자원 | 원본 앱 배포본의 런처·pyd·TCL·tpl 템플릿(§2.7, `deploy/RESOURCES.txt`) |
| 오프라인 묶음 | `physicsai-offline-<version>.zip`(§2.2) — 폐쇄망 서버용 묶음 방식만. git 폴더 설치(§2.0)는 git·인터넷(사내 프록시 가능)만 있으면 된다 |

### 2.2 오프라인 묶음 만들기(폐쇄망 서버용 — 인터넷 되는 준비 PC)

```powershell
# Windows 준비 PC(저장소 폴더에서). 대시보드가 같은 PC에 있으면 -DashboardRoot를 주는 것을 권장(대시보드 고정 Python 3.12·Node 22 사용)
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\collect-offline.ps1 -DashboardRoot E:\VD_SIMULATION_WEB\simdashboard -DryRun   # Python·Node 확인 + 실행할 명령만 출력
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\collect-offline.ps1 -DashboardRoot E:\VD_SIMULATION_WEB\simdashboard
# 대시보드가 없으면: -PythonExe <Python 3.12 python.exe 경로>(생략하면 py -3.12 → PATH의 python 순으로 자동 선택)
```

| 인자 | 기본 | 뜻 |
|---|---|---|
| `-DashboardRoot` | – | (선택) 대시보드 폴더. `.tools\python\cpython-3.12.*\python.exe`(고정 Python 3.12)와 `.tools\node-v22.*-win-x64\node.exe`(고정 Node 22)를 후보로 쓴다(`.env` 비밀번호는 읽지 않음, `dashboard-env.ps1`) |
| `-PythonExe` | 자동 선택 | Python 3.12 실행 파일(대시보드와 같은 3.12.13 권장) |
| `-DryRun` | – | Python·Node 선택만 확인하고 실행할 명령을 출력(빌드·내려받기 없음) |

- **Python 선택**(시연 `start-demo`와 같은 규칙, 공용 `deploy\python-select.ps1`): `-PythonExe` → `-DashboardRoot`의 고정 Python 3.12 → `py -3.12` → PATH의 `python`. 각 후보를 실제로 실행해 3.12인지 확인하고, 실행이 안 되거나(예: pyenv-win shim에 전역 버전 미설정 — "No global/local python version has been set yet", Microsoft Store 별칭) 버전이 다르면 다음 후보로 넘어간다. 고른 Python은 `[PhysicsAI 묶음] Python 선택: … → <경로>` 한 줄로 출력된다. 후보가 모두 실패하면 건너뛴 이유와 다음 행동을 출력하고 중단한다.
- **패키지 설치 위치**: `pip wheel`·`pip download`는 고른 Python으로 만든 **빌드용 임시 venv `dist\_buildvenv`**에서 실행한다. 대시보드 런타임·시스템 Python에는 아무것도 설치하지 않으며, 임시 venv는 끝나면 지우고 묶음(zip)에도 넣지 않는다(묶음 최상위는 `wheels`·`frontend`·`migrations`·`config`·`deploy`만).
- **프런트**: 저장소 빌드본 `frontend-dist`가 현재 소스와 같으면 그대로 묶는다(`[PhysicsAI 묶음] 프런트: 저장소 빌드본 frontend-dist 사용` — Node·npm 불필요, phase3 D3-40). 아래 Node 선택은 빌드본이 오래됐을 때만 한다.
- **Node**(빌드본이 오래됐을 때만, 프런트 빌드 `npm ci && npm run build`): `-DashboardRoot`의 고정 Node 22 → PATH의 `node` 순으로 `node --version`을 실행해 22.x인지 확인하고, 고른 Node를 `[PhysicsAI 묶음] Node 선택: …`로 출력한다(이 실행 동안만 PATH 맨 앞에 둠 — `npm`이 같은 Node를 쓰게). 없거나 22가 아니면 "Node 22를 찾지 못했습니다 … 다음 행동: Node 22.23.2를 PATH 맨 앞에 두거나 -DashboardRoot 지정"으로 중단한다. 22.23.2가 아닌 22.x면 안내만 하고 계속한다.
- **`.bat`·스크립트 실행 차단**: 이 스크립트에는 `.bat`이 없다. 위처럼 `powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\collect-offline.ps1 …`로 직접 실행한다(실행 정책으로 `.ps1`이 막혀도 이 형식은 이 프로세스에만 Bypass를 적용). `install.bat`·`update.bat`·`start-demo.bat`이 "액세스가 거부되었습니다"로 막힐 때도 같은 형식으로 `.ps1`을 직접 실행한다(인자 동일).
- 다시 실행해도 된다(`dist`의 폴더 안으로 내용을 덮어 복사, 빌드용 venv는 매번 새로 만듦).
- `install.ps1`·`update.ps1`도 `deploy.json`의 `python_exe`(또는 `dashboard_root`로 채운 값)를 같은 방식으로 실제 실행해 확인한다 — 망가진 pyenv shim·다른 버전이면 원인과 다음 행동(`python_exe`를 실제 `python.exe` 경로로 고치거나 비우고 `dashboard_root` 지정)을 출력하고, `update.ps1`은 기존 설치를 옮기기 **전에** 중단한다.

```bash
# Linux 준비 PC
bash deploy/collect-offline.sh --dry-run
bash deploy/collect-offline.sh
```

- 하는 일: (빌드용 임시 venv에서) 공통 어댑터 패키지 wheel(`packages/simdash_adapters` → `simdash_adapters-0.1.0-py3-none-any.whl`) → `deploy/requirements.local.lock`을 로컬 wheel만으로 확인(`pip download --no-index --find-links dist/wheels`) → `deploy/requirements.lock` 기준 win_amd64·Python 3.12(cp312) 외부 의존성 wheel 내려받기(PyPI) → 플랫폼 wheel → 프런트(`frontend-dist`가 최신이면 그대로, 아니면 `frontend`에서 `npm ci && npm run build`) → `dist/{wheels, frontend, migrations, config, deploy}`를 `physicsai-offline-<version>.zip`으로 묶음.
- 공통 어댑터 패키지 `simdash-adapters`(3차): HPC(PBS) 게이트웨이·회수 경로 해석을 떼어 낸 순수 Python 패키지(표준 라이브러리만, Windows·Linux 공용). **PyPI에 없고 PyPI에서 받지도 않는다** — lock은 두 개다: `deploy/requirements.lock` = PyPI에서 받는 외부 의존성만(어댑터 없음, 같은 이름의 외부 패키지가 섞여 들어오는 것을 막음), `deploy/requirements.local.lock` = `simdash-adapters==0.1.0`(저장소 소스로 만든 로컬 wheel로만 확인, `--no-index`). 플랫폼 wheel이 `simdash-adapters==0.1.0`을 정확 버전으로 요구하므로 설치(`install.ps1`·`update.ps1`)는 기존 명령(`pip install --no-index --find-links wheels physicsai-platform`) 그대로 함께 설치된다. 묶음 확인: `wheels\simdash_adapters-0.1.0-py3-none-any.whl`이 있어야 한다. 개발 PC에서는 루트 `pip install .` 대신 `scripts/dev-setup`을 쓴다(§2.9 — 패키지를 먼저 설치하지 않으면 의존성을 인덱스에서 찾는다).
- 버전 정책: SemVer(0.x 동안 공개 API 모양 변경 = minor, 동작 수정 = patch). 패키지 버전은 `packages/simdash_adapters/pyproject.toml`과 `__version__`이 같고, 올리면 `CHANGELOG.md`·루트 `pyproject.toml` 의존 고정·`deploy/requirements.local.lock`을 함께 고친다(시험이 대조).
- 원본 반입 자원(`resources.*`)은 묶지 않는다(라이선스·사내 배포물).

### 2.3 설치 매개변수 `deploy.json`(폐쇄망 서버용 묶음)

폐쇄망 PC에서 zip을 풀고 `deploy\deploy.example.json`을 같은 폴더에 `deploy.json`으로 복사해 고친다. **경로 문자열은 이 파일에만** 둔다.

| 키 | 의미 | 예시 |
|---|---|---|
| `install_root` | 설치 루트(venv·migrations·`_backup`) | `D:\physicsai` |
| `dashboard_root` | (선택) 대시보드 폴더. 설정하면 아래 4개 키가 **비어 있거나 없을 때만** 대시보드 값으로 채운다: `pg_bin` ← 대시보드 `.env`의 `POSTGRES_BIN`, `pg_host`·`pg_port` ← `.env`의 `DATABASE_URL`에서 **host·port만**(사용자명·비밀번호는 읽지도 로그에 남기지도 않음), `python_exe` ← `<dashboard_root>\.tools\python\cpython-3.12.*-windows-x86_64-none\python.exe`(대시보드 `setup.ps1` 고정 런타임). deploy.json의 명시 값이 항상 우선 | `E:\simulation_workbench` |
| `python_exe` | Python 3.12 실행 파일(`dashboard_root`가 있으면 생략 가능) | `D:\Python312\python.exe` |
| `pg_bin` | PostgreSQL 18 bin 폴더(`psql.exe`, `dashboard_root`가 있으면 생략 가능) | `E:\PostgreSQL\18\bin` |
| `pg_host` / `pg_port` | DB 주소(대시보드와 같은 인스턴스, `dashboard_root`가 있으면 생략 가능) | `127.0.0.1` / `5432` |
| `db_name` / `db_role` | 만들 DB·앱 역할 | `physicsai` / `physicsai_app` |
| `config_path` | 플랫폼 설정 파일 위치(작업 인자 `--config`가 됨) | `D:\physicsai\config\platform.yaml` |
| `service_user` | 작업 실행 계정 | `CORP\svc_physicsai` |
| `run_mode` | `Background`(로그온 무관, 세션 0) / `Interactive`(그 계정 로그온 세션) | `Background` |
| `caddy_frontend_root` | 프런트 정적 파일 배치 위치(Caddy `root`) | `D:\physicsai\frontend\dist` |

### 2.4 설치 실행(폐쇄망 서버용 묶음)

**권장 순서**: `config_path` 위치에 `platform.yaml`을 먼저 만들어 둔다(§4를 보고 `ai_root`·`altair.*`·`resources.*`·`profile: prod`를 채움). 설치 스크립트는 설정 파일이 없을 때만 예시를 복사하는데, 예시 값 그대로면 워커가 기동을 거부하고(종료코드 2) 작업 스케줄러가 1분마다 재시작을 반복한다.

```powershell
# 일반 PowerShell(관리자 권한 불필요), 풀어 둔 묶음의 deploy 폴더에서
.\install.bat                       # 또는 .\install.ps1 [-ConfigFile .\deploy.json] [-ServiceUser CORP\svc] [-RunMode Interactive]
```

| 단계 | 내용 | 확인 |
|---|---|---|
| ① | Python 3.12 확인(`dashboard_root`가 있으면 먼저 대시보드 기본값 채움 — 채운 키 이름만 출력). 관리자 권한 확인 없음 | 아니면 중단 |
| ② | `<install_root>\venv` 생성, `pip install --no-index --find-links wheels physicsai-platform`, migrations 복사 | |
| ③ | 프런트를 `caddy_frontend_root`로 복사 | |
| ④ | `config_path`가 없으면 `platform.example.yaml` 복사(있으면 그대로) | 복사됐다면 값을 고친 뒤 작업 재시작 |
| ⑤ | DB 역할·DB가 **없을 때만** 생성. 비밀번호 2개(postgres 관리자, 앱 역할)를 화면 입력(`Read-Host -AsSecureString`)으로 받아 `PGPASSWORD` 프로세스 환경으로만 전달 | 역할 생성 SQL은 표준 입력으로, 그 세션의 문장 로그를 끈 뒤 실행(비밀번호가 서버 로그에 남지 않게) |
| ⑥ | DB 접속 정보 파일 `<install_root>\secrets\database_url`(값은 출력하지 않음, 머신 환경변수 쓰지 않음) | 상속 해제 — 현재 사용자·SYSTEM(+실행 계정 읽기)만. 실패하면 경고 |
| ⑦ | `alembic upgrade head` | head = `0003_hpc_cancel_failed` |
| ⑧ | 작업 스케줄러 등록 `PhysicsAI-Backend`(`venv\Scripts\python.exe -m physicsai_api.serve --runtime <install_root> --config <config_path>`), `PhysicsAI-Worker`(`… -m physicsai_worker …`), 작업 폴더 `install_root` | §2.5 |
| ⑨ | 두 작업 시작 → `http://127.0.0.1:<server.port>/physicsai/api/health`(포트는 `platform.yaml`의 `server.port`에서 읽음) 60초까지 확인 | `{"status":"ok"}` |
| ⑩ | Caddy 스니펫 위치·환경변수 안내 출력(묶음 설치는 Caddy 기준. 대시보드 Vite 프록시로 쓰려면 `server.frontend_root`를 `caddy_frontend_root`로 설정) | §2.6 |

주의
- `install.bat`·`update.bat`·시연 `start-demo.bat`·`stop-demo.bat`은 `PSModulePath`를 비우고 Windows PowerShell 5.1을 부른다 — PowerShell 7 창에서 실행해도 5.1 기본 모듈로 동작한다. `.ps1`을 직접 실행할 때는 Windows PowerShell 5.1 창을 쓴다.
- **재설치 시 앱 역할 비밀번호**: 역할이 이미 있으면 비밀번호를 바꾸지 않는다. 그런데 ⑥의 DB URL은 이번에 입력한 값으로 만든다 → 기존 역할 비밀번호와 **같은 값**을 입력해야 한다.
- `Background` 모드는 실행 계정 비밀번호를 한 번 더 묻는다(작업 등록용). 부팅 시 작업이라 **이 모드만 관리자 권한이 필요할 수 있다**(거부되면 안내 — 기본 `Interactive`는 불필요).

### 2.5 작업 스케줄러(서비스 대신)

NSSM·pywin32를 쓰지 않고 작업 스케줄러로 상시 실행한다(phase2 가정 A-14).

| 설정 | 값 | 이유 |
|---|---|---|
| 트리거 | `Background`: 부팅 시(`AtStartup`) / `Interactive`: 실행 계정 로그온 시(`AtLogOn`) | |
| 실행 시간 제한 | **0(무제한)** | 기본 72시간이면 장시간 작업 중 워커가 종료됨 |
| 실패 시 재시작 | 1분 간격, 999회 | 워커·백엔드 비정상 종료 복구 |
| 여러 인스턴스 | `IgnoreNew` | 워커 단일 인스턴스 잠금과 이중 보호 |
| 권한 수준 | `Limited`(`Interactive`는 실행 계정 로그온 형식 `Interactive` — 관리자 권한 없이 등록·중지·시작) | |
| 실행 인자 | `-m physicsai_api.serve --runtime <런타임>`(`--config <설정>`은 설정이 `<런타임>\config\platform.yaml`이 아닐 때만) | 설정·DB 접속 정보 파일 위치만(비밀값 없음) |

- 수동 조작: `Start-ScheduledTask PhysicsAI-Worker`, `Stop-ScheduledTask PhysicsAI-Worker`(백엔드도 같음). 워커를 멈추면 Job Object `KILL_ON_JOB_CLOSE`로 실행 중인 Altair 프로세스 트리도 함께 끝나고, 그 작업은 약 1분(lease) 뒤 `INTERRUPTED`가 된다.
- **재시작**(설정 파일을 고친 뒤 등): 일반 PowerShell에서 `powershell -NoProfile -ExecutionPolicy Bypass -File <git 폴더>\deploy\restart.ps1`, 또는 `deploy\restart.bat` 더블클릭(같은 스크립트 호출). 워커 중지 → 백엔드 중지 → 백엔드 시작 → 워커 시작 후 두 작업의 State 표를 출력한다. `-Stop`(중지만)·`-Start`(시작만) 옵션. 병행 설치는 작업 이름 접두사를 따른다(`-TaskPrefix` > deploy.json `task_prefix` > `PhysicsAI`, deploy.json은 `-ConfigFile` > `deploy\deploy.json` > `<git 폴더>\.runtime\deploy.json` — `uninstall-tasks.ps1`과 같은 규칙). 실행 중 작업이 있으면 워커 중지로 약 1분 뒤 `INTERRUPTED`가 되므로 대기·실행 중 작업이 없을 때 쓴다.
- **세션 0 주의**: `Background`는 데스크톱이 없는 세션 0에서 돈다. HyperWorks·SimLab 배치(특히 `hw -b`로 그림을 만드는 TCL)가 세션 0에서 동작하는지는 미확인(U11·U31). 안 되면 `-RunMode Interactive`로 다시 등록하고 실행 계정을 자동 로그온해 둔다(§13 FAQ).

### 2.6 접속 연결

#### 2.6.1 대시보드 Vite 프록시 + 백엔드 정적 서빙(기본)

운영 대시보드(`start.ps1`)는 Caddy 없이 Vite 서버가 화면을 주고, `/physicsai` 아래 요청 전체를 PhysicsAI 백엔드로 **경로 그대로** 넘긴다. 백엔드는 `/physicsai/api/*`를 API로, 그 밖의 `/physicsai/…`를 프런트 빌드(`server.frontend_root`)로 응답한다.

1. `platform.yaml`의 `server.frontend_root`를 프런트 배치 폴더로 둔다. git 폴더 설치(§2.0)는 `setup.ps1`이 `<git>\.runtime\frontend`로 넣는다(이미 있는 값은 유지). 바꾸면 백엔드 재시작.
2. 대시보드 `<dashboard_root>\.env`에 두 줄을 넣고 대시보드를 다시 시작한다(포트는 `server.port`와 같게):

   ```dotenv
   VITE_PHYSICSAI_TARGET=http://127.0.0.1:8100
   SIMDASH_PHYSICSAI_ENABLED=true
   ```

3. 접속: `http://<대시보드 주소>/physicsai/`(대시보드에 로그인한 상태로). 이 PC 확인용 health: `http://127.0.0.1:8100/physicsai/api/health`.
   예: 대시보드가 `WINDOWS_WEB_PORT=8080`이면 PhysicsAI `http://<서버>:8080/physicsai/`, 대시보드 `http://<서버>:8080/home/`(`WINDOWS_WEB_BASE_PATH`, 기본 `/home/`).
   화면의 로그인·"대시보드로" 링크는 `auth.dashboard_public_login_url`(같은 origin 경로) — `setup.ps1`·`update-repo.ps1`이 대시보드 `.env`의 `WINDOWS_WEB_BASE_PATH`로 맞춘다(값이 `/`이거나 없을 때만, 직접 넣은 값은 유지).

- 서빙 규칙: `/physicsai` → 308 `/physicsai/`. 빌드 폴더 안의 파일은 그대로, 없는 경로는 `index.html`(화면 내부 경로 새로고침 대응). `index.html`은 `Cache-Control: no-cache`, 해시 이름 자산(`assets/`)은 1년 캐시. `..`·드라이브 경로·빌드 폴더 밖을 가리키는 링크는 404. `/physicsai/api/…`는 정적 처리로 가지 않는다(없는 API = JSON 404).
- 정적 파일은 인증 없이 준다(화면이 `/physicsai/api/me`로 로그인 여부를 판단). API 인증은 그대로다.
- 빌드 폴더나 `index.html`이 없어도 백엔드는 기동한다. 관리 > 환경 점검의 `프런트 정적 서빙`(`server.frontend_root`) 항목이 WARN으로 알리고, 화면 요청은 404 "프런트 빌드가 없습니다". 설정하지 않으면(`null`) 항목은 SKIP(외부 서빙).
- PhysicsAI 백엔드가 인증을 확인하는 대시보드 내부 주소 `auth.dashboard_internal_url`의 기본값 `http://127.0.0.1:8000`은 대시보드 `start.ps1`의 백엔드 기본 포트(`-BackendPort 8000`)와 같다. 대시보드를 다른 포트로 띄우면 이 값도 바꾼다.

#### 2.6.2 Caddy(대안)

대시보드 앞에 Caddy를 두는 설치는 `deploy\caddy\physicsai.caddy` 내용을 **대시보드 Caddyfile 사이트 블록 안, catch-all `handle` 앞**에 넣는다. 이때 `server.frontend_root`는 `null`로 두어도 된다(프런트는 Caddy가 서빙).

```caddyfile
redir /physicsai /physicsai/ 308

handle /physicsai/api/* {
	reverse_proxy 127.0.0.1:{$PHYSICSAI_PORT:8100}
}

handle /physicsai/* {
	root * {$PHYSICSAI_FRONTEND_ROOT}
	uri strip_prefix /physicsai
	try_files {path} /index.html
	file_server
}
```

- `{$…}`는 Caddy가 **설정을 읽을 때** 자기 프로세스 환경변수로 바꾼다. Caddy 실행 환경에 `PHYSICSAI_PORT`(= `server.port`), `PHYSICSAI_FRONTEND_ROOT`(= `caddy_frontend_root`)를 두거나 값을 직접 적는다. 바꾼 뒤 Caddy 설정을 다시 읽는다(`caddy reload` 등 대시보드 운영 방식대로).
- 대시보드의 `@api path /api /api/*`와 `/physicsai/api`는 겹치지 않는다.
- 확인: 운영 주소 `/physicsai/` 접속 → 대시보드 로그인 상태면 이름·역할이 보임(E2-0-5).

#### 2.6.3 공유 폴더 설정(다른 PC의 입력·결과, phase3 §12)

다른 PC는 서버 공유 `physicsai-inbox`(받은 파일 폴더 `<ai_root>\inbox`, 쓰기)에 입력을 복사하고 화면 "찾아보기"로 고른다. 결과는 `physicsai-data`(AI 루트, 읽기 전용)로 본다. 공유 생성은 **관리자 PowerShell로 1회**(설치 스크립트는 공유를 만들지 않고 조회만 해 `storage.inbox_share_hint`를 채운다 — 공유를 만든 뒤 `update-repo.ps1`을 한 번 실행):

```powershell
$ai = "E:\shared\AI_WORK"; $grp = "Everyone"   # 사내 그룹으로 바꾸려면 예: $grp = "CORP\PhysicsAI-Users"
New-Item -ItemType Directory -Force "$ai\inbox" | Out-Null
New-SmbShare -Name physicsai-data  -Path $ai         -ReadAccess   $grp
New-SmbShare -Name physicsai-inbox -Path "$ai\inbox" -ChangeAccess $grp
icacls $ai         /grant "${grp}:(OI)(CI)RX"   # NTFS 읽기·실행(하위 상속)
icacls "$ai\inbox" /grant "${grp}:(OI)(CI)M"    # NTFS 수정(하위 상속)
```

- 그룹 바꾸기: `$grp`만 도메인 그룹(`도메인\그룹`)으로 두고 실행한다. 이미 만든 공유는 `Grant-SmbShareAccess -Name physicsai-inbox -AccountName <그룹> -AccessRight Change -Force` + `Revoke-SmbShareAccess -Name physicsai-inbox -AccountName Everyone -Force`(data는 `-AccessRight Read`), NTFS는 `icacls <폴더> /remove Everyone` 후 위 `/grant`를 새 그룹으로.
- 확인: 다른 PC에서 `\\<서버>\physicsai-inbox`에 파일 복사 가능, `\\<서버>\physicsai-data`는 쓰기 거부. 화면 "찾아보기"의 받은 파일 안내에 공유 경로가 보이면 끝(`storage.inbox_share_hint`, 직접 적어도 된다).

### 2.7 원본 반입 자원 배치

원본 앱 배포본에서 아래 파일을 서버 폴더(예 `D:/physicsai/resources/`)로 복사하고 `platform.yaml`의 `resources.*`에 절대경로(`/` 권장, 공백·메타문자 금지)를 적는다. 값이 비어 있으면 **그 기능만 비활성**("관리자 설정 필요: <키>")이다.

| 설정 키 | 원본 파일 | 쓰는 기능 |
|---|---|---|
| `preview_pred_h3d_tcl` | `CONFIG/BATCHRUN/BATCHRUN_preview_pred_h3d.tcl` | ④ 컨투어 미리보기(**prod 필수**) |
| `batchrun_dir` | `CONFIG/BATCHRUN/`(런처 `BATCHRUN_*.py`) | ①-1, ①-3, ⑤ |
| `pyd_dir` | `BUILD_PYD/`(`<core>*.pyd`, 코어마다 **정확히 1개**) | ①-1, ①-3, ⑤ |
| `simlab_tpl_template` | `CONFIG/TEMPLATE/TEMAPLATE_simlab_parametered_mesh.tpl` | ①-2 tpl 생성 |
| `doe_design_type_json` | `CONFIG/DATA/DATA_doe_design_type.json` | ①-3 DOE 유형 |
| `hypermesh_include_tcl` | `CONFIG/BATCHRUN/BATCHRUN_create_include_node_elem.tcl` | ①-3, ⑤ |
| `preview_h3d_tcl` | `CONFIG/BATCHRUN/BATCHRUN_preview_h3d.tcl` | ②-1 |
| `preview_hg_tcl` | `CONFIG/BATCHRUN/BATCHRUN_preview_hg.tcl` | ②-3 |
| `curate_hg_tcl` | `CONFIG/BATCHRUN/BATCHRUN_curate_hg.tcl` | ②-4 |
| `extract_minmax_tcl` | `H3D_StaticMinMax_to_CSV_FAST.tcl` | ⑤ |

- 플랫폼은 pyd를 import하거나 런처를 직접 실행하지 않는다. 작업 폴더로 복사한 뒤 SimLab·hstbatch·hstpy가 실행한다.
- 배치 후 "관리 > 환경 점검"으로 확인한다(§10).

### 2.8 DB 수동 생성(설치 스크립트 없이)

```sql
-- postgres 관리자로. 비밀번호가 서버 로그에 남지 않게 이 세션의 문장 로그를 끈다(superuser 세션)
SET log_statement = 'none'; SET log_min_error_statement = 'panic'; SET log_min_duration_statement = -1;
CREATE ROLE "physicsai_app" LOGIN PASSWORD '<비밀번호>';
CREATE DATABASE "physicsai" OWNER "physicsai_app";
```

```powershell
$env:PHYSICSAI_DATABASE_URL = 'postgresql+psycopg://physicsai_app:<URL 인코딩 비밀번호>@127.0.0.1:5432/physicsai'
$env:PHYSICSAI_CONFIG = 'D:\physicsai\config\platform.yaml'
D:\physicsai\venv\Scripts\python.exe -m alembic -c D:\physicsai\migrations\alembic.ini upgrade head
```

- downgrade는 지원하지 않는다(데이터 보호, `RuntimeError`). 되돌리려면 DB 백업에서 복원한다(§3.3).

### 2.9 개발 실행(참고)

설치 없이 저장소에서 돌릴 때(계약 platform.md §4.6). `.ps1`/`.sh` 쌍. 스크립트는 `PYTHONPATH`에 `backend`·`worker`·`packages/simdash_adapters/src`를 넣는다.

| 스크립트 | 동작 |
|---|---|
| `scripts/dev-setup` | 의존성 설치: `pip install -e packages/simdash_adapters` → `pip install -r deploy/requirements.lock` + pytest(어댑터 패키지는 PyPI에 없어 저장소 소스로 먼저 설치, `requirements.lock`에는 없다 — `requirements.local.lock`) |
| `scripts/dev-db-init` | `PHYSICSAI_DATABASE_URL` DB에 `alembic upgrade head` |
| `scripts/dev-backend` | `python -m physicsai_api.serve`(설정 `server.host`·`port`) |
| `scripts/dev-worker` | `python -m physicsai_worker` |
| `scripts/dev-frontend` | Vite `127.0.0.1:5174/physicsai/`, `/physicsai/api` → `127.0.0.1:8100` 프록시 |
| `scripts/test-all` | 백엔드·워커·어댑터 패키지(`packages/simdash_adapters/tests`) pytest + 프런트 vitest + 타입 검사 |
| `scripts/check-adapters-wheel.sh` | 어댑터 wheel을 만들어 빈 venv에 wheel만(인덱스 없이) 설치·import 확인(CI linux) |

개발 로그인: 대시보드 dev(`127.0.0.1:5173`)에 먼저 로그인한다. 호스트 이름은 둘 다 `127.0.0.1`로 맞춘다(`localhost`와 섞지 않음). 대시보드 없이 하려면 `auth.mode: dev_static`(profile dev + 127.0.0.1 바인딩에서만 허용).

---

## 3. 업데이트·제거·백업

### 3.0 업데이트(git 폴더 설치 — §2.0)

**일반 Windows PowerShell**(관리자 권한 불필요)에서 **한 줄**(어느 폴더에서든, 옵션 입력 없음, 아무것도 묻지 않음 — 값은 `.runtime\deploy.json`, `git pull`도 스스로 한다):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\VD_SIMULATION_WEB\physicsai-platform\deploy\update-repo.ps1
```

끝 줄은 `업데이트 성공 — 접속: …` 또는 `업데이트 실패 — 접속: …`(`http://<서버>:<대시보드 .env WINDOWS_WEB_PORT, 기본 80>/physicsai/`). 대기열에 작업이 있으면 안내 후 중단한다(끝난 뒤 다시 실행, 기다리지 않으려면 `-Force`).

- **처음 한 번만**: 이전 버전을 관리자 PowerShell로 설치했다면 작업 스케줄러 작업이 관리자 소유라 일반 PowerShell에서 중지·다시 등록이 거부될 수 있다. 그러면 "처음 한 번만 관리자 PowerShell로 update-repo.ps1을 실행하세요"가 나오고 아무것도 바꾸지 않는다 — **지금과 같은 사용자 계정으로** '관리자 권한으로 실행'한 창에서(다른 계정은 `.runtime\secrets`를 읽지 못함) 한 번 같은 줄을 실행하면 작업이 새 방식(`--runtime`, 실행 계정 권한 포함)으로 다시 등록되고, 그 뒤로는 일반 PowerShell로 된다.

| 단계 | 내용 |
|---|---|
| ⓪ | `git pull --ff-only`(스스로). 추적 파일에 로컬 변경이 있으면 안내 후 중단(바꾼 것 없음). 분리된 HEAD(특정 커밋으로 되돌린 상태)·추적 브랜치 없음이면 pull 없이 현재 커밋으로. 새 커밋을 받으면 받은 새 `update-repo.ps1`로 이어서 실행. 이전 설치의 머신 환경변수 DB URL은 `.runtime\secrets\database_url`로 옮김(머신 환경변수는 그대로) |
| ① | 대기·실행 중 작업·진행 중 환경 점검 확인(DB 직접 조회). 있으면 안내 후 중단(`-Force`면 진행) |
| ② | 작업 2개 중지. 작업 인자가 새 방식(`--runtime`)이 아니면 현재 사용자 `Interactive`·`Limited`로 다시 등록(`Background`는 비밀번호가 필요해 안내만) |
| ③ | `.runtime\venv` 패키지 갱신(`requirements.lock` → `simdash_adapters` → 플랫폼, 로컬 패키지는 다시 설치). venv가 Python 3.12로 실행되지 않으면 `_backup`으로 옮기고 새로 만든다 |
| ④ | 설정 보충(기존 값 유지, 새 버전에서 생긴 관리 키만. 바뀌면 먼저 `_backup` 복사) |
| ⑤ | 프런트 배치: 저장소 빌드본 `frontend-dist`가 현재 소스와 같으면 그대로 복사(**Node·npm 단계 없음**). 다를 때만 Node 22로 빌드(`npm`은 창에서 직접 친 것과 같이 실행 — 실패하면 10초 뒤 한 번 더) → `.runtime\frontend`(이전 것은 `.runtime\_backup\<UTC>\frontend`) |
| ⑥ | `alembic upgrade head` |
| ⑦ | 시작·health → 성공 + 접속 주소 한 줄 |

- ⑥ 전에 실패하면(패키지·설정·프런트 빌드) 이전 프런트를 되돌리고 작업 2개를 다시 시작한다 — 이전 버전으로 계속 쓸 수 있다. ⑥ 이후 실패면 되돌리는 방법을 출력한다: `git checkout <이전 커밋>` 후 다시 실행(이전 프런트는 `_backup`). migration이 이미 올라갔으면 DB는 백업에서 복원(§3.3).
- 프런트 빌드가 `Error: spawn EPERM`(esbuild)으로 실패하던 문제: 보통은 빌드본(`frontend-dist`)을 복사하므로 서버에서 npm을 실행하지 않는다. 빌드본이 오래돼 직접 빌드할 때는 npm을 콘솔 그대로 실행한다. 그래도 실패하면 개발 쪽에 `scripts/build-frontend-dist` 실행·커밋을 요청한다.
- `.runtime\_backup`은 자동으로 지우지 않는다. 확인 후 관리자가 정리한다.
- 업데이트 전 DB 백업(§3.3)을 먼저 한다.

### 3.1 업데이트(폐쇄망 서버용 묶음)

```powershell
# 일반 PowerShell, 새 묶음의 deploy 폴더(기존 deploy.json을 복사해 둔다)
.\update.bat              # 또는 .\update.ps1 [-Force]
```

| 단계 | 내용 |
|---|---|
| ① | 이전 설치의 머신 환경변수 DB URL → `<install_root>\secrets\database_url`(없을 때만). 대기·실행 중 작업과 진행 중 환경 점검이 있는지 확인(묻지 않고 그 DB URL로 `psql` 직접 조회). 1건 이상이면 **중단**(`-Force`면 경고 후 진행 → 실행 중 작업은 `INTERRUPTED`) |
| ② | 작업 2개 중지(작업 인자가 `--runtime` 방식이 아니면 `Interactive`는 다시 등록) |
| ③ | 기존 `venv`·`migrations`·프런트를 `<install_root>\_backup\<UTC yyyyMMddTHHmmssZ>\`로 **이동**(삭제 없음) |
| ④ | 새 venv·wheel·migrations·프런트 배치 |
| ⑤ | `alembic upgrade head` |
| ⑥ | 시작·health 확인 |
| ⑦ | 실패하면 되돌리는 방법을 출력(자동 되돌림 없음) |

- `platform.yaml`과 `deploy.json`은 건드리지 않는다. 새 버전에 설정 키가 추가됐으면 새 `config/platform.example.yaml`과 비교해 직접 반영한다(알 수 없는 키·누락된 1차 확정 템플릿은 설정 오류).
- 되돌리기: 작업 중지 → 새 `venv`·`migrations`·프런트를 다른 이름으로 옮김 → `_backup\<UTC>`의 `venv`·`migrations`·`frontend_dist`를 원래 위치로 이동 → 작업 시작. migration이 이미 올라갔으면 DB는 백업에서 복원해야 한다.
- 업데이트 전 DB 백업(§3.3)을 먼저 한다.

### 3.2 제거

```powershell
.\uninstall-tasks.ps1     # 작업 스케줄러 등록 해제만(파일·DB·런타임 파일은 그대로)
```

완전 제거가 필요하면 관리자가 직접(되돌릴 수 없으니 백업 후):
1. 대시보드 `.env`에서 `VITE_PHYSICSAI_TARGET`·`SIMDASH_PHYSICSAI_ENABLED` 삭제 → 대시보드 재시작(Caddy를 쓰면 Caddyfile에서 PhysicsAI 스니펫 삭제 → Caddy 다시 읽기)
2. 런타임 폴더의 DB 접속 정보 파일(`.runtime\secrets\database_url` 또는 `<install_root>\secrets\database_url`) 삭제. 이전 버전이 남긴 머신 환경변수 `PHYSICSAI_CONFIG`, `PHYSICSAI_DATABASE_URL`이 있으면 관리자 PowerShell에서 삭제
3. DB `physicsai`·역할 `physicsai_app` 삭제(`pg_dump` 백업 후)
4. `install_root` 폴더 정리
5. **AI 루트의 Study 폴더는 사용자 산출물**이다. 플랫폼은 어떤 경우에도 지우지 않는다. 정리 여부는 사용자와 합의한다.

### 3.3 백업·복원

| 대상 | 방법 | 주기(권장) |
|---|---|---|
| DB `physicsai` | `pg_dump -Fc`(아래) | 매일 + 업데이트 직전 |
| AI 루트(`storage.ai_root`) | 사내 파일 백업(Study 폴더, `_platform`) | 사내 정책 |
| 설정 | `platform.yaml`, `deploy.json` 사본 | 변경 시 |
| 원본 반입 자원 | `resources.*` 폴더 사본 | 반입 시 |

```powershell
$pg = 'E:\PostgreSQL\18\bin'
$s = Read-Host -AsSecureString 'physicsai_app 비밀번호'
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
& "$pg\pg_dump.exe" -h 127.0.0.1 -U physicsai_app -Fc -f "D:\backup\physicsai_$(Get-Date -Format yyyyMMdd).dump" physicsai
$env:PGPASSWORD = $null
# 복원(작업 2개 중지 후): pg_restore -h 127.0.0.1 -U physicsai_app -d physicsai --clean --if-exists <파일>
```

- DB에는 경로·상태·수치만 있고 파일은 AI 루트에 있다. 복원할 때는 **DB와 AI 루트를 같은 시점**으로 맞춘다(한쪽만 복원하면 "파일 없음"·sha256 불일치 `INPUT_CHANGED`가 난다).
- 비밀번호는 명령 인자에 넣지 않는다(위처럼 프로세스 환경변수로만).
- 플랫폼은 덮어쓸 산출물을 `<study>/_backup/<UTC>_<job_id>/`로 옮기고 **자동 삭제하지 않는다**. 디스크가 차면 관리자가 사용자와 확인 후 정리한다(자동 용량 정리는 보류 결정, decisions 2026-10-09).

---

## 4. 설정 파일 레퍼런스

### 4.1 위치·우선순위·검증

- 파일: 설치본은 작업 인자 `--runtime <런타임>`의 `config\platform.yaml`(묶음은 `--config <config_path>`). 개발 실행은 환경변수 `PHYSICSAI_CONFIG`, 없으면 `config/platform.yaml`. 예시는 `config/platform.example.yaml`.
- 우선순위(`physicsai_core.config.runtime`): 프로세스에 직접 준 환경변수 > `--config` > 런타임 파일(`config\platform.yaml`, `secrets\database_url`) > 이전 설치의 머신 환경변수(런타임 파일이 없을 때만). 로그에는 출처(파일 경로)만 남고 값은 남지 않는다.
- 환경변수 우선: `PHYSICSAI_PROFILE` > `profile`, `PHYSICSAI_HPC_GATEWAY` > `hpc.gateway`. DB 비밀번호는 설정 파일에 넣지 않고 `database.url_env`가 가리키는 환경변수에서 읽는다.
- **알 수 없는 키는 오류**(오타 방지). 오류가 있으면 백엔드는 뜨지만 쓰기 API가 503 `CONFIG_INVALID`, 워커는 기동을 거부(종료코드 2)하거나 실행 중이면 새 작업 claim을 멈춘다. 오류 키는 `/status`와 환경 점검 `config.valid`에 나온다.
- **생략한 키는 아래 "코드 기본값"**이 된다. 명령 템플릿처럼 코드 기본값이 null인 키를 빼면 오류가 아니라 **그 기능만 비활성**이다(§4.4). 예시 파일 전체를 복사해서 고치는 방식을 권장한다.
- 기동은 막지 않는 안내(예약 키 사용, 키 누락으로 비활성된 기능)는 `/status`의 `config.warnings`에 키 이름으로 나온다.
- 경로: `/` 구분자 권장. `ai_root`·`allowed_import_roots`·`resources.*`·`collect_root_*`에는 공백·제어문자·`& | < > ^ % ! "` 금지. `storage.spdm_roots`와 겹치면(같거나 안팎) 오류.

### 4.2 반영 시점

백엔드는 **기동 시 1번** 설정을 읽는다. 워커는 claim 주기(기본 2초)마다 파일 sha256을 보고 바뀌었으면 다시 읽어 검증한다(통과 → 새 값 적용, 실패 → 새 claim 중지). 실행 중 step은 이전 값으로 끝까지 간다.

| 표기 | 뜻 |
|---|---|
| **B** | 백엔드 재시작 필요(`Stop/Start-ScheduledTask PhysicsAI-Backend`). 워커는 자동 재적용 |
| **W** | 워커만 쓰는 값. 자동 재적용(재시작 불필요) |
| **W↻** | 워커 재시작 필요 |
| **B+W↻** | 백엔드·워커 모두 재시작 |

헷갈리면 대기열이 빈 시간에 둘 다 재시작한다.

### 4.3 키 표

#### 최상위·server·database

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `schema_version` | 설정 스키마 버전(1만 허용) | `1` | `1` | B+W↻ |
| `profile` | `dev`\|`prod`. prod면 `altair.*`·`resources.*` 파일 존재 검사, `preview_pred_h3d_tcl` 필수, `worker.limiter: null`·`auth.mode: dev_static` 금지 | `dev` | `dev`(운영은 `prod`) | B+W↻ |
| `server.host` | 백엔드 바인딩 주소(대시보드 프록시·Caddy 뒤이므로 `127.0.0.1`) | `127.0.0.1` | `127.0.0.1` | B |
| `server.port` | 백엔드 포트. **포트의 유일한 출처**(설치·업데이트 스크립트의 health 확인도 이 값을 읽음). 대시보드 `.env`의 `VITE_PHYSICSAI_TARGET`(또는 Caddy `PHYSICSAI_PORT`)과 일치 | `8100` | `8100` | B |
| `server.frontend_root` | 백엔드가 `/physicsai/` 아래에 직접 서빙할 프런트 빌드 폴더(절대경로, §2.6.1). `null`·빈 값 = 서빙 안 함(Caddy 등). 폴더·`index.html`이 없으면 기동은 하고 환경 점검 WARN. 시연은 `demo.frontend_root`가 우선 | `null` | `null`(git 설치는 `<git>/.runtime/frontend`) | B |
| `server.base_path` | **예약(미사용)**. 경로는 `/physicsai` 고정. 값이 있으면 경고 `config.warnings`(지워도 됨) | `/physicsai` | (예시에서 제거됨) | – |
| `database.url_env` | DB URL을 담은 환경변수 이름 | `PHYSICSAI_DATABASE_URL` | 같음 | B+W↻ |
| `database.pool_size` | DB 연결 풀 크기 | `5` | `5` | B+W↻ |

#### auth

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `auth.mode` | `dashboard`(운영) \| `dev_static`(개발 전용) \| `demo`(시연 모드 전용, `demo.enabled: true`일 때만 — §14) | `dashboard` | `dashboard` | B |
| `auth.dashboard_internal_url` | 대시보드 백엔드 루프백 주소(`http(s)://호스트[:포트]`) | `http://127.0.0.1:8000` | 같음 | B |
| `auth.dashboard_public_login_url` | 로그인 안내·상단 "대시보드로" 링크(브라우저 기준 같은 origin 경로). 운영 대시보드 웹 경로 = 대시보드 `.env` `WINDOWS_WEB_BASE_PATH`(§2.6.1) | `/` | `/home/`(setup.ps1이 대시보드 `.env`에서) | B |
| `auth.cookie_name` | 대시보드 세션 쿠키 이름(대시보드와 같아야 함, D2) | `analysis_canvas_session` | 같음 | B |
| `auth.introspection_path` | 세션 확인 API | `/api/auth/me` | 같음 | B |
| `auth.projects_path` | 프로젝트 목록 API | `/api/projects` | 같음 | B |
| `auth.cache_ttl_s` | 세션 확인 캐시(초). 역할 변경이 반영되기까지 최대 이 시간 | `30` | `30` | B |
| `auth.timeout_s` | 대시보드 호출 타임아웃(초) | `3` | `3` | B |
| `auth.dev_static_principal.user_id` | dev_static 고정 사용자 id | `dev-admin` | 같음 | B |
| `auth.dev_static_principal.username` | 〃 이름 | `dev` | 같음 | B |
| `auth.dev_static_principal.display_name` | 〃 표시명 | `개발자` | 같음 | B |
| `auth.dev_static_principal.is_global_admin` | 〃 전역 관리자 여부 | `true` | `true` | B |
| `auth.dev_static_principal.memberships` | 〃 `[{project_id, role}]`(role `general`\|`power`\|`admin`) | `[]` | `[]` | B |

#### storage

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `storage.ai_root` | 산출물 유일 루트. 절대경로·존재·쓰기 가능·공백/메타 없음·SPDM과 비중첩 | `""`(오류) | `E:/shared/AI_WORK` | B |
| `storage.allowed_import_roots` | ③-4 모델 폴더·①-1 CAD·①-3 조립 폴더·①-5 결과 폴더를 추가로 읽을 수 있는 루트(읽기 전용) | `[]` | `[]`(예 `["F:/hpc_results"]`) | B |
| `storage.spdm_roots` | SPDM master 루트. 이 하위는 **쓰기 금지**, ②-0 가져오기만 읽기 허용. 비면 SPDM 가져오기 비활성 | `[]` | `[]` | B |
| `storage.inbox_dir` | 받은 파일 폴더(AI 루트 기준 상대, phase3 §12). 설치가 없으면 만든다. 절대경로·공백·`..`·`_backup`·`_platform` 불가 | `inbox` | `inbox` | B |
| `storage.inbox_share_hint` | 화면 "찾아보기" 안내용 공유 경로(표시만, ≤260자). 비면 설치가 SMB 공유 조회로 채움(§2.6.3) | `null` | `null` | B |

#### altair(실행 파일 — 경로는 여기서만)

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `altair.version_label` | 환경 스냅샷 표시용 버전 | `""` | `2026.1` | B |
| `altair.hyperstudy_path` | `{hstbatch}` — `hstbatch.exe` | `""` | `C:/Program Files/Altair/2026.1/hwdesktop/hst/bin/win64/hstbatch.exe` | B |
| `altair.simlab_path` | `{simlab}` — `SimLab.bat` | `""` | `…/SimLab/bin/win64/SimLab.bat` | B |
| `altair.edspy_path` | `{edspy}` — `edspy.bat` | `""` | `…/common/eds/win64/bin/win64/edspy.bat` | B |
| `altair.hw_exe_path` | `{hw}` — `hw.exe` | `""` | `…/hwdesktop/hw/bin/win64/hw.exe` | B |
| `altair.hvtrans_exe_path` | `{hvtrans}` — `hvtrans.exe` | `""` | `…/hwdesktop/io/result_readers/bin/win64/hvtrans.exe` | B |
| `altair.hstpy_path` | `{hstpy}`. 비면 `hyperstudy_path` 폴더의 `hstpy.bat` | `""` | `""` | B |
| `altair.altair_home` | ⑤ 실행 env `ALTAIR_HOME`. 비면 hstpy 폴더의 `../../..` | `""` | `""` | B |

빈 값은 오류가 아니다(그 실행 파일을 쓰는 step만 `EXECUTABLE_MISSING`). 값이 있으면 절대경로, prod면 파일이 있어야 한다. 실행 파일 경로에는 공백 허용(argv[0]만).

#### resources

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `resources.preview_pred_h3d_tcl` | ④ 컨투어 미리보기 TCL(prod 필수) | `""` | `D:/physicsai/resources/BATCHRUN/BATCHRUN_preview_pred_h3d.tcl` | B |
| `resources.batchrun_dir` | 런처 폴더 | `""` | `D:/physicsai/resources/BATCHRUN` | B |
| `resources.pyd_dir` | pyd 코어 폴더 | `""` | `D:/physicsai/resources/BUILD_PYD` | B |
| `resources.simlab_tpl_template` | ①-2 원본 tpl 템플릿 | `""` | `…/TEMPLATE/TEMAPLATE_simlab_parametered_mesh.tpl` | B |
| `resources.doe_design_type_json` | ①-3 DOE 유형 정의 | `""` | `…/DATA/DATA_doe_design_type.json` | B |
| `resources.hypermesh_include_tcl` | ①-3·⑤ include TCL | `""` | `…/BATCHRUN/BATCHRUN_create_include_node_elem.tcl` | B |
| `resources.preview_h3d_tcl` | ②-1 h3d 미리보기 TCL | `""` | `…/BATCHRUN/BATCHRUN_preview_h3d.tcl` | B |
| `resources.preview_hg_tcl` | ②-3 T01 미리보기 TCL | `""` | `…/BATCHRUN/BATCHRUN_preview_hg.tcl` | B |
| `resources.curate_hg_tcl` | ②-4 곡선 추출 TCL | `""` | `…/BATCHRUN/BATCHRUN_curate_hg.tcl` | B |
| `resources.extract_minmax_tcl` | ⑤ 응답 추출 TCL | `""` | `…/BATCHRUN/H3D_StaticMinMax_to_CSV_FAST.tcl` | B |
| `resources.launchers.extract_params.script` / `.core` | ①-1 런처 파일 이름 / pyd 코어 이름 | `BATCHRUN_get_parameter_from_cad.py` / `get_parameter_from_cad_core` | 같음 | B |
| `resources.launchers.gen_radioss.script` / `.core` | ①-3 〃 | `BATCHRUN_hst_gen_radioss_input.py` / `hst_gen_radioss_core` | 같음 | B |
| `resources.launchers.optimization.script` / `.core` | ⑤ 〃 | `BATCHRUN_hst_physicsai_optimization.py` / `hst_physicsai_optimization_core` | 같음 | B |

`script`는 파일 이름만(경로 구분자 없이 `.py`), `core`는 `^[A-Za-z_][A-Za-z0-9_]*$`. 런처 키는 위 3개만 허용.

#### worker(자원 제한·주기)

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `worker.limiter` | `auto`(Windows → `windows_job`, 그 외 `posix`) \| `windows_job` \| `posix` \| `null`(dev만) | `auto` | `auto` | W↻ |
| `worker.max_logical_cores` | CPU 상한 코어 수(1~1024) | `32` | `32` | B |
| `worker.max_memory_gb` | Job 메모리 상한 GB(1~4096) | `64` | `64` | B |
| `worker.priority` | `idle`\|`below_normal`\|`normal` | `below_normal` | `below_normal` | B |
| `worker.auto_detect` | true면 `min(설정값, 감지값 × ratio)` | `false` | `false` | B |
| `worker.auto_detect_ratio` | 자동 감지 비율(0.1~1.0) | `0.7` | `0.7` | B |
| `worker.posix_rlimit_as` | Linux 제한기에서 RLIMIT_AS 메모리 상한 적용 | `false` | `false` | W |
| `worker.heartbeat_interval_s` | 하트비트·lease 갱신 주기(초). 워커 온라인 판정 = 3배 이내 | `10` | `10` | B |
| `worker.lease_ttl_s` | 작업 lease 유효 시간(초, ≥ 3×heartbeat). 워커가 죽으면 이 시간 뒤 `INTERRUPTED` | `60` | `60` | W |
| `worker.claim_interval_s` | 대기열 확인 주기(초) | `2` | `2` | W |
| `worker.cancel_check_interval_s` | 취소 요청 확인 주기(초) | `2` | `2` | W |
| `worker.resource_sample_interval_s` | CPU·RAM·GPU 표본 주기(초) | `10` | `10` | W |
| `worker.env_passthrough` | Altair 자식 프로세스에 추가로 넘길 환경변수 이름 패턴(fnmatch). DB URL·`PHYSICSAI_*`·`*PASSWORD*`·`*SECRET*`·`*TOKEN*`·`PG*`는 항상 제외 | `[]` | `[]` | W |
| `worker.state_dir` | 단일 인스턴스 잠금 파일 폴더(상대경로면 작업 폴더 = `install_root` 기준) | `./state` | `./state` | W↻ |
| `worker.gpu_query` | GPU 조회 argv(`nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits` 형식). 첫 인자가 비었거나(null 포함) 못 찾으면 `resources.gpu_query_candidates`로 자동 탐색(phase3 D3-45) | `null` | `["nvidia-smi", …]` | W |
| `worker.gpu_query_timeout_s` | nvidia-smi 조회 제한 시간(초, 1~120). 요약 조회와 환경 점검 `gpu.detect`가 같은 값을 쓴다. 넘으면 `nvidia-smi 응답 시간 초과(N초)` (phase3 §24) | `15` | `15` | W |
| `worker.gpu_backoff_after` | 연속 조회 실패가 이 횟수부터 조회 간격을 두 배씩 늘린다(1~100) | `3` | `3` | W |
| `worker.gpu_backoff_max_s` | 늘린 조회 간격의 상한(초). `0` = 늘리지 않음. 0이 아니면 `resource_sample_interval_s` 이상~3600 | `300` | `300` | W |
| `resources.gpu_query_candidates` | GPU 조회 실행 파일 자동 탐색 후보(순서대로, 이름만 = PATH, `%VAR%` 확장) | `["nvidia-smi", "%SystemRoot%\\System32\\nvidia-smi.exe", "%ProgramFiles%\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe"]` | 같음 | W |

실행 시간 한도 키는 의도적으로 없다(오래 걸리면 관리자가 취소).

기본 전달 환경변수(허용목록): `SystemRoot`·`windir`·`ComSpec`·`PATH`·`PATHEXT`·`TEMP`·`TMP`·`USERPROFILE`·`HOME`·`APPDATA`·`LOCALAPPDATA`·`PROGRAMDATA`·`USERNAME`·`COMPUTERNAME`·`NUMBER_OF_PROCESSORS` 등 + `ALTAIR_*`·`*_LICENSE_*`·`*_LICENSE`·`EDS_*`·`CUDA_VISIBLE_DEVICES`(PBS 명령은 `PBS_*` 추가). 라이선스 변수 이름이 이 패턴에 안 맞으면 `env_passthrough`에 추가한다.

#### dataset·package·training_log·score·param_set(③④)

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `dataset.holdout_ratio` | 평가용 홀드아웃 비율 기본(0.05~0.5) | `0.1` | `0.1` | B |
| `dataset.seed` | 분할 seed 기본 | `20261008` | `20261008` | B |
| `dataset.split_group` | `file`(파일 단위) \| `parent_dir`(상위 폴더 = run 단위). run당 h3d가 여러 개면 `parent_dir` 권장(U12) | `file` | `file` | B |
| `dataset.min_h3d_files` | 최소 h3d 개수(≥2) | `2` | `2` | B |
| `dataset.min_psdata_bytes` | psdata 최소 크기(원본 검사 1 MiB) | `1048576` | `1048576` | W |
| `dataset.options_default.extract_faces` | 데이터셋 추출 옵션 기본 | `true` | `true` | B |
| `dataset.options_default.extract_mdi` | 〃 | `false` | `false` | B |
| `dataset.options_default.extract_time_history_vectors` | 〃 | `false` | `false` | B |
| `package.link_mode` | ③-2 `hardlink_or_copy`(같은 볼륨이면 하드링크) \| `copy`. HPC가 공유폴더로 하드링크를 못 읽으면 `copy`(U15) | `hardlink_or_copy` | 같음 | W |
| `training_log.log_globs` | ③-4 모델 폴더에서 학습 로그 후보 | `["*.log", "*.txt"]` | 같음 | B |
| `training_log.max_curve_points` | loss 곡선 저장 점 수 상한(≥3) | `2000` | `2000` | W |
| `training_log.parsers` | loss 파서 목록 `[{name, pattern}]`(§5.6) | 원본 `physicsai_default` 1개 | 같음 | W |
| `score.write_files` | true면 평가에 `--write-files`(`@write_files`) | `false` | `false` | W |
| `score.parsers` | 점수 파서 `[{name, pattern}]`(§5.6). 비면 "점수 형식 미확인"(U6) | `[]` | `[]` | W |
| `param_set.max_samples` | samples.csv 행 상한 | `20000` | `20000` | B |
| `param_set.max_total_bytes` | 파라미터 세트 폴더 총량 상한 | `2147483648`(2 GiB) | 같음 | B |

#### predict(④)

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `predict.rendered_script_name` | tpl 렌더 결과 파일 이름(`P/geom/` 아래). 파일 이름만 | `simlab_parametered_mesh.py` | 같음(U2) | W |
| `predict.mesh_output_glob` | SimLab이 `P/geom/` **직계**에 만든 메시 파일 패턴 → `P/INPUT/`로 복사 | `eps_mesh*` | 같음(U3) | W |
| `predict.starter_glob` | Radioss starter 패턴(조립 폴더·INPUT에서 정확히 1개) | `*_0000.rad` | 같음 | B |
| `predict.integer_rounding` | tpl 정수 형식(`%3i`) 반영 규칙 `half_up`\|`truncate`(U9) | `half_up` | `half_up` | B |
| `predict.env` | edspy 예측 추가 환경변수 | `{EDS_TNS_ACTVN_CHCKPT: "1"}` | 같음 | W |

#### commands(명령 템플릿 — §5 참고)

| 키 | step | 코드 기본값 | 예시 값(원본 인용) | 반영 |
|---|---|---|---|---|
| `commands.edspy_create_dataset` | ③-1 데이터셋 생성 | null(**1차 확정 → null이면 설정 오류**) | `["{edspy}", "--physicsai", "--create-dataset", "{out_psdata}", "--spec", "{spec_yaml}"]` | B |
| `commands.edspy_score` | ③-5 평가 | null(오류) | `["{edspy}", "--physicsai", "--score", "{score_path}", "--model", "{model_psmdl}", "--dataset", "{eval_psdata}", "@write_files"]` | B |
| `commands.geom_update` | ④ 형상 갱신 | null(→ 예측 작업 생성 409 `TEMPLATE_NOT_CONFIGURED`) | `["{simlab}", "-auto", "{rendered_script}", "-nographics"]`(U2) | B |
| `commands.mesh` | ④ 메싱 | null(→ SKIPPED) | `null`(U2) | B |
| `commands.rad_assemble` | ④ .rad 조립 후처리 | null(→ 복사 규칙만) | `null`(U3) | B |
| `commands.edspy_predict` | ④ 예측 | null(오류) | `["@cmd_c", "{edspy}", "--physicsai", "--predict-write", "{pred_h3d}", "--model", "{model_psmdl}", "--input-file", "{starter}", "@hooks_arg"]` | B |
| `commands.contour_preview` | ④ 컨투어 미리보기 | null(오류) | `["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{preview_tcl}", "-input", "{pred_h3d_fwd}", "-output", "{preview_json_fwd}"]` | B |
| `commands.response_extract` | ④ 응답 추출, ④ PBS 검증, ①-6 | null(→ SKIPPED, "추출 미구성") | `null`(U8·U35) | B |
| `commands.simlab_extract_params` | ①-1 | null(→ 기능 비활성) | `["{simlab}", "-auto", "{launcher}", "{cad_file}", "{xml_out}", "-nographics"]` | B |
| `commands.hst_gen_radioss` | ①-3 | null(비활성) | `["{hstbatch}", "-multiexec", "{multi_execution}", "-pyfile", "{launcher}"]` | B |
| `commands.h3d_preview` | ②-1 | null(비활성) | `["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{preview_tcl}", "-h3d", "{h3d}", "-result", "{result_json}"]` | B |
| `commands.hvtrans_curate` | ②-2 | null(비활성) | `["{hvtrans}", "-c", "{cfg}", "{h3d}", "{h3d}", "-o", "{out_h3d}", "-z0"]` | B |
| `commands.t01_preview` | ②-3 | null(비활성) | `["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{preview_tcl}", "-input", "{t01}", "-output", "{result_json}"]` | B |
| `commands.t01_curve_export` | ②-4 | null(비활성) | `["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{curate_tcl}", "-config", "{config_json}"]` | B |
| `commands.hst_optimization` | ⑤ | null(비활성) | `["@cmd_c", "{hstpy}", "{launcher}"]` | B |
| `commands_log_error_patterns` | **edspy step**(`edspy_create_dataset`·`edspy_score`·`edspy_predict`) 로그 오류 정규식(대소문자 무시, 줄 단위). 일치하면 종료코드 0이어도 `LOG_ERROR_DETECTED`(단 `edspy_predict`는 결과 h3d가 있으면 성공 + 경고 `LOG_ERROR_PATTERN`, phase3 D3-37). SimLab·hw step에는 적용하지 않음 | 원본 3개 | `'^\s*\d+\s+Error\s*:'`, `'Traceback \(most recent call last\):'`, `'^\s*\[ERROR\]'` | W |

#### hpc(PBS)

| 키 | 의미 | 코드 기본값 | 예시 값 | 반영 |
|---|---|---|---|---|
| `hpc.gateway` | `none`(PBS 기능 비활성) \| `command` \| `adapter`(자리만, 항상 미구성) \| `scx`(SCX — 대시보드 relay 경유, §16) | `none` | `none` | B |
| `hpc.poll_interval_s` | PBS 상태 조회 주기(초) | `60` | `60` | W |
| `hpc.lost_after_polls` | UNKNOWN 연속 이 횟수면 그 run `LOST`(실패) | `10` | `10` | W |
| `hpc.max_unreachable_minutes` | PBS 명령 연속 실패가 이 시간을 넘으면 작업 `HPC_UNREACHABLE` 실패 | `1440` | `1440` | W |
| `hpc.defaults.queue` / `.ncpus` / `.walltime` | 제출 기본값(화면 "고급"에서 바꿀 수 있음). 템플릿에 `{queue}`가 있는데 null이면 제출 실패 | `workq` / `16` / `24:00:00` | 같음 | B |
| `hpc.command.allowed_executables` | PBS 명령으로 허용할 실행 파일 절대경로 목록(`.bat`·`.cmd`·`.ps1` 금지) | `[]` | qsub/qstat/qdel `.exe` 3개 | B |
| `hpc.command.submit` / `.status` / `.cancel` | argv 템플릿(§5.5) | null(command 모드면 오류) | PBS Pro 형태 예시(U1) | B |
| `hpc.command.job_id_regex` | 제출 stdout에서 job id(그룹 `job_id`, 필수) | `^\s*(?P<job_id>\d+(?:\.[A-Za-z0-9_.\-]+)?)\s*$` | 같음 | B |
| `hpc.command.state_regex` | 상태 출력에서 상태 문자(그룹 `state`, 필수) | `job_state\s*=\s*(?P<state>[A-Z])` | 같음 | B |
| `hpc.command.exit_code_regex` | 종료코드(그룹 `exit`, 선택) | `Exit_status\s*=\s*(?P<exit>-?\d+)` | 같음 | B |
| `hpc.command.not_found_regex` | "job 없음" 판별(선택) | `Unknown Job Id` | 같음 | B |
| `hpc.command.state_map` | 원시 상태 → `QUEUED`\|`RUNNING`\|`FINISHED` | `{}`(전부 UNKNOWN!) | `{Q: QUEUED, H: QUEUED, W: QUEUED, T: QUEUED, S: QUEUED, B: RUNNING, R: RUNNING, E: RUNNING, F: FINISHED, X: FINISHED}` | B |
| `hpc.command.submit_timeout_s` / `status_timeout_s` / `cancel_timeout_s` | PBS 명령 타임아웃(초) | `60` / `30` / `30` | 같음 | W |
| `hpc.adapter.module` | **예약(미사용)**. 값이 있으면 경고 | `null` | (예시에서 제거됨) | – |
| `hpc.transfer.stage_in` | **예약(미사용)**(항상 공유 경로). 값이 있으면 경고 | `shared_path` | (예시에서 제거됨) | – |
| `hpc.transfer.path_map` | 이 PC 경로 → PBS 노드 경로 `[{local, remote}]`. 위에서부터 첫 일치(대소문자 무시, `/` 구분) | `[]` | `[{local: "E:/shared/AI_WORK", remote: "/shared/AI_WORK"}]` | W |
| `hpc.transfer.collect_mode` | `in_place`(결과를 Study 폴더에 직접) \| `shared_folder` \| `drive`(= shared_folder 별칭, U36) | `in_place` | `in_place` | B |
| `hpc.transfer.collect_root_local` | shared_folder/drive: 이 PC에서 읽는 결과 루트(읽기 전용, AI 루트·SPDM과 비중첩) | `""` | `""` | B |
| `hpc.transfer.collect_root_remote` | 같은 루트의 PBS 노드 경로 | `""` | `""` | B |
| `hpc.transfer.collect_patterns` | 회수할 파일 패턴 | `["*.h3d", "*T01", "*_0000.out", "*_0001.out"]` | 같음 | W |
| `hpc.transfer.max_collect_bytes` | 회수 파일당 상한 | `21474836480`(20 GiB) | 같음 | W |
| `hpc.scx.*` | SCX 잡 제출 설정(`gateway: scx`일 때만) — 키 표는 §16.3 | (§16.3) | 예시 파일 `hpc.scx` 절 | B |

#### train_data(① 학습데이터)

| 키 | 의미 | 코드 기본값(= 예시) | 반영 |
|---|---|---|---|
| `train_data.cad_extensions` | ①-1 허용 CAD 확장자 | `[".prt"]` | B |
| `train_data.max_xml_bytes` | 추출 XML 크기 상한 | `4194304` | W |
| `train_data.extract_progress_token` | SimLab 추출 로그의 진행 표식(U20) | `Passed` | W |
| `train_data.extract_progress_total` | 표식 총수 | `4` | W |
| `train_data.param_default_range_ratio` | 하한·상한 기본 = 공칭 × (1 ∓ ratio) | `0.05` | B |
| `train_data.param_default_format` | tpl `NewValue` 형식 기본(U23) | `%3i` | B |
| `train_data.tpl_marker` | 원본 tpl의 parameter 블록 끝 표식 | `#` + `*`×63 | B |
| `train_data.tpl_prt_regex` | `dir_file_prt = r"…"` 치환 정규식 | `dir_file_prt\s*=\s*r"[^"]*"` | B |
| `train_data.tpl_parameter_line_regex` | 기존 `{parameter(...)}` 줄 제거 | `(?m)^[^\n]*\{parameter\(.*?\)\}[^\n]*\n?` | B |
| `train_data.tpl_paramitem_line_regex` | 기존 `<paramitem …/>` 줄 제거 | `(?m)^[^\n]*<paramitem[^>]*/>[^\n]*\n?` | B |
| `train_data.max_runs` | DOE run 수 상한 | `2000` | B |
| `train_data.max_multi_execution` | 동시 실행 수 상한(1~64, U21). hstbatch(호환 모드)와 ① 플랫폼 생성 모두에 적용 | `8` | B |
| `train_data.hst_progress_regex` | ①-3 진행 줄(그룹 `run`) | `Finished run\s*\(\s*(?P<run>\d+)\s*\),\s*model\s*\(\s*m_?3\s*\)` | W |
| `train_data.hst_log_error_patterns` | ①-3 오류 정규식(⑤는 줄 수만 셈) | 원본 4개 | W |
| `train_data.run_dir_glob` | DOE 폴더 안 run 폴더 패턴(U17). 문자열 또는 목록. 옛 기본 문자열은 새 기본 목록으로 자동 정규화되고, 0건이면 `*/` 아래를 다시 찾는다(상위 `setup_*` 공칭 run 제외) | `["approaches/doe_*/run__*", "*/approaches/doe_*/run__*"]` | W |
| `train_data.samples_extractor` | DOE 샘플 값 추출기 `paramitem`\|`csv`\|`none`(U18) | `paramitem` | W |
| `train_data.rendered_tpl_glob` | paramitem: run 폴더에서 찾을 파일 패턴 | `**/*` | W |
| `train_data.rendered_tpl_exts` | 〃 확장자(빈 문자열 = 확장자 없음) | `[".py", ".tcl", ".txt", ".xml", ""]` | W |
| `train_data.samples_scan_max_bytes` | 〃 파일당 읽기 상한 | `1048576` | W |
| `train_data.paramitem_regex` | 〃 정규식(그룹 `name`·`value`) | `<paramitem\s+Name="(?P<name>[^"]+)"\s+NewValue="(?P<value>[^"]*)"` | W |
| `train_data.samples_csv_glob` | csv 추출기: DOE 폴더 안 CSV 패턴 | `null` | W |
| `train_data.samples_csv_run_column` | csv 추출기: run 열 이름 | `run_key` | W |
| `train_data.max_runs_per_submit` | ①-4 한 번에 제출할 run 상한 | `500` | B |
| `train_data.result_run_dir_regex` | ①-5 결과 폴더의 run 폴더 이름(그룹 `run_key`, U25) | `^(?P<run_key>run__\d+)$` | B |
| `train_data.result_match_depth` | ①-5 run 폴더 탐색 깊이 | `3` | B |
| `train_data.doe_generator_default` | ①-3 화면 기본 생성 방식 `platform`\|`hyperstudy`(phase3 §23). API는 `generator`를 생략하면 `sampling`이 있을 때 platform | `platform` | B |
| `train_data.platform_parallel_default` | ① 플랫폼 생성 동시 실행 수 화면 기본(실제 = min(값, `max_multi_execution`)) | `4` | B |
| `train_data.platform_max_runs` | ① 플랫폼 생성 표본 run 수 상한(≤ `max_runs`, 아니면 설정 오류) | `500` | B |
| `train_data.platform_run_root` | ① 플랫폼 생성 run 폴더 상위(상대, `..`·절대 금지). `<값>/run__00001`이 `run_dir_glob`과 맞아야 한다(아니면 설정 오류) | `approaches/doe_1` | B |

#### curation·spdm_import·optimize(②⑤)

| 키 | 의미 | 코드 기본값(= 예시) | 반영 |
|---|---|---|---|
| `curation.max_files` | ② 원천 파일 수 상한 | `20000` | B |
| `spdm_import.patterns` | ②-0 SPDM에서 가져올 파일 패턴 | `["*.h3d", "*T01"]` | B |
| `spdm_import.max_files` | 〃 개수 상한 | `20000` | B |
| `spdm_import.max_total_bytes` | 〃 총량 상한 | `536870912000`(500 GiB) | B |
| `optimize.default_study_folder` | ⑤ HyperStudy Study 폴더 이름 기본 | `HST_PHYSICSAI_OPTIMIZATION` | B |
| `optimize.env` | ⑤ 추가 환경변수 | `{EDS_TNS_ACTVN_CHCKPT: "1"}` | W |
| `optimize.progress_regex` | ⑤ 진행 줄(그룹 `run`, U29) | `Started\s+run\s+\(\s*(?P<run>\d+)\s*\),\s*model\s+\(\s*m_1\s*\)` | W |
| `optimize.max_listed_files` | 결과 파일 목록 상한 | `5000` | W |
| `optimize.viewable_globs` | 화면에서 열어볼 수 있게 등록할 파일 패턴 | `["*.csv", "*.txt", "*.json", "*.log"]` | W |
| `optimize.max_viewable_files` | 〃 개수 상한 | `200` | W |
| `optimize.summary_parsers` | 결과 요약 파서 `[{name, glob, kind: csv_table\|json_passthrough, max_rows?}]`(U28) | `[]` | W |

#### env_check·error_bundle·notifications·ui·logging

| 키 | 의미 | 코드 기본값(= 예시) | 반영 |
|---|---|---|---|
| `env_check.probe_timeout_s` | 환경 점검 프로브 1회 시간 상한(작업 시간 한도 아님) | `60` | W |
| `env_check.expire_s` | 점검 요청 만료(워커가 이 시간 안에 못 끝내면 EXPIRED) | `900` | B |
| `env_check.min_free_gb` | AI 루트 여유 공간 경고 기준 | `50` | W |
| `env_check.probes.edspy` … `.hstpy` | 도구별 짧은 실행 argv. argv[0]은 그 도구 placeholder(예 `["{edspy}", "--version"]`), 다른 placeholder 금지. null = 존재 확인만(U32) | 모두 `null` | W |
| `error_bundle.log_tail_bytes` | 오류 묶음 로그 파일당 꼬리(≥1024) | `262144` | B |
| `error_bundle.max_total_bytes` | 오류 묶음 압축 전 총량 상한 | `20971520` | B |
| `notifications.retention_days` | 알림 보관 일수 | `30` | B |
| `notifications.purge_interval_h` | 알림 정리 주기(시간) | `6` | W |
| `ui.max_artifact_bytes` | 화면 표시용 산출물 크기 상한 | `20971520` | B |
| `ui.poll_job_running_ms` / `poll_job_queued_ms` / `poll_job_waiting_hpc_ms` | 작업 상태 폴링(실행·대기·PBS 대기) | `2000` / `5000` / `15000` | B |
| `ui.poll_log_ms` / `poll_queue_ms` / `poll_resources_ms` / `poll_notifications_ms` / `poll_status_ms` | 로그·대기열·자원·알림·상태 폴링 | `2000` / `5000` / `10000` / `10000` / `30000` | B |
| `logging.level` | 백엔드·워커 로그 수준(`DEBUG`\|`INFO`\|`WARNING`\|`ERROR`\|`CRITICAL`) | `INFO` | B+W↻ |
| `logging.dir` | 운영 파일 로그 폴더(`backend.log`·`worker.log`). 빈 값 = 작업 폴더의 `./logs` = 설치본 `<install_root>\logs`. AI 루트·SPDM 밖에 둔다 | `""` | B+W↻ |
| `logging.max_mb` | 로그 파일 하나의 최대 크기(MB). 넘으면 회전 | `20` | B+W↻ |
| `logging.backups` | 회전 보관 개수(`backend.log.1` … `.10`). 가장 오래된 것부터 덮어씀 | `10` | B+W↻ |
| `logging.mask_patterns` | 외부 프로그램 출력 저장 전 마스킹 정규식. 그룹이 있으면 `<그룹1>=***`, 없으면 일치 전체를 `***` | `(?i)(password\|passwd\|token\|secret)\s*[=:]\s*\S+` | B |

#### demo(시연 모드 — §14)

| 키 | 의미 | 코드 기본값(= 예시) | 반영 |
|---|---|---|---|
| `demo.enabled` | 시연 모드(가짜 도구 배포판). **운영에서는 false 유지**. true는 `profile: dev` + `server.host: 127.0.0.1`에서만 허용 | `false` | B+W↻ |
| `demo.frontend_root` | 시연 때 백엔드가 직접 서빙할 프런트 빌드 폴더(Caddy 없이, `index.html` 필요). `enabled: false`면 빈 값 | `""` | B |

### 4.4 부분 설정·예약 키

| 경우 | 동작 | 확인 위치 |
|---|---|---|
| `commands.<키>`가 파일에 **없음**(예시 일부만 복사) | 설정 오류가 아님. 그 명령을 쓰는 기능만 비활성 → 카드 "관리자 설정 필요: commands.<키>", 작업 생성 409 `TEMPLATE_NOT_CONFIGURED`. 1차 확정 템플릿이 빠지면 경고도 남는다 | `/status`의 `features`(`dataset_create`·`evaluate`·`predict` 포함)·`config.warnings` |
| 1차 확정 템플릿(`edspy_create_dataset`·`edspy_score`·`edspy_predict`·`contour_preview`)에 **명시적 `null`** | 설정 오류(`CONFIG_INVALID`) | `config.valid` |
| `hpc.gateway: command`인데 `hpc.command` 블록이 없음 | 오류 아님. PBS 미구성(①-4·④ PBS 검증 비활성) + 경고 | `config.warnings`, `features.train_solve` |
| `worker.gpu_query`가 없음 | nvidia-smi 자동 탐색(못 찾으면 화면에 "GPU 정보 없음 — nvidia-smi를 찾지 못했습니다") + 경고 | `config.warnings` |
| 예약 키 `server.base_path`·`hpc.transfer.stage_in`·`hpc.adapter.module` | 값이 적용되지 않음 + 경고 "예약(미사용) 키입니다 — 지워도 됩니다". 예전 설정 파일 호환용으로만 스키마에 남아 있다 | `config.warnings` |
| 그 밖의 알 수 없는 키·형식 오류 | 설정 오류 | `config.valid` |

---

## 5. 명령 템플릿 교체 가이드

원본 코드로 확인되지 않은 명령(④ 형상·메싱·.rad 조립·응답 추출, PBS)은 **사내에서 실제 명령을 확인한 뒤 `platform.yaml`의 템플릿만 바꾼다**. 코드를 고칠 필요가 없다.

### 5.1 작업 순서

1. Altair PC에서 실제 명령을 손으로 실행해 인자·출력 파일 이름·로그 형식을 확인한다(E2E 체크리스트의 해당 U 항목에 메모).
2. `platform.yaml`의 템플릿을 고친다(아래 규칙).
3. 백엔드 재시작(작업 생성 시 템플릿 null·형식 검사는 백엔드가 함). 워커는 자동 재적용.
4. "관리 > 환경 점검" → `config.valid`가 정상인지 확인. 오류면 메시지에 키와 이유가 나온다.
5. 해당 작업을 한 번 실행하고, 실패하면 **오류 묶음**(§11)의 `steps/*.command.json`에서 실제로 펼쳐진 argv·cwd를 확인한다(전역 관리자는 `GET /physicsai/api/jobs/{id}?include=commands`로도 확인).

### 5.2 템플릿 규칙(Altair 계열, `commands.*`)

- **문자열 배열**이다. 명령 문자열 하나(`"edspy --x"`)는 오류. 셸을 거치지 않는다(`shell=False`).
- **argv[0]** = 실행 파일 placeholder `{edspy}` `{simlab}` `{hw}` `{hstbatch}` `{hvtrans}` `{hstpy}` 중 하나. 단 `@cmd_c`를 맨 앞에 두면 그 다음 요소가 실행 파일 placeholder. 실행 파일 placeholder는 argv[0] 자리에만 쓸 수 있다.
- **placeholder** `{name}`는 요소 전체 또는 일부(`"-Dfile={cad_file}"`)에 쓸 수 있다. 이름은 소문자 `[a-z_][a-z0-9_]*`, 서식·변환(`{x:>5}`, `{x!r}`) 금지. 리터럴 중괄호는 `{{`·`}}`.
- 키마다 **허용 placeholder가 정해져 있다**(아래 표, 코드 `physicsai_core/commands.py` `TEMPLATE_SPECS`). 표 밖 이름은 설정 오류.
- **펼침 토큰**(요소 전체가 정확히 이 문자열일 때):

| 토큰 | 펼침 | 허용 키 |
|---|---|---|
| `@cmd_c` | Windows: `%SystemRoot%\System32\cmd.exe /c`, 그 외: 없음. **맨 앞에만** | `edspy_predict`, `hst_optimization` |
| `@write_files` | `score.write_files: true`면 `--write-files` | `edspy_score` |
| `@hooks_arg` | 항상 없음(hooks 미지원, U13) | `edspy_predict` |

- Windows에서 argv[0] 실행 파일 경로는 `\` 구분자로 바뀐다(hvtrans는 `/` 경로면 리더를 못 찾음).

### 5.3 키별 placeholder·작업 폴더·성공 판정

`P` = `<study>/04_predict/<job_id>/`, `S` = `<study>/04_params/<param_set_id>/`, `D` = 데이터셋/DOE 폴더, `E` = 평가 폴더. 경로 표기 "fwd" = `/` 구분, "OS" = Windows `\` 구분, 표기 없음 = 내부 경로 그대로.

| 키 | 허용 placeholder(값) | cwd | 성공 판정·다음 step 기대 |
|---|---|---|---|
| `edspy_create_dataset` | `{edspy}`, `{out_psdata}`(=`D/train\|eval/dataset.psdata`), `{spec_yaml}`(=같은 폴더 `dataset.yaml`) | `D/train`, `D/eval` | 종료 0 + 파일 ≥ `dataset.min_psdata_bytes` + 오류 정규식 없음 |
| `edspy_score` | `{edspy}`, `{score_path}`(=`E/<모델명>.psscr`), `{model_psmdl}`, `{model_pscfg}`(경로만, 플랫폼은 열지 않음 — U7), `{eval_psdata}` + `@write_files` | `E` | 종료 0 + psscr 존재. 점수는 step 로그에 `score.parsers` 적용 |
| `geom_update` | `{simlab}`, `{rendered_script}`(=`P/geom/<predict.rendered_script_name>`), `{cad_file}`(=`P/geom/<CAD>`), `{work_dir}`(=`P/geom`) | `P/geom` | 종료 0 + 오류 정규식 없음. 다음 RAD_ASSEMBLE이 **`P/geom` 직계**에서 `predict.mesh_output_glob` 파일을 찾음(없으면 경고 `MESH_OUTPUT_MISSING`) |
| `mesh` | `geom_update`와 같음 | `P/geom` | 종료 0. null이면 SKIPPED(형상+메싱을 geom_update 한 번에 한다고 가정) |
| `rad_assemble` | `{hw}`, `{work_dir}`(=`P`), `{starter}`(=`P/INPUT/<starter>`), `{input_dir}`(=`P/INPUT`) | `P/INPUT` | 복사 규칙(조립 폴더의 `eps_mesh*` 아닌 `.rad`·`.inc` + 새 메시) 후 실행. starter 정확히 1개 |
| `edspy_predict` | `{edspy}`, `{pred_h3d}`(=`P/RESULT/<starter stem>_pred.h3d`), `{model_psmdl}`, `{model_pscfg}`, `{starter}` + `@cmd_c`, `@hooks_arg` | `P/INPUT` | env `predict.env` 추가. `pred_h3d` 존재·크기>0(원본처럼 종료코드·로그 오류는 경고 — phase3 D3-37) |
| `contour_preview` | `{hw}`, `{preview_tcl}`(=`resources.preview_pred_h3d_tcl`), `{pred_h3d_fwd}`(fwd), `{preview_json_fwd}`(=`P/H3D_PREVIEW.json`, fwd) | `P` | 종료 0 + `H3D_PREVIEW.json` 존재. `P` 직계에 새 `*.png`·`*.jpg`가 생기면 이미지로 표시(U4) |
| `response_extract` | `{hw}`, `{pred_h3d}`, `{pred_h3d_fwd}`, `{responses_json}`(=`S/responses.json` 또는 `D/responses.json`), `{out_csv}`(=`P/responses_pred.csv`, ①-6은 `R(run)/responses_run.csv`), `{work_dir}` | `P` | 종료 0 + `out_csv` 존재(형식 `name,value` 헤더). **argv[0]은 `{hw}`만 가능** |
| `simlab_extract_params` | `{simlab}`, `{launcher}`(OS), `{cad_file}`(OS), `{xml_out}`(OS, `parameter_extracted.xml`) | `01_train/extract/<job>` | 종료 0 + XML 존재. 오류 정규식 미적용 |
| `hst_gen_radioss` | `{hstbatch}`, `{multi_execution}`, `{launcher}`(fwd) | `01_train/doe/<doe>` | 종료 0 + `train_data.hst_log_error_patterns` 없음 + run 폴더 ≥1(`run_dir_glob`) |
| `h3d_preview` | `{hw}`, `{preview_tcl}`(fwd), `{h3d}`(fwd), `{result_json}`(fwd, `PREVIEW_H3D.json`) | `02_preview/<job>` | 종료 0 + JSON 존재 |
| `hvtrans_curate` | `{hvtrans}`, `{cfg}`(OS), `{h3d}`(OS), `{out_h3d}`(OS) | `02_curated/<id>/work` | 파일마다 순차 실행, 파일별 종료 0 + 출력 존재. 일부 실패 = 경고 `PARTIAL_OUTPUT` |
| `t01_preview` | `{hw}`, `{preview_tcl}`(fwd), `{t01}`(fwd), `{result_json}`(fwd, `PREVIEW_T01.json`) | `02_preview/<job>` | 종료 0 + JSON 존재 |
| `t01_curve_export` | `{hw}`, `{curate_tcl}`(fwd), `{config_json}`(fwd, `INPUT_CURATE_CURVE.json`) | `02_curated/<id>/work` | 종료 0, 출력 1개 이상 |
| `hst_optimization` | `{hstpy}`, `{launcher}`(OS) + `@cmd_c` | `05_opt/<job>` | env `optimize.env` + `ALTAIR_HOME`. 종료 0만(오류 줄은 세기만, 가정 A-8) |

null일 때: 1차 확정 4개(`edspy_create_dataset`, `edspy_score`, `edspy_predict`, `contour_preview`)는 **설정 오류**, `geom_update`는 예측 작업 생성이 409 `TEMPLATE_NOT_CONFIGURED`, `mesh`·`rad_assemble`·`response_extract`는 step 건너뜀, 2차 키는 그 카드만 "관리자 설정 필요".

### 5.4 치환 값 허용 문자

실행 직전에 placeholder에 들어갈 **값**을 검사한다(위반 → step 실패 `INPUT_INVALID`). 템플릿에 직접 쓴 리터럴 요소는 이 검사를 받지 않는다.

| 규칙 | 적용 |
|---|---|
| 빈 값, 제어문자(`\x00-\x1f`, `\x7f`) | 거부 |
| cmd 메타문자 `& \| < > ^ % ! "` | 거부 |
| 공백 | 거부(실행 파일 경로 argv[0]만 허용) |
| `; , = ( )` | 실행 파일이 `.bat`·`.cmd`(SimLab.bat, edspy.bat, hstpy.bat 등)이거나 템플릿에 `@cmd_c`가 있으면 추가로 거부 |

그래서 `ai_root`·`resources.*`·Study 폴더 이름·사용자 입력 경로에 공백·메타문자를 금지한다. `.bat`은 cmd가 인자를 다시 해석하므로(BatBadBut) **리터럴 요소에도 `& | < > ^ % ! " ; , = ( )`를 넣지 않는다**(검사 대상은 아니지만 cmd가 해석해 버림).

### 5.5 PBS 템플릿(`hpc.command.*`)

```yaml
hpc:
  gateway: command
  command:
    allowed_executables: ["C:/Program Files/PBS/exec/bin/qsub.exe", "C:/Program Files/PBS/exec/bin/qstat.exe", "C:/Program Files/PBS/exec/bin/qdel.exe"]
    submit: ["C:/Program Files/PBS/exec/bin/qsub.exe", "-N", "{job_name}", "-q", "{queue}",
             "-l", "select=1:ncpus={ncpus}", "-l", "walltime={walltime}",
             "-v", "INPUT_FILE={input_file},RESULT_DIR={result_dir}", "/shared/scripts/radioss_run.pbs"]
    status: ["C:/Program Files/PBS/exec/bin/qstat.exe", "-x", "-f", "{external_job_id}"]
    cancel: ["C:/Program Files/PBS/exec/bin/qdel.exe", "{external_job_id}"]
```

(위는 PBS Pro 형태의 **자리 예시**다. 사내 명령·스크립트 경로는 U1·U24 확인 후 교체.)

- `submit`·`status`·`cancel`은 문자열 배열(필수). argv[0]은 **절대경로**이고 `allowed_executables`에 있어야 한다(대소문자·구분자 무시 비교). `.bat`·`.cmd`·`.ps1` 금지 → 배치 래퍼가 필요하면 `.exe`를 직접 부른다.
- 허용 placeholder: `{job_name} {run_key} {study} {input_file} {input_dir} {result_dir} {queue} {ncpus} {walltime} {external_job_id}`. 그 밖은 설정 오류(`{{`·`}}` 리터럴 가능).

| placeholder | 값 | 허용 형식 |
|---|---|---|
| `{job_name}` | ④ `<study>_<job8>_a<n>`, ①-4 `<study>_<doe8>_<run_key>_a<n>` | `^[A-Za-z0-9_\-]{1,64}$` |
| `{run_key}`, `{study}` | run 이름(④는 `verify`), Study 폴더 이름 | 같음 |
| `{input_file}`, `{input_dir}`, `{result_dir}` | `path_map` 적용 후 노드 경로(`/` 구분) | `^[A-Za-z0-9_./:\\\-]+$`(공백·콤마 불가) |
| `{queue}` | 화면 "고급" 값 또는 `hpc.defaults.queue` | `^[A-Za-z0-9_.\-@]{1,64}$` |
| `{ncpus}` | 〃 `defaults.ncpus` | 1~4096 |
| `{walltime}` | 〃 `defaults.walltime` | `^\d{1,4}:\d{2}:\d{2}$` |
| `{external_job_id}` | 제출 때 얻은 job id | `job_id_regex`에 다시 일치해야 함 |

- 실행: 워커 hpc 스레드에서 `shell=False`, 제한기 밖, 타임아웃 `*_timeout_s`. 환경변수는 허용목록 + `PBS_*`.
- 결과 판정 흐름: 제출 종료코드 ≠ 0 → `HPC_SUBMIT_FAILED`. 상태 조회 출력(stdout+stderr)에 `not_found_regex` 일치 → "job 없음"(이미 QUEUED/RUNNING을 봤으면 완료로 간주, 처음부터면 UNKNOWN). `state_regex` → `state_map` → `QUEUED|RUNNING|FINISHED`(표에 없으면 UNKNOWN). `FINISHED` + `exit` 0(종료코드 정규식이 없으면 회수 패턴 충족) → 성공, 아니면 실패. UNKNOWN이 `lost_after_polls`회 연속 → `LOST`.

### 5.6 정규식 작성법

Python `re` 문법이다. YAML에서는 **작은따옴표**로 감싼다(역슬래시를 그대로 두기 위해). 작은따옴표 자체는 `''`로 쓴다.

| 설정 | 필수 그룹 | 적용 대상·방식 |
|---|---|---|
| `hpc.command.job_id_regex` | `job_id` | 제출 stdout 전체에 `search`(MULTILINE — `^`·`$`가 줄 단위) |
| `hpc.command.state_regex` | `state` | 상태 stdout+stderr에 `search`(MULTILINE) |
| `hpc.command.exit_code_regex` | `exit`(선택 키) | 같은 출력. **숫자가 아닌 값을 잡으면 그 조회는 UNKNOWN** |
| `hpc.command.not_found_regex` | 없음(선택 키) | 같은 출력, 먼저 검사 |
| `training_log.parsers[].pattern` | `epoch`, `loss`(+선택 `total`) | 학습 로그 **줄마다** `search`. 위에서부터 1줄 이상 일치한 첫 파서 채택. 대소문자 구분 |
| `score.parsers[].pattern` | `value`(+선택 `name`) | 평가 step 로그 줄마다. `name` 그룹이 없으면 파서 `name`이 지표 이름 |
| `commands_log_error_patterns[]` | 없음 | edspy step 로그 줄마다, **대소문자 무시** |
| `train_data.hst_log_error_patterns[]` | 없음 | ①-3(⑤는 줄 수만 셈), 대소문자 무시 |
| `train_data.hst_progress_regex`, `optimize.progress_regex` | `run` | 줄마다 |
| `train_data.paramitem_regex` | `name`, `value` | run 폴더 파일 줄마다 |
| `train_data.result_run_dir_regex` | `run_key` | 폴더 이름 전체에(그룹 부분만 대소문자 무시로 DOE run_key와 대응) |
| `logging.mask_patterns[]` | 없음(그룹 1개면 `<그룹>=***`로 바꿈) | 외부 프로그램 출력 저장 전 |

예시

```yaml
# 학습 로그 "Epoch 12/300 - train_loss: 1.23e-02" 형식 추가(기본 파서는 그대로 두고 아래에 추가)
training_log:
  parsers:
    - {name: physicsai_default, pattern: 'epoch=\s*(?P<epoch>\d+)\s*/\s*(?P<total>\d+)\s+loss=(?P<loss>[0-9.eE+\-]+)'}
    - {name: keras_like, pattern: 'Epoch\s+(?P<epoch>\d+)/(?P<total>\d+).*?train_loss:\s*(?P<loss>[0-9.eE+\-]+)'}
# 평가 점수 "R2 = 0.93", "MAE: 1.84" 같은 줄
score:
  parsers:
    - {name: generic, pattern: '^\s*(?P<name>[A-Za-z][A-Za-z0-9_ ]{0,40})\s*[:=]\s*(?P<value>[-+0-9.eE]+)\s*$'}
# PBS 상태가 "S: R" 형식인 사내 래퍼라면
#   state_regex: '^S:\s*(?P<state>[A-Z])'
```

검증 방법
- 설정 저장 → 백엔드 재시작 → 환경 점검 `config.valid`. 컴파일 오류·필수 그룹 누락은 여기서 걸린다(`training_log.parsers[1]: 정규식에 필수 그룹 'loss'이 없습니다` 등).
- 일치 여부는 실제 출력 몇 줄로 미리 확인한다: `python -c "import re;print(re.search(r'<패턴>', '<샘플 줄>'))"`.
- 실제 작업 후 결과 확인: ③-4는 모델 목록의 "로그 형식 미확인" 문구가 사라지는지, ③-5는 점수 표시, PBS는 대기열 패널의 run 상태·오류 묶음 `hpc_jobs.json`의 `external_state_raw`.
- 파서는 등록·평가 **시점**에 적용된다. 파서를 고친 뒤 이미 등록된 모델은 다시 등록(또는 재평가)해야 반영된다.

### 5.7 흔한 실수

| 증상 | 원인 | 고치기 |
|---|---|---|
| 기동 시 `commands.edspy_score: 확정 템플릿 … null일 수 없습니다` | 1차 확정 템플릿에 **명시적으로** `null`을 씀 | 원본 인용 값으로 되돌림(키를 아예 빼면 오류 대신 그 기능만 비활성 — §4.4) |
| 카드가 "관리자 설정 필요: commands.edspy_predict" | `commands` 블록을 일부만 복사해 그 키가 파일에 없음 | 예시의 `commands` 블록 전체를 복사 |
| `argv[0]은 {edspy} … 중 하나여야 합니다` | 실행 파일 경로를 템플릿에 직접 씀 | 경로는 `altair.*`에, 템플릿엔 placeholder |
| `placeholder '{model_pscfg}'은 허용되지 않습니다` | 그 키의 허용 목록 밖 | §5.3 표 확인(예: `{model_pscfg}`는 `edspy_score`·`edspy_predict`만) |
| `'cad_file' 값에 공백이 있습니다` / `허용되지 않는 문자` | AI 루트·Study·입력 경로에 공백·메타문자 | 경로에서 공백·특수문자 제거 |
| `.bat 실행 시 허용되지 않는 문자 = …` | SimLab.bat 등에 `key=value` 형태 값을 placeholder로 넘김 | 값을 파일(JSON 등)로 넘기거나 `=`가 없는 인자로 |
| 종료코드 0인데 `LOG_ERROR_DETECTED` | edspy step(①-3은 hstbatch) 로그에 `Traceback`·`[ERROR]`·`<숫자> Error:` 줄 | 실제 오류인지 확인. 무해한 출력이면 `commands_log_error_patterns`(①-3은 `train_data.hst_log_error_patterns`)를 좁힘 |
| 예측 경고 `MESH_OUTPUT_MISSING` 후 starter·include 오류 | SimLab 출력 메시 이름이 `eps_mesh*`가 아니거나 하위 폴더에 생김 | `predict.mesh_output_glob` 교체(U3), 출력이 `P/geom` 직계에 생기게 |
| PBS 작업이 영원히 대기 → 결국 `LOST` | `state_map`이 비었거나 사내 상태 문자가 없음, `state_regex` 불일치 | 실제 `qstat` 출력으로 정규식·`state_map` 보완 |
| `제출 결과에서 job id를 찾지 못했습니다` | qsub 출력이 `12345.pbs01` 한 줄이 아님 | `job_id_regex` 수정(MULTILINE이므로 `^…$`는 줄 단위) |
| PBS 노드에서 입력을 못 찾음 | `path_map` 미일치 → 이 PC 경로(`E:/…`)가 그대로 넘어감 | `path_map`에 AI 루트 대응 추가(위에서부터 첫 일치) |
| `'queue' 값이 없습니다` | 템플릿에 `{queue}`가 있는데 `hpc.defaults.queue: null` | 기본값 지정 또는 템플릿에서 제거 |
| `submit argv[0]이 allowed_executables에 없습니다` | 목록과 argv[0] 경로가 다름 | 두 곳을 같은 절대경로로 |

---

## 6. 리소스 제한(Job Object)

- 워커는 LOCAL step(Altair 실행)마다 Windows **Job Object** 1개를 만들어 그 안에서만 실행한다. 제한 없이 실행하는 경로는 없다(할당 실패 → step 실패 `JOB_OBJECT_ASSIGN_FAILED`).
- 적용 값: CPU **hard cap**(`cpu_rate`), 메모리 상한(`JobMemoryLimit`), 우선순위(`priority`), `KILL_ON_JOB_CLOSE`(워커가 죽으면 트리 종료). BREAKAWAY 불허 → 손자 프로세스까지 Job 안. **GPU는 제한하지 않는다.**
- 계산:

```text
감지 코어 = os.cpu_count(), 감지 메모리 = 물리 메모리 GB
auto_detect=false(기본): 유효 코어 = min(max_logical_cores, 감지 코어), 유효 메모리 = min(max_memory_gb, 감지 메모리)
auto_detect=true:        유효 코어 = min(max_logical_cores, floor(감지 코어 × auto_detect_ratio)), 메모리도 같은 방식
cpu_rate = clamp(floor(유효 코어 / 감지 코어 × 10000), 100, 10000)    # 1/100 % 단위
```

  예) 64코어 PC, 기본값 → 유효 32코어 → CPU 50% 상한. 128 GB PC → 메모리 64 GB 상한.
- 메모리 상한 도달로 비정상 종료하면 `RESOURCE_LIMIT`. 큰 모델·데이터셋이면 `max_memory_gb`를 올린다.
- 우측 "워커 자원" 패널에 유효 한도("32코어 · 64GB · 낮은 우선순위")가 보인다. Linux 개발 환경은 `posix` 제한기라 "CPU 상한 미적용(개발 환경)"으로 표시된다.
- PBS 명령(qsub 등)과 GPU 조회는 제한기 밖에서 짧게 실행된다.
- 값 변경(`max_*`, `priority`, `auto_detect*`)은 워커가 다음 claim부터 적용한다. `limiter` 변경은 워커 재시작.
- 확인: Process Explorer → 프로세스 속성 → Job 탭(E1-1~E1-3), 또는 환경 점검 `worker.job_object`.

## 7. 대기열 관리(전역 관리자)

- 로컬 실행 슬롯은 **전역 1개**(Altair·GPU 작업 = SLOT 레인 FIFO). 파일 복사·검증 작업(③-2 패키지, ③-4 모델 등록, ①-5 결과 가져오기, ②-0 SPDM 가져오기)은 LIGHT 레인에서 슬롯과 무관하게 1개씩.
- PBS 제출 작업은 제출 직후 슬롯을 놓고(`WAITING_HPC`), 회수 후 다음 로컬 step이 있으면 **대기열 맨 뒤로** 다시 선다.
- 우측 "실행 대기열" 패널에서 전역 관리자에게만 보이는 버튼:
  - **▲▼**: SLOT 대기 작업 순서 변경(`POST /queue/{job_id}/move {position}`).
  - **취소**: 대기 중이면 즉시 `CANCELED`. 실행 중이면 2초(`cancel_check_interval_s`) 안에 감지해 Job Object로 프로세스 트리 전체를 종료. PBS 대기·회수 중이면 run마다 `qdel`.
- 사용자는 자기 작업도 취소할 수 없다(결정 문구, U10). 요청이 오면 관리자가 취소한다.
- 실행 시간 한도가 없다. 비정상으로 오래 걸리는 작업은 로그(진행 라벨·경과 시간)를 보고 관리자가 취소한다.
- 모든 순서 변경·취소는 감사 테이블 `audit_events`에 남는다.

## 8. 알림

| 이벤트 | 시점 | 수신자 |
|---|---|---|
| `JOB_STARTED` / `JOB_SUCCEEDED` / `JOB_FAILED` / `JOB_CANCELED` / `JOB_INTERRUPTED` | 작업 상태 변화 | 작업 등록자 |
| `MY_TURN_NEXT` | 슬롯 사용 중에 대기 1번이 됨(작업당 1회) | 등록자 |
| `HPC_COLLECTED` | PBS 결과 회수 완료("30개 중 29개 회수") | 등록자 |
| `HPC_PARTIAL_FAILED` | ①-4 일부 run 실패, 나머지 회수 진행 | 등록자 |
| `HPC_CANCEL_FAILED` | PBS 취소 명령 실패(워커가 매 주기 재시도) | 등록자 |
| `ENV_CHECK_DONE` | 환경 점검 완료·실패·만료 | 요청한 관리자 |

- 전달은 폴링(10초, `ui.poll_notifications_ms`) → 우하단 토스트 + 상단 벨 미읽음 수. 이메일·메신저 발송 없음.
- 보관 `notifications.retention_days`(30일), 워커가 `purge_interval_h`(6시간)마다 정리.

## 9. 실패 코드(작업·step)

| 코드 | 뜻 | 먼저 볼 것 |
|---|---|---|
| `EXIT_NONZERO` | 외부 프로그램 종료코드 ≠ 0 | step 로그 끝, 라이선스, 입력 파일 |
| `LOG_ERROR_DETECTED` | 종료코드 0이지만 로그에 오류 줄 | step 로그의 첫 일치 줄(실패 메시지에 표시) |
| `OUTPUT_MISSING` / `OUTPUT_TOO_SMALL` | 기대 출력 없음 / psdata가 너무 작음 | 출력 이름 설정(U2·U3), edspy 로그 |
| `OUTPUT_LOCKED` | 기존 산출물을 `_backup`으로 옮기지 못함 | 해당 파일을 연 프로그램(HyperView 등) 닫기 |
| `RESOURCE_LIMIT` | Job 메모리 상한 도달 | `worker.max_memory_gb` |
| `JOB_OBJECT_ASSIGN_FAILED` | Job Object 할당 실패(실행 안 함) | 실행 계정 권한, 다른 Job에 묶인 상위 프로세스(작업 스케줄러 설정) |
| `EXECUTABLE_MISSING` | `altair.*` 비었거나 파일 없음 | 환경 점검 EXECUTABLE |
| `TEMPLATE_NOT_CONFIGURED` / `RESOURCE_NOT_CONFIGURED` / `RESOURCE_MISSING` | 템플릿 null / 자원 키 비어 있음 / pyd 0개·2개 | §2.7, §5 |
| `INPUT_INVALID` / `INPUT_CHANGED` | 입력 경로·형식 위반 / 등록 후 파일 변경(sha256 불일치) | 실패 메시지의 파일 목록 |
| `HPC_SUBMIT_FAILED` / `HPC_RUN_FAILED` / `HPC_UNREACHABLE` / `COLLECT_FAILED` | PBS 제출 실패 / run 실패 / 장시간 PBS 명령 실패 / 회수 실패 | §5.5, `hpc_jobs.json` |
| `GEN_PARTIAL_FAILED` | ① 플랫폼 생성에서 일부 run 입력 생성 실패(기본 `fail`). 재시도하면 실패한 run만 다시 만든다 | step 로그의 첫 실패 run, 라이선스·동시 수(§19) |
| `WORKER_LOST` | 워커 중단으로 lease 만료(`INTERRUPTED`) | 워커 작업 상태, 재부팅·업데이트 여부 |
| `CONFIG_INVALID` / `INTERNAL_ERROR` | 설정 오류 / 예상 못 한 오류 | `/status`, 오류 묶음 |

---

## 10. 환경 점검

"관리 > 환경 점검"(전역 관리자, `/physicsai/admin/env-check`) → **점검 실행**. 진행 중이면 다시 누를 수 없다(동시 1건). 설치·업데이트·설정 변경 후 항상 실행한다.

![환경 점검 화면](../../frontend/screenshots/phase2/env-check_1920x1080.png)

| 범주 | 항목(key) | 실행 위치 | 판정 |
|---|---|---|---|
| 설정 | `config.valid` | API | 설정 오류 0 → 정상, 아니면 실패(오류 키 목록) |
| 데이터베이스 | `db.connection`, `db.migration_head` | API | `SELECT 1`, head = `0003_hpc_cancel_failed` |
| 인증 | `auth.dashboard`, `auth.projects` | API | 대시보드 세션 확인·프로젝트 목록 200(dev_static이면 건너뜀) |
| HPC | `hpc.gateway` | API | `none` → 경고 "HPC 제출 미설정(hpc.gateway: none)", 설정 오류 → 실패 |
| 워커 | `worker.heartbeat` | API | 최근 하트비트 ≤ 3×주기. 오프라인이면 실패이고 워커 항목은 실행되지 않음 → 결과가 만료(EXPIRED) |
| 실행 파일 | `altair.<key>` 6개, `probe.<tool>` | 워커 | 존재·실행 가능. 프로브는 `env_check.probes` 설정 시에만 실제 실행(제한기 안, `probe_timeout_s`) |
| 원본 자원 | `resource.<key>` | 워커 | 비었으면 경고(기능 비활성), 없으면 실패, 런처는 pyd 정확히 1개 |
| 저장소 | `storage.ai_root.write`, `.free`, `storage.roots_overlap`, `storage.spdm_roots` | 워커 | `_platform/env_check_tmp/`에 임시 파일 쓰기(자동 삭제), 여유 ≥ `min_free_gb`, 루트 비중첩, SPDM 읽기 가능 |
| 워커 | `worker.limiter`, `worker.job_object` | 워커 | `windows_job` 정상(posix·null 경고), Job Object 자체 시험(`python -I -c pass`를 Job 안에서 실행 후 한도 값 조회) |
| GPU | `gpu.detect` | 워커 | `gpu_query`(또는 자동 탐색한 nvidia-smi) 결과 GPU ≥1 |

- 결과: 정상(녹)·경고(노)·실패(적)·건너뜀(회)·대기(회전). 세부 "보기"에 경로·크기·지연 등. 보고서 파일 `<ai_root>/_platform/env_checks/<id>/report.json`(프로브 출력 꼬리 포함, 마스킹)은 화면의 "복사"로 경로를 얻는다.
- 최근 점검에 실패가 있으면 상단 "관리" 옆에 빨간 점.
- 워커 항목은 워커가 15분(`expire_s`) 안에 처리하지 못하면 EXPIRED.

## 11. 오류 묶음

실패·취소·중단(또는 PBS 주의 표시가 있는) 작업 옆 **"오류 묶음 받기"** → `<study>_<job8>_error_bundle.zip`. 작업 등록자 본인과 전역 관리자만 받을 수 있다. 사용자가 받은 zip을 관리자에게 전달하는 용도다.

| zip 안 경로 | 보는 법 |
|---|---|
| `README.txt` | 작업 id·유형·상태·실패 코드·생성 시각 |
| `job.json` | 작업 전체: `params`(입력), `steps[]`(어느 step이 `FAILED`인지, `failure_code`·`failure_message`, `exit_code`), `warnings`, `env_snapshot`(Altair 경로·버전, 유효 한도, GPU) |
| `steps/step_<NN>_<key>.command.json` | **실제 실행된 argv·cwd·추가 env**. 템플릿 교체 결과 확인은 여기서. 팬아웃이면 대상별 명령 앞 200줄 |
| `logs/job.log.tail.txt`, `logs/step_<NN>_<key>.log.tail.txt` | 로그 꼬리(파일당 `log_tail_bytes`). 첫 줄 "앞 N 바이트 생략" |
| `hpc_jobs.json` | PBS run별 `external_job_id`·`state`·`external_state_raw`(정규식 디버깅) |
| `config_summary.json` | 유효 설정(DB URL·비밀 제외 + 마스킹) — 운영 설정이 의도대로인지 |
| `environment.json` | 앱·Python·OS 버전, migration head, 실행 파일 존재·크기·수정 시각, 최신 워커 하트비트(limiter·한도·GPU) |
| `env_check_latest.json` | 최근 완료 환경 점검 요약 |
| `TRUNCATED.txt` | 총량 상한(`max_total_bytes`)으로 빠진 항목 목록(있을 때) |
| `manifest.json` | 로그 폴더 유무(`logs_present`). Study 정리로 `logs/<job_id>/`가 `_backup`으로 옮겨졌으면 `false` |

읽는 순서: `README.txt`의 실패 코드 → `job.json`의 실패 step → 그 step의 `command.json`(인자 확인) → 같은 번호 로그 꼬리 → 필요하면 `environment.json`·`config_summary.json`. 산출물 파일(h3d·psdata 등)은 들어 있지 않다. DB URL·Bearer 토큰·쿠키·비밀 환경변수 값은 `***`로 가려진다.

### 11.1 Study 용량·정리(3차 S3)

Study 관리 화면 ③ "용량·정리"에서 power 사용자가 **용량 계산**(작업 `STUDY_STORAGE_SCAN`)과 **Study 정리**(작업 `STUDY_CLEANUP`)를 실행한다. 둘 다 LIGHT 레인·stage 0("관리") 작업이라 대기열·취소·로그가 다른 작업과 같다. 보관된 Study에서도 실행할 수 있다.

- 정리는 **삭제하지 않는다**. 고른 범주(학습 패키지 사본, 평가 예측 psdata, 정리된 h3d, 예측 Radioss 입력, ② 미리보기 산출, 오래된 작업 로그)를 `<study>\_backup\<UTC 시각>_<작업ID>\<원래 상대경로>`로 옮기고 `CLEANUP_MANIFEST.json`을 남긴다. 등록 모델(`03_model\models`)·`03_dataset`·`04_params`·`00_inbox`·`_backup`·SPDM은 대상이 아니다.
- 정리 중에는 그 Study의 다른 작업 생성·재시도가 409 `STUDY_CLEANUP_RUNNING`. 열린 파일 때문에 옮기지 못한 항목은 건너뛰고(경고 `PARTIAL_OUTPUT`) 결과 화면에 사유가 남는다. 전부 실패하면 `OUTPUT_LOCKED`.
- `_backup`은 앱이 비우지 않는다. 디스크가 부족하면 탐색기에서 `_backup\<시각>_<작업ID>` 폴더를 직접 지운다. 되돌릴 때는 그 아래 파일을 원래 위치로 옮기고, 학습 패키지를 되돌렸다면 ③-2를 다시 실행해 등록한다.
- 설정 `study_storage`(없으면 기본값): `max_entries`(스캔 상한, 넘으면 부분 스캔 — 정리 불가), `top_files`, `max_items_per_category`, `log_min_age_days`(로그 후보 최소 경과일), `keep_failed_logs`(실패 로그 보존 개수), `stale_after_hours`(계산 결과 유효 시간). 감사 기록 `STUDY_CLEANUP`에 범주·개수·바이트가 남는다.

## 12. 로그 위치

| 로그 | 위치 | 비고 |
|---|---|---|
| 작업 로그 | `<ai_root>/<study>/logs/<job_id>/job.log` | 모든 step 출력 병합(UTF-8) |
| step 로그 | `<ai_root>/<study>/logs/<job_id>/step_<NN>_<step_key>.log` | 화면 "로그" 링크와 같은 내용 |
| 팬아웃 명령 기록 | `…/logs/<job_id>/step_<NN>_<key>.commands.jsonl` | 대상별 argv·종료코드 |
| SPDM 가져오기 계획 | `…/logs/<job_id>/spdm_plan.json` | |
| 원본 도구 자체 로그 | 각 작업 폴더(예 `01_train/extract/<job>/*_LogFile.txt`) | ①-1 실패 시 step 로그 끝에 꼬리 2 KiB 첨부 |
| 환경 점검 보고서 | `<ai_root>/_platform/env_checks/<id>/report.json` | |
| 백엔드·워커 프로세스 로그 | `<logging.dir>\backend.log`, `worker.log`(기본 `<install_root>\logs\`) | §12.1 |
| 작업 스케줄러 기록 | 작업 스케줄러 → 작업 → "기록" 탭 | 시작·종료·재시작·종료코드(2 = 워커 기동 거부) |
| 감사 기록 | DB 테이블 `audit_events` | 작업 생성·취소·재시도·순서 변경·Final 지정·환경 점검·오류 묶음 내려받기 등 |
| Caddy | 대시보드 Caddy 설정의 로그 위치 | |

### 12.1 백엔드·워커 파일 로그

- 작업 스케줄러는 표준 출력을 버리므로 백엔드·워커가 직접 **회전 파일 로그**를 쓴다: `<logging.dir>\backend.log`, `<logging.dir>\worker.log`. `logging.dir`이 비면 작업 폴더의 `logs\`(설치본은 `<install_root>\logs\`).
- 회전: 파일당 `logging.max_mb`(기본 20 MB), 보관 `logging.backups`(기본 10개) → 컴포넌트당 최대 약 220 MB. 별도 정리 불필요.
- 내용: 기동·설정 변경 감지·claim·오류·HTTP 접근(uvicorn) 기록. 저장 전에 오류 묶음과 같은 마스킹(`logging.mask_patterns` + DB URL 자격 증명·Bearer·세션 쿠키·비밀 환경변수 값)을 적용한다.
- 수준 `logging.level`. 원인 분석 때만 `DEBUG`로 올리고 두 프로세스를 재시작한다.
- 폴더를 만들 수 없으면 표준 오류에 알리고 콘솔 로그만으로 계속 뜬다(기동 거부 아님) — 실행 계정이 `<install_root>\logs`에 쓸 수 있어야 한다.
- 워커 기동 거부(종료코드 2)는 원인 메시지가 `worker.log`와 작업 스케줄러 기록에 남는다.

---

## 13. 문제 해결(FAQ)

**먼저 `<install_root>\logs\worker.log`·`backend.log`를 본다.** 그래도 모르면 **콘솔에서 직접 띄워 오류 보기** — 작업을 멈추고 일반 PowerShell에서(작업과 같은 인자 `--runtime`):

```powershell
Stop-ScheduledTask PhysicsAI-Worker
cd E:\VD_SIMULATION_WEB\physicsai-platform\.runtime     # 묶음 설치는 install_root
.\venv\Scripts\python.exe -m physicsai_worker --runtime .      # "기동 거부: …" 메시지와 종료코드 2 확인(묶음은 --config <config_path> 추가)
# 확인 후 Ctrl+C, Start-ScheduledTask PhysicsAI-Worker
```

**Q. 경로를 넣으면 "AI 루트 밖입니다"(`PATH_OUTSIDE_ROOT`) / "안전하지 않은 경로"(`PATH_UNSAFE`)가 나온다.**
- 입력은 절대경로, 400자 이하. `ai_root`(모델·CAD·조립·결과 폴더는 `allowed_import_roots`, ①-5는 `collect_root_local`도) 하위여야 한다.
- 거부: 공백·제어문자·`& | < > ^ % ! "`, `..`, 심볼릭 링크·junction, `_backup`·`_platform` 하위, AI 루트 자체, Study 산출 폴더(`03_dataset`·`03_package`·`03_model`·`04_params`·`04_predict`·`01_train/extract|doe|tpl|radioss_assem`·`02_preview`·`05_opt`·`logs`) 안. ③-1은 `01_train/results`·`02_import`·`02_curated/*/CURATED_DATA`는 허용.
- SPDM 경로(②-0)만 공백·한글 허용(읽기만, 복사본 이름을 정리).
- 해결: 파일을 `<study>/00_inbox/` 아래로 옮기거나, 읽기 전용으로 쓸 루트를 `allowed_import_roots`에 추가(백엔드 재시작).

**Q. 매핑 드라이브(E: → `\\서버\share`)를 AI 루트로 쓰는데 워커만 못 읽는다.**
- 매핑 드라이브는 **로그온 세션별**이다. `Background` 모드(세션 0, 서비스 계정)에서는 사용자가 매핑한 `E:`가 보이지 않는다.
- 선택지: (가) AI 루트를 로컬 디스크에 둔다. (나) `Interactive` 모드로 등록하고 그 계정 로그온 시 드라이브가 매핑되게 한다. (다) 실행 계정 시작 스크립트에서 매핑. 어느 경우든 `ai_root` 문자열은 사용자가 화면에 붙여 넣는 경로 형태와 맞춘다(설정값 그대로와 실경로 두 형태로 비교하므로 UNC·SUBST·매핑 드라이브 혼용은 허용되나, 운영 PC에서 E0-7로 확인).
- 확인: 환경 점검 `storage.ai_root.write`.

**Q. 세션 0에서 미리보기·컨투어 이미지가 안 나오거나 hw가 멈춘다.**
- `Background` 모드는 데스크톱 없는 세션 0에서 돈다. HyperWorks 배치(`hw -b -tcl`)·SimLab의 렌더링·GUI 의존 동작이 실패하거나 응답이 없을 수 있다(U11·U31 미확인).
- 해결: `install.ps1 -RunMode Interactive`로 재등록(실행 계정 로그온 시 시작) + 그 계정 자동 로그온·화면 잠금 정책 확인. 전후 결과를 E2-0-4에 기록.

**Q. 작업이 "실행 중"인데 진행이 없다(라이선스 대기).**
- Altair 도구는 라이선스를 얻을 때까지 대기할 수 있고, 플랫폼에는 실행 시간 한도가 없다. step 로그 마지막 줄(진행 라벨)에 라이선스 메시지가 있는지 본다.
- 확인: 실행 계정에서 라이선스 환경변수(`ALTAIR_LICENSE_PATH` 등)가 보이는지. 허용목록 패턴(`ALTAIR_*`, `*_LICENSE_*`, `*_LICENSE`)에 안 맞는 이름이면 `worker.env_passthrough`에 추가. 서비스 계정이 라이선스 서버에 접근 가능한지.
- 오래 막혀 있으면 관리자가 취소한다.

**Q. 취소를 눌렀는데 끝나지 않는다.**
- 로컬 실행: 2초 안에 감지 → `TerminateJobObject` → 최대 30초 대기. 그 뒤에도 `RUNNING`이면 워커가 응답하지 않는 상태 → 작업 스케줄러에서 워커 중지(Job이 닫히며 트리 종료) → 약 1분 뒤 `INTERRUPTED` → 워커 시작.
- PBS: `qdel` 실패 시 작업은 `WAITING_HPC` + "취소 실패, 재시도 중"(`HPC_CANCEL_FAILED`)으로 남고 워커가 매 폴링마다 다시 시도한다. PBS 쪽에서 직접 `qdel <id>`(id는 run 목록·오류 묶음 `hpc_jobs.json`)로 지우면 다음 폴링 때 정리된다.
- 대기 중 작업 취소는 즉시 반영.

**Q. 모든 작업이 대기에서 안 넘어간다.**
- 우측 "워커 자원"에 "워커 오프라인"이면 워커가 죽었거나 기동 거부. 작업 스케줄러 기록의 종료코드 2 → 콘솔 실행으로 원인(설정 오류, DB head 불일치 → `alembic upgrade head`, 잠금 파일 사용 중 → 다른 워커 프로세스 종료).
- 워커는 온라인인데 진행이 없으면 설정 변경 후 검증 실패로 claim을 멈췄을 수 있다 → `/status`·환경 점검 `config.valid`.

**Q. 화면이 "대시보드에서 로그인하세요"만 보인다 / 503.**
- 대시보드에 로그인했는지, 같은 주소(origin)로 접속했는지. 401은 쿠키 없음, 503 `DASHBOARD_UNREACHABLE`는 `auth.dashboard_internal_url`로 대시보드에 연결 실패.

**Q. 카드가 "관리자 설정 필요: …"로 비활성이다.**
- 표시된 키(예 `resources.pyd_dir`, `commands.simlab_extract_params`, `hpc.gateway`, `storage.spdm_roots`)를 채우고 백엔드 재시작. 기능별 필요 키는 `/physicsai/api/status`의 `features.<기능>.missing`.

**Q. 업데이트 후 워커가 뜨지 않는다.**
- `DB migration head 불일치` → `alembic upgrade head`를 다시 실행(⑤ 실패 여부 확인). 새 버전에서 설정 키가 바뀌었으면 `config.valid` 메시지대로 `platform.yaml` 수정.

**Q. 회사 프록시 환경(`HTTP_PROXY`·`HTTPS_PROXY` 설정 PC)에서 health 확인·시연 기동이 실패한다.**
- 증상: `backend.log`에는 `Uvicorn running on http://127.0.0.1:…`로 정상 기동했는데 `start-demo`·`install`·`update`가 "백엔드 기동 실패"/"health 확인 실패"로 끝난다. 원인은 루프백(127.0.0.1) 요청이 프록시로 나가는 것(GitHub #1).
- 현재 버전은 루프백 호출(시연 health·seed, `install.ps1`·`update.ps1` health·대기열 조회, 대시보드 인증 `auth.dashboard_internal_url`이 127.0.0.1·localhost·::1일 때)에서 프록시를 쓰지 않는다. 외부 주소 호출과 pip·npm은 기존 프록시 설정을 그대로 쓴다. 설정 키는 없다.
- 시연 기동이 실패하면 출력과 `<DemoRoot>\logs\demo-setup.log`에 **마지막 health 오류**(예 `URLError: … Connection refused`)가 남는다. 실패 시 이번에 띄운 백엔드·워커는 자동 종료되고, 이전 실행이 일부만 남아 있으면(예: 백엔드만 떠 있음) 다음 실행이 정리하고 다시 띄운다. 시연 DB는 켜 둔 채 다음 실행이 재사용한다.
- 이전 버전에서 실패해 포트(예 8190)를 잡은 백엔드가 남아 있으면 `deploy\demo\stop-demo.bat`(또는 아래 직접 실행) 후 다시 시작한다.

**Q. `.bat` 실행이 "액세스가 거부되었습니다"(Access is denied)로 막힌다.**
- 회사 PC 보안 정책이 배치 파일 실행을 막는 경우다. PowerShell 스크립트를 직접 실행한다(관리자 권한 불필요, 인자는 같다).

```powershell
cd <압축 해제 폴더 또는 저장소>
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\demo\start-demo.ps1 -DashboardRoot E:\simulation_workbench
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\demo\stop-demo.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install.ps1 -ConfigFile .\deploy\deploy.json   # 운영 설치(관리자 PowerShell)
```

**Q. 디스크가 찬다.**
- `<study>/_backup/`(덮어쓰기 전 이동본)과 `03_dataset`(psdata), `04_predict`, `01_train/results`가 크다. 플랫폼은 자동 삭제하지 않는다. 사용자와 확인 후 관리자가 정리한다. 환경 점검 `storage.ai_root.free`로 여유 공간 경고.

---

## 14. 시연 모드

Altair·PBS 없이 **가짜 도구(fake tools)**로 화면·대기열·알림·취소·①~⑤ 흐름을 실제로 돌려 보는 모드다. 운영 설치와 별개로 동작한다(포트·폴더·DB 분리). **운영 서버 설정에 `demo.enabled: true`를 넣지 않는다.**

### 14.1 시작

```powershell
deploy\demo\start-demo.bat                       # 관리자 권한 불필요. 또는 start-demo.ps1
deploy\demo\start-demo.ps1 -DemoRoot D:\pai-demo -PgBin E:\PostgreSQL\18\bin -ToolDelay 5
deploy\demo\start-demo.ps1 -DemoRoot D:\pai-demo -DashboardRoot E:\simulation_workbench   # PgBin·Python을 대시보드 환경에서
```

| 인자 | 기본 | 뜻 |
|---|---|---|
| `-DemoRoot` | `<시스템 드라이브>\physicsai-demo`(보통 `C:\physicsai-demo`) | 시연 폴더. 공백·특수문자 금지 |
| `-Port` | `8190` | 백엔드 포트(127.0.0.1 전용, 운영 8100과 겹치지 않게) |
| `-PythonExe` | 자동 선택(아래 "Python 선택 순서") | Python 3.12(대시보드와 같은 3.12.13 권장). 시연 venv를 처음 만들 때만 쓴다 |
| `-PgBin` | `-DashboardRoot`의 `.env` `POSTGRES_BIN` → PATH → `PGBIN` 순 | PostgreSQL 18 `initdb.exe`·`pg_ctl.exe`·`psql.exe` 폴더(예 `E:\PostgreSQL\18\bin`, 포터블 zip 압축 해제본 가능) |
| `-DashboardRoot` | – | (선택) 대시보드 폴더(예 `E:\simulation_workbench`). `.env`의 `POSTGRES_BIN`과 `.tools` 고정 Python 3.12를 기본값으로(비밀번호는 읽지 않음, §2.3 `dashboard_root`와 같은 규칙) |
| `-PgPort` | `55432` | 시연 전용 PostgreSQL 포트 |
| `-UseExistingDb` | – | 시연 클러스터 대신 기존 PostgreSQL의 **빈 DB** 사용. 접속 URL은 환경변수 `PHYSICSAI_DEMO_DATABASE_URL`로만 준다(비밀번호가 든 URL을 인자로 받지 않음) |
| `-ToolDelay` | `3`(초) | 가짜 도구 1회 실행마다 지연 — 대기열·진행률·취소를 보기 쉽게 |
| `-NoBrowser` | – | 브라우저를 자동으로 열지 않음 |

하는 일: ① Python 준비(저장소·묶음 공통 — 아래) ② 시연 폴더·가짜 도구·가짜 자원·설정(`<DemoRoot>\config\platform.yaml`, 원본 `config/platform.demo.yaml`) ③ DB(시연 전용 클러스터 `<DemoRoot>\pgdata`, 127.0.0.1:`PgPort`, 또는 기존 DB) ④ migration → 백엔드(프런트 정적 서빙 포함, Caddy 불필요) → 시연 Study·샘플 데이터 → 워커 ⑤ 브라우저 열기.

**Python 선택 순서**(저장소·묶음 공통, 시연 venv를 처음 만들 때): `-PythonExe` → `-DashboardRoot`의 고정 Python 3.12(`.tools\python\cpython-3.12.*`) → `py -3.12` → PATH의 `python`. 각 후보를 실제로 실행해 Python 3.12인지 확인하고, 실행이 안 되거나(예: pyenv-win shim에 전역 버전 미설정, Microsoft Store 별칭) 버전이 다르면 다음 후보로 넘어간다. 고른 Python은 `Python 선택: … → <경로>` 한 줄로 출력된다.

**패키지 설치 위치**: 대시보드 런타임이나 시스템 Python에는 아무것도 설치하지 않는다. 항상 `<DemoRoot>\venv`를 만들어 그 안에만 설치한다.

| 실행 위치 | venv에 설치하는 것 | 요구사항 |
|---|---|---|
| 오프라인 묶음(`wheels` 폴더 있음) | `wheels`의 `physicsai-platform`(인덱스 접근 없음) | Python 3.12 |
| 저장소(git clone) | `packages\simdash_adapters`(로컬) → `deploy\requirements.lock`. 기록 파일 `<DemoRoot>\venv\physicsai-repo-deps.sha256`의 해시가 같으면 건너뜀(lock이 바뀌면 다시 설치). 플랫폼 소스는 `PYTHONPATH`로 | Python 3.12, 패키지 인덱스 접근(PyPI 또는 사내 `PIP_INDEX_URL`·프록시 — 기존 pip 설정을 그대로 씀). `frontend\dist`가 없으면 Node 22로 `npm ci` → `npm run build`를 자동 실행(Node가 없거나 22가 아니면 중단) |

- 저장소 모드에서 pip가 인덱스에 접근하지 못하면 "오프라인 묶음(`deploy\collect-offline.ps1`)으로 실행하세요" 안내와 함께 중단한다(폐쇄망 PC는 묶음 사용).
- 기존 `<DemoRoot>\venv`가 Python 3.12가 아니면 중단한다 → 그 `venv` 폴더 이름을 바꾼 뒤 다시 실행. 의존성을 강제로 다시 설치하려면 `physicsai-repo-deps.sha256` 이름을 바꾼다.
- 예: 대시보드가 `E:\VD_SIMULATION_WEB\simdashboard`이고 PATH 첫 `python`이 pyenv shim인 PC → `deploy\demo\start-demo.bat -DashboardRoot E:\VD_SIMULATION_WEB\simdashboard` 그대로 실행하면 대시보드 Python 3.12로 시연 venv를 만든다(GitHub #1).

### 14.2 사용

- 접속 `http://127.0.0.1:8190/` → 시연 사용자 **admin(전역 관리자) / power / general** 중 선택(권한별 화면 차이 확인용). 시연 로그인은 루프백 접속에서만 된다.
- 시연 Study **"시연 브래킷 낙하"**가 자동으로 만들어지고 `00_inbox`에 CAD·`radioss_assem`·`params_demo`가 들어 있다.
- PBS가 없으므로 ①-4 대신 **①-5 결과 가져오기**에 `<DemoRoot>\import\hpc_results`를 지정한다.
- ③-4 모델 등록 폴더는 `<DemoRoot>\import\trained_model`.
- 실패·멈춤 흉내: 환경변수 `FAKE_TOOL_MODE_<도구>=fail`(또는 `hang`)를 설정한 뒤 `start-demo`를 실행한다(도구 이름 `EDSPY`·`SIMLAB`·`HW`·`HVTRANS`·`HSTBATCH`·`HSTPY`. 예 같은 창에서 `$env:FAKE_TOOL_MODE_EDSPY='hang'` 후 `start-demo.ps1` → 관리자 취소 시연). 오류 묶음·알림·취소 흐름을 보여 줄 때 쓴다.
- 로그: `<DemoRoot>\logs\` — `backend.log`·`worker.log`(회전 파일 로그, §12.1)와 `backend.out.log`·`worker.out.log`(표준 출력 — 기동 실패 메시지는 여기). 작업 로그는 일반 운영과 같이 Study `logs\`.

**회사 프록시 환경·`.bat` 차단**:
- `HTTP_PROXY`·`HTTPS_PROXY`가 설정된 PC에서도 시연의 127.0.0.1 호출(health·seed)은 프록시를 타지 않는다(저장소 모드의 pip·npm 설치는 기존 프록시 설정 사용). 기동 실패 시 출력·`<DemoRoot>\logs\demo-setup.log`의 "마지막 오류"로 원인을 보고, 그대로 다시 실행하면 남은 백엔드·워커를 정리하고 다시 띄운다(§13 "회사 프록시 환경").
- `start-demo.bat`이 "액세스가 거부되었습니다"로 막히면 `powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\demo\start-demo.ps1`(운영 설치는 `.\deploy\install.ps1`)를 직접 실행한다(인자 동일).

### 14.3 종료

```powershell
deploy\demo\stop-demo.bat            # 백엔드·워커·시연 DB 클러스터 중지
deploy\demo\stop-demo.bat -KeepDb    # 시연 전용 PostgreSQL은 계속 실행
```

파일·DB는 지우지 않는다. 시연을 처음부터 다시 하려면 `<DemoRoot>`를 다른 이름으로 옮기거나 직접 정리한 뒤 다시 시작한다.

### 14.4 오프라인 묶음과 안전장치

- 오프라인 묶음(§2.2)에 `deploy\demo`, 가짜 도구(`fake_tools`), `config\platform.demo.yaml`이 포함된다. 폐쇄망 PC에서도 묶음의 `deploy\demo\start-demo.bat`로 바로 시연할 수 있다.
- 안전장치: `demo.enabled: true`는 `profile: dev`이고 `server.host: 127.0.0.1`일 때만 허용, `auth.mode: demo`는 `demo.enabled: true`가 필요, 시연 로그인은 루프백 요청만 받는다. 위반하면 설정 오류로 기동하지 않는다.

### 14.5 무인 설치(참고 — CI·자동화용)

운영 설치 스크립트를 대화형 입력 없이 돌릴 수 있다.

```powershell
$env:PHYSICSAI_INSTALL_PG_ADMIN_PASSWORD = '…'; $env:PHYSICSAI_INSTALL_DB_PASSWORD = '…'
$env:PHYSICSAI_INSTALL_SERVICE_PASSWORD = '…'      # Background 모드일 때
.\install.ps1 -PasswordsFromEnv -NoStart            # -NoStart: 작업 등록만 하고 시작·health 확인은 생략
```

비밀번호는 프로세스 환경변수로만 받는다(명령 인자·로그에 남지 않음). 끝나면 그 PowerShell 창을 닫는다.

## 14-1. CI(GitHub Actions)

워크플로 `.github/workflows/ci.yml`. 실행 시점: 모든 `push`, `pull_request`, 수동 실행(`workflow_dispatch`). 같은 브랜치에 새 push가 오면 진행 중인 실행은 취소된다(`concurrency`).

| 잡 | 환경 | 단계(순서대로) |
|---|---|---|
| **linux** "Linux · test-all (PostgreSQL 18)" | ubuntu-24.04, Python 3.12.13(`.python-version`), Node 22.23.2(`.node-version`), PostgreSQL 18(PGDG apt, 시험마다 임시 클러스터 — `PHYSICSAI_TEST_PGBIN`, `PHYSICSAI_REQUIRE_PG_MAJOR=18`), 제한 40분 | ⓪ 버전 확인(Python·Node가 고정값과 같음) ① `./packages/simdash_adapters` → `deploy/requirements.lock` + pytest 설치 ② `pwsh` 확인(ps1 구문 검사 시험용) ③ `scripts/test-all.sh`(pytest(어댑터 패키지 시험 포함) + openapi 최신 여부 + vitest + tsc) ④ `deploy/collect-offline.sh --dry-run` ⑤ `scripts/check-adapters-wheel.sh`(wheel 이름·빈 venv 설치) |
| **windows** "Windows · pytest 전체 + Job Object + 배포·시연" | windows-latest, Python 3.12.13(setup-python Windows 목록에 없어 대시보드처럼 uv 0.11.32로 `<가짜 대시보드>\.tools\python\cpython-3.12.13-windows-x86_64-none`에 설치 → 시험용 venv), Node 22.23.2, PostgreSQL 18(러너 기본이 18이면 그 서비스, 아니면 EDB 공식 zip 바이너리로 클러스터), 제한 75분 | ① **Windows 전용 시험**(`pytest -m windows`: V-JO-1~3, CREATE_SUSPENDED, V2-EC-4) — `PHYSICSAI_REQUIRE_WINDOWS_TESTS=1`이라 **skip이면 실패** ② **pytest 전체**(fake tools `.exe` 런처 + 실제 Job Object 제한기 + 시연 E2E) ③ **PowerShell 구문 검사**: `deploy`·`scripts`의 모든 `.ps1`을 pwsh 7과 Windows PowerShell 5.1 양쪽 파서로 ④ **오프라인 묶음 실제 생성**(GitHub #1 재현: PATH 첫 `python`이 실패하는 가짜 pyenv shim 상태에서 사용자와 같은 Windows PowerShell 5.1 `-File`로 `collect-offline.ps1 -DashboardRoot <가짜 대시보드>` → 대시보드 Python 3.12·Node 22 선택, 빌드용 venv 삭제·묶음 미포함·대시보드 Python 무설치 확인; wheels(`simdash_adapters-0.1.0-py3-none-any.whl` 포함)·프런트·시연 가짜 도구 포함 확인) ⑤ **install 실제 설치**: 시연 설정으로 `dist\deploy\install.bat -PasswordsFromEnv -NoStart`(Interactive 모드) → 작업 2개 등록 확인(`ExecutionTimeLimit=PT0S`, `RestartCount=999`, `MultipleInstances=IgnoreNew`) → 백엔드 health(러너 세션에서 작업이 안 뜨면 설치된 venv로 직접 기동해 설치본 검증, 경고 주석) → `uninstall-tasks.ps1`로 해제·없음 확인. 이 설치는 `deploy.json`에 `python_exe`·`pg_*` 없이 **`dashboard_root`(가짜 대시보드 `.env`·`.tools`)만** 주어 기본값 채움·PostgreSQL 18 확인·대시보드 DB 사용자·비밀번호 미출력을 검사 ⑥ **시연 원클릭**: `start-demo.bat -DashboardRoot`(포트 8196, PgBin을 대시보드 `.env`에서) → power 시연 로그인 → `/status`의 `demo`·워커 온라인·limiter `windows_job` 확인 → 시연 Study에서 ①-1 파라미터 추출 작업 실행 → `SUCCEEDED` 확인 → `stop-demo.bat` |

③~⑥은 앞 단계가 실패해도 실행된다(취소된 경우만 제외) — 한 번에 여러 문제를 볼 수 있다.

**실패 주석** — 실패한 단계는 `scripts/ci_annotate.py <로그> <제목> [줄 수]`가 로그 끝부분(기본 200줄)을 최대 4개 `::error` 주석으로 나눠 남긴다. 로그 원문을 내려받지 않아도 실행 요약 화면·Checks API에서 원인을 볼 수 있다. Windows 전용 시험의 실측값은 `::notice title=Job Object 실측::…` 주석으로 남는다.

결과 보는 법
1. GitHub 저장소 → **Actions** 탭 → 왼쪽 "CI" → 해당 커밋/PR 실행을 연다. PR 화면 아래 "Checks"에도 같은 결과가 나온다.
2. 실행 요약 화면 위쪽 **Annotations**에 실패 주석(`test-all 실패 (1/4)`, `install 예외` 등)과 Job Object 실측 notice가 모여 있다. 먼저 여기를 본다.
3. 잡(linux·windows)을 눌러 빨간 X 단계를 펼치면 전체 로그가 보인다.
4. 수동 실행: Actions → CI → **Run workflow** → 브랜치 선택.
5. windows 잡 ⑤⑥이 통과하면 배포 스크립트·작업 등록·시연 모드가 깨끗한 Windows에서 한 번 돌았다는 뜻이다. 운영 PC 고유 사항(Altair·라이선스·세션 0 렌더링·Caddy·매핑 드라이브)은 E2E 체크리스트로 따로 확인한다.

**참고 — Windows 러너 실측**(구현 에이전트 보고, windows 잡 notice 기준. 러너 사양에 따라 달라질 수 있음)

| 항목 | 설정 | 관측 |
|---|---|---|
| Job Object CPU hard cap(V-JO-1) | CPU rate 20% | 실제 CPU 사용 21~24% |
| Job 메모리 상한 | 256 MiB | 512 MiB 할당 요청이 거부됨. `PeakJobMemoryUsed`는 **거부된 요청량까지 포함**해 보고됨 → 최대 사용량 표시가 상한보다 크게 보일 수 있다 |
| 작업 스케줄러 등록 | install.ps1 | `ExecutionTimeLimit=PT0S`(무제한), `RestartCount=999`, `MultipleInstances=IgnoreNew` 확인 |

---

## 15. 미확정 항목과 확인 후 바꿀 위치

사내 확인(E2E 체크리스트) 결과에 따라 **설정만** 바꾸면 되는 항목과 계약·코드 변경이 필요한 항목을 구분했다. "설정" 열이 있는 항목은 이 매뉴얼 §4·§5대로 바꾼다. 계약 변경이 필요한 항목은 Plan에 결과를 전달한다.

| # | 항목 | E2E | 바꿀 위치 |
|---|---|---|---|
| U1 | PBS 명령·출력 형식·경로 대응 | E6-1 | `hpc.gateway: command`, `hpc.command.*`(§5.5), `hpc.transfer.path_map` |
| U2 | ④ SimLab 형상·메싱 호출, 렌더 파일 이름 | E4-3 | `commands.geom_update`, `commands.mesh`, `predict.rendered_script_name` |
| U3 | 메시 파일 이름·include 연결 | E4-4 | `predict.mesh_output_glob`, `commands.rad_assemble` |
| U4 | 컨투어 TCL 이미지 생성 여부 | E4-6 | 이미지 없으면 신규 렌더 TCL(B안) → 계약 변경(현재 보류: 3D 뷰어 보류 결정) |
| U5 | HPC 학습 로그 형식 | E3-5 | `training_log.parsers`(§5.6) |
| U6 | 평가 점수 형식 | E3-6 | `score.parsers` |
| U7 | 평가·예측에 pscfg 필요 여부 | E4-10 | 필요하면 `commands.edspy_score`·`edspy_predict`에 `{model_pscfg}` 추가 |
| U8 | 응답값 추출(MinMax TCL) | E4-7 | `commands.response_extract`(argv[0] `{hw}`), `resources.extract_minmax_tcl` |
| U9 | 정수 형식 반올림/절삭 | E4-2 | `predict.integer_rounding` |
| U10 | 대기열 관리 = 전역 관리자 해석 | 사용자 확인 | 계약 platform.md §5.3(코드 변경) |
| U11 | BREAKAWAY·메모리 한도·세션 0 | E1-7, E2-0-4 | `install.ps1 -RunMode`, `worker.max_memory_gb` |
| U12 | 홀드아웃 분할 단위 | E3-1 | `dataset.split_group` |
| U13 | hooks 사용 여부 | – | 필요 시 계약 변경(`@hooks_arg`) |
| U14 | 운영 Caddy·쿠키 공유 | E0-4, E2-0-5 | `deploy/caddy/physicsai.caddy` 반영, `auth.cookie_name` |
| U15 | 패키지 하드링크 HPC 동작 | E3-3 | `package.link_mode: copy` |
| U16 | 홀드아웃 대표성 | 운영 판단 | `dataset.holdout_ratio` |
| U17 | HyperStudy run 폴더 구조 | E2-1-4 | `train_data.run_dir_glob` |
| U18 | DOE 샘플 값 위치·형식 | E2-1-5 | `train_data.samples_extractor`, `paramitem_regex`, `rendered_tpl_*`, `samples_csv_*` |
| U19 | 업로드본에 없던 원본 파일 | E2-0-1 | `resources.*`(§2.7) |
| U20 | SimLab 추출 진행 표식·XML 형식 | E2-1-1 | `train_data.extract_progress_token`·`extract_progress_total`(XML 형식은 계약 변경) |
| U21 | `-multiexec`와 Job Object | E2-1-4 | `train_data.max_multi_execution`, `worker.max_*` |
| U22 | FullFact/FracFact run 수 | E2-1-4 | 없음(진행률 표시만) |
| U23 | `%3i` 정수 형식 | E2-1-3 | `train_data.param_default_format`(행별로도 변경 가능) |
| U24 | PBS 다중 run 제출 방식·결과 구조 | E2-1-6 | `hpc.command.submit`, `hpc.transfer.collect_patterns`(배열 job이면 계약 변경) |
| U25 | 수동 결과 폴더 run 매칭 | E2-1-7 | `train_data.result_run_dir_regex`, `result_match_depth` |
| U26 | hvtrans cfg 문법 | E2-2-2 | `commands.hvtrans_curate`(cfg 생성 규칙은 계약 변경) |
| U27 | 곡선 JSON 형식 | E2-2-4 | 없음(화면이 JSON 트리로 대체 표시) |
| U28 | ⑤ 결과 요약 형식 | E2-5-3 | `optimize.summary_parsers` |
| U29 | ⑤ 진행 총수 | E2-5-2 | `optimize.progress_regex` |
| U30 | SPDM 폴더 구조·이름 | E2-6-1 | `spdm_import.patterns` |
| U31 | 세션 0 배치 동작·라이선스 | E2-0-4 | `install.ps1 -RunMode Interactive`, `worker.env_passthrough` |
| U32 | Altair 도구 버전 인자 | E2-0-7 | `env_check.probes.*` |
| U33 | 오류 묶음 권한 범위 | 사용자 확인 | 계약 phase2 §10.1 |
| U34 | 대시보드 SPDM 경로 링크 | 대시보드 측 | 대시보드 D8 |
| U35 | run별 응답 추출 | – | `commands.response_extract` |
| U36 | 회수 모드 "드라이브" 의미 | 사용자 확인 | `hpc.transfer.collect_mode`, `collect_root_*` |
| U37 | 미사용 파라미터의 CAD 공칭 유지 | E2-1-3 | 안 되면 계약 변경(tpl 생성 규칙) |

---

## 16. SCX 잡 제출(scx 모드 — phase3 §16, D3-57)

①-4 해석 제출(`TD_SOLVE`)과 ④ 검증(`PREDICT_VERIFY`)의 Radioss를 Siemens Simcenter X(SCX)에 제출한다. PhysicsAI는 SCX 어댑터를 직접 쓰지 않고
**대시보드의 SCX 연결(공용 계정 토큰)을 같이 쓴다** — 대시보드가 loopback 전용 내부 API "SCX relay"(`/internal/scx-relay/v1`)를 열고
PhysicsAI 워커가 그것을 부른다(계약 `docs/contracts/scx_relay.md`). 토큰·워커 잠금은 대시보드 하나만 가진다.

- 드라이브 위치: 공용 계정 홈(`/Users/vd.dashboard`) 아래 `<Study 폴더 이름>/<잡 폴더>/`. 잡 폴더는 항상 새로 만든다
  (① `01_D-<NNN>_<run>_<시각>`, ④ `04_V-<NNN>_<시각>`, 이미 있으면 `_2`…`_9`). 드라이브에서 지우거나 옮기거나 덮어쓰지 않는다.
- **SPDM 마스터 루트(대시보드 `SIMDASH_SCX_DRIVE_ROOT`) 안이나 그 상위 폴더 이름과 같은 프로젝트 폴더에는 쓰지 않는다**(양쪽 검사, 예외 설정 없음).
  홈 바로 아래가 걱정되면 `hpc.scx.drive_base: "~/physicsai"`처럼 하위 폴더를 쓴다.
- 흐름: 입력 폴더 직속 `*.rad`·`*.inc`·`*.csv`를 대시보드 업로드 대기열로 올림(관리 › 업로드 대기열에 출처 "PhysicsAI") → 제출 →
  상태 조회(`hpc.scx.poll_interval_s`) → 결과(`hpc.transfer.collect_patterns`)를 relay로 내려받아 AI 루트의 결과 폴더에 저장(`.part` → sha256 확인 → 최종 이름).

### 16.1 켜는 순서

1. **대시보드 쪽**(대시보드 관리자): SCX 드라이브 모드(`SIMDASH_DRIVE_GATEWAY=scx`), 드라이브 쓰기(`SIMDASH_DRIVE_WRITES_ENABLED=true` + SPDM 루트),
   어댑터 v0.3.0 이상(잡 API), relay 켜기 `SIMDASH_SCX_RELAY_ENABLED=true`, 비밀 파일 `SIMDASH_SCX_RELAY_SECRET_FILE`(대시보드 문서 `docs/features/scx-relay.md`).
2. **공유 비밀 파일 만들기**(한 번, 두 앱이 같은 값): PowerShell에서 값을 화면에 찍지 않고 바로 파일로 쓴다.
   ```powershell
   # PhysicsAI 런타임 비밀 폴더(git 폴더 설치 = <git>\.runtime\secrets, 묶음 설치 = <install_root>\secrets)
   $dst = "<런타임>\secrets\scx_relay_key"
   $b = New-Object byte[] 48; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
   [IO.File]::WriteAllText($dst, ([Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_')))
   icacls $dst /inheritance:r /grant:r "${env:USERNAME}:R" "SYSTEM:F"   # 작업 스케줄러 실행 계정이 다르면 그 계정에 R
   # 같은 파일을 대시보드 비밀 폴더에 복사하고 SIMDASH_SCX_RELAY_SECRET_FILE에 그 절대 경로를 넣는다
   ```
   파일 내용은 한 줄 base64url 43~128자. 값은 어떤 문서·git·설정 파일·채팅에도 두지 않는다. 바꾸면 두 앱을 모두 다시 시작한다.
3. **PhysicsAI 설정**(`platform.yaml`): `hpc.gateway: scx`, `hpc.scx.relay_url: "http://127.0.0.1:<대시보드 백엔드 포트>"`,
   `hpc.scx.appliance`·`hpc.scx.version`(필수, 서버 확인 E4-11-1·2). `hpc.scx.secret_file`을 비우면 `<런타임>\secrets\scx_relay_key`를 읽는다.
   (`deploy\setup.ps1`은 `hpc.scx` 절이 없을 때 예시 기본 절만 보충하고 `gateway`는 바꾸지 않는다.)
4. API·워커 재시작 후 확인: 상태 화면(`GET /status`)의 HPC가 `SCX(대시보드 연결)`이고 configured=true. 비밀 파일이 없거나 형식이 틀리면
   configured=false와 파일 경로만 보인다(값은 보이지 않음). 관리 › 설정 조회에는 `hpc.scx.secret = {path, present}`만 나온다.

### 16.2 결과 모름(확인 필요)

제출 응답을 잃으면(relay `SUBMISSION_UNKNOWN`, 또는 같은 request_id replay를 다 써도 응답 없음) 그 run은 `UNKNOWN`(확인 필요)이 되고
작업은 `WAITING_HPC`에 남는다(attention·알림 `HPC_SUBMISSION_UNKNOWN`). **자동 재제출·자동 취소는 하지 않고** 남은 run은 제출하지 않는다.
SCX 화면에서 그 잡 폴더(작업 HPC 행의 `remote_dir`)의 잡을 확인한 뒤 `POST /jobs/{id}/hpc-jobs/{hid}/resolve`로 조치한다(작업 등록자 power 이상 또는 전역 관리자):
`recheck`(같은 request_id로 다시 확인) · `attach`(SCX에서 찾은 잡 ID 연결) · `mark_not_submitted`(제출 안 됨 → 그 run 실패, ①은 "실패 run 다시 제출"로 새 폴더에 재제출).
**SCX에 잡이 실제로 있는데 '제출 안 됨'으로 표시하면 같은 해석이 두 번 돌 수 있다(폴더는 따로).** 워커가 제출 도중 멈춘 경우도 housekeeping이 같은 `UNKNOWN`으로 바꾼다.

### 16.3 설정 키(`hpc.scx`, 기본값은 스키마 한 곳)

| 키 | 기본 | 설명 |
|---|---|---|
| `relay_url` | `""`(scx면 필수) | `http://127.0.0.1:<port>`·`http://[::1]:<port>`·`http://localhost:<port>`만(경로·쿼리 없음) |
| `secret_file` | `""` | 비밀 파일 절대 경로(빈 값 = `<런타임>/secrets/scx_relay_key`) |
| `drive_base` | `"~"` | `"~"` 또는 `"~/<상대>"` |
| `home_display` | `/Users/vd.dashboard` | 화면·로그 표시 전용 |
| `appliance` / `version` | `""`(필수) / `"26.1"` | SCX Radioss appliance·버전 문자열(E4-11-1·2). 버전은 작업별 입력(`hpc.version`)이 있으면 덮어씀(D3-68) |
| `ncpu` / `memory_gb` | `16` / `null` | 작업 params `hpc.ncpus`가 있으면 ncpu를 덮어씀(`queue`·`walltime`은 무시) |
| `queue_type` / `run_type` / `mpi` / `single_precision` | `implicit` / `both - use starter and engine files` / `Pure MPI` / `false` | E4-11-10. `mpi` 허용 값: `SMP (default)`·`Pure MPI`(Radioss `-np`)·`Hybrid 2 Threads`·`Hybrid 4 Threads`·`Hybrid 8 Threads`·`auto` — 밖 값은 설정 경고(오류 아님) |
| `poll_interval_s` | `null` | 상태 조회 주기(null = `hpc.poll_interval_s`) |
| `stage_patterns` | `["*.rad","*.inc","*.csv"]` | 올릴 파일(입력 폴더 직속, 대소문자 무시) |
| `list_additional_paths` | `true` | include를 `additional_paths`에 나열(E4-11-4) |
| `max_stage_bytes` / `max_download_bytes` | 20 GiB / 20 GiB | run당 업로드 합계 / 파일당 다운로드 상한 |
| `stage_poll_s` / `stage_timeout_s` | `5` / `7200` | 업로드 대기열 폴링 간격 / 시간 한도 |
| `submit_replay_attempts` / `submit_replay_wait_s` | `3` / `10` | 응답을 잃은 제출의 같은 request_id replay |
| `http_timeout_s` / `transfer_timeout_s` | `30` / `3600` | 요청 1개 / 파일 1개 전송 |
| `collect_max_depth` | `2` | 결과 폴더 하위 탐색 깊이 |
| `health_ttl_s` | `30` | 상태 화면용 relay health 캐시 |

### 16.4 서버 확인 목록(E4-11, 처음 켤 때)

| # | 확인 | 다르면 |
|---|---|---|
| E4-11-1 | Radioss appliance 이름(SCX 화면·HPC_SDK 예제) | `hpc.scx.appliance` |
| E4-11-2 | version 문자열(`2026.1`인지 `Radioss 2026.1`인지) | `hpc.scx.version` |
| E4-11-3 | `input_path` 표기(상대·`~/`·절대) — 시험 폴더 1개로 3가지 | 대시보드 `SIMDASH_SCX_RELAY_JOB_PATH_FORM` |
| E4-11-4 | include(`*.inc`·`RENUM_INIT.csv`)를 `additional_paths`에 꼭 넣어야 하는지 | `hpc.scx.list_additional_paths` |
| E4-11-5 | `run_type` both에서 engine(`_0001.rad`)을 `engine_paths`로 줘야 하는지 | 개발 요청(step 규칙) |
| E4-11-6 | 결과 위치(`output_path` 표기·위치·하위 깊이), relay로 읽히는지 | relay output_rel 변환·`collect_max_depth` |
| E4-11-7 | 상태 문자열 전체(Queued·Running·Completed·Failed·Aborted 외 값) | 개발 요청(상태 표) |
| E4-11-8 | 대기·실행·완료 잡의 terminate 동작과 이후 상태 | 개발 요청(취소 처리) |
| E4-11-9 | 대시보드 어댑터 ≥ 0.3.0·잡 API 노출(relay `/health`의 `job_api`·`adapter_version`) | 어댑터 업데이트 |
| E4-11-10 | `ncpu`·`memory_gb`·`queue_type`·`mpi` 허용 값 | `hpc.scx.*` |
| E4-11-11 | 1 GB 이상 `.rad` 업로드·10 GB h3d 다운로드 시간과 그동안 대시보드 반응 | 대시보드 `SIMDASH_SCX_MAX_CONCURRENCY`·운영 시간대 |
| E4-11-12 | 결과 파일 이름이 `hpc.transfer.collect_patterns`와 맞는지 | `hpc.transfer.collect_patterns` |

### 16.5 실패 코드·문제 해결

| 코드 | 뜻 | 조치 |
|---|---|---|
| `HPC_SUBMIT_FAILED` | relay 연결 실패·잡 API 없음·드라이브 쓰기 꺼짐·확정 제출 실패(이미 제출한 run은 terminate) | 대시보드 relay·SCX 연결·로그 확인 |
| `SCX_STAGE_IN_FAILED` | 업로드 대기열 CONFLICT·FAILED·CANCELLED·PARTIAL·시간 초과(아무것도 제출하지 않음) | 대시보드 업로드 대기열 화면, `stage_timeout_s` |
| `SCX_PATH_NOT_ALLOWED` | 잡 폴더가 SPDM 루트 안이거나 형식 위반 | Study 폴더 이름·`drive_base` |
| `SCX_REMOTE_DIR_EXISTS` | 같은 이름 폴더가 `_9`까지 있음 | 잠시 뒤 다시(시각이 바뀜) |
| `INPUT_INVALID` | 올릴 파일 이름·크기 상한 위반, starter 없음 | 입력 폴더 확인 |
| `HPC_UNREACHABLE` | 상태 조회 실패가 `hpc.max_unreachable_minutes`를 넘음(문구 "대시보드 SCX 연결 확인") | 대시보드 재로그인·relay 확인 |
| 경고 `SCX_SUBDIR_SKIPPED`·`SCX_NOT_SUBMITTED`·`SCX_UNKNOWN_CANCELED` | 하위 폴더 입력 무시·결과 모름으로 남은 run 미제출·결과 모름 행 취소(SCX에서 직접 확인) | 해당 run 다시 제출 |

## 17. ⑥ 플랫폼 내장 최적화(phase3 §18·§22, D3-60·D3-65 — S14 이후 화면 번호는 ⑥, 내부 URL `/stage/5`)

⑤ "플랫폼 내장(쿠션만 가능)" 모드는 HyperStudy 대신 ④ 일괄 예측 체인으로 설계를 검증하며 대리모델(GP·RBF)로 다음 후보를 고른다. mesh_only(쿠션 단독) 템플릿도 동작한다. 원본 최적화 모드는 조립 폴더가 있는 템플릿만(쿠션 단독 템플릿이면 `TEMPLATE_ASSEMBLY_REQUIRED`로 막힘).

### 17.1 런타임 의존성 numpy·scipy

- `pyproject.toml`·`deploy/requirements.lock`에 `numpy==2.4.6`·`scipy==1.17.1`(cp312 win_amd64 wheel, 약 12 MB + 37 MB)이 들어 있다. git 폴더 설치(`setup.ps1`·`update-repo.ps1`)는 ③ 단계 `pip install -r deploy\requirements.lock`에서 사내 pip 설정·프록시로 PyPI에서 함께 받는다(스크립트 변경 없음). 폐쇄망 묶음은 `collect-offline`이 lock을 따라 wheel을 넣는다.
- 설치 확인: `.runtime\venv\Scripts\python.exe -c "import numpy, scipy; print(numpy.__version__, scipy.__version__)"`. 화면 확인: `/status.features.optimize_builtin.enabled` = true. 없으면 그 기능만 꺼지고(`missing`에 `python.numpy`·`python.scipy`) 나머지는 그대로 동작한다. API 프로세스는 numpy를 불러오지 않는다(워커 계산 step 안에서만).
- CPU: 대리모델 적합·후보 탐색은 워커가 슬롯을 잡은 동안 워커 프로세스 안에서 돈다. BLAS·OpenMP 스레드는 `surrogate_opt.blas_threads`(기본 4)와 `worker.max_logical_cores` 중 작은 값으로 제한한다(첫 numpy import 전에 `OMP_NUM_THREADS`·`OPENBLAS_NUM_THREADS`·`MKL_NUM_THREADS` 설정). 자유 변수 20개·점 200개 GP 적합이 4스레드에서 약 10~15초.

### 17.2 설정 키(`surrogate_opt`, 기본값은 스키마 한 곳)

| 키 | 기본 | 뜻 |
|---|---|---|
| `enabled` | true | false면 내장 모드 버튼 비활성 |
| `dir_name` | `05_opt/surrogate` | Study 기준 폴더(`SO-001`마다 `opt.json`·`iter_NN/`·`convergence.csv`·`verified_runs.csv`·`summary.json`) |
| `max_variables`·`max_iterations`·`max_candidates` | 20·10·10 | 자유 변수·반복·후보 상한 |
| `default_iterations`·`default_candidates`·`default_tol_rel`·`default_surrogate` | 3·4·0.01·gp | 화면 기본값 |
| `gp_restarts` | 8 | GP 하이퍼파라미터 최적화 시작점 수 |
| `de_maxiter`·`de_popsize` | 200·15 | 후보 탐색(differential evolution) 세대·개체 배수 |
| `fit_timeout_s` | 600 | 반복 1회의 학습+후보 탐색 시간 한도(넘으면 `SURROGATE_TIMEOUT`) |
| `blas_threads` | 4 | 워커 안 numpy 스레드 상한(바꾸면 워커 재시작 뒤 적용) |

### 17.3 실패 코드

| 코드(정지 사유) | 뜻 | 조치 |
|---|---|---|
| `TOO_FEW_POINTS` | 유효 run이 max(5, 자유 변수+2)보다 적음 | 탐색 run 수를 늘리거나 변수를 고정 |
| `VERIFY_ALL_FAILED` | 한 반복의 검증 run이 모두 실패(값 없음 포함) | 배치 결과 화면에서 실패 사유 확인 후 ⑤ "이어서 실행" |
| `SURROGATE_TIMEOUT` | 학습·후보 탐색이 `fit_timeout_s` 초과 | `de_maxiter`·`gp_restarts` 낮춤 또는 `fit_timeout_s` 늘림 |
| `BATCH_FAILED`·`ROUND_FAILED` | 검증·탐색 배치 입력 생성 또는 반복 작업 실패 | 원인 해결 후 ⑤ "이어서 실행" |
| `BATCH_OWNED_BY_OPT`(409) | 최적화 소유 배치를 ④에서 일괄 취소·실패만 다시 | ⑤에서 취소·이어서 실행 |

### 17.4 성능 정의·다목적(S17, phase3 §22)

- **성능**은 템플릿 응답 정의(H3D 또는 커브 대표값)이고, ⑥ 설정 화면의 "성능" 표에서 편집해 저장한다. 역할(목적·제약·관찰)은 최적화 설정에만 들어간다. 진행 중 내장 최적화가 쓰는 성능의 정의 변경·삭제는 409 `PERF_IN_USE_BY_OPT`이므로 끝난 뒤 바꾼다(단위만 바꾸기는 허용).
- 다목적(목적 2~3개)은 파레토 전선을 찾는다. 새 설정 키(`surrogate_opt`, 기본값은 스키마 한 곳): `max_objectives` 3 · `max_observe` 10 · `max_extra_points` 10(결과 화면 "선택 해 예측 검증"에 한 번에 보낼 점 수) · `mo_lattice_h2` 10 · `mo_lattice_h3` 6(예측 전선 가중 격자) · `mo_de_maxiter` 100 · `mo_rho` 0.05 · `mo_ref_offset` 0.1(HV 기준점) · `mo_gp_restarts` 4 · `mo_hvi_share_m3` 0.5 · `mo_front_prox_m3` 6.0(3목적 후보 배분). 반복당 시간이 길면 `mo_de_maxiter`·`mo_gp_restarts`를 낮추거나 `fit_timeout_s`를 늘린다.
- 끝난 배치의 H3D 성능은 새 작업 "일괄 예측 성능 다시 추출"(`PB_RESP_EXTRACT`, 대기열 1슬롯)로 채운다. 실행 전 run 폴더의 기존 `H3D_REQUESTS.txt`·`RESPONSES.*`·`responses_pred.csv`는 `_backup`으로 옮겨진다. 해당 run의 h3d가 0개 또는 2개 이상이면 그 run만 건너뛴다(경고).
- 추가 실패 코드: `PERF_UNDEFINED`·`PERF_MISSING_IN_BATCH`(성능 다시 추출 안내)·`BATCH_NOT_DONE`·`NO_H3D_PERFORMANCE`(422)·`SURROGATE_OPT_NOT_DONE`·`SURROGATE_OPT_EXTRA_ACTIVE`(409).

## 18. GPU 조회 진단(phase3 §24, D3-67)

워커의 `GpuMonitor` 스레드가 nvidia-smi를 따로 실행하고 결과를 캐시에 두며, 하트비트와 `/resources`는 그 캐시를 읽는다. nvidia-smi가 느리거나 멈춰도 워커 온라인 판정은 흔들리지 않는다. GPU 줄은 상단 자원 칩 툴팁(`GPU 조회 실패 — …` 또는 `GPU 없음 — …`, 연속 2회 이상이면 `(연속 N회 · 다음 조회 HH:mm:ss)`)과 우측 서랍 "워커 자원"의 회색 줄에도 같은 원인이 나온다.

### 18.1 설정 3개와 조회 간격

`worker.gpu_query_timeout_s`(15) · `worker.gpu_backoff_after`(3) · `worker.gpu_backoff_max_s`(300) — 키 표는 §4.3 worker. 기본 조회 간격은 `worker.resource_sample_interval_s`(base, 10초)이다. 연속 실패 k회 때의 다음 조회 간격은 k < `gpu_backoff_after`이면 base, 그 이상이면 `min(gpu_backoff_max_s, base × 2^(k − after + 1))`이다(`gpu_backoff_max_s: 0`이면 늘리지 않음). 기본값이면 실패가 이어질 때 간격이 10 → 10 → 20 → 40 → 80 → 160 → 300초(이후 300초 유지)로 늘고, 조회가 한 번 성공하면 곧바로 base로 돌아간다.

### 18.2 워커 로그 해석(`<install_root>\logs\worker.log`, 로거 `physicsai_worker`)

상태가 바뀔 때만 1줄을 남긴다. 같은 실패가 이어져도 반복해서 쓰지 않는다(작업 로그·DB에도 쓰지 않음).

| 로그 줄 | 수준 | 뜻 |
|---|---|---|
| `GPU 조회 실패(ERROR): <사유> — 회복될 때까지 같은 실패는 기록하지 않습니다` | WARNING | 정상이던 조회가 처음 실패. `<사유>`는 아래 §18.3 |
| `GPU 조회 불가(NOT_FOUND): nvidia-smi를 찾지 못했습니다(시도: …)` | INFO | 시작부터 실행 파일을 못 찾음(GPU 없는 PC면 정상) |
| `GPU 조회 상태 변경(NOT_FOUND → ERROR): …` | WARNING | 실패 종류가 바뀜(예: 파일을 찾은 뒤 실행 오류) |
| `GPU 조회 연속 3회 실패 — 조회 간격을 늘립니다(최대 300초)` | WARNING | `gpu_backoff_after`에 도달. 이후 자원 서랍의 `다음 조회` 시각이 점점 멀어짐 |
| `GPU 조회 회복: <GPU 이름> n개(실패 k회, <경과>)` | INFO | 조회 성공, 간격이 base로 복귀 |

### 18.3 `gpu_message` 사유와 nvidia-smi 실패 확인 순서

| 사유 문구 | 의미 |
|---|---|
| `nvidia-smi를 찾지 못했습니다(시도: …)` | `worker.gpu_query` 첫 인자와 `resources.gpu_query_candidates` 후보 모두 없음 |
| `nvidia-smi를 실행하지 못했습니다: <경로> (…)` | 파일은 있으나 실행 불가(권한·손상) |
| `nvidia-smi 응답 시간 초과(N초): <경로>` | `gpu_query_timeout_s` 안에 끝나지 않음(드라이버 정지·GPU 초기화 중·과부하) |
| `nvidia-smi 종료코드 N: …` | 실행은 됐으나 오류 종료(드라이버·GPU 통신 문제) |
| `nvidia-smi 출력에서 GPU 정보를 읽지 못했습니다` | 출력 형식이 `worker.gpu_query` 인자와 맞지 않음 |

확인 순서(워커 실행 계정으로, 일반 PowerShell):
1. 같은 계정에서 `nvidia-smi`를 직접 실행해 정상 출력되는지 본다(작업 스케줄러 계정과 로그인 계정이 다르면 PATH가 다를 수 있다). 못 찾으면 `worker.gpu_query`에 전체 경로를 넣거나 `resources.gpu_query_candidates`를 고친다.
2. 직접 실행이 15초 넘게 걸리면(느린 PC·드라이버 대기) `worker.gpu_query_timeout_s`를 올린다(화면에 바로 반영되지 않으므로 다음 조회까지 기다린다). 직접 실행은 빠른데 시간 초과가 나면 워커 계정 환경 차이를 의심한다.
3. 종료코드가 나오면 `nvidia-smi -q`로 드라이버·GPU 상태를 보고, 다른 프로세스(원격 데스크톱 세션·다른 서비스)가 GPU를 점유하는지 확인한다.
4. 출력 형식 사유면 `worker.gpu_query`가 `--query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits` 형식인지 확인한다.
5. 고친 뒤에는 워커 재시작 없이도 다음 조회에서 회복 로그 1줄(`GPU 조회 회복`)이 남는다. 확인 후 임시로 바꾼 설정은 원복한다.

GPU가 없는 서버라면 `NOT_FOUND`가 정상이다(칩은 `GPU —`). 조회가 실패해도 예측·학습 작업은 막히지 않는다(자원 표시와 환경 점검 `gpu.detect`에만 영향).

## 19. ① 플랫폼 DOE 생성(phase3 §23, D3-66)

①-3 학습 DOE 생성의 기본 방식은 `platform`(플랫폼 생성: run마다 SimLab·HyperMesh 입력 생성을 최대 M개 동시에 실행)이고, `원본 HyperStudy(호환)`는 기존 hstbatch 동작 그대로이다. 설정 4개는 §4.3 train_data(`doe_generator_default`·`platform_parallel_default`·`platform_max_runs`·`platform_run_root`).

- 동시 실행 수는 화면 입력(1~`train_data.max_multi_execution`)이며 라이선스 동시 수는 자동 감지하지 않는다. 동시 실행 중 라이선스 오류가 나면(step 로그에서 `licens` 검색) 동시 수를 낮춰 재시도한다 — 실패한 run만 다시 만든다. 메모리 한도에 닿으면 `RESOURCE_LIMIT`(`worker.max_memory_gb`, 모든 자식이 작업 1개분 한도를 나눠 쓴다).
- 실패 처리: 기본은 일부 run 실패 시 작업 실패 `GEN_PARTIAL_FAILED`(재시도 = 실패·미완료 run만), 화면 체크 "실패한 run이 있어도 성공한 run으로 DOE 완료"를 켜면 성공 run만 등록하고 경고 `PARTIAL_OUTPUT`.
- 생성 폴더는 `<DOE>/{platform_run_root}/run__NNNNN/{m_1,m_2,m_3}`이고 `train_data.run_dir_glob`과 맞아야 한다. HyperStudy 전용 파일(유형 json·include TCL·런처·`INPUT_HST_RUN.json`)은 만들지 않는다.
- 기능 판정 `features.train_doe_platform` = 템플릿 `geom_update` + `altair.simlab_path`(`commands.mesh`가 `{include_tcl}`·`{hw}`를 쓰면 `resources.hypermesh_include_tcl`·`altair.hw_exe_path`도). HyperStudy 자원은 필요 없다.

## 부록 C. 코드와 문서의 차이(2026-10-09 확인, HEAD 56801e1 기준 갱신)

| # | 내용 | 영향·대응 |
|---|---|---|
| C-1 | (해소, C23) `server.base_path`·`hpc.transfer.stage_in`·`hpc.adapter.module`은 예약(미사용) 키로 정리 — 예시에서 제거, 값이 있으면 경고. 경로 `/physicsai`는 코드 고정 | §4.4 |
| C-2 | (해소, C26) 회전 파일 로그 `logging.dir`·`max_mb`·`backups` 추가 | §12.1 |
| C-3 | (해소, C24) `commands_log_error_patterns`는 계약대로 edspy step에만 적용 | – |
| C-4 | 재시도 API(`POST /jobs/{id}/retry`)와 Study 보관 API(`POST /studies/{id}/archive`)는 있으나 화면에 버튼이 없다 | 사용자는 같은 버튼을 다시 눌러 새 작업을 만든다(실패 step부터 재개되지 않음). 보관은 API로만 |
| C-5 | 예시 YAML과 코드 기본값이 다른 키: `commands.*`(코드 null), `worker.gpu_query`(코드 null), `hpc.command.state_map`(코드 `{}`), `allowed_executables`·`submit`·`status`·`cancel`(코드 빈 값). 키 누락은 이제 오류가 아니라 기능 비활성+경고(C25) | 예시 블록 전체 복사 권장(§4.1·§4.4) |
| C-7 | (해소, C22) `deploy.json`의 `backend_port` 삭제 — 포트는 `platform.yaml` `server.port` 하나 | §2.3 |
| C-6 | 자식 환경 허용목록에 `CUDA_VISIBLE_DEVICES`가 추가로 있다(B19 목록에 없음) | 영향 없음(GPU 선택 전달) |
