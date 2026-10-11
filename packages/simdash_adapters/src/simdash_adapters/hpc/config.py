"""command 모드 설정 값(frozen dataclass). 키 이름은 플랫폼 설정 `hpc.command.*`·`hpc.defaults.*`와 1:1.

기본값은 두지 않는다(필수 인자) — 기본값의 단일 출처는 호출자의 설정 스키마다.
`from_obj`는 속성으로 읽고(플랫폼 pydantic 객체를 그대로 넘길 수 있음), `from_mapping`은 dict에서 읽는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any

_ARGV_KEYS = ("submit", "status", "cancel")


def _tuple_if_seq(v: Any) -> Any:
    # 문자열·None 등 배열이 아닌 값은 그대로 둔다(검증이 "문자열 배열이어야 합니다"로 잡는다)
    return tuple(v) if isinstance(v, (list, tuple)) else v


@dataclass(frozen=True)
class CommandConfig:
    allowed_executables: tuple[str, ...]
    submit: Any  # 정상이면 tuple[str, ...]
    status: Any
    cancel: Any
    job_id_regex: str | None
    state_regex: str | None
    exit_code_regex: str | None
    not_found_regex: str | None
    state_map: Mapping[str, str]
    submit_timeout_s: float
    status_timeout_s: float
    cancel_timeout_s: float

    @classmethod
    def _build(cls, values: Mapping[str, Any]) -> "CommandConfig":
        v = dict(values)
        if "allowed_executables" in v:
            v["allowed_executables"] = tuple(v["allowed_executables"])
        for k in _ARGV_KEYS:
            if k in v:
                v[k] = _tuple_if_seq(v[k])
        if "state_map" in v:
            v["state_map"] = MappingProxyType(dict(v["state_map"]))
        return cls(**v)

    @classmethod
    def from_obj(cls, o: Any) -> "CommandConfig":
        return cls._build({f.name: getattr(o, f.name) for f in fields(cls)})

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> "CommandConfig":
        return cls._build(d)


@dataclass(frozen=True)
class HpcDefaults:
    queue: str | None
    ncpus: int | None
    walltime: str | None

    @classmethod
    def from_obj(cls, o: Any) -> "HpcDefaults":
        return cls(**{f.name: getattr(o, f.name) for f in fields(cls)})

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> "HpcDefaults":
        return cls(**dict(d))
