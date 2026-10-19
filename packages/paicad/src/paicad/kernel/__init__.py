"""Kernel adapter boundary (contract section 18.9).

Only ``paicad.kernel.occ`` imports OCP. This package's top level imports nothing from
OCP so that fakes (tests) can use the neutral types without OCCT; the OCCT loader is
imported lazily by :func:`load_cad`.
"""

from __future__ import annotations

from pathlib import Path

from .base import BodyGeom, BodySummary, EdgeData, FaceData, Topology


class CadInputError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def load_cad(path: str | Path, extensions: tuple[str, ...] = (".step", ".stp")) -> tuple[str, list[BodyGeom]]:
    """Load the nominal CAD. Returns (mode, bodies); mode = "single" (one STEP) or "parts" (folder).

    Body ``name`` is the XDE label name (single) or the file stem (parts); None if unnamed.
    """
    from . import occ

    p = Path(path)
    exts = tuple(e.lower() for e in extensions)
    try:
        if p.is_dir():
            return "parts", list(occ.load_parts_dir(p, exts))
        if not p.is_file():
            raise CadInputError("GEOM_INPUT_INVALID", f"CAD path not found: {p.name}")
        if p.suffix.lower() not in exts:
            raise CadInputError("GEOM_INPUT_INVALID", f"unsupported CAD extension: {p.suffix}")
        return "single", list(occ.load_step(p))
    except occ.KernelError as e:
        raise CadInputError(e.code, e.message) from None


def kernel_versions() -> dict[str, str]:
    from . import occ

    return {"ocp": occ.ocp_version()}


__all__ = ["BodyGeom", "BodySummary", "CadInputError", "EdgeData", "FaceData", "Topology", "kernel_versions", "load_cad"]
