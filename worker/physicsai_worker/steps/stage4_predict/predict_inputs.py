"""④ PREDICT 입력 준비 step(phase3 §11.4·§11.5): GEOM_UPDATE·MESH·RAD_ASSEMBLE와 입력 방식(parametric·prepared) 공용 도우미.

parametric = 원본 ⑤ 체인: SimLab(형상 갱신·메싱 → `EPS_mesh_0000.rad`) → HyperMesh m_2(include 변환 → `104_replace_node_elem.inc`)
→ 조립 폴더 사본에 새 include를 넣어 starter가 새 메시를 쓰게 한다. 성공은 종료코드가 아니라 출력 파일로 판정한다(원본 SimLab rc 무시).
prepared = 원본 ③ 단독 예측: 사용자가 준비한 입력(읽기 전용)을 P/INPUT으로 복사.
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file
from physicsai_core.paths import PathError, is_link_or_reparse
from physicsai_core.stage4_predict import prepared_input
from physicsai_core.stage4_predict.prepared_input import CopyPlan, is_mesh_file

from ...signals import StepSkipped

PREPARED_SKIP = "준비된 입력 — 해당 없음"
LOG_BATCH = "log_batch.txt"  # 원본 include TCL이 cwd에 쓰는 로그(phase3 §11.1)
MAX_LOG_LINES = 5000


def predict_dir(ctx: Any) -> str:
    return ctx.abs(f"04_predict/{ctx.workspace_id}")


def is_prepared(ctx: Any) -> bool:
    return ctx.params.get("input_mode") == "prepared"


def param_set(ctx: Any) -> tuple[dict[str, Any] | None, str | None]:
    """작업의 파라미터 세트(prepared는 없을 수 있음) → (행, 저장 폴더)."""
    psid = ctx.params.get("param_set_id")
    if not psid:
        return None, None
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, psid)
    if ps is None or ps["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "파라미터 세트를 찾을 수 없습니다")
    return ps, ctx.abs(ps["stored_rel"])


def require_param_set(ctx: Any) -> tuple[dict[str, Any], str]:
    ps, S = param_set(ctx)
    if ps is None or S is None:
        raise StepFailure("INPUT_INVALID", "파라미터 세트를 찾을 수 없습니다")
    return ps, S


def check_prepared(ctx: Any) -> CopyPlan:
    """준비된 입력 재검사(phase3 §11.5): 작업 등록 때와 다르면 INPUT_CHANGED."""
    try:
        cp = prepared_input.check_path(ctx.params["input_path"], ctx.settings)
    except PathError as exc:
        raise StepFailure("INPUT_CHANGED", f"준비된 입력을 다시 확인할 수 없습니다: {exc.message}") from None
    plan = prepared_input.plan_copy(cp.path, ctx.settings)
    if plan.problems:
        raise StepFailure("INPUT_CHANGED", f"작업 등록 후 준비된 입력이 바뀌었습니다: {plan.problems[0]['message']}")
    if plan.kind != ctx.params.get("input_kind") or plan.starter != ctx.params.get("starter_name"):
        raise StepFailure("INPUT_CHANGED", f"작업 등록 후 준비된 입력이 바뀌었습니다(starter {plan.starter})")
    return plan


def _geom(ctx: Any) -> str:
    return os.path.join(predict_dir(ctx), "geom")


def _geom_values(ctx: Any, ps: dict[str, Any], S: str) -> dict[str, str]:
    g, pr = _geom(ctx), ctx.settings.predict
    return {"rendered_script": os.path.join(g, pr.rendered_script_name), "cad_file": os.path.join(g, ps["cad_file_name"]),
            "work_dir": g, "include_tcl": ctx.settings.resources.hypermesh_include_tcl,
            "simlab_mesh": os.path.join(g, pr.simlab_mesh_name), "mesh_inc": os.path.join(g, pr.mesh_include_name),
            "renum_csv": os.path.join(S, "radioss_assem", pr.renum_csv_name)}


def _judge_output(ctx: Any, rc: int, out: str, step: str) -> None:
    """출력 파일 기준 판정(phase3 §11.4, EDSPY_PREDICT는 D3-37): 있음(크기>0) = 성공(rc≠0이면 경고),
    없음 = OUTPUT_MISSING(rc≠0이면 EXIT_NONZERO)."""
    name = os.path.basename(out)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        if rc != 0:
            ctx.add_warning("EXIT_NONZERO_IGNORED", f"{step}: 종료코드 {rc}였지만 출력 {name}이(가) 있어 성공으로 처리했습니다")
        ctx.add_output(out)
        return
    if rc != 0:
        raise StepFailure("EXIT_NONZERO", f"종료코드 {rc}: 출력 {name}이(가) 만들어지지 않았습니다 {getattr(ctx, 'last_line', '')}".rstrip())
    raise StepFailure("OUTPUT_MISSING", f"출력 {name}이(가) 만들어지지 않았습니다")


def geom_update(ctx: Any) -> None:
    """GEOM_UPDATE: SimLab `-auto <렌더 .py> -nographics`(cwd P/geom). 성공 = P/geom/{simlab_mesh_name}."""
    if is_prepared(ctx):
        raise StepSkipped(PREPARED_SKIP)
    if ctx.settings.commands.geom_update is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "형상 갱신 명령 템플릿(geom_update)이 설정되지 않았습니다")
    ps, S = require_param_set(ctx)
    v = _geom_values(ctx, ps, S)
    rc = ctx.run_local("geom_update", v, cwd=v["work_dir"], outputs_to_backup=[v["simlab_mesh"]], allow_nonzero_exit=True)
    _judge_output(ctx, rc, v["simlab_mesh"], "형상 갱신")


def _append_log_batch(ctx: Any, path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    lines = text.splitlines()
    ctx.log(f"---- {LOG_BATCH} ({len(lines)}줄) ----")
    for ln in lines[-MAX_LOG_LINES:]:
        ctx.log(ln)
    return text


def mesh(ctx: Any) -> None:
    """MESH: 원본 m_2 HyperMesh include 변환(cwd P/geom). 성공 = P/geom/{mesh_include_name}. 템플릿 null → SKIPPED."""
    if is_prepared(ctx):
        raise StepSkipped(PREPARED_SKIP)
    if ctx.settings.commands.mesh is None:
        raise StepSkipped("메싱 템플릿 미설정 — 형상 갱신 단계가 include를 직접 작성")
    ps, S = require_param_set(ctx)
    v = _geom_values(ctx, ps, S)
    pr = ctx.settings.predict
    if any("{include_tcl}" in el for el in ctx.settings.commands.mesh):
        tcl = v["include_tcl"]
        if not tcl or not os.path.isfile(tcl):
            raise StepFailure("RESOURCE_MISSING", f"resources.hypermesh_include_tcl 파일이 없습니다: {tcl}")
    if not os.path.isfile(v["renum_csv"]):
        ctx.add_warning("RENUM_CSV_MISSING", f"조립 폴더에 {pr.renum_csv_name}이(가) 없습니다 — 노드·요소 번호 재지정 표 없이 실행했습니다")
    log_batch = os.path.join(v["work_dir"], LOG_BATCH)
    rc = ctx.run_local("mesh", v, cwd=v["work_dir"], outputs_to_backup=[v["mesh_inc"], log_batch], allow_nonzero_exit=True)
    text = _append_log_batch(ctx, log_batch) if os.path.isfile(log_batch) else ""
    if pr.mesh_log_complete_marker and pr.mesh_log_complete_marker not in text:
        ctx.add_warning("MESH_LOG_INCOMPLETE", f"메시 변환 로그({LOG_BATCH})에 완료 표식 '{pr.mesh_log_complete_marker}'이 없습니다")
    _judge_output(ctx, rc, v["mesh_inc"], "메시 변환")


def _copy_into(ctx: Any, inp: str, sources: list[str]) -> list[str]:
    names = [os.path.basename(x) for x in sources]
    dsts = [os.path.join(inp, n) for n in names]
    ctx.backup(dsts)
    for src, dst in zip(sources, dsts):
        copy_file(src, dst, checkpoint=ctx.checkpoint)
        ctx.log(f"복사 {src} → INPUT/{os.path.basename(dst)}")
    return names


def _assemble_parametric(ctx: Any, inp: str) -> str:
    """RAD_ASSEMBLE(parametric, phase3 §11.4): 조립 폴더 사본(eps_mesh·include 기준본 제외) + 새 include → INPUT."""
    _ps, S = require_param_set(ctx)
    pr = ctx.settings.predict
    inc = pr.mesh_include_name
    assem = os.path.join(S, "radioss_assem")
    listing = sorted(os.listdir(assem))
    srcs = [os.path.join(assem, n) for n in listing
            if n.lower().endswith((".rad", ".inc")) and not is_mesh_file(n) and n.lower() != inc.lower()
            and os.path.isfile(os.path.join(assem, n))]
    new_inc = os.path.join(_geom(ctx), inc)
    if not os.path.isfile(new_inc) or os.path.getsize(new_inc) == 0:
        raise StepFailure("OUTPUT_MISSING", f"새 메시 include({inc})가 없습니다 — 형상 갱신·메시 변환 결과를 확인하세요")
    names = _copy_into(ctx, inp, srcs) + _copy_into(ctx, inp, [new_inc])
    if not any(n.lower() == inc.lower() for n in listing):
        ctx.add_warning("MESH_INCLUDE_NOT_IN_ASSEM",
                        f"조립 폴더에 {inc} 기준본이 없습니다 — starter가 이 include를 쓰는지 확인하세요")
    starters = [n for n in names if fnmatch.fnmatch(n, pr.starter_glob) and not is_mesh_file(n)]
    if len(starters) != 1:
        raise StepFailure("INPUT_INVALID", f"starter({pr.starter_glob})가 정확히 1개여야 합니다(현재 {len(starters)}개)")
    return starters[0]


def _reset_input(ctx: Any, inp: str) -> None:
    """P/INPUT 기존 내용을 통째로 `_backup/<stamp>_<job>/…/INPUT`으로 옮긴다(phase3 D3-36).

    원본(opti:290-292)은 매번 비우지만 플랫폼은 삭제 대신 이동한다. 재시도 때 이전 시도 파일·S6 이전 작업의
    `EPS_mesh*`가 남아 starter 셈·edspy 입력에 섞이지 않게 한다. 빈 폴더는 그대로 둔다.
    """
    if os.path.lexists(inp) and not (os.path.isdir(inp) and not is_link_or_reparse(inp) and not os.listdir(inp)):
        ctx.backup([inp])
    os.makedirs(inp, exist_ok=True)


def rad_assemble(ctx: Any) -> None:
    P = predict_dir(ctx)
    inp = os.path.join(P, "INPUT")
    _reset_input(ctx, inp)
    if is_prepared(ctx):
        plan = check_prepared(ctx)  # 원본 폴더는 읽기만(복사 원천)
        _copy_into(ctx, inp, plan.files)
        ctx.patch_result({"starter": plan.starter})
        return
    starter = _assemble_parametric(ctx, inp)
    if ctx.settings.commands.rad_assemble is not None:
        ctx.run_local("rad_assemble", {"work_dir": P, "starter": os.path.join(inp, starter), "input_dir": inp}, cwd=inp)
    ctx.patch_result({"starter": starter})
