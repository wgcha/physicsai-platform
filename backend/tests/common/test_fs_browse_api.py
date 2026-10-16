"""서버 경로 탐색 API(phase3 §12 S7, D3-46): 루트 목록, 목록 정렬·상한·확장자, 경로 거부, 권한."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from physicsai_test_support import API, H

P = H("tok-power")


def _list(c, path, exts=None, token="tok-power"):
    q = {"path": str(path)}
    if exts is not None:
        q["exts"] = exts
    return c.get(f"{API}/fs/list", headers=H(token), params=q)


def _code(r):
    return r.status_code, r.json()["detail"]["code"]


def test_roots_ai_inbox_imports_and_hint(settings_dict, engine, fake_dashboard):
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    ai = Path(settings_dict["storage"]["ai_root"])
    imp = settings_dict["storage"]["allowed_import_roots"][0]
    d = {**settings_dict, "storage": {**settings_dict["storage"], "inbox_share_hint": "\\\\SRV\\physicsai-inbox"}}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    with TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))),
                    base_url="http://127.0.0.1") as c:
        r = c.get(f"{API}/fs/roots", headers=P).json()
        # inbox 폴더가 없으면 생략
        assert [x["key"] for x in r["roots"]] == ["ai_root", "import_0"]
        assert r["inbox_share_hint"] == "\\\\SRV\\physicsai-inbox"
        (ai / "inbox").mkdir()
        r = c.get(f"{API}/fs/roots", headers=P).json()
        assert [(x["key"], x["label"], x["path"]) for x in r["roots"]] == [
            ("ai_root", "AI 루트", os.path.normpath(str(ai))),
            ("inbox", "받은 파일(공유 폴더)", os.path.normpath(str(ai / "inbox"))),
            ("import_0", "추가 허용 폴더", os.path.normpath(imp)),
        ]


def test_roots_default_hint_null_and_inbox_link_hidden(client, loaded_config, tmp_path):
    ai = Path(loaded_config.settings.storage.ai_root)
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", ai / "inbox", target_is_directory=True)
    r = client.get(f"{API}/fs/roots", headers=P).json()
    assert r["inbox_share_hint"] is None and "inbox" not in [x["key"] for x in r["roots"]]


def test_list_sorted_dirs_first_hidden_excluded_no_content(client, loaded_config, tmp_path):
    ai = Path(loaded_config.settings.storage.ai_root)
    base = ai / "S1" / "00_inbox"
    base.mkdir(parents=True)
    for n in ("b_dir", "A_dir", "_BACKUP", "_Platform", ".git"):
        (base / n).mkdir()
    (base / "z.rad").write_text("12345")
    (base / "a.INC").write_text("1")
    (base / "c.txt").write_text("1")
    (base / ".hidden.rad").write_text("1")
    (tmp_path / "out").mkdir()
    os.symlink(tmp_path / "out", base / "link_dir", target_is_directory=True)
    os.symlink(base / "z.rad", base / "link.rad")
    r = _list(client, base)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["path"] == os.path.normpath(str(base)) and j["parent"] == os.path.normpath(str(ai / "S1")) and j["truncated"] is False
    assert [(e["name"], e["type"]) for e in j["entries"]] == [
        ("A_dir", "dir"), ("b_dir", "dir"), ("a.INC", "file"), ("c.txt", "file"), ("z.rad", "file")]
    z = j["entries"][-1]
    assert z["size"] == 5 and z["mtime"] and set(z) <= {"name", "type", "size", "mtime"}
    assert j["entries"][0].get("size") is None
    # 확장자 필터: 파일만 거르고 폴더는 항상(대소문자 무시)
    j = _list(client, base, ".rad,.inc").json()
    assert [e["name"] for e in j["entries"]] == ["A_dir", "b_dir", "a.INC", "z.rad"]
    assert _code(_list(client, base, "rad;x")) == (422, "INVALID_PARAMS")


def test_list_root_has_no_parent_and_cap(client, loaded_config, monkeypatch):
    from physicsai_core import fs_browse

    ai = Path(loaded_config.settings.storage.ai_root)
    imp = Path(loaded_config.settings.storage.allowed_import_roots[0])
    assert _list(client, ai).json()["parent"] is None
    assert _list(client, imp).json()["parent"] is None
    for i in range(7):
        (imp / f"f{i}.rad").write_text("x")
    (imp / "d").mkdir()
    monkeypatch.setattr(fs_browse, "MAX_ENTRIES", 5)
    j = _list(client, imp).json()
    assert j["truncated"] is True and len(j["entries"]) == 5 and j["entries"][0]["name"] == "d"


@pytest.mark.parametrize("make", [
    lambda ai, tmp: str(tmp),                                   # 루트 밖
    lambda ai, tmp: str(ai) + "/S1/../..",                      # ..
    lambda ai, tmp: "\\\\SRV\\share\\x",                         # UNC
    lambda ai, tmp: "//SRV/share/x",                             # UNC(슬래시)
    lambda ai, tmp: str(ai / "S1" / "_BACKUP"),                 # _backup 대소문자 무시
    lambda ai, tmp: str(ai / "_Platform"),                      # _platform 대소문자 무시
    lambda ai, tmp: str(ai / "lnk"),                            # 링크
    lambda ai, tmp: str(ai / "lnk" / "sub"),                    # 링크 하위
    lambda ai, tmp: str(ai / "has space"),                      # 공백
    lambda ai, tmp: "S1/rel",                                   # 상대경로
])
def test_list_rejects_unsafe_paths(client, loaded_config, tmp_path, make):
    ai = Path(loaded_config.settings.storage.ai_root)
    (ai / "S1" / "_BACKUP").mkdir(parents=True)
    (ai / "_Platform").mkdir()
    (ai / "has space").mkdir()
    (tmp_path / "out" / "sub").mkdir(parents=True)
    os.symlink(tmp_path / "out", ai / "lnk", target_is_directory=True)
    r = _list(client, make(ai, tmp_path))
    assert r.status_code == 422 and r.json()["detail"]["code"] in ("PATH_UNSAFE", "PATH_OUTSIDE_ROOT"), r.text


def test_list_missing_and_file_path(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    (ai / "f.rad").write_text("x")
    assert _code(_list(client, ai / "nope")) == (422, "PATH_NOT_FOUND")
    assert _code(_list(client, ai / "f.rad")) == (422, "PATH_NOT_FOUND")


@pytest.mark.parametrize("token,status", [("tok-general", 403), ("tok-power", 200), ("tok-admin", 200)])
def test_permission(client, loaded_config, token, status):
    ai = loaded_config.settings.storage.ai_root
    assert client.get(f"{API}/fs/roots", headers=H(token)).status_code == status
    r = _list(client, ai, token=token)
    assert r.status_code == status
    if status == 403:
        assert r.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_list_logs_path_only(client, loaded_config, caplog):
    ai = Path(loaded_config.settings.storage.ai_root)
    (ai / "secret_name.rad").write_text("본문")
    with caplog.at_level("INFO", logger="physicsai_api.fs"):
        assert _list(client, ai).status_code == 200
    msgs = [r.getMessage() for r in caplog.records if r.name == "physicsai_api.fs"]
    assert msgs and all(os.path.normpath(str(ai)) in m and "secret_name" not in m and "본문" not in m for m in msgs)


@pytest.mark.parametrize("val", ["", "/abs", "C:/x", "../up", "a/../b", "has space", "_backup", "x/_Platform"])
def test_config_inbox_dir_rejected(settings_dict, val):
    from physicsai_core.config import load_config_dict

    d = {**settings_dict, "storage": {**settings_dict["storage"], "inbox_dir": val}}
    assert "storage.inbox_dir" in load_config_dict(d, environ={}).error_keys()
