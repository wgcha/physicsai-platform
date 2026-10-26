"""doe-preview.md V-DP-2·V-DP-11 — 가짜가 아니라 **실제 paicad**(`view grid`)로 DOE_PREVIEW를 끝까지 돌린다(가상 쿠션 골든, 24셀).

가짜 paicad가 가정한 출력(grid_manifest 키·셀 폴더·종료코드)과 실제가 어긋나면 이 시험이 깨진다. 같은 본문을 가짜로도 한 번 돌려 두 결과의
셀 필드 모양(키 집합)을 대조한다. 실제 OCP(가상 쿠션 생성)가 필요하다 — `scripts/test-all`의 paicad 단독 시험과 같은 전제.
"""

from __future__ import annotations

import json
import stat
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("OCP", reason="paicad 실제 실행에는 OCP가 필요하다(paicad 단독 시험과 같은 전제)")

from physicsai_test_support import API, H  # noqa: E402

PW, P = H("tok-power", write=True), H("tok-power")
REPO = Path(__file__).resolve().parents[3]


def _real_paicad(tmp: Path) -> str:
    """실제 paicad를 같은 인터프리터로 실행하는 래퍼(설정 `geometry.paicad_path`는 실행 파일 경로)."""
    p = tmp / "paicad_real"
    p.write_text(f"#!{sys.executable}\nimport sys\nfrom paicad.cli import main\nsys.exit(main(sys.argv[1:]))\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


def _cushion_project(root: Path) -> Path:
    sys.path.insert(0, str(REPO / "packages" / "paicad" / "tests"))
    try:
        from data.make_synthetic import make_all
    finally:
        sys.path.pop(0)
    import shutil

    g = make_all(root / "gold")
    proj = root / "proj"
    proj.mkdir(parents=True)
    shutil.copy(g["step"], proj / "cushion.step")
    shutil.copytree(g["assem"], proj / "assem")
    return proj


@pytest.fixture()
def real_env(native_env, tmp_path):
    env = native_env(geometry={"paicad_path": _real_paicad(tmp_path)}, extra={"doe_preview": {"timeout_s_per_cell": 120}})
    proj = _cushion_project(env.imports)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW, json={"path": str(proj), "mode": "discover", "engine": "native", "label": "N"})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    ps = env.c.get(f"{API}/param-sets/{env.job(r.json()['job_id'])['result']['param_set_id']}", headers=P).json()
    env.w.heartbeat_once()
    return env, ps


def test_real_paicad_grid_24_cells(real_env):
    env, ps = real_env
    assert len(ps["parameters"]) >= 10
    body = {"source": {"kind": "param_set", "param_set_id": ps["id"]}, "sampling": {"kind": "lhs", "count": 60, "seed": 7},
            "select": {"order": "change", "limit": 24}}
    r = env.c.post(f"{API}/studies/{env.sid}/doe-previews", headers=PW, json=body)
    assert r.status_code == 202, r.text
    t0 = time.monotonic()
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    wall = time.monotonic() - t0
    pv = env.c.get(f"{API}/doe-previews/{r.json()['id']}", headers=P).json()
    cells = pv["cells"]
    assert pv["status"] == "DONE" and len(cells) == 24 and cells[0]["nominal"] is True, pv
    assert pv["tag_state"] == "tagged" and pv["n_total"] == 60
    n_err = sum(c["status"] == "ERROR" for c in cells)
    assert n_err == 0, [(c["doe_no"], c["code"]) for c in cells if c["status"] == "ERROR"]
    assert all(c["png_artifact_id"] and c["manifest_artifact_id"] for c in cells)
    assert all(c["glb_artifact_id"] for c in cells if c["status"] == "OK")
    assert all(c["glb_artifact_id"] is None for c in cells if c["status"] == "FAIL")
    nom = cells[0]
    assert nom["status"] == "OK" and nom["max_disp_mm"] == 0 and nom["glb_artifact_id"]  # 공칭 셀도 GLB·manifest 제공
    png = env.c.get(f"{API}/artifacts/{nom['png_artifact_id']}/media", headers=P)
    assert png.status_code == 200 and png.headers["content-type"].startswith("image/png") and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    man = env.c.get(f"{API}/artifacts/{nom['manifest_artifact_id']}/content", headers=P).json()
    assert man["thumb"]["file"] == "thumb.png" and man["status"] == "OK"
    jr = env.job(r.json()["job_id"])["result"]
    fails = sorted({c["code"] for c in cells if c["status"] == "FAIL"})
    assert all(c in ("GEOM_FEATURE_COLLISION", "GEOM_UPDATE_INVALID") or c.startswith("GEOM_") for c in fails), fails
    print(f"V-DP-11 real 24 cells: wall {wall:.1f}s render_s {jr.get('render_s')} ok {jr.get('n_ok')} fail {jr.get('n_fail')} error {jr.get('n_error')}")
    assert jr["n_error"] == 0 and jr["n_ok"] + jr["n_fail"] == 24
    assert wall < 90, wall  # V-DP-11 목표(가상 쿠션, parallel 2, chunk 4)
    # 같은 요청 = 전부 캐시 → 200, 작업 없음
    r2 = env.c.post(f"{API}/studies/{env.sid}/doe-previews", headers=PW, json=body)
    assert r2.status_code == 200 and r2.json()["cache_hit"] is True and len(r2.json()["cells"]) == 24
    # 두 번째 페이지(offset 24)는 공칭 없이 24셀 — 첫 페이지 = 공칭 + 23, 이후 = 24
    r3 = env.c.post(f"{API}/studies/{env.sid}/doe-previews", headers=PW, json={**body, "select": {"order": "change", "offset": 24, "limit": 24}})
    assert r3.status_code == 202, r3.text
    assert env.w.run_once_slot() == "SUCCEEDED"
    pv3 = env.c.get(f"{API}/doe-previews/{r3.json()['id']}", headers=P).json()
    assert len(pv3["cells"]) == 24 and not any(c["nominal"] for c in pv3["cells"]) and pv3["cells"][0]["doe_no"] not in [c["doe_no"] for c in cells]
    json.dumps(pv3)


def test_real_paicad_shell_grid_template_argv(tmp_path):
    """쉘(SM1) — 설정 예시의 `commands.paicad_shell_view_grid` 인자 배열을 그대로 채워 실제 `paicad shell view grid`를 돌린다(인자 이름·출력 모양 대조).
    (쉘 세트 등록 전체 흐름은 별도 — 이 시험은 view grid 명령 계약만 본다.) `thumb`·`judge_cell` 처리는 solid와 같은 코드."""
    import subprocess

    import yaml

    sys.path.insert(0, str(REPO / "packages" / "paicad" / "tests"))
    try:
        from conftest import run_cli
        from data.make_synthetic_shell import make_all
    finally:
        sys.path.pop(0)
    from physicsai_core.geometry import doe_preview as dp

    g = make_all(tmp_path / "sm1")
    fx, ex, tg = tmp_path / "fixed", tmp_path / "extract", tmp_path / "tag"
    for argv in (["shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", fx, "--parts", "2001"],
                 ["shell", "extract", "--cad", g["step"], "--assem-dir", g["assem"], "--out-dir", ex]):
        code, log = run_cli(*argv)
        assert code == 0, log
    feats = ex / "shell_features.json"
    code, log = run_cli("shell", "tag", "--cad", g["step"], "--features", feats, "--assem-dir", g["assem"], "--fixed-dir", fx, "--out-dir", tg)
    assert code == 0, log
    doc = json.loads(feats.read_text(encoding="utf-8"))
    nm = [f["name"] for f in doc["features"] if f.get("unit") == "mm"][:2]
    cells = dp.cells_document([("nominal", {}), ("a1", {nm[0]: float(doc["features"][0]["nominal"]) * 1.05}),
                               ("b2", {nm[1]: float([f for f in doc["features"] if f["name"] == nm[1]][0]["nominal"]) * 0.95})])
    cj, tj, vj, oj = (tmp_path / n for n in ("cells.json", "thumb.json", "view.json", "options.json"))
    cj.write_text(json.dumps(cells))
    tj.write_text(json.dumps({"schema_version": 1, "w": 320, "h": 240, "view_dir": [1, -1, 1], "margin": 1.15, "disp_range_mm": [0.0, 2.0],
                              "colormap": "turbo16", "nominal_ghost": True}))
    vj.write_text(json.dumps({"schema_version": 1}))
    oj.write_text(json.dumps({"schema_version": 1}))
    tpl = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))["commands"]["paicad_shell_view_grid"]
    out = tmp_path / "out"
    sub = {"paicad": _real_paicad(tmp_path), "cad_input": str(g["step"]), "features_json": str(feats), "cells_json": str(cj), "fixed_dir": str(fx),
           "tag_dir": str(tg), "options_json": str(oj), "view_options_json": str(vj), "thumb_options_json": str(tj), "threads": "1", "out_dir": str(out)}
    argv = [sub[a[1:-1]] if a.startswith("{") and a.endswith("}") else a for a in tpl]
    r = subprocess.run(argv, capture_output=True, text=True, shell=False, check=False, timeout=300)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    gm = json.loads((out / dp.GRID_MANIFEST).read_text(encoding="utf-8"))
    assert gm["kind"] == "shell" and {c["id"] for c in gm["cells"]} == {"nominal", "a1", "b2"}
    for c in gm["cells"]:
        assert set(c) >= {"id", "status", "code", "category", "max_disp_mm", "total_s"}
        j = dp.judge_cell(c)
        assert j["cacheable"], c
        d = out / "cells" / c["id"]
        assert (d / dp.CELL_MANIFEST).is_file() and (d / dp.THUMB_PNG).is_file()
    assert (out / "cells" / "nominal" / "preview.glb").is_file()
    assert "PAICAD RESULT OK" in r.stdout
