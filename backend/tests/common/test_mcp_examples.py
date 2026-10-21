"""mcp.md V-MCP-19: 클라이언트 설정 예시(deploy/mcp/examples/) — 파싱·필수 키·토큰 평문 없음·가이드 문서 코드 블록과 일치·구현(경로·환경변수·실행기 이름)과 일치."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from physicsai_test_support import REPO

EX = REPO / "deploy" / "mcp" / "examples"
GUIDE = REPO / "docs" / "manual" / "mcp-clients.md"
FILES = {"claude.mcp.json": "json", "claude_desktop_config.json": "json", "codex.config.toml": "toml", "gemini.settings.json": "json",
         "gemini.settings.stdio.json": "json"}
ENV_REF = re.compile(r"\$\{?PHYSICSAI_MCP_TOKEN\}?")


def parse(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)


def guide_blocks() -> list[tuple[str, str, str]]:
    """(소절 제목, 언어, 내용) — `### …` 소절 안의 json·toml 코드 블록."""
    text = GUIDE.read_text(encoding="utf-8")
    out, section = [], ""
    for m in re.finditer(r"^(#{2,3} [^\n]*)$|^```(json|toml)\n(.*?)^```", text, re.S | re.M):
        if m.group(1):
            section = m.group(1)
        else:
            out.append((section, m.group(2), m.group(3)))
    return out


def servers(doc: dict[str, Any]) -> dict[str, Any]:
    return doc.get("mcp_servers") or doc["mcpServers"]


def test_examples_exist_and_parse():
    assert {p.name for p in EX.iterdir()} == set(FILES) | {"README.txt"}
    for name in FILES:
        assert servers(parse(EX / name)), name


def test_examples_have_required_keys_and_no_token_plaintext():
    from physicsai_mcp import stdio

    for name in FILES:
        text = (EX / name).read_text(encoding="utf-8")
        assert "pai_" not in text and "pcf_" not in text, name  # 토큰 평문 금지(예시에 pai_ 0건)
        for sname, s in servers(parse(EX / name)).items():
            if "command" in s:  # stdio: 실행기 + 환경변수(서버 주소 + 토큰 파일 또는 환경변수)
                assert s["command"] == "physicsai-mcp", (name, sname)
                env = s.get("env") or {}
                assert stdio.ENV_URL in env and (stdio.ENV_TOKEN_FILE in env or stdio.ENV_TOKEN in env), (name, sname)
                assert env[stdio.ENV_URL].endswith("/physicsai") and "pai_" not in json.dumps(env), (name, sname)
            else:  # HTTP: 주소 + 환경변수 참조 인증
                url = s.get("url") or s.get("httpUrl")
                assert url and url.endswith("/physicsai/mcp"), (name, sname)
                auth = (s.get("headers") or {}).get("Authorization")
                assert (auth and auth.startswith("Bearer ") and ENV_REF.search(auth)) or s.get("bearer_token_env_var") == stdio.ENV_TOKEN, (name, sname)


def test_examples_match_implementation():
    """예시의 마운트 경로·실행기 이름이 구현과 같다(키가 바뀌면 예시·가이드만 고친다 — 서버 무변경)."""
    from physicsai_api.mcp.http_mount import MOUNT_PATH

    assert MOUNT_PATH == "/physicsai/mcp"
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert "physicsai-mcp" in pyproject["project"]["scripts"]
    assert pyproject["project"]["scripts"]["physicsai-mcp"] == "physicsai_mcp.stdio:main"


def _merge(dicts: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = _merge([out.get(k, {}), v]) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def test_examples_equal_guide_code_blocks():
    blocks = guide_blocks()
    assert blocks, "가이드에서 코드 블록을 찾지 못했습니다"
    by_lang = {lang: [(sec, body) for sec, lg, body in blocks if lg == lang] for lang in ("json", "toml")}
    # JSON 예시 = 가이드의 json 블록 중 하나와 파싱 결과가 같다
    guide_json = [json.loads(body) for _, body in by_lang["json"]]
    for name, kind in FILES.items():
        if kind == "json":
            assert parse(EX / name) in guide_json, f"{name}이 가이드의 어느 json 블록과도 다릅니다"
    # 가이드의 모든 json 블록은 예시 파일이 있다
    ex_json = [parse(EX / n) for n, k in FILES.items() if k == "json"]
    for doc in guide_json:
        assert doc in ex_json, "가이드의 json 블록에 대응하는 예시 파일이 없습니다"
    # TOML 예시 = 가이드 toml 블록들을 합친 것
    assert _merge([tomllib.loads(body) for _, body in by_lang["toml"]]) == parse(EX / "codex.config.toml")


def test_guide_has_no_token_plaintext_and_cli_commands_match():
    text = GUIDE.read_text(encoding="utf-8")
    assert "pai_" not in text.replace("`pai_…`", "").replace("pai_xxxxxxxx", "").replace("pai_…", "")
    from physicsai_mcp import stdio

    for var in (stdio.ENV_URL, stdio.ENV_TOKEN, stdio.ENV_TOKEN_FILE):
        assert var in text, var
    assert "physicsai-mcp --check" in text  # 가이드가 안내하는 실행기 옵션이 실제로 있다
    assert stdio.main(["--version"]) == 0


@pytest.mark.parametrize("name", [n for n in FILES if n.endswith(".json")])
def test_json_examples_are_formatted_like_the_guide(name):
    """사람이 복사해 쓰는 파일 — 들여쓰기 2칸·끝 줄바꿈 1개."""
    text = (EX / name).read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n"
