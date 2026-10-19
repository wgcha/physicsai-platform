"""Radioss assembly folder reading for the shell path (shell-morph sections 4.1, 6.1), numpy only.

Reads every ``*.rad`` / ``*.inc`` below the assembly folder (same collection rule as ``props scan``):
``/NODE``, element blocks (shell, solid, 1D), ``/PART``, ``/PROP/TYPE1`` thickness, node / surface sets
(``/GRNOD``, ``/SURF``) and the fixing definitions (``/INTER/TYPE2``, ``/RBE2``, ``/RBE3``, ``/RBODY``,
``/BCS``). Fixed width and free format lines are both accepted. Nothing is written.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..common import PaicadError, sha256_file
from ..mesh.radioss import _node, read_text

# element keywords -> number of node fields read from the first data line (1D: orientation nodes ignored)
ELEMENTS = {"SHELL": 4, "SH3N": 3, "TETRA4": 4, "BRICK": 8, "PENTA6": 6, "TETRA10": 10, "BEAM": 2, "SPRING": 2, "TRUSS": 2, "TRIA": 3, "QUAD": 4, "SHELL16": 8, "BRIC20": 8}
SHELL_KW = ("SHELL", "SH3N")
_TOK = re.compile(r"[^\s,]+")


@dataclass
class Block:
    keyword: str
    part: int
    rel: str
    ids: np.ndarray  # int64[m]
    conn: np.ndarray  # int64[m, k] (0 = absent)


@dataclass
class SetDef:
    kind: str  # "GRNOD" | "SURF"
    type: str  # NODE | PART | GRNOD | SEG | SURF | other (unsupported)
    id: int
    title: str
    rel: str
    values: list  # ints (NODE/PART/GRNOD/SURF) or segments [n1..n4] (SEG)


@dataclass
class FixDef:
    kind: str  # INTER_TYPE2 | RBE2 | RBE3 | RBODY | BCS
    id: int
    title: str
    rel: str
    nodes: list[int] = field(default_factory=list)  # nodes given directly (master / reference node)
    grnods: list[int] = field(default_factory=list)
    surf: int | None = None
    dsearch: float = 0.0
    error: str | None = None


@dataclass
class Assembly:
    root: Path
    rels: list[str]
    sha: dict[str, str]
    node_ids: np.ndarray  # int64[n] sorted
    xyz: np.ndarray  # float64[n,3]
    node_rel: np.ndarray  # int32[n] index into rels of the defining file
    blocks: list[Block]
    parts: dict[int, dict]  # part id -> {title, prop, rel}
    props: dict[int, dict]  # prop id -> {type, thickness, title}
    sets: dict[tuple[str, int], SetDef]
    fixdefs: list[FixDef]
    errors: list[str]

    def index(self, ids) -> np.ndarray:
        """Rows of node ids (KeyError-safe: -1 when missing)."""
        ids = np.asarray(ids, dtype=np.int64)
        pos = np.searchsorted(self.node_ids, ids)
        pos = np.clip(pos, 0, max(0, len(self.node_ids) - 1))
        ok = len(self.node_ids) > 0
        out = np.where(ok & (self.node_ids[pos] == ids), pos, -1) if ok else np.full(len(ids), -1)
        return out.astype(np.int64)

    def digest(self) -> str:
        h = hashlib.sha256()
        for r in self.rels:
            h.update(f"{r}\t{self.sha[r]}\n".encode())
        return "sha256:" + h.hexdigest()

    def part_blocks(self, pid: int) -> list[Block]:
        return [b for b in self.blocks if b.part == pid]


def assembly_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise PaicadError("GEOM_INPUT_INVALID", f"assembly folder not found: {root.name}")
    return sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".rad", ".inc")), key=lambda p: p.relative_to(root).as_posix())


def _is_comment(line: str) -> bool:
    return line.startswith(("#", "$"))


def _ints_line(line: str) -> list[int] | None:
    """Integers of a data line: 10-wide fields when every non-blank field is an integer, else free tokens."""
    vals: list[int] = []
    fixed_ok = True
    body = line.rstrip()
    for k in range(0, len(body), 10):
        s = body[k : k + 10].strip()
        if not s:
            continue
        try:
            vals.append(int(s))
        except ValueError:
            fixed_ok = False
            break
    if fixed_ok:
        return vals
    try:
        return [int(t) for t in _TOK.findall(line)]
    except ValueError:
        return None


def _data(lines: list[str], j: int) -> tuple[list[str], int]:
    out = []
    n = len(lines)
    while j < n and not lines[j].startswith("/"):
        if lines[j].strip() and not _is_comment(lines[j]):
            out.append(lines[j])
        j += 1
    return out, j


def _title_and_data(lines: list[str], j: int) -> tuple[str, list[str], int]:
    n = len(lines)
    while j < n and _is_comment(lines[j]):
        j += 1
    title = ""
    if j < n and not lines[j].startswith("/"):
        title = lines[j].strip()
        j += 1
    data, j = _data(lines, j)
    return title, data, j


def _int_field(line: str, col: tuple[int, int], tok: int) -> int:
    """Integer of a fixed column span, else of a free-format token (ValueError if neither)."""
    s = line[col[0] : col[1]].strip()
    if s:
        try:
            return int(s)
        except ValueError:
            pass
    return int(_TOK.findall(line)[tok])


def read_assembly(root: str | Path) -> Assembly:
    root = Path(root)
    files = assembly_files(root)
    rels: list[str] = []
    sha: dict[str, str] = {}
    nid: list[int] = []
    nxyz: list[tuple[float, float, float]] = []
    nrel: list[int] = []
    blocks: list[Block] = []
    parts: dict[int, dict] = {}
    props: dict[int, dict] = {}
    sets: dict[tuple[str, int], SetDef] = {}
    fixdefs: list[FixDef] = []
    errors: list[str] = []
    for fi, p in enumerate(files):
        rel = p.relative_to(root).as_posix()
        rels.append(rel)
        sha[rel] = sha256_file(p)
        lines = read_text(p).splitlines()
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.startswith("/"):
                i += 1
                continue
            kw = [s.strip() for s in line.strip().split("/")[1:]]
            head = kw[0].upper() if kw else ""
            sub = kw[1].upper() if len(kw) > 1 else ""
            j = i + 1
            try:
                if head == "NODE":
                    data, j = _data(lines, j)
                    for d in data:
                        r = _node(d)
                        if r is None:
                            raise PaicadError("GEOM_INPUT_INVALID", f"cannot parse /NODE line in {rel}: {d[:40]!r}")
                        nid.append(r[0])
                        nxyz.append(r[1:])
                        nrel.append(fi)
                elif head in ELEMENTS and len(kw) >= 2 and sub.lstrip("-").isdigit():
                    k = ELEMENTS[head]
                    data, j = _data(lines, j)
                    ids, conn = [], []
                    skip_next = head == "TETRA10"
                    for d in data:
                        v = _ints_line(d)
                        if not v or len(v) < 2:
                            if skip_next:
                                continue
                            raise PaicadError("GEOM_INPUT_INVALID", f"cannot parse /{head} line in {rel}: {d[:40]!r}")
                        c = v[1 : 1 + k]
                        if head == "SHELL" and len(c) == 3:
                            c = c + [c[-1]]
                        ids.append(v[0])
                        conn.append((c + [0] * k)[:k])
                    blocks.append(Block(head, int(sub), rel, np.array(ids, dtype=np.int64), np.array(conn, dtype=np.int64).reshape(-1, k)))
                elif head == "PART" and sub.isdigit():
                    title, data, j = _title_and_data(lines, j)
                    prop = None
                    if data:
                        v = _ints_line(data[0][:30]) or []
                        prop = v[0] if v else None
                    parts[int(sub)] = {"title": title, "prop": prop, "rel": rel}
                elif head == "PROP" and len(kw) >= 3 and kw[2].isdigit():
                    while j < n and _is_comment(lines[j]):
                        j += 1
                    title = lines[j].strip() if j < n and not lines[j].startswith("/") else ""
                    j += 1 if j < n and not lines[j].startswith("/") else 0
                    cards = []  # blank lines are data lines (all fields default), comments are skipped
                    while j < n and not lines[j].startswith("/"):
                        if not _is_comment(lines[j]):
                            cards.append(lines[j])
                        j += 1
                    th = None
                    if sub in ("TYPE1", "SHELL") and len(cards) >= 3:
                        from ..props import PROP_FIELDS, PROP_THICK, field_value

                        try:
                            th = field_value(cards[2], PROP_FIELDS, PROP_THICK)
                        except PaicadError:
                            th = None
                    props[int(kw[2])] = {"type": sub, "thickness": th, "title": title}
                elif head in ("GRNOD", "SURF") and len(kw) >= 3 and kw[2].lstrip("-").isdigit():
                    sid = int(kw[2])
                    title, data, j = _title_and_data(lines, j)
                    values: list = []
                    if (head, sub) in (("GRNOD", "NODE"), ("GRNOD", "PART"), ("GRNOD", "GRNOD"), ("SURF", "PART"), ("SURF", "SURF")):
                        for d in data:
                            v = _ints_line(d)
                            if v is None:
                                raise ValueError(f"/{head}/{sub}/{sid}: cannot parse {d[:40]!r}")
                            values += v
                    elif (head, sub) == ("SURF", "SEG"):
                        for d in data:
                            v = _ints_line(d)
                            if v is None or len(v) < 4:
                                raise ValueError(f"/SURF/SEG/{sid}: cannot parse {d[:40]!r}")
                            seg = v[1:5] + [0] * (4 - len(v[1:5]))
                            values.append(seg)
                    if (head, sid) in sets:
                        errors.append(f"/{head}/{sid} is defined twice ({sets[(head, sid)].rel}, {rel})")
                    sets[(head, sid)] = SetDef(head, sub, sid, title, rel, values)
                elif head == "INTER" and sub == "TYPE2" and len(kw) >= 3 and kw[2].isdigit():
                    title, data, j = _title_and_data(lines, j)
                    fd = FixDef("INTER_TYPE2", int(kw[2]), title, rel)
                    try:
                        toks = _TOK.findall(data[0])
                        fd.grnods = [int(toks[0])]
                        fd.surf = int(toks[1])
                        if len(toks) >= 8:
                            fd.dsearch = float(toks[7])
                        elif len(data) > 1:
                            fd.dsearch = float(_TOK.findall(data[1])[0])
                    except (ValueError, IndexError):
                        fd.error = "cannot parse the card"
                    fixdefs.append(fd)
                elif head == "RBE2" and sub.isdigit():
                    title, data, j = _title_and_data(lines, j)
                    fd = FixDef("RBE2", int(sub), title, rel)
                    try:
                        fd.nodes = [_int_field(data[0], (0, 10), 0)]
                        fd.grnods = [_int_field(data[0], (30, 40), 3)]
                    except (ValueError, IndexError):
                        fd.error = "cannot parse the card"
                    fixdefs.append(fd)
                elif head == "RBE3" and sub.isdigit():
                    title, data, j = _title_and_data(lines, j)
                    fd = FixDef("RBE3", int(sub), title, rel)
                    try:
                        fd.nodes = [_int_field(data[0], (0, 10), 0)]
                        for d in data[1:]:
                            fd.grnods.append(int(_TOK.findall(d)[-1]))
                        if not fd.grnods:
                            raise ValueError
                    except (ValueError, IndexError):
                        fd.error = "cannot parse the card"
                    fixdefs.append(fd)
                elif head == "RBODY" and sub.isdigit():
                    title, data, j = _title_and_data(lines, j)
                    fd = FixDef("RBODY", int(sub), title, rel)
                    try:
                        fd.nodes = [_int_field(data[0], (0, 10), 0)]
                        g = _int_field(data[0], (60, 70), 5)
                        fd.grnods = [g] if g else []
                    except (ValueError, IndexError):
                        fd.error = "cannot parse the card"
                    fixdefs.append(fd)
                elif head == "BCS" and sub.isdigit():
                    title, data, j = _title_and_data(lines, j)
                    fd = FixDef("BCS", int(sub), title, rel)
                    try:
                        fd.grnods = [_int_field(data[0], (20, 30), -1)]
                    except (ValueError, IndexError):
                        fd.error = "cannot parse the card"
                    fixdefs.append(fd)
            except ValueError as ex:
                errors.append(f"{ex} in {rel}")
            i = max(j, i + 1)
    ids = np.array(nid, dtype=np.int64)
    xyz = np.array(nxyz, dtype=float).reshape(-1, 3)
    rr = np.array(nrel, dtype=np.int32)
    order = np.argsort(ids, kind="stable")
    ids, xyz, rr = ids[order], xyz[order], rr[order]
    if len(ids) > 1 and np.any(ids[1:] == ids[:-1]):
        dup = int(ids[1:][ids[1:] == ids[:-1]][0])
        raise PaicadError("GEOM_INPUT_INVALID", f"node {dup} is defined more than once in the assembly folder")
    return Assembly(root, rels, sha, ids, xyz, rr, blocks, parts, props, sets, fixdefs, errors)


# ------------------------------------------------------------------ set resolution
class SetError(Exception):
    pass


def resolve_grnod(asm: Assembly, gid: int, _seen: set | None = None) -> set[int]:
    seen = _seen if _seen is not None else set()
    sd = asm.sets.get(("GRNOD", gid))
    if sd is None:
        raise SetError(f"/GRNOD {gid} not found")
    if gid in seen:
        raise SetError(f"/GRNOD/GRNOD {gid} is recursive")
    seen = seen | {gid}
    if sd.type == "NODE":
        return {int(x) for x in sd.values if x > 0}
    if sd.type == "PART":
        out: set[int] = set()
        for pid in sd.values:
            bl = asm.part_blocks(int(pid))
            if not bl:
                raise SetError(f"/GRNOD/PART/{gid}: part {pid} has no elements")
            for b in bl:
                out.update(int(x) for x in np.unique(b.conn) if x > 0)
        return out
    if sd.type == "GRNOD":
        out = set()
        for g in sd.values:
            out |= resolve_grnod(asm, int(g), seen)
        return out
    raise SetError(f"/GRNOD/{sd.type}/{gid} ({sd.rel}) is not supported")


def shell_segments(b: Block) -> list[list[int]]:
    return [[int(x) for x in c if x > 0] for c in b.conn]


def resolve_surf(asm: Assembly, sid: int, _seen: set | None = None) -> list[list[int]]:
    seen = _seen if _seen is not None else set()
    sd = asm.sets.get(("SURF", sid))
    if sd is None:
        raise SetError(f"/SURF {sid} not found")
    if sid in seen:
        raise SetError(f"/SURF/SURF {sid} is recursive")
    seen = seen | {sid}
    if sd.type == "SEG":
        return [[int(x) for x in s if x > 0] for s in sd.values]
    if sd.type == "PART":
        out: list[list[int]] = []
        for pid in sd.values:
            bl = asm.part_blocks(int(pid))
            if not bl:
                raise SetError(f"/SURF/PART/{sid}: part {pid} has no elements")
            for b in bl:
                if b.keyword not in SHELL_KW:
                    raise SetError(f"/SURF/PART/{sid}: part {pid} has /{b.keyword} elements (only shell parts are supported)")
                out += shell_segments(b)
        return out
    if sd.type == "SURF":
        out = []
        for s in sd.values:
            out += resolve_surf(asm, int(s), seen)
        return out
    raise SetError(f"/SURF/{sd.type}/{sid} ({sd.rel}) is not supported")


def seg_triangles(segs: list[list[int]]) -> tuple[np.ndarray, np.ndarray]:
    """(triangles[k,3] node ids, segment index[k]) - quads split along the 1-3 diagonal, n3 = n4 -> triangle."""
    tris, owner = [], []
    for i, s in enumerate(segs):
        n = list(dict.fromkeys(x for x in s if x > 0)) if len(s) == 4 and s[2] == s[3] else [x for x in s if x > 0]
        if len(n) == 3:
            tris.append(n)
            owner.append(i)
        elif len(n) == 4:
            tris += [[n[0], n[1], n[2]], [n[0], n[2], n[3]]]
            owner += [i, i]
    return np.array(tris, dtype=np.int64).reshape(-1, 3), np.array(owner, dtype=np.int64)


def shell_part(asm: Assembly, pid: int) -> dict:
    """Shell elements of one part: ids[m], conn[m,4] node ids (triangles: n4 = n3), is_tri[m], files."""
    ids, conn, tri, files, other = [], [], [], [], 0
    for b in asm.part_blocks(pid):
        if b.keyword == "SHELL":
            ids.append(b.ids)
            conn.append(b.conn)
            tri.append(b.conn[:, 2] == b.conn[:, 3])
            files.append(b.rel)
        elif b.keyword == "SH3N":
            ids.append(b.ids)
            conn.append(np.concatenate([b.conn, b.conn[:, 2:3]], axis=1))
            tri.append(np.ones(len(b.ids), dtype=bool))
            files.append(b.rel)
        else:
            other += len(b.ids)
    if ids:
        I = np.concatenate(ids)
        C = np.concatenate(conn)
        T = np.concatenate(tri)
        o = np.argsort(I, kind="stable")
        I, C, T = I[o], C[o], T[o]
    else:
        I, C, T = np.zeros(0, dtype=np.int64), np.zeros((0, 4), dtype=np.int64), np.zeros(0, dtype=bool)
    return {"ids": I, "conn": C, "tri": T, "files": sorted(set(files)), "other": other}
