"""doe-preview.md ①-1·①-3 세트 출처(param_set) — V-DP-3(세트 표본 행렬 바이트 동일)·tag 사용(`--tag-dir`)·GEOM_PREP_STALE·PREVIEW 레인과 동시 실행·
housekeeping(기간·총량·링크·410·jobs/matrix 폴더)·다중 baseline/Altair 409·쉘 세트(`shell view grid` + `--fixed-dir`). 가짜 paicad."""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone

from helpers_native import native_set

from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")


def _env(native_env, **kw):
    env = native_env(**kw)
    ps = native_set(env)
    env.w.heartbeat_once()  # resources.paicad_version(셀 캐시 키)
    return env, ps


def _body(psid, sampling=None, **select):
    b = {"source": {"kind": "param_set", "param_set_id": psid}, "sampling": sampling or {"kind": "lhs", "count": 6, "seed": 3}}
    if select:
        b["select"] = select
    return b


def _post(env, body, expect=(200, 202), headers=PW):
    r = env.c.post(f"{API}/studies/{env.sid}/doe-previews", headers=headers, json=body)
    assert r.status_code in ((expect,) if isinstance(expect, int) else expect), r.text
    return r


def _get(env, pid):
    r = env.c.get(f"{API}/doe-previews/{pid}", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def _run(env, body, state="SUCCEEDED"):
    p = _post(env, body, expect=202).json()
    assert env.w.run_once_slot() == state, env.job(p["job_id"])
    return _get(env, p["id"])


def _matrix(env, pv):
    mkey = env.job(pv["job_id"])["params"]["matrix_key"]
    return (env.sroot / "_cache" / "doe_preview" / "matrix" / mkey[:2] / mkey / "doe_matrix.csv").read_text(encoding="utf-8")


def _doe(env, params):
    j = env.submit("TD_DOE_GEN", params)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    return env.sroot / "01_train" / "doe" / env.job(j["id"])["result"]["doe_id"]


def _calls(fake_record, sub="grid"):
    return [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1] == "view" and r["argv"][2] == sub]


def test_v_dp_3_set_matrix_bytes_equal_set_doe_and_tag_dir(native_env, fake_record):
    env, ps = _env(native_env)
    names = [r["name"] for r in ps["parameters"]]
    table = ",".join(names) + "\n" + "\n".join(",".join(repr((r["min"] + r["max"]) / 2 + k * 0.01) for r in ps["parameters"]) for k in range(3)) + "\n"
    for sampling in ({"kind": "lhs", "count": 6, "seed": 3}, {"kind": "lhs", "count": 5, "seed": 0}, {"kind": "halton", "count": 7, "seed": 5},
                     {"kind": "sobol", "count": 8, "seed": 4}, {"kind": "lhs_opt", "count": 6, "seed": 3}, {"kind": "pb"}, {"kind": "bbd"},
                     {"kind": "table", "text": table}):
        pv = _run(env, _body(ps["id"], sampling))
        assert pv["status"] == "DONE" and pv["cache_hit"] is False, sampling
        D = _doe(env, {"sampling": sampling, "param_set_id": ps["id"]})
        assert _matrix(env, pv) == (D / "doe_matrix.csv").read_text(encoding="utf-8"), sampling  # 바이트 동일
        rows = list(csv.DictReader(_matrix(env, pv).splitlines()))
        assert pv["n_total"] == len(rows) and sorted(pv["order"]) == [int(r["doe_no"]) for r in rows], sampling
    # 세트 준비본의 tag 폴더를 쓴다 → tagged, argv에 --tag-dir(세트 S/native/tag)
    assert pv["tag_state"] == "tagged"
    S = env.sroot / "04_params" / ps["id"]
    for a in _calls(fake_record):
        assert a[a.index("--tag-dir") + 1] == str(S / "native" / "tag") and "--fixed-dir" not in a and a[a.index("--threads") + 1] == "1"
        assert a[a.index("--features") + 1] == str(S / "native" / "extract" / "parameter_features.json")
    assert all(c["nominal"] or c["gen"] is None for c in pv["cells"])  # 세트 출처는 생성 결과 배지 없음


def test_set_stale_prep_409_at_request_and_failed_when_changed_after_queue(native_env):
    env, ps = _env(native_env)
    S = env.sroot / "04_params" / ps["id"]
    step = next((S / "cad").glob("*.step"), None) or next((S / "cad" / "parts").glob("*.step"))
    queued = _post(env, _body(ps["id"]), expect=202).json()  # 요청 때는 준비본이 유효
    step.write_text(step.read_text() + "\n/* 바뀜 */\n")
    r = _post(env, _body(ps["id"], {"kind": "halton", "count": 6, "seed": 2}), expect=409)  # 요청 시점 검사
    assert r.json()["detail"]["code"] == "GEOM_PREP_STALE" and r.json()["detail"]["prep_status"] == "STALE"
    assert env.w.run_once_slot() == "FAILED"  # 대기 중 바뀜 → DP_PREP이 다시 검사
    pv = _get(env, queued["id"])
    assert pv["status"] == "FAILED" and pv["code"] == "GEOM_PREP_STALE" and pv["cells"] == []
    assert env.job(queued["job_id"])["failure_code"] == "GEOM_PREP_STALE"


def test_newer_request_cancels_queued_and_preview_lane_runs_concurrently(native_env):
    env, ps = _env(native_env, extra={"doe_preview": {"max_active_per_user": 1}})
    a = _post(env, _body(ps["id"]), expect=202).json()
    r = env.c.post(f"{API}/studies/{env.sid}/doe-previews", headers=PW, json=_body(ps["id"], {"kind": "halton", "count": 6, "seed": 1}))
    # 같은 출처의 이전 QUEUED는 취소되고 새 요청이 들어가므로 429가 아니다(상한은 QUEUED+RUNNING 합 — 취소된 것은 제외)
    assert r.status_code == 202 and _get(env, a["id"])["status"] == "CANCELED"
    # DOE_PREVIEW는 CPU 슬롯 1개를 점유하고, 그동안 PREVIEW 레인(GEOM_PREVIEW)은 별도로 실행된다
    held = env.w.claim_only()
    assert held is not None and held["job_type"] == "DOE_PREVIEW"
    pr = env.c.post(f"{API}/param-sets/{ps['id']}/previews", headers=PW, json={"values": {"A_THK_1": 10.1}, "fe": "off"})
    assert pr.status_code == 202, pr.text
    assert env.w.run_once_preview() == "SUCCEEDED"
    assert env.c.get(f"{API}/previews/{pr.json()['id']}", headers=P).json()["status"] == "DONE"


def test_multi_baseline_and_altair_set_409(native_env, monkeypatch):
    env, ps = _env(native_env)
    S = env.sroot / "04_params" / ps["id"]
    (S / "native").mkdir(exist_ok=True)
    (S / "param_map.json").write_text(json.dumps({"schema_version": 1, "baselines": [{"id": "B1"}, {"id": "B2"}]}))
    r = _post(env, _body(ps["id"]), expect=(409,))
    assert r.json()["detail"]["code"] == "DOE_PREVIEW_UNSUPPORTED" and "다중" in r.json()["detail"]["message"]
    alt = env.param_set()  # Altair(템플릿) 세트
    r = _post(env, _body(alt["id"]), expect=(409,))
    assert r.json()["detail"]["code"] == "DOE_PREVIEW_UNSUPPORTED"


def _done(env, ps, seed):
    return _run(env, _body(ps["id"], {"kind": "lhs", "count": 6, "seed": seed}))


def test_housekeeping_cells_total_410_links_and_dirs(native_env, tmp_path):
    from physicsai_worker.housekeeping import purge_view_cache

    env, ps = _env(native_env)
    old = _done(env, ps, 11)
    new = _done(env, ps, 12)
    cache = env.sroot / "_cache" / "doe_preview"
    assert (cache / "jobs" / old["job_id"]).is_dir() and list((cache / "matrix").glob("*/*"))
    cell_old = old["cells"][1]
    past = datetime.now(timezone.utc) - timedelta(days=60)
    keys_old = {e["key"] for e in env.sql("select cell_keys from doe_previews where id=:i", i=old["id"])[0][0]["cells"]}
    keys_new = {e["key"] for e in env.sql("select cell_keys from doe_previews where id=:i", i=new["id"])[0][0]["cells"]}
    only_old = sorted(keys_old - keys_new)
    assert only_old and cell_old["png_artifact_id"]
    for k in only_old:
        env.sql("update doe_preview_cells set last_access_at=:t where cache_key=:k", t=past, k=k)
    # 작업 폴더·행렬 캐시(old의 것)도 오래된 것으로
    t_old = time.time() - 60 * 86400
    jd_old = cache / "jobs" / old["job_id"]
    os.utime(jd_old, (t_old, t_old))
    for m in (cache / "matrix").glob("*/*"):
        if m.name == env.job(old["job_id"])["params"]["matrix_key"]:
            os.utime(m, (t_old, t_old))
    out = purge_view_cache(env.engine, env.lc.settings)
    assert out["expired"] == len(only_old) and out["dirs"] >= 2
    assert not jd_old.exists() and (cache / "jobs" / new["job_id"]).is_dir()  # 최근 폴더는 남는다
    assert all(not (cache / "cells" / k[:2] / k).exists() for k in only_old)
    st = {r[0]: r[1] for r in env.sql("select cache_key, status from doe_preview_cells")}
    assert all(st[k] == "EXPIRED" for k in only_old) and all(st[k] == "DONE" for k in keys_new)
    # 만료 셀의 산출물은 410(다른 셀·공유 셀은 그대로 200)
    expired_cell = next(c for c in old["cells"] if c["png_artifact_id"] and env.sql(
        "select status from doe_preview_cells where png_artifact_id=:a", a=c["png_artifact_id"])[0][0] == "EXPIRED")
    r = env.c.get(f"{API}/artifacts/{expired_cell['png_artifact_id']}/media", headers=P)
    assert r.status_code == 410 and r.json()["detail"]["code"] == "ARTIFACT_EXPIRED"
    assert env.c.get(f"{API}/artifacts/{new['cells'][1]['png_artifact_id']}/media", headers=P).status_code == 200
    # 만료된 셀이 있는 미리보기는 캐시 히트가 아니라 새 작업
    again = _post(env, _body(ps["id"], {"kind": "lhs", "count": 6, "seed": 11}), expect=202).json()
    assert again["cache_hit"] is False
    # 링크 셀 폴더는 지우지 않는다
    key = next(r[0] for r in env.sql("select cache_key from doe_preview_cells where status='DONE' limit 1"))
    d = cache / "cells" / key[:2] / key
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("user data")
    import shutil

    shutil.rmtree(d)
    os.symlink(outside, d)
    env.sql("update doe_preview_cells set last_access_at=:t where cache_key=:k", t=past, k=key)
    out = purge_view_cache(env.engine, env.lc.settings)
    assert out["skipped"] >= 1 and (outside / "keep.txt").is_file()
    # QUEUED·RUNNING의 작업 폴더는 건너뜀
    q = _post(env, _body(ps["id"], {"kind": "lhs", "count": 6, "seed": 13}), expect=202).json()
    qd = cache / "jobs" / q["job_id"]
    qd.mkdir(parents=True, exist_ok=True)
    os.utime(qd, (t_old, t_old))
    purge_view_cache(env.engine, env.lc.settings)
    assert qd.is_dir()
    # 총량 초과 → 마지막 접근이 오래된 셀부터(합계에는 doe_preview 셀 폴더도 포함)
    from physicsai_core.config import load_config_dict

    tiny = load_config_dict({**env.lc.settings.model_dump(), "geometry": {**env.lc.settings.geometry.model_dump(),
                                                                         "view": {"cache": {"max_total_bytes": 1048576}}}}, environ={})
    (env.sroot / "_cache" / "filler.bin").write_bytes(b"\0" * 1100000)
    out = purge_view_cache(env.engine, tiny.settings)
    assert out["lru"] >= 1


def make_shell_project(root):
    """중립면 STEP + 조립 폴더(test_shell_bead.make_shell_project와 같은 모양)."""
    d = root / "shellproj"
    (d / "assem").mkdir(parents=True, exist_ok=True)
    (d / "chassis_mid.step").write_text("ISO-10303-21; mid-surface")
    (d / "assem" / "model_0000.rad").write_text("#include chassis.inc\n#include material.inc\n/BEGIN\n")
    (d / "assem" / "chassis.inc").write_text("/NODE\n2000001 0 0 0\n/SHELL/2001\n1 2000001 2000001 2000001 2000001\n")
    (d / "assem" / "material.inc").write_text("/PROP/TYPE1/1\nBracket\n")
    return d


def test_shell_set_uses_shell_view_grid_with_fixed_dir(native_env, fake_record):
    """쉘 세트: `paicad shell view grid`(`--fixed-dir` = S/native/fixed, `--tag-dir`), 셀 manifest kind=shell. 쉘 템플릿이 없으면 409 UNAVAILABLE."""
    env = native_env()
    proj = make_shell_project(env.imports)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "kind": "shell", "label": "SH"})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    psid = env.job(r.json()["job_id"])["result"]["param_set_id"]
    env.w.heartbeat_once()
    pv = _run(env, _body(psid, {"kind": "lhs", "count": 5, "seed": 2}))
    assert pv["status"] == "DONE" and pv["n_total"] == 5 and pv["tag_state"] == "tagged"
    S = env.sroot / "04_params" / psid
    calls = _calls(fake_record, "grid")
    assert not calls  # solid 명령(`view grid`)은 쓰지 않는다
    sh = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1:4] == ["shell", "view", "grid"]]
    assert sh and all(a[a.index("--fixed-dir") + 1] == str(S / "native" / "fixed") and a[a.index("--tag-dir") + 1] == str(S / "native" / "tag")
                      and a[a.index("--features") + 1].endswith("shell_features.json") for a in sh)
    man = env.c.get(f"{API}/artifacts/{pv['cells'][1]['manifest_artifact_id']}/content", headers=P).json()
    assert man["kind"] == "shell" and man["thumb"]["file"] == "thumb.png"
    # 쉘 두께(prop) 행은 행렬에는 있고 셀 값·정렬에는 없다(형상 변수만)
    assert all(not k.endswith("_SHELL_T") for c in pv["cells"] for k in c["values"])
    # 쉘 grid 템플릿 해제 → 409 DOE_PREVIEW_UNAVAILABLE(solid 템플릿은 있어도)
    env2 = native_env(commands={"paicad_shell_view_grid": None}, folder="p2")
    proj2 = make_shell_project(env2.imports)
    r2 = env2.c.post(f"{API}/studies/{env2.sid}/param-sets", headers=PW,
                     json={"path": str(proj2), "mode": "discover", "engine": "native", "kind": "shell", "label": "SH"})
    assert env2.w.run_once_slot() == "SUCCEEDED", env2.job(r2.json()["job_id"])
    psid2 = env2.job(r2.json()["job_id"])["result"]["param_set_id"]
    env2.w.heartbeat_once()
    r3 = env2.c.post(f"{API}/studies/{env2.sid}/doe-previews", headers=PW, json=_body(psid2))
    assert r3.status_code == 409 and r3.json()["detail"]["code"] == "DOE_PREVIEW_UNAVAILABLE" and r3.json()["detail"]["missing"]
