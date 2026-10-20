"""메시 부피(equiv-check.md §4.3 mesh_volume) — Radioss include 블록 형식 파서 + 솔리드 요소 부피 합.

지원 요소: `/TETRA4/<part>`(4 꼭짓점 사면체), `/TETRA10/<part>`(앞 4 꼭짓점만), `/BRICK/<part>`(hexa8 → 사면체 5분할).
그 밖 솔리드·쉘 블록은 건너뛰고 종류를 돌려준다(호출자가 경고 EQ_VOLUME_ELEM_SKIPPED). 좌표는 `/NODE` 블록.
파일 읽기는 `read_include`만(상한 바이트, 링크 거부는 호출자). 계산은 순수 함수.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Point = tuple[float, float, float]
_SOLID_COUNTS = {"TETRA4": 4, "TETRA10": 10, "BRICK": 8}
# hexa8(Radioss BRICK 노드 순서 1~8: 아래 면 1-2-3-4, 위 면 5-6-7-8) → 사면체 5분할(0-based)
_HEXA_TETS = ((0, 1, 3, 4), (1, 2, 3, 6), (1, 4, 5, 6), (3, 4, 6, 7), (1, 3, 4, 6))
# 부피를 알아도 세지 않는 비솔리드 블록(경고 대상이 아님)
_NON_SOLID = {"NODE", "PART", "SHELL", "SH3N", "SPRING", "BEAM", "TRUSS", "RBODY", "GRNOD", "GRSHEL", "GRBRIC", "SURF",
              "BEGIN", "END", "INTER", "MAT", "PROP", "TITLE", "FUNCT", "BCS", "RWALL", "ACCEL", "TH", "GRAV", "INIVEL",
              "DEF_SHELL", "DEF_SOLID", "ANIM", "RUN", "IMPVEL", "SUBSET", "SET", "DFS", "ALE", "MONVOL", "DAMP", "RANDOM"}


@dataclass
class IncludeMesh:
    nodes: dict[int, Point] = field(default_factory=dict)
    # part id(문자) → [(kind, [node ids])]
    elems: dict[str, list[tuple[str, list[int]]]] = field(default_factory=dict)
    skipped_kinds: set[str] = field(default_factory=set)
    part_titles: dict[str, str] = field(default_factory=dict)


def _floats(line: str, n: int) -> list[float] | None:
    toks = line.split()
    try:
        vals = [float(t) for t in toks[:n]]
    except ValueError:
        return None
    return vals if len(vals) == n else None


def _ints(line: str) -> list[int]:
    out: list[int] = []
    for t in line.split():
        try:
            out.append(int(t))
        except ValueError:
            return out
    return out


def parse_include(lines: Iterable[str]) -> IncludeMesh:
    """Radioss 블록 텍스트 → IncludeMesh. `#` 주석 줄 무시, 블록 머리는 `/KEY/...`."""
    m = IncludeMesh()
    block: str | None = None
    part: str = ""
    pending: list[int] = []
    need = 0
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("/"):
            parts = line.strip().split("/")
            key = parts[1].strip().upper() if len(parts) > 1 else ""
            block = key
            part = parts[2].strip() if len(parts) > 2 else ""
            pending, need = [], (_SOLID_COUNTS.get(key, 0) + 1 if key in _SOLID_COUNTS else 0)
            if key in _SOLID_COUNTS:
                m.elems.setdefault(part, [])
            elif key == "PART" and part:
                m.part_titles.setdefault(part, "")
            elif key not in _NON_SOLID and key and (key.startswith(("TETRA", "BRIC", "PENTA", "HEXA", "SOLID", "SHEL"))):
                m.skipped_kinds.add(key)
            continue
        if block == "NODE":
            toks = line.split()
            if len(toks) >= 4:
                try:
                    m.nodes[int(toks[0])] = (float(toks[1]), float(toks[2]), float(toks[3]))
                except ValueError:
                    continue
            continue
        if block == "PART" and part and m.part_titles.get(part) == "":
            m.part_titles[part] = line.strip()
            continue
        if block in _SOLID_COUNTS:
            pending += _ints(line)
            while len(pending) >= need:
                ids = pending[1:need]
                pending = pending[need:]
                m.elems[part].append((block, ids))
    return m


def read_include(path: str, *, max_bytes: int) -> IncludeMesh | None:
    """include 파일 읽기(크기 상한 초과·없음 → None)."""
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return parse_include(fh)
    except OSError:
        return None


def tet_volume(p0: Point, p1: Point, p2: Point, p3: Point) -> float:
    a = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    b = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    c = (p3[0] - p0[0], p3[1] - p0[1], p3[2] - p0[2])
    det = (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return abs(det) / 6.0


def hexa_volume(p: Sequence[Point]) -> float:
    return sum(tet_volume(p[i], p[j], p[k], p[l]) for i, j, k, l in _HEXA_TETS)


def element_volume(kind: str, ids: Sequence[int], nodes: Mapping[int, Point]) -> float | None:
    try:
        pts = [nodes[i] for i in ids]
    except KeyError:
        return None
    if kind in ("TETRA4", "TETRA10"):
        return tet_volume(pts[0], pts[1], pts[2], pts[3])
    if kind == "BRICK":
        return hexa_volume(pts)
    return None


@dataclass(frozen=True)
class VolumeResult:
    volume: float
    n_elems: int
    n_missing_nodes: int
    parts: tuple[str, ...]
    skipped_kinds: tuple[str, ...]


def part_volume(mesh: IncludeMesh, parts: Sequence[str] | None) -> VolumeResult:
    """대상 part(None = 전부) 솔리드 요소 부피 합."""
    want = [str(p) for p in parts] if parts is not None else sorted(mesh.elems)
    vol, n, miss = 0.0, 0, 0
    for p in want:
        for kind, ids in mesh.elems.get(p, []):
            v = element_volume(kind, ids, mesh.nodes)
            if v is None:
                miss += 1
                continue
            vol += v
            n += 1
    return VolumeResult(vol, n, miss, tuple(want), tuple(sorted(mesh.skipped_kinds)))


def resolve_parts(src_parts: Any, cushion_part_ids: Sequence[str] | None) -> list[str] | None:
    """레시피 `parts`("cushion" | id 목록) → part id 목록. cushion인데 템플릿 id가 없으면 None(= 전체 솔리드)."""
    if isinstance(src_parts, list):
        return [str(p) for p in src_parts]
    if cushion_part_ids:
        return [str(p) for p in cushion_part_ids]
    return None
