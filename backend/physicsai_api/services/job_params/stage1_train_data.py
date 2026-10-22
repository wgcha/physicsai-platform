"""① 학습데이터 생성 작업 params·사전조건(phase2 §6.1.1, §6.2~§6.6.1): TD_*."""

from __future__ import annotations

import os
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import FEATURES, missing_for, train_doe_platform_missing
from physicsai_core.naming import NAME_RE, RUN_KEY_RE
from physicsai_core.paths import allowed_roots, check_user_path
from physicsai_core.stage1_train_data import doe_platform
from physicsai_core.stage1_train_data import doe_types as dt_mod
from physicsai_core.stage1_train_data import train_params as tp
from physicsai_core.stage1_train_data import train_tpl
from physicsai_core.stage1_train_data.train_tpl import tpl_params_snapshot
from physicsai_core.stage4_predict.batch_matrix import BatchShapeError

from ...context import AppContext
from ...schemas.extract_filter import ExtractFilter
from ...schemas.stage1_train_data import TrainSampling
from ..path_inspect import starters_in
from .base import HpcOverrides, _P, invalid_at, invalid_errors, prerequisite_missing, raise_feature_missing
from .stage1_native import native_doe_from_set, native_doe_gen, native_extract_params


class TdExtractParams(_P):
    cad_path: str = Field(max_length=400)
    engine: Literal["altair", "native"] | None = None  # geometry-engine.md §7.3.1: 생략 = geometry.engine 기본값, 서버가 params.engine에 기록
    kind: Literal["solid", "shell"] | None = None  # shell-morph.md §8.2: native 형상 종류(생략 = solid). shell = 중립면 STEP 비드 추출
    extract_filter: ExtractFilter | None = None  # extract-filter.md §6.1: native 솔리드만(altair·shell은 422 EXTRACT_FILTER_UNSUPPORTED). 생략 = 현행


class TdDoeGenParams(_P):
    """①-3 DOE 생성(phase2 §6.4 + phase3 §23.4 S18). generator 생략 → sampling이 있으면 platform, 없으면 hyperstudy(G10).
    platform: sampling 필수, doe_label·num_runs·options 금지. hyperstudy: 기존 키(doe_label 필수), sampling·on_run_failure 금지."""

    generator: Literal["platform", "hyperstudy"] | None = None
    doe_label: str | None = Field(default=None, max_length=120)
    num_runs: int | None = Field(default=None, ge=2)
    options: dict[str, Any] | None = None
    sampling: TrainSampling | None = None
    seed: int | None = Field(default=None, ge=0)  # native LHS 전용(geometry-engine.md §7.3.3). altair는 쓸 수 없다
    multi_execution: int | None = Field(default=None, ge=1)
    # 세트 기준 native DOE(geometry-engine.md §7.3.8·§11.1)면 생략(세트 조립 폴더 사용), 그 밖에는 필수
    radioss_assem_path: str | None = Field(default=None, max_length=400)
    on_run_failure: Literal["fail", "continue"] | None = None
    # native 파라미터 세트 기준 DOE(쉘 두께·다중 baseline 포함). 지정하면 ①-1 setup 대신 세트 준비본·파라미터 표를 쓴다
    param_set_id: str | None = Field(default=None, max_length=64)
    # 조립 매칭 확정본(asm-match.md §6.4, ①-1 Native 솔리드 기준 DOE만): 있으면 기준 메시·RENUM 파일 없이 매칭 PART id가 기준본. 세트 기준·쉘은 쓸 수 없다
    asm_match_id: str | None = Field(default=None, max_length=64)


class TdSolveParams(_P):
    doe_id: str
    run_keys: list[Annotated[str, Field(pattern=RUN_KEY_RE.pattern)]] | None = None
    hpc: HpcOverrides | None = None
    on_run_failure: Literal["collect_partial", "fail"] = "collect_partial"


class TdResultImportParams(_P):
    doe_id: str
    source_path: str = Field(max_length=400)


class ResponseDefIn(_P):
    name: str = Field(pattern=NAME_RE.pattern)
    unit: str = Field(default="", max_length=40)
    spec: dict[str, Any] = Field(default_factory=dict)


class TdRespExtractParams(_P):
    doe_id: str
    responses: list[ResponseDefIn] = Field(min_length=1)


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "TD_EXTRACT_PARAMS": TdExtractParams,
    "TD_DOE_GEN": TdDoeGenParams,
    "TD_SOLVE": TdSolveParams,
    "TD_RESULT_IMPORT": TdResultImportParams,
    "TD_RESP_EXTRACT": TdRespExtractParams,
}


def _ready_doe(conn: Any, sid: str, doe_id: str) -> dict[str, Any]:
    d = train_repo.get_doe(conn, doe_id)
    if d is None or d["study_id"] != sid or d["status"] != "READY":
        raise DomainError("DOE_NOT_READY", "READY 상태의 DOE가 필요합니다", status=409)
    return d


def tpl_is_stale(setup: dict[str, Any]) -> bool:
    if not setup.get("tpl_rel"):
        return False
    snap = setup.get("tpl_params")
    if train_tpl.is_full_snapshot(snap):  # 전체 tpl(altair-vars.md AV-1·AV-4): 모든 유효 행 기록과 비교
        return snap != train_tpl.expected_snapshot(setup.get("parameters") or [])
    return snap != tpl_params_snapshot(tp.used(setup.get("parameters") or []))  # 옛 부분 tpl


def doe_generator(p: TdDoeGenParams) -> str:
    """생성 방식 확정(§23.4 G10) + 방식별 금지 키(422 INVALID_PARAMS). 키 존재는 요청에 적힌 것 기준(model_fields_set)."""
    given = p.model_fields_set
    gen = p.generator or ("platform" if p.sampling is not None else "hyperstudy")
    if gen == "platform":
        if p.sampling is None:
            raise invalid_at("sampling", "플랫폼 생성에는 표본 방식(sampling)이 필요합니다")
        for k in ("doe_label", "num_runs", "options"):
            if k in given:
                raise invalid_at(k, f"플랫폼 생성에서는 {k}를 쓸 수 없습니다(표본 방식 sampling으로 정합니다)")
    else:
        for k in ("sampling", "on_run_failure"):
            if k in given:
                raise invalid_at(k, f"원본 HyperStudy 생성에서는 {k}를 쓸 수 없습니다")
    return gen


def reuse_samples(ctx: AppContext, conn: Any, study: dict[str, Any], sampling: Any) -> Any:
    """①-3 표본표 재사용(equiv-check.md Q1): sampling.kind == train_doe면 원본 DOE samples.csv를 읽어 (헤더, 행)으로, 아니면 None.
    원본이 없거나 준비 안 됨 → 422 DOE_SAMPLING_INVALID(problems)."""
    from physicsai_core.stage1_train_data import doe_reuse

    sp = sampling.model_dump() if hasattr(sampling, "model_dump") else sampling
    if not doe_reuse.is_reuse(sp):
        return None
    from ..common import study_root

    samples, prob = doe_reuse.load_reuse_samples(conn, study["id"], study_root(ctx, study), str(sp["doe_id"]))
    if prob is not None:
        raise DomainError("DOE_SAMPLING_INVALID", "표본을 만들 수 없습니다", status=422, problems=[prob])
    return samples


def _prepare_platform(cfg: Any, setup: dict[str, Any], p: TdDoeGenParams, assem_path: str, samples: Any = None
                      ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """플랫폼 DOE(§23.4): 동시 수(기본 min(platform_parallel_default, max_multi_execution)) → 표본 검증(lhs_opt는 lhs로 대신)."""
    td = cfg.train_data
    cap = td.max_multi_execution
    multi = min(td.platform_parallel_default, cap) if p.multi_execution is None else p.multi_execution
    if multi > cap:
        raise invalid_at("multi_execution", f"동시 실행 수는 1~{cap}")
    assert p.sampling is not None
    try:
        plan = doe_platform.check(p.sampling.model_dump(), setup, cfg, samples=samples)
    except BatchShapeError as exc:
        raise invalid_at("sampling", str(exc)) from None
    if plan.problems or not plan.rows:
        raise DomainError("DOE_SAMPLING_INVALID", "표본을 만들 수 없습니다", status=422,
                          problems=[{"code": x["code"], "message": x["message"]} for x in plan.problems]
                          or [{"code": "TOO_FEW_ROWS", "message": "표본이 없습니다"}])
    doe_id = str(uuid.uuid4())
    params = {"generator": "platform", "doe_id": doe_id, "doe_label": plan.label, "doe_type": plan.doe_type,
              "sampling": {"kind": plan.kind, **plan.input}, "num_runs": plan.run_count, "multi_execution": multi,
              "on_run_failure": p.on_run_failure or "fail", "radioss_assem_path": assem_path}
    warnings = [{"code": n["code"], "message": n["message"]} for n in plan.notes]
    return params, {"doe_id": doe_id}, warnings


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 기능 확인(check_feature)은 디스패처가 먼저 한다."""
    cfg = ctx.settings
    sid = study["id"]
    if job_type == "TD_EXTRACT_PARAMS" and (p.engine or cfg.geometry.engine) == "native":
        return native_extract_params(ctx, p)
    if job_type == "TD_EXTRACT_PARAMS":
        cp = check_user_path(p.cad_path, allowed_roots(cfg, imports=True), expect="file")
        if os.path.splitext(cp.path)[1].lower() not in [e.lower() for e in cfg.train_data.cad_extensions]:
            raise invalid_at("cad_path", f"CAD 확장자는 {', '.join(cfg.train_data.cad_extensions)} 중 하나여야 합니다")
        return {"cad_path": cp.path}, None, []
    if job_type == "TD_DOE_GEN" and p.asm_match_id is not None and p.param_set_id is not None:
        raise invalid_at("asm_match_id", "세트 기준 DOE는 세트의 조립 매칭을 씁니다(asm_match_id 생략)")
    if job_type == "TD_DOE_GEN" and p.param_set_id is not None:
        return native_doe_from_set(ctx, conn, study, p, reuse_samples(ctx, conn, study, p.sampling))
    if job_type == "TD_DOE_GEN" and p.radioss_assem_path is None:
        raise invalid_at("radioss_assem_path", "조립 폴더 경로가 필요합니다")
    if job_type == "TD_DOE_GEN":
        setup = train_repo.get_setup(conn, sid)
        if p.asm_match_id is not None and not (setup is not None and setup.get("engine") == "native"):
            raise invalid_at("asm_match_id", "조립 매칭은 Native 형상 엔진 DOE에서만 쓸 수 있습니다")
        if setup is not None and setup.get("engine") == "native":  # native = 플랫폼 생성의 한 경로(자체 게이트, §7.3.3)
            return native_doe_gen(ctx, setup, p, reuse_samples(ctx, conn, study, p.sampling), study=study)
        gen = doe_generator(p)
        if gen == "hyperstudy":
            raise_feature_missing(*missing_for(cfg, FEATURES["train_doe"], None))
        else:
            raise_feature_missing(*train_doe_platform_missing(cfg))
        if p.seed is not None:
            raise invalid_at("seed", "seed는 Native 형상 엔진 DOE에서만 쓸 수 있습니다")
        if setup is None or not setup.get("tpl_rel"):
            raise DomainError("TPL_REQUIRED", "tpl을 먼저 생성하세요(①-2)", status=409)
        if tpl_is_stale(setup):
            raise DomainError("TPL_STALE", "파라미터 표가 바뀌었습니다 — tpl을 다시 생성하세요", status=409)
        cp = check_user_path(p.radioss_assem_path, allowed_roots(cfg, imports=True))
        st = starters_in(cp.path, cfg.predict.starter_glob)
        if len(st) != 1:
            raise DomainError("PREREQUISITE_MISSING", f"Radioss 조립 폴더에 starter({cfg.predict.starter_glob})가 정확히 1개 있어야 합니다(현재 {len(st)}개)",
                              status=409, missing=["RADIOSS_STARTER"])
        if gen == "platform":
            return _prepare_platform(cfg, setup, p, cp.path, reuse_samples(ctx, conn, study, p.sampling))
        if p.doe_label is None:
            raise invalid_errors([{"loc": ["params", "doe_label"], "msg": "Field required"}])
        types = dt_mod.load_doe_types(cfg.resources.doe_design_type_json, cfg.ui.max_artifact_bytes)
        t = dt_mod.find(types, p.doe_label)
        if t is None:
            raise invalid_at("doe_label", f"알 수 없는 DOE 유형: {p.doe_label}", "DOE_TYPE_UNKNOWN")
        if not t["runs_editable"] and p.num_runs is not None:
            raise invalid_at("num_runs", "이 DOE 유형은 run 수를 직접 정할 수 없습니다(HyperStudy가 결정)", "DOE_OPTIONS_INVALID")
        num_runs = (p.num_runs if p.num_runs is not None else t["default_runs"]) if t["runs_editable"] else None
        if num_runs is not None and not 2 <= num_runs <= cfg.train_data.max_runs:
            raise invalid_at("num_runs", f"run 수는 2~{cfg.train_data.max_runs}", "DOE_OPTIONS_INVALID")
        options = dict(p.options or {})
        probs = dt_mod.validate_options(t, options)
        if probs:
            raise DomainError("DOE_OPTIONS_INVALID", "DOE 옵션이 올바르지 않습니다", status=422, problems=probs)
        multi = 1 if p.multi_execution is None else p.multi_execution
        if multi > cfg.train_data.max_multi_execution:
            raise invalid_at("multi_execution", f"동시 실행 수는 1~{cfg.train_data.max_multi_execution}")
        doe_id = str(uuid.uuid4())
        params = {"generator": "hyperstudy", "doe_label": t["label"], "doe_type": t["value"], "num_runs": num_runs,
                  "default_runs": t["default_runs"], "options": options, "multi_execution": multi,
                  "radioss_assem_path": cp.path, "doe_id": doe_id}
        return params, {"doe_id": doe_id}, []
    if job_type == "TD_SOLVE":
        d = _ready_doe(conn, sid, p.doe_id)
        av = ctx.hpc.availability()
        if not av.configured:
            raise DomainError("HPC_NOT_CONFIGURED", "PBS 연결 안 됨 — DOE 입력 폴더를 직접 해석한 뒤 ①-5에서 결과 폴더를 지정하세요",
                              status=409, mode=av.mode)
        runs = train_repo.runs_for_doe(conn, d["id"])
        keys = {r["run_key"] for r in runs}
        if p.run_keys is not None:
            unknown = [k for k in p.run_keys if k not in keys]
            if unknown or not p.run_keys:
                raise invalid_at("run_keys", f"DOE에 없는 run: {', '.join(unknown[:10])}" if unknown else "run이 비어 있습니다")
            n = len(set(p.run_keys))
        else:
            n = sum(1 for r in runs if r["state"] in train_repo.RESUBMIT_STATES)
            if n == 0:
                raise prerequisite_missing("SUBMITTABLE_RUN")
        if n > cfg.train_data.max_runs_per_submit:
            raise invalid_at("run_keys", f"한 번에 제출할 수 있는 run은 {cfg.train_data.max_runs_per_submit}개입니다")
        params = {"doe_id": d["id"], "run_keys": sorted(set(p.run_keys)) if p.run_keys else None,
                  "hpc": p.hpc.model_dump() if p.hpc else None, "on_run_failure": p.on_run_failure}
        return params, {"doe_id": d["id"]}, []
    if job_type == "TD_RESULT_IMPORT":
        d = _ready_doe(conn, sid, p.doe_id)
        roots = allowed_roots(cfg, imports=True)
        if cfg.hpc.transfer.collect_root_local:
            roots.append(cfg.hpc.transfer.collect_root_local)
        cp = check_user_path(p.source_path, roots)
        return {"doe_id": d["id"], "source_path": cp.path}, {"doe_id": d["id"]}, []
    if job_type == "TD_RESP_EXTRACT":
        d = _ready_doe(conn, sid, p.doe_id)
        if train_repo.run_state_counts(conn, d["id"])["COLLECTED"] < 1:
            raise prerequisite_missing("COLLECTED_RUN")
        names = [r.name for r in p.responses]
        if len(set(names)) != len(names):
            raise invalid_at("responses", "응답 이름이 중복됩니다")
        return {"doe_id": d["id"], "responses": [r.model_dump() for r in p.responses]}, {"doe_id": d["id"]}, []
    raise invalid_at("job_type", "unknown")


def after_insert(conn: Any, principal: Any, study: dict[str, Any], job_type: str, job_id: str, params: dict[str, Any],
                 result: dict[str, Any] | None) -> None:
    """작업 생성과 같은 트랜잭션에서 DOE 행(BUILDING) 생성(B8 방식)."""
    base = {"study_id": study["id"], "job_id": job_id, "created_by": principal.user_id,
            "created_by_name": principal.display_name}
    if job_type == "TD_DOE_GEN":
        did = params["doe_id"]
        platform = params.get("generator") == "platform"
        native = {"engine": "native"} if params.get("engine") == "native" else {}
        if native:  # geometry-engine.md §7.3.3: native = 플랫폼 생성(LHS) + paicad. options = {seed(, param_set_id)}, sampling 없음(표본표 재사용이면 기록)
            sp = params.get("sampling")
            if sp and sp["kind"] != "train_doe":  # doe-methods.md §5.1: lhs 밖 표본 방식 — options = 정규화 입력(+ param_set_id), sampling = {kind, input, meta: null}
                inp = doe_platform.stored_input(sp["kind"], {k: v for k, v in sp.items() if k != "kind"}, params["num_runs"])
                opts = {**inp, **({"param_set_id": params["param_set_id"]} if params.get("param_set_id") else {})}
                extra = {"options": opts, "generator": "PLATFORM", "sampling": {"kind": sp["kind"], "input": inp, "meta": None}}
            else:
                opts = {"seed": params["seed"], **({"param_set_id": params["param_set_id"]} if params.get("param_set_id") else {})}
                extra = {"options": opts, "generator": "PLATFORM",
                         "sampling": {"kind": sp["kind"], "input": {k: v for k, v in sp.items() if k != "kind"}, "meta": None} if sp else None}
        elif platform:  # §23.4: options = 정규화 표본 입력(kind 제외), sampling = {kind, input, meta: null}(DG_PREP이 meta)
            inp = doe_platform.stored_input(params["sampling"]["kind"], {k: v for k, v in params["sampling"].items() if k != "kind"},
                                            params["num_runs"])  # table = 본문 대신 행 수(DM-C3)
            extra = {"options": inp, "generator": "PLATFORM",
                     "sampling": {"kind": params["sampling"]["kind"], "input": inp, "meta": None}}
        else:
            extra = {"options": params["options"], "generator": "HYPERSTUDY", "sampling": None}
        train_repo.insert_doe(conn, {
            **base, "id": did, "doe_label": params["doe_label"], "doe_type": params["doe_type"],
            "num_runs_requested": params["num_runs"], **extra,
            "multi_execution": params["multi_execution"], "radioss_assem_source_path": params["radioss_assem_path"],
            "dir_rel": f"01_train/doe/{did}/", "assem_rel": f"01_train/radioss_assem/{did}/", "status": "BUILDING",
            "sample_status": "PENDING", **native,
        })


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """재시도: DOE 행을 새 작업으로 다시 BUILDING."""
    p = old["params"] or {}
    if old["job_type"] == "TD_DOE_GEN" and p.get("doe_id"):
        train_repo.set_building_job(conn, p["doe_id"], new_id)
