"""다중 baseline 매칭표 결정·확정(R-B 300줄 분할 — `baselines`에서 재노출): 행 결정·검증·확정·상속·baseline 제거·공통 변수."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .baselines_base import ACTIONS, NA_SUFFIX, NAME_RE, ONEHOT_PREFIX, RESERVED, MapError, Var, baseline_ids


# ------------------------------------------------------------------ 결정·확정
def _rows(pm: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [r for r in pm.get("common") or [] if isinstance(r, dict)]


def unresolved(pm: Mapping[str, Any]) -> list[str]:
    """명시 결정이 필요한데 없는 행(§15 Q17): needs_review 또는 등급 check(확인 필요)."""
    out = []
    for r in _rows(pm):
        if r.get("decision") is None and (r.get("needs_review") or (r.get("proposed") or {}).get("grade") == "check"):
            out.append(str(r.get("row_id")))
    return out


def undecided_count(pm: Mapping[str, Any]) -> int:
    return sum(1 for r in _rows(pm) if r.get("decision") is None)


def accept_decision(row: Mapping[str, Any]) -> dict[str, Any]:
    pr = row.get("proposed") or {}
    return {"action": "accept", "name": pr.get("name"), "map": dict(pr.get("map") or {})}


def _decision_parts(row: Mapping[str, Any], d: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if d.get("action") == "split":
        return [(str(p.get("name")), dict(p.get("map") or {})) for p in d.get("parts") or [] if isinstance(p, dict)]
    return [(str(d.get("name")), dict(d.get("map") or {}))]


def normalize_decision(row: Mapping[str, Any], d: Mapping[str, Any] | None, bids: Sequence[str]) -> dict[str, Any] | None:
    """사용자 결정 정규화: accept는 제안 그대로 채움, map 키는 모든 baseline(빠지면 null)."""
    if d is None:
        return None
    act = d.get("action")
    if act == "accept":
        return accept_decision(row)
    if act == "split":
        parts = [{"name": p.get("name"), "map": {b: (p.get("map") or {}).get(b) for b in bids}}
                 for p in d.get("parts") or [] if isinstance(p, dict)]
        return {"action": "split", "name": parts[0]["name"] if parts else None, "map": {b: None for b in bids}, "parts": parts}
    return {"action": act, "name": d.get("name"), "map": {b: (d.get("map") or {}).get(b) for b in bids}}


def decision_problems(pm: Mapping[str, Any], known: Mapping[str, set[str]] | None = None) -> list[dict[str, Any]]:
    """결정 검사(§4.10): 이름 규칙·예약어·충돌(같은 이름이 다른 타입·단위, 이름 중복), 한 baseline 안 원 파라미터 중복,
    알 수 없는 원 이름(known 있을 때), action 값. 문제는 code = PARAM_NAME_CONFLICT | GEOM_INPUT_INVALID."""
    bids = baseline_ids(pm)
    probs: list[dict[str, Any]] = []
    seen: dict[str, tuple[str, str, str]] = {}  # 이름 → (row_id, type, unit)
    used: dict[tuple[str, str], str] = {}  # (baseline, 원 이름) → 공통 이름
    for r in _rows(pm):
        d = r.get("decision")
        if d is None:
            continue
        rid = str(r.get("row_id"))
        if not isinstance(d, dict) or d.get("action") not in ACTIONS:
            probs.append({"code": "GEOM_INPUT_INVALID", "row_id": rid, "message": f"{rid}: action은 {' | '.join(ACTIONS)}"})
            continue
        parts = _decision_parts(r, d)
        if not parts:
            probs.append({"code": "GEOM_INPUT_INVALID", "row_id": rid, "message": f"{rid}: 분리(split)에는 parts가 필요합니다"})
        for name, mp in parts:
            if not NAME_RE.match(name) or name in RESERVED or name.endswith(NA_SUFFIX) or name.startswith(ONEHOT_PREFIX):
                probs.append({"code": "PARAM_NAME_CONFLICT", "row_id": rid,
                              "message": f"{rid}: 공통 이름 '{name}'은 규칙에 맞지 않거나 예약어입니다(baseline·…__na·baseline__…)"})
                continue
            typ, unit = str(r.get("type") or ""), str(r.get("unit") or "")
            if name in seen:
                o = seen[name]
                why = "타입·단위가 다른 행" if (o[1], o[2]) != (typ, unit) else "다른 행"
                probs.append({"code": "PARAM_NAME_CONFLICT", "row_id": rid, "message": f"{rid}: 공통 이름 '{name}'이 {why}({o[0]})과 겹칩니다"})
                continue
            seen[name] = (rid, typ, unit)
            unknown_b = [b for b in mp if b not in bids]
            if unknown_b:
                probs.append({"code": "GEOM_INPUT_INVALID", "row_id": rid, "message": f"{rid}: 알 수 없는 baseline {', '.join(unknown_b)}"})
            if not any(mp.get(b) for b in bids):
                probs.append({"code": "GEOM_INPUT_INVALID", "row_id": rid, "message": f"{rid}: '{name}'이 모든 baseline에서 N/A입니다"})
            for b in bids:
                orig = mp.get(b)
                if orig is None:
                    continue
                if known is not None and orig not in known.get(b, set()):
                    probs.append({"code": "GEOM_INPUT_INVALID", "row_id": rid, "message": f"{rid}: baseline {b}에 원 파라미터 {orig}이(가) 없습니다"})
                k = (b, str(orig))
                if k in used and used[k] != name:
                    probs.append({"code": "PARAM_NAME_CONFLICT", "row_id": rid,
                                  "message": f"{rid}: baseline {b}의 {orig}을(를) 서로 다른 공통 이름({used[k]}, {name})이 가리킵니다"})
                used[k] = name
    return probs


def put_decisions(pm: Mapping[str, Any], items: Sequence[Mapping[str, Any]], known: Mapping[str, set[str]] | None = None
                  ) -> dict[str, Any]:
    """PUT param-map: 행별 decision만 저장(proposed·signature 불변). 결과는 항상 draft(확정 상태였다면 되돌림)."""
    out = copy.deepcopy(dict(pm))
    bids = baseline_ids(out)
    rows = {str(r.get("row_id")): r for r in _rows(out)}
    probs = []
    for it in items:
        rid = str(it.get("row_id"))
        if rid not in rows:
            probs.append({"code": "GEOM_INPUT_INVALID", "row_id": rid, "message": f"{rid}: 매칭표에 없는 행입니다"})
            continue
        d = it.get("decision")
        if d is not None and (not isinstance(d, dict) or d.get("action") not in ACTIONS):
            probs.append({"code": "GEOM_INPUT_INVALID", "row_id": rid, "message": f"{rid}: action은 {' | '.join(ACTIONS)}"})
            continue
        rows[rid]["decision"] = normalize_decision(rows[rid], d, bids)
        if d is not None:
            rows[rid]["needs_review"] = False
    if probs:
        raise MapError("GEOM_INPUT_INVALID", "결정을 저장할 수 없습니다", probs)
    probs = decision_problems(out, known)
    if probs:
        code = "PARAM_NAME_CONFLICT" if any(p["code"] == "PARAM_NAME_CONFLICT" for p in probs) else "GEOM_INPUT_INVALID"
        raise MapError(code, "공통 변수 이름이 충돌합니다" if code == "PARAM_NAME_CONFLICT" else "결정이 올바르지 않습니다", probs)
    out["status"], out["confirmed_by"], out["confirmed_at"] = "draft", None, None
    return out


def confirm(pm: Mapping[str, Any], user: str, now: str, known: Mapping[str, set[str]] | None = None) -> dict[str, Any]:
    """확정(§7.3.8): check 등급·needs_review 행에 결정이 없으면 GEOM_INPUT_INVALID(행 목록), 나머지 미결정 행은 accept로 기록."""
    left = unresolved(pm)
    if left:
        raise MapError("GEOM_INPUT_INVALID", f"확인 필요·재확인 행 {len(left)}개에 결정이 없습니다",
                       [{"code": "GEOM_INPUT_INVALID", "row_id": r, "message": f"{r}: 명시 결정이 필요합니다"} for r in left])
    out = copy.deepcopy(dict(pm))
    for r in _rows(out):
        if r.get("decision") is None:
            r["decision"] = accept_decision(r)
    probs = decision_problems(out, known)
    if probs:
        code = "PARAM_NAME_CONFLICT" if any(p["code"] == "PARAM_NAME_CONFLICT" for p in probs) else "GEOM_INPUT_INVALID"
        raise MapError(code, "확정할 수 없습니다: 결정 검사 실패", probs)
    out["status"], out["confirmed_by"], out["confirmed_at"] = "confirmed", user, now
    return out


def to_draft(pm: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(pm))
    out["status"], out["confirmed_by"], out["confirmed_at"] = "draft", None, None
    return out


def inherit(new: Mapping[str, Any], old: Mapping[str, Any] | None) -> dict[str, Any]:
    """승계 규칙(§4.10): 새 초안에서 signature가 같은 이전 행의 decision을 승계, 나머지는 decision null·needs_review true.
    paicad `--user-map`도 같은 규칙이지만 플랫폼이 다시 적용해 상태(draft)·키를 보장한다."""
    out = to_draft(new)
    if old is None:
        return out
    prev = {r.get("signature"): r for r in _rows(old) if isinstance(r.get("signature"), str)}
    bids = baseline_ids(out)
    for r in _rows(out):
        o = prev.get(r.get("signature"))
        if o is None:  # 서명이 바뀌었거나 새로 생긴 행
            r["decision"], r["needs_review"] = None, True
        elif o.get("decision") is not None:
            r["decision"], r["needs_review"] = normalize_decision(r, o["decision"], bids), False
        else:  # 서명 같고 이전에도 미결정 — 재확인 표시는 이전 그대로
            r["decision"], r["needs_review"] = None, bool(o.get("needs_review"))
    return out


def drop_baseline(pm: Mapping[str, Any], bid: str) -> dict[str, Any]:
    """baseline 삭제 뒤 매칭표(draft): baselines·discrete·range_split·행 map에서 그 id를 빼고, 다른 baseline에 남는 것이 없는 행은 지운다."""
    out = to_draft(pm)
    out["baselines"] = [b for b in out.get("baselines") or [] if b.get("id") != bid]
    if isinstance(out.get("discrete"), dict):
        out["discrete"]["values"] = [v for v in out["discrete"].get("values") or [] if v != bid]
    if isinstance(out.get("range_split"), dict):
        out["range_split"]["intervals"] = [iv for iv in out["range_split"].get("intervals") or [] if iv.get("baseline") != bid]
    rows = []
    for r in _rows(out):
        for blk in ("proposed", "decision"):
            d = r.get(blk)
            if isinstance(d, dict):
                for k in ("map", "nominal"):
                    if isinstance(d.get(k), dict):
                        d[k].pop(bid, None)
                for part in d.get("parts") or []:
                    if isinstance(part, dict) and isinstance(part.get("map"), dict):
                        part["map"].pop(bid, None)
        pm_ = (r.get("proposed") or {}).get("map") or {}
        if any(v is not None for v in pm_.values()):
            rows.append(r)
    out["common"] = rows
    return out


def variables(pm: Mapping[str, Any]) -> list[Var]:
    """확정 결정의 공통 변수(행 순서, split은 부분 순서). 결정 없는 행은 건너뛴다(확정 상태에서는 없음)."""
    out: list[Var] = []
    for r in _rows(pm):
        d = r.get("decision")
        if not isinstance(d, dict):
            continue
        nom = (r.get("proposed") or {}).get("nominal") or {}
        for name, mp in _decision_parts(r, d):
            out.append(Var(name, str(r.get("type") or ""), str(r.get("unit") or "mm"), {k: (v if v else None) for k, v in mp.items()},
                           str(r.get("row_id")), {k: v for k, v in nom.items()}))
    return out


def display_names(pm: Mapping[str, Any]) -> list[str]:
    """draft 동안 표시용 이름(proposed), 확정이면 decision 이름."""
    if pm.get("status") == "confirmed":
        return [v.name for v in variables(pm)]
    return [str((r.get("proposed") or {}).get("name")) for r in _rows(pm)]
