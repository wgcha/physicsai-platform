"""⑤ 결과분석 입력 API(s14_analysis.md §19.5, D3-62): V3-S14-1 — GET /train-does/{doe_id}/result-table.

모양, 샘플 표만(응답 없음)·응답 있음·실패 run null·부분 PARSED, 행 상한 notes, influence_ok(LHS·n 조건),
오류(404 DOE_NOT_FOUND·SAMPLES_MISSING, 409 DOE_NOT_READY), 권한(401·member 200), Study 밖·링크 거부,
DB 쓰기 없음(전 테이블 행 수·DOE/run 행 불변), LRU(같은 파일 두 번 읽지 않음·mtime 변경 시 다시), no-store.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from sqlalchemy import text

from helpers_stage1 import P, _ready_doe
from physicsai_api.services import doe_result_table as rt
from physicsai_core.db.repositories import train as train_repo
from physicsai_test_support import API, H

GP = H("tok-general")


def _url(doe_id: str) -> str:
    return f"{API}/train-does/{doe_id}/result-table"


def _prep(p2_env, name: str, runs: int = 7):
    c, mk, ai, _lc, _d = p2_env
    sid, doe_id = _ready_doe(c, mk(), ai, name, num_runs=runs)
    D = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert D["sample_status"] == "PARSED", D
    return c, ai, sid, doe_id


def _doe_row(engine, doe_id: str) -> dict:
    with engine.connect() as conn:
        return train_repo.get_doe(conn, doe_id)


def _write_responses(engine, ai: Path, name: str, doe_id: str, body: str, rel: str | None = None) -> str:
    d = _doe_row(engine, doe_id)
    rel = rel or f"{d['dir_rel']}run_responses.csv"
    p = ai / name / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    with engine.begin() as conn:
        train_repo.set_doe(conn, doe_id, responses_rel=rel)
    return rel


def _set_states(engine, doe_id: str, states: dict[str, str]) -> None:
    with engine.begin() as conn:
        for rk, st in states.items():
            train_repo.set_run(conn, doe_id, rk, state=st)


def _counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))]
        return {n: conn.execute(text(f'SELECT count(*) FROM "{n}"')).scalar() for n in sorted(names)}


def _snapshot(engine, doe_id: str) -> tuple:
    with engine.connect() as conn:
        d = train_repo.get_doe(conn, doe_id)
        runs = train_repo.runs_for_doe(conn, doe_id)
    return (str(sorted(d.items(), key=lambda kv: kv[0])), str(runs))


def test_v3_s14_1_shape_responses_failed_null_influence(p2_env, engine):
    name = "RT1"
    c, ai, _sid, doe_id = _prep(p2_env, name, runs=7)
    keys = [r["run_key"] for r in c.get(f"{API}/train-does/{doe_id}/samples", headers=P).json()["rows"]]
    assert len(keys) == 7

    # 응답 없음 — 샘플 표만: 200 + responses=[] + notes, influence_ok=false
    assert c.get(_url(doe_id)).status_code == 401
    r = c.get(_url(doe_id), headers=GP)  # member 조회
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    d = r.json()
    assert (d["doe_id"], d["study_id"], d["type"]) == (doe_id, _sid, "TYPE_LATINHYPERCUBE")
    assert d["responses"] == [] and "응답 파일이 없습니다" in d["notes"]
    assert d["influence_ok"] is False
    assert d["meta"] == {"engine_version": None, "baseline_id": None, "scene": None}
    assert [p["name"] for p in d["parameters"]] == [h for h in
        c.get(f"{API}/train-does/{doe_id}/samples", headers=P).json()["columns"][1:]]
    assert d["counts"] == {"total": 7, "usable": 0, "no_response": 7}
    row = d["rows"][0]
    assert row["run_id"] == keys[0] and row["no"] == int(keys[0][-5:]) and row["responses"] == {}
    assert set(row["params"]) == {p["name"] for p in d["parameters"]}
    for p in d["parameters"]:  # 스냅샷 범위가 있으면 그것, min ≤ max
        assert p["min"] is not None and p["max"] is not None and p["min"] <= p["max"]

    # 응답 있음: 실패 run은 null, 비유한·빈 값 null, 부분 응답, usable/no_response
    body = "run_key,MaxStress,Disp\n" + "".join(
        f"{k},{100.0 + i},{('' if i == 2 else 0.5 * i)}\n" for i, k in enumerate(keys[:6]))  # 7번째 run은 응답 행 없음
    body = body.replace(f"{keys[3]},103.0,1.5", f"{keys[3]},nan,inf")
    _write_responses(engine, ai, name, doe_id, body)
    _set_states(engine, doe_id, {keys[0]: "COLLECTED", keys[1]: "SOLVE_FAILED", keys[2]: "COLLECTED"})
    d = c.get(_url(doe_id), headers=P).json()
    assert d["responses"] == [{"name": "MaxStress", "unit": None}, {"name": "Disp", "unit": None}]
    assert "응답 파일이 없습니다" not in d["notes"]
    byk = {r["run_id"]: r for r in d["rows"]}
    assert [r["run_id"] for r in d["rows"]] == keys  # samples.csv 순서
    assert byk[keys[0]]["state"] == "COLLECTED" and byk[keys[0]]["responses"] == {"MaxStress": 100.0, "Disp": 0.0}
    assert byk[keys[1]]["state"] == "SOLVE_FAILED" and byk[keys[1]]["responses"] == {"MaxStress": None, "Disp": None}
    assert byk[keys[2]]["responses"] == {"MaxStress": 102.0, "Disp": None}      # 빈 값 = null
    assert byk[keys[3]]["responses"] == {"MaxStress": None, "Disp": None}       # nan·inf = null
    assert byk[keys[4]]["responses"]["MaxStress"] == 104.0
    assert byk[keys[6]]["responses"] == {"MaxStress": None, "Disp": None}       # 응답 행 없음
    assert d["counts"] == {"total": 7, "usable": 4, "no_response": 3}            # run 0·2·4·5
    assert d["influence_ok"] is False                                            # usable 4 < max(5, p+2)

    # n 조건 충족 + LHS → influence_ok
    full = "run_key,MaxStress,Disp\n" + "".join(f"{k},{10 + i},{i * 0.1}\n" for i, k in enumerate(keys))
    _write_responses(engine, ai, name, doe_id, full)
    _set_states(engine, doe_id, {keys[1]: "COLLECTED"})
    d = c.get(_url(doe_id), headers=P).json()
    assert d["counts"] == {"total": 7, "usable": 7, "no_response": 0} and d["influence_ok"] is True
    # LHS 아님 → 비활성
    with engine.begin() as conn:
        train_repo.set_doe(conn, doe_id, doe_type="TYPE_SOBOL")
    d = c.get(_url(doe_id), headers=P).json()
    assert d["type"] == "TYPE_SOBOL" and d["influence_ok"] is False
    # 접두사 resp: 열도 같은 값으로 읽는다
    with engine.begin() as conn:
        train_repo.set_doe(conn, doe_id, doe_type="TYPE_LATINHYPERCUBE")
    _write_responses(engine, ai, name, doe_id, "run_key,resp:Z\n" + f"{keys[0]},3.5\n")
    d = c.get(_url(doe_id), headers=P).json()
    assert d["responses"] == [{"name": "Z", "unit": None}] and d["rows"][0]["responses"] == {"Z": 3.5}


def test_v3_s14_1_partial_and_errors_paths(p2_env, engine):
    name = "RT2"
    c, ai, _sid, doe_id = _prep(p2_env, name, runs=3)
    # 404 DOE_NOT_FOUND
    r = c.get(_url("nope"), headers=P)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "DOE_NOT_FOUND"
    # 부분 PARSED(PARTIAL)도 읽는다
    with engine.begin() as conn:
        train_repo.set_doe(conn, doe_id, sample_status="PARTIAL")
    assert c.get(_url(doe_id), headers=P).status_code == 200
    # 409 DOE_NOT_READY: MISSING·PENDING
    for st in ("MISSING", "PENDING"):
        with engine.begin() as conn:
            train_repo.set_doe(conn, doe_id, sample_status=st)
        r = c.get(_url(doe_id), headers=P)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DOE_NOT_READY", r.text
        assert "샘플 표가 준비되지 않았습니다" in r.json()["detail"]["message"]
    with engine.begin() as conn:
        train_repo.set_doe(conn, doe_id, sample_status="PARSED")
    d0 = _doe_row(engine, doe_id)
    sp = ai / name / d0["samples_rel"]
    # 404 SAMPLES_MISSING: 파일 없음·경로 없음·Study 밖·링크
    def missing(rel):
        with engine.begin() as conn:
            train_repo.set_doe(conn, doe_id, samples_rel=rel)
        r = c.get(_url(doe_id), headers=P)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "SAMPLES_MISSING", (rel, r.text)
        assert r.json()["detail"]["message"] == "DOE 샘플 표가 없습니다"
    missing(None)
    missing("01_train/doe/gone/samples.csv")
    outside = ai / "outside.csv"
    outside.write_text(sp.read_text(encoding="utf-8"), encoding="utf-8")
    missing("../outside.csv")
    link = ai / name / "01_train" / "link_samples.csv"
    os.symlink(sp, link)
    missing("01_train/link_samples.csv")                  # Study 안 대상이어도 링크는 거부
    with engine.begin() as conn:
        train_repo.set_doe(conn, doe_id, samples_rel=d0["samples_rel"])
    assert c.get(_url(doe_id), headers=P).status_code == 200
    # 응답 파일이 밖·링크면 읽지 않고 notes
    for rel in ("../outside.csv", "01_train/link_samples.csv"):
        with engine.begin() as conn:
            train_repo.set_doe(conn, doe_id, responses_rel=rel)
        d = c.get(_url(doe_id), headers=P).json()
        assert d["responses"] == [] and "응답 파일을 읽을 수 없습니다" in d["notes"]


def test_v3_s14_1_row_cap_no_db_write_lru(p2_env, engine):
    name = "RT3"
    c, ai, _sid, doe_id = _prep(p2_env, name, runs=3)
    d0 = _doe_row(engine, doe_id)
    sp = ai / name / d0["samples_rel"]
    cap = p2_env[3].settings.train_data.max_runs  # 2000(계약 §19.5: train_data.max_runs)
    head = sp.read_text(encoding="utf-8").splitlines()[0]
    ncol = head.count(",")
    sp.write_text(head + "\n" + "".join(f"run__{i:05d}" + ",1.5" * ncol + "\n" for i in range(1, cap + 6)), encoding="utf-8")
    d = c.get(_url(doe_id), headers=P).json()
    assert len(d["rows"]) == cap and d["counts"]["total"] == cap
    assert f"앞 {cap}행만 표시합니다" in d["notes"]
    assert d["rows"][-1]["run_id"] == f"run__{cap:05d}" and d["rows"][-1]["no"] == cap
    assert d["rows"][5]["state"] == "UNKNOWN"  # train_runs에 없는 run

    # DB 쓰기 없음
    _write_responses(engine, ai, name, doe_id, "run_key,A\nrun__00001,1\n")
    before_c, before_s = _counts(engine), _snapshot(engine, doe_id)
    for _ in range(3):
        assert c.get(_url(doe_id), headers=P).status_code == 200
    assert _counts(engine) == before_c and _snapshot(engine, doe_id) == before_s

    # LRU: 같은 파일은 다시 읽지 않고, mtime·크기가 바뀌면 다시 읽는다
    rt.cache_clear()
    c.get(_url(doe_id), headers=P)
    info = rt.cache_info()
    assert info["misses"] == 2 and info["hits"] == 0            # samples + responses
    c.get(_url(doe_id), headers=P)
    info2 = rt.cache_info()
    assert info2["misses"] == 2 and info2["hits"] == 2
    rp = ai / name / _doe_row(engine, doe_id)["responses_rel"]
    time.sleep(0.01)
    rp.write_text("run_key,A\nrun__00001,2\nrun__00002,3\n", encoding="utf-8")
    d = c.get(_url(doe_id), headers=P).json()
    assert rt.cache_info()["misses"] == 3                       # 응답 파일만 다시
    assert d["rows"][0]["responses"] == {"A": 2.0} and d["rows"][1]["responses"] == {"A": 3.0}
