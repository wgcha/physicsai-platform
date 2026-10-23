"""v0.2.10 결과 3D 컨투어 현장 보정(contour3d-field.md C3F) — 워커·API 흐름(가짜 hw): 추출 설정(COMPS·DISP_MAX_NODES), 쿠션 입력 comps 비움,
캐시 키(상한·추출 TCL 해시 — v0.2.9 키 비적중), 결과 FAIL 시 extract 보존, 대체 사유(`reason`·`retryable`), 새 artifact kind·내려받기 상한·
`no-transform`. 변환기(numpy 재작성, schema 2)의 DISP·COMPS 경고는 가짜 hw 모드 시험이 본다."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path


from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
VALUES = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}


def _env(predict_env, *, cushion: bool = False, display: dict | None = None, folder: str = "pred", **c3):
    env = predict_env(folder=folder, extra={"contour3d": {"enabled": True, "max_frames": 3, **c3}})
    ps = env.param_set()
    if display:
        r = env.c.put(f"{API}/param-sets/{ps['id']}/display", headers=PW, json={"display": display})
        assert r.status_code == 200, r.text
    if cushion:
        env.to_mesh_only(ps["id"])
    j = env.submit("PREDICT", VALUES)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    return env, j["id"]


def _post(env, jid, expect=(200, 202), **body):
    r = env.c.post(f"{API}/contour3d", headers=PW, json={"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}, **body})
    assert r.status_code in ((expect,) if isinstance(expect, int) else expect), r.text
    return r.json()


def _settings_of_last_extract(fake_record) -> dict:
    return [x for x in read_record(fake_record) if x["tool"] == "hw_contour3d"][-1]["settings"]


def _manifest(env, g) -> dict:
    return env.c.get(f"{API}/artifacts/{g['manifest_artifact_id']}/content", headers=P).json()


def test_v_c3f_2_comps_and_disp_max_nodes_reach_extract_settings(predict_env, fake_record):
    """V-C3F-2·13: 조립 결과는 표시 설정 comps를 COMPS로, disp_max_nodes를 DISP_MAX_NODES로 넘긴다. 쿠션 입력 예측은 COMPS가 늘 비어 있다."""
    env, jid = _env(predict_env, display={"comps": ["부품B", "A", "A"], "unit": "MPa"}, disp_max_nodes=1234)
    c = _post(env, jid, expect=202)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(c["job_id"])
    st = _settings_of_last_extract(fake_record)
    assert st["COMPS"] == ["A", "부품B"] and st["DISP_MAX_NODES"] == "1234" and st["INCLUDE_DISP"] == "1"
    g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert g["display"]["comps"] == ["A", "부품B"] and g["display"]["unit"] == "MPa" and g["display"]["comps_applicable"] is True
    # 쿠션 입력 예측: 같은 표시 설정이어도 comps를 적용하지 않는다(쿠션 하나뿐 — C3F-13)
    envc, jidc = _env(predict_env, cushion=True, display={"comps": ["A"]}, folder="cush")
    cc = _post(envc, jidc, expect=202)
    assert envc.w.run_once_slot() == "SUCCEEDED", envc.job(cc["job_id"])
    assert _settings_of_last_extract(fake_record)["COMPS"] == []
    gc = envc.c.get(f"{API}/contour3d/{cc['id']}", headers=P).json()
    assert gc["display"]["comps"] == [] and gc["display"]["comps_applicable"] is False


def test_v_c3f_5_cache_key_includes_limits_tcl_and_old_keys_miss(predict_env, tmp_path):
    """V-C3F-5: v0.2.9 키의 DONE+FAIL 행이 있어도 새 키로 새 작업(202), 같은 설정으로 다시 열면 적중. 추출 TCL을 고치면 새 키(C3F-11)."""
    tcl = tmp_path / "tcl" / "contour_extract.tcl"
    tcl.parent.mkdir()
    tcl.write_text((Path(__file__).resolve().parents[3] / "resources" / "hyperview" / "contour_extract.tcl").read_text(encoding="utf-8"),
                   encoding="utf-8")
    env = predict_env(resources={"contour_extract_tcl": str(tcl)}, extra={"contour3d": {"enabled": True, "max_frames": 3}})
    env.param_set()
    j = env.submit("PREDICT", VALUES)
    assert env.w.run_once_slot() == "SUCCEEDED"
    jid = j["id"]
    h3d = env.sroot / env.job(jid)["result"]["pred_h3d_rel"]
    st = h3d.stat()
    old_doc = {"source_kind": "PREDICT_H3D", "source_id": f"job:{jid}", "h3d_size": st.st_size, "h3d_mtime_ns": st.st_mtime_ns,
               "display": {"field": env.lc.settings.capture.default_field, "dcomp": "", "avgmode": ""},
               "max_frames": 3, "include_disp": True, "converter_version": 1}
    old_key = hashlib.sha256(json.dumps(old_doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    env.sql("insert into contour3d_cache(id, study_id, cache_key, created_by, status, source_kind, source_ref, result_status, code)"
            " values (:i,:s,:k,'u-power','DONE','PREDICT_H3D','{}','FAIL','CONTOUR3D_TOO_LARGE')", i=str(uuid.uuid4()), s=env.sid, k=old_key)
    first = _post(env, jid, expect=202)  # 예전 FAIL 행은 적중하지 않는다
    assert first["status"] == "QUEUED" and first["cache_hit"] is False
    assert _post(env, jid, expect=202)["id"] == first["id"]  # 진행 중 공유
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(first["job_id"])
    hit = _post(env, jid, expect=200)
    assert hit["cache_hit"] is True and hit["id"] == first["id"]  # 같은 설정 = 적중
    tcl.write_text(tcl.read_text(encoding="utf-8") + "\n# 현장 수정\n", encoding="utf-8")
    assert _post(env, jid, expect=202)["id"] != first["id"]  # 추출 TCL 해시가 키에 들어 있다
    assert env.w.run_once_slot() == "SUCCEEDED"
    # 상한을 바꾼 설정(다른 앱 인스턴스 = 같은 DB)도 새 키
    env2 = predict_env(folder="p2", resources={"contour_extract_tcl": str(tcl)},
                       extra={"contour3d": {"enabled": True, "max_frames": 3, "max_nodes": 1999999}})
    again = _post(env2, jid, expect=202)
    assert again["id"] not in (first["id"],) and again["status"] == "QUEUED"


def test_v_c3f_13_fail_keeps_extract_settings_result_and_tcl_but_no_csv(predict_env, monkeypatch):
    """C3F-15: 결과 FAIL이면 extract/에서 CSV만 지우고 설정·결과·TCL을 남긴다. OK이면 폴더를 지운다(기존 규칙)."""
    env, jid = _env(predict_env)
    monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", "nan")
    c = _post(env, jid, expect=202)
    assert env.w.run_once_slot() == "SUCCEEDED"
    g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert g["result_status"] == "FAIL"
    dirs = list((env.sroot / "_cache" / "contour3d").rglob("extract"))
    assert len(dirs) == 1
    names = sorted(p.name for p in dirs[0].iterdir())
    assert names == ["contour_extract.tcl", "extract_result.txt", "extract_settings.tcl"], names
    monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", "ok")
    ok = _post(env, jid, expect=202, display={"field": "Other"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(ok["job_id"])
    assert len(list((env.sroot / "_cache" / "contour3d").rglob("extract"))) == 1  # OK 결과의 extract는 지워졌다(FAIL 것만 남음)


def test_v_c3f_unit_from_tcl_is_sanitized_and_display_unit_is_in_key(predict_env, monkeypatch):
    """C3F-14: 오류 문구가 단위 자리에 들어와도 버린다(parse_result). 표시 설정 unit은 키에 들어가 단위를 바꾸면 새 결과."""
    monkeypatch.setenv("FAKE_CONTOUR3D_UNIT", 'Invalid command syntax: "result scalar unit"')
    env, jid = _env(predict_env)
    c = _post(env, jid, expect=202)
    assert env.w.run_once_slot() == "SUCCEEDED"
    g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert g["status"] == "DONE"
    man = _manifest(env, g)
    assert man["unit"] == ""  # 오류 문구는 단위로 쓰이지 않는다
    other = _post(env, jid, expect=202, display={"unit": "MPa"})
    assert other["id"] != c["id"] and other["display"]["unit"] == "MPa"
    r = env.c.post(f"{API}/contour3d", headers=PW, json={"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid},
                                                       "display": {"unit": "x" * 17}})
    assert r.status_code == 422  # 16자 초과


def test_v_c3f_reason_retryable_and_fail_limits(predict_env, monkeypatch):
    """§12·§10: 결과 FAIL(DONE)은 [다시] 없음(retryable false) + reason(manifest limits의 수치), 작업 FAILED·CANCELED는 retryable true."""
    env, jid = _env(predict_env)
    c = _post(env, jid, expect=202)
    assert env.w.run_once_slot() == "SUCCEEDED"
    g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert g["retryable"] is False and g["reason"] is None  # OK 결과: 사유 없음
    assert g["lod_artifact_id"] is None  # 합성 6노드 — LOD 없음
    # 결과 FAIL(TOO_LARGE·노드)로 바꾼다 — FAIL manifest(limits)를 같은 위치에 쓴다
    a = env.sql("select rel_path from artifacts where id=:i", i=g["manifest_artifact_id"])[0][0]
    (env.sroot / a).write_text(json.dumps({"status": "FAIL", "code": "CONTOUR3D_TOO_LARGE", "message": "외부 면 노드 973060개 > 상한 300000",
                                           "limits": {"nodes": 973060, "max_nodes": 300000, "glb_bytes": None, "max_glb_bytes": 67108864,
                                                      "max_bin_bytes": 268435456}}), encoding="utf-8")
    env.sql("update contour3d_cache set result_status='FAIL', code='CONTOUR3D_TOO_LARGE', nodes=973060 where id=:i", i=c["id"])
    f = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert f["status"] == "DONE" and f["retryable"] is False and f["glb_artifact_id"]  # (시험 행이라 id는 남음)
    rs = f["reason"]
    assert rs["kind"] == "nodes" and rs["nodes"] == 973060 and rs["max_nodes"] == 300000 and rs["max_glb_bytes"] == 67108864
    assert rs["code"] == "CONTOUR3D_TOO_LARGE" and rs["message_ko"] and "973060" in rs["detail"] and rs["comps_applicable"] is True
    # 형상 초과·프레임 초과 구분
    (env.sroot / a).write_text(json.dumps({"status": "FAIL", "code": "CONTOUR3D_TOO_LARGE", "message": "x",
                                           "limits": {"nodes": 10, "max_nodes": 100, "glb_bytes": 90, "max_glb_bytes": 64}}), encoding="utf-8")
    assert env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()["reason"]["kind"] == "glb"
    (env.sroot / a).write_text(json.dumps({"status": "FAIL", "code": "CONTOUR3D_TOO_LARGE", "message": "x",
                                           "limits": {"nodes": 10, "max_nodes": 100, "glb_bytes": 1, "max_glb_bytes": 64,
                                                      "max_bin_bytes": 1024}}), encoding="utf-8")
    assert env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()["reason"]["kind"] == "frames"
    (env.sroot / a).unlink()  # manifest를 읽지 못하면 수치 없이 code·message_ko만
    nr = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()["reason"]
    assert nr["kind"] == "other" and nr["nodes"] == 973060 and nr["max_nodes"] is None and nr["message_ko"]
    # 인프라 실패(FAILED)·취소는 [다시]
    monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", "open_error")
    bad = _post(env, jid, expect=202, display={"field": "X"})
    assert env.w.run_once_slot() == "FAILED"
    fb = env.c.get(f"{API}/contour3d/{bad['id']}", headers=P).json()
    assert fb["status"] == "FAILED" and fb["retryable"] is True and fb["reason"] is None
    q = _post(env, jid, expect=202, display={"field": "Z"})
    r = env.c.post(f"{API}/contour3d/{q['id']}/cancel", headers=PW)
    assert r.json()["status"] == "CANCELED" and r.json()["retryable"] is True


def test_v_c3f_12_media_no_transform_new_kinds_range_and_caps(predict_env):
    """V-C3F-12: media 응답(200·206·416)에 `Cache-Control: no-transform`, 새 kind(DISP·LOD) Range, 상한별 413 — GLB는 ui.max_artifact_bytes(20 MiB)가
    아니라 contour3d.max_glb_bytes를 따른다."""
    from physicsai_core.db.repositories import artifacts as artifacts_repo

    env, jid = _env(predict_env, max_glb_bytes=4096, max_bin_bytes=3000, max_disp_bytes=8192)
    d = env.sroot / "_cache" / "contour3d" / "zz"
    d.mkdir(parents=True)
    ids = {}

    def put(kind: str, name: str, size: int, ctype: str) -> str:
        (d / name).write_bytes(bytes(i % 251 for i in range(size)))
        with env.engine.begin() as conn:
            return artifacts_repo.insert(conn, study_id=env.sid, job_id=None, kind=kind, rel_path=f"_cache/contour3d/zz/{name}", size=size,
                                         sha256=None, content_type=ctype)

    ids["lod_ok"] = put("CONTOUR3D_LOD", "lod_ok.glb", 4000, "model/gltf-binary")
    ids["lod_big"] = put("CONTOUR3D_LOD", "lod_big.glb", 5000, "model/gltf-binary")
    ids["glb_big"] = put("CONTOUR3D_GLB", "glb_big.glb", 5000, "model/gltf-binary")
    ids["disp_ok"] = put("CONTOUR3D_DISP", "disp_ok.bin", 8000, "application/octet-stream")
    ids["disp_big"] = put("CONTOUR3D_DISP", "disp_big.bin", 9000, "application/octet-stream")
    ids["frames_big"] = put("CONTOUR3D_FRAMES", "frames_big.bin", 3500, "application/octet-stream")
    ids["frames_ok"] = put("CONTOUR3D_FRAMES", "frames_ok.bin", 3000, "application/octet-stream")

    def get(key: str, **h):
        return env.c.get(f"{API}/artifacts/{ids[key]}/media", headers={**P, **h})

    for key in ("lod_ok", "disp_ok", "frames_ok"):
        r = get(key)
        assert r.status_code == 200 and "no-transform" in r.headers["cache-control"], (key, r.status_code)
        assert r.headers["accept-ranges"] == "bytes"
    r = get("disp_ok", Range="bytes=100-199")
    assert r.status_code == 206 and r.headers["content-range"] == "bytes 100-199/8000" and len(r.content) == 100
    assert "no-transform" in r.headers["cache-control"] and r.headers["content-type"] == "application/octet-stream"
    r = get("lod_ok", Range="bytes=0-3")
    assert r.status_code == 206 and r.headers["content-type"] == "model/gltf-binary"
    r = get("disp_ok", Range="bytes=9000-")
    assert r.status_code == 416 and "no-transform" in r.headers["cache-control"]
    for key, limit in (("lod_big", 4096), ("glb_big", 4096), ("disp_big", 8192), ("frames_big", 3000)):
        r = get(key)
        assert r.status_code == 413 and r.json()["detail"]["limit"] == limit, (key, r.text)


def test_v_c3f_12_media_cap_per_kind_and_static_caddy():
    from types import SimpleNamespace

    from physicsai_api.services.contour_capture import media_cap
    from physicsai_core.config import load_config_dict

    s = load_config_dict({"storage": {"ai_root": "/tmp"}}, environ={}).settings
    ctx = SimpleNamespace(settings=s)
    assert s.ui.max_artifact_bytes == 20 * 1024 * 1024 and s.contour3d.max_glb_bytes == 64 * 1024 * 1024
    assert media_cap(ctx, "CONTOUR3D_GLB") == media_cap(ctx, "CONTOUR3D_LOD") == 67108864  # ui 상한(20 MiB)이 아니다(F5)
    assert media_cap(ctx, "CONTOUR3D_FRAMES") == 268435456 and media_cap(ctx, "CONTOUR3D_DISP") == 1073741824
    assert media_cap(ctx, "GEOM_VIEW_GLB") == s.ui.max_artifact_bytes and media_cap(ctx, "CONTOUR_VIDEO") == s.capture.max_video_bytes
    caddy = (Path(__file__).resolve().parents[3] / "deploy" / "caddy" / "physicsai.caddy").read_text(encoding="utf-8")
    code = [ln for ln in caddy.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("encode" in ln for ln in code)  # 응답 압축 지시어 없음(주석 안내만)
    assert "`encode`" in caddy and "/physicsai/api/artifacts/*" in caddy and "no-transform" in caddy


def test_v_c3f_13_no_disp_and_partial_disp_warnings(predict_env, monkeypatch):
    """변환기 통합 후: 변위 없음(`DISP=NONE`) → disp null·경고 DISP_UNAVAILABLE·OK, 일부 프레임 누락 → 변위 전체 제외 + 같은 경고,
    `SCOPE=ALL`인데 COMPS가 있으면 COMPS_IGNORED, `SKIPPED_NODES`는 DISP_DROPPED."""
    env, jid = _env(predict_env, display={"comps": ["A"]})
    for mode, code in (("no_disp", "CONTOUR3D_DISP_UNAVAILABLE"), ("disp_partial", "CONTOUR3D_DISP_UNAVAILABLE"),
                       ("skipped_nodes", "CONTOUR3D_DISP_DROPPED"), ("scope_all", "CONTOUR3D_COMPS_IGNORED")):
        monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", mode)
        c = _post(env, jid, expect=202, display={"field": f"F-{mode}"})
        assert env.w.run_once_slot() == "SUCCEEDED", env.job(c["job_id"])
        g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
        man = _manifest(env, g)
        assert g["result_status"] == "OK" and code in [w["code"] for w in man["warnings"]], (mode, man["warnings"])
        if mode != "scope_all":
            assert man["disp"] is None and man["frames"]["has_disp"] is False and g["disp_artifact_id"] is None
        assert code in [w["code"] for w in env.job(c["job_id"])["warnings"]]


def test_v_c3f_13_fake_hw_modes_keep_job_ok_and_scalar_only_flow(predict_env, monkeypatch):
    """변환기와 무관하게: 변위 없음·일부 누락·노드 상한 생략·SCOPE=ALL 폴백 모두 추출은 OK로 끝나고 작업이 성공한다(스칼라만으로 계속)."""
    env, jid = _env(predict_env, display={"comps": ["A"]})
    for mode in ("no_disp", "disp_partial", "skipped_nodes", "scope_all"):
        monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", mode)
        c = _post(env, jid, expect=202, display={"field": f"F-{mode}"})
        assert env.w.run_once_slot() == "SUCCEEDED", (mode, env.job(c["job_id"]))
        g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
        assert g["status"] == "DONE" and g["result_status"] == "OK" and g["retryable"] is False and g["reason"] is None, mode


def test_v_c3f_housekeeping_purge_removes_disp_and_lod_artifact_rows(predict_env):
    """C3F §5.6: 변위·LOD 산출물은 캐시 행에 열이 없어도 만료·총량 정리 때 함께 지워지고, 만료 뒤 응답 id는 null."""
    from datetime import datetime, timedelta, timezone

    from physicsai_core.db.repositories import artifacts as artifacts_repo
    from physicsai_worker.housekeeping import purge_view_cache

    env, jid = _env(predict_env)
    c = _post(env, jid, expect=202)
    assert env.w.run_once_slot() == "SUCCEEDED"
    have = {r[0] for r in env.sql("select kind from artifacts where job_id=:j", j=c["job_id"])}
    with env.engine.begin() as conn:  # 변환기가 이미 등록한 kind는 두고(가짜 hw는 변위를 만든다), 없는 kind(LOD)만 같은 작업에 붙인다(캐시 폴더 안 파일)
        for kind, name in (("CONTOUR3D_DISP", "contour_disp.bin"), ("CONTOUR3D_LOD", "contour_lod.glb")):
            if kind in have:
                continue
            d = next((env.sroot / "_cache" / "contour3d").glob("*/*"))
            (d / "out").mkdir(exist_ok=True)
            (d / "out" / name).write_bytes(b"x" * 16)
            artifacts_repo.insert(conn, study_id=env.sid, job_id=c["job_id"], kind=kind, rel_path=f"_cache/contour3d/{d.parent.name}/{d.name}/out/{name}",
                                  size=16, sha256=None, content_type="application/octet-stream")
    g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert g["disp_artifact_id"] and g["lod_artifact_id"]  # 같은 작업의 kind로 조회
    assert env.c.get(f"{API}/artifacts/{g['disp_artifact_id']}/media", headers={**P, "Range": "bytes=0-3"}).status_code == 206
    assert env.sql("select count(*) from artifacts where job_id=:j and kind in ('CONTOUR3D_DISP','CONTOUR3D_LOD')", j=c["job_id"])[0][0] == 2
    env.sql("update contour3d_cache set last_access_at=:t where id=:i", t=datetime.now(timezone.utc) - timedelta(days=30), i=c["id"])
    out = purge_view_cache(env.engine, env.lc.settings)
    assert out["expired"] == 1
    assert env.sql("select count(*) from artifacts where job_id=:j and kind like 'CONTOUR3D_%'", j=c["job_id"])[0][0] == 0
    e = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert e["status"] == "EXPIRED" and e["disp_artifact_id"] is None and e["lod_artifact_id"] is None
    assert env.c.get(f"{API}/artifacts/{g['disp_artifact_id']}/media", headers=P).status_code in (404, 410)
