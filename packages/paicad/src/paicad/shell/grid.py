"""``paicad shell view grid`` - DOE sample thumbnail grid of the mid-surface sheet (doe-preview.md section 3,
``kind: "shell"``): the cells run the ``shell view preview --fe off`` update (same outputs), the nominal GLB is the
``shell view export --fixed-dir`` GLB, an update FAIL cell shows the nominal sheet gray with the faces of the failing
beads red. Shared engine: ``paicad.view.grid``."""

from __future__ import annotations

import time

from ..common import OutDir, Reporter
from ..view import BodyTess, generator, gltf, load_view_options
from ..view.export import ROOT_EXTRAS
from ..view.grid import CELLS_DIR, GRID_MANIFEST, GridSpec, load_cells, load_thumb_options, run_grid
from ..view.preview import _nominal_ref
from . import opts as shopts
from .common import load_shell_features, values_from
from .view import ShellPreviewInputs, _bead_faces, _bodies, _fixed, _glb_items, _source, fixed_markers, shell_preview_core


def run(args, rep: Reporter) -> int:
    t_start = time.monotonic()
    vopts = load_view_options(args.view_options)
    o = shopts.load(args.options)
    topts = load_thumb_options(args.thumb_options)
    nominal_ref, tess = _nominal_ref(None, vopts)
    out = OutDir(args.out_dir, [GRID_MANIFEST, CELLS_DIR])
    out.prepare()
    doc = load_shell_features(args.features)
    cells = load_cells(args.cells, lambda v: values_from(v, doc, o))
    fixed = _fixed(args.fixed_dir)
    rep.progress(5, "loading mid-surface CAD")
    cad, names, nominal = _bodies(args.cad, doc)
    ctx = ShellPreviewInputs("off", vopts, o, nominal_ref, tess, doc, fixed, cad, names, nominal, _source(cad, args.features, fixed))
    fm = {f["name"]: f for f in doc["features"]}
    beads = {b["id"]: b for b in doc["beads"]}

    def fail_faces(feats: list[str]) -> dict[str, set[int]]:
        red: dict[str, set[int]] = {}
        for n in feats:
            f = fm.get(n)
            bj = beads.get(f["bead"]) if f is not None else None
            if bj:
                red.setdefault(f["body"], set()).update(int(str(x)[1:]) for x in _bead_faces(bj)[0])
        return red

    def build(tbs: list[BodyTess]) -> bytes:
        markers, _ = fixed_markers(doc, fixed, tbs)
        return gltf.write_glb(_glb_items(tbs, None, markers), generator(), root_extras=ROOT_EXTRAS)

    spec = GridSpec("shell", names, nominal, tess, vopts, build, lambda values, co, r, t0, sink: shell_preview_core(ctx, values, co, r, t0, sink), fail_faces)
    return run_grid(spec, cells, topts, out, rep, t_start)
