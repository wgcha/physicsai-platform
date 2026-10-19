"""Bead highlight PNG (shell-morph section 4.2): bead faces orange, fixed nodes blue dots, dimension line."""

from __future__ import annotations

import numpy as np

from .. import render as R


def _dimension(bead: dict, feat: dict, body) -> tuple[np.ndarray, np.ndarray] | None:
    c = np.asarray(bead["center"], dtype=float)
    ed = np.asarray(bead["depth_dir"], dtype=float)
    nom = bead["nominal"]
    t = feat["type"]
    if t == "BEAD_DEPTH":
        return c, c + float(nom["depth"]) * ed
    if t == "BEAD_WIDTH":
        u = np.asarray(bead["axis"], dtype=float)
        w = np.cross(np.asarray(bead["normal"], dtype=float), u)
        if bead["shape"] == "linear":
            w = np.cross(np.asarray(bead["normal"], dtype=float), np.asarray(bead["core"][1]) - np.asarray(bead["core"][0]))
            w /= np.linalg.norm(w)
        m = c + 0.5 * float(nom["depth"]) * ed
        return m - 0.5 * float(nom["width"]) * w, m + 0.5 * float(nom["width"]) * w
    ref = feat.get("ref") or {}
    ax = np.asarray(ref.get("axis") or bead["axis"], dtype=float)
    return c, c - float(ref.get("sign", 1.0)) * float(feat["nominal"]) * ax


def render_bead(mesh: R.BodyMesh, bead: dict, feat: dict, fixed_pts: np.ndarray, body) -> np.ndarray:
    faces = [int(x[1:]) for k in ("fillets_top", "flanks", "fillets_bottom", "bottom") for x in bead[k]]
    img = R.render_feature(mesh, faces, [], _dimension(bead, feat, body))
    k = R._choose_view(mesh, set(faces))
    basis, scale, center, _, _, _ = R._body_layer(mesh, k)
    if len(fixed_pts):
        P = R._project(np.asarray(fixed_pts, dtype=float), basis, scale, center)
        for x, y in P[:, :2]:
            xi, yi = int(round(x)), int(round(y))
            if 1 <= xi < R.W - 1 and 1 <= yi < R.H - 1:
                img[yi - 1 : yi + 2, xi - 1 : xi + 2] = R.BLUE
    return img
