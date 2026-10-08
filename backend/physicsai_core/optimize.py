"""⑤ 최적화(phase2 §6.12): RESPONSES 검증, INPUT_HST_RUN.json 작성, 결과 요약 파서.

원본 인용: 4_OPTIMIZATION/GUI/1_gui_physicsai_opti.py:709-735, 742-792(RESPONSES), 859-889(run_cfg),
4_OPTIMIZATION/FUNC/1_physicsai_opti.py:360-368(HYPERVIEW_TCL 작업 폴더 복사본).
"""

from __future__ import annotations

import csv
import fnmatch
import json
import math
import os
import re
from typing import Any

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# Altair 결과 이름 필드(DataType·Component·Layer·Request) 허용 문자(변경 메모 C16): 영숫자(유니코드 포함)·공백·_ - . / ( ) : +
# 줄바꿈·제어문자·" $ [ ] { } ; | 등은 TCL·cfg·JSON 해석기로 넘어가므로 거부한다.
FIELD_RE = re.compile(r"[\w \-./():+]*")
FIELD_PATTERN = r"^[\w \-./():+]{1,200}$"
STUDY_FOLDER_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
STATS = ("MAX", "MIN", "ABSMAX")
GOALS = ("NONE", "MINIMIZE", "MAXIMIZE", "CONSTRAINT")
BOUNDS = ("<=", ">=", "==")
METHODS = ("ARSM", "GRSM", "SQP")
APPROACHES = ("OPT", "DOE")

# 원본 RUN_CONFIG 키(GUI:859-889 + FUNC:364-368) — 시험 V2-OP-2가 정확히 비교한다
RUN_CONFIG_KEYS = (
    "ALTAIR_HOME", "DIR_WORK", "STUDY_FOLDER", "CAD_PARAM", "TPL_FILE", "HYPERMESH_TCL", "RADIOSS_ASSEM_DIR",
    "PHYSICSAI_INPUT_FILE", "PHYSICSAI_MODEL", "PREDICTED_H3D", "PREDICTED_XYDATA", "HYPERVIEW_TCL", "ALTAIR_PATHS",
    "PHYSICSAI_OVERRIDE_ENV", "RUN_NOMINAL", "APPROACH", "OPT_METHOD", "MAX_DESIGNS", "OPT_SETTINGS", "ON_FAILED",
    "RESPONSES",
)


def validate_responses(rows: Any, approach: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """검증 + 정규화(비제약 행 bound·value 제거). (정규화 행, problems)."""
    problems: list[dict[str, str]] = []
    out: list[dict[str, Any]] = []
    if not isinstance(rows, list) or not rows:
        return [], [{"row": "", "message": "응답 행이 1개 이상 필요합니다"}]
    seen: set[str] = set()
    n_obj = 0

    def p(i: int, msg: str) -> None:
        problems.append({"row": str(i), "message": msg})

    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            p(i, "행 형식 오류")
            continue
        name = r.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > 64:
            p(i, "name은 영문으로 시작하고 영문/숫자/_ 만(최대 64자)")
        elif name.upper() in seen:
            p(i, f"이미 있는 name입니다: {name}")
        else:
            seen.add(name.upper())
        source = r.get("source")
        row: dict[str, Any] = {"name": name, "source": source}
        str_fields: list[str] = []
        if source == "H3D":
            sc = r.get("subcase")
            if not isinstance(sc, int) or isinstance(sc, bool) or sc < 1:
                p(i, "subcase는 1 이상 정수")
            row.update(subcase=sc, datatype=r.get("datatype"), component=r.get("component"), layer=r.get("layer", ""))
            str_fields = ["datatype", "component", "layer"]
            for k in ("datatype", "component"):
                if not isinstance(row[k], str) or not row[k]:
                    p(i, f"{k}가 필요합니다")
            if not isinstance(row["layer"], str):
                p(i, "layer는 문자열")
        elif source == "XYDATA":
            row.update(request=r.get("request"), component=r.get("component"))
            str_fields = ["request", "component"]
            for k in str_fields:
                if not isinstance(row[k], str) or not row[k]:
                    p(i, f"{k}가 필요합니다")
        else:
            p(i, "source는 H3D | XYDATA")
        for k in str_fields:
            v = row.get(k)
            if isinstance(v, str) and "|" in v:
                p(i, "'|' 문자는 사용할 수 없습니다")
            elif isinstance(v, str) and (not FIELD_RE.fullmatch(v) or len(v) > 200):
                p(i, f"{k}에 허용되지 않는 문자가 있습니다(영숫자·공백·_ - . / ( ) : + 만)")
        stat, goal = r.get("stat"), r.get("goal")
        if stat not in STATS:
            p(i, "stat은 MAX | MIN | ABSMAX")
        if goal not in GOALS:
            p(i, "goal은 NONE | MINIMIZE | MAXIMIZE | CONSTRAINT")
        row.update(stat=stat, goal=goal)
        if goal == "CONSTRAINT":
            bound, value = r.get("bound"), r.get("value")
            if bound not in BOUNDS:
                p(i, "bound는 <= | >= | ==")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                p(i, "제약조건 value는 유한한 숫자여야 합니다")
            row.update(bound=bound, value=float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value)
        if goal in ("MINIMIZE", "MAXIMIZE"):
            n_obj += 1
        unknown = set(r) - {"name", "source", "subcase", "datatype", "component", "layer", "request", "stat", "goal",
                            "bound", "value"}
        if unknown:
            p(i, f"알 수 없는 키: {sorted(unknown)}")
        out.append(row)
    if approach == "OPT" and n_obj == 0 and not problems:
        problems.append({"row": "", "message": "OBJECTIVE_REQUIRED"})
    return out, problems


def responses_for_run(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """원본 키 대문자 형식(GUI:742-792)."""
    out = []
    for r in rows:
        item: dict[str, Any] = {"NAME": r["name"], "SOURCE": r["source"], "COMPONENT": r["component"], "STAT": r["stat"],
                                "GOAL": r["goal"]}
        if r["goal"] == "CONSTRAINT":
            item["BOUND"] = r["bound"]
            item["VALUE"] = float(r["value"])
        if r["source"] == "H3D":
            item.update({"SUBCASE": int(r["subcase"]), "DATATYPE": r["datatype"], "LAYER": r.get("layer", "")})
        else:
            item["REQUEST"] = r["request"]
        out.append(item)
    return out


def fwd(p: str) -> str:
    return p.replace("\\", "/")


def build_run_config(*, altair_home: str, dir_work: str, study_folder: str, cad_param: str, tpl_file: str,
                     hypermesh_tcl: str, radioss_assem_dir: str, starter: str, model: str, hyperview_tcl: str,
                     simlab_path: str, params: dict[str, Any]) -> dict[str, Any]:
    stem = os.path.splitext(os.path.basename(starter))[0]
    s = params.get("opt_settings") or {}
    return {
        "ALTAIR_HOME": fwd(altair_home),
        "DIR_WORK": fwd(dir_work),
        "STUDY_FOLDER": study_folder,
        "CAD_PARAM": fwd(cad_param),
        "TPL_FILE": fwd(tpl_file),
        "HYPERMESH_TCL": fwd(hypermesh_tcl),
        "RADIOSS_ASSEM_DIR": fwd(radioss_assem_dir),
        "PHYSICSAI_INPUT_FILE": fwd(starter),
        "PHYSICSAI_MODEL": fwd(model),
        "PREDICTED_H3D": f"{stem}_pred.h3d",
        "PREDICTED_XYDATA": f"{stem}_pred.xydata",
        "HYPERVIEW_TCL": fwd(hyperview_tcl),
        "ALTAIR_PATHS": {"simlab_path": fwd(simlab_path)},
        "PHYSICSAI_OVERRIDE_ENV": False,
        "RUN_NOMINAL": bool(params["run_nominal"]),
        "APPROACH": params["approach"],
        "OPT_METHOD": params["opt_method"],
        "MAX_DESIGNS": int(params["max_designs"]),
        "OPT_SETTINGS": {
            "ABS_CONVERGENCE": float(s.get("abs_convergence", 0.001)),
            "REL_CONVERGENCE": float(s.get("rel_convergence", 1.0)),
            "DV_CONVERGENCE": float(s.get("dv_convergence", 0.001)),
        },
        "ON_FAILED": params["on_failed"],
        "RESPONSES": responses_for_run(params["responses"]),
    }


# ---------------------------------------------------------------------------
# 결과 요약 파서(§6.12.1, U28)
# ---------------------------------------------------------------------------


def list_files(root: str, limit: int) -> list[dict[str, Any]]:
    out = []
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            out.append({"rel": os.path.relpath(p, root).replace(os.sep, "/"), "size": os.path.getsize(p)})
            if len(out) >= limit:
                return out
    return out


def match_glob(rel: str, globs: list[str]) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name.lower(), g.lower()) or fnmatch.fnmatch(rel.lower(), g.lower()) for g in globs)


def run_summary_parsers(root: str, files: list[dict[str, Any]], parsers: list[Any], max_bytes: int
                        ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """첫 성공 파서의 (summary.json 내용, summary_meta). 없으면 (None, None)."""
    for pz in parsers:
        cand = [f for f in files if match_glob(f["rel"], [pz.glob]) and f["size"] <= max_bytes]
        if not cand:
            continue
        rel = cand[0]["rel"]
        path = os.path.join(root, *rel.split("/"))
        try:
            if pz.kind == "csv_table":
                with open(path, encoding="utf-8-sig", newline="") as fh:
                    rd = csv.reader(fh)
                    columns = next(rd, [])
                    if not columns:
                        continue
                    lim = pz.max_rows or 1000
                    rows = []
                    for row in rd:
                        if len(rows) >= lim:
                            break
                        rows.append(row)
                data = {"parser": pz.name, "kind": pz.kind, "file_rel": rel, "columns": columns, "rows": rows}
                meta = {"parser": pz.name, "file_rel": rel, "row_count": len(rows), "columns": columns[:50]}
            elif pz.kind == "json_passthrough":
                with open(path, encoding="utf-8-sig") as fh:
                    content = json.load(fh)
                data = {"parser": pz.name, "kind": pz.kind, "file_rel": rel, "data": content}
                meta = {"parser": pz.name, "file_rel": rel, "row_count": None, "columns": []}
            else:
                continue
        except (OSError, ValueError, csv.Error):
            continue
        return data, meta
    return None, None


# ---------------------------------------------------------------------------
# 응답 후보(§6.12.2)
# ---------------------------------------------------------------------------


def candidates_from_preview(preview: Any) -> dict[str, Any] | None:
    """④ H3D_PREVIEW.json → {subcases:[{id, label, datatypes:[{name, components, layers, format}]}]}. 원본 형식과 다르면 가능한 키만."""
    if not isinstance(preview, dict):
        return None
    src = preview.get("h3d_preview") if isinstance(preview.get("h3d_preview"), dict) else preview
    scs = src.get("subcases") if isinstance(src, dict) else None
    if not isinstance(scs, list):
        return None
    out = []
    for i, sc in enumerate(scs, start=1):
        if not isinstance(sc, dict):
            continue
        dts = []
        for dt in sc.get("datatypes", []) or []:
            if not isinstance(dt, dict) or not isinstance(dt.get("name"), str):
                continue
            dts.append({"name": dt["name"], "components": [str(c) for c in dt.get("components", []) or []],
                        "layers": [str(x) for x in dt.get("layers", []) or []], "format": dt.get("format")})
        sid = sc.get("id", i)
        out.append({"id": int(sid) if isinstance(sid, int) or str(sid).isdigit() else i,
                    "label": str(sc.get("label") or sc.get("name") or f"Subcase {i}"), "datatypes": dts})
    return {"subcases": out} if out else None


def candidates_from_curve(curve: Any) -> dict[str, Any] | None:
    """④ curve.json(xydata 파서 출력) → {requests:{name:[component]}}. 원본 xydata_preview가 있으면 그대로."""
    if not isinstance(curve, dict):
        return None
    if isinstance(curve.get("xydata_preview"), dict) and isinstance(curve["xydata_preview"].get("requests"), dict):
        return {"requests": curve["xydata_preview"]["requests"]}
    if isinstance(curve.get("requests"), dict):
        return {"requests": curve["requests"]}
    series = curve.get("series")
    if not isinstance(series, list):
        return None
    req: dict[str, list[str]] = {}
    for s in series:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        name = str(s["name"])
        comp = str(s.get("component") or "")
        req.setdefault(name, [])
        if comp and comp not in req[name]:
            req[name].append(comp)
    return {"requests": req} if req else None
