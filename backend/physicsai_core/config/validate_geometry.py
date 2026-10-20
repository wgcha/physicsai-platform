"""설정 검사 — `geometry` 절(geometry-engine.md §7.1)·`geometry.view`·`contour3d`(geometry-view.md §6.1·§13) — validate에서 호출."""

from __future__ import annotations

import os
import re

from .rules import _compile, has_unsafe_chars, is_abs_path_str
from .schema import ConfigIssue, Settings


def _validate_geometry(s: Settings, issues: list[ConfigIssue]) -> None:
    """`geometry` 절(geometry-engine.md §7.1): 엔진 이름·경로·확장자·진행 정규식·타임아웃·환경변수·기본 옵션 범위."""
    from ..geometry.options import effective_options
    from .schema_geometry import GEOMETRY_ENGINES, GEOMETRY_TIMEOUT_KEYS

    g = s.geometry
    add = lambda k, m: issues.append(ConfigIssue(k, m))  # noqa: E731
    if g.engine not in GEOMETRY_ENGINES:
        add("geometry.engine", "altair | native")
    if g.paicad_path:
        if not is_abs_path_str(g.paicad_path):
            add("geometry.paicad_path", "절대경로여야 합니다(빈 값 = 워커 Python 폴더에서 파생)")
        elif s.profile == "prod" and not os.path.isfile(g.paicad_path):
            add("geometry.paicad_path", f"실행 파일이 없습니다: {g.paicad_path}")
    if not g.step_extensions or not all(re.fullmatch(r"\.[A-Za-z0-9]{1,8}", e) for e in g.step_extensions):
        add("geometry.step_extensions", "'.'으로 시작하는 확장자 1개 이상(예: .step)")
    if g.max_report_bytes < 1024:
        add("geometry.max_report_bytes", "1024 이상")
    _compile("geometry.progress_regex", g.progress_regex, issues, ("pct", "msg"))
    for k, v in g.timeout_s.items():
        if k not in GEOMETRY_TIMEOUT_KEYS:
            add(f"geometry.timeout_s.{k}", "extract | tag | update | morph | check | run (+ shell_<같은 이름>·shell_fixed_scan)")
        elif v is not None and v <= 0:
            add(f"geometry.timeout_s.{k}", "양수 또는 null(없음)")
    for k, v in g.env.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) or not isinstance(v, str) or "\x00" in v:
            add("geometry.env", f"환경변수 이름·값 형식 오류: {k}")
    _opts, problems = effective_options(g.defaults, None)
    for p in problems:
        add("geometry.defaults", f"{p['key']}: {p['message']}")
    from ..geometry.shell_options import effective_shell_options

    _sopts, sproblems = effective_shell_options(g.shell_defaults, None)
    for p in sproblems:
        add("geometry.shell_defaults", f"{p['key']}: {p['message']}")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}", s.shell.default_component or ""):
        add("shell.default_component", "/PART 제목(영숫자·_·.·-, 64자 이내)이어야 합니다")
    _validate_view(s, issues)


def _validate_view(s: Settings, issues: list[ConfigIssue]) -> None:
    """`geometry.view`(geometry-view.md §6.1·§4.5)·`contour3d`(§13)·`resources.contour_extract_tcl` 범위."""
    from .schema_geometry import VIEW_TIMEOUT_KEYS

    v, c = s.geometry.view, s.contour3d
    add = lambda k, m: issues.append(ConfigIssue(k, m))  # noqa: E731
    if not 0 < v.tess.linear_mm <= 10:
        add("geometry.view.tess.linear_mm", "0 초과 10 이하")
    if not 5 <= v.tess.angular_deg <= 45:
        add("geometry.view.tess.angular_deg", "5~45")
    if v.max_triangles < 1000:
        add("geometry.view.max_triangles", "1000 이상")
    if v.max_glb_bytes < 1024:
        add("geometry.view.max_glb_bytes", "1024 이상")
    if not 0 <= v.coarsen_steps <= 5:
        add("geometry.view.coarsen_steps", "0~5")
    if not 1 <= v.max_concurrent <= 8:
        add("geometry.view.max_concurrent", "1~8")
    if not 1 <= v.max_queued_per_user <= 20:
        add("geometry.view.max_queued_per_user", "1~20")
    if not 1 <= v.threads <= 64:
        add("geometry.view.threads", "1~64")
    for k, t in v.timeout_s.items():
        if k not in VIEW_TIMEOUT_KEYS:
            add(f"geometry.view.timeout_s.{k}", "export | preview | preview_fe")
        elif not t > 0:
            add(f"geometry.view.timeout_s.{k}", "양수")
    if not v.cache.retention_days > 0:
        add("geometry.view.cache.retention_days", "양수")
    if v.cache.max_total_bytes < 1048576:
        add("geometry.view.cache.max_total_bytes", "1 MiB 이상")
    if not v.cache.purge_interval_h > 0:
        add("geometry.view.cache.purge_interval_h", "양수")
    if not 2 <= c.max_frames <= 1000:
        add("contour3d.max_frames", "2~1000")
    if c.max_nodes < 3:
        add("contour3d.max_nodes", "3 이상")
    if c.max_bin_bytes < 1024:
        add("contour3d.max_bin_bytes", "1024 이상")
    if not c.timeout_s > 0:
        add("contour3d.timeout_s", "양수")
    t = s.resources.contour_extract_tcl
    if t:
        if not is_abs_path_str(t):
            add("resources.contour_extract_tcl", "절대경로여야 합니다")
        elif has_unsafe_chars(t):
            add("resources.contour_extract_tcl", "공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
