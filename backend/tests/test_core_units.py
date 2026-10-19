"""단위 시험: 상태 머신·명령 템플릿·경로·백업·자원 한도·오류 묶음. 단계 core(분할·파서·최근접·tpl)는 test_core_stage_units."""

from __future__ import annotations

import itertools
import os

import pytest

from physicsai_core.commands import TEMPLATE_SPECS, cmd_c_prefix, render_argv, validate_template
from physicsai_core.errors import StepFailure
from physicsai_core.limits import compute_limits
from physicsai_core.paths import (PathError, backup_existing, check_dataset_input, check_user_path, file_name_problem_message,
                                  file_safety_problem, name_unsafe_chars, resolve_in_study)
from physicsai_core.state_machine import ALL_STATES, TRANSITIONS, IllegalTransition, check_transition

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
    exe0 = "C:\\Program Files\\Altair\\2026.1\\edspy.bat" if os.name == "nt" else "C:/Program Files/Altair/2026.1/edspy.bat"
    assert argv == [exe0, "--physicsai", "--create-dataset",
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
                                   "t01_curve_export", "hst_optimization",
                                   "contour_capture"} | {  # 3차(phase3 §15 S10)
        # native 형상 엔진(geometry-engine §7.1)
        "paicad_version", "paicad_extract", "paicad_tag", "paicad_update", "paicad_morph", "paicad_check", "paicad_run",
        # 단계 3S·4B(geometry-engine §11.1·§7.3.8)
        "paicad_props_scan", "paicad_props_apply", "paicad_map"}


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


def test_d3_34_backup_platform_case_insensitive(tmp_path):
    """phase3 D3-34: Windows에서 `_BACKUP`·`_Platform`으로 우회하지 못하게 대소문자 무시."""
    root = tmp_path / "ai"
    for rel in ("s/_BACKUP/x", "s/_Backup", "_Platform/x", "_PLATFORM", "s/in/_bAcKuP/y"):
        with pytest.raises(PathError) as ei:
            check_user_path(str(root / rel), [str(root)], must_exist=False)
        assert ei.value.code == "PATH_UNSAFE", rel
    # Study 안의 `_platform`(루트 직계가 아님)·비슷한 이름은 그대로 허용
    for rel in ("s/_platform_x", "s/in/_platform", "s/backup"):
        assert check_user_path(str(root / rel), [str(root)], must_exist=False).path == str(root / rel)
    (root / "S1" / "_Backup" / "h3d").mkdir(parents=True)
    with pytest.raises(PathError):
        check_dataset_input(str(root / "S1" / "_Backup" / "h3d"), str(root))


def test_d3_35_file_name_chars(tmp_path):
    """phase3 D3-35: 외부 명령 인자로 들어가는 파일 이름은 `; , = ( ) '`·공백류도 거부, 영숫자·_·-·.·한글은 허용."""
    for ok in ("Face_Drop_0000.rad", "part-1.v2.inc", "브래킷_모델.rad", "A1"):
        assert name_unsafe_chars(ok) is None, ok
    cases = {"a;b.rad": ";", "a,b.inc": ",", "a=b.inc": "=", "run(1).rad": "( )", "it's.inc": "'",
             "a b.inc": "공백", "a\u3000b.inc": "공백", "a\xa0b.inc": "공백", "a\tb": "공백", "a&b": "&",
             "a\u200bb.inc": "제어문자", "x(1);y.rad": "( ) ;"}
    for name, why in cases.items():
        assert name_unsafe_chars(name) == why, name
    assert file_name_problem_message("( )") == "파일 이름에 쓸 수 없는 문자(( ))가 있습니다"
    assert file_name_problem_message("링크") == "링크 파일은 쓸 수 없습니다"
    base = tmp_path / "in(1)"                                           # 기준 폴더는 경로 규칙(check_user_path)만
    (base / "sub=2").mkdir(parents=True)
    for n in ("ok_0000.rad", "bad(2).rad"):
        (base / n).write_text("x")
    (base / "sub=2" / "a.h3d").write_text("x")
    assert file_safety_problem(str(base / "ok_0000.rad"), str(base)) is None
    assert file_safety_problem(str(base / "bad(2).rad"), str(base)) == "( )"
    assert file_safety_problem(str(base / "sub=2" / "a.h3d"), str(base)) == "="


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


def test_error_bundle_commands_head_requires_path_inside_study(tmp_path):
    """H9 회귀: commands_rel이 Study 밖 형제 폴더(…/abc2)를 가리키면 접두 문자열이 같아도 읽지 않는다."""
    from physicsai_core.error_bundle import iter_items
    from physicsai_core.masking import BundleMasker

    root = tmp_path / "abc"
    sibling = tmp_path / "abc2"
    (root / "logs").mkdir(parents=True)
    sibling.mkdir()
    (root / "logs" / "in.commands.jsonl").write_text('{"target_id": "inside"}\n', encoding="utf-8")
    (sibling / "out.commands.jsonl").write_text('{"target_id": "outside"}\n', encoding="utf-8")
    steps = [
        {"step_no": 1, "step_key": "A", "command": {"commands_rel": "logs/in.commands.jsonl"}},
        {"step_no": 2, "step_key": "B", "command": {"commands_rel": "../abc2/out.commands.jsonl"}},
    ]
    job = {"id": "j1", "job_type": "PREDICT", "state": "FAILED", "failure_code": "X"}
    items = dict(iter_items(job=job, steps=steps, log_dir=str(root / "logs"), study_root=str(root), hpc_jobs=None,
                            config_summary={}, environment={}, env_check_latest=None, tail_bytes=1024,
                            max_total=10**6, masker=BundleMasker([], "sess", "DBURL", environ={}), created="t"))
    inside = items["steps/step_01_A.command.json"].decode("utf-8")
    outside = items["steps/step_02_B.command.json"].decode("utf-8")
    assert "commands_head" in inside and "inside" in inside
    assert "commands_head" not in outside and "outside" not in outside.replace("../abc2/out.commands.jsonl", "")
