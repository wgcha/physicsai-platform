"""이슈 #7(서버 버그): hyperstudy 모드 DG_SCAN이 실제 HyperStudy 출력 구조에서 OUTPUT_MISSING.

실제 구조 `D/HST_GEN_RADIOSS_INPUT/approaches/doe_1/run__N/{m_1,m_2,m_3}`(+ 제외할 공칭 run `approaches/setup_1-def/run__00001`,
`reports/doe_1`), m_1·m_2에 EPS_mesh_0000.rad, m_3에 `<조립>_0000.rad`. `train_data.run_dir_glob`은 패턴 목록(문자열 허용),
기본 `["approaches/doe_*/run__*", "*/approaches/doe_*/run__*"]`. 패턴끼리 같은 run_key가 겹치면 그 run은 제외 + 경고.
HyperStudy 생성 코드는 무변경 — DG_SCAN만.
"""

from __future__ import annotations

from pathlib import Path

from helpers_stage1 import doe_gen, extract_and_tpl, job, make_inputs, study, submit
from physicsai_test_support import API, H, _p2_env

P = H("tok-power")


def _prep(c, w, ai: Path, name: str) -> str:
    sid = study(c, name)
    cad, _ = make_inputs(ai / name)
    extract_and_tpl(c, w, sid, cad)
    return sid


def test_issue7_server_layout_scanned_nominal_excluded(p2_env, monkeypatch):
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid = _prep(c, w, ai, "hs1")
    monkeypatch.setenv("FAKE_HST_LAYOUT", "server")
    jd = doe_gen(c, w, sid, ai, "hs1", num_runs=3)
    doe_id = jd["result"]["doe_id"]
    D = ai / "hs1" / "01_train" / "doe" / doe_id
    assert (D / "HST_GEN_RADIOSS_INPUT" / "approaches" / "setup_1-def" / "run__00001" / "m_3" / "drop_0000.rad").is_file()
    runs = c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()
    assert [r["run_key"] for r in runs] == ["run__00001", "run__00002", "run__00003"]       # 공칭 run 제외(doe_* 패턴)
    assert all(r["starter_name"] == "drop_0000.rad" for r in runs)                          # EPS_mesh(m_1·m_2) 제외
    assert all(r["input_display_path"].replace("\\", "/").endswith(
        f"HST_GEN_RADIOSS_INPUT/approaches/doe_1/{r['run_key']}/m_3") for r in runs)
    assert jd["result"]["skipped_runs"] == [] and not [x for x in jd["warnings"] if x["code"] == "RUN_INPUT_INVALID"]
    doe = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert doe["status"] == "READY" and doe["sample_status"] == "PARSED" and doe["run_count"] == 3


def test_issue7_same_run_key_in_two_patterns_excluded(p2_env, monkeypatch):
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid = _prep(c, w, ai, "hs2")
    monkeypatch.setenv("FAKE_HST_LAYOUT", "server")
    j = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LatinHyperCube", "num_runs": 3, "options": {"RANDOM_SEED": 7},
                                      "multi_execution": 2, "radioss_assem_path": str(ai / "hs2" / "00_inbox" / "radioss_assem")})
    D = ai / "hs2" / "01_train" / "doe" / j["result"]["doe_id"]
    dup = D / "approaches" / "doe_1" / "run__00002" / "m_3"                                 # 첫 패턴에도 같은 run_key
    dup.mkdir(parents=True)
    (dup / "drop_0000.rad").write_text("#dup\n")
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    jd = job(c, j["id"])
    runs = c.get(f"{API}/train-does/{jd['result']['doe_id']}/runs", headers=P).json()
    assert [r["run_key"] for r in runs] == ["run__00001", "run__00003"]
    warn = [x["message"] for x in jd["warnings"] if x["code"] == "RUN_INPUT_INVALID"]
    assert len(warn) == 1 and "run__00002" in warn[0] and "여러 개" in warn[0]


def _env_glob(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, glob_value):
    return _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {"train_data": {"run_dir_glob": glob_value}})


def test_issue7_legacy_default_string_normalized_server_layout(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """서버 platform.yaml이 옛 기본 문자열 그대로여도(사용자 수정 없음) 실제 구조를 찾는다 — 설정 경고 없음."""
    gen = _env_glob(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, "approaches/*/run__*")
    c, mk, ai, lc, _d = next(gen)
    try:
        td = lc.settings.train_data
        assert td.run_dir_globs() == ["approaches/doe_*/run__*", "*/approaches/doe_*/run__*"] and not td.run_dir_glob_user_string()
        assert not [i for i in lc.issues if i.key.startswith("train_data.")]
        w = mk()
        sid = _prep(c, w, ai, "hs3")
        monkeypatch.setenv("FAKE_HST_LAYOUT", "server")
        jd = doe_gen(c, w, sid, ai, "hs3", num_runs=2)
        assert jd["result"]["run_count"] == 2 and jd["result"]["skipped_runs"] == []
        monkeypatch.delenv("FAKE_HST_LAYOUT")
        assert doe_gen(c, w, sid, ai, "hs3", num_runs=2)["result"]["run_count"] == 2       # 기존 구조(D/approaches/doe_1)도
    finally:
        for _ in gen:
            pass


def test_issue7_user_string_fallback_prefix_excludes_setup(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """사용자 문자열은 그대로, 0개일 때만 `*/` 접두 변형을 한 번 더 — 공칭 run(상위 setup_*)은 제외."""
    gen = _env_glob(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, "approaches/*/run__0*")
    c, mk, ai, lc, _d = next(gen)
    try:
        assert lc.settings.train_data.run_dir_globs() == ["approaches/*/run__0*"]
        w = mk()
        sid = _prep(c, w, ai, "hs4")
        jd = doe_gen(c, w, sid, ai, "hs4", num_runs=2)                                      # 기존 구조: 패턴 그대로 맞음
        assert jd["result"]["run_count"] == 2
        monkeypatch.setenv("FAKE_HST_LAYOUT", "server")                                     # 0개 → */approaches/*/run__0*
        jd = doe_gen(c, w, sid, ai, "hs4", num_runs=3)
        runs = c.get(f"{API}/train-does/{jd['result']['doe_id']}/runs", headers=P).json()
        assert [r["run_key"] for r in runs] == ["run__00001", "run__00002", "run__00003"]   # setup_1-def/run__00001 제외
        assert all("/approaches/doe_1/" in r["input_display_path"].replace("\\", "/") for r in runs)
        assert jd["result"]["skipped_runs"] == []
    finally:
        for _ in gen:
            pass


def test_issue7_user_string_no_fallback_when_found_or_list(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """목록 설정은 접두 변형을 하지 않는다(0개면 OUTPUT_MISSING 그대로)."""
    gen = _env_glob(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, ["approaches/*/run__0*"])
    c, mk, ai, lc, _d = next(gen)
    try:
        assert not lc.settings.train_data.run_dir_glob_user_string()
        w = mk()
        sid = _prep(c, w, ai, "hs5")
        monkeypatch.setenv("FAKE_HST_LAYOUT", "server")
        jd = doe_gen(c, w, sid, ai, "hs5", num_runs=2, expect="FAILED")
        assert jd["failure_code"] == "OUTPUT_MISSING" and "approaches/*/run__0*" in jd["failure_message"]
    finally:
        for _ in gen:
            pass
