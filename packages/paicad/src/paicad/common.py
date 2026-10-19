"""Shared CLI conventions (contract sections 5.2, 5.4, 17.3, 18.4).

Messages are English technical text only; user-facing wording is the platform's job.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__

SCHEMA_VERSION = 1
ENGINE = "native"

# exit codes (section 5.4)
EXIT_OK = 0
EXIT_ARGS = 2
EXIT_INPUT = 3
EXIT_CAD = 10
EXIT_CHECK = 11
EXIT_TAG = 12
EXIT_EXTRACT_EMPTY = 13
EXIT_INTERNAL = 20
EXIT_INTERRUPTED = 130

CODE_EXIT = {
    "GEOM_INPUT_INVALID": EXIT_INPUT,
    "GEOM_OUTPUT_EXISTS": EXIT_INPUT,
    "RENUM_CSV_MISSING": EXIT_INPUT,
    "PARAM_NAME_CONFLICT": EXIT_INPUT,
    "GEOM_CAD_FAILED": EXIT_CAD,
    "GEOM_TOPOLOGY_CHANGED": EXIT_CAD,
    "GEOM_BODY_MAP_FAILED": EXIT_TAG,
    "GEOM_BASELINE_MISMATCH": EXIT_TAG,
    "GEOM_UNSUPPORTED_ELEMENT": EXIT_TAG,
    "GEOM_TAG_FAILED": EXIT_TAG,
    "GEOM_EXTRACT_EMPTY": EXIT_EXTRACT_EMPTY,
    "GEOM_INTERFERENCE": EXIT_CHECK,
    "GEOM_QUALITY": EXIT_CHECK,
    "GEOM_MORPH_FAILED": EXIT_CHECK,
    "GEOM_DEVIATION": EXIT_CHECK,
    "GEOM_PARAM_MISMATCH": EXIT_CHECK,
    "GEOM_TIE_PROJECTION": EXIT_CHECK,
    "GEOM_INC_FORMAT": EXIT_INTERNAL,
    "GEOM_INTERNAL": EXIT_INTERNAL,
}

CODE_CATEGORY = {
    "GEOM_CAD_FAILED": "CAD_FAILED",
    "GEOM_TOPOLOGY_CHANGED": "CAD_FAILED",
    "GEOM_INTERFERENCE": "INTERFERENCE",
    "GEOM_QUALITY": "QUALITY",
    "GEOM_MORPH_FAILED": "QUALITY",
    "GEOM_DEVIATION": "DEVIATION",
    "GEOM_PARAM_MISMATCH": "DEVIATION",
    "GEOM_TIE_PROJECTION": "TIE",
    "GEOM_INC_FORMAT": "INTERNAL",
    "GEOM_INPUT_INVALID": "INPUT",
    "GEOM_OUTPUT_EXISTS": "INPUT",
    "RENUM_CSV_MISSING": "INPUT",
    "GEOM_BODY_MAP_FAILED": "PREP",
    "GEOM_BASELINE_MISMATCH": "PREP",
    "GEOM_UNSUPPORTED_ELEMENT": "PREP",
    "GEOM_TAG_FAILED": "PREP",
    "GEOM_EXTRACT_EMPTY": "PREP",
    "GEOM_INTERNAL": "INTERNAL",
}


class PaicadError(Exception):
    """A contract failure: ``code`` from the section 6.5 table, English ``message``."""

    def __init__(self, code: str, message: str, exit_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code if exit_code is not None else CODE_EXIT.get(code, EXIT_INTERNAL)


def envelope(**body: Any) -> dict:
    """Top-level keys required on every paicad JSON output (section 17.3)."""
    out = {"schema_version": SCHEMA_VERSION, "engine": ENGINE, "engine_version": __version__}
    out.update(body)
    return out


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False, allow_nan=False) + "\n"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rnd(x: float, nd: int = 6) -> float:
    """Deterministic rounding for reported measurements (-0.0 normalized)."""
    v = round(float(x), nd)
    return 0.0 if v == 0 else v


def vec(a, nd: int = 6) -> list[float]:
    return [rnd(x, nd) for x in a]


class OutDir:
    """Output folder guard: never overwrite (GEOM_OUTPUT_EXISTS), stage in .tmp_<pid>, then os.replace."""

    def __init__(self, path: str | Path, outputs: list[str]):
        self.path = Path(path)
        self.outputs = outputs
        self.tmp = self.path / f".tmp_{os.getpid()}"

    def prepare(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        existing = [o for o in self.outputs if (self.path / o).exists()]
        if existing:
            raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {', '.join(existing[:10])}")
        self.tmp.mkdir(parents=True, exist_ok=True)

    def write_text(self, rel: str, text: str) -> Path:
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return p

    def tmp_path(self, rel: str) -> Path:
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def commit(self, rels: list[str]) -> None:
        for rel in rels:
            dst = self.path / rel
            if dst.exists():
                raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {rel}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.tmp / rel, dst)
        self.cleanup()

    def cleanup(self) -> None:
        # only our own staging folder; left in place on failure (section 5.2)
        try:
            if self.tmp.exists() and not any(p.is_file() for p in self.tmp.rglob("*")):
                shutil.rmtree(self.tmp)
        except OSError:
            pass


class Reporter:
    """stdout PROGRESS/RESULT lines + paicad.log copy (append, never truncated)."""

    def __init__(self, out_dir: Path | None, stdout=None, stderr=None):
        self.out_dir = out_dir
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self._log = None
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            self._log = open(out_dir / "paicad.log", "a", encoding="utf-8", newline="\n")
            self.log(f"paicad {__version__} started {_dt.datetime.now().isoformat(timespec='seconds')}")

    def log(self, line: str) -> None:
        if self._log:
            self._log.write(line.rstrip("\n") + "\n")
            self._log.flush()

    def progress(self, pct: int, msg: str) -> None:
        line = f"PAICAD PROGRESS {int(pct)} {msg}"
        print(line, file=self.stdout, flush=True)
        self.log(line)

    def warn(self, msg: str) -> None:
        print(msg, file=self.stderr, flush=True)
        self.log("WARN " + msg)

    def result(self, status: str, code: str | None, report: str | None) -> None:
        line = f"PAICAD RESULT {status} {code or '-'} {report or '-'}"
        print(line, file=self.stdout, flush=True)
        self.log(line)

    def close(self) -> None:
        if self._log:
            self._log.close()
            self._log = None


class StageReporter(Reporter):
    """Reporter of one stage inside ``paicad run`` / ``selftest``: own log in the stage folder, progress
    rescaled into [lo, hi] of the parent, stage RESULT shown as a progress line (the parent prints the
    single final ``PAICAD RESULT`` line)."""

    def __init__(self, out_dir: Path, parent: Reporter, stage: str, lo: int, hi: int):
        super().__init__(out_dir, stdout=parent.stdout, stderr=parent.stderr)
        self.parent, self.stage, self.lo, self.hi = parent, stage, lo, hi

    def progress(self, pct: int, msg: str) -> None:
        self.log(f"PAICAD PROGRESS {int(pct)} {msg}")
        self.parent.progress(self.lo + int((self.hi - self.lo) * max(0, min(100, int(pct))) / 100), f"{self.stage}: {msg}")

    def result(self, status: str, code: str | None, report: str | None) -> None:
        self.log(f"PAICAD RESULT {status} {code or '-'} {report or '-'}")
        self.parent.progress(self.hi, f"{self.stage} {status} {code or '-'}")
