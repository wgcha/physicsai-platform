"""쉘 판금(비드) 모핑 워커 공용(shell-morph.md §8): `paicad shell` 준비 체인·샘플 생성·m_3 조립 덮어쓰기.

- 준비(세트·DOE 1회): extract(`--assem-dir`, ①-1은 생략) → fixed-scan(`--features`) → tag. 출력 = `<base>/native/{extract,fixed,tag}`.
- 샘플(run마다): `paicad_shell_run`이 있으면 1회, 없으면 update → morph → check. PASS 사본 = `--out-files-dir`.
- m_3 조립: 조립 폴더 사본(기준 메시 교체 없음, 3S 두께 전용 세트와 같은 경로) → PASS 사본을 같은 상대 경로에 덮어쓰기 →
  3S 두께가 있으면 그 뒤 `props apply`(쉘 overlay가 반영된 사본 기준, §8.3). 원본 조립 폴더·SPDM은 건드리지 않는다.
- 실패(보고 FAIL)는 Verdict → 호출자가 step 실패·SKIPPED.json으로 처리. 한국어 문구는 messages.CODE_TABLE(SHELL_*).
이 모듈은 paicad·OCP를 import하지 않는다(파일·CLI 경계).
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json
from physicsai_core.geometry.judge import Verdict
from physicsai_core.geometry.shell_native import SHELL_FILES_DIR, THICKNESS_JSON, target_part_ids, thickness_document
from physicsai_core.stage4_predict.prepared_input import is_mesh_file

from .geometry_native import NativeInputs, run_paicad

SCAN_JSON, TAG_JSON = "shell_scan.json", "shell_tag.json"
UPDATE_JSON, MORPH_JSON, CHECK_JSON, RUN_JSON = "shell_update.json", "shell_morph.json", "shell_check.json", "shell_run.json"
FEATURES_JSON, XML = "shell_features.json", "parameter_extracted.xml"
SHELL_COMMANDS = ("paicad_shell_fixed_scan", "paicad_shell_extract", "paicad_shell_tag", "paicad_shell_update", "paicad_shell_morph",
                  "paicad_shell_check")


def require_shell_commands(settings: Any, *keys: str) -> None:
    missing = [k for k in (keys or SHELL_COMMANDS) if getattr(settings.commands, k, None) is None]
    if missing:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "쉘 형상 명령 템플릿이 설정되지 않았습니다: " + ", ".join(f"commands.{k}" for k in missing))


def extract(x: Any, settings: Any, *, cad_input: str, out_dir: str, options_json: str, assem_dir: str | None,
            body_map: str | None, cwd: str) -> Verdict:
    """`paicad shell extract` → out_dir/{parameter_extracted.xml, shell_features.json, features/}. assem_dir 없음 = ①-1(인자 쌍 생략)."""
    require_shell_commands(settings, "paicad_shell_extract")
    xml, fj = os.path.join(out_dir, XML), os.path.join(out_dir, FEATURES_JSON)
    values = {"cad_input": cad_input, "assem_dir": assem_dir or "", "options_json": options_json, "out_dir": out_dir}
    return run_paicad(x, settings, "paicad_shell_extract", values, cwd=cwd, report=fj, success=[xml],
                      backup=[xml, fj, os.path.join(out_dir, "features"), os.path.join(out_dir, "paicad.log")], body_map=body_map,
                      log_dir=out_dir)


def fixed_scan_and_tag(x: Any, settings: Any, inp: NativeInputs, options_json: str, cwd: str) -> tuple[Verdict, Verdict | None]:
    """NP_TAG(쉘) = fixed-scan(`--features`) → tag. 앞 단계 실패면 (실패, None)."""
    require_shell_commands(settings, "paicad_shell_fixed_scan", "paicad_shell_tag")
    F, T = inp.fixed_dir, inp.tag_dir
    v = run_paicad(x, settings, "paicad_shell_fixed_scan",
                   {"assem_dir": inp.assem_dir, "features_json": inp.features, "options_json": options_json, "out_dir": F},
                   cwd=cwd, report=os.path.join(F, SCAN_JSON), success=[os.path.join(F, "fixed_nodes.npz")], backup=[F], log_dir=F)
    if not v.ok:
        return v, None
    t = run_paicad(x, settings, "paicad_shell_tag", {**inp.base_values(settings), "options_json": options_json, "out_dir": T},
                   cwd=cwd, report=os.path.join(T, TAG_JSON), success=[os.path.join(T, "shell_tag_nodes.npz")], backup=[T],
                   body_map=inp.body_map, log_dir=T)
    return v, t


# ---- 조립 사본 + 덮어쓰기 ------------------------------------------------------------------------------------


def assemble_copy(settings: Any, assem: str, dst: str, *, checkpoint: Any = None, log: Any = None) -> str:
    """조립 폴더 직계 `*.rad`·`*.inc`(SimLab 메시 사본 eps_mesh* 제외, 기준 메시 포함) → dst. starter 이름(정확히 1개)."""
    pr = settings.predict
    names = []
    for n in sorted(os.listdir(assem)):
        src = os.path.join(assem, n)
        if n.lower().endswith((".rad", ".inc")) and not is_mesh_file(n) and os.path.isfile(src):
            copy_file(src, os.path.join(dst, n), checkpoint=checkpoint)
            names.append(n)
    if log is not None:
        log(f"조립 폴더 사본 {len(names)}개 → {os.path.basename(dst)}")
    starters = [n for n in names if fnmatch.fnmatch(n, pr.starter_glob)]
    if len(starters) != 1:
        raise StepFailure("INPUT_INVALID", f"starter({pr.starter_glob})가 정확히 1개여야 합니다(현재 {len(starters)}개)")
    return starters[0]


def _safe_rel(rel: Any) -> str:
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or ":" in rel \
            or ".." in rel.replace("\\", "/").split("/"):
        raise StepFailure("INPUT_INVALID", f"쉘 사본 파일 경로가 올바르지 않습니다: {rel!r}")
    return rel.replace("\\", "/")


def out_files(report: dict[str, Any] | None) -> list[str]:
    """check(또는 run) 보고의 `out_files`(PASS 사본 상대 경로) — 경로 탈출 거부."""
    return [_safe_rel(r) for r in (report or {}).get("out_files") or []]


def overlay(files_dir: str, rels: list[str], dst: str, *, checkpoint: Any = None, log: Any = None) -> int:
    """PASS 사본 `files_dir/<rel>` → 조립 사본 `dst/<rel>` 덮어쓰기(SM §8.3). 이 run이 만든 사본만 바꾼다."""
    for rel in rels:
        src = os.path.join(files_dir, *rel.split("/"))
        if not os.path.isfile(src):
            raise StepFailure("OUTPUT_MISSING", f"쉘 모핑 사본이 없습니다: {rel}")
        copy_file(src, os.path.join(dst, *rel.split("/")), checkpoint=checkpoint)
        if log is not None:
            log(f"쉘 모핑 사본 덮어쓰기: {rel}")
    return len(rels)


def write_thickness(path: str, doc: dict[str, Any] | None) -> str:
    """`--thickness` JSON(3S 두께가 모핑 대상 part에 있을 때만). 없으면 빈 값(인자 쌍 생략)."""
    if not doc:
        return ""
    write_json(path, doc)
    return path


# ---- 샘플 1개(update → morph → check) -------------------------------------------------------------------------


def shell_steps(settings: Any, inp: NativeInputs, *, values_json: str, options_json: str, upd: str, mor: str, chk: str,
                files_dir: str, thickness_json: str) -> tuple[dict[str, str], list[tuple[str, str, str, list[str], list[str], str | None]]]:
    """(placeholder 값, 실행 단계 목록[(키, 단계, 보고, 성공 파일, 백업, cwd)]). paicad_shell_run이 있으면 1단계."""
    v = {**inp.base_values(settings), "values_json": values_json, "options_json": options_json, "update_dir": upd, "morph_dir": mor,
         "check_dir": chk, "out_files_dir": files_dir, "thickness_json": thickness_json}
    if settings.commands.paicad_shell_run is not None:
        return v, [("paicad_shell_run", "run", os.path.join(chk, RUN_JSON), [os.path.join(upd, "sample.brep"), os.path.join(chk, CHECK_JSON)],
                    [upd, mor, chk, files_dir], None)]
    require_shell_commands(settings, "paicad_shell_update", "paicad_shell_morph", "paicad_shell_check")
    return v, [("paicad_shell_update", "update", os.path.join(upd, UPDATE_JSON), [os.path.join(upd, "sample.brep")], [upd], upd),
               ("paicad_shell_morph", "morph", os.path.join(mor, MORPH_JSON), [], [mor], mor),
               ("paicad_shell_check", "check", os.path.join(chk, CHECK_JSON), [], [chk, files_dir], chk)]


STEP_REPORT_REL = {"update": f"m_1/update/{UPDATE_JSON}", "morph": f"m_2/morph/{MORPH_JSON}", "check": f"m_2/check/{CHECK_JSON}"}


def run_sample(x: Any, settings: Any, inp: NativeInputs, R: str, *, thickness_doc: dict[str, Any] | None
               ) -> tuple[Verdict | None, str | None, list[str]]:
    """R/m_1/values.json·R/options.json이 준비된 상태에서 쉘 update→morph→check. (실패 Verdict|None, 실패 단계, PASS 사본 rel 목록)."""
    m1, m2 = os.path.join(R, "m_1"), os.path.join(R, "m_2")
    upd, mor, chk = os.path.join(m1, "update"), os.path.join(m2, "morph"), os.path.join(m2, "check")
    files_dir = os.path.join(m2, SHELL_FILES_DIR)
    tj = write_thickness(os.path.join(m2, THICKNESS_JSON), thickness_doc)
    values, steps = shell_steps(settings, inp, values_json=os.path.join(m1, "values.json"), options_json=os.path.join(R, "options.json"),
                                upd=upd, mor=mor, chk=chk, files_dir=files_dir, thickness_json=tj)
    report: dict[str, Any] | None = None
    for key, step, rep, success, backup, cwd in steps:
        v = run_paicad(x, settings, key, values, cwd=cwd or R, report=rep, success=success, backup=backup, body_map=inp.body_map,
                       log_dir=os.path.dirname(rep))
        if not v.ok:
            return v, (v.step or step if step != "run" else v.step or "update"), []
        report = v.report
    return None, None, out_files(report)


def component_of(settings: Any, base: str) -> str:
    """세트·DOE 준비본의 대상 component(prep.json `component`, 없으면 설정 shell.default_component)."""
    import json

    try:
        with open(os.path.join(base, "native", "prep.json"), encoding="utf-8") as fh:
            c = json.load(fh).get("component")
    except (OSError, ValueError, AttributeError):
        c = None
    return c if isinstance(c, str) and c else settings.shell.default_component


def thickness_for(settings: Any, inp: NativeInputs, props_json: str | None, shell_values: dict[str, float] | None
                  ) -> dict[str, Any] | None:
    """3S 두께 값 중 모핑 대상 part의 PROP → `--thickness` 문서(check (d) 간섭, SM §8.4). 해당 없으면 None."""
    if inp.kind != "shell" or not shell_values or not props_json or not os.path.isfile(props_json):
        return None
    from .geometry_native import read_json

    mb = settings.geometry.max_report_bytes
    feats = read_json(inp.features, mb)
    base = os.path.dirname(os.path.dirname(os.path.dirname(inp.features)))
    return thickness_document([], read_json(props_json, mb), shell_values, target_part_ids(feats, component_of(settings, base)))
