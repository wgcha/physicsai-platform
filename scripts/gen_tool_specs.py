"""도구 스펙 생성기(mcp.md §9): `python scripts/gen_tool_specs.py [--check] [--out DIR] [--allow-breaking]`.

출력(패키지 안 — API `/mcp/tools`·`/mcp/glossary`가 서빙): backend/physicsai_api/mcp/generated/
  tools.mcp.json · tools.openai.json · glossary.json · job_kinds.json
--check: 디스크 파일이 생성 결과와 다르면 실패(test-all), 직전 커밋(git HEAD)과 비교해 깨지는 변경이면 실패.
함께 검사: x-mcp 누락(새 operation), 용어집 사람 파일(glossary_terms.yaml) 키·ko 누락, 이식 가능 스키마 규칙(§9.2 — 생성 실패로 알림).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REL_DIR = "backend/physicsai_api/mcp/generated"
sys.path[:0] = [str(REPO / "backend"), str(REPO / "worker")]


def _git_head(rel: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{rel}"], capture_output=True, text=True, timeout=30,
                           shell=False, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _static_problems() -> list[str]:
    from physicsai_api.export_openapi import build_openapi
    from physicsai_api.mcp import glossary as g
    from physicsai_api.mcp.route_policy import LEGACY_UNMARKED

    spec = build_openapi()
    probs = []
    ids = set()
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if not isinstance(op, dict):
                continue
            oid = op.get("operationId")
            ids.add(oid)
            if "x-mcp" not in op and oid not in LEGACY_UNMARKED:
                probs.append(f"{method.upper()} {path}: x-mcp가 없습니다 — openapi_extra=M.xmcp_tool(...) 또는 M.xmcp_exclude('사유')")
    for oid in sorted(LEGACY_UNMARKED - ids):
        probs.append(f"route_policy.LEGACY_UNMARKED에 없는 operationId {oid} — 목록에서 지우세요")
    probs += g.check_terms(g.extract(spec), g.terms())
    return probs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=str(REPO / REL_DIR))
    ap.add_argument("--allow-breaking", action="store_true", help="깨지는 변경을 알고 쓴다(새 이름 원칙 예외 — 계약 변경 메모 필요)")
    a = ap.parse_args(argv)
    from physicsai_api.mcp import toolspec as ts
    from physicsai_api.mcp.portable import SpecError

    out = Path(a.out)
    probs = _static_problems()
    try:
        files = ts.generate()
    except SpecError as exc:  # §9.2: 이식 불가 스키마·설명 길이·이름 규칙 위반은 생성 실패
        print(f"도구 스펙 생성 실패: {exc}", file=sys.stderr)
        return 1
    disk = ts.read_disk(out)
    base_mcp = (_git_head(f"{REL_DIR}/tools.mcp.json") if a.check else None) or disk["tools.mcp.json"]
    base_kinds = (_git_head(f"{REL_DIR}/job_kinds.json") if a.check else None) or disk["job_kinds.json"]
    if base_mcp and not a.allow_breaking:
        probs += ts.compat_problems(json.loads(base_mcp), json.loads(files["tools.mcp.json"]),
                                    json.loads(base_kinds) if base_kinds else None, json.loads(files["job_kinds.json"]))
    if a.check:
        stale = [f for f in ts.FILES if disk.get(f) != files[f]]
        if stale:
            probs.append(f"생성 파일이 최신이 아닙니다({', '.join(stale)}): python scripts/gen_tool_specs.py")
    if probs:
        print("\n".join(probs), file=sys.stderr)
        return 1
    if not a.check:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
