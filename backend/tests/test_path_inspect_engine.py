"""CAD_FILE 경로 확인의 엔진별 확장자 검사(v0.2.1 핫픽스, geometry-engine.md 변경 메모 2026-10-21)."""

from __future__ import annotations

from helpers_stage1 import make_inputs, study
from physicsai_test_support import API, H

PW = H("tok-power", write=True)


def _inspect(c, sid, path, **extra):
    return c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "CAD_FILE", "path": str(path), **extra})


def test_cad_file_inspect_by_engine(p2_env):
    c, mk, ai, lc, d = p2_env
    sid = study(c, "ie1")
    prt, _assem = make_inputs(ai / "ie1")
    step = prt.with_name("bracket.step")
    step.write_text("ISO-10303-21;")
    # native + .step -> ok
    r = _inspect(c, sid, step, engine="native").json()
    assert r["ok"] and r["problems"] == [] and r["summary"]["extension_ok"] is True
    # native + .prt -> STEP 확장자 문제
    r = _inspect(c, sid, prt, engine="native").json()
    assert not r["ok"] and r["summary"]["extension_ok"] is False
    assert r["problems"][0]["code"] == "STEP_EXTENSION" and r["problems"][0]["message"].startswith("STEP 확장자는 .step, .stp")
    # engine 생략·altair = 기존 동작(.prt만)
    for extra in ({}, {"engine": "altair"}):
        assert _inspect(c, sid, prt, **extra).json()["ok"]
        r = _inspect(c, sid, step, **extra).json()
        assert not r["ok"] and r["problems"][0]["code"] == "CAD_EXTENSION"
    # 잘못된 engine 값은 422
    assert _inspect(c, sid, step, engine="x").status_code == 422
