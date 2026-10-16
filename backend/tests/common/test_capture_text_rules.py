"""D3-53 Verifier 권고: 표시 설정·응답 정의의 `|`(hwc 명령 구분자) 거부, 일괄 예측 캡처 옵션 스키마, 미디어 Range(RFC 9110)."""

from __future__ import annotations

import pytest


def test_capture_display_schema_and_batch_options_reject_pipe():
    from pydantic import ValidationError

    from physicsai_api.schemas.contour_capture import BatchCaptureOptions, CaptureDisplay

    for bad in ({"field": "S|x"}, {"component": "|"}, {"comps": ["a|b"]}):
        with pytest.raises(ValidationError):
            CaptureDisplay.model_validate(bad)
    assert BatchCaptureOptions.model_validate({}).model_dump() == {"enabled": True, "views": None, "video": None}
    assert BatchCaptureOptions.model_validate({"enabled": False, "views": ["iso", "top"], "video": False}).views == ["iso", "top"]
    for bad in ({"views": []}, {"views": ["iso", "iso"]}, {"views": ["iso|top"]}, {"bogus": 1}, {"enabled": "maybe"}):
        with pytest.raises(ValidationError):
            BatchCaptureOptions.model_validate(bad)


def test_response_defs_reject_pipe_and_trailing_newline():
    from physicsai_core.stage4_predict.response_defs import validate_response_defs

    spec = {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}
    assert validate_response_defs([{"name": "S_MAX", "unit": "MPa", "spec": spec}])[1] == []
    for row in ({"name": "S_MAX", "unit": "M|Pa", "spec": spec}, {"name": "S_MAX", "unit": "", "spec": {**spec, "datatype": "S|x"}},
                {"name": "S_MAX", "unit": "", "spec": {**spec, "component": "a|b"}},
                {"name": "S_MAX", "unit": "", "spec": {**spec, "layer": "|"}}, {"name": "S_MAX\n", "unit": "", "spec": spec}):
        assert validate_response_defs([row])[1], row


def test_parse_range_rfc9110():
    """D3-53: 문법상 잘못된 범위는 무시(200 전체), 만족 불가한 범위만 416."""
    from physicsai_api.services.contour_capture import parse_range

    U = "unsatisfiable"
    cases = {
        None: None, "": None, "bytes=0-9": (0, 9), "bytes=60-": (60, 63), "bytes=-5": (59, 63), "bytes=-100": (0, 63),
        "bytes=10-1000": (10, 63), "bytes = 1 - 2": (1, 2),
        "bytes=10-5": None, "bytes=63-0": None,                      # 끝 < 시작 = 문법 오류 → 무시
        "bytes=-": None, "bytes=a-b": None, "items=0-1": None, "bytes=0-1,5-6": None, "bytes=0-1x": None,
        "bytes=١-٢": None, "bytes=０-１": None,     # 유니코드 숫자는 숫자로 치지 않는다
        "bytes=64-": U, "bytes=64-70": U, "bytes=-0": U,             # 만족 불가 → 416
    }
    for h, want in cases.items():
        assert parse_range(h, 64) == want, h
    assert parse_range("bytes=0-", 0) == U and parse_range("bytes=-1", 0) == U and parse_range("bytes=5-1", 0) is None
