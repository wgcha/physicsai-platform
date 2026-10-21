"""upload-report.md V-RP 단위·정적: 영향도 골든(1e-9)·이스케이프·결정성·크기 상한(413)·행 상한 500·그림 규칙·파일 이름·외부 프로그램 없음."""

from __future__ import annotations

import ast
import base64
import json
import re
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from physicsai_api.services import reports as svc
from physicsai_api.services import reports_common as rc
from physicsai_core.errors import DomainError
from physicsai_core.report_html import analysis as ra
from physicsai_core.report_html.influence import avg_ranks, compute_influence
from physicsai_core.report_html.page import Ctx, Doc, Limits, assemble, limits_from, render, BUDGETS
from report_support import FILENAME_RE, assert_no_external, parse_data

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "frontend" / "src" / "__tests__" / "fixtures" / "influenceGolden.json"
AT = datetime(2026, 10, 22, 9, 5, tzinfo=timezone.utc)
STAMP = {"generated_at": "2026-10-22T09:05:00+00:00", "platform_version": "0.2.5"}
EVIL = '<script>alert(1)</script>"\'&</script><img src=x onerror=1>'


def _png(path: Path, size: int = 0) -> Path:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = zlib.compress(b"\x00\xff\x00\x00")
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
                     + b"\0" * size)
    return path


def _table(n: int = 8, label: str = "DOE-001", names: tuple[str, ...] = ("a", "b"), resp: str = "y") -> dict:
    rows = [{"run_id": f"run__{i:05d}", "no": i, "state": "COLLECTED", "params": {"a": float(i), "b": float(i * i % 7)},
             "responses": {resp: 2.0 * i + (i * i % 7) + (0.3 if i % 2 else 0.0)}, "curve": None} for i in range(1, n + 1)]
    return {"source": "solver", "origin": {"kind": "train_doe", "id": "d0000000-0", "label": label},
            "parameters": [{"name": x, "integer": False, "min": 0.0, "max": 10.0, "unit": None} for x in names],
            "responses": [{"name": resp, "unit": "MPa"}], "meta": {"engine_version": None, "baseline_id": None, "scene": None}, "rows": rows,
            "counts": {"total": n, "usable": n, "no_response": 0}, "influence": {"ok": True, "cls": "formal", "note": None, "reason": None},
            "notes": [], "sampling": {"label": "LHS", "lhs": True, "kind": "lhs"}}


def _inp(rt: dict, **kw) -> dict:
    return {"study": {"id": "s1", "title": "스터디", "folder_name": "S"}, "generated_by": "파워", "table": rt, "other": None, "vars": None,
            "resp": None, "warnings": [], "curves": None, "origins": [], "engine": {}, "param_set": None, "model": None, **kw}


def _render(inp: dict, limits: Limits | None = None) -> bytes:
    return render(lambda ctx: ra.analysis_doc(inp, ctx), limits or Limits(), **STAMP)


# ---- V-RP-4: 영향도 = 프런트 골든 ---------------------------------------------------------------------------


def test_v_rp_4_influence_matches_frontend_golden():
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert g["cases"], "골든 사례 없음"
    for c in g["cases"]:
        r = compute_influence(c["names"], c["cols"], c["y"])
        for key, got in (("prcc", r.prcc), ("src", r.src)):
            assert len(got) == len(c[key]), (c["name"], key)
            for a, b in zip(got, c[key]):
                if b is None:
                    assert a is None, (c["name"], key)
                else:
                    assert a == pytest.approx(b, abs=1e-9), (c["name"], key)
        if c["r2"] is None:
            assert r.r2 is None
        else:
            assert r.r2 == pytest.approx(c["r2"], abs=1e-9), c["name"]


def test_v_rp_4_avg_ranks_ties_average():
    assert list(avg_ranks([3.0, 1.0, 3.0, 2.0])) == [3.5, 1.0, 3.5, 2.0]


# ---- V-RP-5: 이스케이프·결정성 --------------------------------------------------------------------------------


def test_v_rp_5_user_strings_escaped_everywhere():
    rt = _table(label=EVIL, names=("a", "b"), resp="y")
    rt["parameters"][0]["name"] = "a"
    rt["responses"][0]["name"] = "y"
    rt["responses"][0]["unit"] = EVIL
    rt["rows"][0]["run_id"] = EVIL
    rt["notes"] = [EVIL]
    inp = _inp(rt, study={"id": "s1", "title": EVIL, "folder_name": EVIL}, generated_by=EVIL, warnings=[EVIL])
    doc = _render(inp).decode()
    assert "<script>alert" not in doc and "<img src=x" not in doc                 # 원문 태그 없음
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in doc                          # 화면에는 글자 그대로
    assert doc.count("<script") == 2                                               # 데이터 JSON + 테마 JS 뿐
    assert "</script>" in doc and doc.count("</script>") == 2
    assert_no_external(doc)
    parse_data(doc)                                                                # inline JSON은 여전히 유효


def test_v_rp_5_json_script_breakout_blocked():
    rt = _table()
    rt["origin"]["label"] = "</script><script>alert(1)</script><!--"
    doc = _render(_inp(rt)).decode()
    assert doc.count("<script") == 2 and "</script><script>alert" not in doc
    parse_data(doc)


def test_v_rp_5_deterministic_bytes():
    inp = _inp(_table(30))
    a, b = _render(inp), _render(inp)
    assert a == b and len(a) > 1000


# ---- V-RP-6: 크기 상한·행 상한 ------------------------------------------------------------------------------


def test_v_rp_6_too_large_413():
    with pytest.raises(DomainError) as e:
        _render(_inp(_table(20)), Limits(max_bytes=2000))
    assert e.value.status == 413 and e.value.code == "REPORT_TOO_LARGE"


def test_v_rp_6_budget_shrinks_before_failing():
    inp = _inp(_table(400))
    full = len(_render(inp))
    out = _render(inp, Limits(max_bytes=int(full * 0.6)))                          # 행·점을 줄여 상한 안으로
    assert len(out) <= int(full * 0.6) and len(out) < full
    assert len(BUDGETS) >= 3


def test_v_rp_4_table_row_cap_500():
    rt = _table(620)
    doc = _render(_inp(rt)).decode()
    assert "run__00500" in doc and "run__00501" not in doc.split('<section id="table">')[1].split("</section>")[0]
    assert "앞 500행만 표시합니다(전체 620행)" in doc and "결과 표은(는) 상한까지만 표시했습니다" in doc or "상한까지만 표시했습니다" in doc
    small = _render(_inp(rt), Limits(max_table_rows=50)).decode()
    assert "앞 50행만" in small


def test_limits_from_settings_defaults_and_override():
    class S: ...

    assert limits_from(S()) == Limits()
    s = S()
    s.report = type("R", (), {"max_bytes": 5, "max_images": 1, "max_image_bytes": 7, "max_table_rows": 9})()
    assert limits_from(s) == Limits(5, 1, 7, 9)
    assert Limits().max_table_rows == 500 and Limits().max_bytes == 30 * 1024 * 1024


# ---- 그림 규칙(PNG data URI만·상한) ---------------------------------------------------------------------------


def test_image_embed_rules(tmp_path):
    ok = _png(tmp_path / "a.png")
    big = _png(tmp_path / "big.png", size=5000)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"GIF89a....")
    ctx = Ctx(Limits(max_images=2, max_image_bytes=2000), BUDGETS[0], **STAMP)
    h1 = ctx.image(str(ok), "정상")
    assert '<img alt="정상" src="data:image/png;base64,' in h1
    b64 = re.search(r"base64,([A-Za-z0-9+/=]+)\"", h1).group(1)
    assert base64.b64decode(b64) == ok.read_bytes()
    assert "그림 생략" in ctx.image(str(big), "큼") and "그림 생략" in ctx.image(str(bad), "PNG아님")
    assert "그림 생략" in ctx.image(str(tmp_path / "none.png"), "없음")
    assert ctx.images_used == 1 and ctx.images_omitted == 3
    assert ctx.image(str(ok), "둘째").startswith("<figure") and "그림 생략" in ctx.image(str(ok), "셋째")      # 개수 상한 2
    assert ctx.image(None, "x") == ""
    off = Ctx(Limits(), BUDGETS[1], **STAMP)                                                                      # 예산 단계 2 = 그림 없음
    assert "그림 생략" in off.image(str(ok), "예산")


def test_image_omission_is_warned_in_report(tmp_path):
    ctx = Ctx(Limits(max_images=0), BUDGETS[0], **STAMP)
    ctx.image(str(_png(tmp_path / "a.png")), "x")
    doc = assemble(Doc(title="t", meta=[], sections=[("s", "S", "<p>.</p>")]), ctx)
    assert "그림 1장 생략" in doc


# ---- V-RP-2: 파일 이름·헤더 ---------------------------------------------------------------------------------


def test_v_rp_2_filename_rules():
    fn = svc.make_filename("한글 스터디", "analysis-doe", "abcdef0123456789", AT)
    assert fn == "PAI_한글_스터디_analysis-doe_abcdef01_20261022-0905.html" and FILENAME_RE.match(fn)
    bad = svc.make_filename('a/b\\c:d*e?f"g<h>i|j', "equiv-check", "12345678-aaaa", AT)
    assert FILENAME_RE.match(bad) and not any(c in bad[4:-5] for c in '/\\:*?"<>|')
    long = svc.make_filename("가" * 200, "optimization", "abcdef01", AT)
    assert FILENAME_RE.match(long) and len(long) < 40 + 70
    assert FILENAME_RE.match(svc.make_filename("  ..  ", "surrogate-opt", "abcdef01", AT)) and "_study_" in svc.make_filename("", "optimization", "abcdef01", AT)
    h = svc.response_headers(fn, True)
    assert h["Content-Disposition"].startswith("attachment; filename*=UTF-8''PAI_%ED%95%9C%EA%B8%80_%EC%8A%A4%ED%84%B0%EB%94%94_")
    assert "Content-Disposition" not in svc.response_headers(fn, False)
    assert {"Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Cache-Control"} <= set(h) and h["Cache-Control"] == "no-store"


def test_v_rp_1_page_has_no_external_resource_even_with_hostile_input():
    rt = _table()
    rt["origin"]["label"] = "http://evil.example/x url(http://e) @import <link href=//e>"
    doc = _render(_inp(rt)).decode()
    assert "http://evil" not in doc.replace("&#x27;", "'") or "&lt;" in doc            # 값으로 나올 때도 글자일 뿐
    for m in re.finditer(r"<(link|iframe|object|embed|form|base)\b", doc, re.I):
        pytest.fail(m.group(0))
    assert re.search(r'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'', doc.replace("&#x27;", "'"))


# ---- 업로드 출처 문구 ---------------------------------------------------------------------------------------


def test_origin_text_uploaded_folder(tmp_path):
    ctx = type("C", (), {"settings": type("S", (), {"storage": type("St", (), {"ai_root": str(tmp_path)})()})()})()
    rows = [{"dir_rel": "S1/00_inbox/uploads/u1", "at": datetime(2026, 10, 21, 14, 2), "username": "홍길동"}]
    p = str(tmp_path / "S1" / "00_inbox" / "uploads" / "u1" / "model" / "a.step")
    assert rc.origin_text(ctx, rows, p) == "내 PC에서 올림 · 10-21 14:02 · 홍길동"
    assert rc.origin_text(ctx, rows, str(tmp_path / "S1" / "00_inbox" / "other")) is None
    assert rc.origin_text(ctx, rows, None) is None and rc.origin_text(ctx, [], p) is None


# ---- V-RP-7: 외부 프로그램 실행 없음 ---------------------------------------------------------------------------

FILES = [*sorted((REPO / "backend" / "physicsai_core" / "report_html").glob("*.py")),
         *sorted((REPO / "backend" / "physicsai_api" / "services").glob("reports*.py")), REPO / "backend" / "physicsai_api" / "routers" / "reports.py"]
BANNED_MODULES = {"subprocess", "multiprocessing", "pty", "pexpect", "shlex"}
BANNED_CALLS = {"system", "popen", "Popen", "run", "spawn", "spawnl", "spawnv", "execv", "execl", "check_output", "check_call", "call", "startfile", "fork"}


def test_v_rp_7_no_external_program_in_report_code():
    assert len(FILES) >= 10
    for f in FILES:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                assert not {a.name.split(".")[0] for a in n.names} & BANNED_MODULES, f"{f.name}:{n.lineno}"
            elif isinstance(n, ast.ImportFrom):
                assert (n.module or "").split(".")[0] not in BANNED_MODULES, f"{f.name}:{n.lineno}"
                assert not {a.name for a in n.names} & {"Popen", "check_output", "system"}, f"{f.name}:{n.lineno}"
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id in ("os", "subprocess"):
                assert n.func.attr not in BANNED_CALLS, f"{f.name}:{n.lineno}"
        assert "shell=True" not in f.read_text(encoding="utf-8")


def test_v_rp_7_no_network_or_storage_writes_in_report_code():
    for f in FILES:
        src = f.read_text(encoding="utf-8")
        for pat in (r"\brequests\b", r"\bhttpx\b", r"urllib\.request", r"\bsocket\b", r"open\([^)]*[\"']w", r"write_text\(", r"write_bytes\("):
            assert not re.search(pat, src), (f.name, pat)
