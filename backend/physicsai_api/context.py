"""앱 문맥: 설정·DB 엔진·인증기·HPC 게이트웨이(availability만)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.engine import Engine

from physicsai_core.config import LoadedConfig, Settings
from physicsai_core.hpc.gateway import HpcJobGateway, get_hpc_gateway

from .auth import Authenticator, DashboardClient


@dataclass
class AppContext:
    config: LoadedConfig
    engine: Engine
    auth: Authenticator
    hpc: HpcJobGateway

    @property
    def settings(self) -> Settings:
        return self.config.settings


def build_context(
    config: LoadedConfig,
    engine: Engine,
    *,
    transport: httpx.BaseTransport | None = None,
    clock: Any = None,
) -> AppContext:
    s = config.settings
    if s.auth.mode == "demo":
        # 시연 모드: 실제 대시보드 경로를 그대로 쓰고 전송 계층만 내장 가짜(허용 여부는 create_app의 기동 검사가 막는다)
        from .demo import demo_transport

        transport = demo_transport()
    client = DashboardClient(s.auth, transport=transport) if s.auth.mode in ("dashboard", "demo") else None
    kwargs = {"clock": clock} if clock is not None else {}
    auth = Authenticator(s.auth, client, **kwargs)
    return AppContext(config, engine, auth, get_hpc_gateway(s))
