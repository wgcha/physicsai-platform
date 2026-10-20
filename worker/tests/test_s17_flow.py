"""V3-S17-9·11·13(가짜 도구 + API + 워커, mesh_only): 2목적(perf H3D CornerStress + perf CURVE AccelPeak) 탐색 6 → 2×2 → FINAL →
DONE, 검증된 전선·가중 추천·HV 추이·예측 전선, 추가 검증 2점 → 전선 갱신, problems 신규 코드, 단수 objective 호환.

가짜 hw·edspy 값은 run마다 같으므로(흐름 확인용) `run_metrics.load_run_metrics`를 감싸 CornerStress(RESPONSES)·커브 값을 그 run의
입력값 함수로 바꾼다 — 요청 파일(H3D_REQUESTS.txt)에 CornerStress 줄이 있는 run만(정의 전 예측 run은 값 없음). 품질은 V3-S17-7.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from physicsai_test_support import API, H

pytest.importorskip("numpy")
pytest.importorskip("scipy")

_spec = importlib.util.spec_from_file_location("_s4_predict_conftest_s17", Path(__file__).parent / "stage4_predict" / "conftest.py")
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules[_spec.name] = _mod  # type: ignore[union-attr]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
predict_env = _mod.predict_env

PW = H("tok-power", write=True)
P = H("tok-power")
TCL_NAME = "H3D_StaticMinMax_to_CSV_FAST.tcl"
H3D = {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}
BASE = [{"name": "MaxStress", "unit": "MPa", "spec": H3D}, {"name": "Disp", "unit": "mm", "spec": None}]
PERFS = [{"name": "CornerStress", "unit": "MPa", "spec": {**H3D, "datatype": "CornerStress", "component": ""}},
         {"name": "AccelPeak", "unit": "g", "spec": {"source": "CURVE", "series": None, "stat": "ABSMAX"}}]
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def f1(v: dict[str, float]) -> float:
    return 100.0 + 20.0 * (v["THK_1"] - 3.4) ** 2 + 3.0 * (v["N_RIB"] - 5) ** 2


def f2(v: dict[str, float]) -> float:
    return 50.0 + 30.0 * (v["THK_1"] - 2.6) ** 2 + 2.0 * (v["N_RIB"] - 3) ** 2


@pytest.fixture()
def mo_env(predict_env, tmp_path, monkeypatch):
    from physicsai_core.stage4_predict import run_metrics

    tcl = tmp_path / "res" / TCL_NAME
    tcl.parent.mkdir(parents=True)
    tcl.write_text("# fake\n")
    env = predict_env(commands={"response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]},
                      resources={"extract_minmax_tcl": str(tcl)})
    orig = run_metrics.load_run_metrics

    def load(files: Any, *, max_bytes: int) -> Any:
        m = orig(files, max_bytes=max_bytes)
        if not files.result_dir or not m.requests or "CornerStress" not in m.requests:
            return m
        jid = UUID_RE.findall(files.result_dir.replace("\\", "/"))[-1]
        row = env.sql("select applied_values from predict_batch_runs where predict_job_id=:i", i=jid)  # 반영값(정수 반올림)
        vals = row[0][0] if row else env.sql("select result -> 'values' from jobs where id=:i", i=jid)[0][0]
        a = f2(vals)
        return run_metrics.RunMetrics(curve={"Impact_force": {"max": a, "min": -a / 2, "absmax": a}},
                                      resp={**(m.resp or {}), "CornerStress_MAX": f1(vals), "CornerStress_MIN": 0.0},
                                      requests=m.requests)

    monkeypatch.setattr(run_metrics, "load_run_metrics", load)
    ps = env.param_set()
    env.to_mesh_only(ps["id"])
    env.ps = ps  # type: ignore[attr-defined]
    return env


def _put(env: Any, rows: list[dict[str, Any]]) -> None:
    r = env.c.put(f"{API}/param-sets/{env.ps['id']}/responses", headers=PW, json={"responses": rows})
    assert r.status_code == 200, r.text


def _body(**kw: Any) -> dict[str, Any]:
    b = {"explore": {"kind": "new", "count": 6, "seed": 1},
         "objectives": [{"metric": "perf:CornerStress", "sense": "min"}, {"metric": "perf:AccelPeak", "sense": "min"}],
         "observe": [{"metric": "perf:MaxStress"}, {"metric": "curve:max", "series": "Nope"}],
         "weights": [50, 50], "iterations": 2, "candidates": 2, "tol_rel": 1e-9, "seed": 1, "multi_execution": 2}
    b.update(kw)
    return b


def _drain(env: Any, limit: int = 80) -> list[tuple[str, str | None]]:
    seen = []
    for _ in range(limit):
        q = env.sql("select id, job_type from jobs where state='QUEUED' and lane='SLOT' order by queue_seq limit 1")
        if not q:
            return seen
        seen.append((q[0][1], env.w.run_once_slot()))
    raise AssertionError("대기열이 끝나지 않았습니다")


def test_v3_s17_13_multiobjective_e2e_and_extra_verify(mo_env):
    env = mo_env
    _put(env, [*BASE, *PERFS])
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=_body())
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["mode"] == "multi" and pv["problems"] == [] and pv["max_total_runs"] == 10
    perf = {x["id"]: x for x in pv["performances"]}
    assert perf["perf:AccelPeak"]["label"] == "AccelPeak (커브 |최대|)" and perf["perf:AccelPeak"]["source"] == "CURVE"
    assert perf["perf:CornerStress"]["label"] == "CornerStress (MAX)" and perf["perf:CornerStress"]["available"] is None
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body())
    assert r.status_code == 201, r.text
    opt = r.json()
    st = env.sql("select settings from surrogate_opts where id=:i", i=opt["id"])[0][0]
    assert st["mode"] == "multi" and st["objective"] == st["objectives"][0] and st["weights"] == [0.5, 0.5]
    assert set(st["performances"]) == {"CornerStress", "AccelPeak", "MaxStress"}
    # 추가 검증은 DONE만
    v = env.c.post(f"{API}/surrogate-opts/{opt['id']}/verify", headers=PW, json={"points": [{"values": {"THK_1": 3, "N_RIB": 4}}]})
    assert v.status_code == 409 and v.json()["detail"]["code"] == "SURROGATE_OPT_NOT_DONE"
    seen = _drain(env)
    assert all(s == "SUCCEEDED" for _t, s in seen), seen
    d = env.c.get(f"{API}/surrogate-opts/{opt['id']}", headers=P).json()
    assert d["status"] == "DONE" and d["mode"] == "multi", d["progress_text"]
    assert [o["label"] for o in d["objectives"]] == ["CornerStress (MAX)", "AccelPeak (커브 |최대|)"]
    assert [o["unit"] for o in d["objectives"]] == ["MPa", "g"] and d["weights"] == [0.5, 0.5]
    assert [o["label"] for o in d["observe"]] == ["MaxStress (MAX)", "커브 최대값(Nope)"]
    n_iter = len([it for it in d["iterations"] if it["kind"] != "EXTRA"])
    assert [it["kind"] for it in d["iterations"]] == ["EXPLORE", *["VERIFY"] * (n_iter - 1)]
    # SO_COLLECT 다목적 기록: hv·front_size·개선율, hv_frame 고정
    frame = env.sql("select hv_frame from surrogate_opts where id=:i", i=opt["id"])[0][0]
    assert frame["ref_offset"] == 0.1 and frame["signs"] == [1.0, 1.0] and len(frame["ideal"]) == 2
    it0 = [x["objectives"] for x in d["runs"] if x["iter_no"] == 0 and x["state"] == "SUCCEEDED"]   # 반복 0 자료로 1회 확정
    assert frame["ideal"] == pytest.approx([min(o[i] for o in it0) for i in range(2)])
    assert frame["nadir"] == pytest.approx([max(o[i] for o in it0) for i in range(2)])
    hvh = d["hv_history"]
    assert [h["iter_no"] for h in hvh] == list(range(n_iter)) and all(h["hv"] is not None for h in hvh)
    assert hvh[0]["improvement_rel"] is None and all(it["best_value"] is None for it in d["iterations"])
    assert all(it["best_feasible"] is True for it in d["iterations"])
    for it in d["iterations"][1:]:
        assert it["fit"]["kind"] in ("gp", "mixed") and len(it["fit"]["per_objective"]) == 2
        assert it["fit"]["per_objective"][0]["pred_vs_verified_mae"] is not None
        assert [c["role"] for c in it["candidates"]][0] == "hvi" and len(it["candidates"][0]["predicted_objectives"]) == 2
        assert all(c["values"]["N_RIB"] == int(c["values"]["N_RIB"]) for c in it["candidates"])
    # 검증된 전선·추천
    par = d["pareto"]
    assert len(par["front"]) >= 1 and par["hv"] == pytest.approx(hvh[-1]["hv"])
    keys = [f["key"] for f in par["front"]]
    assert par["recommended_key"] in keys and par["frame"] == frame
    assert par["predicted_iter"] >= 1 and 1 <= len(par["predicted"]) <= 28 and len(par["predicted"][0]["mean"]) == 2
    for f in par["front"]:
        assert f["objectives"][0] == pytest.approx(f1(f["values"])) and f["objectives"][1] == pytest.approx(f2(f["values"]))
    on = {f"{x['iter_no']}:{x['doe_no']}" for x in d["runs"] if x["on_front"]}
    assert set(keys) <= on
    run0 = next(x for x in d["runs"] if x["state"] == "SUCCEEDED")
    assert run0["observed"]["perf:MaxStress"] == 100.0 and run0["observed"]["curve:max@Nope"] is None
    assert run0["reason"] == "NO_VALUE" and run0["kind"] == "EXPLORE" and len(run0["objectives"]) == 2
    rec = next(f for f in par["front"] if f["key"] == par["recommended_key"])
    assert d["best"]["objectives"] == {"perf:CornerStress": pytest.approx(rec["objectives"][0]),
                                       "perf:AccelPeak": pytest.approx(rec["objectives"][1])}
    assert d["best"]["feasible"] is True and d["best"]["score"] is not None and d["best"]["weights"] == [0.5, 0.5]
    # FINAL 2행 = 기준안 + 추천점
    fin = d["final"]
    assert fin["status"] in ("DONE", "SKIPPED") and fin["batch"] is not None
    assert fin["best"]["values"] == rec["values"] and fin["baseline"]["values"] == {"THK_1": 3.0, "N_RIB": 4}
    notes = env.sql("select title from notifications where event='SURROGATE_OPT_DONE'")
    assert len(notes) == 1 and notes[0][0].startswith("내장 최적화 SO-001 완료 — 파레토 해 ")
    assert " · HV " in notes[0][0] and " · 추천 CornerStress " in notes[0][0] and " / AccelPeak " in notes[0][0]
    assert not env.sql("select 1 from notifications where event='PREDICT_BATCH_DONE'")
    # 파일
    O = env.sroot / "05_opt" / "surrogate" / "SO-001"
    for name in ("iter_01/predicted_front.csv", "iter_01/loo.csv", "iter_01/candidates.csv", "iter_00/dataset.csv"):
        assert (O / name).is_file(), name
    assert (O / "iter_01" / "loo.csv").read_text().splitlines()[0] == "model,i,y,loo_mean,loo_std"
    assert (O / "iter_00" / "dataset.csv").read_text().splitlines()[0].startswith(
        "iter,batch,doe_no,run_key,THK_1,N_RIB,objective_1,objective_2,obs:MaxStress,obs:커브 최대값(Nope),reason,state")
    text = env.c.get(f"{API}/surrogate-opts/{opt['id']}/runs.csv", headers=P).content.decode("utf-8")
    assert text.startswith("﻿iter,batch,doe_no,run_key,THK_1,N_RIB,objective_1,objective_2,obs:MaxStress,")
    assert "reason,predicted,feasible,state\r\n" in text.splitlines(keepends=True)[0]

    # ---- 추가 검증(EXTRA) ----
    url = f"{API}/surrogate-opts/{opt['id']}/verify"
    bad = env.c.post(url, headers=PW, json={"points": [{"values": {"THK_1": 9.9, "N_RIB": 4}}]})
    assert bad.status_code == 422 and bad.json()["detail"]["problems"][0]["code"] == "BOUNDS_OUT_OF_RANGE"
    many = env.c.post(url, headers=PW, json={"points": [{"values": {"THK_1": 3, "N_RIB": 4}}] * 11})
    assert many.status_code == 422 and many.json()["detail"]["problems"][0]["code"] == "EXTRA_POINTS_RANGE"
    pts = [{"values": {"THK_1": 3.4, "N_RIB": 5}}, {"values": dict(par["predicted"][0]["values"])}]
    v = env.c.post(url, headers=PW, json={"points": pts, "capture": False})
    assert v.status_code == 201, v.text
    vj = v.json()
    top = env.sql("select max(iter_no) from surrogate_opt_iters where opt_id=:o and kind<>'EXTRA'", o=opt["id"])[0][0]
    assert vj["iter_no"] == top + 1 and top >= n_iter - 1                      # FINAL(있으면) 다음 번호
    again = env.c.post(url, headers=PW, json={"points": pts[:1]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "SURROGATE_OPT_EXTRA_ACTIVE"
    pj = env.sql("select params from jobs where id=:i", i=vj["job_id"])[0][0]
    assert pj["surrogate_opt"]["extra"] is True and pj["capture"] == {"enabled": False} and pj["source"]["kind"] == "table"
    n_rounds = len(env.sql("select 1 from jobs where job_type='SURROGATE_OPT'"))
    seen = _drain(env)
    assert all(s == "SUCCEEDED" for _t, s in seen) and "SURROGATE_OPT" not in [t for t, _s in seen]
    assert len(env.sql("select 1 from jobs where job_type='SURROGATE_OPT'")) == n_rounds   # 종료 훅: 반복 작업 없음
    notes = env.sql("select title from notifications where event='PREDICT_BATCH_DONE'")
    assert len(notes) == 1 and notes[0][0].startswith(f"일괄 예측 {vj['batch_label']} 완료")
    d2 = env.c.get(f"{API}/surrogate-opts/{opt['id']}", headers=P).json()
    assert d2["status"] == "DONE" and d2["iterations"][-1]["kind"] == "EXTRA"
    extra_runs = [x for x in d2["runs"] if x["kind"] == "EXTRA"]
    assert len(extra_runs) == 2 and all(x["state"] == "SUCCEEDED" for x in extra_runs)
    best1 = f"{vj['iter_no']}:1"                                              # f1 최소 설계 → 전선에 반영
    assert best1 in [f["key"] for f in d2["pareto"]["front"]]
    assert d2["hv_history"] == hvh and d2["can_verify_more"] is True
    # EXTRA 배치는 ④ 일반 배치처럼 취소·실패만 다시(BATCH_OWNED_BY_OPT 아님)
    v3 = env.c.post(url, headers=PW, json={"points": pts[:1]}).json()
    r = env.c.post(f"{API}/predict-batches/{v3['batch_id']}/cancel", headers=PW)
    assert r.status_code == 202, r.text
    _drain(env)
    r = env.c.post(f"{API}/predict-batches/{v3['batch_id']}/retry-failed", headers=PW)
    assert r.status_code in (201, 409) and (r.status_code == 201 or r.json()["detail"]["code"] != "BATCH_OWNED_BY_OPT")


def test_v3_s17_11_problems_and_single_compat(mo_env, monkeypatch):
    env = mo_env
    _put(env, BASE)
    old_bid, _j = env.make_batch(env.ps["id"], "THK_1,N_RIB\n" + "".join(f"{2 + 0.4 * i},{2 + i % 6}\n" for i in range(7)))
    _drain(env)                                                                # 정의 전 예측 배치(성능 값 없음)
    _put(env, [*BASE, *PERFS])
    url = f"{API}/studies/{env.sid}/surrogate-opts/preview"

    def codes(**kw: Any) -> set[str]:
        r = env.c.post(url, headers=PW, json=_body(**kw))
        assert r.status_code == 200, r.text
        return {p["code"] for p in r.json()["problems"]}

    assert codes(objective={"metric": "perf:CornerStress", "sense": "min"}) == {"OBJECTIVES_CONFLICT"}
    assert codes(objectives=[{"metric": f"perf:{n}", "sense": "min"} for n in ("CornerStress", "AccelPeak", "MaxStress")] +
                 [{"metric": "curve:max", "sense": "min"}], weights=None, observe=[]) == {"OBJECTIVES_RANGE"}
    assert codes(objectives=[{"metric": "perf:CornerStress", "sense": "min"}, {"metric": "perf:CornerStress", "sense": "max"}]) == \
        {"OBJECTIVE_DUPLICATE"}
    assert codes(constraints=[{"metric": "perf:CornerStress", "op": "<=", "value": 1}]) == {"OBJECTIVE_DUPLICATE"}
    assert codes(constraints=[{"metric": "perf:MaxStress", "op": "range", "lo": 5, "hi": 5}], observe=[]) == \
        {"CONSTRAINT_INVALID"}
    # ON-C3: 값 없는 제약·방향 없는 목적·다목적 가중치 생략 = OPT_CRITERIA_REQUIRED(기본값으로 채우지 않음)
    assert codes(constraints=[{"metric": "perf:MaxStress", "op": "<="}], observe=[]) == {"OPT_CRITERIA_REQUIRED"}
    assert codes(objectives=[{"metric": "perf:CornerStress"}, {"metric": "perf:AccelPeak", "sense": "max"}]) == \
        {"OPT_CRITERIA_REQUIRED"}
    assert codes(weights=None) == {"OPT_CRITERIA_REQUIRED"}
    assert codes(objectives=[]) == {"OPT_CRITERIA_REQUIRED"}
    assert codes(observe=[{"metric": "curve:min", "series": f"S{i}"} for i in range(11)]) == {"OBSERVE_INVALID"}
    assert codes(observe=[{"metric": "resp:Nope_MAX"}]) == {"OBSERVE_INVALID"}
    assert codes(weights=[1, 2, 3]) == {"WEIGHTS_INVALID"} and codes(weights=[0, 0]) == {"WEIGHTS_INVALID"}
    assert codes(weights=[-1, 2]) == {"WEIGHTS_INVALID"}
    assert codes(objectives=[{"metric": "perf:Nope", "sense": "min"}, {"metric": "perf:AccelPeak", "sense": "min"}]) == \
        {"PERF_UNDEFINED"}
    assert codes(constraints=[{"metric": "perf:MaxStress", "op": "range", "lo": 1, "hi": 900}], observe=[]) == set()
    # 재사용 배치에 성능 값 없음 → PERF_MISSING_IN_BATCH(action extract) — CURVE는 다시 추출 없이 값 있음
    r = env.c.post(url, headers=PW, json=_body(explore={"kind": "reuse", "batch_id": old_bid}))
    probs = r.json()["problems"]
    miss = [p for p in probs if p["code"] == "PERF_MISSING_IN_BATCH"]
    assert len(miss) == 1 and miss[0]["action"] == "extract" and miss[0]["batch_id"] == old_bid
    assert miss[0]["performance"] == "CornerStress" and "EXPLORE_TOO_FEW" in {p["code"] for p in probs}
    perf = {x["id"]: x for x in r.json()["performances"]}
    assert perf["perf:CornerStress"]["available"] == 0 and perf["perf:CornerStress"]["total"] == 7
    assert perf["perf:AccelPeak"]["available"] == 7
    # H3D 성능 + 추출 미구성 → PERF_EXTRACT_UNAVAILABLE
    orig_cmd = env.lc.settings.commands.response_extract
    monkeypatch.setattr(env.lc.settings.commands, "response_extract", None)
    assert codes() == {"PERF_EXTRACT_UNAVAILABLE"}
    monkeypatch.setattr(env.lc.settings.commands, "response_extract", orig_cmd)
    # 단수 objective(호환) → 단일 동작·settings에 objectives 1개 + objective
    body = {"explore": {"kind": "new", "count": 6, "seed": 1}, "objective": {"metric": "perf:AccelPeak", "sense": "min"},
            "constraints": [{"metric": "perf:MaxStress", "op": "range", "lo": 1, "hi": 900}],
            "iterations": 1, "candidates": 1, "seed": 1, "multi_execution": 2}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=body)
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["mode"] == "single" and o["pareto"] is None and o["hv_history"] is None
    assert [c["op"] for c in o["constraints_def"]] == ["range"] and o["constraints_def"][0]["lo"] == 1
    st = env.sql("select settings from surrogate_opts where id=:i", i=o["id"])[0][0]
    assert st["objectives"] == [st["objective"]] and st["mode"] == "single" and st["weights"] == [1.0]
    _drain(env)
    d = env.c.get(f"{API}/surrogate-opts/{o['id']}", headers=P).json()
    assert d["status"] == "DONE" and d["best"]["feasible"] is True
    assert d["best"]["objective"] == pytest.approx(f2(d["best"]["values"]))
    text = env.c.get(f"{API}/surrogate-opts/{o['id']}/runs.csv", headers=P).content.decode("utf-8")
    head = next(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert head == ["iter", "batch", "doe_no", "run_key", "THK_1", "N_RIB", "objective", "perf:MaxStress", "predicted",
                    "feasible", "state"]
    st = env.c.get(f"{API}/status", headers=P).json()["surrogate_opt"]
    assert (st["max_objectives"], st["max_observe"], st["max_extra_points"]) == (3, 10, 10)


def test_v3_s17_11_shared_legend_perf_rule():
    """§22.7: perf:<NAME>도 H3D·datatype = 컨투어 field·stat MAX·ABSMAX면 같은 범례, CURVE·MIN은 이미지마다 자동."""
    from types import SimpleNamespace

    from physicsai_worker.steps.stage5_optimize.surrogate import shared_legend

    cfg = SimpleNamespace(default_field="CornerStress", default_component="", views=["iso"])
    spec = {"source": "H3D", "subcase": 1, "datatype": "CornerStress", "component": "", "layer": ""}
    ps = {"display": None, "responses": [{"name": "Corner", "spec": {**spec, "stat": "ABSMAX"}},
                                         {"name": "CornerMin", "spec": {**spec, "stat": "MIN"}},
                                         {"name": "Accel", "spec": {"source": "CURVE", "series": None, "stat": "MAX"}}]}
    lg, why = shared_legend(cfg, ps, "perf:Corner", [120.0, 90.0])
    assert lg == {"min": 0.0, "max": pytest.approx(126.0)} and why.startswith("같은 범례")
    assert shared_legend(cfg, ps, "perf:CornerMin", [120.0, 90.0])[0] is None
    assert shared_legend(cfg, ps, "perf:Accel", [120.0, 90.0])[0] is None
