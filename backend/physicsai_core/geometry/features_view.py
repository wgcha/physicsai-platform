"""parameter_features.json 요약(geometry-engine.md §4.3, §7.6 `GET /param-sets/{id}/features`).

플랫폼은 키 존재·타입만 보고 모르는 키는 무시한다."""

from __future__ import annotations

from typing import Any

from .extract_filter import from_paicad


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def feature_rows(doc: dict[str, Any], png_ids: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """응답 `features[]`: name·type·body·nominal·min·max·group·ref_provisional·ref_locked·png_artifact_id(+unit·feasible)."""
    out: list[dict[str, Any]] = []
    for f in doc.get("features", []):
        if not isinstance(f, dict) or not isinstance(f.get("name"), str):
            continue
        rng = f.get("range") if isinstance(f.get("range"), dict) else {}
        ref = f.get("ref") if isinstance(f.get("ref"), dict) else {}
        feas = f.get("feasible") if isinstance(f.get("feasible"), dict) else None
        out.append({
            "name": f["name"], "type": f.get("type") if isinstance(f.get("type"), str) else "", "body": f.get("body") or "",
            "nominal": _num(f.get("nominal")), "min": _num(rng.get("min")), "max": _num(rng.get("max")),
            "unit": f.get("unit") if isinstance(f.get("unit"), str) else "mm",
            "group": f.get("group") if isinstance(f.get("group"), str) else None,
            "ref_provisional": bool(ref.get("provisional")), "ref_locked": bool(ref.get("locked")),
            "feasible": {"min": _num(feas.get("min")), "max": _num(feas.get("max")), "source": feas.get("source")} if feas else None,
            "png_artifact_id": (png_ids or {}).get(f["name"]),
        } | ({"row": row} if (row := _row_of(f)) is not None else {}))  # rib-gap.md §3.4: RIB_PITCH 피처의 열 소속(없으면 키 없음)
    return out


def _row_of(f: dict[str, Any]) -> dict[str, Any] | None:
    r = f.get("row")
    if isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("k"), int) and isinstance(r.get("n"), int):
        return {"id": r["id"], "k": r["k"], "n": r["n"]}
    return None


def rib_rows(doc: dict[str, Any]) -> list[dict[str, Any]] | None:
    """features 최상위 `rib_rows`(rib-gap.md §3.4, RIB_PITCH를 골랐을 때만) 사본 — 화면용 필드만(`face_signatures` 제외). 없으면 None."""
    rows = doc.get("rib_rows")
    if not isinstance(rows, list):
        return None
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str):
            continue
        room = r.get("end_room_mm") if isinstance(r.get("end_room_mm"), dict) else {}
        lim = r.get("end_limited_by") if isinstance(r.get("end_limited_by"), dict) else {}
        out.append({
            "id": r["id"], "body": r.get("body") or "", "axis": r.get("axis") if isinstance(r.get("axis"), str) else "",
            "anchor": r.get("anchor") if isinstance(r.get("anchor"), str) else "",
            "ribs": [{"index": int(b["index"]), "thickness": _num(b.get("thickness")), "center": _num(b.get("center"))}
                     for b in r.get("ribs") or [] if isinstance(b, dict) and isinstance(b.get("index"), int)],
            "end_room_mm": {"minus": _num(room.get("minus")), "plus": _num(room.get("plus"))},
            "end_limited_by": {"minus": lim.get("minus") if isinstance(lim.get("minus"), str) else None,
                               "plus": lim.get("plus") if isinstance(lim.get("plus"), str) else None}})
    return out


def representative_params(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """파라미터 표 대표 항목(§4.3): 그룹 대표 + 그룹 없는 피처. `{name, nominal, min, max, unit}` (extract 순서 유지)."""
    members: set[str] = set()
    reps: set[str] = set()
    for g in doc.get("groups", []):
        if isinstance(g, dict) and isinstance(g.get("parameter"), str):
            reps.add(g["parameter"])
            members |= {m for m in g.get("members", []) if isinstance(m, str)}
    rows = feature_rows(doc)
    return [{"name": r["name"], "nominal": r["nominal"], "min": r["min"], "max": r["max"], "unit": r["unit"] or "mm"}
            for r in rows if r["name"] in reps or r["name"] not in members]


def summary(doc: dict[str, Any], png_ids: dict[str, str] | None = None) -> dict[str, Any]:
    """`GET /param-sets/{id}/features` 본문: features + groups + warnings."""
    groups = [{"id": g.get("id"), "kind": g.get("kind"), "parameter": g.get("parameter"),
               "members": [m for m in g.get("members", []) if isinstance(m, str)]}
              for g in doc.get("groups", []) if isinstance(g, dict)]
    warns = [{"code": str(w.get("code")), "message": str(w.get("message") or ""), "feature": w.get("feature")}
             for w in doc.get("warnings", []) if isinstance(w, dict) and w.get("code")]
    return {"engine_version": doc.get("engine_version") if isinstance(doc.get("engine_version"), str) else None,
            "filter": from_paicad(doc.get("filter")),
            "features": feature_rows(doc, png_ids), "groups": groups, "warnings": warns, "rib_rows": rib_rows(doc)}
