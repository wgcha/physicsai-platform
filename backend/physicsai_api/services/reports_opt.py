"""⑥ 최적화 보고서 원천(upload-report.md §9.3.3): 내장 `GET /surrogate-opts/{id}` 상세(스냅숏 우선 변수 범위 포함)·레거시 `GET /optimizations/{id}`(+결과 표).

기존 서비스 함수만 호출한다(읽기 전용). 컨투어 그림은 기존 캡처 PNG 산출물 경로만 모은다(파일을 읽는 것은 렌더러의 크기 상한 아래).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import optimizations as opt_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import feature_status

from ..auth import Principal
from ..context import AppContext
from . import contour_capture as cc_svc
from . import reports_common as rc
from . import stage5_optimize as legacy_svc
from . import surrogate_opts as so_svc

log = logging.getLogger(__name__)
MAX_FINAL_VIEWS = 6  # 기준안·최적안 각각 방향 수 상한(그림 개수는 렌더러가 report.max_images로 다시 막는다)


def _not_ready(what: str) -> DomainError:
    return DomainError("REPORT_NOT_READY", f"{what}이(가) 아직 끝나지 않았습니다 — 끝난 뒤 받으세요", status=409)


def surrogate_input(ctx: AppContext, principal: Principal, opt_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        o = so_svc._require_opt(conn, opt_id)  # 404 SURROGATE_OPT_NOT_FOUND
        if o["status"] in so_repo.ACTIVE:
            raise _not_ready(f"내장 최적화 {so_repo.opt_label(o['opt_no'])}")
        study = rc.require_study(conn, o["study_id"])
        ps = rc.load_param_set(conn, o["param_set_id"])
        model = rc.model_info(conn, study, o["model_id"])
        origins = rc.origins(ctx, conn, study["id"], [("파라미터 세트 입력 경로", (ps or {}).get("source_path")), ("모델 경로", model.get("source_path"))])
    detail = so_svc.get_opt(ctx, principal, opt_id)
    return {"study": rc.study_info(study), "generated_by": principal.display_name, "detail": detail,
            "engine": rc.engine_info(ctx, ps), "param_set": {**rc.param_set_info(ps, o["input_kind"]), **(detail.get("param_set") or {})},
            "model": model or detail.get("model"), "origins": origins, "images": _final_images(ctx, principal, detail)}


def _final_images(ctx: AppContext, principal: Principal, detail: dict[str, Any]) -> list[dict[str, Any]]:
    """⑥ 마무리 캡처(기준안 doe 1·최적안 doe 2)의 기존 컨투어 PNG 경로. 캡처가 없거나 파일이 없으면 빈 목록."""
    fin = detail.get("final") or {}
    out: list[dict[str, Any]] = []
    for key, noun in (("baseline", "기준안"), ("best", "최적안")):
        run = fin.get(key) or {}
        jid = run.get("job_id")
        if not jid:
            continue
        try:
            media = cc_svc.job_media(ctx, principal, jid)
            for item in (media.get("items") or [])[:MAX_FINAL_VIEWS]:
                f = cc_svc.media_file(ctx, item["image"]["artifact_id"])
                if f["content_type"] == "image/png" and os.path.isfile(f["path"]):
                    out.append({"label": f"{noun} · {item.get('label') or item.get('view')}", "path": f["path"]})
        except DomainError:
            continue
        except OSError:
            log.debug("보고서 컨투어 이미지 확인 실패", exc_info=True)
    return out


# ---- 레거시(HyperStudy) -----------------------------------------------------------------------------------


def legacy_enabled(ctx: AppContext) -> bool:
    return bool(feature_status(ctx.settings, ctx.hpc.availability().configured).get("optimize", {}).get("enabled"))


def legacy_input(ctx: AppContext, principal: Principal, opt_id: str) -> dict[str, Any]:
    if not legacy_enabled(ctx):  # opt-native §4.1: HyperStudy 미설정이면 레거시 최적화는 화면·보고서 모두 없음
        raise DomainError("REPORT_TARGET_UNKNOWN", "HyperStudy(레거시) 최적화가 설정되지 않은 서버입니다", status=404)
    opt = legacy_svc.get_opt(ctx, opt_id)  # 404 NOT_FOUND
    if opt["status"] == "RUNNING":
        raise _not_ready("HyperStudy 최적화")
    with ctx.engine.connect() as conn:
        study = rc.require_study(conn, opt["study_id"])
        ps = rc.load_param_set(conn, opt["param_set_id"])
        model = rc.model_info(conn, study, opt["model_id"])
        o = opt_repo.get_opt(conn, opt_id)
        origins = rc.origins(ctx, conn, study["id"], [("파라미터 세트 입력 경로", (ps or {}).get("source_path")), ("모델 경로", model.get("source_path"))])
        art = artifacts_repo.get(conn, opt["summary_artifact_id"]) if opt.get("summary_artifact_id") else None
    table = None
    if art is not None and o is not None:
        data = legacy_svc._read_artifact_json(ctx, study, art)
        table = _as_table(data)
    return {"study": rc.study_info(study), "generated_by": principal.display_name, "opt": opt, "table": table,
            "engine": rc.engine_info(ctx, ps), "param_set": rc.param_set_info(ps), "model": model or None, "origins": origins}


def _as_table(data: Any) -> dict[str, Any] | None:
    """summary.json(C14: csv_table `{columns, rows}` — rows는 배열 또는 열 이름 dict)."""
    if not isinstance(data, dict) or not isinstance(data.get("columns"), list) or not isinstance(data.get("rows"), list):
        return None
    cols = [str(c) for c in data["columns"]]
    rows = [list(r) if isinstance(r, (list, tuple)) else [r.get(c) if isinstance(r, dict) else None for c in cols] for r in data["rows"]]
    return {"columns": cols, "rows": rows}
