"""doe-preview.md 코어(V-DP-3 일부·V-DP-7·V-DP-8·V-DP-13): 순수 함수(정렬·페이지·셀 키·행렬 키·판정·색 범위), 설정·명령 템플릿·작업 유형·기능 플래그·
MCP 제외·openapi 정적 검사. (API·워커 흐름은 worker/tests/stage1_train_data/test_doe_preview_train.py·stage4_predict/test_doe_preview_set.py)"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from physicsai_core.config.schema import Settings
from physicsai_core.geometry import doe_preview as dp
from physicsai_test_support import REPO

PARAMS = [{"name": "A", "nominal": 10.0, "min": 9.0, "max": 11.0, "unit": "mm"},
          {"name": "B", "nominal": 20.0, "min": 18.0, "max": 24.0, "unit": "mm"},
          {"name": "ANG", "nominal": 30.0, "min": 20.0, "max": 40.0, "unit": "deg"}]
ROWS = [(1, "run__00001", {"A": 10.0, "B": 20.0, "ANG": 30.0}),  # 공칭과 같음(변화 0)
        (2, "run__00002", {"A": 11.0, "B": 20.0, "ANG": 30.0}),  # A +0.5
        (3, "run__00003", {"A": 10.0, "B": 24.0, "ANG": 30.0}),  # B +0.667
        (4, "run__00004", {"A": 9.0, "B": 20.0, "ANG": 30.0}),   # A -0.5 (2와 같은 점수)
        (5, "run__00005", {"A": 10.0, "B": 20.0, "ANG": 40.0})]  # ANG +0.5


def test_param_table_units_and_filter():
    rows = [{"name": "A", "nominal": 1, "min": 0, "max": 2, "unit": ""}, {"name": "B", "nominal": "x", "min": 0, "max": 2},
            {"name": "C", "nominal": 1.0, "min": 0.5, "max": 1.5, "unit": "deg"}, {"name": "D", "nominal": 1.0, "min": 0.0, "max": 1.0}]
    t = dp.param_table(rows)
    assert [p["name"] for p in t] == ["A", "C", "D"] and t[0]["unit"] == "mm" and t[1]["unit"] == "deg"  # 숫자 아닌 행 제외, 빈 단위 = mm
    t2 = dp.param_table(rows, {"A": "deg", "D": "mm"})
    assert [p["unit"] for p in t2] == ["deg", "deg", "mm"]  # features 단위 우선


def test_disp_ref_mm_length_units_only_and_zero_fallback():
    # max over 길이 파라미터 of max(|max−nom|, |nom−min|): A=1, B=4 → 4, 각도(ANG 10)는 제외
    assert dp.disp_ref_mm(PARAMS) == 4.0
    assert dp.disp_ref_mm([p for p in PARAMS if p["unit"] != "mm"]) == 1.0  # 길이 단위가 없으면 1.0
    assert dp.disp_ref_mm([{"name": "Z", "nominal": 5.0, "min": 5.0, "max": 5.0, "unit": "mm"}]) == 1.0  # 범위 폭 0
    assert dp.disp_ref_mm([{"name": "Z", "nominal": 5.0, "min": 3.0, "max": 5.5, "unit": "mm"}]) == 2.0  # 비대칭은 큰 쪽


def test_order_change_doe_var_ties_and_paging():
    assert dp.change_score({"A": 10.0, "B": 20.0}, PARAMS) == 0.0
    order = dp.order_rows(ROWS, PARAMS, "change")
    assert order == [3, 2, 4, 5, 1]  # 점수 0.667 > 0.5(같으면 doe_no 오름차순: 2·4·5) > 0
    assert dp.order_rows(ROWS, PARAMS, "doe") == [1, 2, 3, 4, 5]
    assert dp.order_rows(ROWS, PARAMS, "var", "A") == [4, 1, 3, 5, 2]  # A 오름: 9, 10(1·3·5 doe_no 순), 11
    assert dp.order_rows(ROWS, PARAMS, "var", "A", desc=True) == [2, 1, 3, 5, 4]
    with pytest.raises(ValueError):
        dp.order_rows(ROWS, PARAMS, "nope")
    # 페이지: offset 0 = 공칭 + limit−1, 이후 = limit개(공칭 1개를 뺀 위치부터) — 페이지끼리 겹침·빠짐 없음
    big = list(range(1, 60))
    seen: list[int] = []
    for off in (0, 24, 48, 72):
        nominal, picked = dp.page_slice(big, off, 24)
        assert nominal is (off == 0)
        assert len(picked) == (23 if off == 0 else min(24, max(0, len(big) - (off - 1))))
        seen += picked
    assert seen == big
    assert dp.page_slice([], 0, 24) == (True, [])


def test_top_changes_and_full_values():
    vals = {"A": 10.5, "B": 20.0, "ANG": 36.0}
    t = dp.top_changes(vals, PARAMS)
    assert [x["name"] for x in t] == ["ANG", "A"] and t[0]["rel"] == pytest.approx(0.3) and t[1]["rel"] == pytest.approx(0.25)  # B는 변화 0이라 제외
    assert len(dp.top_changes({"A": 11.0, "B": 24.0, "ANG": 40.0}, PARAMS, 2)) == 2
    assert dp.top_changes({}, PARAMS) == []
    assert dp.full_values({"A": 10.5}, PARAMS) == {"A": 10.5, "B": 20.0, "ANG": 30.0}  # 빠진 값은 공칭


def _files(tmp: Path, name: str, content: bytes) -> str:
    p = tmp / name
    p.write_bytes(content)
    return str(p)


def test_v_dp_8_cell_key_elements(tmp_path):
    """셀 키: 값·tag·options·썸네일 옵션·버전·테셀레이션·Study가 다르면 다른 키, 출처·정렬·페이지는 키에 없다."""
    cad = _files(tmp_path, "a.step", b"CAD")
    feat = _files(tmp_path, "f.json", b"{}")
    tag = tmp_path / "tag"
    tag.mkdir()
    (tag / "tag_nodes.npz").write_bytes(b"T1")
    base = dict(cad_files=[cad], body_map=None, features=feat, tag_dir=str(tag), opts_sha=dp.sha_of({"o": 1}), fixed_digest=None)
    sd = dp.shape_digest(**base)
    assert sd == dp.shape_digest(**base)
    kw = dict(kind="solid", study_id="s1", shape=sd, values={"A": 10.0, "B": 20.0}, view_tess={"linear_mm": 0.1, "angular_deg": 20.0},
              thumb=dp.sha_of({"w": 320}), engine_version="0.14.0")
    k0 = dp.cell_key(**kw)
    assert re.fullmatch(r"[0-9a-f]{64}", k0) and dp.cell_key(**kw) == k0
    assert dp.cell_key(**{**kw, "values": {"B": 20.0, "A": 10.0}}) == k0  # 정규 JSON(키 정렬)
    for change in ({"values": {"A": 10.1, "B": 20.0}}, {"study_id": "s2"}, {"engine_version": "0.14.1"}, {"thumb": dp.sha_of({"w": 321})},
                   {"view_tess": {"linear_mm": 0.2, "angular_deg": 20.0}}, {"kind": "shell"},
                   {"shape": dp.shape_digest(**{**base, "opts_sha": dp.sha_of({"o": 2})})}):
        assert dp.cell_key(**{**kw, **change}) != k0, change
    # 형상 입력 digest: CAD·features·tag 내용·body_map·fixed가 바뀌면 달라진다(tag 없음은 null)
    (tag / "tag_nodes.npz").write_bytes(b"T2")
    assert dp.shape_digest(**base) != sd
    assert dp.shape_digest(**{**base, "tag_dir": None}) not in (sd, dp.shape_digest(**base))
    assert dp.shape_digest(**{**base, "tag_dir": str(tmp_path / "no_such")}) == dp.shape_digest(**{**base, "tag_dir": None})
    before = dp.shape_digest(**base)
    (tmp_path / "a.step").write_bytes(b"CAD2")  # CAD 내용이 바뀌면(크기가 같아도 sha256) 달라진다
    assert dp.shape_digest(**base) != before
    (tmp_path / "f.json").write_bytes(b'{"features": []}')
    assert dp.shape_digest(**base) != before
    assert dp.shape_digest(**{**base, "fixed_digest": "x"}) != dp.shape_digest(**base)
    # 소수 표기: float repr — 10 과 10.0 은 같다
    assert dp.cell_key(**{**kw, "values": {"A": 10, "B": 20}}) == k0


def test_v_dp_8_grid_and_matrix_keys():
    params = [{"name": "A", "nominal": 1.0, "min": 0.0, "max": 2.0}]
    m = dp.matrix_key(source_digest="d", sampling={"kind": "halton", "count": 8, "seed": 1}, num_runs=None, seed=None, params=params)
    assert m == dp.matrix_key(source_digest="d", sampling={"kind": "halton", "count": 8, "seed": 1}, num_runs=None, seed=None, params=params)
    for kw in ({"source_digest": "e"}, {"sampling": {"kind": "halton", "count": 8, "seed": 2}}, {"sampling": None, "num_runs": 8, "seed": 1},
               {"params": [{**params[0], "max": 3.0}]}):
        assert dp.matrix_key(**{**dict(source_digest="d", sampling={"kind": "halton", "count": 8, "seed": 1}, num_runs=None, seed=None,
                                       params=params), **kw}) != m, kw
    sel = {"order": "change", "var": None, "desc": False, "offset": 0, "limit": 24}
    g = dp.grid_key(source_digest="d", mkey=m, select=sel, thumb="t", engine_version="v")
    assert g == dp.grid_key(source_digest="d", mkey=m, select={**sel, "extra": 1}, thumb="t", engine_version="v")  # 선택 5키만
    for kw in ({"select": {**sel, "offset": 24}}, {"select": {**sel, "order": "doe"}}, {"mkey": "z"}, {"thumb": "u"}, {"engine_version": "w"},
               {"doe_id": "x"}):
        assert dp.grid_key(**{**dict(source_digest="d", mkey=m, select=sel, thumb="t", engine_version="v"), **kw}) != g, kw


def test_judge_cell_rules():
    ok = dp.judge_cell({"id": "a", "status": "OK", "code": None, "category": None, "max_disp_mm": 0.42})
    assert ok == {"cacheable": True, "status": "OK", "code": None, "category": None, "max_disp_mm": 0.42}
    fail = dp.judge_cell({"status": "FAIL", "code": "GEOM_FEATURE_COLLISION", "category": "CAD_FAILED"})
    assert fail["cacheable"] and fail["status"] == "FAIL" and fail["code"] == "GEOM_FEATURE_COLLISION" and fail["max_disp_mm"] is None
    for e in ({"status": "ERROR", "code": "GEOM_INTERNAL"}, {"status": "FAIL", "code": "VIEW_TOO_LARGE", "category": "VIEW"},
              {"status": "FAIL", "code": "X", "category": "INPUT"}, {"status": "FAIL", "code": "VIEW_TESSELLATION_FAILED"}):
        j = dp.judge_cell(e)
        assert j["status"] == "ERROR" and not j["cacheable"], e  # VIEW_*·INPUT·INTERNAL 범주는 인프라 문제 → 캐시 안 함
    for e in (None, {}, {"status": "WEIRD"}, "x"):
        j = dp.judge_cell(e)  # type: ignore[arg-type]
        assert j["status"] == "ERROR" and j["code"] == "OUTPUT_MISSING" and not j["cacheable"]
    assert dp.judge_cell({"status": "OK", "max_disp_mm": float("nan")})["max_disp_mm"] is None


def test_cells_document_chunks_and_paths():
    doc = dp.cells_document([("nominal", {}), ("ab12", {"A": 1, "B": 2.5})])
    assert doc == {"schema_version": 1, "cells": [{"id": "nominal", "values": {}}, {"id": "ab12", "values": {"A": 1.0, "B": 2.5}}]}
    assert dp.chunked(list(range(10)), 4) == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]] and dp.chunked([], 4) == [] and dp.chunked([1], 0) == [[1]]
    k = "ab" + "c" * 62
    assert dp.cell_dir_rel(k) == f"_cache/doe_preview/cells/ab/{k}" and dp.matrix_dir_rel(k) == f"_cache/doe_preview/matrix/ab/{k}"
    assert dp.job_dir_rel("j1") == "_cache/doe_preview/jobs/j1"
    assert dp.grid_command_key("shell") == "paicad_shell_view_grid" and dp.grid_command_key("solid") == "paicad_view_grid"


def test_thumb_options_document_from_settings():
    s = Settings()
    doc = dp.thumb_options_document(s.doe_preview, PARAMS)
    assert doc == {"schema_version": 1, "w": 320, "h": 240, "view_dir": [1.0, -1.0, 1.0], "margin": 1.15, "disp_range_mm": [0.0, 4.0],
                   "colormap": "turbo16", "nominal_ghost": True, "edges": False}
    s2 = Settings(doe_preview={"thumb": {"w": 400, "margin": 1.3, "nominal_ghost": False}})
    d2 = dp.thumb_options_document(s2.doe_preview, PARAMS)
    assert d2["w"] == 400 and d2["margin"] == 1.3 and d2["nominal_ghost"] is False
    assert dp.thumb_digest(doc) != dp.thumb_digest(d2) and dp.thumb_digest(doc) == dp.thumb_digest(dict(reversed(list(doc.items()))))


def test_config_defaults_example_and_validation():
    from physicsai_core.config.validate_geometry import _validate_doe_preview

    d = Settings().doe_preview
    assert (d.enabled, d.page_size, d.max_page_size, d.chunk_cells, d.parallel, d.timeout_s_per_cell, d.max_active_per_user) == \
        (True, 24, 48, 4, 2, 60, 2)
    assert (d.thumb.w, d.thumb.h, d.thumb.view_dir, d.thumb.margin, d.thumb.colormap, d.thumb.nominal_ghost) == \
        (320, 240, [1.0, -1.0, 1.0], 1.15, "turbo16", True)

    def issues(**kw):
        out: list = []
        _validate_doe_preview(Settings(doe_preview=kw), out)
        return sorted(i.key for i in out)

    assert issues() == []
    assert issues(page_size=5) == ["doe_preview.page_size"] and issues(page_size=49) == ["doe_preview.max_page_size", "doe_preview.page_size"]
    assert issues(chunk_cells=0) == ["doe_preview.chunk_cells"] and issues(chunk_cells=17) == ["doe_preview.chunk_cells"]
    assert issues(parallel=0) == ["doe_preview.parallel"] and issues(parallel=5) == ["doe_preview.parallel"]
    assert issues(timeout_s_per_cell=0) == ["doe_preview.timeout_s_per_cell"] and issues(max_active_per_user=0) == ["doe_preview.max_active_per_user"]
    assert issues(thumb={"w": 159}) == ["doe_preview.thumb.w"] and issues(thumb={"h": 801}) == ["doe_preview.thumb.w"]
    assert issues(thumb={"margin": 0.9}) == ["doe_preview.thumb.margin"] and issues(thumb={"margin": 2.1}) == ["doe_preview.thumb.margin"]
    assert issues(thumb={"view_dir": [0, 0, 0]}) == ["doe_preview.thumb.view_dir"] and issues(thumb={"view_dir": [1, 2]}) == ["doe_preview.thumb.view_dir"]
    assert issues(thumb={"colormap": "viridis"}) == ["doe_preview.thumb.colormap"]
    # 예시 설정이 그대로 읽힌다(절이 없으면 기본값, 있으면 같은 값)
    import yaml

    ex = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert ex["doe_preview"]["page_size"] == 24 and ex["doe_preview"]["thumb"]["colormap"] == "turbo16"
    s = Settings(doe_preview=ex["doe_preview"])
    assert s.doe_preview == d
    assert ex["commands"]["paicad_view_grid"][:4] == ["{paicad}", "view", "grid", "--cad"]
    assert ex["commands"]["paicad_shell_view_grid"][:5] == ["{paicad}", "shell", "view", "grid", "--cad"]


def test_grid_command_templates_render_optional_pairs_and_body_map():
    from physicsai_core.commands import render_argv, template_uses, validate_template

    s = Settings()
    exe = {"paicad_path": "/opt/paicad"}
    for k in ("paicad_view_grid", "paicad_shell_view_grid"):
        assert validate_template(k, getattr(s.commands, k)) == [], k
    assert validate_template("paicad_view_grid", ["{paicad}", "view", "grid", "--bogus", "{nope}"]) != []  # 모르는 placeholder 거부
    v = {"cad_input": "/s/m.step", "features_json": "/s/f.json", "cells_json": "/s/cells.json", "tag_dir": "", "options_json": "/s/o.json",
         "view_options_json": "/s/vo.json", "thumb_options_json": "/s/to.json", "threads": "1", "out_dir": "/s/out", "fixed_dir": ""}
    argv = render_argv("paicad_view_grid", s.commands.paicad_view_grid, v, executables=exe, is_windows=False)
    assert argv[:4] == ["/opt/paicad", "view", "grid", "--cad"] and "--tag-dir" not in argv  # train 출처는 tag 쌍째 생략
    assert argv[argv.index("--cells") + 1] == "/s/cells.json" and argv[argv.index("--thumb-options") + 1] == "/s/to.json"
    assert argv[argv.index("--threads") + 1] == "1" and argv[argv.index("--out-dir") + 1] == "/s/out"
    argv = render_argv("paicad_view_grid", s.commands.paicad_view_grid, {**v, "tag_dir": "/s/tag"}, executables=exe, is_windows=False)
    assert argv[argv.index("--tag-dir") + 1] == "/s/tag"
    sv = render_argv("paicad_shell_view_grid", s.commands.paicad_shell_view_grid, {**v, "fixed_dir": "/s/fx", "tag_dir": "/s/tag"}, executables=exe,
                     is_windows=False)
    assert sv[1:4] == ["shell", "view", "grid"] and sv[sv.index("--fixed-dir") + 1] == "/s/fx"
    assert "--fixed-dir" not in render_argv("paicad_shell_view_grid", s.commands.paicad_shell_view_grid, v, executables=exe, is_windows=False)
    assert template_uses(s.commands.paicad_view_grid, "cad_input") and template_uses(s.commands.paicad_view_grid, "cells_json")
    from physicsai_core.commands_spec import PAICAD_KEYS, PAICAD_VIEW_KEYS

    assert {"paicad_view_grid", "paicad_shell_view_grid"} <= set(PAICAD_VIEW_KEYS) <= set(PAICAD_KEYS)


def test_v_dp_7_job_type_static_cpu_queue_rules():
    from physicsai_core.job_types import HIDDEN_BY_DEFAULT, JOB_TYPES, NO_RETRY_JOB_TYPES, STEP_LABELS
    from physicsai_core.db.repositories.notifications import SILENT_JOB_TYPES

    jt = JOB_TYPES["DOE_PREVIEW"]
    assert (jt.stage, jt.lane, jt.label, jt.stage_label, jt.notify_success) == (1, "SLOT", "형상 미리보기(DOE)", "①", False)
    assert [(s.key, s.kind, s.weight, s.res) for s in jt.steps] == [
        ("DP_PREP", "INTERNAL", 5, "none"), ("DP_MATRIX", "INTERNAL", 10, "none"), ("DP_RENDER", "LOCAL", 80, "cpu"), ("DP_REGISTER", "INTERNAL", 5, "none")]
    assert "DOE_PREVIEW" in NO_RETRY_JOB_TYPES and "DOE_PREVIEW" in HIDDEN_BY_DEFAULT and "DOE_PREVIEW" in SILENT_JOB_TYPES
    assert all(f"{k}" in STEP_LABELS for k in ("DP_PREP", "DP_MATRIX", "DP_RENDER", "DP_REGISTER"))
    from physicsai_core.queues import initial_lane, segments, step_res

    assert initial_lane("DOE_PREVIEW") == "CPU" and segments("DOE_PREVIEW") == ["cpu"]  # PREVIEW 레인이 아니라 CPU 대기열(DP-C6), 구간 전환 없음
    assert [step_res(x) for x in jt.steps] == ["none", "none", "cpu", "none"]
    assert [jt.needs_slot(x) for x in jt.steps] == [True, True, True, True]  # SLOT 레인: INTERNAL도 CPU 슬롯 안에서(전역 슬롯 1개 보유)
    assert "DOE_PREVIEW" not in {k for k, d in JOB_TYPES.items() if d.lane == "PREVIEW"}
    # 이 작업이 쓰는 외부 명령은 grid 키 2개뿐(워커 정적 허용 목록)
    from physicsai_worker.steps.doe_preview import GRID_COMMANDS

    assert GRID_COMMANDS == {"paicad_view_grid", "paicad_shell_view_grid"} == {dp.grid_command_key("solid"), dp.grid_command_key("shell")}


def test_v_dp_13_mcp_excluded_and_openapi_x_mcp():
    from physicsai_api.mcp.job_kinds import JOB_KINDS, MCP_JOB_EXCLUDED

    assert "DOE_PREVIEW" in MCP_JOB_EXCLUDED and MCP_JOB_EXCLUDED["DOE_PREVIEW"] == "화면 전용 형상 그림 생성"
    assert not any("DOE_PREVIEW" in k.job_types for k in JOB_KINDS.values())
    spec = json.loads((REPO / "backend" / "openapi.json").read_text(encoding="utf-8"))
    ops = {}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if "doe-previews" in path:
                ops[f"{method.upper()} {path}"] = op
    assert set(ops) == {"POST /physicsai/api/studies/{study_id}/doe-previews", "GET /physicsai/api/doe-previews/{preview_id}",
                        "POST /physicsai/api/doe-previews/{preview_id}/cancel"}
    for key, op in ops.items():
        assert op["x-mcp"] == {"exclude": "화면 전용 형상 그림 생성"}, key
    post = ops["POST /physicsai/api/studies/{study_id}/doe-previews"]
    assert "200" in post["responses"] and "202" in post["responses"] and "409" in post["responses"] and "429" in post["responses"]
    for name in ("DoePreviewReq", "DoePreview", "DoePreviewCell", "DoePreviewSelect", "DoePreviewSource"):
        assert name in spec["components"]["schemas"]
    cell = spec["components"]["schemas"]["DoePreviewCell"]["properties"]
    assert {"doe_no", "nominal", "status", "values", "top_changes", "png_artifact_id", "glb_artifact_id", "manifest_artifact_id", "gen",
            "clipped", "max_disp_mm", "message_ko"} <= set(cell)
    assert "GEOM_THUMB_PNG" not in json.dumps(spec["paths"])  # 새 kind는 산출물 목록 API(문자열)에만


def test_v_dp_13_features_flag_and_status_schema():
    from physicsai_core.features import FEATURES, doe_preview_missing
    from physicsai_api.schemas.shell import StatusFeatures

    assert "doe_preview" in FEATURES and "doe_preview" in StatusFeatures.model_fields
    tmpl, res = doe_preview_missing(Settings(geometry={"paicad_path": "/nonexistent/paicad"}))
    assert tmpl == [] and res == ["geometry.paicad_path"]  # 켜짐·명령 있음, paicad 실행 파일이 없으면 res에 키
    off = Settings(doe_preview={"enabled": False})
    assert "doe_preview.enabled" in doe_preview_missing(off)[0]
    cmds = Settings(commands={"paicad_view_grid": None, "paicad_shell_view_grid": None})
    assert doe_preview_missing(cmds)[0] == ["commands.paicad_view_grid"]
    assert doe_preview_missing(cmds, "shell")[0] == ["commands.paicad_shell_view_grid"]


def test_v_dp_13_no_new_runtime_dependency_and_no_shell_or_paicad_import():
    """새 런타임 의존 0(paicad·백엔드 pyproject 무변경), 새 모듈은 paicad를 import하지 않고 shell=True·직접 subprocess를 쓰지 않는다."""
    files = [REPO / "backend" / "physicsai_core" / "geometry" / n for n in ("doe_preview.py", "doe_preview_src.py")] + \
            [REPO / "worker" / "physicsai_worker" / "steps" / "doe_preview.py", REPO / "backend" / "physicsai_api" / "services" / "doe_preview_api.py",
             REPO / "backend" / "physicsai_api" / "routers" / "doe_preview.py", REPO / "backend" / "physicsai_core" / "db" / "repositories" / "doe_preview.py"]
    for f in files:
        t = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+paicad\b", t, re.M), f
        assert "shell=True" not in t and "subprocess" not in t and "os.system" not in t, f
        assert "rmtree" not in t and "os.remove" not in t and "unlink" not in t, f  # 삭제 지점은 cache_store 하나
