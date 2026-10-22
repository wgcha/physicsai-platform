"""④ 파라미터 세트 폴더 검증 결과(`ParamSetFolder`)와 parameters·responses·samples 파일 읽기(계약 §15.4)."""

from __future__ import annotations

import csv
import io
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any

from ..naming import NAME_RE, RUN_KEY_RE


@dataclass
class ParamSetFolder:
    problems: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)  # 막지 않는 안내(Native 공칭 범위 밖 VAR_NOMINAL_OUTSIDE)
    unit_system: str = "mm-ton-s"
    parameters: list[dict[str, Any]] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)
    responses_raw: list[dict[str, Any]] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    sample_columns: list[str] = field(default_factory=list)
    sample_has_measured: bool = False
    cad_file: str | None = None
    starter_name: str | None = None
    assem_files: list[str] = field(default_factory=list)
    renum_csv: str | None = None  # phase3 §11.4 radioss_assem/{predict.renum_csv_name}(있으면 복사)
    input_kind: str = "assembly"  # phase3 §14.4: radioss_assem/ 없음 = mesh_only(m1 메시로 바로 예측)
    tpl_params: list[dict[str, str]] = field(default_factory=list)
    total_bytes: int = 0
    param_source: str | None = None
    has_samples: bool = False
    has_responses: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> dict[str, Any]:
        return {
            "parameter_count": len(self.parameters),
            "parameters": [p["name"] for p in self.parameters],
            "sample_count": len(self.samples),
            "sample_has_measured": self.sample_has_measured,
            "response_count": len(self.responses),
            "unit_system": self.unit_system,
            "cad_file_name": self.cad_file,
            "starter_name": self.starter_name,
            "renum_csv": self.renum_csv,
            "input_kind": self.input_kind,
            "total_bytes": self.total_bytes,
        }


def _p(folder: ParamSetFolder, code: str, message: str, file: str | None = None) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if file:
        item["file"] = file
    folder.problems.append(item)


def _finite(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8-sig", errors="strict") as fh:
        return fh.read()


def _load_parameters(f: ParamSetFolder, folder: str, *, require_nominal_inside: bool = True) -> None:
    """`require_nominal_inside=False`(Native 폴더 검증만, native-vars.md NV-10): `min ≤ nominal ≤ max` 검사를 `min ≤ max`로 완화한다."""
    pj, pc = os.path.join(folder, "parameters.json"), os.path.join(folder, "parameters.csv")
    rows: list[dict[str, Any]] = []
    if os.path.isfile(pj):
        f.param_source = "parameters.json"
        try:
            data = json.loads(_read_text(pj))
        except (ValueError, UnicodeDecodeError) as exc:
            _p(f, "PARAMETERS_INVALID", f"parameters.json 형식 오류: {exc}", "parameters.json")
            return
        if not isinstance(data, dict) or not isinstance(data.get("parameters"), list):
            _p(f, "PARAMETERS_INVALID", "parameters.json에 parameters 배열이 없습니다", "parameters.json")
            return
        if data.get("schema_version", 1) != 1:
            _p(f, "PARAMETERS_INVALID", "schema_version은 1이어야 합니다", "parameters.json")
        if isinstance(data.get("unit_system"), str) and data["unit_system"]:
            f.unit_system = data["unit_system"][:40]
        rows = data["parameters"]
    elif os.path.isfile(pc):
        f.param_source = "parameters.csv"
        try:
            rd = csv.DictReader(io.StringIO(_read_text(pc)))
            if [c.strip() for c in (rd.fieldnames or [])][:4] != ["name", "nominal", "min", "max"]:
                _p(f, "PARAMETERS_INVALID", "parameters.csv 헤더는 name,nominal,min,max,unit 입니다", "parameters.csv")
                return
            rows = [dict(r) for r in rd]
        except (csv.Error, UnicodeDecodeError) as exc:
            _p(f, "PARAMETERS_INVALID", f"parameters.csv 형식 오류: {exc}", "parameters.csv")
            return
    else:
        _p(f, "PARAMETERS_MISSING", "parameters.json 또는 parameters.csv가 필요합니다")
        return
    seen = set()
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            _p(f, "PARAMETERS_INVALID", f"{i + 1}번째 파라미터 형식 오류", f.param_source)
            continue
        name = str(r.get("name", "")).strip()
        if not NAME_RE.match(name):
            _p(f, "PARAMETER_NAME_INVALID", f"파라미터 이름 '{name}'이 규칙(^[A-Za-z_][A-Za-z0-9_]{{0,63}}$)에 맞지 않습니다", f.param_source)
            continue
        if name in seen:
            _p(f, "PARAMETER_DUPLICATE", f"파라미터 이름 '{name}'이 중복됩니다", f.param_source)
            continue
        seen.add(name)
        nom, lo, hi = _finite(r.get("nominal")), _finite(r.get("min")), _finite(r.get("max"))
        if nom is None or lo is None or hi is None:
            _p(f, "PARAMETER_VALUE_INVALID", f"'{name}'의 nominal/min/max는 유한한 숫자여야 합니다", f.param_source)
            continue
        if require_nominal_inside and not lo <= nom <= hi:
            _p(f, "PARAMETER_RANGE_INVALID", f"'{name}': min ≤ nominal ≤ max 이어야 합니다", f.param_source)
            continue
        if not require_nominal_inside and not lo <= hi:
            _p(f, "PARAMETER_RANGE_INVALID", f"'{name}': min ≤ max 이어야 합니다", f.param_source)
            continue
        if not require_nominal_inside and not lo <= nom <= hi:
            f.warnings.append({"code": "VAR_NOMINAL_OUTSIDE", "message": f"'{name}' 공칭 {nom:g}이 범위 {lo:g}~{hi:g} 밖입니다(기존안은 범위 밖 점으로 표시)",
                               "file": f.param_source})
        unit = str(r.get("unit") or "").strip()[:40]
        f.parameters.append({"name": name, "nominal": nom, "min": lo, "max": hi, "unit": unit})
    if not f.parameters and not f.problems:
        _p(f, "PARAMETERS_INVALID", "파라미터가 1개 이상 필요합니다", f.param_source)


def _load_responses(f: ParamSetFolder, folder: str) -> None:
    p = os.path.join(folder, "responses.json")
    if not os.path.isfile(p):
        return
    f.has_responses = True
    try:
        data = json.loads(_read_text(p))
    except (ValueError, UnicodeDecodeError) as exc:
        _p(f, "RESPONSES_INVALID", f"responses.json 형식 오류: {exc}", "responses.json")
        return
    if not isinstance(data, dict) or not isinstance(data.get("responses"), list):
        _p(f, "RESPONSES_INVALID", "responses 배열이 없습니다", "responses.json")
        return
    seen = set()
    for r in data["responses"]:
        name = str((r or {}).get("name", "")).strip() if isinstance(r, dict) else ""
        if not NAME_RE.match(name) or name in seen:
            _p(f, "RESPONSE_NAME_INVALID", f"응답 이름 '{name}'이 규칙에 맞지 않거나 중복됩니다", "responses.json")
            continue
        seen.add(name)
        f.responses.append({"name": name, "unit": str(r.get("unit") or "")[:40]})
        f.responses_raw.append({"name": name, "unit": str(r.get("unit") or "")[:40], "spec": r.get("spec", {})})


def _load_samples(f: ParamSetFolder, folder: str, max_samples: int) -> None:
    p = os.path.join(folder, "samples.csv")
    if not os.path.isfile(p):
        return
    f.has_samples = True
    try:
        with open(p, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh)
            header = [h.strip() for h in next(rd, [])]
            if not header or header[0] != "run_key":
                _p(f, "SAMPLES_INVALID", "samples.csv 첫 열은 run_key여야 합니다", "samples.csv")
                return
            pnames = {pp["name"] for pp in f.parameters}
            pcols = [h for h in header[1:] if not h.startswith("resp:")]
            rcols = [h[5:] for h in header[1:] if h.startswith("resp:")]
            if set(pcols) != pnames or len(pcols) != len(set(pcols)):
                _p(f, "SAMPLES_COLUMNS_MISMATCH", "samples.csv 파라미터 열이 파라미터 이름 집합과 다릅니다", "samples.csv")
                return
            rnames = {r["name"] for r in f.responses}
            if not set(rcols) <= rnames:
                _p(f, "SAMPLES_RESPONSE_UNKNOWN", "samples.csv의 resp: 열 이름이 responses.json에 없습니다", "samples.csv")
                return
            f.sample_columns = header
            f.sample_has_measured = bool(rcols)
            keys = set()
            for ln, row in enumerate(rd, start=2):
                if not row or all(not c.strip() for c in row):
                    continue
                if len(f.samples) >= max_samples:
                    _p(f, "SAMPLES_TOO_MANY", f"samples.csv 행이 최대 {max_samples}개를 넘습니다", "samples.csv")
                    return
                if len(row) != len(header):
                    _p(f, "SAMPLES_INVALID", f"{ln}행 열 수가 헤더와 다릅니다", "samples.csv")
                    return
                rk = row[0].strip()
                if not RUN_KEY_RE.match(rk) or rk in keys:
                    _p(f, "SAMPLES_INVALID", f"{ln}행 run_key '{rk}'가 규칙에 맞지 않거나 중복됩니다", "samples.csv")
                    return
                keys.add(rk)
                values: dict[str, float] = {}
                measured: dict[str, float | None] = {}
                for h, c in zip(header[1:], row[1:]):
                    if h.startswith("resp:"):
                        measured[h[5:]] = _finite(c) if c.strip() else None
                        continue
                    v = _finite(c)
                    if v is None:
                        _p(f, "SAMPLES_INVALID", f"{ln}행 '{h}' 값이 유한한 숫자가 아닙니다", "samples.csv")
                        return
                    values[h] = v
                f.samples.append({"run_key": rk, "values": values, "measured": measured})
    except (csv.Error, UnicodeDecodeError) as exc:
        _p(f, "SAMPLES_INVALID", f"samples.csv 형식 오류: {exc}", "samples.csv")
