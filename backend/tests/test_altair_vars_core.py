"""v0.2.8 Altair 변수 공간 — ①-2 전체 tpl 순수부(altair-vars.md §3·§4): V-AV-1(생성)·V-AV-2(사용 뷰)·표지·공칭 표기 손실·fill_nominal."""

from __future__ import annotations

import pytest

from physicsai_test_support import SIMLAB_TPL_TEMPLATE
from physicsai_core.config import TrainDataCfg
from physicsai_core.stage1_train_data import train_params as tp
from physicsai_core.stage1_train_data import train_tpl as tt
from physicsai_core.tpl_render import parse_declarations, parse_tpl, render_tpl

RULES = tt.TplRules.from_settings(TrainDataCfg())


def _table(n: int = 12, used: int = 4) -> list[dict]:
    """①-1 표 n행(사용 used개: 앞 4행 중 1·3·5·7번째 행 등 섞어서) — 이름 P01…, 공칭 10 + i, 형식 %8.4f(일부 %3i)."""
    use_idx = {0, 3, 4, 9}  # 사용 행이 표 중간에 섞임 → 선언 번호가 표 순서를 따르는지 확인
    rows = []
    for i in range(n):
        nom = 10.0 + i
        rows.append({"name": f"P{i + 1:02d}", "nominal": nom, "min": nom - 1, "max": nom + 1, "format": "%8.4f", "unit": "mm",
                     "use": i in use_idx if used == 4 else i < used})
    return rows


def _rows(table: list[dict]) -> list[dict]:
    rows, _skipped = tt.plan_rows(table)
    return rows


def test_v_av_1_full_tpl_declares_every_valid_row():
    table = _table()
    text_full = tt.generate(SIMLAB_TPL_TEMPLATE, _rows(table), "cad.prt", RULES, full=True)
    decl = parse_declarations(text_full)
    assert [d["name"] for d in decl] == [f"P{i:02d}" for i in range(1, 13)] and [d["var"] for d in decl] == [f"var_{i}" for i in range(1, 13)]
    for d, p in zip(decl, table):
        if p["use"]:
            assert (d["nominal"], d["min"], d["max"]) == (p["nominal"], p["min"], p["max"])
        else:
            assert d["min"] == d["max"] == d["nominal"] == p["nominal"]  # 미사용 = 공칭 고정
    assert text_full.count("<paramitem ") == 12
    assert [ln for ln in text_full.splitlines() if ln.startswith("# physicsai-tpl")] == [tt.SCOPE_LINE]  # 표지 줄 1개
    # 표지 줄 = parameter 블록 바로 뒤
    lines = text_full.splitlines()
    assert lines[12] == tt.SCOPE_LINE and lines[11].startswith("{parameter(var_12,")
    assert tt.scope_of(text_full) == "full" and "OLD_PARAM" not in text_full
    assert tt.validate_generated(text_full, tt.declared_rows(_rows(table))) == []
    # 부분 호출(v0.2.7 모양: used 키 없음, 표지 없음)은 표지·미사용 처리 없이 그대로
    part = tt.generate(SIMLAB_TPL_TEMPLATE, [p for p in table if p["use"]], "cad.prt", RULES)
    assert tt.scope_of(part) == "partial" and "physicsai-tpl" not in part and part.count("<paramitem ") == 4


def test_v_av_1_invalid_unused_rows_are_skipped_and_used_invalid_not_in_plan():
    table = _table()
    table[1]["min"] = table[1]["max"] = 11.0  # 미사용 + RANGE_INVALID(min < max 아님)
    table[2]["format"] = "bad"  # 미사용 + FORMAT_INVALID
    rows, skipped = tt.plan_rows(table)
    assert skipped == ["P02", "P03"] and [r["name"] for r in rows] == [f"P{i:02d}" for i in range(1, 13) if i not in (2, 3)]
    built = tt.generate_ex(SIMLAB_TPL_TEMPLATE, rows, "cad.prt", RULES, full=True)
    assert [d["name"] for d in parse_declarations(built.text)] == [r["name"] for r in rows]
    assert built.text.count("<paramitem ") == 10 and tt.validate_generated(built.text, built.declared) == []
    snap = tt.tpl_params_snapshot(built.declared)
    assert [s["var"] for s in snap] == [f"var_{i}" for i in range(1, 11)]  # 선언된 행만 번호
    assert snap[0] == {"var": "var_1", "name": "P01", "format": "%8.4f", "used": True, "table_min": 9.0, "table_max": 11.0, "unit": "mm"}
    assert [s["used"] for s in snap if s["name"] in ("P01", "P04", "P05", "P06")] == [True, True, True, False]
    assert tt.expected_snapshot(table) == snap  # stale 판정 기준 = 같은 표 → 같은 기록


def test_v_av_1_nominal_format_loss_row_is_literal():
    table = _table()
    table[5].update({"name": "N_RIB", "nominal": 2.85, "min": 2.0, "max": 4.0, "format": "%3i", "use": False})  # %3i % 2.85 → "  2" ≠ 2.85
    table[7].update({"nominal": 4.0, "min": 2.0, "max": 8.0, "format": "%3i", "use": False})  # 정수 공칭은 손실 없음
    rows = _rows(table)
    built = tt.generate_ex(SIMLAB_TPL_TEMPLATE, rows, "cad.prt", RULES, full=True)
    assert [r["name"] for r in built.literal] == ["N_RIB"]
    names = [d["name"] for d in parse_declarations(built.text)]
    assert "N_RIB" not in names and len(names) == 11 and "P08" in names
    item = next(ln for ln in built.text.splitlines() if 'Name="N_RIB"' in ln)
    assert 'NewValue="2.85"' in item and 'Value="2.85"' in item and "{var_" not in item  # 리터럴 Value, 변수 참조 없음
    assert built.text.count("<paramitem ") == 12
    assert tt.validate_generated(built.text, built.declared) == []
    assert [s["name"] for s in tt.tpl_params_snapshot(built.declared)] == names  # ④ 풀에 들어가지 않는다
    # 사용 행은 표기 손실이어도 리터럴이 아니다(표본이 움직이는 변수 — 기존 정수 반영 경고 U23)
    table[5]["use"] = True
    assert tt.generate_ex(SIMLAB_TPL_TEMPLATE, _rows(table), "cad.prt", RULES, full=True).literal == []
    assert tt.nominal_lost("%8.4f", 0.123456789012) and not tt.nominal_lost("%8.4f", 2.85) and tt.nominal_lost("%3d", 2.5)


def test_v_av_2_used_view_equals_v027_generate():
    table = _table()
    full = tt.generate(SIMLAB_TPL_TEMPLATE, _rows(table), "cad.prt", RULES, full=True)
    used = [p for p in table if p["use"]]
    v027 = tt.generate(SIMLAB_TPL_TEMPLATE, used, "cad.prt", RULES)
    view = tt.used_view(full, [p["name"] for p in used], {p["name"]: p["nominal"] for p in table})
    # 선언 집합·참조 집합이 v0.2.7 생성 tpl과 같다(변수 번호까지)
    assert parse_declarations(view) == parse_declarations(v027) and parse_tpl(view) == parse_tpl(v027)
    assert tt.scope_of(view) == "partial" and "physicsai-tpl" not in view
    # 차이는 미사용 paramitem 줄뿐 — 값 = fmt % 공칭 문자
    v_lines, o_lines = view.splitlines(), v027.splitlines()
    extra = [ln for ln in v_lines if ln not in o_lines]
    assert len(extra) == 8 and all("<paramitem " in ln and "{var_" not in ln for ln in extra)
    for ln in extra:
        name = ln.split('Name="')[1].split('"')[0]
        nom = next(p["nominal"] for p in table if p["name"] == name)
        assert f'NewValue="{"%8.4f" % nom}"' in ln
    assert [ln for ln in o_lines if ln not in v_lines] == []
    # 사용 행만으로 공칭을 모를 때(nominal_by_name 생략)는 선언의 공칭
    assert tt.used_view(full, [p["name"] for p in used]) == view
    # 모두 사용이면 표지 줄만 빠진 같은 텍스트
    allv = tt.used_view(full, [p["name"] for p in table])
    assert allv == full.replace(tt.SCOPE_LINE + "\n", "")


def test_used_view_keeps_literal_rows_and_renders_same_as_full():
    """사용 뷰 렌더 = 전체 tpl을 (표본 ∪ 공칭)으로 렌더한 것과 같다(레거시 HyperStudy 입력 일관성)."""
    table = _table()
    table[5].update({"name": "N_RIB", "nominal": 2.85, "min": 2.0, "max": 4.0, "format": "%3i", "use": False})
    full = tt.generate(SIMLAB_TPL_TEMPLATE, _rows(table), "cad.prt", RULES, full=True)
    used_names = [p["name"] for p in table if p["use"]]
    view = tt.used_view(full, used_names)
    sample = {n: float(i) + 0.5 for i, n in enumerate(used_names)}
    decl = parse_declarations(full)
    out_full = render_tpl(full, tt.fill_nominal(decl, sample), tt.fill_nominal(decl, sample))
    out_view = render_tpl(view, sample, sample)
    assert out_full.replace(tt.SCOPE_LINE + "\n", "") == out_view and 'NewValue="2.85"' in out_view  # 표지 줄은 렌더에도 남는 주석


def test_fill_nominal_and_scope_file(tmp_path):
    full = tt.generate(SIMLAB_TPL_TEMPLATE, _rows(_table()), "cad.prt", RULES, full=True)
    decl = parse_declarations(full)
    vals = {"P01": 9.5, "P04": 12.5}
    filled = tt.fill_nominal(decl, vals)
    assert filled["P01"] == 9.5 and filled["P04"] == 12.5 and filled["P02"] == 11.0 and len(filled) == 12 and vals == {"P01": 9.5, "P04": 12.5}
    # 렌더: 선언은 있지만 값이 없으면 기존 오류 — fill_nominal 뒤에는 성공, 값 줄이 fmt % 공칭
    with pytest.raises(Exception):
        render_tpl(full, vals, vals)
    out = render_tpl(full, filled, filled)
    assert 'NewValue=" 11.0000"' in out and 'NewValue="  9.5000"' in out
    p = tmp_path / "x.tpl"
    p.write_text(full, encoding="utf-8")
    assert tt.scope_of_file(str(p)) == "full" and tt.scope_of_file(str(tmp_path / "none.tpl")) is None
    q = tmp_path / "y.tpl"
    q.write_text(tt.generate(SIMLAB_TPL_TEMPLATE, _rows(_table())[:2], "cad.prt", RULES), encoding="utf-8")
    assert tt.scope_of_file(str(q)) == "partial"
    # BOM·CRLF에도 표지 판정
    assert tt.scope_of("﻿" + full.replace("\n", "\r\n")) == "full"


def test_summary_and_definition_key_and_stale():
    table = _table()
    table[5].update({"nominal": 2.85, "min": 2.0, "max": 4.0, "format": "%3i", "use": False})
    table[1]["max"] = table[1]["min"]
    rows, skipped = tt.plan_rows(table)
    built = tt.generate_ex(SIMLAB_TPL_TEMPLATE, rows, "cad.prt", RULES, full=True)
    warns = [{"code": tt.NOTE_SKIPPED, "names": skipped, "message": "m"},
             {"code": tt.NOTE_FORMAT_LOSS, "names": [p["name"] for p in built.literal], "message": "m"}]
    snap = tt.tpl_params_snapshot(built.declared)
    s = tt.summary_of(table, snap, warns)
    assert s == {"total": 11, "used": 4, "skipped": ["P02"], "format_loss": ["P06"], "scope": "full"}
    # 옛 부분 tpl 기록(키 없음) = 모두 사용, scope partial
    legacy = tt.tpl_params_snapshot([p for p in table if p["use"]])
    assert legacy[0] == {"var": "var_1", "name": "P01", "format": "%8.4f"} and not tt.is_full_snapshot(legacy)
    assert tt.summary_of(table, legacy, []) == {"total": 4, "used": 4, "skipped": [], "format_loss": [], "scope": "partial"}
    # definition_key: 전체 tpl이면 미사용 행 변경도 감지, 부분 tpl이면 사용 행만(v0.2.7 동작)
    t2 = [dict(p) for p in table]
    t2[8]["max"] += 1  # 미사용 행의 범위
    assert tp.definition_key(t2) == tp.definition_key(table) and tp.definition_key(t2, full=True) != tp.definition_key(table, full=True)
    t3 = [dict(p) for p in table]
    t3[0]["use"] = False
    assert tp.definition_key(t3) != tp.definition_key(table)
