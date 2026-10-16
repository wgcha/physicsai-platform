"""동시 실행 그룹(phase3 §14.5, V3-S9-13): Windows(가짜 kernel32) Job 1개에 N프로세스·한도 1배, POSIX 메모리 한도/M,
null 그룹 종료. run_parallel 구조(null 제한기 BP_GEN)는 stage4_predict/test_predict_batch.py."""

from __future__ import annotations

import os
import sys
import time

import psutil
import pytest
from physicsai_core.limits import compute_limits
from physicsai_worker.limiter.null import NullLimiter
from physicsai_worker.limiter.posix import PosixLimiter
from physicsai_worker.limiter.windows_job import WindowsJobLimiter

LIM = compute_limits(4, 2, "below_normal", False, 0.7, 8, 16)   # memory 2 GiB, cpu_rate 5000
HANG = [sys.executable, "-c", "import subprocess,sys,time\nc=subprocess.Popen([sys.executable,'-c','import time\\nwhile 1: time.sleep(1)'])\nprint(c.pid, flush=True)\nwhile 1: time.sleep(1)"]


class K32:
    """kernel32 주입: Job 생성·할당·종료·닫기와 메모리 한도를 기록."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.next_job = 1000
        self.mem: dict[int, int] = {}
        self.terminated: set[int] = set()

    def CreateJobObjectW(self, *_):
        self.next_job += 1
        self.calls.append(("CreateJob", self.next_job))
        return self.next_job

    def SetInformationJobObject(self, job, cls, ptr, size):
        if cls == 9:
            self.mem[job] = int(ptr._obj.JobMemoryLimit)
        return 1

    def AssignProcessToJobObject(self, job, handle):
        self.calls.append(("Assign", job, handle))
        return 1

    def CreateToolhelp32Snapshot(self, *_):
        return 55

    def Thread32First(self, snap, ptr):
        ptr._obj.th32OwnerProcessID = self._pid
        ptr._obj.th32ThreadID = 7
        return 1

    def Thread32Next(self, snap, ptr):
        return 0

    def OpenThread(self, *_):
        return 77

    def ResumeThread(self, h):
        return 1

    def TerminateJobObject(self, job, code):
        self.calls.append(("TerminateJob", job))
        self.terminated.add(job)
        return 1

    def TerminateProcess(self, h, code):
        self.calls.append(("TerminateProcess", h))
        return 1

    def QueryInformationJobObject(self, job, cls, ptr, size, ret):
        self.calls.append(("Query", job))
        return 0

    def CloseHandle(self, h):
        self.calls.append(("Close", h))
        return 1


def _popen_factory(k: K32, jobs_of: dict[int, int]):
    class Pop:
        n = 0

        def __init__(self, argv, **kw):
            assert kw["shell"] is False and kw["creationflags"] & 0x4
            Pop.n += 1
            self.pid, self._handle = 5000 + Pop.n, 900 + Pop.n
            k._pid = self.pid
            self.stdout = iter(())

        def poll(self):
            return 1 if k.terminated else None

        def wait(self, timeout=None):
            return 1

    return Pop


def test_v3_s9_13_windows_group_one_job_for_n_processes():
    k = K32()
    lim = WindowsJobLimiter(kernel32=k, popen=_popen_factory(k, {}))
    g = lim.open_group(LIM, 3)
    procs = [lim.launch(["SimLab.bat", "-auto", f"r{i}.py"], ".", {}, LIM, group=g) for i in range(3)]
    creates = [c for c in k.calls if c[0] == "CreateJob"]
    assigns = [c for c in k.calls if c[0] == "Assign"]
    assert len(creates) == 1 and g.handle == creates[0][1]                       # Job 1개
    assert [a[1] for a in assigns] == [g.handle] * 3                              # 3프로세스 모두 그 Job에
    assert k.mem[g.handle] == 2 * 2**30                                           # 한도 1배(동시 수로 나누지 않음)
    assert g.launched == 3 and len(g.alive()) == 3
    for p in procs:
        lim.accounting(p)
        lim.close(p)                                                              # 프로세스 close는 Job을 닫지 않는다
    assert ("Close", g.handle) not in k.calls
    assert all(c[1] == g.handle for c in k.calls if c[0] == "Query")             # 회계는 그룹 Job 기준
    lim.terminate_group(g, timeout_s=1)
    assert [c for c in k.calls if c[0] == "TerminateJob"] == [("TerminateJob", g.handle)]
    assert not g.alive()
    lim.close_group(g)
    assert ("Close", creates[0][1]) in k.calls and g.closed and g.handle is None
    with pytest.raises(Exception):                                                # 닫힌 그룹에는 시작하지 않는다
        lim.launch(["x"], ".", {}, LIM, group=g)
    # 그룹 없는 launch는 기존대로 프로세스마다 Job
    lim.launch(["edspy.bat"], ".", {}, LIM)
    assert len([c for c in k.calls if c[0] == "CreateJob"]) == 2


@pytest.mark.posix
def test_v3_s9_13_posix_group_memory_split_and_terminate():
    lim = PosixLimiter(rlimit_as=True)
    g = lim.open_group(LIM, 4)
    p = lim.launch([sys.executable, "-c", "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0])"], os.getcwd(),
                   dict(os.environ), LIM, group=g)
    out = p.stdout.read()
    p.wait()
    lim.close(p)
    assert int(out.strip()) == int(2 * 2**30 / 4)                                 # 메모리 = 한도/M
    hs = [lim.launch(HANG, os.getcwd(), dict(os.environ), LIM, group=g) for _ in range(2)]
    kids = [int(h.stdout.readline()) for h in hs]
    lim.terminate_group(g, timeout_s=10)
    time.sleep(0.2)
    for pid in [h.pid for h in hs] + kids:
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    acc = lim.group_accounting(g)
    assert acc.cpu_cap_enforced is False
    for h in hs:
        lim.close(h)
    lim.close_group(g)


def test_v3_s9_13_null_group_terminate_tree():
    lim = NullLimiter()
    g = lim.open_group(LIM, 2)
    assert g.limits.memory_gb == pytest.approx(1.0)
    hs = [lim.launch(HANG, os.getcwd(), dict(os.environ), LIM, group=g) for _ in range(2)]
    kids = [int(h.stdout.readline()) for h in hs]
    assert g.launched == 2
    lim.terminate_group(g, timeout_s=10)
    time.sleep(0.2)
    for pid in [h.pid for h in hs] + kids:
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
