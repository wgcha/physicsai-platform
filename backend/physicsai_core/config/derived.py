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
    return d
