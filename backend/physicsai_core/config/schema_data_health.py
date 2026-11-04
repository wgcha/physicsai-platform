"""설정 스키마 — ③-1 데이터 점검 절 `data_health`(data-health.md §10). 판정 기준 숫자·정규식·상한은 이 파일(+ 예시 yaml) 한 곳이다.

코드는 이 값을 읽기만 한다(하드코딩 금지). 검증은 `validate_data_health`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import Field

from ..parsers.radioss_out import TOTAL_MASS_RE
from ._model import _M

if TYPE_CHECKING:
    from .schema import ConfigIssue, Settings

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
# Radioss engine 출력 사이클 줄 기본 패턴(이름 그룹 time·err·mas). 열 순서: CYCLE TIME TIME-STEP [ELEMENT 종류 번호] ERROR% … MAS.ERR(마지막 열).
# 실제 현장 출력 픽스처가 없어 시험 픽스처로만 확인했다(U-DH-1 계열 — 현장 확인 후 설정으로 맞춘다).
DEFAULT_CYCLE_REGEX = (
    rf"^\s*(?P<cycle>\d+)\s+(?P<time>{_NUM})\s+{_NUM}\s+(?:[A-Za-z][\w.\-]*\s+\d+\s+)?(?P<err>{_NUM})%?-?\s+"
    rf"(?:{_NUM}%?\s+)*?(?P<mas>{_NUM})%?\s*$"
)
DEFAULT_TOTAL_MASS_REGEX = TOTAL_MASS_RE  # equiv `starter_mass`가 쓰던 값(그룹 1 = 질량) — 정의는 공용 파서 한 곳


class T01SeriesCfg(_M):
    """②-4 곡선 JSON series 이름(hg/접촉 비). 현장 확인 전 null."""

    internal: str
    hourglass: str | None = None
    contact: str | None = None


class DataHealthCfg(_M):
    min_n: int = 8                      # Z·견고 z 최소 유효 표본(DH-7)
    knn_min_n: int = 12
    knn_k: int = 5
    sigma_z: float = 3.0                # 일반 3σ(표시만)
    robust_z: float = 3.5               # 판정(Iglewicz–Hoaglin 수정 z 권장값)
    knn_z: float = 3.5                  # 판정
    energy_error_pct_max: float = 10.0
    added_mass_ratio_max: float = 0.05
    hourglass_ratio_max: float = 0.10
    contact_ratio_max: float = 0.10
    zero_tol: float = 1.0e-12
    engine_out_glob: str = "*_0001.out"
    starter_out_glob: list[str] = Field(default_factory=lambda: ["*_0000.out", "*_0000.sty"])
    out_tail_bytes: int = 262144
    starter_scan_max_bytes: int = 67108864
    normal_regex: str = "NORMAL TERMINATION"
    error_regex: str = "ERROR TERMINATION"
    cycle_regex: str = DEFAULT_CYCLE_REGEX
    total_mass_regex: str = DEFAULT_TOTAL_MASS_REGEX
    t01_series: T01SeriesCfg | None = None
    report_max_rows: int = 2000
    expected_frames: int | None = None
    expected_t_end: float | None = None
    t_end_tol: float = 0.01             # 마지막 시각 < T_end × (1 − tol) → 위반(한 곳)
    engine_rad_glob: str = "*_0001.rad"
    engine_rad_max_bytes: int = 4194304
    frame_write_regex: str | None = None
    engine_scan_max_bytes: int = 67108864
    frame_probe_timeout_s: float = 1800


def validate_data_health(s: "Settings", issues: "list[ConfigIssue]") -> None:
    from .schema import ConfigIssue

    d = s.data_health
    add = lambda k, m: issues.append(ConfigIssue(f"data_health.{k}", m))  # noqa: E731
    if not 0 <= d.t_end_tol < 0.5:
        add("t_end_tol", "0 이상 0.5 미만")
    if d.expected_frames is not None and d.expected_frames < 1:
        add("expected_frames", "1 이상(또는 null)")
    if d.expected_t_end is not None and not d.expected_t_end > 0:
        add("expected_t_end", "양수(또는 null)")
    for k in ("sigma_z", "robust_z", "knn_z", "energy_error_pct_max", "added_mass_ratio_max", "hourglass_ratio_max",
              "contact_ratio_max", "zero_tol", "frame_probe_timeout_s"):
        if not getattr(d, k) > 0:
            add(k, "0보다 커야 합니다")
    if d.min_n < 3:
        add("min_n", "3 이상")
    if not (d.knn_k >= 1 and d.knn_min_n > d.knn_k):
        add("knn_min_n", "knn_min_n > knn_k ≥ 1")
    for k in ("out_tail_bytes", "starter_scan_max_bytes", "engine_rad_max_bytes", "engine_scan_max_bytes"):
        if getattr(d, k) < 1024:
            add(k, "1024 이상")
    if d.report_max_rows < 1:
        add("report_max_rows", "1 이상")
    if not d.engine_out_glob or not d.engine_rad_glob or not d.starter_out_glob:
        add("engine_out_glob", "engine_out_glob·starter_out_glob·engine_rad_glob은 비울 수 없습니다")
    for k in ("normal_regex", "error_regex", "cycle_regex", "total_mass_regex", "frame_write_regex"):
        pat = getattr(d, k)
        if pat is None:
            continue
        try:
            rx = re.compile(pat, re.I)
        except re.error as exc:
            add(k, f"정규식 컴파일 실패: {exc}")
            continue
        if k == "cycle_regex":
            for g in ("time", "err", "mas"):
                if g not in rx.groupindex:
                    add(k, f"정규식에 필수 그룹 '{g}'이 없습니다")
        if k == "total_mass_regex" and rx.groups < 1:
            add(k, "질량을 잡는 그룹 1개가 필요합니다")
