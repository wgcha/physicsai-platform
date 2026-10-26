"""DOE 표본 형상 그리드 미리보기의 형상 입력 해석(doe-preview.md §5.1·§6.3). API(요청 검증·grid_key)와 워커(DP_PREP·DP_MATRIX·DP_RENDER)가 같은 코드를
써서 같은 입력 digest를 얻는다. 표준 라이브러리 + 같은 패키지 모듈만, paicad import 없음.

출처 3종 → `Source`(경로·유효 옵션·형상 종류·digest):
- `train`: ①-3 Native 학습 설정(`01_train/cad`·`features_rel`). tag·fixed 없음(`tag_state="none"`).
- `param_set`: 세트 준비본 `S/native/{extract,tag,fixed}`(변수 스냅숏을 이미 적용한 세트 행을 받는다).
- `train_doe`: 생성된 DOE `D/cad`·`D/native/{extract,tag,fixed}`(저장된 유효 옵션 사본).
행 이름은 두 가지로 나뉜다 — `matrix_rows`(표본 행렬 생성에 쓰는 행: 실제 DOE와 같은 입력, 쉘 두께 행 포함)와 `geo_params`(형상 변수만:
정렬·색 범위·셀 값·셀 키).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..path_links import is_link_or_reparse
from . import doe_preview as dp
from .options import effective_options
from .shell import is_prop_row
from .shell_native import SHELL, features_name, kind_of_features_rel, read_kind
from .shell_options import effective_shell_options
from .view import VIEW_DIR, VIEW_MANIFEST


class SourceError(Exception):
    """출처 입력 문제(코드·한국어 문구). API는 409/422, 워커는 StepFailure로 바꾼다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Source:
    kind: str  # train | param_set | train_doe
    shape: str  # solid | shell
    base: str  # 준비본 폴더(세트 S · DOE D · train은 추출 폴더)
    cad_input: str
    cad_files: list[str]
    features: str
    body_map: str | None
    tag_dir: str | None
    fixed_dir: str | None
    opts: dict[str, Any]
    nominal_manifest: str
    source_ref: dict[str, Any]
    matrix_rows: list[dict[str, Any]]
    geo_params: list[dict[str, Any]]
    digest: str = ""
    tag_state: str = "none"
    extra: dict[str, Any] = field(default_factory=dict)


def step_files(cad_input: str, step_exts: Sequence[str]) -> list[str]:
    """CAD 입력(파일 또는 `cad/parts` 폴더)의 STEP 파일 목록(정렬)."""
    exts = tuple(e.lower() for e in step_exts)
    if os.path.isdir(cad_input):
        return sorted(os.path.join(cad_input, n) for n in os.listdir(cad_input)
                      if n.lower().endswith(exts) and os.path.isfile(os.path.join(cad_input, n)))
    return [cad_input]


def find_cad_input(base: str, step_exts: Sequence[str]) -> str:
    """`<base>/cad/`의 단일 STEP 파일 또는 `cad/parts` 폴더(geometry-engine.md §4.1). 없으면 INPUT_CHANGED."""
    cad = os.path.join(base, "cad")
    exts = tuple(e.lower() for e in step_exts)
    files = sorted(n for n in os.listdir(cad) if os.path.isfile(os.path.join(cad, n)) and n.lower().endswith(exts)) if os.path.isdir(cad) else []
    if files:
        return os.path.join(cad, files[0])
    parts = os.path.join(cad, "parts")
    if os.path.isdir(parts) and any(n.lower().endswith(exts) for n in os.listdir(parts)):
        return parts
    raise SourceError("INPUT_CHANGED", "공칭 STEP 파일이 없습니다 — 형상 준비를 다시 하세요")


def effective_opts(settings: Any, over: Mapping[str, Any] | None, shape: str) -> dict[str, Any]:
    if shape == SHELL:
        opts, probs = effective_shell_options(settings.geometry.shell_defaults, dict(over) if over else None)
    else:
        opts, probs = effective_options(settings.geometry.defaults, dict(over) if over else None)
    if probs:
        raise SourceError("CONFIG_INVALID", "형상 옵션이 범위를 벗어납니다: " + "; ".join(str(p.get("key")) for p in probs[:5]))
    return opts


def _tag_state(tag_dir: str | None) -> str:
    return "tagged" if tag_dir and dp.folder_digest(tag_dir) is not None else "none"


def _finish(src: Source, settings: Any) -> Source:
    for p in (src.features,):
        if not os.path.isfile(p) or is_link_or_reparse(p):
            raise SourceError("INPUT_CHANGED", "형상 피처 파일이 없습니다 — 파라미터 추출(①-1)·형상 준비를 다시 하세요")
    if not src.cad_files or not all(os.path.isfile(f) for f in src.cad_files):
        raise SourceError("INPUT_CHANGED", "STEP 파일이 없습니다 — 파라미터 추출(①-1)·형상 준비를 다시 하세요")
    src.digest = dp.shape_digest(cad_files=src.cad_files, body_map=src.body_map, features=src.features, tag_dir=src.tag_dir,
                                 opts_sha=dp.sha_of(src.opts), fixed_digest=dp.folder_digest(src.fixed_dir) if src.fixed_dir else None)
    src.tag_state = _tag_state(src.tag_dir)
    return src


def _units(features: str) -> dict[str, str]:
    """features JSON의 피처 이름 → 단위(길이·각도 구분에 쓴다). 읽을 수 없으면 빈 표."""
    from .view import read_json

    return {str(f["name"]): str(f["unit"]) for f in (read_json(features) or {}).get("features", [])
            if isinstance(f, dict) and isinstance(f.get("name"), str) and isinstance(f.get("unit"), str) and f["unit"]}


def _geo_rows(rows: Sequence[Mapping[str, Any]], features: str) -> list[dict[str, Any]]:
    return dp.param_table([r for r in rows if not is_prop_row(r)], _units(features))


def from_train(root: str, setup: Mapping[str, Any], settings: Any) -> Source:
    """①-3 Native 단일 baseline, 세트 없음(① 학습 설정). features_rel 기준, tag 없음."""
    from ..stage1_train_data import train_params as tp

    rel, cad_name = setup.get("features_rel"), setup.get("cad_file_name")
    if not rel or not cad_name or setup.get("engine") != "native":
        raise SourceError("PREREQUISITE_MISSING", "형상 피처가 필요합니다(①-1 파라미터 추출을 Native로 먼저)")
    shape = kind_of_features_rel(rel)
    used = tp.used(list(setup.get("parameters") or []))
    if not used:
        raise SourceError("PREREQUISITE_MISSING", "사용 파라미터가 필요합니다(①-2)")
    features = os.path.join(root, *rel.replace("\\", "/").split("/"))
    cad = os.path.join(root, "01_train", "cad", cad_name)
    bm = os.path.join(root, "01_train", "cad", "body_map.json")
    opts = effective_opts(settings, None, shape)
    return _finish(Source(
        kind="train", shape=shape, base=os.path.dirname(features), cad_input=cad, cad_files=step_files(cad, settings.geometry.step_extensions),
        features=features, body_map=bm if os.path.isfile(bm) else None, tag_dir=None, fixed_dir=None, opts=opts,
        nominal_manifest=os.path.join(os.path.dirname(features), "view", VIEW_MANIFEST),
        source_ref={"train_setup_id": setup.get("id")}, matrix_rows=[dict(r) for r in used], geo_params=_geo_rows(used, features)), settings)


def from_param_set(root: str, ps: Mapping[str, Any], settings: Any) -> Source:
    """세트 기준(단일 baseline). `ps`는 변수 스냅숏을 적용한 세트(`native_vars.apply`) — 행·범위가 실제 DOE와 같다."""
    S = os.path.join(root, *str(ps["stored_rel"]).replace("\\", "/").split("/"))
    shape = read_kind(S)
    opts = effective_opts(settings, ps.get("geom_options"), shape)
    cad = find_cad_input(S, settings.geometry.step_extensions)
    bm = os.path.join(S, "cad", "body_map.json")
    params = list(ps.get("parameters") or [])
    return _finish(Source(
        kind="param_set", shape=shape, base=S, cad_input=cad, cad_files=step_files(cad, settings.geometry.step_extensions),
        features=os.path.join(S, "native", "extract", features_name(shape)), body_map=bm if os.path.isfile(bm) else None,
        tag_dir=os.path.join(S, "native", "tag"), fixed_dir=os.path.join(S, "native", "fixed") if shape == SHELL else None, opts=opts,
        nominal_manifest=os.path.join(S, *VIEW_DIR.split("/"), VIEW_MANIFEST), source_ref={"param_set_id": ps.get("id")},
        matrix_rows=[dict(r) for r in params], geo_params=_geo_rows(params, os.path.join(S, "native", "extract", features_name(shape)))),
        settings)


def from_doe(root: str, doe: Mapping[str, Any], settings: Any) -> Source:
    """생성된 DOE(`D/cad`·`D/native/*`). 행 이름·범위는 `parameters_snapshot`, 형상 변수는 features 이름과 겹치는 행만."""
    D = os.path.join(root, *str(doe["dir_rel"]).replace("\\", "/").split("/"))
    shape = read_kind(D)
    opts = effective_opts(settings, doe.get("geom_options"), shape)
    cad = find_cad_input(D, settings.geometry.step_extensions)
    bm = os.path.join(D, "cad", "body_map.json")
    features = os.path.join(D, "native", "extract", features_name(shape))
    snap = list(doe.get("parameters_snapshot") or [])
    from .view import read_json

    names = {f.get("name") for f in (read_json(features) or {}).get("features", []) if isinstance(f, dict)}
    return _finish(Source(
        kind="train_doe", shape=shape, base=D, cad_input=cad, cad_files=step_files(cad, settings.geometry.step_extensions), features=features,
        body_map=bm if os.path.isfile(bm) else None, tag_dir=os.path.join(D, "native", "tag"),
        fixed_dir=os.path.join(D, "native", "fixed") if shape == SHELL else None, opts=opts,
        nominal_manifest=os.path.join(D, *VIEW_DIR.split("/"), VIEW_MANIFEST), source_ref={"doe_id": doe.get("id")},
        matrix_rows=[dict(r) for r in snap], geo_params=dp.param_table([r for r in snap if r.get("name") in names], _units(features)),
        extra={"doe_dir": D}), settings)


def view_tess(src: Source, settings: Any) -> dict[str, float]:
    """셀 키·`view_options.json`에 쓰는 테셀레이션: 공칭 뷰 manifest(OK)의 값, 없으면 설정 기본(GV_PREP과 같은 규칙)."""
    from .view import read_json

    m = read_json(src.nominal_manifest)
    t = (m or {}).get("tess") if (m or {}).get("status") == "OK" else None
    if isinstance(t, dict) and isinstance(t.get("linear_mm"), (int, float)) and isinstance(t.get("angular_deg"), (int, float)):
        return {"linear_mm": float(t["linear_mm"]), "angular_deg": float(t["angular_deg"])}
    v = settings.geometry.view.tess
    return {"linear_mm": float(v.linear_mm), "angular_deg": float(v.angular_deg)}
