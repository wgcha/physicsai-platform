"""③-1 데이터 점검 계약 시험 보강 — V-DH-6(run 해석)·7(응답 재사용·외부 도구 0회)·9(활성 409·취소·_backup)·12(저장)·19(제외 필수 유지·kept_required)
및 보고서 summary.warnings·input_key(DH-C3)."""

from __future__ import annotations

import json
import uuid

from helpers_manage import mk_curation
from physicsai_core.data_health.input_key import folder_key
from physicsai_test_support import API, H, make_h3d_tree, read_record

from ..analysis.eq_support import make_train_doe
from ..stage4_predict.conftest import predict_env  # noqa: F401 - fixture 재사용

PW, P = H("tok-power", write=True), H("tok-power")
FAST = {"min_n": 3, "knn_k": 2, "knn_min_n": 4, "frame_write_regex": "WRITING FRAME"}
RESPS_JSON = {"responses": [
    {"name": "MaxStress", "unit": "MPa", "spec": {"source": "H3D", "subcase": 1, "datatype": "CornerStress", "component": "vonMises", "layer": "", "stat": "MAX"}},
    {"name": "AccPeak", "unit": "g", "spec": {"source": "CURVE", "series": None, "stat": "ABSMAX"}}]}


def _submit(env, jt, params, expect=201):
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": jt, "params": params})
    assert r.status_code == expect, r.text
    return r.json()


def _run(env, **params):
    j = _submit(env, "DATA_HEALTH", params)
    return j["id"], env.w.run_once_slot()


def _report(env, jid):
    r = env.c.get(f"{API}/jobs/{jid}/data-health", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def _outs(env, did, frames=5, skip=()):
    """DOE run마다 engine out(프레임 기록 줄) — hw 조회가 필요 없게 한다."""
    for d in (env.sroot / "01_train" / "results" / did).iterdir():
        if d.name not in skip:
            (d / "model_0001.out").write_text(" NORMAL TERMINATION\n" + "WRITING FRAME\n" * frames, encoding="utf-8")


def _codes(ws) -> set[str]:
    return {w["code"] for w in ws}


def test_limited_mode_warnings_in_report_input_key_and_undecided(predict_env):
    """작업 warnings의 DH_NO_DOE_LINK 등이 보고서 summary.warnings에도 같은 코드로 있고, input_key는 정규화 경로. 종료 시각 기준이 없으면 DH_CONSISTENCY_UNDECIDED."""
    env = predict_env(extra={"data_health": {"min_n": 3, "knn_k": 2, "knn_min_n": 4}})
    inp = make_h3d_tree(env.sroot, n=6)
    jid, st = _run(env, input_path=str(inp) + "/")
    assert st == "SUCCEEDED", env.job(jid)
    job, s = env.job(jid), _report(env, jid)["summary"]
    assert {"DH_NO_DOE_LINK", "DH_CONSISTENCY_UNDECIDED"} <= _codes(job["warnings"]) <= _codes(s["warnings"]) | _codes(job["warnings"])
    assert {"DH_NO_DOE_LINK", "DH_CONSISTENCY_UNDECIDED"} <= _codes(s["warnings"])
    und = next(w for w in s["warnings"] if w["code"] == "DH_CONSISTENCY_UNDECIDED")
    assert und["count"] == 6 == s["n_consistency_undecided"] and s["n_frames_unknown"] == 0
    assert s["input_key"] == folder_key(str(inp)) == job["result"]["input_key"]
    # 끝 구분자·`\` 표기만 다른 입력으로 데이터셋을 만들어도 점검과 같은 대상으로 본다(같은 정규화 함수)
    ds = _submit(env, "DATASET_CREATE", {"input_path": str(inp) + "/", "health_job_id": jid})
    assert ds["job_type"] == "DATASET_CREATE"


def test_partial_probe_failure_warning_in_report(predict_env, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_PROBE", "open_error")
    env = predict_env(extra={"data_health": {"min_n": 3}})
    jid, st = _run(env, input_path=str(make_h3d_tree(env.sroot, n=5)))
    assert st == "SUCCEEDED", env.job(jid)
    s = _report(env, jid)["summary"]
    w = next(x for x in s["warnings"] if x["code"] == "DH_FRAMES_PARTIAL")
    assert w["count"] == 1 and s["n_frames_unknown"] == 1


def test_reference_tie_leaves_undecided_warning(predict_env, monkeypatch):
    monkeypatch.setenv("FAKE_PROBE_FRAMES", "run_0000=5,run_0001=5,run_0002=4,run_0003=4")
    env = predict_env(extra={"data_health": {"min_n": 3}})
    jid, st = _run(env, input_path=str(make_h3d_tree(env.sroot, n=4)))
    assert st == "SUCCEEDED", env.job(jid)
    s = _report(env, jid)["summary"]
    assert {"DH_REF_TIE", "DH_CONSISTENCY_UNDECIDED"} <= _codes(s["warnings"]) and s["n_required"] == 0 and s["n_consistency_undecided"] == 4


def test_v_dh_6_run_resolution_curation_direct_all_external_and_engine_mixed(predict_env):
    env = predict_env(extra={"data_health": FAST})
    da, db = make_train_doe(env, runs=4, label="A"), make_train_doe(env, runs=4, label="B")
    _outs(env, da), _outs(env, db)
    res = env.sroot / "01_train" / "results"
    # results/<doe> 직접 → 그 DOE 한 개
    j1, st = _run(env, input_path=str(res / da))
    assert st == "SUCCEEDED", env.job(j1)
    r1 = _report(env, j1)
    assert {r["doe_id"] for r in r1["runs"]} == {da} and r1["summary"]["limited"] is False
    # results/ 전체 → DOE 2개
    j2, st = _run(env, input_path=str(res))
    assert st == "SUCCEEDED", env.job(j2)
    assert {r["doe_id"] for r in _report(env, j2)["runs"]} == {da, db} and env.job(j2)["result"]["doe_ids"] == sorted([da, db])
    # 큐레이션 file_list의 run_key → DOE 연결, input_key = curation:<id>
    from ..analysis.eq_support import _first_job

    cid = mk_curation(env.engine, env.sid, _first_job(env))
    env.sql("update curations set source=cast(:s as jsonb) where id=:i", s=json.dumps({"kind": "TRAIN_DOE", "doe_id": da}), i=cid)
    C = env.sroot / "02_curated" / cid
    items = []
    for n in range(1, 5):
        f = C / "CURATED_DATA" / f"c_{n}.h3d"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"H3D" + bytes([n]))
        items.append({"ok": True, "output_rel": f"CURATED_DATA/c_{n}.h3d", "run_key": f"run__{n:05d}"})
    (C / "file_list.json").write_text(json.dumps(items), encoding="utf-8")
    j3, st = _run(env, curation_id=cid)
    assert st == "SUCCEEDED", env.job(j3)
    r3 = _report(env, j3)
    assert {(r["doe_id"], r["run_key"]) for r in r3["runs"]} == {(da, f"run__{n:05d}") for n in range(1, 5)}
    assert r3["summary"]["input_key"] == f"curation:{cid}" and env.job(j3)["result"]["curation_id"] == cid
    # 외부 폴더(Study 안이지만 DOE와 무관) → 제한 모드 + DH_NO_DOE_LINK
    j4, st = _run(env, input_path=str(make_h3d_tree(env.sroot, n=4)))
    assert st == "SUCCEEDED", env.job(j4)
    s4 = _report(env, j4)["summary"]
    assert s4["limited"] is True and "DH_NO_DOE_LINK" in _codes(s4["warnings"])
    # 엔진이 섞인 DOE → 422 ENGINE_MIXED
    env.sql("update train_does set engine='native' where id=:d", d=db)
    assert _submit(env, "DATA_HEALTH", {"input_path": str(res)}, expect=422)["detail"]["code"] == "ENGINE_MIXED"


def test_v_dh_7_responses_reuse_missing_na_curve_excluded_and_no_external_tool(predict_env, fake_record):
    env = predict_env(extra={"data_health": FAST})
    did = make_train_doe(env, runs=4, label="R")
    D = env.sroot / "01_train" / "doe" / did
    (D / "responses.json").write_text(json.dumps(RESPS_JSON), encoding="utf-8")
    _outs(env, did)
    runs = sorted((env.sroot / "01_train" / "results" / did).iterdir())
    for i, d in enumerate(runs):
        if i != 2:  # 한 run은 추출 안 됨
            (d / "responses_run.csv").write_text(f"name,value\nMaxStress,{100 + i}\n", encoding="utf-8")
    jid, st = _run(env, input_path=str(env.sroot / "01_train" / "results" / did))
    assert st == "SUCCEEDED", env.job(jid)
    rep = _report(env, jid)
    assert "resp:MaxStress" in rep["summary"]["metrics_used"] or any(m["id"] == "resp:MaxStress" for m in rep["metrics"])
    assert not any(m["id"] == "resp:AccPeak" for m in rep["metrics"])  # CURVE 응답은 제외
    by = {r["run_key"]: r["values"]["resp:MaxStress"] for r in rep["runs"]}
    assert by["run__00001"]["v"] == 100 and by[runs[2].name]["v"] is None and by[runs[2].name]["na"] == "RESP_NOT_EXTRACTED"
    w = next(x for x in rep["summary"]["warnings"] if x["code"] == "DH_RESP_NOT_EXTRACTED")
    assert w["count"] == 1
    assert read_record(fake_record) == []  # 외부 도구 실행 0회(응답 추출·hw 조회 모두 없음)


def test_v_dh_9_active_409_cancel_at_run_boundary_retry_and_backup(predict_env, monkeypatch):
    env = predict_env(extra={"data_health": {"min_n": 3}})
    inp = make_h3d_tree(env.sroot, n=6)
    j = _submit(env, "DATA_HEALTH", {"input_path": str(inp)})
    again = _submit(env, "DATA_HEALTH", {"input_path": str(inp)}, expect=409)
    assert again["detail"]["code"] == "DATA_HEALTH_ACTIVE" and again["detail"]["job_id"] == j["id"]
    # 이전 작업 폴더가 있으면 _backup으로 옮기고 다시 만든다
    old = env.sroot / "03_dataset" / "_health" / j["id"]
    old.mkdir(parents=True)
    (old / "sentinel.txt").write_text("old", encoding="utf-8")
    # run 경계 취소: 세 번째 확인에서 취소
    from physicsai_worker.signals import Cancelled
    from physicsai_worker.step_process import StepProcessMixin

    calls = {"n": 0}
    orig = StepProcessMixin.checkpoint_cancel

    def cp(self):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise Cancelled()
        return orig(self)

    monkeypatch.setattr(StepProcessMixin, "checkpoint_cancel", cp)
    assert env.w.run_once_slot() == "CANCELED"
    monkeypatch.undo()
    job = env.job(j["id"])
    assert job["state"] == "CANCELED" and env.steps(j["id"])["DH_SCAN"]["state"] == "CANCELED"
    assert not (old / "scan.json").exists() and not (old / "sentinel.txt").exists()
    assert list(env.sroot.rglob("sentinel.txt")) and "_backup" in str(next(env.sroot.rglob("sentinel.txt")))
    r = env.c.post(f"{API}/jobs/{j['id']}/retry", headers=PW, json={})
    assert r.status_code == 201 and r.json()["job_type"] == "DATA_HEALTH"
    assert env.w.run_once_slot() == "SUCCEEDED"
    from physicsai_core.features import FEATURES, JOB_FEATURE

    assert JOB_FEATURE["DATA_HEALTH"] is FEATURES["dataset_create"]  # 기능 게이트 = dataset_create


def test_v_dh_12_result_has_no_per_run_values_files_in_health_folder_and_ds_scan_ignores_it(predict_env):
    env = predict_env(extra={"data_health": {"min_n": 3}})
    inp = make_h3d_tree(env.sroot, n=5)
    jid, st = _run(env, input_path=str(inp))
    assert st == "SUCCEEDED", env.job(jid)
    res = env.job(jid)["result"]
    assert set(res) <= {"input_path", "input_key", "curation_id", "doe_ids", "engine", "n_runs", "n_required", "n_frames_unknown",
                        "n_consistency_undecided", "frames_ref", "t_end_ref", "n_recommended", "n_sigma_only", "n_sound_fail",
                        "n_na_by_metric", "metrics_used", "thresholds", "limited", "report_rel", "csv_rel", "warnings"}
    assert "runs" not in res and not any("run_0000" in json.dumps(v) for v in res.values())
    H_ = env.sroot / "03_dataset" / "_health" / jid
    assert {"inputs.json", "runs_raw.csv", "runs.csv", "report.json", "frames_todo.json"} <= {p.name for p in H_.iterdir()}
    assert res["report_rel"] == f"03_dataset/_health/{jid}/report.json"
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(H_)}})
    assert r.status_code >= 400  # `_health`는 데이터셋 입력이 될 수 없다


def test_v_dh_19_kept_required_default_exclude_and_kept_validation(predict_env, monkeypatch):
    """제외 필수 run: 제외도 해제도 아니면 서버가 기본 제외, 해제(kept_required)하면 포함 + DS_INCONSISTENT_KEPT + excluded.json.kept_required,
    제외 필수가 아닌 파일을 kept로 보내면 422."""
    monkeypatch.setenv("FAKE_PROBE_FRAMES", "run_0005=3,x=5")
    env = predict_env(extra={"data_health": {"min_n": 3}})
    inp = make_h3d_tree(env.sroot, n=8)
    hj, st = _run(env, input_path=str(inp))
    assert st == "SUCCEEDED", env.job(hj)
    bad_rel = "run_0005/result_0005.h3d"
    assert [r["file_rel"] for r in _report(env, hj)["runs"] if r["required"]] == [bad_rel]
    body = {"input_path": str(inp), "health_job_id": hj}
    nope = _submit(env, "DATASET_CREATE", {**body, "kept_required": ["run_0001/result_0001.h3d"]}, expect=422)
    assert nope["detail"]["code"] == "INVALID_PARAMS"
    assert _submit(env, "DATASET_CREATE", {"input_path": str(inp), "kept_required": [bad_rel]}, expect=422)  # health_job_id 없이는 검증 불가
    # (a) 아무 것도 보내지 않으면 제외 필수는 기본 제외
    a = _submit(env, "DATASET_CREATE", body)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(a["id"])
    ja = env.job(a["id"])
    assert ja["result"]["excluded_count"] == 1 and "DS_REQUIRED_AUTO_EXCLUDED" in _codes(ja["warnings"])
    # (b) 해제 → 포함 + 경고
    b = _submit(env, "DATASET_CREATE", {**body, "kept_required": [bad_rel]})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(b["id"])
    jb = env.job(b["id"])
    assert jb["result"]["excluded_count"] == 0 and jb["result"]["h3d_count"] == 8
    w = next(x for x in jb["warnings"] if x["code"] == "DS_INCONSISTENT_KEPT")
    assert w["message"] == "프레임 수·종료 시각이 다른 run 1개를 포함했습니다 — 학습이 실패하거나 결과가 왜곡될 수 있습니다"
    D = env.sroot / "03_dataset" / jb["result"]["dataset_id"]
    exj = json.loads((D / "excluded.json").read_text(encoding="utf-8"))
    assert exj["kept_required"] == [bad_rel] and exj["files"] == [] and "DS_REQUIRED_AUTO_EXCLUDED" not in _codes(jb["warnings"])
