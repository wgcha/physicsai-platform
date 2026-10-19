"""S16 V2 조립 FEM 검증 시험 공용(phase3 §21.3): HPC·응답 TCL·커브 설정을 켠 예측 환경, READY ① DOE 조립 폴더, PBS 흉내 실행."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from physicsai_test_support import API, H, make_assem_files, pbs_command_cfg

PW, P = H("tok-power", write=True), H("tok-power")
NEW_CMD = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]
T01_CMD = ["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{curate_tcl}", "-config", "{config_json}"]
VALUES = {"THK_1": 3.0, "N_RIB": 4}
MESH_INC = "104_replace_node_elem.inc"


def spec(dt: str, comp: str, stat: str) -> dict[str, Any]:
    return {"source": "H3D", "subcase": 1, "datatype": dt, "component": comp, "layer": "", "stat": stat}


RESPS = [{"name": "MaxStress", "unit": "MPa", "spec": spec("CornerStress", "vonMises", "MAX")},
         {"name": "MinDisp", "unit": "mm", "spec": spec("Displacement", "X", "MIN")}]


def resources(tmp: Path) -> dict[str, str]:
    d = tmp / "fvres"
    d.mkdir(parents=True, exist_ok=True)
    (d / "H3D_StaticMinMax_to_CSV_FAST.tcl").write_text("# fake extract tcl\n")
    (d / "BATCHRUN_curate_hg.tcl").write_text("# fake curate tcl\n")
    return {"extract_minmax_tcl": str(d / "H3D_StaticMinMax_to_CSV_FAST.tcl"), "curate_hg_tcl": str(d / "BATCHRUN_curate_hg.tcl")}


def fv_env(predict_env: Any, fake_tools: dict[str, str], tmp_path: Path, *, hpc: dict[str, Any] | None = None,
           responses: bool = True, mesh_only: bool = False, **kw: Any) -> tuple[Any, dict[str, Any]]:
    """HPC(PBS command 흉내)·응답 TCL·T01 커브 명령을 켠 예측 환경 + 현재 템플릿(응답 정의 H3D)."""
    env = predict_env(hpc=hpc or pbs_command_cfg(fake_tools, str(tmp_path / "ai_root")),
                      commands={"response_extract": NEW_CMD, "t01_curve_export": T01_CMD}, resources=resources(tmp_path), **kw)
    ps = env.param_set()
    if responses:
        env.set_responses(ps["id"], RESPS)
    if mesh_only:
        env.to_mesh_only(ps["id"])
    return env, ps


def predict(env: Any, values: dict[str, float] | None = None) -> str:
    j = env.submit("PREDICT", {"values": dict(values or VALUES), "value_source": "manual"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    return j["id"]


def ready_doe(env: Any, label: str = "DOE-001") -> tuple[str, Path]:
    """READY ① DOE 행 + 조립 폴더(S/01_train/doe/<id>/radioss_assem) — 원본 형태(starter가 새 include를 #include)."""
    did = str(uuid.uuid4())
    rel = f"01_train/doe/{did[:8]}/radioss_assem"
    assem = env.sroot / rel
    make_assem_files(assem)
    jid = env.sql("select id from jobs where study_id=:s order by created_at limit 1", s=env.sid)[0][0]
    env.sql("insert into train_does(id, study_id, job_id, doe_label, doe_type, radioss_assem_source_path, dir_rel, assem_rel,"
            " parameters_snapshot, status, created_by, created_by_name) values (:i,:s,:j,:l,'LHS','/src',:d,:a,"
            " cast(:ps as jsonb),'READY','u-power','파워')",
            i=did, s=env.sid, j=jid, l=label, d=f"01_train/doe/{did[:8]}", a=rel,
            ps=json.dumps([{"name": "THK_1"}, {"name": "N_RIB"}]))
    return did, assem


def create(env: Any, body: dict[str, Any], expect: int = 201, headers: dict[str, str] | None = None) -> dict[str, Any]:
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications", headers=headers or PW, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def preview(env: Any, body: dict[str, Any], expect: int = 200) -> dict[str, Any]:
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications/preview", headers=PW, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def detail(env: Any, fid: str) -> dict[str, Any]:
    r = env.c.get(f"{API}/fem-verifications/{fid}", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def attempt_dir(env: Any, d: dict[str, Any], n: int = 1) -> Path:
    return env.sroot / "04_verify" / d["label"] / f"a{n}"


def run_until_hpc(env: Any, fid: str) -> dict[str, Any]:
    """(동반 예측 →) FEM_VERIFY 1~4단계 → WAITING_HPC."""
    d = detail(env, fid)
    if d["status"] == "WAITING_PREDICT":
        assert env.w.run_once_slot() == "SUCCEEDED", env.job(d["predict"]["job_id"])
        d = detail(env, fid)
    assert d["status"] == "RUNNING" and d["job"]["state"] == "QUEUED", d
    st = env.w.run_once_slot()
    assert st == "WAITING_HPC", env.job(d["job"]["id"])
    return detail(env, fid)


def finish_hpc(env: Any, fid: str, files: dict[str, bytes]) -> dict[str, Any]:
    """PBS 흉내: Q → R → (결과 쓰기) → F → 회수 → 나머지 step."""
    d = detail(env, fid)
    res = attempt_dir(env, d, d["attempt_no"]) / "result"
    env.w.poll_hpc_once()
    env.w.poll_hpc_once()
    for n, b in files.items():
        (res / n).write_bytes(b)
    env.w.poll_hpc_once()
    assert env.job(d["job"]["id"])["state"] == "COLLECTING", env.job(d["job"]["id"])
    assert env.w.run_once_collect() == "QUEUED"
    env.w.run_once_slot()
    return detail(env, fid)


RESULT_FILES = {"model0_0000.h3d": b"FEM-H3D-DATA", "model0_0000T01": b"T01", "model0_0000.out": b"x"}


def curve_json(env: Any, root: str, names: list[str]) -> None:
    """예측 쪽 curve.json(계열 이름) — 커브 짝 시험용."""
    p = env.sroot / "04_predict" / root / "curve.json"
    p.write_text(json.dumps({"series": [{"name": n, "x": [0, 1, 2], "y": [0, 1, 4]} for n in names]}), encoding="utf-8")
