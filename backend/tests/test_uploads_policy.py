"""upload-report.md V-UP-5~7·9~11: 상한·디스크 예약·ENOSPC, 권한·CSRF·동시 수·남의 세션, 취소·낡음(_backup, 삭제 0), multipart 0·x-mcp·로그, 설정·상태·점검."""

from __future__ import annotations

import errno
import logging
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from mcp_helpers import T, enable, issue
from physicsai_test_support import API, H
from up_helpers import MB, blob, code, complete, create, get, make_client, put, send, study  # noqa: F401

GIB = 1024 ** 3


def _free(monkeypatch, value):
    from physicsai_core import uploads as U

    monkeypatch.setattr(U, "free_bytes", lambda _p: value)


# ---- V-UP-5 ---------------------------------------------------------------------------------------------


def test_v_up_5_size_count_total_limits(make_client):
    c, _ = make_client(upload={"max_file_bytes": 1000, "max_upload_bytes": 1500, "max_files": 3})
    sid = study(c)
    assert code(create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x" * 1001}, declare_sha=False)) == (413, "UPLOAD_TOO_LARGE")
    r = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x" * 1000, "b.csv": b"x" * 1000})  # 합 2000 > 1500
    assert code(r) == (413, "UPLOAD_TOO_LARGE") and r.json()["detail"]["limit"] == 1500
    r = create(c, sid, "RADIOSS_ASSEM", {f"f{i}.csv": b"x" for i in range(4)})
    assert code(r) == (413, "UPLOAD_TOO_MANY_FILES")
    assert code(create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x", "A.CSV": b"y"})) == (409, "UPLOAD_FILE_DUPLICATE")
    assert code(create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x", "a.csv/b.csv": b"y"})) == (409, "UPLOAD_FILE_DUPLICATE")
    up = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x" * 1000}).json()  # 경계값(= 상한)은 통과
    r = c.post(f"{API}/uploads/{up['upload_id']}/files", headers=H("tok-power", True), json={"files": [{"rel": "b.csv", "size": 501}]})
    assert code(r) == (413, "UPLOAD_TOO_LARGE")  # 추가분 포함 합계 1501 > 1500


def test_v_up_5_default_64gib_file_and_200gib_session_boundaries(make_client, monkeypatch):
    _free(monkeypatch, 10 ** 15)
    c, _ = make_client()
    sid = study(c)

    def mk(sizes, name):
        files = [{"rel": f"f{i}.h3d", "size": s} for i, s in enumerate(sizes)]
        return c.post(f"{API}/studies/{sid}/uploads", headers=H("tok-power", True),
                      json={"purpose": "DATASET_INPUT", "name": name, "files": files})

    r = mk([64 * GIB], "ok1")
    assert r.status_code == 201 and r.json()["total_bytes"] == 64 * GIB  # 64 GiB는 허용(희소·미할당)
    assert code(mk([64 * GIB + 1], "big")) == (413, "UPLOAD_TOO_LARGE")
    r = mk([64 * GIB, 64 * GIB, 64 * GIB, 8 * GIB], "ok2")
    assert r.status_code == 201  # 200 GiB 딱 맞춤
    assert code(mk([64 * GIB, 64 * GIB, 64 * GIB, 8 * GIB + 1], "big2")) == (413, "UPLOAD_TOO_LARGE")
    for uid in [r.json()["upload_id"]]:
        assert c.delete(f"{API}/uploads/{uid}", headers=H("tok-power", True)).status_code == 200


def test_v_up_5_disk_reservation_and_min_free(make_client, monkeypatch):
    c, _ = make_client()
    sid = study(c)
    _free(monkeypatch, 3000)
    assert code(create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x" * 3001}, declare_sha=False)) == (507, "INSUFFICIENT_STORAGE")
    a = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x" * 2000}, name="a")
    assert a.status_code == 201
    r = create(c, sid, "RADIOSS_ASSEM", {"b.csv": b"x" * 1500}, name="b", token="tok-power2")  # 1500 + 진행 중 예약 2000 > 3000
    assert code(r) == (507, "INSUFFICIENT_STORAGE") and r.json()["detail"]["reserved"] == 2000
    # 받은 만큼 예약이 줄어든다: 1000 보냈으면 남은 1000 → 1500 + 1000 ≤ 3000
    assert put(c, a.json()["upload_id"], 0, 0, b"x" * 1000, chunk_sha=False).status_code == 200
    assert create(c, sid, "RADIOSS_ASSEM", {"b.csv": b"x" * 1500}, name="b", token="tok-power2").status_code == 201
    # 취소하면 예약 해제
    assert c.delete(f"{API}/uploads/{a.json()['upload_id']}", headers=H("tok-power", True)).status_code == 200
    assert create(c, sid, "RADIOSS_ASSEM", {"c.csv": b"x" * 1400}, name="c").status_code == 201  # a(남은 1000) 해제 후: 1400 + b 1500 ≤ 3000
    assert code(create(c, sid, "RADIOSS_ASSEM", {"d.csv": b"x" * 200}, name="d", token="tok-admin")) == (507, "INSUFFICIENT_STORAGE")  # 200 + 2900 > 3000


def test_v_up_5_min_free_gb_reserve(make_client, monkeypatch):
    c, _ = make_client(upload={"min_free_gb": 2})
    sid = study(c)
    _free(monkeypatch, 3 * GIB)
    assert create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x"}, name="a").status_code == 201
    r = c.post(f"{API}/studies/{sid}/uploads", headers=H("tok-power", True),
               json={"purpose": "RADIOSS_ASSEM", "name": "b", "files": [{"rel": "b.csv", "size": GIB + 2}]})
    assert code(r) == (507, "INSUFFICIENT_STORAGE") and r.json()["detail"]["min_free_bytes"] == 2 * GIB


def test_v_up_5_add_files_checks_disk(make_client, monkeypatch):
    c, _ = make_client()
    sid = study(c)
    _free(monkeypatch, 2500)
    up = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x" * 2000}).json()
    r = c.post(f"{API}/uploads/{up['upload_id']}/files", headers=H("tok-power", True), json={"files": [{"rel": "b.csv", "size": 600}]})
    assert code(r) == (507, "INSUFFICIENT_STORAGE")  # 새 600 + 이 세션 남은 2000 > 2500


def test_v_up_5_enospc_during_chunk_then_resume(make_client, monkeypatch):
    from physicsai_core import uploads as U

    c, _ = make_client()
    sid = study(c)
    data = blob(MB + 100, "e")
    up = create(c, sid, "RADIOSS_ASSEM", {"a.csv": data}).json()
    uid = up["upload_id"]
    assert put(c, uid, 0, 0, data[:MB]).status_code == 200
    real = U.append_chunk
    calls = {"n": 0}

    def full_disk(part, d, root=None):
        calls["n"] += 1
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(U, "append_chunk", full_disk)
    r = put(c, uid, 0, MB, data[MB:])
    assert code(r) == (507, "INSUFFICIENT_STORAGE") and r.json()["detail"]["received"] == MB and calls["n"] == 1
    assert get(c, uid)["files"][0]["received"] == MB  # 받은 데까지 유지
    monkeypatch.setattr(U, "append_chunk", real)
    r = put(c, uid, 0, MB, data[MB:])
    assert r.status_code == 200 and r.json()["done"] is True


def test_v_up_13_chunk_memory_bounded_and_streaming_413(make_client):
    c, _ = make_client()
    sid = study(c)
    up = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"x"}, declare_sha=False).json()
    h = {**H("tok-power", True), "Content-Type": "application/octet-stream"}
    # Content-Length 없는 스트림도 chunk_size를 넘으면 즉시 413(메모리 = 청크 1개)
    def gen():
        for _ in range(3):
            yield b"z" * (MB // 2)

    r = c.put(f"{API}/uploads/{up['upload_id']}/files/0", params={"offset": 0}, content=gen(), headers=h)
    assert code(r) == (413, "CHUNK_TOO_LARGE")
    assert get(c, up["upload_id"])["files"][0]["received"] == 0


# ---- V-UP-6 ---------------------------------------------------------------------------------------------


def test_v_up_6_permissions_csrf_and_foreign_sessions(make_client):
    c, _ = make_client()
    sid = study(c)
    files = {"a.csv": b"hello"}
    # 권한: viewer(general)·비멤버·미인증, CSRF 헤더 없음
    assert code(create(c, sid, "RADIOSS_ASSEM", files, token="tok-general")) == (403, "PERMISSION_DENIED")
    assert code(create(c, sid, "RADIOSS_ASSEM", files, token="tok-nonmember")) == (403, "PERMISSION_DENIED")
    r = c.post(f"{API}/studies/{sid}/uploads", json={"purpose": "RADIOSS_ASSEM", "name": "n", "files": [{"rel": "a.csv", "size": 1}]})
    assert r.status_code == 401
    r = c.post(f"{API}/studies/{sid}/uploads", headers=H("tok-power"), json={"purpose": "RADIOSS_ASSEM", "name": "n", "files": [{"rel": "a.csv", "size": 1}]})
    assert code(r) == (403, "CSRF_HEADER_REQUIRED")
    assert code(c.post(f"{API}/studies/00000000-0000-0000-0000-000000000000/uploads", headers=H("tok-power", True),
                       json={"purpose": "RADIOSS_ASSEM", "name": "n", "files": [{"rel": "a.csv", "size": 1}]})) == (404, "NOT_FOUND")
    up = create(c, sid, "RADIOSS_ASSEM", files).json()
    uid = up["upload_id"]
    assert code(put(c, uid, 0, 0, b"hello", write=False)) == (403, "CSRF_HEADER_REQUIRED")
    assert code(c.post(f"{API}/uploads/{uid}/complete", headers=H("tok-power"))) == (403, "CSRF_HEADER_REQUIRED")
    assert code(c.delete(f"{API}/uploads/{uid}", headers=H("tok-power"))) == (403, "CSRF_HEADER_REQUIRED")
    # 남의 세션은 404(조회·쓰기·완료·추가·취소), 같은 프로젝트 power라도
    assert code(c.get(f"{API}/uploads/{uid}", headers=H("tok-power2"))) == (404, "UPLOAD_NOT_FOUND")
    assert code(put(c, uid, 0, 0, b"hello", token="tok-power2")) == (404, "UPLOAD_NOT_FOUND")
    assert code(complete(c, uid, token="tok-power2")) == (404, "UPLOAD_NOT_FOUND")
    assert code(c.post(f"{API}/uploads/{uid}/files", headers=H("tok-power2", True), json={"files": [{"rel": "b.csv", "size": 1}]})) == (404, "UPLOAD_NOT_FOUND")
    assert code(c.delete(f"{API}/uploads/{uid}", headers=H("tok-power2", True))) == (404, "UPLOAD_NOT_FOUND")
    assert code(c.get(f"{API}/uploads/nope", headers=H("tok-power"))) == (404, "UPLOAD_NOT_FOUND")
    # 전역 관리자: 조회·취소 가능, 남의 세션에 쓰기는 불가
    assert c.get(f"{API}/uploads/{uid}", headers=H("tok-admin")).status_code == 200
    assert code(put(c, uid, 0, 0, b"hello", token="tok-admin")) == (404, "UPLOAD_NOT_FOUND")
    assert c.delete(f"{API}/uploads/{uid}", headers=H("tok-admin", True)).json()["state"] == "CANCELED"
    assert get(c, uid)["backup_display_path"]


def test_v_up_6_list_mine_and_admin(make_client):
    c, _ = make_client()
    sid = study(c)
    a = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"1"}, name="a").json()
    b = create(c, sid, "RADIOSS_ASSEM", {"b.csv": b"1"}, name="b", token="tok-power2").json()
    ids = lambda r: [u["upload_id"] for u in r.json()]  # noqa: E731
    assert ids(c.get(f"{API}/studies/{sid}/uploads", headers=H("tok-power"))) == [a["upload_id"]]
    assert ids(c.get(f"{API}/studies/{sid}/uploads", headers=H("tok-power"), params={"mine": "false"})) == [a["upload_id"]]  # 비관리자는 본인만
    assert sorted(ids(c.get(f"{API}/studies/{sid}/uploads", headers=H("tok-admin"), params={"mine": "false"}))) == sorted([a["upload_id"], b["upload_id"]])
    assert ids(c.get(f"{API}/studies/{sid}/uploads", headers=H("tok-power"), params={"state": "COMPLETED"})) == []
    assert c.get(f"{API}/studies/{sid}/uploads", headers=H("tok-power"), params={"state": "BAD"}).status_code == 422
    assert code(c.get(f"{API}/studies/00000000-0000-0000-0000-000000000000/uploads", headers=H("tok-power"))) == (404, "NOT_FOUND")


def test_v_up_6_concurrent_limit_429(make_client):
    c, _ = make_client()
    sid = study(c)
    u = [create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"1"}, name=f"n{i}") for i in range(2)]
    assert all(r.status_code == 201 for r in u)
    assert code(create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"1"}, name="n3")) == (429, "UPLOAD_LIMIT")
    assert create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"1"}, name="o", token="tok-power2").status_code == 201  # 사용자별
    assert c.delete(f"{API}/uploads/{u[0].json()['upload_id']}", headers=H("tok-power", True)).status_code == 200
    assert create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"1"}, name="n4").status_code == 201


# ---- V-UP-7 ---------------------------------------------------------------------------------------------


def test_v_up_7_cancel_moves_to_backup_no_delete(make_client):
    c, ctx = make_client()
    sid = study(c)
    files = {"d/a.csv": b"hello", "b.csv": b"x" * 100}
    up = create(c, sid, "RADIOSS_ASSEM", files).json()
    send(c, up, files, only={"d/a.csv"})
    put(c, up["upload_id"], 1, 0, b"x" * 50, chunk_sha=False)  # .part 진행 중
    folder = Path(up["path"])
    r = c.delete(f"{API}/uploads/{up['upload_id']}", headers=H("tok-power", True))
    out = r.json()
    assert r.status_code == 200 and out["state"] == "CANCELED" and out["path"] is None and out["backup_display_path"]
    bk = Path(ctx.settings.storage.ai_root) / "uploads" / "_backup" / "power" / folder.name
    assert not folder.exists() and (bk / "d" / "a.csv").read_bytes() == b"hello" and (bk / "b.csv.part").stat().st_size == 50
    assert code(put(c, up["upload_id"], 1, 50, b"x")) == (409, "UPLOAD_CLOSED")
    assert code(c.delete(f"{API}/uploads/{up['upload_id']}", headers=H("tok-power", True))) == (409, "UPLOAD_CLOSED")
    # 같은 이름으로 다시 만들어도 백업과 충돌하지 않는다(_2 접미사)
    up2 = create(c, sid, "RADIOSS_ASSEM", files, name="up1").json()
    assert Path(up2["path"]).exists()
    c.delete(f"{API}/uploads/{up2['upload_id']}", headers=H("tok-power", True))
    assert len(list((bk.parent).iterdir())) == 2


def test_v_up_7_stale_cleanup_admin_create_and_worker(make_client, engine):
    from physicsai_worker import housekeeping

    c, ctx = make_client(upload={"stale_hours": 72})
    sid = study(c)
    a = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"1"}, name="a").json()
    b = create(c, sid, "RADIOSS_ASSEM", {"b.csv": b"1"}, name="b").json()
    fresh = create(c, sid, "RADIOSS_ASSEM", {"c.csv": b"1"}, name="c", token="tok-power2").json()
    with engine.begin() as cn:  # 71시간 = 아직 아님, 73시간 = 낡음
        cn.execute(text("update uploads set updated_at = now() - interval '71 hours' where id=:i"), {"i": a["upload_id"]})
        cn.execute(text("update uploads set updated_at = now() - interval '73 hours' where id=:i"), {"i": b["upload_id"]})
    assert code(c.post(f"{API}/admin/uploads/cleanup-stale", headers=H("tok-power", True))) == (403, "PERMISSION_DENIED")
    r = c.post(f"{API}/admin/uploads/cleanup-stale", headers=H("tok-admin", True))
    assert r.status_code == 200 and r.json() == {"moved": [b["upload_id"]]}
    assert get(c, b["upload_id"])["state"] == "STALE" and get(c, a["upload_id"])["state"] == "OPEN"
    assert not Path(b["path"]).exists() and Path(a["path"]).exists() and get(c, b["upload_id"])["backup_display_path"]
    assert code(put(c, b["upload_id"], 0, 0, b"1")) == (409, "UPLOAD_CLOSED")
    assert c.post(f"{API}/admin/uploads/cleanup-stale", headers=H("tok-admin", True)).json() == {"moved": []}
    # 세션 생성 때마다 낡은 세션 정리(다른 사용자 것 포함) + 워커 하우스키핑
    with engine.begin() as cn:
        cn.execute(text("update uploads set updated_at = now() - interval '80 hours' where id=:i"), {"i": fresh["upload_id"]})
    assert create(c, sid, "RADIOSS_ASSEM", {"d.csv": b"1"}, name="d").status_code == 201
    assert get(c, fresh["upload_id"], token="tok-admin")["state"] == "STALE"
    with engine.begin() as cn:
        cn.execute(text("update uploads set updated_at = now() - interval '99 hours' where id=:i"), {"i": a["upload_id"]})
    assert housekeeping.purge_stale_uploads(engine, ctx.settings) == [a["upload_id"]]
    assert get(c, a["upload_id"])["state"] == "STALE"
    with engine.connect() as cn:
        ev = cn.execute(text("select user_id, detail from audit_events where action='UPLOAD_STALE'")).all()
    assert len(ev) == 3 and {e.user_id for e in ev} == {"system"} and "dir_rel" in ev[0].detail


def test_v_up_7_no_delete_calls_in_upload_modules():
    from physicsai_test_support import REPO

    pat = re.compile(r"\b(os\.remove|os\.unlink|\.unlink\(|shutil\.rmtree|os\.rmdir|\.rmdir\(|removedirs|send2trash)")
    files = [REPO / "backend" / "physicsai_core" / "uploads.py", REPO / "backend" / "physicsai_core" / "uploads_retire.py",
             REPO / "backend" / "physicsai_core" / "db" / "repositories" / "uploads.py",
             *sorted((REPO / "backend" / "physicsai_api" / "services").glob("upload*.py")),
             REPO / "backend" / "physicsai_api" / "routers" / "uploads.py"]
    assert len(files) >= 7
    for f in files:
        assert not pat.search(f.read_text(encoding="utf-8")), f


# ---- V-UP-9 ---------------------------------------------------------------------------------------------


def test_v_up_9_no_multipart_and_x_mcp_exclude():
    from physicsai_api.export_openapi import build_openapi
    from physicsai_api.mcp.route_policy import LEGACY_UNMARKED
    from physicsai_test_support import REPO

    spec = build_openapi()
    assert "multipart/form-data" not in str(spec) and "UploadFile" not in str(spec)
    ups = [(p, m, o) for p, it in spec["paths"].items() for m, o in it.items() if isinstance(o, dict) and "/uploads" in p]
    assert len(ups) == 9
    for p, m, o in ups:
        assert o["x-mcp"] == {"exclude": "웹 파일 업로드"} and o["operationId"] not in LEGACY_UNMARKED, (m, p)
    put_op = spec["paths"]["/physicsai/api/uploads/{upload_id}/files/{index}"]["put"]
    assert put_op["requestBody"]["content"] == {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}
    # 플랫폼 코드는 python-multipart를 import하지 않는다
    for f in (REPO / "backend").rglob("*.py"):
        if "tests" in f.parts:
            continue
        assert not re.search(r"^\s*(import|from)\s+(python_)?multipart", f.read_text(encoding="utf-8"), re.M), f


def test_v_up_9_api_token_gets_403(make_client, settings_dict):
    c, _ = make_client(mcp={"enabled": True})
    sid = study(c)
    plain, _tok = issue(c, scope="admin", name="x", session="tok-admin")
    up = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"1"}).json()
    for method, path, kw in (("get", "/uploads/config", {}), ("post", f"/studies/{sid}/uploads", {"json": {"purpose": "RADIOSS_ASSEM", "name": "n", "files": [{"rel": "a.csv", "size": 1}]}}),
                             ("get", f"/studies/{sid}/uploads", {}), ("get", f"/uploads/{up['upload_id']}", {}),
                             ("post", f"/uploads/{up['upload_id']}/complete", {}), ("delete", f"/uploads/{up['upload_id']}", {}),
                             ("post", "/admin/uploads/cleanup-stale", {}),
                             ("put", f"/uploads/{up['upload_id']}/files/0?offset=0", {"content": b"1", "headers": {"Content-Type": "application/octet-stream"}})):
        headers = {**T(plain), **kw.pop("headers", {})}
        r = getattr(c, method)(f"{API}{path}", headers=headers, **kw)
        assert code(r) == (403, "API_TOKEN_OPERATION_NOT_ALLOWED"), (method, path, r.text)


def test_v_up_9_logs_have_no_cookie_token_or_content(make_client, caplog):
    caplog.set_level(logging.DEBUG)
    c, _ = make_client()
    sid = study(c)
    secret = b"SECRET-CONTENT-12345"
    files = {"secretname.csv": secret + b"\n" * 10}
    up = create(c, sid, "RADIOSS_ASSEM", files).json()
    send(c, up, files)
    complete(c, up["upload_id"])
    put(c, up["upload_id"], 0, 0, b"x", chunk_sha="0" * 64)
    c.delete(f"{API}/uploads/{up['upload_id']}", headers=H("tok-power", True))
    assert "tok-power" not in caplog.text and "SECRET-CONTENT" not in caplog.text and "secretname" not in caplog.text


# ---- V-UP-10·11 -----------------------------------------------------------------------------------------


def _cfg(settings_dict, **storage_or_upload):
    from physicsai_core.config import load_config_dict

    d = {**settings_dict}
    d["storage"] = {**d["storage"], **storage_or_upload.pop("storage", {})}
    for k, v in storage_or_upload.items():
        d[k] = v
    return load_config_dict(d, environ={})


@pytest.mark.parametrize("root,ok", [
    ("uploads", True), ("in/up", True), (None, True), ("..", False), ("../x", False), ("a/../b", False), ("a b", False), ("a&b", False),
    ("_backup", False), ("_Platform/x", False), (".hid", False), ("a//b", False), ("a:b", False),
    ("a.", False), ("/etc/uploads", False), ("", False), ("inbox", False), ("inbox/sub", False),
])
def test_v_up_10_upload_root_validation(settings_dict, root, ok):
    lc = _cfg(settings_dict, storage={"upload_root": root})
    keys = [i.key for i in lc.issues]
    assert (("storage.upload_root" not in keys) is ok), (root, lc.issues)


def test_v_up_10_upload_root_absolute_overlap_and_ranges(settings_dict, tmp_path):
    ai = Path(settings_dict["storage"]["ai_root"])
    assert "storage.upload_root" not in [i.key for i in _cfg(settings_dict, storage={"upload_root": str(ai / "up2")}).issues]
    for bad in (str(ai), str(tmp_path / "elsewhere"), str(ai.parent / (ai.name + "x") / "u")):
        assert "storage.upload_root" in [i.key for i in _cfg(settings_dict, storage={"upload_root": bad}).issues], bad
    sp = tmp_path / "spdm_in_ai"
    d = {**settings_dict}
    d["storage"] = {**d["storage"], "spdm_roots": [str(ai / "uploads")]}
    from physicsai_core.config import load_config_dict

    assert "storage.upload_root" in [i.key for i in load_config_dict(d, environ={}).issues] and sp
    for k, v in (("chunk_mb", 0), ("chunk_mb", 65), ("max_files", 0), ("stale_hours", 0), ("max_concurrent_per_user", 0), ("min_free_gb", -1),
                 ("max_file_bytes", 0), ("max_upload_bytes", 10), ("extra_patterns", ["a/b"]), ("extra_patterns", [""]),
                 ("extra_patterns", ["a b"]), ("purposes", {"NOPE": {"patterns": ["*.x"]}}), ("purposes", {"DATASET_INPUT": {"patterns": ["x/y"]}})):
        up = {"max_file_bytes": 100, **({k: v})} if k == "max_upload_bytes" else {k: v}
        lc = _cfg(settings_dict, upload=up)
        assert any(i.key.startswith("upload.") for i in lc.issues), (k, v)
    for k, v in (("max_bytes", 10), ("max_images", -1), ("max_image_bytes", 1), ("max_table_rows", 0)):
        assert f"report.{k}" in [i.key for i in _cfg(settings_dict, report={k: v}).issues], k
    lc = _cfg(settings_dict, report={})
    assert lc.ok and lc.settings.report.max_bytes == 31457280 and lc.settings.report.max_table_rows == 500
    assert lc.settings.upload.max_file_bytes == 64 * GIB and lc.settings.upload.max_upload_bytes == 200 * GIB
    assert lc.settings.upload.stale_hours == 72 and lc.settings.upload.min_free_gb == 50 and lc.settings.upload.chunk_mb == 16
    assert lc.settings.upload.max_files == 20000 and lc.settings.upload.max_concurrent_per_user == 2


def test_v_up_10_example_yaml_loads_defaults():
    from physicsai_core.config.schema import Settings
    from physicsai_core.config.schema_upload import UploadCfg
    from physicsai_test_support import REPO

    import yaml

    demo = (REPO / "config" / "platform.demo.yaml").read_text(encoding="utf-8")  # {{…}} 자리표시자 템플릿 — 본문만 확인
    assert 'upload_root: "uploads"' in demo and "min_free_gb: 1" in demo
    ex = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert ex["storage"]["upload_root"] == "uploads"
    d = Settings().upload.model_dump()
    assert {k: ex["upload"][k] for k in ex["upload"]} == {k: d[k] for k in ex["upload"]}
    assert set(ex["upload"]) == set(UploadCfg.model_fields)  # 예시 yaml이 모든 키를 담는다
    assert ex["report"] == Settings().report.model_dump()


def test_v_up_10_disabled_503_and_status(make_client, settings_dict):
    c, _ = make_client(storage={**settings_dict["storage"], "upload_root": None})
    sid = study(c)
    r = create(c, sid, "RADIOSS_ASSEM", {"a.csv": b"1"})
    assert code(r) == (503, "UPLOAD_DISABLED")
    assert code(put(c, "x", 0, 0, b"1")) == (503, "UPLOAD_DISABLED")
    assert code(complete(c, "x")) == (503, "UPLOAD_DISABLED")
    cfg = c.get(f"{API}/uploads/config", headers=H("tok-power")).json()
    assert cfg["enabled"] is False and cfg["free_bytes"] is None
    assert c.get(f"{API}/status", headers=H("tok-power")).json()["upload"] == {"enabled": False, "free_bytes": None}
    assert "upload" not in [x["key"] for x in c.get(f"{API}/fs/roots", headers=H("tok-power")).json()["roots"]]


def test_v_up_10_config_and_status_enabled(make_client):
    c, ctx = make_client()
    cfg = c.get(f"{API}/uploads/config", headers=H("tok-general")).json()  # 로그인 사용자면 누구나
    assert cfg["enabled"] is True and cfg["chunk_size"] == MB and cfg["max_file_bytes"] == 64 * GIB and cfg["max_upload_bytes"] == 200 * GIB
    assert cfg["max_files"] == 20000 and cfg["max_concurrent_per_user"] == 2 and isinstance(cfg["free_bytes"], int)
    assert set(cfg["purposes"]) == {"CAD_FILE", "RADIOSS_ASSEM", "RESULT_FOLDER", "CURATION_INPUT", "DATASET_INPUT", "MODEL_FOLDER",
                                    "PARAM_SET", "PREDICT_INPUT", "DISCOVER", "FEM_ASSEMBLY"}
    assert cfg["purposes"]["CAD_FILE"] == {"patterns": ["*.prt"], "mode": "file",
                                           "engine_patterns": {"native": ["*.step", "*.stp"], "altair": ["*.prt"]}}
    assert cfg["purposes"]["PREDICT_INPUT"]["mode"] == "dir_or_file" and cfg["purposes"]["DATASET_INPUT"]["mode"] == "dir"
    assert "*.pscfg" not in cfg["purposes"]["MODEL_FOLDER"]["patterns"] and cfg["purposes"]["DATASET_INPUT"]["patterns"][0] == "*.h3d"
    assert cfg["purposes"]["RESULT_FOLDER"]["patterns"][:4] == ["*.h3d", "*t01", "*_0000.out", "*_0001.out"]
    st = c.get(f"{API}/status", headers=H("tok-power")).json()["upload"]
    assert st["enabled"] is True and isinstance(st["free_bytes"], int)
    assert c.get(f"{API}/uploads/config").status_code == 401


def test_v_up_10_env_check_upload_item(make_client, settings_dict, monkeypatch):
    c, ctx = make_client(upload={"min_free_gb": 0})
    r = c.post(f"{API}/admin/env-checks", headers=H("tok-admin", True))
    assert r.status_code == 202
    item = {i["key"]: i for i in r.json()["items"]}["upload.root"]
    assert item["status"] == "OK" and item["category"] == "STORAGE" and item["source"] == "API" and "여유" in item["message"]
    root = Path(ctx.settings.storage.ai_root) / "uploads"
    assert root.is_dir() and [p.name for p in root.iterdir()] == []  # 시험 파일은 tempfile 자동 삭제
    from physicsai_api.services import env_checks
    from physicsai_core import uploads as U

    _c2, ctx2 = make_client(upload={"min_free_gb": 5})
    monkeypatch.setattr(U, "free_bytes", lambda _p: GIB)
    item = env_checks._upload_item(ctx2)  # 여유 1 GiB < min_free_gb 5 → WARN
    assert item["status"] == "WARN" and item["detail"]["min_free_gb"] == 5


def test_v_up_10_env_check_skip_when_disabled(make_client, settings_dict):
    c, ctx = make_client(storage={**settings_dict["storage"], "upload_root": None})
    from physicsai_api.services import env_checks

    item = env_checks._upload_item(ctx)
    assert item["status"] == "SKIP" and item["key"] == "upload.root"


def test_v_up_10_study_folder_cannot_take_upload_root_name(make_client):
    c, _ = make_client()
    r = c.post(f"{API}/studies", headers=H("tok-power", True), json={"project_id": "p-1", "folder_name": "Uploads", "title": "t"})
    assert code(r) == (409, "FOLDER_RESERVED")
    assert c.post(f"{API}/studies", headers=H("tok-power", True), json={"project_id": "p-1", "folder_name": "S9", "title": "t"}).status_code == 201


def test_v_up_11_fs_roots_and_list_hide_backup_and_part(make_client):
    c, ctx = make_client()
    sid = study(c)
    files = {"a.rad": b"1" * 5, "b.inc": b"2" * 10}
    up = create(c, sid, "RADIOSS_ASSEM", files).json()
    put(c, up["upload_id"], 1, 0, b"2" * 5, chunk_sha=False)
    send(c, up, files, only={"a.rad"})
    root = Path(ctx.settings.storage.ai_root) / "uploads"
    listing = lambda p: [e["name"] for e in c.get(f"{API}/fs/list", headers=H("tok-power"), params={"path": str(p)}).json()["entries"]]  # noqa: E731
    assert listing(up["path"]) == ["a.rad"]
    c.delete(f"{API}/uploads/{up['upload_id']}", headers=H("tok-power", True))
    assert (root / "_backup").is_dir() and listing(root) == ["power"]
    assert c.get(f"{API}/fs/list", headers=H("tok-power"), params={"path": str(root / "_backup")}).status_code == 422
    roots = {x["key"]: x["path"] for x in c.get(f"{API}/fs/roots", headers=H("tok-power")).json()["roots"]}
    assert roots["upload"] == str(root)
