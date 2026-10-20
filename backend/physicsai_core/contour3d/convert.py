"""hw 추출 CSV → `contour.glb`·`contour_frames.bin`·`contour_manifest.json`(geometry-view.md §13.4).

입력(추출 폴더): extract_result.txt, nodes.csv, faces.csv(외부 면) 또는 elements.csv(요소 연결 전체 — 대체 경로, 외부 면을 여기서 계산),
frame_<5자리>.csv. 결정적 실패(노드 수 상한 `CONTOUR3D_TOO_LARGE`, 값 없음 `CONTOUR3D_FIELD_EMPTY`)는 FAIL manifest를 돌려준다
(작업 성공 + 결과 FAIL로 캐시). 파일 불일치는 `ConvertError(CONTOUR3D_EXTRACT_INVALID)`(인프라 실패, 캐시 안 함).
`contour_frames.bin` = 프레임 우선 Float32 LE: record(i) = scalar[N] + (has_disp) disp[N][3], 노드 순서 = GLB 정점 순서.
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
import sys
from array import array
from collections.abc import Callable, Mapping
from typing import Any

from ..fileutil import write_json
from .glb import write_glb
from .settings import CONVERTER_VERSION, OUT_FRAMES, OUT_GLB, OUT_MANIFEST, RESULT_NAME, TCL_STATUS_CODE, message_ko, parse_result

INVALID = "CONTOUR3D_EXTRACT_INVALID"
NAN = float("nan")
# 솔리드 요소 면(HyperView config → 노드 인덱스, 바깥쪽 법선 순서)
SOLID_FACES: dict[int, tuple[tuple[int, ...], ...]] = {
    204: ((0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)),
    205: ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
    206: ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)),
    208: ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)),
}
SHELL_CONFIGS = (103, 104)


class ConvertError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _rows(path: str, header0: str) -> tuple[list[str], list[list[str]]]:
    if not os.path.isfile(path):
        raise ConvertError(INVALID, f"{os.path.basename(path)}이(가) 없습니다")
    with open(path, encoding="utf-8", newline="") as fh:
        rd = csv.reader(fh)
        head = [h.strip().lstrip("﻿") for h in next(rd, [])]
        if not head or head[0] != header0:
            raise ConvertError(INVALID, f"{os.path.basename(path)} 헤더 오류: {','.join(head)[:80]}")
        return head, [r for r in rd if r and any(c.strip() for c in r)]


def _int(s: str) -> int | None:
    s = (s or "").strip()
    try:
        return int(float(s)) if s else None
    except ValueError:
        raise ConvertError(INVALID, f"정수가 아닙니다: {s[:20]}") from None


def _float(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return NAN
    try:
        return float(s)
    except ValueError:
        raise ConvertError(INVALID, f"숫자가 아닙니다: {s[:20]}") from None


def read_nodes(path: str) -> tuple[list[int], list[float]]:
    _h, rows = _rows(path, "node_id")
    ids: list[int] = []
    xyz: list[float] = []
    for r in rows:
        if len(r) < 4:
            raise ConvertError(INVALID, "nodes.csv 행의 열이 모자랍니다")
        nid = _int(r[0])
        if nid is None:
            raise ConvertError(INVALID, "nodes.csv에 빈 node_id가 있습니다")
        p = [_float(r[1]), _float(r[2]), _float(r[3])]
        if not all(math.isfinite(v) for v in p):
            raise ConvertError(INVALID, f"노드 {nid} 좌표가 유한하지 않습니다")
        ids.append(nid)
        xyz.extend(p)
    if len(set(ids)) != len(ids):
        raise ConvertError(INVALID, "nodes.csv에 같은 node_id가 두 번 있습니다")
    return ids, xyz


def external_faces(path: str) -> list[tuple[int, list[int]]]:
    """elements.csv(elem_id,config,n1..n8) → 외부 면 [(elem_id, 노드 ID 3·4개)]. 쉘(103·104) = 요소 그대로, 솔리드 = 한 번만 나온 면."""
    _h, rows = _rows(path, "elem_id")
    shells: list[tuple[int, list[int]]] = []
    seen: dict[tuple[int, ...], tuple[int, list[int], int]] = {}
    order = 0
    for r in rows:
        eid, cfg = _int(r[0]), _int(r[1]) if len(r) > 1 else None
        nodes = [n for n in (_int(c) for c in r[2:10]) if n is not None]
        if eid is None or cfg is None:
            raise ConvertError(INVALID, "elements.csv 행에 elem_id·config가 없습니다")
        if cfg in SHELL_CONFIGS:
            shells.append((eid, nodes[:3 if cfg == 103 else 4]))
        elif cfg in SOLID_FACES:
            for f in SOLID_FACES[cfg]:
                if max(f) >= len(nodes):
                    raise ConvertError(INVALID, f"요소 {eid} 연결 노드 수가 모자랍니다")
                fn = [nodes[i] for i in f]
                key = tuple(sorted(fn))
                if key in seen:
                    seen[key] = (seen[key][0], seen[key][1], seen[key][2] + 1)
                else:
                    seen[key] = (eid, fn, 1)
                    order += 1
    solid = [(eid, fn) for eid, fn, cnt in seen.values() if cnt == 1]
    return shells + solid


def read_faces(path: str) -> list[tuple[int, list[int]]]:
    _h, rows = _rows(path, "elem_id")
    out = []
    for r in rows:
        eid = _int(r[0])
        nodes = [n for n in (_int(c) for c in r[1:5]) if n is not None]
        if eid is None or len(nodes) < 3:
            raise ConvertError(INVALID, "faces.csv 행의 노드가 3개 미만입니다")
        out.append((eid, nodes))
    return out


def _triangulate(faces: list[tuple[int, list[int]]], index: dict[int, int], xyz: list[float]) -> tuple[list[int], int]:
    """쿼드 → (n1,n2,n3)+(n1,n3,n4), n3=n4는 삼각형 1개(§4.1 FE 규칙). 퇴화(같은 노드·면적 0)는 건너뜀 → (indices, 건너뛴 수)."""
    idx: list[int] = []
    skipped = 0
    for _eid, nodes in faces:
        if any(n not in index for n in nodes):
            raise ConvertError(INVALID, "면이 nodes.csv에 없는 노드를 참조합니다")
        tris = [(nodes[0], nodes[1], nodes[2])]
        if len(nodes) == 4 and nodes[3] != nodes[2]:
            tris.append((nodes[0], nodes[2], nodes[3]))
        for t in tris:
            a, b, c = (index[n] for n in t)
            if len({a, b, c}) < 3 or _area2(xyz, a, b, c) <= 1e-24:
                skipped += 1
                continue
            idx.extend((a, b, c))
    return idx, skipped


def _cross(xyz: list[float], a: int, b: int, c: int) -> tuple[float, float, float]:
    ax, ay, az = xyz[3 * a:3 * a + 3]
    bx, by, bz = xyz[3 * b:3 * b + 3]
    cx, cy, cz = xyz[3 * c:3 * c + 3]
    ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
    return uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx


def _area2(xyz: list[float], a: int, b: int, c: int) -> float:
    x, y, z = _cross(xyz, a, b, c)
    return x * x + y * y + z * z


def _normals(xyz: list[float], idx: list[int], n: int) -> list[float]:
    acc = [0.0] * (3 * n)
    for k in range(0, len(idx), 3):
        a, b, c = idx[k], idx[k + 1], idx[k + 2]
        x, y, z = _cross(xyz, a, b, c)
        for v in (a, b, c):
            acc[3 * v] += x
            acc[3 * v + 1] += y
            acc[3 * v + 2] += z
    for v in range(n):
        x, y, z = acc[3 * v:3 * v + 3]
        ln = math.sqrt(x * x + y * y + z * z)
        acc[3 * v:3 * v + 3] = [x / ln, y / ln, z / ln] if ln > 0 else [0.0, 0.0, 1.0]
    return acc


def resample(total: int, k: int) -> list[int]:
    """균등 포함 샘플링(첫·끝 포함, 중복 제거) — TCL과 같은 규칙(§13.3)."""
    if total <= k:
        return list(range(total))
    out: list[int] = []
    for i in range(k):
        s = int(round(i * (total - 1) / (k - 1)))
        if not out or out[-1] != s:
            out.append(s)
    return out


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _fail(base: dict[str, Any], code: str, out_dir: str, detail: str | None = None) -> dict[str, Any]:
    doc = {**base, "status": "FAIL", "code": code, "message": (message_ko(code) or code) + (f" — {detail}" if detail else ""),
           "mesh": None, "frames": None, "range": None}
    os.makedirs(out_dir, exist_ok=True)
    write_json(os.path.join(out_dir, OUT_MANIFEST), doc)
    return doc


def convert(extract_dir: str, out_dir: str, *, source: Mapping[str, Any], max_nodes: int, max_bin_bytes: int, max_frames: int,
            progress: Callable[[float, str], None] | None = None, checkpoint: Callable[[], None] | None = None,
            discard: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """추출 폴더 → out_dir 3종. 반환 = manifest(dict). 인프라 불일치는 ConvertError.
    discard(path) = 값 없음 실패 때 쓰다 만 프레임 임시 파일 처리(워커가 캐시 삭제 지점 cache_store로 넘김, 없으면 0바이트로 비움)."""
    prog = progress or (lambda _p, _m: None)
    tick = checkpoint or (lambda: None)
    rp = os.path.join(extract_dir, RESULT_NAME)
    if not os.path.isfile(rp):
        raise ConvertError(INVALID, "extract_result.txt가 없습니다")
    with open(rp, encoding="utf-8", errors="replace") as fh:
        res = parse_result(fh.read())
    if res["status"] != "OK":
        code = TCL_STATUS_CODE.get(str(res["status"]), INVALID)
        raise ConvertError(code, f"추출 상태 {res['status']}: {res['message'] or ''}".strip())
    base: dict[str, Any] = {"schema_version": 1, "kind": "contour3d", "status": "OK", "code": None, "message": None,
                            "source": dict(source), "display": {"field": res["field"], "comp": res["dcomp"], "avgmode": res["avgmode"]},
                            "unit": res["unit"], "length_unit": "mm", "up_axis": "Z", "warnings": [], "converter_version": CONVERTER_VERSION}
    prog(2, "형상 읽기")
    ids, xyz_all = read_nodes(os.path.join(extract_dir, "nodes.csv"))
    fp, ep = os.path.join(extract_dir, "faces.csv"), os.path.join(extract_dir, "elements.csv")
    faces = read_faces(fp) if os.path.isfile(fp) else external_faces(ep) if os.path.isfile(ep) else None
    if faces is None:
        raise ConvertError(INVALID, "faces.csv·elements.csv가 모두 없습니다")
    tick()
    used = {n for _e, f in faces for n in f}
    keep = [i for i, nid in enumerate(ids) if nid in used]  # 외부 면 노드만(대체 경로는 내부 노드를 뺀다), 원래 행 순서 유지
    if len(keep) > max_nodes:
        return _fail(base, "CONTOUR3D_TOO_LARGE", out_dir, f"외부 면 노드 {len(keep)}개 > 상한 {max_nodes}")
    vid = [ids[i] for i in keep]
    xyz = [xyz_all[3 * i + k] for i in keep for k in range(3)]
    index = {nid: j for j, nid in enumerate(vid)}
    idx, skipped = _triangulate(faces, index, xyz)
    if not idx:
        raise ConvertError(INVALID, "삼각형이 하나도 없습니다(퇴화 면만 있음)")
    if skipped:
        base["warnings"].append({"code": "CONTOUR3D_FACE_SKIPPED", "count": skipped, "message": message_ko("CONTOUR3D_FACE_SKIPPED")})
    prog(20, "형상 변환")
    glb = write_glb(xyz, _normals(xyz, idx, len(vid)), vid, idx)
    tick()
    # ---- 프레임 ----
    frames = sorted(res["frames"])
    if not frames:
        raise ConvertError(INVALID, "추출 결과에 프레임이 없습니다")
    if [f[0] for f in frames] != list(range(len(frames))):
        raise ConvertError(INVALID, "프레임 번호가 0부터 연속이 아닙니다")
    if len(frames) > max_frames:
        frames = [frames[i] for i in resample(len(frames), max_frames)]
    paths = [os.path.join(extract_dir, f"frame_{f[0]:05d}.csv") for f in frames]
    if not all(os.path.isfile(p) for p in paths):
        raise ConvertError(INVALID, "frame_*.csv 파일 수가 FRAME 줄 수와 다릅니다")
    with open(paths[0], encoding="utf-8", newline="") as fh:
        head0 = [h.strip().lstrip("﻿") for h in next(csv.reader(fh), [])]
    has_disp = head0[:4] == ["value", "dx", "dy", "dz"]
    if head0[:1] != ["value"]:
        raise ConvertError(INVALID, "frame 헤더는 value[,dx,dy,dz]여야 합니다")
    n = len(vid)
    total_frames = res["frames_total"] or len(res["frames"])  # h3d 전체 프레임 수(TCL 샘플링 전)
    rec = 4 * n * (1 + 3 * has_disp)
    if rec * len(frames) > max_bin_bytes:
        k = max_bin_bytes // rec
        if k >= 2:
            frames = [frames[i] for i in resample(len(frames), int(k))]
        elif has_disp:
            has_disp = False
            rec = 4 * n
            base["warnings"].append({"code": "CONTOUR3D_DISP_DROPPED", "message": message_ko("CONTOUR3D_DISP_DROPPED")})
            k = max_bin_bytes // rec
            if k < 2:
                return _fail(base, "CONTOUR3D_TOO_LARGE", out_dir, "프레임 2개도 상한(contour3d.max_bin_bytes)을 넘습니다")
            frames = [frames[i] for i in resample(len(frames), int(k))] if rec * len(frames) > max_bin_bytes else frames
        else:
            return _fail(base, "CONTOUR3D_TOO_LARGE", out_dir, "프레임 2개도 상한(contour3d.max_bin_bytes)을 넘습니다")
    os.makedirs(out_dir, exist_ok=True)
    bin_path = os.path.join(out_dir, OUT_FRAMES)
    tmp = bin_path + ".tmp"
    listing: list[dict[str, Any]] = []
    nan_total, gmin, gmax = 0, math.inf, -math.inf
    with open(tmp, "wb") as out:
        for i, (out_idx, src, t) in enumerate(frames):
            tick()
            head, rows = _rows(os.path.join(extract_dir, f"frame_{out_idx:05d}.csv"), "value")
            if len(rows) != len(ids):
                raise ConvertError(INVALID, f"frame_{out_idx:05d}.csv 행 수({len(rows)})가 nodes.csv({len(ids)})와 다릅니다")
            sc = array("f")
            dp = array("f")
            fmin, fmax = math.inf, -math.inf
            for j in keep:
                r = rows[j]
                v = _float(r[0]) if r else NAN
                if not math.isfinite(v):
                    v = NAN
                    nan_total += 1
                else:
                    fmin, fmax = min(fmin, v), max(fmax, v)
                sc.append(v)
                if has_disp:
                    d = [_float(r[c]) if len(r) > c else NAN for c in (1, 2, 3)]
                    dp.extend(x if math.isfinite(x) else 0.0 for x in d)
            for a in ((sc, dp) if has_disp else (sc,)):
                if sys.byteorder == "big":
                    a.byteswap()
                out.write(a.tobytes())
            ok = math.isfinite(fmin)
            listing.append({"i": i, "src": src, "time": t, "min": fmin if ok else None, "max": fmax if ok else None})
            if ok:
                gmin, gmax = min(gmin, fmin), max(gmax, fmax)
            prog(30 + 70 * (i + 1) / len(frames), f"프레임 변환 {i + 1}/{len(frames)}")
    if nan_total > 0.5 * n * len(frames):
        if discard is not None:
            discard(tmp)
        else:
            open(tmp, "wb").close()
        return _fail(base, "CONTOUR3D_FIELD_EMPTY", out_dir, f"값 없는 노드 비율 {nan_total / (n * len(frames)):.0%}")
    os.replace(tmp, bin_path)
    glb_path = os.path.join(out_dir, OUT_GLB)
    with open(glb_path, "wb") as fh:
        fh.write(glb)
    doc = {**base,
           "mesh": {"file": OUT_GLB, "sha256": hashlib.sha256(glb).hexdigest(), "bytes": len(glb), "nodes": n, "triangles": len(idx) // 3},
           "frames": {"file": OUT_FRAMES, "sha256": _sha(bin_path), "bytes": os.path.getsize(bin_path), "count": len(frames),
                      "record_bytes": rec, "has_disp": bool(has_disp), "dtype": "float32", "nan_count": nan_total, "list": listing},
           "range": {"min": gmin if math.isfinite(gmin) else None, "max": gmax if math.isfinite(gmax) else None},
           "sampling": {"total_frames": total_frames, "max_frames": max_frames, "rule": "uniform_inclusive"}}
    write_json(os.path.join(out_dir, OUT_MANIFEST), doc)
    return doc
