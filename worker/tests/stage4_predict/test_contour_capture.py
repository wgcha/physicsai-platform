"""④ 컨투어 캡처(phase3 §15 S10): 예측 체인 끝 CONTOUR_CAPTURE(가짜 hw 캡처 모드) — 골든 argv·cwd·settings, 방향별 산출물,
실패는 경고만, 시간 초과, 표시 설정 결정(config·응답 정의·템플릿·작업·배치), 방향 목록 API·Range·크기 상한·권한, 재캡처, B 행 media_views."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from physicsai_test_support import API, H, make_param_set_folder, read_record

from .test_predict_prepared import make_case

P = H("tok-power")
PW = H("tok-power", write=True)
GW = H("tok-general", write=True)
VIEWS4 = ["iso", "front", "top", "right"]


def _capture_records(rec: Path) -> list[dict]:
    return [r for r in read_record(rec) if r["tool"] == "hw_capture"]


def _predict(env, case: Path, expect="SUCCEEDED", **extra) -> tuple[str, dict]:
    j = env.submit("PREDICT", {"input_mode": "prepared", "input_path": str(case), **extra})
    st = env.w.run_once_slot()
    jd = env.job(j["id"])
    assert st == expect, jd
    return j["id"], jd


def _artifacts(engine, job_id: str) -> list[dict]:
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(
            "select kind, rel_path, content_type, size, meta from artifacts where job_id=:j and kind like 'CONTOUR_%'"
            " order by kind, rel_path"), {"j": job_id})]


def test_v3_s10_capture_golden_and_media_api(predict_env, fake_record, engine):
    env = predict_env()
    jid, jd = _predict(env, make_case(env.imports))
    steps = env.steps(jid)
    assert list(steps)[-1] == "CONTOUR_CAPTURE" and steps["CONTOUR_CAPTURE"]["state"] == "SUCCEEDED"
    Pd = env.predict_dir(jid)
    media = Pd / "RESULT" / "media"
    (rec,) = _capture_records(fake_record)
    hw = env.lc.settings.altair.hw_exe_path
    assert rec["argv"][1:] == ["-clientconfig", "hwpost.dat", "-b", "-tcl", str(media / "contour_capture.tcl").replace("\\", "/")]
    assert os.path.samefile(rec["argv"][0], hw) and rec["cwd"] == str(media)
    st = rec["settings"]
    assert st["H3D_PATH"] == str(Pd / "RESULT" / "Face_Drop_0000_pred.h3d").replace("\\", "/")
    assert st["OUTDIR"] == str(media).replace("\\", "/") and st["VIEWS"] == VIEWS4 and st["FIELD"] == "CornerStress"
    assert (st["DCOMP"], st["LEGMIN"], st["LEGMAX"], st["SAVE_VIDEO"], st["VID_EXT"], st["USE_LAST"]) == ("", "", "", "1", "mp4", "1")
    assert (media / "contour_capture.tcl").read_text(encoding="utf-8").startswith("# =====")
    res = jd["result"]
    assert [m["view"] for m in res["media"]] == VIEWS4 and all(m["image_artifact_id"] and m["video_artifact_id"] for m in res["media"])
    cap = res["capture"]
    assert (cap["status"], cap["field_source"], cap["video_ext"], cap["failed_views"]) == ("OK", "config", "mp4", [])
    assert cap["display"]["legend"] == {"mode": "auto", "min": None, "max": None} and cap["dir_rel"].endswith("RESULT/media")
    assert not [w for w in jd["warnings"] if w["code"].startswith("CAPTURE")]
    arts = _artifacts(engine, jid)
    assert [(a["kind"], a["content_type"], a["meta"]["view"]) for a in arts][:1] == [("CONTOUR_IMAGE", "image/png", "front")]
    assert sorted((a["kind"], a["meta"]["view"]) for a in arts) == sorted(
        [("CONTOUR_IMAGE", v) for v in VIEWS4] + [("CONTOUR_VIDEO", v) for v in VIEWS4])
    assert {a["content_type"] for a in arts if a["kind"] == "CONTOUR_VIDEO"} == {"video/mp4"}

    # ---- 방향 목록 ----
    r = env.c.get(f"{API}/jobs/{jid}/media", headers=H("tok-general"))       # 조회 = 로그인
    assert r.status_code == 200, r.text
    m = r.json()
    assert (m["status"], m["capture_enabled"], m["can_recapture"], m["recapture"]) == ("OK", True, False, None)
    assert [(i["view"], i["label"], i["job_id"]) for i in m["items"]] == [
        ("iso", "등각", jid), ("front", "정면", jid), ("top", "위", jid), ("right", "오른쪽", jid)]
    assert env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()["can_recapture"] is True
    img, vid = m["items"][0]["image"], m["items"][0]["video"]
    assert img["url"] == f"/physicsai/api/artifacts/{img['artifact_id']}/media" and img["content_type"] == "image/png"
    assert vid["content_type"] == "video/mp4" and vid["size"] == 64 and vid["download_url"].endswith("?download=true")
    assert env.c.get(f"{API}/jobs/{jid}/media").status_code == 401

    # ---- 파일 제공: 200·206(Range)·416·내려받기·종류·인증 ----
    r = env.c.get(f"{API}/artifacts/{img['artifact_id']}/media", headers=P)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == (media / "iso.png").read_bytes()
    assert r.headers["accept-ranges"] == "bytes" and r.headers["content-disposition"].startswith("inline")
    full = (media / "iso.mp4").read_bytes()
    u = f"{API}/artifacts/{vid['artifact_id']}/media"
    r = env.c.get(u, headers=P)
    assert r.status_code == 200 and r.content == full and r.headers["content-length"] == "64"
    for rng, (a, b) in (("bytes=0-9", (0, 9)), ("bytes=60-", (60, 63)), ("bytes=-5", (59, 63)), ("bytes=10-1000", (10, 63))):
        r = env.c.get(u, headers={**P, "Range": rng})
        assert r.status_code == 206, rng
        assert r.headers["content-range"] == f"bytes {a}-{b}/64" and r.content == full[a:b + 1], rng
        assert r.headers["content-type"] == "video/mp4" and r.headers["content-length"] == str(b - a + 1)
    r = env.c.get(u, headers={**P, "Range": "bytes=64-"})
    assert r.status_code == 416 and r.headers["content-range"] == "bytes */64"
    assert env.c.get(u, headers={**P, "Range": "bytes=0-1,5-6"}).status_code == 200            # 여러 범위 → 전체
    for rng in ("bytes=10-5", "bytes=\u0661-\u0662"):                                         # 문법 오류 → 무시(D3-53)
        r = env.c.get(u, headers={**P, "Range": rng.encode("utf-8")})
        assert r.status_code == 200 and r.content == full and "content-range" not in r.headers, rng
    assert env.c.get(u, headers={**P, "Range": "bytes=-0"}).status_code == 416                 # 만족 불가만 416
    r = env.c.get(u + "?download=true", headers=P)
    assert r.headers["content-disposition"] == f'attachment; filename="{jid[:8]}_iso.mp4"'
    assert env.c.get(u).status_code == 401
    pid = jd["result"]["preview_json_artifact_id"]
    assert env.c.get(f"{API}/artifacts/{pid}/media", headers=P).status_code == 404               # 컨투어 외 산출물
    assert env.c.get(f"{API}/artifacts/00000000-0000-0000-0000-000000000000/media", headers=P).status_code == 404


@pytest.mark.parametrize("mode,n,status", [("fail", 0, "FAILED"), ("open_error", 0, "FAILED"), ("one_fail", 3, "PARTIAL"),
                                            ("no_manifest", 4, "OK"), ("no_video", 4, "OK")])
def test_v3_s10_capture_failure_is_warning_only(predict_env, fake_record, monkeypatch, mode, n, status):
    monkeypatch.setenv("FAKE_TOOL_MODE_CAPTURE", mode)
    env = predict_env()
    jid, jd = _predict(env, make_case(env.imports))                      # 예측 작업은 성공 유지
    assert env.steps(jid)["CONTOUR_CAPTURE"]["state"] == "SUCCEEDED"
    res = jd["result"]
    assert len(res["media"]) == n and res["capture"]["status"] == status
    warns = [w for w in jd["warnings"] if w["code"] == "CAPTURE_FAILED"]
    assert bool(warns) == (status != "OK"), jd["warnings"]
    if mode == "open_error":
        assert "OPEN_ERROR" in warns[0]["message"] or "cannot open" in warns[0]["message"]
    if mode == "one_fail":
        assert res["capture"]["failed_views"] == ["iso"] and "fake save failed" in warns[0]["message"]
    if mode == "no_video":
        assert all(m["video_artifact_id"] is None for m in res["media"])
    m = env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()
    assert m["status"] == status and len(m["items"]) == n


def test_v3_s10_capture_exec_missing_and_disabled(predict_env, fake_record, tmp_path):
    env = predict_env(resources={"contour_capture_tcl": str(tmp_path / "missing" / "contour_capture.tcl")})
    jid, jd = _predict(env, make_case(env.imports))
    assert [w["code"] for w in jd["warnings"]] == ["CAPTURE_FAILED"] and "캡처 TCL" in jd["warnings"][0]["message"]
    assert jd["result"]["capture"]["status"] == "FAILED" and not _capture_records(fake_record)
    m = env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()
    assert m["capture_enabled"] is False and m["can_recapture"] is False
    env2 = predict_env(folder="pred2")
    env2.lc.settings.capture.enabled = False                            # 같은 설정 객체(워커·API 공용)
    jid2, jd2 = _predict(env2, make_case(env2.imports, "case_B"))
    st = env2.steps(jid2)["CONTOUR_CAPTURE"]
    assert st["state"] == "SKIPPED" and st["progress_label"] == "컨투어 캡처 꺼짐(capture.enabled)"
    assert jd2["result"]["capture"] == {"status": "SKIPPED", "message": "컨투어 캡처 꺼짐(capture.enabled)"}
    assert not [w for w in jd2["warnings"] if w["code"] == "CAPTURE_FAILED"] and len(_capture_records(fake_record)) == 0
    m2 = env2.c.get(f"{API}/jobs/{jid2}/media", headers=P).json()
    assert (m2["status"], m2["items"], m2["capture_enabled"], m2["can_recapture"]) == ("SKIPPED", [], False, False)


def test_v3_s10_capture_timeout(predict_env, fake_record, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_CAPTURE", "hang")
    monkeypatch.setenv("FAKE_CAPTURE_HANG_S", "60")
    env = predict_env()
    env.lc.settings.capture.timeout_s = 1
    t0 = time.monotonic()
    jid, jd = _predict(env, make_case(env.imports))
    assert time.monotonic() - t0 < 40
    w = [x for x in jd["warnings"] if x["code"] == "CAPTURE_FAILED"]
    assert w and "시간 초과" in w[0]["message"] and jd["result"]["media"] == []


def test_v3_s10_video_size_limit(predict_env, fake_record, monkeypatch, engine):
    monkeypatch.setenv("FAKE_CAPTURE_VIDEO_BYTES", str(1048576 + 10))
    env = predict_env()
    env.lc.settings.capture.max_video_bytes = 1048576
    jid, jd = _predict(env, make_case(env.imports))
    assert {w["code"] for w in jd["warnings"]} == {"CAPTURE_VIDEO_TOO_LARGE"}
    assert [m["video_artifact_id"] for m in jd["result"]["media"]] == [None] * 4 and jd["result"]["capture"]["status"] == "OK"
    # 등록 뒤 파일이 상한을 넘으면 제공 413
    monkeypatch.setenv("FAKE_CAPTURE_VIDEO_BYTES", "64")
    jid2, jd2 = _predict(env, make_case(env.imports, "case_C"))
    vid = jd2["result"]["media"][0]["video_artifact_id"]
    with open(env.predict_dir(jid2) / "RESULT" / "media" / "iso.mp4", "ab") as fh:
        fh.write(b"\0" * 1048576)
    r = env.c.get(f"{API}/artifacts/{vid}/media", headers=P)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "ARTIFACT_TOO_LARGE"


def test_v3_s10_display_resolution_template_and_params(predict_env, fake_record):
    env = predict_env()
    ps = env.param_set()
    # 응답 정의 첫 항목(spec 있음)의 datatype/component
    spec = {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}
    r = env.c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW,
                  json={"responses": [{"name": "MaxStress", "unit": "MPa", "spec": spec}, {"name": "Disp", "unit": "mm", "spec": None}]})
    assert r.status_code == 200, r.text
    jid, jd = _predict(env, make_case(env.imports), param_set_id=ps["id"])
    st = _capture_records(fake_record)[-1]["settings"]
    assert (st["FIELD"], st["DCOMP"], jd["result"]["capture"]["field_source"]) == ("Stress", "vonMises", "response")
    # 템플릿 표시 설정(PUT /param-sets/{id}/display): 권한·검증·저장
    body = {"display": {"field": "Displacement", "component": "Mag", "comps": ["PART 1"], "views": ["top", "iso"],
                        "legend": {"mode": "fixed", "min": 0, "max": 12.5}}}
    assert env.c.put(f"{API}/param-sets/{ps['id']}/display", headers=GW, json=body).status_code == 403
    for bad in ({"display": {"views": ["iso", "iso"]}}, {"display": {"field": 'a"b'}}, {"display": {"legend": {"mode": "fixed"}}},
                {"display": {"views": ["diag"]}}, {"display": {"bogus": 1}}):
        r = env.c.put(f"{API}/param-sets/{ps['id']}/display", headers=PW, json=bad)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS", bad
    r = env.c.put(f"{API}/param-sets/{ps['id']}/display", headers=PW, json=body)
    assert r.status_code == 200 and r.json()["display"] == {**body["display"], "legend": {"mode": "fixed", "min": 0.0, "max": 12.5}}
    assert env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()["display"]["field"] == "Displacement"
    jid, jd = _predict(env, make_case(env.imports, "case_D"), param_set_id=ps["id"])
    st = _capture_records(fake_record)[-1]["settings"]
    assert (st["FIELD"], st["DCOMP"], st["COMPS"], st["VIEWS"], st["LEGMIN"], st["LEGMAX"]) == (
        "Displacement", "Mag", ["PART 1"], ["top", "iso"], "0", "12.5")
    assert [m["view"] for m in jd["result"]["media"]] == ["top", "iso"]
    # 작업 params display(준비된 입력)가 템플릿보다 우선, 저장 params에 남음
    jid, jd = _predict(env, make_case(env.imports, "case_E"), param_set_id=ps["id"],
                       display={"legend": {"mode": "auto"}, "views": ["right"]})
    assert jd["params"]["display"] == {"legend": {"mode": "auto", "min": None, "max": None}, "views": ["right"]}
    st = _capture_records(fake_record)[-1]["settings"]
    assert (st["FIELD"], st["LEGMIN"], st["VIEWS"]) == ("Displacement", "", ["right"])
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT", "params": {
        "input_mode": "prepared", "input_path": str(make_case(env.imports, "case_F")), "display": {"views": []}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    # null = 지움
    r = env.c.put(f"{API}/param-sets/{ps['id']}/display", headers=PW, json={"display": None})
    assert r.status_code == 200 and r.json()["display"] is None


def test_v3_s10_recapture(predict_env, fake_record, monkeypatch, engine):
    env = predict_env()
    jid, _jd = _predict(env, make_case(env.imports))
    body = {"views": ["back", "iso"], "display": {"legend": {"mode": "fixed", "min": -1.5, "max": 300}}}
    assert env.c.post(f"{API}/jobs/{jid}/capture", headers=GW, json=body).status_code == 403          # power 이상
    r = env.c.post(f"{API}/jobs/{jid}/capture", headers=PW, json={"views": ["iso", "iso"]})
    assert r.status_code == 422
    r = env.c.post(f"{API}/jobs/{jid}/capture", headers=PW, json=body)
    assert r.status_code == 201, r.text
    rj = r.json()
    assert (rj["job_type"], rj["lane"], rj["stage"]) == ("CONTOUR_RECAPTURE", "LIGHT", 4)
    assert rj["params"] == {"source_job_id": jid, "views": ["back", "iso"],
                            "display": {"legend": {"mode": "fixed", "min": -1.5, "max": 300.0}}}
    r2 = env.c.post(f"{API}/jobs/{jid}/capture", headers=PW, json={})
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "RECAPTURE_ACTIVE"
    m = env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()
    assert m["recapture"] == {"job_id": rj["id"], "state": "QUEUED", "active": True} and m["can_recapture"] is False
    assert env.w.run_once_light() == "SUCCEEDED"
    rec = _capture_records(fake_record)[-1]
    rdir = env.predict_dir(jid) / "RESULT" / "media_recapture" / rj["id"]
    assert rec["cwd"] == str(rdir) and rec["settings"]["VIEWS"] == ["back", "iso"]
    assert (rec["settings"]["LEGMIN"], rec["settings"]["LEGMAX"]) == ("-1.5", "300")
    assert rec["settings"]["H3D_PATH"] == str(env.predict_dir(jid) / "RESULT" / "Face_Drop_0000_pred.h3d").replace("\\", "/")
    rd = env.job(rj["id"])
    assert rd["state"] == "SUCCEEDED" and [x["view"] for x in rd["result"]["media"]] == ["back", "iso"]
    m = env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()
    assert [(i["view"], i["job_id"] == rj["id"]) for i in m["items"]] == [
        ("iso", True), ("front", False), ("back", True), ("top", False), ("right", False)]
    assert m["display"]["legend"] == {"mode": "fixed", "min": -1.5, "max": 300.0} and m["can_recapture"] is True
    assert m["recapture"] == {"job_id": rj["id"], "state": "SUCCEEDED", "active": False}
    # 원래 예측의 파일은 그대로(다른 폴더)
    assert (env.predict_dir(jid) / "RESULT" / "media" / "iso.png").is_file()
    # 실패 → 작업 실패 CAPTURE_FAILED, 목록은 이전 결과 유지
    monkeypatch.setenv("FAKE_TOOL_MODE_CAPTURE", "fail")
    r = env.c.post(f"{API}/jobs/{jid}/capture", headers=PW, json={"views": ["left"]})
    assert r.status_code == 201
    assert env.w.run_once_light() == "FAILED"
    assert env.job(r.json()["id"])["failure_code"] == "CAPTURE_FAILED"
    assert len(env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()["items"]) == 5
    # 대상 오류: 예측 아님·없음
    r = env.c.post(f"{API}/jobs/{rj['id']}/capture", headers=PW, json={})
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["SUCCEEDED_PREDICT"]
    assert env.c.post(f"{API}/jobs/00000000-0000-0000-0000-000000000000/capture", headers=PW, json={}).status_code == 404
    assert env.c.get(f"{API}/jobs/{rj['id']}/media", headers=P).status_code == 404


def test_v3_s10_recapture_not_configured(predict_env, fake_record):
    env = predict_env()
    jid, _ = _predict(env, make_case(env.imports))
    env.lc.settings.capture.enabled = False
    r = env.c.post(f"{API}/jobs/{jid}/capture", headers=PW, json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CAPTURE_NOT_CONFIGURED"
    assert r.json()["detail"]["missing"] == ["capture.enabled"]


def test_v3_s10_batch_display_and_media_views(predict_env, fake_record, engine):
    """B: 배치 params display(범례 fixed)가 하위 예측 캡처에 쓰이고, 배치 행에 media_views."""
    from physicsai_core.db.repositories import predict_batches as pb_repo

    env = predict_env()
    ps = env.param_set()
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "multi_execution": 1, "source": {"kind": "table", "text": "THK_1\tN_RIB\n3.0\t4\n2.5\t5\n"},
        "display": {"legend": {"mode": "fixed", "min": 0, "max": 99}}}})
    assert r.status_code == 201, r.text
    job = r.json()
    bid = job["params"]["batch_id"]
    assert job["params"]["display"] == {"legend": {"mode": "fixed", "min": 0.0, "max": 99.0}}
    with engine.begin() as conn:                                        # BP_GEN·BP_ENQUEUE 흉내(워커 S9 몫)
        b = pb_repo.get(conn, bid)
        for row in pb_repo.runs(conn, bid):
            pb_repo.set_run(conn, bid, row["doe_no"], gen_state="DONE")
        kids = pb_repo.enqueue_children(conn, bid, batch_dir=str(env.sroot / b["dir_rel"]))
        conn.execute(text("update jobs set state='SUCCEEDED', holds_slot=false, queue_seq=null, finished_at=now() where id=:i"),
                     {"i": b["job_id"]})
    case = Path(kids[0]["params"]["input_path"])
    case.mkdir(parents=True, exist_ok=True)
    for name, body in (("Face_Drop_0000.rad", "/BEGIN\n"), ("part.inc", "/NODE\n")):
        (case / name).write_text(body)
    with engine.begin() as conn:  # 하위 params의 입력 확인 값(워커 S9 병합 전 기준 PR_PREP가 비교한다)
        conn.execute(text("update jobs set params = params || cast(:p as jsonb) where id=:i"),
                     {"p": json.dumps({"input_kind": "dir", "starter_name": "Face_Drop_0000.rad"}), "i": kids[0]["id"]})
    st_ = env.w.run_once_slot()
    assert st_ == "SUCCEEDED", [(s["step_key"], s["state"], s["failure_code"], s["failure_message"]) for s in env.job(kids[0]["id"])["steps"]]
    st = _capture_records(fake_record)[-1]["settings"]
    assert (st["LEGMIN"], st["LEGMAX"], st["VIEWS"]) == ("0", "99", VIEWS4)
    d = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert [(r["doe_no"], r["media_views"]) for r in d["rows"]] == [(1, VIEWS4), (2, [])]
    assert ps["id"] == job["params"]["param_set_id"]
