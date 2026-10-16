"""자원 스냅샷(§11.6): CPU/RAM(psutil), GPU(설정 gpu_query argv, 제한기 밖, 타임아웃 5초, shell=False).

GPU 조회 실행 파일 탐색(phase3 D3-45): `worker.gpu_query` 첫 인자가 있고 찾을 수 있으면 그대로 쓴다. 비어 있거나(null 포함)
찾지 못하면 `resources.gpu_query_candidates`(기본: PATH의 `nvidia-smi` → `%SystemRoot%\\System32\\nvidia-smi.exe` →
`%ProgramFiles%\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe`)를 순서대로 찾는다. 후보의 `%VAR%`·`${VAR}`·`$VAR`는 환경변수로
확장하고, 정의되지 않은 변수가 있으면 그 후보는 건너뛴다. 결과 상태는 `gpu_status`(OK·NOT_FOUND·ERROR)와 `gpu_message`.
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

GPU_QUERY_ARGS = ["--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
GPU_TIMEOUT_S = 5
_VAR = re.compile(r"%([A-Za-z_][A-Za-z0-9_()]*)%|\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


class GpuResult(NamedTuple):
    gpus: list[dict[str, Any]]
    status: str          # "OK" | "NOT_FOUND" | "ERROR"
    message: str
    exe: str | None      # 실행한(찾은) 파일


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


def query_gpu_status(gpu_query: Sequence[str] | None, candidates: Sequence[str] = (), env: dict[str, str] | None = None,
                     lookup_env: Mapping[str, str] | None = None) -> GpuResult:
    """GPU 조회(제한기 밖, 타임아웃 5초, shell=False). env = 자식 프로세스 환경, lookup_env = 실행 파일 탐색 환경(기본 os.environ)."""
    argv, tried = resolve_gpu_argv(gpu_query, candidates, lookup_env)
    if argv is None:
        shown = ", ".join(tried) if tried else "후보 없음"
        return GpuResult([], "NOT_FOUND", f"nvidia-smi를 찾지 못했습니다(시도: {shown})", None)
    exe = argv[0]
    try:
        cp = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=GPU_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return GpuResult([], "ERROR", f"nvidia-smi 응답 시간 초과({GPU_TIMEOUT_S}초): {exe}", exe)
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


def sample(gpu_argv: list[str] | None, job: dict[str, Any] | None = None, env: dict[str, str] | None = None,
           candidates: Sequence[str] = ()) -> dict[str, Any]:
    vm = psutil.virtual_memory()
    g = query_gpu_status(gpu_argv, candidates, env)
    return {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used_gb": round((vm.total - vm.available) / 2**30, 3),
        "ram_total_gb": round(vm.total / 2**30, 3),
        "gpu": g.gpus,
        "gpu_status": g.status,
        "gpu_message": g.message,
        "job": job,
    }
