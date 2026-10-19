"""Body <-> component (RENUM part) matching (contract section 4.1)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import PaicadError

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def normalize(name: str) -> str:
    """Non-alphanumerics -> '_', collapse, strip, upper case."""
    return _NON_ALNUM.sub("_", name).strip("_").upper()


def read_body_map(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read body map: {ex.__class__.__name__}") from None
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("map"), dict):
        raise PaicadError("GEOM_INPUT_INVALID", "body map must be {schema_version: 1, map: {body: part}}")
    return {str(k): str(v) for k, v in data["map"].items()}


def match(bodies: list[str | None], parts: list[str], explicit: dict[str, str] | None = None) -> dict[str, str]:
    """Return {body name: part}. Every body and every part must be matched exactly once.

    Rules, first hit wins: (1) explicit map, (2) exact, (3) case-insensitive, (4) normalized.
    """
    if any(b is None for b in bodies):
        raise PaicadError(
            "GEOM_BODY_MAP_FAILED",
            "a body has no name (no XDE label) - use per-component STEP files (one file per component, file name = component name)",
        )
    names = [b for b in bodies if b is not None]
    if len(set(names)) != len(names):
        dup = sorted({b for b in names if names.count(b) > 1})
        raise PaicadError("GEOM_BODY_MAP_FAILED", f"duplicate body names: {', '.join(dup[:10])}")
    explicit = explicit or {}
    result: dict[str, str] = {}
    free_parts = list(parts)

    def take(body: str, part: str) -> None:
        result[body] = part
        free_parts.remove(part)

    for b in names:
        p = explicit.get(b)
        if p is not None and p in free_parts:
            take(b, p)
    for rule in (lambda s: s, lambda s: s.lower(), normalize):
        for b in names:
            if b in result:
                continue
            key = rule(b)
            hits = [p for p in free_parts if rule(p) == key]
            if len(hits) == 1:
                take(b, hits[0])
    left_b = [b for b in names if b not in result]
    if left_b or free_parts:
        raise PaicadError(
            "GEOM_BODY_MAP_FAILED",
            f"unmatched bodies: [{', '.join(left_b[:10])}]; unmatched parts: [{', '.join(free_parts[:10])}]",
        )
    return result
