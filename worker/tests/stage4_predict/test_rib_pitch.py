"""rib-gap.md V-RG-9(플랫폼): 추출 조건 그룹 `rib_pitch`(세트 등록·①-1) → 피처 `row`·`rib_rows` 전달, 변수 풀의 `rib` 요약(mm·position=false), 변수 표 저장
경고 `RIB_PITCH_JOINT_RANGE` 세 경우(끝 여유·가운데 RIB_POS 합산·두께 상한 빈 간격), RIB_PITCH 미선택 시 기존과 같음. 가짜 paicad(합성 열 U1·V1)."""

from __future__ import annotations

import json

from helpers_native import make_project
from physicsai_test_support import API, H

PW = H("tok-power", write=True)
P = H("tok-power")
PITCH = {"groups": ["thickness", "rib_pitch"], "conditions": {}, "draft_max_deg": None}
U_PITCH, V_PITCH = ["B_RIB_PITCH_U_1", "B_RIB_PITCH_U_2", "B_RIB_PITCH_U_3"], ["B_RIB_PITCH_V_1", "B_RIB_PITCH_V_2"]


def _reg(env, **kw):
    proj = make_project(env.imports)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW, json={"path": str(proj), "mode": "discover", "engine": "native", **kw})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    return env.c.get(f"{API}/param-sets/{env.job(r.json()['job_id'])['result']['param_set_id']}", headers=P).json()


def _vars(env, ps):
    r = env.c.get(f"{API}/param-sets/{ps['id']}/variables", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def _put(env, ps, items, expect=200):
    cur = _vars(env, ps)["revision"]
    r = env.c.put(f"{API}/param-sets/{ps['id']}/variables", headers=PW,
                  json={"base_revision": cur, "variables": [{"name": n, "min": a, "max": b} for n, a, b in items]})
    assert r.status_code == expect, r.text
    return r.json()


def _codes(out):
    return [(w["code"], w.get("name")) for w in out["warnings"]]


def test_register_with_rib_pitch_features_rows_and_pool(native_env):
    env = native_env()
    ps = _reg(env, extract_filter=PITCH)
    assert ps["native"]["extract_filter"]["groups"] == ["thickness", "rib_pitch"]
    f = env.c.get(f"{API}/param-sets/{ps['id']}/features", headers=P).json()
    assert f["filter"]["groups"] == ["thickness", "rib_pitch"]
    by = {x["name"]: x for x in f["features"]}
    assert set(U_PITCH + V_PITCH) <= set(by) and by["B_RIB_PITCH_U_2"]["row"] == {"id": "U1", "k": 2, "n": 4}
    assert by["B_RIB_PITCH_V_1"]["row"] == {"id": "V1", "k": 1, "n": 3} and by["A_THK_1"].get("row") is None
    assert (by["B_RIB_PITCH_U_1"]["min"], by["B_RIB_PITCH_U_1"]["max"], by["B_RIB_PITCH_U_1"]["nominal"]) == (15.0, 25.0, 20.0)
    rows = {r["id"]: r for r in f["rib_rows"]}
    assert set(rows) == {"U1", "V1"} and rows["U1"]["anchor"] == "mid:2" and rows["V1"]["anchor"] == "rib:2"
    assert rows["U1"]["end_room_mm"] == {"minus": 12.4, "plus": 18.0} and [b["index"] for b in rows["U1"]["ribs"]] == [1, 2, 3, 4]
    assert all("face_signatures" not in r for r in rows.values())  # 화면용 필드만
    v = _vars(env, ps)
    pool = {e["name"]: e for e in v["pool"]}
    e = pool["B_RIB_PITCH_U_2"]
    assert e["position"] is False and e["unit"] == "mm" and e["type"] == "RIB_PITCH_U" and e["default_range"] == {"min": 15.0, "max": 25.0}
    assert e["rib"] == {"row": "U1", "k": 2, "n": 4, "anchor": "mid:2", "gap_mm": 14.0, "end_room_mm": {"minus": 12.4, "plus": 18.0}}
    assert pool["B_RIB_PITCH_V_2"]["rib"]["anchor"] == "rib:2" and pool["A_THK_1"]["rib"] is None
    assert e["feasible"]["min"] == 7.0


def test_rib_pitch_not_selected_is_unchanged(native_env):
    env = native_env()
    ps = _reg(env, extract_filter={"groups": ["thickness", "position"], "conditions": {}, "draft_max_deg": None})
    f = env.c.get(f"{API}/param-sets/{ps['id']}/features", headers=P).json()
    assert f["rib_rows"] is None and not any(x["type"].startswith("RIB_PITCH") or x.get("row") for x in f["features"])
    ps2 = _reg(env)  # 필터 없음 = 기존 결과
    f2 = env.c.get(f"{API}/param-sets/{ps2['id']}/features", headers=P).json()
    assert f2["rib_rows"] is None and [x["name"] for x in f2["features"]] == ["A_THK_1", "A_THK_2", "B_RIB_H_1", "C_HOLE_R_1"]
    S = env.sroot / "04_params" / ps["id"] / "native" / "extract" / "parameter_features.json"
    assert "rib_rows" not in json.loads(S.read_text(encoding="utf-8"))


def test_joint_range_warnings_three_cases(native_env):
    env = native_env()
    ps = _reg(env, extract_filter=PITCH)
    # 기준: U1(mid:2, 피치 3개: k=1 −쪽, k=2 가운데(−·+ ½), k=3 +쪽), 끝 여유 −12.4/+18.0, 끝 리브 두께 변수 B_RIB_T_1(리브 1)·B_RIB_T_2(리브 4)
    ok = [("B_RIB_PITCH_U_1", 15.0, 25.0), ("B_RIB_PITCH_U_2", 15.0, 25.0), ("B_RIB_PITCH_U_3", 15.0, 25.0)]
    out = _put(env, ps, ok)  # −쪽: 5 + ½·5 = 7.5 ≤ 12.4, +쪽: ½·5 + 5 = 7.5 ≤ 18.0 → 경고 없음
    assert [w for w in out["warnings"] if w["code"] == "RIB_PITCH_JOINT_RANGE"] == []
    # 1) 한쪽 합 > 끝 여유: −쪽 k=1·가운데 상한을 키워 5+… (공칭 20 → 상한 40: 20 + ½·20 = 30 > 12.4)
    out = _put(env, ps, [("B_RIB_PITCH_U_1", 15.0, 40.0), ("B_RIB_PITCH_U_2", 15.0, 40.0), ("B_RIB_PITCH_U_3", 15.0, 25.0)])
    ws = [w for w in out["warnings"] if w["code"] == "RIB_PITCH_JOINT_RANGE"]
    assert len(ws) == 1 and ws[0]["name"] == "B_RIB_PITCH_U_1"  # −쪽 20 + ½·20 = 30 > 12.4, +쪽 ½·20 + 5 = 15 ≤ 18.0
    assert "U1" in ws[0]["message"] and "−쪽" in ws[0]["message"] and "12.4" in ws[0]["message"]
    assert "일부 샘플이 형상 생성에 실패할 수 있습니다" in ws[0]["message"]
    # 끝 리브 두께 증가의 ½도 끝 여유를 쓴다: +쪽 합 7.5 + (B_RIB_T_2 상한 16 → +10 → 5) = 12.5 ≤ 18, 상한 32면 7.5 + 13 = 20.5 > 18
    assert not [w for w in _put(env, ps, [*ok, ("B_RIB_T_2", 5.7, 16.0)])["warnings"] if "끝 여유" in w["message"]]
    out = _put(env, ps, [*ok, ("B_RIB_T_2", 5.7, 32.0)])
    ws = [w for w in out["warnings"] if w["code"] == "RIB_PITCH_JOINT_RANGE" and "끝 여유" in w["message"]]
    assert len(ws) == 1 and "+쪽" in ws[0]["message"] and "18" in ws[0]["message"]
    # 3) 이웃 두 리브 두께 상한 반합 + 최소 간격 > 피치 하한: 피치 하한을 모핑 가능 하한(7)에 가깝게(8) + 두께 상한 +3(6→9; 이웃 리브 1·2 중 리브 1 변수)
    out = _put(env, ps, [("B_RIB_PITCH_U_1", 8.0, 22.0), ("B_RIB_T_1", 5.7, 9.0)])
    ws = [w for w in out["warnings"] if w["code"] == "RIB_PITCH_JOINT_RANGE" and "빈 간격" in w["message"]]
    assert len(ws) == 1 and ws[0]["name"] == "B_RIB_PITCH_U_1" and "리브 두께 상한에서 빈 간격이 최소 간격보다 작아질 수 있습니다" in ws[0]["message"]
    out = _put(env, ps, [("B_RIB_PITCH_U_1", 8.0, 22.0), ("B_RIB_T_1", 5.7, 6.3)])  # 두께 증가 0.15 ≤ 여유(8 − 7 = 1) → 없음
    assert not [w for w in out["warnings"] if "빈 간격" in w["message"]]
    assert not [w for w in _put(env, ps, [("B_RIB_PITCH_U_1", 15.0, 25.0)])["warnings"] if w["code"] == "RIB_PITCH_JOINT_RANGE"]


def _feat(name, typ, nominal, lo, hi, **extra):
    return {"name": name, "type": typ, "body": "B", "nominal": nominal, "unit": "mm", "range": {"min": lo, "max": hi, "ratio": None},
            "group": None, "ref": {"rule": "nearest_fixed", "provisional": True, "locked": False}, **extra}


def test_joint_range_with_middle_rib_pos(native_env, monkeypatch):
    """③ 홀수 열(rib:2)의 가운데 리브 RIB_POS를 함께 쓰면 그 방향 이동 범위를 같은 쪽 피치 상한 합에 더해 판정(같은 경고)."""
    env = native_env()
    row = {"id": "V1", "body": "B", "axis": "x", "base": "F1", "anchor": "rib:2", "end_limited_by": {"minus": None, "plus": None},
           "end_room_mm": {"minus": 9.0, "plus": 9.0}, "face_signatures": {},
           "ribs": [{"index": i, "cap": f"F{i}0", "minus": f"F{i}1", "plus": f"F{i}2", "moving": [], "thickness": 6.0, "center": 20.0 * i} for i in (1, 2, 3)]}
    feats = [_feat("B_RIB_PITCH_V_1", "RIB_PITCH_V", 20.0, 15.0, 25.0, feasible={"min": 7.0, "max": 27.0, "limited_by": None},
                   measure={"method": "rib_pitch", "faces": ["F11", "F12", "F21", "F22"], "axis": "x"}, row={"id": "V1", "k": 1, "n": 3}),
             _feat("B_RIB_PITCH_V_2", "RIB_PITCH_V", 20.0, 15.0, 25.0, feasible={"min": 7.0, "max": 27.0, "limited_by": None},
                   measure={"method": "rib_pitch", "faces": ["F21", "F22", "F31", "F32"], "axis": "x"}, row={"id": "V1", "k": 2, "n": 3}),
             _feat("B_RIB_V_9", "RIB_POS_V", 40.0, 35.0, 45.0, measure={"method": "rib_center", "faces": ["F21", "F22"], "axis": "x"})]
    monkeypatch.setenv("FAKE_PAICAD_FEATURES", json.dumps(feats))
    monkeypatch.setenv("FAKE_PAICAD_RIB_ROWS", json.dumps([row]))
    ps = _reg(env, extract_filter={"groups": ["position", "rib_pitch"], "conditions": {}, "draft_max_deg": None})
    pool = {e["name"]: e for e in _vars(env, ps)["pool"]}
    assert pool["B_RIB_PITCH_V_1"]["rib"]["anchor"] == "rib:2" and pool["B_RIB_V_9"]["rib"] is None and pool["B_RIB_V_9"]["position"] is True
    base = [("B_RIB_PITCH_V_1", 15.0, 25.0), ("B_RIB_PITCH_V_2", 15.0, 25.0)]
    assert not [w for w in _put(env, ps, base)["warnings"] if w["code"] == "RIB_PITCH_JOINT_RANGE"]  # 5 ≤ 9
    out = _put(env, ps, [*base, ("B_RIB_V_9", 35.0, 45.0)])  # −쪽 5 + 5 = 10 > 9, +쪽 5 + 5 = 10 > 9
    ws = [w for w in out["warnings"] if w["code"] == "RIB_PITCH_JOINT_RANGE"]
    assert sorted("−쪽" if "−쪽" in w["message"] else "+쪽" for w in ws) == ["+쪽", "−쪽"] and all("가운데 리브 위치 범위" in w["message"] for w in ws)
    out = _put(env, ps, [*base, ("B_RIB_V_9", 39.0, 45.0)])  # 위치 −1: −쪽 5 + 1 = 6 ≤ 9, +쪽 10 > 9 → 한쪽만
    ws = [w for w in out["warnings"] if w["code"] == "RIB_PITCH_JOINT_RANGE"]
    assert len(ws) == 1 and "+쪽" in ws[0]["message"]
