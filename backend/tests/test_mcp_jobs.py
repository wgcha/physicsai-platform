"""mcp.md V-MCP-4(confirm)·V-MCP-5(감사)·V-MCP-11(plan·동시 작업 제한)·V-MCP-12(토큰 취소 예외)·종류 허용/거부."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from mcp_helpers import T, enable, import_root, install_test_kinds, issue, shift_clock  # noqa: F401 - fixture
from physicsai_test_support import API, H


@pytest.fixture()
def settings_dict(settings_dict):
    return enable(settings_dict)


def _study(client, name="S1", token="tok-power"):
    r = client.post(f"{API}/studies", headers=H(token, write=True), json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _plan(client, headers, sid, kind="test_heavy", **params):
    return client.post(f"{API}/mcp/jobs/plan", headers=headers, json={"kind": kind, "study_id": sid, "params": params})


def _run(client, headers, sid, kind="test_heavy", confirm=None, **params):
    body = {"kind": kind, "study_id": sid, "params": params, **({"confirm_token": confirm} if confirm else {})}
    return client.post(f"{API}/mcp/jobs", headers=headers, json=body)


def test_v_mcp_4_confirm_flow(client, engine, monkeypatch, import_root):
    calls = install_test_kinds(monkeypatch, import_root)
    sid = _study(client)
    run, _ = issue(client, scope="run")
    read, _ = issue(client, scope="read", name="ro")
    # read 토큰·세션 plan은 confirm_token 없음
    assert _plan(client, T(read), sid).json()["confirm_token"] is None
    p = _plan(client, H("tok-power", write=True), sid).json()
    assert p["valid"] and p["confirm_required"] and p["confirm_token"] is None and p["runs"] == 1 and p["lane"]
    # problems 있으면 confirm 없음
    bad = _plan(client, T(run), sid, bad=True).json()
    assert bad["valid"] is False and bad["confirm_token"] is None and bad["problems"][0]["code"] == "TEST_BAD"
    # heavy + 토큰: confirm 없으면 428
    r = _run(client, T(run), sid, n=2)
    assert r.status_code == 428 and r.json()["detail"]["code"] == "CONFIRM_REQUIRED" and r.json()["detail"]["plan_with"] == "plan_job"
    pl = _plan(client, T(run), sid, n=2).json()
    tok = pl["confirm_token"]
    assert tok.startswith("pcf_") and pl["expires_at"]
    r = _run(client, T(run), sid, confirm=tok, n=3)  # 다른 params
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "mismatch"
    r = _run(client, T(run), sid, confirm="pcf_nope", n=2)
    assert r.json()["detail"]["reason"] == "unknown"
    shift_clock(monkeypatch, seconds=601)
    r = _run(client, T(run), sid, confirm=tok, n=2)
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "expired"
    monkeypatch.undo()
    calls = install_test_kinds(monkeypatch, import_root)
    pl = _plan(client, T(run), sid, n=2).json()
    r = _run(client, T(run), sid, confirm=pl["confirm_token"], n=2)
    assert r.status_code == 201, r.text
    js = r.json()
    assert js["kind"] == "test_heavy" and js["job_type"] == "MODEL_REGISTER" and js["state"] == "QUEUED"
    assert js["via_token"] and js["via_token"].startswith("pai_") and calls["create"] == [(sid, 2)]
    with engine.connect() as c:
        used = c.execute(text("select used_job_id, used_at from mcp_plans where id = :i"), {"i": pl["plan_id"]}).one()
        tid = c.execute(text("select api_token_id from jobs where id = :i"), {"i": js["job_id"]}).scalar()
        det = c.execute(text("select detail from audit_events where action = 'JOB_CREATE' and target_id = :i"),
                        {"i": js["job_id"]}).scalar()
    assert used[0] == js["job_id"] and used[1] is not None and tid is not None and det["api_token_id"] == tid
    r = _run(client, T(run), sid, confirm=pl["confirm_token"], n=2)  # 재사용
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "used"
    # light·세션은 confirm 없이 201
    sid2, sid3 = _study(client, "S2"), _study(client, "S3")
    assert _run(client, T(run), sid2, kind="test_light").status_code == 201
    r = _run(client, H("tok-power", write=True), sid3)
    assert r.status_code == 201 and r.json()["via_token"] is None
    # 생성 시점 재검증: 같은 Study 활성 작업 → 기존 409, confirm은 되살아난다(작업 미생성)
    pl = _plan(client, T(run), sid3).json()
    r = _run(client, T(run), sid3, confirm=pl["confirm_token"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STUDY_JOB_BUSY"
    with engine.connect() as c:
        assert c.execute(text("select used_at from mcp_plans where id = :i"), {"i": pl["plan_id"]}).scalar() is None


def test_kind_unknown_denied_and_session_csrf(client, monkeypatch, import_root):
    install_test_kinds(monkeypatch, import_root)
    sid = _study(client)
    run, _ = issue(client, scope="run")
    r = _plan(client, T(run), sid, kind="nope")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "JOB_KIND_UNKNOWN"
    r = _plan(client, T(run), sid, kind="solve_pbs", doe_id="x")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "JOB_KIND_DENIED"  # Q3 기본 denied_job_kinds
    kinds = {k["kind"]: k for k in client.get(f"{API}/mcp/job-kinds", headers=T(run)).json()}
    assert kinds["solve_pbs"]["allowed"] is False and kinds["predict"]["confirm_required"] is False
    d = client.get(f"{API}/mcp/job-kinds/doe_generate", headers=T(run)).json()
    assert d["params_schema"]["properties"]["sampling"]["description"] and d["limits"]["max_runs"] > 0
    r = client.post(f"{API}/mcp/jobs/plan", headers=H("tok-power"), json={"kind": "test_heavy", "study_id": sid})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CSRF_HEADER_REQUIRED"  # 세션은 CSRF 그대로
    r = _plan(client, T(run), "no-such-study")
    assert r.status_code == 404
    # 실제 종류 plan(가짜 도구 환경): 사전조건 문제는 problems로, 저장 없음
    pl = _plan(client, T(run), sid, kind="doe_generate", generator="platform", sampling={"kind": "lhs", "count": 5},
               radioss_assem_path="/nope").json()
    assert pl["valid"] is False and pl["problems"] and pl["confirm_token"] is None
    assert client.get(f"{API}/mcp/jobs?study_id={sid}", headers=T(run)).json() == []


def test_v_mcp_11_plans_and_active_jobs(client, monkeypatch, import_root):
    install_test_kinds(monkeypatch, import_root)
    run, _ = issue(client, scope="run")
    sids = [_study(client, f"S{i}") for i in range(5)]
    for i in range(10):
        assert _plan(client, T(run), sids[0]).status_code == 200
    r = _plan(client, T(run), sids[0])
    assert r.status_code == 429 and r.json()["detail"]["code"] == "RATE_LIMITED" and r.headers.get("Retry-After")
    for sid in sids[:3]:
        assert _run(client, T(run), sid, kind="test_light").status_code == 201
    r = _run(client, T(run), sids[3], kind="test_light")
    assert r.status_code == 429 and r.json()["detail"]["code"] == "TOKEN_ACTIVE_JOB_LIMIT"
    assert len(r.json()["detail"]["active_job_ids"]) == 3
    assert _run(client, H("tok-power", write=True), sids[3], kind="test_light").status_code == 201  # 세션 무제한


def test_v_mcp_12_token_cancel_exception(client, monkeypatch, import_root):
    install_test_kinds(monkeypatch, import_root)
    run, _ = issue(client, scope="run")
    other, _ = issue(client, scope="run", name="other")
    run2, _ = issue(client, session="tok-power2", scope="run", name="p2")
    s1, s2, s3 = _study(client, "S1"), _study(client, "S2"), _study(client, "S3")
    mine = _run(client, T(run), s1, kind="test_light").json()["job_id"]
    theirs = _run(client, T(run2), s2, kind="test_light").json()["job_id"]
    web = _run(client, H("tok-power", write=True), s3, kind="test_light").json()["job_id"]
    for jid, tok in ((theirs, run), (mine, other), (web, run)):
        r = client.post(f"{API}/mcp/jobs/{jid}/cancel", headers=T(tok))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "PERMISSION_DENIED"
    r = client.post(f"{API}/mcp/jobs/{mine}/cancel", headers=T(run))
    assert r.status_code == 202 and r.json()["state"] == "CANCELED"
    assert client.post(f"{API}/mcp/jobs/{mine}/cancel", headers=T(run)).status_code == 202  # 멱등
    # 기존 POST /jobs/{id}/cancel 권한 불변(전역 관리자만), 토큰은 허용 목록 밖
    assert client.post(f"{API}/jobs/{web}/cancel", headers=H("tok-power", write=True)).status_code == 403
    assert client.post(f"{API}/jobs/{web}/cancel", headers=T(run)).json()["detail"]["code"] == "API_TOKEN_OPERATION_NOT_ALLOWED"
    st = client.get(f"{API}/mcp/jobs/{theirs}", headers=T(run)).json()
    assert st["state"] == "QUEUED" and st["queue_position"] >= 1


def test_v_mcp_5_audit(client, engine, monkeypatch, import_root):
    install_test_kinds(monkeypatch, import_root)
    sid = _study(client)
    run, tok = issue(client, scope="run")
    client.get(f"{API}/studies", headers=T(run))  # 토큰 GET: record_reads false → 기록 없음
    pl = _plan(client, T(run), sid, n=1).json()
    _run(client, T(run), sid, n=1)  # 428
    ok = _run(client, T(run), sid, confirm=pl["confirm_token"], n=1).json()
    client.get(f"{API}/queue", headers=T(run))  # 403
    client.get(f"{API}/me", headers=T("pai_abcdefgh_" + "x" * 43))  # 401
    with engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(text("select * from api_audit order by occurred_at"))]
        dump = " ".join(r[0] for r in c.execute(text("select row_to_json(a)::text from api_audit a")))
    by = [(r["tool"], r["status_code"], r["result_code"]) for r in rows]
    assert ("plan_job", 200, None) in by and ("run_job", 428, "CONFIRM_REQUIRED") in by and ("run_job", 201, None) in by
    assert (None, 403, "API_TOKEN_OPERATION_NOT_ALLOWED") in by and ("whoami", 401, "API_TOKEN_INVALID") in by
    assert not any(r["route"] == "/physicsai/api/studies" for r in rows)
    created = next(r for r in rows if r["status_code"] == 201)
    assert created["job_id"] == ok["job_id"] and created["kind"] == "test_heavy" and created["study_id"] == sid
    assert created["plan_id"] == pl["plan_id"] and len(created["params_sha256"]) == 64 and created["api_token_id"] == tok["id"]
    assert created["token_prefix"] == tok["token_prefix"] and created["duration_ms"] is not None
    assert run not in dump and pl["confirm_token"] not in dump and run[12:] not in dump
    page = client.get(f"{API}/mcp/audit?limit=2", headers=H("tok-admin")).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    assert client.get(f"{API}/mcp/audit", headers=H("tok-power")).status_code == 403
    # 보존 초과 정리(워커 housekeeping)
    from datetime import datetime, timedelta, timezone

    from physicsai_worker import housekeeping

    from physicsai_core.config import load_config_dict

    cfg = load_config_dict({"mcp": {"enabled": True}}, environ={}).settings
    out = housekeeping.purge_mcp(engine, cfg, now=datetime.now(timezone.utc) + timedelta(days=181))
    assert out["api_audit"] == len(rows) and out["mcp_plans"] >= 1


def test_v_mcp_8_summary_and_read_tools(client, monkeypatch, import_root, tmp_path):
    install_test_kinds(monkeypatch, import_root)
    sid = _study(client)
    read, _ = issue(client, scope="read")
    run, _ = issue(client, scope="run", name="run")
    jid = _run(client, T(run), sid, kind="test_light").json()["job_id"]
    s = client.get(f"{API}/mcp/summary/study/{sid}", headers=T(read))
    assert s.status_code == 200, s.text
    env = s.json()
    assert env["entity"] == "study" and env["title"] == "S1" and env["facts"]["param_set_count"] == 0
    assert {t["name"] for t in env["tables"]} == {"stages", "recent_jobs"} and env["bytes"] <= 8192
    assert str(tmp_path) not in s.text  # 절대경로 없음
    js = client.get(f"{API}/mcp/jobs/{jid}/summary?top_n=3", headers=T(read)).json()
    assert js["entity"] == "job" and js["state"] == "QUEUED" and js["tables"][0]["name"] == "steps"
    r = client.get(f"{API}/mcp/summary/nope/{sid}", headers=T(read))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "SUMMARY_ENTITY_UNKNOWN"
    assert client.get(f"{API}/mcp/summary/study/missing", headers=T(read)).status_code == 404
    lst = client.get(f"{API}/mcp/jobs?study_id={sid}&kind=test_light", headers=T(read)).json()
    assert [x["job_id"] for x in lst] == [jid]
    sysst = client.get(f"{API}/mcp/system", headers=T(read)).json()
    assert sysst["config_ok"] in (True, False) and sysst["features"]["mcp"] is True and len(sysst["queue_head"]) <= 5
    g = client.get(f"{API}/mcp/glossary?section=feature_abbr", headers=T(read)).json()
    assert "THK" in g["feature_abbr"]
    full = client.get(f"{API}/mcp/glossary", headers=T(read))
    assert len(full.content) <= 65536 and any(t["key"] == "feature:THK" for t in full.json()["terms"])
    assert client.get(f"{API}/mcp/glossary?section=bogus", headers=T(read)).status_code == 422
    tools = client.get(f"{API}/mcp/tools", headers=T(read)).json()
    assert len(tools["tools"]) == 17
    pg = client.get(f"{API}/mcp/ping", headers=T(read)).json()
    assert pg["ok"] is True and pg["mcp_enabled"] is True and pg["tools_count"] == 17 and pg["warnings"] == []
    assert pg["token"]["scope"] == "read" and pg["token"]["prefix"] == read[:12] and pg["token"]["days_left"] in (29, 30)
    assert client.get(f"{API}/mcp/ping", headers=H("tok-power")).json()["token"] is None  # 세션 요청
    assert client.get(f"{API}/status", headers=H("tok-power")).json()["features"]["mcp"]["enabled"] is True
