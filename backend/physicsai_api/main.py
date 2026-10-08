"""FastAPI 앱(§10). 모든 라우트는 `/physicsai/api` 접두.

운영·개발 실행: `uvicorn physicsai_api.main:app --host 127.0.0.1 --port 8100`
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from physicsai_core import __version__
from physicsai_core.config import LoadedConfig, load_config
from physicsai_core.errors import DomainError

from .context import AppContext, build_context
from .routers import (
    admin,
    artifacts,
    curations,
    datasets,
    env_checks,
    jobs,
    models,
    notifications,
    optimize,
    param_sets,
    queue,
    spdm,
    status,
    studies,
    train,
)

log = logging.getLogger("physicsai_api")
API_PREFIX = "/physicsai/api"


class StartupRefused(RuntimeError):
    """기동 거부(CONFIG_INVALID)."""


def check_startup(config: LoadedConfig, bind_host: str | None = None) -> None:
    """V-AUTH-5: dev_static은 profile=dev이고 127.0.0.1 바인딩일 때만."""
    s = config.settings
    host = bind_host or s.server.host
    if s.auth.mode == "dev_static" and (s.profile != "dev" or host != "127.0.0.1"):
        raise StartupRefused("CONFIG_INVALID: auth.mode=dev_static은 profile=dev이고 127.0.0.1 바인딩일 때만 허용됩니다")
    from .demo import demo_problem

    problem = demo_problem(s, host)
    if problem:
        raise StartupRefused(f"CONFIG_INVALID: {problem}")


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message, **extra}})


def create_app(ctx: AppContext, *, bind_host: str | None = None) -> FastAPI:
    check_startup(ctx.config, bind_host)
    app = FastAPI(
        title="PhysicsAI Platform API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.ctx = ctx
    from physicsai_core.paths import register_protected_roots

    register_protected_roots(ctx.settings.storage.spdm_roots)  # SPDM 쓰기 차단(phase2 §13.3)

    @app.exception_handler(DomainError)
    async def _domain(_req: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail()})

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": str(e.get("msg", ""))} for e in exc.errors()]
        return _error(422, "INVALID_PARAMS", "요청 값이 올바르지 않습니다", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error(404, "NOT_FOUND", "찾을 수 없습니다")
        if exc.status_code == 405:
            return _error(405, "METHOD_NOT_ALLOWED", "허용되지 않는 메서드입니다")
        return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def _internal(_req: Request, exc: Exception) -> JSONResponse:
        log.exception("처리되지 않은 오류")
        return _error(500, "INTERNAL_ERROR", "서버 내부 오류가 발생했습니다")

    for r in (status, queue, studies, datasets, models, param_sets, jobs, artifacts, notifications, admin, env_checks, train,
              curations, spdm, optimize):
        app.include_router(r.router, prefix=API_PREFIX)
    if ctx.settings.demo.enabled:  # 시연 모드(check_startup이 dev·127.0.0.1을 보장)
        from . import demo

        if ctx.settings.auth.mode == "demo":
            app.include_router(demo.build_router(ctx.settings), prefix=API_PREFIX)
        if ctx.settings.demo.frontend_root:
            demo.mount_frontend(app, ctx.settings.demo.frontend_root)
    return app


def _app_from_env() -> FastAPI:
    from physicsai_core.db.engine import make_engine

    config = load_config()
    if not config.ok:
        log.warning("설정 검증 실패: %s — 조회만 동작, 쓰기 API는 503", config.error_keys())
    url = os.environ.get(config.settings.database.url_env, "")
    if not url:
        raise StartupRefused(f"DB 접속 정보가 없습니다: 환경변수 {config.settings.database.url_env}")
    engine = make_engine(url, config.settings.database.pool_size)
    return create_app(build_context(config, engine), bind_host=os.environ.get("PHYSICSAI_BIND_HOST"))


def __getattr__(name: str):  # 지연 생성: `uvicorn physicsai_api.main:app`
    if name == "app":
        global app
        app = _app_from_env()
        return app
    raise AttributeError(name)
