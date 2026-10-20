"""병행 설치(같은 서버에 설치 두 번째 이상): deploy.json `task_prefix`(기본 PhysicsAI)·`inherit_existing`(기본 true).

PowerShell 실행 시험은 pwsh가 있는 CI 잡에서만 가능하므로 여기서는 (1) setup_config.py 계획(실제 실행) (2) 스크립트 정적 검사로 확인한다.
기본값에서 기존 동작이 그대로이고, 접두사를 주면 작업 이름·안내 문구가 따르며, 이어받기를 끄면 이전 설치 설정을 읽지 않는다."""

from __future__ import annotations

import json
import re

import pytest
import yaml
from physicsai_test_support import REPO
from test_setup_repo import DEPLOY, _fake_tree, _inputs, _run

COMMON = (DEPLOY / "install-common.ps1").read_text(encoding="utf-8-sig")
PS_FILES = sorted(DEPLOY.glob("*.ps1"))
PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,39}$")


def _txt(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8-sig")


def test_example_has_task_prefix_default_and_inherit_true():
    ex = json.loads((DEPLOY / "deploy.example.json").read_text(encoding="utf-8"))
    assert ex["task_prefix"] == "PhysicsAI" and ex["inherit_existing"] is True       # 기본 = 기존 동작


def test_task_names_come_from_prefix_in_one_place():
    """작업 이름 리터럴은 install-common.ps1의 기본 접두사 한 곳뿐 — 다른 스크립트·함수는 Get-PhysicsAITaskNames."""
    assert "$script:PhysicsAITaskPrefix = 'PhysicsAI'" in COMMON
    assert '"$($script:PhysicsAITaskPrefix)-Backend", "$($script:PhysicsAITaskPrefix)-Worker"' in COMMON
    assert "$PhysicsAITaskNames" not in COMMON
    for p in PS_FILES:   # 작업 이름을 따옴표 리터럴로 쓰는 코드가 없다(설명·주석·안내 문구의 기본 이름은 허용)
        assert not re.search(r"""['"]PhysicsAI-(Backend|Worker)['"]""", p.read_text(encoding="utf-8-sig")), p.name
    for name in ("setup.ps1", "install.ps1", "update.ps1", "update-repo.ps1"):
        assert "Set-PhysicsAIDeployOptions -Config $cfg" in _txt(name) or name == "setup.ps1", name
    assert "Set-PhysicsAIDeployOptions -Config" in _txt("setup.ps1") and "Get-Prev 'task_prefix'" in _txt("setup.ps1")


def test_register_stop_start_export_use_prefixed_names():
    for fn in ("Export-PhysicsAITasks", "Get-PhysicsAITaskExecute", "Get-PhysicsAITaskSpecs", "Stop-PhysicsAITasks",
               "Start-PhysicsAITasksAndWait", "Restore-PhysicsAIAfterFailedUpdate", "Get-PhysicsAITaskAdminMessage"):
        body = COMMON[COMMON.index(f"function {fn}"):]
        body = body[:body.index("\nfunction ", 10)] if "\nfunction " in body[10:] else body
        assert "Get-PhysicsAITaskNames" in body, fn
    assert "PhysicsAI-Backend'" not in COMMON.split("function Get-PhysicsAITaskSpecs")[1].split("function Grant-PhysicsAITaskAccess")[0]
    uninstall = _txt("uninstall-tasks.ps1")
    assert "Get-PhysicsAITaskNames" in uninstall and "-TaskPrefix" in uninstall and "task_prefix" in uninstall
    assert "'PhysicsAI-Backend'" not in uninstall


def test_prefix_pattern_matches_between_powershell_and_python():
    ps = re.search(r"\$PhysicsAITaskPrefixPattern = '([^']+)'", COMMON).group(1)
    assert ps == PATTERN.pattern
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("setup_config", DEPLOY / "setup_config.py")
    mod = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # deploy/에 __pycache__를 남기지 않는다(deploy/ 전체 파일을 읽는 정적 시험)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = keep
    assert mod.TASK_PREFIX_RE.pattern == ps
    assert "task_prefix" in mod.DEPLOY_KEY_ORDER and "inherit_existing" in mod.DEPLOY_KEY_ORDER
    for ok in ("PhysicsAI", "PhysicsAI-Dev", "pai_2.test"):
        assert PATTERN.fullmatch(ok), ok
    for bad in ("", "1abc", "a b", "a\\b", "a" * 41, "한글"):
        assert not PATTERN.fullmatch(bad), bad


def test_inherit_existing_false_disables_machine_env_and_protects_foreign_tasks():
    db = COMMON[COMMON.index("function Get-PhysicsAIDbUrl"):COMMON.index("function Protect-PhysicsAISecretPath")]
    assert db.index("Test-PhysicsAIInheritExisting") < db.index("Get-PhysicsAIMachineEnv 'PHYSICSAI_DATABASE_URL'")
    mv = COMMON[COMMON.index("function Move-PhysicsAIMachineEnvToRuntime"):COMMON.index("function Write-PhysicsAIMachineEnvWarning")]
    assert mv.index("Test-PhysicsAIInheritExisting") < mv.index("Get-PhysicsAIMachineEnv")
    free = COMMON[COMMON.index("function Assert-PhysicsAITaskNamesFree"):COMMON.index("function Invoke-PhysicsAIMigration")]
    assert "if (Test-PhysicsAIInheritExisting) { return }" in free and "task_prefix" in free and "throw" in free
    # 이어받기를 끄면 기존 작업을 중지·삭제·재등록하기 전에(setup: 중지 앞, install: venv 만들기 앞) 확인한다
    s, i = _txt("setup.ps1"), _txt("install.ps1")
    assert s.index("Assert-PhysicsAITaskNamesFree") < s.index("Stop-PhysicsAITasks") < s.index("Register-PhysicsAITasks")
    assert i.index("Assert-PhysicsAITaskNamesFree") < i.index("Register-PhysicsAITasks")
    assert "Test-PhysicsAIInheritExisting) { Get-PhysicsAIMachineEnv 'PHYSICSAI_CONFIG'" in s     # 묶음 설치 설정 이어받기도 끔
    assert "[switch]$NoInherit" in s and "[string]$TaskPrefix" in s and "inherit_existing" in s


def test_machine_env_database_url_warning_on_install():
    w = COMMON[COMMON.index("function Write-PhysicsAIMachineEnvWarning"):COMMON.index("function Assert-PhysicsAITaskNamesFree")]
    assert "Get-PhysicsAIMachineEnv 'PHYSICSAI_DATABASE_URL'" in w and "Write-Warning" in w and "값은 출력하지 않음" in w
    assert "SetEnvironmentVariable('PHYSICSAI_DATABASE_URL'" in w                       # 지우는 방법만 안내(스스로 쓰지 않음)
    for name in ("setup.ps1", "install.ps1"):
        assert "Write-PhysicsAIMachineEnvWarning" in _txt(name), name


def test_plan_task_prefix_and_inherit_roundtrip(tmp_path):
    t = _fake_tree(tmp_path)
    inp = _inputs(t)
    inp["deploy_defaults"].update(task_prefix="PhysicsAI", inherit_existing=True)
    res = _run(tmp_path, t, inp)
    dj = json.loads((t["rt"] / "deploy.json").read_text(encoding="utf-8"))
    assert dj["task_prefix"] == "PhysicsAI" and dj["inherit_existing"] is True and list(dj)[-2:] == ["task_prefix", "inherit_existing"]
    assert res["deploy"]["task_prefix"] == "PhysicsAI"
    # 명시 값이 기존 파일 값을 바꾸고, 다시 실행해도 유지
    inp2 = _inputs(t)
    inp2["deploy_explicit"] = {"task_prefix": "PhysicsAI-Dev", "inherit_existing": False}
    res2 = _run(tmp_path, t, inp2)
    assert {"task_prefix", "inherit_existing"} <= set(res2["deploy_overridden"])
    res3 = _run(tmp_path, t, _inputs(t))
    dj3 = json.loads((t["rt"] / "deploy.json").read_text(encoding="utf-8"))
    assert dj3["task_prefix"] == "PhysicsAI-Dev" and dj3["inherit_existing"] is False and not res3["deploy_changed"]


def test_plan_inherit_false_ignores_legacy_config(tmp_path):
    t = _fake_tree(tmp_path)
    legacy = tmp_path / "old" / "platform.yaml"
    legacy.parent.mkdir()
    legacy.write_text("schema_version: 1\nprofile: prod\nserver:\n  port: 9999\n", encoding="utf-8")
    inherit = _run(tmp_path, t, _inputs(t, legacy_config=str(legacy)))
    assert inherit["config_source"] == "legacy"                                                   # 기본 = 이어받음(기존 동작)
    t2 = _fake_tree(tmp_path / "second")
    inp = _inputs(t2, legacy_config=str(legacy))
    inp["deploy_explicit"] = {"inherit_existing": False}
    res = _run(tmp_path / "second", t2, inp)
    assert res["config_source"] == "example"                                                      # 끄면 새 예시에서 시작
    assert yaml.safe_load((t2["rt"] / "config" / "platform.yaml").read_text(encoding="utf-8"))["server"]["port"] == 8100


@pytest.mark.parametrize("key,value", [("task_prefix", "bad prefix"), ("task_prefix", "1x"), ("inherit_existing", "false")])
def test_plan_rejects_invalid_values(tmp_path, key, value):
    import subprocess
    import sys
    t = _fake_tree(tmp_path)
    inp = _inputs(t)
    inp["deploy_explicit"] = {key: value}
    f = tmp_path / "in.json"
    f.write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(DEPLOY / "setup_config.py"), "plan", "--inputs", str(f), "--out", str(tmp_path / "o.json")],
                       capture_output=True, text=True, encoding="utf-8", timeout=120,
                       env={"PYTHONPATH": ":".join(str(REPO / p) for p in ("backend", "worker", "packages/simdash_adapters/src")), "PATH": ""})
    assert r.returncode != 0 and ("task_prefix" in (r.stdout + r.stderr) or "inherit_existing" in (r.stdout + r.stderr))
