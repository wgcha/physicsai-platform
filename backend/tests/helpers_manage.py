"""3차 S3(Study 용량·정리) 시험 공용 도우미: DB 행을 직접 만들어 분류 조건을 재현한다."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from physicsai_core.job_types import JOB_TYPES
from physicsai_core.queues import initial_lane
from physicsai_test_support import API, H

PW, P = H("tok-power", write=True), H("tok-power")


def mk_study(c, name: str) -> str:
    r = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def mk_job(engine, sid: str, job_type: str, state: str = "SUCCEEDED", *, days_ago: float = 0.0,
           params: dict[str, Any] | None = None, retry_of: str | None = None, result: dict[str, Any] | None = None) -> str:
    """종료(또는 RUNNING) 작업 행. finished_at = 지금 - days_ago일."""
    jid = str(uuid.uuid4())
    jt = JOB_TYPES[job_type]
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    term = state in ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")
    with engine.begin() as c:
        c.execute(text(
            "insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params, result,"
            " failure_code, retry_of_job_id, created_by, created_by_name, created_at, started_at, finished_at)"
            " values (:i,:s,'p-1',:t,:st,:ln,:state,false,:qs,cast(:p as jsonb),cast(:r as jsonb),:fc,:ro,'u-power','파워',"
            " :ts,:ts,:fin)"),
            {"i": jid, "s": sid, "t": job_type, "st": jt.stage, "ln": initial_lane(job_type, params), "state": state,
             "qs": 1 if state == "QUEUED" else None, "p": json.dumps(params or {}), "r": json.dumps(result) if result else None,
             "fc": "EXIT_NONZERO" if state in ("FAILED", "INTERRUPTED") else None, "ro": retry_of, "ts": ts,
             "fin": ts if term else None})
    return jid


def mk_dataset(engine, sid: str, package_rel: str | None, job_id: str | None = None) -> str:
    did = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(text(
            "insert into datasets(id, study_id, job_id, source_path, seed, split_group, options_json, package_rel, status,"
            " created_by, created_by_name) values (:i,:s,:j,'/x',1,'file','{}',:p,'READY','u-power','파워')"),
            {"i": did, "s": sid, "j": job_id, "p": package_rel})
    return did


def mk_curation(engine, sid: str, job_id: str, status: str = "READY", kind: str = "H3D") -> str:
    cid = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(text(
            "insert into curations(id, study_id, job_id, kind, source, output_rel, file_list_rel, status, created_by,"
            " created_by_name) values (:i,:s,:j,:k,'{}',:o,:f,:st,'u-power','파워')"),
            {"i": cid, "s": sid, "j": job_id, "k": kind, "o": f"02_curated/{cid}/CURATED_DATA/",
             "f": f"02_curated/{cid}/file_list.json", "st": status})
    return cid


def mk_model(engine, sid: str, eval_job_id: str | None = None, final: bool = False) -> str:
    mid = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(text(
            "insert into models(id, study_id, name, version, source_path, stored_rel, psmdl_rel, psmdl_sha256, psmdl_size,"
            " pscfg_rel, pscfg_sha256, log_status, eval_job_id, registered_by, registered_by_name)"
            " values (:i,:s,'M',:v,'/x',:sr,:sr,:h,1,:sr,:h,'MISSING',:e,'u-power','파워')"),
            {"i": mid, "s": sid, "v": abs(hash(mid)) % 100000, "sr": f"03_model/models/{mid}/", "h": "0" * 64, "e": eval_job_id})
        if final:
            c.execute(text("update studies set final_model_id=:m where id=:s"), {"m": mid, "s": sid})
    return mid


def put(root: Path, rel: str, size: int = 10) -> Path:
    p = root.joinpath(*rel.split("/"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p
