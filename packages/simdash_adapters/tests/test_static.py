"""V3-S4-4: 패키지 정적 검사 — 표준 라이브러리만 import, 최상위 subprocess 없음, 버전 단일 출처, 공개 API 고정."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import simdash_adapters

PKG_ROOT = Path(__file__).resolve().parents[1]
SRC = PKG_ROOT / "src" / "simdash_adapters"

# phase3.md §6.3 공개 API — 바꾸면 SemVer minor 올림(§6.5)과 이 목록 갱신이 함께 필요하다
PUBLIC_API = {
    "__version__",
    "HpcState", "HpcAvailability", "HpcSubmitSpec", "HpcSubmitResult", "HpcStatus", "HpcGatewayError", "HpcJobGateway",
    "CommandConfig", "HpcDefaults", "validate_command_config", "render_argv", "CommandHpcGateway",
    "NoneHpcGateway", "AdapterHpcGateway", "make_gateway",
    "PathMapEntry", "TransferConfig", "map_path", "resolve_collect_dirs",
    "fwd", "is_abs_path_str",
}
# 허용 표준 라이브러리(§6.3 설계 규칙 + 타입 표기용 collections.abc·types·__future__)
# + scx relay 클라이언트(phase3 §16.2 — http.client만, R3-8): http·urllib(urlsplit·quote)·hashlib·json·fnmatch·unicodedata·time·threading
STDLIB_ALLOWED = {"__future__", "dataclasses", "typing", "re", "string", "os", "logging", "subprocess", "collections", "types",
                  "http", "urllib", "hashlib", "json", "fnmatch", "unicodedata", "time", "threading"}


def _sources() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert files
    return files


def _imports(path: Path) -> list[tuple[int, str, int]]:
    """(줄, 최상위 모듈 이름 또는 '.'(상대), 들여쓰기 깊이 0=모듈 최상위)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    top_level = {id(n) for n in tree.body}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [(n.lineno, a.name.split(".")[0], 0 if id(n) in top_level else 1) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            name = "." if n.level else (n.module or "").split(".")[0]
            out.append((n.lineno, name, 0 if id(n) in top_level else 1))
    return out


def test_imports_are_stdlib_allowlist_only():
    bad = []
    for f in _sources():
        for ln, mod, _ in _imports(f):
            if mod == ".":
                continue
            if mod not in STDLIB_ALLOWED or mod not in sys.stdlib_module_names | {"__future__"}:
                bad.append(f"{f.relative_to(PKG_ROOT)}:{ln} {mod}")
    assert bad == [], bad


def test_no_platform_or_third_party_names_in_source():
    pat = re.compile(r"\b(physicsai_\w+|pydantic|sqlalchemy|fastapi|psycopg)\b")
    for f in _sources():
        for ln, mod, _ in _imports(f):
            assert not pat.match(mod), f"{f}:{ln} {mod}"


def test_subprocess_not_imported_at_module_top():
    for f in _sources():
        tops = [ln for ln, mod, depth in _imports(f) if mod == "subprocess" and depth == 0]
        assert tops == [], f"{f}: 모듈 최상위 subprocess import {tops}"


def test_version_single_source():
    meta = tomllib.loads((PKG_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert meta["version"] == simdash_adapters.__version__ == "0.1.0"
    assert meta["name"] == "simdash-adapters" and meta["dependencies"] == []
    assert f"## {simdash_adapters.__version__}" in (PKG_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_public_api_is_fixed():
    assert set(simdash_adapters.__all__) == PUBLIC_API
    assert len(simdash_adapters.__all__) == len(PUBLIC_API)
    for name in PUBLIC_API:
        assert hasattr(simdash_adapters, name), name


def test_py_typed_marker():
    assert (SRC / "py.typed").is_file()


def test_no_dynamic_import_or_exec():
    """어댑터 자리(`hpc/adapter.py` 포함)는 다른 패키지를 동적으로 불러오지 않는다(platform.md §12.1)."""
    for f in _sources():
        src = f.read_text(encoding="utf-8")
        assert "import_module" not in src and "__import__" not in src, f
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                assert n.func.id not in ("exec", "eval"), f"{f}:{n.lineno}"
