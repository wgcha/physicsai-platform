"""rib-gap.md ①-1(V-RG-9): TD_EXTRACT_PARAMS 추출 조건 그룹 `rib_pitch` — params 정규화·options.json types·features `rib_rows`/`row`·train/features 응답·
train_setups.extract_filter·통계 요약, 모르는 그룹 422, RIB_PITCH 미선택은 기존과 같음. 가짜 paicad."""

from __future__ import annotations

import json

from helpers_native import make_project
from helpers_stage1 import job, study, submit
from physicsai_test_support import API, H

P = H("tok-power")
PW = H("tok-power", write=True)
FILTER = {"groups": ["position", "rib_pitch"], "conditions": {"position_min_size_mm": 3}, "draft_max_deg": None}


def _extract(c, w, sid, ai, name, **params):
    proj = make_project(ai / name / "00_inbox")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native", **params})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    return j, ai / name / "01_train" / "extract" / j["id"]


def test_extract_with_rib_pitch_group(p2_native):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "rp1")
    j, X = _extract(c, w, sid, ai, "rp1", extract_filter=FILTER)
    assert j["params"]["extract_filter"] == {"groups": ["position", "rib_pitch"], "conditions": {"position_min_size_mm": 3.0}, "draft_max_deg": None}
    opts = json.loads((X / "options.json").read_text(encoding="utf-8"))["extract"]["filter"]
    assert opts["types"] == ["HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V", "RIB_PITCH_U", "RIB_PITCH_V"] and opts["position_min_size_mm"] == 3.0
    feats = json.loads((X / "parameter_features.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in feats["rib_rows"]] == ["U1", "V1"]
    f = c.get(f"{API}/studies/{sid}/train/features", headers=P).json()
    assert f["filter"]["groups"] == ["position", "rib_pitch"] and [r["id"] for r in f["rib_rows"]] == ["U1", "V1"]
    pitch = [x for x in f["features"] if x["type"].startswith("RIB_PITCH")]
    assert [x["name"] for x in pitch] == ["B_RIB_PITCH_U_1", "B_RIB_PITCH_U_2", "B_RIB_PITCH_U_3", "B_RIB_PITCH_V_1", "B_RIB_PITCH_V_2"]
    assert pitch[1]["row"] == {"id": "U1", "k": 2, "n": 4} and (pitch[1]["min"], pitch[1]["max"]) == (15.0, 25.0)
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    assert ts["extract_filter"]["groups"] == ["position", "rib_pitch"]
    assert {p["name"] for p in ts["parameters"]} >= {"B_RIB_PITCH_U_1", "B_RIB_PITCH_V_2"}
    s = ts["extract_summary"]["types"]
    assert s["RIB_PITCH_U"]["kept"] == 3 and s["RIB_PITCH_V"]["kept"] == 2 and s["RIB_THICKNESS"]["selected"] is False
    log = (ai / "rp1" / "logs" / j["id"] / "step_02_SIMLAB_EXTRACT.log").read_text(encoding="utf-8")
    assert "리브 피치 U: 후보 3 · 채택 3 · 제외 0" in log


def test_rib_pitch_not_selected_and_unknown_group(p2_native):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "rp2")
    j, X = _extract(c, w, sid, ai, "rp2", extract_filter={"groups": ["thickness", "position"], "conditions": {}, "draft_max_deg": None})
    assert "rib_rows" not in json.loads((X / "parameter_features.json").read_text(encoding="utf-8"))
    assert c.get(f"{API}/studies/{sid}/train/features", headers=P).json()["rib_rows"] is None
    sid2 = study(c, "rp3")
    proj = make_project(ai / "rp3" / "00_inbox")
    r = c.post(f"{API}/studies/{sid2}/jobs", headers=PW, json={"job_type": "TD_EXTRACT_PARAMS", "params": {
        "cad_path": str(proj / "bracket.step"), "engine": "native", "extract_filter": {"groups": ["rib_gap"], "conditions": {}}}})
    assert r.status_code == 422, r.text
