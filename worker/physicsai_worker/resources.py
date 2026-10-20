"""자원 스냅샷(§11.6): CPU/RAM(psutil), GPU(설정 gpu_query argv, 제한기 밖, 제한 시간 worker.gpu_query_timeout_s, shell=False).

GPU 조회 실행 파일 탐색(phase3 D3-45): `worker.gpu_query` 첫 인자가 있고 찾을 수 있으면 그대로 쓴다. 비어 있거나(null 포함)
찾지 못하면 `resources.gpu_query_candidates`(기본: PATH의 `nvidia-smi` → `%SystemRoot%\\System32\\nvidia-smi.exe` →
`%ProgramFiles%\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe`)를 순서대로 찾는다. 후보의 `%VAR%`·`${VAR}`·`$VAR`는 환경변수로
확장하고, 정의되지 않은 변수가 있으면 그 후보는 건너뛴다. 결과 상태는 `gpu_status`(OK·NOT_FOUND·ERROR)와 `gpu_message`.

S19(phase3 §24.3): 워커에서는 `gpu_monitor.GpuMonitor`가 조회하고 하트비트는 그 캐시로 `sample(..., gpu=스냅숏)`을 만든다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, NamedTuple

import psutil

from physicsai_core.config.schema import WorkerCfg

GPU_QUERY_ARGS = ["--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
# 함수 기본값으로만 쓴다(phase3 §24.3) — 워커·환경 점검은 설정 worker.gpu_query_timeout_s를 넘긴다. 기본값은 스키마 한 곳
GPU_TIMEOUT_S: float = WorkerCfg.model_fields["gpu_query_timeout_s"].default
_VAR = re.compile(r"%([A-Za-z_][A-Za-z0-9_()]*)%|\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


class GpuResult(NamedTuple):
    gpus: list[dict[str, Any]]
    status: str          # "OK" | "NOT_FOUND" | "ERROR"
    message: str
    exe: str | None      # 실행한(찾은) 파일
    detail: dict[str, Any] | None = None  # 진단 보강(세션 0 판정 시 session_id·raw)


def expand_env(text: str, env: Mapping[str, str]) -> str | None:
    """`%VAR%`·`${VAR}`·`$VAR` 확장(Windows 환경변수 이름은 대소문자 무시). 정의되지 않은 변수가 있으면 None."""
    folded = {k.upper(): v for k, v in env.items()}
    missing = False

    def sub(m: re.Match[str]) -> str:
        nonlocal missing
        name = m.group(1) or m.group(2) or m.group(3)
        val = env.get(name)
        if val is None:
            val = folded.get(name.upper())
        if not val:
            missing = True
            return ""
        return val

    out = _VAR.sub(sub, text)
    return None if missing else out


def find_executable(raw: str, env: Mapping[str, str]) -> str | None:
    """실행 파일 1개 찾기: 이름만(구분자 없음)이면 PATH에서, 경로면 확장 후 파일 존재 확인."""
    s = expand_env(raw.strip(), env) if raw else None
    if not s:
        return None
    if os.sep == "/":  # 비Windows(개발·CI): 기본 후보의 \ 구분자를 / 로
        s = s.replace("\\", "/")
    if "/" not in s and "\\" not in s:
        return shutil.which(s, path=env.get("PATH") or env.get("Path") or os.defpath)
    return s if os.path.isfile(s) else None


def resolve_gpu_argv(gpu_query: Sequence[str] | None, candidates: Sequence[str],
                     env: Mapping[str, str] | None = None) -> tuple[list[str] | None, list[str]]:
    """(실행할 argv | None, 시도한 후보 표시 목록). gpu_query 인자(첫 인자 뒤)가 없으면 기본 조회 인자."""
    look = os.environ if env is None else env
    q = list(gpu_query or [])
    args = q[1:] if len(q) > 1 else list(GPU_QUERY_ARGS)
    tried: list[str] = []
    if q and q[0].strip():
        tried.append(q[0])
        exe = find_executable(q[0], look)
        if exe:
            return [exe, *q[1:]] if len(q) > 1 else [exe], tried
        if len(q) == 1:  # 인자 없이 실행 파일만 준 설정(가짜 도구 등) — 대체 실행 파일에는 기본 조회 인자
            args = list(GPU_QUERY_ARGS)
    for c in candidates:
        if not c or not c.strip():
            continue
        tried.append(c)
        exe = find_executable(c, look)
        if exe:
            return [exe, *args], tried
    return None, tried


def _parse(stdout: str) -> list[dict[str, Any]]:
    out = []
    for line in stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            out.append({"name": parts[0], "util_pct": float(parts[1]), "mem_used_mb": float(parts[2]),
                        "mem_total_mb": float(parts[3])})
        except ValueError:
            continue
    return out


def _secs(v: float) -> str:
    return f"{v:g}"


SESSION0_GPU_MESSAGE = ("GPU 정보 조회 불가 — 워커가 백그라운드 세션(세션 0)에서 실행 중이라 nvidia-smi가 GPU 드라이버에 "
                        "접근하지 못합니다(예측 계산에는 영향 없음)")


def current_session_id() -> int | None:
    """현재 프로세스의 Windows 세션 ID(ProcessIdToSessionId). 비Windows·실패는 None."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        sid = ctypes.c_ulong()
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if not k32.ProcessIdToSessionId(k32.GetCurrentProcessId(), ctypes.byref(sid)):
            return None
        return int(sid.value)
    except Exception:  # noqa: BLE001
        return None


def query_gpu_status(gpu_query: Sequence[str] | None, candidates: Sequence[str] = (), env: dict[str, str] | None = None,
                     lookup_env: Mapping[str, str] | None = None, *, timeout_s: float | None = None) -> GpuResult:
    """GPU 조회 + 세션 0(작업 스케줄러 Background)이면 ERROR 원인을 명시(상태는 ERROR 유지, 원문은 detail.raw)."""
    g = _query_gpu_status(gpu_query, candidates, env, lookup_env, timeout_s=timeout_s)
    if g.status == "ERROR" and current_session_id() == 0:
        return g._replace(message=SESSION0_GPU_MESSAGE, detail={"session_id": 0, "raw": g.message})
    return g


def _query_gpu_status(gpu_query: Sequence[str] | None, candidates: Sequence[str] = (), env: dict[str, str] | None = None,
                      lookup_env: Mapping[str, str] | None = None, *, timeout_s: float | None = None) -> GpuResult:
    """GPU 조회(제한기 밖, shell=False). env = 자식 프로세스 환경, lookup_env = 실행 파일 탐색 환경(기본 os.environ).
    timeout_s = 제한 시간(초) — 호출자는 설정 worker.gpu_query_timeout_s를 넘기고, 없으면 GPU_TIMEOUT_S(스키마 기본값)."""
    argv, tried = resolve_gpu_argv(gpu_query, candidates, lookup_env)
    if argv is None:
        shown = ", ".join(tried) if tried else "후보 없음"
        return GpuResult([], "NOT_FOUND", f"nvidia-smi를 찾지 못했습니다(시도: {shown})", None)
    exe = argv[0]
    limit = GPU_TIMEOUT_S if timeout_s is None else timeout_s
    try:
        cp = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=limit, env=env)
    except subprocess.TimeoutExpired:
        return GpuResult([], "ERROR", f"nvidia-smi 응답 시간 초과({_secs(limit)}초): {exe}", exe)
    except OSError as exc:
        return GpuResult([], "ERROR", f"nvidia-smi를 실행하지 못했습니다: {exe} ({exc.strerror or exc})", exe)
    if cp.returncode != 0:
        tail = next((ln.strip() for ln in reversed(((cp.stderr or "") + "\n" + (cp.stdout or "")).splitlines()) if ln.strip()), "")
        return GpuResult([], "ERROR", f"nvidia-smi 종료코드 {cp.returncode}{': ' + tail[:200] if tail else ''}", exe)
    gpus = _parse(cp.stdout or "")
    if not gpus:
        return GpuResult([], "ERROR", "nvidia-smi 출력에서 GPU 정보를 읽지 못했습니다", exe)
    return GpuResult(gpus, "OK", exe, exe)


def query_gpu(argv: list[str] | None, env: dict[str, str] | None = None, candidates: Sequence[str] = ()) -> list[dict[str, Any]]:
    return query_gpu_status(argv, candidates, env).gpus


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).isoformat() if t is not None else None


def sample(gpu_argv: list[str] | None, job: dict[str, Any] | None = None, env: dict[str, str] | None = None,
           candidates: Sequence[str] = (), *, gpu: Mapping[str, Any] | None = None,
           timeout_s: float | None = None) -> dict[str, Any]:
    """자원 표본. gpu = GpuMonitor 스냅숏(워커 하트비트 — nvidia-smi를 실행하지 않음). 없으면 직접 조회(기존 동작)."""
    vm = psutil.virtual_memory()
    if gpu is None:
        g = query_gpu_status(gpu_argv, candidates, env, timeout_s=timeout_s)
        gpu = {"gpus": g.gpus, "status": g.status, "message": g.message, "sampled_at": None, "fail_streak": None,
               "next_query_at": None}
    return {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used_gb": round((vm.total - vm.available) / 2**30, 3),
        "ram_total_gb": round(vm.total / 2**30, 3),
        "gpu": list(gpu.get("gpus") or []),
        "gpu_status": gpu.get("status"),
        "gpu_message": gpu.get("message"),
        "gpu_fail_streak": gpu.get("fail_streak"),
        "gpu_sampled_at": _iso(gpu.get("sampled_at")),
        "gpu_next_query_at": _iso(gpu.get("next_query_at")),
        "job": job,
    }


_PAICAD_CACHE: dict[tuple[str, int, int], str | None] = {}


def paicad_version(settings: Any, env: dict[str, str] | None = None) -> str | None:
    """설치된 paicad 버전(geometry-view.md §6.4 미리보기 캐시 키 `engine_version` — 하트비트 resources.paicad_version).
    `commands.paicad_version` 템플릿(shell=False, 제한기 밖, 30초)으로 실행하고 실행 파일(경로·크기·mtime)이 같으면 캐시. 모르면 None."""
    from physicsai_core.commands import render_argv
    from physicsai_core.config import effective_executables
    from physicsai_core.geometry.reports import ReportError, parse_version_json

    tpl = settings.commands.paicad_version
    exe = effective_executables(settings).get("paicad_path") or ""
    if tpl is None or not exe or not os.path.isfile(exe):
        return None
    st = os.stat(exe)
    key = (exe, st.st_size, st.st_mtime_ns)
    if key in _PAICAD_CACHE:
        return _PAICAD_CACHE[key]
    ver = None
    try:
        argv = render_argv("paicad_version", tpl, {}, executables=effective_executables(settings))
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=30, shell=False, env=env, check=False)
        ver = parse_version_json(cp.stdout).get("paicad") if cp.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ReportError, Exception):  # noqa: BLE001 - 하트비트는 실패해도 계속
        ver = None
    if len(_PAICAD_CACHE) > 16:
        _PAICAD_CACHE.clear()
    _PAICAD_CACHE[key] = ver
    return ver
