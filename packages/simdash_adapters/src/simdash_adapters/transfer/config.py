"""회수·경로 변환 설정 값(frozen dataclass). 키 이름은 플랫폼 설정 `hpc.transfer.*`와 1:1, 기본값 없음."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PathMapEntry:
    local: str
    remote: str

    @classmethod
    def from_obj(cls, o: Any) -> "PathMapEntry":
        return cls(o.local, o.remote)

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> "PathMapEntry":
        return cls(d["local"], d["remote"])


@dataclass(frozen=True)
class TransferConfig:
    collect_mode: str  # in_place | shared_folder | drive(= shared_folder 별칭)
    collect_root_remote: str
    collect_root_local: str
    path_map: tuple[PathMapEntry, ...]

    @classmethod
    def from_obj(cls, o: Any) -> "TransferConfig":
        return cls(o.collect_mode, o.collect_root_remote, o.collect_root_local,
                   tuple(PathMapEntry.from_obj(m) for m in o.path_map))

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> "TransferConfig":
        return cls(d["collect_mode"], d["collect_root_remote"], d["collect_root_local"],
                   tuple(PathMapEntry.from_mapping(m) for m in d["path_map"]))
