"""④ 파라미터 세트 자동 구성(phase3 §13 S8, D3-47): 프로젝트 폴더 1개를 읽기만 하며 tpl·CAD·조립 폴더·파라미터를 찾는다.

원본 관례(읽기 전용 참고, 저장소 복사 금지):
- tpl: 원본 ①-1 GUI(`1_gui_create_tpl_file.py:347-357`)가 작업 폴더에 `simlab_parametered_mesh.tpl`을 만들고, 그 옆에 빈 틀
  `TEMAPLATE_simlab_parametered_mesh.tpl`(예시 parameter 줄·절대 CAD 경로)을 둔다 → 이름이 같은 것 우선, `TEMAPLATE_`/`TEMPLATE_` 마지막.
  `{parameter(var_i, "<이름>", <nominal>, <min>, <max>)}`(`1_create_tpl_file.py:144-152`)에서 파라미터를 만든다.
- CAD: tpl의 `dir_file_prt = r"./<CAD>"`(`1_create_tpl_file.py:135-139`, SimLab cwd 상대) 파일명. tpl 폴더 우선.
- 조립 폴더: 원본 `RADIOSS_ASSEM_DIR`("Radioss 입력 폴더", `1_gui_physicsai_opti.py:87`) — starter `*_0000.rad`(eps_mesh 제외)
  정확히 1개(GUI :427-445). SimLab 메시 사본(`EPS_mesh_0000.rad`)·`RENUM_INIT.csv`가 함께 있으면 우선, 이름에 radioss·assem이 있으면 다음.
- HyperStudy run 폴더(`train_data.result_run_dir_regex`, 원본 `approaches/*/run__N`)는 run마다 starter가 있어 건너뛴다.

탐색: 링크·junction·숨김·`_backup`·`_platform`(대소문자 무시) 제외, 깊이·항목 수 상한(넘으면 truncated), 파일 내용은 tpl만(크기 상한).
"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..fileutil import copy_file, write_json, write_text
from ..naming import NAME_RE, TPL_NAME
from ..paths import BACKUP_DIR, PLATFORM_DIR, is_link_or_reparse
from ..tpl_render import PARAM_DECL_RE
from .param_set_files import ParamSetFolder, _load_parameters
from .prepared_input import is_mesh_file

PARAM_FULL_RE = re.compile(
    r'\{\s*parameter\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"([^"]+)"\s*,\s*([^,()}]+?)\s*,\s*([^,()}]+?)\s*,\s*([^,()}]+?)\s*\)\s*\}')
_QUOTED_RE = re.compile(r'"([^"]*)"')
_TEMPLATE_PREFIXES = ("temaplate_", "template_")  # 원본 CONFIG/TEMPLATE 빈 틀 이름(오타 포함 그대로)
_ASSEM_HINTS = ("radioss", "assem")
_CAD_DIR_HINT = "cad"
ROOT_REL = "."


@dataclass
class Scan:
    dirs: dict[str, list[str]] = field(default_factory=dict)  # 상대 폴더("." = 루트) → 직계 파일 이름
    truncated: bool = False
    entries: int = 0
    skipped_links: int = 0
    skipped_runs: int = 0


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


def scan_tree(root: str, *, max_depth: int, max_entries: int, run_dir_re: re.Pattern[str] | None) -> Scan:
    """너비 우선(얕은 곳 먼저) 탐색. 링크·숨김·_backup·_platform·HST run 폴더는 들어가지 않는다."""
    sc = Scan()
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


@dataclass
class Discovery:
    root: str
    tpls: list[TplInfo]
    selected_tpl: TplInfo | None
    cad: list[str]
    assem: list[dict[str, Any]]
    parameters_source: str | None
    parameters_file: str | None
    parameters: list[dict[str, Any]]
    samples: str | None
    responses: str | None
    problems: list[dict[str, Any]]
    notes: list[dict[str, Any]]
    truncated: bool
    scanned: int

    def out(self) -> dict[str, Any]:
        return {
            "path": self.root,
            "tpl": [{"rel": t.rel, "name": t.name, "parameter_count": len(t.decl), "cad_ref": t.cad_ref} for t in self.tpls],
            "selected_tpl": self.selected_tpl.rel if self.selected_tpl else None,
            "cad": [{"rel": c, "name": c.split("/")[-1]} for c in self.cad],
            "radioss_assem": self.assem,
            "parameters_source": self.parameters_source,
            "parameters_file": self.parameters_file,
            "parameters": self.parameters,
            "samples": self.samples,
            "responses": self.responses,
            "problems": self.problems,
            "notes": self.notes,
            "truncated": self.truncated,
            "scanned": self.scanned,
        }


def discover(root: str, settings: Any, *, tpl: str | None = None) -> Discovery:
    """프로젝트 폴더(이미 check_user_path 통과)에서 후보를 찾는다. 디스크 쓰기 없음. `tpl` = 사용자가 고른 tpl 상대경로."""
    ps, pr, td = settings.param_set, settings.predict, settings.train_data
    run_re = re.compile(td.result_run_dir_regex) if td.result_run_dir_regex else None
    sc = scan_tree(root, max_depth=ps.discover_max_depth, max_entries=ps.discover_max_entries, run_dir_re=run_re)
    problems: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    if sc.truncated:
        notes.append({"code": "SCAN_TRUNCATED",
                      "message": f"항목이 많아 {ps.discover_max_entries}개까지만 찾았습니다 — 더 아래 폴더를 지정하세요"})
    if sc.skipped_runs:
        notes.append({"code": "RUN_DIRS_SKIPPED", "message": f"HyperStudy run 폴더 {sc.skipped_runs}개는 건너뛰었습니다"})
    if sc.skipped_links:
        notes.append({"code": "LINKS_SKIPPED", "message": f"링크 {sc.skipped_links}개는 건너뛰었습니다"})
    tpls = find_tpls(root, sc, max_bytes=ps.discover_tpl_max_bytes, prt_regex=td.tpl_prt_regex, notes=notes)
    by_rel = {t.rel: t for t in tpls}
    sel: TplInfo | None = None
    if tpl is not None:
        sel = by_rel.get(tpl)
        if sel is None:
            problems.append({"code": "CHOICE_INVALID", "message": f"고른 tpl({tpl})을 찾은 목록에서 찾을 수 없습니다"})
    elif len(tpls) == 1:
        sel = tpls[0]
    if not tpls:
        problems.append({"code": "TPL_NOT_FOUND",
                         "message": "{parameter(…)} 블록이 있는 SimLab tpl(*.tpl)을 찾지 못했습니다"})
    assem, multi = find_assems(sc, pr.starter_glob, pr.renum_csv_name)
    if not assem:
        msg = f"starter({pr.starter_glob}, eps_mesh 제외)가 정확히 1개인 Radioss 조립 폴더를 찾지 못했습니다"
        if multi:
            msg += " — starter가 여러 개인 폴더: " + ", ".join(multi[:5])
        problems.append({"code": "ASSEM_NOT_FOUND", "message": msg})
    cad: list[str] = []
    p_src, p_file, params = None, None, []
    samples = responses = None
    if sel is not None:
        cad = find_cads(sc, sel, td.cad_extensions)
        if not cad:
            want = _cad_name(sel.cad_ref) if sel.cad_ref else "CAD(" + " ".join(td.cad_extensions) + ")"
            problems.append({"code": "CAD_NOT_FOUND", "message": f"tpl이 가리키는 {want} 파일을 찾지 못했습니다"})
        if not sel.cad_ref:
            notes.append({"code": "TPL_CAD_REF_MISSING", "message": "tpl에 dir_file_prt 줄이 없어 CAD 확장자로 찾았습니다"})
        elif not sel.cad_ref.startswith("./"):
            notes.append({"code": "TPL_CAD_PATH_REWRITE",
                          "message": "tpl의 CAD 경로가 ./<파일명> 형식이 아니라 등록 사본에서 ./<CAD 파일명>으로 바꿉니다"})
        look = [sel.dir_rel] + ([ROOT_REL] if sel.dir_rel != ROOT_REL else [])
        p_file = _first_in(sc, look, ("parameters.json", "parameters.csv"))
        if p_file:
            p_src = "file"
            pf = ParamSetFolder()
            _load_parameters(pf, os.path.dirname(_abs(root, p_file)))
            params = pf.parameters
            problems.extend({**x, "file": p_file} for x in pf.problems)
            if pf.parameters and {p["name"] for p in pf.parameters} != set(sel.decl.values()):
                problems.append({"code": "PARAM_TPL_MISMATCH",
                                 "message": f"{p_file}의 파라미터 이름이 tpl의 parameter 이름과 다릅니다"})
        else:
            p_src = "tpl"
            if sel.params is None or not sel.params:
                problems.append({"code": "TPL_PARAMETERS_INVALID",
                                 "message": "tpl의 {parameter(var, \"이름\", nominal, min, max)} 값을 숫자로 읽을 수 없습니다"})
            else:
                pf = ParamSetFolder()
                _check_rows(pf, sel.params)
                params = pf.parameters
                problems.extend(pf.problems)
        samples = _first_in(sc, look, ("samples.csv",))
        responses = _first_in(sc, look, ("responses.json",))
    elif len(tpls) > 1:
        notes.append({"code": "TPL_CHOICE_REQUIRED", "message": f"tpl 후보가 {len(tpls)}개입니다 — 하나를 고르세요"})
    return Discovery(root=root, tpls=tpls, selected_tpl=sel, cad=cad, assem=assem, parameters_source=p_src,
                     parameters_file=p_file, parameters=params, samples=samples, responses=responses, problems=problems,
                     notes=notes, truncated=sc.truncated, scanned=sc.entries)


def _check_rows(pf: ParamSetFolder, rows: list[dict[str, Any]]) -> None:
    """tpl에서 만든 파라미터를 parameters.json과 같은 규칙으로 검사(이름·중복·범위). 등록 때 validate_folder가 다시 검사한다."""
    seen: set[str] = set()
    for r in rows:
        name = r["name"]
        if not NAME_RE.match(name):
            pf.problems.append({"code": "PARAMETER_NAME_INVALID",
                                "message": f"tpl 파라미터 이름 '{name}'이 규칙(^[A-Za-z_][A-Za-z0-9_]{{0,63}}$)에 맞지 않습니다"})
            continue
        if name in seen:
            pf.problems.append({"code": "PARAMETER_DUPLICATE", "message": f"tpl 파라미터 이름 '{name}'이 중복됩니다"})
            continue
        seen.add(name)
        if not r["min"] <= r["nominal"] <= r["max"]:
            pf.problems.append({"code": "PARAMETER_RANGE_INVALID", "message": f"'{name}': min ≤ nominal ≤ max 이어야 합니다"})
            continue
        pf.parameters.append(dict(r))


# ---------------------------------------------------------------------------------------------------------------------
# 등록: 고른 후보를 §15.4 폴더 구조로 모은다(원본 위치는 읽기만). 이후 검증·정규화는 기존 validate_folder·write_normalized.
# ---------------------------------------------------------------------------------------------------------------------


def resolve_choice(d: Discovery, choice: dict[str, str | None]) -> tuple[TplInfo | None, str | None, dict[str, Any] | None,
                                                                         list[dict[str, Any]]]:
    probs: list[dict[str, Any]] = []
    tpl = d.selected_tpl
    cad = _pick(d.cad, choice.get("cad"))
    rels = [a["rel"] for a in d.assem]
    arel = _pick(rels, choice.get("radioss_assem"))
    assem = next((a for a in d.assem if a["rel"] == arel), None)
    for key, val, cands in (("tpl", tpl, d.tpls), ("cad", cad, d.cad), ("radioss_assem", assem, d.assem)):
        given = choice.get(key)
        if key == "tpl" and given is not None:
            continue  # 고른 tpl이 목록에 없으면 discover가 CHOICE_INVALID를 이미 넣었다
        if val is None and cands:
            probs.append({"code": "CHOICE_INVALID" if given is not None else "CHOICE_REQUIRED",
                          "message": f"{key} 후보 {len(cands)}개 중 하나를 고르세요" if given is None
                          else f"고른 {key}({given})가 찾은 목록에 없습니다"})
    return tpl, cad, assem, probs


def copy_sources(d: Discovery, tpl: TplInfo, cad_rel: str, assem: dict[str, Any], dst: str, settings: Any) -> int:
    """§15.4 폴더 구조로 dst에 모은다. 복사한 바이트 수. 읽기만(원본 위치)."""
    root = d.root
    pr, td = settings.predict, settings.train_data
    cad_name = cad_rel.split("/")[-1]
    total = 0
    # tpl: CAD 경로가 ./<CAD>가 아니면 원본 update_parameter_file(:135-139)처럼 ./<CAD 파일명>으로 바꿔 쓴다
    src_tpl = _abs(root, tpl.rel)
    if tpl.cad_ref is not None and (not tpl.cad_ref.startswith("./") or _cad_name(tpl.cad_ref) != cad_name):
        text = re.sub(td.tpl_prt_regex, lambda _m: f'dir_file_prt = r"./{cad_name}"', tpl.text)
        write_text(os.path.join(dst, TPL_NAME), text)
        total += len(text.encode("utf-8"))
    else:
        total += copy_file(src_tpl, os.path.join(dst, TPL_NAME))
    total += copy_file(_abs(root, cad_rel), os.path.join(dst, "cad", cad_name))
    if d.parameters_source == "file" and d.parameters_file:
        total += copy_file(_abs(root, d.parameters_file), os.path.join(dst, d.parameters_file.split("/")[-1].lower()))
    else:
        write_json(os.path.join(dst, "parameters.json"),
                   {"schema_version": 1, "unit_system": "mm-ton-s", "parameters": d.parameters})
    for rel, name in ((d.samples, "samples.csv"), (d.responses, "responses.json")):
        if rel:
            total += copy_file(_abs(root, rel), os.path.join(dst, name))
    adir = _abs(root, assem["rel"])
    renum = pr.renum_csv_name.casefold()
    for n in sorted(os.listdir(adir)):
        p = os.path.join(adir, n)
        if not os.path.isfile(p) or is_link_or_reparse(p) or is_mesh_file(n):
            continue
        if n.casefold().endswith((".rad", ".inc")) or n.casefold() == renum:
            total += copy_file(p, os.path.join(dst, "radioss_assem", n))
    return total


def planned_bytes(d: Discovery, tpl: TplInfo, cad_rel: str, assem: dict[str, Any], settings: Any) -> int:
    """복사 전 총량 추정(상한 검사용)."""
    root = d.root
    files = [_abs(root, tpl.rel), _abs(root, cad_rel)]
    files += [_abs(root, r) for r in (d.parameters_file, d.samples, d.responses) if r]
    adir = _abs(root, assem["rel"])
    files += [os.path.join(adir, n) for n in os.listdir(adir) if not is_mesh_file(n)
              and n.casefold().endswith((".rad", ".inc", settings.predict.renum_csv_name.casefold()))]
    total = 0
    for f in files:
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    return total
