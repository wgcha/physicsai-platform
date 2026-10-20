"""플랫폼 버전 표시·버전 게시판(읽기 전용 — 배포로만 기록, RELEASES.md).

GET /version·/releases만 있고 POST·PUT·PATCH·DELETE는 없다(라우트 표·405로 강제). 파서·검사 스크립트·배포 묶음 포함 여부도 시험한다."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from physicsai_test_support import API, H

REPO = Path(__file__).resolve().parents[2]

SAMPLE = """# 머리말

설명 문단은 무시한다.

## 0.3.0 — 2026-11-01

- 새 기능 A
- 긴 항목
  다음 줄에 이어짐

## 0.2.0 — 2026-10-20

- 기능 B
"""


def _app(settings_dict, engine, fake_dashboard, frontend_root):
    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    d = copy.deepcopy(settings_dict)
    d["server"] = {**d.get("server", {}), "frontend_root": frontend_root}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    return create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler)))


# ---------------------------------------------------------------- 파서·검사


def test_parse_releases_items_and_continuation():
    from physicsai_core.releases import parse_releases, validate_releases

    rels = parse_releases(SAMPLE)
    assert [(r.version, r.date) for r in rels] == [("0.3.0", "2026-11-01"), ("0.2.0", "2026-10-20")]
    assert rels[0].items == ["새 기능 A", "긴 항목 다음 줄에 이어짐"]
    assert validate_releases(rels) == []


@pytest.mark.parametrize(
    "text,needle",
    [
        ("## 0.2 — 2026-10-20\n- a\n", "버전 제목 형식"),
        ("## 0.2.0 — 2026-10-20\n그냥 문장\n", "목록이어야"),
    ],
)
def test_parse_releases_format_errors(text, needle):
    from physicsai_core.releases import ReleasesFormatError, parse_releases

    with pytest.raises(ReleasesFormatError, match=needle):
        parse_releases(text)


def test_validate_releases_order_and_empty():
    from physicsai_core.releases import parse_releases, validate_releases

    assert validate_releases([]) != []
    errs = validate_releases(parse_releases("## 0.1.0 — 2026-10-20\n- a\n## 0.2.0 — 2026-10-21\n\n## 0.2.0 — 2026-10-01\n- c\n"))
    assert any("버전 순서" in e for e in errs) and any("날짜 순서" in e for e in errs) and any("목록" in e for e in errs)


def test_repo_releases_matches_platform_version():
    """저장소 RELEASES.md 최상단 = pyproject version = physicsai_core.__version__ (scripts/check_releases.py와 같은 규칙)."""
    from physicsai_core import __version__
    from physicsai_core.releases import parse_releases

    rels = parse_releases((REPO / "RELEASES.md").read_text(encoding="utf-8"))
    assert rels[0].version == __version__
    assert f'version = "{__version__}"' in (REPO / "pyproject.toml").read_text(encoding="utf-8")


def _mini_repo(tmp_path, top="0.2.0", py="0.2.0", core="0.2.0", deploy_ok=True):
    (tmp_path / "backend/physicsai_core").mkdir(parents=True)
    (tmp_path / "backend/physicsai_core/__init__.py").write_text(f'__version__ = "{core}"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{py}"\n\n[tool.x]\n', encoding="utf-8")
    (tmp_path / "RELEASES.md").write_text(f"## {top} — 2026-10-20\n- a\n", encoding="utf-8")
    (tmp_path / "deploy").mkdir()
    for f in ("collect-offline.ps1", "collect-offline.sh", "install-common.ps1"):
        (tmp_path / "deploy" / f).write_text("copy RELEASES.md\n" if deploy_ok else "copy\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "kw,ok,needle",
    [
        ({}, True, "통과"),
        ({"top": "0.3.0"}, False, "RELEASES.md 최상단 버전"),
        ({"core": "0.1.0"}, False, "physicsai_core.__version__"),
        ({"deploy_ok": False}, False, "배포 묶음"),
    ],
)
def test_check_releases_script(tmp_path, kw, ok, needle):
    root = _mini_repo(tmp_path, **kw)
    r = subprocess.run([sys.executable, str(REPO / "scripts/check_releases.py"), "--root", str(root)],
                       capture_output=True, text=True, timeout=60)
    assert (r.returncode == 0) is ok, r.stdout + r.stderr
    assert needle in r.stdout + r.stderr


def test_deploy_bundles_include_releases():
    """설치 묶음(collect-offline)과 git 설치(install-common)가 RELEASES.md를 프런트 배치 폴더에 함께 둔다(추가만)."""
    assert "'RELEASES.md' 'dist\\frontend\\RELEASES.md'" in (REPO / "deploy/collect-offline.ps1").read_text(encoding="utf-8-sig")
    assert "cp RELEASES.md dist/frontend/RELEASES.md" in (REPO / "deploy/collect-offline.sh").read_text(encoding="utf-8")
    common = (REPO / "deploy/install-common.ps1").read_text(encoding="utf-8-sig")
    assert common.count("-Releases (Join-Path $RepoRoot 'RELEASES.md')") == 2


def test_git_commit_reads_worktree_and_packed_refs(tmp_path):
    from physicsai_core.releases import git_commit_of

    sha = "a" * 40
    common = tmp_path / "main.git"
    (common / "worktrees/w").mkdir(parents=True)
    (common / "packed-refs").write_text(f"# pack-refs\n{sha} refs/heads/feat\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {common / 'worktrees/w'}\n", encoding="utf-8")
    (common / "worktrees/w/HEAD").write_text("ref: refs/heads/feat\n", encoding="utf-8")
    (common / "worktrees/w/commondir").write_text("../..\n", encoding="utf-8")
    assert git_commit_of(wt) == sha
    assert git_commit_of(tmp_path / "none") is None
    assert git_commit_of(None) is None


# ---------------------------------------------------------------- API


def test_version_and_releases_from_installed_frontend_root(settings_dict, tmp_path, engine, fake_dashboard):
    from physicsai_core import __version__
    from physicsai_core import releases as R

    fe = tmp_path / "fe"
    fe.mkdir()
    (fe / "index.html").write_text("<p/>", encoding="utf-8")
    (fe / "RELEASES.md").write_text(SAMPLE, encoding="utf-8")
    (fe / "BUILD_INFO.json").write_text(json.dumps({"source_hash": "f" * 64, "built_at": "2026-10-20T00:00:00Z", "git_commit": "b" * 40}),
                                        encoding="utf-8")
    R._cache.clear()
    app = _app(settings_dict, engine, fake_dashboard, str(fe))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get(f"{API}/version").status_code == 401  # 로그인 필요
        v = c.get(f"{API}/version", headers=H("tok-general")).json()
        assert v["platform_version"] == __version__
        assert v["build"] == {"source_hash": "f" * 64, "built_at": "2026-10-20T00:00:00Z"}
        assert v["git_commit"] == "b" * 40
        assert "paicad_version" in v
        r = c.get(f"{API}/releases", headers=H("tok-general")).json()
        assert r["current_version"] == __version__
        assert [x["version"] for x in r["releases"]] == ["0.3.0", "0.2.0"]
        assert r["releases"][0]["items"][1] == "긴 항목 다음 줄에 이어짐"
        # 캐시: 같은 파일(mtime·크기)이면 다시 파싱하지 않음, 바뀌면 다시 읽음
        assert str(fe / "RELEASES.md") in R._cache
        (fe / "RELEASES.md").write_text("## 0.4.0 — 2026-12-01\n- 새 배포\n" + SAMPLE.split("\n", 4)[-1], encoding="utf-8")
        r2 = c.get(f"{API}/releases", headers=H("tok-general")).json()
        assert r2["releases"][0]["version"] == "0.4.0"


def test_releases_missing_or_broken_file_is_empty_not_error(settings_dict, tmp_path, engine, fake_dashboard, monkeypatch):
    from physicsai_core import releases as R

    monkeypatch.setattr(R, "source_repo_root", lambda: None)  # 설치본처럼(저장소 폴백 없음)
    fe = tmp_path / "fe"
    fe.mkdir()
    (fe / "index.html").write_text("<p/>", encoding="utf-8")
    app = _app(settings_dict, engine, fake_dashboard, str(fe))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get(f"{API}/releases", headers=H("tok-general")).json()["releases"] == []
        v = c.get(f"{API}/version", headers=H("tok-general")).json()
        assert v["build"] is None and v["git_commit"] is None
        (fe / "RELEASES.md").write_text("## 잘못된 제목\n", encoding="utf-8")
        assert c.get(f"{API}/releases", headers=H("tok-general")).json()["releases"] == []


def test_source_run_falls_back_to_repo_releases(client):
    """소스 실행(frontend_root 없음)이면 저장소 루트 RELEASES.md·frontend-dist/BUILD_INFO.json."""
    r = client.get(f"{API}/releases", headers=H("tok-general")).json()
    assert r["releases"] and r["releases"][0]["version"] == r["current_version"]
    v = client.get(f"{API}/version", headers=H("tok-general")).json()
    assert v["build"] and v["build"]["source_hash"]


def test_version_board_is_read_only(app_ctx):
    """쓰기 불가 — 배포로만 기록: 라우트는 GET뿐, 쓰기 메서드는 405, openapi에도 GET만."""
    from physicsai_api.export_openapi import render
    from physicsai_api.main import create_app

    app = create_app(app_ctx)
    client = TestClient(app, base_url="http://127.0.0.1")

    from physicsai_api.routers import releases as router_mod

    for route in router_mod.router.routes:  # 이 라우터는 GET만
        assert set(route.methods) <= {"GET", "HEAD"}, (route.path, route.methods)
    assert {r.path for r in router_mod.router.routes} == {"/version", "/releases"}
    for p in ("/version", "/releases", "/releases/0.2.0"):
        for meth in ("POST", "PUT", "PATCH", "DELETE"):
            r = client.request(meth, f"{API}{p}", headers=H("tok-admin", write=True), json={})
            assert r.status_code in (404, 405), (meth, p, r.status_code)
    spec = json.loads(render())
    for p in ("/version", "/releases"):
        assert set(spec["paths"][f"{API}{p}"]) == {"get"}
    assert not [p for p in spec["paths"] if p.startswith((f"{API}/version/", f"{API}/releases/"))]


def test_installed_version_reads_dist_info_without_import(tmp_path):
    from physicsai_core.releases import installed_version

    d = tmp_path / "paicad-9.9.9.dist-info"
    d.mkdir()
    (d / "METADATA").write_text("Metadata-Version: 2.1\nName: paicad\nVersion: 9.9.9\n\nbody\n", encoding="utf-8")
    assert installed_version("paicad", [str(tmp_path)]) == "9.9.9"
    assert installed_version("nothing", [str(tmp_path)]) is None
