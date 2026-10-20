"""``paicad shell <verb>`` argument parsing and dispatch (shell-morph sections 5.1, 5.2)."""

from __future__ import annotations

import argparse

REPORTS = {
    "fixed-scan": "shell_scan.json",
    "tag": "shell_tag.json",
    "update": "shell_update.json",
    "morph": "shell_morph.json",
    "check": "shell_check.json",
    "run": "shell_run.json",
    "view export": "view_manifest.json",
    "view preview": "preview_manifest.json",
}


def _req(p: argparse.ArgumentParser, *names: str) -> None:
    for a in names:
        p.add_argument(a, required=True)


def add_parser(sub) -> None:
    sh = sub.add_parser("shell", help="shell (sheet-metal bead) morphing: fixed-scan | extract | tag | update | morph | check | run | selftest | view", allow_abbrev=False)
    ss = sh.add_subparsers(dest="shell_cmd", metavar="verb", required=True)

    f = ss.add_parser("fixed-scan", help="fixed node set (tie / rigid / BC / shared nodes) of the shell parts -> shell_scan.json", allow_abbrev=False)
    _req(f, "--assem-dir", "--out-dir")
    f.add_argument("--parts", help="comma-separated part ids (without --parts/--features: list the shell parts only)")
    f.add_argument("--features", help="shell_features.json whose parts are scanned")
    f.add_argument("--options")
    f.add_argument("--threads", type=int)

    e = ss.add_parser("extract", help="recognize beads of the mid-surface STEP -> parameter_extracted.xml, shell_features.json", allow_abbrev=False)
    _req(e, "--cad", "--out-dir")
    e.add_argument("--assem-dir", help="assembly folder: body <-> /PART correspondence and fixed-region overlap warnings")
    e.add_argument("--body-map")
    e.add_argument("--options")
    e.add_argument("--no-png", action="store_true")
    e.add_argument("--threads", type=int)

    t = ss.add_parser("tag", help="classify shell nodes onto the mid-surface B-rep -> shell_tag.json", allow_abbrev=False)
    _req(t, "--cad", "--features", "--assem-dir", "--fixed-dir", "--out-dir")
    t.add_argument("--body-map")
    t.add_argument("--options")
    t.add_argument("--threads", type=int)

    u = ss.add_parser("update", help="apply bead values to the nominal sheet -> sample.brep, shell_update.json", allow_abbrev=False)
    _req(u, "--cad", "--features", "--values", "--out-dir")
    u.add_argument("--fixed-dir", help="fixed-scan output: fixed-region pre-check")
    u.add_argument("--body-map")
    u.add_argument("--options")
    u.add_argument("--threads", type=int)

    m = ss.add_parser("morph", help="move shell node coordinates onto the sample sheet (or --sweep: morphing envelope)", allow_abbrev=False)
    _req(m, "--assem-dir", "--tag-dir", "--fixed-dir", "--features", "--update-dir", "--out-dir")
    m.add_argument("--solver", default=None, help="solver writer of the file copies (default radioss)")
    m.add_argument("--options")
    m.add_argument("--threads", type=int)
    m.add_argument("--sweep", action="store_true", help="1D parameter sweep -> envelope.json/csv")
    m.add_argument("--steps", default="5,10,20,30,40,50", help="sweep steps of depth/width parameters in percent of the nominal value")
    m.add_argument("--pos-steps", default="1,2,3,5,8,10", help="sweep steps of position parameters (BEAD_POS_U/V) in mm")
    m.add_argument("--params", help="comma-separated parameter names (default: all)")
    m.add_argument("--stop-after-fail", type=int, default=2)
    m.add_argument("--check", default="on", choices=["on", "off"])
    m.add_argument("--keep-steps", action="store_true")

    c = ss.add_parser("check", help="check the morphed shell mesh and write the file copies on PASS", allow_abbrev=False)
    _req(c, "--assem-dir", "--morph-dir", "--update-dir", "--tag-dir", "--fixed-dir", "--features", "--values", "--out-dir", "--out-files-dir")
    c.add_argument("--thickness", help='JSON {"schema_version":1,"parts":{"<part_id>":t}} (default: /PROP/TYPE1)')
    c.add_argument("--options")
    c.add_argument("--threads", type=int)

    r = ss.add_parser("run", help="shell update -> morph -> check in one call (stops at the first failing stage)", allow_abbrev=False)
    _req(r, "--cad", "--features", "--values", "--assem-dir", "--tag-dir", "--fixed-dir", "--update-dir", "--morph-dir", "--check-dir", "--out-files-dir")
    r.add_argument("--body-map")
    r.add_argument("--thickness")
    r.add_argument("--options")
    r.add_argument("--solver", default=None)
    r.add_argument("--threads", type=int)

    st = ss.add_parser("selftest", help="site acceptance kit for the shell path: numeric summary only", allow_abbrev=False)
    _req(st, "--cad", "--assem-dir", "--out-dir")
    st.add_argument("--variant-cad", help="changed mid-surface STEP (site variant) compared with update")
    st.add_argument("--variant-values", help="values.json of --variant-cad")
    st.add_argument("--body-map")
    st.add_argument("--options")
    st.add_argument("--envelope-steps", default="5,10")
    st.add_argument("--envelope-pos-steps", default="1,3")
    st.add_argument("--envelope-params")
    st.add_argument("--stop-after-fail", type=int, default=1)
    st.add_argument("--no-envelope", action="store_true")
    st.add_argument("--threads", type=int)

    add_view_parser(ss)


def add_view_parser(ss) -> None:
    """``paicad shell view export|preview`` (geometry-view.md section 5.1)."""
    vw = ss.add_parser("view", help="3D view (GLB) of the mid-surface sheet | bead preview", allow_abbrev=False)
    vs = vw.add_subparsers(dest="view_cmd", metavar="action", required=True)
    ve = vs.add_parser("export", help="nominal sheet -> view.glb + view_manifest.json (kind shell)", allow_abbrev=False)
    _req(ve, "--cad", "--features", "--out-dir")
    ve.add_argument("--fixed-dir", help="fixed-scan output: fixed node markers and clusters")
    ve.add_argument("--body-map")
    ve.add_argument("--view-options", help="view_options.json (tessellation tolerances, size limits)")
    ve.add_argument("--threads", type=int)
    vp = vs.add_parser("preview", help="values -> changed sheet preview.glb (+ morphed shell mesh) + preview_manifest.json", allow_abbrev=False)
    _req(vp, "--cad", "--features", "--values", "--out-dir")
    vp.add_argument("--fixed-dir", help="fixed-scan output: fixed-region pre-check and markers (required with --fe morph|check)")
    vp.add_argument("--body-map")
    vp.add_argument("--options", help="shell options.json (update / morph / check)")
    vp.add_argument("--view-options")
    vp.add_argument("--nominal-manifest", help="nominal view_manifest.json (nominal_ref and tessellation tolerances)")
    vp.add_argument("--fe", default="off", choices=["off", "morph", "check"])
    vp.add_argument("--assem-dir", help="assembly folder (required with --fe morph|check)")
    vp.add_argument("--tag-dir", help="shell tag output (required with --fe morph|check)")
    vp.add_argument("--thickness")
    vp.add_argument("--threads", type=int)


def dispatch(args, rep) -> int:
    v = args.shell_cmd
    if v == "fixed-scan":
        from . import fixed

        return fixed.run(args, rep)
    if v == "extract":
        from . import extract

        return extract.run(args, rep)
    if v == "tag":
        from . import tag

        return tag.run(args, rep)
    if v == "update":
        from . import update

        return update.run(args, rep)
    if v == "morph":
        if args.sweep:
            from . import sweep

            return sweep.run(args, rep)
        from . import morph

        return morph.run(args, rep)
    if v == "check":
        from . import check

        return check.run(args, rep)
    if v == "run":
        from . import runner

        return runner.run(args, rep)
    if v == "view":
        from . import view

        return view.run(args, rep)
    if v == "selftest":
        from . import selftest

        return selftest.run(args, rep)
    return 2
