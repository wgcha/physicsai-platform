"""Neutral data types and the kernel protocol (contract section 18.9).

Nothing in this module imports OCP. Everything that crosses the kernel boundary is
one of these dataclasses, plain Python numbers/strings, or numpy arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

SURFACE_KINDS = ("PLANE", "CYLINDER", "CONE", "SPHERE", "TORUS", "OTHER")
CURVE_KINDS = ("LINE", "CIRCLE", "ELLIPSE", "OTHER")
EDGE_CONVEXITY = ("CONVEX", "CONCAVE", "SMOOTH", "SEAM", "UNKNOWN")


@dataclass(frozen=True)
class FaceData:
    """One B-rep face. ``id`` is 1-based in TopExp::MapShapes(FACE) order."""

    id: int
    surface: str
    area: float
    centroid: np.ndarray  # (3,)
    bbox: np.ndarray  # (6,) xmin ymin zmin xmax ymax zmax
    edges: tuple[int, ...]  # all edge ids bounding the face
    outer_edges: tuple[int, ...]
    inner_wires: tuple[tuple[int, ...], ...]
    uv_bounds: tuple[float, float, float, float]  # umin umax vmin vmax
    normal: np.ndarray | None = None  # PLANE: outward unit normal
    axis_point: np.ndarray | None = None  # CYLINDER/CONE/TORUS/SPHERE: axis location / center
    axis_dir: np.ndarray | None = None
    radius: float | None = None  # CYLINDER radius, TORUS major radius, SPHERE radius
    minor_radius: float | None = None  # TORUS minor radius
    span_deg: float | None = None  # angular span around the axis (revolved surfaces)
    concave: bool | None = None  # revolved surfaces: True if outward normal points toward the axis


@dataclass(frozen=True)
class EdgeData:
    id: int
    curve: str
    length: float
    vertices: tuple[int, ...]  # vertex ids (1 or 2)
    faces: tuple[int, ...]  # distinct adjacent face ids
    convexity: str
    bbox: np.ndarray  # (6,)
    dihedral_deg: float | None = None  # angle between adjacent outward normals at mid-edge


@dataclass(frozen=True)
class Topology:
    faces: tuple[FaceData, ...]
    edges: tuple[EdgeData, ...]
    vertices: np.ndarray  # (nv, 3); vertex id k is row k-1

    def face(self, fid: int) -> FaceData:
        return self.faces[fid - 1]

    def edge(self, eid: int) -> EdgeData:
        return self.edges[eid - 1]


@dataclass(frozen=True)
class FaceMove:
    """Requested change of one face for push/pull (section 6.3).

    ``translate``: rigid translation of the face surface (mm, global axes); for a plane only the
    normal component matters. ``radius``: new radius of a cylindrical face (None = unchanged).
    """

    translate: np.ndarray | None = None  # (3,)
    radius: float | None = None

    def is_effective(self) -> bool:
        return (self.translate is not None and bool(np.any(np.asarray(self.translate) != 0))) or self.radius is not None


@dataclass(frozen=True)
class BodySummary:
    name: str
    volume: float
    bbox: np.ndarray  # (6,)
    n_faces: int
    n_edges: int
    n_vertices: int
    extra: dict = field(default_factory=dict)


@runtime_checkable
class BodyGeom(Protocol):
    """Geometry of one solid body as seen by paicad modules outside ``kernel/``.

    Implementations: ``paicad.kernel.occ.OccBody`` (OCCT) and fakes in tests.
    All arguments/returns are neutral (ids, floats, numpy arrays).
    """

    name: str

    def summary(self) -> BodySummary: ...

    def topology(self) -> Topology: ...

    def project_to_edge(self, edge_id: int, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (dist[n], t[n] arc-length normalized in [0,1], foot[n,3])."""
        ...

    def project_to_face(self, face_id: int, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return (dist[n], uv[n,2] normalized to the face UV bounds, inside[n] bool, foot[n,3]).

        ``inside`` is True when the foot point is IN or ON the trimmed face.
        """
        ...

    def eval_face(self, face_id: int, uv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Evaluate normalized (u,v) -> (points[n,3], outward normals[n,3])."""
        ...

    def sample_face(self, face_id: int, n: int) -> np.ndarray:
        """Points on the trimmed face from an n x n normalized UV grid (only inside points)."""
        ...

    def points_inside(self, pts: np.ndarray) -> np.ndarray:
        """bool[n]: point strictly inside the solid."""
        ...

    def eval_edge(self, edge_id: int, t: np.ndarray) -> np.ndarray:
        """Points[n,3] at arc-length normalized parameters t in [0,1] (same convention as project_to_edge)."""
        ...

    def classify_face_uv(self, face_id: int, uv: np.ndarray) -> np.ndarray:
        """bool[n]: normalized (u,v) lies IN or ON the trimmed face."""
        ...

    def distance(self, pts: np.ndarray) -> np.ndarray:
        """dist[n]: distance from each point to the body boundary (faces)."""
        ...
