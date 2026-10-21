"""MCP 기능(mcp.md): 작업 종류·요약 레지스트리, operation 정책, 감사 미들웨어, 호출 제한, 용어집·도구 스펙 생성물.

MCP 서버 자체(Streamable HTTP·stdio)는 별도 패키지 `physicsai_mcp`(백엔드 HTTP API만 부르는 얇은 래퍼)다 — 이 패키지는 플랫폼 쪽
기능만 한다. `mcp.enabled: false`(기본)면 모두 꺼진다.
"""
