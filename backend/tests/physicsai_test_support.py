"""시험 공용 fixture: 임시 PostgreSQL, 설정, 가짜 대시보드, 가짜 도구, 앱·워커.

PostgreSQL이 없으면 DB 시험은 실패한다(skip 금지, 계약 §18.2).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[2]
FAKE_TOOLS = Path(__file__).resolve().parent / "fake_tools"
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "worker"))


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _find_pg_bin() -> str | None:
    cand = os.environ.get("PG_BIN")
    if cand and os.path.isfile(os.path.join(cand, "initdb")):
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
        self.as_root = os.geteuid() == 0
        if self.as_root:
            shutil.chown(self.dir, user="postgres")
            os.chmod(self.dir, 0o700)
        data = os.path.join(self.dir, "data")
        self._run([f"{self.bin}/initdb", "-D", data, "-A", "trust", "-U", "postgres", "-E", "UTF8", "--no-sync"])
        self._run(
            [
                f"{self.bin}/pg_ctl", "-D", data, "-l", os.path.join(self.dir, "log"), "-w", "-o",
                f"-p {self.port} -k {self.dir} -c listen_addresses=127.0.0.1 -c fsync=off -c max_connections=200",
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


# ---------------------------------------------------------------------------
# 가짜 도구·설정
# ---------------------------------------------------------------------------


def _install_fake_tools(dest: Path) -> dict[str, str]:
    """fake_tools를 공백 없는 폴더로 복사하고 실행 권한을 준다."""
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for src in FAKE_TOOLS.iterdir():
        if src.is_file() and src.name.startswith("fake_"):
            dst = dest / src.name
            shutil.copyfile(src, dst)
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            out[src.name] = str(dst)
    return out


def make_settings_dict(base: Path, tools: dict[str, str], **overrides: Any) -> dict[str, Any]:
    ai_root = base / "ai_root"
    ai_root.mkdir(exist_ok=True)
    imports = base / "hpc_results"
    imports.mkdir(exist_ok=True)
    res = base / "resources"
    res.mkdir(exist_ok=True)
    tcl = res / "BATCHRUN_preview_pred_h3d.tcl"
    tcl.write_text("# fake tcl\n")
    d: dict[str, Any] = {
        "schema_version": 1,
        "profile": "dev",
        "server": {"host": "127.0.0.1", "port": 8100, "base_path": "/physicsai"},
        "auth": {"mode": "dashboard", "cache_ttl_s": 30, "timeout_s": 3},
        "storage": {"ai_root": str(ai_root), "allowed_import_roots": [str(imports)], "spdm_roots": [str(base / "spdm")]},
        "altair": {
            "version_label": "fake",
            "edspy_path": tools["fake_edspy"],
            "simlab_path": tools["fake_simlab"],
            "hw_exe_path": tools["fake_hw"],
            "hyperstudy_path": "",
            "hvtrans_exe_path": "",
        },
        "resources": {"preview_pred_h3d_tcl": str(tcl)},
        "worker": {
            "limiter": "posix",
            "max_logical_cores": 4,
            "max_memory_gb": 8,
            "heartbeat_interval_s": 0.3,
            "lease_ttl_s": 3,
            "claim_interval_s": 0.1,
            "cancel_check_interval_s": 0.2,
            "resource_sample_interval_s": 0.5,
            "state_dir": str(base / "state"),
            "gpu_query": [tools["fake_nvidia_smi"]],
            "env_passthrough": ["FAKE_*"],
        },
        "dataset": {"holdout_ratio": 0.1, "seed": 20261008, "split_group": "file", "min_h3d_files": 2, "min_psdata_bytes": 1048576},
        "training_log": {
            "log_globs": ["*.log", "*.txt"],
            "max_curve_points": 2000,
            "parsers": [{"name": "physicsai_default", "pattern": r"epoch=\s*(?P<epoch>\d+)\s*/\s*(?P<total>\d+)\s+loss=(?P<loss>[0-9.eE+\-]+)"}],
        },
        "score": {"write_files": False, "parsers": [{"name": "generic", "pattern": r"^\s*(?P<name>[A-Za-z][A-Za-z0-9_ ]{0,40}?)\s*[:=]\s*(?P<value>[-+0-9.eE]+)\s*$"}]},
        "commands": {
            "edspy_create_dataset": ["{edspy}", "--physicsai", "--create-dataset", "{out_psdata}", "--spec", "{spec_yaml}"],
            "edspy_score": ["{edspy}", "--physicsai", "--score", "{score_path}", "--model", "{model_psmdl}", "--dataset", "{eval_psdata}", "@write_files"],
            "geom_update": ["{simlab}", "-auto", "{rendered_script}", "-nographics"],
            "mesh": None,
            "rad_assemble": None,
            "edspy_predict": ["@cmd_c", "{edspy}", "--physicsai", "--predict-write", "{pred_h3d}", "--model", "{model_psmdl}", "--input-file", "{starter}", "@hooks_arg"],
            "contour_preview": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{preview_tcl}", "-input", "{pred_h3d_fwd}", "-output", "{preview_json_fwd}"],
            "response_extract": None,
        },
        "hpc": {"gateway": "none"},
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


@pytest.fixture()
def fake_tools(tmp_path):
    return _install_fake_tools(tmp_path / "tools")


@pytest.fixture()
def fake_record(tmp_path, monkeypatch):
    rec = tmp_path / "fake_record.jsonl"
    monkeypatch.setenv("FAKE_TOOL_RECORD", str(rec))
    monkeypatch.delenv("FAKE_TOOL_MODE", raising=False)
    monkeypatch.delenv("FAKE_TOOL_DELAY_S", raising=False)
    return rec


def read_record(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


@pytest.fixture()
def settings_dict(tmp_path, fake_tools):
    return make_settings_dict(tmp_path, fake_tools)


@pytest.fixture()
def loaded_config(settings_dict):
    from physicsai_core.config import load_config_dict

    lc = load_config_dict(settings_dict, environ={})
    assert lc.ok, lc.issues
    return lc


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


# ---------------------------------------------------------------------------
# 입력 폴더 생성 도우미
# ---------------------------------------------------------------------------


def make_h3d_tree(root: Path, n: int = 10, nested: bool = True) -> Path:
    inp = root / "00_inbox" / "h3d"
    for i in range(n):
        d = inp / f"run_{i:04d}" if nested else inp
        d.mkdir(parents=True, exist_ok=True)
        (d / f"result_{i:04d}.h3d").write_bytes(b"H3D" + bytes([i]))
    return inp


def make_model_folder(root: Path, name: str = "cushion_TNS", log: str | None = "default", extra_log: bool = False) -> Path:
    d = root / f"model_{uuid.uuid4().hex[:6]}"
    d.mkdir(parents=True)
    (d / f"{name}.psmdl").write_bytes(os.urandom(2048))
    (d / "settings.pscfg").write_bytes(b"\x80\x04pickle-not-opened")
    if log == "default":
        lines = [f"epoch= {e:3d}/  50  loss={100.0 / e:.5e}" for e in range(1, 51)]
        (d / "train.log").write_text("start\n" + "\n".join(lines) + "\nend\n")
    elif log == "garbage":
        (d / "train.log").write_text("no loss lines here\n")
    if extra_log:
        (d / "other.txt").write_text("x\n")
    return d


TPL_TEXT = """﻿{parameter(var_1, "THK_1", 3.0, 2.0, 5.0)}
{parameter(var_2, "N_RIB", 4, 2, 8)}
#***************************************************************
dir_file_prt = r"./bracket.x_t"
thickness = {var_1, %8.4f}
<paramitem Name="N_RIB" NewValue="{var_2, %3i}" Value="4"/>
"""


def make_param_set_folder(root: Path, *, with_samples: bool = True, with_responses: bool = True,
                          tpl: str = TPL_TEXT, starters: int = 1) -> Path:
    d = root / f"params_{uuid.uuid4().hex[:6]}"
    (d / "cad").mkdir(parents=True)
    (d / "cad" / "bracket.x_t").write_text("CAD")
    (d / "simlab_parametered_mesh.tpl").write_text(tpl, encoding="utf-8")
    (d / "radioss_assem").mkdir()
    for i in range(starters):
        (d / "radioss_assem" / f"model{i}_0000.rad").write_text("#include eps_mesh_1.inc\n")
    (d / "radioss_assem" / "model_0001.rad").write_text("engine\n")
    (d / "radioss_assem" / "eps_mesh_old.inc").write_text("old mesh\n")
    (d / "radioss_assem" / "material.inc").write_text("mat\n")
    (d / "parameters.json").write_text(json.dumps({
        "schema_version": 1, "unit_system": "mm-ton-s",
        "parameters": [
            {"name": "THK_1", "nominal": 3.0, "min": 2.0, "max": 5.0, "unit": "mm"},
            {"name": "N_RIB", "nominal": 4, "min": 2, "max": 8, "unit": ""},
        ],
    }))
    if with_responses:
        (d / "responses.json").write_text(json.dumps({"responses": [
            {"name": "MaxStress", "unit": "MPa", "spec": {"type": "max"}},
            {"name": "Disp", "unit": "mm", "spec": {}},
        ]}))
    if with_samples:
        rows = ["run_key,THK_1,N_RIB" + (",resp:MaxStress,resp:Disp" if with_responses else "")]
        for i, (t, n) in enumerate([(2.0, 2), (3.0, 4), (4.0, 6), (5.0, 8)]):
            rows.append(f"run_{i:04d},{t},{n}" + (f",{100 + i * 10},{1.5 + i}" if with_responses else ""))
        (d / "samples.csv").write_text("﻿" + "\n".join(rows) + "\n", encoding="utf-8")
    return d
