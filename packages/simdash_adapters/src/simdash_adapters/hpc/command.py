"""command 모드 HPC 게이트웨이(platform.md §12.3). argv 템플릿 + 정규식 + 상태맵.

- 외부 명령은 `shell=False` 인자 배열로만 실행한다. `subprocess`는 메서드 안에서 import한다(모듈 최상위 import 금지).
- 자식 프로세스 환경은 호출자가 `env_factory`로 준다(패키지는 환경변수를 읽지 않는다).
- 마스킹하지 않는다: `HpcGatewayError` 메시지(stderr ≤300자)와 `raw_stdout`(≤4 KiB)은 원문이며,
  저장·로그 전에 호출자가 마스킹한다.
"""

from __future__ import annotations

import logging
import os
import re
import string
from collections.abc import Callable, Mapping
from typing import Any

from ..pathstr import is_abs_path_str
from .config import CommandConfig, HpcDefaults
from .types import HpcAvailability, HpcGatewayError, HpcStatus, HpcSubmitResult, HpcSubmitSpec

DEFAULT_LOGGER = "simdash_adapters.hpc.command"

PLACEHOLDERS = frozenset(
    {"job_name", "run_key", "study", "input_file", "input_dir", "result_dir", "queue", "ncpus", "walltime", "external_job_id"}
)
JOB_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
QUEUE_RE = re.compile(r"^[A-Za-z0-9_.\-@]{1,64}$")
WALLTIME_RE = re.compile(r"^\d{1,4}:\d{2}:\d{2}$")
PATH_RE = re.compile(r"^[A-Za-z0-9_./:\\\-]+$")
FORBIDDEN_EXT = (".bat", ".cmd", ".ps1")
VALID_STATES = {"QUEUED", "RUNNING", "FINISHED"}


def _as_cfg(cfg: Any) -> CommandConfig:
    return cfg if isinstance(cfg, CommandConfig) else CommandConfig.from_obj(cfg)


def _norm_exe(p: str) -> str:
    n = p.replace("\\", "/")
    return n.lower() if os.name == "nt" or re.match(r"^[A-Za-z]:/", n) else n


def validate_command_config(cfg: Any) -> list[str]:
    """설정 문제 목록(한국어 문구). 빈 목록이면 사용 가능. `cfg`는 CommandConfig 또는 같은 속성을 가진 객체."""
    c = _as_cfg(cfg)
    problems: list[str] = []
    allowed = {_norm_exe(x) for x in c.allowed_executables}
    for x in c.allowed_executables:
        if not is_abs_path_str(x):
            problems.append(f"allowed_executables 항목은 절대경로여야 합니다: {x}")
        if x.lower().endswith(FORBIDDEN_EXT):
            problems.append(f".bat·.cmd·.ps1은 허용되지 않습니다: {x}")
    for key in ("submit", "status", "cancel"):
        tpl = getattr(c, key)
        if not isinstance(tpl, (list, tuple)) or not tpl or not all(isinstance(e, str) for e in tpl):
            problems.append(f"{key}는 문자열 배열이어야 합니다")
            continue
        exe = tpl[0]
        if not is_abs_path_str(exe):
            problems.append(f"{key} argv[0]은 절대경로여야 합니다")
        if exe.lower().endswith(FORBIDDEN_EXT):
            problems.append(f"{key} argv[0]에 .bat·.cmd·.ps1은 쓸 수 없습니다")
        if _norm_exe(exe) not in allowed:
            problems.append(f"{key} argv[0]이 allowed_executables에 없습니다")
        for el in tpl:
            try:
                for _lit, field, spec, conv in string.Formatter().parse(el):
                    if field is None:
                        continue
                    if field not in PLACEHOLDERS or spec or conv:
                        problems.append(f"{key}: 허용되지 않는 placeholder '{{{field}}}'")
            except ValueError as exc:
                problems.append(f"{key}: 템플릿 형식 오류 {exc}")
    for key, groups in (("job_id_regex", ("job_id",)), ("state_regex", ("state",)), ("exit_code_regex", ("exit",)), ("not_found_regex", ())):
        pat = getattr(c, key)
        if pat is None:
            if key in ("job_id_regex", "state_regex"):
                problems.append(f"{key}는 필수입니다")
            continue
        try:
            rx = re.compile(pat, re.MULTILINE)
        except re.error as exc:
            problems.append(f"{key} 정규식 오류: {exc}")
            continue
        for g in groups:
            if g not in rx.groupindex:
                problems.append(f"{key}에 그룹 '{g}'이 없습니다")
    for raw, mapped in c.state_map.items():
        if mapped not in VALID_STATES:
            problems.append(f"state_map[{raw}]은 QUEUED|RUNNING|FINISHED")
    return problems


def _check_value(name: str, v: str, job_id_rx: re.Pattern[str]) -> str:
    if re.search(r"[\x00-\x1f\x7f]", v) or len(v) > 1024:
        raise HpcGatewayError("SUBMIT_FAILED", f"'{name}' 값이 허용되지 않습니다")
    if name == "external_job_id":
        if not job_id_rx.match(v):
            raise HpcGatewayError("PARSE_FAILED", "external_job_id 형식 오류")
    elif name == "job_name":
        if not JOB_NAME_RE.match(v):
            raise HpcGatewayError("SUBMIT_FAILED", "job_name 형식 오류")
    elif name == "queue":
        if not QUEUE_RE.match(v):
            raise HpcGatewayError("SUBMIT_FAILED", "queue 형식 오류")
    elif name == "ncpus":
        if not v.isdigit() or not 1 <= int(v) <= 4096:
            raise HpcGatewayError("SUBMIT_FAILED", "ncpus는 1~4096")
    elif name == "walltime":
        if not WALLTIME_RE.match(v):
            raise HpcGatewayError("SUBMIT_FAILED", "walltime 형식 오류(HH:MM:SS)")
    elif name in ("input_file", "input_dir", "result_dir"):
        if not PATH_RE.match(v):
            raise HpcGatewayError("SUBMIT_FAILED", f"'{name}' 경로에 허용되지 않는 문자가 있습니다")
    elif name in ("run_key", "study"):
        if not JOB_NAME_RE.match(v):
            raise HpcGatewayError("SUBMIT_FAILED", f"'{name}' 형식 오류")
    return v


def _render(c: CommandConfig, key: str, values: Mapping[str, Any]) -> list[str]:
    jid_rx = re.compile(c.job_id_regex)  # type: ignore[arg-type]
    out = []
    for el in getattr(c, key):
        names = [f for _l, f, _s, _c in string.Formatter().parse(el) if f is not None]
        mapping = {}
        for n in names:
            v = values.get(n)
            if v is None:
                raise HpcGatewayError("SUBMIT_FAILED", f"'{n}' 값이 없습니다")
            mapping[n] = _check_value(n, str(v), jid_rx)
        out.append(el.format_map(mapping) if names else el)
    return out


def render_argv(cfg: Any, key: str, values: Mapping[str, Any]) -> list[str]:
    """명령 템플릿(`submit`·`status`·`cancel`)을 값으로 채운 argv. 설정 오류면 NOT_CONFIGURED, 값 규칙 위반이면 SUBMIT_FAILED·PARSE_FAILED."""
    c = _as_cfg(cfg)
    if validate_command_config(c):
        raise HpcGatewayError("NOT_CONFIGURED", "PBS 명령 설정 오류")
    return _render(c, key, values)


class CommandHpcGateway:
    def __init__(self, cfg: Any, defaults: Any, env_factory: Callable[[], Mapping[str, str]] | None = None,
                 logger: logging.Logger | None = None) -> None:
        self.c = _as_cfg(cfg)
        self.defaults = defaults if isinstance(defaults, HpcDefaults) else HpcDefaults.from_obj(defaults)
        self.env_factory = env_factory  # 실행 시점에 자식 환경(허용목록)을 만든다
        self.log = logger or logging.getLogger(DEFAULT_LOGGER)
        self.problems = validate_command_config(self.c)
        self._job_id_rx = re.compile(self.c.job_id_regex, re.MULTILINE) if not self.problems else re.compile("$^")  # type: ignore[arg-type]

    def availability(self) -> HpcAvailability:
        if self.problems:
            return HpcAvailability(False, "command", "PBS 명령 설정 오류: " + "; ".join(self.problems)[:300])
        return HpcAvailability(True, "command", "PBS 명령 모드")

    def render(self, key: str, values: Mapping[str, Any]) -> list[str]:
        if self.problems:
            raise HpcGatewayError("NOT_CONFIGURED", "PBS 명령 설정 오류")
        return _render(self.c, key, values)

    def _run(self, argv: list[str], timeout: float) -> tuple[int, str, str]:
        import subprocess  # 호출자(워커 hpc 스레드)에서만 실행된다

        try:
            cp = subprocess.run(argv, shell=False, capture_output=True, timeout=timeout, text=True, encoding="utf-8",
                                errors="replace", env=self.env_factory() if self.env_factory else None)
        except subprocess.TimeoutExpired:
            raise HpcGatewayError("TIMEOUT", "PBS 명령 시간 초과") from None
        except OSError as exc:
            raise HpcGatewayError("UNAVAILABLE", f"PBS 명령 실행 실패: {exc}") from None
        return cp.returncode, cp.stdout or "", cp.stderr or ""

    def submit(self, spec: HpcSubmitSpec) -> HpcSubmitResult:
        vals = {
            "job_name": spec.job_name, "run_key": spec.run_key, "study": spec.study, "input_file": spec.input_file,
            "input_dir": spec.input_dir, "result_dir": spec.result_dir,
            "queue": spec.queue or self.defaults.queue, "ncpus": spec.ncpus or self.defaults.ncpus,
            "walltime": spec.walltime or self.defaults.walltime,
        }
        argv = self.render("submit", vals)
        rc, out, err = self._run(argv, self.c.submit_timeout_s)
        if rc != 0:
            raise HpcGatewayError("SUBMIT_FAILED", f"제출 실패(종료코드 {rc}): {(err or out)[:300]}")
        m = re.search(self.c.job_id_regex, out, re.MULTILINE)  # type: ignore[arg-type]
        if not m:
            raise HpcGatewayError("PARSE_FAILED", "제출 결과에서 job id를 찾지 못했습니다")
        return HpcSubmitResult(m.group("job_id"), out[:4096])

    def status(self, external_job_id: str) -> HpcStatus:
        argv = self.render("status", {"external_job_id": external_job_id})
        rc, out, err = self._run(argv, self.c.status_timeout_s)
        text = out + "\n" + err
        if self.c.not_found_regex and re.search(self.c.not_found_regex, text):
            return HpcStatus("UNKNOWN", None, None, True)
        m = re.search(self.c.state_regex, text, re.MULTILINE)  # type: ignore[arg-type]
        if not m:
            return HpcStatus("UNKNOWN", None, None, False)
        raw = m.group("state")
        mapped = self.c.state_map.get(raw, "UNKNOWN")
        exit_code = None
        if self.c.exit_code_regex:
            em = re.search(self.c.exit_code_regex, text, re.MULTILINE)
            if em:
                try:
                    exit_code = int(em.group("exit"))
                except (TypeError, ValueError):
                    # 정규식이 숫자가 아닌 값을 잡으면 판정하지 않는다(UNKNOWN → lost_after_polls 규칙)
                    self.log.warning("PBS 종료코드 해석 실패: %r (job %s)", em.group("exit"), external_job_id)
                    return HpcStatus("UNKNOWN", raw, None, False)
        return HpcStatus(mapped if mapped in VALID_STATES else "UNKNOWN", raw, exit_code, False)  # type: ignore[arg-type]

    def cancel(self, external_job_id: str) -> None:
        argv = self.render("cancel", {"external_job_id": external_job_id})
        rc, out, err = self._run(argv, self.c.cancel_timeout_s)
        if rc != 0:
            raise HpcGatewayError("UNAVAILABLE", f"취소 실패(종료코드 {rc}): {(err or out)[:300]}")
