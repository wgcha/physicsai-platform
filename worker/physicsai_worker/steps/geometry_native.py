"""native 형상 엔진(`paicad`) 실행 공용(geometry-engine.md §7.2): 별도 프로세스 실행·진행률·시간 상한·판정·로그 꼬리.

- 실행 파일·인자는 설정 템플릿(`commands.paicad_*`, `{paicad}` = geometry.paicad_path)에서만, shell=False(제한기 launch).
- 성공은 종료코드가 아니라 출력 파일·보고 JSON으로 판정(`physicsai_core.geometry.judge`).
- 이 모듈은 `paicad`·OCP를 import하지 않는다(§1.4) — 결과 JSON·파일만 읽는다.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from physicsai_core.commands import template_uses
from physicsai_core.errors import StepFailure
from physicsai_core.geometry.judge import Verdict, judge_paicad, parse_result_line
from physicsai_core.geometry.reports import ReportError, parse_version_json

LOG_TAIL_BYTES = 4096  # 각 단계 로그에 덧붙이는 paicad.log 꼬리(§7.2)
PAICAD_LOG = "paicad.log"
TIMEOUT_KEY = {"paicad_extract": "extract", "paicad_tag": "tag", "paicad_update": "update", "paicad_morph": "morph",
               "paicad_check": "check", "paicad_run": "run"}


@dataclass
class NativeInputs:
    """paicad가 읽는 준비본 경로(세트 S 또는 DOE D 기준)."""

    cad_input: str
    features: str
    tag_dir: str
    baseline_inc: str
    assem_dir: str
    renum_csv: str
    body_map: str | None = None

    def base_values(self, settings: Any) -> dict[str, str]:
        return {"cad_input": self.cad_input, "features_json": self.features, "tag_dir": self.tag_dir,
                "baseline_inc": self.baseline_inc, "assem_dir": self.assem_dir, "renum_csv": self.renum_csv}


def find_cad_input(base: str, step_exts: list[str]) -> str:
    """`<base>/cad/`의 단일 STEP 파일 또는 `cad/parts` 폴더(§4.1). 없으면 INPUT_CHANGED."""
    cad = os.path.join(base, "cad")
    exts = tuple(e.lower() for e in step_exts)
    files = sorted(n for n in os.listdir(cad) if os.path.isfile(os.path.join(cad, n)) and n.lower().endswith(exts)) \
        if os.path.isdir(cad) else []
    if files:
        return os.path.join(cad, files[0])
    parts = os.path.join(cad, "parts")
    if os.path.isdir(parts) and any(n.lower().endswith(exts) for n in os.listdir(parts)):
        return parts
    raise StepFailure("INPUT_CHANGED", "공칭 STEP 파일이 없습니다 — 형상 준비를 다시 하세요")


def native_inputs(settings: Any, base: str, assem_dir: str, *, need_cad: bool = True) -> NativeInputs:
    """need_cad=False: 쉘 두께 전용 세트(§11.1) — STEP 없음(cad_input 빈 값, paicad 형상 단계를 부르지 않는다)."""
    pr = settings.predict
    bm = os.path.join(base, "cad", "body_map.json")
    return NativeInputs(
        cad_input=find_cad_input(base, settings.geometry.step_extensions) if need_cad else "",
        features=os.path.join(base, "native", "extract", "parameter_features.json"),
        tag_dir=os.path.join(base, "native", "tag"),
        baseline_inc=os.path.join(assem_dir, pr.mesh_include_name),
        assem_dir=assem_dir, renum_csv=os.path.join(assem_dir, pr.renum_csv_name),
        body_map=bm if os.path.isfile(bm) else None)


def tail_text(path: str, n: int = LOG_TAIL_BYTES) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - n))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def is_native(params: dict[str, Any] | None) -> bool:
    """작업 params의 엔진(서버가 작업 생성 때 기록, §7.3). 없으면 altair."""
    return isinstance(params, dict) and params.get("engine") == "native"


def child_env_add(settings: Any) -> dict[str, str]:
    return dict(settings.geometry.env)


def extra_args_for(settings: Any, key: str, body_map: str | None) -> list[str]:
    """`{cad_input}`을 쓰는 명령에만 `--body-map <경로>`(S/cad/body_map.json이 있을 때)를 덧붙인다(§7.1)."""
    if body_map and os.path.isfile(body_map) and template_uses(getattr(settings.commands, key, None), "cad_input"):
        return ["--body-map", body_map]
    return []


class LocalRunner:
    """step 컨텍스트(`ctx.run_local`)를 `ParallelRunner`와 같은 모양(run·log·warn·check·last_line)으로 감싼다."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.last_line = ""
        self.last_result: tuple[str, str | None] | None = None
        rx = ctx.settings.geometry.progress_regex
        self._rx = re.compile(rx)

    def log(self, line: str) -> None:
        self.ctx.log(line)

    def warn(self, code: str, message: str) -> None:
        self.ctx.add_warning(code, message)

    def check(self) -> None:
        self.ctx.checkpoint()

    def _line(self, line: str) -> tuple[float | None, str | None] | None:
        r = parse_result_line(line)
        if r is not None:
            self.last_result = r
        m = self._rx.search(line)
        if not m:
            return None
        try:
            return min(float(m.group("pct")), 100.0), m.group("msg")[:100]
        except ValueError:
            return None

    def run(self, key: str, values: dict[str, str], *, cwd: str, outputs_to_backup: list[str] | None = None,
            env_add: dict[str, str] | None = None, extra_args: Sequence[str] = (), timeout_s: float | None = None) -> int:
        began = time.monotonic()

        def poll() -> tuple[float | None, str | None] | None:
            if timeout_s is not None and time.monotonic() - began > timeout_s:  # 던지면 run_local이 프로세스 트리를 종료한다
                raise StepFailure("GEOM_TIMEOUT", f"실행 시간 제한({timeout_s:g}초)을 넘어 중단했습니다")
            return None

        self.last_result = None
        rc = self.ctx.run_local(key, values, cwd=cwd, outputs_to_backup=outputs_to_backup, env_add=env_add,
                                check_log_errors=False, allow_nonzero_exit=True, line_hook=self._line, poll_hook=poll,
                                extra_args=extra_args)
        self.last_line = getattr(self.ctx, "last_line", "")
        return rc


def run_paicad(x: Any, settings: Any, key: str, values: dict[str, str], *, cwd: str, report: str, success: list[str],
               backup: list[str], body_map: str | None = None, log_dir: str | None = None) -> Verdict:
    """paicad 명령 1회 실행 + 판정. x = LocalRunner | ParallelRunner. 실패해도 예외를 던지지 않고 Verdict를 돌려준다
    (호출자가 step 실패·run 실패·SKIPPED로 처리). 플랫폼 오류(실행 파일 없음·시간 초과 등)만 StepFailure."""
    g = settings.geometry
    timeout = g.timeout_s.get(TIMEOUT_KEY.get(key, ""), None)
    # 같은 이름 출력이 있으면 paicad가 종료코드 3으로 거부하므로 먼저 `_backup`으로 옮긴다(삭제 없음, §5.2)
    rc = x.run(key, values, cwd=cwd, outputs_to_backup=backup, env_add=child_env_add(settings),
               extra_args=extra_args_for(settings, key, body_map), timeout_s=timeout)
    verdict = judge_paicad(rc, report, success, max_bytes=g.max_report_bytes, result_line=getattr(x, "last_result", None))
    tail = tail_text(os.path.join(log_dir or os.path.dirname(report), PAICAD_LOG))
    if tail:
        x.log(f"--- {PAICAD_LOG} 꼬리 ---\n{tail}")
    for code, msg in verdict.warnings:
        x.warn(code, msg)
    return verdict


def engine_version(ctx: Any) -> tuple[str | None, str | None, str | None]:
    """`paicad version --json` → (paicad 버전, OCP 버전, 표시 문구). 실행 파일이 없거나 형식 오류면 StepFailure."""
    from physicsai_core.geometry.reports import version_display

    lines: list[str] = []

    def collect(line: str) -> None:
        lines.append(line)
        return None

    ctx.run_local("paicad_version", {}, cwd=os.path.dirname(ctx.log_path), check_log_errors=False, line_hook=collect,
                  env_add=child_env_add(ctx.settings))
    try:
        doc = parse_version_json("\n".join(lines))
    except ReportError as exc:
        raise StepFailure("INPUT_INVALID", exc.message) from None
    return doc.get("paicad"), doc.get("ocp"), version_display(doc)


def effective_opts(settings: Any, geom_options: dict[str, Any] | None) -> dict[str, Any]:
    """유효 옵션 = 코드 기본값 ← geometry.defaults ← 세트 geom_options(§4.9). 범위 위반은 CONFIG_INVALID(저장 때 API가 먼저 막음)."""
    from physicsai_core.geometry.options import effective_options

    opts, probs = effective_options(settings.geometry.defaults, geom_options)
    if probs:
        raise StepFailure("CONFIG_INVALID", "형상 옵션이 범위를 벗어납니다: " + "; ".join(f"{p['key']}" for p in probs[:5]))
    return opts


def ensure_prep_ready(settings: Any, S: str, opts: dict[str, Any], current_version: str | None) -> None:
    """준비본 유효성(§4.2): 입력 sha256·tag 옵션·버전(MAJOR.MINOR)이 다르면 INPUT_CHANGED."""
    from physicsai_core.geometry.prep import READY, prep_state

    pr = settings.predict
    st = prep_state(S, step_exts=settings.geometry.step_extensions, mesh_include_name=pr.mesh_include_name,
                    renum_csv_name=pr.renum_csv_name, opts=opts, current_engine_version=current_version)
    if st.status != READY:
        raise StepFailure("INPUT_CHANGED", st.reason or "형상 준비본이 유효하지 않습니다")


def write_native_options(native_dir: str, opts: dict[str, Any], ver: str | None) -> str:
    """`<native_dir>/options.json`(tag 절만, 준비본 기록) + `options_run.json`(사용값 문서, paicad 인자). options_run 경로를 돌려준다."""
    from physicsai_core.fileutil import write_json
    from physicsai_core.geometry.options import usage_document

    write_json(os.path.join(native_dir, "options.json"), {"schema_version": 1, "tag": opts["tag"]})
    run = os.path.join(native_dir, "options_run.json")
    write_json(run, usage_document(opts, ver))
    return run


def read_json(path: str, max_bytes: int) -> dict[str, Any]:
    from physicsai_core.geometry.reports import read_report

    try:
        return read_report(path, max_bytes)
    except ReportError as exc:
        raise StepFailure("INPUT_INVALID", exc.message) from None


def load_json_file(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


