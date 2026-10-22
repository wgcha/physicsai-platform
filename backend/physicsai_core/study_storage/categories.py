"""정리 범주(CategoryKey)·표시명·영향 문구·폴더 묶음·항상 보호 규칙(phase3 §5.3, §5.5). API·워커 공용."""

from __future__ import annotations

from typing import Final

SCAN_JOB_TYPE: Final = "STUDY_STORAGE_SCAN"
CLEANUP_JOB_TYPE: Final = "STUDY_CLEANUP"

CATEGORY_KEYS: Final = (
    "PACKAGE_PSDATA",
    "SCORE_PREDICTIONS",
    "CURATED_H3D",
    "PREDICT_INPUT",
    "PREVIEW_OUTPUT",
    "JOB_LOGS",
)

CATEGORY_LABELS: Final[dict[str, str]] = {
    "PACKAGE_PSDATA": "학습 패키지 사본(psdata)",
    "SCORE_PREDICTIONS": "평가 예측 psdata",
    "CURATED_H3D": "정리된 h3d(②)",
    "PREDICT_INPUT": "예측 Radioss 입력(④)",
    "PREVIEW_OUTPUT": "② 미리보기 산출",
    "JOB_LOGS": "작업 로그",
}

# 옮긴 뒤 영향(화면에 미리 안내, §5.5 마지막 열 요약)
CATEGORY_IMPACTS: Final[dict[str, str]] = {
    "PACKAGE_PSDATA": "학습 패키지가 '없음'으로 바뀝니다. ③-2 '학습 패키지 내보내기'로 다시 만들 수 있습니다.",
    "SCORE_PREDICTIONS": "평가 점수는 그대로입니다. 다시 평가하면 새로 생깁니다.",
    "CURATED_H3D": "이 큐레이션으로 ③-1 데이터셋을 새로 만들 수 없습니다(이미 만든 데이터셋은 그대로).",
    "PREDICT_INPUT": "'입력파일 받기'와 PBS 검증 재실행을 할 수 없습니다. 예측 결과·컨투어는 그대로입니다.",
    "PREVIEW_OUTPUT": "지난 미리보기 화면은 '결과 파일 없음'으로 보입니다. 다시 실행하면 새로 생깁니다.",
    "JOB_LOGS": "해당 작업의 로그 보기와 오류 묶음의 로그 부분을 쓸 수 없습니다.",
}

# 최상위 폴더 집계 키(§5.3). 목록 밖 최상위 항목은 OTHER_KEY.
FOLDER_KEYS: Final = (
    "00_inbox", "01_train", "02_import", "02_preview", "02_curated", "03_dataset", "03_package", "03_model",
    "04_params", "04_predict", "05_opt", "logs", "_backup",
    "asm_match",  # asm-match.md §4.1: 조립 매칭 묶음(확정본 보존 — 항상 보호, 정리 범주 아님)
    "_cache",  # geometry-view.md §6.6: 플랫폼 임시(자동 정리) — 서버측 미리보기·3D 컨투어 캐시, 총량에 1줄로만(정리 범주 아님)
)
CACHE_KEY: Final = "_cache"
CACHE_LABEL: Final = "플랫폼 임시(자동 정리)"
OTHER_KEY: Final = "(기타)"
BACKUP_KEY: Final = "_backup"

# 범주 항목 경로 패턴(Study 기준 '/' 구분 세그먼트, '*' = 한 세그먼트). 패턴 길이 = 항목 깊이.
ITEM_PATTERNS: Final[dict[str, tuple[tuple[str, ...], ...]]] = {
    "PACKAGE_PSDATA": (("03_package", "*"),),
    "SCORE_PREDICTIONS": (("03_model", "score", "*", "*", "predictions.psdata"),),
    "CURATED_H3D": (("02_curated", "*", "CURATED_DATA"),),
    "PREDICT_INPUT": (("04_predict", "*", "INPUT"), ("04_predict", "*", "verify", "*", "input")),
    "PREVIEW_OUTPUT": (("02_preview", "*"),),
    "JOB_LOGS": (("logs", "*"),),
}

# 항상 보호(§5.5): 이 접두 아래 항목은 어떤 범주에도 들어가지 않는다.
PROTECTED_PREFIXES: Final = (
    ("03_model", "models"), ("03_dataset",), ("04_params",), ("00_inbox",), ("study.json",), ("_backup",), ("_platform",),
    ("asm_match",),
    ("_cache",),  # 서버측 임시 캐시는 housekeeping이 삭제(정리 범주 6개 불변, geometry-view.md §6.6)
)


def match_item(parts: tuple[str, ...] | list[str]) -> list[str]:
    """경로 세그먼트가 속하는 범주 항목 rel 목록(패턴 길이 이상인 경로만)."""
    out: list[str] = []
    for pats in ITEM_PATTERNS.values():
        for pat in pats:
            n = len(pat)
            if len(parts) >= n and all(p == "*" or p == x for p, x in zip(pat, parts[:n])):
                out.append("/".join(parts[:n]))
    return out


def is_protected(rel: str) -> bool:
    """항상 보호 경로이거나 '..'·절대경로·빈 세그먼트가 있으면 True."""
    parts = tuple(rel.split("/"))
    if not rel or rel.startswith("/") or any(x in ("", ".", "..") for x in parts) or ":" in parts[0]:
        return True
    return any(parts[: len(p)] == p for p in PROTECTED_PREFIXES)


def fmt_bytes(n: int) -> str:
    """사람용 크기(1024 단위, 한 자리). 알림 본문·로그용."""
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{int(v)} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{n} B"
