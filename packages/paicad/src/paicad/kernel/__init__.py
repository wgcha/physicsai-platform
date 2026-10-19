"""Kernel adapter boundary (contract section 18.9).

Only ``paicad.kernel.occ`` imports OCP. This package's top level imports nothing from
OCP so that fakes (tests) can use the neutral types without OCCT; the OCCT loader is
imported lazily by :func:`load_cad`.
"""

from __future__ import annotations

from pathlib import Path

from .base import BodyGeom, BodySummary, EdgeData, FaceData, FaceMove, Topology


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


def _view_call(fn, what: str):
    """Run a 3D-view kernel operation; kernel/OCCT errors -> CadInputError (VIEW_TESSELLATION_FAILED by default)."""
    try:
        return fn()
    except CadInputError:
        raise
    except Exception as e:  # noqa: BLE001 - KernelError (code) or an unexpected OCCT/implementation error
        code = getattr(e, "code", None) or "VIEW_TESSELLATION_FAILED"
        msg = getattr(e, "message", None) or f"{what} failed: {e.__class__.__name__}: {e}"
        raise CadInputError(code, msg) from None


def tessellate(body: BodyGeom, linear_mm: float, angular_deg: float):
    """(positions float64[n,3], normals float64[n,3], triangles int64[m,3], face_ids int32[m]) - geometry-view.md section 5.3.

    No vertex is shared between faces; triangles grouped by ascending face id, outward oriented."""
    return _view_call(lambda: body.tessellate(float(linear_mm), float(angular_deg)), "tessellation")  # type: ignore[attr-defined]


def edge_polylines(body: BodyGeom, linear_mm: float, angular_deg: float) -> list:
    """[(edge id, points[k,3])] of the B-rep edges (display lines)."""
    return _view_call(lambda: body.edge_polylines(float(linear_mm), float(angular_deg)), "edge discretization")  # type: ignore[attr-defined]


def distance_to_face(points, body: BodyGeom, face_id: int):
    """dist[n]: distance of each point to the surface of face ``face_id`` of ``body`` (fallback: body distance)."""
    return _view_call(lambda: body.distance_to_face(int(face_id), points), "face distance")  # type: ignore[attr-defined]


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
    "Topology",
    "distance_to_face",
    "edge_polylines",
    "kernel_versions",
    "tessellate",
    "load_brep",
    "load_cad",
    "move_faces",
    "save_brep",
]
