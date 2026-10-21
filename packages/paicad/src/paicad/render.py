"""Feature highlight PNG (contract section 4.3 ``png``): software rasterizer, numpy + zlib only.

No OpenGL: OCP's VTK needs an X server / GPU context for off-screen rendering and aborts the whole
process on a headless machine (not catchable), so the picture is rasterized here instead. Input is
the kernel's display tessellation (``BodyGeom.triangulate``, neutral numpy arrays).

Picture (800 x 600): body gray and semi-transparent (hidden highlighted faces show through, dimmed),
moving faces orange, fixed faces blue, a black dimension line between the moving and fixed faces
(radius line for holes / fillets). Orthographic isometric view from the octant that best shows the
moving faces.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

W, H = 800, 600
MARGIN = 40
BG = np.array([255, 255, 255], dtype=float)
GRAY = np.array([170, 170, 170], dtype=float)
ORANGE = np.array([255, 140, 0], dtype=float)
BLUE = np.array([30, 100, 255], dtype=float)
LINE = np.array([0, 0, 0], dtype=float)
BODY_ALPHA = 0.55  # opacity of the gray body over hidden highlighted faces
_OCTANTS = [np.array([sx, sy, sz], dtype=float) / np.sqrt(3.0) for sz in (1, -1) for sy in (-1, 1) for sx in (1, -1)]


class BodyMesh:
    """Display tessellation of one body: points[n,3], triangles[m,3], face id per triangle."""

    def __init__(self, faces: list[tuple[int, np.ndarray, np.ndarray]]):
        pts, tris, fid = [], [], []
        off = 0
        for f, p, t in faces:
            pts.append(p)
            tris.append(t + off)
            fid.append(np.full(len(t), f, dtype=np.int64))
            off += len(p)
        self.pts = np.concatenate(pts) if pts else np.zeros((0, 3))
        self.tris = np.concatenate(tris) if tris else np.zeros((0, 3), dtype=np.int64)
        self.face = np.concatenate(fid) if fid else np.zeros(0, dtype=np.int64)
        a, b, c = (self.pts[self.tris[:, i]] for i in range(3)) if len(self.tris) else (np.zeros((0, 3)),) * 3
        n = np.cross(b - a, c - a)
        self.area2 = np.linalg.norm(n, axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.normal = np.where(self.area2[:, None] > 0, n / self.area2[:, None], 0.0)
        self._layers: dict[int, tuple] = {}
        self._base: dict[int, np.ndarray] = {}  # octant -> background + shaded body image
        self._highlights: dict[tuple, tuple] = {}  # (octant, faces) -> (zbuf, cbuf), small LRU


def _view(d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(right, up, toward viewer) for view direction ``d`` (from the scene toward the viewer)."""
    z = np.array([0.0, 0.0, 1.0])
    up = z - np.dot(z, d) * d
    if np.linalg.norm(up) < 1e-6:
        up = np.array([0.0, 1.0, 0.0]) - d[1] * d
    up /= np.linalg.norm(up)
    right = np.cross(up, d)
    return right, up, d


def _project(p: np.ndarray, basis, scale: float, center: np.ndarray) -> np.ndarray:
    r, u, d = basis
    q = p - center
    x = W / 2 + scale * (q @ r)
    y = H / 2 - scale * (q @ u)
    return np.stack([x, y, q @ d], axis=-1)  # depth: larger = nearer the viewer


_HIGHLIGHT_CACHE = 16  # cached highlight rasters per body (a shared entry/base face is drawn for many features)
_FRAG_CHUNK = 1 << 21  # fragments (triangle x bbox pixel) per vectorized batch


def _raster_loop(P: np.ndarray, tris: np.ndarray, shade: np.ndarray, zbuf: np.ndarray, cbuf: np.ndarray) -> None:
    """Reference rasterizer (one triangle at a time); ``_raster`` gives the same buffers, batched."""
    for k, t in enumerate(tris):
        a, b, c = P[t[0]], P[t[1]], P[t[2]]
        x0, x1 = int(max(0, np.floor(min(a[0], b[0], c[0])))), int(min(W - 1, np.ceil(max(a[0], b[0], c[0]))))
        y0, y1 = int(max(0, np.floor(min(a[1], b[1], c[1])))), int(min(H - 1, np.ceil(max(a[1], b[1], c[1]))))
        if x1 < x0 or y1 < y0:
            continue
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / den
        w1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        z = w0 * a[2] + w1 * b[2] + w2 * c[2]
        zb = zbuf[y0 : y1 + 1, x0 : x1 + 1]
        cb = cbuf[y0 : y1 + 1, x0 : x1 + 1]
        upd = inside & (z > zb)
        zb[upd] = z[upd]
        cb[upd] = shade[k]


def _raster(P: np.ndarray, tris: np.ndarray, shade: np.ndarray, zbuf: np.ndarray, cbuf: np.ndarray) -> None:
    """Fill triangles (screen x, y, depth) into the z-buffer (nearest wins) with per-triangle intensity.

    Batched form of ``_raster_loop`` with identical buffers: the same element-wise float expressions per
    (triangle, pixel) fragment; per pixel the first triangle (in order) with the largest depth wins, and it
    replaces the buffer only if strictly nearer - exactly what the sequential ``z > zbuf`` updates leave."""
    if len(tris) == 0:
        return
    A, B, C = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    xmin = np.minimum(np.minimum(A[:, 0], B[:, 0]), C[:, 0])
    xmax = np.maximum(np.maximum(A[:, 0], B[:, 0]), C[:, 0])
    ymin = np.minimum(np.minimum(A[:, 1], B[:, 1]), C[:, 1])
    ymax = np.maximum(np.maximum(A[:, 1], B[:, 1]), C[:, 1])
    x0 = np.maximum(0.0, np.floor(xmin)).astype(np.int64)
    x1 = np.minimum(W - 1.0, np.ceil(xmax)).astype(np.int64)
    y0 = np.maximum(0.0, np.floor(ymin)).astype(np.int64)
    y1 = np.minimum(H - 1.0, np.ceil(ymax)).astype(np.int64)
    den = (B[:, 1] - C[:, 1]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 1] - C[:, 1])
    ok = (x1 >= x0) & (y1 >= y0) & ~(np.abs(den) < 1e-12)
    ks = np.nonzero(ok)[0]
    if len(ks) == 0:
        return
    # candidate pixels: per triangle row, the x span allowed by each edge function (slope >= 1e-3 per pixel),
    # widened by 2 pixels - a superset of the pixels whose exact test below can pass (float error << 1 px)
    ny = y1[ks] - y0[ks] + 1
    rk = np.repeat(ks, ny)
    py_r = y0[rk] + (np.arange(int(ny.sum())) - np.repeat(np.cumsum(ny) - ny, ny))
    ys_r = py_r + 0.5
    dr = den[rk]
    g0 = (B[rk, 1] - C[rk, 1]) / dr
    g1 = (C[rk, 1] - A[rk, 1]) / dr
    h0 = (C[rk, 0] - B[rk, 0]) * (ys_r - C[rk, 1]) / dr
    h1 = (A[rk, 0] - C[rk, 0]) * (ys_r - C[rk, 1]) / dr
    lo = x0[rk].astype(float)
    hi = x1[rk].astype(float)
    cx = C[rk, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        for g, h in ((g0, h0), (g1, h1), (-(g0 + g1), 1.0 - h0 - h1)):
            x_star = cx + (-1e-6 - h) / g  # w(x) >= -1e-6 boundary (x = pixel center)
            steep = np.abs(g) >= 1e-3
            lo = np.where(steep & (g > 0), np.maximum(lo, np.floor(x_star - 0.5) - 2.0), lo)
            hi = np.where(steep & (g < 0), np.minimum(hi, np.ceil(x_star - 0.5) + 2.0), hi)
    lo = np.maximum(lo, x0[rk])
    hi = np.minimum(hi, x1[rk])
    good = hi >= lo
    rk, py_r, lo = rk[good], py_r[good], lo[good].astype(np.int64)
    cnt = hi[good].astype(np.int64) - lo + 1
    if len(cnt) == 0:
        return
    ends = np.cumsum(cnt)
    zflat, cflat = zbuf.reshape(-1), cbuf.reshape(-1)
    start = 0
    while start < len(cnt):
        base = ends[start - 1] if start else 0
        stop = int(np.searchsorted(ends, base + _FRAG_CHUNK, side="right"))
        stop = max(stop, start + 1)
        cc = cnt[start:stop]
        rep = np.repeat(np.arange(start, stop), cc)
        off = np.arange(int(cc.sum())) - np.repeat(np.cumsum(cc) - cc, cc)
        k = rk[rep]
        px = lo[rep] + off
        py = py_r[rep]
        xs = px + 0.5
        ys = py + 0.5
        a0, a1, a2 = A[k, 0], A[k, 1], A[k, 2]
        b0, b1, b2 = B[k, 0], B[k, 1], B[k, 2]
        c0, c1, c2 = C[k, 0], C[k, 1], C[k, 2]
        d = den[k]
        w0 = ((b1 - c1) * (xs - c0) + (c0 - b0) * (ys - c1)) / d
        w1 = ((c1 - a1) * (xs - c0) + (a0 - c0) * (ys - c1)) / d
        w2 = 1.0 - w0 - w1
        z = w0 * a2 + w1 * b2 + w2 * c2
        keep = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6) & (z > -np.inf)  # NaN / -inf never win
        if keep.any():
            pix = (py * W + px)[keep]
            z, k = z[keep], k[keep]
            order = np.lexsort((k, -z, pix))  # per pixel: largest depth, then first triangle
            pix, z, k = pix[order], z[order], k[order]
            first = np.ones(len(pix), dtype=bool)
            first[1:] = pix[1:] != pix[:-1]
            pix, z, k = pix[first], z[first], k[first]
            upd = z > zflat[pix]
            zflat[pix[upd]] = z[upd]
            cflat[pix[upd]] = shade[k[upd]]
        start = stop


def _shade(normal: np.ndarray, d: np.ndarray) -> np.ndarray:
    return 0.45 + 0.55 * np.abs(normal @ d)


def _line(img: np.ndarray, p: np.ndarray, q: np.ndarray, width: int = 2) -> None:
    n = int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1
    for s in np.linspace(0.0, 1.0, max(2, n)):
        x, y = p[:2] + s * (q[:2] - p[:2])
        xi, yi = int(round(x)), int(round(y))
        img[max(0, yi - width // 2) : min(H, yi + width - width // 2), max(0, xi - width // 2) : min(W, xi + width - width // 2)] = LINE


def _arrow(img: np.ndarray, p: np.ndarray, q: np.ndarray) -> None:
    """Dimension line p-q with arrow heads at both ends (screen coordinates)."""
    _line(img, p, q)
    v = q[:2] - p[:2]
    L = float(np.linalg.norm(v))
    if L < 1e-6:
        return
    v /= L
    nrm = np.array([-v[1], v[0]])
    h = min(12.0, 0.3 * L)
    for tip, dirv in ((p[:2], v), (q[:2], -v)):
        for s in (1, -1):
            _line(img, np.array([*tip]), np.array([*(tip + h * dirv + s * 0.5 * h * nrm)]))


def png_bytes(img: np.ndarray) -> bytes:
    """8-bit RGB PNG (filter 0 rows, zlib level 6)."""
    a = np.clip(np.rint(img), 0, 255).astype(np.uint8)
    h, w = a.shape[:2]
    rows = np.zeros((h, 1 + a[0].size), dtype=np.uint8)  # filter byte 0 + RGB row
    rows[:, 1:] = a.reshape(h, -1)
    raw = rows.tobytes()

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _choose_view(mesh: BodyMesh, moving: set[int]) -> int:
    sel = np.isin(mesh.face, sorted(moving)) if moving else np.ones(len(mesh.face), dtype=bool)
    best, best_k = -1.0, 0
    for k, d in enumerate(_OCTANTS):
        s = float(np.sum(mesh.area2[sel] * np.clip(mesh.normal[sel] @ d, 0.0, None))) * (1.0 + 0.05 * d[2])  # prefer views from above
        if s > best * (1.0 + 1e-6) + 1e-12:
            best, best_k = s, k
    return best_k


def _body_layer(mesh: BodyMesh, k: int):
    if k not in mesh._layers:
        d = _OCTANTS[k]
        basis = _view(d)
        lo, hi = mesh.pts.min(axis=0), mesh.pts.max(axis=0)
        center = 0.5 * (lo + hi)
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        r, u, _ = basis
        ext_x = float(np.ptp((corners - center) @ r)) or 1.0
        ext_y = float(np.ptp((corners - center) @ u)) or 1.0
        scale = min((W - 2 * MARGIN) / ext_x, (H - 2 * MARGIN) / ext_y)
        P = _project(mesh.pts, basis, scale, center)
        zbuf = np.full((H, W), -np.inf)
        cbuf = np.zeros((H, W))
        _raster(P, mesh.tris, _shade(mesh.normal, d), zbuf, cbuf)
        mesh._layers[k] = (basis, scale, center, P, zbuf, cbuf)
    return mesh._layers[k]


def render_feature(mesh: BodyMesh, moving: list[int], fixed: list[int], dim: tuple[np.ndarray, np.ndarray] | None) -> np.ndarray:
    """RGB float image[H, W, 3] of one feature on its body."""
    k = _choose_view(mesh, set(moving))
    basis, scale, center, P, zbody, cbody = _body_layer(mesh, k)
    d = _OCTANTS[k]
    base = mesh._base.get(k)
    if base is None:
        base = np.tile(BG, (H, W, 1))
        has_body = np.isfinite(zbody)
        base[has_body] = GRAY[None, :] * cbody[has_body][:, None]
        mesh._base[k] = base
    img = base.copy()
    depth_tol = 1e-3 * max(W, H)
    for faces, color in ((fixed, BLUE), (moving, ORANGE)):
        key = (k, tuple(sorted(faces)))
        got = mesh._highlights.pop(key, None)
        if got is None:
            sel = np.isin(mesh.face, sorted(faces))
            if not sel.any():
                continue
            zh = np.full((H, W), -np.inf)
            ch = np.zeros((H, W))
            _raster(P, mesh.tris[sel], _shade(mesh.normal[sel], d), zh, ch)
            rows, cols = np.nonzero(np.isfinite(zh).any(axis=1))[0], np.nonzero(np.isfinite(zh).any(axis=0))[0]
            box = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1)) if len(rows) else None
            got = (zh[box], ch[box], box) if box is not None else (None, None, None)  # only the hit window
        mesh._highlights[key] = got  # most recently used last
        if len(mesh._highlights) > _HIGHLIGHT_CACHE:
            mesh._highlights.pop(next(iter(mesh._highlights)))
        zh, ch, box = got
        if box is None:
            continue  # nothing drawn: the image is unchanged
        sub = img[box]  # view: pixels outside the window have no hit
        hit = np.isfinite(zh)
        front = hit & (zh >= zbody[box] - depth_tol)
        back = hit & ~front
        col = color[None, :] * (0.55 + 0.45 * ch[..., None])
        sub[front] = col[front]
        sub[back] = BODY_ALPHA * sub[back] + (1.0 - BODY_ALPHA) * col[back]
    if dim is not None:
        a, b = (_project(np.asarray(x, dtype=float)[None, :], basis, scale, center)[0] for x in dim)
        _arrow(img, a, b)
    return img


def dimension_points(feature: dict) -> tuple[np.ndarray, np.ndarray] | None:
    """End points of the dimension line from the feature's face signatures (parameter_features.json entry)."""
    sig = feature.get("face_signatures") or {}
    mv = [sig[f] for f in (feature.get("faces") or {}).get("moving", []) if f in sig]
    fx = [sig[f] for f in (feature.get("faces") or {}).get("fixed", []) if f in sig]
    if not mv:
        return None
    m = mv[0]
    if fx and fx[0].get("normal") is not None:
        p = np.asarray(m["centroid"], dtype=float)
        n = np.asarray(fx[0]["normal"], dtype=float)
        q = p - float(np.dot(p - np.asarray(fx[0]["centroid"], dtype=float), n)) * n  # foot on the fixed plane
        return p, q
    if m.get("axis_dir") is not None and m.get("radius"):
        ax = np.asarray(m["axis_dir"], dtype=float)
        c = np.asarray(m["axis_point"], dtype=float)
        cen = np.asarray(m["centroid"], dtype=float)
        c = c + float(np.dot(cen - c, ax)) * ax  # axis point at the face's height
        perp = np.cross(ax, [0.0, 0.0, 1.0] if abs(ax[2]) < 0.9 else [1.0, 0.0, 0.0])
        perp /= np.linalg.norm(perp)
        return c, c + float(m["radius"]) * perp
    if fx:
        return np.asarray(m["centroid"], dtype=float), np.asarray(fx[0]["centroid"], dtype=float)
    return None


def write_png(path: str | Path, img: np.ndarray) -> None:
    Path(path).write_bytes(png_bytes(img))
