"""v0.2.16 ③-1 데이터 점검(data-health.md) 워커·API 흐름(가짜 hw) — V-DH 일관성 판정·프레임 조회 실패 허용·제외 추천 반영·API 오류 코드."""

from __future__ import annotations

import json
from pathlib import Path

from physicsai_test_support import API, H, make_h3d_tree, read_record

PW, P = H("tok-power", write=True), H("tok-power")
OUT = """ NORMAL TERMINATION
 ** CYCLE   TIME     TIME-STEP   ELEMENT    ERROR     MASS
   1000   {t}   1.0E-03   SHELL 12   {err}%   0.0
"""


def _study(client, name):
    r = client.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _tree(ai: Path, name: str, n: int = 6) -> Path:
    inp = make_h3d_tree(ai / name, n=n)
    for i in range(n):
        (inp / f"run_{i:04d}" / f"m{i}_0001.out").write_text(" NORMAL TERMINATION\n", encoding="utf-8")
    return inp


def _run_dh(client, worker_factory, sid, inp, **params):
    j = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATA_HEALTH", "params": {"input_path": str(inp), **params}}).json()
    assert "id" in j, j
    status = worker_factory().run_once_slot()
    return j["id"], status


def _job(client, jid):
    return client.get(f"{API}/jobs/{jid}", headers=P).json()


def test_v_dh_frames_mismatch_is_required_and_probe_runs_once(client, loaded_config, worker_factory, fake_record, monkeypatch):
    """프레임 수·마지막 시각이 기준(최빈값)과 다른 run은 제외 필수. 프레임 원천이 없으면 hw 조회는 작업 전체에서 1회."""
    monkeypatch.setenv("FAKE_PROBE_FRAMES", "run_0005=3,x=5")
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _study(client, "DH1")
    inp = _tree(ai, "DH1")
    jid, status = _run_dh(client, worker_factory, sid, inp)
    assert status == "SUCCEEDED", _job(client, jid)
    probes = [x for x in read_record(fake_record) if x["tool"] == "hw_probe"]
    assert len(probes) == 1 and len(probes[0]["targets"]) == 6
    r = client.get(f"{API}/jobs/{jid}/data-health", headers=P)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["summary"]["n_runs"] == 6 and rep["summary"]["n_required"] == 1 and rep["summary"]["frames_ref"] == 5
    assert rep["summary"]["ref_source"] == "mode"
    first = rep["runs"][0]
    assert first["file_rel"].startswith("run_0005") and first["required"] and first["recommended"]
    assert first["consistency"]["frames"]["status"] == "FAIL"
    res = _job(client, jid)["result"]
    assert res["n_runs"] == 6 and res["n_required"] == 1 and "runs" not in res  # DB에는 요약만
    kinds = {a["kind"] for a in client.get(f"{API}/jobs/{jid}/artifacts", headers=P).json()}
    assert {"DATA_HEALTH_REPORT", "DATA_HEALTH_CSV"} <= kinds


def test_v_dh_probe_failure_keeps_job_succeeded(client, loaded_config, worker_factory, monkeypatch):
    """hw 조회가 실패(종료코드 1·출력 없음)해도 작업은 성공 — 프레임은 NA(FRAMES_PROBE_UNAVAILABLE) + 경고."""
    monkeypatch.setenv("FAKE_TOOL_MODE_PROBE", "fail")
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _study(client, "DH2")
    jid, status = _run_dh(client, worker_factory, sid, _tree(ai, "DH2"))
    assert status == "SUCCEEDED", _job(client, jid)
    codes = {w["code"] for w in _job(client, jid)["warnings"]}
    assert "DH_FRAMES_UNAVAILABLE" in codes
    rep = client.get(f"{API}/jobs/{jid}/data-health", headers=P).json()
    assert rep["summary"]["n_frames_unknown"] == 6 and rep["summary"]["n_required"] == 0
    assert rep["runs"][0]["consistency"]["frames"]["code"] == "FRAMES_PROBE_UNAVAILABLE"


def test_v_dh_report_api_errors(client, loaded_config, worker_factory):
    """DATA_HEALTH가 아닌 작업 404, 보고서가 아직 없으면 409 REPORT_NOT_READY."""
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _study(client, "DH3")
    inp = _tree(ai, "DH3")
    ds = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}}).json()
    assert client.get(f"{API}/jobs/{ds['id']}/data-health", headers=P).status_code == 404
    j = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATA_HEALTH", "params": {"input_path": str(inp)}}).json()
    r = client.get(f"{API}/jobs/{j['id']}/data-health", headers=P)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "REPORT_NOT_READY"


def test_v_dh_exclude_files_and_health_link(client, loaded_config, worker_factory):
    """점검 → 데이터셋 생성에서 exclude_files 제외·excluded.json·split.json.excluded·excluded_count. 입력이 다르면 422 DH_INPUT_MISMATCH."""
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _study(client, "DH4")
    inp = _tree(ai, "DH4", n=8)
    hj, status = _run_dh(client, worker_factory, sid, inp)
    assert status == "SUCCEEDED", _job(client, hj)
    bad = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {
        "input_path": str(_tree(ai, "DH4b", n=8)), "health_job_id": hj}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "DH_INPUT_MISMATCH"
    ex = ["run_0001/result_0001.h3d", "nope/none.h3d"]
    j = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {
        "input_path": str(inp), "exclude_files": ex, "health_job_id": hj}}).json()
    assert worker_factory().run_once_slot() == "SUCCEEDED", _job(client, j["id"])
    job = _job(client, j["id"])
    assert job["result"]["h3d_count"] == 7 and job["result"]["excluded_count"] == 1
    assert "DS_EXCLUDE_NOT_FOUND" in {w["code"] for w in job["warnings"]}
    D = ai / "DH4" / "03_dataset" / job["result"]["dataset_id"]
    assert json.loads((D / "excluded.json").read_text(encoding="utf-8"))["excluded"][0]["file_rel"] == ex[0]
    assert json.loads((D / "split.json").read_text(encoding="utf-8"))["excluded"] == [ex[0]]
    ds = client.get(f"{API}/datasets/{job['result']['dataset_id']}", headers=P).json()
    assert ds["excluded_count"] == 1 and ds["health_job_id"] == hj
