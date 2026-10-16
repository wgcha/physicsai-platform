"""D3-50(Verifier 지적 반영, phase3 §12 S7·§13 S8): 표시 이름 제어문자 거부, 등록 고아 폴더 방지, discover 복사 TOCTOU,
경로 요소 `:`·끝 마침표/공백 거부, tpl 재작성(BOM·CRLF 유지), inbox_dir 규칙, RENUM 판정 일치, 산출 폴더 tpl 제외, 보관 Study PATCH.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from helpers_api import PW, _sid
from physicsai_test_support import API, TPL_TEXT, make_assem_files, make_param_set_folder

BAD_LABELS = ["a\x00b", "줄\n바꿈", "탭\t", "abc\u202edef", "영폭\u200b", "\u2028x"]


def _project(root: Path, name: str = "proj", *, tpl_bytes: bytes | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "simlab_parametered_mesh.tpl").write_bytes(tpl_bytes if tpl_bytes is not None else TPL_TEXT.encode("utf-8"))
    (d / "01_CAD").mkdir()
    (d / "01_CAD" / "bracket.x_t").write_text("CAD")
    make_assem_files(d / "RADIOSS_ASSEM")
    return d


def _entries(p: Path) -> list[str]:
    return sorted(os.listdir(p)) if p.is_dir() else []


# ---------------------------------------------------------------------------------------------------------------------
# 1. label 검증(4경로) + 등록 실패 시 04_params 고아 없음
# ---------------------------------------------------------------------------------------------------------------------


def test_label_problem_and_service_check():
    from physicsai_api.services.stage4_predict import _label
    from physicsai_core.errors import DomainError
    from physicsai_core.naming import label_problem

    for bad in BAD_LABELS:
        assert label_problem(bad), repr(bad)
        with pytest.raises(DomainError) as ei:
            _label(bad)
        assert ei.value.status == 422 and ei.value.code == "LABEL_INVALID"
    for ok in ("쿠션 v1", "A-1 (최종)", "  공백 앞뒤  ", "🙂 emoji"):
        assert label_problem(ok) is None
    assert _label("  쿠션  ") == "쿠션" and _label("") is None and _label(None) is None


@pytest.mark.parametrize("bad", BAD_LABELS)
def test_label_rejected_on_all_paths_before_copy(client, loaded_config, bad):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    ref = make_param_set_folder(ai / "S1" / "00_inbox")
    proj = _project(ai / "S1" / "00_inbox")
    params, tmp = ai / "S1" / "04_params", ai / "S1" / "logs" / "_paramset_tmp"
    before = (_entries(params), _entries(tmp))
    # 폴더 등록·프로젝트 폴더(discover) 등록·①→④·PATCH 모두 422, 사본(04_params·임시 폴더)을 만들지 않는다
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(ref), "label": bad})
    assert r.status_code == 422, r.text
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(proj), "mode": "discover", "label": bad})
    assert r.status_code == 422, r.text
    r = client.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": "x", "label": bad})
    assert r.status_code == 422, r.text
    assert (_entries(params), _entries(tmp)) == before
    ps = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(ref), "label": "정상"}).json()
    r = client.patch(f"{API}/param-sets/{ps['id']}", headers=PW, json={"label": bad})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    assert client.get(f"{API}/param-sets/{ps['id']}", headers=PW).json()["label"] == "정상"


@pytest.mark.parametrize("where", ["insert", "after_move"])
def test_register_db_failure_leaves_no_orphan(client, loaded_config, monkeypatch, where):
    from physicsai_core.db.repositories import param_sets as ps_repo
    from physicsai_core.errors import DomainError

    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    ref = make_param_set_folder(ai / "S1" / "00_inbox")
    proj = _project(ai / "S1" / "00_inbox")
    params, tmp = ai / "S1" / "04_params", ai / "S1" / "logs" / "_paramset_tmp"

    def boom(*_a, **_k):
        raise DomainError("DB_FAIL", "시험용 실패", status=503)

    # insert 실패(이동 전) / 이동 뒤 같은 트랜잭션 안 실패(commit 안 됨) — 둘 다 04_params에 DB 행 없는 폴더가 남지 않는다
    monkeypatch.setattr(ps_repo, "insert_current" if where == "insert" else "get", boom)
    for body in ({"path": str(ref)}, {"path": str(proj), "mode": "discover"}):
        r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json=body)
        assert r.status_code == 503, r.text
        assert _entries(params) == []
    # 미등록 정규화본은 logs/_paramset_tmp에 남는다(삭제 호출 없음)
    assert [n for n in _entries(tmp) if n.endswith(".out")] and all((tmp / n / "source.json").is_file()
                                                                  for n in _entries(tmp) if n.endswith(".out"))
    monkeypatch.undo()
    assert client.get(f"{API}/studies/{sid}/param-sets", headers=PW).json() == []
    assert client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(ref)}).status_code == 201
    assert len(_entries(params)) == 1


def test_patch_archived_study_409(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    ref = make_param_set_folder(ai / "S1" / "00_inbox")
    ps = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(ref)}).json()
    assert client.post(f"{API}/studies/{sid}/archive", headers=PW).status_code == 200
    r = client.patch(f"{API}/param-sets/{ps['id']}", headers=PW, json={"label": "새 이름"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STUDY_ARCHIVED"


# ---------------------------------------------------------------------------------------------------------------------
# 2. discover 등록 복사 TOCTOU(복사 직전 재검사 + 열린 핸들 기준)
# ---------------------------------------------------------------------------------------------------------------------


def _disc(settings, proj: Path):
    from physicsai_core.stage4_predict import param_discover as pd

    d = pd.discover(str(proj), settings)
    tpl, cad, assem, probs = pd.resolve_choice(d, {})
    assert not d.problems and not probs and tpl and cad and assem
    return pd, d, tpl, cad, assem


def test_copy_rechecks_links_and_root(loaded_config, tmp_path):
    from physicsai_core.errors import DomainError

    s = loaded_config.settings
    ai = Path(s.storage.ai_root)
    proj = _project(ai / "S1" / "00_inbox")
    outside = tmp_path / "outside"
    make_assem_files(outside / "assem")
    (outside / "secret.x_t").write_text("SECRET")
    pd, d, tpl, cad, assem = _disc(s, proj)
    # 정상: planned_bytes와 복사 총량이 같다(조립 폴더 파일 판정 공통)
    assert pd.copy_sources(d, tpl, cad, assem, str(tmp_path / "ok"), s) == pd.planned_bytes(d, tpl, cad, assem, s)
    # CAD가 discover 뒤 링크로 바뀜 → 422 PATH_UNSAFE
    cadp = proj / "01_CAD" / "bracket.x_t"
    os.replace(cadp, proj / "01_CAD" / "moved.x_t")
    os.symlink(outside / "secret.x_t", cadp)
    with pytest.raises(DomainError) as ei:
        pd.copy_sources(d, tpl, cad, assem, str(tmp_path / "a1"), s)
    assert ei.value.status == 422 and ei.value.code == "PATH_UNSAFE"
    os.remove(cadp)
    os.replace(proj / "01_CAD" / "moved.x_t", cadp)
    # 조립 폴더 자체가 링크(junction 대용)로 바뀜 → listdir 전에 거부
    os.replace(proj / "RADIOSS_ASSEM", proj / "RADIOSS_ASSEM_old")
    os.symlink(outside / "assem", proj / "RADIOSS_ASSEM", target_is_directory=True)
    with pytest.raises(DomainError) as ei:
        pd.copy_sources(d, tpl, cad, assem, str(tmp_path / "a2"), s)
    assert ei.value.code == "PATH_UNSAFE"
    assert not (tmp_path / "a2" / "radioss_assem").exists()


@pytest.mark.parametrize("nofollow", [True, False], ids=["posix_O_NOFOLLOW", "windows_like_ino_compare"])
def test_copy_rejects_swap_between_check_and_open(loaded_config, tmp_path, monkeypatch, nofollow):
    """검사(lstat) 뒤·열기 전에 원본이 링크로 바뀌는 경쟁: O_NOFOLLOW(POSIX) 또는 연 핸들 (dev, ino) 비교(Windows 방식)로 409."""
    from physicsai_core.errors import DomainError

    s = loaded_config.settings
    proj = _project(Path(s.storage.ai_root) / "S1" / "00_inbox")
    (tmp_path / "secret.inc").write_text("SECRET")
    pd, d, tpl, cad, assem = _disc(s, proj)
    if not nofollow:
        monkeypatch.setattr(pd, "_O_NOFOLLOW", 0)
    target = proj / "RADIOSS_ASSEM" / "material.inc"
    real_open = os.open

    def racing_open(path, flags, *a, **k):
        if os.path.normcase(str(path)) == os.path.normcase(str(target)) and not os.path.islink(target):
            link = proj / "RADIOSS_ASSEM" / "tmp_link"
            os.symlink(tmp_path / "secret.inc", link)
            os.replace(link, target)
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(pd.os, "open", racing_open)
    with pytest.raises(DomainError) as ei:
        pd.copy_sources(d, tpl, cad, assem, str(tmp_path / "dst"), s)
    assert ei.value.status == 409 and ei.value.code == "SOURCE_CHANGED"
    assert not (tmp_path / "dst" / "radioss_assem" / "material.inc").exists()


def test_planned_bytes_matches_copy_renum_rule(loaded_config, tmp_path):
    s = loaded_config.settings
    proj = _project(Path(s.storage.ai_root) / "S1" / "00_inbox")
    (proj / "RADIOSS_ASSEM" / "old_RENUM_INIT.csv").write_text("x" * 5000)  # 이름이 RENUM으로 끝나도 복사 대상 아님
    pd, d, tpl, cad, assem = _disc(s, proj)
    names = pd.assem_files(str(proj / "RADIOSS_ASSEM"), s.predict.renum_csv_name)
    assert "old_RENUM_INIT.csv" not in names and "RENUM_INIT.csv" in names and "EPS_mesh_0000.rad" not in names
    assert pd.copy_sources(d, tpl, cad, assem, str(tmp_path / "dst"), s) == pd.planned_bytes(d, tpl, cad, assem, s)


# ---------------------------------------------------------------------------------------------------------------------
# 3. 경로 요소 `:`·끝 마침표/공백
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,windows,bad", [
    ("C:\\ai\\S1\\in", True, False),
    ("C:/ai/S1/in", True, False),
    ("C:\\ai\\_platform.", True, True),
    ("C:\\ai\\S1\\_backup::$INDEX_ALLOCATION\\x", True, True),
    ("C:\\ai\\S1\\file.txt:ads", True, True),
    ("C:\\ai\\S1\\name ", True, True),
    ("C:\\ai\\S1\\a.b.c", True, False),
    ("C:x\\y", True, True),                 # 드라이브 상대
    ("/ai/S1/in", False, False),
    ("/ai/S1/a:b", False, True),
    ("/ai/S1/_platform.", False, True),
    ("/ai/S1/x./y", False, True),
    ("C:/ai", False, True),                 # POSIX에서는 드라이브 예외 없음
])
def test_path_component_problem_strings(raw, windows, bad):
    from physicsai_core.paths import path_component_problem

    assert (path_component_problem(raw, windows=windows) is not None) is bad


@pytest.mark.posix
def test_check_user_path_rejects_colon_and_trailing_dot(loaded_config):
    from physicsai_core.paths import PathError, check_user_path

    ai = Path(loaded_config.settings.storage.ai_root)
    for name in ("a:b", "_backup.", "dots."):
        (ai / "S1" / name).mkdir(parents=True)
        with pytest.raises(PathError) as ei:
            check_user_path(str(ai / "S1" / name), [str(ai)])
        assert ei.value.code == "PATH_UNSAFE"
    assert check_user_path(str(ai / "S1"), [str(ai)]).path == os.path.normpath(ai / "S1")


@pytest.mark.windows
@pytest.mark.skipif(os.name != "nt", reason="Windows 전용 — Linux에서는 문자열 시험으로 대신(CI windows 잡)")
def test_check_user_path_windows_alias_bypass(loaded_config):
    """Windows는 `_platform.`·`_backup::$INDEX_ALLOCATION`을 실제 `_platform`·`_backup` 폴더로 연다 — 이름 비교 전에 거부."""
    from physicsai_core.paths import PathError, check_user_path

    ai = Path(loaded_config.settings.storage.ai_root)
    (ai / "_platform").mkdir(exist_ok=True)
    (ai / "S1" / "_backup").mkdir(parents=True, exist_ok=True)
    for raw in (f"{ai}\\_platform.", f"{ai}\\_platform ", f"{ai}\\S1\\_backup::$INDEX_ALLOCATION", f"{ai}\\S1\\_backup."):
        with pytest.raises(PathError) as ei:
            check_user_path(raw, [str(ai)])
        assert ei.value.code == "PATH_UNSAFE", raw


# ---------------------------------------------------------------------------------------------------------------------
# 4. tpl 재작성: 원본 바이트 기준 첫 줄만, BOM·CRLF 유지
# ---------------------------------------------------------------------------------------------------------------------


def test_rewrite_tpl_bytes_first_line_only_keeps_bom_crlf():
    from physicsai_core.stage4_predict.param_discover import rewrite_tpl_bytes

    rx = r'dir_file_prt\s*=\s*r"[^"]*"'
    raw = b'\xef\xbb\xbfa = 1\r\ndir_file_prt = r"C:\\X\\b.x_t"\r\n# dir_file_prt = r"C:\\Y\\c.x_t"\r\nend\r\n'
    out = rewrite_tpl_bytes(raw, rx, "b.x_t")
    assert out == b'\xef\xbb\xbfa = 1\r\ndir_file_prt = r"./b.x_t"\r\n# dir_file_prt = r"C:\\Y\\c.x_t"\r\nend\r\n'
    assert rewrite_tpl_bytes(b'dir_file_prt = r"x"', rx, "c.x_t") == b'dir_file_prt = r"./c.x_t"'


def test_discover_register_rewrite_keeps_bom_crlf(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    text = TPL_TEXT.replace('dir_file_prt = r"./bracket.x_t"', 'dir_file_prt = r"C:\\DATA\\01_CAD\\bracket.x_t"')
    raw = text.encode("utf-8").replace(b"\n", b"\r\n")
    assert raw.startswith(b"\xef\xbb\xbf")
    proj = _project(ai / "S1" / "00_inbox", tpl_bytes=raw)
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(proj), "mode": "discover"})
    assert r.status_code == 201, r.text
    stored = (ai / "S1" / "04_params" / r.json()["id"] / "simlab_parametered_mesh.tpl").read_bytes()
    assert stored == raw.replace(b'r"C:\\DATA\\01_CAD\\bracket.x_t"', b'r"./bracket.x_t"')


# ---------------------------------------------------------------------------------------------------------------------
# 5·6. inbox_dir 규칙, discover가 Study 산출 폴더 tpl 제외
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("val", ["_backup.", "in:box", "inbox.", "x/_Platform.", "_BACKUP", "a/b:c"])
def test_config_inbox_dir_colon_trailing_dot(settings_dict, val):
    from physicsai_core.config import load_config_dict

    d = {**settings_dict, "storage": {**settings_dict["storage"], "inbox_dir": val}}
    assert "storage.inbox_dir" in load_config_dict(d, environ={}).error_keys()


def test_discover_skips_study_output_dirs(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    ref = make_param_set_folder(ai / "S1" / "00_inbox")
    ps = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(ref)}).json()
    assert (ai / "S1" / "04_params" / ps["id"] / "simlab_parametered_mesh.tpl").is_file()
    d = client.post(f"{API}/studies/{sid}/param-sets/discover", headers=PW, json={"path": str(ai / "S1")}).json()
    assert d["tpl"] and all(not t["rel"].casefold().startswith(("04_params", "logs")) for t in d["tpl"])
    assert all(not a["rel"].startswith("04_params") for a in d["radioss_assem"])
    assert "STUDY_OUTPUT_SKIPPED" in {n["code"] for n in d["notes"]}
    d = client.post(f"{API}/studies/{sid}/param-sets/discover", headers=PW,
                    json={"path": str(ai / "S1" / "04_params" / ps["id"])}).json()
    assert d["tpl"] == [] and "STUDY_OUTPUT_DIR" in {p["code"] for p in d["problems"]}
