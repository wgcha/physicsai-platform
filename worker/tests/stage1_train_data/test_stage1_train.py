"""①-1 추출 → ①-2 파라미터 표·tpl → ①-3 DOE 생성(샘플 추출 포함), ①-4 회수 모드(shared_folder·drive)·회수 루트 설정 검증.

V2-TD-1·2·4·6, V2-LCH-1, V2-CMD-1(①). ①-4 제출·취소는 test_stage1_solve, ①-5·①-6·F는 test_stage1_results.
"""

from __future__ import annotations

import copy
import csv
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from helpers_stage1 import _ready_doe, _write_results, doe_gen, extract_and_tpl, job, make_inputs, study, submit
from physicsai_test_support import API, H, _p2_env, pbs_command_cfg, read_record

PW, P, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin", write=True)


def test_extract_chain_and_params(p2_env, fake_record, engine):
    """V2-TD-1·V2-TD-2·V2-LCH-1: 추출 체인·진행률·XML 파싱·런처 복사·표 저장 검증."""
    c, mk, ai, lc, _d = p2_env
    w = mk()
    sid = study(c, "tx1")
    cad, _assem = make_inputs(ai / "tx1")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    jd = job(c, j["id"])
    assert jd["result"]["param_count"] == 3 and jd["result"]["valid_count"] == 2
    X = ai / "tx1" / "01_train" / "extract" / j["id"]
    # 런처·pyd 복사(내용 그대로) + sha256 기록
    assert (X / "BATCHRUN_get_parameter_from_cad.py").read_text().startswith("# Generated launcher;")
    assert list(X.glob("get_parameter_from_cad_core*.pyd"))
    with engine.connect() as conn:
        outs = conn.execute(text("select outputs from job_steps where job_id=:j and step_key='TX_PREP'"), {"j": j["id"]}).scalar()
    assert all("sha256" in f for f in outs["files"]) and len(outs["files"]) == 2
    rec = [r for r in read_record(fake_record) if r["tool"] == "simlab"][-1]
    assert rec["argv"][1:] == ["-auto", str(X / "BATCHRUN_get_parameter_from_cad.py"),
                               str(ai / "tx1" / "01_train" / "cad" / "cushion_parametric.prt"),
                               str(X / "parameter_extracted.xml"), "-nographics"]
    assert rec["cwd"] == str(X)
    steps = {s["step_key"]: s for s in jd["steps"]}
    assert steps["SIMLAB_EXTRACT"]["state"] == "SUCCEEDED"
    log = c.get(f"{API}/jobs/{j['id']}/steps/2/log", headers=P).json()["text"]
    assert "Passed" in log and "_LogFile.txt 꼬리" in log
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    by = {p["name"]: p for p in ts["parameters"]}
    assert by["THK_1"]["nominal"] == 3.0 and by["THK_1"]["raw_nominal"] == "3" and by["THK_1"]["min"] == 2.85 and by["THK_1"]["max"] == 3.15
    assert by["THK_1"]["format"] == "%3i" and by["THK_1"]["use"] is True
    assert by["RIB_H"]["nominal"] == 12.5
    assert by["bad name"]["valid"] is False and "NAME_INVALID" in by["bad name"]["problems"] and by["bad name"]["use"] is False
    assert ts["cad"]["file_name"] == "cushion_parametric.prt" and ts["tpl"] is None
    # 저장 검증
    def put(rows, version):
        return c.put(f"{API}/studies/{sid}/train/params", headers=PW, json={"version": version, "parameters": rows})

    base = [{"name": n, "min": by[n]["min"], "max": by[n]["max"], "use": by[n]["use"], "format": by[n]["format"]} for n in by]
    bad = copy.deepcopy(base)
    bad[0]["min"], bad[0]["max"] = 5, 4
    r = put(bad, ts["version"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TRAIN_PARAMS_INVALID"
    assert {p["code"] for p in r.json()["detail"]["problems"]} == {"RANGE_INVALID"}
    bad = copy.deepcopy(base)
    bad[1]["format"] = "%s"
    assert put(bad, ts["version"]).json()["detail"]["problems"][0]["code"] == "FORMAT_INVALID"
    bad = copy.deepcopy(base)
    for b in bad:
        b["use"] = False
    assert put(bad, ts["version"]).json()["detail"]["problems"][-1]["code"] == "NO_PARAMETER_USED"
    assert put(base[:2], ts["version"]).status_code == 422  # 모든 행
    assert put(base, ts["version"] + 7).json()["detail"]["code"] == "VERSION_CONFLICT"
    ok = put(base, ts["version"])
    assert ok.status_code == 200 and ok.json()["version"] == ts["version"] + 1
    assert json.loads((ai / "tx1" / "01_train" / "params.json").read_text())["schema_version"] == 1
    # tpl 생성 + 정수 형식 경고(RIB_H 12.5 + %3i)
    r = c.post(f"{API}/studies/{sid}/train/tpl", headers=PW, json={"version": ok.json()["version"]})
    assert r.status_code == 200, r.text
    tpl = r.json()["tpl"]
    assert tpl["stale"] is False and [p["name"] for p in tpl["params"]] == ["THK_1", "RIB_H"]
    assert tpl["warnings"][0]["code"] == "TPL_INTEGER_FORMAT" and "RIB_H" in tpl["warnings"][0]["message"]
    text_ = (ai / "tx1" / "01_train" / "tpl" / "simlab_parametered_mesh.tpl").read_text()
    assert '{parameter(var_2, "RIB_H", 12.5, 11.875, 13.125)}' in text_ and 'dir_file_prt = r"./cushion_parametric.prt"' in text_
    assert (ai / "tx1" / "01_train" / "tpl" / "TEMAPLATE_simlab_parametered_mesh.tpl").is_file()
    # 표가 바뀌면 stale → DOE 생성 409 TPL_STALE
    v = r.json()["version"]
    changed = copy.deepcopy(base)
    changed[0]["max"] = 3.3
    v = put(changed, v).json()["version"]
    assert c.get(f"{API}/studies/{sid}/train", headers=P).json()["tpl"]["stale"] is True
    r = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LatinHyperCube", "num_runs": 3, "options": {"RANDOM_SEED": 1},
                                      "radioss_assem_path": str(ai / "tx1" / "00_inbox" / "radioss_assem")}, expect=409)
    assert r["detail"]["code"] == "TPL_STALE"
    # 재추출하면 이전 표·params.json 백업 이동
    j2 = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j2["id"])
    assert list((ai / "tx1" / "_backup").rglob("params.json"))


def test_extract_failures(p2_env, monkeypatch):
    """V2-TD-1: DOCTYPE 거부, 출력 없음, pyd 0개·2개 → RESOURCE_MISSING."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid = study(c, "tx2")
    cad, _ = make_inputs(ai / "tx2")
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "bad_xml")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert w.run_once_slot() == "FAILED"
    jd = job(c, j["id"])
    assert jd["failure_code"] == "INPUT_INVALID" and "DOCTYPE" in jd["failure_message"]
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "no_output")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert w.run_once_slot() == "FAILED" and job(c, j["id"])["failure_code"] == "OUTPUT_MISSING"
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "ok")
    pyd_dir = Path(d["resources"]["pyd_dir"])
    extra = pyd_dir / "get_parameter_from_cad_core.cp312-win_amd64.pyd"
    extra.write_bytes(b"x")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert w.run_once_slot() == "FAILED"
    jd = job(c, j["id"])
    assert jd["failure_code"] == "RESOURCE_MISSING" and "2개" in jd["failure_message"]
    os.replace(extra, ai / "moved.pyd")
    os.replace(next(pyd_dir.glob("get_parameter_from_cad_core*")), ai / "moved2.pyd")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert w.run_once_slot() == "FAILED" and "0개" in job(c, j["id"])["failure_message"]
    # 확장자·경로
    other = ai / "tx2" / "00_inbox" / "cad" / "x.step"
    other.write_text("x")
    r = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(other)}, expect=422)
    assert r["detail"]["code"] == "INVALID_PARAMS"
    r = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(ai / "_platform" / "a.prt")}, expect=422)
    assert r["detail"]["code"] == "PATH_UNSAFE"


def test_doe_gen_chain(p2_env, fake_record, monkeypatch):
    """V2-TD-4: DOE 유형·options·INPUT_HST_RUN.json 키·assem 사본·진행률·오류 정규식·run 스캔·샘플 추출."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid = study(c, "dg1")
    cad, _ = make_inputs(ai / "dg1")
    extract_and_tpl(c, w, sid, cad)
    types = c.get(f"{API}/train/doe-types", headers=P).json()
    assert [t["label"] for t in types] == ["FullFact", "FracFact", "LatinHyperCube", "Sobol"]
    assert types[0]["runs_editable"] is False
    base = {"doe_label": "LatinHyperCube", "options": {"RANDOM_SEED": 1}, "radioss_assem_path": str(ai / "dg1" / "00_inbox" / "radioss_assem")}
    for bad, code in [({"doe_label": "Nope"}, "DOE_TYPE_UNKNOWN"), ({"options": {"RANDOM_SEED": -1}}, "DOE_OPTIONS_INVALID"),
                      ({"options": {}}, "DOE_OPTIONS_INVALID"), ({"options": {"RANDOM_SEED": 1, "X": 1}}, "DOE_OPTIONS_INVALID"),
                      ({"doe_label": "FullFact", "options": {}, "num_runs": 5}, "DOE_OPTIONS_INVALID"),
                      ({"num_runs": 999999}, "DOE_OPTIONS_INVALID"), ({"multi_execution": 99}, "INVALID_PARAMS")]:
        r = submit(c, sid, "TD_DOE_GEN", {**base, **bad}, expect=422)
        assert r["detail"]["code"] == code, (bad, r)
    r = submit(c, sid, "TD_DOE_GEN", {"doe_label": "FracFact", "options": {"RESOLUTION": "6"}, "radioss_assem_path": base["radioss_assem_path"]}, expect=422)
    assert r["detail"]["code"] == "DOE_OPTIONS_INVALID"
    jd = doe_gen(c, w, sid, ai, "dg1")
    doe_id = jd["result"]["doe_id"]
    assert jd["result"]["run_count"] == 3 and jd["result"]["sample_status"] == "PARSED"
    D = ai / "dg1" / "01_train" / "doe" / doe_id
    cfg = json.loads((D / "INPUT_HST_RUN.json").read_text())
    assert set(cfg) == {"HST_EXECUTABLE", "ALTAIR_PATHS", "DOE_NUM_RUNS", "DIR_WORK", "CAD_PARAM", "RADIOSS_ASSEM_DIR", "DOE_TYPE",
                        "DOE_METHOD_OPTIONS", "MULTI_EXECUTION"}
    assert set(cfg["ALTAIR_PATHS"]) == {"hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path"}
    assert cfg["DOE_TYPE"] == "TYPE_LATINHYPERCUBE" and cfg["DOE_NUM_RUNS"] == 3 and cfg["MULTI_EXECUTION"] == 2
    assert cfg["DOE_METHOD_OPTIONS"] == {"RANDOM_SEED": 7} and cfg["DIR_WORK"] == str(D).replace("\\", "/")
    assert cfg["RADIOSS_ASSEM_DIR"].endswith(f"01_train/radioss_assem/{doe_id}")
    A = ai / "dg1" / "01_train" / "radioss_assem" / doe_id
    assert sorted(os.listdir(A)) == ["RENUM_INIT.csv", "drop_0000.rad", "drop_0001.rad", "eps_mesh_0000.rad", "mat.inc"]
    for n in ("simlab_parametered_mesh.tpl", "cushion_parametric.prt", "DATA_doe_design_type.json",
              "BATCHRUN_create_include_node_elem.tcl", "BATCHRUN_hst_gen_radioss_input.py"):
        assert (D / n).is_file(), n
    assert list(D.glob("hst_gen_radioss_core*.pyd"))
    rec = [r for r in read_record(fake_record) if r["tool"] == "hstbatch"][-1]
    assert rec["argv"][1:] == ["-multiexec", "2", "-pyfile", str(D / "BATCHRUN_hst_gen_radioss_input.py").replace("\\", "/")]
    assert rec["cwd"] == str(D)
    rows = list(csv.reader((D / "samples.csv").open()))
    assert rows[0] == ["run_key", "THK_1", "RIB_H"] and [r[0] for r in rows[1:]] == ["run__00001", "run__00002", "run__00003"]
    assert float(rows[1][1]) == round(2.85 + 0.3 / 4) or float(rows[1][1]) == 3.0  # %3i 정수 반영
    runs = json.loads((D / "runs.json").read_text())
    assert runs[0] == {"run_key": "run__00001", "input_rel": f"01_train/doe/{doe_id}/approaches/doe_1/run__00001/m_3",
                       "starter_name": "drop_0000.rad"}
    doe = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert doe["status"] == "READY" and doe["run_state_counts"]["GENERATED"] == 3
    rr = c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()
    assert [r["state"] for r in rr] == ["GENERATED"] * 3
    sm = c.get(f"{API}/train-does/{doe_id}/samples", headers=P).json()
    assert sm["columns"] == ["run_key", "THK_1", "RIB_H"] and len(sm["rows"]) == 3
    arts = {a["kind"] for a in c.get(f"{API}/jobs/{jd['id']}/artifacts", headers=P).json()}
    assert arts == {"RUN_CONFIG", "DOE_SAMPLES"}
    # 진행률(Finished run) 반영
    with_steps = {s["step_key"]: s for s in jd["steps"]}
    assert with_steps["HST_GEN_RADIOSS"]["progress_pct"] == 100.0
    # 오류 정규식 → LOG_ERROR_DETECTED(종료코드 0이어도), DOE FAILED
    monkeypatch.setenv("FAKE_TOOL_MODE_HSTBATCH", "error_log")
    jd2 = doe_gen(c, w, sid, ai, "dg1", expect="FAILED")
    assert jd2["failure_code"] == "LOG_ERROR_DETECTED"
    assert c.get(f"{API}/train-does/{jd2['result']['doe_id']}", headers=P).json()["status"] == "FAILED"
    monkeypatch.setenv("FAKE_TOOL_MODE_HSTBATCH", "no_runs")
    jd3 = doe_gen(c, w, sid, ai, "dg1", expect="FAILED")
    assert jd3["failure_code"] == "OUTPUT_MISSING" and "run_dir_glob" in jd3["failure_message"]
    monkeypatch.setenv("FAKE_TOOL_MODE_HSTBATCH", "partial_samples")
    jd4 = doe_gen(c, w, sid, ai, "dg1")
    assert jd4["result"]["sample_status"] == "PARTIAL" and any(x["code"] == "SAMPLES_PARTIAL" for x in jd4["warnings"])
    # starter 0개 run은 제외 + 경고
    monkeypatch.setenv("FAKE_TOOL_MODE_HSTBATCH", "ok")
    assem = ai / "dg1" / "00_inbox" / "radioss_assem"
    os.replace(assem / "drop_0000.rad", ai / "moved.rad")
    r = submit(c, sid, "TD_DOE_GEN", {**base}, expect=409)
    assert r["detail"]["code"] == "PREREQUISITE_MISSING" and r["detail"]["missing"] == ["RADIOSS_STARTER"]


def test_doe_samples_extractors(tmp_path):
    """V2-TD-4: paramitem 미렌더 건너뜀, csv(var_i 열), none."""
    from physicsai_core.config import TrainDataCfg
    from physicsai_core.stage1_train_data import doe_samples

    rd = tmp_path / "run__1"
    (rd / "a").mkdir(parents=True)
    (rd / "a" / "x.py").write_text('<paramitem Name="A" NewValue="{var_1, %3i}" Value="1"/>\n')
    (rd / "a" / "y.txt").write_text('<paramitem Name="A" NewValue="  4" Value="1"/>\n<paramitem Name="B" NewValue="2.5" Value="1"/>\n')
    td = TrainDataCfg()
    vals, src = doe_samples.paramitem_values(str(rd), ["A", "B"], td)
    assert vals == {"A": 4.0, "B": 2.5} and src == "a/y.txt"
    (tmp_path / "s.csv").write_text("run_key,var_1,var_2\nrun__1,1,2\n")
    td2 = TrainDataCfg(samples_extractor="csv", samples_csv_glob="s.csv")
    r = doe_samples.extract(str(tmp_path), [{"run_key": "run__1", "run_dir": str(rd)}, {"run_key": "run__2", "run_dir": str(rd)}], ["A", "B"], td2)
    assert r.status == "PARTIAL" and r.rows == [{"run_key": "run__1", "values": {"A": 1.0, "B": 2.0}}] and r.missing_runs == ["run__2"]
    assert doe_samples.extract(str(tmp_path), [], ["A"], TrainDataCfg(samples_extractor="none")).status == "MISSING"


@pytest.mark.parametrize("mode", ["shared_folder", "drive"])
def test_collect_shared_folder(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, pbs_state, mode):
    """V2-TD-6: shared_folder·drive 복사(원본 미삭제), result_dir = collect_root_remote/…."""
    ai = tmp_path / "ai_root"
    ai.mkdir()
    shared = tmp_path / "pbs_share"
    shared.mkdir()
    hpc = pbs_command_cfg(fake_tools, str(ai))
    hpc["transfer"] = {**hpc["transfer"], "collect_mode": mode, "collect_root_local": str(shared), "collect_root_remote": "/pbs/share"}
    gen = _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {"hpc": hpc})
    c, mk, ai, lc, d = next(gen)
    try:
        w = mk()
        sid, doe_id = _ready_doe(c, w, ai, "sh1", num_runs=2)
        j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
        assert w.run_once_slot() == "WAITING_HPC"
        for _ in range(3):
            w.poll_hpc_once()
        _write_results(ai, "sh1", doe_id, ["run__00001", "run__00002"], base=shared / "sh1" / doe_id)
        assert w.run_once_collect() == "QUEUED"
        assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
        R = ai / "sh1" / "01_train" / "results" / doe_id / "run__00001"
        assert sorted(os.listdir(R)) == ["drop_0000.out", "drop_A001.h3d", "drop_T01"]
        assert (shared / "sh1" / doe_id / "run__00001" / "drop_A001.h3d").is_file()  # 원본 유지
    finally:
        for _ in gen:
            pass


def test_collect_roots_config_validation(settings_dict, tmp_path):
    """V2-TD-6: collect 루트 누락·AI 루트 겹침·SPDM 겹침 설정 오류."""
    from physicsai_core.config import load_config_dict

    d = copy.deepcopy(settings_dict)
    d["hpc"] = {"transfer": {"collect_mode": "shared_folder"}}
    keys = load_config_dict(d, environ={}).error_keys()
    assert "hpc.transfer.collect_root_local" in keys and "hpc.transfer.collect_root_remote" in keys
    d["hpc"] = {"transfer": {"collect_mode": "drive", "collect_root_local": d["storage"]["ai_root"], "collect_root_remote": "/x"}}
    assert "hpc.transfer.collect_root_local" in load_config_dict(d, environ={}).error_keys()
    sp = tmp_path / "spdm"
    sp.mkdir(exist_ok=True)
    d["hpc"] = {"transfer": {"collect_mode": "drive", "collect_root_local": str(sp), "collect_root_remote": "/x"}}
    assert "hpc.transfer.collect_root_local" in load_config_dict(d, environ={}).error_keys()


