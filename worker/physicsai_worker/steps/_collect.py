"""COLLECT 안정성 대기 간격(§8.10). 모듈 속성으로 읽어 시험에서 monkeypatch로 줄인다."""

from __future__ import annotations

COLLECT_STABLE_INTERVAL_S = 10.0  # §8.10 COLLECT: 10초 간격 2회 연속 불변(시험에서 줄임)
