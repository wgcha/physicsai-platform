"""scx 모드 HPC_SUBMIT 단계 B 제출(run 순서, SUBMISSION_UNKNOWN·확정 실패 처리) — _scx에서 재노출."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories import notifications as notif_repo
from physicsai_core.errors import StepFailure
from physicsai_core.hpc.gateway import HpcGatewayError
from simdash_adapters.hpc.scx import ScxRadiossRequest

from ._scx_common import NOT_SUBMITTED_MESSAGE, UNKNOWN_MESSAGE, RunStage, SubmitResult, _mark_rows, mask

# ---------------------------------------------------------------------------
# 단계 B: 제출
# ---------------------------------------------------------------------------

def build_request(ctx: Any, gw: Any, p: RunStage) -> ScxRadiossRequest:
    cfg = gw.cfg
    names = [f["name"] for f in p.files]
    engine: list[str] = []
    if p.starter.casefold().endswith("_0000.rad"):
        want = (p.starter[: -len("_0000.rad")] + "_0001.rad").casefold()
        engine = [n for n in names if n.casefold() == want][:1]
    rest = sorted(n for n in names if n != p.starter and n not in engine) if cfg.list_additional_paths else []
    over = ctx.params.get("hpc") or {}
    ncpu = int(over.get("ncpus") or cfg.ncpu)
    return ScxRadiossRequest(
        request_id=p.request_id, input_path=f"{p.remote_dir}/{p.starter}",
        engine_paths=tuple(f"{p.remote_dir}/{n}" for n in engine), additional_paths=tuple(f"{p.remote_dir}/{n}" for n in rest),
        version=cfg.version, appliance=cfg.appliance, ncpu=ncpu, memory_gb=cfg.memory_gb, queue_type=cfg.queue_type,
        run_type=cfg.run_type, mpi=cfg.mpi, single_precision=cfg.single_precision,
        client_ref=dict(p.client_ref, hpc_job_id=p.hid),
    )


def submit_all(ctx: Any, gw: Any, plans: list[RunStage], on_row: Callable[[Any, RunStage, str], None]) -> SubmitResult:
    """run 순서대로 제출. `on_row(conn, plan, state)`는 행 상태가 QUEUED·UNKNOWN이 된 같은 트랜잭션에서 불린다(① run 연결).
    확정 실패면 형제 terminate 후 StepFailure(HPC_SUBMIT_FAILED)."""
    over = ctx.params.get("hpc") or {}
    if over.get("queue") or over.get("walltime"):
        ctx.log("scx 모드는 hpc.queue·walltime을 쓰지 않습니다(무시)")
    res = SubmitResult()
    n = len(plans)
    for k, p in enumerate(plans, 1):
        req = build_request(ctx, gw, p)

        def mark_submit(c: Any, p: RunStage = p, req: ScxRadiossRequest = req) -> None:
            row = hpc_repo.get(c, p.hid)
            staged = dict(row["staged"] or {})
            staged.update(phase="submit", request=req.to_json())
            hpc_repo.set_fields(c, p.hid, staged=staged)

        ctx.ex.db(mark_submit)
        out = gw.submit_radioss(req)
        if out.replays:
            ctx.log(f"SCX 제출 replay {out.replays}회(같은 request_id {p.request_id})")
        if out.state == "SUBMITTED":
            def ok(c: Any, p: RunStage = p, out: Any = out) -> None:
                hpc_repo.set_fields(c, p.hid, state="QUEUED", external_job_id=out.job_id, submitted_at=datetime.now().astimezone(),
                                    output_path=out.output_path, output_rel=out.output_rel)
                on_row(c, p, "QUEUED")

            ctx.ex.db(ok)
            res.submitted.append((p, str(out.job_id)))
            ctx.log(f"SCX 제출 [{k}/{n}] {p.run_key}: {out.job_id} ({gw.display(p.remote_dir)})")
            ctx.progress(k / n * 100.0, f"제출 {k}/{n}")
            continue
        if out.state == "UNKNOWN":
            def unk(c: Any, p: RunStage = p) -> None:
                hpc_repo.set_fields(c, p.hid, state="UNKNOWN", submission_unknown=True, external_job_id=None,
                                    submitted_at=datetime.now().astimezone(), error_message=UNKNOWN_MESSAGE)
                on_row(c, p, "UNKNOWN")

            ctx.ex.db(unk)
            res.unknown = p
            rest = plans[k:]
            res.not_submitted = [x.run_key for x in rest]
            _mark_rows(ctx, rest, "CANCELED", NOT_SUBMITTED_MESSAGE, phase="not_submitted")
            ctx.log(f"[SUBMISSION_UNKNOWN] {p.run_key}: {mask(ctx, out.message)} — 자동 재제출·자동 취소 없음, "
                    f"남은 run {len(rest)}개 제출 안 함")
            return res
        # 확정 실패: 행 FAILED → 이미 제출한 run terminate(phase2 §6.5) → 남은 행 정리 → 실패
        msg = mask(ctx, f"{p.run_key} SCX 제출 실패({out.code}): {out.message}")
        _mark_rows(ctx, [p], "FAILED", msg, phase="submit_failed")
        ctx.log(f"[FAIL] {msg} — 이미 제출한 {len(res.submitted)}개를 취소합니다")
        cancel_submitted(ctx, gw, res.submitted)
        _mark_rows(ctx, plans[k:], "CANCELED", "제출하지 않음(앞 run 제출 실패)", phase="not_submitted")
        raise StepFailure("HPC_SUBMIT_FAILED", msg)
    return res


def cancel_submitted(ctx: Any, gw: Any, submitted: list[tuple[RunStage, str]]) -> None:
    from physicsai_core.db.repositories import train as train_repo

    for p, ext in submitted:
        try:
            gw.cancel(ext)
        except HpcGatewayError as cexc:
            ctx.add_warning("HPC_CANCEL_FAILED", mask(ctx, f"{ext} 취소 실패: {cexc}"))

        def cancel_row(c: Any, hid: str = p.hid) -> None:
            hpc_repo.set_fields(c, hid, state="CANCELED", finished_at=datetime.now().astimezone())
            train_repo.set_run_state_by_hpc(c, hid, "SOLVE_FAILED")

        ctx.ex.db(cancel_row)


def flag_unknown(ctx: Any, res: SubmitResult) -> None:
    """결과 모름: result not_submitted·경고·attention·알림(등록자). 그 뒤 호출자가 EnterWaitingHpc."""
    if res.not_submitted:
        ctx.add_warning("SCX_NOT_SUBMITTED", f"SCX 제출 결과 모름으로 run {len(res.not_submitted)}개를 제출하지 않았습니다: "
                                             + ", ".join(res.not_submitted[:20]))
    ctx.patch_result({"not_submitted": res.not_submitted, "submission_unknown": True})

    def fn(c: Any) -> None:
        lease_repo.job_update(c, ctx.ex.job_id, ctx.ex.token, attention_code="HPC_SUBMISSION_UNKNOWN")
        notif_repo.notify_job(c, ctx.ex.job_id, "HPC_SUBMISSION_UNKNOWN")

    ctx.ex.db(fn)
