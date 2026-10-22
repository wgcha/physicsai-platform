"""샘플 1개 생성 공용(geometry-engine.md §7.3.6) — ①-3 DOE run·④ 일괄 예측 run이 같이 쓴다.

레이아웃(`RunLayout`): LEGACY(④ 일괄 run) = R/options.json · m_1/{values.json, native_params.xml, update/} ·
m_2/{morph/, check/, <mesh_include_name>} · m_3/(조립) · SKIPPED.json. FLAT(①-3 native DOE run, GE-C13) = R 직계 조립 사본(해석 입력) ·
R/_paicad/{options.json, values.json, native_params.xml, update/, morph/, check/, <mesh_include_name>} · SKIPPED.json — 조립은
R/_paicad/assembly에서 하고(3S props apply가 조립 폴더를 재귀로 읽으므로 보조 파일과 분리) 성공 뒤 R 직계로 옮긴다.
paicad 호출은 `paicad_run`이 설정돼 있으면 1회, 없으면 update → morph → check 순차. 실패(보고 FAIL)는 SKIPPED.json을 쓰고
`StepFailure(code, 한국어 문구)`로 알린다(호출자가 run 실패로 기록). 플랫폼 오류(실행 파일 없음·시간 초과)는 SKIPPED.json 없이 그대로.

단계 3S(§11.1): 쉘 두께 값(`shell`)이 있으면 조립 뒤 `props apply`를 조립 사본(LEGACY m_3, FLAT 조립 임시 폴더)에 적용(작업 폴더는 R 밖 —
DG_SCAN이 R 아래 starter를 세므로). 형상 값이 없으면(`geometry=False`, 쉘 두께 전용) paicad update·morph·check를 생략하고
기준 메시를 그대로 조립한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json, write_text
from physicsai_core.geometry.judge import Verdict
from physicsai_core.geometry.native_files import RUN_AUX_DIR, native_params_xml, skipped_document, values_document
from physicsai_core.geometry.options import usage_document

from .geometry_asm import NODE_PATCH
from .geometry_native import NativeInputs, native_inputs, run_paicad  # noqa: F401 (재노출)

M1, M2, M3 = "m_1", "m_2", "m_3"
SKIPPED_JSON = "SKIPPED.json"


@dataclass(frozen=True)
class RunLayout:
    """run 폴더 R 기준 하위 경로(§7.3.6). 빈 문자열 = R 자체. stage = 조립 임시 폴더(None = inputs에 바로 조립)."""
    meta: str    # options.json
    m1: str      # values.json·native_params.xml·update/
    m2: str      # morph/·check/·<mesh_include_name>·shell_files/
    inputs: str  # 해석 입력(조립 사본) 최종 위치
    stage: str | None = None

    def at(self, R: str, which: str) -> str:
        rel = getattr(self, which) or ""
        return os.path.join(R, *rel.split("/")) if rel else R

    def report_rel(self, step: str, names: dict[str, str]) -> str | None:
        """SKIPPED.json `report`(R 기준 상대). names = {update|morph|check: 보고 파일 이름}."""
        if step not in names:
            return None
        base = self.m1 if step == "update" else self.m2
        return "/".join(x for x in (base, step, names[step]) if x)


LEGACY = RunLayout("", M1, M2, M3)
FLAT = RunLayout(RUN_AUX_DIR, RUN_AUX_DIR, RUN_AUX_DIR, "", f"{RUN_AUX_DIR}/assembly")
REPORT_NAMES = {"update": "update.json", "morph": "morph.json", "check": "check.json"}


def _skipped(R: str, v: Verdict, step: str, engine_version: str | None, baseline_id: str | None = None,
             layout: RunLayout = LEGACY) -> None:
    doc = skipped_document(v.code or "GEOM_INTERNAL", v.english, v.step or step, layout.report_rel(v.step or step, REPORT_NAMES),
                           engine_version, v.category)
    if baseline_id is not None:
        doc["baseline_id"] = baseline_id  # 4B: run 메타(§7.3.8)
    write_json(os.path.join(R, SKIPPED_JSON), doc)


def write_no_cover(R: str, engine_version: str | None, baseline_hint: str | None = None) -> None:
    """샘플 배정 실패(§7.3.8 BASELINE_NO_COVER) → SKIPPED.json(보조 산출물·조립 사본 없음)."""
    from physicsai_core.geometry.messages import korean_message

    doc = skipped_document("BASELINE_NO_COVER", "no baseline covers the sample values", "assign", None, engine_version)
    doc["message"] = korean_message("BASELINE_NO_COVER", None)
    doc["baseline_id"] = baseline_hint
    os.makedirs(R, exist_ok=True)
    write_json(os.path.join(R, SKIPPED_JSON), doc)


def write_sample_inputs(R: str, values: dict[str, float], source: dict[str, Any], opts: dict[str, Any], nominals: dict[str, float],
                        engine_version: str | None, extra: dict[str, Any] | None = None,
                        xml_values: dict[str, float] | None = None, layout: RunLayout = LEGACY) -> str:
    """options.json · values.json · native_params.xml 작성(LEGACY: R·m_1, FLAT: R/_paicad) → values.json 경로. 값은 반올림하지 않는다(GE-9).
    values = paicad가 읽는 형상 값(그 baseline 원 이름), xml_values = 샘플 표 추출용 값(생략 = values; 쉘 두께·공통 이름·학습 입력 열)."""
    m1 = layout.at(R, "m1")
    write_json(os.path.join(layout.at(R, "meta"), "options.json"), usage_document(opts, engine_version))
    vj = os.path.join(m1, "values.json")
    write_json(vj, values_document(values, source["kind"], source.get("id"), engine_version, source.get("doe_no"), extra))
    write_text(os.path.join(m1, "native_params.xml"), native_params_xml(values if xml_values is None else xml_values, nominals))
    return vj


def generate_sample(x: Any, settings: Any, inp: NativeInputs, R: str, *, engine_version: str | None, assemble: bool = True,
                    geometry: bool = True, shell: dict[str, float] | None = None, props_json: str | None = None,
                    props_work: str | None = None, baseline_id: str | None = None,
                    thickness_doc: dict[str, Any] | None = None, layout: RunLayout = LEGACY) -> dict[str, Any]:
    """values.json이 준비된 상태에서 paicad를 실행하고 조립(layout.inputs)까지 한다. 반환 {"starter"} (assemble=False면 starter 없음).
    geometry=False: 형상 값 없음(쉘 두께 전용) — paicad 형상 단계 생략, 기준 메시 그대로 조립. shell: 쉘 두께 값(조립 사본에 props apply,
    props_json = 세트 props.json, props_work = R 밖 작업 폴더). layout: LEGACY(m_1~m_3, ④ 일괄) | FLAT(①-3 DOE, GE-C13)."""
    kw = {"engine_version": engine_version, "assemble": assemble, "shell": shell, "props_json": props_json, "props_work": props_work,
          "baseline_id": baseline_id, "layout": layout}
    if not geometry:
        return _shell_only_sample(x, settings, inp, R, **kw)  # type: ignore[arg-type]
    if inp.kind == "shell":  # 쉘 판금 비드(shell-morph.md §8.2·§8.3)
        return _shell_bead_sample(x, settings, inp, R, thickness_doc=thickness_doc, **kw)  # type: ignore[arg-type]
    m1, m2 = layout.at(R, "m1"), layout.at(R, "m2")
    upd, mor, chk = os.path.join(m1, "update"), os.path.join(m2, "morph"), os.path.join(m2, "check")
    matched = inp.matched  # 조립 매칭 세트(방식 M, asm-match.md §5.4): include 파일 대신 node_patch.npz를 내고 asm write로 조립한다
    inc = settings.predict.mesh_include_name
    out_inc = os.path.join(m2, inc)  # 방식 L만 쓴다(매칭 세트는 이 이름의 파일을 만들지도 찾지도 않는다)
    patch = os.path.join(m2, NODE_PATCH)
    v = {**inp.base_values(settings), "options_json": os.path.join(layout.at(R, "meta"), "options.json"),
         "values_json": os.path.join(m1, "values.json"), "update_dir": upd, "morph_dir": mor, "check_dir": chk}
    v.update({"out_patch": patch} if matched else {"out_inc": out_inc})
    _require_no_skipped(R)
    uj, mj, cj = (os.path.join(d, n) for d, n in ((upd, "update.json"), (mor, "morph.json"), (chk, "check.json")))
    morphed = os.path.join(mor, "node_xyz.npz" if matched else "morphed.inc")
    result = patch if matched else out_inc
    if settings.commands.paicad_run is not None:
        steps: list[tuple[str, str, str, list[str], list[str], str | None]] = [
            ("paicad_run", "run", os.path.join(chk, "run.json"),
             [os.path.join(upd, "sample.brep"), morphed, cj, result], [upd, mor, chk, result], None)]
    else:
        steps = [("paicad_update", "update", uj, [os.path.join(upd, "sample.brep")], [upd], upd),
                 ("paicad_morph", "morph", mj, [morphed], [mor], mor),
                 ("paicad_check", "check", cj, [result], [chk, result], chk)]
    for key, step, report, success, backup, cwd in steps:
        verdict = run_paicad(x, settings, key, v, cwd=cwd or layout.at(R, "meta"), report=report, success=success, backup=backup,
                             body_map=inp.body_map, log_dir=os.path.dirname(report))
        if not verdict.ok:
            _skipped(R, verdict, step if step != "run" else "update", engine_version, baseline_id, layout)
            raise StepFailure(verdict.code or "GEOM_INTERNAL", verdict.message or "형상 생성 실패")
    if not assemble:
        return {"starter": None}
    dst = _assembly_dir(x, R, layout)
    if matched:
        starter = _assemble_matched(x, settings, inp, R, patch, dst, m2, engine_version, baseline_id, layout)
        warns: list[tuple[str, str]] = []
    else:
        from .stage4_predict.predict_inputs import assemble_into  # 지연 import: stage4_predict가 이 모듈을 쓴다

        starter, warns = assemble_into(settings, inp.assem_dir, out_inc, dst, checkpoint=x.check)
    for w in warns:
        x.warn(*w)
    _apply_shell(x, settings, R, dst, shell, props_json, props_work, engine_version, baseline_id, layout)
    _promote(x, R, dst, layout)
    return {"starter": starter}


def _assemble_matched(x: Any, settings: Any, inp: NativeInputs, R: str, patch: str | None, dst: str, work: str,
                      engine_version: str | None, baseline_id: str | None, layout: RunLayout) -> str:
    """매칭 세트 조립(§5.4): `paicad asm write`(패치 있으면 좌표 줄 갱신, 없으면 바이트 동일 사본) → dst에 include 트리 배치.
    실패는 SKIPPED.json(step "assemble") + StepFailure."""
    from .geometry_asm import WRITE_DIR, assemble_matched

    try:
        starter, verdict = assemble_matched(x, settings, inp, patch, dst, os.path.join(work, WRITE_DIR))
    except StepFailure as exc:
        doc = skipped_document(exc.code, exc.message, "assemble", None, engine_version)
        if baseline_id is not None:
            doc["baseline_id"] = baseline_id
        write_json(os.path.join(R, SKIPPED_JSON), doc)
        raise
    if not verdict.ok:
        _skipped(R, verdict, "assemble", engine_version, baseline_id, layout)
        raise StepFailure(verdict.code or "GEOM_INTERNAL", verdict.message or "조립 사본 쓰기 실패")
    return starter


def write_cushion_rad(x: Any, settings: Any, inp: NativeInputs, R: str, *, engine_version: str | None, geometry: bool = True,
                      baseline_id: str | None = None) -> str:
    """④ 일괄 쿠션 입력(input-kind.md §4.2): `generate_sample(assemble=False)` 뒤 `paicad cushion write` →
    `R/m_1/{simlab_mesh_name}`(`--out-dir R/m_2/cushion`). include = 모핑 PASS(`R/m_2/<mesh_include_name>`), 형상 값 없으면 기준본.
    실패는 SKIPPED.json(step "cushion") + StepFailure(그 run만 생성 실패). 반환 = 하위 예측 입력 파일 경로."""
    from . import geometry_cushion as cu

    m1, m2 = (os.path.join(R, d) for d in (M1, M2))
    rad = os.path.join(m1, settings.predict.simlab_mesh_name)
    if inp.matched:  # 방식 M: include 파일 대신 모핑 PASS 노드 패치(형상 값이 없으면 공칭 — 패치 없음), asm-match.md §5.5
        inc, patch = "", (os.path.join(m2, NODE_PATCH) if geometry else None)
    else:
        inc, patch = (os.path.join(m2, settings.predict.mesh_include_name) if geometry else inp.baseline_inc), None
    v = cu.write_cushion(x, settings, inp, cushion_inc=inc, cushion_dir=os.path.join(m2, cu.CUSHION_DIR), cushion_rad=rad, node_patch=patch)
    if not v.ok:
        doc = skipped_document(v.code or "GEOM_INTERNAL", v.english, "cushion", f"{M2}/{cu.CUSHION_DIR}/{cu.CUSHION_JSON}",
                               engine_version, v.category)
        if baseline_id is not None:
            doc["baseline_id"] = baseline_id
        write_json(os.path.join(R, SKIPPED_JSON), doc)
        raise StepFailure(v.code or "GEOM_INTERNAL", v.message or "쿠션 입력 rad 쓰기 실패")
    return rad


def _require_no_skipped(R: str) -> None:
    if os.path.lexists(os.path.join(R, SKIPPED_JSON)):
        raise StepFailure("INTERNAL_ERROR", "이전 시도의 SKIPPED.json이 남아 있습니다")  # 호출자가 R을 _backup으로 비운 뒤에만 호출


def _assembly_dir(x: Any, R: str, layout: RunLayout) -> str:
    """조립할 빈 폴더(LEGACY m_3, FLAT R/_paicad/assembly). 이전 내용은 `_backup`으로(삭제 대신 이동)."""
    dst = layout.at(R, "stage") if layout.stage else layout.at(R, "inputs")
    if os.path.isdir(dst) and os.listdir(dst):
        backup_path(x, dst)
    os.makedirs(dst, exist_ok=True)
    return dst


def _promote(x: Any, R: str, stage: str, layout: RunLayout) -> None:
    """FLAT: 조립 임시 폴더 내용 → R 직계(해석 입력). 같은 이름이 R에 있으면 그것을 먼저 `_backup`으로.
    빈 임시 폴더는 남긴다(삭제 호출 금지 규칙 — DG_SCAN·SCX가 `_paicad`를 보지 않으므로 무해)."""
    if not layout.stage:
        return
    dst_root = layout.at(R, "inputs")
    for n in sorted(os.listdir(stage)):
        dst = os.path.join(dst_root, n)
        if os.path.lexists(dst):
            backup_path(x, dst)
        os.replace(os.path.join(stage, n), dst)


def _apply_shell(x: Any, settings: Any, R: str, m3: str, shell: dict[str, float] | None, props_json: str | None,
                 props_work: str | None, engine_version: str | None, baseline_id: str | None = None,
                 layout: RunLayout = LEGACY) -> None:
    """쉘 두께 값이 있으면 조립 사본(m3 = INPUT 복사본)에 props apply. 실패 → SKIPPED.json(step "props") + StepFailure."""
    if not shell:
        return
    from .geometry_props import apply

    if not props_json or not props_work:
        raise StepFailure("INTERNAL_ERROR", "쉘 두께 적용 경로가 없습니다")
    v = apply(x, settings, m3, shell, props_json, props_work, engine_version)
    if not v.ok:
        backup_path(x, m3)  # 두께가 적용되지 않은 조립본을 남기지 않는다(DG_SCAN이 starter로 세지 않게, 삭제 대신 이동)
        _skipped(R, v, "props", engine_version, baseline_id, layout)
        raise StepFailure(v.code or "GEOM_INTERNAL", v.message or "쉘 두께 적용 실패")


def _shell_only_sample(x: Any, settings: Any, inp: NativeInputs, R: str, *, engine_version: str | None, assemble: bool,
                       shell: dict[str, float] | None, props_json: str | None, props_work: str | None,
                       baseline_id: str | None = None, layout: RunLayout = LEGACY) -> dict[str, Any]:
    """형상 값 없는 샘플(§11.1·§7.3.4): 조립 폴더 사본 + 기준 메시 그대로 → 조립 사본, 쉘 두께 적용."""
    _require_no_skipped(R)
    if not assemble:
        return {"starter": None}
    from .stage4_predict.predict_inputs import assemble_into

    dst = _assembly_dir(x, R, layout)
    starter, warns = assemble_into(settings, inp.assem_dir, inp.baseline_inc, dst, checkpoint=x.check)
    for w in warns:
        x.warn(*w)
    _apply_shell(x, settings, R, dst, shell, props_json, props_work, engine_version, baseline_id, layout)
    _promote(x, R, dst, layout)
    return {"starter": starter}


def _shell_bead_sample(x: Any, settings: Any, inp: NativeInputs, R: str, *, engine_version: str | None, assemble: bool,
                       shell: dict[str, float] | None, props_json: str | None, props_work: str | None, baseline_id: str | None,
                       thickness_doc: dict[str, Any] | None, layout: RunLayout = LEGACY) -> dict[str, Any]:
    """쉘 비드 샘플(SM §8.2): shell update→morph→check(또는 shell run) → 조립 사본 + PASS 사본 덮어쓰기 → 3S props apply.
    쉘 형상 check FAIL이면 props apply를 하지 않는다(실패 우선 = 쉘 코드, §8.4)."""
    from physicsai_core.geometry.shell_native import SHELL_FILES_DIR

    from .geometry_shell import CHECK_JSON, MORPH_JSON, UPDATE_JSON, assemble_copy, overlay, run_sample, thickness_for

    _require_no_skipped(R)
    if thickness_doc is None:
        thickness_doc = thickness_for(settings, inp, props_json, shell)
    v, step, rels = run_sample(x, settings, inp, R, thickness_doc=thickness_doc, layout=layout)
    if v is not None:
        st = step or "update"
        rep = layout.report_rel(st, {"update": UPDATE_JSON, "morph": MORPH_JSON, "check": CHECK_JSON})
        doc = skipped_document(v.code or "GEOM_INTERNAL", v.english, st, rep, engine_version, v.category)
        if baseline_id is not None:
            doc["baseline_id"] = baseline_id
        write_json(os.path.join(R, SKIPPED_JSON), doc)
        raise StepFailure(v.code or "GEOM_INTERNAL", v.message or "쉘 형상 생성 실패")
    if not assemble:
        return {"starter": None}
    dst = _assembly_dir(x, R, layout)
    starter = assemble_copy(settings, inp.assem_dir, dst, checkpoint=x.check)
    overlay(os.path.join(layout.at(R, "m2"), SHELL_FILES_DIR), rels, dst, checkpoint=x.check)
    _apply_shell(x, settings, R, dst, shell, props_json, props_work, engine_version, baseline_id, layout)
    _promote(x, R, dst, layout)
    return {"starter": starter, "shell_files": rels}


def backup_path(x: Any, path: str) -> None:
    """`_backup`으로 이동(병렬 실행기에서는 파일 시스템 잠금 안에서)."""
    pool = getattr(x, "pool", None)
    if pool is None:
        x.ctx.backup([path])
    else:
        with pool.fs_lock:
            x.ctx.backup([path])
