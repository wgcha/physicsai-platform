"""단계 4C 쉘 판금 비드 플랫폼 연동 E2E(shell-morph.md §8, V-SM-13): kind=shell 세트 등록(extract --assem-dir → fixed-scan
--features → tag, prep.json kind·assem_digest·fixed_digest, 기준 메시·RENUM 불필요, 기본 대상 component chassis_rear) → 단건 예측
(shell update·morph·check, 조립 사본 + 사본 덮어쓰기 → 3S props apply 순서) → 세트 기준 DOE(shell run, FIXED 스킵) → ①-1·①-3 쉘,
실패 코드 한국어, 솔리드·쉘 혼합 거부. 가짜 paicad(shell 그룹)."""

from __future__ import annotations

import json

from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
BEAD = {"CHASSIS_REAR_BEAD_D_1": 4.1, "CHASSIS_REAR_BEAD_U_1": 36.0, "CHASSIS_REAR_BEAD_D_2": 3.0}


def make_shell_project(root, *, renum: bool = False):
    """중립면 STEP + 조립 폴더(starter·chassis.inc·material.inc, 기준 메시·RENUM 없음)."""
    d = root / "shellproj"
    (d / "assem").mkdir(parents=True, exist_ok=True)
    (d / "chassis_mid.step").write_text("ISO-10303-21; mid-surface")
    (d / "assem" / "model_0000.rad").write_text("#include chassis.inc\n#include material.inc\n/BEGIN\n")
    (d / "assem" / "chassis.inc").write_text("/NODE\n2000001 0 0 0\n/SHELL/2001\n1 2000001 2000001 2000001 2000001\n")
    (d / "assem" / "material.inc").write_text("/PROP/TYPE1/1\nBracket\n")
    if renum:
        (d / "assem" / "RENUM_INIT.csv").write_text("x\n")
    return d


def shell_set(env, **kw):
    proj = make_shell_project(env.imports)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "kind": "shell", "label": "SH", **kw})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    return jid, proj


def test_shell_set_register_chain_prep_and_rows(native_env, fake_record):
    env = native_env()
    jid, proj = shell_set(env)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(jid)
    st = env.steps(jid)
    assert [st[k]["state"] for k in ("NP_PREP", "NP_EXTRACT", "NP_TAG", "NP_VIEW", "BL_MAP", "NP_REGISTER")] == \
        ["SUCCEEDED", "SUCCEEDED", "SUCCEEDED", "SUCCEEDED", "SKIPPED", "SUCCEEDED"]
    rec = [r for r in read_record(fake_record) if r["tool"] == "paicad"]
    assert [r["argv"][1:3] for r in rec[-5:]] == [["version", "--json"], ["shell", "extract"], ["shell", "fixed-scan"], ["shell", "tag"],
                                                  ["shell", "view"]]
    ext = rec[-4]["argv"]
    assert ext[ext.index("--assem-dir") + 1].endswith("radioss_assem")  # 세트 준비는 조립 폴더로 대응·고정 겹침 경고
    vw = rec[-1]["argv"]  # NP_VIEW 쉘: paicad 0.10.0 `shell view export`, {fixed_dir}=T/native/fixed(GV §6.3)
    assert vw[3] == "export" and vw[vw.index("--fixed-dir") + 1].endswith("fixed")
    fs = rec[-3]["argv"]
    assert fs[fs.index("--features") + 1].endswith("shell_features.json") and "--parts" not in fs
    jd = env.job(jid)
    codes = [w["code"] for w in jd["warnings"]]
    assert "BEAD_FIXED_OVERLAP" in codes and "VIEW_EXPORT_FAILED" not in codes  # 쉘 뷰 기본 템플릿(0.10.0) → 공칭 뷰 READY
    psid = jd["result"]["param_set_id"]
    ps = env.c.get(f"{API}/param-sets/{psid}", headers=P).json()
    assert ps["native"]["kind"] == "shell" and ps["native"]["prep_status"] == "READY" and ps["native"]["view_status"] == "READY"
    assert [(p["name"], p["source"]) for p in ps["parameters"]] == [(n, "shell") for n in BEAD]
    assert ps["geom_options_effective"]["fixed"]["kinds"][:2] == ["INTER_TYPE2", "RBE2"]  # 쉘 options 스키마
    S = env.sroot / "04_params" / psid
    prep = json.loads((S / "native" / "prep.json").read_text())
    assert prep["kind"] == "shell" and prep["inputs"]["baseline_inc"] is None and prep["inputs"]["renum_csv"] is None
    assert prep["inputs"]["assem_digest"].startswith("sha256:") and prep["fixed_digest"] == "sha256:fakefixed"
    assert prep["component"] == "chassis_rear"
    for rel in ("native/extract/shell_features.json", "native/fixed/shell_scan.json", "native/tag/shell_tag.json"):
        assert (S / rel).is_file(), rel
    opts = json.loads((S / "native" / "options.json").read_text())
    assert opts["kind"] == "shell" and set(opts) == {"schema_version", "kind", "tag", "fixed"}
    # 쉘 옵션 덮어쓰기: 솔리드 키 거부, 쉘 키 저장
    r = env.c.patch(f"{API}/param-sets/{psid}", headers=PW, json={"geom_options": {"quality": {"min_stretch": 0.2}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "GEOM_OPTIONS_INVALID", r.text
    r = env.c.patch(f"{API}/param-sets/{psid}", headers=PW, json={"geom_options": {"fixed": {"transition_mm": 8.0}}})
    assert r.status_code == 200 and r.json()["native"]["prep_status"] == "READY", r.text  # 전이 폭은 준비본 무관
    r = env.c.patch(f"{API}/param-sets/{psid}", headers=PW, json={"geom_options": {"tag": {"tol_abs_mm": 0.08}}})
    assert r.json()["native"]["prep_status"] == "STALE"
    # 조립 폴더(쉘 메시) 변경 → STALE
    env.c.patch(f"{API}/param-sets/{psid}", headers=PW, json={"geom_options": None})
    (S / "radioss_assem" / "chassis.inc").write_text("/NODE\n2000001 0 0 1\n")
    assert env.c.get(f"{API}/param-sets/{psid}", headers=P).json()["native"]["prep_status"] == "STALE"


def test_shell_component_missing_and_mix_rejected(native_env, monkeypatch):
    env = native_env(extra={"shell": {"default_component": "chassis_front"}})
    jid, _proj = shell_set(env)
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(jid)
    assert jd["failure_code"] == "SHELL_PART_NOT_FOUND" and "chassis_front" in jd["failure_message"] and jd["current_step_key"] == "NP_EXTRACT"
    proj = make_shell_project(env.imports / "x")
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "kind": "shell", "shell_only": True})
    assert r.status_code == 422, r.text
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "kind": "shell",
                         "geom_options": {"thickness_ref": "contact_fixed"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "GEOM_OPTIONS_INVALID"
    # 폴더 검증: 솔리드·쉘 피처 파일이 함께 있으면 혼합 거부(GEOM_KIND_MIXED)
    from physicsai_core.stage4_predict.param_set_native import validate_native_folder

    S = env.sroot / "logs" / "_paramset_tmp" / jid
    (S / "native" / "extract" / "parameter_features.json").write_text("{}")
    f = validate_native_folder(str(S), max_total_bytes=1 << 30, starter_glob="model*_0000.rad", renum_csv_name="RENUM_INIT.csv",
                               baseline_inc_name="104_replace_node_elem.inc", step_extensions=[".step"], kind="shell")
    assert "GEOM_KIND_MIXED" in [p["code"] for p in f.problems]


def _ready_shell(env):
    jid, _ = shell_set(env)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(jid)
    return env.job(jid)["result"]["param_set_id"]


def test_shell_predict_overlay_then_props_apply(native_env, fake_record, monkeypatch):
    env = native_env()
    psid = _ready_shell(env)
    S = env.sroot / "04_params" / psid
    r = env.c.post(f"{API}/param-sets/{psid}/props/scan", headers=PW)
    assert r.status_code == 202 and env.w.run_once_slot() == "SUCCEEDED"
    r = env.c.put(f"{API}/param-sets/{psid}/props", headers=PW, json={"selected": [{"name": "BRACKET_SHELL_T"}]})
    assert r.status_code == 200, r.text
    assert {p["source"] for p in r.json()["parameters"]} == {"shell", "prop"}  # 쉘 형상 + 3S 두께 동시 사용
    monkeypatch.setenv("FAKE_PAICAD_SHELL_FILE", "material.inc")  # 쉘 노드와 PROP이 같은 파일 → 순차 적용으로 합쳐짐
    orig = (S / "radioss_assem" / "material.inc").read_bytes()
    j = env.submit("PREDICT", {"values": {**BEAD, "CHASSIS_REAR_BEAD_D_1": 4.15, "BRACKET_SHELL_T": 1.25}, "value_source": "manual",
                               "param_set_id": psid})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    Pd = env.predict_dir(j["id"])
    rec = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad"]
    assert [a[1:3] for a in rec[-4:]] == [["shell", "update"], ["shell", "morph"], ["shell", "check"], ["props", "apply"]]
    upd = rec[-4]
    assert upd[upd.index("--fixed-dir") + 1].endswith("native/fixed")  # 고정 사전 검사
    chk = rec[-2]
    assert chk[chk.index("--out-files-dir") + 1].endswith("geom/shell_files") and "--thickness" not in chk
    vals = json.loads((Pd / "geom" / "values.json").read_text())["values"]
    assert "BRACKET_SHELL_T" not in vals and vals["CHASSIS_REAR_BEAD_D_1"] == 4.15
    out = (Pd / "INPUT" / "material.inc").read_text()
    assert out.index("#FAKE_SHELL_NODE") < out.index("#FAKE_PROP 1 1.25")  # 쉘 overlay 뒤 props apply(SM §8.3)
    assert (Pd / "INPUT" / "chassis.inc").is_file() and (Pd / "INPUT" / "model_0000.rad").is_file()
    assert (S / "radioss_assem" / "material.inc").read_bytes() == orig  # 원본 조립 폴더 불변
    jd = env.job(j["id"])
    assert jd["result"]["shell_files"] == ["material.inc"] and jd["result"]["geometry"]["check_status"] == "PASS"
    assert env.steps(j["id"])["GEOM_UPDATE"]["state"] == "SUCCEEDED" and env.steps(j["id"])["MESH"]["state"] == "SUCCEEDED"


def test_shell_predict_fixed_violation_korean(native_env, monkeypatch):
    env = native_env()
    psid = _ready_shell(env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "shell_check:SHELL_FIXED_REGION_VIOLATION")
    j = env.submit("PREDICT", {"values": BEAD, "value_source": "manual", "param_set_id": psid})
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(j["id"])
    assert jd["failure_code"] == "SHELL_FIXED_REGION_VIOLATION" and "고정 영역(tie·RBE2) 침범" in jd["failure_message"]
    assert jd["current_step_key"] == "MESH"


def test_shell_doe_from_set_run_and_fixed_skip(native_env, fake_record, monkeypatch):
    env = native_env()
    psid = _ready_shell(env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", "shell_update:SHELL_FIXED_REGION_VIOLATION:CHASSIS_REAR_BEAD_D_1>4.1")
    j = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 6, "seed": 3, "multi_execution": 2})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    jd = env.job(j["id"])
    ok, skipped = jd["result"]["gen_ok"], jd["result"]["gen_skipped"]
    assert ok + skipped == 6 and ok >= 1 and skipped >= 1 and "PARTIAL_OUTPUT" in [w["code"] for w in jd["warnings"]]
    runs = sorted(p for p in (env.sroot / "01_train").rglob("run__*") if p.is_dir() and (p / "m_1").is_dir())
    seen_skip = seen_ok = False
    for R in runs:
        if (R / "SKIPPED.json").is_file():
            sk = json.loads((R / "SKIPPED.json").read_text())
            assert sk["code"] == "SHELL_FIXED_REGION_VIOLATION" and sk["category"] == "FIXED" and "고정 영역" in sk["message"]
            assert not (R / "m_3").exists()
            seen_skip = True
        else:
            m3 = (R / "m_3" / "chassis.inc").read_text()
            assert "#FAKE_SHELL_NODE" in m3 and (R / "m_2" / "check" / "shell_run.json").is_file()
            seen_ok = True
    assert seen_skip and seen_ok
    cmds = {tuple(r["argv"][1:3]) for r in read_record(fake_record) if r["tool"] == "paicad"}
    assert ("shell", "run") in cmds  # paicad_shell_run이 있으면 1회


def test_shell_sequential_when_run_template_null(native_env, fake_record):
    env = native_env(commands={"paicad_shell_run": None})
    psid = _ready_shell(env)
    j = env.submit("TD_DOE_GEN", {"param_set_id": psid, "num_runs": 2, "seed": 1, "multi_execution": 1})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    cmds = [tuple(r["argv"][1:3]) for r in read_record(fake_record) if r["tool"] == "paicad"]
    assert ("shell", "run") not in cmds and cmds.count(("shell", "check")) == 2


def test_train_extract_and_doe_shell(native_env, fake_record):
    env = native_env()
    proj = make_shell_project(env.imports / "t1")
    j = env.submit("TD_EXTRACT_PARAMS", {"cad_path": str(proj / "chassis_mid.step"), "engine": "native", "kind": "shell"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    ext = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1:3] == ["shell", "extract"]][-1]
    assert "--assem-dir" not in ext  # ①-1: 조립 폴더 없음 → fixed_overlap unknown
    st = env.steps(j["id"])
    assert st["TX_VIEW"]["state"] == "SUCCEEDED"
    tv = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1:4] == ["shell", "view", "export"]][-1]
    assert "--fixed-dir" not in tv  # ①-1 쉘 뷰: 고정 정보 없음 → 쌍 생략(GV §6.4)
    setup = env.c.get(f"{API}/studies/{env.sid}/train", headers=P).json()
    use = {p["name"]: p["use"] for p in setup["parameters"]}
    assert use["CHASSIS_REAR_BEAD_D_1"] is True and use["CHASSIS_REAR_BEAD_D_2"] is False  # 체결 영역 겹침 → 기본 use=false
    feats = env.c.get(f"{API}/studies/{env.sid}/train/features", headers=P).json()
    assert [f["name"] for f in feats["features"]][:1] == ["CHASSIS_REAR_BEAD_D_1"]
    j2 = env.submit("TD_DOE_GEN", {"radioss_assem_path": str(proj / "assem"), "num_runs": 2, "seed": 1, "multi_execution": 1})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j2["id"])
    cmds = [tuple(r["argv"][1:3]) for r in read_record(fake_record) if r["tool"] == "paicad"]
    i = cmds.index(("shell", "fixed-scan"))
    assert cmds[i + 1] == ("shell", "tag")  # DOE 준비: tag 자리에서 fixed-scan → tag
    preps = [json.loads(p.read_text()) for p in (env.sroot / "01_train").rglob("native/prep.json")]
    assert preps and all(x["kind"] == "shell" and x["inputs"]["renum_csv"] is None for x in preps)  # D 준비본(쉘)
    runs = [p for p in (env.sroot / "01_train").rglob("run__*") if (p / "m_3").is_dir()]
    assert len(runs) == 2 and all("#FAKE_SHELL_NODE" in (r / "m_3" / "chassis.inc").read_text() for r in runs)


def test_shell_batch_generation_overlay(native_env, fake_record):
    """④ 일괄 예측(B): run마다 shell run → m_3 = 조립 사본 + 쉘 사본 덮어쓰기(하위 PREDICT 입력 검사 통과)."""
    env = native_env()
    psid = _ready_shell(env)
    rows = "CHASSIS_REAR_BEAD_D_1,CHASSIS_REAR_BEAD_U_1,CHASSIS_REAR_BEAD_D_2\n3.9,35,3.0\n4.1,36,3.1\n"
    pj = env.submit("PREDICT_BATCH", {"param_set_id": psid, "multi_execution": 2, "source": {"kind": "table", "text": rows}})
    st = env.w.run_once_slot()
    jd = env.job(pj["id"])
    assert st == "SUCCEEDED", (jd["failure_code"], jd["failure_message"])
    bid = pj["params"]["batch_id"]
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert b["gen"]["done"] == 2
    run_dir = env.sql("select dir_rel from predict_batches where id=:i", i=bid)[0][0]
    for r in b["rows"]:
        R = env.sroot / run_dir / r["run_key"]
        assert "#FAKE_SHELL_NODE" in (R / "m_3" / "chassis.inc").read_text() and (R / "m_2" / "shell_files" / "chassis.inc").is_file()


def test_shell_discover_without_baseline_inc_and_altair_rejected(native_env):
    env = native_env()
    proj = make_shell_project(env.imports / "d")
    d = env.c.post(f"{API}/studies/{env.sid}/param-sets/discover", headers=PW,
                   json={"path": str(proj), "engine": "native", "kind": "shell"}).json()
    assert d["kind"] == "shell" and [a["rel"] for a in d["radioss_assem"]] == ["assem"]
    assert not {"BASELINE_INC_MISSING", "RENUM_CSV_MISSING"} & {p["code"] for p in d["problems"]}
    solid = env.c.post(f"{API}/studies/{env.sid}/param-sets/discover", headers=PW, json={"path": str(proj), "engine": "native"}).json()
    assert "BASELINE_INC_MISSING" in {p["code"] for p in solid["problems"]}  # 솔리드는 기준 메시 필수(기존 규칙 불변)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW, json={"path": str(proj), "engine": "altair", "kind": "shell"})
    assert r.status_code == 422, r.text


def test_shell_view_and_preview_default_templates(native_env, fake_record):
    """paicad 0.10.0 `shell view` 기본 템플릿: 쉘 세트 GET /view READY, 미리보기 202 → PREVIEW 레인 → DONE(fe check: --fixed-dir·
    --tag-dir·--assem-dir 전달, 3S 두께 없음 → --thickness 생략)."""
    env = native_env()
    psid = _ready_shell(env)
    env.w.heartbeat_once()
    v = env.c.get(f"{API}/param-sets/{psid}/view", headers=P).json()
    assert v["status"] == "READY" and v["kind"] == "shell" and v["available"] and v["preview_available"], v
    r = env.c.post(f"{API}/param-sets/{psid}/previews", headers=PW, json={"values": {"CHASSIS_REAR_BEAD_D_1": 4.5}, "fe": "check"})
    assert r.status_code == 202, r.text
    pid = r.json()["id"]
    assert env.w.run_once_preview() == "SUCCEEDED"
    assert env.c.get(f"{API}/previews/{pid}", headers=P).json()["status"] == "DONE"
    pv = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1:4] == ["shell", "view", "preview"]][-1]
    assert pv[pv.index("--fe") + 1] == "check" and "--thickness" not in pv
    for flag, tail in (("--fixed-dir", "fixed"), ("--tag-dir", "tag"), ("--assem-dir", "radioss_assem")):
        assert pv[pv.index(flag) + 1].endswith(tail), (flag, pv)
