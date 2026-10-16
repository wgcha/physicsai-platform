"""V3-S9-5: batch_matrix 골든 — LHS(seed·층·정수 반영·out_of_range), 표(탭·쉼표·BOM·열 순서·doe 열·오류), train_doe(doe_no = run 번호)."""

from __future__ import annotations

import pytest

from physicsai_core.stage4_predict import batch_matrix as bm

P = [{"name": "THK_1", "min": 2.0, "max": 5.0}, {"name": "RIB_N", "min": 4.0, "max": 8.0}]
T = [{"name": "THK_1", "format": "%5.2f"}, {"name": "RIB_N", "format": "%3i"}]


def _m(source, **kw):
    args = {"parameters": P, "tpl_params": T, "max_runs": 200, "table_max_bytes": 1024}
    args.update(kw)
    return bm.build_matrix(source, **args)


def _codes(m):
    return [p["code"] for p in m.problems]


# ---- LHS ---------------------------------------------------------------------------------------


def test_lhs_golden_seed1_n4():
    m = _m({"kind": "lhs", "count": 4, "seed": 1, "ranges": {"RIB_N": [3.0, 9.0]}})
    assert m.ok and m.source_kind == "LHS"
    assert m.source_meta == {"count": 4, "seed": 1, "ranges": {"THK_1": [2.0, 5.0], "RIB_N": [3.0, 9.0]}}
    assert [r.as_dict() for r in m.rows] == [
        {"doe_no": 1, "run_key": "run__00001", "values": {"THK_1": 4.441301769304566, "RIB_N": 6.04252121478301},
         "applied_values": {"THK_1": 4.441301769304566, "RIB_N": 6}, "out_of_range": []},
        {"doe_no": 2, "run_key": "run__00002", "values": {"THK_1": 2.371576315318956, "RIB_N": 8.753647655879805},
         "applied_values": {"THK_1": 2.371576315318956, "RIB_N": 9}, "out_of_range": ["RIB_N"]},
        {"doe_no": 3, "run_key": "run__00003", "values": {"THK_1": 3.8371182985915535, "RIB_N": 3.6491506018575803},
         "applied_values": {"THK_1": 3.8371182985915535, "RIB_N": 4}, "out_of_range": ["RIB_N"]},
        {"doe_no": 4, "run_key": "run__00004", "values": {"THK_1": 3.2386947295420723, "RIB_N": 5.643420123686913},
         "applied_values": {"THK_1": 3.2386947295420723, "RIB_N": 6}, "out_of_range": []},
    ]


@pytest.mark.parametrize("n", [2, 7, 50])
def test_lhs_one_per_stratum_and_reproducible(n):
    src = {"kind": "lhs", "count": n, "seed": 42}
    a, b = _m(src), _m(dict(src))
    assert [r.values for r in a.rows] == [r.values for r in b.rows]
    assert [r.values for r in _m({**src, "seed": 43}).rows] != [r.values for r in a.rows]
    for p in P:
        lo, hi = p["min"], p["max"]
        strata = sorted(int((r.values[p["name"]] - lo) / (hi - lo) * n) for r in a.rows)
        assert strata == list(range(n))  # 층마다 정확히 1개, 범위 안
        assert all(lo <= r.values[p["name"]] < hi for r in a.rows)
    assert all(r.out_of_range == [] for r in a.rows)
    assert all(isinstance(r.applied_values["RIB_N"], int) for r in a.rows)


def test_lhs_default_seed_is_1_and_rounding_mode():
    assert [r.values for r in _m({"kind": "lhs", "count": 3}).rows] == [r.values for r in _m({"kind": "lhs", "count": 3, "seed": 1}).rows]
    m = _m({"kind": "lhs", "count": 4, "seed": 1, "ranges": {"RIB_N": [3.0, 9.0]}}, integer_rounding="truncate")
    assert [r.applied_values["RIB_N"] for r in m.rows] == [6, 8, 3, 5]


def test_lhs_problems():
    assert _codes(_m({"kind": "lhs", "count": 1})) == ["TOO_FEW_ROWS"]
    assert _codes(_m({"kind": "lhs", "count": 6}, max_runs=5)) == ["TOO_MANY_ROWS"]
    for bad in ([5, 5], [6, 2], ["a", 3], [1], [float("inf"), 3], [float("nan"), 3]):
        m = _m({"kind": "lhs", "count": 4, "ranges": {"THK_1": bad}})
        assert _codes(m) == ["RANGE_INVALID"] and m.rows == [] and not m.ok
    assert _codes(_m({"kind": "lhs", "count": 4, "ranges": {"NOPE": [0, 1]}})) == ["RANGE_INVALID"]
    for bad in ({"kind": "lhs", "count": "4"}, {"kind": "lhs", "count": True}, {"kind": "lhs", "count": 4, "seed": 1.5},
                {"kind": "lhs", "count": 4, "ranges": [1, 2]}, {"kind": "grid"}, "lhs"):
        with pytest.raises(bm.BatchShapeError):
            _m(bad)


def test_lhs_fixed_parameter_when_set_min_equals_max():
    m = bm.build_matrix({"kind": "lhs", "count": 3}, parameters=[{"name": "A", "min": 1.5, "max": 1.5}], tpl_params=[],
                        max_runs=10, table_max_bytes=10)
    assert m.ok and [r.values["A"] for r in m.rows] == [1.5, 1.5, 1.5]


# ---- 표 ------------------------------------------------------------------------------------------


def test_table_tab_comma_bom_order_doe_column():
    tab = _m({"kind": "table", "text": "THK_1\tRIB_N\n3.0\t5.4\n2.5\t6\n"})
    comma = _m({"kind": "table", "text": "﻿doe,RIB_N,THK_1\r\n7,5.4,3.0\r\n\r\n8,6,2.5"})
    assert tab.ok and comma.ok and tab.source_kind == "TABLE" and tab.source_meta == {"row_count": 2}
    assert [r.as_dict() for r in tab.rows] == [r.as_dict() for r in comma.rows] == [
        {"doe_no": 1, "run_key": "run__00001", "values": {"THK_1": 3.0, "RIB_N": 5.4},
         "applied_values": {"THK_1": 3.0, "RIB_N": 5}, "out_of_range": []},
        {"doe_no": 2, "run_key": "run__00002", "values": {"THK_1": 2.5, "RIB_N": 6.0},
         "applied_values": {"THK_1": 2.5, "RIB_N": 6}, "out_of_range": []},
    ]
    oor = _m({"kind": "table", "text": "THK_1,RIB_N\n9,5\n"})
    assert oor.ok and oor.rows[0].out_of_range == ["THK_1"]


def test_table_problems():
    assert _codes(_m({"kind": "table", "text": "THK_1\n3\n"})) == ["TABLE_HEADER"]  # 열 누락
    assert _codes(_m({"kind": "table", "text": "THK_1,RIB_N,X\n3,5,1\n"})) == ["TABLE_HEADER"]
    assert _codes(_m({"kind": "table", "text": "THK_1,RIB_N,THK_1\n3,5,3\n"})) == ["TABLE_HEADER"]
    assert _codes(_m({"kind": "table", "text": ""})) == ["TABLE_HEADER"]
    assert _codes(_m({"kind": "table", "text": "THK_1,RIB_N\n"})) == ["TOO_FEW_ROWS"]
    assert _codes(_m({"kind": "table", "text": "THK_1,RIB_N\n1,5\n2,5\n3,5\n"}, max_runs=2)) == ["TOO_MANY_ROWS"]
    assert _codes(_m({"kind": "table", "text": "THK_1,RIB_N\n" + "3,5\n" * 300})) == ["TEXT_TOO_LARGE"]
    m = _m({"kind": "table", "text": "THK_1,RIB_N\n3,5\nabc,5\n3\n4,inf\n2,6\n"})
    assert [(p["code"], p.get("row")) for p in m.problems] == [("TABLE_VALUE", 2), ("TABLE_VALUE", 3), ("TABLE_VALUE", 4)]
    assert [r.doe_no for r in m.rows] == [1, 5] and not m.ok  # 미리보기는 남은 행, 생성은 422
    with pytest.raises(bm.BatchShapeError):
        _m({"kind": "table", "text": None})


def test_table_problem_count_is_capped():
    m = _m({"kind": "table", "text": "THK_1,RIB_N\n" + "x,1\n" * 150}, table_max_bytes=10_000)
    assert len(m.problems) == bm.MAX_PROBLEMS


# ---- ① 학습 DOE ----------------------------------------------------------------------------------


def test_train_doe_rows_use_run_numbers(tmp_path):
    from physicsai_core.stage1_train_data import doe_samples

    p = tmp_path / "samples.csv"
    doe_samples.write_samples_csv(str(p), ["RIB_N", "THK_1"], [
        {"run_key": "run__00014", "values": {"RIB_N": 5, "THK_1": 3.1}},
        {"run_key": "run__00002", "values": {"RIB_N": 7.6, "THK_1": 2.2}},
    ])
    header, rows = doe_samples.read_samples_csv(str(p))  # PARTIAL DOE도 있는 행만
    m = _m({"kind": "train_doe", "doe_id": "doe-1"}, samples_header=header, samples=rows)
    assert m.ok and m.source_kind == "TRAIN_DOE" and m.source_meta == {"doe_id": "doe-1"}
    assert [(r.doe_no, r.run_key, r.values, r.applied_values["RIB_N"]) for r in m.rows] == [
        (2, "run__00002", {"THK_1": 2.2, "RIB_N": 7.6}, 8), (14, "run__00014", {"THK_1": 3.1, "RIB_N": 5.0}, 5)]
    resp_hdr = [*header, "resp:MaxStress"]  # resp: 열은 무시
    assert _m({"kind": "train_doe", "doe_id": "d"}, samples_header=resp_hdr, samples=rows).ok


def test_train_doe_problems():
    hdr = ["run_key", "THK_1", "RIB_N"]
    assert _codes(_m({"kind": "train_doe", "doe_id": "d"}, samples_header=["run_key", "THK_1", "X"], samples=[])) == ["DOE_PARAM_MISMATCH"]
    assert _codes(_m({"kind": "train_doe", "doe_id": "d"}, samples_header=hdr, samples=[])) == ["TOO_FEW_ROWS"]
    rows = [{"run_key": "run__00001", "values": {"THK_1": 3, "RIB_N": 5}}, {"run_key": "case_2", "values": {"THK_1": 3, "RIB_N": 5}},
            {"run_key": "run__00001", "values": {"THK_1": 3, "RIB_N": 5}}, {"run_key": "run__00003", "values": {"THK_1": 3}}]
    m = _m({"kind": "train_doe", "doe_id": "d"}, samples_header=hdr, samples=rows)
    assert _codes(m) == ["TABLE_VALUE"] * 3 and [r.doe_no for r in m.rows] == [1]
    many = [{"run_key": f"run__{i:05d}", "values": {"THK_1": 3, "RIB_N": 5}} for i in range(1, 4)]
    assert _codes(_m({"kind": "train_doe", "doe_id": "d"}, samples_header=hdr, samples=many, max_runs=2)) == ["TOO_MANY_ROWS"]
    for bad in ({"kind": "train_doe"}, {"kind": "train_doe", "doe_id": ""}):
        with pytest.raises(bm.BatchShapeError):
            _m(bad, samples_header=hdr, samples=[])
    with pytest.raises(bm.BatchShapeError):
        _m({"kind": "train_doe", "doe_id": "d"})  # samples 미전달


# ---- 공용 도우미 ------------------------------------------------------------------------------------


def test_helpers_and_settings_entry():
    from physicsai_core.config import Settings

    assert bm.run_key_for(7) == "run__00007" and bm.doe_no_of("run__00014") == 14
    assert bm.doe_no_of("run__0") is None and bm.doe_no_of("run_1") is None
    # D3-53: fullmatch + ASCII 숫자 — 끝 줄바꿈·유니코드 숫자(아랍·전각) 거부
    for bad in ("run__1\n", "run__00001\n", "run__\u0661", "run__\uff11", " run__1", "run__1 ", None, 5):
        assert bm.doe_no_of(bad) is None, bad  # type: ignore[arg-type]
    assert bm.batch_label(3) == "B-003" and bm.batch_dir_rel("04_batch", 12) == "04_batch/B-012"
    assert bm.input_rel_for("run__00002", "assembly", "EPS_mesh_0000.rad") == "run__00002/m_3"
    assert bm.input_rel_for("run__00002", "mesh_only", "EPS_mesh_0000.rad") == "run__00002/m_1/EPS_mesh_0000.rad"
    s = Settings()
    assert (s.predict_batch.max_runs, s.predict_batch.table_max_bytes, s.predict_batch.dir_name, s.predict_batch.curve_max_runs) == (
        200, 1048576, "04_batch", 200)
    m = bm.build_matrix_for({"kind": "lhs", "count": 3}, {"parameters": P, "tpl_params": T}, s)
    assert [r.as_dict() for r in m.rows] == [r.as_dict() for r in _m({"kind": "lhs", "count": 3}).rows]
    assert _codes(bm.build_matrix_for({"kind": "lhs", "count": 201}, {"parameters": P, "tpl_params": T}, s)) == ["TOO_MANY_ROWS"]
    assert bm.samples_csv_text(["THK_1", "RIB_N"], m.rows[:1]).splitlines() == [
        "doe_no,run_key,THK_1,RIB_N", f"1,run__00001,{m.rows[0].applied_values['THK_1']!r},{float(m.rows[0].applied_values['RIB_N'])!r}"]
