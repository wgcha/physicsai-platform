"""시험 공용 PostgreSQL: 임시 클러스터(PG_BIN)·DB별 URL·alembic upgrade, fixture pg_server·db_url·engine."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from support_base import IS_WINDOWS, REPO

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _find_pg_bin() -> str | None:
    cand = os.environ.get("PG_BIN")
    if cand and (os.path.isfile(os.path.join(cand, "initdb")) or os.path.isfile(os.path.join(cand, "initdb.exe"))):
        return cand
    base = Path("/usr/lib/postgresql")
    if base.is_dir():
        for v in sorted(base.iterdir(), reverse=True):
            if (v / "bin" / "initdb").is_file():
                return str(v / "bin")
    w = shutil.which("initdb")
    return os.path.dirname(w) if w else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _TempCluster:
    def __init__(self) -> None:
        self.bin = _find_pg_bin()
        if not self.bin:
            pytest.fail("PostgreSQL을 찾을 수 없습니다(PG_BIN 또는 PHYSICSAI_TEST_DATABASE_URL 필요). DB 시험은 skip하지 않습니다")
        self.dir = tempfile.mkdtemp(prefix="physicsai-pg-")
        self.port = _free_port()
        self.as_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if self.as_root:
            shutil.chown(self.dir, user="postgres")
            os.chmod(self.dir, 0o700)
        data = os.path.join(self.dir, "data")
        self._run([f"{self.bin}/initdb", "-D", data, "-A", "trust", "-U", "postgres", "-E", "UTF8", "--no-sync"])
        self._run(
            [
                f"{self.bin}/pg_ctl", "-D", data, "-l", os.path.join(self.dir, "log"), "-w", "-o",
                f"-p {self.port} " + ("" if IS_WINDOWS else f"-k {self.dir} ")
                + "-c listen_addresses=127.0.0.1 -c fsync=off -c max_connections=200",
                "start",
            ]
        )
        self.data = data
        self.url = f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/postgres"

    def _run(self, argv: list[str]) -> None:
        if self.as_root:
            argv = ["runuser", "-u", "postgres", "--", *argv]
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode != 0:
            pytest.fail(f"PostgreSQL 임시 클러스터 실패: {' '.join(argv)}\n{r.stdout}\n{r.stderr}")

    def stop(self) -> None:
        try:
            self._run([f"{self.bin}/pg_ctl", "-D", self.data, "-m", "immediate", "stop"])
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


def _with_db(url: str, db: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{db}"


def run_alembic_upgrade(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def pg_server():
    ext = os.environ.get("PHYSICSAI_TEST_DATABASE_URL")
    cluster = None
    if ext:
        from physicsai_core.db.engine import normalize_url

        admin_url = _with_db(normalize_url(ext), "postgres")
    else:
        cluster = _TempCluster()
        admin_url = cluster.url
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    tpl = f"physicsai_tpl_{uuid.uuid4().hex[:8]}"
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{tpl}"'))
    run_alembic_upgrade(_with_db(admin_url, tpl))
    yield {"admin": admin, "admin_url": admin_url, "template": tpl}
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{tpl}" WITH (FORCE)'))
    admin.dispose()
    if cluster:
        cluster.stop()


@pytest.fixture()
def db_url(pg_server):
    name = f"physicsai_t_{uuid.uuid4().hex[:10]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{pg_server["template"]}"'))
    url = _with_db(pg_server["admin_url"], name)
    yield url
    with pg_server["admin"].connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture()
def engine(db_url):
    from physicsai_core.db.engine import make_engine

    eng = make_engine(db_url, pool_size=5)
    yield eng
    eng.dispose()
