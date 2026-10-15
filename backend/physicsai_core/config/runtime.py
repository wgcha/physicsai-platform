"""설치 런타임 폴더에서 설정 경로·DB URL을 찾는다(phase3 D3-41 — 관리자 권한 없는 설치, 머신 환경변수 대신 파일).

설치(deploy/setup.ps1·install.ps1)는 작업 스케줄러에 `python -m physicsai_api.serve --runtime <런타임>`,
`python -m physicsai_worker --runtime <런타임>`을 등록한다. 인자에는 파일 경로만 있고 비밀값은 없다.

런타임 폴더(<git>/.runtime 또는 묶음 install_root):
  config/platform.yaml     설정(기본 위치 — 다르면 --config)
  secrets/database_url     DB URL 한 줄(현재 사용자·SYSTEM만 읽기, install-common.ps1 Write-PhysicsAIRuntimeSecret)

우선순위(이름마다, 높은 것부터):
  1) 이 프로세스에 직접 준 환경변수 — 머신 환경변수에서 물려받은 값과 다를 때(개발·시험·수동 실행)
  2) --config 인자(설정 경로만)
  3) 런타임 파일
  4) 이전 설치의 머신 환경변수(물려받은 값) — 런타임 파일이 없을 때만(이전 후에는 런타임 파일이 우선)
찾은 값은 이 프로세스 환경(os.environ)에 넣는다 — load_config()·DB 연결·로그 마스킹이 그대로 쓴다. 출처 설명에는 값이 없다.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, MutableMapping
from pathlib import Path

CONFIG_ENV = "PHYSICSAI_CONFIG"
DB_URL_ENV = "PHYSICSAI_DATABASE_URL"
_MACHINE_ENV_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"


def runtime_config_path(runtime_dir: str | os.PathLike[str]) -> Path:
    return Path(runtime_dir) / "config" / "platform.yaml"


def runtime_secret_path(runtime_dir: str | os.PathLike[str]) -> Path:
    return Path(runtime_dir) / "secrets" / "database_url"


def machine_environment(names: Iterable[str]) -> dict[str, str]:
    """Windows 머신 범위 환경변수(레지스트리, 일반 사용자도 읽기 가능). 그 밖의 OS·실패는 빈 dict."""
    if os.name != "nt":
        return {}
    try:
        import winreg

        out: dict[str, str] = {}
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY) as key:
            for n in names:
                try:
                    out[n] = str(winreg.QueryValueEx(key, n)[0])
                except OSError:
                    pass
        return out
    except OSError:
        return {}


def read_secret(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    return value or None


def apply_runtime(
    runtime_dir: str | os.PathLike[str] | None,
    *,
    config_arg: str | None = None,
    url_envs: Iterable[str] = (DB_URL_ENV,),
    environ: MutableMapping[str, str] | None = None,
    machine_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """위 우선순위로 PHYSICSAI_CONFIG와 DB URL 환경변수(url_envs)를 정해 environ에 넣는다. 반환: 이름 → 출처 설명(값 없음)."""
    env = os.environ if environ is None else environ
    names = [CONFIG_ENV, *url_envs]
    machine = machine_environment(names) if machine_env is None else machine_env
    rt = Path(runtime_dir) if runtime_dir else None
    sources: dict[str, str] = {}

    def explicit(name: str) -> bool:
        value = env.get(name)
        return bool(value) and value != machine.get(name)

    cfg_file = runtime_config_path(rt) if rt else None
    if explicit(CONFIG_ENV):
        sources[CONFIG_ENV] = "환경변수"
    elif config_arg:
        env[CONFIG_ENV] = str(config_arg)
        sources[CONFIG_ENV] = "--config 인자"
    elif cfg_file is not None and cfg_file.is_file():
        env[CONFIG_ENV] = str(cfg_file)
        sources[CONFIG_ENV] = f"런타임 파일 {cfg_file}"
    elif env.get(CONFIG_ENV):
        sources[CONFIG_ENV] = "머신 환경변수(이전 설치)"
    else:
        sources[CONFIG_ENV] = "기본값 config/platform.yaml"

    secret_file = runtime_secret_path(rt) if rt else None
    secret = read_secret(secret_file) if secret_file is not None else None
    for name in url_envs:
        if explicit(name):
            sources[name] = "환경변수"
        elif secret:
            env[name] = secret
            sources[name] = f"런타임 파일 {secret_file}"
        elif env.get(name):
            sources[name] = "머신 환경변수(이전 설치)"
        else:
            sources[name] = "없음"
    return sources


def describe(sources: dict[str, str]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in sources.items())
