"""④ 조립 FEM 검증의 조립 원본 검사·스냅숏(phase3 §21.3.3 S16) — API(미리보기·생성·경로 확인)·워커(FV_PREP) 공용, 순수 파일 검사.

- 조립 원본 3종: `predict_input`(예측 INPUT이 조립 상태일 때만, reuse) · `train_doe`(① DOE 조립 폴더, rebuild) ·
  `custom`(사용자 폴더 — AI 루트·가져오기 루트 또는 SPDM 루트, 읽기만, rebuild).
- 복사 대상 = 직계 `*.rad`·`*.inc` 중 eps_mesh·include 기준본(`predict.mesh_include_name`)이 아닌 것 + `{renum_csv_name}`(있으면).
  RAD_ASSEMBLE(`assembly_sources`)과 같은 규칙. 원본은 읽기만 하고 스냅숏은 열린 핸들 기준 복사(하드링크 금지, §6.11).
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from ..fileutil import copy_stream
from ..paths import (BACKUP_DIR, PLATFORM_DIR, file_name_problem_message, file_safety_problem, is_link_or_reparse, real,
                     windows_reserved_name)
from .param_discover import open_source
from .prepared_input import is_mesh_file

MAX_RAD_LIST = 50
_COPY_EXTS = (".rad", ".inc")
INCLUDE_REF_MAX_LINE = 4096


def _p(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def assembly_name_problem(path: str, base: str) -> str | None:
    """조립 파일 1개의 이름·링크 문제 사용자 문구(없으면 None). `file_safety_problem` + Windows 예약어
    (CON·PRN·AUX·NUL·COM1-9·LPT1-9, 확장자 포함·대소문자 무시) — 스냅숏이 Windows HPC·SCX로 올라간다(D3-64 후속)."""
    why = file_safety_problem(path, base)
    if why:
        return file_name_problem_message(why)
    if windows_reserved_name(os.path.basename(path)):
        return "Windows 예약 이름(CON·PRN·AUX·NUL·COM1~9·LPT1~9)은 파일 이름으로 쓸 수 없습니다"
    return None


def assembly_files(folder: str, settings: Any) -> list[str]:
    """복사 대상 파일 이름(이름순) — eps_mesh·include 기준본 제외, RENUM csv 포함(링크·폴더는 뺀다)."""
    pr = settings.predict
    inc, csv = pr.mesh_include_name.casefold(), pr.renum_csv_name.casefold()
    out = []
    for n in sorted(os.listdir(folder)):
        low = n.casefold()
        if not (low.endswith(_COPY_EXTS) or low == csv) or is_mesh_file(n) or low == inc:
            continue
        p = os.path.join(folder, n)
        if os.path.isfile(p) or is_link_or_reparse(p):
            out.append(n)
    return out


def _references_include(paths: list[str], inc_name: str, max_bytes: int) -> bool | None:
    """직계 rad·inc(크기 ≤ max_bytes)를 줄 단위로 읽어 `#include` 줄에 inc_name(대소문자 무시)이 있는지. 검사 파일 0개 = None."""
    target = inc_name.casefold()
    scanned = 0
    for p in paths:
        try:
            if os.path.getsize(p) > max_bytes:
                continue
            with open(p, "rb") as fh:
                scanned += 1
                for raw in fh:
                    line = raw[:INCLUDE_REF_MAX_LINE].decode("utf-8", errors="replace").strip()
                    if line.casefold().startswith("#include") and target in line.casefold():
                        return True
        except OSError:
            continue
    return False if scanned else None


def plan_assembly(path: str, settings: Any) -> dict[str, Any]:
    """조립 폴더 검사 → {files[], starter, rad[≤50], inc_count, renum_csv, include_baseline, include_referenced, total_bytes,
    file_count, signature[[name,size,mtime_ns]], problems[], warnings[]}. 폴더 경로 자체의 허용 루트 검사는 호출자 몫."""
    pr, fv = settings.predict, settings.fem_verify
    out: dict[str, Any] = {"files": [], "starter": None, "starters": [], "rad": [], "inc_count": 0, "renum_csv": False,
                           "include_baseline": False, "include_referenced": None, "total_bytes": 0, "file_count": 0,
                           "signature": [], "problems": [], "warnings": []}
    if not os.path.isdir(path):
        out["problems"].append(_p("PATH_NOT_FOUND", "조립 폴더가 없습니다"))
        return out
    listing = sorted(os.listdir(path))
    names = assembly_files(path, settings)
    total = 0
    sig = []
    for n in names:
        p = os.path.join(path, n)
        why = assembly_name_problem(p, path)
        if why:
            out["problems"].append(_p("FILE_NAME_UNSAFE", f"{n}: {why}"))
            continue
        st = os.stat(p)
        total += st.st_size
        sig.append([n, st.st_size, st.st_mtime_ns])
    out.update(files=names, file_count=len(names), total_bytes=total, signature=sig)
    out["rad"] = [n for n in names if n.casefold().endswith(".rad")][:MAX_RAD_LIST]
    out["inc_count"] = sum(1 for n in names if n.casefold().endswith(".inc"))
    starters = [n for n in names if fnmatch.fnmatch(n, pr.starter_glob) and not is_mesh_file(n)]
    out["starters"] = starters[:MAX_RAD_LIST]
    if len(starters) == 1:
        out["starter"] = starters[0]
    else:
        listed = f": {', '.join(starters[:10])}" if starters else ""
        out["problems"].append(_p("ASSEM_STARTER_COUNT",
                                  f"조립 폴더에 starter({pr.starter_glob})가 정확히 1개 있어야 합니다(현재 {len(starters)}개{listed})"))
    if len(names) > fv.max_assem_files:
        out["problems"].append(_p("ASSEM_TOO_MANY_FILES", f"조립 원본 파일이 너무 많습니다({len(names)}개, 상한 {fv.max_assem_files})"))
    if total > fv.max_assem_bytes:
        out["problems"].append(_p("ASSEM_TOO_LARGE", f"조립 원본이 너무 큽니다({total} B, 상한 {fv.max_assem_bytes} B)"))
    out["renum_csv"] = any(n.casefold() == pr.renum_csv_name.casefold() for n in names)
    out["include_baseline"] = any(n.casefold() == pr.mesh_include_name.casefold() for n in listing)
    rads = [os.path.join(path, n) for n in names if n.casefold().endswith(_COPY_EXTS)]
    out["include_referenced"] = _references_include(rads, pr.mesh_include_name, fv.include_scan_max_bytes)
    if not out["renum_csv"]:
        out["warnings"].append(_p("RENUM_CSV_MISSING", f"조립 폴더에 {pr.renum_csv_name}이 없습니다 — 메시 번호 재지정 없이 변환합니다"))
    if not out["include_baseline"]:
        out["warnings"].append(_p("MESH_INCLUDE_NOT_IN_ASSEM",
                                  f"조립 폴더에 {pr.mesh_include_name} 기준본이 없습니다 — starter가 이 include를 쓰는지 확인하세요"))
    if out["include_referenced"] is False:
        out["warnings"].append(_p("MESH_INCLUDE_NOT_REFERENCED",
                                  f"조립 입력이 {pr.mesh_include_name}을 #include하지 않습니다 — 새 메시가 해석에 쓰이지 않을 수 있습니다"))
    return out


def summary(plan: dict[str, Any]) -> dict[str, Any]:
    """API 모양(`assembly` 요약 — signature·files 제외)."""
    keys = ("starter", "rad", "inc_count", "renum_csv", "include_baseline", "include_referenced", "file_count", "total_bytes")
    return {k: plan.get(k) for k in keys}


def changed(before: list[list[Any]] | None, after: list[list[Any]]) -> bool:
    """생성 때 서명(파일 이름·크기·mtime)과 지금이 다른지(INPUT_CHANGED)."""
    return [list(x) for x in (before or [])] != [list(x) for x in after]


def snapshot(src: str, dst: str, names: list[str], *, checkpoint: Any = None) -> list[str]:
    """조립 원본 → dst(`F/a<n>/assem`) 복사. 원본은 열린 핸들 기준(O_NOFOLLOW·(dev, ino) 대조)으로 읽기만 한다."""
    os.makedirs(dst, exist_ok=True)
    root_real = real(src)
    out = []
    for n in names:
        if checkpoint is not None:
            checkpoint()
        with open_source(src, root_real, n) as fi:
            copy_stream(fi, os.path.join(dst, n))
        out.append(n)
    return out


def predict_input_ok(input_dir: str, starter: str | None) -> bool:
    """`predict_input` 허용: 예측 INPUT 폴더가 있고 starter가 eps_mesh 파일이 아니다(조립 상태)."""
    return bool(starter) and not is_mesh_file(starter or "") and os.path.isfile(os.path.join(input_dir, starter or ""))


def path_forbidden(path: str) -> bool:
    """_backup·_platform 아래(대소문자 무시)."""
    parts = [x.casefold() for x in os.path.normpath(path).replace("\\", "/").split("/")]
    return BACKUP_DIR in parts or PLATFORM_DIR in parts


def mesh_part_ids(inc_path: str, limit: int = 200) -> list[str]:
    """메시 include의 `/PART/<id>` 머리 줄 id(최대 limit개, 순서 유지)."""
    out: list[str] = []
    try:
        with open(inc_path, "rb") as fh:
            for raw in fh:
                line = raw[:INCLUDE_REF_MAX_LINE].decode("utf-8", errors="replace").strip()
                if line.upper().startswith("/PART/"):
                    pid = line.split("/")[2].strip() if len(line.split("/")) > 2 else ""
                    if pid.isdigit() and pid not in out:
                        out.append(pid)
                        if len(out) >= limit:
                            break
    except OSError:
        return []
    return out


def check_custom_path(raw: object, settings: Any) -> tuple[str, str]:
    """`custom` 조립 원본 경로 → (정규화 경로, "ai"|"spdm"). AI 루트·가져오기 루트(`check_user_path`) 또는 SPDM 루트
    (`check_spdm_path`, 읽기만). `_backup`·`_platform`·링크·공백·메타문자 거부(PathError PATH_*)."""
    from ..fs_browse import check_spdm_dir_for, spdm_configured
    from ..paths import PathError, allowed_roots, check_user_path, unsafe_reason

    try:
        return check_user_path(raw, allowed_roots(settings, imports=True), expect="dir").path, "ai"
    except PathError as exc:
        if exc.code != "PATH_OUTSIDE_ROOT" or not spdm_configured(settings):
            raise
    reason = unsafe_reason(raw) if isinstance(raw, str) else None
    if reason:
        raise PathError("PATH_UNSAFE", f"경로에 {reason}를 쓸 수 없습니다", path=raw)
    path = check_spdm_dir_for(settings, raw)
    if path_forbidden(path):
        raise PathError("PATH_UNSAFE", "_backup·_platform 폴더 아래 경로는 쓸 수 없습니다", path=raw)
    return path, "spdm"


def mesh_source_rel(predict_job: dict[str, Any], root_id: str, settings: Any, *, batch_dir_rel: str | None = None,
                    run_key: str | None = None) -> str | None:
    """재조립용 메시 원천(Study 기준 '/' 상대경로, §21.3.2 표). parametric: `04_predict/<root>/geom/{simlab_mesh_name}`,
    일괄 하위(prepared + batch_run): `B/run__N/m_1/{simlab_mesh_name}`, 그 밖 prepared: None."""
    mesh = settings.predict.simlab_mesh_name
    p = predict_job.get("params") or {}
    if p.get("input_mode") != "prepared":
        return f"04_predict/{root_id}/geom/{mesh}"
    if isinstance(p.get("batch_run"), dict) and batch_dir_rel and run_key:
        return f"{batch_dir_rel}/{run_key}/m_1/{mesh}"
    return None
