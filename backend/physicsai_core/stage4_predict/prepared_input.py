"""④ 준비된 입력 예측(phase3 §11.5): 입력 경로 검사와 복사 계획. API(작업 생성·경로 확인)·워커(PR_PREP·RAD_ASSEMBLE) 공용.

원본 ③ 단독 예측(`3_PHYSICS_AI/FUNC/5_predict.py`)과 ⑤ 기준 Predict(`1_physicsai_opti.py:294-305`)의 입력 규칙:
`.rad` 파일·폴더 → 그 폴더 직계 `*.rad`·`*.inc`(이름이 `eps_mesh`로 시작하는 것 제외, 하위 폴더 무시), `.hm` → 그 파일만.
원본 폴더는 읽기만 한다.
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any, NamedTuple

from ..paths import (CheckedPath, PathError, allowed_roots, check_user_path, file_name_problem_message, file_safety_problem,
                     is_link_or_reparse)

MESH_PREFIX = "eps_mesh"  # SimLab 메시 산출(원본 opti:300, GUI :427-445) — 복사·starter 셈에서 제외(대소문자 무시)
_COPY_EXTS = (".rad", ".inc")


class CopyPlan(NamedTuple):
    kind: str                       # "file" | "dir"
    starter: str | None             # starter 파일 이름(정확히 1개일 때)
    files: list[str]                # 복사할 원본 절대경로(이름순)
    problems: list[dict[str, Any]]  # [{code, message}] — code ∈ INPUT_EXT·STARTER_COUNT·FILE_NAME_UNSAFE·TOO_MANY_FILES·TOO_LARGE


def is_mesh_file(name: str) -> bool:
    return name.lower().startswith(MESH_PREFIX)


def starter_candidates(folder: str, starter_glob: str) -> list[str]:
    """폴더 직계의 starter 후보(`starter_glob` 일치·eps_mesh 아님)."""
    return sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))
                  and fnmatch.fnmatch(n, starter_glob) and not is_mesh_file(n))


def check_path(raw: object, settings: Any) -> CheckedPath:
    """사용자 입력 경로 검사(허용 루트 = AI 루트 + allowed_import_roots). 위반 시 PathError."""
    cp = check_user_path(raw, allowed_roots(settings, imports=True), expect="any")
    if not os.path.isfile(cp.path) and not os.path.isdir(cp.path):
        raise PathError("PATH_NOT_FOUND", "파일이나 폴더가 없습니다", path=raw)
    return cp


def _direct_copy_set(folder: str) -> list[str]:
    return sorted(n for n in os.listdir(folder) if n.lower().endswith(_COPY_EXTS) and not is_mesh_file(n)
                  and (os.path.isfile(os.path.join(folder, n)) or is_link_or_reparse(os.path.join(folder, n))))


def plan_copy(path: str, settings: Any) -> CopyPlan:
    """검사를 마친 경로(`check_path`)의 복사 계획. 문제가 있어도 계획은 끝까지 만든다(경로 확인 화면 요약용)."""
    pr = settings.predict
    problems: list[dict[str, Any]] = []
    add = lambda code, msg: problems.append({"code": code, "message": msg})  # noqa: E731
    exts = [e.lower() for e in pr.prepared_input_exts]
    if os.path.isdir(path):
        kind, folder = "dir", path
        cands = starter_candidates(folder, pr.starter_glob)
        starter = cands[0] if len(cands) == 1 else None
        if len(cands) != 1:
            add("STARTER_COUNT", f"starter({pr.starter_glob})가 정확히 1개 있어야 합니다(현재 {len(cands)}개)")
        names = _direct_copy_set(folder)
    else:
        kind, folder = "file", os.path.dirname(path)
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        starter = name
        if ext not in exts:
            add("INPUT_EXT", f"입력 파일 확장자는 {', '.join(pr.prepared_input_exts)} 중 하나여야 합니다")
        if is_mesh_file(name):
            add("STARTER_COUNT", "eps_mesh로 시작하는 파일은 starter로 쓸 수 없습니다")
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
    subdir_count}. subdir_count = 복사 대상 폴더(폴더 입력 또는 .rad의 폴더)의 직계 하위 폴더 수(복사 안 함), .hm이면 0(D3-43)."""
    if plan.kind == "dir":
        starters = starter_candidates(path, settings.predict.starter_glob)
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
