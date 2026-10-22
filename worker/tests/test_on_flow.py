"""opt-native V-ON-10(가짜 도구 + API + 워커): problems 신규 코드, 하위 호환(키 없음 → ego·loop), `ga` 단일·`nsga2` 2목적 반복
검증 흐름 DONE(fit.algo·role·algo_history.csv·final_population.csv), `verification: "none"` → 배치 1개(탐색)·반복 작업 1개·DONE·
SURROGATE_ONLY·best = 탐색 최선·후보 UNVERIFIED·FINAL 없음·알림 문구, 이어서 EXTRA verify.

가짜 hw의 RESPONSES 값은 run마다 같으므로 `run_metrics.load_run_metrics`를 감싸 MaxStress_MAX·Disp_MAX를 입력값 함수로 바꾼다
(test_surrogate_flow와 같은 방식).
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from physicsai_test_support import API, H

pytest.importorskip("numpy")
pytest.importorskip("scipy")

_spec = importlib.util.spec_from_file_location("_s4_predict_conftest_on", Path(__file__).parent / "stage4_predict" / "conftest.py")
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules[_spec.name] = _mod  # type: ignore[union-attr]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
predict_env = _mod.predict_env

PW = H("tok-power", write=True)
P = H("tok-power")
TCL_NAME = "H3D_StaticMinMax_to_CSV_FAST.tcl"
RESP = [{"name": "MaxStress", "unit": "MPa",
         "spec": {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}},
        {"name": "Disp", "unit": "mm", "spec": None}]
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def f1(v: dict[str, float]) -> float:
    return 100.0 + 20.0 * (v["THK_1"] - 3.4) ** 2 + 3.0 * (v["N_RIB"] - 5) ** 2


def f2(v: dict[str, float]) -> float:
    return 50.0 + 30.0 * (v["THK_1"] - 2.6) ** 2 + 2.0 * (v["N_RIB"] - 3) ** 2


@pytest.fixture()
def on_env(predict_env, tmp_path, monkeypatch):
    from physicsai_core.stage4_predict import run_metrics

    tcl = tmp_path / "res" / TCL_NAME
    tcl.parent.mkdir(parents=True)
    tcl.write_text("# fake\n")
    env = predict_env(commands={"response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"],
                                "hst_gen_radioss": None, "hst_optimization": None},
                      resources={"extract_minmax_tcl": str(tcl)})
    orig = run_metrics.load_run_metrics

    def load(files: Any, *, max_bytes: int) -> Any:
        m = orig(files, max_bytes=max_bytes)
        if m.resp is None or not files.result_dir:
            return m
        jid = UUID_RE.findall(files.result_dir.replace("\\", "/"))[-1]
        row = env.sql("select applied_values from predict_batch_runs where predict_job_id=:i", i=jid)
        vals = row[0][0] if row else env.sql("select result -> 'values' from jobs where id=:i", i=jid)[0][0]
        return run_metrics.RunMetrics(curve=m.curve, resp={**m.resp, "MaxStress_MAX": f1(vals), "Disp_MAX": f2(vals)})

    monkeypatch.setattr(run_metrics, "load_run_metrics", load)
    ps = env.param_set()
    r = env.c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": RESP})
    assert r.status_code == 200, r.text
    env.ps = ps  # type: ignore[attr-defined]
    return env


def _body(**kw: Any) -> dict[str, Any]:
    b = {"explore": {"kind": "new", "count": 6, "seed": 1}, "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"},
         "iterations": 2, "candidates": 2, "tol_rel": 1e-9, "seed": 1, "multi_execution": 2}
    b.update(kw)
    return b


MO = {"objective": None, "objectives": [{"metric": "resp:MaxStress_MAX", "sense": "min"}, {"metric": "resp:Disp_MAX", "sense": "min"}],
      "weights": [50, 50]}


def _drain(env: Any, limit: int = 120) -> list[tuple[str, str | None]]:
    seen = []
    for _ in range(limit):
        q = env.sql("select id, job_type from jobs where state='QUEUED' and lane in ('CPU','GPU') order by queue_seq limit 1")
        if not q:
            return seen
        st = env.w.run_once_slot()
        seen.append((q[0][1], st))
    raise AssertionError("대기열이 끝나지 않았습니다")


def _create(env: Any, body: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in body.items() if v is not None}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _detail(env: Any, oid: str) -> dict[str, Any]:
    return env.c.get(f"{API}/surrogate-opts/{oid}", headers=P).json()


def _preview(env: Any, body: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in body.items() if v is not None}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _odir(env: Any, d: dict[str, Any]) -> Path:
    return env.sroot / env.sql("select dir_rel from surrogate_opts where id=:i", i=d["id"])[0][0]


def test_v_on_10_problem_codes_and_preview(on_env):
    env = on_env
    codes = lambda **kw: [p["code"] for p in _preview(env, _body(**kw))["problems"]]  # noqa: E731
    assert codes(algorithm="cmaes") == ["ALGORITHM_INVALID"]
    assert codes(algorithm="nsga2") == ["ALGORITHM_MISMATCH"]
    assert codes(**MO, algorithm="ga") == ["ALGORITHM_MISMATCH"]
    assert codes(algorithm="ga", algo_options={"pop_size": 7}) == ["ALGO_OPTIONS_INVALID"]
    assert codes(algorithm="ga", algo_options={"nope": 1}) == ["ALGO_OPTIONS_INVALID"]
    assert codes(algo_options={"generations": 10}) == ["ALGO_OPTIONS_INVALID"]  # ego인데 옵션
    assert codes(verification="sometimes") == ["VERIFICATION_INVALID"]
    assert codes(levels={"baseline": ["base"]}) == ["LEVELS_INVALID"]  # 단일 세트
    pv = _preview(env, _body(algorithm="ga", algo_options={"generations": 30}))
    assert pv["problems"] == [] and pv["algorithm"] == "ga" and pv["verification"] == "loop"
    assert pv["algo_options"] == {"pop_size": 40, "generations": 30, "crossover_prob": 0.9, "mutation_prob": None, "eta_c": 15.0,
                                  "eta_m": 20.0}
    assert pv["variables_kind"] == {"THK_1": "continuous", "N_RIB": "integer"} and pv["max_total_runs"] == 6 + 2 * 2
    pv = _preview(env, _body(verification="none", iterations=99, tol_rel=5.0))  # none이면 반복·개선 기준 무시
    assert pv["problems"] == [] and pv["max_total_runs"] == 6 and pv["verification"] == "none"
    pv = _preview(env, _body())  # 하위 호환: 키 없음 → ego·loop
    assert (pv["algorithm"], pv["verification"], pv["algo_options"]) == ("ego", "loop", {})


def test_v_on_10_ga_loop_flow(on_env):
    env = on_env
    env.to_mesh_only(env.ps["id"])
    opt = _create(env, _body(algorithm="ga", algo_options={"generations": 40}))
    assert opt["settings"]["algorithm"] == "ga" and opt["settings"]["verification"] == "loop"
    seen = _drain(env)
    assert all(st == "SUCCEEDED" for _, st in seen), seen
    d = _detail(env, opt["id"])
    assert d["status"] == "DONE" and d["stop_reason"] in ("MAX_ITER", "CONVERGED"), d["progress_text"]
    verify = [it for it in d["iterations"] if it["kind"] == "VERIFY"]
    assert verify
    for it in verify:
        a = it["fit"]["algo"]
        assert a["name"] == "ga" and a["pop_size"] == 40 and a["generations"] == 40 and a["stop"] in ("MAX_GEN", "STALL")
        assert a["evals"] == 40 * (a["generations_run"] + 1) and a["seed"] == 100000 + 1000 * it["iter_no"] + 900
        assert a["surrogate_optimum"]["values"] and a["best_pred"] is not None
        roles = [c["role"] for c in it["candidates"]]
        assert roles[0] in ("ga", "ga_ei") and set(roles) <= {"ga", "ga_ei"}
        assert all(c["values"]["N_RIB"] == int(c["values"]["N_RIB"]) and c["state"] == "SUCCEEDED" for c in it["candidates"])
    O = _odir(env, d)
    hist = list(csv.reader(io.StringIO((O / "iter_01" / "algo_history.csv").read_text())))
    assert hist[0] == ["gen", "evals", "n_feasible", "best_pred", "mean_pred"] and hist[1][0] == "0"
    pop = list(csv.reader(io.StringIO((O / "iter_01" / "final_population.csv").read_text())))
    assert pop[0] == ["THK_1", "N_RIB", "mu_1", "sd_1", "cv", "rank", "crowding"] and len(pop) == 41 and pop[1][-1] == ""
    s = json.loads((O / "summary.json").read_text())
    assert s["algorithm"] == "ga" and s["verification"] == "loop" and s["algo_options"]["generations"] == 40
    oj = json.loads((O / "opt.json").read_text())
    assert oj["algorithm"] == "ga" and oj["algo_options"]["pop_size"] == 40
    sj = json.loads((O / "iter_01" / "surrogate.json").read_text())
    assert sj["algo"]["name"] == "ga" and sj["algo"]["options"]["generations"] == 40


def test_v_on_10_default_request_is_ego_loop(on_env):
    env = on_env
    opt = _create(env, _body(iterations=1, candidates=1))
    assert (opt["settings"]["algorithm"], opt["settings"]["verification"], opt["settings"]["algo_options"]) == ("ego", "loop", {})
    _drain(env)
    d = _detail(env, opt["id"])
    assert d["status"] == "DONE"
    it = next(x for x in d["iterations"] if x["kind"] == "VERIFY")
    assert it["fit"]["algo"] == {"name": "ego"} and not (_odir(env, d) / "iter_01" / "algo_history.csv").exists()


def test_v_on_10_nsga2_loop_flow(on_env):
    env = on_env
    opt = _create(env, _body(**MO, algorithm="nsga2", algo_options={"generations": 30}))
    seen = _drain(env)
    assert all(st == "SUCCEEDED" for _, st in seen), seen
    d = _detail(env, opt["id"])
    assert d["status"] == "DONE" and d["mode"] == "multi", d["progress_text"]
    it = next(x for x in d["iterations"] if x["kind"] == "VERIFY")
    assert it["fit"]["algo"]["name"] == "nsga2" and it["fit"]["algo"]["pop_size"] == 100 and it["fit"]["algo"]["hv_pred"] is not None
    assert all(c["role"] == "nsga2" and c["weight"] is None for c in it["candidates"])
    assert d["pareto"]["predicted"] and len(d["pareto"]["predicted"]) <= 28 and d["hv_history"]
    O = _odir(env, d)
    hist = list(csv.reader(io.StringIO((O / "iter_01" / "algo_history.csv").read_text())))
    assert hist[0] == ["gen", "evals", "n_feasible", "front_size", "hv_pred"]
    front = list(csv.reader(io.StringIO((O / "iter_01" / "predicted_front.csv").read_text())))
    assert front[0][:2] == ["THK_1", "N_RIB"] and len(front) - 1 >= len(d["pareto"]["predicted"])
    pop = list(csv.reader(io.StringIO((O / "iter_01" / "final_population.csv").read_text())))
    assert pop[0][-3:] == ["cv", "rank", "crowding"] and pop[1][-2] == "1"


def test_v_on_10_surrogate_only_then_extra_verify(on_env):
    env = on_env
    opt = _create(env, _body(algorithm="ga", algo_options={"generations": 30}, verification="none", iterations=5, candidates=3))
    assert opt["settings"]["iterations"] == 1 and opt["settings"]["verification"] == "none"
    seen = _drain(env)
    types = [t for t, _ in seen]
    assert all(st == "SUCCEEDED" for _, st in seen), seen
    assert types.count("PREDICT_BATCH") == 1 and types.count("SURROGATE_OPT") == 1 and types.count("PREDICT") == 6
    d = _detail(env, opt["id"])
    assert d["status"] == "DONE" and d["stop_reason"] == "SURROGATE_ONLY", d["progress_text"]
    assert d["progress_text"].startswith("완료 — 대리모델만")
    assert [it["kind"] for it in d["iterations"]] == ["EXPLORE"]
    it0 = d["iterations"][0]
    assert it0["fit"]["algo"]["name"] == "ga" and len(it0["candidates"]) == 3
    assert all(c["state"] == "UNVERIFIED" and c["verified"] is None for c in it0["candidates"])
    explore = [r for r in d["runs"] if r["state"] == "SUCCEEDED"]
    assert d["best"]["objective"] == min(r["objective"] for r in explore)
    assert all(r["predicted"] is None for r in d["runs"])  # 미검증 후보는 탐색 run과 짝짓지 않음
    assert d["final"]["status"] == "SKIPPED" and d["final"]["batch"] is None
    n = env.sql("select title from notifications where event='SURROGATE_OPT_DONE' order by seq desc limit 1")
    assert n and n[0][0] == "내장 최적화 SO-001 완료(대리모델만) — 미검증 후보 3개, 결과 화면에서 예측 검증하세요"
    s = json.loads((_odir(env, d) / "summary.json").read_text())
    assert s["stop_reason"] == "SURROGATE_ONLY" and s["verification"] == "none" and len(s["candidates"]) == 3
    # 이어서 고른 해를 추가 검증(§22.7 EXTRA, 단일 목적·none에도)
    assert d["can_verify_more"] is True
    pts = [{"values": c["values"]} for c in it0["candidates"][:2]]
    r = env.c.post(f"{API}/surrogate-opts/{opt['id']}/verify", headers=PW, json={"points": pts})
    assert r.status_code == 201, r.text
    assert all(st == "SUCCEEDED" for _, st in _drain(env))
    d = _detail(env, opt["id"])
    extra = [x for x in d["runs"] if x["kind"] == "EXTRA"]
    assert len(extra) == 2 and all(x["state"] == "SUCCEEDED" and x["objective"] is not None for x in extra)
    assert d["status"] == "DONE" and d["stop_reason"] == "SURROGATE_ONLY"
