"""조립 매칭 시험 공용(asm-match.md): include 트리 조립 폴더 생성 + API 흐름(생성 → 목록 → 행 → 검사 → 확정) 도우미.

c = TestClient, w = Worker(PREVIEW 레인 작업은 `run_once_preview`). ROWS는 가짜 paicad(fake_paicad_asm)의 바디 A·B ↔ PART 3000001·3000002.
"""

from __future__ import annotations

from pathlib import Path

from physicsai_test_support import API, H

PW, P = H("tok-power", write=True), H("tok-power")


def job(c, jid):
    return c.get(f"{API}/jobs/{jid}", headers=P).json()


STARTER = "MODEL_0000.rad"


def make_tree(d: Path) -> Path:
    """include 트리 조립 폴더: starter가 하위 폴더 파일까지 #include. 기준본·RENUM 표 없음. unused.inc는 트리 밖."""
    (d / "nodes").mkdir(parents=True, exist_ok=True)
    (d / STARTER).write_text("#RADIOSS STARTER\n/BEGIN\nmodel\n#include 101_parts.inc\n#include nodes/102_nodes.inc\n/END\n")
    (d / "101_parts.inc").write_text("/PART/3000001\nCUSH_A\n/PART/3000002\nCUSH_B\n/PART/3000009\nPLATE\n")
    (d / "nodes" / "102_nodes.inc").write_text("/NODE\n 1 0 0 0\n/TETRA4/3000001\n 1 1 1 1 1\n/TETRA4/3000002\n 2 1 1 1 1\n/SHELL/3000009\n 3 1 1 1 1\n")
    (d / "unused.inc").write_text("not in the include tree\n")
    return d


def _create(c, sid, asm: Path, cad: dict, expect=202):
    r = c.post(f"{API}/studies/{sid}/asm-matches", headers=PW, json={"radioss_assem_path": str(asm), "cad": cad})
    assert r.status_code == expect, r.text
    return r.json()


def _get(c, mid):
    r = c.get(f"{API}/asm-matches/{mid}", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def _scan(c, w, sid, asm, cad=None):
    out = _create(c, sid, asm, cad or {"kind": "train"})
    st = w.run_once_preview()
    assert st == "SUCCEEDED", (job(c, out["job_id"]).get("failure_code"), job(c, out["job_id"]).get("failure_message"))
    return out["match_id"]


ROWS = {"rows": [{"body": "A", "pids": [3000001]}, {"body": "B", "pids": [3000002]}], "excluded_bodies": []}


def _check(c, w, mid, expect="SUCCEEDED"):
    r = c.post(f"{API}/asm-matches/{mid}/check", headers=PW)
    assert r.status_code == 202, r.text
    assert w.run_once_preview() == expect, job(c, r.json()["job_id"])
    return r.json()


def _confirmed(c, w, sid, asm, cad=None) -> str:
    mid = _scan(c, w, sid, asm, cad)
    assert c.put(f"{API}/asm-matches/{mid}/rows", headers=PW, json=ROWS).status_code == 200
    _check(c, w, mid)
    r = c.post(f"{API}/asm-matches/{mid}/confirm", headers=PW)
    assert r.status_code == 200 and r.json()["state"] == "CONFIRMED", r.text
    return mid


