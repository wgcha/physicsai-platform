"""④ native 파라미터 세트 자동 구성(geometry-engine.md §7.4): 프로젝트 폴더에서 STEP·조립 폴더 후보를 찾는다(읽기만).

tpl은 찾지 않는다. CAD 후보 = `geometry.step_extensions` 파일(단일) 또는 이름이 `parts`이고 STEP ≥1인 폴더(component별).
조립 폴더 후보 = 기존 규칙(starter 1개) + 기준본 `{predict.mesh_include_name}` 존재 필수(없으면 후보 아님 — problems BASELINE_INC_MISSING).
RENUM csv가 없으면 problems RENUM_CSV_MISSING. `parameter_features.json`·`parameter_extracted.xml`이 같은 폴더에 둘 다 있으면 notes.
복사 규칙(원본 재검사·핸들 기준 복사)은 altair 자동 구성(param_discover)과 같은 함수를 쓴다.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .param_discover import (
    ROOT_REL,
    Discovery,
    _abs,
    _copy_src,
    _pick,
    _recheck,
    _rel,
    assem_files,
    find_assems,
    scan_tree,
    study_output_dir,
)
from ..paths import real

FEATURES_NAME = "parameter_features.json"
EXTRACTED_NAME = "parameter_extracted.xml"
PARTS_DIR = "parts"


def _is_step(name: str, exts: tuple[str, ...]) -> bool:
    return name.casefold().endswith(exts)


def discover_native(root: str, settings: Any) -> Discovery:
    ps, pr, td, geo = settings.param_set, settings.predict, settings.train_data, settings.geometry
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
    if sc.truncated:
        notes.append({"code": "SCAN_TRUNCATED",
                      "message": f"항목이 많아 {ps.discover_max_entries}개까지만 찾았습니다 — 더 아래 폴더를 지정하세요"})
    exts = tuple(e.casefold() for e in geo.step_extensions)
    cad: list[str] = []
    companions: list[str] = []
    for d, files in sc.dirs.items():
        base = (d if d != ROOT_REL else "").split("/")[-1].casefold()
        steps = [n for n in files if _is_step(n, exts)]
        if base == PARTS_DIR:
            if steps:
                cad.append(d)
            continue
        cad.extend(_rel(d, n) for n in steps)
        low = {n.casefold() for n in files}
        if FEATURES_NAME.casefold() in low and EXTRACTED_NAME.casefold() in low:
            companions.append(d)
    cad.sort(key=lambda r: (len(r.split("/")), r.casefold()))
    if not cad:
        problems.append({"code": "CAD_NOT_FOUND",
                         "message": f"STEP 파일({' '.join(geo.step_extensions)}) 또는 STEP이 든 parts 폴더를 찾지 못했습니다"})
    assem_all, multi = find_assems(sc, pr.starter_glob, pr.renum_csv_name)
    inc = pr.mesh_include_name.casefold()
    assem = []
    for a in assem_all:
        if any(n.casefold() == inc for n in sc.dirs.get(a["rel"], [])):
            assem.append({**a, "has_baseline_inc": True})
    if assem_all and not assem:
        problems.append({"code": "BASELINE_INC_MISSING",
                         "message": f"조립 폴더 후보에 기준 메시({pr.mesh_include_name})가 없습니다 — native 형상 엔진은 기준 메시가 필요합니다"})
    elif not assem_all:
        problems.append({"code": "ASSEM_NOT_FOUND",
                         "message": f"starter({pr.starter_glob})가 1개 있는 조립 폴더를 찾지 못했습니다"
                                    + (f" (여러 개인 폴더: {', '.join(multi[:5])})" if multi else "")})
    if assem and not any(a["has_renum_csv"] for a in assem):
        problems.append({"code": "RENUM_CSV_MISSING",
                         "message": f"조립 폴더에 번호 재지정 표({pr.renum_csv_name})가 없습니다 — native 형상 엔진은 필수입니다"})
    if companions:
        notes.append({"code": "FEATURES_FOUND",
                      "message": f"{PARAM_NOTE}: " + ", ".join(c if c != ROOT_REL else "(프로젝트 폴더)" for c in companions[:5])})
    pfile = None
    for d in [ROOT_REL] + [c for c in companions if c != ROOT_REL]:
        if any(n.casefold() == "parameters.json" for n in sc.dirs.get(d, [])):
            pfile = _rel(d, next(n for n in sc.dirs[d] if n.casefold() == "parameters.json"))
            break
    return Discovery(root=root, tpls=[], selected_tpl=None, cad=cad, assem=assem, parameters_source=None, parameters_file=pfile,
                     parameters=[], samples=None, responses=None, problems=problems, notes=notes, truncated=sc.truncated,
                     scanned=sc.entries)


PARAM_NOTE = "이미 추출한 형상 피처 파일(parameter_features.json·parameter_extracted.xml)이 있어 형상 추출을 건너뜁니다"


def resolve_choice_native(d: Discovery, choice: dict[str, str | None]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """(CAD 상대경로, 조립 폴더, problems). CAD는 후보 1개면 자동, 아니면 고름. 조립 폴더도 같다."""
    probs: list[dict[str, Any]] = []
    cad = _pick(d.cad, choice.get("cad"))
    arel = _pick([a["rel"] for a in d.assem], choice.get("radioss_assem"))
    assem = next((a for a in d.assem if a["rel"] == arel), None)
    for key, val, cands in (("cad", cad, d.cad), ("radioss_assem", assem, d.assem)):
        given = choice.get(key)
        if val is None and (cands or given is not None):
            probs.append({"code": "CHOICE_INVALID" if given is not None else "CHOICE_REQUIRED",
                          "message": f"{key} 후보 {len(cands)}개 중 하나를 고르세요" if given is None
                          else f"고른 {key}({given})가 찾은 목록에 없습니다"})
    if assem is not None and not assem["has_renum_csv"]:
        probs.append({"code": "RENUM_CSV_MISSING", "message": "고른 조립 폴더에 번호 재지정 표가 없습니다"})
    return cad, assem, probs


def cad_files(root: str, cad_rel: str, settings: Any) -> list[tuple[str, str]]:
    """(원본 상대경로, 세트 안 상대경로 `cad/…`) 목록 — 단일 STEP 또는 parts 폴더의 STEP + (같은 폴더의) body_map.json."""
    exts = tuple(e.casefold() for e in settings.geometry.step_extensions)
    is_parts = cad_rel.split("/")[-1].casefold() == PARTS_DIR
    adir = _abs(root, cad_rel) if is_parts else os.path.dirname(_abs(root, cad_rel))
    if is_parts:
        names = [n for n in sorted(os.listdir(adir)) if _is_step(n, exts) and os.path.isfile(os.path.join(adir, n))]
        out = [(_rel(cad_rel, n), f"cad/{PARTS_DIR}/{n}") for n in names]
        parent = os.path.dirname(cad_rel) or ROOT_REL
    else:
        out = [(cad_rel, "cad/" + cad_rel.split("/")[-1])]
        parent = os.path.dirname(cad_rel) or ROOT_REL
    pdir = _abs(root, parent)
    if os.path.isfile(os.path.join(pdir, "body_map.json")):
        out.append((_rel(parent, "body_map.json"), "cad/body_map.json"))
    return out


def companion_files(root: str, cad_rel: str) -> list[tuple[str, str]]:
    """CAD와 같은 폴더(parts는 그 부모)에 features·xml이 둘 다 있으면 `native/extract/`로 복사할 (원본 상대경로, 세트 안 경로)."""
    parent = os.path.dirname(cad_rel) or ROOT_REL
    pdir = _abs(root, parent)
    if os.path.isfile(os.path.join(pdir, FEATURES_NAME)) and os.path.isfile(os.path.join(pdir, EXTRACTED_NAME)):
        return [(_rel(parent, n), f"native/extract/{n}") for n in (FEATURES_NAME, EXTRACTED_NAME)]
    return []


def copy_sources_native(d: Discovery, cad_rel: str, assem: dict[str, Any], dst: str, settings: Any) -> int:
    """고른 후보를 세트 폴더 구조(cad/, radioss_assem/, native/extract/)로 dst에 모은다. 원본마다 복사 직전 재검사·핸들 복사."""
    root = d.root
    root_real = real(root)
    total = 0
    for src, rel in cad_files(root, cad_rel, settings) + companion_files(root, cad_rel):
        total += _copy_src(root, root_real, src, os.path.join(dst, *rel.split("/")))
    arel = assem["rel"]
    adir = _recheck(root, root_real, arel)
    for n in assem_files(adir, settings.predict.renum_csv_name):
        total += _copy_src(root, root_real, _rel(arel, n), os.path.join(dst, "radioss_assem", n))
    return total


def planned_bytes_native(d: Discovery, cad_rel: str, assem: dict[str, Any], settings: Any) -> int:
    root = d.root
    files = [_abs(root, s) for s, _r in cad_files(root, cad_rel, settings) + companion_files(root, cad_rel)]
    adir = _abs(root, assem["rel"])
    files += [os.path.join(adir, n) for n in assem_files(adir, settings.predict.renum_csv_name)]
    total = 0
    for f in files:
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    return total
