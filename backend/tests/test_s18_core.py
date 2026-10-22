"""V3-S18-1: ① 플랫폼 DOE 표본 `doe_platform.check`/`build`(phase3 §23.4·§23.5) — check run 수 = build 행 수(8 kind × k = 2~11),
lhs_opt 대체 검증(count·seed 오류 동일), platform_max_runs 상한 문구, problems·notes 코드, ①-2 표 → parameters/tpl_params 변환,
영향도 분기(doe_influence → batch_influence), 설정 검증(platform_run_root·platform_max_runs)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from physicsai_core.sampling import registry
from physicsai_core.stage1_train_data import doe_platform
from physicsai_core.stage4_predict.batch_matrix import BatchShapeError

SETTINGS = SimpleNamespace(train_data=SimpleNamespace(platform_max_runs=500), predict_batch=SimpleNamespace(table_max_bytes=1 << 20),
                           predict=SimpleNamespace(integer_rounding="half_up"))
INPUTS = {"lhs": {"count": 20, "seed": 2}, "lhs_opt": {"count": 14, "seed": 3}, "sobol": {"count": 16, "seed": 4},
          "halton": {"count": 12, "seed": 5}, "random": {"count": 9, "seed": 6},
          "fullfact": {}, "fracfact": {"resolution": 4}, "pb": {}, "bbd": {}, "ccd": {"alpha": "inscribed"}}


def _setup(k: int, *, fmt: str = "%8.3f") -> dict:
    params = [{"name": f"P{i}", "nominal": 5.0, "min": 0.0, "max": 10.0, "use": True, "format": fmt, "unit": ""}
              for i in range(1, k + 1)]
    params.append({"name": "OFF", "nominal": 1.0, "min": 0.0, "max": 2.0, "use": False, "format": "%3i", "unit": ""})
    return {"parameters": params, "tpl_params": None}


def _codes(items: list[dict]) -> list[str]:
    return [x["code"] for x in items]


@pytest.mark.parametrize("kind", registry.PLATFORM_KINDS)  # train_doe(표본표 재사용)는 samples 입력이 필요해 test_doe_reuse에서
def test_v3_s18_1_check_runs_equal_build_rows(kind):
    assert doe_platform.KINDS == ("lhs_opt", "sobol", "halton", "lhs", "random", "fullfact", "fracfact", "pb", "bbd", "ccd", "table",
                                  "train_doe")  # equiv-check.md Q1: 표본표 재사용 + doe-methods.md DM-C3: halton·random·table
    for k in range(2, 12):
        s = {"kind": kind, **INPUTS[kind]}
        chk = doe_platform.check(s, _setup(k), SETTINGS)
        bld = doe_platform.build(s, _setup(k), SETTINGS)
        assert chk.run_count == bld.run_count, (kind, k)
        assert _codes(chk.problems) == _codes(bld.problems), (kind, k)
        assert chk.doe_type == bld.doe_type == registry.METHODS[kind][0] and chk.desc_id == f"td_{kind}"
        assert chk.label == registry.METHODS[kind][1] and chk.input == bld.input
        if bld.ok:
            assert [r.run_key for r in bld.rows] == [f"run__{n:05d}" for n in range(1, bld.run_count + 1)]
            assert set(bld.rows[0].values) == {f"P{i}" for i in range(1, k + 1)}  # 사용 행만
            assert bld.sampling_record(with_meta=True)["meta"] == bld.meta and bld.meta
    # 결정적: 같은 입력이면 같은 행
    a = doe_platform.build({"kind": kind, **INPUTS[kind]}, _setup(3), SETTINGS)
    b = doe_platform.build({"kind": kind, **INPUTS[kind]}, _setup(3), SETTINGS)
    assert [r.values for r in a.rows] == [r.values for r in b.rows]


def test_v3_s18_1_lhs_opt_substitute_validation_same_errors():
    st = _setup(3)
    for inp in ({"count": 600, "seed": 1}, {"count": 2, "seed": 1}):
        chk = doe_platform.check({"kind": "lhs_opt", **inp}, st, SETTINGS)
        lhs = doe_platform.check({"kind": "lhs", **inp}, st, SETTINGS)
        bld = doe_platform.build({"kind": "lhs_opt", **inp}, st, SETTINGS)
        assert chk.problems == lhs.problems and _codes(chk.problems) == _codes(bld.problems)
        assert chk.run_count == bld.run_count and chk.meta == {}  # 대체 검증 meta는 버림(워커가 채움)
    big = doe_platform.check({"kind": "lhs_opt", "count": 600}, st, SETTINGS)
    assert big.problems == [{"code": "TOO_MANY_ROWS", "message": "조합 수는 최대 500개입니다"}]
    for bad in ({"count": "x"}, {"count": 4, "seed": True}):
        for kind in ("lhs_opt", "lhs"):
            with pytest.raises(BatchShapeError):
                doe_platform.check({"kind": kind, **bad}, st, SETTINGS)
    assert doe_platform.check({"kind": "lhs_opt", "count": 4}, st, SETTINGS).input == {"count": 4, "seed": 1, "criterion": "maximin"}


def test_v3_s18_1_max_runs_problems_notes():
    small = SimpleNamespace(**{**vars(SETTINGS), "train_data": SimpleNamespace(platform_max_runs=100)})
    ff = doe_platform.check({"kind": "fullfact", "levels": {"P1": 10, "P2": 10}}, _setup(3), small)
    assert ff.problems == [{"code": "TOO_MANY_ROWS", "message": "전체 요인 run 수 200개가 상한 100개를 넘습니다 — 수준 수를 줄이세요"}]
    assert _codes(doe_platform.check({"kind": "sobol", "count": 6}, _setup(3), SETTINGS).problems) == ["COUNT_NOT_POW2"]
    assert _codes(doe_platform.check({"kind": "fullfact", "levels": {"P1": 1}}, _setup(3), SETTINGS).problems) == ["LEVELS_INVALID"]
    assert _codes(doe_platform.check({"kind": "bbd"}, _setup(2), SETTINGS).problems) == ["DESIGN_UNSUPPORTED"]
    assert _codes(doe_platform.check({"kind": "fracfact"}, _setup(2), SETTINGS).notes) == ["FULL_FACTORIAL_USED", "INFLUENCE_TOO_FEW"]
    assert "BBD_PAIRWISE" in _codes(doe_platform.check({"kind": "bbd"}, _setup(6), SETTINGS).notes)
    # 정수 형식 좁은 범위 → 반올림 중복 안내
    st = _setup(2, fmt="%3i")
    for p in st["parameters"][:2]:
        p.update(min=2.85, max=3.15, nominal=3.0)
    assert "DUPLICATE_ROWS" in _codes(doe_platform.check({"kind": "ccd"}, st, SETTINGS).notes)


def test_v3_s18_1_setup_conversion_integer_applied_and_shape_errors():
    st = {"parameters": [
        {"name": "THK_1", "nominal": 3.0, "min": 2.85, "max": 3.15, "use": True, "format": "%3i", "unit": "mm"},
        {"name": "RIB_H", "nominal": 12.5, "min": 11.875, "max": 13.125, "use": True, "format": "%8.3f", "unit": ""},
        {"name": "bad name", "nominal": None, "min": None, "max": None, "use": False, "format": "%3i", "unit": ""}],
        "tpl_params": [{"var": "var_1", "name": "THK_1", "format": "%3i"}, {"var": "var_2", "name": "RIB_H", "format": "%8.3f"}]}
    params, tpl = doe_platform.design_inputs(st)
    assert [p["name"] for p in params] == ["THK_1", "RIB_H"] and tpl == st["tpl_params"]
    assert doe_platform.design_inputs({**st, "tpl_params": None})[1] == st["tpl_params"]  # 없으면 사용 행으로 같은 모양
    plan = doe_platform.build({"kind": "lhs", "count": 6, "seed": 7}, st, SETTINGS)
    for r in plan.rows:
        assert r.applied_values["THK_1"] == 3 and r.applied_values["RIB_H"] == r.values["RIB_H"]
        assert 2.85 <= r.values["THK_1"] <= 3.15
    for bad in ({"kind": "table"}, {"kind": "train_doe", "doe_id": "d"}, {"kind": "lhs", "count": 4, "ranges": {}},
                {"kind": "sobol", "count": 4, "continue_from": "b"}, {"kind": "pb", "levels": {}}, {"kind": "nope"}):
        with pytest.raises(BatchShapeError):
            doe_platform.check(bad, st, SETTINGS)


def test_v3_s18_1_influence_branch():
    assert registry.doe_influence("LHS_OPT", {"count": 4}) == ("formal", None)
    assert registry.doe_influence("SOBOL", {}) == ("formal", None)
    assert registry.doe_influence("PB", {}) == ("reference", registry.NOTE_PB)
    assert registry.doe_influence("FRACFACT", {"resolution": 4}) == ("reference", registry.NOTE_FRAC_IV)
    assert registry.doe_influence("CCD", {"alpha": "face"}) == ("reference", registry.NOTE_RSM)
    assert registry.doe_influence("TYPE_LATINHYPERCUBE", {}) == ("formal", None)  # HyperStudy 유형 무변경
    assert registry.doe_influence("TYPE_FRACFACT", {"RESOLUTION": "3"})[1] == registry.NOTE_FRAC_III


def test_v3_s18_1_config_validation(settings_dict):
    from physicsai_core.config import load_config_dict

    def issues(**td):
        d = {**settings_dict, "train_data": {**(settings_dict.get("train_data") or {}), **td}}
        return {i.key for i in load_config_dict(d, environ={}).issues}

    assert not {k for k in issues() if k.startswith("train_data.")}
    s = load_config_dict(settings_dict, environ={}).settings.train_data
    assert (s.doe_generator_default, s.platform_parallel_default, s.platform_max_runs, s.platform_run_root) == \
        ("platform", 4, 500, "approaches/doe_1")
    assert "train_data.platform_run_root" in issues(platform_run_root="other/doe_1")       # run_dir_glob 불일치
    assert "train_data.platform_run_root" in issues(platform_run_root="../x")
    assert "train_data.platform_run_root" in issues(platform_run_root="C:/abs")
    assert "train_data.platform_run_root" in issues(platform_run_root="approaches/a/b")    # 깊이 다름(* 는 '/'를 넘지 않음)
    assert "train_data.platform_run_root" not in issues(platform_run_root="approaches/doe_2")
    assert "train_data.platform_run_root" in issues(platform_run_root="approaches/plat_2")     # 기본 패턴은 doe_*만
    # run_dir_glob: 문자열도 허용(하위호환) — 목록 중 하나와 맞으면 통과(이슈 #7)
    assert "train_data.platform_run_root" not in issues(platform_run_root="approaches/plat_2", run_dir_glob="approaches/*/run_*")
    # 옛 기본 문자열은 새 기본 목록으로 정규화(이슈 #7) — plat_2는 doe_*가 아니라 불일치
    assert "train_data.platform_run_root" in issues(platform_run_root="approaches/plat_2", run_dir_glob="approaches/*/run__*")
    assert not {k for k in issues(run_dir_glob="approaches/*/run__*") if k.startswith("train_data.")}
    assert not {k for k in issues(run_dir_glob=["x/run__*", "approaches/doe_*/run__*"]) if k.startswith("train_data.")}
    assert "train_data.platform_run_root" in issues(run_dir_glob=["x/run__*"])
    assert "train_data.run_dir_glob" in issues(run_dir_glob=["../approaches/*/run__*"])
    assert "train_data.run_dir_glob" in issues(run_dir_glob=[])
    s2 = load_config_dict({**settings_dict, "train_data": {"run_dir_glob": "a/*/run__*"}}, environ={}).settings.train_data
    assert s2.run_dir_globs() == ["a/*/run__*"] and s.run_dir_globs() == ["approaches/doe_*/run__*", "*/approaches/doe_*/run__*"]
    assert "train_data.platform_max_runs" in issues(platform_max_runs=3000)                # > max_runs
    assert "train_data.platform_parallel_default" in issues(platform_parallel_default=0)
    assert "train_data.doe_generator_default" in issues(doe_generator_default="native")
