"""API 스키마 — ③-1 데이터 점검 결과(data-health.md §6.2·§8). `GET /jobs/{job_id}/data-health` = `report.json` 내용."""

from __future__ import annotations


from .common import Resp

__all__ = ["DataHealthWarning", "DataHealthSummary", "DataHealthMetric", "DataHealthReason", "DataHealthSound", "DataHealthConsistency",
           "DataHealthValue", "DataHealthRun", "DataHealthReport"]


class DataHealthWarning(Resp):
    code: str
    message: str
    count: int | None = None  # 해당되는 run 수(있을 때)


class DataHealthSummary(Resp):
    input_key: str | None = None  # 점검 대상 식별: 폴더 정규화 경로(core/data_health/input_key.py) 또는 `curation:<id>`
    n_consistency_undecided: int = 0  # 기준값이 없어 일관성을 판정하지 못한 run 수(n_frames_unknown과 별개)
    n_runs: int
    n_required: int  # 제외 필수(일관성 위반) run 수
    n_recommended: int
    n_sigma_only: int  # 일반 3σ 태그만(추천 아님)
    n_sound_fail: int
    n_frames_unknown: int  # 프레임 확인 불가 run 수
    frames_ref: int | None = None  # 프레임 수 기준(DOE마다 다르면 null — refs_by_doe)
    t_end_ref: float | None = None
    ref_source: str | None = None  # config | mode — 프레임·종료 시각 기준값 출처
    frames_ref_source: str | None = None  # 설정 | 최빈
    t_end_ref_source: str | None = None
    refs_by_doe: dict[str, dict[str, float | None]] = {}
    preview_frames: int | None = None  # ② 큐레이션 미리보기 프레임 수(참고 표시)
    n_na_by_metric: dict[str, int] = {}
    metrics_used: list[str] = []
    thresholds: dict[str, float | int | None] = {}  # 판정 기준 스냅숏(읽기 전용)
    limited: bool = False  # 제한 모드(DOE 연결 없음)
    warnings: list[DataHealthWarning] = []


class DataHealthMetric(Resp):
    id: str
    label: str
    unit: str = ""
    group: str
    n: int
    mean: float | None = None
    std: float | None = None
    median: float | None = None
    mad: float | None = None
    skipped: bool = False  # 표본 부족(SKIP_SMALL_N)
    knn_skipped: bool = False


class DataHealthReason(Resp):
    code: str
    metric: str | None = None
    value: float | None = None
    z: float | None = None
    zr: float | None = None
    s: float | None = None
    message: str


class DataHealthSound(Resp):
    status: str  # OK | FAIL | NA
    value: float | str | None = None
    limit: float | None = None
    code: str | None = None
    v: float | None = None
    na: str | None = None
    fail: bool = False


class DataHealthConsistency(Resp):
    status: str  # OK | FAIL | NA
    value: float | None = None
    ref: float | None = None
    code: str | None = None


class DataHealthValue(Resp):
    v: float | None = None
    z: float | None = None
    zr: float | None = None
    s: float | None = None
    na: str | None = None
    fail: bool = False  # 견고 z·이웃 점수 판정 초과
    knn_dist: float | None = None


class DataHealthRun(Resp):
    file_rel: str
    run_key: str | None = None
    doe_id: str | None = None
    recommended: bool
    required: bool  # 제외 필수(기본 선택)
    score: float
    sigma_only: bool
    sound: dict[str, DataHealthSound] = {}
    consistency: dict[str, DataHealthConsistency] = {}
    values: dict[str, DataHealthValue] = {}
    reasons: list[DataHealthReason] = []
    t_end: float | None = None


class DataHealthReport(Resp):
    summary: DataHealthSummary
    metrics: list[DataHealthMetric] = []
    runs: list[DataHealthRun] = []
    truncated: bool = False  # 크기 상한으로 runs를 score 상위만 남김
