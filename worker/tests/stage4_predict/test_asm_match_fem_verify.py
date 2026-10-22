"""조립 매칭 세트(asm-match.md §6.4) FEM 검증: 예측 입력 그대로(reuse)는 INPUT의 include 트리(하위 폴더)를 상대 경로째 A/input에 복사한다.
조립 다시 만들기(rebuild)는 1차 미지원 → 미리보기 problems ASM_MATCH_UNSUPPORTED. 기존(RENUM) 세트의 INPUT 복사는 직계 파일만(불변)."""

from __future__ import annotations

from helpers_asm import STARTER
from physicsai_test_support import API, H, pbs_command_cfg

from .fv_support import NEW_CMD, T01_CMD, create, preview, ready_doe, resources, run_until_hpc
from .test_asm_match_predict import matched_set

PW = H("tok-power", write=True)
NAT = {"values": {"A_THK_1": 10.2, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}, "value_source": "manual"}


def _env(predict_env, fake_tools, tmp_path):
    return predict_env(hpc=pbs_command_cfg(fake_tools, str(tmp_path / "ai_root")), commands={"response_extract": NEW_CMD, "t01_curve_export": T01_CMD},
                       resources=resources(tmp_path), geometry={"engine": "native", "paicad_path": fake_tools["fake_paicad"]})


def test_reuse_copies_include_tree_and_rebuild_is_rejected(predict_env, fake_tools, tmp_path, pbs_state, monkeypatch):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)
    env = _env(predict_env, fake_tools, tmp_path)
    matched_set(env)
    j = env.submit("PREDICT", NAT)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": j["id"]}})
    assert pv["input_mode"] == "reuse" and pv["assembly"]["kind"] == "PREDICT_INPUT" and pv["assembly"]["starter"] == STARTER
    assert pv["assembly"]["file_count"] == 3  # 직계 2개 + nodes/ 하위 1개(트리 전체)
    d = create(env, {"source": {"kind": "predict_job", "job_id": j["id"]}})
    d = run_until_hpc(env, d["id"])
    A = env.sroot / "04_verify" / d["label"] / f"a{d['attempt_no']}"
    assert (A / "input" / STARTER).is_file() and (A / "input" / "nodes" / "102_nodes.inc").is_file()
    assert "#FAKE_PATCH" in (A / "input" / STARTER).read_text()
    # 조립 다시 만들기 요청(custom 폴더) → 매칭 세트는 미지원 problems
    doe, assem = ready_doe(env)
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": j["id"]}, "assembly": {"kind": "train_doe", "doe_id": doe}})
    assert "ASM_MATCH_UNSUPPORTED" in {p["code"] for p in pv["problems"]}
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications", headers=PW,
                   json={"source": {"kind": "predict_job", "job_id": j["id"]}, "assembly": {"kind": "train_doe", "doe_id": doe}})
    assert r.status_code == 422, r.text
