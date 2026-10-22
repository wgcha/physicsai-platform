"""①-1 native 추출 → ①-3 native DOE(geometry-engine.md §7.3.1·§7.3.3·§7.3.6, V-GE-5·6·8·10):
LHS 행렬·run__N 레이아웃(직계 = 해석 입력, 보조 = _paicad/, GE-C13)·paramitem 호환 샘플 추출·스킵 사유 기록·엔진 분리·from-train."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from helpers_native import make_project
from helpers_stage1 import job, study, submit
from physicsai_test_support import API, H, MESH_INC, read_record

PW, P = H("tok-power", write=True), H("tok-power")


def _extract(c, w, sid, ai: Path, name: str):
    proj = make_project(ai / name / "00_inbox")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert j["params"]["engine"] == "native"
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    return proj, j


def _doe(c, w, sid, proj, expect="SUCCEEDED", **kw):
    p = {"doe_label": "LHS", "num_runs": 4, "seed": 7, "multi_execution": 2, "radioss_assem_path": str(proj / "assem"), **kw}
    j = submit(c, sid, "TD_DOE_GEN", p)
    assert w.run_once_slot() == expect, job(c, j["id"])
    return job(c, j["id"])


def test_native_extract_parses_features_and_locks(p2_native, fake_record):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "ne1")
    proj, j = _extract(c, w, sid, ai, "ne1")
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    assert ts["engine"] == "native" and ts["tpl"] is None
    by = {p["name"]: p for p in ts["parameters"]}
    assert set(by) == {"A_THK_1", "B_RIB_H_1", "C_HOLE_R_1"}
    assert by["B_RIB_H_1"]["use"] is False and by["A_THK_1"]["use"] is True      # 양면 접촉(locked)은 기본 use=false
    X = ai / "ne1" / "01_train" / "extract" / j["id"]
    assert (X / "parameter_features.json").is_file() and (X / "parameter_extracted.xml").is_file()
    rec = [r for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1] == "extract"][-1]
    assert "--body-map" not in rec["argv"] and rec["cwd"] == str(X)
    arts = c.get(f"{API}/jobs/{j['id']}", headers=P).json()
    assert arts["result"]["feature_png_count"] == 4
    r = c.post(f"{API}/studies/{sid}/train/tpl", headers=PW, json={"version": ts["version"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ENGINE_NATIVE_NO_TPL"


def test_native_doe_layout_matrix_and_samples(p2_native, fake_record):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "nd1")
    proj, _ = _extract(c, w, sid, ai, "nd1")
    jd = _doe(c, w, sid, proj)
    doe_id = jd["result"]["doe_id"]
    D = ai / "nd1" / "01_train" / "doe" / doe_id
    assert jd["result"]["run_count"] == 4 and jd["result"]["skipped_runs"] == []
    rows = list(csv.DictReader((D / "doe_matrix.csv").open(encoding="utf-8")))
    assert [r["run_key"] for r in rows] == [f"run__0000{i}" for i in range(1, 5)] and "A_THK_1" in rows[0]
    assert "B_RIB_H_1" not in rows[0]                                            # use=false 파라미터는 행렬에 없음
    for r in rows:
        R = D / "approaches" / "doe_1" / r["run_key"]
        for rel in ("_paicad/options.json", "_paicad/values.json", "_paicad/native_params.xml", "_paicad/update/update.json",
                    "_paicad/morph/morph.json", "_paicad/check/check.json", f"_paicad/{MESH_INC}", "model0_0000.rad", MESH_INC):
            assert (R / rel).is_file(), (r["run_key"], rel)
        assert not any((R / m).exists() for m in ("m_1", "m_2", "m_3", "options.json"))
        assert list((R / "_paicad" / "assembly").iterdir()) == []                 # 조립 임시 폴더는 비어 있음(내용은 R 직계로 이동)
        assert 9.5 <= float(r["A_THK_1"]) <= 10.5
        assert f'Name="A_THK_1" NewValue="{float(r["A_THK_1"])!r}"' in (R / "_paicad" / "native_params.xml").read_text()
    runs = json.loads((D / "runs.json").read_text())                             # TD_SOLVE 입력 = run__N 직계 starter
    assert runs[0] == {"run_key": "run__00001", "input_rel": f"01_train/doe/{doe_id}/approaches/doe_1/run__00001",
                       "starter_name": "model0_0000.rad"}
    # 같은 seed → 같은 행렬(결정적)
    jd2 = _doe(c, w, sid, proj)
    D2 = ai / "nd1" / "01_train" / "doe" / jd2["result"]["doe_id"]
    assert (D2 / "doe_matrix.csv").read_text() == (D / "doe_matrix.csv").read_text()
    # 샘플 표(paramitem 호환): _paicad/native_params.xml에서 추출 — 행 4개, A_THK_1 값 = 행렬 값
    d = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert d["engine"] == "native" and d["engine_version"] == "0.5.0" and d["sample_status"] == "PARSED" and d["run_count"] == 4
    sm = c.get(f"{API}/train-does/{doe_id}/samples", headers=P).json()
    got = {r["run_key"]: r["values"]["A_THK_1"] for r in sm["rows"]}
    assert got == {r["run_key"]: float(r["A_THK_1"]) for r in rows}
    cmds = [r["argv"][1] for r in read_record(fake_record) if r["tool"] == "paicad"]
    assert cmds.count("tag") == 2 and cmds.count("run") == 8      # paicad_run 설정(기본) → run마다 1회


def test_native_doe_skips_failed_runs_with_reason(p2_native, monkeypatch):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "nd2")
    proj, _ = _extract(c, w, sid, ai, "nd2")
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", "check:GEOM_QUALITY:A_THK_1>10.0")
    jd = _doe(c, w, sid, proj, num_runs=6)
    sk = jd["result"]["skipped_runs"]
    assert sk and all(s["reason"] == "GEOM_QUALITY" and s["category"] == "QUALITY" and s["run_key"].startswith("run__") for s in sk)
    assert jd["result"]["run_count"] == 6 - len(sk) and jd["result"]["run_count"] >= 1
    assert "PARTIAL_OUTPUT" in [x["code"] for x in jd["warnings"]]
    D = ai / "nd2" / "01_train" / "doe" / jd["result"]["doe_id"]
    R = D / "approaches" / "doe_1" / sk[0]["run_key"]
    d = json.loads((R / "SKIPPED.json").read_text())
    assert d["code"] == "GEOM_QUALITY" and d["step"] == "check" and d["report"] == "_paicad/check/check.json"
    assert not list(R.glob("*.rad")) and not (R / "m_3").exists() and (R / "_paicad" / "values.json").is_file()


def test_native_from_train_rejects_tpl_source(p2_native):
    """altair-vars.md AV-11: tpl_source는 Altair DOE 전용 — Native DOE에 current를 주면 422(세트는 만들어지지 않는다)."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "nd6")
    proj, _ = _extract(c, w, sid, ai, "nd6")
    doe_id = _doe(c, w, sid, proj)["result"]["doe_id"]
    before = c.get(f"{API}/studies/{sid}/param-sets", headers=P).json()
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id, "runs": "all", "tpl_source": "current"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "INVALID_PARAMS" and "tpl_source" in json.dumps(r.json()["detail"], ensure_ascii=False)
    assert c.get(f"{API}/studies/{sid}/param-sets", headers=P).json() == before


def test_native_doe_all_fail_and_option_rules(p2_native, monkeypatch):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "nd3")
    proj, _ = _extract(c, w, sid, ai, "nd3")
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": {
        "doe_label": "LHS", "num_runs": 4, "options": {"RANDOM_SEED": 1}, "radioss_assem_path": str(proj / "assem")}})
    assert r.status_code == 422, r.text
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "update:GEOM_CAD_FAILED")
    jd = _doe(c, w, sid, proj, expect="FAILED")
    assert jd["failure_code"] == "GEOM_CAD_FAILED" and "모두 생성 실패" in jd["failure_message"]


def test_native_doe_preconditions(p2_native):
    c, mk, ai, lc, _d = p2_native
    sid = study(c, "nd4")
    proj = make_project(ai / "nd4" / "00_inbox")
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": {
        "doe_label": "LHS", "num_runs": 4, "radioss_assem_path": str(proj / "assem")}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TPL_REQUIRED", r.text   # 추출 전 = altair 경로의 기존 오류


def test_dataset_engine_detection_and_mixing(p2_native, engine):
    """③-1: 입력이 DOE 결과 폴더면 그 DOE의 engine을 데이터셋에 기록, altair·native가 섞이면 422 ENGINE_MIXED, MINOR가 다르면 경고."""
    from sqlalchemy import text

    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "nd5")
    proj, _ = _extract(c, w, sid, ai, "nd5")
    d1 = _doe(c, w, sid, proj)["result"]["doe_id"]
    d2 = _doe(c, w, sid, proj, seed=8)["result"]["doe_id"]
    res = ai / "nd5" / "01_train" / "results"
    for d in (d1, d2):
        (res / d / "run__00001").mkdir(parents=True)
        (res / d / "run__00001" / "x.h3d").write_bytes(b"H3D")

    def create(path):
        return c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(path)}})

    def cancel(resp):
        assert c.post(f"{API}/jobs/{resp.json()['id']}/cancel", headers=H("tok-admin", write=True)).status_code == 202

    r = create(res / d1)
    assert r.status_code == 201, r.text
    assert r.json()["result"]["engine"] == "native" and r.json()["result"]["engine_version"] == "0.5.0" and r.json()["warnings"] == []
    with engine.connect() as conn:
        row = conn.execute(text("select engine, engine_version from datasets where id=:i"), {"i": r.json()["result"]["dataset_id"]}).one()
    assert tuple(row) == ("native", "0.5.0")
    cancel(r)
    with engine.begin() as conn:
        conn.execute(text("update train_does set engine='altair', engine_version=null where id=:i"), {"i": d2})
    r = create(res)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ENGINE_MIXED", r.text
    r = create(res / d2)
    assert r.status_code == 201 and r.json()["result"]["engine"] == "altair" and r.json()["result"].get("engine_version") is None
    cancel(r)
    with engine.begin() as conn:
        conn.execute(text("update train_does set engine='native', engine_version='0.4.0' where id=:i"), {"i": d2})
    r = create(res)
    assert r.status_code == 201, r.text
    assert [x["code"] for x in r.json()["warnings"]] == ["ENGINE_VERSION_MIXED"] and r.json()["result"]["engine_version"] is None
    cancel(r)
    other = ai / "nd5" / "02_import" / "any"
    other.mkdir(parents=True)
    (other / "a.h3d").write_bytes(b"H3D")
    r = create(other)
    assert r.status_code == 201 and "engine" not in r.json()["result"]                # 판별 불가 → NULL


def test_native_doe_as_s18_platform_path(p2_native, engine, monkeypatch):
    """S18 병합(phase3 §23 + geometry-engine.md §7.3.3): native DOE = 생성 방식 platform의 한 경로.
    sampling{kind:lhs}도 받고(다른 kind·hyperstudy 422), generator=PLATFORM·engine=native로 기록, 동시 수 기본 = 플랫폼 기본,
    run 생성은 native(doe_matrix·approaches/doe_1·SKIPPED)이고 S18 run별 점 표는 쓰지 않음, on_run_failure=fail이면 일부 실패 = GEN_PARTIAL_FAILED."""
    from sqlalchemy import text

    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "nd6")
    proj, _ = _extract(c, w, sid, ai, "nd6")
    assem = str(proj / "assem")

    def post(params):
        return c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": params})

    r = post({"generator": "hyperstudy", "doe_label": "LHS", "num_runs": 4, "radioss_assem_path": assem})
    assert r.status_code == 422, r.text
    r = post({"generator": "platform", "sampling": {"kind": "lhs_opt", "count": 4, "seed": 1}, "radioss_assem_path": assem})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "DOE_SAMPLING_INVALID", r.text
    assert r.json()["detail"]["problems"][0]["code"] == "DESIGN_UNSUPPORTED"
    r = post({"sampling": {"kind": "lhs", "count": 4, "seed": 7}, "num_runs": 4, "radioss_assem_path": assem})
    assert r.status_code == 422, r.text                                              # sampling과 num_runs 동시 금지
    r = post({"generator": "platform", "sampling": {"kind": "lhs", "count": 4, "seed": 7}, "radioss_assem_path": assem})
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["engine"] == "native" and p["generator"] == "platform" and p["num_runs"] == 4 and p["seed"] == 7
    assert p["doe_label"] == "LHS(Native)" and p["on_run_failure"] == "continue"
    assert w.run_once_slot() == "SUCCEEDED", job(c, r.json()["id"])
    doe_id = job(c, r.json()["id"])["result"]["doe_id"]
    with engine.connect() as conn:
        row = conn.execute(text("select generator, engine, sampling, doe_type from train_does where id=:i"), {"i": doe_id}).one()
        npts = conn.execute(text("select count(*) from train_doe_points where doe_id=:i"), {"i": doe_id}).scalar()
    assert tuple(row) == ("PLATFORM", "native", None, "NATIVE_LHS") and npts == 0
    D = ai / "nd6" / "01_train" / "doe" / doe_id
    assert (D / "doe_matrix.csv").is_file() and (D / "approaches" / "doe_1" / "run__00004" / "model0_0000.rad").is_file()
    d = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert d["generator"] == "platform" and d["gen"] is None and d["sampling"] is None and d["run_count"] == 4
    # 같은 seed·run 수면 계약 §7.3.3 모양과 같은 행렬
    jd = _doe(c, w, sid, proj)
    assert (ai / "nd6" / "01_train" / "doe" / jd["result"]["doe_id"] / "doe_matrix.csv").read_text() == (D / "doe_matrix.csv").read_text()
    # on_run_failure=fail: 일부 실패면 작업 실패(GEN_PARTIAL_FAILED), continue(기본)면 스킵 + PARTIAL_OUTPUT
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", "check:GEOM_QUALITY:A_THK_1>10.0")
    jf = _doe(c, w, sid, proj, expect="FAILED", num_runs=6, on_run_failure="fail")
    assert jf["failure_code"] == "GEN_PARTIAL_FAILED" and "SKIPPED.json" in jf["failure_message"]
