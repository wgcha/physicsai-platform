"""작업 대기열 시험 도구(job-queues.md V-JQ-3~12): Study·작업 행 직접 생성, step 핸들러 대체(지연·기록), 표본 추적.

실제 Altair 도구를 쓰지 않는다 — 핸들러를 가짜(지정 시간 잠자기 + 기록)로 바꿔 구간 전환·동시성만 시험한다.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from sqlalchemy import text

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.job_types import JOB_TYPES


def new_study(engine: Any, name: str | None = None) -> str:
    sid = str(uuid.uuid4())
    name = name or "Q" + sid[:10]
    with engine.begin() as c:
        c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                       " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": name})
    return sid


def add_job(engine: Any, job_type: str, *, study_id: str | None = None, resume_from_step: int | None = None,
            params: dict[str, Any] | None = None) -> dict[str, Any]:
    """저장소 `insert_job`으로 작업 1건(T1, 초기 대기열 규칙 적용). Study를 안 주면 작업마다 새 Study(활성 unique 회피)."""
    sid = study_id or new_study(engine)
    with engine.begin() as c:
        study = studies_repo.require(c, sid)
        return jobs_repo.insert_job(c, study=study, job_type=job_type, params=params or {}, user_id="u-power",
                                    user_name="파워", resume_from_step=resume_from_step)


def job_row(engine: Any, jid: str) -> dict[str, Any]:
    with engine.connect() as c:
        return dict(c.execute(text("select * from jobs where id=:i"), {"i": jid}).one()._mapping)


class Recorder:
    """대체 핸들러가 남기는 기록: (시각, job_id, step_key, start|end, 실행기가 쥔 대기열)과 동시 실행 수."""

    def __init__(self) -> None:
        self.events: list[tuple[float, str, str, str, str]] = []
        self.lock = threading.Lock()
        self.active: dict[str, int] = {"CPU": 0, "GPU": 0}
        self.max_active: dict[str, int] = {"CPU": 0, "GPU": 0}
        self.lanes_by_job: dict[str, list[str]] = {}

    def lanes(self, jid: str) -> list[str]:
        """작업이 step을 실행한 대기열의 연속 구간(중복 제거) — 예 CPU → GPU → CPU."""
        out: list[str] = []
        for _t, j, _k, ph, lane in self.events:
            if j == jid and ph == "start" and (not out or out[-1] != lane):
                out.append(lane)
        return out

    def intervals(self, jid: str, step_key: str) -> tuple[float, float]:
        st = [t for t, j, k, ph, _l in self.events if j == jid and k == step_key and ph == "start"]
        en = [t for t, j, k, ph, _l in self.events if j == jid and k == step_key and ph == "end"]
        return st[0], en[0]


def patch_handlers(monkeypatch: Any, delays: dict[str, float] | None = None, *, default: float = 0.0,
                   fail: dict[tuple[str, str], str] | None = None) -> Recorder:
    """워커 step 핸들러 전부를 `delays[step_key]`(없으면 default)초 잠자고 기록하는 가짜로 바꾼다. fail = {(job_type, step_key): 오류 코드}."""
    from physicsai_core.errors import StepFailure
    from physicsai_worker import steps

    rec = Recorder()
    delays = delays or {}

    def make(jt: str, key: str) -> Any:
        def handler(ctx: Any) -> None:
            lane = ctx.ex.lane
            jid = ctx.ex.job_id
            with rec.lock:
                rec.events.append((time.time(), jid, key, "start", lane))
                if lane in rec.active:
                    rec.active[lane] += 1
                    rec.max_active[lane] = max(rec.max_active[lane], rec.active[lane])
            try:
                time.sleep(delays.get(key, default))
                if fail and (jt, key) in fail:
                    raise StepFailure(fail[(jt, key)], "시험용 실패")
            finally:
                with rec.lock:
                    rec.events.append((time.time(), jid, key, "end", lane))
                    if lane in rec.active:
                        rec.active[lane] -= 1

        return handler

    for (jt, key) in list(steps.HANDLERS):
        monkeypatch.setitem(steps.HANDLERS, (jt, key), make(jt, key))
    return rec


class Sampler(threading.Thread):
    """DB 표본 추적: RUNNING GPU·CPU 행 수 최댓값, GPU 보유자와 worker_slot 일치, 최대 CPU 도달."""

    def __init__(self, engine: Any, interval: float = 0.01) -> None:
        super().__init__(daemon=True)
        self.engine, self.interval = engine, interval
        self.max_gpu = self.max_cpu = 0
        self.gpu_mismatch = 0
        self.samples = 0
        self._stop_evt = threading.Event()

    def run(self) -> None:
        q = text("select lane, count(*), min(id), (select holder_job_id from worker_slot where id=1) from jobs"
                 " where state='RUNNING' and lane in ('CPU','GPU') group by lane")
        while not self._stop_evt.is_set():
            try:
                with self.engine.connect() as c:  # 한 스냅숏 안에서 읽는다
                    rows = {r[0]: r for r in c.execute(q)}
            except Exception:  # noqa: BLE001 - 시험 종료 중 연결 오류
                return
            self.samples += 1
            g, cp = rows.get("GPU"), rows.get("CPU")
            self.max_gpu = max(self.max_gpu, g[1] if g else 0)
            self.max_cpu = max(self.max_cpu, cp[1] if cp else 0)
            if g and g[1] == 1 and g[3] != g[2]:
                self.gpu_mismatch += 1
            time.sleep(self.interval)

    def stop(self) -> None:
        self._stop_evt.set()
        self.join(timeout=5)


def wait_all_terminal(engine: Any, ids: list[str], timeout: float = 60.0) -> dict[str, str]:
    end = time.time() + timeout
    while True:
        with engine.connect() as c:
            rows = dict(c.execute(text("select id, state from jobs where id = any(:ids)"), {"ids": ids}).all())
        if all(s in ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED") for s in rows.values()) or time.time() > end:
            return rows
        time.sleep(0.05)


def all_gpu_types() -> list[str]:
    return [t for t, d in JOB_TYPES.items() if any(s.res == "gpu" for s in d.steps)]


class Pool:
    """수령 스레드 묶음: 각 스레드가 fn을 쉬지 않고 부른다(작업이 없으면 잠깐 쉼)."""

    def __init__(self) -> None:
        self.stop_evt = threading.Event()
        self.threads: list[threading.Thread] = []
        self.errors: list[BaseException] = []

    def spawn(self, n: int, fn: Any, name: str) -> None:
        def body() -> None:
            while not self.stop_evt.is_set():
                try:
                    r = fn()
                except BaseException as exc:  # noqa: BLE001
                    self.errors.append(exc)
                    return
                if r is None:
                    time.sleep(0.02)

        for i in range(n):
            t = threading.Thread(target=body, name=f"{name}{i}", daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self) -> None:
        self.stop_evt.set()
        for t in self.threads:
            t.join(timeout=15)
        assert not self.errors, self.errors
