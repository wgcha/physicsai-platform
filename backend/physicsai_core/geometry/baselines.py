"""단계 4B 다중 baseline(geometry-engine.md §4.10·§7.3.8·§11.4) — 순수 함수(파일 쓰기·DB는 호출자).

세트 S에 `S/param_map.json`이 있으면 다중 baseline 세트다(없으면 기존 단일 경로 — 분기 1곳, §16 8).
- baseline 목록 = param_map.json `baselines[{id, rel}]`. 첫 baseline(`base`)은 S 자신(rel ".", 복사·이동 없음),
  추가 baseline은 `S/baselines/<id>/{cad, radioss_assem, native/, baseline.json}`.
- 행마다 `proposed`(paicad 제안, 편집 불가)와 `decision`(사용자 결정, 플랫폼만 씀). 유효 대응은 항상 decision.map.
- 확정(`status: confirmed`) 전에는 DOE·일괄 생성 불가(409 PARAM_MAP_UNCONFIRMED, 단건 예측은 대상 아님).
- 공통 이름 → baseline 원 이름 변환·샘플 배정·층화 LHS·학습 입력 열(N/A 지시 열·원-핫)은 플랫폼이 한다(§18).
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

PARAM_MAP = "param_map.json"
BASELINES_DIR = "baselines"
BASELINE_JSON = "baseline.json"
SINGLE_PARAMS = "baselines/single_parameters.json"  # 다중으로 바꾸기 전 단일 파라미터 표(단일로 되돌릴 때 복원)
BASE_ID = "base"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RESERVED = ("baseline",)
NA_SUFFIX = "__na"
ONEHOT_PREFIX = "baseline__"
ACTIONS = ("accept", "rename", "change", "split")
USAGES = ("topology", "range")
NO_COVER = "BASELINE_NO_COVER"


class MapError(ValueError):
    """매칭표 검증 실패. code = PARAM_NAME_CONFLICT | GEOM_INPUT_INVALID | PARAM_MAP_UNCONFIRMED, problems = 행별 사유(한국어)."""

    def __init__(self, code: str, message: str, problems: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code, self.message, self.problems = code, message, problems or []


@dataclass
class Var:
    """확정 결정에서 나온 공통 변수 1개(split 행은 부분마다 1개)."""

    name: str
    type: str
    unit: str
    map: dict[str, str | None]
    row_id: str
    nominal: dict[str, float | None] = field(default_factory=dict)

    def active(self, bid: str) -> bool:
        return self.map.get(bid) is not None


# ------------------------------------------------------------------ 파일·목록
def map_path(S: str) -> str:
    return os.path.join(S, PARAM_MAP)


def is_multi(S: str) -> bool:
    return os.path.isfile(map_path(S))


def load(S: str, max_bytes: int) -> dict[str, Any] | None:
    """S/param_map.json(없으면 None). 형식이 틀리면 MapError(GEOM_INPUT_INVALID)."""
    p = map_path(S)
    if not os.path.isfile(p):
        return None
    return load_file(p, max_bytes)


def load_file(p: str, max_bytes: int) -> dict[str, Any]:
    """param_map.json 형식 파일(paicad map 출력 포함) 읽기·모양 검사."""
    if not os.path.isfile(p):
        raise MapError("GEOM_INPUT_INVALID", "param_map.json이 없습니다")
    if os.path.getsize(p) > max_bytes:
        raise MapError("GEOM_INPUT_INVALID", f"param_map.json이 읽기 상한({max_bytes} bytes)을 넘습니다")
    try:
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise MapError("GEOM_INPUT_INVALID", f"param_map.json 형식 오류: {exc.__class__.__name__}") from None
    probs = shape_problems(doc)
    if probs:
        raise MapError("GEOM_INPUT_INVALID", "param_map.json 형식 오류: " + "; ".join(p["message"] for p in probs[:3]), probs)
    return doc


def shape_problems(doc: Any) -> list[dict[str, Any]]:
    """param_map.json 필수 키·타입(§4.10). topology+range_split 혼합은 GEOM_INPUT_INVALID."""
    p: list[dict[str, Any]] = []
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        return [{"code": "GEOM_INPUT_INVALID", "message": "schema_version 1인 객체가 아닙니다"}]
    if doc.get("usage") not in USAGES:
        p.append({"code": "GEOM_INPUT_INVALID", "message": "usage는 topology | range"})
    bl = doc.get("baselines")
    if not isinstance(bl, list) or len(bl) < 2 or not all(isinstance(b, dict) and isinstance(b.get("id"), str) for b in bl):
        p.append({"code": "GEOM_INPUT_INVALID", "message": "baselines는 2개 이상의 {id, rel} 목록이어야 합니다"})
    if not isinstance(doc.get("common"), list):
        p.append({"code": "GEOM_INPUT_INVALID", "message": "common 행 목록이 없습니다"})
    if doc.get("status") not in ("draft", "confirmed"):
        p.append({"code": "GEOM_INPUT_INVALID", "message": "status는 draft | confirmed"})
    if doc.get("discrete") and doc.get("range_split"):
        p.append({"code": "GEOM_INPUT_INVALID", "message": "위상 변형(discrete)과 범위 분할(range_split)을 함께 쓸 수 없습니다"})
    if doc.get("usage") == "range" and doc.get("discrete"):
        p.append({"code": "GEOM_INPUT_INVALID", "message": "range 용도에는 discrete가 없어야 합니다"})
    if doc.get("usage") == "topology" and doc.get("range_split"):
        p.append({"code": "GEOM_INPUT_INVALID", "message": "topology 용도에는 range_split이 없어야 합니다"})
    return p


def baseline_ids(pm: Mapping[str, Any]) -> list[str]:
    return [str(b["id"]) for b in pm.get("baselines") or [] if isinstance(b, dict)]


def baseline_rel(pm: Mapping[str, Any], bid: str) -> str:
    for b in pm.get("baselines") or []:
        if isinstance(b, dict) and b.get("id") == bid:
            rel = b.get("rel")
            return rel if isinstance(rel, str) and rel else "."
    raise MapError("GEOM_INPUT_INVALID", f"baseline {bid}이(가) 매칭표에 없습니다")


def baseline_root(S: str, pm: Mapping[str, Any], bid: str) -> str:
    """baseline 준비본 루트(S 기준). base(rel ".")는 S 자신. 세트 밖을 가리키면 MapError."""
    rel = baseline_rel(pm, bid)
    if rel in (".", ""):
        return S
    parts = rel.replace("\\", "/").split("/")
    if parts[0] != BASELINES_DIR or len(parts) != 2 or not ID_RE.match(parts[1]):
        raise MapError("GEOM_INPUT_INVALID", f"baseline {bid}의 경로({rel})는 baselines/<id> 형식이어야 합니다")
    return os.path.join(S, BASELINES_DIR, parts[1])


def baselines_input(S: str, ids_roots: Sequence[tuple[str, str]], features_rel: str) -> list[dict[str, str]]:
    """`paicad map --baselines` 입력 [{id, features(절대), rel}]."""
    out = []
    for bid, root in ids_roots:
        rel = "." if os.path.normpath(root) == os.path.normpath(S) else os.path.relpath(root, S).replace(os.sep, "/")
        out.append({"id": bid, "features": os.path.join(root, *features_rel.split("/")), "rel": rel})
    return out


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


# ------------------------------------------------------------------ 파라미터 표
def _range_of(f: Mapping[str, Any] | None, rows: Mapping[str, Mapping[str, Any]], name: str) -> dict[str, float] | None:
    """원 파라미터의 (nominal, min, max): 그 baseline 파라미터 표 행 우선, 없으면 features range."""
    r = rows.get(name)
    if r is not None:
        return {"nominal": float(r["nominal"]), "min": float(r["min"]), "max": float(r["max"])}
    if f is None:
        return None
    rg = f.get("range") if isinstance(f.get("range"), dict) else {}
    try:
        return {"nominal": float(f["nominal"]), "min": float(rg["min"]), "max": float(rg["max"])}
    except (KeyError, TypeError, ValueError):
        return None


def feasible_of(f: Mapping[str, Any] | None, fallback: Mapping[str, float] | None) -> tuple[float, float] | None:
    """`feasible`(source envelope 우선, 없으면 estimate) → (lo, hi). 없으면 파라미터 범위."""
    fe = (f or {}).get("feasible")
    if isinstance(fe, dict):
        lo, hi = fe.get("min"), fe.get("max")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and math.isfinite(lo) and math.isfinite(hi) and lo <= hi:
            return float(lo), float(hi)
    if fallback is not None:
        return float(fallback["min"]), float(fallback["max"])
    return None


def parameter_rows(pm: Mapping[str, Any], features: Mapping[str, Mapping[str, Mapping[str, Any]]],
                   param_rows: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """확정 매칭표 → 세트 파라미터 표(공통 이름 행). features = {bid: {원 이름: 피처}}, param_rows = {bid: {원 이름: 표 행}}.
    공통 행 min·max = 활성 baseline 범위의 합집합, nominal = 첫 활성 baseline 공칭, `baselines` = {bid: {param, nominal, min, max, feasible}|null}."""
    out = []
    bids = baseline_ids(pm)
    for v in variables(pm):
        per: dict[str, Any] = {}
        for b in bids:
            orig = v.map.get(b)
            if orig is None:
                per[b] = None
                continue
            f = (features.get(b) or {}).get(orig)
            rg = _range_of(f, param_rows.get(b) or {}, orig)
            if rg is None:
                raise MapError("GEOM_INPUT_INVALID", f"{v.name}: baseline {b}의 {orig} 범위를 알 수 없습니다")
            fe = feasible_of(f, rg)
            per[b] = {"param": orig, **rg, "feasible": {"min": fe[0], "max": fe[1]} if fe else None}
        act = [per[b] for b in bids if per[b] is not None]
        lo, hi = min(x["min"] for x in act), max(x["max"] for x in act)
        nom = act[0]["nominal"]
        out.append({"name": v.name, "nominal": min(max(nom, lo), hi), "min": lo, "max": hi, "unit": v.unit or "mm", "baselines": per})
    return out


# ------------------------------------------------------------------ 샘플 배정·변환
def _per(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(r["name"]): r for r in rows if isinstance(r.get("baselines"), dict)}


def assign_baseline(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], values: Mapping[str, Any]) -> str | None:
    """샘플 배정(§7.3.8): topology = values["baseline"], range = 활성 값이 모두 그 baseline feasible 이내인 후보 중
    분할 변수 공칭이 가장 가까운 baseline(동률 = baselines 순서). 후보 없음 → None(BASELINE_NO_COVER)."""
    bids = baseline_ids(pm)
    if pm.get("usage") == "topology":
        b = values.get("baseline")
        return b if isinstance(b, str) and b in bids else None
    per = _per(rows)
    split = (pm.get("range_split") or {}).get("param")
    cands = []
    for b in bids:
        ok = True
        for name, r in per.items():
            info = r["baselines"].get(b)
            x = values.get(name)
            if info is None or x is None:
                continue
            fe = info.get("feasible") or {"min": info["min"], "max": info["max"]}
            if not (fe["min"] - 1e-12 <= float(x) <= fe["max"] + 1e-12):
                ok = False
                break
        if ok:
            cands.append(b)
    if not cands:
        return None
    if not split or split not in per or values.get(split) is None:
        return cands[0]
    x = float(values[split])
    return min(cands, key=lambda b: (abs(x - per[split]["baselines"][b]["nominal"]) if per[split]["baselines"].get(b) else math.inf,
                                     bids.index(b)))


def original_values(rows: Sequence[Mapping[str, Any]], bid: str, common: Mapping[str, Any]) -> dict[str, float]:
    """공통 이름 값 → 그 baseline 원 파라미터 이름 값(values.json 키, §4.10). N/A 변수·값 없음은 넣지 않는다."""
    out: dict[str, float] = {}
    for name, r in _per(rows).items():
        info = r["baselines"].get(bid)
        x = common.get(name)
        if info is not None and x is not None:
            out[str(info["param"])] = float(x)
    return out


def na_names(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """어느 baseline에서든 N/A인 공통 변수(결측 지시 열 대상)."""
    bids = baseline_ids(pm)
    return [n for n, r in _per(rows).items() if any(r["baselines"].get(b) is None for b in bids)]


def training_columns(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], extra: Sequence[str] = ()) -> list[str]:
    """학습 입력 열(§7.3.8): 공통 변수 + 쉘 두께 등 extra + `<이름>__na`(N/A 가능 변수) + topology면 `baseline__<id>` 원-핫."""
    cols = list(_per(rows)) + list(extra)
    cols += [n + NA_SUFFIX for n in na_names(pm, rows)]
    if pm.get("usage") == "topology":
        cols += [ONEHOT_PREFIX + b for b in baseline_ids(pm)]
    return cols


def training_values(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], bid: str, common: Mapping[str, Any],
                    extra: Mapping[str, float] | None = None) -> dict[str, float]:
    """학습 입력 값: N/A 변수는 0 대체 + 지시 열 1(아니면 0), topology 원-핫. run 메타(null)와 달리 여기서만 0 대체."""
    per = _per(rows)
    out: dict[str, float] = {}
    for name, r in per.items():
        na = r["baselines"].get(bid) is None or common.get(name) is None
        out[name] = 0.0 if na else float(common[name])
    for k, v in (extra or {}).items():
        out[k] = float(v)
    for name in na_names(pm, rows):
        out[name + NA_SUFFIX] = 1.0 if (per[name]["baselines"].get(bid) is None or common.get(name) is None) else 0.0
    if pm.get("usage") == "topology":
        for b in baseline_ids(pm):
            out[ONEHOT_PREFIX + b] = 1.0 if b == bid else 0.0
    return out


def training_snapshot(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], extra_rows: Sequence[Mapping[str, Any]] = ()
                      ) -> list[dict[str, Any]]:
    """DOE parameters_snapshot(학습 입력 열과 같은 순서): 공통 행 + extra 행 + 지시·원-핫 열(0~1)."""
    snap = [{"name": r["name"], "nominal": r["nominal"], "min": r["min"], "max": r["max"], "unit": r.get("unit", "")}
            for r in _per(rows).values()]
    snap += [{"name": r["name"], "nominal": r["nominal"], "min": r["min"], "max": r["max"], "unit": r.get("unit", "")} for r in extra_rows]
    for n in na_names(pm, rows):
        snap.append({"name": n + NA_SUFFIX, "nominal": 0.0, "min": 0.0, "max": 1.0, "unit": ""})
    if pm.get("usage") == "topology":
        snap += [{"name": ONEHOT_PREFIX + b, "nominal": 0.0, "min": 0.0, "max": 1.0, "unit": ""} for b in baseline_ids(pm)]
    return snap


# ------------------------------------------------------------------ 층화 LHS(§7.3.8 DOE)
def stratum_counts(n: int, b: int) -> list[int]:
    """n_b = ⌊N/B⌋ + (앞쪽 baseline부터 나머지 1씩) — 수준별 샘플 수 차 ≤ 1."""
    q, r = divmod(int(n), int(b))
    return [q + (1 if k < r else 0) for k in range(b)]


def _split_intervals(pm: Mapping[str, Any], per_split: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    """range: 분할 변수 구간 = 인접 공칭의 중점 경계, 양 끝은 그 baseline 범위 끝."""
    ivs = [iv for iv in (pm.get("range_split") or {}).get("intervals") or [] if isinstance(iv, dict)]
    order = sorted(((float(iv["nominal"]), str(iv["baseline"])) for iv in ivs if iv.get("baseline") in per_split
                    and per_split[iv["baseline"]] is not None), key=lambda t: t)
    out: dict[str, tuple[float, float]] = {}
    for k, (nom, b) in enumerate(order):
        lo = (order[k - 1][0] + nom) / 2 if k > 0 else -math.inf
        hi = (nom + order[k + 1][0]) / 2 if k + 1 < len(order) else math.inf
        out[b] = (lo, hi)
    return out


def range_gaps(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """range: 분할 변수 구간이 그 baseline feasible과 겹치지 않거나 인접 feasible 사이에 틈이 있으면 경고 대상(BASELINE_RANGE_GAP)."""
    per = _per(rows)
    split = (pm.get("range_split") or {}).get("param")
    if pm.get("usage") != "range" or split not in per:
        return []
    bl = per[split]["baselines"]
    fe = sorted(((info["feasible"] or info)["min"], (info["feasible"] or info)["max"], b) for b, info in bl.items() if info)
    return [f"{fe[k][2]}–{fe[k + 1][2]}" for k in range(len(fe) - 1) if fe[k][1] < fe[k + 1][0]]


def stratified_lhs(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], n: int, seed: int,
                   lhs: Callable[[Sequence[str], Mapping[str, tuple[float, float]], int, int], list[dict[str, float]]],
                   run_key: Callable[[int], str], extra: Mapping[str, tuple[float, float]] | None = None
                   ) -> list[tuple[int, str, str, dict[str, float | None]]]:
    """baseline별 층화 LHS → [(doe_no, run_key, baseline_id, {공통 이름: 값|None})]. 층 k(0부터)의 seed = seed + k(결정적).
    (a) topology: 층 변수 = 그 baseline 활성 변수의 그 baseline 범위. (b) range: 분할 변수 = 담당 구간(인접 공칭 중점 경계)을
    그 baseline feasible로 자른 구간, 나머지 활성 변수 = 그 baseline 범위. N/A 변수 = None.
    extra = baseline과 무관한 변수(쉘 두께 등) {이름: (min, max)} — 모든 층에서 같은 범위로 함께 뽑는다."""
    per = _per(rows)
    bids = baseline_ids(pm)
    counts = stratum_counts(n, len(bids))
    split = (pm.get("range_split") or {}).get("param") if pm.get("usage") == "range" else None
    ivs = _split_intervals(pm, per[split]["baselines"]) if split in per else {}
    out: list[tuple[int, str, str, dict[str, float | None]]] = []
    doe_no = 0
    for k, (b, nb) in enumerate(zip(bids, counts)):
        if nb <= 0:
            continue
        names = [name for name, r in per.items() if r["baselines"].get(b) is not None]
        bounds: dict[str, tuple[float, float]] = {}
        for name in names:
            info = per[name]["baselines"][b]
            lo, hi = float(info["min"]), float(info["max"])
            if name == split and b in ivs:
                fe = info.get("feasible") or {"min": lo, "max": hi}
                lo, hi = max(ivs[b][0], float(fe["min"])), min(ivs[b][1], float(fe["max"]))
                if lo > hi:  # 담당 구간이 feasible 밖 = 미커버 구간 → 그 baseline 범위로(배정이 NO_COVER로 걸러냄)
                    lo, hi = float(info["min"]), float(info["max"])
            bounds[name] = (lo, hi)
        for name, bd in (extra or {}).items():
            names.append(name)
            bounds[name] = (float(bd[0]), float(bd[1]))
        samples = lhs(names, bounds, nb, seed + k) if names else [{} for _ in range(nb)]
        for vals in samples:
            doe_no += 1
            row: dict[str, float | None] = {name: (vals.get(name) if name in vals else None) for name in per}
            row.update({name: vals[name] for name in (extra or {})})
            out.append((doe_no, run_key(doe_no), b, row))
    return out


# ------------------------------------------------------------------ 세트 폴더 읽기(API·워커 공용)
FEATURES_REL = "native/extract/parameter_features.json"


def _read_json(path: str, max_bytes: int) -> dict[str, Any] | None:
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _rep_features(doc: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not doc:
        return {}
    members: set[str] = set()
    reps: set[str] = set()
    for g in doc.get("groups") or []:
        if isinstance(g, dict) and isinstance(g.get("parameter"), str):
            reps.add(g["parameter"])
            members |= {m for m in g.get("members") or [] if isinstance(m, str)}
    return {f["name"]: f for f in doc.get("features") or []
            if isinstance(f, dict) and isinstance(f.get("name"), str) and (f["name"] in reps or f["name"] not in members)}


def read_baselines(S: str, pm: Mapping[str, Any], max_bytes: int) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, dict[str, Any]]]]:
    """({bid: {원 이름: 대표 피처}}, {bid: {원 이름: 파라미터 표 행}}). base 표 = 다중 전환 전 단일 표(single_parameters.json) 우선."""
    feats: dict[str, dict[str, dict[str, Any]]] = {}
    rows: dict[str, dict[str, dict[str, Any]]] = {}
    for b in baseline_ids(pm):
        root = baseline_root(S, pm, b)
        feats[b] = _rep_features(_read_json(os.path.join(root, *FEATURES_REL.split("/")), max_bytes))
        pj = os.path.join(S, *SINGLE_PARAMS.split("/")) if root == S and os.path.isfile(os.path.join(S, *SINGLE_PARAMS.split("/"))) \
            else os.path.join(root, "parameters.json")
        doc = _read_json(pj, max_bytes) or {}
        rows[b] = {str(r["name"]): r for r in doc.get("parameters") or []
                   if isinstance(r, dict) and isinstance(r.get("name"), str) and r.get("source") != "prop"
                   and all(isinstance(r.get(k), (int, float)) for k in ("nominal", "min", "max"))}
    return feats, rows


def rep_features_at(root: str, max_bytes: int) -> dict[str, dict[str, Any]]:
    return _rep_features(_read_json(os.path.join(root, *FEATURES_REL.split("/")), max_bytes))


def known_names(feats: Mapping[str, Mapping[str, Any]]) -> dict[str, set[str]]:
    return {b: set(f) for b, f in feats.items()}
