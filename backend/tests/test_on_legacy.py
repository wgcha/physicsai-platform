"""opt-native V-ON-1~3(백엔드): HyperStudy 레거시 기능 판정·`/status` legacy·환경 점검 SKIP·설정 예시.

V-ON-1 정적: LEGACY_FEATURES 밖 판정(FeatureReq·special missing 함수 소스)이 HyperStudy 키·템플릿·런처를 참조하지 않는다.
V-ON-2: HyperStudy 미설정 설정(+ 가짜 도구)에서 train_doe·optimize만 false·legacy, 나머지 features 전부 true.
V-ON-3: 레거시 키 빈 값 → SKIP 문구, 다른 빈 키 → WARN, 레거시 경로 있으나 파일 없음 → FAIL, 프로브 SKIP.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import yaml

from physicsai_test_support import REPO
from support_resources import LAUNCHERS, PHASE2_COMMANDS, make_phase2_settings, pbs_command_cfg

FORBIDDEN = ("hyperstudy_path", "hstpy_path", "altair_home", "hst_gen_radioss", "hst_optimization", "gen_radioss",
             "\"optimization\"", "'optimization'", "hstbatch", "hstpy")


def _req_tokens(req) -> list[str]:
    return [*req.templates, *req.altair, *req.resources, *req.launchers]


def test_v_on_1_static_non_legacy_features_do_not_reference_hyperstudy():
    from physicsai_core import features as f
    from physicsai_core.config import schema_capture
    from physicsai_core.stage5_optimize import surrogate

    assert f.LEGACY_FEATURES == frozenset({"train_doe", "optimize"}) and f.LEGACY_JOBS == frozenset({"OPTIMIZE"})
    bad = {"hyperstudy_path", "hstpy_path", "altair_home", "hst_gen_radioss", "hst_optimization", "gen_radioss", "optimization"}
    for name, req in f.FEATURES.items():
        if name in f.LEGACY_FEATURES:
            continue
        assert not bad & set(_req_tokens(req)), name
    for job, req in f.JOB_FEATURE.items():
        if job in f.LEGACY_JOBS:
            continue
        assert not bad & set(_req_tokens(req)), job
    # special missing 함수와 그 함수들이 부르는 판정 함수(모듈 안 전부 + 캡처·모듈 확인) 소스에 HyperStudy 토큰 없음
    fns = [obj for _n, obj in inspect.getmembers(f, inspect.isfunction) if obj.__module__ == f.__name__]
    fns += [schema_capture.capture_missing, surrogate.missing_modules]
    assert set(f._SPECIAL_MISSING.values()) <= set(fns) and f.fem_verify_missing in fns
    for fn in fns:
        src = inspect.getsource(fn)
        for tok in FORBIDDEN:
            assert tok not in src, (fn.__name__, tok)
    # 레거시 정의 자체는 그대로(FeatureReq 불변 — 설정한 사이트 동작 유지)
    assert f.FEATURES["train_doe"].launchers == ("gen_radioss",) and f.FEATURES["optimize"].altair == ("hstpy_path", "simlab_path")
    assert f.JOB_FEATURE["OPTIMIZE"] is f.FEATURES["optimize"]


def _no_hyperstudy_settings(tmp_path: Path, fake_tools: dict[str, str]) -> dict:
    """V-ON-2 설정: altair hyperstudy·hstpy = "", hst_* null, launcher gen_radioss·optimization 없음, 나머지는 가짜 도구로 전부 구성."""
    d = make_phase2_settings(tmp_path, fake_tools)
    d["altair"] = {**d["altair"], "hyperstudy_path": "", "hstpy_path": "", "altair_home": ""}
    cap_tcl = tmp_path / "resources" / "contour_capture.tcl"
    cap_tcl.write_text("# fake capture\n")
    launchers = {k: {"script": v[0], "core": v[1]} for k, v in LAUNCHERS.items() if k == "extract_params"}
    ext_tcl = tmp_path / "resources" / "contour_extract.tcl"  # 결과 3D 컨투어(geometry-view.md §13, 기본 꺼짐 → 여기서 켬)
    ext_tcl.write_text("# fake extract\n")
    d["resources"] = {**d["resources"], "launchers": launchers, "contour_capture_tcl": str(cap_tcl),
                      "contour_extract_tcl": str(ext_tcl)}
    d["contour3d"] = {"enabled": True}
    d["commands"] = {**d["commands"], **{k: v for k, v in PHASE2_COMMANDS.items() if not k.startswith("hst_")},
                     "hst_gen_radioss": None, "hst_optimization": None,
                     "response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]}
    d["hpc"] = pbs_command_cfg(fake_tools, d["storage"]["ai_root"])
    d["geometry"] = {"engine": "native", "paicad_path": fake_tools["fake_paicad"]}
    d["fem_verify"] = {"enabled": True}
    return d


def test_v_on_2_hyperstudy_unset_only_legacy_disabled(tmp_path, fake_tools):
    from physicsai_core.config import load_config_dict
    from physicsai_core.features import LEGACY_FEATURES, feature_status

    d = _no_hyperstudy_settings(tmp_path, fake_tools)
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    st = feature_status(lc.settings, True)
    off = {k for k, v in st.items() if not v["enabled"]}
    assert off == {"train_doe", "optimize"}, {k: st[k]["missing"] for k in off}
    assert {k for k, v in st.items() if v.get("legacy")} == set(LEGACY_FEATURES)
    assert "altair.hyperstudy_path" in st["train_doe"]["missing"] and "commands.hst_optimization" in st["optimize"]["missing"]
    for k in ("train_extract", "train_doe_platform", "train_resp", "curation_h3d", "curation_t01", "dataset_create", "evaluate",
              "predict", "predict_parametric", "predict_mesh_only", "predict_responses", "contour_capture", "optimize_builtin",
              "geometry_native", "fem_verify", "fem_verify_rebuild", "train_solve", "spdm_import", "geometry_native_shell",
              "geometry_view", "geometry_view_shell", "contour3d", "equiv_check", "equiv_check_extract"):
        assert st[k] == {"enabled": True, "missing": []}, (k, st[k])


def test_v_on_2_status_legacy_flag_exactly_two(client):
    from physicsai_test_support import API, H

    st = client.get(f"{API}/status", headers=H("tok-power")).json()
    legacy = {k for k, v in st["features"].items() if v.get("legacy")}
    assert legacy == {"train_doe", "optimize"}
    assert all("legacy" not in v for k, v in st["features"].items() if k not in legacy)  # 기본 false는 생략(기존 모양 유지)
    so = st["surrogate_opt"]
    assert so["algorithms"] == ["ego", "ga", "nsga2"] and so["verifications"] == ["loop", "none"]
    assert so["ga_max_evals"] == 100000 and so["max_levels"] == 8 and so["default_algorithm"] == "ego"
    assert so["algo_defaults"]["ga"] == {"pop_size": None, "generations": 150, "crossover_prob": 0.9, "mutation_prob": None,
                                         "eta_c": 15.0, "eta_m": 20.0}
    assert so["algo_defaults"]["nsga2"]["generations"] == 200 and so["algo_defaults"]["nsga2"]["eta_c"] == 20.0


def test_v_on_3_env_check_legacy_skip_warn_fail(tmp_path):
    from physicsai_core.env_check import LEGACY_SKIP_MESSAGE
    from physicsai_worker import env_check as ec

    sk = ec._exec_item("hyperstudy_path", "")
    assert (sk["status"], sk["message"]) == ("SKIP", "선택(레거시 HyperStudy) — 미설정") == ("SKIP", LEGACY_SKIP_MESSAGE)
    assert ec._exec_item("hstpy_path", "")["status"] == "SKIP"
    assert ec._exec_item("simlab_path", "")["status"] == "WARN" and ec._exec_item("simlab_path", "")["message"] == "미설정"
    missing = str(tmp_path / "nope" / "hstbatch.exe")
    assert ec._exec_item("hyperstudy_path", missing)["status"] == "FAIL"
    # 프로브: argv가 설정됐어도 실행 파일 경로가 비면 SKIP(레거시만), 경로가 있는데 파일이 없으면 FAIL
    w = SimpleNamespace(settings=SimpleNamespace(env_check=SimpleNamespace(probes=SimpleNamespace(
        hstbatch=["{hstbatch}", "-h"], hstpy=["{hstpy}", "-h"], simlab=["{simlab}", "-h"]))))
    p = ec._probe(w, "hstbatch", "", None, {})
    assert (p["status"], p["message"]) == ("SKIP", LEGACY_SKIP_MESSAGE)
    assert ec._probe(w, "hstpy", "", None, {})["status"] == "SKIP"
    assert ec._probe(w, "hstbatch", missing, None, {})["status"] == "FAIL"
    assert ec._probe(w, "simlab", "", None, {})["status"] == "FAIL"


def test_v_on_3_example_config_hyperstudy_blank_with_comment():
    text = (REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8")
    ex = yaml.safe_load(text)
    assert ex["altair"]["hyperstudy_path"] == ""
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("hyperstudy_path:"))
    assert "선택(레거시). 비우면 ①-3 HyperStudy 생성·⑥ 원본 최적화만 꺼짐" in line
    assert ex["commands"]["hst_optimization"] and ex["commands"]["hst_gen_radioss"]  # 명령 템플릿은 유지
    so = ex["surrogate_opt"]
    assert so["default_algorithm"] == "ego" and so["ga_max_evals"] == 100000 and so["max_levels"] == 8
    for k in ("ga_pop_size", "ga_generations", "nsga2_pop_size", "nsga2_generations", "ga_crossover_prob", "ga_eta_c",
              "nsga2_eta_c", "ga_eta_m", "ga_stall_generations", "ga_archive_max"):
        assert k in so, k
