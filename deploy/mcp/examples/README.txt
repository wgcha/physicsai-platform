PhysicsAI MCP 클라이언트 설정 예시(docs/contracts/mcp.md §21, docs/manual/mcp-clients.md).
토큰 평문(pai_…)은 어느 파일에도 쓰지 않는다 — 환경변수 참조 또는 토큰 파일 경로만. <…> 자리표시자는 내 환경 값으로 바꾼다.
이 파일들은 가이드의 코드 블록과 내용이 같아야 하고(backend/tests/common/test_mcp_examples.py가 검사), 클라이언트 키 이름이 바뀌면 여기와 가이드만 고친다(서버 무변경).

claude.mcp.json                 Claude Code CLI(HTTP) — 프로젝트 .mcp.json
claude_desktop_config.json      Claude Desktop(stdio)
codex.config.toml               OpenAI Codex CLI — ~/.codex/config.toml (HTTP 서버 physicsai + stdio 서버 physicsai_stdio)
gemini.settings.json            Gemini CLI(HTTP) — ~/.gemini/settings.json
gemini.settings.stdio.json      Gemini CLI(stdio) — ~/.gemini/settings.json (HTTP와 같은 이름 physicsai라 파일을 나눔)
