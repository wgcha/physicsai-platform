"""레이어 규칙(architecture.md §4.2)을 AST로 검사한다.

규칙 1: physicsai_core는 physicsai_api·physicsai_worker를 import하지 않는다.
규칙 2: physicsai_api와 physicsai_worker는 서로 import하지 않는다.
규칙 3: routers는 services·schemas·deps·auth만 쓰고 sqlalchemy·physicsai_core.db를 모른다.
규칙 4: services는 sqlalchemy(타입용 sqlalchemy.engine 제외)·physicsai_core.db.tables를 import하지 않는다.
규칙 6: 워커 steps/**는 executor·runtime을 import하지 않는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

from physicsai_test_support import REPO

PKG_ROOTS = {
    "physicsai_core": REPO / "backend" / "physicsai_core",
    "physicsai_api": REPO / "backend" / "physicsai_api",
    "physicsai_worker": REPO / "worker" / "physicsai_worker",
}

# 규칙 4: 예외 없음(서비스 SQL은 저장소 함수로 옮김, refactor-plan R5).
SERVICE_SQL_ALLOWED: set[str] = set()

# 규칙 6: 예외 없음(제어 예외는 signals, 수집 간격은 steps/_collect).
STEP_BACKREF_ALLOWED: set[str] = set()


def _module_name(path: Path) -> tuple[str, bool]:
    for top, root in PKG_ROOTS.items():
        if path.is_relative_to(root):
            parts = [top, *path.relative_to(root).with_suffix("").parts]
            is_pkg = parts[-1] == "__init__"
            if is_pkg:
                parts = parts[:-1]
            return ".".join(parts), is_pkg
    raise AssertionError(path)


def imported_modules(path: Path) -> list[tuple[int, str]]:
    """파일이 import하는 모듈의 절대 이름 목록(함수 안 지역 import 포함, `from X import Y`는 X와 X.Y 둘 다)."""
    mod, is_pkg = _module_name(path)
    return _resolve(path.read_text(encoding="utf-8"), mod, is_pkg)


def _resolve(src: str, mod: str, is_pkg: bool) -> list[tuple[int, str]]:
    pkg_parts = mod.split(".") if is_pkg else mod.split(".")[:-1]
    out: list[tuple[int, str]] = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            out += [(n.lineno, a.name) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg_parts[: len(pkg_parts) - (n.level - 1)]
                full = ".".join([*base, *([n.module] if n.module else [])])
            else:
                full = n.module or ""
            out.append((n.lineno, full))
            out += [(n.lineno, f"{full}.{a.name}") for a in n.names]
    return out


def _files(top: str, sub: str = "") -> list[Path]:
    root = PKG_ROOTS[top] / sub if sub else PKG_ROOTS[top]
    files = sorted(root.rglob("*.py"))
    assert files, root
    return files


def _starts(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _violations(files, bad) -> list[str]:
    return [f"{f.relative_to(REPO)}:{ln} {m}" for f in files for ln, m in imported_modules(f) if bad(m)]


def test_rule1_core_does_not_import_api_or_worker():
    v = _violations(_files("physicsai_core"), lambda m: _starts(m, "physicsai_api") or _starts(m, "physicsai_worker"))
    assert v == [], v


def test_rule2_api_and_worker_do_not_import_each_other():
    v = _violations(_files("physicsai_api"), lambda m: _starts(m, "physicsai_worker"))
    v += _violations(_files("physicsai_worker"), lambda m: _starts(m, "physicsai_api"))
    assert v == [], v


def test_rule3_routers_use_only_services_schemas_deps():
    allowed_api = ("physicsai_api.services", "physicsai_api.schemas", "physicsai_api.deps", "physicsai_api.auth")

    def bad(m: str) -> bool:
        if _starts(m, "sqlalchemy") or _starts(m, "physicsai_core.db"):
            return True
        if _starts(m, "physicsai_api") and m != "physicsai_api":
            return not any(_starts(m, a) for a in allowed_api)
        return False

    v = _violations(_files("physicsai_api", "routers"), bad)
    assert v == [], v


def _service_sql(m: str) -> bool:
    if _starts(m, "sqlalchemy"):
        return not _starts(m, "sqlalchemy.engine")
    return _starts(m, "physicsai_core.db.tables")


def test_rule4_services_use_repositories_only():
    root = PKG_ROOTS["physicsai_api"] / "services"
    files = _files("physicsai_api", "services")
    offenders = {f.relative_to(root).as_posix() for f in files if _violations([f], _service_sql)}
    # 허용 목록 밖 위반은 실패, 허용 목록에 있으나 이미 고쳐진 파일도 목록에서 지우도록 실패
    assert offenders - SERVICE_SQL_ALLOWED == set(), _violations(files, _service_sql)
    assert SERVICE_SQL_ALLOWED - offenders == set(), "허용 목록에서 지울 파일"


def test_rule6_steps_do_not_import_executor_or_runtime():
    def bad(m: str) -> bool:
        return any(_starts(m, f"physicsai_worker.{x}") for x in ("executor", "runtime"))

    files = _files("physicsai_worker", "steps")
    offenders = {f.relative_to(PKG_ROOTS["physicsai_worker"] / "steps").as_posix() for f in files if _violations([f], bad)}
    assert offenders - STEP_BACKREF_ALLOWED == set(), _violations(files, bad)
    assert STEP_BACKREF_ALLOWED - offenders == set(), "허용 목록에서 지울 파일"


def test_import_resolver_sees_relative_and_local_imports():
    """검사기 자체 시험: 상대 import와 함수 안 import를 절대 이름으로 푼다."""
    src = "from ..executor import X\nfrom . import y\ndef f():\n    from .. import runtime\n"
    names = {m for _, m in _resolve(src, "physicsai_worker.steps.a", False)}
    assert {"physicsai_worker.executor", "physicsai_worker.executor.X", "physicsai_worker.steps.y", "physicsai_worker.runtime"} <= names
    names = {m for _, m in _resolve("from .b import c\n", "physicsai_worker.steps", True)}
    assert "physicsai_worker.steps.b.c" in names
