"""④ PREDICT 입력 준비 step(phase3 §11.4·§11.5): GEOM_UPDATE·MESH·RAD_ASSEMBLE와 입력 방식(parametric·prepared) 공용 도우미.

parametric = 원본 ⑤ 체인: SimLab(형상 갱신·메싱 → `EPS_mesh_0000.rad`) → HyperMesh m_2(include 변환 → `104_replace_node_elem.inc`)
→ 조립 폴더 사본에 새 include를 넣어 starter가 새 메시를 쓰게 한다. 성공은 종료코드가 아니라 출력 파일로 판정한다(원본 SimLab rc 무시).
prepared = 원본 ③ 단독 예측: 사용자가 준비한 입력(읽기 전용)을 P/INPUT으로 복사(eps_mesh 포함, D3-44 — 제외는 parametric만).
mesh_only 템플릿(phase3 §14.4): MESH SKIPPED, RAD_ASSEMBLE은 P/geom 직계 rad·inc 복사만, starter = SimLab 메시(`EPS_mesh_0000.rad`).
템플릿 종류는 작업 params `template_kind`(없으면 세트 `input_kind`) — prepared params의 `input_kind`(file|dir)와 다르다.
판정·조립 규칙은 일괄 예측 BP_GEN(run 폴더 m_1~m_3)이 같이 쓴다(`judge_output`·`assemble_into`·`mesh_only_into`).
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
MESH_ONLY_SKIP = "쿠션 단독 템플릿 — 메시 연결 불필요"
MESH_ONLY = "mesh_only"
ASSEMBLY = "assembly"
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


def template_kind(ctx: Any, ps: dict[str, Any] | None = None) -> str:
    """parametric 템플릿 종류(phase3 §14.4): params `template_kind`(서버 확정 기록) → 세트 `input_kind` → assembly."""
    k = ctx.params.get("template_kind")
    if k in (MESH_ONLY, ASSEMBLY):
        return k
    if ps is None:
        ps, _S = param_set(ctx)
    k = (ps or {}).get("input_kind")
    return k if k in (MESH_ONLY, ASSEMBLY) else ASSEMBLY


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
    # 일괄 예측 하위(BP_ENQUEUE가 만든 작업)는 등록 시 계획(input_kind·starter_name)을 params에 남기지 않는다 — 있으면 비교
    want_kind, want_starter = ctx.params.get("input_kind"), ctx.params.get("starter_name")
    if ((want_kind is not None or not ctx.params.get("batch_run")) and plan.kind != want_kind) or \
            ((want_starter is not None or not ctx.params.get("batch_run")) and plan.starter != want_starter):
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


def judge_output(rc: int, out: str, step: str, last_line: str = "") -> tuple[str, str] | None:
    """출력 파일 기준 판정(phase3 §11.4, EDSPY_PREDICT는 D3-37): 있음(크기>0) = 성공(rc≠0이면 경고 (code, message)),
    없음 = OUTPUT_MISSING(rc≠0이면 EXIT_NONZERO)."""
    name = os.path.basename(out)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        if rc != 0:
            return "EXIT_NONZERO_IGNORED", f"{step}: 종료코드 {rc}였지만 출력 {name}이(가) 있어 성공으로 처리했습니다"
        return None
    if rc != 0:
        raise StepFailure("EXIT_NONZERO", f"종료코드 {rc}: 출력 {name}이(가) 만들어지지 않았습니다 {last_line}".rstrip())
    raise StepFailure("OUTPUT_MISSING", f"출력 {name}이(가) 만들어지지 않았습니다")


def _judge_output(ctx: Any, rc: int, out: str, step: str) -> None:
    w = judge_output(rc, out, step, getattr(ctx, "last_line", ""))
    if w:
        ctx.add_warning(*w)
    ctx.add_output(out)


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


def mesh_preflight(settings: Any, renum_csv: str) -> list[tuple[str, str]]:
    """MESH 실행 전 확인(phase3 §11.4·D3-32): include TCL 자원 없음 → RESOURCE_MISSING, csv 없음 → 경고 RENUM_CSV_MISSING."""
    if any("{include_tcl}" in el for el in settings.commands.mesh or []):
        tcl = settings.resources.hypermesh_include_tcl
        if not tcl or not os.path.isfile(tcl):
            raise StepFailure("RESOURCE_MISSING", f"resources.hypermesh_include_tcl 파일이 없습니다: {tcl}")
    if not os.path.isfile(renum_csv):
        name = settings.predict.renum_csv_name
        return [("RENUM_CSV_MISSING", f"조립 폴더에 {name}이(가) 없습니다 — 노드·요소 번호 재지정 표 없이 실행했습니다")]
    return []


def mesh_log_warning(settings: Any, text: str) -> tuple[str, str] | None:
    marker = settings.predict.mesh_log_complete_marker
    if marker and marker not in text:
        return "MESH_LOG_INCOMPLETE", f"메시 변환 로그({LOG_BATCH})에 완료 표식 '{marker}'이 없습니다"
    return None


def mesh(ctx: Any) -> None:
    """MESH: 원본 m_2 HyperMesh include 변환(cwd P/geom). 성공 = P/geom/{mesh_include_name}. 템플릿 null → SKIPPED."""
    if is_prepared(ctx):
        raise StepSkipped(PREPARED_SKIP)
    ps, S = require_param_set(ctx)
    if template_kind(ctx, ps) == MESH_ONLY:  # phase3 §14.4: commands.mesh 설정과 무관
        raise StepSkipped(MESH_ONLY_SKIP)
    if ctx.settings.commands.mesh is None:
        raise StepSkipped("메싱 템플릿 미설정 — 형상 갱신 단계가 include를 직접 작성")
    v = _geom_values(ctx, ps, S)
    for w in mesh_preflight(ctx.settings, v["renum_csv"]):
        ctx.add_warning(*w)
    log_batch = os.path.join(v["work_dir"], LOG_BATCH)
    rc = ctx.run_local("mesh", v, cwd=v["work_dir"], outputs_to_backup=[v["mesh_inc"], log_batch], allow_nonzero_exit=True)
    text = _append_log_batch(ctx, log_batch) if os.path.isfile(log_batch) else ""
    w = mesh_log_warning(ctx.settings, text)
    if w:
        ctx.add_warning(*w)
    _judge_output(ctx, rc, v["mesh_inc"], "메시 변환")


def copy_files(sources: list[str], dst_dir: str, *, checkpoint: Any = None, log: Any = None) -> list[str]:
    """sources → dst_dir(이름 그대로). 복사한 이름 목록."""
    names = []
    os.makedirs(dst_dir, exist_ok=True)
    for src in sources:
        n = os.path.basename(src)
        copy_file(src, os.path.join(dst_dir, n), checkpoint=checkpoint)
        if log is not None:
            log(f"복사 {src} → {os.path.basename(dst_dir)}/{n}")
        names.append(n)
    return names


def _copy_into(ctx: Any, inp: str, sources: list[str]) -> list[str]:
    ctx.backup([os.path.join(inp, os.path.basename(x)) for x in sources])
    return copy_files(sources, inp, checkpoint=ctx.checkpoint, log=ctx.log)


def assembly_sources(settings: Any, assem: str) -> tuple[list[str], list[str]]:
    """조립 폴더 직계 `*.rad`·`*.inc` 중 eps_mesh·include 기준본이 아닌 것(phase3 §11.4 ①) → (원본 경로, 폴더 목록)."""
    inc = settings.predict.mesh_include_name
    listing = sorted(os.listdir(assem))
    srcs = [os.path.join(assem, n) for n in listing
            if n.lower().endswith((".rad", ".inc")) and not is_mesh_file(n) and n.lower() != inc.lower()
            and os.path.isfile(os.path.join(assem, n))]
    return srcs, listing


def assemble_into(settings: Any, assem: str, new_inc: str, dst: str, *, checkpoint: Any = None,
                  log: Any = None) -> tuple[str, list[tuple[str, str]]]:
    """RAD_ASSEMBLE ①~④(phase3 §11.4): 조립 폴더 사본 + 새 include → dst. (starter, 경고 목록). dst는 비어 있어야 한다
    (호출자가 _backup으로 비움). 일괄 예측 m_3도 같은 규칙."""
    pr = settings.predict
    inc = pr.mesh_include_name
    srcs, listing = assembly_sources(settings, assem)
    if not os.path.isfile(new_inc) or os.path.getsize(new_inc) == 0:
        raise StepFailure("OUTPUT_MISSING", f"새 메시 include({inc})가 없습니다 — 형상 갱신·메시 변환 결과를 확인하세요")
    names = copy_files(srcs, dst, checkpoint=checkpoint, log=log) + copy_files([new_inc], dst, checkpoint=checkpoint, log=log)
    warnings: list[tuple[str, str]] = []
    if not any(n.lower() == inc.lower() for n in listing):
        warnings.append(("MESH_INCLUDE_NOT_IN_ASSEM",
                         f"조립 폴더에 {inc} 기준본이 없습니다 — starter가 이 include를 쓰는지 확인하세요"))
    starters = [n for n in names if fnmatch.fnmatch(n, pr.starter_glob) and not is_mesh_file(n)]
    if len(starters) != 1:
        raise StepFailure("INPUT_INVALID", f"starter({pr.starter_glob})가 정확히 1개여야 합니다(현재 {len(starters)}개)")
    return starters[0], warnings


def _assemble_parametric(ctx: Any, inp: str) -> str:
    """RAD_ASSEMBLE(parametric, phase3 §11.4): 조립 폴더 사본(eps_mesh·include 기준본 제외) + 새 include → INPUT."""
    _ps, S = require_param_set(ctx)
    inc = ctx.settings.predict.mesh_include_name
    starter, warnings = assemble_into(ctx.settings, os.path.join(S, "radioss_assem"), os.path.join(_geom(ctx), inc), inp,
                                      checkpoint=ctx.checkpoint, log=ctx.log)
    for w in warnings:
        ctx.add_warning(*w)
    return starter


def mesh_only_into(settings: Any, geom: str, dst: str, *, checkpoint: Any = None, log: Any = None) -> str:
    """mesh_only RAD_ASSEMBLE(phase3 §14.4): geom 직계 `*.rad`·`*.inc` → dst(복사만). starter = SimLab 메시 이름."""
    mesh = settings.predict.simlab_mesh_name
    src = os.path.join(geom, mesh)
    if not os.path.isfile(src) or os.path.getsize(src) == 0:
        raise StepFailure("OUTPUT_MISSING", f"형상 메시({mesh})가 없습니다 — 형상 갱신 결과를 확인하세요")
    srcs = [os.path.join(geom, n) for n in sorted(os.listdir(geom))
            if n.lower().endswith((".rad", ".inc")) and os.path.isfile(os.path.join(geom, n))]
    copy_files(srcs, dst, checkpoint=checkpoint, log=log)
    return mesh


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
        # 원본 폴더는 읽기만(복사 원천). 직계 *.rad·*.inc 전부 — eps_mesh*도 starter가 include할 수 있어 복사(D3-44)
        plan = check_prepared(ctx)
        _copy_into(ctx, inp, plan.files)
        ctx.patch_result({"starter": plan.starter})
        return
    if template_kind(ctx) == MESH_ONLY:  # phase3 §14.4: 복사만, rad_assemble·csv 무관
        starter = mesh_only_into(ctx.settings, _geom(ctx), inp, checkpoint=ctx.checkpoint, log=ctx.log)
        ctx.patch_result({"starter": starter})
        return
    starter = _assemble_parametric(ctx, inp)
    if ctx.settings.commands.rad_assemble is not None:
        ctx.run_local("rad_assemble", {"work_dir": P, "starter": os.path.join(inp, starter), "input_dir": inp}, cwd=inp)
    ctx.patch_result({"starter": starter})
