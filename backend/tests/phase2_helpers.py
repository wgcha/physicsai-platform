"""2차 시험 공용 도우미(API로 Study·DOE 준비)."""

from __future__ import annotations

import os
from pathlib import Path

from physicsai_test_support import API, H

PW, P = H("tok-power", write=True), H("tok-power")


def study(c, name):
    r = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def job(c, jid):
    return c.get(f"{API}/jobs/{jid}", headers=P).json()


def submit(c, sid, jt, params, expect=201):
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": jt, "params": params})
    assert r.status_code == expect, r.text
    return r.json()


def make_inputs(sroot: Path) -> tuple[Path, Path]:
    cad = sroot / "00_inbox" / "cad" / "cushion_parametric.prt"
    cad.parent.mkdir(parents=True)
    cad.write_bytes(b"PRT" * 100)
    assem = sroot / "00_inbox" / "radioss_assem"
    assem.mkdir(parents=True)
    (assem / "drop_0000.rad").write_text("#include eps_mesh_1.inc\n")
    (assem / "drop_0001.rad").write_text("/ENGINE\n")
    (assem / "eps_mesh_0000.rad").write_text("old mesh starter\n")
    (assem / "mat.inc").write_text("mat\n")
    (assem / "notes.txt").write_text("ignored\n")
    return cad, assem


def extract_and_tpl(c, w, sid, cad: Path) -> dict:
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert j["stage_label"] == "①-1"
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    rows = [{"name": p["name"], "min": p["min"], "max": p["max"], "use": p["use"], "format": p["format"]} for p in ts["parameters"]]
    r = c.put(f"{API}/studies/{sid}/train/params", headers=PW, json={"version": ts["version"], "parameters": rows})
    assert r.status_code == 200, r.text
    r = c.post(f"{API}/studies/{sid}/train/tpl", headers=PW, json={"version": r.json()["version"]})
    assert r.status_code == 200, r.text
    return r.json()


def doe_gen(c, w, sid, ai: Path, name: str, num_runs=3, expect="SUCCEEDED", **kw) -> dict:
    j = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LatinHyperCube", "num_runs": num_runs, "options": {"RANDOM_SEED": 7},
                                      "multi_execution": 2, "radioss_assem_path": str(ai / name / "00_inbox" / "radioss_assem"), **kw})
    assert w.run_once_slot() == expect, job(c, j["id"])
    return job(c, j["id"])


def _ready_doe(c, w, ai, name, num_runs=3) -> tuple[str, str]:
    sid = study(c, name)
    cad, _ = make_inputs(ai / name)
    extract_and_tpl(c, w, sid, cad)
    return sid, doe_gen(c, w, sid, ai, name, num_runs=num_runs)["result"]["doe_id"]


def _write_results(ai, name, doe_id, run_keys, base: Path | None = None):
    for rk in run_keys:
        R = (base or ai / name / "01_train" / "results" / doe_id) / rk
        R.mkdir(parents=True, exist_ok=True)
        (R / "drop_0000.out").write_text("out")
        (R / "drop_A001.h3d").write_bytes(b"H3D" + rk.encode())
        (R / "drop_T01").write_text("T01")
        (R / "ignore.tmp").write_text("x")
