"""동시 실행기 `run_parallel`(phase3 §14.5 S9 BP_GEN): 항목(run)마다 순차 명령 체인을 최대 M개 동시에 실행한다.

- 모든 자식 프로세스는 제한기의 그룹 1개(Windows = Job Object 1개)에 들어가 작업 1개분 한도를 나눠 쓴다.
- 항목 실패는 그 항목만 실패로 기록하고 나머지는 계속한다(`ParallelOutcome`). 호출자가 성공 0개·일부 실패를 판정한다.
- 취소·lease 상실: 주 스레드가 감지 → 그룹 전체 종료(프로세스 트리 포함) → Cancelled / LeaseLost.
- 외부 명령은 shell=False argv(제한기 launch), 실행 파일·인자는 설정 템플릿에서만(`ctx.render`).
300줄 분할(R-B): 결과 모양·병렬 실행기(ParallelRunner)·슬롯 풀은 `step_parallel_runner`(여기서 재노출, 로그 이름 physicsai_worker.executor 유지)."""

from __future__ import annotations

import queue
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from typing import Any

from physicsai_core.db.repositories.job_lease import LeaseLost
from physicsai_core.errors import DomainError, StepFailure

from .limiter.base import LimiterError
from .signals import Cancelled
from .step_parallel_runner import log, MEMORY_SAMPLE_S, ParallelOutcome, ParallelRunner, _Pool  # noqa: F401 - 기존 경로 재노출


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
