"""형상 3D 가시화·미리보기 플랫폼 쪽 순수 함수(geometry-view.md §4·§6). 표준 라이브러리만, paicad import 없음.

- 공칭 뷰: `<base>/native/view/{view.glb, view_manifest.json, view_options.json}`(NP_VIEW·TX_VIEW). prep.json 선택 키 `view`.
- 미리보기 캐시: 서버측 AI 루트 `<study>/_cache/geom_preview/<key[0:2]>/<key>/`(플랫폼 임시 산출물, §6.6 — 브라우저 캐시 아님).
- 캐시 키 = sha256(정규 JSON — 키 정렬·공백 없음·float는 repr): {param_set_id, kind, prep_digest, view_tess, values, fe, engine_version}.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any

VIEW_DIR = "native/view"
VIEW_GLB, VIEW_MANIFEST, VIEW_OPTIONS = "view.glb", "view_manifest.json", "view_options.json"
PREVIEW_GLB, PREVIEW_FE_GLB, PREVIEW_MANIFEST = "preview.glb", "preview_fe.glb", "preview_manifest.json"
CACHE_DIR = "_cache"
PREVIEW_CACHE = "_cache/geom_preview"
CONTOUR_CACHE = "_cache/contour3d"
GLB_CONTENT_TYPE = "model/gltf-binary"
OCTET_CONTENT_TYPE = "application/octet-stream"
JSON_CONTENT_TYPE = "application/json"
VIEW_KINDS = ("GEOM_VIEW_GLB", "GEOM_VIEW_MANIFEST")
PREVIEW_KINDS = ("GEOM_PREVIEW_GLB", "GEOM_PREVIEW_FE_GLB", "GEOM_PREVIEW_MANIFEST")
CONTOUR_KINDS = ("CONTOUR3D_GLB", "CONTOUR3D_FRAMES", "CONTOUR3D_MANIFEST", "CONTOUR3D_DISP", "CONTOUR3D_LOD")  # DISP·LOD = v0.2.10(C3F-6·8)
GLB_KINDS = ("GEOM_VIEW_GLB", "GEOM_PREVIEW_GLB", "GEOM_PREVIEW_FE_GLB", "CONTOUR3D_GLB", "CONTOUR3D_LOD")
MEDIA_KINDS = GLB_KINDS + ("CONTOUR3D_FRAMES", "CONTOUR3D_DISP")  # `/artifacts/{id}/media`(Range) 대상
NEW_ARTIFACT_KINDS = VIEW_KINDS + PREVIEW_KINDS + CONTOUR_KINDS
FE_MODES = ("off", "check", "morph")
READY, MISSING, FAILED = "READY", "MISSING", "FAILED"


def view_options_document(settings: Any, tess: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """`view_options.json`(§4.5) = 설정 `geometry.view` 사용값. max_glb_bytes는 ui.max_artifact_bytes로 자른다(§6.1)."""
    v = settings.geometry.view
    t = dict(tess) if tess else {"linear_mm": float(v.tess.linear_mm), "angular_deg": float(v.tess.angular_deg)}
    return {"schema_version": 1, "tess": {"linear_mm": float(t["linear_mm"]), "angular_deg": float(t["angular_deg"])},
            "max_triangles": int(v.max_triangles), "max_glb_bytes": int(min(v.max_glb_bytes, settings.ui.max_artifact_bytes)),
            "coarsen_steps": int(v.coarsen_steps), "edges": bool(v.edges), "fe_edges": bool(v.fe_edges)}


def export_key(kind: str) -> str:
    return "paicad_shell_view_export" if kind == "shell" else "paicad_view_export"


def preview_key(kind: str) -> str:
    return "paicad_shell_view_preview" if kind == "shell" else "paicad_view_preview"


def read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def view_result(out_dir: str, engine_version: str | None) -> dict[str, Any] | None:
    """export 결과 → `view = {status:"READY", sha256, tess, engine_version}`(manifest OK + view.glb). 아니면 None."""
    m = read_json(os.path.join(out_dir, VIEW_MANIFEST))
    glb = os.path.join(out_dir, VIEW_GLB)
    if not m or m.get("status") != "OK" or not os.path.isfile(glb) or os.path.getsize(glb) == 0:
        return None
    from ..fileutil import sha256_file

    tess = m.get("tess") if isinstance(m.get("tess"), dict) else None
    return {"status": READY, "sha256": sha256_file(glb),
            "tess": {"linear_mm": tess.get("linear_mm"), "angular_deg": tess.get("angular_deg")} if tess else None,
            "engine_version": m.get("engine_version") if isinstance(m.get("engine_version"), str) else engine_version}


def prep_view(base: str) -> dict[str, Any]:
    """prep.json `view`(없으면 MISSING). 파일이 사라졌으면 MISSING으로 본다(준비본 유효성과는 무관, §2.3)."""
    prep = read_json(os.path.join(base, "native", "prep.json")) or {}
    v = prep.get("view") if isinstance(prep.get("view"), dict) else None
    if not v:
        return {"status": MISSING}
    if v.get("status") == READY and not os.path.isfile(os.path.join(base, *VIEW_DIR.split("/"), VIEW_GLB)):
        return {**v, "status": MISSING}
    return v


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def prep_digest(prep: Mapping[str, Any] | None, opts: Mapping[str, Any]) -> str:
    """준비본 입력 sha256들 + tag 옵션 sha256 + 유효 geom options 전체 sha256 + (쉘) fixed_digest(§6.4)."""
    p = prep or {}
    doc = {"inputs": p.get("inputs"), "tag_options_sha256": p.get("tag_options_sha256"), "fixed_digest": p.get("fixed_digest"),
           "options_sha256": hashlib.sha256(canonical(opts).encode("utf-8")).hexdigest()}
    return hashlib.sha256(canonical(doc).encode("utf-8")).hexdigest()


def preview_cache_key(*, param_set_id: str, kind: str, prep_digest: str, view_tess: Mapping[str, Any] | None,
                      values: Mapping[str, float], fe: str, engine_version: str) -> str:
    doc = {"param_set_id": param_set_id, "kind": kind, "prep_digest": prep_digest,
           "view_tess": {k: float(v) for k, v in (view_tess or {}).items() if v is not None},
           "values": {k: float(v) for k, v in values.items()}, "fe": fe, "engine_version": engine_version}
    return hashlib.sha256(canonical(doc).encode("utf-8")).hexdigest()


def cache_rel(prefix: str, key: str) -> str:
    return f"{prefix}/{key[:2]}/{key}"


def judge_preview(manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    """§6.4 판정: manifest 있음·status OK/FAIL·FAIL category ∉ {VIEW, INPUT, INTERNAL} → 성공(결과 캐시). 그 밖 → 인프라 실패.
    반환 {cacheable, result_status, code, category, fe_status, fe_code, message}."""
    if not manifest or manifest.get("status") not in ("OK", "FAIL"):
        return {"cacheable": False, "result_status": None, "code": "OUTPUT_MISSING", "category": None, "fe_status": None, "fe_code": None,
                "message": None}
    st = manifest["status"]
    cat = manifest.get("category") if isinstance(manifest.get("category"), str) else None
    code = manifest.get("code") if isinstance(manifest.get("code"), str) else None
    fe = manifest.get("fe") if isinstance(manifest.get("fe"), dict) else {}
    out = {"cacheable": True, "result_status": st, "code": code, "category": cat,
           "fe_status": fe.get("status") if isinstance(fe.get("status"), str) else None,
           "fe_code": fe.get("code") if isinstance(fe.get("code"), str) else None,
           "message": manifest.get("message") if isinstance(manifest.get("message"), str) else None}
    if st == "FAIL" and (cat in ("VIEW", "INPUT", "INTERNAL") or (code or "").startswith("VIEW_")):
        out["cacheable"] = False
    return out


def safe_cache_dir(study_root: str, path: str, prefix: str) -> bool:
    """삭제 전 확인(§6.6): 실경로가 `<study>/<prefix>/` 아래이고 경로 위 링크·reparse point가 없다."""
    from ..path_links import is_link_or_reparse

    base = os.path.realpath(os.path.join(study_root, *prefix.split("/")))
    real = os.path.realpath(path)
    if not real.startswith(base + os.sep):
        return False
    cur = os.path.abspath(path)
    stop = os.path.abspath(study_root)
    while cur.startswith(stop) and cur != stop:
        if is_link_or_reparse(cur):
            return False
        cur = os.path.dirname(cur)
    return True


def dir_bytes(path: str) -> int:
    total = 0
    for dp, dn, fn in os.walk(path, followlinks=False):
        for f in fn:
            try:
                total += os.lstat(os.path.join(dp, f)).st_size
            except OSError:
                pass
    return total
