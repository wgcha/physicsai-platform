"""시험 공용 가짜 대시보드(§5.5)·앱 클라이언트·워커 fixture, 인증 헤더 H·API 접두, wait_for."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# 가짜 대시보드(§5.5)
# ---------------------------------------------------------------------------

USERS: dict[str, dict[str, Any]] = {
    "tok-admin": {"id": "u-admin", "username": "admin", "display_name": "관리자", "account_status": "ACTIVE",
                  "is_global_admin": True, "memberships": []},
    "tok-power": {"id": "u-power", "username": "power", "display_name": "파워", "account_status": "ACTIVE",
                  "is_global_admin": False, "memberships": [{"project_id": "p-1", "role": "power"}]},
    "tok-power2": {"id": "u-power2", "username": "power2", "display_name": "파워2", "account_status": "ACTIVE",
                   "is_global_admin": False, "memberships": [{"project_id": "p-1", "role": "power"}]},
    "tok-general": {"id": "u-general", "username": "general", "display_name": "일반", "account_status": "ACTIVE",
                    "is_global_admin": False, "memberships": [{"project_id": "p-1", "role": "general"}]},
    "tok-nonmember": {"id": "u-non", "username": "non", "display_name": "비멤버", "account_status": "ACTIVE",
                      "is_global_admin": False, "memberships": [{"project_id": "p-2", "role": "power"}, {"project_id": "p-1", "role": "owner"}]},
    "tok-pending": {"id": "u-pend", "username": "pend", "display_name": "대기", "account_status": "PENDING",
                    "is_global_admin": False, "memberships": []},
}
PROJECTS = [
    {"id": "p-1", "name": "쿠션", "product_name": "Phone", "description": "x", "created_at": "2026-01-01", "selection_metadata": {}},
    {"id": "p-2", "name": "브래킷", "product_name": "TV", "description": "y", "created_at": "2026-01-01", "selection_metadata": {}},
]


class FakeDashboard:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.mode: str = "ok"  # ok | 503 | timeout | badjson | 500

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if self.mode == "503":
            return httpx.Response(503, json={"detail": {"code": "AUTH_SETUP_REQUIRED"}})
        if self.mode == "500":
            return httpx.Response(500, json={})
        if self.mode == "badjson":
            return httpx.Response(200, content=b"<html>")
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        if token == "tok-suspended":
            return httpx.Response(403, json={"detail": {"code": "AUTH_ACCOUNT_SUSPENDED"}})
        user = USERS.get(token)
        if user is None:
            return httpx.Response(401, json={"detail": "인증 필요"})
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json={**user, "employee_id": None, "company_permissions": [], "role": None})
        if request.url.path == "/api/projects":
            return httpx.Response(200, json=PROJECTS)
        return httpx.Response(404, json={})

    def me_calls(self) -> int:
        return sum(1 for c in self.calls if c.url.path == "/api/auth/me")


@pytest.fixture()
def fake_dashboard():
    return FakeDashboard()


@pytest.fixture()
def app_ctx(engine, loaded_config, fake_dashboard):
    from physicsai_api.context import build_context

    return build_context(loaded_config, engine, transport=httpx.MockTransport(fake_dashboard.handler))


@pytest.fixture()
def client(app_ctx):
    from fastapi.testclient import TestClient

    from physicsai_api.main import create_app

    app = create_app(app_ctx)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def H(token: str, write: bool = False) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if write:
        h["X-PhysicsAI-Request"] = "1"
    return h


API = "/physicsai/api"


# ---------------------------------------------------------------------------
# 워커
# ---------------------------------------------------------------------------


@pytest.fixture()
def worker_factory(engine, loaded_config):
    from physicsai_worker.runtime import Worker

    made: list[Any] = []

    def make(**kw: Any) -> Any:
        w = Worker(loaded_config, engine, **kw)
        made.append(w)
        return w

    yield make
    for w in made:
        w.stop()


def wait_for(pred, timeout: float = 20.0, interval: float = 0.05) -> Any:
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    raise AssertionError("시간 내 조건 충족 실패")
