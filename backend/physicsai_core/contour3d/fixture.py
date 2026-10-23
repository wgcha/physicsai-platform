"""V-C3F-8 프런트 픽스처 생성(contour3d-field.md §15 — Backend가 생성 스크립트, Frontend가 픽스처 커밋).

`python -m physicsai_core.contour3d.fixture <출력 폴더>` → `<출력>/meshopt/`·`<출력>/plain/`(meshopt 켬·끔)에 같은 합성 입력의
contour.glb·contour_lod.glb·contour_frames.bin·contour_disp.bin·contour_manifest.json과 `expected.json`(디코드 기대값: 정점 수,
int16 위치·`_NODE_ID`·인덱스·LOD `_SRC`의 base64 LE)을 쓴다. 프런트 vitest는 두 GLB를 three MeshoptDecoder·GLTFLoader로 읽어
expected와 바이트가 같은지 확인한다. 결정적(같은 코드면 같은 바이트).
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys
import tempfile

import numpy as np

from . import glb as glbmod
from .convert import convert

NX, NY = 24, 16  # 두 겹 헥사 판(노드 768)


def _write_extract(d: str) -> None:
    ids = 500 + np.arange(NX * NY * 2)[::-1] * 7  # 섞인 순서·불연속 ID
    xs, ys, zs = np.meshgrid(np.arange(NX) * 2.0, np.arange(NY) * 1.5, np.arange(2) * 0.2, indexing="ij")
    xyz = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
    lin = np.arange(ids.size).reshape(NX, NY, 2)
    q = np.stack([lin[:-1, :-1, 0], lin[1:, :-1, 0], lin[1:, 1:, 0], lin[:-1, 1:, 0]], axis=-1).reshape(-1, 4)
    hexes = ids[np.concatenate([q, q + 1], axis=1)]
    with open(os.path.join(d, "nodes.csv"), "w", encoding="utf-8") as fh:
        fh.write("node_id,x,y,z\n")
        fh.writelines(f"{i},{p[0]:g},{p[1]:g},{p[2]:g}\n" for i, p in zip(ids.tolist(), xyz.tolist()))
    with open(os.path.join(d, "elements.csv"), "w", encoding="utf-8") as fh:
        fh.write("elem_id,config,n1,n2,n3,n4,n5,n6,n7,n8\n")
        fh.writelines(f"{k + 1},208," + ",".join(str(x) for x in h) + "\n" for k, h in enumerate(hexes.tolist()))
    lines = ["# contour_extract 1", "STATUS=OK", "UNIT=MPa", "FIELD=Stress", "DCOMP=vonMises", "AVGMODE=simple",
             f"NODES={ids.size}", f"FACES={len(hexes)}", "FRAMES_TOTAL=3", "DISP=ON", "DISP_MISSING_FRAMES=0", "SCOPE=ALL"]
    for i in range(3):
        lines.append(f"FRAME={i}|{i}|{0.001 * i:g}")
        v = np.sin(ids * 0.3) * 50 * (i + 1)
        rows = [f"{float(a)!r},{0.1 * i * math.cos(n * 0.2)!r},0,{-0.05 * i!r}" for n, a in zip(ids.tolist(), v.tolist())]
        rows[3] = ",0,0,0"  # 값 없음(NaN 코드 65535)
        with open(os.path.join(d, f"frame_{i:05d}.csv"), "w", encoding="utf-8") as fh:
            fh.write("value,dx,dy,dz\n" + "\n".join(rows) + "\n")
    with open(os.path.join(d, "extract_result.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _expected(path: str) -> dict:
    with open(path, "rb") as fh:
        doc, bin_chunk = glbmod.read_glb(fh.read())
    prim = doc["meshes"][0]["primitives"][0]
    out: dict = {"count": doc["accessors"][prim["attributes"]["POSITION"]]["count"]}
    pos = glbmod.decode_view(doc, bin_chunk, doc["accessors"][prim["attributes"]["POSITION"]]["bufferView"])
    out["position_i16"] = _b64(np.frombuffer(pos, dtype="<i2").reshape(-1, 4)[:, :3].tobytes())
    for name, ai in prim["attributes"].items():
        if name != "POSITION":
            out[name] = _b64(glbmod.decode_view(doc, bin_chunk, doc["accessors"][ai]["bufferView"]))
    out["indices_u32"] = _b64(glbmod.decode_view(doc, bin_chunk, doc["accessors"][prim["indices"]]["bufferView"]))
    out["translation"], out["scale"] = doc["nodes"][1]["translation"], doc["nodes"][1]["scale"]
    return out


def generate(out_root: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _write_extract(tmp)
        for name, flag in (("meshopt", True), ("plain", False)):
            out = os.path.join(out_root, name)
            convert(tmp, out, source={"kind": "PREDICT_H3D", "ref": {"job_id": "fixture"}, "h3d_name": "fixture.h3d"},
                    max_nodes=2_000_000, max_bin_bytes=256 << 20, max_frames=55, lod_min_nodes=100, lod_target_vertices=1000,
                    meshopt=flag, comps=[])
            exp = {f: _expected(os.path.join(out, f)) for f in ("contour.glb", "contour_lod.glb")}
            with open(os.path.join(out, "expected.json"), "w", encoding="utf-8") as fh:
                json.dump(exp, fh, indent=1, sort_keys=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용: python -m physicsai_core.contour3d.fixture <출력 폴더>")
        raise SystemExit(2)
    generate(sys.argv[1])
