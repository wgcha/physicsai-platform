"""진입점: `python -m physicsai_worker [--config PATH]` (§11.1). 기동 검사 실패 시 종료코드 2."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

from sqlalchemy import text

from physicsai_core.config import load_config, paths_overlap

log = logging.getLogger("physicsai_worker")


def _fail(msg: str) -> int:
    print(f"[physicsai_worker] 기동 거부: {msg}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="physicsai_worker")
    ap.add_argument("--config", default=None, help="설정 파일(기본 PHYSICSAI_CONFIG 또는 config/platform.yaml)")
    args = ap.parse_args(argv)
    config = load_config(args.config)
    logging.basicConfig(level=getattr(logging, config.settings.logging.level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not config.ok:
        return _fail("설정 검증 실패: " + "; ".join(f"{i.key}: {i.message}" for i in config.issues))
    s = config.settings

    from .lockfile import AlreadyRunning, InstanceLock

    lock = InstanceLock(s.worker.state_dir)
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        return _fail(str(exc))

    url = os.environ.get(s.database.url_env, "")
    if not url:
        return _fail(f"DB 접속 정보가 없습니다: 환경변수 {s.database.url_env}")
    from physicsai_core.db.engine import make_engine

    engine = make_engine(url, s.database.pool_size)
    try:
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar()
    except Exception as exc:  # noqa: BLE001
        return _fail(f"DB 연결 또는 migration 확인 실패: {exc}")
    from physicsai_core.db import MIGRATION_HEAD

    if head != MIGRATION_HEAD:
        return _fail(f"DB migration head 불일치: {head} (필요: {MIGRATION_HEAD})")
    try:
        import tempfile

        with tempfile.TemporaryFile(dir=s.storage.ai_root) as fh:
            fh.write(b"ok")
    except OSError as exc:
        return _fail(f"ai_root에 쓸 수 없습니다: {exc}")
    for r in s.storage.spdm_roots:
        if paths_overlap(s.storage.ai_root, r):
            return _fail("ai_root가 SPDM 루트와 겹칩니다")
    for k in ("edspy_path", "simlab_path", "hw_exe_path"):
        p = getattr(s.altair, k)
        if not p or not os.path.isfile(p):
            log.warning("Altair 실행 파일 없음(해당 step은 EXECUTABLE_MISSING으로 실패): altair.%s=%s", k, p)

    from .runtime import Worker

    worker = Worker(config, engine, config_path=config.path)
    if s.hpc.gateway != "none" and not worker.hpc.availability().configured:
        log.warning("HPC 게이트웨이 미구성: %s", worker.hpc.availability().message)

    def _term(_sig: int, _frm: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _term)
    try:
        worker.run_forever()
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
