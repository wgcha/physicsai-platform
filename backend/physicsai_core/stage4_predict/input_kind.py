"""예측 입력 종류 변환·능력 판정(input-kind.md §6.1, v0.2.7) — 순수 함수, DB·파일 접근 없음.

공개 API·화면은 `input: "assembly" | "cushion"`, 저장은 기존 열·키 `input_kind`/`template_kind`(`assembly | mesh_only`)를 재사용한다
(IK-2, migration 없음). 두 이름 사이 변환은 이 모듈 한 곳에서만 한다(R4).

- 쿠션 입력 = 쿠션 메시 rad 하나로 예측(내부 값 mesh_only). 조립 가능 템플릿도 실행 단위로 쿠션을 고를 수 있다(IK-1·IK-4).
- 템플릿 능력(`capability`)은 조회 때 계산한다(저장 안 함, IK-3).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..geometry.shell import is_prop_row
from .prepared_input import is_mesh_file

ASSEMBLY = "assembly"
CUSHION = "cushion"
INPUTS = (ASSEMBLY, CUSHION)
INTERNAL_ASSEMBLY = "assembly"
INTERNAL_CUSHION = "mesh_only"
_TO_INTERNAL = {ASSEMBLY: INTERNAL_ASSEMBLY, CUSHION: INTERNAL_CUSHION}
_TO_PUBLIC = {INTERNAL_ASSEMBLY: ASSEMBLY, INTERNAL_CUSHION: CUSHION}

TEXT = {ASSEMBLY: "조립", CUSHION: "쿠션"}

# 능력 밖 사유(INPUT_KIND_UNSUPPORTED 문구·ParamSet.input_capability_reason — 계약 §6.4)
REASON_CUSHION_ONLY = "쿠션만 가능한 템플릿(조립 폴더 없음)"
REASON_SHELL = "쉘 템플릿에는 쿠션 바디가 없습니다"
REASON_SHELL_THICKNESS = "쉘 두께 값이 있는 템플릿은 조립 입력만"
REASON_CUSHION_CMD = "관리자 설정 필요: commands.paicad_cushion_write"
REASON_PREPARED = "준비된 입력은 starter로 정해집니다"
REASON_LEGACY = "HyperStudy 최적화는 입력 종류를 고를 수 없습니다"

CODE_UNSUPPORTED = "INPUT_KIND_UNSUPPORTED"
NOTE_CUSHION_RESPONSES = "INPUT_CUSHION_RESPONSES"
MESSAGE_CUSHION_RESPONSES = "쿠션 입력은 쿠션 메시의 예측 결과만 있습니다 — 제품(조립) 부품 기준 응답은 비거나 실패할 수 있습니다"


def to_internal(value: str | None) -> str:
    """공개 입력 종류 → 저장값. 생략(None)·모르는 값은 assembly(하위호환)."""
    return _TO_INTERNAL.get(value or ASSEMBLY, INTERNAL_ASSEMBLY)


def to_public(input_kind: str | None) -> str:
    """저장값(`assembly|mesh_only`) → 공개 입력 종류. 모르는 값·None은 assembly."""
    return _TO_PUBLIC.get(input_kind or INTERNAL_ASSEMBLY, ASSEMBLY)


def text_of(value: str | None) -> str:
    """표시 문구: 조립 | 쿠션(공개 값 기준)."""
    return TEXT.get(value or ASSEMBLY, TEXT[ASSEMBLY])


def cushion_write_configured(settings: Any) -> bool:
    """Native 쿠션 rad 쓰기 명령(`commands.paicad_cushion_write`) 설정 여부. 키가 없는 설정 판은 미설정으로 본다."""
    return getattr(getattr(settings, "commands", None), "paicad_cushion_write", None) is not None


def capability(ps: Mapping[str, Any], settings: Any, *, native_kind: str | None = None,
               shell_only: bool = False) -> tuple[list[str], str | None]:
    """템플릿이 받을 수 있는 입력 종류 목록과, 목록이 [assembly, cushion]이 아닐 때의 사유(IK-3).

    Altair: assembly 템플릿 → 둘 다, mesh_only 템플릿 → cushion만.
    Native: solid(단일·다중 baseline) → 둘 다(단 `commands.paicad_cushion_write`가 없으면 assembly만 + 사유),
    쉘(판금 비드)·쉘 두께 전용·쉘 두께 값(source prop) 행이 있는 세트 → assembly만.
    `native_kind`·`shell_only`는 준비본(파일)에서 읽은 값을 호출자가 준다(이 함수는 파일을 읽지 않는다)."""
    if (ps.get("engine") or "altair") != "native":
        if ps.get("input_kind") == INTERNAL_CUSHION:
            return [CUSHION], REASON_CUSHION_ONLY
        return [ASSEMBLY, CUSHION], None
    if native_kind == "shell" or shell_only:
        return [ASSEMBLY], REASON_SHELL
    if has_thickness_rows(ps.get("parameters")):
        return [ASSEMBLY], REASON_SHELL_THICKNESS
    if not cushion_write_configured(settings):
        return [ASSEMBLY], REASON_CUSHION_CMD
    return [ASSEMBLY, CUSHION], None


def has_thickness_rows(parameters: Iterable[Any] | None) -> bool:
    """쉘 두께 값 행(`source: "prop"`, 3S)이 있는지 — PROP 값은 조립 쪽에만 적용되므로 쿠션 불가."""
    return any(isinstance(r, Mapping) and is_prop_row(r) for r in parameters or [])


def pick(requested: str | None, cap: Iterable[str]) -> str | None:
    """요청 입력 종류와 능력으로 실행 입력 종류를 정한다(IK-1). 생략 = assembly 가능하면 assembly, 아니면 cushion.
    능력 밖(또는 능력이 비어 있음)이면 None → 호출자가 422 INPUT_KIND_UNSUPPORTED."""
    cap = list(cap)
    if requested is None:
        return ASSEMBLY if ASSEMBLY in cap else (CUSHION if CUSHION in cap else None)
    return requested if requested in cap else None


def unsupported_message(requested: str, reason: str | None) -> str:
    base = f"이 템플릿은 {text_of(requested)} 입력을 쓸 수 없습니다"
    return f"{base}({reason})" if reason else base


def cushion_missing_warning(names: Iterable[str]) -> dict[str, str] | None:
    """쿠션 입력에서 값이 없는 응답 이름 → 경고 `INPUT_CUSHION_RESPONSES`(차단 없음, 사용자 확정 Q2: 목적·제약 응답은 쿠션·제품 모두
    고를 수 있고 값이 없는 응답만 알린다). 이름이 없으면 None."""
    miss = [str(n) for n in names]
    if not miss:
        return None
    shown = ", ".join(miss[:5]) + (f" 외 {len(miss) - 5}개" if len(miss) > 5 else "")
    return {"code": NOTE_CUSHION_RESPONSES, "message": f"쿠션 입력에서 값이 없는 응답: {shown} — {MESSAGE_CUSHION_RESPONSES}"}


def of_prepared(starter: str | None) -> str:
    """준비된 입력(prepared) 실행의 입력 종류 표시값: starter가 eps_mesh면 cushion, 아니면 assembly(IK-13)."""
    return CUSHION if starter and is_mesh_file(starter) else ASSEMBLY


def of_run(params: Mapping[str, Any] | None, result: Mapping[str, Any] | None, template_input_kind: str | None) -> str:
    """단건 PREDICT 실행의 입력 종류(공개 값): job params `template_kind` → result `template_kind` → 템플릿 값 순.
    prepared는 starter로 판정(params의 `input_kind`는 file|dir이므로 쓰지 않는다)."""
    p, r = params or {}, result or {}
    if p.get("input_mode") == "prepared":
        return of_prepared(r.get("starter") or p.get("starter_name"))
    kind = p.get("template_kind") or r.get("template_kind") or template_input_kind
    return to_public(kind)
