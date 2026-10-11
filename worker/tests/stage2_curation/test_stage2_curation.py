"""② 데이터 정리·③-1 큐레이션 입력(V2-CU-1~4, V2-CMD-1(②), V2-CMD-3). G SPDM 가져오기(V2-SPDM-1~3)는 test_stage2_spdm_import."""

from __future__ import annotations

import json
import os
from pathlib import Path

from helpers_stage1 import _ready_doe, _write_results, job, study, submit
from physicsai_test_support import API, H, read_record

PW, P = H("tok-power", write=True), H("tok-power")


def _collected_doe(c, w, ai, lc, name, n=3):
    sid, doe_id = _ready_doe(c, w, ai, name, num_runs=n)
    src = Path(lc.settings.storage.allowed_import_roots[0]) / f"res_{name}"
    keys = [f"run__{i:05d}" for i in range(1, n + 1)]
    _write_results(ai, name, doe_id, keys[:-1], base=src)  # 마지막 run은 누락
    for rk in keys[:-1]:
        os.makedirs(src / rk / "m_3", exist_ok=True)
        os.replace(src / rk / "drop_A001.h3d", src / rk / "m_3" / "drop_A001.h3d")
    j = submit(c, sid, "TD_RESULT_IMPORT", {"doe_id": doe_id, "source_path": str(src)})
    assert w.run_once_light() == "SUCCEEDED", job(c, j["id"])
    return sid, doe_id


def test_h3d_preview_and_curate_from_doe(p2_env, fake_record, monkeypatch, engine):
    """V2-CU-1·V2-CU-2·V2-CMD-3: 미리보기 체인·usable·cfg 골든·run 폴더·팬아웃 일부 실패·누락 run·백업, ③-1 입력."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid, doe_id = _collected_doe(c, w, ai, lc, "cu1")
    srcs = c.get(f"{API}/studies/{sid}/curation-sources", headers=P).json()
    assert srcs[0]["kind"] == "TRAIN_DOE" and srcs[0]["h3d_count"] == 2 and srcs[0]["t01_count"] == 2 and srcs[0]["runs_expected"] == 3
    source = {"kind": "TRAIN_DOE", "doe_id": doe_id}
    pj = submit(c, sid, "CU_H3D_PREVIEW", {"source": source})
    assert w.run_once_slot() == "SUCCEEDED", job(c, pj["id"])
    pr = job(c, pj["id"])["result"]
    assert pr["sample_file"] == "run__00001/m_3/drop_A001.h3d" and pr["datatype_count"] == 2
    assert pr["part_counts"] == {"shell": 2, "solid": 1, "rbody": 0} and pr["num_time_step"] == 5 and pr["source_file_count"] == 2
    W = ai / "cu1" / "02_preview" / pj["id"]
    hw = [r for r in read_record(fake_record) if r["tool"] == "hw"][-1]
    F = lambda p: str(p).replace("\\", "/")  # noqa: E731 - h3d_preview 경로 값은 '/' 표기(phase2 §8.1)
    assert hw["argv"][1:] == ["-clientconfig", "hwpost.dat", "-b", "-tcl", F(d["resources"]["preview_h3d_tcl"]), "-h3d",
                              F(ai / "cu1" / "01_train" / "results" / doe_id / "run__00001" / "m_3" / "drop_A001.h3d"),
                              "-result", F(W / "PREVIEW_H3D.json")]
    summ = json.loads((W / "preview_summary.json").read_text())
    stress = next(x for x in summ["datatypes"] if x["name"] == "Stress")
    assert stress["usable"] == ["vonMises", "P1"]  # "Max Abs Principal"(3단어) 제외
    assert [f["rel"] for f in summ["files"]] == ["run__00001/m_3/drop_A001.h3d", "run__00002/m_3/drop_A001.h3d"]
    assert summ["files"][0]["run_folder"] == "run__00001"
    arts = c.get(f"{API}/jobs/{pj['id']}/artifacts", headers=P).json()
    assert [a["kind"] for a in arts] == ["PREVIEW_JSON", "PREVIEW_JSON"]
    sel = {"items": [{"datatype": "Stress", "component": "vonMises"}, {"datatype": "Displacement", "component": "X"}],
           "parts": {"shell": [1], "solid": [], "rbody": []}, "time_increment": 2}
    for bad in ({"items": [{"datatype": "Stress", "component": "Max"}]}, {"items": []},
                {"items": [{"datatype": "Nope", "component": "x"}]}, {"parts": {"shell": [99]}}):
        r = submit(c, sid, "CU_H3D_CURATE", {"source": source, "preview_job_id": pj["id"], "selection": {**sel, **bad}}, expect=422)
        assert r["detail"]["code"] in ("SELECTION_INVALID", "INVALID_PARAMS"), (bad, r)
    r = submit(c, sid, "CU_H3D_CURATE", {"source": source, "preview_job_id": "nope", "selection": sel}, expect=409)
    assert r["detail"]["code"] == "CURATION_PREVIEW_REQUIRED"
    monkeypatch.setenv("FAKE_TOOL_MODE_HVTRANS", "fail_match")
    monkeypatch.setenv("FAKE_FAIL_MATCH", "run__00002")
    cj = submit(c, sid, "CU_H3D_CURATE", {"source": source, "preview_job_id": pj["id"], "selection": sel})
    cid = cj["result"]["curation_id"]
    assert w.run_once_slot() == "SUCCEEDED", job(c, cj["id"])
    jd = job(c, cj["id"])
    assert jd["result"]["target_count"] == 2 and jd["result"]["ok_count"] == 1 and jd["result"]["failed_count"] == 1
    assert jd["result"]["missing_run_count"] == 2  # run__00002(실패) + run__00003(누락)
    assert any(x["code"] == "PARTIAL_OUTPUT" and x["message"] == "2개 중 1개 실패" for x in jd["warnings"])
    C = ai / "cu1" / "02_curated" / cid
    cfg = (C / "work" / "CURATE_H3D.cfg").read_text()
    assert cfg == ("BeginParts\n    BeginPool:Shell\n        1\n    EndPool\nEndParts\nBeginSubcase:1\n"
                   + "".join(f"    BeginSimulation:{s}\n        Stress|vonMises\n        Displacement\n    EndSimulation\n" for s in (1, 3, 5))
                   + "EndSubcase\nExtendedInfo: {1 0 1 0} {1 0 1 1}\n")
    assert (C / "CURATED_DATA" / "run__00001" / "drop_A001.h3d").read_bytes().endswith(b"|CURATED")
    hv = [r for r in read_record(fake_record) if r["tool"] == "hvtrans"]
    assert hv[0]["argv"][1:] == ["-c", str(C / "work" / "CURATE_H3D.cfg"),
                                 str(ai / "cu1" / "01_train" / "results" / doe_id / "run__00001" / "m_3" / "drop_A001.h3d")] * 1 + \
        [str(ai / "cu1" / "01_train" / "results" / doe_id / "run__00001" / "m_3" / "drop_A001.h3d"), "-o",
         str(C / "CURATED_DATA" / "run__00001" / "drop_A001.h3d"), "-z0"]
    assert hv[0]["cwd"] == str(C / "work")
    lines = (ai / "cu1" / "logs" / cj["id"] / "step_02_HVTRANS_CURATE.log").read_text()
    assert "=== [1/2] run__00001/m_3/drop_A001.h3d ===" in lines and "=== [2/2] run__00002/m_3/drop_A001.h3d ===" in lines
    cur = c.get(f"{API}/curations/{cid}", headers=P).json()
    assert cur["status"] == "READY" and cur["missing_runs"] == ["run__00002", "run__00003"] and cur["kind"] == "H3D"
    files = c.get(f"{API}/curations/{cid}/files?ok=false", headers=P).json()["items"]
    assert len(files) == 1 and files[0]["run_key"] == "run__00002" and files[0]["exit_code"] == 1
    job_cmd = c.get(f"{API}/jobs/{cj['id']}?include=commands", headers=H("tok-admin")).json()
    hvs = next(s for s in job_cmd["steps"] if s["step_key"] == "HVTRANS_CURATE")
    assert hvs["command"]["invocations"] == 2 and hvs["command"]["commands_rel"].endswith(".commands.jsonl")
    # 전부 실패 → FAILED, 출력 폴더 백업 이동
    monkeypatch.setenv("FAKE_TOOL_MODE_HVTRANS", "fail")
    cj2 = submit(c, sid, "CU_H3D_CURATE", {"source": source, "preview_job_id": pj["id"], "selection": sel})
    assert w.run_once_slot() == "FAILED"
    assert job(c, cj2["id"])["failure_code"] == "EXIT_NONZERO"
    assert c.get(f"{API}/curations/{cj2['result']['curation_id']}", headers=P).json()["status"] == "FAILED"
    # ③-1: curation_id 입력(둘 다 주면 422), used_by_dataset_ids
    r = submit(c, sid, "DATASET_CREATE", {"curation_id": cid, "input_path": "/x"}, expect=422)
    assert r["detail"]["code"] == "INVALID_PARAMS"
    monkeypatch.setenv("FAKE_TOOL_MODE_HVTRANS", "ok")
    monkeypatch.delenv("FAKE_FAIL_MATCH")
    cj3 = submit(c, sid, "CU_H3D_CURATE", {"source": source, "preview_job_id": pj["id"], "selection": sel})
    assert w.run_once_slot() == "SUCCEEDED"
    cid3 = cj3["result"]["curation_id"]
    dj = submit(c, sid, "DATASET_CREATE", {"curation_id": cid3})
    assert dj["params"]["input_path"] == str(ai / "cu1" / "02_curated" / cid3 / "CURATED_DATA")
    assert w.run_once_slot() == "SUCCEEDED", job(c, dj["id"])
    ds = c.get(f"{API}/datasets/{job(c, dj['id'])['result']['dataset_id']}", headers=P).json()
    assert ds["curation_id"] == cid3 and ds["h3d_count"] == 2
    assert c.get(f"{API}/curations/{cid3}", headers=P).json()["used_by_dataset_ids"] == [ds["id"]]
    # B23 확장: 2차 산출 폴더 입력 거부, 01_train/results는 허용
    for bad in (ai / "cu1" / "01_train" / "doe", ai / "cu1" / "02_preview", ai / "cu1" / "05_opt"):
        bad.mkdir(parents=True, exist_ok=True)
        r = submit(c, sid, "DATASET_CREATE", {"input_path": str(bad)}, expect=422)
        assert r["detail"]["code"] == "PATH_UNSAFE", bad
    ok = c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW,
                json={"purpose": "DATASET_INPUT", "path": str(ai / "cu1" / "01_train" / "results" / doe_id)}).json()
    assert ok["summary"]["h3d_count"] == 2


def test_t01_preview_and_curves(p2_env, fake_record, monkeypatch):
    """V2-CU-1·V2-CU-3: T01 미리보기, INPUT_CURATE_CURVE.json 골든, 한 번 호출, 출력 누락 표시, CURVE_JSON."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid = study(c, "t01")
    root = ai / "t01" / "00_inbox" / "t01"
    for rk in ("case_a", "case_b"):
        (root / rk / "sub").mkdir(parents=True)
        (root / rk / "sub" / "dropT01").write_text("T01")
    (root / "case_a" / "sub" / "ignore.T02").write_text("x")
    src = {"kind": "FOLDER", "path": str(root)}
    insp = c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "CURATION_INPUT", "path": str(root)}).json()
    assert insp["ok"] and insp["summary"] == {"h3d_count": 0, "t01_count": 2, "run_folders": ["case_a", "case_b"]}
    pj = submit(c, sid, "CU_T01_PREVIEW", {"source": src})
    assert w.run_once_slot() == "SUCCEEDED", job(c, pj["id"])
    W = ai / "t01" / "02_preview" / pj["id"]
    hw = [r for r in read_record(fake_record) if r["tool"] == "hw"][-1]
    F = lambda p: str(p).replace("\\", "/")  # noqa: E731 - t01_preview 경로 값은 '/' 표기(phase2 §8.1)
    assert hw["argv"][1:] == ["-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", F(d["resources"]["preview_hg_tcl"]), "-input",
                              F(root / "case_a" / "sub" / "dropT01"), "-output", F(W / "PREVIEW_T01.json")]
    assert job(c, pj["id"])["result"]["type_count"] == 1
    monkeypatch.setenv("FAKE_TOOL_MODE_HW", "skip_one")
    cj = submit(c, sid, "CU_T01_CURVES", {"source": src, "curves": [{"type": "Rigid Body", "request": "RBODY 1", "component": "F-Mag"}]})
    assert w.run_once_slot() == "SUCCEEDED", job(c, cj["id"])
    cid = cj["result"]["curation_id"]
    C = ai / "t01" / "02_curated" / cid
    inp = json.loads((C / "work" / "INPUT_CURATE_CURVE.json").read_text())
    assert inp == {"curves": [{"yDataType": "Rigid Body", "yRequest": "RBODY 1", "yComponent": "F-Mag"}],
                   "jobs": [{"inputFile": F(root / "case_a" / "sub" / "dropT01"), "outputFile": F(C / "CURVES" / "case_a" / "drop_curves.json")},
                            {"inputFile": F(root / "case_b" / "sub" / "dropT01"), "outputFile": F(C / "CURVES" / "case_b" / "drop_curves.json")}]}
    hws = [r for r in read_record(fake_record) if r["tool"] == "hw" and "-config" in r["argv"]]
    assert len(hws) == 1 and hws[0]["argv"][1:] == ["-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", F(d["resources"]["curate_hg_tcl"]),
                                                    "-config", F(C / "work" / "INPUT_CURATE_CURVE.json")]
    jd = job(c, cj["id"])
    assert jd["result"]["ok_count"] == 1 and jd["result"]["curve_artifact_id"]
    curve = c.get(f"{API}/artifacts/{jd['result']['curve_artifact_id']}/content", headers=P).json()
    assert curve["series"][0]["name"] == "F-Mag"
    files = c.get(f"{API}/curations/{cid}/files", headers=P).json()["items"]
    assert [f["ok"] for f in files] == [False, True]
    monkeypatch.setenv("FAKE_TOOL_MODE_HW", "no_output")
    cj2 = submit(c, sid, "CU_T01_CURVES", {"source": src, "curves": [{"type": "Rigid Body", "request": "RBODY 1", "component": "F-Mag"}]})
    assert w.run_once_slot() == "FAILED" and job(c, cj2["id"])["failure_code"] == "OUTPUT_MISSING"


def test_curation_units():
    """V2-CU-1·V2-CU-2: to_cfg_datacomp, run 폴더 이름 규칙, ExtendedInfo all 플래그, Parts 블록 없음."""
    from physicsai_core.stage2_curation import curation as cu

    assert [cu.to_cfg_datacomp(x) for x in ("vonMises", "Scalar value", "P1 (major)", "Max Abs Principal", "Extreme Principal", "")] == \
        ["vonMises", "Scalar", "P1", None, None, None]
    s = "/src"
    assert cu.run_folder_names(s, ["/src/output_0001/m3/x.h3d", "/src/output_0002/m3/x.h3d"]) == ["output_0001", "output_0002"]
    assert cu.run_folder_names(s, ["/src/a/x.h3d", "/src/b/x.h3d"]) == ["a", "b"]
    assert cu.run_folder_names(s, ["/src/x.h3d", "/src/y.h3d"]) == ["x", "y"]
    assert cu.run_folder_names(s, ["/src/a/m/x.h3d", "/src/m/y.h3d"]) == ["x", "y"]  # 깊이 다르면(ok=False) 파일 stem
    cfg = cu.hvtrans_cfg({"items": [{"datatype": "Stress", "component": "vonMises"}, {"datatype": "Stress", "component": "P1"}],
                          "parts": {}, "time_increment": 1}, {"Stress": ["vonMises", "P1 (major)", "Max Abs Principal"]}, 2)
    assert cfg.startswith("BeginParts\nEndParts\nBeginSubcase:1\n") and cfg.endswith("ExtendedInfo: {1 0 1 1} {1 0 1 1}\n")
    assert cu.time_steps(5, 2) == [1, 3, 5] and cu.time_steps(0, 1) == []
