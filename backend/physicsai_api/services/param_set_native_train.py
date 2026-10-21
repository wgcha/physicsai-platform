"""④ native 세트 API 서비스 — ① 학습 DOE 가져오기(from-train)·공칭 뷰 등록·학습 피처 요약(R-B 300줄 분할, `param_set_native_api`에서 재노출).

`enrich`는 `param_set_native_api`에 있으므로 호출 시점에 가져온다(순환 import 회피)."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from physicsai_core.db.repositories import artifacts as art_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.geometry import features_view
from physicsai_core.geometry.options import effective_options
from physicsai_core.geometry.reports import ReportError, read_report
from physicsai_core.paths import resolve_in_study

from ..auth import Principal
from ..context import AppContext
from .common import audit, study_root


def from_train(ctx: AppContext, principal: Principal, study: dict[str, Any], d: dict[str, Any], D: str, label: str | None,
               body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    """①→④(native DOE): `D/cad`→`cad/`, `A`→`radioss_assem/`, `D/native`→`native/`(prep.json은 S 기준으로 다시 씀). paicad 실행 없음(§7.3.4)."""
    import shutil
    from datetime import datetime, timezone

    from physicsai_core.fileutil import copy_tree, write_json
    from physicsai_core.geometry.prep import PREP_JSON, prep_document
    from physicsai_core.stage4_predict.param_set_native import validate_native_folder

    from .common import param_set_out

    s = ctx.settings
    root = study_root(ctx, study)
    A = resolve_in_study(root, f"01_train/radioss_assem/{d['id']}")
    if not os.path.isdir(os.path.join(D, "cad")) or not os.path.isdir(os.path.join(D, "native")) or not os.path.isdir(A):
        raise DomainError("PARAM_SET_INVALID", "DOE 준비본(cad·Native·조립 폴더)이 없습니다", status=422,
                          problems=[{"code": "NATIVE_PREP_MISSING", "message": "DOE의 형상 준비 폴더를 찾을 수 없습니다"}])
    T = resolve_in_study(root, f"logs/_paramset_tmp/{uuid.uuid4()}")
    os.makedirs(T)
    copy_tree(os.path.join(D, "cad"), os.path.join(T, "cad"))
    copy_tree(os.path.join(D, "native"), os.path.join(T, "native"))
    for n in sorted(os.listdir(A)):
        if os.path.isfile(os.path.join(A, n)) and not n.lower().startswith("eps_mesh"):
            copy_tree_file = os.path.join(T, "radioss_assem", n)
            os.makedirs(os.path.dirname(copy_tree_file), exist_ok=True)
            shutil.copyfile(os.path.join(A, n), copy_tree_file)
    old = {}
    try:
        with open(os.path.join(D, "native", "prep.json"), encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        pass
    snap = d.get("parameters_snapshot") or []
    kind = "shell" if old.get("kind") == "shell" else "solid"  # shell-morph.md §8.2: DOE 준비본 kind 승계
    write_json(os.path.join(T, "parameters.json"), {
        "schema_version": 1, "unit_system": body.unit_system or "mm-ton-s",
        "parameters": [{"name": p["name"], "nominal": p["nominal"], "min": p["min"], "max": p["max"], "unit": p.get("unit", "")}
                       for p in snap]})
    if kind == "shell":
        from physicsai_core.geometry.shell_options import effective_shell_options

        opts, _ = effective_shell_options(s.geometry.shell_defaults, d.get("geom_options"))
    else:
        opts, _ = effective_options(s.geometry.defaults, d.get("geom_options"))
    pdoc = prep_document(
        T, step_exts=s.geometry.step_extensions, mesh_include_name=s.predict.mesh_include_name,
        renum_csv_name=s.predict.renum_csv_name, opts=opts, engine_version=d.get("engine_version") or old.get("engine_version"),
        ocp_version=old.get("ocp_version"), job_id=old.get("job_id"), created_at=datetime.now(timezone.utc).isoformat(),
        kind=kind, component=old.get("component"))
    from physicsai_core.geometry.view import view_result

    view = view_result(os.path.join(T, "native", "view"), pdoc.get("engine_version"))  # geometry-view.md §6.9: DOE 공칭 뷰 복사
    if view is not None:
        pdoc["view"] = view
    write_json(os.path.join(T, PREP_JSON), pdoc)
    f = validate_native_folder(T, max_total_bytes=s.param_set.max_total_bytes, starter_glob=s.predict.starter_glob,
                               renum_csv_name=s.predict.renum_csv_name, baseline_inc_name=s.predict.mesh_include_name,
                               step_extensions=s.geometry.step_extensions, kind=kind)
    if not f.ok:
        raise DomainError("PARAM_SET_INVALID", "파라미터 세트 검증에 실패했습니다", status=422, problems=f.problems)
    rows = [{**x, "source": "shell"} for x in f.parameters] if kind == "shell" else f.parameters
    psid = str(uuid.uuid4())
    src_label = f"① DOE {d['id'][:8]}"
    write_json(os.path.join(T, "source.json"), {"source_path": src_label, "registered_at": datetime.now(timezone.utc).isoformat(),
                                                "mode": "from_train", "doe_id": d["id"]})
    stored_rel = f"04_params/{psid}"
    dst = resolve_in_study(root, stored_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    moved = False
    try:
        with ctx.engine.begin() as conn:
            ps_repo.insert_current(conn, {
                "id": psid, "study_id": study["id"], "source_path": src_label, "stored_rel": stored_rel + "/",
                "unit_system": f.unit_system, "parameters": rows, "responses": [], "sample_count": 0,
                "sample_has_measured": False, "cad_file_name": f.cad_file or "parts/", "tpl_rel": None,
                "assem_rel": f"{stored_rel}/radioss_assem/", "starter_name": f.starter_name, "input_kind": "assembly",
                "tpl_params": [], "registered_by": principal.user_id, "registered_by_name": principal.display_name,
                "label": label, "origin": "TRAIN_DOE", "train_doe_id": d["id"], "engine": "native",
                "geom_options": d.get("geom_options"), "engine_version": d.get("engine_version")})
            audit(conn, principal, "PARAM_SET_FROM_TRAIN", "param_set", psid,
                  {"doe_id": d["id"], "runs": body.runs, "engine": "native", "kind": kind}, rid, ip)
            os.replace(T, dst)
            moved = True
            if view is not None:
                _register_view(conn, study["id"], dst, f"{stored_rel}/native/view")
            row = ps_repo.get(conn, psid)
    except BaseException:
        if moved and os.path.isdir(dst) and not os.path.lexists(T):
            os.replace(dst, T)  # 04_params에 DB 행 없는 고아 폴더를 남기지 않는다(삭제 없음)
        raise
    from .param_set_native_api import enrich

    return enrich(ctx, row, {**param_set_out(row), "warnings": []})  # type: ignore[arg-type]


def _register_view(conn: Any, study_id: str, S: str, rel_dir: str) -> dict[str, str | None]:
    """공칭 뷰 artifacts(GEOM_VIEW_GLB·GEOM_VIEW_MANIFEST) 등록 — from-train(동기, paicad 없음) 복사본(geometry-view.md §6.3)."""
    from physicsai_core.fileutil import sha256_file
    from physicsai_core.geometry.view import GLB_CONTENT_TYPE, JSON_CONTENT_TYPE, VIEW_GLB, VIEW_MANIFEST

    out: dict[str, str | None] = {}
    for kind, name, ctype in (("GEOM_VIEW_GLB", VIEW_GLB, GLB_CONTENT_TYPE), ("GEOM_VIEW_MANIFEST", VIEW_MANIFEST, JSON_CONTENT_TYPE)):
        p = os.path.join(S, "native", "view", name)
        out[kind] = art_repo.insert(conn, study_id=study_id, job_id=None, kind=kind, rel_path=f"{rel_dir}/{name}",
                                    size=os.path.getsize(p), sha256=sha256_file(p), content_type=ctype) if os.path.isfile(p) else None
    return out


def train_features(ctx: AppContext, study_id: str) -> dict[str, Any]:
    """① 학습 native 피처 요약(`GET /studies/{id}/train/features`, §7.3.1 TX_PARSE 결과): 종류·범위·하이라이트 PNG artifact id."""
    from physicsai_core.db.repositories import train as train_repo

    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        setup = train_repo.get_setup(conn, study_id)
        rel = (setup or {}).get("features_rel")
        if not setup or setup.get("engine") != "native" or not rel:
            raise DomainError("NATIVE_PREP_MISSING", "① Native 형상 피처가 없습니다 — 파라미터 추출을 Native로 먼저 하세요", status=409)
        root = study_root(ctx, st)
        prefix = os.path.dirname(rel).rstrip("/") + "/features/"
        arts = art_repo.list_by_prefix(conn, study_id, "FEATURE_PNG", prefix)
    try:
        doc = read_report(resolve_in_study(root, rel), ctx.settings.geometry.max_report_bytes)
    except ReportError:
        raise DomainError("NATIVE_PREP_MISSING", "형상 피처 파일을 읽을 수 없습니다 — 파라미터 추출을 다시 하세요", status=409) from None
    ids: dict[str, str] = {}
    for a in arts:
        ids.setdefault(os.path.splitext(os.path.basename(a["rel_path"]))[0], a["id"])
    return features_view.summary(doc, ids)
