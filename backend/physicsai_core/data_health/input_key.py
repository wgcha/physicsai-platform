"""점검 대상 식별 키(data-health.md DH-C3) — 점검 보고서와 DATASET_CREATE가 같은 정규화 함수 하나를 쓴다.

폴더 입력 = 정규화 경로, 큐레이션 입력 = `curation:<id>`. 정규화: 구분자 `\\`·`/`를 `/`로 통일, `.`·`..`·중복·끝 구분자 제거(normpath).
Windows 형태(드라이브 문자·UNC)는 대소문자를 구분하지 않으므로 소문자로 통일한다(드라이브 `E:`와 `e:`는 같은 키).
"""

from __future__ import annotations

import ntpath
import posixpath
import re

_WIN = re.compile(r"^(?:[A-Za-z]:|[\\/]{2})")


def folder_key(path: str) -> str:
    s = str(path).strip()
    if _WIN.match(s):
        return ntpath.normcase(ntpath.normpath(s)).replace("\\", "/")
    return posixpath.normpath(s.replace("\\", "/"))


def input_key(path: str, curation_id: str | None = None) -> str:
    return f"curation:{curation_id}" if curation_id else folder_key(path)
