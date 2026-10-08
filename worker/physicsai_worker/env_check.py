"""환경 점검 워커 부분(phase2 §9.3). 외부 프로그램·파일 시스템·Job Object가 필요한 항목.

- 프로브는 제한기 안에서만 실행(shell=False argv, argv[0] = 도구 placeholder → 설정 경로).
- 쓰기 시험은 `<ai_root>/_platform/env_check_tmp/`에서 tempfile 자동 삭제만(명시적 삭제 호출 없음).
- 프로그램 출력 꼬리(마스킹)는 보고서 파일에만, DB에는 넣지 않는다.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any

from physicsai_core import spdm
from physicsai_core.childenv import child_env
from physicsai_core.commands import EXECUTABLE_PLACEHOLDERS
from physicsai_core.config import (
    ENV_PROBE_TOOLS,
    LAUNCHER_KEYS,
    RESOURCE_DIR_KEYS,
    RESOURCE_FILE_KEYS,
    effective_altair,
    paths_overlap,
)
from physicsai_core.db.repositories import env_checks as env_repo
from physicsai_core.env_check import ALTAIR_CHECK_KEYS, item, report_rel
from physicsai_core.fileutil import write_json
from physicsai_core.parsers.log_errors import Masker

from . import resources
from .steps.launcher import check_launcher

log = logging.getLogger("physicsai_worker.env_check")
PLATFORM_DIR = "_platform"
TAIL = 4096


def _exec_item(key: str, path: str) -> dict[str, Any]:
    k = f"altair.{key}"
    if not path:
        return item(k, "EXECUTABLE", "WARN", "미설정", "WORKER")
    if not os.path.isfile(path):
        return item(k, "EXECUTABLE", "FAIL", f"실행 파일이 없습니다: {path}", "WORKER", {"path": path})
    st = os.stat(path)
    detail = {"path": path, "size": st.st_size, "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}
    if os.name == "nt":
        exts = [e.lower() for e in os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(";") if e]
        ok = os.path.splitext(path)[1].lower() in exts and os.access(path, os.R_OK)
    else:
        ok = os.access(path, os.X_OK)
    if not ok:
        return item(k, "EXECUTABLE", "FAIL", "실행할 수 없는 파일입니다", "WORKER", detail)
    return item(k, "EXECUTABLE", "OK", "정상", "WORKER", detail)


def _probe(w: Any, tool: str, exe: str, masker: Masker, tails: dict[str, str]) -> dict[str, Any]:
    s = w.settings
    key = f"probe.{tool}"
    argv_t = getattr(s.env_check.probes, tool)
    if argv_t is None:
        return item(key, "EXECUTABLE", "SKIP", "존재 확인만(인자 미확인)", "WORKER")
    if not exe or not os.path.isfile(exe):
        return item(key, "EXECUTABLE", "FAIL", "실행 파일이 없어 프로브를 실행하지 못했습니다", "WORKER")
    argv = [exe, *argv_t[1:]]
    cwd = os.path.join(os.path.normpath(s.storage.ai_root), PLATFORM_DIR, "env_check_tmp")
    os.makedirs(cwd, exist_ok=True)
    env = child_env(s.worker.env_passthrough, deny_names=[s.database.url_env])
    t0 = time.time()
    proc = w.limiter.launch(argv, cwd, env, w.limits)
    out: list[str] = []

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            out.append(line)

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    timed_out = False
    try:
        while proc.poll() is None:
            if time.time() - t0 > s.env_check.probe_timeout_s:
                timed_out = True
                w.limiter.terminate(proc)
                break
            time.sleep(0.05)
        th.join(timeout=5)
    finally:
        if proc.poll() is None:
            w.limiter.terminate(proc)
        w.limiter.close(proc)
    dur = int((time.time() - t0) * 1000)
    tails[key] = masker("".join(out)[-TAIL:])
    if timed_out:
        return item(key, "EXECUTABLE", "FAIL", "시간 초과", "WORKER", {"duration_ms": dur})
    rc = proc.poll()
    if rc == 0:
        return item(key, "EXECUTABLE", "OK", "정상 종료", "WORKER", {"exit_code": rc, "duration_ms": dur})
    return item(key, "EXECUTABLE", "FAIL", f"종료코드 {rc}", "WORKER", {"exit_code": rc, "duration_ms": dur})


def _resource_items(s: Any) -> list[dict[str, Any]]:
    out = []
    for k in RESOURCE_FILE_KEYS + RESOURCE_DIR_KEYS:
        v = getattr(s.resources, k)
        key = f"resource.{k}"
        if not v:
            out.append(item(key, "RESOURCE", "WARN", "미설정(해당 기능 비활성)", "WORKER"))
        elif (k in RESOURCE_DIR_KEYS and os.path.isdir(v)) or (k in RESOURCE_FILE_KEYS and os.path.isfile(v)):
            out.append(item(key, "RESOURCE", "OK", "정상", "WORKER", {"path": v}))
        else:
            out.append(item(key, "RESOURCE", "FAIL", f"없습니다: {v}", "WORKER", {"path": v}))
    for k in LAUNCHER_KEYS:
        key = f"resource.launchers.{k}"
        if k not in s.resources.launchers or not s.resources.batchrun_dir:
            out.append(item(key, "RESOURCE", "WARN", "미설정(해당 기능 비활성)", "WORKER"))
            continue
        info = check_launcher(s, k)
        det = {"script": info.get("script"), "compiled": info.get("compiled"), "pyd_count": len(info.get("pyd") or [])}
        if info.get("problem"):
            out.append(item(key, "RESOURCE", "FAIL", info["problem"], "WORKER", det))
        else:
            out.append(item(key, "RESOURCE", "OK", "정상", "WORKER", det))
    return out


def _storage_items(s: Any) -> list[dict[str, Any]]:
    out = []
    ai = os.path.normpath(s.storage.ai_root)
    tmpdir = os.path.join(ai, PLATFORM_DIR, "env_check_tmp")
    try:
        os.makedirs(tmpdir, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=tmpdir, delete=True) as fh:
            fh.write(b"\0" * 1024)
            fh.flush()
            os.fsync(fh.fileno())
        out.append(item("storage.ai_root.write", "STORAGE", "OK", "쓰기 가능", "WORKER", {"path": tmpdir}))
    except OSError as exc:
        out.append(item("storage.ai_root.write", "STORAGE", "FAIL", f"쓰기 실패: {exc}", "WORKER", {"path": tmpdir}))
    try:
        free_gb = shutil.disk_usage(ai).free / 2**30
        st = "OK" if free_gb >= s.env_check.min_free_gb else "WARN"
        out.append(item("storage.ai_root.free", "STORAGE", st, f"여유 {free_gb:.1f} GB", "WORKER",
                        {"free_gb": round(free_gb, 2), "min_free_gb": s.env_check.min_free_gb}))
    except OSError as exc:
        out.append(item("storage.ai_root.free", "STORAGE", "FAIL", str(exc), "WORKER"))
    others = [("storage.ai_root", s.storage.ai_root)]
    others += [(f"storage.allowed_import_roots[{i}]", r) for i, r in enumerate(s.storage.allowed_import_roots)]
    if s.hpc.transfer.collect_root_local:
        others.append(("hpc.transfer.collect_root_local", s.hpc.transfer.collect_root_local))
    bad = [{"key": k, "spdm_root": r} for k, v in others for r in s.storage.spdm_roots if v and paths_overlap(v, r)]
    out.append(item("storage.roots_overlap", "STORAGE", "FAIL" if bad else "OK",
                    "SPDM 루트와 겹치는 루트가 있습니다" if bad else "겹침 없음", "WORKER", {"overlaps": bad} if bad else None))
    if not s.storage.spdm_roots:
        out.append(item("storage.spdm_roots", "STORAGE", "SKIP", "SPDM 루트 미설정", "WORKER"))
    else:
        res = spdm.probe_roots(s.storage.spdm_roots)
        ok = all(r["ok"] for r in res)
        out.append(item("storage.spdm_roots", "STORAGE", "OK" if ok else "FAIL", "읽기 가능" if ok else "읽을 수 없는 루트가 있습니다",
                        "WORKER", {"roots": res}))
    return out


def _job_object_item(w: Any) -> dict[str, Any]:
    if os.name != "nt":
        return item("worker.job_object", "WORKER", "SKIP", "Windows 아님", "WORKER")
    try:
        from .limiter.windows_job import self_test

        info = self_test(w.limiter, w.limits, [sys.executable, "-I", "-c", "pass"])
    except Exception as exc:  # noqa: BLE001 - 점검 결과로 보고
        return item("worker.job_object", "WORKER", "FAIL", f"Job Object 자체 시험 실패: {exc}", "WORKER")
    st = "OK" if info.get("in_job") and info.get("kill_on_close") else "FAIL"
    return item("worker.job_object", "WORKER", st, "정상" if st == "OK" else "Job Object 설정이 기대와 다릅니다", "WORKER", info)


def collect_items(w: Any, masker: Masker, tails: dict[str, str]) -> list[dict[str, Any]]:
    s = w.settings
    alt = effective_altair(s)
    items = [_exec_item(k, alt.get(k, "")) for k in ALTAIR_CHECK_KEYS]
    for tool in ENV_PROBE_TOOLS:
        items.append(_probe(w, tool, alt.get(EXECUTABLE_PLACEHOLDERS[tool], ""), masker, tails))
    items += _resource_items(s)
    items += _storage_items(s)
    lim = w.limiter.name
    st = "OK" if lim == "windows_job" else "WARN"
    msg = "정상" if st == "OK" else ("CPU 상한 미적용(비Windows)" if lim == "posix" else "제한기 없음(null)")
    items.append(item("worker.limiter", "WORKER", st, msg, "WORKER",
                      {"name": lim, "cpu_cap_enforced": bool(w.limiter.cpu_cap_enforced)}))
    items.append(_job_object_item(w))
    gpus = resources.query_gpu(s.worker.gpu_query, w.child_env())
    if gpus:
        items.append(item("gpu.detect", "GPU", "OK", f"GPU {len(gpus)}개", "WORKER",
                          {"gpus": [{"name": g["name"], "memory_total_mb": g.get("mem_total_mb")} for g in gpus]}))
    else:
        items.append(item("gpu.detect", "GPU", "WARN", "GPU를 찾지 못했습니다", "WORKER"))
    return items


def run_env_check(w: Any, chk: dict[str, Any]) -> str:
    s = w.settings
    masker = Masker(s.logging.mask_patterns)
    tails: dict[str, str] = {}
    try:
        items = collect_items(w, masker, tails)
        all_items = list(chk["api_items"] or []) + items
        summary = env_repo.summarize(all_items)
        rel = report_rel(chk["id"])
        path = os.path.join(os.path.normpath(s.storage.ai_root), *rel.split("/"))
        write_json(path, {"id": chk["id"], "generated_at": datetime.now(timezone.utc).isoformat(), "summary": summary,
                          "items": all_items, "probe_output_tails": tails})
        with w.engine.begin() as conn:
            ok = env_repo.finish(conn, chk["id"], w.worker_id, state="DONE", worker_items=items, summary=summary,
                                 report_rel=rel)
        return "DONE" if ok else "REJECTED"
    except Exception as exc:  # noqa: BLE001
        log.exception("환경 점검 오류")
        with w.engine.begin() as conn:
            ok = env_repo.finish(conn, chk["id"], w.worker_id, state="FAILED", worker_items=None, summary=None,
                                 report_rel=None, failure_message=f"워커 점검 오류: {exc}")
        return "FAILED" if ok else "REJECTED"
