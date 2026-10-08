"""단위 시험: 상태 머신·명령 템플릿·경로·분할·파서·최근접·자원 한도·tpl."""

from __future__ import annotations

import itertools
import os
import random

import pytest

from physicsai_core import nearest as nm
from physicsai_core.commands import TEMPLATE_SPECS, cmd_c_prefix, render_argv, validate_template
from physicsai_core.dataset_split import collect_h3d, dataset_yaml, split_files
from physicsai_core.errors import StepFailure
from physicsai_core.limits import compute_limits
from physicsai_core.parsers.loss import parse_loss_lines
from physicsai_core.parsers.score import parse_scores
from physicsai_core.parsers.xydata import parse_xydata
from physicsai_core.paths import PathError, backup_existing, check_user_path, resolve_in_study
from physicsai_core.state_machine import ALL_STATES, TRANSITIONS, IllegalTransition, check_transition
from physicsai_core.tpl_render import parse_tpl, render_tpl

# ---- V-SM-1 -----------------------------------------------------------------


def test_state_machine_table():
    expected = {
        (None, "QUEUED"), ("QUEUED", "RUNNING"), ("QUEUED", "CANCELED"), ("RUNNING", "RUNNING"),
        ("RUNNING", "WAITING_HPC"), ("RUNNING", "SUCCEEDED"), ("RUNNING", "FAILED"), ("RUNNING", "CANCELED"),
        ("RUNNING", "INTERRUPTED"), ("COLLECTING", "INTERRUPTED"), ("WAITING_HPC", "COLLECTING"),
        ("WAITING_HPC", "WAITING_HPC"), ("WAITING_HPC", "CANCELED"), ("COLLECTING", "CANCELED"),
        ("WAITING_HPC", "FAILED"), ("COLLECTING", "QUEUED"), ("COLLECTING", "SUCCEEDED"), ("COLLECTING", "FAILED"),
    }
    assert set(TRANSITIONS) == expected
    for src, dst in itertools.product([None, *ALL_STATES], ALL_STATES):
        if (src, dst) in expected:
            assert check_transition(src, dst).startswith("T")
        else:
            with pytest.raises(IllegalTransition):
                check_transition(src, dst)


# ---- V-CMD-3, V-CMD-6, V-CMD-1 ------------------------------------------------

EXE = {"edspy_path": "C:/Program Files/Altair/2026.1/edspy.bat", "hw_exe_path": "/opt/hw", "simlab_path": "/opt/simlab"}


def test_default_templates_render_like_original():
    argv = render_argv("edspy_create_dataset", ["{edspy}", "--physicsai", "--create-dataset", "{out_psdata}", "--spec", "{spec_yaml}"],
                       {"out_psdata": "E:/AI/s/03_dataset/x/train/dataset.psdata", "spec_yaml": "E:/AI/s/03_dataset/x/train/dataset.yaml"},
                       executables=EXE)
    assert argv == ["C:/Program Files/Altair/2026.1/edspy.bat", "--physicsai", "--create-dataset",
                    "E:/AI/s/03_dataset/x/train/dataset.psdata", "--spec", "E:/AI/s/03_dataset/x/train/dataset.yaml"]
    t = ["{edspy}", "--physicsai", "--score", "{score_path}", "--model", "{model_psmdl}", "--dataset", "{eval_psdata}", "@write_files"]
    v = {"score_path": "/a/m.psscr", "model_psmdl": "/a/m.psmdl", "eval_psdata": "/a/e.psdata"}
    assert render_argv("edspy_score", t, v, executables=EXE)[-1] == "/a/e.psdata"
    assert render_argv("edspy_score", t, v, executables=EXE, write_files=True)[-1] == "--write-files"


def test_cmd_c_expansion():
    assert cmd_c_prefix(False) == []
    assert cmd_c_prefix(True, {"SystemRoot": "C:\\Windows"}) == ["C:\\Windows\\System32\\cmd.exe", "/c"]
    t = ["@cmd_c", "{edspy}", "--predict-write", "{pred_h3d}", "--model", "{model_psmdl}", "--input-file", "{starter}", "@hooks_arg"]
    v = {"pred_h3d": "/p/R/a_pred.h3d", "model_psmdl": "/m.psmdl", "starter": "/p/I/a_0000.rad"}
    win = render_argv("edspy_predict", t, v, executables=EXE, is_windows=True, environ={"SystemRoot": "C:\\Windows"})
    # phase2 §2.3: Windows argv[0]은 '\\' 구분자(normpath)
    assert win[:3] == ["C:\\Windows\\System32\\cmd.exe", "/c", EXE["edspy_path"].replace("/", "\\")] and win[-1] == "/p/I/a_0000.rad"
    lin = render_argv("edspy_predict", t, v, executables=EXE, is_windows=False)
    assert lin[0] == EXE["edspy_path"]


@pytest.mark.parametrize("bad", ["a&b", "a|b", "a<b", "a>b", "a^b", "a%b", "a!b", 'a"b', "a\nb", "a\x00b", "a b", "a;b\x07"])
def test_value_injection_rejected(bad):
    with pytest.raises(StepFailure) as ei:
        render_argv("edspy_create_dataset", ["{edspy}", "--create-dataset", "{out_psdata}", "--spec", "{spec_yaml}"],
                    {"out_psdata": bad, "spec_yaml": "/ok"}, executables=EXE)
    assert ei.value.code == "INPUT_INVALID"


@pytest.mark.parametrize(
    "key,tpl",
    [
        ("edspy_score", ["{edspy}", "{evil}"]),
        ("edspy_score", ["/bin/sh", "-c", "x"]),
        ("edspy_score", ["{score_path}", "x"]),
        ("geom_update", ["{simlab}", "{edspy}"]),
        ("edspy_create_dataset", ["{edspy}", "@cmd_c"]),
        ("edspy_create_dataset", ["{edspy}", "{out_psdata!r}"]),
        ("edspy_create_dataset", ["{edspy}", "{out_psdata:>10}"]),
        ("edspy_create_dataset", None),
        ("edspy_create_dataset", "edspy --create-dataset"),
        ("edspy_score", ["{edspy}", "@unknown"]),
    ],
)
def test_template_validation_rejects(key, tpl):
    assert validate_template(key, tpl)


def test_null_optional_templates_ok():
    for k in ("mesh", "rad_assemble", "response_extract", "geom_update"):
        assert validate_template(k, None) == []
    assert set(TEMPLATE_SPECS) == {"edspy_create_dataset", "edspy_score", "geom_update", "mesh", "rad_assemble",
                                   "edspy_predict", "contour_preview", "response_extract",
                                   # 2차(phase2 §8.1): null 허용
                                   "simlab_extract_params", "hst_gen_radioss", "h3d_preview", "hvtrans_curate", "t01_preview",
                                   "t01_curve_export", "hst_optimization"}


def test_null_template_render_is_not_configured():
    with pytest.raises(StepFailure) as ei:
        render_argv("geom_update", None, {}, executables=EXE)
    assert ei.value.code == "TEMPLATE_NOT_CONFIGURED"


# ---- 경로(§17.3) ---------------------------------------------------------------


def test_path_checks(tmp_path):
    root = tmp_path / "ai"
    (root / "s" / "in").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    ok = check_user_path(str(root / "s" / "in"), [str(root)])
    assert ok.path == str(root / "s" / "in")
    cases = {
        str(outside): "PATH_OUTSIDE_ROOT",
        str(root) + "/s/../../outside": "PATH_UNSAFE",
        str(root / "s" / "missing"): "PATH_NOT_FOUND",
        "relative/path": "PATH_UNSAFE",
        str(root / "s" / "a b"): "PATH_UNSAFE",
        str(root / "s" / "a&b"): "PATH_UNSAFE",
        str(root / "s" / "_backup" / "x"): "PATH_UNSAFE",
        "/" + "a" * 401: "PATH_UNSAFE",
    }
    (root / "s" / "_backup" / "x").mkdir(parents=True)
    os.symlink(outside, root / "s" / "link")
    cases[str(root / "s" / "link")] = "PATH_UNSAFE"
    (root / "s" / "real").mkdir()
    os.symlink(root / "s" / "real", root / "s" / "inner_link")
    cases[str(root / "s" / "inner_link")] = "PATH_UNSAFE"
    for p, code in cases.items():
        with pytest.raises(PathError) as ei:
            check_user_path(p, [str(root)])
        assert ei.value.code == code, p
    # 루트 접두가 같은 형제 폴더(ai → ai2)는 밖
    (tmp_path / "ai2").mkdir()
    with pytest.raises(PathError) as ei:
        check_user_path(str(tmp_path / "ai2"), [str(root)])
    assert ei.value.code == "PATH_OUTSIDE_ROOT"


def test_resolve_in_study_escape(tmp_path):
    with pytest.raises(Exception):
        resolve_in_study(str(tmp_path), "../x")
    assert resolve_in_study(str(tmp_path), "a/b") == str(tmp_path / "a" / "b")


def test_backup_moves_not_deletes(tmp_path, monkeypatch):
    study = tmp_path / "s"
    (study / "03_dataset" / "d").mkdir(parents=True)
    f = study / "03_dataset" / "d" / "split.json"
    f.write_text("old")
    moved = backup_existing(str(study), [str(f)], "job1", "20261008T000000Z")
    assert moved == ["03_dataset/d/split.json"] and not f.exists()
    assert (study / "_backup" / "20261008T000000Z_job1" / "03_dataset" / "d" / "split.json").read_text() == "old"
    f.write_text("locked")

    def boom(*a, **k):
        raise PermissionError("locked by another process")

    monkeypatch.setattr(os, "replace", boom)  # 잠김 모사(root 권한에서는 권한 제거로 모사 불가)
    with pytest.raises(StepFailure) as ei:
        backup_existing(str(study), [str(f)], "job2")
    assert ei.value.code == "OUTPUT_LOCKED" and "split.json" in ei.value.message
    assert f.read_text() == "locked"


# ---- V-DS-1 --------------------------------------------------------------------


def test_collect_and_split(tmp_path):
    for i in range(20):
        d = tmp_path / f"run_{i:02d}"
        d.mkdir()
        (d / f"r{i}.H3D").write_text("x")
        (d / f"r{i}b.h3d").write_text("x")
    (tmp_path / "note.txt").write_text("x")
    files = collect_h3d(str(tmp_path))
    assert len(files) == 40 and files == sorted(files)
    a = split_files(files, 0.1, 42)
    b = split_files(files, 0.1, 42)
    assert a == b and len(a.eval) == 4 and len(a.train) == 36 and set(a.train).isdisjoint(a.eval)
    assert split_files(files, 0.1, 43).eval != a.eval
    g = split_files(files, 0.1, 42, "parent_dir")
    assert len(g.eval) == 4
    eval_dirs = {os.path.dirname(f) for f in g.eval}
    assert all(os.path.dirname(f) not in eval_dirs for f in g.train)
    small = split_files(files[:3], 0.1, 1)
    assert len(small.eval) == 1
    assert split_files(files[:1], 0.1, 1).eval == []


def test_dataset_yaml_format():
    y = dataset_yaml(["/a/1.h3d", "/a/2.h3d"], "/d/hooks", {"extract_faces": True, "extract_mdi": False, "extract_time_history_vectors": True})
    assert y == ("files:\n- /a/1.h3d\n- /a/2.h3d\ninterface: hw\noptions:\n  extract_faces: true\n  extract_files: true\n"
                 "  extract_mdi: false\n  extract_results: true\n  extract_time_history_vectors: true\n  hooks_dir: /d/hooks\n  selection: {}\n")


# ---- V-MR-2 ---------------------------------------------------------------------

DEFAULT = [("physicsai_default", r"epoch=\s*(?P<epoch>\d+)\s*/\s*(?P<total>\d+)\s+loss=(?P<loss>[0-9.eE+\-]+)")]


def test_loss_parser_default_and_downsample():
    rng = random.Random(1)
    lines = []
    losses = {}
    for e in range(1, 10001):
        v = 100.0 / e + rng.random() * 0.01
        if e == 5000:
            v = 1e-6
        losses[e] = v
        lines.append(f"epoch= {e:5d}/10000  loss={v:.6e}")
    r = parse_loss_lines(iter(["header"] + lines), DEFAULT, 2000)
    assert r.status == "PARSED" and r.epochs_total == 10000 and r.last_epoch == 10000
    assert r.min_loss_epoch == 5000 and r.min_loss == pytest.approx(1e-6)
    pts = [p[0] for p in r.loss_curve]
    assert len(r.loss_curve) <= 2000 and pts[0] == 1 and pts[-1] == 10000 and 5000 in pts
    assert pts == sorted(pts)


def test_loss_parser_unrecognized_and_order():
    assert parse_loss_lines(["no match"], DEFAULT).status == "UNRECOGNIZED"
    parsers = [("p1", r"step (?P<epoch>\d+) l=(?P<loss>[\d.]+)"), *DEFAULT]
    r = parse_loss_lines(["epoch=  1/ 2 loss=3.0", "epoch=  2/ 2 loss=1.0"], parsers)
    assert r.parser == "physicsai_default" and r.epochs_total == 2


def test_score_parser():
    p = [("generic", r"^\s*(?P<name>[A-Za-z][A-Za-z0-9_ ]{0,40}?)\s*[:=]\s*(?P<value>[-+0-9.eE]+)\s*$"), ("fixed_rmse", r"RMSE\((?P<value>[\d.]+)\)")]
    st, m = parse_scores(["R2 = 0.9", "noise", "RMSE(1.5)"], p)
    assert st == "PARSED" and m == {"R2": 0.9, "fixed_rmse": 1.5}
    assert parse_scores(["x"], []) == ("UNRECOGNIZED", {})


def test_xydata(tmp_path):
    f = tmp_path / "a.xy"
    f.write_text("XYDATA, Force\n0 1\n1 2\nXYDATA, Disp\n0 0.1\n1 0.2\n")
    d = parse_xydata(str(f), "a.xy")
    assert [s["name"] for s in d["series"]] == ["Force", "Disp"] and d["series"][1]["y"] == [0.1, 0.2]
    g = tmp_path / "b.xy"
    g.write_text("0,1,5\n1,2,6\n")
    d = parse_xydata(str(g))
    assert [s["name"] for s in d["series"]] == ["Impact_force Column 2", "Impact_force Column 3"] and d["note"]


# ---- V-PR-1 ---------------------------------------------------------------------

PARAMS = [{"name": "A", "nominal": 1, "min": 0, "max": 10}, {"name": "B", "nominal": 1, "min": 5, "max": 5}]


def test_nearest_and_range():
    samples = [{"run_key": "r2", "values": {"A": 4, "B": 5}, "measured": {"S": 1.0}},
               {"run_key": "r1", "values": {"A": 6, "B": 5}, "measured": {"S": 2.0}},
               {"run_key": "r3", "values": {"A": 9, "B": 99}, "measured": {}}]
    n = nm.nearest_run(PARAMS, samples, {"A": 5, "B": 123})  # B는 max=min이라 제외 → r1·r2 동률 → 사전순
    assert n["run_key"] == "r1" and n["distance"] == pytest.approx(0.1)
    assert nm.nearest_run(PARAMS, [], {"A": 1}) is None
    assert nm.out_of_range(PARAMS, {"A": 11, "B": 5}) == [{"name": "A", "value": 11, "min": 0, "max": 10}]
    assert nm.out_of_range(PARAMS, {"A": 10, "B": 5}) == []


def test_integer_rounding():
    tp = [{"var": "var_1", "name": "N", "format": "%3i"}, {"var": "var_2", "name": "T", "format": "%8.4f"}]
    assert nm.rounded(tp, {"N": 2.5, "T": 1.0}, "half_up") == [{"name": "N", "value": 2.5, "applied": 3}]
    assert nm.rounded(tp, {"N": 2.5}, "truncate")[0]["applied"] == 2
    assert nm.apply_rounding(-2.5, "half_up") == -3


def test_tpl_parse_and_render():
    tpl = '\ufeff{parameter(var_1, "THK", 3, 2, 5)}\n#****\nt = {var_1, %6.2f}\nn = {var_1, %3i}\n'
    decl, refs = parse_tpl(tpl)
    assert decl == {"var_1": "THK"} and {r["format"] for r in refs} == {"%6.2f", "%3i"}
    out = render_tpl(tpl, {"THK": 2.6}, {"THK": 3})
    assert out == "#****\nt =   3.00\nn =   3\n"
    with pytest.raises(StepFailure):
        render_tpl('{parameter(var_1, "THK", 3, 2, 5)}\nx={var_2, %3i}\n', {"THK": 1}, {})


# ---- V-JO-5 ---------------------------------------------------------------------


def test_effective_limits():
    l = compute_limits(32, 64, "below_normal", False, 0.7, 64, 256)
    assert (l.cores, l.memory_gb, l.cpu_rate) == (32, 64, 5000)
    l = compute_limits(32, 64, "below_normal", False, 0.7, 16, 32)
    assert (l.cores, l.memory_gb, l.cpu_rate) == (16, 32, 10000)
    l = compute_limits(32, 64, "idle", True, 0.7, 20, 100)
    assert (l.cores, l.cpu_rate) == (14, 7000) and l.memory_gb == 64
    l = compute_limits(1, 64, "normal", False, 0.7, 256, 512)
    assert l.cpu_rate == 100  # 하한 clamp(1/256 → 39 → 100)
