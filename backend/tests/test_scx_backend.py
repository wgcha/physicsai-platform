"""phase3 §16.12-1·9: scx 설정 검증·비밀 파일·런타임 기본 위치·마스킹, migration 0009 PG 왕복, 정적(API는 게이트웨이 미호출)."""

from __future__ import annotations

import copy
import logging
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from physicsai_core.config import load_config_dict, redacted_settings
from physicsai_test_support import REPO, scx_hpc_cfg


def _cfg(settings_dict, hpc):
    d = copy.deepcopy(settings_dict)
    d["hpc"] = hpc
    return load_config_dict(d, environ={})


def test_scx_config_validation(settings_dict, fake_relay, tmp_path):
    ok = _cfg(settings_dict, scx_hpc_cfg(fake_relay, tmp_path))
    assert ok.ok, ok.issues
    for over, frag in [
        ({"relay_url": "http://10.1.2.3:8000"}, "127.0.0.1"),
        ({"relay_url": "http://127.0.0.1:8000/x"}, "경로"),
        ({"relay_url": ""}, "필수"),
        ({"appliance": ""}, "appliance"),
        ({"version": ""}, "version"),
        ({"drive_base": "/Users/vd.dashboard"}, "drive_base"),
        ({"drive_base": "~/../x"}, "drive_base"),
        ({"ncpu": 0}, "ncpu"),
        ({"stage_patterns": []}, "stage_patterns"),
        ({"submit_replay_attempts": 11}, "submit_replay_attempts"),
    ]:
        lc = _cfg(settings_dict, scx_hpc_cfg(fake_relay, tmp_path, **over))
        msgs = " | ".join(i.message for i in lc.issues if i.key.startswith("hpc.scx"))
        assert not lc.ok and frag in msgs, (over, msgs)
    lc = _cfg(settings_dict, scx_hpc_cfg(fake_relay, tmp_path, secret_file="relative/key"))
    assert "hpc.scx.secret_file" in lc.error_keys()
    # gateway none이면 scx 절을 검사하지 않는다(설정 예시의 빈 appliance·version 허용)
    assert _cfg(settings_dict, {"gateway": "none", "scx": {"appliance": ""}}).ok
    assert "hpc.gateway" in _cfg(settings_dict, {"gateway": "slurm"}).error_keys()


def test_scx_secret_missing_is_not_configured(settings_dict, fake_relay, tmp_path, caplog):
    from physicsai_core.hpc.gateway import get_hpc_gateway

    caplog.set_level(logging.DEBUG)
    hpc = scx_hpc_cfg(fake_relay, tmp_path)
    hpc["scx"]["secret_file"] = str(tmp_path / "nope" / "scx_relay_key")
    lc = _cfg(settings_dict, hpc)
    assert lc.ok  # 비밀 파일 문제는 설정 오류가 아니라 configured=false
    av = get_hpc_gateway(lc.settings).availability()
    assert av.mode == "scx" and not av.configured and "scx_relay_key" in av.message
    red = redacted_settings(lc.settings)
    assert red["hpc"]["scx"]["secret"] == {"path": hpc["scx"]["secret_file"], "present": False}
    # 형식 오류
    bad = tmp_path / "bad_key"
    bad.write_text("x" * 10, encoding="utf-8")
    hpc["scx"]["secret_file"] = str(bad)
    av = get_hpc_gateway(_cfg(settings_dict, hpc).settings).availability()
    assert not av.configured and "형식" in av.message and "xxxxxxxxxx" not in av.message
    # 정상: present true, 값은 요약·로그에 없음
    lc = _cfg(settings_dict, scx_hpc_cfg(fake_relay, tmp_path))
    gw = get_hpc_gateway(lc.settings)
    assert gw.availability().configured
    red = redacted_settings(lc.settings)
    assert red["hpc"]["scx"]["secret"]["present"] is True and fake_relay.secret not in str(red)
    assert fake_relay.secret not in caplog.text


def test_scx_secret_default_runtime_path(settings_dict, fake_relay, tmp_path, monkeypatch):
    """secret_file 빈 값 = <런타임>/secrets/scx_relay_key(--runtime → PHYSICSAI_RUNTIME_DIR, 또는 <런타임>/config/platform.yaml)."""
    from physicsai_core.config.runtime import apply_runtime, current_runtime_dir, default_scx_secret_path
    from physicsai_core.hpc.gateway import get_hpc_gateway, scx_secret_path

    from physicsai_core.config import runtime as rt_mod

    rt = tmp_path / "runtime"
    env: dict[str, str] = {}
    apply_runtime(str(rt), environ=env, machine_env={})
    assert "PHYSICSAI_RUNTIME_DIR" not in env  # 환경변수는 건드리지 않는다
    monkeypatch.setattr(rt_mod, "_APPLIED_RUNTIME", [rt])  # --runtime으로 기동한 프로세스
    monkeypatch.delenv("PHYSICSAI_RUNTIME_DIR", raising=False)
    assert default_scx_secret_path() == str(rt / "secrets" / "scx_relay_key")
    assert default_scx_secret_path({"PHYSICSAI_RUNTIME_DIR": str(rt)}) == str(rt / "secrets" / "scx_relay_key")
    assert current_runtime_dir({"PHYSICSAI_CONFIG": str(rt / "config" / "platform.yaml")}) == rt.resolve()
    assert current_runtime_dir({"PHYSICSAI_CONFIG": str(tmp_path / "x.yaml")}) is None
    monkeypatch.delenv("PHYSICSAI_CONFIG", raising=False)
    monkeypatch.setenv("PHYSICSAI_RUNTIME_DIR", str(rt))
    hpc = scx_hpc_cfg(fake_relay, tmp_path)  # tmp_path/runtime/secrets/scx_relay_key에 비밀을 쓴다
    hpc["scx"]["secret_file"] = ""
    lc = _cfg(settings_dict, hpc)
    assert scx_secret_path(lc.settings) == str(rt / "secrets" / "scx_relay_key")
    assert get_hpc_gateway(lc.settings).availability().configured


def test_registered_secret_is_masked(settings_dict, fake_relay, tmp_path):
    from physicsai_core.hpc.gateway import get_hpc_gateway
    from physicsai_core.masking import Masker, bundle_masker

    lc = _cfg(settings_dict, scx_hpc_cfg(fake_relay, tmp_path))
    get_hpc_gateway(lc.settings)  # 비밀을 읽으며 마스킹 목록에 등록
    line = f"oops key={fake_relay.secret} end"
    assert fake_relay.secret not in bundle_masker(lc.settings)(line)
    assert fake_relay.secret not in Masker([])(line)


GATEWAY_CALLS = {"submit", "status", "cancel", "health", "submit_radioss", "resolve", "upload", "download", "mkdirs", "list",
                 "batch", "ensure_new_dir", "client"}


def test_api_never_calls_gateway_methods_other_than_availability():
    """platform.md §12.2: API는 availability()만 — resolve는 요청 기록만(정적)."""
    import ast

    for f in (REPO / "backend" / "physicsai_api").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "hpc":
                assert n.attr not in GATEWAY_CALLS, f"{f}:{n.lineno} hpc.{n.attr}"


def _alembic(url: str, rev: str, down: bool = False) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    (command.downgrade if down else command.upgrade)(cfg, rev)


def test_migration_0009_roundtrip(pg_server):
    """0008 → 0009: 기존 hpc_jobs 행 보존(submission_unknown=false), request_id 부분 유일, 알림 이벤트 추가, downgrade 거부."""
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0018_equiv_check"
    name = f"physicsai_m9_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0008_contour_capture")
        with eng.begin() as c:
            sid = str(uuid.uuid4())
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1','M9','t','/x','u','u')"), {"i": sid})
            jid = str(uuid.uuid4())
            c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                           " created_by, created_by_name) values (:i,:s,'p-1','PREDICT_VERIFY',4,'SLOT','QUEUED',false,1,'{}','u','u')"),
                      {"i": jid, "s": sid})
            stid = str(uuid.uuid4())
            c.execute(text("insert into job_steps(id, job_id, step_no, step_key, kind, needs_slot, state, log_rel) values"
                           " (:i,:j,1,'HPC_SUBMIT','LOCAL',true,'PENDING','logs/x.log')"), {"i": stid, "j": jid})
            c.execute(text("insert into hpc_jobs(id, job_id, step_id, run_key, attempt_no, gateway_mode, external_job_id, state)"
                           " values (:i,:j,:s,'verify',1,'command','1.pbs','QUEUED')"), {"i": str(uuid.uuid4()), "j": jid, "s": stid})
        _alembic(url, "0009_scx_gateway")
        with eng.begin() as c:
            row = c.execute(text("select submission_unknown, remote_dir, request_id, staged, resolve_request from hpc_jobs")).one()
            assert tuple(row) == (False, None, None, None, None)
            for i in (2, 3):
                c.execute(text("insert into hpc_jobs(id, job_id, step_id, run_key, attempt_no, gateway_mode, state, request_id)"
                               " values (:i,:j,:s,'verify',:a,'scx','SUBMITTING',null)"),
                          {"i": str(uuid.uuid4()), "j": jid, "s": stid, "a": i})  # NULL request_id는 여러 개 허용
            c.execute(text("insert into notifications(user_id, event, title) values ('u','HPC_SUBMISSION_UNKNOWN','t')"))
        with pytest.raises(IntegrityError):
            with eng.begin() as c:
                for i in (4, 5):
                    c.execute(text("insert into hpc_jobs(id, job_id, step_id, run_key, attempt_no, gateway_mode, state, request_id)"
                                   " values (:i,:j,:s,'verify',:a,'scx','SUBMITTING','pai-dup')"),
                              {"i": str(uuid.uuid4()), "j": jid, "s": stid, "a": i})
        with pytest.raises(IntegrityError):
            with eng.begin() as c:
                c.execute(text("insert into notifications(user_id, event, title) values ('u','NOPE','t')"))
        with pytest.raises(RuntimeError):
            _alembic(url, "0008_contour_capture", down=True)
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
