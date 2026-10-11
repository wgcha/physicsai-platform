"""단계 core 단위 시험: ③ 데이터셋 수집·분할·yaml, 학습 로그(loss)·점수 파서, ④ xydata·최근접·범위·정수 반올림, tpl 파싱·렌더."""

from __future__ import annotations

import os
import random

import pytest

from physicsai_core.errors import StepFailure
from physicsai_core.stage3_model.dataset_split import collect_h3d, dataset_yaml, split_files
from physicsai_core.stage3_model.loss import parse_loss_lines
from physicsai_core.stage3_model.score import parse_scores
from physicsai_core.stage4_predict import nearest as nm
from physicsai_core.stage4_predict.xydata import parse_xydata
from physicsai_core.tpl_render import parse_tpl, render_tpl

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
