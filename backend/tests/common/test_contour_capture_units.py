"""phase3 §15 S10 컨투어 캡처 — 공용 단위: 설정·명령 템플릿·기능 판정, 표시 설정 검증·결정, capture_settings.tcl(이스케이프·공백·한글
경로), capture_result.txt 해석, 가짜 hw 설정 해석과의 왕복, (tclsh가 있으면) 실제 TCL 리소스를 흉내 hwc로 실행."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from physicsai_test_support import FAKE_TOOLS, REPO, make_phase2_settings

TCL = REPO / "resources" / "hyperview" / "contour_capture.tcl"


def _load(d):
    from physicsai_core.config import load_config_dict

    return load_config_dict(d, environ={})


@pytest.fixture()
def p2_dict(tmp_path, fake_tools):
    return make_phase2_settings(tmp_path, fake_tools)


# ---- 설정·명령·기능 ---------------------------------------------------------------------------------


def test_capture_config_defaults_ranges_and_example(p2_dict, tmp_path):
    import yaml

    lc = _load(p2_dict)
    assert lc.ok, lc.issues
    assert lc.settings.capture.model_dump() == {
        "enabled": True, "views": ["iso", "front", "top", "right"], "video": True, "video_ext": "mp4", "use_last": True,
        "default_field": "CornerStress", "default_component": "vonMises", "estimate_image_mb": 0.3, "estimate_video_mb": 1.0,
        "estimate_sec_per_view": 20, "estimate_sec_per_video": 40, "timeout_s": 1800, "max_video_bytes": 209715200}
    # 설정 파일에 commands.contour_capture가 없어도 기본 템플릿(기능 켬)
    assert lc.settings.commands.contour_capture == ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{capture_tcl}"]
    bad = (("views", []), ("views", ["iso", "iso"]), ("views", ["diag"]), ("video_ext", "mov"), ("default_field", 'a"b'),
           ("default_field", "Von|Mises"), ("default_field", "a\tb"), ("timeout_s", 0), ("max_video_bytes", 10),
           ("default_component", "a|b"), ("default_component", 'v"m'), ("default_component", "x" * 65),
           ("estimate_video_mb", -1), ("estimate_sec_per_view", float("inf")), ("estimate_image_mb", 5000))
    for k, v in bad:
        assert _load({**p2_dict, "capture": {k: v}}).error_keys() == [f"capture.{k}"], (k, v)
    assert _load({**p2_dict, "capture": {"timeout_s": None, "views": ["back"], "video_ext": "gif"}}).ok
    assert _load({**p2_dict, "capture": {"default_component": ""}}).ok                      # D3-54: 빈 값 = 성분 없음
    assert _load({**p2_dict, "capture": {"bogus": 1}}).error_keys()[0].startswith("capture")
    for v, ok in (("relative/x.tcl", False), ("/a b/x.tcl", False), (str(tmp_path / "x.tcl"), True)):
        res = {**p2_dict["resources"], "contour_capture_tcl": v}
        assert _load({**p2_dict, "resources": res}).ok is ok, v
    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    data["storage"]["ai_root"] = str(tmp_path)
    ex = _load(data)
    assert ex.ok, ex.issues
    assert ex.settings.capture.views == ["iso", "front", "top", "right"] and ex.settings.resources.contour_capture_tcl == ""
    assert ex.settings.commands.contour_capture == ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{capture_tcl}"]


def test_capture_template_render_golden():
    from physicsai_core.commands import render_argv, validate_template
    from physicsai_core.errors import StepFailure

    tpl = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{capture_tcl}"]
    assert validate_template("contour_capture", tpl) == [] and validate_template("contour_capture", None) == []
    assert validate_template("contour_capture", ["{hw}", "{extract_tcl}"]) != []                 # 허용 placeholder는 hw·capture_tcl만
    argv = render_argv("contour_capture", tpl, {"capture_tcl": "E:\\AI\\S1\\04_predict\\j\\RESULT\\media\\contour_capture.tcl"},
                       executables={"hw_exe_path": "C:\\Altair\\hw.exe"}, is_windows=True)
    assert argv == ["C:\\Altair\\hw.exe", "-clientconfig", "hwpost.dat", "-b", "-tcl",
                    "E:/AI/S1/04_predict/j/RESULT/media/contour_capture.tcl"]
    with pytest.raises(StepFailure):  # 명령 인자 경로 공백 금지(다른 hw TCL과 같은 규칙)
        render_argv("contour_capture", tpl, {"capture_tcl": "/a b/contour_capture.tcl"}, executables={"hw_exe_path": "/x/hw"})


def test_contour_capture_feature(p2_dict):
    from physicsai_core.features import feature_status

    on = _load(p2_dict).settings
    assert feature_status(on, False)["contour_capture"] == {"enabled": True, "missing": []}
    off = _load({**p2_dict, "capture": {"enabled": False}}).settings
    assert feature_status(off, False)["contour_capture"]["missing"] == ["capture.enabled"]
    nohw = _load({**p2_dict, "altair": {**p2_dict["altair"], "hw_exe_path": ""}}).settings
    assert feature_status(nohw, False)["contour_capture"]["missing"] == ["altair.hw_exe_path"]
    nocmd = _load({**p2_dict, "commands": {**(p2_dict.get("commands") or {}), "contour_capture": None}}).settings
    assert feature_status(nocmd, False)["contour_capture"]["missing"] == ["commands.contour_capture"]
    gone = _load({**p2_dict, "resources": {**p2_dict["resources"], "contour_capture_tcl": "/no/such/contour_capture.tcl"}}).settings
    assert feature_status(gone, False)["contour_capture"]["missing"] == ["resources.contour_capture_tcl"]


def test_repo_resource_is_user_tcl_with_two_changes():
    """출처 주석, 사용자 설정 블록 → settings source, VIEWS 반복·고정 파일 이름·capture_result.txt·exit."""
    from physicsai_core.config.schema_capture import repo_capture_tcl

    assert repo_capture_tcl() == str(TCL).replace("\\", "/")
    t = TCL.read_text(encoding="utf-8")
    assert "사용자 제공 이슈 #2, HyperView 26.1 확인" in t
    assert "source [file join [file dirname [info script]] capture_settings.tcl]" in t
    assert 'set H3D_PATH    "C:/' not in t and "foreach VIEW $VIEWS" in t
    assert 'set png_name "${VIEW}.png"' in t and 'set vid_name "${VIEW}.${VID_EXT}"' in t
    assert "capture_result.txt" in t and "catch { exit }" in t
    for keep in ("hwc open animation modelandresult", "result scalar load type=", "hwc save image window", "hwc save animation page",
                 "hwc view orientation $VIEW | view fit", "legendmin $LEGMIN", "hide component all"):
        assert keep in t, keep


# ---- 표시 설정 --------------------------------------------------------------------------------------


def test_validate_display():
    from physicsai_core.stage4_predict.contour_capture import validate_display

    assert validate_display(None) == [] and validate_display({}) == []
    ok = {"field": "Stress", "component": "", "avgmode": "simple", "comps": ["PART_1", "쿠션 A"],
          "legend": {"mode": "fixed", "min": 0, "max": 150.5}, "views": ["iso", "back"]}
    assert validate_display(ok) == []
    bad = [({"field": 'a"b'}, ["display", "field"]), ({"field": ""}, ["display", "field"]), ({"comps": ["x[1]"]}, ["display", "comps", 0]),
           ({"avgmode": "avg"}, ["display", "avgmode"]), ({"legend": {"mode": "fixed", "min": 1}}, ["display", "legend"]),
           ({"legend": {"mode": "fixed", "min": 2, "max": 1}}, ["display", "legend"]), ({"views": ["iso", "iso"]}, ["display", "views"]),
           ({"views": []}, ["display", "views"]), ({"bogus": 1}, ["display", "bogus"]),
           ({"legend": {"mode": "auto", "min": float("nan")}}, ["display", "legend", "min"])]
    for d, loc in bad:
        errs = validate_display(d)
        assert errs and errs[0]["loc"] == loc, (d, errs)
    # D3-53: hwc 명령 구분자 '|'는 모든 문자열 값에서 거부(field·component·comps), 열거형(avgmode·views·legend.mode)도 거부
    pipe = [({"field": "Von|Mises"}, ["display", "field"]), ({"component": "a|b"}, ["display", "component"]),
            ({"comps": ["P1", "x|y"]}, ["display", "comps", 1]), ({"avgmode": "simple|max"}, ["display", "avgmode"]),
            ({"views": ["iso|top"]}, ["display", "views"]), ({"legend": {"mode": "auto|fixed"}}, ["display", "legend", "mode"])]
    for d, loc in pipe:
        errs = validate_display(d)
        assert errs and errs[0]["loc"] == loc, (d, errs)
    assert "|" in validate_display({"field": "a|b"})[0]["msg"]


def test_resolve_display_order():
    from physicsai_core.config import Settings
    from physicsai_core.stage4_predict.contour_capture import resolve_display

    cfg = Settings().capture
    d, src = resolve_display(cfg, None)
    assert src == "config" and d == {"field": "CornerStress", "component": "vonMises", "avgmode": "", "comps": [],
                                     "legend": {"mode": "auto", "min": None, "max": None}, "views": ["iso", "front", "top", "right"]}
    ps = {"responses": [{"name": "M", "spec": None}, {"name": "S", "spec": {"datatype": "Stress", "component": "vonMises"}}]}
    d, src = resolve_display(cfg, ps)
    assert (src, d["field"], d["component"]) == ("response", "Stress", "vonMises")
    ps["display"] = {"field": "Displacement", "views": ["top"]}
    d, src = resolve_display(cfg, ps)
    assert (src, d["field"], d["component"], d["views"]) == ("template", "Displacement", "", ["top"])   # field를 정하면 component도 그 층
    batch = {"legend": {"mode": "fixed", "min": 0.0, "max": 200.0}}
    d, src = resolve_display(cfg, ps, batch, {"component": "Mag"}, None)
    assert (src, d["field"], d["component"], d["legend"]) == ("template", "Displacement", "Mag",
                                                              {"mode": "fixed", "min": 0.0, "max": 200.0})
    d, src = resolve_display(cfg, ps, batch, {"field": "Von Mises", "legend": {"mode": "auto"}})
    assert (src, d["field"], d["legend"]["mode"], d["views"]) == ("params", "Von Mises", "auto", ["top"])
    # D3-54: 성분이 비었고 field가 capture.default_field(CornerStress)일 때만 capture.default_component
    corner = {"responses": [{"name": "C", "spec": {"datatype": "CornerStress", "component": ""}}]}
    assert resolve_display(cfg, corner)[0]["component"] == "vonMises"
    assert resolve_display(cfg, corner, {"field": "CornerStress", "component": "P1"})[0]["component"] == "P1"
    assert resolve_display(cfg, ps, {"field": "Stress"})[0]["component"] == ""                  # 다른 field는 그대로 빈 값
    assert resolve_display(cfg.model_copy(update={"default_component": ""}), corner)[0]["component"] == ""


# ---- capture_settings.tcl ------------------------------------------------------------------------


def test_tcl_quote_escapes_and_unicode():
    from physicsai_core.stage4_predict.contour_capture import tcl_list, tcl_quote

    assert tcl_quote("") == '""'
    assert tcl_quote('E:/AI 루트/a"b$c[d]{e};\\f') == '"E:/AI \\ub8e8\\ud2b8/a\\"b\\$c\\[d\\]\\{e\\}\\;\\\\f"'
    assert tcl_quote("x\ny") == '"x\\u000ay"' and tcl_quote("😀") == '"\\U0001f600"'
    assert tcl_list([]) == "[list]" and tcl_list(["PART 1", "쿠션"]) == '[list "PART 1" "\\ucfe0\\uc158"]'


def _settings(tmp: Path) -> tuple[str, dict]:
    from physicsai_core.stage4_predict.contour_capture import settings_text

    h3d = str(tmp / "예측 결과" / "Face_Drop_0000_pred.h3d")
    out = str(tmp / "예측 결과" / "media")
    disp = {"field": "Von Mises", "component": "", "avgmode": "maximum", "comps": ["PART 1", "쿠션{A}"],
            "legend": {"mode": "fixed", "min": 0, "max": 152.25}}
    return settings_text(h3d_path=h3d, out_dir=out, display=disp, views=["iso", "front"], save_video=True, video_ext="mp4",
                         use_last=True), {"h3d": h3d, "out": out}


def test_settings_text_golden_ascii(tmp_path):
    from physicsai_core.stage4_predict.contour_capture import settings_text

    text = settings_text(h3d_path="E:\\AI\\S1\\04_predict\\j\\RESULT\\Face_Drop_0000_pred.h3d", out_dir="E:\\AI\\S1\\04_predict\\j\\RESULT\\media",
                         display={"field": "Stress", "component": "vonMises", "legend": {"mode": "auto"}}, views=["iso", "top"],
                         save_video=False, video_ext="avi", use_last=False)
    assert text.splitlines()[2:] == [
        'set H3D_PATH   "E:/AI/S1/04_predict/j/RESULT/Face_Drop_0000_pred.h3d"',
        'set OUTDIR     "E:/AI/S1/04_predict/j/RESULT/media"',
        'set FIELD      "Stress"', 'set DCOMP      "vonMises"', 'set AVGMODE    ""', "set USE_LAST   0",
        'set LEGMIN     ""', 'set LEGMAX     ""', "set SAVE_VIDEO 0", 'set VID_EXT    "avi"', "set COMPS      [list]",
        'set VIEWS      [list "iso" "top"]']
    text, _ = _settings(tmp_path)
    text.encode("ascii")  # 한글·공백 경로도 ASCII(\uXXXX) — HyperView 시스템 인코딩과 무관
    assert 'set LEGMIN     "0"' in text and 'set LEGMAX     "152.25"' in text


def test_settings_roundtrip_with_fake_parser(tmp_path):
    """가짜 hw가 쓰는 Tcl 리터럴 해석기로 되읽으면 원래 값(공백·한글·괄호)."""
    sys.path.insert(0, str(FAKE_TOOLS))
    try:
        import fake_hw_capture
    finally:
        sys.path.remove(str(FAKE_TOOLS))
    text, p = _settings(tmp_path)
    st = fake_hw_capture.parse_settings(text)
    assert st["H3D_PATH"] == p["h3d"].replace("\\", "/") and st["OUTDIR"] == p["out"].replace("\\", "/")
    assert st["COMPS"] == ["PART 1", "쿠션{A}"] and st["VIEWS"] == ["iso", "front"] and st["AVGMODE"] == "maximum"


def test_parse_result():
    from physicsai_core.stage4_predict.contour_capture import parse_result

    r = parse_result("\ufeff# capture_result 1\nSTATUS=OK\nVIEW=iso|1|iso.png|1|iso.mp4|\n"
                     "VIEW=top|0|top.png|0|top.mp4|image: 저장 실패; video: x\nVIEW=left|1|left.png|-||\n")
    assert r["status"] == "OK" and r["message"] is None
    assert r["views"]["iso"] == {"image": True, "image_file": "iso.png", "video": "OK", "video_file": "iso.mp4", "error": None}
    assert r["views"]["top"]["image"] is False and r["views"]["top"]["video"] == "FAIL" and "저장 실패" in r["views"]["top"]["error"]
    assert r["views"]["left"]["video"] == "SKIP"
    assert parse_result("STATUS=OPEN_ERROR\nMESSAGE=cannot open\n") == {"status": "OPEN_ERROR", "message": "cannot open", "views": {}}


# ---- 실제 TCL(흉내 hwc·hwi, tclsh 있을 때) --------------------------------------------------------------------

MOCK = r'''
set ::LOGF [open [file join [file dirname [info script]] hwc.log] w]
fconfigure $::LOGF -encoding utf-8
proc logline {s} { puts $::LOGF $s; flush $::LOGF }
proc hwc {args} {
    logline "hwc $args"
    if {[lindex $args 0] eq "open" && [info exists ::env(MOCK_OPEN_FAIL)]} { error "cannot open file" }
    if {[lrange $args 0 2] eq {save image window}} {
        if {[info exists ::env(MOCK_IMAGE_FAIL)]} { error "image failed" }
        set f [open [lindex $args 3] w]; puts $f png; close $f
    }
    if {[lrange $args 0 2] eq {save animation page}} { set f [open [lindex $args 3] w]; puts $f mp4; close $f }
    return ""
}
proc mkh {name} {
    proc $name {method args} {
        set me [lindex [info level 0] 0]
        if {[string match Get*Handle $method]} { mkh [lindex $args 0]; return "" }
        switch -- $method {
            GetActivePage - GetActiveWindow - GetActiveModel - GetCurrentSubcase { return 1 }
            GetNumberOfSimulations { return 5 }
            default { logline "$me $method $args"; return "" }
        }
    }
}
proc hwi {method name} { mkh $name }
source [lindex $argv 0]
'''


@pytest.mark.skipif(shutil.which("tclsh") is None and shutil.which("tclsh8.6") is None, reason="tclsh 없음(선택 시험)")
@pytest.mark.parametrize("mode", ["ok", "open_fail", "image_fail"])
def test_resource_tcl_runs_with_mock_hyperview(tmp_path, mode):
    from physicsai_core.stage4_predict.contour_capture import parse_result

    tclsh = shutil.which("tclsh") or shutil.which("tclsh8.6")
    text, p = _settings(tmp_path)
    media = Path(p["out"])
    media.mkdir(parents=True)
    Path(p["h3d"]).write_bytes(b"h3d")
    shutil.copyfile(TCL, media / "contour_capture.tcl")
    (media / "capture_settings.tcl").write_text(text, encoding="ascii")
    (media / "mock.tcl").write_text(MOCK, encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}  # 리눅스 tclsh 파일 이름 인코딩(Windows는 유니코드 API)
    if mode == "open_fail":
        env["MOCK_OPEN_FAIL"] = "1"
    if mode == "image_fail":
        env["MOCK_IMAGE_FAIL"] = "1"
    r = subprocess.run([tclsh, str(media / "mock.tcl"), str(media / "contour_capture.tcl")], cwd=str(tmp_path), env=env,
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    res = parse_result((media / "capture_result.txt").read_text(encoding="utf-8"))
    log = (media / "hwc.log").read_text(encoding="utf-8")
    if mode == "open_fail":
        assert res["status"] == "OPEN_ERROR" and "cannot open" in res["message"] and res["views"] == {}
        assert "save image" not in log
        return
    # 로그는 Tcl 목록 표기({…} = 한 인자): 한글·공백 경로·필드 이름이 각각 한 인자로 넘어간다
    h3d = p["h3d"].replace("\\", "/")  # 설정 파일 경로는 `/` 표기(§15.1) — Windows도 같다
    assert f"hwc open animation modelandresult {{{h3d}}} {{{h3d}}}" in log
    assert "hwc result scalar load type= {Von Mises} avgmode= maximum displayed=true" in log
    assert "hwc result scalar legendminenabled true | result scalar legendmin 0" in log
    assert "hwc result scalar legendmaxenabled true | result scalar legendmax 152.25" in log
    assert "hwc show component {PART 1}" in log and "hwc show component 쿠션{A}" in log
    assert log.index("hwc view orientation iso | view fit") < log.index("hwc view orientation front | view fit")
    assert "hvResult SetCurrentSimulation 4" in log
    if mode == "ok":
        assert res["status"] == "OK" and sorted(res["views"]) == ["front", "iso"]
        assert res["views"]["iso"] == {"image": True, "image_file": "iso.png", "video": "OK", "video_file": "iso.mp4", "error": None}
        assert sorted(x.name for x in media.iterdir() if x.suffix in (".png", ".mp4")) == ["front.mp4", "front.png", "iso.mp4", "iso.png"]
    else:
        assert res["status"] == "SAVE_ERROR" and res["views"]["iso"]["image"] is False
        assert "image failed" in res["views"]["iso"]["error"] and res["views"]["iso"]["video"] == "OK"
    json.dumps(res)
