"""``paicad shell fixed-scan`` - fixed node set of the shell parts (shell-morph sections 4.3, 6.1).

Fixed kinds (bit order of ``kind_mask`` = ``KINDS`` order): ``/INTER/TYPE2`` secondary nodes and main
segments reached by a secondary node within Dsearch, ``/RBE2`` / ``/RBE3`` / ``/RBODY`` nodes, ``/BCS``
nodes and nodes shared with elements of other parts. Kinds left out of ``fixed.kinds`` are computed and
reported but not fixed (FIXED_KIND_SKIPPED). Unsupported or missing set references and unreadable
cards -> SHELL_FIXED_PARSE_FAILED (``fixed.required``) or FIXED_PARSE_SKIPPED.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from ..common import EXIT_OK, EXIT_TAG, OutDir, PaicadError, Reporter, dumps, rnd, vec
from ..meshgeom import TriangleSet
from ..update import read_json
from . import opts as shopts
from .assem import SHELL_KW, Assembly, SetError, read_assembly, resolve_grnod, resolve_surf, seg_triangles, shell_part
from .common import shell_envelope

SCAN_JSON = "shell_scan.json"
FIXED_NPZ = "fixed_nodes.npz"
KINDS = ("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN", "RBE2", "RBE3", "RBODY", "BCS", "SHARED")
OPTION_KIND = {"INTER_TYPE2_SECONDARY": "INTER_TYPE2", "INTER_TYPE2_MAIN": "INTER_TYPE2"}


@dataclass
class PartMesh:
    part_id: int
    title: str
    elem_ids: np.ndarray
    conn: np.ndarray  # int64[m,4] node ids (tri: n4 = n3)
    tri: np.ndarray
    node_ids: np.ndarray  # sorted unique
    files: list[str]


@dataclass
class FixedResult:
    parts: list[int]
    node_id: np.ndarray
    part: np.ndarray
    kind_mask: np.ndarray
    cluster: np.ndarray
    xyz: np.ndarray
    by_kind: dict[str, int]
    refs: list[dict]
    clusters: list[dict]
    warnings: list[dict] = field(default_factory=list)
    digest: str = ""

    def total(self) -> int:
        return int(len(self.node_id))


def part_mesh(asm: Assembly, pid: int) -> PartMesh:
    sp = shell_part(asm, pid)
    title = (asm.parts.get(pid) or {}).get("title", "")
    nodes = np.unique(sp["conn"]) if len(sp["conn"]) else np.zeros(0, dtype=np.int64)
    nodes = nodes[nodes > 0]
    return PartMesh(pid, title, sp["ids"], sp["conn"], sp["tri"], nodes, sp["files"])


def candidates(asm: Assembly) -> list[dict]:
    out = []
    pids = sorted({b.part for b in asm.blocks if b.keyword in SHELL_KW})
    for pid in pids:
        sp = shell_part(asm, pid)
        nodes = np.unique(sp["conn"])
        nodes = nodes[nodes > 0]
        info = asm.parts.get(pid) or {}
        prop = info.get("prop")
        pd = asm.props.get(prop) if prop is not None else None
        out.append(
            {
                "part_id": pid,
                "title": info.get("title", ""),
                "n_shell": int(sum(len(b.ids) for b in asm.part_blocks(pid) if b.keyword == "SHELL")),
                "n_sh3n": int(sum(len(b.ids) for b in asm.part_blocks(pid) if b.keyword == "SH3N")),
                "n_other": int(sp["other"]),
                "nodes": int(len(nodes)),
                "files": sp["files"],
                "prop": {"id": prop, "type": 1 if pd and pd["type"] in ("TYPE1", "SHELL") else None, "thickness": pd.get("thickness") if pd else None},
            }
        )
    return out


def _edges_of(conn: np.ndarray) -> np.ndarray:
    e = np.concatenate([conn[:, [0, 1]], conn[:, [1, 2]], conn[:, [2, 3]], conn[:, [3, 0]]])
    e = e[e[:, 0] != e[:, 1]]
    return np.unique(np.sort(e, axis=1), axis=0)


def compute_fixed(asm: Assembly, part_ids: list[int], o: dict) -> FixedResult:
    fo = o["fixed"]
    required = bool(fo["required"])
    active = set(fo["kinds"])
    warnings: list[dict] = []
    issues: list[str] = []
    meshes = []
    for pid in part_ids:
        if not asm.part_blocks(pid):
            raise PaicadError("SHELL_PART_NOT_FOUND", f"shell part {pid} not found in the assembly folder")
        pm = part_mesh(asm, pid)
        other = [b for b in asm.part_blocks(pid) if b.keyword not in SHELL_KW]
        if other:
            raise PaicadError("SHELL_UNSUPPORTED_ELEMENT", f"part {pid}: {sum(len(b.ids) for b in other)} non-shell elements (/{other[0].keyword})")
        if len(pm.elem_ids) == 0:
            raise PaicadError("SHELL_PART_NOT_FOUND", f"shell part {pid} has no /SHELL or /SH3N element")
        meshes.append(pm)
    N_all = np.unique(np.concatenate([m.node_ids for m in meshes]))
    Nset = set(int(x) for x in N_all)
    sets_kind: dict[str, set[int]] = {k: set() for k in KINDS}
    refs: list[dict] = []
    xyz_of = asm.xyz

    def coords(ids):
        r = asm.index(list(ids))
        if np.any(r < 0):
            raise SetError(f"{int(np.sum(r < 0))} referenced nodes have no /NODE definition")
        return xyz_of[r]

    for fd in asm.fixdefs:
        label = f"/{fd.kind.replace('_', '/')}/{fd.id} ({fd.rel})"
        try:
            if fd.error:
                raise SetError(fd.error)
            if fd.kind == "INTER_TYPE2":
                sec = resolve_grnod(asm, fd.grnods[0]) if fd.grnods and fd.grnods[0] else set()
                segs = resolve_surf(asm, int(fd.surf)) if fd.surf else []
                hit_s = sec & Nset
                own = [i for i, s in enumerate(segs) if s and all(x in Nset for x in s)]
                hit_m: set[int] = set()
                ds = float(fd.dsearch)
                if own and sec:
                    tris, owner = seg_triangles(segs)
                    P = coords(sorted(sec))
                    T = coords(tris.ravel()).reshape(-1, 3, 3)
                    ts = TriangleSet(T)
                    if ds <= 0:
                        ds = o["tie"].get("default_dsearch_mm") or 0.0
                    if ds <= 0:
                        d0, _ = ts.distance(P, 1e30)
                        ds = 1.5 * float(d0.max()) if d0.size else 0.0
                    d, ti = ts.distance(P, ds)
                    owned = set(own)
                    for k in np.flatnonzero(ti >= 0):
                        si = int(owner[ti[k]])
                        if si in owned:
                            hit_m.update(segs[si])
                    hit_m &= Nset
                sets_kind["INTER_TYPE2_SECONDARY"] |= hit_s
                sets_kind["INTER_TYPE2_MAIN"] |= hit_m
                if hit_s:
                    refs.append({"kind": "INTER_TYPE2_SECONDARY", "id": fd.id, "title": fd.title, "file": fd.rel, "nodes": len(hit_s), "dsearch_mm": rnd(fd.dsearch)})
                if hit_m:
                    refs.append({"kind": "INTER_TYPE2_MAIN", "id": fd.id, "title": fd.title, "file": fd.rel, "nodes": len(hit_m), "dsearch_mm": rnd(ds)})
            else:
                nodes = set(int(x) for x in fd.nodes if x)
                for g in fd.grnods:
                    nodes |= resolve_grnod(asm, int(g))
                hit = nodes & Nset
                sets_kind[fd.kind] |= hit
                if hit:
                    ref = {"kind": fd.kind, "id": fd.id, "title": fd.title, "file": fd.rel, "nodes": len(hit)}
                    if fd.kind in ("RBE2", "RBODY") and fd.nodes:
                        ref["independent"] = int(fd.nodes[0])
                    if fd.kind == "RBE3" and fd.nodes:
                        ref["reference"] = int(fd.nodes[0])
                    refs.append(ref)
        except SetError as ex:
            issues.append(f"{label}: {ex}")
    # shared nodes: referenced by elements of other parts
    target = set(part_ids)
    shared_with: dict[int, set[int]] = {}
    for b in asm.blocks:
        if b.part in target:
            continue
        ns = set(int(x) for x in np.unique(b.conn) if x > 0) & Nset
        if ns:
            sets_kind["SHARED"] |= ns
            shared_with.setdefault(b.part, set()).update(ns)
    if sets_kind["SHARED"]:
        for pm in meshes:
            nn = sets_kind["SHARED"] & set(int(x) for x in pm.node_ids)
            if nn:
                warnings.append({"code": "FIXED_SHARED_NODES", "part_id": pm.part_id, "nodes": len(nn), "with_parts": sorted(p for p, s in shared_with.items() if s & nn)})
    if asm.errors:
        issues += asm.errors
    if issues:
        if required:
            raise PaicadError("SHELL_FIXED_PARSE_FAILED", "cannot evaluate fixing definitions: " + "; ".join(issues[:5]))
        warnings.append({"code": "FIXED_PARSE_SKIPPED", "message": "; ".join(issues[:10]), "count": len(issues)})
    for k in KINDS:
        if OPTION_KIND.get(k, k) not in active and sets_kind[k]:
            warnings.append({"code": "FIXED_KIND_SKIPPED", "kind": k, "nodes": len(sets_kind[k])})
    fixed_ids = sorted(set().union(*(sets_kind[k] for k in KINDS if OPTION_KIND.get(k, k) in active)))
    fid = np.array(fixed_ids, dtype=np.int64)
    mask = np.zeros(len(fid), dtype=np.int16)
    pos = {n: i for i, n in enumerate(fixed_ids)}
    for bit, k in enumerate(KINDS):
        for n in sets_kind[k]:
            i = pos.get(n)
            if i is not None:
                mask[i] |= 1 << bit
    part_of = np.zeros(len(fid), dtype=np.int32)
    for pm in meshes:
        inm = np.isin(fid, pm.node_ids)
        part_of[inm & (part_of == 0)] = pm.part_id
    # clusters: connected components of F in the mesh adjacency
    cluster = np.zeros(len(fid), dtype=np.int32)
    clusters: list[dict] = []
    if len(fid):
        edges = np.concatenate([_edges_of(pm.conn) for pm in meshes])
        a, bb = np.searchsorted(fid, edges[:, 0]), np.searchsorted(fid, edges[:, 1])
        a = np.clip(a, 0, len(fid) - 1)
        bb = np.clip(bb, 0, len(fid) - 1)
        keep = (fid[a] == edges[:, 0]) & (fid[bb] == edges[:, 1])
        g = coo_matrix((np.ones(int(keep.sum())), (a[keep], bb[keep])), shape=(len(fid), len(fid)))
        ncomp, lab = connected_components(g, directed=False)
        # deterministic numbering: by smallest node id of the component
        first = {}
        for i, l in enumerate(lab):
            first.setdefault(int(l), i)
        order = sorted(first, key=lambda l: first[l])
        ren = {l: k + 1 for k, l in enumerate(order)}
        cluster = np.array([ren[int(l)] for l in lab], dtype=np.int32)
        X = xyz_of[asm.index(fid)]
        for k in range(1, ncomp + 1):
            sel = cluster == k
            c = X[sel].mean(axis=0)
            kinds = [KINDS[bit] for bit in range(len(KINDS)) if np.any(mask[sel] & (1 << bit))]
            clusters.append({"id": k, "nodes": int(sel.sum()), "center": vec(c, 3), "radius_mm": rnd(float(np.linalg.norm(X[sel] - c, axis=1).max()), 3), "kinds": kinds})
    else:
        X = np.zeros((0, 3))
    digest = "sha256:" + hashlib.sha256(",".join(str(x) for x in fixed_ids).encode()).hexdigest()
    by_kind = {k: len(sets_kind[k]) for k in KINDS}
    refs.sort(key=lambda r: (KINDS.index(r["kind"]), r["id"]))
    return FixedResult(list(part_ids), fid, part_of, mask, cluster, X, by_kind, refs, clusters, warnings, digest)


def save_npz(path: Path, fx: FixedResult) -> None:
    with open(path, "wb") as f:
        np.savez(f, node_id=fx.node_id, part=fx.part, kind_mask=fx.kind_mask, cluster=fx.cluster, xyz=fx.xyz)


@dataclass
class FixedData:
    doc: dict
    node_id: np.ndarray
    part: np.ndarray
    kind_mask: np.ndarray
    cluster: np.ndarray
    xyz: np.ndarray

    @property
    def digest(self) -> str:
        return (self.doc.get("fixed") or {}).get("digest", "")


def load_fixed(fixed_dir: str | Path) -> FixedData:
    d = Path(fixed_dir)
    doc = read_json(d / SCAN_JSON, SCAN_JSON)
    if doc.get("status") != "OK" or doc.get("kind") != "shell" or not isinstance(doc.get("fixed"), dict):
        raise PaicadError("GEOM_INPUT_INVALID", "shell_scan.json is not an OK shell scan with a fixed set")
    name = (doc.get("files") or {}).get("nodes", FIXED_NPZ)
    try:
        z = np.load(d / name)
        arr = {k: np.asarray(z[k]) for k in ("node_id", "part", "kind_mask", "cluster", "xyz")}
    except (OSError, KeyError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read fixed nodes file: {ex.__class__.__name__}") from None
    return FixedData(doc, arr["node_id"].astype(np.int64), arr["part"].astype(np.int32), arr["kind_mask"].astype(np.int16), arr["cluster"].astype(np.int32), arr["xyz"].astype(float))


def parts_from_args(parts: str | None, features: str | None) -> list[int] | None:
    if parts and features:
        raise PaicadError("GEOM_INPUT_INVALID", "--parts and --features are mutually exclusive")
    if parts:
        try:
            out = [int(x) for x in parts.split(",") if x.strip()]
        except ValueError:
            raise PaicadError("GEOM_INPUT_INVALID", f"--parts must be comma-separated part ids: {parts!r}") from None
        if not out:
            raise PaicadError("GEOM_INPUT_INVALID", "--parts is empty")
        return sorted(set(out))
    if features:
        doc = read_json(features, "features file")
        if doc.get("kind") != "shell" or not isinstance(doc.get("parts"), list):
            raise PaicadError("GEOM_INPUT_INVALID", "--features must be a shell_features.json (kind shell)")
        ids = [p.get("part_id") for p in doc["parts"]]
        if any(not isinstance(i, int) for i in ids):
            raise PaicadError("GEOM_INPUT_INVALID", "shell_features.json parts without part_id (extract was run without --assem-dir)")
        return sorted(set(ids))
    return None


def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    o = shopts.load(args.options)
    pids = parts_from_args(args.parts, args.features)
    out = OutDir(args.out_dir, [SCAN_JSON, FIXED_NPZ])
    out.prepare()
    rep.progress(5, "reading the assembly folder")
    asm = read_assembly(args.assem_dir)
    cands = candidates(asm)
    if pids is None:
        doc = shell_envelope(status="OK", code=None, message=None, candidates=cands, parts=[], fixed=None, files={}, warnings=[], elapsed_s=rnd(time.monotonic() - t0, 3))
        out.write_text(SCAN_JSON, dumps(doc))
        out.commit([SCAN_JSON])
        rep.progress(100, f"fixed-scan (list mode): {len(cands)} shell parts")
        rep.result("OK", None, SCAN_JSON)
        return EXIT_OK
    rep.progress(30, f"fixed node sets of parts {', '.join(map(str, pids))}")
    try:
        fx = compute_fixed(asm, pids, o)
    except PaicadError as e:
        if e.code in ("SHELL_FIXED_PARSE_FAILED", "SHELL_UNSUPPORTED_ELEMENT"):
            doc = shell_envelope(status="FAIL", code=e.code, category="PREP", message=e.message, candidates=cands, parts=pids, fixed=None, files={}, warnings=[])
            out.write_text(SCAN_JSON, dumps(doc))
            out.commit([SCAN_JSON])
            rep.result("FAIL", e.code, SCAN_JSON)
            return EXIT_TAG
        raise
    save_npz(out.tmp_path(FIXED_NPZ), fx)
    fixed = {
        "digest": fx.digest,
        "total": fx.total(),
        "by_kind": fx.by_kind,
        "kinds": list(o["fixed"]["kinds"]),
        "refs": fx.refs,
        "clusters": fx.clusters,
    }
    doc = shell_envelope(
        status="OK", code=None, message=None, candidates=cands, parts=pids, fixed=fixed, files={"nodes": FIXED_NPZ},
        assem_digest=asm.digest(), warnings=fx.warnings, elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(SCAN_JSON, dumps(doc))
    out.commit([FIXED_NPZ, SCAN_JSON])
    rep.progress(100, f"fixed-scan done: {fx.total()} fixed nodes in {len(fx.clusters)} clusters")
    rep.result("OK", None, SCAN_JSON)
    return EXIT_OK
