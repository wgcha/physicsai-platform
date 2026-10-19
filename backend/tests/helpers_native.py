"""native 시험 공용: 프로젝트 폴더 생성(geometry-engine.md §7.4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from physicsai_test_support import API, H, make_assem_files


def make_project(root: Path, *, parts: bool = False, renum_csv: bool = True, include_base: bool = True,
                 params_json: dict[str, Any] | None = None) -> Path:
    """native 등록용 프로젝트 폴더: STEP(또는 parts/) + 조립 폴더(starter·기준본·RENUM)."""
    d = root / "proj"
    d.mkdir(parents=True, exist_ok=True)
    if parts:
        (d / "parts").mkdir(exist_ok=True)
        for n in ("a.step", "b.step"):
            (d / "parts" / n).write_text("ISO-10303-21;")
    else:
        (d / "bracket.step").write_text("ISO-10303-21;")
    make_assem_files(d / "assem", renum_csv=renum_csv, include_base=include_base)
    if params_json is not None:
        (d / "parameters.json").write_text(json.dumps(params_json))
    return d


def native_set(env, **kw):
    proj = make_project(env.imports, **kw)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=H("tok-power", write=True),
                   json={"path": str(proj), "mode": "discover", "engine": "native", "label": "N"})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    return env.c.get(f"{API}/param-sets/{env.job(r.json()['job_id'])['result']['param_set_id']}", headers=H("tok-power")).json()
