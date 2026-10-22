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
from ..geometry.asm_match import is_matched
from ..geometry.shell_native import features_kind_problems
from .prepared_input import is_mesh_file

PARTS_NAME = "parts"
FEATURES_REL = "native/extract/parameter_features.json"
TAG_REL = "native/tag/tag.json"
PREP_REL = "native/prep.json"
PROPS_REL = "native/props/props.json"
SHELL_FEATURES_REL = "native/extract/shell_features.json"
SHELL_SCAN_REL = "native/fixed/shell_scan.json"
SHELL_TAG_REL = "native/tag/shell_tag.json"


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


def _json(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def extra_known_names(folder: str) -> set[str]:
    """형상 피처 밖에서 오는 파라미터 이름: 쉘 두께(native/props/props.json, §11.1)·다중 baseline 공통 이름(param_map.json, §4.10)."""
    names = {str(r["parameter"]) for r in _json(os.path.join(folder, *PROPS_REL.split("/"))).get("props", [])
             if isinstance(r, dict) and isinstance(r.get("parameter"), str)}
    pm = _json(os.path.join(folder, "param_map.json"))
    for r in pm.get("common") or []:
        if not isinstance(r, dict):
            continue
        for blk in (r.get("proposed"), r.get("decision")):
            if isinstance(blk, dict):
                if isinstance(blk.get("name"), str):
                    names.add(blk["name"])
                names |= {str(x["name"]) for x in blk.get("parts") or [] if isinstance(x, dict) and isinstance(x.get("name"), str)}
    return names


def validate_native_folder(folder: str, *, max_total_bytes: int, starter_glob: str, renum_csv_name: str, baseline_inc_name: str,
                           step_extensions: list[str], shell_only: bool = False, kind: str = "solid") -> ParamSetFolder:
    """shell_only: 쉘 두께 전용 세트(§11.1) — cad·extract·tag 대신 native/props/props.json 필수.
    kind=shell: 쉘 판금 비드 세트(shell-morph.md §8.2) — RENUM csv·기준 메시 검사 없음, native/{extract/shell_features.json,
    fixed/shell_scan.json, tag/shell_tag.json} 필수, 솔리드·쉘 피처 혼합 금지."""
    shell_kind = kind == "shell"
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
    _load_parameters(f, folder, require_nominal_inside=False)  # native-vars.md NV-10: 공칭이 범위 밖인 정의 허용(Altair 검증은 기본값 True)
    exts = tuple(e.lower() for e in step_extensions)
    cad = os.path.join(folder, "cad")
    if shell_only:
        f.cad_file = ""
    elif not os.path.isdir(cad):
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
        matched = not shell_only and not shell_kind and is_matched(folder)  # 조립 매칭 세트(asm-match.md §6.4): 번호 표·기준 메시 파일을 요구하지 않는다
        if f.renum_csv is None and not shell_only and not shell_kind and not matched:
            _p(f, "RENUM_CSV_MISSING", f"radioss_assem에 번호 재지정 표({renum_csv_name})가 필요합니다", "radioss_assem")
        if not shell_kind and not matched and not any(x.lower() == baseline_inc_name.lower() for x in files):
            _p(f, "BASELINE_INC_MISSING", f"radioss_assem에 기준 메시({baseline_inc_name})가 필요합니다", "radioss_assem")
        starters = [x for x in files if fnmatch.fnmatch(x, starter_glob)]
        if len(starters) != 1:
            _p(f, "STARTER_COUNT", f"radioss_assem에 starter({starter_glob})가 정확히 1개 있어야 합니다(현재 {len(starters)}개)", "radioss_assem")
        else:
            f.starter_name = starters[0]
    f.input_kind = "assembly"
    need = (PREP_REL, PROPS_REL) if shell_only else (PREP_REL, SHELL_FEATURES_REL, SHELL_SCAN_REL, SHELL_TAG_REL) if shell_kind \
        else (PREP_REL, FEATURES_REL, TAG_REL)
    missing = [rel for rel in need if not os.path.isfile(os.path.join(folder, *rel.split("/")))]
    for q in features_kind_problems(folder):
        _p(f, q["code"], q["message"], "native/extract")
    feats_rel = SHELL_FEATURES_REL if shell_kind else FEATURES_REL
    for rel in missing:
        _p(f, "NATIVE_PREP_MISSING", f"형상 준비 파일({rel})이 없습니다 — 형상 준비를 다시 하세요", rel)
    if shell_only and PROPS_REL not in missing and f.parameters:
        if not {p["name"] for p in f.parameters} <= extra_known_names(folder):
            _p(f, "PARAM_FEATURE_MISMATCH", "파라미터 이름이 쉘 두께 PROP 목록에 없습니다", "parameters.json")
    elif feats_rel not in missing and f.parameters:
        try:
            with open(os.path.join(folder, *feats_rel.split("/")), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            _p(f, "NATIVE_PREP_MISSING", f"{feats_rel}을 읽을 수 없습니다", feats_rel)
        else:
            known = set(representative_names(doc if isinstance(doc, dict) else {})) | extra_known_names(folder)
            if not {p["name"] for p in f.parameters} <= known:  # 등록 세트는 전부, ①→④ 세트는 DOE에서 쓴 부분집합
                _p(f, "PARAM_FEATURE_MISMATCH", "파라미터 이름이 형상 피처(그룹 대표)에 없습니다", "parameters.json")
    return f
