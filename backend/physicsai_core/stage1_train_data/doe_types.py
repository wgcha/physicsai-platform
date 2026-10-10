"""①-3 DOE 유형 정의(resources.doe_design_type_json = 원본 CONFIG/DATA/DATA_doe_design_type.json) 검증(phase2 §6.4).

형식: {label: {value, default_runs, runs_editable, fields:[{key, label, type: combo|int|bool, items?, default, min?, max?}]}}
(원본 2_gui_run_hst_gen_rad_input.py:205-294)
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..errors import DomainError

FIELD_TYPES = ("combo", "int", "bool")


class DoeTypesInvalid(ValueError):
    pass


def parse_doe_types(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not data:
        raise DoeTypesInvalid("최상위는 비어 있지 않은 객체여야 합니다")
    out = []
    for label, cfg in data.items():
        if not isinstance(label, str) or not isinstance(cfg, dict):
            raise DoeTypesInvalid(f"'{label}' 형식 오류")
        value = cfg.get("value")
        if not isinstance(value, str) or not value:
            raise DoeTypesInvalid(f"'{label}'.value가 없습니다")
        dr = cfg.get("default_runs", 2)
        if not isinstance(dr, int) or isinstance(dr, bool) or dr < 1:
            raise DoeTypesInvalid(f"'{label}'.default_runs는 양의 정수")
        editable = cfg.get("runs_editable", True)
        if not isinstance(editable, bool):
            raise DoeTypesInvalid(f"'{label}'.runs_editable은 bool")
        fields = []
        for f in cfg.get("fields", []) or []:
            if not isinstance(f, dict) or not isinstance(f.get("key"), str) or f.get("type") not in FIELD_TYPES:
                raise DoeTypesInvalid(f"'{label}'.fields 항목 형식 오류")
            item: dict[str, Any] = {"key": f["key"], "label": str(f.get("label") or f["key"]), "type": f["type"],
                                    "default": f.get("default")}
            if f["type"] == "combo":
                items = f.get("items")
                if not isinstance(items, list) or not items or not all(isinstance(x, str) for x in items):
                    raise DoeTypesInvalid(f"'{label}'.{f['key']}.items는 문자열 배열")
                item["items"] = items
            if f["type"] == "int":
                item["min"] = int(f.get("min", 0))
                item["max"] = int(f.get("max", 999999))
            fields.append(item)
        out.append({"label": label, "value": value, "default_runs": dr, "runs_editable": editable, "fields": fields})
    return out


def load_doe_types(path: str, max_bytes: int) -> list[dict[str, Any]]:
    """설정 경로에서 읽기. 없음·형식 오류 → DomainError(503 CONFIG_INVALID)."""
    if not path:
        raise DomainError("RESOURCE_NOT_CONFIGURED", "DOE 유형 정의 파일이 설정되지 않았습니다", status=409,
                          missing=["resources.doe_design_type_json"])
    try:
        if os.path.getsize(path) > max_bytes:
            raise DoeTypesInvalid("파일이 너무 큽니다")
        with open(path, encoding="utf-8-sig") as fh:
            return parse_doe_types(json.load(fh))
    except (OSError, ValueError, DoeTypesInvalid) as exc:
        raise DomainError("CONFIG_INVALID", f"DOE 유형 정의 파일 오류: {exc}", status=503) from None


def find(types: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    return next((t for t in types if t["label"] == label), None)


def validate_options(t: dict[str, Any], options: dict[str, Any]) -> list[dict[str, str]]:
    """options 키 집합 = fields 키 집합, combo는 items 중 하나, int는 [min,max], bool은 bool."""
    problems = []
    keys = {f["key"] for f in t["fields"]}
    for k in options:
        if k not in keys:
            problems.append({"key": k, "message": "알 수 없는 옵션"})
    for f in t["fields"]:
        k = f["key"]
        if k not in options:
            problems.append({"key": k, "message": "필수 옵션"})
            continue
        v = options[k]
        if f["type"] == "combo" and (not isinstance(v, str) or v not in f["items"]):
            problems.append({"key": k, "message": f"{f['items']} 중 하나"})
        elif f["type"] == "int" and (not isinstance(v, int) or isinstance(v, bool) or not f["min"] <= v <= f["max"]):
            problems.append({"key": k, "message": f"정수 {f['min']}~{f['max']}"})
        elif f["type"] == "bool" and not isinstance(v, bool):
            problems.append({"key": k, "message": "true/false"})
    return problems
