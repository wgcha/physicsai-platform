"""input-kind.md V-IK-1(변환 한 곳)·V-IK-6(능력)·MR-C3 설정 검사: `stage4_predict/input_kind.py` 순수 함수와 `mcp.public_url` 검증."""

from __future__ import annotations

import pytest

from physicsai_core.config import load_config_dict
from physicsai_core.stage4_predict import input_kind as ik


class _Cmds:
    def __init__(self, cushion: list[str] | None) -> None:
        self.paicad_cushion_write = cushion


class _Settings:
    def __init__(self, cushion: list[str] | None = None) -> None:
        self.commands = _Cmds(cushion)


ALT = {"engine": "altair", "input_kind": "assembly", "parameters": [{"name": "THK_1"}]}
ALT_MESH = {"engine": "altair", "input_kind": "mesh_only", "parameters": []}
NAT = {"engine": "native", "input_kind": "assembly", "parameters": [{"name": "A_THK_1"}]}
NAT_PROP = {"engine": "native", "input_kind": "assembly", "parameters": [{"name": "A_THK_1"}, {"name": "T_5", "source": "prop", "prop_id": 5}]}
CMD = ["{paicad}", "cushion", "write"]


def test_conversion_is_one_place_and_roundtrips():
    assert ik.to_internal("cushion") == "mesh_only" and ik.to_internal("assembly") == "assembly"
    assert ik.to_internal(None) == "assembly" and ik.to_internal("weird") == "assembly"  # 생략·모름 = 하위호환
    assert ik.to_public("mesh_only") == "cushion" and ik.to_public("assembly") == "assembly" and ik.to_public(None) == "assembly"
    for v in ik.INPUTS:
        assert ik.to_public(ik.to_internal(v)) == v
    assert (ik.text_of("cushion"), ik.text_of("assembly"), ik.text_of(None)) == ("쿠션", "조립", "조립")


def test_capability_matrix():
    assert ik.capability(ALT, _Settings()) == (["assembly", "cushion"], None)  # Altair는 명령 키와 무관
    assert ik.capability(ALT_MESH, _Settings()) == (["cushion"], ik.REASON_CUSHION_ONLY)
    assert ik.capability(NAT, _Settings(CMD), native_kind="solid") == (["assembly", "cushion"], None)
    assert ik.capability(NAT, _Settings(None), native_kind="solid") == (["assembly"], ik.REASON_CUSHION_CMD)  # null = Native 쿠션 비활성
    assert ik.capability(NAT, _Settings(CMD), native_kind="shell") == (["assembly"], ik.REASON_SHELL)
    assert ik.capability(NAT, _Settings(CMD), native_kind="solid", shell_only=True) == (["assembly"], ik.REASON_SHELL)
    assert ik.capability(NAT_PROP, _Settings(CMD), native_kind="solid") == (["assembly"], ik.REASON_SHELL_THICKNESS)  # 3S 쉘 두께 값
    assert ik.capability({"engine": None, "input_kind": "assembly"}, object()) == (["assembly", "cushion"], None)  # 설정 판에 키가 없어도 Altair는 안전


def test_cushion_write_flag_missing_key_means_not_configured():
    class NoKey:
        commands = object()

    assert ik.cushion_write_configured(NoKey()) is False and ik.cushion_write_configured(_Settings(CMD)) is True


def test_pick_default_rule_and_unsupported():
    both, only_cushion, only_assembly = ["assembly", "cushion"], ["cushion"], ["assembly"]
    assert ik.pick(None, both) == "assembly" and ik.pick(None, only_cushion) == "cushion" and ik.pick(None, only_assembly) == "assembly"
    assert ik.pick("cushion", both) == "cushion" and ik.pick("assembly", both) == "assembly"
    assert ik.pick("assembly", only_cushion) is None and ik.pick("cushion", only_assembly) is None and ik.pick(None, []) is None
    msg = ik.unsupported_message("assembly", ik.REASON_CUSHION_ONLY)
    assert "조립 입력을 쓸 수 없습니다" in msg and ik.REASON_CUSHION_ONLY in msg
    assert ik.unsupported_message("cushion", None).endswith("쓸 수 없습니다")


def test_prepared_and_run_value():
    assert ik.of_prepared("EPS_mesh_0000.rad") == "cushion" and ik.of_prepared("model_0000.rad") == "assembly"
    assert ik.of_prepared(None) == "assembly"
    # 단건 실행 값: params.template_kind → result.template_kind → 템플릿 순
    assert ik.of_run({"template_kind": "mesh_only"}, {"template_kind": "assembly"}, "assembly") == "cushion"
    assert ik.of_run({}, {"template_kind": "mesh_only"}, "assembly") == "cushion"
    assert ik.of_run({}, {}, "mesh_only") == "cushion" and ik.of_run({}, {}, None) == "assembly"
    # prepared의 params.input_kind(file|dir)는 입력 종류가 아니다
    assert ik.of_run({"input_mode": "prepared", "input_kind": "dir", "starter_name": "EPS_mesh_0000.rad"}, {}, "assembly") == "cushion"
    assert ik.of_run({"input_mode": "prepared", "input_kind": "file"}, {"starter": "a.rad"}, "mesh_only") == "assembly"


def test_cushion_missing_warning_only_when_names():
    assert ik.cushion_missing_warning([]) is None
    w = ik.cushion_missing_warning(["MaxStress", "Disp"])
    assert w and w["code"] == "INPUT_CUSHION_RESPONSES" and "MaxStress, Disp" in w["message"] and ik.MESSAGE_CUSHION_RESPONSES in w["message"]
    assert "외 2개" in ik.cushion_missing_warning([f"R{i}" for i in range(7)])["message"]


# ---- MR-C3: mcp.public_url 설정 검사 ---------------------------------------------------------------------


@pytest.mark.parametrize("url", ["https://host/physicsai/mcp", "http://10.0.0.5:8100/physicsai/mcp/", "https://a.b.c/mcp"])
def test_public_url_accepts(url):
    lc = load_config_dict({"mcp": {"public_url": url}}, environ={})
    assert "mcp.public_url" not in lc.error_keys() and lc.settings.mcp.public_url == url


@pytest.mark.parametrize("url", ["", " https://h/mcp", "ftp://h/mcp", "https://h/physicsai", "https://h/mcp?x=1", "https://h/mcp#a",
                                 "https://user:pw@h/mcp", "https://h/m cp", "//h/mcp", "https://h:99999/mcp", "https:///mcp"])
def test_public_url_rejects(url):
    assert "mcp.public_url" in load_config_dict({"mcp": {"public_url": url}}, environ={}).error_keys(), url


def test_public_url_default_null():
    assert load_config_dict({}, environ={}).settings.mcp.public_url is None
