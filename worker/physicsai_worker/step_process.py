"""StepContext의 외부 프로그램 실행부(§11.3): 명령 렌더링, `run_local`(제한기·취소·진행률), 팬아웃 `run_fanout`(phase2 §4.3),
동시 실행 `run_parallel`(phase3 §14.5, step_parallel)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from physicsai_core.childenv import child_env
from physicsai_core.commands import (
    EXECUTABLE_PLACEHOLDERS,
    parse_placeholders,
    render_argv,
)
from physicsai_core.config import effective_altair
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories.job_lease import LeaseLost
from physicsai_core.errors import StepFailure
from physicsai_core.parsers.log_errors import ErrorDetector

from .signals import Cancelled

# 로거 이름은 분리 전과 같게 유지(로그 출력 불변)
log = logging.getLogger("physicsai_worker.executor")


class StepProcessMixin:
    """외부 프로그램 실행 메서드 묶음. StepContext가 상속한다(시험이 `StepContext.run_local`을 monkeypatch해도
    `run_fanout`의 `self.run_local` 호출에 그대로 적용된다)."""

    # ---- 외부 프로그램 ----
    def render(self, template_key: str, values: dict[str, str]) -> tuple[list[str], str | None]:
        """(argv, 실행 파일 altair 키). 실행 파일이 없으면 StepFailure(EXECUTABLE_MISSING)."""
        s = self.settings
        template = getattr(s.commands, template_key)
        exes = effective_altair(s)
        argv = render_argv(template_key, template, values, executables=exes, write_files=s.score.write_files)
        exe_key = next(
            (EXECUTABLE_PLACEHOLDERS[n] for el in (template or []) if not el.startswith("@")
             for n in parse_placeholders(el) if n in EXECUTABLE_PLACEHOLDERS),
            None,
        )
        exe = exes.get(exe_key or "", "") if exe_key else ""
        if not exe or not os.path.isfile(exe):
            raise StepFailure("EXECUTABLE_MISSING", f"실행 파일이 없습니다: altair.{exe_key} = {exe}")
        return argv, exe_key

    def run_local(
        self,
        template_key: str,
        values: dict[str, str],
        *,
        cwd: str,
        outputs_to_backup: list[str] | None = None,
        env_add: dict[str, str] | None = None,
        check_log_errors: bool | None = None,
        error_patterns: list[str] | None = None,
        line_hook: Callable[[str], tuple[float | None, str | None] | None] | None = None,
        poll_hook: Callable[[], tuple[float | None, str | None] | None] | None = None,
        record_command: bool = True,
        log_errors_fail: bool = True,
        allow_nonzero_exit: bool = False,
    ) -> int:
        """외부 프로그램 1회(제한기 안, shell=False argv).

        error_patterns: 로그 오류 정규식(None이면 commands_log_error_patterns). check_log_errors=False면 적용 안 함.
        check_log_errors=None(기본): error_patterns를 주었거나 edspy 템플릿(edspy_*)일 때만 적용(계약 platform.md §8.3 —
        commands_log_error_patterns는 edspy step 전용).
        line_hook(line) / poll_hook(): (진행률 %, 라벨)을 돌려주면 step 진행률에 반영(phase2 §6.2·§6.4·§6.12).
        record_command=False: 팬아웃(§4.3)이 job_steps.command를 직접 기록한다.
        log_errors_fail=False: 오류 줄 수만 센다(self.last_error_lines, phase2 가정 A-8).
        allow_nonzero_exit=True: 종료코드≠0이어도 실패로 보지 않고 rc를 돌려준다 — 호출자가 출력 파일로 성공을 판정
        (phase3 §11.4 GEOM_UPDATE·MESH, 원본 SimLab rc 무시). 메모리 한도 종료는 그대로 RESOURCE_LIMIT.
        """
        s = self.settings
        argv, _exe_key = self.render(template_key, values)
        if outputs_to_backup:
            self.backup(outputs_to_backup)
        os.makedirs(cwd, exist_ok=True)
        env = child_env(s.worker.env_passthrough, env_add, deny_names=[s.database.url_env])
        self.last_argv = argv
        if record_command:
            command = {"argv": argv, "cwd": cwd, "env_added": dict(env_add or {})}
            self.ex.db(lambda c: lease_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, command=command))
        self.log("[CMD] " + " ".join(argv))
        patterns = error_patterns if error_patterns is not None else s.commands_log_error_patterns
        if check_log_errors is None:
            check_log_errors = error_patterns is not None or template_key.startswith("edspy_")
        detector = ErrorDetector(patterns) if check_log_errors else None
        proc = self.ex.limiter.launch(argv, cwd, env, self.ex.limits)
        with self.ex._proc_lock:
            self.ex.current_proc = proc
        last_line = [""]
        prog: list[Any] = [None, None]  # pct, label
        hook_lock = threading.Lock()

        def apply(res: tuple[float | None, str | None] | None) -> None:
            if res is None:
                return
            with hook_lock:
                if res[0] is not None:
                    prog[0] = res[0]
                if res[1] is not None:
                    prog[1] = res[1]

        def reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                self.log(line)
                if detector is not None:
                    detector.feed(line)
                if line_hook is not None:
                    try:
                        apply(line_hook(line))
                    except Exception:  # noqa: BLE001 - 진행률 해석 오류는 실행에 영향 없음
                        log.exception("line_hook 오류")
                if line.strip():
                    last_line[0] = line.strip()[:120]

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        interval = s.worker.cancel_check_interval_s
        cancelled = False
        try:
            while proc.poll() is None:
                time.sleep(min(interval, 0.25))
                if self.ex.keeper is not None and self.ex.keeper.lost.is_set():
                    self.ex.limiter.terminate(proc)
                    raise LeaseLost(self.ex.job_id)
                now = time.time()
                if now - getattr(self, "_last_cancel_check", 0.0) >= interval:
                    self._last_cancel_check = now
                    if self.ex.cancel_requested():
                        self.log("[CANCEL] 취소 요청 감지 — 프로세스 트리를 종료합니다")
                        self.ex.limiter.terminate(proc)
                        cancelled = True
                        break
                if poll_hook is not None:
                    apply(poll_hook())
                with hook_lock:
                    pct, lbl = prog[0], prog[1]
                if pct is not None or lbl or last_line[0]:
                    self.progress(pct, lbl or last_line[0])
            t.join(timeout=10)
            if poll_hook is not None:
                apply(poll_hook())
            if line_hook is not None or poll_hook is not None:
                with hook_lock:
                    if prog[0] is not None or prog[1]:
                        self.progress(prog[0], prog[1] or last_line[0], force=True)
            acc = self.ex.limiter.accounting(proc)
        except BaseException:
            # lease 상실·DB 오류 등 어떤 이유로든 감시가 끝나면 프로세스 트리를 남기지 않는다
            if proc.poll() is None:
                self.ex.limiter.terminate(proc)
            raise
        finally:
            with self.ex._proc_lock:
                self.ex.current_proc = None
            self.ex.limiter.close(proc)
        self.last_accounting = acc
        self.outputs["accounting"] = acc.as_dict()
        if cancelled:
            raise Cancelled()
        rc = proc.poll()
        rc = -1 if rc is None else rc
        self.last_exit_code = rc
        self.log(f"[EXIT] {rc}")
        if record_command:
            self.ex.db(lambda c: lease_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, exit_code=rc))
        self.last_error_lines = detector.count if detector is not None else 0
        self.last_error_match = detector.first_match if detector is not None else None
        if rc != 0:
            if acc.memory_limit_hit:
                raise StepFailure("RESOURCE_LIMIT", f"작업 메모리 한도({self.ex.limits.memory_gb} GB)에 도달해 종료되었습니다")
            if not allow_nonzero_exit:
                raise StepFailure("EXIT_NONZERO", f"종료코드 {rc}: {last_line[0]}")
            self.last_line = last_line[0]
        if detector is not None and detector.first_match and log_errors_fail:
            raise StepFailure("LOG_ERROR_DETECTED", f"로그에서 오류를 감지했습니다: {detector.first_match}")
        return rc

    def run_fanout(
        self,
        template_key: str,
        targets: list[dict[str, Any]],
        *,
        cwd: str,
        success: Callable[[dict[str, Any]], bool],
        env_add: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """팬아웃 LOCAL(phase2 §4.3): 대상마다 같은 템플릿을 순차 실행. 실패해도 다음 대상 계속 → 요약.

        targets = [{target_id, values}]. 반환 {ok:[target_id], failed:[{target_id, exit_code, code, reason}]}.
        성공 0개 → StepFailure(첫 실패 코드). 일부 실패 → 작업 warnings PARTIAL_OUTPUT.
        """
        n = len(targets)
        rel = f"logs/{self.ex.job_id}/step_{self.step_no:02d}_{self.key}.commands.jsonl"
        cmd_path = self.abs(rel)
        os.makedirs(os.path.dirname(cmd_path), exist_ok=True)
        ok: list[str] = []
        failed: list[dict[str, Any]] = []
        first_argv: list[str] | None = None
        peak: int | None = None
        cpu = 0.0
        cpu_seen = False
        for k, t in enumerate(targets, 1):
            self.checkpoint_cancel()
            tid = t["target_id"]
            self.log(f"=== [{k}/{n}] {tid} ===")
            tcwd = t.get("cwd") or cwd
            rec: dict[str, Any] = {"target_id": tid, "argv": None, "cwd": tcwd, "exit_code": None}
            code = reason = None
            try:
                try:
                    argv, _ = self.render(template_key, t["values"])
                    rec["argv"] = argv
                    if first_argv is None:
                        first_argv = argv
                        command = {"argv": argv, "cwd": tcwd, "env_added": dict(env_add or {}), "invocations": n,
                                   "commands_rel": rel}
                        self.ex.db(lambda c: lease_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no,
                                                                      command=command))
                    base = (k - 1) / n * 100.0
                    self.run_local(template_key, t["values"], cwd=tcwd, env_add=env_add, check_log_errors=False,
                                   record_command=False, poll_hook=lambda b=base, i=k, x=tid: (b, f"{i}/{n} {x}"))
                    rec["exit_code"] = self.last_exit_code
                except StepFailure as exc:
                    rec["exit_code"] = getattr(self, "last_exit_code", None) if exc.code == "EXIT_NONZERO" else None
                    code, reason = exc.code, exc.message
                acc = getattr(self, "last_accounting", None)
                if acc is not None:
                    if acc.peak_memory_bytes is not None:
                        peak = max(peak or 0, acc.peak_memory_bytes)
                    if acc.cpu_time_s is not None:
                        cpu += acc.cpu_time_s
                        cpu_seen = True
                    self.last_accounting = None
                if code is None and not success(t):
                    code, reason = "OUTPUT_MISSING", "출력 파일이 만들어지지 않았습니다"
            finally:
                with open(cmd_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if code is None:
                ok.append(tid)
            else:
                self.log(f"[TARGET FAIL] {tid}: {code} {reason}")
                failed.append({"target_id": tid, "exit_code": rec["exit_code"], "code": code, "reason": (reason or "")[:200]})
            self.progress(k / n * 100.0, f"{k}/{n} {tid}", force=True)
        self.outputs["accounting"] = {"peak_memory_bytes": peak, "cpu_time_s": cpu if cpu_seen else None,
                                      "cpu_cap_enforced": bool(self.ex.limiter.cpu_cap_enforced)}
        self.outputs["fanout"] = {"invocations": n, "ok": len(ok), "failed": len(failed)}
        if n and not ok:
            first = failed[0]
            raise StepFailure(first["code"] or "EXIT_NONZERO", f"대상 {n}개 모두 실패: {first['target_id']} — {first['reason']}")
        if failed:
            self.add_warning("PARTIAL_OUTPUT", f"{n}개 중 {len(failed)}개 실패")
        return {"ok": ok, "failed": failed}

    def run_parallel(self, items: list[Any], fn: Callable[[Any, Any], None], *, item_id: Callable[[Any], str],
                     max_parallel: int, label: Callable[[int, int, int, int, int], str] | None = None) -> list[Any]:
        """동시 실행(phase3 §14.5 BP_GEN): 항목마다 fn(runner, item)을 최대 max_parallel개 동시에. 모든 자식 프로세스는
        제한기 그룹 1개(Windows Job Object 1개)를 공유한다. 상세는 step_parallel.run_parallel."""
        from .step_parallel import run_parallel

        return run_parallel(self, items, fn, item_id=item_id, max_parallel=max_parallel, label=label)

    def checkpoint_cancel(self) -> None:
        """취소 플래그를 즉시 확인(팬아웃 대상 사이, §4.3)."""
        if self.ex.keeper is not None and self.ex.keeper.lost.is_set():
            raise LeaseLost(self.ex.job_id)
        if self.ex.cancel_requested():
            raise Cancelled()
