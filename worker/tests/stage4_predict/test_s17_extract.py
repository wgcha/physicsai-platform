"""V3-S17-4(가짜 도구): ④ RESPONSE_EXTRACT가 H3D(가짜 hw minmax) + CURVE 값을 responses_pred.csv에 모두 씀, CURVE만이면 TCL·요청 파일
없음, ①-6·PV는 CURVE를 조용히 건너뜀. PB_RESP_EXTRACT e2e: `_backup` 이동·새 RESPONSES·`predict_batch_runs.responses` 갱신·h3d 2개 run
건너뜀·API 409 4종·422."""

from __future__ import annotations

import csv
import json
import os
import uuid
from pathlib import Path
from typing import Any

from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
TCL_NAME = "H3D_StaticMinMax_to_CSV_FAST.tcl"
NEW_CMD = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]
VALUES = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}
H3D = {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}
CURVE_MAX = {"source": "CURVE", "series": None, "stat": "MAX"}      # 가짜 edspy .xy: y 0 · 10.5 · 20.25 · 15.0
KEEP = [{"name": "Disp", "unit": "mm", "spec": None}]               # 실측 열(지울 수 없음)


def _env(predict_env, tmp_path, **kw):
    tcl = tmp_path / "res" / TCL_NAME
    tcl.parent.mkdir(parents=True, exist_ok=True)
    tcl.write_text("# fake\n")
    return predict_env(commands={"response_extract": NEW_CMD}, resources={"extract_minmax_tcl": str(tcl)}, **kw)


def _tcl_calls(fake_record) -> list[dict[str, Any]]:
    return [r for r in read_record(fake_record) if r["tool"] == "hw" and r["argv"][-2:-1] == ["-tcl"]]


def _csv(path: Path) -> list[list[str]]:
    return list(csv.reader(path.open(encoding="utf-8")))


def test_v3_s17_4_predict_writes_h3d_and_curve(predict_env, tmp_path, fake_record):
    env = _env(predict_env, tmp_path)
    ps = env.param_set()
    env.set_responses(ps["id"], [{"name": "MaxStress", "unit": "MPa", "spec": H3D},
                                 {"name": "AccelPeak", "unit": "g", "spec": CURVE_MAX},
                                 {"name": "AccelMin", "unit": "g", "spec": {**CURVE_MAX, "stat": "MIN"}},
                                 {"name": "Missing", "unit": "g", "spec": {**CURVE_MAX, "series": "Node 9 / Z"}}, *KEEP])
    j = env.submit("PREDICT", VALUES)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    jd = env.job(j["id"])
    rows = _csv(env.predict_dir(j["id"]) / "responses_pred.csv")
    assert rows == [["name", "value"], ["MaxStress", "100.0"], ["AccelPeak", "20.25"], ["AccelMin", "0.0"], ["Missing", ""],
                    ["Disp", ""]]
    req = (env.predict_dir(j["id"]) / "RESULT" / "H3D_REQUESTS.txt").read_text(encoding="utf-8")
    assert "MaxStress|1|Stress|vonMises|" in req and "Accel" not in req   # CURVE는 요청하지 않는다
    table = {r["name"]: r["predicted"] for r in jd["result"]["response_table"]}
    assert table == {"MaxStress": 100.0, "AccelPeak": 20.25, "AccelMin": 0.0, "Missing": None, "Disp": None}
    assert jd["result"]["response_errors"] == {"Missing": "SERIES_MISSING", "Disp": "NOT_DEFINED"}
    warn = [w for w in jd["warnings"] if w["code"] == "RESPONSE_NO_VALUE"]
    assert len(warn) == 1 and "Missing" in warn[0]["message"] and "커브 계열 없음" in warn[0]["message"]


def test_v3_s17_4_curve_only_skips_tcl(predict_env, tmp_path, fake_record):
    env = _env(predict_env, tmp_path)
    ps = env.param_set()
    env.set_responses(ps["id"], [{"name": "AccelPeak", "unit": "g", "spec": {**CURVE_MAX, "stat": "ABSMAX"}}, *KEEP])
    n = len(_tcl_calls(fake_record))
    j = env.submit("PREDICT", VALUES)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    assert len(_tcl_calls(fake_record)) == n                                # TCL 미실행
    R = env.predict_dir(j["id"]) / "RESULT"
    assert not (R / "H3D_REQUESTS.txt").exists() and not (R / TCL_NAME).exists()
    assert _csv(env.predict_dir(j["id"]) / "responses_pred.csv") == [["name", "value"], ["AccelPeak", "20.25"], ["Disp", ""]]
    assert "RESPONSE_NO_VALUE" not in [w["code"] for w in env.job(j["id"])["warnings"]]


def test_v3_s17_4_curve_silent_in_td_and_pv_paths():
    from physicsai_core.stage4_predict import responses as resp_mod
    from physicsai_worker.steps.response_tcl import warn_reasons

    class Ctx:
        def __init__(self) -> None:
            self.warnings: list[tuple[str, str]] = []

        def add_warning(self, code: str, message: str) -> None:
            self.warnings.append((code, message))

    rows = [{"name": "A", "spec": CURVE_MAX}, {"name": "B", "spec": H3D}]
    reqs, skipped = resp_mod.build_requests(rows)
    values, reasons = resp_mod.pick_values(rows, resp_mod.parse_responses_text("RESP:B_MIN=1\nRESP:B_MAX=2\n"), skipped=skipped)
    assert [r.name for r in reqs] == ["B"] and values == {"A": None, "B": 2.0} and reasons == {"A": "CURVE"}
    ctx = Ctx()
    warn_reasons(ctx, reasons)
    assert ctx.warnings == []                                               # ①-6·PV: CURVE는 경고 없이 비움


# ---- PB_RESP_EXTRACT ---------------------------------------------------------------------------------------------


def _done_batch(env, ps_id: str) -> str:
    pj = env.submit("PREDICT_BATCH", {"param_set_id": ps_id, "multi_execution": 2,
                                      "source": {"kind": "table", "text": "THK_1,N_RIB\n2.5,3\n3.0,4\n3.5,5\n"}})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj["id"])
    for _ in range(3):
        assert env.w.run_once_slot() == "SUCCEEDED"
    bid = pj["params"]["batch_id"]
    assert env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()["status"] == "DONE"
    return bid


def test_v3_s17_4_pb_resp_extract_e2e(predict_env, tmp_path, fake_record):
    env = _env(predict_env, tmp_path)
    ps = env.param_set()
    r = env.c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW,
                  json={"responses": [{"name": "MaxStress", "unit": "MPa", "spec": H3D}, *KEEP]})
    assert r.status_code == 200, r.text
    bid = _done_batch(env, ps["id"])
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert [x["responses"] for x in b["rows"]] == [{"MaxStress": 100.0, "Disp": None}] * 3
    # 정의 추가(H3D CornerStress + CURVE) 뒤 다시 추출. run 2는 결과 h3d를 2개로 만들어 건너뛰게 한다
    rows = [{"name": "MaxStress", "unit": "MPa", "spec": H3D},
            {"name": "CornerStress", "unit": "MPa", "spec": {**H3D, "datatype": "CornerStress", "component": ""}},
            {"name": "AccelPeak", "unit": "g", "spec": CURVE_MAX}, *KEEP]
    assert env.c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": rows}).status_code == 200
    run_dirs = [env.predict_dir(x["job_id"]) for x in b["rows"]]
    old = (run_dirs[0] / "RESULT" / "RESPONSES.txt").read_text(encoding="utf-8")
    (run_dirs[1] / "RESULT" / "extra_pred.h3d").write_bytes(b"x")
    r = env.c.post(f"{API}/predict-batches/{bid}/extract-responses", headers=PW)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["job_type"] == "PB_RESP_EXTRACT" and job["params"]["performances"] == ["MaxStress", "CornerStress"]
    assert job["params"]["param_set_id"] == ps["id"]
    again = env.c.post(f"{API}/predict-batches/{bid}/extract-responses", headers=PW)   # Study당 진행 중 1개
    assert again.status_code == 409 and again.json()["detail"]["code"] == "STUDY_JOB_BUSY"
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(job["id"])
    jd = env.job(job["id"])
    assert [s["step_key"] for s in jd["steps"]] == ["PX_PREP", "RESPONSE_EXTRACT_RUNS", "PX_TABLE"]
    assert jd["result"]["summary"] == {"targets": 2, "extracted": 2, "failed": 0}
    assert "RESP_H3D_AMBIGUOUS" in [w["code"] for w in jd["warnings"]]
    new = (run_dirs[0] / "RESULT" / "RESPONSES.txt").read_text(encoding="utf-8")
    assert "CornerStress_MAX" in new and "CornerStress" not in old
    backups = [p for p in (env.sroot / "_backup").rglob("RESPONSES.txt")]
    assert any(p.read_text(encoding="utf-8") == old for p in backups)   # 옛 RESPONSES는 _backup으로
    assert any(p.name == "responses_pred.csv" for p in (env.sroot / "_backup").rglob("*"))
    pred = _csv(run_dirs[0] / "responses_pred.csv")
    assert pred[0] == ["name", "value"] and [x[0] for x in pred[1:]] == ["MaxStress", "CornerStress", "AccelPeak", "Disp"]
    assert pred[3] == ["AccelPeak", "20.25"]
    b2 = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    resp = [x["responses"] for x in b2["rows"]]
    assert resp[0]["CornerStress"] == 110.0 and resp[0]["AccelPeak"] == 20.25 and resp[0]["MaxStress"] == 100.0
    assert "Disp" not in resp[0]                                            # 수치만
    assert resp[1] == {"MaxStress": 100.0, "Disp": None}                     # 건너뛴 run은 그대로
    # 하위 PREDICT의 result.response_table은 갱신하지 않는다(R-5)
    assert [x["name"] for x in env.job(b["rows"][0]["job_id"])["result"]["response_table"]] == ["MaxStress", "Disp"]


def test_v3_s17_4_pb_resp_extract_api_errors(predict_env, tmp_path):
    env = _env(predict_env, tmp_path)
    ps = env.param_set()
    env.set_responses(ps["id"], [{"name": "MaxStress", "unit": "MPa", "spec": H3D}, *KEEP])
    bid = _done_batch(env, ps["id"])
    # 409 BATCH_NOT_DONE
    nb, _job = env.make_batch(ps["id"], "THK_1,N_RIB\n3.0,4\n")
    r = env.c.post(f"{API}/predict-batches/{nb}/extract-responses", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "BATCH_NOT_DONE"
    assert env.c.post(f"{API}/predict-batches/nope/extract-responses", headers=PW).status_code == 404
    # 409 BATCH_OWNED_BY_OPT(진행 중 최적화 소유) → 끝난 최적화면 허용 대상
    oid = str(uuid.uuid4())
    env.sql("insert into surrogate_opts(id, study_id, opt_no, param_set_id, model_id, input_kind, settings, status, dir_rel,"
            " created_by, created_by_name) values (:o,:s,1,:p,:m,'assembly',cast(:st as jsonb),'VERIFYING','05_opt/x','u','u')",
            o=oid, s=env.sid, p=ps["id"], m=env.model_id, st=json.dumps({"objective": {"metric": "curve:max"}}))
    env.sql("insert into surrogate_opt_iters(opt_id, iter_no, kind, batch_id) values (:o,0,'EXPLORE',:b)", o=oid, b=bid)
    r = env.c.post(f"{API}/predict-batches/{bid}/extract-responses", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "BATCH_OWNED_BY_OPT"
    env.sql("update surrogate_opts set status='DONE' where id=:o", o=oid)
    # 422 NO_H3D_PERFORMANCE
    env.set_responses(ps["id"], [{"name": "AccelPeak", "unit": "g", "spec": CURVE_MAX}, *KEEP])
    r = env.c.post(f"{API}/predict-batches/{bid}/extract-responses", headers=PW)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "NO_H3D_PERFORMANCE"
    env.set_responses(ps["id"], [{"name": "MaxStress", "unit": "MPa", "spec": H3D}, *KEEP])
    assert env.c.post(f"{API}/predict-batches/{bid}/extract-responses", headers=P).status_code in (401, 403)  # 쓰기 헤더 없음
    r = env.c.post(f"{API}/predict-batches/{bid}/extract-responses", headers=PW)
    assert r.status_code == 201, r.text                                      # 끝난 최적화 소유 배치는 허용


def test_v3_s17_4_pb_resp_extract_feature_unavailable(predict_env, tmp_path):
    env = predict_env(commands={"response_extract": None}, folder="nofeat")
    ps = env.param_set()
    env.set_responses(ps["id"], [{"name": "MaxStress", "unit": "MPa", "spec": H3D}, *KEEP])
    nb, _job = env.make_batch(ps["id"], "THK_1,N_RIB\n3.0,4\n")
    env.sql("update predict_batches set status='DONE' where id=:b", b=nb)
    r = env.c.post(f"{API}/predict-batches/{nb}/extract-responses", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEATURE_NOT_AVAILABLE"
    assert os.path.isdir(env.sroot)
