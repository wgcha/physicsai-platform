"""①-3 HST 동시 실행(multiexec) 진행 표시 — 완료 순서와 무관한 집계, 실행 중/대기/완료 라벨."""

from __future__ import annotations

import re

from physicsai_worker.steps.stage1_train_data.doe_gen import HstRunTracker, hst_run_label

RX = re.compile(r"Finished run\s*\(\s*(?P<run>\d+)\s*\),\s*model\s*\(\s*m_?3\s*\)")


def _mk_runs(D, n):
    for k in range(1, n + 1):
        (D / "approaches" / "doe_1" / f"run__{k:05d}").mkdir(parents=True, exist_ok=True)


def test_parallel_runs_counted_and_out_of_order_finish(tmp_path):
    tr = HstRunTracker(str(tmp_path), "approaches/*/run__*", RX, total=10, multi=4)
    assert tr.poll(now=100.0) == (10.0, "실행 중 0 · 대기 10 · 완료 0/10 (동시 4)")
    _mk_runs(tmp_path, 4)  # HST가 4개 run 폴더를 동시에 만든 상태
    assert tr.poll(now=101.0) is None  # 2초 간격 미만이면 폴더 재조사 안 함
    assert tr.poll(now=102.5)[1] == "실행 중 4 · 대기 6 · 완료 0/10 (동시 4)"
    # run 3이 먼저 끝나도 '완료 1'(이전: run 번호 3 → 진행률 3/10으로 점프)
    pct, lbl = tr.line("Finished run (3), model (m_3)")
    assert pct == 10 + 1 / 10 * 85 and lbl == "실행 중 3 · 대기 6 · 완료 1/10 (동시 4)"
    assert tr.line("Finished run (3), model (m_1)") is None
    _mk_runs(tmp_path, 10)  # 폴더를 미리 다 만들어도 실행 중은 동시 실행 수 이하
    assert tr.poll(now=105.0)[1] == "실행 중 4 · 대기 5 · 완료 1/10 (동시 4)"
    for k in (1, 2, 4, 5, 6, 7, 8, 9, 10):
        pct, lbl = tr.line(f"Finished run ({k}), model (m_3)")
    assert pct == 95 and lbl == "실행 중 0 · 대기 0 · 완료 10/10 (동시 4)"


def test_label_without_total():
    assert hst_run_label(2, None, 5, None, 2) == "실행 중 2 · 완료 5 (동시 2)"
