"""작업 대기열 분류(job-queues.md §3): step 자원 종류·초기 대기열·건너뛰기 판정·구간 목록.

규칙은 이 파일 한 곳에 둔다(API·워커·migration 시험이 같은 함수를 쓴다). 순수 함수 — DB·설정 파일을 읽지 않고,
현장 보정(`worker.queues.step_resource`)은 호출자가 dict로 넘긴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .job_types import JOB_TYPES, RES_CPU, RES_GPU, RES_NONE, StepDef

CPU, GPU, LIGHT, PREVIEW = "CPU", "GPU", "LIGHT", "PREVIEW"
LANES = (CPU, GPU, LIGHT, PREVIEW)
# 구간 전환 대상(슬롯을 쥐는) 대기열. LIGHT·PREVIEW는 기존 레인 그대로(JQ-8)
SLOT_LANES = (CPU, GPU)
# 짧은 INTERNAL + GPU step 1개 + 짧은 INTERNAL로만 된 종류는 GPU로 시작한다(전환 2회 절약, §3.3)
GPU_START_TYPES = frozenset({"EVALUATE", "OPTIMIZE"})
# 슬롯이 필요 없는 step 종류(HPC 대기·회수 — 기존 규칙)
_SLOTLESS_KINDS = ("HPC_WAIT", "COLLECT")
_RESOURCE_KINDS = ("LOCAL", "HPC_SUBMIT")


def lane_of_res(res: str) -> str:
    """step 자원 종류(cpu|gpu) → 대기열 이름."""
    return GPU if res == RES_GPU else CPU


def res_of_lane(lane: str) -> str:
    return RES_GPU if lane == GPU else RES_CPU


def step_res(step: StepDef, overrides: Mapping[str, str] | None = None) -> str:
    """step의 자원 종류 cpu|gpu|none. none = 중립(INTERNAL — 지금 쥔 슬롯) 또는 슬롯 없음(HPC_WAIT·COLLECT).
    `overrides`(worker.queues.step_resource)는 LOCAL step에만 적용한다(설정 검증이 HPC_* 키를 거부)."""
    if step.kind in _SLOTLESS_KINDS or step.kind not in _RESOURCE_KINDS:
        return RES_NONE
    if overrides and step.kind == "LOCAL" and step.key in overrides:
        return RES_GPU if overrides[step.key] == RES_GPU else RES_CPU
    return step.res if step.res in (RES_CPU, RES_GPU) else RES_CPU


def skip_without_slot(job_type: str, params: Mapping[str, Any] | None, step_key: str) -> bool:
    """실행 중 건너뛰기(StepSkipped)가 확실한 step이면 true — 자원 종류가 달라도 슬롯 전환을 하지 않는다(§3.3).
    prepared PREDICT(`params.input_mode == 'prepared'`)의 GEOM_UPDATE·MESH만 해당(params만 보는 순수 판정)."""
    p = params or {}
    return job_type == "PREDICT" and p.get("input_mode") == "prepared" and step_key in ("GEOM_UPDATE", "MESH")


def initial_lane(job_type: str, params: Mapping[str, Any] | None = None, resume_from_step: int | None = None,
                 overrides: Mapping[str, str] | None = None) -> str:
    """작업 생성(T1) 때 들어갈 대기열 CPU|GPU|LIGHT|PREVIEW.

    LIGHT·PREVIEW 종류는 정적 레인 그대로. 그 밖은 기본 CPU(준비·복사 INTERNAL을 GPU에서 하지 않는다) — 예외:
    ① GPU_START_TYPES(EVALUATE·OPTIMIZE)는 남은 step의 첫 자원 step이 gpu이면 GPU,
    ② 재개(resume_from_step)로 남은 첫 step 자체가 건너뛰기 아닌 gpu step이면 GPU(앞에 준비 step이 없으므로).
    """
    jt = JOB_TYPES[job_type]
    if jt.lane in (LIGHT, PREVIEW):
        return jt.lane
    first = max(1, int(resume_from_step or 1))
    pending = list(jt.steps[first - 1:])
    skipped = lambda s: skip_without_slot(job_type, params, s.key)  # noqa: E731
    resource = [s for s in pending if step_res(s, overrides) != RES_NONE and not skipped(s)]
    if job_type in GPU_START_TYPES:
        return GPU if resource and step_res(resource[0], overrides) == RES_GPU else CPU
    if first > 1 and pending and step_res(pending[0], overrides) == RES_GPU and not skipped(pending[0]):
        return GPU
    return CPU


def segments(job_type: str, overrides: Mapping[str, str] | None = None) -> list[str]:
    """job_type의 구간 흐름(소문자, 예 PREDICT = cpu·gpu·cpu). LIGHT·PREVIEW 종류는 [그 레인]."""
    jt = JOB_TYPES[job_type]
    if jt.lane in (LIGHT, PREVIEW):
        return [jt.lane.lower()]
    cur = initial_lane(job_type, None, None, overrides).lower()
    out = [cur]
    for s in jt.steps:
        r = step_res(s, overrides)
        if r != RES_NONE and r != cur:
            out.append(r)
            cur = r
    return out


def uses_gpu(job_type: str, overrides: Mapping[str, str] | None = None) -> bool:
    jt = JOB_TYPES[job_type]
    return jt.lane not in (LIGHT, PREVIEW) and any(step_res(s, overrides) == RES_GPU for s in jt.steps)


def gpu_step_keys(overrides: Mapping[str, str] | None = None) -> frozenset[str]:
    """정의된 모든 job_type의 gpu step 키(시험·migration 대조용)."""
    return frozenset(s.key for d in JOB_TYPES.values() for s in d.steps if step_res(s, overrides) == RES_GPU)


def known_local_step_keys() -> frozenset[str]:
    """`worker.queues.step_resource`로 바꿀 수 있는 키 = 알려진 LOCAL step."""
    return frozenset(s.key for d in JOB_TYPES.values() for s in d.steps if s.kind == "LOCAL")


def step_need(job_type: str, step: StepDef, params: Mapping[str, Any] | None,
              overrides: Mapping[str, str] | None = None) -> str | None:
    """이 step을 실행하려면 어느 대기열의 슬롯이 필요한가 — CPU|GPU, 중립(INTERNAL)·슬롯 없음·건너뛰기 확실이면 None.
    executor가 step 경계마다 부른다(§5 규칙 1): 지금 쥔 슬롯과 다르면 T17로 반납·재진입."""
    if skip_without_slot(job_type, params, step.key):
        return None
    r = step_res(step, overrides)
    return None if r == RES_NONE else lane_of_res(r)


def entry_lane(job_type: str, steps: list[dict[str, Any]], params: Mapping[str, Any] | None,
               overrides: Mapping[str, str] | None = None) -> str:
    """PBS 회수 뒤(T14) 다시 설 대기열: 남은(PENDING) step 중 처음 자원이 정해진 step의 대기열, 없으면(INTERNAL뿐) CPU.
    steps = job_steps 행(step_no 순)."""
    by_key = {s.key: s for s in JOB_TYPES[job_type].steps}
    for row in steps:
        sd = by_key.get(row["step_key"])
        if row["state"] != "PENDING" or sd is None:
            continue
        need = step_need(job_type, sd, params, overrides)
        if need is not None:
            return need
    return CPU
