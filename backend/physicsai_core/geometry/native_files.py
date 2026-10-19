"""플랫폼이 쓰는 native 파일들(geometry-engine.md §4.4·§7.3.3·§7.3.6): values.json·native_params.xml·doe_matrix.csv·SKIPPED.json.

모두 순수 함수(문자열·dict 반환) — 파일 쓰기는 호출자가 fileutil로 한다."""

from __future__ import annotations

import csv
import io
from typing import Any
from xml.sax.saxutils import quoteattr

from .messages import category_of, korean_message


def values_document(values: dict[str, float], kind: str, source_id: str | None, engine_version: str | None,
                    doe_no: int | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """`values.json`(§4.4). 값은 반올림하지 않는다(GE-9). kind ∈ predict|batch|doe."""
    src: dict[str, Any] = {"kind": kind, "id": source_id}
    if doe_no is not None:
        src["doe_no"] = doe_no
    doc: dict[str, Any] = {"schema_version": 1, "engine": "native", "engine_version": engine_version,
                           "values": {k: float(v) for k, v in values.items()}, "source": src}
    if extra:
        doc.update(extra)
    return doc


def native_params_xml(values: dict[str, float], nominals: dict[str, float]) -> str:
    """paramitem 호환 파일(§7.3.6): 기존 `train_data.paramitem_regex`·`rendered_tpl_exts`(.xml)로 샘플 값이 추출된다.
    줄 형식 `   <paramitem Name="<이름>" NewValue="<값 repr>" Value="<공칭>"/>`, 루트 `<Parameters Value="">`."""
    lines = ['<Parameters Value="">']
    for name, v in values.items():
        nom = nominals.get(name, v)
        lines.append(f"   <paramitem Name={quoteattr(name)} NewValue={quoteattr(repr(float(v)))} Value={quoteattr(repr(float(nom)))}/>")
    lines.append("</Parameters>")
    return "\n".join(lines) + "\n"


def doe_matrix_csv(names: list[str], rows: list[tuple[int, str, dict[str, float]]]) -> str:
    """`D/doe_matrix.csv`: `doe_no,run_key,<이름…>`(값 repr, 행 순서 = doe_no)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["doe_no", "run_key", *names])
    for doe_no, run_key, vals in rows:
        w.writerow([doe_no, run_key, *[repr(float(vals[n])) for n in names]])
    return buf.getvalue()


def skipped_document(code: str, english: str | None, step: str | None, report: str | None, engine_version: str | None,
                     category: str | None = None) -> dict[str, Any]:
    """`R/SKIPPED.json`(§7.3.6): {schema_version, engine, engine_version, code, category, message, step, report}.
    message = 한국어 표준 문구(§6.5, 영문 기술 메시지 덧붙임)."""
    return {"schema_version": 1, "engine": "native", "engine_version": engine_version, "code": code,
            "category": category_of(code, category), "message": korean_message(code, english), "step": step, "report": report}


def doe_matrix_csv_multi(names: list[str], rows: list[tuple[int, str, str | None, dict[str, float | None]]]) -> str:
    """다중 baseline DOE `D/doe_matrix.csv`(§7.3.8): `doe_no,run_key,baseline_id,<공통 이름…>`. N/A 칸·배정 없음은 빈 값."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["doe_no", "run_key", "baseline_id", *names])
    for doe_no, run_key, bid, vals in rows:
        w.writerow([doe_no, run_key, bid or "", *["" if vals.get(n) is None else repr(float(vals[n])) for n in names]])  # type: ignore[arg-type]
    return buf.getvalue()


def read_doe_matrix(text: str) -> list[tuple[int, str, str | None, dict[str, float | None]]]:
    """doe_matrix.csv(단일·다중 공용) → [(doe_no, run_key, baseline_id|None, {이름: 값|None})]."""
    rd = csv.DictReader(io.StringIO(text))
    names = [h for h in (rd.fieldnames or []) if h not in ("doe_no", "run_key", "baseline_id")]
    out = []
    for r in rd:
        out.append((int(r["doe_no"]), r["run_key"], (r.get("baseline_id") or None),
                    {n: (float(r[n]) if (r.get(n) or "").strip() else None) for n in names}))
    return out
