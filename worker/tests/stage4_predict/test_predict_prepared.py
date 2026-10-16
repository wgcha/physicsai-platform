"""④ 준비된 입력 예측(phase3 §11.5, V3-S6-7·8·11): 복사 규칙, step 2~4 SKIPPED, 응답 표, 검증·input.zip·재시도. 원본 폴더 불변.
D3-36·37 후속: 재시도 시 이전 INPUT → _backup, EDSPY_PREDICT 판정 = h3d 존재(parametric 재시도 포함)."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

from physicsai_test_support import API, MESH_INC, H, pbs_command_cfg, read_record

P = H("tok-power")
PW = H("tok-power", write=True)


def make_case(root: Path, name: str = "case_A") -> Path:
    d = root / name
    (d / "sub").mkdir(parents=True)
    (d / "Face_Drop_0000.rad").write_text("#include part.inc\n/BEGIN\n")
    (d / "Face_Drop_0001.rad").write_text("/ENGINE\n")
    (d / "part.inc").write_text("/NODE\n1 0 0 0\n")
    (d / "EPS_mesh_0000.rad").write_text("simlab mesh\n")
    (d / "eps_mesh_1.inc").write_text("simlab inc\n")
    (d / "notes.txt").write_text("not copied\n")
    (d / "sub" / "deep.inc").write_text("not copied\n")
    return d


# make_case의 복사 대상(D3-44: eps_mesh 포함 직계 *.rad·*.inc 전부)
PREP_INPUT = ["EPS_mesh_0000.rad", "Face_Drop_0000.rad", "Face_Drop_0001.rad", "eps_mesh_1.inc", "part.inc"]


def snapshot(d: Path) -> dict[str, float]:
    return {str(p.relative_to(d)): p.stat().st_mtime_ns for p in sorted(d.rglob("*"))}


def run_prepared(env, path: Path, expect_state="SUCCEEDED", **extra):
    j = env.submit("PREDICT", {"input_mode": "prepared", "input_path": str(path), **extra})
    st = env.w.run_once_slot()
    jd = env.job(j["id"])
    assert st == expect_state, jd
    return j["id"], jd


@pytest.mark.parametrize("use_dir", [False, True])
def test_v3_s6_7_prepared_rad_file_and_folder(predict_env, fake_record, use_dir):
    env = predict_env(commands={"geom_update": None})                   # 형상 갱신 설정 없이도 동작
    case = make_case(env.imports)
    before = snapshot(case)
    jid, jd = run_prepared(env, case if use_dir else case / "Face_Drop_0000.rad")
    assert jd["params"] == {"input_mode": "prepared", "input_path": str(case if use_dir else case / "Face_Drop_0000.rad"),
                            "input_kind": "dir" if use_dir else "file", "starter_name": "Face_Drop_0000.rad",
                            "model_id": env.model_id, "param_set_id": None}
    Pd = env.predict_dir(jid)
    # D3-44: 준비된 입력은 직계 *.rad·*.inc 전부(eps_mesh 포함 — starter가 include할 수 있음), txt·하위 폴더 제외
    assert sorted(os.listdir(Pd / "INPUT")) == PREP_INPUT
    assert (Pd / "INPUT" / "eps_mesh_1.inc").read_text() == "simlab inc\n"
    steps = env.steps(jid)
    for k in ("TPL_RENDER", "GEOM_UPDATE", "MESH"):
        assert steps[k]["state"] == "SKIPPED" and steps[k]["progress_label"] == "준비된 입력 — 해당 없음", k
    pred = [r for r in read_record(fake_record) if "--predict-write" in r["argv"]][-1]
    assert pred["argv"][pred["argv"].index("--input-file") + 1] == str(Pd / "INPUT" / "Face_Drop_0000.rad")
    assert pred["cwd"] == str(Pd / "INPUT")
    assert not [r for r in read_record(fake_record) if r["tool"] == "simlab"]
    res = jd["result"]
    assert res["starter"] == "Face_Drop_0000.rad" and res["preview_json_artifact_id"] and res["curve_artifact_id"]
    assert res["input_mode"] == "prepared" and res["values"] == {} and res["nearest"] is None and res["response_table"] == []
    assert snapshot(case) == before                                      # 원본 폴더 목록·mtime 불변


def test_v3_s6_7_prepared_hm_copies_only_that_file(predict_env, fake_record):
    env = predict_env()
    case = make_case(env.imports, "case_hm")
    (case / "drop_model.hm").write_bytes(b"HM" * 10)
    jid, jd = run_prepared(env, case / "drop_model.hm")
    Pd = env.predict_dir(jid)
    assert os.listdir(Pd / "INPUT") == ["drop_model.hm"]
    pred = [r for r in read_record(fake_record) if "--predict-write" in r["argv"]][-1]["argv"]
    assert pred[pred.index("--input-file") + 1] == str(Pd / "INPUT" / "drop_model.hm")
    assert pred[pred.index("--predict-write") + 1] == str(Pd / "RESULT" / "drop_model_pred.h3d")


def test_v3_s6_8_prepared_response_table(predict_env):
    env = predict_env(commands={"response_extract": ["{hw}", "--responses", "{responses_json}", "--input", "{pred_h3d}", "--out", "{out_csv}"]})
    case = make_case(env.imports)
    jid, jd = run_prepared(env, case)                                     # 세트 없음 → SKIPPED·[]
    steps = env.steps(jid)
    assert steps["RESPONSE_EXTRACT"]["state"] == steps["RESPONSE_TABLE"]["state"] == "SKIPPED"
    assert jd["result"]["response_table"] == []
    ps = env.param_set()                                                  # 현재 세트 = 응답 목록용
    jid, jd = run_prepared(env, case)
    assert jd["params"]["param_set_id"] == ps["id"]
    assert jd["result"]["response_table"] == [
        {"name": "MaxStress", "unit": "MPa", "predicted": 110.0, "nearest_measured": None, "diff_pct": None},
        {"name": "Disp", "unit": "mm", "predicted": 111.0, "nearest_measured": None, "diff_pct": None},
    ]


def test_v3_s6_7_input_changed_after_submit(predict_env):
    env = predict_env()
    case = make_case(env.imports)
    j = env.submit("PREDICT", {"input_mode": "prepared", "input_path": str(case)})
    (case / "Other_0000.rad").write_text("second starter\n")             # 등록 뒤 starter가 2개가 됨
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(j["id"])
    assert jd["failure_code"] == "INPUT_CHANGED" and jd["current_step_key"] == "PR_PREP"


def test_v3_s6_11_prepared_verify_zip_and_retry(predict_env, fake_tools, fake_record, pbs_state, monkeypatch, tmp_path):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.05)
    env = predict_env(hpc=pbs_command_cfg(fake_tools, str(tmp_path / "ai_root")))
    case = make_case(env.imports)
    # 재시도: EDSPY 실패 → RAD_ASSEMBLE(5단계)부터 재시도하면 INPUT을 다시 만들고 성공
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "fail")
    jid, jd = run_prepared(env, case, expect_state="FAILED")
    assert jd["current_step_key"] == "EDSPY_PREDICT"
    monkeypatch.delenv("FAKE_TOOL_MODE_EDSPY")
    r = env.c.post(f"{API}/jobs/{jid}/retry", headers=PW, json={"from_step": 5})
    assert r.status_code in (200, 201), r.text
    nid = r.json()["id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(nid)
    steps = env.steps(nid)
    assert [steps[k]["state"] for k in ("PR_PREP", "RAD_ASSEMBLE", "EDSPY_PREDICT")] == ["SKIPPED", "SUCCEEDED", "SUCCEEDED"]
    Pd = env.predict_dir(jid)                                             # 재시도 묶음 root 폴더
    assert sorted(os.listdir(Pd / "INPUT")) == PREP_INPUT
    # input.zip
    z = env.c.get(f"{API}/jobs/{nid}/artifacts/input.zip", headers=P)
    assert z.status_code == 200
    assert sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == PREP_INPUT
    # PBS 검증: P/INPUT 기준 starter로 제출
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_VERIFY", "params": {"predict_job_id": nid}})
    assert r.status_code == 201, r.text
    assert env.w.run_once_slot() == "WAITING_HPC", env.job(r.json()["id"])
    sub = [x for x in read_record(fake_record) if x["tool"] == "qsub"][-1]["argv"]
    v_arg = sub[sub.index("-v") + 1]
    assert v_arg.startswith("INPUT_FILE=/shared/AI_WORK/pred/04_predict/") and "/verify/1/input/Face_Drop_0000.rad," in v_arg
    assert sorted(os.listdir(Pd / "verify" / "1" / "input")) == PREP_INPUT


# ---- 시연 안정성 후속(phase3 D3-36·37): 재시도 시 이전 INPUT → _backup, EDSPY_PREDICT 판정 = h3d 존재 ----

VALUES = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}
STALE = ("EPS_mesh_0000.rad", "old_try.inc", "Prev_0000.rad")



@pytest.mark.parametrize("mode", ["parametric", "prepared"])
def test_d3_36_retry_moves_old_input_to_backup(predict_env, monkeypatch, mode):
    env = predict_env()
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "fail")
    if mode == "parametric":
        env.param_set()
        j = env.submit("PREDICT", VALUES)
        assert env.w.run_once_slot() == "FAILED"
        jid, expected = j["id"], sorted([MESH_INC, "material.inc", "model0_0000.rad", "model_0001.rad"])
    else:
        jid, _jd = run_prepared(env, make_case(env.imports), expect_state="FAILED")
        expected = PREP_INPUT
    assert env.job(jid)["current_step_key"] == "EDSPY_PREDICT"
    inp = env.predict_dir(jid) / "INPUT"
    for n in STALE:                                                       # 이전 시도·S6 이전 작업의 잔존 파일 흉내
        (inp / n).write_text("stale\n")
    first = {n: (inp / n).read_bytes() for n in os.listdir(inp)}
    monkeypatch.delenv("FAKE_TOOL_MODE_EDSPY")
    r = env.c.post(f"{API}/jobs/{jid}/retry", headers=PW, json={"from_step": 5})
    assert r.status_code in (200, 201), r.text
    nid = r.json()["id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(nid)
    assert sorted(os.listdir(inp)) == expected                           # 이전 파일 없음
    if mode == "prepared":                                                # 원본의 EPS_mesh가 다시 복사됨(잔존 내용 아님)
        assert (inp / "EPS_mesh_0000.rad").read_text() == "simlab mesh\n"
    backups = [p for p in (env.sroot / "_backup").glob(f"*_{nid}/04_predict/{jid}/INPUT") if p.is_dir()]
    assert len(backups) == 1
    assert {n: (backups[0] / n).read_bytes() for n in os.listdir(backups[0])} == first   # 통째로 보존(삭제 없음)


def test_d3_36_empty_or_missing_input_needs_no_backup(predict_env):
    env = predict_env()
    jid, _jd = run_prepared(env, make_case(env.imports))
    assert not (env.sroot / "_backup").exists() or not list((env.sroot / "_backup").rglob("INPUT"))


@pytest.mark.parametrize("fake_mode,state,code,warnings", [
    ("ok", "SUCCEEDED", None, []),
    ("nonzero_with_output", "SUCCEEDED", None, ["EXIT_NONZERO_IGNORED"]),
    ("error_log", "SUCCEEDED", None, ["LOG_ERROR_PATTERN"]),
    ("fail", "FAILED", "EXIT_NONZERO", None),
    ("no_output", "FAILED", "OUTPUT_MISSING", None),
    ("error_log_no_output", "FAILED", "OUTPUT_MISSING", None),
])
def test_d3_37_edspy_predict_judged_by_h3d(predict_env, monkeypatch, fake_mode, state, code, warnings):
    env = predict_env()
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", fake_mode)
    jid, jd = run_prepared(env, make_case(env.imports), expect_state=state)
    step = env.steps(jid)["EDSPY_PREDICT"]
    if state == "SUCCEEDED":
        assert [w["code"] for w in jd["warnings"]] == warnings, jd["warnings"]
        assert step["state"] == "SUCCEEDED"
        assert step["exit_code"] == (5 if fake_mode == "nonzero_with_output" else 0)
        assert jd["result"]["pred_h3d_rel"].endswith("RESULT/Face_Drop_0000_pred.h3d")
    else:
        assert jd["failure_code"] == code and jd["current_step_key"] == "EDSPY_PREDICT", jd
