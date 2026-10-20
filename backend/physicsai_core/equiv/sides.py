"""결과 집합(side) 해석(equiv-check.md §4.1) — DB 읽기 + 파일 존재 확인만(쓰기 없음). API 미리보기·워커 EQ_PREP 공용.

side 종류: train_doe(doe_id) · predict_batch(batch_id) · fem_verify(fv_id[, attempt]) · folder(paths).
run마다 이름·번호·파라미터·성공 여부·파일 위치(h3d·T01·결과 폴더·curve.json·메시 include)를 모은다.
"""

from __future__ import annotations

import fnmatch
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ..db.repositories import fem_verifications as fv_repo
from ..db.repositories import jobs as jobs_repo
from ..db.repositories import param_sets as ps_repo
from ..db.repositories import predict_batches as pb_repo
from ..db.repositories import train as train_repo
from ..db.repositories.artifacts import get as artifact_get
from ..path_links import is_link_or_reparse
from ..stage1_train_data.doe_samples import read_samples_csv
from ..stage4_predict.nearest import integer_vars
from ..stage4_predict.run_metrics import safe_study_path

SIDE_KINDS = ("train_doe", "predict_batch", "fem_verify", "folder")
OK_TRAIN_STATES = ("COLLECTED",)
_NO_RE = re.compile(r"(\d+)$")
PARAMS_JSON = "params.json"


@dataclass
class Run:
    name: str
    no: int | None
    ok: bool
    params: dict[str, float] | None = None
    h3d: str | None = None            # 결과 h3d 절대경로(폴더 직계에 정확히 1개일 때)
    h3d_count: int = 0
    t01: str | None = None            # T01 절대경로(정확히 1개일 때)
    t01_count: int = 0
    result_dir: str | None = None     # RESPONSES.txt·H3D_REQUESTS.txt 위치(= h3d 폴더)
    curve_json: str | None = None     # 예측 curve.json(CURVE_PICK) — 해석은 None(추출)
    mesh_inc: str | None = None       # 입력 메시 include(부피)
    state: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Side:
    kind: str
    ref: str
    label: str
    runs: list[Run] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)  # 성능 정의(템플릿 responses)
    param_set_id: str | None = None
    integer_names: list[str] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    model_id: str | None = None       # 예측 쪽: FV_CURVE 규칙 ①(데이터셋 큐레이션) 추적용

    @property
    def ok(self) -> bool:
        return not self.problems

    def ref_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "label": self.label}


def _run_no(name: str, idx: int) -> int:
    m = _NO_RE.search(name)
    return int(m.group(1)) if m else idx + 1


def _files(folder: str, pattern: str, *, recursive: bool = False) -> list[str]:
    """폴더(직계 또는 재귀, `_backup` 제외, 링크 제외)의 패턴 일치 파일(정렬)."""
    out: list[str] = []
    if not folder or not os.path.isdir(folder):
        return out
    if not recursive:
        for n in sorted(os.listdir(folder)):
            p = os.path.join(folder, n)
            if fnmatch.fnmatch(n.lower(), pattern) and os.path.isfile(p) and not is_link_or_reparse(p):
                out.append(p)
        return out
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "_backup" and not is_link_or_reparse(os.path.join(dirpath, d)))
        for n in sorted(filenames):
            p = os.path.join(dirpath, n)
            if fnmatch.fnmatch(n.lower(), pattern) and os.path.isfile(p) and not is_link_or_reparse(p):
                out.append(p)
    return out


def _fill_results(run: Run, folder: str | None, *, recursive: bool = False) -> None:
    if not folder:
        return
    h3ds = _files(folder, "*.h3d", recursive=recursive)
    t01s = _files(folder, "*t01", recursive=recursive)
    run.h3d_count, run.t01_count = len(h3ds), len(t01s)
    if len(h3ds) == 1:
        run.h3d = h3ds[0]
        run.result_dir = os.path.dirname(h3ds[0])
    elif h3ds:
        run.result_dir = os.path.dirname(h3ds[0])
    if len(t01s) == 1:
        run.t01 = t01s[0]


def _mesh_in(folder: str | None, mesh_name: str) -> str | None:
    if not folder or not os.path.isdir(folder):
        return None
    for n in os.listdir(folder):
        if n.lower() == mesh_name.lower():
            p = os.path.join(folder, n)
            return p if os.path.isfile(p) and not is_link_or_reparse(p) else None
    for sub in ("m_3", "m_2"):  # ④ 일괄 run(m_1~m_3) — 조립 입력(m_3) 또는 모핑 출력(m_2)
        p = os.path.join(folder, sub, mesh_name)
        if os.path.isfile(p) and not is_link_or_reparse(p):
            return p
    return None


def _finite(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _responses_of(conn: Any, ps: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return [dict(r) for r in ((ps or {}).get("responses") or []) if isinstance(r, Mapping)]


# ---- train_doe ------------------------------------------------------------------------------------


def _train_doe(conn: Any, settings: Any, study: Mapping[str, Any], root: str, doe_id: str) -> Side:
    d = train_repo.get_doe(conn, doe_id)
    side = Side("train_doe", doe_id, "")
    if d is None or d["study_id"] != study["id"]:
        side.problems.append({"code": "SIDE_NOT_FOUND", "message": "해석 DOE를 찾을 수 없습니다", "side": None})
        return side
    side.label = f"① {d['doe_label']}"
    if d["status"] != "READY":
        side.problems.append({"code": "SIDE_NOT_READY", "message": f"DOE {d['doe_label']}가 준비 상태가 아닙니다"})
        return side
    samples: dict[str, dict[str, float]] = {}
    sp = safe_study_path(root, d.get("samples_rel")) if d.get("samples_rel") else None
    if sp and os.path.isfile(sp):
        header, rows = read_samples_csv(sp)
        for r in rows:
            samples[r["run_key"]] = {k: float(v) for k, v in r["values"].items()}
    for p in train_repo.points(conn, doe_id):
        samples.setdefault(p["run_key"], {k: float(v) for k, v in (p.get("values") or {}).items() if _finite(v) is not None})
    snap = [p for p in (d.get("parameters_snapshot") or []) if isinstance(p, dict) and "name" in p]
    side.integer_names = list(integer_vars(snap))
    mesh_name = settings.predict.mesh_include_name
    for i, r in enumerate(train_repo.runs_for_doe(conn, doe_id)):
        run = Run(r["run_key"], _run_no(r["run_key"], i), r["state"] in OK_TRAIN_STATES, samples.get(r["run_key"]), state=r["state"])
        R = safe_study_path(root, f"01_train/results/{doe_id}/{r['run_key']}")
        _fill_results(run, R, recursive=True)
        inp = safe_study_path(root, r["input_rel"]) if r.get("input_rel") else None
        run.mesh_inc = _mesh_in(inp, mesh_name) or (_mesh_in(os.path.dirname(inp), mesh_name) if inp else None)
        side.runs.append(run)
    pss = [p for p in ps_repo.list_for_study(conn, study["id"]) if p.get("train_doe_id") == doe_id]
    ps = pss[0] if pss else ps_repo.current(conn, study["id"])
    side.param_set_id = ps["id"] if ps else None
    side.responses = _responses_of(conn, ps)
    if not side.responses:  # ①-6 응답 정의(D/responses.json)로 대신
        rj = safe_study_path(root, f"01_train/doe/{doe_id}/responses.json")
        try:
            if rj and os.path.isfile(rj):
                with open(rj, encoding="utf-8-sig") as fh:
                    side.responses = [dict(x) for x in (json.load(fh).get("responses") or []) if isinstance(x, Mapping)]
        except (OSError, ValueError):
            pass
    return side


# ---- predict_batch --------------------------------------------------------------------------------


def _predict_batch(conn: Any, settings: Any, study: Mapping[str, Any], root: str, batch_id: str) -> Side:
    from ..stage4_predict.batch_matrix import batch_label

    b = pb_repo.get(conn, batch_id)
    side = Side("predict_batch", batch_id, "")
    if b is None or b["study_id"] != study["id"]:
        side.problems.append({"code": "SIDE_NOT_FOUND", "message": "일괄 예측 배치를 찾을 수 없습니다"})
        return side
    side.label = f"④ {batch_label(b['batch_no'])}"
    if b["status"] not in ("DONE",):
        side.problems.append({"code": "SIDE_NOT_READY", "message": f"배치 {batch_label(b['batch_no'])}가 완료 상태가 아닙니다"})
        return side
    ps = ps_repo.get(conn, b["param_set_id"])
    side.param_set_id, side.model_id = b["param_set_id"], b["model_id"]
    side.responses = _responses_of(conn, ps)
    side.integer_names = list(integer_vars(list((ps or {}).get("parameters") or [])))
    mesh_name = settings.predict.mesh_include_name
    B = safe_study_path(root, b["dir_rel"])
    for r in pb_repo.runs_with_jobs(conn, batch_id):
        job = jobs_repo.get_job(conn, r["predict_job_id"]) if r.get("predict_job_id") else None
        ok = bool(job) and job["state"] == "SUCCEEDED"
        run = Run(r["run_key"], int(r["doe_no"]), ok, {k: float(v) for k, v in (r.get("values") or {}).items() if _finite(v) is not None},
                  state=(job or {}).get("state") or r.get("gen_state"))
        res = (job or {}).get("result") or {}
        pred = res.get("pred_h3d_rel")
        if isinstance(pred, str) and pred:
            p = safe_study_path(root, pred)
            if p and os.path.isfile(p):
                run.h3d, run.h3d_count, run.result_dir = p, 1, os.path.dirname(p)
        aid = res.get("curve_artifact_id")
        a = artifact_get(conn, aid) if isinstance(aid, str) else None
        cp = safe_study_path(root, (a or {}).get("rel_path")) if a else None
        run.curve_json = cp if cp and os.path.isfile(cp) else None
        run_dir = os.path.join(B, r["run_key"]) if B else None
        run.mesh_inc = _mesh_in(run_dir, mesh_name)
        side.runs.append(run)
    return side


# ---- fem_verify -----------------------------------------------------------------------------------


def _fem_verify(conn: Any, settings: Any, study: Mapping[str, Any], root: str, fv_id: str, attempt: int | None) -> Side:
    r = fv_repo.get(conn, fv_id)
    side = Side("fem_verify", fv_id, "")
    if r is None or r["study_id"] != study["id"]:
        side.problems.append({"code": "SIDE_NOT_FOUND", "message": "FEM 검증을 찾을 수 없습니다"})
        return side
    lab = fv_repo.label(int(r["fv_no"]))
    side.label = f"FEM 검증 {lab}"
    if r["status"] != "DONE":
        side.problems.append({"code": "SIDE_NOT_READY", "message": f"FEM 검증 {lab}이 완료 상태가 아닙니다"})
        return side
    n = int(attempt or r.get("attempt_no") or 1)
    A = safe_study_path(root, f"{r['dir_rel']}/a{n}")
    run = Run(lab, int(r["fv_no"]), True, None, state="DONE")
    _fill_results(run, os.path.join(A, "result") if A else None)
    run.mesh_inc = _mesh_in(os.path.join(A, "input") if A else None, settings.predict.mesh_include_name) or \
        _mesh_in(os.path.join(A, "mesh") if A else None, settings.predict.mesh_include_name)
    side.runs.append(run)
    ps = ps_repo.get(conn, r["param_set_id"]) if r.get("param_set_id") else None
    if ps is None and r.get("predict_job_id"):
        pj = jobs_repo.get_job(conn, r["predict_job_id"]) or {}
        psid = (pj.get("result") or {}).get("param_set_id") or (pj.get("params") or {}).get("param_set_id")
        ps = ps_repo.get(conn, psid) if psid else None
    side.param_set_id, side.model_id = (ps or {}).get("id"), r.get("model_id")
    side.responses = _responses_of(conn, ps)
    return side


# ---- folder ---------------------------------------------------------------------------------------


def _folder(conn: Any, settings: Any, study: Mapping[str, Any], paths: Sequence[str]) -> Side:
    from ..stage4_predict.fem_assembly import check_custom_path
    from ..paths import PathError

    side = Side("folder", "folder", f"폴더 {len(paths)}개")
    seen: set[str] = set()
    for i, raw in enumerate(paths):
        try:
            p, _where = check_custom_path(raw, settings)
        except PathError as exc:
            side.problems.append({"code": "FOLDER_OUTSIDE_ROOTS" if exc.code == "PATH_OUTSIDE_ROOT" else exc.code,
                                  "message": f"{raw}: {exc.message}"})
            continue
        if not os.path.isdir(p) or is_link_or_reparse(p):
            side.problems.append({"code": "SIDE_NOT_FOUND", "message": f"폴더가 없거나 링크입니다: {raw}"})
            continue
        name = os.path.basename(os.path.normpath(p))
        if name in seen:
            side.problems.append({"code": "SIDE_NOT_READY", "message": f"폴더 이름이 중복됩니다(run 이름 = 폴더 이름): {name}"})
            continue
        seen.add(name)
        run = Run(name, _run_no(name, i), True, None, state="FOLDER")
        _fill_results(run, p)
        if run.h3d_count != 1 or run.t01_count > 1:
            side.warnings.append({"code": "FOLDER_FILES", "message": f"{name}: h3d {run.h3d_count}개·T01 {run.t01_count}개(각 정확히 1개여야 값을 읽습니다)"})
        pj = os.path.join(p, PARAMS_JSON)
        if os.path.isfile(pj) and not is_link_or_reparse(pj):
            try:
                with open(pj, encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                if isinstance(data, Mapping):
                    run.params = {str(k): float(v) for k, v in data.items() if _finite(v) is not None}
            except (OSError, ValueError):
                side.warnings.append({"code": "FOLDER_PARAMS", "message": f"{name}: params.json을 읽을 수 없습니다"})
        run.mesh_inc = _mesh_in(p, settings.predict.mesh_include_name)
        side.runs.append(run)
    ps = ps_repo.current(conn, study["id"])
    side.param_set_id = ps["id"] if ps else None
    side.responses = _responses_of(conn, ps)
    return side


# ---- 진입점 ---------------------------------------------------------------------------------------


def resolve_side(conn: Any, settings: Any, study: Mapping[str, Any], root: str, ref: Mapping[str, Any]) -> Side:
    """side 요청 `{kind, doe_id|batch_id|fv_id(+attempt)|paths, label?}` → Side(problems가 비면 사용 가능)."""
    kind = ref.get("kind")
    if kind == "train_doe":
        side = _train_doe(conn, settings, study, root, str(ref.get("doe_id") or ""))
    elif kind == "predict_batch":
        side = _predict_batch(conn, settings, study, root, str(ref.get("batch_id") or ""))
    elif kind == "fem_verify":
        side = _fem_verify(conn, settings, study, root, str(ref.get("fv_id") or ""), ref.get("attempt"))
    elif kind == "folder":
        side = _folder(conn, settings, study, [str(p) for p in (ref.get("paths") or [])])
    else:
        side = Side(str(kind), "", "")
        side.problems.append({"code": "SIDE_NOT_FOUND", "message": "결과 집합 종류는 train_doe | predict_batch | fem_verify | folder 중 하나입니다"})
    if ref.get("label"):
        side.label = str(ref["label"])[:120]
    if not side.problems and not side.runs:
        side.problems.append({"code": "SIDE_NOT_READY", "message": f"{side.label}: run이 없습니다"})
    return side


def runs_for_pairing(side: Side) -> list[dict[str, Any]]:
    return [{"name": r.name, "no": r.no, "params": r.params, "ok": r.ok} for r in side.runs]
