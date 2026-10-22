"""쿠션 입력 rad 쓰기 공용(input-kind.md §5, geometry-engine.md GE-C19): `paicad cushion write` 실행.

모핑·check PASS 뒤(형상 값이 없으면 기준 include) 쿠션 바디만의 단일 starter rad(`predict.simlab_mesh_name`)를 만든다.
④ 단건(`predict_native.mesh`)과 ④ 일괄 run(`batch_native.gen_one`)이 같은 함수를 쓴다. 성공 판정 = `cushion.json`(OK) + 출력 rad.
쿠션 바디 범위는 세트 `RENUM_INIT.csv`(IK-7)라 조립 폴더(`assem_dir`)와 `renum_csv`를 그대로 넘긴다. 원본·SPDM은 읽기만 한다.
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.geometry.judge import Verdict
from physicsai_core.geometry.messages import label_of

from .geometry_native import NativeInputs, run_paicad

KEY = "paicad_cushion_write"
CUSHION_DIR = "cushion"
CUSHION_JSON = "cushion.json"
WARN_PART_DEF = "CUSHION_PART_DEF_MISSING"
MAX_WARN = 480


def require_command(settings: Any) -> None:
    """명령 미설정이면 `TEMPLATE_NOT_CONFIGURED`(IK-11) — 쿠션 입력 실행의 PR_PREP·BP_PREP이 먼저 확인한다."""
    if getattr(settings.commands, KEY, None) is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "쿠션 입력 rad 명령(commands.paicad_cushion_write)이 설정되지 않았습니다 — 관리자 설정이 필요합니다")


def require_cushion_capable(inp: NativeInputs, shell_values: dict[str, float] | None, shell_only: bool = False) -> None:
    """쉘 판금 세트·쉘 두께 전용 세트·쉘 두께 값은 쿠션 입력 불가(IK-3). 서버 검사가 먼저지만 워커도 막는다(요청 뒤 세트가 바뀐 경우)."""
    if inp.kind == "shell" or shell_only or shell_values:
        raise StepFailure("INPUT_KIND_UNSUPPORTED", "쉘 판금·쉘 두께 값이 있는 템플릿은 쿠션 입력으로 실행할 수 없습니다")


def _report_warnings(x: Any, v: Verdict) -> None:
    """보고 `warnings[]` 중 쿠션 부품 정의 누락을 한국어 경고로(이름 목록은 코드가 아니라 문구로만, 길이 제한)."""
    for w in (v.report or {}).get("warnings") or []:
        if isinstance(w, dict) and w.get("code") == WARN_PART_DEF:
            detail = w.get("message")
            msg = label_of(WARN_PART_DEF) + (f" — {detail}" if isinstance(detail, str) and detail else "")
            x.warn(WARN_PART_DEF, msg[:MAX_WARN])


def write_cushion(x: Any, settings: Any, inp: NativeInputs, *, cushion_inc: str, cushion_dir: str, cushion_rad: str,
                  log_dir: str | None = None) -> Verdict:
    """`paicad cushion write` 1회 + 판정(실패해도 던지지 않고 Verdict). x = LocalRunner | ParallelRunner.
    같은 이름 출력(cushion_dir·cushion_rad)이 있으면 먼저 `_backup`으로 옮긴다(paicad가 종료코드 3으로 거부하므로, 삭제 없음)."""
    require_command(settings)
    values = {**inp.base_values(settings), "cushion_inc": cushion_inc, "cushion_dir": cushion_dir, "cushion_rad": cushion_rad}
    v = run_paicad(x, settings, KEY, values, cwd=cushion_dir, report=os.path.join(cushion_dir, CUSHION_JSON), success=[cushion_rad],
                   backup=[cushion_dir, cushion_rad], body_map=None, log_dir=log_dir or cushion_dir)
    if v.ok:
        _report_warnings(x, v)
    return v
