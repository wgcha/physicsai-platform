"""Kernel adapter boundary (contract section 18.9).

Only ``paicad.kernel.occ`` imports OCP. This package's top level imports nothing from
OCP so that fakes (tests) can use the neutral types without OCCT; the OCCT loader is
imported lazily by :func:`load_cad`.
"""

from __future__ import annotations

from pathlib import Path

from .base import BodyGeom, BodySummary, EdgeData, FaceData, FaceMove, SurfaceEdit, Topology


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


def move_faces(body: BodyGeom, moves: dict[int, FaceMove]) -> BodyGeom:
    """Push/pull: new body with the face moves applied, same topology and sub-shape numbering (section 6.3).

    Raises CadInputError with code GEOM_CAD_FAILED / GEOM_TOPOLOGY_CHANGED; never lets OCCT errors escape.
    """
    from . import occ

    try:
        return body.moved(moves)  # type: ignore[attr-defined]
    except occ.KernelError as e:
        raise CadInputError(e.code, e.message) from None


def save_brep(bodies: list[BodyGeom], path: str | Path) -> None:
    from . import occ

    try:
        occ.write_brep(bodies, path)  # type: ignore[arg-type]
    except occ.KernelError as e:
        raise CadInputError(e.code, e.message) from None


def load_brep(path: str | Path, names: list[str]) -> list[BodyGeom]:
    from . import occ

    try:
        return list(occ.load_brep(path, names))
    except occ.KernelError as e:
        raise CadInputError(e.code, e.message) from None


def load_sheets(path: str | Path, extensions: tuple[str, ...] = (".step", ".stp")) -> tuple[str, list[BodyGeom]]:
    """Load mid-surface (sheet) bodies (shell-morph section 4.1). Returns (mode, bodies) like :func:`load_cad`;
    a solid body raises CadInputError SHELL_BODY_NOT_SHEET."""
    from . import occ, occ_sheet

    p = Path(path)
    exts = tuple(e.lower() for e in extensions)
    try:
        if p.is_dir():
            return "parts", list(occ_sheet.load_sheet_parts_dir(p, exts))
        if not p.is_file():
            raise CadInputError("GEOM_INPUT_INVALID", f"CAD path not found: {p.name}")
        if p.suffix.lower() not in exts:
            raise CadInputError("GEOM_INPUT_INVALID", f"unsupported CAD extension: {p.suffix}")
        return "single", list(occ_sheet.load_sheet_step(p))
    except occ.KernelError as e:
        raise CadInputError(e.code, e.message) from None


def rebuild_sheet(body: BodyGeom, face_edits: dict, edge_points: dict, vertex_pos: dict) -> BodyGeom:
    """Topology-preserving geometry replacement of a sheet body (shell-morph section 6.4).

    ``face_edits`` {face id: SurfaceEdit}, ``edge_points`` {edge id: points[3,3]} = images of the old edge
    points at arc-length t = 0, 1/2, 1 (closed edges: 0, 1/3, 2/3), ``vertex_pos`` {vertex id: xyz}.
    Raises CadInputError GEOM_CAD_FAILED / GEOM_TOPOLOGY_CHANGED.
    """
    from . import occ

    try:
        return body.rebuilt(face_edits, edge_points, vertex_pos)  # type: ignore[attr-defined]
    except occ.KernelError as e:
        raise CadInputError(e.code, e.message) from None


def save_sheet_brep(bodies: list[BodyGeom], path: str | Path) -> None:
    from . import occ, occ_sheet

    try:
        occ_sheet.write_sheet_brep(bodies, path)  # type: ignore[arg-type]
    except occ.KernelError as e:
        raise CadInputError(e.code, e.message) from None


def load_sheet_brep(path: str | Path, names: list[str]) -> list[BodyGeom]:
    from . import occ, occ_sheet

    try:
        return list(occ_sheet.load_sheet_brep(path, names))
    except occ.KernelError as e:
        raise CadInputError(e.code, e.message) from None


def kernel_versions() -> dict[str, str]:
    from . import occ

    return {"ocp": occ.ocp_version()}


__all__ = [
    "BodyGeom",
    "BodySummary",
    "CadInputError",
    "EdgeData",
    "FaceData",
    "FaceMove",
    "SurfaceEdit",
    "Topology",
    "kernel_versions",
    "load_brep",
    "load_cad",
    "load_sheet_brep",
    "load_sheets",
    "move_faces",
    "rebuild_sheet",
    "save_brep",
    "save_sheet_brep",
]
