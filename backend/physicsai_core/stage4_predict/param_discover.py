"""④ 파라미터 세트 자동 구성(phase3 §13 S8, D3-47): 프로젝트 폴더 1개를 읽기만 하며 tpl·CAD·조립 폴더·파라미터를 찾는다.

원본 관례(읽기 전용 참고, 저장소 복사 금지):
- tpl: 원본 ①-1 GUI(`1_gui_create_tpl_file.py:347-357`)가 작업 폴더에 `simlab_parametered_mesh.tpl`을 만들고, 그 옆에 빈 틀
  `TEMAPLATE_simlab_parametered_mesh.tpl`(예시 parameter 줄·절대 CAD 경로)을 둔다 → 이름이 같은 것 우선, `TEMAPLATE_`/`TEMPLATE_` 마지막.
  `{parameter(var_i, "<이름>", <nominal>, <min>, <max>)}`(`1_create_tpl_file.py:144-152`)에서 파라미터를 만든다.
- CAD: tpl의 `dir_file_prt = r"./<CAD>"`(`1_create_tpl_file.py:135-139`, SimLab cwd 상대) 파일명. tpl 폴더 우선.
- 조립 폴더: 원본 `RADIOSS_ASSEM_DIR`("Radioss 입력 폴더", `1_gui_physicsai_opti.py:87`) — starter `*_0000.rad`(eps_mesh 제외)
  정확히 1개(GUI :427-445). SimLab 메시 사본(`EPS_mesh_0000.rad`)·`RENUM_INIT.csv`가 함께 있으면 우선, 이름에 radioss·assem이 있으면 다음.
- HyperStudy run 폴더(`train_data.result_run_dir_regex`, 원본 `approaches/*/run__N`)는 run마다 starter가 있어 건너뛴다.

탐색: 링크·junction·숨김·`_backup`·`_platform`(대소문자 무시)·Study 산출 폴더(`04_params` 등) 제외, 깊이·항목 수 상한
(넘으면 truncated), 파일 내용은 tpl만(크기 상한).
등록 복사(D3-50): 각 원본을 복사 직전에 다시 검사(경로 요소 링크·junction 없음, realpath가 프로젝트 폴더 안)하고
열린 핸들 기준으로 복사(O_NOFOLLOW + 연 파일과 경로의 (st_dev, st_ino) 일치) — 검사 뒤 링크로 바뀌면 거부.
"""

from __future__ import annotations

import fnmatch
import io
import os
import re
import stat
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..errors import DomainError
from ..fileutil import copy_stream, write_json
from ..naming import NAME_RE, TPL_NAME
from ..paths import (
    BACKUP_DIR,
    PLATFORM_DIR,
    STUDY_OUTPUT_DIRS,
    STUDY_OUTPUT_DIRS_2,
    PathError,
    is_link_or_reparse,
    is_under,
    real,
)
from ..tpl_render import PARAM_DECL_RE
from .param_set_files import ParamSetFolder, _load_parameters
from .param_sets import tpl_export_name
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
    st = settings.storage
    sc = scan_tree(root, max_depth=ps.discover_max_depth, max_entries=ps.discover_max_entries, run_dir_re=run_re,
                   ai_root=st.ai_root, inbox_dir=st.inbox_dir)
    problems: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    out_dir = study_output_dir(root, st.ai_root, st.inbox_dir)
    if out_dir:
        problems.append({"code": "STUDY_OUTPUT_DIR",
                         "message": f"플랫폼 산출 폴더({out_dir}) 안은 찾지 않습니다 — 원본 프로젝트 폴더를 지정하세요"})
    elif sc.skipped_outputs:
        notes.append({"code": "STUDY_OUTPUT_SKIPPED",
                      "message": f"플랫폼 산출 폴더(04_params 등) {sc.skipped_outputs}개는 건너뛰었습니다"})
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
    if not assem:  # phase3 §14.4: 조립 폴더 0개 = 메시 단독(mesh_only) 템플릿 — 문제가 아니라 안내
        msg = MESH_ONLY_NOTE
        if multi:
            msg += f" (starter({pr.starter_glob})가 여러 개인 폴더는 후보가 아닙니다: " + ", ".join(multi[:5]) + ")"
        notes.append({"code": "MESH_ONLY", "message": msg})
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
        exp = tpl_export_name(sel.text, ps.tpl_export_regex)
        if exp is not None and exp.casefold() != pr.simlab_mesh_name.casefold():
            notes.append({"code": "SIMLAB_EXPORT_NAME",
                          "message": f"tpl의 내보내기 파일({exp})이 설정 predict.simlab_mesh_name({pr.simlab_mesh_name})과 "
                                     "다릅니다 — 형상 갱신 성공 판정이 실패할 수 있습니다"})
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
    """(tpl, CAD, 조립 폴더|None, problems). 조립 폴더 None + problems 없음 = mesh_only(후보 0개 또는 명시적 null)."""
    probs: list[dict[str, Any]] = []
    tpl = d.selected_tpl
    cad = _pick(d.cad, choice.get("cad"))
    rels = [a["rel"] for a in d.assem]
    # phase3 §14.4: radioss_assem을 명시적 null로 주면 메시 단독(mesh_only) — 후보가 있어도 쓰지 않는다
    mesh_only = "radioss_assem" in choice and choice["radioss_assem"] is None
    arel = None if mesh_only else _pick(rels, choice.get("radioss_assem"))
    assem = next((a for a in d.assem if a["rel"] == arel), None)
    for key, val, cands in (("tpl", tpl, d.tpls), ("cad", cad, d.cad), ("radioss_assem", assem, d.assem)):
        given = choice.get(key)
        if key == "tpl" and given is not None:
            continue  # 고른 tpl이 목록에 없으면 discover가 CHOICE_INVALID를 이미 넣었다
        if key == "radioss_assem" and mesh_only:
            continue
        if val is None and (cands or given is not None):
            probs.append({"code": "CHOICE_INVALID" if given is not None else "CHOICE_REQUIRED",
                          "message": f"{key} 후보 {len(cands)}개 중 하나를 고르세요" if given is None
                          else f"고른 {key}({given})가 찾은 목록에 없습니다"})
    return tpl, cad, assem, probs


_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_BOM = b"\xef\xbb\xbf"


def _recheck(root: str, root_real: str, rel: str) -> str:
    """복사 직전 재검사: 프로젝트 폴더부터 rel까지 각 요소가 링크·junction이 아니고 realpath가 프로젝트 폴더 안."""
    if is_link_or_reparse(root):
        raise PathError("PATH_UNSAFE", "프로젝트 폴더가 링크·junction으로 바뀌었습니다", path=root)
    cur = root
    for part in [] if rel == ROOT_REL else rel.split("/"):
        cur = os.path.join(cur, part)
        if is_link_or_reparse(cur):
            raise PathError("PATH_UNSAFE", f"복사할 원본이 링크·junction입니다: {rel}", path=cur)
    if not is_under(real(cur), root_real):
        raise PathError("PATH_UNSAFE", f"복사할 원본이 프로젝트 폴더 밖을 가리킵니다: {rel}", path=cur)
    return cur


def _changed(rel: str) -> DomainError:
    return DomainError("SOURCE_CHANGED", f"복사하는 동안 원본이 바뀌었습니다(링크 교체 등) — 다시 시도하세요: {rel}", status=409)


def open_source(root: str, root_real: str, rel: str) -> Any:
    """원본 파일을 검사 후 열어 바이너리 핸들을 돌려준다. 이후 복사는 이 핸들로만(경로를 다시 열지 않음).

    POSIX: O_NOFOLLOW(마지막 요소가 링크면 열기 실패). Windows(O_NOFOLLOW 없음): 연 핸들의 (st_dev, st_ino)가
    열기 전 lstat과 같아야 한다 — 그 사이 링크·junction으로 바뀌면 다른 파일이 열려 거부된다. 연 뒤 realpath도 다시 본다.
    """
    p = _recheck(root, root_real, rel)
    try:
        before = os.lstat(p)
    except OSError as exc:
        raise _changed(rel) from exc
    if not stat.S_ISREG(before.st_mode):
        raise PathError("PATH_UNSAFE", f"복사할 원본이 일반 파일이 아닙니다: {rel}", path=p)
    try:
        fd = os.open(p, os.O_RDONLY | _O_NOFOLLOW | _O_BINARY)
    except OSError as exc:  # ELOOP 등: 검사 뒤 링크로 바뀜
        raise _changed(rel) from exc
    try:
        st = os.fstat(fd)
        # Windows st_dev(볼륨 일련번호)는 조회 방식(lstat 빠른 경로·fstat)마다 폭이 달라 파일 ID(st_ino)만 비교
        same = st.st_ino == before.st_ino and (os.name == "nt" or st.st_dev == before.st_dev)
        if not stat.S_ISREG(st.st_mode) or not same:
            raise _changed(rel)
        _recheck(root, root_real, rel)
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, "rb")


def _copy_src(root: str, root_real: str, rel: str, dst: str) -> int:
    with open_source(root, root_real, rel) as fi:
        return copy_stream(fi, dst)


def rewrite_tpl_bytes(raw: bytes, prt_regex: str, cad_name: str) -> bytes:
    """원본 바이트 기준으로 첫 `dir_file_prt` 일치 줄만 `dir_file_prt = r"./<CAD>"`로 바꾼다. BOM·CRLF·나머지 바이트 유지."""
    bom = _BOM if raw.startswith(_BOM) else b""
    lines = raw[len(bom):].decode("utf-8").split("\n")  # '\r'은 줄 내용 끝에 남아 그대로 돌아간다
    rx = re.compile(prt_regex)
    for i, line in enumerate(lines):
        if rx.search(line):
            lines[i] = rx.sub(lambda _m: f'dir_file_prt = r"./{cad_name}"', line, count=1)
            break
    return bom + "\n".join(lines).encode("utf-8")


def assem_files(adir: str, renum_csv_name: str) -> list[str]:
    """조립 폴더에서 등록에 복사할 파일 이름(.rad·.inc·RENUM csv, eps_mesh·링크 제외). copy_sources·planned_bytes 공통."""
    renum = renum_csv_name.casefold()
    out: list[str] = []
    for n in sorted(os.listdir(adir)):
        low = n.casefold()
        if is_mesh_file(n) or not (low.endswith((".rad", ".inc")) or low == renum):
            continue
        p = os.path.join(adir, n)
        if is_link_or_reparse(p) or not os.path.isfile(p):
            continue
        out.append(n)
    return out


def copy_sources(d: Discovery, tpl: TplInfo, cad_rel: str, assem: dict[str, Any] | None, dst: str, settings: Any) -> int:
    """§15.4 폴더 구조로 dst에 모은다. 복사한 바이트 수. 읽기만(원본 위치). 원본마다 복사 직전 재검사·핸들 기준 복사.
    assem None = mesh_only(radioss_assem/ 없음)."""
    root = d.root
    root_real = real(root)
    pr, td = settings.predict, settings.train_data
    cad_name = cad_rel.split("/")[-1]
    total = 0
    # tpl: CAD 경로가 ./<CAD>가 아니면 원본 update_parameter_file(:135-139)처럼 ./<CAD 파일명>으로 바꿔 쓴다
    if tpl.cad_ref is not None and (not tpl.cad_ref.startswith("./") or _cad_name(tpl.cad_ref) != cad_name):
        with open_source(root, root_real, tpl.rel) as fi:
            raw = fi.read()
        try:
            data = rewrite_tpl_bytes(raw, td.tpl_prt_regex, cad_name)
        except UnicodeDecodeError as exc:
            raise _changed(tpl.rel) from exc
        total += copy_stream(io.BytesIO(data), os.path.join(dst, TPL_NAME))
    else:
        total += _copy_src(root, root_real, tpl.rel, os.path.join(dst, TPL_NAME))
    total += _copy_src(root, root_real, cad_rel, os.path.join(dst, "cad", cad_name))
    if d.parameters_source == "file" and d.parameters_file:
        total += _copy_src(root, root_real, d.parameters_file,
                           os.path.join(dst, d.parameters_file.split("/")[-1].lower()))
    else:
        write_json(os.path.join(dst, "parameters.json"),
                   {"schema_version": 1, "unit_system": "mm-ton-s", "parameters": d.parameters})
    for rel, name in ((d.samples, "samples.csv"), (d.responses, "responses.json")):
        if rel:
            total += _copy_src(root, root_real, rel, os.path.join(dst, name))
    if assem is None:
        return total
    arel = assem["rel"]
    adir = _recheck(root, root_real, arel)  # 조립 폴더 자체도 listdir 직전에 다시 본다
    for n in assem_files(adir, pr.renum_csv_name):
        total += _copy_src(root, root_real, _rel(arel, n), os.path.join(dst, "radioss_assem", n))
    return total


def planned_bytes(d: Discovery, tpl: TplInfo, cad_rel: str, assem: dict[str, Any] | None, settings: Any) -> int:
    """복사 전 총량 추정(상한 검사용). 조립 폴더 파일 판정은 copy_sources와 같은 assem_files. assem None = mesh_only."""
    root = d.root
    files = [_abs(root, tpl.rel), _abs(root, cad_rel)]
    files += [_abs(root, r) for r in (d.parameters_file, d.samples, d.responses) if r]
    if assem is not None:
        adir = _abs(root, assem["rel"])
        files += [os.path.join(adir, n) for n in assem_files(adir, settings.predict.renum_csv_name)]
    total = 0
    for f in files:
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    return total
