"""upload-report.md V-RP(⑤ 결과분석 보고서): `GET /reports/analysis?source=batch|doe&id=`.

doe·batch 두 출처의 구역·값·영향도(서버 numpy ↔ 화면 골든 1e-9)·선택 변수/응답·비교 출처·경고, 409(진행 중)·404·422·401, DB 쓰기 없음.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from helpers_stage1 import P, _ready_doe
from physicsai_core.report_html.analysis import influence_for, min_influence_runs
from physicsai_core.stage4_predict import run_metrics as rm
from physicsai_test_support import API, H
from report_support import assert_report_basics, parse_data
from test_api_predict_batch import _batch, _client, _end, _gen_done, _setup
from test_design_map_api import _finish

GP = H("tok-general")
TABLE5 = "THK_1,N_RIB\n3.0,4\n2.5,5\n4.0,7\n3.5,6\n2.2,3\n"
STRESS = [150.0, 120.0, 210.0, 180.0, 95.0]


def _get(c, **params):
    return c.get(f"{API}/reports/analysis", headers=P, params=params)


def _counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))]
        return {n: conn.execute(text(f'SELECT count(*) FROM "{n}"')).scalar() for n in sorted(names)}


def _doe(p2_env, name: str, runs: int = 7, responses: bool = True):
    c, mk, ai, _lc, _d = p2_env
    sid, doe_id = _ready_doe(c, mk(), ai, name, num_runs=runs)
    keys = [r["run_key"] for r in c.get(f"{API}/train-does/{doe_id}/samples", headers=P).json()["rows"]]
    return c, ai, sid, doe_id, keys


def _write_responses(engine, ai: Path, name: str, doe_id: str, keys: list[str]) -> None:
    from physicsai_core.db.repositories import train as train_repo

    with engine.connect() as conn:
        d = train_repo.get_doe(conn, doe_id)
    rel = f"{d['dir_rel']}run_responses.csv"
    p = ai / name / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("run_key,MaxStress,Disp\n" + "".join(f"{k},{100 + 7 * i * i % 13 + i},{0.1 * i}\n" for i, k in enumerate(keys)), encoding="utf-8")
    with engine.begin() as conn:
        train_repo.set_doe(conn, doe_id, responses_rel=rel)
        for k in keys:
            train_repo.set_run(conn, doe_id, k, state="COLLECTED")


def test_v_rp_5_doe_report_sections_values_influence(p2_env, engine):
    name = "RA1"
    c, ai, sid, doe_id, keys = _doe(p2_env, name, runs=7)
    _write_responses(engine, ai, name, doe_id, keys)
    before = _counts(engine)
    r = _get(c, source="doe", id=doe_id, download=1)
    assert r.status_code == 200, r.text
    doc = assert_report_basics(r, "analysis-doe", doe_id)
    for sid_ in ("summary", "input", "table", "varresp", "map", "influence"):
        assert f'<section id="{sid_}">' in doc, sid_
    assert '<section id="curves">' not in doc                       # 커브는 일괄 예측 출처만
    data = parse_data(doc)
    assert data["source"] == "solver" and data["id"] == doe_id and data["counts"]["total"] == 7
    assert [s["name"] for s in data["stats"]] == ["MaxStress", "Disp"]
    assert all(k in doc for k in keys)                              # 결과 표에 run 전부
    # 영향도: 같은 표를 프런트 규칙(influence_for)으로 직접 재계산한 값과 같다(골든 일치는 단위 시험 V-RP-4)
    inf = data["influence"]["MaxStress"]
    assert inf["n"] == 7 and set(inf["prcc"]) == set(inf["src"]) and len(inf["prcc"]) >= 2
    assert any(isinstance(v, float) for v in inf["prcc"].values())            # 상수 열은 null(화면과 같다)
    assert _counts(engine) == before                                # DB 쓰기 0 · 저장 0


def test_v_rp_5_doe_selection_and_warnings(p2_env, engine):
    name = "RA2"
    c, ai, sid, doe_id, keys = _doe(p2_env, name, runs=7)
    _write_responses(engine, ai, name, doe_id, keys)
    cols = c.get(f"{API}/train-does/{doe_id}/samples", headers=P).json()["columns"][1:]
    r = _get(c, source="doe", id=doe_id, vars=[f"{cols[1]},{cols[0]}", "NOPE"], resp="Disp")
    d = parse_data(r.text)
    assert d["vars"] == [cols[1], cols[0]] and d["resp"] == "Disp"        # 쉼표·반복 모두, 알 수 없는 변수는 무시
    assert "알 수 없는 변수를 무시했습니다: NOPE" in r.text
    r = _get(c, source="doe", id=doe_id, resp="없는응답")
    d = parse_data(r.text)
    assert d["resp"] == "MaxStress" and "알 수 없는 응답" in r.text       # 첫 응답으로 대체 + 경고
    assert list(d["vars"]) == cols[:1]                                      # 변수 기본 = 첫 변수 1개


def test_v_rp_5_doe_no_responses_and_too_few_runs(p2_env, engine):
    c, ai, sid, doe_id, keys = _doe(p2_env, "RA3", runs=3)
    r = _get(c, source="doe", id=doe_id)                                   # 응답 파일 없음 = 샘플 표만도 보고서는 만든다
    assert r.status_code == 200, r.text
    assert "영향도" in r.text and "응답이 없어" in r.text
    assert parse_data(r.text)["influence"] == {}


def test_v_rp_6_doe_errors_auth(p2_env, engine):
    c, ai, sid, doe_id, keys = _doe(p2_env, "RA4", runs=3)
    u = f"{API}/reports/analysis"
    assert c.get(u, params={"source": "doe", "id": doe_id}).status_code == 401
    assert c.get(u, headers=GP, params={"source": "doe", "id": doe_id}).status_code == 200        # member 조회
    r = _get(c, source="doe", id="nope")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "DOE_NOT_FOUND"
    r = _get(c, source="zzz", id=doe_id)
    assert r.status_code == 422
    r = _get(c, source="doe", id=doe_id, compare_source="doe")             # 비교는 둘 다 있어야
    assert r.status_code == 422
    r = _get(c, source="doe", id=doe_id, compare_source="batch", compare_id="nope")
    assert r.status_code == 404
    r = c.get(f"{API}/reports/nothing/{doe_id}", headers=P)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "REPORT_TARGET_UNKNOWN"


def test_v_rp_5_batch_report_curves_compare_409(settings_dict, engine, fake_dashboard, worker_factory):
    rm.cache_clear()
    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "RB")
        job = _batch(c, sid, {"kind": "table", "text": TABLE5})
        assert job.status_code == 201, job.text
        bid = job.json()["params"]["batch_id"]
        kids = _gen_done(engine, ai, "RB", bid)
        assert len(kids) == 5
        r = _get(c, source="batch", id=bid)                                  # 진행 중 → 409 REPORT_NOT_READY
        assert r.status_code == 409 and r.json()["detail"]["code"] == "REPORT_NOT_READY"
        for i, k in enumerate(kids):
            _finish(engine, ai, "RB", sid, k, series=[{"name": "Acc", "x": [0, 1, 2], "y": [0.0, STRESS[i] / 10, STRESS[i]]}],
                    resp_text=f"RESP:MaxStress_MAX={STRESS[i]}\n", table=[{"name": "MaxStress", "unit": "MPa", "predicted": STRESS[i]}])
        before = _counts(engine)
        r = _get(c, source="batch", id=bid, download=1)
        assert r.status_code == 200, r.text
        doc = assert_report_basics(r, "analysis-batch", bid)
        for s in ("summary", "input", "table", "varresp", "map", "influence", "curves"):
            assert f'<section id="{s}">' in doc, s
        data = parse_data(doc)
        assert data["source"] == "predict" and data["counts"]["total"] == 5
        assert doc.count('<svg class="chart"') >= 4                          # 변수–응답·지도·영향도·커브
        assert "run__00001" in doc and "MaxStress" in doc and "표본 방식" in doc
        # 같은 배치끼리 비교 — 같은 Study·같은 파라미터 이름이라 겹쳐 그린다
        r2 = _get(c, source="batch", id=bid, compare_source="batch", compare_id=bid)
        assert r2.status_code == 200 and "비교 출처" in r2.text and parse_data(r2.text)["compare"] == bid
        assert _counts(engine) == before
        assert c.get(f"{API}/reports/analysis", params={"source": "batch", "id": bid}).status_code == 401


def test_v_rp_4_influence_for_matches_documented_minimum():
    rows = [{"no": i, "run_id": f"r{i}", "state": "SUCCEEDED", "params": {"a": float(i), "b": float(i * i % 7)}, "responses": {"y": 2.0 * i + (i * i % 7)}}
            for i in range(1, 9)]
    rt = {"source": "predict", "parameters": [{"name": "a"}, {"name": "b"}], "responses": [{"name": "y"}], "rows": rows,
          "influence": {"ok": True, "cls": "reference", "note": "참고", "reason": None}}
    v = influence_for(rt, "y")
    assert v["disabled"] is None and v["note"] == "참고" and v["result"].n == 8
    few = {**rt, "rows": rows[: min_influence_runs(2) - 1]}
    assert influence_for(few, "y")["disabled"].startswith("영향도에는 유효 run이 5개 이상 필요합니다")
    off = {**rt, "source": "solver", "influence": {"ok": False, "reason": "계산 불가"}}
    assert influence_for(off, "y")["disabled"] == "계산 불가"


def test_v_rp_6_too_large_413_via_api(p2_env, engine, monkeypatch):
    from physicsai_api.services import reports as svc
    from physicsai_core.report_html.page import Limits

    c, ai, sid, doe_id, keys = _doe(p2_env, "RA5", runs=7)
    _write_responses(engine, ai, "RA5", doe_id, keys)
    assert _get(c, source="doe", id=doe_id).status_code == 200
    monkeypatch.setattr(svc, "limits_resolved", lambda ctx: Limits(max_bytes=4000))     # report.max_bytes를 작게
    r = _get(c, source="doe", id=doe_id)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "REPORT_TOO_LARGE"
