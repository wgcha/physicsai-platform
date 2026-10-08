"""V-CFG-1, V-SEC-4: 설정 검증(§14.3)."""

from __future__ import annotations

import copy

import pytest
import yaml

from physicsai_core.config import load_config, load_config_dict
from physicsai_test_support import REPO


def _issues(d, env=None):
    return load_config_dict(d, environ=env or {}).error_keys()


def test_example_yaml_is_valid_schema(tmp_path):
    """예시 파일은 스키마상 유효하다(ai_root만 이 PC 경로로 바꿔 검증)."""
    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    data["storage"]["ai_root"] = str(tmp_path)
    data["storage"]["allowed_import_roots"] = []
    lc = load_config_dict(data, environ={})
    assert lc.ok, lc.issues
    assert lc.settings.commands.mesh is None and lc.settings.hpc.gateway == "none"


def test_valid_fixture(loaded_config):
    assert loaded_config.ok


@pytest.mark.parametrize(
    "mutate,key",
    [
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(typo_key=1), "typo_key"),
        (lambda d: d["worker"].update(unknown=1), "worker.unknown"),
        (lambda d: d["storage"].update(ai_root="relative/path"), "storage.ai_root"),
        (lambda d: d["storage"].update(ai_root=d["storage"]["ai_root"] + "/missing"), "storage.ai_root"),
        (lambda d: d["storage"].update(spdm_roots=[d["storage"]["ai_root"]]), "storage.ai_root"),
        (lambda d: d["storage"].update(spdm_roots=[d["storage"]["ai_root"] + "/.."]), "storage.ai_root"),
        (lambda d: d["storage"].update(spdm_roots=[d["storage"]["allowed_import_roots"][0]]), "storage.allowed_import_roots[0]"),
        (lambda d: d["altair"].update(edspy_path="relative.bat"), "altair.edspy_path"),
        (lambda d: d["resources"].update(preview_pred_h3d_tcl="/x y/a.tcl"), "resources.preview_pred_h3d_tcl"),
        (lambda d: d["worker"].update(max_logical_cores=0), "worker.max_logical_cores"),
        (lambda d: d["worker"].update(max_memory_gb=5000), "worker.max_memory_gb"),
        (lambda d: d["worker"].update(auto_detect_ratio=1.5), "worker.auto_detect_ratio"),
        (lambda d: d["worker"].update(lease_ttl_s=0.5), "worker.lease_ttl_s"),
        (lambda d: d["worker"].update(limiter="docker"), "worker.limiter"),
        (lambda d: d.update(profile="prod") or d["worker"].update(limiter="null"), "worker.limiter"),
        (lambda d: d["auth"].update(mode="oidc"), "auth.mode"),
        (lambda d: d["auth"].update(cookie_name="bad name"), "auth.cookie_name"),
        (lambda d: d["auth"].update(dashboard_internal_url="ftp:/x"), "auth.dashboard_internal_url"),
        (lambda d: d["dataset"].update(holdout_ratio=0.6), "dataset.holdout_ratio"),
        (lambda d: d["dataset"].update(min_h3d_files=1), "dataset.min_h3d_files"),
        (lambda d: d["training_log"]["parsers"].append({"name": "x", "pattern": "(?P<epoch>\\d+)"}), "training_log.parsers[1]"),
        (lambda d: d["training_log"]["parsers"].append({"name": "x", "pattern": "(unclosed"}), "training_log.parsers[1]"),
        (lambda d: d.update(score={"parsers": [{"name": "s", "pattern": "(?P<name>x)"}]}), "score.parsers[0]"),
        (lambda d: d["commands"].update(edspy_score=None), "commands.edspy_score"),
        (lambda d: d["commands"].update(geom_update=["{simlab}", "{edspy}"]), "commands.geom_update"),
        (lambda d: d["commands"].update(contour_preview=["/usr/bin/hw", "-b"]), "commands.contour_preview"),
        (lambda d: d.update(hpc={"gateway": "pbs"}), "hpc.gateway"),
        (lambda d: d.update(hpc={"transfer": {"collect_mode": "ftp"}}), "hpc.transfer.collect_mode"),
        (lambda d: d.update(predict={"integer_rounding": "banker"}), "predict.integer_rounding"),
    ],
)
def test_validation_failures(settings_dict, mutate, key):
    d = copy.deepcopy(settings_dict)
    mutate(d)
    assert key in _issues(d), _issues(d)


def test_env_overrides(settings_dict):
    lc = load_config_dict(copy.deepcopy(settings_dict), environ={"PHYSICSAI_HPC_GATEWAY": "adapter", "PHYSICSAI_PROFILE": "dev"})
    assert lc.settings.hpc.gateway == "adapter"


def test_prod_requires_existing_executables(settings_dict):
    d = copy.deepcopy(settings_dict)
    d["profile"] = "prod"
    d["altair"]["hyperstudy_path"] = "/nonexistent/hstbatch"
    assert "altair.hyperstudy_path" in _issues(d)


def test_missing_file_and_bad_yaml(tmp_path):
    assert not load_config(str(tmp_path / "none.yaml")).ok
    p = tmp_path / "bad.yaml"
    p.write_text("a: [")
    assert not load_config(str(p)).ok


def test_no_timeout_key_in_schema():
    """V-SM-6: 실행 시간 한도 설정 없음."""
    from physicsai_core.config import WorkerCfg

    assert not [k for k in WorkerCfg.model_fields if "timeout" in k]
