"""v0.2.8 ①-2 전체 tpl·① DOE 불변(altair-vars.md §3·§4): V-AV-1(생성 API)·V-AV-3(① DOE 불변)·AV-7(레거시 hstbatch 사용 뷰).

기준(v0.2.7 상태)은 같은 표로 부분 tpl(사용 파라미터만, 표지 줄 없음)을 직접 만들어 DB 기록을 v0.2.7 모양으로 되돌려 재현한다.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from sqlalchemy import text

from helpers_stage1 import doe_gen, job, make_inputs, study, submit
from physicsai_core.config import TrainDataCfg
from physicsai_core.fileutil import sha256_file
from physicsai_core.stage1_train_data import train_tpl as tt
from physicsai_core.tpl_render import parse_declarations, parse_tpl
from physicsai_test_support import API, H, SIMLAB_TPL_TEMPLATE

PW, P = H("tok-power", write=True), H("tok-power")
RULES = tt.TplRules.from_settings(TrainDataCfg())


def _extract(c, w, ai: Path, name: str) -> tuple[str, dict]:
    sid = study(c, name)
    cad, _a = make_inputs(ai / name)
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    return sid, c.get(f"{API}/studies/{sid}/train", headers=P).json()


def _put_tpl(c, sid: str, ts: dict, *, rib_format: str, rib_use: bool) -> dict:
    """THK_1 사용(%3i), RIB_H = rib_use·rib_format, 'bad name' 무효 미사용 → 저장 → tpl 생성."""
    rows = [{"name": p["name"], "min": p["min"], "max": p["max"], "use": p["use"], "format": p["format"]} for p in ts["parameters"]]
    for r in rows:
        if r["name"] == "RIB_H":
            r["use"], r["format"] = rib_use, rib_format
    r = c.put(f"{API}/studies/{sid}/train/params", headers=PW, json={"version": ts["version"], "parameters": rows})
    assert r.status_code == 200, r.text
    r = c.post(f"{API}/studies/{sid}/train/tpl", headers=PW, json={"version": r.json()["version"]})
    assert r.status_code == 200, r.text
    return r.json()


def _make_v027(c, engine, ai: Path, name: str, sid: str) -> None:
    """같은 표로 v0.2.7 tpl(부분)·기록(`{var, name, format}`)을 다시 써서 v0.2.7 상태를 재현."""
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    used = [p for p in ts["parameters"] if p["use"]]
    path = ai / name / "01_train" / "tpl" / "simlab_parametered_mesh.tpl"
    path.write_text(tt.generate(SIMLAB_TPL_TEMPLATE, used, "cushion_parametric.prt", RULES), encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text("update train_setups set tpl_sha256=:h, tpl_params=cast(:p as jsonb) where study_id=:s"),
                     {"h": sha256_file(str(path)), "p": json.dumps(tt.tpl_params_snapshot(used)), "s": sid})
    assert c.get(f"{API}/studies/{sid}/train", headers=P).json()["tpl"]["stale"] is False


def _gen(c, sid: str, ai: Path, name: str, sampling: dict) -> dict:
    return submit(c, sid, "TD_DOE_GEN", {"sampling": sampling, "radioss_assem_path": str(ai / name / "00_inbox" / "radioss_assem"),
                                         "multi_execution": 2})


def _doe_rows(engine, doe_id: str):
    with engine.connect() as conn:
        pts = conn.execute(text("select doe_no, run_key, values, applied_values from train_doe_points where doe_id=:d order by doe_no"),
                           {"d": doe_id}).all()
        d = conn.execute(text("select parameters_snapshot, run_count, num_runs_requested, sampling->'kind' from train_does where id=:d"),
                         {"d": doe_id}).one()
    return [tuple(r) for r in pts], d


def test_v_av_1_generate_api_full_tpl_summary_and_stale(p2_env, engine):
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid, ts = _extract(c, w, ai, "av1")
    out = _put_tpl(c, sid, ts, rib_format="%3i", rib_use=False)  # 미사용 RIB_H(공칭 12.5) + %3i → 표기 손실 / 무효 미사용 'bad name' → 건너뜀
    tpl = out["tpl"]
    assert out["tpl_summary"] == {"total": 2, "used": 1, "skipped": ["bad name"], "format_loss": ["RIB_H"], "scope": "full"}
    assert [p["name"] for p in tpl["params"]] == ["THK_1"] and tpl["params"][0]["used"] is True
    assert {w_["code"] for w_ in tpl["warnings"]} == {"TPL_INTEGER_FORMAT", "TPL_PARAM_SKIPPED", "TPL_NOMINAL_FORMAT_LOSS"} and tpl["stale"] is False
    text_ = (ai / "av1" / "01_train" / "tpl" / "simlab_parametered_mesh.tpl").read_text()
    assert tt.scope_of(text_) == "full" and text_.count("<paramitem ") == 2
    assert 'Name="RIB_H" NewValue="12.5" Value="12.5"' in text_ and "RIB_H" not in [d["name"] for d in parse_declarations(text_)]
    # 감사 detail
    with engine.connect() as conn:
        det = conn.execute(text("select detail from audit_events where action='TRAIN_TPL_GENERATE' and target_id=:s"), {"s": sid}).scalar()
    assert det == {"used": 1, "total": 2, "skipped": 1}
    # 미사용 행을 %8.4f로 바꿔 다시 생성 → 선언 2개(RIB_H 미사용 = 공칭 고정), 표지 1줄
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    out = _put_tpl(c, sid, ts, rib_format="%8.4f", rib_use=False)
    text_ = (ai / "av1" / "01_train" / "tpl" / "simlab_parametered_mesh.tpl").read_text()
    decl = {d["name"]: d for d in parse_declarations(text_)}
    assert (decl["RIB_H"]["nominal"], decl["RIB_H"]["min"], decl["RIB_H"]["max"]) == (12.5, 12.5, 12.5)
    assert (decl["THK_1"]["min"], decl["THK_1"]["max"]) == (2.85, 3.15) and text_.count("physicsai-tpl scope=full") == 1
    assert out["tpl_summary"] == {"total": 2, "used": 1, "skipped": ["bad name"], "format_loss": [], "scope": "full"}
    snap = {p["name"]: p for p in out["tpl"]["params"]}
    assert snap["RIB_H"]["used"] is False and (snap["RIB_H"]["table_min"], snap["RIB_H"]["table_max"]) == (11.875, 13.125)
    # 미사용 행의 범위를 바꾸면 전체 tpl은 stale(DOE 생성 409 TPL_STALE) — v0.2.7(부분 tpl)은 stale이 아니었다
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    rows = [{"name": p["name"], "min": p["min"], "max": p["max"], "use": p["use"], "format": p["format"]} for p in ts["parameters"]]
    for r in rows:
        if r["name"] == "RIB_H":
            r["max"] = 14.0
    assert c.put(f"{API}/studies/{sid}/train/params", headers=PW, json={"version": ts["version"], "parameters": rows}).status_code == 200
    assert c.get(f"{API}/studies/{sid}/train", headers=P).json()["tpl"]["stale"] is True


def test_v_av_3_doe_unchanged_vs_v027_and_nominal_render(p2_env, engine, tmp_path, monkeypatch):
    """같은 표·seed·설정: 점 표·parameters_snapshot·run 수 동일, 렌더 스크립트 차이 = 미사용 paramitem 줄뿐(값 = fmt % 공칭)."""
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    pit = tmp_path / "paramitems.jsonl"
    monkeypatch.setenv("FAKE_SIMLAB_PARAMITEMS", str(pit))
    sampling = {"kind": "lhs", "count": 4, "seed": 11}
    res = {}
    for name, legacy in (("av3n", False), ("av3o", True)):
        sid, ts = _extract(c, w, ai, name)
        _put_tpl(c, sid, ts, rib_format="%8.4f", rib_use=False)
        if legacy:
            _make_v027(c, engine, ai, name, sid)
        j = _gen(c, sid, ai, name, sampling)
        assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
        doe_id = job(c, j["id"])["result"]["doe_id"]
        D = ai / name / "01_train" / "doe" / doe_id
        res[name] = {"doe_id": doe_id, "D": D, "rows": _doe_rows(engine, doe_id)}
    new, old = res["av3n"], res["av3o"]
    assert new["rows"] == old["rows"]  # 점 표(값·반영값)·parameters_snapshot(사용 행)·run 수·표본 방식 동일
    pts, d = new["rows"]
    assert [s["name"] for s in d[0]] == ["THK_1"] and d[1] == 4 and d[2] == 4 and len(pts) == 4
    assert all(set(p[2]) == {"THK_1"} and set(p[3]) == {"THK_1"} for p in pts)  # 표본은 사용 행만
    # D tpl: 플랫폼 DOE = 전체 tpl 사본(AV-7), v0.2.7 = 부분 tpl
    assert tt.scope_of((new["D"] / "simlab_parametered_mesh.tpl").read_text()) == "full"
    assert tt.scope_of((old["D"] / "simlab_parametered_mesh.tpl").read_text()) == "partial"
    assert {x for x in os.listdir(new["D"])} == {x for x in os.listdir(old["D"])}  # 폴더 구성도 같다(.full.tpl 없음)
    # 렌더 스크립트: 차이는 RIB_H paramitem 줄(+표지 주석 줄)뿐, 값 = %8.4f % 12.5
    for n in range(1, 5):
        rk = f"run__{n:05d}"
        a = (new["D"] / "approaches" / "doe_1" / rk / "m_1" / "simlab_parametered_mesh.py").read_text().splitlines()
        b = (old["D"] / "approaches" / "doe_1" / rk / "m_1" / "simlab_parametered_mesh.py").read_text().splitlines()
        extra = [ln for ln in a if ln not in b]
        assert [ln for ln in b if ln not in a] == []
        assert sorted(ln.strip() for ln in extra) == sorted([tt.SCOPE_LINE, '<paramitem Name="RIB_H" NewValue=" 12.5000" Value="12.5"/>'])
        # THK_1 줄은 같은 값(표본 반영값 %3i)
        assert [ln for ln in a if 'Name="THK_1"' in ln] == [ln for ln in b if 'Name="THK_1"' in ln]
    # fake_simlab 입력 확인: 전체 tpl의 모든 파라미터 paramitem에 값이 들어갔다(치환 안 된 참조 없음 — 있으면 run 실패)
    recs = [json.loads(x) for x in pit.read_text().splitlines()]
    mine = [r for r in recs if "/av3n/" in r["cwd"]]
    assert len(mine) == 4 and all(set(r["paramitems"]) == {"THK_1", "RIB_H"} for r in mine)
    assert all(r["paramitems"]["RIB_H"] == " 12.5000" for r in mine)
    olds = [r for r in recs if "/av3o/" in r["cwd"]]
    assert len(olds) == 4 and all(set(r["paramitems"]) == {"THK_1"} for r in olds)  # v0.2.7: 미사용은 아예 없었다


def test_av_7_legacy_hstbatch_gets_used_view_and_full_copy(p2_env, engine):
    """레거시 hstbatch ① DOE: D/simlab_parametered_mesh.tpl = 사용 뷰(v0.2.7 생성 tpl과 선언·참조 같음), 전체 tpl은 .full.tpl."""
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid, ts = _extract(c, w, ai, "av7")
    _put_tpl(c, sid, ts, rib_format="%8.4f", rib_use=False)
    jd = doe_gen(c, w, sid, ai, "av7", num_runs=3)
    D = ai / "av7" / "01_train" / "doe" / jd["result"]["doe_id"]
    view = (D / "simlab_parametered_mesh.tpl").read_text()
    full = (D / "simlab_parametered_mesh.full.tpl").read_text()
    assert tt.scope_of(full) == "full" and tt.scope_of(view) == "partial"
    used = [p for p in c.get(f"{API}/studies/{sid}/train", headers=P).json()["parameters"] if p["use"]]
    assert [p["name"] for p in used] == ["THK_1"]
    v027 = tt.generate(SIMLAB_TPL_TEMPLATE, used, "cushion_parametric.prt", RULES)
    assert parse_declarations(view) == parse_declarations(v027) and parse_tpl(view) == parse_tpl(v027)
    assert [d["name"] for d in parse_declarations(full)] == ["THK_1", "RIB_H"]
    with engine.connect() as conn:
        sha = conn.execute(text("select tpl_sha256 from train_does where id=:d"), {"d": jd["result"]["doe_id"]}).scalar()
    assert sha == sha256_file(str(D / "simlab_parametered_mesh.tpl"))
    # 부분 tpl(옛 것)이면 그대로 복사하고 .full.tpl은 만들지 않는다
    sid2, ts2 = _extract(c, w, ai, "av7b")
    _put_tpl(c, sid2, ts2, rib_format="%8.4f", rib_use=False)
    _make_v027(c, engine, ai, "av7b", sid2)
    jd2 = doe_gen(c, w, sid2, ai, "av7b", num_runs=3)
    D2 = ai / "av7b" / "01_train" / "doe" / jd2["result"]["doe_id"]
    assert not (D2 / "simlab_parametered_mesh.full.tpl").exists() and tt.scope_of((D2 / "simlab_parametered_mesh.tpl").read_text()) == "partial"


def _from_train(c, sid: str, doe_id: str, source: str | None, expect: int = 201) -> dict:
    body = {"doe_id": doe_id, "runs": "all", **({"tpl_source": source} if source else {})}
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def _vars(c, ps_id: str) -> dict:
    r = c.get(f"{API}/param-sets/{ps_id}/variables", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def test_v_av_7_from_train_tpl_source_doe_and_current(p2_env, engine):
    """① DOE → 템플릿: doe(기본) = DOE 폴더 tpl, current = 현재 ①-2 전체 tpl. 둘 다 전체 tpl 세트(풀 = 모든 파라미터, 표 범위·used 기록)."""
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid, ts = _extract(c, w, ai, "av7c")
    _put_tpl(c, sid, ts, rib_format="%8.4f", rib_use=False)
    j = _gen(c, sid, ai, "av7c", {"kind": "lhs", "count": 4, "seed": 5})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    table = {p["name"]: p for p in ts["parameters"]}
    sets = {}
    for source in (None, "doe", "current"):
        ps = _from_train(c, sid, doe_id, source)
        sets[source or "default"] = ps
        g = _vars(c, ps["id"])
        assert g["engine"] == "altair" and g["editable"] is True and g["revision"] == 0
        assert [p["name"] for p in g["pool"]] == ["THK_1", "RIB_H"] and [v["name"] for v in g["variables"]] == ["THK_1"]  # 정의 = DOE 사용 행
        pool = {p["name"]: p for p in g["pool"]}
        for n in ("THK_1", "RIB_H"):                                              # 기본 범위 = ①-1 표 범위(미사용 행 포함)
            assert pool[n]["default_range"] == {"min": table[n]["min"], "max": table[n]["max"]} and pool[n]["range_unset"] is False
        info = c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()
        assert info["vars_scope"] == "full" and info["vars_count"] == 1
        rows = {r["name"]: r for r in info["tpl_params"]}
        assert rows["THK_1"]["used"] is True and rows["RIB_H"]["used"] is False and rows["RIB_H"]["table_min"] == table["RIB_H"]["min"]
    # 같은 DOE에서 만든 세트는 tpl 본문까지 같다
    S = {k: ai / "av7c" / "04_params" / v["id"] / "simlab_parametered_mesh.tpl" for k, v in sets.items()}
    assert S["doe"].read_text() == S["default"].read_text() == S["current"].read_text()
    # 미사용 RIB_H를 변수로 추가 + 그 범위로 ④ 미리보기(변수 정의 편집 → ④)
    cur = sets["current"]
    put = c.put(f"{API}/param-sets/{cur['id']}/variables", headers=PW, json={"base_revision": 0, "variables": [
        {"name": "THK_1", "min": math.ceil(table["THK_1"]["min"]), "max": math.floor(table["THK_1"]["max"])},  # THK_1 = 정수 형식(%3i)
        {"name": "RIB_H", "min": table["RIB_H"]["min"], "max": table["RIB_H"]["max"]}]})
    assert put.status_code == 200, put.text
    pv = c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW, json={"param_set_id": cur["id"], "source": {"kind": "lhs", "count": 3, "seed": 1}})
    assert pv.status_code == 200 and pv.json()["problems"] == [] and set(pv.json()["rows"][0]["values"]) == {"THK_1", "RIB_H"}, pv.text
    # ①-2 표를 바꿔 tpl을 다시 만들면(사용 THK_1 범위 변경) current는 DOE와 달라 409, doe는 그대로 성공
    ts2 = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    rows = [{"name": p["name"], "min": p["min"], "max": p["max"] + 1.0 if p["name"] == "THK_1" else p["max"], "use": p["use"], "format": p["format"]}
            for p in ts2["parameters"]]
    r = c.put(f"{API}/studies/{sid}/train/params", headers=PW, json={"version": ts2["version"], "parameters": rows})
    assert r.status_code == 200, r.text
    r = c.post(f"{API}/studies/{sid}/train/tpl", headers=PW, json={"version": r.json()["version"]})
    assert r.status_code == 200, r.text
    err = _from_train(c, sid, doe_id, "current", expect=409)
    assert err["detail"]["code"] == "TPL_DOE_MISMATCH"
    _from_train(c, sid, doe_id, "doe")
    # 옛 부분 tpl(①-2 현재 tpl): current는 422 TPL_SCOPE_PARTIAL
    _make_v027(c, engine, ai, "av7c", sid)
    err = _from_train(c, sid, doe_id, "current", expect=422)
    assert err["detail"]["code"] == "TPL_SCOPE_PARTIAL"
    assert _from_train(c, sid, doe_id, "bogus", expect=422)["detail"]


def test_v_av_7_from_train_current_requires_tpl_record_and_file(p2_env, engine):
    """tpl_source=current: ①-2 tpl 기록(tpl_rel)이 없거나 파일 sha가 기록과 다르면 409 TPL_REQUIRED(DOE는 그대로 doe 출처로 성공)."""
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid, ts = _extract(c, w, ai, "av7d")
    _put_tpl(c, sid, ts, rib_format="%8.4f", rib_use=False)
    j = _gen(c, sid, ai, "av7d", {"kind": "lhs", "count": 4, "seed": 5})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    tpl = ai / "av7d" / "01_train" / "tpl" / "simlab_parametered_mesh.tpl"
    original = tpl.read_bytes()
    # sha 불일치: 파일이 기록(tpl_sha256)과 다르게 바뀜
    tpl.write_bytes(original + b"\n# edited by hand\n")
    err = _from_train(c, sid, doe_id, "current", expect=409)
    assert err["detail"]["code"] == "TPL_REQUIRED" and "바뀌었습니다" in err["detail"]["message"]
    tpl.write_bytes(original)
    # tpl 파일 없음
    tpl.unlink()
    assert _from_train(c, sid, doe_id, "current", expect=409)["detail"]["code"] == "TPL_REQUIRED"
    tpl.write_bytes(original)
    # tpl_rel 기록 없음(①-2에서 tpl을 만든 적 없는 상태)
    with engine.begin() as conn:
        conn.execute(text("update train_setups set tpl_rel=null where study_id=:s"), {"s": sid})
    err = _from_train(c, sid, doe_id, "current", expect=409)
    assert err["detail"]["code"] == "TPL_REQUIRED" and "먼저 생성" in err["detail"]["message"]
    _from_train(c, sid, doe_id, "doe")                                   # doe 출처는 ①-2 기록과 무관하게 성공
