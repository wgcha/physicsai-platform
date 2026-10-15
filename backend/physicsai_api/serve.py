"""백엔드 실행: 설정의 server.host·port로 uvicorn 기동(`python -m physicsai_api.serve [--runtime DIR] [--config PATH]`). 포트는 설정에서만 읽는다.

설치본(작업 스케줄러)은 `--runtime <런타임 폴더>`로 설정·DB URL 파일을 찾는다(관리자 권한 없는 설치 — phase3 D3-41,
physicsai_core.config.runtime). 인자에는 경로만 있고 비밀값은 없다. 환경변수를 직접 주면 그 값이 우선.
"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from physicsai_core.config import load_config
from physicsai_core.config.runtime import DB_URL_ENV, apply_runtime, describe
from physicsai_core.logsetup import FORMAT, setup_file_logging


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="physicsai_api.serve")
    ap.add_argument("--runtime", default=None, help="설치 런타임 폴더(config/platform.yaml, secrets/database_url)")
    ap.add_argument("--config", default=None, help="설정 파일(기본: 환경변수 PHYSICSAI_CONFIG → <런타임>/config/platform.yaml)")
    args = ap.parse_args(argv)
    sources: dict[str, str] = {}
    if args.runtime or args.config:
        sources = apply_runtime(args.runtime, config_arg=args.config)
    cfg = load_config()
    if (args.runtime or args.config) and cfg.settings.database.url_env != DB_URL_ENV:
        sources.update(apply_runtime(args.runtime, config_arg=args.config, url_envs=(cfg.settings.database.url_env,)))
    host, port = cfg.settings.server.host, cfg.settings.server.port
    os.environ.setdefault("PHYSICSAI_BIND_HOST", host)
    # 로그: 콘솔 + 회전 파일(<logging.dir>/backend.log, 마스킹). uvicorn 로거도 루트로 전파되게 log_config=None
    level = getattr(logging, cfg.settings.logging.level.upper(), logging.INFO)
    logging.basicConfig(level=level, format=FORMAT)
    path = setup_file_logging(cfg.settings, "backend")
    log = logging.getLogger("physicsai_api")
    log.info("백엔드 시작 %s:%s, 파일 로그 %s", host, port, path)
    if sources:
        log.info("설정·DB 접속 정보 출처: %s", describe(sources))
    uvicorn.run("physicsai_api.main:app", host=host, port=port, log_level=cfg.settings.logging.level.lower(), log_config=None)


if __name__ == "__main__":
    main()
