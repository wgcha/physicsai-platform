"""설정 YAML 로드(계약 §14): 파일·dict → LoadedConfig, 누락 키·예약 키 안내."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..commands import TEMPLATE_SPECS
from .schema import ConfigIssue, LoadedConfig, Settings
from .validate import validate_settings


def _pydantic_issues(exc: ValidationError) -> list[ConfigIssue]:
    out = []
    for e in exc.errors():
        key = ".".join(str(x) for x in e.get("loc", ())) or "(root)"
        msg = "알 수 없는 키입니다" if e.get("type") == "extra_forbidden" else f"형식 오류: {e.get('msg')}"
        out.append(ConfigIssue(key, msg))
    return out


def load_config(path: str | None = None, environ: dict[str, str] | None = None) -> LoadedConfig:
    env = environ if environ is not None else dict(os.environ)
    path = path or env.get("PHYSICSAI_CONFIG") or "config/platform.yaml"
    try:
        raw_bytes = Path(path).read_bytes()
    except OSError as exc:
        return LoadedConfig(Settings(), [ConfigIssue("(file)", f"설정 파일을 읽을 수 없습니다: {path} ({exc})")], path)
    sha = hashlib.sha256(raw_bytes).hexdigest()
    try:
        data = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        return LoadedConfig(Settings(), [ConfigIssue("(file)", f"YAML 형식 오류: {exc}")], path, sha)
    if not isinstance(data, dict):
        return LoadedConfig(Settings(), [ConfigIssue("(root)", "최상위는 매핑이어야 합니다")], path, sha)
    return load_config_dict(data, env, path=path, sha256=sha)


def load_config_dict(
    data: dict[str, Any], environ: dict[str, str] | None = None, *, path: str | None = None, sha256: str | None = None
) -> LoadedConfig:
    env = environ if environ is not None else dict(os.environ)
    data = dict(data)
    if env.get("PHYSICSAI_PROFILE"):
        data["profile"] = env["PHYSICSAI_PROFILE"]
    if env.get("PHYSICSAI_HPC_GATEWAY"):
        hpc = dict(data.get("hpc") or {})
        hpc["gateway"] = env["PHYSICSAI_HPC_GATEWAY"]
        data["hpc"] = hpc
    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:
        return LoadedConfig(Settings(), _pydantic_issues(exc), path, sha256)
    absent = absent_keys(data, settings)
    issues = validate_settings(settings, absent=absent)
    return LoadedConfig(settings, issues, path, sha256, config_warnings(data, settings, absent))


# 예약(미사용) 키: 값이 있어도 동작에 쓰이지 않는다(경고만). 기존 설정 파일 호환을 위해 스키마에는 남긴다.
RESERVED_KEYS: tuple[tuple[str, ...], ...] = (("server", "base_path"), ("hpc", "transfer", "stage_in"), ("hpc", "adapter", "module"))


def _has(data: Any, *path: str) -> bool:
    for k in path:
        if not isinstance(data, dict) or k not in data:
            return False
        data = data[k]
    return True


def absent_keys(data: dict[str, Any], s: Settings) -> frozenset[str]:
    """설정 파일에 아예 없는 키(예시 yaml 일부만 복사한 경우). 이 키들은 오류가 아니라 '해당 기능 비활성'으로 다룬다.
    명시적으로 null을 쓴 1차 확정 템플릿은 그대로 오류(V2-CFG-1)."""
    out = {f"commands.{k}" for k in TEMPLATE_SPECS if not _has(data, "commands", k)}
    if s.hpc.gateway == "command" and not _has(data, "hpc", "command"):
        out.add("hpc.command")
    if not _has(data, "worker", "gpu_query"):
        out.add("worker.gpu_query")
    return frozenset(out)


def config_warnings(data: dict[str, Any], s: Settings, absent: frozenset[str]) -> list[ConfigIssue]:
    w: list[ConfigIssue] = []
    for path in RESERVED_KEYS:
        if _has(data, *path):
            w.append(ConfigIssue(".".join(path), "예약(미사용) 키입니다 — 값이 적용되지 않습니다(지워도 됩니다)"))
    for k in sorted(absent):
        if k.startswith("commands.") and TEMPLATE_SPECS[k.split(".", 1)[1]].required:
            w.append(ConfigIssue(k, "설정 파일에 없어 이 명령을 쓰는 기능이 비활성입니다(config/platform.example.yaml 참고)"))
    if "hpc.command" in absent:
        w.append(ConfigIssue("hpc.command", "hpc.gateway=command인데 hpc.command가 없어 PBS 제출이 비활성입니다"))
    if "worker.gpu_query" in absent:
        w.append(ConfigIssue("worker.gpu_query",
                             "GPU 조회 명령이 없어 nvidia-smi를 자동 탐색합니다(resources.gpu_query_candidates, 못 찾으면 GPU 정보 없음)"))
    if _has(data, "predict", "mesh_output_glob"):
        w.append(ConfigIssue("predict.mesh_output_glob",
                             "폐지된 키입니다 — 값이 적용되지 않습니다(새 메시는 predict.mesh_include_name, 지워도 됩니다)"))
    from .schema_hpc import SCX_MPI_KNOWN

    if s.hpc.scx.mpi not in SCX_MPI_KNOWN:  # 오류 아님 — 어댑터가 허용 값을 늘릴 수 있다(S20 보강 1)
        w.append(ConfigIssue("hpc.scx.mpi", f"hpc.scx.mpi가 알려진 값이 아닙니다: {s.hpc.scx.mpi}"))
    from .schema_capture import capture_warnings

    for key, msg in capture_warnings(s):  # phase3 §21.4.4 S16: avi 대체·ffmpeg 파일 없음
        w.append(ConfigIssue(key, msg))
    from ..features import geometry_status, predict_parametric_missing  # features가 config를 import하므로 지역 import

    if s.geometry.engine == "native" and not geometry_status(s)["native_available"]:
        w.append(ConfigIssue("geometry.engine", "기본 엔진 Native를 쓸 수 없습니다 — paicad 설치 확인"))

    from ..geometry.extract_filter import DEFAULTS_IGNORED_MESSAGE, has_defaults_filter

    if has_defaults_filter(s.geometry.defaults):  # extract-filter.md §6.3: 추출 조건은 설정이 아니라 사용자가 정한다
        w.append(ConfigIssue("geometry.defaults.extract.filter", DEFAULTS_IGNORED_MESSAGE))
    if s.geometry.view.max_glb_bytes > s.ui.max_artifact_bytes:  # geometry-view.md §6.1: 넘으면 ui 상한으로 자른다
        w.append(ConfigIssue("geometry.view.max_glb_bytes",
                             f"ui.max_artifact_bytes({s.ui.max_artifact_bytes})보다 커서 그 값으로 줄여 씁니다"))
    tmpl, res = predict_parametric_missing(s)
    if not tmpl and res:
        w.append(ConfigIssue(res[0], "commands.mesh가 {include_tcl}을 쓰는데 이 자원이 비어 있어 ④ 파라미터 예측(형상 생성)이 비활성입니다"))
    elif "commands.geom_update" in tmpl:
        w.append(ConfigIssue("commands.geom_update", "형상 갱신 템플릿이 없어 ④ 파라미터 예측(형상 생성)이 비활성입니다 — 준비된 입력 예측만 쓸 수 있습니다"))
    return w
