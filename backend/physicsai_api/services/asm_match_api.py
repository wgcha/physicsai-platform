"""조립 매칭 API(asm-match.md §6.3): 생성(202 ASM_MATCH parts)·조회·행 저장·검사(202 ASM_MATCH check)·확정.

상태·행은 파일(`<study>/asm_match/<id>/match.json`)에 있고(AM-12 DB 변경 없음) 작업 상태는 `jobs`(ASM_MATCH)에서 읽는다.
`match.json`은 이 모듈만 쓴다(워커는 `parts/`·`check/<seq>/` 산출물만 씀 — 경쟁 없음). Study 행을 잠근 트랜잭션 안에서 쓰기를 직렬화한다.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import asm_match as am_repo
from physicsai_core.db.repositories import artifacts as art_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import asm_match_missing
from physicsai_core.fileutil import write_json_atomic
from physicsai_core.geometry import asm_match as am
from physicsai_core.geometry.prep import sha256_file
from physicsai_core.geometry.shell_native import kind_of_features_rel
from physicsai_core.paths import allowed_roots, check_user_path, resolve_in_study
from physicsai_core.stage1_train_data import train_params as tp
from physicsai_core.state_machine import ACTIVE

from ..auth import Principal
from ..context import AppContext
from . import asm_match_gate as gate
from .common import audit, require_power, study_root
from .job_params.study_manage import study_gate

API_PREFIX = "/physicsai/api"
GLB_KIND = "GEOM_PREVIEW_FE_GLB"  # 새 artifacts.kind(ASM_MATCH_GLB)는 DB CHECK 변경이 필요해 기존 FE GLB 종류를 재사용(AM-C2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_available(ctx: AppContext, *, write: bool = False) -> None:
    """409 TEMPLATE_NOT_CONFIGURED(§6.2): asm_match.enabled=false·명령 null·paicad 실행 파일 없음."""
    tmpl, res = asm_match_missing(ctx.settings, write=write)
    if tmpl or res:
        first = (tmpl + res)[0]
        raise DomainError("TEMPLATE_NOT_CONFIGURED", f"관리자 설정 필요: {first}", status=409, missing=tmpl + res)


def _study_of(ctx: AppContext, match_id: str) -> dict[str, Any]:
    if not gate.valid_id(match_id):
        raise DomainError("NOT_FOUND", "조립 매칭을 찾을 수 없습니다", status=404)
    with ctx.engine.connect() as conn:
        st = am_repo.study_of(conn, match_id)
    if st is None:
        raise DomainError("NOT_FOUND", "조립 매칭을 찾을 수 없습니다", status=404)
    return st


def _load(ctx: AppContext, study: dict[str, Any], match_id: str) -> tuple[str, dict[str, Any]]:
    mdir = am.match_dir(study_root(ctx, study), match_id)
    match = am.read_match(mdir)
    if match is None or match.get("match_id") != match_id:
        raise DomainError("NOT_FOUND", "조립 매칭 파일이 없습니다 — Study 정리로 옮겨졌을 수 있습니다", status=404)
    return mdir, match


def _parts(mdir: str, max_bytes: int) -> dict[str, Any] | None:
    """component 목록 보고(`parts/asm_parts.json`) — status OK일 때만(FAIL 보고는 목록이 없는 것으로 본다 → 상태 FAILED)."""
    doc = am.read_json(os.path.join(mdir, am.PARTS_DIR, am.PARTS_JSON), max_bytes)
    return doc if doc is not None and doc.get("status") == "OK" else None


# ---- 생성 ---------------------------------------------------------------------------------------------------


def _source(ctx: AppContext, conn: Any, study: dict[str, Any], cad: Any) -> dict[str, Any]:
    """STEP 출처 검사·기록(match.json `source`). train = ①-1 Native 솔리드 추출 결과, path = 허용 루트 안 STEP 파일."""
    s = ctx.settings
    if cad.kind == am.KIND_TRAIN:
        setup = train_repo.get_setup(conn, study["id"])
        if not setup or setup.get("engine") != "native" or not setup.get("features_rel") or not setup.get("cad_file_name"):
            raise DomainError("PREREQUISITE_MISSING", "① Native 파라미터 추출(STEP·피처)이 먼저 필요합니다", status=409, missing=["GEOM_FEATURES"])
        if kind_of_features_rel(setup["features_rel"]) == "shell":
            raise DomainError("ASM_MATCH_UNSUPPORTED", "쉘 판금 세트는 조립 매칭을 쓰지 않습니다", status=422)
        root = study_root(ctx, study)
        cad_rel = f"01_train/cad/{setup['cad_file_name']}"
        feat = resolve_in_study(root, setup["features_rel"])
        cadp = resolve_in_study(root, cad_rel)
        if not os.path.isfile(cadp) or not os.path.isfile(feat):
            raise DomainError("PREREQUISITE_MISSING", "STEP 사본·피처 파일이 없습니다 — ①-1을 다시 실행하세요", status=409, missing=["GEOM_FEATURES"])
        return {"kind": am.KIND_TRAIN, "cad_name": setup["cad_file_name"], "cad_rel": cad_rel, "cad_sha256": sha256_file(cadp),
                "features_rel": setup["features_rel"], "features_sha256": sha256_file(feat)}
    if not cad.path:
        raise DomainError("INPUT_INVALID", "STEP 파일 경로(cad.path)가 필요합니다", status=422, errors=[{"loc": ["cad", "path"], "msg": "필수"}])
    cp = check_user_path(cad.path, allowed_roots(s, imports=True), expect="file")
    if os.path.splitext(cp.path)[1].lower() not in [e.lower() for e in s.geometry.step_extensions]:
        raise DomainError("INPUT_INVALID", f"STEP 확장자는 {', '.join(s.geometry.step_extensions)} 중 하나여야 합니다", status=422,
                          errors=[{"loc": ["cad", "path"], "msg": "확장자"}])
    return {"kind": am.KIND_PATH, "cad_name": os.path.basename(cp.path), "cad_path": cp.path, "cad_sha256": sha256_file(cp.path),
            "features_rel": None, "features_sha256": None}


def create(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    """`POST /studies/{id}/asm-matches` → {match_id, job_id}(202)."""
    require_available(ctx)
    with ctx.engine.connect() as conn:
        st0 = studies_repo.require(conn, study_id)
    require_power(principal, st0["project_id"])
    ap = check_user_path(body.radioss_assem_path, allowed_roots(ctx.settings, imports=True))
    mid = am.new_match_id()
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study_id, for_update=True)
        study_gate(conn, study, "ASM_MATCH")
        source = _source(ctx, conn, study, body.cad)
        if am_repo.active_of(conn, study_id) is not None:
            raise DomainError("STUDY_JOB_BUSY", "이 Study에서 조립 매칭 작업이 이미 대기 중이거나 실행 중입니다", status=409)
        mdir = am.match_dir(study_root(ctx, study), mid)
        now = _now()
        am.write_match(mdir, {"schema_version": am.SCHEMA_VERSION, "match_id": mid, "state": "SCANNING", "source": source,
                              "assem": {"path": ap.path, "digest": None, "starter": None}, "rows": [], "excluded_bodies": [],
                              "rows_sha256": am.rows_sha256([], []), "created_by": principal.user_id, "created_at": now, "updated_at": now})
        job = jobs_repo.insert_job(conn, study=study, job_type="ASM_MATCH", params={"match_id": mid, "mode": "parts"},
                                   user_id=principal.user_id, user_name=principal.display_name)
        audit(conn, principal, "ASM_MATCH_CREATE", "study", study_id, {"match_id": mid, "job_id": job["id"], "source": source["kind"]}, rid, ip)
    return {"match_id": mid, "job_id": job["id"]}


# ---- 조회 ---------------------------------------------------------------------------------------------------


def _use_bodies(ctx: AppContext, study: dict[str, Any], match: dict[str, Any]) -> list[str]:
    """① 출처만: use=true 파라미터가 있는 바디(매칭 안 함 불가, §3.2). 피처 이름 → 바디."""
    src = match.get("source") or {}
    if src.get("kind") != am.KIND_TRAIN:
        return []
    _cad, feat = gate.source_files(ctx, study, src)
    doc = am.read_json(feat or "", ctx.settings.geometry.max_report_bytes)
    with ctx.engine.connect() as conn:
        setup = train_repo.get_setup(conn, study["id"])
    if doc is None or not setup:
        return []
    used = {str(p["name"]) for p in tp.used(setup.get("parameters") or [])}
    return sorted({str(f.get("body")) for f in doc.get("features") or [] if isinstance(f, dict) and f.get("name") in used and f.get("body")})


def worst_points(cdir: str, row: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """행의 `worst`(paicad `worst_<body>.npz`: node_id·xyz·dist, 거리 내림차순) → 상위 limit점 `[{node_id, xyz:[x,y,z], dist_mm}]`.
    파일 이름은 폴더 직계 `.npz`만 읽는다(보고 내용으로 경로를 벗어나지 못하게). 읽기 실패 = 빈 목록."""
    name = ((row.get("worst") or {}).get("file")) if isinstance(row.get("worst"), dict) else None
    if not isinstance(name, str) or name != os.path.basename(name) or not name.endswith(".npz") or limit <= 0:
        return []
    path = os.path.join(cdir, name)
    if not os.path.isfile(path):
        return []
    try:
        import numpy as np

        with np.load(path, allow_pickle=False) as z:
            ids, xyz, dist = z["node_id"][:limit], z["xyz"][:limit], z["dist"][:limit]
            return [{"node_id": int(i), "xyz": [float(v) for v in p3], "dist_mm": float(d)} for i, p3, d in zip(ids, xyz, dist)]
    except (OSError, KeyError, ValueError):
        return []


def _rows_with_worst(cdir: str, rows: list[Any], limit: int) -> list[Any]:
    out = []
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get("worst"), dict):
            r = {**r, "worst": {**r["worst"], "points": worst_points(cdir, r, limit)}}
        out.append(r)
    return out


def _check_view(ctx: AppContext, study: dict[str, Any], match: dict[str, Any], mdir: str, cur_sha: str) -> dict[str, Any] | None:
    """최신 검사(`check/<seq>/asm_check.json`) 요약 + GLB 산출물. 현재 행과 같은 검사면 current=true."""
    max_b = ctx.settings.geometry.max_report_bytes
    for seq in reversed(am.check_seqs(mdir)):
        cdir = am.check_dir(mdir, seq)
        doc = am.read_json(os.path.join(cdir, am.CHECK_JSON), max_b)
        if doc is None:
            continue
        rel = f"{am.MATCH_ROOT}/{match['match_id']}/{am.CHECK_DIR}/{seq}/"
        with ctx.engine.connect() as conn:
            glb = art_repo.list_by_prefix(conn, study["id"], GLB_KIND, rel)
        gid = glb[0]["id"] if glb else None
        return {"seq": seq, "status": doc.get("status"), "code": doc.get("code"), "message": doc.get("message"),
                "rows_sha256": doc.get("rows_sha256"), "current": doc.get("rows_sha256") == cur_sha, "tolerance": doc.get("tolerance"),
                "rows": _rows_with_worst(cdir, doc.get("rows") or [], int(ctx.settings.asm_match.worst_nodes)), "file_checks": doc.get("file_checks"), "warnings": doc.get("warnings") or [],
                "assem_digest": (doc.get("assem") or {}).get("digest"), "elapsed_s": doc.get("elapsed_s"),
                "glb_artifact_id": gid, "glb_url": f"{API_PREFIX}/artifacts/{gid}/media" if gid else None}
    return None


def _last_job(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not jobs:
        return None
    j = jobs[0]
    return {"id": j["id"], "mode": (j.get("params") or {}).get("mode"), "state": j["state"], "failure_code": j.get("failure_code"),
            "failure_message": j.get("failure_message"), "progress_pct": j.get("progress_pct"),
            "progress_label": j.get("progress_label")}


def view(ctx: AppContext, study: dict[str, Any], match_id: str) -> dict[str, Any]:
    """AsmMatch 응답(§6.3). 상태는 파일 + 최신 작업 + 입력 변경 판정에서 계산한다."""
    mdir, match = _load(ctx, study, match_id)
    with ctx.engine.connect() as conn:
        jobs = am_repo.jobs_of(conn, match_id, 5)
    parts_doc = _parts(mdir, ctx.settings.geometry.max_report_bytes)
    active = jobs[0] if jobs and jobs[0]["state"] in ACTIVE else None
    assem = dict(match.get("assem") or {})
    p_assem = (parts_doc or {}).get("assem") or {}
    digest, starter = p_assem.get("digest"), p_assem.get("starter")
    cur_sha = am.rows_sha256(match.get("rows") or [], match.get("excluded_bodies") or [])
    check = _check_view(ctx, study, match, mdir, cur_sha)
    confirmed_doc = am.read_json(os.path.join(mdir, am.CONFIRMED_JSON))
    confirmed = {"sha256": sha256_file(os.path.join(mdir, am.CONFIRMED_JSON)), "confirmed_at": confirmed_doc.get("confirmed_at"),
                 "confirmed_by": confirmed_doc.get("confirmed_by")} if confirmed_doc else None
    stale = None
    if active is None and (parts_doc is not None or confirmed_doc is not None):
        stale = gate.stale_reason(ctx, study, match, (confirmed_doc or {}).get("assem", {}).get("digest") or digest)
    if active is not None:
        state = "SCANNING" if (active.get("params") or {}).get("mode") == "parts" else "CHECKING"
    elif parts_doc is None:
        state = "FAILED"
    elif stale:
        state = "STALE"
    elif confirmed:
        state = "CONFIRMED"
    elif check and check["current"] and check["status"] == "PASS":
        state = "CHECKED"
    else:
        state = "DRAFT"
    bodies = [b["body"] for b in (parts_doc or {}).get("bodies") or []]
    return {"match_id": match_id, "study_id": study["id"], "state": state,
            "source": {k: v for k, v in (match.get("source") or {}).items() if k in ("kind", "cad_name", "features_rel", "cad_sha256")},
            "assem": {"display_path": assem.get("path"), "digest": digest, "starter": starter, "files": len(p_assem.get("tree") or [])},
            "bodies": (parts_doc or {}).get("bodies") or [], "parts": (parts_doc or {}).get("parts") or [],
            "recommend": (parts_doc or {}).get("recommend") or [], "rows": match.get("rows") or [],
            "excluded_bodies": match.get("excluded_bodies") or [], "check": check, "confirmed": confirmed, "stale_reason": stale,
            "last_job": _last_job(jobs), "warnings": (parts_doc or {}).get("warnings") or [],
            "rows_complete": am.rows_complete(match.get("rows") or [], match.get("excluded_bodies") or [], bodies),
            "use_bodies": _use_bodies(ctx, study, match), "created_at": match.get("created_at"), "updated_at": match.get("updated_at")}


def get(ctx: AppContext, match_id: str) -> dict[str, Any]:
    return view(ctx, _study_of(ctx, match_id), match_id)


def list_matches(ctx: AppContext, study_id: str, source: str | None = None, latest: bool = False, limit: int = 20) -> dict[str, Any]:
    """`GET /studies/{id}/asm-matches` → {items:[AsmMatch…]} 최신(created_at)순. source = train|path 필터, latest = 1개만.
    목록 = `<study>/asm_match/<uuid>/match.json`(파일 기준 — Study 정리로 옮겨진 것은 빠진다), 항목은 단건 조회와 같은 모양."""
    with ctx.engine.connect() as conn:
        study = studies_repo.require(conn, study_id)
    base = os.path.join(study_root(ctx, study), am.MATCH_ROOT)
    found: list[tuple[str, str]] = []
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if not gate.valid_id(name):
            continue
        m = am.read_match(os.path.join(base, name))
        if m is None or m.get("match_id") != name or (source and (m.get("source") or {}).get("kind") != source):
            continue
        found.append((str(m.get("created_at") or ""), name))
    found.sort(reverse=True)
    n = 1 if latest else max(1, min(int(limit), 100))
    return {"items": [view(ctx, study, mid) for _c, mid in found[:n]]}


# ---- 행 저장 ------------------------------------------------------------------------------------------------


def _writable(view_: dict[str, Any]) -> None:
    st = view_["state"]
    if st == "CONFIRMED":
        raise DomainError("ASM_MATCH_CONFIRMED", "확정된 매칭은 바꿀 수 없습니다 — 새 조립 매칭을 만드세요", status=409)
    if st in ("SCANNING", "CHECKING"):
        raise DomainError("ASM_MATCH_BUSY", "조립 매칭 작업이 진행 중입니다 — 끝난 뒤 다시 하세요", status=409)
    if st == "FAILED":
        raise DomainError("PREREQUISITE_MISSING", "조립 component 목록을 만들지 못했습니다 — 새 조립 매칭을 만드세요", status=409, missing=["ASM_PARTS"])
    if st == "STALE":
        raise DomainError("ASM_MATCH_STALE", view_.get("stale_reason") or gate.STALE_ASSEM, status=409)


def set_rows(ctx: AppContext, principal: Principal, match_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    """`PUT /asm-matches/{id}/rows` → AsmMatch(DRAFT, 검사 무효). 422 ASM_ROW_INVALID(problems[]), 409 ASM_MATCH_CONFIRMED."""
    study0 = _study_of(ctx, match_id)
    require_power(principal, study0["project_id"])
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study0["id"], for_update=True)  # 같은 Study 쓰기 직렬화
        study_gate(conn, study, "ASM_MATCH")
        v = view(ctx, study, match_id)
        _writable(v)
        mdir, match = _load(ctx, study, match_id)
        names = [b["body"] for b in v["bodies"]]
        rows, excl, probs = am.validate_rows([r.model_dump() for r in body.rows], list(body.excluded_bodies), names, v["parts"],
                                             set(v["use_bodies"]))
        if probs:
            raise DomainError("ASM_ROW_INVALID", "매칭 표가 올바르지 않습니다", status=422, problems=probs, body=probs[0].get("body"))
        doc = {**match, "state": "DRAFT", "rows": rows, "excluded_bodies": excl, "rows_sha256": am.rows_sha256(rows, excl), "updated_at": _now()}
        am.write_match(mdir, doc)
        audit(conn, principal, "ASM_MATCH_ROWS", "asm_match", match_id, {"rows": len(rows), "excluded": len(excl)}, rid, ip)
    return view(ctx, study, match_id)


# ---- 검사 ---------------------------------------------------------------------------------------------------


def plan_check(ctx: AppContext, principal: Principal, match_id: str) -> dict[str, Any]:
    """검사 시작 전 점검(MCP plan_fn용, 부작용 없음): {problems[], match_id, study_id}."""
    study = _study_of(ctx, match_id)
    probs: list[dict[str, str]] = []
    tmpl, res = asm_match_missing(ctx.settings)
    if tmpl or res:
        probs.append({"code": "TEMPLATE_NOT_CONFIGURED", "message": f"관리자 설정 필요: {(tmpl + res)[0]}"})
    v = view(ctx, study, match_id)
    if v["state"] == "CONFIRMED":
        probs.append({"code": "ASM_MATCH_CONFIRMED", "message": "이미 확정된 매칭입니다"})
    elif v["state"] in ("SCANNING", "CHECKING"):
        probs.append({"code": "ASM_MATCH_BUSY", "message": "조립 매칭 작업이 진행 중입니다"})
    elif v["state"] == "STALE":
        probs.append({"code": "ASM_MATCH_STALE", "message": v.get("stale_reason") or gate.STALE_ASSEM})
    elif not v["rows_complete"]:
        probs.append({"code": "ASM_ROWS_INCOMPLETE", "message": "모든 바디를 component에 매칭하거나 매칭 안 함으로 두세요"})
    return {"match_id": match_id, "study_id": study["id"], "problems": probs}


def check(ctx: AppContext, principal: Principal, match_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """`POST /asm-matches/{id}/check` → {job_id, match_id, seq}(202). 409 ASM_ROWS_INCOMPLETE."""
    require_available(ctx)
    study0 = _study_of(ctx, match_id)
    require_power(principal, study0["project_id"])
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study0["id"], for_update=True)
        study_gate(conn, study, "ASM_MATCH")
        v = view(ctx, study, match_id)
        _writable(v)
        if not v["rows_complete"]:
            raise DomainError("ASM_ROWS_INCOMPLETE", "모든 바디를 component에 매칭하거나 매칭 안 함으로 두세요(매칭 행 1개 이상)", status=409)
        if am_repo.active_of(conn, study["id"]) is not None:
            raise DomainError("STUDY_JOB_BUSY", "이 Study에서 조립 매칭 작업이 이미 대기 중이거나 실행 중입니다", status=409)
        mdir, match = _load(ctx, study, match_id)
        seq = am.next_seq(mdir)
        cdir = am.check_dir(mdir, seq)
        os.makedirs(cdir, exist_ok=True)
        data = am.canonical_rows(match["rows"], match.get("excluded_bodies") or [])
        with open(os.path.join(cdir, am.ROWS_JSON), "wb") as fh:  # `--match` 입력 = 이 바이트(sha256 = rows_sha256)
            fh.write(data)
        sha = hashlib.sha256(data).hexdigest()
        am.write_match(mdir, {**match, "state": "CHECKING", "updated_at": _now()})
        job = jobs_repo.insert_job(conn, study=study, job_type="ASM_MATCH", user_id=principal.user_id, user_name=principal.display_name,
                                   params={"match_id": match_id, "mode": "check", "seq": seq, "rows_sha256": sha})
        audit(conn, principal, "ASM_MATCH_CHECK", "asm_match", match_id, {"job_id": job["id"], "seq": seq}, rid, ip)
    return {"job_id": job["id"], "match_id": match_id, "seq": seq}


def run_check(ctx: AppContext, principal: Principal, study_id: str, match_id: str, rid: str, ip: str | None
              ) -> tuple[dict[str, Any], str | None, str | None]:
    """MCP 작업 종류 `asm_match`(검사 시작)용: (결과, 작업 id, match id). 다른 Study의 묶음이면 404."""
    if _study_of(ctx, match_id)["id"] != study_id:
        raise DomainError("NOT_FOUND", "이 Study의 조립 매칭이 아닙니다", status=404)
    out = check(ctx, principal, match_id, rid, ip)
    return out, out["job_id"], match_id


# ---- 확정 ---------------------------------------------------------------------------------------------------


def confirm(ctx: AppContext, principal: Principal, match_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """`POST /asm-matches/{id}/confirm` → AsmMatch(CONFIRMED). 409 ASM_CHECK_REQUIRED(마지막 검사 없음·FAIL·rows 다름)·ASM_MATCH_STALE."""
    study0 = _study_of(ctx, match_id)
    require_power(principal, study0["project_id"])
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study0["id"], for_update=True)
        study_gate(conn, study, "ASM_MATCH")
        v = view(ctx, study, match_id)
        if v["state"] == "CONFIRMED":
            return v
        _writable(v)
        c = v["check"]
        mdir, match = _load(ctx, study, match_id)
        if c is None or c["status"] != "PASS" or not c["current"]:
            raise DomainError("ASM_CHECK_REQUIRED", "마지막 검사가 없거나 통과하지 않았거나 그 뒤 행이 바뀌었습니다 — 검사를 다시 하세요", status=409)
        cpath = os.path.join(am.check_dir(mdir, c["seq"]), am.CHECK_JSON)
        cdoc = am.read_json(cpath, ctx.settings.geometry.max_report_bytes) or {}
        if c.get("assem_digest") != v["assem"]["digest"]:  # 목록과 검사 사이에 조립이 바뀜
            raise DomainError("ASM_MATCH_STALE", gate.STALE_ASSEM, status=409)
        parts_doc = _parts(mdir, ctx.settings.geometry.max_report_bytes) or {}
        doc = am.confirmed_document({**match, "assem": {**(match.get("assem") or {}), "digest": v["assem"]["digest"],
                                                        "starter": v["assem"]["starter"]}}, parts_doc.get("parts") or [], cdoc, c["seq"],
                                    sha256_file(cpath), engine_version=cdoc.get("engine_version"), user=principal.user_id, now_iso=_now())
        write_json_atomic(os.path.join(mdir, am.CONFIRMED_JSON), doc)
        am.write_match(mdir, {**match, "state": "CONFIRMED", "updated_at": doc["confirmed_at"]})
        audit(conn, principal, "ASM_MATCH_CONFIRM", "asm_match", match_id, {"seq": c["seq"]}, rid, ip)
    return view(ctx, study, match_id)
