"""``paicad run`` - update -> morph -> check in one call (contract sections 5.3, 5.4, 6.5).

Each stage writes its usual outputs (and log) into its own folder; a stage that fails stops the chain
and later stages produce no report. ``run.json`` (in ``--check-dir``) records every stage and, on
failure, the skip reason ``{code, category, message, step, report}``. Exit code = the failing stage's
exit code (section 5.4), 0 on PASS. The final stdout line is ``PAICAD RESULT <PASS|FAIL> <code|-> run.json``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import options
from .check import CHECK_JSON
from .common import CODE_CATEGORY, EXIT_INTERNAL, EXIT_OK, OutDir, PaicadError, Reporter, StageReporter, dumps, envelope, rnd
from .morph import MORPH_JSON, MORPHED_INC
from .update import FACE_MAP_JSON, SAMPLE_BREP, UPDATE_JSON

RUN_JSON = "run.json"
STAGE_REPORT = {"update": UPDATE_JSON, "morph": MORPH_JSON, "check": CHECK_JSON}


def _stage_args(args) -> list[tuple[str, argparse.Namespace, int, int]]:
    common = dict(options=args.options, threads=args.threads, _nested=True)
    u = argparse.Namespace(cmd="update", cad=args.cad, features=args.features, values=args.values, out_dir=args.update_dir, tag_dir=args.tag_dir, body_map=args.body_map, **common)
    m = argparse.Namespace(
        cmd="morph", baseline_inc=args.baseline_inc, tag_dir=args.tag_dir, features=args.features, update_dir=args.update_dir, out_dir=args.morph_dir, solver=args.solver, sweep=False, **common
    )
    c = argparse.Namespace(
        cmd="check",
        baseline_inc=args.baseline_inc,
        morph_dir=args.morph_dir,
        update_dir=args.update_dir,
        tag_dir=args.tag_dir,
        features=args.features,
        values=args.values,
        assem_dir=args.assem_dir,
        renum_csv=args.renum_csv,
        out_dir=args.check_dir,
        out_inc=args.out_inc,
        **common,
    )
    return [("update", u, 2, 35), ("morph", m, 35, 70), ("check", c, 70, 97)]


def _precheck(args) -> None:
    from .writers import get_writer

    options.load(args.options)
    get_writer(args.solver)
    existing = []
    for d, names in ((args.update_dir, [UPDATE_JSON, SAMPLE_BREP, FACE_MAP_JSON]), (args.morph_dir, [MORPH_JSON, MORPHED_INC]), (args.check_dir, [CHECK_JSON, RUN_JSON])):
        existing += [n for n in names if (Path(d) / n).exists()]
    if Path(args.out_inc).exists():
        existing.append(Path(args.out_inc).name)
    if existing:
        raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {', '.join(existing[:10])}")


def _read_report(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def run(args, rep: Reporter) -> int:
    from .cli import guarded

    t0 = time.monotonic()
    _precheck(args)
    stages, fail = [], None
    for name, ns, lo, hi in _stage_args(args):
        srep = StageReporter(Path(ns.out_dir), rep, name, lo, hi)
        try:
            code, err_code, err_msg = guarded(ns, srep)
        finally:
            srep.close()
        rpath = Path(ns.out_dir) / STAGE_REPORT[name]
        d = _read_report(rpath) if rpath.is_file() else None
        rec = {
            "step": name,
            "exit_code": code,
            "status": d.get("status") if d else None,
            "code": (d.get("code") if d else None) or err_code,
            "report": str(rpath) if d else None,
        }
        stages.append(rec)
        if code != EXIT_OK:
            fcode = rec["code"] or "GEOM_INTERNAL"
            fail = {
                "code": fcode,
                "category": (d.get("category") if d else None) or CODE_CATEGORY.get(fcode),
                "message": (d.get("message") if d else None) or err_msg or f"{name} failed with exit code {code}",
                "step": name,
                "report": rec["report"],
                "exit_code": code,
            }
            break
    status = "FAIL" if fail else "PASS"
    doc = envelope(
        status=status,
        code=fail["code"] if fail else None,
        category=fail["category"] if fail else None,
        message=fail["message"] if fail else None,
        stages=stages,
        skip=None if fail is None else {k: fail[k] for k in ("code", "category", "message", "step", "report")},
        out_inc=Path(args.out_inc).name if not fail else None,
        solver=args.solver or "radioss",
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out = OutDir(args.check_dir, [RUN_JSON])
    out.prepare()
    out.write_text(RUN_JSON, dumps(doc))
    out.commit([RUN_JSON])
    rep.progress(100, f"run {status}")
    rep.result(status, doc["code"], RUN_JSON)
    if fail is None:
        return EXIT_OK
    return int(fail["exit_code"]) if fail["exit_code"] else EXIT_INTERNAL
