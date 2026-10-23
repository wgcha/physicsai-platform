"""`contour.glb`·`contour_lod.glb` 작성(schema 2 — contour3d-field.md §4.3, geometry-view.md GV-C5). glTF 2.0 바이너리.

루트 노드 `paicad_contour`(extras unit·up_axis) 아래 `surface` 노드(translation·scale = 위치 역양자화) + 메시 1개(TRIANGLES).
- POSITION: `KHR_mesh_quantization` SHORT normalized ×3(+2 B 0 패딩, byteStride 8), min·max = 저장된 정수값(glTF 규칙).
- NORMAL 없음(뷰어가 1회 계산). 사용자 속성 `_NODE_ID`·`_SRC`(선택) = UNSIGNED_INT 무손실. indices = UNSIGNED_INT.
- meshopt=True: 버퍼 뷰마다 `EXT_meshopt_compression`(ATTRIBUTES / INDICES), 압축 데이터는 GLB BIN(버퍼 0), 부모 뷰는 데이터 없는
  대체 버퍼 1(`fallback: true`, 뷰어 전용 — 대체 데이터는 두지 않음). meshopt=False: 같은 배치를 압축 없이 버퍼 0에.
결정성: JSON 키 순서 고정·공백 없음, 4바이트 정렬(JSON 공백·BIN 0 채움), 시각·경로 없음 → 같은 입력이면 바이트 동일.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence

import numpy as np

from . import meshopt as mo

SHORT, UINT = 5122, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
GENERATOR = "physicsai contour3d 2"
EXT_QUANT, EXT_MESHOPT = "KHR_mesh_quantization", "EXT_meshopt_compression"


def _pad(b: bytes, fill: bytes) -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def write_glb(q_pos: np.ndarray, translation: Sequence[float], scale: Sequence[float], attrs: Sequence[tuple[str, np.ndarray]],
              indices: np.ndarray, *, meshopt: bool) -> bytes:
    """q_pos int16 [N,3](meshopt.quantize_positions), attrs = [(이름, uint32[N])], indices = uint32[3T]."""
    q = np.ascontiguousarray(q_pos, dtype=np.int16)
    n = int(q.shape[0])
    pos = np.zeros((n, 4), dtype="<i2")
    pos[:, :3] = q
    views_raw: list[tuple[bytes, int, int, str, int]] = [(pos.tobytes(), 8, ARRAY_BUFFER, "ATTRIBUTES", n)]  # (데이터, stride, target, mode, count)
    for _name, a in attrs:
        views_raw.append((np.ascontiguousarray(a, dtype="<u4").tobytes(), 4, ARRAY_BUFFER, "ATTRIBUTES", n))
    idx = np.ascontiguousarray(indices, dtype="<u4").ravel()
    views_raw.append((idx.tobytes(), 4, ELEMENT_ARRAY_BUFFER, "INDICES", int(idx.size)))
    views: list[dict] = []
    blobs: list[bytes] = []
    off = 0  # 버퍼 0(GLB BIN)
    foff = 0  # 대체 버퍼 1(meshopt)
    for data, stride, target, mode, count in views_raw:
        view: dict = {"buffer": 0, "byteOffset": 0, "byteLength": len(data)}
        if target == ARRAY_BUFFER:
            view["byteStride"] = stride
        view["target"] = target
        if meshopt:
            if mode == "ATTRIBUTES":
                enc = mo.encode_vertex_buffer(np.frombuffer(data, dtype=np.uint8).reshape(count, stride))
            else:
                enc = mo.encode_index_sequence(idx)
            view["buffer"], view["byteOffset"] = 1, foff
            foff += len(_pad(data, b"\x00"))
            view["extensions"] = {EXT_MESHOPT: {"buffer": 0, "byteOffset": off, "byteLength": len(enc), "byteStride": stride,
                                                "count": count, "mode": mode}}
            payload = enc
        else:
            view["byteOffset"] = off
            payload = data
        padded = _pad(payload, b"\x00")
        blobs.append(padded)
        off += len(padded)
        views.append(view)
    bin_chunk = b"".join(blobs)
    mn = [int(x) for x in q.min(axis=0)] if n else [0, 0, 0]
    mx = [int(x) for x in q.max(axis=0)] if n else [0, 0, 0]
    attributes = {"POSITION": 0}
    accessors: list[dict] = [{"bufferView": 0, "componentType": SHORT, "normalized": True, "count": n, "type": "VEC3", "min": mn, "max": mx}]
    for i, (name, _a) in enumerate(attrs, start=1):
        attributes[name] = i
        accessors.append({"bufferView": i, "componentType": UINT, "count": n, "type": "SCALAR"})
    accessors.append({"bufferView": len(attrs) + 1, "componentType": UINT, "count": int(idx.size), "type": "SCALAR"})
    ext = [EXT_QUANT, EXT_MESHOPT] if meshopt else [EXT_QUANT]
    buffers: list[dict] = [{"byteLength": len(bin_chunk)}]
    if meshopt:
        buffers.append({"byteLength": foff, "extensions": {EXT_MESHOPT: {"fallback": True}}})
    doc = {
        "asset": {"version": "2.0", "generator": GENERATOR},
        "extensionsUsed": ext,
        "extensionsRequired": ext,
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "paicad_contour", "children": [1], "extras": {"unit": "mm", "up_axis": "Z"}},
                  {"name": "surface", "mesh": 0, "translation": [float(x) for x in translation], "scale": [float(x) for x in scale]}],
        "meshes": [{"name": "surface", "primitives": [{"attributes": attributes, "indices": len(attrs) + 1, "mode": 4}]}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": buffers,
    }
    js = _pad(json.dumps(doc, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii"), b" ")
    total = 12 + 8 + len(js) + 8 + len(bin_chunk)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk)


def read_glb(data: bytes) -> tuple[dict, bytes]:
    """시험·검증용: GLB 헤더 확인 → (JSON, BIN)."""
    magic, ver, total = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or ver != 2 or total != len(data):
        raise ValueError("GLB 헤더 오류")
    ln, typ = struct.unpack_from("<II", data, 12)
    if typ != 0x4E4F534A:
        raise ValueError("JSON 청크 없음")
    doc = json.loads(data[20:20 + ln].decode("ascii"))
    p = 20 + ln
    if p + 8 > len(data):
        return doc, b""
    bl, bt = struct.unpack_from("<II", data, p)
    if bt != 0x004E4942:
        raise ValueError("BIN 청크 없음")
    return doc, data[p + 8:p + 8 + bl]


def read_glb_json(data: bytes) -> dict:
    return read_glb(data)[0]


def decode_view(doc: dict, bin_chunk: bytes, view_index: int) -> bytes:
    """시험·검증용: 버퍼 뷰 원본 바이트(meshopt면 참조 디코더로 푼다)."""
    v = doc["bufferViews"][view_index]
    e = (v.get("extensions") or {}).get(EXT_MESHOPT)
    if e is None:
        return bin_chunk[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
    src = bin_chunk[e.get("byteOffset", 0):e.get("byteOffset", 0) + e["byteLength"]]
    if e["mode"] == "ATTRIBUTES":
        return mo.decode_vertex_buffer(src, e["count"], e["byteStride"])
    vals = mo.decode_index_sequence(src, e["count"])
    return np.asarray(vals, dtype="<u4" if e["byteStride"] == 4 else "<u2").tobytes()
