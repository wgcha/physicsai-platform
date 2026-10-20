"""API 스키마 — native 형상 엔진(geometry-engine.md §7.4~§7.6): 세트 준비 상태·피처 목록·202 응답."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import Req, Resp

__all__ = ["NativeAccepted", "NativeInfo", "NativeFeature", "NativeGroup", "NativeWarning", "NativeFeatures",
           "ShellPropPart", "ShellProp", "ShellPropWarning", "ShellProps", "ShellPropSelect", "ShellPropsUpdate",
           "BaselineAddRequest", "ParamMapRemapRequest", "BaselineInfo", "ParamMapDecisionPart", "ParamMapDecision", "ParamMapRowDecision",
           "ParamMapUpdate", "ParamMapProposed", "ParamMapRow", "ParamMapBaseline", "ParamMapWarning", "ParamMap",
           "ViewTess", "GeomView", "GeomPreviewCreate", "GeomPreviewTiming", "GeomPreview", "Contour3dDisplay", "Contour3dCreate",
           "Contour3dProgress", "Contour3d"]


class NativeAccepted(Resp):
    """native 세트 등록·다시 준비 202 본문 — 진행은 job으로 본다."""

    job_id: str


class NativeInfo(Resp):
    prep_status: Literal["READY", "STALE", "MISSING"]
    prep_reason: str | None = None  # 한국어(STALE·MISSING 사유)
    feature_count: int = 0
    shell_only: bool = False  # §11.1 쉘 두께 전용 세트(형상 피처·tag 없음)
    props_scanned: bool = False  # §11.1 native/props/props.json 있음
    kind: Literal["solid", "shell"] = "solid"  # shell-morph.md §8.2: 세트 형상 종류(native/prep.json kind, 없으면 solid)
    view_status: Literal["READY", "MISSING", "FAILED"] = "MISSING"  # geometry-view.md §6.5: 공칭 3D 뷰 상태


class NativeFeature(Resp):
    name: str
    type: str = ""
    body: str = ""
    nominal: float | None = None
    min: float | None = None
    max: float | None = None
    unit: str = "mm"
    group: str | None = None
    ref_provisional: bool = False
    ref_locked: bool = False
    feasible: dict[str, Any] | None = None
    png_artifact_id: str | None = None


class NativeGroup(Resp):
    id: str | None = None
    kind: str | None = None
    parameter: str | None = None
    members: list[str] = []


class NativeWarning(Resp):
    code: str
    message: str = ""
    feature: str | None = None


class NativeFeatures(Resp):
    engine_version: str | None = None
    features: list[NativeFeature]
    groups: list[NativeGroup]
    warnings: list[NativeWarning]


# ---- 단계 3S 쉘 두께(geometry-engine.md §11.1) -------------------------------------------------------------


class ShellPropPart(Resp):
    id: int | None = None
    title: str = ""
    thickness: float | None = None  # part_overrides: /PART 카드 Thick(≠0이면 PROP 두께를 덮어씀)


class ShellProp(Resp):
    """props scan 결과 1행 + 현재 선택. selectable=false면 reason_code(PROP_UNSUPPORTED_TYPE·PROP_OVERRIDDEN_BY_ELEMENT·
    PROP_OVERRIDDEN_BY_PART·PROP_THICKNESS_INVALID)."""

    id: int | None = None
    title: str = ""
    type: str = ""
    keyword: str = ""
    supported: bool = False
    parameter: str | None = None
    thickness: float | None = None
    range: dict[str, Any] | None = None
    parts: list[ShellPropPart] = []
    part_overrides: list[ShellPropPart] = []
    element_overrides: int = 0
    file: str | None = None
    selectable: bool = False
    reason_code: str | None = None
    selected: bool = False
    min: float | None = None
    max: float | None = None


class ShellPropWarning(Resp):
    code: str
    prop: int | None = None
    parts: list[int] = []
    message: str = ""


class ShellProps(Resp):
    """`GET /param-sets/{id}/props`: 스캔 전이면 scanned=false·빈 목록."""

    scanned: bool
    shell_only: bool = False
    include_geometry: bool = True  # 파라미터 표에 형상 행이 있는가
    engine_version: str | None = None
    props: list[ShellProp] = []
    warnings: list[ShellPropWarning] = []


class ShellPropSelect(Req):
    name: str = Field(max_length=64)
    min: float | None = None  # 생략 = 공칭 −range_ratio
    max: float | None = None  # 생략 = 공칭 +range_ratio


class ShellPropsUpdate(Req):
    """`PUT /param-sets/{id}/props`: 선택 전체 교체. include_geometry=false면 형상 행을 빼고 쉘 두께만(§11.1, 다중 baseline 세트 불가)."""

    selected: list[ShellPropSelect] = Field(max_length=500)
    include_geometry: bool = True


# ---- 단계 4B 다중 baseline(geometry-engine.md §4.10·§7.3.8) ------------------------------------------------


class BaselineAddRequest(Req):
    """`POST /param-sets/{id}/baselines` → 202 {job_id}(PARAM_SET_NATIVE mode add_baseline). path = 그 baseline 프로젝트 폴더."""

    id: str = Field(max_length=32)
    path: str = Field(max_length=400)
    choice: dict[str, str | None] | None = None  # {cad, radioss_assem}(discover 후보 상대경로, 후보 1개면 생략)
    label: str | None = Field(default=None, max_length=120)
    usage: Literal["topology", "range"] | None = None  # 생략 = 기존 매칭표 usage(없으면 topology)
    split_param: str | None = Field(default=None, max_length=64)  # range 분할 변수(제안 공통 이름)


class ParamMapRemapRequest(Req):
    """`POST /param-sets/{id}/remap` → 202 {job_id}(PARAM_SET_NATIVE mode remap). 생략 = 기존 usage·분할 변수."""

    usage: Literal["topology", "range"] | None = None
    split_param: str | None = Field(default=None, max_length=64)


class BaselineInfo(Resp):
    id: str
    rel: str
    label: str | None = None
    prep_status: Literal["READY", "STALE", "MISSING"] = "MISSING"
    prep_reason: str | None = None
    feature_count: int = 0


class ParamMapDecisionPart(Req):
    name: str = Field(max_length=64)
    map: dict[str, str | None]


class ParamMapDecision(Req):
    """사용자 결정: accept(제안 그대로) | rename·change(name·map 지정, map 값 null = 그 baseline N/A) | split(parts마다 변수 1개)."""

    action: Literal["accept", "rename", "change", "split"]
    name: str | None = Field(default=None, max_length=64)
    map: dict[str, str | None] | None = None
    parts: list[ParamMapDecisionPart] | None = Field(default=None, max_length=32)


class ParamMapRowDecision(Req):
    row_id: str = Field(max_length=64)
    decision: ParamMapDecision | None  # null = 결정 취소(미결정)


class ParamMapUpdate(Req):
    """`PUT /param-sets/{id}/param-map`: 행별 decision만 저장(proposed·signature 불변). 확정 상태면 draft로 되돌린다."""

    decisions: list[ParamMapRowDecision] = Field(max_length=2000)


class ParamMapProposed(Resp):
    name: str
    score: float | None = None
    grade: Literal["recommend", "check", "unmatched"] | None = None
    map: dict[str, str | None] = {}
    nominal: dict[str, float | None] = {}
    group_size: int | None = None
    candidates: list[dict[str, Any]] = []


class ParamMapRow(Resp):
    row_id: str
    type: str = ""
    feature_type: str | None = None
    unit: str = "mm"
    signature: str = ""
    needs_review: bool = False
    proposed: ParamMapProposed
    decision: dict[str, Any] | None = None
    requires_decision: bool = False  # check 등급·needs_review 행에 결정이 없으면 true(확정 전 필수)


class ParamMapBaseline(Resp):
    id: str
    rel: str | None = None


class ParamMapWarning(Resp):
    code: str
    row_id: str | None = None
    message: str = ""


class ParamMap(Resp):
    """`GET·PUT /param-sets/{id}/param-map`, `POST …/confirm` 본문(param_map.json + 요약)."""

    status: Literal["draft", "confirmed"]
    usage: Literal["topology", "range"]
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    engine_version: str | None = None
    baselines: list[ParamMapBaseline]
    discrete: dict[str, Any] | None = None
    range_split: dict[str, Any] | None = None
    common: list[ParamMapRow]
    map_options: dict[str, Any] | None = None
    warnings: list[ParamMapWarning] = []
    unresolved_rows: list[str] = []  # 확정 전에 명시 결정이 필요한 행
    undecided_count: int = 0
    variables: list[str] = []  # 확정이면 decision 공통 이름, draft면 표시용 proposed 이름


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
    timing: dict[str, Any] | None = None
    progress: Contour3dProgress | None = None
    created_at: Any = None
    finished_at: Any = None
