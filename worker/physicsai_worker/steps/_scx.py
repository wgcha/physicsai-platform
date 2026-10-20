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
300줄 분할(R-B): 공용 모양·마스킹은 `_scx_common`, 단계 B 제출은 `_scx_submit`, COLLECT는 `_scx_collect`(여기서 재노출).
단계 A STAGE_IN(대기열 폴링 — `_scx.time` 시계)은 이 파일.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories.job_lease import LeaseLost
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import sha256_file
from physicsai_core.hpc.gateway import HpcGatewayError
from physicsai_core.paths import is_link_or_reparse
from simdash_adapters.hpc.scx_naming import file_name_problem, forbidden_reason, join_rel, rel_problem, sanitize_project
from ._scx_common import (  # noqa: F401 - 기존 경로 재노출
    MAX_LIST_ENTRIES,
    BATCH_FAIL,
    UNKNOWN_MESSAGE,
    NOT_SUBMITTED_MESSAGE,
    mask,
    timestamp,
    RunStage,
    SubmitResult,
    _mark_rows,
)
from ._scx_submit import build_request, submit_all, cancel_submitted, flag_unknown  # noqa: F401 - 기존 경로 재노출
from ._scx_collect import (  # noqa: F401 - 기존 경로 재노출
    CollectFail,
    _walk,
    WINDOWS_BAD_CHARS,
    _safe_target,
    _collisions,
    collect_run,
)


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
    home = gw.cfg.home_display
    for plan in plans:
        # 목록 조회 전에 먼저 검사(SPDM 루트 안·그 상위 프로젝트 폴더면 relay를 부르지 않음)
        why = forbidden_reason(join_rel(parent, plan.job_name), forbidden, base=gw.base, home_display=home)
        if why:
            raise StepFailure("SCX_PATH_NOT_ALLOWED", f"SCX 잡 폴더를 쓸 수 없습니다({why}): {gw.display(join_rel(parent, plan.job_name))}")
        try:
            name = gw.ensure_new_dir(parent, plan.job_name)
        except HpcGatewayError as exc:
            if exc.relay_code == "SCX_REMOTE_DIR_EXISTS":
                raise StepFailure("SCX_REMOTE_DIR_EXISTS", f"{plan.run_key}: {exc}") from None
            if exc.relay_code == "PATH_NOT_ALLOWED":
                raise StepFailure("SCX_PATH_NOT_ALLOWED", mask(ctx, f"{plan.run_key}: SCX 드라이브 경로 거부 — {exc}")) from None
            raise StepFailure("HPC_SUBMIT_FAILED", mask(ctx, f"{plan.run_key}: 드라이브 폴더 확인 실패 — {exc}")) from None
        rel = join_rel(parent, name)
        why = rel_problem(rel, segment_check_from=seg_from) or forbidden_reason(rel, forbidden, base=gw.base, home_display=home)
        if why:
            raise StepFailure("SCX_PATH_NOT_ALLOWED", f"SCX 잡 폴더를 쓸 수 없습니다({why}): {gw.display(rel)}")
        plan.remote_dir = rel


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
            for idx, f in enumerate(p.files, 1):
                ctx.checkpoint()

                def tick(n: int) -> None:
                    sent[0] += n
                    ctx.checkpoint()

                bid = gw.upload(os.path.join(p.input_dir, f["name"]), p.remote_dir, f["name"], f["sha256"],
                                f"{p.request_id}:f:{idx}", size=int(f["size"]), on_chunk=tick)  # 이름 대신 순번(헤더 ASCII 규칙)
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
