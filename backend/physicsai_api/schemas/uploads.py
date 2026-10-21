"""API 스키마 — 브라우저 분할 업로드(upload-report.md §4). 청크 본문은 octet-stream(요청 모델 없음)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Req, Resp
from .studies import PathInspectResponse, PathProblem

__all__ = ["UploadItemIn", "UploadCreate", "UploadAddFiles", "UploadEntryOut", "UploadOut", "UploadChunkOut",
           "UploadCompleteOut", "UploadPurposeInfo", "UploadConfig", "UploadCleanupOut"]

SHA256_PATTERN = r"^[0-9a-fA-F]{64}$"


class UploadItemIn(Req):
    rel: str = Field(min_length=1, max_length=400, description="선택 폴더 기준 상대경로('/' 구분, 파일 이름 포함)")
    size: int = Field(ge=0, description="파일 크기[B]")
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN, description="파일 전체 sha256(선택 — 마지막 청크에서 서버가 확인)")


class UploadCreate(Req):
    purpose: str = Field(min_length=1, max_length=40, description="paths/inspect purpose(SPDM_IMPORT 제외) 또는 업로드 전용 DISCOVER")
    name: str = Field(min_length=1, max_length=200, description="폴더 이름에 쓸 표시 이름(경로 구분자·'..' 불가)")
    engine: Literal["native", "altair"] | None = Field(default=None, description="CAD_FILE 허용 확장자 기준(생략 = altair)")
    files: list[UploadItemIn] = Field(min_length=1)


class UploadAddFiles(Req):
    files: list[UploadItemIn] = Field(min_length=1)


class UploadEntryOut(Resp):
    index: int
    rel: str
    size: int
    received: int = Field(description="서버가 받은 바이트 — 이어 올리기 offset")
    done: bool
    sha256: str | None = None
    sha256_expected: str | None = None


class UploadOut(Resp):
    upload_id: str
    study_id: str
    purpose: str
    engine: Literal["native", "altair"] | None = None
    name: str
    state: Literal["OPEN", "COMPLETED", "CANCELED", "STALE"]
    path: str | None = Field(None, description="경로 칸에 채울 값(폴더 또는 CAD 파일 1개 — 취소·낡음이면 null)")
    display_path: str | None = None
    chunk_size: int
    total_bytes: int
    received_bytes: int
    files: list[UploadEntryOut]
    inspect: PathInspectResponse | None = None
    backup_display_path: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class UploadChunkOut(Resp):
    index: int
    received: int
    done: bool
    sha256: str | None = None


class UploadCompleteOut(Resp):
    upload_id: str
    state: Literal["OPEN", "COMPLETED", "CANCELED", "STALE"]
    path: str | None = None
    display_path: str | None = None
    purpose: str
    inspect: PathInspectResponse | None = None
    problems: list[PathProblem]


class UploadPurposeInfo(Resp):
    patterns: list[str]
    mode: Literal["file", "dir", "dir_or_file"]
    engine_patterns: dict[str, list[str]] | None = Field(None, description="CAD_FILE만: engine(native|altair)별 패턴")


class UploadConfig(Resp):
    enabled: bool
    chunk_size: int
    max_file_bytes: int
    max_upload_bytes: int
    max_files: int
    max_concurrent_per_user: int
    purposes: dict[str, UploadPurposeInfo]
    always_denied: list[str]
    free_bytes: int | None = None


class UploadCleanupOut(Resp):
    moved: list[str]

