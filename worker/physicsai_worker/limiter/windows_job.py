"""WindowsJobLimiter(§11.5): step 프로세스마다 Job Object 1개(ctypes kernel32, pywin32 미사용).

- KILL_ON_JOB_CLOSE | JOB_MEMORY | PRIORITY_CLASS | DIE_ON_UNHANDLED_EXCEPTION, BREAKAWAY 불허(손자까지 Job 안)
- CPU rate hard cap, GPU 무제한
- CREATE_SUSPENDED로 시작 → AssignProcessToJobObject → 주 스레드 ResumeThread
- 할당 실패 시 TerminateProcess 후 JOB_OBJECT_ASSIGN_FAILED — 제한 없이 실행하는 경로는 없다
- 동시 실행 그룹(phase3 §14.5 `run_parallel`): `open_group`이 Job 1개를 만들고 그룹의 모든 프로세스를 그 Job에 넣는다
  (hstbatch `-multiexec`처럼 작업 1개분 CPU·메모리 한도를 나눠 씀). 그룹 취소 = TerminateJobObject 1번, 닫기 = KILL_ON_JOB_CLOSE
kernel32·Popen은 주입 가능(Linux 단위 시험 V-JO-4, V3-S9-13).
300줄 분할(R-B): Win32 상수·ctypes 구조체·kernel32 적재는 `windows_job_api`(여기서 재노출)."""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes
from typing import Any, Callable

from physicsai_core.limits import EffectiveLimits

from .base import POPEN_TEXT_KW, Accounting, LimitedProcess, LimiterError, ProcGroup
from .windows_job_api import (  # noqa: F401 - 기존 경로 재노출
    JobObjectBasicAccountingInformation, JobObjectExtendedLimitInformation, JobObjectCpuRateControlInformation,
    JOB_OBJECT_LIMIT_PRIORITY_CLASS, JOB_OBJECT_LIMIT_JOB_MEMORY, JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_CPU_RATE_CONTROL_ENABLE, JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
    IDLE_PRIORITY_CLASS, BELOW_NORMAL_PRIORITY_CLASS, NORMAL_PRIORITY_CLASS, PRIORITY, CREATE_SUSPENDED,
    CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW, TH32CS_SNAPTHREAD, THREAD_SUSPEND_RESUME, INVALID_HANDLE_VALUE,
    RESUME_FAILED, LIMIT_FLAGS, JOBOBJECT_BASIC_LIMIT_INFORMATION, IO_COUNTERS, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOBOBJECT_CPU_RATE_CONTROL_INFORMATION, JOBOBJECT_BASIC_ACCOUNTING_INFORMATION, THREADENTRY32, _load_kernel32,
)


class WindowsJobLimiter:
    name = "windows_job"
    cpu_cap_enforced = True

    def __init__(self, kernel32: Any = None, popen: Callable[..., subprocess.Popen] | None = None) -> None:
        self.k = kernel32 if kernel32 is not None else _load_kernel32()
        self.popen = popen or subprocess.Popen

    # --- Job 생성·설정 ---
    def _create_job(self, limits: EffectiveLimits) -> Any:
        job = self.k.CreateJobObjectW(None, None)
        if not job:
            raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "Job Object를 만들 수 없습니다")
        ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ext.BasicLimitInformation.LimitFlags = LIMIT_FLAGS
        ext.BasicLimitInformation.PriorityClass = PRIORITY.get(limits.priority, BELOW_NORMAL_PRIORITY_CLASS)
        ext.JobMemoryLimit = int(limits.memory_gb * 2**30)
        if not self.k.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(ext), ctypes.sizeof(ext)):
            self.k.CloseHandle(job)
            raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "Job 메모리·우선순위 한도 설정 실패")
        cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        cpu.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
        cpu.CpuRate = int(limits.cpu_rate)
        if not self.k.SetInformationJobObject(job, JobObjectCpuRateControlInformation, ctypes.byref(cpu), ctypes.sizeof(cpu)):
            self.k.CloseHandle(job)
            raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "Job CPU 상한 설정 실패")
        return job

    def _resume_main_thread(self, pid: int) -> None:
        snap = self.k.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if not snap or snap == INVALID_HANDLE_VALUE:
            raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "스레드 스냅샷 실패")
        try:
            te = THREADENTRY32()
            te.dwSize = ctypes.sizeof(THREADENTRY32)
            ok = self.k.Thread32First(snap, ctypes.byref(te))
            resumed = False
            while ok:
                if te.th32OwnerProcessID == pid:
                    h = self.k.OpenThread(THREAD_SUSPEND_RESUME, False, te.th32ThreadID)
                    if not h:
                        raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "주 스레드를 열지 못했습니다(OpenThread 실패)")
                    try:
                        rc = self.k.ResumeThread(h)
                    finally:
                        self.k.CloseHandle(h)
                    if rc in (RESUME_FAILED, -1):
                        raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "주 스레드를 재개하지 못했습니다(ResumeThread = -1)")
                    resumed = True
                ok = self.k.Thread32Next(snap, ctypes.byref(te))
            if not resumed:
                raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "주 스레드를 재개하지 못했습니다")
        finally:
            self.k.CloseHandle(snap)

    def launch(self, argv: list[str], cwd: str, env: dict[str, str], limits: EffectiveLimits,
               group: ProcGroup | None = None) -> LimitedProcess:
        """group이 있으면 그 Job(작업 1개분 한도)에 넣는다 — 프로세스마다 Job을 새로 만들지 않는다(phase3 §14.5)."""
        if group is not None and (group.closed or not group.handle):
            raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "동시 실행 그룹이 닫혀 프로세스를 시작하지 않았습니다")
        job = group.handle if group is not None else self._create_job(limits)
        own_job = group is None
        flags = CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        try:
            p = self.popen(argv, cwd=cwd, env=env, creationflags=flags, **POPEN_TEXT_KW)
        except OSError as exc:
            if own_job:
                self.k.CloseHandle(job)
            raise LimiterError("EXECUTABLE_MISSING", f"프로세스를 시작할 수 없습니다: {exc}") from None
        handle = getattr(p, "_handle", None)
        if not self.k.AssignProcessToJobObject(job, handle):
            try:
                self.k.TerminateProcess(handle, 1)
            finally:
                try:
                    p.wait(timeout=10)
                except Exception:
                    pass
                if own_job:
                    self.k.CloseHandle(job)
            raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "프로세스를 Job Object에 넣지 못해 실행하지 않았습니다")
        try:
            self._resume_main_thread(p.pid)
        except LimiterError:
            # 재개 실패: 일시정지 상태 프로세스를 남기지 않는다 → TerminateProcess(+ 자기 Job 종료), step FAILED(JOB_OBJECT_ASSIGN_FAILED)
            try:
                self.k.TerminateProcess(handle, 1)
                if own_job:
                    self.k.TerminateJobObject(job, 1)
            finally:
                try:
                    p.wait(timeout=10)
                except Exception:
                    pass
                if own_job:
                    self.k.CloseHandle(job)
            raise
        mem = int((group.limits if group is not None else limits).memory_gb * 2**30)
        if group is None:
            return LimitedProcess(p, handle=job, extra={"memory_limit": mem})
        proc = LimitedProcess(p, handle=None, extra={"memory_limit": mem, "group": group})
        group.add(proc)
        return proc

    # --- 동시 실행 그룹(phase3 §14.5) ---
    def open_group(self, limits: EffectiveLimits, size: int) -> ProcGroup:
        """Job 1개(작업 1개분 한도 그대로 — 동시 수로 나누지 않음, CPU·메모리를 그룹이 나눠 씀)."""
        return ProcGroup(size=max(1, int(size)), limits=limits, handle=self._create_job(limits), shared_accounting=True)

    def terminate_group(self, group: ProcGroup, timeout_s: float = 30) -> None:
        if group.handle:
            self.k.TerminateJobObject(group.handle, 1)
        deadline = time.time() + timeout_s
        while time.time() < deadline and group.alive():
            time.sleep(0.1)

    def group_accounting(self, group: ProcGroup) -> Accounting:
        return self._job_accounting(group.handle, int(group.limits.memory_gb * 2**30))

    def close_group(self, group: ProcGroup) -> None:
        """핸들을 닫는다(KILL_ON_JOB_CLOSE — 남은 프로세스도 종료)."""
        group.closed = True
        if group.handle:
            self.k.CloseHandle(group.handle)
            group.handle = None

    def terminate(self, proc: LimitedProcess, timeout_s: float = 30) -> None:
        group = proc.extra.get("group")
        if proc.handle:
            self.k.TerminateJobObject(proc.handle, 1)
        elif group is not None:  # 그룹 안 프로세스 1개만: 그 프로세스만 종료(그룹 전체는 terminate_group)
            self.k.TerminateProcess(getattr(proc.popen, "_handle", None), 1)
        deadline = time.time() + timeout_s
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.1)

    def _job_accounting(self, job: Any, limit: int) -> Accounting:
        ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        acc = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        peak = cpu = None
        if job and self.k.QueryInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(ext), ctypes.sizeof(ext), None):
            peak = int(ext.PeakJobMemoryUsed)
        if job and self.k.QueryInformationJobObject(job, JobObjectBasicAccountingInformation, ctypes.byref(acc), ctypes.sizeof(acc), None):
            cpu = (acc.TotalUserTime + acc.TotalKernelTime) / 1e7
        hit = bool(peak and limit and peak >= 0.98 * limit)
        return Accounting(peak_memory_bytes=peak, cpu_time_s=cpu, cpu_cap_enforced=True, memory_limit_hit=hit)

    def accounting(self, proc: LimitedProcess) -> Accounting:
        group = proc.extra.get("group")
        job = proc.handle if proc.handle else (group.handle if group is not None else None)
        return self._job_accounting(job, proc.extra.get("memory_limit") or 0)

    def close(self, proc: LimitedProcess) -> None:
        """그룹 안 프로세스는 Job 핸들을 공유하므로 닫지 않는다(close_group이 닫음)."""
        if proc.handle:
            self.k.CloseHandle(proc.handle)
            proc.handle = None


def self_test(limiter: Any, limits: EffectiveLimits, argv: list[str]) -> dict[str, Any]:
    """환경 점검 worker.job_object(phase2 §9.3): 고정 인자 [sys.executable, "-I", "-c", "pass"]를 제한기로 실행해
    IsProcessInJob + QueryInformationJobObject(CPU rate·메모리 한도·KILL_ON_JOB_CLOSE)를 확인한다. Windows 전용."""
    if not isinstance(limiter, WindowsJobLimiter):
        raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", f"제한기가 windows_job이 아닙니다: {getattr(limiter, 'name', '?')}")
    k = limiter.k
    k.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    import os

    cwd = os.getcwd()
    proc = limiter.launch(argv, cwd, dict(os.environ), limits)
    try:
        in_job = wintypes.BOOL(False)
        k.IsProcessInJob(getattr(proc.popen, "_handle", None), proc.handle, ctypes.byref(in_job))
        ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        k.QueryInformationJobObject(proc.handle, JobObjectExtendedLimitInformation, ctypes.byref(ext), ctypes.sizeof(ext), None)
        cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        k.QueryInformationJobObject(proc.handle, JobObjectCpuRateControlInformation, ctypes.byref(cpu), ctypes.sizeof(cpu), None)
        proc.wait(timeout=30)
        return {
            "in_job": bool(in_job.value),
            "kill_on_close": bool(ext.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE),
            "cpu_rate": int(cpu.CpuRate),
            "memory_gb": round(int(ext.JobMemoryLimit) / 2**30, 3),
            "priority": limits.priority,
        }
    finally:
        limiter.close(proc)
