# 계약: MCP 기능(LLM 클라이언트 조작 — 플랫폼 준비 + MCP 서버) — mcp

작성: Plan, 2026-10-21(초안 `mcp-ready.md`, 같은 날 MCP 기능 전체로 확장·이름 변경). 초안 기준: 브랜치 `feat/r1-mcpready` 18dc408(migration HEAD `0018_equiv_check`). **구현 기준: v0.2.3(b05d34d, HEAD `0019_extract_filter`)** — 릴리스 v0.2.4([roadmap.md](../roadmap.md)). **구현 반영: v0.2.4 통합본 `feat/r1-v024` 8206870**(변경 메모 MR-C2). v0.2.7 추가: 웹 "AI 연결(MCP)" 페이지(§23, MR-C3).
우선순위: **이 문서 > [platform.md](platform.md) §5(인증)·§10.1(API 공통)·§17.6(감사)** — 이 문서가 바꾸는 것은 §2 "기존 규칙 예외" 표에만 있다. 배포 설정은 [phase3.md](phase3.md) 기준(decisions 2026-10-20 "phase3 설정이 배포 설정").
ID 규칙: 결정 `MR-n`, 시험 `V-MCP-n`, 변경 메모 `MR-Cn`.

## 0. 사용자 결정·설계 원칙(2026-10-20·21)

1. 대상 클라이언트(2026-10-21 사용자 확정 — "MCP는 claude, chatgpt(codex), gemini 지원"): **Claude Code CLI·Claude Desktop, OpenAI Codex CLI, Gemini CLI** + 사내 LLM 클라이언트(MCP 지원 시). **전제: Claude·Codex·Gemini 모델은 사내 on-premise 배포본을 쓰고, 클라이언트는 사내 모델 엔드포인트에 연결한다**(2026-10-21 사용자 확인) — 초안의 "폐쇄망 사내 LLM만" 전제와 충돌 없음. 클라이언트의 모델 엔드포인트 설정은 각 사내 배포 안내를 따른다(플랫폼 범위 밖). 플랫폼(MCP 서버)은 외부로 나가는 호출을 하지 않고, 클라이언트가 사용자 PC에서 사내망 주소로 접속한다. MCP 미지원 클라이언트를 위해 **OpenAI 호환 function 정의**를 병행한다. ChatGPT 웹·데스크톱 앱 커넥터는 범위 밖(§21.2).
2. 범위는 **MCP 기능 전체**(2026-10-21 사용자 확정): 플랫폼 쪽 준비(인증·확인 절차·감사·요약·스펙, §4~§15) + **MCP 서버 구현·배포**(공식 MCP Python SDK, Streamable HTTP 마운트 + stdio 실행기, §20) + 클라이언트 연결 가이드(§21, [docs/manual/mcp-clients.md](../manual/mcp-clients.md)).
3. **기능을 나중에 추가해도 MCP 쪽 수정이 최소화**되어야 한다(§15): 도구 정의는 openapi `x-mcp`에서 자동 생성, 작업 생성은 공통 작업 계약으로 일원화, 요약은 레지스트리, 용어집은 코드 자동 추출, 누락은 정적 시험이 잡는다, 깨지는 변경은 새 도구 이름.
4. 기본값으로는 기존 동작 불변: `mcp.enabled: false`(토큰 인증·`/mcp/*` 전부 꺼짐).

## 1. 범위

| 범위 | 비범위(후속) |
|---|---|
| 사용자별 API 토큰(발급·폐기·만료 ≤ 30일·범위), Bearer 인증 경로 | ChatGPT 웹·데스크톱 앱 커넥터(OAuth 2.1 인가 서버 + 외부 접근 필요, §21.2) |
| **MCP 서버**: 백엔드 마운트 Streamable HTTP `/physicsai/mcp` + stdio 실행기 `physicsai-mcp`(같은 도구 정의, §20) | MCP OAuth 인가·동적 클라이언트 등록 |
| 클라이언트 연결 가이드·설정 예시 5파일(Claude Code·Claude Desktop·Codex CLI·Gemini CLI HTTP·stdio, §21.1) | MCP prompts·sampling·elicitation 기능 |
| 공통 작업 계약 `/mcp/jobs*`(plan → confirm → run → status → summary → cancel) | 기존 생성 API(`POST /studies/{id}/jobs` 등)의 dry-run 개조 — 웹 흐름은 손대지 않음 |
| 토큰 요청 감사 로그·조회·보존 | 임베딩 기반 문서 RAG·run 메타 의미 검색(§12.2, 사내 임베딩 모델 있을 때만) |
| 요약 API 레지스트리 `/mcp/summary/*` | 대시보드 코드 변경 |
| openapi `x-mcp` 확장·도구 스펙 생성기(MCP + OpenAI 형식)·용어집 | LLM 프롬프트·에이전트 정책 |
| 토큰별 호출 제한(429) | 다중 백엔드 프로세스용 분산 제한(현재 uvicorn 단일 프로세스, `serve.py`) |
| 연결 점검 도구 `ping`·`whoami`, 리소스(용어집·스키마 사전) | |
| 파라미터 벡터 유사 설계 검색 API(§12.1, **포함 여부 미결 Q2** — 미정 시 제외로 진행) | |

## 2. 현황(코드 확인, 18dc408)

| 항목 | 현재 | 근거 |
|---|---|---|
| 인증 | 대시보드 세션 토큰을 매 요청 `/api/auth/me` introspection(30초 캐시, 키 sha256). 쿠키 `analysis_canvas_session` 우선, 없으면 `Authorization: Bearer` — **Bearer 값도 대시보드로 전달**됨 | `physicsai_api/auth.py`·`deps.py:extract_token`, platform §5.2 |
| 프록시 | 운영은 대시보드 Vite 프록시(또는 Caddy 스니펫 `deploy/caddy/physicsai.caddy`)가 `/physicsai/api/*`를 127.0.0.1:8100으로 전달. 백엔드는 프록시 헤더로 신원을 판정하지 않음(relay만 프록시 헤더 부재 검사) | main.py, scx_relay.md §2 |
| 권한 | 역할 `general/power/admin`(프로젝트별) + `is_global_admin`. 조회=ACTIVE 전원, 실행=power+, 대기열·작업 취소·남의 재시도=전역 관리자. **DB에 역할 복제 금지** | platform §5.3, `services/jobs.py:cancel_job` |
| CSRF | 비GET은 `X-PhysicsAI-Request: 1` 필수 | deps.py |
| 감사 | `audit_events`(id, occurred_at, user_id, username, action, target_type, target_id, detail JSONB, request_id, client_ip) — 성공한 도메인 쓰기만 서비스 트랜잭션 안에서 기록. 조회 API 없음 | schema_0001.py, `services/common.py:audit` |
| openapi | `python -m physicsai_api.export_openapi` → `backend/openapi.json`(정렬·결정적). operationId = FastAPI 기본(`<함수>_<경로>_<메서드>`), **프런트 시험이 일부 operationId를 고정**(`mockContract.test.ts`) | export_openapi.py |
| 작업 생성 | 범용 `POST /studies/{id}/jobs {job_type, params}`(TD_DOE_GEN·TD_SOLVE·PREDICT·PREDICT_BATCH·DATASET_CREATE …) + 전용 생성 `POST …/surrogate-opts`·`…/equiv-checks`·`…/fem-verifications`·`/surrogate-opts/{id}/verify`·`/param-sets/{id}/previews` | job_types.py(28종), routers |
| 미리보기(dry-run 성격) | `POST …/predict-batches/preview`(count·estimate_min)·`…/surrogate-opts/preview`·`…/fem-verifications/preview`·`…/equiv-checks/preview`(예상 바이트) — 모두 동기·저장 없음. ①-3 DOE·①-4 PBS는 미리보기 없음 | phase3 §14.7·s12_s13·s16·equiv-check §6 |
| 동시 실행 | 레인 SLOT(전역 슬롯 1)·LIGHT·PREVIEW(슬롯 미사용, 동시 1), HPC 대기는 슬롯 미점유. `train_data.max_multi_execution` 8, `platform_parallel_default` 4, `fem_verify.max_active` 4, `equiv_check.max_active` 2 | job_types.py, config |
| 로그 마스킹 | `Bearer \S+` → `Bearer ***` 고정 규칙 | masking.py |

### 2.1 기존 규칙 예외(이 문서가 바꾸는 것 — 이 표 밖은 불변)

| 기존 규칙 | 예외 | 이유 |
|---|---|---|
| platform §5.3 "DB에 역할을 복제하지 않는다" | `api_tokens.principal_snapshot`에 발급·갱신 시점 역할 스냅숏 저장(§4.3) | 토큰 요청에는 대시보드 세션이 없어 introspection 불가 |
| platform §5.2 "Bearer 값은 대시보드로 introspect" | 접두 `pai_` Bearer는 **대시보드로 보내지 않고** 토큰 테이블로 검증 | 토큰 유출 경로 축소, 대시보드 변경 없음 |
| platform §5.4 CSRF 헤더 | 토큰 요청(쿠키 미사용)은 면제 | 쿠키가 없으면 CSRF 대상 아님 |
| platform §5.3 작업 취소 = 전역 관리자 | **같은 토큰이 만든 작업**은 그 토큰(run 범위)이 `cancel_job`으로 취소 가능 | 사내 LLM 오조작 즉시 회수 |

## 3. 결정 요약

| ID | 결정 |
|---|---|
| MR-1 | 기계 인증 = 사용자별 API 토큰 `pai_<id8>_<secret43>`(Bearer). 저장은 sha256(전체 토큰)만, 평문은 발급 응답 1회. 범위 `read < run < admin`(계층) |
| MR-2 | 토큰 주체 = 토큰 소유자. 권한 = min(토큰 범위, 역할 스냅숏). 스냅숏은 소유자의 **세션 introspection 성공 때마다 갱신**, `snapshot_max_age_days` 넘으면 401 `API_TOKEN_STALE` |
| MR-3 | 토큰 요청은 **`x-mcp.tool`이 붙은 operation만** 허용(허용 목록), 그 밖은 403 `API_TOKEN_OPERATION_NOT_ALLOWED`. 토큰 관리 API는 세션 전용 |
| MR-4 | 작업 생성은 공통 작업 계약 `/mcp/jobs*` + **작업 종류 레지스트리 `JOB_KINDS`**로 일원화. 기존 생성 API·웹 흐름 불변(내부적으로 같은 서비스 함수 호출) |
| MR-5 | 비용 큰 종류(`cost: heavy`)는 `plan_job` → 단기 `confirm_token`(기본 600초·1회용·요청 해시 결합) → `run_job`. 토큰 요청에만 강제(`mcp.require_confirm_for_token`) |
| MR-6 | 감사 = 새 테이블 `api_audit`(토큰 요청의 모든 비GET·모든 거부·모든 작업 생성, 본문 미저장). 기존 `audit_events`는 그대로 + `detail.api_token_id` 추가 |
| MR-7 | 요약 = 엔티티 레지스트리 `SUMMARIES` + 공통 봉투, 응답 ≤ `mcp.summary.max_bytes`(8 KiB) |
| MR-8 | `x-mcp` 확장(도구명·위험도·confirm·버전). 기존 operationId 불변, 새 `/mcp/*`만 명시 operationId. 모든 operation은 `x-mcp`(도구 또는 제외 사유) 또는 동결 목록 — 정적 시험 |
| MR-9 | `scripts/gen_tool_specs.py`가 openapi에서 MCP tool JSON·OpenAI function JSON·용어집 JSON을 결정적으로 생성, `--check`를 test-all에 |
| MR-10 | 호출 제한 = 토큰별 분당 요청·분당 plan·동시 진행 작업 상한, 초과 429 + `Retry-After`(프로세스 메모리, 단일 프로세스 전제) |
| MR-11 | 용어집 = 코드 자동 추출(job_types·작업 종류·요약 엔티티·피처 약어·오류 코드·enum) + 사람이 쓰는 동의어·설명 YAML. `GET /mcp/glossary` |
| MR-12 | 깨지는 변경은 새 도구 이름(`<tool>_v2`)·새 작업 종류 이름. 생성기 `--check`가 직전 스펙과 비교해 막는다 |
| MR-13 | 토큰 기한 = esl과 같은 30일 계약: `default_expiry_days` 30, `max_expiry_days` 30(설정 상한도 30 — 발급 시 30일 초과 불가, 짧게는 가능), `snapshot_max_age_days` 30. 즉시 차단은 관리자 폐기(§4.4) |
| MR-14 | MCP 서버 = 공식 MCP Python SDK(`mcp`, 저수준 `Server` — 도구·입력 스키마를 생성 파일에서 동적 등록). 도구 = §9 생성기 출력(x-mcp tool operation), 리소스 = §10 용어집·스키마 사전. **권한 판단 없음**: 모든 도구 호출은 같은 Bearer로 백엔드 HTTP API를 부르는 얇은 래퍼(MR-1~12 그대로 적용) |
| MR-15 | 전송 둘 다, 같은 도구 정의: ① Streamable HTTP를 백엔드 프로세스에 마운트 `/physicsai/mcp`(Bearer `pai_` 필수, `mcp.enabled=false`면 404, stateless·JSON 응답), ② stdio 실행기 `physicsai-mcp`(환경변수 서버 URL + 토큰 → 백엔드 HTTP API) |
| MR-16 | 도구 입력 스키마는 **이식 가능 부분집합**(Gemini 함수 선언이 받는 키워드만, §9.2) 하나로 생성해 MCP·OpenAI 형식에 공통 사용. 도구 이름 `^[a-zA-Z0-9_-]{1,64}$`, 설명 영어+한국어 짧게 병기 |
| MR-17 | 연결 점검 도구 `ping`(`GET /mcp/ping`, 서버 버전·토큰 접두·범위·남은 일수)·`whoami`(기존 `GET /me`) |
| MR-18 | 오프라인 배포: `mcp`와 전이 의존을 `deploy/requirements.lock`에 고정·오프라인 wheel 수집 대상. python-multipart는 SDK 전이 의존으로만 허용(플랫폼 코드 import·multipart 라우트 0 유지 — upload-report UR-C1) |

## 4. 기계용 인증(API 토큰)

### 4.1 토큰 형식·저장

- 형식 `pai_<id8>_<secret>`: `id8` = 소문자 base32 8자(공개 식별자, 목록 표시), `secret` = `secrets.token_urlsafe(32)`(43자). 전체 길이 고정 검사.
- DB에는 `token_hash = sha256(전체 토큰)` hex(유일 인덱스)와 `token_prefix = "pai_<id8>"`만. 평문은 `POST /me/api-tokens` 응답 본문 1회 — 이후 어떤 API도 돌려주지 않는다. 고엔트로피 난수이므로 느린 해시·pepper 불필요(비밀 파일 추가 없음, phase3 D3-41 유지).
- 로그: `Authorization` 값은 기존 마스킹(`Bearer ***`)으로 덮이고, 접근 로그에 헤더를 남기지 않는다. 오류 메시지에 토큰 일부도 넣지 않는다(prefix만 허용).

### 4.2 인증 흐름(`deps.get_principal` 확장 — 세션 경로 코드 불변)

```text
auth = Authorization 헤더
if auth가 "Bearer pai_" 로 시작:                       # 토큰 경로(쿠키 무시)
    mcp.enabled=false            → 401 AUTHENTICATION_REQUIRED (대시보드로 보내지 않음)
    형식 오류·해시 불일치         → 401 API_TOKEN_INVALID
    revoked_at 있음              → 401 API_TOKEN_REVOKED
    expires_at ≤ now             → 401 API_TOKEN_EXPIRED
    now - snapshot_at > snapshot_max_age_days → 401 API_TOKEN_STALE("웹 화면에 한 번 로그인해 권한을 갱신하세요")
    operation에 x-mcp.tool 없음   → 403 API_TOKEN_OPERATION_NOT_ALLOWED
    범위 부족                     → 403 API_TOKEN_SCOPE (required: "run"|"admin")
    호출 제한(§11)                → 429
    Principal = 스냅숏(user_id, username, display_name, is_global_admin, roles) + request.state.api_token_id
    CSRF 헤더 면제
else:                                                  # 기존 세션 경로 그대로
    기존 get_principal(쿠키 우선 → Bearer → 대시보드 introspection)
    성공 + mcp.enabled → 그 사용자의 유효 토큰 스냅숏 갱신(§4.3)
```

- 판정 순서는 platform §5.3에 토큰 단계를 끼운다: 인증(401) → 허용 operation·범위(403) → 호출 제한(429) → 대상 존재(404) → 역할 권한(403 `PERMISSION_DENIED`) → 상태(409).
- 범위 판정: operation `x-mcp.risk`가 `read`면 read+, `run`이면 run+, `admin`이면 admin(+스냅숏 `is_global_admin`). 그 위에 기존 역할 검사(`require_power` 등)가 스냅숏 역할로 그대로 돈다.
- `last_used_at`·`last_used_ip`는 `mcp.token.last_used_update_s`(60초) 간격으로만 갱신(쓰기 폭주 방지).

### 4.3 역할 스냅숏

- 발급 시 세션 Principal의 `{is_global_admin, roles}`를 `principal_snapshot`에 저장, `snapshot_at = now`.
- 세션 introspection **캐시 미스 후 성공**(≤ 30초에 1회/사용자)마다 같은 user_id의 미폐기·미만료 토큰 스냅숏을 갱신(같은 값이면 `snapshot_at`만). 대시보드에서 역할이 빠지면 다음 웹 로그인 때 토큰 권한도 줄어든다.
- 스냅숏 갱신 시 소유자 `is_global_admin`이 false가 되면 admin 범위 토큰은 자동 폐기(`revoked_by = "system:role_change"`).
- 계정 정지(대시보드 SUSPENDED)는 세션 introspection이 403이므로 스냅숏이 갱신되지 않고, `snapshot_max_age_days`(**30일**, MR-13) 후 토큰이 막힌다 — 토큰 최대 기한도 30일이므로 실제로는 만료와 같은 시점(설정을 바꿔도 지켜지는 안전장치). **즉시 차단은 전역 관리자 폐기**(§4.4, 관리자 매뉴얼에 안내). 권한 출처는 역할 스냅숏으로 확정(초안 Q1 종결, 대시보드 서비스 introspection은 후속).

### 4.4 API(세션 전용 — 토큰 요청은 403 `SESSION_REQUIRED`, `x-mcp.exclude`)

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `GET /me/api-tokens` | 로그인 | – | `ApiToken[]`(최신순, 폐기 포함 최근 90일) | 404 `MCP_DISABLED` |
| `POST /me/api-tokens` | 로그인 | `{name, scope:"read"|"run"|"admin", expires_in_days?}` | `201 {token:"pai_…", api_token: ApiToken}` | 403 `API_TOKEN_SCOPE`(run은 어느 프로젝트든 power+ 필요, admin은 전역 관리자), 409 `API_TOKEN_LIMIT`(유효 토큰 ≥ `max_per_user`), 409 `API_TOKEN_NAME_EXISTS`, 422 |
| `DELETE /me/api-tokens/{id}` | 소유자 | – | `204`(멱등, `revoked_at` 기록, 행 삭제 안 함) | 404 |
| `GET /admin/api-tokens?user_id=&active=` | 전역 관리자 | – | `ApiToken[]`(+user_id, username) | |
| `POST /admin/api-tokens/{id}/revoke` | 전역 관리자 | – | `ApiToken` | 404 |

`ApiToken` = `{id, name, scope, token_prefix, created_at, expires_at, last_used_at, revoked_at, revoked_by, snapshot_at, status:"active"|"expired"|"revoked"|"stale"}`. `name` = 1~64자, `^[0-9A-Za-z가-힣 _.-]+$`. `expires_in_days` 생략 = `default_expiry_days`(30), 1~`max_expiry_days`(30, MR-13 — 초과 시 422 `API_TOKEN_EXPIRY_TOO_LONG`, 화면 기본값 30·최댓값 30). 무기한 없음. 갱신(연장) API 없음 — 만료 전 새 토큰 발급 후 클라이언트 설정 교체(esl §9.1과 같음). 발급·폐기는 `audit_events`(`API_TOKEN_CREATE`·`API_TOKEN_REVOKE`)에 기록.

### 4.5 화면(최소, Impl-Frontend)

- 메뉴는 `/status` `features.mcp`가 true일 때만 보인다(false면 메뉴·화면 없음): 상단 바 "내 API 토큰"(전원), 관리 메뉴 "API 토큰 관리"(전역 관리자). **v0.2.7부터 상단 바 메뉴는 "AI 연결(MCP)" 페이지로 대체되고 아래 "내 API 토큰" 화면은 그 페이지의 토큰 영역이 된다(§23, MR-C3).**
- "내 API 토큰"(`frontend/src/pages/ApiTokens.tsx`): 표(이름·범위·접두·만료(남은 일수)·마지막 사용·상태) + "발급"(이름·범위 라디오 — 권한 없는 범위는 비활성+사유·만료일 수 최대 30) + "폐기"(확인 대화) + 연결 안내(접힘). 오류 문구 한국어.
- 발급 직후 평문은 **1회 표시**: 복사 버튼·"이 창을 닫으면 다시 볼 수 없습니다" 경고, 대화를 닫으면 컴포넌트 상태에서 지운다. localStorage·sessionStorage·전역 상태 저장소·로그에 쓰지 않는다(정적 시험: 토큰 문자열을 저장하는 코드 없음).
- "API 토큰 관리"(전역 관리자, 구현 반영 MR-C2): `GET /admin/api-tokens`의 `user_id`·`active`(전체/유효/무효) 필터 + 행별 폐기(`POST /admin/api-tokens/{id}/revoke`, 확인 대화). 감사 조회 화면은 비범위(API `list_audit`만).

## 5. 공통 작업 계약(dry-run + 확인 토큰)

### 5.1 작업 종류 레지스트리 `JOB_KINDS`(`physicsai_api/mcp/job_kinds.py`)

종류 하나 = `{kind, version, label_ko, stage("①-3" 등 화면 번호), job_types[], cost:"heavy"|"light", params_model(pydantic, 모든 필드 설명·단위·범위), plan_fn, create_fn, status_fn?, summary_entity, cancel_fn?}`. `plan_fn`·`create_fn`은 **기존 서비스 함수·미리보기 함수를 호출만** 한다(로직 복제 금지). 새 job_type은 이 표에 한 줄 등록하면 범용 도구로 쓰인다.

초기 등록(첫 구현 범위):

| kind | 대상(기존 경로) | cost | plan 근거(재사용) | summary_entity |
|---|---|---|---|---|
| `doe_generate` | ①-3 TD_DOE_GEN(`POST /studies/{id}/jobs`) | heavy | 신규 plan: 표본 수(`num_runs`/`sampling.count`)·엔진(native/altair)·세트·동시 수(min(입력, max_multi_execution))·최근 성공 TD_DOE_GEN run당 중앙값 × N | `train_doe` |
| `solve_pbs` | ①-4 TD_SOLVE | heavy | 신규 plan: 대상 run 수·HPC 모드(pbs/scx)·큐·코어·walltime·제출 작업 수 | `train_doe` |
| `predict` | ④ PREDICT(단건) | light | `POST /studies/{id}/predict/check` | `predict_run` |
| `predict_batch` | ④ PREDICT_BATCH | heavy | `POST …/predict-batches/preview`(count·estimate_min) | `predict_batch` |
| `surrogate_opt` | ⑥ SURROGATE_OPT(`POST …/surrogate-opts`) | heavy | `POST …/surrogate-opts/preview` + 반복 수×검증 run 수 | `surrogate_opt` |
| `surrogate_opt_verify` | `POST /surrogate-opts/{id}/verify` | heavy | 검증 대상 후보 수·검증 경로(native/altair) | `surrogate_opt` |
| `equiv_check` | ⑤ EQ_CHECK(`POST …/equiv-checks`) | heavy | `POST …/equiv-checks/preview`(쌍 수·추출 필요 수·예상 바이트) | `equiv_check` |
| `fem_verify` | ④ FEM_VERIFY(`POST …/fem-verifications`) | heavy | `POST …/fem-verifications/preview` | `fem_verify` |
| `geom_preview` | GEOM_PREVIEW(`POST /param-sets/{id}/previews`) | light | 캐시 적중 여부 | `geom_preview` |

등록 안 함(정적 시험의 제외 목록 `MCP_JOB_EXCLUDED`에 사유와 함께): DATASET_CREATE·PACKAGE_EXPORT·MODEL_REGISTER·EVALUATE(③ 모델 관리 — 사람 판단 단계), TD_EXTRACT_PARAMS·TD_RESULT_IMPORT·TD_RESP_EXTRACT·CU_*·SPDM_IMPORT(데이터 준비), OPTIMIZE(레거시 HyperStudy), PARAM_SET_NATIVE·PB_RESP_EXTRACT·CONTOUR_*·PREDICT_VERIFY(내부·후속 단계), STUDY_STORAGE_SCAN·STUDY_CLEANUP(관리). 나중에 등록하면 제외 목록에서 빼기만 한다.

### 5.2 API(`physicsai_api/routers/mcp.py`, 접두 `/physicsai/api/mcp`, 세션·토큰 모두 허용)

| 메서드·경로 | operationId(= tool) | risk | 요청 | 응답 |
|---|---|---|---|---|
| `GET /mcp/job-kinds` | `list_job_kinds` | read | – | `[{kind, version, label_ko, stage, cost, confirm_required, summary_entity}]` |
| `GET /mcp/job-kinds/{kind}` | `describe_job_kind` | read | – | `{kind, version, params_schema(JSON Schema, 설명·단위·범위), example, limits, cost}` |
| `POST /mcp/jobs/plan` | `plan_job` | read | `{kind, study_id, params}` | `JobPlan` |
| `POST /mcp/jobs` | `run_job` | run | `{kind, study_id, params, confirm_token?}` | `201 JobStatus` |
| `GET /mcp/jobs?study_id=&state=&kind=&mine=&limit≤50` | `list_jobs` | read | – | `JobStatus[]`(짧은 형태) |
| `GET /mcp/jobs/{job_id}` | `job_status` | read | – | `JobStatus` |
| `GET /mcp/jobs/{job_id}/summary?top_n=` | `job_summary` | read | – | `Summary`(종류의 `summary_entity`로 위임) |
| `POST /mcp/jobs/{job_id}/cancel` | `cancel_job` | run | – | `202 JobStatus`(멱등) |

```jsonc
// JobPlan
{"kind":"predict_batch","kind_version":1,"study_id":"…","valid":true,
 "runs":20,"parallel":4,"lane":"SLOT","uses_global_slot":true,"hpc_jobs":0,
 "estimate_min":35,"estimate_basis":"recent_median"|"none",
 "disk_bytes_est":null,"targets":{"param_set":"쿠션 v1 (ps-1)","model":"cushion_TNS v1 (m-2)"},
 "queue_ahead":2,"warnings":[{"code":"…","message":"…"}],"problems":[],
 "confirm_required":true,"confirm_token":"pcf_…"|null,"expires_at":"…"}
// JobStatus — 종류 무관 공통
{"job_id":"…","kind":"predict_batch","job_type":"PREDICT_BATCH","study_id":"…","state":"RUNNING",
 "progress_pct":40,"progress_label":"…","queue_position":null,"entity":{"type":"predict_batch","id":"…"},
 "created_by_name":"…","via_token":"pai_ab12cd34","created_at":"…","started_at":"…","finished_at":null,
 "error":{"code":"…","message":"…"}|null}
```

규칙:
- `problems`가 비어 있지 않으면 `valid:false`, `confirm_token:null`(생성 불가). read 범위 토큰·세션 요청에는 `confirm_token:null`(계획만 보여 줌).
- `confirm_token` = `pcf_` + 난수. `mcp_plans`에 해시로 저장하고 **(api_token_id, kind, study_id, sha256(정규화 JSON params))**에 결합. TTL `mcp.confirm_ttl_s`(600초), 1회용.
- `run_job`(토큰 요청 + heavy + `require_confirm_for_token`): 없으면 428 `CONFIRM_REQUIRED`(+`plan_with: "plan_job"`), 해시 불일치·만료·사용됨·모름은 409 `CONFIRM_INVALID`(+`reason: mismatch|expired|used|unknown`). light 종류·세션 요청은 confirm 없이 생성(세션이 confirm을 보내면 검증만).
- 생성 시점 재검증: create_fn이 기존 서비스 검증을 그대로 거치므로 plan 이후 상태 변화(STUDY_JOB_BUSY 등)는 기존 409로 돌려준다.
- `cancel_job`: 종류의 `cancel_fn`(배치·최적화·FEM은 기존 cancel 서비스) 또는 기존 `cancel_job`. 토큰 요청은 **그 토큰이 만든 작업**(jobs.api_token_id 일치)만 허용(§2.1 예외), 그 밖은 기존 권한.
- `mcp.allowed_job_kinds`(null = 전체) / `mcp.denied_job_kinds`(기본 미결 Q3)에 걸리면 403 `JOB_KIND_DENIED`. 모르는 kind 422 `JOB_KIND_UNKNOWN`.

## 6. 감사 로그

### 6.1 기록 대상·위치

- **`api_audit`**(새 테이블, 미들웨어가 응답 후 별도 트랜잭션으로 기록 — 실패한 요청도 남는다): 토큰 요청의 모든 비GET, 모든 거부(401·403·428·429), `plan_job`·`run_job`. 토큰 GET은 `mcp.audit.record_reads`(기본 false)일 때만.
- 세션 요청은 기존대로(`audit_events`만). 토큰 요청이 기존 서비스의 `audit()`를 타면 `detail.api_token_id`를 함께 넣는다(스키마 변경 없음).
- 열: `id, occurred_at, user_id, username, api_token_id, token_prefix, operation_id, tool, method, route(템플릿 경로), target_type, target_id(경로 파라미터 중 대표 id), study_id, kind, job_id(생성 시), plan_id, status_code, result_code(오류 code 또는 null), duration_ms, request_id, client_ip, params_sha256`.
- **본문 저장 금지**: 요청·응답 본문, 파라미터 값, 쿼리 값, 토큰·confirm_token 원문을 저장하지 않는다. 쿼리는 키 이름 목록만(필요 시), 본문은 `params_sha256`만(재현 확인용). 정적 시험이 `api_audit` insert 인자 목록을 고정한다.

### 6.2 조회·보존

| 메서드·경로 | operationId(tool) | 권한 | 응답 |
|---|---|---|---|
| `GET /mcp/audit?user_id=&token_id=&operation_id=&status=&since=&until=&limit≤200&cursor=` | `list_audit` | admin(세션 전역 관리자 또는 admin 토큰) | `{items:[ApiAudit], next_cursor}` 최신순 |

- 보존: `mcp.audit.retention_days`(180, 30~3650). 워커 주기 정리(기존 미리보기 캐시 정리와 같은 주기)에서 초과 행 삭제(플랫폼 내부 기록이므로 사용자 산출물 삭제 금지 규칙과 별개). `mcp_plans`는 만료 후 1일 지나면 삭제.

## 7. 요약형 조회 API(레지스트리)

- `SUMMARIES`(`physicsai_api/mcp/summaries.py`): `{entity: (load_fn, summary_fn, id_label)}`. 새 엔티티는 등록만. 각 summary_fn은 **기존 서비스 조회 함수**를 불러 공통 봉투로 줄인다(SQL·파일 파서 복제 금지).
- `GET /mcp/summary/{entity}/{id}?top_n=` → operationId·tool `get_summary`(read). 모르는 entity 404 `SUMMARY_ENTITY_UNKNOWN`.
- 시스템 요약 `GET /mcp/system` → tool `system_status`(대기열 앞 5개·슬롯 보유·워커 온라인·설정 ok·HPC 모드·features).
- 연결 점검 `GET /mcp/ping` → tool `ping`(read, §9.1 표·MR-17). 세션 요청이면 `token:null`.

```jsonc
// 공통 봉투 Summary
{"entity":"surrogate_opt","id":"…","title":"OPT-003 무게 최소화","state":"SUCCEEDED","as_of":"…",
 "facts":{"algorithm":"nsga2","iterations":12,"evaluated":240,"verified":8},        // 스칼라만, ≤ 30키
 "tables":[{"name":"pareto_top","columns":["rank","MASS[kg]","MaxStress[MPa]","THK_1[mm]"],
            "rows":[[1,1.82,151.2,3.1]],"total_rows":37,"stats":{"MASS[kg]":{"min":1.80,"max":2.40,"mean":2.05}}}],
 "links":[{"entity":"predict_batch","id":"…","rel":"verification"}],
 "truncated":false,"bytes":1834}
```

| entity | 내용(요지) |
|---|---|
| `study` | 제목·프로젝트·Final 모델·현재 세트·단계별 상태(①~⑥)·최근 작업 5·하위 엔티티 개수와 최근 id |
| `param_set` | 엔진(native/altair)·kind(solid/shell)·파라미터(이름·종류 약어·단위·공칭·range·envelope 요약)·응답·perf 정의 이름·baseline 수·준비 상태. Native는 `facts.vars_revision`(0 = 등록 정의)·`facts.vars_count`(형상 행 수) — native-vars §6.6, Altair는 둘 다 null |
| `train_doe` | 생성 방식·표본 수·run 상태 집계·결과 표 상위 N·응답 통계 |
| `predict_run` | 입력 값·응답 값·경고 |
| `predict_batch` | run 상태 집계·응답 상위 N·통계·범위 밖 개수 |
| `surrogate_opt` | 알고리즘·기준(목적·제약)·반복·최적/파레토 상위 N·검증 결과 |
| `equiv_check` | 레시피 이름·버전·종합 판정·필수 지표별 통과/실패 수·최악 쌍 상위 N |
| `fem_verify` | 대상·상태·응답 비교 상위 N |
| `geom_preview` | 값·성공/실패 reason·품질 요약 |
| `job` | `JobStatus` + 단계별 상태·마지막 오류 |

- 크기: 직렬화 후 `mcp.summary.max_bytes`(8192) 초과 시 표 행을 줄이고 `truncated:true`. `top_n` 기본 10, 최대 50. 절대경로는 넣지 않는다(표시 이름·id만).
- 단위: 수치 열 이름에 `[단위]` 접미(성능 정의·세트 단위에서), 단위 모르면 접미 없음.

## 8. openapi 보강·`x-mcp`

- 라우트 데코레이터 `openapi_extra={"x-mcp": {...}}`. 모양:
  - 도구: `{"tool":"run_job","risk":"read|run|admin","confirm":"never|by_kind|always","version":1,"summary_en":"…","summary_ko":"…","deprecated":false}` — `summary_en`·`summary_ko` 필수(MR-16, 도구 설명 = `"<en> / <ko>"` ≤ 300자)
  - 제외: `{"exclude":"웹 전용 편집"}`(사유 필수, 10자 이내 한국어 권장)
- 도구 operation 필수 항목(정적 시험 V-MCP-6): `summary`, `description`(한국어, 언제 쓰는지·부작용), 모든 요청 필드·쿼리에 `description`, 수치에 단위(`x-unit` 또는 설명 안 `[mm]`)와 `minimum`/`maximum` 또는 enum, 요청 `examples` 1개 이상, 응답 모델 명시, 오류 code 목록(`responses` 설명).
- operationId: **기존 operation 불변**(프런트 시험 고정). 새 `/mcp/*`는 `operation_id=<tool 이름>` 명시. 도구 이름은 `x-mcp.tool`이 단일 출처(operationId와 같지 않아도 됨 — 기존 GET에 붙일 때).
- 동결 목록: 18dc408 기준 기존 operation 전부를 `physicsai_api/mcp/route_policy.py` `LEGACY_UNMARKED`(operationId 집합)로 둔다. **새 operation은 `x-mcp`(도구 또는 제외) 없으면 시험 실패**, 동결 목록은 줄기만 한다(없는 id가 있으면 실패).
- 기존 operation 중 도구로 쓰는 것: `GET /studies` → `list_studies`, `GET /me` → `whoami`, `POST /studies/{id}/predict/check` → `check_prediction_input`(read, 쓰기 없음). 나머지 기존 쓰기는 토큰 요청 불가(허용 목록 밖).
- 동결 목록 기준은 **구현 기준 커밋(v0.2.3 + 병합된 native-vars)**의 기존 operation. native-vars·upload-report가 추가하는 operation은 동결 목록에 넣지 않고 각 계약의 x-mcp 표기를 따른다(native-vars §6.6, upload-report §4.1·§9.4). `x-mcp` 표기는 openapi 확장일 뿐이므로 MCP 병합 전에도 붙일 수 있다.

## 9. 도구 스펙 생성기

- `scripts/gen_tool_specs.py [--check] [--out DIR]`: `export_openapi.build_openapi()` 결과에서 `x-mcp.tool` operation만 골라 도구 이름순으로 생성. 출력(패키지 안 — API가 서빙): `backend/physicsai_api/mcp/generated/`
  - `tools.mcp.json` — `{schema_version:1, generated_from:"openapi <version>", tools:[{name, description, inputSchema, annotations:{readOnlyHint, destructiveHint, x-risk, x-confirm, x-version}, x-http:{method, path, operationId}}]}`
  - `tools.openai.json` — `[{type:"function", function:{name, description, parameters, strict:false}}]`. 경로·쿼리·본문 인자를 한 객체로 평탄화(이름 충돌은 생성 실패). `parameters` = MCP `inputSchema`와 **같은 이식 가능 스키마**(§9.2).
  - 자유 객체(작업 종류별 `params` 등 properties 없는 object)는 도구 입력에서 `params_json`(문자열, JSON 객체 텍스트 ≤ 64 KiB, 설명 "describe_job_kind로 스키마 확인")으로 바꾸고 `x-http.json_string_fields`에 기록 — MCP 계층이 파싱해 HTTP 본문 객체로 넣는다(파싱 실패 = 도구 오류 `PARAMS_JSON_INVALID`, HTTP 호출 안 함).
  - `glossary.json` — §10.
  - `job_kinds.json` — `JOB_KINDS` 스냅숏(kind·version·cost·`params_schema`·예시). `describe_job_kind` 리소스 텍스트와 작업 종류 호환 검사(`--check`)의 비교 기준. 도구 입력 스키마가 아니다(§9.2 화이트리스트 대상 아님 — V-MCP-14).
- 결정적: 키 정렬·`ensure_ascii=False`·indent 2·끝 줄바꿈, 시각·경로 미포함. `--check`는 디스크 파일과 다르면 실패(test-all).
- 호환 검사(`--check`): 직전 커밋된 `tools.mcp.json`과 비교해 같은 이름 도구에서 **인자 제거·이름 변경·타입 변경·새 필수 인자**가 있으면 실패 — 새 이름(`<tool>_v2`)을 쓰고 옛 도구는 `deprecated:true`로 1 릴리스 유지. 작업 종류 params도 같은 규칙(`kind` 이름·`kind_version`).
- 서빙: `GET /mcp/tools?format=mcp|openai[&visible=true]` → operationId `mcp_tool_specs`, tool `—`(x-mcp exclude "MCP 서버 부팅용"; 세션·토큰 read 허용, 생성 파일 그대로). MCP 서버(§20)는 이 응답(HTTP 마운트는 같은 파일을 주입받음)으로 도구를 동적 노출하고 HTTP로 위임하는 얇은 계층.
  - `visible=true`(기본 false, `format=mcp`에서만 의미 — openai 형식은 무시): 응답 최상위에 `visible: [도구 이름]`을 더한다 = 이 요청의 토큰 범위로 부를 수 있는 도구(판정 = 백엔드 `scope_allows(scope, annotations.x-risk)`, 세션 요청은 전체). stdio 실행기가 시작 시 이 값으로 `tools/list`를 거른다(§20.1). 그 밖 키·`tools` 배열은 생성 파일과 바이트 단위로 같은 내용.

### 9.2 이식 가능 스키마(MR-16 — Claude·Codex·Gemini 공통)

생성기가 openapi 스키마를 아래 규칙으로 바꾼다. 바꿀 수 없으면 생성 실패(오류 문구에 operation·필드).

| 규칙 | 내용 |
|---|---|
| 허용 키워드(화이트리스트) | `type`(단일 문자열: object·string·number·integer·boolean·array), `description`, `properties`, `required`, `items`, `enum`(**문자열만**), `minimum`·`maximum`, `minItems`·`maxItems`, `minLength`·`maxLength`, `nullable` |
| 제거·평탄화 | `$ref`·`$defs` 인라인 평탄화(순환이면 실패), `title`·`default`·`examples`·`format`·`pattern`·`additionalProperties`·`patternProperties`·`const`·`exclusive*` 제거 — 기본값·형식·패턴은 description 끝에 `(기본 …, 형식 …)`로 옮김 |
| 합성 | `anyOf`/`oneOf`/`allOf` 금지. pydantic `X \| None` = X + `nullable: true`, 그 밖 합성은 생성 실패(API 쪽 모델을 단순화하거나 x-mcp exclude) |
| object | properties가 비면 금지(→ `*_json` 문자열, §9) |
| 이름 | 도구 `^[a-zA-Z0-9_-]{1,64}$`, 인자 `^[a-zA-Z_][a-zA-Z0-9_]{0,63}$`, 도구 수 ≤ 40(굵은 도구 소수 원칙) |
| 설명 길이 | 도구 ≤ 300자(영어 / 한국어), 인자 ≤ 200자. 수치 인자 단위는 description의 `[mm]` 표기 |

- 정적 검사(V-MCP-14): **도구 입력 스키마**(`tools.mcp.json` `inputSchema`·`tools.openai.json` `parameters`)를 같은 화이트리스트 검사기로 다시 확인(생성기와 별도 구현 — `backend/tests/common/test_mcp_portable_schema.py`). `job_kinds.json`의 `params_schema`(리소스·`describe_job_kind` 텍스트용, `params_json` 안 내용)는 화이트리스트 대상이 아니고 모양만 검사(`type: object`·kind·version·cost), `glossary.json`은 필수 섹션 존재만.
- 응답(도구 결과)은 JSON 텍스트 + `structuredContent`(§20.3) — 응답 스키마(`outputSchema`)는 내보내지 않는다(클라이언트별 지원 차이).

### 9.1 도구 목록(구현 17개 — 아래 18행 중 `find_similar_designs`는 Q2 미확정으로 미구현)

| tool | risk | 경로 | 비고 |
|---|---|---|---|
| `whoami` | read | `GET /me` | 기존 |
| `system_status` | read | `GET /mcp/system` | |
| `list_studies` | read | `GET /studies` | 기존 |
| `get_summary` | read | `GET /mcp/summary/{entity}/{id}` | 엔티티 레지스트리 |
| `get_glossary` | read | `GET /mcp/glossary` | MCP resource 후보 |
| `check_prediction_input` | read | `POST /studies/{id}/predict/check` | 기존, 범위 검사 |
| `list_job_kinds` | read | `GET /mcp/job-kinds` | |
| `describe_job_kind` | read | `GET /mcp/job-kinds/{kind}` | params 스키마 |
| `plan_job` | read | `POST /mcp/jobs/plan` | confirm_token 발급(run 토큰만) |
| `run_job` | run | `POST /mcp/jobs` | confirm by_kind |
| `list_jobs` | read | `GET /mcp/jobs` | |
| `job_status` | read | `GET /mcp/jobs/{id}` | |
| `job_summary` | read | `GET /mcp/jobs/{id}/summary` | |
| `cancel_job` | run | `POST /mcp/jobs/{id}/cancel` | 자기 토큰 작업 |
| `list_audit` | admin | `GET /mcp/audit` | |
| `find_similar_designs` | read | `POST /mcp/similar` | **Q2 확정 시에만** |
| `ping` | read | `GET /mcp/ping` | 연결 점검(MR-17) — `{ok, server_version, mcp_enabled, token:{prefix, scope, expires_at, days_left, snapshot_age_days}, tools_count}`, `days_left ≤ 5`이면 `warnings`에 "토큰 만료 임박 — 웹에서 새 토큰 발급" |
| `get_native_vars` | read | `GET /param-sets/{id}/variables` | native-vars §6.6(v0.2.4 함께) — 조회만. `PUT …/variables`는 x-mcp exclude "웹 전용 편집"(도구 아님) |

## 10. 도메인 용어집·스키마 사전(경량 온톨로지)

- `GET /mcp/glossary?section=` → tool `get_glossary`(read). 생성 `glossary.json` + 사람 파일 병합 결과(응답 상한 64 KiB, `section`으로 부분 조회).
- **자동 추출**(생성기, 손 유지보수 없음): `entities`(SUMMARIES 키 + 관계 표), `job_types`(JOB_TYPES: lane·stage_label·label), `job_kinds`(JOB_KINDS), `feature_abbr`(paicad `features.py`·`shell/common.py`의 `TYPE_ABBR`를 **AST로 읽음** — 플랫폼은 paicad를 import하지 않는다), `enums`(openapi 스키마의 enum: 작업 상태·레인·범위 등), `error_codes`(backend·worker·`physicsai_mcp` 소스 AST에서 `DomainError("CODE", "메시지", status=…)`·`_err(status, "CODE", …)`·`_error(status|None, "CODE", …)`(MCP 계층 로컬 오류 — status null)·`StepFailure("CODE", …)`의 문자열 리터럴 → `{code, status, message_ko(첫 출처), sources:[파일]}`, 파일 경로순 결정적).
- **사람이 쓰는 부분**: `backend/physicsai_api/mcp/glossary_terms.yaml`(Impl-Backend 소유, 패키지 포함) — 키는 자동 추출 키를 참조만:

```yaml
schema_version: 1
terms:
  - key: feature:THK            # 자동 추출 키(없으면 시험 실패)
    ko: 두께
    synonyms: [두께, 쿠션 두께, thickness]
    unit: mm
  - key: feature:RIB_T
    ko: 리브 두께
    synonyms: [리브, 리브 두께]
  - key: feature:BEAD_D
    ko: 비드 깊이
    synonyms: [비드, 판금 비드]
  - key: entity:param_set
    ko: 파라미터 세트
    synonyms: [세트, 템플릿]
  - key: stage:①-3
    ko: 학습 데이터 DOE 생성
  - key: unmapped:낙하씬         # 코드 엔티티 없음 — 설명만
    ko: 낙하 해석 조건(방향·높이)
error_hints:
  CONFIRM_REQUIRED: plan_job을 먼저 호출해 confirm_token을 받으세요
  PARAMS_JSON_INVALID: params_json은 JSON 객체 텍스트(64 KiB 이하)여야 합니다 — describe_job_kind의 params_schema·example을 보고 만드세요
  # INVALID_ARGUMENTS·UNKNOWN_TOOL·SERVER_UNREACHABLE·BACKEND_TIMEOUT·RESULT_TOO_LARGE도 힌트 한 줄씩(§20.3 표)
```

- 단계 번호: 화면 번호(①-1~⑥)와 내부 `stage_label`이 다른 경우(예: SURROGATE_OPT 내부 "⑤" = 화면 ⑥ 최적화, decisions 2026-10-17 화면 재편)를 `stages` 표에 둘 다 싣는다.
- 관계(entities.relations, 사람 파일에서 보충 가능): study 1─N param_set·train_doe·predict_batch·surrogate_opt·equiv_check·model, param_set 1─N baseline·parameter(feature), train_doe 1─N run, run N─N response, response ← perf 정의, equiv_check → recipe(버전).
- 정적 시험(V-MCP-10): 사람 파일의 모든 `key`가 자동 추출 키에 있음, 자동 추출 `feature_abbr`·`job_kinds`·`entities` 전부에 사람 `ko`가 있음(누락 시 실패 — 기능 추가자가 한 줄 쓰게), error_hints 키 ⊂ error_codes.

## 11. 호출 제한

| 설정 | 기본 | 초과 응답 |
|---|---|---|
| `mcp.rate_limit.requests_per_min` | 60(토큰별, 고정 창 60초) | 429 `RATE_LIMITED` + `Retry-After` |
| `mcp.rate_limit.plans_per_min` | 10 | 429 `RATE_LIMITED` |
| `mcp.rate_limit.max_active_jobs_per_token` | 3(이 토큰이 만든 비종료 작업 수, `jobs.api_token_id`) | 429 `TOKEN_ACTIVE_JOB_LIMIT`(+active_job_ids) |

- 세션 요청은 제한 없음(기존 불변). 기존 동시 제한(전역 슬롯·`fem_verify.max_active`·`equiv_check.max_active`)은 그대로 먼저 적용.
- 카운터는 프로세스 메모리(단일 uvicorn 프로세스). 재기동 시 초기화는 허용. 다중 프로세스 전환 시 DB 기반으로 바꾼다(리스크 표).

## 12. 검색

### 12.1 파라미터 벡터 유사 설계 검색(후보 — 포함 여부 미결 Q2)

- `POST /mcp/similar` `{study_id, param_set_id, values:{name:number}, responses?:{name:{target, weight}}, scope:["train_doe","predict_batch","surrogate_opt"], k:1..20}` → `[{entity, id, run_key, distance, values, responses}]`.
- 거리 = 세트 range로 [0,1] 정규화한 파라미터 유클리드(+선택 응답 정규화 항), 범주·baseline은 불일치 시 1. 결과 표 파일(기존 result-table·table.csv 서비스)만 읽음, 새 인덱스·DB 없음, 텍스트 임베딩 없음. 대상 run 상한 `mcp.similar.max_rows`(20000).

### 12.2 임베딩 검색(후속, 선택)

사내 임베딩 모델이 폐쇄망에 있을 때만: 계약·매뉴얼 문서 RAG, 과거 run 메타 의미 검색. 이번 계약은 인터페이스·저장소를 정하지 않는다.

## 13. 설정·배포

```yaml
mcp:
  enabled: false                 # false면 토큰 인증·/mcp/*·토큰 화면 모두 꺼짐(404 MCP_DISABLED)
  require_confirm_for_token: true
  confirm_ttl_s: 600             # 60~3600
  allowed_job_kinds: null        # null = 레지스트리 전체
  denied_job_kinds: []           # 기본값 미결 Q3(제안 [solve_pbs])
  token: {default_expiry_days: 30, max_expiry_days: 30, max_per_user: 5, snapshot_max_age_days: 30, last_used_update_s: 60}  # 기한 1~30(MR-13, default ≤ max)
  server: {http_enabled: true, call_timeout_s: 60, max_result_bytes: 65536}  # §20 — http_enabled=false면 /physicsai/mcp 404(stdio는 API만 쓰므로 영향 없음)
  public_url: null               # v0.2.7 §23.4 — 사용자에게 보일 HTTP MCP 주소(…/mcp), null이면 접속 origin으로 짐작
  rate_limit: {requests_per_min: 60, plans_per_min: 10, max_active_jobs_per_token: 3}
  audit: {retention_days: 180, record_reads: false}
  summary: {max_bytes: 8192, top_n_default: 10, top_n_max: 50}
  similar: {max_rows: 20000}
```

- phase3 배포 기준: `config/platform.example.yaml`·`platform.demo.yaml`에 위 블록 **추가만**(주석 포함), `deploy/setup_config.py`는 건드리지 않는다(키 없으면 기본값). 기본값으로 기존 배포 동작 불변 — V-MCP-1이 검사.
- `/status` `features.mcp`(bool) 추가. 설정 검증: 범위 밖 값은 기존 설정 오류 형식(`mcp.<key>`).
- `/mcp/*`·`/me/api-tokens*` 라우트는 설정과 무관하게 등록(openapi 결정성), 꺼져 있으면 핸들러가 404 `MCP_DISABLED`.

## 14. DB — migration `0020_mcp`(down_revision `0019_extract_filter`, `MIGRATION_HEAD` = `0020_mcp`; 확정 — roadmap, upload-report `0021_uploads`가 이 위)

| 테이블·열 | 내용 |
|---|---|
| `api_tokens` | `id, user_id, username, display_name, name, scope, token_prefix, token_hash(UNIQUE), principal_snapshot JSONB{is_global_admin, roles}, snapshot_at, created_at, expires_at, last_used_at, last_used_ip, revoked_at, revoked_by`; 인덱스 (user_id, revoked_at), UNIQUE(user_id, name) WHERE revoked_at IS NULL |
| `mcp_plans` | `id, api_token_id, user_id, kind, kind_version, study_id, params_sha256, confirm_hash(UNIQUE), summary JSONB(JobPlan 수치만), created_at, expires_at, used_at, used_job_id` |
| `api_audit` | §6.1 열, 인덱스 (occurred_at), (api_token_id, occurred_at), (user_id, occurred_at) |
| `jobs.api_token_id` | nullable 추가(FK 없음 — 토큰 행은 지우지 않지만 감사 독립). 토큰 요청에서 만든 모든 작업 행에 요청 문맥(contextvar)으로 기록 |

- downgrade: 세 테이블에 행이 있으면 거부(데이터 보호, native 0017과 같은 원칙), 없으면 삭제.

## 15. 확장 규칙(기능 추가 시 MCP 쪽 수정 최소화)

| 새로 추가하는 것 | 개발자가 할 일 | 자동으로 따라오는 것 | 빠지면 |
|---|---|---|---|
| 조회 API | 도구로 쓸지 정해 `x-mcp`(tool 또는 exclude) | 도구 스펙·OpenAI 함수·권한 판정 | V-MCP-6 실패 |
| 비용 큰 작업(job_type) | `JOB_KINDS` 한 줄(plan_fn·create_fn은 기존 서비스 호출) 또는 `MCP_JOB_EXCLUDED`+사유 | `plan_job`·`run_job`·`job_status`·`job_summary`·`cancel_job`, confirm·감사·제한 | V-MCP-7 실패 |
| 결과 엔티티 | `SUMMARIES` 한 줄 | `get_summary`, 용어집 entities | V-MCP-8 실패 |
| 피처 약어·오류 코드·enum | 없음(자동 추출) + 용어집 `ko` 한 줄 | `get_glossary` | V-MCP-10 실패 |
| 깨지는 API 변경 | 새 도구 이름·새 kind 이름 | 옛 도구 deprecated 유지 | V-MCP-9 실패 |

MCP 서버(§20)는 생성 스펙을 읽어 도구를 동적 노출하므로, 위 표만 지키면 서버 코드(`backend/physicsai_mcp/**`)는 바뀌지 않는다. 새 도구가 §9.2 규칙을 어기면 생성기가 실패해 개발자에게 알린다.

## 16. 단계·파일 소유

| 단계 | 내용 | 소유 |
|---|---|---|
| M1 | 설정 `mcp`·migration·`api_tokens` 인증 경로·토큰 API·`api_audit` 미들웨어·호출 제한·`route_policy.py` 동결 목록 | Impl-Backend: `config/schema_mcp.py`, `physicsai_api/{deps.py, auth_tokens.py, mcp/route_policy.py, mcp/audit_mw.py, mcp/ratelimit.py, routers/api_tokens.py}`, `migrations/versions/0020_mcp.py`, `db/repositories/{api_tokens,api_audit,mcp_plans}.py`, `config/platform.example.yaml`·`platform.demo.yaml`(추가만) |
| M2 | `JOB_KINDS`·`/mcp/jobs*`·doe_generate·solve_pbs plan 신규, `SUMMARIES`·`/mcp/summary`·`/mcp/system`·`/mcp/audit` | Impl-Backend: `physicsai_api/mcp/{job_kinds.py, summaries.py}`, `routers/mcp.py`, `schemas/mcp.py` |
| M3 | `x-mcp` 표시·설명 보강(`summary_en`·`summary_ko`), §9.2 이식 가능 스키마 변환·검사기, `scripts/gen_tool_specs.py`·생성 파일·`/mcp/tools`·용어집(`glossary_terms.yaml`, `/mcp/glossary`), test-all 연결, `backend/openapi.json` 갱신 | Impl-Backend |
| M4 | "내 API 토큰"·"API 토큰 관리" 화면 + `frontend-dist/` | Impl-Frontend: `frontend/src/pages/ApiTokens.tsx`·`shell/TopBar.tsx`·`api/typesTokens.ts`·`mock/apiTokens.ts`(구현 위치, MR-C2) |
| M5 | MCP 서버(§20): 공통 도구 실행기·HTTP 마운트·stdio 실행기·리소스·`/mcp/ping`, 의존 고정(`pyproject.toml`·`deploy/requirements.lock`·오프라인 수집), Caddy 스니펫 `handle /physicsai/mcp*`, 클라이언트 설정 예시 5파일(§21.1), E2E | Impl-Backend: `backend/physicsai_mcp/**`(신규), `physicsai_api/main.py`(마운트 1곳), `deploy/{requirements.lock, collect-offline.*, caddy/physicsai.caddy}`, `deploy/mcp/examples/*`, `pyproject.toml`(`[project.scripts] physicsai-mcp`), 시험 `backend/tests/test_mcp_server*.py` |
| M7(v0.2.7) | 웹 "AI 연결(MCP)" 페이지·`GET /mcp/connection`·`mcp.public_url` | §23.5 |
| M6 | 연결 가이드·관리자 매뉴얼 반영(설정 키·Caddy·폐기 절차) | Plan: `docs/manual/mcp-clients.md`(초안 작성됨)·`admin.md` |
| (Q2) | `/mcp/similar` | Impl-Backend |

- 옛 구현 WIP: `/home/claude/wt-mcp`(브랜치 `feat/r1-mcpready` 7a8bacf 위 미커밋, 기준 18dc408 — v0.2.0 이전). **참고용**이며 v0.2.3 기준 새 브랜치에 재이식한다(그대로 병합 금지): migration `0019_mcp_ready` → `0020_mcp`(down_revision `0019_extract_filter`), `route_policy` 동결 목록은 현재 openapi에서 다시 만들고, 토큰 기한 30일(MR-13)·§9.2 스키마 규칙·`ping` 반영, `frontend-dist` 변경분은 버리고 Impl-Frontend가 다시 빌드.

## 17. Verifier 체크(V-MCP-*)

| ID | 검사 | 완료 기준 |
|---|---|---|
| V-MCP-1 | 기본값 불변 | `mcp` 키 없는 설정으로 기존 전체 시험 통과, `pai_` Bearer → 401이고 대시보드 가짜 서버 호출 0회, `/mcp/*` 404 `MCP_DISABLED`, `/physicsai/mcp` 404, 세션 요청 응답·CSRF 동작 동일, 기존 operation의 `operationId` 불변 |
| V-MCP-2 | 토큰 수명 | 발급 응답만 평문, 목록·상세에 평문·해시 없음, DB에 평문 없음(문자열 검색), 폐기·만료·stale·형식 오류 각각 401 코드, `expires_in_days` 31 → 422 `API_TOKEN_EXPIRY_TOO_LONG`·생략 = 30일·설정 `max_expiry_days` 31 → 설정 오류, 상한 409, 세션 전용 API에 토큰 403 `SESSION_REQUIRED` |
| V-MCP-3 | 범위·허용 목록 | read 토큰 `run_job` 403 `API_TOKEN_SCOPE`, 비 x-mcp operation 403, admin 범위는 스냅숏 전역 관리자만 발급, 스냅숏 역할 갱신(세션 로그인 후 power 제거 → run 403), 관리자 해제 시 admin 토큰 자동 폐기 |
| V-MCP-4 | confirm | heavy + 토큰: 없음 428, 다른 params 409 mismatch, 만료(시계 주입)·재사용 409, 정상 201 + `mcp_plans.used_job_id`; light·세션은 confirm 없이 201; problems 있으면 confirm_token null; 웹 기존 생성 API 결과 불변 |
| V-MCP-5 | 감사 | 토큰 비GET·거부·plan·run 각 1행, 실패 요청도 기록, 본문·값·토큰 원문 없음(insert 인자 고정 시험 + DB 문자열 검색), 보존 초과 정리, `list_audit` admin만 |
| V-MCP-6 | x-mcp 정적 | 모든 operation이 x-mcp 또는 `LEGACY_UNMARKED`, 동결 목록에 없는 id 없음, 도구 operation 필수 항목(설명·단위·범위·예시·응답 모델) 누락 0, 도구 이름 유일 |
| V-MCP-7 | 작업 종류 | JOB_TYPES ⊆ (JOB_KINDS.job_types ∪ MCP_JOB_EXCLUDED), 각 kind에 plan_fn·create_fn·summary_entity·params 필드 설명·단위, plan_fn·create_fn이 기존 서비스 호출(가짜 서비스 주입 시험) |
| V-MCP-8 | 요약 | 모든 엔티티 봉투 모양·`max_bytes` 이하(대형 픽스처로 truncated 확인)·절대경로 없음, summary_entity ⊆ SUMMARIES |
| V-MCP-9 | 생성기 | 두 번 실행 바이트 동일, `--check` 최신, OpenAI 출력 최상위 oneOf/anyOf 없음·인자 충돌 없음, 호환 검사(필수 인자 추가·제거·타입 변경 → 실패, 새 이름 → 통과) |
| V-MCP-10 | 용어집 | 자동 추출 키(피처 약어 = paicad TYPE_ABBR 전체, job_types, job_kinds, entities, error_codes)와 실제 코드 일치, 사람 파일 키 ⊂ 자동 키, 필수 `ko` 누락 0, paicad import 없음 |
| V-MCP-11 | 호출 제한 | 분당 61번째 429 + Retry-After, plan 11번째 429, 동시 작업 4번째 429, 세션 무제한 |
| V-MCP-12 | 토큰 취소 예외 | 같은 토큰 작업만 `cancel_job` 성공, 다른 사용자·다른 토큰 작업 403, 기존 `POST /jobs/{id}/cancel` 권한 불변 |
| V-MCP-13 | 화면 | features.mcp false면 두 메뉴 숨김, 평문 1회 표시·복사·닫으면 상태에서 삭제·저장 코드 없음(정적), 폐기 확인 대화, 만료일 입력 최대 30, 관리자 목록 user_id·active 필터 |
| V-MCP-14 | 이식 가능 스키마 | 도구 입력 스키마(`tools.*.json`)가 §9.2 화이트리스트 통과(별도 검사기), `job_kinds.json` params_schema는 모양 검사만, 도구·인자 이름 정규식, enum 문자열만, 빈 properties object 0, 도구 수 ≤ 40, 설명 en/ko 병기·길이 |
| V-MCP-15 | HTTP E2E(SDK 클라이언트 `streamable_http`) | 시험 uvicorn(127.0.0.1 임시 포트)+PostgreSQL: initialize → `tools/list`(read 토큰은 read 도구만, run 토큰은 run 포함) = 생성 파일과 이름·스키마 일치 → `ping`·`whoami`·`get_summary` 호출 → `resources/list`·`resources/read`(용어집) → run 토큰 `plan_job`→`run_job`(confirm)→`job_status`; Bearer 없음·`pai_` 아님·폐기 토큰 401 + `WWW-Authenticate: Bearer`, `mcp.enabled=false` 404 |
| V-MCP-16 | stdio E2E(SDK 클라이언트 `stdio_client`) | `python -m physicsai_mcp.stdio`를 환경변수(URL·토큰 또는 토큰 파일)로 띄워 V-MCP-15와 같은 시나리오·같은 도구 목록, 토큰 없음 → 시작 실패 문구(종료 코드 2), 서버 다운 → 도구 오류 `SERVER_UNREACHABLE` |
| V-MCP-17 | 거부·감사 | MCP 경유 read 토큰 `run_job` → 도구 결과 `isError` + `API_TOKEN_SCOPE`(HTTP 403 그대로 전달), confirm 없음 428 → `isError` + 힌트 "plan_job을 먼저", 호출 제한 429 전달; 각 호출이 `api_audit`에 1행(MCP 계층은 감사 직접 기록 없음 — 백엔드 미들웨어만), MCP 계층 로그에 토큰·인자 값 없음 |
| V-MCP-18 | 얇은 래퍼 정적 | `physicsai_mcp`가 `physicsai_api`·`physicsai_core`·`physicsai_worker`를 import하지 않음(`test_layering` 규칙 8), 권한·범위 판정 코드 없음(도구 목록 필터는 주입된 백엔드 함수만), python-multipart import 0(플랫폼 코드 전체) |
| V-MCP-19 | 클라이언트 설정 예시 | `deploy/mcp/examples/`의 7파일(§21.1 표 — 목록이 정확히 7개 + `README.txt`)이 json/tomllib 파싱 통과·필수 키(HTTP: url/httpUrl·Authorization 또는 bearer_token_env_var, 브리지: `npx`·`mcp-remote` args·`env.AUTH`·`${AUTH}` 참조, stdio: command·env)·토큰 평문 없음(`pai_` 문자열 0), 가이드 문서의 같은 블록과 내용 일치 |
| V-MCP-20 | 오프라인 설치 | `deploy/requirements.lock`에 `mcp`·전이 의존 고정, `collect-offline`이 wheel 수집, 빈 venv에 `--no-index` 설치 후 `physicsai-mcp --version`(CI Linux) + Windows 묶음 수동(e2e-checklist) |
| V-MCP-21~26 | 웹 "AI 연결(MCP)" 페이지(v0.2.7) | §23.6 |

## 18. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| 토큰 유출(설정 파일·대화 기록·LLM 로그) | 소유자 권한으로 작업 생성 | 해시 저장·1회 표시·만료 필수(≤ 30일)·클라이언트 설정에 평문 대신 환경변수·토큰 파일(§21)·범위 최소(read 기본 권장)·허용 목록·호출 제한·감사·즉시 폐기, `pai_` 접두로 비밀 검사 도구 탐지 가능 |
| 사내 LLM 오조작(잘못된 범위·대량 run) | 슬롯·HPC 점유 | heavy confirm(요청 해시 결합 — plan 후 값 바꿔치기 불가)·동시 작업 상한·`denied_job_kinds`·자기 작업 취소·plan에 대기열·예상 시간 표시 |
| 역할 스냅숏이 대시보드보다 늦음 | 권한 회수 지연(최대 30일 = 토큰 기한) | 웹 로그인 시 즉시 갱신·관리자 폐기(즉시 차단 경로, 관리자 매뉴얼)·admin 자동 폐기 |
| MCP SDK 버전 변화(2.x 빠른 개정, 2026-10-21 PyPI 최신 `mcp` 2.3.0) | API 깨짐·전이 의존 증가 | `mcp==2.3.0` 고정(pyproject·lock 같은 값, 구현 반영), SDK 사용은 `physicsai_mcp/sdk_adapter.py` 한 파일에 모음, E2E V-MCP-15·16 |
| SDK 전이 의존(2.3.0 기준 python-multipart·pyjwt[crypto]·sse-starlette·opentelemetry-api·httpx2·mcp-types·jsonschema·pywin32(Windows)) | 오프라인 묶음·보안 검토 증가, upload-report "python-multipart 의존 금지"와 충돌 | MR-18·UR-C1(전이 의존만 허용, 코드 import·multipart 라우트 0 유지), 구현 시 lock 해석으로 목록 확정·라이선스 확인 |
| Streamable HTTP가 프록시에서 끊김(SSE 버퍼링) | 도구 호출 실패 | stateless + JSON 응답 모드(SSE 미사용), Caddy `handle /physicsai/mcp*`, Vite 프록시는 `/physicsai` 전체 전달이라 무변경 |
| HTTP(비 TLS) 대시보드에서 Bearer 전송 | 사내망 도청 시 토큰 노출 | 대시보드가 HTTPS면 HTTPS 주소 권장(가이드), 짧은 기한·범위 최소·즉시 폐기 |
| 클라이언트별 스키마 수용 차이 | 특정 클라이언트에서 도구 거부 | §9.2 최소 공통 부분집합·V-MCP-14, 클라이언트 수동 확인(e2e-checklist) |
| plan 추정 부정확(최근 중앙값 없음) | 잘못된 판단 | `estimate_basis:"none"` 명시, 수치 대신 run 수·슬롯 정보 우선 |
| 요약 레지스트리가 기존 화면 API와 어긋남 | 다른 숫자 | summary_fn은 기존 서비스 호출만(복제 금지) |
| 단일 프로세스 전제(메모리 카운터) | 다중 프로세스면 제한 약화 | 전환 시 DB 카운터로(변경 메모) |
| x-mcp·용어집 의무가 기능 개발 부담 | 누락·형식적 설명 | 한 줄 등록 구조·동결 목록·생성기 오류 문구가 할 일을 알려 줌 |

## 19. 미결(사용자 확인)

- ~~Q1~~ 종결(2026-10-21): 역할 스냅숏 + `snapshot_max_age_days` 30, 즉시 차단은 관리자 폐기(MR-13).
- **Q2** 파라미터 벡터 유사 설계 검색 `find_similar_designs`(§12.1)를 넣을지 — 회신 없으면 **제외로 진행**(후속 추가는 도구 1개 추가라 MCP 서버 무변경).
- **Q3** `denied_job_kinds` 기본값 — 회신 없으면 **제안값 `[solve_pbs]`로 진행**(PBS 클러스터 자원은 사람이 웹에서만, 설정으로 해제 가능).
- **Q4**(사용자 확인 대기 — 차단 아님) 사내 on-premise 배포 클라이언트(Claude·Codex·Gemini·사내 LLM)가 실제 허용하는 전송(stdio 실행 허용 여부·HTTP 사내 주소 접속 허용 여부). 모르면 **둘 다 제공으로 진행**(MR-15).

## 20. MCP 서버 구현·배포(MR-14·MR-15)

### 20.1 패키지·구조(`backend/physicsai_mcp/`, Impl-Backend)

| 파일 | 역할 |
|---|---|
| `toolset.py` | 생성 스펙(`tools.mcp.json`)·리소스 목록을 받아 SDK `Server`에 `list_tools`·`call_tool`·`list_resources`·`list_resource_templates`·`read_resource` 등록. 도구 호출 = `x-http`(method·path·operationId·`json_string_fields`)로 HTTP 요청 조립 → 응답을 도구 결과로 변환(§20.3). **두 전송 공용** |
| `backend_client.py` | 위임 HTTP 클라이언트 인터페이스: `request(method, path, query, json, bearer) -> (status, body)`. 구현 2개 — 네트워크(httpx, stdio용)·ASGI(같은 프로세스 앱, HTTP 마운트용) |
| `http_app.py` | `build_mcp_asgi(app, verify_token, load_specs) -> ASGI`. SDK `StreamableHTTPSessionManager`(`json_response=True, stateless=True`)를 **요청마다 새로 만들어** `run()` 안에서 그 요청 하나를 처리하고 닫는다(`run()`은 인스턴스당 1회라서 — 앱 lifespan에 매달지 않음, 마운트 앱의 시작·종료 훅과 무관). 요청마다 `Authorization: Bearer pai_…` 확인 → 주입된 `verify_token`(= 백엔드 `auth_tokens` 검증 함수, §4.2와 같은 401 코드)로 검증, 실패 401 + `WWW-Authenticate: Bearer` + 오류 본문(아래). POST 외 메서드(GET·DELETE — stateless·JSON이라 독립 SSE 스트림·세션 종료 없음)는 405 `METHOD_NOT_ALLOWED` + `Allow: POST`. 검증된 Bearer를 그 요청의 도구 호출에 그대로 실어 ASGI 클라이언트로 `/physicsai/api/...` 호출 |
| `stdio.py` | 진입점 `physicsai-mcp`(`[project.scripts]`)·`python -m physicsai_mcp.stdio`. 환경변수 §20.4 → 네트워크 클라이언트. 시작 시 `GET /mcp/tools?format=mcp&visible=true` 1회로 도구 로드(최상위 `visible`로 `tools/list` 표시 필터, §9)(실패 시 표준오류에 한국어 원인 + 종료 코드 2), `--version`·`--check`(ping 1회 후 종료) |
| `sdk_adapter.py` | 공식 SDK(`mcp`) import를 이 파일에만 둔다(버전 변화 흡수) |
| `resources.py` | 리소스 URI ↔ API 경로 표(§20.2) |

- 레이어(`test_layering` 규칙 8): `physicsai_mcp`는 `physicsai_api`·`physicsai_core`·`physicsai_worker`를 import하지 않는다. HTTP 마운트에 필요한 앱·토큰 검증 함수·스펙 로더는 `physicsai_api/main.py`가 **주입**한다(마운트 1곳: `/physicsai/mcp`, 프런트 정적 서빙보다 먼저 등록). stdio는 `mcp`·httpx·표준 라이브러리만 — 나중에 별도 경량 wheel로 떼어 낼 수 있게.
- 권한 판단 없음: 범위·허용 목록·역할·confirm·호출 제한·감사는 전부 백엔드(MR-1~12). 예외는 `tools/list` 표시 필터 하나 — 토큰 범위 미만 도구를 숨기되, 판정은 주입된 백엔드 함수(`scope_allows(scope, risk)`)가 한다(HTTP 마운트는 `load_specs(scope)`가 같은 함수로 `visible`을 채운 문서를 주입, stdio는 `GET /mcp/tools?format=mcp&visible=true` 응답의 `visible`을 씀 — `toolset`은 문서에 `visible`이 있으면 그 이름만 `tools/list`에 보이고, 없으면 전체. 숨김은 편의일 뿐, 숨긴 도구 호출도 백엔드가 거부).
- 감사: MCP 계층은 따로 기록하지 않는다. 모든 도구 호출이 백엔드 API 요청이므로 `api_audit`가 남는다(HTTP 마운트의 ASGI 호출도 미들웨어를 탄다). `initialize`·`tools/list`는 API 호출이 아니므로 감사 대상 아님(토큰 검증 실패 401은 `api_audit` 거부 행으로 기록 — `verify_token`이 감사 함수 호출).
- 로그: 메서드·도구 이름·상태·소요 시간만. 인자 값·결과 본문·Authorization 없음(V-MCP-17).
- `mcp.enabled=false` 또는 `mcp.server.http_enabled=false` → `/physicsai/mcp` 404 `MCP_DISABLED`(마운트는 하되 핸들러가 404 — openapi에는 나타나지 않음).
- 마운트 오류 본문(401·404·405 공통, 구현 반영 MR-C2): `{"code": C, "message": M, "detail": {"code": C, "message": M}}` — 최상위는 MCP 클라이언트용, `detail`은 기존 API 오류 형식(platform §10.1)과 같은 키라 같은 파서로 읽힌다. 401만 `WWW-Authenticate: Bearer`, 405는 `Allow: POST`.

### 20.2 리소스(§10 용어집·스키마 사전)

| URI | 원천 API | 내용 |
|---|---|---|
| `physicsai://glossary` | `GET /mcp/glossary` | 전체(≤ 64 KiB) |
| `physicsai://glossary/{section}`(템플릿) | `GET /mcp/glossary?section=` | entities·job_types·job_kinds·feature_abbr·enums·error_codes·stages·terms |
| `physicsai://job-kinds` | `GET /mcp/job-kinds` | 작업 종류 목록 |
| `physicsai://job-kinds/{kind}`(템플릿) | `GET /mcp/job-kinds/{kind}` | params JSON Schema·예시·한도 |

- mimeType `application/json`. 리소스를 읽지 못하는 클라이언트를 위해 같은 내용은 도구 `get_glossary`·`describe_job_kind`로도 제공(중복 의도).

### 20.3 도구 결과 변환

- 2xx: `content=[{type:"text", text: <JSON 직렬화, ensure_ascii=False>}]` + `structuredContent`(JSON 객체일 때). `mcp.server.max_result_bytes`(64 KiB) 초과 시 잘라 내지 말고 도구 오류 `RESULT_TOO_LARGE`("top_n·limit을 줄이세요").
- 4xx·5xx: `isError: true`, 본문 `{status, code, message, hint?}` — `hint` = 용어집 `error_hints[code]`(예 428 `CONFIRM_REQUIRED` → "plan_job을 먼저 호출해 confirm_token을 받으세요"). 429는 `retry_after_s` 포함.
- 연결 실패·시간 초과(`call_timeout_s` 60): `isError` + `SERVER_UNREACHABLE`·`BACKEND_TIMEOUT`.
- **MCP 계층 로컬 오류**(HTTP 호출 전·후 MCP 계층이 판정, 본문 `status: null` — `toolset._error(None, CODE, 메시지, hint?)`, 용어집 `error_codes` 자동 추출·`error_hints` 한 줄씩):

| code | 언제 | HTTP 호출 |
|---|---|---|
| `PARAMS_JSON_INVALID` | `params_json` 등 `json_string_fields`가 문자열 아님·64 KiB 초과·JSON 파싱 실패·객체 아님 | 안 함 |
| `INVALID_ARGUMENTS` | 입력 스키마에 없는 인자·필수 인자 누락·스칼라 타입 불일치·경로 인자 미충족 | 안 함 |
| `UNKNOWN_TOOL` | 스펙에 없는 도구 이름 | 안 함 |
| `SERVER_UNREACHABLE` | 백엔드 연결 실패 | 시도 |
| `BACKEND_TIMEOUT` | `call_timeout_s` 초과 | 시도 |
| `RESULT_TOO_LARGE` | 2xx 결과가 `max_result_bytes` 초과(잘라 내지 않음) | 함 |

- 리소스 읽기 실패는 SDK 오류(`INTERNAL_ERROR`) + 메시지에 위 코드(`SERVER_UNREACHABLE`·`BACKEND_TIMEOUT`·`RESULT_TOO_LARGE`).

### 20.4 stdio 환경변수

| 변수 | 필수 | 내용 |
|---|---|---|
| `PHYSICSAI_MCP_URL` | ✓ | 플랫폼 기본 주소(예 `http://<대시보드 주소>/physicsai`). 실행기가 `/api/...`를 붙인다 |
| `PHYSICSAI_MCP_TOKEN` | 둘 중 하나 | `pai_…` 토큰 |
| `PHYSICSAI_MCP_TOKEN_FILE` | 둘 중 하나 | 토큰 한 줄 파일 경로(**권장** — 일부 클라이언트가 상속 환경변수의 TOKEN류를 지우거나 설정 파일에 평문이 남는 것을 피함). 둘 다 있으면 TOKEN 우선 |
| `PHYSICSAI_MCP_CA_BUNDLE` | – | 사내 인증서 묶음 경로(HTTPS일 때) |
| `PHYSICSAI_MCP_TIMEOUT_S` | – | 기본 60 |

### 20.5 배포

- 의존(구현 반영): `pyproject.toml`에 **`mcp==2.3.0`** 정확 고정, `deploy/requirements.lock`에 `mcp==2.3.0`·`mcp-types==2.3.0`과 전이 의존(attrs·cffi·cryptography·httpcore2·httpx2·jsonschema*·pycparser·PyJWT·python-multipart·pywin32(Windows 전용)·referencing·rpds-py·sse-starlette·truststore) 정확 버전 추가(MR-18), `collect-offline.{sh,ps1}`가 wheel 수집(폐쇄망). SDK import는 `physicsai_mcp/sdk_adapter.py` 한 파일.
- 설치: `setup.ps1`·`update-repo.ps1`·묶음 `install.ps1`·`update.ps1`이 기존 플랫폼 설치 단계에서 함께 설치(별도 단계 없음). HTTP 전송은 **백엔드 프로세스 안 마운트라 새 작업 스케줄러 작업·포트 불필요**.
- 프록시: 대시보드 Vite 프록시는 `/physicsai` 전체를 전달하므로 무변경. Caddy 설치는 `deploy/caddy/physicsai.caddy`에 `handle /physicsai/mcp* { reverse_proxy 127.0.0.1:{$PHYSICSAI_PORT:8100} }`를 `/physicsai/*` 앞에 추가(관리자 매뉴얼 §2.6.2 갱신).
- stdio: 사용자 PC 설치는 **선택**(가이드 §21) — 서버 PC에서 클라이언트를 쓰면 설치된 venv의 `physicsai-mcp` 그대로. 사용자 PC는 묶음 wheels로 venv 설치(`pip install --no-index --find-links <묶음>\wheels physicsai-platform`, 전체 의존이 함께 설치됨 — 경량 wheel 분리는 후속).
- `/status` `features.mcp`(기존) + `features.mcp_http`(마운트 활성) 추가.

## 21. 지원 클라이언트(2026-10-21 사용자 확정)

### 21.1 지원 표

| 클라이언트 | 전송 | 설정 위치(예시 파일 `deploy/mcp/examples/`) | 토큰 전달 |
|---|---|---|---|
| Claude Code CLI | HTTP(`.mcp.json` `type:"http"`·`url`·`headers`, 또는 `claude mcp add --transport http …`) / stdio(`claude mcp add … -- physicsai-mcp` 명령, 예시 파일 없음) | `claude.mcp.json`(HTTP, 서버 이름 `physicsai`) | `headers.Authorization: "Bearer ${PHYSICSAI_MCP_TOKEN}"` 환경변수 확장, stdio는 `--env PHYSICSAI_MCP_TOKEN_FILE` |
| Claude Desktop | **기본(v0.2.8): `npx mcp-remote` 브리지**(Node.js 필요) / 대안: stdio | `claude_desktop_config.json`(브리지: `command: "npx"`·`args`·`env.AUTH`) / `claude_desktop_config.stdio.json`(stdio) | 브리지: `env.AUTH = "Bearer <토큰>"` + `args`의 `Authorization:${AUTH}`(§23.3), stdio: `env.PHYSICSAI_MCP_URL`·`env.PHYSICSAI_MCP_TOKEN_FILE` |
| OpenAI Codex CLI[^2] | `~/.codex/config.toml` — **기본(v0.2.8): 브리지 `[mcp_servers.physicsai]`**(`command = "npx"`·`args`·`[…env]` AUTH) / 대안: stdio `[mcp_servers.physicsai_stdio]` | `codex.config.toml`(브리지) / `codex.config.stdio.toml`(stdio) | 브리지: `env.AUTH`(§23.3), stdio: `env.PHYSICSAI_MCP_TOKEN_FILE` |
| Gemini CLI[^3] — 브리지(기본, v0.2.8) | `~/.gemini/settings.json` `mcpServers.physicsai` — Claude Desktop과 같은 항목(`command: "npx"`·`args`·`env`) | `gemini.settings.json` | `env.AUTH`(§23.3) |
| Gemini CLI — stdio(대안) | 같은 파일 `mcpServers.physicsai`(`command`·`env`·`timeout`·`trust`) — 브리지와 같은 서버 이름이라 **파일을 나눔**(둘 중 하나만 쓴다) | `gemini.settings.stdio.json` | `env.PHYSICSAI_MCP_TOKEN_FILE`(Gemini CLI가 상속 환경변수의 토큰류를 지울 수 있음) |
| 사내 LLM 클라이언트(MCP 지원) | 지원하는 쪽(Q4) | – | 같은 규칙 |
| MCP 미지원 클라이언트 | – | `GET /mcp/tools?format=openai` 함수 정의 + 사용자 측 HTTP 호출 | Bearer |

- "chatgpt" 요구는 **Codex CLI로 충족**. 모델 엔드포인트(사내 on-premise 배포) 설정은 각 사내 배포 안내를 따른다(플랫폼 범위 밖).
- 예시 파일 = `deploy/mcp/examples/` 7파일 + `README.txt`(파일별 용도, v0.2.8: 브리지 기본 + `*.stdio.*` 대안 추가). 가이드 [mcp-clients.md](../manual/mcp-clients.md) §4의 json 블록 = json 예시 5파일(파싱 결과 일치), toml 블록들을 합친 것 = `codex.config.toml` + `codex.config.stdio.toml`(V-MCP-19, `backend/tests/common/test_mcp_examples.py`).
- 설정 파일에 토큰 평문 금지 권고(가이드·V-MCP-19 예시에 `pai_` 0건). 예외(MR-C3, 사용자 원칙 "사용성 우선"): 웹 "AI 연결(MCP)" 페이지의 기본 복사본은 토큰 포함 완성본이고 평문이 남는다는 경고 + env/토큰 파일 대안을 함께 보인다(§23.2). 저장소 예시 파일·가이드 블록의 `pai_` 0건 규칙은 그대로. 클라이언트별 키 이름은 구현 시점 각 클라이언트 문서로 다시 확인(키 이름 변경 시 예시 파일·가이드만 고침 — 서버 무변경).

### 21.2 범위 밖: ChatGPT 웹·데스크톱 앱(developer mode 커넥터)

- 커넥터 인증이 OAuth 또는 무인증만이고 서버가 OpenAI 쪽에서 접근 가능해야 함[^1] → 폐쇄망 정적 Bearer 구조로는 불가. 사내 on-premise라도 OAuth가 필요하다.
- 조건부: 사내 배포가 정적 Bearer(또는 사내망 한정 무인증) 커스텀 커넥터를 지원하면 HTTP 엔드포인트(`/physicsai/mcp`)로 연결 가능.
- 후속 후보: OAuth 2.1 인가 서버(대시보드 로그인 연동) + 접근 경로 — 별도 계약.

## 22. 출처(2026-10-21 메인 조사)

[^1]: OpenAI, Developer mode — https://developers.openai.com/api/docs/guides/developer-mode
[^2]: Codex CLI MCP 설정(`config.toml` `mcp_servers`) — https://www.tembo.io/blog/codex-cli-mcp
[^3]: Gemini CLI MCP 설정(`settings.json` `mcpServers`·`httpUrl`·`headers`) — https://docs.bland.ai/integrations/mcp/clients/gemini-cli.md

## 23. 웹 "AI 연결(MCP)" 페이지(MR-C3, v0.2.7)

사용자 요구(2026-10-22): "웹에 MCP 사용할 수 있는 창이 나타나던지 메뉴가 있어야지. MatNexus 참고해." 참고 구현(읽기 전용): MatNexus `frontend/src/shared/components/McpSetup.tsx`(설계 이유 주석)·`AccessTokens.tsx`·`modules/auth/ProfilePage.tsx`("액세스 토큰" + "AI 도구에 등록하기"), 백엔드 `/auth/mcp-connection`(`MCP_PUBLIC_URL`). 물려받는 원칙 셋: ① 토큰이 없어도 **완성된 설정 형식**을 보여 주고 발급하면 그 자리에 토큰을 채운다, ② 사람이 문서에서 옮겨 적지 않고 **완성본을 복사**한다, ③ 서버 주소는 **서버가 준다**(모를 때만 짐작하고 짐작이라고 표시). MatNexus와 다른 점: 폐쇄망이라 `npx mcp-remote`(Node) 브리지 대신 우리 stdio 실행기 `physicsai-mcp`(§20, 토큰을 env로 받아 헤더 공백 문제 없음).

### 23.1 메뉴·경로

- 상단 바 메뉴 **"AI 연결(MCP)"**(`/status` `features.mcp`일 때만, 전원) → 한 페이지 `/me/ai-connection`. 기존 상단 바 "내 API 토큰"은 이 메뉴로 대체하고 기존 경로 `/me/api-tokens`(프런트 라우트)는 `/me/ai-connection#tokens`로 리다이렉트. 관리 메뉴 "API 토큰 관리"(전역 관리자)는 그대로.
- `features.mcp = false`면 메뉴 없음(기존 §4.5). 대신 관리 화면(전역 관리자 — 기존 관리 첫 화면의 기능 상태 영역)에 한 줄: "AI 연결(MCP)이 꺼져 있습니다 — 설정 `mcp.enabled: true`(HTTP는 `mcp.server.http_enabled`) 후 백엔드 재시작(`deploy/restart.ps1`). 안내: 관리자 매뉴얼 MCP 절". (roadmap §6 "MCP 활성 관리자 안내 링크" 항목을 이것으로 종결.)

### 23.2 페이지 구성(위에서 아래, 한 페이지)

| # | 영역 | 내용 |
|---|---|---|
| ① | 상태 | MCP 켜짐(`enabled`)·HTTP 켜짐(`http_enabled`)·서버 주소(`url`, `url_source = guess`면 회색 배지 "짐작 — 관리자에게 mcp.public_url 설정 요청")·내 역할(전역 관리자/프로젝트별 최고 역할 요약 — 기존 `GET /me`)·발급 가능한 범위(read/run/admin — §4.4 규칙). 전역 관리자에게는 HTTP 꺼짐일 때 켜는 방법 한 줄 |
| ② | 토큰(`#tokens`) | 기존 "내 API 토큰" 화면(§4.5 — 표·발급·폐기·1회 표시) 컴포넌트를 그대로 흡수. 발급 직후 평문은 이 페이지 컴포넌트 상태에만 들고 ③에 전달(대화 닫아도 페이지를 떠나기 전까지 ③ 채움 유지, 떠나면 사라짐) |
| ③ | **AI 도구에 등록하기** | 탭 4개 Claude Code / Claude Desktop / Codex CLI / Gemini CLI. 각 탭 = 완성된 설정(명령·JSON·TOML) + [복사] 버튼(복사 실패 시 "복사됨"을 띄우지 않음 — 클립보드 API 없는 http 접속 대비, 선택 영역 폴백) + 붙여 넣을 위치 한 줄. 토큰 자리 = 발급 전 자리표시자 `‹발급받은_토큰›`, 발급 직후 실제 토큰. **기본은 토큰 포함 완성본**(사용성 우선 — 사용자 원칙) + 접힘 대안 "환경변수/토큰 파일 방식"(§21.1·`deploy/mcp/examples/` 형식, `pai_` 없음) + 경고 한 줄 "이 설정을 저장하면 토큰이 설정 파일에 평문으로 남습니다 — 공유 PC·저장소에 올리지 마세요. 유출 시 즉시 폐기" |
| ④ | 사용 가능한 도구(접힘) | `GET /mcp/tools?format=mcp&visible=true`의 `visible` 이름 + 각 도구 `summary_ko`(세션 요청이라 전체 — 화면은 **선택한/최근 발급 토큰 범위** 기준으로 거른다: 판정 = `annotations.x-risk` ≤ 범위, 표시 편의일 뿐 권한은 백엔드) |
| ⑤ | 연결 시험 | 버튼 "연결 시험": (a) 웹 세션으로 `GET /mcp/ping`(`ok`·`server_version`·`tools_count`) + `GET /mcp/connection`(`http_enabled`) → "서버 정상"; (b) 방금 발급한 토큰이 화면 상태에 있고 `url`이 현재 origin과 같으면 그 토큰으로 `POST {url}` JSON-RPC `initialize` 1회(Accept `application/json, text/event-stream`) → "토큰으로 MCP 연결 정상 / 401(토큰 문제) / 404(MCP 꺼짐)". (b) 조건이 안 되면 "AI 도구에서 `ping` 도구를 불러 확인하세요" 안내 |

### 23.3 탭별 완성 설정(서버 이름 `physicsai`, `{url}` = HTTP MCP 주소, `{api}` = stdio 기본 주소, `{tok}` = 토큰 또는 자리표시자)

| 탭 | 기본(토큰 포함) | 접힘 대안(토큰 비포함) |
|---|---|---|
| Claude Code | 명령 `claude mcp add --transport http physicsai {url} --header "Authorization: Bearer {tok}"` | `.mcp.json` HTTP + `${PHYSICSAI_MCP_TOKEN}`(예시 `claude.mcp.json`), stdio `claude mcp add physicsai --env PHYSICSAI_MCP_URL={api} --env PHYSICSAI_MCP_TOKEN_FILE=<경로> -- physicsai-mcp` |
| Claude Desktop | **v0.2.8: mcp-remote 브리지.** `claude_desktop_config.json`의 `mcpServers` **안에 넣을 항목만**(바깥 중괄호 없음 — 기존 설정 덮어쓰기 방지): `"physicsai": {"command": "npx", "args": ["-y","mcp-remote","{url}","--allow-http","--header","Authorization:${AUTH}"], "env": {"AUTH": "Bearer {tok}", "NODE_OPTIONS": "--use-system-ca"}}` | stdio 항목 `command: "physicsai-mcp"`·`env.PHYSICSAI_MCP_URL = {api}`·`PHYSICSAI_MCP_TOKEN_FILE`(예시 `claude_desktop_config.stdio.json`) |
| Codex CLI | `~/.codex/config.toml`: 같은 브리지를 TOML로 — `[mcp_servers.physicsai]` `command = "npx"`·`args = [...]` + `[mcp_servers.physicsai.env]` `AUTH = "Bearer {tok}"`·`NODE_OPTIONS = "--use-system-ca"` | stdio `[mcp_servers.physicsai_stdio]`(`command = "physicsai-mcp"`·`env.PHYSICSAI_MCP_TOKEN_FILE`, 예시 `codex.config.stdio.toml`) |
| Gemini CLI | `~/.gemini/settings.json`의 `mcpServers` 안 항목 = **Claude Desktop 항목과 같다**(브리지) | stdio 항목 `command`·`env.PHYSICSAI_MCP_TOKEN_FILE`(예시 `gemini.settings.stdio.json`) |

- 브리지 규칙(v0.2.8, 이슈 #10): 헤더 값의 공백 때문에 `args`에 토큰을 넣지 않고 `env.AUTH` + `${AUTH}` 참조(치환은 mcp-remote). `{url}`은 `GET /mcp/connection`의 `url`(없으면 접속 주소 짐작 + 짐작 표시). 화면 안내: "Claude Code를 뺀 셋은 Node.js가 필요합니다(npx 사용)."
- stdio는 접힌 대안("Node.js를 쓸 수 없는 PC")에만 남고 거기에 실행기 설치 한 줄을 둔다: "서버 PC: 설치된 venv의 `physicsai-mcp`(경로 `{stdio_hint.command_path}`) / 내 PC: 관리자에게 오프라인 묶음 `wheels`를 받아 `pip install --no-index --find-links <wheels> physicsai-platform`(Python 3.12) — 이 실행기는 Node.js 불필요(기본 브리지는 필요)"(`stdio_hint.install`, 응답 스키마 불변·문구만 v0.2.8 변경). `command`에 전체 경로가 필요하면 그 경로로 바꾸라는 안내.
- 설정 문자열은 프런트 순수 함수(`frontend/src/lib/mcpSetup.ts`: `buildConfigs({url, api, token}) -> {claudeCode, desktop, codex, gemini, alt…}`) 한 곳에서 만들고, JSON은 `JSON.stringify`, TOML은 문자열 이스케이프 함수로 만든다(따옴표·역슬래시). 클라이언트별 키 이름이 바뀌면 이 함수·§21.1·예시 파일만 고친다(서버 무변경).
- 평문 토큰 규칙(§4.5) 유지: 컴포넌트 상태에만, localStorage·sessionStorage·전역 저장소·URL·로그·오류 보고에 쓰지 않는다. 복사는 사용자 동작으로만.

### 23.4 API `GET /mcp/connection`(세션 전용)

| 항목 | 내용 |
|---|---|
| 권한 | 로그인(세션). 토큰 요청 403 `SESSION_REQUIRED`(§4.4 토큰 API와 같은 처리), `x-mcp: {"exclude": "웹 연결 안내 전용(세션)"}` |
| 응답 | `{enabled: bool, http_enabled: bool, url: str, url_source: "config"\|"guess", api_base: str, stdio_hint: {command: "physicsai-mcp", command_path: str\|null, install: str}}` |
| `url` | 설정 `mcp.public_url`(신규, 예 `https://host/physicsai/mcp`)이 있으면 그 값(`url_source: config`), 없으면 요청 origin(`X-Forwarded-Proto/Host` 신뢰는 기존 `client_ip`·프록시 설정 규칙과 같게) + `/physicsai/mcp`(`guess`) |
| `api_base` | stdio `PHYSICSAI_MCP_URL`용(§20.4) = `url`에서 끝의 `/mcp`를 뗀 값(예 `https://host/physicsai`) |
| `command_path` | 서버 venv의 실행기 경로(`sys.prefix` 기준 `Scripts\physicsai-mcp.exe`/`bin/physicsai-mcp`, 없으면 null) — 경로만, 비밀 없음 |
| 꺼짐 | `mcp.enabled=false`면 404 `MCP_DISABLED`(기존 `/mcp/*` 규칙 — 라우트는 항상 등록) |

- 설정 키 `mcp.public_url: null`(문자열, `http(s)://…/mcp`로 끝나야 — 아니면 설정 오류 `mcp.public_url`). `config/platform.example.yaml`·`platform.demo.yaml`에 주석과 함께 **추가만**(기본 null = 기존 동작). `/status` 변경 없음.

### 23.5 구현 분해(M7)

| 담당 | 범위 |
|---|---|
| Impl-Backend | `config/schema_mcp.py`(`public_url` + 검증), `physicsai_api/routers/mcp.py`(`GET /mcp/connection`·x-mcp exclude·세션 전용), schemas, `backend/openapi.json`·`operation_ids.txt`, `route_policy` 동결 목록 영향 없음 확인, 시험(설정/짐작·토큰 403·꺼짐 404) |
| Impl-Frontend | `pages/AiConnection.tsx`(신규, 기존 `ApiTokens.tsx` 흡수), `lib/mcpSetup.ts`, `shell/TopBar.tsx`(메뉴 이름·경로), `app/App.tsx`(리다이렉트), 관리 화면 꺼짐 안내 한 줄, mock·시험, `frontend-dist` |
| Plan | [mcp-clients.md](../manual/mcp-clients.md) §1 "상단 바 AI 연결(MCP)" 갱신(이 커밋) |

### 23.6 검증(V-MCP-21~26)

| ID | 항목 | 기준 |
|---|---|---|
| V-MCP-21 | 자리표시자 → 발급 후 채움 | 발급 전 4탭 설정에 `‹발급받은_토큰›`, 발급 응답 후 같은 자리에 그 토큰, 페이지 이탈 후 재진입 시 다시 자리표시자 |
| V-MCP-22 | 저장소 미사용 | 정적 시험: 토큰 평문을 localStorage·sessionStorage·전역 저장소·URL에 쓰는 코드 0, 기존 `apiTokens` 정적 시험을 새 페이지로 확장 |
| V-MCP-23 | 설정 문법 | `buildConfigs` 출력(자리표시자·실제 형식 토큰 각각): Claude Desktop·Gemini 항목은 `{…}`로 감싸 JSON 파싱, Codex는 TOML 파싱(프런트 시험 파서 또는 백엔드 `tomllib` 골든), Claude Code 명령은 셸 분해 시 인자 수·`--header` 값 1개. 대안 블록은 `pai_` 0건·예시 파일(V-MCP-19)과 키 일치 |
| V-MCP-24 | 주소 출처 | `mcp.public_url` 설정 → `url_source: config`·화면 배지 없음, 미설정 → `guess`·"짐작" 배지, `api_base` = `/mcp` 뗀 값, 잘못된 설정값 → 설정 오류 |
| V-MCP-25 | 연결 시험 | 세션 ping 성공·실패 표시, 같은 origin + 토큰이면 `initialize` 200 → 정상, 폐기 토큰 401·MCP 꺼짐 404 문구 |
| V-MCP-26 | 경로·권한 | `features.mcp=false` → 메뉴 없음·관리 화면 안내 한 줄(전역 관리자만), `/me/api-tokens` → `/me/ai-connection#tokens` 리다이렉트, `GET /mcp/connection` 토큰 요청 403·x-mcp exclude(V-MCP-6) |

## 변경 메모(MR-Cn)

- **MR-C1**(2026-10-21, 사용자 결정 — Plan): 범위를 "MCP 준비"에서 **MCP 기능 전체**로 확장하고 파일 이름을 `mcp-ready.md` → `mcp.md`로 변경(ID 접두 MR·V-MCP 유지). 추가: MR-13(토큰·스냅숏 30일 — 초안 90일·14일 대체), MR-14~18(SDK 서버·두 전송·이식 가능 스키마·ping·오프라인 의존), §9.2·§20·§21, V-MCP-14~20, M5·M6. 지원 클라이언트 Claude·Codex CLI·Gemini CLI(사내 on-premise 모델 전제), ChatGPT 웹 앱 범위 밖. migration `0020_mcp` 확정. Q1 종결, Q2·Q3 기본 진행값 명시, Q4 추가. 릴리스 v0.2.4.
- **MR-C2**(2026-10-21, Plan — v0.2.4 구현 반영, 기준 `feat/r1-v024` 8206870): 구현과 계약 차이를 계약에 맞춤. ① `GET /mcp/tools?format=mcp&visible=true` — 최상위 `visible`(토큰 범위로 부를 수 있는 도구, 판정 백엔드 `scope_allows`), stdio가 `tools/list` 필터에 사용(§9·§20.1). ② 마운트 401·404·405 본문 `{code, message, detail:{code, message}}`, 비POST 405 `METHOD_NOT_ALLOWED`(§20.1). ③ MCP 계층 로컬 오류 6종(status null)·용어집 `error_hints`(§20.3·§10). ④ V-MCP-14 화이트리스트는 도구 입력 스키마(`tools.*.json`)만, `job_kinds.json`(생성 파일 추가) params_schema는 모양 검사(§9·§9.2). ⑤ 클라이언트 예시 5파일 — Gemini는 HTTP·stdio 분리(§21.1, 가이드 갱신). ⑥ 도구 17개(`find_similar_designs` 제외, `get_native_vars` 포함 — PUT은 exclude), `param_set` 요약 facts `vars_revision`·`vars_count`(§7·§9.1). ⑦ `mcp==2.3.0` 고정·lock 전이 의존 추가, 세션 관리자 요청마다 생성(lifespan 무관), 용어집 `error_codes` 추출에 `_error(...)` 포함(§10·§20.1·§20.5). ⑧ 토큰 화면: 메뉴는 `features.mcp`일 때만, 평문 1회 표시·복사·저장소 미사용, 관리자 "API 토큰 관리"(user_id·active 필터·폐기) 구현 — 초안의 "관리자 화면 비범위"를 대체(§4.5·§16 M4·V-MCP-13).
- **MR-C3**(2026-10-22, 사용자 요구 — Plan, 릴리스 v0.2.7): 웹 **"AI 연결(MCP)" 페이지**(§23) — 상단 바 메뉴(`features.mcp`일 때만)가 "내 API 토큰"을 대체하고 한 페이지에 상태·토큰·"AI 도구에 등록하기"(Claude Code·Claude Desktop·Codex CLI·Gemini CLI 완성 설정 복사, 발급 전 자리표시자 `‹발급받은_토큰›` → 발급 직후 실제 토큰, 기본 토큰 포함·대안 env/토큰 파일 접힘 + 평문 경고)·도구 목록·연결 시험. 새 API `GET /mcp/connection`(세션 전용·x-mcp exclude), 설정 `mcp.public_url`(없으면 origin 짐작 + "짐작" 표시), stdio는 `physicsai-mcp` 기준(Node·mcp-remote 불필요). `/me/api-tokens` → 새 페이지 리다이렉트, 꺼짐이면 관리 화면에 켜는 방법 한 줄(roadmap §6 후속 항목 종결). M7·V-MCP-21~26. 평문 토큰 저장 금지(§4.5)는 그대로 — 화면 상태에만.
- **MR-C4**(2026-10-22, 사용자 요구 — GitHub 이슈 #10, 릴리스 v0.2.8): 클라이언트 설정 기본을 matnexus 규칙으로 변경 — Claude Code는 HTTP 직결 유지, Claude Desktop·Codex·Gemini는 `npx mcp-remote` 브리지(env `AUTH` + `${AUTH}` 참조, `NODE_OPTIONS=--use-system-ca`)가 기본이고 stdio `physicsai-mcp`는 접힌 "대안(Node.js를 쓸 수 없는 PC)"으로만 남김. 예시 파일 5 → 7(`claude_desktop_config.stdio.json`·`codex.config.stdio.toml` 추가, 브리지가 `claude_desktop_config.json`·`codex.config.toml`·`gemini.settings.json`을 대체), `stdio_hint.install` 문구 갱신(스키마·API 불변). 근거: 이슈 #10 · matnexus `McpSetup.tsx`(§21.1·§23.3·V-MCP-19 반영).
