"""input-kind.md V-IK-2·7·8(API + 기존 워커, 가짜 도구): 조립 가능 템플릿의 쿠션 입력 실행·⑥ 쿠션 입력·FEM 검증 조립 원본.

워커 코드는 이 브랜치에서 바꾸지 않는다 — 기존 워커가 `params.template_kind=mesh_only`·`assem_ref.path`를 이미 그대로 쓰는 것으로 API 쪽 계약을 확인한다.
워커 쪽 fixture(`predict_env`)·FEM 시험 도우미(`fv_support`)는 읽기 전용으로 불러 쓴다(test_surrogate_flow.py와 같은 방식).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from physicsai_test_support import API, H

_W = Path(__file__).resolve().parents[2] / "worker" / "tests" / "stage4_predict"


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _W / file)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_conf = _load("_ik_s4_conftest", "conftest.py")
predict_env = _conf.predict_env
pbs_state = _conf.pbs_state
fv = _load("_ik_fv_support", "fv_support.py")

PW = H("tok-power", write=True)
P = H("tok-power")
MESH = "EPS_mesh_0000.rad"
VALUES = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}
TCL_NAME = "H3D_StaticMinMax_to_CSV_FAST.tcl"
RESP = [{"name": "MaxStress", "unit": "MPa",
         "spec": {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}},
        {"name": "Disp", "unit": "mm", "spec": None}]


@pytest.fixture(autouse=True)
def _fast_collect(monkeypatch, pbs_state):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)


def _predict(env: Any, **extra: Any) -> str:
    j = env.submit("PREDICT", {**VALUES, **extra})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    return j["id"]


# ---- V-IK-2 단건 ------------------------------------------------------------------------------------------


def test_v_ik_2_cushion_on_assembly_template_single(predict_env):
    env = predict_env()
    ps = env.param_set()  # 조립 가능 템플릿(조립 폴더 있음)
    assert ps["input_capability"] == ["assembly", "cushion"]
    a = _predict(env)
    k = _predict(env, input="cushion")
    # 조립(기본) = 변경 전과 같음: MESH 실행·INPUT 여러 파일
    assert env.steps(a)["MESH"]["state"] != "SKIPPED" and len(os.listdir(env.predict_dir(a) / "INPUT")) > 1
    assert env.job(a)["params"]["template_kind"] == "assembly"
    # 쿠션 = mesh_only 템플릿과 같은 체인: MESH SKIPPED, INPUT = 쿠션 rad 하나
    jd = env.job(k)
    assert jd["params"]["template_kind"] == "mesh_only" and jd["result"]["template_kind"] == "mesh_only"
    assert env.steps(k)["MESH"]["state"] == "SKIPPED"
    assert os.listdir(env.predict_dir(k) / "INPUT") == [MESH] and jd["result"]["starter"] == MESH
    runs = {x["job_id"]: x for x in env.c.get(f"{API}/studies/{env.sid}/predict-runs", headers=P).json()}
    assert (runs[a]["input"], runs[k]["input"]) == ("assembly", "cushion")
    # 같은 템플릿·같은 값이라도 입력 종류가 다르면 서로 다른 실행(파라미터 세트는 그대로, 마이그레이션 없음)
    assert env.sql("select input_kind from param_sets where id=:i", i=ps["id"])[0][0] == "assembly"


def test_v_ik_2_cushion_batch_runs_one_file_each(predict_env):
    env = predict_env()
    ps = env.param_set()
    pj = env.submit("PREDICT_BATCH", {"param_set_id": ps["id"], "multi_execution": 2, "input": "cushion",
                                      "source": {"kind": "table", "text": "THK_1,N_RIB\n2.5,3\n3.5,5\n"}})
    bid = pj["params"]["batch_id"]
    assert pj["params"]["template_kind"] == "mesh_only"
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj["id"])
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert (b["input_kind"], b["input"]) == ("mesh_only", "cushion")
    kids = [x["job_id"] for x in b["rows"]]
    assert len(kids) == 2
    for cid in kids:
        assert env.w.run_once_slot() == "SUCCEEDED", env.job(cid)
        assert env.steps(cid)["MESH"]["state"] == "SKIPPED"
        assert os.listdir(env.predict_dir(cid) / "INPUT") == [MESH]
    assert env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()["status"] == "DONE"


# ---- V-IK-7 ⑥ ---------------------------------------------------------------------------------------------


@pytest.fixture()
def so_env(predict_env, tmp_path):
    tcl = tmp_path / "res" / TCL_NAME
    tcl.parent.mkdir(parents=True)
    tcl.write_text("# fake\n")
    env = predict_env(commands={"response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]},
                      resources={"extract_minmax_tcl": str(tcl)})
    ps = env.param_set()
    r = env.c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": RESP})
    assert r.status_code == 200, r.text
    env.ps = ps  # type: ignore[attr-defined]
    return env


def _so_body(**kw: Any) -> dict[str, Any]:
    b = {"explore": {"kind": "new", "count": 6, "seed": 1}, "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"},
         "iterations": 1, "candidates": 2, "tol_rel": 1e-6, "seed": 1, "multi_execution": 2}
    b.update(kw)
    return b


def test_v_ik_7_surrogate_opt_cushion_input(so_env):
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    env = so_env
    base = f"{API}/studies/{env.sid}/surrogate-opts"
    # 미리보기: 입력 종류·능력·노트(탐색 신규 = 값 확인 전이라 노트 없음)
    pv = env.c.post(f"{base}/preview", headers=PW, json=_so_body(input="cushion")).json()
    assert (pv["input"], pv["input_capability"], pv["notes"]) == ("cushion", ["assembly", "cushion"], [])
    assert env.c.post(f"{base}/preview", headers=PW, json=_so_body()).json()["input"] == "assembly"
    r = env.c.post(base, headers=PW, json=_so_body(input="cushion"))
    assert r.status_code == 201, r.text
    opt = r.json()
    assert opt["input"] == "cushion"
    assert env.sql("select input_kind from surrogate_opts where id=:i", i=opt["id"])[0][0] == "mesh_only"
    # 소유 배치·하위 예측도 쿠션 입력
    assert env.sql("select input_kind from predict_batches")[0][0] == "mesh_only"
    pj = env.sql("select params from jobs where job_type='PREDICT_BATCH' order by created_at limit 1")[0][0]
    assert pj["template_kind"] == "mesh_only"
    # 진행 중 목록·상세 `input`
    assert env.c.get(base, headers=P).json()[0]["input"] == "cushion"
    d = env.c.get(f"{API}/surrogate-opts/{opt['id']}", headers=P).json()
    assert d["input"] == "cushion" and d["warnings"] == []  # 성공 run이 없으면 경고하지 않는다
    # 첫 탐색 하위 예측 하나를 실제로 돌려 쿠션 입력(rad 하나)인지 확인
    assert env.w.run_once_slot() == "SUCCEEDED"  # 탐색 배치 부모
    assert env.w.run_once_slot() == "SUCCEEDED"
    kid = env.sql("select id from jobs where job_type='PREDICT' and state='SUCCEEDED' limit 1")[0][0]
    assert os.listdir(env.predict_dir(kid) / "INPUT") == [MESH]


def test_v_ik_7_unsupported_for_surrogate_opt(predict_env):
    env = predict_env()
    ps = env.param_set()
    env.to_mesh_only(ps["id"])
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW,
                   json=_so_body(input="assembly"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INPUT_KIND_UNSUPPORTED"
    ok = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=_so_body())
    assert ok.status_code == 200 and ok.json()["input"] == "cushion" and ok.json()["input_capability"] == ["cushion"]


# ---- V-IK-8 FEM 검증 --------------------------------------------------------------------------------------


def test_v_ik_8_fem_cushion_source_defaults_to_template_assembly(predict_env, fake_tools, tmp_path):
    env, ps = fv.fv_env(predict_env, fake_tools, tmp_path)  # 조립 가능 템플릿
    pj_k = _predict(env, input="cushion")
    pv = fv.preview(env, {"source": {"kind": "predict_job", "job_id": pj_k}})
    assert pv["problems"] == [] and pv["input_mode"] == "rebuild" and pv["assembly"]["kind"] == "TEMPLATE"
    assert pv["assembly"]["label"] == "템플릿 조립 폴더" and pv["assembly"]["path"].endswith("radioss_assem")
    assert pv["design"]["input"] == "cushion"
    # predict_input(쿠션 INPUT)은 쓸 수 없고, DOE를 고르면 그대로 DOE
    bad = fv.preview(env, {"source": {"kind": "predict_job", "job_id": pj_k}, "assembly": {"kind": "predict_input"}})
    assert [x["code"] for x in bad["problems"]] == ["INPUT_MESH_ONLY"]
    did, _a = fv.ready_doe(env)
    pv = fv.preview(env, {"source": {"kind": "predict_job", "job_id": pj_k}, "assembly": {"kind": "train_doe", "doe_id": did}})
    assert pv["problems"] == [] and pv["assembly"]["kind"] == "TRAIN_DOE"
    # 생성: 저장은 CUSTOM + template_id(DB CHECK 불변), 응답은 TEMPLATE
    d = fv.create(env, {"source": {"kind": "predict_job", "job_id": pj_k}})
    assert d["assembly"]["kind"] == "TEMPLATE" and d["design"]["input"] == "cushion"
    row = env.sql("select assem_kind, assem_ref from fem_verifications where id=:i", i=d["id"])[0]
    assert row[0] == "CUSTOM" and row[1]["template_id"] == ps["id"] and row[1]["path"].endswith("radioss_assem")
    # 기존 워커가 그 폴더로 재조립 → HPC 대기까지(CUSTOM 경로 재검사 포함)
    d = fv.run_until_hpc(env, d["id"])
    assert d["assembly"]["kind"] == "TEMPLATE"
    A = fv.attempt_dir(env, d)
    assert (A / "input").is_dir() and fv.MESH_INC in os.listdir(A / "input")
    assert "starter" in env.job(d["job"]["id"])["result"]
    assert env.job(d["job"]["id"])["result"]["fv_rel"].endswith("04_verify/FV-001/a1")


def test_v_ik_8_fem_assembly_run_keeps_predict_input_default(predict_env, fake_tools, tmp_path):
    env, ps = fv.fv_env(predict_env, fake_tools, tmp_path)
    pj = _predict(env)
    pv = fv.preview(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert pv["problems"] == [] and pv["input_mode"] == "reuse" and pv["assembly"]["kind"] == "PREDICT_INPUT"
    assert pv["design"]["input"] == "assembly"


def test_v_ik_8_fem_mesh_only_template_keeps_doe_default(predict_env, fake_tools, tmp_path):
    env, ps = fv.fv_env(predict_env, fake_tools, tmp_path, mesh_only=True)
    pj = fv.predict(env)
    did, _a = fv.ready_doe(env)
    pv = fv.preview(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert pv["assembly"]["kind"] == "TRAIN_DOE" and pv["design"]["input"] == "cushion"
    # template 지정은 쓸 수 없다(조립 폴더 없음)
    bad = fv.preview(env, {"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "template"}})
    assert [x["code"] for x in bad["problems"]] == ["TEMPLATE_ASSEMBLY_MISSING"] and did


def test_v_ik_8_fem_values_source_companion_inherits_input(predict_env, fake_tools, tmp_path):
    env, ps = fv.fv_env(predict_env, fake_tools, tmp_path)
    pj_a = fv.predict(env)  # 같은 값의 조립 예측이 이미 있다
    src = {"kind": "values", "param_set_id": ps["id"], "values": fv.VALUES}
    # 입력 종류가 다르면 같은 설계점이어도 재사용하지 않고 쿠션 동반 예측을 만든다
    d = fv.create(env, {"source": {**src, "input": "cushion"}})
    assert d["status"] == "WAITING_PREDICT" and d["predict"]["companion"] is True and d["predict"]["job_id"] != pj_a
    assert d["design"]["input"] == "cushion" and d["assembly"]["kind"] == "TEMPLATE"
    cj = env.job(d["predict"]["job_id"])
    assert cj["params"]["template_kind"] == "mesh_only" and cj["params"]["fem_verify_id"] == d["id"]
    # 같은 입력 종류(생략 = 조립)는 기존 예측을 재사용
    env.lc.settings.fem_verify.max_active = 4
    r = fv.preview(env, {"source": src})
    assert r["predict"]["job_id"] == pj_a and r["design"]["input"] == "assembly"
    # 능력 밖(쿠션만 가능한 템플릿 + assembly) → 422 INPUT_KIND_UNSUPPORTED
    env.to_mesh_only(ps["id"])
    resp = env.c.post(f"{API}/studies/{env.sid}/fem-verifications/preview", headers=PW, json={"source": {**src, "input": "assembly"}})
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "INPUT_KIND_UNSUPPORTED"
