"""hw 추출 CSV → `contour.glb`·(선택)`contour_lod.glb`·`contour_frames.bin`·(선택)`contour_disp.bin`·`contour_manifest.json`
(schema 2 — contour3d-field.md §4·§5·§7·§9.6, geometry-view.md GV-C5). numpy 배열 기반, 프레임 단위 스트리밍(워커 전용 import).

입력(추출 폴더): extract_result.txt, nodes.csv, faces.csv(외부 면) 또는 elements.csv(요소 연결 전체 — 외부 면을 여기서 계산),
frame_<5자리>.csv(헤더 `value` 또는 `value,dx,dy,dz`, nodes.csv 행 순서, 빈 칸 = 값 없음).
- 정점 = 외부 면 노드, 순서 = 양자화 좌표 Morton 코드(같으면 노드 ID) — **정점 i = 모든 프레임 레코드의 i번째 값**(C3F-3).
- `contour_frames.bin` record(i) = uint16[N](프레임별 min·scale 양자화, 65535 = NaN), `contour_disp.bin` record(i) = uint16[N][3].
- 크기 판정(§5.4): 노드 → 형상 GLB(LOD 포함) → 변위 먼저 제외 → 스칼라 재샘플(최소 2). 결정적 실패(`CONTOUR3D_TOO_LARGE`·
  `CONTOUR3D_FIELD_EMPTY`)는 FAIL manifest(limits 포함)를 돌려준다. 파일 불일치는 `ConvertError(CONTOUR3D_EXTRACT_INVALID)`.
결정성: 같은 입력이면 모든 출력 파일 바이트가 같다.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, BinaryIO

import numpy as np

from ..fileutil import write_json
from . import glb as glbmod
from . import lod as lodmod
from . import meshopt as mo
from .settings import (
    CONVERTER_VERSION,
    MESSAGES,
    OUT_DISP,
    OUT_FRAMES,
    OUT_GLB,
    OUT_LOD,
    OUT_MANIFEST,
    RESULT_NAME,
    TCL_STATUS_CODE,
    clean_unit,
    message_ko,
    normalize_comps,
    parse_result,
)

INVALID = "CONTOUR3D_EXTRACT_INVALID"
SCHEMA_VERSION = 2
NAN_CODE = 65535
SCALAR_STEPS = 65534  # 스칼라 q ∈ [0, 65534], 65535 예약
DISP_STEPS = 65535
# 상한 기본값(contour3d-field.md §8 — 실제 값은 설정 contour3d.*에서 워커가 넘긴다)
DEFAULT_MAX_GLB_BYTES = 64 << 20
DEFAULT_MAX_DISP_BYTES = 1 << 30
DEFAULT_LOD_MIN_NODES = 500_000
DEFAULT_LOD_TARGET_VERTICES = 100_000
CHUNK_BYTES = 8 << 20  # CSV 스트리밍 단위(완결된 행만)
# 솔리드 요소 면(HyperView config → 노드 인덱스, 바깥쪽 법선 순서)
SOLID_FACES: dict[int, tuple[tuple[int, ...], ...]] = {
    204: ((0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)),
    205: ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
    206: ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)),
    208: ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)),
}
SHELL_CONFIGS = (103, 104)
# HyperMesh config = 100(2D)/200(3D) + 노드 수. 2차 요소 → 같은 모양의 1차 요소(꼭짓점 노드만 쓴다 — HyperMesh 노드 순서는 꼭짓점이 먼저). 중간 노드는 면 계산에 쓰지 않는다
CONFIG_ALIAS: dict[int, int] = {106: 103, 108: 104, 210: 204, 213: 205, 215: 206, 220: 208}


class ConvertError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _cfg_text(d: Mapping[int, int]) -> str:
    return "{" + ", ".join(f"{k}: {v}" for k, v in sorted(d.items())) + "}"


def _msg(code: str) -> str:
    return MESSAGES.get(code) or message_ko(code) or code


def _warn(code: str, detail: str | None = None, **extra: Any) -> dict[str, Any]:
    w: dict[str, Any] = {"code": code, "message": _msg(code) + (f" — {detail}" if detail else "")}
    if detail:
        w["detail"] = detail
    w.update(extra)
    return w


# ---- CSV(스트리밍) ------------------------------------------------------------------------------------------------


def _open(path: str) -> BinaryIO:
    if not os.path.isfile(path):
        raise ConvertError(INVALID, f"{os.path.basename(path)}이(가) 없습니다")
    return open(path, "rb")


def _header(fh: BinaryIO, path: str, header0: str) -> list[str]:
    line = fh.readline().decode("utf-8", errors="replace")
    head = [h.strip().lstrip("﻿") for h in line.strip("\r\n").split(",")] if line.strip() else []
    if not head or head[0] != header0:
        raise ConvertError(INVALID, f"{os.path.basename(path)} 헤더 오류: {','.join(head)[:80]}")
    return head


def _blocks(fh: BinaryIO, tick: Callable[[], None]) -> Iterator[bytes]:
    """남은 본문을 완결된 행 묶음(끝은 늘 `\\n`)으로 나눠 준다."""
    rest = b""
    while True:
        buf = fh.read(CHUNK_BYTES)
        if not buf:
            if rest:
                yield rest + b"\n"
            return
        buf = rest + buf
        cut = buf.rfind(b"\n")
        if cut < 0:
            rest = buf
            continue
        rest = buf[cut + 1:]
        tick()
        yield buf[:cut + 1]


def _parse_block(block: bytes, ncol: int, blank_nan: bool, name: str, base_row: int = 0) -> np.ndarray:
    """행 묶음 → float64 [m, ncol]. 빈 칸·모자란 열 = NaN, 넘치는 열은 버림. blank_nan=False면 빈 행을 건너뛴다."""
    b = block.replace(b"\r", b"")
    if not blank_nan:
        while b"\n\n" in b:
            b = b.replace(b"\n\n", b"\n")
        b = b.lstrip(b"\n")
        if not b:
            return np.zeros((0, ncol))
    b = b"\n" + b
    b = b.replace(b"\n,", b"\nnan,").replace(b",\n", b",nan\n")
    while b",," in b:
        b = b.replace(b",,", b",nan,")
    while b"\n\n" in b:
        b = b.replace(b"\n\n", b"\nnan\n")
    b = b[1:]
    try:
        lines = b.decode("utf-8", errors="replace").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        # 행 목록 입력: BytesIO보다 Python 할당이 적다(tracemalloc 측정 오버헤드 포함 가장 빠름)
        arr = np.loadtxt(lines, delimiter=",", dtype=np.float64, ndmin=2, comments=None)
        del lines
        if arr.shape[1] >= ncol:
            return arr[:, :ncol]
    except ValueError:
        pass
    return _parse_slow(b, ncol, name, blank_nan, base_row)


# 프레임 값 칸의 비정상 부동소수 표기(Windows `1.#QNAN`·`-1.#IND`·`Infinity` 등) — 값 없음(NaN)으로 본다
_NAN_LIKE = re.compile(rb"-?nan|[+-]?inf|-?1\.#ind|-?1\.#qnan|#qnan|-?1\.#inf", re.IGNORECASE)


def _parse_slow(b: bytes, ncol: int, name: str, lenient: bool = False, base_row: int = 0) -> np.ndarray:
    rows = b.split(b"\n")
    if rows and rows[-1] == b"":
        rows.pop()
    out = np.full((len(rows), ncol), np.nan)
    for i, r in enumerate(rows):
        for k, c in enumerate(r.split(b",")[:ncol]):
            s = c.strip()
            if s and s != b"nan":
                try:
                    out[i, k] = float(s)
                except ValueError:
                    if lenient and _NAN_LIKE.fullmatch(s):
                        continue  # 값 없음(NaN)
                    raise ConvertError(
                        INVALID, f"{name} {base_row + i + 2}번째 줄 {k + 1}번째 칸: 숫자가 아닙니다: {s[:20].decode('utf-8', 'replace')}") from None
    return out


def _read_table(path: str, header0: str, ncol: int, tick: Callable[[], None]) -> np.ndarray:
    name = os.path.basename(path)
    with _open(path) as fh:
        _header(fh, path, header0)
        parts = [_parse_block(blk, ncol, False, name) for blk in _blocks(fh, tick)]
    return np.concatenate(parts) if parts else np.zeros((0, ncol))


def _read_frame(path: str, nrows: int, tick: Callable[[], None]) -> tuple[list[str], np.ndarray]:
    """frame CSV → (헤더, float64 [nrows, 1|4]). 빈 행 = NaN 행, 끝의 남는 빈 행만 허용."""
    name = os.path.basename(path)
    with _open(path) as fh:
        head = _header(fh, path, "value")
        ncol = 4 if head[:4] == ["value", "dx", "dy", "dz"] else 1
        out = np.empty((nrows, ncol))
        row = 0
        extra = False
        for blk in _blocks(fh, tick):
            if extra:
                if blk.strip():
                    row = -1
                    break
                continue
            cnt = blk.count(b"\n")
            if row + cnt > nrows:
                parts = blk.split(b"\n", nrows - row)
                if parts[-1].strip():
                    row = -1
                    break
                blk = b"\n".join(parts[:-1]) + b"\n" if nrows > row else b""
                extra = True
                cnt = nrows - row
            if cnt:
                a = _parse_block(blk, ncol, True, name, row)
                if a.shape[0] != cnt:
                    raise ConvertError(INVALID, f"{name} {row + 2}번째 줄 부근: 행을 읽지 못했습니다(읽은 행 {a.shape[0]} != 기대 {cnt})")
                out[row:row + cnt] = a
                row += cnt
    if row != nrows:
        raise ConvertError(INVALID, f"{name} 데이터 행 수가 nodes.csv({nrows})와 다릅니다(읽은 행 {row if row >= 0 else '초과'}, 검사: 프레임 행 수 == 노드 수)")
    return head, out


# ---- 형상 --------------------------------------------------------------------------------------------------------


def read_nodes(path: str, tick: Callable[[], None] = lambda: None) -> tuple[np.ndarray, np.ndarray]:
    """nodes.csv → (ids int64 [n], xyz float64 [n,3])."""
    t = _read_table(path, "node_id", 4, tick)
    raw = t[:, 0]
    if not np.isfinite(raw).all():
        raise ConvertError(INVALID, f"nodes.csv {int(np.argmax(~np.isfinite(raw))) + 2}번째 줄: 빈 node_id가 있습니다")
    if (raw != np.floor(raw)).any() or (raw < 0).any() or (raw > 0xFFFFFFFF).any():
        raise ConvertError(INVALID, f"nodes.csv {int(np.argmax((raw != np.floor(raw)) | (raw < 0) | (raw > 0xFFFFFFFF))) + 2}번째 줄: node_id는 0 이상 4294967295 이하 정수여야 합니다")
    ids = raw.astype(np.int64)
    xyz = t[:, 1:4]
    bad = ~np.isfinite(xyz).all(axis=1)
    if bad.any():
        raise ConvertError(INVALID, f"nodes.csv {int(np.argmax(bad)) + 2}번째 줄: 노드 {int(ids[np.argmax(bad)])} 좌표가 유한하지 않습니다")
    # 같은 node_id가 여러 행이어도 허용(면 참조는 첫 행, 프레임 값은 행 단위) — HyperView 다중 모델 결과 대비
    return ids, np.ascontiguousarray(xyz)


def _ints(a: np.ndarray) -> np.ndarray:
    """float(NaN 포함) → int64, NaN = −1."""
    out = np.full(a.shape, -1, dtype=np.int64)
    m = np.isfinite(a)
    if (a[m] != np.floor(a[m])).any() or (a[m] < 0).any():
        raise ConvertError(INVALID, "노드·요소 번호는 0 이상 정수여야 합니다(csv의 n1.. 열 검사)")
    out[m] = a[m].astype(np.int64)
    return out


def external_faces(path: str, tick: Callable[[], None] = lambda: None, unknown: dict[int, int] | None = None) -> np.ndarray:
    """elements.csv(elem_id,config,n1..n8) → 외부 면 노드 ID int64 [K,4](삼각형은 4번째 −1).
    쉘(103·104) = 요소 그대로, 솔리드 = 한 번만 나온 면(정렬 키 lexsort → 같은 면 묶음 크기 1)."""
    t = _read_table(path, "elem_id", 10, tick)
    if t.shape[0] and not np.isfinite(t[:, :2]).all():
        raise ConvertError(INVALID, f"elements.csv {int(np.argmax(~np.isfinite(t[:, :2]).all(axis=1))) + 2}번째 줄: elem_id·config가 없습니다")
    eid = t[:, 0]
    cfg = t[:, 1].astype(np.int64) if t.shape[0] else np.zeros(0, dtype=np.int64)
    for k, v in CONFIG_ALIAS.items():
        cfg[cfg == k] = v
    if unknown is not None and cfg.size:  # 인식하지 못한 config는 건너뛰되 개수를 알린다
        known = np.isin(cfg, list(SHELL_CONFIGS) + list(SOLID_FACES))
        for c, cnt in zip(*np.unique(cfg[~known], return_counts=True)):
            unknown[int(c)] = int(cnt)
    conn = _ints(t[:, 2:10])
    shells: list[np.ndarray] = []
    for c in SHELL_CONFIGS:
        rows = conn[cfg == c]
        if not rows.size:
            continue
        f = np.full((rows.shape[0], 4), -1, dtype=np.int64)
        f[:, :3] = rows[:, :3]
        if c == 104:
            f[:, 3] = rows[:, 3]
        if (f[:, :3] < 0).any():
            raise ConvertError(INVALID, f"elements.csv 쉘 요소(config {c})의 노드가 모자랍니다")
        shells.append(f)
    cand: list[np.ndarray] = []
    for c, tmpl in SOLID_FACES.items():
        sel = cfg == c
        rows = conn[sel]
        if not rows.size:
            continue
        need = max(max(f) for f in tmpl)
        short = (rows[:, :need + 1] < 0).any(axis=1)
        if short.any():
            raise ConvertError(INVALID, f"요소 {int(eid[sel][np.argmax(short)])} 연결 노드 수가 모자랍니다")
        for f in tmpl:
            x = np.full((rows.shape[0], 4), -1, dtype=np.int64)
            x[:, :len(f)] = rows[:, list(f)]
            cand.append(x)
    tick()
    solid = np.zeros((0, 4), dtype=np.int64)
    if cand:
        allf = np.concatenate(cand)
        del cand
        key = np.sort(allf, axis=1)
        order = np.lexsort((key[:, 3], key[:, 2], key[:, 1], key[:, 0]))
        ks = key[order]
        del key
        start = np.ones(ks.shape[0], dtype=bool)
        start[1:] = (ks[1:] != ks[:-1]).any(axis=1)
        del ks
        bounds = np.flatnonzero(np.append(start, True))
        single = order[bounds[:-1][np.diff(bounds) == 1]]
        solid = allf[np.sort(single)]
    return np.concatenate(shells + [solid]) if shells else solid


def read_faces(path: str, tick: Callable[[], None] = lambda: None) -> np.ndarray:
    """faces.csv(elem_id,n1..n4) → 노드 ID int64 [K,4](삼각형은 4번째 −1)."""
    t = _read_table(path, "elem_id", 5, tick)
    f = _ints(t[:, 1:5])
    if t.shape[0] and (not np.isfinite(t[:, 0]).all() or (f[:, :3] < 0).any()):
        raise ConvertError(INVALID, f"faces.csv {int(np.argmax(~np.isfinite(t[:, 0]) | (f[:, :3] < 0).any(axis=1))) + 2}번째 줄: 노드가 3개 미만이거나 elem_id가 없습니다")
    return f


def morton_order(q: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """양자화 좌표(int16 [N,3]) Morton 코드 오름차순(같으면 노드 ID) 순열."""
    def part(x: np.ndarray) -> np.ndarray:
        x = x & np.uint64(0x1FFFFF)
        x = (x | (x << np.uint64(32))) & np.uint64(0x1F00000000FFFF)
        x = (x | (x << np.uint64(16))) & np.uint64(0x1F0000FF0000FF)
        x = (x | (x << np.uint64(8))) & np.uint64(0x100F00F00F00F00F)
        x = (x | (x << np.uint64(4))) & np.uint64(0x10C30C30C30C30C3)
        return (x | (x << np.uint64(2))) & np.uint64(0x1249249249249249)

    u = (q.astype(np.int64) + 32767).astype(np.uint64)
    code = part(u[:, 0]) | (part(u[:, 1]) << np.uint64(1)) | (part(u[:, 2]) << np.uint64(2))
    return np.lexsort((ids, code))


def triangulate(faces: np.ndarray, xyz: np.ndarray) -> tuple[np.ndarray, int]:
    """면(정점 번호 [K,4], 4번째 −1 = 삼각형) → 삼각형 [T,3]과 건너뛴 퇴화 수. 쿼드 = (n1,n2,n3)+(n1,n3,n4), n4 = n3이면 1개(§4.1)."""
    quad = (faces[:, 3] >= 0) & (faces[:, 3] != faces[:, 2])
    t = np.concatenate([faces[:, :3], faces[quad][:, [0, 2, 3]]])
    a, b, c = xyz[t[:, 0]], xyz[t[:, 1]], xyz[t[:, 2]]
    cr = np.cross(b - a, c - a)
    ok = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2]) & ((cr * cr).sum(axis=1) > 1e-24)
    return t[ok], int((~ok).sum())


# ---- 필드 양자화(§5.2) ---------------------------------------------------------------------------------------------


def quantize_scalar(v: np.ndarray) -> tuple[np.ndarray, dict[str, Any], int]:
    """v float64 [N] → (q uint16, {min,max,scale,min_v,max_v}, 비유한 수). q = rint((v − min)/s), s = (max − min)/65534, 비유한 = 65535."""
    fin = np.isfinite(v)
    nbad = int(v.size - np.count_nonzero(fin))
    q = np.full(v.size, NAN_CODE, dtype=np.uint16)
    if nbad == v.size:
        return q, {"min": None, "max": None, "scale": 0.0, "min_v": None, "max_v": None}, nbad
    lo_v = int(np.where(fin, v, np.inf).argmin())
    hi_v = int(np.where(fin, v, -np.inf).argmax())
    lo, hi = float(v[lo_v]), float(v[hi_v])
    s = (hi - lo) / SCALAR_STEPS
    if s > 0 and math.isfinite(s):
        with np.errstate(invalid="ignore", over="ignore"):
            t = np.rint((v[fin] - lo) / s)
        q[fin] = np.clip(np.nan_to_num(t, nan=0.0), 0, SCALAR_STEPS).astype(np.uint16)
    else:
        s = 0.0
        q[fin] = 0
    return q, {"min": lo, "max": hi, "scale": s, "min_v": lo_v, "max_v": hi_v}, nbad


def _extreme_nodes(info: Mapping[str, Any], vid: np.ndarray, xyz: np.ndarray) -> dict[str, Any]:
    """프레임 극값 정점의 노드 ID·원 좌표(mm, 첫 프레임 기준) — LOD에 그 정점이 없어도 뷰어가 마커를 그린다(C3F-C1). 값이 없으면 null."""
    out: dict[str, Any] = {}
    for kind in ("max", "min"):
        v = info.get(f"{kind}_v")
        out[f"{kind}_node"] = None if v is None else int(vid[v])
        out[f"{kind}_xyz"] = None if v is None else [float(x) for x in xyz[v]]
    return out


def quantize_disp(d: np.ndarray) -> tuple[np.ndarray, list[float], list[float]]:
    """d float64 [N,3] → (q uint16 [N,3], min[3], scale[3]). 비유한 = 0 mm, t = (max − min)/65535."""
    d = np.where(np.isfinite(d), d, 0.0)
    lo, hi = d.min(axis=0), d.max(axis=0)
    q = np.zeros(d.shape, dtype=np.uint16)
    mins: list[float] = []
    scales: list[float] = []
    for c in range(3):
        mn = float(lo[c])
        t = (float(hi[c]) - mn) / DISP_STEPS
        if t > 0 and math.isfinite(t):
            q[:, c] = np.clip(np.rint((d[:, c] - mn) / t), 0, DISP_STEPS).astype(np.uint16)
        else:
            t = 0.0
        mins.append(mn)
        scales.append(t)
    return q, mins, scales


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


# ---- 변환 --------------------------------------------------------------------------------------------------------


def _fail(base: dict[str, Any], code: str, out_dir: str, detail: str | None = None) -> dict[str, Any]:
    doc = {**base, "status": "FAIL", "code": code, "message": _msg(code) + (f" — {detail}" if detail else ""),
           "mesh": None, "lod": None, "frames": None, "disp": None, "range": None}
    os.makedirs(out_dir, exist_ok=True)
    write_json(os.path.join(out_dir, OUT_MANIFEST), doc)
    return doc


def convert(extract_dir: str, out_dir: str, *, source: Mapping[str, Any], max_nodes: int, max_bin_bytes: int, max_frames: int,
            max_glb_bytes: int = DEFAULT_MAX_GLB_BYTES, max_disp_bytes: int = DEFAULT_MAX_DISP_BYTES,
            lod_min_nodes: int = DEFAULT_LOD_MIN_NODES, lod_target_vertices: int = DEFAULT_LOD_TARGET_VERTICES,
            meshopt: bool = True, comps: Sequence[str] = (), unit: str | None = None,
            progress: Callable[[float, str], None] | None = None, checkpoint: Callable[[], None] | None = None,
            discard: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """추출 폴더 → out_dir. 반환 = manifest(dict). 인프라 불일치는 ConvertError.
    comps = 요청한 표시 부품 이름(SCOPE=ALL이면 경고), unit = 표시 설정 display.unit(TCL 단위가 비면 사용 — §9.2).
    discard(path) = 실패 때 쓰다 만 임시 파일 처리(워커가 캐시 삭제 지점으로 넘김, 없으면 0바이트로 비움)."""
    prog = progress or (lambda _p, _m: None)
    tick = checkpoint or (lambda: None)
    rp = os.path.join(extract_dir, RESULT_NAME)
    if not os.path.isfile(rp):
        raise ConvertError(INVALID, f"{RESULT_NAME}이(가) 없습니다(추출 폴더 {os.path.basename(extract_dir)})")
    with open(rp, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    res = parse_result(text)
    if res["status"] != "OK":
        code = TCL_STATUS_CODE.get(str(res["status"]), INVALID)
        raise ConvertError(code, f"{RESULT_NAME} STATUS={res['status']}(OK 아님) {res['message'] or ''}".strip()
                           + ("" if res["header_ok"] else " — 파일 첫 줄 `# contour_extract` 없음(잘렸거나 다른 파일)"))
    unit_h3d, unit_disp = clean_unit(res.get("unit")), clean_unit(unit)
    unit_out, unit_source = (unit_h3d, "h3d") if unit_h3d else (unit_disp, "display") if unit_disp else ("", None)
    comps_l = normalize_comps(comps)
    limits: dict[str, Any] = {"nodes": None, "max_nodes": int(max_nodes), "glb_bytes": None, "max_glb_bytes": int(max_glb_bytes),
                              "bin_bytes": None, "max_bin_bytes": int(max_bin_bytes), "disp_bytes": None,
                              "max_disp_bytes": int(max_disp_bytes)}
    warnings: list[dict[str, Any]] = []
    base: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "kind": "contour3d", "status": "OK", "code": None, "message": None,
                            "source": dict(source), "display": {"field": res["field"], "comp": res["dcomp"], "avgmode": res["avgmode"]},
                            "unit": unit_out, "unit_source": unit_source, "length_unit": "mm", "up_axis": "Z", "warnings": warnings,
                            "converter_version": CONVERTER_VERSION, "limits": limits,
                            "scope": {"comps": comps_l, "comps_applicable": bool(comps_l), "applied": res["scope"] == "COMPS"}}
    if comps_l and res["scope"] != "COMPS":
        warnings.append(_warn("CONTOUR3D_COMPS_IGNORED"))
    # ---- 형상 ----
    prog(2, "형상 읽기")
    ids, xyz_all = read_nodes(os.path.join(extract_dir, "nodes.csv"), tick)
    fp, ep = os.path.join(extract_dir, "faces.csv"), os.path.join(extract_dir, "elements.csv")
    unknown_cfg: dict[int, int] = {}
    if os.path.isfile(fp):
        face_ids = read_faces(fp, tick)
    elif os.path.isfile(ep):
        face_ids = external_faces(ep, tick, unknown_cfg)
        if unknown_cfg:
            warnings.append(_warn("CONTOUR3D_FACE_SKIPPED", f"미지원 요소 config {_cfg_text(unknown_cfg)}를 건너뜀", count=sum(unknown_cfg.values())))
    else:
        raise ConvertError(INVALID, "faces.csv·elements.csv가 모두 없습니다(추출 폴더에 외부 면 파일 없음)")
    tick()
    order = np.argsort(ids, kind="stable")
    sids = ids[order]
    flat = face_ids.ravel()
    m = flat >= 0
    pos = np.searchsorted(sids, flat[m])
    pos_c = np.minimum(pos, max(sids.size - 1, 0))
    if not sids.size:
        raise ConvertError(INVALID, "nodes.csv에 노드가 없습니다(데이터 행 0)")
    miss = sids[pos_c] != flat[m]
    rows_flat = np.full(flat.shape, -1, dtype=np.int64)
    rows_flat[m] = order[pos_c]
    face_rows = rows_flat.reshape(face_ids.shape)
    if miss.any():  # nodes.csv에 없는 노드를 쓰는 면은 건너뛴다(전부 그렇다면 오류)
        first_missing = int(flat[m][np.argmax(miss)])
        mi = np.flatnonzero(m)[miss] // face_ids.shape[1]
        badf = np.zeros(face_ids.shape[0], dtype=bool)
        badf[mi] = True
        if badf.all():
            raise ConvertError(INVALID, f"모든 면이 nodes.csv에 없는 노드를 참조합니다(예: 노드 {first_missing}, 면 {face_ids.shape[0]}개 검사)")
        face_rows[badf] = -1
        warnings.append(_warn("CONTOUR3D_FACE_SKIPPED", f"nodes.csv에 없는 노드를 쓰는 면 {int(badf.sum())}개(예: 노드 {first_missing})",
                              count=int(badf.sum())))
    del face_ids, flat, rows_flat, pos, pos_c, m
    keep = np.unique(face_rows[face_rows >= 0])  # 외부 면 노드(nodes.csv 행 번호 오름차순)
    n = int(keep.size)
    limits["nodes"] = n
    if n > max_nodes:
        return _fail(base, "CONTOUR3D_TOO_LARGE", out_dir, f"외부 면 노드 {n:,}개 > 상한 {max_nodes:,}")
    if n == 0:
        raise ConvertError(INVALID, "삼각형이 하나도 없습니다(면 없음)"
                           + (f" — 미지원 요소 config {_cfg_text(unknown_cfg)}(elements.csv)" if unknown_cfg else ""))
    q_keep, translation, scale = mo.quantize_positions(xyz_all[keep])
    perm = morton_order(q_keep, ids[keep])
    src_rows = keep[perm]  # 정점 i의 nodes.csv(=프레임) 행 번호
    vid = ids[src_rows]
    xyz = xyz_all[src_rows]
    qpos = q_keep[perm]
    del q_keep
    vert_of_row = np.full(ids.size, -1, dtype=np.int64)
    vert_of_row[src_rows] = np.arange(n)
    fv = np.where(face_rows >= 0, vert_of_row[np.maximum(face_rows, 0)], -1)
    del face_rows, vert_of_row
    tris, skipped = triangulate(fv, xyz)
    del fv
    if not tris.size:
        raise ConvertError(INVALID, "삼각형이 하나도 없습니다(퇴화 면만 있음)")
    if skipped:
        warnings.append(_warn("CONTOUR3D_FACE_SKIPPED", count=skipped))
    tris = lodmod.canonical_triangles(tris)
    prog(15, "형상 압축")
    glb = glbmod.write_glb(qpos, translation, scale, [("_NODE_ID", vid.astype(np.uint32))], tris.astype(np.uint32), meshopt=meshopt)
    limits["glb_bytes"] = len(glb)
    if len(glb) > max_glb_bytes:
        return _fail(base, "CONTOUR3D_TOO_LARGE", out_dir,
                     f"형상 {len(glb) / 1e6:.1f} MB > 상한 {max_glb_bytes / 1e6:.1f} MB(contour3d.max_glb_bytes)")
    tick()
    # ---- 프레임 목록·크기 판정(§5.4) ----
    frames = sorted(res["frames"])
    if not frames:
        raise ConvertError(INVALID, f"{RESULT_NAME}에 해석 가능한 `FRAME=번호|원본번호|시간` 줄이 없습니다(FRAMES_TOTAL={res['frames_total']})")
    uniq: dict[int, tuple[int, int, Any]] = {}
    for f in frames:  # 같은 번호의 FRAME 줄이 겹치면 첫 줄만(시간이 같은 프레임은 별개 프레임으로 허용)
        uniq.setdefault(f[0], f)
    frames = [uniq[k] for k in sorted(uniq)]
    if [f[0] for f in frames] != list(range(len(frames))):
        bad = next(i for i, f in enumerate(frames) if f[0] != i)
        raise ConvertError(INVALID, f"{RESULT_NAME} FRAME 번호가 0부터 연속이 아닙니다(기대 {bad}, 실제 {frames[bad][0]}, 총 {len(frames)}줄)")
    if len(frames) > max_frames:
        frames = [frames[i] for i in resample(len(frames), max_frames)]
    absent = [f"frame_{f[0]:05d}.csv" for f in frames if not os.path.isfile(os.path.join(extract_dir, f"frame_{f[0]:05d}.csv"))]
    if absent:
        raise ConvertError(INVALID, f"{RESULT_NAME}의 FRAME 줄에 대응하는 파일이 없습니다: {absent[0]} 외 {len(absent) - 1}개(검사: 파일 존재)")
    p0 = os.path.join(extract_dir, f"frame_{frames[0][0]:05d}.csv")
    with _open(p0) as fh:
        head0 = _header(fh, p0, "value")
    has_disp = head0[:4] == ["value", "dx", "dy", "dz"]
    dstate, missing = res["disp"], int(res["disp_missing_frames"] or 0)
    if dstate == "NONE":
        has_disp = False
        warnings.append(_warn("CONTOUR3D_DISP_UNAVAILABLE", res["disp_reason"] or None))
    elif dstate == "SKIPPED_NODES":
        has_disp = False
        warnings.append(_warn("CONTOUR3D_DISP_DROPPED", "노드 수"))
    elif dstate == "OFF":
        has_disp = False
    elif dstate == "ON" and missing > 0:
        has_disp = False
        warnings.append(_warn("CONTOUR3D_DISP_UNAVAILABLE", f"일부 프레임({missing}개)에 변위 없음"))
    elif dstate == "ON" and not has_disp:
        warnings.append(_warn("CONTOUR3D_DISP_UNAVAILABLE", "frame 헤더에 변위 열이 없습니다"))
    if has_disp and 6 * n * len(frames) > max_disp_bytes:
        has_disp = False
        warnings.append(_warn("CONTOUR3D_DISP_DROPPED", "크기"))
    if 2 * n * len(frames) > max_bin_bytes:
        k = max_bin_bytes // (2 * n)
        if k < 2:
            limits["bin_bytes"] = 2 * n * 2
            return _fail(base, "CONTOUR3D_TOO_LARGE", out_dir, "프레임 2개도 상한(contour3d.max_bin_bytes)을 넘습니다")
        frames = [frames[i] for i in resample(len(frames), int(k))]
    # ---- 프레임(스트리밍) ----
    os.makedirs(out_dir, exist_ok=True)
    bin_path, disp_path = os.path.join(out_dir, OUT_FRAMES), os.path.join(out_dir, OUT_DISP)
    tmp, dtmp = bin_path + ".tmp", disp_path + ".tmp"
    h_bin, h_disp = hashlib.sha256(), hashlib.sha256()
    listing: list[dict[str, Any]] = []
    dlist: list[dict[str, Any]] = []
    nan_total, gmin, gmax = 0, math.inf, -math.inf
    peak = np.full(n, -np.inf)
    disp_lost = 0
    nf = len(frames)
    out_d = open(dtmp, "wb") if has_disp else None
    try:
        with open(tmp, "wb") as out:
            for i, (out_idx, src, t) in enumerate(frames):
                tick()
                head, arr = _read_frame(os.path.join(extract_dir, f"frame_{out_idx:05d}.csv"), int(ids.size), tick)
                v = arr[src_rows, 0]
                q, info, bad = quantize_scalar(v)
                nan_total += bad
                b = q.astype("<u2").tobytes()
                out.write(b)
                h_bin.update(b)
                av = np.abs(v)
                av[~np.isfinite(av)] = np.nan
                np.fmax(peak, av, out=peak)
                listing.append({"i": i, "src": src, "time": t, **info, **_extreme_nodes(info, vid, xyz)})
                if info["min"] is not None:
                    gmin, gmax = min(gmin, info["min"]), max(gmax, info["max"])
                if out_d is not None:
                    if arr.shape[1] < 4:
                        disp_lost += 1
                    elif not disp_lost:
                        dq, dmin, dsc = quantize_disp(arr[src_rows, 1:4])
                        db = dq.astype("<u2").tobytes()
                        out_d.write(db)
                        h_disp.update(db)
                        dlist.append({"i": i, "min": dmin, "scale": dsc})
                del arr, v, q
                prog(25 + 65 * (i + 1) / nf, f"프레임 변환 {i + 1}/{nf}")
    finally:
        if out_d is not None:
            out_d.close()

    def drop(path: str) -> None:
        if os.path.exists(path):
            if discard is not None:
                discard(path)
            else:
                open(path, "wb").close()

    if nan_total > 0.5 * n * nf:
        drop(tmp)
        drop(dtmp)
        return _fail(base, "CONTOUR3D_FIELD_EMPTY", out_dir, f"값 없는 노드 비율 {nan_total / (n * nf):.0%}")
    if has_disp and disp_lost:
        has_disp = False
        drop(dtmp)
        warnings.append(_warn("CONTOUR3D_DISP_UNAVAILABLE", f"일부 프레임({disp_lost}개)에 변위 없음"))
    # ---- LOD(§7.2) ----
    lod_glb: bytes | None = None
    lod_info: dict[str, Any] | None = None
    if n > lod_min_nodes:
        prog(92, "저해상도(LOD) 만들기")
        lo = lodmod.build(xyz, tris, peak, vid, int(lod_target_vertices))
        src = lo.src.astype(np.int64)
        lod_glb = glbmod.write_glb(qpos[src], translation, scale, [("_NODE_ID", vid[src].astype(np.uint32)), ("_SRC", lo.src)],
                                   lo.triangles, meshopt=meshopt)
        lod_info = {"file": OUT_LOD, "sha256": hashlib.sha256(lod_glb).hexdigest(), "bytes": len(lod_glb), "vertices": int(src.size),
                    "triangles": int(lo.triangles.shape[0]), "method": "cluster_peak", "cell_mm": lo.cell}
        tick()
    glb_total = len(glb) + (len(lod_glb) if lod_glb else 0)
    limits["glb_bytes"] = glb_total
    rec, drec = 2 * n, 6 * n
    limits["bin_bytes"] = rec * nf
    limits["disp_bytes"] = drec * nf if has_disp else 0
    if glb_total > max_glb_bytes:
        drop(tmp)
        drop(dtmp)
        return _fail(base, "CONTOUR3D_TOO_LARGE", out_dir,
                     f"형상 {glb_total / 1e6:.1f} MB > 상한 {max_glb_bytes / 1e6:.1f} MB(contour3d.max_glb_bytes)")
    os.replace(tmp, bin_path)
    if has_disp:
        os.replace(dtmp, disp_path)
    with open(os.path.join(out_dir, OUT_GLB), "wb") as fh:
        fh.write(glb)
    if lod_glb is not None:
        with open(os.path.join(out_dir, OUT_LOD), "wb") as fh:
            fh.write(lod_glb)
    total_frames = res["frames_total"] or len(res["frames"])  # h3d 전체 프레임 수(TCL 샘플링 전)
    doc = {**base,
           "mesh": {"file": OUT_GLB, "sha256": hashlib.sha256(glb).hexdigest(), "bytes": len(glb), "nodes": n,
                    "triangles": int(tris.shape[0]), "compression": "meshopt" if meshopt else "none",
                    "quantization": {"position": "int16n"}, "order": "morton", "normals": "viewer"},
           "lod": lod_info,
           "frames": {"file": OUT_FRAMES, "sha256": h_bin.hexdigest(), "bytes": rec * nf, "dtype": "uint16q", "nan_code": NAN_CODE,
                      "record_bytes": rec, "count": nf, "has_disp": bool(has_disp), "nan_count": nan_total, "list": listing},
           "disp": ({"file": OUT_DISP, "dtype": "uint16q", "record_bytes": drec, "sha256": h_disp.hexdigest(), "bytes": drec * nf,
                     "list": dlist} if has_disp else None),
           "range": {"min": gmin if math.isfinite(gmin) else None, "max": gmax if math.isfinite(gmax) else None},
           "sampling": {"total_frames": total_frames, "max_frames": max_frames, "rule": "uniform_inclusive"}}
    write_json(os.path.join(out_dir, OUT_MANIFEST), doc)
    prog(100, "완료")
    return doc
