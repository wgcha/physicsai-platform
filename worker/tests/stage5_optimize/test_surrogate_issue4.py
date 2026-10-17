"""V3-S13-7(이슈 #4): mesh_only 템플릿으로 원본 OPTIMIZE 생성·재시도 → 409 TEMPLATE_ASSEMBLY_REQUIRED(문구),
워커 op_prep은 경로 조합 전에 같은 코드로 실패(TypeError 없음). assembly 회귀는 test_stage5_optimize 무수정 통과."""

from __future__ import annotations

from helpers_stage1 import job, study, submit
from physicsai_test_support import API, H, make_model_folder, make_param_set_folder

PW = H("tok-power", write=True)
RESP = [{"name": "MAX_VM", "source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "",
         "stat": "MAX", "goal": "MINIMIZE"}]
MSG = "이 템플릿은 조립 폴더가 없는 쿠션 단독(메시 단독) 템플릿이라 원본 최적화를 실행할 수 없습니다"


def _setup(c, w, ai, name):
    sid = study(c, name)
    sroot = ai / name
    jid = submit(c, sid, "MODEL_REGISTER", {"model_path": str(make_model_folder(sroot / "00_inbox"))})["id"]
    assert w.run_once_light() == "SUCCEEDED"
    mid = job(c, jid)["result"]["model_id"]
    assert c.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": mid}).status_code == 200
    ps = c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(make_param_set_folder(sroot / "00_inbox"))}).json()
    return sid, ps["id"]


def _to_mesh_only(engine, ps_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("update param_sets set input_kind='mesh_only', assem_rel=null, starter_name=null where id=:i"),
                     {"i": ps_id})


def test_issue4_create_retry_and_worker_guard(p2_env, engine):
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid, psid = _setup(c, w, ai, "op4")
    j = submit(c, sid, "OPTIMIZE", {"responses": RESP, "max_designs": 2})  # assembly일 때 등록(대기 중인 옛 작업)
    _to_mesh_only(engine, psid)
    r = submit(c, sid, "OPTIMIZE", {"responses": RESP}, expect=409)
    assert r["detail"]["code"] == "TEMPLATE_ASSEMBLY_REQUIRED" and r["detail"]["message"].startswith(MSG)
    assert "플랫폼 내장(쿠션만 가능)" in r["detail"]["message"]
    # 이미 대기 중이던 옛 작업: 워커 op_prep가 경로 조합 전에 같은 코드로 실패(TypeError 아님)
    assert w.run_once_slot() == "FAILED"
    jj = job(c, j["id"])
    assert jj["failure_code"] == "TEMPLATE_ASSEMBLY_REQUIRED" and MSG in jj["failure_message"]
    assert "TypeError" not in (jj["failure_message"] or "")
    # 재시도도 같은 검사
    r = c.post(f"{API}/jobs/{j['id']}/retry", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_ASSEMBLY_REQUIRED"


def test_needs_assembly_block_units():
    from physicsai_core.stage5_optimize.optimize import needs_assembly_block

    assert needs_assembly_block({"input_kind": "mesh_only", "assem_rel": "x", "starter_name": "s"})
    assert needs_assembly_block({"input_kind": "assembly", "assem_rel": None, "starter_name": "s"})
    assert needs_assembly_block(None)
    assert not needs_assembly_block({"input_kind": "assembly", "assem_rel": "a", "starter_name": "s"})
