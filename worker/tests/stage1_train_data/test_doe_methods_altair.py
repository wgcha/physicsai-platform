"""doe-methods.md DM-C3·§5.2: ①-3 Altair 플랫폼 생성에 halton·random·table 추가(워커 DG_PREP 표본 = `doe_platform.build`, 표 본문은 작업
params에만, TABLE_OUT_OF_RANGE 422) — V-DM-5(Altair)·V-DM-6(기존 8종 무수정은 test_s18_*)."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text

from helpers_stage1 import extract_and_tpl, job, make_inputs, study, submit
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.stage1_train_data import doe_platform
from physicsai_test_support import API, H

PW, P = H("tok-power", write=True), H("tok-power")


def _prepare(c, w, ai: Path, name: str) -> str:
    sid = study(c, name)
    cad, _assem = make_inputs(ai / name)
    extract_and_tpl(c, w, sid, cad)
    return sid


def _params(ai: Path, name: str, sampling: dict, **kw) -> dict:
    return {"sampling": sampling, "radioss_assem_path": str(ai / name / "00_inbox" / "radioss_assem"), **kw}


def _points(engine, doe_id: str) -> list[tuple[str, dict, dict]]:
    with engine.connect() as conn:
        rows = conn.execute(text("select run_key, values, applied_values from train_doe_points where doe_id=:d order by doe_no"),
                            {"d": doe_id}).all()
    return [(r[0], r[1], r[2]) for r in rows]


def test_v_dm_6_altair_halton_random_worker_rows_equal_build(p2_env, engine):
    c, mk, ai, lc, _d = p2_env
    w = mk()
    sid = _prepare(c, w, ai, "am1")
    with engine.connect() as conn:
        setup = train_repo.get_setup(conn, sid)
    for kind, inp, label, doe_type in (("halton", {"count": 5, "seed": 3}, "Halton(스크램블 QMC)", "HALTON"),
                                       ("random", {"count": 4, "seed": 9}, "균일 랜덤", "RANDOM")):
        sampling = {"kind": kind, **inp}
        j = submit(c, sid, "TD_DOE_GEN", _params(ai, "am1", sampling, multi_execution=2))
        assert j["params"]["doe_type"] == doe_type and j["params"]["doe_label"] == label and j["params"]["num_runs"] == inp["count"]
        assert j["params"]["sampling"] == sampling
        assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
        jd = job(c, j["id"])
        doe_id = jd["result"]["doe_id"]
        plan = doe_platform.build(sampling, setup, lc.settings)
        pts = _points(engine, doe_id)
        assert [p[0] for p in pts] == [r.run_key for r in plan.rows] and len(pts) == inp["count"]
        assert [p[1] for p in pts] == [r.values for r in plan.rows] and [p[2] for p in pts] == [r.applied_values for r in plan.rows]
        d = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
        assert d["doe_type"] == doe_type and d["options"] == inp and d["generator"] == "platform" and d["status"] == "READY"
        assert d["sampling"] == {"kind": kind, "label": label, "desc_id": f"td_{kind}", "meta": plan.meta}
        assert d["gen"]["done"] == inp["count"] and d["sampling"]["meta"]["seed"] == inp["seed"]
        dj = json.loads((ai / "am1" / "01_train" / "doe" / doe_id / "doe.json").read_text())
        assert dj["sampling"]["kind"] == kind and dj["sampling"]["label"] == label
        res = c.get(f"{API}/train-does/{doe_id}/result-table", headers=P)       # ⑤ 표본 방식 표시(응답이 없으면 영향도 off)
        assert res.status_code == 200, res.text
        assert res.json()["sampling"]["method"] == doe_type and res.json()["sampling"]["desc_id"] == f"td_{kind}"
        assert res.json()["sampling"]["label"] == label and res.json()["influence_class"] == "off"


def test_v_dm_5_altair_table_in_range_rows_and_out_of_range_422(p2_env, engine):
    c, mk, ai, lc, _d = p2_env
    w = mk()
    sid = _prepare(c, w, ai, "am2")
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    used = [p for p in ts["parameters"] if p["use"]]
    names = [p["name"] for p in used]
    lo = {p["name"]: p["min"] for p in used}
    hi = {p["name"]: p["max"] for p in used}
    rev = list(reversed(names))                                                   # 머리줄 순서 무관
    body = ",".join(rev) + "\n" + "\n".join(",".join(repr(v[n]) for n in rev) for v in (lo, hi, {n: (lo[n] + hi[n]) / 2 for n in names})) + "\n"
    bad = body.replace(repr(hi[names[0]]), repr(hi[names[0]] + 1.0))
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN",
                                                              "params": _params(ai, "am2", {"kind": "table", "text": bad})})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "DOE_SAMPLING_INVALID", r.text
    pr = r.json()["detail"]["problems"]
    assert pr[0]["code"] == "TABLE_OUT_OF_RANGE" and f"'{names[0]}' 값" in pr[0]["message"] and "학습 범위" in pr[0]["message"]
    one = ",".join(rev) + "\n" + ",".join(repr(lo[n]) for n in rev) + "\n"
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN",
                                                              "params": _params(ai, "am2", {"kind": "table", "text": one})})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["code"] == "TOO_FEW_ROWS"
    j = submit(c, sid, "TD_DOE_GEN", _params(ai, "am2", {"kind": "table", "text": body}, multi_execution=2))
    assert j["params"]["doe_type"] == "TABLE" and j["params"]["num_runs"] == 3 and j["params"]["sampling"]["text"] == body
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    pts = _points(engine, doe_id)
    assert [p[0] for p in pts] == ["run__00001", "run__00002", "run__00003"]
    assert [[p[1][n] for n in names] for p in pts] == [[lo[n] for n in names], [hi[n] for n in names], [(lo[n] + hi[n]) / 2 for n in names]]
    with engine.connect() as conn:
        row = conn.execute(text("select options, sampling from train_does where id=:i"), {"i": doe_id}).one()
    assert row[0] == {"row_count": 3} and row[1]["input"] == {"row_count": 3} and row[1]["kind"] == "table"   # DB에는 본문 없음
    d = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert d["options"] == {"row_count": 3} and d["sampling"]["kind"] == "table" and d["sampling"]["desc_id"] == "td_table"
    assert d["doe_type"] == "TABLE" and d["gen"]["done"] == 3
    dj = json.loads((ai / "am2" / "01_train" / "doe" / doe_id / "doe.json").read_text())
    assert dj["sampling"]["input"] == {"row_count": 3} and dj["rows"][0]["values"] == pts[0][1]
