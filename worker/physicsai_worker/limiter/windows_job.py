"""WindowsJobLimiter(§11.5): step 프로세스마다 Job Object 1개(ctypes kernel32, pywin32 미사용).

- KILL_ON_JOB_CLOSE | JOB_MEMORY | PRIORITY_CLASS | DIE_ON_UNHANDLED_EXCEPTION, BREAKAWAY 불허(손자까지 Job 안)
- CPU rate hard cap, GPU 무제한
- CREATE_SUSPENDED로 시작 → AssignProcessToJobObject → 주 스레드 ResumeThread
- 할당 실패 시 TerminateProcess 후 JOB_OBJECT_ASSIGN_FAILED — 제한 없이 실행하는 경로는 없다
kernel32·Popen은 주입 가능(Linux 단위 시험 V-JO-4).
"""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes
from typing import Any, Callable

from physicsai_core.limits import EffectiveLimits

from .base import POPEN_TEXT_KW, Accounting, LimitedProcess, LimiterError

JobObjectBasicAccountingInformation = 1
JobObjectExtendedLimitInformation = 9
JobObjectCpuRateControlInformation = 15

JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4

IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS = 0x00000020
PRIORITY = {"idle": IDLE_PRIORITY_CLASS, "below_normal": BELOW_NORMAL_PRIORITY_CLASS, "normal": NORMAL_PRIORITY_CLASS}

CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x0002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
RESUME_FAILED = 0xFFFFFFFF  # (DWORD)-1

LIMIT_FLAGS = (
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    | JOB_OBJECT_LIMIT_JOB_MEMORY
    | JOB_OBJECT_LIMIT_PRIORITY_CLASS
    | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
)


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
    _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


def _load_kernel32() -> Any:
    k = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.Thread32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k.OpenThread.restype = wintypes.HANDLE
    k.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.ResumeThread.argtypes = [wintypes.HANDLE]
    k.ResumeThread.restype = wintypes.DWORD
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    return k


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

    def launch(self, argv: list[str], cwd: str, env: dict[str, str], limits: EffectiveLimits) -> LimitedProcess:
        job = self._create_job(limits)
        flags = CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        try:
            p = self.popen(argv, cwd=cwd, env=env, creationflags=flags, **POPEN_TEXT_KW)
        except OSError as exc:
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
                self.k.CloseHandle(job)
            raise LimiterError("JOB_OBJECT_ASSIGN_FAILED", "프로세스를 Job Object에 넣지 못해 실행하지 않았습니다")
        try:
            self._resume_main_thread(p.pid)
        except LimiterError:
            # 재개 실패: 일시정지 상태 프로세스를 남기지 않는다 → TerminateProcess + Job 종료, step FAILED(JOB_OBJECT_ASSIGN_FAILED)
            try:
                self.k.TerminateProcess(handle, 1)
                self.k.TerminateJobObject(job, 1)
            finally:
                try:
                    p.wait(timeout=10)
                except Exception:
                    pass
                self.k.CloseHandle(job)
            raise
        return LimitedProcess(p, handle=job, extra={"memory_limit": int(limits.memory_gb * 2**30)})

    def terminate(self, proc: LimitedProcess, timeout_s: float = 30) -> None:
        if proc.handle:
            self.k.TerminateJobObject(proc.handle, 1)
        deadline = time.time() + timeout_s
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.1)

    def accounting(self, proc: LimitedProcess) -> Accounting:
        ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        acc = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        peak = cpu = None
        if proc.handle and self.k.QueryInformationJobObject(proc.handle, JobObjectExtendedLimitInformation, ctypes.byref(ext), ctypes.sizeof(ext), None):
            peak = int(ext.PeakJobMemoryUsed)
        if proc.handle and self.k.QueryInformationJobObject(proc.handle, JobObjectBasicAccountingInformation, ctypes.byref(acc), ctypes.sizeof(acc), None):
            cpu = (acc.TotalUserTime + acc.TotalKernelTime) / 1e7
        limit = proc.extra.get("memory_limit") or 0
        hit = bool(peak and limit and peak >= 0.98 * limit)
        return Accounting(peak_memory_bytes=peak, cpu_time_s=cpu, cpu_cap_enforced=True, memory_limit_hit=hit)

    def close(self, proc: LimitedProcess) -> None:
        if proc.handle:
            self.k.CloseHandle(proc.handle)
            proc.handle = None
