"""시연 준비 공용: 경로·상수(시연 Study·토큰·경로 규칙), 로그 출력, 템플릿·가짜 도구 찾기, `_backup` 이동, 없을 때만 쓰기."""

from __future__ import annotations

import datetime as _dt
import re
import shutil
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parents[1]  # 저장소 루트 또는 오프라인 묶음 루트
TOOLS = ("fake_edspy", "fake_simlab", "fake_hw", "fake_hstbatch", "fake_hstpy", "fake_hvtrans", "fake_nvidia_smi")
TOOL_HELPERS = ("fake_hw_capture.py",)  # 가짜 도구가 import하는 보조 모듈(실행 파일 옆에 그대로 복사, phase3 §15 S10)
STUDY_FOLDER = "demo_bracket"
STUDY_TITLE = "시연 브래킷 낙하"
PROJECT_ID = "demo"
POWER_TOKEN = "demo-power"
UNSAFE = re.compile(r"[\s&|<>^%!\";,=()]")
# 모든 가짜 도구 맨 앞에 넣는 지연(FAKE_DEMO_DELAY_S초): 대기열·진행·취소를 눈으로 보게 한다
DELAY_PROLOGUE = 'import os as _o, time as _t; _t.sleep(float(_o.environ.get("FAKE_DEMO_DELAY_S") or 0))\n'


def _log(msg: str) -> None:
    print(f"[PhysicsAI 시연] {msg}", flush=True)


# 시연 백엔드(127.0.0.1) 호출 전용 opener: HTTP_PROXY·HTTPS_PROXY 환경변수와 Windows 시스템(레지스트리) 프록시를 쓰지 않는다.
# 회사 PC에서 루프백 요청이 프록시로 나가 health가 실패하던 문제(GitHub #1). 시연 스크립트의 모든 HTTP 호출은 이 함수만 쓴다.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_urlopen(req: urllib.request.Request | str, timeout: float):
    """프록시 없이 연다(루프백 전용). 응답 객체는 urllib.request.urlopen과 같다."""
    return _LOCAL_OPENER.open(req, timeout=timeout)


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
