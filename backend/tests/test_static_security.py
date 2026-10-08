"""정적 시험: V-CMD-2, V-CMD-4, V-CMD-7, V-SEC-1, V-SEC-3, V-SM-6, 구조(router에 SQL 없음)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from physicsai_test_support import REPO

CODE_DIRS = [REPO / "backend" / "physicsai_core", REPO / "backend" / "physicsai_api", REPO / "worker" / "physicsai_worker"]


def _py_files(dirs=CODE_DIRS):
    for d in dirs:
        yield from d.rglob("*.py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
    return out


def test_api_has_no_subprocess():
    for f in _py_files([REPO / "backend" / "physicsai_api"]):
        assert not _imports(f) & {"subprocess", "multiprocessing"}, f
        assert "os.system" not in f.read_text() and "os.popen" not in f.read_text()


def test_no_pickle_family_imports():
    for f in _py_files():
        assert not _imports(f) & {"pickle", "joblib", "dill", "cloudpickle", "torch", "shelve"}, f
        assert "torch.load" not in f.read_text()


def test_no_shell_true_or_string_commands():
    for f in _py_files():
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"shell\s*=\s*True", src), f
        tree = ast.parse(src)
        for n in ast.walk(tree):
            f_ = n.func if isinstance(n, ast.Call) else None
            is_sub = (isinstance(f_, ast.Attribute) and isinstance(f_.value, ast.Name) and f_.value.id == "subprocess"
                      and f_.attr in ("Popen", "run", "call", "check_output", "check_call")) or (isinstance(f_, ast.Name) and f_.id == "Popen")
            if is_sub:
                if n.args and isinstance(n.args[0], (ast.Constant, ast.JoinedStr)) and isinstance(getattr(n.args[0], "value", ""), str):
                    raise AssertionError(f"문자열 명령: {f}:{n.lineno}")


def test_no_hardcoded_altair_paths():
    for f in _py_files():
        src = f.read_text(encoding="utf-8")
        assert "Program Files" not in src, f
        assert not re.search(r"[A-Za-z]:[\\/]+(Altair|PBS)", src), f


def test_no_user_output_delete_calls():
    allowed: set[str] = set()  # 플랫폼 코드에는 삭제 호출이 없다(임시 파일은 tempfile이 정리)
    pat = re.compile(r"\b(os\.remove|os\.unlink|\.unlink\(|shutil\.rmtree|os\.rmdir|\.rmdir\()")
    for f in _py_files():
        if pat.search(f.read_text(encoding="utf-8")):
            assert f.name in allowed, f


def test_no_upload_routes():
    src = "\n".join(f.read_text() for f in _py_files([REPO / "backend" / "physicsai_api"]))
    assert "UploadFile" not in src and not re.search(r"(?<![A-Za-z_])File\(", src) and "multipart" not in src


def test_no_multipart_in_openapi():
    from physicsai_api.export_openapi import build_openapi

    assert "multipart/form-data" not in str(build_openapi())


def test_no_timeout_handling_in_executor():
    src = (REPO / "worker" / "physicsai_worker" / "executor.py").read_text()
    assert "STEP_TIMEOUT" not in src and "timeout_s" not in src.replace("timeout_s: float = 30", "")


def test_routers_have_no_sql():
    for f in (REPO / "backend" / "physicsai_api" / "routers").glob("*.py"):
        imps = _imports(f)
        assert "sqlalchemy" not in imps, f
        assert "physicsai_core" not in {i for i in imps} or "db" not in f.read_text(), f
