"""opt-native V-ON-12 e2e(가짜 도구, V-ON-2 설정 = HyperStudy 미설정): ① 플랫폼 DOE(altair 가짜 SimLab)·native DOE(가짜 paicad)
→ ③ 데이터셋(가짜 edspy)·모델 등록 → ④ 예측(⑥ 탐색·검증 배치의 하위 PREDICT) → ⑤ 배치 결과 표 → ⑥ `ga` 단일(mesh_only)·
`none` 1회·`nsga2` 2목적(native 세트)이 DONE. 실행 argv 기록에 hstbatch·hstpy가 0건.

가짜 hw의 RESPONSES 값은 run마다 같으므로 `run_metrics.load_run_metrics`를 감싸 MaxStress_MAX·Disp_MAX를 그 run 입력값의 함수로
바꾼다(test_surrogate_flow와 같은 방식).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from helpers_native import make_project, native_set
from helpers_stage1 import extract_and_tpl, job, make_inputs, study, submit
from physicsai_test_support import API, LAUNCHERS, H, _p2_env, make_h3d_tree, make_model_folder, read_record

pytest.importorskip("numpy")
pytest.importorskip("scipy")

_spec = importlib.util.spec_from_file_location("_s4_predict_conftest_on_e2e", Path(__file__).parents[1] / "stage4_predict" / "conftest.py")
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules[_spec.name] = _mod  # type: ignore[union-attr]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
PredictEnv = _mod.PredictEnv

PW, P = H("tok-power", write=True), H("tok-power")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RESP = [{"name": "MaxStress", "unit": "MPa",
         "spec": {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}},
        {"name": "Disp", "unit": "mm", "spec": None}]


def _f(vals: dict[str, float], k: int) -> float:
    xs = [float(vals[n]) for n in sorted(vals) if isinstance(vals.get(n), (int, float))][:2]
    c = (0.3, 0.7) if k == 1 else (0.8, 0.2)
    return 100.0 + sum((x - ci * (1 + abs(x))) ** 2 for x, ci in zip(xs, c))


@pytest.fixture()
def on_e2e(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, fake_record):
    ai = tmp_path / "ai_root"
    ai.mkdir(exist_ok=True)
    over = {
        "altair": {"hyperstudy_path": "", "hstpy_path": "", "altair_home": ""},
        "commands": {"hst_gen_radioss": None, "hst_optimization": None,
                     "response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]},
        "resources": {"launchers": {"extract_params": {"script": LAUNCHERS["extract_params"][0], "core": LAUNCHERS["extract_params"][1]}}},
        "geometry": {"engine": "altair", "paicad_path": fake_tools["fake_paicad"]},
    }
    yield from _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, over)


def _drain(c: Any, w: Any, env: Any, limit: int = 150) -> list[tuple[str, str | None]]:
    seen = []
    for _ in range(limit):
        q = env.sql("select id, job_type from jobs where state='QUEUED' and lane in ('CPU','GPU') order by queue_seq limit 1")
        if not q:
            return seen
        seen.append((q[0][1], w.run_once_slot()))
    raise AssertionError("대기열이 끝나지 않았습니다")


def test_v_on_12_full_chain_without_hyperstudy(on_e2e, engine, fake_record, monkeypatch):
    from physicsai_core.stage4_predict import run_metrics

    c, mk, ai, lc, _d = on_e2e
    w = mk()
    st = c.get(f"{API}/status", headers=P).json()["features"]
    assert {k for k, v in st.items() if not v["enabled"]} >= {"train_doe", "optimize"}
    assert st["train_doe"]["legacy"] and st["optimize"]["legacy"]
    for k in ("train_extract", "train_doe_platform", "dataset_create", "predict", "predict_mesh_only", "predict_responses",
              "optimize_builtin", "geometry_native"):
        assert st[k]["enabled"], (k, st[k])

    # ① 플랫폼 DOE(altair 가짜 SimLab)
    sid = study(c, "on1")
    cad, _ = make_inputs(ai / "on1")
    extract_and_tpl(c, w, sid, cad)
    j = submit(c, sid, "TD_DOE_GEN", {"sampling": {"kind": "lhs_opt", "count": 3, "seed": 1}, "multi_execution": 2,
                                      "radioss_assem_path": str(ai / "on1" / "00_inbox" / "radioss_assem")})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    assert job(c, j["id"])["params"].get("generator", "platform") == "platform"
    # ① native DOE(가짜 paicad)
    sid2 = study(c, "on2")
    proj = make_project(ai / "on2" / "00_inbox")
    jx = submit(c, sid2, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, jx["id"])
    jd = submit(c, sid2, "TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 3, "seed": 7, "multi_execution": 2,
                                         "radioss_assem_path": str(proj / "assem")})
    assert w.run_once_slot() == "SUCCEEDED", job(c, jd["id"])

    # ③ 데이터셋 + 모델 등록·Final
    sroot = ai / "on1"
    inp = make_h3d_tree(sroot, n=4)
    jds = submit(c, sid, "DATASET_CREATE", {"input_path": str(inp)})
    assert w.run_once_slot() == "SUCCEEDED", job(c, jds["id"])
    mf = make_model_folder(sroot / "00_inbox", name="M1")
    jm = submit(c, sid, "MODEL_REGISTER", {"model_path": str(mf)})
    assert w.run_once_light() == "SUCCEEDED"
    model_id = job(c, jm["id"])["result"]["model_id"]
    assert c.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": model_id}).status_code == 200

    env = PredictEnv(c, w, lc, sid=sid, sroot=sroot, model_id=model_id, engine=engine)
    orig = run_metrics.load_run_metrics

    def load(files: Any, *, max_bytes: int) -> Any:
        m = orig(files, max_bytes=max_bytes)
        if m.resp is None or not files.result_dir:
            return m
        jid = UUID_RE.findall(files.result_dir.replace("\\", "/"))[-1]
        row = env.sql("select applied_values from predict_batch_runs where predict_job_id=:i", i=jid)
        vals = row[0][0] if row else {}
        return run_metrics.RunMetrics(curve=m.curve, resp={**m.resp, "MaxStress_MAX": _f(vals, 1), "Disp_MAX": _f(vals, 2)})

    monkeypatch.setattr(run_metrics, "load_run_metrics", load)

    def opt(body: dict[str, Any]) -> dict[str, Any]:
        r = c.post(f"{API}/studies/{sid}/surrogate-opts", headers=PW, json=body)
        assert r.status_code == 201, r.text
        seen = _drain(c, w, env)
        assert all(s == "SUCCEEDED" for _, s in seen), seen
        d = c.get(f"{API}/surrogate-opts/{r.json()['id']}", headers=P).json()
        assert d["status"] == "DONE", d["progress_text"]
        return d

    # ⑥ ga 단일(mesh_only 템플릿)
    ps = env.param_set()
    env.to_mesh_only(ps["id"])
    assert c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": RESP}).status_code == 200
    base = {"explore": {"kind": "new", "count": 6, "seed": 1}, "seed": 1, "multi_execution": 2, "candidates": 2, "tol_rel": 1e-9}
    d1 = opt({**base, "param_set_id": ps["id"], "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"}, "iterations": 1,
              "algorithm": "ga", "algo_options": {"generations": 30}})
    assert next(it for it in d1["iterations"] if it["kind"] == "VERIFY")["fit"]["algo"]["name"] == "ga"
    # ⑤ 배치 결과 표(⑥ 탐색 배치 = ④ 일괄 예측)
    b = c.get(f"{API}/predict-batches/{d1['iterations'][0]['batch']['id']}", headers=P).json()
    assert b["status"] == "DONE" and len(b["rows"]) == 6 and all(x["responses"] for x in b["rows"])
    # ⑥ none 1회
    d2 = opt({**base, "param_set_id": ps["id"], "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"},
              "algorithm": "ga", "algo_options": {"generations": 20}, "verification": "none"})
    assert d2["stop_reason"] == "SURROGATE_ONLY" and all(x["state"] == "UNVERIFIED" for x in d2["iterations"][0]["candidates"])
    # ⑥ nsga2 2목적(native 세트)
    nps = native_set(env)
    assert c.put(f"{API}/param-sets/{nps['id']}/responses", headers=PW, json={"responses": RESP}).status_code == 200
    d3 = opt({**base, "param_set_id": nps["id"], "iterations": 1, "algorithm": "nsga2", "algo_options": {"generations": 20},
              "objectives": [{"metric": "resp:MaxStress_MAX", "sense": "min"}, {"metric": "resp:Disp_MAX", "sense": "min"}],
              "weights": [1, 1]})  # ON-C4: 다목적 가중치는 사용자 입력(자동 균등 없음)
    assert d3["mode"] == "multi" and next(it for it in d3["iterations"] if it["kind"] == "VERIFY")["fit"]["algo"]["name"] == "nsga2"
    assert d3["pareto"]["predicted"]

    tools = {r["tool"] for r in read_record(fake_record)}
    assert {"simlab", "paicad", "edspy", "hw"} <= tools
    assert not tools & {"hstbatch", "hstpy"}, tools
