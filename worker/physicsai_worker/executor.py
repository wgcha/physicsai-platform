"""step 실행기(§11.3). claim된 작업 1건의 step 체인을 실행한다.

- lease는 LeaseKeeper 스레드가 heartbeat_interval_s마다 renew. 실패 → 소유권 상실: 프로세스 트리 종료, 이후 상태 쓰기 없음
- LOCAL step은 제한기 안에서 argv 배열(shell=False)로만 실행
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.engine import Engine

from physicsai_core.childenv import child_env
from physicsai_core.commands import EXECUTABLE_PLACEHOLDERS, TEMPLATE_SPECS, parse_placeholders, render_argv
from physicsai_core.config import Settings, effective_altair
from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories.jobs import LeaseLost
from physicsai_core.errors import DomainError, StepFailure
from physicsai_core.job_types import JOB_TYPES
from physicsai_core.limits import EffectiveLimits
from physicsai_core.parsers.log_errors import ErrorDetector, Masker
from physicsai_core.paths import backup_existing, backup_stamp, real, resolve_in_study, study_dir, to_rel

from .limiter.base import LimiterError, ProcessLimiter

log = logging.getLogger("physicsai_worker.executor")


class Cancelled(Exception):
    pass


class StepSkipped(Exception):
    def __init__(self, label: str = "") -> None:
        super().__init__(label)
        self.label = label


class EnterWaitingHpc(Exception):
    """HPC_SUBMIT 성공 → T5."""


class LeaseKeeper(threading.Thread):
    def __init__(self, engine: Engine, job_id: str, token: str, ttl: float, interval: float, slot: bool,
                 on_lost: Callable[[], None]) -> None:
        super().__init__(daemon=True, name=f"lease-{job_id[:8]}")
        self.engine, self.job_id, self.token, self.ttl, self.interval, self.slot = engine, job_id, token, ttl, interval, slot
        self.on_lost = on_lost
        self.lost = threading.Event()
        self._stop = threading.Event()
        self.paused = threading.Event()  # 시험: 워커 사망 모사

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            if self.paused.is_set():
                continue
            try:
                with self.engine.begin() as conn:
                    ok = jobs_repo.renew(conn, self.job_id, self.token, self.ttl, slot=self.slot)
            except Exception:  # DB 일시 오류: 다음 주기에 재시도(만료 전이면 유지)
                log.exception("lease renew 오류")
                continue
            if not ok:
                self.lost.set()
                self.on_lost()
                return

    def stop(self) -> None:
        self._stop.set()


class Executor:
    def __init__(self, worker: Any, job: dict[str, Any]) -> None:
        self.w = worker
        self.engine: Engine = worker.engine
        self.settings: Settings = worker.settings
        self.limiter: ProcessLimiter = worker.limiter
        self.limits: EffectiveLimits = worker.limits
        self.job = job
        self.job_id: str = job["id"]
        self.token: str = job["lease_token"]
        self.jt = JOB_TYPES[job["job_type"]]
        with self.engine.connect() as conn:
            self.study = studies_repo.require(conn, job["study_id"])
            self.workspace_id = jobs_repo.root_job_id(conn, job)
        self.study_root = real(study_dir(self.settings.storage.ai_root, self.study["folder_name"]))
        self.stamp = backup_stamp()
        self.current_proc: Any = None
        self._proc_lock = threading.Lock()
        self.keeper: LeaseKeeper | None = None
        self.masker = Masker(self.settings.logging.mask_patterns)
        self.log_dir = os.path.join(self.study_root, "logs", self.job_id)
        os.makedirs(self.log_dir, exist_ok=True)

    # ---- DB 도우미 ----
    def db(self, fn: Callable[[Any], Any]) -> Any:
        if self.keeper is not None and self.keeper.lost.is_set():
            raise LeaseLost(self.job_id)
        with self.engine.begin() as conn:
            return fn(conn)

    def result(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            j = jobs_repo.get_job(conn, self.job_id)
        return dict((j or {}).get("result") or {})

    def patch_result(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self.db(lambda c: jobs_repo.patch_result(c, self.job_id, self.token, patch))

    def add_warning(self, code: str, message: str) -> None:
        self.db(lambda c: jobs_repo.add_warning(c, self.job_id, self.token, code, message))

    def _on_lost(self) -> None:
        log.warning("lease 소유권 상실: %s", self.job_id)
        with self._proc_lock:
            p = self.current_proc
        if p is not None:
            try:
                self.limiter.terminate(p)
            except Exception:
                log.exception("lease 상실 후 프로세스 종료 실패")

    def cancel_requested(self) -> bool:
        with self.engine.connect() as conn:
            return jobs_repo.is_cancel_requested(conn, self.job_id)

    # ---- 실행 ----
    def run(self) -> str | None:
        """작업을 끝까지(또는 상태 전이까지) 실행. 최종 상태 또는 None(lease 상실)."""
        slot = bool(self.job.get("holds_slot"))
        ws = self.settings.worker
        self.keeper = LeaseKeeper(self.engine, self.job_id, self.token, ws.lease_ttl_s, ws.heartbeat_interval_s, slot, self._on_lost)
        self.w.current_executor = self
        self.keeper.start()
        try:
            return self._run_steps()
        except LeaseLost:
            log.warning("작업 %s: lease 상실로 중단(상태 쓰기 없음)", self.job_id)
            return None
        finally:
            self.keeper.stop()
            self.w.current_executor = None

    def _release(self, state: str, code: str | None = None, msg: str | None = None) -> str:
        self.db(lambda c: jobs_repo.release(c, self.job_id, self.token, state, failure_code=code, failure_message=msg))
        return state

    def _job_log(self, text: str) -> None:
        with open(os.path.join(self.log_dir, "job.log"), "a", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")

    def _run_steps(self) -> str | None:
        from .steps import HANDLERS

        collecting = self.job["state"] == "COLLECTING"
        with self.engine.connect() as conn:
            steps = jobs_repo.get_steps(conn, self.job_id)
        total_w = sum(self.jt.weight_of(s["step_key"]) for s in steps) or 1
        done_w = sum(self.jt.weight_of(s["step_key"]) for s in steps if s["state"] in ("SUCCEEDED", "SKIPPED"))
        for s in steps:
            if s["state"] != "PENDING":
                continue
            if collecting and s["kind"] != "COLLECT":
                return self._release("QUEUED")  # T14: 다음 step이 슬롯 필요
            if not collecting and s["kind"] in ("HPC_WAIT", "COLLECT"):
                raise StepFailure("INTERNAL_ERROR", "HPC 대기 step을 슬롯 실행기에서 만났습니다")
            if self.cancel_requested():
                return self._release("CANCELED")
            if not collecting:
                self.db(lambda c: jobs_repo.continue_running(c, self.job_id, self.token))
            ctx = StepContext(self, s, done_w, total_w)
            ctx.start()
            try:
                handler = HANDLERS[(self.job["job_type"], s["step_key"])]
                handler(ctx)
            except StepSkipped as sk:
                ctx.finish("SKIPPED", label=sk.label or None)
            except EnterWaitingHpc:
                ctx.finish("SUCCEEDED")
                return self._release("WAITING_HPC")
            except Cancelled:
                ctx.finish("CANCELED")
                return self._release("CANCELED")
            except LeaseLost:
                raise
            except (StepFailure, DomainError, LimiterError) as exc:
                code = getattr(exc, "code", "INTERNAL_ERROR")
                if isinstance(exc, DomainError):
                    code = "INPUT_INVALID"
                msg = getattr(exc, "message", str(exc))
                ctx.log(f"[FAIL] {code}: {msg}")
                ctx.finish("FAILED", code=code, message=msg)
                return self._release("FAILED", code, msg)
            except Exception as exc:  # noqa: BLE001
                ctx.log("[FAIL] INTERNAL_ERROR\n" + traceback.format_exc())
                ctx.finish("FAILED", code="INTERNAL_ERROR", message=f"내부 오류: {exc}")
                return self._release("FAILED", "INTERNAL_ERROR", f"내부 오류: {exc}")
            else:
                ctx.finish("SUCCEEDED")
            done_w += self.jt.weight_of(s["step_key"])
        return self._release("SUCCEEDED")


class StepContext:
    """step 핸들러가 쓰는 도구 모음."""

    def __init__(self, ex: Executor, step: dict[str, Any], done_w: int, total_w: int) -> None:
        self.ex = ex
        self.step = step
        self.step_no: int = step["step_no"]
        self.key: str = step["step_key"]
        self.settings = ex.settings
        self.job = ex.job
        self.params: dict[str, Any] = ex.job["params"]
        self.study = ex.study
        self.root = ex.study_root
        self.workspace_id = ex.workspace_id
        self.done_w, self.total_w = done_w, total_w
        self.weight = ex.jt.weight_of(self.key)
        self.log_path = os.path.join(self.root, step["log_rel"])
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.outputs: dict[str, Any] = {"files": []}
        self._last_progress = 0.0
        self._label: str | None = None

    # ---- 경로 ----
    def abs(self, rel: str) -> str:
        return resolve_in_study(self.root, rel)

    def rel(self, path: str) -> str:
        return to_rel(self.root, path)

    def backup(self, paths: list[str]) -> list[str]:
        moved = backup_existing(self.root, paths, self.ex.job_id, self.ex.stamp)
        for m in moved:
            self.log(f"[BACKUP] 기존 산출물을 _backup/{self.ex.stamp}_{self.ex.job_id}/{m} 로 옮겼습니다")
        return moved

    # ---- 로그·진행률 ----
    def log(self, line: str) -> None:
        line = self.ex.masker(line.rstrip("\n"))
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self.ex._job_log(f"[{self.key}] {line}")

    def progress(self, pct: float | None, label: str | None = None, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_progress < 0.5:
            return
        self._last_progress = now
        job_pct = None
        if pct is not None:
            job_pct = round(100.0 * (self.done_w + self.weight * max(0.0, min(100.0, pct)) / 100.0) / self.total_w, 2)
        lbl = (label or self._label or "")[:120] or None
        self._label = lbl
        self.ex.db(lambda c: (
            jobs_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, progress_pct=pct, progress_label=lbl),
            jobs_repo.job_update(c, self.ex.job_id, self.ex.token, progress_pct=job_pct, progress_label=lbl,
                                 current_step_no=self.step_no),
        ))

    def checkpoint(self) -> None:
        """취소·lease 확인 지점(파일 1개 복사·1 MiB마다)."""
        if self.ex.keeper is not None and self.ex.keeper.lost.is_set():
            raise LeaseLost(self.ex.job_id)
        now = time.time()
        if now - getattr(self, "_last_cancel_check", 0.0) >= self.settings.worker.cancel_check_interval_s:
            self._last_cancel_check = now
            if self.ex.cancel_requested():
                raise Cancelled()

    def start(self) -> None:
        job_pct = round(100.0 * self.done_w / self.total_w, 2)
        self.ex.db(lambda c: (
            jobs_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, state="RUNNING", started_at=func.now(),
                                  progress_pct=None, progress_label=None),
            jobs_repo.job_update(c, self.ex.job_id, self.ex.token, current_step_no=self.step_no, progress_pct=job_pct,
                                 progress_label=self.key),
        ))
        self.log(f"=== {self.key} 시작 {datetime.now(timezone.utc).isoformat()} ===")

    def finish(self, state: str, code: str | None = None, message: str | None = None, label: str | None = None) -> None:
        vals: dict[str, Any] = {"state": state, "finished_at": func.now(), "outputs": self.outputs}
        if state == "SUCCEEDED":
            vals["progress_pct"] = 100.0
        if label:
            vals["progress_label"] = label[:120]
        if code:
            vals["failure_code"] = code
            vals["failure_message"] = (message or "")[:500]
        self.log(f"=== {self.key} {state}{' ' + code if code else ''} ===")
        self.ex.db(lambda c: jobs_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, **vals))

    # ---- 결과·산출물 ----
    def result(self) -> dict[str, Any]:
        return self.ex.result()

    def patch_result(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self.ex.patch_result(patch)

    def add_warning(self, code: str, message: str) -> None:
        self.ex.add_warning(code, message)

    def add_output(self, path: str, sha: bool = False) -> None:
        item: dict[str, Any] = {"rel": self.rel(path), "size": os.path.getsize(path)}
        if sha:
            item["sha256"] = _sha256(path)
        self.outputs["files"].append(item)

    def register_artifact(self, kind: str, path: str, content_type: str | None = None) -> str | None:
        size = os.path.getsize(path)
        if size > self.settings.ui.max_artifact_bytes:
            self.add_warning("ARTIFACT_TOO_LARGE", f"{os.path.basename(path)}이(가) 표시 상한을 넘어 등록하지 않았습니다")
            return None
        ext = os.path.splitext(path)[1].lower()
        ctype = content_type or artifacts_repo.CONTENT_TYPES.get(ext, "text/plain")
        return self.ex.db(lambda c: artifacts_repo.insert(
            c, study_id=self.study["id"], job_id=self.ex.job_id, kind=kind, rel_path=self.rel(path), size=size,
            sha256=_sha256(path), content_type=ctype,
        ))

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
    ) -> int:
        """외부 프로그램 1회(제한기 안, shell=False argv).

        error_patterns: 로그 오류 정규식(None이면 commands_log_error_patterns). check_log_errors=False면 적용 안 함.
        check_log_errors=None(기본): error_patterns를 주었거나 edspy 템플릿(edspy_*)일 때만 적용(계약 platform.md §8.3 —
        commands_log_error_patterns는 edspy step 전용).
        line_hook(line) / poll_hook(): (진행률 %, 라벨)을 돌려주면 step 진행률에 반영(phase2 §6.2·§6.4·§6.12).
        record_command=False: 팬아웃(§4.3)이 job_steps.command를 직접 기록한다.
        log_errors_fail=False: 오류 줄 수만 센다(self.last_error_lines, phase2 가정 A-8).
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
            self.ex.db(lambda c: jobs_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, command=command))
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
            self.ex.db(lambda c: jobs_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, exit_code=rc))
        self.last_error_lines = detector.count if detector is not None else 0
        if rc != 0:
            if acc.memory_limit_hit:
                raise StepFailure("RESOURCE_LIMIT", f"작업 메모리 한도({self.ex.limits.memory_gb} GB)에 도달해 종료되었습니다")
            raise StepFailure("EXIT_NONZERO", f"종료코드 {rc}: {last_line[0]}")
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
                        self.ex.db(lambda c: jobs_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no,
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

    def checkpoint_cancel(self) -> None:
        """취소 플래그를 즉시 확인(팬아웃 대상 사이, §4.3)."""
        if self.ex.keeper is not None and self.ex.keeper.lost.is_set():
            raise LeaseLost(self.ex.job_id)
        if self.ex.cancel_requested():
            raise Cancelled()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


__all__ = ["Executor", "StepContext", "Cancelled", "StepSkipped", "EnterWaitingHpc", "TEMPLATE_SPECS"]
