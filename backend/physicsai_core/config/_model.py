"""설정 스키마 공용 기반 모델 `_M`(알 수 없는 키 금지, 계약 §14)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")
