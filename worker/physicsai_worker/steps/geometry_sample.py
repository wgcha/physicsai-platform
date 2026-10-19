"""샘플 1개 생성 공용(geometry-engine.md §7.3.6) — ①-3 DOE run·④ 일괄 예측 run이 같이 쓴다.

R/options.json · m_1/{values.json, native_params.xml, update/} · m_2/{morph/, check/, <mesh_include_name>} · m_3/(조립) · SKIPPED.json.
paicad 호출은 `paicad_run`이 설정돼 있으면 1회, 없으면 update → morph → check 순차. 실패(보고 FAIL)는 SKIPPED.json을 쓰고
`StepFailure(code, 한국어 문구)`로 알린다(호출자가 run 실패로 기록). 플랫폼 오류(실행 파일 없음·시간 초과)는 SKIPPED.json 없이 그대로.
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json, write_text
from physicsai_core.geometry.judge import Verdict
from physicsai_core.geometry.native_files import native_params_xml, skipped_document, values_document
from physicsai_core.geometry.options import usage_document

from .geometry_native import NativeInputs, native_inputs, run_paicad  # noqa: F401 (재노출)

M1, M2, M3 = "m_1", "m_2", "m_3"
SKIPPED_JSON = "SKIPPED.json"
STEP_REPORT_REL = {"update": f"{M1}/update/update.json", "morph": f"{M2}/morph/morph.json", "check": f"{M2}/check/check.json"}


def _skipped(R: str, v: Verdict, step: str, engine_version: str | None) -> None:
    write_json(os.path.join(R, SKIPPED_JSON), skipped_document(
        v.code or "GEOM_INTERNAL", v.english, v.step or step, STEP_REPORT_REL.get(v.step or step), engine_version, v.category))


def write_sample_inputs(R: str, values: dict[str, float], source: dict[str, Any], opts: dict[str, Any], nominals: dict[str, float],
                        engine_version: str | None, extra: dict[str, Any] | None = None) -> str:
    """R/options.json · m_1/values.json · m_1/native_params.xml 작성 → values.json 경로. 값은 반올림하지 않는다(GE-9)."""
    m1 = os.path.join(R, M1)
    write_json(os.path.join(R, "options.json"), usage_document(opts, engine_version))
    vj = os.path.join(m1, "values.json")
    write_json(vj, values_document(values, source["kind"], source.get("id"), engine_version, source.get("doe_no"), extra))
    write_text(os.path.join(m1, "native_params.xml"), native_params_xml(values, nominals))
    return vj


def generate_sample(x: Any, settings: Any, inp: NativeInputs, R: str, *, engine_version: str | None, assemble: bool = True) -> dict[str, Any]:
    """R/m_1 입력이 준비된 상태에서 paicad를 실행하고 m_3 조립까지 한다. 반환 {"starter","elapsed"} (assemble=False면 starter 없음)."""
    m1, m2, m3 = (os.path.join(R, d) for d in (M1, M2, M3))
    upd, mor, chk = os.path.join(m1, "update"), os.path.join(m2, "morph"), os.path.join(m2, "check")
    inc = settings.predict.mesh_include_name
    out_inc = os.path.join(m2, inc)
    v = {**inp.base_values(settings), "options_json": os.path.join(R, "options.json"), "values_json": os.path.join(m1, "values.json"),
         "update_dir": upd, "morph_dir": mor, "check_dir": chk, "out_inc": out_inc}
    sj = os.path.join(R, SKIPPED_JSON)
    if os.path.lexists(sj):
        raise StepFailure("INTERNAL_ERROR", "이전 시도의 SKIPPED.json이 남아 있습니다")  # 호출자가 R을 _backup으로 비운 뒤에만 호출
    uj, mj, cj = (os.path.join(d, n) for d, n in ((upd, "update.json"), (mor, "morph.json"), (chk, "check.json")))
    if settings.commands.paicad_run is not None:
        steps: list[tuple[str, str, str, list[str], list[str], str | None]] = [
            ("paicad_run", "run", os.path.join(chk, "run.json"),
             [os.path.join(upd, "sample.brep"), os.path.join(mor, "morphed.inc"), cj, out_inc], [upd, mor, chk, out_inc], None)]
    else:
        steps = [("paicad_update", "update", uj, [os.path.join(upd, "sample.brep")], [upd], upd),
                 ("paicad_morph", "morph", mj, [os.path.join(mor, "morphed.inc")], [mor], mor),
                 ("paicad_check", "check", cj, [out_inc], [chk, out_inc], chk)]
    for key, step, report, success, backup, cwd in steps:
        verdict = run_paicad(x, settings, key, v, cwd=cwd or R, report=report, success=success, backup=backup, body_map=inp.body_map,
                             log_dir=os.path.dirname(report))
        if not verdict.ok:
            _skipped(R, verdict, step if step != "run" else "update", engine_version)
            raise StepFailure(verdict.code or "GEOM_INTERNAL", verdict.message or "형상 생성 실패")
    starter = None
    if assemble:
        from .stage4_predict.predict_inputs import assemble_into  # 지연 import: stage4_predict가 이 모듈을 쓴다


        if os.path.isdir(m3) and os.listdir(m3):
            backup_path(x, m3)
        os.makedirs(m3, exist_ok=True)
        starter, warns = assemble_into(settings, inp.assem_dir, out_inc, m3, checkpoint=x.check)
        for w in warns:
            x.warn(*w)
    return {"starter": starter}


def backup_path(x: Any, path: str) -> None:
    """`_backup`으로 이동(병렬 실행기에서는 파일 시스템 잠금 안에서)."""
    pool = getattr(x, "pool", None)
    if pool is None:
        x.ctx.backup([path])
    else:
        with pool.fs_lock:
            x.ctx.backup([path])
