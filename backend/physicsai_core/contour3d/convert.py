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
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, BinaryIO

import numpy as np

from ..fileutil import write_json
from . import glb as glbmod
from . import lod as lodmod
from . import meshopt as mo
from . import settings as _st
from .settings import MESSAGES, OUT_FRAMES, OUT_GLB, OUT_MANIFEST, RESULT_NAME, TCL_STATUS_CODE, message_ko, parse_result

INVALID = "CONTOUR3D_EXTRACT_INVALID"
SCHEMA_VERSION = 2
CONVERTER_VERSION = 2  # manifest converter_version(C3F-6). 캐시 키의 settings.CONVERTER_VERSION과 같아야 한다
OUT_DISP: str = getattr(_st, "OUT_DISP", "contour_disp.bin")
OUT_LOD: str = getattr(_st, "OUT_LOD", "contour_lod.glb")
NAN_CODE = 65535
SCALAR_STEPS = 65534  # 스칼라 q ∈ [0, 65534], 65535 예약
DISP_STEPS = 65535
# 상한 기본값(contour3d-field.md §8 — 실제 값은 설정 contour3d.*에서 워커가 넘긴다)
DEFAULT_MAX_GLB_BYTES = 64 << 20
DEFAULT_MAX_DISP_BYTES = 1 << 30
DEFAULT_LOD_MIN_NODES = 500_000
DEFAULT_LOD_TARGET_VERTICES = 100_000
CHUNK_BYTES = 8 << 20  # CSV 스트리밍 단위(완결된 행만)
NEW_MESSAGES = {  # settings.MESSAGES에 아직 없을 때의 문구(§9.4·§9.5)
    "CONTOUR3D_DISP_UNAVAILABLE": "결과에 변위가 없어 변형 표시 없이 보입니다",
    "CONTOUR3D_COMPS_IGNORED": "표시 부품 이름을 적용하지 못해 전체를 표시합니다",
    "CONTOUR3D_DISP_DROPPED": "크기 상한으로 변위(변형 배율)를 뺐습니다(표시 유지)",
}
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


def _msg(code: str) -> str:
    return MESSAGES.get(code) or NEW_MESSAGES.get(code) or message_ko(code) or code


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


def _parse_block(block: bytes, ncol: int, blank_nan: bool, name: str) -> np.ndarray:
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
    return _parse_slow(b, ncol, name)


def _parse_slow(b: bytes, ncol: int, name: str) -> np.ndarray:
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
                    raise ConvertError(INVALID, f"{name}: 숫자가 아닙니다: {s[:20].decode('utf-8', 'replace')}") from None
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
                a = _parse_block(blk, ncol, True, name)
                if a.shape[0] != cnt:
                    raise ConvertError(INVALID, f"{name} 행을 읽지 못했습니다")
                out[row:row + cnt] = a
                row += cnt
    if row != nrows:
        raise ConvertError(INVALID, f"{name} 행 수가 nodes.csv({nrows})와 다릅니다")
    return head, out


# ---- 형상 --------------------------------------------------------------------------------------------------------


def read_nodes(path: str, tick: Callable[[], None] = lambda: None) -> tuple[np.ndarray, np.ndarray]:
    """nodes.csv → (ids int64 [n], xyz float64 [n,3])."""
    t = _read_table(path, "node_id", 4, tick)
    raw = t[:, 0]
    if not np.isfinite(raw).all():
        raise ConvertError(INVALID, "nodes.csv에 빈 node_id가 있습니다")
    if (raw != np.floor(raw)).any() or (raw < 0).any() or (raw > 0xFFFFFFFF).any():
        raise ConvertError(INVALID, "nodes.csv node_id는 0 이상 4294967295 이하 정수여야 합니다")
    ids = raw.astype(np.int64)
    xyz = t[:, 1:4]
    bad = ~np.isfinite(xyz).all(axis=1)
    if bad.any():
        raise ConvertError(INVALID, f"노드 {int(ids[np.argmax(bad)])} 좌표가 유한하지 않습니다")
    if np.unique(ids).size != ids.size:
        raise ConvertError(INVALID, "nodes.csv에 같은 node_id가 두 번 있습니다")
    return ids, np.ascontiguousarray(xyz)


def _ints(a: np.ndarray) -> np.ndarray:
    """float(NaN 포함) → int64, NaN = −1."""
    out = np.full(a.shape, -1, dtype=np.int64)
    m = np.isfinite(a)
    if (a[m] != np.floor(a[m])).any() or (a[m] < 0).any():
        raise ConvertError(INVALID, "노드·요소 번호는 0 이상 정수여야 합니다")
    out[m] = a[m].astype(np.int64)
    return out


def external_faces(path: str, tick: Callable[[], None] = lambda: None) -> np.ndarray:
    """elements.csv(elem_id,config,n1..n8) → 외부 면 노드 ID int64 [K,4](삼각형은 4번째 −1).
    쉘(103·104) = 요소 그대로, 솔리드 = 한 번만 나온 면(정렬 키 lexsort → 같은 면 묶음 크기 1)."""
    t = _read_table(path, "elem_id", 10, tick)
    if t.shape[0] and not np.isfinite(t[:, :2]).all():
        raise ConvertError(INVALID, "elements.csv 행에 elem_id·config가 없습니다")
    eid = t[:, 0]
    cfg = t[:, 1].astype(np.int64) if t.shape[0] else np.zeros(0, dtype=np.int64)
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
            raise ConvertError(INVALID, "elements.csv 쉘 요소의 노드가 모자랍니다")
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
        raise ConvertError(INVALID, "faces.csv 행의 노드가 3개 미만입니다")
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


# ---- extract_result.txt 추가 줄(§9.4·§9.5) ------------------------------------------------------------------------


def result_extras(text: str) -> dict[str, Any]:
    """DISP·DISP_REASON·DISP_MISSING_FRAMES·SCOPE(없으면 None — 예전 TCL)."""
    out: dict[str, Any] = {"disp": None, "disp_reason": None, "disp_missing_frames": 0, "scope": None}
    for raw in text.splitlines():
        key, sep, val = raw.strip().lstrip("﻿").partition("=")
        if not sep:
            continue
        val = val.strip()
        if key == "DISP":
            out["disp"] = val.upper() or None
        elif key == "DISP_REASON":
            out["disp_reason"] = val[:120] or None
        elif key == "DISP_MISSING_FRAMES":
            out["disp_missing_frames"] = int(val) if val.isdigit() else 0
        elif key == "SCOPE":
            out["scope"] = val.upper() or None
    return out


def clean_unit(u: Any) -> str:
    """오류 문구처럼 보이는 단위는 버린다(§9.2: 16자 초과·공백·`"`·`:`·invalid·error)."""
    s = str(u or "").strip()
    low = s.lower()
    if len(s) > 16 or any(ch in s for ch in ' "\t:') or "invalid" in low or "error" in low:
        return ""
    return s


def _normalize_comps(comps: Sequence[str] | None) -> list[str]:
    """정렬·중복 제거·공백 제거(settings.normalize_comps가 있으면 그것 — 캐시 키와 같은 규칙)."""
    fn = getattr(_st, "normalize_comps", None)
    if fn is not None:
        return list(fn(comps))
    return sorted({str(c).strip() for c in (comps or ()) if str(c).strip()})


def _clean_unit(u: Any) -> str:
    fn = getattr(_st, "clean_unit", None)
    return fn(u) if fn is not None else clean_unit(u)


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
        raise ConvertError(INVALID, "extract_result.txt가 없습니다")
    with open(rp, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    res = parse_result(text)
    if res["status"] != "OK":
        code = TCL_STATUS_CODE.get(str(res["status"]), INVALID)
        raise ConvertError(code, f"추출 상태 {res['status']}: {res['message'] or ''}".strip())
    ext = result_extras(text)
    unit_h3d, unit_disp = _clean_unit(res.get("unit")), _clean_unit(unit)
    unit_out, unit_source = (unit_h3d, "h3d") if unit_h3d else (unit_disp, "display") if unit_disp else ("", None)
    comps_l = _normalize_comps(comps)
    limits: dict[str, Any] = {"nodes": None, "max_nodes": int(max_nodes), "glb_bytes": None, "max_glb_bytes": int(max_glb_bytes),
                              "bin_bytes": None, "max_bin_bytes": int(max_bin_bytes), "disp_bytes": None,
                              "max_disp_bytes": int(max_disp_bytes)}
    warnings: list[dict[str, Any]] = []
    base: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "kind": "contour3d", "status": "OK", "code": None, "message": None,
                            "source": dict(source), "display": {"field": res["field"], "comp": res["dcomp"], "avgmode": res["avgmode"]},
                            "unit": unit_out, "unit_source": unit_source, "length_unit": "mm", "up_axis": "Z", "warnings": warnings,
                            "converter_version": CONVERTER_VERSION, "limits": limits,
                            "scope": {"comps": comps_l, "comps_applicable": bool(comps_l), "applied": ext["scope"] == "COMPS"}}
    if comps_l and ext["scope"] != "COMPS":
        warnings.append(_warn("CONTOUR3D_COMPS_IGNORED"))
    # ---- 형상 ----
    prog(2, "형상 읽기")
    ids, xyz_all = read_nodes(os.path.join(extract_dir, "nodes.csv"), tick)
    fp, ep = os.path.join(extract_dir, "faces.csv"), os.path.join(extract_dir, "elements.csv")
    if os.path.isfile(fp):
        face_ids = read_faces(fp, tick)
    elif os.path.isfile(ep):
        face_ids = external_faces(ep, tick)
    else:
        raise ConvertError(INVALID, "faces.csv·elements.csv가 모두 없습니다")
    tick()
    order = np.argsort(ids, kind="stable")
    sids = ids[order]
    flat = face_ids.ravel()
    m = flat >= 0
    pos = np.searchsorted(sids, flat[m])
    pos_c = np.minimum(pos, max(sids.size - 1, 0))
    if not sids.size or (sids[pos_c] != flat[m]).any():
        raise ConvertError(INVALID, "면이 nodes.csv에 없는 노드를 참조합니다")
    rows_flat = np.full(flat.shape, -1, dtype=np.int64)
    rows_flat[m] = order[pos_c]
    face_rows = rows_flat.reshape(face_ids.shape)
    del face_ids, flat, rows_flat, pos, pos_c, m
    keep = np.unique(face_rows[face_rows >= 0])  # 외부 면 노드(nodes.csv 행 번호 오름차순)
    n = int(keep.size)
    limits["nodes"] = n
    if n > max_nodes:
        return _fail(base, "CONTOUR3D_TOO_LARGE", out_dir, f"외부 면 노드 {n:,}개 > 상한 {max_nodes:,}")
    if n == 0:
        raise ConvertError(INVALID, "삼각형이 하나도 없습니다(면 없음)")
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
        raise ConvertError(INVALID, "추출 결과에 프레임이 없습니다")
    if [f[0] for f in frames] != list(range(len(frames))):
        raise ConvertError(INVALID, "프레임 번호가 0부터 연속이 아닙니다")
    if len(frames) > max_frames:
        frames = [frames[i] for i in resample(len(frames), max_frames)]
    if not all(os.path.isfile(os.path.join(extract_dir, f"frame_{f[0]:05d}.csv")) for f in frames):
        raise ConvertError(INVALID, "frame_*.csv 파일 수가 FRAME 줄 수와 다릅니다")
    p0 = os.path.join(extract_dir, f"frame_{frames[0][0]:05d}.csv")
    with _open(p0) as fh:
        head0 = _header(fh, p0, "value")
    has_disp = head0[:4] == ["value", "dx", "dy", "dz"]
    dstate, missing = ext["disp"], int(ext["disp_missing_frames"] or 0)
    if dstate == "NONE":
        has_disp = False
        warnings.append(_warn("CONTOUR3D_DISP_UNAVAILABLE", ext["disp_reason"]))
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
                listing.append({"i": i, "src": src, "time": t, **info})
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
