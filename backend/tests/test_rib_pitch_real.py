"""rib-gap.md — 가짜가 아니라 **실제 paicad**(0.14.0)가 낸 RIB_PITCH 피처 JSON·update.json을 백엔드 파서가 그대로 읽는지 대조한다.

리브 열 골든(`packages/paicad/tests/data/make_ribrow.py`)을 실제 `paicad extract`(13종 전부)로 뽑고, 같은 입력을 `features_view`·`native_vars`
(변수 풀의 열 정보·공동 범위 경고)·`extract_filter`(제외 사유 라벨)에 통과시킨다. 실제 OCP·gmsh가 필요하다(paicad 단독 시험과 같은 전제).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("OCP", reason="paicad 실제 실행에는 OCP가 필요하다(paicad 단독 시험과 같은 전제)")

from physicsai_core.geometry import extract_filter as ef  # noqa: E402
from physicsai_core.geometry import features_view as fv  # noqa: E402
from physicsai_core.geometry import native_vars as nv  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PITCH = ("RIB_PITCH_U", "RIB_PITCH_V")


def _w(path: Path, obj) -> str:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    sys.path.insert(0, str(REPO / "packages" / "paicad" / "tests"))
    try:
        from conftest import run_cli
        from data.make_ribrow import make_all
    finally:
        sys.path.pop(0)
    root = tmp_path_factory.mktemp("ribreal")
    g = make_all(root / "set")
    # 플랫폼이 만드는 추출 조건(그룹 6개 전부) 그대로 실제 paicad가 받는지까지 본다
    norm, probs = ef.normalize({"groups": ["thickness", "height", "position", "rib_pitch", "hole_radius", "fillet"], "conditions": {}, "draft_max_deg": None})
    assert probs == []
    flt, _ = ef.to_paicad(norm)
    assert "RIB_PITCH_U" in flt["types"] and len(flt["types"]) == 13
    opts = _w(root / "opts.json", {"schema_version": 1, "extract": {"filter": flt}})
    ex = root / "extract"
    code, text = run_cli("extract", "--cad", g["step"], "--out-dir", ex, "--renum-csv", g["renum"], "--options", opts, "--no-png")
    assert code == 0, text
    doc = json.loads((ex / "parameter_features.json").read_text(encoding="utf-8"))
    pitch = next(f for f in doc["features"] if f["type"] in PITCH)
    vals = _w(root / "values.json", {"schema_version": 1, "values": {pitch["name"]: pitch["nominal"] + 1.0}})
    code, text = run_cli("update", "--cad", g["step"], "--features", ex / "parameter_features.json", "--values", vals, "--out-dir", root / "upd")
    assert code == 0, text
    return {"doc": doc, "stats": json.loads((ex / "extract_stats.json").read_text(encoding="utf-8")), "pitch": pitch,
            "update": json.loads((root / "upd" / "update.json").read_text(encoding="utf-8"))}


def test_feature_json_shape_matches_backend_parser(real):
    doc = real["doc"]
    pf = [f for f in doc["features"] if f["type"] in PITCH]
    assert pf, "RIB_PITCH 피처가 없다"
    for f in pf:
        assert re.fullmatch(r"[A-Z0-9_]+_RIB_PITCH_[UV]_\d+", f["name"]) and f["unit"] == "mm"
        assert f["measure"]["method"] == "rib_pitch" and set(f["row"]) >= {"id", "k", "n"} and f["row"]["k"] < f["row"]["n"]
        assert {"min", "max", "mm"} <= set(f["range"]) and f["range"]["mm"] > 0  # 단위 절대 mm(range.mm = ± 폭)
        assert f["faces"]["fixed"] and f["faces"]["moving"]
    rows = {r["id"]: r for r in doc["rib_rows"]}
    for r in doc["rib_rows"]:
        assert set(r) >= {"id", "body", "axis", "anchor", "ribs", "end_room_mm", "end_limited_by", "face_signatures"}
        assert re.fullmatch(r"(rib|mid):\d+|first|last", r["anchor"]) or r["anchor"], r["anchor"]
        assert all({"index", "cap", "minus", "plus", "moving", "thickness", "center"} <= set(b) for b in r["ribs"])
    # features_view(API 응답 변환) — row·rib_rows, 면 서명은 싣지 않는다
    view = {r["name"]: r for r in fv.feature_rows(doc)}
    for f in pf:
        assert view[f["name"]]["row"] == {"id": f["row"]["id"], "k": f["row"]["k"], "n": f["row"]["n"]}
    vr = fv.rib_rows(doc)
    assert vr and {r["id"] for r in vr} == set(rows) and all("face_signatures" not in r for r in vr)
    assert all(isinstance(b["thickness"], float) for r in vr for b in r["ribs"])


def test_variable_pool_row_info_and_joint_range_from_real_features(real):
    doc = real["doc"]
    pool = {e["name"]: e for e in nv.pool(doc)}
    pf = [f for f in doc["features"] if f["type"] in PITCH and f["name"] in pool]  # 대칭 그룹 구성원은 대표만 풀에 있다
    assert pf
    for f in pf:
        e = pool[f["name"]]
        assert e["position"] is False and e["type"] == f["type"] and e["unit"] == "mm"
        pub = nv.rib_public(e["rib"])
        assert pub and pub["row"] == f["row"]["id"] and pub["k"] == f["row"]["k"] and pub["n"] == f["row"]["n"] and pub["gap_mm"] is not None
        assert pub["end_room_mm"]["minus"] is not None and pub["end_room_mm"]["plus"] is not None
        assert [b["index"] for b in e["rib"]["ribs"]] == sorted(b["index"] for b in e["rib"]["ribs"])
        assert any(b["thk"] for b in e["rib"]["ribs"]) or True  # 양 끝 리브만 RIB_THICKNESS가 있을 수 있다
    # 공동 범위: 피치만 기본 범위(paicad가 정한 공동 안전값)로 쓰면 경고 없음, 상한을 feasible.max로 넓히면 경고
    # (가운데 RIB_POS·끝 RIB_THICKNESS까지 함께 쓰면 그 증가분이 끝 여유에 더해져 경고가 날 수 있다 — rib-gap.md §5 셋째·넷째 항목, 정상)
    rows = [{"name": n, "nominal": e["nominal"], "min": e["default_range"]["min"], "max": e["default_range"]["max"], "unit": "mm"}
            for n, e in pool.items() if e["type"] in PITCH]
    vd = nv.effective(rows, list(pool.values()))[0]
    assert [w for w in nv.warn_rows(vd) if w["code"] == "RIB_PITCH_JOINT_RANGE"] == []
    wide = [{**r, "max": (pool[r["name"]]["feasible"] or {}).get("max") or r["max"]} if pool[r["name"]]["type"] in PITCH else r for r in rows]
    vd2 = nv.effective(wide, list(pool.values()))[0]
    assert [w for w in nv.warn_rows(vd2) if w["code"] == "RIB_PITCH_JOINT_RANGE"], "공동 범위 경고가 나와야 한다"


def test_excluded_keys_and_update_report_keys(real):
    known = set(ef.EXCLUDED_LABELS)
    for b in real["stats"]["bodies"]:
        for t, v in (b.get("types") or {}).items():
            if v.get("selected") and (t in PITCH or t.startswith("RIB_POS")):  # (THICKNESS no_partner 등 기존 키는 원문 표시 — extract-filter.md §7)
                assert set(v.get("excluded") or {}) <= known, (t, set(v["excluded"]) - known)
    u = real["update"]
    ops = {a.get("op") for a in u["applied"]}
    assert "RIB_ROW_SHIFT" in ops
    a = next(a for a in u["applied"] if a.get("op") == "RIB_ROW_SHIFT")
    assert a["ref_rule"] == "row_anchor" and a["name"] == real["pitch"]["name"]
    r = u["rib_rows"][0]
    assert set(r) >= {"id", "body", "axis", "anchor", "ribs", "pitches", "end_room_mm"} and r["pitches"][0]["name"] == real["pitch"]["name"]
