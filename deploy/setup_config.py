"""git 폴더 설치(deploy/setup.ps1)의 설정 파일 계획·작성. setup.ps1이 설치 venv의 Python으로 부른다.

  python setup_config.py plan  --inputs <inputs.json> [--out <결과.json>]   계획만 계산해 JSON으로 출력(파일을 바꾸지 않음)
  python setup_config.py write --inputs <inputs.json> [--out <결과.json>]   계획대로 deploy.json·platform.yaml을 쓰고(바뀌는 기존 파일은 먼저 _backup\\<UTC>로 복사)
                                                       AI 루트 폴더를 만든 뒤 설정 검증 결과를 JSON으로 출력

규칙
- 이미 있는 파일은 보존한다: 사용자가 고친 값은 덮어쓰지 않고, 빠진 키(또는 비어 있는 자원·Altair 경로)만 보충한다.
- 새 platform.yaml은 config/platform.example.yaml(주석 유지)에서 만들고 profile prod, storage.ai_root, altair.*(탐색), resources.*(원본 앱 폴더),
  hpc.gateway none, server.port·worker 기본값(예시 값), server.frontend_root(프런트 배치 폴더 — 백엔드가 /physicsai/ 직접 서빙)를 넣는다. 기존 묶음 설치의 설정(legacy_config)이 있으면 그것을 이어받는다.
- resources.* 위치는 deploy/RESOURCES.txt 표(원본 앱 폴더 기준 상대경로)에서 읽는다. 없으면 같은 이름 파일을 원본 앱 폴더에서(깊이 4까지) 찾고,
  그래도 없으면 빈 값(그 기능만 비활성).
- Altair 실행 파일의 상대 배치는 config/platform.example.yaml의 altair.* 값에서 읽는다(코드에 경로 없음). 후보 루트: 명시 값 →
  레지스트리(설치 프로그램 목록의 Altair InstallLocation) → ProgramFiles 폴더 아래 Altair\\<버전>. 실행 파일이 가장 많이, 같으면 최신 버전.
  ProgramFiles 폴더는 입력 program_files_dirs(setup.ps1이 $env:ProgramFiles·ProgramW6432를 넘김)에서 읽고, 입력에 없을 때만 환경변수에서 읽는다
  (Windows는 새 프로세스의 ProgramFiles 환경변수를 시스템 값으로 다시 정하므로 부모가 바꾼 값이 자식에 전달되지 않는다).
  환경변수 이름과 파일·폴더 이름은 Windows처럼 대소문자를 구분하지 않고 찾는다(Linux 시험에서도 같은 규칙).
  Altair를 못 찾아도 altair 절의 키(version_label·실행 파일 경로)는 항상 둔다(빈 값 = 기능 비활성, 경고).
- auth.dashboard_public_login_url(로그인·"대시보드로" 링크, 같은 origin 상대경로)은 대시보드 .env의 WINDOWS_WEB_BASE_PATH(없으면 /home/ —
  대시보드 Vite 기본 base)로 맞춘다. 키가 없거나 이전 기본값 "/"일 때만 바꾸고 사용자가 넣은 다른 값은 보존(phase3 D3-38).
  .env에서는 이 키 한 줄만 읽는다(입력 dashboard_web_base_path가 있으면 그것을 쓴다 — setup.ps1이 dashboard-env.ps1로 읽어 넘김).
- 받은 파일 폴더(phase3 §12 S7, D3-46): write가 `<ai_root>/<storage.inbox_dir>`(기본 inbox)를 없으면 만든다. 입력 smb_shares
  (setup.ps1·update-repo.ps1이 Get-SmbShare로 조회만 — 관리자 권한 없이, 실패하면 빈 목록)에서 Path가 그 폴더인 공유를 찾으면
  storage.inbox_share_hint를 `\\\\<computer_name>\\<공유 이름>`으로 채운다(키가 없거나 비어 있을 때만 — 사용자 값 보존).
- 비밀번호·DB URL은 다루지 않는다.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ALTAIR_TOOL_KEYS = ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path")
WORKER_KEYS = ("limiter", "max_logical_cores", "max_memory_gb", "priority")
DEPLOY_KEY_ORDER = ("install_mode", "repo_root", "install_root", "dashboard_root", "python_exe", "pg_bin", "pg_host", "pg_port",
                    "db_name", "db_role", "config_path", "service_user", "run_mode", "caddy_frontend_root", "ai_root",
                    "original_app_root", "altair_root")
_UNSAFE = re.compile(r'[\s\x00-\x1f\x7f&|<>^%!"]')
_VERSION_DIR = re.compile(r"^\d{2,4}(?:\.\d+){0,3}$")
SEARCH_DEPTH = 4


# ---------------------------------------------------------------------------
# 공용
# ---------------------------------------------------------------------------

def fwd(p: str) -> str:
    return p.replace("\\", "/") if p else p


def unsafe(p: str) -> bool:
    return bool(_UNSAFE.search(p))


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(x) for x in name.split(".") if x.isdigit())


def _yaml():
    import yaml  # 설치 venv에 있음(requirements.lock)

    return yaml


def resource_table(resources_txt: Path) -> dict[str, str]:
    """RESOURCES.txt의 'resources.<키>  원본 <상대경로>' 줄 → {키: 상대경로}."""
    out: dict[str, str] = {}
    for line in resources_txt.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*resources\.(\w+)\s+원본\s+(\S+)", line)
        if m:
            out[m.group(1)] = m.group(2).rstrip("/")
    return out


def altair_layout(example: dict[str, Any]) -> dict[str, str]:
    """예시 설정의 altair.* 값에서 '<버전>/' 뒤 상대 배치를 읽는다(예 hwdesktop/hw/bin/win64/hw.exe)."""
    alt = example.get("altair") or {}
    ver = str(alt.get("version_label") or "")
    out = {}
    for k in ALTAIR_TOOL_KEYS:
        v = fwd(str(alt.get(k) or ""))
        i = v.find(f"/{ver}/") if ver else -1
        if i >= 0:
            out[k] = v[i + len(ver) + 2:]
    return out


def _registry_altair_dirs() -> list[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return []
    found: list[Path] = []
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = str(winreg.QueryValueEx(k, "DisplayName")[0])
                        loc = str(winreg.QueryValueEx(k, "InstallLocation")[0])
                except OSError:
                    continue
                if name.lower().startswith("altair") and loc:
                    found.append(Path(loc))
    return found


def env_value(name: str) -> str:
    """환경변수를 Windows처럼 이름 대소문자 무시로 읽는다(정확한 이름 우선). Windows의 os.environ은 원래 그렇게 동작한다."""
    v = os.environ.get(name)
    if v is None:
        low = name.lower()
        v = next((val for k, val in sorted(os.environ.items()) if k.lower() == low), None)
    return v or ""


def resolve_ci(root: Path, rel: str) -> Path | None:
    """root 아래 상대경로 rel(예 SimLab/bin/win64/SimLab.bat)의 파일 — 각 단계 이름을 대소문자 무시로 맞춘다(Windows 파일 시스템과 같은 규칙)."""
    exact = root / rel
    if exact.is_file():
        return exact
    cur = root
    parts = [x for x in fwd(rel).split("/") if x]
    for i, part in enumerate(parts):
        nxt = cur / part
        if not nxt.exists():
            try:
                nxt = next((c for c in sorted(cur.iterdir()) if c.name.lower() == part.lower()), None)
            except OSError:
                nxt = None
            if nxt is None:
                return None
        cur = nxt
    return cur if cur.is_file() else None


def program_files_dirs(given: Any) -> list[str]:
    """입력 program_files_dirs(문자열 또는 목록 — PowerShell 5.1 ConvertTo-Json은 원소 1개 배열을 문자열로 낼 수 있음). 없으면(None) 환경변수."""
    if given is None:
        return [v for v in (env_value("ProgramFiles"), env_value("ProgramW6432")) if v]
    items = [given] if isinstance(given, str) else list(given or [])
    return [str(v) for v in items if v]


def altair_candidates(explicit: str, pf_dirs: list[str] | None = None) -> list[Path]:
    roots: list[Path] = []

    def add_with_versions(p: Path) -> None:
        if not p.is_dir():
            return
        roots.append(p)
        try:
            kids = [c for c in p.iterdir() if c.is_dir() and _VERSION_DIR.match(c.name)]
        except OSError:
            kids = []
        roots.extend(sorted(kids, key=lambda c: _version_key(c.name), reverse=True))

    if explicit:
        add_with_versions(Path(explicit))
    for loc in _registry_altair_dirs():
        # InstallLocation이 <Altair>\<버전> 또는 그 하위일 수 있다 → 자신과 상위 2단계 중 버전 이름 폴더
        for p in (loc, *list(loc.parents)[:2]):
            if _VERSION_DIR.match(p.name):
                roots.append(p)
    for v in program_files_dirs(None) if pf_dirs is None else pf_dirs:
        add_with_versions(Path(v) / "Altair")
    uniq, seen = [], set()
    for r in roots:
        key = os.path.normcase(str(r))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def detect_altair(explicit: str, layout: dict[str, str], pf_dirs: list[str] | None = None) -> dict[str, Any]:
    best: dict[str, Any] = {"root": "", "version_label": "", "paths": {k: "" for k in ALTAIR_TOOL_KEYS}, "found": 0}
    best_key: tuple = (0, ())
    for root in altair_candidates(explicit, pf_dirs):
        paths = {}
        for k in ALTAIR_TOOL_KEYS:
            rel = layout.get(k)
            p = resolve_ci(root, rel) if rel else None
            paths[k] = fwd(str(p)) if p is not None else ""
        n = sum(1 for v in paths.values() if v)
        key = (n, _version_key(root.name) if _VERSION_DIR.match(root.name) else ())
        if n and key > best_key:
            best_key = key
            best = {"root": fwd(str(root)), "version_label": root.name if _VERSION_DIR.match(root.name) else "", "paths": paths, "found": n}
    return best


def _search(root: Path, name: str, want_dir: bool) -> Path | None:
    base_depth = len(root.parts)
    low = name.lower()
    for cur, dirs, files in os.walk(root):
        depth = len(Path(cur).parts) - base_depth
        if depth >= SEARCH_DEPTH:
            dirs[:] = []
        dirs.sort()
        pool = dirs if want_dir else sorted(files)
        for n in pool:
            if n.lower() == low:
                return Path(cur) / n
    return None


def map_resources(original_root: str, table: dict[str, str]) -> dict[str, dict[str, Any]]:
    """원본 앱 폴더 하위의 자원 위치. {키: {path, found, note}} — 못 찾으면 path ''."""
    out: dict[str, dict[str, Any]] = {}
    root = Path(original_root) if original_root else None
    for key, rel in table.items():
        want_dir = key.endswith("_dir")
        if root is None:
            out[key] = {"path": "", "found": False, "note": "원본 앱 폴더 미지정"}
            continue
        p = root / rel
        ok = p.is_dir() if want_dir else p.is_file()
        note = ""
        if not ok:
            hit = _search(root, Path(rel).name, want_dir) if root.is_dir() else None
            if hit is not None:
                p, ok, note = hit, True, f"이름으로 찾음({fwd(str(hit.relative_to(root)))})"
        if ok and unsafe(str(p)):
            out[key] = {"path": "", "found": False, "note": f"경로에 공백·특수문자가 있어 쓸 수 없음: {fwd(str(p))}"}
        elif ok:
            out[key] = {"path": fwd(str(p)), "found": True, "note": note}
        else:
            out[key] = {"path": "", "found": False, "note": f"없음: {rel}"}
    return out


# ---------------------------------------------------------------------------
# YAML 텍스트 편집(주석·순서 유지). 결과는 항상 다시 읽어 검증한다.
# ---------------------------------------------------------------------------

_VALUE = re.compile(r"""^(?P<pre>[ \t]*[^:#\s][^:]*:[ \t]*)(?P<val>"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^#\r\n]*?)(?P<post>[ \t]+#.*)?$""")


def literal(v: Any) -> str:
    if isinstance(v, list):  # 흐름 표기 목록(예시 파일 commands.* 표기와 같게)
        return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = "" if v is None else str(v)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s) and s.lower() not in ("true", "false", "null", "yes", "no", "on", "off", "y", "n"):
        return s  # 단순 낱말은 따옴표 없이(예시 파일 표기와 같게)
    return json.dumps(s, ensure_ascii=False)


def _block(lines: list[str], section: str) -> tuple[int, int, str] | None:
    hdr = re.compile(rf"^{re.escape(section)}:[ \t]*(#.*)?$")
    for i, ln in enumerate(lines):
        if hdr.match(ln):
            end = len(lines)
            indent = ""
            for j in range(i + 1, len(lines)):
                s = lines[j]
                if re.match(r"^[^\s#]", s):
                    end = j
                    break
                if not indent and s.strip() and not s.lstrip().startswith("#"):
                    indent = s[: len(s) - len(s.lstrip())]
            return i, end, indent or "  "
    return None


def set_yaml_value(text: str, path: tuple[str, ...], value: Any, note: str = "") -> str:
    """path(최상위 또는 2단계)의 값을 바꾸거나(줄 끝 주석 유지) 없으면 넣는다."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    lit = literal(value)
    comment = f"  # {note}" if note else ""
    if len(path) == 1:
        rx = re.compile(rf"^{re.escape(path[0])}:")
        for i, ln in enumerate(lines):
            if rx.match(ln):
                m = _VALUE.match(ln)
                lines[i] = m.group("pre") + lit + (m.group("post") or "") if m else f"{path[0]}: {lit}"
                return nl.join(lines)
        insert_at = next((i for i, ln in enumerate(lines) if re.match(r"^[^\s#]", ln)), len(lines))
        lines.insert(insert_at, f"{path[0]}: {lit}{comment}")
        return nl.join(lines)
    section, key = path
    b = _block(lines, section)
    if b is None:
        if lines and lines[-1] == "":
            lines.pop()
        lines += [f"{section}:", f"  {key}: {lit}{comment}", ""]
        return nl.join(lines)
    start, end, indent = b
    rx = re.compile(rf"^{re.escape(indent)}{re.escape(key)}:")
    for i in range(start + 1, end):
        if rx.match(lines[i]):
            m = _VALUE.match(lines[i])
            lines[i] = m.group("pre") + lit + (m.group("post") or "") if m else f"{indent}{key}: {lit}"
            return nl.join(lines)
    lines.insert(start + 1, f"{indent}{key}: {lit}{comment}")
    return nl.join(lines)


def remove_yaml_key(text: str, path: tuple[str, str]) -> str:
    """2단계 키의 한 줄 값(스칼라)을 지운다. 없거나 여러 줄 값이면 그대로."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    b = _block(lines, path[0])
    if b is None:
        return text
    start, end, indent = b
    rx = re.compile(rf"^{re.escape(indent)}{re.escape(path[1])}:[ \t]*\S")
    for i in range(start + 1, end):
        if rx.match(lines[i]):
            del lines[i]
            return nl.join(lines)
    return text


# 이전 예시 기본값 → 새 기본값(phase3 §11.8). S6 이전 설정(= predict.mesh_include_name 없음)에서만, 사용자가 바꾸지 않은
# (이전 기본값 그대로이거나 없는) 키만 갱신하고 표시 키(mesh_include_name)를 넣는다 — 다음 실행부터는 사용자 값(mesh: null 포함)을 건드리지 않음.
# 새 값은 config/platform.example.yaml에서 읽는다(_REMOVE = 폐지 키 삭제).
_REMOVE = object()
UPGRADE_MARKER = ("predict", "mesh_include_name")
UPGRADES: tuple[tuple[tuple[str, str], tuple[Any, ...], str], ...] = (
    # (경로, 이전 기본값들, 없을 때: "skip" | "fill"(절이 있으면 채움) | "always"(절이 없어도 만듦))
    (("commands", "mesh"), (None,), "fill"),                # 이전: mesh: null(SKIPPED) → 원본 m_2 HyperMesh include 변환
    (("predict", "mesh_output_glob"), ("eps_mesh*",), "skip"),  # 폐지(새 메시는 predict.mesh_include_name)
    (UPGRADE_MARKER, (), "always"),
)
# phase3 §14.6·§14.7(S9): S9 이전 설정(= predict_batch.max_runs 없음)에서만 한 번 — response_extract: null(이전 기본) →
# 원본 ⑤ m_4 방식 기본값, predict_batch 절(표시 키 max_runs)을 넣는다. 이후 사용자가 다시 null로 바꾼 값은 건드리지 않는다.
UPGRADE_MARKER_S9 = ("predict_batch", "max_runs")
UPGRADES_S9: tuple[tuple[tuple[str, str], tuple[Any, ...], str], ...] = (
    (("commands", "response_extract"), (None,), "fill"),
    (UPGRADE_MARKER_S9, (), "always"),
)
UPGRADE_GROUPS = ((UPGRADE_MARKER, UPGRADES), (UPGRADE_MARKER_S9, UPGRADES_S9))
# phase3 D3-53: 컨투어 캡처 기본 결과 필드 "Von Mises" → 예측 h3d의 응력 결과 "CornerStress". 이전 기본값 그대로일 때만 1회 —
# 갱신한 줄 끝 주석에 표시(CAPTURE_FIELD_MARK)를 남겨 다음 실행부터는 사용자가 다시 고른 "Von Mises"도 보존한다.
CAPTURE_FIELD_PATH = ("capture", "default_field")
CAPTURE_FIELD_OLD = ("Von Mises",)
CAPTURE_FIELD_MARK = "setup.ps1 D3-53"


def yaml_line(text: str, path: tuple[str, str]) -> tuple[int, str] | None:
    """2단계 키 path의 줄(번호, 내용). 없으면 None."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    b = _block(lines, path[0])
    if b is None:
        return None
    start, end, indent = b
    rx = re.compile(rf"^{re.escape(indent)}{re.escape(path[1])}:")
    for i in range(start + 1, end):
        if rx.match(lines[i]):
            return i, lines[i]
    return None


def set_line_comment(text: str, path: tuple[str, str], note: str) -> str:
    """path 줄의 끝 주석을 note로 바꾼다(값은 그대로)."""
    nl = "\r\n" if "\r\n" in text else "\n"
    found = yaml_line(text, path)
    if found is None:
        return text
    i, ln = found
    m = _VALUE.match(ln)
    if not m:
        return text
    lines = text.split(nl)
    lines[i] = (m.group("pre") + m.group("val")).rstrip() + f"   # {note}"
    return nl.join(lines)


def _get(data: Any, path: tuple[str, ...]) -> tuple[bool, Any]:
    for k in path:
        if not isinstance(data, dict) or k not in data:
            return False, None
        data = data[k]
    return True, data


def _set(data: dict, path: tuple[str, ...], value: Any) -> None:
    for k in path[:-1]:
        data = data.setdefault(k, {})
    data[path[-1]] = value


# 대시보드 웹 경로(phase3 D3-38): 운영 대시보드는 Vite가 WINDOWS_WEB_BASE_PATH(기본 /home/)에서 열린다.
LOGIN_URL_PATH = ("auth", "dashboard_public_login_url")
LOGIN_URL_OLD_DEFAULTS = ("/", "", None)
DASHBOARD_WEB_BASE_KEY = "WINDOWS_WEB_BASE_PATH"
DASHBOARD_WEB_BASE_DEFAULT = "/home/"
_WEB_BASE_OK = re.compile(r"^/(?:[A-Za-z0-9._~\-]+/)*$")


def read_dashboard_env_value(dashboard_root: str, key: str) -> str | None:
    """대시보드 <root>/.env에서 key 한 줄의 값만 읽는다(따옴표 제거). 파일·키가 없으면 None. 다른 줄은 보관하지 않는다."""
    if not dashboard_root:
        return None
    env = Path(dashboard_root) / ".env"
    if not env.is_file():
        return None
    rx = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=\s*(.*?)\s*$")
    for line in env.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = rx.match(line)
        if m:
            v = m.group(1)
            if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                v = v[1:-1]
            return v.strip()
    return None


def normalize_web_base(raw: str | None) -> tuple[str, str | None]:
    """WINDOWS_WEB_BASE_PATH → 링크 경로(앞뒤 '/'). 비었으면 기본 /home/. (값, 경고 또는 None)."""
    v = (raw or "").strip()
    if not v:
        return DASHBOARD_WEB_BASE_DEFAULT, None
    v = "/" + v.strip("/") + "/" if v.strip("/") else "/"
    if not _WEB_BASE_OK.match(v) or any(seg in (".", "..") for seg in v.split("/")):
        return "", f"대시보드 .env의 {DASHBOARD_WEB_BASE_KEY} 값을 링크 경로로 쓸 수 없습니다(영숫자·._~-·/만) — auth.dashboard_public_login_url을 직접 정하세요"
    return v, None


def dashboard_login_url(inputs: dict[str, Any], dashboard_root: str) -> tuple[str, str | None]:
    given = inputs.get("dashboard_web_base_path")
    raw = given if isinstance(given, str) else read_dashboard_env_value(dashboard_root, DASHBOARD_WEB_BASE_KEY)
    return normalize_web_base(raw)


# ---------------------------------------------------------------------------
# 계획
# ---------------------------------------------------------------------------

# 받은 파일 폴더 공유 안내(phase3 §12 S7, D3-46)
INBOX_HINT_PATH = ("storage", "inbox_share_hint")
INBOX_DIR_DEFAULT = "inbox"


def inbox_folder(ai_root: str, inbox_dir: Any) -> str:
    """`<ai_root>/<inbox_dir>`('/' 구분). 상대 이름 규칙(공백·메타문자·'..'·절대경로 없음)을 어기면 빈 값(폴더를 만들지 않음).

    D3-50: `_backup`·`_platform`(대소문자 무시, 끝 마침표·공백 무시)·요소 안 ':'·끝 마침표/공백도 mkdir 전에 거부.
    """
    rel = str(inbox_dir or INBOX_DIR_DEFAULT)
    parts = rel.replace("\\", "/").split("/")
    if not ai_root or unsafe(rel) or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel) or any(x in ("", ".", "..") for x in parts):
        return ""
    if any(":" in x or x[-1] in ". " or x.rstrip(" .").casefold() in ("_backup", "_platform") for x in parts):
        return ""
    return fwd(ai_root).rstrip("/") + "/" + "/".join(parts)


def _norm_share_path(p: str) -> str:
    return fwd(p).rstrip("/").casefold()


def inbox_share_hint(inputs: dict[str, Any], inbox: str) -> str | None:
    """Get-SmbShare 결과(입력 smb_shares: [{name, path}])에서 Path가 받은 파일 폴더인 공유 → `\\\\<컴퓨터>\\<공유>`."""
    host = str(inputs.get("computer_name") or "").strip()
    if not inbox or not host:
        return None
    want = _norm_share_path(inbox)
    for sh in inputs.get("smb_shares") or []:
        if not isinstance(sh, dict):
            continue
        name, path = str(sh.get("name") or "").strip(), str(sh.get("path") or "")
        if name and path and not name.endswith("$") and _norm_share_path(path) == want:
            return f"\\\\{host}\\{name}"
    return None


def _read_json(p: Path) -> dict[str, Any] | None:
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


def plan(inputs: dict[str, Any]) -> dict[str, Any]:
    yaml = _yaml()
    repo = Path(inputs["repo_root"])
    runtime = Path(inputs["runtime_dir"])
    warnings: list[str] = []

    # ---- deploy.json: 명시 인자 > 기존 파일 > 파생 기본값(기존 값은 덮어쓰지 않음) -----------------------------
    deploy_path = runtime / "deploy.json"
    existing = _read_json(deploy_path)
    defaults: dict[str, Any] = dict(inputs.get("deploy_defaults") or {})
    explicit: dict[str, Any] = dict(inputs.get("deploy_explicit") or {})
    deploy = dict(existing or {})
    added, overridden = [], []
    for k in list(DEPLOY_KEY_ORDER) + [k for k in defaults if k not in DEPLOY_KEY_ORDER]:
        if k in explicit:
            if k in deploy and deploy[k] != explicit[k]:
                overridden.append(k)
            elif k not in deploy:
                added.append(k)
            deploy[k] = explicit[k]
        elif k not in deploy and k in defaults:
            deploy[k] = defaults[k]
            added.append(k)
    ordered = {k: deploy[k] for k in DEPLOY_KEY_ORDER if k in deploy}
    ordered.update({k: v for k, v in deploy.items() if k not in ordered})
    deploy = ordered
    deploy_changed = existing is None or deploy != existing

    # ---- platform.yaml ----------------------------------------------------------------------------
    example_path = repo / "config" / "platform.example.yaml"
    example_text = example_path.read_text(encoding="utf-8")
    example = yaml.safe_load(example_text) or {}
    config_path = Path(deploy.get("config_path") or (runtime / "config" / "platform.yaml"))
    legacy = str(inputs.get("legacy_config") or "")
    if config_path.is_file():
        source, base_text = "existing", config_path.read_text(encoding="utf-8-sig")
    elif legacy and Path(legacy).is_file():
        source, base_text = "legacy", Path(legacy).read_text(encoding="utf-8-sig")
    else:
        source, base_text = "example", example_text
    try:
        base = yaml.safe_load(base_text) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"설정 파일 YAML 형식 오류 — 직접 고친 뒤 다시 실행하세요: {config_path if source == 'existing' else legacy} ({exc})")
    if not isinstance(base, dict):
        raise SystemExit(f"설정 파일 최상위가 매핑이 아닙니다: {config_path}")

    ai_root = fwd(str(deploy.get("ai_root") or ""))
    if ai_root and unsafe(ai_root):
        warnings.append(f"AI 루트 경로에 공백·특수문자가 있습니다(쓸 수 없음): {ai_root}")
    alt = detect_altair(str(deploy.get("altair_root") or ""), altair_layout(example), program_files_dirs(inputs.get("program_files_dirs")))
    res = map_resources(str(deploy.get("original_app_root") or ""), resource_table(HERE / "RESOURCES.txt"))

    desired: dict[tuple[str, ...], Any] = {("profile",): "prod"}
    desired[("server", "port")] = (example.get("server") or {}).get("port", 8100)
    # 백엔드가 /physicsai/를 직접 서빙(대시보드 Vite 프록시 경로). 프런트 배치 폴더 = deploy.json caddy_frontend_root(기본 <런타임>\frontend).
    # 기존 파일에 키가 없을 때만 보충 — 사용자가 null(외부 서빙)이나 다른 경로로 바꾼 값은 유지
    desired[("server", "frontend_root")] = fwd(str(deploy.get("caddy_frontend_root") or (runtime / "frontend")))
    desired[("storage", "ai_root")] = ai_root
    desired[("altair", "version_label")] = alt["version_label"]
    for k in ALTAIR_TOOL_KEYS:
        desired[("altair", k)] = alt["paths"][k]
    for k, r in res.items():
        desired[("resources", k)] = r["path"]
    # phase3 §15 S10: 컨투어 캡처 TCL = git 폴더의 저장소 리소스(설치는 wheel이라 패키지 위치에서 찾을 수 없음). 비었거나 없을 때만 채움
    cap_tcl = repo.joinpath("resources", "hyperview", "contour_capture.tcl")
    if cap_tcl.is_file() and not unsafe(fwd(str(cap_tcl))):
        desired[("resources", "contour_capture_tcl")] = fwd(str(cap_tcl))
    desired[("hpc", "gateway")] = "none"
    for k in WORKER_KEYS:
        desired[("worker", k)] = (example.get("worker") or {}).get(k)
    # 비어 있으면 채워도 되는 키(경로 탐색 값): 자원·Altair 경로·AI 루트
    fill_empty = {p for p in desired if p[0] in ("resources", "altair") or p == ("storage", "ai_root")}

    text = base_text
    rows, changed = [], []
    new_file = source == "example"
    for path, want in desired.items():
        key = ".".join(path)
        has, cur = _get(base, path)
        if new_file:
            if want is None or (has and cur == want):
                rows.append({"key": key, "value": cur, "action": "예시 값"})
                continue
            text = set_yaml_value(text, path, want)
            rows.append({"key": key, "value": want, "action": "새로 씀"})
            changed.append(key)
        elif not has:
            # altair 절은 못 찾아도 키를 둔다(빈 값 = 기능 비활성) — 나중에 사용자가 값만 채우면 되게
            if want is None or (want == "" and path[0] == "resources"):
                rows.append({"key": key, "value": cur, "action": "없음(기능 비활성)"})
                continue
            text = set_yaml_value(text, path, want, "setup.ps1이 보충")
            rows.append({"key": key, "value": want, "action": "보충"})
            changed.append(key)
        elif path in fill_empty and (cur is None or cur == "") and want:
            text = set_yaml_value(text, path, want)
            rows.append({"key": key, "value": want, "action": "빈 값 채움"})
            changed.append(key)
        else:
            note = "유지" if cur == want or want in (None, "") else "유지(설정 파일 값 — 바꾸려면 파일을 직접 수정)"
            rows.append({"key": key, "value": cur, "action": note})
    upgraded: dict[tuple[str, ...], Any] = {}
    for marker, group in UPGRADE_GROUPS:
        if new_file or _get(base, marker)[0]:
            continue
        for path, olds, missing in group:
            has, cur = _get(base, path)
            ex_has, want = _get(example, path)
            fill = missing == "always" or (missing == "fill" and isinstance(base.get(path[0]), dict))
            if not ((has and cur in olds) or (not has and fill)):
                continue
            if ex_has and want is not None:
                text = set_yaml_value(text, path, want, "" if has else "setup.ps1이 보충")
                upgraded[path] = want
                rows.append({"key": ".".join(path), "value": want, "action": "새 기본값으로 갱신(이전 기본값)"})
            elif not ex_has and has:
                text = remove_yaml_key(text, path)  # type: ignore[arg-type]
                upgraded[path] = _REMOVE
                rows.append({"key": ".".join(path), "value": None, "action": "폐지 키 제거(이전 기본값)"})
    # 컨투어 캡처 기본 필드(D3-53): 이전 기본값 "Von Mises" 그대로이고 아직 갱신 표시가 없을 때만 1회, 사용자 값은 보존
    has, cur = _get(base, CAPTURE_FIELD_PATH)
    ex_has, field_want = _get(example, CAPTURE_FIELD_PATH)
    line = yaml_line(text, CAPTURE_FIELD_PATH)
    if (not new_file and has and cur in CAPTURE_FIELD_OLD and ex_has and field_want not in CAPTURE_FIELD_OLD
            and line is not None and CAPTURE_FIELD_MARK not in line[1]):
        text = set_yaml_value(text, CAPTURE_FIELD_PATH, field_want)
        text = set_line_comment(text, CAPTURE_FIELD_PATH, f"예측 h3d 응력 결과({CAPTURE_FIELD_MARK}: 이전 기본 {cur} → 새 기본)")
        upgraded[CAPTURE_FIELD_PATH] = field_want
        rows.append({"key": ".".join(CAPTURE_FIELD_PATH), "value": field_want, "action": "새 기본값으로 갱신(이전 기본값)"})
    # 로그인·"대시보드로" 링크(D3-38): 키가 없거나 이전 기본값 "/"일 때만 대시보드 웹 경로로, 사용자 값은 보존
    login_want, login_warn = dashboard_login_url(inputs, str(deploy.get("dashboard_root") or ""))
    if login_warn:
        warnings.append(login_warn)
    has, cur = _get(base, LOGIN_URL_PATH)
    if login_want and (not has or cur in LOGIN_URL_OLD_DEFAULTS) and cur != login_want:
        text = set_yaml_value(text, LOGIN_URL_PATH, login_want, "" if has else "setup.ps1이 보충")
        upgraded[LOGIN_URL_PATH] = login_want
        rows.append({"key": ".".join(LOGIN_URL_PATH), "value": login_want,
                     "action": "대시보드 웹 경로로 맞춤" + ("(이전 기본값)" if has else "")})
    else:
        rows.append({"key": ".".join(LOGIN_URL_PATH), "value": cur, "action": "유지" if cur == login_want or not has else
                     "유지(설정 파일 값 — 바꾸려면 파일을 직접 수정)"})
    # 받은 파일 공유 안내(D3-46): 키가 없거나 비어 있을 때만 SMB 공유 경로로, 사용자 값 보존
    inbox = inbox_folder(ai_root, _get(base, ("storage", "inbox_dir"))[1])
    hint_want = inbox_share_hint(inputs, inbox)
    has, cur = _get(base, INBOX_HINT_PATH)
    if hint_want and (not has or cur in (None, "")):
        text = set_yaml_value(text, INBOX_HINT_PATH, hint_want, "" if has else "setup.ps1이 보충")
        upgraded[INBOX_HINT_PATH] = hint_want
        rows.append({"key": ".".join(INBOX_HINT_PATH), "value": hint_want, "action": "SMB 공유에서 채움"})
    elif has and cur:
        rows.append({"key": ".".join(INBOX_HINT_PATH), "value": cur, "action": "유지"})
    if new_file:
        hdr = "# PhysicsAI 설정 — deploy/setup.ps1이 config/platform.example.yaml에서 생성. 값은 이 파일에서 직접 고친다(setup.ps1을 다시 실행해도 덮어쓰지 않음)."
        nl = "\r\n" if "\r\n" in text else "\n"
        first, _, rest = text.partition(nl)
        text = (hdr + nl + rest) if first.startswith("#") else (hdr + nl + text)

    # 편집 결과 검증: 바꾼 키는 원하는 값, 나머지는 원본과 같아야 한다(아니면 쓰지 않고 안내)
    config_ok = True
    try:
        after = yaml.safe_load(text) or {}
        expect = copy.deepcopy(base)
        for key in changed:
            _set(expect, tuple(key.split(".")), desired[tuple(key.split("."))])
        for path, want in upgraded.items():
            if want is _REMOVE:
                del expect[path[0]][path[1]]
            else:
                _set(expect, path, want)
        if after != expect:
            config_ok = False
    except yaml.YAMLError:
        config_ok = False
    if not config_ok:
        warnings.append(f"설정 파일을 자동으로 보충하지 못했습니다(형식이 예상과 다름) — 다음 키를 직접 추가하세요: {', '.join(changed)}")
        text, changed, upgraded = base_text, [], {}
    changed += [".".join(p) for p in upgraded]
    config_changed = source != "existing" or bool(changed)

    if not alt["found"]:
        warnings.append("Altair 실행 파일을 찾지 못했습니다(altair.* 빈 값 — Altair 기능 비활성). 설치 위치가 다르면 -AltairRoot로 지정하거나 설정 파일에서 직접 고치세요")
    elif alt["found"] < len(ALTAIR_TOOL_KEYS):
        miss = [k for k, v in alt["paths"].items() if not v]
        warnings.append(f"Altair {alt['version_label']}에서 일부 실행 파일을 찾지 못했습니다: {', '.join(miss)}")
    final_pred = _get(yaml.safe_load(text) or {}, ("resources", "preview_pred_h3d_tcl"))[1]
    final_profile = _get(yaml.safe_load(text) or {}, ("profile",))[1]
    if final_profile == "prod" and not final_pred:
        warnings.append("resources.preview_pred_h3d_tcl이 비어 있습니다 — profile prod에서는 필수라 워커가 시작되지 않습니다"
                        "(원본 앱 폴더를 지정하거나 설정 파일에 경로를 쓰세요)")
    return {
        "deploy_path": str(deploy_path), "deploy_exists": existing is not None, "deploy": deploy,
        "deploy_added": added if existing is not None else [], "deploy_overridden": overridden, "deploy_changed": deploy_changed,
        "config_path": str(config_path), "config_source": source, "config_changed": config_changed,
        "config_rows": rows, "config_changed_keys": changed, "config_text": text,
        "altair": alt, "resources": res, "ai_root": ai_root, "inbox_path": inbox, "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 쓰기
# ---------------------------------------------------------------------------

def _backup(p: Path, runtime: Path, stamp: str) -> str:
    dest = runtime / "_backup" / stamp / p.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    return str(dest)


def write(inputs: dict[str, Any], pl: dict[str, Any]) -> dict[str, Any]:
    runtime = Path(inputs["runtime_dir"])
    stamp = str(inputs.get("stamp") or "backup")
    out: dict[str, Any] = {"backups": [], "written": []}
    for sub in ("config", "logs", "state"):
        (runtime / sub).mkdir(parents=True, exist_ok=True)
    deploy_path = Path(pl["deploy_path"])
    if pl["deploy_changed"]:
        if deploy_path.is_file():
            out["backups"].append(_backup(deploy_path, runtime, stamp))
        deploy_path.write_text(json.dumps(pl["deploy"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out["written"].append(str(deploy_path))
    cfg = Path(pl["config_path"])
    if pl["config_changed"]:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        if cfg.is_file():
            out["backups"].append(_backup(cfg, runtime, stamp))
        with open(cfg, "w", encoding="utf-8", newline="") as f:
            f.write(pl["config_text"])
        out["written"].append(str(cfg))
    ai_root = pl["ai_root"]
    if ai_root and not unsafe(ai_root):
        Path(ai_root).mkdir(parents=True, exist_ok=True)
        if pl.get("inbox_path") and not os.path.lexists(pl["inbox_path"]):
            Path(pl["inbox_path"]).mkdir(parents=True, exist_ok=True)  # 받은 파일 폴더(D3-46) — 공유는 관리자가 따로 만든다
    out["validation"] = validate(str(cfg))
    return out


def validate(config_path: str) -> dict[str, Any]:
    try:
        from physicsai_core.config import load_config
    except ImportError as exc:  # pragma: no cover - 설치 venv에는 있음
        return {"ok": None, "issues": [f"(검증 생략: {exc})"], "warnings": []}
    lc = load_config(config_path, environ={})
    return {"ok": lc.ok, "issues": [f"{i.key}: {i.message}" for i in lc.issues],
            "warnings": [f"{i.key}: {i.message}" for i in lc.warnings]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="setup_config.py")
    ap.add_argument("action", choices=("plan", "write"))
    ap.add_argument("--inputs", required=True, help="입력 JSON 파일(setup.ps1이 만든다)")
    ap.add_argument("--out", default="", help="결과 JSON 파일(UTF-8). 비우면 표준 출력")
    args = ap.parse_args(argv)
    inputs = _read_json(Path(args.inputs)) or {}
    pl = plan(inputs)
    if args.action == "write":
        pl["write"] = write(inputs, pl)
    pl.pop("config_text", None)
    data = json.dumps(pl, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(data, encoding="utf-8")  # PowerShell 5.1은 콘솔 코드 페이지와 무관하게 파일을 UTF-8로 읽는다
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
