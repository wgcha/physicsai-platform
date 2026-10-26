"""doe-preview.md ①-1 Native 추출 기준(출처 train·train_doe) — V-DP-3(표본 행렬 바이트 동일)·V-DP-5(셀 FAIL·ERROR 처리, 플랫폼 쪽)·V-DP-7(작업·CPU 대기열·
청크 등록·취소)·V-DP-8(캐시·중복·취소·권한)·V-DP-9(범위 409)·V-DP-12(생성 후 갤러리). 가짜 paicad `view grid`."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest
from helpers_native import make_project
from helpers_stage1 import job, study, submit
from sqlalchemy import text

from physicsai_core.geometry import doe_preview as dp
from physicsai_test_support import API, H, read_record
from support_resources import _p2_env

PW, P = H("tok-power", write=True), H("tok-power")
PW2 = H("tok-power2", write=True)
GENERAL, ADMIN = H("tok-general", write=True), H("tok-admin", write=True)


def _feat(name, typ, nominal, lo, hi):
    return {"name": name, "type": typ, "body": "A", "nominal": nominal, "unit": "mm", "range": {"min": lo, "max": hi, "ratio": 0.05},
            "group": None, "ref": {"rule": "contact_fixed", "provisional": True, "locked": False}}


FEATURES = [_feat("A_THK_1", "THICKNESS", 10.0, 9.5, 10.5), _feat("B_RIB_H_1", "RIB_HEIGHT", 20.0, 19.0, 21.0),
            _feat("C_HOLE_R_1", "HOLE_RADIUS", 4.0, 3.8, 4.2), _feat("D_POCKET_D_1", "POCKET_DEPTH", 5.0, 4.75, 5.25)]
NAMES = [f["name"] for f in FEATURES]
LHS40 = {"kind": "lhs", "count": 40, "seed": 5}


@pytest.fixture()
def dp_env(request, tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, fake_record):
    """native 형상 엔진(가짜 paicad) + `doe_preview` 절 덮어쓰기(`@pytest.mark.parametrize("dp_env", [{…}], indirect=True)`)."""
    extra = dict(getattr(request, "param", None) or {})
    over = {"geometry": {"engine": "native", "paicad_path": fake_tools["fake_paicad"], **(extra.pop("geometry", None) or {})}, **extra}
    yield from _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, over)


def _ready(c, w, ai: Path, name: str, monkeypatch, features=FEATURES):
    """①-1 Native 추출(사용 파라미터 4개) + 워커 하트비트(paicad 버전 = 캐시 키) → (study id, 프로젝트 폴더)."""
    monkeypatch.setenv("FAKE_PAICAD_FEATURES", json.dumps(features))
    sid = study(c, name)
    proj = make_project(ai / name / "00_inbox")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    w.heartbeat_once()
    return sid, proj


def _req(sampling=None, **select):
    body: dict = {"source": {"kind": "train"}}
    if sampling is not None:
        body["sampling"] = sampling
    if select:
        body["select"] = select
    return body


def _post(c, sid, body, expect=(200, 202), headers=PW):
    r = c.post(f"{API}/studies/{sid}/doe-previews", headers=headers, json=body)
    assert r.status_code in ((expect,) if isinstance(expect, int) else expect), r.text
    return r


def _get(c, pid) -> dict:
    r = c.get(f"{API}/doe-previews/{pid}", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def _run_preview(c, w, sid, body, expect_state="SUCCEEDED") -> dict:
    p = _post(c, sid, body, expect=202).json()
    assert w.run_once_slot() == expect_state, job(c, p["job_id"])
    return _get(c, p["id"])


def _sql(engine, q: str, **kw):
    with engine.begin() as conn:
        r = conn.execute(text(q), kw)
        return r.fetchall() if r.returns_rows else None


def _matrix_of(ai: Path, name: str, jid: str, c) -> str:
    mkey = job(c, jid)["params"]["matrix_key"]
    return (ai / name / "_cache" / "doe_preview" / "matrix" / mkey[:2] / mkey / "doe_matrix.csv").read_text(encoding="utf-8")


def _doe_gen(c, w, sid, proj, params) -> tuple[str, dict]:
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW,
               json={"job_type": "TD_DOE_GEN", "params": {"radioss_assem_path": str(proj / "assem"), "multi_execution": 4, **params}})
    assert r.status_code == 201, r.text
    assert w.run_once_slot() == "SUCCEEDED", job(c, r.json()["id"])
    return job(c, r.json()["id"])["result"]["doe_id"], r.json()


def _doe_matrix(ai: Path, name: str, doe_id: str) -> str:
    return (ai / name / "01_train" / "doe" / doe_id / "doe_matrix.csv").read_text(encoding="utf-8")


INPUTS = {"lhs": {"count": 9, "seed": 3}, "lhs_opt": {"count": 6, "seed": 3}, "sobol": {"count": 8, "seed": 4}, "halton": {"count": 7, "seed": 5},
          "random": {"count": 5, "seed": 6}, "fullfact": {"levels": {"A_THK_1": 3}}, "fracfact": {"resolution": 5}, "pb": {}, "bbd": {},
          "ccd": {"alpha": "inscribed"}}
CSV_OK = "C_HOLE_R_1,A_THK_1,D_POCKET_D_1,B_RIB_H_1\n4.0,9.6,5.0,19.5\n4.1,10.4,5.2,20.5\n3.9,10.0,4.8,20.0\n"


def test_v_dp_3_train_matrix_bytes_equal_td_doe_gen_every_site_kind(dp_env, monkeypatch):
    """미리보기 행렬(`matrix/<mkey>/doe_matrix.csv`) = 같은 본문의 TD_DOE_GEN DG_PREP `doe_matrix.csv`(바이트 동일) — SITE_KINDS[train_native] 전 kind
    (lhs·lhs seed 0(DG_PREP의 `seed or 1` 규칙까지)·table 포함)."""
    from physicsai_core.sampling import registry

    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, proj = _ready(c, w, ai, "dp3", monkeypatch)
    cases = [({"kind": k, **v}) for k, v in INPUTS.items()] + [{"kind": "lhs", "count": 7, "seed": 0}, {"kind": "table", "text": CSV_OK}]
    assert {x["kind"] for x in cases} == set(registry.SITE_KINDS["train_native"]) - {"train_doe"}  # train_doe는 아래 별도 테스트
    for sampling in cases:
        pv = _run_preview(c, w, sid, _req(sampling))
        assert pv["status"] == "DONE" and pv["n_total"] >= 2, sampling
        got = _matrix_of(ai, "dp3", pv["job_id"], c)
        _doe, _j = _doe_gen(c, w, sid, proj, {"sampling": sampling})
        assert got == _doe_matrix(ai, "dp3", _doe), sampling  # 바이트 동일
        rows = list(csv.DictReader(got.splitlines()))
        assert pv["n_total"] == len(rows) and sorted(pv["order"]) == [int(r["doe_no"]) for r in rows], sampling


def test_v_dp_3_train_doe_reuse_sampling_and_row_values(dp_env, monkeypatch):
    """`sampling.kind == train_doe`(표본표 재사용)도 TD_DOE_GEN과 같은 함수 — 원본 DOE samples 행 그대로, 셀 값 = 행렬 행 값."""
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, proj = _ready(c, w, ai, "dp3r", monkeypatch)
    doe_id, _ = _doe_gen(c, w, sid, proj, {"sampling": {"kind": "lhs", "count": 6, "seed": 2}})
    r = c.get(f"{API}/train-does/{doe_id}/samples", headers=P)
    assert r.status_code == 200 and r.json()["rows"], r.text
    pv = _run_preview(c, w, sid, _req({"kind": "train_doe", "doe_id": doe_id}))
    assert pv["status"] == "DONE" and pv["n_total"] == 6
    rows = {int(x["doe_no"]): {n: float(x[n]) for n in NAMES} for x in csv.DictReader(_matrix_of(ai, "dp3r", pv["job_id"], c).splitlines())}
    for cell in pv["cells"]:
        if not cell["nominal"]:
            assert cell["values"] == rows[cell["doe_no"]]  # 셀 값 = 행렬 행(사용 파라미터 전부)


def test_train_page_flow_sort_orders_cells_and_artifacts(dp_env, engine, monkeypatch, fake_record, tmp_path):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, proj = _ready(c, w, ai, "dp1", monkeypatch)
    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("FAKE_TOOL_TRACE", str(trace))
    monkeypatch.setenv("FAKE_PAICAD_SLEEP_S", "0.4")  # 병렬 겹침 관측
    pv = _run_preview(c, w, sid, _req(LHS40))
    assert pv["status"] == "DONE" and pv["cache_hit"] is False and pv["queue"] is None
    assert pv["n_total"] == 40 and pv["n_ok"] == 24 and pv["n_fail"] == 0 and pv["n_error"] == 0
    assert pv["tag_state"] == "none" and pv["colormap"] == "turbo16" and pv["disp_range_mm"] == [0.0, 1.0]  # 길이 단위 최대 변화(B_RIB_H ±1)
    assert pv["source"] == {"kind": "train", "param_set_id": None, "doe_id": None}
    assert pv["select"] == {"order": "change", "var": None, "desc": False, "offset": 0, "limit": 24}
    cells = pv["cells"]
    assert len(cells) == 24 and cells[0]["nominal"] and cells[0]["doe_no"] is None and cells[0]["top_changes"] == []
    assert cells[0]["values"] == {f["name"]: f["nominal"] for f in FEATURES}
    assert [x["doe_no"] for x in cells[1:]] == pv["order"][:23]  # 변화 큰 순 23개
    rows = {int(x["doe_no"]): {n: float(x[n]) for n in NAMES} for x in csv.DictReader(_matrix_of(ai, "dp1", pv["job_id"], c).splitlines())}
    table = [{"name": f["name"], "nominal": f["nominal"], "min": f["range"]["min"], "max": f["range"]["max"], "unit": "mm"} for f in FEATURES]
    scores = [dp.change_score(rows[n], table) for n in pv["order"]]
    assert scores == sorted(scores, reverse=True) and sorted(pv["order"]) == list(range(1, 41))
    for cell in cells:
        assert cell["status"] == "OK" and cell["png_artifact_id"] and cell["glb_artifact_id"] and cell["manifest_artifact_id"]
        assert cell["max_disp_mm"] is not None and cell["clipped"] is False and cell["gen"] is None
        if not cell["nominal"]:
            assert len(cell["top_changes"]) == 3 and abs(cell["top_changes"][0]["rel"]) >= abs(cell["top_changes"][1]["rel"])
    # 산출물: PNG(image/png), GLB(media), manifest(content)
    png = c.get(f"{API}/artifacts/{cells[1]['png_artifact_id']}/media", headers=P)
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert c.get(f"{API}/artifacts/{cells[1]['glb_artifact_id']}/media", headers=P).content[:4] == b"glTF"
    man = c.get(f"{API}/artifacts/{cells[1]['manifest_artifact_id']}/content", headers=P).json()
    assert man["thumb"]["file"] == "thumb.png" and man["status"] == "OK"
    # view grid 호출: 청크 6개(24셀/4), tag 없음(train) → --tag-dir 쌍 생략, --threads 1, cells·thumb 옵션·out-dir은 작업 폴더
    calls = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1:3] == ["view", "grid"]]
    assert len(calls) == 6
    jdir = ai / "dp1" / "_cache" / "doe_preview" / "jobs" / pv["job_id"]
    for a in calls:
        assert "--tag-dir" not in a and "--fixed-dir" not in a and a[a.index("--threads") + 1] == "1"
        assert Path(a[a.index("--cells") + 1]).parent == jdir and a[a.index("--thumb-options") + 1] == str(jdir / "thumb_options.json")
        assert Path(a[a.index("--out-dir") + 1]).parent == jdir and a[a.index("--view-options") + 1] == str(jdir / "view_options.json")
        assert a[a.index("--features") + 1].endswith("parameter_features.json") and a[a.index("--cad") + 1].endswith("bracket.step")
    topts = json.loads((jdir / "thumb_options.json").read_text())
    assert topts == {"schema_version": 1, "w": 320, "h": 240, "view_dir": [1.0, -1.0, 1.0], "margin": 1.15, "disp_range_mm": [0.0, 1.0],
                     "colormap": "turbo16", "nominal_ghost": True, "edges": False}
    sizes = [len(json.loads(Path(a[a.index("--cells") + 1]).read_text())["cells"]) for a in calls]
    assert sorted(sizes) == [4, 4, 4, 4, 4, 4]
    ev = [json.loads(x) for x in trace.read_text().splitlines()]
    live, peak = 0, 0
    for e in sorted((e for e in ev if e["tool"] == "paicad" and e["ev"] in ("start", "end")), key=lambda e: e["t"]):
        live += 1 if e["ev"] == "start" else -1
        peak = max(peak, live)
    assert peak == 2  # parallel 2(CPU 슬롯 1개 안의 동시 프로세스)
    # 셀 캐시 폴더·인덱스 행(DONE 24개)·썸네일 산출물 kind
    done = _sql(engine, "select count(*) from doe_preview_cells where status='DONE'")
    assert done[0][0] == 24
    kinds = {r[0] for r in _sql(engine, "select distinct kind from artifacts where job_id=:j", j=pv["job_id"])}
    assert kinds == {"GEOM_THUMB_PNG", "GEOM_PREVIEW_GLB", "GEOM_PREVIEW_MANIFEST"}
    keyrows = _sql(engine, "select cache_key from doe_preview_cells")
    for (k,) in keyrows:
        assert (ai / "dp1" / "_cache" / "doe_preview" / "cells" / k[:2] / k / "thumb.png").is_file()
    # 다음 24개: offset 24 = 표본 17개(공칭 없음), 두 페이지의 표본이 겹치지 않고 합치면 전부
    p2 = _run_preview(c, w, sid, _req(LHS40, offset=24))
    assert p2["status"] == "DONE" and [x["nominal"] for x in p2["cells"]] == [False] * 17 and p2["order"] == pv["order"]
    assert [x["doe_no"] for x in p2["cells"]] == pv["order"][23:]
    assert sorted([x["doe_no"] for x in cells[1:]] + [x["doe_no"] for x in p2["cells"]]) == list(range(1, 41))
    # DOE 순서·변수 정렬(오름·내림)
    p3 = _run_preview(c, w, sid, _req(LHS40, order="doe"))
    assert [x["doe_no"] for x in p3["cells"]] == [None, *range(1, 24)] and p3["order"] == list(range(1, 41))
    p4 = _run_preview(c, w, sid, _req(LHS40, order="var", var="B_RIB_H_1", desc=True))
    vals = [x["values"]["B_RIB_H_1"] for x in p4["cells"][1:]]
    assert vals == sorted(vals, reverse=True)
    p5 = _run_preview(c, w, sid, _req(LHS40, order="var", var="B_RIB_H_1"))
    vals = [x["values"]["B_RIB_H_1"] for x in p5["cells"][1:]]
    assert vals == sorted(vals)
    # 정렬·페이지가 바뀌어도 같은 표본은 같은 셀 키 → 새로 그리지 않는다(셀 캐시 공유)
    r3 = job(c, p3["job_id"])["result"]
    assert r3["cached"] >= 1 and r3["to_render"] == r3["page_cells"] - r3["cached"] and r3["to_render"] < r3["page_cells"]
    assert cells[0]["png_artifact_id"] == p3["cells"][0]["png_artifact_id"]  # 공칭 셀은 하나



SMALL = {"kind": "lhs", "count": 8, "seed": 7}  # 공칭 + 8 = 셀 9개 → 청크 3개(4·4·1)


def _rows(ai, name, pv, c):
    return {int(x["doe_no"]): {n: float(x[n]) for n in NAMES} for x in csv.DictReader(_matrix_of(ai, name, pv["job_id"], c).splitlines())}


def test_dedupe_cache_hit_and_newer_request_cancels_queued(dp_env, engine, monkeypatch):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, _ = _ready(c, w, ai, "dpd", monkeypatch)
    a = _post(c, sid, _req(SMALL), expect=202).json()
    assert a["status"] == "QUEUED" and a["queue"]["lane"] == "CPU" and a["queue"]["position"] == 1 and a["cells"] == [] and a["cache_hit"] is False
    b = _post(c, sid, _req(SMALL), expect=202).json()  # 같은 요청(grid_key) → 진행 중인 것 그대로
    assert b["id"] == a["id"] and b["job_id"] == a["job_id"]
    assert _sql(engine, "select count(*) from jobs where job_type='DOE_PREVIEW'")[0][0] == 1
    # 같은 출처의 다른 페이지 요청 → 이전 QUEUED는 취소(최신 우선)
    n = _post(c, sid, _req(SMALL, order="doe"), expect=202).json()
    assert n["id"] != a["id"]
    assert _get(c, a["id"])["status"] == "CANCELED" and job(c, a["job_id"])["state"] == "CANCELED"
    assert w.run_once_slot() == "SUCCEEDED" and _get(c, n["id"])["status"] == "DONE"
    # 완료 후 같은 요청 → 200 cache_hit, 새 작업 없음, 셀 전부 OK
    jobs_before = _sql(engine, "select count(*) from jobs where job_type='DOE_PREVIEW'")[0][0]
    h = _post(c, sid, _req(SMALL, order="doe"), expect=200).json()
    assert h["cache_hit"] is True and h["status"] == "DONE" and h["id"] == n["id"] and h["job_id"] == n["job_id"]
    assert len(h["cells"]) == 9 and all(x["status"] == "OK" for x in h["cells"])
    assert _sql(engine, "select count(*) from jobs where job_type='DOE_PREVIEW'")[0][0] == jobs_before
    # 캐시 파일이 지워지면 cache_hit이 아니라 새 작업
    k = _sql(engine, "select cache_key from doe_preview_cells limit 1")[0][0]
    (ai / "dpd" / "_cache" / "doe_preview" / "cells" / k[:2] / k / "thumb.png").unlink()
    again = _post(c, sid, _req(SMALL, order="doe"), expect=202).json()
    assert again["id"] != n["id"] and again["cache_hit"] is False
    assert w.run_once_slot() == "SUCCEEDED"
    d = _get(c, again["id"])
    assert d["status"] == "DONE" and job(c, again["job_id"])["result"]["to_render"] == 1  # 지워진 셀 1개만 다시 그린다


def test_cancel_permissions_audit_and_terminal(dp_env, engine, monkeypatch):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, _ = _ready(c, w, ai, "dpc", monkeypatch)
    a = _post(c, sid, _req(SMALL), expect=202).json()
    cancel = f"{API}/doe-previews/{a['id']}/cancel"
    assert c.post(cancel, headers=GENERAL).status_code == 403  # 일반 사용자(power 아님)
    assert c.post(cancel, headers=PW2).status_code == 403  # 다른 power 사용자
    assert c.get(f"{API}/doe-previews/{a['id']}", headers=P).status_code == 200
    r = c.post(cancel, headers=ADMIN)
    assert r.status_code == 202 and r.json()["status"] == "CANCELED", r.text
    assert c.post(cancel, headers=PW).status_code == 409 and c.post(cancel, headers=PW).json()["detail"]["code"] == "JOB_TERMINAL"
    assert c.post(f"{API}/doe-previews/{'0' * 8}-0000-0000-0000-000000000000/cancel", headers=PW).status_code == 404
    acts = [r[0] for r in _sql(engine, "select action from audit_events where action like 'DOE_PREVIEW_%' order by occurred_at, action desc")]
    assert acts == ["DOE_PREVIEW_CREATE", "DOE_PREVIEW_CANCEL"]
    # 요청자 본인 취소 + 비멤버는 만들 수 없음
    b = _post(c, sid, _req(SMALL, order="doe"), expect=202).json()
    assert c.post(f"{API}/doe-previews/{b['id']}/cancel", headers=PW).status_code == 202
    assert c.post(f"{API}/studies/{sid}/doe-previews", headers=H("tok-nonmember", write=True), json=_req(SMALL)).status_code in (403, 404)
    assert c.post(f"{API}/studies/{sid}/doe-previews", headers=GENERAL, json=_req(SMALL)).status_code == 403


def test_cpu_queue_counts_and_busy_429(dp_env, engine, monkeypatch):
    """DOE_PREVIEW는 CPU 대기열(슬롯 1개를 점유하는 다른 작업 뒤에 줄을 선다). 사용자별 대기+실행 상한 초과 → 429 PREVIEW_BUSY."""
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, _ = _ready(c, w, ai, "dpq", monkeypatch)
    a = _post(c, sid, _req(SMALL), expect=202).json()
    b = _post(c, sid, _req(SMALL, order="var", var="B_RIB_H_1"), expect=202).json()  # 같은 출처의 이전 QUEUED(a)는 취소
    assert _get(c, a["id"])["status"] == "CANCELED" and _get(c, b["id"])["queue"]["position"] == 1
    # 다른 출처(param_set은 없으니 train 다른 sampling = 같은 출처 취소 대상) → 상한은 QUEUED+RUNNING 합 기준이라 다른 사용자로 확인
    other = _post(c, sid, _req(SMALL, order="doe"), headers=PW2, expect=202).json()
    assert other["queue"]["position"] == 2
    assert _get(c, b["id"])["queue"]["position"] == 1
    assert w.run_once_slot() == "SUCCEEDED" and _get(c, b["id"])["status"] == "DONE"
    assert _get(c, other["id"])["queue"]["position"] == 1


@pytest.mark.parametrize("dp_env", [{"doe_preview": {"max_active_per_user": 1}}], indirect=True)
def test_per_user_active_limit_429_and_other_user_ok(dp_env, engine, monkeypatch):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    s1, _ = _ready(c, w, ai, "dpb1", monkeypatch)
    s2, _ = _ready(c, w, ai, "dpb2", monkeypatch)
    a = _post(c, s1, _req(SMALL), expect=202).json()
    r = c.post(f"{API}/studies/{s2}/doe-previews", headers=PW, json=_req(SMALL))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "PREVIEW_BUSY" and r.json()["detail"]["limit"] == 1, r.text
    assert _sql(engine, "select count(*) from doe_previews")[0][0] == 1  # 거부된 요청은 행·작업을 만들지 않는다
    assert _post(c, s2, _req(SMALL), headers=PW2, expect=202).status_code == 202  # 다른 사용자는 각자 상한
    assert w.run_once_slot() == "SUCCEEDED" and _get(c, a["id"])["status"] == "DONE"
    assert _post(c, s2, _req(SMALL, order="doe"), expect=(200, 202)).status_code in (200, 202)  # 끝나면 다시 가능


def test_fail_and_error_cells_partial_warning_and_rerender_only_errors(dp_env, monkeypatch):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, _ = _ready(c, w, ai, "dpf", monkeypatch)
    # FAIL(형상 실패)은 캐시되는 결과, ERROR(VIEW_*·셀 폴더 없음)는 캐시 안 함
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", "view_grid:GEOM_TOPOLOGY_CHANGED:A_THK_1<9.7")
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "view_grid_cell:1:VIEW_TESSELLATION_FAILED")  # 청크마다 둘째 셀(청크 0·1만 해당)
    body = _req(SMALL, order="doe")
    pv = _run_preview(c, w, sid, body)
    rows = _rows(ai, "dpf", pv, c)
    cells = pv["cells"]
    assert [x["doe_no"] for x in cells] == [None, *range(1, 9)]
    err_pos = {1, 5}  # 청크 [0..3]·[4..7]의 둘째 셀 = 위치 1·5(doe_no 1·5)
    for pos, cell in enumerate(cells):
        low = cell["doe_no"] is not None and rows[cell["doe_no"]]["A_THK_1"] < 9.7
        if pos in err_pos:
            assert cell["status"] == "ERROR" and cell["code"] == "VIEW_TESSELLATION_FAILED" and cell["png_artifact_id"] is None, cell
        elif low:
            assert cell["status"] == "FAIL" and cell["code"] == "GEOM_TOPOLOGY_CHANGED" and cell["category"] == "CAD_FAILED"
            assert cell["message_ko"] and cell["png_artifact_id"] and cell["glb_artifact_id"] is None and cell["max_disp_mm"] is None
        else:
            assert cell["status"] == "OK" and cell["glb_artifact_id"]
    n_fail = sum(1 for x in cells if x["status"] == "FAIL")
    low = {n for n in (1, 5) if rows[n]["A_THK_1"] < 9.7}
    assert pv["n_error"] == 2 and pv["n_fail"] == n_fail and pv["n_ok"] == 9 - 2 - n_fail
    assert [x["code"] for x in pv["warnings"]] == ["DOE_PREVIEW_PARTIAL"]
    assert job(c, pv["job_id"])["state"] == "SUCCEEDED"
    # 다시 요청: ERROR였던 셀 2개만 그린다(OK·FAIL은 캐시), 이번엔 정상이라 경고 없음
    monkeypatch.delenv("FAKE_PAICAD_FAIL")
    monkeypatch.delenv("FAKE_PAICAD_FAIL_WHEN")
    p2 = _run_preview(c, w, sid, body)
    r2 = job(c, p2["job_id"])["result"]
    assert r2["to_render"] == 2 and r2["cached"] == 7 and p2["n_error"] == 0 and p2["warnings"] == []
    assert p2["n_fail"] == n_fail and p2["n_ok"] == 9 - n_fail  # FAIL은 캐시된 결과 그대로, ERROR였던 2개는 이번에 OK
    assert [x["status"] for x in p2["cells"] if x["doe_no"] in (1, 5) and x["doe_no"] not in low] == ["OK"] * len([1 for n in (1, 5) if n not in low])


def test_all_cells_error_job_failed_and_chunk_timeout(dp_env, monkeypatch):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, _ = _ready(c, w, ai, "dpe", monkeypatch)
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "view_grid:GEOM_INPUT_INVALID")  # 명령 전체 실패(grid_manifest 없음, 종료코드만) → 모든 셀 ERROR
    pv = _run_preview(c, w, sid, _req(SMALL), expect_state="FAILED")
    assert pv["status"] == "FAILED" and pv["code"] == "EXIT_NONZERO" and pv["message_ko"] and pv["n_ok"] == 0 and pv["n_error"] == 9
    assert all(x["status"] == "ERROR" and x["code"] == "EXIT_NONZERO" for x in pv["cells"])
    monkeypatch.delenv("FAKE_PAICAD_FAIL")
    ok = _run_preview(c, w, sid, _req(SMALL))  # 실패 뒤 같은 요청 = 새 작업, 정상 완료
    assert ok["status"] == "DONE" and ok["id"] != pv["id"] and ok["n_error"] == 0
    # 보고 없이 종료코드 1(grid_manifest 없음)도 같은 처리
    monkeypatch.setenv("FAKE_PAICAD_NOREPORT", "view_grid")
    nr = _run_preview(c, w, sid, _req({**SMALL, "seed": 8}))  # 새 표본 8개는 오류, 캐시된 공칭 셀 1개는 OK → 일부 오류(작업 성공 + 경고)
    assert nr["status"] == "DONE" and nr["n_error"] == 8 and nr["n_ok"] == 1 and [x["code"] for x in nr["warnings"]] == ["DOE_PREVIEW_PARTIAL"]


@pytest.mark.parametrize("dp_env", [{"doe_preview": {"timeout_s_per_cell": 0.2, "chunk_cells": 2}}], indirect=True)
def test_chunk_timeout_marks_cells_error(dp_env, monkeypatch):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, _ = _ready(c, w, ai, "dpt", monkeypatch)
    monkeypatch.setenv("FAKE_PAICAD_SLEEP_S", "5")  # 청크 한도 2 × 0.2s = 0.4s 초과
    pv = _run_preview(c, w, sid, _req(SMALL), expect_state="FAILED")
    assert pv["status"] == "FAILED" and pv["n_error"] == 9 and pv["code"]
    codes = set(job(c, pv["job_id"])["result"]["cell_errors"].values())
    assert len(codes) == 1 and "TIMEOUT" in next(iter(codes)).upper()


@pytest.mark.parametrize("dp_env", [{"doe_preview": {"parallel": 1}}], indirect=True)
def test_chunk_registration_and_cancel_keeps_finished_cells(dp_env, engine, monkeypatch):
    """청크가 끝날 때마다 셀을 캐시·산출물·DB에 등록(폴링이 바로 채움). 취소해도 끝난 청크 셀은 남고, 다시 요청하면 나머지만 그린다."""
    from physicsai_worker.steps import doe_preview as wdp

    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, _ = _ready(c, w, ai, "dpx", monkeypatch)
    p = _post(c, sid, _req(SMALL, order="doe"), expect=202).json()
    real, seen = wdp.run_paicad, {"n": 0, "mid": None}

    def wrapped(*a, **kw):
        v = real(*a, **kw)
        seen["n"] += 1
        if seen["n"] == 1:
            seen["mid"] = _sql(engine, "select count(*) from doe_preview_cells where status='DONE'")[0][0]  # 아직 청크 등록 전
            assert c.post(f"{API}/doe-previews/{p['id']}/cancel", headers=PW).status_code == 202
        return v

    monkeypatch.setattr(wdp, "run_paicad", wrapped)
    assert w.run_once_slot() == "CANCELED", job(c, p["job_id"])
    monkeypatch.setattr(wdp, "run_paicad", real)
    assert seen["n"] == 1  # 취소 뒤 다음 청크는 시작하지 않는다
    pv = _get(c, p["id"])
    assert pv["status"] == "CANCELED" and [x["status"] for x in pv["cells"]] == ["OK"] * 4 + ["PENDING"] * 5
    assert _sql(engine, "select count(*) from doe_preview_cells where status='DONE'")[0][0] == 4
    p2 = _run_preview(c, w, sid, _req(SMALL, order="doe"))
    r2 = job(c, p2["job_id"])["result"]
    assert p2["status"] == "DONE" and r2["cached"] == 4 and r2["to_render"] == 5 and all(x["status"] == "OK" for x in p2["cells"])


def test_train_doe_gallery_with_skipped_badges(dp_env, engine, monkeypatch):
    """V-DP-12: 생성이 끝난 DOE의 갤러리 — 표본 표는 D/doe_matrix.csv 그대로, 실제 생성 결과(SKIPPED.json)가 셀 `gen`에 붙는다."""
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, proj = _ready(c, w, ai, "dpg", monkeypatch)
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", "check:GEOM_QUALITY:A_THK_1>10.0")
    doe_id, jd = _doe_gen(c, w, sid, proj, {"sampling": {"kind": "lhs", "count": 6, "seed": 2}})
    monkeypatch.delenv("FAKE_PAICAD_FAIL_WHEN")
    res = job(c, jd["id"])["result"]
    skipped = {s["run_key"]: s for s in res["skipped_runs"]}
    assert skipped and len(skipped) < 6
    pv = _run_preview(c, w, sid, {"source": {"kind": "train_doe", "doe_id": doe_id}, "select": {"order": "doe"}})
    assert pv["status"] == "DONE" and pv["source"] == {"kind": "train_doe", "param_set_id": None, "doe_id": doe_id}
    assert pv["n_total"] == 6 and [x["doe_no"] for x in pv["cells"]] == [None, 1, 2, 3, 4, 5, 6]
    D = _doe_matrix(ai, "dpg", doe_id)
    assert _matrix_of(ai, "dpg", pv["job_id"], c) == D  # 행렬은 원본 DOE 파일 그대로(바이트 동일)
    gens = [x["gen"] for x in pv["cells"][1:]]
    sk = [g for g in gens if g["status"] == "SKIPPED"]
    assert len(sk) == len(skipped) and all(g["code"] == "GEOM_QUALITY" and g["step"] == "check" for g in sk)
    assert all(g["status"] in ("SKIPPED", "OK") for g in gens) and pv["cells"][0]["gen"] is None
    # 스킵된 표본도 형상 셀은 그린다(상태는 렌더 결과 — 생성 결과와 별개), 셀 값은 DOE 표의 값
    rows = {int(x["doe_no"]): x for x in csv.DictReader(D.splitlines())}
    for cell in pv["cells"][1:]:
        assert cell["status"] == "OK" and cell["values"]["A_THK_1"] == pytest.approx(float(rows[cell["doe_no"]]["A_THK_1"]))
    # 같은 요청 → cache_hit
    assert _post(c, sid, {"source": {"kind": "train_doe", "doe_id": doe_id}, "select": {"order": "doe"}}, expect=200).json()["cache_hit"] is True
    # DOE가 READY가 아니거나 없으면 409/404
    r = c.post(f"{API}/studies/{sid}/doe-previews", headers=PW, json={"source": {"kind": "train_doe", "doe_id": "nope"}})
    assert r.status_code == 404
    r = c.post(f"{API}/studies/{sid}/doe-previews", headers=PW, json={"source": {"kind": "train_doe"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"


def test_scope_and_validation_errors(dp_env, engine, monkeypatch):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid0 = study(c, "dpv0")  # ①-1 없음
    url0 = f"{API}/studies/{sid0}/doe-previews"
    r = c.post(url0, headers=PW, json=_req(SMALL))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREREQUISITE_MISSING"
    sid, _ = _ready(c, w, ai, "dpv", monkeypatch)
    url = f"{API}/studies/{sid}/doe-previews"

    def bad(body, code, status=422, headers=PW):
        r = c.post(url, headers=headers, json=body)
        assert r.status_code == status and r.json()["detail"]["code"] == code, (body, r.text)
        return r.json()["detail"]

    bad(_req(None), "INVALID_PARAMS")  # sampling 없음
    bad(_req({"kind": "lhs", "count": 1, "seed": 1}), "INVALID_PARAMS")  # 표본 수 범위
    bad(_req({"kind": "bogus"}), "INVALID_PARAMS")
    bad(_req(SMALL, offset=5), "INVALID_PARAMS")  # page_size 배수 아님
    bad(_req(SMALL, limit=49), "INVALID_PARAMS")  # max_page_size 초과
    bad(_req(SMALL, order="var"), "INVALID_PARAMS")  # var 필요
    bad(_req(SMALL, order="var", var="NOPE"), "INVALID_PARAMS")  # 모르는 변수
    bad({"source": {"kind": "param_set"}, "sampling": SMALL}, "INVALID_PARAMS")  # param_set_id 필요
    bad({"source": {"kind": "param_set", "param_set_id": "nope"}, "sampling": SMALL}, "PREREQUISITE_MISSING", 409)
    assert c.post(url, headers=GENERAL, json=_req(SMALL)).status_code == 403  # power 필요
    assert c.post(f"{API}/studies/00000000-0000-0000-0000-000000000000/doe-previews", headers=PW, json=_req(SMALL)).status_code == 404
    assert c.post(url, headers={}, json=_req(SMALL)).status_code in (401, 403)
    assert _sql(engine, "select count(*) from doe_previews")[0][0] == 0  # 거부된 요청은 행·작업을 만들지 않는다
    assert _sql(engine, "select count(*) from jobs where job_type='DOE_PREVIEW'")[0][0] == 0
    # 쉘(①-1 기반)·Altair 설정은 409 DOE_PREVIEW_UNSUPPORTED
    _sql(engine, "update train_setups set features_rel = replace(features_rel, 'parameter_features.json', 'shell_features.json') where study_id=:s", s=sid)
    d = bad(_req(SMALL), "DOE_PREVIEW_UNSUPPORTED", 409)
    assert "파라미터 세트" in d["message"]
    _sql(engine, "update train_setups set features_rel = replace(features_rel, 'shell_features.json', 'parameter_features.json'), engine='altair' "
                 "where study_id=:s", s=sid)
    assert "Native" in bad(_req(SMALL), "DOE_PREVIEW_UNSUPPORTED", 409)["message"]


@pytest.mark.parametrize("dp_env", [{"doe_preview": {"enabled": False}}], indirect=True)
def test_disabled_config_is_409_unavailable_and_feature_flag(dp_env, monkeypatch):
    c, mk, ai, lc, _d = dp_env
    w = mk()
    sid, _ = _ready(c, w, ai, "dpoff", monkeypatch)
    r = c.post(f"{API}/studies/{sid}/doe-previews", headers=PW, json=_req(SMALL))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DOE_PREVIEW_UNAVAILABLE" and r.json()["detail"]["missing"]
    assert c.get(f"{API}/doe-previews/00000000-0000-0000-0000-000000000000", headers=P).status_code == 404
