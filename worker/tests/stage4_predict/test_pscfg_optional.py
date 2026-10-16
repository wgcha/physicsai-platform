"""D3-43(사용자 결정 2026-10-16, U7): 모델 등록 시 .pscfg는 선택(0개 또는 1개).

- pscfg 0개 등록 성공 → 준비된 입력 예측 성공(가짜 도구), argv에 pscfg 없음
- {model_pscfg}를 쓰는 템플릿 + pscfg 없는 모델 → 작업 생성 409 PSCFG_REQUIRED(PREDICT·EVALUATE)
- 기존 1개 경로 회귀: {model_pscfg}에 저장본 경로 전달, 사용 직전 무결성은 pscfg도 확인
- 워커 방어: 생성 뒤 설정이 바뀌어도 INPUT_INVALID(같은 문구)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from physicsai_test_support import read_record



def make_case(root: Path, name: str = "case_A") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "Face_Drop_0000.rad").write_text("#include part.inc\n/BEGIN\n")
    (d / "part.inc").write_text("/NODE\n1 0 0 0\n")
    return d


def run_prepared(env, path: Path, expect_state="SUCCEEDED"):
    j = env.submit("PREDICT", {"input_mode": "prepared", "input_path": str(path)})
    st = env.w.run_once_slot()
    jd = env.job(j["id"])
    assert st == expect_state, jd
    return j["id"], jd

PRED_WITH_PSCFG = ["@cmd_c", "{edspy}", "--physicsai", "--predict-write", "{pred_h3d}", "--model", "{model_psmdl}",
                   "--spec", "{model_pscfg}", "--input-file", "{starter}", "@hooks_arg"]
SCORE_WITH_PSCFG = ["{edspy}", "--physicsai", "--score", "{score_path}", "--model", "{model_psmdl}", "--spec", "{model_pscfg}",
                    "--dataset", "{eval_psdata}", "@write_files"]
MSG = "이 명령 설정은 .pscfg가 필요합니다 — pscfg가 있는 모델을 등록하거나 설정에서 {model_pscfg}를 빼세요"


def _model_row(engine, mid):
    with engine.connect() as c:
        return c.execute(text("select pscfg_rel, pscfg_sha256, stored_rel, status from models where id=:i"), {"i": mid}).mappings().one()


def test_d3_43_no_pscfg_register_and_predict(predict_env, fake_record, engine):
    env = predict_env(commands={"geom_update": None}, model_pscfg=0)
    row = _model_row(engine, env.model_id)
    assert row["pscfg_rel"] is None and row["pscfg_sha256"] is None and row["status"] == "ACTIVE"
    stored = env.sroot / row["stored_rel"]
    assert not list(stored.glob("*.pscfg")) and (stored / "M1.psmdl").is_file()
    jid, _jd = run_prepared(env, make_case(env.imports))
    pred = [r for r in read_record(fake_record) if "--predict-write" in r["argv"]][-1]
    assert not any(a.endswith(".pscfg") for a in pred["argv"])
    assert (env.predict_dir(jid) / "RESULT" / "Face_Drop_0000_pred.h3d").is_file()


def test_d3_43_model_pscfg_template_without_pscfg_rejected(predict_env):
    env = predict_env(commands={"geom_update": None, "edspy_predict": PRED_WITH_PSCFG, "edspy_score": SCORE_WITH_PSCFG},
                      model_pscfg=0)
    d = env.submit("PREDICT", {"input_mode": "prepared", "input_path": str(make_case(env.imports))}, expect=409)["detail"]
    assert d["code"] == "PSCFG_REQUIRED" and d["message"] == MSG and d["template"] == "edspy_predict"
    d = env.submit("EVALUATE", {"model_id": env.model_id}, expect=409)["detail"]
    assert d["code"] == "PSCFG_REQUIRED" and d["template"] == "edspy_score"


def test_d3_43_single_pscfg_regression(predict_env, fake_record, engine):
    env = predict_env(commands={"geom_update": None, "edspy_predict": PRED_WITH_PSCFG})
    row = _model_row(engine, env.model_id)
    assert row["pscfg_rel"] == row["stored_rel"] + "settings.pscfg" and len(row["pscfg_sha256"]) == 64
    run_prepared(env, make_case(env.imports))
    pred = [r for r in read_record(fake_record) if "--predict-write" in r["argv"]][-1]
    assert pred["argv"][pred["argv"].index("--spec") + 1] == str(env.sroot / row["pscfg_rel"])
    (env.sroot / row["pscfg_rel"]).write_bytes(b"changed")                 # 등록 후 pscfg 변경 → 무결성 실패
    jid, jd = run_prepared(env, make_case(env.imports, "case_B"), expect_state="FAILED")
    assert jd["failure_code"] == "INPUT_CHANGED"
    assert _model_row(engine, env.model_id)["status"] == "INVALID"


def test_d3_43_worker_guard_same_message():
    from physicsai_core.errors import StepFailure
    from physicsai_worker.steps.common import model_command_values

    ctx = SimpleNamespace(settings=SimpleNamespace(commands=SimpleNamespace(edspy_predict=PRED_WITH_PSCFG)),
                          abs=lambda rel: "/S/" + rel)
    m = {"psmdl_rel": "03_model/models/x/M.psmdl", "pscfg_rel": None}
    with pytest.raises(StepFailure) as ei:
        model_command_values(ctx, "edspy_predict", m)
    assert ei.value.code == "INPUT_INVALID" and str(ei.value) == MSG
    ctx.settings.commands.edspy_predict = [x for x in PRED_WITH_PSCFG if x not in ("--spec", "{model_pscfg}")]
    assert model_command_values(ctx, "edspy_predict", m) == {"model_psmdl": "/S/03_model/models/x/M.psmdl"}
    m["pscfg_rel"] = "03_model/models/x/s.pscfg"
    assert model_command_values(ctx, "edspy_predict", m)["model_pscfg"] == "/S/03_model/models/x/s.pscfg"
