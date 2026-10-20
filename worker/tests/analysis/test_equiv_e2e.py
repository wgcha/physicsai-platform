"""equiv-check.md V-EQ-7(EQ_EXTRACT 재사용·사본·원본 불변·상한)·V-EQ-8(결과 집합 4종 e2e, folder 루트 밖·링크 거부)·V-EQ-9(DB에 파일 본문 없음)
— 가짜 hw(minmax·T01 곡선)로 EQ_CHECK 작업을 끝까지 돌린다."""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text

from physicsai_core.config.schema_equiv import default_system_recipe
from physicsai_test_support import API, read_record

from ..stage4_predict.conftest import predict_env  # noqa: F401 - fixture 재사용
from .eq_support import (P, PW, body, create, detail, eq_dir, eq_env, make_fem_verify, make_folders, make_predict_batch, make_train_doe,
                         preview, recipe_def, run_check, snapshot_tree)

T01 = {"type": "Rigid Body", "request": "RBODY 1", "component": "F-Mag"}


def _with_t01(d: dict) -> dict:
    for m in d["metrics"]:
        if m["kind"].startswith("curve"):
            m["source"]["t01"] = T01
    return d


def _hw_calls(rec, kind: str) -> int:
    calls = [r for r in read_record(rec) if r["tool"] == "hw"]
    if kind == "minmax":
        return sum(1 for r in calls if "hwpost.dat" in r["argv"] and r["argv"].index("-tcl") + 2 == len(r["argv"]))
    return sum(1 for r in calls if "-config" in r["argv"])


def test_v_eq_8_same_doe_both_sides_all_pass_and_files(predict_env, fake_tools, fake_record, tmp_path, engine):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path)
    did = make_train_doe(env, runs=3)
    before = snapshot_tree(env.sroot / "01_train")
    b = body({"kind": "train_doe", "doe_id": did}, {"kind": "train_doe", "doe_id": did, "label": "같은 DOE"}, inline=_with_t01(recipe_def()))
    pv = preview(env, b)
    assert pv["can_run"] and pv["pairing"]["n_pairs"] == 3 and pv["extract"]["h3d_runs"] == 6 and pv["extract"]["t01_runs"] == 6
    assert pv["problems"] == [] and all(m["bound"] for m in pv["metrics"])
    with engine.connect() as c:  # 미리보기는 DB 무쓰기
        assert c.execute(text("select count(*) from eq_checks")).scalar() == 0
    d = run_check(env, b)
    assert d["status"] == "DONE" and d["verdict"] == "PASS" and d["verdict_text"] == "통과", d
    assert d["summary"]["verdict"]["required_total"] == 4 and d["summary"]["verdict"]["required_pass"] == 4
    rows = d["rows"]
    assert len(rows) == 12 and all(r["status"] == "PASS" for r in rows)
    sc = [r for r in rows if r["metric_id"] == "stress_peak"]
    assert all(r["diff"] == 0 and r["rel_pct"] == 0 for r in sc)
    cc = [r for r in rows if r["metric_id"] == "acc_corr"]
    assert all(abs(r["corr"] - 1.0) < 1e-9 for r in cc)
    vd = [r for r in rows if r["metric_id"] == "volume_diff"]
    assert all(abs(r["a"] - (1 + 1 / 6)) < 1e-9 and r["diff"] == 0 for r in vd)
    # 파일: 판정 폴더에만 — 원본 run 폴더(01_train) mtime·내용 불변(EQ-6)
    assert snapshot_tree(env.sroot / "01_train") == before
    E = eq_dir(env, d)
    assert {p.name for p in E.iterdir()} >= {"recipe.json", "pairs.json", "metrics.csv", "result.json", "extract", "curves"}
    assert (E / "extract" / "a" / "run__00001" / "RESPONSES.txt").is_file() and (E / "extract" / "b" / "run__00001" / "curve.json").is_file()
    assert (E / "curves" / "1" / "acc_corr.json").is_file()
    assert _hw_calls(fake_record, "minmax") == 6 and _hw_calls(fake_record, "t01") == 1  # T01은 1회 호출
    # 곡선 API·표 CSV·알림
    cv = env.c.get(f"{API}/equiv-checks/{d['id']}/curves", headers=P, params={"pair": 1, "metric": "acc_corr"}).json()
    assert cv["a_run"] == "run__00001" and len(cv["t"]) == len(cv["a"]) == len(cv["b"]) and abs(cv["corr"] - 1) < 1e-9
    assert env.c.get(f"{API}/equiv-checks/{d['id']}/curves", headers=P, params={"pair": 1, "metric": "stress_peak"}).status_code == 404
    csv = env.c.get(f"{API}/equiv-checks/{d['id']}/table.csv", headers=P)
    assert csv.status_code == 200 and csv.text.lstrip("﻿").startswith("pair_no,a_run,b_run,metric_id,a,b,diff,rel_pct,corr,status,reason")
    with engine.connect() as c:
        n = c.execute(text("select title from notifications where event='EQ_CHECK_DONE'")).all()
        row = c.execute(text("select summary, recipe_snapshot from eq_checks where id=:i"), {"i": d["id"]}).one()
    assert len(n) == 1 and n[0][0].startswith("등가성 판정 EQ-001 통과 — 필수 4/4 · 참고 미달 0 · 쌍 3")
    # V-EQ-9: DB 요약·스냅숏은 수치·정의만(쌍별 값 없음, 64 KiB 이하)
    assert "pair_no" not in json.dumps(row[0]) and len(json.dumps(row[0])) < 65536 and len(json.dumps(row[1])) < 65536
    assert "rows" not in row[0] and set(row[0]["metrics"]) == {"stress_peak", "disp_min", "acc_corr", "volume_diff"}
    assert row[0]["metrics"]["stress_peak"]["worst_pair"] == "run__00001 ↔ run__00001" and row[0]["n_rows"] == 12


def test_v_eq_7_reuse_skips_extraction_and_too_large(predict_env, fake_tools, fake_record, tmp_path):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path, extra={"equiv_check": {"max_extract_copy_bytes": 1048576}})
    did = make_train_doe(env, runs=2, pre_extracted=True, with_t01=False)
    d = _with_t01(recipe_def(volume=False))
    d["metrics"] = [m for m in d["metrics"] if m["kind"] == "scalar"]
    b = body({"kind": "train_doe", "doe_id": did}, {"kind": "train_doe", "doe_id": did}, inline=d)
    pv = preview(env, b)
    assert pv["extract"] == {"h3d_runs": 0, "t01_runs": 0, "copy_bytes": 0}
    out = run_check(env, b)
    assert out["verdict"] == "PASS" and _hw_calls(fake_record, "minmax") == 0
    assert not (eq_dir(env, out) / "extract" / "a").exists()
    assert out["job"]["state"] == "SUCCEEDED"
    steps = env.steps(out["job_id"])
    assert steps["EQ_EXTRACT"]["state"] == "SKIPPED"
    # 사본 상한 초과: h3d가 상한보다 크면 preview problems·create 422 EQ_EXTRACT_TOO_LARGE
    did2 = make_train_doe(env, runs=1, label="DOE-BIG", with_t01=False)
    big = env.sroot / "01_train" / "results" / did2 / "run__00001" / "model_0000.h3d"
    big.write_bytes(b"x" * (1048576 + 10))
    b2 = body({"kind": "train_doe", "doe_id": did2}, {"kind": "train_doe", "doe_id": did2}, inline=d)
    assert [p["code"] for p in preview(env, b2)["problems"]] == ["EQ_EXTRACT_TOO_LARGE"]
    r = env.c.post(f"{API}/studies/{env.sid}/equiv-checks", headers=PW, json=b2)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "EQ_CHECK_INVALID"
    assert "사본 없이 재사용" in r.json()["detail"]["problems"][0]["message"]


def test_v_eq_8_predict_batch_vs_doe_by_params_and_fail(predict_env, fake_tools, fake_record, tmp_path):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path)
    did = make_train_doe(env, runs=3, h3d_seed=0)
    bid = make_predict_batch(env, ps["id"], runs=3, h3d_seed=1, names=["run__00003", "run__00002", "run__00001"],
                             values=[{"THK_1": 3.0, "N_RIB": 4}, {"THK_1": 2.5, "N_RIB": 3}, {"THK_1": 2.0, "N_RIB": 2}])
    d = _with_t01(recipe_def(required_stress=False, nrmse=True))
    d["metrics"][0]["tol"] = {"rel_pct": 0.5, "abs": None}  # h3d 바이트 수 % 7 차이(1~4%)가 미달이 되게
    b = body({"kind": "train_doe", "doe_id": did}, {"kind": "predict_batch", "batch_id": bid}, pairing="by_params", inline=d)
    pv = preview(env, b)
    assert pv["pairs"] == [{"no": 1, "a": "run__00001", "b": "run__00001"}, {"no": 2, "a": "run__00002", "b": "run__00002"},
                           {"no": 3, "a": "run__00003", "b": "run__00003"}]  # 값으로 짝(이름 무시)
    assert pv["extract"]["t01_runs"] == 3 and pv["extract"]["h3d_runs"] == 6  # 예측 쪽도 요청이 다르면 사본 추출
    out = run_check(env, b)
    mets = {m["id"]: m for m in out["metrics"]}
    # 응력(참고)은 미달이어도 종합에 영향 없음, 변위(MIN, 같은 값)·곡선·부피 통과
    assert mets["stress_peak"]["status"] == "FAIL" and mets["stress_peak"]["required"] is False
    assert mets["disp_min"]["status"] == "PASS" and mets["acc_corr"]["status"] == "PASS" and mets["volume_diff"]["status"] == "PASS"
    assert out["verdict"] == "PASS" and out["summary"]["verdict"]["reference_fail"] == 2  # 응력 + NRMSE(참고)
    assert "참고 미달 2" in out["summary_line"] and mets["acc_nrmse"]["status"] == "FAIL"
    nr = [r for r in out["rows"] if r["metric_id"] == "acc_nrmse"]
    assert len(nr) == 3 and all(r["status"] in ("PASS", "FAIL") for r in nr)
    assert (eq_dir(env, out) / "extract" / "b" / "run__00001" / f"run__00001_pred.h3d").is_file()  # 예측 폴더 아닌 사본
    # 이름 집합 다르면 PARAM_SET_MISMATCH
    bid2 = make_predict_batch(env, ps["id"], runs=1, values=[{"THK_1": 2.0, "OTHER": 1}])
    pv2 = preview(env, body({"kind": "train_doe", "doe_id": did}, {"kind": "predict_batch", "batch_id": bid2}, pairing="by_params", inline=d))
    assert pv2["problems"][0]["code"] == "PARAM_SET_MISMATCH" and pv2["problems"][0]["only_b"] == ["OTHER"]


def test_v_eq_8_fem_verify_vs_folder_and_folder_rules(predict_env, fake_tools, fake_record, tmp_path):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path)
    fid = make_fem_verify(env, ps["id"], h3d_seed=4)
    folders = make_folders(env.sroot / "00_inbox" / "simlab", ["case_a"], h3d_seed=4)
    d = _with_t01(recipe_def())
    b = body({"kind": "fem_verify", "fv_id": fid}, {"kind": "folder", "paths": folders}, inline=d)
    pv = preview(env, b)
    assert pv["pairs"] == [{"no": 1, "a": "FV-001", "b": "case_a"}]  # EQ-C1: 양쪽 1 run이면 이름이 달라도 쌍
    out = run_check(env, b)
    assert out["verdict"] == "PASS" and out["side_a"]["label"] == "FEM 검증 FV-001" and out["side_b"]["kind"] == "folder"
    # 폴더: 허용 루트 밖·링크 거부, h3d 2개면 값 NA(RUN은 유지)
    outside = tmp_path / "elsewhere" / "x"
    outside.mkdir(parents=True)
    pv = preview(env, body({"kind": "fem_verify", "fv_id": fid}, {"kind": "folder", "paths": [str(outside)]}, inline=d))
    assert pv["problems"][0]["code"] == "FOLDER_OUTSIDE_ROOTS"
    link = env.sroot / "00_inbox" / "lnk"
    os.symlink(folders[0], link)
    pv = preview(env, body({"kind": "fem_verify", "fv_id": fid}, {"kind": "folder", "paths": [str(link)]}, inline=d))
    assert pv["problems"] and pv["problems"][0]["code"] in ("PATH_UNSAFE", "SIDE_NOT_FOUND")
    two = make_folders(env.sroot / "00_inbox" / "two", ["dup"], h3d_seed=4)
    (env.sroot / "00_inbox" / "two" / "dup" / "second.h3d").write_bytes(b"H3D")
    pv = preview(env, body({"kind": "fem_verify", "fv_id": fid}, {"kind": "folder", "paths": two}, inline=d))
    assert any(w["code"] == "FOLDER_FILES" for w in pv["warnings"]) and pv["side_b"]["runs"][0]["has_h3d"] is False


def test_v_eq_8_run_not_succeeded_unbound_and_incomplete(predict_env, fake_tools, fake_record, tmp_path):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path)
    did = make_train_doe(env, runs=2, collected=False)  # run__00001 SOLVE_FAILED
    d = recipe_def(volume=False)
    d["metrics"] = [m for m in d["metrics"] if m["kind"] == "scalar"]
    out = run_check(env, body({"kind": "train_doe", "doe_id": did}, {"kind": "train_doe", "doe_id": did}, inline=d))
    r1 = [r for r in out["rows"] if r["a_run"] == "run__00001"]
    assert all(r["status"] == "NA" and r["reason"] == "RUN_NOT_SUCCEEDED" and r["reason_text"] == "run이 성공 상태가 아님" for r in r1)
    assert out["verdict"] == "PASS" and any(w["code"] == "EQ_PARTIAL_PAIRS" for w in out["warnings"])
    # EQ-C1: 시스템 기본(제안값)은 그대로 실행 불가 — 응답을 모두 연결해도 422 RECIPE_NOT_CONFIRMED(복제·확인한 레시피만)
    sides = ({"kind": "train_doe", "doe_id": did}, {"kind": "train_doe", "doe_id": did})
    sysb = body(*sides, recipe={"key": "sys:default"})
    r = env.c.post(f"{API}/studies/{env.sid}/equiv-checks", headers=PW, json=sysb)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "EQ_CHECK_INVALID"
    codes = [p["code"] for p in r.json()["detail"]["problems"]]
    assert codes.count("RECIPE_NOT_CONFIRMED") == 1 and codes.count("METRIC_UNBOUND") == 6  # 참고(응력·접촉력)도 연결 필요
    assert "복제" in next(p["message"] for p in r.json()["detail"]["problems"] if p["code"] == "RECIPE_NOT_CONFIRMED")
    perf = {"type": "perf", "perf": "MaxStress"}
    all6 = {k: perf for k in ("accel_peak", "ie_max", "ke_max", "stress_peak", "contact_peak")} | {"cushion_deform": {"type": "perf", "perf": "MinDisp"}}
    sysb["bindings"] = all6
    r = env.c.post(f"{API}/studies/{env.sid}/equiv-checks", headers=PW, json=sysb)
    assert r.status_code == 422 and [p["code"] for p in r.json()["detail"]["problems"]] == ["RECIPE_NOT_CONFIRMED"]
    inl = body(*sides)
    inl["recipe_inline"] = {"definition": default_system_recipe(), "base": {"key": "sys:default"}}
    assert "RECIPE_NOT_CONFIRMED" in [p["code"] for p in preview(env, inl)["problems"]]
    # 복제(사용자 레시피) → 필수만 연결하면 참고 미연결로 422, 모두 연결하면 실행
    cl = env.c.post(f"{API}/equiv/recipes", headers=PW, json={"name": "현장 복제", "scope": "study", "study_id": env.sid, "clone_from": {"key": "sys:default"}})
    assert cl.status_code == 201, cl.text
    ub = body(*sides, recipe={"key": cl.json()["key"], "version": 1},
              bindings={k: v for k, v in all6.items() if k not in ("stress_peak", "contact_peak")})
    r = env.c.post(f"{API}/studies/{env.sid}/equiv-checks", headers=PW, json=ub)
    assert r.status_code == 422 and sorted(p["metric_id"] for p in r.json()["detail"]["problems"]) == ["contact_peak", "stress_peak"]
    assert "레시피에서 지표를 빼세요" in r.json()["detail"]["problems"][0]["message"]
    ub["bindings"] = all6
    out = run_check(env, ub)
    assert out["recipe"]["source"] == "user" and out["recipe"]["name"] == "현장 복제" and out["recipe"]["version"] == 1
    mets = {m["id"]: m for m in out["metrics"]}
    assert mets["accel_corr"]["status"] == "NA"  # T01 요청 없음(②-4 곡선 정의 없음) → NA
    assert out["verdict"] == "INCOMPLETE" and out["verdict_text"] == "판정 불가"
    assert any(w["code"] == "EQ_CURVE_DEFS_MISSING" for w in out["warnings"])
    assert "system_version" not in out["recipe_snapshot"] and out["recipe_snapshot"]["metrics"][0]["source"] == perf


def test_v_eq_10_active_limit_cancel_retry_and_note(predict_env, fake_tools, fake_record, tmp_path, engine):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path, extra={"equiv_check": {"max_active": 1}})
    did = make_train_doe(env, runs=1, with_t01=False)
    d = recipe_def(volume=False)
    d["metrics"] = [m for m in d["metrics"] if m["kind"] == "scalar"]
    b = body({"kind": "train_doe", "doe_id": did}, {"kind": "train_doe", "doe_id": did}, inline=d, note="첫 판정")
    c1 = create(env, b)
    r = env.c.post(f"{API}/studies/{env.sid}/equiv-checks", headers=PW, json=b)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EQ_CHECK_LIMIT"
    # 취소 → 이력 CANCELED(행은 남음) → 재시도(같은 스냅숏) → DONE
    from physicsai_test_support import H

    r = env.c.post(f"{API}/jobs/{c1['job_id']}/cancel", headers=H("tok-admin", write=True))  # 취소는 기존 규칙(전역 관리자)
    assert r.status_code in (200, 202), r.text
    env.w.run_once_slot()
    dd = detail(env, c1["eq_id"])
    assert dd["status"] == "CANCELED" and dd["note"] == "첫 판정" and dd["can_retry"] is True
    r = env.c.post(f"{API}/jobs/{c1['job_id']}/retry", headers=PW, json={})
    assert r.status_code == 201, r.text
    assert env.w.run_once_slot() == "SUCCEEDED"
    dd = detail(env, c1["eq_id"])
    assert dd["status"] == "DONE" and dd["verdict"] == "PASS" and dd["job_id"] == r.json()["id"]
    # 메모만 PATCH(작성자), 다른 사용자는 403
    r = env.c.patch(f"{API}/equiv-checks/{c1['eq_id']}", headers=PW, json={"note": "메모 수정"})
    assert r.status_code == 200 and r.json()["note"] == "메모 수정"
    r = env.c.patch(f"{API}/equiv-checks/{c1['eq_id']}", headers=H("tok-power2", write=True), json={"note": "x"})
    assert r.status_code == 403
    r = env.c.patch(f"{API}/equiv-checks/{c1['eq_id']}", headers=PW, json={"verdict": "PASS"})
    assert r.status_code == 422
    lst = env.c.get(f"{API}/studies/{env.sid}/equiv-checks", headers=P).json()
    assert len(lst) == 1 and lst[0]["note"] == "메모 수정" and lst[0]["verdict"] == "PASS"
