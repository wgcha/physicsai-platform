"""Shell report conventions (shell-morph section 4: GE JSON rules + top-level ``kind: "shell"``)."""

from __future__ import annotations

from typing import Any

from .. import __version__
from ..common import ENGINE, SCHEMA_VERSION


def shell_envelope(**body: Any) -> dict:
    out = {"schema_version": SCHEMA_VERSION, "kind": "shell", "engine": ENGINE, "engine_version": __version__}
    out.update(body)
    return out


# ------------------------------------------------------------------ features document / values
import math  # noqa: E402
from pathlib import Path  # noqa: E402

from ..common import PaicadError  # noqa: E402
from ..update import read_json  # noqa: E402

TYPE_ABBR = {"BEAD_DEPTH": "BEAD_D", "BEAD_POS_U": "BEAD_U", "BEAD_POS_V": "BEAD_V", "BEAD_WIDTH": "BEAD_W"}
TYPE_ORDER = ("BEAD_DEPTH", "BEAD_POS_U", "BEAD_POS_V", "BEAD_WIDTH")
POSITION_TYPES = ("BEAD_POS_U", "BEAD_POS_V")
OP = {"BEAD_DEPTH": "BEAD_DEPTH", "BEAD_POS_U": "BEAD_TRANSLATE", "BEAD_POS_V": "BEAD_TRANSLATE", "BEAD_WIDTH": "BEAD_WIDTH"}


def load_shell_features(path: str | Path) -> dict:
    doc = read_json(path, "features file")
    if doc.get("schema_version") != 1 or doc.get("kind") != "shell":
        raise PaicadError("GEOM_INPUT_INVALID", "features file is not a shell_features.json (kind shell, schema_version 1)")
    for k in ("parts", "beads", "features"):
        if not isinstance(doc.get(k), list):
            raise PaicadError("GEOM_INPUT_INVALID", f"shell_features.json: missing {k}")
    return doc


def split_groups(doc: dict, o: dict) -> set[str]:
    ids = {g["id"] for g in doc.get("groups") or []}
    split = set(o.get("symmetry_split") or [])
    unknown = sorted(split - ids)
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"symmetry_split: unknown group ids: {', '.join(unknown[:10])}")
    return split


def param_keys(doc: dict, o: dict) -> list[str]:
    split = split_groups(doc, o)
    grp = {g["id"]: g for g in doc.get("groups") or []}
    keys = []
    for f in doc["features"]:
        g = f.get("group")
        if g is None or g in split or grp.get(g, {}).get("parameter") == f["name"]:
            keys.append(f["name"])
    return keys


def nominal_of(doc: dict, name: str) -> float:
    for f in doc["features"]:
        if f["name"] == name:
            return float(f["nominal"])
    raise PaicadError("GEOM_INPUT_INVALID", f"unknown parameter: {name}")


def feature_values(doc: dict, o: dict, values: dict[str, float]) -> dict[str, float]:
    split = split_groups(doc, o)
    grp = {g["id"]: g for g in doc.get("groups") or []}
    out = {}
    for f in doc["features"]:
        g = f.get("group")
        key = grp[g]["parameter"] if g is not None and g not in split else f["name"]
        out[f["name"]] = float(values.get(key, nominal_of(doc, key)))
    return out


def load_values(path: str | Path, doc: dict, o: dict) -> dict[str, float]:
    return values_from(read_json(path, "values file"), doc, o)


def values_from(v: dict, doc: dict, o: dict) -> dict[str, float]:
    """Validated values of a parsed values document (``load_values``; ``view grid`` cells use the same rules)."""
    if not isinstance(v, dict) or v.get("schema_version", 1) != 1 or not isinstance(v.get("values"), dict):
        raise PaicadError("GEOM_INPUT_INVALID", "values file must be {schema_version: 1, values: {name: number}}")
    keys = param_keys(doc, o)
    unknown = sorted(set(v["values"]) - set(keys))
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"unknown parameter names in values: {', '.join(unknown[:10])}")
    out = {}
    for k, x in v["values"].items():
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise PaicadError("GEOM_INPUT_INVALID", f"value of {k} must be a finite number")
        out[k] = float(x)
    return out
