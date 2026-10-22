"""④ 조립 FEM 검증 출처 해석(phase3 §21.3.2 S16): 출처 4종 → 비교 대상 예측 P(재사용 또는 동반 예측 계획)·설계점·메시 원천.

해석 결과는 생성 때 검증 행(source_ref·predict_job_id)에 고정한다(뒤에 다시 해석하지 않음). DB 쓰기 없음."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage4_predict import fem_assembly
from physicsai_core.stage4_predict import input_kind as ik
from physicsai_core.stage4_predict import nearest as nearest_mod
from physicsai_core.stage4_predict.prepared_input import is_mesh_file

from ..context import AppContext
from .common import study_root
from .job_params.base import invalid_errors
from .input_kind_gate import resolve_internal
from .job_params.stage4_predict import model_for, template_kind

APPLIED_TOL = 1e-9


@dataclass
class Resolved:
    kind: str  # PREDICT_JOB | BATCH_RUN | VALUES | OPT_DESIGN
    source_ref: dict[str, Any]
    label: str
    links: dict[str, Any] = field(default_factory=lambda: {"predict_job_id": None, "batch_id": None, "doe_no": None,
                                                           "opt_id": None})
    predict_job: dict[str, Any] | None = None  # 재사용할 P(SUCCEEDED)
    companion: dict[str, Any] | None = None  # 동반 예측 계획 {param_set_id, model_id, values}
    param_set: dict[str, Any] | None = None
    model: dict[str, Any] | None = None
    template_kind: str | None = None
    values: dict[str, float] = field(default_factory=dict)
    applied_values: dict[str, float] = field(default_factory=dict)
    out_of_range: list[str] = field(default_factory=list)
    mesh_rel: str | None = None  # 메시 원천(Study 기준). 동반 예측이면 생성 뒤에 정해진다
    mesh_available: bool = False
    mesh_native: bool = False  # native 세트: 메시 원천 = 모핑 include(재조립에 HyperMesh 변환 불필요, geometry-engine.md §7.3.5)
    input_rel: str | None = None  # P/INPUT(predict_input 원본)
    starter: str | None = None  # P의 starter
    problems: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def problem(self, code: str, message: str) -> None:
        self.problems.append({"code": code, "message": message})

    def warn(self, code: str, message: str) -> None:
        if not any(w["code"] == code for w in self.warnings):
            self.warnings.append({"code": code, "message": message})


def _fmt_time(ts: Any) -> str:
    try:
        return ts.astimezone().strftime("%m-%d %H:%M")
    except (AttributeError, ValueError):
        return ""


def _predict_label(j: dict[str, Any]) -> str:
    return f"④ 예측 {_fmt_time(j['created_at'])}"


def _fill_from_predict(ctx: AppContext, conn: Any, study: dict[str, Any], r: Resolved, j: dict[str, Any]) -> None:
    """P(성공한 PREDICT) → 설계점·템플릿·모델·메시 원천·INPUT."""
    if j["state"] != "SUCCEEDED":
        r.problem("PREDICT_NOT_SUCCEEDED", "비교할 예측이 성공한 상태가 아닙니다")
    r.predict_job = j
    res, p = j["result"] or {}, j["params"] or {}
    psid, mid = res.get("param_set_id") or p.get("param_set_id"), res.get("model_id") or p.get("model_id")
    r.param_set = ps_repo.get(conn, psid) if psid else None
    r.model = models_repo.get(conn, mid) if mid else None
    r.values = {k: float(v) for k, v in (res.get("values") or p.get("values") or {}).items()}
    r.applied_values = {k: float(v) for k, v in (res.get("applied_values") or {}).items()}
    r.out_of_range = list(res.get("out_of_range") or [])
    r.starter = res.get("starter")
    root = jobs_repo.root_job_id(conn, j)
    sroot = study_root(ctx, study)
    ref = pb_repo.batch_run_ref(j)
    batch_dir = run_key = None
    if ref is not None:
        b = pb_repo.get(conn, ref[0])
        run = next((x for x in pb_repo.runs(conn, ref[0]) if x["doe_no"] == ref[1]), None)
        if b is not None and run is not None:
            batch_dir, run_key = b["dir_rel"], run["run_key"]
            r.template_kind = b["input_kind"]
    elif p.get("input_mode") != "prepared":
        r.template_kind = res.get("template_kind") or p.get("template_kind") or (template_kind(r.param_set) if r.param_set else None)
    r.mesh_native = (r.param_set or {}).get("engine") == "native"
    r.mesh_rel = fem_assembly.mesh_source_rel(j, root, ctx.settings, batch_dir_rel=batch_dir, run_key=run_key, native=r.mesh_native)
    r.mesh_available = bool(r.mesh_rel) and os.path.isfile(resolve_in_study(sroot, r.mesh_rel))  # type: ignore[arg-type]
    inp = f"04_predict/{root}/INPUT"
    r.input_rel = inp if os.path.isdir(resolve_in_study(sroot, inp)) else None


def _require_study_job(conn: Any, study: dict[str, Any], job_id: str) -> dict[str, Any] | None:
    j = jobs_repo.get_job(conn, job_id)
    if j is None or j["study_id"] != study["id"] or j["job_type"] != "PREDICT":
        return None
    return j


def _from_batch_run(ctx: AppContext, conn: Any, study: dict[str, Any], r: Resolved, batch_id: str, doe_no: int) -> None:
    b = pb_repo.get(conn, batch_id)
    run = next((x for x in pb_repo.runs(conn, batch_id) if x["doe_no"] == doe_no), None) if b else None
    if b is None or b["study_id"] != study["id"] or run is None:
        r.problem("SOURCE_NOT_FOUND", "일괄 예측 run을 찾을 수 없습니다")
        return
    r.links.update(batch_id=batch_id, doe_no=doe_no)
    if not run.get("predict_job_id"):
        r.problem("PREDICT_NOT_SUCCEEDED", "이 run의 예측이 아직 없습니다")
        return
    j = jobs_repo.get_job(conn, run["predict_job_id"])
    if j is None:
        r.problem("SOURCE_NOT_FOUND", "run의 예측 작업을 찾을 수 없습니다")
        return
    r.links["predict_job_id"] = j["id"]
    _fill_from_predict(ctx, conn, study, r, j)


def _from_values(ctx: AppContext, conn: Any, study: dict[str, Any], r: Resolved, src: Any) -> None:
    ps = ps_repo.get(conn, src.param_set_id)
    if ps is None or ps["study_id"] != study["id"]:
        r.problem("SOURCE_NOT_FOUND", "템플릿(파라미터 세트)을 찾을 수 없습니다")
        return
    m = model_for(conn, study, src.model_id)  # 409 FINAL_MODEL_REQUIRED·ACTIVE_MODEL
    names = [x["name"] for x in ps["parameters"]]
    values = {k: float(v) for k, v in (src.values or {}).items()}
    unknown = [k for k in values if k not in names]
    missing = [n for n in names if n not in values]
    if unknown or missing:
        raise invalid_errors([{"loc": ["source", "values", k], "msg": "unknown" if k in unknown else "required"}
                              for k in unknown + missing])
    mode = ctx.settings.predict.integer_rounding
    applied = nearest_mod.applied_values(ps["tpl_params"], values, mode)
    oor = [o["name"] for o in nearest_mod.out_of_range(ps["parameters"], values)]
    if oor:
        r.warn("OUT_OF_RANGE", f"학습 범위 밖 값: {', '.join(oor[:5])}")
    r.param_set, r.model, r.values, r.applied_values, r.out_of_range = ps, m, values, applied, oor
    r.template_kind = resolve_internal(ctx, ps, getattr(src, "input", None))  # input-kind.md §4.3: ⑥ 입력 종류 승계(능력 밖 422)
    sroot = study_root(ctx, study)
    if src.reuse_existing:
        for j in fv_repo.reusable_predicts(conn, study["id"], ps["id"], m["id"]):
            jk = (j["result"] or {}).get("template_kind") or (j["params"] or {}).get("template_kind") or template_kind(ps)
            if jk != r.template_kind:  # 입력 종류가 다른 예측은 같은 설계점이라도 재사용하지 않는다
                continue
            av = (j["result"] or {}).get("applied_values") or {}
            if set(av) != set(applied) or any(abs(float(av[k]) - float(applied[k])) > APPLIED_TOL for k in applied):
                continue
            root = jobs_repo.root_job_id(conn, j)
            if not (os.path.isdir(resolve_in_study(sroot, f"04_predict/{root}/INPUT"))
                    and os.path.isdir(resolve_in_study(sroot, f"04_predict/{root}/geom"))):
                continue
            _fill_from_predict(ctx, conn, study, r, j)
            r.values, r.applied_values, r.out_of_range = values, applied, oor
            r.links["predict_job_id"] = j["id"]
            return
    r.companion = {"param_set_id": ps["id"], "model_id": m["id"], "values": values, "template_kind": r.template_kind}
    r.mesh_available = True  # 동반 예측이 형상 메시를 만든다


def _opt_values_source(conn: Any, opt: dict[str, Any], study_root_dir: str) -> dict[str, float] | None:
    """대리모델 예측 최적안 값: summary.json surrogate_optimum → 최신 반복 후보 1위."""
    sp = resolve_in_study(study_root_dir, f"{opt['dir_rel']}/summary.json")
    try:
        if os.path.isfile(sp) and os.path.getsize(sp) <= 4 * 1024 * 1024:
            with open(sp, encoding="utf-8") as fh:
                so = (json.load(fh) or {}).get("surrogate_optimum") or {}
            if isinstance(so.get("values"), dict):
                return {k: float(v) for k, v in so["values"].items()}
    except (OSError, ValueError, TypeError):
        pass
    for it in reversed(so_repo.iters(conn, opt["id"])):
        c = (it.get("candidates") or [None])[0]
        if isinstance(c, dict) and isinstance(c.get("values"), dict):
            return {k: float(v) for k, v in c["values"].items()}
    return None


class _ValuesSrc:
    def __init__(self, param_set_id: str, model_id: str | None, values: dict[str, float], reuse_existing: bool = True,
                 input: str | None = None):  # noqa: A002 - 요청 필드 이름 그대로
        self.param_set_id, self.model_id, self.values, self.reuse_existing = param_set_id, model_id, values, reuse_existing
        self.input = input


def _from_opt(ctx: AppContext, conn: Any, study: dict[str, Any], r: Resolved, src: Any) -> None:
    opt = so_repo.get(conn, src.opt_id)
    if opt is None or opt["study_id"] != study["id"]:
        r.problem("SOURCE_NOT_FOUND", "최적화를 찾을 수 없습니다")
        return
    r.links["opt_id"] = opt["id"]
    olabel = so_repo.opt_label(opt["opt_no"])
    if src.pick == "best":
        best = opt.get("best") or {}
        if not best.get("batch_id") or best.get("doe_no") is None:
            r.problem("OPT_DESIGN_UNAVAILABLE", "검증된 최적 설계가 없습니다")
            return
        r.label = f"⑥ {olabel} 최적 설계"
        _from_batch_run(ctx, conn, study, r, best["batch_id"], int(best["doe_no"]))
    elif src.pick == "run":
        it = so_repo.get_iter(conn, opt["id"], int(src.iter_no))
        if it is None:
            r.problem("OPT_DESIGN_UNAVAILABLE", f"반복 {src.iter_no}을 찾을 수 없습니다")
            return
        r.label = f"⑥ {olabel} 반복 {src.iter_no} DOE #{src.doe_no}"
        _from_batch_run(ctx, conn, study, r, it["batch_id"], int(src.doe_no))
    elif src.pick == "final_optimum":
        fb = (opt.get("final") or {}).get("batch_id")
        if not fb:
            r.problem("OPT_DESIGN_UNAVAILABLE", "마무리 캡처(최적안) 배치가 없습니다")
            return
        r.label = f"⑥ {olabel} 최적안(마무리)"
        _from_batch_run(ctx, conn, study, r, fb, 2)
    else:  # surrogate_optimum
        vals = _opt_values_source(conn, opt, study_root(ctx, study))
        if not vals:
            r.problem("OPT_DESIGN_UNAVAILABLE", "대리모델 예측 최적안이 없습니다")
            return
        r.label = f"⑥ {olabel} 대리모델 예측 최적안(미검증)"
        _from_values(ctx, conn, study, r, _ValuesSrc(opt["param_set_id"], opt["model_id"], vals,
                                                     input=ik.to_public(opt["input_kind"])))  # ⑥ 입력 종류 승계


def resolve(ctx: AppContext, conn: Any, study: dict[str, Any], src: Any) -> Resolved:
    """출처 해석(§21.3.2). problems는 422 FEM_VERIFY_INVALID 후보, 모양 오류는 즉시 422 INVALID_PARAMS."""
    kind = src.kind
    if kind == "predict_job":
        r = Resolved("PREDICT_JOB", {"job_id": src.job_id}, "")
        j = _require_study_job(conn, study, src.job_id)
        if j is None:
            r.problem("SOURCE_NOT_FOUND", "예측 작업을 찾을 수 없습니다")
            return r
        r.label = _predict_label(j)
        r.links["predict_job_id"] = j["id"]
        ref = pb_repo.batch_run_ref(j)
        if ref is not None:
            r.links.update(batch_id=ref[0], doe_no=ref[1])
        _fill_from_predict(ctx, conn, study, r, j)
    elif kind == "batch_run":
        r = Resolved("BATCH_RUN", {"batch_id": src.batch_id, "doe_no": int(src.doe_no)}, "")
        b = pb_repo.get(conn, src.batch_id)
        r.label = f"B-{b['batch_no']:03d} DOE #{src.doe_no}" if b else "일괄 예측 run"
        _from_batch_run(ctx, conn, study, r, src.batch_id, int(src.doe_no))
    elif kind == "values":
        origin = src.origin.model_dump() if getattr(src, "origin", None) else None
        r = Resolved("VALUES", {"param_set_id": src.param_set_id, "model_id": src.model_id, "values": dict(src.values),
                                "reuse_existing": bool(src.reuse_existing), "origin": origin}, "템플릿 값")
        if origin:
            r.label = "⑥ 최적화 결과 설계점"
        _from_values(ctx, conn, study, r, src)
    else:
        r = Resolved("OPT_DESIGN", {"opt_id": src.opt_id, "pick": src.pick, "iter_no": src.iter_no, "doe_no": src.doe_no}, "")
        _from_opt(ctx, conn, study, r, src)
    r.source_ref.update({"label": r.label, "values": dict(r.values)})
    if r.predict_job is not None:
        r.source_ref["predict_job_id"] = r.predict_job["id"]
    return r


def input_is_assembly(r: Resolved) -> bool:
    """P 입력이 조립 상태(starter가 eps_mesh 아님). 동반 예측은 조립 템플릿이면 True."""
    if r.companion is not None:
        return r.template_kind == "assembly"
    return bool(r.input_rel) and bool(r.starter) and not is_mesh_file(r.starter or "")


__all__ = ["Resolved", "resolve", "input_is_assembly", "DomainError"]
