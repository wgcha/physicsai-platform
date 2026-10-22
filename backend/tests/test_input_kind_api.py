"""input-kind.md V-IK-1·6·9(API): 실행 단위 입력 종류(`input: assembly|cushion`)의 요청·능력·기본값·조회·MCP 요약·보고서·③ 출처.

워커 step·FEM·⑥은 `test_input_kind_flow.py`(가짜 도구 + 워커). 여기서는 워커 없이 API만 — 일괄 생성 결과는 저장소 행으로 확인한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from helpers_api import P, PW, _job
from physicsai_test_support import API
from test_api_predict_batch import TABLE, _batch, _client, _end, _gen_done, _setup
VALUES = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}


def _sql(engine, q: str, **kw):
    with engine.begin() as conn:
        r = conn.execute(text(q), kw)
        return r.all() if r.returns_rows else []


def _predict(c, engine, sid: str, body: dict):
    """단건 PREDICT 생성 — 같은 Study의 같은 종류 작업은 하나뿐이라(STUDY_JOB_BUSY) 만든 뒤 종료 처리한다."""
    r = _job(c, sid, "PREDICT", body)
    if r.status_code == 201:
        _end(engine, r.json()["id"], "SUCCEEDED")
    return r


def _code(r) -> str:
    return r.json()["detail"]["code"]


def _use_cushion_cmd(monkeypatch, on: bool = True) -> None:
    """`commands.paicad_cushion_write` 설정 여부(키는 워커 브랜치가 추가 — 여기서는 판정 함수를 고정)."""
    from physicsai_core.stage4_predict import input_kind as ik

    monkeypatch.setattr(ik, "cushion_write_configured", lambda settings: on)


# ---- V-IK-1 하위호환 --------------------------------------------------------------------------------------


def test_v_ik_1_default_matches_template_kind(settings_dict, engine, fake_dashboard, worker_factory):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0023_doe_methods"  # IK-2: migration 없음
    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = lc.settings.storage.ai_root
        sid, _mid, ps = _setup(c, worker_factory(), __import__("pathlib").Path(ai), "K1")
        assert ps["input_capability"] == ["assembly", "cushion"] and ps["input_capability_reason"] is None
        # input 없는 조립 템플릿 요청 = 변경 전과 같은 값
        r = _batch(c, sid)
        assert r.status_code == 201, r.text
        assert r.json()["params"]["template_kind"] == "assembly" and "input" not in r.json()["params"]
        bid = r.json()["params"]["batch_id"]
        b = c.get(f"{API}/predict-batches/{bid}", headers=P).json()
        assert (b["input_kind"], b["input"], b["warnings"]) == ("assembly", "assembly", [])
        assert c.get(f"{API}/studies/{sid}/predict-batches", headers=P).json()[0]["input"] == "assembly"
        pv = c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW, json={"source": {"kind": "table", "text": TABLE}})
        assert pv.status_code == 200, pv.text
        j = pv.json()
        assert (j["input_kind"], j["input"], j["input_capability"], j["input_capability_reason"]) == ("assembly", "assembly", ["assembly", "cushion"], None)
        # 단건
        r = _job(c, sid, "PREDICT", VALUES)
        assert r.status_code == 201 and r.json()["params"]["template_kind"] == "assembly"


def test_v_ik_1_mesh_only_template_defaults_to_cushion(settings_dict, engine, fake_dashboard, worker_factory):
    from pathlib import Path

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        sid, _mid, ps = _setup(c, worker_factory(), Path(lc.settings.storage.ai_root), "K2", mesh_only=True)
        assert ps["input_kind"] == "mesh_only" and ps["input_capability"] == ["cushion"]
        assert "쿠션만" in ps["input_capability_reason"]
        r = _batch(c, sid)
        assert r.status_code == 201, r.text
        assert r.json()["params"]["template_kind"] == "mesh_only"
        b = c.get(f"{API}/predict-batches/{r.json()['params']['batch_id']}", headers=P).json()
        assert (b["input_kind"], b["input"]) == ("mesh_only", "cushion")
        pv = c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW, json={"source": {"kind": "table", "text": TABLE}}).json()
        assert (pv["input_kind"], pv["input"], pv["input_capability"]) == ("mesh_only", "cushion", ["cushion"])
        r = _predict(c, engine, sid, VALUES)
        assert r.status_code == 201 and r.json()["params"]["template_kind"] == "mesh_only"
        # 명시 cushion도 같다
        r = _predict(c, engine, sid, {**VALUES, "input": "cushion"})
        assert r.status_code == 201, r.text
        assert r.json()["params"]["template_kind"] == "mesh_only"


# ---- V-IK-6 능력·오류 --------------------------------------------------------------------------------------


def test_v_ik_6_unsupported_input_is_422(settings_dict, engine, fake_dashboard, worker_factory):
    from pathlib import Path

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        sid, _mid, ps = _setup(c, worker_factory(), Path(lc.settings.storage.ai_root), "K3", mesh_only=True)
        r = _job(c, sid, "PREDICT", {**VALUES, "input": "assembly"})
        assert r.status_code == 422 and _code(r) == "INPUT_KIND_UNSUPPORTED", r.text
        d = r.json()["detail"]
        assert d["errors"][0]["loc"] == ["params", "input"] and "조립 입력을 쓸 수 없습니다" in d["message"] and "쿠션만 가능한 템플릿" in d["message"]
        assert d["input_capability"] == ["cushion"]
        r = _batch(c, sid, input="assembly")
        assert r.status_code == 422 and _code(r) == "INPUT_KIND_UNSUPPORTED"
        r = c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW, json={"source": {"kind": "table", "text": TABLE}, "input": "assembly"})
        assert r.status_code == 422 and _code(r) == "INPUT_KIND_UNSUPPORTED"
        assert not _sql(engine, "select 1 from predict_batches")  # 거부된 요청은 저장하지 않는다
        # 모르는 값은 모양 오류
        r = _job(c, sid, "PREDICT", {**VALUES, "input": "mesh_only"})
        assert r.status_code == 422 and _code(r) == "INVALID_PARAMS"


def test_v_ik_6_prepared_and_legacy_optimize_refuse_input(settings_dict, engine, fake_dashboard, worker_factory, tmp_path):
    from pathlib import Path

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        sid, _mid, _ps = _setup(c, worker_factory(), Path(lc.settings.storage.ai_root), "K4")
        r = _job(c, sid, "PREDICT", {"input_mode": "prepared", "input_path": str(tmp_path), "input": "cushion"})
        assert r.status_code == 422 and _code(r) == "INPUT_KIND_UNSUPPORTED", r.text
        assert "starter" in r.json()["detail"]["message"]
        # 레거시 OPTIMIZE: 기능 검사(commands.hst_optimization)가 이 설정에선 먼저 막으므로 prepare 단계 거부를 직접 확인한다
        from physicsai_api.services.job_params import stage5_optimize as so
        from physicsai_core.errors import DomainError

        with pytest.raises(DomainError) as ei:
            so.prepare(__import__("types").SimpleNamespace(settings=lc.settings), None, {"id": sid}, "OPTIMIZE", so.OptimizeParams(responses=[{"name": "A", "goal": "MINIMIZE"}], input="cushion"))
        assert (ei.value.code, ei.value.status) == ("INPUT_KIND_UNSUPPORTED", 422) and "HyperStudy" in ei.value.message


def test_v_ik_6_cushion_on_assembly_template_batch(settings_dict, engine, fake_dashboard, worker_factory):
    """조립 가능 템플릿 + cushion = 내부 값 mesh_only(IK-2), run 입력 위치 = m_1/EPS_mesh(`input_rel_for`)."""
    from pathlib import Path

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "K5")
        r = _batch(c, sid, input="cushion")
        assert r.status_code == 201, r.text
        assert r.json()["params"]["template_kind"] == "mesh_only"
        bid = r.json()["params"]["batch_id"]
        assert _sql(engine, "select input_kind from predict_batches where id=:i", i=bid) == [("mesh_only",)]
        assert {x[0] for x in _sql(engine, "select input_rel from predict_batch_runs where batch_id=:i", i=bid)} == {
            "run__00001/m_1/EPS_mesh_0000.rad", "run__00002/m_1/EPS_mesh_0000.rad", "run__00003/m_1/EPS_mesh_0000.rad"}
        b = c.get(f"{API}/predict-batches/{bid}", headers=P).json()
        assert (b["input_kind"], b["input"]) == ("mesh_only", "cushion")
        assert c.get(f"{API}/studies/{sid}/predict-batches", headers=P).json()[0]["input"] == "cushion"
        pv = c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW,
                    json={"source": {"kind": "table", "text": TABLE}, "input": "cushion"}).json()
        assert (pv["input_kind"], pv["input"], pv["input_capability"]) == ("mesh_only", "cushion", ["assembly", "cushion"])
        # 같은 템플릿의 조립 요청과 쿠션 요청이 한 Study에서 따로 저장된다
        _gen_done(engine, ai, "K5", bid)
        r2 = _batch(c, sid, input="assembly")
        assert r2.status_code == 201 and r2.json()["params"]["template_kind"] == "assembly"


# ---- Native 능력(IK-3) ------------------------------------------------------------------------------------


def _native_ps(engine, sid: str, ai, *, kind: str = "solid", shell_only: bool = False, prop: bool = False) -> dict:
    """native 세트 행 + 준비본 prep.json(kind·shell_only) — 능력 계산 입력만 만든다(형상 작업은 하지 않음)."""
    import json
    import uuid
    from pathlib import Path

    pid, rel = str(uuid.uuid4()), None
    rel = f"04_params/{pid}"
    folder = Path(ai) / "KN" / rel / "native"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "prep.json").write_text(json.dumps({"kind": kind, **({"shell_only": True} if shell_only else {})}))
    params = [{"name": "A_THK_1", "nominal": 3.0, "min": 2.0, "max": 4.0, "unit": "mm"}]
    if prop:
        params.append({"name": "T_5", "nominal": 1.0, "min": 0.8, "max": 1.2, "unit": "mm", "source": "prop", "prop_id": 5})
    with engine.begin() as conn:
        conn.execute(text(
            "insert into param_sets(id, study_id, source_path, stored_rel, parameters, responses, sample_count, sample_has_measured,"
            " cad_file_name, assem_rel, starter_name, tpl_params, registered_by, registered_by_name, engine)"
            " values (:i,:s,'/x',:r,cast(:p as jsonb),cast('[]' as jsonb),0,false,'a.step',:a,'s.rad',cast('[]' as jsonb),'u','u','native')"),
            {"i": pid, "s": sid, "r": rel, "p": json.dumps(params), "a": f"{rel}/radioss_assem/"})
    return {"id": pid}


def test_v_ik_6_native_capability_and_cushion_command(settings_dict, engine, fake_dashboard, worker_factory, monkeypatch):
    from pathlib import Path

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "KN")
        solid = _native_ps(engine, sid, ai)
        shell = _native_ps(engine, sid, ai, kind="shell")
        prop = _native_ps(engine, sid, ai, prop=True)
        thick = _native_ps(engine, sid, ai, shell_only=True)

        def cap(ps_id):
            j = c.get(f"{API}/param-sets/{ps_id}", headers=P).json()
            return j["input_capability"], j["input_capability_reason"]

        _use_cushion_cmd(monkeypatch, False)  # commands.paicad_cushion_write = null
        assert cap(solid["id"]) == (["assembly"], "관리자 설정 필요: commands.paicad_cushion_write")
        _use_cushion_cmd(monkeypatch, True)
        assert cap(solid["id"]) == (["assembly", "cushion"], None)
        assert cap(shell["id"])[0] == ["assembly"] and "쿠션 바디가 없습니다" in cap(shell["id"])[1]
        assert cap(thick["id"])[0] == ["assembly"] and "쿠션 바디가 없습니다" in cap(thick["id"])[1]
        assert cap(prop["id"]) == (["assembly"], "쉘 두께 값이 있는 템플릿은 조립 입력만")
        lst = {x["id"]: x["input_capability"] for x in c.get(f"{API}/studies/{sid}/param-sets", headers=P).json()}
        assert lst[solid["id"]] == ["assembly", "cushion"] and lst[shell["id"]] == ["assembly"]
        # 요청 검사: 쉘·쉘 두께 세트 + cushion = 422(준비·모델 검사보다 먼저 — 능력이 문제)
        for ps in (shell, prop):
            r = _job(c, sid, "PREDICT", {**VALUES, "param_set_id": ps["id"], "input": "cushion"})
            assert r.status_code == 422 and _code(r) == "INPUT_KIND_UNSUPPORTED", r.text
        r = c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW,
                   json={"param_set_id": shell["id"], "source": {"kind": "lhs", "count": 3}, "input": "cushion"})
        assert r.status_code == 422 and _code(r) == "INPUT_KIND_UNSUPPORTED"
        # 명령이 없으면 solid + cushion = 409 TEMPLATE_NOT_CONFIGURED(능력 사유와 같은 문구), assembly·생략은 영향 없음
        _use_cushion_cmd(monkeypatch, False)
        r = _job(c, sid, "PREDICT", {**VALUES, "param_set_id": solid["id"], "input": "cushion"})
        assert r.status_code == 409 and _code(r) == "TEMPLATE_NOT_CONFIGURED", r.text
        assert "commands.paicad_cushion_write" in r.json()["detail"]["message"]
        r = c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW,
                   json={"param_set_id": solid["id"], "source": {"kind": "lhs", "count": 3}, "input": "cushion"})
        assert r.status_code == 409 and _code(r) == "TEMPLATE_NOT_CONFIGURED"


def test_v_ik_6_native_cushion_recorded_when_configured(settings_dict, engine, fake_dashboard, worker_factory, monkeypatch):
    """명령이 있으면 Native solid의 cushion 요청이 template_kind mesh_only로 기록된다(준비본 검사는 이 시험에서 통과 처리)."""
    from pathlib import Path

    from physicsai_api.services.job_params import stage4_predict as sp

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        sid, _mid, _ps = _setup(c, worker_factory(), Path(lc.settings.storage.ai_root), "KN2")
        solid = _native_ps(engine, sid, lc.settings.storage.ai_root)
        _use_cushion_cmd(monkeypatch, True)
        monkeypatch.setattr(sp, "native_set_gate", lambda ctx, ps: None)
        monkeypatch.setattr(sp, "check_engine_match", lambda ps, m: [])
        body = {"values": {"A_THK_1": 3.0}, "value_source": "manual", "param_set_id": solid["id"]}
        r = _predict(c, engine, sid, {**body, "input": "cushion"})
        assert r.status_code == 201, r.text
        assert r.json()["params"]["template_kind"] == "mesh_only" and r.json()["params"]["engine"] == "native"
        r = _predict(c, engine, sid, body)
        assert r.status_code == 201 and r.json()["params"]["template_kind"] == "assembly"


# ---- V-IK-9 표시 ------------------------------------------------------------------------------------------


def test_v_ik_9_single_run_input_and_warning(settings_dict, engine, fake_dashboard, worker_factory):
    from pathlib import Path

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        sid, _mid, _ps = _setup(c, worker_factory(), Path(lc.settings.storage.ai_root), "K6")
        a = _predict(c, engine, sid, VALUES).json()["id"]
        k = _predict(c, engine, sid, {**VALUES, "input": "cushion"}).json()["id"]
        table = [{"name": "MaxStress", "unit": "MPa", "predicted": 150.0}, {"name": "Disp", "unit": "mm", "predicted": None}]
        for jid, extra in ((a, {}), (k, {"predict_input": {"input": "cushion", "starter": "EPS_mesh_0000.rad", "bytes": 10, "files": 1}})):
            _end(engine, jid, "SUCCEEDED", {"response_table": table, **extra})
        runs = {x["job_id"]: x for x in c.get(f"{API}/studies/{sid}/predict-runs", headers=P).json()}
        assert runs[a]["input"] == "assembly" and runs[k]["input"] == "cushion"
        da, dk = (c.get(f"{API}/predict-runs/{x}", headers=P).json() for x in (a, k))
        assert da["input_warnings"] == [] and da["predict_input"] is None  # 조립은 값이 없어도 경고하지 않는다
        assert dk["predict_input"] == {"input": "cushion", "starter": "EPS_mesh_0000.rad", "bytes": 10, "files": 1}
        w = dk["input_warnings"]  # 값이 없는 응답만(Disp), 차단 없음
        assert len(w) == 1 and w[0]["code"] == "INPUT_CUSHION_RESPONSES" and "Disp" in w[0]["message"] and "MaxStress" not in w[0]["message"]
        # prepared: starter가 eps_mesh면 cushion
        pj = _predict(c, engine, sid, VALUES).json()["id"]
        _sql(engine, "update jobs set params = params || cast('{\"input_mode\": \"prepared\", \"input_kind\": \"file\", \"starter_name\": \"EPS_mesh_0000.rad\"}' as jsonb) where id=:i", i=pj)
        _end(engine, pj, "SUCCEEDED", {"starter": "EPS_mesh_0000.rad"})
        assert {x["job_id"]: x for x in c.get(f"{API}/studies/{sid}/predict-runs", headers=P).json()}[pj]["input"] == "cushion"


def test_v_ik_9_batch_warning_only_when_cushion_has_no_values(settings_dict, engine, fake_dashboard, worker_factory):
    from pathlib import Path

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, ps = _setup(c, worker_factory(), ai, "K7")
        assert c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": [
            {"name": "MaxStress", "unit": "MPa", "spec": None}, {"name": "Disp", "unit": "mm", "spec": None}]}).status_code == 200
        out = {}
        for kind in ("assembly", "cushion"):
            bid = _batch(c, sid, input=kind).json()["params"]["batch_id"]
            kids = _gen_done(engine, ai, "K7", bid)
            assert c.get(f"{API}/predict-batches/{bid}", headers=P).json()["warnings"] == []  # 성공 run이 없으면 경고하지 않는다
            for kid in kids:
                _end(engine, kid["id"], "SUCCEEDED", {"response_table": [{"name": "MaxStress", "unit": "MPa", "predicted": 100.0}]})
            _sql(engine, "update predict_batch_runs set responses = cast('{\"MaxStress\": 100.0}' as jsonb) where batch_id=:b", b=bid)
            out[kind] = c.get(f"{API}/predict-batches/{bid}", headers=P).json()["warnings"]
            _sql(engine, "update predict_batches set status='DONE' where id=:b", b=bid)
        assert out["assembly"] == []
        assert len(out["cushion"]) == 1 and out["cushion"][0]["code"] == "INPUT_CUSHION_RESPONSES"
        assert "Disp" in out["cushion"][0]["message"] and "MaxStress" not in out["cushion"][0]["message"]


def test_v_ik_9_html_report_shows_run_input(settings_dict, engine, fake_dashboard, worker_factory):
    from pathlib import Path

    from test_design_map_api import _finish

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "K8")
        texts = {}
        for kind in ("cushion", "assembly"):
            bid = _batch(c, sid, {"kind": "table", "text": "THK_1,N_RIB\n3.0,4\n2.5,5\n"}, input=kind).json()["params"]["batch_id"]
            for k in _gen_done(engine, ai, "K8", bid):
                _finish(engine, ai, "K8", sid, k, resp_text="RESP:MaxStress_MAX=1.0\n", table=[{"name": "MaxStress", "unit": "MPa", "predicted": 1.0}])
            r = c.get(f"{API}/reports/analysis", headers=P, params={"source": "batch", "id": bid})
            assert r.status_code == 200, r.text
            texts[kind] = r.text
        assert "입력: 쿠션" in texts["cushion"] and "입력: 조립" not in texts["cushion"]
        assert "입력: 조립" in texts["assembly"] and "입력: 쿠션" not in texts["assembly"]
        assert "메시 단독" not in texts["cushion"] and "조립 폴더" not in texts["assembly"]  # 옛 표기 대체


def test_v_ik_9_report_text_helper():
    from physicsai_core.report_html.common import param_set_text

    assert param_set_text({"label": "T", "input": "cushion", "input_kind": "assembly"}) == "T · 입력: 쿠션"  # 실행 값 우선
    assert param_set_text({"label": "T", "input_kind": "mesh_only"}) == "T · 입력: 쿠션"  # 값이 없으면 템플릿 값
    assert param_set_text({"label": "T", "input_kind": "assembly"}) == "T · 입력: 조립" and param_set_text({"label": "T"}) == "T"


def test_v_ik_9_dataset_source_doe(settings_dict, engine, fake_dashboard, worker_factory):
    """③ 데이터셋 출처 표시용 `source_doe`(P3): 입력 폴더가 ① DOE 결과면 라벨, 외부 폴더면 null — 판정은 `dataset_engine._doe_ids`."""
    import uuid
    from pathlib import Path

    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "K9")
        job = _sql(engine, "select id from jobs where study_id=:s order by created_at limit 1", s=sid)[0][0]
        d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
        for did, label in ((d1, "D-001"), (d2, "D-002")):
            _sql(engine, "insert into train_does(id, study_id, job_id, doe_label, doe_type, radioss_assem_source_path, dir_rel, assem_rel,"
                         " parameters_snapshot, status, created_by, created_by_name) values (:i,:s,:j,:l,'LHS','/src',:d,:a,"
                         " cast('[]' as jsonb),'READY','u-power','파워')", i=did, s=sid, j=job, l=label, d=f"01_train/doe/{did[:8]}",
                 a=f"01_train/doe/{did[:8]}/radioss_assem")
        sources = {"one": f"{ai}/K9/01_train/results/{d1}", "all": f"{ai}/K9/01_train/results", "ext": str(ai / "elsewhere" / "h3d")}
        for k, src in sources.items():
            _sql(engine, "insert into datasets(id, study_id, job_id, status, source_path, holdout_ratio, seed, split_group, options_json,"
                         " created_by, created_by_name) values (:i,:s,:j,'READY',:p,0.2,1,'file',cast('{}' as jsonb),'u-power','파워')",
                 i=f"ds-{k}", s=sid, j=job, p=src)
        got = {x["id"]: x["source_doe"] for x in c.get(f"{API}/studies/{sid}/datasets", headers=P).json()}
        assert got["ds-one"] == {"doe_ids": [d1], "label": "① DOE D-001(조립)"}
        assert got["ds-all"]["label"] == "① DOE 여러 개(조립)" and sorted(got["ds-all"]["doe_ids"]) == sorted([d1, d2])
        assert got["ds-ext"] is None
        assert c.get(f"{API}/datasets/ds-one", headers=P).json()["source_doe"]["label"] == "① DOE D-001(조립)"
        assert c.get(f"{API}/datasets/ds-ext", headers=P).json()["source_doe"] is None


@pytest.mark.parametrize("path", ["/mcp/connection"])
def test_connection_route_is_session_only_and_excluded_from_tools(path):
    """x-mcp exclude(session_only) — 도구 목록에 없다. (자세한 동작은 test_mcp_connection.py)"""
    from physicsai_api.export_openapi import build_openapi

    op = build_openapi()["paths"][f"/physicsai/api{path}"]["get"]
    assert op["x-mcp"]["exclude"] and op["x-mcp"]["session_only"] is True
