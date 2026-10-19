"""Independent glTF 2.0 binary (GLB) parser + structure validator for the view tests (no external library).

Written from the glTF 2.0 specification, not from ``paicad.view.gltf``: header/chunks, 4-byte alignment
(JSON padded with spaces, BIN with zeros), buffer views, accessor element alignment and bounds,
POSITION min/max = data, index range (no primitive-restart value), application-specific attribute
names (``_`` prefix), node tree, no extensions.
"""

from __future__ import annotations

import json
import struct

import numpy as np

COMP = {5120: ("i1", 1), 5121: ("u1", 1), 5122: ("<i2", 2), 5123: ("<u2", 2), 5125: ("<u4", 4), 5126: ("<f4", 4)}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
STANDARD_ATTRS = {"POSITION", "NORMAL", "TANGENT", "TEXCOORD_0", "TEXCOORD_1", "COLOR_0", "JOINTS_0", "WEIGHTS_0"}


class GlbError(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise GlbError(msg)


def parse_glb(data: bytes) -> tuple[dict, bytes]:
    check(len(data) >= 20, "too short")
    magic, version, length = struct.unpack_from("<III", data, 0)
    check(magic == 0x46546C67 and version == 2, "bad header")
    check(length == len(data) and length % 4 == 0, "header length")
    off = 12
    chunks = []
    while off < length:
        clen, ctype = struct.unpack_from("<II", data, off)
        check(clen % 4 == 0, "chunk length not 4-byte aligned")
        chunks.append((ctype, data[off + 8 : off + 8 + clen]))
        off += 8 + clen
    check(off == length, "chunks do not fill the file")
    check(len(chunks) == 2, f"expected JSON + one BIN chunk, got {len(chunks)}")
    (t0, js), (t1, bin_) = chunks
    check(t0 == 0x4E4F534A and t1 == 0x004E4942, "chunk types")
    check(b"\x00" not in js, "JSON chunk must be padded with spaces")
    doc = json.loads(js.decode("utf-8"))
    return doc, bin_


def read_accessor(doc: dict, bin_: bytes, idx: int) -> np.ndarray:
    acc = doc["accessors"][idx]
    view = doc["bufferViews"][acc["bufferView"]]
    dt, size = COMP[acc["componentType"]]
    w = WIDTH[acc["type"]]
    elem = size * w
    stride = view.get("byteStride", elem)
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    n = acc["count"]
    check(acc.get("byteOffset", 0) + stride * (n - 1) + elem <= view["byteLength"], f"accessor {idx} exceeds its buffer view")
    raw = np.frombuffer(bin_, dtype=np.uint8, count=stride * (n - 1) + elem, offset=start)
    if stride == elem:
        out = raw.view(dt).reshape(n, w)
    else:
        rows = np.lib.stride_tricks.as_strided(raw, shape=(n, elem), strides=(stride, 1))
        out = np.ascontiguousarray(rows).view(dt).reshape(n, w)
    return out[:, 0] if w == 1 else out


def validate(doc: dict, bin_: bytes) -> None:
    check(doc.get("asset", {}).get("version") == "2.0", "asset.version")
    check("extensionsUsed" not in doc and "extensionsRequired" not in doc, "extensions present")
    bufs = doc.get("buffers") or []
    check(len(bufs) == 1 and "uri" not in bufs[0], "exactly one GLB buffer")
    blen = bufs[0]["byteLength"]
    check(len(bin_) - 3 <= blen <= len(bin_), "buffer byteLength vs BIN chunk")
    check(set(bin_[blen:]) <= {0}, "BIN chunk must be padded with zeros")
    for i, v in enumerate(doc.get("bufferViews") or []):
        check(v["buffer"] == 0, "buffer index")
        check(v.get("byteOffset", 0) % 4 == 0, f"bufferView {i} offset not 4-byte aligned")
        check(v.get("byteOffset", 0) + v["byteLength"] <= blen, f"bufferView {i} exceeds the buffer")
        if "byteStride" in v:
            check(v["byteStride"] % 4 == 0 and 4 <= v["byteStride"] <= 252, f"bufferView {i} byteStride")
    for i, a in enumerate(doc.get("accessors") or []):
        check(a["componentType"] in COMP and a["type"] in WIDTH and a["count"] >= 1, f"accessor {i}")
        read_accessor(doc, bin_, i)
    nmesh = len(doc.get("meshes") or [])
    for mi, m in enumerate(doc.get("meshes") or []):
        for p in m["primitives"]:
            attrs = p["attributes"]
            check("POSITION" in attrs, f"mesh {mi}: POSITION missing")
            counts = set()
            for name, ai in attrs.items():
                check(name in STANDARD_ATTRS or name.startswith("_"), f"attribute name {name}")
                acc = doc["accessors"][ai]
                view = doc["bufferViews"][acc["bufferView"]]
                check(view.get("target", 34962) == 34962, f"{name}: target")
                _, size = COMP[acc["componentType"]]
                check((view.get("byteOffset", 0) + acc.get("byteOffset", 0)) % 4 == 0, f"{name}: element offset not 4-byte aligned")
                check(view.get("byteStride", size * WIDTH[acc["type"]]) % 4 == 0, f"{name}: element stride not 4-byte aligned")
                counts.add(acc["count"])
            check(len(counts) == 1, f"mesh {mi}: attribute counts differ")
            pa = doc["accessors"][attrs["POSITION"]]
            check(pa["type"] == "VEC3" and pa["componentType"] == 5126 and "min" in pa and "max" in pa, "POSITION accessor")
            pos = read_accessor(doc, bin_, attrs["POSITION"])
            check(np.array_equal(pos.min(axis=0), np.asarray(pa["min"], dtype=np.float32)), "POSITION min")
            check(np.array_equal(pos.max(axis=0), np.asarray(pa["max"], dtype=np.float32)), "POSITION max")
            if "NORMAL" in attrs:
                nrm = read_accessor(doc, bin_, attrs["NORMAL"])
                check(np.allclose(np.linalg.norm(nrm, axis=1), 1.0, atol=1e-4), "NORMAL not unit length")
            check(p.get("mode", 4) in (1, 4), "mode")
            if "indices" in p:
                ia = doc["accessors"][p["indices"]]
                check(ia["componentType"] in (5121, 5123, 5125) and ia["type"] == "SCALAR", "indices type")
                check("byteStride" not in doc["bufferViews"][ia["bufferView"]], "indices byteStride")
                idx = read_accessor(doc, bin_, p["indices"])
                restart = {5121: 0xFF, 5123: 0xFFFF, 5125: 0xFFFFFFFF}[ia["componentType"]]
                check(int(idx.max()) < len(pos) and int(idx.max()) != restart, "index range")
                check(len(idx) % (3 if p.get("mode", 4) == 4 else 2) == 0, "index count")
            if "material" in p:
                check(0 <= p["material"] < len(doc.get("materials") or []), "material index")
    nodes = doc.get("nodes") or []
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            check(0 <= c < len(nodes) and c != i, "child index")
        if "mesh" in n:
            check(0 <= n["mesh"] < nmesh, "node mesh index")
    for s in doc.get("scenes") or []:
        for r in s["nodes"]:
            check(0 <= r < len(nodes), "scene node")


def load(path) -> tuple[dict, bytes]:
    with open(path, "rb") as f:
        data = f.read()
    doc, bin_ = parse_glb(data)
    validate(doc, bin_)
    return doc, bin_


def node_mesh(doc: dict, bin_: bytes, name: str) -> dict[str, np.ndarray]:
    """{attribute: array, "indices": [k,3|2]} of the node named ``name``."""
    node = next(n for n in doc["nodes"] if n.get("name") == name)
    prim = doc["meshes"][node["mesh"]]["primitives"][0]
    out = {k: read_accessor(doc, bin_, a) for k, a in prim["attributes"].items()}
    w = 3 if prim.get("mode", 4) == 4 else 2
    out["indices"] = read_accessor(doc, bin_, prim["indices"]).astype(np.int64).reshape(-1, w)
    out["_mode"] = prim.get("mode", 4)
    return out
