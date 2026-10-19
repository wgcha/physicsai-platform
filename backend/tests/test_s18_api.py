"""V3-S18-2: ①-3 TD_DOE_GEN params 확장(phase3 §23.4) — generator 추론, 금지 조합 422, DOE_SAMPLING_INVALID problems,
생성 warnings(notes), 저장 params(B8), train_does 열, multi_execution 기본·상한, 방식별 기능 판정, /status 키."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from helpers_stage1 import extract_and_tpl, make_inputs, study, submit
from physicsai_test_support import API, H, _p2_env

PW, P = H("tok-power", write=True), H("tok-power")


def _env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, overrides, name):
    gen = _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, overrides)
    c, mk, ai, lc, _d = next(gen)
    w = mk()
    sid = study(c, name)
    cad, _ = make_inputs(ai / name)
    extract_and_tpl(c, w, sid, cad)
    return gen, c, ai, sid


def _post(c, sid, params):
    return c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": params})


def _assem(ai: Path, name: str) -> str:
    return str(ai / name / "00_inbox" / "radioss_assem")


def _ok(c, sid, params) -> dict:
    """생성 성공 확인 후 바로 취소(Study당 같은 종류 작업 1개 — 다음 생성 시험이 STUDY_JOB_BUSY가 되지 않게)."""
    j = submit(c, sid, "TD_DOE_GEN", params)
    r = c.post(f"{API}/jobs/{j['id']}/cancel", headers=H("tok-admin", write=True))
    assert r.status_code == 202, r.text
    return j


def _close(gen):
    for _ in gen:
        pass


def test_v3_s18_2_params_inference_forbidden_and_records(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    gen, c, ai, sid = _env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {}, "sa1")
    try:
        A = _assem(ai, "sa1")
        # 생략 + sampling → platform, 저장 params(B8)
        j = _ok(c, sid, {"sampling": {"kind": "lhs_opt", "count": 6, "seed": 2}, "radioss_assem_path": A})
        p = j["params"]
        assert p == {"generator": "platform", "doe_id": p["doe_id"], "doe_label": "최적화 LHS", "doe_type": "LHS_OPT",
                     "sampling": {"kind": "lhs_opt", "count": 6, "seed": 2, "criterion": "maximin"}, "num_runs": 6,
                     "multi_execution": 4, "on_run_failure": "fail", "radioss_assem_path": A}
        with engine.connect() as conn:
            row = conn.execute(text("select generator, doe_label, doe_type, options, num_runs_requested, sampling, multi_execution"
                                    " from train_does where id=:d"), {"d": p["doe_id"]}).one()
        assert tuple(row) == ("PLATFORM", "최적화 LHS", "LHS_OPT", {"count": 6, "seed": 2, "criterion": "maximin"}, 6,
                              {"kind": "lhs_opt", "input": {"count": 6, "seed": 2, "criterion": "maximin"}, "meta": None},
                              4)
        doe = c.get(f"{API}/train-does/{p['doe_id']}", headers=P).json()
        assert doe["generator"] == "platform" and doe["gen"] == {"total": 0, "pending": 0, "running": 0, "done": 0, "failed": 0}
        assert doe["sampling"] == {"kind": "lhs_opt", "label": "최적화 LHS", "desc_id": "td_lhs_opt", "meta": None}
        # 생략 + doe_label → hyperstudy(기존 키 + generator)
        j = _ok(c, sid, {"doe_label": "LatinHyperCube", "num_runs": 3, "options": {"RANDOM_SEED": 7},
                                          "multi_execution": 2, "radioss_assem_path": A})
        hp = j["params"]
        assert hp["generator"] == "hyperstudy" and hp["doe_type"] == "TYPE_LATINHYPERCUBE" and hp["num_runs"] == 3
        assert hp["options"] == {"RANDOM_SEED": 7} and hp["multi_execution"] == 2 and "sampling" not in hp
        with engine.connect() as conn:
            assert conn.execute(text("select generator, sampling from train_does where id=:d"), {"d": hp["doe_id"]}).one() == \
                ("HYPERSTUDY", None)
        hd = c.get(f"{API}/train-does/{hp['doe_id']}", headers=P).json()
        assert hd["generator"] == "hyperstudy" and hd["sampling"] is None and hd["gen"] is None
        # hyperstudy multi 기본 1(기존)
        j = _ok(c, sid, {"doe_label": "LatinHyperCube", "options": {"RANDOM_SEED": 1}, "radioss_assem_path": A})
        assert j["params"]["multi_execution"] == 1
        # 금지 조합 5종 + platform sampling 필수 + hyperstudy doe_label 필수
        smp = {"kind": "lhs", "count": 4}
        for params, loc in (({"sampling": smp, "doe_label": "LatinHyperCube"}, "doe_label"),
                            ({"sampling": smp, "num_runs": 4}, "num_runs"),
                            ({"sampling": smp, "options": {}}, "options"),
                            ({"generator": "hyperstudy", "doe_label": "LatinHyperCube", "sampling": smp}, "sampling"),
                            ({"doe_label": "LatinHyperCube", "on_run_failure": "continue"}, "on_run_failure"),
                            ({"generator": "platform"}, "sampling"),
                            ({"generator": "hyperstudy"}, "doe_label")):
            r = _post(c, sid, {**params, "radioss_assem_path": A})
            assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS", (params, r.text)
            assert r.json()["detail"]["errors"][0]["loc"] == ["params", loc], params
        # 모양: 추가 키·범위
        for bad in ({"kind": "lhs", "count": 4, "ranges": {}}, {"kind": "sobol", "count": 4, "continue_from": "x"},
                    {"kind": "table", "text": "a"}, {"kind": "lhs", "count": 1}, {"kind": "sobol", "count": 2}):
            assert _post(c, sid, {"sampling": bad, "radioss_assem_path": A}).status_code == 422, bad
        # DOE_SAMPLING_INVALID problems(S15 코드, 상한 = platform_max_runs)
        r = _post(c, sid, {"sampling": {"kind": "sobol", "count": 6}, "radioss_assem_path": A})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "DOE_SAMPLING_INVALID"
        assert [x["code"] for x in r.json()["detail"]["problems"]] == ["COUNT_NOT_POW2"]
        r = _post(c, sid, {"sampling": {"kind": "lhs_opt", "count": 501}, "radioss_assem_path": A})
        assert r.json()["detail"]["problems"] == [{"code": "TOO_MANY_ROWS", "message": "조합 수는 최대 500개입니다"}]
        r = _post(c, sid, {"sampling": {"kind": "bbd"}, "radioss_assem_path": A})  # 변수 2개
        assert [x["code"] for x in r.json()["detail"]["problems"]] == ["DESIGN_UNSUPPORTED"]
        # 생성 warnings = notes(막지 않음)
        j = _ok(c, sid, {"sampling": {"kind": "pb"}, "radioss_assem_path": A})
        codes = [x["code"] for x in j["warnings"]]
        assert "DUPLICATE_ROWS" in codes  # 정수 형식(%3i) 좁은 범위 → 반올림 중복 안내
        assert j["params"]["num_runs"] == 8 and j["params"]["sampling"] == {"kind": "pb"}
        # multi_execution 상한
        r = _post(c, sid, {"sampling": smp, "multi_execution": 9, "radioss_assem_path": A})
        assert r.status_code == 422 and r.json()["detail"]["errors"][0]["loc"] == ["params", "multi_execution"]
        assert _ok(c, sid, {"sampling": smp, "multi_execution": 8, "on_run_failure": "continue",
                                             "radioss_assem_path": A})["params"]["on_run_failure"] == "continue"
        # starter 검사는 두 방식 모두(기존 409)
        empty = ai / "sa1" / "00_inbox" / "empty_assem"
        empty.mkdir()
        r = _post(c, sid, {"sampling": smp, "radioss_assem_path": str(empty)})
        assert r.status_code == 409 and r.json()["detail"]["missing"] == ["RADIOSS_STARTER"]
        # /status
        st = c.get(f"{API}/status", headers=P).json()
        conf = st["limits"]["configured"]
        assert (conf["doe_generator_default"], conf["doe_platform_parallel_default"], conf["doe_platform_max_runs"]) == \
            ("platform", 4, 500)
        assert st["features"]["train_doe_platform"] == {"enabled": True, "missing": []}
        assert st["features"]["train_doe"]["enabled"] is True
    finally:
        _close(gen)


def test_v3_s18_2_feature_by_generator(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """platform은 geom_update·simlab만(HyperStudy 자원 없어도 생성 가능), hyperstudy는 그 반대도 독립."""
    t1 = tmp_path / "a"
    t1.mkdir()
    gen, c, ai, sid = _env(t1, fake_tools, engine, fake_dashboard, monkeypatch,
                           {"commands": {"hst_gen_radioss": None}}, "sf1")
    try:
        A = _assem(ai, "sf1")
        assert _ok(c, sid, {"sampling": {"kind": "lhs", "count": 3}, "radioss_assem_path": A})
        r = _post(c, sid, {"doe_label": "LatinHyperCube", "radioss_assem_path": A})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"
        assert r.json()["detail"]["missing"] == ["commands.hst_gen_radioss"]
        st = c.get(f"{API}/status", headers=P).json()["features"]
        assert st["train_doe"]["enabled"] is False and st["train_doe_platform"]["enabled"] is True
    finally:
        _close(gen)
    t2 = tmp_path / "b"
    t2.mkdir()
    gen, c, ai, sid = _env(t2, fake_tools, engine, fake_dashboard, monkeypatch, {"commands": {"geom_update": None}}, "sf2")
    try:
        A = _assem(ai, "sf2")
        r = _post(c, sid, {"sampling": {"kind": "lhs", "count": 3}, "radioss_assem_path": A})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"
        assert r.json()["detail"]["missing"] == ["commands.geom_update"]
        assert _ok(c, sid, {"doe_label": "LatinHyperCube", "options": {"RANDOM_SEED": 1}, "radioss_assem_path": A})["params"]["generator"] == \
            "hyperstudy"
        st = c.get(f"{API}/status", headers=P).json()["features"]
        assert st["train_doe_platform"] == {"enabled": False, "missing": ["commands.geom_update"]}
    finally:
        _close(gen)
    t3 = tmp_path / "c"
    t3.mkdir()
    gen, c, ai, sid = _env(t3, fake_tools, engine, fake_dashboard, monkeypatch, {"resources": {"hypermesh_include_tcl": ""}}, "sf3")
    try:  # mesh가 {include_tcl}을 쓰면 include TCL 자원도 필요
        r = _post(c, sid, {"sampling": {"kind": "lhs", "count": 3}, "radioss_assem_path": _assem(ai, "sf3")})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "RESOURCE_NOT_CONFIGURED"
        assert "resources.hypermesh_include_tcl" in r.json()["detail"]["missing"]
    finally:
        _close(gen)
