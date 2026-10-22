"""``paicad morph`` - move baseline node coordinates onto the sample B-rep (contract sections 4.7, 6.4).

Boundary targets: vertex nodes -> sample vertex, edge nodes -> same normalized arc length on the
sample edge, face nodes -> same normalized (u,v) on the sample face. Faces whose evaluation leaves
the trimmed face, whose inner wires moved, or whose parametrization was replaced by the update use
the fallback: harmonic (cotangent) interpolation of the face-boundary displacements on the skin
triangles, projected onto the sample face. Interior (and unmatched) nodes: one linear-elastic solve
per connected component with element stiffness ~ 1 / element volume and the boundary displacements
as Dirichlet conditions. Only the ``/NODE`` coordinate fields of the baseline include change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import cg, spsolve

from . import options
from .common import CODE_CATEGORY, EXIT_CHECK, EXIT_OK, OutDir, PaicadError, Reporter, dumps, envelope, rnd
from .kernel import BodyGeom, CadInputError, load_brep
from .mesh.radioss import RadMesh, parse_text
from .meshsrc import NODE_XYZ, mesh_args, open_source, save_xyz
from .meshdata import KIND_EDGE, KIND_FACE, KIND_UNMATCHED, KIND_VERTEX, Comp, components_from_tag, load_tag
from .update import FACE_MAP_JSON, SAMPLE_BREP, UPDATE_JSON, load_features, read_json

MORPH_JSON = "morph.json"
MORPHED_INC = "morphed.inc"
NOOP_EPS = 1.0e-6  # mm: displacements at or below this are treated as zero (keeps unchanged lines byte-identical)
SPSOLVE_MAX_DOF = 300_000


class MorphFailed(PaicadError):
    def __init__(self, message: str):
        super().__init__("GEOM_MORPH_FAILED", message)


@dataclass
class SampleSet:
    bodies: dict[str, BodyGeom]  # by body name
    face_map: dict  # body -> {"F": {...}, "E": {...}, "V": {...}}
    uv_fallback: dict[str, set[int]] = field(default_factory=dict)  # nominal face ids with an invalid (u,v) mapping

    def fid(self, body: str, kind: str, nominal: int) -> int:
        try:
            return int(self.face_map[body][kind][str(int(nominal))])
        except KeyError:
            raise PaicadError("GEOM_INPUT_INVALID", f"face_map has no {kind}{nominal} for {body}") from None


def load_sample(update_dir: str | Path, doc: dict) -> SampleSet:
    d = Path(update_dir)
    u = read_json(d / UPDATE_JSON, "update.json")
    if u.get("status") != "OK":
        raise PaicadError("GEOM_INPUT_INVALID", "update.json status is not OK")
    names = [b["body"] for b in doc["bodies"]]
    try:
        bodies = load_brep(d / SAMPLE_BREP, names)
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None
    fm = read_json(d / FACE_MAP_JSON, "face_map.json")
    uvf = {b: {int(x) for x in (fm.get(b) or {}).get("uv_fallback", [])} for b in names}
    return SampleSet({n: b for n, b in zip(names, bodies)}, fm, uvf)


# ------------------------------------------------------------------ boundary targets
@dataclass
class Targets:
    pos: dict[int, np.ndarray]  # global node row -> target xyz (boundary nodes only)
    fallback_faces: dict[str, list[int]]  # body -> nominal face ids solved by the harmonic fallback


def _cot_laplacian(xyz: np.ndarray, tris: np.ndarray, n: int) -> sp.csr_matrix:
    """Symmetric cotangent Laplacian (weights clamped positive) on the given triangles."""
    rows, cols, vals = [], [], []
    for a, b, c in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        pa, pb, pc = xyz[tris[:, a]], xyz[tris[:, b]], xyz[tris[:, c]]
        u, v = pa - pc, pb - pc
        cr = np.linalg.norm(np.cross(u, v), axis=1)
        cot = np.einsum("ij,ij->i", u, v) / np.where(cr > 1e-300, cr, 1e-300)
        w = 0.5 * cot
        rows.append(tris[:, a])
        cols.append(tris[:, b])
        vals.append(w)
    r = np.concatenate(rows)
    c = np.concatenate(cols)
    w = np.concatenate(vals)
    pos = w[w > 0]
    floor = 1e-3 * (float(pos.mean()) if pos.size else 1.0)
    w = np.maximum(w, floor)
    W = sp.coo_matrix((np.concatenate([w, w]), (np.concatenate([r, c]), np.concatenate([c, r]))), shape=(n, n)).tocsr()
    d = np.asarray(W.sum(axis=1)).ravel()
    return (sp.diags(d) - W).tocsr()


def boundary_targets(comps: list[Comp], xyz: np.ndarray, sample: SampleSet) -> Targets:
    pos: dict[int, np.ndarray] = {}
    fallback: dict[str, list[int]] = {}
    for comp in comps:
        body = sample.bodies[comp.body]
        topo = body.topology()
        own = comp.owner == comp.index
        k = comp.kind
        # vertices
        for i in np.flatnonzero(own & (k == KIND_VERTEX)):
            v = sample.fid(comp.body, "V", comp.entity[i])
            pos[int(comp.gidx[i])] = np.asarray(topo.vertices[v - 1], dtype=float)
        # edges
        sel = np.flatnonzero(own & (k == KIND_EDGE))
        for e in np.unique(comp.entity[sel]):
            idx = sel[comp.entity[sel] == e]
            pts = body.eval_edge(sample.fid(comp.body, "E", e), comp.uv[idx, 0])
            for j, i in enumerate(idx):
                pos[int(comp.gidx[i])] = pts[j]
        # faces: (u,v) mapping unless the fallback rule applies
        sel = np.flatnonzero(own & (k == KIND_FACE))
        harmonic: list[int] = []
        for f in np.unique(comp.entity[sel]):
            idx = sel[comp.entity[sel] == f]
            sf = sample.fid(comp.body, "F", f)
            use_fallback = int(f) in sample.uv_fallback.get(comp.body, set())
            if not use_fallback:
                inside = body.classify_face_uv(sf, comp.uv[idx])
                use_fallback = not bool(inside.all())
            if use_fallback:
                harmonic.append(int(f))
                continue
            pts, _ = body.eval_face(sf, comp.uv[idx])
            for j, i in enumerate(idx):
                pos[int(comp.gidx[i])] = pts[j]
        if harmonic:
            fallback[comp.body] = sorted(harmonic)
            _harmonic(comp, body, topo, harmonic, xyz, pos, sample)
    return Targets(pos, fallback)


def _harmonic(comp: Comp, body: BodyGeom, topo, faces: list[int], xyz: np.ndarray, pos: dict, sample: SampleSet) -> None:
    """Section 6.4 fallback for the given nominal faces of one component."""
    n = len(comp.node_ids)
    unknown = np.zeros(n, dtype=bool)
    on_face = np.full(n, -1, dtype=np.int64)
    for f in faces:
        m = (comp.kind == KIND_FACE) & (comp.entity == f) & (comp.owner == comp.index)
        unknown |= m
        on_face[m] = f
    unknown |= comp.kind == KIND_UNMATCHED
    tris = comp.skin[unknown[comp.skin].any(axis=1)]
    used = np.unique(tris)
    base = xyz[comp.gidx]
    known = np.zeros(n, dtype=bool)
    known[used] = ~unknown[used]
    disp = np.zeros((n, 3))
    for i in np.flatnonzero(known):
        g = int(comp.gidx[i])
        if g not in pos:
            raise MorphFailed(f"{comp.part}: harmonic fallback needs the displacement of node {int(comp.node_ids[i])} (unclassified neighbour)")
        disp[i] = pos[g] - base[i]
    L = _cot_laplacian(base, tris, n)
    u_idx = np.flatnonzero(unknown & np.isin(np.arange(n), used))
    k_idx = np.flatnonzero(known)
    if u_idx.size == 0:
        return
    A = L[u_idx][:, u_idx].tocsc()
    B = L[u_idx][:, k_idx]
    try:
        sol = spsolve(A, -(B @ disp[k_idx]))
    except Exception as ex:  # singular patch
        raise MorphFailed(f"{comp.part}: harmonic fallback failed ({ex.__class__.__name__})") from None
    sol = np.asarray(sol).reshape(-1, 3)
    if not np.all(np.isfinite(sol)):
        raise MorphFailed(f"{comp.part}: harmonic fallback produced non-finite values")
    for f in faces:
        sel = [j for j, i in enumerate(u_idx) if on_face[i] == f]
        if not sel:
            continue
        rows = u_idx[sel]
        p = base[rows] + sol[sel]
        sf = sample.fid(comp.body, "F", f)
        d, _, inside, foot = body.project_to_face(sf, p)
        if not np.all(np.isfinite(foot)):
            raise MorphFailed(f"{comp.part}: projection on face F{f} failed")
        out = np.flatnonzero(~inside)
        if out.size:
            fd = topo.face(sf)
            best_d = np.full(out.size, np.inf)
            best_p = foot[out].copy()
            for e in fd.edges:
                de, _, fe = body.project_to_edge(e, p[out])
                better = de < best_d
                best_d[better] = de[better]
                best_p[better] = fe[better]
            if not np.all(np.isfinite(best_d)):
                raise MorphFailed(f"{comp.part}: projection on the boundary of face F{f} failed")
            foot[out] = best_p
        for j, i in enumerate(rows):
            pos[int(comp.gidx[i])] = foot[j]


# ------------------------------------------------------------------ pseudo-elastic interior solve
def _elastic_stiffness(xyz: np.ndarray, tets: np.ndarray, poisson: float) -> sp.csr_matrix:
    m = len(tets)
    X = xyz[tets]  # m,4,3
    M = np.concatenate([np.ones((m, 4, 1)), X], axis=2)  # m,4,4
    det = np.linalg.det(M)
    vol = np.abs(det) / 6.0
    if np.any(vol <= 0):
        raise MorphFailed("baseline has degenerate (zero-volume) tetrahedra")
    inv = np.linalg.inv(M)  # m,4,4 ; columns -> shape functions
    G = inv[:, 1:4, :]  # m,3,4 gradients dN_j/dx_i
    Bm = np.zeros((m, 6, 12))
    for j in range(4):
        gx, gy, gz = G[:, 0, j], G[:, 1, j], G[:, 2, j]
        c = 3 * j
        Bm[:, 0, c] = gx
        Bm[:, 1, c + 1] = gy
        Bm[:, 2, c + 2] = gz
        Bm[:, 3, c] = gy
        Bm[:, 3, c + 1] = gx
        Bm[:, 4, c + 1] = gz
        Bm[:, 4, c + 2] = gy
        Bm[:, 5, c] = gz
        Bm[:, 5, c + 2] = gx
    nu = float(poisson)
    lam = nu / ((1 + nu) * (1 - 2 * nu))
    mu = 1.0 / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[np.arange(3), np.arange(3)] += 2 * mu
    D[3:, 3:] = np.eye(3) * mu
    E = vol.mean() / vol  # small elements stiffer (section 6.4 step 2)
    Ke = np.einsum("mki,kl,mlj->mij", Bm, D, Bm) * (vol * E)[:, None, None]
    dofs = (3 * tets[:, :, None] + np.arange(3)[None, None, :]).reshape(m, 12)
    rows = np.repeat(dofs, 12, axis=1).ravel()
    cols = np.tile(dofs, (1, 12)).ravel()
    n = 3 * int(xyz.shape[0])
    return sp.coo_matrix((Ke.ravel(), (rows, cols)), shape=(n, n)).tocsr()


def solve_interior(xyz: np.ndarray, tets: np.ndarray, fixed: np.ndarray, u_fixed: np.ndarray, opts: dict) -> tuple[np.ndarray, dict]:
    """Displacements of all nodes; ``fixed`` = bool[n] Dirichlet nodes with ``u_fixed`` [n,3]."""
    n = len(xyz)
    u = np.zeros((n, 3))
    u[fixed] = u_fixed[fixed]
    free = ~fixed
    if not free.any() or not np.any(u_fixed[fixed]):
        return u, {"method": "none", "iterations": 0, "rel_residual": 0.0}
    mo = opts["morph"]
    K = _elastic_stiffness(xyz, tets, mo["poisson"])
    fd = np.repeat(free, 3)
    A = K[fd][:, fd].tocsr()
    b = -(K[fd][:, ~fd] @ u[fixed].ravel())
    diag = A.diagonal()
    if np.any(diag <= 0):
        raise MorphFailed("stiffness matrix has a non-positive diagonal (free node not attached to any element)")
    Minv = sp.diags(1.0 / diag)
    it = [0]

    def cb(_):
        it[0] += 1

    x, info = cg(A, b, rtol=float(mo["solver_rtol"]), maxiter=int(mo["solver_maxiter"]), M=Minv, callback=cb)
    method = "cg"
    bn = float(np.linalg.norm(b)) or 1.0
    res = float(np.linalg.norm(b - A @ x)) / bn
    if info != 0 or not np.all(np.isfinite(x)):
        if A.shape[0] > SPSOLVE_MAX_DOF:
            raise MorphFailed(f"interior solve did not converge (cg info {info}, rel. residual {res:.3g})")
        x = spsolve(A.tocsc(), b)
        method = "spsolve"
        res = float(np.linalg.norm(b - A @ x)) / bn
        if not np.all(np.isfinite(x)):
            raise MorphFailed("interior solve failed (spsolve)")
    u[free] = np.asarray(x).reshape(-1, 3)
    return u, {"method": method, "iterations": it[0], "rel_residual": float(f"{res:.3e}")}


# ------------------------------------------------------------------ core
@dataclass
class MorphResult:
    xyz: np.ndarray  # new coordinates of every baseline node (RadMesh order)
    moved: dict[int, tuple[float, float, float]]  # node id -> new xyz (only moved nodes)
    parts: list[dict]
    fallback_faces: dict[str, list[int]]
    max_disp: float


def _groups(comps: list[Comp]) -> list[list[int]]:
    """Connected components over parts (parts sharing nodes are solved together)."""
    parent = list(range(len(comps)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            if np.intersect1d(comps[i].node_ids, comps[j].node_ids, assume_unique=True).size:
                parent[find(j)] = find(i)
    out: dict[int, list[int]] = {}
    for i in range(len(comps)):
        out.setdefault(find(i), []).append(i)
    return list(out.values())


def morph_core(mesh: RadMesh, comps: list[Comp], sample: SampleSet, opts: dict) -> MorphResult:
    xyz = mesh.xyz
    tg = boundary_targets(comps, xyz, sample)
    new_xyz = xyz.copy()
    parts_out: list[dict] = [None] * len(comps)  # type: ignore[list-item]
    for grp in _groups(comps):
        g_nodes = np.unique(np.concatenate([comps[i].gidx for i in grp]))
        loc = {int(g): k for k, g in enumerate(g_nodes)}
        tets = np.concatenate([np.vectorize(loc.__getitem__, otypes=[np.int64])(comps[i].gidx[comps[i].tets]) for i in grp])
        n = len(g_nodes)
        fixed = np.zeros(n, dtype=bool)
        u_fixed = np.zeros((n, 3))
        for k, g in enumerate(g_nodes):
            t = tg.pos.get(int(g))
            if t is not None:
                fixed[k] = True
                d = t - xyz[g]
                if float(np.linalg.norm(d)) > NOOP_EPS:
                    u_fixed[k] = d
        u, info = solve_interior(xyz[g_nodes], tets, fixed, u_fixed, opts)
        mag = np.linalg.norm(u, axis=1)
        u[mag <= NOOP_EPS] = 0.0
        new_xyz[g_nodes] = xyz[g_nodes] + u
        for i in grp:
            c = comps[i]
            cm = np.array([loc[int(g)] for g in c.gidx])
            mm = mag[cm]
            parts_out[i] = {
                "part": c.part,
                "moved_nodes": int((mm > NOOP_EPS).sum()),
                "max_disp_mm": rnd(float(mm.max()) if mm.size else 0.0),
                "solver": info,
            }
    moved = {}
    disp = np.linalg.norm(new_xyz - xyz, axis=1)
    for r in np.flatnonzero(disp > 0):
        moved[int(mesh.node_ids[r])] = tuple(float(x) for x in new_xyz[r])
    return MorphResult(new_xyz, moved, parts_out, tg.fallback_faces, float(disp.max()) if disp.size else 0.0)


def write_morphed(base_bytes: bytes, base_mesh: RadMesh, moved: dict, solver: str | None = None) -> bytes:
    """Section 6.4 step 4 through the solver writer registry (section 18.3, default radioss)."""
    from .writers import get_writer

    return get_writer(solver).write(base_bytes, base_mesh, moved)


def read_baseline(path: str | Path) -> tuple[bytes, RadMesh]:
    p = Path(path)
    if not p.is_file():
        raise PaicadError("GEOM_INPUT_INVALID", f"baseline include not found: {p.name}")
    data = p.read_bytes()
    return data, parse_text(data.decode("latin-1"))


# ------------------------------------------------------------------ reports (also written by ``paicad view preview``)
def fail_report(e: PaicadError, t0: float) -> dict:
    return envelope(status="FAIL", code=e.code, category=CODE_CATEGORY[e.code], message=e.message, max_disp_mm=None, parts=[], elapsed_s=rnd(time.monotonic() - t0, 3))


def ok_report(res: MorphResult, t0: float) -> dict:
    return envelope(
        status="OK",
        code=None,
        category=None,
        message=None,
        max_disp_mm=rnd(res.max_disp),
        parts=res.parts,
        fallback_faces={b: [f"F{i}" for i in v] for b, v in res.fallback_faces.items()},
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )


# ------------------------------------------------------------------ CLI
def run(args, rep: Reporter) -> int:
    if getattr(args, "sweep", False):
        from . import sweep

        return sweep.run(args, rep)
    t0 = time.monotonic()
    opts = options.load(args.options)
    from .writers import get_writer

    get_writer(getattr(args, "solver", None))  # unknown solver -> GEOM_INPUT_INVALID before any work
    asm = mesh_args(args, ("baseline_inc",)) == "M"
    out = OutDir(args.out_dir, [MORPH_JSON, NODE_XYZ if asm else MORPHED_INC])
    out.prepare()
    doc = load_features(args.features)
    rep.progress(5, "reading baseline and tag")
    if asm:  # assembly match: node coordinates file instead of the include (asm-match.md section 6.1)
        base_bytes, mesh = None, open_source(args).mesh
    else:
        base_bytes, mesh = read_baseline(args.baseline_inc)
    tag = load_tag(args.tag_dir)
    comps = components_from_tag(mesh, tag)
    rep.progress(15, "loading sample B-rep")
    sample = load_sample(args.update_dir, doc)
    rep.progress(25, "computing boundary targets and interior solve")
    try:
        res = morph_core(mesh, comps, sample, opts)
    except MorphFailed as e:
        rep.warn(f"{e.code}: {e.message}")
        out.write_text(MORPH_JSON, dumps(fail_report(e, t0)))
        out.commit([MORPH_JSON])
        rep.result("FAIL", e.code, MORPH_JSON)
        return EXIT_CHECK
    if asm:
        rep.progress(85, "writing node coordinates")
        save_xyz(out.tmp_path(NODE_XYZ), mesh.node_ids, res.xyz)
        written = NODE_XYZ
    else:
        rep.progress(85, "writing morphed include")
        data = write_morphed(base_bytes, mesh, res.moved, getattr(args, "solver", None))
        with open(out.tmp_path(MORPHED_INC), "wb") as f:
            f.write(data)
        written = MORPHED_INC
    out.write_text(MORPH_JSON, dumps(ok_report(res, t0)))
    out.commit([written, MORPH_JSON])
    rep.progress(100, f"morph done: max displacement {res.max_disp:.4f} mm")
    rep.result("OK", None, MORPH_JSON)
    return EXIT_OK
