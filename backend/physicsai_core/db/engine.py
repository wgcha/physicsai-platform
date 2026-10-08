"""DB 엔진. PostgreSQL 전용(psycopg 3)."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def normalize_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def database_url(url_env: str = "PHYSICSAI_DATABASE_URL") -> str:
    url = os.environ.get(url_env, "")
    if not url:
        raise RuntimeError(f"DB 접속 정보가 없습니다: 환경변수 {url_env}를 설정하세요")
    return normalize_url(url)


def make_engine(url: str, pool_size: int = 5) -> Engine:
    url = normalize_url(url)
    if not url.startswith("postgresql"):
        raise RuntimeError("PhysicsAI는 PostgreSQL만 지원합니다")
    return create_engine(url, pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True, future=True)
