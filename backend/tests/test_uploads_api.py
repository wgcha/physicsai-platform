"""upload-report.md V-UP-1~4·8: 정상 흐름(complete → 기존 paths/inspect·작업 생성), 청크 순서·이어 올리기·sha256, 이름·패턴 거부, complete 재시도."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text

from physicsai_test_support import API, H
from up_helpers import MB, blob, code, complete, create, get, make_client, put, send, sha, study  # noqa: F401


def _audit(engine, action):
    with engine.connect() as c:
        return c.execute(text("select detail from audit_events where action=:a order by occurred_at"), {"a": action}).scalars().all()


def test_v_up_1_model_folder_flow_then_inspect_and_job(make_client, engine, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    c, ctx = make_client()
    ai = Path(ctx.settings.storage.ai_root)
    sid = study(c)
    files = {"cushion.psmdl": blob(2 * MB + 500, "m"), "train.log": b"epoch= 1/ 2 loss=1.0e+00\n", "info.json": b"{}\n"}
    r = create(c, sid, "MODEL_FOLDER", files)
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["state"] == "OPEN" and up["purpose"] == "MODEL_FOLDER" and up["chunk_size"] == MB and up["created_by"] == "power"
    assert up["total_bytes"] == sum(map(len, files.values())) and up["received_bytes"] == 0
    d = Path(up["path"])
    assert d.is_dir() and d.parent.parent == ai / "uploads" and d.parent.name == "power" and "_up1" in d.name
    send(c, up, files)
    cp = complete(c, up["upload_id"])
    assert cp.status_code == 200, cp.text
    out = cp.json()
    assert out["state"] == "COMPLETED" and out["path"] == up["path"] and out["inspect"]["ok"] is True and out["problems"] == []
    assert out["inspect"]["summary"]["psmdl"] == ["cushion.psmdl"] and out["inspect"]["summary"]["pscfg"] == []
    assert (d / "cushion.psmdl").read_bytes() == files["cushion.psmdl"]
    assert not list(d.rglob("*.part"))
    got = get(c, up["upload_id"])
    assert got["state"] == "COMPLETED" and got["received_bytes"] == got["total_bytes"] and all(f["done"] for f in got["files"])
    assert got["files"][0]["sha256"] == sha(files["cushion.psmdl"]) and got["completed_at"]
    # 같은 complete 재호출은 같은 결과(멱등), 이후 쓰기·취소는 409 UPLOAD_CLOSED
    assert complete(c, up["upload_id"]).json()["state"] == "COMPLETED"
    assert code(put(c, up["upload_id"], 0, 0, b"x")) == (409, "UPLOAD_CLOSED")
    assert code(c.delete(f"{API}/uploads/{up['upload_id']}", headers=H("tok-power", True))) == (409, "UPLOAD_CLOSED")
    # 기존 흐름: complete의 path가 paths/inspect·작업 생성에서 그대로 통과(V-UP-1)
    model_dir = out["path"]
    ins = c.post(f"{API}/studies/{sid}/paths/inspect", headers=H("tok-power", True),
                 json={"purpose": "MODEL_FOLDER", "path": model_dir})
    assert ins.status_code == 200 and ins.json()["ok"] is True, ins.text
    job = c.post(f"{API}/studies/{sid}/jobs", headers=H("tok-power", True),
                 json={"job_type": "MODEL_REGISTER", "params": {"model_path": model_dir}})
    assert job.status_code == 201, job.text
    # 감사: id·수치·폴더 상대경로만(파일 이름 목록·토큰 없음)
    ev = _audit(engine, "UPLOAD_COMPLETE")
    assert ev and ev[0]["files"] == 3 and ev[0]["bytes"] == up["total_bytes"] and ev[0]["dir_rel"].startswith("uploads/power/")
    assert "cushion" not in str(_audit(engine, "UPLOAD_CREATE"))
    with engine.connect() as cn:
        row = cn.execute(text("select dir_rel, inspect::text as ins from uploads")).one()
    assert not row.dir_rel.startswith("/") and str(ai) not in row.ins and "normalized_path" not in row.ins
    # 로그에 세션 토큰·파일 내용 없음
    assert "tok-power" not in caplog.text and "epoch=" not in caplog.text


def test_v_up_1_roots_list_hide_part(make_client):
    c, ctx = make_client()
    sid = study(c)
    assert "upload" not in [x["key"] for x in c.get(f"{API}/fs/roots", headers=H("tok-power")).json()["roots"]]  # 폴더 없으면 생략
    files = {"a.rad": b"x\n" * 10, "b.inc": blob(2 * MB, "b")}
    up = create(c, sid, "RADIOSS_ASSEM", files).json()
    roots = {x["key"]: x for x in c.get(f"{API}/fs/roots", headers=H("tok-power")).json()["roots"]}
    assert roots["upload"]["label"] == "내가 올린 파일" and roots["upload"]["path"] == os.path.normpath(str(Path(ctx.settings.storage.ai_root) / "uploads"))
    send(c, up, files, only={"a.rad"})
    put(c, up["upload_id"], 1, 0, files["b.inc"][:MB])  # b.inc.part 진행 중
    assert (Path(up["path"]) / "b.inc.part").exists()
    names = [e["name"] for e in c.get(f"{API}/fs/list", headers=H("tok-power"), params={"path": up["path"]}).json()["entries"]]
    assert names == ["a.rad"]  # .part 숨김
    r = c.delete(f"{API}/uploads/{up['upload_id']}", headers=H("tok-power", True))
    assert r.status_code == 200
    top = [e["name"] for e in c.get(f"{API}/fs/list", headers=H("tok-power"), params={"path": str(Path(ctx.settings.storage.ai_root) / "uploads")}).json()["entries"]]
    assert "_backup" not in top  # _backup 숨김


def test_v_up_1_cad_file_native_and_altair(make_client):
    c, _ = make_client()
    sid = study(c)
    step = {"part.STEP": blob(3000, "s")}
    up = create(c, sid, "CAD_FILE", step, engine="native").json()
    send(c, up, step)
    out = complete(c, up["upload_id"]).json()
    assert out["state"] == "COMPLETED" and out["path"].endswith("part.STEP") and os.path.isfile(out["path"])  # 파일 경로
    assert out["inspect"]["ok"] is True and out["inspect"]["summary"]["extension_ok"] is True
    # altair(생략)는 .prt만, STEP은 UPLOAD_EXT_NOT_ALLOWED
    assert code(create(c, sid, "CAD_FILE", step, name="up2")) == (422, "UPLOAD_EXT_NOT_ALLOWED")
    prt = {"part.prt": blob(100, "p")}
    up2 = create(c, sid, "CAD_FILE", prt, name="up3").json()
    send(c, up2, prt)
    assert complete(c, up2["upload_id"]).json()["inspect"]["ok"] is True
    # 파일 1개만: 2개·폴더 성분은 UPLOAD_SHAPE_INVALID
    assert code(create(c, sid, "CAD_FILE", {"a.prt": b"1", "b.prt": b"2"}, name="up4")) == (422, "UPLOAD_SHAPE_INVALID")
    assert code(create(c, sid, "CAD_FILE", {"d/a.prt": b"1"}, name="up5")) == (422, "UPLOAD_SHAPE_INVALID")


def test_v_up_1_discover_and_predict_input_shapes(make_client):
    c, _ = make_client()
    sid = study(c)
    files = {"proj/a.tpl": b"t\n", "proj/model.stp": blob(50), "proj/run.rad": b"r\n"}
    up = create(c, sid, "DISCOVER", files).json()
    send(c, up, files)
    out = complete(c, up["upload_id"]).json()  # 형태 검사만 — inspect 없음
    assert out["state"] == "COMPLETED" and out["inspect"] is None and out["problems"] == [] and os.path.isdir(out["path"])
    one = {"starter_0000.rad": b"x\n"}
    up2 = create(c, sid, "PREDICT_INPUT", one, name="p1").json()
    assert up2["path"].endswith("starter_0000.rad")  # 파일 1개면 그 파일
    up3 = create(c, sid, "PREDICT_INPUT", {"d/a.rad": b"x\n", "d/b.inc": b"y\n"}, name="p2").json()
    assert os.path.isdir(up3["path"])


def test_zero_byte_files_done_at_create(make_client):
    c, _ = make_client()
    sid = study(c)
    up = create(c, sid, "RADIOSS_ASSEM", {"e.csv": b"", "n.csv": b"abc"}).json()
    assert up["files"][0]["done"] and up["files"][0]["sha256"] == sha(b"") and not up["files"][1]["done"]
    assert code(put(c, up["upload_id"], 0, 0, b"")) == (409, "UPLOAD_FILE_DONE")


# ---- V-UP-2 ---------------------------------------------------------------------------------------------


def test_v_up_2_offset_resume_sha_overflow_media(make_client):
    c, ctx = make_client()
    sid = study(c)
    data = blob(2 * MB + 10, "d")
    up = create(c, sid, "RADIOSS_ASSEM", {"big.csv": data}).json()
    uid = up["upload_id"]
    # 순서 위반: 아직 0바이트인데 offset 5
    r = put(c, uid, 0, 5, data[:10])
    assert code(r) == (409, "UPLOAD_OFFSET_MISMATCH") and r.json()["detail"]["received"] == 0
    r = put(c, uid, 0, 0, data[:MB])
    assert r.status_code == 200 and r.json() == {"index": 0, "received": MB, "done": False, "sha256": None}
    # 같은 청크 재전송(offset 0)은 409 + received → 클라이언트가 received로 맞춘다
    r = put(c, uid, 0, 0, data[:MB])
    assert code(r) == (409, "UPLOAD_OFFSET_MISMATCH") and r.json()["detail"]["received"] == MB
    # 새로 고침 후 이어 올리기: GET의 received
    assert get(c, uid)["files"][0]["received"] == MB
    # 청크 sha256 불일치 422, 쓰기 0
    part = Path(up["path"]) / "big.csv.part"
    r = put(c, uid, 0, MB, data[MB:2 * MB], chunk_sha="0" * 64)
    assert code(r) == (422, "CHUNK_SHA256_MISMATCH") and part.stat().st_size == MB
    # 청크 크기·선언 크기 초과·잘못된 Content-Type·없는 파일 번호
    assert code(put(c, uid, 0, MB, data[:MB + 1], chunk_sha=False)) == (413, "CHUNK_TOO_LARGE")
    small = create(c, sid, "RADIOSS_ASSEM", {"s.csv": b"12345"}, name="small").json()
    assert code(put(c, small["upload_id"], 0, 0, b"123456", chunk_sha=False)) == (422, "CHUNK_OVERFLOW")
    assert code(put(c, uid, 0, MB, b"x", ctype="application/json")) == (415, "UNSUPPORTED_MEDIA_TYPE")
    assert code(put(c, uid, 0, MB, b"x", ctype="multipart/form-data; boundary=x")) == (415, "UNSUPPORTED_MEDIA_TYPE")
    assert code(put(c, uid, 7, 0, b"x")) == (404, "UPLOAD_FILE_NOT_FOUND")
    assert part.stat().st_size == MB
    # 이어 올려 완료 — .part → 최종 이름, 전체 sha256 기록
    r = put(c, uid, 0, MB, data[MB:2 * MB]) and put(c, uid, 0, 2 * MB, data[2 * MB:])
    assert r.json()["done"] is True and r.json()["sha256"] == sha(data)
    assert not part.exists() and (Path(up["path"]) / "big.csv").read_bytes() == data
    assert code(put(c, uid, 0, 0, b"x")) == (409, "UPLOAD_FILE_DONE")


def test_v_up_2_file_sha_mismatch_moves_part_to_backup(make_client):
    c, ctx = make_client()
    sid = study(c)
    data = blob(1500, "q")
    body = {"purpose": "RADIOSS_ASSEM", "name": "bad", "files": [{"rel": "x.csv", "size": len(data), "sha256": "a" * 64}]}
    up = c.post(f"{API}/studies/{sid}/uploads", headers=H("tok-power", True), json=body).json()
    r = put(c, up["upload_id"], 0, 0, data)
    d = r.json()["detail"]
    assert (r.status_code, d["code"]) == (422, "SHA256_MISMATCH") and d["received"] == 0 and d["actual"] == sha(data)
    folder = Path(up["path"])
    assert not (folder / "x.csv.part").exists() and not (folder / "x.csv").exists()
    moved = list((Path(ctx.settings.storage.ai_root) / "uploads" / "_backup" / "power").glob("*mismatch"))
    assert len(moved) == 1 and moved[0].read_bytes() == data  # 지우지 않고 _backup으로
    assert get(c, up["upload_id"])["files"][0]["received"] == 0


# ---- V-UP-3 ---------------------------------------------------------------------------------------------

BAD_RELS = ["../x.rad", "/abs/x.rad", "a\\b.rad", "C:/x.rad", "C:x.rad", "CON.rad", "a/nul.csv", "a/AUX", "x.rad.", "x.rad ", "a b.rad",
            "a&b.rad", "a(b).rad", "a;b.rad", "a,b.rad", "a=b.rad", "a'b.rad", "a\x01b.rad", "a|b.rad", "a%b.rad", "a!b.rad", 'a"b.rad',
            "a*b.rad", "a?b.rad", "a:b.rad", "_backup/x.rad", "_Backup/x.rad", "_platform/x.rad", ".hidden/x.rad", "a//b.rad",
            "a/./b.rad", "a/../b.rad", "./a.rad", "a/", "", "d/" + "n" * 256 + ".rad", "x" * 401]


@pytest.mark.parametrize("rel", BAD_RELS)
def test_v_up_3_name_attacks_rejected(make_client, rel):
    c, ctx = make_client()
    sid = study(c)
    r = c.post(f"{API}/studies/{sid}/uploads", headers=H("tok-power", True),
               json={"purpose": "RADIOSS_ASSEM", "name": "n", "files": [{"rel": rel, "size": 1}]})
    assert r.status_code == 422, (rel, r.text)
    assert r.json()["detail"]["code"] in ("UPLOAD_NAME_INVALID", "INVALID_PARAMS", "UPLOAD_EXT_NOT_ALLOWED"), r.text
    root = Path(ctx.settings.storage.ai_root) / "uploads"
    assert not root.exists() or not [p for p in root.rglob("*") if p.is_file()]  # 아무것도 쓰이지 않음


def test_v_up_3_path_too_long_and_session_name(make_client):
    c, ctx = make_client()
    sid = study(c)
    rel = "a" * 200 + "/" + "b" * 150 + "/x.rad"  # rel ≤ 400, 폴더 경로를 더하면 MAX_PATH_LEN(400) 초과
    r = create(c, sid, "RADIOSS_ASSEM", {rel: b"x"})
    assert code(r) == (422, "UPLOAD_NAME_INVALID") and "너무 깁니다" in r.json()["detail"]["message"]
    for bad in ("a/b", "a\\b", "..", "x..y", "CON", "a\x00b"):
        r = c.post(f"{API}/studies/{sid}/uploads", headers=H("tok-power", True),
                   json={"purpose": "RADIOSS_ASSEM", "name": bad, "files": [{"rel": "x.rad", "size": 1}]})
        assert r.status_code == 422, bad
    up = c.post(f"{API}/studies/{sid}/uploads", headers=H("tok-power", True),
                json={"purpose": "RADIOSS_ASSEM", "name": "내 파일: a b<c>", "files": [{"rel": "x.rad", "size": 1}]}).json()
    assert Path(up["path"]).name.endswith("_내_파일_a_b_c") and " " not in up["path"]  # 폴더 이름은 정규화(경로 규칙 통과)


def test_v_up_3_symlink_hardlink_overwrite_blocked(make_client, tmp_path):
    c, ctx = make_client()
    sid = study(c)
    files = {"sub/a.csv": b"hello", "b.csv": b"world", "c.csv": b"cc"}
    up = create(c, sid, "RADIOSS_ASSEM", files, declare_sha=False).json()
    uid, d = up["upload_id"], Path(up["path"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"KEEP")
    # 상위 성분을 링크로 바꿈 → PATH_UNSAFE, 밖에 쓰기 0
    os.rename(d / "sub", d / "sub_real")
    os.symlink(outside, d / "sub", target_is_directory=True)
    assert code(put(c, uid, 0, 0, b"hello")) == (422, "PATH_UNSAFE")
    assert sorted(os.listdir(outside)) == ["keep.txt"]
    # .part가 밖 파일의 하드 링크 → PATH_UNSAFE, 밖 파일 변경 0
    os.link(outside / "keep.txt", d / "b.csv.part")
    assert code(put(c, uid, 1, 4, b"world")) == (422, "PATH_UNSAFE")
    assert (outside / "keep.txt").read_bytes() == b"KEEP"
    # 최종 이름에 이미 파일 → 덮어쓰기 금지 409
    (d / "c.csv").write_bytes(b"other")
    assert code(put(c, uid, 2, 0, b"cc")) == (409, "UPLOAD_FILE_EXISTS")
    assert (d / "c.csv").read_bytes() == b"other"
    # 최종 이름이 링크 → PATH_UNSAFE
    os.rename(d / "c.csv", d / "c_old")
    os.symlink(outside / "keep.txt", d / "c.csv")
    assert code(put(c, uid, 2, 0, b"cc")) == (422, "PATH_UNSAFE")
    assert (outside / "keep.txt").read_bytes() == b"KEEP"


def test_v_up_3_spdm_protected_root_double_defense(make_client):
    from physicsai_core.paths import register_protected_roots

    c, ctx = make_client()
    sid = study(c)
    register_protected_roots([str(Path(ctx.settings.storage.ai_root) / "uploads")])  # 설정 검사를 우회한 가정
    r = create(c, sid, "RADIOSS_ASSEM", {"a.rad": b"x"})
    assert code(r) == (422, "PATH_UNSAFE")


# ---- V-UP-4 ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("purpose,rel,expect", [
    ("MODEL_FOLDER", "settings.pscfg", "pscfg"), ("MODEL_FOLDER", "SETTINGS.PSCFG", "pscfg"), ("RADIOSS_ASSEM", "x.psdata", "항상 거부"),
    ("RADIOSS_ASSEM", "run.exe", "항상 거부"), ("RADIOSS_ASSEM", "a.dll", "항상 거부"), ("RADIOSS_ASSEM", "a.PY", "항상 거부"),
    ("RADIOSS_ASSEM", "a.ps1", "항상 거부"), ("RADIOSS_ASSEM", "a.bat", "항상 거부"), ("RADIOSS_ASSEM", "a.js", "항상 거부"),
    ("RADIOSS_ASSEM", "a.lnk", "항상 거부"), ("RADIOSS_ASSEM", "a.rad.part", "항상 거부"), ("DATASET_INPUT", "a.msi", "항상 거부"),
    ("RADIOSS_ASSEM", "a.bin", "허용되지 않는"), ("DATASET_INPUT", "a.rad", "허용되지 않는"), ("RESULT_FOLDER", "a.A001", "허용되지 않는"),
    ("MODEL_FOLDER", "a.h3d", "허용되지 않는"),
])
def test_v_up_4_denied_and_pattern(make_client, purpose, rel, expect):
    c, _ = make_client()
    sid = study(c)
    r = create(c, sid, purpose, {rel: b"x"})
    assert code(r) == (422, "UPLOAD_EXT_NOT_ALLOWED") and expect in r.json()["detail"]["message"], r.text
    if "pscfg" in expect:
        assert "pscfg(pickle)는 올릴 수 없습니다 — 모델은 psmdl만으로 등록됩니다" in r.json()["detail"]["message"]


def test_v_up_4_purpose_invalid(make_client):
    c, _ = make_client()
    sid = study(c)
    for p in ("SPDM_IMPORT", "FOO"):
        assert code(create(c, sid, p, {"a.rad": b"x"})) == (422, "UPLOAD_PURPOSE_INVALID")


def test_v_up_4_allowed_patterns_case_insensitive(make_client):
    c, _ = make_client()
    sid = study(c)
    ok = {"A.RAD": b"1", "d/x.INC": b"2", "run1_T01": b"3"}
    assert create(c, sid, "RESULT_FOLDER", {"r/a.H3D": b"1", "r/run_0000.out": b"2", "r/info.JSON": b"3", "r/x_T01": b"4"}).status_code == 201
    assert create(c, sid, "RADIOSS_ASSEM", {k: v for k, v in ok.items() if "T01" not in k}, name="u2").status_code == 201


def test_v_up_4_config_cannot_release_always_denied(make_client):
    c, ctx = make_client(upload={"extra_patterns": ["*.pscfg", "*.bin", "*.EXE"],
                                 "purposes": {"MODEL_FOLDER": {"patterns": ["*.pscfg", "*.psmdl"]}}})
    keys = {w.key for w in ctx.config.warnings}
    assert {"upload.extra_patterns", "upload.purposes.MODEL_FOLDER.patterns"} <= keys  # 경고 후 무시
    sid = study(c)
    assert create(c, sid, "RADIOSS_ASSEM", {"x.bin": b"1"}).status_code == 201  # extra 패턴은 적용
    for purpose, rel in (("RADIOSS_ASSEM", "x.pscfg"), ("MODEL_FOLDER", "m.pscfg"), ("RADIOSS_ASSEM", "x.exe")):
        assert code(create(c, sid, purpose, {rel: b"1"}, name="z")) == (422, "UPLOAD_EXT_NOT_ALLOWED")
    # purposes 덮어쓰기: MODEL_FOLDER는 *.psmdl만 → *.log 거부
    assert code(create(c, sid, "MODEL_FOLDER", {"t.log": b"1"}, name="z2")) == (422, "UPLOAD_EXT_NOT_ALLOWED")
    cfg = c.get(f"{API}/uploads/config", headers=H("tok-power")).json()
    assert cfg["purposes"]["MODEL_FOLDER"]["patterns"] == ["*.psmdl", "*.bin"]
    assert "*.pscfg" in cfg["always_denied"] and "*.part" in cfg["always_denied"]


# ---- V-UP-8 ---------------------------------------------------------------------------------------------


def test_v_up_8_inspect_failure_keeps_open_then_add_files(make_client):
    c, _ = make_client()
    sid = study(c)
    first = {"info.json": b"{}"}
    up = create(c, sid, "MODEL_FOLDER", first).json()
    uid = up["upload_id"]
    r = complete(c, uid)
    assert code(r) == (409, "UPLOAD_INCOMPLETE") and r.json()["detail"]["pending"] == ["info.json"]
    send(c, up, first)
    out = complete(c, uid).json()  # psmdl 없음 → inspect ok=false, OPEN 유지
    assert out["state"] == "OPEN" and out["inspect"]["ok"] is False and [p["code"] for p in out["problems"]] == ["PSMDL_COUNT"]
    assert get(c, uid)["state"] == "OPEN" and get(c, uid)["inspect"]["ok"] is False
    # 같은 이름 추가는 409(대소문자 무시), 새 파일은 index 뒤에 붙음
    r = c.post(f"{API}/uploads/{uid}/files", headers=H("tok-power", True), json={"files": [{"rel": "INFO.json", "size": 1}]})
    assert code(r) == (409, "UPLOAD_FILE_DUPLICATE")
    more = {"a.psmdl": blob(MB + 7, "p")}
    r = c.post(f"{API}/uploads/{uid}/files", headers=H("tok-power", True),
               json={"files": [{"rel": "a.psmdl", "size": len(more["a.psmdl"])}]})
    assert r.status_code == 200 and [f["index"] for f in r.json()["files"]] == [0, 1] and r.json()["inspect"] is None
    assert code(c.post(f"{API}/uploads/{uid}/files", headers=H("tok-power", True),
                       json={"files": [{"rel": "b.pscfg", "size": 1}]})) == (422, "UPLOAD_EXT_NOT_ALLOWED")
    send(c, get(c, uid), more)
    out = complete(c, uid).json()
    assert out["state"] == "COMPLETED" and out["inspect"]["ok"] is True
    assert code(c.post(f"{API}/uploads/{uid}/files", headers=H("tok-power", True),
                       json={"files": [{"rel": "c.json", "size": 1}]})) == (409, "UPLOAD_CLOSED")


def test_add_files_keeps_cad_shape(make_client):
    c, _ = make_client()
    sid = study(c)
    up = create(c, sid, "CAD_FILE", {"a.prt": b"1"}).json()
    r = c.post(f"{API}/uploads/{up['upload_id']}/files", headers=H("tok-power", True), json={"files": [{"rel": "b.prt", "size": 1}]})
    assert code(r) == (422, "UPLOAD_SHAPE_INVALID")


def test_result_folder_inspect_runs_without_doe(make_client):
    c, _ = make_client()
    sid = study(c)
    files = {"results/run__00001/out_0000.out": b"1" * 20, "results/run__00001/a.csv": b"2" * 5}
    up = create(c, sid, "RESULT_FOLDER", files).json()
    send(c, up, files)
    out = complete(c, up["upload_id"]).json()
    assert out["inspect"]["summary"]["doe_id"] is None and out["state"] in ("COMPLETED", "OPEN")
