"""BL_MAP(geometry-engine.md §7.3.8·§11.4): `paicad map`으로 다중 baseline 공통 변수 매칭 초안(param_map.json, status draft).

입력 = baseline마다 `native/extract/parameter_features.json`(첫 baseline `base` = 세트 S 자신, 추가 baseline = `S/baselines/<id>`,
지금 추가 중인 baseline은 T). 기존 `S/param_map.json`이 있으면 `--user-map`으로 넘겨 signature 같은 행의 decision을 승계한다.
출력은 `logs/_paramset_tmp/<job_id>_map/param_map.json`(세트에는 NP_REGISTER가 검사 후 저장). 성공 판정 = 파일 존재 + map_status OK
(paicad map은 성공해도 status가 draft이므로 일반 보고 판정을 쓰지 않는다).
"""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry.judge import parse_result_line
from physicsai_core.geometry.messages import korean_message
from physicsai_core.geometry.options import usage_document

from ..geometry_native import LocalRunner, child_env_add, tail_text

FEATURES_REL = "native/extract/parameter_features.json"


def map_out_dir(ctx: Any) -> str:
    return ctx.abs(f"logs/_paramset_tmp/{ctx.ex.job_id}_map")


def load_map(S: str, max_bytes: int) -> dict[str, Any] | None:
    try:
        return bl.load(S, max_bytes)
    except bl.MapError as exc:
        raise StepFailure(exc.code, exc.message) from None


def _entries(ctx: Any, S: str, old: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """(id, 준비본 루트, 세트 기준 rel). 지금 추가하는 baseline은 T(최종 위치 rel = baselines/<id>)."""
    out = [(b, bl.baseline_root(S, old, b), bl.baseline_rel(old, b)) for b in bl.baseline_ids(old)] if old else [(bl.BASE_ID, S, ".")]
    if ctx.params["mode"] == "add_baseline":
        bid = ctx.params["baseline"]["id"]
        if bid in [e[0] for e in out]:
            raise StepFailure("INPUT_INVALID", f"baseline id {bid}이(가) 이미 있습니다")
        out.append((bid, ctx.abs(ctx.result()["target_rel"]), f"{bl.BASELINES_DIR}/{bid}"))
    return out


def run_map(ctx: Any) -> None:
    s, p, r = ctx.settings, ctx.params, ctx.result()
    if s.commands.paicad_map is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "다중 baseline 매칭 명령(commands.paicad_map)이 설정되지 않았습니다")
    S = ctx.abs(r["param_set_rel"])
    old = load_map(S, s.geometry.max_report_bytes)
    usage = p.get("usage") or (old or {}).get("usage") or "topology"
    split = p.get("split_param") if p.get("split_param") is not None else ((old or {}).get("range_split") or {}).get("param")
    if usage == "topology":
        split = None
    if old is not None and old.get("usage") != usage:
        old = None  # 용도가 바뀌면 이전 결정은 승계하지 않는다(paicad도 다른 usage의 user map을 거부)
    entries = _entries(ctx, S, load_map(S, s.geometry.max_report_bytes))
    if len(entries) < 2:
        raise StepFailure("INPUT_INVALID", "다중 baseline 매칭에는 baseline이 2개 이상 필요합니다")
    for bid, root, _rel in entries:
        if not os.path.isfile(os.path.join(root, *FEATURES_REL.split("/"))):
            raise StepFailure("NATIVE_PREP_MISSING", f"baseline {bid}의 형상 피처 파일이 없습니다 — 형상 준비를 다시 하세요")
    out = map_out_dir(ctx)
    ctx.backup([out])
    os.makedirs(out, exist_ok=True)
    bj, oj, pm_out = os.path.join(out, "baselines.json"), os.path.join(out, "options_run.json"), os.path.join(out, bl.PARAM_MAP)
    write_json(bj, [{"id": bid, "features": os.path.join(root, *FEATURES_REL.split("/")), "rel": rel} for bid, root, rel in entries])
    write_json(oj, usage_document(r["opts"], r.get("engine_version")))
    user_map = ""
    if old is not None:  # 이전 결정 보존(서명 같은 행 승계) — 세트 파일을 그대로 넘긴다(paicad는 읽기만)
        user_map = bl.map_path(S)
    x = LocalRunner(ctx)
    values = {"baselines_json": bj, "map_out_dir": out, "user_map": user_map, "usage": usage, "split_param": split or "",
              "options_json": oj}
    rc = x.run("paicad_map", values, cwd=out, outputs_to_backup=[pm_out], env_add=child_env_add(s),
               timeout_s=s.geometry.timeout_s.get("tag"))
    tail = tail_text(os.path.join(out, "paicad.log"))
    if tail:
        ctx.log(f"--- paicad.log 꼬리 ---\n{tail}")
    doc = _read(pm_out, s.geometry.max_report_bytes)
    if doc is None or doc.get("map_status") != "OK":
        code = (x.last_result or (None, None))[1] or ("OUTPUT_MISSING" if rc == 0 else "EXIT_NONZERO")
        raise StepFailure(code, korean_message(code, None) if code.startswith(("GEOM_", "PARAM_")) else
                          f"매칭표(param_map.json)를 만들지 못했습니다(종료코드 {rc})")
    if rc != 0:
        ctx.add_warning("EXIT_NONZERO_IGNORED", f"종료코드 {rc}였지만 매칭표가 정상이라 성공으로 처리했습니다")
    n = len(doc.get("common") or [])
    ctx.add_output(pm_out)
    ctx.patch_result({"map_rel": ctx.rel(pm_out), "usage": usage, "split_param": split, "map_rows": n,
                      "map_grades": _grades(doc)})


def _read(path: str, max_bytes: int) -> dict[str, Any] | None:
    if not os.path.isfile(path) or os.path.getsize(path) > max_bytes:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) and d.get("schema_version") == 1 else None
    except (OSError, ValueError):
        return None


def _grades(doc: dict[str, Any]) -> dict[str, int]:
    out = {"recommend": 0, "check": 0, "unmatched": 0}
    for row in doc.get("common") or []:
        g = (row.get("proposed") or {}).get("grade") if isinstance(row, dict) else None
        if g in out:
            out[g] += 1
    return out


__all__ = ["load_map", "map_out_dir", "parse_result_line", "run_map"]
