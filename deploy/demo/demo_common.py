"""시연 준비 공용: 경로·상수(시연 Study·토큰·경로 규칙), 로그 출력, 템플릿·가짜 도구 찾기, `_backup` 이동, 없을 때만 쓰기."""

from __future__ import annotations

import datetime as _dt
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parents[1]  # 저장소 루트 또는 오프라인 묶음 루트
TOOLS = ("fake_edspy", "fake_simlab", "fake_hw", "fake_hstbatch", "fake_hstpy", "fake_hvtrans", "fake_nvidia_smi")
STUDY_FOLDER = "demo_bracket"
STUDY_TITLE = "시연 브래킷 낙하"
PROJECT_ID = "demo"
POWER_TOKEN = "demo-power"
UNSAFE = re.compile(r"[\s&|<>^%!\";,=()]")
# 모든 가짜 도구 맨 앞에 넣는 지연(FAKE_DEMO_DELAY_S초): 대기열·진행·취소를 눈으로 보게 한다
DELAY_PROLOGUE = 'import os as _o, time as _t; _t.sleep(float(_o.environ.get("FAKE_DEMO_DELAY_S") or 0))\n'


def _log(msg: str) -> None:
    print(f"[PhysicsAI 시연] {msg}", flush=True)


def fwd(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def find_template() -> Path:
    for c in (PKG_ROOT / "config" / "platform.demo.yaml",):
        if c.is_file():
            return c
    raise SystemExit("config/platform.demo.yaml을 찾을 수 없습니다")


def find_fake_tools() -> Path:
    for c in (HERE / "fake_tools", PKG_ROOT / "backend" / "tests" / "fake_tools"):
        if (c / "fake_hw").is_file():
            return c
    raise SystemExit("가짜 도구(fake_tools)를 찾을 수 없습니다 — 저장소 또는 오프라인 묶음에서 실행하세요")


def move_to_backup(root: Path, path: Path) -> None:
    """사용자 산출물은 삭제하지 않고 <root>/_backup/<UTC>/ 로 옮긴다."""
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root / "_backup" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest / path.name))


def _write_if_missing(path: Path, data: str | bytes) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
