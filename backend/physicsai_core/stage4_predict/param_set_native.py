"""④ native 파라미터 세트 폴더 검증(geometry-engine.md §7.4 `validate_folder(..., engine="native")`).

세트 폴더 S: parameters.json · cad/(단일 STEP 또는 parts/ + body_map.json) · radioss_assem/(starter 1 + 기준본 + RENUM csv) ·
native/{prep.json, extract/parameter_features.json, tag/tag.json}. tpl·샘플·응답 정의는 없다(응답은 나중에 PUT).
"""

from __future__ import annotations

import fnmatch
import json
import os
from typing import Any

from ..paths import file_name_problem_message, is_link_or_reparse, name_unsafe_chars
from .param_set_files import ParamSetFolder, _load_parameters, _p
from .prepared_input import is_mesh_file

PARTS_NAME = "parts"
FEATURES_REL = "native/extract/parameter_features.json"
TAG_REL = "native/tag/tag.json"
PREP_REL = "native/prep.json"


def representative_names(features_doc: dict[str, Any]) -> list[str]:
    """파라미터 표 이름 = 그룹 대표 + 그룹 없는 피처(extract가 낸 xml 순서, §4.3)."""
    members: set[str] = set()
    reps: set[str] = set()
    for g in features_doc.get("groups", []):
        if isinstance(g, dict) and isinstance(g.get("parameter"), str):
            reps.add(g["parameter"])
            members |= {m for m in g.get("members", []) if isinstance(m, str)}
    return [f["name"] for f in features_doc.get("features", [])
            if isinstance(f, dict) and isinstance(f.get("name"), str) and (f["name"] in reps or f["name"] not in members)]


def validate_native_folder(folder: str, *, max_total_bytes: int, starter_glob: str, renum_csv_name: str, baseline_inc_name: str,
                           step_extensions: list[str]) -> ParamSetFolder:
    f = ParamSetFolder()
    total = 0
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        for d in list(dirnames):
            if is_link_or_reparse(os.path.join(dirpath, d)):
                _p(f, "PATH_UNSAFE", "링크 폴더는 쓸 수 없습니다", os.path.relpath(os.path.join(dirpath, d), folder))
                dirnames.remove(d)
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            if is_link_or_reparse(fp):
                _p(f, "PATH_UNSAFE", "링크 파일은 쓸 수 없습니다", os.path.relpath(fp, folder))
                continue
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    f.total_bytes = total
    if total > max_total_bytes:
        _p(f, "PARAM_SET_TOO_LARGE", f"폴더 총량이 상한({max_total_bytes} bytes)을 넘습니다")
    _load_parameters(f, folder)
    exts = tuple(e.lower() for e in step_extensions)
    cad = os.path.join(folder, "cad")
    if not os.path.isdir(cad):
        _p(f, "CAD_MISSING", "cad 폴더가 필요합니다", "cad")
    else:
        steps = sorted(x for x in os.listdir(cad) if os.path.isfile(os.path.join(cad, x)) and x.lower().endswith(exts))
        parts = os.path.join(cad, PARTS_NAME)
        pfiles = sorted(x for x in os.listdir(parts) if x.lower().endswith(exts)) if os.path.isdir(parts) else []
        if steps and pfiles:
            _p(f, "CAD_COUNT", "cad에는 STEP 파일(단일) 또는 parts 폴더 중 하나만 둘 수 있습니다", "cad")
        elif len(steps) == 1:
            f.cad_file = steps[0]
            why = name_unsafe_chars(steps[0])
            if why:
                _p(f, "PATH_UNSAFE", f"CAD {file_name_problem_message(why)}", "cad/" + steps[0])
        elif pfiles:
            f.cad_file = PARTS_NAME + "/"
        else:
            _p(f, "CAD_COUNT", f"cad 폴더에는 STEP 파일이 정확히 1개(또는 parts 폴더에 component별 STEP)여야 합니다(현재 {len(steps)}개)", "cad")
    assem = os.path.join(folder, "radioss_assem")
    if not os.path.isdir(assem):
        _p(f, "ASSEM_MISSING", "radioss_assem 폴더가 필요합니다", "radioss_assem")
    else:
        names = sorted(os.listdir(assem))
        files = [x for x in names if os.path.isfile(os.path.join(assem, x)) and x.lower().endswith((".rad", ".inc"))
                 and not is_mesh_file(x)]
        f.assem_files = files
        for x in files:
            why = name_unsafe_chars(x)
            if why:
                _p(f, "PATH_UNSAFE", file_name_problem_message(why), "radioss_assem/" + x)
        f.renum_csv = next((x for x in names if x.lower() == renum_csv_name.lower() and os.path.isfile(os.path.join(assem, x))), None)
        if f.renum_csv is None:
            _p(f, "RENUM_CSV_MISSING", f"radioss_assem에 번호 재지정 표({renum_csv_name})가 필요합니다", "radioss_assem")
        if not any(x.lower() == baseline_inc_name.lower() for x in files):
            _p(f, "BASELINE_INC_MISSING", f"radioss_assem에 기준 메시({baseline_inc_name})가 필요합니다", "radioss_assem")
        starters = [x for x in files if fnmatch.fnmatch(x, starter_glob)]
        if len(starters) != 1:
            _p(f, "STARTER_COUNT", f"radioss_assem에 starter({starter_glob})가 정확히 1개 있어야 합니다(현재 {len(starters)}개)", "radioss_assem")
        else:
            f.starter_name = starters[0]
    f.input_kind = "assembly"
    missing = [rel for rel in (PREP_REL, FEATURES_REL, TAG_REL) if not os.path.isfile(os.path.join(folder, *rel.split("/")))]
    for rel in missing:
        _p(f, "NATIVE_PREP_MISSING", f"형상 준비 파일({rel})이 없습니다 — 형상 준비를 다시 하세요", rel)
    if FEATURES_REL not in missing and f.parameters:
        try:
            with open(os.path.join(folder, *FEATURES_REL.split("/")), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            _p(f, "NATIVE_PREP_MISSING", f"{FEATURES_REL}을 읽을 수 없습니다", FEATURES_REL)
        else:
            if {p["name"] for p in f.parameters} != set(representative_names(doc if isinstance(doc, dict) else {})):
                _p(f, "PARAM_FEATURE_MISMATCH", "파라미터 이름 집합이 형상 피처(그룹 대표)의 이름 집합과 다릅니다", "parameters.json")
    return f
