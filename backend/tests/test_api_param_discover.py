"""④ 파라미터 세트 "프로젝트 폴더에서 자동 구성"(phase3 §13 S8, D3-47) + 표시 이름(label).

discover(단일·다수 후보, tpl에서 parameters 생성, CAD 이름 매칭, eps_mesh 조립 폴더 starter 판정, 상한·링크·_BACKUP 제외, 루트 밖 거부),
등록 후 정규화본이 기존 폴더 등록과 같은 구조, 원본 위치 불변, label 등록·변경.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

import httpx

from helpers_api import PW, _sid
from physicsai_test_support import API, MESH_INC, TPL_TEXT, make_assem_files, make_param_set_folder

TEMPLATE_TPL = TPL_TEXT.replace('dir_file_prt = r"./bracket.x_t"',
                                'dir_file_prt = r"C:\\DATA\\PROJECT\\01_CAD\\bracket.x_t"')


def _project(root: Path, name: str = "proj", *, runs: int = 2) -> Path:
    """원본 작업 폴더 형태: 생성 tpl(parameters 파일 없음)·CAD 폴더·조립 폴더·HyperStudy run 폴더·_BACKUP."""
    d = root / name
    d.mkdir(parents=True)
    (d / "simlab_parametered_mesh.tpl").write_text(TPL_TEXT, encoding="utf-8")
    (d / "01_CAD").mkdir()
    (d / "01_CAD" / "bracket.x_t").write_text("CAD")
    make_assem_files(d / "RADIOSS_ASSEM")
    for i in range(runs):  # run마다 starter가 있지만 후보가 아니다
        make_assem_files(d / "approaches" / "doe_1" / f"run__{i + 1:05d}" / "m_1", eps_mesh=False)
    (d / "_BACKUP").mkdir()
    (d / "_BACKUP" / "old.tpl").write_text(TPL_TEXT, encoding="utf-8")
    (d / ".hidden").mkdir()
    make_assem_files(d / ".hidden" / "assem")
    return d


def _discover(c, sid, path, tpl=None):
    body = {"path": str(path)} if tpl is None else {"path": str(path), "tpl": tpl}
    return c.post(f"{API}/studies/{sid}/param-sets/discover", headers=PW, json=body)


def _register(c, sid, path, choice=None, label=None):
    body: dict = {"path": str(path), "mode": "discover"}
    if choice is not None:
        body["choice"] = choice
    if label is not None:
        body["label"] = label
    return c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json=body)


def _tree(p: Path) -> list[str]:
    return sorted(str(x.relative_to(p)).replace(os.sep, "/") for x in p.rglob("*") if x.is_file())


def _snapshot(p: Path) -> dict[str, float]:
    return {str(x): x.stat().st_mtime for x in p.rglob("*")}


@contextlib.contextmanager
def _client(settings_dict, engine, fake_dashboard, **over):
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    for k, v in over.items():
        d[k] = {**(d.get(k) or {}), **v}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    with TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))),
                    base_url="http://127.0.0.1") as c:
        yield c, lc


def test_discover_single_candidates_tpl_parameters_and_register(client, loaded_config):
    s = loaded_config.settings
    ai, imp = Path(s.storage.ai_root), Path(s.storage.allowed_import_roots[0])
    sid = _sid(client)
    proj = _project(imp)                                           # allowed_import_roots 허용(imports=True)
    before = _snapshot(proj)
    r = _discover(client, sid, proj)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["problems"] == [] and d["truncated"] is False
    assert [t["rel"] for t in d["tpl"]] == ["simlab_parametered_mesh.tpl"] and d["selected_tpl"] == "simlab_parametered_mesh.tpl"
    assert d["tpl"][0]["cad_ref"] == "./bracket.x_t" and d["tpl"][0]["parameter_count"] == 2
    assert d["cad"] == [{"rel": "01_CAD/bracket.x_t", "name": "bracket.x_t"}]
    assert [(a["rel"], a["starter"], a["has_eps_mesh"], a["has_renum_csv"]) for a in d["radioss_assem"]] == [
        ("RADIOSS_ASSEM", "model0_0000.rad", True, True)]                      # run·_BACKUP·숨김 폴더 제외
    assert d["parameters_source"] == "tpl" and d["parameters_file"] is None
    assert d["parameters"] == [{"name": "THK_1", "nominal": 3.0, "min": 2.0, "max": 5.0, "unit": ""},
                               {"name": "N_RIB", "nominal": 4.0, "min": 2.0, "max": 8.0, "unit": ""}]
    assert {n["code"] for n in d["notes"]} == {"RUN_DIRS_SKIPPED"}
    # 등록: 후보가 1개씩이면 choice 생략 가능
    r = _register(client, sid, proj, label="쿠션 v1")
    assert r.status_code == 201, r.text
    ps = r.json()
    assert ps["label"] == "쿠션 v1" and ps["origin"] == "FOLDER" and ps["source_path"] == str(proj)
    assert ps["starter_name"] == "model0_0000.rad" and ps["cad_file_name"] == "bracket.x_t"
    assert [p["name"] for p in ps["parameters"]] == ["THK_1", "N_RIB"] and ps["sample_count"] == 0
    stored = ai / "S1" / "04_params" / ps["id"]
    # 기존 폴더 등록(§15.4)과 같은 구조
    ref = make_param_set_folder(ai / "S1" / "00_inbox", with_samples=False, with_responses=False)
    r2 = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(ref)})
    assert r2.status_code == 201, r2.text
    assert r2.json()["label"] is None
    assert _tree(stored) == _tree(ai / "S1" / "04_params" / r2.json()["id"])
    assert (stored / "simlab_parametered_mesh.tpl").read_text(encoding="utf-8-sig") == TPL_TEXT.lstrip("\ufeff")
    assert MESH_INC in os.listdir(stored / "radioss_assem") and "EPS_mesh_0000.rad" not in os.listdir(stored / "radioss_assem")
    src = json.loads((stored / "source.json").read_text(encoding="utf-8"))
    assert src["mode"] == "discover" and src["discovered"]["radioss_assem"] == "RADIOSS_ASSEM"
    assert _snapshot(proj) == before                               # 원본 위치는 읽기만


def test_discover_multiple_candidates_require_choice(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    proj = _project(ai / "S1" / "00_inbox")
    (proj / "TEMAPLATE_simlab_parametered_mesh.tpl").write_text(TEMPLATE_TPL, encoding="utf-8")
    make_assem_files(proj / "other_case", include_base=False, renum_csv=False, eps_mesh=False)
    d = _discover(client, sid, proj).json()
    assert [t["rel"] for t in d["tpl"]] == ["simlab_parametered_mesh.tpl", "TEMAPLATE_simlab_parametered_mesh.tpl"]
    assert d["selected_tpl"] is None and d["cad"] == [] and d["parameters"] == []
    assert "TPL_CHOICE_REQUIRED" in {n["code"] for n in d["notes"]}
    assert [a["rel"] for a in d["radioss_assem"]] == ["RADIOSS_ASSEM", "other_case"]  # eps_mesh·RENUM 있는 폴더 우선
    r = _register(client, sid, proj)
    assert r.status_code == 422
    assert {p["code"] for p in r.json()["detail"]["problems"]} == {"CHOICE_REQUIRED"}
    # 빈 틀 tpl(절대 CAD 경로)을 고르면 파일명으로 CAD를 찾고 등록 사본은 ./<CAD>로 바꾼다
    d = _discover(client, sid, proj, tpl="TEMAPLATE_simlab_parametered_mesh.tpl").json()
    assert d["selected_tpl"] == "TEMAPLATE_simlab_parametered_mesh.tpl" and [c["rel"] for c in d["cad"]] == ["01_CAD/bracket.x_t"]
    assert "TPL_CAD_PATH_REWRITE" in {n["code"] for n in d["notes"]}
    bad = _register(client, sid, proj, choice={"tpl": "TEMAPLATE_simlab_parametered_mesh.tpl", "radioss_assem": "nope"})
    assert bad.status_code == 422 and {p["code"] for p in bad.json()["detail"]["problems"]} == {"CHOICE_INVALID"}
    r = _register(client, sid, proj, choice={"tpl": "TEMAPLATE_simlab_parametered_mesh.tpl", "cad": "01_CAD/bracket.x_t",
                                             "radioss_assem": "other_case"})
    assert r.status_code == 201, r.text
    stored = ai / "S1" / "04_params" / r.json()["id"]
    text = (stored / "simlab_parametered_mesh.tpl").read_text(encoding="utf-8")
    assert 'dir_file_prt = r"./bracket.x_t"' in text and "C:\\DATA" not in text
    assert sorted(os.listdir(stored / "radioss_assem")) == ["material.inc", "model0_0000.rad", "model_0001.rad"]


def test_discover_parameters_file_and_cad_matching(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    proj = _project(ai / "S1" / "00_inbox")
    # tpl 폴더의 같은 이름 CAD가 다른 폴더보다 우선
    (proj / "bracket.x_t").write_text("CAD-root")
    d = _discover(client, sid, proj).json()
    assert [c["rel"] for c in d["cad"]] == ["bracket.x_t"]
    os.replace(proj / "bracket.x_t", proj / "unrelated.x_t")
    # parameters.json이 있으면 사용(단위 유지), 이름이 tpl과 다르면 PARAM_TPL_MISMATCH
    (proj / "parameters.json").write_text(json.dumps({"schema_version": 1, "parameters": [
        {"name": "THK_1", "nominal": 3, "min": 2, "max": 5, "unit": "mm"},
        {"name": "N_RIB", "nominal": 4, "min": 2, "max": 8, "unit": ""}]}))
    (proj / "samples.csv").write_text("run_key,THK_1,N_RIB\nrun_0001,3,4\n")
    d = _discover(client, sid, proj).json()
    assert d["parameters_source"] == "file" and d["parameters_file"] == "parameters.json" and d["samples"] == "samples.csv"
    assert d["parameters"][0]["unit"] == "mm" and d["problems"] == []
    r = _register(client, sid, proj)
    assert r.status_code == 201, r.text
    assert r.json()["sample_count"] == 1 and r.json()["parameters"][0]["unit"] == "mm"
    (proj / "parameters.json").write_text(json.dumps({"schema_version": 1, "parameters": [
        {"name": "OTHER", "nominal": 3, "min": 2, "max": 5, "unit": "mm"}]}))
    assert "PARAM_TPL_MISMATCH" in {p["code"] for p in _discover(client, sid, proj).json()["problems"]}
    os.remove(proj / "parameters.json")
    os.remove(proj / "samples.csv")
    # CAD를 못 찾으면 무엇이 없는지 한국어로
    os.replace(proj / "01_CAD" / "bracket.x_t", proj / "01_CAD" / "renamed.x_t")
    probs = _discover(client, sid, proj).json()["problems"]
    assert [p["code"] for p in probs] == ["CAD_NOT_FOUND"] and "bracket.x_t" in probs[0]["message"]
    assert _register(client, sid, proj).status_code == 422


def test_discover_assem_starter_rules_and_nothing_found(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    empty = ai / "S1" / "00_inbox" / "empty"
    (empty / "a").mkdir(parents=True)
    (empty / "a" / "EPS_mesh_0000.rad").write_text("mesh only")          # eps_mesh는 starter가 아님
    make_assem_files(empty / "two", starters=2)                           # starter 2개 → 후보 아님
    d = _discover(client, sid, empty).json()
    codes = {p["code"]: p["message"] for p in d["problems"]}
    assert set(codes) == {"TPL_NOT_FOUND", "ASSEM_NOT_FOUND"}
    assert "two(2개)" in codes["ASSEM_NOT_FOUND"] and d["radioss_assem"] == []
    r = _register(client, sid, empty)
    assert r.status_code == 422 and {p["code"] for p in r.json()["detail"]["problems"]} == {"TPL_NOT_FOUND", "ASSEM_NOT_FOUND"}


def test_discover_excludes_links_backup_and_rejects_outside(client, loaded_config, tmp_path):
    s = loaded_config.settings
    ai = Path(s.storage.ai_root)
    sid = _sid(client)
    proj = ai / "S1" / "00_inbox" / "linky"
    proj.mkdir(parents=True)
    real = _project(ai / "S1" / "00_inbox", "real")
    os.symlink(real, proj / "linked_dir")                               # 링크 폴더는 따라가지 않음
    (proj / "_Backup").mkdir()
    (proj / "_Backup" / "x.tpl").write_text(TPL_TEXT, encoding="utf-8")
    d = _discover(client, sid, proj).json()
    assert d["tpl"] == [] and d["radioss_assem"] == []
    assert "LINKS_SKIPPED" in {n["code"] for n in d["notes"]}
    outside = _project(tmp_path / "elsewhere")
    r = _discover(client, sid, outside)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT"
    assert _register(client, sid, outside).status_code == 422
    r = _discover(client, sid, real / "_BACKUP")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE"


def test_discover_limits_truncated_and_tpl_size(settings_dict, engine, fake_dashboard):
    with _client(settings_dict, engine, fake_dashboard,
                 param_set={"discover_max_entries": 3, "discover_tpl_max_bytes": 1024}) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid = _sid(c, "LIM")
        proj = _project(ai / "LIM" / "00_inbox")
        d = _discover(c, sid, proj).json()
        assert d["truncated"] is True and d["scanned"] == 3 and "SCAN_TRUNCATED" in {n["code"] for n in d["notes"]}
    with _client(settings_dict, engine, fake_dashboard, param_set={"discover_tpl_max_bytes": 1024, "discover_max_depth": 1}) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid = _sid(c, "BIG")
        proj = _project(ai / "BIG" / "00_inbox")
        (proj / "simlab_parametered_mesh.tpl").write_text(TPL_TEXT + "#" * 2000, encoding="utf-8")
        d = _discover(c, sid, proj).json()
        assert d["tpl"] == [] and "TPL_TOO_LARGE" in {n["code"] for n in d["notes"]}
        deep = proj / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "x.tpl").write_text(TPL_TEXT, encoding="utf-8")         # 깊이 2 > 1 → 찾지 않음
        assert all(t["rel"] != "a/b/x.tpl" for t in _discover(c, sid, proj).json()["tpl"])


def test_param_set_label_patch(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    ref = make_param_set_folder(ai / "S1" / "00_inbox")
    ps = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(ref), "label": "  쿠션 v1 "}).json()
    assert ps["label"] == "쿠션 v1"
    r = client.patch(f"{API}/param-sets/{ps['id']}", headers=PW, json={"label": "쿠션 v2"})
    assert r.status_code == 200 and r.json()["label"] == "쿠션 v2"
    assert client.patch(f"{API}/param-sets/{ps['id']}", headers=PW, json={"label": ""}).json()["label"] is None
    assert client.post(f"{API}/studies/{sid}/param-sets", headers=PW,
                       json={"path": str(ref), "choice": {"tpl": "x"}}).status_code == 422
