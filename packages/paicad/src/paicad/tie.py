"""Tie (``/INTER/TYPE2``) projection check (contract section 6.5 (e)), numpy/scipy only.

Supported references: ``/GRNOD/NODE`` (secondary nodes) and ``/SURF/SEG`` (main segments).
Other set types make the interface "unparsed" (strict: FAIL when ``tie.required``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .mesh.radioss import read_text
from .meshgeom import TriangleSet


@dataclass
class TieDef:
    id: int
    grnod: int | None
    surf: int | None
    dsearch: float
    file: str


@dataclass
class AssemblySets:
    ties: list[TieDef] = field(default_factory=list)
    grnod_node: dict[int, list[int]] = field(default_factory=dict)
    surf_seg: dict[int, list[list[int]]] = field(default_factory=dict)
    other_sets: set[tuple[str, int]] = field(default_factory=set)  # ("GRNOD"|"SURF", id) of unsupported types
    errors: list[str] = field(default_factory=list)


def _data_lines(lines: list[str], start: int) -> list[str]:
    out = []
    for ln in lines[start:]:
        if ln.startswith("/"):
            break
        if not ln.strip() or ln.startswith(("#", "$")):
            continue
        out.append(ln)
    return out


def _ints_fixed(line: str) -> list[int]:
    vals = []
    for k in range(0, len(line.rstrip()), 10):
        s = line[k : k + 10].strip()
        if not s:
            continue
        try:
            vals.append(int(s))
        except ValueError:
            return [int(t) for t in line.split() if t.lstrip("-").isdigit()]
    return vals


def parse_sets(files: list[Path]) -> AssemblySets:
    out = AssemblySets()
    for f in files:
        lines = read_text(f).splitlines()
        for i, ln in enumerate(lines):
            if not ln.startswith("/"):
                continue
            parts = ln.strip().split("/")
            kw = [p.upper() for p in parts[1:]]
            try:
                if kw[:2] == ["INTER", "TYPE2"]:
                    iid = int(parts[3])
                    data = _data_lines(lines, i + 1)
                    if len(data) < 2:
                        out.errors.append(f"/INTER/TYPE2/{iid}: incomplete card")
                        continue
                    toks = data[1].split()
                    grnod, surf = int(toks[0]), int(toks[1])
                    ds = 0.0
                    if len(toks) >= 8:
                        ds = float(toks[7])
                    elif len(data) > 2:
                        try:
                            ds = float(data[2].split()[0])
                        except (ValueError, IndexError):
                            ds = 0.0
                    out.ties.append(TieDef(iid, grnod or None, surf or None, ds, f.name))
                elif kw[:1] == ["GRNOD"] and len(kw) >= 3:
                    gid = int(parts[3])
                    if kw[1] == "NODE":
                        ids = []
                        for d in _data_lines(lines, i + 1)[1:]:
                            ids += _ints_fixed(d)
                        out.grnod_node[gid] = ids
                    else:
                        out.other_sets.add(("GRNOD", gid))
                elif kw[:1] == ["SURF"] and len(kw) >= 3:
                    sid = int(parts[3])
                    if kw[1] == "SEG":
                        segs = []
                        for d in _data_lines(lines, i + 1)[1:]:
                            v = _ints_fixed(d)
                            if len(v) >= 4:
                                segs.append(v[1:5])
                        out.surf_seg[sid] = segs
                    else:
                        out.other_sets.add(("SURF", sid))
            except (ValueError, IndexError):
                out.errors.append(f"cannot parse {ln.strip()[:40]!r} in {f.name}")
    return out


def _seg_tris(segs: list[list[int]]) -> np.ndarray:
    tris = []
    for s in segs:
        n = [x for x in s if x > 0]
        if len(n) == 3 or (len(n) == 4 and n[2] == n[3]):
            tris.append(n[:3])
        elif len(n) == 4:
            tris.append([n[0], n[1], n[2]])
            tris.append([n[0], n[2], n[3]])
    return np.array(tris, dtype=np.int64).reshape(-1, 3)


def check_ties(sets: AssemblySets, cushion_nodes: set[int], coords_new: dict[int, np.ndarray], coords_base: dict[int, np.ndarray], opts: dict) -> tuple[dict, str | None, list[dict]]:
    """Returns (tie report, failure message or None, warnings)."""
    t = opts["tie"]
    required = bool(t.get("required", True))
    warnings: list[dict] = []
    items = []
    unparsed = []
    applicable = 0
    for td in sets.ties:
        sec = sets.grnod_node.get(td.grnod) if td.grnod is not None else None
        segs = sets.surf_seg.get(td.surf) if td.surf is not None else None
        if sec is None or segs is None:
            unknown = (td.grnod is not None and ("GRNOD", td.grnod) in sets.other_sets) or (td.surf is not None and ("SURF", td.surf) in sets.other_sets)
            unparsed.append(f"/INTER/TYPE2/{td.id}: {'unsupported set type' if unknown else 'set not found'}")
            continue
        main_nodes = {n for s in segs for n in s if n > 0}
        if not (set(sec) & cushion_nodes or main_nodes & cushion_nodes):
            continue
        applicable += 1
        tris = _seg_tris(segs)
        missing = [n for n in set(sec) | main_nodes if n not in coords_new]
        if missing:
            unparsed.append(f"/INTER/TYPE2/{td.id}: {len(missing)} nodes without coordinates")
            continue

        def dist(coords):
            P = np.array([coords[n] for n in sec])
            T = np.array([[coords[n] for n in tri] for tri in tris])
            d, _ = TriangleSet(T).distance(P, 1e30)
            return d

        d1 = dist(coords_new)
        ds = td.dsearch if td.dsearch > 0 else t.get("default_dsearch_mm")
        if not ds:
            d0 = dist(coords_base)
            ds = 1.5 * float(d0.max()) if d0.size else 0.0
        failed = int((d1 > ds).sum())
        items.append({"id": td.id, "dsearch_mm": round(float(ds), 6), "max_gap_mm": round(float(d1.max()) if d1.size else 0.0, 6), "failed_nodes": failed})
    msg = None
    if unparsed or sets.errors:
        reason = "; ".join((unparsed + sets.errors)[:5])
        if required:
            rep = {"status": "FAIL", "interfaces": items, "parse_errors": unparsed + sets.errors}
            return rep, f"tie: cannot evaluate ties ({reason})", warnings
        warnings.append({"code": "TIE_PARSE_SKIPPED", "message": reason})
        return {"status": "NOT_EVALUATED", "interfaces": items, "parse_errors": unparsed + sets.errors}, None, warnings
    if applicable == 0:
        return {"status": "SKIPPED", "interfaces": [], "reason": "no_tie_on_component"}, None, warnings
    bad = [it for it in items if it["failed_nodes"]]
    if bad:
        msg = "tie: " + ", ".join(f"interface {it['id']} has {it['failed_nodes']} nodes beyond Dsearch" for it in bad[:5])
    return {"status": "FAIL" if bad else "PASS", "interfaces": items}, msg, warnings
