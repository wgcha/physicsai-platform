"""SCX 드라이브 경로·이름 규칙(phase3 §16.3). 순수 함수 — 네트워크·파일시스템 없음.

- 드라이브 경로는 모두 **공용 계정 홈 기준 상대 경로**(어댑터 `drive_root="~"` 관례, relay API 경로): `/` 구분, 앞 `/`·`~` 없음.
- 설정 `hpc.scx.drive_base`는 `"~"`(= 홈) 또는 `"~/<상대>"`만 → 내부 기준 `""` 또는 `<상대>`.
- 프로젝트 = Study 폴더 이름 정규화, 잡 폴더 = `01_D-<NNN>_<run_key>_<ts>` | `04_V-<NNN>_<ts>`, 이미 있으면 `_2`…`_9`.
- SPDM 마스터 루트(relay `/health`의 `forbidden_prefixes`)와 같거나 그 안이면 거부(예외 설정 없음).
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "SEGMENT_RE", "MAX_REL_LEN", "MAX_SUFFIX", "WINDOWS_RESERVED",
    "sanitize_project", "fmt_no", "train_job_name", "verify_job_name", "with_suffix",
    "drive_base_rel", "join_rel", "rel_problem", "file_name_problem", "forbidden_reason", "display_path",
]

# 프로젝트·잡 폴더 구간(§16.3 검사)
SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
MAX_REL_LEN = 1024
MAX_SUFFIX = 9
WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_NON_SAFE = re.compile(r"[^A-Za-z0-9_\-]")
_MULTI_US = re.compile(r"_+")
_TS_RE = re.compile(r"^\d{8}T\d{6}$")
_RUN_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def sanitize_project(folder_name: str) -> str:
    """Study 폴더 이름 → 드라이브 프로젝트 폴더 이름(§16.3).

    NFC → `[A-Za-z0-9_-]` 밖 문자는 `_` → `_` 연속은 하나로 → 앞뒤 `_`·`-` 제거 → 64자 자름 → 비면 `study`.
    Windows 예약 이름(대소문자 무시)이면 앞에 `s_`.
    """
    s = unicodedata.normalize("NFC", folder_name or "")
    s = _NON_SAFE.sub("_", s)
    s = _MULTI_US.sub("_", s)
    s = s.strip("_-")
    s = s[:64].strip("_-")
    if not s:
        s = "study"
    if s.upper() in WINDOWS_RESERVED:
        s = "s_" + s
    return s


def fmt_no(n: int) -> str:
    """번호 3자리 0 채움(1000 이상은 그대로)."""
    if n < 1:
        raise ValueError("번호는 1 이상")
    return f"{n:03d}"


def train_job_name(doe_no: int, run_key: str, ts: str) -> str:
    """① 잡 폴더 이름 `01_D-<NNN>_<run_key>_<ts>`."""
    if not _RUN_KEY_RE.match(run_key or ""):
        raise ValueError("run_key 형식 오류")
    if not _TS_RE.match(ts or ""):
        raise ValueError("시각 형식 오류(%Y%m%dT%H%M%S)")
    name = f"01_D-{fmt_no(doe_no)}_{run_key}_{ts}"
    if not SEGMENT_RE.match(name):
        raise ValueError("잡 폴더 이름 형식 오류")
    return name


def verify_job_name(v_no: int, ts: str) -> str:
    """④ 잡 폴더 이름 `04_V-<NNN>_<ts>`."""
    if not _TS_RE.match(ts or ""):
        raise ValueError("시각 형식 오류(%Y%m%dT%H%M%S)")
    return f"04_V-{fmt_no(v_no)}_{ts}"


def with_suffix(name: str, n: int) -> str:
    """같은 이름 폴더가 있을 때 `_2`…`_9`(n=1이면 그대로)."""
    if n <= 1:
        return name
    if n > MAX_SUFFIX:
        raise ValueError("접미 번호 상한 초과")
    return f"{name}_{n}"


def _segments_problem(rel: str) -> str | None:
    if _CTRL.search(rel):
        return "제어문자"
    if "\\" in rel:
        return "'\\' 구분자"
    if rel.startswith(("/", "~")):
        return "'/'·'~'로 시작"
    parts = rel.split("/")
    for p in parts:
        if p in ("", ".", ".."):
            return "빈 구간·'.'·'..'"
        if len(p) > 255:
            return "구간이 255자를 넘음"
    if len(rel) > MAX_REL_LEN:
        return f"전체 길이가 {MAX_REL_LEN}자를 넘음"
    return None


def drive_base_rel(drive_base: str) -> str:
    """설정 `drive_base`(`"~"` | `"~/<상대>"`) → 내부 기준(`""` | `<상대>`). 형식 오류면 ValueError."""
    if not isinstance(drive_base, str):
        raise ValueError("drive_base는 문자열")
    v = unicodedata.normalize("NFC", drive_base)
    if v == "~":
        return ""
    if not v.startswith("~/"):
        raise ValueError("drive_base는 \"~\" 또는 \"~/<상대 경로>\"")
    rel = v[2:].rstrip("/")
    why = _segments_problem(rel) if rel else "빈 상대 경로"
    if why:
        raise ValueError(f"drive_base 형식 오류: {why}")
    if rel.split("/")[0].startswith("."):
        raise ValueError("drive_base 첫 구간은 '.'로 시작할 수 없습니다")
    return rel


def join_rel(*parts: str) -> str:
    """빈 구간을 건너뛰고 `/`로 잇는다(기준이 홈이면 `""`)."""
    return "/".join(p.strip("/") for p in parts if p and p.strip("/"))


def rel_problem(rel: str, *, segment_check_from: int = 0) -> str | None:
    """드라이브 상대 경로 검사. `segment_check_from` 번째 구간부터 SEGMENT_RE(프로젝트·잡 폴더)를 적용한다."""
    if not rel:
        return "빈 경로"
    rel = unicodedata.normalize("NFC", rel)
    why = _segments_problem(rel)
    if why:
        return why
    parts = rel.split("/")
    if parts[0].startswith("."):
        return "첫 구간이 '.'로 시작"
    for p in parts[segment_check_from:]:
        if not SEGMENT_RE.match(p):
            return f"폴더 이름 형식 오류: {p}"
    return None


def file_name_problem(name: str) -> str | None:
    """올릴 파일 이름 검사(§16.4 2번): 제어문자·`/\\:` 금지, 1~255자, `.`·`..` 금지."""
    if not name or len(name) > 255:
        return "파일 이름 길이(1~255자)"
    if _CTRL.search(name) or any(c in name for c in "/\\:"):
        return "제어문자·'/'·'\\'·':'"
    if name in (".", ".."):
        return "'.'·'..'"
    return None


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def _prefix_rel(raw: str, home_display: str) -> str:
    """금지 접두 표기(상대 `SPDM`·`~/SPDM`·절대 `<home_display>/SPDM`) → 홈 기준 상대(대소문자 접기·NFC)."""
    v = _fold(str(raw).strip()).replace("\\", "/")
    home = _fold(home_display or "").rstrip("/")
    if home and (v == home or v.startswith(home + "/")):
        v = v[len(home):]
    elif v.startswith("~"):
        v = v[1:]
    return v.strip("/")


def forbidden_reason(rel: str, forbidden_prefixes: list[str] | tuple[str, ...], base: str = "",
                     home_display: str = "") -> str | None:
    """SPDM 루트 보호(§16.3, 대소문자 무시·NFC): `rel`이 금지 접두 S와 같거나 그 안이면, 또는 `rel`의 프로젝트 폴더
    (`base` 바로 아래 첫 구간까지)가 S 자신이거나 S의 상위 폴더면(예 S=`SPDM`·프로젝트 `SPDM`, S=`Projects/SPDM`·프로젝트 `Projects`) 사유."""
    p = _fold(rel.strip("/"))
    b = _fold(base.strip("/"))
    tail = p[len(b) + 1:] if b and p.startswith(b + "/") else p
    project = join_rel(b, tail.split("/")[0]) if tail else b
    for raw in forbidden_prefixes or ():
        s = _prefix_rel(raw, home_display)
        if not s:
            return "SPDM 루트가 홈 전체입니다"
        if p == s or p.startswith(s + "/"):
            return "SPDM 루트 안"
        if project and (project == s or s.startswith(project + "/")):
            return "프로젝트 폴더가 SPDM 루트이거나 그 상위 폴더"
    return None


def display_path(home_display: str, rel: str) -> str:
    """표시 전용 경로(`<home_display>/<rel>`). 계산에 쓰지 않는다."""
    base = (home_display or "").rstrip("/")
    return f"{base}/{rel}" if rel else base
