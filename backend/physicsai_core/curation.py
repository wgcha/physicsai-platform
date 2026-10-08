"""② 데이터 정리 공용(phase2 §4.4, §6.7~§6.10).

원본 규칙 재구현:
- run 폴더 이름: 2_DATA_CURATION/GUI/1_gui_curate_h3d.py:471-495 (T01: 2_gui_curate_t0.py:399-422)
- to_cfg_datacomp: 1_gui_curate_h3d.py:711-734
- hvtrans cfg: 1_gui_curate_h3d.py:736-842 (__create_hvtrans_config)
- INPUT_CURATE_CURVE.json: 2_gui_curate_t0.py:459-532 (__create_input_json)
"""

from __future__ import annotations

import os
from typing import Any

from .errors import DomainError
from .paths import BACKUP_DIR, is_link_or_reparse


# ---------------------------------------------------------------------------
# 원천(source)
# ---------------------------------------------------------------------------


def source_root_rel(source: dict[str, Any]) -> str | None:
    """TRAIN_DOE·SPDM_IMPORT의 Study 기준 루트. FOLDER는 None(절대경로)."""
    k = source.get("kind")
    if k == "TRAIN_DOE":
        return f"01_train/results/{source['doe_id']}"
    if k == "SPDM_IMPORT":
        return f"02_import/{source['import_id']}"
    return None


def is_t01(name: str) -> bool:
    return name.endswith("T01")  # 원본 2_gui_curate_t0.py:344-375 fname.endswith("T01")


def is_h3d(name: str) -> bool:
    return name.lower().endswith(".h3d")


def collect_files(root: str, kind: str, max_files: int | None = None) -> list[str]:
    """루트 아래 재귀 수집(정렬·링크 거부·_backup 제외). kind = H3D | T01."""
    match = is_h3d if kind == "H3D" else is_t01
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != BACKUP_DIR and not is_link_or_reparse(os.path.join(dirpath, d)))
        for f in filenames:
            p = os.path.join(dirpath, f)
            if match(f) and not is_link_or_reparse(p) and os.path.isfile(p):
                out.append(os.path.normpath(p))
                if max_files is not None and len(out) > max_files:
                    raise DomainError("INPUT_INVALID", f"대상 파일이 상한({max_files}개)을 넘습니다", status=422)
    return sorted(out)


def run_folder_names(source_folder: str, paths: list[str]) -> list[str]:
    """파일 바로 위 폴더부터 위로 올라가며 그 레벨 이름만으로 서로 구분되는 첫 레벨의 폴더 이름. 없으면 파일 stem."""
    dirs_list = []
    for p in paths:
        rel_dir = os.path.relpath(os.path.dirname(p), source_folder).replace("\\", "/")
        parts = rel_dir.split("/") if rel_dir != "." else []
        dirs_list.append(parts)
    max_depth = max((len(parts) for parts in dirs_list), default=0)
    for level_from_end in range(1, max_depth + 1):
        candidates = []
        ok = True
        for parts in dirs_list:
            if level_from_end > len(parts):
                ok = False
                break
            candidates.append(parts[-level_from_end])
        if ok and len(set(candidates)) == len(candidates):
            return candidates
    return [os.path.splitext(os.path.basename(p))[0] for p in paths]


def run_key_of(source_root: str, path: str, run_keys: set[str]) -> str | None:
    """TRAIN_DOE 원천: 결과 루트 바로 아래 폴더 이름이 run_key."""
    rel = os.path.relpath(path, source_root).replace("\\", "/").split("/")
    return rel[0] if len(rel) > 1 and rel[0] in run_keys else None


# ---------------------------------------------------------------------------
# 미리보기 JSON
# ---------------------------------------------------------------------------


def to_cfg_datacomp(raw_comp: str | None) -> str | None:
    comp = (raw_comp or "").strip()
    if not comp:
        return None
    words = comp.split()
    if len(words) >= 3:
        return None
    if words[0].startswith("Extreme"):
        return None
    return words[0]


def validate_h3d_preview(data: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """PREVIEW_H3D.json 검증(원본 GUI:362-407 키) → (요약 + usable, 문제)."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return None, ["최상위가 객체가 아닙니다"]
    dti = data.get("datatype_info")
    if not isinstance(dti, dict) or not all(isinstance(k, str) and isinstance(v, list) for k, v in dti.items()):
        problems.append("datatype_info: {DataType: [component…]} 형식이 아닙니다")
        dti = {}
    parts = {}
    for k in ("shell", "solid", "rbody"):
        v = data.get(f"lst_cid_{k}", [])
        if not isinstance(v, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
            problems.append(f"lst_cid_{k}: 정수 배열이 아닙니다")
            v = []
        parts[k] = v
    nts = data.get("num_time_step")
    if not isinstance(nts, int) or isinstance(nts, bool) or nts < 0:
        problems.append("num_time_step: 정수가 아닙니다")
        nts = 0
    datatypes = []
    for name, comps in dti.items():
        comps_s = [str(c) for c in comps]
        usable: list[str] = []
        for c in comps_s:
            u = to_cfg_datacomp(c)
            if u and u not in usable:
                usable.append(u)
        datatypes.append({"name": name, "components": comps_s, "usable": usable})
    return {"datatypes": datatypes, "parts": parts, "num_time_step": nts}, problems


def validate_t01_preview(data: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """PREVIEW_T01.json 검증(원본 GUI:259-289): dataTypes:[{name, requests:[{name, components:[…]}]}]."""
    if not isinstance(data, dict) or not isinstance(data.get("dataTypes"), list):
        return None, ["dataTypes 배열이 없습니다"]
    out = []
    for dt in data["dataTypes"]:
        if not isinstance(dt, dict) or not isinstance(dt.get("name"), str) or not isinstance(dt.get("requests", []), list):
            return None, ["dataTypes 항목 형식 오류"]
        reqs = []
        for r in dt.get("requests", []):
            if not isinstance(r, dict) or not isinstance(r.get("name"), str) or not isinstance(r.get("components", []), list):
                return None, ["requests 항목 형식 오류"]
            reqs.append({"name": r["name"], "components": [str(c) for c in r.get("components", [])]})
        out.append({"name": dt["name"], "requests": reqs})
    return {"dataTypes": out}, []


# ---------------------------------------------------------------------------
# hvtrans cfg(②-2)
# ---------------------------------------------------------------------------


def validate_selection(selection: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, str]]:
    """selection을 미리보기 요약(preview_summary.json)과 대조(phase2 §6.8)."""
    probs: list[dict[str, str]] = []
    usable = {d["name"]: d["usable"] for d in summary.get("datatypes", [])}
    items = selection.get("items") or []
    if not items:
        probs.append({"field": "items", "message": "DataType·Component 항목이 1개 이상 필요합니다"})
    seen = set()
    for it in items:
        dt, comp = it.get("datatype"), it.get("component")
        if dt not in usable:
            probs.append({"field": "items", "message": f"미리보기에 없는 DataType: {dt}"})
            continue
        if dt != "Displacement" and comp not in usable[dt]:
            probs.append({"field": "items", "message": f"사용할 수 없는 Component: {dt}|{comp}"})
        if (dt, comp) in seen:
            probs.append({"field": "items", "message": f"중복: {dt}|{comp}"})
        seen.add((dt, comp))
    parts = selection.get("parts") or {}
    for k in ("shell", "solid", "rbody"):
        allowed = set(summary.get("parts", {}).get(k, []))
        for cid in parts.get(k, []) or []:
            if cid not in allowed:
                probs.append({"field": f"parts.{k}", "message": f"미리보기에 없는 Part id: {cid}"})
    if int(summary.get("num_time_step") or 0) < 1:
        probs.append({"field": "time_increment", "message": "미리보기의 Time Step 수가 0입니다"})
    return probs


def time_steps(num_time_step: int, increment: int) -> list[int]:
    inc = max(1, int(increment or 1))
    if num_time_step <= 0:
        return []
    return list(range(1, num_time_step + 1, inc))


def hvtrans_cfg(selection: dict[str, Any], datatype_info: dict[str, list[str]], num_time_step: int) -> str:
    """원본 __create_hvtrans_config 그대로. datatype_info = 미리보기 원문 {DataType: [raw comp…]}."""
    steps = time_steps(num_time_step, selection.get("time_increment", 1))
    request_lines: list[str] = []
    datatype_order: list[str] = []
    selected: dict[str, set[str]] = {}
    for it in selection.get("items") or []:
        dt, comp = it["datatype"], it["component"]
        if dt == "Displacement":
            continue
        request_lines.append(f"{dt}|{comp}")
        if dt not in datatype_order:
            datatype_order.append(dt)
            selected[dt] = set()
        selected[dt].add(comp)
    request_lines.append("Displacement")
    parts = selection.get("parts") or {}
    lines = ["BeginParts"]
    for key, pool in (("shell", "Shell"), ("solid", "Solid"), ("rbody", "Rbody")):
        ids = parts.get(key) or []
        if ids:
            lines.append(f"    BeginPool:{pool}")
            for cid in ids:
                lines.append(f"        {cid}")
            lines.append("    EndPool")
    lines.append("EndParts")
    lines.append("BeginSubcase:1")
    for step in steps:
        lines.append(f"    BeginSimulation:{step}")
        for req in request_lines:
            lines.append(f"        {req}")
        lines.append("    EndSimulation")
    lines.append("EndSubcase")
    groups = []
    for dt in datatype_order:
        usable = {u for u in (to_cfg_datacomp(r) for r in datatype_info.get(dt, [])) if u}
        total = len(usable)
        flag = 1 if (total > 0 and len(selected.get(dt, set())) == total) else 0
        groups.append(f"{{1 0 1 {flag}}}")
    groups.append("{1 0 1 1}")
    lines.append("ExtendedInfo: " + " ".join(groups))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# T01 곡선(②-4)
# ---------------------------------------------------------------------------


def curve_base_name(t01_name: str) -> str:
    return t01_name[:-3] if t01_name.endswith("T01") else t01_name


def curve_input_json(curves: list[dict[str, str]], targets: list[tuple[str, str]], out_root: str) -> dict[str, Any]:
    """targets = [(t01 절대경로, run_folder)]. 경로는 '/' 구분(원본 replace)."""
    jobs = []
    for t01, run_folder in targets:
        out = os.path.join(out_root, run_folder, curve_base_name(os.path.basename(t01)) + "_curves.json")
        jobs.append({"inputFile": t01.replace("\\", "/"), "outputFile": out.replace("\\", "/")})
    return {
        "curves": [{"yDataType": c["type"], "yRequest": c["request"], "yComponent": c["component"]} for c in curves],
        "jobs": jobs,
    }
