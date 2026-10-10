"""API 스키마(계약 §10). 요청은 알 수 없는 키를 거부(422 INVALID_PARAMS).

도메인별 모듈로 나누고 여기서 전부 재노출한다(라우터의 `schemas as S` / `S.Name` 사용 불변).
"""

from .common import *  # noqa: F401,F403
from .shell import *  # noqa: F401,F403
from .jobs import *  # noqa: F401,F403
from .studies import *  # noqa: F401,F403
from .stage1_train_data import *  # noqa: F401,F403
from .stage2_curation import *  # noqa: F401,F403
from .stage3_model import *  # noqa: F401,F403
from .stage4_predict import *  # noqa: F401,F403
from .stage5_optimize import *  # noqa: F401,F403
from .ops import *  # noqa: F401,F403
