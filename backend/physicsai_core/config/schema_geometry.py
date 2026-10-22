"""설정 스키마 — native 형상 엔진 절 `geometry`(geometry-engine.md §7.1), 쉘 모핑 기본 대상 `shell`(shell-morph.md §8.1·§12 Q1),
3D 가시화 `geometry.view`(geometry-view.md §6.1), 결과 3D 컨투어 `contour3d`(geometry-view.md §13)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ._model import _M

GEOMETRY_ENGINES = ("altair", "native")
SHELL_TIMEOUT_KEYS = ("shell_fixed_scan", "shell_extract", "shell_tag", "shell_update", "shell_morph", "shell_check", "shell_run")
GEOMETRY_TIMEOUT_KEYS = ("extract", "tag", "update", "morph", "check", "run") + SHELL_TIMEOUT_KEYS
VIEW_TIMEOUT_KEYS = ("export", "preview", "preview_fe")


def _timeouts() -> dict[str, float | None]:
    return {"extract": 1800, "tag": 1800, "update": 600, "morph": 1800, "check": 1800, "run": 3600}


def _env() -> dict[str, str]:
    return {"OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4", "PAICAD_THREADS": "4"}


class ViewTessCfg(_M):
    linear_mm: float = 0.1
    angular_deg: float = 20.0


class ViewCacheCfg(_M):
    """서버측 AI 루트 `<study>/_cache/` 임시 캐시(브라우저 캐시 아님). 컨투어 3D 캐시와 합산·공유(geometry-view.md §6.6)."""

    retention_days: float = 7
    max_total_bytes: int = 2147483648
    purge_interval_h: float = 6


def _view_timeouts() -> dict[str, float]:
    return {"export": 300, "preview": 60, "preview_fe": 300}


class GeometryViewCfg(_M):
    enabled: bool = True
    tess: ViewTessCfg = Field(default_factory=ViewTessCfg)
    max_triangles: int = 500000
    max_glb_bytes: int = 16777216  # ≤ ui.max_artifact_bytes — 넘으면 config.warnings + 그 값으로 자름
    coarsen_steps: int = 3
    edges: bool = True
    fe_edges: bool = True
    max_concurrent: int = 1  # PREVIEW 레인 동시 실행 수(전역)
    max_queued_per_user: int = 2  # 사용자별 대기+실행 미리보기 상한(넘으면 429 PREVIEW_BUSY)
    threads: int = 2  # 미리보기 paicad --threads(진행 중 DOE와 CPU 공유)
    timeout_s: dict[str, float] = Field(default_factory=_view_timeouts)
    cache: ViewCacheCfg = Field(default_factory=ViewCacheCfg)


class GeometryCfg(_M):
    engine: str = "altair"  # altair | native — 새 파라미터 세트·①-1 추출·①-3 DOE의 기본 엔진
    paicad_path: str = ""  # 빈 값 = 워커 Python 폴더의 Scripts\paicad.exe(Windows)·bin/paicad(그 외)
    step_extensions: list[str] = Field(default_factory=lambda: [".step", ".stp"])
    max_report_bytes: int = 4194304
    progress_regex: str = r"^PAICAD PROGRESS (?P<pct>[0-9.]+) (?P<msg>.*)$"
    timeout_s: dict[str, float | None] = Field(default_factory=_timeouts)  # shell_* 키가 없으면 같은 이름 솔리드 값(SM §8.1)
    env: dict[str, str] = Field(default_factory=_env)
    defaults: dict[str, Any] = Field(default_factory=dict)  # §4.9 options.json 기본값 덮어쓰기(코드 기본값 위에 깊은 병합)
    shell_defaults: dict[str, Any] = Field(default_factory=dict)  # SM §4.10 쉘 options 기본값 덮어쓰기(솔리드 defaults 불변)
    view: GeometryViewCfg = Field(default_factory=GeometryViewCfg)  # geometry-view.md §6.1


class ShellCfg(_M):
    """쉘 판금 모핑 플랫폼 설정(SM §12 Q1, SM-C1): 기본 대상 component(=/PART 제목, 대소문자 무시). paicad는 기본 대상을 갖지 않는다."""

    default_component: str = "chassis_rear"


class Contour3dCfg(_M):
    """결과 3D 컨투어(geometry-view.md §13). enabled=false면 기능 숨김(hw·contour_extract 명령이 설정된 현장만 true)."""

    enabled: bool = False
    max_frames: int = 50
    max_nodes: int = 300000
    max_bin_bytes: int = 268435456
    include_disp: bool = True
    timeout_s: float = 1800


class AsmMatchCfg(_M):
    """조립 매칭(asm-match.md §6.2). enabled=false·명령 null이면 API 409 TEMPLATE_NOT_CONFIGURED. `max_parts`·`recommend_min_score`·
    `worst_nodes`는 paicad `--options`의 `asm_match` 절로 넘긴다(허용오차는 `geometry.defaults.tag`, AM-3)."""

    enabled: bool = True
    max_parts: int = 5000
    recommend_min_score: float = 0.6
    worst_nodes: int = 2000
    timeout_s: float = 600
