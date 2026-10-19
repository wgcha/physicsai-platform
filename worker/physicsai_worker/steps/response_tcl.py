"""응답 추출 원본 ⑤ m_4 방식(phase3 §14.6) 워커 공용: ④ RESPONSE_EXTRACT · PV_EXTRACT · ①-6 RESPONSE_EXTRACT_RUNS.

`commands.response_extract`가 `{extract_tcl}`을 쓰면 이 방식(H3D_REQUESTS.txt → RESPONSES.txt), 아니면 각 step의 옛 방식
(`{out_csv}` 직접 작성) 그대로. h3d 폴더에 원본 TCL 사본·요청 파일을 두고 cwd = 그 폴더로 `hw -clientconfig hwpost.dat -b -tcl`
(설정 템플릿, shell=False, 제한기 안)을 실행한다 — 원본 TCL이 자기 폴더에서 요청·h3d를 찾기 때문(FUNC:360-366).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from physicsai_core.commands import fwd
from physicsai_core.errors import StepFailure
from physicsai_core.features import response_extract_uses_tcl
from physicsai_core.fileutil import copy_file, write_text
from physicsai_core.stage4_predict import responses as resp_mod

MAX_LOG_LINES = 2000


def uses_tcl(ctx: Any) -> bool:
    return response_extract_uses_tcl(ctx.settings)


def _append_log(ctx: Any, folder: str) -> None:
    path = os.path.join(folder, resp_mod.RESPONSES_LOG)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    ctx.log(f"---- {resp_mod.RESPONSES_LOG} ({len(lines)}줄) ----")
    for ln in lines[-MAX_LOG_LINES:]:
        ctx.log(ln)


def extract_in_folder(ctx: Any, responses: Sequence[Mapping[str, Any]], folder: str, h3d: str,
                      extra_values: Mapping[str, str] | None = None) -> tuple[dict[str, float | None], dict[str, str]]:
    """folder(= h3d가 있는 폴더)에서 원본 TCL로 응답을 추출해 ({name: 값|None}, {name: 사유})를 돌려준다.

    요청할 응답이 없으면 도구를 실행하지 않는다. 도구 실패(종료코드≠0이고 RESPONSES.txt 없음 등)는 StepFailure —
    호출자가 경고로 바꿀지 정한다(④는 경고, phase3 §14.6 사용자 결정). 종료코드≠0이어도 RESPONSES.txt가 있으면 성공 + 경고.
    """
    reqs, skipped = resp_mod.build_requests(responses)
    if not reqs:
        return resp_mod.pick_values(responses, resp_mod.ParsedResponses(), skipped=skipped)
    tcl_src = ctx.settings.resources.extract_minmax_tcl
    if not tcl_src or not os.path.isfile(tcl_src):
        raise StepFailure("RESOURCE_MISSING", f"resources.extract_minmax_tcl 파일이 없습니다: {tcl_src}")
    tcl = os.path.join(folder, os.path.basename(tcl_src))
    olds = [os.path.join(folder, n) for n in (resp_mod.REQUESTS_FILE, resp_mod.RESPONSES_FILE, resp_mod.RESPONSES_LOG)]
    ctx.backup([tcl, *olds])
    copy_file(tcl_src, tcl)
    resp_mod.write_requests(folder, reqs)
    values = {"extract_tcl": tcl, "pred_h3d": h3d, "pred_h3d_fwd": fwd(h3d), "work_dir": folder, **(extra_values or {})}
    rc = ctx.run_local("response_extract", values, cwd=folder, allow_nonzero_exit=True)
    _append_log(ctx, folder)
    parsed = resp_mod.read_responses(folder)
    if parsed is None:
        if rc != 0:
            raise StepFailure("EXIT_NONZERO", f"종료코드 {rc}: {resp_mod.RESPONSES_FILE}가 만들어지지 않았습니다")
        raise StepFailure("OUTPUT_MISSING", f"{resp_mod.RESPONSES_FILE}가 만들어지지 않았습니다")
    if rc != 0:
        ctx.add_warning("EXIT_NONZERO_IGNORED", f"응답 추출: 종료코드 {rc}였지만 {resp_mod.RESPONSES_FILE}가 있어 값을 읽었습니다")
    return resp_mod.pick_values(responses, parsed, skipped=skipped)


def curve_values(ctx: Any, responses: Sequence[Mapping[str, Any]], curve_json: str | None
                 ) -> tuple[dict[str, float | None], dict[str, str]]:
    """S17 §22.3.4: CURVE 성능 값을 예측 curve.json(CURVE_PICK 산출)에서 `performance.perf_value`로 계산.
    ({name: 값|None}, {name: 사유}) — CURVE 행만. curve.json 없으면 사유 NO_CURVE."""
    from physicsai_core.stage4_predict import performance, run_metrics

    defs = {n: d for n, d in performance.perf_defs(responses).items() if d.source == "CURVE"}
    if not defs:
        return {}, {}
    files = run_metrics.RunFiles(curve_json=curve_json if curve_json and os.path.isfile(curve_json) else None,
                                 result_dir=None)
    m = run_metrics.load_run_metrics(files, max_bytes=ctx.settings.ui.max_artifact_bytes)
    values: dict[str, float | None] = {}
    reasons: dict[str, str] = {}
    for n, d in defs.items():
        v, why = performance.perf_value(d, m)
        values[n] = v
        if why:
            reasons[n] = why
    return values, reasons


def merge_curve(responses: Sequence[Mapping[str, Any]], values: dict[str, float | None], reasons: dict[str, str],
                cvals: Mapping[str, float | None], creasons: Mapping[str, str]) -> None:
    """H3D 추출 결과(values·reasons, 정의 순서)에 CURVE 값을 채운다(제자리)."""
    for r in responses:
        n = str(r.get("name") or "")
        if n in cvals:
            values[n] = cvals[n]
            reasons.pop(n, None)
            if n in creasons:
                reasons[n] = creasons[n]


def append_curve_csv(ctx: Any, responses: Sequence[Mapping[str, Any]], out: str, curve_json: str) -> None:
    """옛 `{out_csv}` 방식: 도구가 쓴 name,value CSV에 CURVE 성능 값만 덧붙여 다시 쓴다(CURVE 정의가 없으면 그대로)."""
    from physicsai_core.parsers.name_value import read_name_value_csv

    cvals, creasons = curve_values(ctx, responses, curve_json)
    if not cvals:
        return
    warn_reasons(ctx, creasons)
    write_text(out, resp_mod.name_value_csv_text({**read_name_value_csv(out), **cvals}))


def has_h3d(responses: Sequence[Mapping[str, Any]]) -> bool:
    """H3D 요청이 1개 이상인지(없으면 TCL을 실행하지 않는다 — §22.3.4)."""
    return bool(resp_mod.build_requests(responses)[0])


def warn_reasons(ctx: Any, reasons: Mapping[str, str], prefix: str = "") -> None:
    """값 없는 응답 → 경고 RESPONSE_NO_VALUE(이름·사유) 1건. spec null(추출 정의 없음)은 경고하지 않는다."""
    reasons = {n: r for n, r in reasons.items() if r not in resp_mod.SILENT_REASONS}
    if not reasons:
        return
    body = ", ".join(f"{n}: {resp_mod.reason_text(r)}" for n, r in reasons.items())
    ctx.add_warning("RESPONSE_NO_VALUE", f"{prefix}응답 값을 얻지 못했습니다 — {body}"[:480])


def write_values_csv(ctx: Any, path: str, values: Mapping[str, float | None]) -> None:
    ctx.backup([path])
    write_text(path, resp_mod.name_value_csv_text(values))


def single_h3d(folder: str) -> tuple[str | None, list[str]]:
    """대상 폴더 직계 `*.h3d`가 정확히 1개면 (경로, 목록), 아니면 (None, 목록) — phase3 §14.6: 원본 TCL은 폴더의 h3d를
    전부 열므로 1개일 때만 추출한다(아니면 호출자가 SKIPPED/null + 경고 RESP_H3D_AMBIGUOUS)."""
    try:
        names = sorted(n for n in os.listdir(folder)
                       if n.lower().endswith(".h3d") and os.path.isfile(os.path.join(folder, n)))
    except OSError:
        names = []
    return (os.path.join(folder, names[0]) if len(names) == 1 else None), names


def extract_requests(ctx: Any, reqs: Sequence[resp_mod.H3dRequest], folder: str, h3d: str) -> resp_mod.ParsedResponses:
    """요청 목록을 그대로 써서 folder에서 원본 TCL 실행 → RESPONSES.txt 파싱(phase3 §21.3.6 S16 FV_EXTRACT — FEM datatype
    덮어쓰기·범례 줄 `__FV_LEGEND`). 도구 실패는 StepFailure(호출자가 경고로)."""
    tcl_src = ctx.settings.resources.extract_minmax_tcl
    if not tcl_src or not os.path.isfile(tcl_src):
        raise StepFailure("RESOURCE_MISSING", f"resources.extract_minmax_tcl 파일이 없습니다: {tcl_src}")
    tcl = os.path.join(folder, os.path.basename(tcl_src))
    olds = [os.path.join(folder, n) for n in (resp_mod.REQUESTS_FILE, resp_mod.RESPONSES_FILE, resp_mod.RESPONSES_LOG)]
    ctx.backup([tcl, *olds])
    copy_file(tcl_src, tcl)
    resp_mod.write_requests(folder, reqs)
    values = {"extract_tcl": tcl, "pred_h3d": h3d, "pred_h3d_fwd": fwd(h3d), "work_dir": folder}
    rc = ctx.run_local("response_extract", values, cwd=folder, allow_nonzero_exit=True)
    _append_log(ctx, folder)
    parsed = resp_mod.read_responses(folder)
    if parsed is None:
        if rc != 0:
            raise StepFailure("EXIT_NONZERO", f"종료코드 {rc}: {resp_mod.RESPONSES_FILE}가 만들어지지 않았습니다")
        raise StepFailure("OUTPUT_MISSING", f"{resp_mod.RESPONSES_FILE}가 만들어지지 않았습니다")
    return parsed
