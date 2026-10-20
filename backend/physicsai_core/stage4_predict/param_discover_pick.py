"""④ 파라미터 세트 자동 구성 결과(Discovery)·자동 구성(discover) — param_discover에서 재노출."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from ..naming import NAME_RE
from .param_discover_scan import (
    MESH_ONLY_NOTE,
    ROOT_REL,
    TplInfo,
    _abs,
    _cad_name,
    _first_in,
    find_assems,
    find_cads,
    find_tpls,
    scan_tree,
    study_output_dir,
)
from .param_set_files import ParamSetFolder, _load_parameters
from .param_sets import tpl_export_name


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
