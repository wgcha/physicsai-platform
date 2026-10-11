"""G SPDM 가져오기: 읽기 전용 복사(원본 불변·링크 거부), 기능 비활성·쓰기 헬퍼의 SPDM 거부(V2-SPDM-1~3)."""

from __future__ import annotations

import builtins
import json
import os
import stat
from pathlib import Path

import pytest

from helpers_stage1 import job, study, submit
from physicsai_test_support import API, H

PW, P = H("tok-power", write=True), H("tok-power")


@pytest.fixture()
def spdm_tree(p2_env):
    c, mk, ai, lc, d = p2_env
    root = Path(d["storage"]["spdm_roots"][0])
    case = root / "PRJ" / "Case 01" / "Scene&1"
    case.mkdir(parents=True)
    (case / "a.h3d").write_bytes(b"H3D" * 1000)
    (case / "b_T01").write_text("T01")
    (case / "c.txt").write_text("skip")
    (case / "CON.h3d").write_bytes(b"x")
    os.symlink(case / "a.h3d", case / "link.h3d")
    outside = ai.parent / "outside"
    outside.mkdir()
    os.symlink(outside, root / "PRJ" / "linkdir")
    return root


def _snapshot(root: Path) -> dict[str, tuple]:
    out = {}
    for dp, dns, fns in os.walk(root):
        for n in dns + fns:
            p = os.path.join(dp, n)
            st = os.lstat(p)
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns, stat.S_IMODE(st.st_mode), st.st_nlink)
    return out


def test_spdm_import_read_only(p2_env, spdm_tree, monkeypatch):
    """V2-SPDM-1·V2-SPDM-2: 경로 검사(공백 허용·루트 밖·링크·..), 스냅샷 불변, 쓰기 계열 0, 하드링크 아님, 이름 정리·manifest."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid = study(c, "sp1")
    spdm_path = str(spdm_tree / "PRJ" / "Case 01")
    insp = c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "SPDM_IMPORT", "path": spdm_path}).json()
    assert insp["ok"] and insp["summary"]["h3d_count"] == 2 and insp["summary"]["t01_count"] == 1 and insp["summary"]["renamed_count"] == 3
    for bad, code in [(str(ai), "PATH_OUTSIDE_ROOT"), (spdm_path + "/../..", "PATH_UNSAFE"),
                      (str(spdm_tree / "PRJ" / "linkdir"), "PATH_UNSAFE"), (str(spdm_tree / "nope"), "PATH_NOT_FOUND")]:
        r = submit(c, sid, "SPDM_IMPORT", {"spdm_path": bad}, expect=422)
        assert r["detail"]["code"] == code, bad
    before = _snapshot(spdm_tree)
    writes: list[str] = []
    real_open = builtins.open
    root_s = str(spdm_tree)

    def guard_open(file, mode="r", *a, **kw):  # noqa: ANN001
        if isinstance(file, (str, os.PathLike)) and str(file).startswith(root_s) and any(ch in mode for ch in "wax+"):
            writes.append(f"open {file} {mode}")
        return real_open(file, mode, *a, **kw)

    def guard(name):
        orig = getattr(os, name)

        def f(*a, **kw):
            if any(isinstance(x, (str, os.PathLike)) and str(x).startswith(root_s) for x in a[:2]):
                if name != "utime" or str(a[0]).startswith(root_s):
                    writes.append(f"{name} {a[:2]}")
            return orig(*a, **kw)
        return f

    j = submit(c, sid, "SPDM_IMPORT", {"spdm_path": spdm_path})
    monkeypatch.setattr(builtins, "open", guard_open)
    for n in ("utime", "chmod", "rename", "replace", "link", "symlink", "remove", "unlink", "mkdir", "makedirs"):
        monkeypatch.setattr(os, n, guard(n))
    try:
        assert w.run_once_light() == "SUCCEEDED", job(c, j["id"])
    finally:
        monkeypatch.undo()
    assert writes == []
    assert _snapshot(spdm_tree) == before
    res = job(c, j["id"])["result"]
    iid = res["import_id"]
    I = ai / "sp1" / "02_import" / iid
    assert res["file_count"] == 3 and res["renamed_count"] == 3
    a_dst = I / "Scene_1" / "a.h3d"
    src_a = spdm_tree / "PRJ" / "Case 01" / "Scene&1" / "a.h3d"
    assert a_dst.read_bytes() == src_a.read_bytes()
    assert os.stat(a_dst).st_ino != os.stat(src_a).st_ino and os.stat(a_dst).st_nlink == 1
    assert os.stat(a_dst).st_mtime_ns == os.stat(src_a).st_mtime_ns
    assert (I / "Scene_1" / "_CON.h3d").is_file() and not (I / "Scene_1" / "link.h3d").exists()
    man = json.loads((I / "import_manifest.json").read_text())
    assert {f["source_rel"] for f in man["files"]} == {"Scene&1/a.h3d", "Scene&1/b_T01", "Scene&1/CON.h3d"}
    imps = c.get(f"{API}/studies/{sid}/spdm-imports", headers=P).json()
    assert imps[0]["status"] == "READY" and imps[0]["file_count"] == 3
    # ② 원천으로 사용
    srcs = c.get(f"{API}/studies/{sid}/curation-sources", headers=P).json()
    assert srcs[0]["kind"] == "SPDM_IMPORT" and srcs[0]["h3d_count"] == 2
    pj = submit(c, sid, "CU_H3D_PREVIEW", {"source": {"kind": "SPDM_IMPORT", "import_id": iid}})
    assert w.run_once_slot() == "SUCCEEDED", job(c, pj["id"])


def test_spdm_disabled_and_write_helpers_refuse(p2_env, tmp_path):
    """V2-SPDM-1·V2-SPDM-3: spdm_roots 비면 409, 쓰기 헬퍼가 SPDM 경로에서 예외."""
    from physicsai_core.errors import StepFailure
    from physicsai_core.fileutil import copy_file, write_json
    from physicsai_core.paths import backup_existing

    c, mk, ai, lc, d = p2_env
    sp = Path(d["storage"]["spdm_roots"][0])
    (sp / "f.h3d").write_text("x")
    with pytest.raises(StepFailure):
        write_json(str(sp / "x.json"), {})
    with pytest.raises(StepFailure):
        copy_file(str(sp / "f.h3d"), str(sp / "g.h3d"))
    with pytest.raises(StepFailure):
        backup_existing(str(ai), [str(sp / "f.h3d")], "j")
    assert not (sp / "x.json").exists() and not (sp / "g.h3d").exists()
    import httpx
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict
    d2 = dict(d)
    d2["storage"] = {**d["storage"], "spdm_roots": []}
    lc2 = load_config_dict(d2, environ={})
    assert lc2.ok, lc2.issues
    ctx = build_context(lc2, mk().engine, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "id": "u-power", "username": "p", "display_name": "p", "account_status": "ACTIVE", "is_global_admin": False,
        "memberships": [{"project_id": "p-1", "role": "power"}]} if r.url.path == "/api/auth/me" else [{"id": "p-1", "name": "x"}])))
    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c2:
        sid = c2.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": "nospdm", "title": "x"}).json()["id"]
        r = c2.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "SPDM_IMPORT", "params": {"spdm_path": "/x"}})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "SPDM_IMPORT_DISABLED"
        st = c2.get(f"{API}/status", headers=P).json()
        assert st["features"]["spdm_import"] == {"enabled": False, "missing": ["storage.spdm_roots"]}
