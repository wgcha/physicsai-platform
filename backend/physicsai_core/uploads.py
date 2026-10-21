"""브라우저 분할 업로드의 이름·경로·파일 쓰기 규칙(upload-report.md §3·§5, esl `core/uploads.py` 이식). DB·HTTP 없음.

- 업로드 폴더: `<ai_root>/<upload_root>/<사용자>/<UTC yyyymmdd-HHMMSS>_<이름>/<rel…>` — 기존 폴더·파일 덮어쓰기 없음.
- 파일 `rel`: `/` 구분 상대경로(선택 폴더 기준). 성분마다 physicsai 이름 규칙(`name_unsafe_chars`·`path_component_problem`) +
  Windows 예약 장치명·`* ? \\`, 최종 절대경로 ≤ MAX_PATH_LEN, 첫 성분 `_backup`·`_platform`·`.`으로 시작 거부.
- 허용 파일: purpose별 glob ∪ `upload.extra_patterns`(파일 이름에만, 대소문자 무시) — 항상 거부(`*.pscfg`·`*.psdata`·실행/스크립트·`*.part`)가 먼저.
- 쓰기 대상은 업로드 폴더 아래만: 상위 성분 링크·reparse 거부, realpath가 폴더 밖이면 PATH_UNSAFE, `.part` 새 파일은 O_EXCL.
- 취소·낡음·sha256 불일치는 지우지 않고 `<upload_root>/_backup/<사용자>/…`로 옮긴다(삭제 함수 호출 0 — V-UP-7).
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import os
import re
import shutil
import stat
from typing import Any

from .config import ALWAYS_DENIED, PURPOSE_MODES, UPLOAD_PURPOSES, is_abs_path_str
from .config.schema_upload import RESERVED_FIRST, is_always_denied_pattern
from .errors import DomainError, StepFailure
from .path_links import is_link_or_reparse, is_under, real, windows_reserved_name
from .path_names import name_unsafe_chars, path_component_problem
from .paths import BACKUP_DIR, MAX_PATH_LEN, assert_writable

PART_SUFFIX = ".part"
MAX_REL = 400
MAX_SEG = 255
_FS_FORBIDDEN = frozenset('*?\\')
_NAME_REPLACE = re.compile(r"[^0-9A-Za-z가-힣_.\-]+")
DIR_SUFFIX_MARGIN = 4  # 폴더 이름 뒤 `_2`~`_999`


def _unprocessable(code: str, message: str, **extra: Any) -> DomainError:
    return DomainError(code, message, status=422, **extra)


def _bad(msg: str, **extra: Any) -> DomainError:
    return _unprocessable("UPLOAD_NAME_INVALID", msg, **extra)


def _writable(path: str) -> None:
    try:
        assert_writable(path)
    except StepFailure as exc:  # SPDM 보호 루트·링크 — 이중 방어(§5)
        raise _unprocessable("PATH_UNSAFE", exc.message) from exc


# ---------------------------------------------------------------- 위치
def upload_root_path(settings: Any) -> str | None:
    """`<ai_root>/<storage.upload_root>` 절대경로(설정 null이면 None)."""
    ur = settings.storage.upload_root
    if not ur:
        return None
    if is_abs_path_str(ur):
        return os.path.normpath(ur)
    return os.path.normpath(os.path.join(settings.storage.ai_root, *ur.replace("\\", "/").split("/")))


def dir_rel_of(settings: Any, abs_dir: str) -> str:
    """AI 루트 기준 상대경로('/' 구분) — DB에는 이것만 저장한다."""
    return os.path.relpath(os.path.normpath(abs_dir), os.path.normpath(settings.storage.ai_root)).replace(os.sep, "/")


def abs_dir_of(settings: Any, dir_rel: str) -> str:
    return os.path.normpath(os.path.join(settings.storage.ai_root, *dir_rel.split("/")))


# ---------------------------------------------------------------- 패턴
def mode_of(purpose: str) -> str:
    return PURPOSE_MODES[purpose]


def _exts_to_globs(exts: list[str]) -> list[str]:
    return ["*" + e if e.startswith(".") else "*." + e for e in exts]


def _default_patterns(s: Any, purpose: str, engine: str | None) -> list[str]:
    docs = ["*.csv", "*.json", "*.txt"]
    if purpose == "CAD_FILE":  # GE-C15: inspect와 같은 기준 — native는 STEP, 그 밖은 기존 CAD 확장자
        return _exts_to_globs(s.geometry.step_extensions if engine == "native" else s.train_data.cad_extensions)
    if purpose == "RADIOSS_ASSEM" or purpose == "FEM_ASSEMBLY":
        return ["*.rad", "*.inc", "*.k", "*.key", "*.csv", "*.txt", "*.json", "*.dat"]
    if purpose == "RESULT_FOLDER":
        return [*s.hpc.transfer.collect_patterns, *docs]
    if purpose == "CURATION_INPUT":
        return ["*.h3d", "*T01", *docs]
    if purpose == "DATASET_INPUT":
        return ["*.h3d", *docs]
    if purpose == "MODEL_FOLDER":  # `*.pscfg` 제외(D3-43: pscfg 없이 등록 가능)
        return ["*.psmdl", *s.training_log.log_globs, "*.json", "*.csv"]
    if purpose == "PARAM_SET":
        return ["*.tpl", "*.prt", "*.stp", "*.step", "*.csv", "*.json", "*.txt", "*.rad", "*.inc", "*.k", "*.hm", "*.tcl"]
    if purpose == "PREDICT_INPUT":
        return ["*.rad", "*.inc", "*.hm", "*.k", "*.csv", "*.json", "*.txt"]
    raise KeyError(purpose)


def _purpose_base(s: Any, purpose: str, engine: str | None) -> list[str]:
    ov = s.upload.purposes.get(purpose)
    if ov is not None and ov.patterns:
        return list(ov.patterns)
    if purpose == "DISCOVER":
        return [*_purpose_base(s, "PARAM_SET", engine), *_purpose_base(s, "RADIOSS_ASSEM", engine)]
    if purpose == "FEM_ASSEMBLY":
        return _purpose_base(s, "RADIOSS_ASSEM", engine)
    return _default_patterns(s, purpose, engine)


def purpose_patterns(settings: Any, purpose: str, engine: str | None = None) -> list[str]:
    """purpose 허용 패턴 ∪ 전역 extra_patterns, 항상 거부 패턴 제외(소문자·중복 제거)."""
    if purpose not in UPLOAD_PURPOSES:
        raise DomainError("UPLOAD_PURPOSE_INVALID", f"업로드할 수 없는 용도입니다: {purpose}", status=422)
    out: list[str] = []
    for p in [*_purpose_base(settings, purpose, engine), *settings.upload.extra_patterns]:
        q = p.strip().lower()
        if q and not is_always_denied_pattern(q) and q not in out:
            out.append(q)
    return out


def matches_any(name: str, patterns: list[str]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, p.lower()) for p in patterns)


def denied_reason(name: str) -> tuple[str, str] | None:
    """항상 거부 이름이면 (코드, 문구)."""
    low = name.lower()
    if fnmatch.fnmatchcase(low, "*.pscfg"):
        return "UPLOAD_EXT_NOT_ALLOWED", "pscfg(pickle)는 올릴 수 없습니다 — 모델은 psmdl만으로 등록됩니다"
    if any(fnmatch.fnmatchcase(low, p) for p in ALWAYS_DENIED):
        return "UPLOAD_EXT_NOT_ALLOWED", f"올릴 수 없는 파일 종류입니다(항상 거부 목록): {name}"
    return None


def config_purposes(settings: Any) -> dict[str, dict[str, Any]]:
    """`GET /uploads/config`의 purposes. CAD_FILE만 engine별 패턴을 `engine_patterns`로 함께 준다."""
    out: dict[str, dict[str, Any]] = {}
    for p in UPLOAD_PURPOSES:
        out[p] = {"patterns": purpose_patterns(settings, p), "mode": mode_of(p), "engine_patterns": None}
    out["CAD_FILE"]["engine_patterns"] = {e: purpose_patterns(settings, "CAD_FILE", e) for e in ("native", "altair")}
    return out


# ---------------------------------------------------------------- 이름 규칙
def check_segment(seg: str, what: str) -> None:
    if not seg:
        raise _bad(f"{what}: 빈 이름(연속 '/')은 쓸 수 없습니다", rel=what)
    if seg in (".", ".."):
        raise _bad(f"{what}: '.'·'..' 은 쓸 수 없습니다", rel=what)
    if len(seg) > MAX_SEG:
        raise _bad(f"{what}: 이름이 너무 깁니다(성분 {MAX_SEG}자 이하)", rel=what)
    why = name_unsafe_chars(seg)
    if why:
        raise _bad(f"{what}: 이름에 쓸 수 없는 문자({why})가 있습니다 — 이름을 바꿔 다시 선택하세요", rel=what)
    if _FS_FORBIDDEN.intersection(seg):
        raise _bad(f"{what}: 이름에 * ? \\ 는 쓸 수 없습니다", rel=what)
    why = path_component_problem(seg, windows=False)
    if why:
        raise _bad(f"{what}: 이름에 {why}을 쓸 수 없습니다", rel=what)
    if windows_reserved_name(seg):
        raise _bad(f"{what}: Windows 예약 이름·끝 점/공백은 쓸 수 없습니다", rel=what)


def check_rel(rel: object, patterns: list[str]) -> list[str]:
    """파일 상대경로 검사 → 성분 목록. 이름 규칙 → 항상 거부 → purpose 패턴 순."""
    if not isinstance(rel, str) or not rel or len(rel) > MAX_REL:
        raise _bad("파일 경로가 비었거나 너무 깁니다", rel=rel if isinstance(rel, str) else None)
    if rel.startswith("/") or "\\" in rel or re.match(r"^[A-Za-z]:", rel):
        raise _bad(f"절대경로나 '\\' 구분자는 쓸 수 없습니다(선택 폴더 기준 상대경로만): {rel}", rel=rel)
    segs = rel.split("/")
    for s in segs:
        check_segment(s, rel)
    first = segs[0]
    if first.casefold() in RESERVED_FIRST or first.startswith("."):
        raise _bad(f"경로가 _backup·_platform·'.'으로 시작할 수 없습니다: {rel}", rel=rel)
    name = segs[-1]
    den = denied_reason(name)
    if den:
        raise _unprocessable(den[0], f"{den[1]}", rel=rel)
    if not matches_any(name, patterns):
        raise _unprocessable("UPLOAD_EXT_NOT_ALLOWED", f"이 용도에서 허용되지 않는 파일입니다: {rel}", rel=rel, allowed=patterns)
    return segs


def check_final_length(upload_dir: str, segs: list[str], *, margin: int = 0) -> None:
    """최종 절대경로가 MAX_PATH_LEN 이하(이후 check_user_path 통과 보장)."""
    n = len(os.path.join(upload_dir, *segs)) + margin
    if n > MAX_PATH_LEN:
        raise _bad(f"업로드 폴더 경로를 포함한 전체 경로가 너무 깁니다({n}자 > {MAX_PATH_LEN}자): {'/'.join(segs)}",
                   rel="/".join(segs))


def check_shape(purpose: str, rels: list[str]) -> None:
    """모양 검사: 파일 1개 purpose(CAD)는 폴더 성분 없는 파일 정확히 1개."""
    if mode_of(purpose) == "file" and (len(rels) != 1 or "/" in rels[0]):
        raise _unprocessable("UPLOAD_SHAPE_INVALID", "이 용도는 파일 1개만 올릴 수 있습니다(폴더·여러 파일 불가)")


def result_rel(purpose: str, rels: list[str]) -> str | None:
    """경로 칸에 채울 값이 파일이면 그 rel, 폴더면 None."""
    mode = mode_of(purpose)
    if mode == "file":
        return rels[0] if rels else None
    if mode == "dir_or_file" and len(rels) == 1 and "/" not in rels[0]:
        return rels[0]
    return None


def check_no_conflicts(existing: list[str], new: list[str]) -> None:
    """대소문자 무시 중복·파일/폴더 이름 겹침(409 UPLOAD_FILE_DUPLICATE)."""
    files = {r.casefold() for r in existing}
    dirs: set[str] = set()
    for r in existing:
        parts = r.casefold().split("/")
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
    for r in new:
        k = r.casefold()
        parts = k.split("/")
        prefixes = ["/".join(parts[:i]) for i in range(1, len(parts))]
        if k in files:
            raise DomainError("UPLOAD_FILE_DUPLICATE", f"같은 경로의 파일이 이미 있습니다(대소문자 무시): {r}", status=409, rel=r)
        if k in dirs or any(p in files for p in prefixes):
            raise DomainError("UPLOAD_FILE_DUPLICATE", f"파일과 폴더 이름이 겹칩니다: {r}", status=409, rel=r)
        files.add(k)
        dirs.update(prefixes)


def safe_name(name: object, what: str = "업로드 이름") -> str:
    """폴더 이름 성분으로 쓸 이름: 경로 구분자·'..'·제어문자·예약어 거부, 나머지 특수문자는 '_'(최대 64자)."""
    if not isinstance(name, str) or not name.strip():
        raise _bad(f"{what}이 비었습니다")
    n = name.strip()
    if "/" in n or "\\" in n or ".." in n or re.search(r"[\x00-\x1f\x7f]", n):
        raise _bad(f"{what}에 경로 구분자·'..'·제어문자를 쓸 수 없습니다")
    if windows_reserved_name(n.split(".", 1)[0].strip()):
        raise _bad(f"{what}에 Windows 예약 이름은 쓸 수 없습니다")
    return _NAME_REPLACE.sub("_", n)[:64].strip("._") or "upload"


def user_segment(username: str, user_id: str) -> str:
    try:
        seg = safe_name(username, "사용자 이름")
    except DomainError:  # 이상한 사용자 이름이면 id로
        seg = _NAME_REPLACE.sub("_", user_id)[:64].strip("._") or "user"
    return seg


def utc_stamp(now: _dt.datetime | None = None) -> str:
    return (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y%m%d-%H%M%S")


def projected_dir(upload_root: str, user_seg: str, name_seg: str, stamp: str) -> str:
    return os.path.join(upload_root, user_seg, f"{stamp}_{name_seg}")


# ---------------------------------------------------------------- 파일시스템
def _no_links_below(root: str, path: str) -> None:
    """root 아래 path까지 이미 있는 성분 중 링크(symlink·junction)가 있으면 거부, realpath가 root 밖이면 거부."""
    rootn = os.path.normpath(root)
    rel = os.path.relpath(os.path.normpath(path), rootn)
    if rel == os.curdir:
        return
    if rel.startswith(os.pardir):
        raise _unprocessable("PATH_UNSAFE", "업로드 폴더 밖 경로입니다")
    cur = rootn
    for comp in rel.split(os.sep):
        cur = os.path.join(cur, comp)
        if is_link_or_reparse(cur):
            raise _unprocessable("PATH_UNSAFE", "링크가 포함된 경로에는 쓰지 않습니다")
    if not is_under(real(path), real(rootn)):
        raise _unprocessable("PATH_UNSAFE", "실제 경로가 업로드 폴더 밖입니다")


def check_root(ai_root: str, upload_root: str) -> None:
    """업로드 루트가 AI 루트 안의 실제 폴더(링크 아님)인지."""
    _writable(upload_root)
    _no_links_below(ai_root, upload_root)


def make_upload_dir(ai_root: str, upload_root: str, user_seg: str, name_seg: str, stamp: str) -> str:
    """새 업로드 폴더를 만든다(이미 있으면 _2, _3 … — os.mkdir 원자 생성, 덮어쓰기 없음)."""
    _writable(upload_root)
    os.makedirs(upload_root, exist_ok=True)
    _no_links_below(ai_root, upload_root)
    udir = os.path.join(upload_root, user_seg)
    _no_links_below(upload_root, udir)
    os.makedirs(udir, exist_ok=True)
    _no_links_below(upload_root, udir)
    for i in range(1, 1000):
        d = os.path.join(udir, f"{stamp}_{name_seg}" + ("" if i == 1 else f"_{i}"))
        try:
            os.mkdir(d)
        except FileExistsError:
            continue
        _no_links_below(upload_root, d)
        return d
    raise _unprocessable("UPLOAD_DIR_EXISTS", "업로드 폴더를 만들 수 없습니다(같은 이름이 너무 많음)")


def _check_stat(st: os.stat_result) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise _unprocessable("PATH_UNSAFE", "일반 파일이 아닌 경로에는 쓰지 않습니다")
    if st.st_nlink != 1:
        raise _unprocessable("PATH_UNSAFE", "하드 링크된 파일에는 쓰지 않습니다")


def check_existing_file(path: str, root: str | None = None) -> None:
    """이미 있는 파일: 링크 아님·일반 파일·링크 수 1(하드 링크 거부)·realpath가 root 안."""
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or is_link_or_reparse(path):
        raise _unprocessable("PATH_UNSAFE", "링크 경로에는 쓰지 않습니다")
    _check_stat(st)
    if root is not None and not is_under(real(path), real(root)):
        raise _unprocessable("PATH_UNSAFE", "실제 경로가 업로드 폴더 밖입니다")


def target_path(upload_dir: str, segs: list[str], *, create_parents: bool = False) -> str:
    """업로드 폴더 안 파일 경로(성분 링크·realpath 탈출·경로 길이 거부). create_parents면 상위 폴더를 만든 뒤 다시 검사."""
    check_final_length(upload_dir, segs)
    p = os.path.join(upload_dir, *segs)
    parent = os.path.dirname(p)
    _writable(upload_dir)
    _no_links_below(upload_dir, parent)
    if create_parents:
        os.makedirs(parent, exist_ok=True)
        _no_links_below(upload_dir, parent)
    for q in (p, p + PART_SUFFIX):
        if is_link_or_reparse(q):
            raise _unprocessable("PATH_UNSAFE", "링크 경로에는 쓰지 않습니다")
        if os.path.lexists(q):
            check_existing_file(q, upload_dir)
    return p


def append_chunk(part_path: str, data: bytes, root: str | None = None) -> None:
    """part_path에 이어 쓴다. 새 파일은 O_EXCL로 만들고, 기존 파일은 열린 fd로 일반 파일·링크 수 1을 확인
    (하드 링크로 밖 파일에 쓰기 방지)·root가 주어지면 realpath가 그 안인지 확인."""
    base = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(part_path, base | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        fd = os.open(part_path, base)
        try:
            _check_stat(os.fstat(fd))
            if root is not None and not is_under(real(part_path), real(root)):
                raise _unprocessable("PATH_UNSAFE", "실제 경로가 업로드 폴더 밖입니다")
        except BaseException:
            os.close(fd)
            raise
    try:
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
    finally:
        os.close(fd)


def part_size(part_path: str) -> int:
    try:
        return os.path.getsize(part_path)
    except OSError:
        return 0


# ---------------------------------------------------------------- _backup 이동(삭제 없음)
def backup_dest(upload_root: str, user_seg: str, name: str) -> str:
    base = os.path.join(upload_root, BACKUP_DIR, user_seg)
    os.makedirs(base, exist_ok=True)
    for i in range(1, 1000):
        d = os.path.join(base, name + ("" if i == 1 else f"_{i}"))
        if not os.path.lexists(d):
            return d
    raise _unprocessable("BACKUP_EXISTS", "백업 위치를 정할 수 없습니다")


def move_to_backup(upload_root: str, user_seg: str, src: str, name: str | None = None) -> str | None:
    """src(파일·폴더)를 <upload_root>/_backup/<사용자>/<이름>으로 옮긴다(삭제 없음). 없으면 None."""
    if not os.path.lexists(src):
        return None
    if not is_link_or_reparse(src):
        _writable(src)
    dest = backup_dest(upload_root, user_seg, name or os.path.basename(src))
    shutil.move(src, dest)
    return dest


def free_bytes(path: str) -> int | None:
    """path(또는 가장 가까운 존재하는 상위 폴더)가 있는 드라이브의 여유 바이트. 읽지 못하면 None."""
    p = os.path.normpath(path)
    while p and not os.path.exists(p):
        up = os.path.dirname(p)
        if up == p:
            break
        p = up
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None
