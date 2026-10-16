"""공유 회계 그룹(Windows Job 1개)의 RESOURCE_LIMIT 판정(D3-53): run별 종료코드 ≠ 0이고 메모리 한도 도달 기록이 그 run의
실행 시간대와 겹칠 때만 RESOURCE_LIMIT(다른 run과 함께 겹치면 "원인 불확실" 문구), 아니면 종료코드를 그대로 돌려준다."""

from __future__ import annotations

import os
import sys
import threading
from types import SimpleNamespace

import pytest
from physicsai_core.errors import StepFailure
from physicsai_core.limits import compute_limits
from physicsai_worker.limiter.base import Accounting, ProcGroup
from physicsai_worker.limiter.null import NullLimiter
from physicsai_worker.step_parallel import ParallelRunner, _Pool

LIM = compute_limits(4, 2, "below_normal", False, 0.7, 8, 16)


# ---- 순수 판정(ProcGroup.memory_verdict) ----------------------------------------------------------------


def _group() -> ProcGroup:
    return ProcGroup(size=2, limits=LIM, shared_accounting=True)


def test_verdict_no_hit_and_before_after():
    g = _group()
    a = g.run_started(1.0)
    g.note_memory(False, 1.0)
    g.run_ended(a, 2.0)
    assert g.memory_verdict(a) is None                                  # 도달 기록 없음
    g.note_memory(False, 2.5)
    g.note_memory(True, 3.0)                                            # 도달 ∈ (2.5, 3.0]
    assert g.memory_verdict(a) is None                                  # a 끝(2.0) 뒤 → a 탓 아님
    b = g.run_started(4.0)
    g.run_ended(b, 5.0)
    assert g.memory_verdict(b) is None                                  # b 시작 전에 이미 도달 → b 탓 아님
    g.note_memory(False, 9.0)                                           # 도달 뒤 표본은 기록을 바꾸지 않는다
    assert (g.mem_ok_at, g.mem_hit_at) == (2.5, 3.0)


def test_verdict_exact_and_uncertain():
    g = _group()
    a = g.run_started(1.0)
    g.note_memory(False, 1.0)
    g.note_memory(False, 1.5)
    g.note_memory(True, 2.0)
    g.run_ended(a, 2.2)
    assert g.memory_verdict(a) == "exact"                               # (1.5, 2.0] ⊂ [1.0, 2.2], 혼자 실행
    b = g.run_started(1.8)                                              # 도달 구간에 다른 run도 돌았다
    g.run_ended(b, 3.0)
    assert g.memory_verdict(a) == "uncertain" and g.memory_verdict(b) == "uncertain"
    g2 = _group()
    c = g2.run_started(1.6)                                             # 시작 전 표본 없음 → 시작 전에 도달했을 수 있음
    g2.note_memory(False, 1.0)
    g2.note_memory(True, 2.0)
    g2.run_ended(c, 2.5)
    assert g2.memory_verdict(c) == "uncertain"
    g3 = _group()
    d = g3.run_started(1.0)                                             # 아직 실행 중(끝 None)인 다른 run도 겹침으로 친다
    e = g3.run_started(1.0)
    g3.note_memory(False, 1.0)
    g3.note_memory(True, 1.5)
    g3.run_ended(e, 2.0)
    assert g3.memory_verdict(e) == "uncertain" and g3.memory_verdict(d) == "uncertain"


# ---- ParallelRunner.run(실제 프로세스, 가짜 공유 회계) ------------------------------------------------------


class SharedFake(NullLimiter):
    """Windows Job처럼 회계를 그룹이 공유: flag 파일이 생기면(최고 사용량은 줄지 않음) 그 뒤로 계속 '도달'."""

    def __init__(self, flag: str) -> None:
        self.flag = flag

    def open_group(self, limits, size):
        return ProcGroup(size=size, limits=limits, shared_accounting=True)

    def _acc(self) -> Accounting:
        return Accounting(memory_limit_hit=os.path.exists(self.flag))

    def group_accounting(self, group):
        return self._acc()

    def accounting(self, proc):
        return self._acc()


def _pool(tmp_path, lim) -> _Pool:
    logs: list[str] = []
    ex = SimpleNamespace(job_id="j" * 32, token="t", limiter=lim, limits=LIM, db=lambda fn: None)
    ctx = SimpleNamespace(
        ex=ex, step_no=1, key="BP_GEN", abs=lambda rel: str(tmp_path / rel), log=logs.append,
        render=lambda key, v: (v["argv"], v["argv"][0]), backup=lambda paths: None,
        settings=SimpleNamespace(worker=SimpleNamespace(env_passthrough=["PATH", "SYSTEMROOT"]),
                                 database=SimpleNamespace(url_env="PHYSICSAI_DATABASE_URL")))
    pool = _Pool(ctx, lim.open_group(LIM, 2), 2, 2)
    pool.logs = logs  # type: ignore[attr-defined]
    return pool


def _py(code: str) -> dict[str, list[str]]:
    return {"argv": [sys.executable, "-I", "-c", code]}


def _run(pool: _Pool, item: str, code: str, cwd) -> int:
    return ParallelRunner(pool, item).run("geom_update", _py(code), cwd=str(cwd))


def test_runner_exact_resource_limit(tmp_path):
    flag = tmp_path / "hit.flag"
    pool = _pool(tmp_path, SharedFake(str(flag)))
    code = f"import time,sys\ntime.sleep(0.7)\nopen({str(flag)!r},'w').close()\ntime.sleep(0.7)\nsys.exit(3)"
    with pytest.raises(StepFailure) as ei:
        _run(pool, "run__00001", code, tmp_path)
    assert ei.value.code == "RESOURCE_LIMIT" and "도달해 종료되었습니다" in ei.value.message


def test_runner_hit_before_this_run_is_plain_exit(tmp_path):
    flag = tmp_path / "hit.flag"
    pool = _pool(tmp_path, SharedFake(str(flag)))
    first = f"open({str(flag)!r},'w').close()"
    assert _run(pool, "run__00001", first, tmp_path) == 0             # 앞 run이 한도에 도달(성공 종료)
    assert _run(pool, "run__00002", "import sys; sys.exit(4)", tmp_path) == 4   # 뒤 run 실패는 일반 종료코드
    assert any("겹치지 않아 일반 종료코드" in x for x in pool.logs)  # type: ignore[attr-defined]


def test_runner_concurrent_overlap_is_uncertain(tmp_path):
    flag = tmp_path / "hit.flag"
    pool = _pool(tmp_path, SharedFake(str(flag)))
    out: dict[str, object] = {}

    def a() -> None:
        out["a"] = _run(pool, "run__00001", "import time; time.sleep(2.0)", tmp_path)

    t = threading.Thread(target=a)
    t.start()
    code = f"import time,sys\ntime.sleep(0.7)\nopen({str(flag)!r},'w').close()\ntime.sleep(0.5)\nsys.exit(3)"
    with pytest.raises(StepFailure) as ei:
        _run(pool, "run__00002", code, tmp_path)
    t.join()
    assert out["a"] == 0                                                  # 성공한 run은 영향 없음
    assert ei.value.code == "RESOURCE_LIMIT"
    assert "작업 묶음이 메모리 한도" in ei.value.message and "이 run의 원인인지 불확실" in ei.value.message


def test_runner_unshared_group_keeps_per_process_rule(tmp_path):
    """POSIX·null 그룹(프로세스별 회계)은 기존대로 rc≠0 + 도달 = RESOURCE_LIMIT."""

    class PerProc(NullLimiter):
        def accounting(self, proc):
            return Accounting(memory_limit_hit=True)

    pool = _pool(tmp_path, PerProc())
    assert pool.group.shared_accounting is False
    with pytest.raises(StepFailure) as ei:
        _run(pool, "run__00001", "import sys; sys.exit(2)", tmp_path)
    assert ei.value.code == "RESOURCE_LIMIT" and "도달해 종료되었습니다" in ei.value.message
    assert _run(pool, "run__00002", "pass", tmp_path) == 0
