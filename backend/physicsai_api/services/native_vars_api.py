"""④ 세트 변수 정의 API 서비스(native-vars.md §3·§6.1, v0.2.8 Altair 확장 altair-vars.md §5.1): 조회(`GET …/variables`)·저장(`PUT …/variables`, 리비전 파일).
Altair는 전체 tpl 세트만 편집(풀 = tpl 선언 행, 쉘·다중 baseline 규칙 없음), 부분 tpl은 조회만(422 TPL_SCOPE_PARTIAL).

- 세트 정의(현재값) = 기존 `S/parameters.json` + DB `param_sets.parameters`(형식 불변). 리비전 = `S/vars/vars.json` + `history/rev_<NNNN>.json`
  (`S/native/` 밖 — `native-prepare`가 `S/native/`를 `_backup`으로 옮기므로). 파일 없음 = 리비전 0(등록 정의).
- 풀 = 피처 파일의 그룹 대표 + 그룹 없는 피처. 이 기능은 풀 안에서 사용 여부·하한·상한만 정한다(추출 조건 불변).
- 쉘 두께 PROP 행(`source: "prop"`)은 `PUT /props` 소관 — 저장 시 기존 PROP 행을 그대로 뒤에 붙인다.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import sha256_file, write_json_atomic
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import native_vars as nv
from physicsai_core.geometry import shell as sh
from physicsai_core.geometry.prep import is_shell_only
from physicsai_core.geometry.shell_native import features_name, read_kind
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage4_predict import nearest

from ..auth import Principal
from ..context import AppContext
from .common import audit, study_root
from . import template_vars as tv
from .native_vars_train import identities_of, train_for
from .param_set_baselines_api import require_writable
from .param_set_native_api import _features_doc

VARS_DIR = "vars"
VARS_JSON = "vars/vars.json"
HISTORY_DIR = "vars/history"
HISTORY_LIMIT = 20
REV_RE = re.compile(r"rev_(\d{4,})\.json")
MULTI_MESSAGE = "다중 baseline 템플릿은 변수 추가·제외를 아직 지원하지 않습니다"
OFF_MESSAGE = "쉘 두께 설정에서 형상 파라미터를 켠 뒤 편집하세요"
SHELL_ONLY_MESSAGE = "쉘 두께 전용 템플릿에는 형상 변수가 없습니다"
CONFLICT_MESSAGE = "다른 사용자가 먼저 저장했습니다 — 새로 불러온 뒤 다시 저장하세요"
INVALID_MESSAGE = "변수 정의가 올바르지 않습니다"


# ---- 파일(리비전) --------------------------------------------------------------------------------------


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def read_revision(S: str) -> int:
    """현재 변수 정의 리비전(`S/vars/vars.json`, 없거나 깨졌으면 0 = 등록 정의)."""
    d = _read_json(os.path.join(S, *VARS_JSON.split("/")))
    r = (d or {}).get("revision")
    return r if isinstance(r, int) and not isinstance(r, bool) and r >= 0 else 0


def _history_revs(S: str) -> list[int]:
    d = os.path.join(S, *HISTORY_DIR.split("/"))
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted(int(m.group(1)) for n in names if (m := REV_RE.fullmatch(n)))


def _rev_path(S: str, n: int) -> str:
    return os.path.join(S, *HISTORY_DIR.split("/"), f"rev_{n:04d}.json")


def _history(S: str) -> list[dict[str, Any]]:
    out = []
    for n in reversed(_history_revs(S)[-HISTORY_LIMIT:]):
        d = _read_json(_rev_path(S, n)) or {}
        out.append({"revision": n, "saved_at": d.get("saved_at"), "saved_by_name": d.get("saved_by_name"),
                    "count": len(d.get("variables") or [])})
    return out


def _write_new(path: str, doc: dict[str, Any]) -> None:
    """덮어쓰기 금지(`x` 모드) — 이미 있으면 FileExistsError(호출부가 409)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)


# ---- 풀·세트 공용 ---------------------------------------------------------------------------------------


def component_of(ctx: AppContext, S: str) -> str:
    prep = _read_json(os.path.join(S, "native", "prep.json")) or {}
    c = prep.get("component")
    return c if isinstance(c, str) and c else ctx.settings.geometry.shell.default_component


def set_pool(ctx: AppContext, S: str) -> tuple[list[dict[str, Any]], str | None]:
    """(풀, features 파일 sha256). 피처 파일이 없으면 ([], None)."""
    kind = read_kind(S)
    doc = _features_doc(ctx, S)
    if doc is None:
        return [], None
    path = os.path.join(S, "native", "extract", features_name(kind))
    try:
        sha: str | None = sha256_file(path)
    except OSError:
        sha = None
    return nv.pool(doc, kind=kind, component=component_of(ctx, S) if kind == "shell" else None), sha


def vars_set(conn: Any, ps_id: str, *, for_update: bool = False) -> dict[str, Any]:
    """변수 정의 대상 세트(엔진 무관 — v0.2.8부터 Altair도 허용, NATIVE_VARS_UNSUPPORTED 폐지 AV-10)."""
    p = ps_repo.get(conn, ps_id, for_update=for_update)
    if p is None:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    return p


def _S(ctx: AppContext, conn: Any, p: dict[str, Any]) -> str:
    return resolve_in_study(study_root(ctx, studies_repo.require(conn, p["study_id"])), p["stored_rel"])


def editable_state(p: dict[str, Any], S: str) -> tuple[bool, str | None]:
    if tv.is_altair(p):  # altair-vars.md AV-10: 전체 tpl만 편집, 부분 tpl은 reason = TPL_SCOPE_PARTIAL
        return (True, None) if tv.tpl_scope(S) == tv.SCOPE_FULL else (False, tv.PARTIAL_REASON)
    if bl.is_multi(S):
        return False, MULTI_MESSAGE
    if is_shell_only(S):
        return False, SHELL_ONLY_MESSAGE
    if not sh.has_geometry(p["parameters"]):
        return False, OFF_MESSAGE
    return True, None


def _items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": str(r["name"]), "min": float(r["min"]), "max": float(r["max"])} for r in rows]


def pool_out(entries: list[dict[str, Any]], train: dict[str, Any] | None) -> list[dict[str, Any]]:
    out = []
    for e in entries:
        tr = (train or {}).get(e["name"])
        out.append({"name": e["name"], "type": e["type"], "body": e["body"], "nominal": e["nominal"], "unit": e["unit"],
                    "position": e["position"], "default_range": e["default_range"], "feasible": e["feasible"],
                    "ref_locked": e["ref_locked"], "group": e["group"], "train": tr,
                    "integer": bool(e.get("integer")), "range_unset": bool(e.get("range_unset")), "rib": nv.rib_public(e.get("rib"))})
    return out


# ---- 조회 ---------------------------------------------------------------------------------------------


def get_variables(ctx: AppContext, ps_id: str, model_id: str | None = None, revision: int | None = None) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        p = vars_set(conn, ps_id)
        S = _S(ctx, conn, p)
        study = studies_repo.require(conn, p["study_id"])
        model = None
        if model_id:
            model = models_repo.get(conn, model_id)
            if model is None or model["study_id"] != p["study_id"]:
                raise DomainError("NOT_FOUND", "모델을 찾을 수 없습니다", status=404)
        entries, sha = tv.pool_for(ctx, p, S)
        alt = tv.is_altair(p)
        train, src, notes = train_for(ctx, conn, study, model, identities_of(entries, list(p["parameters"])), "altair" if alt else "native") \
            if alt or not bl.is_multi(S) else (None, None, [])
    return _out(p, S, entries, sha, train, src, notes, revision)


def _out(p: dict[str, Any], S: str, entries: list[dict[str, Any]], sha: str | None, train: dict[str, Any] | None,
         src: dict[str, Any] | None, notes: list[dict[str, str]], revision: int | None, warnings: list[dict[str, str]] | None = None
         ) -> dict[str, Any]:
    cur = read_revision(S)
    geo = sh.geometry_rows(p["parameters"])  # Altair 행에는 source가 없어 전부 형상 행(= 변수 행)이다
    if revision is not None and revision != cur:
        doc = _read_json(_rev_path(S, revision))
        if doc is None:
            raise DomainError("NATIVE_VARS_REVISION_NOT_FOUND", f"변수 정의 리비전 {revision}을 찾을 수 없습니다", status=404)
        items = [{"name": str(v["name"]), "min": float(v["min"]), "max": float(v["max"])} for v in doc.get("variables") or []
                 if isinstance(v, dict) and "name" in v and "min" in v and "max" in v]
    else:
        items = _items(geo)
    editable, reason = editable_state(p, S)
    names = {e["name"] for e in entries}
    return {"engine": tv.engine_label(p), "revision": cur, "features_sha256": sha, "editable": editable, "reason": reason, "variables": items,
            "pool": pool_out(entries, train), "stale_names": [r["name"] for r in geo if r["name"] not in names] if entries else [],
            "train_source": src, "notes": notes, "warnings": warnings or [], "history": _history(S)}


# ---- 저장 ---------------------------------------------------------------------------------------------


def _problem(code: str, message: str, name: str | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"code": code, "message": message}
    if name:
        p["name"] = name
    return p


def validate_items(items: list[Any], entries: list[dict[str, Any]], prop_count: int) -> list[dict[str, Any]]:
    """§3.4 검증 → problems(VAR_UNKNOWN·VAR_DUPLICATE·VAR_RANGE_INVALID·VARS_EMPTY)."""
    names = {e["name"] for e in entries}
    by_name = {e["name"]: e for e in entries}
    seen: set[str] = set()
    probs: list[dict[str, Any]] = []
    for it in items:
        n = it.name
        if n in seen:
            probs.append(_problem("VAR_DUPLICATE", f"'{n}'이 중복되었습니다", n))
            continue
        seen.add(n)
        if n not in names:
            probs.append(_problem("VAR_UNKNOWN", f"'{n}'은 이 템플릿의 형상 변수가 아닙니다", n))
            continue
        if not (math.isfinite(it.min) and math.isfinite(it.max)) or it.min > it.max:
            probs.append(_problem("VAR_RANGE_INVALID", "하한·상한은 유한한 숫자이고 하한 ≤ 상한이어야 합니다", n))
        elif by_name[n].get("integer") and not nearest.is_integer_range(it.min, it.max):  # altair-vars.md §5.1(④ 일괄·⑥과 공용 검사)
            probs.append(_problem(nearest.INT_RANGE_CODE, nearest.INT_RANGE_MESSAGE, n))
    if not seen and prop_count == 0:
        probs.append(_problem("VARS_EMPTY", "변수를 하나 이상 고르세요"))
    return probs


def build_rows(items: list[Any], entries: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """풀 순서의 형상 행(`{name, nominal, min, max, unit}`, 기존 행의 다른 키는 보존, 쉘 피처는 source=shell)."""
    chosen = {it.name: it for it in items}
    old = {str(r["name"]): r for r in current}
    rows: list[dict[str, Any]] = []
    for e in entries:
        it = chosen.get(e["name"])
        if it is None:
            continue
        row = {**old.get(e["name"], {}), "name": e["name"], "nominal": e["nominal"], "min": float(it.min), "max": float(it.max),
               "unit": e["unit"]}
        if e.get("source"):
            row.setdefault("source", e["source"])
        rows.append(row)
    return rows


def put_variables(ctx: AppContext, principal: Principal, ps_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        p = vars_set(conn, ps_id, for_update=True)
        require_writable(conn, principal, p)
        S = _S(ctx, conn, p)
        alt = tv.is_altair(p)
        if alt:
            if tv.tpl_scope(S) != tv.SCOPE_FULL:  # altair-vars.md AV-10: 옛 부분 tpl은 편집 불가 + 재생성 안내
                raise DomainError(tv.PARTIAL_REASON, tv.PARTIAL_MESSAGE, status=422)
        elif bl.is_multi(S):
            raise DomainError("NATIVE_VARS_MULTI_UNSUPPORTED", MULTI_MESSAGE, status=409)
        elif is_shell_only(S):
            raise DomainError("NATIVE_VARS_GEOMETRY_OFF", SHELL_ONLY_MESSAGE, status=409)
        elif not sh.has_geometry(p["parameters"]):
            raise DomainError("NATIVE_VARS_GEOMETRY_OFF", OFF_MESSAGE, status=409)
        entries, sha = tv.pool_for(ctx, p, S)
        if not entries:
            raise DomainError("TPL_MISSING" if alt else "NATIVE_PREP_MISSING",
                              "tpl에서 변수를 찾을 수 없습니다" if alt else "형상 피처 파일이 없습니다 — 형상 준비를 다시 하세요", status=409)
        cur = read_revision(S)
        if body.base_revision != cur:
            raise DomainError("NATIVE_VARS_CONFLICT", CONFLICT_MESSAGE, status=409, revision=cur)
        props = sh.prop_rows(p["parameters"])
        probs = validate_items(body.variables, entries, len(props))
        if probs:
            raise DomainError("NATIVE_VARS_INVALID", INVALID_MESSAGE, status=422, problems=probs)
        old_geo = sh.geometry_rows(p["parameters"])
        rows = sh.merge_rows(build_rows(body.variables, entries, old_geo), props)
        hist = _history_revs(S)
        new_rev = max([cur, *hist]) + 1
        now = datetime.now(timezone.utc).isoformat()
        doc = {"schema_version": nv.SCHEMA_VERSION, "revision": new_rev, "parent_revision": cur, "saved_at": now,
               "saved_by": principal.user_id, "saved_by_name": principal.display_name, "features_sha256": sha,
               "engine_version": p.get("engine_version"),
               "variables": [{"name": r["name"], "min": r["min"], "max": r["max"]} for r in rows if not nv.is_prop_row(r)]}
        pj, vj = os.path.join(S, "parameters.json"), os.path.join(S, *VARS_JSON.split("/"))
        old_pj, old_vj = _raw(pj), _raw(vj)
        try:
            if cur == 0 and not os.path.isfile(_rev_path(S, 0)):  # 등록 정의도 되살릴 수 있게 리비전 0 보관
                _write_new(_rev_path(S, 0), {
                    "schema_version": nv.SCHEMA_VERSION, "revision": 0, "parent_revision": None, "saved_at": now, "saved_by": None,
                    "saved_by_name": "등록", "features_sha256": sha, "engine_version": p.get("engine_version"),
                    "variables": [{"name": r["name"], "min": r["min"], "max": r["max"]} for r in old_geo]})
            _write_new(_rev_path(S, new_rev), doc)
        except FileExistsError:
            raise DomainError("NATIVE_VARS_CONFLICT", CONFLICT_MESSAGE, status=409, revision=cur) from None
        try:
            write_json_atomic(pj, {"schema_version": 1, "unit_system": p.get("unit_system") or "mm-ton-s", "parameters": rows})
            write_json_atomic(vj, doc)
            ps_repo.set_values(conn, ps_id, parameters=rows)
            audit(conn, principal, "PARAM_SET_UPDATE", "param_set", ps_id,
                  {"vars_revision": new_rev, "names": [v["name"] for v in doc["variables"]], "count": len(doc["variables"])}, rid, ip)
        except BaseException:
            _restore(pj, old_pj)
            _restore(vj, old_vj)  # 리비전 파일은 남겨도 무해 — 다음 저장은 max(history)+1
            raise
        p = ps_repo.get(conn, ps_id)  # type: ignore[assignment]
    sets, _ = nv.effective(rows, entries)
    warns = nv.warn_rows(sets)
    return _out(p, S, entries, sha, None, None, [], None, warns)  # type: ignore[arg-type]


def _raw(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _restore(path: str, data: bytes | None) -> None:
    """③ 실패 시 ②를 이전 내용으로 되씀. 원래 없던 vars.json은 지우지 않고(삭제 금지) 리비전 0 표시로 되쓴다(파일 없음 = 리비전 0)."""
    try:
        if data is None:
            write_json_atomic(path, {"schema_version": nv.SCHEMA_VERSION, "revision": 0, "parent_revision": None})
        else:
            write_json_atomic(path, json.loads(data.decode("utf-8")))
    except (OSError, ValueError):
        pass
