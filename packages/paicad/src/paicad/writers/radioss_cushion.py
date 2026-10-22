"""Radioss cushion starter rad (input-kind.md section 5.2, GE-C19) - numpy only, no OCP.

One self-contained starter file made of byte copies:

1. ``#RADIOSS STARTER`` + the assembly starter's ``/BEGIN`` card (run name line = ``--out-rad`` stem)
2. the cushion ``/PART`` cards + the ``/PROP`` and ``/MAT`` cards they reference (first definition in
   ``--inc`` then the assembly folder files by name; missing -> warning ``CUSHION_PART_DEF_MISSING``)
3. ``/NODE``: the lines of the nodes used by cushion elements (``--inc`` order, ids and coordinates kept)
4. the ``/TETRA4/<pid>`` blocks of the cushion components (RENUM rule, section 4.1), lines kept
5. ``/END``

A card is the keyword line up to the next ``/`` line or ``#include`` line (never copied).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..common import PaicadError
from ..mesh.radioss import RenumRow, _ints, _node, components, is_node_keyword, parse_text, rewrite_node_line

DEF_KINDS = ("PART", "PROP", "MAT")
MESH_FILE_PREFIX = "eps_mesh"  # SimLab cushion mesh files are never sources (input-kind.md section 5.2)
WARN_DEF_MISSING = "CUSHION_PART_DEF_MISSING"


@dataclass
class CushionRad:
    data: bytes
    node_count: int
    elem_count: int
    parts: list[dict]
    begin_from: str
    def_sources: list[str]
    warnings: list[dict] = field(default_factory=list)


def _eol_of(lines: list[bytes]) -> bytes:
    for ln in lines:
        if ln.endswith(b"\r\n"):
            return b"\r\n"
        if ln.endswith(b"\n"):
            return b"\n"
    return b"\n"


def _keyword(line: bytes) -> list[str]:
    """``/PROP/TYPE14/5`` -> ``["PROP", "TYPE14", "5"]`` (upper case, stripped)."""
    return [p.strip().upper() for p in line.rstrip(b"\r\n").decode("latin-1").strip().split("/")[1:]]


def _is_comment(line: bytes) -> bool:
    return line.startswith((b"#", b"$"))


def _is_include(line: bytes) -> bool:
    return line[:8].lower() == b"#include"


def _card_ranges(lines: list[bytes]) -> list[tuple[int, int]]:
    """[start, end) line ranges of the keyword cards: from a ``/`` line to the next ``/`` or ``#include`` line."""
    out = []
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(b"/") or _is_include(ln):
            if start is not None:
                out.append((start, i))
            start = i if ln.startswith(b"/") else None
    if start is not None:
        out.append((start, len(lines)))
    return out


def _with_eol(line: bytes, eol: bytes) -> bytes:
    return line if line.endswith((b"\n", b"\r")) else line + eol


def _def_key(kw: list[str]) -> tuple[str, int] | None:
    """(kind, id) of a ``/PART/<id>``, ``/PROP/<type>/<id>`` or ``/MAT/<law>/<id>`` keyword."""
    if not kw or kw[0] not in DEF_KINDS:
        return None
    pos = 1 if kw[0] == "PART" else 2
    if len(kw) <= pos:
        return None
    try:
        return kw[0], int(kw[pos])
    except ValueError:
        return None


def _part_refs(card: list[bytes], pid: int) -> tuple[int, int]:
    """(prop_ID, mat_ID) of a /PART card: title line, then ``prop_ID mat_ID ...`` (I10 fields, free format fallback)."""
    data = [ln for ln in card[1:] if not _is_comment(ln) and ln.strip()]
    if len(data) < 2:
        raise PaicadError("GEOM_INPUT_INVALID", f"/PART/{pid} has no prop_ID/mat_ID line")
    line = data[1].rstrip(b"\r\n").decode("latin-1")
    try:
        return int(line[0:10].strip() or 0), int(line[10:20].strip() or 0)
    except ValueError:
        pass
    toks = line.replace(",", " ").split()
    try:
        return int(toks[0]), (int(toks[1]) if len(toks) > 1 else 0)
    except (ValueError, IndexError):
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot parse the prop_ID/mat_ID line of /PART/{pid}") from None


def _excluded(name: str, names: set[str]) -> bool:
    low = name.lower()
    return low.startswith(MESH_FILE_PREFIX) or low in names


def find_starter(assem: Path, exclude: set[str]) -> Path:
    """The one ``*.rad`` file of the assembly folder (direct children) holding a ``/BEGIN`` card."""
    found = []
    for p in sorted((q for q in assem.iterdir() if q.is_file() and q.suffix.lower() == ".rad"), key=lambda q: q.name):
        if _excluded(p.name, exclude):
            continue
        with open(p, "rb") as f:
            if any(ln.startswith(b"/") and _keyword(ln)[:1] == ["BEGIN"] for ln in f):
                found.append(p)
    if not found:
        raise PaicadError("GEOM_INPUT_INVALID", "no starter (*.rad with /BEGIN) in the assembly folder")
    if len(found) > 1:
        raise PaicadError("GEOM_INPUT_INVALID", "more than one starter (*.rad with /BEGIN) in the assembly folder: " + ", ".join(p.name for p in found[:10]))
    return found[0]


def begin_card(starter: Path, run_name: str) -> list[bytes]:
    lines = starter.read_bytes().splitlines(keepends=True)
    eol = _eol_of(lines)
    for a, b in _card_ranges(lines):
        if _keyword(lines[a])[:1] == ["BEGIN"]:
            card = [_with_eol(ln, eol) for ln in lines[a:b]]
            for k in range(1, len(card)):
                if not _is_comment(card[k]):
                    ln = card[k]
                    tail = ln[len(ln.rstrip(b"\r\n")) :] or eol
                    card[k] = run_name.encode("utf-8") + tail
                    return card
            raise PaicadError("GEOM_INPUT_INVALID", f"/BEGIN card of {starter.name} has no run name line")
    raise PaicadError("GEOM_INPUT_INVALID", f"no /BEGIN card in {starter.name}")  # pragma: no cover - find_starter checked


def source_files(inc: Path, assem: Path, exclude: set[str]) -> list[Path]:
    """Definition search order: ``--inc`` first, then the assembly folder's direct ``*.rad``/``*.inc`` by name."""
    rest = sorted((p for p in assem.iterdir() if p.is_file() and p.suffix.lower() in (".rad", ".inc") and not _excluded(p.name, exclude)), key=lambda p: p.name)
    return [inc] + rest


def find_definitions(files: list, pids: list[int]) -> tuple[dict[tuple[str, int], tuple[str, list[bytes]]], list[tuple[str, int]]]:
    """First definition of each cushion PART and of the PROP/MAT ids it references. ``files``: paths (label =
    file name) or ``(label, path)`` pairs. Returns ({(kind, id): (label, card lines)}, ordered wanted keys)."""
    found: dict[tuple[str, int], tuple[str, list[bytes]]] = {}
    want_parts = [("PART", p) for p in pids]

    def refs() -> list[tuple[str, int]]:
        props, mats = [], []
        for key in want_parts:
            if key in found:
                prop, mat = _part_refs(found[key][1], key[1])
                if prop > 0 and ("PROP", prop) not in props:
                    props.append(("PROP", prop))
                if mat > 0 and ("MAT", mat) not in mats:
                    mats.append(("MAT", mat))
        return props + mats

    def done() -> bool:
        return all(k in found for k in want_parts) and all(k in found for k in refs())

    for item in files:
        if done():
            break
        label, f = item if isinstance(item, tuple) else (item.name, item)
        lines = f.read_bytes().splitlines(keepends=True)
        eol = _eol_of(lines)
        for a, b in _card_ranges(lines):
            key = _def_key(_keyword(lines[a]))
            if key is not None and key not in found:
                found[key] = (label, [_with_eol(ln, eol) for ln in lines[a:b]])
    wanted = want_parts + refs()
    return {k: found[k] for k in wanted if k in found}, wanted


def build(inc: Path, renum: list[RenumRow], assem: Path, out_name: str) -> CushionRad:
    data = inc.read_bytes()
    mesh = parse_text(data.decode("latin-1"))
    comps, comp_warn = components(mesh, renum)
    elem_comp: dict[int, str] = {}
    for c in comps:
        for e in c.tet_ids.tolist():
            elem_comp[int(e)] = c.part
    need_nodes = set(np.unique(np.concatenate([c.node_ids for c in comps])).tolist())
    lines = data.splitlines(keepends=True)
    eol = _eol_of(lines)

    node_head: bytes | None = None
    node_lines: list[bytes] = []
    seen_nodes: set[int] = set()
    tet_out: list[bytes] = []
    part_elems: dict[int, int] = {}
    part_nodes: dict[int, set[int]] = {}
    part_comps: dict[int, list[str]] = {}
    pid_order: list[int] = []
    elem_count = 0
    for a, b in _card_ranges(lines):
        kw = _keyword(lines[a])
        if kw[:1] == ["NODE"]:
            if node_head is None:
                node_head = _with_eol(lines[a], eol)
            for ln in lines[a + 1 : b]:
                if _is_comment(ln) or not ln.strip():
                    continue
                r = _node(ln.rstrip(b"\r\n").decode("latin-1"))
                if r is None or r[0] not in need_nodes:
                    continue
                if r[0] in seen_nodes:
                    raise PaicadError("GEOM_INPUT_INVALID", f"node {r[0]} is defined more than once in the cushion include")
                seen_nodes.add(r[0])
                node_lines.append(_with_eol(ln, eol))
        elif kw[:1] == ["TETRA4"]:
            pid = int(kw[1]) if len(kw) > 1 and kw[1].isdigit() else 0
            block: list[bytes] = []
            kept = 0
            for ln in lines[a + 1 : b]:
                if _is_comment(ln) or not ln.strip():
                    block.append(_with_eol(ln, eol))
                    continue
                vals = _ints(ln.rstrip(b"\r\n").decode("latin-1"), 5)
                comp = elem_comp.get(int(vals[0])) if vals else None
                if comp is None:
                    continue
                block.append(_with_eol(ln, eol))
                kept += 1
                part_nodes.setdefault(pid, set()).update(int(n) for n in vals[1:5])
                names = part_comps.setdefault(pid, [])
                if comp not in names:
                    names.append(comp)
            if kept:
                tet_out.append(_with_eol(lines[a], eol))
                tet_out.extend(block)
                elem_count += kept
                part_elems[pid] = part_elems.get(pid, 0) + kept
                if pid not in pid_order:
                    pid_order.append(pid)
    if elem_count != len(elem_comp):
        raise PaicadError("GEOM_INPUT_INVALID", f"cushion element ids are not unique in the include ({elem_count} lines, {len(elem_comp)} ids)")
    missing = need_nodes - seen_nodes
    if missing:
        raise PaicadError("GEOM_INPUT_INVALID", f"{len(missing)} nodes of cushion elements have no /NODE line in the include (first {min(missing)})")

    exclude = {inc.name.lower(), out_name.lower()}
    starter = find_starter(assem, exclude)
    begin = begin_card(starter, Path(out_name).stem)
    pids = sorted(pid_order)
    defs, wanted = find_definitions(source_files(inc, assem, exclude), pids)
    miss = [f"{k}/{i}" for k, i in wanted if (k, i) not in defs]
    warnings = [{"code": w["code"], "message": w["message"]} for w in comp_warn]
    if miss:
        warnings.append({"code": WARN_DEF_MISSING, "message": "cushion part definitions not found in the include or the assembly folder: " + ", ".join(miss), "names": miss})
    def_sources: list[str] = []
    for k in wanted:
        if k in defs and defs[k][0] not in def_sources:
            def_sources.append(defs[k][0])

    out = [b"#RADIOSS STARTER" + eol, *begin]
    for kind in DEF_KINDS:
        for k in wanted:
            if k[0] == kind and k in defs:
                out.extend(defs[k][1])
    out.append(node_head or b"/NODE" + eol)
    out.extend(node_lines)
    out.extend(tet_out)
    out.append(b"/END" + eol)
    parts = [
        {"part": pid, "components": part_comps[pid], "nodes": len(part_nodes[pid]), "elems": part_elems[pid], "part_def": ("PART", pid) in defs}
        for pid in pids
    ]
    return CushionRad(b"".join(out), len(node_lines), elem_count, parts, starter.name, def_sources, warnings)


def build_asm(src, patch: dict[int, tuple[float, float, float]] | None, out_name: str) -> CushionRad:
    """Assembly-match variant (asm-match.md section 5.5): same file layout as :func:`build` from the include
    tree collection - matched pid ``/PART`` + referenced ``/PROP`` / ``/MAT`` (first definition in tree order),
    the cushion node lines (tree order; with ``patch`` only the coordinate fields change, ids kept) and the
    ``/TETRA4/<pid>`` blocks of the matched PARTs (tree order, lines kept)."""
    idx = src.index
    pids = sorted(src.pids)
    body_of = {p: r["body"] for r in src.match.rows for p in r["pids"]}
    for p in pids:
        other = [b for b in idx.pid_blocks(p) if b.keyword != "TETRA4"]
        if other:
            raise PaicadError("GEOM_UNSUPPORTED_ELEMENT", f"component {body_of[p]}: non-TETRA4 elements in PART {p} (/{other[0].keyword})")
    mesh = src.mesh
    rows = idx.lookup(mesh.node_ids)
    node_at: dict[int, set[int]] = {}
    for fi, ln in zip(idx.node_file[rows].tolist(), idx.node_line[rows].tolist()):
        node_at.setdefault(int(fi), set()).add(int(ln))
    tet_at: dict[int, dict[int, int]] = {}
    want_elems = 0
    for b in idx.blocks:
        if b.pid in src.pids and b.keyword == "TETRA4":
            tet_at.setdefault(b.file, {})[b.line] = b.pid
            want_elems += len(b.ids)
    node_head: bytes | None = None
    out_eol: bytes | None = None
    node_lines: list[bytes] = []
    tet_out: list[bytes] = []
    part_elems: dict[int, int] = {}
    elem_count = 0
    for k, tf in enumerate(idx.files):
        nl = node_at.get(k, set())
        tl = tet_at.get(k, {})
        if not nl and not tl:
            continue
        eol = None
        last_node_kw: bytes | None = None
        cur: int | None = None
        with open(tf.path, "rb") as f:
            for ln, raw in enumerate(f):
                if eol is None and raw.endswith(b"\n"):
                    eol = b"\r\n" if raw.endswith(b"\r\n") else b"\n"
                e = eol or b"\n"
                if raw.startswith(b"/") or _is_include(raw):
                    cur = tl.get(ln) if raw.startswith(b"/") else None
                    if raw.startswith(b"/") and is_node_keyword(raw):
                        last_node_kw = raw
                    if cur is not None:
                        tet_out.append(_with_eol(raw, e))
                    continue
                if ln in nl:
                    if node_head is None:
                        node_head = _with_eol(last_node_kw or b"/NODE", e)
                        out_eol = e
                    node_lines.append(_with_eol(rewrite_node_line(raw, patch) if patch else raw, e))
                elif cur is not None:
                    tet_out.append(_with_eol(raw, e))
                    if not (_is_comment(raw.lstrip()) or not raw.strip()):
                        elem_count += 1
                        part_elems[cur] = part_elems.get(cur, 0) + 1
    if len(node_lines) != len(mesh.node_ids) or elem_count != want_elems:
        raise PaicadError("GEOM_INTERNAL", f"cushion collection mismatch ({len(node_lines)}/{len(mesh.node_ids)} nodes, {elem_count}/{want_elems} elements)")
    eol = out_eol or b"\n"
    starter = idx.root / idx.starter
    begin = begin_card(starter, Path(out_name).stem)
    defs, wanted = find_definitions([(tf.rel, tf.path) for tf in idx.files], pids)
    miss = [f"{kk}/{i}" for kk, i in wanted if (kk, i) not in defs]
    warnings: list[dict] = []
    if miss:
        warnings.append({"code": WARN_DEF_MISSING, "message": "cushion part definitions not found in the include tree: " + ", ".join(miss), "names": miss})
    def_sources: list[str] = []
    for kk in wanted:
        if kk in defs and defs[kk][0] not in def_sources:
            def_sources.append(defs[kk][0])
    out = [b"#RADIOSS STARTER" + eol, *begin]
    for kind in DEF_KINDS:
        for kk in wanted:
            if kk[0] == kind and kk in defs:
                out.extend(defs[kk][1])
    out.append(node_head or b"/NODE" + eol)
    out.extend(node_lines)
    out.extend(tet_out)
    out.append(b"/END" + eol)
    parts = []
    for p in pids:
        conn = np.concatenate([b.conn for b in idx.pid_blocks(p)])
        parts.append({"part": p, "components": [body_of[p]], "nodes": int(np.unique(conn).size), "elems": part_elems.get(p, 0), "part_def": ("PART", p) in defs})
    return CushionRad(b"".join(out), len(node_lines), elem_count, parts, idx.starter, def_sources, warnings)
