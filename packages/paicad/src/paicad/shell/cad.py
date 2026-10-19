"""Mid-surface CAD loading and body <-> shell /PART correspondence (shell-morph section 4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..bodymap import normalize, read_body_map
from ..common import PaicadError, sha256_file
from ..kernel import CadInputError, load_sheet_brep, load_sheets
from .assem import SHELL_KW, Assembly


@dataclass
class SheetSet:
    mode: str
    path: Path
    bodies: list
    files: list[dict]

    def by_name(self) -> dict:
        return {b.name: b for b in self.bodies if b.name is not None}


def load(cad: str | Path) -> SheetSet:
    p = Path(cad)
    try:
        mode, bodies = load_sheets(p)
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None
    if mode == "single":
        files = [{"rel": p.name, "sha256": sha256_file(p)}]
    else:
        files = [{"rel": f"{p.name}/{f.name}", "sha256": sha256_file(f)} for f in sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() in (".step", ".stp"))]
    names = [b.name for b in bodies]
    if any(n is None for n in names):
        raise PaicadError("GEOM_BODY_MAP_FAILED", "a sheet body has no name (no XDE label) - use per-part STEP files (file name = /PART title)")
    if len(set(names)) != len(names):
        raise PaicadError("GEOM_BODY_MAP_FAILED", f"duplicate body names: {', '.join(sorted({n for n in names if names.count(n) > 1})[:10])}")
    return SheetSet(mode, p, bodies, files)


def load_sample(path: str | Path, names: list[str]) -> list:
    try:
        return load_sheet_brep(path, names)
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None


def correspond(names: list[str], asm: Assembly | None, body_map_path: str | None) -> dict[str, tuple[int | None, str]]:
    """{body: (part_id, title)}. Without an assembly: (None, body name). Rules: explicit map (title or
    ``PART:<id>``), exact, case-insensitive, normalized title; shell parts may stay unmatched."""
    explicit = read_body_map(body_map_path)
    if asm is None:
        return {n: (None, explicit.get(n, n)) for n in names}
    parts = sorted({b.part for b in asm.blocks if b.keyword in SHELL_KW})
    title = {p: (asm.parts.get(p) or {}).get("title", "") for p in parts}
    free = list(parts)
    out: dict[str, tuple[int | None, str]] = {}

    def take(n, p):
        out[n] = (p, title[p])
        free.remove(p)

    for n in names:
        v = explicit.get(n)
        if v is None:
            continue
        if v.upper().startswith("PART:"):
            try:
                pid = int(v[5:])
            except ValueError:
                raise PaicadError("GEOM_INPUT_INVALID", f"body map value {v!r} is not PART:<id>") from None
            if pid not in free:
                raise PaicadError("GEOM_BODY_MAP_FAILED", f"body map: {n} -> part {pid} is not a free shell part")
            take(n, pid)
        else:
            hits = [p for p in free if title[p] == v]
            if len(hits) != 1:
                raise PaicadError("GEOM_BODY_MAP_FAILED", f"body map: {n} -> title {v!r} matches {len(hits)} shell parts (use PART:<id>)")
            take(n, hits[0])
    for rule in (lambda s: s, lambda s: s.lower(), normalize):
        for n in names:
            if n in out:
                continue
            hits = [p for p in free if rule(title[p]) == rule(n)]
            if len(hits) == 1:
                take(n, hits[0])
    left = [n for n in names if n not in out]
    if left:
        raise PaicadError("GEOM_BODY_MAP_FAILED", f"unmatched bodies: [{', '.join(left[:10])}]; shell parts: [{', '.join(f'{p}:{title[p]}' for p in free[:10])}]")
    for n, (pid, _) in out.items():
        other = [b for b in asm.part_blocks(pid) if b.keyword not in SHELL_KW]
        if other:
            raise PaicadError("SHELL_UNSUPPORTED_ELEMENT", f"part {pid} ({n}): {sum(len(b.ids) for b in other)} non-shell elements (/{other[0].keyword})")
    return out
