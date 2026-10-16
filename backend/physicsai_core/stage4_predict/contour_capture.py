"""④ 컨투어 캡처(phase3 §15 S10) — API·워커 공용: 표시 설정(display) 검증·결정, capture_settings.tcl 생성, capture_result.txt 해석.

- 표시 설정 `display` = `{field, component, avgmode, comps[], legend:{mode:"auto"|"fixed", min, max}, views?}`(모든 키 선택).
  결정 순서(`resolve_display`): config 기본(`capture.default_field`·`capture.views`) → 템플릿 응답 정의 첫 항목의
  datatype/component → 템플릿 `param_sets.display` → 작업 params `display`(준비된 입력·배치 단위 범례·재캡처).
- capture_settings.tcl 값은 Tcl 큰따옴표 리터럴(백슬래시 이스케이프, ASCII 밖 문자는 `\\uXXXX`)이라 파일 인코딩과 무관하다.
  경로는 '/' 표기.
- 파일 이름은 고정: `<view>.png`, `<view>.<video_ext>`, 결과 목록 `capture_result.txt`(TCL 리소스와 같은 규칙).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

VIEWS: tuple[str, ...] = ("iso", "front", "back", "top", "bottom", "left", "right")
VIEW_LABELS: dict[str, str] = {"iso": "등각", "front": "정면", "back": "후면", "top": "위", "bottom": "아래", "left": "왼쪽",
                               "right": "오른쪽"}
AVG_MODES: tuple[str, ...] = ("", "simple", "maximum", "minimum", "difference")
LEGEND_MODES: tuple[str, ...] = ("auto", "fixed")
IMAGE_CONTENT_TYPE = "image/png"
VIDEO_CONTENT_TYPES: dict[str, str] = {"mp4": "video/mp4", "avi": "video/x-msvideo", "gif": "image/gif"}
MEDIA_KINDS: tuple[str, ...] = ("CONTOUR_IMAGE", "CONTOUR_VIDEO")

SCRIPT_NAME = "contour_capture.tcl"
SETTINGS_NAME = "capture_settings.tcl"
RESULT_NAME = "capture_result.txt"
MEDIA_DIR_REL = "RESULT/media"  # 예측 작업 폴더(04_predict/<id>) 기준
RECAPTURE_DIR_REL = "RESULT/media_recapture"  # + /<재캡처 작업 id>

DISPLAY_KEYS = frozenset({"field", "component", "avgmode", "comps", "legend", "views"})
LEGEND_KEYS = frozenset({"mode", "min", "max"})
MAX_TEXT = 64
MAX_COMPS = 50
# TCL이 명령 문자열을 다시 만드는 값(필드·성분·부품 이름)에서 막는 문자: 따옴표·괄호·치환 문자·명령 구분자
# (Tcl `;`, hwc 명령 구분자 `|` — D3-53)
_TEXT_FORBIDDEN = re.compile(r'["{}\[\]$\\;|]|[\x00-\x1f\x7f]')
TEXT_FORBIDDEN_MSG = '따옴표·괄호({ } [ ])·$·\\·;·|·제어문자는 쓸 수 없습니다'


# ---- 검증 ------------------------------------------------------------------------------------------


def text_problem(v: str) -> bool:
    """표시 설정 문자열에 금지 문자(따옴표·괄호·$·\\·;·|·제어문자)가 있으면 True — config `capture.default_field`도 같은 규칙."""
    return bool(_TEXT_FORBIDDEN.search(v))


def _text(errs: list[dict[str, Any]], loc: list[Any], v: Any, *, allow_empty: bool) -> None:
    if v is None:
        return
    if not isinstance(v, str):
        errs.append({"loc": loc, "msg": "문자열이어야 합니다"})
    elif not v.strip() and not (allow_empty and v == ""):
        errs.append({"loc": loc, "msg": "비어 있을 수 없습니다"})
    elif len(v) > MAX_TEXT:
        errs.append({"loc": loc, "msg": f"{MAX_TEXT}자 이내"})
    elif text_problem(v):
        errs.append({"loc": loc, "msg": TEXT_FORBIDDEN_MSG})


def validate_views(views: Any, loc: list[Any]) -> list[dict[str, Any]]:
    errs: list[dict[str, Any]] = []
    if not isinstance(views, list) or not views:
        return [{"loc": loc, "msg": f"방향 1개 이상: {', '.join(VIEWS)}"}]
    bad = [v for v in views if v not in VIEWS]
    if bad:
        errs.append({"loc": loc, "msg": f"알 수 없는 방향 {bad} — {', '.join(VIEWS)} 중에서"})
    if len(set(views)) != len(views):
        errs.append({"loc": loc, "msg": "같은 방향이 두 번 있습니다"})
    return errs


def validate_display(d: Any, loc: Iterable[Any] = ("display",)) -> list[dict[str, Any]]:
    """표시 설정 검증 → 오류 목록 `[{loc, msg}]`(빈 목록 = 정상). 모든 키는 선택(null = 상위 설정을 따름)."""
    base = list(loc)
    if d is None:
        return []
    if not isinstance(d, Mapping):
        return [{"loc": base, "msg": "객체여야 합니다"}]
    errs: list[dict[str, Any]] = []
    for k in sorted(set(d) - DISPLAY_KEYS):
        errs.append({"loc": [*base, k], "msg": "알 수 없는 키입니다"})
    _text(errs, [*base, "field"], d.get("field"), allow_empty=False)
    _text(errs, [*base, "component"], d.get("component"), allow_empty=True)
    if d.get("avgmode") is not None and d.get("avgmode") not in AVG_MODES:
        errs.append({"loc": [*base, "avgmode"], "msg": "'' | simple | maximum | minimum | difference"})
    comps = d.get("comps")
    if comps is not None:
        if not isinstance(comps, list) or len(comps) > MAX_COMPS:
            errs.append({"loc": [*base, "comps"], "msg": f"부품 이름 목록(최대 {MAX_COMPS}개)"})
        else:
            for i, c in enumerate(comps):
                _text(errs, [*base, "comps", i], c, allow_empty=False)
    lg = d.get("legend")
    if lg is not None:
        if not isinstance(lg, Mapping):
            errs.append({"loc": [*base, "legend"], "msg": "객체여야 합니다"})
        else:
            for k in sorted(set(lg) - LEGEND_KEYS):
                errs.append({"loc": [*base, "legend", k], "msg": "알 수 없는 키입니다"})
            mode = lg.get("mode", "auto")
            if mode not in LEGEND_MODES:
                errs.append({"loc": [*base, "legend", "mode"], "msg": "auto | fixed"})
            nums = {}
            for k in ("min", "max"):
                v = lg.get(k)
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
                    errs.append({"loc": [*base, "legend", k], "msg": "유한한 수여야 합니다"})
                else:
                    nums[k] = v
            if mode == "fixed":
                if nums.get("min") is None or nums.get("max") is None:
                    errs.append({"loc": [*base, "legend"], "msg": "fixed는 min·max가 모두 필요합니다"})
                elif nums["min"] >= nums["max"]:
                    errs.append({"loc": [*base, "legend"], "msg": "min < max 여야 합니다"})
    if d.get("views") is not None:
        errs += validate_views(d.get("views"), [*base, "views"])
    return errs


def clean_display(d: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """검증된 표시 설정에서 null 키를 뺀 사본(저장용). 비면 None."""
    if not d:
        return None
    out: dict[str, Any] = {}
    for k in ("field", "component", "avgmode", "comps", "views"):
        if d.get(k) is not None:
            out[k] = list(d[k]) if isinstance(d[k], list) else d[k]
    lg = d.get("legend")
    if lg is not None:
        mode = lg.get("mode") or "auto"
        out["legend"] = {"mode": mode, "min": lg.get("min") if mode == "fixed" else None,
                         "max": lg.get("max") if mode == "fixed" else None}
    return out or None


# ---- 결정 ------------------------------------------------------------------------------------------


def _first_response_spec(param_set: Mapping[str, Any] | None) -> dict[str, Any] | None:
    for r in (param_set or {}).get("responses") or []:
        spec = r.get("spec") if isinstance(r, Mapping) else None
        if isinstance(spec, Mapping) and spec.get("datatype"):
            return dict(spec)
    return None


def resolve_display(cfg: Any, param_set: Mapping[str, Any] | None, *overrides: Mapping[str, Any] | None
                    ) -> tuple[dict[str, Any], str]:
    """최종 표시 설정과 필드 출처(`config`|`response`|`template`|`params`).

    cfg = Settings.capture. 층마다 null이 아닌 키만 덮어쓴다. 어떤 층이 field를 정하면 component는 그 층 값(없으면 '')."""
    out: dict[str, Any] = {"field": cfg.default_field, "component": "", "avgmode": "", "comps": [],
                           "legend": {"mode": "auto", "min": None, "max": None}, "views": list(cfg.views)}
    source = "config"
    spec = _first_response_spec(param_set)
    if spec:
        out["field"], out["component"] = str(spec["datatype"]), str(spec.get("component") or "")
        source = "response"
    layers = [("template", (param_set or {}).get("display")), *(("params", o) for o in overrides)]
    for name, layer in layers:
        if not layer:
            continue
        if layer.get("field") is not None:
            out["field"], out["component"] = layer["field"], layer.get("component") or ""
            source = name
        elif layer.get("component") is not None:
            out["component"] = layer["component"]
        for k in ("avgmode", "comps", "views"):
            if layer.get(k) is not None:
                out[k] = list(layer[k]) if isinstance(layer[k], list) else layer[k]
        if layer.get("legend") is not None:
            lg = layer["legend"]
            mode = lg.get("mode") or "auto"
            out["legend"] = {"mode": mode, "min": lg.get("min") if mode == "fixed" else None,
                             "max": lg.get("max") if mode == "fixed" else None}
    return out, source


# ---- capture_settings.tcl ------------------------------------------------------------------------


def tcl_quote(value: str) -> str:
    """Tcl 큰따옴표 리터럴. `\\ " $ [ ] { } ;`는 백슬래시, 출력 가능 ASCII 밖(한글·제어문자)은 `\\uXXXX`/`\\UXXXXXXXX`."""
    out = ['"']
    for ch in value:
        o = ord(ch)
        if ch in '\\"$[]{};':
            out.append("\\" + ch)
        elif 0x20 <= o < 0x7F:
            out.append(ch)
        elif o <= 0xFFFF:
            out.append(f"\\u{o:04x}")
        else:
            out.append(f"\\U{o:08x}")
    out.append('"')
    return "".join(out)


def tcl_list(items: Iterable[str]) -> str:
    vals = [tcl_quote(str(x)) for x in items]
    return "[list " + " ".join(vals) + "]" if vals else "[list]"


def _num(v: float | None) -> str:
    return "" if v is None else format(float(v), ".12g")


def settings_text(*, h3d_path: str, out_dir: str, display: Mapping[str, Any], views: list[str], save_video: bool,
                  video_ext: str, use_last: bool) -> str:
    """capture_settings.tcl 본문(ASCII). 원본 TCL 1절 변수 + VIEWS."""
    lg = display.get("legend") or {}
    fixed = lg.get("mode") == "fixed"
    rows = [
        ("H3D_PATH", tcl_quote(h3d_path.replace("\\", "/"))),
        ("OUTDIR", tcl_quote(out_dir.replace("\\", "/"))),
        ("FIELD", tcl_quote(display.get("field") or "")),
        ("DCOMP", tcl_quote(display.get("component") or "")),
        ("AVGMODE", tcl_quote(display.get("avgmode") or "")),
        ("USE_LAST", "1" if use_last else "0"),
        ("LEGMIN", tcl_quote(_num(lg.get("min")) if fixed else "")),
        ("LEGMAX", tcl_quote(_num(lg.get("max")) if fixed else "")),
        ("SAVE_VIDEO", "1" if save_video else "0"),
        ("VID_EXT", tcl_quote(video_ext)),
        ("COMPS", tcl_list(display.get("comps") or [])),
        ("VIEWS", tcl_list(views)),
    ]
    head = ["# capture_settings.tcl - generated by PhysicsAI platform (phase3 S10). Do not edit.",
            "# Values are Tcl double-quoted literals; non-ASCII characters are \\uXXXX escapes."]
    return "\n".join(head + [f"set {k:<10} {v}" for k, v in rows]) + "\n"


# ---- capture_result.txt ------------------------------------------------------------------------------


def parse_result(text: str) -> dict[str, Any]:
    """`# capture_result 1` / `STATUS=` / `MESSAGE=` / `VIEW=view|image_ok|image_file|video(1|0|-)|video_file|error`."""
    out: dict[str, Any] = {"status": None, "message": None, "views": {}}
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition("=")
        if not sep:
            continue
        if key == "STATUS":
            out["status"] = val.strip() or None
        elif key == "MESSAGE":
            out["message"] = val.strip() or None
        elif key == "VIEW":
            f = (val.split("|") + [""] * 6)[:6]
            out["views"][f[0]] = {"image": f[1] == "1", "image_file": f[2], "video": {"1": "OK", "0": "FAIL"}.get(f[3], "SKIP"),
                                  "video_file": f[4], "error": f[5] or None}
    return out


# ---- 결과(media) -----------------------------------------------------------------------------------


def media_items(result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """작업 result.media(방향 순서 그대로). 이미지가 없는 항목은 뺀다."""
    items = (result or {}).get("media") or []
    return [m for m in items if isinstance(m, Mapping) and m.get("view") and m.get("image_artifact_id")]


def merge_media(base: list[dict[str, Any]], newer: list[dict[str, Any]], job_id: str) -> list[dict[str, Any]]:
    """방향별 덮어쓰기(재캡처가 일부 방향만 다시 찍어도 나머지는 유지). 순서 = VIEWS 순."""
    by = {m["view"]: dict(m) for m in base}
    for m in newer:
        by[m["view"]] = {**m, "job_id": job_id}
    return [by[v] for v in sorted(by, key=lambda x: VIEWS.index(x) if x in VIEWS else len(VIEWS))]
