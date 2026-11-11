"""SM-C3~C8 플랫폼 측(shell-morph.md §14.10): 새 옵션 키 통과·검증(V-SM-13 확장), `warn` 정책 DOE의 경고 통과 집계·`waived`(V-SM-19 플랫폼 측),
`skip` 기본의 기존 통계·옵션 불변, hold_eligible 아닌 비드 422(V-SM-20 플랫폼 측), PREDICT·최적화 정책 skip 고정. 가짜 paicad(shell 그룹)."""

from __future__ import annotations

import json

from .test_shell_bead import BEAD, P, PW, _ready_shell, make_shell_project  # noqa: F401 - 같은 디렉터리 시험의 준비 도우미

from physicsai_test_support import API

FIXED = "CHASSIS_REAR_BEAD_D_1>4.1"
WARN_BOTH = {"fixed": {"policy": "warn"}, "quality": {"fail_policy": "warn"}}
DEFAULT_KEYS = {"tag", "fixed", "morph", "quality", "deviation", "interference", "tie", "extract", "bead", "symmetry_split", "schema_version",
                "engine", "engine_version"}


def _runs(env):
    return sorted(p for p in (env.sroot / "01_train").rglob("run__*") if p.is_dir() and (p / "_paicad").is_dir())


def test_skip_default_keeps_stats_and_options(native_env, monkeypatch):
    env = native_env()
    psid = _ready_shell(env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", f"shell_update:SHELL_FIXED_REGION_VIOLATION:{FIXED}")
    j = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 6, "seed": 3, "multi_execution": 2})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    res = env.job(j["id"])["result"]
    assert res["gen_ok"] + res["gen_skipped"] == 6 and res["gen_skipped"] >= 1
    s = res["gen_summary"]  # 스킵 집계: 고정 a·품질 b, 경고 통과 0
    assert s["skipped"] == {"fixed": res["gen_skipped"], "quality": 0, "other": 0} and res["gen_warned"] == 0 and res["warned_runs"] == []
    assert s["warned"] == {"fixed": 0, "quality": 0, "other": 0} and s["waived"] == {}
    for R in _runs(env):  # 기본값 새 키는 options.json에 없다(기존 결과·옵션 sha 유지)
        o = json.loads((R / "_paicad" / "options.json").read_text())
        assert set(o) == DEFAULT_KEYS and "policy" not in o["fixed"] and "fail_policy" not in o["quality"] and "hold" not in o["bead"]
    doe = env.sql("select geom_options from train_does order by created_at desc limit 1")[0][0]
    assert "policy" not in doe["fixed"]


def test_warn_policy_doe_counts_and_waived(native_env, fake_record, monkeypatch):
    env = native_env()
    psid = _ready_shell(env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", f"shell_update:SHELL_FIXED_REGION_VIOLATION:{FIXED}")
    j = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 6, "seed": 3, "multi_execution": 2, "geom_options": WARN_BOTH})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    jd = env.job(j["id"])
    res = jd["result"]
    assert res["gen_skipped"] == 0 and res["gen_ok"] == 6 and res["gen_warned"] >= 1  # 같은 입력이 스킵 대신 경고 통과
    assert res["gen_summary"]["warned"]["fixed"] == res["gen_warned"] and res["gen_summary"]["skipped"]["fixed"] == 0
    assert res["gen_summary"]["waived"] == {"SHELL_FIXED_REGION_VIOLATION": res["gen_warned"]}
    assert all(r["codes"] == ["SHELL_FIXED_MOVED"] and r["waived"] == ["SHELL_FIXED_REGION_VIOLATION"] for r in res["warned_runs"])
    codes = [w["code"] for w in jd["warnings"]]
    assert "SHELL_WARN_PASSED" in codes and "PARTIAL_OUTPUT" not in codes
    saw = False
    for R in _runs(env):
        o = json.loads((R / "_paicad" / "options.json").read_text())
        assert o["fixed"]["policy"] == "warn" and o["quality"]["fail_policy"] == "warn"
        ck = json.loads((R / "_paicad" / "check" / "shell_check.json").read_text())
        saw = saw or ck.get("waived") == ["SHELL_FIXED_REGION_VIOLATION"]
        assert not (R / "SKIPPED.json").exists()
    assert saw


def test_warn_policy_quality_waived_but_inverted_still_fails(native_env, monkeypatch):
    env = native_env()
    psid = _ready_shell(env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "shell_check:GEOM_QUALITY")
    j = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 2, "seed": 1, "multi_execution": 1, "geom_options": WARN_BOTH})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    res = env.job(j["id"])["result"]
    assert res["gen_ok"] == 2 and res["gen_warned"] == 2 and res["gen_summary"]["warned"]["quality"] == 2
    assert res["gen_summary"]["waived"] == {"GEOM_QUALITY": 2}
    # 반전은 warn에서도 실패(SM-11) — 전부 실패면 작업이 첫 실패 코드로 실패
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "shell_check:GEOM_QUALITY_INVERTED")
    j = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 2, "seed": 1, "multi_execution": 1, "geom_options": WARN_BOTH})
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(j["id"])
    assert jd["failure_code"] == "GEOM_QUALITY" and "품질 미달" in jd["failure_message"]
    # skip(기본)이면 같은 GEOM_QUALITY가 스킵 집계(품질 b)로
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", "shell_check:GEOM_QUALITY:CHASSIS_REAR_BEAD_D_1>4.0")
    monkeypatch.delenv("FAKE_PAICAD_FAIL")
    j = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 6, "seed": 3, "multi_execution": 1})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    res = env.job(j["id"])["result"]
    assert res["gen_summary"]["skipped"]["quality"] == res["gen_skipped"] >= 1 and res["gen_warned"] == 0


def test_doe_geom_options_validation(native_env):
    env = native_env()
    psid = _ready_shell(env)
    base = {"param_set_id": psid, "num_runs": 2, "seed": 1, "multi_execution": 1}
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW,
                   json={"job_type": "TD_DOE_GEN", "params": {**base, "geom_options": {"fixed": {"policy": "ignore"}}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "GEOM_OPTIONS_INVALID", r.text
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW,
                   json={"job_type": "TD_DOE_GEN", "params": {**base, "geom_options": {"bead": {"hold": {"beads": ["CHASSIS_REAR_B2"]}}}}})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["key"] == "bead.hold.beads"  # hold_eligible 아님


def test_hold_requires_eligible_bead_and_policy_forced_skip_in_predict(native_env, monkeypatch):
    beads = [{"id": "CHASSIS_REAR_B2", "hold_eligible": True}, {"id": "CHASSIS_REAR_B1", "hold_eligible": False}]
    monkeypatch.setenv("FAKE_PAICAD_SHELL_BEADS", json.dumps(beads))
    env = native_env()
    psid = _ready_shell(env)
    url = f"{API}/param-sets/{psid}"
    r = env.c.patch(url, headers=PW, json={"geom_options": {"bead": {"hold": {"beads": ["CHASSIS_REAR_B1"]}}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "GEOM_OPTIONS_INVALID", r.text
    assert r.json()["detail"]["problems"][0]["key"] == "bead.hold.beads" and "CHASSIS_REAR_B1" in r.json()["detail"]["problems"][0]["message"]
    r = env.c.patch(url, headers=PW, json={"geom_options": {"bead": {"hold": {"beads": ["nope"]}}}})
    assert r.status_code == 422
    r = env.c.patch(url, headers=PW, json={"geom_options": {"bead": {"hold": {"beads": ["CHASSIS_REAR_B2"]}}, **WARN_BOTH}})
    assert r.status_code == 422 and {p["key"] for p in r.json()["detail"]["problems"]} == {"fixed.policy", "quality.fail_policy"}  # warn은 DOE에서만
    assert "DOE 고급 옵션" in r.json()["detail"]["problems"][0]["message"]
    r = env.c.patch(url, headers=PW, json={"geom_options": {"bead": {"hold": {"beads": ["CHASSIS_REAR_B2"], "ring_mm": 4.0}},
                                                            "fixed": {"policy": "skip"}}})
    assert r.status_code == 200 and r.json()["native"]["prep_status"] == "READY", r.text  # skip·hold는 허용, 준비본 STALE 아님
    eff = r.json()["geom_options_effective"]
    assert eff["bead"]["hold"] == {"beads": ["CHASSIS_REAR_B2"], "ring_mm": 4.0, "blend_mm": 8.0} and "policy" not in eff["fixed"]
    # 이미 warn이 저장된 세트(직전 버전 등): DB에 직접 넣어 DOE가 승계하지 않고 경고를 남기는지
    env.sql("update param_sets set geom_options = jsonb_set(geom_options, '{fixed}', '{\"policy\": \"warn\"}') where id=:i", i=psid)
    j0 = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 2, "seed": 1, "multi_execution": 1})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j0["id"])
    assert "SET_POLICY_IGNORED" in [w["code"] for w in env.job(j0["id"])["warnings"]]
    for R in _runs(env):
        assert "policy" not in json.loads((R / "_paicad" / "options.json").read_text())["fixed"]
    env.sql("update param_sets set geom_options = jsonb_set(geom_options, '{fixed}', '{}') where id=:i", i=psid)
    # PREDICT(A): 세트에 warn이 있어도 정책 skip 고정 — 같은 FIXED 침범이 실패, options에 정책 키 없음, hold는 유지
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "shell_check:SHELL_FIXED_REGION_VIOLATION")
    j = env.submit("PREDICT", {"values": BEAD, "value_source": "manual", "param_set_id": psid})
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(j["id"])
    assert jd["failure_code"] == "SHELL_FIXED_REGION_VIOLATION" and "고정 영역(tie·RBE2) 침범" in jd["failure_message"]
    opts = json.loads((env.predict_dir(j["id"]) / "geom" / "options.json").read_text())
    assert "policy" not in opts["fixed"] and "fail_policy" not in opts["quality"]
    assert opts["bead"]["hold"]["beads"] == ["CHASSIS_REAR_B2"]
    # DOE는 세트 옵션을 승계하고 요청 geom_options가 덮는다(hold 유지 + 정책 요청값)
    monkeypatch.delenv("FAKE_PAICAD_FAIL")
    j = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 2, "seed": 1, "multi_execution": 1, "geom_options": {"fixed": {"policy": "skip"}}})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    for R in _runs(env):
        o = json.loads((R / "_paicad" / "options.json").read_text())
        assert o["bead"]["hold"]["beads"] == ["CHASSIS_REAR_B2"] and "policy" not in o["fixed"]


def test_doe_geom_options_solid_rejected(native_env):
    env = native_env()
    proj = make_shell_project(env.imports / "t2")
    j = env.submit("TD_EXTRACT_PARAMS", {"cad_path": str(proj / "chassis_mid.step"), "engine": "native", "kind": "shell"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW,
                   json={"job_type": "TD_DOE_GEN", "params": {"radioss_assem_path": str(proj / "assem"), "num_runs": 2, "seed": 1,
                                                              "geom_options": {"bead": {"hold": {"beads": ["x"]}}}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "GEOM_OPTIONS_INVALID", r.text  # ①-1 기반은 hold 대상을 아직 모른다


def test_features_response_carries_bead_hold_eligible_use_default(native_env, monkeypatch):
    monkeypatch.setenv("FAKE_PAICAD_SHELL_BEADS", json.dumps([{"id": "CHASSIS_REAR_B1", "hold_eligible": True}]))
    monkeypatch.setenv("FAKE_PAICAD_SHELL_FEATURES", json.dumps([
        {"name": "CHASSIS_REAR_BEAD_D_1", "type": "BEAD_DEPTH", "bead": "CHASSIS_REAR_B1", "body": "CHASSIS_REAR", "nominal": 4.0,
         "range": {"min": 3.8, "max": 4.2}, "use_default": False},
        {"name": "CHASSIS_REAR_BEAD_D_2", "type": "BEAD_DEPTH", "bead": "CHASSIS_REAR_B2", "body": "CHASSIS_REAR", "nominal": 3.0,
         "range": {"min": 2.8, "max": 3.2}, "use_default": True}]))
    env = native_env()
    psid = _ready_shell(env)
    feats = env.c.get(f"{API}/param-sets/{psid}/features", headers=P).json()["features"]
    got = {f["name"]: (f["bead"], f["hold_eligible"], f["use_default"]) for f in feats}
    assert got == {"CHASSIS_REAR_BEAD_D_1": ("CHASSIS_REAR_B1", True, False), "CHASSIS_REAR_BEAD_D_2": ("CHASSIS_REAR_B2", False, True)}
    ps = env.c.get(f"{API}/param-sets/{psid}", headers=P).json()
    assert ps["native"]["kind"] == "shell"  # 정책·hold 칸 노출 판정


def test_train_setup_kind_hold_beads_put_and_doe_inherits(native_env, monkeypatch):
    monkeypatch.setenv("FAKE_PAICAD_SHELL_BEADS", json.dumps([{"id": "CHASSIS_REAR_B1", "hold_eligible": True}]))
    env = native_env()
    proj = make_shell_project(env.imports / "t3")
    j = env.submit("TD_EXTRACT_PARAMS", {"cad_path": str(proj / "chassis_mid.step"), "engine": "native", "kind": "shell"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    setup = env.c.get(f"{API}/studies/{env.sid}/train", headers=P).json()
    assert setup["kind"] == "shell" and setup["hold_beads"] == []
    rows = [{"name": p["name"], "min": p["min"], "max": p["max"], "use": p["use"]} for p in setup["parameters"]]
    put = f"{API}/studies/{env.sid}/train/params"
    r = env.c.put(put, headers=PW, json={"version": setup["version"], "parameters": rows, "hold_beads": ["CHASSIS_REAR_B2"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TRAIN_PARAMS_INVALID", r.text  # hold_eligible 아님
    r = env.c.put(put, headers=PW, json={"version": setup["version"], "parameters": rows, "hold_beads": ["CHASSIS_REAR_B1"]})
    assert r.status_code == 200 and r.json()["hold_beads"] == ["CHASSIS_REAR_B1"] and r.json()["kind"] == "shell", r.text
    again = env.c.get(f"{API}/studies/{env.sid}/train", headers=P).json()
    assert again["hold_beads"] == ["CHASSIS_REAR_B1"]
    r = env.c.put(put, headers=PW, json={"version": again["version"], "parameters": rows})  # 생략 = 기존 유지
    assert r.json()["hold_beads"] == ["CHASSIS_REAR_B1"]
    ver = env.c.get(f"{API}/studies/{env.sid}/train", headers=P).json()["version"]
    r = env.c.put(put, headers=PW, json={"version": ver, "parameters": rows, "hold_options": {"ring_mm": 0}})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["name"] == "hold_options.ring_mm", r.text
    ver = env.c.get(f"{API}/studies/{env.sid}/train", headers=P).json()["version"]
    r = env.c.put(put, headers=PW, json={"version": ver, "parameters": rows, "hold_options": {"ring_mm": 4.5, "blend_mm": 8.0}})
    assert r.status_code == 200 and r.json()["hold_options"] == {"ring_mm": 4.5, "blend_mm": None}, r.text  # 기본값(b 8)은 저장 안 함
    r = env.c.put(put, headers=PW, json={"version": r.json()["version"], "parameters": rows})  # 생략 = 유지
    assert r.json()["hold_options"]["ring_mm"] == 4.5 and r.json()["hold_beads"] == ["CHASSIS_REAR_B1"]
    # 의미: 일부 키만 = 그 키만 갱신 · 기본값과 같은 값 = 그 키 삭제 · null/{} = 초기화
    def hput(**body):
        v = env.c.get(f"{API}/studies/{env.sid}/train", headers=P).json()["version"]
        return env.c.put(put, headers=PW, json={"version": v, "parameters": rows, **body})

    r = hput(hold_options={"blend_mm": 10.0})
    assert r.json()["hold_options"] == {"ring_mm": 4.5, "blend_mm": 10.0}
    r = hput(hold_options={"ring_mm": 3.0})  # 기본값으로 되돌림 → ring 삭제, blend 유지
    assert r.json()["hold_options"] == {"ring_mm": None, "blend_mm": 10.0}
    assert "ring_mm" not in json.loads((env.sroot / "01_train" / "params.json").read_text())["hold_options"]
    assert hput(hold_options={}).json()["hold_options"] == {"ring_mm": None, "blend_mm": None}  # {} = 초기화
    assert "hold_options" not in json.loads((env.sroot / "01_train" / "params.json").read_text())
    hput(hold_options={"ring_mm": 4.5})
    assert hput(hold_options=None).json()["hold_options"] == {"ring_mm": None, "blend_mm": None}  # null = 초기화
    assert hput().json()["hold_options"] == {"ring_mm": None, "blend_mm": None}
    hput(hold_options={"ring_mm": 4.5})
    j2 = env.submit("TD_DOE_GEN", {"radioss_assem_path": str(proj / "assem"), "num_runs": 2, "seed": 1, "multi_execution": 1})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j2["id"])
    assert env.job(j2["id"])["params"]["geom_options"]["bead"]["hold"] == {"beads": ["CHASSIS_REAR_B1"], "ring_mm": 4.5}
    for R in _runs(env):
        assert json.loads((R / "_paicad" / "options.json").read_text())["bead"]["hold"] == {"beads": ["CHASSIS_REAR_B1"], "ring_mm": 4.5,
                                                                                            "blend_mm": 8.0}
    ver = env.c.get(f"{API}/studies/{env.sid}/train", headers=P).json()["version"]
    r = env.c.put(put, headers=PW, json={"version": ver, "parameters": rows, "hold_beads": []})
    assert r.status_code == 200 and r.json()["hold_beads"] == []


def test_preview_gen_carries_waived(tmp_path):
    from types import SimpleNamespace

    from physicsai_api.services import doe_preview_api as dpa

    R = tmp_path / "doe" / "run_root" / "run__1"
    (R / "_paicad" / "check").mkdir(parents=True)
    (R / "model_0000.rad").write_text("x")
    (R / "_paicad" / "check" / "shell_check.json").write_text(json.dumps({"waived": ["GEOM_QUALITY"], "warnings": [{"code": "SHELL_QUALITY_WARN"}]}))
    assert dpa._warn_of(str(R)) == {"waived": ["GEOM_QUALITY"], "warnings": ["SHELL_QUALITY_WARN"]}
    assert dpa._warn_of(str(tmp_path)) == {}  # 보고 없음 = 키 없음(기존 모양)
    ctx = SimpleNamespace(settings=SimpleNamespace(train_data=SimpleNamespace(platform_run_root="run_root"),
                                                   predict=SimpleNamespace(starter_glob="model*_0000.rad")))
    g = dpa._gen_of(ctx, str(tmp_path / "doe"), "run__1")
    assert g["status"] == "OK" and g["waived"] == ["GEOM_QUALITY"]
