"""v0.2.10 3D 컨투어 변환기(contour3d-field.md §4·§5·§7·§9.6): 양자화 오차(V-C3F-7), meshopt 왕복(V-C3F-8 — Python 참조 디코더 +
Node three MeshoptDecoder·GLTFLoader), 정점 순서 불변식(V-C3F-9), 크기 우선순위(V-C3F-6), LOD(V-C3F-10), 메모리·시간(V-C3F-11),
변위 판정·부품 범위·단위(§9.2·§9.4·§9.5), CSV 견고성, 바이트 결정성."""

from __future__ import annotations

import base64
import json
import math
import os
import shutil
import subprocess
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

from physicsai_core.contour3d import glb as glbmod
from physicsai_core.contour3d import lod as lodmod
from physicsai_core.contour3d import meshopt as mo
from physicsai_core.contour3d.convert import ConvertError, convert, quantize_disp, quantize_scalar

REPO = Path(__file__).resolve().parents[2]
JS = Path(__file__).resolve().parent / "js" / "meshopt_roundtrip.mjs"
SRC = {"kind": "PREDICT_H3D", "ref": {"job_id": "j"}}


# ---- 합성 입력 ---------------------------------------------------------------------------------------------------


def _val(ids: np.ndarray, i: int) -> np.ndarray:
    return np.sin(ids * 0.37) * 100.0 * (i + 1) + ids * 1e-3


def _disp(ids: np.ndarray, i: int) -> np.ndarray:
    return np.stack([np.cos(ids * 0.11) * i, np.sin(ids * 0.05) * 0.5 * i, -0.01 * i * np.ones(ids.size)], axis=1)


def _grid(nx: int, ny: int, layers: int = 1, dz: float = 0.1, seed: int = 0):
    """판(layers=1 → 쿼드 faces) 또는 두 겹 헥사(layers=2 → elements). 노드 ID는 섞인 순서·불연속."""
    rng = np.random.default_rng(seed)
    n = nx * ny * layers
    ids = 1000 + rng.permutation(n) * 3
    xs, ys, zs = np.meshgrid(np.arange(nx) * 1.5, np.arange(ny) * 1.0, np.arange(layers) * dz, indexing="ij")
    xyz = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
    lin = np.arange(n).reshape(nx, ny, layers)
    q = np.stack([lin[:-1, :-1, 0], lin[1:, :-1, 0], lin[1:, 1:, 0], lin[:-1, 1:, 0]], axis=-1).reshape(-1, 4)
    if layers == 1:
        return ids, xyz, ("faces", ids[q])
    up = q + 1  # 같은 (x, y)의 위층(layers 축이 마지막)
    hexes = np.concatenate([q, up], axis=1)
    return ids, xyz, ("elements", ids[hexes])


def _write(d: Path, ids, xyz, topo, *, frames: int = 4, disp: bool = True, extra: tuple[str, ...] = (), unit: str = "MPa",
           nan_every: int = 0, values=None, link: bool = False) -> None:
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "nodes.csv", "w") as fh:
        fh.write("node_id,x,y,z\n")
        np.savetxt(fh, np.column_stack([ids, xyz]), fmt=["%d", "%.6f", "%.6f", "%.6f"], delimiter=",")
    kind, conn = topo
    if kind == "faces":
        with open(d / "faces.csv", "w") as fh:
            fh.write("elem_id,n1,n2,n3,n4\n")
            np.savetxt(fh, np.column_stack([np.arange(1, len(conn) + 1), conn]), fmt="%d", delimiter=",")
    else:
        with open(d / "elements.csv", "w") as fh:
            fh.write("elem_id,config,n1,n2,n3,n4,n5,n6,n7,n8\n")
            np.savetxt(fh, np.column_stack([np.arange(1, len(conn) + 1), np.full(len(conn), 208), conn]), fmt="%d", delimiter=",")
    lines = ["# contour_extract 1", "STATUS=OK", f"UNIT={unit}", "FIELD=Stress", "DCOMP=vonMises", "AVGMODE=simple",
             f"NODES={len(ids)}", f"FACES={len(conn)}", f"FRAMES_TOTAL={frames}", *extra]
    for i in range(frames):
        lines.append(f"FRAME={i}|{i}|Time = {0.001 * i:g}")
        p = d / f"frame_{i:05d}.csv"
        if link and i > 0:
            os.link(d / "frame_00000.csv", p)
            continue
        v = _val(ids, i) if values is None else values(ids, i)
        cells = [[repr(float(x)) for x in v]]
        if nan_every:
            for j in range(0, len(ids), nan_every):
                cells[0][j] = ""
        if disp:
            dd = _disp(ids, i)
            cells += [[repr(float(x)) for x in dd[:, c]] for c in range(3)]
        body = "\n".join(",".join(r) for r in zip(*cells))
        p.write_text(("value,dx,dy,dz\n" if disp else "value\n") + body + "\n")
    (d / "extract_result.txt").write_text("\n".join(lines) + "\n")


def _conv(d: Path, out: Path, **kw):
    lim = {"max_nodes": 10_000_000, "max_bin_bytes": 1 << 30, "max_frames": 55}
    lim.update(kw)
    return convert(str(d), str(out), source=SRC, **lim)


def _glb_arrays(path: Path) -> dict:
    doc, bin_chunk = glbmod.read_glb(path.read_bytes())
    prim = doc["meshes"][0]["primitives"][0]
    out = {"doc": doc}
    for name, ai in [*prim["attributes"].items(), ("INDICES", prim["indices"])]:
        acc = doc["accessors"][ai]
        raw = glbmod.decode_view(doc, bin_chunk, acc["bufferView"])
        if name == "POSITION":
            out[name] = np.frombuffer(raw, dtype="<i2").reshape(-1, 4)[:, :3]
        else:
            out[name] = np.frombuffer(raw, dtype="<u4")
    node = doc["nodes"][1]
    out["xyz"] = np.asarray(node["translation"]) + np.asarray(node["scale"]) * out["POSITION"] / 32767.0
    return out


def _frames(out: Path, man: dict) -> tuple[np.ndarray, np.ndarray | None]:
    fr = man["frames"]
    q = np.fromfile(out / fr["file"], dtype="<u2").reshape(fr["count"], -1)
    v = np.full(q.shape, np.nan)
    for i, e in enumerate(fr["list"]):
        ok = q[i] != 65535
        if e["min"] is not None:
            v[i, ok] = e["min"] + q[i, ok] * e["scale"]
    if not man["disp"]:
        return v, None
    dq = np.fromfile(out / man["disp"]["file"], dtype="<u2").reshape(fr["count"], -1, 3)
    d = np.stack([np.asarray(e["min"]) + dq[i] * np.asarray(e["scale"]) for i, e in enumerate(man["disp"]["list"])])
    return v, d


# ---- V-C3F-7 양자화 ----------------------------------------------------------------------------------------------


def test_quantize_scalar_error_nan_constant_and_extremes():
    rng = np.random.default_rng(3)
    v = rng.normal(50, 120, 20000)
    v[[5, 77, 900]] = np.nan
    v[[6, 78]] = [np.inf, -np.inf]
    v[100] = v[~np.isnan(v) & np.isfinite(v)].max()  # 최대값 동률 → 작은 번호
    q, info, bad = quantize_scalar(v)
    fin = np.isfinite(v)
    assert bad == 5 and (q[~fin] == 65535).all() and q.dtype == np.uint16 and q[fin].max() <= 65534
    lo, hi = v[fin].min(), v[fin].max()
    assert info["min"] == lo and info["max"] == hi and info["scale"] == (hi - lo) / 65534
    assert info["max_v"] == int(np.flatnonzero(v == hi)[0]) and info["min_v"] == int(np.flatnonzero(v == lo)[0])
    rec = info["min"] + q[fin] * info["scale"]
    assert np.abs(rec - v[fin]).max() <= (hi - lo) / 131068 * (1 + 1e-6)
    q, info, bad = quantize_scalar(np.full(10, 7.25))  # 상수 프레임
    assert info["scale"] == 0.0 and info["min"] == info["max"] == 7.25 and (q == 0).all() and info["min_v"] == info["max_v"] == 0
    q, info, bad = quantize_scalar(np.array([np.nan, 3.0, np.nan]))
    assert info["scale"] == 0.0 and list(q) == [65535, 0, 65535] and info["min_v"] == info["max_v"] == 1
    q, info, bad = quantize_scalar(np.full(4, np.nan))
    assert bad == 4 and (q == 65535).all() and info["min"] is None and info["max_v"] is None


def test_quantize_disp_error_and_nonfinite():
    rng = np.random.default_rng(4)
    d = rng.normal(0, 20, (5000, 3))
    d[:, 2] = 1.5  # 상수 성분
    d[10, 0] = np.nan
    q, mn, sc = quantize_disp(d)
    dd = np.where(np.isfinite(d), d, 0.0)
    rec = np.asarray(mn) + q * np.asarray(sc)
    for c in range(3):
        rng_c = dd[:, c].max() - dd[:, c].min()
        assert np.abs(rec[:, c] - dd[:, c]).max() <= rng_c / 131070 * (1 + 1e-6) + 1e-12
    assert sc[2] == 0.0 and (q[:, 2] == 0).all() and rec[10, 0] == pytest.approx(0.0, abs=sc[0])


# ---- V-C3F-8 meshopt 왕복(Python 참조 디코더) -------------------------------------------------------------------------


@pytest.mark.parametrize("count,stride", [(1, 4), (15, 4), (16, 8), (17, 8), (256, 4), (257, 8), (1000, 12), (3000, 8), (70, 256)])
def test_meshopt_vertex_codec_roundtrip(count, stride):
    rng = np.random.default_rng(count * 7 + stride)
    for a in (rng.integers(0, 256, (count, stride), dtype=np.uint8), np.zeros((count, stride), np.uint8),
              (np.cumsum(rng.integers(-3, 4, (count, stride)), axis=0) % 256).astype(np.uint8)):
        enc = mo.encode_vertex_buffer(a)
        assert enc[0] == 0xA0 and enc[-stride:] == a[0].tobytes()
        assert mo.decode_vertex_buffer(enc, count, stride) == a.tobytes()
        assert mo.encode_vertex_buffer(a) == enc


def test_meshopt_index_sequence_roundtrip():
    rng = np.random.default_rng(5)
    for idx in (np.zeros(0, np.uint32), np.array([0, 1, 2], np.uint32), rng.integers(0, 1 << 30, 300).astype(np.uint32),
                np.sort(rng.integers(0, 5000, 30000)).astype(np.uint32)):
        enc = mo.encode_index_sequence(idx)
        assert enc[0] == 0xD1 and enc[-4:] == b"\0\0\0\0"
        assert mo.decode_index_sequence(enc, idx.size) == idx.tolist()
        assert mo.decode_index_sequence(mo.encode_index_sequence(idx, np.zeros(idx.size)), idx.size) == idx.tolist()
    with pytest.raises(ValueError):
        mo.encode_index_sequence(np.array([1 << 30], np.uint32))
    with pytest.raises(mo.DecodeError):
        mo.decode_vertex_buffer(mo.encode_vertex_buffer(np.ones((20, 4), np.uint8)) + b"\0", 20, 4)  # 꼬리 길이


def _three_dir() -> Path | None:
    for p in (os.environ.get("PHYSICSAI_THREE_DIR"), str(REPO / "frontend" / "node_modules" / "three")):
        if p and (Path(p) / "examples" / "jsm" / "libs" / "meshopt_decoder.module.js").is_file():
            return Path(p)
    return None


def test_meshopt_roundtrip_three_decoder_and_gltfloader(tmp_path):
    """V-C3F-8(Node): three 동봉 MeshoptDecoder로 버퍼 왕복 + GLTFLoader로 GLB(meshopt 켬·끔)를 읽어 정점 수·_NODE_ID 순서·인덱스 대조.
    three는 frontend/node_modules(또는 PHYSICSAI_THREE_DIR) — 없으면 Python 참조 디코더 시험이 같은 비트스트림을 검증한다."""
    three, node = _three_dir(), shutil.which("node")
    if three is None or node is None:
        pytest.skip("node 또는 three(frontend/node_modules) 없음 — Python 참조 디코더 시험으로 대체")
    rng = np.random.default_rng(6)
    job: dict = {"buffers": [], "glbs": []}
    ref: dict[str, bytes] = {}
    for k, (count, stride) in enumerate([(1, 4), (17, 8), (257, 8), (1000, 12), (5000, 4), (70, 256)]):
        a = (np.cumsum(rng.integers(-40, 41, (count, stride)), axis=0) % 256).astype(np.uint8)
        f = tmp_path / f"v{k}.bin"
        f.write_bytes(mo.encode_vertex_buffer(a))
        job["buffers"].append({"file": str(f), "count": count, "stride": stride, "mode": "ATTRIBUTES", "out": str(f) + ".out"})
        ref[str(f)] = a.tobytes()
    for k, n in enumerate([3, 300, 30000]):
        idx = np.sort(rng.integers(0, 60000, n)).astype(np.uint32) if n > 3 else np.array([7, 0, 1 << 29], np.uint32)
        for stride, dt in ((4, "<u4"), (2, "<u2")):
            sub = idx if stride == 4 else idx[idx < 65536]
            f = tmp_path / f"i{k}_{stride}.bin"
            f.write_bytes(mo.encode_index_sequence(sub))
            job["buffers"].append({"file": str(f), "count": int(sub.size), "stride": stride, "mode": "INDICES", "out": str(f) + ".out"})
            ref[str(f)] = sub.astype(dt).tobytes()
    ids, xyz, topo = _grid(30, 20, seed=1)
    _write(tmp_path / "x", ids, xyz, topo, frames=2)
    mans = {}
    for flag in (True, False):
        out = tmp_path / f"out_{flag}"
        mans[flag] = _conv(tmp_path / "x", out, meshopt=flag, lod_min_nodes=100, lod_target_vertices=1000)
        for name in ("contour.glb", "contour_lod.glb"):
            job["glbs"].append({"file": str(out / name), "out": str(out / name) + ".json"})
    jp = tmp_path / "job.json"
    jp.write_text(json.dumps(job))
    r = subprocess.run([node, str(JS), str(three), str(jp)], capture_output=True, text=True, timeout=120, shell=False)
    assert r.returncode == 0, r.stderr[-2000:]
    for j in job["buffers"]:
        assert not os.path.exists(j["out"] + ".err"), Path(j["out"] + ".err").read_text()
        assert Path(j["out"]).read_bytes() == ref[j["file"]], j
    for g in job["glbs"]:
        assert not os.path.exists(g["out"] + ".err"), Path(g["out"] + ".err").read_text()
        got = json.loads(Path(g["out"]).read_text())
        mine = _glb_arrays(Path(g["file"]))
        assert got["count"] == mine["POSITION"].shape[0] and got["normalized"] is True and got["hasNormal"] is False
        assert np.array_equal(np.frombuffer(base64.b64decode(got["position"]), "<i2").reshape(-1, 3), mine["POSITION"])
        assert np.array_equal(np.frombuffer(base64.b64decode(got["attrs"]["_node_id"]), "<u4"), mine["_NODE_ID"])
        assert np.array_equal(np.frombuffer(base64.b64decode(got["index"]), "<u4"), mine["INDICES"])
        if "_SRC" in mine:
            assert np.array_equal(np.frombuffer(base64.b64decode(got["attrs"]["_src"]), "<u4"), mine["_SRC"])
        node = mine["doc"]["nodes"][1]
        assert got["translation"] == pytest.approx(node["translation"]) and got["scale"] == pytest.approx(node["scale"])
    assert mans[True]["mesh"]["sha256"] != mans[False]["mesh"]["sha256"]


# ---- V-C3F-9 정점 순서·GLB 내용 -----------------------------------------------------------------------------------


def test_convert_vertex_order_invariant_and_glb_schema2(tmp_path):
    ids, xyz, topo = _grid(40, 25, seed=2)
    _write(tmp_path / "x", ids, xyz, topo, frames=3)
    out = tmp_path / "out"
    man = _conv(tmp_path / "x", out)
    assert man["schema_version"] == 2 and man["converter_version"] == 2 and man["status"] == "OK" and man["lod"] is None
    me = man["mesh"]
    assert me["nodes"] == ids.size and me["triangles"] == 2 * 39 * 24 and me["compression"] == "meshopt" and me["order"] == "morton"
    g = _glb_arrays(out / "contour.glb")
    doc = g["doc"]
    assert doc["extensionsUsed"] == doc["extensionsRequired"] == ["KHR_mesh_quantization", "EXT_meshopt_compression"]
    assert set(doc["meshes"][0]["primitives"][0]["attributes"]) == {"POSITION", "_NODE_ID"}  # NORMAL 없음
    acc = doc["accessors"]
    assert acc[0]["componentType"] == 5122 and acc[0]["normalized"] and acc[0]["min"] == g["POSITION"].min(axis=0).tolist()
    assert acc[2]["componentType"] == 5125 and doc["bufferViews"][0]["byteStride"] == 8
    assert doc["buffers"][1]["extensions"]["EXT_meshopt_compression"]["fallback"] is True
    nid = g["_NODE_ID"].astype(np.int64)
    assert sorted(nid.tolist()) == sorted(ids.tolist())  # _NODE_ID 무손실
    # 위치 오차 ≤ 축별 bbox 길이 / 65534 / 2
    row = {int(k): i for i, k in enumerate(ids)}
    p0 = xyz[[row[int(k)] for k in nid]]
    span = xyz.max(axis=0) - xyz.min(axis=0)
    span = np.where(span > 0, span, 1)
    assert (np.abs(g["xyz"] - p0) <= span / 65534 / 2 * (1 + 1e-6) + 1e-9).all()
    # 정점 순서 = 레코드 순서: record[i] ≈ f(_NODE_ID[i])
    v, d = _frames(out, man)
    for i in range(3):
        exact = _val(nid.astype(np.float64), i)
        e = man["frames"]["list"][i]
        assert np.abs(v[i] - exact).max() <= (e["max"] - e["min"]) / 131068 * (1 + 1e-6)
        assert e["max"] == exact.max() and nid[e["max_v"]] == nid[np.argmax(exact)] and e["min"] == exact.min()
        de = _disp(nid.astype(np.float64), i)
        rng_c = de.max(axis=0) - de.min(axis=0)
        assert (np.abs(d[i] - de).max(axis=0) <= rng_c / 131070 * (1 + 1e-6) + 1e-12).all()
    assert man["frames"]["record_bytes"] == 2 * ids.size and man["disp"]["record_bytes"] == 6 * ids.size
    assert (out / "contour_frames.bin").stat().st_size == 3 * 2 * ids.size and (out / "contour_disp.bin").stat().st_size == 18 * ids.size
    # Morton 순서(양자화 좌표) — 인접 정점 국소성 + 삼각형은 최소 정점 순 정렬, 감김 유지(+z)
    tri = g["INDICES"].reshape(-1, 3)
    assert (tri[:, 0] < tri[:, 1]).all() and (tri[:, 0] < tri[:, 2]).all() and (np.diff(tri[:, 0].astype(np.int64)) >= 0).all()
    pz = g["xyz"]
    nz = np.cross(pz[tri[:, 1]] - pz[tri[:, 0]], pz[tri[:, 2]] - pz[tri[:, 0]])[:, 2]
    assert (nz > 0).all()


def test_convert_meshopt_false_quantization_only_same_content(tmp_path):
    ids, xyz, topo = _grid(12, 9, seed=3)
    _write(tmp_path / "x", ids, xyz, topo, frames=2)
    a = _conv(tmp_path / "x", tmp_path / "a", meshopt=True)
    b = _conv(tmp_path / "x", tmp_path / "b", meshopt=False)
    ga, gb = _glb_arrays(tmp_path / "a" / "contour.glb"), _glb_arrays(tmp_path / "b" / "contour.glb")
    assert gb["doc"]["extensionsUsed"] == ["KHR_mesh_quantization"] and len(gb["doc"]["buffers"]) == 1
    assert all("extensions" not in v for v in gb["doc"]["bufferViews"]) and b["mesh"]["compression"] == "none"
    for k in ("POSITION", "_NODE_ID", "INDICES"):
        assert np.array_equal(ga[k], gb[k])
    assert a["frames"]["sha256"] == b["frames"]["sha256"]


def test_convert_bytes_deterministic(tmp_path):
    ids, xyz, topo = _grid(15, 10, layers=2, seed=4)
    for name in ("a", "b"):
        _write(tmp_path / f"x{name}", ids, xyz, topo, frames=3)
        _conv(tmp_path / f"x{name}", tmp_path / name, lod_min_nodes=10, lod_target_vertices=1000)
    for f in ("contour.glb", "contour_lod.glb", "contour_frames.bin", "contour_disp.bin", "contour_manifest.json"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f


# ---- V-C3F-6 크기 우선순위 ---------------------------------------------------------------------------------------


def test_size_priority_disp_first_then_resample_then_fail(tmp_path):
    ids, xyz, topo = _grid(10, 6, seed=5)
    n = ids.size
    _write(tmp_path / "x", ids, xyz, topo, frames=10)
    m = _conv(tmp_path / "x", tmp_path / "a", max_disp_bytes=6 * n * 10 - 1)  # 변위 초과 → 변위만 제외, 프레임 수 그대로
    assert m["status"] == "OK" and m["frames"]["count"] == 10 and m["disp"] is None and m["frames"]["has_disp"] is False
    w = [x for x in m["warnings"] if x["code"] == "CONTOUR3D_DISP_DROPPED"]
    assert len(w) == 1 and w[0]["detail"] == "크기" and not (tmp_path / "a" / "contour_disp.bin").exists()
    m = _conv(tmp_path / "x", tmp_path / "b", max_bin_bytes=2 * n * 4)  # 스칼라 초과 → 4프레임 재샘플(첫·끝), 변위도 같은 목록
    assert m["frames"]["count"] == 4 and [e["src"] for e in m["frames"]["list"]] == [0, 3, 6, 9]
    assert m["disp"] is not None and len(m["disp"]["list"]) == 4 and m["sampling"]["total_frames"] == 10
    assert m["limits"]["bin_bytes"] == 8 * n and m["limits"]["disp_bytes"] == 24 * n
    m = _conv(tmp_path / "x", tmp_path / "c", max_bin_bytes=2 * n * 2 - 1)  # 2프레임 미만 → FAIL + limits
    assert m["status"] == "FAIL" and m["code"] == "CONTOUR3D_TOO_LARGE" and m["limits"]["nodes"] == n and "max_bin_bytes" in m["message"]
    m = _conv(tmp_path / "x", tmp_path / "d", max_glb_bytes=1024)
    assert m["code"] == "CONTOUR3D_TOO_LARGE" and m["limits"]["glb_bytes"] > 1024 and m["limits"]["max_glb_bytes"] == 1024
    assert m["mesh"] is None and m["frames"] is None and m["disp"] is None and m["lod"] is None
    m = _conv(tmp_path / "x", tmp_path / "e", max_nodes=n - 1)
    assert m["code"] == "CONTOUR3D_TOO_LARGE" and m["limits"]["nodes"] == n and m["limits"]["max_nodes"] == n - 1
    assert json.loads((tmp_path / "e" / "contour_manifest.json").read_text())["limits"]["nodes"] == n
    m = _conv(tmp_path / "x", tmp_path / "f", max_frames=3)  # TCL보다 작은 max_frames → 균등 재샘플
    assert [e["src"] for e in m["frames"]["list"]] == [0, 4, 9] or [e["src"] for e in m["frames"]["list"]] == [0, 5, 9]


def test_field_empty_discards_temp_files(tmp_path):
    ids, xyz, topo = _grid(6, 5, seed=6)
    _write(tmp_path / "x", ids, xyz, topo, frames=2, nan_every=1)
    seen: list[str] = []
    m = convert(str(tmp_path / "x"), str(tmp_path / "o"), source=SRC, max_nodes=1000, max_bin_bytes=1 << 20, max_frames=50,
                discard=lambda p: (seen.append(os.path.basename(p)), os.remove(p)))
    assert m["status"] == "FAIL" and m["code"] == "CONTOUR3D_FIELD_EMPTY"
    assert sorted(seen) == ["contour_disp.bin.tmp", "contour_frames.bin.tmp"]
    assert sorted(os.listdir(tmp_path / "o")) == ["contour_manifest.json"]


# ---- §9.4 변위 판정·§9.5 부품 범위·§9.2 단위 ------------------------------------------------------------------------


def test_disp_states_scope_and_unit(tmp_path):
    ids, xyz, topo = _grid(6, 5, seed=7)

    def run(name, *, disp=True, extra=(), comps=(), unit="MPa", display_unit=None):
        _write(tmp_path / name, ids, xyz, topo, frames=3, disp=disp, extra=extra, unit=unit)
        return convert(str(tmp_path / name), str(tmp_path / name / "o"), source=SRC, max_nodes=1000, max_bin_bytes=1 << 20, max_frames=50,
                       comps=comps, unit=display_unit)

    codes = lambda m: [w["code"] for w in m["warnings"]]  # noqa: E731
    m = run("none", disp=False, extra=("DISP=NONE", "DISP_REASON=no displacement result type"))
    assert m["status"] == "OK" and m["disp"] is None and codes(m) == ["CONTOUR3D_DISP_UNAVAILABLE"]
    assert m["warnings"][0]["detail"] == "no displacement result type"
    m = run("partial", extra=("DISP=ON", "DISP_MISSING_FRAMES=2"))
    assert m["disp"] is None and codes(m) == ["CONTOUR3D_DISP_UNAVAILABLE"] and "2개" in m["warnings"][0]["message"]
    m = run("skipped", disp=False, extra=("DISP=SKIPPED_NODES",))
    assert m["disp"] is None and codes(m) == ["CONTOUR3D_DISP_DROPPED"] and m["warnings"][0]["detail"] == "노드 수"
    m = run("off", disp=False, extra=("DISP=OFF",))
    assert m["disp"] is None and codes(m) == []
    m = run("on", extra=("DISP=ON", "DISP_MISSING_FRAMES=0", "SCOPE=COMPS"), comps=["B", "A", "A"])
    assert m["disp"] is not None and codes(m) == [] and m["scope"] == {"comps": ["A", "B"], "comps_applicable": True, "applied": True}
    m = run("scope_all", extra=("SCOPE=ALL",), comps=["A"])
    assert codes(m) == ["CONTOUR3D_COMPS_IGNORED"] and m["scope"]["applied"] is False
    # 뒤 프레임 헤더에 변위 열이 없으면 변위 전체 제외(일관성)
    d = tmp_path / "late"
    _write(d, ids, xyz, topo, frames=3)
    (d / "frame_00002.csv").write_text("value\n" + "".join(f"{float(x)!r}\n" for x in _val(ids, 2)))
    m = convert(str(d), str(d / "o"), source=SRC, max_nodes=1000, max_bin_bytes=1 << 20, max_frames=50)
    assert m["disp"] is None and codes(m) == ["CONTOUR3D_DISP_UNAVAILABLE"] and not (d / "o" / "contour_disp.bin").exists()
    # 단위: 오류 문구 → 버림 → 표시 설정 unit
    m = run("unit1", unit='Invalid command syntax: "result scalar unit"', display_unit="MPa")
    assert m["unit"] == "MPa" and m["unit_source"] == "display"
    m = run("unit2", unit="", display_unit=None)
    assert m["unit"] == "" and m["unit_source"] is None
    assert run("unit3")["unit_source"] == "h3d"


# ---- CSV 견고성 ---------------------------------------------------------------------------------------------------


def test_csv_blank_nan_rows_crlf_bom_and_errors(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "nodes.csv").write_bytes(b"\xef\xbb\xbfnode_id,x,y,z\r\n1,0,0,0\r\n2,1,0,0\r\n3,1,1,0\r\n4,0,1,0\r\n\r\n9,5,5,5\r\n")
    (d / "faces.csv").write_text("elem_id,n1,n2,n3,n4\n1,1,2,3\n2,1,3,4,\n")  # 삼각형 행: n4 없음(열 수 다름 → 느린 경로)
    (d / "extract_result.txt").write_text("# contour_extract 1\nSTATUS=OK\nUNIT=MPa\nFRAMES_TOTAL=2\nFRAME=0|0|0\nFRAME=1|5|0.5\n")
    (d / "frame_00000.csv").write_text("value\n1.5\n\n-2\n4\n77\n\n\n")  # 노드 2 = 값 없음(빈 행), 끝의 빈 행 허용
    (d / "frame_00001.csv").write_text("value\r\nnan\r\n2\r\nInf\r\n1e3\r\n0")
    m = _conv(d, tmp_path / "o")
    assert m["status"] == "OK" and m["mesh"]["nodes"] == 4 and m["mesh"]["triangles"] == 2 and m["frames"]["nan_count"] == 3
    v, _d = _frames(tmp_path / "o", m)
    nid = _glb_arrays(tmp_path / "o" / "contour.glb")["_NODE_ID"]
    exp0 = {1: 1.5, 2: np.nan, 3: -2.0, 4: 4.0}
    exp1 = {1: np.nan, 2: 2.0, 3: np.nan, 4: 1000.0}
    for i, exp in enumerate((exp0, exp1)):
        e = np.array([exp[int(k)] for k in nid])
        assert np.array_equal(np.isnan(v[i]), np.isnan(e)) and np.allclose(v[i][~np.isnan(e)], e[~np.isnan(e)], rtol=0, atol=1e-6 * 1000)
    (d / "frame_00001.csv").write_text("value\n1\n2\n3\n")  # 행 모자람
    with pytest.raises(ConvertError) as ei:
        _conv(d, tmp_path / "o2")
    assert ei.value.code == "CONTOUR3D_EXTRACT_INVALID"
    (d / "frame_00001.csv").write_text("value\n1\n2\nabc\n4\n5\n")
    with pytest.raises(ConvertError, match="숫자가 아닙니다"):
        _conv(d, tmp_path / "o3")
    (d / "frame_00001.csv").write_text("value\n1\n2\n3\n4\n5\n6\n")  # 행 남음(빈 행 아님)
    with pytest.raises(ConvertError):
        _conv(d, tmp_path / "o4")


def test_elements_external_faces_two_layer_hex(tmp_path):
    ids, xyz, topo = _grid(5, 4, layers=2, seed=8)
    _write(tmp_path / "x", ids, xyz, topo, frames=2)
    m = _conv(tmp_path / "x", tmp_path / "o")
    # 헥사 4×3 = 12개, 외부 면 = 위·아래 24 + 옆 2·(4+3) = 14 → 38 쿼드 = 76 삼각형, 모든 노드가 외부
    assert m["mesh"]["nodes"] == 40 and m["mesh"]["triangles"] == 76


# ---- V-C3F-10 LOD ----------------------------------------------------------------------------------------------


def test_lod_peak_representative_normal_buckets_and_null(tmp_path):
    ids, xyz, topo = _grid(60, 40, layers=2, dz=0.05, seed=9)  # 얇은 두 겹 판(두께 0.05 ≪ 셀)
    _write(tmp_path / "x", ids, xyz, topo, frames=3)
    out = tmp_path / "o"
    m = _conv(tmp_path / "x", out, lod_min_nodes=1000, lod_target_vertices=1000)
    lod = m["lod"]
    assert lod["method"] == "cluster_peak" and 0 < lod["vertices"] <= 1000 and lod["cell_mm"] > 0.05
    g, lg = _glb_arrays(out / "contour.glb"), _glb_arrays(out / "contour_lod.glb")
    src = lg["_SRC"].astype(np.int64)
    n = g["_NODE_ID"].size
    assert (src < n).all() and (np.diff(src) > 0).all() and np.array_equal(lg["_NODE_ID"], g["_NODE_ID"][src])
    assert np.array_equal(lg["POSITION"], g["POSITION"][src]) and lg["doc"]["nodes"][1] == g["doc"]["nodes"][1]
    # 윗면·아랫면이 합쳐지지 않음: LOD 삼각형 중 위층만·아래층만 쓰는 것이 각각 있고 법선이 +z·−z
    z = lg["xyz"][:, 2]
    tri = lg["INDICES"].reshape(-1, 3)
    top = (z[tri] > 0.025).all(axis=1)
    bot = (z[tri] < 0.025).all(axis=1)
    p = lg["xyz"]
    nz = np.cross(p[tri[:, 1]] - p[tri[:, 0]], p[tri[:, 2]] - p[tri[:, 0]])[:, 2]
    assert top.sum() > 100 and bot.sum() > 100 and (nz[top] > 0).mean() > 0.95 and (nz[bot] < 0).mean() > 0.95
    # 대표 = 군 피크 최대(같으면 작은 노드 ID): 같은 키 규칙으로 다시 계산
    v, _d = _frames(out, m)
    peak = np.nanmax(np.abs(v), axis=0)
    gx = g["xyz"]
    gtri = g["INDICES"].reshape(-1, 3).astype(np.int64)
    bucket = lodmod.vertex_normal_bucket(gx, gtri)
    lo_, span = gx.min(axis=0), gx.max(axis=0) - gx.min(axis=0)
    key = lodmod._keys(gx, lo_, lod["cell_mm"], bucket, lodmod._dims(span, lod["cell_mm"]))
    nid = g["_NODE_ID"].astype(np.int64)
    for s in src:
        members = np.flatnonzero(key == key[s])
        best = members[np.lexsort((nid[members], -peak[members]))[0]]
        assert best == s
    # 전역 최대 정점(극값 마커)은 프레임 목록의 max_v와 같고 LOD에 남는다(피크 우선)
    assert int(np.argmax(peak)) in set(src.tolist())
    assert m["frames"]["list"][-1]["max_v"] == int(np.nanargmax(v[-1]))
    m2 = _conv(tmp_path / "x", tmp_path / "o2", lod_min_nodes=ids.size)  # N ≤ lod_min_nodes → null
    assert m2["lod"] is None and not (tmp_path / "o2" / "contour_lod.glb").exists()


# ---- V-C3F-11 메모리·시간 ----------------------------------------------------------------------------------------


def test_memory_per_node_two_layer_hex_100k_50_frames(tmp_path):
    ids, xyz, topo = _grid(224, 224, layers=2, seed=10)  # 노드 100,352, 헥사 49,729
    _write(tmp_path / "x", ids, xyz, topo, frames=50, link=True)
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        m = _conv(tmp_path / "x", tmp_path / "o", lod_min_nodes=50_000, lod_target_vertices=10_000)
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    dt = time.perf_counter() - t0
    n = m["mesh"]["nodes"]
    print(f"V-C3F-11: nodes={n} frames={m['frames']['count']} time={dt:.1f}s peak={peak / 1e6:.1f}MB ({peak / n:.0f} B/node) "
          f"glb={m['mesh']['bytes']} lod={m['lod']['bytes']}")
    assert m["status"] == "OK" and n == ids.size and m["frames"]["count"] == 50 and m["lod"] is not None
    assert peak / n <= 1200
    assert math.isfinite(dt)


def test_frontend_fixture_generator_deterministic(tmp_path):
    """V-C3F-8 픽스처 생성(Backend 스크립트): meshopt·plain 두 벌, expected.json = 같은 디코드 값, 다시 만들면 바이트 동일."""
    from physicsai_core.contour3d.fixture import generate

    generate(str(tmp_path / "a"))
    generate(str(tmp_path / "b"))
    for sub in ("meshopt", "plain"):
        for f in ("contour.glb", "contour_lod.glb", "contour_frames.bin", "contour_disp.bin", "contour_manifest.json", "expected.json"):
            assert (tmp_path / "a" / sub / f).read_bytes() == (tmp_path / "b" / sub / f).read_bytes(), (sub, f)
    ea = json.loads((tmp_path / "a" / "meshopt" / "expected.json").read_text())
    eb = json.loads((tmp_path / "a" / "plain" / "expected.json").read_text())
    assert ea == eb and ea["contour.glb"]["count"] == 768 and "_SRC" in ea["contour_lod.glb"]
    man = json.loads((tmp_path / "a" / "meshopt" / "contour_manifest.json").read_text())
    assert man["frames"]["nan_count"] == 3 and man["disp"] is not None and man["lod"]["vertices"] == ea["contour_lod.glb"]["count"]


def test_committed_frontend_fixture_is_current(tmp_path):
    """V-C3F-8: 프런트가 커밋한 서버 인코더 픽스처(frontend/src/__tests__/fixtures/c3f_server, `--b64`)가 현재 인코더 출력과 같다.
    인코더·변환기를 바꾸면 `python -m physicsai_core.contour3d.fixture frontend/src/__tests__/fixtures/c3f_server --b64`로 다시 만든다."""
    from pathlib import Path

    from physicsai_core.contour3d.fixture import generate

    committed = Path(__file__).resolve().parents[2] / "frontend" / "src" / "__tests__" / "fixtures" / "c3f_server"
    if not committed.is_dir():
        pytest.skip("frontend 픽스처 폴더 없음(백엔드만 배포한 묶음)")
    generate(str(tmp_path), b64=True)
    names = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert names == sorted(str(p.relative_to(committed)) for p in committed.rglob("*") if p.is_file())
    for n in names:
        if n.endswith(("contour_frames.bin.b64", "contour_disp.bin.b64", "contour_manifest.json")):
            continue  # sin·cos로 만든 값은 플랫폼 libm 차이로 마지막 비트가 다를 수 있다 — 형상(정수·좌표 격자)만 바이트 비교
        assert (tmp_path / n).read_bytes() == (committed / n).read_bytes(), f"{n} 픽스처가 낡았습니다 — 다시 생성하세요"
    sizes = {n: len((tmp_path / n).read_bytes()) for n in names if n.endswith(("frames.bin.b64", "disp.bin.b64"))}
    assert sizes == {n: len((committed / n).read_bytes()) for n in sizes}  # 프레임·변위는 크기만 같으면 된다
