"""① native 형상 엔진 작업 params·사전조건(geometry-engine.md §7.3.1·§7.3.3): TD_EXTRACT_PARAMS·TD_DOE_GEN의 native 분기."""

from __future__ import annotations

import os
import uuid
from typing import Any

from physicsai_core.errors import DomainError
from physicsai_core.paths import allowed_roots, check_user_path
from physicsai_core.stage1_train_data import train_params as tp

from ...context import AppContext
from ..geometry_gate import require_native_available
from ..path_inspect import starters_in
from .base import invalid_at

DOE_TYPE_NATIVE = "NATIVE_LHS"
DOE_LABEL_NATIVE = "LHS(Native)"


def _native_doe_common(cfg: Any, p: Any, samples: Any = None, names: list[str] | None = None) -> tuple[str, int, int, int, str]:
    """native DOE 공통 입력(geometry-engine.md §7.3.3 + phase3 §23.4 S18 통합) → (doe_label, num_runs, seed, 동시 수, 실패 처리).

    native는 S18 생성 방식 `platform`의 한 경로(LHS + paicad)다. `generator`는 생략 또는 platform만.
    입력은 두 모양 중 하나: (a) 계약 §7.3.3 `{doe_label?, num_runs, seed?}` (b) S18 `sampling:{kind:"lhs", count, seed}`.
    동시 수 생략 = S18 플랫폼 기본(min(platform_parallel_default, max_multi_execution)). 실패 처리 생략 = continue(스킵 후 경고).
    """
    if p.generator == "hyperstudy":
        raise invalid_at("generator", "Native 형상 엔진 DOE는 플랫폼 생성(LHS)만 됩니다")
    if p.options:
        raise invalid_at("options", "Native DOE는 options를 쓸 수 없습니다(seed 사용)", "DOE_OPTIONS_INVALID")
    given = p.model_fields_set
    if p.sampling is not None and p.sampling.model_dump().get("kind") == "train_doe":  # equiv-check.md Q1: 표본표 재사용(run 이름 유지)
        from physicsai_core.stage1_train_data import doe_reuse

        for k in ("num_runs", "seed"):
            if k in given:
                raise invalid_at(k, f"표본표 재사용(sampling.kind=train_doe)에서는 {k}를 쓸 수 없습니다")
        mism = doe_reuse.name_mismatch(samples, names or []) if samples else {"code": "SOURCE_DOE_NOT_FOUND", "message": "원본 DOE 표본표가 없습니다"}
        if mism is not None:
            raise DomainError("DOE_SAMPLING_INVALID", "표본을 만들 수 없습니다", status=422, problems=[mism])
        rows, _skipped = doe_reuse.matrix_rows(samples, names or [])
        if not 2 <= len(rows) <= cfg.train_data.max_runs:
            raise DomainError("DOE_SAMPLING_INVALID", "표본을 만들 수 없습니다", status=422,
                              problems=[{"code": "TOO_FEW_ROWS" if len(rows) < 2 else "TOO_MANY_ROWS",
                                         "message": f"재사용할 run이 {len(rows)}개입니다(2~{cfg.train_data.max_runs})"}])
        cap = cfg.train_data.max_multi_execution
        multi = min(cfg.train_data.platform_parallel_default, cap) if p.multi_execution is None else p.multi_execution
        if multi > cap:
            raise invalid_at("multi_execution", f"동시 실행 수는 1~{cap}")
        return p.doe_label or "표본표 재사용(Native)", len(rows), 1, multi, p.on_run_failure or "continue"
    if p.sampling is not None:
        sp = p.sampling.model_dump()
        if sp.get("kind") != "lhs":
            raise DomainError("DOE_SAMPLING_INVALID", "표본을 만들 수 없습니다", status=422,
                              problems=[{"code": "DESIGN_UNSUPPORTED",
                                         "message": "Native 형상 엔진 DOE는 표본 방식 LHS만 지원합니다"}])
        for k in ("num_runs", "seed"):
            if k in given:
                raise invalid_at(k, f"표본 방식(sampling)을 쓰면 {k}를 함께 쓸 수 없습니다")
        num_runs, seed = sp.get("count"), sp.get("seed")
    else:
        num_runs, seed = p.num_runs, p.seed
    if num_runs is None or not 2 <= num_runs <= cfg.train_data.max_runs:
        raise invalid_at("num_runs", f"run 수는 2~{cfg.train_data.max_runs}", "DOE_OPTIONS_INVALID")
    cap = cfg.train_data.max_multi_execution
    multi = min(cfg.train_data.platform_parallel_default, cap) if p.multi_execution is None else p.multi_execution
    if multi > cap:
        raise invalid_at("multi_execution", f"동시 실행 수는 1~{cap}")
    return p.doe_label or DOE_LABEL_NATIVE, int(num_runs), int(seed if seed is not None else 1), multi, p.on_run_failure or "continue"


def normalized_filter(raw: Any) -> dict[str, Any] | None:
    """요청 extract_filter(스키마 객체|dict|None) → 정규화본. 값 오류는 422 EXTRACT_FILTER_INVALID(problems[{key, message}])."""
    from physicsai_core.geometry.extract_filter import normalize

    if raw is None:
        return None
    norm, probs = normalize(raw.model_dump() if hasattr(raw, "model_dump") else raw)
    if probs:
        raise DomainError("EXTRACT_FILTER_INVALID", "추출 조건이 올바르지 않습니다", status=422, problems=probs)
    return norm


def raise_filter_unsupported() -> None:
    from physicsai_core.geometry.extract_filter import UNSUPPORTED_MESSAGE

    raise DomainError("EXTRACT_FILTER_UNSUPPORTED", UNSUPPORTED_MESSAGE, status=422)


def guard_extract_filter(ctx: AppContext, p: Any) -> None:
    """①-1 요청 검증 분기 1곳(V-EF-12): extract_filter가 왔는데 엔진이 altair이거나 kind=shell이면 422 EXTRACT_FILTER_UNSUPPORTED.
    엔진 = 요청 engine, 생략 시 geometry.engine. 그 밖 altair 처리는 건드리지 않는다."""
    if getattr(p, "extract_filter", None) is None:
        return
    if (p.engine or ctx.settings.geometry.engine) != "native" or getattr(p, "kind", None) == "shell":
        raise_filter_unsupported()


def native_extract_params(ctx: AppContext, p: Any) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    cfg = ctx.settings
    require_native_available(cfg)
    cp = check_user_path(p.cad_path, allowed_roots(cfg, imports=True), expect="file")
    if os.path.splitext(cp.path)[1].lower() not in [e.lower() for e in cfg.geometry.step_extensions]:
        raise invalid_at("cad_path", f"STEP 확장자는 {', '.join(cfg.geometry.step_extensions)} 중 하나여야 합니다")
    if getattr(p, "kind", None) == "shell":
        from ..geometry_gate import require_shell_available

        require_shell_available(cfg)
        return {"cad_path": cp.path, "engine": "native", "kind": "shell"}, None, []
    out: dict[str, Any] = {"cad_path": cp.path, "engine": "native"}
    norm = normalized_filter(getattr(p, "extract_filter", None))  # extract-filter.md §6.1: 서버 정규화본을 params에 기록
    if norm is not None:
        out["extract_filter"] = norm
    return out, None, []


def _sampling_param(p: Any) -> dict[str, Any]:
    sp = p.sampling.model_dump() if p.sampling is not None else None
    return {"sampling": sp} if sp and sp.get("kind") == "train_doe" else {}


def native_doe_gen(ctx: AppContext, setup: dict[str, Any], p: Any, samples: Any = None
                   ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    cfg = ctx.settings
    require_native_available(cfg)
    if not setup.get("features_rel") or not setup.get("cad_file_name") or not tp.used(setup.get("parameters") or []):
        raise DomainError("PREREQUISITE_MISSING", "형상 피처와 사용 파라미터가 필요합니다(①-1을 Native로 먼저)", status=409,
                          missing=["GEOM_FEATURES"])
    label, num_runs, seed, multi, on_fail = _native_doe_common(cfg, p, samples, [q["name"] for q in tp.used(setup.get("parameters") or [])])
    if p.radioss_assem_path is None:
        raise invalid_at("radioss_assem_path", "조립 폴더 경로가 필요합니다")
    cp = check_user_path(p.radioss_assem_path, allowed_roots(cfg, imports=True))
    names = {n.lower() for n in os.listdir(cp.path)}
    st = starters_in(cp.path, cfg.predict.starter_glob)
    missing = []
    if len(st) != 1:
        missing.append("RADIOSS_STARTER")
    from physicsai_core.geometry.shell_native import kind_of_features_rel

    shell = kind_of_features_rel(setup.get("features_rel")) == "shell"  # shell-morph.md §8.2: 쉘은 기준 메시·RENUM 불필요
    if shell:
        from ..geometry_gate import require_shell_available

        require_shell_available(cfg)
    if cfg.predict.mesh_include_name.lower() not in names and not shell:
        missing.append("BASELINE_INC")
    if cfg.predict.renum_csv_name.lower() not in names and not shell:
        missing.append("RENUM_CSV")
    if missing:
        raise DomainError("PREREQUISITE_MISSING", "조립 폴더에 starter 1개·기준 메시·번호 재지정 표가 모두 있어야 합니다", status=409,
                          missing=missing)
    doe_id = str(uuid.uuid4())
    params = {"engine": "native", "generator": "platform", "doe_label": label, "doe_type": DOE_TYPE_NATIVE,
              "num_runs": num_runs, "default_runs": num_runs, "options": {}, "seed": seed, "multi_execution": multi,
              "on_run_failure": on_fail, "radioss_assem_path": cp.path, "doe_id": doe_id, **_sampling_param(p)}
    return params, {"doe_id": doe_id}, []


def native_doe_from_set(ctx: AppContext, conn: Any, study: dict[str, Any], p: Any, samples: Any = None
                        ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """세트 기준 native DOE(§7.3.6·§7.3.8·§11.1): 준비본 READY(baseline별) + 다중 baseline이면 매칭표 확정(409 PARAM_MAP_UNCONFIRMED)."""
    from physicsai_core.db.repositories import param_sets as ps_repo

    from ..geometry_gate import native_set_gate, require_map_confirmed
    from ..param_set_native_api import set_path

    cfg = ctx.settings
    require_native_available(cfg)
    ps = ps_repo.get(conn, p.param_set_id)
    if ps is None or ps["study_id"] != study["id"]:
        raise DomainError("PREREQUISITE_MISSING", "파라미터 세트를 찾을 수 없습니다", status=409, missing=["PARAM_SET"])
    if ps.get("engine") != "native":
        raise DomainError("ENGINE_MISMATCH", "세트 기준 DOE는 Native 형상 엔진 세트에서만 만듭니다", status=409)
    native_set_gate(ctx, ps)
    require_map_confirmed(ctx, ps)
    if p.radioss_assem_path is not None:
        raise invalid_at("radioss_assem_path", "세트 기준 DOE는 세트의 조립 폴더를 씁니다(radioss_assem_path 생략)")
    if samples is not None and os.path.isfile(os.path.join(set_path(ctx, ps), "param_map.json")):
        raise DomainError("DOE_SAMPLING_INVALID", "표본을 만들 수 없습니다", status=422,
                          problems=[{"code": "DESIGN_UNSUPPORTED", "message": "다중 baseline 세트에서는 표본표 재사용을 지원하지 않습니다"}])
    label, num_runs, seed, multi, on_fail = _native_doe_common(cfg, p, samples, [str(r["name"]) for r in ps["parameters"]])
    doe_id = str(uuid.uuid4())
    params = {"engine": "native", "generator": "platform", "doe_label": label, "doe_type": DOE_TYPE_NATIVE,
              "num_runs": num_runs, "default_runs": num_runs, "options": {}, "seed": seed, "multi_execution": multi,
              "on_run_failure": on_fail, "radioss_assem_path": os.path.join(set_path(ctx, ps), "radioss_assem"),
              "doe_id": doe_id, "param_set_id": ps["id"], **_sampling_param(p)}
    return params, {"doe_id": doe_id, "param_set_id": ps["id"]}, []
