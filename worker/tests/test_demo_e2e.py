"""시연 모드 E2E(deploy/demo): 시연 설정으로 실제 백엔드·워커 프로세스를 띄워 ①→②→③→④ 한 바퀴 + ⑤ 취소.

- deploy/demo/demo_setup.py init/seed 를 그대로 쓴다(설치 스크립트의 Linux 대응은 하지 않음).
- 로그인은 내장 가짜 대시보드(시연 로그인 화면 POST → 쿠키)로 한다. 대시보드 없음.
- ⑤는 가짜 hstpy를 hang 모드로 두고 실행 중 취소 → CANCELED + 자식 프로세스 트리 종료를 확인한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psutil
import pytest

from physicsai_test_support import REPO, _free_port

API = "/physicsai/api"
DEMO = REPO / "deploy" / "demo" / "demo_setup.py"
WH = {"X-PhysicsAI-Request": "1"}


def _env(db_url: str, cfg: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "PHYSICSAI_"))}
    env.update({
        "PYTHONPATH": os.pathsep.join([str(REPO / "backend"), str(REPO / "worker")]),
        "PHYSICSAI_CONFIG": str(cfg),
        "PHYSICSAI_DATABASE_URL": db_url,
        "PYTHONIOENCODING": "utf-8",
    })
    env.update(extra or {})
    return env


def _wait_job(c: httpx.Client, jid: str, states=("SUCCEEDED",), timeout=90.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"{API}/jobs/{jid}").json()
        if j["state"] in states:
            return j
        if j["state"] in ("FAILED", "CANCELED", "INTERRUPTED") and j["state"] not in states:
            raise AssertionError(f"작업 실패: {json.dumps(j, ensure_ascii=False)[:2000]}")
        time.sleep(0.3)
    raise AssertionError(f"시간 초과: {jid} {c.get(f'{API}/jobs/{jid}').json()['state']}")


def _submit(c: httpx.Client, sid: str, jt: str, params: dict, expect: int = 201) -> dict:
    r = c.post(f"{API}/studies/{sid}/jobs", headers=WH, json={"job_type": jt, "params": params})
    assert r.status_code == expect, r.text
    return r.json()


@pytest.mark.timeout(420)
def test_demo_mode_end_to_end(tmp_path, db_url):
    root = tmp_path / "demo"
    fe = tmp_path / "fe_dist"
    (fe / "assets").mkdir(parents=True)
    (fe / "index.html").write_text("<!doctype html><title>PhysicsAI</title><div id=root></div>", encoding="utf-8")
    (fe / "assets" / "app.js").write_text("console.log('x')", encoding="utf-8")
    port = _free_port()
    r = subprocess.run([sys.executable, str(DEMO), "init", "--root", str(root), "--port", str(port), "--frontend", str(fe)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = Path(json.loads(r.stdout.strip().splitlines()[-1])["config"])
    pidfile = tmp_path / "hang.pid"
    env = _env(db_url, cfg, {"FAKE_TOOL_MODE_HSTPY": "hang", "FAKE_TOOL_PIDFILE": str(pidfile), "FAKE_SIMLAB_STEP_S": "0.05",
                             "FAKE_DEMO_DELAY_S": "0"})
    base = f"http://127.0.0.1:{port}"
    state = root / "state" / "demo-procs.json"

    def logs() -> str:
        return "".join(f"\n--- {f.name}\n" + f.read_text(errors="replace")[-4000:] for f in (root / "logs").glob("*.log"))

    try:
        # start-demo.ps1이 부르는 것과 같은 up: migration → 백엔드 → seed → 워커
        r = subprocess.run([sys.executable, str(DEMO), "up", "--root", str(root)], env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=180)
        assert r.returncode == 0, r.stdout + r.stderr + logs()
        assert json.loads(r.stdout.strip().splitlines()[-1]) == {"url": base + "/", "already_running": False}
        r = subprocess.run([sys.executable, str(DEMO), "up", "--root", str(root)], env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        assert r.returncode == 0 and json.loads(r.stdout.strip().splitlines()[-1])["already_running"] is True
        procs = json.loads(state.read_text(encoding="utf-8"))
        assert set(procs) == {"backend", "worker"}

        # ---- 시연 로그인·정적 서빙 ----
        anon = httpx.Client(base_url=base, timeout=30)
        assert anon.get(API + "/status").status_code == 401
        r = anon.get("/", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == API + "/demo/login"
        page = anon.get(API + "/demo/login")
        assert page.status_code == 200 and "시연 모드" in page.text and 'value="power"' in page.text
        assert anon.get("/physicsai/study/xyz").text.startswith("<!doctype html>")  # SPA fallback
        assert anon.get("/physicsai/assets/app.js").text == "console.log('x')"
        trav = anon.get("/physicsai/%2e%2e/%2e%2e/config/platform.yaml")  # 프런트 폴더 밖 → index.html
        assert "ai_root" not in trav.text
        for evil in ("/physicsai//etc/passwd", "/physicsai/C:/Windows/win.ini", f"/physicsai/{cfg.as_posix()}"):
            r = anon.get(evil)
            assert r.status_code == 200 and r.text.startswith("<!doctype html>"), evil  # root 밖 파일은 index.html
        assert anon.get(API + "/nope").status_code == 404
        assert anon.post(API + "/demo/login", data={"role": "root"}).status_code == 422

        def login(role: str) -> httpx.Client:
            c = httpx.Client(base_url=base, timeout=30)
            r = c.post(API + "/demo/login", data={"role": role}, follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/physicsai/", r.text
            assert c.cookies.get("analysis_canvas_session") == f"demo-{role}"
            return c

        c = login("power")
        st = c.get(API + "/status").json()
        assert st["demo"] is True and st["auth"]["mode"] == "demo" and st["config"]["ok"], st["config"]
        assert [p["id"] for p in c.get(API + "/projects").json()] == ["demo"]
        assert c.get(API + "/me").json()["display_name"] == "시연 파워 사용자"

        # ---- 샘플 데이터 ----
        r = subprocess.run([sys.executable, str(DEMO), "seed", "--root", str(root), "--url", base],
                           capture_output=True, text=True, encoding="utf-8", timeout=120, env=env)
        assert r.returncode == 0, r.stdout + r.stderr
        seed = json.loads(r.stdout.strip().splitlines()[-1])
        sid = seed["study_id"]
        r2 = subprocess.run([sys.executable, str(DEMO), "seed", "--root", str(root), "--url", base],
                            capture_output=True, text=True, encoding="utf-8", timeout=120, env=env)
        assert r2.returncode == 0 and json.loads(r2.stdout.strip().splitlines()[-1])["study_id"] == sid  # 재실행 안전

        gen = login("general")
        assert gen.post(f"{API}/studies/{sid}/jobs", headers=WH, json={"job_type": "TD_EXTRACT_PARAMS",
                                                                         "params": {"cad_path": seed["cad"]}}).status_code == 403
        end = time.time() + 30
        while not c.get(API + "/status").json()["worker"]["online"]:
            assert time.time() < end, logs()
            time.sleep(0.3)

        # ---- ① 학습데이터 ----
        j = _submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": seed["cad"]})
        _wait_job(c, j["id"])
        ts = c.get(f"{API}/studies/{sid}/train").json()
        rows = [{"name": p["name"], "min": p["min"], "max": p["max"], "use": p["use"], "format": p["format"]} for p in ts["parameters"]]
        assert {p["name"] for p in ts["parameters"] if p["use"]} == {"THK_1", "RIB_H"}
        r = c.put(f"{API}/studies/{sid}/train/params", headers=WH, json={"version": ts["version"], "parameters": rows})
        assert r.status_code == 200, r.text
        r = c.post(f"{API}/studies/{sid}/train/tpl", headers=WH, json={"version": r.json()["version"]})
        assert r.status_code == 200, r.text
        j = _submit(c, sid, "TD_DOE_GEN", {"doe_label": "LatinHyperCube", "num_runs": 5, "options": {"RANDOM_SEED": 7},
                                           "multi_execution": 2, "radioss_assem_path": seed["radioss_assem"]})
        doe_id = _wait_job(c, j["id"])["result"]["doe_id"]
        assert _submit(c, sid, "TD_SOLVE", {"doe_id": doe_id}, expect=409)["detail"]["code"] == "HPC_NOT_CONFIGURED"
        j = _submit(c, sid, "TD_RESULT_IMPORT", {"doe_id": doe_id, "source_path": seed["results"]})
        res = _wait_job(c, j["id"])["result"]
        assert res["matched"] == 5 and res["missing_runs"] == []

        # ---- ② 데이터 정리 ----
        src = {"kind": "TRAIN_DOE", "doe_id": doe_id}
        pj = _submit(c, sid, "CU_H3D_PREVIEW", {"source": src})
        _wait_job(c, pj["id"])
        sel = {"items": [{"datatype": "Stress", "component": "P1"}], "parts": {"shell": [], "solid": [3], "rbody": []},
               "time_increment": 1}
        cj = _submit(c, sid, "CU_H3D_CURATE", {"source": src, "preview_job_id": pj["id"], "selection": sel})
        cur_id = _wait_job(c, cj["id"])["result"]["curation_id"]

        # ---- ③ 데이터셋·모델 ----
        dj = _submit(c, sid, "DATASET_CREATE", {"curation_id": cur_id})
        assert _wait_job(c, dj["id"])["result"]["h3d_count"] == 5
        mj = _submit(c, sid, "MODEL_REGISTER", {"model_path": seed["model"]})
        model_id = _wait_job(c, mj["id"])["result"]["model_id"]
        ej = _submit(c, sid, "EVALUATE", {"model_id": model_id})
        _wait_job(c, ej["id"])
        assert c.put(f"{API}/studies/{sid}/final-model", headers=WH, json={"model_id": model_id}).status_code == 200

        # ---- ④ 예측(① 결과로 파라미터 세트) ----
        r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=WH, json={"doe_id": doe_id})
        assert r.status_code == 201, r.text
        assert r.json()["sample_count"] == 5
        pr = _submit(c, sid, "PREDICT", {"values": {"THK_1": 3.0, "RIB_H": 12.5}, "value_source": "manual"})
        pres = _wait_job(c, pr["id"])["result"]
        assert pres["preview_json_artifact_id"]

        # ---- ⑤ 최적화 실행 중 취소(가짜 hstpy hang) ----
        resp = [{"name": "MAX_VM", "source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "",
                 "stat": "MAX", "goal": "MINIMIZE"}]
        oj = _submit(c, sid, "OPTIMIZE", {"responses": resp, "max_designs": 4})
        _wait_job(c, oj["id"], states=("RUNNING",))
        end = time.time() + 30
        while not pidfile.exists() or not pidfile.read_text().strip():
            assert time.time() < end
            time.sleep(0.2)
        pids = [int(x) for x in pidfile.read_text().split()]
        assert c.post(f"{API}/jobs/{oj['id']}/cancel", headers=WH).status_code == 403  # 취소는 전역 관리자만
        adm = login("admin")
        assert adm.post(f"{API}/jobs/{oj['id']}/cancel", headers=WH).status_code == 202
        assert _wait_job(c, oj["id"], states=("CANCELED",))["state"] == "CANCELED"
        end = time.time() + 30
        while any(psutil.pid_exists(p) and psutil.Process(p).status() != psutil.STATUS_ZOMBIE for p in pids):
            assert time.time() < end, f"취소 후 남은 프로세스: {pids}"
            time.sleep(0.2)

        # ---- 대기열·알림 ----
        q = c.get(API + "/queue").json()
        assert q["running"] is None or q["running"]["id"] != oj["id"]
        events = [n["event"] for n in c.get(API + "/notifications").json()["items"]]
        assert "JOB_SUCCEEDED" in events and "JOB_CANCELED" in events
        assert adm.get(API + "/status").json()["demo"] is True
        r = adm.get(API + "/demo/logout", follow_redirects=False)
        assert r.status_code == 303 and "analysis_canvas_session" in r.headers.get("set-cookie", "")
    finally:
        r = subprocess.run([sys.executable, str(DEMO), "down", "--root", str(root)], env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    left = [v["pid"] for v in json.loads(state.read_text(encoding="utf-8") or "{}").values()]
    assert left == []
    for v in procs.values():
        assert not psutil.pid_exists(v["pid"]) or psutil.Process(v["pid"]).status() == psutil.STATUS_ZOMBIE
    assert not _alive_url(base)


def _alive_url(base: str) -> bool:
    try:
        return httpx.get(base + API + "/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.timeout(180)
def test_demo_db_up_down():
    """시연 전용 PostgreSQL: db-up(initdb·시작·DB 생성, 재실행 안전) → 접속 → db-down. 파일은 지우지 않는다."""
    import shutil

    from physicsai_test_support import _find_pg_bin

    pg_bin = _find_pg_bin()
    assert pg_bin, "PostgreSQL 실행 파일이 없습니다(PG_BIN)"
    import tempfile

    work = Path(tempfile.mkdtemp(prefix="physicsai-demo-db-"))  # pytest tmp 상위는 root 전용(0700)이라 별도 폴더
    root = work / "demo"
    root.mkdir()
    port = _free_port()
    pre: list[str] = []
    if hasattr(os, "geteuid") and os.geteuid() == 0:  # initdb는 root 실행 불가 → postgres 계정으로
        shutil.chown(work, user="postgres")
        shutil.chown(root, user="postgres")
        pre = ["runuser", "-u", "postgres", "--"]
    base = [*pre, sys.executable, str(DEMO)]
    try:
        for _ in range(2):
            r = subprocess.run([*base, "db-up", "--root", str(root), "--pg-bin", pg_bin, "--pg-port", str(port)],
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
            assert r.returncode == 0, r.stdout + r.stderr
        url = json.loads(r.stdout.strip().splitlines()[-1])["database_url"]
        assert url == f"postgresql+psycopg://postgres@127.0.0.1:{port}/physicsai_demo"
        from sqlalchemy import create_engine, text

        eng = create_engine(url)
        with eng.connect() as c:
            assert c.execute(text("select current_database()")).scalar() == "physicsai_demo"
        eng.dispose()
    finally:
        r = subprocess.run([*base, "db-down", "--root", str(root)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    assert (root / "pgdata" / "PG_VERSION").is_file()
    shutil.rmtree(work, ignore_errors=True)  # 시험 임시 폴더 정리(시험 코드)
