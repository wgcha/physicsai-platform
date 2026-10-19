"""Radioss fixed-width input reading/writing (numpy only, no OCP).

Reads ``/NODE`` and element blocks; writes node-coordinate changes while keeping every
other byte of the baseline file (contract section 6.4 formatting rules).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..common import PaicadError

SOLID_KEYWORDS = {"TETRA4": 4, "TETRA10": 10, "BRICK": 8, "PENTA6": 6}
SHELL_KEYWORDS = {"SHELL": 4, "SH3N": 3}
ELEMENT_KEYWORDS = {**SOLID_KEYWORDS, **SHELL_KEYWORDS}


@dataclass
class ElementBlock:
    keyword: str
    part_id: int
    ids: np.ndarray  # int64[m]
    conn: np.ndarray  # int64[m, k]


@dataclass
class RadMesh:
    node_ids: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    xyz: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    blocks: list[ElementBlock] = field(default_factory=list)

    def node_index(self) -> dict[int, int]:
        return {int(n): i for i, n in enumerate(self.node_ids)}


def _is_comment(line: str) -> bool:
    return line.startswith("#") or line.startswith("$")


def _ints(line: str, n: int) -> list[int] | None:
    vals = []
    for k in range(n):
        s = line[10 * k : 10 * k + 10].strip()
        if not s:
            break
        try:
            vals.append(int(s))
        except ValueError:
            vals = None
            break
    if vals is not None and len(vals) >= 1:
        return vals
    try:
        return [int(t) for t in line.split()[:n]]
    except ValueError:
        return None


def _node(line: str) -> tuple[int, float, float, float] | None:
    try:
        return int(line[0:10]), float(line[10:30]), float(line[30:50]), float(line[50:70])
    except ValueError:
        pass
    t = line.split()
    if len(t) >= 4:
        try:
            return int(t[0]), float(t[1]), float(t[2]), float(t[3])
        except ValueError:
            return None
    return None


def parse_text(text: str) -> RadMesh:
    node_ids: list[int] = []
    xyz: list[tuple[float, float, float]] = []
    blocks: list[ElementBlock] = []
    mode: tuple[str, int, int] | None = None  # (kind, part, nnodes)
    cur_ids: list[int] = []
    cur_conn: list[list[int]] = []

    def flush():
        nonlocal cur_ids, cur_conn
        if mode is not None and mode[0] != "NODE" and cur_ids:
            k = mode[2]
            blocks.append(ElementBlock(mode[0], mode[1], np.array(cur_ids, dtype=np.int64), np.array(cur_conn, dtype=np.int64).reshape(-1, k)))
        cur_ids, cur_conn = [], []

    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if line.startswith("/"):
            flush()
            parts = line.strip().split("/")
            kw = parts[1].upper() if len(parts) > 1 else ""
            if kw == "NODE":
                mode = ("NODE", 0, 0)
            elif kw in ELEMENT_KEYWORDS:
                try:
                    pid = int(parts[2]) if len(parts) > 2 and parts[2].strip() else 0
                except ValueError:
                    pid = 0
                mode = (kw, pid, ELEMENT_KEYWORDS[kw])
            else:
                mode = None
            continue
        if mode is None or _is_comment(line):
            continue
        if mode[0] == "NODE":
            r = _node(line)
            if r is None:
                raise PaicadError("GEOM_INPUT_INVALID", f"cannot parse /NODE line: {line[:40]!r}")
            node_ids.append(r[0])
            xyz.append(r[1:])
        else:
            k = mode[2]
            if mode[0] == "TETRA10":
                vals = _ints(line, 11)  # id + 10 nodes may continue on next line; keep first 4 corners
                if vals is None:
                    continue
                if len(vals) < 5:
                    continue
                cur_ids.append(vals[0])
                cur_conn.append((vals[1:] + [0] * 10)[:10])
                continue
            vals = _ints(line, k + 1)
            if vals is None or len(vals) < 2:
                raise PaicadError("GEOM_INPUT_INVALID", f"cannot parse /{mode[0]} line: {line[:40]!r}")
            conn = vals[1:]
            if len(conn) < k:
                conn = conn + [conn[-1]] * (k - len(conn))  # e.g. /SHELL with 3 nodes
            cur_ids.append(vals[0])
            cur_conn.append(conn[:k])
    flush()
    return RadMesh(np.array(node_ids, dtype=np.int64), np.array(xyz, dtype=float).reshape(-1, 3), blocks)


def read_text(path: str | Path) -> str:
    with open(path, "rb") as f:
        return f.read().decode("latin-1")


def read_mesh(path: str | Path) -> RadMesh:
    return parse_text(read_text(path))


# ---------------- RENUM table ----------------
@dataclass(frozen=True)
class RenumRow:
    part: str
    node_start: int
    elem_start: int
    row: int  # 1-based row in file order


def read_renum_csv(path: str | Path) -> list[RenumRow]:
    p = Path(path)
    if not p.is_file():
        raise PaicadError("RENUM_CSV_MISSING", f"renumber table not found: {p.name}")
    text = p.read_bytes().decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise PaicadError("GEOM_INPUT_INVALID", f"renumber table is empty: {p.name}")
    head = [c.strip().lower() for c in rows[0]]
    try:
        ip, ino, iel = head.index("part"), head.index("node_start"), head.index("elem_start")
    except ValueError:
        raise PaicadError("GEOM_INPUT_INVALID", f"renumber table header must be part,node_start,elem_start: {p.name}") from None
    out = []
    for k, r in enumerate(rows[1:], 1):
        try:
            out.append(RenumRow(r[ip].strip(), int(r[ino].strip()), int(r[iel].strip()), k))
        except (ValueError, IndexError):
            raise PaicadError("GEOM_INPUT_INVALID", f"renumber table row {k} is invalid") from None
    if not out:
        raise PaicadError("GEOM_INPUT_INVALID", f"renumber table has no rows: {p.name}")
    names = [r.part for r in out]
    if len(set(names)) != len(names):
        raise PaicadError("GEOM_INPUT_INVALID", "renumber table has duplicate part names")
    return out


# ---------------- components ----------------
@dataclass
class Component:
    part: str
    row: int
    elem_range: tuple[int, int]  # inclusive [first, last] element ids found
    tet_ids: np.ndarray  # int64[m]
    tets: np.ndarray  # int64[m, 4] node ids
    node_ids: np.ndarray  # int64[n] sorted unique


def components(mesh: RadMesh, renum: list[RenumRow]) -> tuple[list[Component], list[dict]]:
    """Split the baseline into RENUM components (contract section 4.1). Returns (components, warnings)."""
    rows = sorted(renum, key=lambda r: r.elem_start)
    all_ids = np.concatenate([b.ids for b in mesh.blocks]) if mesh.blocks else np.zeros(0, dtype=np.int64)
    max_id = int(all_ids.max()) if all_ids.size else 0
    warnings: list[dict] = []
    tet_blocks = [b for b in mesh.blocks if b.keyword == "TETRA4"]
    tet_ids = np.concatenate([b.ids for b in tet_blocks]) if tet_blocks else np.zeros(0, dtype=np.int64)
    tet_conn = np.concatenate([b.conn for b in tet_blocks]) if tet_blocks else np.zeros((0, 4), dtype=np.int64)
    other = [b for b in mesh.blocks if b.keyword != "TETRA4"]
    out: list[Component] = []
    for k, r in enumerate(rows):
        lo = r.elem_start
        hi = rows[k + 1].elem_start - 1 if k + 1 < len(rows) else max_id
        nlo = r.node_start
        nhi = rows[k + 1].node_start - 1 if k + 1 < len(rows) else None
        for b in other:
            bad = b.ids[(b.ids >= lo) & (b.ids <= hi)]
            if bad.size:
                raise PaicadError(
                    "GEOM_UNSUPPORTED_ELEMENT", f"component {r.part}: {bad.size} non-TETRA4 elements (/{b.keyword}) in element range {lo}-{hi}"
                )
        sel = (tet_ids >= lo) & (tet_ids <= hi)
        ids = tet_ids[sel]
        conn = tet_conn[sel]
        if ids.size == 0:
            raise PaicadError("GEOM_INPUT_INVALID", f"component {r.part}: no TETRA4 element in element range {lo}-{hi}")
        order = np.argsort(ids, kind="stable")
        ids, conn = ids[order], conn[order]
        nodes = np.unique(conn)
        outside = nodes[(nodes < nlo) | ((nodes > nhi) if nhi is not None else False)]
        if outside.size:
            warnings.append({"code": "RENUM_NODE_RANGE", "part": r.part, "message": f"{outside.size} nodes of {r.part} are outside its node id range"})
        out.append(Component(r.part, r.row, (int(ids[0]), int(ids[-1])), ids, conn, nodes))
    return out, warnings


_TET_FACES = np.array([[1, 2, 3], [0, 3, 2], [0, 1, 3], [0, 2, 1]])


def skin_triangles(tets: np.ndarray) -> np.ndarray:
    """Boundary triangles of a tet set: faces used exactly once (node-sorted key). Returns int64[k,3] node ids."""
    if len(tets) == 0:
        return np.zeros((0, 3), dtype=np.int64)
    faces = tets[:, _TET_FACES].reshape(-1, 3)
    key = np.sort(faces, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    keep = cnt[inv.ravel()] == 1
    return faces[keep]


_HEX_FACES = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
_PENTA_FACES = [[0, 2, 1, -1], [3, 4, 5, -1], [0, 1, 4, 3], [1, 2, 5, 4], [2, 0, 3, 5]]


def _solid_skin_polys(kw: str, conn: np.ndarray) -> list[np.ndarray]:
    if kw in ("TETRA4", "TETRA10"):
        return [skin_triangles(conn[:, :4])]
    table = _HEX_FACES if kw == "BRICK" else _PENTA_FACES
    polys = []
    for f in table:
        idx = [i for i in f if i >= 0]
        polys.append(conn[:, idx])
    tris = []
    for pf in polys:
        if pf.shape[1] == 3:
            tris.append(pf)
        else:
            tris.append(pf[:, [0, 1, 2]])
            tris.append(pf[:, [0, 2, 3]])
    allt = np.concatenate(tris)
    key = np.sort(allt, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return [allt[cnt[inv.ravel()] == 1]]


def surface_triangles(mesh: RadMesh) -> np.ndarray:
    """Shell triangles + solid skin triangles of a whole mesh, as node ids int64[k,3]."""
    tris = []
    for b in mesh.blocks:
        if b.keyword in SHELL_KEYWORDS:
            c = b.conn
            if c.shape[1] == 3:
                tris.append(c)
            else:
                tris.append(c[:, [0, 1, 2]])
                quad = c[:, 2] != c[:, 3]
                tris.append(c[quad][:, [0, 2, 3]])
        elif b.keyword in SOLID_KEYWORDS:
            tris.extend(_solid_skin_polys(b.keyword, b.conn))
    return np.concatenate(tris) if tris else np.zeros((0, 3), dtype=np.int64)


def collect_assembly_surface(assem_dir: str | Path, exclude: list[str | Path], bbox: np.ndarray | None, margin: float = 10.0) -> np.ndarray:
    """Product (non-baseline) surface triangles as coordinates float[k,3,3] (contract section 6.5 collection rule)."""
    d = Path(assem_dir)
    excl = set()
    for e in exclude:
        try:
            excl.add(Path(e).resolve())
        except OSError:
            pass
    files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in (".rad", ".inc") and p.resolve() not in excl)
    ids: list[np.ndarray] = []
    xyz: list[np.ndarray] = []
    blocks: list[ElementBlock] = []
    for f in files:
        m = read_mesh(f)
        ids.append(m.node_ids)
        xyz.append(m.xyz)
        blocks.extend(m.blocks)
    if not blocks:
        return np.zeros((0, 3, 3))
    nid = np.concatenate(ids) if ids else np.zeros(0, dtype=np.int64)
    pts = np.concatenate(xyz) if xyz else np.zeros((0, 3))
    tris = surface_triangles(RadMesh(nid, pts, blocks))
    if tris.size == 0 or nid.size == 0:
        return np.zeros((0, 3, 3))
    order = np.argsort(nid)
    pos = np.searchsorted(nid[order], tris)
    pos = np.clip(pos, 0, len(nid) - 1)
    ok = (nid[order][pos] == tris).all(axis=1)
    coords = pts[order][pos[ok]]
    if bbox is not None:
        lo, hi = bbox[:3] - margin, bbox[3:] + margin
        tmin, tmax = coords.min(axis=1), coords.max(axis=1)
        keep = (tmax >= lo).all(axis=1) & (tmin <= hi).all(axis=1)
        coords = coords[keep]
    return coords


# ---------------- writing (coordinate-only changes) ----------------
_TOKEN = re.compile(rb"\S+")


MIN_SIG = 7  # section 6.4: at least 7 significant digits


def _fmt(value: float, width: int) -> bytes:
    """Section 6.4 value format: ``%.{p}g`` with the most significant digits that fit (p >= 7; a narrow
    field (< 8) still takes the ``%.7g`` text when it fits), else exponent notation keeping 7 significant
    digits (a shorter exponent text only when it is the same 7-digit value), else GEOM_INC_FORMAT."""
    for p in range(max(width - 1, MIN_SIG), MIN_SIG - 1, -1):
        s = f"{value:.{p}g}"
        if "e" in s or "E" in s:
            continue
        if "." not in s and "inf" not in s and "nan" not in s:
            s += "."
        if len(s) <= width:
            return s.rjust(width).encode("ascii")
    ref = float(f"{value:.{MIN_SIG}g}")
    for p in range(width - 1, -1, -1):
        s = f"{value:.{p}e}"
        if len(s) <= width and (p >= MIN_SIG - 1 or float(s) == ref):
            return s.rjust(width).encode("ascii")
    raise PaicadError("GEOM_INC_FORMAT", f"value {value!r} does not fit a {width}-wide field with {MIN_SIG} significant digits")


def rewrite_nodes(data: bytes, new_xyz: dict[int, tuple[float, float, float]]) -> bytes:
    """Return ``data`` with X/Y/Z fields of the given node ids replaced; all other bytes kept.

    Lines of nodes whose coordinates are unchanged are copied verbatim.
    """
    out = []
    in_node = False
    for line in data.splitlines(keepends=True):
        if line.startswith(b"/"):
            in_node = line.rstrip(b"\r\n").strip().upper() == b"/NODE" or line.upper().startswith(b"/NODE/")
            out.append(line)
            continue
        if not in_node or line.startswith((b"#", b"$")) or not line.strip():
            out.append(line)
            continue
        body = line.rstrip(b"\r\n")
        eol = line[len(body) :]
        toks = list(_TOKEN.finditer(body))
        if len(toks) < 4:
            out.append(line)
            continue
        try:
            nid = int(toks[0].group())
        except ValueError:
            out.append(line)
            continue
        new = new_xyz.get(nid)
        if new is None:
            out.append(line)
            continue
        old = [float(t.group()) for t in toks[1:4]]
        if all(a == b for a, b in zip(old, new)):
            out.append(line)
            continue
        buf = bytearray(body)
        # standard I10,F20,F20,F20 columns: the value may fill its field (positional); any other layout
        # (free format) keeps one blank before the value so that tokens never merge
        fixed = all(toks[k].end() == 10 + 20 * k for k in range(4))
        for k in range(3):
            start = toks[k].end()
            end = toks[k + 1].end()
            if fixed:
                buf[start:end] = _fmt(float(new[k]), end - start)
            elif end - start < 2:
                raise PaicadError("GEOM_INC_FORMAT", f"value {float(new[k])!r} does not fit a {end - start}-wide free-format field")
            else:
                buf[start:end] = b" " + _fmt(float(new[k]), end - start - 1)
        out.append(bytes(buf) + eol)
    return b"".join(out)
