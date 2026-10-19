"""Solver writer registry (contract section 18.3).

A writer turns the node-coordinate update (node id -> new xyz) into a solver input file derived
from the baseline file. Selection: ``--solver`` (default ``radioss``). Only Radioss is implemented
(section 6.4 byte-preserving rules); other solvers are out of scope (interface only).
"""

from __future__ import annotations

from typing import Protocol

from ..common import PaicadError


class SolverWriter(Protocol):
    name: str
    output_name: str  # file name written in the morph output folder

    def write(self, base_bytes: bytes, base_mesh, moved: dict[int, tuple[float, float, float]]) -> bytes:
        """Return the new solver file content: the baseline with only node coordinates replaced."""
        ...


_REGISTRY: dict[str, SolverWriter] = {}
DEFAULT_SOLVER = "radioss"


def register(writer: SolverWriter) -> None:
    _REGISTRY[writer.name] = writer


def available() -> list[str]:
    return sorted(_REGISTRY)


def get_writer(name: str | None) -> SolverWriter:
    w = _REGISTRY.get(name or DEFAULT_SOLVER)
    if w is None:
        raise PaicadError("GEOM_INPUT_INVALID", f"unsupported solver writer: {name!r} (available: {', '.join(available())})")
    return w


from .radioss import RadiossWriter  # noqa: E402  (registers itself)

register(RadiossWriter())
