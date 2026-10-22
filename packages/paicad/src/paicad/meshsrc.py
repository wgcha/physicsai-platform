"""Mesh source of the solid commands (asm-match.md AM-9, sections 5.2-5.4), numpy only.

Method L (``--baseline-inc`` + ``--renum-csv``) keeps the existing code paths of every command. Method M
(``--asm-match`` + ``--assem-dir``) builds the baseline mesh from the include tree: the ``/TETRA4/<pid>`` blocks
of the matched PART ids (wherever they are) and the nodes they reference (definition order = tree order, then
line), one :class:`~paicad.mesh.radioss.Component` per match row (component name = body name). The product
mesh of the interference / contact collection is the whole tree minus the matched pid elements, ties come from
the tree files. The include tree digest is checked against the confirmed match (``ASM_MATCH_INVALID``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .common import PaicadError, sha256_file
from .mesh import asmtree
from .mesh.radioss import SHELL_KEYWORDS, SOLID_KEYWORDS, Component, ElementBlock, RadMesh, surface_triangles

NODE_XYZ = "node_xyz.npz"  # method M morph output (all baseline mesh nodes)
INVALID = "ASM_MATCH_INVALID"


@dataclass
class MatchRows:
    rows: list[dict]  # [{body, pids, titles}]
    excluded: list[str]


@dataclass
class MatchDoc(MatchRows):
    path: Path
    sha256: str
    digest: str
    starter: str | None


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def parse_rows(doc, code: str = INVALID) -> MatchRows:
    """``{rows: [{body, pids}], excluded_bodies}``: 1 body <-> N pids, a pid in one row only (AM-4)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("rows"), list) or not doc["rows"]:
        raise PaicadError(code, "match: rows must be a non-empty list")
    rows: list[dict] = []
    bodies: set[str] = set()
    seen: dict[int, str] = {}
    for k, r in enumerate(doc["rows"]):
        if not isinstance(r, dict) or not isinstance(r.get("body"), str) or not r["body"]:
            raise PaicadError(code, f"match: row {k + 1} has no body name")
        b = r["body"]
        pids = r.get("pids")
        if not isinstance(pids, list) or not pids or not all(_int(p) and p > 0 for p in pids):
            raise PaicadError(code, f"match: row {b} pids must be a non-empty list of positive integers")
        if b in bodies:
            raise PaicadError(code, f"match: body {b} appears in two rows")
        bodies.add(b)
        for p in pids:
            if p in seen:
                raise PaicadError(code, f"match: PART {p} is used by rows {seen[p]} and {b} (one component per row only)")
            seen[p] = b
        titles = r.get("titles") if isinstance(r.get("titles"), list) else []
        rows.append({"body": b, "pids": [int(p) for p in pids], "titles": [str(t) for t in titles]})
    ex = doc.get("excluded_bodies", [])
    if ex is None:
        ex = []
    if not isinstance(ex, list) or not all(isinstance(x, str) for x in ex):
        raise PaicadError(code, "match: excluded_bodies must be a list of body names")
    both = sorted(set(ex) & bodies)
    if both:
        raise PaicadError(code, f"match: bodies both matched and excluded: {', '.join(both[:10])}")
    return MatchRows(rows, list(ex))


def _read_json(path: str | Path, what: str, code: str) -> tuple[dict, bytes]:
    p = Path(path)
    if not p.is_file():
        raise PaicadError(code, f"{what} not found: {p.name}")
    data = p.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as ex:
        raise PaicadError(code, f"cannot read {what}: {ex.__class__.__name__}") from None
    return doc, data


def load_match(path: str | Path) -> MatchDoc:
    """Confirmed ``asm_match.json`` (asm-match.md section 4.4)."""
    doc, _ = _read_json(path, "asm_match file", INVALID)
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise PaicadError(INVALID, "asm_match: unsupported schema_version")
    mr = parse_rows(doc)
    assem = doc.get("assem")
    dg = assem.get("digest") if isinstance(assem, dict) else None
    if not isinstance(dg, str) or not dg.startswith("sha256:"):
        raise PaicadError(INVALID, "asm_match: assem.digest missing")
    return MatchDoc(mr.rows, mr.excluded, Path(path), sha256_file(path), dg, (assem or {}).get("starter"))


def mesh_args(args, l_keys: tuple[str, ...], m_extra: tuple[str, ...] = ()) -> str:
    """Method of the command arguments: ``L`` or ``M``. Mixing both = GEOM_INPUT_INVALID (missing arguments
    are rejected by the CLI before, exit 2)."""
    has_l = [k for k in l_keys if getattr(args, k, None)]
    has_m = getattr(args, "asm_match", None)
    extra = [k for k in m_extra if getattr(args, k, None)]
    if has_m and has_l:
        raise PaicadError("GEOM_INPUT_INVALID", "mesh source: give --asm-match + --assem-dir or " + " + ".join("--" + k.replace("_", "-") for k in l_keys) + ", not both")
    if not has_m and extra:
        raise PaicadError("GEOM_INPUT_INVALID", "mesh source: " + ", ".join("--" + k.replace("_", "-") for k in extra) + " needs --asm-match")
    return "M" if has_m else "L"


class AsmSource:
    """Method M baseline mesh (asm-match.md section 5.2)."""

    mode = "M"

    def __init__(self, match_path: str | Path, assem_dir: str | Path, cache_dir: str | Path | None = None, progress=None):
        self.match = load_match(match_path)
        self.assem_dir = str(assem_dir)
        self.index = asmtree.build(assem_dir, cache_dir, progress)
        if self.index.digest() != self.match.digest:
            raise PaicadError(INVALID, "assembly include tree changed since the match was confirmed (digest differs) - check the assembly match again")
        if self.index.duplicates:
            d = self.index.duplicates
            raise PaicadError("GEOM_INPUT_INVALID", f"{len(d)} node ids are defined more than once in the include tree (first {d[0]['node']}: {', '.join(d[0]['files'])})")
        self.pids = {p for r in self.match.rows for p in r["pids"]}
        have = {b.pid for b in self.index.blocks}
        missing = sorted(self.pids - have)
        if missing:
            raise PaicadError(INVALID, f"matched PART ids have no elements in the include tree: {', '.join(map(str, missing[:10]))}")
        self.mesh = self._mesh()

    @property
    def ident_path(self) -> Path:
        return self.match.path

    def _mesh(self) -> RadMesh:
        tb = [b for b in self.index.blocks if b.pid in self.pids and b.keyword == "TETRA4"]
        conn = np.concatenate([b.conn for b in tb]) if tb else np.zeros((0, 4), dtype=np.int64)
        nodes = np.unique(conn)
        rows = self.index.lookup(nodes)
        if (rows < 0).any():
            bad = nodes[rows < 0]
            raise PaicadError("GEOM_INPUT_INVALID", f"{bad.size} nodes of the matched elements have no /NODE line in the include tree (first {int(bad[0])})")
        rows = np.sort(rows)
        return RadMesh(self.index.node_id[rows].copy(), self.index.node_xyz[rows].copy(), [ElementBlock("TETRA4", b.pid, b.ids, b.conn) for b in tb])

    def row_tets(self, pids: list[int]) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """(element ids sorted, connectivity, other element keywords) of the union of the pids' blocks."""
        tb = [b for p in pids for b in self.index.pid_blocks(p) if b.keyword == "TETRA4"]
        other = sorted({f"/{b.keyword} {len(b.ids)}" for p in pids for b in self.index.pid_blocks(p) if b.keyword != "TETRA4"})
        ids = np.concatenate([b.ids for b in tb]) if tb else np.zeros(0, dtype=np.int64)
        conn = np.concatenate([b.conn for b in tb]) if tb else np.zeros((0, 4), dtype=np.int64)
        order = np.argsort(ids, kind="stable")
        return ids[order], conn[order], other

    def components(self) -> tuple[list[Component], list[dict]]:
        out = []
        for k, r in enumerate(self.match.rows):
            ids, conn, other = self.row_tets(r["pids"])
            if other:
                raise PaicadError("GEOM_UNSUPPORTED_ELEMENT", f"component {r['body']}: non-TETRA4 elements in PART {', '.join(map(str, r['pids']))} ({', '.join(other)})")
            if ids.size == 0:
                raise PaicadError("GEOM_INPUT_INVALID", f"component {r['body']}: no TETRA4 element")
            if np.unique(ids).size != ids.size:
                raise PaicadError("GEOM_INPUT_INVALID", f"component {r['body']}: element ids are not unique")
            out.append(Component(r["body"], k + 1, (int(ids[0]), int(ids[-1])), ids, conn, np.unique(conn)))
        return out, []

    def product_surface(self, bbox: np.ndarray | None, margin: float = 10.0) -> np.ndarray:
        """Surface triangles (coordinates) of every non-matched element block of the tree (section 6.5 rule,
        asm-match.md section 2.3: other PARTs of the same file are product)."""
        idx = self.index
        blocks = [ElementBlock(b.keyword, b.pid, b.ids, b.conn) for b in idx.blocks if b.pid not in self.pids and (b.keyword in SHELL_KEYWORDS or b.keyword in SOLID_KEYWORDS)]
        if not blocks:
            return np.zeros((0, 3, 3))
        tris = surface_triangles(RadMesh(blocks=blocks))
        if tris.size == 0:
            return np.zeros((0, 3, 3))
        rows = idx.lookup(tris)
        ok = (rows >= 0).all(axis=1)
        coords = idx.node_xyz[rows[ok]]
        if bbox is not None and len(coords):
            lo, hi = bbox[:3] - margin, bbox[3:] + margin
            keep = (coords.max(axis=1) >= lo).all(axis=1) & (coords.min(axis=1) <= hi).all(axis=1)
            coords = coords[keep]
        return coords

    def tie_check(self, comps, mesh: RadMesh, Xm: np.ndarray, opts: dict):
        """check (e) on the tree files (same rule as method L, coordinates from the index)."""
        from .tie import check_ties, parse_sets

        sets = parse_sets(self.index.rel_paths())
        if not sets.ties and not sets.errors:
            return {"status": "SKIPPED", "interfaces": [], "reason": "no_tie_on_component"}, None, []
        cushion = {int(n) for c in comps for n in c.node_ids}
        need: set[int] = set()
        for td in sets.ties:
            need.update(sets.grnod_node.get(td.grnod, []) if td.grnod is not None else [])
            need.update(n for s in (sets.surf_seg.get(td.surf, []) if td.surf is not None else []) for n in s if n > 0)
        ids = np.array(sorted(need), dtype=np.int64)
        rows = self.index.lookup(ids)
        coords_new = {int(n): self.index.node_xyz[r] for n, r in zip(ids, rows) if r >= 0}
        coords_base = dict(coords_new)
        mrow = mesh.node_index()
        for n in ids:
            r = mrow.get(int(n))
            if r is not None:
                coords_new[int(n)] = Xm[r]
                coords_base[int(n)] = mesh.xyz[r]
        return check_ties(sets, cushion, coords_new, coords_base, opts)


def open_source(args, progress=None) -> AsmSource:
    return AsmSource(args.asm_match, args.assem_dir, getattr(args, "cache_dir", None), progress)


def save_xyz(path: Path, node_ids: np.ndarray, xyz: np.ndarray) -> None:
    with open(path, "wb") as f:
        np.savez(f, node_id=np.asarray(node_ids, dtype=np.int64), xyz=np.asarray(xyz, dtype=np.float64))


def load_xyz(path: str | Path, what: str) -> tuple[np.ndarray, np.ndarray]:
    p = Path(path)
    if not p.is_file():
        raise PaicadError("GEOM_INPUT_INVALID", f"{what} not found: {p.name}")
    try:
        with np.load(p, allow_pickle=False) as z:
            ids = np.asarray(z["node_id"]).astype(np.int64)
            xyz = np.asarray(z["xyz"]).astype(np.float64)
    except (OSError, KeyError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read {what}: {ex.__class__.__name__}") from None
    if xyz.shape != (len(ids), 3) or not np.all(np.isfinite(xyz)):
        raise PaicadError("GEOM_INPUT_INVALID", f"{what}: node_id / xyz shapes differ or values are not finite")
    return ids, xyz
