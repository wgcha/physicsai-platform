"""① 시험 공용 fixture: 가짜 PBS 상태 파일(pbs_state), PBS command 게이트웨이 2차 환경(p2_pbs)."""

from __future__ import annotations

import pytest

from physicsai_test_support import _p2_env, pbs_command_cfg


@pytest.fixture()
def pbs_state(tmp_path, monkeypatch):
    p = tmp_path / "pbs_state.json"
    monkeypatch.setenv("FAKE_PBS_STATE", str(p))
    monkeypatch.delenv("FAKE_TOOL_MODE_PBS", raising=False)
    return p


@pytest.fixture()
def p2_pbs(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, pbs_state):
    ai = tmp_path / "ai_root"
    ai.mkdir(exist_ok=True)
    yield from _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {"hpc": pbs_command_cfg(fake_tools, str(ai))})
