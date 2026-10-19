"""단계 3S 쉘 두께(geometry-engine.md §11.1) 워커 공용: `paicad props scan`·`props apply` 실행.

- scan: 세트 조립 폴더(`S/radioss_assem`) → `S/native/props/props.json`(성공 = 보고 존재 + status OK).
- apply: run의 INPUT **복사본**(단건 `P/INPUT`, 샘플 `R/m_3`)에 쉘 두께 값을 적용. paicad는 `--out-dir`에 PROP 정의 파일
  사본만 쓰고(원본 불변), 플랫폼이 그 사본을 INPUT 복사본의 같은 상대 경로에 덮어쓴다. 원본 조립 폴더·SPDM은 건드리지 않는다.
- 실패(PROP_*·GEOM_*)는 Verdict로 돌려준다(호출자가 step 실패·샘플 스킵으로 처리). 실행 파일 없음 등 플랫폼 오류만 StepFailure.
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json
from physicsai_core.geometry.judge import Verdict
from physicsai_core.geometry.shell import apply_values_document

from .geometry_native import run_paicad

PROPS_JSON = "props.json"
APPLY_JSON = "props_apply.json"
VALUES_JSON = "props_values.json"


def require_props_commands(settings: Any, *keys: str) -> None:
    missing = [k for k in keys if getattr(settings.commands, k, None) is None]
    if missing:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "쉘 두께 명령 템플릿이 설정되지 않았습니다: " + ", ".join(f"commands.{k}" for k in missing))


def run_scan(x: Any, settings: Any, assem_dir: str, out_dir: str, options_json: str) -> Verdict:
    """`paicad props scan` → out_dir/props.json. 이전 출력은 `_backup`으로(덮어쓰지 않음)."""
    require_props_commands(settings, "paicad_props_scan")
    os.makedirs(out_dir, exist_ok=True)
    pj = os.path.join(out_dir, PROPS_JSON)
    return run_paicad(x, settings, "paicad_props_scan", {"assem_dir": assem_dir, "options_json": options_json, "out_dir": out_dir},
                      cwd=out_dir, report=pj, success=[pj], backup=[pj, os.path.join(out_dir, "paicad.log")], log_dir=out_dir)


def apply(x: Any, settings: Any, input_dir: str, values: dict[str, float], props_json: str, work_dir: str,
          engine_version: str | None) -> Verdict:
    """INPUT 복사본(input_dir)에 쉘 두께 적용. work_dir = 이 run의 작업 폴더(값 파일·paicad 출력 `work_dir/out`)."""
    require_props_commands(settings, "paicad_props_apply")
    if not os.path.isfile(props_json):
        raise StepFailure("INPUT_CHANGED", "쉘 두께 PROP 목록(native/props/props.json)이 없습니다 — PROP 스캔을 다시 하세요")
    os.makedirs(work_dir, exist_ok=True)
    vj, out = os.path.join(work_dir, VALUES_JSON), os.path.join(work_dir, "out")
    _backup(x, [vj])
    write_json(vj, apply_values_document(values, engine_version))
    v = run_paicad(x, settings, "paicad_props_apply",
                   {"assem_dir": input_dir, "values_json": vj, "props_json": props_json, "out_dir": out},
                   cwd=work_dir, report=os.path.join(out, APPLY_JSON), success=[], backup=[out], log_dir=out)
    if not v.ok:
        return v
    for f in (v.report or {}).get("files") or []:
        rel = f.get("rel") if isinstance(f, dict) else None
        if not isinstance(rel, str) or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
            raise StepFailure("INPUT_INVALID", f"props_apply.json의 파일 경로가 올바르지 않습니다: {rel!r}")
        src, dst = os.path.join(out, *rel.split("/")), os.path.join(input_dir, *rel.split("/"))
        if not os.path.isfile(src):
            raise StepFailure("OUTPUT_MISSING", f"쉘 두께 적용 사본이 없습니다: {rel}")
        copy_file(src, dst, checkpoint=x.check)  # 이 run이 만든 INPUT 복사본만 덮어쓴다(원본 조립 폴더 불변)
    return v


def _backup(x: Any, paths: list[str]) -> None:
    from .geometry_sample import backup_path

    for p in paths:
        if os.path.lexists(p):
            backup_path(x, p)
