"""v0.2.16 ③-1 데이터 점검 코어(data-health.md) — 통계(견고 z)·Radioss 출력 꼬리·판정·설정 검증·TCL(정적·tclsh 가짜 hw)·step 자원."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from physicsai_core.config.schema import Settings
from physicsai_core.config.schema_data_health import DataHealthCfg, validate_data_health
from physicsai_core.data_health import report as rp
from physicsai_core.data_health import frame_probe as fp
from physicsai_core.data_health import metrics as mx
from physicsai_core.data_health.stats import summarize
from physicsai_core.job_types import JOB_TYPES
from physicsai_core.parsers import radioss_out as ro
from physicsai_test_support import REPO

TCL = REPO / "resources" / "hyperview" / "h3d_frame_probe.tcl"
STUB = REPO / "backend" / "tests" / "fake_tools" / "hw_tcl_stub.tcl"
D = DataHealthCfg()


def test_robust_z_flags_outlier_and_small_n_skips():
    vals = [10.0, 10.1, 9.9, 10.05, 9.95, 10.0, 10.02, 9.98, 25.0]
    st = summarize(vals, D.min_n)
    assert not st.skipped and abs(st.zr[-1]) > D.robust_z and all(abs(z) < D.robust_z for z in st.zr[:-1])
    assert summarize(vals[:5], D.min_n).skipped  # 표본 부족은 판정하지 않는다(SKIP_SMALL_N)
    same = summarize([3.0] * 9, D.min_n)
    assert same.scale_kind == "ZERO" and all(z in (0.0, None) for z in same.zr)  # 전부 같은 값 — 0으로 나누지 않는다


def test_engine_tail_parses_termination_and_last_cycle(tmp_path):
    p = tmp_path / "m_0001.out"
    p.write_text("x\n" * 5000 + " ** CYCLE TIME\n   1000   1.5E-02   1.0E-03   SHELL 12   3.2%   0.0\n NORMAL TERMINATION\n", encoding="utf-8")
    t = ro.read_engine_tail(str(p), limit=2048, normal_regex=D.normal_regex, error_regex=D.error_regex, cycle_regex=D.cycle_regex)
    assert t.term == ro.NORMAL and t.omitted_bytes > 0  # 꼬리만 읽는다
    assert t.cycle is not None and abs(t.cycle.time - 0.015) < 1e-12 and abs(t.cycle.err - 3.2) < 1e-9


def test_starter_mass_stops_at_first_match_and_respects_limit(tmp_path):
    p = tmp_path / "s_0000.out"
    p.write_text("a\n" * 10 + "  TOTAL MASS = 1.25E+01\n" + "b\n" * 10, encoding="utf-8")
    assert ro.starter_total_mass(str(p)) == 12.5
    with pytest.raises(ro.ScanTooLarge):
        ro.starter_total_mass(str(p), max_bytes=4)


def test_judge_sound_uses_config_thresholds_only():
    vals = {"term": "NORMAL", "energy_err_pct": D.energy_error_pct_max + 1, "added_mass": 0.0}
    res = mx.judge_sound(vals, {}, D)
    assert res["energy_err_pct"].status == "FAIL" and res["term"].status == "OK"
    loose = D.model_copy(update={"energy_error_pct_max": 99.0})
    assert mx.judge_sound(vals, {}, loose)["energy_err_pct"].status == "OK"


def _row(i, frames, t_last):
    return {"file_rel": f"r{i}/a.h3d", "run_key": f"r{i}", "doe_id": "D", "params": {"x": float(i)}, "values": {"frames": frames, "t_last": t_last},
            "na": {}, "aux": {}, "t_end": None}


def test_score_required_first_and_references():
    rows = [_row(i, 5, 2.0) for i in range(6)] + [_row(6, 3, 1.0)]
    sc = rp.score(rows, [], D)
    assert sc.runs[0]["file_rel"] == "r6/a.h3d" and sc.runs[0]["required"] and sc.runs[0]["score"] >= rp.REQUIRED_SCORE
    assert sc.summary["frames_ref"] == 5 and sc.summary["ref_source"] == "mode" and sc.summary["n_required"] == 1
    d2 = D.model_copy(update={"expected_frames": 3})  # 설정 기대값이 최빈값보다 우선
    s2 = rp.score(rows, [], d2)
    assert s2.summary["ref_source"] == "config" and s2.summary["n_required"] == 6
    tie = rp.score([_row(0, 5, 2.0), _row(1, 4, 2.0), _row(2, 5, 2.0), _row(3, 4, 2.0)], [], D)
    assert any(w["code"] == "DH_REF_TIE" for w in tie.summary["warnings"]) and tie.summary["n_required"] == 0


def test_config_validation_rejects_bad_values():
    issues: list = []
    bad = DataHealthCfg(min_n=2, knn_k=5, knn_min_n=5, cycle_regex="(?P<time>x")
    s = Settings()
    s.data_health = bad
    validate_data_health(s, issues)
    keys = {getattr(i, "key", None) or str(i) for i in issues}
    assert any("min_n" in k for k in keys) and any("knn" in k for k in keys) and any("cycle_regex" in k for k in keys)
    issues2: list = []
    s.data_health = D
    validate_data_health(s, issues2)
    assert not issues2


def test_dh_frames_step_is_cpu_resource():
    steps = {s.key: s for s in JOB_TYPES["DATA_HEALTH"].steps}
    assert [*steps] == ["DH_PREP", "DH_SCAN", "DH_FRAMES", "DH_SCORE", "DH_REPORT"]
    assert steps["DH_FRAMES"].kind == "LOCAL" and steps["DH_FRAMES"].res == "cpu"


def test_tcl_static_contract():
    code = "\n".join(ln for ln in TCL.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
    assert "frame_probe_settings.tcl" in code and "GetNumberOfSimulations" in code and "OPEN_ERROR" in code
    for forbidden in ("result scalar load", "node.displacement", "contour.value"):  # 결과장·변위를 읽지 않는다(경량 조회)
        assert forbidden not in code


def _tclsh():
    return os.environ.get("PAI_TEST_TCLSH") or shutil.which("tclsh") or shutil.which("tclsh8.6")


@pytest.mark.skipif(_tclsh() is None, reason="tclsh 없음")
@pytest.mark.parametrize("env,expect", [({}, ["OK", 5]), ({"STUB_NSIM": "3"}, ["OK", 3]), ({"STUB_OPEN_FAIL": "1"}, ["OPEN_ERROR", None])])
def test_tcl_runtime_with_stub_and_parse(tmp_path, env, expect):
    shutil.copy(TCL, tmp_path / fp.SCRIPT_NAME)
    outs = [tmp_path / "frames" / f"{i}.txt" for i in range(2)]
    (tmp_path / "frames").mkdir()
    (tmp_path / fp.SETTINGS_NAME).write_text(fp.settings_text([{"idx": i, "h3d": "/x.h3d", "out": o.as_posix()} for i, o in enumerate(outs)]), encoding="utf-8")
    r = subprocess.run([_tclsh(), str(STUB), str(tmp_path / fp.SCRIPT_NAME)], capture_output=True, text=True, timeout=60, cwd=tmp_path,
                       env={**os.environ, **env})
    assert r.returncode == 0, r.stderr
    for o in outs:  # OPEN_ERROR여도 다음 파일로 계속 — 파일마다 결과가 있다
        res = fp.read_result(str(o))
        assert res.ok == (expect[0] == "OK") and (res.frames == expect[1] or not res.ok)
