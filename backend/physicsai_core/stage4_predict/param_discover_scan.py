"""④ 파라미터 세트 자동 구성의 폴더 탐색(링크·숨김·산출 폴더 제외, 상한)과 tpl·CAD·조립 폴더 후보 찾기 — param_discover에서 재노출."""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..naming import TPL_NAME
from ..paths import (
    BACKUP_DIR,
    PLATFORM_DIR,
    STUDY_OUTPUT_DIRS,
    STUDY_OUTPUT_DIRS_2,
    is_link_or_reparse,
    is_under,
    real,
)
from ..tpl_render import PARAM_DECL_RE
from .prepared_input import is_mesh_file

PARAM_FULL_RE = re.compile(
    r'\{\s*parameter\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"([^"]+)"\s*,\s*([^,()}]+?)\s*,\s*([^,()}]+?)\s*,\s*([^,()}]+?)\s*\)\s*\}')
_QUOTED_RE = re.compile(r'"([^"]*)"')
_TEMPLATE_PREFIXES = ("temaplate_", "template_")  # 원본 CONFIG/TEMPLATE 빈 틀 이름(오타 포함 그대로)
_ASSEM_HINTS = ("radioss", "assem")
_CAD_DIR_HINT = "cad"
ROOT_REL = "."
MESH_ONLY_NOTE = "조립 폴더 없음 — m1 메시로 바로 예측합니다"


@dataclass
class Scan:
    dirs: dict[str, list[str]] = field(default_factory=dict)  # 상대 폴더("." = 루트) → 직계 파일 이름
    truncated: bool = False
    entries: int = 0
    skipped_links: int = 0
    skipped_runs: int = 0
    skipped_outputs: int = 0


@dataclass
class TplInfo:
    rel: str
    name: str
    dir_rel: str
    decl: dict[str, str]
    cad_ref: str | None
    rank: tuple[Any, ...]
    params: list[dict[str, Any]] | None  # None = parameter 값이 숫자가 아님
    text: str


def _rel(dir_rel: str, name: str) -> str:
    return name if dir_rel == ROOT_REL else f"{dir_rel}/{name}"


def _abs(root: str, rel: str) -> str:
    return root if rel == ROOT_REL else os.path.join(root, *rel.split("/"))


def _hidden(entry: os.DirEntry[str]) -> bool:
    if entry.name.startswith("."):
        return True
    try:
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0))


def study_output_dir(path: str, ai_root: str | None, inbox_dir: str | None = None) -> str | None:
    """`path`가 `<ai_root>/<Study>/<플랫폼 산출 폴더>`(04_params·logs·01_train/tpl 등) 안이면 그 폴더 이름. 아니면 None."""
    if not ai_root:
        return None
    inbox0 = (inbox_dir or "").replace("\\", "/").split("/")[0].casefold()
    for base in dict.fromkeys((os.path.normpath(ai_root), real(ai_root))):
        if not is_under(path, base):
            continue
        rel = os.path.relpath(path, base)
        parts = [] if rel == "." else [x.casefold() for x in rel.split(os.sep)]
        if len(parts) < 2 or parts[0] in (inbox0, PLATFORM_DIR):
            continue
        if parts[1] in STUDY_OUTPUT_DIRS or parts[1] in STUDY_OUTPUT_DIRS_2:
            return parts[1]
        if len(parts) >= 3 and f"{parts[1]}/{parts[2]}" in STUDY_OUTPUT_DIRS_2:
            return f"{parts[1]}/{parts[2]}"
    return None


def scan_tree(root: str, *, max_depth: int, max_entries: int, run_dir_re: re.Pattern[str] | None,
              ai_root: str | None = None, inbox_dir: str | None = None) -> Scan:
    """너비 우선(얕은 곳 먼저) 탐색. 링크·숨김·_backup·_platform·HST run 폴더·Study 산출 폴더는 들어가지 않는다."""
    sc = Scan()
    if study_output_dir(root, ai_root, inbox_dir):
        sc.skipped_outputs += 1
        return sc
    q: deque[tuple[str, int]] = deque([(ROOT_REL, 0)])
    while q:
        rel, depth = q.popleft()
        try:
            with os.scandir(_abs(root, rel)) as it:
                items = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        files: list[str] = []
        for e in items:
            if sc.entries >= max_entries:
                sc.truncated = True
                break
            sc.entries += 1
            if _hidden(e):
                continue
            if is_link_or_reparse(e.path):
                sc.skipped_links += 1
                continue
            if e.is_dir(follow_symlinks=False):
                low = e.name.casefold()
                if low in (BACKUP_DIR, PLATFORM_DIR):
                    continue
                if run_dir_re is not None and run_dir_re.match(e.name):
                    sc.skipped_runs += 1
                    continue
                if study_output_dir(e.path, ai_root, inbox_dir):  # 04_params 등 플랫폼 산출 tpl·조립 사본은 후보 아님
                    sc.skipped_outputs += 1
                    continue
                if depth < max_depth:
                    q.append((_rel(rel, e.name), depth + 1))
            elif e.is_file(follow_symlinks=False):
                files.append(e.name)
        sc.dirs[rel] = files
        if sc.truncated:
            break
    return sc


def _num(s: str) -> float | None:
    try:
        v = float(s.strip().rstrip("mM").strip()) if s.strip() else None
    except ValueError:
        return None
    return v


def _tpl_params(text: str) -> list[dict[str, Any]] | None:
    out: list[dict[str, Any]] = []
    for m in PARAM_FULL_RE.finditer(text):
        nom, lo, hi = _num(m.group(3)), _num(m.group(4)), _num(m.group(5))
        if nom is None or lo is None or hi is None:
            return None
        out.append({"name": m.group(2).strip(), "nominal": nom, "min": lo, "max": hi, "unit": ""})
    return out


def cad_ref_of(text: str, prt_regex: str) -> str | None:
    m = re.search(prt_regex, text)
    if not m:
        return None
    q = _QUOTED_RE.search(m.group(0))
    return q.group(1) if q else None


def _cad_name(ref: str) -> str:
    return ref.replace("\\", "/").rstrip("/").split("/")[-1]


def _depth(rel: str) -> int:
    return 0 if rel == ROOT_REL else rel.count("/") + 1


def find_tpls(root: str, sc: Scan, *, max_bytes: int, prt_regex: str, notes: list[dict[str, Any]]) -> list[TplInfo]:
    out: list[TplInfo] = []
    for d, files in sc.dirs.items():
        for n in files:
            if not n.casefold().endswith(".tpl"):
                continue
            p = os.path.join(_abs(root, d), n)
            rel = _rel(d, n)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if size > max_bytes:
                notes.append({"code": "TPL_TOO_LARGE", "message": f"{rel}: 크기 상한({max_bytes} bytes)을 넘어 읽지 않았습니다"})
                continue
            try:
                with open(p, encoding="utf-8-sig", errors="strict") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                notes.append({"code": "TPL_UNREADABLE", "message": f"{rel}: UTF-8로 읽을 수 없어 건너뛰었습니다"})
                continue
            decl = {m.group(1): m.group(2) for m in PARAM_DECL_RE.finditer(text)}
            if not decl:
                continue
            low = n.casefold()
            kind = 0 if low == TPL_NAME else (2 if low.startswith(_TEMPLATE_PREFIXES) else 1)
            out.append(TplInfo(rel=rel, name=n, dir_rel=d, decl=decl, cad_ref=cad_ref_of(text, prt_regex),
                               rank=(kind, _depth(d), rel.casefold()), params=_tpl_params(text), text=text))
    return sorted(out, key=lambda t: t.rank)


def find_cads(sc: Scan, tpl: TplInfo, cad_exts: list[str]) -> list[str]:
    """tpl `dir_file_prt` 파일명과 같은 이름(대소문자 무시). tpl 폴더에 있으면 그것만. 참조가 없으면 cad_extensions 파일 전부."""
    if tpl.cad_ref:
        want = _cad_name(tpl.cad_ref).casefold()
        same = [n for n in sc.dirs.get(tpl.dir_rel, []) if n.casefold() == want]
        if same:
            return [_rel(tpl.dir_rel, same[0])]
        hits = [(d, n) for d, fs in sc.dirs.items() for n in fs if n.casefold() == want]
    else:
        exts = tuple(e.casefold() for e in cad_exts)
        hits = [(d, n) for d, fs in sc.dirs.items() for n in fs if n.casefold().endswith(exts)]
    hits.sort(key=lambda x: (x[0] != tpl.dir_rel, _CAD_DIR_HINT not in x[0].split("/")[-1].casefold(), _depth(x[0]),
                             _rel(*x).casefold()))
    return [_rel(d, n) for d, n in hits]


def find_assems(sc: Scan, starter_glob: str, renum_csv_name: str) -> tuple[list[dict[str, Any]], list[str]]:
    """starter(eps_mesh 제외) 정확히 1개인 폴더 → 후보. 2개 이상인 폴더는 안내용으로 따로."""
    cands, multi = [], []
    renum = renum_csv_name.casefold()
    for d, files in sc.dirs.items():
        starters = [n for n in files if fnmatch.fnmatch(n, starter_glob) and not is_mesh_file(n)]
        if len(starters) > 1:
            multi.append(f"{d}({len(starters)}개)")
        if len(starters) != 1:
            continue
        has_mesh = any(is_mesh_file(n) for n in files)
        has_csv = any(n.casefold() == renum for n in files)
        base = (d if d != ROOT_REL else "").split("/")[-1].casefold()
        cands.append({
            "rel": d, "starter": starters[0], "has_eps_mesh": has_mesh, "has_renum_csv": has_csv,
            "file_count": sum(1 for n in files if n.casefold().endswith((".rad", ".inc")) and not is_mesh_file(n)),
            "_rank": (not (has_mesh or has_csv), not any(h in base for h in _ASSEM_HINTS), _depth(d), d.casefold()),
        })
    cands.sort(key=lambda c: c["_rank"])
    for c in cands:
        c.pop("_rank")
    return cands, sorted(multi)


def _first_in(sc: Scan, dirs: list[str], names: tuple[str, ...]) -> str | None:
    for d in dirs:
        files = {n.casefold(): n for n in sc.dirs.get(d, [])}
        for want in names:
            if want in files:
                return _rel(d, files[want])
    return None


def _pick(cands: list[str], chosen: str | None) -> str | None:
    if chosen is not None:
        return chosen if chosen in cands else None
    return cands[0] if len(cands) == 1 else None
