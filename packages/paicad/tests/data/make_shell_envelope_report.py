"""Golden SM1 shell envelope report generator (shell-morph sections 7.1, 9.2 4C-env).

Builds the virtual sheet-metal golden (``make_synthetic_shell.py``), then runs fixed-scan -> extract -> tag ->
nominal update -> ``shell morph --sweep`` with **default options and default steps** (all parameters, depth /
width 5..50 %, position 1..10 mm) and returns the sweep's ``report_envelope.md`` / ``report_envelope.csv``.
The committed copies live in ``packages/paicad/tests/golden/geometry/SM1/``; ``test_shell_envelope.py``
regenerates them and requires byte identity after blanking the ``engine_version`` / ``sweep_id`` lines (same
rule as G1, :func:`make_envelope_report.normalize_report`).

Usage: python make_shell_envelope_report.py [--write]   (``--write`` refreshes the committed files)
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN_DIR = HERE.parent / "golden" / "geometry" / "SM1"
REPORT_FILES = ("report_envelope.md", "report_envelope.csv")


def _cli(*argv) -> str:
    from paicad.cli import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([str(a) for a in argv])
    if code != 0:
        raise RuntimeError(f"paicad {' '.join(map(str, argv[:2]))} failed ({code}):\n{buf.getvalue()}")
    return buf.getvalue()


def generate(work: Path, golden: dict | None = None) -> dict[str, bytes]:
    """Run the default shell sweep in ``work``; ``golden`` = an already prepared shell golden (conftest
    ``shell_golden``: fixed / extract / tag / nominal update) to reuse, else everything is built here."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    work = Path(work)
    if golden is None:
        from data.make_synthetic_shell import make_all

        g = make_all(work / "sm1")
        out = work / "out"
        fx, ex, tg, up = out / "fixed", out / "extract", out / "tag", out / "update0"
        _cli("shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", fx, "--parts", "2001")
        _cli("shell", "extract", "--cad", g["step"], "--assem-dir", g["assem"], "--out-dir", ex, "--no-png")
        feats = ex / "shell_features.json"
        _cli("shell", "tag", "--cad", g["step"], "--features", feats, "--assem-dir", g["assem"], "--fixed-dir", fx, "--out-dir", tg)
        vals = work / "nominal_values.json"
        vals.write_text('{"schema_version": 1, "values": {}}', encoding="utf-8")
        _cli("shell", "update", "--cad", g["step"], "--features", feats, "--values", vals, "--fixed-dir", fx, "--out-dir", up)
        assem = g["assem"]
    else:
        fx, feats, tg, up, assem = golden["fixed_dir"], golden["features_path"], golden["tag_dir"], golden["update0"], golden["assem"]
    sw = work / "sweep"
    _cli("shell", "morph", "--sweep", "--assem-dir", assem, "--tag-dir", tg, "--fixed-dir", fx, "--features", feats, "--update-dir", up, "--out-dir", sw)
    return {name: (sw / name).read_bytes() for name in REPORT_FILES}


def main(argv: list[str]) -> int:
    from make_envelope_report import normalize_report

    with tempfile.TemporaryDirectory(prefix="paicad_sm1_") as tmp:
        rep = generate(Path(tmp))
    if "--write" in argv:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        for name, data in rep.items():
            (GOLDEN_DIR / name).write_bytes(data)
        print(f"wrote {', '.join(REPORT_FILES)} to {GOLDEN_DIR}")
        return 0
    same = all((GOLDEN_DIR / n).is_file() and normalize_report((GOLDEN_DIR / n).read_bytes()) == normalize_report(d) for n, d in rep.items())
    print("identical" if same else "DIFFERENT (run with --write to refresh)")
    return 0 if same else 1


if __name__ == "__main__":  # pragma: no cover
    sys.path.insert(0, str(HERE))
    sys.exit(main(sys.argv[1:]))
