"""CAD loading + body/component correspondence shared by extract and tag."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import bodymap
from .common import PaicadError, sha256_file
from .kernel import BodyGeom, CadInputError, load_cad
from .mesh.radioss import RenumRow


@dataclass
class CadSet:
    mode: str  # "single" | "parts"
    path: Path
    bodies: list[BodyGeom]
    files: list[dict]  # [{"rel", "sha256"}]

    def by_name(self) -> dict[str, BodyGeom]:
        return {b.name: b for b in self.bodies if b.name is not None}


def load(cad: str | Path) -> CadSet:
    p = Path(cad)
    try:
        mode, bodies = load_cad(p)
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None
    if mode == "single":
        files = [{"rel": p.name, "sha256": sha256_file(p)}]
    else:
        files = [
            {"rel": f"{p.name}/{f.name}", "sha256": sha256_file(f)}
            for f in sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() in (".step", ".stp"))
        ]
    return CadSet(mode, p, bodies, files)


def correspond(cad: CadSet, renum: list[RenumRow] | None, body_map_path: str | None) -> list[tuple[BodyGeom, str, int | None]]:
    """[(body, part, renum_row)] in component order (RENUM row order, else body order)."""
    explicit = bodymap.read_body_map(body_map_path)
    names = [b.name for b in cad.bodies]
    if renum is None:
        if any(n is None for n in names):
            bodymap.match(names, [], explicit)  # raises the unnamed-body error
        parts = [explicit.get(n, n) for n in names]
        if len(set(parts)) != len(parts):
            raise PaicadError("GEOM_BODY_MAP_FAILED", "two bodies map to the same component name")
        return [(b, p, None) for b, p in zip(cad.bodies, parts)]
    m = bodymap.match(names, [r.part for r in renum], explicit)
    inv = {v: k for k, v in m.items()}
    byname = cad.by_name()
    return [(byname[inv[r.part]], r.part, r.row) for r in sorted(renum, key=lambda r: r.row)]
