"""API 스키마 — 형상 3D 보기·미리보기·결과 3D 컨투어(geometry-view.md §6.5·§6.9·§13.5). R-B 300줄 분할: `geometry`에서 재노출."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import Req, Resp

__all__ = ["ViewTess", "GeomView", "GeomPreviewCreate", "GeomPreviewTiming", "GeomPreview", "Contour3dDisplay", "Contour3dCreate",
           "Contour3dProgress", "Contour3dReason", "Contour3d"]


# ---- 형상 3D 보기·미리보기(geometry-view.md §6.5·§6.9) ---------------------------------------------------------------


class ViewTess(Resp):
    linear_mm: float | None = None
    angular_deg: float | None = None


class GeomView(Resp):
    """공칭 3D 뷰(④ 세트 `GET /param-sets/{id}/view`, ① `GET /studies/{id}/train/view`). GLB·manifest는 artifacts로 받는다
    (`/artifacts/{glb_artifact_id}/media` model/gltf-binary, `/artifacts/{manifest_artifact_id}/content` JSON)."""

    param_set_id: str | None = None
    train_setup_id: str | None = None  # ① 학습 단계(§6.9)만
    kind: Literal["solid", "shell"] = "solid"
    status: Literal["READY", "MISSING", "FAILED"]
    reason: str | None = None  # 한국어(MISSING·FAILED 사유)
    glb_artifact_id: str | None = None
    manifest_artifact_id: str | None = None
    tess: ViewTess | None = None
    engine_version: str | None = None
    available: bool = False  # features.geometry_view[_shell]
    preview_available: bool = False  # ① 학습 단계는 항상 false(미리보기는 ④만)


class GeomPreviewCreate(Req):
    """`POST /param-sets/{id}/previews`: 대표 파라미터 이름 → 값(빠진 이름은 공칭). fe 생략 = off(화면은 off·check만)."""

    values: dict[str, float] = Field(default_factory=dict)
    fe: Literal["off", "check"] = "off"


class GeomPreviewTiming(Resp):
    total_s: float | None = None
    update_s: float | None = None
    tess_s: float | None = None
    morph_s: float | None = None
    check_s: float | None = None


class GeomPreview(Resp):
    """미리보기 1건(§6.5). 200 = 캐시 적중(cache_hit), 202 = QUEUED·RUNNING(job_id) — 화면은 `GET /previews/{id}`를 0.5초 간격으로."""

    id: str
    param_set_id: str
    job_id: str | None = None
    status: Literal["QUEUED", "RUNNING", "DONE", "FAILED", "CANCELED", "EXPIRED"]
    cache_hit: bool = False
    values: dict[str, float]
    fe: str = "off"
    result_status: Literal["OK", "FAIL"] | None = None
    code: str | None = None
    category: str | None = None
    message_ko: str | None = None  # code → 한국어(geometry-engine.md §6.5·shell-morph.md §6.7·geometry-view.md §5.5)
    fe_status: str | None = None
    fe_code: str | None = None
    glb_artifact_id: str | None = None
    fe_glb_artifact_id: str | None = None
    manifest_artifact_id: str | None = None
    timing: GeomPreviewTiming | None = None
    created_at: Any = None
    finished_at: Any = None


# ---- 결과 3D 컨투어(geometry-view.md §13.5) ---------------------------------------------------------------------------


class Contour3dDisplay(Req):
    """표시 값(생략 = 기존 컨투어 표시 설정 결정 순서 결과). 범례는 뷰어가 manifest min·max로 정한다."""

    field: str | None = Field(default=None, max_length=120)
    component: str | None = Field(default=None, max_length=120)
    avgmode: str | None = Field(default=None, max_length=40)
    unit: str | None = Field(default=None, max_length=16)  # 범례 단위(선택 — TCL이 단위를 읽지 않으므로 표시 설정 값을 쓴다, C3F-14)


class Contour3dCreate(Req):
    """`POST /contour3d` — 열 때 생성(해석·예측 완료 시 자동 생성 안 함).
    source_ref: PREDICT_H3D = {job_id}(성공한 PREDICT), SOLVER_H3D = {fem_verification_id} 또는 {study_id, h3d_rel}(Study 기준 .h3d
    상대 경로 — ① run 결과 등)."""

    source_kind: Literal["SOLVER_H3D", "PREDICT_H3D"]
    source_ref: dict[str, str]
    display: Contour3dDisplay | None = None


class Contour3dProgress(Resp):
    """대기 안내 화면용 진행 단계(§13.6): phase = waiting(대기) | reading_h3d(H3D 읽기) | geometry(형상) | frames(프레임 변환) |
    done(완료) | failed(실패) | canceled(취소). estimate_s = 같은 원본 종류 최근 소요 평균(없으면 null → 화면 "수 분")."""

    phase: Literal["waiting", "reading_h3d", "geometry", "frames", "done", "failed", "canceled", "expired"]
    phase_label: str
    step_key: str | None = None
    percent: float | None = None
    label: str | None = None
    elapsed_s: float | None = None
    estimate_s: float | None = None
    can_cancel: bool = False


class Contour3dReason(Resp):
    """결과 FAIL(DONE + result_status FAIL) 대체 사유(contour3d-field.md §12). kind = nodes | glb | frames | field | other.
    수치는 FAIL manifest의 `limits`(못 읽으면 null → code·message_ko만 보임). `comps_applicable` = false(쿠션 입력 예측)면
    "부품 이름으로 범위를 줄이거나" 문구를 뺀다."""

    kind: Literal["nodes", "glb", "frames", "field", "other"]
    code: str | None = None
    message_ko: str | None = None
    detail: str | None = None
    nodes: int | None = None
    max_nodes: int | None = None
    glb_bytes: int | None = None
    max_glb_bytes: int | None = None
    bin_bytes: int | None = None
    max_bin_bytes: int | None = None
    field: str | None = None
    comps_applicable: bool = True


class Contour3d(Resp):
    id: str
    job_id: str | None = None
    status: Literal["QUEUED", "RUNNING", "DONE", "FAILED", "CANCELED", "EXPIRED"]
    cache_hit: bool = False
    source_kind: str
    source_ref: dict[str, Any]
    display: dict[str, Any] | None = None
    result_status: Literal["OK", "FAIL"] | None = None
    code: str | None = None
    message_ko: str | None = None
    frames: int | None = None
    nodes: int | None = None
    bytes: int | None = None
    glb_artifact_id: str | None = None
    frames_artifact_id: str | None = None
    manifest_artifact_id: str | None = None
    disp_artifact_id: str | None = None  # 변위 프레임 파일(`CONTOUR3D_DISP`, Range) — 변위가 없으면 null(변형 배율 컨트롤 숨김)
    lod_artifact_id: str | None = None  # LOD GLB(`CONTOUR3D_LOD`) — 노드 수가 lod_min_nodes 이하면 null
    timing: dict[str, Any] | None = None
    progress: Contour3dProgress | None = None
    retryable: bool = False  # true = 작업 FAILED·CANCELED([다시] 보임). 결과 FAIL(DONE)은 false — 사유만 보인다
    reason: Contour3dReason | None = None
    created_at: Any = None
    finished_at: Any = None
