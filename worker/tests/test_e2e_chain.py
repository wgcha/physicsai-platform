"""fake tools로 ③-1 → ③-2 → ③-4 → ③-5 → ④ 예측 체인을 API·워커까지 통과(§18, V-CMD-1, V-DS-*, V-EV-1, V-PR-*)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import text

from physicsai_test_support import API, LIMITER, H, make_h3d_tree, make_model_folder, make_param_set_folder, read_record

PW = H("tok-power", write=True)
P = H("tok-power")


def create_study(client, folder="cushion"):
    r = client.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": folder, "title": "쿠션 낙하"})
    assert r.status_code == 201, r.text
    return r.json()


def submit(client, sid, job_type, params, expect=201):
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": job_type, "params": params})
    assert r.status_code == expect, r.text
    return r.json()


def job(client, jid):
    r = client.get(f"{API}/jobs/{jid}", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def test_full_chain(client, worker_factory, loaded_config, fake_record, monkeypatch, engine):
    s = loaded_config.settings
    ai_root = Path(s.storage.ai_root)
    study = create_study(client)
    sroot = ai_root / "cushion"
    assert (sroot / "study.json").is_file()
    w = worker_factory()

    # ③-1 데이터셋
    inp = make_h3d_tree(sroot, n=10)
    insp = client.post(f"{API}/studies/{study['id']}/paths/inspect", headers=PW,
                       json={"purpose": "DATASET_INPUT", "path": str(inp)}).json()
    assert insp["ok"] and insp["summary"]["h3d_count"] == 10
    assert insp["summary"]["expected_train"] == 9 and insp["summary"]["expected_eval"] == 1
    j = submit(client, study["id"], "DATASET_CREATE", {"input_path": str(inp)})
    assert j["state"] == "QUEUED" and j["queue_position"] == 1
    assert w.run_once_slot() == "SUCCEEDED"
    jd = job(client, j["id"])
    assert jd["state"] == "SUCCEEDED", jd
    ds_id = jd["result"]["dataset_id"]
    assert jd["result"]["train_count"] == 9 and jd["result"]["eval_count"] == 1
    D = sroot / "03_dataset" / ds_id
    y = (D / "train" / "dataset.yaml").read_text()
    assert y.startswith("files:\n- ") and "interface: hw" in y and "  selection: {}\n" in y and f"hooks_dir: {D / 'hooks'}" in y
    assert (D / "train" / "dataset.psdata").stat().st_size > 1024 * 1024
    split = json.loads((D / "split.json").read_text())
    assert set(split["train"]).isdisjoint(split["eval"])
    rec = [r for r in read_record(fake_record) if r["tool"] == "edspy"]
    assert rec[0]["argv"][1:] == ["--physicsai", "--create-dataset", str(D / "train" / "dataset.psdata"), "--spec", str(D / "train" / "dataset.yaml")]
    assert rec[0]["cwd"] == str(D / "train")
    ds = client.get(f"{API}/datasets/{ds_id}", headers=P).json()
    assert ds["status"] == "READY" and ds["h3d_count"] == 10
    arts = client.get(f"{API}/jobs/{j['id']}/artifacts", headers=P).json()
    assert [a["kind"] for a in arts] == ["SPLIT_JSON"]
    assert client.get(f"{API}/artifacts/{arts[0]['id']}/content", headers=P).json()["seed"] == 20261008
    # env_snapshot·로그
    with engine.connect() as c:
        env = c.execute(text("select env_snapshot from jobs where id=:i"), {"i": j["id"]}).scalar()
    assert env["worker"]["limiter"] == LIMITER and env["altair"]["version_label"] == "fake"
    lg = client.get(f"{API}/jobs/{j['id']}/log", headers=P).json()
    assert "[EDSPY_DATASET_TRAIN]" in lg["text"] and lg["eof"]

    # ③-2 패키지(LIGHT 레인)
    j2 = submit(client, study["id"], "PACKAGE_EXPORT", {"dataset_id": ds_id})
    assert j2["lane"] == "LIGHT"
    assert w.run_once_slot() is None
    assert w.run_once_light() == "SUCCEEDED"
    K = sroot / "03_package" / ds_id
    assert (K / "dataset_train.psdata").is_file() and not (K / "dataset_eval.psdata").exists()
    assert "--train <MODEL_NAME>.psmdl --dataset dataset_train.psdata" in (K / "COMMANDS.txt").read_text()
    assert client.get(f"{API}/datasets/{ds_id}", headers=P).json()["package_ready"] is True

    # ③-4 모델 등록(허용 가져오기 루트)
    mf = make_model_folder(Path(s.storage.allowed_import_roots[0]))
    insp = client.post(f"{API}/studies/{study['id']}/paths/inspect", headers=PW, json={"purpose": "MODEL_FOLDER", "path": str(mf)}).json()
    assert insp["ok"] and insp["summary"]["psmdl"] == ["cushion_TNS.psmdl"]
    j3 = submit(client, study["id"], "MODEL_REGISTER", {"model_path": str(mf)})
    assert j3["params"]["name"] == "cushion_TNS"
    assert w.run_once_light() == "SUCCEEDED"
    model_id = job(client, j3["id"])["result"]["model_id"]
    m = client.get(f"{API}/models/{model_id}", headers=P).json()
    assert m["log_status"] == "PARSED" and m["epochs_total"] == 50 and m["last_epoch"] == 50
    assert m["min_loss_epoch"] == 50 and abs(m["final_loss"] - 2.0) < 1e-9 and m["dataset_id"] == ds_id
    assert m["version"] == 1 and len(m["loss_curve"]) == 50
    # 원본 폴더 삭제해도 복사본 사용
    stored = sroot / "03_model" / "models" / model_id
    assert (stored / "cushion_TNS.psmdl").is_file() and (stored / "source.json").is_file()

    # ③-5 평가 → Final
    j4 = submit(client, study["id"], "EVALUATE", {"model_id": model_id})
    assert w.run_once_slot() == "SUCCEEDED", job(client, j4["id"])
    m = client.get(f"{API}/models/{model_id}", headers=P).json()
    assert m["eval_status"] == "DONE" and m["eval_score"]["status"] == "PARSED"
    assert m["eval_score"]["metrics"] == {"R2": 0.93, "MAE": 1.25}
    score_rec = [r for r in read_record(fake_record) if "--score" in r["argv"]][-1]
    E = sroot / "03_model" / "score" / model_id / j4["id"]
    assert score_rec["argv"][1:] == ["--physicsai", "--score", str(E / "cushion_TNS.psscr"), "--model", str(stored / "cushion_TNS.psmdl"),
                                     "--dataset", str(D / "eval" / "dataset.psdata")]
    r = client.put(f"{API}/studies/{study['id']}/final-model", headers=PW, json={"model_id": model_id})
    assert r.status_code == 200 and r.json()["final_model_id"] == model_id

    # ④ 파라미터 세트·입력 확인·예측
    psf = make_param_set_folder(sroot / "00_inbox")
    r = client.post(f"{API}/studies/{study['id']}/param-sets", headers=PW, json={"path": str(psf)})
    assert r.status_code == 201, r.text
    ps = r.json()
    assert ps["is_current"] and ps["sample_count"] == 4 and ps["starter_name"] == "model0_0000.rad"
    chk = client.post(f"{API}/studies/{study['id']}/predict/check", headers=PW,
                      json={"values": {"THK_1": 6.0, "N_RIB": 4.6}}).json()
    assert [o["name"] for o in chk["out_of_range"]] == ["THK_1"]
    assert chk["rounded"] == [{"name": "N_RIB", "value": 4.6, "applied": 5.0}]
    assert chk["nearest"]["run_key"] == "run_0003"
    monkeypatch.setenv("FAKE_HW_IMAGE", "1")
    j5 = submit(client, study["id"], "PREDICT", {"values": {"THK_1": 3.5, "N_RIB": 4}, "value_source": "manual"})
    assert j5["params"]["model_id"] == model_id
    assert w.run_once_slot() == "SUCCEEDED", job(client, j5["id"])
    jd = job(client, j5["id"])
    Pd = sroot / "04_predict" / j5["id"]
    rendered = (Pd / "geom" / "simlab_parametered_mesh.py").read_text()
    assert "parameter(" not in rendered and "thickness =   3.5000" in rendered and 'NewValue="  4"' in rendered
    assert not rendered.startswith("﻿")
    inputs = sorted(os.listdir(Pd / "INPUT"))
    assert "eps_mesh_old.inc" not in inputs and "eps_mesh_1.inc" in inputs and "model0_0000.rad" in inputs
    pred_rec = [r for r in read_record(fake_record) if "--predict-write" in r["argv"]][-1]
    assert pred_rec["env"]["EDS_TNS_ACTVN_CHCKPT"] == "1"
    assert pred_rec["argv"][1:] == ["--physicsai", "--predict-write", str(Pd / "RESULT" / "model0_0000_pred.h3d"),
                                    "--model", str(stored / "cushion_TNS.psmdl"), "--input-file", str(Pd / "INPUT" / "model0_0000.rad")]
    hw_rec = [r for r in read_record(fake_record) if r["tool"] == "hw"][-1]
    assert hw_rec["argv"][1:] == ["-clientconfig", "hwpost.dat", "-b", "-tcl", s.resources.preview_pred_h3d_tcl, "-input",
                                  str(Pd / "RESULT" / "model0_0000_pred.h3d"), "-output", str(Pd / "H3D_PREVIEW.json")]
    res = jd["result"]
    assert res["preview_json_artifact_id"] and len(res["image_artifact_ids"]) == 1 and res["curve_artifact_id"]
    steps = {s_["step_key"]: s_ for s_ in jd["steps"]}
    assert steps["MESH"]["state"] == "SKIPPED" and steps["RESPONSE_EXTRACT"]["state"] == "SKIPPED"
    assert res["response_table"] == [
        {"name": "MaxStress", "unit": "MPa", "predicted": None, "nearest_measured": 110.0, "diff_pct": None},
        {"name": "Disp", "unit": "mm", "predicted": None, "nearest_measured": 2.5, "diff_pct": None},
    ]
    curve = client.get(f"{API}/artifacts/{res['curve_artifact_id']}/content", headers=P).json()
    assert curve["series"][0]["name"] == "Impact_force" and curve["series"][0]["y"][1] == 10.5
    img = client.get(f"{API}/artifacts/{res['image_artifact_ids'][0]}/content", headers=P)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    # 알림
    n = client.get(f"{API}/notifications", headers=P).json()
    events = [i["event"] for i in n["items"]]
    assert events.count("JOB_SUCCEEDED") == 5 and "JOB_STARTED" in events
    # lease_token 미노출
    for path in (f"/jobs/{j5['id']}", "/queue", f"/jobs?study_id={study['id']}"):
        assert "lease" not in client.get(API + path, headers=H("tok-admin")).text
    assert "lease" not in client.get(f"{API}/jobs/{j5['id']}?include=commands", headers=H("tok-admin")).text


def test_predict_with_response_extract(client, worker_factory, loaded_config, settings_dict, engine, fake_dashboard):
    """response_extract 템플릿이 있으면 예측 열과 차이%가 채워진다(V-PR-4)."""
    from fastapi.testclient import TestClient
    import httpx

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["commands"] = {**d["commands"], "response_extract": ["{hw}", "--responses", "{responses_json}", "--input", "{pred_h3d}", "--out", "{out_csv}"]}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))
    from physicsai_worker.runtime import Worker

    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c:
        sid = create_study(c, "resp")["id"]
        sroot = Path(lc.settings.storage.ai_root) / "resp"
        _register_final_model(c, sid, Path(lc.settings.storage.ai_root) / "resp", Worker(lc, engine))
        psf = make_param_set_folder(sroot / "00_inbox")
        assert c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(psf)}).status_code == 201
        jb = submit(c, sid, "PREDICT", {"values": {"THK_1": 2.0, "N_RIB": 2}, "value_source": "run", "source_run_key": "run_0000"})
        w = Worker(lc, engine)
        assert w.run_once_slot() == "SUCCEEDED", job(c, jb["id"])
        table = job(c, jb["id"])["result"]["response_table"]
        assert table[0] == {"name": "MaxStress", "unit": "MPa", "predicted": 110.0, "nearest_measured": 100.0, "diff_pct": 10.0}
        assert table[1]["predicted"] == 111.0 and table[1]["nearest_measured"] == 1.5


def _register_final_model(c, sid, sroot, w):
    mf = make_model_folder(sroot / "00_inbox", name="M1")
    jb = submit(c, sid, "MODEL_REGISTER", {"model_path": str(mf)})
    assert w.run_once_light() == "SUCCEEDED"
    mid = job(c, jb["id"])["result"]["model_id"]
    assert c.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": mid}).status_code == 200
    return mid


def test_input_zip_and_display_paths(client, worker_factory, loaded_config, engine):
    """B16·B17: ④ 입력 파일 zip 스트리밍(완료 전 409), 표시용 절대경로."""
    import io
    import zipfile

    ai = Path(loaded_config.settings.storage.ai_root)
    st = create_study(client, "zipst")
    sid = st["id"]
    assert st["folder_display_path"] == str(ai / "zipst")
    w = worker_factory()
    inp = make_h3d_tree(ai / "zipst", n=4)
    dj = submit(client, sid, "DATASET_CREATE", {"input_path": str(inp)})
    r = client.get(f"{API}/jobs/{dj['id']}/artifacts/input.zip", headers=P)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "INPUT_NOT_READY"
    assert w.run_once_slot() == "SUCCEEDED"
    ds_id = job(client, dj["id"])["result"]["dataset_id"]
    submit(client, sid, "PACKAGE_EXPORT", {"dataset_id": ds_id})
    assert w.run_once_light() == "SUCCEEDED"
    ds = client.get(f"{API}/datasets/{ds_id}", headers=P).json()
    assert ds["package_display_path"] == str(ai / "zipst" / "03_package" / ds_id)
    assert ds["dataset_display_path"] == str(ai / "zipst" / "03_dataset" / ds_id)
    mid = _register_final_model(client, sid, ai / "zipst", w)
    assert client.get(f"{API}/models/{mid}", headers=P).json()["stored_display_path"] == str(ai / "zipst" / "03_model" / "models" / mid)
    psf = make_param_set_folder(ai / "zipst" / "00_inbox")
    assert client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(psf)}).status_code == 201
    pj = submit(client, sid, "PREDICT", {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "nominal"})
    r = client.get(f"{API}/jobs/{pj['id']}/artifacts/input.zip", headers=H("tok-general"))
    assert r.status_code == 409
    assert job(client, pj["id"])["input_display_path"] is None
    assert w.run_once_slot() == "SUCCEEDED"
    # 링크 파일은 zip에 넣지 않는다
    inp_dir = ai / "zipst" / "04_predict" / pj["id"] / "INPUT"
    os.symlink("/etc/passwd", inp_dir / "evil.inc")
    r = client.get(f"{API}/jobs/{pj['id']}/artifacts/input.zip", headers=H("tok-general"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(zf.namelist()) == sorted(n for n in os.listdir(inp_dir) if n != "evil.inc")
    assert "model0_0000.rad" in zf.namelist() and "eps_mesh_1.inc" in zf.namelist()
    assert zf.read("model0_0000.rad") == (inp_dir / "model0_0000.rad").read_bytes()
    assert job(client, pj["id"])["input_display_path"] == str(inp_dir)


def test_display_path_windows_form():
    from physicsai_api.services.common import display_path

    assert display_path("E:/shared/AI_WORK", "cushion", "03_package/abc/") == "E:\\shared\\AI_WORK\\cushion\\03_package\\abc"
    assert display_path("/srv/ai/", "s", None) == "/srv/ai/s"
