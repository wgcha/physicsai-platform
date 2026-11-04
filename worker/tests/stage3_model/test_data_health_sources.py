"""③-1 데이터 점검 — 프레임 원천 우선순위(① 컨투어 캐시 manifest → ② engine out 기록 → ③ DH_FRAMES hw 1회), DOE 연결 모드, hw 시간 초과.
이미 정해진 run은 hw 조회 대상에서 빠진다(조회 호출 기록으로 확인)."""

from __future__ import annotations

from physicsai_test_support import API, H, make_h3d_tree, read_record

from ..analysis.eq_support import MESH_INC, MESH_TEXT, make_train_doe
from ..stage4_predict.conftest import predict_env  # noqa: F401 - fixture 재사용

PW, P = H("tok-power", write=True), H("tok-power")
FAST = {"min_n": 3, "knn_k": 2, "knn_min_n": 4}


def _run(env, inp, **params):
    j = env.submit("DATA_HEALTH", {"input_path": str(inp), **params})
    st = env.w.run_once_slot()
    return j["id"], st


def _probes(fake_record) -> list[list[str]]:
    return [x["targets"] for x in read_record(fake_record) if x["tool"] == "hw_probe"]


def _report(env, jid) -> dict:
    r = env.c.get(f"{API}/jobs/{jid}/data-health", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def _by(rep) -> dict:
    return {r["file_rel"]: r for r in rep["runs"]}


def test_frame_source_contour_cache_manifest_then_key_mismatch(predict_env, fake_record, monkeypatch):
    """① 컨투어 캐시 manifest가 키(h3d 크기·mtime) 일치일 때만 프레임 수 원천 — 일치하면 그 run은 hw 조회 대상이 아니고, h3d가 바뀌면 조회로 대체."""
    monkeypatch.setenv("FAKE_CONTOUR3D_FRAMES", "7")
    env = predict_env(extra={"contour3d": {"enabled": True, "max_frames": 3}, "data_health": FAST})
    inp = make_h3d_tree(env.sroot, n=6)
    target = inp / "run_0002" / "result_0002.h3d"
    rel = target.relative_to(env.sroot).as_posix()
    r = env.c.post(f"{API}/contour3d", headers=PW, json={"source_kind": "SOLVER_H3D", "source_ref": {"study_id": env.sid, "h3d_rel": rel}})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED"
    jid, st = _run(env, inp)
    assert st == "SUCCEEDED", env.job(jid)
    probes = _probes(fake_record)
    assert len(probes) == 1 and len(probes[0]) == 5 and not any(str(target) in t for t in probes[0])  # 정해진 run은 조회에서 빠짐
    run = _by(_report(env, jid))["run_0002/result_0002.h3d"]
    assert run["consistency"]["frames"]["value"] == 7 and run["consistency"]["frames"]["status"] == "FAIL" and run["required"]
    # h3d 크기가 바뀌면 캐시 키가 달라져 무시 → ③ 조회(6개 전부)로 대체, 프레임 7이 아니다
    target.write_bytes(target.read_bytes() + b"xx")
    jid2, st2 = _run(env, inp)
    assert st2 == "SUCCEEDED", env.job(jid2)
    assert len(_probes(fake_record)[-1]) == 6
    assert _by(_report(env, jid2))["run_0002/result_0002.h3d"]["consistency"]["frames"]["value"] == 5


def test_frame_source_engine_out_write_regex_skips_probe(predict_env, fake_record):
    """② frame_write_regex를 정하면 engine out의 기록 줄 수가 프레임 수 — 그 run은 조회에서 빠지고, out이 없는 run만 hw로 조회."""
    env = predict_env(extra={"data_health": {**FAST, "frame_write_regex": "WRITING FRAME"}})
    inp = make_h3d_tree(env.sroot, n=6)
    for i in range(5):
        n = 3 if i == 4 else 5
        (inp / f"run_{i:04d}" / f"m{i}_0001.out").write_text(" NORMAL TERMINATION\n" + "WRITING FRAME\n" * n, encoding="utf-8")
    jid, st = _run(env, inp)
    assert st == "SUCCEEDED", env.job(jid)
    probes = _probes(fake_record)
    assert len(probes) == 1 and len(probes[0]) == 1 and probes[0][0].endswith("result_0005.h3d")
    rep = _by(_report(env, jid))
    assert rep["run_0004/result_0004.h3d"]["required"] and rep["run_0004/result_0004.h3d"]["consistency"]["frames"]["value"] == 3
    assert rep["run_0005/result_0005.h3d"]["consistency"]["frames"]["value"] == 5 and not rep["run_0005/result_0005.h3d"]["required"]


def test_frame_probe_not_called_when_all_sources_known(predict_env, fake_record):
    """모든 run의 원천이 정해지면 DH_FRAMES는 SKIPPED — hw 호출 0회."""
    env = predict_env(extra={"data_health": {**FAST, "frame_write_regex": "WRITING FRAME"}})
    inp = make_h3d_tree(env.sroot, n=4)
    for i in range(4):
        (inp / f"run_{i:04d}" / f"m{i}_0001.out").write_text("WRITING FRAME\n" * 5, encoding="utf-8")
    jid, st = _run(env, inp)
    assert st == "SUCCEEDED", env.job(jid)
    assert _probes(fake_record) == [] and env.steps(jid)["DH_FRAMES"]["state"] == "SKIPPED"


def test_doe_linked_mode_knn_with_snapshot_params_and_refs_by_doe(predict_env, fake_record, monkeypatch, tmp_path):
    """train_doe 연결: 파라미터 스냅숏으로 kNN(제한 모드 아님·DH_NO_DOE_LINK 없음), DOE마다 프레임 기준값(refs_by_doe)이 다르면 각각으로 판정."""
    env = predict_env(extra={"data_health": FAST})
    da = make_train_doe(env, runs=4, label="A")
    db = make_train_doe(env, runs=4, label="B")
    out = env.sroot / "01_train" / "results" / da / "run__00002"  # 한 run만 부피가 다른 메시(이상치)
    big = env.sroot / "01_train" / "doe" / da / "approaches" / "doe_1" / "run__00002" / MESH_INC
    big.write_text(MESH_TEXT.replace("/NODE\n", "/NODE\n9 5 5 5\n").replace("2 1 2 5 3 4 6 8 7", "2 1 2 5 3 4 6 8 9"))
    assert out.is_dir()
    monkeypatch.setenv("FAKE_PROBE_FRAMES", f"{da}=5,{db}=4")
    jid, st = _run(env, env.sroot / "01_train" / "results")
    assert st == "SUCCEEDED", env.job(jid)
    rep = _report(env, jid)
    s = rep["summary"]
    assert s["limited"] is False and s["n_runs"] == 8 and s["n_required"] == 0 and s["frames_ref"] is None
    assert s["refs_by_doe"][da]["frames"] == 5 and s["refs_by_doe"][db]["frames"] == 4  # DOE별 기준값
    assert "DH_NO_DOE_LINK" not in {w["code"] for w in s["warnings"]} and "DH_PARAMS_MIXED" not in {w["code"] for w in s["warnings"]}
    vol = next(m for m in rep["metrics"] if m["id"] == "volume")
    assert vol["knn_skipped"] is False  # 스냅숏 파라미터(THK_1·N_RIB)로 이웃을 정했다
    runs = rep["runs"]
    assert all(r["run_key"] and r["doe_id"] for r in runs)
    assert sum(1 for r in runs if r["values"]["volume"]["s"] is not None) >= 4
    outlier = next(r for r in runs if r["run_key"] == "run__00002" and r["doe_id"] == da)
    assert outlier["recommended"] and any(x["code"] in ("ROBUST_Z", "KNN_JUMP") for x in outlier["reasons"])
    assert len(_probes(fake_record)) == 1  # hw 조회는 작업 전체에서 1회


def test_probe_timeout_makes_targets_na_and_job_succeeds(predict_env, fake_record, monkeypatch):
    """hw가 시간 초과(frame_probe_timeout_s)면 대상 run은 NA(FRAMES_PROBE_UNAVAILABLE), 작업은 성공, '확인 불가' 건수와 경고를 남긴다."""
    monkeypatch.setenv("FAKE_TOOL_MODE_PROBE", "hang")
    monkeypatch.setenv("FAKE_PROBE_HANG_S", "30")
    env = predict_env(extra={"data_health": {**FAST, "frame_probe_timeout_s": 1}})
    inp = make_h3d_tree(env.sroot, n=5)
    jid, st = _run(env, inp)
    assert st == "SUCCEEDED", env.job(jid)
    job = env.job(jid)
    assert job["result"]["n_frames_unknown"] == 5 and job["result"]["n_required"] == 0
    assert "DH_FRAMES_UNAVAILABLE" in {w["code"] for w in job["warnings"]}
    rep = _report(env, jid)
    assert all(r["consistency"]["frames"]["code"] == "FRAMES_PROBE_UNAVAILABLE" and r["consistency"]["frames"]["status"] == "NA" for r in rep["runs"])
