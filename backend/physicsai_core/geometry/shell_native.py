"""쉘 판금(비드) 모핑 세트(`kind=shell`) 플랫폼 쪽 순수 함수(shell-morph.md §4.2·§8). 표준 라이브러리만.

- 준비본 `native/`(쉘): prep.json(`kind:"shell"`, `inputs.assem_digest`, `fixed_digest`, baseline_inc·renum_csv null),
  extract/shell_features.json, fixed/shell_scan.json, tag/shell_tag.json. `kind` 키가 없으면 solid(기존 준비본 호환).
- 파라미터 표: 쉘 피처 대표(그룹 대표 + 그룹 없는 피처) 행 `source:"shell"`. 기본 대상 component(`shell.default_component`,
  대소문자 무시)의 피처만 쓴다. 한 세트에 솔리드(쿠션) 형상 행과 쉘 형상 행을 섞지 않는다(SM §12 Q3).
- `features_view.feature_rows`가 쉘 features JSON도 같은 키(name·type·body·nominal·range·group·feasible)로 읽는다.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from typing import Any

from ..path_links import is_link_or_reparse

SOLID, SHELL = "solid", "shell"
KINDS = (SOLID, SHELL)
SHELL_SOURCE = "shell"
SHELL_FEATURES_NAME = "shell_features.json"
SOLID_FEATURES_NAME = "parameter_features.json"
SHELL_FEATURES_JSON = "native/extract/shell_features.json"
SHELL_TAG_JSON = "native/tag/shell_tag.json"
SHELL_SCAN_JSON = "native/fixed/shell_scan.json"
FIXED_DIR = "native/fixed"
SHELL_FILES_DIR = "shell_files"  # PASS 사본 `--out-files-dir`(P/geom/shell_files, R/m_2/shell_files)
THICKNESS_JSON = "shell_thickness.json"
ASSEM_EXTS = (".rad", ".inc")


def features_name(kind: str) -> str:
    return SHELL_FEATURES_NAME if kind == SHELL else SOLID_FEATURES_NAME


def kind_of_features_rel(rel: str | None) -> str:
    """①-1 `train_setups.features_rel`(…/shell_features.json | …/parameter_features.json) → kind."""
    return SHELL if (rel or "").replace("\\", "/").rsplit("/", 1)[-1] == SHELL_FEATURES_NAME else SOLID


def _read(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def read_kind(base: str) -> str:
    """준비본 폴더(S·D·baseline)의 형상 종류: prep.json `kind`(없으면 solid). prep.json이 없으면 features 파일로 판단."""
    prep = _read(os.path.join(base, "native", "prep.json"))
    if prep is not None:
        return SHELL if prep.get("kind") == SHELL else SOLID
    if os.path.isfile(os.path.join(base, *SHELL_FEATURES_JSON.split("/"))):
        return SHELL
    return SOLID


def _cached_sha(p: str) -> str:
    """경로·크기·수정시각이 같으면 캐시(prep.sha256_file) — 세트 조회마다 큰 쉘 inc를 다시 읽지 않게."""
    from .prep import sha256_file as cached

    return cached(p)


def assem_digest(assem_dir: str) -> str | None:
    """조립 폴더 `*.rad`·`*.inc`(하위 폴더 포함, 링크 제외) 상대 경로·sha256 정렬 목록의 sha256(SM §4.2). 폴더 없음 = None."""
    if not os.path.isdir(assem_dir):
        return None
    items: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(assem_dir, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not is_link_or_reparse(os.path.join(dirpath, d)) and d != "_backup")
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            if fn.lower().endswith(ASSEM_EXTS) and os.path.isfile(p) and not is_link_or_reparse(p):
                items.append((os.path.relpath(p, assem_dir).replace(os.sep, "/"), _cached_sha(p)))
    items.sort()
    return "sha256:" + hashlib.sha256(json.dumps(items, separators=(",", ":")).encode("utf-8")).hexdigest()


def fixed_digest(base: str) -> str | None:
    doc = _read(os.path.join(base, *SHELL_SCAN_JSON.split("/")))
    fixed = (doc or {}).get("fixed")
    d = fixed.get("digest") if isinstance(fixed, dict) else None
    return d if isinstance(d, str) else None


# ---- 파라미터 표 ------------------------------------------------------------------------------------------


def _same(a: Any, b: str) -> bool:
    return isinstance(a, str) and a.casefold() == b.casefold()


def component_bodies(doc: Mapping[str, Any], component: str) -> set[str]:
    """features `parts`에서 /PART 제목이 component(대소문자 무시)인 바디 이름. `PART:<id>` 표기도 받는다."""
    out: set[str] = set()
    for p in doc.get("parts") or []:
        if not isinstance(p, dict):
            continue
        if _same(p.get("title"), component) or _same(p.get("body"), component) or component == f"PART:{p.get('part_id')}":
            out.add(str(p.get("body") or p.get("title")))
    return out


def shell_rows(doc: Mapping[str, Any], component: str) -> tuple[list[dict[str, Any]], list[str]]:
    """쉘 features → 파라미터 표 행(대표만, `source:"shell"`, 기본 대상 component의 비드) + 경고 문구(한국어).

    대상 component 바디가 없으면 rows = [](호출자가 SHELL_PART_NOT_FOUND). `use_default:false`(체결 영역과 겹침) 피처는
    `use:false` 표시(①-1 표 기본값, ④ 세트에서는 정보용)."""
    bodies = component_bodies(doc, component)
    members: set[str] = set()
    reps: set[str] = set()
    for g in doc.get("groups") or []:
        if isinstance(g, dict) and isinstance(g.get("parameter"), str):
            reps.add(g["parameter"])
            members |= {m for m in g.get("members", []) if isinstance(m, str)}
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for f in doc.get("features") or []:
        if not isinstance(f, dict) or not isinstance(f.get("name"), str):
            continue
        name = f["name"]
        if name in members and name not in reps:
            continue
        if str(f.get("body") or "") not in bodies:
            skipped.append(name)
            continue
        rng = f.get("range") if isinstance(f.get("range"), dict) else {}
        num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None  # noqa: E731
        row: dict[str, Any] = {"name": name, "nominal": num(f.get("nominal")), "min": num(rng.get("min")), "max": num(rng.get("max")),
                               "unit": f.get("unit") if isinstance(f.get("unit"), str) else "mm", "source": SHELL_SOURCE}
        if f.get("use_default") is False:
            row["use"] = False
        rows.append(row)
    warns = [f"기본 대상 component({component}) 밖의 쉘 피처 {len(skipped)}개는 파라미터 표에서 뺐습니다: "
             + ", ".join(skipped[:10])] if skipped and rows else []
    return rows, warns


def is_shell_row(row: Mapping[str, Any]) -> bool:
    return row.get("source") == SHELL_SOURCE


def kind_mix_problems(rows: Iterable[Mapping[str, Any]], kind: str) -> list[dict[str, str]]:
    """한 세트에 솔리드 형상 행과 쉘 형상 행을 섞지 않는다(SM §1.3·§12 Q3). 3S 두께 행(source=prop)은 어느 쪽과도 함께 쓸 수 있다."""
    rows = list(rows)
    solid = [str(r.get("name")) for r in rows if r.get("source") is None]
    shell = [str(r.get("name")) for r in rows if is_shell_row(r)]
    bad = solid if kind == SHELL else shell
    if bad:
        return [{"code": "GEOM_KIND_MIXED", "message": "솔리드(쿠션)와 쉘(판금) 형상 파라미터는 한 세트에 함께 쓸 수 없습니다: "
                 + ", ".join(bad[:5])}]
    return []


def features_kind_problems(base: str) -> list[dict[str, str]]:
    """준비본에 솔리드·쉘 features가 함께 있으면(혼합) 문제."""
    ex = os.path.join(base, "native", "extract")
    if os.path.isfile(os.path.join(ex, SHELL_FEATURES_NAME)) and os.path.isfile(os.path.join(ex, SOLID_FEATURES_NAME)):
        return [{"code": "GEOM_KIND_MIXED", "message": "native/extract에 솔리드·쉘 피처 파일이 함께 있습니다 — 한 세트는 한 종류만 씁니다"}]
    return []


def thickness_document(rows: Iterable[Mapping[str, Any]], props_doc: Mapping[str, Any] | None, shell_values: Mapping[str, float],
                       part_ids: Iterable[int]) -> dict[str, Any] | None:
    """3S 두께 값 중 모핑 대상 part의 PROP 값 → check (d) 간섭용 `--thickness` JSON(SM §4.1·§8.4). 해당 없으면 None."""
    targets = {int(x) for x in part_ids}
    by_name = {}
    for r in (props_doc or {}).get("props") or []:
        if isinstance(r, dict) and isinstance(r.get("parameter"), str):
            by_name[r["parameter"]] = r
    parts: dict[str, float] = {}
    for name, v in shell_values.items():
        r = by_name.get(name)
        for p in (r or {}).get("parts") or []:
            pid = p.get("id") if isinstance(p, dict) else None
            if isinstance(pid, int) and pid in targets:
                parts[str(pid)] = float(v)
    return {"schema_version": 1, "parts": dict(sorted(parts.items()))} if parts else None


def target_part_ids(doc: Mapping[str, Any], component: str) -> list[int]:
    bodies = component_bodies(doc, component)
    return sorted(int(p["part_id"]) for p in doc.get("parts") or []
                  if isinstance(p, dict) and isinstance(p.get("part_id"), int) and str(p.get("body") or p.get("title")) in bodies)
