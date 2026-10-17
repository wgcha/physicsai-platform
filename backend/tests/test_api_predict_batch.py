"""④ 템플릿 예측·일괄 예측(DOE) API(phase3 §14 S9, D3-49): V3-S9-2·6·9(API)·10·11·12·17·18(API).

워커 step(BP_PREP·BP_GEN·BP_ENQUEUE)은 Worker 몫이라 여기서는 저장소 함수로 생성 결과·하위 종료를 흉내 낸다
(`_gen_done`·`_end` — 종료 훅·알림은 실제 경로 `job_end._side_effects_on_end`·`notify_job`).
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
from pathlib import Path

import httpx
from sqlalchemy import text

from helpers_api import AW, P, PW, _job, _model, _sid
from physicsai_test_support import API, H, TPL_TEXT, make_assem_files, make_param_set_folder

GW = H("tok-general", write=True)
PW2 = H("tok-power2", write=True)
TABLE = "THK_1\tN_RIB\n3.0\t4\n2.5\t5\n4.0\t7\n"


@contextlib.contextmanager
def _client(settings_dict, engine, fake_dashboard, **over):
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    for k, v in over.items():
        d[k] = {**(d.get(k) or {}), **v}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    with TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))),
                    base_url="http://127.0.0.1") as c:
        yield c, lc


def _mesh_only_folder(root: Path) -> Path:
    d = make_param_set_folder(root)
    os.rename(d / "radioss_assem", root / f"_moved_{d.name}")
    return d


def _setup(c, w, ai: Path, name="S1", *, mesh_only=False):
    """Study + Final 모델 + 현재 세트(assembly 또는 mesh_only). (sid, mid, ps)."""
    sid = _sid(c, name)
    mid = _model(c, w, sid, ai / name / "00_inbox")
    assert c.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": mid}).status_code == 200
    folder = _mesh_only_folder(ai / name / "00_inbox") if mesh_only else make_param_set_folder(ai / name / "00_inbox")
    r = c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(folder)})
    assert r.status_code == 201, r.text
    return sid, mid, r.json()


def _batch(c, sid, source=None, me=2, **extra):
    return _job(c, sid, "PREDICT_BATCH", {"multi_execution": me, "source": source or {"kind": "table", "text": TABLE}, **extra})


def _gen_done(engine, ai: Path, folder: str, bid: str, *, failed: tuple[int, ...] = ()) -> list[dict]:
    """BP_GEN·BP_ENQUEUE 흉내: run 생성 결과 기록 → 하위 PREDICT 대기열 등록 → 부모 SUCCEEDED."""
    from physicsai_core.db.repositories import predict_batches as pb_repo

    with engine.begin() as conn:
        b = pb_repo.get(conn, bid)
        for r in pb_repo.runs(conn, bid):
            if r["doe_no"] in failed:
                pb_repo.set_run(conn, bid, r["doe_no"], gen_state="FAILED", gen_code="EXIT_NONZERO", gen_message="m1 실패")
            else:
                pb_repo.set_run(conn, bid, r["doe_no"], gen_state="DONE")
        kids = pb_repo.enqueue_children(conn, bid, batch_dir=str(ai / folder / b["dir_rel"]))
    _end(engine, b["job_id"], "SUCCEEDED")
    return kids


def _end(engine, job_id: str, state: str, result: dict | None = None, failure_code: str | None = None) -> None:
    """작업 종료 흉내(lease 해제와 같은 부수효과·알림 순서)."""
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import notifications as notif_repo
    from physicsai_core.db.repositories.job_end import _side_effects_on_end

    with engine.begin() as conn:
        j = jobs_repo.get_job(conn, job_id)
        res = {**(j["result"] or {}), **(result or {})}
        conn.execute(text("update jobs set state=:s, holds_slot=false, queue_seq=null, finished_at=now(), started_at=now() - interval '2 minutes',"
                          " result=cast(:r as jsonb), failure_code=:fc where id=:i"),
                     {"s": state, "r": json.dumps(res), "fc": failure_code, "i": job_id})
        _side_effects_on_end(conn, {**j, "result": res}, state)
        notif_repo.notify_job(conn, job_id, {"SUCCEEDED": "JOB_SUCCEEDED", "FAILED": "JOB_FAILED",
                                             "CANCELED": "JOB_CANCELED"}[state])


def _notifs(engine, user="u-power"):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(
            "select n.event, n.job_id, n.title from notifications n join jobs j on j.id = n.job_id"
            " where n.user_id=:u and j.job_type <> 'MODEL_REGISTER' order by n.seq"), {"u": user})]


# ---- V3-S9-2 템플릿 등록(mesh_only) ------------------------------------------------------------------------------


def test_v3_s9_2_register_mesh_only_and_export_name(client, loaded_config):
    s = loaded_config.settings
    ai, imp = Path(s.storage.ai_root), Path(s.storage.allowed_import_roots[0])
    sid = _sid(client)
    # 폴더 등록: radioss_assem/ 없음 → mesh_only, assem_rel·starter_name null
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(_mesh_only_folder(ai / "S1" / "00_inbox"))})
    assert r.status_code == 201, r.text
    ps = r.json()
    assert (ps["input_kind"], ps["assem_rel"], ps["starter_name"], ps["warnings"]) == ("mesh_only", None, None, [])
    assert not (ai / "S1" / "04_params" / ps["id"] / "radioss_assem").exists()
    assert client.get(f"{API}/param-sets/{ps['id']}", headers=P).json()["input_kind"] == "mesh_only"
    # 폴더 등록(assembly)은 그대로
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(make_param_set_folder(ai / "S1" / "00_inbox"))})
    assert r.json()["input_kind"] == "assembly" and r.json()["assem_rel"] == f"04_params/{r.json()['id']}/radioss_assem/"
    assert r.json()["starter_name"] == "model0_0000.rad"
    # discover: 조립 폴더 0개 → notes MESH_ONLY, 등록 = mesh_only
    proj = imp / "proj0"
    (proj / "01_CAD").mkdir(parents=True)
    (proj / "simlab_parametered_mesh.tpl").write_text(TPL_TEXT.replace('"EPS_mesh_0000.rad"', '"cushion_mesh.rad"'),
                                                       encoding="utf-8")
    (proj / "01_CAD" / "bracket.x_t").write_text("CAD")
    d = client.post(f"{API}/studies/{sid}/param-sets/discover", headers=PW, json={"path": str(proj)}).json()
    notes = {n["code"]: n["message"] for n in d["notes"]}
    assert d["problems"] == [] and d["radioss_assem"] == []
    assert notes["MESH_ONLY"].startswith("조립 폴더 없음 — m1 메시로 바로 예측합니다")
    assert "SIMLAB_EXPORT_NAME" in notes and "cushion_mesh.rad" in notes["SIMLAB_EXPORT_NAME"]
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(proj), "mode": "discover"})
    assert r.status_code == 201, r.text
    assert r.json()["input_kind"] == "mesh_only" and [w["code"] for w in r.json()["warnings"]] == ["SIMLAB_EXPORT_NAME"]
    # 후보 1개 + 생략 → assembly, 명시적 null → mesh_only, 없는 후보 이름 → CHOICE_INVALID
    make_assem_files(proj / "RADIOSS_ASSEM")
    body = {"path": str(proj), "mode": "discover"}
    assert client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json=body).json()["input_kind"] == "assembly"
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={**body, "choice": {"radioss_assem": None}})
    assert r.status_code == 201 and r.json()["input_kind"] == "mesh_only" and r.json()["starter_name"] is None
    src = json.loads((ai / "S1" / "04_params" / r.json()["id"] / "source.json").read_text(encoding="utf-8"))
    assert src["discovered"]["radioss_assem"] is None
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={**body, "choice": {"radioss_assem": "nope"}})
    assert r.status_code == 422 and {p["code"] for p in r.json()["detail"]["problems"]} == {"CHOICE_INVALID"}


def test_v3_s9_2_from_train_requires_assembly(tmp_path):
    from physicsai_core.stage4_predict import param_sets as ps_mod

    d = _mesh_only_folder(tmp_path)
    kw = {"max_samples": 100, "max_total_bytes": 10 ** 9, "starter_glob": "*_0000.rad"}
    assert ps_mod.validate_folder(str(d), **kw).input_kind == "mesh_only"
    f = ps_mod.validate_folder(str(d), allow_mesh_only=False, **kw)
    assert [p["code"] for p in f.problems] == ["ASSEM_MISSING"]


# ---- A: mesh_only 단일 예측 params(template_kind) --------------------------------------------------------------------


def test_v3_s9_predict_template_kind_and_mesh_only_gate(settings_dict, engine, fake_dashboard, worker_factory):
    vals = {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "manual"}
    # include TCL 자원이 없으면 assembly는 409, mesh_only는 geom_update만 있으면 된다
    with _client(settings_dict, engine, fake_dashboard, resources={"hypermesh_include_tcl": ""}) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, ps = _setup(c, worker_factory(), ai, "MO", mesh_only=True)
        st = c.get(f"{API}/status", headers=P).json()["features"]
        assert st["predict_mesh_only"]["enabled"] is True and st["predict_parametric"]["enabled"] is False
        r = _job(c, sid, "PREDICT", vals)
        assert r.status_code == 201, r.text
        assert r.json()["params"]["template_kind"] == "mesh_only" and r.json()["params"]["param_set_id"] == ps["id"]
        asm = c.post(f"{API}/studies/{sid}/param-sets", headers=PW,
                     json={"path": str(make_param_set_folder(ai / "MO" / "00_inbox"))}).json()
        r = _job(c, sid, "PREDICT", {**vals, "param_set_id": asm["id"]})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"
    with _client(settings_dict, engine, fake_dashboard, commands={"geom_update": None}) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "MG", mesh_only=True)
        r = _job(c, sid, "PREDICT", vals)
        assert r.status_code == 409 and r.json()["detail"]["template"] == "geom_update"
        r = _batch(c, sid)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"


# ---- 생성 검증(조합 3방식·상한·사전조건·권한) ------------------------------------------------------------------------


def test_v3_s9_batch_create_validation(client, loaded_config, worker_factory):
    s = loaded_config.settings
    ai = Path(s.storage.ai_root)
    sid = _sid(client)
    r = _batch(client, sid)
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["PARAM_SET"]
    client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(make_param_set_folder(ai / "S1" / "00_inbox"))})
    r = _batch(client, sid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FINAL_MODEL_REQUIRED"
    mid = _model(client, worker_factory(), sid, ai / "S1" / "00_inbox")
    client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": mid})
    cap = s.train_data.max_multi_execution
    assert client.get(f"{API}/status", headers=P).json()["limits"]["configured"]["max_multi_execution"] == cap
    for params, code in [
        ({"multi_execution": 2, "source": {"kind": "sobol", "count": 3}}, "INVALID_PARAMS"),
        ({"multi_execution": 2, "source": {"kind": "lhs"}}, "INVALID_PARAMS"),
        ({"multi_execution": 2, "source": {"kind": "table", "text": TABLE, "x": 1}}, "INVALID_PARAMS"),
        ({"multi_execution": 0, "source": {"kind": "table", "text": TABLE}}, "INVALID_PARAMS"),
        ({"multi_execution": cap + 1, "source": {"kind": "table", "text": TABLE}}, "INVALID_PARAMS"),
        ({"source": {"kind": "table", "text": TABLE}}, "INVALID_PARAMS"),
        ({"multi_execution": 2, "source": {"kind": "table", "text": "THK_1,BAD\n1,2\n"}}, "BATCH_SOURCE_INVALID"),
        ({"multi_execution": 2, "source": {"kind": "lhs", "count": s.predict_batch.max_runs + 1}}, "BATCH_SOURCE_INVALID"),
        ({"multi_execution": 2, "source": {"kind": "lhs", "count": 3, "ranges": {"THK_1": [5, 2]}}}, "BATCH_SOURCE_INVALID"),
    ]:
        r = _job(client, sid, "PREDICT_BATCH", params)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, (params, r.text)
    r = _batch(client, sid, {"kind": "table", "text": "THK_1\tN_RIB\n1\tx\n"})
    assert [(p["code"], p.get("row")) for p in r.json()["detail"]["problems"]] == [("TABLE_VALUE", 1)]
    r = _batch(client, sid, {"kind": "train_doe", "doe_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DOE_NOT_READY"
    # 권한: general 403, PREDICT에 batch_run(워커 전용) 422
    assert _job(client, sid, "PREDICT_BATCH", {"multi_execution": 1, "source": {"kind": "table", "text": TABLE}},
                token="tok-general").status_code == 403
    r = _job(client, sid, "PREDICT", {"input_mode": "prepared", "input_path": str(ai), "batch_run": {"batch_id": "x", "doe_no": 1}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"


# ---- V3-S9-6 미리보기 = 생성 후 run 행, batch_no 연번 ------------------------------------------------------------------


def test_v3_s9_6_preview_matches_runs(client, loaded_config, worker_factory, engine):
    from physicsai_core.db.repositories import predict_batches as pb_repo

    ai = Path(loaded_config.settings.storage.ai_root)
    sid, mid, ps = _setup(client, worker_factory(), ai)
    src = {"kind": "lhs", "count": 6, "seed": 7, "ranges": {"THK_1": [1.0, 6.0]}}
    r = client.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW, json={"source": src})
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["input_kind"] == "assembly" and pv["count"] == 6 and pv["problems"] == [] and pv["estimate_min"] is None
    assert [x["run_key"] for x in pv["rows"]] == [f"run__{i:05d}" for i in range(1, 7)]
    assert any(x["out_of_range"] == ["THK_1"] for x in pv["rows"])            # 학습 범위 밖 허용
    assert all(float(x["applied_values"]["N_RIB"]).is_integer() for x in pv["rows"])
    # 문제는 200 problems
    bad = client.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW,
                      json={"param_set_id": ps["id"], "source": {"kind": "table", "text": "THK_1\n1\n"}}).json()
    assert bad["rows"] == [] and [p["code"] for p in bad["problems"]] == ["TABLE_HEADER"]
    assert client.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW,
                       json={"source": {"kind": "nope"}}).status_code == 422
    # 생성: 미리보기 행 = predict_batch_runs, params에 batch_id·batch_no·출처 요약(표 본문 없음)
    r = _batch(client, sid, src, me=3)
    assert r.status_code == 201, r.text
    job = r.json()
    p = job["params"]
    assert (p["batch_no"], p["template_kind"], p["multi_execution"], p["model_id"], p["param_set_id"]) == (1, "assembly", 3, mid, ps["id"])
    assert p["source"] == {"kind": "lhs", "count": 6, "seed": 7, "ranges": {"THK_1": [1.0, 6.0], "N_RIB": [2.0, 8.0]}}
    assert job["batch"] == {"id": p["batch_id"], "label": "B-001", "doe_no": None}
    with engine.connect() as conn:
        b = pb_repo.get(conn, p["batch_id"])
        runs = pb_repo.runs(conn, p["batch_id"])
    assert (b["status"], b["dir_rel"], b["job_id"], b["run_count"], b["source_kind"]) == ("GENERATING", "04_batch/B-001", job["id"], 6, "LHS")
    assert [{k: x[k] for k in ("doe_no", "run_key", "values", "applied_values", "out_of_range")} for x in runs] == pv["rows"]
    assert all(x["input_rel"] == f"{x['run_key']}/m_3" for x in runs)
    # 같은 Study 활성 PREDICT_BATCH는 1개(기존 409), 끝나면 batch_no 2 → B-002, 표 본문은 params에 없음
    assert _batch(client, sid).status_code == 409
    _end(engine, job["id"], "FAILED", failure_code="EXIT_NONZERO")
    r = _batch(client, sid, {"kind": "table", "text": TABLE})
    assert r.status_code == 201 and r.json()["params"]["batch_no"] == 2
    assert r.json()["params"]["source"] == {"kind": "table", "row_count": 3}
    lst = client.get(f"{API}/studies/{sid}/predict-batches", headers=P).json()
    assert [x["label"] for x in lst] == ["B-002", "B-001"]
    # D3-53 "실행 목록": 템플릿·입력 생성·예측 집계
    assert lst[0]["param_set"]["id"] == p["param_set_id"] and set(lst[0]["param_set"]) == {"id", "label"}
    assert lst[0]["gen"] == {"total": 3, "done": 0, "failed": 0, "running": 0, "waiting": 3}
    assert lst[0]["predict"] == {"running": 0, "queued": 0, "succeeded": 0, "failed": 0, "canceled": 0}


# ---- V3-S9-9·10·11·12: 하위 짝짓기·알림·종료 훅·CSV·권한 --------------------------------------------------------------


def test_v3_s9_10_12_children_hook_notice_detail_csv(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, ps = _setup(client, worker_factory(), ai)
    job = _batch(client, sid).json()
    bid = job["params"]["batch_id"]
    kids = _gen_done(engine, ai, "S1", bid, failed=(2,))
    assert [k["params"]["batch_run"]["doe_no"] for k in kids] == [1, 3]
    assert kids[0]["params"]["input_path"] == str(ai / "S1" / "04_batch" / "B-001" / "run__00001" / "m_3")
    # 작업 목록: 하위 PREDICT에 batch{label, doe_no}
    lst = {j["id"]: j for j in client.get(f"{API}/jobs", headers=P, params={"study_id": sid}).json()}
    assert lst[kids[1]["id"]]["batch"] == {"id": bid, "label": "B-001", "doe_no": 3}
    d = client.get(f"{API}/predict-batches/{bid}", headers=H("tok-general")).json()       # 조회 = 로그인
    assert (d["status"], d["gen"], d["predict"]["queued"]) == ("PREDICTING", {"total": 3, "done": 2, "failed": 1, "running": 0, "waiting": 0}, 2)
    assert [(r["doe_no"], r["state"], r["code"]) for r in d["rows"]] == [(1, "QUEUED", None), (2, "GEN_FAILED", "EXIT_NONZERO"), (3, "QUEUED", None)]
    assert d["can_cancel"] is False and d["can_retry_failed"] is False                    # general
    table = [{"name": "MaxStress", "unit": "MPa", "predicted": 152.3}, {"name": "Disp", "unit": "mm", "predicted": None}]
    _end(engine, kids[0]["id"], "SUCCEEDED", {"response_table": table})
    assert [n["event"] for n in _notifs(engine)] == []                                      # 하위 알림 없음
    _end(engine, kids[1]["id"], "FAILED", failure_code="EXIT_NONZERO")
    notes = _notifs(engine)
    assert [(n["event"], n["job_id"], n["title"]) for n in notes] == [
        ("PREDICT_BATCH_DONE", job["id"], "일괄 예측 B-001 완료 — 완료 1 · 실패 2")]
    d = client.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert d["status"] == "DONE" and d["finished_at"] and d["label"] == "B-001" and d["input_kind"] == "assembly"
    assert d["param_set"] == {"id": ps["id"], "label": None} and d["model"]["name"].endswith(" v1")
    assert d["parameters"] == ["THK_1", "N_RIB"] and [x["name"] for x in d["responses"]] == ["MaxStress", "Disp"]
    row1 = d["rows"][0]
    assert (row1["run_key"], row1["state"], row1["job_id"], row1["responses"]) == ("run__00001", "SUCCEEDED", kids[0]["id"],
                                                                                   {"MaxStress": 152.3, "Disp": None})
    assert row1["folder"].endswith(os.path.join("04_batch", "B-001", "run__00001")) and row1["values"] == {"THK_1": 3.0, "N_RIB": 4.0}
    assert d["rows"][2]["state"] == "FAILED" and d["rows"][2]["code"] == "EXIT_NONZERO"
    assert d["dir"].endswith(os.path.join("S1", "04_batch", "B-001"))
    # CSV: BOM·헤더·행
    r = client.get(f"{API}/predict-batches/{bid}/table.csv", headers=P)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and r.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0] == ["doe_no", "run_key", "folder", "THK_1", "N_RIB", "MaxStress", "Disp", "state"]
    assert rows[1][:2] == ["1", "run__00001"] and rows[1][3:] == ["3.0", "4.0", "152.3", "", "SUCCEEDED"]
    assert [x[-1] for x in rows[1:]] == ["SUCCEEDED", "GEN_FAILED", "FAILED"]
    # 404
    for u in ("", "/table.csv", "/curves"):
        r = client.get(f"{API}/predict-batches/00000000-0000-0000-0000-000000000000{u}", headers=P)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "BATCH_NOT_FOUND"


def test_v3_s9_10_parent_failure_notifies_job_failed(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, _ps = _setup(client, worker_factory(), ai)
    job = _batch(client, sid).json()
    _end(engine, job["id"], "FAILED", failure_code="OUTPUT_MISSING")
    assert [n["event"] for n in _notifs(engine)] == ["JOB_FAILED"]
    assert client.get(f"{API}/predict-batches/{job['params']['batch_id']}", headers=P).json()["status"] == "FAILED"


# ---- V3-S9-11 retry-failed·하위 retry ------------------------------------------------------------------------------


def test_v3_s9_11_retry_failed(client, loaded_config, worker_factory, engine):
    from physicsai_core.db.repositories import predict_batches as pb_repo

    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, _ps = _setup(client, worker_factory(), ai)
    job = _batch(client, sid).json()
    bid = job["params"]["batch_id"]
    r = client.post(f"{API}/predict-batches/{bid}/retry-failed", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "BATCH_ACTIVE"              # 부모 대기 중
    kids = _gen_done(engine, ai, "S1", bid, failed=(2,))
    _end(engine, kids[0]["id"], "SUCCEEDED", {"response_table": []})
    _end(engine, kids[1]["id"], "FAILED", failure_code="EXIT_NONZERO")
    assert client.get(f"{API}/predict-batches/{bid}", headers=P).json()["can_retry_failed"] is True
    assert client.post(f"{API}/predict-batches/{bid}/retry-failed", headers=GW).status_code == 403
    r = client.post(f"{API}/predict-batches/{bid}/retry-failed", headers=PW)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["parent_job_id"] and len(out["retried_job_ids"]) == 1
    parent = client.get(f"{API}/jobs/{out['parent_job_id']}", headers=P).json()
    assert parent["job_type"] == "PREDICT_BATCH" and parent["params"] == {"batch_id": bid, "batch_no": 1}
    child = client.get(f"{API}/jobs/{out['retried_job_ids'][0]}", headers=P).json()
    assert child["retry_of_job_id"] == kids[1]["id"] and child["params"]["batch_run"]["doe_no"] == 3
    with engine.connect() as conn:
        b = pb_repo.get(conn, bid)
        runs = {r["doe_no"]: r for r in pb_repo.runs(conn, bid)}
    assert b["job_id"] == out["parent_job_id"] and b["status"] == "GENERATING" and b["finished_at"] is None
    assert (runs[2]["gen_state"], runs[2]["gen_code"]) == ("PENDING", None) and runs[3]["predict_job_id"] == child["id"]
    d = client.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert d["job_id"] == out["parent_job_id"] and [r["state"] for r in d["rows"]] == ["SUCCEEDED", "GEN_PENDING", "QUEUED"]
    assert client.post(f"{API}/predict-batches/{bid}/retry-failed", headers=PW).json()["detail"]["code"] == "BATCH_ACTIVE"
    # 재생성 → 새 하위, 재시도 하위 종료 → 이전 하위 무시하고 완료 판정, 알림 1건
    kids2 = _gen_done(engine, ai, "S1", bid)
    assert [k["params"]["batch_run"]["doe_no"] for k in kids2] == [2]
    _end(engine, child["id"], "SUCCEEDED", {"response_table": [{"name": "MaxStress", "predicted": 1.5}]})
    _end(engine, kids2[0]["id"], "SUCCEEDED", {"response_table": [{"name": "MaxStress", "predicted": 2.5}]})
    d = client.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert d["status"] == "DONE" and [r["responses"]["MaxStress"] if r["responses"] else None for r in d["rows"]] == [None, 2.5, 1.5]
    # D3-53 실행 목록: 완료 배치 행의 첫 응답 요약(값 있는 완료 run의 최소~최대)
    (row,) = client.get(f"{API}/studies/{sid}/predict-batches", headers=P).json()
    assert row["response_summary"] == {"name": "MaxStress", "unit": "MPa", "min": 1.5, "max": 2.5, "count": 2}
    assert row["status"] == "DONE" and row["predict"]["succeeded"] == 3
    assert [n["title"] for n in _notifs(engine) if n["event"] == "PREDICT_BATCH_DONE"] == [
        "일괄 예측 B-001 완료 — 완료 1 · 실패 2", "일괄 예측 B-001 완료 — 완료 3 · 실패 0"]
    r = client.post(f"{API}/predict-batches/{bid}/retry-failed", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_NOT_RETRYABLE"
    # 행 1개 재시도(기존 /jobs/{id}/retry)도 predict_job_id 갱신·PREDICTING
    _end_child = d["rows"][0]["job_id"]
    with engine.begin() as conn:
        conn.execute(text("update jobs set state='FAILED', failure_code='EXIT_NONZERO' where id=:i"), {"i": _end_child})
    r = client.post(f"{API}/jobs/{_end_child}/retry", headers=PW, json={})
    assert r.status_code == 201, r.text
    d = client.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert d["status"] == "PREDICTING" and d["rows"][0]["job_id"] == r.json()["id"] and d["rows"][0]["responses"] is None


# ---- V3-S9-8(API) 일괄 취소 -----------------------------------------------------------------------------------------


def test_v3_s9_cancel_batch(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, _ps = _setup(client, worker_factory(), ai)
    job = _batch(client, sid).json()
    bid = job["params"]["batch_id"]
    # 부모 대기 중 취소
    assert client.post(f"{API}/predict-batches/{bid}/cancel", headers=GW).status_code == 403
    assert client.post(f"{API}/predict-batches/{bid}/cancel", headers=PW2).status_code == 403      # 등록자 아님
    r = client.post(f"{API}/predict-batches/{bid}/cancel", headers=PW)
    assert r.status_code == 202 and r.json()["status"] == "CANCELED"
    assert client.get(f"{API}/jobs/{job['id']}", headers=P).json()["state"] == "CANCELED"
    assert client.post(f"{API}/predict-batches/{bid}/cancel", headers=PW).status_code == 202   # 멱등
    # 예측 중 취소: 대기 하위 CANCELED, 실행 중 하위는 취소 요청, 완료 알림 없음
    job = _batch(client, sid).json()
    bid = job["params"]["batch_id"]
    kids = _gen_done(engine, ai, "S1", bid)
    with engine.begin() as conn:
        conn.execute(text("update jobs set state='RUNNING', holds_slot=true, queue_seq=null, started_at=now() where id=:i"), {"i": kids[0]["id"]})
    r = client.post(f"{API}/predict-batches/{bid}/cancel", headers=AW)                    # 관리자
    assert r.status_code == 202 and r.json()["can_cancel"] is False
    k0 = client.get(f"{API}/jobs/{kids[0]['id']}", headers=P).json()
    assert k0["state"] == "RUNNING" and k0["cancel_requested"] is True
    assert {client.get(f"{API}/jobs/{k['id']}", headers=P).json()["state"] for k in kids[1:]} == {"CANCELED"}
    _end(engine, kids[0]["id"], "CANCELED")
    assert client.get(f"{API}/predict-batches/{bid}", headers=P).json()["status"] == "CANCELED"
    assert [n["event"] for n in _notifs(engine)] == ["JOB_CANCELED"]                      # 첫 부모만(하위·완료 없음)


# ---- V3-S9-18(API) 커브 ---------------------------------------------------------------------------------------------


def _curve(engine, ai: Path, folder: str, sid: str, job_id: str, series: list[dict]) -> None:
    from physicsai_core.db.repositories import artifacts as artifacts_repo

    rel = f"04_predict/{job_id}/curve.json"
    p = ai / folder / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"file": "a.xy", "series": series, "note": ""}), encoding="utf-8")
    with engine.begin() as conn:
        aid = artifacts_repo.insert(conn, study_id=sid, job_id=job_id, kind="CURVE_JSON", rel_path=rel, size=p.stat().st_size,
                                    sha256=None, content_type="application/json")
    _end(engine, job_id, "SUCCEEDED", {"curve_artifact_id": aid})


def test_v3_s9_18_curves(settings_dict, engine, fake_dashboard, worker_factory):
    from physicsai_api.services.predict_batches import downsample

    with _client(settings_dict, engine, fake_dashboard, predict_batch={"curve_max_runs": 2}) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "CV")
        text4 = "THK_1,N_RIB\n3,4\n3,4\n3,4\n3,4\n"
        job = _batch(c, sid, {"kind": "table", "text": text4}).json()
        bid = job["params"]["batch_id"]
        kids = _gen_done(engine, ai, "CV", bid)
        xs = [float(i) for i in range(3000)]
        ys = [0.0] * 3000
        ys[1234], ys[2345] = 99.0, -77.0
        _curve(engine, ai, "CV", sid, kids[0]["id"], [{"name": "Node 100 / X", "x": xs, "y": ys},
                                                       {"name": "Node 200 / Y", "x": [0, 1], "y": [1, 2]}])
        _curve(engine, ai, "CV", sid, kids[1]["id"], [{"name": "Node 200 / Y", "x": [0, 1, 2], "y": [3, 4, 5]}])
        _curve(engine, ai, "CV", sid, kids[2]["id"], [{"name": "Node 100 / X", "x": [0, 1], "y": [5, 6]}])  # run 상한 밖
        # kids[3]은 미완료 → 제외
        r = c.get(f"{API}/predict-batches/{bid}/curves", headers=P, params={"max_points": 200})
        assert r.status_code == 200, r.text
        cv = r.json()
        assert cv["names"] == ["Node 100 / X", "Node 200 / Y"] and cv["name"] == "Node 100 / X"
        assert cv["truncated"] is True and cv["downsampled"] is True
        assert [s["doe_no"] for s in cv["series"]] == [1]
        s0 = cv["series"][0]
        assert len(s0["x"]) <= 200 and 99.0 in s0["y"] and -77.0 in s0["y"] and s0["x"][0] == 0.0 and s0["x"][-1] == 2999.0
        cv = c.get(f"{API}/predict-batches/{bid}/curves", headers=P, params={"name": "Node 200 / Y"}).json()
        assert [(s["run_key"], s["y"]) for s in cv["series"]] == [("run__00001", [1, 2]), ("run__00002", [3, 4, 5])]
        assert cv["downsampled"] is False
        assert c.get(f"{API}/predict-batches/{bid}/curves", headers=P, params={"max_points": 5000}).status_code == 422
    x, y, d = downsample([0.0, 1.0, 2.0], [1.0, 2.0, 3.0], 10)
    assert (x, d) == ([0.0, 1.0, 2.0], False)


# ---- V3-S9-17 응답 정의 ---------------------------------------------------------------------------------------------


def test_v3_s9_17_put_responses(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    ps = client.post(f"{API}/studies/{sid}/param-sets", headers=PW,
                     json={"path": str(make_param_set_folder(ai / "S1" / "00_inbox"))}).json()
    stored = ai / "S1" / "04_params" / ps["id"]
    orig = (stored / "original" / "responses.json").read_bytes()
    spec = {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}
    body = {"responses": [{"name": "MaxStress", "unit": "MPa", "spec": spec}, {"name": "Disp", "unit": "mm", "spec": None},
                          {"name": "MinDisp", "unit": "mm", "spec": {**spec, "datatype": "Displacement", "component": "Mag",
                                                                     "stat": "ABSMAX", "subcase": 2}}]}
    r = client.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["responses"] == body["responses"]
    assert json.loads((stored / "responses.json").read_text(encoding="utf-8")) == body
    assert (stored / "original" / "responses.json").read_bytes() == orig                          # original 불변
    assert client.get(f"{API}/param-sets/{ps['id']}", headers=P).json()["responses"][0]["spec"] == spec
    bad = [
        [{"name": "1x", "unit": "", "spec": None}],
        [{"name": "A", "spec": None}, {"name": "a", "spec": None}],
        [{"name": "A", "spec": {**spec, "stat": "AVG"}}],
        [{"name": "A", "spec": {**spec, "subcase": 0}}],
        [{"name": "A", "spec": {**spec, "component": "von|Mises"}}],
        [{"name": "A", "spec": {**spec, "source": "XYDATA"}}],
        [{"name": "A", "spec": {**spec, "goal": "MINIMIZE"}}],
        [{"name": "A", "spec": {**spec, "component": None}}],          # 선택 항목이어도 값은 문자열(layer와 같은 규칙)
        [{"name": "A", "spec": {**spec, "component": 'von"Mises'}}],
    ]
    for rows in bad:
        rows = rows + [{"name": "MaxStress", "spec": None}, {"name": "Disp", "spec": None}]
        r = client.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": rows})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "RESPONSE_INVALID", rows
        assert r.json()["detail"]["problems"]
    # D3-54: component는 선택(빈 값·키 없음 = "") — PhysicsAI 예측 h3d CornerStress처럼 성분 없는 결과
    corner = {k: v for k, v in spec.items() if k != "component"} | {"datatype": "CornerStress"}
    rows = [*body["responses"], {"name": "Corner", "unit": "MPa", "spec": {**corner, "component": ""}},
            {"name": "Corner2", "unit": "", "spec": corner}]
    r = client.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": rows})
    assert r.status_code == 200, r.text
    assert [x["spec"]["component"] for x in r.json()["responses"][3:]] == ["", ""]
    assert json.loads((stored / "responses.json").read_text(encoding="utf-8"))["responses"][4]["spec"] == {**corner, "component": ""}
    r = client.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": [{"name": "MaxStress", "spec": spec}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "RESPONSE_IN_USE"
    assert "Disp" in r.json()["detail"]["problems"][0]["message"]
    assert client.put(f"{API}/param-sets/{ps['id']}/responses", headers=GW, json=body).status_code == 403
    assert client.put(f"{API}/param-sets/nope/responses", headers=PW, json=body).status_code == 404
    # 실측 열이 없는 세트는 비워도 된다
    ps2 = client.post(f"{API}/studies/{sid}/param-sets", headers=PW,
                      json={"path": str(make_param_set_folder(ai / "S1" / "00_inbox", with_samples=False))}).json()
    r = client.put(f"{API}/param-sets/{ps2['id']}/responses", headers=PW, json={"responses": []})
    assert r.status_code == 200 and r.json()["responses"] == []
