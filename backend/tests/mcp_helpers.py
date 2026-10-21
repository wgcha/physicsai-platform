"""MCP 시험 공용(mcp.md §17): 설정 켜기·토큰 발급·시험용 작업 종류(가짜 heavy·light)·시계 이동."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from physicsai_test_support import API, H, make_model_folder


def enable(settings_dict: dict[str, Any], **mcp: Any) -> dict[str, Any]:
    settings_dict["mcp"] = {"enabled": True, **mcp}
    return settings_dict


def issue(client, session="tok-power", scope="run", name="llm", **kw) -> tuple[str, dict[str, Any]]:
    r = client.post(f"{API}/me/api-tokens", headers=H(session, write=True), json={"name": name, "scope": scope, **kw})
    assert r.status_code == 201, r.text
    return r.json()["token"], r.json()["api_token"]


def T(token: str) -> dict[str, str]:
    """토큰 요청 헤더(CSRF 헤더 없음 — 면제)."""
    return {"Authorization": f"Bearer {token}"}


def shift_clock(monkeypatch, **delta: float) -> None:
    from physicsai_api.mcp import clock

    real = clock.now.__wrapped__ if hasattr(clock.now, "__wrapped__") else clock.now

    def fake():
        return real() + timedelta(**delta)

    fake.__wrapped__ = real  # type: ignore[attr-defined]
    monkeypatch.setattr(clock, "now", fake)


def install_test_kinds(monkeypatch, import_root) -> dict[str, Any]:
    """시험용 종류: test_heavy(heavy)·test_light(light). 생성 = 기존 범용 작업 생성 서비스(MODEL_REGISTER, Study당 활성 1개)."""
    from pydantic import BaseModel, ConfigDict, Field

    from physicsai_api.mcp import job_kinds as jk

    class P(BaseModel):
        model_config = ConfigDict(extra="forbid")
        n: int = Field(default=1, ge=1, le=10, description="시험 값[개](1~10)")
        bad: bool = Field(default=False, description="문제 만들기")

    calls: dict[str, list[Any]] = {"plan": [], "create": []}

    def plan_fn(ctx, principal, study_id, p):
        calls["plan"].append((study_id, p.n))
        probs = [jk.problem("TEST_BAD", "문제", "bad")] if p.bad else []
        return {**jk.lane_info("MODEL_REGISTER"), "runs": p.n, "parallel": 1, "problems": probs, "warnings": []}

    def create_fn(ctx, principal, study_id, p, rid, ip):
        calls["create"].append((study_id, p.n))
        mf = make_model_folder(import_root)
        out = jk._svc("jobs").create_job(ctx, principal, study_id, "MODEL_REGISTER", {"model_path": str(mf)}, rid, ip)
        return out, out["id"], None

    kinds = dict(jk.JOB_KINDS)
    for name, cost in (("test_heavy", "heavy"), ("test_light", "light")):
        kinds[name] = jk.JobKind(name, 1, f"시험 {cost}", "③", ("MODEL_REGISTER",), cost, P, plan_fn, create_fn, "job", {"n": 1})
    monkeypatch.setattr(jk, "JOB_KINDS", kinds)
    monkeypatch.setitem(jk.KIND_OF_JOB_TYPE, "MODEL_REGISTER", "test_heavy")
    return calls


@pytest.fixture()
def import_root(tmp_path):
    p = tmp_path / "hpc_results"
    p.mkdir(exist_ok=True)
    return p
