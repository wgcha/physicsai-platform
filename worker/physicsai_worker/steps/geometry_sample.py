"""샘플 1개 생성 공용(geometry-engine.md §7.3.6) — ①-3 DOE run·④ 일괄 예측 run이 같이 쓴다.

R/options.json · m_1/{values.json, native_params.xml, update/} · m_2/{morph/, check/, <mesh_include_name>} · m_3/(조립) · SKIPPED.json.
paicad 호출은 `paicad_run`이 설정돼 있으면 1회, 없으면 update → morph → check 순차. 실패(보고 FAIL)는 SKIPPED.json을 쓰고
`StepFailure(code, 한국어 문구)`로 알린다(호출자가 run 실패로 기록). 플랫폼 오류(실행 파일 없음·시간 초과)는 SKIPPED.json 없이 그대로.

단계 3S(§11.1): 쉘 두께 값(`shell`)이 있으면 m_3 조립 뒤 `props apply`를 m_3(INPUT 복사본)에 적용(작업 폴더는 R 밖 —
DG_SCAN이 R 아래 starter를 세므로). 형상 값이 없으면(`geometry=False`, 쉘 두께 전용) paicad update·morph·check를 생략하고
기준 메시를 그대로 조립한다.
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


def _skipped(R: str, v: Verdict, step: str, engine_version: str | None, baseline_id: str | None = None) -> None:
    doc = skipped_document(v.code or "GEOM_INTERNAL", v.english, v.step or step, STEP_REPORT_REL.get(v.step or step), engine_version,
                           v.category)
    if baseline_id is not None:
        doc["baseline_id"] = baseline_id  # 4B: run 메타(§7.3.8)
    write_json(os.path.join(R, SKIPPED_JSON), doc)


def write_no_cover(R: str, engine_version: str | None, baseline_hint: str | None = None) -> None:
    """샘플 배정 실패(§7.3.8 BASELINE_NO_COVER) → SKIPPED.json(m_1·m_2·m_3 없음)."""
    from physicsai_core.geometry.messages import korean_message

    doc = skipped_document("BASELINE_NO_COVER", "no baseline covers the sample values", "assign", None, engine_version)
    doc["message"] = korean_message("BASELINE_NO_COVER", None)
    doc["baseline_id"] = baseline_hint
    os.makedirs(R, exist_ok=True)
    write_json(os.path.join(R, SKIPPED_JSON), doc)


def write_sample_inputs(R: str, values: dict[str, float], source: dict[str, Any], opts: dict[str, Any], nominals: dict[str, float],
                        engine_version: str | None, extra: dict[str, Any] | None = None,
                        xml_values: dict[str, float] | None = None) -> str:
    """R/options.json · m_1/values.json · m_1/native_params.xml 작성 → values.json 경로. 값은 반올림하지 않는다(GE-9).
    values = paicad가 읽는 형상 값(그 baseline 원 이름), xml_values = 샘플 표 추출용 값(생략 = values; 쉘 두께·공통 이름·학습 입력 열)."""
    m1 = os.path.join(R, M1)
    write_json(os.path.join(R, "options.json"), usage_document(opts, engine_version))
    vj = os.path.join(m1, "values.json")
    write_json(vj, values_document(values, source["kind"], source.get("id"), engine_version, source.get("doe_no"), extra))
    write_text(os.path.join(m1, "native_params.xml"), native_params_xml(values if xml_values is None else xml_values, nominals))
    return vj


def generate_sample(x: Any, settings: Any, inp: NativeInputs, R: str, *, engine_version: str | None, assemble: bool = True,
                    geometry: bool = True, shell: dict[str, float] | None = None, props_json: str | None = None,
                    props_work: str | None = None, baseline_id: str | None = None,
                    thickness_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """R/m_1 입력이 준비된 상태에서 paicad를 실행하고 m_3 조립까지 한다. 반환 {"starter","elapsed"} (assemble=False면 starter 없음).
    geometry=False: 형상 값 없음(쉘 두께 전용) — paicad 형상 단계 생략, 기준 메시 그대로 조립. shell: 쉘 두께 값(m_3에 props apply,
    props_json = 세트 props.json, props_work = R 밖 작업 폴더)."""
    if not geometry:
        return _shell_only_sample(x, settings, inp, R, engine_version=engine_version, assemble=assemble, shell=shell,
                                  props_json=props_json, props_work=props_work, baseline_id=baseline_id)
    if inp.kind == "shell":  # 쉘 판금 비드(shell-morph.md §8.2·§8.3)
        return _shell_bead_sample(x, settings, inp, R, engine_version=engine_version, assemble=assemble, shell=shell,
                                  props_json=props_json, props_work=props_work, baseline_id=baseline_id, thickness_doc=thickness_doc)
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
            _skipped(R, verdict, step if step != "run" else "update", engine_version, baseline_id)
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
        _apply_shell(x, settings, R, m3, shell, props_json, props_work, engine_version, baseline_id)
    return {"starter": starter}


def _apply_shell(x: Any, settings: Any, R: str, m3: str, shell: dict[str, float] | None, props_json: str | None,
                 props_work: str | None, engine_version: str | None, baseline_id: str | None = None) -> None:
    """쉘 두께 값이 있으면 m_3(INPUT 복사본)에 props apply. 실패 → SKIPPED.json(step "props") + StepFailure."""
    if not shell:
        return
    from .geometry_props import apply

    if not props_json or not props_work:
        raise StepFailure("INTERNAL_ERROR", "쉘 두께 적용 경로가 없습니다")
    v = apply(x, settings, m3, shell, props_json, props_work, engine_version)
    if not v.ok:
        backup_path(x, m3)  # 두께가 적용되지 않은 조립본을 남기지 않는다(DG_SCAN이 starter로 세지 않게, 삭제 대신 이동)
        _skipped(R, v, "props", engine_version, baseline_id)
        raise StepFailure(v.code or "GEOM_INTERNAL", v.message or "쉘 두께 적용 실패")


def _shell_only_sample(x: Any, settings: Any, inp: NativeInputs, R: str, *, engine_version: str | None, assemble: bool,
                       shell: dict[str, float] | None, props_json: str | None, props_work: str | None,
                       baseline_id: str | None = None) -> dict[str, Any]:
    """형상 값 없는 샘플(§11.1·§7.3.4): 조립 폴더 사본 + 기준 메시 그대로 → m_3, 쉘 두께 적용."""
    m3 = os.path.join(R, M3)
    if os.path.lexists(os.path.join(R, SKIPPED_JSON)):
        raise StepFailure("INTERNAL_ERROR", "이전 시도의 SKIPPED.json이 남아 있습니다")
    if not assemble:
        return {"starter": None}
    from .stage4_predict.predict_inputs import assemble_into

    if os.path.isdir(m3) and os.listdir(m3):
        backup_path(x, m3)
    os.makedirs(m3, exist_ok=True)
    starter, warns = assemble_into(settings, inp.assem_dir, inp.baseline_inc, m3, checkpoint=x.check)
    for w in warns:
        x.warn(*w)
    _apply_shell(x, settings, R, m3, shell, props_json, props_work, engine_version, baseline_id)
    return {"starter": starter}


def _shell_bead_sample(x: Any, settings: Any, inp: NativeInputs, R: str, *, engine_version: str | None, assemble: bool,
                       shell: dict[str, float] | None, props_json: str | None, props_work: str | None, baseline_id: str | None,
                       thickness_doc: dict[str, Any] | None) -> dict[str, Any]:
    """쉘 비드 샘플(SM §8.2): shell update→morph→check(또는 shell run) → m_3 = 조립 사본 + PASS 사본 덮어쓰기 → 3S props apply.
    쉘 형상 check FAIL이면 props apply를 하지 않는다(실패 우선 = 쉘 코드, §8.4)."""
    from .geometry_shell import STEP_REPORT_REL as SHELL_REPORT_REL
    from .geometry_shell import assemble_copy, overlay, run_sample

    from .geometry_shell import thickness_for

    if os.path.lexists(os.path.join(R, SKIPPED_JSON)):
        raise StepFailure("INTERNAL_ERROR", "이전 시도의 SKIPPED.json이 남아 있습니다")
    if thickness_doc is None:
        thickness_doc = thickness_for(settings, inp, props_json, shell)
    v, step, rels = run_sample(x, settings, inp, R, thickness_doc=thickness_doc)
    if v is not None:
        st = step or "update"
        doc = skipped_document(v.code or "GEOM_INTERNAL", v.english, st, SHELL_REPORT_REL.get(st), engine_version, v.category)
        if baseline_id is not None:
            doc["baseline_id"] = baseline_id
        write_json(os.path.join(R, SKIPPED_JSON), doc)
        raise StepFailure(v.code or "GEOM_INTERNAL", v.message or "쉘 형상 생성 실패")
    if not assemble:
        return {"starter": None}
    m3 = os.path.join(R, M3)
    if os.path.isdir(m3) and os.listdir(m3):
        backup_path(x, m3)
    os.makedirs(m3, exist_ok=True)
    starter = assemble_copy(settings, inp.assem_dir, m3, checkpoint=x.check)
    overlay(os.path.join(R, M2, "shell_files"), rels, m3, checkpoint=x.check)
    _apply_shell(x, settings, R, m3, shell, props_json, props_work, engine_version, baseline_id)
    return {"starter": starter, "shell_files": rels}


def backup_path(x: Any, path: str) -> None:
    """`_backup`으로 이동(병렬 실행기에서는 파일 시스템 잠금 안에서)."""
    pool = getattr(x, "pool", None)
    if pool is None:
        x.ctx.backup([path])
    else:
        with pool.fs_lock:
            x.ctx.backup([path])
