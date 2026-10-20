"""opt-native ON-C4: ⑥ 최적화 기준(응답·방향·임계값·가중치)은 사용자가 정한다 — 자동 지정·기본값 없음."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from physicsai_core.stage5_optimize.surrogate import criteria

ROOT = Path(__file__).resolve().parents[2]


def test_missing_paths_order_and_scope():
    objs = [{"metric": "perf:A", "sense": None}, {"metric": "perf:B", "sense": "max"}]
    cons = [{"op": "<=", "value": None}, {"op": "range", "lo": 1.0, "hi": None}, {"op": ">=", "value": 2.0}]
    assert criteria.missing(objs, cons, None, max_objectives=3) == [
        "objectives.0.sense", "constraints.0.value", "constraints.1.hi", "weights"]
    assert criteria.missing([], [], None) == ["objectives"]
    # 단일 목적: 가중치 불필요(자명), 단수 objective 경로
    assert criteria.missing([{"sense": None}], [], None, obj_prefix="objective") == ["objective.sense"]
    assert criteria.missing([{"sense": "min"}], [], None) == []
    # 목적 수 초과는 OBJECTIVES_RANGE 담당 — 가중치 누락으로 중복 보고하지 않음
    assert "weights" not in criteria.missing([{"sense": "min"}] * 4, [], None, max_objectives=3)
    assert criteria.missing([{"sense": "min"}, {"sense": "max"}], [], [1.0, 2.0]) == []


def test_settings_missing_saved_rows_compat():
    """기존 저장 설정(API가 항상 sense·weights를 기록)은 그대로 통과 — 0014 이전 단일 `objective` 행 포함."""
    old_single = {"objective": {"metric": "resp:X_MAX", "series": None, "sense": "min"}, "constraints": []}
    assert criteria.settings_missing(old_single) == []
    multi = {"objectives": [{"metric": "perf:A", "sense": "min"}, {"metric": "perf:B", "sense": "max"}],
             "constraints": [{"metric": "perf:C", "op": "range", "value": None, "lo": 1.0, "hi": 2.0}], "weights": [0.5, 0.5]}
    assert criteria.settings_missing(multi) == []
    assert criteria.settings_missing({**multi, "weights": []}) == ["weights"]
    assert criteria.settings_missing({"objective": {"metric": "x"}, "constraints": [{"op": "<=", "value": None}]}) == [
        "objective.sense", "constraints.0.value"]
    for p in criteria.settings_missing({**multi, "objectives": [{"metric": "a"}, {"metric": "b"}], "weights": None}):
        assert criteria.item_message(p)  # 한국어 안내(값 제안 없음)


def test_worker_problem_refuses_missing_criteria():
    from physicsai_core.errors import StepFailure
    from physicsai_worker.steps.stage5_optimize.surrogate_common import _problem

    st = {"names": ["A"], "integer": [], "bounds": {"A": [0.0, 1.0]}, "objectives": [{"metric": "perf:A", "series": None}],
          "constraints": []}
    with pytest.raises(StepFailure) as e:
        _problem({"settings": st})
    assert e.value.code == criteria.CODE and "objectives.0.sense" in str(e.value)
    ok = _problem({"settings": {**st, "objectives": [{"metric": "perf:A", "series": None, "sense": "max"}]}})
    assert ok.sense == "max" and ok.weights == [1.0]


def test_problem_from_settings_has_no_invented_defaults():
    from physicsai_core.stage5_optimize.surrogate.dataset_model import Problem

    st = {"names": ["A"], "integer": [], "bounds": {"A": [0.0, 1.0]},
          "objectives": [{"metric": "a", "sense": None}, {"metric": "b", "sense": "max"}]}
    p = Problem.from_settings(st)
    assert p.objectives[0].sense is None and p.weights == []  # 기본 min·균등 가중치로 채우지 않음


def test_api_schema_and_space_no_defaults():
    from physicsai_api.schemas.surrogate_opt_req import SoObjective
    from physicsai_api.services.surrogate_opt_space import _weights

    assert SoObjective(metric="perf:A").sense is None
    probs: list = []
    assert _weights(type("B", (), {"weights": None})(), 2, probs) == [] and not probs
    assert _weights(type("B", (), {"weights": None})(), 1, probs) == [1.0]


def test_legacy_constraint_criteria():
    from physicsai_api.services.job_params.stage5_optimize import legacy_criteria_missing

    rows = [{"goal": "MINIMIZE"}, {"goal": "CONSTRAINT", "value": 1.0}, {"goal": "CONSTRAINT", "bound": "<="},
            {"goal": "CONSTRAINT", "bound": ">=", "value": 2.0}]
    assert legacy_criteria_missing(rows) == ["responses.1.bound", "responses.2.value"]


def test_static_no_auto_sense_or_equal_weights():
    """⑥ 내장 최적화 코드에 방향 기본 'min'·균등 가중치 대체가 다시 들어오지 않는다(정적)."""
    files = [ROOT / "backend/physicsai_api/schemas/surrogate_opt_req.py",
             ROOT / "backend/physicsai_api/services/surrogate_opt_space.py",
             ROOT / "backend/physicsai_api/services/surrogate_opt_pareto.py",
             ROOT / "backend/physicsai_core/stage5_optimize/surrogate/dataset_model.py"]
    for f in files:
        src = f.read_text(encoding="utf-8")
        assert 'get("sense") or "min"' not in src, f
        assert "[1.0 / m] * m" not in src or f.name == "surrogate_opt_space.py", f
        assert "[1.0 / len(objs)] * len(objs)" not in src, f
        ast.parse(src)
    req = (ROOT / "backend/physicsai_api/schemas/surrogate_opt_req.py").read_text(encoding="utf-8")
    assert 'Literal["min", "max"] = "min"' not in req
    fe = (ROOT / "frontend/src/stages/stage5/surrogate/perfRules.ts").read_text(encoding="utf-8")
    assert "DEFAULT_WEIGHT" not in fe
    rules = (ROOT / "frontend/src/stages/stage5/rules.ts").read_text(encoding="utf-8")
    assert 'r.bound ?? "<="' not in rules
