"""워커 자식 프로세스 환경변수 허용목록. DB URL 등 비밀은 전달하지 않는다."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable, Mapping

BASE_NAMES = frozenset({
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP", "TMPDIR", "USERPROFILE", "HOME",
    "USERNAME", "USER", "LOGNAME", "COMPUTERNAME", "HOSTNAME", "LANG", "LC_ALL", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "PROGRAMDATA", "APPDATA", "LOCALAPPDATA",
})
BASE_PATTERNS = ("ALTAIR_*", "*_LICENSE_*", "*_LICENSE", "EDS_*", "CUDA_VISIBLE_DEVICES")
DENY_PATTERNS = ("PHYSICSAI_*", "*PASSWORD*", "*SECRET*", "*TOKEN*", "DATABASE_URL", "PG*")


def _match(name: str, patterns: Iterable[str]) -> bool:
    up = name.upper()
    return any(fnmatch.fnmatchcase(up, p.upper()) for p in patterns)


def child_env(
    extra_patterns: Iterable[str] = (),
    add: Mapping[str, str] | None = None,
    source: Mapping[str, str] | None = None,
    deny_names: Iterable[str] = (),
) -> dict[str, str]:
    """허용목록(기본 + 설정 worker.env_passthrough)만 통과. 거부 패턴·deny_names(DB URL 환경변수 이름)는 항상 제외."""
    src = os.environ if source is None else source
    extra = tuple(extra_patterns)
    deny = {n.upper() for n in deny_names}
    out: dict[str, str] = {}
    for k, v in src.items():
        if k.upper() in deny or _match(k, DENY_PATTERNS):
            continue
        if k.upper() in BASE_NAMES or _match(k, BASE_PATTERNS) or _match(k, extra):
            out[k] = v
    out.update(add or {})
    return out
