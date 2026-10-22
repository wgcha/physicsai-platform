PhysicsAI MCP 클라이언트 설정 예시(docs/contracts/mcp.md §21, docs/manual/mcp-clients.md).
기본은 Claude Code = HTTP 직결, Claude Desktop·Codex CLI·Gemini CLI = `npx mcp-remote` 브리지(Node.js 필요, 이슈 #10·matnexus 규칙).
브리지는 헤더 값의 공백 때문에 args에 토큰을 넣지 않고 env AUTH에 "Bearer <토큰>"을 두고 args에서 ${AUTH}로 참조한다(치환은 mcp-remote).
stdio(physicsai-mcp, PC에 wheel 설치·토큰 파일)는 Node.js를 쓸 수 없는 PC용 대안이다(*.stdio.* 파일).
브리지 예시의 AUTH 값은 자리표시자다 — 토큰 평문(pai_…)은 어느 파일에도 쓰지 않는다. <…> 자리표시자는 내 환경 값으로 바꾼다.
이 파일들은 가이드의 코드 블록과 내용이 같아야 하고(backend/tests/common/test_mcp_examples.py가 검사), 클라이언트 키 이름이 바뀌면 여기와 가이드만 고친다(서버 무변경).

claude.mcp.json                 Claude Code CLI(HTTP) — 프로젝트 .mcp.json (환경변수 토큰, 접힌 대안)
claude_desktop_config.json      Claude Desktop(mcp-remote 브리지, 기본) — mcpServers 안의 항목
claude_desktop_config.stdio.json Claude Desktop(stdio 대안) — 브리지와 같은 이름 physicsai라 파일을 나눔
codex.config.toml               OpenAI Codex CLI(mcp-remote 브리지, 기본) — ~/.codex/config.toml 의 [mcp_servers.physicsai]
codex.config.stdio.toml         OpenAI Codex CLI(stdio 대안) — [mcp_servers.physicsai_stdio] (브리지와 함께 둘 수 있음)
gemini.settings.json            Gemini CLI(mcp-remote 브리지, 기본) — C:\Users\<사용자>\.gemini\settings.json (없으면 새로 만듦)
gemini.settings.stdio.json      Gemini CLI(stdio 대안) — C:\Users\<사용자>\.gemini\settings.json (없으면 새로 만듦) (브리지와 같은 이름 physicsai라 파일을 나눔)
