"""scx 모드 HPC 게이트웨이(phase3 §16, platform.md §12.5): 대시보드 SCX relay 경유 Radioss 제출.

PhysicsAI는 SCX 어댑터를 import·실행하지 않는다(토큰 공유 — 대시보드가 유일한 어댑터 소유자, scx_relay.md §0).
`HpcJobGateway`(availability·submit·status·cancel) + scx 전용 메서드(health·ensure_new_dir·mkdirs·upload·batch·submit_radioss·
list·download·resolve). 범용 `submit(spec)`은 NOT_CONFIGURED — HPC_SUBMIT·COLLECT step이 `availability().mode == "scx"`로 분기한다.
드라이브를 지우거나 옮기는 메서드는 없다(정적 시험). 오류 문구·JobInfo.error_message는 원문 — 호출자가 마스킹한다.
"""

from __future__ import annotations

import fnmatch
import logging
import re
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from typing import Any, Literal

from .scx_client import MSG_RELAY_DISABLED, MSG_RELAY_NO_ROUTE, ScxRelayClient, parse_relay_url
from .scx_naming import MAX_SUFFIX, display_path, drive_base_rel, rel_problem, with_suffix
from .types import HpcAvailability, HpcGatewayError, HpcStatus, HpcSubmitResult, HpcSubmitSpec

__all__ = [
    "ScxConfig", "ScxRadiossRequest", "ScxSubmitOutcome", "ScxHpcGateway", "validate_scx_config", "read_secret_file",
    "SECRET_RE", "SCX_STATUS_MAP",
]

DEFAULT_LOGGER = "simdash_adapters.hpc.scx"
SECRET_RE = re.compile(r"^[A-Za-z0-9_\-]{43,128}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_MSG_OK = "SCX(대시보드 연결)"
_MSG_NO_JOB_API = "대시보드 어댑터에 잡 API 없음(v0.3.0 이상 필요)"
_MSG_HEALTH_FAIL = "대시보드 연결 확인 실패(일시)"
_MSG_GENERIC_SUBMIT = "scx 모드는 단계 A·B 흐름으로 제출합니다(HPC_SUBMIT step)"
# GET /jobs/{id}.status(어댑터 값 그대로, 대소문자 무시) → (HpcState, outcome)  (§16.6)
SCX_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    "queued": ("QUEUED", None),
    "running": ("RUNNING", None),
    "completed": ("FINISHED", "SUCCEEDED"),
    "failed": ("FINISHED", "FAILED"),
    "aborted": ("FINISHED", "FAILED"),
}
HEALTH_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class ScxConfig:
    """`hpc.scx.*`와 1:1(기본값은 플랫폼 설정 스키마 한 곳 — 여기는 필수 인자)."""

    relay_url: str
    secret_file: str
    drive_base: str
    home_display: str
    appliance: str
    version: str
    ncpu: int
    memory_gb: int | None
    queue_type: str
    run_type: str
    mpi: str
    single_precision: bool
    poll_interval_s: float | None
    max_download_bytes: int
    stage_patterns: tuple[str, ...]
    list_additional_paths: bool
    max_stage_bytes: int
    stage_poll_s: float
    stage_timeout_s: float
    submit_replay_attempts: int
    submit_replay_wait_s: float
    http_timeout_s: float
    transfer_timeout_s: float
    collect_max_depth: int
    health_ttl_s: float

    @classmethod
    def _build(cls, values: Mapping[str, Any]) -> ScxConfig:
        v = dict(values)
        if isinstance(v.get("stage_patterns"), (list, tuple)):
            v["stage_patterns"] = tuple(v["stage_patterns"])
        return cls(**v)

    @classmethod
    def from_obj(cls, o: Any) -> ScxConfig:
        return cls._build({f.name: getattr(o, f.name) for f in fields(cls)})

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> ScxConfig:
        return cls._build(d)


def _as_cfg(cfg: Any) -> ScxConfig:
    return cfg if isinstance(cfg, ScxConfig) else ScxConfig.from_obj(cfg)


def _text_ok(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, str) and lo <= len(v) <= hi and not _CTRL.search(v)


def _int_in(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _num_in(v: Any, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def validate_scx_config(cfg: Any) -> list[str]:
    """설정 문제 목록(한국어, 비밀 값 없음). 빈 목록이면 사용 가능(비밀 파일은 별도 — availability)."""
    c = _as_cfg(cfg)
    p: list[str] = []
    if not c.relay_url:
        p.append("relay_url은 scx 모드에서 필수입니다")
    else:
        try:
            parse_relay_url(c.relay_url)
        except ValueError as exc:
            p.append(str(exc))
    if not isinstance(c.secret_file, str) or _CTRL.search(c.secret_file or ""):
        p.append("secret_file 형식 오류")
    try:
        drive_base_rel(c.drive_base)
    except ValueError as exc:
        p.append(str(exc))
    if not _text_ok(c.home_display, 1, 1024):
        p.append("home_display는 1~1024자")
    if not _text_ok(c.appliance, 1, 128):
        p.append("appliance는 필수(1~128자, 제어문자 금지 — 서버 확인 E4-11-1)")
    if not _text_ok(c.version, 1, 128):
        p.append("version은 필수(1~128자 — 서버 확인 E4-11-2)")
    if not _int_in(c.ncpu, 1, 4096):
        p.append("ncpu는 1~4096")
    if c.memory_gb is not None and not _int_in(c.memory_gb, 1, 65536):
        p.append("memory_gb는 null 또는 1~65536")
    if not _text_ok(c.queue_type, 1, 64):
        p.append("queue_type은 1~64자")
    for k in ("run_type", "mpi"):
        if not _text_ok(getattr(c, k), 1, 128):
            p.append(f"{k}는 1~128자")
    if not isinstance(c.single_precision, bool):
        p.append("single_precision은 true|false")
    if c.poll_interval_s is not None and not _num_in(c.poll_interval_s, 10, 3600):
        p.append("poll_interval_s는 null 또는 10~3600")
    for k in ("max_download_bytes", "max_stage_bytes"):
        if not _int_in(getattr(c, k), 1 << 20, 1 << 40):
            p.append(f"{k}는 1 MiB~2^40")
    pats = c.stage_patterns
    if not isinstance(pats, tuple) or not 1 <= len(pats) <= 32:
        p.append("stage_patterns는 1~32개")
    else:
        for pat in pats:
            if not _text_ok(pat, 1, 128) or "/" in pat or "\\" in pat:
                p.append(f"stage_patterns 항목 형식 오류('/'·'\\' 금지): {pat!r}"[:200])
    if not isinstance(c.list_additional_paths, bool):
        p.append("list_additional_paths는 true|false")
    if not _num_in(c.stage_poll_s, 1, 60):
        p.append("stage_poll_s는 1~60")
    if not _num_in(c.stage_timeout_s, 60, 86400):
        p.append("stage_timeout_s는 60~86400")
    if not _int_in(c.submit_replay_attempts, 0, 10):
        p.append("submit_replay_attempts는 0~10")
    if not _num_in(c.submit_replay_wait_s, 1, 120):
        p.append("submit_replay_wait_s는 1~120")
    if not _num_in(c.http_timeout_s, 1, 600):
        p.append("http_timeout_s는 1~600")
    if not _num_in(c.transfer_timeout_s, 10, 86400):
        p.append("transfer_timeout_s는 10~86400")
    if not _int_in(c.collect_max_depth, 0, 5):
        p.append("collect_max_depth는 0~5")
    if not _num_in(c.health_ttl_s, 0, 600):
        p.append("health_ttl_s는 0~600")
    return p


def read_secret_file(path: str) -> tuple[str | None, str | None]:
    """(값, 문제). 파일 한 줄 base64url 43~128자(앞뒤 공백·BOM 무시). 문제 문구에 값은 넣지 않는다."""
    if not path:
        return None, "비밀 파일 경로 없음"
    try:
        with open(path, encoding="utf-8-sig") as fh:
            raw = fh.read(4096)
    except FileNotFoundError:
        return None, "비밀 파일 없음"
    except (OSError, UnicodeDecodeError):
        return None, "비밀 파일을 읽을 수 없음"
    value = raw.strip()
    if not SECRET_RE.match(value):
        return None, "비밀 파일 형식 오류(한 줄 base64url 43~128자)"
    return value, None


@dataclass(frozen=True)
class ScxRadiossRequest:
    """`POST /jobs/radioss` 본문(scx_relay.md §5.7). 경로는 홈 기준 상대."""

    request_id: str
    input_path: str
    engine_paths: tuple[str, ...]
    additional_paths: tuple[str, ...]
    version: str
    appliance: str
    ncpu: int
    memory_gb: int | None
    queue_type: str
    run_type: str
    mpi: str
    single_precision: bool
    client_ref: Mapping[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "input_path": self.input_path,
            "engine_paths": list(self.engine_paths), "additional_paths": list(self.additional_paths),
            "version": self.version,
            "resources": {"appliance": self.appliance, "ncpu": self.ncpu, "memory_gb": self.memory_gb, "queue_type": self.queue_type},
            "run_type": self.run_type, "mpi": self.mpi, "single_precision": self.single_precision,
            "client_ref": {k: str(v)[:128] for k, v in dict(self.client_ref).items()},
        }

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> ScxRadiossRequest:
        r = d.get("resources") or {}
        return cls(request_id=d["request_id"], input_path=d["input_path"], engine_paths=tuple(d.get("engine_paths") or ()),
                   additional_paths=tuple(d.get("additional_paths") or ()), version=d["version"], appliance=r["appliance"],
                   ncpu=int(r["ncpu"]), memory_gb=r.get("memory_gb"), queue_type=r["queue_type"], run_type=d["run_type"],
                   mpi=d["mpi"], single_precision=bool(d["single_precision"]), client_ref=dict(d.get("client_ref") or {}))


@dataclass(frozen=True)
class ScxSubmitOutcome:
    """제출 결과. SUBMITTED(잡 ID 있음) · UNKNOWN(결과 모름 — 사람 확인) · FAILED(확정 실패)."""

    state: Literal["SUBMITTED", "UNKNOWN", "FAILED"]
    job_id: str | None = None
    status: str | None = None
    output_path: str | None = None
    output_rel: str | None = None
    code: str | None = None
    message: str = ""
    replays: int = 0


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


class ScxHpcGateway:
    def __init__(self, cfg: Any, secret_path: str | None, *, logger: logging.Logger | None = None,
                 sleep: Callable[[float], None] | None = None, clock: Callable[[], float] | None = None,
                 on_secret: Callable[[str], None] | None = None) -> None:
        self.cfg = _as_cfg(cfg)
        self.secret_path = secret_path or ""
        self.log = logger or logging.getLogger(DEFAULT_LOGGER)
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._on_secret = on_secret
        self.problems = validate_scx_config(self.cfg)
        self.base = drive_base_rel(self.cfg.drive_base) if not self.problems else ""
        self._lock = threading.Lock()
        self._client: ScxRelayClient | None = None
        self._secret_problem: str | None = None
        self._health: tuple[float, dict[str, Any] | None, str | None] | None = None
        self._load_secret()

    def __repr__(self) -> str:
        return f"ScxHpcGateway(relay={self.cfg.relay_url!r}, secret_file={self.secret_path!r})"

    # ---- 구성·비밀 ----
    def _load_secret(self) -> None:
        if self.problems:
            return
        value, problem = read_secret_file(self.secret_path)
        self._secret_problem = problem
        if value is None:
            return
        if self._on_secret is not None:
            self._on_secret(value)  # 로그 마스킹 목록 등록(값은 로그·오류에 쓰지 않음)
        self._client = ScxRelayClient(self.cfg.relay_url, value, http_timeout_s=self.cfg.http_timeout_s,
                                      transfer_timeout_s=self.cfg.transfer_timeout_s)

    def client(self) -> ScxRelayClient:
        if self.problems:
            raise HpcGatewayError("NOT_CONFIGURED", "SCX 설정 오류: " + "; ".join(self.problems)[:300])
        with self._lock:
            if self._client is None:
                self._load_secret()  # 관리자가 나중에 비밀 파일을 만든 경우
            if self._client is None:
                raise HpcGatewayError("NOT_CONFIGURED", f"SCX relay 비밀 파일 문제: {self.secret_path} ({self._secret_problem})")
            return self._client

    def secret_present(self) -> bool:
        return read_secret_file(self.secret_path)[0] is not None if not self.problems else False

    def display(self, rel: str) -> str:
        return display_path(self.cfg.home_display, rel)

    # ---- HpcJobGateway ----
    def availability(self) -> HpcAvailability:
        if self.problems:
            return HpcAvailability(False, "scx", "SCX 설정 오류: " + "; ".join(self.problems)[:300])
        try:
            c = self.client()
        except HpcGatewayError as exc:
            return HpcAvailability(False, "scx", str(exc))
        now = self._clock()
        cached = self._health
        if cached is None or self.cfg.health_ttl_s <= 0 or now - cached[0] >= self.cfg.health_ttl_s:
            try:
                h = c.call("GET", "/health", timeout=HEALTH_TIMEOUT_S)
                cached = (now, h if isinstance(h, dict) else {}, None)
            except HpcGatewayError as exc:
                cached = (now, None, str(exc))
            self._health = cached
        _ts, h, err = cached
        if h is None:
            if err in (MSG_RELAY_NO_ROUTE, MSG_RELAY_DISABLED):  # 설정 원인이 분명한 두 경우는 조치 문구를 그대로 보인다
                return HpcAvailability(True, "scx", f"{_MSG_OK} — {err}")
            return HpcAvailability(True, "scx", f"{_MSG_OK} — {_MSG_HEALTH_FAIL}")
        if h.get("job_api") is False:
            return HpcAvailability(False, "scx", _MSG_NO_JOB_API)
        return HpcAvailability(True, "scx", _MSG_OK)

    def submit(self, spec: HpcSubmitSpec) -> HpcSubmitResult:
        raise HpcGatewayError("NOT_CONFIGURED", _MSG_GENERIC_SUBMIT)

    def status(self, external_job_id: str) -> HpcStatus:
        try:
            d = self.client().call("GET", "/jobs/" + ScxRelayClient.seg(external_job_id))
        except HpcGatewayError as exc:
            if exc.relay_code == "SCX_JOB_NOT_FOUND":  # 어댑터가 잡을 모름 → UNKNOWN 계수(PBS not_found 규칙은 쓰지 않음)
                return HpcStatus("UNKNOWN", "SCX_JOB_NOT_FOUND", None, False)
            if exc.relay_code == "JOB_NOT_FOUND":
                raise HpcGatewayError("UNAVAILABLE", "relay 기록에 없는 잡입니다(설정·DB 불일치) — 대시보드 SCX 연결 확인",
                                      relay_code="JOB_NOT_FOUND", http_status=exc.http_status) from None
            raise HpcGatewayError("UNAVAILABLE", f"{exc} — 대시보드 SCX 연결 확인", relay_code=exc.relay_code,
                                  http_status=exc.http_status, retryable=exc.retryable, transport=exc.transport) from None
        d = d if isinstance(d, dict) else {}
        raw = d.get("status")
        raw_s = raw if isinstance(raw, str) else None
        state, outcome = SCX_STATUS_MAP.get(_fold(raw_s or "").strip(), ("UNKNOWN", None))
        return HpcStatus(state, raw_s, None, False, outcome=outcome,  # type: ignore[arg-type]
                         output_path=_opt_str(d.get("output_path")), output_rel=_opt_str(d.get("output_rel")),
                         error_message=_opt_str(d.get("error_message")))

    def cancel(self, external_job_id: str) -> None:
        try:
            self.client().call("POST", "/jobs/" + ScxRelayClient.seg(external_job_id) + "/terminate", body={})
        except HpcGatewayError as exc:
            raise HpcGatewayError("UNAVAILABLE", f"SCX 잡 취소 실패: {exc}", relay_code=exc.relay_code,
                                  http_status=exc.http_status, transport=exc.transport) from None

    # ---- scx 전용 ----
    def health(self) -> dict[str, Any]:
        h = self.client().call("GET", "/health")
        if not isinstance(h, dict):
            raise HpcGatewayError("PARSE_FAILED", "relay /health 응답 형식 오류")
        self._health = (self._clock(), h, None)
        return h

    def list(self, rel: str, max_entries: int = 5000) -> list[dict[str, Any]]:
        d = self.client().call("GET", "/list", query={"path": rel, "max_entries": int(max_entries)})
        entries = (d or {}).get("entries") if isinstance(d, dict) else None
        if not isinstance(entries, list):
            raise HpcGatewayError("PARSE_FAILED", "relay /list 응답 형식 오류")
        return [e for e in entries if isinstance(e, dict)]

    def ensure_new_dir(self, parent: str, name: str) -> str:
        """`parent` 아래 아직 없는 잡 폴더 이름(`name`, `name_2`…`name_9`). 모두 있으면 SCX_REMOTE_DIR_EXISTS. 폴더를 만들지는 않는다."""
        try:
            existing = {_fold(str(e.get("name") or "")) for e in self.list(parent, 50000)} if parent else None
        except HpcGatewayError as exc:
            if exc.relay_code != "NOT_FOUND":
                raise
            existing = set()
        if existing is None:  # 기준이 홈 자체인 경우는 없음(잡 폴더는 항상 <프로젝트>/<잡> — 깊이 2)
            raise HpcGatewayError("SUBMIT_FAILED", "잡 폴더의 부모 경로가 비어 있습니다", relay_code="INVALID_PATH")
        for n in range(1, MAX_SUFFIX + 1):
            cand = with_suffix(name, n)
            if _fold(cand) not in existing:
                return cand
        raise HpcGatewayError("SUBMIT_FAILED", f"잡 폴더가 이미 있습니다({name}_2…_{MAX_SUFFIX}까지)", relay_code="SCX_REMOTE_DIR_EXISTS")

    def mkdirs(self, rel: str, request_id: str) -> dict[str, Any]:
        why = rel_problem(rel)
        if why:
            raise HpcGatewayError("SUBMIT_FAILED", f"드라이브 경로 형식 오류: {why}", relay_code="INVALID_PATH")
        d = self.client().call("POST", "/mkdirs", body={"request_id": request_id, "path": rel})
        if not isinstance(d, dict) or not d.get("batch_id"):
            raise HpcGatewayError("PARSE_FAILED", "relay /mkdirs 응답 형식 오류")
        return d

    def upload(self, local_path: str, rel_dir: str, name: str, sha256: str, request_id: str, *, size: int,
               on_chunk: Callable[[int], None] | None = None) -> str:
        d = self.client().upload_file(local_path, rel_dir, name, sha256, size, request_id, on_chunk=on_chunk)
        if not isinstance(d, dict) or not d.get("batch_id"):
            raise HpcGatewayError("PARSE_FAILED", "relay /files 응답 형식 오류")
        return str(d["batch_id"])

    def batch(self, batch_id: str) -> dict[str, Any]:
        d = self.client().call("GET", "/batches/" + ScxRelayClient.seg(batch_id))
        if not isinstance(d, dict) or not isinstance(d.get("state"), str):
            raise HpcGatewayError("PARSE_FAILED", "relay /batches 응답 형식 오류")
        return d

    def submit_radioss(self, req: ScxRadiossRequest) -> ScxSubmitOutcome:
        """`POST /jobs/radioss`. 전송 오류·시간 초과·SUBMISSION_IN_PROGRESS·코드 없는 5xx는 같은 request_id로 replay
        (`submit_replay_attempts`회, relay가 어댑터를 다시 부르지 않음). SUBMISSION_UNKNOWN·replay 소진 → UNKNOWN, 그 밖 → FAILED."""
        body = req.to_json()
        attempts = 1 + int(self.cfg.submit_replay_attempts)
        last = ""
        for i in range(attempts):
            if i:
                self.log.info("SCX 제출 replay %d/%d (request_id %s): %s", i, attempts - 1, req.request_id, last)
                self._sleep(float(self.cfg.submit_replay_wait_s))
            try:
                d = self.client().call("POST", "/jobs/radioss", body=body)
            except HpcGatewayError as exc:
                if exc.relay_code == "SUBMISSION_UNKNOWN":
                    return ScxSubmitOutcome("UNKNOWN", code="SUBMISSION_UNKNOWN", message=str(exc), replays=i)
                if exc.code == "NOT_CONFIGURED" or not (
                        exc.transport or exc.relay_code == "SUBMISSION_IN_PROGRESS" or (exc.relay_code is None and (exc.http_status or 0) >= 500)):
                    return ScxSubmitOutcome("FAILED", code=exc.relay_code or exc.code, message=str(exc), replays=i)
                last = str(exc)
                continue
            job = (d or {}).get("job") if isinstance(d, dict) else None
            if isinstance(d, dict) and d.get("state") in ("SUBMITTED", "ATTACHED") and isinstance(job, dict) and job.get("job_id"):
                return ScxSubmitOutcome("SUBMITTED", job_id=str(job["job_id"]), status=_opt_str(job.get("status")),
                                        output_path=_opt_str(job.get("output_path")), output_rel=_opt_str(job.get("output_rel")),
                                        replays=i)
            last = "relay 제출 응답 형식 오류"
        return ScxSubmitOutcome("UNKNOWN", code="SUBMISSION_UNKNOWN", message=f"replay를 다 써도 응답 없음: {last}"[:300],
                                replays=attempts - 1)

    def download(self, rel: str, dst_local: str, max_bytes: int, *, on_chunk: Callable[[int], None] | None = None) -> tuple[int, str]:
        """드라이브 파일을 `dst_local`(호출자가 정한 `.part` 경로)에 쓴다. 크기·`X-Content-SHA256` 불일치면 HASH_MISMATCH."""
        with open(dst_local, "wb") as fh:
            size, sha, want_sha, want_len = self.client().download_to(rel, max_bytes, fh, on_chunk=on_chunk)
        if not want_sha or want_sha != sha or (want_len is not None and want_len != size):
            raise HpcGatewayError("PARSE_FAILED", "내려받은 파일의 크기·해시가 relay 값과 다릅니다", relay_code="HASH_MISMATCH")
        return size, sha

    def resolve(self, request_id: str, action: str, job_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"action": action}
        if job_id is not None:
            body["job_id"] = job_id
        d = self.client().call("POST", "/submissions/" + ScxRelayClient.seg(request_id) + "/resolve", body=body)
        return d if isinstance(d, dict) else {}

    def matches_stage_pattern(self, name: str) -> bool:
        """올릴 파일 이름 일치(대소문자 무시 — Windows·Linux 같은 결과)."""
        low = name.casefold()
        return any(fnmatch.fnmatchcase(low, p.casefold()) for p in self.cfg.stage_patterns)


def _opt_str(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None
