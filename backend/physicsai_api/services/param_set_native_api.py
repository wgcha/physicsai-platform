"""④ native 세트 API 서비스(geometry-engine.md §7.4~§7.6): 등록(202 job)·다시 준비·피처 조회·옵션 변경·응답 보강."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import artifacts as art_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.geometry import features_view
from physicsai_core.geometry.extract_filter import from_paicad
from physicsai_core.geometry.options import effective_options, tag_section_changed
from physicsai_core.geometry.prep import is_shell_only, prep_state
from physicsai_core.geometry.shell import PROPS_JSON
from physicsai_core.geometry.reports import ReportError, read_report
from physicsai_core.paths import allowed_roots, check_user_path, resolve_in_study
from physicsai_core.stage4_predict import param_discover_native as dn

from ..auth import Principal
from ..context import AppContext
from . import jobs as jobs_svc
from .common import audit, study_root
from .geometry_gate import require_native_available, require_shell_available, validate_geom_options
from .param_set_native_train import _register_view, from_train, train_features  # noqa: F401 - 300줄 분할(R-B), 기존 경로 재노출


def wants_native(ctx: AppContext, body: Any, *, discover: bool = False) -> bool:
    """등록·discover 요청의 엔진: 명시 값 → 없으면 geometry.engine 기본값(등록은 mode=discover일 때만 기본값을 따른다)."""
    eng = getattr(body, "engine", None)
    if eng is not None:
        return eng == "native"
    return (discover or getattr(body, "mode", None) == "discover") and ctx.settings.geometry.engine == "native"


def discover_native_out(ctx: AppContext, path: str, kind: str = "solid") -> dict[str, Any]:
    cp = check_user_path(path, allowed_roots(ctx.settings, imports=True))
    d = dn.discover_native(cp.path, ctx.settings, kind=kind)
    out = d.out()
    out["engine"] = "native"
    out["kind"] = kind
    out["cad"] = [{**c, "kind": "parts" if c["name"].casefold() == dn.PARTS_DIR else "file"} for c in out["cad"]]
    return out


def raise_filter_unsupported() -> None:
    from .job_params.stage1_native import raise_filter_unsupported as _raise

    _raise()


def register_native(ctx: AppContext, principal: Principal, study_id: str, body: Any, label: str | None, rid: str,
                    ip: str | None) -> dict[str, Any]:
    """POST /studies/{id}/param-sets {engine:native} → 후보를 읽기만 확인하고 PARAM_SET_NATIVE 작업을 만든다(202)."""
    if getattr(body, "mode", None) != "discover":
        raise DomainError("INVALID_PARAMS", "Native 형상 엔진은 mode=discover로만 등록합니다", status=422)
    require_native_available(ctx.settings)
    kind = getattr(body, "kind", None) or "solid"  # shell-morph.md §8.2: 세트 형상 종류(prep.json kind, DB 열 없음)
    shell_only = bool(getattr(body, "shell_only", False))  # §11.1 쉘 두께 전용: STEP·번호 표 불필요
    if shell_only and getattr(body, "extract_filter", None) is not None:  # 쉘 두께 전용은 형상 추출 없음 — 조건 거부
        raise_filter_unsupported()
    if kind == "shell":
        if shell_only:
            raise DomainError("INVALID_PARAMS", "쉘 두께 전용(shell_only)과 쉘 판금 형상(kind=shell)은 함께 쓸 수 없습니다", status=422,
                              errors=[{"loc": ["body", "kind"], "msg": "shell_only와 함께 쓸 수 없음"}])
        require_shell_available(ctx.settings)
    over = validate_geom_options(ctx.settings, body.geom_options, kind)
    cp = check_user_path(body.path, allowed_roots(ctx.settings, imports=True))
    choice = body.choice.model_dump(exclude_unset=True) if body.choice is not None else {}
    if shell_only:
        choice.pop("cad", None)
    d = dn.discover_native(cp.path, ctx.settings, kind=kind)
    cad, assem, probs = dn.resolve_choice_native(d, choice, kind=kind)
    problems = dn.shell_only_problems(d.problems + probs) if shell_only else d.problems + probs
    if problems or assem is None or (cad is None and not shell_only):
        raise DomainError("PARAM_SET_INVALID", "프로젝트 폴더에서 파라미터 세트를 구성할 수 없습니다", status=422,
                          problems=problems or [{"code": "DISCOVER_INCOMPLETE", "message": "STEP·조립 폴더를 모두 찾아야 합니다"}])
    params = {"mode": "new", "path": cp.path, "choice": {"cad": None if shell_only else cad, "radioss_assem": assem["rel"]},
              "label": label, "geom_options": over or None}
    if shell_only:
        params["shell_only"] = True
    if kind == "shell":
        params["kind"] = "shell"
    from .job_params.stage1_native import normalized_filter

    norm = normalized_filter(getattr(body, "extract_filter", None))  # extract-filter.md §6.7: 정규화본을 params에 기록(쉘·altair는 앞에서 422)
    if norm is not None:
        params["extract_filter"] = norm
    job = jobs_svc.create_job(ctx, principal, study_id, "PARAM_SET_NATIVE", params, rid, ip)
    return {"job_id": job["id"]}


def raise_filter_fixed() -> None:
    """extract-filter.md §6.7: 등록된 세트(reprep·baseline 추가)는 추출 조건을 받지 않는다 → 422 EXTRACT_FILTER_INVALID."""
    from physicsai_core.geometry.extract_filter import CANT_CHANGE_MESSAGE

    raise DomainError("EXTRACT_FILTER_INVALID", CANT_CHANGE_MESSAGE, status=422, problems=[{"key": "extract_filter", "message": CANT_CHANGE_MESSAGE}])


def prepare_native(ctx: AppContext, principal: Principal, ps_id: str, rid: str, ip: str | None, body: Any = None) -> dict[str, Any]:
    """POST /param-sets/{id}/native-prepare → reprep 작업(202)."""
    if getattr(body, "extract_filter", None) is not None:
        raise_filter_fixed()
    with ctx.engine.connect() as conn:
        p = ps_repo.get(conn, ps_id)
    if p is None:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    job = jobs_svc.create_job(ctx, principal, p["study_id"], "PARAM_SET_NATIVE", {"mode": "reprep", "param_set_id": ps_id}, rid, ip)
    return {"job_id": job["id"]}


def _S(ctx: AppContext, conn: Any, p: dict[str, Any]) -> str:
    return resolve_in_study(study_root(ctx, studies_repo.require(conn, p["study_id"])), p["stored_rel"])


def _features_doc(ctx: AppContext, S: str) -> dict[str, Any] | None:
    from physicsai_core.geometry.shell_native import features_name, read_kind

    try:
        return read_report(os.path.join(S, "native", "extract", features_name(read_kind(S))), ctx.settings.geometry.max_report_bytes)
    except ReportError:
        return None


def _state(ctx: AppContext, p: dict[str, Any]) -> tuple[Any, dict[str, Any], str]:
    s = ctx.settings
    with ctx.engine.connect() as conn:
        S = _S(ctx, conn, p)
    opts = kind_options(ctx, S, p.get("geom_options"))
    st = prep_state(S, step_exts=s.geometry.step_extensions, mesh_include_name=s.predict.mesh_include_name,
                    renum_csv_name=s.predict.renum_csv_name, opts=opts)
    return st, opts, S


def kind_options(ctx: AppContext, S: str, geom_options: dict[str, Any] | None) -> dict[str, Any]:
    """준비본 kind에 맞는 유효 옵션(솔리드 §4.9 | 쉘 SM §4.10)."""
    from physicsai_core.geometry.shell_native import read_kind
    from physicsai_core.geometry.shell_options import effective_shell_options

    if read_kind(S) == "shell":
        return effective_shell_options(ctx.settings.geometry.shell_defaults, geom_options)[0]
    return effective_options(ctx.settings.geometry.defaults, geom_options)[0]


def set_kind(ctx: AppContext, p: dict[str, Any]) -> str:
    from physicsai_core.geometry.shell_native import read_kind

    return read_kind(set_path(ctx, p)) if (p.get("engine") or "altair") == "native" else "solid"


def set_path(ctx: AppContext, p: dict[str, Any]) -> str:
    with ctx.engine.connect() as conn:
        return _S(ctx, conn, p)


def baseline_prep_problems(ctx: AppContext, p: dict[str, Any]) -> list[tuple[str, str]]:
    """다중 baseline 세트의 추가 baseline 중 준비본이 READY가 아닌 것(§7.3.8)."""
    if (p.get("engine") or "altair") != "native":
        return []
    from .param_set_baselines_api import prep_problems

    _st, opts, S = _state(ctx, p)
    return prep_problems(ctx, p, S, opts)


def prep_state_of(ctx: AppContext, p: dict[str, Any]) -> Any:
    """native 세트의 준비본 상태(PrepState), altair 세트면 None. 엔진 버전 비교는 워커가 실행 때 한다(API는 paicad를 실행하지 않는다)."""
    return _state(ctx, p)[0] if (p.get("engine") or "altair") == "native" else None


def enrich(ctx: AppContext, p: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    """native 세트 응답에 geom_options_effective·native{prep_status…} 추가(altair는 그대로)."""
    if (p.get("engine") or "altair") != "native":
        return out
    st, opts, S = _state(ctx, p)
    from physicsai_core.geometry.shell_native import read_kind
    from physicsai_core.geometry.view import prep_view

    doc = _features_doc(ctx, S) or {}
    out["geom_options_effective"] = opts
    out["native"] = {"prep_status": st.status, "prep_reason": st.reason, "feature_count": len(doc.get("features", [])),
                     "shell_only": is_shell_only(S), "props_scanned": os.path.isfile(os.path.join(S, *PROPS_JSON.split("/"))),
                     "kind": read_kind(S), "view_status": prep_view(S).get("status") or "MISSING",
                     "extract_filter": from_paicad(doc.get("filter"))}  # extract-filter.md §6.7
    from .param_set_baselines_api import baselines_info  # 4B(§7.3.8): 다중 baseline 세트만

    info = baselines_info(ctx, p, S, opts)
    if info is not None:
        out["baselines"], out["param_map_status"] = info
    return out


def features(ctx: AppContext, ps_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        p = ps_repo.get(conn, ps_id)
        if p is None:
            raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
        if (p.get("engine") or "altair") != "native":
            raise DomainError("ENGINE_MISMATCH", "Native 형상 엔진 세트가 아닙니다", status=409)
        S = _S(ctx, conn, p)
        arts = art_repo.list_by_prefix(conn, p["study_id"], "FEATURE_PNG", p["stored_rel"].rstrip("/") + "/native/extract/features/")
    doc = _features_doc(ctx, S)
    if doc is None:
        raise DomainError("NATIVE_PREP_MISSING", "형상 피처 파일이 없습니다 — 형상 준비를 다시 하세요", status=409)
    ids: dict[str, str] = {}
    for a in arts:  # 최신이 먼저 — 이름마다 첫 항목만
        ids.setdefault(os.path.splitext(os.path.basename(a["rel_path"]))[0], a["id"])
    return features_view.summary(doc, ids)


def patch_geom_options(ctx: AppContext, conn: Any, principal: Principal, p: dict[str, Any], raw: dict[str, Any] | None,
                       rid: str, ip: str | None) -> None:
    """PATCH geom_options(전체 덮어쓰기). altair 세트는 422. tag 절이 바뀌면 prep_status가 STALE로 보인다(준비본 해시 비교)."""
    if (p.get("engine") or "altair") != "native":
        raise DomainError("ENGINE_MISMATCH", "geom_options는 Native 형상 엔진 세트에서만 바꿀 수 있습니다", status=422)
    over = validate_geom_options(ctx.settings, raw, set_kind(ctx, p))
    ps_repo.set_values(conn, p["id"], geom_options=over or None)
    audit(conn, principal, "PARAM_SET_UPDATE", "param_set", p["id"],
          {"geom_options": over, "tag_changed": tag_section_changed(p.get("geom_options"), over)}, rid, ip)
