"""step 공용 도우미."""

from __future__ import annotations

from typing import Any

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


def verify_model_integrity(ctx: Any, m: dict[str, Any]) -> tuple[str, str]:
    """사용 직전 무결성(§8.3): sha256 불일치 → 모델 INVALID + INPUT_CHANGED."""
    psmdl, pscfg = ctx.abs(m["psmdl_rel"]), ctx.abs(m["pscfg_rel"])
    ok = True
    for path, expected in ((psmdl, m["psmdl_sha256"]), (pscfg, m["pscfg_sha256"])):
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
