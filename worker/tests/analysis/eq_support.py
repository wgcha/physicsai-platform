"""equiv-check.md 시험 공용: 응답 TCL·T01 곡선 명령을 켠 예측 환경 + 4종 결과 집합(train_doe·predict_batch·fem_verify·folder) 흉내 자료.

파일은 Study 폴더 안에 직접 만들고 DB 행은 SQL로 넣는다(원본 run 폴더는 시험이 mtime·내용 스냅숏으로 불변을 확인한다)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from physicsai_test_support import API, H

from ..stage4_predict.fv_support import NEW_CMD, T01_CMD, resources

PW, P = H("tok-power", write=True), H("tok-power")
MESH_INC = "104_replace_node_elem.inc"
MESH_TEXT = ("/NODE\n1 0 0 0\n2 1 0 0\n3 0 1 0\n4 0 0 1\n5 1 1 0\n6 1 0 1\n7 0 1 1\n8 1 1 1\n"
             "/TETRA4/10\n1 1 2 3 4\n/BRICK/10\n2 1 2 5 3 4 6 8 7\n")  # 부피 1 + 1/6


def spec(dt: str, comp: str, stat: str) -> dict[str, Any]:
    return {"source": "H3D", "subcase": 1, "datatype": dt, "component": comp, "layer": "", "stat": stat}


RESPS = [{"name": "MaxStress", "unit": "MPa", "spec": spec("CornerStress", "vonMises", "MAX")},
         {"name": "MinDisp", "unit": "mm", "spec": spec("Displacement", "X", "MIN")},
         {"name": "AccPeak", "unit": "g", "spec": {"source": "CURVE", "series": None, "stat": "ABSMAX"}}]


def recipe_def(*, required_stress: bool = True, volume: bool = True, nrmse: bool = False) -> dict[str, Any]:
    mets = [{"id": "stress_peak", "label": "응력 피크", "kind": "scalar", "source": {"type": "perf", "perf": "MaxStress"},
             "tol": {"rel_pct": 5.0, "abs": None}, "required": required_stress},
            {"id": "disp_min", "label": "변위 최소", "kind": "scalar", "source": {"type": "perf", "perf": "MinDisp"},
             "tol": {"rel_pct": 5.0, "abs": 1.0}, "required": True},
            {"id": "acc_corr", "label": "가속도 곡선 상관", "kind": "curve_corr", "source": {"type": "curve", "series": None, "t01": None},
             "tol": {"corr_min": 0.95}, "required": True}]
    if nrmse:
        mets.append({"id": "acc_nrmse", "label": "가속도 NRMSE", "kind": "curve_nrmse", "source": {"type": "curve", "series": None, "t01": None},
                     "tol": {"nrmse_max_pct": 5.0}, "required": False})
    if volume:
        mets.append({"id": "volume_diff", "label": "쿠션 부피 차", "kind": "mesh_volume",
                     "source": {"type": "mesh_volume", "parts": "cushion", "origin": "mesh"}, "tol": {"rel_pct": 0.1, "abs": None}, "required": True})
    return {"schema_version": 1, "metrics": mets, "pair_rule": {"mode": "all"}, "verdict_rule": "required_all"}


def eq_env(predict_env: Any, fake_tools: dict[str, str], tmp_path: Path, **kw: Any) -> tuple[Any, dict[str, Any]]:
    env = predict_env(commands={"response_extract": NEW_CMD, "t01_curve_export": T01_CMD}, resources=resources(tmp_path), **kw)
    ps = env.param_set()
    env.set_responses(ps["id"], RESPS)
    return env, ps


def _first_job(env: Any) -> str:
    return env.sql("select id from jobs where study_id=:s order by created_at limit 1", s=env.sid)[0][0]


def _h3d(path: Path, seed: int) -> None:
    path.write_bytes(b"H3D" + bytes([seed % 7]) * (10 + seed))  # 바이트 수 % 7이 가짜 hw 값에 섞인다 — 같은 길이면 같은 값


def make_train_doe(env: Any, *, runs: int = 3, label: str = "DOE-001", h3d_seed: int = 0, with_t01: bool = True,
                   collected: bool = True, pre_extracted: bool = False) -> str:
    """READY ① DOE + run 폴더(01_train/results/<doe>/run__N/{model_0000.h3d, model_0000T01}) + 입력 폴더 메시 include + samples.csv.
    pre_extracted=True면 run 폴더에 RESPS와 같은 요청의 H3D_REQUESTS.txt·RESPONSES.txt를 미리 둔다(재사용 → 추출 0회)."""
    did = str(uuid.uuid4())
    D = env.sroot / "01_train" / "doe" / did
    D.mkdir(parents=True)
    names = [f"run__{i:05d}" for i in range(1, runs + 1)]
    lines = ["run_key,THK_1,N_RIB"] + [f"{n},{2.0 + i * 0.5},{2 + i}" for i, n in enumerate(names)]
    (D / "samples.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env.sql("insert into train_does(id, study_id, job_id, doe_label, doe_type, radioss_assem_source_path, dir_rel, assem_rel,"
            " parameters_snapshot, status, sample_status, samples_rel, created_by, created_by_name) values (:i,:s,:j,:l,'LHS','/src',:d,:a,"
            " cast(:ps as jsonb),'READY','PARSED',:sr,'u-power','파워')",
            i=did, s=env.sid, j=_first_job(env), l=label, d=f"01_train/doe/{did}/", a=f"01_train/radioss_assem/{did}/",
            ps=json.dumps([{"name": "THK_1", "min": 2.0, "max": 5.0}, {"name": "N_RIB", "min": 2, "max": 8, "format": "%3i"}]),
            sr=f"01_train/doe/{did}/samples.csv")
    for i, n in enumerate(names):
        R = env.sroot / "01_train" / "results" / did / n
        R.mkdir(parents=True)
        _h3d(R / "model_0000.h3d", h3d_seed + i)
        if with_t01:
            (R / "model_0000T01").write_bytes(b"T01")
        if pre_extracted:
            from physicsai_core.stage4_predict import responses as resp_mod

            reqs, _ = resp_mod.build_requests(RESPS)
            resp_mod.write_requests(str(R), reqs)
            out = ["# fake"] + [f"RESP:{q.name}_MIN={-(1.5 + k):20.10e}\nRESP:{q.name}_MAX={100.0 + 10 * k:20.10e}" for k, q in enumerate(reqs)]
            (R / "RESPONSES.txt").write_text("\n".join(out) + "\n")
        inp = env.sroot / "01_train" / "doe" / did / "approaches" / "doe_1" / n
        inp.mkdir(parents=True)
        (inp / MESH_INC).write_text(MESH_TEXT)
        (inp / "model_0000.rad").write_text(f"#include {MESH_INC}\n")
        env.sql("insert into train_runs(id, doe_id, run_key, input_rel, starter_name, state, result_rel) values (:i,:d,:k,:ir,'model_0000.rad',:st,:rr)",
                i=str(uuid.uuid4()), d=did, k=n, ir=f"01_train/doe/{did}/approaches/doe_1/{n}", st="COLLECTED" if collected or i else "SOLVE_FAILED",
                rr=f"01_train/results/{did}/{n}")
    return did


def make_predict_batch(env: Any, ps_id: str, *, runs: int = 3, h3d_seed: int = 0, curve_scale: float = 1.0,
                       names: list[str] | None = None, values: list[dict[str, float]] | None = None) -> str:
    """DONE ④ 배치 + run마다 성공한 PREDICT 작업(result.pred_h3d_rel·curve_artifact_id)·P/RESULT h3d·curve.json·run 폴더 m_3 메시."""
    bid = str(uuid.uuid4())
    no = int(env.sql("select coalesce(max(batch_no),0)+1 from predict_batches where study_id=:s", s=env.sid)[0][0])
    names = names or [f"run__{i:05d}" for i in range(1, runs + 1)]
    pj = str(uuid.uuid4())
    env.sql("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params, created_by, created_by_name)"
            " values (:i,:s,'p-1','PREDICT_BATCH',4,'CPU','SUCCEEDED',false,null,cast(:p as jsonb),'u-power','파워')",
            i=pj, s=env.sid, p=json.dumps({"batch_id": bid, "batch_no": no}))
    env.sql("insert into predict_batches(id, study_id, batch_no, job_id, param_set_id, model_id, input_kind, source_kind, run_count, dir_rel,"
            " status, created_by, created_by_name, finished_at) values (:i,:s,:n,:j,:ps,:m,'assembly','TABLE',:rc,:d,'DONE','u-power','파워',now())",
            i=bid, s=env.sid, n=no, j=pj, ps=ps_id, m=env.model_id, rc=len(names), d=f"04_batch/B-{no:03d}")
    B = env.sroot / "04_batch" / f"B-{no:03d}"
    for i, n in enumerate(names):
        jid = str(uuid.uuid4())
        P_ = env.sroot / "04_predict" / jid
        (P_ / "RESULT").mkdir(parents=True)
        _h3d(P_ / "RESULT" / f"{n}_pred.h3d", h3d_seed + i)
        curve = {"series": [{"name": "Acc", "x": [0, 1, 2, 3], "y": [0, 1 * curve_scale, 4 * curve_scale, 9 * curve_scale]}]}
        (P_ / "curve.json").write_text(json.dumps(curve))
        aid = str(uuid.uuid4())
        env.sql("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params, result, created_by,"
                " created_by_name) values (:i,:s,'p-1','PREDICT',4,'CPU','SUCCEEDED',false,null,cast(:p as jsonb),cast(:r as jsonb),'u-power','파워')",
                i=jid, s=env.sid, p=json.dumps({"batch_run": {"batch_id": bid, "batch_no": no, "doe_no": i + 1}}),
                r=json.dumps({"pred_h3d_rel": f"04_predict/{jid}/RESULT/{n}_pred.h3d", "curve_artifact_id": aid, "param_set_id": ps_id}))
        env.sql("insert into artifacts(id, study_id, job_id, kind, rel_path, size, content_type) values (:i,:s,:j,'CURVE_JSON',:r,10,'application/json')",
                i=aid, s=env.sid, j=jid, r=f"04_predict/{jid}/curve.json")
        v = (values[i] if values else {"THK_1": 2.0 + i * 0.5, "N_RIB": 2 + i})
        env.sql("insert into predict_batch_runs(batch_id, doe_no, run_key, values, applied_values, gen_state, input_rel, predict_job_id)"
                " values (:b,:n,:k,cast(:v as jsonb),cast(:v as jsonb),'DONE',:ir,:j)", b=bid, n=i + 1, k=n, v=json.dumps(v), ir=f"{n}/m_3", j=jid)
        m3 = B / n / "m_3"
        m3.mkdir(parents=True)
        (m3 / MESH_INC).write_text(MESH_TEXT)
    return bid


def make_fem_verify(env: Any, ps_id: str, *, h3d_seed: int = 0) -> str:
    fid = str(uuid.uuid4())
    no = int(env.sql("select coalesce(max(fv_no),0)+1 from fem_verifications where study_id=:s", s=env.sid)[0][0])
    A = env.sroot / "04_verify" / f"FV-{no:03d}" / "a1"
    (A / "result").mkdir(parents=True)
    (A / "input").mkdir(parents=True)
    _h3d(A / "result" / "model0_0000.h3d", h3d_seed)
    (A / "result" / "model0_0000T01").write_bytes(b"T01")
    (A / "input" / MESH_INC).write_text(MESH_TEXT)
    env.sql("insert into fem_verifications(id, study_id, fv_no, source_kind, source_ref, param_set_id, assem_kind, input_mode, attempt_no, status,"
            " dir_rel, created_by, created_by_name, finished_at) values (:i,:s,:n,'VALUES','{}',:ps,'TRAIN_DOE','rebuild',1,'DONE',:d,'u-power','파워',now())",
            i=fid, s=env.sid, n=no, ps=ps_id, d=f"04_verify/FV-{no:03d}")
    return fid


def make_folders(root: Path, names: list[str], *, h3d_seed: int = 0, params: bool = True, t01: bool = True) -> list[str]:
    out = []
    for i, n in enumerate(names):
        d = root / n
        d.mkdir(parents=True, exist_ok=True)
        _h3d(d / f"{n}.h3d", h3d_seed + i)
        if t01:
            (d / f"{n}T01").write_bytes(b"T01")
        if params:
            (d / "params.json").write_text(json.dumps({"THK_1": 2.0 + i * 0.5, "N_RIB": 2 + i}))
        (d / MESH_INC).write_text(MESH_TEXT)
        out.append(str(d))
    return out


def snapshot_tree(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return out


def body(side_a: dict[str, Any], side_b: dict[str, Any], *, pairing: str = "by_name", recipe: dict[str, Any] | None = None,
         inline: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    b: dict[str, Any] = {"side_a": side_a, "side_b": side_b, "pairing": {"mode": pairing}, **kw}
    if recipe is not None:
        b["recipe"] = recipe
    if inline is not None:
        b["recipe_inline"] = {"definition": inline}
    return b


def preview(env: Any, b: dict[str, Any], expect: int = 200) -> dict[str, Any]:
    r = env.c.post(f"{API}/studies/{env.sid}/equiv-checks/preview", headers=PW, json=b)
    assert r.status_code == expect, r.text
    return r.json()


def create(env: Any, b: dict[str, Any], expect: int = 202, headers: dict[str, str] | None = None) -> dict[str, Any]:
    r = env.c.post(f"{API}/studies/{env.sid}/equiv-checks", headers=headers or PW, json=b)
    assert r.status_code == expect, r.text
    return r.json()


def detail(env: Any, eid: str) -> dict[str, Any]:
    r = env.c.get(f"{API}/equiv-checks/{eid}", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def run_check(env: Any, b: dict[str, Any]) -> dict[str, Any]:
    c = create(env, b)
    st = env.w.run_once_slot()
    assert st == "SUCCEEDED", env.job(c["job_id"])
    return detail(env, c["eq_id"])


def eq_dir(env: Any, d: dict[str, Any]) -> Path:
    return env.sroot / "05_equiv" / d["label"]
