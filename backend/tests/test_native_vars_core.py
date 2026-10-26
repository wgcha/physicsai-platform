"""native-vars.md(V-NV-2·V-NV-4·V-NV-5·V-NV-6 순수부) — `physicsai_core.geometry.native_vars` 풀·유효 변수·스냅숏 적용·경고·학습 범위 합집합,
Native 공칭 밖 허용(Altair 검증 불변), 일괄 행 out_of_range 기준, `ps["parameters"]` 직접 읽기 정적 검사(R3)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from physicsai_core.geometry import native_vars as nv

REPO = Path(__file__).resolve().parents[2]


def _f(name, typ, body, nominal, lo, hi, group=None, feas=None, locked=False):
    f = {"name": name, "type": typ, "body": body, "nominal": nominal, "unit": "mm", "range": {"min": lo, "max": hi},
         "group": group, "ref": {"locked": locked}}
    if feas:
        f["feasible"] = feas
    return f


DOC = {"schema_version": 1, "features": [
    _f("A_THK_1", "THICKNESS", "A", 10.0, 9.5, 10.5, "G1", {"min": 6.0, "max": 14.0, "source": "envelope"}),
    _f("A_THK_2", "THICKNESS", "A", 10.0, 9.5, 10.5, "G1"),
    _f("B_RIB_H_1", "RIB_HEIGHT", "B", 20.0, 19.0, 21.0, None, {"min": 15.0, "max": 25.0, "source": "estimate"}, locked=True),
    _f("B_RIB_U_1", "RIB_POS_U", "B", 30.0, 25.0, 35.0),
], "groups": [{"id": "G1", "parameter": "A_THK_1", "members": ["A_THK_1", "A_THK_2"]}]}
SET_ROWS = [{"name": "A_THK_1", "nominal": 10.0, "min": 9.0, "max": 11.0, "unit": "mm"},
            {"name": "B_RIB_H_1", "nominal": 20.0, "min": 18.0, "max": 22.0, "unit": "mm"},
            {"name": "T_PROP", "nominal": 1.2, "min": 1.0, "max": 1.4, "unit": "mm", "source": "prop", "prop_id": 10}]


def test_pool_is_group_representative_plus_ungrouped():
    p = nv.pool(DOC)
    assert [e["name"] for e in p] == ["A_THK_1", "B_RIB_H_1", "B_RIB_U_1"]     # A_THK_2(그룹 구성원)는 풀 밖
    assert [e["position"] for e in p] == [False, False, True]                  # 위치형(RIB_POS) 표시
    assert p[0]["feasible"] == {"min": 6.0, "max": 14.0, "source": "envelope"} and p[2]["feasible"] is None
    assert p[0]["default_range"] == {"min": 9.5, "max": 10.5} and p[1]["ref_locked"] is True
    assert nv.pool(None) == [] and nv.pool({"features": [{"name": "X", "type": "T", "nominal": 1.0}]}) == []  # 범위 없는 피처는 뺀다


def test_effective_add_exclude_snapshot_and_problems():
    pool = nv.pool(DOC)
    doc, probs = nv.effective(SET_ROWS, pool, add=["B_RIB_U_1"], exclude=["B_RIB_H_1"],
                              train={"A_THK_1": {"min": 9.9, "max": 10.1}}, set_revision=3,
                              train_source={"model_id": "m", "dataset_id": "d", "doe_ids": ["x"]})
    assert probs == [] and doc["set_revision"] == 3 and doc["edited"] is True and doc["excluded"] == ["B_RIB_H_1"]
    names = [v["name"] for v in doc["variables"]]
    assert names == ["A_THK_1", "T_PROP", "B_RIB_U_1"]                          # 세트 순서(PROP 행 포함) 뒤에 풀 순서 추가
    by = {v["name"]: v for v in doc["variables"]}
    assert by["A_THK_1"]["origin"] == "set" and by["A_THK_1"]["train"] == {"min": 9.9, "max": 10.1}
    assert by["A_THK_1"]["feasible"] == {"min": 6.0, "max": 14.0, "source": "envelope"}
    assert by["B_RIB_U_1"] == {"name": "B_RIB_U_1", "nominal": 30.0, "min": 25.0, "max": 35.0, "unit": "mm", "origin": "added",
                               "train": None, "feasible": None}              # 추가 변수 = 피처 기본 범위
    assert by["T_PROP"]["source"] == "prop" and by["T_PROP"]["prop_id"] == 10  # PROP 키 보존
    assert doc["train_source"]["doe_ids"] == ["x"]
    # apply: parameters만 스냅숏 행으로(표시용 키 제거), 나머지 세트 필드 유지
    ps = {"id": "s1", "parameters": SET_ROWS, "label": "L"}
    p2 = nv.apply(ps, doc)
    assert p2["id"] == "s1" and p2["label"] == "L" and [r["name"] for r in p2["parameters"]] == names
    assert all(not ({"origin", "train", "feasible", "ref_locked"} & set(r)) for r in p2["parameters"])
    assert ps["parameters"] is SET_ROWS and nv.apply(ps, None)["parameters"] == SET_ROWS
    # 오류: 풀 밖 add·이미 있는 add·세트에 없는 exclude·중복·add∩exclude
    _d, probs = nv.effective(SET_ROWS, pool, add=["NOPE", "A_THK_1", "B_RIB_U_1", "B_RIB_U_1"], exclude=["ZZ", "ZZ"])
    msgs = [(p["field"], p["name"]) for p in probs]
    assert ("vars.add", "NOPE") in msgs and ("vars.add", "A_THK_1") in msgs and ("vars.add", "B_RIB_U_1") in msgs
    assert msgs.count(("vars.exclude", "ZZ")) == 2
    _d, probs = nv.effective(SET_ROWS, pool, add=["B_RIB_U_1"], exclude=["B_RIB_U_1"])
    assert any("함께" in p["message"] or "세트 정의에 없는" in p["message"] for p in probs)
    # 정의 미편집(add·exclude 없음) = 세트 행 그대로, edited false
    doc0, _ = nv.effective(SET_ROWS, pool)
    assert doc0["edited"] is False and [r["name"] for r in nv.apply(ps, doc0)["parameters"]] == [r["name"] for r in SET_ROWS]
    assert nv.vars_of({"vars": doc0}) == doc0 and nv.vars_of({"vars": {"variables": []}}) is None and nv.vars_of(None) is None


def test_warn_rows_codes_and_tolerances():
    pool = nv.pool(DOC)
    doc, _ = nv.effective(SET_ROWS[:2], pool, train={"A_THK_1": {"min": 9.0, "max": 11.0}, "B_RIB_H_1": None})
    assert nv.warn_rows(doc) == [{"code": "VAR_REF_LOCKED", "name": "B_RIB_H_1",
                                  "message": "'B_RIB_H_1' 양면 접촉 피처 — 형상 생성이 실패할 수 있습니다"}]
    w = nv.warn_rows(doc, {"A_THK_1": [5.0, 15.0], "B_RIB_H_1": [10.0, 30.0]})
    codes = [(x["code"], x["name"]) for x in w]
    assert codes == [("VAR_OUT_OF_TRAIN", "A_THK_1"), ("VAR_OUT_OF_FEASIBLE", "A_THK_1"),
                     ("VAR_OUT_OF_FEASIBLE", "B_RIB_H_1"), ("VAR_REF_LOCKED", "B_RIB_H_1")]   # B_RIB_H_1 학습 범위 모름 → 외삽 경고 없음
    assert "학습 형상 분포 밖 — 외삽 주의(학습 9~11)" in w[0]["message"] and "모핑 실패 가능(모핑 가능 6~14)" in w[1]["message"]
    # 허용오차: 학습 범위 1e-9·max(1,|x|) 안은 밖이 아님
    assert not [x for x in nv.warn_rows(doc, {"A_THK_1": [9.0 - 1e-10, 11.0 + 1e-10]}) if x["code"] == "VAR_OUT_OF_TRAIN"]
    assert [x for x in nv.warn_rows(doc, {"A_THK_1": [9.0 - 1e-6, 11.0]}) if x["code"] == "VAR_OUT_OF_TRAIN"]
    # 공칭이 범위 밖(D5): 경고만
    n = nv.warn_rows(doc, {"A_THK_1": [10.5, 10.8]})
    assert any(x["code"] == "VAR_NOMINAL_OUTSIDE" and x["name"] == "A_THK_1" for x in n)
    # 고정(하한 = 상한)도 같은 규칙, 제외 변수는 변수 목록에 없으므로 경고 없음
    assert not nv.warn_rows(nv.effective(SET_ROWS[:1], pool, exclude=["A_THK_1"])[0], {"A_THK_1": [99.0, 99.0]})
    # 추가 검증 점
    pts = nv.warn_points(doc, [{"A_THK_1": 12.0, "B_RIB_H_1": 20.0}, {"A_THK_1": 20.0, "B_RIB_H_1": 20.0}],
                         {"A_THK_1": [9.0, 11.0], "B_RIB_H_1": [18.0, 22.0]})
    assert [(x["code"], x["name"]) for x in pts] == [("VAR_OUT_OF_BOUNDS", "A_THK_1"), ("VAR_OUT_OF_TRAIN", "A_THK_1"),
                                                      ("VAR_OUT_OF_FEASIBLE", "A_THK_1")]            # 변수·코드마다 1건
    rows = nv.var_rows(doc, pool)
    assert rows[0]["base"] == {"min": 9.0, "max": 11.0} and rows[0]["position"] is False and rows[1]["train"] is None
    assert nv.out_of_range_parameters(doc) == [{"name": "A_THK_1", "min": 9.0, "max": 11.0}]      # 학습 범위를 아는 변수만


def _doe(snapshot, doc=DOC, did="d1"):
    return {"id": did, "snapshot": snapshot, "features": doc}


def test_train_ranges_union_nominal_fixed_and_unmatched():
    pool = nv.pool(DOC)
    ident = [{"name": e["name"], "type": e["type"], "body": e["body"], "nominal": e["nominal"]} for e in pool]
    ident.append({"name": "T_PROP", "nominal": 1.2, "prop": True})
    d1 = _doe([{"name": "A_THK_1", "nominal": 10.0, "min": 9.5, "max": 10.5}, {"name": "T_PROP", "nominal": 1.2, "min": 1.1, "max": 1.3},
               {"name": "A_THK_1__na", "min": 0, "max": 1}], did="d1")
    d2 = _doe([{"name": "A_THK_1", "nominal": 10.0, "min": 10.2, "max": 11.0}, {"name": "T_PROP", "nominal": 1.2, "min": 1.15, "max": 1.4}], did="d2")
    out, notes = nv.train_ranges(ident, [d1, d2])
    assert out["A_THK_1"] == {"min": 9.5, "max": 11.0}                           # DOE 합집합
    assert out["B_RIB_H_1"] == {"min": 20.0, "max": 20.0}                        # DOE에 없는 변수 = [공칭, 공칭](움직이면 외삽)
    assert out["B_RIB_U_1"] == {"min": 30.0, "max": 30.0}
    assert out["T_PROP"] == {"min": 1.1, "max": 1.4} and notes == []
    # 같은 이름이라도 추출 조건이 달라 다른 피처(type·body·공칭 불일치) → None + UNMATCHED
    other = json.loads(json.dumps(DOC))
    other["features"][2]["nominal"] = 21.0
    out, notes = nv.train_ranges(ident, [_doe([], other)])
    assert out["B_RIB_H_1"] is None and out["A_THK_1"] == {"min": 10.0, "max": 10.0}
    assert [n["code"] for n in notes] == ["TRAIN_RANGE_UNMATCHED"] and "B_RIB_H_1" in notes[0]["message"]
    other["features"][3]["type"] = "RIB_POS_V"
    out, notes = nv.train_ranges(ident, [_doe([], other)])
    assert out["B_RIB_U_1"] is None and "B_RIB_U_1" in notes[0]["message"]
    # 한 DOE에서 이름을 판단할 수 없으면 그 이름은 None, DOE가 없으면 전부 None
    gone = {"features": [f for f in DOC["features"] if f["name"] != "B_RIB_U_1"], "groups": DOC["groups"], "schema_version": 1}
    assert nv.train_ranges(ident, [d1, _doe([], gone, "d3")])[0]["B_RIB_U_1"] is None
    assert set(nv.train_ranges(ident, [])[0].values()) == {None}


def _write_native_folder(tmp_path: Path, params: list[dict]) -> Path:
    """validate_native_folder 최소 입력: parameters.json + 피처 파일(검증 대상은 parameters 읽기·이름 집합)."""
    (tmp_path / "native" / "extract").mkdir(parents=True)
    (tmp_path / "parameters.json").write_text(json.dumps({"schema_version": 1, "parameters": params}), encoding="utf-8")
    return tmp_path


def test_v_nv_2_native_allows_nominal_outside_and_altair_unchanged(tmp_path):
    from physicsai_core.stage4_predict.param_set_files import ParamSetFolder, _load_parameters
    from physicsai_core.stage4_predict.param_set_native import validate_native_folder
    from physicsai_core.stage4_predict.param_sets import validate_folder  # noqa: F401 - Altair 경로 존재 확인

    rows = [{"name": "A_THK_1", "nominal": 12.5, "min": 14.0, "max": 18.0, "unit": "mm"},
            {"name": "B", "nominal": 1.0, "min": 0.5, "max": 2.0}]
    d = _write_native_folder(tmp_path, rows)
    f = ParamSetFolder()
    _load_parameters(f, str(d), require_nominal_inside=False)
    assert f.problems == [] and [p["name"] for p in f.parameters] == ["A_THK_1", "B"]
    assert [w["code"] for w in f.warnings] == ["VAR_NOMINAL_OUTSIDE"] and "A_THK_1" in f.warnings[0]["message"]
    f = ParamSetFolder()  # Altair 검증(기본값 True)은 그대로 거부
    _load_parameters(f, str(d))
    assert [p["code"] for p in f.problems] == ["PARAMETER_RANGE_INVALID"] and "min ≤ nominal ≤ max" in f.problems[0]["message"]
    # Native도 min ≤ max는 지킨다
    d2 = _write_native_folder(tmp_path / "x", [{"name": "A", "nominal": 1.0, "min": 3.0, "max": 2.0}])
    f = ParamSetFolder()
    _load_parameters(f, str(d2), require_nominal_inside=False)
    assert [p["code"] for p in f.problems] == ["PARAMETER_RANGE_INVALID"] and "min ≤ max" in f.problems[0]["message"]
    # validate_native_folder는 Native 전용 완화를 쓴다(공칭 범위 밖 PARAMETER_RANGE_INVALID 없음)
    nf = validate_native_folder(str(d), max_total_bytes=10**9, starter_glob="*.rad", renum_csv_name="r.csv", baseline_inc_name="b.inc",
                                step_extensions=[".step"])
    assert "PARAMETER_RANGE_INVALID" not in [p["code"] for p in nf.problems]


def test_batch_matrix_out_of_range_basis_is_pluggable():
    from physicsai_core.sampling.matrix import build_matrix

    params = [{"name": "A", "nominal": 10.0, "min": 8.0, "max": 12.0}, {"name": "B", "nominal": 1.0, "min": 1.0, "max": 1.0}]
    src = {"kind": "table", "text": "A,B\n9,1\n11.5,1\n"}
    kw = {"parameters": params, "tpl_params": [], "max_runs": 100, "table_max_bytes": 10000}
    assert [r.out_of_range for r in build_matrix(src, **kw).rows] == [[], []]                     # 기본 = 세트 범위(Altair)
    train = [{"name": "A", "min": 9.5, "max": 10.5}]                                              # Native 일괄 = 학습 범위
    assert [r.out_of_range for r in build_matrix(src, oor_parameters=train, **kw).rows] == [["A"], ["A"]]
    assert [r.out_of_range for r in build_matrix(src, oor_parameters=[], **kw).rows] == [[], []]  # 학습 범위 모름 = 빈 목록


# ---- R3: `ps["parameters"]` 직접 읽기 정적 검사 ------------------------------------------------------------------

# 세트 정의(`param_sets.parameters`)를 직접 읽는 곳 전수(native-vars.md §4.2·§9·R3). 새로 읽는 곳이 생기면 이 표를 먼저 갱신하며
# "Native 실행(④ 일괄·⑥·①-3)이면 스냅숏 우선(`native_vars.apply`/`vars_of`), 세트 상세·단건·등록·props 등 세트 자체 편집이면 세트 정의"인지 판단한다.
# 값 = (줄 수 상한 없이) 그 파일의 `["parameters"]`·`.get("parameters")` 개수.
ALLOWED = {
    # --- Native 실행 경로, 스냅숏 적용 뒤(ps' = `native_vars.apply` 결과)의 값을 읽는 곳 ---
    "backend/physicsai_api/services/surrogate_opt_space.py": 2,           # _bounds(ps')·_multi_settings(다중 baseline은 vars 없음)
    "backend/physicsai_api/services/surrogate_opts.py": 4,               # _explore_batch(n["ps"] = ps') + _explore_batch_method(같은 n["ps"], DM-C5)
    "backend/physicsai_core/sampling/matrix.py": 1,                      # build_matrix_for(호출부가 ps'를 넘김)
    "backend/physicsai_api/services/predict_batches.py": 1,              # _recommended(ps' = res.ps)
    "backend/physicsai_api/services/surrogate_opts_view.py": 1,          # nv.apply(ps, settings.vars)["parameters"]
    "backend/physicsai_api/services/predict_batches_info.py": 1,         # nv.apply(ps, source_meta.vars)["parameters"]
    "backend/physicsai_api/services/predict_batches_curves.py": 2,       # 상세(_detail) 응답의 parameters(스냅숏 이름)
    "backend/physicsai_api/services/design_map.py": 1,                   # nv.apply 뒤
    "worker/physicsai_worker/steps/stage1_train_data/doe_native_set.py": 2,   # ps = apply 결과(_set)
    "worker/physicsai_worker/steps/stage4_predict/batch_native.py": 5,   # ps = apply 결과(bp_prep·gen_one)
    "worker/physicsai_worker/steps/stage4_predict/batch.py": 1,          # Altair 일괄(스냅숏 없음, _param_set이 apply)
    "worker/physicsai_worker/steps/stage5_optimize/surrogate.py": 1,     # ps = apply 결과
    "worker/physicsai_worker/steps/stage5_optimize/surrogate_final.py": 2,    # ps = apply 결과
    "backend/physicsai_api/services/doe_preview_api.py": 3,              # ①-1 train_setup(학습 설정) + 세트 이름 확인(세트 정의, 실제 DOE와 같음) + res.ps(스냅숏 적용 결과)
    "backend/physicsai_core/geometry/doe_preview_src.py": 2,             # ①-1 train_setup(학습 설정) + from_param_set(호출부가 ps'를 넘김)
    # --- 세트 정의가 입력인 곳(스냅숏을 만드는 쪽·세트 상세·편집) ---
    "backend/physicsai_api/services/native_vars_run.py": 2,              # 세트 정의 → 스냅숏 입력
    "backend/physicsai_api/services/native_vars_api.py": 6,              # 세트 정의 조회·편집
    "backend/physicsai_api/services/surrogate_opt_pareto.py": 1,         # 스냅숏 없는 이전 최적화의 추가 검증 경고 입력
    "backend/physicsai_api/services/param_set_native_api.py": 2,         # enrich: vars_count(Native·Altair 세트 정의 행 수 — v0.2.8 Altair 최상위 키)
    "backend/physicsai_api/services/template_vars.py": 1,                # Altair 풀: 세트 정의의 단위로 보충(v0.2.8 altair-vars.md §5.1)
    "backend/physicsai_api/services/job_params/stage1_native.py": 4,     # ①-1 train_setup 2곳 + 세트 DOE 이름 확인(세트 정의) + 세트 DOE 표본 입력 = native_vars_run 해석 결과 res.ps(DM-C2)
    # --- 세트 자체(등록·단건·FEM 검증·3D 보기·props·baseline·①·폴더 파일)와 Altair·다중 baseline: 세트 정의가 정답 ---
    "backend/physicsai_api/services/common.py": 1,                       # param_set_out
    "backend/physicsai_api/services/geom_view_api.py": 3,
    "backend/physicsai_api/services/stage1_train_data.py": 9,            # ① 학습 설정(train_setups.parameters, 세트 아님)
    "backend/physicsai_api/services/asm_match_api.py": 1,                # ① 학습 설정(train_setups.parameters, 세트 아님): use=true 파라미터 바디 판정(asm-match.md §3.2)
    "backend/physicsai_api/services/stage4_predict.py": 3,               # 단건 PREDICT 확인(세트 정의, 비범위 §6.4)
    "backend/physicsai_api/services/fem_verify_sources.py": 2,
    "backend/physicsai_api/services/fem_verify_plan.py": 1,
    "backend/physicsai_api/services/param_set_baselines_api.py": 5,
    "backend/physicsai_api/services/param_set_props_api.py": 4,
    "backend/physicsai_api/services/job_params/stage1_train_data.py": 2,   # tpl stale 판정(train_setups.parameters, 세트 아님)
    "backend/physicsai_api/services/job_params/stage4_predict.py": 1,    # 단건 PREDICT(세트 정의)
    "backend/physicsai_core/stage1_train_data/doe_platform.py": 1,
    "backend/physicsai_core/geometry/baselines.py": 1,
    "backend/physicsai_core/stage4_predict/param_set_files.py": 2,       # 폴더 파일 읽기
    "backend/physicsai_core/stage4_predict/input_kind.py": 1,            # 입력 종류 능력: 세트 정의의 쉘 두께(source prop) 행 유무(input-kind.md IK-3)
    "backend/physicsai_core/stage4_predict/batch_multi.py": 2,           # 다중 baseline(vars 없음, NV-9)
    "backend/physicsai_core/equiv/sides.py": 1,
    "worker/physicsai_worker/steps/stage1_train_data/doe_platform_gen.py": 1,
    "worker/physicsai_worker/steps/stage1_train_data/doe_native.py": 1,
    "worker/physicsai_worker/steps/stage1_train_data/doe_gen.py": 3,     # 레거시 hstbatch DOE의 ①-1 표(train_setups.parameters, 세트 아님)
    "worker/physicsai_worker/steps/stage4_predict/np_register.py": 5,    # 등록·reprep·props 스캔(세트 정의)
    "worker/physicsai_worker/steps/stage4_predict/predict_native.py": 4,  # 단건 PREDICT(세트 정의)
    "worker/physicsai_worker/steps/stage4_predict/predict.py": 2,
    "worker/physicsai_worker/steps/stage5_optimize/optimize.py": 2,       # 원본 HyperStudy 최적화(변수 정의·스냅숏 없음): 세트 정의 변수만 선언한 tpl 사용 뷰(altair-vars.md §5.3)
    # --- MCP(mcp.md): 읽기 전용 요약·스펙 생성기 ---
    "backend/physicsai_api/mcp/summaries.py": 1,                         # param_set 요약 = 세트 정의 표(실행 경로 아님, vars_revision은 facts에 함께)
    "backend/physicsai_api/mcp/toolspec.py": 1,                          # openapi operation의 `parameters`(경로·쿼리 인자) — 세트 정의와 무관
    # --- 보고서(upload-report.md §9): 결과 표·최적화 입력 dict의 `parameters`(변수 목록) 읽기 — 세트 정의 실행 경로 아님 ---
    "backend/physicsai_api/services/reports_analysis.py": 4,
    "backend/physicsai_core/report_html/analysis.py": 7,
    "backend/physicsai_core/report_html/opt.py": 4,
}
PATTERN = re.compile(r"\[\"parameters\"\]|\.get\(\"parameters\"\)")


def _scan() -> dict[str, int]:
    out: dict[str, int] = {}
    for top in ("backend/physicsai_api", "backend/physicsai_core", "worker/physicsai_worker"):
        for p in sorted((REPO / top).rglob("*.py")):
            n = len(PATTERN.findall(p.read_text(encoding="utf-8")))
            if n:
                out[p.relative_to(REPO).as_posix()] = n
    return out


def test_r3_direct_parameters_reads_are_reviewed():
    """`ps["parameters"]`(세트 정의)를 직접 읽는 곳의 목록이 바뀌면 실패 — Native 실행 경로가 스냅숏을 건너뛰지 않았는지 검토하고 ALLOWED를 갱신한다."""
    found = _scan()
    assert found == ALLOWED, ({k: (found.get(k), ALLOWED.get(k)) for k in sorted(set(found) | set(ALLOWED)) if found.get(k) != ALLOWED.get(k)})


def test_r3_native_run_paths_use_snapshot_first():
    """Native 실행 경로(워커·API 조회)가 `native_vars.apply`/`vars_of`로 스냅숏을 먼저 쓴다."""
    must = {
        "worker/physicsai_worker/steps/stage4_predict/batch.py": "nv.apply(ps, nv.vars_of(b.get(\"source_meta\")))",
        "worker/physicsai_worker/steps/stage4_predict/batch_native.py": "nv.apply(ps, nv.vars_of(b.get(\"source_meta\")))",
        "worker/physicsai_worker/steps/stage5_optimize/surrogate.py": "nv.apply(ps, nv.vars_of(opt[\"settings\"]))",
        "worker/physicsai_worker/steps/stage5_optimize/surrogate_final.py": "nv.apply(ps, nv.vars_of(opt[\"settings\"]))",
        "worker/physicsai_worker/steps/stage1_train_data/doe_native_set.py": "nv.apply(ps, nv.vars_of(ctx.params))",
        "worker/physicsai_worker/steps/doe_preview.py": "nv.apply(ps, nv.vars_of(p))",
        "backend/physicsai_api/services/surrogate_opts_view.py": "nv.apply(ps, nv.vars_of(o[\"settings\"]))",
        "backend/physicsai_api/services/predict_batches_info.py": "nv.apply(ps, nv.vars_of(b.get(\"source_meta\")))",
        "backend/physicsai_api/services/design_map.py": "nv.apply(ps, nv.vars_of(b.get(\"source_meta\")))",
    }
    for rel, needle in must.items():
        assert needle in (REPO / rel).read_text(encoding="utf-8"), rel


@pytest.mark.parametrize("rel", ["backend/physicsai_core/geometry/native_vars.py"])
def test_native_vars_core_is_stdlib_only(rel):
    import ast

    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    mods = {n.module.split(".")[0] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else
            a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in (n.names if isinstance(n, ast.Import) else [n]) if not (isinstance(n, ast.ImportFrom) and n.level > 0)}
    assert mods <= {"__future__", "math", "collections", "typing"}, mods
