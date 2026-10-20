"""Pure Python glTF 2.0 binary (GLB) writer (geometry-view.md sections 4.1, GV-1, GV-5).

``struct`` + ``json`` + numpy only, no extension. Layout: 12-byte header, one JSON chunk (padded with
spaces), one BIN chunk (padded with zeros); every buffer view starts on a 4-byte boundary and 2-byte
vertex attributes (``UNSIGNED_SHORT`` scalars) use ``byteStride`` 4 so that every vertex attribute
element is 4-byte aligned (glTF 2.0 section 3.6.2.4). JSON keys are written in a fixed order without
whitespace and the output has no time, path or random content: same input -> same bytes.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field

import numpy as np

GLB_MAGIC = 0x46546C67  # "glTF"
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
FLOAT, UNSIGNED_SHORT, UNSIGNED_INT = 5126, 5123, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
MODE_POINTS, MODE_LINES, MODE_TRIANGLES = 0, 1, 4
GRAY = [0.7, 0.7, 0.7, 1.0]


@dataclass
class TriMesh:
    """Triangle mesh node: positions[n,3], triangles[m,3] (0-based), optional normals[n,3] and per-vertex
    attributes {name: array[n] or [n,3]} (dtype float32 -> FLOAT, uint16 -> UNSIGNED_SHORT, uint32 -> UNSIGNED_INT)."""

    name: str
    positions: np.ndarray
    triangles: np.ndarray
    normals: np.ndarray | None = None
    attributes: dict[str, np.ndarray] = field(default_factory=dict)
    double_sided: bool = False


@dataclass
class LineSet:
    """Line node (mode LINES): positions[n,3], segments[k,2] (0-based), per-vertex attributes."""

    name: str
    positions: np.ndarray
    segments: np.ndarray
    attributes: dict[str, np.ndarray] = field(default_factory=dict)


@dataclass
class PointSet:
    """Point node (mode POINTS, no indices): positions[n,3], per-vertex attributes (marker nodes)."""

    name: str
    positions: np.ndarray
    attributes: dict[str, np.ndarray] = field(default_factory=dict)


def id_dtype(max_value: int) -> type:
    """UNSIGNED_SHORT if every id fits in 16 bits, else UNSIGNED_INT (section 4.1 ``_FACE_ID``)."""
    return np.uint16 if int(max_value) <= 0xFFFF else np.uint32


def polylines(items: list[tuple[int, np.ndarray]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """[(id, points[k,3])] -> (positions, segments, id per vertex) for a LineSet."""
    pos, seg, ids = [], [], []
    off = 0
    for eid, pts in items:
        k = len(pts)
        if k < 2:
            continue
        pos.append(np.asarray(pts, dtype=float))
        a = np.arange(off, off + k - 1, dtype=np.int64)
        seg.append(np.stack([a, a + 1], axis=1))
        ids.append(np.full(k, int(eid), dtype=np.int64))
        off += k
    if not pos:
        return np.zeros((0, 3)), np.zeros((0, 2), dtype=np.int64), np.zeros(0, dtype=np.int64)
    return np.concatenate(pos), np.concatenate(seg), np.concatenate(ids)


def _num(x) -> float | int:
    return int(x) if isinstance(x, (int, np.integer)) else float(x)


class _Builder:
    def __init__(self) -> None:
        self.bin = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def _view(self, data: bytes, target: int, stride: int | None = None) -> int:
        self.bin += b"\x00" * (-len(self.bin) % 4)
        v: dict = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if stride is not None:
            v["byteStride"] = stride
        v["target"] = target
        self.bin += data
        self.views.append(v)
        return len(self.views) - 1

    def attribute(self, arr: np.ndarray, minmax: bool = True) -> int:
        a = np.asarray(arr)
        if a.dtype == np.float64:
            a = a.astype(np.float32)
        a = np.ascontiguousarray(a)
        if a.dtype == np.float32:
            comp = FLOAT
        elif a.dtype == np.uint16:
            comp = UNSIGNED_SHORT
        elif a.dtype == np.uint32:
            comp = UNSIGNED_INT
        else:
            raise ValueError(f"unsupported attribute dtype {a.dtype}")
        if a.ndim == 1:
            kind, width = "SCALAR", 1
        elif a.ndim == 2 and a.shape[1] == 3:
            kind, width = "VEC3", 3
        else:
            raise ValueError(f"unsupported attribute shape {a.shape}")
        if len(a) == 0:
            raise ValueError("empty attribute")
        stride = None
        data = a.astype(a.dtype.newbyteorder("<"), copy=False).tobytes()
        if comp == UNSIGNED_SHORT and width == 1:  # 2-byte elements padded to 4 (vertex attribute alignment)
            pad = np.zeros((len(a), 2), dtype="<u2")
            pad[:, 0] = a
            data = pad.tobytes()
            stride = 4
        acc: dict = {"bufferView": self._view(data, ARRAY_BUFFER, stride), "componentType": comp, "count": int(len(a)), "type": kind}
        if minmax:
            lo = a.min(axis=0) if width > 1 else a.min()
            hi = a.max(axis=0) if width > 1 else a.max()
            acc["min"] = [_num(x) for x in np.atleast_1d(lo)]
            acc["max"] = [_num(x) for x in np.atleast_1d(hi)]
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def indices(self, idx: np.ndarray, n_vertices: int) -> int:
        dt = "<u2" if n_vertices <= 0xFFFF else "<u4"  # largest index n-1 stays below the restart value 65535
        a = np.ascontiguousarray(np.asarray(idx, dtype=np.int64).reshape(-1)).astype(dt)
        acc = {
            "bufferView": self._view(a.tobytes(), ELEMENT_ARRAY_BUFFER),
            "componentType": UNSIGNED_SHORT if dt == "<u2" else UNSIGNED_INT,
            "count": int(len(a)),
            "type": "SCALAR",
        }
        self.accessors.append(acc)
        return len(self.accessors) - 1


def write_glb(items: list[TriMesh | LineSet | PointSet], generator: str, root_name: str = "paicad_view", root_extras: dict | None = None) -> bytes:
    """GLB bytes: root node ``root_name`` with one child node per item (item order kept)."""
    b = _Builder()
    nodes: list[dict] = [{}]
    meshes: list[dict] = []
    materials: list[dict] = []
    for it in items:
        if isinstance(it, TriMesh):
            if len(it.triangles) == 0:
                raise ValueError(f"{it.name}: no triangles")
            attrs = {"POSITION": b.attribute(np.asarray(it.positions, dtype=np.float32))}
            if it.normals is not None:
                attrs["NORMAL"] = b.attribute(np.asarray(it.normals, dtype=np.float32), minmax=False)
            for k, v in it.attributes.items():
                attrs[k] = b.attribute(v)
            materials.append(
                {
                    "name": it.name,
                    "pbrMetallicRoughness": {"baseColorFactor": GRAY, "metallicFactor": 0.0, "roughnessFactor": 0.9},
                    "doubleSided": bool(it.double_sided),
                }
            )
            prim = {"attributes": attrs, "indices": b.indices(it.triangles, len(it.positions)), "material": len(materials) - 1, "mode": MODE_TRIANGLES}
        elif isinstance(it, PointSet):
            if len(it.positions) == 0:
                raise ValueError(f"{it.name}: no points")
            attrs = {"POSITION": b.attribute(np.asarray(it.positions, dtype=np.float32))}
            for k, v in it.attributes.items():
                attrs[k] = b.attribute(v)
            prim = {"attributes": attrs, "mode": MODE_POINTS}
        else:
            if len(it.segments) == 0:
                raise ValueError(f"{it.name}: no line segments")
            attrs = {"POSITION": b.attribute(np.asarray(it.positions, dtype=np.float32))}
            for k, v in it.attributes.items():
                attrs[k] = b.attribute(v)
            prim = {"attributes": attrs, "indices": b.indices(it.segments, len(it.positions)), "mode": MODE_LINES}
        meshes.append({"name": it.name, "primitives": [prim]})
        nodes.append({"name": it.name, "mesh": len(meshes) - 1})
    root: dict = {"name": root_name, "children": list(range(1, len(nodes)))}
    if root_extras:
        root["extras"] = root_extras
    nodes[0] = root
    b.bin += b"\x00" * (-len(b.bin) % 4)
    doc: dict = {"asset": {"version": "2.0", "generator": generator}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes, "meshes": meshes}
    if materials:
        doc["materials"] = materials
    doc["accessors"] = b.accessors
    doc["bufferViews"] = b.views
    doc["buffers"] = [{"byteLength": len(b.bin)}]
    js = json.dumps(doc, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(b.bin)
    return b"".join(
        [
            struct.pack("<III", GLB_MAGIC, 2, total),
            struct.pack("<II", len(js), CHUNK_JSON),
            js,
            struct.pack("<II", len(b.bin), CHUNK_BIN),
            bytes(b.bin),
        ]
    )
