"""SPDM 읽기 전용 접근(phase2 §6.11, §13.3). SPDM 경로를 다루는 코드는 이 모듈 하나뿐이다.

- 공개 함수는 읽기만 한다: check_spdm_path, scan, open_read, probe_roots.
- SPDM 쪽 쓰기 0: 파일 생성·이름 변경·속성 변경·잠금 파일 없음. 하드링크·심볼릭 링크·os.replace·copy2 금지.
- 다른 모듈의 쓰기 헬퍼(paths.backup_existing, fileutil.copy_file 등)는 보호 루트 하위 경로를 받으면 예외
  (paths.register_protected_roots로 등록).
"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from typing import IO

from ..paths import MAX_PATH_LEN, PathError, WINDOWS_RESERVED, is_link_or_reparse, is_under, real

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_NAME_BAD = re.compile(r"[\s&|<>^%!\";,=()\x00-\x1f\x7f]")


def _is_abs(raw: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", raw)) or raw.startswith("\\\\") or raw.startswith("/")


def check_spdm_path(raw: object, roots: Sequence[str]) -> str:
    """SPDM 경로 검사(§13.3). 공백·한글 허용, 제어문자 금지. realpath 후 spdm_roots 하위, 링크·junction 거부.

    실패: PathError(PATH_OUTSIDE_ROOT | PATH_UNSAFE | PATH_NOT_FOUND). 성공: 정규화 절대경로.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise PathError("PATH_UNSAFE", "경로가 비어 있습니다")
    if len(raw) > MAX_PATH_LEN:
        raise PathError("PATH_UNSAFE", f"경로가 너무 깁니다(최대 {MAX_PATH_LEN}자)")
    if _CTRL.search(raw):
        raise PathError("PATH_UNSAFE", "경로에 제어문자를 쓸 수 없습니다")
    if not _is_abs(raw):
        raise PathError("PATH_UNSAFE", "절대경로(드라이브 또는 UNC)를 입력하세요", path=raw)
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts or "." in parts[1:]:
        raise PathError("PATH_UNSAFE", "경로에 '..' 또는 '.'을 쓸 수 없습니다", path=raw)
    norm = os.path.normpath(raw)
    matched = matched_real = None
    for r in roots:
        if not r:
            continue
        rr = real(r)
        for cand in (os.path.normpath(r), rr):
            if is_under(norm, cand):
                matched, matched_real = cand, rr
                break
        if matched:
            break
    if matched is None or matched_real is None:
        raise PathError("PATH_OUTSIDE_ROOT", "SPDM 루트(storage.spdm_roots) 밖의 경로입니다", path=raw)
    rel = os.path.relpath(norm, matched)
    cur = matched
    for part in ([] if rel == "." else rel.split(os.sep)):
        cur = os.path.join(cur, part)
        if not os.path.lexists(cur):
            break
        if is_link_or_reparse(cur):
            raise PathError("PATH_UNSAFE", "심볼릭 링크·junction이 포함된 경로입니다", path=raw)
    if os.path.lexists(norm) and not is_under(real(norm), matched_real):
        raise PathError("PATH_UNSAFE", "링크로 SPDM 루트 밖을 가리키는 경로입니다", path=raw)
    if not os.path.isdir(norm):
        raise PathError("PATH_NOT_FOUND", "폴더가 없습니다", path=raw)
    return norm


def safe_component(name: str) -> str:
    """복사 대상 이름 정리: 공백·cmd 메타문자·제어문자 → '_', Windows 예약 이름은 앞에 '_'."""
    out = _NAME_BAD.sub("_", name)
    stem = out.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED or out != out.rstrip(" ."):
        out = "_" + out.rstrip(" .")
    return out or "_"


@dataclass(frozen=True)
class SpdmFile:
    source: str  # SPDM 절대경로(읽기 전용)
    source_rel: str  # SPDM 기준 원래 상대경로('/')
    dest_rel: str  # 정리된 상대경로('/')
    size: int
    mtime_ns: int
    atime_ns: int
    renamed: bool
    dev: int | None = None  # 스캔 때 lstat (st_dev, st_ino) — 열 때 대조(C17)
    ino: int | None = None


@dataclass(frozen=True)
class ScanResult:
    files: list[SpdmFile]
    total_bytes: int
    renamed_count: int
    h3d_count: int
    t01_count: int
    skipped_links: int


def scan(path: str, patterns: Sequence[str], max_files: int) -> ScanResult:
    """재귀 수집(대소문자 무시 패턴). 링크·reparse 거부, 디렉터리 링크는 따라가지 않는다. 읽기만 한다."""
    files: list[SpdmFile] = []
    used: set[str] = set()
    total = renamed = links = h3d = t01 = 0
    pats = [p.lower() for p in patterns]
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        keep = []
        for d in sorted(dirnames):
            if is_link_or_reparse(os.path.join(dirpath, d)):
                links += 1
            else:
                keep.append(d)
        dirnames[:] = keep
        for fn in sorted(filenames):
            if not any(fnmatch.fnmatchcase(fn.lower(), p) for p in pats):
                continue
            src = os.path.join(dirpath, fn)
            if is_link_or_reparse(src):
                links += 1
                continue
            st = os.lstat(src)
            if not os.path.isfile(src):
                continue
            rel_parts = os.path.relpath(src, path).split(os.sep)
            clean = [safe_component(x) for x in rel_parts]
            dest = "/".join(clean)
            n = 1
            base = dest
            while dest.lower() in used:
                stem, ext = os.path.splitext(base)
                dest = f"{stem}~{n}{ext}"
                n += 1
            used.add(dest.lower())
            was_renamed = dest != "/".join(rel_parts)
            renamed += int(was_renamed)
            files.append(SpdmFile(src, "/".join(rel_parts), dest, st.st_size, st.st_mtime_ns, st.st_atime_ns, was_renamed,
                                  st.st_dev, st.st_ino))
            total += st.st_size
            if fn.lower().endswith(".h3d"):
                h3d += 1
            if fn.endswith("T01"):
                t01 += 1
            if len(files) > max_files:
                raise PathError("INPUT_INVALID", f"가져올 파일이 상한({max_files}개)을 넘습니다")
    return ScanResult(files, total, renamed, h3d, t01, links)


def _same_file(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def open_read(f: SpdmFile) -> IO[bytes]:
    """SPDM 원본을 읽기 전용으로 연다(SI_SCAN~SI_COPY 사이 링크 교체 TOCTOU 방지, 변경 메모 C17).

    1) 상위 폴더 구성요소와 파일 자체가 링크·reparse point가 아닌지 다시 확인(lstat)
    2) O_RDONLY | O_NOFOLLOW(있는 OS)로 연다 — 마지막 구성요소가 링크로 바뀌었으면 여는 단계에서 실패
    3) 연 fd의 fstat와 경로 lstat의 (st_dev, st_ino) 대조, 일반 파일만, 스캔 때 기록한 크기·mtime과 대조
    Windows: O_NOFOLLOW가 없어 1)의 reparse 검사 + 3)의 핸들 정보(파일 인덱스·볼륨 번호) 대조로 대신한다.
    위반 → StepFailure(INPUT_CHANGED). 쓰기·속성 변경 호출 없음.
    """
    from ..errors import StepFailure

    def changed(why: str) -> StepFailure:
        return StepFailure("INPUT_CHANGED", f"스캔 후 SPDM 파일이 바뀌었습니다({why}): {f.source_rel}")

    parts = f.source_rel.split("/")
    base = f.source
    for _ in parts:
        base = os.path.dirname(base)
    cur = base
    for part in parts:
        cur = os.path.join(cur, part)
        if is_link_or_reparse(cur):
            raise changed("링크·reparse point")
    try:
        st_path = os.lstat(f.source)
    except OSError:
        raise changed("파일 없음") from None
    if not stat.S_ISREG(st_path.st_mode):
        raise changed("일반 파일 아님")
    try:
        fd = os.open(f.source, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise changed("열기 실패(링크 교체 가능성)") from None
    try:
        st_fd = os.fstat(fd)
        if not stat.S_ISREG(st_fd.st_mode) or not _same_file(st_fd, st_path):
            raise changed("다른 파일로 교체됨")
        if f.ino is not None and (st_fd.st_dev, st_fd.st_ino) != (f.dev, f.ino):
            raise changed("스캔 후 다른 파일로 교체됨")
        if st_fd.st_size != f.size or st_fd.st_mtime_ns != f.mtime_ns:
            raise changed("크기·수정 시각 변경")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def probe_roots(roots: Sequence[str]) -> list[dict[str, object]]:
    """환경 점검: 각 루트 존재·읽기 가능(os.listdir 1회)."""
    out = []
    for r in roots:
        try:
            n = len(os.listdir(r))
            out.append({"root": r, "ok": True, "entries": n})
        except OSError as exc:
            out.append({"root": r, "ok": False, "error": str(exc)[:200]})
    return out
