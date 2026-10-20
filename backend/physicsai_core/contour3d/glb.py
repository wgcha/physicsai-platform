"""`contour.glb` 작성(geometry-view.md §13.4) — glTF 2.0 바이너리, 확장 없음, 표준 라이브러리만(형상 엔진 writer와 코드 공유 없음).

루트 노드 `paicad_contour`(extras unit·up_axis) 아래 `surface` 메시 1개(TRIANGLES). 정점 = FE 노드(공유), 속성 POSITION(min·max)·
NORMAL·`_NODE_ID`(UNSIGNED_INT, 노드 ID 보존). indices = 정점 < 65536이면 UNSIGNED_SHORT, 아니면 UNSIGNED_INT.
결정성: JSON 키 순서 고정·공백 없음, 4바이트 정렬(JSON 공백·BIN 0 채움), 시각·경로 없음 → 같은 입력이면 바이트 동일.
"""

from __future__ import annotations

import json
import struct
import sys
from array import array
from collections.abc import Sequence

FLOAT, UINT, USHORT = 5126, 5125, 5123
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
GENERATOR = "physicsai contour3d 1"


def _le(a: array) -> bytes:
    if sys.byteorder == "big":
        a = array(a.typecode, a)
        a.byteswap()
    return a.tobytes()


def _pad(b: bytes, fill: bytes) -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def write_glb(positions: Sequence[float], normals: Sequence[float], node_ids: Sequence[int], indices: Sequence[int]) -> bytes:
    """positions·normals = 평탄 [x0,y0,z0,…](float), node_ids = 정점별 ID, indices = 삼각형 정점 번호(3개씩)."""
    n = len(node_ids)
    m = len(indices)
    pos = array("f", positions)
    nor = array("f", normals)
    ids = array("I", node_ids) if array("I").itemsize == 4 else array("L", node_ids)
    small = n < 65536
    idx = array("H" if small else "I", indices)
    blobs: list[bytes] = []
    views: list[dict] = []
    off = 0
    for data, target in ((_le(pos), ARRAY_BUFFER), (_le(nor), ARRAY_BUFFER), (_le(ids), ARRAY_BUFFER), (_le(idx), ELEMENT_ARRAY_BUFFER)):
        padded = _pad(data, b"\x00")
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        blobs.append(padded)
        off += len(padded)
    bin_chunk = b"".join(blobs)
    mn = [min(pos[i::3]) for i in range(3)] if n else [0.0, 0.0, 0.0]
    mx = [max(pos[i::3]) for i in range(3)] if n else [0.0, 0.0, 0.0]
    doc = {
        "asset": {"version": "2.0", "generator": GENERATOR},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "paicad_contour", "children": [1], "extras": {"unit": "mm", "up_axis": "Z"}},
                  {"name": "surface", "mesh": 0}],
        "meshes": [{"name": "surface", "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "_NODE_ID": 2}, "indices": 3,
                                                       "mode": 4}]}],
        "accessors": [
            {"bufferView": 0, "componentType": FLOAT, "count": n, "type": "VEC3", "min": [float(x) for x in mn],
             "max": [float(x) for x in mx]},
            {"bufferView": 1, "componentType": FLOAT, "count": n, "type": "VEC3"},
            {"bufferView": 2, "componentType": UINT, "count": n, "type": "SCALAR"},
            {"bufferView": 3, "componentType": USHORT if small else UINT, "count": m, "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_chunk)}],
    }
    js = _pad(json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("ascii"), b" ")
    total = 12 + 8 + len(js) + 8 + len(bin_chunk)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk)


def read_glb_json(data: bytes) -> dict:
    """시험·검증용: GLB 헤더 확인 후 JSON 청크."""
    magic, ver, total = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or ver != 2 or total != len(data):
        raise ValueError("GLB 헤더 오류")
    ln, typ = struct.unpack_from("<II", data, 12)
    if typ != 0x4E4F534A:
        raise ValueError("JSON 청크 없음")
    return json.loads(data[20:20 + ln].decode("ascii"))
