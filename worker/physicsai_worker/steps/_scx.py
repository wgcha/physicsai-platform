"""scx 모드 HPC_SUBMIT·COLLECT 공통(phase3 §16.4) — ① TD_SOLVE·④ PREDICT_VERIFY가 함께 쓴다. step 키는 바꾸지 않는다.

HPC_SUBMIT
  단계 A STAGE_IN(모든 run 먼저): health → run별 입력 파일 검사(패턴·링크·하위 폴더·크기) → hpc_jobs 행 삽입(SUBMITTING,
  request_id = "pai-<id>") → mkdirs·파일마다 POST /files(대시보드 업로드 대기열) → 묶음이 모두 DONE일 때까지 폴링.
  단계 B 제출(run 순서): POST /jobs/radioss(같은 request_id replay만 자동). SUBMISSION_UNKNOWN → 행 UNKNOWN·submission_unknown,
  자동 재제출·형제 취소 없음, 남은 run 제출 안 함(행 CANCELED·result not_submitted), attention·알림 HPC_SUBMISSION_UNKNOWN.
  확정 실패 → 행 FAILED + 이미 제출한 run terminate(phase2 §6.5) + HPC_SUBMIT_FAILED.
COLLECT
  SUCCEEDED 행마다 output_rel 아래를 깊이 collect_max_depth까지 목록 → collect_patterns 일치 파일을 relay 스트리밍으로
  `<result_dir>/<상대 경로>.part`에 받고 sha256 확인 → os.replace. 쓰기는 AI 루트(허용 루트) 안만, 링크·`..`·절대 거부.
드라이브는 지우거나 옮기지 않는다(클라이언트에 그런 메서드 없음). 사용자 표시 문구는 한국어, relay 문구는 마스킹 후 500자.
"""

from __future__ import annotations

import fnmatch
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories.job_lease import LeaseLost
from physicsai_core.db.repositories import notifications as notif_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import sha256_file
from physicsai_core.hpc.gateway import HpcGatewayError
from physicsai_core.masking import bundle_masker
from physicsai_core.paths import PathError, allowed_roots, assert_writable, check_user_path, is_link_or_reparse, is_under
from simdash_adapters.hpc.scx import ScxRadiossRequest
from simdash_adapters.hpc.scx_naming import file_name_problem, forbidden_reason, join_rel, rel_problem, sanitize_project

MAX_LIST_ENTRIES = 20000
BATCH_FAIL = ("CONFLICT", "FAILED", "CANCELLED", "PARTIAL")
UNKNOWN_MESSAGE = "SCX 제출 결과를 알 수 없습니다 — SCX에서 확인 필요"
NOT_SUBMITTED_MESSAGE = "제출하지 않음(앞 run의 SCX 제출 결과 모름)"


def mask(ctx_or_settings: Any, text: str) -> str:
    """relay 오류·JobInfo.error_message 마스킹(오류 묶음 규칙 — Bearer·DB 자격·비밀 값) 후 500자."""
    s = getattr(ctx_or_settings, "settings", ctx_or_settings)
    return bundle_masker(s)(str(text))[:500]


def timestamp() -> str:
    """잡 폴더 시각: HPC_SUBMIT step 시작 시 워커 현지 시각(§16.3)."""
    return datetime.now().strftime("%Y%m%dT%H%M%S")


@dataclass
class RunStage:
    """run 1개의 STAGE_IN·제출 계획."""

    run_key: str
    input_dir: str
    starter: str
    job_name: str                       # 접미 전 잡 폴더 이름(01_D-…·04_V-…)
    client_ref: dict[str, str]
    files: list[dict[str, Any]] = field(default_factory=list)  # {name, size, sha256}
    remote_dir: str = ""
    hid: str = ""
    request_id: str = ""
    batches: list[str] = field(default_factory=list)
    bytes_total: int = 0


@dataclass
class SubmitResult:
    submitted: list[tuple[RunStage, str]] = field(default_factory=list)  # (계획, 외부 잡 ID)
    unknown: RunStage | None = None
    not_submitted: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 단계 A: STAGE_IN
# ---------------------------------------------------------------------------

def check_health(ctx: Any, gw: Any) -> dict[str, Any]:
    try:
        h = gw.health()
    except HpcGatewayError as exc:
        raise StepFailure("HPC_SUBMIT_FAILED", mask(ctx, f"대시보드 SCX relay 연결 실패(UNAVAILABLE): {exc}")) from None
    if h.get("job_api") is False:
        raise StepFailure("HPC_SUBMIT_FAILED", "대시보드 어댑터에 잡 API 없음(v0.3.0 이상 필요)")
    if h.get("writes_active") is False:
        raise StepFailure("HPC_SUBMIT_FAILED", "대시보드 드라이브 쓰기 꺼짐(SIMDASH_DRIVE_WRITES_ENABLED·SPDM 루트 설정 확인)")
    return h


def _subdir_has_pattern(path: str, matches: Callable[[str], bool], depth: int = 0) -> bool:
    if depth > 4:
        return False
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return False
    for n in names:
        p = os.path.join(path, n)
        if is_link_or_reparse(p):
            continue
        if os.path.isdir(p):
            if _subdir_has_pattern(p, matches, depth + 1):
                return True
        elif matches(n):
            return True
    return False


def scan_inputs(ctx: Any, gw: Any, plan: RunStage, health: dict[str, Any]) -> None:
    """올릴 파일 = 입력 폴더 직속 정규 파일 중 stage_patterns 일치(링크·_backup 제외, 하위 폴더는 경고만). 위반 → INPUT_INVALID."""
    cfg = gw.cfg
    d = plan.input_dir
    if not os.path.isdir(d) or is_link_or_reparse(d):
        raise StepFailure("INPUT_INVALID", f"{plan.run_key}: 입력 폴더가 없습니다")
    max_file = int(health.get("max_upload_bytes") or cfg.max_stage_bytes)
    files: list[dict[str, Any]] = []
    total = 0
    sub_warned = False
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if name.casefold() == "_backup" or is_link_or_reparse(p):
            continue
        if os.path.isdir(p):
            if not sub_warned and _subdir_has_pattern(p, gw.matches_stage_pattern):
                ctx.add_warning("SCX_SUBDIR_SKIPPED", f"{plan.run_key}: 하위 폴더의 입력 파일은 올리지 않습니다({name})")
                sub_warned = True
            continue
        if not os.path.isfile(p) or not gw.matches_stage_pattern(name):
            continue
        why = file_name_problem(name)
        if why:
            raise StepFailure("INPUT_INVALID", f"{plan.run_key}: 파일 이름을 올릴 수 없습니다({why}): {name[:80]}")
        size = os.path.getsize(p)
        if size > max_file:
            raise StepFailure("INPUT_INVALID", f"{plan.run_key}: 파일이 업로드 상한({max_file} B)을 넘습니다: {name}")
        total += size
        if total > cfg.max_stage_bytes:
            raise StepFailure("INPUT_INVALID", f"{plan.run_key}: 올릴 파일 합계가 hpc.scx.max_stage_bytes를 넘습니다")
        files.append({"name": name, "size": size, "sha256": sha256_file(p, checkpoint=ctx.checkpoint)})
    if not any(f["name"] == plan.starter for f in files):
        raise StepFailure("INPUT_INVALID", f"{plan.run_key}: starter 파일이 올릴 목록에 없습니다: {plan.starter or '(없음)'}")
    plan.files = files
    plan.bytes_total = total


def plan_remote_dirs(ctx: Any, gw: Any, plans: list[RunStage], health: dict[str, Any]) -> None:
    """잡 폴더 = <기준>/<프로젝트>/<잡 이름>(항상 새 폴더 — 있으면 _2…_9). SPDM 루트·형식 위반은 작업 실패."""
    project = sanitize_project(ctx.study["folder_name"])
    parent = join_rel(gw.base, project)
    forbidden = list(health.get("forbidden_prefixes") or [])
    seg_from = len(gw.base.split("/")) if gw.base else 0
    for plan in plans:
        try:
            name = gw.ensure_new_dir(parent, plan.job_name)
        except HpcGatewayError as exc:
            if exc.relay_code == "SCX_REMOTE_DIR_EXISTS":
                raise StepFailure("SCX_REMOTE_DIR_EXISTS", f"{plan.run_key}: {exc}") from None
            if exc.relay_code == "PATH_NOT_ALLOWED":
                raise StepFailure("SCX_PATH_NOT_ALLOWED", mask(ctx, f"{plan.run_key}: SCX 드라이브 경로 거부 — {exc}")) from None
            raise StepFailure("HPC_SUBMIT_FAILED", mask(ctx, f"{plan.run_key}: 드라이브 폴더 확인 실패 — {exc}")) from None
        rel = join_rel(parent, name)
        why = rel_problem(rel, segment_check_from=seg_from) or forbidden_reason(rel, forbidden, base=gw.base)
        if why:
            raise StepFailure("SCX_PATH_NOT_ALLOWED", f"SCX 잡 폴더를 쓸 수 없습니다({why}): {gw.display(rel)}")
        plan.remote_dir = rel


def _mark_rows(ctx: Any, plans: list[RunStage], state: str, message: str, phase: str | None = None) -> None:
    def fn(c: Any) -> None:
        for p in plans:
            if not p.hid:
                continue
            row = hpc_repo.get(c, p.hid)
            if row is None or row["state"] != "SUBMITTING":
                continue
            staged = dict(row["staged"] or {})
            if phase:
                staged["phase"] = phase
            hpc_repo.set_fields(c, p.hid, state=state, error_message=message[:500], staged=staged,
                                finished_at=datetime.now().astimezone())

    ctx.ex.db(fn)


def stage_in(ctx: Any, gw: Any, plans: list[RunStage], attempt_no: int) -> None:
    """행 삽입 → mkdirs·업로드 → 묶음 DONE까지 폴링. 실패면 이 step의 행을 FAILED로 두고 SCX_STAGE_IN_FAILED(제출 0건)."""
    for p in plans:
        staged = {"phase": "stage_in", "files": p.files, "display_dir": gw.display(p.remote_dir)}

        def ins(c: Any, p: RunStage = p, staged: dict[str, Any] = staged) -> tuple[str, str]:
            return hpc_repo.insert_submitting(c, job_id=ctx.ex.job_id, step_id=ctx.step["id"], run_key=p.run_key,
                                              attempt_no=attempt_no, remote_dir=p.remote_dir, staged=staged)

        p.hid, p.request_id = ctx.ex.db(ins)
    total = sum(p.bytes_total for p in plans) or 1
    sent = [0]
    try:
        for p in plans:
            gw.mkdirs(p.remote_dir, f"{p.request_id}:mkdir")
            for f in p.files:
                ctx.checkpoint()

                def tick(n: int) -> None:
                    sent[0] += n
                    ctx.checkpoint()

                bid = gw.upload(os.path.join(p.input_dir, f["name"]), p.remote_dir, f["name"], f["sha256"],
                                f"{p.request_id}:f:{f['name']}", size=int(f["size"]), on_chunk=tick)
                p.batches.append(bid)
            ctx.log(f"SCX 업로드 요청 {p.run_key}: {len(p.files)}개 → {gw.display(p.remote_dir)}")
        _wait_batches(ctx, gw, plans, total)
    except StepFailure as exc:
        _mark_rows(ctx, plans, "FAILED", exc.message, phase="stage_in_failed")
        raise
    except HpcGatewayError as exc:
        msg = mask(ctx, f"SCX 업로드 실패: {exc}")
        _mark_rows(ctx, plans, "FAILED", msg, phase="stage_in_failed")
        raise StepFailure("SCX_STAGE_IN_FAILED", msg) from None
    except LeaseLost:
        raise  # lease 상실: 쓰기 없이 그대로(housekeeping이 phase=stage_in 행을 FAILED로 정리)
    except Exception:
        # 취소·내부 오류: 아직 아무것도 제출하지 않았다(취소할 것 없음)
        _mark_rows(ctx, plans, "FAILED", "업로드 중 중단 — 제출하지 않음", phase="stage_in_failed")
        raise


def _wait_batches(ctx: Any, gw: Any, plans: list[RunStage], total: int) -> None:
    cfg = gw.cfg
    pending = {bid: p for p in plans for bid in p.batches}
    done_bytes: dict[str, int] = {}
    paused_logged = False
    started = time.monotonic()
    while pending:
        for bid, p in list(pending.items()):
            b = gw.batch(bid)
            st = b.get("state")
            done_bytes[bid] = sum(int(it.get("size") or 0) for it in b.get("items") or [] if it.get("state") == "DONE")
            if st == "DONE":
                pending.pop(bid)
            elif st in BATCH_FAIL:
                bad = next((it for it in b.get("items") or [] if it.get("state") not in ("DONE", "PENDING", "RUNNING")), {})
                why = bad.get("error_message") or bad.get("error_code") or st
                raise StepFailure("SCX_STAGE_IN_FAILED",
                                  mask(ctx, f"{p.run_key}: SCX 업로드 실패({st}) {bad.get('target') or ''} — {why}"))
            elif st == "PAUSED" and not paused_logged:
                ctx.log("SCX 업로드 대기열 일시정지(대시보드 재로그인 필요) — 계속 기다립니다")
                paused_logged = True
        ctx.progress(min(99.0, 100.0 * sum(done_bytes.values()) / total), f"SCX 업로드 {len(pending)}건 대기")
        if not pending:
            break
        if time.monotonic() - started > cfg.stage_timeout_s:
            raise StepFailure("SCX_STAGE_IN_FAILED", f"SCX 업로드가 {int(cfg.stage_timeout_s)}초 안에 끝나지 않았습니다")
        _sleep_checked(ctx, float(cfg.stage_poll_s))


def _sleep_checked(ctx: Any, seconds: float) -> None:
    end = time.monotonic() + seconds
    while True:
        ctx.checkpoint()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.5, left))


# ---------------------------------------------------------------------------
# 단계 B: 제출
# ---------------------------------------------------------------------------

def build_request(ctx: Any, gw: Any, p: RunStage) -> ScxRadiossRequest:
    cfg = gw.cfg
    names = [f["name"] for f in p.files]
    engine: list[str] = []
    if p.starter.endswith("_0000.rad"):
        eng = p.starter[: -len("_0000.rad")] + "_0001.rad"
        if eng in names:
            engine = [eng]
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


# ---------------------------------------------------------------------------
# COLLECT
# ---------------------------------------------------------------------------

class CollectFail(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _walk(gw: Any, root: str, max_depth: int) -> list[tuple[str, int]]:
    """output_rel 아래 파일 (root 기준 상대 경로, 크기). 깊이 0 = 직속만, 항목 합계 ≤ 20000."""
    out: list[tuple[str, int]] = []
    count = 0
    stack: list[tuple[str, str, int]] = [(root, "", 0)]
    while stack:
        rel, sub, depth = stack.pop()
        for e in gw.list(rel, MAX_LIST_ENTRIES):
            count += 1
            if count > MAX_LIST_ENTRIES:
                raise CollectFail("COLLECT_FAILED", f"결과 폴더 항목이 {MAX_LIST_ENTRIES}개를 넘습니다")
            name = str(e.get("name") or "")
            if file_name_problem(name):
                continue
            child_sub = f"{sub}/{name}" if sub else name
            if e.get("kind") == "dir":
                if depth < max_depth:
                    stack.append((f"{rel}/{name}", child_sub, depth + 1))
            elif e.get("kind") == "file":
                out.append((child_sub, int(e.get("size") or 0)))
    return sorted(out)


def _safe_target(ctx: Any, result_dir: str, rel: str) -> str:
    parts = rel.split("/")
    if any(p in ("", ".", "..") or file_name_problem(p) for p in parts):
        raise CollectFail("PATH_UNSAFE", f"결과 파일 경로를 쓸 수 없습니다: {rel[:200]}")
    dst = os.path.join(result_dir, *parts)
    try:
        check_user_path(dst, allowed_roots(ctx.settings, imports=False), expect="file", must_exist=False)
        assert_writable(dst)
    except PathError as exc:
        raise CollectFail("PATH_UNSAFE", f"결과 파일을 AI 루트에 쓸 수 없습니다({exc.message}): {rel[:200]}") from None
    except StepFailure as exc:
        raise CollectFail("PATH_UNSAFE", f"{exc.message}: {rel[:200]}") from None
    if not is_under(os.path.realpath(dst), os.path.realpath(result_dir)):
        raise CollectFail("PATH_UNSAFE", f"결과 폴더 밖 경로입니다: {rel[:200]}")
    return dst


def collect_run(ctx: Any, gw: Any, row: dict[str, Any], result_dir: str, health_max: int | None) -> list[str]:
    """SUCCEEDED 행 1개 회수. 받은 상대 경로 목록. 실패면 CollectFail(그 run만 회수 실패)."""
    s = ctx.settings
    out_rel = row.get("output_rel")
    if not out_rel and row.get("external_job_id"):
        try:
            st = gw.status(row["external_job_id"])
            out_rel = st.output_rel
            if out_rel:
                ctx.ex.db(lambda c: hpc_repo.set_fields(c, row["id"], output_rel=out_rel, output_path=st.output_path))
        except HpcGatewayError as exc:
            raise CollectFail("COLLECT_FAILED", mask(ctx, f"SCX 잡 상태를 다시 받지 못했습니다: {exc}")) from None
    if not out_rel:
        raise CollectFail("SCX_OUTPUT_MISSING", "SCX 결과 위치 없음")
    if rel_problem(out_rel):
        raise CollectFail("SCX_OUTPUT_MISSING", f"SCX 결과 위치 형식 오류: {out_rel[:200]}")
    pats = s.hpc.transfer.collect_patterns
    limit = min(int(gw.cfg.max_download_bytes), int(s.hpc.transfer.max_collect_bytes),
                int(health_max) if health_max else int(gw.cfg.max_download_bytes))
    try:
        files = [(r, sz) for r, sz in _walk(gw, out_rel, int(gw.cfg.collect_max_depth))
                 if any(fnmatch.fnmatch(r.rsplit("/", 1)[-1], pat) for pat in pats)]
    except HpcGatewayError as exc:
        raise CollectFail("COLLECT_FAILED", mask(ctx, f"SCX 결과 목록 실패: {exc}")) from None
    if not files:
        raise CollectFail("COLLECT_FAILED", "결과 파일 없음")
    big = [r for r, sz in files if sz > limit]
    if big:
        raise CollectFail("COLLECT_FAILED", f"회수 파일이 상한을 넘습니다: {big[0]}")
    got: list[str] = []
    for r, _sz in files:
        dst = _safe_target(ctx, result_dir, r)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        for attempt in (1, 2):
            ctx.checkpoint()
            # `<이름>.<임의>.part`(같은 폴더) — 성공하면 os.replace, 실패·취소면 tempfile이 지운다(.part를 남기지 않음, §16.4 9)
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(dst), prefix=os.path.basename(dst) + ".", suffix=".part",
                                             delete=True, delete_on_close=False) as tf:
                tf.close()
                try:
                    gw.download(f"{out_rel}/{r}", tf.name, limit, on_chunk=lambda _n: ctx.checkpoint())
                except HpcGatewayError as exc:
                    if exc.relay_code == "HASH_MISMATCH" and attempt == 1:
                        ctx.log(f"SCX 다운로드 해시 불일치 — 1회 다시 받습니다: {r}")
                        continue
                    raise CollectFail("COLLECT_FAILED", f"SCX 다운로드 실패({r}): {mask(ctx, str(exc))}") from None
                os.replace(tf.name, dst)
            got.append(r)
            break
    return got
