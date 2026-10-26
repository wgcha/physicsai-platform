"""DOE 표본 형상 그리드 미리보기 `DOE_PREVIEW`(doe-preview.md §6.1): DP_PREP → DP_MATRIX → DP_RENDER(CPU 대기열, 셀 묶음 병렬) → DP_REGISTER.

- 표본 행은 실제 TD_DOE_GEN DG_PREP과 같은 함수·같은 입력(`lhs_values`·`doe_native_methods.single_matrix`·`reuse_matrix`·`doe_matrix_csv`)으로
  계산해 같은 바이트의 `doe_matrix.csv`를 만든다(V-DP-3). `train_doe`는 `D/doe_matrix.csv`를 그대로 쓴다.
- 캐시(서버측 `<study>/_cache/doe_preview/`, 플랫폼 임시 산출물 — 삭제는 `cache_store`만): `cells/<key[0:2]>/<key>/`(셀), `matrix/<mkey>/`(행렬),
  `jobs/<job_id>/`(작업 폴더). 청크가 끝날 때마다 완료 셀을 셀 캐시로 옮기고 산출물·`doe_preview_cells`를 등록한다(화면 폴링이 바로 채움).
- 셀 판정(GV-10 준용, `judge_cell`): OK·FAIL → 캐시, ERROR·청크 시간 초과·manifest 없음 → 그 셀만 ERROR(캐시 안 함, 작업 SUCCEEDED + 경고
  `DOE_PREVIEW_PARTIAL`), 전부 ERROR면 작업 FAILED(첫 코드). 취소 시 완료 청크 셀은 캐시에 남는다.
- 외부 명령은 설정 템플릿 `paicad_view_grid`·`paicad_shell_view_grid`만(shell=False, `--threads 1`).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from physicsai_core.cache_store import remove_cache_dir
from physicsai_core.db.repositories import doe_preview as dp_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json, write_text
from physicsai_core.geometry import doe_preview as dp
from physicsai_core.geometry import doe_preview_src as src_mod
from physicsai_core.geometry import native_vars as nv
from physicsai_core.geometry.messages import label_of
from physicsai_core.geometry.native_files import doe_matrix_csv
from physicsai_core.geometry.options import usage_document
from physicsai_core.geometry.view import (
    GLB_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    PREVIEW_GLB,
    PREVIEW_MANIFEST,
    THUMB_KIND,
    dir_bytes,
    read_json,
    view_options_document,
)
from physicsai_core.stage1_train_data import doe_platform
from physicsai_core.stage4_predict.batch_matrix import lhs_values, run_key_for

from .geometry_native import run_paicad
from .stage1_train_data import doe_native, doe_native_methods

GRID_COMMANDS = frozenset({"paicad_view_grid", "paicad_shell_view_grid"})  # 이 작업이 쓰는 외부 명령은 이 둘뿐


def _pid(ctx: Any) -> str:
    return str(ctx.params["preview_id"])


def _T(ctx: Any) -> str:
    return ctx.abs(dp.job_dir_rel(ctx.ex.job_id))


def _set_preview(ctx: Any, **vals: Any) -> None:
    ctx.ex.db(lambda c: dp_repo.set_values(c, _pid(ctx), **vals))


def _source(ctx: Any) -> tuple[src_mod.Source, dict[str, Any] | None]:
    """작업 params.source → 형상 입력(API와 같은 `doe_preview_src`) + (train 출처의 학습 설정). 입력이 바뀌었으면 StepFailure."""
    s, p = ctx.settings, ctx.params
    ref = p["source"]
    kind = ref["kind"]
    sid = ctx.study["id"]
    try:
        with ctx.ex.engine.connect() as conn:
            if kind == "train":
                setup = train_repo.get_setup(conn, sid)
                if setup is None:
                    raise StepFailure("INPUT_INVALID", "학습 설정이 없습니다(①-1 파라미터 추출 먼저)")
                return src_mod.from_train(ctx.root, setup, s), setup
            if kind == "param_set":
                ps = ps_repo.get(conn, ref.get("param_set_id") or "")
                if ps is None or ps["study_id"] != sid or ps.get("engine") != "native":
                    raise StepFailure("INPUT_INVALID", "Native 파라미터 세트를 찾을 수 없습니다")
                ps = nv.apply(ps, nv.vars_of(p))  # native-vars.md §4.2: 요청 때의 세트 정의 스냅숏(실제 DOE와 같은 범위)
                return src_mod.from_param_set(ctx.root, ps, s), None
            doe = train_repo.get_doe(conn, ref.get("doe_id") or "")
            if doe is None or doe["study_id"] != sid or doe["status"] != "READY":
                raise StepFailure("INPUT_INVALID", "READY 상태의 DOE를 찾을 수 없습니다")
            return src_mod.from_doe(ctx.root, doe, s), None
    except src_mod.SourceError as exc:
        raise StepFailure(exc.code, exc.message) from None


def _check_prep(ctx: Any, src: src_mod.Source) -> None:
    """세트 준비본이 낡았으면 GEOM_PREP_STALE(§6.1 DP_PREP). 세트 출처만 — train·train_doe는 추출·생성 산출물을 그대로 쓴다."""
    if src.kind != "param_set":
        return
    from physicsai_core.geometry.prep import READY, prep_state

    pr = ctx.settings.predict
    st = prep_state(src.base, step_exts=ctx.settings.geometry.step_extensions, mesh_include_name=pr.mesh_include_name,
                    renum_csv_name=pr.renum_csv_name, opts=src.opts, current_engine_version=ctx.params.get("engine_version"))
    if st.status != READY:
        raise StepFailure("GEOM_PREP_STALE", st.reason or "형상 준비본이 유효하지 않습니다 — 형상 준비를 다시 하세요")


def dp_prep(ctx: Any) -> None:
    src, _setup = _source(ctx)
    _check_prep(ctx, src)
    T = _T(ctx)
    if not remove_cache_dir(ctx.root, T, dp.CACHE_ROOT):  # 작업 폴더도 캐시(재시도·이어받기 없음) — 이미 있으면 지우고 새로
        raise StepFailure("PATH_UNSAFE", "미리보기 작업 폴더 경로가 안전하지 않습니다")
    os.makedirs(T)
    _set_preview(ctx, status="RUNNING")
    ctx.patch_result({"preview_id": _pid(ctx), "kind": src.shape, "source_kind": src.kind, "job_dir_rel": ctx.rel(T)})


# ---- DP_MATRIX -------------------------------------------------------------------------------------------------


def _read_matrix(dir_: str) -> list[tuple[int, str, dict[str, float]]]:
    return doe_native._matrix(dir_)


def _train_matrix(ctx: Any, src: src_mod.Source, setup: dict[str, Any]) -> tuple[list[str], list[tuple[int, str, dict[str, float]]]]:
    """①-3 native DG_PREP(`doe_native.dg_prep`)의 표본 행 계산과 같은 함수·같은 순서. seed 규칙은 DG_PREP(`int(seed or 1)`)과 같다."""
    p = ctx.params
    used = src.matrix_rows
    names = [q["name"] for q in used]
    matrix = doe_native.reuse_matrix(ctx, p, names)
    if matrix is None and (sp := doe_native_methods.method_sampling(p)) is not None:
        matrix, _record = doe_native_methods.single_matrix(ctx, sp, doe_platform.design_inputs_native(setup))
        names = list(matrix[0][2])
    if matrix is None:
        seed = int(p.get("seed") or 1)
        rows = lhs_values(names, {q["name"]: (float(q["min"]), float(q["max"])) for q in used}, int(p.get("num_runs") or 2), seed)
        matrix = [(i, run_key_for(i), v) for i, v in enumerate(rows, 1)]
    return names, matrix


def _set_matrix(ctx: Any, src: src_mod.Source) -> tuple[list[str], list[tuple[int, str, dict[str, float]]]]:
    """세트 기준 native DG_PREP(`doe_native_set.dg_prep` 단일 baseline 분기)의 표본 행 계산과 같은 함수. seed 규칙 `int(seed if not None else 1)`."""
    p = ctx.params
    params = src.matrix_rows
    names = [str(r["name"]) for r in params]
    matrix = doe_native.reuse_matrix(ctx, p, names)
    if matrix is None and (sp := doe_native_methods.method_sampling(p)) is not None:
        matrix, _record = doe_native_methods.single_matrix(ctx, sp, doe_platform.design_inputs_from_params(params))
        names = list(matrix[0][2])
    if matrix is None:
        seed = int(p.get("seed") if p.get("seed") is not None else 1)
        vals = lhs_values(names, {str(r["name"]): (float(r["min"]), float(r["max"])) for r in params}, int(p.get("num_runs") or 2), seed)
        matrix = [(i, run_key_for(i), v) for i, v in enumerate(vals, 1)]
    return names, matrix


def _ensure_matrix(ctx: Any, src: src_mod.Source, setup: dict[str, Any] | None) -> tuple[str, list[tuple[int, str, dict[str, float]]], bool]:
    """행렬 캐시 `matrix/<mkey>/doe_matrix.csv`(있으면 재사용) → (캐시 폴더, 행, 재사용 여부)."""
    mkey = str(ctx.params["matrix_key"])
    M = ctx.abs(dp.matrix_dir_rel(mkey))
    csv_path = os.path.join(M, dp.MATRIX_CSV)
    if os.path.isfile(csv_path):
        os.utime(M)  # housekeeping 보관 기간 갱신(재사용 = 접근)
        return M, _read_matrix(M), True
    os.makedirs(M, exist_ok=True)
    if src.kind == "train_doe":
        D = src.extra["doe_dir"]
        from physicsai_core.geometry.prep import sha256_file

        want = ctx.params.get("matrix_sha256")
        have = os.path.join(D, dp.MATRIX_CSV)
        if not os.path.isfile(have) or (want and sha256_file(have) != want):
            raise StepFailure("INPUT_CHANGED", "DOE 표본 표(doe_matrix.csv)가 요청 이후 바뀌었거나 없습니다 — 다시 여세요")
        copy_file(have, csv_path, checkpoint=ctx.checkpoint)
        return M, _read_matrix(M), False
    names, matrix = _train_matrix(ctx, src, setup or {}) if src.kind == "train" else _set_matrix(ctx, src)
    write_text(csv_path, doe_matrix_csv(names, matrix))  # DG_PREP과 같은 함수·같은 바이트
    return M, _read_matrix(M), False


def dp_matrix(ctx: Any) -> None:
    t0 = time.monotonic()
    s, p = ctx.settings, ctx.params
    cfg = s.doe_preview
    src, setup = _source(ctx)
    M, rows, reused = _ensure_matrix(ctx, src, setup)
    ctx.log(f"표본 표 {len(rows)}행 ({'행렬 캐시 재사용' if reused else '새로 계산'}): {ctx.rel(M)}")
    sel = p["select"]
    geo = src.geo_params
    order = dp.order_rows(rows, geo, sel["order"], sel.get("var"), bool(sel.get("desc")))
    with_nominal, picked = dp.page_slice(order, int(sel["offset"]), int(sel["limit"]))
    by_no = {r[0]: r for r in rows}
    thumb_doc = dp.thumb_options_document(cfg, geo)
    thumb = dp.thumb_digest(thumb_doc)
    tess = src_mod.view_tess(src, s)
    ver = p.get("engine_version")
    ev = ver or f"unknown:{ctx.ex.job_id}"  # 버전을 모르면 캐시 조회 없이 전부 렌더(GV §6.4)
    sid = ctx.study["id"]

    def key_of(values: dict[str, float]) -> str:
        return dp.cell_key(kind=src.shape, study_id=sid, shape=src.digest, values=values, view_tess=tess, thumb=thumb, engine_version=ev)

    entries: list[dict[str, Any]] = []
    if with_nominal:
        nv_ = dp.full_values({}, geo)
        entries.append({"key": key_of(nv_), "doe_no": None, "run_key": None, "nominal": True, "values": nv_})
    for no in picked:
        _no, rk, vals = by_no[no]
        fv = dp.full_values(vals, geo)
        entries.append({"key": key_of(fv), "doe_no": no, "run_key": rk, "nominal": False, "values": fv})
    keys = list(dict.fromkeys(e["key"] for e in entries))
    done: dict[str, dict[str, Any]] = {}
    if ver:
        with ctx.ex.engine.connect() as conn:
            done = dp_repo.done_cells(conn, sid, keys)
        done = {k: v for k, v in done.items() if os.path.isfile(os.path.join(ctx.abs(dp.cell_dir_rel(k)), dp.THUMB_PNG))}
        if done:
            ctx.ex.db(lambda c: dp_repo.touch_cells(c, list(done)))
    todo = [e for e in {x["key"]: x for x in entries}.values() if e["key"] not in done]
    T = _T(ctx)
    doc = {"v": 1, "order": order[:dp.ORDER_MAX], "tag_state": src.tag_state, "disp_range_mm": thumb_doc["disp_range_mm"],
           "colormap": thumb_doc["colormap"], "params": geo, "cells": entries}
    write_json(os.path.join(T, dp.CELLS_JSON), dp.cells_document([(e["key"], {} if e["nominal"] else e["values"]) for e in todo]))
    write_json(os.path.join(T, dp.THUMB_OPTIONS_JSON), thumb_doc)
    write_json(os.path.join(T, dp.VIEW_OPTIONS_JSON), view_options_document(s, tess))
    write_json(os.path.join(T, dp.OPTIONS_JSON), {**usage_document(src.opts, ver), **({"kind": "shell"} if src.shape == "shell" else {})})
    ctx.ex.db(lambda c: dp_repo.set_values(c, _pid(ctx), matrix_key=str(p["matrix_key"]), cell_keys=doc, n_total=len(rows)))
    ctx.log(f"이번 페이지 셀 {len(entries)}개(공칭 {'포함' if with_nominal else '없음'}) — 캐시 적중 {len(done)}개, 렌더 {len(todo)}개")
    ctx.patch_result({"n_total": len(rows), "page_cells": len(entries), "cached": len(done), "to_render": len(todo), "matrix_reused": reused,
                      "matrix_s": round(time.monotonic() - t0, 2), "cell_errors": {}})


# ---- DP_RENDER -------------------------------------------------------------------------------------------------


def _register_cell(ctx: Any, key: str, entry: dict[str, Any], values: dict[str, float], src_dir: str, ver: str | None) -> dict[str, Any]:
    """완료 셀 폴더를 셀 캐시로 옮기고(`os.replace`) 산출물·인덱스 행을 등록 → 판정 요약."""
    dest = ctx.abs(dp.cell_dir_rel(key))
    if not remove_cache_dir(ctx.root, dest, dp.CACHE_ROOT):
        raise StepFailure("PATH_UNSAFE", "셀 캐시 폴더 경로가 안전하지 않습니다")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.replace(src_dir, dest)
    man = read_json(os.path.join(dest, dp.CELL_MANIFEST)) or {}
    th = man.get("thumb") if isinstance(man.get("thumb"), dict) else {}
    png = os.path.join(dest, dp.THUMB_PNG)
    glb = os.path.join(dest, PREVIEW_GLB)
    ids = {"png_artifact_id": ctx.register_artifact(THUMB_KIND, png, dp.THUMB_CONTENT_TYPE),
           "glb_artifact_id": ctx.register_artifact("GEOM_PREVIEW_GLB", glb, GLB_CONTENT_TYPE) if os.path.isfile(glb) else None,
           "manifest_artifact_id": ctx.register_artifact("GEOM_PREVIEW_MANIFEST", os.path.join(dest, PREVIEW_MANIFEST), JSON_CONTENT_TYPE)}
    j = dp.judge_cell(entry)
    row = {"cache_key": key, "study_id": ctx.study["id"], "status": "DONE", "result_status": j["status"], "code": j["code"],
           "category": j["category"], "max_disp_mm": j["max_disp_mm"], "clipped": bool(th.get("clipped")), "values": values, **ids,
           "bytes": dir_bytes(dest), "engine_version": ver}
    ctx.ex.db(lambda c: dp_repo.upsert_cell(c, row))
    return j


def dp_render(ctx: Any) -> None:
    t0 = time.monotonic()
    s, p = ctx.settings, ctx.params
    cfg = s.doe_preview
    src, _setup = _source(ctx)
    T = _T(ctx)
    todo = [(c["id"], c["values"]) for c in (read_json(os.path.join(T, dp.CELLS_JSON)) or {}).get("cells", [])]
    if not todo:
        ctx.log("렌더할 셀이 없습니다(전부 캐시)")
        ctx.patch_result({"render_s": 0.0, "rendered": 0})
        return
    with ctx.ex.engine.connect() as conn:
        doc = (dp_repo.get(conn, _pid(ctx)) or {}).get("cell_keys") or {}
    values_of = {e["key"]: e["values"] for e in doc.get("cells", [])}
    key = dp.grid_command_key(src.shape)
    if key not in GRID_COMMANDS:  # 허용 외부 명령은 grid 키 2개뿐(정적 시험도 확인)
        raise StepFailure("INTERNAL_ERROR", f"DOE_PREVIEW에서 허용되지 않은 명령: {key}")
    if getattr(s.commands, key, None) is None:
        raise StepFailure("DOE_PREVIEW_UNAVAILABLE", f"형상 미리보기를 쓸 수 없습니다 — commands.{key} 설정 확인")
    chunks = dp.chunked(todo, cfg.chunk_cells)
    lock = threading.Lock()
    state = {"ok": 0, "fail": 0, "error": 0}
    errors: dict[str, str] = {}
    ver = p.get("engine_version")
    base = {"cad_input": src.cad_input, "features_json": src.features, "tag_dir": src.tag_dir or "", "fixed_dir": src.fixed_dir or "",
            "options_json": os.path.join(T, dp.OPTIONS_JSON), "view_options_json": os.path.join(T, dp.VIEW_OPTIONS_JSON),
            "thumb_options_json": os.path.join(T, dp.THUMB_OPTIONS_JSON), "threads": "1"}
    if src.tag_dir and not os.path.isdir(src.tag_dir):
        base["tag_dir"] = ""

    def mark_error(keys: list[str], code: str) -> None:
        with lock:
            for k in keys:
                errors[k] = code
            state["error"] += len(keys)

    def flush() -> None:
        with lock:  # patch_result는 얕은 병합이라 동시 갱신이 서로 덮어쓰지 않게 전체 dict를 한 번에, 잠금 안에서
            ctx.patch_result({"cell_errors": dict(errors), "rendered_ok": state["ok"], "rendered_fail": state["fail"]})

    def one(runner: Any, item: tuple[int, list[tuple[str, dict[str, float]]]]) -> None:
        i, chunk = item
        out = os.path.join(T, f"chunk_{i}")
        cells_file = os.path.join(T, f"chunk_{i}.cells.json")
        write_json(cells_file, dp.cells_document(chunk))
        ids = [c[0] for c in chunk]
        values = {**base, "cells_json": cells_file, "out_dir": out}
        manifest = os.path.join(out, dp.GRID_MANIFEST)
        try:
            verdict = run_paicad(runner, s, key, values, cwd=T, report=manifest, success=[], backup=[out], body_map=src.body_map, log_dir=out,
                                 timeout_s=len(chunk) * float(cfg.timeout_s_per_cell))
        except StepFailure as exc:  # 시간 초과·실행 파일 없음 등 청크 전체 오류(그 셀만 ERROR, 다음 청크는 계속)
            mark_error(ids, exc.code)
            flush()
            return
        gm = read_json(manifest)
        if gm is None:  # grid_manifest.json 존재 = 성공 판정(§3.1) — 없으면 청크 셀 전부 ERROR(paicad가 보고한 코드, 없으면 OUTPUT_MISSING)
            mark_error(ids, verdict.code or "OUTPUT_MISSING")
            flush()
            return
        by_id = {c.get("id"): c for c in gm.get("cells", []) if isinstance(c, dict)}
        for cid in ids:
            j = dp.judge_cell(by_id.get(cid))
            sdir = os.path.join(out, "cells", cid)
            ok_dir = os.path.isfile(os.path.join(sdir, dp.CELL_MANIFEST)) and os.path.isfile(os.path.join(sdir, dp.THUMB_PNG))
            if not j["cacheable"] or not ok_dir:
                mark_error([cid], j["code"] if not j["cacheable"] and j["code"] else "OUTPUT_MISSING")
                continue
            jj = _register_cell(ctx, cid, by_id[cid], values_of.get(cid) or {}, sdir, ver)
            with lock:
                state["ok" if jj["status"] == "OK" else "fail"] += 1
        flush()

    total = len(todo)

    def label(_r: int, _d: int, _f: int, _t: int, _m: int) -> str:
        with lock:
            return f"셀 {state['ok'] + state['fail'] + state['error']}/{total} 완료 · 실패 {state['fail']} · 오류 {state['error']}"

    outcomes = ctx.run_parallel(list(enumerate(chunks)), one, item_id=lambda it: f"chunk_{it[0]}", max_parallel=cfg.parallel, label=label)
    for o, chunk in zip(outcomes, chunks):  # fn 밖(내부 오류 등)으로 실패한 청크의 아직 기록 안 된 셀은 ERROR
        if not o.ok and o.code != "CANCELED":
            lost = [c[0] for c in chunk if c[0] not in errors and not _cached(ctx, c[0])]
            if lost:
                mark_error(lost, o.code or "INTERNAL_ERROR")
    flush()
    ctx.patch_result({"render_s": round(time.monotonic() - t0, 2), "rendered": total})


def _cached(ctx: Any, key: str) -> bool:
    return os.path.isfile(os.path.join(ctx.abs(dp.cell_dir_rel(key)), dp.THUMB_PNG))


# ---- DP_REGISTER -----------------------------------------------------------------------------------------------


def dp_register(ctx: Any) -> None:
    sid = ctx.study["id"]
    r = ctx.result()
    with ctx.ex.engine.connect() as conn:
        row = dp_repo.get(conn, _pid(ctx)) or {}
        keys = [e["key"] for e in (row.get("cell_keys") or {}).get("cells", [])]
        cells = dp_repo.done_cells(conn, sid, keys)
    errors: dict[str, str] = dict(r.get("cell_errors") or {})
    uniq = list(dict.fromkeys(keys))
    n_ok = sum(1 for k in uniq if k in cells and cells[k]["result_status"] == "OK")
    n_fail = sum(1 for k in uniq if k in cells and cells[k]["result_status"] == "FAIL")
    bad = [k for k in uniq if k not in cells]
    n_error = len(bad)
    if uniq and n_error == len(uniq):  # 모든 셀 ERROR → 작업 FAILED(첫 코드)
        code = errors.get(bad[0]) or "OUTPUT_MISSING"
        raise StepFailure(code, f"형상 미리보기 셀 {len(uniq)}개가 모두 오류입니다 — {label_of(code)}")
    if n_error:
        ctx.add_warning("DOE_PREVIEW_PARTIAL", f"셀 {len(uniq)}개 중 {n_error}개를 그리지 못했습니다(다시 요청하면 그 셀만 다시 그립니다)")
    timing = {"total_s": round(float(r.get("matrix_s") or 0) + float(r.get("render_s") or 0), 2), "matrix_s": r.get("matrix_s"),
              "render_s": r.get("render_s")}
    from sqlalchemy import func

    ctx.ex.db(lambda c: dp_repo.set_values(c, _pid(ctx), status="DONE", n_ok=n_ok, n_fail=n_fail, n_error=n_error, timing=timing,
                                           finished_at=func.now()))
    ctx.patch_result({"n_ok": n_ok, "n_fail": n_fail, "n_error": n_error})


HANDLERS = {
    ("DOE_PREVIEW", "DP_PREP"): dp_prep,
    ("DOE_PREVIEW", "DP_MATRIX"): dp_matrix,
    ("DOE_PREVIEW", "DP_RENDER"): dp_render,
    ("DOE_PREVIEW", "DP_REGISTER"): dp_register,
}
