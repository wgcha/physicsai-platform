# LLM 클라이언트 연결 가이드(MCP)

> 상태: v0.2.8 반영(2026-10-22, 이슈 #10 — matnexus 규칙으로 기본 연결 방식 변경). 계약 [mcp.md](../contracts/mcp.md) §20·§21·§23.3.
> 설정 예시 원본은 `deploy/mcp/examples/` 7파일(+ `README.txt`)이고, 이 문서의 코드 블록과 내용이 같아야 한다(V-MCP-19 — json 블록 = json 예시 5파일, toml 블록 합 = `codex.config.toml` + `codex.config.stdio.toml`).

| 클라이언트 | 기본 방식 | 예시 파일 | 넣을 위치 | 이 문서 |
|---|---|---|---|---|
| Claude Code CLI | HTTP 직결 | `claude.mcp.json`(`.mcp.json` 방식) | `claude mcp add` 명령 또는 프로젝트 `.mcp.json` | §4.1 |
| Claude Desktop | `npx mcp-remote` 브리지 | `claude_desktop_config.json` | `claude_desktop_config.json`의 `mcpServers` 안 | §4.2 |
| OpenAI Codex CLI | `npx mcp-remote` 브리지 | `codex.config.toml` | `~/.codex/config.toml`(서버 `physicsai`) | §4.3 |
| Gemini CLI | `npx mcp-remote` 브리지 | `gemini.settings.json` | `~/.gemini/settings.json`의 `mcpServers` 안 | §4.4 |
| 대안(Node.js를 쓸 수 없는 PC) | stdio `physicsai-mcp` | `claude_desktop_config.stdio.json`·`codex.config.stdio.toml`·`gemini.settings.stdio.json` | 위 각 파일(브리지와 같은 서버 이름이면 둘 중 하나만) | §4.5 |

**Claude Code를 뺀 셋(Desktop·Codex·Gemini)은 Node.js가 필요하다(`npx` 사용).** Claude Code는 HTTP를 직접 받아 Node.js가 필요 없다.

## 1. 무엇을 연결하나

- PhysicsAI의 조회·작업 실행 기능을 LLM 클라이언트(Claude Code·Claude Desktop·OpenAI Codex CLI·Gemini CLI·MCP를 지원하는 사내 LLM 클라이언트)에서 도구로 쓴다.
- **전제**: 모델은 사내 on-premise 배포본을 쓴다. 클라이언트가 사내 모델 엔드포인트를 쓰도록 하는 설정은 **각 사내 배포 안내를 따른다**(이 가이드 범위 밖).
- 연결 방식 세 가지(같은 도구):
  - **HTTP 직결**(Claude Code): `http://<대시보드 주소>/physicsai/mcp` + `Authorization: Bearer <토큰>`. 설치할 것 없음.
  - **mcp-remote 브리지**(Claude Desktop·Codex·Gemini 기본): 클라이언트 설정 파일은 stdio(`command`) 서버만 받으므로 `npx -y mcp-remote`가 HTTP 주소로 이어 준다. Node.js 필요.
  - **stdio 대안**(Node.js를 쓸 수 없는 PC): 내 PC의 `physicsai-mcp` 실행기를 클라이언트가 띄운다(실행기가 플랫폼 HTTP API를 부름). 실행기 설치 필요(§5).
- 안 되는 것: ChatGPT 웹·데스크톱 앱 커넥터(OAuth 필요 — 사내 배포가 정적 Bearer 커스텀 커넥터를 지원하면 HTTP 주소로 연결 가능). "ChatGPT 계열"은 Codex CLI를 쓴다.

## 2. 토큰 발급(웹)

1. PhysicsAI 웹 → 상단 바 **AI 연결(MCP)**(v0.2.7부터, 이전 "내 API 토큰") → 토큰 영역 **발급**. 메뉴가 없으면 관리자가 `mcp.enabled`를 켜지 않은 것이다(`/status` `features.mcp`가 true일 때만 보임). 같은 페이지의 **AI 도구에 등록하기** 탭(Claude Code·Claude Desktop·Codex CLI·Gemini CLI)에서 토큰이 채워진 완성 설정을 그대로 복사할 수 있다(이 경우 설정 파일에 토큰이 평문으로 남는다 — 토큰 파일 방식은 같은 탭의 접힌 "대안 — Node.js를 쓸 수 없는 PC"에 있다). 페이지의 **연결 시험**으로 서버 상태도 확인한다.
2. 이름(예 `codex-내PC`), 범위 선택: 조회만이면 **read**(권장), 작업 실행까지면 **run**(권한이 없는 범위는 선택할 수 없고 이유가 표시된다). 만료는 최대 **30일**(기본 30일).
3. 표시된 `pai_…` 값은 한 번만 보여 준다(복사 버튼, 창을 닫으면 다시 볼 수 없음 — 브라우저 저장소에도 남지 않는다). 바로 복사해 아래 둘 중 하나에 넣는다.
   - **토큰 파일**(권장): 예 `%USERPROFILE%\.physicsai\token`(Windows)·`~/.physicsai/token`, 한 줄로 저장하고 본인만 읽게 권한 설정.
   - **사용자 환경변수** `PHYSICSAI_MCP_TOKEN`.
4. 권장: 클라이언트 설정 파일에 토큰 평문을 쓰지 않는다(아래 예시는 환경변수 참조·토큰 파일·자리표시자). 웹 페이지의 기본 복사본(토큰 포함)을 쓰면 공유 PC·저장소에 그 설정 파일을 올리지 않는다.
5. 30일이 지나면 만료된다. 만료 전 새 토큰을 발급해 파일·환경변수만 바꾸면 된다. 잃어버렸거나 유출이 의심되면 즉시 **폐기**(관리자도 폐기 가능 — 즉시 차단).

## 3. 연결 확인

- 클라이언트에서 도구 `ping`을 호출한다: 서버 버전·토큰 접두(`pai_xxxxxxxx`)·범위·남은 일수가 나오면 정상. 남은 일수 5일 이하면 경고가 함께 나온다.
- `whoami`로 내 이름·프로젝트 역할을 확인한다.
- stdio 대안은 터미널에서 `physicsai-mcp --check`(ping 1회 후 종료)로도 확인한다.

## 4. 클라이언트별 설정

브리지 항목의 규칙(4.2~4.4 공통): 헤더 값에 공백(`Bearer …`)이 있어 `args`에 토큰을 직접 넣으면 도구에 따라 잘리므로, 토큰은 `env.AUTH`에 두고 `args`에서 `Authorization:${AUTH}`로 참조한다(치환은 mcp-remote가 한다). `--allow-http`는 사내 http 주소용, `NODE_OPTIONS=--use-system-ca`는 사내 인증서를 쓰기 위한 것이다. `<대시보드 주소>`는 AI 연결 페이지 ① 상태의 서버 주소(`mcp.public_url`, 없으면 접속 주소로 짐작한 값)로, `<발급받은 토큰>`은 발급한 `pai_…` 값으로 바꾼다.

### 4.1 Claude Code CLI(HTTP 직결) — `claude.mcp.json`

Node.js 불필요. 명령 한 줄(토큰이 Claude Code 설정에 평문으로 남는다):

```bash
claude mcp add --transport http physicsai http://<대시보드 주소>/physicsai/mcp --header "Authorization: Bearer <발급받은 토큰>"
```

설정 파일에 토큰을 남기지 않으려면 예시 `claude.mcp.json`을 프로젝트 `.mcp.json`으로(환경변수 `${PHYSICSAI_MCP_TOKEN}`은 Claude Code가 실행 시 확장):

```json
{
  "mcpServers": {
    "physicsai": {
      "type": "http",
      "url": "http://<대시보드 주소>/physicsai/mcp",
      "headers": {
        "Authorization": "Bearer ${PHYSICSAI_MCP_TOKEN}"
      }
    }
  }
}
```

### 4.2 Claude Desktop(mcp-remote 브리지) — `claude_desktop_config.json`

Node.js 필요. 설정 → 개발자 → 설정 편집으로 `claude_desktop_config.json`을 열어 `mcpServers` 안에 `"physicsai": { … }` 항목만 넣고(웹 페이지의 복사본은 항목만 준다) 다시 시작한다. 예시 `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "physicsai": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://<대시보드 주소>/physicsai/mcp",
        "--allow-http",
        "--header",
        "Authorization:${AUTH}"
      ],
      "env": {
        "AUTH": "Bearer <발급받은 토큰>",
        "NODE_OPTIONS": "--use-system-ca"
      }
    }
  }
}
```

### 4.3 OpenAI Codex CLI(mcp-remote 브리지) — `codex.config.toml` → `~/.codex/config.toml`

Node.js 필요. 같은 브리지를 TOML로:

```toml
[mcp_servers.physicsai]
command = "npx"
args = ["-y", "mcp-remote", "http://<대시보드 주소>/physicsai/mcp", "--allow-http", "--header", "Authorization:${AUTH}"]

[mcp_servers.physicsai.env]
AUTH = "Bearer <발급받은 토큰>"
NODE_OPTIONS = "--use-system-ca"
```

### 4.4 Gemini CLI(mcp-remote 브리지) — `gemini.settings.json` → `~/.gemini/settings.json`

Node.js 필요. 항목은 Claude Desktop(4.2)과 같다:

```json
{
  "mcpServers": {
    "physicsai": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://<대시보드 주소>/physicsai/mcp",
        "--allow-http",
        "--header",
        "Authorization:${AUTH}"
      ],
      "env": {
        "AUTH": "Bearer <발급받은 토큰>",
        "NODE_OPTIONS": "--use-system-ca"
      }
    }
  }
}
```

### 4.5 대안: stdio `physicsai-mcp`(Node.js를 쓸 수 없는 PC)

실행기 설치가 필요하다(§5). 토큰은 한 줄 파일에 두고 설정에는 경로만 쓴다. 브리지와 같은 서버 이름(`physicsai`)이므로 Claude Desktop·Gemini는 둘 중 하나만 `mcpServers`에 넣는다(Codex는 서버 이름이 `physicsai_stdio`라 함께 둘 수 있다).

Claude Code(예시 파일 없음):

```bash
claude mcp add physicsai --env PHYSICSAI_MCP_URL=http://<대시보드 주소>/physicsai --env PHYSICSAI_MCP_TOKEN_FILE=<토큰 파일 경로> -- physicsai-mcp
```

Claude Desktop — 예시 `claude_desktop_config.stdio.json`:

```json
{
  "mcpServers": {
    "physicsai": {
      "command": "physicsai-mcp",
      "env": {
        "PHYSICSAI_MCP_URL": "http://<대시보드 주소>/physicsai",
        "PHYSICSAI_MCP_TOKEN_FILE": "<토큰 파일 경로>"
      }
    }
  }
}
```

Codex CLI — 예시 `codex.config.stdio.toml`:

```toml
[mcp_servers.physicsai_stdio]
command = "physicsai-mcp"
args = []

[mcp_servers.physicsai_stdio.env]
PHYSICSAI_MCP_URL = "http://<대시보드 주소>/physicsai"
PHYSICSAI_MCP_TOKEN_FILE = "<토큰 파일 경로>"
```

Gemini CLI — 예시 `gemini.settings.stdio.json`(Gemini CLI는 상속 환경변수 중 토큰류를 지울 수 있으므로 토큰 파일을 쓴다):

```json
{
  "mcpServers": {
    "physicsai": {
      "command": "physicsai-mcp",
      "env": {
        "PHYSICSAI_MCP_URL": "http://<대시보드 주소>/physicsai",
        "PHYSICSAI_MCP_TOKEN_FILE": "<토큰 파일 경로>"
      },
      "timeout": 60000,
      "trust": false
    }
  }
}
```

- 도구 호출마다 확인을 받도록(Gemini `trust: false`) 두고, Claude Code·Codex도 도구 승인 확인을 끄지 않는 것을 권장한다.

### 4.6 MCP를 지원하지 않는 클라이언트

- `GET http://<대시보드 주소>/physicsai/api/mcp/tools?format=openai`(Bearer 필요)가 OpenAI 호환 함수 정의를 준다. 함수 호출을 플랫폼 HTTP API로 넘기는 부분은 그 클라이언트 쪽에서 구성한다.

## 5. stdio 실행기 설치(대안 방식에만 필요)

- 서버 PC에서 클라이언트를 쓰면 플랫폼 설치 폴더의 venv에 이미 `physicsai-mcp`가 있다.
- 내 PC: 관리자에게 오프라인 묶음의 `wheels` 폴더를 받아 Python 3.12 venv에 설치한다.

```powershell
py -3.12 -m venv $env:USERPROFILE\.physicsai\venv
& $env:USERPROFILE\.physicsai\venv\Scripts\pip.exe install --no-index --find-links <묶음>\wheels physicsai-platform
```

- 클라이언트 설정의 `command`에는 `…\.physicsai\venv\Scripts\physicsai-mcp.exe` 전체 경로를 쓰면 PATH 설정이 필요 없다.

## 6. 작업 실행 흐름(run 토큰)

1. `list_job_kinds` → `describe_job_kind`로 입력 스키마 확인.
2. `plan_job`: 실행 계획(run 수·예상 시간·대기열·경고)과 `confirm_token`(10분·1회용)을 받는다. 비용 큰 작업은 이 단계 없이 실행되지 않는다.
3. 사람이 계획을 확인한 뒤 `run_job`(같은 입력 + `confirm_token`).
4. `job_status`·`job_summary`로 진행·결과 확인, 필요하면 `cancel_job`(이 토큰이 만든 작업만).

## 7. 자주 나오는 오류

| 코드 | 뜻 | 할 일 |
|---|---|---|
| 401 `API_TOKEN_EXPIRED` | 30일 만료 | 새 토큰 발급 |
| 401 `API_TOKEN_REVOKED` | 폐기됨 | 새 토큰 발급(관리자 폐기면 관리자 문의) |
| 401 `API_TOKEN_STALE` | 권한 정보가 30일 넘게 갱신 안 됨 | 웹에 한 번 로그인 |
| 403 `API_TOKEN_SCOPE` | read 토큰으로 실행 시도 | run 토큰 발급 |
| 403 `API_TOKEN_OPERATION_NOT_ALLOWED` | 도구로 열지 않은 기능(업로드·편집 등) | 웹 화면에서 직접 |
| 428 `CONFIRM_REQUIRED` | 비용 큰 작업에 확인 없음 | `plan_job` 먼저 |
| 429 `RATE_LIMITED`·`TOKEN_ACTIVE_JOB_LIMIT` | 호출·동시 작업 한도 | 잠시 후, 진행 중 작업 확인 |
| 404(`/physicsai/mcp`) | 관리자가 MCP를 끔 | 관리자 문의 |
| 405(`/physicsai/mcp`) `METHOD_NOT_ALLOWED` | HTTP 전송은 POST만(stateless JSON) | 클라이언트 전송 방식을 Streamable HTTP로 |
| `SERVER_UNREACHABLE` | stdio 실행기가 서버에 못 붙음 | `PHYSICSAI_MCP_URL`·사내망 접속 확인 |
| `BACKEND_TIMEOUT` | 60초 안에 응답 없음 | 잠시 후 다시, 조회 범위(`top_n`·`limit`) 줄이기 |
| `RESULT_TOO_LARGE` | 결과가 64 KiB 초과 | `top_n`·`limit`을 줄이거나 `section`으로 나눠 조회 |
| `PARAMS_JSON_INVALID` | `params_json`이 JSON 객체 텍스트가 아님 | `describe_job_kind`의 스키마·예시대로 |
| `INVALID_ARGUMENTS`·`UNKNOWN_TOOL` | 없는 인자·필수 누락·없는 도구 | 도구 목록·입력 스키마 확인 |

- `SERVER_UNREACHABLE`·`BACKEND_TIMEOUT`·`RESULT_TOO_LARGE`·`PARAMS_JSON_INVALID`·`INVALID_ARGUMENTS`·`UNKNOWN_TOOL`은 MCP 계층이 직접 내는 오류라 HTTP 상태가 없다(`status: null`). 각 오류 결과의 `hint`에 할 일이 한 줄 붙는다.
- 도구 목록(`tools/list`)에는 내 토큰 범위로 부를 수 있는 도구만 보인다(read 토큰에는 `run_job`·`cancel_job` 등 없음).

## 8. 관리자 메모

- 켜기: `mcp.enabled: true`(설정 키 전체는 mcp.md §13). HTTP 전송은 백엔드 안에서 돌아 새 작업·포트가 없다. Caddy 설치는 `handle /physicsai/mcp*`를 `/physicsai/*` 앞에 추가.
- 즉시 차단: 웹 관리 메뉴 **API 토큰 관리**(전역 관리자, 사용자 ID·유효 여부 필터) → 폐기, 또는 `POST /admin/api-tokens/{id}/revoke`. 계정 정지만으로는 토큰이 만료(최대 30일)까지 남는다.
- 감사: `GET /physicsai/api/mcp/audit`(전역 관리자) — 토큰 요청 이력(본문 없음).
