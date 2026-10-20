"""형상 3D 보기·미리보기 E2E(geometry-view.md §6, V-GV 플랫폼): NP_VIEW(READY·실패 경고)·GET /view·artifacts media(GLB), ① TX_VIEW·
GET /train/view, 미리보기 202 → PREVIEW 레인 → DONE·캐시 200·중복 반환·QUEUED 취소·429·FAIL 결과 캐시·인프라 실패 비캐시·시간 초과,
전역 슬롯 점유 중 실행·동시 1, housekeeping(기간·총량·경로 탈출·링크)·410, 작업 목록 기본 숨김. 가짜 paicad(view)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from helpers_native import make_project, native_set
from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")


def _env(native_env, **kw):
    env = native_env(**kw)
    ps = native_set(env)
    env.w.heartbeat_once()  # resources.paicad_version(미리보기 캐시 키)
    return env, ps


def _preview(env, psid, values, fe="off", expect=(200, 202)):
    r = env.c.post(f"{API}/param-sets/{psid}/previews", headers=PW, json={"values": values, "fe": fe})
    assert r.status_code in ((expect,) if isinstance(expect, int) else expect), r.text
    return r


def test_np_view_ready_and_media(native_env, fake_record):
    env, ps = _env(native_env)
    v = env.c.get(f"{API}/param-sets/{ps['id']}/view", headers=P).json()
    assert v["status"] == "READY" and v["kind"] == "solid" and v["available"] and v["preview_available"], v
    assert v["tess"] == {"linear_mm": 0.1, "angular_deg": 20.0}
    assert env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()["native"]["view_status"] == "READY"
    S = env.sroot / "04_params" / ps["id"]
    assert json.loads((S / "native" / "prep.json").read_text())["view"]["status"] == "READY"
    vo = json.loads((S / "native" / "view" / "view_options.json").read_text())
    assert vo["tess"] == {"linear_mm": 0.1, "angular_deg": 20.0} and vo["max_glb_bytes"] <= env.lc.settings.ui.max_artifact_bytes
    r = env.c.get(f"{API}/artifacts/{v['glb_artifact_id']}/media", headers={**P, "Range": "bytes=0-3"})
    assert r.status_code == 206 and r.headers["content-type"] == "model/gltf-binary" and r.content == b"glTF"
    m = env.c.get(f"{API}/artifacts/{v['manifest_artifact_id']}/content", headers=P)
    assert m.status_code == 200 and m.json()["mode"] == "nominal"
    alt = env.param_set()
    r = env.c.get(f"{API}/param-sets/{alt['id']}/view", headers=P)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VIEW_NATIVE_ONLY"


def test_np_view_failure_is_warning(native_env, monkeypatch):
    env = native_env()
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "view_export:VIEW_TESSELLATION_FAILED")
    ps = native_set(env)  # 세트 등록은 성공
    v = env.c.get(f"{API}/param-sets/{ps['id']}/view", headers=P).json()
    assert v["status"] == "FAILED" and v["glb_artifact_id"] is None and "그림" in v["reason"]
    env2 = native_env(commands={"paicad_view_export": None}, folder="p2")
    ps2 = native_set(env2)
    assert env2.c.get(f"{API}/param-sets/{ps2['id']}/view", headers=P).json()["status"] == "MISSING"


def test_train_view_tx_view(native_env, monkeypatch):
    env = native_env()
    proj = make_project(env.imports)
    j = env.submit("TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    assert env.steps(j["id"])["TX_VIEW"]["state"] == "SUCCEEDED"
    v = env.c.get(f"{API}/studies/{env.sid}/train/view", headers=P).json()
    assert v["status"] == "READY" and v["param_set_id"] is None and v["preview_available"] is False and v["glb_artifact_id"]
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "view_export:VIEW_TOO_LARGE")
    j = env.submit("TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert env.w.run_once_slot() == "SUCCEEDED"
    assert "VIEW_EXPORT_FAILED" in [w["code"] for w in env.job(j["id"])["warnings"]]
    env2 = native_env(engine="altair", folder="p2")
    assert env2.c.get(f"{API}/studies/{env2.sid}/train/view", headers=P).status_code == 404


def test_preview_queue_run_cache_and_dedupe(native_env, fake_record):
    env, ps = _env(native_env)
    r = _preview(env, ps["id"], {"A_THK_1": 10.3}, expect=202)
    p = r.json()
    assert p["status"] == "QUEUED" and p["job_id"] and p["cache_hit"] is False
    assert p["values"] == {"A_THK_1": 10.3, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}  # 빠진 이름은 공칭
    dup = _preview(env, ps["id"], {"A_THK_1": 10.3}, expect=202).json()
    assert dup["id"] == p["id"]  # 같은 키 QUEUED → 그 행(작업 중복 없음)
    assert env.w.run_once_preview() == "SUCCEEDED"
    g = env.c.get(f"{API}/previews/{p['id']}", headers=P).json()
    assert g["status"] == "DONE" and g["result_status"] == "OK" and g["glb_artifact_id"] and g["manifest_artifact_id"]
    assert g["fe_glb_artifact_id"] is None and g["timing"]["total_s"] == 0.2
    pv = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1:3] == ["view", "preview"]][-1]
    assert pv[pv.index("--fe") + 1] == "off" and pv[pv.index("--threads") + 1] == "2"
    assert pv[pv.index("--nominal-manifest") + 1].endswith("native/view/view_manifest.json")
    out = pv[pv.index("--out-dir") + 1]
    assert "/_cache/geom_preview/" in out.replace("\\", "/") and not any(f.endswith(".inc") for f in os.listdir(out))
    hit = _preview(env, ps["id"], {"A_THK_1": 10.3, "B_RIB_H_1": 20.0}, expect=200).json()
    assert hit["cache_hit"] and hit["id"] == p["id"] and hit["status"] == "DONE"
    m = env.c.get(f"{API}/artifacts/{g['glb_artifact_id']}/media", headers=P)
    assert m.status_code == 200 and m.content[:4] == b"glTF"
    fe = _preview(env, ps["id"], {"A_THK_1": 10.3}, fe="check", expect=202).json()  # fe가 다르면 다른 키
    assert fe["id"] != p["id"]
    assert env.w.run_once_preview() == "SUCCEEDED"
    assert env.c.get(f"{API}/previews/{fe['id']}", headers=P).json()["fe_glb_artifact_id"]
    jobs = env.c.get(f"{API}/jobs?study_id={env.sid}", headers=P).json()
    assert "GEOM_PREVIEW" not in {j["job_type"] for j in jobs}  # 작업 목록 기본 숨김
    jobs = env.c.get(f"{API}/jobs?study_id={env.sid}&include_preview=true", headers=P).json()
    assert "GEOM_PREVIEW" in {j["job_type"] for j in jobs}


def test_preview_cancel_busy_and_validation(native_env):
    env, ps = _env(native_env, geometry={"view": {"max_queued_per_user": 1}})
    a = _preview(env, ps["id"], {"A_THK_1": 10.1}, expect=202).json()
    b = _preview(env, ps["id"], {"A_THK_1": 10.2}, expect=202).json()  # 같은 사용자·세트 QUEUED → 이전 요청 취소(최신 값 우선)
    assert env.c.get(f"{API}/previews/{a['id']}", headers=P).json()["status"] == "CANCELED"
    assert env.job(a["job_id"])["state"] == "CANCELED"
    ps2 = native_set(env)
    env.w.heartbeat_once()
    r = _preview(env, ps2["id"], {"A_THK_1": 10.0}, expect=429)
    assert r.json()["detail"]["code"] == "PREVIEW_BUSY"
    assert env.w.run_once_preview() == "SUCCEEDED"
    assert env.c.get(f"{API}/previews/{b['id']}", headers=P).json()["status"] == "DONE"
    r = _preview(env, ps["id"], {"NOPE": 1.0}, expect=422)
    assert r.json()["detail"]["code"] == "INPUT_INVALID" and r.json()["detail"]["errors"][0]["loc"] == ["values", "NOPE"]
    alt = env.param_set()
    r = _preview(env, alt["id"], {}, expect=409)
    assert r.json()["detail"]["code"] == "VIEW_NATIVE_ONLY"
    env3 = native_env(commands={"paicad_view_preview": None}, folder="p3")
    ps3 = native_set(env3)
    r = env3.c.post(f"{API}/param-sets/{ps3['id']}/previews", headers=PW, json={"values": {}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VIEW_UNAVAILABLE"
    (env.sroot / "04_params" / ps["id"] / "radioss_assem" / "104_replace_node_elem.inc").write_text("/NODE\n1 1 1 1\n")
    r = _preview(env, ps["id"], {"A_THK_1": 10.4}, expect=409)
    assert r.json()["detail"]["code"] == "GEOM_PREP_STALE"


def test_preview_fail_result_cached_infra_not(native_env, monkeypatch):
    env, ps = _env(native_env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "view_preview:GEOM_FEATURE_COLLISION")
    p = _preview(env, ps["id"], {"A_THK_1": 10.4}, expect=202).json()
    assert env.w.run_once_preview() == "SUCCEEDED"  # GV-10: 결과 FAIL도 작업 성공
    g = env.c.get(f"{API}/previews/{p['id']}", headers=P).json()
    assert g["status"] == "DONE" and g["result_status"] == "FAIL" and g["code"] == "GEOM_FEATURE_COLLISION"
    assert g["message_ko"].startswith("CAD 생성 불가(피처 간 충돌") and g["glb_artifact_id"] is None and g["manifest_artifact_id"]
    assert _preview(env, ps["id"], {"A_THK_1": 10.4}, expect=200).json()["cache_hit"]
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "view_preview:VIEW_TOO_LARGE")
    p2 = _preview(env, ps["id"], {"A_THK_1": 10.45}, expect=202).json()
    assert env.w.run_once_preview() == "FAILED"
    g = env.c.get(f"{API}/previews/{p2['id']}", headers=P).json()
    assert g["status"] == "FAILED" and g["code"] == "VIEW_TOO_LARGE"
    assert env.job(p2["job_id"])["can_retry"] is False
    again = _preview(env, ps["id"], {"A_THK_1": 10.45}, expect=202).json()
    assert again["id"] != p2["id"]  # 인프라 실패는 캐시하지 않는다


def test_preview_timeout(native_env, monkeypatch):
    env, ps = _env(native_env, geometry={"view": {"timeout_s": {"export": 300, "preview": 1, "preview_fe": 300}}})
    monkeypatch.setenv("FAKE_PAICAD_SLEEP_S", "3")
    p = _preview(env, ps["id"], {"A_THK_1": 10.2}, expect=202).json()
    assert env.w.run_once_preview() == "FAILED"
    assert env.job(p["job_id"])["failure_code"] == "VIEW_PREVIEW_TIMEOUT"
    assert env.c.get(f"{API}/previews/{p['id']}", headers=P).json()["status"] == "FAILED"


def test_preview_runs_while_slot_busy_and_concurrency_one(native_env):
    from physicsai_core.db.repositories import job_lease as lease_repo

    env, ps = _env(native_env)
    j = env.submit("PREDICT", {"values": {"A_THK_1": 10.2, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}, "value_source": "manual"})
    held = env.w.claim_only()  # 전역 슬롯 점유(DOE·일괄 예측 실행 중 모사)
    assert held is not None and held["id"] == j["id"]
    p = _preview(env, ps["id"], {"A_THK_1": 10.1}, expect=202).json()
    q = _preview(env, ps["id"], {"B_RIB_H_1": 20.5}, expect=202).json()  # 다른 사용자 아님 → p는 취소됨; q만 대기
    with env.engine.begin() as conn:  # PREVIEW 실행 중 1개를 만들고(실행 없이 claim) 동시 1이면 두 번째 claim 없음
        first = lease_repo.claim_preview(conn, "w-test", 60, 1)
    assert first is not None and first["id"] == q["job_id"] and first["holds_slot"] is False
    from physicsai_core.db.repositories import jobs as jobs_repo

    with env.engine.begin() as conn:
        study = {"id": env.sid, "project_id": "p-1"}
        extra = jobs_repo.insert_job(conn, study=study, job_type="GEOM_PREVIEW", params={"x": 1}, user_id="u2", user_name="u2")
        assert lease_repo.claim_preview(conn, "w-test", 60, 1) is None  # 동시 1(설정 max_concurrent)
        assert lease_repo.claim_preview(conn, "w-test", 60, 2)["id"] == extra["id"]
    assert p["id"] != q["id"]


def _done_preview(env, ps, val):
    p = _preview(env, ps["id"], {"A_THK_1": val}, expect=202).json()
    assert env.w.run_once_preview() == "SUCCEEDED"
    return env.c.get(f"{API}/previews/{p['id']}", headers=P).json()


def test_housekeeping_purge_age_total_and_410(native_env):
    from physicsai_worker.housekeeping import purge_view_cache

    env, ps = _env(native_env)
    old = _done_preview(env, ps, 10.1)
    new = _done_preview(env, ps, 10.2)
    root = env.sroot / "_cache" / "geom_preview"
    dirs = sorted(p for p in root.glob("*/*") if p.is_dir())
    assert len(dirs) == 2
    past = datetime.now(timezone.utc) - timedelta(days=30)
    env.sql("update geom_previews set last_access_at=:t where id=:i", t=past, i=old["id"])
    out = purge_view_cache(env.engine, env.lc.settings)
    assert out["expired"] == 1 and out["lru"] == 0
    assert env.c.get(f"{API}/previews/{old['id']}", headers=P).json()["status"] == "EXPIRED"
    r = env.c.get(f"{API}/artifacts/{old['glb_artifact_id']}/media", headers=P)
    assert r.status_code == 410 and r.json()["detail"]["code"] == "ARTIFACT_EXPIRED"
    assert env.c.get(f"{API}/artifacts/{old['manifest_artifact_id']}/content", headers=P).status_code == 410
    assert env.c.get(f"{API}/artifacts/{new['glb_artifact_id']}/media", headers=P).status_code == 200
    assert (env.sroot / "04_params" / ps["id"] / "native" / "view" / "view.glb").is_file()  # _cache 밖은 건드리지 않음
    # 총량 초과 → 오래된 것부터
    from physicsai_core.config import load_config_dict

    tiny = load_config_dict({**env.lc.settings.model_dump(), "geometry": {**env.lc.settings.geometry.model_dump(),
                                                                         "view": {"cache": {"max_total_bytes": 1048576}}}}, environ={})
    big = root / new["id"][:2]
    (env.sroot / "_cache" / "filler.bin").write_bytes(b"\0" * 1100000)  # 합계 > 1 MiB
    out = purge_view_cache(env.engine, tiny.settings)
    assert out["lru"] == 1 and env.c.get(f"{API}/previews/{new['id']}", headers=P).json()["status"] == "EXPIRED"
    assert big is not None
    # 다시 요청하면 새로 만든다(만료 행은 캐시 아님)
    again = _preview(env, ps["id"], {"A_THK_1": 10.2}, expect=202).json()
    assert again["id"] != new["id"]


def test_housekeeping_skips_links_and_active(native_env, tmp_path):
    from physicsai_core.geometry.view import PREVIEW_CACHE, cache_rel
    from physicsai_worker.housekeeping import purge_view_cache

    env, ps = _env(native_env)
    done = _done_preview(env, ps, 10.3)
    key = env.sql("select cache_key from geom_previews where id=:i", i=done["id"])[0][0]
    d = env.sroot / cache_rel(PREVIEW_CACHE, key)
    import shutil

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("user data")
    shutil.rmtree(d)
    os.symlink(outside, d)  # 캐시 폴더가 링크면 지우지 않는다
    env.sql("update geom_previews set last_access_at=:t where id=:i", t=datetime.now(timezone.utc) - timedelta(days=30), i=done["id"])
    queued = _preview(env, ps["id"], {"A_THK_1": 10.35}, expect=202).json()
    env.sql("update geom_previews set last_access_at=:t where id=:i", t=datetime.now(timezone.utc) - timedelta(days=30), i=queued["id"])
    out = purge_view_cache(env.engine, env.lc.settings)
    assert out["skipped"] == 1 and (outside / "keep.txt").is_file()
    assert env.c.get(f"{API}/previews/{done['id']}", headers=P).json()["status"] == "DONE"
    assert env.c.get(f"{API}/previews/{queued['id']}", headers=P).json()["status"] == "QUEUED"  # 대기·실행 중은 건너뜀


def test_from_train_copies_train_view(native_env, fake_record):
    """①-1 TX_VIEW 공칭 뷰 → ①-3 DG_PREP이 D/native/view로 → from-train(동기, paicad 없음)이 세트로 복사·등록(§6.9)."""
    from helpers_stage1 import job, submit

    env = native_env(final_model=False)
    c, w, sid = env.c, env.w, env.sid
    proj = make_project(env.imports)
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    j = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 2, "seed": 3, "radioss_assem_path": str(proj / "assem")})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    before = len(read_record(fake_record))
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id, "runs": "all"})
    assert r.status_code == 201, r.text
    ps = r.json()
    assert ps["native"]["view_status"] == "READY" and len(read_record(fake_record)) == before
    v = c.get(f"{API}/param-sets/{ps['id']}/view", headers=P).json()
    assert v["status"] == "READY" and v["glb_artifact_id"] and v["manifest_artifact_id"]
    assert c.get(f"{API}/artifacts/{v['glb_artifact_id']}/media", headers=P).content[:4] == b"glTF"


def test_preview_lane_static_rules_and_status(native_env):
    """§6.2: PREVIEW 레인 작업 유형·허용 명령(정적), /status features(geometry_view·_shell·native_shell·contour3d)."""
    from physicsai_core.geometry.view import preview_key
    from physicsai_core.job_types import JOB_TYPES
    from physicsai_worker.step_process import PREVIEW_LANE_COMMANDS
    from physicsai_worker.steps.stage4_predict.geom_preview import PREVIEW_COMMANDS

    assert {k for k, d in JOB_TYPES.items() if d.lane == "PREVIEW"} == {"GEOM_PREVIEW"}
    assert not any(JOB_TYPES["GEOM_PREVIEW"].needs_slot(s) for s in JOB_TYPES["GEOM_PREVIEW"].steps)  # 전역 슬롯 미사용
    assert PREVIEW_COMMANDS == PREVIEW_LANE_COMMANDS == {preview_key("solid"), preview_key("shell")}
    assert JOB_TYPES["CONTOUR_3D"].lane == "LIGHT" and [s.key for s in JOB_TYPES["PARAM_SET_NATIVE"].steps].index("NP_VIEW") == 3
    env = native_env()
    f = env.c.get(f"{API}/status", headers=P).json()["features"]
    assert f["geometry_view"]["enabled"] and f["geometry_native_shell"]["enabled"]
    assert f["geometry_view_shell"]["enabled"]  # paicad 0.10.0 `shell view` 기본 템플릿(GV §6.1)
    assert f["contour3d"]["enabled"] is False and "contour3d.enabled" in f["contour3d"]["missing"]
