"""설정 파생 값(phase2 §8.1): Altair 경로 파생, 유효 실행 파일 표, 관리 조회용 가림."""

from __future__ import annotations

from typing import Any

from .schema import AltairCfg, Settings


def derived_hstpy_path(a: AltairCfg) -> str:
    if a.hstpy_path:
        return a.hstpy_path
    if not a.hyperstudy_path:
        return ""
    hs = a.hyperstudy_path.replace("\\", "/")
    return hs.rsplit("/", 1)[0] + "/hstpy.bat" if "/" in hs else ""


def derived_altair_home(a: AltairCfg) -> str:
    if a.altair_home:
        return a.altair_home.replace("\\", "/")
    hp = derived_hstpy_path(a)
    if not hp:
        return ""
    parts = hp.replace("\\", "/").split("/")[:-1]  # hstpy 폴더
    if len(parts) <= 3:
        return ""
    return "/".join(parts[:-3])


def effective_altair(s: Settings) -> dict[str, str]:
    """명령 펼침용 실행 파일 표(altair 키 → 경로). hstpy_path·altair_home은 파생값 포함."""
    d = {k: v for k, v in s.altair.model_dump().items() if isinstance(v, str)}
    d["hstpy_path"] = derived_hstpy_path(s.altair)
    d["altair_home"] = derived_altair_home(s.altair)
    return d


def redacted_settings(s: Settings) -> dict[str, Any]:
    """관리 조회용(§10.8). DB URL·비밀은 설정 파일에 없지만 혹시 모를 값을 가린다."""
    d = s.model_dump()
    d["database"] = {"url_env": s.database.url_env, "pool_size": s.database.pool_size}
    # scx relay 비밀(phase3 §16.10-3): 경로와 읽힘 여부만(값 없음)
    from simdash_adapters.hpc.scx import read_secret_file

    from ..hpc.gateway import scx_secret_path

    sp = scx_secret_path(s)
    d["hpc"]["scx"]["secret"] = {"path": sp, "present": bool(sp) and read_secret_file(sp)[0] is not None}
    return d
