"""run별 입력 생성 공용 체인(phase3 §23.6 S18, D3-66): m_1 형상 → m_2 include → m_3 조립.

④ 일괄 예측 BP_GEN(`batch._gen_one`)과 ① 학습 DOE 플랫폼 생성(`doe_platform_gen.gen_platform`)이 같은 함수를 쓴다.
판정·경고 규칙은 단일 예측(§11.4)과 같다(`predict_inputs.judge_output`·`mesh_preflight`·`mesh_log_warning`·`assemble_into`).

교체 경계(native 형상 엔진, 프로젝트 문서 contracts/geometry-engine.md):
- `geometry_update` — 형상 생성 한 곳. 출력 계약 = `work_dir/{predict.simlab_mesh_name}` 경로 1개.
- `build_run_inputs` — run 폴더 단위(m_1 → m_2 → m_3). 엔진별 구현 선택은 `select_engine` 한 곳(지금은 altair만).
형상 명령(`geom_update` 템플릿)을 실행하는 곳은 이 파일뿐이다(정적 검사 V3-S18-8).

runner = `ParallelRunner`(동시 실행) 또는 `CtxRunner`(단일 실행 어댑터): `run(template_key, values, *, cwd, outputs_to_backup)`
→ 종료코드, `warn(code, message)`, `last_line`, `check()`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .stage4_predict import predict_inputs as _pi

M1, M2, M3 = "m_1", "m_2", "m_3"
GEOM_TEMPLATE = "geom_update"
MESH_TEMPLATE = "mesh"


class CtxRunner:
    """단일 실행(ctx.run_local) 어댑터 — ParallelRunner와 같은 모양. 경고는 step 경고(ctx.add_warning)로."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    @property
    def last_line(self) -> str:
        return getattr(self.ctx, "last_line", "")

    def run(self, template_key: str, values: dict[str, str], *, cwd: str, outputs_to_backup: list[str] | None = None) -> int:
        return self.ctx.run_local(template_key, values, cwd=cwd, outputs_to_backup=outputs_to_backup, allow_nonzero_exit=True)

    def warn(self, code: str, message: str) -> None:
        self.ctx.add_warning(code, message)

    def check(self) -> None:
        self.ctx.checkpoint()


def _backup(runner: Any, paths: list[str]) -> None:
    """run 폴더 안 기존 산출물을 _backup으로(동시 실행이면 fs_lock 안에서 — _backup 폴더 이름 경합 방지)."""
    pool = getattr(runner, "pool", None)
    if pool is not None:
        with pool.fs_lock:
            runner.ctx.backup(paths)
    else:
        runner.ctx.backup(paths)


# ---- altair(SimLab·HyperMesh) 구현 ------------------------------------------------------------------


def _altair_geometry_update(runner: Any, settings: Any, *, work_dir: str, rendered_script: str, cad_file: str) -> str:
    simlab_mesh = os.path.join(work_dir, settings.predict.simlab_mesh_name)
    v = {"rendered_script": rendered_script, "cad_file": cad_file, "work_dir": work_dir, "simlab_mesh": simlab_mesh}
    rc = runner.run(GEOM_TEMPLATE, v, cwd=work_dir, outputs_to_backup=[simlab_mesh])
    w = _pi.judge_output(rc, simlab_mesh, "형상 갱신", runner.last_line)
    if w:
        runner.warn(*w)
    return simlab_mesh


def _altair_build_run_inputs(runner: Any, settings: Any, *, run_dir: str, cad_file_name: str, assem_dir: str | None,
                             assembly: bool) -> str:
    pr = settings.predict
    m1, m2, m3 = (os.path.join(run_dir, x) for x in (M1, M2, M3))
    # m_1: 형상 갱신·메싱(cwd m_1) — 성공 = {simlab_mesh_name}(§11.4)
    simlab_mesh = geometry_update(runner, settings, work_dir=m1, rendered_script=os.path.join(m1, pr.rendered_script_name),
                                  cad_file=os.path.join(m1, cad_file_name))
    if not assembly:
        return simlab_mesh  # mesh_only: m_1 메시가 곧 입력(§14.3 input_rel)
    if assem_dir is None:
        raise ValueError("assembly 입력 생성에는 조립 폴더가 필요합니다")
    if settings.commands.mesh is not None:  # m_2: HyperMesh include 변환(cwd m_2)
        os.makedirs(m2, exist_ok=True)
        renum_csv = os.path.join(assem_dir, pr.renum_csv_name)
        for w in _pi.mesh_preflight(settings, renum_csv):
            runner.warn(*w)
        mesh_inc = os.path.join(m2, pr.mesh_include_name)
        v = {"rendered_script": os.path.join(m1, pr.rendered_script_name), "cad_file": os.path.join(m1, cad_file_name),
             "work_dir": m2, "include_tcl": settings.resources.hypermesh_include_tcl, "simlab_mesh": simlab_mesh,
             "mesh_inc": mesh_inc, "renum_csv": renum_csv}
        log_batch = os.path.join(m2, _pi.LOG_BATCH)
        rc = runner.run(MESH_TEMPLATE, v, cwd=m2, outputs_to_backup=[mesh_inc, log_batch])
        text = ""
        if os.path.isfile(log_batch):
            with open(log_batch, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        w = _pi.mesh_log_warning(settings, text)
        if w:
            runner.warn(*w)
        w = _pi.judge_output(rc, mesh_inc, "메시 변환", runner.last_line)
        if w:
            runner.warn(*w)
        new_inc = mesh_inc
    else:  # MESH null: SimLab이 include를 직접 작성(cwd m_1)
        new_inc = os.path.join(m1, pr.mesh_include_name)
    # m_3: 조립 폴더 사본 + 새 include(RAD_ASSEMBLE ①~④). 재시도로 남은 이전 내용은 _backup(D3-36과 같은 이유)
    if os.path.isdir(m3) and os.listdir(m3):
        _backup(runner, [m3])
    os.makedirs(m3, exist_ok=True)
    _starter, warns = _pi.assemble_into(settings, assem_dir, new_inc, m3, checkpoint=runner.check)
    for w in warns:
        runner.warn(*w)
    return m3


@dataclass(frozen=True)
class Engine:
    """형상 엔진 구현 1개(교체 단위). geometry_update·build_run_inputs의 출력 계약은 모듈 함수와 같다."""

    name: str
    geometry_update: Callable[..., str]
    build_run_inputs: Callable[..., str]


ALTAIR = Engine("altair", _altair_geometry_update, _altair_build_run_inputs)


def select_engine(settings: Any, param_set: dict[str, Any] | None = None) -> Engine:
    """엔진 선택 한 곳(D3-66 보강). 지금은 altair(SimLab·HyperMesh 명령 템플릿)만 — native(paicad)는 후속."""
    return ALTAIR


# ---- 공개 경계 ---------------------------------------------------------------------------------------


def geometry_update(runner: Any, settings: Any, *, work_dir: str, rendered_script: str, cad_file: str) -> str:
    """형상 생성 경계(native 엔진 교체 지점, D3-66). 입력: work_dir 안의 렌더 스크립트·CAD 사본.
    출력: work_dir/{predict.simlab_mesh_name} 경로(판정 통과). 지금 = 템플릿 'geom_update'(SimLab -auto).
    실패 = StepFailure(EXIT_NONZERO|OUTPUT_MISSING), rc≠0 + 출력 있음 = 경고 EXIT_NONZERO_IGNORED(§11.4)."""
    return select_engine(settings).geometry_update(runner, settings, work_dir=work_dir, rendered_script=rendered_script,
                                                   cad_file=cad_file)


def build_run_inputs(runner: Any, settings: Any, *, run_dir: str, cad_file_name: str, assem_dir: str | None,
                     assembly: bool, param_set: dict[str, Any] | None = None) -> str:
    """m_1 geometry_update → (assembly) m_2 MESH(commands.mesh null이면 SimLab include) → m_3 assemble_into.
    반환 = 예측/해석 입력 경로(assembly: m_3 폴더, mesh_only: m_1/{simlab_mesh_name}) — ④ _gen_one과 같은 규칙.
    m_1에는 호출자가 CAD 사본·렌더 스크립트({predict.rendered_script_name})를 먼저 둔다."""
    return select_engine(settings, param_set).build_run_inputs(runner, settings, run_dir=run_dir, cad_file_name=cad_file_name,
                                                                assem_dir=assem_dir, assembly=assembly)


def mesh_preflight(settings: Any, renum_csv: str) -> list[tuple[str, str]]:
    """MESH 실행 전 확인(§11.4, 단일 예측과 같은 함수): include TCL 없음 → RESOURCE_MISSING, csv 없음 → 경고 목록."""
    return _pi.mesh_preflight(settings, renum_csv)


def aggregate_warnings(ctx: Any, outcomes: list[Any]) -> None:
    """run별 경고를 코드마다 1건으로(200 run이 같은 경고를 반복하지 않게)."""
    by_code: dict[str, list[tuple[str, str]]] = {}
    for o in outcomes:
        for code, msg in o.warnings:
            by_code.setdefault(code, []).append((o.item_id, msg))
    for code, items in by_code.items():
        keys = sorted({k for k, _ in items})
        ctx.add_warning(code, f"run {len(keys)}개({', '.join(keys[:5])}{' …' if len(keys) > 5 else ''}): {items[0][1]}"[:480])
