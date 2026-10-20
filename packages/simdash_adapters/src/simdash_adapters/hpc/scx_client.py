"""대시보드 SCX relay HTTP 클라이언트(phase3 §16.2, docs/contracts/scx_relay.md). 표준 라이브러리 `http.client`만.

- loopback 전용: `relay_url`은 `http://127.0.0.1:<port>`·`http://[::1]:<port>`·`http://localhost:<port>`만(경로·쿼리·사용자 정보 없음).
  클라이언트가 접두 `/internal/scx-relay/v1`을 붙인다.
- 리다이렉트를 따르지 않는다(3xx는 오류). 모든 요청에 시간 한도.
- 공유 비밀은 헤더 `X-SCX-Relay-Key`에만 싣는다(URL·쿼리·오류 문구·repr에 값 없음).
- 드라이브를 지우거나 옮기는 메서드는 없다(정적 시험). 쓰기는 relay의 업로드 대기열(MKDIR·FILE, 덮어쓰기 없음)뿐.
- 오류는 `HpcGatewayError`(code + relay_code·http_status·retryable·transport). 문구는 마스킹 전 원문 — 호출자가 마스킹한다.
"""

from __future__ import annotations

import hashlib
import http.client
import json
from collections.abc import Callable
from typing import Any, BinaryIO
from urllib.parse import quote, urlencode, urlsplit

from .types import HpcGatewayError

__all__ = ["RELAY_PREFIX", "CLIENT_NAME", "parse_relay_url", "ScxRelayClient"]

RELAY_PREFIX = "/internal/scx-relay/v1"
CLIENT_NAME = "physicsai"
CHUNK = 1024 * 1024
_LOOPBACK = ("127.0.0.1", "::1", "localhost")
# 연결은 되지만 지금은 못 하는 상태(상태 조회에서 hpc_unreachable_since로 센다)
_UNAVAILABLE_CODES = frozenset({
    "RELAY_DISABLED", "RELAY_FORBIDDEN", "RELAY_UNAUTHORIZED", "DRIVE_MODE_DISABLED", "DRIVE_BUSY", "DRIVE_AUTH_REQUIRED",
    "DRIVE_TIMEOUT", "DRIVE_UNAVAILABLE", "DRIVE_STAGING_FULL", "DRIVE_INTERNAL", "LOCKED", "JOB_API_UNAVAILABLE",
})
_NOT_FOUND_CODES = frozenset({"NOT_FOUND", "JOB_NOT_FOUND", "SCX_JOB_NOT_FOUND"})
MSG_RELAY_NO_ROUTE = ("relay HTTP 404 — relay 경로가 없습니다. relay_url이 대시보드 화면(Vite·Caddy) 포트가 아니라 백엔드(uvicorn) 포트인지, "
                      "대시보드가 relay 포함 버전인지 확인하세요")
MSG_RELAY_DISABLED = "대시보드 relay가 꺼져 있습니다(SIMDASH_SCX_RELAY_ENABLED=true 후 대시보드 재시작)"


def parse_relay_url(url: str) -> tuple[str, int]:
    """relay_url → (host, port). loopback·http·포트 필수·경로/쿼리/사용자 정보 없음. 위반이면 ValueError(값은 문구에 넣지 않음)."""
    if not isinstance(url, str) or not url:
        raise ValueError("relay_url이 비어 있습니다")
    if any(ord(c) < 0x21 or ord(c) == 0x7F for c in url):
        raise ValueError("relay_url에 공백·제어문자를 쓸 수 없습니다")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        raise ValueError("relay_url 형식 오류") from None
    if u.scheme != "http":
        raise ValueError("relay_url은 http://만 허용합니다(loopback)")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise ValueError("relay_url에 사용자 정보를 쓸 수 없습니다")
    if u.path not in ("", "/") or u.query or u.fragment:
        raise ValueError("relay_url에 경로·쿼리를 쓸 수 없습니다(클라이언트가 /internal/scx-relay/v1을 붙임)")
    host = (u.hostname or "").lower()
    if host not in _LOOPBACK:
        raise ValueError("relay_url은 127.0.0.1·[::1]·localhost만 허용합니다")
    if host == "::1" and not u.netloc.startswith("["):
        raise ValueError("relay_url 형식 오류")
    if port is None or not 1 <= port <= 65535:
        raise ValueError("relay_url에 포트가 필요합니다")
    return host, port


def _gateway_code(status: int, relay_code: str | None) -> str:
    if relay_code == "SUBMISSION_UNKNOWN":
        return "SUBMISSION_UNKNOWN"
    if relay_code in _NOT_FOUND_CODES:
        return "NOT_FOUND"
    if relay_code in _UNAVAILABLE_CODES or status >= 500:
        return "UNAVAILABLE"
    return "SUBMIT_FAILED"


class ScxRelayClient:
    """relay 호출 1개 = HTTP 연결 1개(keep-alive 없음 — 워커 스레드 간 공유 상태 없음)."""

    def __init__(self, relay_url: str, secret: str, *, http_timeout_s: float = 30, transfer_timeout_s: float = 3600,
                 client_name: str = CLIENT_NAME) -> None:
        self.host, self.port = parse_relay_url(relay_url)
        self.__secret = secret
        self.http_timeout_s = float(http_timeout_s)
        self.transfer_timeout_s = float(transfer_timeout_s)
        self.client_name = client_name

    def __repr__(self) -> str:  # 비밀 값 비노출
        return f"ScxRelayClient(host={self.host!r}, port={self.port})"

    # ---- 공통 ----
    def _conn(self, timeout: float) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(self.host, self.port, timeout=timeout)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"X-SCX-Relay-Key": self.__secret, "X-SCX-Relay-Client": self.client_name, "Accept": "application/json"}
        if extra:
            h.update(extra)
        return h

    @staticmethod
    def url(path: str, query: dict[str, Any] | None = None) -> str:
        u = RELAY_PREFIX + path
        if query:
            u += "?" + urlencode({k: v for k, v in query.items() if v is not None}, quote_via=quote)
        return u

    @staticmethod
    def seg(value: str) -> str:
        """경로 구간 하나(잡 ID·묶음 ID·request_id)를 인코딩."""
        return quote(str(value), safe="")

    @staticmethod
    def _transport_error(exc: BaseException, what: str) -> HpcGatewayError:
        kind = "시간 초과" if isinstance(exc, TimeoutError) else type(exc).__name__
        return HpcGatewayError("UNAVAILABLE", f"대시보드 SCX relay {what} 실패({kind})", retryable=True, transport=True)

    @staticmethod
    def _error_from(status: int, raw: bytes) -> HpcGatewayError:
        code: str | None = None
        message = ""
        retryable = False
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, ValueError):
            body = None
        if isinstance(body, dict):
            c = body.get("code")
            code = c if isinstance(c, str) and c else None
            m = body.get("message")
            message = m if isinstance(m, str) else ""
            retryable = bool(body.get("retryable"))
        if 300 <= status < 400:
            return HpcGatewayError("UNAVAILABLE", f"relay 리다이렉트 응답(HTTP {status})은 따르지 않습니다", http_status=status)
        if code == "RELAY_DISABLED":  # 본문(message)은 문구에 넣지 않는다
            return HpcGatewayError(_gateway_code(status, code), MSG_RELAY_DISABLED, relay_code=code, http_status=status,
                                   retryable=retryable or status >= 500)
        if status == 404 and code is None:  # relay 오류 JSON이 아님 = relay 라우트 자체가 없음(화면 포트·구버전 대시보드)
            return HpcGatewayError(_gateway_code(status, None), MSG_RELAY_NO_ROUTE, http_status=status)
        text = f"relay {code or 'HTTP ' + str(status)}" + (f": {message}" if message else "")
        return HpcGatewayError(_gateway_code(status, code), text[:300], relay_code=code, http_status=status,
                               retryable=retryable or status >= 500)

    def call(self, method: str, path: str, *, query: dict[str, Any] | None = None, body: Any = None,
             timeout: float | None = None) -> Any:
        """JSON 요청 1개. 2xx면 JSON 본문(없으면 None), 아니면 HpcGatewayError."""
        data = None
        extra: dict[str, str] = {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            extra = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(data))}
        conn = self._conn(timeout or self.http_timeout_s)
        try:
            conn.request(method, self.url(path, query), body=data, headers=self._headers(extra))
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status
        except (OSError, http.client.HTTPException) as exc:
            raise self._transport_error(exc, "요청") from None
        finally:
            conn.close()
        if not 200 <= status < 300:
            raise self._error_from(status, raw)
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HpcGatewayError("PARSE_FAILED", "relay 응답 JSON 형식 오류", http_status=status, transport=True) from None

    # ---- 업로드(대기열 MKDIR+FILE) ----
    def upload_file(self, local_path: str, dir_rel: str, name: str, sha256: str, size: int, request_id: str,
                    on_chunk: Callable[[int], None] | None = None) -> Any:
        """파일 본문을 스트리밍으로 보낸다(`Content-Length`·`X-Content-SHA256`·`X-Request-Id`). 202/200 묶음 JSON."""
        extra = {"Content-Type": "application/octet-stream", "Content-Length": str(int(size)),
                 "X-Content-SHA256": sha256, "X-Request-Id": request_id}
        conn = self._conn(self.transfer_timeout_s)
        try:
            conn.putrequest("POST", self.url("/files", {"dir": dir_rel, "name": name}), skip_accept_encoding=True)
            for k, v in self._headers(extra).items():
                conn.putheader(k, v)
            conn.endheaders()
            sent = 0
            with open(local_path, "rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    conn.send(chunk)
                    sent += len(chunk)
                    if on_chunk is not None:
                        on_chunk(len(chunk))
            if sent != int(size):
                raise HpcGatewayError("SUBMIT_FAILED", "올리는 중 파일 크기가 바뀌었습니다", relay_code="SIZE_CHANGED")
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status
        except (OSError, http.client.HTTPException) as exc:
            raise self._transport_error(exc, "업로드") from None
        finally:
            conn.close()
        if not 200 <= status < 300:
            raise self._error_from(status, raw)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HpcGatewayError("PARSE_FAILED", "relay 응답 JSON 형식 오류", http_status=status, transport=True) from None

    # ---- 다운로드(스트리밍) ----
    def download_to(self, path_rel: str, max_bytes: int, fh: BinaryIO,
                    on_chunk: Callable[[int], None] | None = None) -> tuple[int, str, str | None, int | None]:
        """`GET /files` 본문을 fh에 쓴다. 반환 (받은 크기, 계산 sha256, 헤더 X-Content-SHA256, 헤더 Content-Length)."""
        conn = self._conn(self.transfer_timeout_s)
        try:
            conn.request("GET", self.url("/files", {"path": path_rel, "max_bytes": int(max_bytes)}), headers=self._headers())
            resp = conn.getresponse()
            if not 200 <= resp.status < 300:
                raise self._error_from(resp.status, resp.read(65536))
            want_sha = (resp.getheader("X-Content-SHA256") or "").strip().lower() or None
            cl = resp.getheader("Content-Length")
            want_len = int(cl) if cl and cl.isdigit() else None
            if want_len is not None and want_len > max_bytes:
                raise HpcGatewayError("SUBMIT_FAILED", "내려받을 파일이 상한을 넘습니다", relay_code="TOO_LARGE")
            h = hashlib.sha256()
            got = 0
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                got += len(chunk)
                if got > max_bytes:
                    raise HpcGatewayError("SUBMIT_FAILED", "내려받는 파일이 상한을 넘습니다", relay_code="TOO_LARGE")
                h.update(chunk)
                fh.write(chunk)
                if on_chunk is not None:
                    on_chunk(len(chunk))
        except (OSError, http.client.HTTPException) as exc:
            raise self._transport_error(exc, "다운로드") from None
        finally:
            conn.close()
        return got, h.hexdigest(), want_sha, want_len
