"""``paicad cushion write`` - cushion-only starter rad for prediction input (input-kind.md section 5, GE-C19).

Inputs are read only; ``cushion.json`` goes to ``--out-dir`` and the rad to ``--out-rad`` (both never
overwritten: GEOM_OUTPUT_EXISTS). No OCP: only the Radioss reader and the solver writer registry.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import options
from .common import EXIT_OK, OutDir, PaicadError, Reporter, dumps, envelope, rnd
from .mesh.radioss import read_renum_csv
from .writers import get_writer

CUSHION_JSON = "cushion.json"


def report(res, out_name: str, t0: float) -> dict:
    return envelope(
        status="OK",
        code=None,
        category=None,
        message="cushion rad written",
        out_rad=out_name,
        node_count=res.node_count,
        elem_count=res.elem_count,
        bytes=len(res.data),
        parts=res.parts,
        begin_from=res.begin_from,
        def_sources=res.def_sources,
        warnings=res.warnings,
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )


def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    if args.options:
        options.load(args.options)  # validated like every command; no cushion keys
    writer = get_writer(args.solver)
    if not hasattr(writer, "write_cushion"):
        raise PaicadError("GEOM_INPUT_INVALID", f"solver writer {writer.name!r} cannot write a cushion input file")
    out_rad = Path(args.out_rad)
    if out_rad.exists():
        raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {out_rad.name}")
    out = OutDir(args.out_dir, [CUSHION_JSON])
    out.prepare()
    inc = Path(args.inc)
    if not inc.is_file():
        raise PaicadError("GEOM_INPUT_INVALID", f"cushion include not found: {inc.name}")
    assem = Path(args.assem_dir)
    if not assem.is_dir():
        raise PaicadError("GEOM_INPUT_INVALID", f"assembly folder not found: {assem.name}")
    renum = read_renum_csv(args.renum_csv)
    rep.progress(10, "reading cushion include")
    res = writer.write_cushion(inc, renum, assem, out_rad.name)
    rep.progress(80, f"writing {res.node_count} nodes, {res.elem_count} elements")
    for w in res.warnings:
        rep.warn(f"{w['code']}: {w['message']}")
    out.write_text(CUSHION_JSON, dumps(report(res, out_rad.name, t0)))
    out_rad.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_rad.with_name(f".{out_rad.name}.tmp{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(res.data)
    if out_rad.exists():
        raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {out_rad.name}")
    os.replace(tmp, out_rad)
    out.commit([CUSHION_JSON])
    rep.progress(100, "cushion write OK")
    rep.result("OK", None, CUSHION_JSON)
    return EXIT_OK
