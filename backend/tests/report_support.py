"""upload-report.md V-RP 시험 공용: 응답 검사(헤더·파일명·외부 자원 0·단일 파일)와 inline 데이터 파싱."""

from __future__ import annotations

import json
import os
import re
from urllib.parse import unquote

CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"
# V-RP-1: 외부 URL·로딩 컨텍스트 0건
EXTERNAL = [r"https?://", r"(?:src|href|action|poster)\s*=\s*[\"']?//", r"<link\b", r"<script[^>]*\bsrc\s*=", r"@import", r"url\(", r"<iframe",
            r"\bfetch\(", r"XMLHttpRequest", r"<object\b", r"<embed\b", r"<form\b", r"<base\b", r"sendBeacon", r"\bimport\s*\("]
FILENAME_RE = re.compile(r"^PAI_(?P<study>[^_].*?)_(?P<target>analysis-batch|analysis-doe|surrogate-opt|optimization|equiv-check)_(?P<id8>[0-9a-f]{8})_"
                         r"(?P<ts>\d{8}-\d{4})\.html$")


def assert_no_external(doc: str) -> None:
    for pat in EXTERNAL:
        assert not re.search(pat, doc, re.I), pat
    for m in re.finditer(r"<img\b[^>]*>", doc, re.I):  # 그림은 data URI만
        assert re.search(r'\bsrc="data:image/png;base64,', m.group(0)), m.group(0)[:80]
    assert doc.count("<script") == 2                       # inline JSON 1 + inline JS 1(테마 전환)
    assert "xmlns" not in doc and doc.startswith("<!DOCTYPE html>")


def filename_of(resp) -> str:
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment; filename*=UTF-8''"), cd
    return unquote(cd.split("''", 1)[1])


def assert_report_basics(resp, target_key: str, target_id: str, study_title: str | None = None) -> str:
    h = resp.headers
    assert h["content-type"].startswith("text/html") and "charset=utf-8" in h["content-type"].lower()
    assert h["content-security-policy"] == CSP and h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer" and h["cache-control"] == "no-store"
    name = filename_of(resp)
    m = FILENAME_RE.match(name)
    assert m, name
    assert m["target"] == target_key and target_id.startswith(m["id8"]), name
    if study_title is not None:
        assert m["study"] == study_title, name
    doc = resp.text
    dump = os.environ.get("PAI_REPORT_DUMP")  # 개발 중 눈으로 확인용(시험 동작 무관)
    if dump:
        os.makedirs(dump, exist_ok=True)
        with open(os.path.join(dump, name), "w", encoding="utf-8") as fh:
            fh.write(doc)
    assert_no_external(doc)
    assert f'content="{CSP}"' in doc.replace("&#x27;", "'")  # HTML 메타에도 같은 CSP(저장한 파일도 보호)
    return doc


def parse_data(doc: str) -> dict:
    m = re.search(r'<script type="application/json" id="pai-report-data">(.*?)</script>', doc, re.S)
    assert m
    return json.loads(m.group(1))
