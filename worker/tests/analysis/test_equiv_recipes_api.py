"""equiv-check.md V-EQ-3(레시피 생명주기)·V-EQ-4(권한·범위)·V-EQ-10(API 계약: 목록 3그룹·이력 필터·커서·오류 한국어)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from physicsai_test_support import API, H

from .eq_support import recipe_def

PW, P, GW = H("tok-power", write=True), H("tok-power"), H("tok-general", write=True)
P2W, AW = H("tok-power2", write=True), H("tok-admin", write=True)


@pytest.fixture()
def study(client):
    r = client.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": "eqs", "title": "등가성"})
    assert r.status_code == 201, r.text
    r2 = client.post(f"{API}/studies", headers=H("tok-nonmember", write=True), json={"project_id": "p-2", "folder_name": "eqs2", "title": "다른"})
    assert r2.status_code == 201, r2.text
    return r.json()["id"], r2.json()["id"]


def _create(client, sid, name="내 레시피", scope="study", headers=PW, expect=201, **kw):
    body = {"name": name, "scope": scope, **kw}
    if scope == "study":
        body["study_id"] = sid
    if not any(k in kw for k in ("definition", "clone_from", "from_check")):
        body["definition"] = recipe_def()
    r = client.post(f"{API}/equiv/recipes", headers=headers, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def test_v_eq_3_lifecycle(client, study, engine):
    sid, _other = study
    lst = client.get(f"{API}/equiv/recipes", headers=P, params={"study_id": sid}).json()
    assert [x["scope"] for x in lst] == ["system"] and lst[0]["key"] == "sys:default" and lst[0]["readonly"] is True
    sysr = client.get(f"{API}/equiv/recipes/sys:default", headers=P).json()
    assert sysr["definition"]["metrics"][0]["source"] is None and sysr["metrics_count"] == 8 and sysr["version"] == 1
    # 복제(시스템 기본에서) → parent 기록, v1
    c = _create(client, sid, name="복제본", clone_from={"key": "sys:default"})
    assert c["version"] == 1 and c["parent"] == {"key": "sys:default", "version": 1} and c["can_edit"] is True
    assert c["definition"]["metrics"][4]["required"] is False
    # 편집 = 새 버전(이전 행 불변), base_version 충돌 409
    d = c["definition"]
    d["metrics"][4]["required"] = True
    r = client.put(f"{API}/equiv/recipes/{c['key']}", headers=PW, json={"base_version": 1, "definition": d, "description": "응력 필수"})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["description"] == "응력 필수"
    r = client.put(f"{API}/equiv/recipes/{c['key']}", headers=PW, json={"base_version": 1, "definition": d})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EQ_RECIPE_VERSION_CONFLICT" and r.json()["detail"]["current_version"] == 2
    v1 = client.get(f"{API}/equiv/recipes/{c['key']}", headers=P, params={"version": 1}).json()
    assert v1["definition"]["metrics"][4]["required"] is False and v1["version"] == 1
    vs = client.get(f"{API}/equiv/recipes/{c['key']}/versions", headers=P).json()
    assert [v["version"] for v in vs["versions"]] == [2, 1] and vs["version"] == 2
    # 이름 중복(같은 범위, 대소문자 무시) 409, 다른 범위는 허용
    _create(client, sid, name="복제본", expect=409)
    _create(client, sid, name="복제본", scope="global")
    r = client.put(f"{API}/equiv/recipes/{c['key']}", headers=PW, json={"base_version": 2, "name": "복제본", "definition": d})
    assert r.status_code == 200 and r.json()["version"] == 3  # 자기 이름 유지는 중복 아님
    # 검증 오류 422(problems 코드)
    bad = recipe_def()
    bad["metrics"][0]["tol"] = {"rel_pct": -1}
    r = client.post(f"{API}/equiv/recipes", headers=PW, json={"name": "x", "scope": "study", "study_id": sid, "definition": bad})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "EQ_RECIPE_INVALID" and r.json()["detail"]["problems"][0]["code"] == "TOL_INVALID"
    # 시스템 기본 수정·삭제 409
    r = client.put(f"{API}/equiv/recipes/sys:default", headers=PW, json={"base_version": 1, "definition": d})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EQ_RECIPE_READONLY"
    assert client.delete(f"{API}/equiv/recipes/sys:default", headers=PW).status_code == 409
    # 소프트 삭제 → 목록 숨김·조회는 deleted:true·편집 404, restore(관리자만, 멱등)
    assert client.delete(f"{API}/equiv/recipes/{c['key']}", headers=PW).status_code == 204
    assert client.delete(f"{API}/equiv/recipes/{c['key']}", headers=PW).status_code == 204
    names = [x["name"] for x in client.get(f"{API}/equiv/recipes", headers=P, params={"study_id": sid}).json()]
    assert "복제본" in names and names.count("복제본") == 1  # global 하나만 남음
    g = client.get(f"{API}/equiv/recipes/{c['key']}", headers=P).json()
    assert g["deleted"] is True and g["version"] == 3 and g["can_edit"] is False
    assert client.put(f"{API}/equiv/recipes/{c['key']}", headers=PW, json={"base_version": 3, "definition": d}).status_code == 404
    assert client.post(f"{API}/equiv/recipes/{c['key']}/restore", headers=PW).status_code == 403
    r = client.post(f"{API}/equiv/recipes/{c['key']}/restore", headers=AW)
    assert r.status_code == 200 and r.json()["deleted"] is False
    assert client.post(f"{API}/equiv/recipes/{c['key']}/restore", headers=AW).status_code == 200
    with engine.connect() as conn:
        rows = conn.execute(text("select version, name from eq_recipes where recipe_key=:k order by version"), {"k": c["key"]}).all()
        acts = [r[0] for r in conn.execute(text("select action from audit_events where target_type='eq_recipe' order by occurred_at")).all()]
    assert [r[0] for r in rows] == [1, 2, 3] and "EQ_RECIPE_CREATE" in acts and "EQ_RECIPE_DELETE" in acts and "EQ_RECIPE_RESTORE" in acts


def test_v_eq_4_permissions_and_scope(client, study):
    sid, other = study
    _create(client, sid, headers=GW, expect=403)  # general 생성 403
    g = _create(client, sid, name="전역", scope="global", headers=PW)
    d = g["definition"]
    r = client.put(f"{API}/equiv/recipes/{g['key']}", headers=P2W, json={"base_version": 1, "definition": d})
    assert r.status_code == 403 and "작성자" in r.json()["detail"]["message"]  # global 타인 편집 403
    assert client.delete(f"{API}/equiv/recipes/{g['key']}", headers=P2W).status_code == 403
    r = client.put(f"{API}/equiv/recipes/{g['key']}", headers=AW, json={"base_version": 1, "definition": d})
    assert r.status_code == 200 and r.json()["version"] == 2  # admin 허용
    s = _create(client, sid, name="이 Study만")
    mine = client.get(f"{API}/equiv/recipes", headers=P, params={"study_id": sid}).json()
    theirs = client.get(f"{API}/equiv/recipes", headers=H("tok-nonmember"), params={"study_id": other}).json()
    assert {x["name"] for x in mine} == {"시스템 기본(제안값)", "전역", "이 Study만"}
    assert {x["name"] for x in theirs} == {"시스템 기본(제안값)", "전역"}  # study 레시피는 다른 Study에서 안 보임
    assert [x["scope"] for x in mine] == ["system", "study", "global"] or {x["scope"] for x in mine} == {"system", "study", "global"}
    assert client.get(f"{API}/equiv/recipes/{s['key']}", headers=H("tok-general")).status_code == 200  # 읽기는 로그인 사용자
    r = client.get(f"{API}/equiv/recipes/{uuid.uuid4()}", headers=P)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "EQ_RECIPE_NOT_FOUND" and "레시피" in r.json()["detail"]["message"]


def test_v_eq_10_check_create_errors_list_filters_cursor(client, study, engine):
    sid, _ = study
    body = {"side_a": {"kind": "train_doe", "doe_id": "nope"}, "side_b": {"kind": "train_doe", "doe_id": "nope"}, "pairing": {"mode": "by_name"}}
    r = client.post(f"{API}/studies/{sid}/equiv-checks/preview", headers=PW, json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "EQ_CHECK_INVALID" and "레시피를 선택" in r.json()["detail"]["message"]
    body["recipe"] = {"key": "sys:default"}
    pv = client.post(f"{API}/studies/{sid}/equiv-checks/preview", headers=PW, json=body).json()
    assert pv["can_run"] is False and {p["code"] for p in pv["problems"]} >= {"SIDE_NOT_FOUND", "METRIC_UNBOUND"}
    assert all(p["message"] for p in pv["problems"]) and pv["side_a"]["run_count"] == 0
    r = client.post(f"{API}/studies/{sid}/equiv-checks", headers=PW, json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "EQ_CHECK_INVALID"
    r = client.post(f"{API}/studies/{sid}/equiv-checks", headers=GW, json=body)
    assert r.status_code == 403
    body["recipe"] = {"key": str(uuid.uuid4())}
    assert client.post(f"{API}/studies/{sid}/equiv-checks/preview", headers=PW, json=body).status_code == 404
    with engine.connect() as c:
        assert c.execute(text("select count(*) from eq_checks")).scalar() == 0  # preview·실패한 create는 DB 무쓰기
    assert client.get(f"{API}/equiv-checks/{uuid.uuid4()}", headers=P).json()["detail"]["code"] == "EQ_CHECK_NOT_FOUND"
    # 이력 목록 필터·커서(행은 직접 넣어 확인 — 생성 경로는 e2e)
    with engine.begin() as c:
        for i in range(5):
            c.execute(text("insert into eq_checks(id, study_id, eq_no, recipe_source, recipe_snapshot, side_a, side_b, pairing, status, verdict,"
                           " dir_rel, created_by, created_by_name, created_at) values (:i,:s,:n,'adhoc','{\"metrics\":[]}',cast(:a as jsonb),"
                           " cast(:b as jsonb),cast(:pg as jsonb),'DONE',:v,:d,'u-power','파워', now() - make_interval(secs => :n))"),
                      {"i": str(uuid.uuid4()), "s": sid, "n": i + 1, "v": "PASS" if i % 2 else "FAIL", "d": f"05_equiv/EQ-{i + 1:03d}",
                       "pg": json.dumps({"mode": "by_name", "n_pairs": 1}),
                       "a": json.dumps({"kind": "train_doe", "ref": f"doe-{i}", "label": "A"}), "b": json.dumps({"kind": "folder", "ref": "folder", "label": "B"})})
    r = client.get(f"{API}/studies/{sid}/equiv-checks", headers=P, params={"limit": 2})
    assert [x["label"] for x in r.json()] == ["EQ-001", "EQ-002"] and r.headers.get("X-Next-Cursor")
    r2 = client.get(f"{API}/studies/{sid}/equiv-checks", headers=P, params={"limit": 2, "cursor": r.headers["X-Next-Cursor"]})
    assert [x["label"] for x in r2.json()] == ["EQ-003", "EQ-004"] and r2.headers.get("X-Next-Cursor")
    r3 = client.get(f"{API}/studies/{sid}/equiv-checks", headers=P, params={"limit": 2, "cursor": r2.headers["X-Next-Cursor"]})
    assert [x["label"] for x in r3.json()] == ["EQ-005"] and not r3.headers.get("X-Next-Cursor")
    assert len(client.get(f"{API}/studies/{sid}/equiv-checks", headers=P, params={"verdict": "PASS"}).json()) == 2
    assert [x["label"] for x in client.get(f"{API}/studies/{sid}/equiv-checks", headers=P, params={"side_ref": "doe-2"}).json()] == ["EQ-003"]
    assert len(client.get(f"{API}/studies/{sid}/equiv-checks", headers=P, params={"side_kind": "folder"}).json()) == 5
    assert client.get(f"{API}/studies/{sid}/equiv-checks", headers=P, params={"cursor": "***"}).status_code == 422
    item = r.json()[0]
    assert item["status_text"] == "완료" and item["verdict_text"] == "미달" and item["recipe"]["source"] == "adhoc"
