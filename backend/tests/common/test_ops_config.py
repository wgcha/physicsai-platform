"""운영 설정 정리: 예약(미사용) 키 경고, 예시 일부만 복사해도 기동(누락 → 해당 기능만 비활성)."""

from __future__ import annotations

import copy

import httpx
import yaml
from fastapi.testclient import TestClient

from physicsai_test_support import API, REPO, H


def _lc(d):
    from physicsai_core.config import load_config_dict

    return load_config_dict(d, environ={})


def test_reserved_keys_warn_not_error(settings_dict):
    d = copy.deepcopy(settings_dict)
    d["server"]["base_path"] = "/other"
    d["hpc"] = {"gateway": "none", "transfer": {"stage_in": "shared_path"}, "adapter": {"module": "x.y"}}
    lc = _lc(d)
    assert lc.ok, lc.issues
    assert {w.key for w in lc.warnings} >= {"server.base_path", "hpc.transfer.stage_in", "hpc.adapter.module"}
    assert not {w.key for w in _lc(settings_dict).warnings} & {"server.base_path", "hpc.transfer.stage_in", "hpc.adapter.module"}


def test_example_has_no_reserved_keys():
    ex = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert "base_path" not in ex["server"] and "stage_in" not in ex["hpc"]["transfer"] and "adapter" not in ex["hpc"]


def test_partial_example_starts_with_features_disabled(tmp_path, engine):
    """예시에서 storage·altair 일부만 복사: 설정 오류 없이 기동, 명령 템플릿이 없는 기능만 비활성 + 작업 생성 409."""
    from physicsai_api.context import build_context
    from physicsai_api.main import create_app

    ai = tmp_path / "ai"
    ai.mkdir()
    d = {"schema_version": 1, "profile": "dev", "auth": {"mode": "dev_static",
                                                          "dev_static_principal": {"memberships": [{"project_id": "p", "role": "power"}]}},
         "storage": {"ai_root": str(ai)}}
    lc = _lc(d)
    assert lc.ok, lc.issues
    keys = {w.key for w in lc.warnings}
    assert {"commands.edspy_create_dataset", "commands.edspy_score", "commands.edspy_predict", "commands.contour_preview",
            "worker.gpu_query"} <= keys
    with TestClient(create_app(build_context(lc, engine)), base_url="http://127.0.0.1") as c:
        st = c.get(f"{API}/status").json()
        assert st["config"]["ok"] and "commands.edspy_score" in st["config"]["warnings"]
        assert st["features"]["dataset_create"] == {"enabled": False, "missing": ["commands.edspy_create_dataset"]}
        assert st["features"]["predict"]["enabled"] is False and st["features"]["evaluate"]["enabled"] is False
        sid = c.post(f"{API}/studies", headers=H("x", write=True), json={"project_id": "p", "folder_name": "s1", "title": "t"}).json()["id"]
        (ai / "s1" / "00_inbox" / "h").mkdir(parents=True)
        r = c.post(f"{API}/studies/{sid}/jobs", headers=H("x", write=True),
                   json={"job_type": "DATASET_CREATE", "params": {"input_path": str(ai / "s1" / "00_inbox" / "h")}})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"


def test_explicit_null_required_template_still_error(settings_dict):
    """V2-CFG-1 유지: 1차 확정 템플릿을 명시적으로 null로 쓰면 설정 오류(누락과 구분)."""
    d = copy.deepcopy(settings_dict)
    d["commands"]["edspy_score"] = None
    assert "commands.edspy_score" in _lc(d).error_keys()


def test_hpc_command_missing_disables_solve_only(settings_dict, engine):
    from physicsai_api.context import build_context

    d = copy.deepcopy(settings_dict)
    d["hpc"] = {"gateway": "command"}
    lc = _lc(d)
    assert lc.ok, lc.issues
    assert "hpc.command" in {w.key for w in lc.warnings}
    ctx = build_context(lc, engine, transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    assert ctx.hpc.availability().configured is False
    d["hpc"] = {"gateway": "command", "command": {"submit": "qsub"}}  # 있는데 틀리면 여전히 오류
    assert "hpc.command" in _lc(d).error_keys()
