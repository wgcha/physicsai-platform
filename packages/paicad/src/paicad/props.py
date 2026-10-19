"""``paicad props scan`` / ``paicad props apply`` - shell thickness parameters (contract section 11.1, stage 3S).

Only ``/PROP/TYPE1`` (= ``/PROP/SHELL``) thickness is a parameter. ``/PROP/TYPE9``, ``TYPE10``, ``TYPE11``
(SH_ORTH, SH_COMP, SH_SANDW) are listed with ``supported: false`` (PROP_UNSUPPORTED_TYPE).

Card layout (Radioss 2017+ input format, fixed width; free-format lines fall back to whitespace tokens):

* ``/PROP/TYPE1/prop_ID[/unit_ID]`` -> title line -> data line 1 (Ishell ...) -> data line 2 (hm hf hr dm dn)
  -> data line 3 ``N Istrain Thick Ashear . Ithick Iplas``; ``Thick`` = columns 21-40.
  Blank lines are data lines (all fields default); ``#``/``$`` lines are comments.
* ``/PART/part_ID`` -> title -> ``prop_ID mat_ID subset_ID Thick`` (prop_ID = columns 1-10, Thick = columns
  31-50; Thick != 0 overrides the PROP thickness for that part -> PROP_OVERRIDDEN_BY_PART).
* ``/SHELL/part_ID`` element lines ``shell_ID n1 n2 n3 n4 . phi Thick`` and ``/SH3N/part_ID``
  ``sh3n_ID n1 n2 n3 . . phi Thick``: element thickness = columns 81-100 (0 or blank = take the PROP).

apply writes copies of the PROP definition files into ``--out-dir`` (same relative paths) with only the
thickness field replaced (section 6.4 fixed-width value rules); the ``--assem-dir`` files are never written.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import options
from .bodymap import normalize
from .common import (
    CODE_CATEGORY,
    EXIT_OK,
    OutDir,
    PaicadError,
    Reporter,
    dumps,
    envelope,
    rnd,
    sha256_file,
)
from .mesh.radioss import _fmt
from .update import read_json

PROPS_JSON = "props.json"
APPLY_JSON = "props_apply.json"
PARAM_SUFFIX = "_SHELL_T"
NAME_MAX = 64
SUPPORTED = {"TYPE1": "SHELL", "SHELL": "SHELL"}
UNSUPPORTED = {"TYPE9": "SH_ORTH", "SH_ORTH": "SH_ORTH", "TYPE10": "SH_COMP", "SH_COMP": "SH_COMP", "TYPE11": "SH_SANDW", "SH_SANDW": "SH_SANDW"}
PROP_FIELDS = (0, 10, 20, 40, 60, 70, 80, 90)  # card 3 field starts; Thick = field 2 ([20, 40))
PROP_THICK = (2, 20, 40)  # (field index, start, end)
ELEM_FIELDS = (0, 10, 20, 30, 40, 50, 60, 80, 100)
PART_FIELDS = (0, 10, 20, 30, 50)
PART_THICK = (3, 30, 50)  # /PART card: prop_ID mat_ID subset_ID Thick
ELEM_THICK = {"SHELL": (6, 80, 100), "SH3N": (5, 80, 100)}  # free-format token index differs (3 nodes)
_TOK = re.compile(r"[^\s,]+")


@dataclass
class PropDef:
    id: int
    kind: str  # SHELL | SH_ORTH | SH_COMP | SH_SANDW
    keyword: str  # e.g. /PROP/TYPE1
    title: str
    file: str  # posix path relative to the assembly folder
    line: int  # 1-based keyword line
    thick_line: int | None = None  # 1-based line of the thickness card (TYPE1)
    thickness: float | None = None
    parts: list[tuple[int, str]] = field(default_factory=list)
    element_overrides: int = 0
    part_overrides: list[tuple[int, str, float]] = field(default_factory=list)  # parts whose /PART Thick != 0


# ------------------------------------------------------------------ field helpers
def _float(s: str) -> float:
    s = s.strip()
    if not s:
        return 0.0
    try:
        return float(s.replace("D", "E").replace("d", "e"))
    except ValueError:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot parse number {s[:20]!r}") from None


def _is_fixed(line: str, starts: tuple[int, ...]) -> bool:
    """Fixed-width line: no token crosses a field boundary and no field holds more than one token."""
    seen: set[int] = set()
    for m in _TOK.finditer(line):
        a, b = m.start(), m.end()
        k = max(i for i, s in enumerate(starts) if s <= a)
        if k + 1 < len(starts) and b > starts[k + 1]:
            return False
        if k in seen:
            return False
        seen.add(k)
    return True


def field_span(line: str, starts: tuple[int, ...], spec: tuple[int, int, int]) -> tuple[int, int]:
    """Column span [a, b) of the field: fixed columns when the line is fixed width, else the free-format
    token's span from the end of the previous token (section 6.4 field boundary rule)."""
    k, a, b = spec
    if _is_fixed(line, starts):
        return a, b
    toks = list(_TOK.finditer(line))
    if len(toks) <= k:
        return a, b  # short free-format line: the field is absent (default 0)
    start = toks[k - 1].end() if k > 0 else 0
    comma = line.rfind(",", start, toks[k].start())
    return (comma + 1 if comma >= 0 else start), toks[k].end()


def field_value(line: str, starts: tuple[int, ...], spec: tuple[int, int, int]) -> float:
    a, b = field_span(line, starts, spec)
    return _float(line[a:b])


def part_thickness(line: str) -> float:
    """``Thick`` of a /PART data line (0 when absent: short fixed line or fewer than 4 free-format tokens)."""
    if _is_fixed(line, PART_FIELDS):
        return _float(line[PART_THICK[1] : PART_THICK[2]])
    toks = _TOK.findall(line)
    return _float(toks[PART_THICK[0]]) if len(toks) > PART_THICK[0] else 0.0


def _is_comment(line: str) -> bool:
    return line.startswith(("#", "$"))


def _keyword(line: str) -> list[str]:
    return [p.strip() for p in line.strip().split("/")[1:]]


def _int(s: str) -> int | None:
    try:
        return int(s)
    except ValueError:
        return None


# ------------------------------------------------------------------ scanning
def assembly_files(assem_dir: str | Path) -> list[Path]:
    d = Path(assem_dir)
    if not d.is_dir():
        raise PaicadError("GEOM_INPUT_INVALID", f"assembly folder not found: {d.name}")
    return sorted((p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in (".rad", ".inc")), key=lambda p: p.relative_to(d).as_posix())


def _read_lines(p: Path) -> list[str]:
    return p.read_bytes().decode("latin-1").splitlines()


def scan_tree(assem_dir: str | Path) -> tuple[dict[int, PropDef], list[dict]]:
    """All shell PROPs of the assembly folder with their PARTs and element thickness overrides.
    Returns ({prop id: PropDef}, file list [{rel, sha256}])."""
    root = Path(assem_dir)
    props: dict[int, PropDef] = {}
    part_prop: dict[int, tuple[int, str, float]] = {}  # part id -> (prop id, part title, /PART Thick)
    elem_thick: dict[int, int] = {}  # part id -> elements with own thickness != 0
    files = []
    for p in assembly_files(root):
        rel = p.relative_to(root).as_posix()
        files.append({"rel": rel, "sha256": sha256_file(p)})
        lines = _read_lines(p)
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.startswith("/"):
                i += 1
                continue
            kw = _keyword(line)
            head = kw[0].upper() if kw else ""
            j = i + 1
            if head == "PROP" and len(kw) >= 3:
                ptype = kw[1].upper()
                kind = SUPPORTED.get(ptype) or UNSUPPORTED.get(ptype)
                pid = _int(kw[2])
                if kind is not None and pid is not None:
                    while j < n and _is_comment(lines[j]):
                        j += 1
                    title = lines[j].strip() if j < n and not lines[j].startswith("/") else ""
                    j += 1 if j < n and not lines[j].startswith("/") else 0
                    if pid in props:
                        raise PaicadError("GEOM_INPUT_INVALID", f"PROP {pid} is defined twice ({props[pid].file}, {rel})")
                    pd = PropDef(pid, kind, f"/PROP/{ptype}", title, rel, i + 1)
                    if kind == "SHELL":
                        data = []
                        while j < n and not lines[j].startswith("/") and len(data) < 3:
                            if not _is_comment(lines[j]):
                                data.append(j)
                            j += 1
                        if len(data) == 3:
                            pd.thick_line = data[2] + 1
                            pd.thickness = field_value(lines[data[2]], PROP_FIELDS, PROP_THICK)
                    props[pid] = pd
            elif head == "PART" and len(kw) >= 2 and _int(kw[1]) is not None:
                while j < n and _is_comment(lines[j]):
                    j += 1
                title = lines[j].strip() if j < n and not lines[j].startswith("/") else ""
                j += 1
                while j < n and _is_comment(lines[j]):
                    j += 1
                if j < n and not lines[j].startswith("/"):
                    s = lines[j]
                    pid = _int(s[0:10].strip()) if _is_fixed(s, (0, 10, 20, 30, 50)) else (_int(_TOK.findall(s)[0]) if _TOK.findall(s) else None)
                    if pid is not None:
                        part_prop[int(kw[1])] = (pid, title, part_thickness(s))
            elif head in ELEM_THICK and len(kw) >= 2 and _int(kw[1]) is not None:
                part = int(kw[1])
                spec = ELEM_THICK[head]
                cnt = 0
                while j < n and not lines[j].startswith("/"):
                    s = lines[j]
                    if s.strip() and not _is_comment(s) and field_value(s, ELEM_FIELDS, spec) != 0.0:
                        cnt += 1
                    j += 1
                elem_thick[part] = elem_thick.get(part, 0) + cnt
            i = max(j, i + 1)
    for part, (pid, title, thick) in sorted(part_prop.items()):
        if pid in props:
            props[pid].parts.append((part, title))
            props[pid].element_overrides += elem_thick.get(part, 0)
            if thick != 0.0:
                props[pid].part_overrides.append((part, title, thick))
    return props, files


def parameter_names(props: dict[int, PropDef]) -> dict[int, str]:
    """``<PROP_TITLE>_SHELL_T`` (normalized, NAME_RE), ``PROP<ID>_SHELL_T`` without a title; names used by
    more than one PROP get the PROP id appended to the title part (``<TITLE>_<ID>_SHELL_T``)."""

    def base(pd: PropDef) -> str:
        t = normalize(pd.title)
        if not t:
            return f"PROP{pd.id}"
        return t if (t[0].isalpha() or t[0] == "_") else "_" + t

    def fit(stem: str) -> str:
        if len(stem) + len(PARAM_SUFFIX) <= NAME_MAX:
            return stem + PARAM_SUFFIX
        h = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:4].upper()
        keep = NAME_MAX - len(PARAM_SUFFIX) - len(h) - 1
        return f"{stem[:keep]}_{h}{PARAM_SUFFIX}"

    shell = [pd for pd in sorted(props.values(), key=lambda p: p.id) if pd.kind == "SHELL"]
    first = {pd.id: fit(base(pd)) for pd in shell}
    count: dict[str, int] = {}
    for v in first.values():
        count[v] = count.get(v, 0) + 1
    out = {}
    for pd in shell:
        out[pd.id] = first[pd.id] if count[first[pd.id]] == 1 else fit(f"{base(pd)}_{pd.id}")
    return out


def scan_doc(assem_dir: str | Path, opts: dict) -> dict:
    props, files = scan_tree(assem_dir)
    names = parameter_names(props)
    ratio = float(opts["extract"]["range_ratio"])
    rows, warnings = [], []
    for pid in sorted(props):
        pd = props[pid]
        supported = pd.kind == "SHELL"
        row = {
            "id": pd.id,
            "title": pd.title,
            "type": pd.kind,
            "keyword": pd.keyword,
            "supported": supported,
            "parameter": names.get(pid),
            "thickness": rnd(pd.thickness, 9) if pd.thickness is not None else None,
            "unit": "mm",
            "range": None,
            "parts": [{"id": a, "title": t} for a, t in pd.parts],
            "file": pd.file,
            "line": pd.line,
            "element_overrides": pd.element_overrides,
            "part_overrides": [{"id": a, "title": t, "thickness": rnd(x, 9)} for a, t, x in pd.part_overrides],
            "selectable": False,
        }
        if not supported:
            warnings.append({"code": "PROP_UNSUPPORTED_TYPE", "prop": pid, "message": f"PROP {pid} ({pd.keyword}, {pd.kind}) is not supported: listed only"})
        elif pd.thickness is None:
            warnings.append({"code": "PROP_THICKNESS_INVALID", "prop": pid, "message": f"PROP {pid}: thickness card not found"})
            row["parameter"] = None
        else:
            t = float(pd.thickness)
            if t > 0:
                row["range"] = {"min": rnd(t * (1 - ratio)), "max": rnd(t * (1 + ratio)), "ratio": ratio}
                row["selectable"] = pd.element_overrides == 0 and not pd.part_overrides
            else:
                warnings.append({"code": "PROP_THICKNESS_INVALID", "prop": pid, "message": f"PROP {pid}: thickness {t!r} <= 0"})
            if pd.element_overrides:
                warnings.append(
                    {
                        "code": "PROP_OVERRIDDEN_BY_ELEMENT",
                        "prop": pid,
                        "message": f"PROP {pid}: {pd.element_overrides} shell elements of its parts carry their own thickness (a PROP change has no effect)",
                    }
                )
            if pd.part_overrides:
                ids = [a for a, _, _ in pd.part_overrides]
                warnings.append(
                    {
                        "code": "PROP_OVERRIDDEN_BY_PART",
                        "prop": pid,
                        "parts": ids,
                        "message": f"PROP {pid}: /PART Thick != 0 on parts {', '.join(str(a) for a in ids)} (a PROP change has no effect there)",
                    }
                )
        if len(pd.parts) > 1:
            warnings.append(
                {
                    "code": "PROP_SHARED_BY_PARTS",
                    "prop": pid,
                    "parts": [a for a, _ in pd.parts],
                    "message": f"PROP {pid} is shared by {len(pd.parts)} parts: {', '.join(str(a) for a, _ in pd.parts)}",
                }
            )
        rows.append(row)
    return envelope(status="OK", kind="props", files=files, props=rows, warnings=warnings, options={"range_ratio": ratio})


# ------------------------------------------------------------------ apply
def replace_field(line: str, starts: tuple[int, ...], spec: tuple[int, int, int], value: float) -> str:
    """Replace one field. Fixed width: same columns, one leading blank, value right-aligned in the rest of
    the field (shortest round-trip text when it fits, else the section 6.4 value rule). Free format: the
    token text is replaced by the shortest round-trip text."""
    txt = repr(float(value))
    if not _is_fixed(line, starts):  # free format: no columns, the token text is replaced
        toks = list(_TOK.finditer(line))
        if len(toks) <= spec[0]:
            raise PaicadError("GEOM_INC_FORMAT", "thickness field is absent in a free-format card")
        t = toks[spec[0]]
        return line[: t.start()] + txt + line[t.end() :]
    a, b = field_span(line, starts, spec)
    if len(line) < b:
        line = line.ljust(b)
    w = b - a - 1
    if w < 1:
        raise PaicadError("GEOM_INC_FORMAT", f"thickness field is too narrow ({b - a} columns)")
    if len(txt) > w:
        txt = _fmt(float(value), w).decode("ascii").strip()
    return line[:a] + " " + txt.rjust(w) + line[b:]


class PropFail(PaicadError):
    pass


def load_props_json(path: str | Path) -> dict:
    d = read_json(path, "props file")
    if d.get("schema_version") != 1 or not isinstance(d.get("props"), list):
        raise PaicadError("GEOM_INPUT_INVALID", "props file: unsupported schema or missing props")
    return d


def load_prop_values(path: str | Path, names: set[str]) -> dict[str, float]:
    v = read_json(path, "values file")
    if v.get("schema_version", 1) != 1 or not isinstance(v.get("values"), dict):
        raise PaicadError("GEOM_INPUT_INVALID", "values file must be {schema_version: 1, values: {name: number}}")
    unknown = sorted(set(v["values"]) - names)
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"unknown shell thickness parameter names in values: {', '.join(unknown[:10])}")
    out = {}
    for k, x in v["values"].items():
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise PaicadError("GEOM_INPUT_INVALID", f"value of {k} must be a number")
        out[k] = float(x)
    return out


def apply_values(assem_dir: str | Path, pdoc: dict, values: dict[str, float]) -> tuple[dict[str, bytes], list[dict]]:
    """New bytes of every PROP definition file named by ``values`` (unchanged values -> identical bytes)."""
    by_name = {r["parameter"]: r for r in pdoc["props"] if r.get("parameter")}
    current, _ = scan_tree(assem_dir)
    for name, x in sorted(values.items()):
        if not math.isfinite(x) or x <= 0:
            raise PropFail("PROP_THICKNESS_INVALID", f"{name}: thickness {x!r} <= 0 or not finite")
    edits: dict[str, list[tuple[int, float]]] = {}
    applied = []
    for name, x in sorted(values.items()):
        row = by_name[name]
        pd = current.get(int(row["id"]))
        if pd is None or pd.kind != "SHELL" or pd.thick_line is None:
            raise PropFail("PROP_NOT_FOUND", f"{name}: PROP {row['id']} (/PROP/TYPE1) not found in the assembly folder")
        old = float(pd.thickness)
        changed = x != old
        if changed and pd.element_overrides:
            raise PropFail(
                "PROP_OVERRIDDEN_BY_ELEMENT", f"{name}: {pd.element_overrides} shell elements of PROP {pd.id} carry their own thickness (PROP change has no effect)"
            )
        if changed and pd.part_overrides:
            ids = ", ".join(str(a) for a, _, _ in pd.part_overrides)
            raise PropFail("PROP_OVERRIDDEN_BY_PART", f"{name}: /PART Thick != 0 on parts {ids} of PROP {pd.id} (PROP change has no effect)")
        edits.setdefault(pd.file, [])
        if changed:
            edits[pd.file].append((pd.thick_line, x))
        applied.append({"parameter": name, "prop": pd.id, "file": pd.file, "line": pd.thick_line, "old": rnd(old, 9), "new": rnd(x, 9), "changed": changed})
    root = Path(assem_dir)
    out: dict[str, bytes] = {}
    for rel, items in sorted(edits.items()):
        data = (root / rel).read_bytes()
        if not items:
            out[rel] = data
            continue
        lines = data.decode("latin-1").splitlines(keepends=True)
        for ln, x in items:
            raw = lines[ln - 1]
            body = raw.rstrip("\r\n")
            lines[ln - 1] = replace_field(body, PROP_FIELDS, PROP_THICK, x) + raw[len(body) :]
        out[rel] = "".join(lines).encode("latin-1")
    return out, applied


# ------------------------------------------------------------------ CLI
def run(args, rep: Reporter) -> int:
    if args.props_cmd == "scan":
        return run_scan(args, rep)
    return run_apply(args, rep)


def run_scan(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    opts = options.load(args.options)
    out = OutDir(args.out_dir, [PROPS_JSON])
    out.prepare()
    rep.progress(10, "scanning assembly folder for shell properties")
    doc = scan_doc(args.assem_dir, opts)
    doc["elapsed_s"] = rnd(time.monotonic() - t0, 3)
    out.write_text(PROPS_JSON, dumps(doc))
    out.commit([PROPS_JSON])
    n = sum(1 for r in doc["props"] if r["supported"])
    rep.progress(100, f"props scan done: {len(doc['props'])} shell properties ({n} supported)")
    rep.result("OK", None, PROPS_JSON)
    return EXIT_OK


def run_apply(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    out = OutDir(args.out_dir, [APPLY_JSON])
    out.prepare()
    pdoc = load_props_json(args.props)
    names = {r["parameter"] for r in pdoc["props"] if r.get("parameter")}
    values = load_prop_values(args.values, names)
    rep.progress(10, "applying shell thicknesses")
    try:
        new_files, applied = apply_values(args.assem_dir, pdoc, values)
    except PropFail as e:
        d = envelope(status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code), message=e.message, applied=[], files=[], elapsed_s=rnd(time.monotonic() - t0, 3))
        out.write_text(APPLY_JSON, dumps(d))
        out.commit([APPLY_JSON])
        rep.result("FAIL", e.code, APPLY_JSON)
        return e.exit_code
    rels = sorted(new_files)
    existing = [r for r in rels if (Path(args.out_dir) / r).exists()]
    if existing:
        raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {', '.join(existing[:10])}")
    for rel in rels:
        out.tmp_path(rel).write_bytes(new_files[rel])
    d = envelope(
        status="OK",
        code=None,
        category=None,
        message=None,
        applied=applied,
        files=[{"rel": r, "sha256": hashlib.sha256(new_files[r]).hexdigest(), "changed": any(a["changed"] for a in applied if a["file"] == r)} for r in rels],
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(APPLY_JSON, dumps(d))
    out.commit(rels + [APPLY_JSON])
    rep.progress(100, f"props apply done: {sum(1 for a in applied if a['changed'])} thickness fields changed")
    rep.result("OK", None, APPLY_JSON)
    return EXIT_OK


__all__ = ["APPLY_JSON", "PROPS_JSON", "apply_values", "parameter_names", "part_thickness", "scan_doc", "scan_tree"]
