"""④ 파라미터 세트 폴더 검증·정규화·복사(계약 §15.4). 파일별 읽기는 param_set_files(`ParamSetFolder` 재노출)."""

from __future__ import annotations

import csv
import fnmatch
import io
import os
from datetime import datetime, timezone
from typing import Any

from ..fileutil import copy_file, sha256_file, write_json, write_text
from ..naming import NAME_RE, RUN_KEY_RE, TPL_NAME  # noqa: F401 - 모듈 속성 유지(architecture §1.1 naming)
from ..paths import file_name_problem_message, is_link_or_reparse, name_unsafe_chars
from ..tpl_render import VALID_FMT_RE, parse_tpl
from .param_set_files import ParamSetFolder, _load_parameters, _load_responses, _load_samples, _p, _read_text
from .prepared_input import is_mesh_file


def validate_folder(folder: str, *, max_samples: int, max_total_bytes: int, starter_glob: str,
                    renum_csv_name: str | None = None) -> ParamSetFolder:
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
            why = name_unsafe_chars(cads[0])
            if why:
                _p(f, "PATH_UNSAFE", f"CAD {file_name_problem_message(why)}", "cad/" + cads[0])
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
        # phase3 §11.4(§15.4 갱신): eps_mesh로 시작하는 파일은 무시(starter로 세지 않고 복사 안 함), RENUM csv는 있으면 복사
        files = sorted(
            x for x in os.listdir(assem)
            if os.path.isfile(os.path.join(assem, x)) and x.lower().endswith((".rad", ".inc")) and not is_mesh_file(x)
        )
        f.assem_files = files
        # 복사 뒤 외부 명령 인자(starter·include)로 쓰인다(phase3 D3-35)
        for x in files:
            why = name_unsafe_chars(x)
            if why:
                _p(f, "PATH_UNSAFE", file_name_problem_message(why), "radioss_assem/" + x)
        if renum_csv_name:
            f.renum_csv = next((x for x in sorted(os.listdir(assem)) if x.lower() == renum_csv_name.lower()
                                and os.path.isfile(os.path.join(assem, x))), None)
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
    for x in f.assem_files + ([f.renum_csv] if f.renum_csv else []):
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
