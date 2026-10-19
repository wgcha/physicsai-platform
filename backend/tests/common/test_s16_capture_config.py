"""S16 V3 설정(phase3 §21.4.4): V3-S16-23 — capture.ffmpeg 검증·avi 대체 경고·video_scope·target·/status.capture 새 필드,
파생 영상 템플릿 펼침(shell=False argv)."""

from __future__ import annotations

import pytest

from physicsai_test_support import make_phase2_settings


def _load(d):
    from physicsai_core.config import load_config_dict

    return load_config_dict(d, environ={})


@pytest.fixture()
def p2(tmp_path, fake_tools):
    return make_phase2_settings(tmp_path, fake_tools)


def test_v3_s16_23_ffmpeg_validation(p2, tmp_path):
    ok = _load({**p2, "capture": {"ffmpeg": {"exe": str(tmp_path / "ffmpeg"), "probe_exe": ""}}})
    assert ok.ok, ok.issues
    assert "capture.ffmpeg.exe" in [w.key for w in ok.warnings]                    # 파일 없음 = 경고(변환 건너뜀)
    base = {"args": ["-i", "{video_in}", "{video_out}"]}
    bad = [
        ({"exe": "relative/ffmpeg"}, "capture.ffmpeg.exe"),
        ({"exe": "/a b/ffmpeg"}, "capture.ffmpeg.exe"),
        ({"probe_exe": "/x/ff&probe"}, "capture.ffmpeg.probe_exe"),
        ({"args": []}, "capture.ffmpeg.args"),
        ({"args": ["-i", "{video_in}"]}, "capture.ffmpeg.args"),                      # {video_out} 없음
        ({"args": ["{video_in}", "{video_in}", "{video_out}"]}, "capture.ffmpeg.args"),  # 2번
        ({"args": ["{video_in}", "{video_out}", "{bogus}"]}, "capture.ffmpeg.args"),
        ({"args": ["{video_in}", "{video_out}", "a\tb"]}, "capture.ffmpeg.args"),
        ({"args": ["{video_in}", "{video_out}", "x" * 257]}, "capture.ffmpeg.args"),
        ({"args": ["{video_in}", "{video_out}"] + ["-y"] * 63}, "capture.ffmpeg.args"),
        ({"probe_args": ["{video_out}"]}, "capture.ffmpeg.probe_args"),
        ({"ladder": []}, "capture.ffmpeg.ladder"),
        ({"ladder": [{"scale": 0.05, "crf": 28, "fps": 15}]}, "capture.ffmpeg.ladder.0"),
        ({"ladder": [{"scale": 1.0, "crf": 52, "fps": 15}]}, "capture.ffmpeg.ladder.0"),
        ({"ladder": [{"scale": 1.0, "crf": 28, "fps": 61}]}, "capture.ffmpeg.ladder.0"),
        ({"ladder": [{"scale": 1.0, "crf": 28, "fps": 15}] * 9}, "capture.ffmpeg.ladder"),
        ({"timeout_s": 0}, "capture.ffmpeg.timeout_s"),
    ]
    for ff, key in bad:
        assert _load({**p2, "capture": {"ffmpeg": {**base, **ff}}}).error_keys() == [key], (ff, key)
    assert _load({**p2, "capture": {"ffmpeg": base}}).ok
    for k, v, key in (("video_scope", "screen", "capture.video_scope"), ("video_target_bytes", 1000, "capture.video_target_bytes"),
                      ("video_target_bytes", 209715201, "capture.video_target_bytes")):
        assert _load({**p2, "capture": {k: v}}).error_keys() == [key], (k, v)
    assert _load({**p2, "capture": {"video_scope": "window", "video_target_bytes": 65536}}).ok


def test_v3_s16_23_avi_fallback_warning(p2):
    from physicsai_core.config.schema_capture import AVI_FALLBACK_MESSAGE, effective_video_ext

    lc = _load({**p2, "capture": {"video_ext": "avi"}})
    assert lc.ok and [(w.key, w.message) for w in lc.warnings if w.key.startswith("capture")] == [
        ("capture.video_ext", AVI_FALLBACK_MESSAGE)]
    assert effective_video_ext(lc.settings) == "mp4"
    lc2 = _load({**p2, "capture": {"video_ext": "avi", "allow_avi": True}})
    assert lc2.ok and not [w for w in lc2.warnings if w.key.startswith("capture")] and effective_video_ext(lc2.settings) == "avi"
    assert effective_video_ext(_load({**p2, "capture": {"video_ext": "gif"}}).settings) == "gif"


def test_v3_s16_23_video_argv_render(p2, fake_tools):
    from physicsai_core.commands import TEMPLATE_SPECS, render_video_argv, video_executables, video_template
    from physicsai_core.errors import StepFailure

    assert "video_transcode" not in TEMPLATE_SPECS                                   # commands 절 키가 아님(파생)
    s = _load(p2).settings
    assert video_template(s.capture, "video_transcode") is None and video_template(s.capture, "video_probe") is None
    s.capture.ffmpeg.exe = fake_tools["fake_ffmpeg"]
    tmpl = video_template(s.capture, "video_transcode")
    argv = render_video_argv("video_transcode", tmpl, {"video_in": "/s/raw/iso.mp4", "video_out": "/s/tmp/iso.try1.mp4",
                                                        "scale": "0.5", "crf": "32", "fps": "10"},
                             executables=video_executables(s.capture), is_windows=False)
    assert argv[0] == fake_tools["fake_ffmpeg"] and argv[argv.index("-i") + 1] == "/s/raw/iso.mp4"
    assert "scale=trunc(iw*0.5/2)*2:trunc(ih*0.5/2)*2,fps=10" in argv and argv[-1] == "/s/tmp/iso.try1.mp4"
    with pytest.raises(StepFailure) as ei:
        render_video_argv("video_transcode", tmpl, {"video_in": "/s/a b.mp4", "video_out": "/o", "scale": "1", "crf": "1",
                                                    "fps": "1"}, executables=video_executables(s.capture), is_windows=False)
    assert ei.value.code == "INPUT_INVALID"
    with pytest.raises(StepFailure) as ei:
        render_video_argv("video_probe", None, {}, executables={}, is_windows=False)
    assert ei.value.code == "TEMPLATE_NOT_CONFIGURED"


def test_v3_s16_23_status_capture_fields(client, app_ctx, fake_tools):
    from physicsai_test_support import API, H

    cap = client.get(f"{API}/status", headers=H("tok-power")).json()["capture"]
    assert (cap["video_target_bytes"], cap["transcode"], cap["video_ext_effective"]) == (1048576, False, "mp4")
    s = app_ctx.settings
    s.capture.ffmpeg.exe = fake_tools["fake_ffmpeg"]
    s.capture.video_ext = "avi"
    cap = client.get(f"{API}/status", headers=H("tok-power")).json()["capture"]
    assert (cap["transcode"], cap["video_ext_effective"], cap["video_ext"]) == (True, "mp4", "avi")


def test_v3_s16_fem_verify_config(p2):
    """phase3 §21.3.10: fem_verify 절 기본값·검증(field_map 문자 규칙, 범위, dir_name), 예시 yaml이 그대로 통과."""
    import yaml

    from physicsai_test_support import REPO

    lc = _load(p2)
    f = lc.settings.fem_verify
    assert (f.enabled, f.dir_name, f.max_active, f.field_map, f.legend_subcase, f.auto_isolate_cushion) == (
        True, "04_verify", 4, {}, 1, True)
    assert (f.zero_tol, f.max_assem_files, f.max_assem_bytes, f.include_scan_max_bytes, f.max_pred_h3d_copy_bytes) == (
        1e-12, 500, 2147483648, 16777216, 4294967296)
    bad = [({"max_active": 0}, "fem_verify.max_active"), ({"max_active": 21}, "fem_verify.max_active"),
           ({"field_map": {"CornerStress": 'a"b'}}, "fem_verify.field_map"), ({"field_map": {"x|y": "z"}}, "fem_verify.field_map"),
           ({"dir_name": "04_predict"}, "fem_verify.dir_name"), ({"dir_name": "a b"}, "fem_verify.dir_name"),
           ({"legend_subcase": 0}, "fem_verify.legend_subcase"), ({"zero_tol": -1}, "fem_verify.zero_tol"),
           ({"max_assem_files": 0}, "fem_verify.max_assem_files")]
    for v, key in bad:
        assert _load({**p2, "fem_verify": v}).error_keys() == [key], (v, key)
    ok = _load({**p2, "fem_verify": {"field_map": {"CornerStress": "Element Stresses (2D & 3D)"}}})
    assert ok.ok and ok.settings.fem_verify.field_map["CornerStress"] == "Element Stresses (2D & 3D)"
    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert data["fem_verify"]["dir_name"] == "04_verify" and data["capture"]["ffmpeg"]["exe"] == ""
