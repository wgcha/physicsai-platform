"""다중 baseline 매칭표 기본(R-B 300줄 분할 — `baselines`에서 재노출): 상수·`MapError`·`Var`·파일·목록(§4.10·§7.3.8)."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
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
