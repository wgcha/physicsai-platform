"""모델 속성(쿠션 bbox·부피·CoG, data-health.md §3.3, DH-14) — 입력 메시 include(altair·native 공통)에서 계산, 서명 캐시.

파서·상한은 equiv `mesh_volume`과 같다(`equiv.volume.read_include`·`read_tree`·`resolve_parts`, 상한 = fem_verify.include_scan_max_bytes × 16).
쿠션 기준 include는 쿠션 메시만이라 parts=None(솔리드 전체)이고, 조립 매칭 run은 트리 + 매칭 PART id. 균일 밀도 가정(쿠션 단일 재료).
캐시: `<캐시 폴더>/<sha256(abs path|size|mtime_ns)>.json`(include 1개당, 조립 트리는 트리 파일 서명 전체 + PART id) — 같은 서명이면 다시 파싱하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..equiv import volume as vol
from ..errors import StepFailure
from ..fileutil import write_json_atomic

ATTR_IDS = ("bbox_dx", "bbox_dy", "bbox_dz", "cog_x", "cog_y", "cog_z", "volume")
CACHE_VERSION = 1


@dataclass
class AttrResult:
    values: dict[str, float] = field(default_factory=dict)   # 성공한 속성(ATTR_IDS)
    na: str | None = None                                     # 전부 NA일 때 사유(MESH_MISSING·NO_SOLID)
    skipped_kinds: list[str] = field(default_factory=list)   # 미지원 요소형(경고 EQ_VOLUME_ELEM_SKIPPED와 같은 문구용)
    n_elems: int = 0
    from_cache: bool = False


def solid_attrs(mesh: vol.IncludeMesh, parts: Sequence[str] | None) -> AttrResult:
    """대상 PART(None = 전부)의 솔리드 요소로 bbox(요소 노드 합집합)·부피·부피 가중 중심. 요소 0개 → NA NO_SOLID."""
    want = [str(p) for p in parts] if parts is not None else sorted(mesh.elems)
    total, n = 0.0, 0
    cx = cy = cz = 0.0
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for p in want:
        for kind, ids in mesh.elems.get(p, []):
            v = vol.element_volume(kind, ids, mesh.nodes)
            if v is None:
                continue
            pts = [mesh.nodes[i] for i in ids]
            corners = pts[:4] if kind in ("TETRA4", "TETRA10") else pts
            m = len(corners)
            total += v
            n += 1
            cx += v * sum(c[0] for c in corners) / m
            cy += v * sum(c[1] for c in corners) / m
            cz += v * sum(c[2] for c in corners) / m
            for q in pts:
                for a in range(3):
                    lo[a] = min(lo[a], q[a])
                    hi[a] = max(hi[a], q[a])
    res = AttrResult(skipped_kinds=list(sorted(mesh.skipped_kinds)), n_elems=n)
    if n == 0 or total <= 0:
        res.na = "NO_SOLID"
        return res
    res.values = {"bbox_dx": hi[0] - lo[0], "bbox_dy": hi[1] - lo[1], "bbox_dz": hi[2] - lo[2],
                  "cog_x": cx / total, "cog_y": cy / total, "cog_z": cz / total, "volume": total}
    return res


def _sig(path: str) -> str:
    st = os.stat(path)
    return f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}"


def _tree_sig(folder: str) -> str:
    from ..geometry.asm_tree import AsmTreeError, build

    try:
        tree = build(folder)
    except (AsmTreeError, OSError):
        return ""
    return "|".join(_sig(f.path) for f in sorted(tree.files, key=lambda f: f.path))


def cache_key(inc: str | None, tree: str | None, parts: Sequence[str] | None) -> str | None:
    """서명 키(sha256 hex). 파일이 없거나 트리를 못 읽으면 None."""
    try:
        if inc:
            raw = _sig(inc)
        elif tree:
            raw = _tree_sig(tree)
            if not raw:
                return None
            raw += "|parts=" + ",".join(sorted(str(p) for p in (parts or [])))
        else:
            return None
    except OSError:
        return None
    return hashlib.sha256(f"v{CACHE_VERSION}|{raw}".encode("utf-8")).hexdigest()


def _from_doc(doc: Mapping[str, Any]) -> AttrResult:
    vals = {k: float(doc["values"][k]) for k in ATTR_IDS if isinstance(doc.get("values"), Mapping) and k in doc["values"]}
    return AttrResult(vals, doc.get("na"), list(doc.get("skipped_kinds") or []), int(doc.get("n_elems") or 0), True)


def model_attrs(*, mesh_inc: str | None, mesh_tree: str | None, mesh_parts: Sequence[str] | None, max_bytes: int,
                cache_dir: str | None) -> AttrResult:
    """run 1개의 모델 속성. include·트리가 없거나 읽을 수 없으면 NA MESH_MISSING(equiv와 같은 사유 이름)."""
    key = cache_key(mesh_inc, mesh_tree, None if mesh_inc else mesh_parts)
    if key is None:
        return AttrResult(na="MESH_MISSING")
    cp = os.path.join(cache_dir, f"{key}.json") if cache_dir else None
    if cp and os.path.isfile(cp):
        try:
            with open(cp, encoding="utf-8") as fh:
                doc = json.load(fh)
            if isinstance(doc, Mapping) and doc.get("version") == CACHE_VERSION:
                return _from_doc(doc)
        except (OSError, ValueError, TypeError):
            pass  # 깨진 캐시는 무시하고 다시 계산
    mesh = vol.read_include(mesh_inc, max_bytes=max_bytes) if mesh_inc else vol.read_tree(str(mesh_tree), max_bytes=max_bytes)
    if mesh is None:
        return AttrResult(na="MESH_MISSING")
    res = solid_attrs(mesh, None if mesh_inc else vol.resolve_parts("cushion", mesh_parts))
    if cp:
        try:
            os.makedirs(cache_dir, exist_ok=True)  # type: ignore[arg-type]
            write_json_atomic(cp, {"version": CACHE_VERSION, "values": res.values, "na": res.na, "skipped_kinds": res.skipped_kinds,
                                   "n_elems": res.n_elems})
        except (OSError, StepFailure):
            pass  # 캐시 쓰기 실패는 계산 결과에 영향 없음
    return res
