"""V-JO-1~6: 제한기. Windows Job Object 실제 시험은 @pytest.mark.windows(Linux skip = 미수행)."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil
import pytest

from physicsai_core.limits import compute_limits
from physicsai_worker.limiter.base import LimiterError
from physicsai_worker.limiter.posix import PosixLimiter
from physicsai_worker.limiter.windows_job import (
    BELOW_NORMAL_PRIORITY_CLASS,
    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE,
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
    LIMIT_FLAGS,
    WindowsJobLimiter,
)

LIM = compute_limits(4, 2, "below_normal", False, 0.7, 8, 16)
HANG = [sys.executable, "-c", "import subprocess,sys,time\nc=subprocess.Popen([sys.executable,'-c','import time\\nwhile 1: time.sleep(1)'])\nprint(c.pid, flush=True)\nwhile 1: time.sleep(1)"]


def test_posix_nice_tree_kill_and_flags():
    lim = PosixLimiter()
    assert lim.cpu_cap_enforced is False and lim.name == "posix"
    p = lim.launch(HANG, os.getcwd(), dict(os.environ), LIM)
    child = int(p.stdout.readline())
    assert psutil.Process(p.pid).nice() >= 10
    assert os.getpgid(p.pid) == p.pid  # 새 세션·프로세스 그룹
    lim.terminate(p, timeout_s=10)
    time.sleep(0.2)
    for pid in (p.pid, child):
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    acc = lim.accounting(p)
    assert acc.cpu_cap_enforced is False
    lim.close(p)


def test_posix_accounting_and_rlimit():
    lim = PosixLimiter(rlimit_as=True)
    p = lim.launch([sys.executable, "-c", "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0])"], os.getcwd(), dict(os.environ), LIM)
    out = p.stdout.read()
    p.wait()
    assert int(out.strip()) == int(2 * 2**30)
    lim.close(p)


def test_posix_missing_executable():
    with pytest.raises(LimiterError) as ei:
        PosixLimiter().launch(["/nonexistent/exe"], os.getcwd(), dict(os.environ), LIM)
    assert ei.value.code == "EXECUTABLE_MISSING"


class FakeKernel32:
    """V-JO-4: kernel32 주입. AssignProcessToJobObject 실패를 모사."""

    def __init__(self, assign_ok=False):
        self.calls = []
        self.assign_ok = assign_ok
        self.terminated = False

    def CreateJobObjectW(self, *_):
        self.calls.append("CreateJobObjectW")
        return 1234

    def SetInformationJobObject(self, job, cls, ptr, size):
        self.calls.append(("Set", cls))
        info = ptr._obj
        if cls == 9:
            assert info.BasicLimitInformation.LimitFlags == LIMIT_FLAGS
            assert info.BasicLimitInformation.PriorityClass == BELOW_NORMAL_PRIORITY_CLASS
            assert info.JobMemoryLimit == 2 * 2**30
        if cls == 15:
            assert info.ControlFlags == JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            assert info.CpuRate == 5000
        return 1

    def AssignProcessToJobObject(self, job, handle):
        self.calls.append("Assign")
        return 1 if self.assign_ok else 0

    def TerminateProcess(self, handle, code):
        self.calls.append("TerminateProcess")
        self.terminated = True
        return 1

    def CloseHandle(self, h):
        self.calls.append("Close")
        return 1


class FakePopen:
    started = []

    def __init__(self, argv, **kw):
        assert kw["creationflags"] & 0x4  # CREATE_SUSPENDED
        assert kw["shell"] is False
        self.pid = 4242
        self._handle = 99
        FakePopen.started.append(argv)

    def wait(self, timeout=None):
        return 1

    def poll(self):
        return 1


def test_job_assign_failure_never_runs_unlimited():
    k = FakeKernel32(assign_ok=False)
    lim = WindowsJobLimiter(kernel32=k, popen=FakePopen)
    with pytest.raises(LimiterError) as ei:
        lim.launch(["edspy.bat"], ".", {}, LIM)
    assert ei.value.code == "JOB_OBJECT_ASSIGN_FAILED"
    assert k.terminated and "Assign" in k.calls and k.calls.index("Assign") < k.calls.index("TerminateProcess")
    assert ("Set", 9) in k.calls and ("Set", 15) in k.calls


def test_select_limiter_rules():
    from physicsai_core.config import WorkerCfg
    from physicsai_worker.limiter import select_limiter

    assert select_limiter(WorkerCfg(limiter="posix"), "dev").name == "posix"
    assert select_limiter(WorkerCfg(limiter="null"), "dev").name == "null"
    with pytest.raises(LimiterError):
        select_limiter(WorkerCfg(limiter="null"), "prod")
    if os.name != "nt":
        assert select_limiter(WorkerCfg(limiter="auto"), "dev").name == "posix"


@pytest.mark.windows
@pytest.mark.skipif(os.name != "nt", reason="Windows 전용 — Linux에서는 미수행(사용자 E2E)")
def test_windows_job_object_real():  # pragma: no cover - Windows에서만
    """V-JO-1~3: 실제 Job Object 한도·손자 프로세스 포함·TerminateJobObject."""
    import ctypes

    lim = WindowsJobLimiter()
    p = lim.launch(HANG, os.getcwd(), dict(os.environ), LIM)
    child = int(p.stdout.readline())
    k = ctypes.WinDLL("kernel32")
    for pid in (p.pid, child):
        h = k.OpenProcess(0x1000, False, pid)
        res = ctypes.c_int()
        k.IsProcessInJob(h, p.handle, ctypes.byref(res))
        assert res.value
    lim.terminate(p)
    assert not psutil.pid_exists(child)
    lim.close(p)


def test_worker_single_instance_lock(tmp_path):
    from physicsai_worker.lockfile import AlreadyRunning, InstanceLock

    a = InstanceLock(str(tmp_path))
    a.acquire()
    code = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from physicsai_worker.lockfile import InstanceLock, AlreadyRunning\n"
         "try:\n InstanceLock(sys.argv[2]).acquire()\nexcept AlreadyRunning:\n sys.exit(2)\n", str(os.path.dirname(os.path.dirname(__import__('physicsai_worker').__file__))), str(tmp_path)],
    ).returncode
    assert code == 2
    a.release()
    b = InstanceLock(str(tmp_path))
    b.acquire()
    b.release()
    del AlreadyRunning


def test_worker_main_refuses_invalid_config(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("schema_version: 2\n")
    from physicsai_worker.__main__ import main

    assert main(["--config", str(cfg)]) == 2


def test_config_change_pauses_claims(engine, settings_dict, tmp_path):
    """V-CFG-2: 설정 파일이 바뀌면 다시 읽고, 검증 실패면 새 claim 중지."""
    import yaml

    from physicsai_core.config import load_config
    from physicsai_worker.runtime import Worker

    p = tmp_path / "platform.yaml"
    p.write_text(yaml.safe_dump(settings_dict, allow_unicode=True), encoding="utf-8")
    w = Worker(load_config(str(p)), engine, config_path=str(p))
    assert not w.claims_paused
    bad = dict(settings_dict)
    bad["worker"] = {**bad["worker"], "max_logical_cores": 0}
    p.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    assert w.run_once_slot() is None and w.claims_paused
    w.heartbeat_once()
    good = dict(settings_dict)
    good["worker"] = {**good["worker"], "max_logical_cores": 2}
    p.write_text(yaml.safe_dump(good, allow_unicode=True), encoding="utf-8")
    w.run_once_slot()
    assert not w.claims_paused and w.limits.cores <= 2
