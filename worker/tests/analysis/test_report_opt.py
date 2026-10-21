"""upload-report.md V-RP-1·2·3·6(⑥): GET /reports/surrogate-opt/{id}·/reports/optimization/{id} — 내장 ego·ga·nsga2 각 1건(가짜 도구 + 워커로 DONE까지),
설정·최적안·파레토·수렴/HV·검증·기준안 비교·권한·409·404·헤더·파일명·외부 자원 0."""

from __future__ import annotations

import pytest

from physicsai_test_support import API, H

from ..stage4_predict.conftest import predict_env  # noqa: F401 - on_env가 쓰는 픽스처
from ..test_on_flow import MO, _body, _create, _detail, _drain, on_env  # noqa: F401 - on_env 픽스처 재사용
from report_support import assert_report_basics, parse_data  # noqa: E402

P = H("tok-power")


def _get(env, target, tid, **params):
    return env.c.get(f"{API}/reports/{target}/{tid}", headers=P, params=params)


def _done(env, **kw):
    opt = _create(env, _body(**kw))
    seen = _drain(env)
    assert all(st == "SUCCEEDED" for _, st in seen), seen
    d = _detail(env, opt["id"])
    assert d["status"] == "DONE", d["progress_text"]
    return d


def test_v_rp_3_ego_single_report(on_env):
    env = on_env
    d = _done(env, iterations=2, candidates=2)
    r = _get(env, "surrogate-opt", d["id"], download=1)
    assert r.status_code == 200, r.text
    doc = assert_report_basics(r, "surrogate-opt", d["id"], study_title="예측")
    for s in ('<section id="input">', '<section id="setting">', '<section id="result">', '<section id="convergence">', '<section id="verify">'):
        assert s in doc, s
    assert "EGO(기대 개선)" in doc and "MaxStress_MAX" in doc and "최소화" in doc            # 설정: 목적·방향·알고리즘
    assert "최적안 — 기준안 대비 변수" in doc or "기준안 대비 변수" in doc
    assert "수렴 그래프" in doc and doc.count("<svg") >= 2                                # 수렴 SVG
    assert "예측 vs 해석(검증 run)" in doc                                                # 검증 결과
    assert "THK_1" in doc and "N_RIB" in doc and "변수와 범위" in doc
    data = parse_data(doc)
    assert data["target"] == "surrogate-opt" and data["mode"] == "single" and data["best"]["objective"] == pytest.approx(d["best"]["objective"])
    assert "파라미터 세트(템플릿)" in doc and "형상 엔진" in doc and "Altair(SimLab)" in doc


def test_v_rp_3_ga_report_and_not_ready_and_404(on_env):
    env = on_env
    env.to_mesh_only(env.ps["id"])
    opt = _create(env, _body(algorithm="ga", algo_options={"generations": 30}))
    # 진행 중 → 409 REPORT_NOT_READY
    r = _get(env, "surrogate-opt", opt["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "REPORT_NOT_READY"
    seen = _drain(env)
    assert all(st == "SUCCEEDED" for _, st in seen), seen
    r = _get(env, "surrogate-opt", opt["id"])
    assert r.status_code == 200
    doc = r.text
    assert "GA(유전 알고리즘)" in doc and "pop_size=40" in doc and "generations=30" in doc   # 하이퍼파라미터
    assert "메시 단독" in doc
    # 404: 없는 id·없는 target
    assert _get(env, "surrogate-opt", "00000000-0000-0000-0000-000000000000").status_code == 404
    bad = _get(env, "predict", opt["id"])
    assert bad.status_code == 404 and bad.json()["detail"]["code"] == "REPORT_TARGET_UNKNOWN"
    # 인증 필수
    assert env.c.get(f"{API}/reports/surrogate-opt/{opt['id']}").status_code == 401
    # 비멤버·일반 사용자도 Study 조회 권한이면 받을 수 있다(조회는 member 이상 공통)
    assert env.c.get(f"{API}/reports/surrogate-opt/{opt['id']}", headers=H("tok-general")).status_code == 200


def test_v_rp_3_nsga2_pareto_report(on_env):
    env = on_env
    d = _done(env, **MO, algorithm="nsga2", algo_options={"generations": 30})
    r = _get(env, "surrogate-opt", d["id"], download=1)
    assert r.status_code == 200, r.text
    doc = assert_report_basics(r, "surrogate-opt", d["id"], study_title="예측")
    assert 'section id="pareto"' in doc and "NSGA-II" in doc
    assert "파레토 산점" in doc and "HV 추이" in doc and "검증된 파레토 해" in doc
    assert "★" in doc                                                      # 추천 해 표시
    data = parse_data(doc)
    assert data["mode"] == "multi" and data["pareto_size"] == len(d["pareto"]["front"]) and data["pareto_size"] >= 1
    for key in (x["key"] for x in d["pareto"]["front"][:3]):
        assert f"<td>{'★ ' if key == d['pareto']['recommended_key'] else ''}{key}</td>" in doc


def test_v_rp_3_surrogate_only_says_no_verification(on_env):
    env = on_env
    opt = _create(env, _body(algorithm="ga", algo_options={"generations": 30}, verification="none", iterations=5, candidates=3))
    _drain(env)
    r = _get(env, "surrogate-opt", opt["id"])
    assert r.status_code == 200 and "검증 없음" in r.text and "대리모델만" in r.text


def test_v_rp_3_legacy_optimization_404_when_unset(on_env):
    """HyperStudy 미설정(on_env는 hst_* null) → /reports/optimization 404, 내장은 그대로."""
    env = on_env
    r = _get(env, "optimization", "00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "REPORT_TARGET_UNKNOWN"
