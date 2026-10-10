"""2차 Verifier 결함 회귀 시험(1~8): SPDM TOCTOU, XML DTD(인코딩 무관), 마스킹, 이름 필드 화이트리스트, run 폴더 매칭,
환경 점검 출력 마스킹·상한, PBS 종료코드 해석·취소 실패, 배포 스크립트."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from helpers_stage1 import _ready_doe, _write_results, job, study, submit
from physicsai_test_support import API, H, REPO, _p2_env, pbs_command_cfg

PW, P, A, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin"), H("tok-admin", write=True)


# ---- 1 SPDM TOCTOU ---------------------------------------------------------------------


def test_spdm_open_read_rejects_swaps(tmp_path):
    from physicsai_core.stage2_curation import spdm
    from physicsai_core.errors import StepFailure

    root = tmp_path / "spdm"
    (root / "case" / "s").mkdir(parents=True)
    f = root / "case" / "s" / "a.h3d"
    f.write_bytes(b"H3D" * 10)
    outside = tmp_path / "secret.h3d"
    outside.write_bytes(b"SECRET" * 5)
    res = spdm.scan(str(root / "case"), ["*.h3d"], 10)
    entry = res.files[0]
    with spdm.open_read(entry) as fh:
        assert fh.read() == b"H3D" * 10
    # 파일을 링크로 교체
    os.replace(f, tmp_path / "orig.h3d")
    os.symlink(outside, f)
    with pytest.raises(StepFailure) as ei:
        spdm.open_read(entry)
    assert ei.value.code == "INPUT_CHANGED"
    os.replace(f, tmp_path / "link_moved")
    # 다른 파일(같은 이름, 다른 inode)로 교체
    f.write_bytes(b"H3D" * 10)
    os.utime(f, ns=(entry.atime_ns, entry.mtime_ns))
    with pytest.raises(StepFailure):
        spdm.open_read(entry)  # 크기·mtime이 같아도 스캔 때 기록한 inode와 다르면 거부
    # 상위 폴더를 링크로 교체
    os.replace(root / "case" / "s", tmp_path / "moved_dir")
    (tmp_path / "evil").mkdir()
    (tmp_path / "evil" / "a.h3d").write_bytes(b"H3D" * 10)
    os.symlink(tmp_path / "evil", root / "case" / "s")
    with pytest.raises(StepFailure):
        spdm.open_read(entry)


def test_spdm_open_read_size_mtime(tmp_path):
    from physicsai_core.stage2_curation import spdm
    from physicsai_core.errors import StepFailure

    (tmp_path / "r").mkdir()
    f = tmp_path / "r" / "a.h3d"
    f.write_bytes(b"x" * 10)
    e = spdm.scan(str(tmp_path / "r"), ["*.h3d"], 10).files[0]
    f.write_bytes(b"x" * 11)
    with pytest.raises(StepFailure):
        spdm.open_read(e)
    f.write_bytes(b"x" * 10)
    os.utime(f, ns=(e.atime_ns, e.mtime_ns + 10**9))
    with pytest.raises(StepFailure):
        spdm.open_read(e)
    os.utime(f, ns=(e.atime_ns, e.mtime_ns))
    spdm.open_read(e).close()


# ---- 2 XML ---------------------------------------------------------------------------------

BODY = "<Root><Model><Parameter><Name>A</Name><Value>3 mm</Value></Parameter></Model></Root>"


@pytest.mark.parametrize("enc", ["utf-16", "utf-16-le", "utf-8-sig", "latin-1"])
def test_xml_dtd_rejected_any_encoding(tmp_path, enc):
    from physicsai_core.errors import StepFailure
    from physicsai_core.stage1_train_data.train_params import read_extracted_xml

    decl = {"utf-16": "UTF-16", "utf-16-le": "UTF-16", "utf-8-sig": "UTF-8", "latin-1": "ISO-8859-1"}[enc]
    doc = f'<?xml version="1.0" encoding="{decl}"?><!DOCTYPE r [<!ENTITY e "x">]>' + BODY
    data = doc.encode(enc)
    if enc == "utf-16-le":
        data = b"\xff\xfe" + data
    p = tmp_path / "x.xml"
    p.write_bytes(data)
    with pytest.raises(StepFailure) as ei:
        read_extracted_xml(str(p), 1 << 20)
    assert "DOCTYPE" in ei.value.message
    p.write_bytes((f'<?xml version="1.0" encoding="{decl}"?>' + BODY).encode(enc if enc != "utf-16-le" else "utf-16"))
    assert read_extracted_xml(str(p), 1 << 20) == [("A", "3")]


def test_xml_utf32_rejected(tmp_path):
    from physicsai_core.errors import StepFailure
    from physicsai_core.stage1_train_data.train_params import read_extracted_xml

    p = tmp_path / "x.xml"
    p.write_bytes(('<!DOCTYPE r [<!ENTITY e "x">]>' + BODY).encode("utf-32"))
    with pytest.raises(StepFailure) as ei:
        read_extracted_xml(str(p), 1 << 20)
    assert ei.value.code == "INPUT_INVALID"


# ---- 3 마스킹 -------------------------------------------------------------------------------


def test_masker_contract_rule_and_json_escape():
    from physicsai_core.masking import BundleMasker

    m = BundleMasker([], "sess", "DBURL", environ={"MY_SECRET": 'pa"ss\\word'})
    assert m("postgresql://user:pa/ss@host/db") == "postgresql://***@host/db"
    assert m("postgresql+psycopg://u:p@h:5432/d x") == "postgresql+psycopg://***@h:5432/d x"
    blob = json.dumps({"v": 'x pa"ss\\word y'})  # JSON 안에서는 pa\"ss\\word 로 이스케이프됨
    assert m(blob) == json.dumps({"v": "x *** y"})


# ---- 4 이름 필드 화이트리스트 -------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["a\nb", 'a"b', "$x", "[a]", "{a}", "a;b", "a\tb", "a\x00"])
def test_response_fields_whitelist(bad):
    from physicsai_core.stage5_optimize.optimize import validate_responses

    row = {"name": "R1", "source": "H3D", "subcase": 1, "datatype": "Stress", "component": bad, "layer": "", "stat": "MAX",
           "goal": "MINIMIZE"}
    assert validate_responses([row], "OPT")[1]
    row2 = {"name": "R1", "source": "XYDATA", "request": bad, "component": "X", "stat": "MAX", "goal": "MINIMIZE"}
    assert validate_responses([row2], "OPT")[1]
    ok = {**row, "component": "P1 (major)", "layer": "Z1:top+"}
    assert validate_responses([ok], "OPT")[1] == []


def test_curve_and_selection_fields_whitelist(p2_env):
    c, mk, ai, lc, d = p2_env
    sid = study(c, "wl1")
    root = ai / "wl1" / "00_inbox" / "t"
    root.mkdir(parents=True)
    (root / "aT01").write_text("x")
    for bad in ("a\nb", "F{Mag}", "a;b", 'a"', "$x"):
        r = submit(c, sid, "CU_T01_CURVES", {"source": {"kind": "FOLDER", "path": str(root)},
                                             "curves": [{"type": "Rigid Body", "request": "RBODY 1", "component": bad}]}, expect=422)
        assert r["detail"]["code"] == "INVALID_PARAMS", bad
        r = submit(c, sid, "CU_H3D_CURATE", {"source": {"kind": "FOLDER", "path": str(root)}, "preview_job_id": "x",
                                             "selection": {"items": [{"datatype": bad, "component": "X"}]}}, expect=422)
        assert r["detail"]["code"] == "INVALID_PARAMS", bad


# ---- 5 run 폴더 매칭 ------------------------------------------------------------------------


def test_run_dir_matcher_prefix_exact():
    from physicsai_core.stage1_train_data.train_params import RunDirMatcher

    m = RunDirMatcher(r"^case_(?P<run_key>run__\d+)$", {"run__00001"})
    assert m.match("case_run__00001") == "run__00001"
    assert m.match("case_RUN__00001") == "run__00001"  # run_key 그룹만 대소문자 무시
    assert m.match("CASE_run__00001") is None  # 접두부는 정확히
    d = RunDirMatcher(r"^(?P<run_key>run__\d+)$", {"run__00001"})
    assert d.match("RUN__00001") == "run__00001" and d.match("run__00002") is None


def test_result_import_duplicate_clear_error(p2_env):
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "dp1", num_runs=2)
    base = Path(lc.settings.storage.allowed_import_roots[0]) / "dup2"
    _write_results(ai, "dp1", doe_id, ["run__00001"], base=base / "a")
    _write_results(ai, "dp1", doe_id, ["RUN__00001"], base=base / "b")
    j = submit(c, sid, "TD_RESULT_IMPORT", {"doe_id": doe_id, "source_path": str(base)})
    assert w.run_once_light() == "FAILED"
    jd = job(c, j["id"])
    assert jd["failure_code"] == "INPUT_INVALID" and "중복" in jd["failure_message"] and "run__00001" in jd["failure_message"]
    assert any(x["code"] == "RUN_FOLDER_DUPLICATE" and "a/run__00001" in x["message"] for x in jd["warnings"])


# ---- 6 환경 점검 프로브 출력 -----------------------------------------------------------------


def test_env_probe_output_masked_and_capped(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    secret = "postgresql+psycopg://app:Pr0beSecret@127.0.0.1/physicsai"
    monkeypatch.setenv("FAKE_ECHO", secret)
    monkeypatch.setenv("PHYSICSAI_DATABASE_URL", secret)
    gen = _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch,
                  {"env_check": {"probes": {"edspy": ["{edspy}", "--probe-echo"]}}})
    c, mk, ai, lc, d = next(gen)
    try:
        chk = c.post(f"{API}/admin/env-checks", headers=AW).json()
        assert mk().run_env_check_once() == "DONE"
        rep = json.loads((ai / "_platform" / "env_checks" / chk["id"] / "report.json").read_text())
        tail = rep["probe_output_tails"]["probe.edspy"]
        assert "Pr0beSecret" not in tail and len(tail) <= 4096 and "filler line 04999" in tail
        import physicsai_worker.env_check as ec

        assert ec.COLLECT_CAP <= 65536
    finally:
        for _ in gen:
            pass


# ---- 7 PBS 종료코드 해석·취소 실패 ---------------------------------------------------------------


def test_exit_code_parse_failure_unknown(settings_dict, fake_tools, tmp_path, monkeypatch):
    import copy

    from physicsai_core.config import load_config_dict
    from physicsai_core.hpc.command import CommandHpcGateway
    from physicsai_core.hpc.gateway import HpcSubmitSpec

    monkeypatch.setenv("FAKE_PBS_STATE", str(tmp_path / "st.json"))
    d = copy.deepcopy(settings_dict)
    hpc = pbs_command_cfg(fake_tools, str(tmp_path))
    hpc["command"]["exit_code_regex"] = r"job_state\s*=\s*(?P<exit>\w)"
    d["hpc"] = hpc
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    gw = CommandHpcGateway(lc.settings.hpc)
    jid = gw.submit(HpcSubmitSpec("j", "r", "s", "/a/b.rad", "/a", "/r", None, None, None)).external_job_id
    assert gw.status(jid).state == "UNKNOWN"  # Q: 'Q'도 숫자가 아니어서 해석 실패 → 판정 보류
    st = gw.status(jid)  # F → exit 'F' 해석 실패
    assert st.state == "UNKNOWN" and st.exit_code is None


@pytest.fixture()
def p2_pbs(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    monkeypatch.setenv("FAKE_PBS_STATE", str(tmp_path / "pbs_state.json"))
    monkeypatch.delenv("FAKE_TOOL_MODE_PBS", raising=False)
    ai = tmp_path / "ai_root"
    ai.mkdir(exist_ok=True)
    yield from _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {"hpc": pbs_command_cfg(fake_tools, str(ai))})


def test_cancel_failure_keeps_waiting_and_retries(p2_pbs, monkeypatch, engine):
    c, mk, ai, lc, d = p2_pbs
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "cf1", num_runs=2)
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC"
    assert c.post(f"{API}/jobs/{j['id']}/cancel", headers=AW).status_code == 202
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "cancel_fail")
    w.poll_hpc_once()
    w.poll_hpc_once()
    jd = job(c, j["id"])
    assert jd["state"] == "WAITING_HPC" and jd["attention_code"] == "HPC_CANCEL_FAILED"
    assert {h["state"] for h in c.get(f"{API}/jobs/{j['id']}/hpc-jobs", headers=P).json()} == {"CANCEL_REQUESTED"}
    with engine.connect() as conn:
        n = conn.execute(text("select count(*) from notifications where job_id=:j and event='HPC_CANCEL_FAILED'"), {"j": j["id"]}).scalar()
    assert n == 1  # 한 번만
    assert jd["can_download_error_bundle"] is True  # 주의 코드가 있는 비종료 작업
    # C20: JobSummary(대기열·목록)에도 attention_code
    q = c.get(f"{API}/queue", headers=P).json()
    assert q["waiting_hpc"][0]["attention_code"] == "HPC_CANCEL_FAILED"
    assert c.get(f"{API}/jobs?study_id={sid}&job_type=TD_SOLVE", headers=P).json()[0]["attention_code"] == "HPC_CANCEL_FAILED"
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "ok")
    w.poll_hpc_once()
    assert job(c, j["id"])["state"] == "CANCELED"
    assert {h["state"] for h in c.get(f"{API}/jobs/{j['id']}/hpc-jobs", headers=P).json()} == {"CANCELED"}


# ---- 8 배포 스크립트 ---------------------------------------------------------------------------


def test_deploy_password_not_logged_and_env_checks_in_update():
    inst = (REPO / "deploy" / "install.ps1").read_text(encoding="utf-8")
    i_set, i_create = inst.index("SET log_statement = 'none'"), inst.index("CREATE ROLE")
    assert i_set < i_create and "log_min_error_statement = 'panic'" in inst
    upd = (REPO / "deploy" / "update.ps1").read_text(encoding="utf-8")
    assert "FROM env_checks WHERE state IN ('PENDING','RUNNING')" in upd and "/physicsai/api/admin/env-checks/latest" in upd
