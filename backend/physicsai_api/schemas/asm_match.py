"""API 스키마 — 조립 매칭(asm-match.md §6.3). 요청은 알 수 없는 키 거부, 응답은 가산 필드 허용."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from .common import Req, Resp

__all__ = ["AsmCad", "AsmMatchCreate", "AsmRowIn", "AsmRowsPut", "AsmMatchCreated", "AsmCheckStarted", "AsmMatch", "AsmMatchList"]


class AsmCad(Req):
    kind: Literal["train", "path"] = Field(description="STEP 출처 — train(①-1 Native 추출 결과, 피처 파일 사용) | path(④ 새 템플릿의 STEP 파일 경로)")
    path: str | None = Field(default=None, max_length=1024, description="kind=path일 때 STEP 파일 경로(허용 루트 안, 확장자는 geometry.step_extensions)")


class AsmMatchCreate(Req):
    """`POST /studies/{id}/asm-matches` — 조립 폴더와 STEP 출처를 정하고 component 목록 작업(mode parts)을 시작."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"radioss_assem_path": "D:/AI/assem", "cad": {"kind": "train"}}]})
    radioss_assem_path: str = Field(min_length=1, max_length=1024, description="Radioss 조립 폴더 경로(허용 루트 안, starter 정확히 1개)")
    cad: AsmCad = Field(description="STEP 출처 {kind: train | path, path?}")


class AsmRowIn(Req):
    body: str = Field(min_length=1, max_length=128, description="STEP 바디 이름(asm_match_get의 bodies[].body)")
    pids: list[int] = Field(min_length=1, max_length=64, description="이 바디에 대응하는 조립 /PART id 목록(1:N 허용, 1 이상 정수, 다른 행과 겹치지 않음)")


class AsmRowsPut(Req):
    """`PUT /asm-matches/{id}/rows` — 초안 저장(검사 결과는 무효가 됨)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"rows": [{"body": "CUSH_L", "pids": [3000001]}, {"body": "CUSH_R", "pids": [3000002, 3000003]}], "excluded_bodies": []}]})
    rows: list[AsmRowIn] = Field(max_length=2000, description="매칭 행 — 바디마다 최대 1행(매칭할 바디만)")
    excluded_bodies: list[str] = Field(default_factory=list, max_length=2000,
                                       description="매칭 안 함으로 둔 바디 이름(use=true 파라미터가 있는 바디는 제외 불가)")


class AsmMatchCreated(Resp):
    match_id: str
    job_id: str


class AsmCheckStarted(Resp):
    job_id: str
    match_id: str | None = None
    seq: int | None = None  # 이번 검사 번호(check/<seq>/)


class AsmMatch(Resp):
    """조립 매칭 묶음 상태. state = SCANNING|DRAFT|CHECKING|CHECKED|CONFIRMED|FAILED|STALE.
    bodies·parts·recommend는 `paicad asm parts` 보고(asm_parts.json) 그대로(§4.2), check는 최신 검사 요약(§4.3)."""

    match_id: str
    study_id: str
    state: Literal["SCANNING", "DRAFT", "CHECKING", "CHECKED", "CONFIRMED", "FAILED", "STALE"]
    source: dict[str, Any] = Field(default_factory=dict)  # {kind, cad_name, features_rel|null}
    assem: dict[str, Any] = Field(default_factory=dict)  # {display_path, digest, starter, files}
    bodies: list[dict[str, Any]] = Field(default_factory=list)
    parts: list[dict[str, Any]] = Field(default_factory=list)
    recommend: list[dict[str, Any]] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    excluded_bodies: list[str] = Field(default_factory=list)
    check: dict[str, Any] | None = None  # {seq, status, rows_sha256, rows:[…], file_checks, glb_url, current}
    confirmed: dict[str, Any] | None = None  # {sha256, confirmed_at}
    stale_reason: str | None = None
    # 가산(additive) 필드 — 화면이 진행·실패 사유를 보이는 데 쓴다
    last_job: dict[str, Any] | None = None  # {id, mode, state, failure_code, failure_message, progress_pct}
    warnings: list[dict[str, Any]] = Field(  # [{code, message}] — 목록 읽기 경고 + 확정 뒤 ASM_CHECK_FAILED_WARN·ASM_CHECK_STALE_WARN(AM-C3)
        default_factory=list, description="경고 [{code, message}]. 확정된 매칭에는 검사 불합격(ASM_CHECK_FAILED_WARN)·검사가 현재 행과 다름(ASM_CHECK_STALE_WARN)이 올 수 있다")
    rows_complete: bool = False  # 모든 바디가 선택 또는 매칭 안 함 + 매칭 행 ≥1(검사·저장 가능 조건)
    use_bodies: list[str] = Field(default_factory=list)  # use=true 파라미터가 있는 바디(① 출처만, "매칭 안 함" 불가 표시용)
    created_at: str | None = None
    updated_at: str | None = None


class AsmMatchList(Resp):
    """`GET /studies/{id}/asm-matches` — 최신순, 항목은 단건 조회(AsmMatch)와 같은 모양."""

    items: list[AsmMatch] = Field(default_factory=list)
