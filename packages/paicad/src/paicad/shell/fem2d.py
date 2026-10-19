"""In-surface displacement solve on a planar shell patch (shell-morph section 6.5-2), numpy/scipy only.

``elastic``: plane-stress linear elasticity, CST triangles / bilinear Q4 quads (2 x 2 Gauss), element
modulus ``E0 * mean_area / area`` (small elements are stiffer); ``laplacian``: cotangent-weighted harmonic
interpolation per component. Dirichlet nodes carry prescribed displacements. Solver: Jacobi-preconditioned
CG (``solver_rtol`` / ``solver_maxiter``), direct ``spsolve`` when CG does not converge.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix, diags
from scipy.sparse.linalg import cg, splu, spsolve


class SolveFailed(Exception):
    pass


@dataclass
class SolveInfo:
    method: str
    iterations: int
    rel_residual: float


def _cst(xy: np.ndarray, tris: np.ndarray, E: np.ndarray, nu: float):
    p = xy[tris]
    x1, y1 = p[:, 0, 0], p[:, 0, 1]
    x2, y2 = p[:, 1, 0], p[:, 1, 1]
    x3, y3 = p[:, 2, 0], p[:, 2, 1]
    A2 = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    b = np.stack([y2 - y3, y3 - y1, y1 - y2], axis=1)
    c = np.stack([x3 - x2, x1 - x3, x2 - x1], axis=1)
    B = np.zeros((len(tris), 3, 6))
    B[:, 0, 0::2] = b
    B[:, 1, 1::2] = c
    B[:, 2, 0::2] = c
    B[:, 2, 1::2] = b
    B /= A2[:, None, None]
    D = np.array([[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2]]) / (1 - nu * nu)
    Ke = np.einsum("eki,kl,elj->eij", B, D, B) * (0.5 * np.abs(A2) * E)[:, None, None]
    return Ke


_G = np.array([-1.0, 1.0]) / np.sqrt(3.0)


def _q4(xy: np.ndarray, quads: np.ndarray, E: np.ndarray, nu: float):
    p = xy[quads]  # (m,4,2)
    D = np.array([[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2]]) / (1 - nu * nu)
    Ke = np.zeros((len(quads), 8, 8))
    for xi in _G:
        for eta in _G:
            dN = 0.25 * np.array([[-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)], [-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)]])
            J = np.einsum("ak,mkb->mab", dN, p)  # (m,2,2)
            det = J[:, 0, 0] * J[:, 1, 1] - J[:, 0, 1] * J[:, 1, 0]
            inv = np.stack([np.stack([J[:, 1, 1], -J[:, 0, 1]], -1), np.stack([-J[:, 1, 0], J[:, 0, 0]], -1)], 1) / det[:, None, None]
            dNx = np.einsum("mab,bk->mak", inv, dN)  # (m,2,4)
            B = np.zeros((len(quads), 3, 8))
            B[:, 0, 0::2] = dNx[:, 0]
            B[:, 1, 1::2] = dNx[:, 1]
            B[:, 2, 0::2] = dNx[:, 1]
            B[:, 2, 1::2] = dNx[:, 0]
            Ke += np.einsum("eki,kl,elj->eij", B, D, B) * (np.abs(det) * E)[:, None, None]
    return Ke


def _areas(xy, tris, quads):
    def tri_area(t):
        p = xy[t]
        return 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))

    at = tri_area(tris) if len(tris) else np.zeros(0)
    aq = (tri_area(quads[:, [0, 1, 2]]) + tri_area(quads[:, [0, 2, 3]])) if len(quads) else np.zeros(0)
    return at, aq


DIRECT_MAX_DOF = 300_000
_CACHE: dict = {}  # cache key -> (Kff, Kfd, LU) - the patch system is the same for every sweep step


def _solve(K: csr_matrix, free: np.ndarray, fixed: np.ndarray, uf_known: np.ndarray, ncomp: int, rtol: float, maxiter: int, key=None):
    n = K.shape[0] if K is not None else _CACHE[key][3]
    u = np.zeros(n)
    u[fixed] = uf_known
    if len(free) == 0:
        return u, SolveInfo("none", 0, 0.0)
    if key is not None and key in _CACHE:
        Kff, Kfd, lu, _ = _CACHE[key]
    else:
        Kff = K[free][:, free].tocsc()
        Kfd = K[free][:, fixed].tocsr()
        lu = None
    rhs = -(Kfd @ uf_known)
    if not np.any(rhs):
        return u, SolveInfo("none", 0, 0.0)
    if len(free) <= DIRECT_MAX_DOF:
        # direct sparse LU (same solution as the CG of GE section 6.4-2, factorization reused across sweep steps)
        try:
            if lu is None:
                lu = splu(Kff)
                if key is not None:
                    if len(_CACHE) >= 16:
                        _CACHE.pop(next(iter(_CACHE)))
                    _CACHE[key] = (Kff, Kfd, lu, n)
            x = lu.solve(rhs)
            res = float(np.linalg.norm(Kff @ x - rhs) / (np.linalg.norm(rhs) or 1.0))
            if np.all(np.isfinite(x)) and res <= max(1e-6, 10 * rtol):
                u[free] = x
                return u, SolveInfo("splu", 1, res)
        except RuntimeError:
            pass
    d = Kff.diagonal()
    if np.any(d <= 0):
        raise SolveFailed("singular in-surface system (free node without element stiffness)")
    M = diags(1.0 / d)
    it = [0]

    def cb(_):
        it[0] += 1

    x, flag = cg(Kff, rhs, rtol=rtol, maxiter=maxiter, M=M, callback=cb)
    res = float(np.linalg.norm(Kff @ x - rhs) / (np.linalg.norm(rhs) or 1.0))
    method = "cg"
    if flag != 0 or not np.isfinite(res) or res > 10 * rtol:
        x = spsolve(Kff.tocsc(), rhs)
        res = float(np.linalg.norm(Kff @ x - rhs) / (np.linalg.norm(rhs) or 1.0))
        method = "spsolve"
        if not np.all(np.isfinite(x)) or res > 1e-6:
            raise SolveFailed(f"in-surface solve did not converge (relative residual {res:.3g})")
    u[free] = x
    return u, SolveInfo(method, it[0], res)


def solve_patch(xy: np.ndarray, tris: np.ndarray, quads: np.ndarray, dir_idx: np.ndarray, dir_val: np.ndarray, smoother: str, nu: float, rtol: float, maxiter: int, key=None):
    """Displacements u[n,2] of the patch nodes; ``dir_idx`` / ``dir_val[k,2]`` = Dirichlet nodes / values.
    ``key``: cache key of this patch system (same mesh, Dirichlet set and options -> reuse the factorization)."""
    n = len(xy)
    dir_idx = np.asarray(dir_idx, dtype=np.int64)
    free_nodes = np.setdiff1d(np.arange(n), dir_idx)
    if key is not None and (key, smoother) in _CACHE:
        fd = np.stack([2 * dir_idx, 2 * dir_idx + 1], 1).ravel() if smoother != "laplacian" else dir_idx
        if smoother == "laplacian":
            u = np.zeros((n, 2))
            info = SolveInfo("none", 0, 0.0)
            for c in range(2):
                uc, info = _solve(None, free_nodes, dir_idx, dir_val[:, c], 1, rtol, maxiter, (key, smoother))
                u[:, c] = uc
            return u, info
        ff = np.stack([2 * free_nodes, 2 * free_nodes + 1], 1).ravel()
        uu, info = _solve(None, ff, fd, np.asarray(dir_val, dtype=float).reshape(-1), 2, rtol, maxiter, (key, smoother))
        return uu.reshape(n, 2), info
    if smoother == "laplacian":
        allt = np.concatenate([tris, quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]]) if len(quads) else tris
        rows, cols, vals = [], [], []
        p = xy[allt]
        for k in range(3):
            i, j, m = allt[:, k], allt[:, (k + 1) % 3], allt[:, (k + 2) % 3]
            a = p[:, k] - p[:, (k + 2) % 3]
            b = p[:, (k + 1) % 3] - p[:, (k + 2) % 3]
            cross = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
            cot = np.einsum("ij,ij->i", a, b) / np.maximum(cross, 1e-30)
            w = 0.5 * np.maximum(cot, 1e-6)
            rows += [i, j, i, j]
            cols += [j, i, i, j]
            vals += [-w, -w, w, w]
            del m
        L = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
        u = np.zeros((n, 2))
        info = SolveInfo("none", 0, 0.0)
        for c in range(2):
            uc, info = _solve(L, free_nodes, dir_idx, dir_val[:, c], 1, rtol, maxiter, None if key is None else (key, smoother))
            u[:, c] = uc
        return u, info
    at, aq = _areas(xy, tris, quads)
    allA = np.concatenate([at, aq])
    if np.any(allA <= 1e-14):
        raise SolveFailed("degenerate element in the in-surface patch")
    Abar = float(allA.mean())
    rows, cols, vals = [], [], []
    for conn, Ke in ((tris, _cst(xy, tris, Abar / at, nu) if len(tris) else None), (quads, _q4(xy, quads, Abar / aq, nu) if len(quads) else None)):
        if Ke is None:
            continue
        k = conn.shape[1]
        dofs = np.stack([2 * conn, 2 * conn + 1], axis=2).reshape(len(conn), 2 * k)
        rows.append(np.repeat(dofs, 2 * k, axis=1).ravel())
        cols.append(np.tile(dofs, (1, 2 * k)).ravel())
        vals.append(Ke.ravel())
    K = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(2 * n, 2 * n)).tocsr()
    fd = np.stack([2 * dir_idx, 2 * dir_idx + 1], 1).ravel()
    ff = np.stack([2 * free_nodes, 2 * free_nodes + 1], 1).ravel()
    uu, info = _solve(K, ff, fd, np.asarray(dir_val, dtype=float).reshape(-1), 2, rtol, maxiter, None if key is None else (key, smoother))
    return uu.reshape(n, 2), info
