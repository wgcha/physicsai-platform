"""② 데이터 정리·G SPDM 가져오기·③-1 큐레이션 입력(V2-CU-1~4, V2-SPDM-1~3, V2-CMD-1(②), V2-CMD-3)."""

from __future__ import annotations

import builtins
import json
import os
import stat
from pathlib import Path

import pytest

from physicsai_test_support import API, H, read_record
from phase2_helpers import _ready_doe, _write_results, job, study, submit

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
                   "jobs": [{"inputFile": str(root / "case_a" / "sub" / "dropT01"), "outputFile": str(C / "CURVES" / "case_a" / "drop_curves.json")},
                            {"inputFile": str(root / "case_b" / "sub" / "dropT01"), "outputFile": str(C / "CURVES" / "case_b" / "drop_curves.json")}]}
    hws = [r for r in read_record(fake_record) if r["tool"] == "hw" and "-config" in r["argv"]]
    assert len(hws) == 1 and hws[0]["argv"][1:] == ["-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", d["resources"]["curate_hg_tcl"],
                                                    "-config", str(C / "work" / "INPUT_CURATE_CURVE.json")]
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
    from physicsai_core import curation as cu

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


@pytest.fixture()
def spdm_tree(p2_env):
    c, mk, ai, lc, d = p2_env
    root = Path(d["storage"]["spdm_roots"][0])
    case = root / "PRJ" / "Case 01" / "Scene&1"
    case.mkdir(parents=True)
    (case / "a.h3d").write_bytes(b"H3D" * 1000)
    (case / "b_T01").write_text("T01")
    (case / "c.txt").write_text("skip")
    (case / "CON.h3d").write_bytes(b"x")
    os.symlink(case / "a.h3d", case / "link.h3d")
    outside = ai.parent / "outside"
    outside.mkdir()
    os.symlink(outside, root / "PRJ" / "linkdir")
    return root


def _snapshot(root: Path) -> dict[str, tuple]:
    out = {}
    for dp, dns, fns in os.walk(root):
        for n in dns + fns:
            p = os.path.join(dp, n)
            st = os.lstat(p)
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns, stat.S_IMODE(st.st_mode), st.st_nlink)
    return out


def test_spdm_import_read_only(p2_env, spdm_tree, monkeypatch):
    """V2-SPDM-1·V2-SPDM-2: 경로 검사(공백 허용·루트 밖·링크·..), 스냅샷 불변, 쓰기 계열 0, 하드링크 아님, 이름 정리·manifest."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid = study(c, "sp1")
    spdm_path = str(spdm_tree / "PRJ" / "Case 01")
    insp = c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "SPDM_IMPORT", "path": spdm_path}).json()
    assert insp["ok"] and insp["summary"]["h3d_count"] == 2 and insp["summary"]["t01_count"] == 1 and insp["summary"]["renamed_count"] == 3
    for bad, code in [(str(ai), "PATH_OUTSIDE_ROOT"), (spdm_path + "/../..", "PATH_UNSAFE"),
                      (str(spdm_tree / "PRJ" / "linkdir"), "PATH_UNSAFE"), (str(spdm_tree / "nope"), "PATH_NOT_FOUND")]:
        r = submit(c, sid, "SPDM_IMPORT", {"spdm_path": bad}, expect=422)
        assert r["detail"]["code"] == code, bad
    before = _snapshot(spdm_tree)
    writes: list[str] = []
    real_open = builtins.open
    root_s = str(spdm_tree)

    def guard_open(file, mode="r", *a, **kw):  # noqa: ANN001
        if isinstance(file, (str, os.PathLike)) and str(file).startswith(root_s) and any(ch in mode for ch in "wax+"):
            writes.append(f"open {file} {mode}")
        return real_open(file, mode, *a, **kw)

    def guard(name):
        orig = getattr(os, name)

        def f(*a, **kw):
            if any(isinstance(x, (str, os.PathLike)) and str(x).startswith(root_s) for x in a[:2]):
                if name != "utime" or str(a[0]).startswith(root_s):
                    writes.append(f"{name} {a[:2]}")
            return orig(*a, **kw)
        return f

    j = submit(c, sid, "SPDM_IMPORT", {"spdm_path": spdm_path})
    monkeypatch.setattr(builtins, "open", guard_open)
    for n in ("utime", "chmod", "rename", "replace", "link", "symlink", "remove", "unlink", "mkdir", "makedirs"):
        monkeypatch.setattr(os, n, guard(n))
    try:
        assert w.run_once_light() == "SUCCEEDED", job(c, j["id"])
    finally:
        monkeypatch.undo()
    assert writes == []
    assert _snapshot(spdm_tree) == before
    res = job(c, j["id"])["result"]
    iid = res["import_id"]
    I = ai / "sp1" / "02_import" / iid
    assert res["file_count"] == 3 and res["renamed_count"] == 3
    a_dst = I / "Scene_1" / "a.h3d"
    src_a = spdm_tree / "PRJ" / "Case 01" / "Scene&1" / "a.h3d"
    assert a_dst.read_bytes() == src_a.read_bytes()
    assert os.stat(a_dst).st_ino != os.stat(src_a).st_ino and os.stat(a_dst).st_nlink == 1
    assert os.stat(a_dst).st_mtime_ns == os.stat(src_a).st_mtime_ns
    assert (I / "Scene_1" / "_CON.h3d").is_file() and not (I / "Scene_1" / "link.h3d").exists()
    man = json.loads((I / "import_manifest.json").read_text())
    assert {f["source_rel"] for f in man["files"]} == {"Scene&1/a.h3d", "Scene&1/b_T01", "Scene&1/CON.h3d"}
    imps = c.get(f"{API}/studies/{sid}/spdm-imports", headers=P).json()
    assert imps[0]["status"] == "READY" and imps[0]["file_count"] == 3
    # ② 원천으로 사용
    srcs = c.get(f"{API}/studies/{sid}/curation-sources", headers=P).json()
    assert srcs[0]["kind"] == "SPDM_IMPORT" and srcs[0]["h3d_count"] == 2
    pj = submit(c, sid, "CU_H3D_PREVIEW", {"source": {"kind": "SPDM_IMPORT", "import_id": iid}})
    assert w.run_once_slot() == "SUCCEEDED", job(c, pj["id"])


def test_spdm_disabled_and_write_helpers_refuse(p2_env, tmp_path):
    """V2-SPDM-1·V2-SPDM-3: spdm_roots 비면 409, 쓰기 헬퍼가 SPDM 경로에서 예외."""
    from physicsai_core.errors import StepFailure
    from physicsai_core.fileutil import copy_file, write_json
    from physicsai_core.paths import backup_existing

    c, mk, ai, lc, d = p2_env
    sp = Path(d["storage"]["spdm_roots"][0])
    (sp / "f.h3d").write_text("x")
    with pytest.raises(StepFailure):
        write_json(str(sp / "x.json"), {})
    with pytest.raises(StepFailure):
        copy_file(str(sp / "f.h3d"), str(sp / "g.h3d"))
    with pytest.raises(StepFailure):
        backup_existing(str(ai), [str(sp / "f.h3d")], "j")
    assert not (sp / "x.json").exists() and not (sp / "g.h3d").exists()
    from physicsai_core.config import load_config_dict
    import httpx
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    d2 = dict(d)
    d2["storage"] = {**d["storage"], "spdm_roots": []}
    lc2 = load_config_dict(d2, environ={})
    assert lc2.ok, lc2.issues
    ctx = build_context(lc2, mk().engine, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "id": "u-power", "username": "p", "display_name": "p", "account_status": "ACTIVE", "is_global_admin": False,
        "memberships": [{"project_id": "p-1", "role": "power"}]} if r.url.path == "/api/auth/me" else [{"id": "p-1", "name": "x"}])))
    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c2:
        sid = c2.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": "nospdm", "title": "x"}).json()["id"]
        r = c2.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "SPDM_IMPORT", "params": {"spdm_path": "/x"}})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "SPDM_IMPORT_DISABLED"
        st = c2.get(f"{API}/status", headers=P).json()
        assert st["features"]["spdm_import"] == {"enabled": False, "missing": ["storage.spdm_roots"]}
