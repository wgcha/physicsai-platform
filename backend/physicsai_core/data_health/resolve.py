"""점검 대상 h3d → run 해석(data-health.md §4.1) — DB 읽기 + 파일 존재 확인만(쓰기 없음).

1. 입력 해석·h3d 수집은 DATASET_CREATE와 같다(호출자가 `collect_h3d`로 모은 목록을 넘긴다).
2. run_key 대응: 큐레이션 입력(원천 TRAIN_DOE) = `file_list.json`의 `output_rel` → `run_key`·`doe_id`(큐레이션 `source.doe_id`).
   직접 입력이 `01_train/results/<doe_id>/<run_key>/…` 아래면 경로에서(`results/` 자체면 DOE 여러 개). 그 밖 = DOE 연결 없음(제한 모드, DH-15).
3. DOE마다 `equiv.sides.resolve_side(train_doe)` 1회 → run_key로 `Run`(params·result_dir·mesh_inc/tree) 대응. 대응 못 한 h3d는 행은 남기고 ②③ NA(RUN_UNLINKED).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..db.repositories import curations as cur_repo
from ..db.repositories import jobs as jobs_repo
from ..db.repositories import train as train_repo
from ..equiv.sides import Run, Side, resolve_side
from ..path_links import is_under
from ..stage4_predict.run_metrics import safe_study_path


@dataclass
class Target:
    file_rel: str                 # 입력 루트 기준 h3d 상대경로('/') — 제외 단위(DH-10)
    h3d: str                      # 절대경로(큐레이션 입력이면 큐레이션 출력 h3d)
    study_rel: str                # Study 기준 h3d 상대경로(컨투어 캐시 조회용)
    run_key: str | None = None
    doe_id: str | None = None
    run: Run | None = None
    result_dir: str | None = None  # R(run) = 01_train/results/<doe>/<run_key> (원본 해석 출력, 재귀 탐색)
    input_dir: str | None = None   # run 입력 폴더(`/RUN` Tstop 읽기)
    unlinked: bool = False         # DOE 연결 없음·run 대응 실패 → ②③ NA(RUN_UNLINKED)


@dataclass
class RunSet:
    targets: list[Target] = field(default_factory=list)
    doe_ids: list[str] = field(default_factory=list)
    snapshots: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    sides: dict[str, Side] = field(default_factory=dict)
    responses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)   # doe_id → D/responses.json 정의(추출 때 기록된 것)
    limited: bool = False
    preview_frames: int | None = None
    warnings: list[dict[str, str]] = field(default_factory=list)


def _curation_map(root: str, cur: Mapping[str, Any]) -> tuple[str | None, dict[str, str]]:
    """큐레이션 → (doe_id | None, {abs h3d 경로(normcase) → run_key}). TRAIN_DOE 원천만 DOE 연결."""
    src = cur.get("source") or {}
    doe_id = src.get("doe_id") if src.get("kind") == "TRAIN_DOE" else None
    fl = safe_study_path(root, cur.get("file_list_rel"))
    out: dict[str, str] = {}
    if fl and os.path.isfile(fl):
        C = os.path.dirname(fl)
        try:
            with open(fl, encoding="utf-8-sig") as fh:
                items = json.load(fh)
        except (OSError, ValueError):
            items = []
        for it in items if isinstance(items, list) else []:
            if isinstance(it, Mapping) and it.get("ok") and it.get("output_rel") and it.get("run_key"):
                out[os.path.normcase(os.path.normpath(os.path.join(C, *str(it["output_rel"]).split("/"))))] = str(it["run_key"])
    return doe_id, out


def _read_responses_json(root: str, doe_id: str) -> list[dict[str, Any]]:
    p = safe_study_path(root, f"01_train/doe/{doe_id}/responses.json")
    try:
        if p and os.path.isfile(p):
            with open(p, encoding="utf-8-sig") as fh:
                return [dict(x) for x in (json.load(fh).get("responses") or []) if isinstance(x, Mapping)]
    except (OSError, ValueError, AttributeError):
        pass
    return []


def resolve_runs(conn: Any, settings: Any, study: Mapping[str, Any], root: str, input_path: str, files: Sequence[str],
                 curation_id: str | None = None) -> RunSet:
    rs = RunSet()
    results_root = os.path.join(root, "01_train", "results")
    cur_doe: str | None = None
    cur_map: dict[str, str] = {}
    if curation_id:
        cur = cur_repo.get_curation(conn, curation_id)
        if cur is not None:
            cur_doe, cur_map = _curation_map(root, cur)
            pj = jobs_repo.get_job(conn, cur["preview_job_id"]) if cur.get("preview_job_id") else None
            nts = ((pj or {}).get("result") or {}).get("num_time_step")
            rs.preview_frames = nts if isinstance(nts, int) and not isinstance(nts, bool) and nts > 0 else None
    for f in files:
        t = Target(file_rel=os.path.relpath(f, input_path).replace("\\", "/"), h3d=f,
                   study_rel=os.path.relpath(f, root).replace("\\", "/"))
        if curation_id:
            if cur_doe:
                t.doe_id, t.run_key = cur_doe, cur_map.get(os.path.normcase(os.path.normpath(f)))
        elif is_under(f, results_root):
            parts = os.path.relpath(f, results_root).replace("\\", "/").split("/")
            if len(parts) >= 3:
                t.doe_id, t.run_key = parts[0], parts[1]
        rs.targets.append(t)
    rs.doe_ids = sorted({t.doe_id for t in rs.targets if t.doe_id})
    runs_by_doe: dict[str, dict[str, Run]] = {}
    inputs_by_doe: dict[str, dict[str, str]] = {}
    for doe_id in rs.doe_ids:
        side = resolve_side(conn, settings, dict(study), root, {"kind": "train_doe", "doe_id": doe_id})
        if side.problems:
            rs.warnings.append({"code": "DH_DOE_UNAVAILABLE", "message": f"DOE {doe_id[:8]}: {side.problems[0].get('message', '')}"})
            continue
        rs.sides[doe_id] = side
        runs_by_doe[doe_id] = {r.name: r for r in side.runs}
        inputs_by_doe[doe_id] = {r["run_key"]: r.get("input_rel") for r in train_repo.runs_for_doe(conn, doe_id) if r.get("input_rel")}
        d = train_repo.get_doe(conn, doe_id) or {}
        rs.snapshots[doe_id] = [dict(p) for p in (d.get("parameters_snapshot") or []) if isinstance(p, dict) and "name" in p]
        rs.responses[doe_id] = _read_responses_json(root, doe_id)
    for t in rs.targets:
        run = runs_by_doe.get(t.doe_id or "", {}).get(t.run_key or "")
        if run is None:
            t.unlinked = True
            continue
        t.run = run
        t.result_dir = safe_study_path(root, f"01_train/results/{t.doe_id}/{t.run_key}")
        rel = inputs_by_doe[t.doe_id].get(t.run_key or "")  # type: ignore[index]
        t.input_dir = safe_study_path(root, rel) if rel else None
    rs.limited = not any(not t.unlinked for t in rs.targets)
    if rs.limited:
        rs.warnings.append({"code": "DH_NO_DOE_LINK", "message": "① 학습 DOE와 연결되지 않은 입력이라 해석 건전성·일관성만 점검합니다(파라미터·응답·메시를 알 수 없음)"})
    return rs


# ---- 보조 원천 인덱스(DB 읽기) -------------------------------------------------------------------------


def t01_curve_index(conn: Any, root: str, study_id: str) -> dict[str, str]:
    """최신 READY T01 큐레이션의 `{run_key: 곡선 JSON 절대경로}`(ok 항목만, 파일이 있을 때만). 없으면 빈 dict."""
    from ..db.repositories import data_health as dh_repo

    cur = dh_repo.latest_ready_t01(conn, study_id)
    fl = safe_study_path(root, (cur or {}).get("file_list_rel"))
    out: dict[str, str] = {}
    if not fl or not os.path.isfile(fl):
        return out
    C = os.path.dirname(fl)
    try:
        with open(fl, encoding="utf-8-sig") as fh:
            items = json.load(fh)
    except (OSError, ValueError):
        return out
    for it in items if isinstance(items, list) else []:
        if isinstance(it, Mapping) and it.get("ok") and it.get("run_key") and it.get("output_rel"):
            p = os.path.join(C, *str(it["output_rel"]).split("/"))
            if os.path.isfile(p):
                out.setdefault(str(it["run_key"]), p)
    return out


def contour_manifests(conn: Any, settings: Any, root: str, study_id: str, targets: Sequence[Target]) -> dict[str, str]:
    """프레임 원천 ① — `{Study 기준 h3d 상대경로: manifest 절대경로}`. 3D 컨투어 캐시(DONE·OK·SOLVER_H3D)의 행 중 키에 들어 있는
    h3d 크기·mtime_ns가 지금 파일과 같은 것만(키를 지금 파일 값으로 다시 계산해 행의 키와 같을 때). 설정이 바뀌어 키가 달라지면 무시(③ 조회로 대체)."""
    from ..config.schema_capture import effective_extract_tcl
    from ..contour3d.settings import OUT_MANIFEST, cache_key, limits_of, tcl_hash
    from ..db.repositories import data_health as dh_repo
    from ..geometry.view import CONTOUR_CACHE, cache_rel

    want = {t.study_rel: t for t in targets}
    c3 = settings.contour3d
    out: dict[str, str] = {}
    for row in dh_repo.contour_done_rows(conn, study_id):
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
        prm = (job or {}).get("params") or {}
        rel = prm.get("h3d_rel")
        t = want.get(rel) if isinstance(rel, str) else None
        if t is None or rel in out:
            continue
        try:
            st = os.stat(t.h3d)
        except OSError:
            continue
        disp = prm.get("display") or {}
        key = cache_key(source_kind="SOLVER_H3D", source_id=f"rel:{rel}", h3d_size=st.st_size, h3d_mtime_ns=st.st_mtime_ns, display=disp,
                        max_frames=int(prm.get("max_frames") or 0), include_disp=bool(prm.get("include_disp")), comps=disp.get("comps"),
                        limits=limits_of(c3), lod_min_nodes=c3.lod_min_nodes, lod_target_vertices=c3.lod_target_vertices,
                        meshopt=c3.meshopt, extract_tcl=tcl_hash(effective_extract_tcl(settings)))
        if key != row["cache_key"]:
            continue
        man = safe_study_path(root, f"{cache_rel(CONTOUR_CACHE, key)}/out/{OUT_MANIFEST}")
        if man and os.path.isfile(man):
            out[rel] = man
    return out
