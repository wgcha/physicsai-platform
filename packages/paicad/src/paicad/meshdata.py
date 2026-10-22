"""Baseline mesh + tag data shared by morph and check (numpy only)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .common import PaicadError
from .mesh.radioss import RadMesh, skin_triangles
from .update import read_json

KIND_UNMATCHED, KIND_INTERIOR, KIND_FACE, KIND_EDGE, KIND_VERTEX = -1, 0, 1, 2, 3


@dataclass
class TagData:
    doc: dict
    node_id: np.ndarray  # int64[n]
    part: np.ndarray  # int32[n]
    kind: np.ndarray  # int8[n]
    entity: np.ndarray  # int32[n]
    uv: np.ndarray  # float64[n,2]

    def lookup(self) -> dict[int, int]:
        return {int(n): i for i, n in enumerate(self.node_id)}


def load_tag(tag_dir: str | Path) -> TagData:
    d = Path(tag_dir)
    doc = read_json(d / "tag.json", "tag.json")
    if doc.get("status") != "OK" or doc.get("schema_version") != 1:
        raise PaicadError("GEOM_INPUT_INVALID", "tag.json is not an OK schema_version 1 report")
    name = (doc.get("files") or {}).get("nodes", "tag_nodes.npz")
    try:
        z = np.load(d / name)
        arr = {k: np.asarray(z[k]) for k in ("node_id", "part", "kind", "entity", "uv")}
    except (OSError, KeyError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read tag nodes file: {ex.__class__.__name__}") from None
    return TagData(doc, arr["node_id"].astype(np.int64), arr["part"].astype(np.int32), arr["kind"].astype(np.int8), arr["entity"].astype(np.int32), arr["uv"].astype(float))


@dataclass
class Comp:
    """One cushion component of the baseline: tets (local node indices) and its node table."""

    index: int  # position in tag.json parts
    part: str
    body: str
    elem_ids: np.ndarray  # int64[m]
    node_ids: np.ndarray  # int64[n] sorted unique
    gidx: np.ndarray  # int64[n] row in RadMesh.node_ids / xyz
    tets: np.ndarray  # int64[m,4] local node indices
    skin: np.ndarray  # int64[k,3] local node indices (outward)
    kind: np.ndarray  # int8[n] (-1/0/1/2/3)
    entity: np.ndarray  # int32[n] nominal entity id
    uv: np.ndarray  # float64[n,2]
    owner: np.ndarray  # int32[n] tag part index that classified the node (shared nodes: first part)


def components_from_tag(mesh: RadMesh, tag: TagData) -> list[Comp]:
    """Split the baseline by tag.json parts[].elem_range (TETRA4 only, like section 4.1)."""
    tet_blocks = [b for b in mesh.blocks if b.keyword == "TETRA4"]
    if not tet_blocks:
        raise PaicadError("GEOM_INPUT_INVALID", "baseline has no /TETRA4 elements")
    ids = np.concatenate([b.ids for b in tet_blocks])
    conn = np.concatenate([b.conn for b in tet_blocks])
    pid_of = np.concatenate([np.full(len(b.ids), b.part_id, dtype=np.int64) for b in tet_blocks])
    nidx = mesh.node_index()
    look = tag.lookup()
    out = []
    for k, p in enumerate(tag.doc.get("parts") or []):
        lo, hi = (int(x) for x in p["elem_range"])
        if p.get("pids"):  # assembly match (asm-match.md section 5.2): component = union of the PART blocks
            sel = np.isin(pid_of, np.asarray(p["pids"], dtype=np.int64))
        else:
            sel = (ids >= lo) & (ids <= hi)
        if not sel.any():
            raise PaicadError("GEOM_INPUT_INVALID", f"component {p['part']}: no TETRA4 element in {lo}-{hi} (tag does not match the baseline)")
        e = ids[sel]
        c = conn[sel]
        order = np.argsort(e, kind="stable")
        e, c = e[order], c[order]
        nodes = np.unique(c)
        try:
            g = np.array([nidx[int(n)] for n in nodes], dtype=np.int64)
            rows = np.array([look[int(n)] for n in nodes], dtype=np.int64)
        except KeyError as ex:
            raise PaicadError("GEOM_INPUT_INVALID", f"node {ex.args[0]} of {p['part']} is missing in the baseline or the tag") from None
        local = np.searchsorted(nodes, c)
        skin_ids = skin_triangles(c)
        skin = np.searchsorted(nodes, skin_ids) if skin_ids.size else np.zeros((0, 3), dtype=np.int64)
        out.append(
            Comp(k, p["part"], p["body"], e, nodes, g, local, skin, tag.kind[rows], tag.entity[rows], tag.uv[rows], tag.part[rows])
        )
    if not out:
        raise PaicadError("GEOM_INPUT_INVALID", "tag.json has no parts")
    return out


def tet_volumes(xyz: np.ndarray, tets: np.ndarray) -> np.ndarray:
    p = [xyz[tets[:, i]] for i in range(4)]
    return np.einsum("ij,ij->i", np.cross(p[1] - p[0], p[2] - p[0]), p[3] - p[0]) / 6.0
