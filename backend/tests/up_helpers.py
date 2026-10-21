"""업로드 시험 공용(upload-report.md §13.1 V-UP): 설정을 바꾼 클라이언트 팩토리, 세션 생성·청크 전송 도우미."""

from __future__ import annotations

import hashlib
from contextlib import ExitStack
from typing import Any

import httpx
import pytest

from physicsai_test_support import API, H

OCTET = "application/octet-stream"
MB = 1024 * 1024


def blob(n: int, seed: str = "x") -> bytes:
    """결정적 바이트 n개(청크마다 달라 보이게 seed 해시를 반복)."""
    unit = hashlib.sha256(seed.encode()).digest() * 4096  # 128 KiB
    return (unit * (n // len(unit) + 1))[:n]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def make_client(settings_dict, engine, fake_dashboard):
    """make(upload={...}, **top) → (TestClient, AppContext). 기본 chunk_mb=1·min_free_gb=0(여유 공간 시험은 free_bytes를 대체)."""
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    stack = ExitStack()

    def make(upload: dict[str, Any] | None = None, **top: Any):
        d = {**settings_dict, **top, "upload": {"min_free_gb": 0, "chunk_mb": 1, **(upload or {})}}
        lc = load_config_dict(d, environ={})
        assert lc.ok, lc.issues
        ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))
        c = stack.enter_context(TestClient(create_app(ctx), base_url="http://127.0.0.1"))
        return c, ctx

    yield make
    stack.close()
    from physicsai_core.paths import register_protected_roots

    register_protected_roots([])  # create_app이 전역 보호 루트를 등록한다 — 시험 사이에 새지 않게


def study(c, name="S1", token="tok-power") -> str:
    r = c.post(f"{API}/studies", headers=H(token, True), json={"project_id": "p-1", "folder_name": name, "title": "제목"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def create(c, sid, purpose, files: dict[str, bytes], *, name="up1", token="tok-power", declare_sha=True, engine=None,
           sizes: dict[str, int] | None = None):
    body: dict[str, Any] = {"purpose": purpose, "name": name, "files": [
        {"rel": r, "size": (sizes or {}).get(r, len(b)), **({"sha256": sha(b)} if declare_sha else {})} for r, b in files.items()]}
    if engine:
        body["engine"] = engine
    return c.post(f"{API}/studies/{sid}/uploads", headers=H(token, True), json=body)


def put(c, uid, index, offset, data: bytes, *, token="tok-power", chunk_sha: bool | str = True, ctype=OCTET, write=True):
    h = {**H(token, write), "Content-Type": ctype}
    if chunk_sha is True:
        h["X-Chunk-Sha256"] = sha(data)
    elif chunk_sha:
        h["X-Chunk-Sha256"] = chunk_sha
    return c.put(f"{API}/uploads/{uid}/files/{index}", params={"offset": offset}, content=data, headers=h)


def send(c, up: dict[str, Any], files: dict[str, bytes], *, chunk=MB, token="tok-power", only: set[str] | None = None) -> None:
    """세션의 파일을 청크로 전부(또는 only) 보낸다(이어 올리기 — 서버 received부터)."""
    for f in up["files"]:
        if f["done"] or (only is not None and f["rel"] not in only):
            continue
        data = files[f["rel"]]
        off = f["received"]
        while off < len(data):
            r = put(c, up["upload_id"], f["index"], off, data[off:off + chunk], token=token)
            assert r.status_code == 200, r.text
            off = r.json()["received"]
        assert off == len(data)


def get(c, uid, token="tok-power") -> dict[str, Any]:
    r = c.get(f"{API}/uploads/{uid}", headers=H(token))
    assert r.status_code == 200, r.text
    return r.json()


def complete(c, uid, token="tok-power"):
    return c.post(f"{API}/uploads/{uid}/complete", headers=H(token, True))


def code(r) -> tuple[int, str]:
    return r.status_code, r.json()["detail"]["code"]
