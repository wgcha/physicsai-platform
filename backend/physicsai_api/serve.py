"""개발 실행: 설정의 server.host·port로 uvicorn 기동(`python -m physicsai_api.serve`). 포트는 설정에서만 읽는다."""

from __future__ import annotations

import logging
import os

import uvicorn

from physicsai_core.config import load_config
from physicsai_core.logsetup import FORMAT, setup_file_logging


def main() -> None:
    cfg = load_config()
    host, port = cfg.settings.server.host, cfg.settings.server.port
    os.environ.setdefault("PHYSICSAI_BIND_HOST", host)
    # 로그: 콘솔 + 회전 파일(<logging.dir>/backend.log, 마스킹). uvicorn 로거도 루트로 전파되게 log_config=None
    level = getattr(logging, cfg.settings.logging.level.upper(), logging.INFO)
    logging.basicConfig(level=level, format=FORMAT)
    path = setup_file_logging(cfg.settings, "backend")
    logging.getLogger("physicsai_api").info("백엔드 시작 %s:%s, 파일 로그 %s", host, port, path)
    uvicorn.run("physicsai_api.main:app", host=host, port=port, log_level=cfg.settings.logging.level.lower(), log_config=None)


if __name__ == "__main__":
    main()
