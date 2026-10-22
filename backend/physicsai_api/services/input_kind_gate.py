"""예측 입력 종류 선택·능력 검사(input-kind.md §4·§6, IK-1·IK-3·IK-11) — ④ 단건·일괄·⑥ 공용.

변환·능력 규칙은 core `stage4_predict/input_kind.py`(순수 함수), 여기는 준비본(파일)에서 읽은 Native 종류를 넣어 주고
오류(422 INPUT_KIND_UNSUPPORTED · 409 TEMPLATE_NOT_CONFIGURED)로 바꾸는 얇은 층이다.
"""

from __future__ import annotations

from typing import Any

from physicsai_core.errors import DomainError
from physicsai_core.stage4_predict import input_kind as ik

from ..context import AppContext


def _unsupported(message: str, reason: str | None, cap: list[str]) -> DomainError:
    """422 INPUT_KIND_UNSUPPORTED(field `input`) — errors 모양은 invalid_at(params.<loc>)과 같다."""
    return DomainError("INPUT_KIND_UNSUPPORTED", message, status=422, errors=[{"loc": ["params", "input"], "msg": message}],
                       reason=reason, input_capability=cap)


def capability_of(ctx: AppContext, ps: dict[str, Any]) -> tuple[list[str], str | None]:
    """템플릿 입력 능력(조회 계산값, 저장 안 함). Native는 준비본 kind·쉘 두께 전용 여부를 읽는다."""
    native_kind: str | None = None
    shell_only = False
    if (ps.get("engine") or "altair") == "native":
        from physicsai_core.geometry.prep import is_shell_only

        from . import param_set_native_api as nat

        base = nat.set_path(ctx, ps)
        native_kind = nat.set_kind(ctx, ps)
        shell_only = is_shell_only(base)
    return ik.capability(ps, ctx.settings, native_kind=native_kind, shell_only=shell_only)


def with_capability(ctx: AppContext, ps: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    """`ParamSet` 응답에 `input_capability`·`input_capability_reason`을 더한다(원본 `out`을 바꿔 돌려줌)."""
    cap, reason = capability_of(ctx, ps)
    out["input_capability"] = cap
    out["input_capability_reason"] = reason
    return out


def resolve_internal(ctx: AppContext, ps: dict[str, Any], requested: str | None) -> str:
    """요청 `input`(생략 가능) → 저장값(`assembly|mesh_only`). 능력 밖이면 422 INPUT_KIND_UNSUPPORTED(field `input`),
    Native 쿠션인데 `commands.paicad_cushion_write`가 없으면 409 TEMPLATE_NOT_CONFIGURED."""
    cap, reason = capability_of(ctx, ps)
    chosen = ik.pick(requested, cap)
    if chosen is None:
        if requested == ik.CUSHION and reason == ik.REASON_CUSHION_CMD:
            raise DomainError("TEMPLATE_NOT_CONFIGURED", ik.REASON_CUSHION_CMD, status=409, template="paicad_cushion_write")
        raise _unsupported(ik.unsupported_message(requested or ik.ASSEMBLY, reason), reason, cap)
    return ik.to_internal(chosen)


def reject_input(requested: str | None, reason: str) -> None:
    """`input`을 받지 않는 경로(prepared·레거시 optimize, IK-13)에서 값이 오면 422 INPUT_KIND_UNSUPPORTED."""
    if requested is not None:
        raise _unsupported(f"입력 종류를 고를 수 없습니다({reason})", reason, [])
