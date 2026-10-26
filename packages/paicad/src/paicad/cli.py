"""``paicad`` command line (contract section 5)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import sys
import traceback
from pathlib import Path

from . import __version__

EPILOG = "Exit codes: 0 ok, 2 arguments, 3 input, 10 CAD, 11 check/morph/props apply, 12 tag, 13 extract empty, 14 view output, 15 asm check FAIL, 20 internal, 130 interrupted."
MESH_HELP = "mesh source: --baseline-inc + --renum-csv (baseline include) or --asm-match + --assem-dir (assembly match, asm-match.md)"


def _asm_source_args(sp, assem: bool = False) -> None:
    """Method M arguments of the solid commands (asm-match.md section 6.1)."""
    sp.add_argument("--asm-match", help="confirmed asm_match.json (assembly match: replaces --baseline-inc/--renum-csv)")
    if assem:
        sp.add_argument("--assem-dir", help="assembly folder (include tree root)")
    sp.add_argument("--cache-dir", help="include tree parse cache folder (<sha256>.idx.npz)")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paicad", description="Native geometry engine (R1 morphing).", epilog=EPILOG, allow_abbrev=False)
    p.add_argument("--version", action="version", version=f"paicad {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    v = sub.add_parser("version", help="print component versions", allow_abbrev=False)
    v.add_argument("--json", action="store_true", help="JSON output")

    e = sub.add_parser("extract", help="recognize parametric features of the nominal CAD", allow_abbrev=False)
    e.add_argument("--cad", required=True, help="STEP file or folder of per-component STEP files")
    e.add_argument("--out-dir", required=True)
    e.add_argument("--body-map")
    e.add_argument("--renum-csv")
    e.add_argument("--asm-match", help="confirmed asm_match.json: body / component correspondence check (instead of --renum-csv)")
    e.add_argument("--options", help="options.json; optional extract.filter = feature types to find + conditions (types, thickness_mm, height_mm, face_area_min_mm2, position_min_size_mm, hole_radius_min_mm, fillet_radius_min_mm) - also enables RIB_POS_U/V and RIB_PITCH_U/V (rib rows, optional rib_gap section); extract_stats.json is always written")
    e.add_argument("--no-png", action="store_true")
    e.add_argument("--threads", type=int)

    t = sub.add_parser("tag", help="classify baseline mesh nodes onto the nominal B-rep", allow_abbrev=False, epilog=MESH_HELP)
    for a in ("--cad", "--features", "--assem-dir", "--out-dir"):
        t.add_argument(a, required=True)
    t.add_argument("--baseline-inc")
    t.add_argument("--renum-csv")
    _asm_source_args(t)
    t.add_argument("--body-map")
    t.add_argument("--options")
    t.add_argument("--threads", type=int)
    u = sub.add_parser("update", help="apply sample values to the nominal B-rep (push/pull)", allow_abbrev=False)
    for a in ("--cad", "--features", "--values", "--out-dir"):
        u.add_argument(a, required=True)
    u.add_argument("--tag-dir")
    u.add_argument("--body-map")
    u.add_argument("--options")
    u.add_argument("--threads", type=int)

    m = sub.add_parser("morph", help="move baseline node coordinates onto the sample B-rep (or --sweep: morphing envelope)", allow_abbrev=False, epilog=MESH_HELP)
    for a in ("--tag-dir", "--features", "--update-dir", "--out-dir"):
        m.add_argument(a, required=True)
    m.add_argument("--baseline-inc")
    _asm_source_args(m, assem=True)
    m.add_argument("--options")
    m.add_argument("--threads", type=int)
    m.add_argument("--solver", default=None, help="solver writer for the morphed file (default radioss)")
    m.add_argument("--sweep", action="store_true", help="1D parameter sweep -> envelope.json/csv")
    m.add_argument("--steps", default="5,10,20,30,40,50", help="sweep steps in percent of the nominal value")
    m.add_argument("--pos-steps", default="1,2,3,5,8,10", help="sweep steps of position parameters (HOLE_POS_U/V, RIB_POS_U/V) and rib pitches (RIB_PITCH_U/V) in mm from the nominal value")
    m.add_argument("--params", help="comma-separated parameter names (default: all values.json keys)")
    m.add_argument("--stop-after-fail", type=int, default=2, help="stop a direction after this many consecutive failures")
    m.add_argument("--check", default="on", choices=["on", "off"], help="evaluate quality/deviation/re-measurement per step")
    m.add_argument("--keep-steps", action="store_true", help="keep per-step outputs under sweep/<param>/<+-pct>/")

    c = sub.add_parser("check", help="check the morphed mesh and write the include (node patch) on PASS", allow_abbrev=False, epilog=MESH_HELP)
    for a in ("--morph-dir", "--update-dir", "--tag-dir", "--features", "--values", "--assem-dir", "--out-dir"):
        c.add_argument(a, required=True)
    for a in ("--baseline-inc", "--renum-csv", "--out-inc"):
        c.add_argument(a)
    c.add_argument("--out-patch", help="assembly match: node_patch.npz written on PASS (instead of --out-inc)")
    _asm_source_args(c)
    c.add_argument("--options")
    c.add_argument("--threads", type=int)

    r = sub.add_parser("run", help="update -> morph -> check in one call (stops at the first failing stage)", allow_abbrev=False, epilog=MESH_HELP)
    for a in ("--cad", "--features", "--values", "--tag-dir", "--assem-dir", "--update-dir", "--morph-dir", "--check-dir"):
        r.add_argument(a, required=True)
    for a in ("--baseline-inc", "--renum-csv", "--out-inc"):
        r.add_argument(a)
    r.add_argument("--out-patch", help="assembly match: node_patch.npz written on PASS (instead of --out-inc)")
    _asm_source_args(r)
    r.add_argument("--body-map")
    r.add_argument("--options")
    r.add_argument("--solver", default=None, help="solver writer (default radioss)")
    r.add_argument("--threads", type=int)

    pr = sub.add_parser("props", help="shell thickness parameters (/PROP/TYPE1): scan | apply", allow_abbrev=False)
    psub = pr.add_subparsers(dest="props_cmd", metavar="action", required=True)
    ps = psub.add_parser("scan", help="list shell properties of the assembly folder -> props.json", allow_abbrev=False)
    ps.add_argument("--assem-dir", required=True)
    ps.add_argument("--out-dir", required=True)
    ps.add_argument("--options")
    ps.add_argument("--threads", type=int)
    pa = psub.add_parser("apply", help="write copies of PROP files with new thicknesses -> props_apply.json", allow_abbrev=False)
    for a in ("--assem-dir", "--values", "--props", "--out-dir"):
        pa.add_argument(a, required=True)
    pa.add_argument("--threads", type=int)

    mp = sub.add_parser("map", help="multi-baseline parameter matching draft -> param_map.json", allow_abbrev=False)
    mp.add_argument("--baselines", required=True, help='JSON file [{"id", "features", "rel"?}] (2 or more baselines)')
    mp.add_argument("--out-dir", required=True)
    mp.add_argument("--user-map", help="previous param_map.json: decisions of rows with the same signature are kept")
    mp.add_argument("--usage", default="topology", choices=["topology", "range"])
    mp.add_argument("--split-param", help="range usage: proposed common name of the split parameter")
    mp.add_argument("--options")
    mp.add_argument("--threads", type=int)

    vw = sub.add_parser("view", help="3D view (GLB) of the nominal B-rep | parameter preview", allow_abbrev=False)
    vsub = vw.add_subparsers(dest="view_cmd", metavar="action", required=True)
    ve = vsub.add_parser("export", help="nominal B-rep -> view.glb + view_manifest.json", allow_abbrev=False)
    for a in ("--cad", "--features", "--out-dir"):
        ve.add_argument(a, required=True)
    ve.add_argument("--body-map")
    ve.add_argument("--view-options", help="view_options.json (tessellation tolerances, size limits)")
    ve.add_argument("--threads", type=int)
    vp = vsub.add_parser("preview", help="values -> changed B-rep preview.glb (+ morphed FE skin) + preview_manifest.json", allow_abbrev=False)
    for a in ("--cad", "--features", "--values", "--out-dir"):
        vp.add_argument(a, required=True)
    vp.add_argument("--tag-dir")
    vp.add_argument("--body-map")
    vp.add_argument("--options", help="geometry options (update/morph/check behaviour)")
    vp.add_argument("--view-options")
    vp.add_argument("--nominal-manifest", help="nominal view_manifest.json (nominal_ref and tessellation tolerances)")
    vp.add_argument("--fe", default="off", choices=["off", "morph", "check"], help="also morph (and check) the baseline mesh (default off)")
    vp.add_argument("--baseline-inc")
    vp.add_argument("--renum-csv")
    vp.add_argument("--assem-dir")
    _asm_source_args(vp)
    vp.add_argument("--threads", type=int)
    add_grid_parser(vsub, shell=False)

    st = sub.add_parser("selftest", help="site acceptance kit: numeric summary report only (no CAD/mesh content)", allow_abbrev=False, epilog=MESH_HELP)
    for a in ("--cad", "--assem-dir", "--out-dir"):
        st.add_argument(a, required=True)
    st.add_argument("--baseline-inc")
    st.add_argument("--renum-csv")
    _asm_source_args(st)
    st.add_argument("--body-map")
    st.add_argument("--options")
    st.add_argument("--envelope-steps", default="5,10", help="short envelope steps in percent (default 5,10)")
    st.add_argument("--envelope-pos-steps", default="1,3", help="short envelope steps of position parameters in mm (default 1,3)")
    st.add_argument("--envelope-params", help="comma-separated parameter names (default: all)")
    st.add_argument("--stop-after-fail", type=int, default=1)
    st.add_argument("--no-envelope", action="store_true")
    st.add_argument("--nx-samples", help="folder of NX change samples: <name>.json (values) + <name>.step per sample")
    st.add_argument("--threads", type=int)

    cu = sub.add_parser("cushion", help="cushion-only solver input for prediction: write", allow_abbrev=False)
    csub = cu.add_subparsers(dest="cushion_cmd", metavar="action", required=True)
    cw = csub.add_parser("write", help="morphed cushion include (or assembly match + node patch) -> single cushion starter rad + cushion.json", allow_abbrev=False)
    for a in ("--assem-dir", "--out-dir", "--out-rad"):
        cw.add_argument(a, required=True)
    cw.add_argument("--inc")
    cw.add_argument("--renum-csv")
    cw.add_argument("--patch", help="assembly match: node_patch.npz (absent = nominal coordinates)")
    _asm_source_args(cw)
    cw.add_argument("--solver", default=None, help="solver writer (default radioss)")
    cw.add_argument("--options")
    cw.add_argument("--threads", type=int)

    am = sub.add_parser("asm", help="assembly match: parts | check | write (asm-match.md)", allow_abbrev=False)
    asub = am.add_subparsers(dest="asm_cmd", metavar="action", required=True)
    ap = asub.add_parser("parts", help="include tree -> PART list + body recommendation -> asm_parts.json", allow_abbrev=False)
    ap.add_argument("--assem-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--features", help="parameter_features.json (bodies; no OCP)")
    g.add_argument("--cad", help="STEP file or folder (bodies read from the CAD)")
    ap.add_argument("--renum-csv", help="renumber table: RENUM ranges recommended first")
    ap.add_argument("--cache-dir")
    ap.add_argument("--options")
    ap.add_argument("--threads", type=int)
    ac = asub.add_parser("check", help="match rows -> skin node / CAD boundary distance check -> asm_check.json (+ match_fe.glb)", allow_abbrev=False)
    for a in ("--cad", "--assem-dir", "--match", "--out-dir"):
        ac.add_argument(a, required=True)
    ac.add_argument("--features")
    ac.add_argument("--cache-dir")
    ac.add_argument("--options")
    ac.add_argument("--no-glb", action="store_true")
    ac.add_argument("--threads", type=int)
    aw = asub.add_parser("write", help="include tree copy with the patch node coordinates -> asm_write.json", allow_abbrev=False)
    for a in ("--assem-dir", "--asm-match", "--out-dir"):
        aw.add_argument(a, required=True)
    aw.add_argument("--patch", help="node_patch.npz (absent = byte-identical copy)")
    aw.add_argument("--cache-dir")
    aw.add_argument("--threads", type=int)

    from .shell.cli import add_parser as add_shell_parser

    add_shell_parser(sub)
    return p


def add_grid_parser(vsub, shell: bool) -> None:
    """``paicad [shell] view grid`` (doe-preview.md section 3.1)."""
    what = "sheet" if shell else "B-rep"
    g = vsub.add_parser("grid", help=f"cells.json value sets -> per cell changed {what} preview (update only) + thumb.png, grid_manifest.json", allow_abbrev=False)
    for a in ("--cad", "--features", "--cells", "--out-dir", *(("--fixed-dir",) if shell else ()), "--thumb-options"):
        g.add_argument(a, required=True)
    g.add_argument("--tag-dir", help="tag output" + (" (accepted, not used by the shell update)" if shell else " (contact faces of the update)"))
    g.add_argument("--body-map")
    g.add_argument("--options", help="geometry options (update behaviour)")
    g.add_argument("--view-options", help="view_options.json (tessellation tolerances, size limits)")
    g.add_argument("--threads", type=int)


def versions() -> dict:
    out = {"paicad": __version__}
    try:
        from .kernel import kernel_versions

        out.update(kernel_versions())
    except Exception:  # OCP missing: still report the rest
        out["ocp"] = None
    import numpy
    import scipy

    out["numpy"] = numpy.__version__
    out["scipy"] = scipy.__version__
    out["python"] = platform.python_version()
    return out


REPORTS = {
    "tag": "tag.json",
    "update": "update.json",
    "morph": "morph.json",
    "check": "check.json",
    "run": "run.json",
    "props apply": "props_apply.json",
    "view export": "view_manifest.json",
    "view preview": "preview_manifest.json",
    "cushion write": "cushion.json",
    "asm parts": "asm_parts.json",
    "asm check": "asm_check.json",
    "asm write": "asm_write.json",
}

# solid commands with two mesh sources (asm-match.md AM-9): (method L arguments, extra method M arguments)
MESH_SOURCES = {
    "tag": (("baseline_inc", "renum_csv"), ()),
    "morph": (("baseline_inc",), ()),
    "check": (("baseline_inc", "renum_csv", "out_inc"), ("out_patch",)),
    "run": (("baseline_inc", "renum_csv", "out_inc"), ("out_patch",)),
    "selftest": (("baseline_inc", "renum_csv"), ()),
    "cushion": (("inc", "renum_csv"), ()),
}


def _mesh_source_missing(args) -> list[str]:
    """Missing arguments of the chosen mesh source (argparse-like exit 2); mixing both sources is left to the
    command (GEOM_INPUT_INVALID with a report)."""
    spec = MESH_SOURCES.get(args.cmd)
    if spec is None:
        return []
    l_keys, m_keys = spec
    if getattr(args, "asm_match", None):
        if any(getattr(args, k, None) for k in l_keys):
            return []
        need = ("asm_match", "assem_dir") + m_keys
    else:
        need = l_keys
    return ["--" + k.replace("_", "-") for k in need if not getattr(args, k, None)]


def _fail_report(cmd: str, out_dir: str, code: str, message: str) -> str | None:
    """Best-effort FAIL report for input/internal errors (section 5.4: report when possible); never overwrites.
    Success-by-existence outputs (props.json, param_map.json, extract files) never get a FAIL report."""
    from .common import CODE_CATEGORY, dumps, envelope

    if cmd.startswith("shell "):
        from .shell.cli import REPORTS as SHELL_REPORTS
        from .shell.common import shell_envelope

        name = SHELL_REPORTS.get(cmd[6:])
        mk = envelope if cmd.startswith("shell view ") else shell_envelope
    else:
        name = REPORTS.get(cmd)
        mk = envelope
    if name is None:
        return None
    p = Path(out_dir) / name
    if p.exists():
        return None
    extra = {
        "tag": dict(parts=[], contacts=[], files={}, warnings=[]),
        "view export": dict(kind="solid", mode="nominal", glb=None, warnings=[]),
        "view preview": dict(kind="solid", mode="preview", glb=None, warnings=[]),
        "asm parts": dict(assem=None, bodies=[], parts=[], recommend=[], warnings=[]),
        "asm check": dict(rows=[], file_checks=None, glb=None, warnings=[]),
        "asm write": dict(files=[], nodes_written=0),
        "shell view export": dict(kind="shell", mode="nominal", glb=None, warnings=[]),
        "shell view preview": dict(kind="shell", mode="preview", glb=None, warnings=[]),
        "cushion write": dict(out_rad=None, warnings=[]),
    }.get(cmd, {})
    doc = mk(status="FAIL", code=code, category=CODE_CATEGORY.get(code), message=message, **extra)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{name}.{os.getpid()}")
    tmp.write_text(dumps(doc), encoding="utf-8")
    os.replace(tmp, p)
    return p.name


def dispatch(args, rep) -> int:
    if args.cmd == "extract":
        from . import extract

        return extract.run(args, rep)
    if args.cmd == "tag":
        from . import tag

        return tag.run(args, rep)
    if args.cmd == "update":
        from . import update

        return update.run(args, rep)
    if args.cmd == "morph":
        from . import morph

        return morph.run(args, rep)
    if args.cmd == "check":
        from . import check

        return check.run(args, rep)
    if args.cmd == "run":
        from . import runner

        return runner.run(args, rep)
    if args.cmd == "props":
        from . import props

        return props.run(args, rep)
    if args.cmd == "map":
        from . import paramap

        return paramap.run(args, rep)
    if args.cmd == "view":
        from . import view

        return view.run(args, rep)
    if args.cmd == "selftest":
        from . import selftest

        return selftest.run(args, rep)
    if args.cmd == "cushion":
        from . import cushion

        return cushion.run(args, rep)
    if args.cmd == "asm":
        from . import asm

        return asm.run(args, rep)
    if args.cmd == "shell":
        from .shell.cli import dispatch as shell_dispatch

        return shell_dispatch(args, rep)
    return 2


def guarded(args, rep) -> tuple[int, str | None, str | None]:
    """Run one command with the section 5.4 error mapping: (exit code, failure code, message)."""
    from .common import EXIT_INTERNAL, EXIT_INTERRUPTED, PaicadError

    try:
        return dispatch(args, rep), None, None
    except PaicadError as e:
        rep.warn(f"{e.code}: {e.message}")
        report = None
        if e.code != "GEOM_OUTPUT_EXISTS" and not (args.cmd in ("morph", "shell") and getattr(args, "sweep", False)):
            cmd = {
                "props": f"props {getattr(args, 'props_cmd', '')}",
                "shell": f"shell {getattr(args, 'shell_cmd', '')}" + (f" {getattr(args, 'view_cmd', '')}" if getattr(args, "shell_cmd", "") == "view" else ""),
                "view": f"view {getattr(args, 'view_cmd', '')}",
                "cushion": f"cushion {getattr(args, 'cushion_cmd', '')}",
                "asm": f"asm {getattr(args, 'asm_cmd', '')}",
            }.get(args.cmd, args.cmd)
            report = _fail_report(cmd, args.out_dir, e.code, e.message)
        rep.result("FAIL", e.code, report)
        return e.exit_code, e.code, e.message
    except KeyboardInterrupt:
        rep.warn("interrupted")
        if getattr(args, "_nested", False):
            raise
        return EXIT_INTERRUPTED, None, "interrupted"
    except Exception as e:  # noqa: BLE001 - contract: GEOM_INTERNAL with traceback on stderr/log
        tb = traceback.format_exc()
        rep.warn(tb)
        rep.result("FAIL", "GEOM_INTERNAL", None)
        print(f"GEOM_INTERNAL: {e.__class__.__name__}: {e}", file=sys.stderr)
        return EXIT_INTERNAL, "GEOM_INTERNAL", f"{e.__class__.__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 2
    missing = _mesh_source_missing(args)
    if missing:
        parser.error(f"the following arguments are required: {', '.join(missing)} ({MESH_HELP})")
    if args.cmd == "version":
        v = versions()
        print(json.dumps(v) if args.json else " ".join(f"{k} {val}" for k, val in v.items()))
        return 0
    if getattr(args, "threads", None) is None:
        try:
            args.threads = int(os.environ.get("PAICAD_THREADS", "4"))
        except ValueError:
            args.threads = 4
    if hasattr(signal, "SIGBREAK"):  # Windows CTRL_BREAK -> KeyboardInterrupt
        signal.signal(signal.SIGBREAK, signal.default_int_handler)  # type: ignore[attr-defined]

    from .common import Reporter

    if args.cmd == "run" or (args.cmd == "shell" and args.shell_cmd == "run"):
        args.out_dir = args.check_dir  # run-level log and run.json live with the final stage
    out_dir = Path(args.out_dir)
    rep = Reporter(out_dir)
    rep.log(f"argv: {' '.join(sys.argv[1:] if argv is None else argv)}")
    rep.log("versions: " + json.dumps(versions()))
    try:
        return guarded(args, rep)[0]
    finally:
        rep.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
