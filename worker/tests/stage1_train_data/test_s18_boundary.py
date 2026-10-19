"""V3-S18-8: 형상 생성 경계(phase3 §23.6, D3-66) — `geom_update` 명령을 실행하는 곳은 `steps/run_chain.py` 한 파일뿐,
엔진 선택은 `select_engine` 한 곳(지금 altair). ④ V3-S9 시험은 무수정 통과(별도 파일)."""

from __future__ import annotations

import re
from pathlib import Path

import physicsai_worker
from physicsai_worker.steps import run_chain

ROOT = Path(physicsai_worker.__file__).resolve().parent
LITERAL = re.compile(r"""["']geom_update["']""")


def test_v3_s18_8_geom_update_command_only_in_run_chain():
    hits = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*.py") if LITERAL.search(p.read_text(encoding="utf-8")))
    assert hits == ["steps/run_chain.py"]
    src = (ROOT / "steps" / "run_chain.py").read_text(encoding="utf-8")
    assert 'GEOM_TEMPLATE = "geom_update"' in src and src.count("runner.run(GEOM_TEMPLATE") == 1


def test_v3_s18_8_engine_selection_single_point(monkeypatch):
    assert run_chain.select_engine(None).name == "altair"
    calls: list[str] = []
    fake = run_chain.Engine("native", lambda *a, **k: calls.append("geom") or "g",
                            lambda *a, **k: calls.append("build") or "b")
    monkeypatch.setattr(run_chain, "select_engine", lambda settings, param_set=None: fake)
    assert run_chain.geometry_update(None, None, work_dir="w", rendered_script="r", cad_file="c") == "g"
    assert run_chain.build_run_inputs(None, None, run_dir="d", cad_file_name="c", assem_dir=None, assembly=False) == "b"
    assert calls == ["geom", "build"]
