"""Sobol(스크램블) 생성 — scipy 지연 import 한 곳(phase3 §20.5.3, D3-63).

S13 §18.2 "API 프로세스는 numpy를 불러오지 않는다"의 유일한 예외다. 모듈 import 때는 scipy·numpy를 부르지 않고,
`sobol_unit` 호출 때만(함수 안에서) 부른다. import에 실패하면 `GeneratorUnavailable`(problem GENERATOR_UNAVAILABLE).
"""

from __future__ import annotations

import inspect
import warnings
from typing import Any

GENERATOR_UNAVAILABLE_MESSAGE = "표본 계산 모듈(scipy)을 불러올 수 없습니다 — 관리자에게 문의하세요"


class GeneratorUnavailable(RuntimeError):
    """scipy(또는 numpy) import 실패."""


def _load() -> tuple[Any, Any, str]:
    """(Sobol 클래스, numpy 모듈, scipy 버전). 시험은 이 함수를 바꿔 import 실패·시그니처를 흉내 낸다."""
    try:
        import numpy
        import scipy
        from scipy.stats.qmc import Sobol
    except Exception as exc:  # ImportError 외에 바이너리 불일치 등도 같은 안내
        raise GeneratorUnavailable(GENERATOR_UNAVAILABLE_MESSAGE) from exc
    return Sobol, numpy, str(scipy.__version__)


def rng_keyword(sobol_cls: Any) -> str:
    """생성자 시그니처에 `rng`가 있으면 "rng", 없으면 "seed"(scipy 1.13~1.x 호환, 판정 1곳)."""
    try:
        params = inspect.signature(sobol_cls).parameters
    except (TypeError, ValueError):
        return "seed"
    return "rng" if "rng" in params else "seed"


def generator_label() -> str:
    """meta.generator 값 `scipy 1.17.1`."""
    return f"scipy {_load()[2]}"


def sobol_unit(k: int, count: int, seed: int, offset: int) -> tuple[list[list[float]], str]:
    """스크램블 Sobol 단위 점 count개 × k열 + generator 라벨. 같은 (k, seed, offset, count, scipy 버전)이면 같은 값.

    `offset`개를 건너뛴 위치부터 만든다(이어서 추가). 균형 경고(UserWarning)는 이 함수 안에서만 무시한다.
    """
    sobol_cls, numpy, version = _load()
    kw = rng_keyword(sobol_cls)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        eng = sobol_cls(d=k, scramble=True, **{kw: numpy.random.default_rng(seed)})
        if offset:
            eng.fast_forward(offset)
        pts = eng.random(count)
    return [[float(v) for v in row] for row in pts.tolist()], f"scipy {version}"
