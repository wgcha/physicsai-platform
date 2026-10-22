"""④ native 세트 작업 params·사전조건(geometry-engine.md §7.3.4·§7.3.8·§11.1): PARAM_SET_NATIVE
(등록·다시 준비·PROP 스캔·baseline 추가·재매핑 API가 만든다, 사용자 선택 job_type 아님).

mode: new(+shell_only) | reprep | props_scan(3S) | add_baseline · remap(4B). 4B도 새 job_type 없이 같은 체인(GE-3).
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry.asm_match import is_matched
from physicsai_core.geometry.prep import is_shell_only
from physicsai_core.paths import allowed_roots, check_user_path, resolve_in_study

from ...context import AppContext
from ..common import study_root
from ..geometry_gate import require_native_available, validate_geom_options
from ...schemas.extract_filter import ExtractFilter
from .base import _P, invalid_at


class NativeBaselineParams(_P):
    id: str = Field(max_length=32)
    path: str = Field(max_length=400)
    choice: dict[str, Any] | None = None
    label: str | None = Field(default=None, max_length=120)


class NativeSetParams(_P):
    mode: Literal["new", "reprep", "props_scan", "add_baseline", "remap"]
    path: str | None = None
    choice: dict[str, Any] | None = None
    label: str | None = None
    geom_options: dict[str, Any] | None = None
    param_set_id: str | None = None
    shell_only: bool = False  # 3S: 형상 파라미터 없는 쉘 두께 전용 세트(tag·update·morph·check 생략, §11.1)
    kind: Literal["solid", "shell"] | None = None  # shell-morph.md §8.2: new 세트 형상 종류(생략 = solid)
    baseline: NativeBaselineParams | None = None  # 4B add_baseline
    usage: Literal["topology", "range"] | None = None  # 4B: 생략 = 기존 매칭표 usage(없으면 topology)
    split_param: str | None = Field(default=None, max_length=64)  # 4B range 분할 변수(공통 이름 제안)
    extract_filter: ExtractFilter | None = None  # extract-filter.md §6.7: new(solid)만 — 서버가 정규화해 기록
    asm_match_id: str | None = Field(default=None, max_length=64)  # asm-match.md §6.4: new(solid)만 — 확정된 조립 매칭(source=path)
    asm_match_sha256: str | None = Field(default=None, max_length=80)  # 서버가 확정본 sha256을 기록(요청 값은 무시)


PARAM_MODELS: dict[str, type[BaseModel]] = {"PARAM_SET_NATIVE": NativeSetParams}


def _require_command(ctx: AppContext, key: str, what: str) -> None:
    if getattr(ctx.settings.commands, key, None) is None:
        raise DomainError("GEOM_NATIVE_UNAVAILABLE", f"{what} 명령(commands.{key})이 설정되지 않았습니다 — 관리자 설정이 필요합니다",
                          status=409, missing=[f"commands.{key}"])


def _native_set(conn: Any, study: dict[str, Any], psid: str | None) -> dict[str, Any]:
    ps = ps_repo.get(conn, psid) if psid else None
    if ps is None or ps["study_id"] != study["id"]:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    if ps.get("engine") != "native":
        raise DomainError("ENGINE_MISMATCH", "Native 형상 엔진 세트가 아닙니다", status=409)
    return ps


def set_dir(ctx: AppContext, conn: Any, ps: dict[str, Any]) -> str:
    return resolve_in_study(study_root(ctx, studies_repo.require(conn, ps["study_id"])), ps["stored_rel"])


def load_map(S: str, ctx: AppContext) -> dict[str, Any] | None:
    try:
        return bl.load(S, ctx.settings.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise DomainError(exc.code, exc.message, status=422, problems=exc.problems) from None


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    require_native_available(ctx.settings)
    if p.asm_match_id is not None and p.mode != "new":  # 조립 매칭은 신규 등록에서만(세트의 방식은 prep가 정한다)
        raise invalid_at("asm_match_id", "asm_match_id는 새 세트 등록(mode=new)에서만 쓸 수 있습니다")
    if p.extract_filter is not None and p.mode != "new":  # 등록된 세트의 조건은 바꾸지 않는다(reprep·baseline·remap·props_scan)
        from ..param_set_native_api import raise_filter_fixed

        raise_filter_fixed()
    if p.mode == "new":
        if not p.path:
            raise invalid_at("path", "path가 필요합니다")
        if p.shell_only:
            _require_command(ctx, "paicad_props_scan", "쉘 두께 PROP 스캔")
        kind = p.kind or "solid"
        if kind == "shell" and p.shell_only:
            raise invalid_at("kind", "쉘 두께 전용(shell_only)과 쉘 판금 형상(kind=shell)은 함께 쓸 수 없습니다")
        if kind == "shell":
            from ..geometry_gate import require_shell_available

            require_shell_available(ctx.settings)
        if p.asm_match_id is not None and (kind == "shell" or p.shell_only):
            raise DomainError("ASM_MATCH_UNSUPPORTED", "쉘 판금·쉘 두께 전용 세트는 조립 매칭을 쓰지 않습니다", status=422)
        if p.extract_filter is not None and (kind == "shell" or p.shell_only):
            from .stage1_native import raise_filter_unsupported

            raise_filter_unsupported()
        over = validate_geom_options(ctx.settings, p.geom_options, kind)
        out = {"engine": "native", "mode": "new", "path": p.path, "choice": p.choice or {}, "label": p.label, "geom_options": over or None}
        if p.shell_only:
            out["shell_only"] = True
        if kind == "shell":
            out["kind"] = "shell"
        from .stage1_native import normalized_filter

        norm = normalized_filter(p.extract_filter)
        if norm is not None:
            out["extract_filter"] = norm
        if p.asm_match_id is not None:  # 서버가 확정본 sha256을 다시 읽어 기록한다(요청 값 불신). 입력 일치 검사는 register_native가 이미 했다
            from ..asm_match_gate import confirmed_of

            got = confirmed_of(ctx, study, p.asm_match_id)
            if got is None:
                raise DomainError("PREREQUISITE_MISSING", "조립 매칭을 먼저 하세요 — 확정된 조립 매칭이 없습니다", status=409, missing=["ASM_MATCH"])
            out["asm_match_id"], out["asm_match_sha256"] = p.asm_match_id, got[1]
        return out, None, []
    ps = _native_set(conn, study, p.param_set_id)
    S = set_dir(ctx, conn, ps)
    if p.mode in ("add_baseline", "remap") and is_matched(S):  # asm-match.md §8.3: 다중 baseline(4B)은 1차에서 RENUM 방식만
        raise DomainError("ASM_MATCH_UNSUPPORTED", "다중 baseline은 아직 조립 매칭을 지원하지 않습니다", status=409)
    if p.mode == "reprep":
        if is_shell_only(S):
            raise DomainError("SHELL_ONLY_SET", "쉘 두께 전용 세트는 형상 준비가 없습니다 — PROP 스캔을 다시 하세요", status=409)
        return {"engine": "native", "mode": "reprep", "param_set_id": ps["id"]}, None, []
    if p.mode == "props_scan":
        _require_command(ctx, "paicad_props_scan", "쉘 두께 PROP 스캔")
        return {"engine": "native", "mode": "props_scan", "param_set_id": ps["id"]}, None, []
    # ---- 4B ----
    _require_command(ctx, "paicad_map", "다중 baseline 매칭")
    if is_shell_only(S):
        raise DomainError("SHELL_ONLY_SET", "쉘 두께 전용 세트에는 baseline을 추가할 수 없습니다(형상 피처 없음)", status=409)
    pm = load_map(S, ctx)
    usage = p.usage or (pm or {}).get("usage") or "topology"
    if p.split_param is not None and usage != "range":
        raise invalid_at("split_param", "split_param은 usage=range에서만 쓸 수 있습니다(위상 변형과 범위 분할은 섞을 수 없습니다)",
                         "GEOM_INPUT_INVALID")
    out: dict[str, Any] = {"engine": "native", "mode": p.mode, "param_set_id": ps["id"], "usage": usage, "split_param": p.split_param}
    if p.mode == "remap":
        if pm is None:
            raise DomainError("NOT_MULTI_BASELINE", "다중 baseline 세트가 아닙니다 — baseline을 먼저 추가하세요", status=409)
        return out, None, []
    b = p.baseline
    if b is None:
        raise invalid_at("baseline", "baseline {id, path}가 필요합니다")
    if not bl.ID_RE.match(b.id) or b.id == bl.BASE_ID:
        raise invalid_at("baseline.id", f"baseline id는 [A-Za-z0-9_-]{{1,32}}이고 '{bl.BASE_ID}'(첫 baseline 예약)가 아니어야 합니다")
    if b.id in bl.baseline_ids(pm or {}) or os.path.lexists(os.path.join(S, bl.BASELINES_DIR, b.id)):
        raise DomainError("BASELINE_EXISTS", f"baseline id {b.id}이(가) 이미 있습니다", status=409)
    cp = check_user_path(b.path, allowed_roots(ctx.settings, imports=True))
    out["baseline"] = {"id": b.id, "path": cp.path, "choice": b.choice or {}, "label": b.label}
    return out, None, []
