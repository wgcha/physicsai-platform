"""④ 파라미터 세트 자동 구성(phase3 §13 S8, D3-47): 프로젝트 폴더 1개를 읽기만 하며 tpl·CAD·조립 폴더·파라미터를 찾는다.

원본 관례(읽기 전용 참고, 저장소 복사 금지):
- tpl: 원본 ①-1 GUI(`1_gui_create_tpl_file.py:347-357`)가 작업 폴더에 `simlab_parametered_mesh.tpl`을 만들고, 그 옆에 빈 틀
  `TEMAPLATE_simlab_parametered_mesh.tpl`(예시 parameter 줄·절대 CAD 경로)을 둔다 → 이름이 같은 것 우선, `TEMAPLATE_`/`TEMPLATE_` 마지막.
  `{parameter(var_i, "<이름>", <nominal>, <min>, <max>)}`(`1_create_tpl_file.py:144-152`)에서 파라미터를 만든다.
- CAD: tpl의 `dir_file_prt = r"./<CAD>"`(`1_create_tpl_file.py:135-139`, SimLab cwd 상대) 파일명. tpl 폴더 우선.
- 조립 폴더: 원본 `RADIOSS_ASSEM_DIR`("Radioss 입력 폴더", `1_gui_physicsai_opti.py:87`) — starter `*_0000.rad`(eps_mesh 제외)
  정확히 1개(GUI :427-445). SimLab 메시 사본(`EPS_mesh_0000.rad`)·`RENUM_INIT.csv`가 함께 있으면 우선, 이름에 radioss·assem이 있으면 다음.
- HyperStudy run 폴더(`train_data.result_run_dir_regex`, 원본 `approaches/*/run__N`)는 run마다 starter가 있어 건너뛴다.

탐색: 링크·junction·숨김·`_backup`·`_platform`(대소문자 무시)·Study 산출 폴더(`04_params` 등) 제외, 깊이·항목 수 상한
(넘으면 truncated), 파일 내용은 tpl만(크기 상한).
등록 복사(D3-50): 각 원본을 복사 직전에 다시 검사(경로 요소 링크·junction 없음, realpath가 프로젝트 폴더 안)하고
열린 핸들 기준으로 복사(O_NOFOLLOW + 연 파일과 경로의 (st_dev, st_ino) 일치) — 검사 뒤 링크로 바뀌면 거부.
300줄 분할(R-B): 폴더 탐색·후보 찾기는 `param_discover_scan`, 자동 구성은 `param_discover_pick`(여기서 재노출).
후보 선택 검증·등록 복사(열린 핸들 기준, `_O_NOFOLLOW`)는 이 파일.
"""

from __future__ import annotations

import io
import os
import re
import stat
from typing import Any

from ..errors import DomainError
from ..fileutil import copy_stream, write_json
from ..naming import TPL_NAME
from ..paths import PathError, is_link_or_reparse, is_under, real
from .prepared_input import is_mesh_file
from .param_discover_scan import (  # noqa: F401 - 기존 경로 재노출
    PARAM_FULL_RE,
    ROOT_REL,
    MESH_ONLY_NOTE,
    Scan,
    TplInfo,
    _rel,
    _abs,
    study_output_dir,
    scan_tree,
    cad_ref_of,
    _cad_name,
    find_tpls,
    find_cads,
    find_assems,
    _pick,
)
from .param_discover_pick import Discovery, discover  # noqa: F401 - 기존 경로 재노출


# ---------------------------------------------------------------------------------------------------------------------
# 등록: 고른 후보를 §15.4 폴더 구조로 모은다(원본 위치는 읽기만). 이후 검증·정규화는 기존 validate_folder·write_normalized.
# ---------------------------------------------------------------------------------------------------------------------


def resolve_choice(d: Discovery, choice: dict[str, str | None]) -> tuple[TplInfo | None, str | None, dict[str, Any] | None,
                                                                         list[dict[str, Any]]]:
    """(tpl, CAD, 조립 폴더|None, problems). 조립 폴더 None + problems 없음 = mesh_only(후보 0개 또는 명시적 null)."""
    probs: list[dict[str, Any]] = []
    tpl = d.selected_tpl
    cad = _pick(d.cad, choice.get("cad"))
    rels = [a["rel"] for a in d.assem]
    # phase3 §14.4: radioss_assem을 명시적 null로 주면 메시 단독(mesh_only) — 후보가 있어도 쓰지 않는다
    mesh_only = "radioss_assem" in choice and choice["radioss_assem"] is None
    arel = None if mesh_only else _pick(rels, choice.get("radioss_assem"))
    assem = next((a for a in d.assem if a["rel"] == arel), None)
    for key, val, cands in (("tpl", tpl, d.tpls), ("cad", cad, d.cad), ("radioss_assem", assem, d.assem)):
        given = choice.get(key)
        if key == "tpl" and given is not None:
            continue  # 고른 tpl이 목록에 없으면 discover가 CHOICE_INVALID를 이미 넣었다
        if key == "radioss_assem" and mesh_only:
            continue
        if val is None and (cands or given is not None):
            probs.append({"code": "CHOICE_INVALID" if given is not None else "CHOICE_REQUIRED",
                          "message": f"{key} 후보 {len(cands)}개 중 하나를 고르세요" if given is None
                          else f"고른 {key}({given})가 찾은 목록에 없습니다"})
    return tpl, cad, assem, probs


_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_BOM = b"\xef\xbb\xbf"


def _recheck(root: str, root_real: str, rel: str) -> str:
    """복사 직전 재검사: 프로젝트 폴더부터 rel까지 각 요소가 링크·junction이 아니고 realpath가 프로젝트 폴더 안."""
    if is_link_or_reparse(root):
        raise PathError("PATH_UNSAFE", "프로젝트 폴더가 링크·junction으로 바뀌었습니다", path=root)
    cur = root
    for part in [] if rel == ROOT_REL else rel.split("/"):
        cur = os.path.join(cur, part)
        if is_link_or_reparse(cur):
            raise PathError("PATH_UNSAFE", f"복사할 원본이 링크·junction입니다: {rel}", path=cur)
    if not is_under(real(cur), root_real):
        raise PathError("PATH_UNSAFE", f"복사할 원본이 프로젝트 폴더 밖을 가리킵니다: {rel}", path=cur)
    return cur


def _changed(rel: str) -> DomainError:
    return DomainError("SOURCE_CHANGED", f"복사하는 동안 원본이 바뀌었습니다(링크 교체 등) — 다시 시도하세요: {rel}", status=409)


def open_source(root: str, root_real: str, rel: str) -> Any:
    """원본 파일을 검사 후 열어 바이너리 핸들을 돌려준다. 이후 복사는 이 핸들로만(경로를 다시 열지 않음).

    POSIX: O_NOFOLLOW(마지막 요소가 링크면 열기 실패). Windows(O_NOFOLLOW 없음): 연 핸들의 (st_dev, st_ino)가
    열기 전 lstat과 같아야 한다 — 그 사이 링크·junction으로 바뀌면 다른 파일이 열려 거부된다. 연 뒤 realpath도 다시 본다.
    """
    p = _recheck(root, root_real, rel)
    try:
        before = os.lstat(p)
    except OSError as exc:
        raise _changed(rel) from exc
    if not stat.S_ISREG(before.st_mode):
        raise PathError("PATH_UNSAFE", f"복사할 원본이 일반 파일이 아닙니다: {rel}", path=p)
    try:
        fd = os.open(p, os.O_RDONLY | _O_NOFOLLOW | _O_BINARY)
    except OSError as exc:  # ELOOP 등: 검사 뒤 링크로 바뀜
        raise _changed(rel) from exc
    try:
        st = os.fstat(fd)
        # Windows st_dev(볼륨 일련번호)는 조회 방식(lstat 빠른 경로·fstat)마다 폭이 달라 파일 ID(st_ino)만 비교
        same = st.st_ino == before.st_ino and (os.name == "nt" or st.st_dev == before.st_dev)
        if not stat.S_ISREG(st.st_mode) or not same:
            raise _changed(rel)
        _recheck(root, root_real, rel)
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, "rb")


def _copy_src(root: str, root_real: str, rel: str, dst: str) -> int:
    with open_source(root, root_real, rel) as fi:
        return copy_stream(fi, dst)


def rewrite_tpl_bytes(raw: bytes, prt_regex: str, cad_name: str) -> bytes:
    """원본 바이트 기준으로 첫 `dir_file_prt` 일치 줄만 `dir_file_prt = r"./<CAD>"`로 바꾼다. BOM·CRLF·나머지 바이트 유지."""
    bom = _BOM if raw.startswith(_BOM) else b""
    lines = raw[len(bom):].decode("utf-8").split("\n")  # '\r'은 줄 내용 끝에 남아 그대로 돌아간다
    rx = re.compile(prt_regex)
    for i, line in enumerate(lines):
        if rx.search(line):
            lines[i] = rx.sub(lambda _m: f'dir_file_prt = r"./{cad_name}"', line, count=1)
            break
    return bom + "\n".join(lines).encode("utf-8")


def assem_files(adir: str, renum_csv_name: str) -> list[str]:
    """조립 폴더에서 등록에 복사할 파일 이름(.rad·.inc·RENUM csv, eps_mesh·링크 제외). copy_sources·planned_bytes 공통."""
    renum = renum_csv_name.casefold()
    out: list[str] = []
    for n in sorted(os.listdir(adir)):
        low = n.casefold()
        if is_mesh_file(n) or not (low.endswith((".rad", ".inc")) or low == renum):
            continue
        p = os.path.join(adir, n)
        if is_link_or_reparse(p) or not os.path.isfile(p):
            continue
        out.append(n)
    return out


def copy_sources(d: Discovery, tpl: TplInfo, cad_rel: str, assem: dict[str, Any] | None, dst: str, settings: Any) -> int:
    """§15.4 폴더 구조로 dst에 모은다. 복사한 바이트 수. 읽기만(원본 위치). 원본마다 복사 직전 재검사·핸들 기준 복사.
    assem None = mesh_only(radioss_assem/ 없음)."""
    root = d.root
    root_real = real(root)
    pr, td = settings.predict, settings.train_data
    cad_name = cad_rel.split("/")[-1]
    total = 0
    # tpl: CAD 경로가 ./<CAD>가 아니면 원본 update_parameter_file(:135-139)처럼 ./<CAD 파일명>으로 바꿔 쓴다
    if tpl.cad_ref is not None and (not tpl.cad_ref.startswith("./") or _cad_name(tpl.cad_ref) != cad_name):
        with open_source(root, root_real, tpl.rel) as fi:
            raw = fi.read()
        try:
            data = rewrite_tpl_bytes(raw, td.tpl_prt_regex, cad_name)
        except UnicodeDecodeError as exc:
            raise _changed(tpl.rel) from exc
        total += copy_stream(io.BytesIO(data), os.path.join(dst, TPL_NAME))
    else:
        total += _copy_src(root, root_real, tpl.rel, os.path.join(dst, TPL_NAME))
    total += _copy_src(root, root_real, cad_rel, os.path.join(dst, "cad", cad_name))
    if d.parameters_source == "file" and d.parameters_file:
        total += _copy_src(root, root_real, d.parameters_file,
                           os.path.join(dst, d.parameters_file.split("/")[-1].lower()))
    else:
        write_json(os.path.join(dst, "parameters.json"),
                   {"schema_version": 1, "unit_system": "mm-ton-s", "parameters": d.parameters})
    for rel, name in ((d.samples, "samples.csv"), (d.responses, "responses.json")):
        if rel:
            total += _copy_src(root, root_real, rel, os.path.join(dst, name))
    if assem is None:
        return total
    arel = assem["rel"]
    adir = _recheck(root, root_real, arel)  # 조립 폴더 자체도 listdir 직전에 다시 본다
    for n in assem_files(adir, pr.renum_csv_name):
        total += _copy_src(root, root_real, _rel(arel, n), os.path.join(dst, "radioss_assem", n))
    return total


def planned_bytes(d: Discovery, tpl: TplInfo, cad_rel: str, assem: dict[str, Any] | None, settings: Any) -> int:
    """복사 전 총량 추정(상한 검사용). 조립 폴더 파일 판정은 copy_sources와 같은 assem_files. assem None = mesh_only."""
    root = d.root
    files = [_abs(root, tpl.rel), _abs(root, cad_rel)]
    files += [_abs(root, r) for r in (d.parameters_file, d.samples, d.responses) if r]
    if assem is not None:
        adir = _abs(root, assem["rel"])
        files += [os.path.join(adir, n) for n in assem_files(adir, settings.predict.renum_csv_name)]
    total = 0
    for f in files:
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    return total
