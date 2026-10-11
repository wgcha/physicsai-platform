"""패키지 단독 시험 공용 픽스처(플랫폼·PostgreSQL 없이 실행)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FAKE = str(HERE / "fake_pbs.py")
PY = sys.executable


def command_mapping(**over):
    d = {
        "allowed_executables": [PY],
        "submit": [PY, FAKE, "qsub", "-N", "{job_name}", "-q", "{queue}", "-l", "select=1:ncpus={ncpus}", "-l",
                   "walltime={walltime}", "-v", "INPUT_FILE={input_file},RESULT_DIR={result_dir}", "-W", "{input_dir}:{run_key}:{study}",
                   "/shared/scripts/run.pbs"],
        "status": [PY, FAKE, "qstat", "-x", "-f", "{external_job_id}"],
        "cancel": [PY, FAKE, "qdel", "{external_job_id}"],
        "job_id_regex": r"^\s*(?P<job_id>\d+(?:\.[A-Za-z0-9_.\-]+)?)\s*$",
        "state_regex": r"job_state\s*=\s*(?P<state>[A-Z])",
        "exit_code_regex": r"Exit_status\s*=\s*(?P<exit>-?\d+)",
        "not_found_regex": "Unknown Job Id",
        "state_map": {"Q": "QUEUED", "R": "RUNNING", "F": "FINISHED"},
        "submit_timeout_s": 30, "status_timeout_s": 30, "cancel_timeout_s": 30,
    }
    d.update(over)
    return d


DEFAULTS = {"queue": "workq", "ncpus": 16, "walltime": "24:00:00"}


class PbsState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.mode = "ok"

    def env(self) -> dict[str, str]:
        e = dict(os.environ)
        e["FAKE_PBS_STATE"] = str(self.path)
        e["FAKE_TOOL_MODE_PBS"] = self.mode
        return e

    def calls(self) -> list[list[str]]:
        return json.loads(self.path.read_text(encoding="utf-8"))["calls"] if self.path.exists() else []


@pytest.fixture()
def cmd_mapping():
    """command 설정 dict를 만드는 함수(키 덮어쓰기 가능)."""
    return command_mapping


@pytest.fixture()
def defaults_mapping():
    return dict(DEFAULTS)


@pytest.fixture()
def pbs(tmp_path):
    return PbsState(tmp_path / "pbs_state.json")
