from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..schemas import mcp as M
from ..services import native_vars_api as vars_svc
from ..services import param_set_baselines_api as bl_svc
from ..services import param_set_native_api as native_svc
from ..services import param_set_props_api as props_svc
from ..services import param_set_responses as resp_svc
from ..services import stage4_predict as svc

router = APIRouter(tags=["param-sets"])
ERR = {404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}, 422: {"model": S.ErrorResponse}}


@router.post("/studies/{study_id}/param-sets", response_model=S.ParamSet, status_code=201,
             responses={**ERR, 202: {"model": S.NativeAccepted, "description": "engine=native: 형상 준비 작업이 만들어졌습니다"}})
def register(study_id: str, body: S.ParamSetCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """§15.4 폴더 등록. mode="discover"면 프로젝트 폴더에서 자동 구성(phase3 §13 S8)."""
    out = svc.register_param_set(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))
    if "job_id" in out and "id" not in out:  # engine=native: 202 {job_id}(geometry-engine.md §7.4)
        return JSONResponse(out, status_code=202)  # type: ignore[return-value]
    return out


@router.post("/studies/{study_id}/param-sets/discover", response_model=S.ParamSetDiscoverResponse, responses=ERR)
def discover(study_id: str, body: S.ParamSetDiscoverRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """phase3 §13 S8: 프로젝트 폴더에서 tpl·CAD·조립 폴더·파라미터 후보 찾기(디스크 읽기만)."""
    return svc.discover_param_set(get_ctx(request), principal, study_id, body)


@router.post("/studies/{study_id}/param-sets/from-train", response_model=S.ParamSet, status_code=201, responses=ERR)
def from_train(study_id: str, body: S.ParamSetFromTrain, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """F(phase2 §6.13): ① DOE 결과로 파라미터 세트 만들기."""
    return svc.register_param_set_from_train(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))


@router.get("/studies/{study_id}/param-sets", response_model=list[S.ParamSet], responses=ERR)
def list_sets(study_id: str, request: Request, response: Response, limit: int | None = Query(default=None, ge=1, le=200),
              cursor: str | None = None, _p: Principal = Depends(get_principal)) -> list:
    items, nxt = svc.list_param_sets(get_ctx(request), study_id, limit, cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/param-sets/{ps_id}", response_model=S.ParamSet, responses=ERR)
def get_set(ps_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_param_set(get_ctx(request), ps_id)


@router.patch("/param-sets/{ps_id}", response_model=S.ParamSet, responses=ERR)
def patch_set(ps_id: str, body: S.ParamSetPatch, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """표시 이름(label) 바꾸기(phase3 §13 S8)."""
    return svc.patch_param_set(get_ctx(request), principal, ps_id, body, request_id(request), client_ip(request))


@router.put("/param-sets/{ps_id}/responses", response_model=S.ParamSet, responses={**ERR, 403: {"model": S.ErrorResponse}})
def put_responses(ps_id: str, body: S.ParamSetResponsesUpdate, request: Request,
                  principal: Principal = Depends(get_principal)) -> dict:
    """템플릿 응답 정의(phase3 §14.6): ⑤ OptResponse H3D 형식. 422 RESPONSE_INVALID·RESPONSE_IN_USE + problems."""
    return resp_svc.put_responses(get_ctx(request), principal, ps_id, body.responses, request_id(request), client_ip(request))


@router.get("/param-sets/{ps_id}/samples", response_model=S.SamplesPage, responses=ERR)
def samples(ps_id: str, request: Request, limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None,
            _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_samples(get_ctx(request), ps_id, limit, cursor)


@router.post("/studies/{study_id}/predict/check", response_model=S.PredictCheckResponse, summary="예측 입력 범위 검사",
             responses={**ERR, **M.errors(e404="NOT_FOUND · PARAM_SET_REQUIRED", e422="INVALID_PARAMS")},
             openapi_extra=M.xmcp_tool("check_prediction_input", "read", "Check parameter values against the set range (no job created)",
                                       "파라미터 값이 세트 범위 안인지·반올림·최근접 학습 run 확인"))
def predict_check(study_id: Annotated[str, Path(description="Study id")], body: S.PredictCheckRequest, request: Request,
                  _p: Principal = Depends(get_principal)) -> dict:
    """파라미터 값이 세트 범위(min~max) 안인지, 정수 반올림, 가장 가까운 학습 run을 확인한다(저장·작업 없음). 예측 전에 쓴다."""
    return svc.predict_check(get_ctx(request), study_id, body.param_set_id, body.values)


@router.post("/param-sets/{ps_id}/native-prepare", response_model=S.NativeAccepted, status_code=202, responses=ERR)
def native_prepare(ps_id: str, request: Request, body: S.NativePrepareRequest | None = None,
                   principal: Principal = Depends(get_principal)) -> dict:
    """geometry-engine.md §7.4: native 세트의 형상 준비를 다시 한다(tag 옵션 변경·입력 교체·엔진 버전 변경 후).
    본문은 없어도 된다(extract_filter가 오면 422 — 등록된 세트의 추출 조건은 바꿀 수 없음)."""
    return native_svc.prepare_native(get_ctx(request), principal, ps_id, request_id(request), client_ip(request), body)


@router.get("/param-sets/{ps_id}/features", response_model=S.NativeFeatures, responses=ERR)
def native_features(ps_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """geometry-engine.md §7.6: 추출된 형상 피처·그룹·경고(하이라이트 PNG artifact id 포함)."""
    return native_svc.features(get_ctx(request), ps_id)


# ---- 단계 3S 쉘 두께(geometry-engine.md §11.1) ----
@router.post("/param-sets/{ps_id}/props/scan", response_model=S.NativeAccepted, status_code=202, responses=ERR)
def props_scan(ps_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """조립 폴더의 /PROP/TYPE1 쉘 두께 목록을 다시 찾는다(PARAM_SET_NATIVE mode props_scan 작업)."""
    return props_svc.start_scan(get_ctx(request), principal, ps_id, request_id(request), client_ip(request))


@router.get("/param-sets/{ps_id}/props", response_model=S.ShellProps, responses=ERR)
def props_get(ps_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """PROP 스캔 결과 + 현재 선택(스캔 전이면 scanned=false)."""
    return props_svc.get_props(get_ctx(request), ps_id)


@router.put("/param-sets/{ps_id}/props", response_model=S.ParamSet, responses={**ERR, 403: {"model": S.ErrorResponse}})
def props_put(ps_id: str, body: S.ShellPropsUpdate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """쉘 두께 파라미터 선택 저장(파라미터 표 source=prop 행 전체 교체). 422 PROP_SELECTION_INVALID + problems."""
    return props_svc.put_props(get_ctx(request), principal, ps_id, body, request_id(request), client_ip(request))


# ---- 단계 4B 다중 baseline(geometry-engine.md §7.3.8) ----
@router.post("/param-sets/{ps_id}/baselines", response_model=S.NativeAccepted, status_code=202, responses=ERR)
def baseline_add(ps_id: str, body: S.BaselineAddRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """baseline 추가(PARAM_SET_NATIVE mode add_baseline: 준비·추출·tag·BL_MAP 매칭 초안). 매칭표는 항상 draft로 저장된다."""
    return bl_svc.add_baseline(get_ctx(request), principal, ps_id, body, request_id(request), client_ip(request))


@router.post("/param-sets/{ps_id}/baselines/disable", response_model=S.ParamSet, responses={**ERR, 403: {"model": S.ErrorResponse}})
def baseline_disable(ps_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """단일 baseline으로 되돌림(baselines/·param_map.json은 _backup으로)."""
    return bl_svc.disable(get_ctx(request), principal, ps_id, request_id(request), client_ip(request))


@router.delete("/param-sets/{ps_id}/baselines/{baseline_id}", response_model=S.ParamSet,
               responses={**ERR, 403: {"model": S.ErrorResponse}})
def baseline_delete(ps_id: str, baseline_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """추가 baseline 삭제(폴더는 _backup, 매칭표 draft). 첫 baseline·남은 추가 baseline이 1개면 409."""
    return bl_svc.delete_baseline(get_ctx(request), principal, ps_id, baseline_id, request_id(request), client_ip(request))


@router.post("/param-sets/{ps_id}/remap", response_model=S.NativeAccepted, status_code=202, responses=ERR)
def param_map_remap(ps_id: str, body: S.ParamMapRemapRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """매칭표만 다시 만든다(PARAM_SET_NATIVE mode remap: BL_MAP·NP_REGISTER만, 서명 같은 행 결정 승계)."""
    return bl_svc.remap(get_ctx(request), principal, ps_id, body, request_id(request), client_ip(request))


@router.get("/param-sets/{ps_id}/param-map", response_model=S.ParamMap, responses=ERR)
def param_map_get(ps_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """다중 baseline 매칭표(제안·결정·확정 상태·확정 전 필수 결정 행)."""
    return bl_svc.get_map(get_ctx(request), ps_id)


@router.put("/param-sets/{ps_id}/param-map", response_model=S.ParamMap, responses={**ERR, 403: {"model": S.ErrorResponse}})
def param_map_put(ps_id: str, body: S.ParamMapUpdate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """행별 decision 저장(proposed·signature 불변). 확정 상태면 draft로 되돌린다. 충돌 422 PARAM_NAME_CONFLICT."""
    return bl_svc.put_map(get_ctx(request), principal, ps_id, body, request_id(request), client_ip(request))


@router.post("/param-sets/{ps_id}/param-map/confirm", response_model=S.ParamMap, responses={**ERR, 403: {"model": S.ErrorResponse}})
def param_map_confirm(ps_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """매칭표 확정: 추천 등의 미결정 행은 accept로 기록, check 등급·needs_review 행은 명시 결정 필수(없으면 422 GEOM_INPUT_INVALID)."""
    return bl_svc.confirm_map(get_ctx(request), principal, ps_id, request_id(request), client_ip(request))


# ---- 템플릿 변수 정의(Native·Altair 전체 tpl; native-vars.md §6.1, altair-vars.md §6, MCP 표기 §6.6) ----
_VARS_GET_MCP = {"tool": "get_native_vars", "risk": "read", "confirm": "never", "version": 1,
                 "summary_en": "Template variable definition for Native and Altair (full tpl) templates (used vars, ranges, pool, training range)",
                 "summary_ko": "템플릿 변수 정의 조회 — Native·Altair(전체 tpl) 공통(사용 변수·범위·풀·학습 범위)"}


@router.get("/param-sets/{ps_id}/variables", response_model=S.NativeVars, responses=ERR, openapi_extra={"x-mcp": _VARS_GET_MCP})
def native_vars_get(
        request: Request, ps_id: str = Path(description="파라미터 세트(템플릿) id — Native 또는 Altair", examples=["0b9f6f3e-2d3a-4c5e-9a41-5b1c2d3e4f50"]),
        model_id: str | None = Query(default=None, description="학습 범위를 보려는 같은 Study의 모델 id(생략 = 학습 범위 없음)",
                                     examples=["7c1e0d52-8a3b-4f6d-b2c9-1e4a5f6b7c80"]),
        revision: int | None = Query(default=None, ge=0, le=100000, description="특정 리비전의 변수 목록만 보려면 리비전 번호[번](0 = 등록 정의, 생략 = 현재)",
                                     examples=[2]),
        _p: Principal = Depends(get_principal)) -> dict:
    """템플릿(④ 파라미터 세트)의 변수 정의를 조회한다 — Native와 Altair(전체 tpl) 모두. 쓰는 변수·하한·상한(`variables`), 고를 수 있는 전체 변수(`pool`:
    Native = 종류·공칭·기본 범위·모핑 가능 범위·양면 접촉 여부, Altair = tpl 선언 파라미터의 공칭·기본 범위·정수 형식 여부), 리비전 이력을 돌려준다.
    `model_id`를 주면 그 모델의 학습 범위(`train`)와 범위를 알 수 없을 때의 안내(`notes`)가 함께 온다. `engine`이 altair이고 옛 부분 tpl이면
    `editable=false`, `reason=TPL_SCOPE_PARTIAL`(①-2에서 tpl을 다시 생성해 새 템플릿으로 등록). 읽기 전용이며 부작용이 없다.
    오류: 404 NOT_FOUND(세트·모델)·NATIVE_VARS_REVISION_NOT_FOUND."""
    return vars_svc.get_variables(get_ctx(request), ps_id, model_id, revision)


@router.put("/param-sets/{ps_id}/variables", response_model=S.NativeVars, responses={**ERR, 403: {"model": S.ErrorResponse}},
            openapi_extra={"x-mcp": {"exclude": "웹 전용 편집"}})
def native_vars_put(ps_id: str, body: S.NativeVarsUpdate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """세트 변수 정의 저장(형상 행 전체 교체, 리비전 기록). base_revision이 현재 리비전과 다르면 409 NATIVE_VARS_CONFLICT.
    422 NATIVE_VARS_INVALID(problems: VAR_UNKNOWN·VAR_DUPLICATE·VAR_RANGE_INVALID·VARS_EMPTY), 409 NATIVE_VARS_MULTI_UNSUPPORTED·NATIVE_VARS_GEOMETRY_OFF.
    경고(모핑 가능 범위 밖·공칭 밖·양면 접촉)는 응답 `warnings`(저장은 됨). Altair는 전체 tpl 세트만 저장할 수 있고(부분 tpl = 422 TPL_SCOPE_PARTIAL),
    정수 형식 파라미터의 범위는 정수여야 한다(VAR_RANGE_INVALID)."""
    return vars_svc.put_variables(get_ctx(request), principal, ps_id, body, request_id(request), client_ip(request))
