"""④ 준비된 입력 예측(phase3 §11.5): 입력 경로 검사와 복사 계획. API(작업 생성·경로 확인)·워커(PR_PREP·RAD_ASSEMBLE) 공용.

원본 ③ 단독 예측(`3_PHYSICS_AI/FUNC/5_predict.py`)의 입력 규칙:
`.rad` 파일·폴더 → 그 폴더 직계 `*.rad`·`*.inc` **전부**(하위 폴더 무시), `.hm` → 그 파일만. 원본 폴더는 읽기만 한다.
사용자가 준비한 입력은 starter가 `eps_mesh*.inc` 등을 include할 수 있으므로 eps_mesh 파일도 복사한다(phase3 D3-44).
eps_mesh 제외는 parametric(조립 폴더의 이전 형상 메시, 원본 opti:294-305)에만 적용한다(`is_mesh_file`).
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any, NamedTuple

from ..paths import (BACKUP_DIR, PLATFORM_DIR, CheckedPath, PathError, allowed_roots, check_user_path, file_name_problem_message,
                     file_safety_problem, is_link_or_reparse, name_unsafe_chars)

MESH_PREFIX = "eps_mesh"  # SimLab 메시 산출(원본 opti:300, GUI :427-445) — parametric 복사·starter 셈에서 제외(대소문자 무시)
_COPY_EXTS = (".rad", ".inc")
MAX_STARTER_HINTS = 10


class CopyPlan(NamedTuple):
    kind: str                       # "file" | "dir"
    starter: str | None             # starter 파일 이름(정확히 1개일 때)
    files: list[str]                # 복사할 원본 절대경로(이름순)
    problems: list[dict[str, Any]]  # [{code, message}] — code ∈ INPUT_EXT·STARTER_COUNT·FILE_NAME_UNSAFE·TOO_MANY_FILES·TOO_LARGE


def is_mesh_file(name: str) -> bool:
    return name.lower().startswith(MESH_PREFIX)


def starter_candidates(folder: str, starter_glob: str) -> list[str]:
    """폴더 직계의 starter 후보(`starter_glob` 일치·eps_mesh 아님) — ① 조립 폴더·파라미터 세트(parametric) 규칙."""
    return sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))
                  and fnmatch.fnmatch(n, starter_glob) and not is_mesh_file(n))


def prepared_starter_candidates(folder: str, starter_glob: str) -> list[str]:
    """준비된 입력 폴더의 starter 후보(phase3 D3-44): 직계 `starter_glob` 일치 파일 — 1개면 그대로(eps_mesh여도),
    여러 개면 eps_mesh로 시작하지 않는 것만(없으면 전체). 결과가 정확히 1개일 때 그것이 starter."""
    hits = sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)) and fnmatch.fnmatch(n, starter_glob))
    if len(hits) <= 1:
        return hits
    rest = [n for n in hits if not is_mesh_file(n)]
    return rest or hits


def starter_hints(folder: str, starter_glob: str, limit: int = MAX_STARTER_HINTS) -> list[str]:
    """폴더 직계에 starter가 없을 때 1단계 하위 폴더의 starter 후보(상대경로, 최대 `limit`개 — phase3 D3-44).
    읽기만 하며 복사·실행에는 쓰지 않는다. 링크·`_backup`·이름이 안전하지 않은 하위 폴더는 건너뛴다."""
    out: list[str] = []
    try:
        subs = sorted(os.listdir(folder))
    except OSError:
        return out
    for sub in subs:
        d = os.path.join(folder, sub)
        if (not os.path.isdir(d) or is_link_or_reparse(d) or name_unsafe_chars(sub)
                or sub.casefold() in (BACKUP_DIR, PLATFORM_DIR)):
            continue
        try:
            cands = prepared_starter_candidates(d, starter_glob)
        except OSError:
            continue
        for n in cands:
            if file_safety_problem(os.path.join(d, n), folder) is None:
                out.append(os.path.join(sub, n))
            if len(out) >= limit:
                return out
    return out


def check_path(raw: object, settings: Any) -> CheckedPath:
    """사용자 입력 경로 검사(허용 루트 = AI 루트 + allowed_import_roots). 위반 시 PathError."""
    cp = check_user_path(raw, allowed_roots(settings, imports=True), expect="any")
    if not os.path.isfile(cp.path) and not os.path.isdir(cp.path):
        raise PathError("PATH_NOT_FOUND", "파일이나 폴더가 없습니다", path=raw)
    return cp


def _direct_copy_set(folder: str) -> list[str]:
    """복사 대상: 폴더 직계 `*.rad`·`*.inc` 전부(eps_mesh 포함, phase3 D3-44). 링크는 포함해 FILE_NAME_UNSAFE로 알린다."""
    return sorted(n for n in os.listdir(folder) if n.lower().endswith(_COPY_EXTS)
                  and (os.path.isfile(os.path.join(folder, n)) or is_link_or_reparse(os.path.join(folder, n))))


def plan_copy(path: str, settings: Any) -> CopyPlan:
    """검사를 마친 경로(`check_path`)의 복사 계획. 문제가 있어도 계획은 끝까지 만든다(경로 확인 화면 요약용)."""
    pr = settings.predict
    problems: list[dict[str, Any]] = []
    add = lambda code, msg: problems.append({"code": code, "message": msg})  # noqa: E731
    exts = [e.lower() for e in pr.prepared_input_exts]
    if os.path.isdir(path):
        kind, folder = "dir", path
        cands = prepared_starter_candidates(folder, pr.starter_glob)
        starter = cands[0] if len(cands) == 1 else None
        if len(cands) != 1:
            listed = f": {', '.join(cands[:10])}{' …' if len(cands) > 10 else ''}" if cands else ""
            add("STARTER_COUNT", f"starter({pr.starter_glob})가 정확히 1개 있어야 합니다(현재 {len(cands)}개{listed})")
        names = _direct_copy_set(folder)
    else:
        kind, folder = "file", os.path.dirname(path)
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        starter = name
        if ext not in exts:
            add("INPUT_EXT", f"입력 파일 확장자는 {', '.join(pr.prepared_input_exts)} 중 하나여야 합니다")
        if ext == ".rad":
            names = _direct_copy_set(folder)
            if name not in names:
                names = sorted([*names, name])
        else:
            names = [name]
    files = [os.path.join(folder, n) for n in names]
    total = 0
    for f in files:
        why = file_safety_problem(f, folder)
        if why:
            add("FILE_NAME_UNSAFE", f"{os.path.basename(f)}: {file_name_problem_message(why)}")
            continue
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    if len(files) > pr.prepared_max_files:
        add("TOO_MANY_FILES", f"복사할 파일이 상한({pr.prepared_max_files}개)을 넘습니다(현재 {len(files)}개)")
    if total > pr.prepared_max_total_bytes:
        add("TOO_LARGE", f"복사할 파일 총량이 상한({pr.prepared_max_total_bytes} bytes)을 넘습니다")
    return CopyPlan(kind, starter if not any(p["code"] in ("STARTER_COUNT", "INPUT_EXT") for p in problems) else None,
                    files, problems)


def summary(path: str, plan: CopyPlan, settings: Any) -> dict[str, Any]:
    """경로 확인(`PREDICT_INPUT`) 요약: {kind, starter:[names], starter_ok, rad:[≤50], inc_count, file_count, total_bytes,
    subdir_count, starter_hints}. subdir_count = 복사 대상 폴더(폴더 입력 또는 .rad의 폴더)의 직계 하위 폴더 수(복사 안 함),
    .hm이면 0(D3-43). starter_hints = 폴더 입력에 starter가 0개일 때 1단계 하위 폴더 후보(상대경로 ≤10, 그 밖엔 [], D3-44)."""
    hints: list[str] = []
    if plan.kind == "dir":
        starters = prepared_starter_candidates(path, settings.predict.starter_glob)
        if not starters:
            hints = starter_hints(path, settings.predict.starter_glob)
    else:
        starters = [os.path.basename(path)]
    names = [os.path.basename(f) for f in plan.files]
    total = 0
    for f in plan.files:
        try:
            total += os.path.getsize(f) if os.path.isfile(f) and not is_link_or_reparse(f) else 0
        except OSError:
            pass
    return {
        "kind": plan.kind,
        "starter": starters,
        "starter_ok": plan.starter is not None,
        "rad": [n for n in names if n.lower().endswith(".rad")][:50],
        "inc_count": sum(1 for n in names if n.lower().endswith(".inc")),
        "file_count": len(names),
        "total_bytes": total,
        "subdir_count": _subdir_count(path, plan.kind),
        "starter_hints": hints,
    }


def _subdir_count(path: str, kind: str) -> int:
    if kind == "dir":
        folder = path
    elif path.lower().endswith(".rad"):
        folder = os.path.dirname(path)
    else:
        return 0
    try:
        return sum(1 for n in os.listdir(folder) if os.path.isdir(os.path.join(folder, n)))
    except OSError:
        return 0
