"""도메인 용어집·스키마 사전(mcp.md §10). 자동 추출(손 유지보수 없음) + 사람이 쓰는 `glossary_terms.yaml` 병합.

자동 추출: entities(SUMMARIES + 관계), job_types(JOB_TYPES), job_kinds(JOB_KINDS), stages(화면 번호 ↔ 내부 stage_label),
feature_abbr(paicad `features.py`·`shell/common.py`의 TYPE_ABBR를 **AST로** 읽음 — 플랫폼은 paicad를 import하지 않는다),
enums(openapi 스키마 enum), error_codes(backend·worker 소스 AST의 DomainError·_err·StepFailure 문자열 리터럴).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import yaml

PKG_DIR = Path(__file__).resolve().parent
GENERATED_DIR = PKG_DIR / "generated"
TERMS_FILE = PKG_DIR / "glossary_terms.yaml"
REPO = PKG_DIR.parents[2]
PAICAD_ABBR_FILES = ("packages/paicad/src/paicad/features.py", "packages/paicad/src/paicad/shell/common.py")
ERROR_SCAN_DIRS = ("backend/physicsai_core", "backend/physicsai_api", "backend/physicsai_mcp", "worker/physicsai_worker")
ERROR_CALLS = ("DomainError", "StepFailure", "RateLimited", "McpToolError")  # 첫 인자 = 코드 리터럴
SECTIONS = ("entities", "job_types", "job_kinds", "stages", "feature_abbr", "enums", "error_codes", "terms", "error_hints")
MAX_BYTES = 65536


# ---- 자동 추출 --------------------------------------------------------------------------------------


def feature_abbr(repo: Path = REPO) -> dict[str, dict[str, str]]:
    """paicad TYPE_ABBR(AST): 약어 → {type, source}. 소스 파일 순·약어 순(결정적)."""
    out: dict[str, dict[str, str]] = {}
    for rel in PAICAD_ABBR_FILES:
        path = repo / rel
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TYPE_ABBR" for t in node.targets):
                d = ast.literal_eval(node.value)
                for typ, ab in d.items():
                    out.setdefault(str(ab), {"type": str(typ), "source": rel})
    return dict(sorted(out.items()))


def _lit(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{…}" for v in node.values)  # type: ignore[union-attr]
    return None


def _status_kw(call: ast.Call) -> int | None:
    for kw in call.keywords:
        if kw.arg == "status" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
            return int(kw.value.value)
    return None


def error_codes(repo: Path = REPO) -> dict[str, dict[str, Any]]:
    """`DomainError("CODE", "메시지", status=…)`·`_err(status, "CODE", "메시지")`·`_error(status|None, "CODE", "메시지")`·`StepFailure("CODE", "메시지")` 리터럴 → 코드표."""
    out: dict[str, dict[str, Any]] = {}
    files: list[Path] = []
    for d in ERROR_SCAN_DIRS:
        if (repo / d).is_dir():
            files += sorted((repo / d).rglob("*.py"))
    for f in sorted(files, key=lambda p: p.relative_to(repo).as_posix()):
        rel = f.relative_to(repo).as_posix()
        if "/generated/" in rel:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ""
            code = msg = None
            status: int | None = None
            if fn in ERROR_CALLS and n.args:
                code = _lit(n.args[0])
                msg = _lit(n.args[1]) if len(n.args) > 1 else None
                status = _status_kw(n) if fn != "RateLimited" else 429
                if fn == "DomainError" and status is None and len(n.args) > 2 and isinstance(n.args[2], ast.Constant):
                    status = n.args[2].value if isinstance(n.args[2].value, int) else None
            elif (fn in ("_err", "_error") and len(n.args) >= 2 and isinstance(n.args[0], ast.Constant)
                  and (isinstance(n.args[0].value, int) or n.args[0].value is None)):  # `_error(None, "CODE", …)`: MCP 계층의 로컬 오류(상태 없음)
                status = int(n.args[0].value) if n.args[0].value is not None else None
                code = _lit(n.args[1])
                msg = _lit(n.args[2]) if len(n.args) > 2 else None
            if not code or not code.replace("_", "").isalnum() or not code.isupper():
                continue
            e = out.setdefault(code, {"code": code, "status": status, "message_ko": msg, "sources": []})
            if e["status"] is None and status is not None:
                e["status"] = status
            if e["message_ko"] is None and msg:
                e["message_ko"] = msg
            if rel not in e["sources"]:
                e["sources"].append(rel)
    return dict(sorted(out.items()))


def enums(openapi: dict[str, Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for name, sch in sorted((openapi.get("components") or {}).get("schemas", {}).items()):
        for prop, ps in sorted((sch.get("properties") or {}).items()):
            cands = [ps, *(ps.get("anyOf") or [])]
            for c in cands:
                if isinstance(c, dict) and isinstance(c.get("enum"), list):
                    out[f"{name}.{prop}"] = list(c["enum"])
                    break
    return out


def extract(openapi: dict[str, Any], repo: Path = REPO) -> dict[str, Any]:
    from physicsai_core.job_types import JOB_TYPES

    from .job_kinds import JOB_KINDS, KIND_OF_JOB_TYPE
    from .summaries import RELATIONS, SUMMARIES

    stages: list[dict[str, Any]] = []
    for jt, d in sorted(JOB_TYPES.items()):
        k = KIND_OF_JOB_TYPE.get(jt)
        stages.append({"job_type": jt, "internal": d.stage_label, "screen": JOB_KINDS[k].stage if k else d.stage_label})
    return {
        "schema_version": 1,
        "entities": {"items": {e: {"label_ko": s.label_ko, "id_label": s.id_label} for e, s in sorted(SUMMARIES.items())},
                     "relations": RELATIONS},
        "job_types": {jt: {"label": d.label, "lane": d.lane, "stage_label": d.stage_label} for jt, d in sorted(JOB_TYPES.items())},
        "job_kinds": {k.kind: {"label_ko": k.label_ko, "stage": k.stage, "cost": k.cost, "job_types": list(k.job_types),
                               "version": k.version, "summary_entity": k.summary_entity} for k in sorted(JOB_KINDS.values(), key=lambda x: x.kind)},
        "stages": stages,
        "feature_abbr": feature_abbr(repo),
        "enums": enums(openapi),
        "error_codes": error_codes(repo),
    }


def auto_keys(gen: dict[str, Any]) -> set[str]:
    keys = {f"entity:{e}" for e in gen["entities"]["items"]}
    keys |= {f"job_type:{j}" for j in gen["job_types"]}
    keys |= {f"job_kind:{k}" for k in gen["job_kinds"]}
    keys |= {f"feature:{a}" for a in gen["feature_abbr"]}
    keys |= {f"error:{c}" for c in gen["error_codes"]}
    keys |= {f"enum:{e}" for e in gen["enums"]}
    keys |= {f"stage:{s['internal']}" for s in gen["stages"]} | {f"stage:{s['screen']}" for s in gen["stages"]}
    keys |= {f"stage:{k['stage']}" for k in gen["job_kinds"].values()}
    return keys


def required_ko_keys(gen: dict[str, Any]) -> set[str]:
    """사람 파일에 `ko`가 반드시 있어야 하는 키(V-MCP-10): 피처 약어·작업 종류·엔티티 전부."""
    return ({f"feature:{a}" for a in gen["feature_abbr"]} | {f"job_kind:{k}" for k in gen["job_kinds"]}
            | {f"entity:{e}" for e in gen["entities"]["items"]})


def terms() -> dict[str, Any]:
    return yaml.safe_load(TERMS_FILE.read_text(encoding="utf-8")) or {}


def check_terms(gen: dict[str, Any], human: dict[str, Any]) -> list[str]:
    """사람 파일 검사 → 문제 목록(비면 통과). 생성기·정적 시험 공용."""
    probs: list[str] = []
    keys = auto_keys(gen)
    have_ko: set[str] = set()
    for t in human.get("terms") or []:
        k = str(t.get("key") or "")
        if not k.startswith("unmapped:") and k not in keys:
            probs.append(f"glossary_terms.yaml: 자동 추출 키에 없는 key {k}")
        if t.get("ko"):
            have_ko.add(k)
    for k in sorted(required_ko_keys(gen) - have_ko):
        probs.append(f"glossary_terms.yaml: {k}의 ko가 없습니다 — 한 줄 추가하세요")
    for code in sorted(human.get("error_hints") or {}):
        if code not in gen["error_codes"]:
            probs.append(f"glossary_terms.yaml: error_hints {code}가 오류 코드에 없습니다")
    return probs


# ---- 서빙(병합) --------------------------------------------------------------------------------------


def load_generated() -> dict[str, Any]:
    return json.loads((GENERATED_DIR / "glossary.json").read_text(encoding="utf-8"))


def merged(section: str | None = None) -> dict[str, Any]:
    gen = load_generated()
    human = terms()
    full = {**{k: gen[k] for k in SECTIONS if k in gen}, "terms": human.get("terms") or [],
            "error_hints": human.get("error_hints") or {}}
    if section:
        return {"schema_version": 1, section: full.get(section), "truncated": False}
    out = {"schema_version": 1, **full, "truncated": False}
    if len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:  # 64 KiB 상한 — 큰 절은 section으로 따로
        out = {"schema_version": 1, **{k: v for k, v in full.items() if k not in ("error_codes", "enums")},
               "truncated": True, "omitted_sections": ["error_codes", "enums"]}
    return out
