"""대시보드 로그인 공유(계약 §5). 신원은 매 요청 대시보드 `/api/auth/me` introspection으로 확정한다.

- 토큰 원문은 로그·DB·응답에 남기지 않는다(캐시 키도 sha256).
- 인증 클라이언트는 httpx transport 주입형(시험은 가짜 대시보드 MockTransport).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from physicsai_core.config import AuthCfg
from physicsai_core.errors import DomainError

ROLES = ("general", "power", "admin")
CACHE_MAX = 1000


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    display_name: str
    is_global_admin: bool
    roles: dict[str, str] = field(default_factory=dict)

    def role(self, project_id: str) -> str | None:
        if self.is_global_admin:
            return "admin"
        return self.roles.get(project_id)

    def can_execute(self, project_id: str) -> bool:
        return self.role(project_id) in ("power", "admin")


def _err(status: int, code: str, message: str) -> DomainError:
    return DomainError(code, message, status=status)


def auth_required() -> DomainError:
    return _err(401, "AUTHENTICATION_REQUIRED", "대시보드에서 로그인하세요")


class DashboardClient:
    """대시보드 HTTP 호출(루프백 dashboard_internal_url만)."""

    def __init__(self, cfg: AuthCfg, transport: httpx.BaseTransport | None = None) -> None:
        self.cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.dashboard_internal_url.rstrip("/"),
            timeout=cfg.timeout_s,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, token: str, request_id: str) -> httpx.Response:
        try:
            return self._client.get(path, headers={"Authorization": f"Bearer {token}", "X-Request-Id": request_id})
        except httpx.HTTPError:
            raise _err(503, "DASHBOARD_UNREACHABLE", "대시보드에 연결할 수 없습니다") from None

    def me(self, token: str, request_id: str) -> dict[str, Any]:
        r = self._get(self.cfg.introspection_path, token, request_id)
        if r.status_code == 401:
            raise auth_required()
        if r.status_code == 403:
            raise _err(403, "ACCOUNT_NOT_ACTIVE", "대시보드 계정이 활성 상태가 아닙니다")
        if r.status_code == 503:
            raise _err(503, "DASHBOARD_AUTH_UNAVAILABLE", "대시보드 인증 설정이 완료되지 않았습니다")
        if r.status_code != 200:
            raise _err(503, "DASHBOARD_UNREACHABLE", f"대시보드 응답 오류({r.status_code})")
        try:
            data = r.json()
        except ValueError:
            raise _err(503, "DASHBOARD_UNREACHABLE", "대시보드 응답 형식 오류") from None
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise _err(503, "DASHBOARD_UNREACHABLE", "대시보드 응답 형식 오류")
        return data

    def projects(self, token: str, request_id: str) -> list[dict[str, Any]]:
        r = self._get(self.cfg.projects_path, token, request_id)
        if r.status_code == 401:
            raise auth_required()
        if r.status_code != 200:
            raise _err(503, "DASHBOARD_UNREACHABLE", f"대시보드 프로젝트 목록 오류({r.status_code})")
        try:
            data = r.json()
        except ValueError:
            raise _err(503, "DASHBOARD_UNREACHABLE", "대시보드 응답 형식 오류") from None
        if not isinstance(data, list):
            raise _err(503, "DASHBOARD_UNREACHABLE", "대시보드 응답 형식 오류")
        return [
            {"id": str(p.get("id")), "name": str(p.get("name") or ""), "product_name": p.get("product_name")}
            for p in data
            if isinstance(p, dict) and p.get("id") is not None
        ]


def principal_from_me(data: dict[str, Any]) -> Principal:
    roles: dict[str, str] = {}
    for m in data.get("memberships") or []:
        if isinstance(m, dict) and m.get("role") in ROLES and m.get("project_id") is not None:
            roles[str(m["project_id"])] = m["role"]
    return Principal(
        user_id=str(data["id"]),
        username=str(data.get("username") or data["id"]),
        display_name=str(data.get("display_name") or data.get("username") or data["id"]),
        is_global_admin=bool(data.get("is_global_admin")),
        roles=roles,
    )


class _TTLCache:
    def __init__(self, ttl: float, clock: Callable[[], float], maxsize: int = CACHE_MAX) -> None:
        self.ttl = ttl
        self.clock = clock
        self.maxsize = maxsize
        self._d: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            hit = self._d.get(key)
            if hit is None:
                return None
            if hit[0] <= self.clock():
                self._d.pop(key, None)
                return None
            self._d.move_to_end(key)
            return hit[1]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._d[key] = (self.clock() + self.ttl, value)
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)


def token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Authenticator:
    def __init__(
        self,
        cfg: AuthCfg,
        client: DashboardClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        dev_projects: list[dict[str, Any]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.mode = cfg.mode
        self.client = client
        self._me = _TTLCache(cfg.cache_ttl_s, clock)
        self._projects = _TTLCache(cfg.cache_ttl_s, clock)
        self._dev_projects = dev_projects

    def dev_principal(self) -> Principal:
        p = self.cfg.dev_static_principal
        return Principal(
            p.user_id, p.username, p.display_name, p.is_global_admin, {m.project_id: m.role for m in p.memberships}
        )

    def authenticate(self, token: str | None, request_id: str) -> Principal:
        if self.mode == "dev_static":
            return self.dev_principal()
        if not token:
            raise auth_required()
        key = token_key(token)
        cached = self._me.get(key)
        if cached is not None:
            return cached
        assert self.client is not None
        data = self.client.me(token, request_id)
        if data.get("account_status") != "ACTIVE":
            raise _err(403, "ACCOUNT_NOT_ACTIVE", "대시보드 계정이 활성 상태가 아닙니다(승인 대기 등)")
        principal = principal_from_me(data)
        self._me.put(key, principal)
        return principal

    def projects(self, principal: Principal, token: str | None, request_id: str) -> list[dict[str, Any]]:
        if self.mode == "dev_static":
            if self._dev_projects is not None:
                return self._dev_projects
            ids = sorted({*principal.roles.keys(), "dev"})
            return [{"id": i, "name": f"개발 프로젝트 {i}", "product_name": None} for i in ids]
        key = "u:" + principal.user_id
        cached = self._projects.get(key)
        if cached is not None:
            return cached
        assert self.client is not None and token
        data = self.client.projects(token, request_id)
        self._projects.put(key, data)
        return data
