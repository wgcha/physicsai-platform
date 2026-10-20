"""①-3 native DOE run 폴더 레이아웃(geometry-engine.md §7.3.3·§7.3.6, GE-C13): `run__N/` 직계 = 해석 입력(starter·include·조립 사본),
보조 산출물 = `run__N/_paicad/`. TD_SOLVE가 run 직계 starter를 제출, starter 탐색·SCX 업로드가 `_paicad`를 보지 않음,
paramitem 역판독, 이전 m_1~m_3 native run 폴더 읽기 호환."""

from __future__ import annotations

import fnmatch
import json
import types
from pathlib import Path

import pytest
from helpers_native import make_project
from helpers_stage1 import job, study, submit
from physicsai_test_support import _p2_env, pbs_command_cfg, read_record

from physicsai_core.stage1_train_data import doe_samples


@pytest.fixture()
def p2_native_pbs(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, pbs_state):
    ai = tmp_path / "ai_root"
    ai.mkdir(exist_ok=True)
    over = {"geometry": {"engine": "native", "paicad_path": fake_tools["fake_paicad"]}, "hpc": pbs_command_cfg(fake_tools, str(ai))}
    yield from _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, over)


def _native_doe(c, w, ai: Path, name: str, num_runs: int = 3):
    sid = study(c, name)
    proj = make_project(ai / name / "00_inbox")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    j = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LHS", "num_runs": num_runs, "seed": 5, "multi_execution": 2,
                                      "radioss_assem_path": str(proj / "assem")})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    jd = job(c, j["id"])
    return sid, jd["result"]["doe_id"], jd


def _qsub_inputs(fake_record) -> list[str]:
    out = []
    for r in read_record(fake_record):
        if r["tool"] == "qsub":
            v = r["argv"][r["argv"].index("-v") + 1]
            out.append(next(x.split("=", 1)[1] for x in v.split(",") if x.startswith("INPUT_FILE=")))
    return out


def test_native_doe_flat_run_and_solve_starter(p2_native_pbs, fake_record):
    """새 native DOE: run 직계에 starter·include, m_* 없음 → DG_SCAN input_rel = run 폴더 → TD_SOLVE INPUT_FILE = run 직계 starter."""
    c, mk, ai, _lc, _d = p2_native_pbs
    w = mk()
    sid, doe_id, jd = _native_doe(c, w, ai, "rf1")
    assert jd["result"]["run_count"] == 3 and jd["result"]["sample_status"] == "PARSED"
    D = ai / "rf1" / "01_train" / "doe" / doe_id
    for rk in ("run__00001", "run__00002", "run__00003"):
        R = D / "approaches" / "doe_1" / rk
        direct = sorted(p.name for p in R.iterdir())
        assert "_paicad" in direct and not [n for n in direct if n.startswith("m_")]
        assert [n for n in direct if fnmatch.fnmatch(n, "*_0000.rad")] == ["model0_0000.rad"]
        assert all((R / n).is_file() for n in direct if n != "_paicad")              # 직계 = 해석 입력 파일만(하위 폴더는 _paicad 1개)
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC", job(c, j["id"])
    got = _qsub_inputs(fake_record)
    assert len(got) == 3 and all(g.endswith(f"/01_train/doe/{doe_id}/approaches/doe_1/run__0000{i}/model0_0000.rad")
                                 for i, g in zip((1, 2, 3), got)), got


def test_native_doe_legacy_m_layout_still_read(p2_native_pbs, fake_record, monkeypatch):
    """이전 코드가 만든 m_1~m_3 native run(LEGACY 레이아웃)도 DG_SCAN(m_3 starter)·paramitem(m_1)·TD_SOLVE가 그대로 읽는다."""
    from physicsai_worker.steps import geometry_sample
    from physicsai_worker.steps.stage1_train_data import doe_native

    monkeypatch.setattr(doe_native, "FLAT", geometry_sample.LEGACY)  # 이전 생성 코드 재현
    c, mk, ai, _lc, _d = p2_native_pbs
    w = mk()
    sid, doe_id, jd = _native_doe(c, w, ai, "rf2", num_runs=2)
    assert jd["result"]["run_count"] == 2 and jd["result"]["sample_status"] == "PARSED"
    D = ai / "rf2" / "01_train" / "doe" / doe_id
    R = D / "approaches" / "doe_1" / "run__00001"
    assert (R / "m_3" / "model0_0000.rad").is_file() and (R / "m_1" / "native_params.xml").is_file() and not (R / "_paicad").exists()
    runs = json.loads((D / "runs.json").read_text())
    assert [r["input_rel"] for r in runs] == [f"01_train/doe/{doe_id}/approaches/doe_1/run__0000{i}/m_3" for i in (1, 2)]
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC", job(c, j["id"])
    assert all(g.endswith("/m_3/model0_0000.rad") for g in _qsub_inputs(fake_record))


def test_find_starter_ignores_aux_dir_and_reads_both_layouts(tmp_path):
    from physicsai_worker.steps.stage1_train_data.doe_gen import _find_starter

    flat = tmp_path / "run__00001"
    (flat / "_paicad" / "shell_files").mkdir(parents=True)
    (flat / "_paicad" / "shell_files" / "model0_0000.rad").write_text("#copy\n")   # 보조 폴더의 starter 모양 파일(쉘 PASS 사본 등)
    (flat / "model0_0000.rad").write_text("#starter\n")
    (flat / "EPS_mesh_0000.rad").write_text("#mesh\n")
    assert _find_starter(str(flat), "*_0000.rad", ("_paicad",)) == [str(flat / "model0_0000.rad")]
    assert len(_find_starter(str(flat), "*_0000.rad")) == 2                         # altair(skip 없음)는 기존 재귀 그대로
    legacy = tmp_path / "run__00002"
    (legacy / "m_3").mkdir(parents=True)
    (legacy / "m_3" / "model0_0000.rad").write_text("#starter\n")
    assert _find_starter(str(legacy), "*_0000.rad", ("_paicad",)) == [str(legacy / "m_3" / "model0_0000.rad")]


def test_paramitem_reads_aux_and_legacy(tmp_path):
    from physicsai_core.geometry.native_files import native_params_xml

    td = types.SimpleNamespace(paramitem_regex=r'<paramitem\s+Name="(?P<name>[^"]+)"\s+NewValue="(?P<value>[^"]*)"',
                               rendered_tpl_glob="**/*", rendered_tpl_exts=[".py", ".tcl", ".txt", ".xml", ""],
                               samples_scan_max_bytes=1 << 20, samples_extractor="paramitem")
    a, b = tmp_path / "run__00001" / "_paicad", tmp_path / "run__00002" / "m_1"
    for d, v in ((a, 1.25), (b, 2.5)):
        d.mkdir(parents=True)
        (d / "native_params.xml").write_text(native_params_xml({"A": v}, {"A": 1.0}))
    sr = doe_samples.extract(str(tmp_path), [{"run_key": "run__00001", "run_dir": str(a.parent)},
                                             {"run_key": "run__00002", "run_dir": str(b.parent)}], ["A"], td)
    assert sr.status == "PARSED" and [r["values"]["A"] for r in sr.rows] == [1.25, 2.5]


def test_scx_scan_skips_aux_dir_without_warning(tmp_path):
    from physicsai_worker.steps import _scx

    R = tmp_path / "run__00001"
    (R / "_paicad" / "check").mkdir(parents=True)
    (R / "_paicad" / "104_replace_node_elem.inc").write_text("x\n")
    (R / "model0_0000.rad").write_text("#s\n")
    (R / "104_replace_node_elem.inc").write_text("x\n")
    warns: list[tuple[str, str]] = []
    ctx = types.SimpleNamespace(add_warning=lambda code, msg: warns.append((code, msg)), checkpoint=None)
    gw = types.SimpleNamespace(cfg=types.SimpleNamespace(max_stage_bytes=1 << 30),
                               matches_stage_pattern=lambda n: n.lower().endswith((".rad", ".inc")))
    plan = _scx.RunStage(run_key="run__00001", input_dir=str(R), starter="model0_0000.rad", job_name="j", client_ref={})
    _scx.scan_inputs(ctx, gw, plan, {})
    assert sorted(f["name"] for f in plan.files) == ["104_replace_node_elem.inc", "model0_0000.rad"] and warns == []
    (R / "sub").mkdir()
    (R / "sub" / "x.inc").write_text("x\n")
    _scx.scan_inputs(ctx, gw, plan, {})
    assert [c for c, _m in warns] == ["SCX_SUBDIR_SKIPPED"]                         # 그 밖 하위 폴더는 기존처럼 경고
