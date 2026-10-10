"""step 핸들러가 쓰는 도구 모음(StepContext, §11.3). 실행기(executor.Executor)가 step마다 만든다."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import func

from physicsai_core.childenv import child_env
from physicsai_core.commands import EXECUTABLE_PLACEHOLDERS, parse_placeholders, render_argv
from physicsai_core.config import effective_altair
from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories.jobs import LeaseLost
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import sha256_file
from physicsai_core.parsers.log_errors import ErrorDetector
from physicsai_core.paths import backup_existing, resolve_in_study, to_rel

from .signals import Cancelled

if TYPE_CHECKING:
    from .executor import Executor

# 로거 이름은 분리 전과 같게 유지(로그 출력 불변)
log = logging.getLogger("physicsai_worker.executor")


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
            item["sha256"] = sha256_file(path)
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
            sha256=sha256_file(path), content_type=ctype,
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
