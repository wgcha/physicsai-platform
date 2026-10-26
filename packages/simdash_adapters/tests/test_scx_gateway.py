"""phase3 §16.7·§16.12: ScxHpcGateway·ScxRelayClient — 가짜 relay로 설정·비밀·health·업로드·제출(replay·UNKNOWN)·상태 매핑·다운로드·resolve."""

from __future__ import annotations

import ast
import hashlib
import logging
from pathlib import Path

import pytest

from simdash_adapters.hpc import (
    HpcGatewayError,
    ScxConfig,
    ScxHpcGateway,
    ScxRadiossRequest,
    make_gateway,
    parse_relay_url,
    read_secret_file,
    validate_scx_config,
)

from simdash_adapters.hpc.scx_client import MSG_RELAY_DISABLED, MSG_RELAY_NO_ROUTE

SRC = Path(__file__).resolve().parents[1] / "src" / "simdash_adapters" / "hpc"


def _gw(fake_relay, tmp_path, **over) -> ScxHpcGateway:
    sec = fake_relay.write_secret(tmp_path / "secrets" / "scx_relay_key")
    cfg = ScxConfig.from_mapping(fake_relay.config_mapping(str(sec), **over))
    return ScxHpcGateway(cfg, str(sec), sleep=lambda s: None)


def _req(rid: str, job_dir: str, **over) -> ScxRadiossRequest:
    d = dict(request_id=rid, input_path=f"{job_dir}/m_0000.rad", engine_paths=(), additional_paths=(), version="2026.1",
             appliance="radioss-app", ncpu=16, memory_gb=None, queue_type="implicit", run_type="both", mpi="SMP (default)",
             single_precision=False, client_ref={"app": "physicsai"})
    d.update(over)
    return ScxRadiossRequest(**d)


def _put(fake_relay, rel: str, data: bytes = b"x") -> None:
    p = fake_relay.drive_file(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


@pytest.mark.parametrize("url, ok", [
    ("http://127.0.0.1:8000", True), ("http://[::1]:8000", True), ("http://localhost:8000/", True),
    ("https://127.0.0.1:8000", False), ("http://10.0.0.1:8000", False), ("http://127.0.0.1", False),
    ("http://127.0.0.1:8000/internal", False), ("http://u:p@127.0.0.1:8000", False), ("http://127.0.0.1:8000?x=1", False),
    ("http://evil.com#@127.0.0.1:80", False), ("", False),
])
def test_relay_url_loopback_only(url, ok):
    if ok:
        parse_relay_url(url)
    else:
        with pytest.raises(ValueError):
            parse_relay_url(url)


def test_config_validation_and_secret(tmp_path, fake_relay):
    base = fake_relay.config_mapping("")
    assert validate_scx_config(ScxConfig.from_mapping(base)) == []
    probs = validate_scx_config(ScxConfig.from_mapping({**base, "appliance": "", "version": "", "ncpu": 0, "memory_gb": 0,
                                                         "drive_base": "/Users/x", "relay_url": "http://1.2.3.4:1",
                                                         "stage_patterns": ["a/*.rad"], "collect_max_depth": 9}))
    joined = " | ".join(probs)
    for frag in ("appliance", "version", "ncpu", "memory_gb", "drive_base", "loopback" if "loopback" in joined else "127.0.0.1",
                 "stage_patterns", "collect_max_depth"):
        assert frag in joined, frag
    # 비밀 파일: 없음·형식 오류·정상(BOM·공백 무시), 문제 문구에 값 없음
    p = tmp_path / "k"
    assert read_secret_file(str(p)) == (None, "비밀 파일 없음")
    p.write_text("short\n", encoding="utf-8")
    v, why = read_secret_file(str(p))
    assert v is None and "short" not in why
    good = "A" * 43
    p.write_text("﻿  " + good + "\r\n", encoding="utf-8")
    assert read_secret_file(str(p)) == (good, None)


def test_availability_states(fake_relay, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    gw = _gw(fake_relay, tmp_path)
    av = gw.availability()
    assert av.configured and av.mode == "scx" and av.message == "SCX(대시보드 연결)"
    # TTL 안에서는 health를 다시 부르지 않음
    gw.availability()
    assert len(fake_relay.calls("/health")) == 1
    # job_api 없음 → configured=false
    gw2 = _gw(fake_relay, tmp_path, health_ttl_s=0)
    fake_relay.job_api = False
    av2 = gw2.availability()
    assert not av2.configured and "잡 API" in av2.message
    # 연결 실패(일시) → 작업 생성은 막지 않음
    fake_relay.job_api = True
    gw3 = _gw(fake_relay, tmp_path, health_ttl_s=0)
    fake_relay.drop_all = True
    av3 = gw3.availability()
    assert av3.configured and "확인 실패" in av3.message
    fake_relay.drop_all = False
    # 비밀 파일 없음 → configured=false(경로만)
    cfg = ScxConfig.from_mapping(fake_relay.config_mapping(""))
    gw4 = ScxHpcGateway(cfg, str(tmp_path / "none" / "scx_relay_key"))
    av4 = gw4.availability()
    assert not av4.configured and "scx_relay_key" in av4.message
    # 설정 오류
    bad = ScxHpcGateway(ScxConfig.from_mapping(fake_relay.config_mapping("", relay_url="http://example.com:1")), "")
    assert not bad.availability().configured
    # 범용 submit은 NOT_CONFIGURED
    with pytest.raises(HpcGatewayError) as ei:
        gw.submit(None)  # type: ignore[arg-type]
    assert ei.value.code == "NOT_CONFIGURED"
    # 비밀 값은 repr·로그·헤더 밖 어디에도 없음
    assert fake_relay.secret not in repr(gw) and fake_relay.secret not in repr(gw.client())
    assert fake_relay.secret not in caplog.text
    assert all(h.get("x-scx-relay-key") == fake_relay.secret for h in fake_relay.headers_seen)
    assert all(fake_relay.secret not in str(r["query"]) for r in fake_relay.requests)


def test_wrong_secret_is_unavailable(fake_relay, tmp_path):
    sec = tmp_path / "k"
    sec.write_text("B" * 43, encoding="utf-8")
    gw = ScxHpcGateway(ScxConfig.from_mapping(fake_relay.config_mapping(str(sec))), str(sec))
    with pytest.raises(HpcGatewayError) as ei:
        gw.health()
    assert ei.value.relay_code == "RELAY_UNAUTHORIZED" and ei.value.code == "UNAVAILABLE"
    assert "B" * 43 not in str(ei.value)


def _serve(handler_cls):
    import threading
    from http.server import HTTPServer
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("ctype, body, want, relay_code", [
    ("text/plain", b"The server is configured with a public base URL of /home/secret/x", MSG_RELAY_NO_ROUTE, None),
    ("application/json", b'{"code":"RELAY_DISABLED","message":"secret detail","retryable":false}', MSG_RELAY_DISABLED, "RELAY_DISABLED"),
])
def test_relay_404_messages(fake_relay, tmp_path, ctype, body, want, relay_code):
    from http.server import BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(404)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = _serve(H)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        gw = _gw(fake_relay, tmp_path, relay_url=url, health_ttl_s=0)
        with pytest.raises(HpcGatewayError) as ei:
            gw.health()
        assert str(ei.value) == want and ei.value.http_status == 404 and ei.value.relay_code == relay_code
        assert "secret" not in str(ei.value) and "/home/" not in str(ei.value)
        av = gw.availability()  # 환경 점검(health) 경로도 같은 문구, 작업 생성은 막지 않음
        assert av.configured and av.message.endswith(want)
    finally:
        srv.shutdown()
        srv.server_close()


def test_upload_batch_and_new_dir(fake_relay, tmp_path):
    gw = _gw(fake_relay, tmp_path)
    src = tmp_path / "a.rad"
    src.write_bytes(b"hello")
    sha = hashlib.sha256(b"hello").hexdigest()
    assert gw.ensure_new_dir("cushion", "01_x") == "01_x"  # 부모 없음 → 그대로
    b0 = gw.mkdirs("cushion/01_x", "pai-1:mkdir")
    bid = gw.upload(str(src), "cushion/01_x", "a.rad", sha, "pai-1:f:a.rad", size=5)
    states = [gw.batch(bid)["state"] for _ in range(3)]
    assert states == ["RUNNING", "DONE", "DONE"]
    assert gw.batch(b0["batch_id"])["state"] in ("RUNNING", "DONE")
    assert fake_relay.drive_file("cushion/01_x/a.rad").read_bytes() == b"hello"
    # 멱등: 같은 request_id는 같은 묶음
    assert gw.upload(str(src), "cushion/01_x", "a.rad", sha, "pai-1:f:a.rad", size=5) == bid
    # 항상 새 폴더: _2…_9, 다 있으면 SCX_REMOTE_DIR_EXISTS
    assert gw.ensure_new_dir("cushion", "01_x") == "01_x_2"
    for i in range(2, 10):
        fake_relay.drive_file(f"cushion/01_x_{i}").mkdir(parents=True)
    with pytest.raises(HpcGatewayError) as ei:
        gw.ensure_new_dir("cushion", "01_x")
    assert ei.value.relay_code == "SCX_REMOTE_DIR_EXISTS"
    # 해시 불일치 업로드 → 400
    with pytest.raises(HpcGatewayError) as ei:
        gw.upload(str(src), "cushion/01_y", "a.rad", "0" * 64, "pai-2:f:a.rad", size=5)
    assert ei.value.relay_code == "HASH_MISMATCH"
    # SPDM 루트 거부(relay 쪽)
    with pytest.raises(HpcGatewayError) as ei:
        gw.mkdirs("SPDM/x", "pai-3:mkdir")
    assert ei.value.relay_code == "PATH_NOT_ALLOWED"
    with pytest.raises(HpcGatewayError):
        gw.mkdirs("../x", "pai-4:mkdir")  # PhysicsAI 쪽 검사


def test_submit_replay_unknown_failed(fake_relay, tmp_path):
    gw = _gw(fake_relay, tmp_path)
    _put(fake_relay, "cushion/01_a/m_0000.rad")
    # 응답이 끊김 2번 → 같은 request_id replay → 어댑터 호출 1회
    fake_relay.drop_submit = 2
    out = gw.submit_radioss(_req("pai-a", "cushion/01_a"))
    assert out.state == "SUBMITTED" and out.job_id and out.replays == 2
    assert len(fake_relay.adapter_calls) == 1 and len(fake_relay.calls("/jobs/radioss")) == 3
    # SUBMISSION_UNKNOWN → UNKNOWN(replay 안 함)
    _put(fake_relay, "cushion/01_b/m_0000.rad")
    fake_relay.submit_mode = "unknown"
    out = gw.submit_radioss(_req("pai-b", "cushion/01_b"))
    assert out.state == "UNKNOWN" and out.code == "SUBMISSION_UNKNOWN" and out.replays == 0
    # 처리 중 → replay 소진 → UNKNOWN
    _put(fake_relay, "cushion/01_c/m_0000.rad")
    fake_relay.submit_mode = "in_progress"
    out = gw.submit_radioss(_req("pai-c", "cushion/01_c"))
    assert out.state == "UNKNOWN" and out.replays == 3
    # 전송 오류만 계속 → UNKNOWN
    fake_relay.submit_mode = "ok"
    fake_relay.drop_all = True
    out = gw.submit_radioss(_req("pai-d", "cushion/01_d"))
    assert out.state == "UNKNOWN" and "replay" in out.message
    fake_relay.drop_all = False
    # 확정 실패
    _put(fake_relay, "cushion/01_e/m_0000.rad")
    fake_relay.submit_mode = "fail:SCX_JOB_ERROR"
    out = gw.submit_radioss(_req("pai-e", "cushion/01_e"))
    assert out.state == "FAILED" and out.code == "SCX_JOB_ERROR"
    fake_relay.submit_mode = "ok"
    out = gw.submit_radioss(_req("pai-f", "cushion/01_f"))  # 입력 파일 없음
    assert out.state == "FAILED" and out.code == "NOT_FOUND"
    out = gw.submit_radioss(_req("pai-g", "cushion/01_a", additional_paths=("other/x.inc",)))
    assert out.state == "FAILED" and out.code == "INVALID_REQUEST"


def test_status_mapping_table(fake_relay, tmp_path):
    gw = _gw(fake_relay, tmp_path)
    _put(fake_relay, "cushion/01_a/m_0000.rad")
    fake_relay.status_seq = ["Queued", "Running", "Completed", "Failed", "Aborted", "Weird", "__SCX_NOT_FOUND__", "completed"]
    jid = gw.submit_radioss(_req("pai-a", "cushion/01_a")).job_id
    got = []
    for _ in range(8):
        st = gw.status(jid)
        got.append((st.state, st.outcome, st.raw_state))
    assert got == [("QUEUED", None, "Queued"), ("RUNNING", None, "Running"), ("FINISHED", "SUCCEEDED", "Completed"),
                   ("FINISHED", "FAILED", "Failed"), ("FINISHED", "CANCELED", "Aborted"), ("UNKNOWN", None, "Weird"),
                   ("UNKNOWN", None, "SCX_JOB_NOT_FOUND"), ("FINISHED", "SUCCEEDED", "completed")]
    st = gw.status(jid)
    assert st.output_rel == "cushion/01_a" and st.output_path.endswith("cushion/01_a") and st.not_found is False
    fake_relay.busy_status = 1
    with pytest.raises(HpcGatewayError) as ei:
        gw.status(jid)
    assert ei.value.code == "UNAVAILABLE" and "대시보드 SCX 연결 확인" in str(ei.value)
    with pytest.raises(HpcGatewayError) as ei:
        gw.status("nope")
    assert ei.value.code == "UNAVAILABLE" and ei.value.relay_code == "JOB_NOT_FOUND"
    gw.cancel(jid)
    assert fake_relay.terminated == [jid]
    with pytest.raises(HpcGatewayError):
        gw.cancel("nope")


def test_download_and_resolve(fake_relay, tmp_path):
    gw = _gw(fake_relay, tmp_path)
    _put(fake_relay, "cushion/01_a/r.h3d", b"h3d-bytes")
    dst = tmp_path / "out.part"
    size, sha = gw.download("cushion/01_a/r.h3d", str(dst), 1 << 20)
    assert size == 9 and sha == hashlib.sha256(b"h3d-bytes").hexdigest() and dst.read_bytes() == b"h3d-bytes"
    fake_relay.hash_mismatch = 1
    with pytest.raises(HpcGatewayError) as ei:
        gw.download("cushion/01_a/r.h3d", str(dst), 1 << 20)
    assert ei.value.relay_code == "HASH_MISMATCH"
    with pytest.raises(HpcGatewayError) as ei:
        gw.download("cushion/01_a/r.h3d", str(dst), 4)
    assert ei.value.relay_code == "TOO_LARGE"
    ents = gw.list("cushion/01_a")
    assert [e["name"] for e in ents] == ["r.h3d"]
    # resolve: UNKNOWN 기록 → attach / abandon
    _put(fake_relay, "cushion/01_b/m_0000.rad")
    fake_relay.submit_mode = "unknown"
    assert gw.submit_radioss(_req("pai-b", "cushion/01_b")).state == "UNKNOWN"
    from simdash_fake_scx_relay import add_remote_job

    jid = add_remote_job(fake_relay, "cushion/01_b")
    d = gw.resolve("pai-b", "attach", jid)
    assert d["state"] == "ATTACHED" and d["job"]["job_id"] == jid
    with pytest.raises(HpcGatewayError) as ei:
        gw.resolve("pai-b", "abandon")
    assert ei.value.relay_code == "NOT_UNKNOWN"


def test_factory_scx(fake_relay, tmp_path):
    sec = fake_relay.write_secret(tmp_path / "s" / "k")
    seen = []
    gw = make_gateway("scx", scx=ScxConfig.from_mapping(fake_relay.config_mapping(str(sec))), scx_secret_path=str(sec),
                      on_secret=seen.append)
    assert isinstance(gw, ScxHpcGateway) and seen == [fake_relay.secret]
    with pytest.raises(ValueError):
        make_gateway("scx")


def test_static_no_delete_move_overwrite_names():
    """정적(§16.10-1): scx 클라이언트·게이트웨이에 삭제·이동·덮어쓰기 계열 이름이 없다."""
    bad = ("delete", "remove", "unlink", "rmdir", "rmtree", "move", "rename", "overwrite", "copy_within", "upload_new")
    for f in ("scx.py", "scx_client.py", "scx_naming.py"):
        tree = ast.parse((SRC / f).read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        hits = sorted(x for x in names if any(b in x.lower() for b in bad))
        assert hits == [], (f, hits)
        src = (SRC / f).read_text(encoding="utf-8")
        assert '"DELETE"' not in src and '"PUT"' not in src and '"PATCH"' not in src


@pytest.mark.parametrize("raw, want", [
    ("Cancelled", ("FINISHED", "CANCELED")), ("canceled", ("FINISHED", "CANCELED")), (" CANCEL ", ("FINISHED", "CANCELED")),
    ("Terminated", ("FINISHED", "CANCELED")), ("KILLED", ("FINISHED", "CANCELED")), ("Deleted", ("FINISHED", "CANCELED")),
    ("Stopped", ("FINISHED", "CANCELED")), ("Aborted", ("FINISHED", "CANCELED")),
    ("Cancelling", ("RUNNING", None)), ("Canceling", ("RUNNING", None)), ("Terminating", ("RUNNING", None)),
    ("Weird", ("UNKNOWN", None)),
])
def test_status_map_cancel_family(fake_relay, tmp_path, raw, want):
    gw = _gw(fake_relay, tmp_path)
    _put(fake_relay, "cushion/01_a/m_0000.rad")
    fake_relay.status_seq = [raw]
    jid = gw.submit_radioss(_req("pai-c", "cushion/01_a")).job_id
    st = gw.status(jid)
    assert (st.state, st.outcome) == want and st.raw_state == raw
