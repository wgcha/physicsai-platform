"""step 공용 도우미."""

from __future__ import annotations

from typing import Any

from physicsai_core.commands import PSCFG_REQUIRED_MESSAGE, model_lacks_required_pscfg
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import sha256_file


def path_failure(exc: Any) -> StepFailure:
    return StepFailure("INPUT_INVALID", f"{getattr(exc, 'code', '')}: {getattr(exc, 'message', exc)}")


def load_model(ctx: Any, model_id: str) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        m = models_repo.get(conn, model_id)
    if m is None or m["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "모델을 찾을 수 없습니다")
    return m


def verify_model_integrity(ctx: Any, m: dict[str, Any]) -> tuple[str, str | None]:
    """사용 직전 무결성(§8.3): sha256 불일치 → 모델 INVALID + INPUT_CHANGED. pscfg는 있을 때만 확인(D3-43 선택)."""
    psmdl = ctx.abs(m["psmdl_rel"])
    pscfg = ctx.abs(m["pscfg_rel"]) if m.get("pscfg_rel") else None
    checks = [(psmdl, m["psmdl_sha256"])]
    if pscfg is not None:
        checks.append((pscfg, m["pscfg_sha256"]))
    ok = True
    for path, expected in checks:
        try:
            if sha256_file(path, ctx.checkpoint) != expected:
                ok = False
        except FileNotFoundError:
            ok = False
    if not ok:
        ctx.ex.db(lambda c: models_repo.set_values(c, m["id"], status="INVALID"))
        raise StepFailure("INPUT_CHANGED", f"등록 후 모델 파일이 바뀌었거나 없습니다: {m['name']} v{m['version']}")
    if m["status"] != "ACTIVE":
        raise StepFailure("INPUT_INVALID", "ACTIVE 모델이 아닙니다")
    return psmdl, pscfg


def model_command_values(ctx: Any, template_key: str, m: dict[str, Any]) -> dict[str, str]:
    """명령 템플릿용 모델 경로 값. pscfg 없는 모델에 {model_pscfg} 템플릿이면 INPUT_INVALID(D3-43, API 409와 같은 문구)."""
    template = getattr(ctx.settings.commands, template_key, None)
    if model_lacks_required_pscfg(template, m):
        raise StepFailure("INPUT_INVALID", PSCFG_REQUIRED_MESSAGE)
    values = {"model_psmdl": ctx.abs(m["psmdl_rel"])}
    if m.get("pscfg_rel"):
        values["model_pscfg"] = ctx.abs(m["pscfg_rel"])
    return values
