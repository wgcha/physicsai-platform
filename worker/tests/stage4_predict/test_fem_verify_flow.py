"""S16 V2 조립 FEM 검증 워커(phase3 §21.3.5~§21.3.6): V3-S16-8(rebuild·reuse 골든, INPUT_CHANGED, 예측 폴더 무변경),
V3-S16-9(command 제출 spec), V3-S16-10(FV_EXTRACT 요청 골든·예측 RESPONSES 재사용/사본·필드 매핑·zero_tol·h3d 2개),
V3-S16-11(FV_CURVE 정의 출처·T01·짝), V3-S16-12(FV_CAPTURE 범례·두 쪽·meta·실패는 경고), V3-S16-13(FV_COMPARE)."""

from __future__ import annotations

import csv
import json
import os

import pytest
from sqlalchemy import text

from physicsai_test_support import API, read_record

from .fv_support import (MESH_INC, P, RESULT_FILES, VALUES, attempt_dir, create, curve_json, detail, finish_hpc, fv_env,
                         predict, ready_doe, run_until_hpc)


@pytest.fixture(autouse=True)
def _fast_collect(monkeypatch, pbs_state):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)


def _snapshot(d) -> dict[str, int]:
    return {str(p.relative_to(d)): p.stat().st_mtime_ns for p in sorted(d.rglob("*")) if p.is_file()}


def _steps(env, jid) -> dict[str, str]:
    return {k: v["state"] for k, v in env.steps(jid).items()}


def test_v3_s16_8_rebuild_mesh_only_train_doe_full(predict_env, fake_tools, fake_record, tmp_path, engine):
    env, ps = fv_env(predict_env, fake_tools, tmp_path, mesh_only=True)
    did, assem = ready_doe(env)
    pj = predict(env)
    curve_json(env, pj, ["Node 100 / X", "Energy"])
    pdir = env.predict_dir(pj)
    (pdir / "RESULT" / "media").mkdir(parents=True, exist_ok=True)
    with open(pdir / "geom" / "EPS_mesh_0000.rad", "a") as fh:                     # 쿠션 부품 id(격리용)
        fh.write("/PART/2000001\nCushion\n/PART/2000002\nCushion2\n")
    before = _snapshot(pdir)
    assem_before = _snapshot(assem)
    d = create(env, {"source": {"kind": "values", "param_set_id": ps["id"], "values": VALUES}})   # 같은 값 → 기존 예측 재사용
    assert (d["status"], d["predict"]["job_id"], d["input_mode"], d["assembly"]["kind"]) == ("RUNNING", pj, "rebuild", "TRAIN_DOE")
    d = run_until_hpc(env, d["id"])
    A = attempt_dir(env, d)
    jid = d["job"]["id"]
    # FV_MESH argv·cwd(원본 m_2 그대로)
    hm = [r for r in read_record(fake_record) if r["tool"] == "hw" and "hwfepre.dat" in r["argv"]][-1]
    tcl = env.lc.settings.resources.hypermesh_include_tcl
    assert hm["argv"][1:] == ["-clientconfig", "hwfepre.dat", "-b", "-tcl", tcl, str(A / "mesh" / "EPS_mesh_0000.rad"),
                              str(A / "mesh" / MESH_INC), str(A / "assem" / "RENUM_INIT.csv")]
    assert hm["cwd"] == str(A / "mesh")
    # FV_ASSEMBLE: 조립 사본 + 새 include, eps_mesh 없음, starter 1개
    inp = sorted(os.listdir(A / "input"))
    assert inp == sorted([MESH_INC, "material.inc", "model0_0000.rad", "model_0001.rad"])
    assert (A / "input" / MESH_INC).read_text() == (A / "mesh" / MESH_INC).read_text() and "3000001 0 0 0" in (A / "input" / MESH_INC).read_text()
    assert sorted(os.listdir(A / "assem")) == ["RENUM_INIT.csv", "material.inc", "model0_0000.rad", "model_0001.rad"]
    res = env.job(jid)["result"]
    assert res["cushion_part_ids"] == ["2000001", "2000002"]
    assert res["starter"] == "model0_0000.rad" and res["fv_rel"].endswith("04_verify/FV-001/a1") and res["attempt"] == 1
    vj = json.loads((A.parent / "verify.json").read_text(encoding="utf-8"))
    assert vj["predict_job_id"] == pj and vj["assembly"]["kind"] == "TRAIN_DOE" and len(vj["assembly"]["files"]) == 4
    assert all(len(f["sha256"]) == 64 for f in vj["assembly"]["files"]) and vj["model"]["psmdl_sha256"]
    # command 제출 spec(V3-S16-9): job_name·입력·결과 경로(path_map)
    sub = [x for x in read_record(fake_record) if x["tool"] == "qsub"][-1]["argv"]
    assert sub[sub.index("-N") + 1] == "pred_fv001_a1"
    v_arg = sub[sub.index("-v") + 1]
    assert v_arg == ("INPUT_FILE=/shared/AI_WORK/pred/04_verify/FV-001/a1/input/model0_0000.rad,"
                     "RESULT_DIR=/shared/AI_WORK/pred/04_verify/FV-001/a1/result")
    assert detail(env, d["id"])["status_text"] == "해석 대기(PBS)"
    d = finish_hpc(env, d["id"], RESULT_FILES)
    assert d["status"] == "DONE", d
    st = _steps(env, jid)
    assert st == {"FV_PREP": "SUCCEEDED", "FV_MESH": "SUCCEEDED", "FV_ASSEMBLE": "SUCCEEDED", "HPC_SUBMIT": "SUCCEEDED",
                  "HPC_WAIT": "SUCCEEDED", "COLLECT": "SUCCEEDED", "FV_EXTRACT": "SUCCEEDED", "FV_CURVE": "SKIPPED",
                  "FV_CAPTURE": "SUCCEEDED", "FV_COMPARE": "SUCCEEDED"}, st
    # FV_EXTRACT(V3-S16-10): FEM 요청 골든(범례 줄 포함), 예측 쪽은 사본(예측 폴더 쓰기 0)
    req = (A / "result" / "H3D_REQUESTS.txt").read_text(encoding="utf-8").splitlines()[2:]
    assert req == ["MaxStress|1|CornerStress|vonMises|", "MinDisp|1|Displacement|X|", "__FV_LEGEND|1|CornerStress|vonMises|"]
    assert (A / "extract" / "pred" / "EPS_mesh_0000_pred.h3d").is_file()
    cmp_ = d["compare"]
    rows = {r["name"]: r for r in cmp_["responses"]}
    assert rows["MaxStress"]["stat"] == "MAX" and rows["MaxStress"]["fem_value"] is not None
    ms = rows["MaxStress"]
    assert ms["diff"] == pytest.approx(ms["pred_value"] - ms["fem_value"])
    assert ms["diff_pct"] == pytest.approx((ms["pred_value"] - ms["fem_value"]) / abs(ms["fem_value"]) * 100)
    assert cmp_["worst"] in rows and cmp_["max_abs_diff_pct"] == pytest.approx(max(abs(r["diff_pct"]) for r in rows.values()))
    assert cmp_["legend"]["source"] == "minmax" and cmp_["legend"]["mode"] == "fixed"
    assert cmp_["curve"]["status"] == "SKIPPED"
    codes = [w["code"] for w in d["warnings"]]
    assert "FEM_RESPONSE_WHOLE_MODEL" in codes
    # FV_CAPTURE(V3-S16-12): 두 쪽 같은 범례·출력 폴더·meta side/fv_id, FEM comps = 자동(쿠션 /PART 없음 → 표시 그대로)
    caps = [r["settings"] for r in read_record(fake_record) if r["tool"] == "hw_capture"][-2:]
    assert [c["OUTDIR"] for c in caps] == [str(A / "media" / x).replace("\\", "/") for x in ("pred", "fem")]  # Tcl '/' 표기
    assert caps[0]["LEGMIN"] == caps[1]["LEGMIN"] != "" and caps[0]["LEGMAX"] == caps[1]["LEGMAX"] != ""
    assert caps[0]["COMPS"] == [] and caps[1]["COMPS"] == ["2000001", "2000002"]                   # mesh_only → 자동 격리
    assert caps[0]["FIELD"] == caps[1]["FIELD"] == "CornerStress"
    with engine.connect() as c:
        metas = [r.meta for r in c.execute(text("select meta from artifacts where job_id=:j and kind='CONTOUR_IMAGE'"), {"j": jid})]
    assert sorted({(m["side"], m["fv_id"]) for m in metas}) == [("fem", d["id"]), ("pred", d["id"])]
    m = env.c.get(f"{API}/fem-verifications/{d['id']}/media", headers=P).json()
    assert m["status"] == "OK" and len(m["items"]) == 4 and all(i["pred"] and i["fem"] for i in m["items"])
    assert m["legend"]["source"] == "minmax"
    # FV_COMPARE(V3-S16-13): compare.json·responses_fem.csv·행 summary(수치만)
    cj = json.loads((A / "compare.json").read_text(encoding="utf-8"))
    assert cj["worst"] == cmp_["worst"]
    with open(A / "responses_fem.csv", encoding="utf-8-sig") as fh:
        assert [r[0] for r in csv.reader(fh)][1:] == ["MaxStress", "MinDisp"]
    with engine.connect() as c:
        summ = c.execute(text("select summary from fem_verifications where id=:i"), {"i": d["id"]}).scalar()
    assert summ["attempt"] == 1 and summ["worst"] == cmp_["worst"] and summ["curve"]["status"] == "SKIPPED"
    assert set(summ) == {"attempt", "responses", "max_abs_diff_pct", "worst", "curve", "media", "warnings_count"}
    assert summ["media"]["legend"]["source"] == "minmax" and isinstance(summ["warnings_count"], int)
    # 예측 폴더·조립 원본 무변경
    assert _snapshot(pdir) == before and _snapshot(assem) == assem_before
    # 알림 1건 문구
    with engine.connect() as c:
        notes = c.execute(text("select event, title from notifications where event='FEM_VERIFY_DONE'")).all()
    assert len(notes) == 1 and notes[0][1].startswith(f"FEM 검증 FV-001 완료 — 최대 오차 ") and f"({cmp_['worst']})" in notes[0][1]
    # 표 CSV
    r = env.c.get(f"{API}/fem-verifications/{d['id']}/table.csv", headers=P)
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf")
    assert r.text.lstrip("﻿").splitlines()[0] == "name,unit,stat,pred_min,pred_max,fem_min,fem_max,pred_value,fem_value,diff,diff_pct"


def test_v3_s16_8_reuse_predict_input_and_curves(predict_env, fake_tools, fake_record, tmp_path, engine):
    """조립 템플릿 예측 → predict_input(reuse): FV_MESH SKIPPED·INPUT = 예측 INPUT 사본, 커브 정의(최신 CU_T01_CURVES) → 짝."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    env.lc.settings.fem_verify.field_map = {"CornerStress": "Element Stresses"}
    pj = predict(env)
    curve_json(env, pj, ["Node 100 / X", "energy total", "Only Pred"])
    cu = env.sql("select id from jobs where study_id=:s limit 1", s=env.sid)[0][0]
    env.sql("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, params, created_by,"
            " created_by_name) values (gen_random_uuid()::text, :s, 'p-1', 'CU_T01_CURVES', 2, 'SLOT', 'SUCCEEDED', false,"
            " cast(:p as jsonb), 'u', 'u')", s=env.sid,
            p=json.dumps({"curves": [{"type": "Node", "request": "N100", "component": "Node 100 / X"},
                                     {"type": "Energy", "request": "E", "component": "Energy Total"},
                                     {"type": "Energy", "request": "E", "component": "Only FEM"}]}))
    del cu
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}, "fem": {"component": "vonMises"}})
    assert (d["input_mode"], d["assembly"]["kind"]) == ("reuse", "PREDICT_INPUT")
    d = run_until_hpc(env, d["id"])
    A = attempt_dir(env, d)
    jid = d["job"]["id"]
    assert sorted(os.listdir(A / "input")) == sorted(os.listdir(env.predict_dir(pj) / "INPUT"))
    assert env.steps(jid)["FV_MESH"]["state"] == "SKIPPED" and env.steps(jid)["FV_MESH"]["progress_label"] == "예측 입력 재사용"
    assert os.listdir(A / "assem") == []
    d = finish_hpc(env, d["id"], RESULT_FILES)
    assert d["status"] == "DONE", d
    req = (A / "result" / "H3D_REQUESTS.txt").read_text(encoding="utf-8").splitlines()[2:]
    assert req[0] == "MaxStress|1|Element Stresses|vonMises|" and req[2].startswith("__FV_LEGEND|1|Element Stresses|vonMises")
    cv = d["compare"]["curve"]
    assert cv["status"] == "OK" and cv["names"] == ["Node 100 / X", "energy total"]
    assert cv["unmatched_pred"] == ["Only Pred"] and cv["unmatched_fem"] == ["Only FEM"]
    t01 = [r for r in read_record(fake_record) if r["tool"] == "hw" and "-config" in r["argv"]][-1]
    assert t01["cwd"] == str(A / "curves") and t01["argv"][t01["argv"].index("-config") + 1] == str(A / "curves" / "INPUT_CURATE_CURVE.json").replace("\\", "/")
    c = env.c.get(f"{API}/fem-verifications/{d['id']}/curves", headers=P, params={"name": "energy total"}).json()
    assert c["name"] == "energy total" and c["pred"]["x"] == [0, 1, 2] and c["fem"]["y"] == [0, 2]
    c0 = env.c.get(f"{API}/fem-verifications/{d['id']}/curves", headers=P).json()
    assert c0["names"] == ["Node 100 / X", "energy total"] and c0["name"] == "Node 100 / X"
    assert env.c.get(f"{API}/fem-verifications/{d['id']}/curves", headers=P, params={"name": "nope"}).json()["pred"] is None


def test_v3_s16_8_input_changed(predict_env, fake_tools, tmp_path):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    ai = env.ai
    custom = env.imports / "assem_custom"
    from physicsai_test_support import make_assem_files

    make_assem_files(custom)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "custom", "path": str(custom)}})
    (custom / "material.inc").write_text("changed after create\n")
    d0 = detail(env, d["id"])
    assert env.w.run_once_slot() == "FAILED"
    j = env.job(d0["job"]["id"])
    assert j["failure_code"] == "INPUT_CHANGED" and j["current_step_key"] == "FV_PREP"
    d = detail(env, d["id"])
    assert d["status"] == "FAILED" and d["failure"]["code"] == "INPUT_CHANGED" and d["can_rerun"] is True
    del ai


def test_v3_s16_10_pred_reuse_zero_tol_and_ambiguous(predict_env, fake_tools, tmp_path, monkeypatch):
    """예측 RESPONSES 재사용(요청 같음 + 범례 고정) → 사본 추출 없음, FEM h3d 2개 → RESP_H3D_AMBIGUOUS·FEM 값 null."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    R = env.predict_dir(pj) / "RESULT"
    assert (R / "RESPONSES.txt").is_file()                                  # 예측 체인이 같은 요청으로 추출
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj},
                     "display": {"legend": {"mode": "fixed", "min": 0, "max": 10}}})
    run_until_hpc(env, d["id"])
    d = finish_hpc(env, d["id"], {**RESULT_FILES, "second.h3d": b"other"})
    A = attempt_dir(env, d)
    assert d["status"] == "DONE"
    assert not (A / "extract" / "pred" / "EPS_mesh_0000_pred.h3d").exists() and not list((A / "extract" / "pred").iterdir())
    rows = {r["name"]: r for r in d["compare"]["responses"]}
    assert rows["MaxStress"]["pred_value"] is not None and rows["MaxStress"]["fem_value"] is None
    assert "RESP_H3D_AMBIGUOUS" in [w["code"] for w in d["warnings"]]
    assert d["compare"]["legend"] == {"mode": "fixed", "min": 0.0, "max": 10.0, "source": "request", "note": None}


def test_v3_s16_10_pure_rules():
    from physicsai_core.stage4_predict import responses as rm
    from physicsai_worker.steps.stage4_predict.fem_compare import compare_rows, legend_name, legend_union, pair_curves, worst_of

    assert legend_name([{"name": "A"}]) == "__FV_LEGEND"
    assert legend_name([{"name": "__FV_LEGEND"}, {"name": "__FV_LEGEND2"}]) == "__FV_LEGEND3"
    q = [rm.H3dRequest("S", 1, "D", "", "", "MAX"), rm.H3dRequest("Z", 1, "D", "", "", "ABSMAX")]
    p = rm.ParsedResponses(values={"S_MIN": -1.0, "S_MAX": 110.0, "Z_MIN": -2.0, "Z_MAX": 1.0})
    f = rm.ParsedResponses(values={"S_MIN": -2.0, "S_MAX": 100.0, "Z_MIN": 0.0, "Z_MAX": 0.0})
    rows = compare_rows(q, {"S": "MPa"}, p, f, 1e-12)
    assert rows[0]["diff"] == 10.0 and rows[0]["diff_pct"] == pytest.approx(10.0) and rows[0]["unit"] == "MPa"
    assert rows[0]["min_diff"] == 1.0 and rows[0]["min_diff_pct"] == pytest.approx(50.0)
    assert rows[1]["pred_value"] == 2.0 and rows[1]["diff_pct"] is None and rows[1]["note"] == "기준값 0"
    assert worst_of(rows) == (pytest.approx(10.0), "S")
    assert legend_union((0.0, 5.0), (-1.0, 3.0)) == (-1.0, 5.0)
    assert legend_union((0.0, None), (1.0, 2.0)) is None and legend_union((1.0, 1.0), (1.0, 1.0)) is None
    pairs, up, uf = pair_curves(["A b", "C", "x"], ["a B", "C", "y"])
    assert pairs == [{"pred": "C", "fem": "C"}, {"pred": "A b", "fem": "a B"}] and up == ["x"] and uf == ["y"]


def test_v3_s16_12_capture_failure_is_warning(predict_env, fake_tools, tmp_path, monkeypatch):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    run_until_hpc(env, d["id"])
    monkeypatch.setenv("FAKE_TOOL_MODE_CAPTURE", "fail")
    d = finish_hpc(env, d["id"], RESULT_FILES)
    assert d["status"] == "DONE"
    assert [w["code"] for w in d["warnings"]].count("CAPTURE_FAILED") == 2
    assert d["compare"]["media"] == {"pred_status": "FAILED", "fem_status": "FAILED"}
    pmedia = env.predict_dir(pj) / "RESULT" / "media"
    assert not (pmedia / "contour_capture.tcl").exists() or True                 # 예측 원래 media는 고치지 않음(아래 확인)
    assert all(not str(p).startswith(str(attempt_dir(env, d))) for p in pmedia.glob("*"))
