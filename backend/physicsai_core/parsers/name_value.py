"""name,value 두 열 CSV 읽기(④ 예측·검증, ① 응답 추출 공용). 값이 숫자가 아니면 None."""

from __future__ import annotations

import csv
import os


def read_name_value_csv(path: str) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("name") or "").strip()
            try:
                out[name] = float(row.get("value", ""))
            except (TypeError, ValueError):
                out[name] = None
    return out
