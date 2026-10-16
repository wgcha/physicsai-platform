"""동시 실행기 `run_parallel`(phase3 §14.5 S9 BP_GEN): 항목(run)마다 순차 명령 체인을 최대 M개 동시에 실행한다.

- 모든 자식 프로세스는 제한기의 그룹 1개(Windows = Job Object 1개)에 들어가 작업 1개분 한도를 나눠 쓴다.
- 항목 실패는 그 항목만 실패로 기록하고 나머지는 계속한다(`ParallelOutcome`). 호출자가 성공 0개·일부 실패를 판정한다.
- 취소·lease 상실: 주 스레드가 감지 → 그룹 전체 종료(프로세스 트리 포함) → Cancelled / LeaseLost.
- 외부 명령은 shell=False argv(제한기 launch), 실행 파일·인자는 설정 템플릿에서만(`ctx.render`).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from physicsai_core.childenv import child_env
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories.job_lease import LeaseLost
from physicsai_core.errors import DomainError, StepFailure

from .limiter.base import LimiterError, ProcGroup
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
            env_add: dict[str, str] | None = None) -> int:
        """외부 프로그램 1회(그룹 안, shell=False). 종료코드를 돌려준다 — 성공 판정은 호출자가 출력 파일로(§11.4).
        메모리 한도 도달 종료 → RESOURCE_LIMIT. 회계를 그룹이 공유하면(Windows Job 1개) 도달 기록이 이 실행 시간대와
        겹칠 때만 RESOURCE_LIMIT(다른 run과 겹치면 "원인 불확실" 문구), 아니면 종료코드를 그대로 돌려준다(D3-53).
        취소되면 Cancelled."""
        ctx = self.ctx
        self.check()
        argv, _exe = ctx.render(template_key, values)
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
            while proc.poll() is None:
                if self.pool.stop.wait(0.1):
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


def run_parallel(
    ctx: Any,
    items: Sequence[Any],
    fn: Callable[[ParallelRunner, Any], None],
    *,
    item_id: Callable[[Any], str],
    max_parallel: int,
    label: Callable[[int, int, int, int, int], str] | None = None,
) -> list[ParallelOutcome]:
    """items를 순서대로 최대 max_parallel개 동시에 fn(runner, item)으로 처리한다.

    fn 안의 StepFailure·LimiterError·DomainError는 그 항목 실패(code·message)로, 그 밖의 예외는 INTERNAL_ERROR로 기록한다.
    label(running, done, failed, total, M) → 진행 라벨. 진행률 = (완료+실패)/전체.
    반환: items 순서의 ParallelOutcome 목록. 취소 → Cancelled, lease 상실 → LeaseLost(그룹 프로세스 전부 종료 후).
    """
    n = len(items)
    m = max(1, min(int(max_parallel), n or 1))
    ex = ctx.ex
    group = ex.limiter.open_group(ex.limits, m)
    pool = _Pool(ctx, group, n, m)
    outcomes: dict[int, ParallelOutcome] = {}
    work: queue.Queue[tuple[int, Any]] = queue.Queue()
    for i, it in enumerate(items):
        work.put((i, it))

    def worker() -> None:
        while not pool.stop.is_set():
            try:
                i, it = work.get_nowait()
            except queue.Empty:
                return
            iid = item_id(it)
            runner = ParallelRunner(pool, iid)
            with pool.lock:
                pool.active_items += 1
            try:
                fn(runner, it)
            except Cancelled:
                runner.outcome.code = "CANCELED"
                runner.outcome.message = "취소됨"
            except LeaseLost:
                pool.lease_lost = True
                pool.stop.set()
                runner.outcome.code = "CANCELED"
                runner.outcome.message = "lease 상실"
            except (StepFailure, LimiterError) as exc:
                runner.outcome.code = exc.code
                runner.outcome.message = exc.message
            except DomainError as exc:
                runner.outcome.code = "INPUT_INVALID"
                runner.outcome.message = getattr(exc, "message", str(exc))
            except Exception as exc:  # noqa: BLE001 - 항목 1개의 내부 오류는 그 항목만 실패
                runner.log("[FAIL] INTERNAL_ERROR\n" + traceback.format_exc())
                runner.outcome.code = "INTERNAL_ERROR"
                runner.outcome.message = f"내부 오류: {exc}"
            with pool.lock:
                pool.active_items -= 1
                if runner.outcome.code is None:
                    pool.done += 1
                elif runner.outcome.code != "CANCELED":
                    pool.failed += 1
                outcomes[i] = runner.outcome
            if runner.outcome.code not in (None, "CANCELED"):
                runner.log(f"[RUN FAIL] {runner.outcome.code}: {runner.outcome.message}")

    threads = [threading.Thread(target=worker, daemon=True, name=f"par-{ex.job_id[:8]}-{k}") for k in range(m)]
    ctx.log(f"동시 실행 {n}개 항목, 동시 {m}개(그룹 1개)")
    for t in threads:
        t.start()
    interval = ctx.settings.worker.cancel_check_interval_s
    last_cancel = 0.0
    reason: str | None = None
    try:
        with ex._proc_lock:
            ex.current_group = group
        while any(t.is_alive() for t in threads):
            time.sleep(min(interval, 0.25))
            if ex.keeper is not None and ex.keeper.lost.is_set():
                reason = "lease"
                break
            now = time.time()
            if now - last_cancel >= interval:
                last_cancel = now
                if ex.cancel_requested():
                    reason = "cancel"
                    ctx.log("[CANCEL] 취소 요청 감지 — 동시 실행 프로세스 전부를 종료합니다")
                    break
            if label is not None:
                running, done, failed, total = pool.snapshot()
                ctx.progress((done + failed) / total * 100.0 if total else None, label(running, done, failed, total, m))
        if reason is not None:
            pool.stop.set()
            ex.limiter.terminate_group(group)
            for t in threads:
                t.join(timeout=30)
            if reason == "lease":
                raise LeaseLost(ex.job_id)
            raise Cancelled()
        for t in threads:
            t.join()
        if pool.lease_lost or (ex.keeper is not None and ex.keeper.lost.is_set()):
            raise LeaseLost(ex.job_id)
    except BaseException:
        pool.stop.set()
        if group.alive():
            ex.limiter.terminate_group(group)
        raise
    finally:
        with ex._proc_lock:
            ex.current_group = None
        acc = ex.limiter.group_accounting(group)
        ex.limiter.close_group(group)
        ctx.outputs["accounting"] = {**acc.as_dict(), "cpu_cap_enforced": bool(ex.limiter.cpu_cap_enforced)}
        ctx.outputs["parallel"] = {"items": n, "max_parallel": m, "peak_processes": pool.peak_procs,
                                   "launched": group.launched, "ok": pool.done, "failed": pool.failed,
                                   "commands_rel": pool.commands_rel}
    if label is not None:
        running, done, failed, total = pool.snapshot()
        ctx.progress(100.0, label(0, done, failed, total, m), force=True)
    return [outcomes.get(i) or ParallelOutcome(item_id(it), "CANCELED", "실행되지 않음") for i, it in enumerate(items)]
