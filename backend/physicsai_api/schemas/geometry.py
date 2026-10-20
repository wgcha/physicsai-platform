"""API 스키마 — native 형상 엔진(geometry-engine.md §7.4~§7.6): 세트 준비 상태·피처 목록·202 응답.

300줄 분할(R-B): 형상 3D 보기·미리보기·결과 컨투어 모델은 `geometry_view`(맨 아래에서 재노출)."""

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


from .geometry_view import (  # noqa: E402,F401 - 300줄 분할(R-B), 기존 경로 재노출
    Contour3d, Contour3dCreate, Contour3dDisplay, Contour3dProgress, GeomPreview, GeomPreviewCreate, GeomPreviewTiming, GeomView,
    ViewTess,
)
