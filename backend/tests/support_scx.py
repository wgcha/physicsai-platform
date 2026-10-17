"""SCX relay 시험 지원(phase3 §16.12): 가짜 relay(packages/simdash_adapters/tests/fake_scx_relay.py)를 backend·worker 시험에서 재사용."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from support_base import REPO

FAKE_RELAY_PATH = REPO / "packages" / "simdash_adapters" / "tests" / "fake_scx_relay.py"
_MOD = "simdash_fake_scx_relay"


def fake_relay_module() -> Any:
    if _MOD in sys.modules:
        return sys.modules[_MOD]
    spec = importlib.util.spec_from_file_location(_MOD, FAKE_RELAY_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def fake_relay(tmp_path):
    """127.0.0.1 임의 포트의 가짜 relay. 드라이브 = tmp_path/scx_drive. 기본 묶음 진행은 바로 DONE(시험 시간 단축)."""
    f = fake_relay_module().FakeRelay(tmp_path / "scx_drive").start()
    f.batch_steps = ["DONE"]
    try:
        yield f
    finally:
        f.stop()


def scx_hpc_cfg(fake: Any, tmp_path: Path, **scx_over: Any) -> dict[str, Any]:
    """`hpc` 절(gateway=scx). 비밀 파일은 tmp_path/runtime/secrets/scx_relay_key(절대경로)."""
    sec = fake.write_secret(tmp_path / "runtime" / "secrets" / "scx_relay_key")
    m = fake.config_mapping(str(sec))
    m.update(scx_over)
    return {"gateway": "scx", "lost_after_polls": 2, "scx": m}


@pytest.fixture()
def p2_scx(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, fake_relay):
    """2차 환경 + hpc.gateway=scx(가짜 relay). (client, mk_worker, ai_root, loaded_config, settings_dict, fake_relay)."""
    from support_resources import _p2_env

    ai = tmp_path / "ai_root"
    ai.mkdir(exist_ok=True)
    for item in _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {"hpc": scx_hpc_cfg(fake_relay, tmp_path)}):
        yield (*item, fake_relay)
