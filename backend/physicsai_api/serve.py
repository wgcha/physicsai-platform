"""개발 실행: 설정의 server.host·port로 uvicorn 기동(`python -m physicsai_api.serve`). 포트는 설정에서만 읽는다."""

from __future__ import annotations

import os

import uvicorn

from physicsai_core.config import load_config


def main() -> None:
    cfg = load_config()
    host, port = cfg.settings.server.host, cfg.settings.server.port
    os.environ.setdefault("PHYSICSAI_BIND_HOST", host)
    uvicorn.run("physicsai_api.main:app", host=host, port=port, log_level=cfg.settings.logging.level.lower())


if __name__ == "__main__":
    main()
