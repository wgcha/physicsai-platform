"""doe-methods.md DM-C2·C8: ①-3 Native 단일 baseline(①-1 Native 추출 기준) 표본 방식 확대 — V-DM-1(lhs 골든 불변)·V-DM-2(전 kind 워커 행 =
`doe_platform.build` 행, API check run 수 = 워커 행 수, sampling.meta 기록)·V-DM-5(① table, Native). 가짜 paicad."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

import pytest
from helpers_native import make_project
from helpers_stage1 import job, study, submit
from sqlalchemy import text

from physicsai_core.db.repositories import train as train_repo
from physicsai_core.sampling import registry
from physicsai_core.stage1_train_data import doe_platform
from physicsai_test_support import API, H

PW, P = H("tok-power", write=True), H("tok-power")


def _feat(name, typ, nominal, lo, hi):
    return {"name": name, "type": typ, "body": "A", "nominal": nominal, "unit": "mm", "range": {"min": lo, "max": hi, "ratio": 0.05},
            "group": None, "ref": {"rule": "contact_fixed", "provisional": True, "locked": False}}


FEATURES = [_feat("A_THK_1", "THICKNESS", 10.0, 9.5, 10.5), _feat("B_RIB_H_1", "RIB_HEIGHT", 20.0, 19.0, 21.0),
            _feat("C_HOLE_R_1", "HOLE_RADIUS", 4.0, 3.8, 4.2), _feat("D_POCKET_D_1", "POCKET_DEPTH", 5.0, 4.75, 5.25)]
NAMES = [f["name"] for f in FEATURES]
BOUNDS = {f["name"]: (f["range"]["min"], f["range"]["max"]) for f in FEATURES}


def _ready(c, w, ai: Path, name: str, monkeypatch):
    """①-1 Native 추출(사용 파라미터 4개) → (study id, 프로젝트 폴더)."""
    monkeypatch.setenv("FAKE_PAICAD_FEATURES", json.dumps(FEATURES))
    sid = study(c, name)
    proj = make_project(ai / name / "00_inbox")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    return sid, proj


def _post(c, sid, proj, params):
    return c.post(f"{API}/studies/{sid}/jobs", headers=PW,
                  json={"job_type": "TD_DOE_GEN", "params": {"radioss_assem_path": str(proj / "assem"), "multi_execution": 4, **params}})


def _run(c, w, sid, proj, params) -> tuple[dict, dict]:
    r = _post(c, sid, proj, params)
    assert r.status_code == 201, r.text
    assert w.run_once_slot() == "SUCCEEDED", job(c, r.json()["id"])
    return r.json(), job(c, r.json()["id"])


def _matrix_text(ai: Path, name: str, doe_id: str) -> str:
    return (ai / name / "01_train" / "doe" / doe_id / "doe_matrix.csv").read_text(encoding="utf-8")


def _expected_lhs_csv(n: int, seed: int) -> str:
    """lhs 골든 기대값 — 계약(geometry-engine/matrix.py 문서)의 알고리즘을 시험 안에서 독립 구현(파라미터마다 층 순열 → run마다 random())."""
    rng = random.Random(seed)
    cols = {}
    for name in NAMES:
        lo, hi = BOUNDS[name]
        perm = list(range(n))
        rng.shuffle(perm)
        cols[name] = [lo + (perm[i] + rng.random()) / n * (hi - lo) for i in range(n)]
    lines = ["doe_no,run_key," + ",".join(NAMES)]
    for i in range(n):
        lines.append(f"{i + 1},run__{i + 1:05d}," + ",".join(repr(float(cols[nm][i])) for nm in NAMES))
    return "\n".join(lines) + "\n"


def _row(engine, doe_id: str) -> dict:
    with engine.connect() as conn:
        r = conn.execute(text("select doe_type, doe_label, options, sampling, generator, engine, num_runs_requested, run_count"
                              " from train_does where id=:i"), {"i": doe_id}).one()
    return dict(zip(("doe_type", "doe_label", "options", "sampling", "generator", "engine", "num_runs_requested", "run_count"), r))


def test_v_dm_1_native_lhs_golden_unchanged_three_request_shapes(p2_native, engine, monkeypatch):
    """lhs 요청 3모양(num_runs·seed만 / doe_label 포함 옛 모양 / sampling:{kind:lhs}) → 같은 doe_matrix.csv(독립 구현 기대값과 바이트 동일),
    doe_type NATIVE_LHS·options {seed}·sampling null·응답 sampling null — def0517과 같다(DM-C8)."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid, proj = _ready(c, w, ai, "dm1", monkeypatch)
    expect = _expected_lhs_csv(4, 7)
    shapes = [({"num_runs": 4, "seed": 7}, "LHS(Native)"), ({"doe_label": "내 LHS", "num_runs": 4, "seed": 7}, "내 LHS"),
              ({"sampling": {"kind": "lhs", "count": 4, "seed": 7}}, "LHS(Native)"),
              ({"generator": "platform", "sampling": {"kind": "lhs", "count": 4, "seed": 7}}, "LHS(Native)")]
    for params, label in shapes:
        j, jd = _run(c, w, sid, proj, params)
        p = j["params"]
        assert p["engine"] == "native" and p["generator"] == "platform" and p["doe_type"] == "NATIVE_LHS" and p["doe_label"] == label
        assert p["num_runs"] == 4 and p["seed"] == 7 and p["options"] == {} and "sampling" not in p, params
        doe_id = jd["result"]["doe_id"]
        assert _matrix_text(ai, "dm1", doe_id) == expect, params
        row = _row(engine, doe_id)
        assert row == {"doe_type": "NATIVE_LHS", "doe_label": label, "options": {"seed": 7}, "sampling": None, "generator": "PLATFORM",
                       "engine": "native", "num_runs_requested": 4, "run_count": 4}, params
        d = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
        assert d["sampling"] is None and d["gen"] is None and d["generator"] == "platform" and d["options"] == {"seed": 7}
    # 첫 행 고정 기대값(리터럴) — 알고리즘 변경 감지
    first = expect.splitlines()[1].split(",")
    assert first[:2] == ["1", "run__00001"] and len(first) == 2 + len(NAMES)
    # lhs 상한은 기존 train_data.max_runs(2000) 유지: 501도 받는다(플랫폼 상한 500 아님)
    assert _post(c, sid, proj, {"num_runs": 501, "seed": 1}).status_code in (201, 409)


def test_v_dm_1_native_lhs_max_runs_unchanged_2000(p2_native, monkeypatch):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid, proj = _ready(c, w, ai, "dm1b", monkeypatch)
    r = _post(c, sid, proj, {"sampling": {"kind": "lhs", "count": 2001, "seed": 1}})
    assert r.status_code == 422, r.text
    r = _post(c, sid, proj, {"num_runs": 2001, "seed": 1})
    assert r.status_code == 422 and "2~2000" in json.dumps(r.json(), ensure_ascii=False), r.text
    r = _post(c, sid, proj, {"sampling": {"kind": "lhs", "count": 1, "seed": 1}})
    assert r.status_code == 422, r.text


INPUTS = {"lhs_opt": {"count": 6, "seed": 3}, "sobol": {"count": 8, "seed": 4}, "halton": {"count": 7, "seed": 5},
          "random": {"count": 5, "seed": 6}, "fullfact": {"levels": {"A_THK_1": 3}}, "fracfact": {"resolution": 5}, "pb": {},
          "bbd": {}, "ccd": {"alpha": "inscribed"}}
EXPECT_RUNS = {"lhs_opt": 6, "sobol": 8, "halton": 7, "random": 5, "fullfact": 24, "fracfact": 16, "pb": 8, "bbd": 25, "ccd": 25}


@pytest.mark.parametrize("kind", list(INPUTS))
def test_v_dm_2_native_single_kind_matches_platform_build(p2_native, engine, monkeypatch, kind):
    """DM-C2: lhs 밖 9종 — 워커 doe_matrix.csv 행 = 같은 입력의 `doe_platform.build` 반영값 행, API check run 수 = 워커 행 수,
    train_does.options·sampling.input/meta 기록, 응답 sampling{kind,label,desc_id,meta}."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid, proj = _ready(c, w, ai, "dm2", monkeypatch)
    sampling = {"kind": kind, **INPUTS[kind]}
    j, jd = _run(c, w, sid, proj, {"sampling": sampling})
    doe_type, label, _desc = registry.METHODS[kind]
    p = j["params"]
    assert p["engine"] == "native" and p["generator"] == "platform" and p["doe_type"] == doe_type and p["doe_label"] == f"{label}(Native)"
    assert p["on_run_failure"] == "continue" and p["options"] == {}
    has_seed = kind in ("lhs_opt", "sobol", "halton", "random")
    assert ("seed" in p) is has_seed and p["sampling"]["kind"] == kind
    doe_id = jd["result"]["doe_id"]
    with engine.connect() as conn:
        setup = train_repo.get_setup(conn, sid)
    plan = doe_platform.build(sampling, {}, lc.settings, inputs=doe_platform.design_inputs_native(setup))
    assert plan.ok and plan.run_count == EXPECT_RUNS[kind] == p["num_runs"], plan.problems         # API check run 수 = 워커 행 수
    rows = list(csv.DictReader(_matrix_text(ai, "dm2", doe_id).splitlines()))
    assert len(rows) == p["num_runs"] == jd["result"]["run_count"]
    assert [r["run_key"] for r in rows] == [r.run_key for r in plan.rows]
    names = [n for n in NAMES]
    got = [[float(r[n]) for n in names] for r in rows]
    exp = [[r.applied_values[n] for n in names] for r in plan.rows]
    assert got == exp
    row = _row(engine, doe_id)
    inp = plan.stored_input()
    assert row["doe_type"] == doe_type and row["options"] == inp and row["generator"] == "PLATFORM" and row["engine"] == "native"
    assert row["sampling"] == {"kind": kind, "input": inp, "meta": plan.meta} and row["sampling"]["meta"], kind
    assert row["num_runs_requested"] == plan.run_count == row["run_count"]
    if has_seed:
        assert inp["seed"] == INPUTS[kind]["seed"]
    d = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert d["generator"] == "platform" and d["engine"] == "native" and d["gen"] is None and d["doe_type"] == doe_type
    assert d["sampling"] == {"kind": kind, "label": label, "desc_id": f"td_{kind}", "meta": plan.meta}
    # 같은 입력이면 같은 행(결정적) — 두 번째 생성
    j2, jd2 = _run(c, w, sid, proj, {"sampling": sampling})
    assert _matrix_text(ai, "dm2", jd2["result"]["doe_id"]) == _matrix_text(ai, "dm2", doe_id)
    # 샘플 표(paramitem 호환)는 반영값 행과 같다
    sm = c.get(f"{API}/train-does/{doe_id}/samples", headers=P).json()
    assert {r["run_key"]: r["values"]["A_THK_1"] for r in sm["rows"]} == {r["run_key"]: float(r["A_THK_1"]) for r in rows}


def test_v_dm_2_native_single_validation_and_forbidden_keys(p2_native, monkeypatch):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid, proj = _ready(c, w, ai, "dm2v", monkeypatch)

    def problems(sampling, status=422):
        r = _post(c, sid, proj, {"sampling": sampling})
        assert r.status_code == status, r.text
        return r.json()["detail"]

    d = problems({"kind": "sobol", "count": 6})
    assert d["code"] == "DOE_SAMPLING_INVALID" and [x["code"] for x in d["problems"]] == ["COUNT_NOT_POW2"]
    d = problems({"kind": "halton", "count": 501})                                      # 그 밖 방식 상한 = platform_max_runs(500)
    assert d["problems"] == [{"code": "TOO_MANY_ROWS", "message": "조합 수는 최대 500개입니다"}]
    d = problems({"kind": "random", "count": 501})
    assert d["problems"][0]["code"] == "TOO_MANY_ROWS"
    d = problems({"kind": "fullfact", "levels": {"A_THK_1": 10, "B_RIB_H_1": 10, "C_HOLE_R_1": 10}})
    assert d["problems"][0]["code"] == "TOO_MANY_ROWS"
    assert problems({"kind": "halton", "count": 1})["code"] in ("INVALID_PARAMS", "DOE_SAMPLING_INVALID")
    for bad in ({"kind": "halton", "count": 4, "seed": 4294967296}, {"kind": "halton", "count": 4, "levels": {}}, {"kind": "random"},
                {"kind": "random", "count": 4, "seed": -1}, {"kind": "table"}, {"kind": "bbd", "count": 4}):
        assert problems(bad)["code"] == "INVALID_PARAMS", bad
    for extra in ({"num_runs": 4}, {"seed": 3}):                                         # sampling과 옛 입력 동시 금지(lhs와 같은 규칙)
        r = _post(c, sid, proj, {"sampling": {"kind": "halton", "count": 4}, **extra})
        assert r.status_code == 422 and "함께 쓸 수 없습니다" in json.dumps(r.json(), ensure_ascii=False), r.text
    r = _post(c, sid, proj, {"generator": "hyperstudy", "sampling": {"kind": "halton", "count": 4}})
    assert r.status_code == 422, r.text
    r = _post(c, sid, proj, {"sampling": {"kind": "halton", "count": 4}, "multi_execution": 9})
    assert r.status_code == 422, r.text
    r = _post(c, sid, proj, {"sampling": {"kind": "halton", "count": 4, "seed": 2}, "doe_label": "H4", "on_run_failure": "fail"})
    assert r.status_code == 201, r.text
    assert r.json()["params"]["doe_label"] == "H4" and r.json()["params"]["on_run_failure"] == "fail"
    assert w.run_once_slot() == "SUCCEEDED"
    # BBD는 변수 3개 이상 — ①-2에서 사용 변수를 2개로 줄이면 DESIGN_UNSUPPORTED
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    body = {"version": ts["version"], "parameters": [{"name": x["name"], "min": x["min"], "max": x["max"], "use": x["name"] in NAMES[:2],
                                                     "format": x["format"], "unit": x["unit"]} for x in ts["parameters"]]}
    assert c.put(f"{API}/studies/{sid}/train/params", headers=PW, json=body).status_code == 200
    d = problems({"kind": "bbd"})
    assert d["problems"][0]["code"] == "DESIGN_UNSUPPORTED" and "3개 이상" in d["problems"][0]["message"]


CSV_OK = "C_HOLE_R_1,A_THK_1,D_POCKET_D_1,B_RIB_H_1\n4.0,9.6,5.0,19.5\n4.1,10.4,5.2,20.5\n3.9,10.0,4.8,20.0\n"


def test_v_dm_5_native_table_rows_and_range_block(p2_native, engine, monkeypatch):
    """① table(Native): 머리줄 순서 무관, 값이 ①-2 학습 범위 밖이면 422 TABLE_OUT_OF_RANGE. DB에는 본문 대신 행 수, 본문은 작업 params에만."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid, proj = _ready(c, w, ai, "dm5", monkeypatch)

    def post(t):
        return _post(c, sid, proj, {"sampling": {"kind": "table", "text": t}})

    for text_, code in ((CSV_OK.replace("9.6", "9.0"), "TABLE_OUT_OF_RANGE"), ("A_THK_1,B_RIB_H_1\n10,20\n10,20\n", "TABLE_HEADER"),
                        ("A_THK_1,B_RIB_H_1,C_HOLE_R_1,D_POCKET_D_1\n10,20,4,5\n", "TOO_FEW_ROWS"),
                        ("A_THK_1,B_RIB_H_1,C_HOLE_R_1,D_POCKET_D_1\n10,20,4,x\n10,20,4,5\n", "TABLE_VALUE")):
        r = post(text_)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "DOE_SAMPLING_INVALID", r.text
        assert r.json()["detail"]["problems"][0]["code"] == code, r.text
    r = post(CSV_OK.replace("9.6", "9.0"))
    assert r.json()["detail"]["problems"][0]["message"] == "'A_THK_1' 값 9가 학습 범위 9.5~10.5 밖입니다"
    r = post(CSV_OK)
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["doe_type"] == "TABLE" and p["doe_label"] == "표 붙여넣기 / CSV(Native)" and p["num_runs"] == 3 and "seed" not in p
    assert p["sampling"] == {"kind": "table", "text": CSV_OK}                             # 본문은 작업 params에만
    assert w.run_once_slot() == "SUCCEEDED", job(c, r.json()["id"])
    doe_id = job(c, r.json()["id"])["result"]["doe_id"]
    row = _row(engine, doe_id)
    assert row["options"] == {"row_count": 3} and row["sampling"] == {"kind": "table", "input": {"row_count": 3}, "meta": {"row_count": 3}}
    assert "9.6" not in json.dumps(row["options"]) and "text" not in row["sampling"]["input"]
    rows = list(csv.DictReader(_matrix_text(ai, "dm5", doe_id).splitlines()))
    assert [(r["A_THK_1"], r["B_RIB_H_1"], r["C_HOLE_R_1"], r["D_POCKET_D_1"]) for r in rows] == \
        [("9.6", "19.5", "4.0", "5.0"), ("10.4", "20.5", "4.1", "5.2"), ("10.0", "20.0", "3.9", "4.8")]
    d = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert d["options"] == {"row_count": 3} and d["sampling"]["kind"] == "table" and d["sampling"]["desc_id"] == "td_table"
    assert d["sampling"]["label"] == "표 붙여넣기 / CSV" and d["gen"] is None
