"""MCP 리소스 URI ↔ 백엔드 API 경로 표(mcp.md §20.2). 내용은 전부 백엔드 응답 — 이 파일은 경로 매핑만 한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

MIME = "application/json"
_SEG = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class StaticResource:
    uri: str
    name: str
    description: str
    path: str


@dataclass(frozen=True)
class TemplateResource:
    uri_template: str
    name: str
    description: str


STATIC = (
    StaticResource("physicsai://glossary", "glossary", "Domain glossary (entities, job kinds, feature abbreviations, error codes) / 도메인 용어집",
                   "/api/mcp/glossary"),
    StaticResource("physicsai://job-kinds", "job-kinds", "Job kinds that can be created through the API / API로 만들 수 있는 작업 종류",
                   "/api/mcp/job-kinds"),
)
TEMPLATES = (
    TemplateResource("physicsai://glossary/{section}", "glossary-section",
                     "One glossary section: entities, job_types, job_kinds, stages, feature_abbr, enums, error_codes, terms / 용어집 한 절"),
    TemplateResource("physicsai://job-kinds/{kind}", "job-kind", "Params JSON Schema, example and limits of one job kind / 작업 종류 하나의 스키마·예시·한도"),
)


def resolve(uri: str) -> tuple[str, dict[str, str]] | None:
    """URI → (API 경로, 쿼리). 모르는 URI·형식이 틀린 세그먼트면 None."""
    for r in STATIC:
        if uri == r.uri:
            return r.path, {}
    prefix = "physicsai://glossary/"
    if uri.startswith(prefix):
        sec = uri[len(prefix):]
        return ("/api/mcp/glossary", {"section": sec}) if _SEG.fullmatch(sec) else None
    prefix = "physicsai://job-kinds/"
    if uri.startswith(prefix):
        kind = uri[len(prefix):]
        return (f"/api/mcp/job-kinds/{quote(kind, safe='')}", {}) if _SEG.fullmatch(kind) else None
    return None
