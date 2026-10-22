"""v0.2.9 3차 통합: DOE 표본 방식(doe-methods.md DM-C2) × 조립 매칭(asm-match.md §6.4) 조합 — ①-3 Native에서 sobol·halton·random·ccd 표본이
asm_match_id(방식 M, RENUM·기준본 없음)와 함께 만들어지고, 같은 seed는 같은 표, 조립 사본에는 노드 좌표 패치만 반영된다. 가짜 paicad."""

from __future__ import annotations

import json

from pathlib import Path

import pytest
from helpers_asm import STARTER, _confirmed, make_tree
from helpers_native import make_project
from helpers_stage1 import job, study, submit
from physicsai_test_support import API, H, MESH_INC

PW = H("tok-power", write=True)


def _project(ai: Path, name: str):
    proj = make_project(ai / name / "00_inbox", include_base=False, renum_csv=False)
    return proj, make_tree(proj / "asm")


def _extract(c, w, sid, proj: Path) -> None:
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])


def _doe(c, w, sid, asm, mid, sampling):
    params = {"doe_label": "m", "multi_execution": 2, "radioss_assem_path": str(asm), "asm_match_id": mid, "sampling": sampling}
    j = submit(c, sid, "TD_DOE_GEN", params)
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    return job(c, j["id"])


@pytest.mark.parametrize("kind,inp,runs", [("sobol", {"count": 8, "seed": 4}, 8), ("halton", {"count": 7, "seed": 5}, 7),
                                           ("random", {"count": 5, "seed": 6}, 5), ("ccd", {"alpha": "inscribed"}, None)])
def test_doe_method_with_asm_match(p2_native, fake_record, kind, inp, runs):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, f"amdm_{kind}")
    proj, asm = _project(ai, f"amdm_{kind}")
    _extract(c, w, sid, proj)
    mid = _confirmed(c, w, sid, asm)
    jd = _doe(c, w, sid, asm, mid, {"kind": kind, **inp})
    p, res = jd["params"], jd["result"]
    assert p["asm_match_id"] == mid and p["sampling"]["kind"] == kind and len(p["asm_match_sha256"]) == 64
    D = ai / f"amdm_{kind}" / "01_train" / "doe" / res["doe_id"]
    rows = (D / "doe_matrix.csv").read_text(encoding="utf-8").strip().splitlines()[1:]
    assert res["run_count"] == len(rows) > 0 and (runs is None or len(rows) == runs)
    prep = json.loads((D / "native" / "prep.json").read_text())
    assert prep["inputs"]["asm_match"]["rel"] == "cad/asm_match.json" and prep["inputs"]["baseline_inc"] is None and prep["inputs"]["renum_csv"] is None
    run_dirs = sorted((D / "approaches" / "doe_1").iterdir())
    assert len(run_dirs) == len(rows)
    for run in run_dirs:
        assert (run / STARTER).is_file() and "#FAKE_PATCH" in (run / STARTER).read_text() and not (run / MESH_INC).exists()
    d = c.get(f"{API}/train-does/{res['doe_id']}", headers=H("tok-power")).json()
    assert d["sampling"]["kind"] == kind
    # 같은 방식·seed로 다시 만들면 같은 표(결정성은 조립 매칭 유무와 무관)
    if kind != "ccd":
        jd2 = _doe(c, w, sid, asm, mid, {"kind": kind, **inp})
        D2 = ai / f"amdm_{kind}" / "01_train" / "doe" / jd2["result"]["doe_id"]
        assert (D2 / "doe_matrix.csv").read_text(encoding="utf-8") == (D / "doe_matrix.csv").read_text(encoding="utf-8")
