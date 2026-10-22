"""결과 3D 컨투어 E2E(geometry-view.md §13, 열 때 생성): POST /contour3d → 202(진행 단계 대기) → CONTOUR_3D(CPU 대기열: hw TCL 추출 →
변환 → 등록) → DONE·artifacts 3종(GLB·프레임 Range·manifest) → 다시 열면 200 캐시. 결정적 실패 캐시·인프라 실패 비캐시·시간 초과·
취소·미구성 409, 외부 면 계산 대체(elements.csv), FEM 검증·h3d 경로 원본. 가짜 hw(contour3d 모드)."""

from __future__ import annotations

import json
import struct

from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
M = H("tok-general", write=True)  # member(general) — 읽기 사용자
VALUES = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}


def _env(predict_env, **extra):
    env = predict_env(extra={"contour3d": {"enabled": True, "max_frames": 3, **extra}})
    env.param_set()
    j = env.submit("PREDICT", VALUES)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    return env, j["id"]


def _open(env, body, expect=(200, 202)):
    r = env.c.post(f"{API}/contour3d", headers=PW, json=body)
    assert r.status_code in ((expect,) if isinstance(expect, int) else expect), r.text
    return r


def test_contour3d_open_progress_done_and_cache(predict_env, fake_record, monkeypatch):
    monkeypatch.setenv("FAKE_CONTOUR3D_FRAMES", "7")
    env, jid = _env(predict_env)
    r = _open(env, {"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}}, expect=202)
    c = r.json()
    assert c["status"] == "QUEUED" and c["cache_hit"] is False and c["progress"]["phase"] == "waiting"
    assert c["progress"]["phase_label"] == "대기" and c["progress"]["can_cancel"] is True and c["progress"]["estimate_s"] is None
    dup = _open(env, {"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}}, expect=202).json()
    assert dup["id"] == c["id"]  # 같은 키 대기 중 → 그 행
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(c["job_id"])
    g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert g["status"] == "DONE" and g["result_status"] == "OK" and g["frames"] == 3 and g["nodes"] == 6
    assert g["progress"]["phase"] == "done" and g["progress"]["can_cancel"] is False and g["timing"]["total_s"] is not None
    rec = [x for x in read_record(fake_record) if x["tool"] == "hw_contour3d"][-1]
    st = rec["settings"]
    assert st["MAX_FRAMES"] == "3" and st["INCLUDE_DISP"] == "1" and st["FIELD"] == env.lc.settings.capture.default_field
    man = env.c.get(f"{API}/artifacts/{g['manifest_artifact_id']}/content", headers=P).json()
    assert man["status"] == "OK" and man["source"]["kind"] == "PREDICT_H3D" and man["sampling"]["total_frames"] == 7
    assert [f["src"] for f in man["frames"]["list"]] == [0, 3, 6] and man["frames"]["has_disp"] is True
    rb = man["frames"]["record_bytes"]
    r1 = env.c.get(f"{API}/artifacts/{g['frames_artifact_id']}/media", headers={**P, "Range": f"bytes={rb}-{2 * rb - 1}"})
    assert r1.status_code == 206 and r1.headers["content-type"] == "application/octet-stream" and len(r1.content) == rb
    assert list(struct.unpack_from("<6f", r1.content, 0)) == [0.0, 3.0, 6.0, 9.0, 12.0, 15.0]  # 프레임 1(src 3)
    glb = env.c.get(f"{API}/artifacts/{g['glb_artifact_id']}/media", headers=P)
    assert glb.status_code == 200 and glb.content[:4] == b"glTF"
    C = env.sroot / "_cache" / "contour3d"
    assert not list(C.rglob("extract"))  # 변환 후 추출 CSV 삭제
    hit = _open(env, {"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}}, expect=200).json()
    assert hit["cache_hit"] and hit["id"] == c["id"]
    other = _open(env, {"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}, "display": {"field": "Displacement"}},
                  expect=202).json()
    assert other["id"] != c["id"] and other["display"]["field"] == "Displacement"
    assert env.w.run_once_slot() == "SUCCEEDED"
    est = env.c.get(f"{API}/contour3d/{other['id']}", headers=P).json()
    assert est["progress"]["estimate_s"] is not None  # 같은 원본 종류 최근 소요


def test_contour3d_deterministic_fail_cached_infra_not(predict_env, monkeypatch):
    env, jid = _env(predict_env)
    body = {"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}}
    monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", "nan")
    c = _open(env, body, expect=202).json()
    assert env.w.run_once_slot() == "SUCCEEDED"
    g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    assert g["status"] == "DONE" and g["result_status"] == "FAIL" and g["code"] == "CONTOUR3D_FIELD_EMPTY"
    assert g["message_ko"] == "선택한 결과 값이 없습니다" and g["glb_artifact_id"] is None and g["manifest_artifact_id"]
    assert _open(env, body, expect=200).json()["cache_hit"]
    monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", "open_error")
    body2 = {**body, "display": {"field": "X"}}
    c2 = _open(env, body2, expect=202).json()
    assert env.w.run_once_slot() == "FAILED"
    g = env.c.get(f"{API}/contour3d/{c2['id']}", headers=P).json()
    assert g["status"] == "FAILED" and g["code"] == "CONTOUR3D_OPEN_ERROR" and g["progress"]["phase"] == "failed"
    assert _open(env, body2, expect=202).json()["id"] != c2["id"]  # 인프라 실패는 캐시 안 함
    monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", "invalid")
    c3 = _open(env, {**body, "display": {"field": "Y"}}, expect=202).json()
    env.w.run_once_slot()  # 앞의 대기 작업
    assert env.w.run_once_slot() == "FAILED"
    assert env.job(c3["job_id"])["failure_code"] == "CONTOUR3D_EXTRACT_INVALID"


def test_contour3d_timeout_cancel_and_not_configured(predict_env, monkeypatch):
    env, jid = _env(predict_env, timeout_s=1)
    monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", "hang")
    monkeypatch.setenv("FAKE_CAPTURE_HANG_S", "5")
    c = _open(env, {"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}}, expect=202).json()
    assert env.w.run_once_slot() == "FAILED"
    assert env.job(c["job_id"])["failure_code"] == "CONTOUR3D_TIMEOUT"
    q = _open(env, {"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}, "display": {"field": "Z"}}, expect=202).json()
    r = env.c.post(f"{API}/contour3d/{q['id']}/cancel", headers=PW)
    assert r.status_code == 200 and r.json()["status"] == "CANCELED" and r.json()["progress"]["phase"] == "canceled"
    assert env.c.post(f"{API}/contour3d/{q['id']}/cancel", headers=PW).status_code == 409
    off = predict_env(folder="p2")
    off.param_set()
    r = off.c.post(f"{API}/contour3d", headers=PW, json={"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CONTOUR3D_NOT_CONFIGURED"


def test_contour3d_elements_fallback_and_h3d_rel(predict_env, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_CONTOUR3D", "elements")
    env, jid = _env(predict_env)
    rel = env.job(jid)["result"]["pred_h3d_rel"]
    c = _open(env, {"source_kind": "SOLVER_H3D", "source_ref": {"study_id": env.sid, "h3d_rel": rel}}, expect=202).json()
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(c["job_id"])
    g = env.c.get(f"{API}/contour3d/{c['id']}", headers=P).json()
    man = env.c.get(f"{API}/artifacts/{g['manifest_artifact_id']}/content", headers=P).json()
    assert g["source_kind"] == "SOLVER_H3D" and man["mesh"]["nodes"] == 10 and man["mesh"]["triangles"] == 14  # 육면체 외부 면 + 쉘
    r = env.c.post(f"{API}/contour3d", headers=PW, json={"source_kind": "SOLVER_H3D", "source_ref": {"study_id": env.sid,
                                                                                                    "h3d_rel": "../../etc/x.h3d"}})
    assert r.status_code in (409, 422), r.text
    r = env.c.post(f"{API}/contour3d", headers=PW, json={"source_kind": "PREDICT_H3D", "source_ref": {"job_id": "nope"}})
    assert r.status_code == 422
    assert json.loads(json.dumps(g))["frames_artifact_id"]


def test_contour3d_member_cache_hit_ok_new_generation_needs_power(predict_env):
    """V-C3D-7 / C3D-6: member는 캐시 적중 200·진행 중 202(작업 추가 0)만 허용, 미적중 새 생성은 403(작업·행 0건), power 미적중은 202."""
    env, jid = _env(predict_env)
    body = {"source_kind": "PREDICT_H3D", "source_ref": {"job_id": jid}}

    def counts():
        return (env.sql("select count(*) from jobs where job_type='CONTOUR_3D'")[0][0],
                env.sql("select count(*) from contour3d_cache")[0][0])

    def member(b):
        return env.c.post(f"{API}/contour3d", headers=M, json=b)

    r = member(body)  # 미적중 + 진행 중 행 없음 → 403, 아무것도 만들지 않음
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PERMISSION_DENIED" and r.json()["detail"]["required"] == "power"
    assert counts() == (0, 0)
    c = _open(env, body, expect=202).json()  # power 새 생성
    assert counts() == (1, 1)
    r = member(body)  # 진행 중 → member도 같은 행(202), 새 작업 없음
    assert r.status_code == 202 and r.json()["id"] == c["id"] and r.json()["cache_hit"] is False
    assert counts() == (1, 1)
    assert env.w.run_once_light() == "SUCCEEDED", env.job(c["job_id"])
    r = member(body)  # 적중 → 200, 작업 추가 0
    assert r.status_code == 200 and r.json()["cache_hit"] is True and r.json()["id"] == c["id"] and r.json()["status"] == "DONE"
    assert counts() == (1, 1)
    r = member({**body, "display": {"field": "Displacement"}})  # 다른 표시 = 미적중 → 403, 작업·행 0건 추가
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PERMISSION_DENIED"
    assert counts() == (1, 1)
    assert _open(env, {**body, "display": {"field": "Displacement"}}, expect=202).json()["id"] != c["id"]  # power는 202
    assert counts() == (2, 2)
    # 설정 확인(409)·원본 확인(404/409/422)은 권한보다 앞선다
    r = env.c.post(f"{API}/contour3d", headers=M, json={"source_kind": "PREDICT_H3D", "source_ref": {"job_id": "nope"}})
    assert r.status_code == 422
    # 취소는 power 그대로
    assert env.c.post(f"{API}/contour3d/{c['id']}/cancel", headers=M).status_code == 403
