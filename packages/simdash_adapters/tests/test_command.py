"""V3-S4-3: command 게이트웨이 — 설정 검증 문구 골든, render_argv 값 규칙, 가짜 PBS로 submit/status/cancel, make_gateway 분기."""

from __future__ import annotations

import logging
import sys

import pytest

from simdash_adapters import (
    AdapterHpcGateway,
    CommandConfig,
    CommandHpcGateway,
    HpcDefaults,
    HpcGatewayError,
    HpcSubmitSpec,
    NoneHpcGateway,
    make_gateway,
    render_argv,
    validate_command_config,
)

SPEC = dict(job_name="s_1_a1", run_key="verify", study="s", input_file="/shared/a.rad", input_dir="/shared",
            result_dir="/shared/r", queue=None, ncpus=None, walltime=None)


def _gw(cmd_mapping, defaults_mapping, pbs, **over):
    return CommandHpcGateway(CommandConfig.from_mapping(cmd_mapping(**over)), HpcDefaults.from_mapping(defaults_mapping),
                             env_factory=pbs.env)


def test_valid_config_has_no_problems(cmd_mapping):
    assert validate_command_config(CommandConfig.from_mapping(cmd_mapping())) == []


def test_validation_messages_golden(cmd_mapping):
    """현행(physicsai_core.hpc.command) 문구 그대로."""
    cfg = CommandConfig.from_mapping(cmd_mapping(
        allowed_executables=["relative/qsub", "C:/PBS/qsub.bat", "/opt/pbs/bin/qstat"],
        submit="qsub -N x",
        status=["C:/PBS/qsub.bat", "{external_job_id}"],
        cancel=["/opt/pbs/bin/qstat", "{evil}", "{job_name:>5}", "{bad"],
        job_id_regex=None,
        state_regex="(?P<other>x)",
        exit_code_regex="(",
        not_found_regex=None,
        state_map={"Q": "QUEUED", "X": "DONE"},
    ))
    assert validate_command_config(cfg) == [
        "allowed_executables 항목은 절대경로여야 합니다: relative/qsub",
        ".bat·.cmd·.ps1은 허용되지 않습니다: C:/PBS/qsub.bat",
        "submit는 문자열 배열이어야 합니다",
        "status argv[0]에 .bat·.cmd·.ps1은 쓸 수 없습니다",
        "cancel: 허용되지 않는 placeholder '{evil}'",
        "cancel: 허용되지 않는 placeholder '{job_name}'",
        "cancel: 템플릿 형식 오류 expected '}' before end of string",
        "job_id_regex는 필수입니다",
        "state_regex에 그룹 'state'이 없습니다",
        "exit_code_regex 정규식 오류: missing ), unterminated subpattern at position 0",
        "state_map[X]은 QUEUED|RUNNING|FINISHED",
    ]


def test_validation_argv0_rules(cmd_mapping):
    cfg = CommandConfig.from_mapping(cmd_mapping(status=["qstat", "{external_job_id}"], cancel=["/usr/bin/qdel"], submit=[]))
    assert validate_command_config(cfg) == [
        "submit는 문자열 배열이어야 합니다",
        "status argv[0]은 절대경로여야 합니다",
        "status argv[0]이 allowed_executables에 없습니다",
        "cancel argv[0]이 allowed_executables에 없습니다",
    ]


def test_validate_accepts_attribute_objects(cmd_mapping):
    class Obj:
        pass

    o = Obj()
    for k, v in cmd_mapping(submit=None).items():
        setattr(o, k, v)
    assert validate_command_config(o) == ["submit는 문자열 배열이어야 합니다"]


@pytest.mark.parametrize("field,bad,code", [
    ("job_name", "a;rm", "SUBMIT_FAILED"), ("job_name", "a\nb", "SUBMIT_FAILED"), ("job_name", "x" * 65, "SUBMIT_FAILED"),
    ("input_file", "/a/$(id)", "SUBMIT_FAILED"), ("input_dir", "/a b", "SUBMIT_FAILED"), ("result_dir", "/a&b", "SUBMIT_FAILED"),
    ("queue", "q;x", "SUBMIT_FAILED"), ("walltime", "1h", "SUBMIT_FAILED"), ("ncpus", 5000, "SUBMIT_FAILED"),
    ("ncpus", 0, "SUBMIT_FAILED"), ("run_key", "a/b", "SUBMIT_FAILED"), ("study", "s s", "SUBMIT_FAILED"),
    ("job_name", "y" * 1025, "SUBMIT_FAILED"),
])
def test_render_argv_value_rules(cmd_mapping, field, bad, code):
    cfg = CommandConfig.from_mapping(cmd_mapping())
    vals = {**SPEC, "queue": "workq", "ncpus": 8, "walltime": "01:00:00", field: bad}
    with pytest.raises(HpcGatewayError) as ei:
        render_argv(cfg, "submit", vals)
    assert ei.value.code == code


def test_render_argv_ok_missing_and_job_id(cmd_mapping):
    cfg = CommandConfig.from_mapping(cmd_mapping())
    argv = render_argv(cfg, "submit", {**SPEC, "queue": "workq", "ncpus": 8, "walltime": "01:00:00"})
    assert argv[0] == sys.executable and "select=1:ncpus=8" in argv and "INPUT_FILE=/shared/a.rad,RESULT_DIR=/shared/r" in argv
    with pytest.raises(HpcGatewayError) as ei:
        render_argv(cfg, "submit", {**SPEC, "queue": None, "ncpus": 8, "walltime": "01:00:00"})
    assert ei.value.code == "SUBMIT_FAILED" and str(ei.value) == "'queue' 값이 없습니다"
    with pytest.raises(HpcGatewayError) as ei:
        render_argv(cfg, "status", {"external_job_id": "12345; rm -rf /"})
    assert ei.value.code == "PARSE_FAILED"
    assert render_argv(cfg, "status", {"external_job_id": "12345.pbs01"})[-1] == "12345.pbs01"
    bad = CommandConfig.from_mapping(cmd_mapping(submit="x"))
    with pytest.raises(HpcGatewayError) as ei:
        render_argv(bad, "status", {"external_job_id": "1"})
    assert ei.value.code == "NOT_CONFIGURED"


def test_gateway_submit_status_cancel(cmd_mapping, defaults_mapping, pbs):
    gw = _gw(cmd_mapping, defaults_mapping, pbs)
    assert gw.availability().configured and gw.availability().mode == "command"
    r = gw.submit(HpcSubmitSpec(**SPEC))
    assert r.external_job_id == "12345.pbs01" and r.raw_stdout.strip() == "12345.pbs01"
    sub = pbs.calls()[-1]
    assert sub[0] == "qsub" and sub[sub.index("-q") + 1] == "workq" and "select=1:ncpus=16" in sub and "walltime=24:00:00" in sub
    assert [gw.status(r.external_job_id).state for _ in range(3)] == ["QUEUED", "RUNNING", "FINISHED"]
    st = gw.status(r.external_job_id)
    assert st.exit_code == 0 and st.raw_state == "F" and not st.not_found
    gw.cancel(r.external_job_id)
    assert pbs.calls()[-1] == ["qdel", "12345.pbs01"]


def test_gateway_failure_modes(cmd_mapping, defaults_mapping, pbs):
    gw = _gw(cmd_mapping, defaults_mapping, pbs)
    pbs.mode = "not_found"
    assert gw.status("12345.pbs01").not_found
    pbs.mode = "unknown"
    st = gw.status("12345.pbs01")
    assert st.state == "UNKNOWN" and not st.not_found
    pbs.mode = "submit_fail"
    with pytest.raises(HpcGatewayError) as ei:
        gw.submit(HpcSubmitSpec(**SPEC))
    assert ei.value.code == "SUBMIT_FAILED" and str(ei.value).startswith("제출 실패(종료코드 1): qsub: Unauthorized")
    pbs.mode = "cancel_fail"
    with pytest.raises(HpcGatewayError) as ei:
        gw.cancel("12345.pbs01")
    assert ei.value.code == "UNAVAILABLE" and "Server unreachable" in str(ei.value)


def test_gateway_exit_code_parse_failure_logs(cmd_mapping, defaults_mapping, pbs, caplog):
    log = logging.getLogger("caller.hpc")
    gw = CommandHpcGateway(CommandConfig.from_mapping(cmd_mapping(exit_code_regex=r"job_state\s*=\s*(?P<exit>\w)")),
                           HpcDefaults.from_mapping(defaults_mapping), env_factory=pbs.env, logger=log)
    jid = gw.submit(HpcSubmitSpec(**SPEC)).external_job_id
    with caplog.at_level(logging.WARNING, logger="caller.hpc"):
        st = gw.status(jid)
    assert st.state == "UNKNOWN" and st.exit_code is None and st.raw_state == "Q"
    assert any(r.name == "caller.hpc" and "종료코드 해석 실패" in r.getMessage() for r in caplog.records)
    assert CommandHpcGateway(gw.c, gw.defaults).log.name == "simdash_adapters.hpc.command"


def test_gateway_misconfigured(cmd_mapping, defaults_mapping, pbs):
    gw = _gw(cmd_mapping, defaults_mapping, pbs, submit="qsub -N x")
    av = gw.availability()
    assert not av.configured and av.message == "PBS 명령 설정 오류: submit는 문자열 배열이어야 합니다"
    with pytest.raises(HpcGatewayError) as ei:
        gw.submit(HpcSubmitSpec(**SPEC))
    assert ei.value.code == "NOT_CONFIGURED"


def test_gateway_unavailable_and_timeout(cmd_mapping, defaults_mapping, pbs, tmp_path):
    missing = str(tmp_path / "no_such_qsub")
    gw = _gw(cmd_mapping, defaults_mapping, pbs, allowed_executables=[missing], submit=[missing], status=[missing, "{external_job_id}"],
             cancel=[missing, "{external_job_id}"])
    with pytest.raises(HpcGatewayError) as ei:
        gw.status("1")
    assert ei.value.code == "UNAVAILABLE"
    py = sys.executable
    slow = [py, "-c", "import time; time.sleep(5)", "{external_job_id}"]
    gw = _gw(cmd_mapping, defaults_mapping, pbs, status=slow, status_timeout_s=0.3)
    with pytest.raises(HpcGatewayError) as ei:
        gw.status("1")
    assert ei.value.code == "TIMEOUT"


def test_make_gateway_branches(cmd_mapping, defaults_mapping):
    assert isinstance(make_gateway("none"), NoneHpcGateway)
    assert isinstance(make_gateway("pbs"), NoneHpcGateway)  # 알 수 없는 값 → none
    ad = make_gateway("adapter")
    assert isinstance(ad, AdapterHpcGateway)
    av = ad.availability()
    assert av.mode == "adapter" and not av.configured and av.message == "어댑터 job API 미확인 — 미구현"
    gw = make_gateway("command", CommandConfig.from_mapping(cmd_mapping()), HpcDefaults.from_mapping(defaults_mapping))
    assert isinstance(gw, CommandHpcGateway) and gw.availability().configured
    with pytest.raises(ValueError):
        make_gateway("command")
    none = make_gateway("none")
    assert none.availability().message == "PBS 연결 안 됨"
    for call in (lambda g: g.submit(None), lambda g: g.status("1"), lambda g: g.cancel("1")):
        for g in (none, ad):
            with pytest.raises(HpcGatewayError) as ei:
                call(g)
            assert ei.value.code == "NOT_CONFIGURED"


def test_config_is_frozen_and_requires_all_keys(cmd_mapping, defaults_mapping):
    cfg = CommandConfig.from_mapping(cmd_mapping())
    assert isinstance(cfg.submit, tuple) and isinstance(cfg.allowed_executables, tuple)
    with pytest.raises(Exception):
        cfg.submit = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        CommandConfig.from_mapping({k: v for k, v in cmd_mapping().items() if k != "state_map"})
    with pytest.raises(TypeError):
        HpcDefaults.from_mapping({"queue": "q"})
    assert HpcDefaults.from_mapping(defaults_mapping) == HpcDefaults("workq", 16, "24:00:00")
