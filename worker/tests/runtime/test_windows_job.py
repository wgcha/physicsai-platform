"""V-JO-1~3 실제 Windows Job Object 시험(@pytest.mark.windows). Linux에서는 skip = 미수행(통과로 치지 않음).

CI(windows 잡)는 PHYSICSAI_REQUIRE_WINDOWS_TESTS=1로 실행해 이 시험이 skip되면 실패로 바꾼다.
- V-JO-1 CPU hard cap: 바쁜 자식 N개를 Job CPU rate 20%로 돌려 Job 누적 CPU 시간이 상한 근처에 머무는지
- V-JO-2 메모리 상한: Job 메모리 한도(256 MiB)를 넘는 할당이 MemoryError로 거부되는지
- V-JO-3 취소 시 프로세스 트리 종료: 손자까지 TerminateJobObject로 종료, 핸들 닫기(KILL_ON_JOB_CLOSE)로도 종료
- CREATE_SUSPENDED 경로: 일시정지 상태에서 Job에 먼저 들어가고, 재개 전에는 한 줄도 실행되지 않는지
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil
import pytest

from physicsai_core.limits import EffectiveLimits

pytestmark = [pytest.mark.windows, pytest.mark.skipif(os.name != "nt", reason="Windows 전용 — Linux에서는 미수행(사용자 E2E·CI windows 잡)")]

CORES = os.cpu_count() or 1


def _measure(name: str, **values) -> None:
    """실측값 기록(CI가 PHYSICSAI_CI_MEASURE_FILE을 주면 ::notice로 남긴다)."""
    import json

    f = os.environ.get("PHYSICSAI_CI_MEASURE_FILE")
    if f:
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"test": name, **values}) + "\n")


def _limits(cpu_rate: int = 10000, memory_gb: float = 4.0) -> EffectiveLimits:
    return EffectiveLimits(cores=CORES, cpu_rate=cpu_rate, memory_gb=memory_gb, priority="below_normal",
                           detected_cores=CORES, detected_memory_gb=16.0)


def _k32():
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def _in_job(pid: int, job) -> bool:
    import ctypes
    from ctypes import wintypes

    k = _k32()
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    assert h, f"OpenProcess 실패: {pid}"
    try:
        res = wintypes.BOOL(False)
        assert k.IsProcessInJob(h, job, ctypes.byref(res))
        return bool(res.value)
    finally:
        k.CloseHandle(h)


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).is_running() and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _wait_dead(pids, timeout=15.0) -> list[int]:
    end = time.time() + timeout
    while time.time() < end:
        left = [p for p in pids if _alive(p)]
        if not left:
            return []
        time.sleep(0.1)
    return [p for p in pids if _alive(p)]


# 자식 → 손자 트리를 만들고 pid를 출력한 뒤 대기
TREE = [sys.executable, "-c",
        "import subprocess,sys,time\n"
        "c=subprocess.Popen([sys.executable,'-c',\"import subprocess,sys,time\\n"
        "g=subprocess.Popen([sys.executable,'-c','import time\\\\nwhile 1: time.sleep(1)'])\\n"
        "print(g.pid,flush=True)\\nwhile 1: time.sleep(1)\"],stdout=subprocess.PIPE,text=True)\n"
        "g=c.stdout.readline().strip()\n"
        "print(c.pid,g,flush=True)\n"
        "while 1: time.sleep(1)"]


def _tree(lim, limits):
    p = lim.launch(TREE, os.getcwd(), dict(os.environ), limits)
    line = p.stdout.readline().split()
    assert len(line) == 2, line
    return p, [p.pid, int(line[0]), int(line[1])]


def test_vjo1_cpu_hard_cap():
    """V-JO-1: CPU rate 20%(hard cap)에서 바쁜 자식 N개(=논리 코어 수)를 4초간 돌리면 누적 CPU ≪ 무제한 기대값."""
    from physicsai_worker.limiter.windows_job import WindowsJobLimiter

    wall = 4.0
    n = max(1, CORES)
    busy = (f"import subprocess,sys\n"
            f"code='import time\\nend=time.time()+{wall}\\nwhile time.time()<end: pass'\n"
            f"ps=[subprocess.Popen([sys.executable,'-c',code]) for _ in range({n})]\n"
            f"[p.wait() for p in ps]\nprint('done',flush=True)")
    lim = WindowsJobLimiter()
    p = lim.launch([sys.executable, "-c", busy], os.getcwd(), dict(os.environ), _limits(cpu_rate=2000))
    try:
        assert p.wait(timeout=120) == 0
        acc = lim.accounting(p)
    finally:
        lim.close(p)
    uncapped = n * wall
    _measure("V-JO-1", cores=n, cpu_rate_pct=20, wall_s=wall, job_cpu_s=round(acc.cpu_time_s or 0, 2),
             uncapped_cpu_s=uncapped, ratio=round((acc.cpu_time_s or 0) / uncapped, 3))
    assert acc.cpu_cap_enforced and acc.cpu_time_s is not None and acc.cpu_time_s > 0
    # 상한 20% → 이론값 0.2 × N × wall. 여유를 두되 무제한(N × wall)의 45% 미만이어야 한다
    assert acc.cpu_time_s < 0.45 * uncapped, (acc.cpu_time_s, uncapped, n)


def test_vjo2_memory_limit():
    """V-JO-2: Job 메모리 한도 256 MiB — 64 MiB는 되고 512 MiB 할당은 MemoryError(종료코드 3)."""
    from physicsai_worker.limiter.windows_job import WindowsJobLimiter

    code = ("import sys\na=bytearray(64*2**20)\n"
            "try:\n    b=bytearray(512*2**20)\nexcept MemoryError:\n    print('limited',flush=True); sys.exit(3)\n"
            "print('unlimited',flush=True); sys.exit(0)")
    lim = WindowsJobLimiter()
    p = lim.launch([sys.executable, "-c", code], os.getcwd(), dict(os.environ), _limits(memory_gb=0.25))
    try:
        out = p.stdout.read()
        rc = p.wait(timeout=60)
        acc = lim.accounting(p)
    finally:
        lim.close(p)
    assert rc == 3 and "limited" in out, (rc, out)
    # PeakJobMemoryUsed는 거부된 요청까지 반영될 수 있어(실측 ≈ 64 MiB + 512 MiB) 한도 도달 표시만 확인
    assert acc.peak_memory_bytes is not None and acc.memory_limit_hit, acc
    _measure("V-JO-2", limit_mib=256, peak_mib=round(acc.peak_memory_bytes / 2**20, 1), rc=rc)


def test_vjo3_cancel_kills_tree_and_kill_on_close():
    """V-JO-3: terminate(TerminateJobObject)로 자식·손자 모두 종료 / 핸들만 닫아도(KILL_ON_JOB_CLOSE) 트리 종료."""
    from physicsai_worker.limiter.windows_job import WindowsJobLimiter

    lim = WindowsJobLimiter()
    p, pids = _tree(lim, _limits())
    for pid in pids:
        assert _in_job(pid, p.handle), pid  # 손자까지 같은 Job(BREAKAWAY 불허)
    lim.terminate(p, timeout_s=15)
    assert p.poll() is not None
    assert _wait_dead(pids) == []
    lim.close(p)

    p2, pids2 = _tree(lim, _limits())
    lim.close(p2)  # 워커가 죽어 Job 핸들이 닫히는 경우
    assert _wait_dead(pids2) == []


def test_create_suspended_assign_before_resume(tmp_path):
    """CREATE_SUSPENDED: Popen은 일시정지 플래그로 시작, Job 할당이 재개보다 먼저, 재개 전에는 실행되지 않는다."""
    from physicsai_worker.limiter import windows_job as wj

    marker = tmp_path / "started.txt"
    flags: list[int] = []
    seen: dict[str, bool] = {}

    def popen(*a, **kw):
        flags.append(kw["creationflags"])
        return subprocess.Popen(*a, **kw)

    class Spy(wj.WindowsJobLimiter):
        def _create_job(self, limits):
            self.job = super()._create_job(limits)
            return self.job

        def _resume_main_thread(self, pid):
            time.sleep(0.5)
            seen["in_job_before_resume"] = _in_job(pid, self.job)
            seen["ran_before_resume"] = marker.exists()
            super()._resume_main_thread(pid)

    lim = Spy(popen=popen)
    p = lim.launch([sys.executable, "-c", f"open(r'{marker}','w').write('x')"], os.getcwd(), dict(os.environ), _limits())
    try:
        assert p.wait(timeout=60) == 0
    finally:
        lim.close(p)
    assert flags and flags[0] & wj.CREATE_SUSPENDED
    assert seen == {"in_job_before_resume": True, "ran_before_resume": False}
    assert marker.read_text() == "x"


def test_select_limiter_auto_is_windows_job():
    from physicsai_core.config import WorkerCfg
    from physicsai_worker.limiter import select_limiter

    lim = select_limiter(WorkerCfg(limiter="auto"), "dev")
    assert lim.name == "windows_job" and lim.cpu_cap_enforced is True
