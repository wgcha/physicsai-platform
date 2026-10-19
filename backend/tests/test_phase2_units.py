"""2차 단위·정적 시험: V2-TD-3, V2-LCH-1, V2-SEC-1~3, V2-SPDM-3, T10b(V-SM-1 확장), V2-NT-1, V2-DEP-1.

설정(V2-CFG-1·2)·명령(V2-CMD-1·2)은 common/test_config_stages."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import subprocess

import pytest

from physicsai_test_support import REPO, SIMLAB_TPL_TEMPLATE

CODE_DIRS = [REPO / "backend" / "physicsai_core", REPO / "backend" / "physicsai_api", REPO / "worker" / "physicsai_worker",
             REPO / "packages" / "simdash_adapters" / "src"]  # 3차 S4: 옮긴 HPC 코드도 같은 정적 검사


def _py(dirs=CODE_DIRS):
    for d in dirs:
        yield from d.rglob("*.py")


# ---------------------------------------------------------------------------
# tpl 재구현 골든(V2-TD-3)
# ---------------------------------------------------------------------------


def _original():
    spec = importlib.util.spec_from_file_location("original_create_tpl", REPO / "backend" / "tests" / "data" / "original_create_tpl.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


PARAMS = [
    {"name": "THK_1", "nominal": 3.0, "min": 2.85, "max": 3.15, "format": "%3i", "use": True},
    {"name": "RIB_H", "nominal": 12.5, "min": 11.875, "max": 13.125, "format": "%3i", "use": False},
    {"name": "N_RIB", "nominal": 4.0, "min": 2.0, "max": 8.0, "format": "%3i", "use": True},
]


@pytest.mark.parametrize("use_all", [True, False])
def test_tpl_generate_matches_original(tmp_path, use_all):
    from physicsai_core.config import TrainDataCfg
    from physicsai_core.stage1_train_data.train_tpl import TplRules, generate, num_text

    used = [p for p in PARAMS if use_all or p["use"]]
    tmpl = tmp_path / "TEMAPLATE.tpl"
    tmpl.write_text(SIMLAB_TPL_TEMPLATE, encoding="utf-8")
    out = tmp_path / "orig.tpl"
    rows = {i: {"param": p["name"], "nominal": num_text(p["nominal"]), "min": num_text(p["min"]), "max": num_text(p["max"])}
            for i, p in enumerate(used)}
    _original().update_parameter_file(str(tmpl), str(out), rows, "cad.prt")
    ours = generate(SIMLAB_TPL_TEMPLATE, used, "cad.prt", TplRules.from_settings(TrainDataCfg()))
    assert ours == out.read_text(encoding="utf-8")
    assert "OLD_PARAM" not in ours and ('RIB_H' in ours) == use_all


def test_tpl_generate_errors_and_validation():
    from physicsai_core.config import TrainDataCfg
    from physicsai_core.stage1_train_data.train_tpl import TplRules, TplTemplateInvalid, generate, validate_generated

    rules = TplRules.from_settings(TrainDataCfg())
    with pytest.raises(TplTemplateInvalid) as ei:
        generate(SIMLAB_TPL_TEMPLATE.replace("#*****", "#-----"), PARAMS[:1], "c.prt", rules)
    assert ei.value.problems[0]["code"] == "TPL_MARKER_MISSING"
    with pytest.raises(TplTemplateInvalid) as ei:
        generate(SIMLAB_TPL_TEMPLATE.replace('<Parameters Value="">', "<Parameters>"), PARAMS[:1], "c.prt", rules)
    assert ei.value.problems[0]["code"] == "TPL_ANCHOR_MISSING"
    p = [{**PARAMS[0], "format": "%8.4f"}]
    text = generate(SIMLAB_TPL_TEMPLATE, p, "c.prt", rules)
    assert 'NewValue="{var_1, %8.4f}"' in text and validate_generated(text, p) == []
    assert validate_generated(text, PARAMS) != []


def test_train_params_units(tmp_path):
    """V2-TD-1·2: XML 파싱(mm 제거·비숫자·이름 규칙·DOCTYPE), 기본 범위, 정수 형식 경고."""
    from physicsai_core.stage1_train_data import train_params as tp
    from physicsai_core.errors import StepFailure

    x = tmp_path / "p.xml"
    x.write_text("<Root><Model><Parameter><Name> A </Name><Value>-2 MM</Value></Parameter>"
                 "<Parameter><Name>B</Name><Value>abc</Value></Parameter><Parameter><Name>C</Name></Parameter></Model></Root>")
    pairs = tp.read_extracted_xml(str(x), 4096)
    assert pairs == [("A", "-2"), ("B", "abc")]
    rows = tp.build_from_extracted(pairs, 0.05, "%3i")
    assert rows[0]["min"] == -2.1 and rows[0]["max"] == -1.9 and rows[0]["valid"] and rows[0]["use"]
    assert rows[1]["nominal"] is None and not rows[1]["valid"] and not rows[1]["use"]
    with pytest.raises(StepFailure):
        tp.read_extracted_xml(str(x), 10)
    x.write_text('<!DOCTYPE r [<!ENTITY e "x">]><Root/>')
    with pytest.raises(StepFailure):
        tp.read_extracted_xml(str(x), 4096)
    assert tp.integer_format_warnings([{"name": "A", "use": True, "format": "%3i", "nominal": 3.0, "min": 2.0, "max": 4.0}]) == []
    assert tp.integer_format_warnings([{"name": "A", "use": True, "format": "%d", "nominal": 3.0, "min": 2.5, "max": 4.0}])


def test_doe_types_parse_original_json():
    from physicsai_core.stage1_train_data.doe_types import find, parse_doe_types, validate_options
    from physicsai_test_support import DOE_TYPES

    t = parse_doe_types(DOE_TYPES)
    sob = find(t, "Sobol")
    assert sob["fields"][1] == {"key": "SCRAMBLE", "label": "Scramble", "type": "bool", "default": False}
    assert validate_options(sob, {"SEQUENCE_OFFSET": 1, "SCRAMBLE": True, "SEED": 0}) == []
    assert validate_options(sob, {"SEQUENCE_OFFSET": 1, "SCRAMBLE": 1, "SEED": 0})
    assert validate_options(find(t, "FracFact"), {"RESOLUTION": "4"}) == []


# ---------------------------------------------------------------------------
# 상태 머신·알림(T10b, V2-NT-1)
# ---------------------------------------------------------------------------


def test_t10b_rules():
    from physicsai_core.state_machine import CONDITIONAL_TRANSITIONS, check_transition, hpc_terminal_transition

    assert check_transition(*CONDITIONAL_TRANSITIONS["T10b"]) == "T10"
    f = hpc_terminal_transition
    assert f("TD_SOLVE", "collect_partial", ["SUCCEEDED", "FAILED"]) == "T10b"
    assert f("TD_SOLVE", "collect_partial", ["SUCCEEDED", "LOST"]) == "T10b"
    assert f("TD_SOLVE", "fail", ["SUCCEEDED", "FAILED"]) == "T13"
    assert f("TD_SOLVE", None, ["FAILED", "FAILED"]) == "T13"
    assert f("PREDICT_VERIFY", None, ["SUCCEEDED", "FAILED"]) == "T13"
    assert f("TD_SOLVE", None, ["SUCCEEDED", "SUCCEEDED"]) == "T10"
    assert f("TD_SOLVE", None, ["SUCCEEDED", "RUNNING"]) is None


def test_notification_titles():
    from physicsai_core.db.repositories.notifications import _title
    from physicsai_core.job_types import job_label

    assert _title("JOB_SUCCEEDED", job_label("TD_DOE_GEN"), "cushion", None)[0] == "완료: DOE·Radioss 입력 생성 (cushion)"
    assert _title("JOB_FAILED", job_label("CU_H3D_CURATE"), "cushion", "EXIT_NONZERO")[0] == "실패: 큐레이션 (cushion) — EXIT_NONZERO"
    assert _title("JOB_SUCCEEDED", job_label("OPTIMIZE"), "cushion", None)[0] == "완료: 최적화 (cushion)"
    assert _title("HPC_COLLECTED", "PBS 해석", "c", None, {"submitted": 30, "failed": 1, "collected": 29})[0] == \
        "PBS 결과 회수 완료 — 30개 중 29개 회수"
    assert _title("HPC_PARTIAL_FAILED", "PBS 해석", "c", None, {"submitted": 30, "failed": 1})[0] == \
        "PBS 해석 일부 실패 — 30개 중 1개 실패, 나머지 회수 진행"
    labels = {k: job_label(k) for k in ("TD_EXTRACT_PARAMS", "TD_SOLVE", "TD_RESULT_IMPORT", "TD_RESP_EXTRACT", "CU_H3D_PREVIEW",
                                        "CU_T01_PREVIEW", "CU_T01_CURVES", "SPDM_IMPORT")}
    assert labels == {"TD_EXTRACT_PARAMS": "파라미터 추출", "TD_SOLVE": "PBS 해석", "TD_RESULT_IMPORT": "결과 가져오기",
                      "TD_RESP_EXTRACT": "run 응답 추출", "CU_H3D_PREVIEW": "h3d 미리보기", "CU_T01_PREVIEW": "T01 미리보기",
                      "CU_T01_CURVES": "곡선 추출", "SPDM_IMPORT": "SPDM 가져오기"}


# ---------------------------------------------------------------------------
# 정적(V2-SEC-1~3, V2-LCH-1, V2-SPDM-3)
# ---------------------------------------------------------------------------


def test_platform_never_imports_or_execs_launchers():
    """V2-LCH-1·V2-SEC-2: pyd·런처를 import·exec하지 않는다(importlib·runpy·exec 사용 금지)."""
    for f in _py():
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("exec", "eval", "__import__"):
                raise AssertionError(f"{f}: {n.func.id}")
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                assert not any(m.split(".")[0] in ("runpy", "importlib") for m in mods), f
        assert "import_module(" not in src and ".pyd\")" not in src.replace("*.pyd\")", ""), f


def test_spdm_access_only_in_spdm_module():
    """V2-SPDM-3: SPDM 경로를 읽는 코드는 spdm.py 하나(나머지는 설정 검증·기능 판정·보호 루트 등록만)."""
    # 파일 이름이 아니라 저장소 상대경로로 정확히 대조한다(refactor-plan R4: 단계 이름 파일이 여러 패키지에 있음)
    allowed = {
        "backend/physicsai_core/stage2_curation/spdm.py", "backend/physicsai_core/config/schema.py", "backend/physicsai_core/config/validate.py",
        "backend/physicsai_core/features.py",
        "backend/physicsai_core/fs_browse.py",  # phase3 §21.3.8 S16: SPDM 루트 탐색·조립 원본 직접 지정(spdm.check_spdm_path 포장)
        "backend/physicsai_core/env_check.py", "backend/physicsai_api/main.py",
        "backend/physicsai_api/services/job_params/stage2_curation.py", "backend/physicsai_api/services/path_inspect.py",
        "worker/physicsai_worker/env_check.py", "worker/physicsai_worker/__main__.py", "worker/physicsai_worker/runtime.py",
        "worker/physicsai_worker/steps/stage2_curation/spdm_import.py",
    }
    for f in _py():
        src = f.read_text(encoding="utf-8")
        if "spdm_roots" in src:
            assert f.relative_to(REPO).as_posix() in allowed, f
    # SPDM 경로 접근은 spdm.check_spdm_path/scan/open_read/probe_roots로만
    for rel in ("backend/physicsai_api/services/job_params/stage2_curation.py", "backend/physicsai_api/services/path_inspect.py",
                "worker/physicsai_worker/steps/stage2_curation/spdm_import.py", "worker/physicsai_worker/env_check.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert re.search(r"spdm\.(check_spdm_path|scan|open_read|probe_roots)", src), rel
    tree = ast.parse((REPO / "backend" / "physicsai_core" / "stage2_curation" / "spdm.py").read_text(encoding="utf-8"))
    banned = {"link", "symlink", "replace", "copy2", "copyfile", "utime", "chmod", "rename", "makedirs", "mkdir", "remove",
              "unlink", "write", "write_text", "write_bytes"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            owner = getattr(getattr(n.func, "value", None), "id", None)
            if owner in ("os", "shutil", "pathlib") or name in ("write_text", "write_bytes", "copy2", "copyfile"):
                assert name not in banned, name
            if owner == "os" and name == "open":  # 읽기 전용 플래그만
                flags = ast.unparse(n.args[1])
                assert "O_RDONLY" in flags and not re.search(r"O_(WRONLY|RDWR|CREAT|TRUNC|APPEND)", flags), flags
            if owner == "os" and name == "fdopen":
                assert [a.value for a in n.args[1:2] if isinstance(a, ast.Constant)] == ["rb"]
            if isinstance(n.func, ast.Name) and name == "open":
                modes = [a.value for a in n.args[1:2] if isinstance(a, ast.Constant)]
                assert modes == ["rb"], modes


def test_no_new_delete_calls_and_no_hardcoded_paths_in_deploy():
    """V2-SEC-1·V2-SEC-3: 삭제 호출 0(1차 정적 시험과 같은 규칙) + deploy/에 Program Files·평문 비밀번호 인자 없음."""
    pat = re.compile(r"\b(os\.remove|os\.unlink|\.unlink\(|shutil\.rmtree|os\.rmdir|\.rmdir\()")
    for f in _py():
        assert not pat.search(f.read_text(encoding="utf-8")), f
    for f in (REPO / "deploy").rglob("*"):
        if f.is_file():
            t = f.read_text(encoding="utf-8")
            assert "Program Files" not in t, f
            assert not re.search(r"(?i)PASSWORD\s*=\s*['\"][^'\"$]+['\"]", t), f
            assert not re.search(r"(?i)--password[= ]", t), f  # psql 등에 비밀번호를 명령 인자로 넘기지 않는다
            assert not re.search(r"(?i)PASSWORD\s+'[A-Za-z0-9]", t), f  # SQL 평문 비밀번호 리터럴 없음


# ---------------------------------------------------------------------------
# 배포(V2-DEP-1·2)
# ---------------------------------------------------------------------------

DEPLOY = REPO / "deploy"


def test_deploy_files_and_keys():
    for n in ("deploy.example.json", "collect-offline.sh", "collect-offline.ps1", "requirements.lock", "install.ps1", "install.bat",
              "update.ps1", "update.bat", "caddy/physicsai.caddy", "uninstall-tasks.ps1"):
        assert (DEPLOY / n).is_file(), n
    cfg = json.loads((DEPLOY / "deploy.example.json").read_text(encoding="utf-8"))
    keys = {"install_root", "python_exe", "pg_bin", "pg_host", "pg_port", "db_name", "db_role", "config_path", "service_user",
            "run_mode", "caddy_frontend_root", "dashboard_root"}  # 포트는 platform.yaml server.port 한 곳(deploy.json에 없음)
    assert set(cfg) == keys and cfg["db_name"] == "physicsai" and cfg["db_role"] == "physicsai_app"
    used = set()
    for n in ("install.ps1", "update.ps1", "uninstall-tasks.ps1"):
        used |= set(re.findall(r"\$cfg\.([A-Za-z_]+)", (DEPLOY / n).read_text(encoding="utf-8")))
    assert used <= keys and used >= keys - {"caddy_frontend_root"} | set(), used ^ keys
    # DB·환경변수·alembic·작업 스케줄러·health는 공용 함수(install-common.ps1) — install.ps1(묶음)·setup.ps1(git 폴더)이 같은 코드를 쓴다
    common = (DEPLOY / "install-common.ps1").read_text(encoding="utf-8")
    inst = (DEPLOY / "install.ps1").read_text(encoding="utf-8") + common
    # 실행 환경은 대시보드와 같게: Python 3.12(아니면 중단), PostgreSQL 18(아니면 경고) — decisions 2026-10-13
    # python_exe는 실제로 실행해 3.12인지 확인(deploy/python-select.ps1 공용 — 망가진 pyenv shim이면 원인·다음 행동, GitHub #1)
    sel = (DEPLOY / "python-select.ps1").read_text(encoding="utf-8")
    assert "sys.version_info[:2] == (3, 12)" in sel and "3.13" not in sel
    for n in ("install.ps1", "update.ps1"):
        t = (DEPLOY / n).read_text(encoding="utf-8")
        assert "python-select.ps1" in t and "Assert-PhysicsAIPython312" in t and "& $cfg.python_exe" not in t, n
    assert "3.13" not in inst and "SHOW server_version_num" in inst and "-ne 18" in inst
    assert "dashboard-env.ps1" in inst and "dashboard-env.ps1" in (DEPLOY / "update.ps1").read_text(encoding="utf-8")
    assert "ExecutionTimeLimit" in inst and "New-TimeSpan -Seconds 0" in inst and "RestartCount 999" in inst
    assert "Read-Host" in inst and "-AsSecureString" in inst and "PGPASSWORD" in inst and "IgnoreNew" in inst
    assert "physicsai_api.serve" in inst and "physicsai_worker" in inst and "/physicsai/api/health" in inst
    upd = (DEPLOY / "update.ps1").read_text(encoding="utf-8")
    assert "_backup" in upd and "Remove-Item" not in upd and "FROM jobs WHERE state IN" in common
    assert "세션 토큰(없으면" not in upd + common and "/physicsai/api/queue" not in upd + common   # phase3 D3-39: 대기열은 묻지 않고 DB 직접
    assert "Remove-Item" not in inst and "Remove-Item" not in (DEPLOY / "uninstall-tasks.ps1").read_text(encoding="utf-8")
    for n in ("install.ps1", "update.ps1", "setup.ps1", "update-repo.ps1"):
        assert "install-common.ps1" in (DEPLOY / n).read_text(encoding="utf-8"), n
    for b in ("install.bat", "update.bat"):
        assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in (DEPLOY / b).read_text(encoding="utf-8")
    caddy = (DEPLOY / "caddy" / "physicsai.caddy").read_text(encoding="utf-8")
    assert "redir /physicsai /physicsai/ 308" in caddy and "handle /physicsai/api/*" in caddy and "reverse_proxy 127.0.0.1:{$PHYSICSAI_PORT:8100}" in caddy
    lock = (DEPLOY / "requirements.lock").read_text(encoding="utf-8")
    for pkg in ("fastapi==", "uvicorn==", "pydantic==", "sqlalchemy==", "psycopg==", "alembic==", "pyyaml==", "httpx==", "psutil=="):
        assert pkg in lock.lower(), pkg


@pytest.mark.posix  # bash 스크립트(Windows는 collect-offline.ps1 — CI windows 잡에서 실제 실행)
def test_collect_offline_dry_run():
    r = subprocess.run(["bash", str(DEPLOY / "collect-offline.sh"), "--dry-run"], capture_output=True, text=True, cwd=REPO, timeout=60)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "pip download -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.12 -d dist/wheels" in out
    assert "3.13" not in out
    # 프런트: 저장소 빌드본 frontend-dist가 최신이면 그대로(npm 없음 — phase3 D3-40)
    assert "pip wheel . --no-deps -w dist/wheels" in out and "cp -r frontend-dist/. dist/frontend/" in out and "npm ci" not in out
    assert "physicsai-offline-" in out and ".zip" in out


def _pwsh() -> str | None:
    import os

    return os.environ.get("PHYSICSAI_PWSH") or shutil.which("pwsh")


@pytest.mark.posix  # Windows는 CI windows 잡 "오프라인 묶음 만들기"(가짜 pyenv shim이 PATH 맨 앞, -DashboardRoot)에서 실제 실행
def test_collect_offline_ps1_selects_dashboard_runtimes(tmp_path):
    """GitHub #1: collect-offline.ps1은 PATH의 망가진 pyenv shim 대신 -DashboardRoot의 Python 3.12·Node 22를 고르고,
    pip는 빌드용 임시 venv(dist\\_buildvenv)에서 실행한다. Node 22가 없거나 python_exe가 망가지면 원인·다음 행동으로 중단."""
    import os

    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("pwsh 없음 — collect-offline.ps1 실행 시험 미수행(CI linux·windows 잡은 pwsh 있음)")

    def stub(path, body: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)
        return path.as_posix()

    shims = tmp_path / "shims"
    stub(shims / "python", 'echo "No global/local python version has been set yet." >&2; echo "pyenv global 3.7.4" >&2; exit 1')
    stub(shims / "python3", 'echo "No global/local python version has been set yet." >&2; exit 1')
    dash = tmp_path / "dash"
    dpy = stub(dash / ".tools" / "python" / "cpython-3.12.13-windows-x86_64-none" / "python.exe",
               'echo "PHYSICSAI_PY=3.12.13 /dash/cpython-3.12.13/python.exe"; exit 0')
    stub(dash / ".tools" / "node-v22.23.2-win-x64" / "node.exe", 'echo v22.23.2')
    stub(dash / ".tools" / "node-v22.23.2-win-x64" / "npm.cmd", 'exit 0')
    (dash / ".env").write_text("DATABASE_URL=postgresql://u:secret-x@h:5/d\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}
    # 프런트 빌드본이 없는(오래된) 저장소 사본 — Node 선택·npm 경로(phase3 D3-40)
    stale = tmp_path / "stale-repo"
    shutil.copytree(DEPLOY, stale / "deploy", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(REPO / "pyproject.toml", stale / "pyproject.toml")
    (stale / ".node-version").write_text("v22.23.2\n", encoding="utf-8")
    (stale / "frontend").mkdir()
    (stale / "frontend" / "package-lock.json").write_text("{}", encoding="utf-8")

    def run(*args: str, path: str | None = None, root: Path = stale) -> subprocess.CompletedProcess:
        e = dict(env) if path is None else {**env, "PATH": path}
        return subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", (root / "deploy" / "collect-offline.ps1").as_posix(), "-DryRun", *args],
                              capture_output=True, text=True, cwd=root, env=e, timeout=120)

    r = run("-DashboardRoot", dash.as_posix())
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "Python 후보 건너뜀: -PythonExe" not in out and "Python 선택: 대시보드 Python 3.12 → /dash/cpython-3.12.13/python.exe" in out
    assert "frontend-dist가 없습니다" in out and "Node 선택: 대시보드 Node" in out and "v22.23.2" in out and "secret-x" not in out
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("+ ")]
    assert any("pip wheel packages/simdash_adapters" in ln for ln in lines) and any("npm ci" in ln for ln in lines)
    assert any("copy frontend\\dist" in ln for ln in lines)
    assert not (stale / "dist" / "_buildvenv").exists()   # -DryRun은 venv를 만들지 않는다

    # 실제 저장소(frontend-dist 최신): Node를 고르지 않고 빌드본을 묶는다(Node·npm 불필요)
    r = run("-DashboardRoot", dash.as_posix(), root=REPO)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "저장소 빌드본 frontend-dist 사용" in out and "Node 선택" not in out
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("+ ")]
    assert not any("npm" in ln for ln in lines) and any("copy frontend-dist" in ln for ln in lines)
    assert not (REPO / "dist" / "_buildvenv").exists()

    # 대시보드 없이 PATH 첫 python이 shim이고 다른 3.12도 없으면: 원인(건너뛴 후보)·다음 행동으로 중단
    r = run(path=f"{shims}{os.pathsep}{tmp_path / 'empty'}")
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "No global/local python" in out and "Python 3.12를 찾지 못했습니다" in out and "-DashboardRoot" in out

    # Python은 있어도 Node 22가 없으면(PATH node 20) Node 원인·다음 행동
    stub(tmp_path / "node20" / "node", 'echo v20.11.1')
    r = run("-PythonExe", dpy, path=f"{shims}{os.pathsep}{tmp_path / 'node20'}")
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "Python 선택: -PythonExe" in out
    assert "Node 22를 찾지 못했습니다" in out and "Node v20.11.1(22 아님)" in out and "다음 행동" in out

    # install.ps1·update.ps1의 python_exe 검증: 망가진 shim이면 원인·다음 행동
    sel = (DEPLOY / "python-select.ps1").as_posix()
    r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command",
                        f". '{sel}'; Assert-PhysicsAIPython312 -Exe '{(shims / 'python').as_posix()}'"],
                       capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "python_exe가 Python 3.12로 실행되지 않습니다" in out and "No global/local python" in out and "dashboard_root" in out


def test_dashboard_env_reads_only_bin_host_port(tmp_path):
    """deploy/dashboard-env.ps1: 대시보드 .env에서 POSTGRES_BIN·DATABASE_URL host·port·WINDOWS_WEB_BASE_PATH만, .tools 고정 Python 3.12.
    비밀값은 출력에 없다."""
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("pwsh 없음 — dashboard-env.ps1 실행 시험 미수행(CI linux·windows 잡은 pwsh 있음)")
    dash = tmp_path / "simulation_workbench"
    for v in ("3.12.4", "3.12.13", "3.13.1"):
        d = dash / ".tools" / "python" / f"cpython-{v}-windows-x86_64-none"
        d.mkdir(parents=True)
        (d / "python.exe").write_bytes(b"")
    secret = "Pw-Do-Not-Leak%40x"
    (dash / ".env").write_text(
        "# 주석 DATABASE_URL=postgresql://x:y@wrong:1/z\n"
        f"DATABASE_URL=postgresql+psycopg://simdashboard_app:{secret}@db.intra:5433/simulation_dashboard\n"
        "POSTGRES_BIN=\"E:\\PostgreSQL\\18\\bin\"\n"
        "WINDOWS_WEB_PORT=8080\nWINDOWS_WEB_BASE_PATH='/home/'\n", encoding="utf-8")
    script = (DEPLOY / "dashboard-env.ps1").as_posix()
    cmd = (f". '{script}'; $d = Get-DashboardRuntimeDefaults -DashboardRoot '{dash.as_posix()}'; "
           "$c = [pscustomobject]@{ pg_bin = ''; pg_port = 6543; python_exe = $null }; "
           "$f = Merge-DashboardDefaults -Config $c -Defaults $d; "
           "[pscustomobject]@{ d = $d; c = $c; filled = @($f) } | ConvertTo-Json -Depth 4 -Compress")
    r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert secret not in r.stdout + r.stderr and "simdashboard_app" not in r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["d"]["PgBin"] == "E:\\PostgreSQL\\18\\bin" and out["d"]["PgHost"] == "db.intra" and out["d"]["PgPort"] == 5433
    assert "cpython-3.12.13-windows-x86_64-none" in out["d"]["PythonExe"]
    assert out["d"]["WebBasePath"] == "/home/"                                # phase3 D3-38: 로그인 링크 경로용
    assert out["d"]["WebPort"] == 8080                                        # phase3 D3-39: update-repo.ps1 끝 접속 주소
    # deploy.json 명시 값(pg_port 6543) 우선, 빈 값만 채움
    assert out["c"]["pg_port"] == 6543 and out["c"]["pg_bin"] == out["d"]["PgBin"] and out["c"]["pg_host"] == "db.intra"
    assert sorted(out["filled"]) == ["pg_bin", "pg_host", "python_exe"]


def test_postgres_server_major(engine):
    """기준 PostgreSQL 주 버전(대시보드와 같은 18). PHYSICSAI_REQUIRE_PG_MAJOR가 있으면(CI) 시험 서버가 그 버전이어야 한다."""
    import os

    from sqlalchemy import text

    with engine.connect() as c:
        num = int(c.execute(text("SHOW server_version_num")).scalar_one())
    want = os.environ.get("PHYSICSAI_REQUIRE_PG_MAJOR")
    if want:
        assert num // 10000 == int(want), num


def test_powershell_syntax():
    """V2-DEP-2: pwsh가 있으면 구문 검사. 없으면 미수행(통과로 치지 않음 — skip)."""
    import os

    pwsh = os.environ.get("PHYSICSAI_PWSH") or shutil.which("pwsh")
    if not pwsh:
        pytest.skip("pwsh 없음 — PowerShell 구문 검사 미수행(사용자 E2E)")
    for f in [*DEPLOY.rglob("*.ps1"), *(REPO / "scripts").glob("*.ps1")]:
        cmd = ("$e=$null; [System.Management.Automation.Language.Parser]::ParseFile('" + str(f) +
               "', [ref]$null, [ref]$e) | Out-Null; if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }")
        r = subprocess.run([pwsh, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (f, r.stdout, r.stderr)
