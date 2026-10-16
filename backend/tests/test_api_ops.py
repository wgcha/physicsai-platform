"""API 시험(공통): 알림 읽음·정리(V-NT-1), 로그·ETag(V-API-2), 산출물(V-SEC-2)."""

from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import text

from helpers_api import PW, P, _job, _sid
from physicsai_test_support import API, IS_WINDOWS, LIMITER, H, make_h3d_tree

# ---- 알림 ---------------------------------------------------------------------------


def test_notifications_read_and_purge(client, engine, loaded_config, worker_factory):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    inp = make_h3d_tree(ai / "S1", 4)
    _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)})
    w = worker_factory()
    assert w.run_once_slot() == "SUCCEEDED"
    u = client.get(f"{API}/notifications/unread-count", headers=P).json()
    assert u["unread_count"] == 2 and u["max_seq"] > 0
    lst = client.get(f"{API}/notifications", headers=P).json()
    assert [i["event"] for i in lst["items"]] == ["JOB_SUCCEEDED", "JOB_STARTED"]
    assert lst["items"][0]["title"] == "완료: 데이터셋 생성 (제목)"
    # 본인 것만
    assert client.get(f"{API}/notifications", headers=H("tok-general")).json()["items"] == []
    after = client.get(f"{API}/notifications?after_seq={lst['items'][1]['seq']}", headers=P).json()
    assert [i["event"] for i in after["items"]] == ["JOB_SUCCEEDED"]
    r = client.post(f"{API}/notifications/read", headers=PW, json={"seqs": [lst["items"][0]["seq"]]})
    assert r.json() == {"unread_count": 1}
    assert client.post(f"{API}/notifications/read", headers=H("tok-general", write=True), json={"all": True}).json() == {"unread_count": 0}
    assert client.get(f"{API}/notifications/unread-count", headers=P).json()["unread_count"] == 1
    assert client.post(f"{API}/notifications/read", headers=PW, json={"all": True}).json() == {"unread_count": 0}
    assert client.post(f"{API}/notifications/read", headers=PW, json={}).status_code == 422
    # 30일 정리
    with engine.begin() as c:
        c.execute(text("update notifications set created_at = now() - interval '31 days' where seq = :s"), {"s": lst["items"][1]["seq"]})
    assert len(client.get(f"{API}/notifications", headers=P).json()["items"]) == 1
    w.housekeeping_once(force_purge=True)
    with engine.connect() as c:
        assert c.execute(text("select count(*) from notifications")).scalar() == 1


# ---- 로그·ETag·산출물·자원 --------------------------------------------------------------


def test_logs_etag_artifacts(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    inp = make_h3d_tree(ai / "S1", 4)
    jid = _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)}).json()["id"]
    r = client.get(f"{API}/jobs/{jid}/log", headers=P)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "LOG_NOT_FOUND"
    r = client.get(f"{API}/jobs/{jid}", headers=P)
    etag = r.headers["ETag"]
    assert etag.startswith(f'"{jid}:')
    assert client.get(f"{API}/jobs/{jid}", headers={**P, "If-None-Match": etag}).status_code == 304
    w = worker_factory()
    assert w.run_once_slot() == "SUCCEEDED"
    assert client.get(f"{API}/jobs/{jid}", headers={**P, "If-None-Match": etag}).status_code == 200
    # 한글 로그를 UTF-8 경계에서 자르기
    logf = ai / "S1" / "logs" / jid / "job.log"
    with open(logf, "a", encoding="utf-8") as fh:
        fh.write("한글로그끝\n")
    size = logf.stat().st_size
    text_all, cur = "", 0
    while True:
        chunk = client.get(f"{API}/jobs/{jid}/log?cursor={cur}&limit=7", headers=P).json()
        text_all += chunk["text"]
        assert chunk["next_cursor"] > cur
        cur = chunk["next_cursor"]
        if chunk["eof"]:
            break
    assert cur == size and text_all == logf.read_bytes().decode("utf-8") and "�" not in text_all  # Windows 텍스트 모드 CRLF 그대로
    assert client.get(f"{API}/jobs/{jid}/log?limit=262145", headers=P).status_code == 422
    st = client.get(f"{API}/jobs/{jid}/steps/3/log", headers=P).json()
    assert "[CMD]" in st["text"]
    assert client.get(f"{API}/jobs/{jid}/steps/99/log", headers=P).status_code == 404
    # 산출물: id로만, 크기 상한, 화이트리스트
    arts = client.get(f"{API}/jobs/{jid}/artifacts", headers=P).json()
    assert len(arts) == 1 and arts[0]["content_type"] == "application/json" and "rel_path" not in arts[0]
    assert client.get(f"{API}/artifacts/does-not-exist/content", headers=P).status_code == 404
    with engine.begin() as c:
        c.execute(text("update artifacts set content_type='application/octet-stream'"))
    assert client.get(f"{API}/artifacts/{arts[0]['id']}/content", headers=P).status_code == 404
    with engine.begin() as c:
        c.execute(text("update artifacts set content_type='application/json', rel_path='../../etc/passwd'"))
    assert client.get(f"{API}/artifacts/{arts[0]['id']}/content", headers=P).status_code in (404, 422)
    # 관리자 include=commands
    j_admin = client.get(f"{API}/jobs/{jid}?include=commands", headers=H("tok-admin")).json()
    assert j_admin["steps"][2]["command"]["argv"][1] == "--physicsai"
    assert client.get(f"{API}/jobs/{jid}?include=commands", headers=P).status_code == 403
    assert client.get(f"{API}/jobs/{jid}", headers=P).json()["steps"][2].get("command") is None
    # 자원: 샘플 없으면 404, 하트비트 후 값
    assert client.get(f"{API}/resources", headers=P).json()["detail"]["code"] == "NO_SAMPLE"
    w.heartbeat_once()
    res = client.get(f"{API}/resources", headers=P).json()
    assert res["gpu"] == [{"name": "RTX A6000", "util_pct": 12.0, "mem_used_mb": 2048.0, "mem_total_mb": 49140.0}]
    assert res["gpu_status"] == "OK" and res["gpu_message"]                # D3-45
    assert res["limits"]["cpu_cap_enforced"] is IS_WINDOWS and res["limits"]["cores"] >= 1
    st = client.get(f"{API}/status", headers=P).json()
    assert st["worker"]["online"] and st["worker"]["limiter"] == LIMITER and st["limits"]["effective"]["cpu_cap_enforced"] is IS_WINDOWS
    tm = {t["key"]: t["configured"] for t in st["templates"]}
    assert tm["rad_assemble"] is False and tm["mesh"] is True  # phase3 §11.4: mesh 기본 = 원본 m_2
    assert st["ui"]["poll_queue_ms"] == 5000
    time.sleep(0)
