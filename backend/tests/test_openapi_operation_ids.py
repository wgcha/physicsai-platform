"""operationId 스냅샷(architecture.md §0 동결): 라우터 함수 이름이 바뀌면 여기서 먼저 실패한다."""

from __future__ import annotations

from physicsai_test_support import REPO

SNAPSHOT = REPO / "backend" / "tests" / "data" / "operation_ids.txt"


def _operation_ids(spec: dict) -> list[str]:
    return sorted(op["operationId"] for item in spec["paths"].values() for op in item.values() if isinstance(op, dict) and "operationId" in op)


def test_operation_ids_match_snapshot():
    from physicsai_api.export_openapi import build_openapi

    expected = SNAPSHOT.read_text(encoding="utf-8").split()
    actual = _operation_ids(build_openapi())
    assert len(actual) == len(set(actual))
    missing, extra = sorted(set(expected) - set(actual)), sorted(set(actual) - set(expected))
    assert (missing, extra) == ([], []), f"사라진 operationId={missing}, 새 operationId={extra}"
