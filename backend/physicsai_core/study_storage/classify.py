"""정리 범주 분류(phase3 §5.5 SS_CLASSIFY·SC_VALIDATE): 스캔 항목 + DB 행 → 범주별 이동 후보. 순수 함수.

DB 조회는 호출자(워커 step)가 저장소로 하고 `StudyRefs`로 넘긴다. 같은 함수가 스캔 시점 분류와
정리 실행 시점 재검사에 쓰인다(조건이 바뀐 항목은 후보에서 빠진다).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..job_types import job_label
from ..state_machine import TERMINAL
from .categories import CATEGORY_KEYS, CATEGORY_LABELS, is_protected

PREVIEW_TYPES = ("CU_H3D_PREVIEW", "CU_T01_PREVIEW")
FAILED_STATES = ("FAILED", "INTERRUPTED")
_VERIFY_RE = re.compile(r"^04_predict/([^/]+)/verify/[^/]+/input$")


@dataclass
class StudyRefs:
    """분류에 필요한 Study의 DB 행(경로·상태·ID만)."""

    jobs: list[dict[str, Any]] = field(default_factory=list)  # id, job_type, state, created_at, finished_at, retry_of_job_id, params
    datasets: list[dict[str, Any]] = field(default_factory=list)  # id, package_rel
    curations: list[dict[str, Any]] = field(default_factory=list)  # id, kind, status, output_rel
    curation_dataset_counts: dict[str, int] = field(default_factory=dict)
    models: list[dict[str, Any]] = field(default_factory=list)  # id, name, version, eval_job_id
    final_model_id: str | None = None


@dataclass(frozen=True)
class Candidate:
    category: str
    ref_id: str | None
    note: str | None


@dataclass(frozen=True)
class Rules:
    log_min_age_days: int
    keep_failed_logs: int


def _roots(jobs: list[dict[str, Any]]) -> dict[str, str]:
    by_id = {j["id"]: j for j in jobs}
    out: dict[str, str] = {}
    for j in jobs:
        cur, seen = j, set()
        while cur.get("retry_of_job_id") in by_id and cur["id"] not in seen:
            seen.add(cur["id"])
            cur = by_id[cur["retry_of_job_id"]]
        out[j["id"]] = cur["id"]
    return out


def candidates(refs: StudyRefs, rules: Rules, now: datetime, rels: Iterable[str]) -> dict[str, Candidate]:
    """rel → 후보(범주·참조 ID·비고). `rels`는 검사 대상 경로(검증 입력 attempt 폴더를 찾는 데 쓴다)."""
    jobs = refs.jobs
    root = _roots(jobs)
    chain_done: dict[str, bool] = {}
    for j in jobs:
        r = root[j["id"]]
        chain_done[r] = chain_done.get(r, True) and j["state"] in TERMINAL
    out: dict[str, Candidate] = {}

    for d in refs.datasets:
        if d.get("package_rel"):
            out[d["package_rel"].strip("/")] = Candidate("PACKAGE_PSDATA", d["id"], f"데이터셋 {d['id'][:8]}")

    models = {m["id"]: m for m in refs.models}
    final = models.get(refs.final_model_id or "")
    final_eval_root = root.get(final["eval_job_id"]) if final and final.get("eval_job_id") else None
    for r in {root[j["id"]] for j in jobs if j["job_type"] == "EVALUATE"}:
        mid = next((j["params"].get("model_id") for j in jobs if j["id"] == r), None)
        if not mid or not chain_done[r] or (mid == refs.final_model_id and r == final_eval_root):
            continue
        m = models.get(mid)
        note = f"모델 {m['name']} v{m['version']} 평가" if m else None
        out[f"03_model/score/{mid}/{r}/predictions.psdata"] = Candidate("SCORE_PREDICTIONS", mid, note)

    for c in refs.curations:
        if c["status"] == "READY" and c["kind"] == "H3D":
            n = refs.curation_dataset_counts.get(c["id"], 0)
            out[c["output_rel"].strip("/")] = Candidate(
                "CURATED_H3D", c["id"], f"데이터셋 {n}개가 이 큐레이션으로 만들어짐" if n else None)

    predict_roots = {root[j["id"]] for j in jobs if j["job_type"] == "PREDICT"}
    verify_busy = {root.get(j["params"].get("predict_job_id") or "", "") for j in jobs
                   if j["job_type"] == "PREDICT_VERIFY" and j["state"] not in TERMINAL}
    ok_predict = {r for r in predict_roots if chain_done[r] and r not in verify_busy}
    for r in ok_predict:
        out[f"04_predict/{r}/INPUT"] = Candidate("PREDICT_INPUT", r, f"예측 작업 {r[:8]}")
    for rel in rels:
        m = _VERIFY_RE.match(rel)
        if m and m.group(1) in ok_predict:
            out[rel] = Candidate("PREDICT_INPUT", m.group(1), f"예측 작업 {m.group(1)[:8]} PBS 검증 입력")

    for jt in PREVIEW_TYPES:
        mine = [j for j in jobs if j["job_type"] == jt]
        ok = [j for j in mine if j["state"] == "SUCCEEDED" and j.get("finished_at")]
        keep = root[max(ok, key=lambda j: j["finished_at"])["id"]] if ok else None
        for r in {root[j["id"]] for j in mine}:
            if chain_done[r] and r != keep:
                out[f"02_preview/{r}"] = Candidate("PREVIEW_OUTPUT", r, f"{job_label(jt)} {r[:8]}")

    latest_by_type: dict[str, dict[str, Any]] = {}
    for j in jobs:
        cur = latest_by_type.get(j["job_type"])
        if cur is None or j["created_at"] > cur["created_at"]:
            latest_by_type[j["job_type"]] = j
    keep_ids = {j["id"] for j in latest_by_type.values()}
    failed = sorted((j for j in jobs if j["state"] in FAILED_STATES and j.get("finished_at")),
                    key=lambda j: j["finished_at"], reverse=True)
    keep_ids |= {j["id"] for j in failed[: rules.keep_failed_logs]}
    min_age = timedelta(days=rules.log_min_age_days)
    for j in jobs:
        if j["state"] in TERMINAL and j.get("finished_at") and now - j["finished_at"] >= min_age and j["id"] not in keep_ids:
            out[f"logs/{j['id']}"] = Candidate("JOB_LOGS", j["id"], f"{job_label(j['job_type'])} · {j['state']}")
    return {k: v for k, v in out.items() if not is_protected(k)}


def classify(items: dict[str, list[int]], refs: StudyRefs, rules: Rules, now: datetime, max_items: int
             ) -> tuple[list[dict[str, Any]], int]:
    """스캔 항목 {rel: [bytes, files, links]} → (범주 목록 §5.6, 링크 때문에 뺀 항목 수)."""
    cands = candidates(refs, rules, now, items)
    per: dict[str, list[dict[str, Any]]] = {k: [] for k in CATEGORY_KEYS}
    link_excluded = 0
    for rel, (nbytes, nfiles, links) in items.items():
        c = cands.get(rel)
        if c is None:
            continue
        if links:
            link_excluded += 1
            continue
        per[c.category].append({"rel": rel, "bytes": nbytes, "files": nfiles, "ref_id": c.ref_id,
                                "note": (c.note or "")[:120] or None})
    out = []
    for k in CATEGORY_KEYS:
        lst = sorted(per[k], key=lambda x: (-x["bytes"], x["rel"]))
        shown = lst[:max_items]
        out.append({"key": k, "label": CATEGORY_LABELS[k], "total_bytes": sum(x["bytes"] for x in shown),
                    "item_count": len(shown), "truncated": len(lst) > max_items, "items": shown})
    return out, link_excluded
