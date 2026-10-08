"""④ 파라미터 세트 폴더 검증·정규화·복사(계약 §15.4)."""

from __future__ import annotations

import csv
import fnmatch
import io
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .fileutil import copy_file, sha256_file, write_json, write_text
from .paths import is_link_or_reparse
from .tpl_render import VALID_FMT_RE, parse_tpl

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RUN_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
TPL_NAME = "simlab_parametered_mesh.tpl"


@dataclass
class ParamSetFolder:
    problems: list[dict[str, Any]] = field(default_factory=list)
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


def _load_parameters(f: ParamSetFolder, folder: str) -> None:
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
        if not lo <= nom <= hi:
            _p(f, "PARAMETER_RANGE_INVALID", f"'{name}': min ≤ nominal ≤ max 이어야 합니다", f.param_source)
            continue
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


def validate_folder(folder: str, *, max_samples: int, max_total_bytes: int, starter_glob: str) -> ParamSetFolder:
    f = ParamSetFolder()
    total = 0
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        for d in list(dirnames):
            if is_link_or_reparse(os.path.join(dirpath, d)):
                _p(f, "PATH_UNSAFE", "링크 폴더는 쓸 수 없습니다", os.path.relpath(os.path.join(dirpath, d), folder))
                dirnames.remove(d)
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            if is_link_or_reparse(fp):
                _p(f, "PATH_UNSAFE", "링크 파일은 쓸 수 없습니다", os.path.relpath(fp, folder))
                continue
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    f.total_bytes = total
    if total > max_total_bytes:
        _p(f, "PARAM_SET_TOO_LARGE", f"폴더 총량이 상한({max_total_bytes} bytes)을 넘습니다")
    _load_parameters(f, folder)
    _load_responses(f, folder)
    if f.parameters:
        _load_samples(f, folder, max_samples)
    # cad/
    cad_dir = os.path.join(folder, "cad")
    if not os.path.isdir(cad_dir):
        _p(f, "CAD_MISSING", "cad 폴더가 필요합니다", "cad")
    else:
        cads = sorted(x for x in os.listdir(cad_dir) if os.path.isfile(os.path.join(cad_dir, x)))
        if len(cads) != 1:
            _p(f, "CAD_COUNT", f"cad 폴더에는 CAD 파일이 정확히 1개 있어야 합니다(현재 {len(cads)}개)", "cad")
        else:
            f.cad_file = cads[0]
            if re.search(r"[\s&|<>^%!\"]", cads[0]):
                _p(f, "PATH_UNSAFE", "CAD 파일 이름에 공백·cmd 메타문자를 쓸 수 없습니다", "cad/" + cads[0])
    # tpl
    tpl = os.path.join(folder, TPL_NAME)
    if not os.path.isfile(tpl):
        _p(f, "TPL_MISSING", f"{TPL_NAME}이 필요합니다", TPL_NAME)
    else:
        try:
            decl, refs = parse_tpl(_read_text(tpl))
        except UnicodeDecodeError:
            _p(f, "TPL_INVALID", "tpl은 UTF-8이어야 합니다", TPL_NAME)
            decl, refs = {}, []
        if f.parameters and set(decl.values()) != {p["name"] for p in f.parameters}:
            _p(f, "PARAM_TPL_MISMATCH", "tpl의 parameter 이름 집합이 파라미터 이름 집합과 다릅니다", TPL_NAME)
        for r in refs:
            if not VALID_FMT_RE.match(r["format"]):
                _p(f, "TPL_FORMAT_INVALID", f"tpl 형식 '{r['format']}'을 쓸 수 없습니다", TPL_NAME)
            if r["var"] not in decl:
                _p(f, "TPL_VAR_UNDEFINED", f"tpl 변수 '{r['var']}'가 parameter로 정의되지 않았습니다", TPL_NAME)
        f.tpl_params = [r for r in refs if r["var"] in decl]
    # radioss_assem/
    assem = os.path.join(folder, "radioss_assem")
    if not os.path.isdir(assem):
        _p(f, "ASSEM_MISSING", "radioss_assem 폴더가 필요합니다", "radioss_assem")
    else:
        files = sorted(
            x for x in os.listdir(assem)
            if os.path.isfile(os.path.join(assem, x)) and x.lower().endswith((".rad", ".inc"))
        )
        f.assem_files = files
        starters = [x for x in files if fnmatch.fnmatch(x, starter_glob)]
        if len(starters) != 1:
            _p(f, "STARTER_COUNT", f"radioss_assem에 starter({starter_glob})가 정확히 1개 있어야 합니다(현재 {len(starters)}개)", "radioss_assem")
        else:
            f.starter_name = starters[0]
    return f


def write_normalized(f: ParamSetFolder, src: str, dst: str, source_path: str) -> None:
    """정규화본(JSON·CSV 재작성)과 원본 파일을 dst(04_params/<id>/)로 복사."""
    os.makedirs(dst, exist_ok=True)
    write_json(os.path.join(dst, "parameters.json"),
               {"schema_version": 1, "unit_system": f.unit_system, "parameters": f.parameters})
    if f.has_responses:
        write_json(os.path.join(dst, "responses.json"), {"responses": f.responses_raw})
    if f.has_samples:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        pn = [p["name"] for p in f.parameters]
        rn = [h[5:] for h in f.sample_columns if h.startswith("resp:")]
        w.writerow(["run_key", *pn, *[f"resp:{r}" for r in rn]])
        for s in f.samples:
            w.writerow([s["run_key"], *[repr(s["values"][n]) for n in pn],
                        *["" if s["measured"].get(r) is None else repr(s["measured"][r]) for r in rn]])
        write_text(os.path.join(dst, "samples.csv"), buf.getvalue())
    originals = {}
    for name in ("parameters.json", "parameters.csv", "samples.csv", "responses.json"):
        sp = os.path.join(src, name)
        if os.path.isfile(sp):
            copy_file(sp, os.path.join(dst, "original", name))
            originals[name] = sha256_file(sp)
    copy_file(os.path.join(src, "cad", f.cad_file or ""), os.path.join(dst, "cad", f.cad_file or ""))
    copy_file(os.path.join(src, TPL_NAME), os.path.join(dst, TPL_NAME))
    for x in f.assem_files:
        copy_file(os.path.join(src, "radioss_assem", x), os.path.join(dst, "radioss_assem", x))
    write_json(
        os.path.join(dst, "source.json"),
        {
            "source_path": source_path,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "originals_sha256": originals,
        },
    )


def read_samples(stored_dir: str) -> tuple[list[str], list[dict[str, Any]]]:
    """정규화된 samples.csv 읽기(없으면 빈 목록)."""
    p = os.path.join(stored_dir, "samples.csv")
    if not os.path.isfile(p):
        return [], []
    out = []
    with open(p, encoding="utf-8", newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd, [])
        for row in rd:
            if not row:
                continue
            values, measured = {}, {}
            for h, c in zip(header[1:], row[1:]):
                if h.startswith("resp:"):
                    measured[h[5:]] = float(c) if c else None
                else:
                    values[h] = float(c)
            out.append({"run_key": row[0], "values": values, "measured": measured})
    return header, out
