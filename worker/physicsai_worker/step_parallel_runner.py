"""step 병렬 실행 결과 모양(ParallelOutcome)·실행기(ParallelRunner)·슬롯 풀(_Pool) — step_parallel에서 재노출."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from physicsai_core.childenv import child_env
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.errors import StepFailure

from .limiter.base import ProcGroup
from .signals import Cancelled

log = logging.getLogger("physicsai_worker.executor")
MEMORY_SAMPLE_S = 0.5  # 공유 회계 그룹(Windows Job)의 메모리 한도 도달 표본 간격(초)


@dataclass
class ParallelOutcome:
    """항목 1개 결과. code None = 성공."""

    item_id: str
    code: str | None = None
    message: str | None = None
    warnings: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.code is None


class ParallelRunner:
    """작업 스레드 1개가 항목 1개를 처리할 때 쓰는 도구(ctx.run_local의 동시 실행판)."""

    def __init__(self, pool: _Pool, item_id: str) -> None:
        self.pool = pool
        self.ctx = pool.ctx
        self.item_id = item_id
        self.last_line = ""
        self.last_exit_code: int | None = None
        self.outcome = ParallelOutcome(item_id)

    def log(self, line: str) -> None:
        self.pool.log(f"[{self.item_id}] {line}")

    def warn(self, code: str, message: str) -> None:
        self.outcome.warnings.append((code, message))
        self.log(f"[WARN] {code}: {message}")

    def check(self) -> None:
        if self.pool.stop.is_set():
            raise Cancelled()

    def run(self, template_key: str, values: dict[str, str], *, cwd: str, outputs_to_backup: list[str] | None = None,
            env_add: dict[str, str] | None = None, extra_args: Sequence[str] = (), timeout_s: float | None = None) -> int:
        """외부 프로그램 1회(그룹 안, shell=False). 종료코드를 돌려준다 — 성공 판정은 호출자가 출력 파일로(§11.4).
        메모리 한도 도달 종료 → RESOURCE_LIMIT. 회계를 그룹이 공유하면(Windows Job 1개) 도달 기록이 이 실행 시간대와
        겹칠 때만 RESOURCE_LIMIT(다른 run과 겹치면 "원인 불확실" 문구), 아니면 종료코드를 그대로 돌려준다(D3-53).
        취소되면 Cancelled. extra_args = argv 끝에 덧붙이는 `--옵션 경로` 쌍, timeout_s = 이 실행 1회 시간 상한(넘으면 이 프로세스만
        종료하고 GEOM_TIMEOUT)."""
        ctx = self.ctx
        self.check()
        argv, _exe = ctx.render(template_key, values, extra_args) if extra_args else ctx.render(template_key, values)
        if outputs_to_backup:
            with self.pool.fs_lock:
                ctx.backup(outputs_to_backup)
        os.makedirs(cwd, exist_ok=True)
        s = ctx.settings
        env = child_env(s.worker.env_passthrough, env_add, deny_names=[s.database.url_env])
        self.pool.record_first(argv, cwd, env_add)
        self.log("[CMD] " + " ".join(argv))
        grp = self.pool.group
        start, _ = self.pool.sample_memory()
        win = grp.run_started(start)
        try:
            proc = ctx.ex.limiter.launch(argv, cwd, env, ctx.ex.limits, group=grp)
        except BaseException:
            grp.run_ended(win, time.perf_counter())
            raise
        self.pool.started()
        rc: int | None = None
        timed_out = False
        try:
            if self.pool.stop.is_set():  # 그룹 종료와 launch가 엇갈린 경우
                ctx.ex.limiter.terminate(proc)
                raise Cancelled()

            def reader() -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    self.log(line)
                    if line.strip():
                        self.last_line = line.strip()[:120]

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            last_sample = time.perf_counter()
            began = time.monotonic()
            while proc.poll() is None:
                if self.pool.stop.wait(0.1):
                    break
                if timeout_s is not None and time.monotonic() - began > timeout_s:
                    timed_out = True
                    ctx.ex.limiter.terminate(proc)
                    break
                if time.perf_counter() - last_sample >= MEMORY_SAMPLE_S:
                    last_sample = time.perf_counter()
                    self.pool.sample_memory()
            if self.pool.stop.is_set() and proc.poll() is None:
                ctx.ex.limiter.terminate(proc)
            t.join(timeout=10)
            rc = proc.poll()
            acc = ctx.ex.limiter.accounting(proc)
            _, end = self.pool.sample_memory()
            grp.run_ended(win, end)
        finally:
            grp.run_ended(win, time.perf_counter())  # 이미 기록했으면 그대로
            ctx.ex.limiter.close(proc)
            self.pool.finished(self.item_id, template_key, argv, cwd, rc)
        if self.pool.stop.is_set():
            raise Cancelled()
        if timed_out:
            raise StepFailure("GEOM_TIMEOUT", f"실행 시간 제한({timeout_s:g}초)을 넘어 중단했습니다")
        rc = -1 if rc is None else rc
        self.last_exit_code = rc
        self.log(f"[EXIT] {rc}")
        if rc != 0 and acc.memory_limit_hit:
            gb = ctx.ex.limits.memory_gb
            verdict = grp.memory_verdict(win) if grp.shared_accounting else "exact"
            if verdict is None and grp.mem_hit_at is None:  # 표본이 도달을 못 잡았는데 끝 회계는 도달 → 시간대 불명
                verdict = "uncertain"
            if verdict == "exact":
                raise StepFailure("RESOURCE_LIMIT", f"작업 메모리 한도({gb} GB)에 도달해 종료되었습니다")
            if verdict == "uncertain":
                raise StepFailure("RESOURCE_LIMIT", f"종료코드 {rc}: 작업 묶음이 메모리 한도({gb} GB)에 도달한 적 있음"
                                                    "(이 run의 원인인지 불확실)")
            self.log("[INFO] 작업 묶음의 메모리 한도 도달 기록은 이 실행 시간대와 겹치지 않아 일반 종료코드로 판정합니다")
        return rc


class _Pool:
    def __init__(self, ctx: Any, group: ProcGroup, total: int, max_parallel: int) -> None:
        self.ctx = ctx
        self.group = group
        self.total = total
        self.max_parallel = max_parallel
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.fs_lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.running_procs = 0
        self.peak_procs = 0
        self.active_items = 0
        self.done = 0
        self.failed = 0
        self.first_recorded = False
        self.lease_lost = False
        rel = f"logs/{ctx.ex.job_id}/step_{ctx.step_no:02d}_{ctx.key}.commands.jsonl"
        self.commands_rel = rel
        self.commands_path = ctx.abs(rel)
        os.makedirs(os.path.dirname(self.commands_path), exist_ok=True)

    def log(self, line: str) -> None:
        with self.log_lock:
            self.ctx.log(line)

    def record_first(self, argv: list[str], cwd: str, env_add: dict[str, str] | None) -> None:
        with self.lock:
            if self.first_recorded:
                return
            self.first_recorded = True
        command = {"argv": argv, "cwd": cwd, "env_added": dict(env_add or {}), "parallel": self.max_parallel,
                   "invocations": None, "commands_rel": self.commands_rel}
        ex = self.ctx.ex
        ex.db(lambda c: lease_repo.step_update(c, ex.job_id, ex.token, self.ctx.step_no, command=command))

    def started(self) -> None:
        with self.lock:
            self.running_procs += 1
            self.peak_procs = max(self.peak_procs, self.running_procs)

    def finished(self, item_id: str, template_key: str, argv: list[str], cwd: str, rc: int | None) -> None:
        with self.lock:
            self.running_procs -= 1
            with open(self.commands_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"target_id": item_id, "template": template_key, "argv": argv, "cwd": cwd,
                                     "exit_code": rc}, ensure_ascii=False) + "\n")

    def sample_memory(self) -> tuple[float, float]:
        """그룹 회계 표본(공유 회계 그룹만 조회) → (조회 전, 조회 후) 시각. 실행 시작 = 조회 전, 끝 = 조회 후.
        perf_counter를 쓴다 — Windows monotonic은 약 15.6 ms 단위라 앞 run 끝과 뒤 run 시작이 같은 값이 될 수 있다."""
        t0 = time.perf_counter()
        if not self.group.shared_accounting or self.group.closed:
            return t0, t0
        try:
            hit = bool(self.ctx.ex.limiter.group_accounting(self.group).memory_limit_hit)
        except Exception:  # noqa: BLE001 - 표본 실패는 판정 근거가 없을 뿐(끝 회계로 판정)
            return t0, time.perf_counter()
        t1 = time.perf_counter()
        self.group.note_memory(hit, t1 if hit else t0)
        return t0, t1

    def snapshot(self) -> tuple[int, int, int, int]:
        with self.lock:
            return self.active_items, self.done, self.failed, self.total
