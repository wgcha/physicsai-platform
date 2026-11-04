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


# ---- V-DH-2 kNN ------------------------------------------------------------------------------------------


def _pts(n=36, seed=1, jitter=0.02):
    """6x6 격자 + 작은 잡음(DOE 표본 흉내) — 완전 격자는 거리 동률이 많아 이웃 선택이 치우친다."""
    import numpy as np

    rng = np.random.default_rng(seed)
    g = np.array([(i / 5, j / 5) for i in range(6) for j in range(6)])[:n]
    u = g + rng.normal(0, jitter, g.shape)
    return {f"r{i}": {"a": float(u[i, 0]), "b": float(u[i, 1])} for i in range(len(u))}, u


def test_knn_spike_flagged_only_for_that_run_and_deterministic():
    from physicsai_core.data_health.knn import build_space, knn_scores

    params, u = _pts()
    sp = build_space(params, None)
    vals = {f"r{i}": u[i, 0] ** 2 + u[i, 1] for i in range(36)}
    vals["r14"] += 5.0  # 매끈한 함수 + 스파이크 1개
    res = knn_scores(sp, vals, knn_k=5, knn_min_n=12)
    flagged = [k for k, s in res.s.items() if abs(s) > D.knn_z]
    assert flagged == ["r14"] and res.k == 5 and res.mean_dist["r14"] is not None
    again = knn_scores(sp, dict(vals), knn_k=5, knn_min_n=12)
    assert again.s == res.s  # 같은 입력 → 같은 결과


def test_knn_local_step_only_boundary_run_can_be_flagged():
    """국소 계단(바닥 닿음형)은 스파이크가 아니다 — 계단 경계 한 점 밖의 run은 오판하지 않는다(경계 run은 §3.4 정의상 이웃이 갈려 점수가 크다)."""
    from physicsai_core.data_health.knn import build_space, knn_scores

    params, u = _pts()
    sp = build_space(params, None)
    vals = {f"r{i}": (10.0 if u[i, 0] > 0.7 else 0.0) + u[i, 1] for i in range(36)}
    res = knn_scores(sp, vals, knn_k=5, knn_min_n=12)
    flagged = [k for k, s in res.s.items() if abs(s) > D.knn_z]
    near_edge = {k for k in vals if abs(params[k]["a"] - 0.7) < 0.15}
    assert set(flagged) <= near_edge


def test_knn_k_n_minus_1_snapshot_mixed_and_small_n():
    from physicsai_core.data_health.knn import build_space, knn_scores

    sp = build_space({f"r{i}": {"x": float(i)} for i in range(4)}, None)
    assert knn_scores(sp, {f"r{i}": float(i * i) for i in range(4)}, knn_k=5, knn_min_n=3).k == 3  # k = min(knn_k, n-1)
    assert knn_scores(sp, {f"r{i}": float(i) for i in range(4)}, knn_k=5, knn_min_n=12).skipped  # n < knn_min_n 생략
    snap = build_space({"r0": {"x": 5.0}, "r1": {"x": 10.0}}, [{"name": "x", "min": 0.0, "max": 10.0}])
    assert list(snap.u["r0"]) == [0.5] and list(snap.u["r1"]) == [1.0]  # snapshot 범위로 정규화
    assert build_space({"r0": {"x": 1.0}, "r1": {"y": 2.0}}, None).mixed  # 파라미터 이름 집합이 다르면 혼합
    assert knn_scores(build_space({"r0": {"x": 1.0}, "r1": {"y": 2.0}}, None), {"r0": 1.0, "r1": 2.0}, knn_k=1, knn_min_n=2).skipped
    const = build_space({"r0": {"x": 1.0}, "r1": {"x": 1.0}}, None)
    assert const.names == []  # max = min인 파라미터는 뺀다


def test_knn_distance_tie_uses_run_order_index():
    from physicsai_core.data_health.knn import build_space, knn_scores

    p = {"a": {"x": 0.0}, "b": {"x": 0.5}, "c": {"x": 1.0}}
    sp = build_space(p, None)
    first = knn_scores(sp, {"a": 10.0, "b": 15.0, "c": 20.0}, knn_k=1, knn_min_n=3)
    flipped = knn_scores(sp, {"c": 20.0, "a": 10.0, "b": 15.0}, knn_k=1, knn_min_n=3)  # b의 이웃 a·c는 같은 거리 — 먼저 나온 run이 이웃
    assert first.s["b"] > 0 > flipped.s["b"]


# ---- V-DH-5 모델 속성 -------------------------------------------------------------------------------------

MESH = ("/NODE\n1 0 0 0\n2 1 0 0\n3 0 1 0\n4 0 0 1\n5 1 1 0\n6 1 0 1\n7 0 1 1\n8 1 1 1\n"
        "/TETRA4/10\n1 1 2 3 4\n/BRICK/20\n2 1 2 5 3 4 6 8 7\n")


def test_attrs_known_mesh_parts_and_cache_reparse_zero(tmp_path, monkeypatch):
    from physicsai_core.data_health import attrs
    from physicsai_core.equiv import volume as vol

    inc = tmp_path / "104_replace_node_elem.inc"
    inc.write_text(MESH, encoding="utf-8")
    cache = str(tmp_path / "_attrs")
    r = attrs.model_attrs(mesh_inc=str(inc), mesh_tree=None, mesh_parts=None, max_bytes=1 << 20, cache_dir=cache)
    v = r.values
    assert abs(v["volume"] - (1 + 1 / 6)) < 1e-9 and (v["bbox_dx"], v["bbox_dy"], v["bbox_dz"]) == (1.0, 1.0, 1.0)
    assert abs(v["cog_x"] - (0.25 / 6 + 0.5) / (7 / 6)) < 1e-9  # 부피 가중 중심
    only = attrs.solid_attrs(vol.parse_include(MESH.splitlines()), ["10"])  # 조립 매칭 run은 PART 선택으로 계산한다
    assert abs(only.values["volume"] - 1 / 6) < 1e-9 and only.values["bbox_dz"] == 1.0
    calls = []
    monkeypatch.setattr(vol, "read_include", lambda *a, **k: calls.append(1))
    again = attrs.model_attrs(mesh_inc=str(inc), mesh_tree=None, mesh_parts=None, max_bytes=1 << 20, cache_dir=cache)
    assert not calls and again.values == v  # 서명 일치 → 재파싱 0회
    inc.write_text(MESH + "\n", encoding="utf-8")  # 서명(크기)이 달라지면 다시 계산
    monkeypatch.undo()
    assert attrs.model_attrs(mesh_inc=str(inc), mesh_tree=None, mesh_parts=None, max_bytes=1 << 20, cache_dir=cache).values == v


def test_attrs_missing_include_and_shell_only(tmp_path):
    from physicsai_core.data_health import attrs

    assert attrs.model_attrs(mesh_inc=None, mesh_tree=None, mesh_parts=None, max_bytes=1 << 20, cache_dir=None).na == "MESH_MISSING"
    assert attrs.model_attrs(mesh_inc=str(tmp_path / "none.inc"), mesh_tree=None, mesh_parts=None, max_bytes=1 << 20, cache_dir=None).na == "MESH_MISSING"
    shell = tmp_path / "shell.inc"
    shell.write_text("/NODE\n1 0 0 0\n2 1 0 0\n3 1 1 0\n4 0 1 0\n/SHELL/1\n1 1 2 3 4\n", encoding="utf-8")
    assert attrs.model_attrs(mesh_inc=str(shell), mesh_tree=None, mesh_parts=None, max_bytes=1 << 20, cache_dir=None).na == "NO_SOLID"


# ---- input_key(DH-C3) ------------------------------------------------------------------------------------


def test_input_key_windows_drive_case_separators_and_trailing():
    from physicsai_core.data_health.input_key import folder_key, input_key

    base = folder_key("E:/AI/Study1/01_train/results")
    assert base == folder_key("e:\\AI\\Study1\\01_train\\results") == folder_key("E:\\AI\\Study1\\01_train\\results\\")
    assert base == folder_key("E:/AI/Study1/./01_train//results/") and base == "e:/ai/study1/01_train/results"
    assert folder_key("/data/ai/s/") == folder_key("/data/ai/s") == "/data/ai/s"
    assert input_key("/x/y", "c-1") == "curation:c-1" and input_key("/x/y/", None) == "/x/y"


def test_dataset_check_uses_same_key_function():
    import inspect

    from physicsai_api.services.job_params import stage3_model as st

    assert "folder_key" in inspect.getsource(st.check_health_job)


@pytest.mark.skipif(_tclsh() is None, reason="tclsh 없음")
def test_tcl_nsim_failure_is_probe_error_not_one_frame(tmp_path):
    shutil.copy(TCL, tmp_path / fp.SCRIPT_NAME)
    (tmp_path / "frames").mkdir()
    o = tmp_path / "frames" / "0.txt"
    (tmp_path / fp.SETTINGS_NAME).write_text(fp.settings_text([{"idx": 0, "h3d": "/x.h3d", "out": o.as_posix()}]), encoding="utf-8")
    r = subprocess.run([_tclsh(), str(STUB), str(tmp_path / fp.SCRIPT_NAME)], capture_output=True, text=True, timeout=60, cwd=tmp_path,
                       env={**os.environ, "STUB_NSIM_FAIL": "1"})
    assert r.returncode == 0, r.stderr
    res = fp.read_result(str(o))
    assert not res.ok and res.code == "FRAMES_PROBE_FAILED" and "PROBE_ERROR" in (res.message or "")
