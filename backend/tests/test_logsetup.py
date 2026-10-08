"""운영 파일 로그: 회전·마스킹·설정 검증·uvicorn 로그 전파."""

from __future__ import annotations

import copy
import logging

from physicsai_test_support import REPO


def _settings(settings_dict, tmp_path, **lg):
    from physicsai_core.config import load_config_dict

    d = copy.deepcopy(settings_dict)
    d["logging"] = {"dir": str(tmp_path / "oplogs"), "max_mb": 0.001, "backups": 2, **lg}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    return lc.settings


def test_file_log_masks_secrets_and_rotates(settings_dict, tmp_path, monkeypatch):
    from physicsai_core.logsetup import setup_file_logging

    monkeypatch.setenv("PHYSICSAI_DATABASE_URL", "postgresql+psycopg://app:S3cretPw@127.0.0.1:5432/physicsai")
    s = _settings(settings_dict, tmp_path)
    path = setup_file_logging(s, "worker")
    try:
        lg = logging.getLogger("physicsai_worker.test")
        lg.warning("db=%s token=abcdef123 Authorization: Bearer xyz.abc cookie analysis_canvas_session=val123",
                   "postgresql+psycopg://app:S3cretPw@127.0.0.1:5432/physicsai")
        for i in range(60):
            lg.warning("줄 %d %s", i, "가" * 20)
        logging.getLogger("uvicorn.access").warning("GET /physicsai/api/health 200")
    finally:
        from physicsai_core import logsetup

        h = logsetup._INSTALLED.pop("worker")
        logging.getLogger().removeHandler(h)
        h.close()
    files = sorted(p.name for p in (tmp_path / "oplogs").iterdir())
    assert files == ["worker.log", "worker.log.1", "worker.log.2"]  # 1 KiB 회전, 백업 2개만 유지
    text = "".join((tmp_path / "oplogs" / f).read_text(encoding="utf-8") for f in files)
    assert "S3cretPw" not in text and "abcdef123" not in text and "xyz.abc" not in text and "val123" not in text
    assert "GET /physicsai/api/health" in text and path.endswith("worker.log")


def test_logging_dir_validation(settings_dict, tmp_path):
    from physicsai_core.config import load_config_dict

    d = copy.deepcopy(settings_dict)
    d["logging"] = {"dir": d["storage"]["ai_root"] + "/logs"}
    assert "logging.dir" in load_config_dict(d, environ={}).error_keys()
    d["logging"] = {"max_mb": 0, "backups": 0, "level": "LOUD"}
    assert {"logging.max_mb", "logging.backups", "logging.level"} <= set(load_config_dict(d, environ={}).error_keys())


def test_entrypoints_install_file_logging():
    serve = (REPO / "backend" / "physicsai_api" / "serve.py").read_text(encoding="utf-8")
    assert 'setup_file_logging(cfg.settings, "backend")' in serve and "log_config=None" in serve
    wm = (REPO / "worker" / "physicsai_worker" / "__main__.py").read_text(encoding="utf-8")
    assert 'setup_file_logging(s, "worker")' in wm
