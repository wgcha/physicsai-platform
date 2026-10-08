# 계약: PhysicsAI 플랫폼 1차

- 상태: 확정 (2026-10-08) — 구현 전 계약. 미확정 항목은 §19에 모은다
- 대상: Impl-Backend, Impl-Frontend, Verifier. **이 문서만으로 구현·검수할 수 있게** 쓴다. 다른 저장소 코드는 근거로만 인용하고 import하지 않는다
- 근거
  - 기존 초안(대시보드 통합 전제): `physicsai/docs/contracts/physicsai-jobs.md`(2026-10-07) — 상태 머신·워커 프로토콜·명령 규약·HpcJobGateway·설정 스키마를 이 문서로 옮기며 고쳤다. 이 문서가 우선한다
  - 원본 데스크톱 앱 `OPEN_SOURCE_physics_ai_platform` Ver.0.0.6(이하 "원본"). 명령 인용은 `파일:줄`로 표기
  - 대시보드 저장소 `wgcha/scx`, 브랜치 `claude/scx-drive`(이하 "대시보드"). 인증 인용은 `파일:줄`로 표기
- 결정 기록: [../decisions.md](../decisions.md), 사용자 현장 확인: [../e2e-checklist.md](../e2e-checklist.md)

---

## 1. 한 줄 요약

대시보드와 **같은 Windows Server PC**에서 도는 **독립 플랫폼**(React 프런트 / FastAPI 백엔드 / 별도 워커 / 전용 PostgreSQL DB)이다. 접속은 대시보드와 같은 주소의 `/physicsai/` 하위 경로이고 **대시보드 로그인 쿠키를 그대로 받아 대시보드에 세션을 확인**한다. 1차는 **③ 데이터셋·모델**과 **④ 단일 예측**, 그리고 이를 돌리는 **대기열(로컬 슬롯 1개 FIFO)·워커(Windows Job Object)·알림·공통 셸**을 만든다. 학습 자체는 사용자가 HPC에서 직접 하고, 플랫폼은 학습 패키지를 내보내고 결과 모델 폴더를 등록·평가한다.

---

## 2. 용어

| 용어 | 뜻 |
|---|---|
| 대시보드 | 기존 사내 해석 대시보드(Analysis Canvas, `wgcha/scx`). 로그인·프로젝트·멤버십의 원천 |
| AI 루트 | 산출물을 두는 유일한 폴더(설정 `storage.ai_root`, 임시 예 `E:\shared\AI_WORK`). SPDM master 밖 |
| Study | PhysicsAI 작업 단위. 대시보드 프로젝트 1개에 속하고(`project_id`) AI 루트 아래 폴더 1개(`<ai_root>/<folder_name>/`)를 가진다 |
| 단계(stage) | ① 학습데이터 생성 ② 데이터 정리 ③ 데이터셋·모델 ④ 단일 예측 ⑤ 최적화. 1차는 ③④만 동작 |
| 하위 단계 | ③-1 데이터셋 생성 ③-2 학습 패키지 내보내기 ③-3 HPC 학습(플랫폼 밖) ③-4 모델 등록 ③-5 평가·Final 지정 |
| 작업(job) | 실행 버튼 1번으로 만든 요청 1건(`jobs`). 단계 명령(step)의 체인 |
| 단계 명령(step) | 작업 안의 외부 프로그램 실행 1회 또는 내부 처리 1회(`job_steps`) |
| 레인(lane) | `SLOT`(로컬 슬롯 필요, 외부 프로그램 실행) / `LIGHT`(슬롯 불필요, 파일 복사·검증·파싱만) |
| 슬롯 | 로컬 실행 권한. 전역 1개. `SLOT` 레인 작업만 잡는다 |
| 워커 | `python -m physicsai_worker`로 뜨는 별도 프로세스. API 프로세스는 외부 프로그램을 실행하지 않는다 |
| 데이터셋 | ③-1 결과. 학습용(train)·평가용(eval, 홀드아웃) `.psdata` 2개와 분할 기록(`datasets`) |
| 모델 | ③-4에서 등록한 `.psmdl` + `.pscfg` + 학습 로그 묶음(`models`) |
| Final 모델 | Study당 1개, 사용자가 지정. ④ 예측의 기본 모델 |
| 파라미터 세트 | ④용 파라미터 정의(이름·공칭·하한·상한)·학습 샘플값·예측 입력 파일 묶음. 폴더 경로로 등록(`param_sets`) |
| 최근접 run | ④ 입력값과 정규화 거리가 가장 작은 학습 샘플 run |
| 학습 범위 밖 | ④ 입력값 중 하나라도 파라미터 [하한, 상한] 밖 |
| pscfg | PhysicsAI 학습 설정 파일. **pickle** — 플랫폼은 열지 않는다 |
| fake tools | Altair 없는 Linux에서 시험하려고 만든 가짜 edspy/SimLab/hw/qsub 스크립트(§18) |

단위: **mm-ton-s**(길이 mm, 질량 ton, 시간 s, 응력 MPa, 힘 N, 에너지 mJ, 밀도 ton/mm³). 플랫폼은 단위를 **변환하지 않는다**. 표·축 라벨에는 파라미터 세트에 적힌 단위 문자열을 그대로 표시하고, 없으면 빈칸.

---

## 3. 범위

### 3.1 1차 범위

1. 공통 셸: 경로바, 5단계 스텝퍼, 좌측 작업영역, 우측 공통 패널(대기열·워커 자원·모델 목록/Final), 알림(토스트·벨·이력)
2. 대시보드 로그인 공유(§5), 프로젝트 선택(대시보드 프로젝트 목록), Study 생성·보관
3. 대기열: 전역 슬롯 1개 FIFO, 대기 순번, **관리자 전용** 순서 변경·취소, 재시도(실패 step부터)
4. 워커: lease 기반 claim/renew/release, 워커 사망 시 `INTERRUPTED`, Windows Job Object 자원 제한, 비Windows 대체 구현
5. ③-1 데이터셋 생성(10% 홀드아웃, 고정 seed), ③-2 학습 패키지 내보내기, ③-3 안내 문구, ③-4 모델 폴더 등록(플러그형 로그 파서), ③-5 평가(`--score`)와 Final 지정
6. ④ 파라미터 세트 등록, 예측 입력 확인(학습 범위·최근접 run), 예측 체인 실행, 결과(컨투어 미리보기 출력·커브·응답값 표)
7. `HpcJobGateway`(none|command|adapter) 인터페이스와 none·command 구현(가짜 도구로 시험). 기본 `none`. ④ "PBS 검증 해석"은 `none`이면 비활성
8. 개발 실행 스크립트(Windows `.ps1`, Linux `.sh`), Alembic 초기 migration, 설정 예시
9. 자동 시험(Altair 없는 Linux) + 사용자 E2E 체크리스트

### 3.2 2차(1차에서는 화면에 단계 표시와 비활성 안내만)

- ① 학습데이터 생성, ② 데이터 정리, ⑤ 최적화. 스텝퍼에 칸은 보이되 클릭하면 "2차에서 제공 예정" 안내만 표시
- PBS 실제 연동(사내 명령 확인 후 `config`의 템플릿만 교체), 회수 모드 `shared_folder`·`drive`
- 대시보드 Case 결과를 학습 데이터로 가져오기, ① 이력과 ④ 파라미터 연동
- 오프라인 wheel 묶음·`deploy.bat`·Windows 서비스 등록·Caddy 운영 설정 반영
- `.pscfg` 템플릿 생성 기능(1차·2차 모두 계획 없음, 별도 결정 필요)

### 3.3 비범위

- 플랫폼이 학습(`--train`)을 실행하거나 HPC 학습 로그를 실시간으로 받는 일
- `.pscfg`·`.psmdl`·`.psdata` 업로드(브라우저 → 서버). 파일은 **폴더 경로 지정**으로만 들어온다
- 플랫폼 프로세스(API·워커)가 pickle(`.pscfg`)을 여는 일
- SPDM master에 쓰기(읽기도 1차에는 없음)
- 다중 슬롯·원격 워커(스키마는 막지 않지만 구현·검증하지 않는다)
- 모바일 UI
- 작업 실행 시간 한도(없음. 오래 걸리면 관리자가 수동 취소)

---

## 4. 아키텍처

### 4.1 구성

```text
Browser ── https://<대시보드 주소>/physicsai/...  (같은 origin → 대시보드 세션 쿠키가 함께 감)
   │
Caddy ─┬─ /api/*, /assets/*, 나머지 ─────────────▶ 대시보드(기존)
       ├─ /physicsai/api/* ──────────────────────▶ PhysicsAI 백엔드 FastAPI 127.0.0.1:8100
       └─ /physicsai/*     ──────────────────────▶ PhysicsAI 프런트 정적 파일(Vite build, base=/physicsai/)

PhysicsAI 백엔드 ──(세션 확인: GET /api/auth/me, 프로젝트: GET /api/projects)──▶ 대시보드 127.0.0.1:8000
       │  입력 검증·권한·작업 생성·조회만. 외부 프로그램 실행 안 함
       ▼
PostgreSQL (같은 서버, 별도 DB `physicsai`, Alembic)
       ▲  claim/renew/release (CAS)
       │
physicsai_worker (별도 프로세스, 같은 PC, 1개)
  ├─ SLOT 실행기 ─ Job Object ─ edspy.bat / SimLab.bat / hw.exe
  ├─ LIGHT 실행기 ─ 파일 복사·검증·로그 파싱(외부 프로그램 없음)
  ├─ HPC 폴러/회수기 ─ HpcJobGateway (1차 기본 none)
  ├─ 하트비트·자원 스냅샷(CPU/RAM/GPU)
  └─ 리퍼·알림 보관기간 정리
```

### 4.2 배포·경로

- 1차 운영 형태는 **개발 실행 스크립트**(§4.6)뿐이다. 운영 Caddy 설정·서비스 등록·오프라인 설치는 2차. 단 경로 구조는 처음부터 `/physicsai/` 기준으로 만든다.
- 백엔드는 모든 라우트를 `/physicsai/api` 접두로 등록한다(Caddy가 접두를 **벗기지 않는다**). 개발·운영에서 같은 경로.
- 프런트는 Vite `base: "/physicsai/"`, 라우터 basename `/physicsai`. API 호출은 상대경로 `/physicsai/api/...`.
- 대시보드 쪽 Caddy 변경은 §20 대시보드 측 요구사항 D1.

### 4.3 프로세스 규칙

- API 프로세스는 Altair 실행 파일·`subprocess`를 실행하지 않는다(정적 시험 V-SEC-3). 예외: 없음.
- 워커는 `subprocess.Popen(argv_list, shell=False)`만 쓴다. 문자열 명령·`shell=True` 금지.
- 워커는 PC당 1개: `worker.state_dir/physicsai-worker.lock` 비차단 배타 잠금(Windows `msvcrt.locking`, POSIX `fcntl.flock`) 실패 시 기동 거부(종료코드 2).
- DB는 PostgreSQL 전용. DuckDB·SQLite 미사용(시험도 PostgreSQL).

### 4.4 저장소 구조(예정)

```text
physicsai-platform/
  pyproject.toml                  # Python 패키지 정의(backend·worker 공용). Impl-Backend 소유
  backend/
    physicsai_core/               # API·워커 공용: 설정, 경로, DB 테이블·저장소, 상태 머신, 명령 템플릿, 파서, HPC 게이트웨이
    physicsai_api/                # FastAPI 앱, 인증, 라우터, 스키마, 서비스
    tests/                        # 백엔드 시험 + fake_tools/
    openapi.json                  # 백엔드가 생성·커밋(프런트 타입 원천)
  worker/
    physicsai_worker/             # 워커 루프, 단계 실행기, 자원 제한기(limiter)
    tests/
  migrations/                     # alembic.ini, env.py, versions/0001_initial.py
  frontend/                       # React + Vite + TS
  config/
    platform.example.yaml         # 설정 스키마 예시(커밋). 실제 platform.yaml은 .gitignore
  scripts/                        # dev-*.ps1 / dev-*.sh (개발 실행·DB 초기화·전체 시험)
  docs/
```

### 4.5 의존성

- Python 3.11+(개발 확인 3.13). 런타임: `fastapi`, `uvicorn`, `pydantic>=2`, `sqlalchemy>=2`(Core만, ORM 세션 미사용), `psycopg[binary]>=3`, `alembic`, `pyyaml`, `httpx`(대시보드 호출), `psutil`(자원 스냅샷·비Windows 제한기). 시험: `pytest`, `pytest-timeout`. 버전은 `pyproject.toml`에 하한, 잠금 파일은 2차(오프라인 wheel과 함께).
- Windows Job Object는 표준 `ctypes`(kernel32)로 호출한다. `pywin32` 미사용.
- 프런트: `react`, `react-dom`, `react-router-dom`, `typescript`, `vite`, `@vitejs/plugin-react`. 시험: `vitest`, `@testing-library/react`, `jsdom`. 타입 생성: `openapi-typescript`. 차트 라이브러리는 쓰지 않고 loss 곡선은 SVG 컴포넌트로 그린다(폐쇄망 반입 부담 최소화).

### 4.6 개발 실행

| 스크립트(.ps1 / .sh 쌍) | 동작 |
|---|---|
| `scripts/dev-db-init` | `PHYSICSAI_DATABASE_URL`의 DB에 `alembic upgrade head` |
| `scripts/dev-backend` | `uvicorn physicsai_api.main:app --host 127.0.0.1 --port 8100` |
| `scripts/dev-worker` | `python -m physicsai_worker` |
| `scripts/dev-frontend` | Vite dev server `127.0.0.1:5174`, proxy `/physicsai/api` → `127.0.0.1:8100` |
| `scripts/test-all` | 백엔드·워커 pytest + 프런트 vitest + 타입 검사. PG가 없으면 `PG_BIN`(예 `/usr/lib/postgresql/16/bin`)으로 임시 클러스터를 `initdb`해서 씀 |

개발 시 로그인: 대시보드 dev(`127.0.0.1:5173`)에 로그인하면 쿠키가 호스트 `127.0.0.1`에 저장되고, 쿠키는 포트를 구분하지 않으므로 `127.0.0.1:5174/physicsai/`에도 전송된다(SameSite=Strict는 포트와 무관한 same-site 판정). 호스트 이름은 둘 다 `127.0.0.1`로 맞춘다(`localhost`와 섞지 않는다).

환경변수: `PHYSICSAI_CONFIG`(설정 파일 경로, 기본 `config/platform.yaml`), `PHYSICSAI_DATABASE_URL`, `PHYSICSAI_PROFILE`(`dev`|`prod`, 설정 `profile`보다 우선), `PHYSICSAI_HPC_GATEWAY`(설정 `hpc.gateway`보다 우선).

---

## 5. 인증 연동(대시보드 로그인 공유)

### 5.1 대시보드 인증 방식(코드 근거)

| 항목 | 내용 | 근거(대시보드 `backend/app/…`) |
|---|---|---|
| 세션 쿠키 이름 | `analysis_canvas_session` | `security.py:45` |
| 쿠키 속성 | `httponly=True`, `samesite="strict"`, `path="/"`, `secure=AUTH_COOKIE_SECURE`, `max_age=AUTH_TOKEN_TTL_MINUTES×60`(기본 480분) | `routers/security.py:278-286`, `config.py:288,298` |
| 토큰 형식 | `base64url(JSON{sub,iat,exp}).base64url(HMAC-SHA256(AUTH_SECRET_KEY))` — 서버 상태 없는 서명 토큰 | `security.py:136-144`, 검증 `security.py:147-163` |
| 요청 인증 | `Authorization: Bearer <token>` 우선, 없으면 쿠키 값 | `security.py:185-196` |
| 사용자 로드 | 매 요청 `users` 테이블에서 `account_status`(PENDING/ACTIVE/SUSPENDED)·`is_global_admin`·`is_active` 재조회 | `security.py:166-182` |
| 인증 모드 | `AUTH_MODE = disabled | password | oidc`. `disabled`면 고정 주체 `local-admin`(전역 관리자) | `config.py:281-283`, `security.py:186-189` |
| 상태 차단 | PENDING은 `/api/auth/me` 등 일부만 허용, SUSPENDED는 403 `AUTH_ACCOUNT_SUSPENDED` | `security.py:38`, `security.py:307-349` |
| 내 정보 API | `GET /api/auth/me` → `{id, username, display_name, employee_id, account_status, is_global_admin, memberships:[{project_id, role}], company_permissions, role}` | `routers/security.py:311-334` |
| 프로젝트 역할 | `general | power | admin`(프로젝트 멤버십). 전역 관리자는 모든 프로젝트에서 `admin`으로 취급 | `access_policy.py:13`, `access_policy.py:307-316` |
| 비멤버 권한 | 멤버가 아니어도 `company.dashboard.view`, `project.data.view`, `report.export` | `access_policy.py:100-102`, `access_policy.py:284-291` |
| 프로젝트 목록 | `GET /api/projects` → `[{id, name, product_name, description, created_at, selection_metadata}]`, 필요 권한 `project.data.view`(모든 ACTIVE 사용자) | `adapters/http/routers/projects.py:18-23` |
| 멤버 목록 | `GET /api/projects/{id}/members`는 `project.member.manage` 필요 → **PhysicsAI는 사용하지 않는다** | `adapters/http/routers/project_memberships.py:38-41,83-88` |
| 관리형 로컬 실행의 세션 introspection 패턴 | 외부 프로세스가 단기 세션 토큰을 대시보드에 제시 → 대시보드가 토큰 해시·만료·사용자 재조회·ACTIVE 확인 후 **행위자와 작업 문맥을 서버가 확정**해 돌려줌 | `services/managed_local_execution.py:94-113`(세션 발급), `:194-210`(`_authenticate_session`), `:234-253`(`authorize_device`), `local_runner/README.md:40-46` |

### 5.2 PhysicsAI의 세션 검증 흐름

관리형 로컬 실행과 같은 원칙(**신원은 매번 대시보드가 확정, 클라이언트가 보낸 신원 정보는 믿지 않음**)을 따르되, 새 토큰을 발급하지 않고 **브라우저가 이미 가진 대시보드 세션 토큰을 대시보드의 `/api/auth/me`로 introspect**한다. 이 방식은 대시보드 코드 변경 없이 동작한다.

```text
1. 브라우저 → /physicsai/api/... (쿠키 analysis_canvas_session 자동 첨부)
2. 백엔드 의존성 get_principal():
   a. token = request.cookies[auth.cookie_name]; 없으면 401 AUTHENTICATION_REQUIRED
      (Authorization: Bearer 헤더도 허용 — 시험·도구용)
   b. 캐시 조회: key = sha256(token), TTL auth.cache_ttl_s(기본 30초), 최대 1000개 LRU. 실패 응답은 캐시하지 않음
   c. GET {auth.dashboard_internal_url}{auth.introspection_path}   (기본 http://127.0.0.1:8000/api/auth/me)
      헤더: Authorization: Bearer <token>, X-Request-Id: <요청 id>
      타임아웃 auth.timeout_s(기본 3초), 재시도 없음
   d. 응답 매핑:
      200 + account_status=="ACTIVE"           → Principal 생성
      200 + account_status!="ACTIVE"(PENDING)  → 403 ACCOUNT_NOT_ACTIVE
      401                                       → 401 AUTHENTICATION_REQUIRED
      403 (AUTH_ACCOUNT_SUSPENDED 등)           → 403 ACCOUNT_NOT_ACTIVE
      503 (AUTH_SETUP_REQUIRED)                 → 503 DASHBOARD_AUTH_UNAVAILABLE
      연결 실패·타임아웃·그 밖의 상태·JSON 형식 오류 → 503 DASHBOARD_UNREACHABLE
3. Principal = {user_id=id, username, display_name, is_global_admin, roles: {project_id: role}}
   (memberships의 role이 general|power|admin이 아니면 무시)
```

- 토큰 값은 로그·DB·응답에 남기지 않는다(캐시 키도 해시). 쿠키를 다시 설정하거나 지우지 않는다(로그아웃은 대시보드에서).
- 대시보드 `AUTH_MODE=disabled`(개발)면 `/api/auth/me`가 `local-admin`·전역 관리자·memberships `[]`를 돌려준다(`security.py:186-189`, `routers/security.py:315`). PhysicsAI는 이를 그대로 전역 관리자로 취급한다.
- 프로젝트 목록 `GET /physicsai/api/projects`는 같은 토큰으로 대시보드 `GET /api/projects`를 호출해 `{id, name, product_name}`만 돌려준다(캐시 30초, 사용자별 키). Study 생성 시 `project_id`가 이 목록에 있어야 한다(없으면 404 `PROJECT_NOT_FOUND`).
- 401을 받은 프런트는 "대시보드에서 로그인하세요" 화면과 `auth.dashboard_public_login_url`(기본 `/`) 링크를 보인다.

### 5.3 권한 매핑

`role(p)` = `is_global_admin`이면 `admin`, 아니면 `roles[p]`(없으면 `None`).

| 동작 | 허용 |
|---|---|
| 조회(프로젝트·Study·작업·로그·산출물·데이터셋·모델·파라미터 세트·대기열·자원·상태) | 로그인한 모든 ACTIVE 사용자(프로젝트 멤버가 아니어도 — 대시보드 `project.data.view` 비멤버 허용과 일치) |
| 실행: Study 생성·수정·보관, 경로 확인, 파라미터 세트 등록, 작업 생성(대기열 등록), 자기 작업 재시도, Final 지정, 모델 보관·이름 변경 | `role(study.project_id) ∈ {power, admin}` |
| 대기열 관리: 순서 변경, 작업 취소(누구의 작업이든, 상태 무관) | **전역 관리자**(`is_global_admin`) — 대기열이 프로젝트를 가로지르는 전역 자원이므로(§19 U10) |
| 남의 작업 재시도 | 전역 관리자 |
| 관리 조회 `/admin/*`(유효 설정, 명령 스냅샷) | 전역 관리자 |
| 알림 조회·읽음 | 본인 것만 |

- 판정 순서: 인증(401) → 대상 존재(404) → 권한(403 `PERMISSION_DENIED`, `required: "power" | "global_admin"`) → 상태(409).
- 권한은 요청마다 introspection 결과(최대 30초 캐시)로 판정한다. DB에 역할을 복제하지 않는다. 작업 행에는 `created_by`(user_id)와 `created_by_name`(표시 스냅샷)만 저장한다.

### 5.4 CSRF

쿠키가 `SameSite=Strict`이고 같은 origin이므로 기본 방어가 된다. 추가로 모든 비GET 요청은 헤더 `X-PhysicsAI-Request: 1`이 있어야 한다(없으면 403 `CSRF_HEADER_REQUIRED`). 프런트 API 클라이언트가 항상 붙인다.

### 5.5 개발·시험 모드

- `auth.mode: dev_static`은 `profile=dev`이고 서버가 `127.0.0.1`에 바인딩될 때만 허용(아니면 기동 거부 `CONFIG_INVALID`). 설정의 `auth.dev_static_principal`을 모든 요청의 주체로 쓴다. Linux 자동 시험과 대시보드 없는 프런트 개발용.
- 자동 시험은 `dashboard` 모드를 **가짜 대시보드**(httpx `MockTransport` 또는 시험 fixture HTTP 서버)로 검증한다: 200 ACTIVE/PENDING, 401, 403, 503, 타임아웃, 잘못된 JSON, 캐시 TTL.

---

## 6. 데이터 모델

### 6.1 공통 규칙

- PostgreSQL 16 기준, DB 이름 `physicsai`(대시보드 DB와 별도), 스키마 `public`. 변경은 Alembic(`migrations/versions/0001_initial.py`가 1차 전체).
- ID: 문자열 UUID4(`VARCHAR(36)`). 시간: `TIMESTAMPTZ`(UTC). 판정용 현재 시각은 **DB 시계**(`now()`)만 쓴다.
- 경로 컬럼(`*_rel`)은 **Study 폴더 기준 상대경로**(`/` 구분). 절대경로는 실행 시 `ai_root/folder_name`과 합성. 사용자가 지정한 원본 경로는 `source_path`(표시·감사용 문자열)로만 저장한다.
- **파일 본문 저장 금지.** DB에 넣는 것은 경로·상태·크기·sha256·수치 요약(점수, loss 배열, 파라미터 정의 수치, 응답값 표)뿐이다. 로그 본문·샘플 표·yaml·json 원문은 파일에만.
- JSON 컬럼은 `JSONB`. 각 JSON 형태는 아래 표에 명시하고 Pydantic으로 검증 후 저장.
- 낙관적 동시성: 갱신 가능한 행은 `version BIGINT`(상태 변경마다 +1).

### 6.2 `studies`

| 컬럼 | 타입·제약 | 설명 |
|---|---|---|
| id | VARCHAR(36) PK | |
| project_id | VARCHAR NOT NULL | 대시보드 `projects.id`(FK 없음 — 다른 DB). 인덱스 |
| folder_name | VARCHAR(64) NOT NULL UNIQUE | `^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$`. 생성 후 불변. `_`로 시작 금지 |
| title | VARCHAR(120) NOT NULL | 표시명(한글 가능) |
| status | VARCHAR NOT NULL | `ACTIVE` \| `ARCHIVED` |
| final_model_id | VARCHAR(36) NULL FK models.id | Final 모델 |
| final_set_by / final_set_at | NULL | |
| ai_root_snapshot | VARCHAR NOT NULL | 생성 당시 `ai_root`(진단용) |
| created_by / created_by_name / created_at / updated_at | | |
| version | BIGINT NOT NULL DEFAULT 1 | |

### 6.3 `datasets` (③-1)

| 컬럼 | 설명 |
|---|---|
| id PK, study_id FK, job_id FK jobs | 만든 `DATASET_CREATE` 작업 |
| source_path | 사용자가 지정한 h3d 폴더(AI 루트 하위, 정규화된 절대경로 문자열) |
| h3d_count / train_count / eval_count | INT |
| holdout_ratio | NUMERIC(4,3), 기본 0.1 |
| seed | BIGINT |
| split_group | `file` \| `parent_dir` |
| options_json | `{extract_faces: bool, extract_mdi: bool, extract_time_history_vectors: bool}` |
| split_rel | `03_dataset/<id>/split.json` |
| train_psdata_rel / train_psdata_size | `03_dataset/<id>/train/dataset.psdata` |
| eval_psdata_rel / eval_psdata_size | `03_dataset/<id>/eval/dataset.psdata` |
| package_rel | NULL → ③-2 완료 시 `03_package/<id>/` |
| status | `BUILDING` \| `READY` \| `FAILED` |
| created_by / created_by_name / created_at | |

### 6.4 `models` (③-4, ③-5)

| 컬럼 | 설명 |
|---|---|
| id PK, study_id FK | |
| name | `^[A-Za-z][A-Za-z0-9_]{0,63}$` |
| version | INT. `UNIQUE(study_id, name, version)`, 같은 이름 등록 시 +1 |
| label | VARCHAR(120) NULL 자유 표시명 |
| dataset_id | FK datasets NULL. 이 모델을 학습한 데이터셋(등록 시 선택, 기본 = Study 최신 READY 데이터셋). 평가는 이 데이터셋의 eval psdata로 한다 |
| source_path | 사용자가 지정한 모델 폴더(표시용) |
| stored_rel | `03_model/models/<id>/` (복사본 위치) |
| psmdl_rel / psmdl_sha256 / psmdl_size | 필수 |
| pscfg_rel / pscfg_sha256 | 필수. **경로·해시만 기록, 열지 않음** |
| log_rel | NULL 가능 |
| log_status | `PARSED` \| `UNRECOGNIZED`(로그는 있으나 형식 미확인) \| `MISSING` |
| log_parser | 일치한 파서 이름 NULL |
| epochs_total / last_epoch | INT NULL |
| final_loss / min_loss | DOUBLE NULL |
| min_loss_epoch | INT NULL |
| loss_curve | JSONB NULL `[[epoch, loss], ...]` 최대 `training_log.max_curve_points`점(다운샘플: 첫·마지막·최소 loss 점 보존, 나머지 균등 간격) |
| eval_status | `NONE` \| `RUNNING` \| `DONE` \| `FAILED` |
| eval_job_id | FK jobs NULL(최신 평가) |
| eval_score | JSONB NULL `{status: "PARSED" \| "UNRECOGNIZED", metrics: {name: number}, score_rel: str}` |
| status | `ACTIVE` \| `ARCHIVED` \| `INVALID`(사용 직전 sha256 불일치 감지) |
| registered_by / registered_by_name / registered_at, row_version | row_version = 낙관적 동시성 값(모델 버전 `version`과 구분) |

### 6.5 `param_sets` (④)

| 컬럼 | 설명 |
|---|---|
| id PK, study_id FK | |
| source_path | 사용자가 지정한 폴더 |
| stored_rel | `04_params/<id>/` (검증 후 복사·정규화본) |
| unit_system | 문자열(기본 `mm-ton-s`) |
| parameters | JSONB `[{name, nominal, min, max, unit}]` (정의 수치 = 요약으로 허용) |
| responses | JSONB `[{name, unit}]` (추출 사양 본문은 파일 `responses.json`에만) |
| sample_count | INT (샘플값 자체는 파일 `samples.csv`에만) |
| sample_has_measured | BOOLEAN — `resp:` 열 존재 여부 |
| cad_file_name / tpl_rel / assem_rel / starter_name | 예측 입력 파일 위치 |
| tpl_params | JSONB `[{var, name, format}]` tpl에서 읽은 변수 대응 |
| is_current | BOOLEAN. Study당 최신 1개 true(부분 unique `UNIQUE(study_id) WHERE is_current`) |
| registered_by / registered_by_name / registered_at | |

### 6.6 `jobs`

| 컬럼 | 타입·제약 | 설명 |
|---|---|---|
| id PK, study_id FK, project_id | | project_id 비정규화 |
| job_type | VARCHAR NOT NULL | §8.1 |
| stage | SMALLINT NOT NULL | 3 또는 4(1차) |
| lane | VARCHAR NOT NULL | `SLOT` \| `LIGHT` |
| state | VARCHAR NOT NULL | §7 |
| attention_code | VARCHAR NULL | `HPC_RUN_FAILED` 등 |
| holds_slot | BOOLEAN NOT NULL DEFAULT false | |
| queue_seq | BIGINT NULL | `QUEUED`일 때만. 시퀀스 `job_queue_seq` |
| next_notified_at | TIMESTAMPTZ NULL | "내 차례 도래" 알림 1회 발송 기록 |
| queued_at / started_at / finished_at | NULL | started_at = 최초 RUNNING |
| current_step_no / progress_pct / progress_label | NULL | progress_pct NULL = 미상 |
| params | JSONB NOT NULL | 검증된 요청(§10.6) |
| result | JSONB NULL | 수치 요약·산출물 id(§8 각 작업) |
| warnings | JSONB NOT NULL DEFAULT '[]' | `[{code, message}]` |
| env_snapshot | JSONB NULL | 첫 RUNNING 시(§11.7) |
| failure_code / failure_message | NULL | message ≤500자 |
| cancel_requested_at / cancel_requested_by | NULL | 취소 플래그(상태 아님) |
| retry_of_job_id / resume_from_step | NULL | |
| lease_owner_id / lease_token / lease_generation / lease_acquired_at / lease_expires_at | | lease_token은 **어떤 API 응답에도 노출 금지** |
| created_by / created_by_name / created_at / updated_at / version | | |

CHECK:
- `lane IN ('SLOT','LIGHT')`, `stage BETWEEN 1 AND 5`
- `holds_slot = (state = 'RUNNING' AND lane = 'SLOT')`
- `(queue_seq IS NOT NULL) = (state = 'QUEUED')`
- lease identity: `lease_owner_id, lease_token, lease_acquired_at, lease_expires_at`가 모두 NULL 또는 모두 NOT NULL이고 `lease_expires_at > lease_acquired_at`
- `lease_token IS NULL OR state IN ('RUNNING','COLLECTING')`

인덱스: `(state, lane, queue_seq)`, `(study_id, created_at DESC)`, `(created_by, created_at DESC)`. 부분 unique: `UNIQUE(study_id, job_type) WHERE state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')` → 위반 시 409 `STUDY_JOB_BUSY`.

### 6.7 `job_steps`

| 컬럼 | 설명 |
|---|---|
| id PK, job_id FK, step_no | `UNIQUE(job_id, step_no)` |
| step_key | §8 표의 키 |
| kind | `LOCAL`(외부 프로그램) \| `INTERNAL` \| `HPC_SUBMIT` \| `HPC_WAIT` \| `COLLECT` |
| needs_slot | `LOCAL`·`HPC_SUBMIT`은 true, `HPC_WAIT`·`COLLECT`는 false, `INTERNAL`은 작업 lane을 따름 |
| state | `PENDING` \| `RUNNING` \| `SUCCEEDED` \| `FAILED` \| `SKIPPED` \| `CANCELED` |
| started_at / finished_at / exit_code / progress_pct / progress_label | |
| command | JSONB NULL `{argv:[...], cwd, env_added:{}}` (실행 직전 확정값. 비밀 없음) |
| log_rel | `logs/<job_id>/step_<NN>_<step_key>.log` |
| outputs | JSONB `{files:[{rel, size, sha256?}], accounting:{peak_memory_bytes, cpu_time_s, cpu_cap_enforced}}` |
| failure_code / failure_message | |

### 6.8 `artifacts`

`id, study_id, job_id NULL, kind, rel_path, size, sha256 NULL, content_type, created_at`. kind = `PREVIEW_JSON` \| `PREVIEW_IMAGE` \| `CURVE_JSON` \| `RESPONSE_TABLE` \| `SCORE_FILE` \| `PACKAGE_COMMANDS` \| `SPLIT_JSON`. 내려받기는 **id로만**(경로 인자 금지). 화면 표시용 작은 파일만 등록하고(`.psdata`·`.psmdl`·`.h3d`는 등록하지 않음, 경로만 표시) 크기 상한 `ui.max_artifact_bytes`(기본 20 MiB).

### 6.9 `notifications`

| 컬럼 | 설명 |
|---|---|
| seq | BIGSERIAL PK (폴링 커서) |
| user_id | 수신자(작업 `created_by`) |
| event | `JOB_STARTED` \| `JOB_SUCCEEDED` \| `JOB_FAILED` \| `JOB_CANCELED` \| `JOB_INTERRUPTED` \| `MY_TURN_NEXT` \| `HPC_COLLECTED` |
| job_id / study_id / project_id | |
| title / body | 한국어, ≤120 / ≤500자 |
| created_at / read_at | read_at NULL = 미읽음 |

인덱스 `(user_id, seq DESC)`, `(user_id) WHERE read_at IS NULL`. 보관 30일(§13).

### 6.10 워커·슬롯·HPC

- `worker_slot`(단일 행 `id=1` CHECK): `holder_job_id NULL, lease_owner_id, lease_token, lease_generation BIGINT NOT NULL DEFAULT 0, lease_acquired_at, lease_expires_at` + 위와 같은 lease identity CHECK. migration이 행 1개를 넣는다.
- `worker_heartbeats`: `worker_id PK, host, pid, app_version, started_at, last_seen_at, effective_limits JSONB, resources JSONB, limiter VARCHAR`.
- `hpc_jobs`: `id, job_id FK, step_id FK, run_key, attempt_no, gateway_mode, external_job_id NULL, submit_argv JSONB, state(SUBMITTING|QUEUED|RUNNING|SUCCEEDED|FAILED|CANCEL_REQUESTED|CANCELED|UNKNOWN|LOST), external_state_raw, exit_code, collect_state(NONE|PENDING|COLLECTING|COLLECTED|FAILED), collected JSONB, submitted_at, last_polled_at, finished_at, collected_at, unknown_count, error_message, version`. `UNIQUE(job_id, run_key, attempt_no)`, 부분 unique `(gateway_mode, external_job_id) WHERE external_job_id IS NOT NULL`.

---

## 7. 작업 상태 머신

### 7.1 상태

| 상태 | 슬롯 | 뜻 |
|---|---|---|
| `QUEUED` | 없음 | 대기. 레인별 `queue_seq` 오름차순 FIFO. 대기 순번 = 같은 레인 QUEUED 중 순위(1부터) |
| `RUNNING` | SLOT 레인이면 **보유** | step 실행 중. 연속된 슬롯 step 사이에 슬롯을 놓지 않는다 |
| `WAITING_HPC` | 없음 | PBS job 진행 중 |
| `COLLECTING` | 없음 | PBS 결과 회수·검증 중 |
| `SUCCEEDED` / `FAILED` / `CANCELED` / `INTERRUPTED` | 없음 | 종료(불변). `FAILED`·`INTERRUPTED`는 `failure_code` 필수 |

- "취소 중"은 `cancel_requested_at IS NOT NULL`인 비종료 작업(표시만).
- 종료 상태 이후 변경은 409 `JOB_TERMINAL`.
- **실행 시간 한도 없음.** `STEP_TIMEOUT` 코드·설정은 두지 않는다.

### 7.2 전이

| # | 전이 | 주체 | 조건·부수효과 |
|---|---|---|---|
| T1 | (생성) → `QUEUED` | API `POST /studies/{id}/jobs` | 사전조건 통과(§8.2). `queue_seq=nextval`. 알림 재계산(§13.2) |
| T2 | `QUEUED` → `RUNNING` | 워커 claim | SLOT: 슬롯 행 CAS + 최소 `queue_seq`. LIGHT: 최소 `queue_seq`(동시 1개). lease 발급, `queue_seq=NULL`, 첫 RUNNING이면 `env_snapshot`. 알림 `JOB_STARTED` |
| T3 | `QUEUED` → `CANCELED` | API cancel(전역 관리자) | 즉시. 알림 `JOB_CANCELED` |
| T4 | `RUNNING` → `RUNNING` | 워커 | 다음 step 진행 |
| T5 | `RUNNING` → `WAITING_HPC` | 워커: `HPC_SUBMIT` 성공 직후 | 같은 트랜잭션에서 슬롯·lease 해제 |
| T6 | `RUNNING` → `SUCCEEDED` | 워커: 마지막 step 성공 | 슬롯 해제(lease CAS 확인). 알림 `JOB_SUCCEEDED` |
| T7 | `RUNNING` → `FAILED` | 워커: step 실패 | 남은 step `SKIPPED`, 슬롯 해제. 알림 `JOB_FAILED` |
| T8 | `RUNNING` → `CANCELED` | 워커: `cancel_requested_at` 감지(≤ `cancel_check_interval_s`) | 실행 중 프로세스 트리 종료(§11.5) 확인 후 슬롯 해제. 알림 `JOB_CANCELED` |
| T9 | `RUNNING`/`COLLECTING` → `INTERRUPTED` | 리퍼 | `lease_expires_at < now()`. `failure_code=WORKER_LOST`, 실행 중 step `FAILED`, 슬롯 회수. 알림 `JOB_INTERRUPTED` |
| T10 | `WAITING_HPC` → `COLLECTING` | HPC 폴러 | 모든 hpc_job 종료, 실패 run 없음 |
| T11 | `WAITING_HPC` + `attention_code=HPC_RUN_FAILED` | HPC 폴러 | 모든 run 종료 + 실패 존재(1차 ④ 검증은 run 1개 → 곧바로 T13) |
| T12 | `WAITING_HPC`/`COLLECTING` → `CANCELED` | API cancel → 폴러 | 비종료 hpc_job마다 gateway `cancel`(실패는 경고) |
| T13 | `WAITING_HPC` → `FAILED` | HPC 폴러 | run 실패(`HPC_RUN_FAILED`) 또는 게이트웨이 연속 실패 `hpc.max_unreachable_minutes` 초과(`HPC_UNREACHABLE`) |
| T14 | `COLLECTING` → `QUEUED` | 회수기 | 회수 완료 + 다음 step `needs_slot=true` → **새 `queue_seq`**로 뒤에 섬. 알림 `HPC_COLLECTED` |
| T15 | `COLLECTING` → `SUCCEEDED` | 회수기 | 남은 step 없음. 알림 `HPC_COLLECTED`, `JOB_SUCCEEDED` |
| T16 | `COLLECTING` → `FAILED` | 회수기 | `COLLECT_FAILED`(3회 재시도 후) |

그 밖의 전이는 저장소 계층이 `IllegalTransition`으로 거부(표 기반 시험 V-SM-1).

### 7.3 대기열 순서 변경(전역 관리자)

`POST /queue/{job_id}/move {position}`(1부터, SLOT 레인 QUEUED만): 한 트랜잭션에서 SLOT 레인 QUEUED 행 전부를 `SELECT … FOR UPDATE`로 잠그고, 원하는 순서대로 `queue_seq=nextval`을 다시 부여한다. 대상이 이미 QUEUED가 아니면 409 `JOB_NOT_QUEUED`. 감사 로그(§17.6)와 알림 재계산.

### 7.4 실패 코드

`EXIT_NONZERO`, `LOG_ERROR_DETECTED`, `OUTPUT_MISSING`, `OUTPUT_TOO_SMALL`, `OUTPUT_LOCKED`(백업 이동 실패), `RESOURCE_LIMIT`(Job 메모리 한도), `JOB_OBJECT_ASSIGN_FAILED`, `EXECUTABLE_MISSING`, `TEMPLATE_NOT_CONFIGURED`, `INPUT_INVALID`, `INPUT_CHANGED`(등록 후 sha256 불일치), `HPC_SUBMIT_FAILED`, `HPC_RUN_FAILED`, `HPC_UNREACHABLE`, `COLLECT_FAILED`, `WORKER_LOST`, `CONFIG_INVALID`, `INTERNAL_ERROR`.

---

## 8. 작업 유형과 단계 체인

### 8.1 목록(1차)

| job_type | 단계 | lane | 화면 버튼 | step 체인 |
|---|---|---|---|---|
| `DATASET_CREATE` | ③-1 | SLOT | "데이터셋 생성" | DS_SCAN → DS_YAML → EDSPY_DATASET_TRAIN → EDSPY_DATASET_EVAL → DS_REGISTER |
| `PACKAGE_EXPORT` | ③-2 | LIGHT | "학습 패키지 내보내기" | PKG_COPY → PKG_TEXT |
| `MODEL_REGISTER` | ③-4 | LIGHT | "모델 등록" | MR_VALIDATE → MR_COPY → MR_PARSE_LOG → MR_REGISTER |
| `EVALUATE` | ③-5 | SLOT | "평가" | EV_PREP → EDSPY_SCORE → EV_PARSE |
| `PREDICT` | ④ | SLOT | "예측 실행" | PR_PREP → TPL_RENDER → GEOM_UPDATE → MESH → RAD_ASSEMBLE → EDSPY_PREDICT → CONTOUR_PREVIEW → CURVE_PICK → RESPONSE_EXTRACT → RESPONSE_TABLE |
| `PREDICT_VERIFY` | ④ | SLOT | "PBS 검증 해석" | PV_PREP → HPC_SUBMIT → HPC_WAIT → COLLECT → PV_EXTRACT → PV_TABLE |

파라미터 세트 등록(④)은 작업이 아니라 동기 API(§10.4, 파일이 작음). ③-3은 화면 안내 문구뿐.

### 8.2 사전조건(없으면 409 `PREREQUISITE_MISSING` + `missing:[...]`)

| 작업 | 사전조건 |
|---|---|
| 모든 작업 | Study `ACTIVE`(아니면 409 `STUDY_ARCHIVED`), 설정 유효(아니면 503 `CONFIG_INVALID`) |
| `DATASET_CREATE` | `params.input_path`가 AI 루트 하위 폴더(§17.3) |
| `PACKAGE_EXPORT` | `READY` 데이터셋 |
| `MODEL_REGISTER` | `params.model_path`가 AI 루트 또는 `storage.allowed_import_roots` 하위 폴더 |
| `EVALUATE` | `ACTIVE` 모델 + 모델의 `dataset_id`가 `READY` |
| `PREDICT` | 파라미터 세트(`is_current` 또는 지정) + `ACTIVE` 모델(기본 Final, 없으면 409 `FINAL_MODEL_REQUIRED`) |
| `PREDICT_VERIFY` | `SUCCEEDED` PREDICT 작업 + `HpcJobGateway.availability().configured`(아니면 409 `HPC_NOT_CONFIGURED`) |

### 8.3 공통 실행 규약

- **기존 산출물 처리**: step이 쓸 파일·폴더가 이미 있으면 삭제하지 않고 `<study>/_backup/<UTC yyyyMMddTHHmmssZ>_<job_id>/<원래 상대경로>`로 `os.replace` 이동 후 실행. 이동 실패 → step `FAILED` `OUTPUT_LOCKED`(파일명 포함). 플랫폼 코드에는 사용자 산출물 삭제 호출이 없다(자기 임시 폴더 `<study>/logs/<job_id>/tmp/` 예외, 정적 시험 V-CMD-7). `_backup`은 자동 삭제하지 않는다.
- 로그: stdout+stderr 병합, `encoding="utf-8", errors="replace"`, 줄 단위로 step 로그와 `logs/<job_id>/job.log`에 기록.
- 오류 감지 정규식(원본 `1_CREATE_TRAINING_DATA/FUNC/2_run_hst_gen_rad_input.py:65-67`에서 이식, IGNORECASE): `^\s*\d+\s+Error\s*:|Traceback \(most recent call last\):|^\s*\[ERROR\]`. edspy step에 적용, 일치하면 종료코드 0이어도 `LOG_ERROR_DETECTED`. 설정 `commands_log_error_patterns`로 교체 가능.
- 진행률: 작업 진행률 = step 가중치 합산. 외부 프로그램이 진행률을 내지 않으면 step은 `progress_pct=NULL`(막대 indeterminate) + 경과 시간 라벨.
- 사용 직전 무결성: 모델 `.psmdl`·`.pscfg`는 EVALUATE·PREDICT 시작 시 sha256 재계산해 DB와 비교, 다르면 모델 `INVALID` + step `FAILED` `INPUT_CHANGED`.

### 8.4 ③-1 `DATASET_CREATE`

요청 `params`: `{input_path: str, holdout_ratio?: 0.05~0.5 (기본 설정값 0.1), seed?: int (기본 설정값), split_group?: "file"|"parent_dir", options?: {extract_faces, extract_mdi, extract_time_history_vectors}}`. 데이터셋 폴더 `D = <study>/03_dataset/<dataset_id>/` (작업 생성 시 `datasets` 행을 `BUILDING`으로 만든다).

| step_key | kind | 처리 | 가중 | 성공 판정 |
|---|---|---|---|---|
| DS_SCAN | INTERNAL | `input_path` 아래 재귀로 `*.h3d`(대소문자 무시) 수집 → 정렬·중복 제거(원본 `3_PHYSICS_AI/FUNC/1_create_dataset.py:17-48`). 경로 안전성 검사(§17.3: 공백·cmd 메타문자·링크 금지; 위반 파일 목록과 함께 `INPUT_INVALID`). 분할: 그룹 = 파일(`file`) 또는 상위 폴더(`parent_dir`); 그룹 목록을 정렬 → `random.Random(seed).shuffle` → 앞에서 `n_eval = max(1, round(n_groups × holdout_ratio))`개 그룹이 eval. `n_groups < 2` 또는 `h3d < dataset.min_h3d_files`면 `INPUT_INVALID`. `D/split.json` = `{seed, holdout_ratio, split_group, train:[abs path], eval:[abs path]}` | 5 | train ≥1, eval ≥1 |
| DS_YAML | INTERNAL | 원본 `generate_dataset_yaml`(`1_create_dataset.py:50-80`) 형식 그대로 `D/train/dataset.yaml`, `D/eval/dataset.yaml` 작성: `files:` 목록, `interface: hw`, `options:`(`extract_faces`, `extract_files: true`, `extract_mdi`, `extract_results: true`, `extract_time_history_vectors`, `hooks_dir: D/hooks`(빈 폴더 생성), `selection: {}` — 이 키가 없으면 edspy TypeError) | 1 | |
| EDSPY_DATASET_TRAIN | LOCAL | 템플릿 `edspy_create_dataset`, `{out_psdata}=D/train/dataset.psdata`, `{spec_yaml}=D/train/dataset.yaml`, cwd `D/train` | 60 | 종료코드 0 + 파일 ≥ `dataset.min_psdata_bytes`(기본 1 MiB, 원본 검사) |
| EDSPY_DATASET_EVAL | LOCAL | 같은 템플릿, `D/eval/…` | 33 | 동일 |
| DS_REGISTER | INTERNAL | `datasets` 행 `READY`, 크기 기록, `SPLIT_JSON` artifact | 1 | |

결과 `result`: `{dataset_id, h3d_count, train_count, eval_count}`. 실패 시 `datasets.status=FAILED`.

**평가용 홀드아웃은 학습 패키지(③-2)에 넣지 않는다.** 화면에 "평가용 N개는 학습에 쓰지 않고 점수 계산에만 씁니다" 표시.

### 8.5 ③-2 `PACKAGE_EXPORT`

`params`: `{dataset_id}`. 출력 `K = <study>/03_package/<dataset_id>/`.

| step_key | 처리 |
|---|---|
| PKG_COPY | `D/train/dataset.psdata` → `K/dataset_train.psdata`. `package.link_mode=hardlink_or_copy`면 같은 볼륨에서 하드링크 시도 후 실패 시 복사(`shutil.copyfile`, 1 MiB 버퍼, 진행률 = 복사 바이트/전체). `copy`면 항상 복사 |
| PKG_TEXT | `K/COMMANDS.txt`(아래), `K/REGISTER_README.txt`(③-4 폴더 형식 §15.3 설명) 작성, `datasets.package_rel` 기록, `PACKAGE_COMMANDS` artifact |

`COMMANDS.txt` 내용(원본 `3_PHYSICS_AI/FUNC/3_training.py:55-59`의 학습 명령 형태를 예시로):

```text
# PhysicsAI 학습 명령 예시 (HPC에서 직접 실행)
# 단위계: mm-ton-s. 이 폴더의 dataset_train.psdata는 학습용입니다(평가용 홀드아웃 제외).
edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg > train.log 2>&1
# 전이학습:
edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg --pretrained-model <PRETRAINED>.psmdl > train.log 2>&1
# 학습이 끝나면 .psmdl, 사용한 .pscfg, train.log를 한 폴더에 모아 플랫폼 ③-4 "모델 등록"에서 그 폴더 경로를 지정하세요.
# 로그의 loss 줄 예: "epoch=   1/1500  loss=1.03956e+02"
```

### 8.6 ③-4 `MODEL_REGISTER`

`params`: `{model_path: str, name?: str, label?: str, dataset_id?: str, log_file?: str(폴더 안 파일명)}`. 이름 기본 = 폴더의 `.psmdl` 파일 stem(정규식 불일치 시 422 `INVALID_PARAMS`로 이름 입력 요구).

| step_key | 처리 | 실패 |
|---|---|---|
| MR_VALIDATE | 폴더 직계 파일만 본다(하위 폴더 무시). `*.psmdl` 정확히 1개, `*.pscfg` 정확히 1개. 로그 후보 = `training_log.log_globs`(기본 `*.log`, `*.txt`) 일치 파일: 0개 → `log_status=MISSING`(등록 계속), 1개 → 사용, 2개 이상 → `log_file` 지정 필수(없으면 `INPUT_INVALID` + 후보 목록) | `INPUT_INVALID` |
| MR_COPY | 3개 파일을 `<study>/03_model/models/<model_id>/`로 복사(원본 파일명 유지) + sha256. `source.json`(원본 경로·시각·sha256) 작성 | `OUTPUT_LOCKED` 등 |
| MR_PARSE_LOG | `training_log.parsers`를 순서대로 적용, 1줄 이상 일치한 첫 파서 채택. 파서 = 정규식(필수 그룹 `epoch`, `loss`; 선택 `total`). 결과: `epochs_total`(total 마지막 값 또는 최대 epoch), `last_epoch`, `final_loss`, `min_loss`, `min_loss_epoch`, `loss_curve`. 한 줄도 일치하지 않으면 `log_status=UNRECOGNIZED`. **파싱 실패는 작업 실패가 아니다** | 없음 |
| MR_REGISTER | `models` 행 생성(`ACTIVE`, version 자동). `dataset_id` 미지정이면 Study 최신 READY 데이터셋(없으면 NULL — 평가 불가 표시) | |

기본 파서(원본 `3_PHYSICS_AI/GUI/3_gui_training.py:15-16` `LOSS_LINE_PATTERN`): `epoch=\s*(?P<epoch>\d+)\s*/\s*(?P<total>\d+)\s+loss=(?P<loss>[0-9.eE+\-]+)`. 로그 파일은 줄 단위 스트리밍으로 읽는다(크기 무제한, 메모리는 다운샘플 버퍼만).

등록 후 사용자는 **원본 폴더를 지워도 된다**(복사본 사용). 화면에 "로그 형식 미확인" 또는 "로그 없음"은 작은 회색 문구로.

### 8.7 ③-5 `EVALUATE`와 Final 지정

`params`: `{model_id}`. 평가 폴더 `E = <study>/03_model/score/<model_id>/<job_id>/`.

| step_key | kind | 처리 | 성공 판정 |
|---|---|---|---|
| EV_PREP | INTERNAL | 모델 sha256 재확인, `models.eval_status=RUNNING`, `E` 생성 | |
| EDSPY_SCORE | LOCAL | 템플릿 `edspy_score`: `{score_path}=E/<name>.psscr`, `{model_psmdl}`=등록 복사본, `{eval_psdata}`=모델 데이터셋의 eval psdata, `@write_files`는 `score.write_files=true`면 `--write-files`(원본 `3_PHYSICS_AI/FUNC/4_testing.py:57-65`). cwd `E`. 같은 폴더에 `predictions.psdata`도 생기므로 원본처럼 두 파일 모두 기존이면 백업 이동(`4_testing.py:96-114`의 삭제를 백업 이동으로 대체) | 종료코드 0 + psscr 존재 |
| EV_PARSE | INTERNAL | `score.parsers`(정규식, 그룹 `name`·`value` 또는 고정 이름 + 그룹 `value`)를 EDSPY_SCORE step 로그에 적용 → `metrics`. 없으면 `status=UNRECOGNIZED`. `models.eval_score`, `eval_status=DONE`, `SCORE_FILE` artifact(psscr는 등록하지 않고 경로만) | 항상 성공 |

Final 지정: `PUT /studies/{id}/final-model {model_id}` — `ACTIVE` 모델만, 평가 여부와 무관하게 허용(평가 전이면 화면에 "평가 전" 문구). 재지정 가능, `null`로 해제 가능. Final 모델을 `ARCHIVED`로 바꾸면 409 `MODEL_IS_FINAL`.

모델 목록 표시 열: 이름·버전, 데이터셋, epoch 수, 최종 loss, 최소 loss(epoch), loss 곡선(작은 스파크라인; 클릭 시 큰 차트, 로그 축), 평가 점수(metrics 또는 "점수 형식 미확인"), 로그 상태, Final 표시·지정 버튼.

### 8.8 ④ 파라미터 입력 확인(동기)

`POST /studies/{id}/predict/check {param_set_id?, values:{name:number}}` → 워커 불필요.

- 학습 범위 밖: `value < min or value > max`인 파라미터 목록.
- 정수 반영: tpl 형식이 정수(`%Ni`, `%Nd`)인 변수는 `predict.integer_rounding`(기본 `half_up`)으로 반올림해 반영됨을 `rounded:[{name, value, applied}]`로 알림(원본 tpl `{var_i, %3i}` 동작 보존, §19 U9).
- 최근접 run: 샘플(`samples.csv`) 중 `d = sqrt(Σ((x_i − y_i)/(max_i − min_i))²)` 최소(`max=min` 파라미터 제외). 동률이면 run_key 사전순.
- 응답: `{out_of_range:[{name, value, min, max}], rounded:[...], nearest:{run_key, distance, values:{}, measured:{resp:value}|null}}`.
- 화면: 경고 배지 없이 입력 표 아래 **작은 참고 문구 한 줄**만. 예) `학습 범위 밖 · 최근접 run_0012` / 범위 안이면 `최근접 run_0012 (거리 0.08)`.

### 8.9 ④ `PREDICT`

`params`: `{param_set_id?: str(기본 current), model_id?: str(기본 Final), values: {name: number}, value_source: "nominal"|"run"|"manual", source_run_key?: str}`. 모든 파라미터 값 필수·유한. 작업 폴더 `P = <study>/04_predict/<job_id>/`, 입력 원천 `S = <study>/04_params/<param_set_id>/`.

| step_key | kind | 처리 | 상태 |
|---|---|---|---|
| PR_PREP | INTERNAL | 모델·파라미터 세트 sha256 확인. `P/params.json`(값, 정수 반영값, 출처, 최근접 run) 작성. `S/cad/<cad>` → `P/geom/<cad>` 복사 | 확정 |
| TPL_RENDER | INTERNAL | `S/simlab_parametered_mesh.tpl`을 읽어(§15.4) `{parameter(var, "NAME", …)}` 줄을 제거하고 본문의 `{var, FMT}`를 `FMT % 값`(정수 형식은 반영값)으로 치환 → `P/geom/{predict.rendered_script_name}`. BOM 제거. 정의되지 않은 변수 참조가 남으면 `INPUT_INVALID` | 치환 규칙은 원본 `update_parameter_file`의 tpl 구조에서 유도 — **출력 파일 이름·형식은 미확인(U2)** |
| GEOM_UPDATE | LOCAL | 템플릿 `geom_update`(기본 `["{simlab}", "-auto", "{rendered_script}", "-nographics"]`), cwd `P/geom`. 템플릿이 `null`이면 `TEMPLATE_NOT_CONFIGURED` | **사내 확인 후 교체(U2)** |
| MESH | LOCAL | 템플릿 `mesh`. `null`(기본)이면 `SKIPPED` — GEOM_UPDATE 한 번의 SimLab 실행이 학습과 같은 tpl로 형상 갱신과 메싱을 함께 한다고 가정 | **사내 확인 후 교체(U2)** |
| RAD_ASSEMBLE | INTERNAL(+선택 LOCAL) | `S/radioss_assem/`의 `*.rad`·`*.inc` 중 이름이 `eps_mesh`로 시작하지 않는 것을 `P/INPUT/`로 복사(원본 `4_OPTIMIZATION/FUNC/1_physicsai_opti.py:294-303`), 이어서 `P/geom/` 아래 `predict.mesh_output_glob`(기본 `eps_mesh*`) 일치 파일을 `P/INPUT/`로 복사. starter = `P/INPUT/`의 `predict.starter_glob`(기본 `*_0000.rad`) 정확히 1개. 템플릿 `rad_assemble`이 있으면 이후 실행(cwd `P/INPUT`) | 복사 규칙 확정(원본), **메시 파일 이름·include 연결은 미확인(U3)** |
| EDSPY_PREDICT | LOCAL | 템플릿 `edspy_predict`(기본 `["@cmd_c", "{edspy}", "--physicsai", "--predict-write", "{pred_h3d}", "--model", "{model_psmdl}", "--input-file", "{starter}", "@hooks_arg"]`), `{pred_h3d}=P/RESULT/<starter stem>_pred.h3d`, env `EDS_TNS_ACTVN_CHCKPT=1`, cwd `P/INPUT`(원본 `1_physicsai_opti.py:306-323`). 모델 기본 = Final | 확정(원본). pscfg 미전달(U7) |
| CONTOUR_PREVIEW | LOCAL | 템플릿 `contour_preview`(기본 `["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{preview_tcl}", "-input", "{pred_h3d_fwd}", "-output", "{preview_json_fwd}"]`, `_fwd` = `/` 구분 경로), cwd `P`, `{preview_tcl}` = 설정 `resources.preview_pred_h3d_tcl`(원본 `CONFIG/BATCHRUN/BATCHRUN_preview_pred_h3d.tcl`), `{preview_json}=P/H3D_PREVIEW.json`(원본 `1_physicsai_opti.py:223-235`). **A안: TCL 출력을 가공 없이 그대로 쓴다** — `H3D_PREVIEW.json`을 `PREVIEW_JSON` artifact로, 실행 후 `P/` 직계에 새로 생긴 `*.png`·`*.jpg`가 있으면 각각 `PREVIEW_IMAGE` artifact로 등록 | 확정(원본). TCL은 tbcload 바이트코드라 이미지 생성 여부 미확인(U4) |
| CURVE_PICK | INTERNAL | `P/RESULT/`의 `*.xy`·`*.xydata` 첫 파일(이름순)을 원본 `parse_xydata`(`1_physicsai_opti.py:174-218`) 규칙 + 숫자 열 추출로 `P/curve.json` = `{file, series:[{name, x:[], y:[]}], note}` 작성 → `CURVE_JSON` artifact. **없으면 커브 없음**(경고 아님, `result.curve=null`) | best effort |
| RESPONSE_EXTRACT | LOCAL | 템플릿 `response_extract`, `{responses_json}=S/responses.json`, `{pred_h3d}`, `{out_csv}=P/responses_pred.csv`(형식 `name,value` 헤더 포함). `null`(기본)이면 `SKIPPED`, 예측 열 "추출 미구성" | **미확인(U8)** |
| RESPONSE_TABLE | INTERNAL | `P/responses.json` = 행: 파라미터 세트 `responses[]`, 열: `predicted`(responses_pred.csv, 없으면 null), `nearest_measured`(최근접 run의 `resp:` 열, 없으면 null), `diff_pct`(둘 다 있고 실측≠0일 때), `unit`. `RESPONSE_TABLE` artifact, `result.response_table`에 같은 수치 | 확정 |

결과 `result`: `{model_id, param_set_id, values, applied_values, out_of_range:[names], nearest:{run_key, distance}, preview_json_artifact_id, image_artifact_ids:[], curve_artifact_id|null, response_table:[{name, unit, predicted, nearest_measured, diff_pct}]}`.

결과 화면: ① 컨투어 영역 — 이미지 artifact가 있으면 이미지, 없으면 `H3D_PREVIEW.json`의 subcase/datatype 목록을 그대로 트리로 표시하고 회색 문구 "컨투어 이미지 없음 — 미리보기 TCL 출력은 결과 목록입니다" ② 커브 — 있을 때만 ③ 응답값 표(예측 / 최근접 학습 run 실측 / 차이%) ④ 입력값과 참고 문구.

### 8.10 ④ `PREDICT_VERIFY`

`params`: `{predict_job_id, hpc?: {queue?, ncpus?, walltime?}}`. 폴더 `V = P/verify/<attempt>/`.

| step_key | kind | 처리 |
|---|---|---|
| PV_PREP | INTERNAL | `P/INPUT/` → `V/input/` 복사, `V/result/` 생성 |
| HPC_SUBMIT | HPC_SUBMIT | `HpcJobGateway.submit(HpcSubmitSpec{job_name=<study>_<job8>_a<n>, run_key="verify", input_file=V/input/<starter>, input_dir, result_dir=V/result, …})` (path_map 적용) |
| HPC_WAIT | HPC_WAIT | 폴러(§12.4) |
| COLLECT | COLLECT | 1차는 `collect_mode=in_place`만: `V/result/`의 `hpc.transfer.collect_patterns` 일치 파일이 존재하고 크기·mtime이 10초 간격 2회 연속 불변 |
| PV_EXTRACT | LOCAL | `response_extract` 템플릿을 회수한 h3d에 적용(`null`이면 SKIPPED) |
| PV_TABLE | INTERNAL | `V/responses_verify.json`, `result.verify_values:{name: value}`. 화면은 원 PREDICT 응답 표에 "PBS 검증" 열을 합쳐 보여준다(PREDICT 행은 불변) |

`HpcJobGateway` 모드가 `none`이면 버튼 비활성 + 안내 "PBS 연결 안 됨 — 2차에서 제공(관리자 설정 필요)".

---

## 9. 명령 템플릿

### 9.1 규약

- 외부 프로그램 argv는 **코드에 박지 않고** 설정 `commands.<key>`(문자열 배열)에서 만든다. 기본값은 `config/platform.example.yaml`에 원본 인용으로 둔다. 코드에는 템플릿 키 이름과 placeholder 목록만 있다.
- 실행 파일 경로는 `altair.*`(`hyperstudy_path`, `simlab_path`, `edspy_path`, `hw_exe_path`, `hvtrans_exe_path` — 원본 `common.py:25-37` 키와 동일)에서만 얻는다. **코드에 `Program Files`·Altair 경로 하드코딩 금지**(정적 시험 V-CMD-4).
- argv[0]은 `{edspy}` `{simlab}` `{hw}` `{hstbatch}` `{hvtrans}` 중 하나이거나 `@cmd_c` 다음 요소여야 한다(그 외 argv[0] 템플릿은 설정 검증 실패).
- placeholder: 요소 전체 또는 일부 문자열 안의 `{name}`. 템플릿 키별 허용 목록(§9.2) 밖이면 설정 검증 실패. 리터럴 중괄호 `{{`·`}}`.
- 펼침 토큰(요소 전체가 정확히 이 문자열일 때만):
  - `@cmd_c` → Windows: `[<%SystemRoot%>\System32\cmd.exe, "/c"]`(SystemRoot 환경변수로 절대경로 구성), 비Windows: `[]`. 원본은 `.bat`의 종료코드를 받으려고 `cmd /c`를 썼다(`1_physicsai_opti.py:120-122`).
  - `@write_files` → `score.write_files`면 `["--write-files"]`, 아니면 `[]`.
  - `@hooks_arg` → 1차는 항상 `[]`(hooks 미지원, U13).
- 치환 값 검사: 제어문자(`\x00-\x1f`)·cmd 메타문자 `& | < > ^ % ! "` 포함 시 실행 전 거부(`INPUT_INVALID`). 공백은 argv[0](Altair 설치 경로)에만 허용. 이를 위해 `ai_root`·`resources.*`·Study 폴더명·입력 경로에 공백·메타문자를 금지한다(§14.3, §17.3). `.bat`이 cmd로 해석되는 문제(BatBadBut) 대비.
- 모든 LOCAL step은 워커의 제한기(§11.5) 안에서 실행. `env`는 워커 환경 + step 추가분(`predict.env` 등).

### 9.2 템플릿 키와 placeholder

| 키 | 사용 step | 허용 placeholder | 기본값 근거 | 상태 |
|---|---|---|---|---|
| `edspy_create_dataset` | EDSPY_DATASET_TRAIN/EVAL | `{edspy} {out_psdata} {spec_yaml}` | `3_PHYSICS_AI/FUNC/1_create_dataset.py:90` | 확정 |
| `edspy_score` | EDSPY_SCORE | `{edspy} {score_path} {model_psmdl} {model_pscfg} {eval_psdata}` + `@write_files` | `3_PHYSICS_AI/FUNC/4_testing.py:62-64` | 확정 |
| `geom_update` | GEOM_UPDATE | `{simlab} {rendered_script} {cad_file} {work_dir}` | 원본 SimLab 호출 형태(`1_CREATE_TRAINING_DATA/FUNC/1_create_tpl_file.py:45`의 `-auto … -nographics`) | 사내 확인 후 교체 |
| `mesh` | MESH | `{simlab} {rendered_script} {cad_file} {work_dir}` | 없음(기본 null) | 사내 확인 후 교체 |
| `rad_assemble` | RAD_ASSEMBLE | `{hw} {work_dir} {starter} {input_dir}` | 없음(기본 null) | 사내 확인 후 교체 |
| `edspy_predict` | EDSPY_PREDICT | `{edspy} {pred_h3d} {model_psmdl} {model_pscfg} {starter}` + `@cmd_c`, `@hooks_arg` | `4_OPTIMIZATION/FUNC/1_physicsai_opti.py:310-316`, 단독 예측 `3_PHYSICS_AI/FUNC/5_predict.py:62-65` | 확정 |
| `contour_preview` | CONTOUR_PREVIEW | `{hw} {preview_tcl} {pred_h3d_fwd} {preview_json_fwd}` | `1_physicsai_opti.py:230-231` | 확정 |
| `response_extract` | RESPONSE_EXTRACT, PV_EXTRACT | `{hw} {pred_h3d} {pred_h3d_fwd} {responses_json} {out_csv} {work_dir}` | 없음(기본 null) | 미확인(U8) |

`{model_pscfg}`는 기본 템플릿에서 쓰지 않는다(원본 score·predict 명령에 pscfg 인자가 없음, U7). 사내 확인으로 필요해지면 템플릿에만 추가한다 — 플랫폼은 경로만 넘기고 파일을 열지 않는다.

### 9.3 진행률·라벨 파서

| step | 규칙 |
|---|---|
| EDSPY_DATASET_*, EDSPY_SCORE, EDSPY_PREDICT, GEOM_UPDATE, MESH, CONTOUR_PREVIEW, RESPONSE_EXTRACT | 진행률 미상(NULL), 라벨 = 마지막 비어있지 않은 로그 줄 앞 120자 |
| PKG_COPY | 복사 바이트 / 전체 |
| MR_PARSE_LOG | 읽은 바이트 / 전체 |

---

## 10. REST API

### 10.1 공통

- 접두 `/physicsai/api`. 구조: router(HTTP·권한·감사) → service(use case) → repository(SQL). router에서 SQL 금지(구조 시험).
- 오류 형식 `{"detail": {"code": "...", "message": "<한국어>", ...추가 필드}}`(대시보드와 같은 모양).
- 공통 오류: 401 `AUTHENTICATION_REQUIRED`, 403 `ACCOUNT_NOT_ACTIVE` / `PERMISSION_DENIED` / `CSRF_HEADER_REQUIRED`, 404 `NOT_FOUND`, 422 `INVALID_PARAMS`(필드 오류 목록 `errors[]`), 503 `CONFIG_INVALID`(쓰기 API만) / `DASHBOARD_UNREACHABLE` / `DASHBOARD_AUTH_UNAVAILABLE`.
- 목록은 최신순, `limit`(기본 50, 최대 200)·`cursor`(불투명 문자열) 페이지.
- 응답에서 제외: `lease_*`, step `command`(전역 관리자의 `?include=commands`만), 절대경로 목록. 절대경로는 사용자가 지정한 `source_path`·`input_path` 표시와 `paths/inspect` 결과만.

### 10.2 셸·상태

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `GET /health` | 공개 | – | `{status:"ok", version}` | |
| `GET /me` | 로그인 | – | `{user_id, username, display_name, is_global_admin, roles:{project_id: role}}` | |
| `GET /projects` | 로그인 | – | `[{id, name, product_name}]` | 503 `DASHBOARD_UNREACHABLE` |
| `GET /status` | 로그인 | – | `{config:{ok, errors:[key]}, worker:{online, worker_id, last_seen_at, limiter}, hpc:{mode, configured, message}, altair:[{key, ok}], templates:[{key, configured}], limits:{configured, detected, effective}}` | |
| `GET /queue` | 로그인 | – | `{slot:{holder_job_id, since}, running: JobSummary?, queued:[JobSummary+queue_position], light:{running?, queued:[]}, waiting_hpc:[], collecting:[]}` | |
| `POST /queue/{job_id}/move` | 전역 관리자 | `{position:int≥1}` | `200 Queue` | 409 `JOB_NOT_QUEUED`, 422 |
| `GET /resources` | 로그인 | – | `{sampled_at, cpu_pct, ram_used_gb, ram_total_gb, gpu:[{name, util_pct, mem_used_mb, mem_total_mb}], job:{job_id, cpu_time_s, peak_memory_gb}?, limits:{cores, cpu_rate, memory_gb, priority, cpu_cap_enforced}}` | 404 `NO_SAMPLE` |

`JobSummary` = `{id, study_id, project_id, study_title, job_type, stage, lane, state, created_by, created_by_name, queue_position, progress_pct, progress_label, cancel_requested, created_at, started_at}`.

### 10.3 Study·경로

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `GET /studies?project_id=&status=` | 로그인 | – | `Study[]` | |
| `POST /studies` | power(해당 project) | `{project_id, folder_name, title}` | `201 Study` (폴더·`study.json` 생성) | 404 `PROJECT_NOT_FOUND`, 409 `STUDY_NAME_EXISTS`, 409 `FOLDER_EXISTS`(디스크에 이미 있음), 422 |
| `GET /studies/{id}` | 로그인 | – | `Study{…, final_model, stage_status:{3:{…},4:{…}}, current_param_set_id}` | |
| `PATCH /studies/{id}` | power | `{version, title}` | `Study` | 409 `VERSION_CONFLICT` |
| `POST /studies/{id}/archive` | power | – | `Study` | 409 `STUDY_HAS_ACTIVE_JOB` |
| `POST /studies/{id}/paths/inspect` | power | `{purpose:"DATASET_INPUT"|"MODEL_FOLDER"|"PARAM_SET", path}` | `{normalized_path, ok, problems:[{code, file?}], summary}` — DATASET_INPUT: `{h3d_count, sample_files[≤10], expected_train, expected_eval}`; MODEL_FOLDER: `{psmdl:[names], pscfg:[names], logs:[names]}`; PARAM_SET: §15.4 검증 결과 요약. **디스크 읽기만, 쓰기 없음** | 422 `PATH_OUTSIDE_ROOT` / `PATH_UNSAFE` / `PATH_NOT_FOUND` |

`Study` = `{id, project_id, folder_name, title, status, final_model_id, created_by, created_by_name, created_at, updated_at, version, can_execute}` (`can_execute` = 현재 사용자 power 이상).

### 10.4 데이터셋·모델·파라미터 세트

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `GET /studies/{id}/datasets` | 로그인 | – | `Dataset[]` | |
| `GET /datasets/{id}` | 로그인 | – | `Dataset` | |
| `GET /studies/{id}/models?status=` | 로그인 | – | `Model[]` (loss_curve 제외, `curve_points` 수만) | |
| `GET /models/{id}` | 로그인 | – | `Model`(loss_curve 포함) | |
| `PATCH /models/{id}` | power | `{row_version, label?, status?:"ACTIVE"|"ARCHIVED"}` | `Model` | 409 `MODEL_IS_FINAL`, `MODEL_IN_USE`(비종료 작업이 사용 중), `VERSION_CONFLICT` |
| `PUT /studies/{id}/final-model` | power | `{model_id: str|null}` | `Study` | 409 `MODEL_NOT_ACTIVE`, 404 |
| `POST /studies/{id}/param-sets` | power | `{path}` | `201 ParamSet` (동기 검증·복사, 폴더 총량 ≤ `param_set.max_total_bytes` 기본 2 GiB, 시간 초과 없음) | 422 `PARAM_SET_INVALID` + `problems[]`, `PATH_*` |
| `GET /studies/{id}/param-sets` | 로그인 | – | `ParamSet[]` | |
| `GET /param-sets/{id}` | 로그인 | – | `ParamSet` | |
| `GET /param-sets/{id}/samples?limit=&cursor=` | 로그인 | – | `{columns:[...], rows:[{run_key, values:{}, measured:{}}], next_cursor}` (파일에서 읽음) | |
| `POST /studies/{id}/predict/check` | 로그인 | `{param_set_id?, values}` | §8.8 | 404, 422 |

`Dataset` = `{id, study_id, job_id, status, source_path, h3d_count, train_count, eval_count, holdout_ratio, seed, split_group, options, package_ready, created_by_name, created_at}`.
`Model` = `{id, study_id, name, version, label, dataset_id, source_path, log_status, log_parser, epochs_total, last_epoch, final_loss, min_loss, min_loss_epoch, loss_curve?, eval_status, eval_score, status, is_final, registered_by_name, registered_at, row_version}` (`version`은 모델 버전, `row_version`은 낙관적 동시성 값).
`ParamSet` = `{id, study_id, source_path, unit_system, parameters, responses, sample_count, sample_has_measured, cad_file_name, starter_name, tpl_params, is_current, registered_by_name, registered_at}`.

### 10.5 작업·로그·산출물

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `POST /studies/{id}/jobs` | power | `{job_type, params}` | `201 Job{…, queue_position, warnings}` | 409 `STUDY_JOB_BUSY`, `PREREQUISITE_MISSING`, `FINAL_MODEL_REQUIRED`, `HPC_NOT_CONFIGURED`, `STUDY_ARCHIVED`, `TEMPLATE_NOT_CONFIGURED`(필수 템플릿 null), 422 `INVALID_PARAMS`/`PATH_*`, 503 `CONFIG_INVALID` |
| `GET /jobs?study_id=&state=&mine=&job_type=` | 로그인 | – | `JobSummary[]` | |
| `GET /jobs/{id}` | 로그인 | `If-None-Match` | `Job` + `ETag: "<id>:<version>:<log_size>"` | 304 |
| `GET /jobs/{id}/log?cursor=&limit=` | 로그인 | cursor = 바이트 오프셋, limit ≤ 262144 | `{text, next_cursor, eof, size}` (UTF-8 경계 보정) | 404 `LOG_NOT_FOUND` |
| `GET /jobs/{id}/steps/{step_no}/log?cursor=&limit=` | 로그인 | 동일 | 동일 | |
| `POST /jobs/{id}/cancel` | **전역 관리자** | – | `202 Job` | 409 `JOB_TERMINAL` |
| `POST /jobs/{id}/retry` | power(본인 작업) / 전역 관리자 | `{from_step?}` | `201 Job`(새 작업, `retry_of_job_id`) | 409 `JOB_NOT_RETRYABLE`(SUCCEEDED·비종료) |
| `GET /jobs/{id}/artifacts` | 로그인 | – | `Artifact[]` | |
| `GET /artifacts/{id}/content` | 로그인 | – | 파일 스트림(content-type 화이트리스트: `image/png`, `image/jpeg`, `application/json`, `text/plain`, `text/csv`) | 404 |
| `GET /jobs/{id}/hpc-jobs` | 로그인 | – | `[{id, run_key, attempt_no, external_job_id, state, external_state_raw, submitted_at, elapsed_s, collect_state}]` | |

`Job` = `JobSummary` + `{params, result, warnings, steps:[{step_no, step_key, kind, state, progress_pct, progress_label, started_at, finished_at, exit_code, failure_code, failure_message}], failure_code, failure_message, finished_at, retry_of_job_id, version, can_cancel, can_retry}`.

재시도: 실패 step(또는 `from_step`)부터 새 작업을 만들고 이전 성공 step의 산출물을 재사용한다(같은 폴더를 쓰는 작업은 같은 `dataset_id`/`model_id`/`P`를 이어받음, `params`는 원 작업 그대로).

### 10.6 작업 `params` 스키마 요약

```jsonc
// DATASET_CREATE
{"input_path": "E:/shared/AI_WORK/cushion/00_inbox/h3d", "holdout_ratio": 0.1, "seed": 20261008,
 "split_group": "file", "options": {"extract_faces": true, "extract_mdi": false, "extract_time_history_vectors": false}}
// PACKAGE_EXPORT
{"dataset_id": "…"}
// MODEL_REGISTER
{"model_path": "E:/shared/AI_WORK/cushion/00_inbox/model_v3", "name": "cushion_TNS", "label": null, "dataset_id": null, "log_file": null}
// EVALUATE
{"model_id": "…"}
// PREDICT
{"param_set_id": null, "model_id": null, "values": {"THK_1": 4.0}, "value_source": "manual", "source_run_key": null}
// PREDICT_VERIFY
{"predict_job_id": "…", "hpc": {"queue": null, "ncpus": null, "walltime": null}}
```

알 수 없는 키는 422. 숫자는 유한값. 이름 정규식: 모델 `^[A-Za-z][A-Za-z0-9_]{0,63}$`, 파라미터·응답 `^[A-Za-z_][A-Za-z0-9_]{0,63}$`, run_key `^[A-Za-z0-9_\-]{1,64}$`.

### 10.7 알림

| 메서드·경로 | 권한 | 요청 | 응답 |
|---|---|---|---|
| `GET /notifications?after_seq=&limit=` | 본인 | `after_seq` 없으면 최근 30일 최신순 | `{items:[{seq, event, job_id, study_id, project_id, title, body, created_at, read_at}], max_seq, unread_count}` |
| `GET /notifications/unread-count` | 본인 | – | `{unread_count, max_seq}` |
| `POST /notifications/read` | 본인 | `{seqs:[int]}` 또는 `{all:true}` | `{unread_count}` |

### 10.8 관리

| 메서드·경로 | 권한 | 응답 |
|---|---|---|
| `GET /admin/config` | 전역 관리자 | 유효 설정(DB URL·비밀 제외), 검증 결과, 템플릿 원문 |
| `GET /jobs/{id}?include=commands` | 전역 관리자 | step별 `command`(argv·cwd·추가 env) |

### 10.9 폴링 주기(SSE 없음)

| 대상 | 주기 |
|---|---|
| `GET /jobs/{id}` | RUNNING·COLLECTING 2초, QUEUED 5초, WAITING_HPC 15초, 종료면 중지 |
| 로그 | 로그 뷰어가 열려 있고 RUNNING일 때 2초 |
| `GET /queue` | 5초 |
| `GET /resources` | 10초 |
| `GET /notifications?after_seq=` | 10초 |
| `GET /status` | 30초 |

`document.visibilityState === "hidden"`이면 모두 멈추고, 돌아오면 즉시 1회 후 재개. 주기는 설정 `ui.poll_*`로 바꿀 수 있고 `/status`에 실어 보낸다.

---

## 11. 워커 프로토콜

### 11.1 프로세스·스레드

- 진입점 `python -m physicsai_worker [--config PATH]`. 기동 검사(실패 시 종료코드 2 + 한국어 메시지): 단일 인스턴스 잠금, DB 연결·migration head 일치, 설정 검증(§14.3), `ai_root` 쓰기 가능·SPDM 루트와 비중첩, 필수 Altair 실행 파일 존재(없으면 경고만 하고 해당 step이 `EXECUTABLE_MISSING`으로 실패 — 시험 환경 대비), HPC 모드 유효성.
- `worker_id = "<hostname>:<pid>:<uuid4>"`. 시작 시 `worker_heartbeats` upsert, 리퍼 1회.
- 스레드: `slot`(SLOT 레인 claim·실행), `light`(LIGHT 레인, 동시 1개), `hpc`(폴러·회수기), `heartbeat`(하트비트·자원 스냅샷·lease renew), `housekeeping`(리퍼 매 claim 주기, 알림 정리 `notifications.purge_interval_h`).
- 설정 파일 sha256을 claim마다 확인해 바뀌었으면 다시 읽고 검증. 실패하면 새 claim 중지 + `/status`에 오류. 실행 중 step에는 영향 없음.
- 종료 신호(Ctrl+C, SIGTERM): 새 claim 중지 → 실행 중 step은 그대로 두고 lease 갱신을 멈춘 채 종료(→ lease 만료 후 `INTERRUPTED`). Windows Job은 `KILL_ON_JOB_CLOSE`로 함께 종료.

### 11.2 claim / renew / release

```text
claim_slot(worker_id) — 한 트랜잭션:
  1. SELECT * FROM worker_slot WHERE id=1 FOR UPDATE
  2. 슬롯 lease 유효(expires_at > now()) → 종료
     슬롯 lease 만료 + holder 있음 → 그 작업 T9(INTERRUPTED)
  3. 대상 = SELECT id, version FROM jobs WHERE state='QUEUED' AND lane='SLOT' AND cancel_requested_at IS NULL
            ORDER BY queue_seq LIMIT 1 FOR UPDATE SKIP LOCKED
  4. token = secrets.token_urlsafe(32); gen = slot.lease_generation + 1
     UPDATE worker_slot SET holder_job_id=대상, lease_owner_id=?, lease_token=?, lease_generation=gen,
            lease_acquired_at=now(), lease_expires_at=now()+ttl WHERE id=1 AND lease_generation=<읽은 값>
     UPDATE jobs SET state='RUNNING', holds_slot=true, queue_seq=NULL, lease_*=(같은 값),
            started_at=COALESCE(started_at, now()), version=version+1
       WHERE id=대상 AND state='QUEUED' AND version=<읽은 값>
  5. 둘 다 1행이면 알림(JOB_STARTED, 다음 대기자 MY_TURN_NEXT 재계산) 후 커밋, 아니면 롤백
claim_light: 3~4에서 worker_slot 없이 lane='LIGHT', holds_slot=false. 동시 RUNNING LIGHT가 있으면 claim 안 함
renew(job_id, token) — heartbeat 스레드가 heartbeat_interval_s마다:
  UPDATE jobs SET lease_expires_at=now()+ttl WHERE id=? AND lease_token=? AND lease_expires_at>now()
  UPDATE worker_slot SET lease_expires_at=now()+ttl WHERE id=1 AND lease_token=? AND lease_expires_at>now()  (SLOT만)
  0행 → 소유권 상실: 즉시 프로세스 트리 종료, 이후 그 작업에 어떤 상태 쓰기도 하지 않음
release(job_id, token, next_state) — 전이와 같은 트랜잭션:
  jobs lease_*=NULL, holds_slot=false, state=next_state WHERE id=? AND lease_token=? AND lease_generation=?
  worker_slot holder_job_id=NULL, lease_*=NULL WHERE id=1 AND lease_token=?  (SLOT만)
```

- 상수(설정): `heartbeat_interval_s=10`, `lease_ttl_s=60`, `claim_interval_s=2`, `cancel_check_interval_s=2`.
- `COLLECTING`의 회수도 작업 lease를 같은 방식으로 잡는다. `WAITING_HPC` 폴링은 `hpc_jobs.version` CAS만.
- `/status`의 `worker.online` = `now() - last_seen_at ≤ 3 × heartbeat_interval_s`.
- 리퍼: `state IN ('RUNNING','COLLECTING') AND lease_expires_at < now()` → T9. 워커 시작 시와 매 claim 주기.

### 11.3 step 실행기

```text
for step in steps[resume_from..]:
  cancel 플래그 확인 → T8
  step RUNNING 기록(command 확정값 포함)
  INTERNAL → 파이썬 함수 실행(취소 확인 지점: 파일 1개 복사·1 MiB마다)
  LOCAL    → 템플릿 펼침·검사(§9.1) → limiter.launch → 줄 스트리밍(로그·진행률 파서·오류 정규식)
             → cancel_check_interval_s마다 cancel 플래그 확인 → 종료 → accounting 기록 → 성공 판정
  실패 → T7 / 성공 → 다음
```

외부 프로세스 출력은 로그 저장 전 `mask_secrets`(설정 `logging.mask_patterns`, 기본: `password=…`, `token=…` 값 마스킹)를 적용한다.

### 11.4 자원 한도 계산

```text
detected_cores = os.cpu_count()
detected_mem_gb = psutil.virtual_memory().total / 2^30
auto_detect=false(기본): eff_cores = min(max_logical_cores, detected_cores); eff_mem = min(max_memory_gb, detected_mem_gb)
auto_detect=true:        eff_cores = min(max_logical_cores, floor(detected_cores × auto_detect_ratio)); eff_mem 동일 방식
cpu_rate = clamp(floor(eff_cores / detected_cores × 10000), 100, 10000)     # 1/100 % 단위
기본값: max_logical_cores=32, max_memory_gb=64, priority=below_normal
```

### 11.5 제한기(limiter)

인터페이스(`worker/physicsai_worker/limiter/base.py`):

```python
class ProcessLimiter(Protocol):
    name: str                      # "windows_job" | "posix" | "null"
    cpu_cap_enforced: bool
    def launch(self, argv: list[str], cwd: str, env: dict[str, str], limits: EffectiveLimits) -> LimitedProcess: ...
    def terminate(self, proc: LimitedProcess, timeout_s: float = 30) -> None: ...   # 트리 전체
    def accounting(self, proc: LimitedProcess) -> Accounting: ...                  # peak_memory_bytes, cpu_time_s
```

선택: 설정 `worker.limiter = auto | windows_job | posix | null`. `auto` = Windows면 `windows_job`, 그 외 `posix`. `null`은 `profile=dev`에서만 허용.

**WindowsJobLimiter(ctypes, kernel32)** — step 프로세스마다 Job 1개:
1. `CreateJobObjectW(NULL, NULL)`
2. `SetInformationJobObject(JobObjectExtendedLimitInformation)`: `LimitFlags = KILL_ON_JOB_CLOSE | JOB_MEMORY | PRIORITY_CLASS | DIE_ON_UNHANDLED_EXCEPTION`, `JobMemoryLimit = eff_mem × 2^30`, `PriorityClass = BELOW_NORMAL_PRIORITY_CLASS`(`idle`→IDLE, `normal`→NORMAL). `BREAKAWAY_OK`·`SILENT_BREAKAWAY_OK`는 **설정하지 않는다** → 손자 프로세스까지 Job 안.
3. `SetInformationJobObject(JobObjectCpuRateControlInformation)`: `CPU_RATE_CONTROL_ENABLE | CPU_RATE_CONTROL_HARD_CAP`, `CpuRate = cpu_rate`.
4. GPU는 제한하지 않는다.
5. `Popen(argv, shell=False, creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)` → `AssignProcessToJobObject` → 주 스레드 `ResumeThread`(`CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)` + `OpenThread(THREAD_SUSPEND_RESUME)`). 할당 실패 시 `TerminateProcess` 후 `JOB_OBJECT_ASSIGN_FAILED` — **제한 없이 실행하는 경로는 없다**.
6. 취소·lease 상실: `TerminateJobObject(job, 1)` → 종료 대기(최대 30초).
7. 종료 후 `QueryInformationJobObject`(`PeakJobMemoryUsed`, `TotalUserTime+TotalKernelTime`) → `outputs.accounting`. `PeakJobMemoryUsed ≥ 0.98 × 한도`이고 비정상 종료면 `RESOURCE_LIMIT`.
8. 워커가 죽으면 Job 핸들이 닫혀 `KILL_ON_JOB_CLOSE`로 트리 전체 종료.

**PosixLimiter(psutil, 시험·Linux 개발용)**: `Popen(..., start_new_session=True, preexec_fn=lambda: os.nice(10))`, 메모리 상한 `resource.setrlimit(RLIMIT_AS)`(설정 `worker.posix_rlimit_as`, 기본 false), CPU hard cap 없음(`cpu_cap_enforced=false`로 기록·표시). terminate = `os.killpg(pgid, SIGTERM)` → 5초 후 남은 `psutil.Process.children(recursive=True)` 포함 `SIGKILL`. accounting = psutil 샘플 최대 RSS 합계.

**NullLimiter**: 제한 없이 `Popen`, terminate는 psutil 트리 kill. `profile=dev`에서만.

### 11.6 자원 스냅샷(`resource_sample_interval_s`, 기본 10초)

CPU %(`psutil.cpu_percent(interval=None)`), RAM(`psutil.virtual_memory()`), 실행 중 작업 accounting, GPU: 설정 `worker.gpu_query` argv 실행(제한기 밖, 타임아웃 5초, `nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits` 형식 파싱). 없거나 실패면 `gpu: []`. `worker_heartbeats.resources`에 최신값만 저장.

### 11.7 환경 스냅샷(`jobs.env_snapshot`)

```json
{"app_version": "<git describe 또는 패키지 버전>", "config_sha256": "…",
 "altair": {"version_label": "2026.1", "paths": {"edspy_path": {"path": "…", "size": 0, "mtime": "…"}}},
 "worker": {"worker_id": "…", "limiter": "windows_job", "detected": {"cores": 64, "memory_gb": 256},
            "effective": {"cores": 32, "cpu_rate": 5000, "memory_gb": 64, "priority": "below_normal"}},
 "gpu": [{"name": "…", "memory_total_mb": 0}], "hpc": {"mode": "none"}}
```

---

## 12. HPC 게이트웨이

### 12.1 모드

`PHYSICSAI_HPC_GATEWAY` 환경변수 > 설정 `hpc.gateway`, 기본 `none`.

| 모드 | 동작 |
|---|---|
| `none` | `configured=false`, message "PBS 연결 안 됨". HPC 필요한 작업 생성은 409 `HPC_NOT_CONFIGURED`. UI 버튼 비활성 + 안내 |
| `command` | 설정 argv 템플릿으로 submit/status/cancel. 템플릿 누락·검증 실패면 `configured=false`(사유) |
| `adapter` | 자리만. 항상 `configured=false`, message "어댑터 job API 미확인 — 미구현". 어댑터 패키지 import 없음 |

### 12.2 프로토콜(`backend/physicsai_core/hpc/gateway.py`)

```python
HpcState = Literal["QUEUED", "RUNNING", "FINISHED", "UNKNOWN"]

@dataclass(frozen=True)
class HpcAvailability:
    configured: bool
    mode: Literal["none", "command", "adapter"]
    message: str                          # 한국어

@dataclass(frozen=True)
class HpcSubmitSpec:
    job_name: str                         # ^[A-Za-z0-9_\-]{1,64}$
    run_key: str
    study: str
    input_file: str                       # path_map 적용 후 클러스터 경로
    input_dir: str
    result_dir: str
    queue: str | None
    ncpus: int | None
    walltime: str | None                  # ^\d{1,4}:\d{2}:\d{2}$

@dataclass(frozen=True)
class HpcSubmitResult:
    external_job_id: str
    raw_stdout: str                       # ≤4 KiB, 마스킹

@dataclass(frozen=True)
class HpcStatus:
    state: HpcState
    raw_state: str | None
    exit_code: int | None
    not_found: bool

class HpcGatewayError(RuntimeError):
    code: Literal["NOT_CONFIGURED", "SUBMIT_FAILED", "PARSE_FAILED", "TIMEOUT", "NOT_FOUND", "UNAVAILABLE"]

class HpcJobGateway(Protocol):
    def availability(self) -> HpcAvailability: ...
    def submit(self, spec: HpcSubmitSpec) -> HpcSubmitResult: ...
    def status(self, external_job_id: str) -> HpcStatus: ...
    def cancel(self, external_job_id: str) -> None: ...
```

구현: `NoneHpcGateway`, `CommandHpcGateway`, `AdapterHpcGateway`(자리). 팩터리 `get_hpc_gateway(config)` 하나. API와 워커가 같은 팩터리를 쓰되 **API는 `availability()`만 호출**한다.

### 12.3 command 템플릿 규칙

- `submit`, `status`, `cancel`은 문자열 배열(필수). 문자열 하나면 설정 오류.
- argv[0]은 절대경로이고 `hpc.command.allowed_executables`에 있어야 한다. `.bat`·`.cmd`·`.ps1` 금지.
- placeholder 화이트리스트: `{job_name} {run_key} {study} {input_file} {input_dir} {result_dir} {queue} {ncpus} {walltime} {external_job_id}`.
- 치환 값: 제어문자 금지, ≤1024자, `{external_job_id}`는 `job_id_regex` 재일치, `{queue}` `^[A-Za-z0-9_.\-@]{1,64}$`, `{ncpus}` 1~4096, `{walltime}` 위 정규식, 경로는 path_map 적용 후 `^[A-Za-z0-9_./:\\\-]+$`.
- 실행: `subprocess.run(argv, shell=False, capture_output=True, timeout=…)`(제한기 밖, hpc 스레드). 타임아웃 submit 60s, status 30s, cancel 30s(설정).
- 파싱: `job_id_regex`(그룹 `job_id`) — submit stdout, `state_regex`(그룹 `state`)·`exit_code_regex`(그룹 `exit`, 선택)·`not_found_regex`(선택) — status stdout+stderr.
- `state_map`: 원시 문자 → `QUEUED|RUNNING|FINISHED`. 없는 값·불일치 → `UNKNOWN`. `FINISHED` + exit 0(정규식 없으면 회수 패턴 충족) → `SUCCEEDED`, 아니면 `FAILED`. `not_found`는 QUEUED/RUNNING을 본 뒤면 FINISHED로 간주, 처음부터면 UNKNOWN. UNKNOWN이 `lost_after_polls`회 연속이면 `LOST`(→ T13).

### 12.4 폴러·회수

- `poll_interval_s`(기본 60)마다 `WAITING_HPC` 작업의 비종료 hpc_jobs에 `status`. 연속 게이트웨이 오류 시작 시각은 `jobs.result.hpc_unreachable_since`.
- 회수: 1차는 `in_place`만(설정에 `shared_folder`·`drive`가 오면 설정 검증 실패 "2차"). 파일당 상한 `max_collect_bytes`.

---

## 13. 알림

### 13.1 이벤트·수신자

| event | 발생 시점(같은 트랜잭션) | 수신자 | title 예 |
|---|---|---|---|
| `JOB_STARTED` | T2 | 작업 등록자 | "실행 시작: 데이터셋 생성 (cushion)" |
| `JOB_SUCCEEDED` | T6, T15 | 등록자 | "완료: 예측 (cushion)" |
| `JOB_FAILED` | T7, T13, T16 | 등록자 | "실패: 평가 (cushion) — EXIT_NONZERO" |
| `JOB_CANCELED` | T3, T8, T12 | 등록자 | "관리자가 작업을 취소했습니다" |
| `JOB_INTERRUPTED` | T9 | 등록자 | "워커 중단으로 작업이 멈췄습니다" |
| `MY_TURN_NEXT` | 대기열 변화(T1·T2·T3·T8·순서 변경) 후 SLOT 레인 대기 1번이 된 작업, 슬롯이 사용 중일 때, 작업당 1회(`next_notified_at`) | 등록자 | "다음 차례입니다: 예측 (cushion)" |
| `HPC_COLLECTED` | T14, T15 | 등록자 | "PBS 결과 회수 완료" |

### 13.2 전달·보관

- 폴링: 프런트가 페이지 로드 시 `GET /notifications/unread-count`로 `max_seq`를 받고, 이후 10초마다 `GET /notifications?after_seq=<max_seq>`. 새 항목마다 **우하단 토스트**(5초 후 자동 닫힘, 최대 3개 쌓임, 클릭 시 해당 작업 화면). 로드 이전 알림은 토스트로 띄우지 않는다.
- **상단 우측 벨 아이콘**: 미읽음 수 배지(99+ 상한). 클릭 → 알림 이력 패널(최근 30일, 최신순, 무한 스크롤), 항목 클릭 시 읽음 처리 + 이동, "모두 읽음" 버튼.
- 보관: 워커 housekeeping이 `notifications.purge_interval_h`(기본 6)마다 `created_at < now() - retention_days(30)` 삭제.

---

## 14. 설정 YAML

### 14.1 위치·우선순위

- 파일: `PHYSICSAI_CONFIG` 환경변수, 기본 `config/platform.yaml`(`.gitignore`). 예시 `config/platform.example.yaml`이 전체 스키마이자 기본값이다.
- 환경변수 우선: `PHYSICSAI_PROFILE` > `profile`, `PHYSICSAI_HPC_GATEWAY` > `hpc.gateway`. DB 비밀번호는 설정 파일에 넣지 않고 `database.url_env`가 가리키는 환경변수에서 읽는다.
- API와 워커가 같은 파일을 읽는다. API는 기동 시 검증 실패해도 뜨되 쓰기 API는 503 `CONFIG_INVALID`, 조회는 동작.

### 14.2 스키마

`config/platform.example.yaml` 참조(이 계약의 일부). 최상위 키: `schema_version, profile, server, database, auth, storage, altair, resources, worker, dataset, package, training_log, score, param_set, predict, commands, commands_log_error_patterns, hpc, notifications, ui, logging`.

### 14.3 검증 규칙

| 대상 | 규칙 |
|---|---|
| `schema_version` | 1 |
| `storage.ai_root` | 절대경로, 존재, 쓰기 가능, 공백·cmd 메타문자 없음, `storage.spdm_roots` 각각과 같거나 안팎으로 겹치지 않음 |
| `storage.allowed_import_roots[]` | 절대경로, 존재, 읽기 가능, 공백·메타문자 없음, SPDM 루트와 비중첩 |
| `altair.*` | 문자열(빈 값 허용 — 해당 step만 `EXECUTABLE_MISSING`). 값이 있으면 절대경로. `profile=prod`면 존재해야 함 |
| `resources.preview_pred_h3d_tcl` | 절대경로, 공백·메타문자 없음. prod면 존재 |
| `worker` | cores 1~1024, memory_gb 1~4096, ratio 0.1~1.0, interval·ttl 양수이고 `lease_ttl_s ≥ 3 × heartbeat_interval_s`, limiter 값, `null`은 dev만 |
| `auth` | mode 값, `dev_static`은 dev+127.0.0.1만, URL 형식, cookie_name `^[A-Za-z0-9_\-]+$` |
| `dataset` | holdout_ratio 0.05~0.5, min_h3d_files ≥2, min_psdata_bytes ≥0 |
| `training_log.parsers[]`, `score.parsers[]`, `commands_log_error_patterns[]` | 정규식 컴파일, 필수 그룹 존재 |
| `commands.*` | §9.1·§9.2(배열 또는 null, argv[0] 규칙, 허용 placeholder, 펼침 토큰). 확정 템플릿(`edspy_*`, `contour_preview`)은 null 금지 |
| `hpc` | §12.3, `collect_mode`는 1차 `in_place`만 |
| 알 수 없는 키 | 오류(오타 방지) |

---

## 15. 폴더 스키마

### 15.1 AI 루트

```text
<ai_root>/
  <study_folder>/                         # studies.folder_name (영문·숫자·_- , _로 시작 금지)
    study.json                            # {id, project_id, title, created_at} 사람용 메타
    00_inbox/                             # 사용자가 h3d·모델·파라미터 폴더를 두는 권장 위치(앱은 읽기만)
    03_dataset/<dataset_id>/
      split.json
      hooks/                              # 빈 폴더(dataset.yaml hooks_dir)
      train/dataset.yaml, train/dataset.psdata
      eval/dataset.yaml,  eval/dataset.psdata     # 홀드아웃 — 학습 패키지에 넣지 않음
    03_package/<dataset_id>/
      dataset_train.psdata, COMMANDS.txt, REGISTER_README.txt
    03_model/
      models/<model_id>/<name>.psmdl, <name>.pscfg, <log 파일>, source.json
      score/<model_id>/<job_id>/<name>.psscr, predictions.psdata
    04_params/<param_set_id>/
      parameters.json, samples.csv, responses.json (정규화본), source.json
      cad/<CAD 파일>, simlab_parametered_mesh.tpl, radioss_assem/*.rad, *.inc
    04_predict/<job_id>/
      params.json
      geom/<CAD 사본>, <rendered script>, <SimLab 출력·메시>
      INPUT/*.rad, *.inc                  # 조립된 Radioss 입력
      RESULT/<stem>_pred.h3d, *.xy|*.xydata
      H3D_PREVIEW.json, [*.png|*.jpg], curve.json, responses_pred.csv, responses.json
      verify/<attempt>/input/, result/, responses_verify.json
    logs/<job_id>/job.log, step_<NN>_<step_key>.log, tmp/
    _backup/<UTC yyyyMMddTHHmmssZ>_<job_id>/<원래 상대경로>
```

- SPDM master에는 아무것도 쓰지 않는다. AI 루트 밖에 쓰는 일도 없다(허용 루트는 읽기 전용).

### 15.2 ③-1 입력(h3d 폴더)

AI 루트 하위 임의 폴더. 하위 트리의 모든 `*.h3d`를 쓴다. 경로(폴더·파일)에 공백·cmd 메타문자·심볼릭 링크·reparse point가 없어야 한다.

### 15.3 ③-4 입력(모델 폴더)

AI 루트 또는 `allowed_import_roots` 하위 폴더. 직계에 `*.psmdl` 1개, `*.pscfg` 1개, 학습 로그 0~1개(여러 개면 선택). `REGISTER_README.txt`에 같은 내용을 쓴다.

### 15.4 ④ 입력(파라미터 세트 폴더)

AI 루트 하위 폴더, 직계 구성:

| 파일 | 필수 | 형식 |
|---|---|---|
| `parameters.json` 또는 `parameters.csv` | 필수(둘 다 있으면 json) | JSON: `{"schema_version":1, "unit_system":"mm-ton-s", "parameters":[{"name":"THK_1","nominal":3.0,"min":2.0,"max":5.0,"unit":"mm"}]}` / CSV 헤더 `name,nominal,min,max,unit` |
| `samples.csv` | 선택(없으면 최근접 run·실측 열 없음) | UTF-8(BOM 허용), 헤더 `run_key,<파라미터 이름 전부>[,resp:<응답 이름>…]`, 행 ≤ `param_set.max_samples`(기본 20000) |
| `responses.json` | 선택(없으면 응답 표 없음) | `{"responses":[{"name":"MaxStress","unit":"MPa","spec":{…}}]}` — `spec`은 `response_extract` 템플릿이 읽는 불투명 객체 |
| `cad/` | 필수 | CAD 파일 정확히 1개 |
| `simlab_parametered_mesh.tpl` | 필수 | 학습에 쓴 SimLab 템플릿(원본 `TEMAPLATE_simlab_parametered_mesh.tpl`로 만든 것) |
| `radioss_assem/` | 필수 | `*.rad`·`*.inc`, `predict.starter_glob` 일치 정확히 1개 |

검증: 이름 정규식·중복 없음, 유한값, `min ≤ nominal ≤ max`, samples 열 = 파라미터 이름 집합(순서 무관), `resp:` 이름 ⊂ responses 이름, tpl의 `{parameter(VAR, "NAME", …)}` 이름 집합 = 파라미터 이름 집합(아니면 `PARAM_TPL_MISMATCH`), tpl 본문 `{VAR, FMT}`의 FMT ∈ `%[-0-9.]*[idfeEgG]`. 등록 시 정규화본(JSON·CSV 재작성)과 원본 파일을 `04_params/<id>/`로 복사, 새 세트가 `is_current`.

tpl 구조 근거: 원본 `update_parameter_file`(`1_CREATE_TRAINING_DATA/FUNC/1_create_tpl_file.py:134-175`)가 `{parameter(var_i, "<param>", <nominal>, <min>, <max>)}` 블록과 `<paramitem Name="<param>" NewValue="{var_i, %3i}" …/>`, `dir_file_prt = r"./<cad 파일명>"`을 쓴다.

---

## 16. UI 계약

### 16.1 라우팅

| 경로 | 화면 |
|---|---|
| `/physicsai/` | 프로젝트 선택(대시보드 프로젝트 목록, 내 역할 표시) |
| `/physicsai/p/:projectId` | Study 목록 + "새 Study"(power 이상) |
| `/physicsai/p/:projectId/s/:studyId/stage/:n` | 단계 작업 화면(n=1~5, 기본 3) |

### 16.2 레이아웃

- 상단 바: 좌측 경로바 `AI 예측 > <프로젝트명> > <Study 제목> > <단계명>`(각 항목 링크), 우측 사용자 이름·역할, **벨 아이콘**(미읽음 배지), "대시보드로" 링크.
- 그 아래 **5단계 스텝퍼**: ① 학습데이터 생성 ② 데이터 정리 ③ 데이터셋·모델 ④ 단일 예측 ⑤ 최적화. 1차 비활성 단계(①②⑤)는 회색 + "2차" 표시, 클릭 시 작업영역에 "2차에서 제공 예정입니다" 안내만. 활성 단계는 최근 작업 상태 점(실행/대기/성공/실패).
- 본문 그리드: 좌측 작업영역 `minmax(0, 1fr)` + 우측 공통 패널 `clamp(360px, 22vw, 560px)`. 가로 스크롤 없음.
- **32인치 4K 대응**: 3840×2160(배율 100~150%)에서 작업영역 최대 폭 제한 없음, 표·차트가 폭을 채운다. 기본 글꼴 15px, 뷰포트 폭 ≥ 2560px에서 17px(rem 기반 스케일). 최소 지원 폭 1280px. 데스크톱 전용.
- 우측 공통 패널(위→아래): ① **실행 대기열**(실행 중 1건·진행률, 대기 목록 순번·등록자·Study, LIGHT 작업, PBS 대기; 내 작업 강조; 전역 관리자에게만 순서 이동(▲▼)·취소 버튼) ② **워커 자원**(CPU/RAM/GPU 막대, 유효 한도 "32코어·64GB·낮은 우선순위", `cpu_cap_enforced=false`면 "CPU 상한 미적용(개발 환경)", 워커 오프라인 경고) ③ **모델 목록·Final**(현재 Study 모델, Final 배지, 최종/최소 loss, 평가 점수 요약, "Final로 지정" 버튼).
- 토스트: 우하단(§13.2).

### 16.3 단계 화면 원칙

- 하위 단계마다 카드 1개, **실행 버튼 1개**(주 동작), 필수 입력만 노출. 선택 입력은 "고급" 접힘(기본 닫힘).
- 실행 권한이 없으면(general·비멤버) 버튼 비활성 + 툴팁 "실행 권한(power 이상)이 필요합니다".
- 버튼을 누르면 작업이 대기열에 등록되고 버튼 옆에 상태("대기 2번째" / 진행률 / 결과 링크) 표시.
- 로그 뷰어: 접힘 기본, 열면 커서 폴링, 자동 스크롤 토글.

### 16.4 ③ 화면

| 카드 | 입력 | 결과 표시 |
|---|---|---|
| ③-1 데이터셋 생성 | h3d 폴더 경로(텍스트 + "확인" → `paths/inspect` 요약: h3d N개, 학습 M / 평가 K 예상). 고급: holdout 비율, seed, 분할 단위, 추출 옵션 3개 | 데이터셋 목록(상태, 개수, 생성자·시각) |
| ③-2 학습 패키지 | 데이터셋 선택(기본 최신 READY) | 패키지 폴더 경로(복사 버튼), `COMMANDS.txt` 내용 미리보기 |
| ③-3 HPC 학습 | 없음(안내 문구: 패키지 폴더를 HPC로 가져가 학습, 실시간 로그 없음) | – |
| ③-4 모델 등록 | 모델 폴더 경로(+ "확인" → psmdl/pscfg/로그 후보), 이름(기본값 채움). 고급: 표시명, 데이터셋, 로그 파일 선택 | 등록 결과(로그 상태 문구) |
| ③-5 평가·Final | 모델 선택 → "평가" | 모델 표(§8.7 열) + loss 곡선(선택 모델, SVG, 선형/로그 축 토글) + Final 지정 |

### 16.5 ④ 화면

| 영역 | 내용 |
|---|---|
| 파라미터 세트 | 현재 세트 요약(파라미터 수, 샘플 수, 단위계) + "폴더 등록"(경로 + 확인 + 등록) |
| 입력 | 파라미터 표: 이름·단위·하한·공칭·상한·**입력값**. 값 채우기 버튼 3개: "공칭" / "학습 run 불러오기"(run_key 선택 목록) / 직접 입력. 입력 변경 시 디바운스(300ms) `predict/check` → 표 아래 작은 회색 문구 한 줄(§8.8). 경고 배지·빨간 강조 없음 |
| 모델 | 기본 Final 모델 이름 표시. 고급: 다른 ACTIVE 모델 선택 |
| 실행 | "예측 실행" 1개. 옆에 "PBS 검증 해석"(hpc 미구성 시 비활성 + 툴팁 안내) |
| 결과 | 컨투어 미리보기(이미지 또는 결과 목록 트리 + 문구), 커브(있을 때만, SVG 선 그래프), 응답값 표(응답·단위·예측·최근접 run 실측·차이%·[PBS 검증]) |

---

## 17. 보안

1. 명령 실행은 워커만, argv 배열 + `shell=False`. argv[0]은 설정 `altair.*`, `cmd.exe`(고정 경로), HPC 허용 목록, GPU 조회 argv[0]뿐. 사용자 입력은 argv[0]이 될 수 없다.
2. 사용자 문자열 정규식 제한(§10.6). HyperWorks 이름류는 JSON 파일로만 전달.
3. **경로 검사**(사용자 지정 경로 공통): 입력은 절대경로(Windows `X:\…`/`X:/…` 또는 POSIX `/…`) 문자열 ≤ 400자. `os.path.realpath` 후 허용 루트(`ai_root`, 모델 폴더는 `allowed_import_roots` 추가) 접두 일치(대소문자 무시 on Windows), `..` 잔존 금지, 경로 구성요소 중 심볼릭 링크·reparse point(`FILE_ATTRIBUTE_REPARSE_POINT`) 거부, `_backup` 하위 거부, 공백·제어문자·cmd 메타문자 거부. 오류 코드 `PATH_OUTSIDE_ROOT`/`PATH_UNSAFE`/`PATH_NOT_FOUND`. 플랫폼 내부 파일 접근은 Study 폴더 아래로 `resolve()` 후 접두 검사.
4. **pickle 금지**: `.pscfg`는 경로·sha256만. `physicsai_api`·`physicsai_core`·`physicsai_worker`에 `pickle`·`joblib`·`dill`·`torch.load` import 없음(정적 시험 V-SEC-2). pscfg 파일은 edspy 프로세스 안에서만 열린다.
5. 업로드 엔드포인트 없음(multipart 라우트 0개, 정적 시험). 산출물 다운로드는 id로만, 화이트리스트 content-type, 크기 상한.
6. 감사: 작업 생성·취소·재시도·대기열 이동·Final 지정·모델 상태 변경·Study 생성/보관·파라미터 세트 등록을 `audit_events`(`id, occurred_at, user_id, username, action, target_type, target_id, detail JSONB, request_id, client_ip`) 테이블에 기록(0001 migration에 포함).
7. SPDM: 쓰기·읽기 모두 없음. `ai_root`·허용 루트가 `storage.spdm_roots`와 겹치면 설정 오류.
8. 대시보드 토큰: 로그·DB·응답에 남기지 않음. 대시보드 호출은 `dashboard_internal_url`(루프백)로만.
9. 로그 마스킹 §11.3.

---

## 18. 시험 전략(Altair 없는 Linux)

### 18.1 fake tools(`backend/tests/fake_tools/`, Impl-Backend 소유)

실행 가능한 Python 스크립트(shebang `#!/usr/bin/env python3`, 시험 fixture가 `chmod +x`). 시험용 설정이 `altair.edspy_path` 등을 이 파일로 가리킨다. 동작은 환경변수 `FAKE_TOOL_MODE`(기본 `ok`)와 `FAKE_TOOL_DELAY_S`로 조절하고, 받은 argv·cwd·주요 env를 `FAKE_TOOL_RECORD`(JSON lines 파일)에 기록한다(골든 시험용).

| 파일 | 흉내 | `ok` 동작 | 그 밖의 모드 |
|---|---|---|---|
| `fake_edspy` | `edspy.bat` | `--create-dataset OUT --spec YAML`: yaml의 files 존재 확인 후 OUT에 1 MiB+1 바이트 파일. `--score S --model M --dataset D [--write-files]`: S와 같은 폴더 `predictions.psdata` 생성, stdout에 `R2 = 0.93` 같은 줄. `--predict-write H --model M --input-file I`: `EDS_TNS_ACTVN_CHCKPT=1` 확인(없으면 종료코드 3), H와 같은 폴더에 `<stem>.xy`(헤더 + 숫자 2열) 생성 | `fail`(종료코드 1), `error_log`(종료코드 0 + `Traceback (most recent call last):` 출력), `small`(1 KiB 출력), `hang`(취소될 때까지 대기, 자식 프로세스 1개 생성 — 트리 종료 시험), `no_output`, `noxy`(커브 없음) |
| `fake_simlab` | `SimLab.bat` | `-auto SCRIPT … -nographics`: SCRIPT 존재 확인, cwd에 `eps_mesh_1.inc` 생성 | `fail`, `hang` |
| `fake_hw` | `hw.exe` | `-tcl X -input H -output J`: J에 `{"subcases":[{"name":"Subcase 1","datatypes":[{"name":"Stress","components":["vonMises"]}]}]}`; `FAKE_HW_IMAGE=1`이면 J 폴더에 `contour_1.png`(유효한 1×1 PNG) | `fail` |
| `fake_qsub` / `fake_qstat` / `fake_qdel` | PBS | qsub: `12345.pbs01` 출력, 상태 파일에 기록. qstat: 호출 횟수에 따라 `job_state = Q`→`R`→`F` + `Exit_status = 0` | `submit_fail`, `exit1`, `unknown`(파싱 불가 출력), `not_found` |
| `fake_nvidia_smi` | GPU 조회 | `RTX A6000, 12, 2048, 49140` | `fail` |
| `fake_extract` | `response_extract` 예시 | `--responses J --input H --out C` → C에 `name,value` + 각 응답 1행 | |

### 18.2 시험 환경

- PostgreSQL: `PHYSICSAI_TEST_DATABASE_URL`이 있으면 사용, 없으면 fixture가 `PG_BIN`의 `initdb`/`pg_ctl`로 임시 클러스터를 띄운다(세션당 1회, 시험마다 새 DB 또는 트랜잭션 롤백). PG가 전혀 없으면 DB 시험은 **실패**로 처리(skip 금지).
- 인증: 가짜 대시보드(§5.5). 
- 제한기: Linux에서는 `PosixLimiter`. Windows Job Object 시험은 `@pytest.mark.windows`로 표시하고 Linux에서 skip — **skip은 통과로 기록하지 않는다**(Verifier 표에 "미수행"). 사용자 E2E에서 확인.
- 워커 시험은 워커 루프를 별도 스레드 또는 `run_once()` 함수로 구동하고, lease 만료 시험은 DB 시계 대신 짧은 ttl(1~2초) 설정으로 한다.
- 프런트: vitest + Testing Library, `fetch` 목, 가짜 타이머로 폴링 검증. API 타입은 `backend/openapi.json`에서 생성(`npm run gen:api`), 생성물과 스냅샷 불일치 시 실패.

---

## 19. 리스크·미확정

| # | 항목 | 영향 | 1차 처리 | 해소 방법 |
|---|---|---|---|---|
| U1 | PBS 실제 명령·출력 형식, 입력·결과 경로(path_map) | ④ 검증 | 기본 `none`, command는 placeholder 예시로 가짜 도구 시험 | 사내 확인 후 설정만 교체(2차) |
| U2 | ④ 형상 갱신·메싱의 정확한 SimLab 호출: tpl 렌더 결과 파일 이름·형식(`dir_file_prt = r"./…"`로 보아 Python 스크립트로 추정 → 기본 `simlab_parametered_mesh.py`), 형상과 메싱이 한 번에 되는지 | ④ 체인 | `geom_update`·`mesh` 템플릿과 `predict.rendered_script_name` 설정값, "사내 확인 후 교체" | E2E 체크리스트 E4-3에서 확인 후 설정 교체 |
| U3 | 새 메시 파일 이름(`eps_mesh*` 추정 — 원본이 조립 폴더 복사 시 `eps_mesh*`를 제외하는 데서 유도)과 starter include 연결 방식 | ④ .rad 조립 | `predict.mesh_output_glob`, 선택 템플릿 `rad_assemble` | E4-4 |
| U4 | `BATCHRUN_preview_pred_h3d.tcl`은 tbcload 바이트코드라 내용 확인 불가. 원본 사용처는 결과 목록 JSON 생성이며 컨투어 이미지 생성 여부 미확인 | ④ 컨투어 | A안: TCL 출력 그대로 표시(이미지 있으면 이미지, 없으면 결과 목록 + 문구) | E4-6 결과로 B안(신규 렌더 TCL) 필요 여부 결정 |
| U5 | HPC 학습 로그 형식 | ③-4 loss 곡선 | 플러그형 정규식, 기본 원본 패턴, 실패해도 등록 성공 | 실제 로그 샘플로 파서 추가 |
| U6 | `.psscr`·score stdout의 점수 형식 | ③-5 점수 표시 | `score.parsers` 기본 빈 목록 → "점수 형식 미확인" | E3-5 출력으로 파서 추가 |
| U7 | 평가·예측에 pscfg 전달 필요 여부 — 원본 score·predict 명령에는 pscfg 인자가 없음(`4_testing.py:62`, `5_predict.py:62`) | 결정 12 해석 | 경로만 기록, 기본 템플릿에서 미전달, `{model_pscfg}` placeholder 준비 | 사내 확인 |
| U8 | 응답값 추출 방법(원본 `H3D_StaticMinMax_to_CSV_FAST.tcl` 미반입·단독 인자 미확인) | ④ 응답 표 예측 열 | `response_extract` 템플릿 null → "추출 미구성", 최근접 실측 열은 samples.csv로 동작 | TCL 확보 후 템플릿 지정 |
| U9 | tpl 정수 형식(`%3i`)에 비정수 입력 시 HST의 반올림/절삭 규칙 | ④ 입력 반영 | `half_up` 반올림 + 참고 문구, 설정 `predict.integer_rounding`(`half_up`/`truncate`) | E4-2 |
| U10 | 결정 3의 "admin"을 **전역 관리자**로 해석(대기열이 전역). 본인 작업 취소도 불가(결정 문구대로) | 권한 | 전역 관리자만 순서 변경·취소 | 사용자 확인. 바꾸면 §5.3 표 1줄 변경 |
| U11 | Altair 런처의 `CREATE_BREAKAWAY_FROM_JOB` 사용 여부, 메모리 한도 도달 시 동작, HyperWorks 배치의 비대화형 세션(서비스 세션 0) 동작 | 실행 실패 | BREAKAWAY 불허, 1차는 워커를 로그온 사용자 콘솔에서 실행 | E1 |
| U12 | 홀드아웃 분할 단위: run당 h3d가 여러 개면 파일 단위 분할이 학습·평가 누설 | 평가 신뢰도 | `split_group` 설정(`file` 기본, `parent_dir` 선택) | E3-1에서 폴더 구조 확인 후 기본값 결정 |
| U13 | hooks 폴더 사용 여부 | ③-1, ④ | 빈 hooks 폴더, `--hooks-dir` 미전달 | 필요 시 2차 |
| U14 | 대시보드 운영 Caddy 경로 추가·쿠키 공유 실제 동작 | 운영 접속 | 1차는 개발 스크립트(포트 공유 쿠키) | §20 D1, E0 |
| U15 | 학습 패키지 하드링크: HPC가 공유폴더를 통해 읽을 때 하드링크 파일 동작 | ③-2 | `link_mode` 설정 | E3-2 |
| U16 | 데이터셋 수가 적을 때 10% 홀드아웃(최소 1개) 점수의 대표성 | 평가 | 화면에 평가 개수 표시 | 운영 판단 |

---

## 20. 대시보드 측 요구사항

**1차 구현에는 대시보드 코드 변경이 필요 없다**(기존 `/api/auth/me`·`/api/projects`로 충분). 아래는 운영 반영(2차)과 계약 유지 요청이다. 대시보드 저장소는 이 작업에서 수정하지 않는다.

| # | 구분 | 내용 | 근거 |
|---|---|---|---|
| D1 | 운영 배포(2차) | `deploy/windows/Caddyfile.intranet.template`에 catch-all `handle`(36-43줄) **앞에** `handle /physicsai/api/* { reverse_proxy 127.0.0.1:8100 }`와 `handle /physicsai/* { root * <physicsai>/frontend/dist; uri strip_prefix /physicsai; try_files {path} /index.html; file_server }` 추가. 기존 `@api path /api /api/*`(17-20줄)는 `/physicsai/api`와 겹치지 않음 | Caddyfile 템플릿 |
| D2 | 계약 고정 | 쿠키 이름 `analysis_canvas_session`, `Path=/`, `SameSite=Strict` 유지. 바꾸면 PhysicsAI 설정 `auth.cookie_name` 동시 변경 필요 | `security.py:45`, `routers/security.py:278-286` |
| D3 | 계약 고정 | `GET /api/auth/me` 응답의 `id, username, display_name, account_status, is_global_admin, memberships[{project_id, role}]` 필드와 Bearer 인증 허용 유지 | `routers/security.py:311-334`, `security.py:190-196` |
| D4 | 계약 고정 | `GET /api/projects`의 `id, name, product_name`과 "모든 ACTIVE 사용자 조회 가능" 유지 | `adapters/http/routers/projects.py:18-23` |
| D5 | 선택(편의) | 대시보드 사이드바에 외부 링크 "AI 예측"(`/physicsai/`) 추가. 메뉴 정책 표(`access_policy.py:115-133`)에 넣을지는 대시보드 쪽 결정 | |
| D6 | 선택(편의) | 로그인 후 복귀 경로(`?next=/physicsai/...`, 같은 origin 상대경로만 허용) 지원. 없으면 사용자가 로그인 후 `/physicsai/`로 다시 이동 | |
| D7 | 선택(운영) | 서비스 간 introspection을 감사·속도 면에서 분리하고 싶으면 `GET /api/auth/introspect`(같은 응답 + `exp`) 신설. 1차는 불필요 | |

---

## 21. 구현 분해와 파일 소유권

공용 파일은 소유자만 수정하고 다른 쪽은 요청한다. `docs/`·`AGENTS.md`·`README.md`는 Plan 소유(구현 에이전트는 수정 제안만).

### 21.1 Impl-Backend 소유: `pyproject.toml`, `backend/**`, `worker/**`, `migrations/**`, `config/**`, `scripts/**`, `.gitignore`

| 경로 | 내용 |
|---|---|
| `pyproject.toml` | 패키지 `physicsai_core`, `physicsai_api`(where=`backend`), `physicsai_worker`(where=`worker`), 의존성(§4.5), pytest 설정 |
| `migrations/alembic.ini`, `env.py`, `versions/0001_initial.py` | §6 전체 + `audit_events` + `worker_slot` 초기 행 + 시퀀스 `job_queue_seq` |
| `backend/physicsai_core/config.py` | YAML 로드·검증(§14), 템플릿 검증(§9) |
| `backend/physicsai_core/paths.py` | 경로 검사(§17.3), Study 경로, 백업 이동 |
| `backend/physicsai_core/db/` | `engine.py`, `tables.py`(SQLAlchemy Core), `repositories/{studies,datasets,models,param_sets,jobs,queue,notifications,hpc,audit}.py` — 상태 전이 CAS, claim/renew/release |
| `backend/physicsai_core/state_machine.py` | §7.2 전이 표 |
| `backend/physicsai_core/commands.py` | 템플릿 펼침·값 검사(§9) |
| `backend/physicsai_core/parsers/` | `loss.py`, `score.py`, `xydata.py`, `log_errors.py` |
| `backend/physicsai_core/param_sets.py`, `tpl_render.py`, `nearest.py`, `dataset_split.py` | §15.4, §8.9, §8.8, §8.4 |
| `backend/physicsai_core/notifications.py` | 이벤트 생성·MY_TURN_NEXT 재계산 |
| `backend/physicsai_core/hpc/` | `gateway.py`, `none.py`, `command.py`, `adapter.py` |
| `backend/physicsai_api/main.py` | 앱, `/physicsai/api` 접두, 예외 처리기 |
| `backend/physicsai_api/auth.py` | 대시보드 introspection·캐시·dev_static·CSRF 헤더 |
| `backend/physicsai_api/routers/` | `status.py`, `queue.py`, `studies.py`, `datasets.py`, `models.py`, `param_sets.py`, `jobs.py`, `artifacts.py`, `notifications.py`, `admin.py` |
| `backend/physicsai_api/schemas/`, `services/` | Pydantic 모델(§10), use case |
| `backend/openapi.json` | 생성·커밋(`python -m physicsai_api.export_openapi`) |
| `backend/tests/` | API·저장소·상태 머신·파서·설정·보안 정적 시험, `fake_tools/`, `conftest.py`(PG·가짜 대시보드) |
| `worker/physicsai_worker/` | `__main__.py`, `runtime.py`(스레드), `claim.py`, `executor.py`, `steps/{dataset,package,model_register,evaluate,predict,verify}.py`, `limiter/{base,windows_job,posix,null}.py`, `resources.py`, `housekeeping.py`, `lockfile.py` |
| `worker/tests/` | 워커 시험(가짜 도구), `@pytest.mark.windows` Job Object 시험 |
| `config/platform.example.yaml` | 이 계약의 설정 스키마(값 변경 시 Plan과 합의) |
| `scripts/` | `dev-db-init`, `dev-backend`, `dev-worker`, `dev-frontend`, `test-all` (.ps1·.sh) |

### 21.2 Impl-Frontend 소유: `frontend/**`

| 경로 | 내용 |
|---|---|
| `frontend/package.json`, `vite.config.ts`(base `/physicsai/`, dev 5174, proxy), `tsconfig.json`, `index.html` | |
| `frontend/src/api/` | `client.ts`(상대경로, `X-PhysicsAI-Request` 헤더, ETag, 오류 매핑), `generated/`(openapi-typescript 산출) |
| `frontend/src/app/` | `App.tsx`, `routes.tsx`, `AuthGate.tsx`(401 → 대시보드 로그인 안내) |
| `frontend/src/shell/` | `TopBar`, `PathBar`, `StageStepper`, `RightPanel`, `NotificationBell`, `NotificationDrawer`, `ToastHost`, `DeferredStageNotice` |
| `frontend/src/panels/` | `QueuePanel`, `WorkerResourcePanel`, `ModelPanel` |
| `frontend/src/stages/stage3/` | `DatasetCreateCard`, `PackageExportCard`, `HpcTrainingNotice`, `ModelRegisterCard`, `EvaluateCard`, `ModelTable` |
| `frontend/src/stages/stage4/` | `ParamSetCard`, `ParamInputTable`, `RangeNote`, `PredictResult`, `ContourPreview`, `CurveChart`, `ResponseTable` |
| `frontend/src/components/` | `LossChart`(SVG), `JobLogViewer`, `PathInput`(경로 + 확인), `JobStatusBadge`, `ProgressBar` |
| `frontend/src/hooks/` | `usePolling`(가시성·ETag), `useMe`, `useNotifications` |
| `frontend/src/**/__tests__/` | 컴포넌트·훅 시험 |

### 21.3 순서·인터페이스

1. Impl-Backend가 `0001_initial`·스키마·`openapi.json`을 먼저 커밋 → Impl-Frontend가 타입 생성. 그 전에는 프런트가 §10을 보고 목 데이터로 진행.
2. API 응답 모양 변경은 이 계약 수정(Plan) → `openapi.json` 갱신 → 프런트 반영 순서.

---

## 22. Verifier 체크리스트(완료 기준)

각 항목은 자동 시험 이름 또는 명시적 수동 증적이 있어야 완료. `windows` 표시 시험을 Linux에서 skip한 것은 통과가 아니라 "미수행 → 사용자 E2E"로 기록.

| ID | 기준 | 방법 |
|---|---|---|
| V-DB-1 | 빈 PG에 `alembic upgrade head` 성공, `downgrade`는 `RuntimeError`(데이터 보호) | PG |
| V-DB-2 | CHECK 위반 거부: holds_slot, queue_seq, lease identity, worker_slot id=1 | PG |
| V-DB-3 | 같은 Study·job_type 비종료 작업 2개 → 409 `STUDY_JOB_BUSY` | API |
| V-DB-4 | DB에 파일 본문 없음: 모든 JSONB 컬럼 스키마가 §6 정의와 일치(스키마 시험), 로그 본문 컬럼 없음 | 단위 |
| V-AUTH-1 | 쿠키 → 가짜 대시보드 `/api/auth/me` Bearer 호출, 200 ACTIVE 통과 / PENDING 403 / 401 / 403 / 503 / 타임아웃 503 매핑 | API |
| V-AUTH-2 | introspection 캐시 TTL(30초) 동작, 실패 비캐시, 토큰 원문이 로그·DB에 없음 | 단위 |
| V-AUTH-3 | 권한 표(§5.3): general/비멤버 조회 가능·실행 403, power 실행 가능·취소 403, 전역 관리자 이동·취소 가능, 남의 작업 재시도 403 | API |
| V-AUTH-4 | 비GET에 `X-PhysicsAI-Request` 없으면 403 | API |
| V-AUTH-5 | `dev_static`은 profile=prod 또는 0.0.0.0 바인딩에서 기동 거부 | 단위 |
| V-SM-1 | §7.2 전이 표 전 항목 허용, 그 외 `IllegalTransition` | 표 기반 |
| V-SM-2 | FIFO: SLOT 작업 3개 → 순번 1,2,3, claim 순서 동일. LIGHT 작업은 슬롯과 무관하게 실행 | PG |
| V-SM-3 | 관리자 순서 이동 후 claim 순서가 바뀜, QUEUED 아닌 대상 409 | PG |
| V-SM-4 | 취소: QUEUED 즉시 / RUNNING은 `cancel_check_interval_s` 내 감지 후 프로세스 트리 종료(fake `hang` + 자식) | 가짜 도구 |
| V-SM-5 | 재시도: 실패 step부터 새 작업, 이전 성공 산출물 재사용 | 가짜 도구 |
| V-SM-6 | 실행 시간 한도 없음: 설정·코드에 step timeout 없음(정적), 장시간 fake(`hang` 30초) 작업이 자동 종료되지 않음 | 정적·가짜 |
| V-LS-1 | lease 만료 → `INTERRUPTED`(`WORKER_LOST`), 슬롯 회수, 알림 | PG(짧은 ttl) |
| V-LS-2 | renew 실패 시 워커가 상태를 쓰지 않고 프로세스 종료 | 단위 |
| V-LS-3 | 두 연결 동시 claim → 승자 1 | PG |
| V-LS-4 | lease_token이 어떤 API 응답(관리자 포함)에도 없음 | 응답 스냅샷 |
| V-JO-1 | Job Object: CPU rate hard cap 값, BELOW_NORMAL, JobMemoryLimit, KILL_ON_JOB_CLOSE(QueryInformationJobObject) | windows |
| V-JO-2 | 손자 프로세스가 같은 Job(`IsProcessInJob`) | windows |
| V-JO-3 | 취소 시 TerminateJobObject로 트리 종료, 워커 강제 종료 시 트리 종료 | windows |
| V-JO-4 | Job 할당 실패 주입 → 프로세스 미실행 + `JOB_OBJECT_ASSIGN_FAILED` | 단위(주입) |
| V-JO-5 | 유효 코어·메모리 계산(auto_detect on/off), cpu_rate 경계 | 단위 |
| V-JO-6 | Linux PosixLimiter: nice 적용, killpg 트리 종료, `cpu_cap_enforced=false` 표시 | Linux |
| V-CMD-1 | 기본 템플릿 펼침 결과가 §8·§9.2의 원본 인용 argv와 정확히 일치(골든: fake 기록 파일) | 가짜 도구 |
| V-CMD-2 | 모든 실행이 `shell=False` 배열, 문자열 명령 없음, API 패키지에 subprocess 없음 | 정적 |
| V-CMD-3 | 메타문자·제어문자·공백(argv[0] 외) 값 거부, 미허용 placeholder·argv[0] 설정 거부 | 단위 |
| V-CMD-4 | `backend/`·`worker/` 코드에 `Program Files`/Altair 경로 하드코딩 없음(설정 예시·시험 제외) | 정적 |
| V-CMD-5 | 오류 정규식 일치 시 종료코드 0이어도 `LOG_ERROR_DETECTED`(fake `error_log`) | 가짜 도구 |
| V-CMD-6 | `@cmd_c`가 Windows에서 cmd.exe /c, Linux에서 빈 목록 | 단위 |
| V-CMD-7 | 기존 산출물 `_backup` 이동, 잠김(권한 제거로 모사) 시 `OUTPUT_LOCKED`, 사용자 산출물 삭제 호출 없음(정적: `os.remove`·`unlink`·`rmtree` 사용처가 허용 목록뿐) | 단위·정적 |
| V-DS-1 | ③-1: 재귀 수집·정렬, seed 고정 시 분할 재현, eval ≥1, train∩eval=∅, `parent_dir` 그룹 분할 | 단위 |
| V-DS-2 | ③-1: yaml 2개가 원본 형식(selection: {} 포함), psdata 크기 판정(fake `small` → `OUTPUT_TOO_SMALL`) | 가짜 도구 |
| V-DS-3 | ③-2: 패키지에 train psdata만(eval 없음), COMMANDS.txt 내용, 하드링크 실패 시 복사 | 단위 |
| V-MR-1 | ③-4: psmdl/pscfg 0개·2개 거부, 로그 0개 MISSING, 2개 이상 선택 요구 | API |
| V-MR-2 | ③-4: 기본 파서로 epoch/loss 추출, 최소 loss·epoch, 다운샘플(첫·끝·최소 보존, ≤2000), 형식 불일치 로그 → `UNRECOGNIZED`이고 등록 성공 | 단위 |
| V-MR-3 | ③-4: 허용 루트 밖·링크·`..` 경로 거부 | API |
| V-EV-1 | ③-5: eval psdata로 score 실행, 기존 psscr·predictions 백업, `score.parsers`로 metrics, 파서 없으면 UNRECOGNIZED | 가짜 도구 |
| V-EV-2 | Final 지정·재지정·해제, ARCHIVED 모델 지정 거부, Final 보관 거부, sha256 변경 → INVALID + `INPUT_CHANGED` | API |
| V-PS-1 | 파라미터 세트 검증: §15.4 각 실패 사례(`PARAM_TPL_MISMATCH` 포함), 정상 등록 시 정규화본 복사·is_current 전환 | API |
| V-PR-1 | predict/check: 범위 밖 판정, 정수 반영, 최근접 거리(min=max 제외)·동률 규칙, 샘플 없을 때 nearest null | 단위 |
| V-PR-2 | PREDICT 체인: tpl 렌더(변수 치환·parameter 줄 제거), 조립 복사 규칙(eps_mesh 제외 후 새 메시 복사, starter 1개), env `EDS_TNS_ACTVN_CHCKPT=1`, Final 모델 기본 사용 | 가짜 도구 |
| V-PR-3 | 템플릿 null: `mesh`·`response_extract`는 SKIPPED, `geom_update` null이면 작업 생성 409 `TEMPLATE_NOT_CONFIGURED` | API |
| V-PR-4 | 결과: 이미지 있으면 PREVIEW_IMAGE, 없으면 JSON만; 커브 있을 때만; 응답 표(예측·최근접 실측·차이%) | 가짜 도구 |
| V-HPC-1 | `none`: status message, `PREDICT_VERIFY` 409 `HPC_NOT_CONFIGURED` | API |
| V-HPC-2 | `command`: 가짜 qsub/qstat 파싱, 상태 매핑, exit code, not_found, UNKNOWN→LOST, 슬롯 해제 후 다른 작업 claim, 회수 후 재대기열(T14) | 가짜 도구 |
| V-HPC-3 | 템플릿 검증·치환 값 주입 시도(`;`, 줄바꿈, `$(…)`, `&`) 거부, `adapter`는 configured=false·import 없음 | 단위·정적 |
| V-NT-1 | 이벤트별 알림 생성(§13.1), MY_TURN_NEXT 1회, 본인 것만 조회, 읽음 처리, 30일 정리 | PG |
| V-SEC-1 | multipart 라우트 0개, pickle/joblib/dill/torch.load import 없음 | 정적 |
| V-SEC-2 | 산출물 다운로드 id로만, content-type 화이트리스트, 크기 상한 | API |
| V-SEC-3 | API 프로세스가 외부 프로그램을 실행하지 않음(정적: `physicsai_api`에 subprocess import 없음) | 정적 |
| V-SEC-4 | `ai_root`·허용 루트가 SPDM 루트와 겹치면 설정 오류 | 단위 |
| V-SEC-5 | 감사 이벤트 기록(§17.6 동작 전부) | API |
| V-CFG-1 | §14.3 각 실패 사례, 알 수 없는 키 거부 | 단위 |
| V-CFG-2 | 설정 변경 감지 후 재검증, 실패 시 새 claim 중지 | 단위 |
| V-API-1 | 오류 코드·HTTP 상태가 §10과 일치 | API |
| V-API-2 | 로그 커서 UTF-8 경계·limit 상한·404, ETag/304 | API |
| V-API-3 | `openapi.json` 최신(생성 결과와 동일), 프런트 생성 타입 컴파일 | CI |
| V-FE-1 | 셸: 경로바·스텝퍼(①②⑤ 비활성 안내)·우측 패널 3종 렌더 | 컴포넌트 |
| V-FE-2 | 권한별 버튼: general 비활성, power 실행, 전역 관리자만 대기열 이동·취소 | 컴포넌트 |
| V-FE-3 | 폴링 주기(§10.9)와 숨김 탭 중지·복귀 즉시 갱신 | 가짜 타이머 |
| V-FE-4 | 알림: 새 항목 토스트(로드 이전 항목은 토스트 없음), 벨 미읽음 수, 이력 패널 읽음 처리 | 컴포넌트 |
| V-FE-5 | ③: 경로 확인 요약, 모델 표 열, loss 곡선(선형/로그), Final 지정 | 컴포넌트 |
| V-FE-6 | ④: 값 채우기 3방식, 범위 밖 작은 문구(배지 없음), PBS 버튼 비활성 툴팁, 결과 3영역 조건부 표시 | 컴포넌트 |
| V-FE-7 | 401 시 대시보드 로그인 안내 | 컴포넌트 |
| V-FE-8 | 3840×2160 뷰포트 스크린샷(가로 스크롤 없음, 우측 패널 폭 범위)과 1280px 폭 | 수동 증적(Playwright 가능하면 자동) |
| V-REG-1 | `scripts/test-all` 전체 통과(Linux, PG 포함) | CI |
| V-E2E-1 | 사용자 E2E 체크리스트 결과 기록(미수행 항목은 "미수행") | 사용자 증적 |

---

## 변경 메모 (Impl-Backend, 2026-10-08 — 본문 미수정, Plan 확인 요청)

본문과 다르거나 본문에 없던 구현 결정. Plan이 수용하면 본문에 반영, 아니면 되돌림 지시.

| # | 위치 | 내용 |
|---|---|---|
| B1 | §10.2 `/status` vs §10.9 | §10.9는 폴링 주기를 `/status`에 싣는다고 하나 §10.2 응답 표에 없음 → `ui:{poll_*_ms…}` 추가. §5.2 로그인 링크용 `auth:{mode, login_url}`도 추가. 워커가 보고한 설정 오류는 `config.errors`에 `worker:<key>`로 합침 |
| B2 | §10.1 목록 페이지 | 응답이 배열이라 다음 커서 위치가 없음 → `X-Next-Cursor` 응답 헤더. `GET /notifications`는 `cursor`(더 오래된 쪽)도 받음(무한 스크롤) |
| B3 | §9.1·§9.2 vs §18.1 | `response_extract`의 argv[0]은 `{hw}`만 가능(허용 placeholder) → 별도 `fake_extract`를 템플릿으로 가리킬 수 없음. 시험은 `fake_hw`가 `--responses` 인자를 받으면 fake_extract와 같은 동작을 하도록 구현(fake_extract 파일도 유지) |
| B4 | §10.3 `stage_status` | 형태 미정 → `{"3": {latest_job_id, latest_job_type, latest_state}, "4": {…}}` |
| B5 | §10.4·§10.5 응답 | `Dataset.package_rel`, `Job.attention_code`, `Artifact.file_name`(rel_path 대신) 추가. `JobStep.command`는 `?include=commands`(전역 관리자)일 때만 채움 |
| B6 | §8.7 EV_PARSE | psscr를 등록하지 않으므로 `SCORE_FILE` artifact는 `E/score_summary.json`(`{status, metrics, score_rel}`) |
| B7 | §15.4 등록 | 원본 파일 사본 위치를 `04_params/<id>/original/`로 정함 |
| B8 | §10.6 PREDICT params | 저장 시 기본값을 풀어 `model_id`(Final)·`param_set_id`(current)를 확정 기록(재시도 재현성). DATASET_CREATE도 기본값(holdout·seed·split_group·options)을 채워 저장 |
| B9 | §10.5 재시도 | `from_step` 기본값 = 첫 FAILED/CANCELED/PENDING step, 그보다 뒤 지정은 422. 이전 step은 `SKIPPED`("이전 작업 산출물 재사용"). 작업 폴더는 재시도 체인의 최초 작업 id 기준. PREDICT_VERIFY는 항상 1단계부터(HPC 제출 재사용 안 함) |
| B10 | §11.2 renew | heartbeat 스레드 대신 작업별 LeaseKeeper 스레드가 `heartbeat_interval_s`마다 renew(동작 동일) |
| B11 | §5.5 dev_static | `GET /projects`는 대시보드 없이 `memberships` 프로젝트 + `dev`를 합성해 돌려줌 |
| B12 | §10.4 PATCH /models | INVALID → ACTIVE 변경은 409 `MODEL_NOT_ACTIVE`(코드 목록에 없던 경우) |
| B13 | §4.6 vs 작업 지시 | 스크립트 이름은 계약대로 `scripts/dev-db-init|dev-backend|dev-worker|dev-frontend|test-all`(.sh/.ps1). dev-backend는 포트를 설정에서 읽으려고 `python -m physicsai_api.serve` 사용 |
| B14 | §6.2·§6.7 | `migrations/versions/0001_initial.py`는 `physicsai_core.db.tables` 메타데이터로 생성(이후 변경은 명시적 DDL migration). `jobs`에 CHECK `FAILED/INTERRUPTED → failure_code NOT NULL` 추가 |
| B15 | §8.3·V-CMD-7 | root 권한 시험 환경에서는 "권한 제거로 잠김 모사"가 불가 → `os.replace` 실패 주입으로 `OUTPUT_LOCKED` 시험 |
| B16 | §10.5 신규(메인 결정) | `GET /jobs/{job_id}/artifacts/input.zip` — ④ "입력파일 받기". PREDICT 작업의 `04_predict/<최초 작업 id>/INPUT/` 직계 일반 파일(.rad·.inc)을 zip(deflate, zip64)으로 스트리밍(1 MiB 단위, 전체 적재 없음). 권한: 로그인 사용자 전원. RAD_ASSEMBLE 완료(또는 재시도 재사용) 전이거나 PREDICT가 아닌 작업은 409 `INPUT_NOT_READY`, 없는 작업 404. 링크·하위 폴더 제외(경로 탈출 방지). `Content-Disposition: attachment; filename="<study>_<job8>_INPUT.zip"` |
| B17 | §10.1 "절대경로 제외" 예외(메인 결정) | 탐색기 붙여넣기용 표시 경로 추가(`ai_root` + Study 폴더 + 상대경로, `ai_root`가 드라이브 문자 형식이면 `\` 구분): `Study.folder_display_path`, `Dataset.dataset_display_path`·`package_display_path`(패키지 없으면 null), `Model.stored_display_path`, `Job.input_display_path`(PREDICT, 입력 준비 후만, 그 외 null). 표시 전용이며 요청 입력으로 받지 않는다 |
| B18 | §10.5 산출물 조회(확인) | 컨투어 이미지·커브는 기존 계약 경로 그대로: `GET /jobs/{id}/artifacts`(kind `PREVIEW_IMAGE`·`PREVIEW_JSON`·`CURVE_JSON`·`RESPONSE_TABLE`) → `GET /artifacts/{artifact_id}/content`. id는 `Job.result`의 `image_artifact_ids`·`preview_json_artifact_id`·`curve_artifact_id`·`response_table_artifact_id`에도 있음. 이름 기반 신규 엔드포인트는 만들지 않음 |
| B19 | §9.1 env, §14.2 설정 | 자식 프로세스(LOCAL step·GPU 조회·HPC 명령) 환경 = 허용목록만: `SystemRoot`·`windir`·`ComSpec`·`PATH`·`PATHEXT`·`TEMP`·`TMP`·`USERPROFILE`·`HOME` 등 기본 이름 + `ALTAIR_*`·`*_LICENSE_*`·`*_LICENSE`·`EDS_*`(HPC는 `PBS_*` 추가) + 새 설정 키 `worker.env_passthrough`(fnmatch 패턴 목록, 기본 `[]`, 예시 yaml 미반영 — config 소유 작업 시 추가 필요). `PHYSICSAI_*`·`*PASSWORD*`·`*SECRET*`·`*TOKEN*`·`PG*`와 `database.url_env` 이름은 설정과 무관하게 항상 제외. step 추가분(`predict.env`)은 그 뒤에 더함 |
| B20 | §17.3 경로 | 허용 루트는 설정값 그대로와 realpath 두 형태로 비교(매핑 드라이브·SUBST·UNC). 루트 아래 구성요소의 링크 검사 + 입력 realpath가 루트 realpath 안인지 확인. "reparse point 거부"는 실제 링크(IO_REPARSE_TAG_SYMLINK·MOUNT_POINT=junction)만 — dedup·클라우드 파일 등 다른 reparse 태그는 허용. Study 기준 상대경로·백업도 양쪽 realpath로 계산 |
| B21 | §8.3 백업 | 같은 백업 경로가 이미 있으면 덮어쓰지 않고 `name~N.ext`. Study 밖 대상은 존재 여부와 무관하게 거부 |
| B22 | §6.2 folder_name | 정규식에 더해 Windows 예약 이름(CON·PRN·AUX·NUL·COM1-9·LPT1-9, 대소문자·확장자 무관)과 끝 공백·마침표 거부 → 422 `INVALID_PARAMS` |
| B23 | §8.4·§15.2 ③-1 입력 | AI 루트 자체와 Study 산출 폴더(`03_dataset`·`03_package`·`03_model`·`04_params`·`04_predict`·`logs`·`_backup`) 안은 422 `PATH_UNSAFE`(워커 DS_SCAN에서도 재검사 → `INPUT_INVALID`). Study 폴더 자체를 주면 산출 폴더는 수집 제외, `_backup`은 어느 깊이든 제외 |
| B24 | §9.1 치환 값 | `.bat`·`.cmd` 실행 파일이거나 `@cmd_c`를 쓰는 템플릿은 치환 값에 `; , = ( )`도 거부(실행 파일 경로 자체는 제외) |
| B25 | §11.5 WindowsJobLimiter | `OpenThread` 실패 또는 `ResumeThread` = (DWORD)-1 → `TerminateProcess` + `TerminateJobObject` 후 step FAILED `JOB_OBJECT_ASSIGN_FAILED` |
| B26 | §8.6 MR_VALIDATE | 워커가 `log_file`(파일 이름만·직계·링크 금지·안전 문자)과 psmdl·pscfg(링크·폴더 밖 실경로 금지)를 다시 검증, 위반 시 `INPUT_INVALID` |
