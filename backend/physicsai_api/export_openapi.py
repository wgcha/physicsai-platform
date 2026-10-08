"""openapi.json 생성: `python -m physicsai_api.export_openapi [출력경로]` (기본 backend/openapi.json)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI


def build_openapi() -> dict:
    from physicsai_core.config import LoadedConfig, Settings
    from physicsai_core.hpc.none import NoneHpcGateway

    from .auth import Authenticator
    from .context import AppContext
    from .main import create_app

    settings = Settings()
    ctx = AppContext(LoadedConfig(settings), engine=None, auth=Authenticator(settings.auth), hpc=NoneHpcGateway())  # type: ignore[arg-type]
    app: FastAPI = create_app(ctx)
    return app.openapi()


def render() -> str:
    return json.dumps(build_openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "openapi.json"
    out.write_text(render(), encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    main()
