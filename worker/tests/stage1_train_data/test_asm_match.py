"""조립 매칭(asm-match.md V-AM-9·10·11, 가짜 paicad): API 5개 + ASM_MATCH 작업(PREVIEW 레인) → ①-3 DOE(asm_match_id, RENUM·기준본 없음)
→ 방식 M 쌍 치환 argv · 트리 복사 · node_patch · asm write · prep.json inputs.asm_match · STALE · ④ 세트 등록 · 기존 RENUM 방식 불변."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from helpers_asm import ROWS, STARTER, _check, _confirmed, _create, _get, _scan, make_tree
from helpers_native import make_project
from helpers_stage1 import job, study, submit
from physicsai_test_support import API, H, MESH_INC, read_record

PW, P = H("tok-power", write=True), H("tok-power")


def _project(ai: Path, name: str) -> tuple[Path, Path]:
    proj = make_project(ai / name / "00_inbox", include_base=False, renum_csv=False)
    return proj, make_tree(proj / "asm")


def _extract(c, w, sid, proj: Path) -> None:
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])


def _doe(c, w, sid, asm: Path, expect="SUCCEEDED", **kw):
    """expect=409 → 요청 거부 응답 그대로, 그 밖 → 작업 최종 상태 확인 후 작업 본문."""
    p = {"doe_label": "LHS", "num_runs": 3, "seed": 7, "multi_execution": 2, "radioss_assem_path": str(asm), **kw}
    if expect == 409:
        return c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": p})
    j = submit(c, sid, "TD_DOE_GEN", p)
    assert w.run_once_slot() == expect, job(c, j["id"])
    return job(c, j["id"])


# ---- V-AM-9·10: 목록 → 매칭 → 검사 → 확정 ---------------------------------------------------------------------------


def test_scan_rows_check_confirm_flow(p2_native, fake_record):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am1")
    proj, asm = _project(ai, "am1")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)
    m = _get(c, mid)
    assert m["state"] == "DRAFT" and m["study_id"] == sid and m["assem"]["starter"] == STARTER and m["assem"]["digest"].startswith("sha256:")
    assert [b["body"] for b in m["bodies"]] == ["A", "B"] and {p["pid"] for p in m["parts"]} == {3000001, 3000002, 3000009}
    assert [r["pids"] for r in m["recommend"]] == [[3000001], [3000002]]
    assert m["rows_complete"] is False and set(m["use_bodies"]) == {"A", "B"}  # use=true 파라미터(A_THK_1·C_HOLE_R_1)가 있는 바디
    assert m["assem"]["files"] == 3  # unused.inc는 트리 밖
    argv = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1] == "asm"][-1]
    assert argv[2] == "parts" and "--features" in argv and "--cache-dir" in argv and "--renum-csv" not in argv
    assert (ai / "am1" / "_cache" / "asm_parse").is_dir()
    # 행 검증 422 — 사유 코드
    for bad, code in (({"rows": [{"body": "Z", "pids": [3000001]}], "excluded_bodies": ["A", "B"]}, "UNKNOWN_BODY"),
                      ({"rows": [{"body": "A", "pids": [999]}], "excluded_bodies": ["B"]}, "UNKNOWN_PID"),
                      ({"rows": [{"body": "A", "pids": [3000009]}], "excluded_bodies": ["B"]}, "NOT_SOLID"),
                      ({"rows": [{"body": "A", "pids": [3000001]}, {"body": "B", "pids": [3000001]}], "excluded_bodies": []}, "PID_DUPLICATE"),
                      ({"rows": [{"body": "A", "pids": [3000001]}], "excluded_bodies": []}, "BODY_MISSING"),
                      ({"rows": [{"body": "A", "pids": [3000001]}], "excluded_bodies": ["B"]}, "USE_PARAM")):
        r = c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=bad)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ASM_ROW_INVALID", r.text
        assert code in {p["code"] for p in r.json()["detail"]["problems"]}, (code, r.text)
    # 행 미완성이면 check·confirm 모두 409 ASM_ROWS_INCOMPLETE(검사 자체는 확정의 조건이 아니다, AM-C3)
    assert c.post(f"{API}/asm-matches/{mid}/check", headers=PW).json()["detail"]["code"] == "ASM_ROWS_INCOMPLETE"
    assert c.post(f"{API}/asm-matches/{mid}/confirm", headers=PW).json()["detail"]["code"] == "ASM_ROWS_INCOMPLETE"
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).json()["state"] == "DRAFT"
    started = _check(c, w, mid)
    assert started["seq"] == 1
    m = _get(c, mid)
    assert m["state"] == "CHECKED" and m["check"]["status"] == "PASS" and m["check"]["current"] is True
    pts = m["check"]["rows"][0]["worst"]["points"]  # 프런트 가정: rows[].worst.points[{xyz, dist_mm}]
    assert len(pts) == 3 and pts[0]["xyz"] == [0.0, 0.0, 0.0] and pts[0]["dist_mm"] == pytest.approx(0.04)
    glb = c.get(m["check"]["glb_url"], headers=P)
    assert glb.status_code == 200 and glb.content[:4] == b"glTF"
    # 행을 바꾸면 검사는 무효(current=false)
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json={"rows": ROWS["rows"][::-1], "excluded_bodies": []}).status_code == 200
    m = _get(c, mid)
    assert m["state"] == "CHECKED" and m["check"]["current"] is True  # 서버가 정규화(바디 순서) → 같은 내용이면 검사는 유효
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json={"rows": [{"body": "A", "pids": [3000001, 3000002]}],
                                                                     "excluded_bodies": ["B"]}).status_code == 422  # B는 use 파라미터가 있다
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json={"rows": [{"body": "A", "pids": [3000002]}, {"body": "B", "pids": [3000001]}],
                                                                     "excluded_bodies": []}).json()["state"] == "DRAFT"  # 내용이 바뀌면 검사 무효
    assert _get(c, mid)["check"]["current"] is False
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).status_code == 200
    _check(c, w, mid)
    r = c.post(f"{API}/asm-matches/{mid}/confirm", headers=PW)
    assert r.status_code == 200 and r.json()["state"] == "CONFIRMED" and r.json()["confirmed"]["sha256"]
    assert not [w for w in r.json()["warnings"] if w["code"].startswith("ASM_CHECK_")]  # 통과한 검사 = 경고 없음
    assert c.post(f"{API}/asm-matches/{mid}/confirm", headers=PW).json()["state"] == "CONFIRMED"  # 멱등
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).json()["detail"]["code"] == "ASM_MATCH_CONFIRMED"
    doc = json.loads((ai / "am1" / "asm_match" / mid / "asm_match.json").read_text())
    assert doc["cad"]["rel"] == "bracket.step" or doc["cad"]["rel"].endswith(".step")
    assert [r["body"] for r in doc["rows"]] and doc["check"]["rows_sha256"] and doc["check"]["status"] == "PASS" and doc["check"]["current"] is True
    # 목록(가산 API): 최신순·source 필터·latest
    lst = c.get(f"{API}/studies/{sid}/asm-matches", headers=P, params={"source": "train", "latest": "true"}).json()
    assert [x["match_id"] for x in lst["items"]] == [mid]
    assert c.get(f"{API}/studies/{sid}/asm-matches", headers=P, params={"source": "path"}).json()["items"] == []


def _codes(m: dict) -> set[str]:
    return {w["code"] for w in m["warnings"]}


def test_confirm_without_check_is_allowed(p2_native):
    """AM-C3: 경계 검사는 선택 — 검사 없이 확정되고(경고 없음), 확정본 check = null, 하류 DOE도 그대로 동작한다."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am2a")
    proj, asm = _project(ai, "am2a")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).status_code == 200
    assert _get(c, mid)["check"] is None
    r = c.post(f"{API}/asm-matches/{mid}/confirm", headers=PW)
    assert r.status_code == 200 and r.json()["state"] == "CONFIRMED" and r.json()["check"] is None, r.text
    assert not [x for x in r.json()["warnings"] if x["code"].startswith("ASM_CHECK_")]
    doc = json.loads((ai / "am2a" / "asm_match" / mid / "asm_match.json").read_text())
    assert doc["check"] is None and [x["body"] for x in doc["rows"]] == ["A", "B"] and doc["assem"]["digest"].startswith("sha256:")
    assert _doe(c, w, sid, asm, asm_match_id=mid)["result"]["run_count"] == 3  # ①-3 DOE는 검사 통과를 요구하지 않는다
    # 확정 뒤에는 검사도 행 저장도 막힌다(확정본 불변)
    assert c.post(f"{API}/asm-matches/{mid}/check", headers=PW).json()["detail"]["code"] == "ASM_MATCH_CONFIRMED"


def test_failed_check_is_data_and_only_warns_on_confirm(p2_native, monkeypatch):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am2")
    proj, asm = _project(ai, "am2")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).status_code == 200
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "asm_check:ASM_BOUNDARY_MISMATCH")
    _check(c, w, mid)  # rows가 있는 FAIL = 작업 SUCCEEDED(결과 데이터)
    m = _get(c, mid)
    assert m["check"]["status"] == "FAIL" and m["check"]["code"] == "ASM_BOUNDARY_MISMATCH" and m["state"] == "DRAFT"
    assert not _codes(m) & {"ASM_CHECK_FAILED_WARN", "ASM_CHECK_STALE_WARN"}  # 확정 전에는 화면이 검사 결과를 직접 보인다
    r = c.post(f"{API}/asm-matches/{mid}/confirm", headers=PW)  # FAIL이어도 확정은 허용 + 경고
    assert r.status_code == 200 and r.json()["state"] == "CONFIRMED", r.text
    assert "ASM_CHECK_FAILED_WARN" in _codes(r.json()) and "ASM_CHECK_STALE_WARN" not in _codes(r.json())
    assert "ASM_CHECK_FAILED_WARN" in _codes(_get(c, mid))  # 조회에도 유지
    doc = json.loads((ai / "am2" / "asm_match" / mid / "asm_match.json").read_text())
    assert doc["check"]["status"] == "FAIL" and doc["check"]["current"] is False
    # rows 없는 FAIL = 작업 FAILED(별도 묶음)
    mid2 = _scan(c, w, sid, asm)
    assert c.put(f"{API}/asm-matches/{mid2}/rows", headers=PW, json=ROWS).status_code == 200
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "asm_check_norows:ASM_INCLUDE_MISSING")
    r = c.post(f"{API}/asm-matches/{mid2}/check", headers=PW)
    assert w.run_once_preview() == "FAILED"
    assert job(c, r.json()["job_id"])["failure_code"] == "ASM_INCLUDE_MISSING"


def test_confirm_after_rows_changed_warns_stale_check(p2_native):
    """검사 PASS 뒤 행을 바꾸고 확정 → 허용 + ASM_CHECK_STALE_WARN(검사가 현재 행과 다름)."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am2b")
    proj, asm = _project(ai, "am2b")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).status_code == 200
    _check(c, w, mid)
    swapped = {"rows": [{"body": "A", "pids": [3000002]}, {"body": "B", "pids": [3000001]}], "excluded_bodies": []}
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=swapped).json()["check"]["current"] is False
    r = c.post(f"{API}/asm-matches/{mid}/confirm", headers=PW)
    assert r.status_code == 200 and r.json()["state"] == "CONFIRMED", r.text
    assert "ASM_CHECK_STALE_WARN" in _codes(r.json()) and "ASM_CHECK_FAILED_WARN" not in _codes(r.json())
    assert [x["pids"] for x in r.json()["rows"]] == [[3000002], [3000001]]


def test_confirm_keeps_stale_gate(p2_native):
    """검사가 없어도 조립 트리가 바뀌면 확정은 409 ASM_MATCH_STALE(AM-C3은 STALE 규칙을 바꾸지 않는다)."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am2c")
    proj, asm = _project(ai, "am2c")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).status_code == 200
    (asm / "101_parts.inc").write_text("/PART/3000001\nCUSH_A\n/PART/3000002\nCUSH_B\n/PART/3000009\nPLATE_CHANGED\n")
    r = c.post(f"{API}/asm-matches/{mid}/confirm", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ASM_MATCH_STALE"


def test_check_job_can_be_cancelled_by_power_user(p2_native):
    """AM-C3: 시간 제한이 없는 검사는 power 사용자가 [취소](POST /asm-matches/{id}/cancel)로 멈춘다(작업 취소 API는 관리자 전용). 행은 그대로."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am2e")
    proj, asm = _project(ai, "am2e")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).status_code == 200
    assert c.post(f"{API}/asm-matches/{mid}/cancel", headers=PW).json()["detail"]["code"] == "JOB_TERMINAL"  # 진행 중 작업 없음
    started = c.post(f"{API}/asm-matches/{mid}/check", headers=PW).json()
    assert _get(c, mid)["state"] == "CHECKING"
    assert c.post(f"{API}/asm-matches/{mid}/cancel", headers=H("tok-general", write=True)).status_code == 403
    r = c.post(f"{API}/asm-matches/{mid}/cancel", headers=PW)
    assert r.status_code == 202, r.text
    assert job(c, started["job_id"])["state"] == "CANCELED"
    m = _get(c, mid)
    assert m["state"] == "DRAFT" and m["check"] is None and m["last_job"]["state"] == "CANCELED"
    assert [x["body"] for x in m["rows"]] == ["A", "B"]  # 표는 그대로
    assert c.post(f"{API}/asm-matches/{mid}/cancel", headers=PW).json()["detail"]["code"] == "JOB_TERMINAL"
    _check(c, w, mid)  # 취소 뒤 다시 검사할 수 있다(seq 증가)
    assert _get(c, mid)["check"]["seq"] == 2 and _get(c, mid)["state"] == "CHECKED"


def test_check_timeout_unlimited_and_parts_keeps_limit(p2_native, monkeypatch):
    """AM-C3: asm check 시간 제한 기본 null(상한 없음), asm parts는 asm_match.timeout_s 유지. 설정으로 check에 상한을 줄 수도 있다."""
    from physicsai_worker.steps import asm_match as step

    c, mk, ai, lc, _d = p2_native
    w = mk()
    assert w.settings.asm_match.check_timeout_s is None and w.settings.asm_match.timeout_s == 600
    seen: list[tuple[str, float | None]] = []
    real = step.run_paicad

    def spy(x, settings, key, values, **kw):
        seen.append((key, kw.get("timeout_s", "unset")))
        return real(x, settings, key, values, **kw)

    monkeypatch.setattr(step, "run_paicad", spy)
    sid = study(c, "am2d")
    proj, asm = _project(ai, "am2d")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).status_code == 200
    _check(c, w, mid)
    assert seen == [("paicad_asm_parts", 600.0), ("paicad_asm_check", None)]
    w.settings.asm_match.check_timeout_s = 90.0
    _check(c, w, mid)
    assert seen[-1] == ("paicad_asm_check", 90.0)


def test_scan_failure_and_unsupported_sources(p2_native, monkeypatch):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am3")
    proj, asm = _project(ai, "am3")
    out = _create(c, sid, asm, {"kind": "train"}, expect=409)  # ① Native 추출 없음
    assert out["detail"]["code"] == "PREREQUISITE_MISSING" and out["detail"]["missing"] == ["GEOM_FEATURES"]
    _extract(c, w, sid, proj)
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "asm_parts:ASM_NO_SOLID_PART")
    out = _create(c, sid, asm, {"kind": "train"})
    assert w.run_once_preview() == "FAILED" and job(c, out["job_id"])["failure_code"] == "ASM_NO_SOLID_PART"
    m = _get(c, out["match_id"])
    assert m["state"] == "FAILED" and m["last_job"]["failure_code"] == "ASM_NO_SOLID_PART"
    assert c.put(f"{API}/asm-matches/{out['match_id']}/rows", headers=PW, json=ROWS).json()["detail"]["code"] == "PREREQUISITE_MISSING"
    assert c.get(f"{API}/asm-matches/{'0' * 8}-0000-0000-0000-{'0' * 12}", headers=P).status_code == 404


# ---- ①-3 DOE(asm_match_id) -----------------------------------------------------------------------------------------


def test_doe_with_asm_match_uses_method_m(p2_native, fake_record):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am4")
    proj, asm = _project(ai, "am4")
    _extract(c, w, sid, proj)
    # 매칭 없이 + 기준본·RENUM 없음 → 409 ASM_MATCH(문구 '조립 매칭')
    r = _doe(c, w, sid, asm, expect=409)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "PREREQUISITE_MISSING" and "ASM_MATCH" in d["missing"] and "조립 매칭" in d["message"]
    assert "renum" not in d["message"].lower() and "기준" not in d["message"]
    mid = _confirmed(c, w, sid, asm)
    jd = _doe(c, w, sid, asm, asm_match_id=mid)
    doe_id = jd["result"]["doe_id"]
    assert jd["result"]["run_count"] == 3 and jd["params"]["asm_match_id"] == mid and len(jd["params"]["asm_match_sha256"]) == 64
    D = ai / "am4" / "01_train" / "doe" / doe_id
    assert (D / "cad" / "asm_match.json").is_file()
    prep = json.loads((D / "native" / "prep.json").read_text())
    assert prep["inputs"]["asm_match"]["rel"] == "cad/asm_match.json" and prep["inputs"]["baseline_inc"] is None
    assert prep["inputs"]["renum_csv"] is None and prep["inputs"]["assem_digest"].startswith("sha256:")
    for run in sorted((D / "approaches" / "doe_1").iterdir()):
        assert (run / STARTER).is_file() and (run / "nodes" / "102_nodes.inc").is_file() and (run / "101_parts.inc").is_file()
        assert not (run / MESH_INC).exists() and not (run / "unused.inc").exists()  # 기준본 파일 없음·트리 밖 파일 불복사
        assert "#FAKE_PATCH" in (run / STARTER).read_text()  # asm write: 패치가 조립 사본에 반영
        assert (run / "_paicad" / "node_patch.npz").is_file() and not (run / "_paicad" / MESH_INC).exists()
        assert (run / "_paicad" / "morph" / "node_xyz.npz").is_file()
    tools = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad"]
    for sub in ("tag", "run"):  # DOE는 paicad_run(update→morph→check 한 번에)을 쓴다
        a = next(x for x in tools if x[1] == sub)
        assert "--asm-match" in a and "--renum-csv" not in a and "--baseline-inc" not in a and "--cache-dir" in a, (sub, a)
    run_a = next(x for x in tools if x[1] == "run")
    assert "--out-patch" in run_a and "--out-inc" not in run_a
    assert any(x[1:3] == ["asm", "write"] and "--patch" in x for x in tools)
    # 트리 파일을 고치면 DOE 요청 409 ASM_MATCH_STALE(확정본 digest 불일치)
    (asm / "nodes" / "102_nodes.inc").write_text("/NODE\n 1 0 0 1\n/TETRA4/3000001\n 1 1 1 1 1\n")
    r = _doe(c, w, sid, asm, expect=409, asm_match_id=mid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ASM_MATCH_STALE"
    m = _get(c, mid)
    assert m["state"] == "STALE" and m["stale_reason"]
    # 트리 밖 파일은 digest에 들어가지 않는다(STALE 아님)
    (asm / "nodes" / "102_nodes.inc").write_text("/NODE\n 1 0 0 0\n/TETRA4/3000001\n 1 1 1 1 1\n/TETRA4/3000002\n 2 1 1 1 1\n/SHELL/3000009\n 3 1 1 1 1\n")
    (asm / "unused.inc").write_text("edited outside the tree\n")
    assert _get(c, mid)["state"] == "CONFIRMED"


def test_doe_rejects_unconfirmed_and_mismatched_match(p2_native):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am5")
    proj, asm = _project(ai, "am5")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)  # 확정 전
    r = _doe(c, w, sid, asm, expect=409, asm_match_id=mid)
    assert r.json()["detail"]["code"] == "PREREQUISITE_MISSING" and "ASM_MATCH" in r.json()["detail"]["missing"]
    mid = _confirmed(c, w, sid, asm)
    other = make_tree(proj / "asm_other")  # 다른 조립 폴더 경로(내용은 같아도 digest는 같다 → 통과), 파일을 바꾸면 STALE
    (other / "101_parts.inc").write_text("/PART/3000001\nCUSH_A\n/PART/3000002\nCUSH_B_RENAMED\n/PART/3000009\nPLATE\n")
    r = _doe(c, w, sid, other, expect=409, asm_match_id=mid)
    assert r.json()["detail"]["code"] == "ASM_MATCH_STALE"
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": {
        "doe_label": "X", "num_runs": 3, "radioss_assem_path": str(asm), "asm_match_id": "not-a-uuid"}})
    assert r.status_code in (404, 409, 422) and r.json()["detail"]["code"] in ("PREREQUISITE_MISSING", "INVALID_PARAMS", "INPUT_INVALID")


# ---- V-AM-11: 기존 RENUM 방식 불변 -------------------------------------------------------------------------------------


def test_legacy_renum_doe_unchanged(p2_native, fake_record):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am6")
    proj = make_project(ai / "am6" / "00_inbox")  # 기준본·RENUM 있는 기존 조립 폴더
    _extract(c, w, sid, proj)
    jd = _doe(c, w, sid, proj / "assem")
    assert jd["result"]["run_count"] == 3 and "asm_match_id" not in jd["params"]
    D = ai / "am6" / "01_train" / "doe" / jd["result"]["doe_id"]
    assert not (D / "cad" / "asm_match.json").exists()
    prep = json.loads((D / "native" / "prep.json").read_text())
    assert prep["inputs"]["baseline_inc"] and prep["inputs"]["renum_csv"] and "asm_match" not in prep["inputs"]
    tools = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad"]
    tag = next(x for x in tools if x[1] == "tag")
    assert "--renum-csv" in tag and "--baseline-inc" in tag and "--asm-match" not in tag
    assert not any(x[1] == "asm" for x in tools)
    assert (D / "approaches" / "doe_1" / "run__00001" / MESH_INC).is_file()


# ---- ④ 새 템플릿 등록(PARAM_SET_NATIVE + asm_match_id, source=path) ----------------------------------------------------


def test_register_native_set_with_asm_match(p2_native, fake_record):
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am7")
    proj = make_project(ai / "am7" / "00_inbox", include_base=False, renum_csv=False)
    shutil.rmtree(proj / "assem")
    asm = make_tree(proj / "assem")  # 프로젝트 폴더의 조립 폴더(후보 = starter 1개, 기준본·RENUM 없음)
    # 일반 discover는 기준본 없음 문제를 내지만 asm_match=true는 내지 않는다
    plain = c.post(f"{API}/studies/{sid}/param-sets/discover", headers=PW, json={"path": str(proj), "engine": "native"}).json()
    assert {p["code"] for p in plain["problems"]} & {"BASELINE_INC_MISSING", "RENUM_CSV_MISSING"}
    ok = c.post(f"{API}/studies/{sid}/param-sets/discover", headers=PW, json={"path": str(proj), "engine": "native", "asm_match": True}).json()
    assert not {p["code"] for p in ok["problems"]} & {"BASELINE_INC_MISSING", "RENUM_CSV_MISSING"} and ok["radioss_assem"]
    # 조립 매칭 없이 등록 → 422(기준본 없음), 쉘은 422 ASM_MATCH_UNSUPPORTED
    body = {"path": str(proj), "mode": "discover", "engine": "native", "label": "M"}
    assert c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json=body).status_code == 422
    mid = _confirmed(c, w, sid, asm, {"kind": "path", "path": str(proj / "bracket.step")})
    r = c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={**body, "asm_match_id": mid, "kind": "shell"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ASM_MATCH_UNSUPPORTED"
    r = c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={**body, "asm_match_id": mid})
    assert r.status_code == 202, r.text
    assert w.run_once_slot() == "SUCCEEDED", job(c, r.json()["job_id"])
    jb = job(c, r.json()["job_id"])
    assert jb["params"]["asm_match_id"] == mid and len(jb["params"]["asm_match_sha256"]) == 64
    ps = c.get(f"{API}/param-sets/{jb['result']['param_set_id']}", headers=P).json()
    S = ai / "am7" / ps["stored_rel"].strip("/") if "stored_rel" in ps else None
    S = S or next((ai / "am7" / "04_params").iterdir())
    assert (S / "cad" / "asm_match.json").is_file() and (S / "radioss_assem" / "nodes" / "102_nodes.inc").is_file()
    assert not (S / "radioss_assem" / "unused.inc").exists()
    prep = json.loads((S / "native" / "prep.json").read_text())
    assert prep["inputs"]["asm_match"]["rel"] == "cad/asm_match.json" and prep["inputs"]["baseline_inc"] is None
    assert ps["native"]["prep_status"] == "READY"
    tag = next(x["argv"] for x in read_record(fake_record) if x["tool"] == "paicad" and x["argv"][1] == "tag")
    assert "--asm-match" in tag and "--renum-csv" not in tag
    # 4B(다중 baseline)는 1차 미지원 → 409 ASM_MATCH_UNSUPPORTED
    other = make_project(ai / "am7" / "00_inbox" / "other", include_base=True)
    r = c.post(f"{API}/param-sets/{ps['id']}/baselines", headers=PW, json={"id": "B2", "path": str(other)})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ASM_MATCH_UNSUPPORTED", r.text
    # 세트 파일을 바꾸면 준비본이 STALE(GEOM_PREP_STALE 판정)
    (S / "radioss_assem" / "101_parts.inc").write_text("/PART/3000001\nCUSH_A\nchanged\n")
    ps2 = c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()
    assert ps2["native"]["prep_status"] == "STALE"


def test_permissions_and_not_found(p2_native):
    """쓰기 API(생성·행 저장·검사·확정)는 일반 권한(general)이 아니라 파워 이상 — 조회는 누구나. 없는 묶음·형식 오류 id = 404."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "am8")
    proj, asm = _project(ai, "am8")
    _extract(c, w, sid, proj)
    mid = _scan(c, w, sid, asm)
    gw = H("tok-general", write=True)
    assert c.post(f"{API}/studies/{sid}/asm-matches", headers=gw, json={"radioss_assem_path": str(asm), "cad": {"kind": "train"}}).status_code == 403
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=gw, json=ROWS).status_code == 403
    assert c.post(f"{API}/asm-matches/{mid}/check", headers=gw).status_code == 403
    assert c.post(f"{API}/asm-matches/{mid}/confirm", headers=gw).status_code == 403
    assert c.get(f"{API}/asm-matches/{mid}", headers=H("tok-general")).status_code == 200
    for bad in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        assert c.get(f"{API}/asm-matches/{bad}", headers=P).status_code == 404
    assert c.post(f"{API}/studies/{sid}/asm-matches", headers=PW, json={"radioss_assem_path": str(asm), "cad": {"kind": "path"}}).status_code == 422
    other = ai.parent / "outside_root"
    other.mkdir(exist_ok=True)
    assert c.post(f"{API}/studies/{sid}/asm-matches", headers=PW, json={"radioss_assem_path": str(other), "cad": {"kind": "train"}}).status_code == 422
