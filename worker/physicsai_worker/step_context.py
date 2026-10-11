"""step 핸들러가 쓰는 도구 모음(StepContext, §11.3). 실행기(executor.Executor)가 step마다 만든다.

외부 프로그램 실행(render·run_local·run_fanout·checkpoint_cancel)은 step_process.StepProcessMixin(상속).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import func

from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories.job_lease import LeaseLost
from physicsai_core.fileutil import sha256_file
from physicsai_core.paths import backup_existing, resolve_in_study, to_rel

from .signals import Cancelled
from .step_process import StepProcessMixin

if TYPE_CHECKING:
    from .executor import Executor

# 로거 이름은 분리 전과 같게 유지(로그 출력 불변)
log = logging.getLogger("physicsai_worker.executor")


class StepContext(StepProcessMixin):
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
            lease_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, progress_pct=pct, progress_label=lbl),
            lease_repo.job_update(c, self.ex.job_id, self.ex.token, progress_pct=job_pct, progress_label=lbl,
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
            lease_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, state="RUNNING", started_at=func.now(),
                                   progress_pct=None, progress_label=None),
            lease_repo.job_update(c, self.ex.job_id, self.ex.token, current_step_no=self.step_no, progress_pct=job_pct,
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
        self.ex.db(lambda c: lease_repo.step_update(c, self.ex.job_id, self.ex.token, self.step_no, **vals))

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

