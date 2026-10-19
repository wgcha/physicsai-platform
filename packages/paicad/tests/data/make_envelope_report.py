"""Golden G1 envelope report generator (contract sections 9 stage 2, 11.2).

Builds the development golden (virtual cushion, ``make_synthetic.py``), then runs
extract -> tag -> nominal update -> ``morph --sweep`` with **default options and default steps**
(all parameters, dimension 5..50 %, position 1..10 mm) and returns the sweep's
``report_envelope.md`` / ``report_envelope.csv``. The committed copies live in
``packages/paicad/tests/golden/geometry/G1/`` (repository path of the contract's
``golden/geometry/G1/``, kept under the package); ``test_v050.py`` regenerates them and
requires byte identity.

The STEP file written by the CAD exporter carries process-dependent bytes: the header timestamp
(``FILE_NAME`` date) and the ``NEXT_ASSEMBLY_USAGE_OCCURRENCE`` ids (a process-wide counter, so a
second export in the same process numbers them differently, and a longer id can wrap the line).
Both are pinned before extract so that
the input hashes, and thus the ``sweep_id`` printed in the report, are stable.

Usage: python make_envelope_report.py [--write]   (``--write`` refreshes the committed files)
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN_DIR = HERE.parent / "golden" / "geometry" / "G1"
REPORT_FILES = ("report_envelope.md", "report_envelope.csv")
_STEP_DATE = re.compile(rb"(FILE_NAME\('[^']*',')[^']*(')")
PINNED_DATE = b"2026-01-01T00:00:00"
_NAUO = re.compile(rb"NEXT_ASSEMBLY_USAGE_OCCURRENCE\('[^']*'(.*?);", re.S)
_WRAP = re.compile(rb"\r?\n\s*")


def _cli(*argv) -> str:
    from paicad.cli import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([str(a) for a in argv])
    if code != 0:
        raise RuntimeError(f"paicad {argv[0]} failed ({code}):\n{buf.getvalue()}")
    return buf.getvalue()


def normalize_step(step: Path) -> None:
    data = step.read_bytes()
    new, n = _STEP_DATE.subn(lambda m: m.group(1) + PINNED_DATE + m.group(2), data, count=1)
    if n != 1:
        raise RuntimeError("STEP FILE_NAME header not found")
    # renumber in file order and undo the line wrap a longer id may have caused
    counter = iter(range(1, 1 << 30))
    new = _NAUO.sub(lambda m: b"NEXT_ASSEMBLY_USAGE_OCCURRENCE('%d'" % next(counter) + _WRAP.sub(b"", m.group(1)) + b";", new)
    step.write_bytes(new)


def generate(work: Path) -> dict[str, bytes]:
    """Run the full default sweep in ``work`` (must be empty or absent); return report bytes."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from make_synthetic import make_all

    work = Path(work)
    g = make_all(work / "synthetic")
    normalize_step(g["step"])
    out = work / "out"
    _cli("extract", "--cad", g["step"], "--out-dir", out / "extract", "--renum-csv", g["renum"], "--no-png")
    feats = out / "extract" / "parameter_features.json"
    _cli(
        "tag", "--cad", g["step"], "--features", feats, "--baseline-inc", g["baseline"], "--renum-csv", g["renum"],
        "--assem-dir", g["assem"], "--out-dir", out / "tag",
    )
    vals = work / "nominal_values.json"
    vals.write_text('{"schema_version": 1, "values": {}}', encoding="utf-8")
    _cli("update", "--cad", g["step"], "--features", feats, "--values", vals, "--tag-dir", out / "tag", "--out-dir", out / "update")
    _cli(
        "morph", "--sweep", "--baseline-inc", g["baseline"], "--tag-dir", out / "tag", "--features", feats,
        "--update-dir", out / "update", "--out-dir", out / "sweep",
    )
    return {name: (out / "sweep" / name).read_bytes() for name in REPORT_FILES}


def main(argv: list[str]) -> int:
    with tempfile.TemporaryDirectory(prefix="paicad_g1_") as tmp:
        rep = generate(Path(tmp))
    if "--write" in argv:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        for name, data in rep.items():
            (GOLDEN_DIR / name).write_bytes(data)
        print(f"wrote {', '.join(REPORT_FILES)} to {GOLDEN_DIR}")
        return 0
    same = all((GOLDEN_DIR / n).is_file() and (GOLDEN_DIR / n).read_bytes() == d for n, d in rep.items())
    print("identical" if same else "DIFFERENT (run with --write to refresh)")
    return 0 if same else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
