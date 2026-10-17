"""⑤ 내장 최적화 대리모델(phase3 §18.5 S13, D3-60) — 순수 numpy·scipy 계산.

- `gp`: 상수 평균 Kriging(Matérn 5/2 ARD + nugget), 집중 로그우도 L-BFGS-B 다중 시작, 닫힌 식 LOO.
- `rbf`: cubic RBF + 1차 다항 꼬리, Rippa LOO.
- `infill`: 후보 k개(활용 1 + EI×PoF kriging believer / RBF 거리 규칙), `differential_evolution`(integrality).
- `dataset`: 표준 라이브러리만 — 같은 설계 판정·중복 평균·최선·개선율·정지 판정·CSV.

numpy·scipy는 `gp`·`rbf`·`infill` 안에서만 import한다(API 프로세스는 이 하위 모듈을 import하지 않는다 — `/status`의
`features.optimize_builtin`은 `available()` — sys.path에서 패키지 폴더만 찾는다,
importlib·실행 없이(V2-LCH-1 정적 규칙)). 워커는 `limit_threads`를 numpy를 처음
불러오기 전에 불러 BLAS 스레드를 제한한다(공유 워커에서 적합이 코어를 다 쓰지 않게).
"""

from __future__ import annotations

import os
import sys

BLAS_THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS",
                   "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")
REQUIRED_MODULES = ("numpy", "scipy")


def _installed(name: str) -> bool:
    if name in sys.modules:
        return True
    for entry in sys.path:
        if isinstance(entry, str) and os.path.isfile(os.path.join(entry or ".", name, "__init__.py")):
            return True
    return False


def missing_modules() -> list[str]:
    """설치되지 않은 계산 모듈 이름(불러오지 않고 sys.path의 패키지 폴더만 확인)."""
    return [name for name in REQUIRED_MODULES if not _installed(name)]


def available() -> bool:
    return not missing_modules()


def limit_threads(n: int) -> None:
    """BLAS·OpenMP 스레드 수 상한(numpy 첫 import 전에만 효과). 이미 값이 있으면 더 작은 쪽."""
    n = max(1, int(n))
    for k in BLAS_THREAD_ENV:
        cur = os.environ.get(k)
        try:
            v = min(int(cur), n) if cur else n
        except ValueError:
            v = n
        os.environ[k] = str(v)
