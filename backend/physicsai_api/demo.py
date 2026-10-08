"""시연 모드(fake tools 배포판) 전용: 내장 가짜 대시보드 인증·로그인 화면·프런트 정적 서빙.

- 설정 `demo.enabled=true` + `auth.mode=demo`일 때만 쓰인다. 운영 설정에서는 켤 수 없다:
  설정 검증(profile=dev, server.host=127.0.0.1)과 기동 검사(`check_demo_startup`, 실제 바인드 주소 127.0.0.1)가 이중으로 막는다.
- 사용자는 고정 3명(admin·power·general) 중에서 고른다. 토큰은 `demo-<역할>` 고정 문자열이라 비밀이 아니며,
  인증은 실제 대시보드 경로(`DashboardClient` → `/api/auth/me`)를 그대로 거치고 전송 계층만 내장 가짜로 바꾼다.
- 로그인 요청은 루프백 클라이언트에서만 받는다.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from physicsai_core.config import Settings
from physicsai_core.errors import DomainError

DEMO_PROJECT_ID = "demo"
TOKEN_PREFIX = "demo-"
LOGIN_PATH = "/physicsai/api/demo/login"
LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}

DEMO_USERS: dict[str, dict[str, Any]] = {
    "admin": {"id": "demo-admin", "username": "admin", "display_name": "시연 관리자", "account_status": "ACTIVE",
              "is_global_admin": True, "memberships": [{"project_id": DEMO_PROJECT_ID, "role": "admin"}]},
    "power": {"id": "demo-power", "username": "power", "display_name": "시연 파워 사용자", "account_status": "ACTIVE",
              "is_global_admin": False, "memberships": [{"project_id": DEMO_PROJECT_ID, "role": "power"}]},
    "general": {"id": "demo-general", "username": "general", "display_name": "시연 일반 사용자", "account_status": "ACTIVE",
                "is_global_admin": False, "memberships": [{"project_id": DEMO_PROJECT_ID, "role": "general"}]},
}
ROLE_LABEL = {"admin": "관리자 — 환경 점검·전체 작업 관리", "power": "파워 사용자 — 작업 실행", "general": "일반 사용자 — 조회만"}
DEMO_PROJECTS = [{"id": DEMO_PROJECT_ID, "name": "시연 프로젝트", "product_name": "시연", "description": "fake tools 시연용",
                  "created_at": "2026-01-01", "selection_metadata": {}}]


def demo_token(role: str) -> str:
    return TOKEN_PREFIX + role


def demo_problem(s: Settings, bind_host: str | None = None) -> str | None:
    """시연 모드를 쓸 수 없는 이유(없으면 None). demo 관련 설정이 하나도 없으면 None."""
    if not (s.demo.enabled or s.auth.mode == "demo" or s.demo.frontend_root):
        return None
    host = bind_host or s.server.host
    if not s.demo.enabled:
        return "auth.mode=demo·demo.frontend_root는 demo.enabled=true일 때만 쓸 수 있습니다"
    if s.profile != "dev":
        return "시연 모드는 profile=dev에서만 허용됩니다"
    if s.server.host != "127.0.0.1" or host != "127.0.0.1":
        return "시연 모드는 127.0.0.1 바인딩에서만 허용됩니다"
    return None


def demo_transport() -> httpx.MockTransport:
    """대시보드 `/api/auth/me`·`/api/projects`를 흉내 내는 내장 전송 계층(네트워크 사용 없음)."""

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        role = token[len(TOKEN_PREFIX):] if token.startswith(TOKEN_PREFIX) else ""
        user = DEMO_USERS.get(role)
        if user is None:
            return httpx.Response(401, json={"detail": "인증 필요"})
        if request.url.path.endswith("/auth/me"):
            return httpx.Response(200, json={**user, "employee_id": None, "company_permissions": [], "role": None})
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json=DEMO_PROJECTS)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in LOOPBACK_CLIENTS:
        raise DomainError("FORBIDDEN", "시연 로그인은 이 PC(127.0.0.1)에서만 할 수 있습니다", status=403)


def _login_page(current: str | None) -> str:
    buttons = "".join(
        f'<button type="submit" name="role" value="{r}"{" class=cur" if r == current else ""}>'
        f"<b>{html.escape(u['display_name'])}</b> ({u['username']})<br><small>{html.escape(ROLE_LABEL[r])}</small></button>"
        for r, u in DEMO_USERS.items()
    )
    cur = f"<p>현재 로그인: <b>{html.escape(DEMO_USERS[current]['display_name'])}</b></p>" if current in DEMO_USERS else ""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PhysicsAI 시연 로그인</title>
<style>
body{{font-family:system-ui,'Malgun Gothic',sans-serif;max-width:560px;margin:40px auto;padding:0 16px;background:#f6f7f9;color:#1d2330}}
.badge{{display:inline-block;background:#b45309;color:#fff;border-radius:4px;padding:2px 8px;font-size:13px}}
form{{display:grid;gap:10px;margin-top:16px}}
button{{text-align:left;padding:12px 14px;border:1px solid #c8ced8;border-radius:6px;background:#fff;font-size:15px;cursor:pointer}}
button:hover,button.cur{{border-color:#2563eb;background:#eef4ff}}
small{{color:#5b6475}}
</style></head><body>
<p><span class="badge">시연 모드</span></p>
<h1>PhysicsAI 시연 로그인</h1>
<p>실제 Altair 대신 가짜 도구(fake tools)로 동작합니다. 사용할 사용자를 고르세요.</p>
{cur}
<form method="post" action="{LOGIN_PATH}">{buttons}</form>
<p style="margin-top:24px"><a href="/physicsai/">플랫폼 화면으로 이동</a> · <a href="/physicsai/api/demo/logout">로그아웃</a></p>
</body></html>"""


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    cookie = settings.auth.cookie_name

    @router.get("/demo/login")
    def login_page(request: Request) -> HTMLResponse:
        _require_loopback(request)
        tok = request.cookies.get(cookie) or ""
        current = tok[len(TOKEN_PREFIX):] if tok.startswith(TOKEN_PREFIX) else None
        return HTMLResponse(_login_page(current))

    @router.post("/demo/login")
    async def login(request: Request) -> Response:
        _require_loopback(request)
        body = (await request.body()).decode("utf-8", errors="replace")
        role = (parse_qs(body).get("role") or [""])[0]
        if role not in DEMO_USERS:
            raise DomainError("INVALID_PARAMS", "role은 admin | power | general 중 하나입니다", status=422)
        r = RedirectResponse("/physicsai/", status_code=303)
        r.set_cookie(cookie, demo_token(role), httponly=True, samesite="lax", path="/")
        return r

    @router.get("/demo/logout")
    def logout(request: Request) -> Response:
        _require_loopback(request)
        r = RedirectResponse(LOGIN_PATH, status_code=303)
        r.delete_cookie(cookie, path="/")
        return r

    return router


def mount_frontend(app: FastAPI, frontend_root: str) -> None:
    """Caddy 없이 프런트 빌드를 /physicsai/ 아래에 서빙(try_files {path} /index.html 과 같은 규칙)."""
    root = Path(frontend_root).resolve()
    index = root / "index.html"

    @app.get("/", include_in_schema=False)
    def _root() -> Response:
        return RedirectResponse(LOGIN_PATH, status_code=307)

    @app.get("/physicsai", include_in_schema=False)
    def _base() -> Response:
        return RedirectResponse("/physicsai/", status_code=308)

    @app.get("/physicsai/{path:path}", include_in_schema=False)
    def _static(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise DomainError("NOT_FOUND", "찾을 수 없습니다", status=404)
        if path:
            cand = (root / path).resolve()  # '..'·절대경로·다른 드라이브는 root 밖 → index.html
            if cand.is_relative_to(root) and cand.is_file():
                return FileResponse(cand)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
