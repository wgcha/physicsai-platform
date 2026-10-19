"""V3-S17-2(API): `PUT /param-sets/{id}/responses` CURVE spec 저장·`PERF_IN_USE_BY_OPT`(진행 중 최적화가 스냅샷한 성능의
spec 변경·삭제 409, 단위만 바꾸면 200, 끝난 최적화면 200)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import text

from helpers_api import PW, _sid
from physicsai_test_support import API, make_param_set_folder

H3D = {"source": "H3D", "subcase": 1, "datatype": "CornerStress", "component": "", "layer": "", "stat": "MAX"}
CURVE = {"source": "CURVE", "series": "Node 100 / X", "stat": "ABSMAX"}


def _opt_row(engine, sid: str, ps_id: str, status: str, perfs: dict) -> str:
    oid, mid = str(uuid.uuid4()), str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(text("insert into models(id, study_id, name, version, source_path, stored_rel, psmdl_rel, psmdl_sha256,"
                       " psmdl_size, log_status, registered_by, registered_by_name) values (:i,:s,:n,1,'/x','r','r/a.psmdl',:h,1,"
                       "'MISSING','u','u')"), {"i": mid, "s": sid, "n": "m" + mid[:6], "h": "0" * 64})
        no = c.execute(text("select coalesce(max(opt_no),0)+1 from surrogate_opts where study_id=:s"), {"s": sid}).scalar()
        c.execute(text("insert into surrogate_opts(id, study_id, opt_no, param_set_id, model_id, input_kind, settings, status,"
                       " dir_rel, created_by, created_by_name) values (:o,:s,:no,:p,:m,'assembly',cast(:st as jsonb),:status,"
                       " :d,'u','u')"),
                  {"o": oid, "s": sid, "no": no, "p": ps_id, "m": mid, "status": status, "d": f"05_opt/surrogate/SO-{no:03d}",
                   "st": json.dumps({"objective": {"metric": "perf:CornerStress", "series": None, "sense": "min"},
                                     "performances": perfs})})
    return oid


def test_v3_s17_2_put_curve_and_perf_in_use(client, loaded_config, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    ps = client.post(f"{API}/studies/{sid}/param-sets", headers=PW,
                     json={"path": str(make_param_set_folder(ai / "S1" / "00_inbox"))}).json()
    url = f"{API}/param-sets/{ps['id']}/responses"
    keep = [{"name": "MaxStress", "unit": "MPa", "spec": None}, {"name": "Disp", "unit": "mm", "spec": None}]
    rows = [*keep, {"name": "CornerStress", "unit": "MPa", "spec": H3D}, {"name": "AccelPeak", "unit": "g", "spec": CURVE}]
    r = client.put(url, headers=PW, json={"responses": rows})
    assert r.status_code == 200, r.text
    assert r.json()["responses"][3]["spec"] == CURVE
    stored = ai / "S1" / "04_params" / ps["id"] / "responses.json"
    assert json.loads(stored.read_text(encoding="utf-8"))["responses"][3]["spec"] == CURVE
    bad = client.put(url, headers=PW, json={"responses": [*keep, {"name": "X", "spec": {**CURVE, "series": "a|b"}}]})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "RESPONSE_INVALID"

    oid = _opt_row(engine, sid, ps["id"], "VERIFYING", {"CornerStress": {"unit": "MPa", "spec": H3D},
                                                         "AccelPeak": {"unit": "g", "spec": CURVE}})
    for changed in ([*keep, {"name": "CornerStress", "unit": "MPa", "spec": {**H3D, "stat": "ABSMAX"}}, rows[3]],
                    [*keep, rows[2], {"name": "AccelPeak", "unit": "g", "spec": {**CURVE, "series": None}}],
                    [*keep, rows[2]],                                              # 삭제
                    [*keep, {"name": "CornerStress", "unit": "MPa", "spec": None}, rows[3]]):
        r = client.put(url, headers=PW, json={"responses": changed})
        assert r.status_code == 409, changed
        d = r.json()["detail"]
        assert d["code"] == "PERF_IN_USE_BY_OPT" and "SO-001" in d["message"] and "끝난 뒤 바꾸세요" in d["message"]
        assert d["surrogate_opt_id"] == oid
    # 단위만 바꾸기·다른 성능 추가는 허용
    ok = [*keep, {**rows[2], "unit": "kPa"}, {**rows[3], "unit": "m/s2"}, {"name": "New", "unit": "", "spec": H3D}]
    assert client.put(url, headers=PW, json={"responses": ok}).status_code == 200
    # 끝난 최적화면 자유롭게
    with engine.begin() as c:
        c.execute(text("update surrogate_opts set status='DONE' where id=:o"), {"o": oid})
    r = client.put(url, headers=PW, json={"responses": [*keep, rows[2]]})
    assert r.status_code == 200, r.text
