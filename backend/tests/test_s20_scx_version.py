"""S20(D3-68) SCX Radioss 버전 작업별 입력 — V3-S20-1(설정 기본 26.1)·V3-S20-2(version pattern·trim·빈 값 null)·
V3-S20-5 중 openapi 모양(StatusHpc.scx_version·FvHpc.version). /status 값·워커는 worker/tests/stage1_train_data/test_s20_scx_version."""

from __future__ import annotations

import copy
import json

import pytest
import yaml
from pydantic import ValidationError

from physicsai_core.config import load_config_dict
from physicsai_test_support import REPO, scx_hpc_cfg


def _cfg(settings_dict, hpc):
    d = copy.deepcopy(settings_dict)
    d["hpc"] = hpc
    return load_config_dict(d, environ={})


# ---- V3-S20-1 설정 기본 -------------------------------------------------------------------------------------------


def test_v3_s20_1_default_version(settings_dict, fake_relay, tmp_path):
    from physicsai_core.config.schema_hpc import HpcScxCfg

    assert HpcScxCfg().version == "26.1" and HpcScxCfg().appliance == ""
    assert load_config_dict(settings_dict, environ={}).settings.hpc.scx.version == "26.1"
    ex = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert ex["hpc"]["scx"]["version"] == "26.1" and ex["hpc"]["scx"]["appliance"] == ""
    row = next(ln for ln in (REPO / "docs" / "manual" / "admin.md").read_text(encoding="utf-8").splitlines()
               if ln.startswith("| `appliance` / `version` |"))
    assert '`""`(필수) / `"26.1"`' in row
    # scx 설정에서 version 키를 빼면 기본 26.1로 통과
    hpc = scx_hpc_cfg(fake_relay, tmp_path)
    hpc["scx"].pop("version")
    lc = _cfg(settings_dict, hpc)
    assert lc.ok, lc.issues
    assert lc.settings.hpc.scx.version == "26.1"
    # 빈 문자열이면 기존 필수 누락 오류 그대로
    lc = _cfg(settings_dict, scx_hpc_cfg(fake_relay, tmp_path, version=""))
    msgs = [i.message for i in lc.issues if i.key.startswith("hpc.scx")]
    assert not lc.ok and any("version은 필수" in m for m in msgs), msgs
    # appliance는 여전히 필수
    lc = _cfg(settings_dict, scx_hpc_cfg(fake_relay, tmp_path, appliance=""))
    assert not lc.ok and any("appliance" in i.message for i in lc.issues)


# ---- V3-S20-2 HpcOverrides·FvHpc version ----------------------------------------------------------------------------

OK = [("26.1", "26.1"), ("2026.1", "2026.1"), ("  26.1  ", "26.1"), ("2026 R1", "2026 R1"), ("v26_1-hf.2", "v26_1-hf.2"),
      ("A" * 64, "A" * 64), ("", None), ("   ", None), (None, None)]
BAD = ["-26", ".1", " _x", "26;1", "26/1", "26$1", "26\\1", "버전", "26\t1", "A" * 65, 26.1, 5]


def _models():
    from physicsai_api.schemas.fem_verify_req import FvHpc
    from physicsai_api.services.job_params.base import HpcOverrides

    return [HpcOverrides, FvHpc]


@pytest.mark.parametrize("raw,want", OK)
def test_v3_s20_2_version_accept(raw, want):
    for M in _models():
        assert M(version=raw).version == want, (M.__name__, raw)


@pytest.mark.parametrize("raw", BAD)
def test_v3_s20_2_version_reject(raw):
    for M in _models():
        with pytest.raises(ValidationError) as ei:
            M(version=raw)
        assert ei.value.errors()[0]["loc"] == ("version",), (M.__name__, raw)


def test_v3_s20_2_missing_is_null_and_dumped():
    for M in _models():
        m = M()
        assert m.version is None and m.model_dump()["version"] is None
        assert M(ncpus=4).model_dump() == {"queue": None, "ncpus": 4, "walltime": None, "version": None}
    from physicsai_api.schemas.fem_verify_req import FemVerifyCreate

    b = FemVerifyCreate.model_validate({"source": {"kind": "predict_job", "job_id": "j"}, "hpc": {"version": " 2026.1 "}})
    assert b.hpc is not None and b.hpc.version == "2026.1"


# ---- V3-S20-5 openapi 모양 ---------------------------------------------------------------------------------------


def test_v3_s20_5_openapi_shape():
    spec = json.loads((REPO / "backend" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]
    sv = sch["StatusHpc"]["properties"]["scx_version"]
    assert {"type": "null"} in sv["anyOf"]
    assert "scx_version" not in sch["StatusHpc"].get("required", [])
    fv = sch["FvHpc"]["properties"]["version"]
    assert {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}$"} in fv["anyOf"]


# ---- V3-S20-8 보강 1: mpi 기본 Pure MPI·목록 밖 값 설정 경고 ----------------------------------------------------------


def test_v3_s20_8_mpi_default_and_warning(settings_dict, fake_relay, tmp_path):
    from physicsai_core.config.schema_hpc import SCX_MPI_KNOWN, HpcScxCfg

    assert HpcScxCfg().mpi == "Pure MPI"
    assert SCX_MPI_KNOWN == ("SMP (default)", "Pure MPI", "Hybrid 2 Threads", "Hybrid 4 Threads", "Hybrid 8 Threads", "auto")
    ex = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert ex["hpc"]["scx"]["mpi"] == "Pure MPI"
    row = next(ln for ln in (REPO / "docs" / "manual" / "admin.md").read_text(encoding="utf-8").splitlines()
               if ln.startswith("| `queue_type` / `run_type` / `mpi`"))
    assert "/ `Pure MPI` /" in row and "SMP (default)" in row and "`auto`" in row
    hpc = scx_hpc_cfg(fake_relay, tmp_path)
    hpc["scx"].pop("mpi")
    assert _cfg(settings_dict, hpc).settings.hpc.scx.mpi == "Pure MPI"

    def mpi_warns(value):
        lc = _cfg(settings_dict, scx_hpc_cfg(fake_relay, tmp_path, mpi=value))
        assert lc.ok, lc.issues  # 경고일 뿐 오류 아님
        return [w for w in lc.warnings if w.key == "hpc.scx.mpi"]

    for ok in SCX_MPI_KNOWN:
        assert mpi_warns(ok) == [], ok
    got = mpi_warns("Hybrid 16 Threads")
    assert len(got) == 1 and got[0].message == "hpc.scx.mpi가 알려진 값이 아닙니다: Hybrid 16 Threads"
