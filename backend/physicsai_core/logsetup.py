"""운영 파일 로그(백엔드·워커 공통): 회전 파일 + 비밀 마스킹.

- 작업 스케줄러로 실행하면 표준 출력이 버려지므로 파일에 남긴다: <logging.dir>/<component>.log
  (logging.dir 빈 값 = 작업 폴더의 ./logs — 설치 시 작업 폴더는 install_root라 <install_root>\\logs).
- 회전: logging.max_mb(파일당 MB) × logging.backups(보관 개수). 삭제는 회전 핸들러가 가장 오래된 백업만 덮어쓴다.
- 모든 레코드에 오류 묶음과 같은 마스킹(logging.mask_patterns + DB URL 자격 증명·Bearer·쿠키·비밀 환경변수 값).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from typing import Any

from .masking import BundleMasker, bundle_masker

FORMAT = "%(asctime)s %(levelname)s %(name)s [%(process)d] %(message)s"
_INSTALLED: dict[str, logging.Handler] = {}


class MaskingFilter(logging.Filter):
    def __init__(self, masker: BundleMasker) -> None:
        super().__init__()
        self.masker = masker

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - 형식 오류 레코드도 남긴다
            msg = str(record.msg)
        record.msg = self.masker(msg)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.masker(record.exc_text)
        return True


def log_dir(settings: Any) -> str:
    return os.path.abspath(settings.logging.dir or os.path.join(".", "logs"))


def setup_file_logging(settings: Any, component: str) -> str | None:
    """루트(+전파 안 하는 uvicorn 로거)에 회전 파일 핸들러를 붙인다(다시 불러도 1개). 로그 파일 경로를 돌려준다.
    폴더를 만들 수 없으면 표준 오류에 알리고 None(기동은 계속)."""
    lg = settings.logging
    d = log_dir(settings)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as exc:
        import sys

        print(f"[physicsai] 파일 로그 폴더를 만들 수 없습니다: {d} ({exc}) — 콘솔 로그만 남깁니다", file=sys.stderr)
        return None
    path = os.path.join(d, f"{component}.log")
    old = _INSTALLED.pop(component, None)
    targets = [logging.getLogger(), logging.getLogger("uvicorn"), logging.getLogger("uvicorn.error"),
               logging.getLogger("uvicorn.access")]
    if old is not None:
        for t in targets:
            t.removeHandler(old)
        old.close()
    h = logging.handlers.RotatingFileHandler(path, maxBytes=int(lg.max_mb * 2**20), backupCount=int(lg.backups),
                                             encoding="utf-8", delay=True)
    h.setFormatter(logging.Formatter(FORMAT))
    h.addFilter(MaskingFilter(bundle_masker(settings)))
    level = getattr(logging, str(lg.level).upper(), logging.INFO)
    h.setLevel(level)
    root = logging.getLogger()
    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)
    for t in targets:
        if t is root or not t.propagate:
            t.addHandler(h)
    _INSTALLED[component] = h
    return path
