"""조립 매칭 세트(방식 M, asm-match.md §5.4·§6.4)의 조립 사본 만들기 — `paicad asm write` 실행과 트리 파일 배치.

`{mesh_include_name}` 파일을 만들거나 찾지 않는다(AM-1). 모핑 PASS 결과 = `node_patch.npz`, 조립 사본 = include 트리 복사 + 패치 노드의
`/NODE` 줄 좌표만 갱신(paicad). 보고 `asm_write.json`은 `--out-dir` 직계(AM-C2)이고 임시 폴더에 남긴다(해석 입력에 넣지 않음).
성공 판정 = `asm_write.json` status OK + starter 존재(§6.4 `assembly_sources`·`assemble_into` 행).
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.geometry.asm_match import ASM_WRITE_JSON
from physicsai_core.geometry.judge import Verdict

from .geometry_native import NativeInputs, read_json, run_paicad

KEY = "paicad_asm_write"
WRITE_DIR = "asm_write"  # 작업 폴더 안 임시 출력(--out-dir, 없는 폴더여야 함)
NODE_PATCH = "node_patch.npz"


def require_command(settings: Any) -> None:
    if getattr(settings.commands, KEY, None) is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "조립 사본 쓰기 명령(commands.paicad_asm_write)이 설정되지 않았습니다 — 관리자 설정이 필요합니다")


def write_assembly(x: Any, settings: Any, inp: NativeInputs, patch: str | None, out: str, log_dir: str | None = None) -> Verdict:
    """`paicad asm write` 1회 + 판정(실패해도 던지지 않고 Verdict). patch = node_patch.npz 경로(없으면 공칭 — 바이트 동일 사본)."""
    require_command(settings)
    values = {**inp.base_values(settings), "node_patch": patch or "", "out_dir": out}
    return run_paicad(x, settings, KEY, values, cwd=os.path.dirname(out), report=os.path.join(out, ASM_WRITE_JSON), success=[], backup=[out],
                      body_map=None, log_dir=log_dir or out)


def place(verdict: Verdict, out: str, dst: str, checkpoint: Any = None) -> str:
    """보고의 `files[].rel`을 임시 출력 폴더 → dst로 옮긴다(상대 경로·하위 폴더 유지, 보고 파일은 두고 감). 반환 = starter 상대 경로.
    보고에 없는 파일은 옮기지 않는다(트리 밖 파일 불복사). starter가 없으면 OUTPUT_MISSING."""
    rep = verdict.report or {}
    rels = [str(f["rel"]) for f in rep.get("files") or [] if isinstance(f, dict) and f.get("rel")]
    starter = (rep.get("assem") or {}).get("starter")
    if not rels or not isinstance(starter, str) or starter not in rels:
        raise StepFailure("OUTPUT_MISSING", f"{ASM_WRITE_JSON}에 파일 목록·starter가 없습니다")
    for rel in rels:
        src = os.path.join(out, *rel.split("/"))
        if not os.path.isfile(src):
            raise StepFailure("OUTPUT_MISSING", f"조립 사본 파일이 만들어지지 않았습니다: {rel}")
        d = os.path.join(dst, *rel.split("/"))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        os.replace(src, d)
        if checkpoint:
            checkpoint()
    return starter


def assemble_matched(x: Any, settings: Any, inp: NativeInputs, patch: str | None, dst: str, out: str) -> tuple[str, Verdict]:
    """조립 사본(dst, 빈 폴더) 만들기 → (starter, Verdict). Verdict가 실패면 starter는 빈 문자열(호출자가 SKIPPED·실패 처리)."""
    v = write_assembly(x, settings, inp, patch, out)
    if not v.ok:
        return "", v
    return place(v, out, dst, checkpoint=x.check), v


def read_report(out: str, max_bytes: int) -> dict[str, Any]:
    return read_json(os.path.join(out, ASM_WRITE_JSON), max_bytes)
