"""equiv-check.md Q1 확정(2026-10-20): ①-3 "다른 DOE의 표본표 재사용"(sampling.kind = train_doe) — altair 플랫폼 생성·native DOE 모두.
run 이름을 그대로 유지(등가성 판정 by_name 쌍 매칭 키), 파라미터 이름 집합이 같을 때만. 원본 미준비·없음은 422 DOE_SAMPLING_INVALID."""

from __future__ import annotations

import csv

from helpers_native import make_project
from helpers_stage1 import extract_and_tpl, job, make_inputs, study, submit
from physicsai_test_support import API, H
from sqlalchemy import text

PW, P = H("tok-power", write=True), H("tok-power")


def _rows(path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def test_q1_platform_reuse_keeps_run_names_and_values(p2_env, engine):
    c, mk, ai, lc, _d = p2_env
    w = mk()
    sid = study(c, "ru1")
    cad, _assem = make_inputs(ai / "ru1")
    extract_and_tpl(c, w, sid, cad)
    A = str(ai / "ru1" / "00_inbox" / "radioss_assem")
    j = submit(c, sid, "TD_DOE_GEN", {"sampling": {"kind": "lhs", "count": 3, "seed": 5}, "radioss_assem_path": A, "multi_execution": 1})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    src = job(c, j["id"])["result"]["doe_id"]
    # 재사용: 준비 전·없는 DOE는 422(problems), 있으면 run 수 = 원본 행 수·params.sampling 기록
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN",
                                                              "params": {"sampling": {"kind": "train_doe", "doe_id": "nope"}, "radioss_assem_path": A}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "DOE_SAMPLING_INVALID"
    assert r.json()["detail"]["problems"][0]["code"] == "SOURCE_DOE_NOT_FOUND"
    j2 = submit(c, sid, "TD_DOE_GEN", {"sampling": {"kind": "train_doe", "doe_id": src}, "radioss_assem_path": A, "multi_execution": 1})
    assert j2["params"]["num_runs"] == 3 and j2["params"]["sampling"] == {"kind": "train_doe", "doe_id": src} and j2["params"]["doe_type"] == "TRAIN_DOE"
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN",
                                                              "params": {"sampling": {"kind": "train_doe", "doe_id": j2["result"]["doe_id"]}, "radioss_assem_path": A}})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["code"] == "SOURCE_DOE_NOT_READY"  # 아직 BUILDING
    assert w.run_once_slot() == "SUCCEEDED", job(c, j2["id"])
    new = job(c, j2["id"])["result"]["doe_id"]
    D0, D1 = (ai / "ru1" / "01_train" / "doe" / src), (ai / "ru1" / "01_train" / "doe" / new)
    r0, r1 = _rows(D0 / "samples.csv"), _rows(D1 / "samples.csv")
    assert [x["run_key"] for x in r1] == [x["run_key"] for x in r0] == ["run__00001", "run__00002", "run__00003"]
    assert [(float(x["THK_1"]), float(x["RIB_H"])) for x in r1] == [(float(x["THK_1"]), float(x["RIB_H"])) for x in r0]
    with engine.connect() as conn:
        row = conn.execute(text("select generator, doe_type, sampling, options from train_does where id=:i"), {"i": new}).one()
        keys = conn.execute(text("select run_key from train_doe_points where doe_id=:i order by doe_no"), {"i": new}).scalars().all()
    assert row[0] == "PLATFORM" and row[1] == "TRAIN_DOE" and row[2]["kind"] == "train_doe" and row[2]["input"] == {"doe_id": src}
    assert keys == ["run__00001", "run__00002", "run__00003"]
    d = c.get(f"{API}/train-does/{new}", headers=P).json()
    assert d["status"] == "READY" and d["doe_label"] == "① 학습 DOE 그대로 재사용" and d["sampling"]["desc_id"] == "td_train_doe"
    tbl = c.get(f"{API}/train-does/{new}/result-table", headers=P).json()
    assert tbl["sampling"]["method"] == "TRAIN_DOE" and len(tbl["rows"]) == 3


def test_q1_native_reuse_matrix_and_name_mismatch(p2_native, engine):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "ru2")
    proj = make_project(ai / "ru2" / "00_inbox")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    assem = str(proj / "assem")
    j = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 3, "seed": 7, "multi_execution": 1, "radioss_assem_path": assem})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    src = job(c, j["id"])["result"]["doe_id"]
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": {
        "sampling": {"kind": "train_doe", "doe_id": src}, "num_runs": 3, "radioss_assem_path": assem}})
    assert r.status_code == 422  # 표본표 재사용과 num_runs 동시 금지
    j2 = submit(c, sid, "TD_DOE_GEN", {"sampling": {"kind": "train_doe", "doe_id": src}, "multi_execution": 1, "radioss_assem_path": assem})
    assert j2["params"]["num_runs"] == 3 and j2["params"]["engine"] == "native" and j2["params"]["doe_label"] == "표본표 재사용(Native)"
    assert w.run_once_slot() == "SUCCEEDED", job(c, j2["id"])
    new = job(c, j2["id"])["result"]["doe_id"]
    D0, D1 = (ai / "ru2" / "01_train" / "doe" / src), (ai / "ru2" / "01_train" / "doe" / new)
    m0, m1 = _rows(D0 / "doe_matrix.csv"), _rows(D1 / "doe_matrix.csv")
    assert [x["run_key"] for x in m1] == [x["run_key"] for x in m0] and [x["A_THK_1"] for x in m1] == [x["A_THK_1"] for x in m0]
    assert (D1 / "approaches" / "doe_1" / "run__00003" / "model0_0000.rad").is_file()
    with engine.connect() as conn:
        row = conn.execute(text("select sampling, doe_type from train_does where id=:i"), {"i": new}).one()
    assert row[0] == {"kind": "train_doe", "input": {"doe_id": src}, "meta": None} and row[1] == "NATIVE_LHS"
    # 파라미터 이름 집합이 다르면(원본 samples.csv 열 바꿈) 422 DOE_PARAM_MISMATCH
    sp = D0 / "samples.csv"
    sp.write_text(sp.read_text(encoding="utf-8").replace("A_THK_1", "OTHER_NAME", 1), encoding="utf-8")
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": {
        "sampling": {"kind": "train_doe", "doe_id": src}, "radioss_assem_path": assem}})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["code"] == "DOE_PARAM_MISMATCH"
    assert "OTHER_NAME" in r.json()["detail"]["problems"][0]["message"]
