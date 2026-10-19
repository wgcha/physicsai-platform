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

EPILOG = "Exit codes: 0 ok, 2 arguments, 3 input, 10 CAD, 11 check/morph, 12 tag, 13 extract empty, 20 internal, 130 interrupted."


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
    e.add_argument("--options")
    e.add_argument("--no-png", action="store_true")
    e.add_argument("--threads", type=int)

    t = sub.add_parser("tag", help="classify baseline mesh nodes onto the nominal B-rep", allow_abbrev=False)
    for a in ("--cad", "--features", "--baseline-inc", "--renum-csv", "--assem-dir", "--out-dir"):
        t.add_argument(a, required=True)
    t.add_argument("--body-map")
    t.add_argument("--options")
    t.add_argument("--threads", type=int)
    return p


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


def _tag_fail_report(out_dir: str, code: str, message: str) -> str | None:
    from .common import CODE_CATEGORY, dumps, envelope

    p = Path(out_dir) / "tag.json"
    if p.exists():
        return None
    doc = envelope(status="FAIL", code=code, category=CODE_CATEGORY.get(code), message=message, parts=[], contacts=[], files={}, warnings=[])
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".tag.json.{os.getpid()}")
    tmp.write_text(dumps(doc), encoding="utf-8")
    os.replace(tmp, p)
    return p.name


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd is None:
        _parser().print_help()
        return 2
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

    from .common import EXIT_INTERNAL, EXIT_INTERRUPTED, PaicadError, Reporter

    out_dir = Path(args.out_dir)
    rep = Reporter(out_dir)
    rep.log(f"argv: {' '.join(sys.argv[1:] if argv is None else argv)}")
    rep.log("versions: " + json.dumps(versions()))
    try:
        if args.cmd == "extract":
            from . import extract

            return extract.run(args, rep)
        if args.cmd == "tag":
            from . import tag

            return tag.run(args, rep)
        return 2
    except PaicadError as e:
        rep.warn(f"{e.code}: {e.message}")
        report = None
        if args.cmd == "tag" and e.code != "GEOM_OUTPUT_EXISTS":
            report = _tag_fail_report(args.out_dir, e.code, e.message)
        rep.result("FAIL", e.code, report)
        return e.exit_code
    except KeyboardInterrupt:
        rep.warn("interrupted")
        return EXIT_INTERRUPTED
    except Exception as e:  # noqa: BLE001 - contract: GEOM_INTERNAL with traceback on stderr/log
        tb = traceback.format_exc()
        rep.warn(tb)
        rep.result("FAIL", "GEOM_INTERNAL", None)
        print(f"GEOM_INTERNAL: {e.__class__.__name__}: {e}", file=sys.stderr)
        return EXIT_INTERNAL
    finally:
        rep.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
