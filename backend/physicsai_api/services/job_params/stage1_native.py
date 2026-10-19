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
DOE_LABEL_NATIVE = "LHS(native)"


def native_extract_params(ctx: AppContext, p: Any) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    cfg = ctx.settings
    require_native_available(cfg)
    cp = check_user_path(p.cad_path, allowed_roots(cfg, imports=True), expect="file")
    if os.path.splitext(cp.path)[1].lower() not in [e.lower() for e in cfg.geometry.step_extensions]:
        raise invalid_at("cad_path", f"STEP 확장자는 {', '.join(cfg.geometry.step_extensions)} 중 하나여야 합니다")
    return {"cad_path": cp.path, "engine": "native"}, None, []


def native_doe_gen(ctx: AppContext, setup: dict[str, Any], p: Any) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    cfg = ctx.settings
    require_native_available(cfg)
    if not setup.get("features_rel") or not setup.get("cad_file_name") or not tp.used(setup.get("parameters") or []):
        raise DomainError("PREREQUISITE_MISSING", "형상 피처와 사용 파라미터가 필요합니다(①-1을 native로 먼저)", status=409,
                          missing=["GEOM_FEATURES"])
    if p.options:
        raise invalid_at("options", "native DOE는 options를 쓸 수 없습니다(seed 사용)", "DOE_OPTIONS_INVALID")
    if p.num_runs is None or not 2 <= p.num_runs <= cfg.train_data.max_runs:
        raise invalid_at("num_runs", f"run 수는 2~{cfg.train_data.max_runs}", "DOE_OPTIONS_INVALID")
    if p.multi_execution > cfg.train_data.max_multi_execution:
        raise invalid_at("multi_execution", f"동시 실행 수는 1~{cfg.train_data.max_multi_execution}")
    if p.radioss_assem_path is None:
        raise invalid_at("radioss_assem_path", "조립 폴더 경로가 필요합니다")
    cp = check_user_path(p.radioss_assem_path, allowed_roots(cfg, imports=True))
    names = {n.lower() for n in os.listdir(cp.path)}
    st = starters_in(cp.path, cfg.predict.starter_glob)
    missing = []
    if len(st) != 1:
        missing.append("RADIOSS_STARTER")
    if cfg.predict.mesh_include_name.lower() not in names:
        missing.append("BASELINE_INC")
    if cfg.predict.renum_csv_name.lower() not in names:
        missing.append("RENUM_CSV")
    if missing:
        raise DomainError("PREREQUISITE_MISSING", "조립 폴더에 starter 1개·기준 메시·번호 재지정 표가 모두 있어야 합니다", status=409,
                          missing=missing)
    seed = p.seed if p.seed is not None else 1
    doe_id = str(uuid.uuid4())
    params = {"engine": "native", "doe_label": p.doe_label, "doe_type": DOE_TYPE_NATIVE, "num_runs": p.num_runs,
              "default_runs": p.num_runs, "options": {}, "seed": seed, "multi_execution": p.multi_execution,
              "radioss_assem_path": cp.path, "doe_id": doe_id}
    return params, {"doe_id": doe_id}, []


def native_doe_from_set(ctx: AppContext, conn: Any, study: dict[str, Any], p: Any
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
        raise DomainError("ENGINE_MISMATCH", "세트 기준 DOE는 native 형상 엔진 세트에서만 만듭니다", status=409)
    native_set_gate(ctx, ps)
    require_map_confirmed(ctx, ps)
    if p.options:
        raise invalid_at("options", "native DOE는 options를 쓸 수 없습니다(seed 사용)", "DOE_OPTIONS_INVALID")
    if p.radioss_assem_path is not None:
        raise invalid_at("radioss_assem_path", "세트 기준 DOE는 세트의 조립 폴더를 씁니다(radioss_assem_path 생략)")
    if p.num_runs is None or not 2 <= p.num_runs <= cfg.train_data.max_runs:
        raise invalid_at("num_runs", f"run 수는 2~{cfg.train_data.max_runs}", "DOE_OPTIONS_INVALID")
    if p.multi_execution > cfg.train_data.max_multi_execution:
        raise invalid_at("multi_execution", f"동시 실행 수는 1~{cfg.train_data.max_multi_execution}")
    seed = p.seed if p.seed is not None else 1
    doe_id = str(uuid.uuid4())
    params = {"engine": "native", "doe_label": p.doe_label, "doe_type": DOE_TYPE_NATIVE, "num_runs": p.num_runs,
              "default_runs": p.num_runs, "options": {}, "seed": seed, "multi_execution": p.multi_execution,
              "radioss_assem_path": os.path.join(set_path(ctx, ps), "radioss_assem"), "doe_id": doe_id, "param_set_id": ps["id"]}
    return params, {"doe_id": doe_id, "param_set_id": ps["id"]}, []
