"""opt-native V-ON-11(흐름, 가짜 paicad·hw·edspy): 확정 위상 변형 세트 → `baseline` 범주 변수·levels·problems(LEVELS_INVALID·
TOO_MANY_LEVELS)·N/A, 탐색 = 층화 LHS(배정 메타), `ga` 검증 배치의 baseline 열 → run values.json `baseline_id`, DONE.
범위 분할 세트 → baseline 변수 없음·배정 spec 저장."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from helpers_native import native_set
from physicsai_test_support import API, H

from .test_native_multi import B2_TOPO, _add, _confirm, _feat, _map, _put

pytest.importorskip("numpy")
pytest.importorskip("scipy")

PW = H("tok-power", write=True)
P = H("tok-power")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RESP = [{"name": "MaxStress", "unit": "MPa",
         "spec": {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}},
        {"name": "Disp", "unit": "mm", "spec": None}]


@pytest.fixture()
def mb_env(native_env, settings_dict, tmp_path, monkeypatch):
    from physicsai_core.stage4_predict import run_metrics

    settings_dict["surrogate_opt"] = {"max_levels": 2}
    tcl = tmp_path / "res" / "H3D_StaticMinMax_to_CSV_FAST.tcl"
    tcl.parent.mkdir(parents=True)
    tcl.write_text("# fake\n")
    env = native_env(commands={"response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]},
                     resources={"extract_minmax_tcl": str(tcl)})
    orig = run_metrics.load_run_metrics

    def load(files: Any, *, max_bytes: int) -> Any:
        m = orig(files, max_bytes=max_bytes)
        if m.resp is None or not files.result_dir:
            return m
        jid = UUID_RE.findall(files.result_dir.replace("\\", "/"))[-1]
        row = env.sql("select applied_values from predict_batch_runs where predict_job_id=:i", i=jid)
        v = row[0][0] if row else {}
        f = 100.0 + (float(v.get("A_THK_1", 10)) - 10.1) ** 2 + 0.5 * float(v.get("D_POCKET_D_1", 0) or 0)
        return run_metrics.RunMetrics(curve=m.curve, resp={**m.resp, "MaxStress_MAX": f})

    monkeypatch.setattr(run_metrics, "load_run_metrics", load)
    return env


def _drain(env: Any, limit: int = 150) -> list[tuple[str, str | None]]:
    seen = []
    for _ in range(limit):
        q = env.sql("select id, job_type from jobs where state='QUEUED' and lane in ('CPU','GPU') order by queue_seq limit 1")
        if not q:
            return seen
        seen.append((q[0][1], env.w.run_once_slot()))
    raise AssertionError("대기열이 끝나지 않았습니다")


def test_v_on_11_topology_categorical_flow(mb_env, monkeypatch):
    env = mb_env
    ps = native_set(env)
    _add(env, ps["id"], "B2", B2_TOPO, monkeypatch)
    _add(env, ps["id"], "B3", B2_TOPO, monkeypatch)
    body = {"param_set_id": ps["id"], "explore": {"kind": "new", "count": 8, "seed": 1},
            "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"}, "iterations": 1, "candidates": 2, "tol_rel": 1e-9,
            "seed": 1, "multi_execution": 2, "algorithm": "ga", "algo_options": {"generations": 20}}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=body)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PARAM_MAP_UNCONFIRMED", r.text  # 미확정 409 유지
    pm = _map(env, ps["id"])
    _put(env, ps["id"], [{"row_id": x["row_id"], "decision": {"action": "accept"}} for x in pm["common"]])
    _confirm(env, ps["id"])
    env.set_responses(ps["id"], RESP)

    def preview(**kw: Any) -> dict[str, Any]:
        rr = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json={**body, **kw})
        assert rr.status_code == 200, rr.text
        return rr.json()

    assert [p["code"] for p in preview()["problems"]] == ["TOO_MANY_LEVELS"]  # 3 > max_levels 2
    assert [p["code"] for p in preview(levels={"baseline": ["base", "ZZ"]})["problems"]] == ["LEVELS_INVALID"]
    assert [p["code"] for p in preview(levels={"baseline": []})["problems"]] == ["LEVELS_INVALID"]
    assert [p["code"] for p in preview(levels={"thk": ["base"]})["problems"]] == ["LEVELS_INVALID"]
    pv = preview(levels={"baseline": ["base", "B2"]})
    assert pv["problems"] == [] and pv["variables_kind"]["baseline"] == "categorical" and "baseline" in pv["free_variables"]
    assert pv["levels"] == {"baseline": ["base", "B2"]}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json={**body, "levels": {"baseline": ["base", "B2"]}})
    assert r.status_code == 201, r.text
    st = r.json()["settings"]
    mb = st["multi_baseline"]
    assert mb["usage"] == "topology" and st["levels"] == {"baseline": ["base", "B2"]} and st["bounds"]["baseline"] == [0.0, 1.0]
    assert mb["active"]["D_POCKET_D_1"] == [False, True] and mb["active"]["C_HOLE_R_1"] == [True, False]
    assert mb["na"] == [n for n in ("C_HOLE_R_1", "D_POCKET_D_1") if n in mb["na"]] and set(mb["na"]) == {"C_HOLE_R_1", "D_POCKET_D_1"}
    seen = _drain(env)
    assert all(s == "SUCCEEDED" for _, s in seen), seen
    d = env.c.get(f"{API}/surrogate-opts/{r.json()['id']}", headers=P).json()
    assert d["status"] == "DONE", d["progress_text"]
    exp = env.batch(d["iterations"][0]["batch"]["id"])
    meta = exp["source_meta"]["multi_baseline"]
    assert set(meta["assign"].values()) == {"base", "B2"} and exp["source_kind"] == "LHS"  # 층화 LHS(선택 수준만)
    assert {r_["values"]["baseline"] for r_ in d["runs"] if r_["iter_no"] == 0} == {0.0, 1.0}
    it = next(x for x in d["iterations"] if x["kind"] == "VERIFY")
    cands = it["candidates"]
    assert cands and all(c["baseline"] in ("base", "B2") and c["values"]["baseline"] in (0.0, 1.0) for c in cands)
    for c in cands:  # N/A 변수 = 0
        if c["baseline"] == "base":
            assert c["values"]["D_POCKET_D_1"] == 0.0
        else:
            assert c["values"]["C_HOLE_R_1"] == 0.0
    vb = env.batch(it["batch"]["id"])
    vmeta = vb["source_meta"]["multi_baseline"]
    assert [vmeta["assign"][str(c["doe_no"])] for c in cands] == [c["baseline"] for c in cands]
    for c in cands:
        run = next(x for x in vb["runs"] if x["doe_no"] == c["doe_no"])
        v = json.loads((env.sroot / vb["dir_rel"] / run["run_key"] / "m_1" / "values.json").read_text())
        assert v["baseline_id"] == c["baseline"]
    assert d["final"]["status"] == "SKIPPED"


def test_v_on_11_range_split_settings(mb_env, monkeypatch):
    env = mb_env
    ps = native_set(env)
    b2 = [_feat("A_THK_1", "THICKNESS", 15.0, 14.25, 15.75, feasible=(14.5, 15.5)),
          _feat("B_RIB_H_1", "RIB_HEIGHT", 20.0, 19.0, 21.0), _feat("C_HOLE_R_1", "HOLE_RADIUS", 4.0, 3.8, 4.2)]
    _add(env, ps["id"], "B2", b2, monkeypatch, usage="range", split_param="A_THK_1")
    _confirm(env, ps["id"])
    env.set_responses(ps["id"], RESP)
    body = {"param_set_id": ps["id"], "explore": {"kind": "new", "count": 8, "seed": 1},
            "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"}, "iterations": 1, "candidates": 2, "seed": 1}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=body)
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert "baseline" not in r.json()["variables_kind"] and r.json()["levels"] is None
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json={**body, "levels": {"baseline": ["base"]}})
    assert [p["code"] for p in r.json()["problems"]] == ["LEVELS_INVALID"]  # 범위 분할 세트는 levels 없음
