"""Assembly include tree: streaming index of every file reachable from the starter (asm-match.md sections 4.1, 5.1).

numpy only (no OCP). The starter is the one direct ``*.rad`` of the assembly folder with a ``/BEGIN`` card
(IK-C1 rule, same as ``cushion write``); ``#include <path>`` lines (case-insensitive, leading blanks allowed,
path relative to the including file's folder, ``/`` or ``\\``) are followed depth first. File names carry no
meaning: ``/PART`` cards, element blocks and ``/NODE`` lines are collected wherever they are.

Each file is read line by line (never loaded whole) into a :class:`FileIndex`: node id / coordinates / line
number, element blocks ``/<KW>/<pid>`` (ids + connectivity), ``/PART`` cards (title, prop, mat) and include
lines. With a cache folder the index is stored as ``<cache_dir>/<sha256>.idx.npz`` (key = file content, so a
renamed or moved copy hits; a different ``schema_version`` / ``engine_version`` is ignored and rebuilt).
"""

from __future__ import annotations

import hashlib
import json
import os
from array import array
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import __version__
from ..common import PaicadError, sha256_file

INDEX_SCHEMA = 1
# element keywords -> node fields read from the (single) data line; continuation-line elements are not indexed
ELEMENTS = {"TETRA4": 4, "TETRA10": 10, "BRICK": 8, "PENTA6": 6, "SHELL": 4, "SH3N": 3, "BEAM": 3, "SPRING": 2, "TRUSS": 2, "TRIA": 3, "QUAD": 4}
UNUSED_LIST_MAX = 10


@dataclass
class FileIndex:
    sha: str
    includes: list[tuple[int, str]]  # (0-based line, raw path)
    begin: bool
    parts: list[dict]  # {pid, title, line, prop, mat}
    blocks: list[tuple[str, int, int, int, int]]  # (keyword, pid, line, count, k)
    node_id: np.ndarray  # int64[n] (file order)
    node_xyz: np.ndarray  # float64[n,3]
    node_line: np.ndarray  # int64[n] 0-based line of the definition
    elem_id: np.ndarray  # int64[m] (block order)
    elem_conn: np.ndarray  # int64[sum count*k] flat


def _err(rel: str, line: int, what: str, raw: bytes) -> PaicadError:
    return PaicadError("GEOM_INPUT_INVALID", f"cannot parse {what} in {rel} line {line + 1}: {raw[:40].decode('latin-1')!r}")


def _node_b(raw: bytes) -> tuple[int, float, float, float] | None:
    """``/NODE`` data line: I10,F20,F20,F20 columns, else free format (same rule as ``mesh.radioss._node``)."""
    try:
        return int(raw[0:10]), float(raw[10:30]), float(raw[30:50]), float(raw[50:70])
    except ValueError:
        pass
    t = raw.split()
    if len(t) >= 4:
        try:
            return int(t[0]), float(t[1]), float(t[2]), float(t[3])
        except ValueError:
            return None
    return None


def _ints_b(raw: bytes, n: int) -> list[int] | None:
    """First ``n`` integers of an element line: 10-wide fields (blank field = 0), else free tokens."""
    body = raw.rstrip()
    try:
        vals = []
        for p in range(0, min(len(body), 10 * n), 10):
            s = body[p : p + 10]
            vals.append(int(s) if s.strip() else 0)
        return vals
    except ValueError:
        pass
    try:
        return [int(t) for t in body.replace(b",", b" ").split()[:n]]
    except ValueError:
        return None


def _part_refs(raw: bytes) -> tuple[int, int]:
    line = raw.rstrip(b"\r\n")
    try:
        return int(line[0:10].strip() or 0), int(line[10:20].strip() or 0)
    except ValueError:
        pass
    toks = line.replace(b",", b" ").split()
    try:
        return int(toks[0]), (int(toks[1]) if len(toks) > 1 else 0)
    except (ValueError, IndexError):
        return 0, 0


def parse_file(path: Path, rel: str, sha: str) -> FileIndex:
    """One streaming pass over ``path`` (binary lines split on ``\\n``; the same split as ``asm write``)."""
    nid, nxyz, nline = array("q"), array("d"), array("q")
    eid, econn = array("q"), array("q")
    blocks: list[list] = []
    parts: list[dict] = []
    includes: list[tuple[int, str]] = []
    begin = False
    mode = 0  # 0 none, 1 node, 2 element, 3 part title, 4 part refs
    k = 0
    cur: list | None = None  # current element block record
    part: dict | None = None
    with open(path, "rb") as f:
        for ln, raw in enumerate(f):
            if raw[:1] == b"/":
                if cur is not None:
                    cur = None
                kw = raw.strip().split(b"/")
                head = kw[1].strip().upper() if len(kw) > 1 else b""
                sub = kw[2].strip() if len(kw) > 2 else b""
                mode = 0
                if head == b"NODE":
                    mode = 1
                elif head.decode("latin-1") in ELEMENTS and sub.lstrip(b"-").isdigit():
                    name = head.decode("latin-1")
                    k = ELEMENTS[name]
                    cur = [name, int(sub), ln, 0, k]
                    blocks.append(cur)
                    mode = 2
                elif head == b"PART" and sub.isdigit():
                    part = {"pid": int(sub), "title": "", "line": ln, "prop": 0, "mat": 0}
                    parts.append(part)
                    mode = 3
                elif head == b"BEGIN":
                    begin = True
                continue
            s = raw.lstrip()
            if s[:1] in (b"#", b"$"):
                if s[:8].lower() == b"#include":
                    p = s[8:].strip().strip(b"\"'").decode("latin-1")
                    if p:
                        includes.append((ln, p))
                    mode = 0
                    cur = None
                continue
            if mode == 3:  # title line (may be blank)
                part["title"] = raw.strip().decode("latin-1")  # type: ignore[index]
                mode = 4
                continue
            if not s:
                continue
            if mode == 1:
                r = _node_b(raw)
                if r is None:
                    raise _err(rel, ln, "/NODE line", raw)
                nid.append(r[0])
                nxyz.extend(r[1:])
                nline.append(ln)
            elif mode == 2:
                v = _ints_b(raw, k + 1)
                if not v or len(v) < 2:
                    raise _err(rel, ln, f"/{cur[0]} line", raw)  # type: ignore[index]
                c = v[1 : 1 + k]
                if len(c) < k:
                    c = c + [0] * (k - len(c))
                if cur[0] == "SHELL" and c[3] == 0:  # type: ignore[index]
                    c[3] = c[2]  # triangle written as /SHELL (same as mesh.radioss)
                eid.append(v[0])
                econn.extend(c)
                cur[3] += 1  # type: ignore[index]
            elif mode == 4:
                part["prop"], part["mat"] = _part_refs(raw)  # type: ignore[index]
                mode = 0
    return FileIndex(
        sha,
        includes,
        begin,
        parts,
        [tuple(b) for b in blocks if b[3] > 0],  # type: ignore[misc]
        np.frombuffer(nid, dtype=np.int64).copy() if len(nid) else np.zeros(0, dtype=np.int64),
        np.frombuffer(nxyz, dtype=np.float64).reshape(-1, 3).copy() if len(nxyz) else np.zeros((0, 3)),
        np.frombuffer(nline, dtype=np.int64).copy() if len(nline) else np.zeros(0, dtype=np.int64),
        np.frombuffer(eid, dtype=np.int64).copy() if len(eid) else np.zeros(0, dtype=np.int64),
        np.frombuffer(econn, dtype=np.int64).copy() if len(econn) else np.zeros(0, dtype=np.int64),
    )


# ------------------------------------------------------------------ cache
def _cache_path(cache_dir: Path, sha: str) -> Path:
    return cache_dir / f"{sha}.idx.npz"


def load_cached(cache_dir: Path | None, sha: str) -> FileIndex | None:
    if cache_dir is None:
        return None
    p = _cache_path(cache_dir, sha)
    if not p.is_file():
        return None
    try:
        with np.load(p, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            if meta.get("schema_version") != INDEX_SCHEMA or meta.get("engine_version") != __version__ or meta.get("sha256") != sha:
                return None
            arr = {k: np.asarray(z[k]) for k in ("node_id", "node_xyz", "node_line", "elem_id", "elem_conn")}
    except (OSError, ValueError, KeyError):
        return None
    return FileIndex(
        sha,
        [(int(a), str(b)) for a, b in meta["includes"]],
        bool(meta["begin"]),
        list(meta["parts"]),
        [(str(b[0]), int(b[1]), int(b[2]), int(b[3]), int(b[4])) for b in meta["blocks"]],
        arr["node_id"].astype(np.int64),
        arr["node_xyz"].astype(np.float64).reshape(-1, 3),
        arr["node_line"].astype(np.int64),
        arr["elem_id"].astype(np.int64),
        arr["elem_conn"].astype(np.int64),
    )


def save_cached(cache_dir: Path | None, fi: FileIndex) -> None:
    """Best effort (a cache that cannot be written only costs time); atomic replace."""
    if cache_dir is None:
        return
    meta = {
        "schema_version": INDEX_SCHEMA,
        "engine_version": __version__,
        "sha256": fi.sha,
        "includes": fi.includes,
        "begin": fi.begin,
        "parts": fi.parts,
        "blocks": [list(b) for b in fi.blocks],
    }
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        p = _cache_path(cache_dir, fi.sha)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        with open(tmp, "wb") as f:
            np.savez(f, meta=np.array(json.dumps(meta)), node_id=fi.node_id, node_xyz=fi.node_xyz, node_line=fi.node_line, elem_id=fi.elem_id, elem_conn=fi.elem_conn)
        os.replace(tmp, p)
    except OSError:
        pass


# ------------------------------------------------------------------ tree
@dataclass
class TreeFile:
    rel: str
    path: Path
    sha: str
    includes: list[str]
    index: FileIndex


@dataclass
class Block:
    keyword: str
    pid: int
    file: int  # index into AsmIndex.files
    line: int
    ids: np.ndarray  # int64[m]
    conn: np.ndarray  # int64[m,k] (0 = absent)


@dataclass
class AsmIndex:
    root: Path
    starter: str
    files: list[TreeFile]
    node_id: np.ndarray  # int64[n] definition order (tree order, then line), duplicates removed (first kept)
    node_xyz: np.ndarray  # float64[n,3]
    node_file: np.ndarray  # int32[n]
    node_line: np.ndarray  # int64[n]
    sorter: np.ndarray  # int64[n]: node_id[sorter] ascending
    duplicates: list[dict]  # [{node, files}] (all duplicate ids, files in tree order)
    parts: dict[int, dict]  # pid -> {title, def_file, prop, mat} (first /PART card)
    duplicate_parts: list[int]
    blocks: list[Block]
    cache: dict
    warnings: list[dict] = field(default_factory=list)

    def digest(self) -> str:
        return tree_digest([(f.rel, f.sha) for f in self.files])

    def lookup(self, ids) -> np.ndarray:
        """Definition rows of node ids (-1 when not defined in the tree)."""
        ids = np.asarray(ids, dtype=np.int64)
        if len(self.node_id) == 0:
            return np.full(ids.shape, -1, dtype=np.int64)
        srt = self.node_id[self.sorter]
        pos = np.clip(np.searchsorted(srt, ids), 0, len(srt) - 1)
        return np.where(srt[pos] == ids, self.sorter[pos], -1).astype(np.int64)

    def pid_blocks(self, pid: int) -> list[Block]:
        return [b for b in self.blocks if b.pid == pid]

    def rel_paths(self) -> list[Path]:
        return [f.path for f in self.files]


def tree_digest(items: list[tuple[str, str]]) -> str:
    """``sha256:<hex>`` of the (relative path, sha256) list sorted by path (asm-match.md section 4.1)."""
    h = hashlib.sha256()
    for rel, sha in sorted(items):
        h.update(f"{rel}\t{sha}\n".encode())
    return "sha256:" + h.hexdigest()


def find_starter(root: Path) -> Path:
    from ..writers.radioss_cushion import find_starter as _find

    return _find(root, set())


def _inside(real: Path, root_real: Path) -> bool:
    try:
        real.relative_to(root_real)
        return True
    except ValueError:
        return False


def build(assem_dir: str | Path, cache_dir: str | Path | None = None, progress=None) -> AsmIndex:
    """Resolve the include tree from the starter and index every file (cache by content sha256)."""
    root = Path(assem_dir)
    if not root.is_dir():
        raise PaicadError("GEOM_INPUT_INVALID", f"assembly folder not found: {root.name}")
    cdir = Path(cache_dir) if cache_dir else None
    root_real = root.resolve()
    starter = find_starter(root)
    if starter.is_symlink():
        raise PaicadError("ASM_INCLUDE_OUTSIDE", f"starter {starter.name} is a link")
    files: list[TreeFile] = []
    seen: dict[str, int] = {}
    hits = misses = 0

    def visit(path: Path, rel: str, stack: list[str]) -> None:
        nonlocal hits, misses
        if progress:
            progress(f"indexing {rel}")
        sha = sha256_file(path)
        fi = load_cached(cdir, sha)
        if fi is None:
            misses += 1
            fi = parse_file(path, rel, sha)
            save_cached(cdir, fi)
        else:
            hits += 1
        tf = TreeFile(rel, path, sha, [], fi)
        seen[rel] = len(files)
        files.append(tf)
        for ln, raw in fi.includes:
            target = path.parent / raw.replace("\\", "/")
            where = f"{rel} line {ln + 1}"
            if target.is_symlink():
                raise PaicadError("ASM_INCLUDE_OUTSIDE", f"include {raw!r} ({where}) is a link")
            real = target.resolve()
            if not _inside(real, root_real):
                raise PaicadError("ASM_INCLUDE_OUTSIDE", f"include {raw!r} ({where}) points outside the assembly folder")
            if not real.is_file():
                raise PaicadError("ASM_INCLUDE_MISSING", f"include {raw!r} ({where}) not found")
            trel = real.relative_to(root_real).as_posix()
            if trel in stack:
                raise PaicadError("GEOM_INPUT_INVALID", f"include cycle: {' -> '.join(stack + [trel])}")
            if trel in seen:
                raise PaicadError("GEOM_INPUT_INVALID", f"{trel} is included more than once ({where})")
            tf.includes.append(trel)
            visit(root / trel, trel, stack + [trel])

    srel = starter.resolve().relative_to(root_real).as_posix()
    visit(root / srel, srel, [srel])
    warnings: list[dict] = []
    used = {f.rel.lower() for f in files}
    unused = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix.lower() in (".rad", ".inc") and p.name.lower() not in used)
    if unused:
        warnings.append(
            {"code": "ASM_FILE_UNUSED", "count": len(unused), "files": unused[:UNUSED_LIST_MAX], "message": f"{len(unused)} files of the assembly folder are not in the include tree (not read)"}
        )
    return _merge(root, srel, files, {"hits": hits, "misses": misses}, warnings)


def _merge(root: Path, starter: str, files: list[TreeFile], cache: dict, warnings: list[dict]) -> AsmIndex:
    ids = [f.index.node_id for f in files]
    nid = np.concatenate(ids) if ids else np.zeros(0, dtype=np.int64)
    xyz = np.concatenate([f.index.node_xyz for f in files]) if files else np.zeros((0, 3))
    nfile = np.concatenate([np.full(len(f.index.node_id), k, dtype=np.int32) for k, f in enumerate(files)]) if files else np.zeros(0, dtype=np.int32)
    nline = np.concatenate([f.index.node_line for f in files]) if files else np.zeros(0, dtype=np.int64)
    order = np.argsort(nid, kind="stable")
    srt = nid[order]
    dup_mask = np.zeros(len(nid), dtype=bool)
    duplicates: list[dict] = []
    if len(srt) > 1:
        same = srt[1:] == srt[:-1]
        if same.any():
            dup_mask[order[1:][same]] = True
            for v in np.unique(srt[1:][same]):
                rows = order[np.searchsorted(srt, v) : np.searchsorted(srt, v, side="right")]
                duplicates.append({"node": int(v), "files": [files[int(nfile[r])].rel for r in sorted(rows)]})
    keep = ~dup_mask
    nid, xyz, nfile, nline = nid[keep], xyz[keep], nfile[keep], nline[keep]
    parts: dict[int, dict] = {}
    dup_parts: list[int] = []
    blocks: list[Block] = []
    for k, f in enumerate(files):
        for p in f.index.parts:
            pid = int(p["pid"])
            if pid in parts:
                if pid not in dup_parts:
                    dup_parts.append(pid)
                continue
            parts[pid] = {"title": p["title"], "def_file": f.rel, "prop": int(p["prop"]), "mat": int(p["mat"])}
        e0 = c0 = 0
        for kw, pid, line, count, kk in f.index.blocks:
            blocks.append(Block(kw, pid, k, line, f.index.elem_id[e0 : e0 + count], f.index.elem_conn[c0 : c0 + count * kk].reshape(count, kk)))
            e0 += count
            c0 += count * kk
    return AsmIndex(root, starter, files, nid, xyz, nfile, nline, np.argsort(nid, kind="stable"), duplicates, parts, sorted(dup_parts), blocks, cache, warnings)
