"""upload-report.md V-RP-4b(⑤ equiv-check 보고서): 레시피 스냅숏·판정 배지·지표 표·불합격 쌍·곡선 SVG, 삭제된 레시피도 스냅숏, 진행 중 409·404·권한."""

from __future__ import annotations

import pytest

from physicsai_test_support import API, H
from report_support import assert_no_external, assert_report_basics, parse_data

from ..stage4_predict.conftest import predict_env  # noqa: F401 - 픽스처 재사용
from .eq_support import PW, P, body, eq_env, make_predict_batch, make_train_doe, recipe_def, run_check
from .test_equiv_e2e import _with_t01


def _get(env, eid, **params):
    return env.c.get(f"{API}/reports/equiv-check/{eid}", headers=P, params=params)


def test_v_rp_4b_equiv_pass_report(predict_env, fake_tools, fake_record, tmp_path):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path)
    did = make_train_doe(env, runs=3)
    d = run_check(env, body({"kind": "train_doe", "doe_id": did}, {"kind": "train_doe", "doe_id": did, "label": "같은 DOE"}, inline=_with_t01(recipe_def())))
    r = _get(env, d["id"], download=1)
    assert r.status_code == 200, r.text
    doc = assert_report_basics(r, "equiv-check", d["id"], study_title="예측")
    for sid in ("summary", "recipe", "target", "metrics", "fails", "curves"):
        assert f'<section id="{sid}">' in doc, sid
    assert '<span class="badge pass">통과</span>' in doc and "필수 4/4" in doc
    assert "응력 피크" in doc and "가속도 곡선 상관" in doc and "상대 5%" in doc and "r ≥ 0.95" in doc     # 레시피 스냅숏·허용오차
    assert "같은 DOE" in doc and "해석 DOE(①)" in doc                                                  # 대상
    assert "미달 쌍 없음" in doc and doc.count('<svg class="chart"') >= 1                              # 곡선 SVG
    data = parse_data(doc)
    assert data["verdict"] == "PASS" and data["required"] == [4, 4] and data["n_pairs"] == 3
    assert data["metrics"]["acc_corr"]["status"] == "PASS"


def test_v_rp_4b_equiv_fail_pairs_and_deleted_recipe(predict_env, fake_tools, fake_record, tmp_path):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path)
    did = make_train_doe(env, runs=3, h3d_seed=0)
    bid = make_predict_batch(env, ps["id"], runs=3, h3d_seed=1, names=["run__00003", "run__00002", "run__00001"],
                             values=[{"THK_1": 3.0, "N_RIB": 4}, {"THK_1": 2.5, "N_RIB": 3}, {"THK_1": 2.0, "N_RIB": 2}])
    defn = _with_t01(recipe_def(required_stress=True))
    defn["metrics"][0]["tol"] = {"rel_pct": 0.5, "abs": None}
    sid = env.sid
    rec = env.c.post(f"{API}/equiv/recipes", headers=PW, json={"name": "응력 엄격", "scope": "study", "study_id": sid, "definition": defn})
    assert rec.status_code == 201, rec.text
    key = rec.json()["key"]
    b = body({"kind": "train_doe", "doe_id": did}, {"kind": "predict_batch", "batch_id": bid}, pairing="by_params", recipe={"key": key, "version": 1})
    d = run_check(env, b)
    assert d["verdict"] == "FAIL"
    assert env.c.delete(f"{API}/equiv/recipes/{key}", headers=PW).status_code == 204       # 레시피 삭제 후에도 이력 보고서는 스냅숏으로
    r = _get(env, d["id"])
    assert r.status_code == 200 and "content-disposition" not in r.headers  # download 없이 = 새 탭 보기
    doc = r.text
    assert_no_external(doc)
    assert '<span class="badge fail">미달</span>' in doc
    assert "응력 엄격" in doc and "삭제된 레시피" in doc                                      # 스냅숏 + 삭제 표시
    assert "미달 쌍 상위 목록" in doc and "응력 피크" in doc and "미달 쌍 없음" not in doc
    data = parse_data(doc)
    assert data["verdict"] == "FAIL" and data["metrics"]["stress_peak"]["status"] == "FAIL"


def test_v_rp_6_equiv_running_409_404_auth(predict_env, fake_tools, fake_record, tmp_path):  # noqa: F811
    env, ps = eq_env(predict_env, fake_tools, tmp_path)
    did = make_train_doe(env, runs=2)
    c = env.c.post(f"{API}/studies/{env.sid}/equiv-checks", headers=PW,
                   json=body({"kind": "train_doe", "doe_id": did}, {"kind": "train_doe", "doe_id": did}, inline=_with_t01(recipe_def())))
    assert c.status_code == 202, c.text
    r = _get(env, c.json()["eq_id"])                      # 작업이 아직 대기 중 = RUNNING → 409
    assert r.status_code == 409 and r.json()["detail"]["code"] == "REPORT_NOT_READY"
    assert _get(env, "00000000-0000-0000-0000-000000000000").status_code == 404
    assert env.c.get(f"{API}/reports/equiv-check/{c.json()['eq_id']}").status_code == 401
