"""EXT_meshopt_compression 인코더(numpy 직접 구현)와 KHR_mesh_quantization 위치 양자화(contour3d-field.md §4.3·§4.4, C3F-2·C3F-4).

- vertex codec v0(ATTRIBUTES 모드, 헤더 0xA0): 블록(정점 ≤ 256, 8192 B/stride를 16 배수로 내림) × 바이트 위치 k마다 직전 정점과의 바이트
  차이를 zigzag8로 바꾸고 16바이트 그룹을 0·2·4·8비트(센티널 = 모든 비트 1, 넘치는 값은 뒤에 원래 바이트)로 담는다. 첫 블록의 기준은
  첫 정점이고, 꼬리 = 0 채움 + 첫 정점(합 max(32, stride) B).
- index sequence codec v1(INDICES 모드, 헤더 0xD1): 값마다 기준 2개 중 하나와의 차이(zigzag) << 1 | 기준 번호를 varint(7비트, LE)로,
  꼬리 0 4바이트. 기준 선택은 인코더 자유(디코더는 저장된 비트를 따른다) — 여기서는 삼각형 첫 정점 = 기준 0, 나머지 = 기준 1(벡터화).
- 디코더(`decode_vertex_buffer`·`decode_index_sequence`)는 왕복 시험용 참조 구현(meshoptimizer 디코더와 같은 검사·꼬리 길이 규칙).
결정성: 같은 입력이면 같은 바이트(그룹 비트 폭은 크기 최소, 같으면 작은 폭).
"""

from __future__ import annotations

import numpy as np

VERTEX_HEADER = 0xA0  # | version 0
INDEX_SEQUENCE_HEADER = 0xD1  # 0xD0 | version 1
BLOCK_BYTES = 8192
BLOCK_MAX = 256
GROUP = 16
TAIL_MIN = 32
_BITS = (0, 2, 4, 8)  # 헤더 2비트 값 0..3 → 비트 폭


def block_size(stride: int) -> int:
    return min((BLOCK_BYTES // stride) & ~(GROUP - 1), BLOCK_MAX)


def _zigzag8(d: np.ndarray) -> np.ndarray:
    s = d.astype(np.int8).astype(np.int16)
    return (((s << 1) ^ (s >> 7)) & 0xFF).astype(np.uint8)


def _encode_streams(streams: np.ndarray) -> np.ndarray:
    """streams uint8 [S, L](L = 16의 배수) → 스트림마다 encodeBytes(헤더 + 그룹)를 차례로 이은 uint8 배열."""
    s_count, length = streams.shape
    groups = length // GROUP
    g = streams.reshape(s_count, groups, GROUP)
    # 그룹별 크기: 0비트(전부 0) · 2비트 · 4비트 · 8비트
    big = np.iinfo(np.int64).max
    size0 = np.where(g.any(axis=2), big, 0)
    size2 = 4 + (g >= 3).sum(axis=2)
    size4 = 8 + (g >= 15).sum(axis=2)
    size8 = np.full_like(size2, 16)
    choice = np.argmin(np.stack([size0, size2, size4, size8]), axis=0).astype(np.uint8)  # [S, G], 같으면 작은 폭
    # 헤더: 그룹 j → header[j // 4] 비트 (j % 4)·2
    hbytes = (groups + 3) // 4
    padded = np.zeros((s_count, hbytes * 4), dtype=np.uint8)
    padded[:, :groups] = choice
    p4 = padded.reshape(s_count, hbytes, 4).astype(np.uint16)
    header = (p4[..., 0] | (p4[..., 1] << 2) | (p4[..., 2] << 4) | (p4[..., 3] << 6)).astype(np.uint8)
    # 그룹 토큰(고정부 16 + 가변부 16)과 유효 마스크 — 마스크 선택이 행 우선 순서를 지키므로 그대로 이으면 된다
    tok = np.zeros((s_count, groups, 2 * GROUP), dtype=np.uint8)
    msk = np.zeros((s_count, groups, 2 * GROUP), dtype=bool)
    c = choice[..., None]
    v2 = np.minimum(g, 3).astype(np.uint8).reshape(s_count, groups, 4, 4)
    f2 = (v2[..., 0] << 6) | (v2[..., 1] << 4) | (v2[..., 2] << 2) | v2[..., 3]  # [S, G, 4]
    v4 = np.minimum(g, 15).astype(np.uint8).reshape(s_count, groups, 8, 2)
    f4 = (v4[..., 0] << 4) | v4[..., 1]  # [S, G, 8]
    is2, is4, is8 = (choice == 1), (choice == 2), (choice == 3)
    tok[..., :4] = np.where(is2[..., None], f2, 0)
    tok[..., :8] = np.where(is4[..., None], f4, tok[..., :8])
    tok[..., :16] = np.where(is8[..., None], g, tok[..., :16])
    lane = np.arange(GROUP)
    flen = np.array([0, 4, 8, 16], dtype=np.int64)[choice]  # [S, G]
    msk[..., :GROUP] = lane[None, None, :] < flen[..., None]
    tok[..., GROUP:] = g
    sentinel = np.array([256, 3, 15, 256], dtype=np.int16)[c]  # 0·8비트는 가변부 없음
    msk[..., GROUP:] = g.astype(np.int16) >= sentinel
    body = np.concatenate([header, np.where(msk, tok, 0).reshape(s_count, -1)], axis=1)
    bmask = np.concatenate([np.ones_like(header, dtype=bool), msk.reshape(s_count, -1)], axis=1)
    return body[bmask]


def encode_vertex_buffer(data: np.ndarray) -> bytes:
    """data uint8 [count, stride](stride는 4의 배수, ≤ 256) → meshopt vertex buffer(v0) 바이트."""
    arr = np.ascontiguousarray(data, dtype=np.uint8)
    if arr.ndim != 2:
        raise ValueError("data는 [count, stride]여야 합니다")
    count, stride = arr.shape
    if count < 1 or stride < 1 or stride > 256 or stride % 4:
        raise ValueError(f"정점 수·stride가 올바르지 않습니다: {count}, {stride}")
    prev = np.empty_like(arr)
    prev[0] = arr[0]
    prev[1:] = arr[:-1]
    zz = _zigzag8(arr.astype(np.int16) - prev.astype(np.int16))
    bs = block_size(stride)
    parts: list[np.ndarray] = [np.array([VERTEX_HEADER], dtype=np.uint8)]
    full = count // bs
    if full:
        blk = zz[:full * bs].reshape(full, bs, stride).transpose(0, 2, 1).reshape(full * stride, bs)  # 블록 → k → 정점
        parts.append(_encode_streams(blk))
    rest = count - full * bs
    if rest:
        aligned = (rest + GROUP - 1) & ~(GROUP - 1)
        tail = np.zeros((stride, aligned), dtype=np.uint8)
        tail[:, :rest] = zz[full * bs:].T
        parts.append(_encode_streams(tail))
    tail_size = max(TAIL_MIN, stride)
    parts.append(np.zeros(tail_size - stride, dtype=np.uint8))
    parts.append(arr[0])
    return np.concatenate(parts).tobytes()


def triangle_baselines(count: int) -> np.ndarray:
    """INDICES 기준 선택(결정적): 삼각형 첫 정점 0, 나머지 1."""
    b = np.ones(count, dtype=np.uint32)
    b[0::3] = 0
    return b


def encode_index_sequence(indices: np.ndarray, baselines: np.ndarray | None = None) -> bytes:
    """indices(uint32) → meshopt index sequence(v1) 바이트. baselines = 값마다 기준 번호(0·1), 없으면 triangle_baselines."""
    idx = np.ascontiguousarray(indices, dtype=np.uint32).ravel()
    n = idx.size
    base = triangle_baselines(n) if baselines is None else np.ascontiguousarray(baselines, dtype=np.uint32).ravel()
    if base.size != n or (base > 1).any():
        raise ValueError("baselines는 indices와 같은 길이의 0·1이어야 합니다")
    if n and int(idx.max()) >= 1 << 30:  # (zigzag << 1)이 32비트에 들어가는 차이 범위 [−2^30, 2^30)
        raise ValueError("인덱스는 2^30 미만이어야 합니다")
    last = np.zeros(n, dtype=np.uint32)  # 값마다 쓰는 기준의 직전 값(같은 기준의 바로 앞 값, 처음은 0)
    for b in (0, 1):
        pos = np.flatnonzero(base == b)
        if pos.size:
            last[pos[1:]] = idx[pos[:-1]]
    d = (idx.astype(np.int64) - last.astype(np.int64)) & 0xFFFFFFFF  # uint32 산술
    d32 = d.astype(np.uint32)
    zz = (d32 << np.uint32(1)) ^ (d32.view(np.int32) >> np.int32(31)).view(np.uint32)
    v = ((zz.astype(np.uint64) << np.uint64(1)) | base.astype(np.uint64)) & np.uint64(0xFFFFFFFF)
    nb = np.ones(n, dtype=np.int64)
    for k in range(1, 5):
        nb += v >= np.uint64(1 << (7 * k))
    sh = np.arange(5, dtype=np.uint64) * np.uint64(7)
    grp = ((v[:, None] >> sh[None, :]) & np.uint64(0x7F)).astype(np.uint8)
    j = np.arange(5)[None, :]
    grp |= np.where(j < (nb[:, None] - 1), 0x80, 0).astype(np.uint8)
    body = grp[j < nb[:, None]]
    return bytes([INDEX_SEQUENCE_HEADER]) + body.tobytes() + b"\x00" * 4


# ---- 참조 디코더(시험용, meshoptimizer 디코더와 같은 규칙) ------------------------------------------------------------


class DecodeError(ValueError):
    pass


def _decode_group(data: bytes, pos: int, bitslog2: int) -> tuple[list[int], int]:
    if bitslog2 == 0:
        return [0] * GROUP, pos
    if bitslog2 == 3:
        return list(data[pos:pos + GROUP]), pos + GROUP
    bits = 2 if bitslog2 == 1 else 4
    per = 8 // bits
    fixed = GROUP * bits // 8
    var = pos + fixed
    sentinel = (1 << bits) - 1
    out: list[int] = []
    for b in data[pos:pos + fixed]:
        for k in range(per):
            enc = (b >> (8 - bits * (k + 1))) & sentinel
            if enc == sentinel:
                out.append(data[var])
                var += 1
            else:
                out.append(enc)
    return out, var


def decode_vertex_buffer(data: bytes, count: int, stride: int) -> bytes:
    if len(data) < 1 + stride:
        raise DecodeError("버퍼가 짧습니다")
    if data[0] & 0xF0 != VERTEX_HEADER or data[0] & 0x0F != 0:
        raise DecodeError("vertex 헤더 오류")
    end = len(data)
    last = list(data[end - stride:end])
    out = bytearray(count * stride)
    pos = 1
    bs = block_size(stride)
    off = 0
    while off < count:
        m = min(bs, count - off)
        aligned = (m + GROUP - 1) & ~(GROUP - 1)
        for k in range(stride):
            groups = aligned // GROUP
            header = data[pos:pos + (groups + 3) // 4]
            pos += (groups + 3) // 4
            buf: list[int] = []
            for gi in range(groups):
                if end - pos < 24:
                    raise DecodeError("데이터가 모자랍니다")
                vals, pos = _decode_group(data, pos, (header[gi // 4] >> ((gi % 4) * 2)) & 3)
                buf.extend(vals)
            p = last[k]
            for i in range(m):
                z = buf[i]
                v = (p + ((z >> 1) ^ -(z & 1))) & 0xFF
                out[(off + i) * stride + k] = v
                p = v
        last = list(out[(off + m - 1) * stride:(off + m) * stride])
        off += m
    if end - pos != max(TAIL_MIN, stride):
        raise DecodeError("꼬리 길이 오류")
    return bytes(out)


def decode_index_sequence(data: bytes, count: int) -> list[int]:
    if len(data) < 1 + count + 4:
        raise DecodeError("버퍼가 짧습니다")
    if data[0] & 0xF0 != 0xD0 or data[0] & 0x0F > 1:
        raise DecodeError("index sequence 헤더 오류")
    pos, safe_end = 1, len(data) - 4
    last = [0, 0]
    out: list[int] = []
    for _ in range(count):
        if pos >= safe_end:
            raise DecodeError("데이터가 모자랍니다")
        v, shift = 0, 0
        while True:
            b = data[pos]
            pos += 1
            v |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80 or shift >= 35:
                break
        v &= 0xFFFFFFFF
        cur = v & 1
        v >>= 1
        d = ((v >> 1) ^ -(v & 1)) & 0xFFFFFFFF
        idx = (last[cur] + d) & 0xFFFFFFFF
        last[cur] = idx
        out.append(idx)
    if pos != safe_end:
        raise DecodeError("꼬리 길이 오류")
    return out


# ---- KHR_mesh_quantization 위치 ------------------------------------------------------------------------------------


def quantize_positions(xyz: np.ndarray) -> tuple[np.ndarray, list[float], list[float]]:
    """xyz float64 [N,3] → (q int16 [N,3] ∈ [−32767, 32767], translation, scale). 복원 = translation + scale·q/32767.
    축별 scale = bbox 반길이(길이 0인 축은 다른 축 최대 반길이, 모두 0이면 1 — 노드 행렬이 역행렬을 갖게)."""
    p = np.asarray(xyz, dtype=np.float64)
    lo, hi = p.min(axis=0), p.max(axis=0)
    center = (lo + hi) / 2.0
    half = (hi - lo) / 2.0
    fallback = float(half.max()) if half.max() > 0 else 1.0
    half = np.where(half > 0, half, fallback)
    q = np.rint((p - center) / half * 32767.0)
    q = np.clip(q, -32767, 32767).astype(np.int16)
    return q, [float(x) for x in center], [float(x) for x in half]
