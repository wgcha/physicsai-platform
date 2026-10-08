"""환경 점검(V2-EC-1~3), 오류 묶음(V2-EB-1~2), 팬아웃 취소(V2-CMD-3), 대기열 표시(V2-HPC-1 일부)."""

from __future__ import annotations

import io
import json
import os
import threading
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text

from phase2_helpers import job, study, submit
from physicsai_test_support import API, H, _p2_env

PW, P, A, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin"), H("tok-admin", write=True)


def test_env_check_flow(p2_env, fake_dashboard, engine, monkeypatch):
    """V2-EC-1·V2-EC-2·V2-EC-3: 권한·동시 1건·API 항목·워커 항목·보고서·알림·상태."""
    c, mk, ai, lc, d = p2_env
    assert c.post(f"{API}/admin/env-checks", headers=PW).status_code == 403
    assert c.get(f"{API}/admin/env-checks/latest", headers=A).status_code == 404
    # 워커 오프라인 상태에서 생성
    r = c.post(f"{API}/admin/env-checks", headers=AW)
    assert r.status_code == 202, r.text
    chk = r.json()
    items = {i["key"]: i for i in chk["items"]}
    assert chk["state"] == "PENDING"
    assert items["config.valid"]["status"] == "OK" and items["db.connection"]["status"] == "OK"
    assert items["db.migration_head"]["detail"] == {"current": "0003_hpc_cancel_failed", "head": "0003_hpc_cancel_failed"}
    assert items["auth.dashboard"]["status"] == "OK" and items["auth.projects"]["detail"] == {"count": 2}
    assert items["hpc.gateway"]["status"] == "WARN" and items["worker.heartbeat"]["status"] == "FAIL"
    assert items["altair.edspy_path"]["status"] == "PENDING" and items["altair.edspy_path"]["source"] == "WORKER"
    assert c.post(f"{API}/admin/env-checks", headers=AW).json()["detail"]["code"] == "ENV_CHECK_BUSY"
    # 워커 claim → DONE
    w = mk()
    w.heartbeat_once(with_resources=False)
    assert w.run_env_check_once() == "DONE"
    got = c.get(f"{API}/admin/env-checks/{chk['id']}", headers=A).json()
    assert got["state"] == "DONE" and got["worker_id"] == w.worker_id
    wi = {i["key"]: i for i in got["items"] if i["source"] == "WORKER"}
    assert wi["altair.edspy_path"]["status"] == "OK" and wi["altair.edspy_path"]["detail"]["path"] == d["altair"]["edspy_path"]
    assert wi["altair.hstpy_path"]["status"] == "OK"
    assert wi["probe.hw"]["status"] == "SKIP" and wi["probe.hw"]["message"] == "존재 확인만(인자 미확인)"
    assert wi["resource.pyd_dir"]["status"] == "OK" and wi["resource.launchers.optimization"]["status"] == "OK"
    assert wi["storage.ai_root.write"]["status"] == "OK"
    assert os.listdir(ai / "_platform" / "env_check_tmp") == []  # tempfile 자동 삭제, 남는 파일 0
    assert wi["storage.spdm_roots"]["status"] == "OK" and wi["storage.roots_overlap"]["status"] == "OK"
    if os.name == "nt":  # 시험 설정 제한기 = windows_job(실제 Job Object)
        assert wi["worker.limiter"]["status"] == "OK" and wi["worker.job_object"]["status"] == "OK", (wi["worker.limiter"], wi["worker.job_object"])
    else:
        assert wi["worker.limiter"]["status"] == "WARN" and wi["worker.limiter"]["message"] == "CPU 상한 미적용(비Windows)"
        assert wi["worker.job_object"]["status"] == "SKIP"
    assert wi["gpu.detect"]["status"] == "OK"
    assert got["summary"]["fail"] == 1  # worker.heartbeat(생성 시점 오프라인)
    report = ai / "_platform" / "env_checks" / chk["id"] / "report.json"
    assert json.loads(report.read_text())["summary"] == got["summary"]
    assert got["report_display_path"] == str(report)
    n = c.get(f"{API}/notifications", headers=A).json()["items"]
    assert n[0]["event"] == "ENV_CHECK_DONE" and n[0]["title"].startswith("환경 점검 완료 — 실패 1") and n[0]["job_id"] is None
    st = c.get(f"{API}/status", headers=A).json()["env_check"]
    assert st["latest_id"] == chk["id"] and st["latest_state"] == "DONE" and st["fail"] == 1
    assert c.get(f"{API}/status", headers=P).json()["env_check"] is None
    lst = c.get(f"{API}/admin/env-checks", headers=A).json()
    assert lst[0]["id"] == chk["id"]
    # 만료: 워커 미기동 → EXPIRED, 만료 후 워커 쓰기 거부
    r2 = c.post(f"{API}/admin/env-checks", headers=AW).json()
    with engine.begin() as conn:
        conn.execute(text("update env_checks set expires_at = now() - interval '1 second' where id=:i"), {"i": r2["id"]})
    assert c.get(f"{API}/admin/env-checks/{r2['id']}", headers=A).json()["state"] == "EXPIRED"
    assert w.run_env_check_once() is None
    from physicsai_worker import housekeeping

    assert housekeeping.expire_env_checks(engine) == [r2["id"]]
    from physicsai_core.db.repositories import env_checks as env_repo

    r3 = c.post(f"{API}/admin/env-checks", headers=AW).json()
    with engine.begin() as conn:
        claimed = env_repo.claim(conn, w.worker_id)
        conn.execute(text("update env_checks set expires_at = now() - interval '1 second' where id=:i"), {"i": r3["id"]})
    with engine.begin() as conn:
        assert env_repo.finish(conn, claimed["id"], w.worker_id, state="DONE", worker_items=[], summary={}, report_rel=None) is False
    ev = [x["title"] for x in c.get(f"{API}/notifications", headers=A).json()["items"]]
    assert ev[0].startswith("환경 점검 만료")


def test_env_check_probes_and_failures(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """V2-EC-2: 프로브 실행·시간 초과 트리 종료·실행 파일 없음·빈 값·pyd 개수·GPU 실패."""
    gen = _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {
        "env_check": {"probe_timeout_s": 1.0, "probes": {"edspy": ["{edspy}", "--version"], "simlab": ["{simlab}", "-auto", "x"]}},
        "altair": {"version_label": "fake", "edspy_path": fake_tools["fake_edspy"], "simlab_path": fake_tools["fake_simlab"],
                   "hw_exe_path": str(tmp_path / "missing_hw.exe"), "hyperstudy_path": "", "hvtrans_exe_path": "",
                   "hstpy_path": ""},
    })
    c, mk, ai, lc, d = next(gen)
    try:
        monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "hang")
        monkeypatch.setenv("FAKE_TOOL_MODE_NVIDIA", "fail")
        pyd = Path(d["resources"]["pyd_dir"])
        (pyd / "hst_gen_radioss_core.cp312-win_amd64.pyd").write_bytes(b"x")
        chk = c.post(f"{API}/admin/env-checks", headers=AW).json()
        w = mk()
        assert w.run_env_check_once() == "DONE"
        wi = {i["key"]: i for i in c.get(f"{API}/admin/env-checks/{chk['id']}", headers=A).json()["items"]}
        assert wi["probe.edspy"]["status"] == "FAIL" and "종료코드" in wi["probe.edspy"]["message"]  # fake_edspy unknown → 4
        assert wi["probe.simlab"]["status"] == "FAIL" and wi["probe.simlab"]["message"] == "시간 초과"
        assert wi["altair.hw_exe_path"]["status"] == "FAIL" and wi["altair.hyperstudy_path"]["status"] == "WARN"
        assert wi["altair.hstpy_path"]["status"] == "WARN"  # hyperstudy 비어 파생도 비어 있음
        assert wi["resource.launchers.gen_radioss"]["status"] == "FAIL" and "2개" in wi["resource.launchers.gen_radioss"]["message"]
        assert wi["gpu.detect"]["status"] == "WARN"
        rep = json.loads((ai / "_platform" / "env_checks" / chk["id"] / "report.json").read_text())
        assert "Altair edspy (fake) starting" in rep["probe_output_tails"]["probe.edspy"]
    finally:
        for _ in gen:
            pass


def test_env_check_probe_config_validation(settings_dict):
    """V2-CFG-1: probes argv[0]은 그 도구 placeholder, 다른 placeholder 금지."""
    import copy

    from physicsai_core.config import load_config_dict

    for probes in ({"hw": ["{edspy}", "-v"]}, {"hw": ["{hw}", "{h3d}"]}, {"hw": []}):
        d = copy.deepcopy(settings_dict)
        d["env_check"] = {"probes": probes}
        assert "env_check.probes.hw" in load_config_dict(d, environ={}).error_keys(), probes
    d = copy.deepcopy(settings_dict)
    d["env_check"] = {"probes": {"hw": ["{hw}", "-version"]}}
    assert load_config_dict(d, environ={}).ok


@pytest.mark.windows
def test_job_object_self_test_windows():
    """V2-EC-4: Windows Job Object 자체 시험(Linux에서는 미수행)."""
    if os.name != "nt":
        pytest.skip("Windows 전용 — Linux에서는 미수행(사용자 E2E)")
    import sys

    from physicsai_core.limits import limits_from_settings
    from physicsai_core.config import WorkerCfg
    from physicsai_worker.limiter.windows_job import WindowsJobLimiter, self_test

    lim = limits_from_settings(WorkerCfg(max_logical_cores=2, max_memory_gb=2), (8, 16.0))
    info = self_test(WindowsJobLimiter(), lim, [sys.executable, "-I", "-c", "pass"])
    assert info["in_job"] and info["kill_on_close"] and info["memory_gb"] == 2.0


def test_error_bundle(p2_env, engine, monkeypatch):
    """V2-EB-1·V2-EB-2: 권한·조건·zip 항목·꼬리 상한·TRUNCATED·마스킹."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid = study(c, "eb1")
    cad = ai / "eb1" / "00_inbox" / "x.prt"
    cad.parent.mkdir(parents=True, exist_ok=True)
    cad.write_text("x")
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "fail")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    r = c.get(f"{API}/jobs/{j['id']}/error-bundle.zip", headers=P)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ERROR_BUNDLE_NOT_AVAILABLE"
    assert w.run_once_slot() == "FAILED"
    log = ai / "eb1" / "logs" / j["id"] / "job.log"
    secret_url = "postgresql+psycopg://physicsai_app:S3cretPw@127.0.0.1:5432/physicsai"
    monkeypatch.setenv("PHYSICSAI_DATABASE_URL", secret_url)
    monkeypatch.setenv("MY_API_TOKEN", "tok-very-secret-123")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("가" * 200_000 + "\n")
        fh.write(f"db={secret_url}\nAuthorization: Bearer abc.def.ghi\nanalysis_canvas_session=cookieValue42; path=/\n")
        fh.write("password=hunter2 token: tok-very-secret-123\n")
    assert job(c, j["id"])["can_download_error_bundle"] is True
    assert c.get(f"{API}/jobs/{j['id']}/error-bundle.zip", headers=H("tok-power2")).status_code == 403
    assert c.get(f"{API}/jobs/{j['id']}/error-bundle.zip", headers=H("tok-power2")).json()["detail"]["required"] == "owner_or_global_admin"
    assert c.get(f"{API}/jobs/nope/error-bundle.zip", headers=P).status_code == 404
    r = c.get(f"{API}/jobs/{j['id']}/error-bundle.zip", headers=A)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == f'attachment; filename="eb1_{j["id"][:8]}_error_bundle.zip"'
    r = c.get(f"{API}/jobs/{j['id']}/error-bundle.zip", headers=P)
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    for n in ("README.txt", "job.json", "config_summary.json", "environment.json", "env_check_latest.json",
              "steps/step_01_TX_PREP.command.json", "steps/step_02_SIMLAB_EXTRACT.command.json", "logs/job.log.tail.txt",
              "logs/step_02_SIMLAB_EXTRACT.log.tail.txt"):
        assert n in names, n
    tail = zf.read("logs/job.log.tail.txt").decode("utf-8")
    assert tail.startswith("[앞 ") and len(zf.read("logs/job.log.tail.txt")) <= lc.settings.error_bundle.log_tail_bytes + 100
    blob = b"".join(zf.read(n) for n in names).decode("utf-8", errors="replace")
    for secret in ("S3cretPw", "abc.def.ghi", "cookieValue42", "hunter2", "tok-very-secret-123", "lease_token", "tok-power"):
        assert secret not in blob, secret
    assert "db=***" in blob and "Bearer ***" in blob  # DB URL 환경변수 값 전체 마스킹
    cmd = json.loads(zf.read("steps/step_02_SIMLAB_EXTRACT.command.json"))
    assert cmd["command"]["argv"][0] == d["altair"]["simlab_path"]
    env = json.loads(zf.read("environment.json"))
    assert env["migration_head"] == "0003_hpc_cancel_failed" and env["executables"]["simlab_path"]["exists"] is True
    assert json.loads(zf.read("job.json"))["failure_code"] == "EXIT_NONZERO"
    with engine.connect() as conn:
        n = conn.execute(text("select count(*) from audit_events where action='ERROR_BUNDLE_DOWNLOAD'")).scalar()
    assert n == 2
    # 총량 상한 → TRUNCATED.txt
    monkeypatch.setattr(lc.settings.error_bundle, "max_total_bytes", 4096)
    zf = zipfile.ZipFile(io.BytesIO(c.get(f"{API}/jobs/{j['id']}/error-bundle.zip", headers=P).content))
    assert "TRUNCATED.txt" in zf.namelist() and "logs/" in zf.read("TRUNCATED.txt").decode()


def test_fanout_cancel_stops_remaining(p2_env, monkeypatch):
    """V2-CMD-3: 취소 시 다음 대상 미실행."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid = study(c, "fc1")
    root = ai / "fc1" / "00_inbox" / "h3d"
    for i in range(4):
        (root / f"r{i}").mkdir(parents=True)
        (root / f"r{i}" / "a.h3d").write_bytes(b"H3D")
    src = {"kind": "FOLDER", "path": str(root)}
    pj = submit(c, sid, "CU_H3D_PREVIEW", {"source": src})
    assert w.run_once_slot() == "SUCCEEDED"
    sel = {"items": [{"datatype": "Stress", "component": "vonMises"}], "parts": {}, "time_increment": 1}
    cj = submit(c, sid, "CU_H3D_CURATE", {"source": src, "preview_job_id": pj["id"], "selection": sel})
    monkeypatch.setenv("FAKE_TOOL_DELAY_S", "0")
    res: dict = {}
    import physicsai_worker.executor as ex_mod

    orig = ex_mod.StepContext.run_local
    calls = []

    def slow(self, *a, **kw):
        calls.append(1)
        if len(calls) == 1:
            c.post(f"{API}/jobs/{cj['id']}/cancel", headers=AW)
        return orig(self, *a, **kw)

    monkeypatch.setattr(ex_mod.StepContext, "run_local", slow)
    t = threading.Thread(target=lambda: res.setdefault("s", w.run_once_slot()))
    t.start()
    t.join(60)
    assert res["s"] == "CANCELED" and len(calls) == 1
    assert job(c, cj["id"])["state"] == "CANCELED"


def test_bundle_masker_rules():
    """V2-EB-2: 고정 규칙(환경변수와 무관한 DB URL 자격 증명·쿠키·비밀 환경변수 이름)."""
    from physicsai_core.error_bundle import BundleMasker, read_tail

    m = BundleMasker([r"(?i)(password|passwd|token|secret)\s*[=:]\s*\S+"], "sess", "PHYSICSAI_DATABASE_URL",
                     environ={"PGPASSWORD": "pgpw1234", "OTHER": "visible"})
    out = m("postgres://u:pw@h/db sess=abc PGPASSWORD=pgpw1234 x pgpw1234 OTHER=visible secret: zz")
    assert out == "postgres://***@h/db sess=*** PGPASSWORD=*** x *** OTHER=visible secret=***"
    assert "postgresql+psycopg://***@" in m("postgresql+psycopg://a:b@127.0.0.1/x")


def test_env_check_api_item_failures(p2_env, fake_dashboard, engine):
    """V2-EC-1: 대시보드 401·타임아웃, migration head 불일치 → FAIL 항목(요청자 principal은 캐시)."""
    c, mk, ai, lc, d = p2_env
    assert c.get(f"{API}/me", headers=A).status_code == 200  # principal 캐시
    fake_dashboard.mode = "timeout"
    with engine.begin() as conn:
        conn.execute(text("update alembic_version set version_num='0001_initial'"))
    chk = c.post(f"{API}/admin/env-checks", headers=AW).json()
    items = {i["key"]: i for i in chk["items"]}
    assert items["auth.dashboard"]["status"] == "FAIL" and items["auth.dashboard"]["detail"]["code"] == "DASHBOARD_UNREACHABLE"
    assert items["db.migration_head"]["status"] == "FAIL" and items["db.migration_head"]["detail"]["current"] == "0001_initial"
    with engine.begin() as conn:
        conn.execute(text("update alembic_version set version_num='0003_hpc_cancel_failed'"))
        conn.execute(text("update env_checks set state='FAILED'"))
    fake_dashboard.mode = "503"
    chk = c.post(f"{API}/admin/env-checks", headers=AW).json()
    items = {i["key"]: i for i in chk["items"]}
    assert items["auth.dashboard"]["detail"]["code"] == "DASHBOARD_AUTH_UNAVAILABLE" and items["auth.projects"]["status"] == "FAIL"
    fake_dashboard.mode = "ok"
