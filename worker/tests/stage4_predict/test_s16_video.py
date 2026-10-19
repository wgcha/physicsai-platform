"""S16 V3 영상(phase3 §21.4): V3-S16-20(TCL VID_SCOPE·파일 확인), V3-S16-21(워커 영상 판정·video_error·extra_meta),
V3-S16-22(가짜 ffmpeg 변환·가짜 ffprobe), V3-S16-24(media API 새 필드)."""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from physicsai_test_support import API, H, read_record

from .test_predict_prepared import make_case

P = H("tok-power")
REPO = Path(__file__).resolve().parents[3]
TCL = REPO / "resources" / "hyperview" / "contour_capture.tcl"
VIEWS4 = ["iso", "front", "top", "right"]


def _predict(env, case: Path) -> tuple[str, dict]:
    j = env.submit("PREDICT", {"input_mode": "prepared", "input_path": str(case)})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    return j["id"], env.job(j["id"])


def _codes(jd: dict) -> list[str]:
    return [w["code"] for w in jd["warnings"]]


def _videos(engine, job_id: str) -> list[dict]:
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(
            "select rel_path, content_type, size, meta from artifacts where job_id=:j and kind='CONTOUR_VIDEO' order by rel_path"),
            {"j": job_id})]


# ---- V3-S16-20 TCL ---------------------------------------------------------------------------------

_STUB = r"""
set ::LOG [open [file join $::env(STUB_OUT) hwc_calls.txt] a]
proc _handle {name} { proc $name {args} "_method $name {*}\$args" }
proc _method {name args} {
    set m [lindex $args 0]
    if {[string match Get*Handle $m]} { _handle [lindex $args 1]; return "" }
    switch -- $m {
        GetActivePage - GetActiveWindow - GetActiveModel { return 1 }
        GetCurrentSubcase { return 1 }
        GetNumberOfSimulations { return 3 }
    }
    return ""
}
proc hwi {args} { if {[string match Get*Handle [lindex $args 0]]} { _handle [lindex $args 1] }; return "" }
proc hwc {args} {
    puts $::LOG $args
    if {[lrange $args 0 2] eq {save image window}} {
        set fh [open [lindex $args 3] wb]; puts -nonewline $fh PNG; close $fh
    }
    if {[lrange $args 0 1] eq {save animation}} {
        set mode $::env(STUB_MODE)
        if {$mode eq "error"} { error "encoder missing" }
        if {$mode eq "ok"} { set fh [open [lindex $args 3] wb]; puts -nonewline $fh MP4DATA; close $fh }
        if {$mode eq "zero"} { close [open [lindex $args 3] wb] }
    }
    return ""
}
source $::env(STUB_TCL)
"""


def _run_tcl(tmp_path: Path, mode: str, scope: str | None) -> tuple[str, str, list[str]]:
    from physicsai_core.stage4_predict.contour_capture import settings_text

    tclsh = shutil.which("tclsh") or shutil.which("tclsh8.6")
    work = tmp_path / f"w_{mode}_{scope}"
    work.mkdir()
    shutil.copyfile(TCL, work / "contour_capture.tcl")
    h3d = work / "pred.h3d"
    h3d.write_bytes(b"h3d")
    (work / "capture_settings.tcl").write_text(settings_text(
        h3d_path=str(h3d), out_dir=str(work), display={"field": "S", "legend": {"mode": "auto"}}, views=["iso"],
        save_video=True, video_ext="mp4", use_last=True, video_scope=scope), encoding="ascii")
    (work / "stub.tcl").write_text(_STUB, encoding="utf-8")
    env = {**os.environ, "STUB_OUT": str(work), "STUB_MODE": mode, "STUB_TCL": str(work / "contour_capture.tcl")}
    p = subprocess.run([tclsh, str(work / "stub.tcl")], cwd=work, env=env, capture_output=True, timeout=60,
                       encoding="utf-8", errors="replace")
    calls = (work / "hwc_calls.txt").read_text(encoding="utf-8").splitlines()
    return p.stdout, (work / "capture_result.txt").read_text(encoding="utf-8"), calls


def test_v3_s16_20_settings_vid_scope_escape():
    from physicsai_core.stage4_predict.contour_capture import settings_text

    base = dict(h3d_path="/a/p.h3d", out_dir="/a/m", display={"field": "S"}, views=["iso"], save_video=True, video_ext="mp4",
                use_last=True)
    assert "VID_SCOPE" not in settings_text(**base)                       # 인자 없음 = 줄 없음(기존 골든 유지, TCL 기본 page)
    assert 'set VID_SCOPE  "window"' in settings_text(**base, video_scope="window").splitlines()
    assert 'set VID_SCOPE  "page"' in settings_text(**base, video_scope='page"; exit').splitlines()  # 허용 밖 값 → page
    t = TCL.read_text(encoding="utf-8")
    assert "hwc save animation window" in t and "hwc save animation page" in t
    assert "ERROR: 동영상 파일 없음 - $vid_path" in t and "SUCCESS: 동영상 저장 완료" in t and "ERROR: 동영상 저장 실패" in t
    assert "파일이 만들어지지 않았습니다(HyperView 성공 보고)" in t


@pytest.mark.skipif(not (shutil.which("tclsh") or shutil.which("tclsh8.6")), reason="tclsh 없음 — 문자열 골든만(위 시험)")
@pytest.mark.parametrize("mode,scope,vid,log,err", [
    ("ok", "window", "1", "SUCCESS: 동영상 저장 완료", ""),
    ("ok", None, "1", "SUCCESS: 동영상 저장 완료", ""),
    ("no_file", "page", "0", "ERROR: 동영상 파일 없음", "video: 파일이 만들어지지 않았습니다(HyperView 성공 보고)"),
    ("zero", "page", "0", "ERROR: 동영상 파일 없음", "video: 파일이 만들어지지 않았습니다(HyperView 성공 보고)"),
    ("error", "page", "0", "ERROR: 동영상 저장 실패 - encoder missing", "video: encoder missing"),
])
def test_v3_s16_20_tcl_video_file_check(tmp_path, mode, scope, vid, log, err):
    out, result, calls = _run_tcl(tmp_path, mode, scope)
    anim = [c for c in calls if c.startswith("save animation")]
    assert len(anim) == 1 and anim[0].split()[2] == (scope or "page"), calls
    assert log in out, out
    row = [ln for ln in result.splitlines() if ln.startswith("VIEW=")][0].split("=", 1)[1].split("|")
    assert row[:5] == ["iso", "1", "iso.png", vid, "iso.mp4"] and row[5].rstrip(";") == err, row
    assert "STATUS=OK" in result


# ---- V3-S16-21 워커 영상 판정 ------------------------------------------------------------------------


def test_v3_s16_21_reason_order():
    from physicsai_worker.steps.stage4_predict.capture import _video_missing_reason as r

    assert r({"error": "image: x; video: enc fail", "video": "FAIL"}, exists=False, timed_out=True, rc=1) == "video: enc fail"
    assert r({"video": "OK"}, exists=False, timed_out=True, rc=0) == "파일이 만들어지지 않았습니다(HyperView 성공 보고)"
    assert r({}, exists=False, timed_out=True, rc=0) == "시간 초과"
    assert r({}, exists=True, timed_out=False, rc=0) == "동영상 파일이 0바이트입니다"
    assert r({}, exists=False, timed_out=False, rc=3) == "동영상 파일 없음(종료코드 3)"


@pytest.mark.parametrize("mode,reason", [
    ("no_video", "video: fake encoder missing"),
    ("no_file", "파일이 만들어지지 않았습니다(HyperView 성공 보고)"),
    ("zero_video", "파일이 만들어지지 않았습니다(HyperView 성공 보고)"),
])
def test_v3_s16_21_video_failed_warning_and_api(predict_env, fake_record, monkeypatch, mode, reason):
    monkeypatch.setenv("FAKE_TOOL_MODE_CAPTURE", mode)
    env = predict_env()
    jid, jd = _predict(env, make_case(env.imports))
    vw = [w for w in jd["warnings"] if w["code"] == "CAPTURE_VIDEO_FAILED"]
    assert len(vw) == 1 and vw[0]["message"].startswith("동영상 저장 실패 4/4 방향: iso: ") and reason in vw[0]["message"]
    assert "CAPTURE_FAILED" not in _codes(jd)                               # 이미지 규칙 불변
    res = jd["result"]
    assert res["capture"]["status"] == "OK" and all(m["video_error"] == reason and m["video_artifact_id"] is None
                                                     for m in res["media"])
    m = env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()
    assert [(i["video"], i["video_error"]) for i in m["items"]] == [(None, reason)] * 4


def test_v3_s16_21_video_off_no_warning_and_extra_meta(predict_env, fake_record, monkeypatch, engine):
    from physicsai_worker.steps.stage4_predict import capture as cap

    env = predict_env()
    env.lc.settings.capture.video = False
    jid, jd = _predict(env, make_case(env.imports))
    assert not [c for c in _codes(jd) if c.startswith("CAPTURE")] and all("video_error" not in m for m in jd["result"]["media"])
    env.lc.settings.capture.video = True
    monkeypatch.setattr(cap, "run_capture", functools.partial(cap.run_capture, extra_meta={"side": "fem", "fv_id": "fv-1"}))
    jid2, _ = _predict(env, make_case(env.imports, "case_B"))
    with engine.connect() as c:
        metas = [r.meta for r in c.execute(text("select meta from artifacts where job_id=:j and kind like 'CONTOUR_%'"), {"j": jid2})]
    assert len(metas) == 8 and all(m["side"] == "fem" and m["fv_id"] == "fv-1" and m["view"] in VIEWS4 for m in metas)


# ---- V3-S16-22 변환 ------------------------------------------------------------------------------------


def _ff(env, fake_tools, probe: bool = False):
    f = env.lc.settings.capture.ffmpeg
    f.exe = fake_tools["fake_ffmpeg"]
    if probe:
        f.probe_exe = fake_tools["fake_ffprobe"]


def test_v3_s16_22_transcode_ladder_first_within_target(predict_env, fake_record, fake_tools, monkeypatch, engine):
    monkeypatch.setenv("FAKE_FFMPEG_SIZES", "3000000,2000000,900000,500000")
    env = predict_env()
    _ff(env, fake_tools)
    jid, jd = _predict(env, make_case(env.imports))
    assert not [c for c in _codes(jd) if c.startswith("CAPTURE")], jd["warnings"]
    media = env.predict_dir(jid) / "RESULT" / "media"
    recs = [r for r in read_record(fake_record) if r["tool"] == "ffmpeg"]
    assert len(recs) == 3 * 4                                                # 방향마다 단계 1~3(3단계가 첫 ≤ target)
    a = recs[0]["argv"]
    raw = str(media / "raw" / "iso.mp4")
    tmpd = env.sroot / "logs" / jid / "tmp"
    assert os.path.samefile(a[0], fake_tools["fake_ffmpeg"]) and recs[0]["cwd"] == str(media)
    assert a[1:] == ["-hide_banner", "-loglevel", "error", "-y", "-i", raw, "-an", "-vf",
                     "scale=trunc(iw*1/2)*2:trunc(ih*1/2)*2,fps=15", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmpd / "iso.try1.mp4")]
    assert recs[1]["argv"][recs[1]["argv"].index("-crf") + 1] == "30" and "fps=12" in recs[1]["argv"][9]
    assert (media / "iso.mp4").stat().st_size == 900000 and (media / "raw" / "iso.mp4").stat().st_size == 64  # raw 보존
    assert sorted(p.name for p in tmpd.iterdir() if p.name.startswith("iso.")) == ["iso.try1.mp4", "iso.try2.mp4"]
    vids = _videos(engine, jid)
    assert len(vids) == 4 and all(v["content_type"] == "video/mp4" and v["size"] == 900000 for v in vids)
    assert vids[0]["meta"] == {"view": "front", "transcoded": True, "raw_rel": f"04_predict/{jid}/RESULT/media/raw/front.mp4",
                               "codec": "h264", "pix_fmt": "yuv420p", "playable": True}
    it = env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()["items"][0]["video"]
    assert (it["playable"], it["codec"], it["transcoded"]) == (True, "h264", True)


def test_v3_s16_22_all_over_target_smallest(predict_env, fake_record, fake_tools, monkeypatch):
    monkeypatch.setenv("FAKE_FFMPEG_SIZES", "3000000,2500000,1900000,2200000")
    env = predict_env()
    _ff(env, fake_tools)
    jid, jd = _predict(env, make_case(env.imports))
    w = [x for x in jd["warnings"] if x["code"] == "CAPTURE_VIDEO_OVER_TARGET"]
    assert len(w) == 1 and w[0]["message"].startswith("영상이 목표 크기(1.0 MB)를 넘습니다: iso 1.8 MB")
    assert (env.predict_dir(jid) / "RESULT" / "media" / "iso.mp4").stat().st_size == 1900000


@pytest.mark.parametrize("mode", ["fail", "no_output"])
def test_v3_s16_22_transcode_failure_registers_original(predict_env, fake_record, fake_tools, monkeypatch, engine, mode):
    monkeypatch.setenv("FAKE_TOOL_MODE_FFMPEG", mode)
    env = predict_env()
    _ff(env, fake_tools)
    jid, jd = _predict(env, make_case(env.imports))
    w = [x for x in jd["warnings"] if x["code"] == "CAPTURE_VIDEO_TRANSCODE_FAILED"]
    assert len(w) == 1 and w[0]["message"].startswith("영상 변환 실패 — 원본을 그대로 씁니다: iso: ")
    vids = _videos(engine, jid)
    assert len(vids) == 4 and all(v["rel_path"].endswith(f"RESULT/media/raw/{v['meta']['view']}.mp4") and v["size"] == 64
                                  for v in vids)
    assert all(v["meta"]["transcoded"] is False and v["meta"]["playable"] is None for v in vids)


def test_v3_s16_22_transcode_timeout(predict_env, fake_record, fake_tools, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_FFMPEG", "hang")
    monkeypatch.setenv("FAKE_FFMPEG_HANG_S", "60")
    env = predict_env()
    _ff(env, fake_tools)
    env.lc.settings.capture.views = ["iso"]
    env.lc.settings.capture.ffmpeg.timeout_s = 1
    jid, jd = _predict(env, make_case(env.imports))
    w = [x for x in jd["warnings"] if x["code"] == "CAPTURE_VIDEO_TRANSCODE_FAILED"]
    assert w and "iso: 시간 초과" in w[0]["message"]


def test_v3_s16_22_no_exe_skips_and_probe(predict_env, fake_record, fake_tools, monkeypatch, engine):
    env = predict_env()
    jid, jd = _predict(env, make_case(env.imports))                       # exe 빈 값 = 변환·확인 없음
    assert not [r for r in read_record(fake_record) if r["tool"] in ("ffmpeg", "ffprobe")]
    assert all(v["meta"] == {"view": v["meta"]["view"], "playable": None} for v in _videos(engine, jid))
    env.lc.settings.capture.ffmpeg.probe_exe = fake_tools["fake_ffprobe"]   # probe만
    monkeypatch.setenv("FAKE_FFPROBE_CODEC", "mpeg4")
    jid2, jd2 = _predict(env, make_case(env.imports, "case_B"))
    w = [x for x in jd2["warnings"] if x["code"] == "CAPTURE_VIDEO_NOT_PLAYABLE"]
    assert len(w) == 1 and w[0]["message"] == "브라우저가 재생하지 못할 수 있는 코덱(mpeg4) — ffmpeg 변환을 설정하세요"
    v = _videos(engine, jid2)[0]
    assert (v["meta"]["codec"], v["meta"]["pix_fmt"], v["meta"]["playable"]) == ("mpeg4", "yuv420p", False)
    pr = [r for r in read_record(fake_record) if r["tool"] == "ffprobe"][0]["argv"]
    assert pr[1:-1] == ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt", "-of", "default=nw=1"]
    item = env.c.get(f"{API}/jobs/{jid2}/media", headers=P).json()["items"][0]["video"]
    assert (item["playable"], item["codec"], item["transcoded"]) == (False, "mpeg4", False)
    monkeypatch.setenv("FAKE_FFPROBE_CODEC", "h264")
    jid3, jd3 = _predict(env, make_case(env.imports, "case_C"))
    assert "CAPTURE_VIDEO_NOT_PLAYABLE" not in _codes(jd3) and _videos(engine, jid3)[0]["meta"]["playable"] is True


def test_v3_s16_22_avi_fallback_and_over_target_without_transcode(predict_env, fake_record, monkeypatch, engine):
    monkeypatch.setenv("FAKE_CAPTURE_VIDEO_BYTES", str(2 * 1048576))
    env = predict_env()
    env.lc.settings.capture.video_ext = "avi"                             # allow_avi=false → 실제 mp4
    jid, jd = _predict(env, make_case(env.imports))
    rec = [r for r in read_record(fake_record) if r["tool"] == "hw_capture"][0]["settings"]
    assert rec["VID_EXT"] == "mp4" and rec["VID_SCOPE"] == "page" and jd["result"]["capture"]["video_ext"] == "mp4"
    w = [x for x in jd["warnings"] if x["code"] == "CAPTURE_VIDEO_OVER_TARGET"]
    assert len(w) == 1 and "iso 2.0 MB" in w[0]["message"]
    env.lc.settings.capture.allow_avi = True
    env.lc.settings.capture.video_scope = "window"
    monkeypatch.setenv("FAKE_CAPTURE_VIDEO_BYTES", "64")
    jid2, _ = _predict(env, make_case(env.imports, "case_B"))
    rec2 = [r for r in read_record(fake_record) if r["tool"] == "hw_capture"][-1]["settings"]
    assert rec2["VID_EXT"] == "avi" and rec2["VID_SCOPE"] == "window"
    v = _videos(engine, jid2)[0]
    assert v["content_type"] == "video/x-msvideo" and v["meta"]["playable"] is False
    item = env.c.get(f"{API}/jobs/{jid2}/media", headers=P).json()["items"][0]
    assert item["video"]["playable"] is False and item["video_error"] is None


# ---- V3-S16-24 media API 호환 -------------------------------------------------------------------------


def test_v3_s16_24_media_fields_legacy_rows(predict_env, fake_record, engine):
    env = predict_env()
    jid, _ = _predict(env, make_case(env.imports))
    with engine.begin() as c:                                               # S16 이전 행(meta = {view}만, gif)
        c.execute(text("update artifacts set meta=jsonb_build_object('view', meta->>'view') where job_id=:j"), {"j": jid})
    m = env.c.get(f"{API}/jobs/{jid}/media", headers=P).json()
    it = m["items"][0]
    assert (it["image"]["playable"], it["image"]["codec"], it["image"]["transcoded"]) == (True, None, False)
    assert (it["video"]["playable"], it["video"]["transcoded"], it["video_error"]) == (None, False, None)
    assert set(it["video"]) == {"artifact_id", "content_type", "size", "url", "download_url", "playable", "codec", "transcoded"}
