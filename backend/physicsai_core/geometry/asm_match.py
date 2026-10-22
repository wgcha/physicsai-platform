"""조립 매칭 묶음(asm-match.md §4.1·§4.4) — 경로 규칙·`match.json` 입출력·행 검증·`rows_sha256`·확정본 작성.

저장 = `<study>/asm_match/<match_id>/`(DB 변경 없음, AM-12). 파일 쓰기 주체를 나눠 경쟁을 없앤다:
- `match.json`·`check/<seq>/match_rows.json`·`asm_match.json` = API만(생성·행 저장·검사 요청·확정).
- `parts/`·`check/<seq>/{asm_check.json,match_fe.glb,worst_*.npz}` = 워커(`paicad asm parts|check`)만.
검사 결과(`last_check`)는 `check/<seq>/`에서 읽어 계산한다(워커가 match.json을 건드리지 않음 — 계약 §4.1 `last_check`의 구현 방식, AM-C2).

`--match` 파일의 바이트가 곧 `rows_sha256`의 기준(paicad `asm check`는 그 파일 바이트의 sha256을 보고에 적는다): 플랫폼은 행을
정규 JSON(`canonical_rows`)으로 한 번 써서 그 바이트로 sha256을 구한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any

from ..fileutil import write_json_atomic

MATCH_ROOT = "asm_match"
CACHE_REL = "_cache/asm_parse"  # paicad --cache-dir(지워도 재생성, AM-11)
MATCH_JSON = "match.json"
PARTS_DIR = "parts"
PARTS_JSON = "asm_parts.json"
CHECK_DIR = "check"
CHECK_JSON = "asm_check.json"
CHECK_GLB = "match_fe.glb"
ROWS_JSON = "match_rows.json"  # `--match` 입력(검사 요청 때 API가 씀, 그 바이트 sha256 = rows_sha256)
CONFIRMED_JSON = "asm_match.json"
ASM_MATCH_REL = "cad/asm_match.json"  # 소비자(세트 S·DOE D) 안의 확정본 사본 위치(prep.json `inputs.asm_match.rel`)
ASM_WRITE_JSON = "asm_write.json"  # `paicad asm write` 보고(--out-dir 직계, AM-C2)
SCHEMA_VERSION = 1
UNIT_SYSTEM = "mm-ton-s"
KIND_TRAIN, KIND_PATH = "train", "path"
# 행 검증 사유 코드(PUT rows 422 ASM_ROW_INVALID problems[].code)
R_EMPTY, R_BODY, R_BODY_DUP, R_PID, R_PID_DUP, R_SOLID, R_MISSING, R_USE = (
    "ROWS_EMPTY", "UNKNOWN_BODY", "BODY_DUPLICATE", "UNKNOWN_PID", "PID_DUPLICATE", "NOT_SOLID", "BODY_MISSING", "USE_PARAM")


def new_match_id() -> str:
    return str(uuid.uuid4())


def match_dir(study_root: str, match_id: str) -> str:
    return os.path.join(study_root, MATCH_ROOT, match_id)


def cache_dir(study_root: str) -> str:
    return os.path.join(study_root, *CACHE_REL.split("/"))


def check_dir(mdir: str, seq: int) -> str:
    return os.path.join(mdir, CHECK_DIR, str(int(seq)))


def read_json(path: str, max_bytes: int = 64 * 1024 * 1024) -> dict[str, Any] | None:
    """JSON 객체(없음·깨짐·크기 초과 = None)."""
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def write_match(mdir: str, doc: dict[str, Any]) -> None:
    os.makedirs(mdir, exist_ok=True)
    write_json_atomic(os.path.join(mdir, MATCH_JSON), doc)


def read_match(mdir: str) -> dict[str, Any] | None:
    return read_json(os.path.join(mdir, MATCH_JSON))


def check_seqs(mdir: str) -> list[int]:
    """`check/<seq>/` 폴더 번호(오름차순)."""
    base = os.path.join(mdir, CHECK_DIR)
    try:
        return sorted(int(n) for n in os.listdir(base) if n.isdigit() and os.path.isdir(os.path.join(base, n)))
    except OSError:
        return []


def next_seq(mdir: str) -> int:
    s = check_seqs(mdir)
    return (s[-1] + 1) if s else 1


# ---- 행 ------------------------------------------------------------------------------------------------------


def canonical_rows(rows: list[dict[str, Any]], excluded: list[str]) -> bytes:
    """`--match` 파일 바이트(`{rows:[{body,pids}], excluded_bodies}`) — 같은 행이면 같은 바이트(정렬·구분자 고정)."""
    doc = {"rows": [{"body": r["body"], "pids": [int(p) for p in r["pids"]]} for r in rows], "excluded_bodies": list(excluded)}
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def rows_sha256(rows: list[dict[str, Any]], excluded: list[str]) -> str:
    return hashlib.sha256(canonical_rows(rows, excluded)).hexdigest()


def problem(code: str, message: str, body: str | None = None, pid: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "message": message}
    if body is not None:
        out["body"] = body
    if pid is not None:
        out["pid"] = pid
    return out


def validate_rows(rows_in: list[Any], excluded_in: list[str], bodies: list[str], parts: list[dict[str, Any]],
                  use_bodies: set[str] | None = None) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """행 저장 검증(§6.3 PUT rows) → (정규화 행, 정규화 제외, problems). problems가 있으면 앞 둘은 쓰지 않는다.

    규칙(AM-4): 바디는 한 행에만(또는 제외), component(pid)는 한 행에만, 바디 1 ↔ pid ≥1, pid는 목록에 있고 `solid_ok`(TETRA4만),
    모든 바디가 행 또는 제외에 있어야 하고(누락 = BODY_MISSING), 매칭 행은 ≥1. 제외 바디에 `use=true` 파라미터가 있으면 USE_PARAM.
    정규화 = 행은 `bodies` 순서(= 파라미터 순서), pid 오름차순."""
    by_pid = {int(p["pid"]): p for p in parts}
    known = set(bodies)
    probs: list[dict[str, Any]] = []
    seen_body: set[str] = set()
    owner: dict[int, str] = {}
    norm: dict[str, list[int]] = {}
    for r in rows_in:
        b = r["body"] if isinstance(r, dict) else getattr(r, "body", None)
        pids = r["pids"] if isinstance(r, dict) else getattr(r, "pids", None)
        if b not in known:
            probs.append(problem(R_BODY, f"STEP에 없는 바디입니다: {b}", b))
            continue
        if b in seen_body:
            probs.append(problem(R_BODY_DUP, f"바디 {b}이(가) 두 행에 있습니다", b))
            continue
        seen_body.add(b)
        ok: list[int] = []
        for p in pids or []:
            pid = int(p)
            part = by_pid.get(pid)
            if part is None:
                probs.append(problem(R_PID, f"조립에 없는 PART입니다: {pid}", b, pid))
            elif not part.get("solid_ok"):
                probs.append(problem(R_SOLID, f"PART {pid}은(는) TETRA4만 가진 component가 아닙니다", b, pid))
            elif pid in owner:
                probs.append(problem(R_PID_DUP, f"PART {pid}은(는) {owner[pid]} 행에서 이미 사용합니다", b, pid))
            else:
                owner[pid] = b
                ok.append(pid)
        if not (pids or []):
            probs.append(problem(R_PID, f"바디 {b}에 component가 없습니다(매칭 안 함은 excluded_bodies로)", b))
        norm[b] = sorted(set(ok))
    ex: list[str] = []
    for b in excluded_in:
        if b not in known:
            probs.append(problem(R_BODY, f"STEP에 없는 바디입니다: {b}", b))
        elif b in seen_body or b in ex:
            probs.append(problem(R_BODY_DUP, f"바디 {b}이(가) 행과 제외에 함께 있거나 두 번 있습니다", b))
        elif use_bodies and b in use_bodies:
            probs.append(problem(R_USE, f"선택한 파라미터가 이 바디({b})에 있어 매칭 안 함으로 둘 수 없습니다", b))
        else:
            ex.append(b)
    for b in bodies:
        if b not in seen_body and b not in ex and not any(q.get("body") == b for q in probs):
            probs.append(problem(R_MISSING, f"바디 {b}의 매칭이 없습니다(component를 고르거나 매칭 안 함)", b))
    if not norm and not probs:
        probs.append(problem(R_EMPTY, "매칭한 바디가 1개 이상이어야 합니다"))
    out_rows = [{"body": b, "pids": norm[b]} for b in bodies if b in norm]
    return out_rows, [b for b in bodies if b in set(ex)], probs


def titles_of(pids: list[int], parts: list[dict[str, Any]]) -> list[str]:
    t = {int(p["pid"]): str(p.get("title") or "") for p in parts}
    return [t.get(int(p), "") for p in pids]


def rows_complete(rows: list[dict[str, Any]], excluded: list[str], bodies: list[str]) -> bool:
    """검사 요청 가능 = 모든 바디가 선택 또는 매칭 안 함이고 매칭 행 ≥ 1(§3.2 단추 상태)."""
    covered = {r["body"] for r in rows} | set(excluded)
    return bool(rows) and bool(bodies) and covered >= set(bodies)


# ---- 확정본 --------------------------------------------------------------------------------------------------


def confirmed_document(match: dict[str, Any], parts: list[dict[str, Any]], check_doc: dict[str, Any], check_seq: int, check_sha: str,
                       *, engine_version: str | None, user: str, now_iso: str) -> dict[str, Any]:
    """§4.4 확정본. 행 순서 = bodies 순서, titles = 조립 PART 제목, check = 검사 요약(match_ratio_min·dist_max_mm)."""
    rows = [{"body": r["body"], "pids": [int(p) for p in r["pids"]], "titles": titles_of(r["pids"], parts)} for r in match["rows"]]
    ratios = [float(r["match_ratio"]) for r in check_doc.get("rows") or [] if isinstance(r.get("match_ratio"), (int, float))]
    dmax = [float(((r.get("dist_mm") or {}).get("max"))) for r in check_doc.get("rows") or []
            if isinstance((r.get("dist_mm") or {}).get("max"), (int, float))]
    assem = match.get("assem") or {}
    src = match.get("source") or {}
    nodes = [str(n.get("rel")) for n in ((check_doc.get("assem") or {}).get("node_files") or []) if isinstance(n, dict) and n.get("rel")]
    return {"schema_version": SCHEMA_VERSION, "engine": "native", "engine_version": engine_version, "match_id": match["match_id"],
            "cad": {"rel": src.get("cad_name"), "sha256": src.get("cad_sha256")},
            "features_sha256": src.get("features_sha256"), "unit_system": UNIT_SYSTEM,
            "assem": {"digest": assem.get("digest"), "starter": assem.get("starter"), "node_files": nodes},
            "rows": rows, "excluded_bodies": list(match.get("excluded_bodies") or []),
            "check": {"seq": int(check_seq), "sha256": check_sha, "rows_sha256": check_doc.get("rows_sha256"),
                      "match_ratio_min": min(ratios) if ratios else None, "dist_max_mm": max(dmax) if dmax else None},
            "confirmed_by": user, "confirmed_at": now_iso}


def check_summary(check_doc: dict[str, Any]) -> dict[str, Any]:
    """`jobs.result` 요약(상태·개수·match_ratio_min·dist_max_mm·shared_nodes만, §6.3)."""
    rows = [r for r in check_doc.get("rows") or [] if isinstance(r, dict)]
    ratios = [float(r["match_ratio"]) for r in rows if isinstance(r.get("match_ratio"), (int, float))]
    dmax = [float((r.get("dist_mm") or {}).get("max")) for r in rows if isinstance((r.get("dist_mm") or {}).get("max"), (int, float))]
    shared = sum(int((r.get("shared") or {}).get("nodes") or 0) for r in rows)
    return {"status": check_doc.get("status"), "rows": len(rows), "match_ratio_min": min(ratios) if ratios else None,
            "dist_max_mm": max(dmax) if dmax else None, "shared_nodes": shared}


def parts_summary(parts_doc: dict[str, Any]) -> dict[str, Any]:
    tree = ((parts_doc.get("assem") or {}).get("tree")) or []
    parts = parts_doc.get("parts") or []
    return {"files": len(tree), "parts": len(parts), "solid_parts": sum(1 for p in parts if p.get("solid_ok")),
            "bodies": len(parts_doc.get("bodies") or [])}


def matched_doc(S: str) -> dict[str, Any] | None:
    """세트 S·DOE D의 확정본 사본(`cad/asm_match.json`) — 있으면 매칭 세트(방식 M), 없으면 None(방식 L)."""
    return read_json(os.path.join(S, *ASM_MATCH_REL.split("/")))


def is_matched(S: str) -> bool:
    return os.path.isfile(os.path.join(S, *ASM_MATCH_REL.split("/")))
