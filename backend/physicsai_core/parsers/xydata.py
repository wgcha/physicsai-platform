"""커브 파일(.xy/.xydata) 파서(§8.9 CURVE_PICK).

원본 parse_xydata(4_OPTIMIZATION/FUNC/1_physicsai_opti.py:174-218) 규칙: 숫자가 아닌 줄은 헤더(요청 이름),
숫자 줄의 열 수로 Column 2..N. 여기에 숫자 열 추출을 더한다.
"""

from __future__ import annotations

import re
from typing import Any

_NUM_RE = re.compile(r"^[\s,;]*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")
_SPLIT = re.compile(r"[,\s;]+")
MAX_POINTS = 20000


def _clean_header(h: str) -> str:
    return re.sub(r"^(#|//|XYDATA\s*[,:]?|TITLE\s*[,:=]?)\s*", "", h, flags=re.I).strip(" ,;\"'")


def parse_xydata(path: str, display_name: str | None = None) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    note = ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            t = line.strip()
            if not t:
                continue
            if _NUM_RE.match(t):
                vals = []
                for tok in _SPLIT.split(t):
                    if not tok:
                        continue
                    try:
                        vals.append(float(tok))
                    except ValueError:
                        vals = []
                        break
                if len(vals) < 2:
                    continue
                if cur is None:
                    cur = {"name": None, "rows": []}
                    blocks.append(cur)
                if len(cur["rows"]) < MAX_POINTS:
                    cur["rows"].append(vals)
            else:
                cur = {"name": _clean_header(t) or None, "rows": []}
                blocks.append(cur)
            if i > 2_000_000:
                break
    series: list[dict[str, Any]] = []
    unnamed = 0
    for b in blocks:
        rows = b["rows"]
        if not rows:
            continue
        ncol = min(len(r) for r in rows)
        name = b["name"]
        if not name:
            unnamed += 1
            name = "Impact_force" if unnamed == 1 else f"Series {unnamed}"
            note = "헤더에서 요청 이름을 찾지 못해 기본 이름을 썼습니다."
        x = [r[0] for r in rows]
        for c in range(1, ncol):
            series.append({"name": name if ncol == 2 else f"{name} Column {c + 1}", "x": x, "y": [r[c] for r in rows]})
    return {"file": display_name or path, "series": series, "note": note}
