"""V3-S15-8·10: 표본 방식 API(phase3 §20.6·§20.7, D3-63).

- V3-S15-8: ④ 미리보기 `sampling`·`notes`·`count`·`recommended_count`, 모양 422, 작업 생성 → DB source_kind(새 값 포함),
  미리보기 행 = predict_batch_runs(7개 kind 모두), 상세 `sampling.influence_class`(kind별·소유 EXPLORE/VERIFY·TRAIN_DOE·DOE 없음),
  목록 `sampling`, Sobol 이어서 추가 생성 끝까지, openapi 스키마·operation_ids 불변.
- V3-S15-10: ① `GET /train/doe-types` desc_id·recommended·influence_class, `GET /train-does/{id}/result-table` 등급·사유·influence_ok.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from helpers_api import P, PW
from physicsai_test_support import API, H
from test_api_predict_batch import TABLE, _batch, _client, _end, _setup
from test_doe_result_table_api import _prep, _set_states, _url, _write_responses

GP = H("tok-general")


def _three_params(engine, ps_id: str) -> None:
    """현재 세트에 정수 아닌 파라미터 T_2를 더해 3개로 만든다(BBD는 변수 3개 이상)."""
    with engine.begin() as c:
        params, tpl = c.execute(text("select parameters, tpl_params from param_sets where id=:i"), {"i": ps_id}).one()
        params = [*params, {"name": "T_2", "nominal": 2.0, "min": 1.0, "max": 4.0, "unit": "mm"}]
        tpl = [*tpl, {"name": "T_2", "format": "%5.2f"}]
        c.execute(text("update param_sets set parameters=cast(:p as jsonb), tpl_params=cast(:t as jsonb) where id=:i"),
                  {"p": json.dumps(params), "t": json.dumps(tpl), "i": ps_id})


def _preview(c, sid: str, source: dict, **kw):
    return c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW, json={"source": source, **kw})


SOURCES = {
    "lhs_opt": {"kind": "lhs_opt", "count": 10, "seed": 3, "criterion": "corr"},
    "sobol": {"kind": "sobol", "count": 8, "seed": 3},
    "lhs": {"kind": "lhs", "count": 6, "seed": 7},
    "fullfact": {"kind": "fullfact", "levels": {"THK_1": 3, "N_RIB": 3, "T_2": 2}},
    "fracfact": {"kind": "fracfact", "resolution": 4},
    "pb": {"kind": "pb"},
    "bbd": {"kind": "bbd"},
    "ccd": {"kind": "ccd", "alpha": "inscribed"},
    "table": {"kind": "table", "text": TABLE.replace("N_RIB", "N_RIB\tT_2").replace("\n3.0\t4", "\n3.0\t4\t2").replace("\n2.5\t5", "\n2.5\t5\t2")
              .replace("\n4.0\t7", "\n4.0\t7\t3")},
}
EXPECT = {  # kind → (method, label, desc_id, class, 안내 문구 일부, recommended_count(k = 3))
    "lhs_opt": ("LHS_OPT", "최적화 LHS", "lhs_opt", "formal", None, 30),
    "sobol": ("SOBOL", "Sobol(스크램블 QMC)", "sobol", "formal", None, 32),
    "lhs": ("LHS", "LHS(무작위 층화)", "lhs", "formal", None, 30),
    "fullfact": ("FULLFACT", "전체 요인", "fullfact", "formal", None, None),
    "fracfact": ("FRACFACT", "부분 요인(2수준)", "fracfact", "reference", "해상도 IV", None),
    "pb": ("PB", "Plackett–Burman", "pb", "reference", "Plackett–Burman", None),
    "bbd": ("BBD", "Box–Behnken", "bbd", "reference", "2차 응답면 설계", None),
    "ccd": ("CCD", "중심 합성(CCD)", "ccd", "reference", "2차 응답면 설계", None),
    "table": ("TABLE", "표 붙여넣기 / CSV", "table", "reference", "직접 만든 표", None),
}


def test_v3_s15_8_preview_job_detail_list_all_kinds(client, loaded_config, worker_factory, engine):
    from physicsai_core.db.repositories import predict_batches as pb_repo

    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, ps = _setup(client, worker_factory(), ai)
    _three_params(engine, ps["id"])
    batch_ids: dict[str, str] = {}
    for kind, src in SOURCES.items():
        method, label, desc_id, cls, note_part, rec = EXPECT[kind]
        r = _preview(client, sid, src)
        assert r.status_code == 200, (kind, r.text)
        pv = r.json()
        assert pv["problems"] == [] and pv["count"] == len(pv["rows"]) and pv["count"] > 0, (kind, pv["problems"])
        sp = pv["sampling"]
        assert (sp["kind"], sp["method"], sp["label"], sp["desc_id"], sp["influence_class"]) == (kind, method, label, desc_id, cls)
        assert (note_part is None) == (sp["influence_note"] is None) and (note_part is None or note_part in sp["influence_note"])
        assert sp["recommended_count"] == rec, kind
        assert isinstance(sp["meta"], dict) and isinstance(pv["notes"], list)
        if kind in ("lhs_opt", "sobol", "lhs"):                                    # 공간 채움 계열은 품질 지표
            assert set(sp["meta"]["quality"]) == {"min_dist", "max_abs_corr"}, kind
        else:
            assert "quality" not in sp["meta"], kind
        # 작업 생성 → DB source_kind, 저장 params.source = {kind, **meta}, 행 = 미리보기 행
        r = _batch(client, sid, src, me=2)
        assert r.status_code == 201, (kind, r.text)
        job = r.json()
        bid = job["params"]["batch_id"]
        batch_ids[kind] = bid
        stored = dict(sp["meta"])
        if kind == "lhs":
            stored.pop("quality")                                                  # lhs는 meta에 저장하지 않고 API가 계산
        assert job["params"]["source"] == {"kind": kind, **stored}, kind
        with engine.connect() as conn:
            b = pb_repo.get(conn, bid)
            runs = pb_repo.runs(conn, bid)
        assert (b["source_kind"], b["run_count"]) == (method, pv["count"])
        assert [{k: x[k] for k in ("doe_no", "run_key", "values", "applied_values", "out_of_range")} for x in runs] == pv["rows"], kind
        _end(engine, job["id"], "FAILED", failure_code="EXIT_NONZERO")

    # 상세: sampling(등급·meta, recommended_count null), 목록: sampling 요약
    for kind, bid in batch_ids.items():
        method, label, desc_id, cls, note_part, _rec = EXPECT[kind]
        d = client.get(f"{API}/predict-batches/{bid}", headers=P).json()
        assert d["source_kind"] == method
        sp = d["sampling"]
        assert (sp["kind"], sp["method"], sp["label"], sp["desc_id"], sp["influence_class"]) == (kind, method, label, desc_id, cls)
        assert sp["recommended_count"] is None and (note_part is None or note_part in sp["influence_note"])
        if kind == "lhs":
            assert set(sp["meta"]["quality"]) == {"min_dist", "max_abs_corr"}      # 기존 LHS 행에도 계산
    lst = {x["id"]: x for x in client.get(f"{API}/studies/{sid}/predict-batches", headers=P).json()}
    assert lst[batch_ids["sobol"]]["sampling"] == {"kind": "sobol", "method": "SOBOL", "label": "Sobol(스크램블 QMC)", "count": 8,
                                                   "seed": 3, "offset": 0}
    assert lst[batch_ids["lhs_opt"]]["sampling"]["seed"] == 3 and lst[batch_ids["lhs_opt"]]["sampling"]["offset"] is None
    assert lst[batch_ids["table"]]["sampling"] == {"kind": "table", "method": "TABLE", "label": "표 붙여넣기 / CSV", "count": 3,
                                                    "seed": None, "offset": None}
    # 세부 문구 확인
    fr = client.get(f"{API}/predict-batches/{batch_ids['fracfact']}", headers=P).json()["sampling"]
    assert fr["influence_note"] == ("부분 요인(해상도 IV) — 2인자 교호작용끼리 교락되어 영향도는 참고용입니다"
                                    "(주효과는 2인자 교호작용과 교락 없음)")


def test_v3_s15_8_preview_notes_and_problems(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, ps = _setup(client, worker_factory(), ai)
    # 변수 2개(THK_1, N_RIB): 정수 변수 + 작은 run → 안내
    pv = _preview(client, sid, {"kind": "lhs_opt", "count": 4}).json()
    assert [n["code"] for n in pv["notes"]] == ["INFLUENCE_TOO_FEW"] and pv["count"] == 4
    assert pv["notes"][0]["message"] == "run이 5개보다 적어 ⑤ 영향도는 계산되지 않습니다"
    pv = _preview(client, sid, {"kind": "fracfact"}).json()                           # k = 2 → 전체 요인
    assert pv["count"] == 4 and [n["code"] for n in pv["notes"]][0] == "FULL_FACTORIAL_USED"
    # 문제는 200 problems + sampling은 채움
    for src, code in [({"kind": "bbd"}, "DESIGN_UNSUPPORTED"), ({"kind": "sobol", "count": 6}, "COUNT_NOT_POW2"),
                      ({"kind": "fullfact", "levels": {"THK_1": 11}}, None), ({"kind": "fullfact", "levels": {"N_RIB": 9}}, "LEVELS_INVALID"),
                      ({"kind": "lhs_opt", "count": 0}, "TOO_FEW_ROWS"), ({"kind": "pb", "ranges": {"THK_1": [5, 2]}}, "RANGE_INVALID"),
                      ({"kind": "sobol", "count": 8, "continue_from": "nope"}, "CONTINUE_INVALID")]:
        r = _preview(client, sid, src)
        if code is None:
            assert r.status_code == 422
            continue
        assert r.status_code == 200, (src, r.text)
        body = r.json()
        assert [p["code"] for p in body["problems"]] == [code] and body["rows"] == [] and body["count"] == 0, (src, body["problems"])
        assert body["sampling"]["kind"] == src["kind"] and isinstance(body["sampling"]["meta"], dict)
        # 같은 문제는 생성에서 422 BATCH_SOURCE_INVALID
        g = _batch(client, sid, src)
        assert g.status_code == 422 and g.json()["detail"]["code"] == "BATCH_SOURCE_INVALID"
        assert [p["code"] for p in g.json()["detail"]["problems"]] == [code]
    # 정수 변수 수준 초과 메시지(N_RIB 2~8 → 최대 7수준)
    msg = _preview(client, sid, {"kind": "fullfact", "levels": {"N_RIB": 9}}).json()["problems"][0]["message"]
    assert msg.startswith("'N_RIB'은 정수 변수라 2~8에서 최대 7수준입니다")
    assert ps["id"]


def test_v3_s15_8_shape_errors_422(client, loaded_config, worker_factory):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, _ps = _setup(client, worker_factory(), ai)
    for bad in [{"kind": "nope"}, {"kind": "fracfact", "resolution": 3}, {"kind": "fracfact", "resolution": "5"},
                {"kind": "ccd", "alpha": "rotatable"}, {"kind": "sobol", "count": 8, "seed": -1},
                {"kind": "sobol", "count": 8, "seed": 4294967296}, {"kind": "lhs_opt", "count": 8, "seed": -1},
                {"kind": "lhs_opt", "count": 8, "criterion": "x"}, {"kind": "fullfact", "levels": {"THK_1": 11}},
                {"kind": "fullfact", "levels": {"THK_1": 0}}, {"kind": "pb", "extra": 1}, {"kind": "bbd", "count": 3},
                {"kind": "sobol", "count": 8, "continue_from": "x" * 65}, {"kind": "lhs_opt"}]:
        r = _preview(client, sid, bad)
        assert r.status_code == 422, (bad, r.text)
        g = _batch(client, sid, bad)
        assert g.status_code == 422 and g.json()["detail"]["code"] == "INVALID_PARAMS", (bad, g.text)


def test_v3_s15_8_sobol_continue_end_to_end(client, loaded_config, worker_factory, engine):
    from physicsai_core.db.repositories import predict_batches as pb_repo

    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, _ps = _setup(client, worker_factory(), ai)
    first = _batch(client, sid, {"kind": "sobol", "count": 8, "seed": 5}, me=2).json()
    b1 = first["params"]["batch_id"]
    _end(engine, first["id"], "FAILED", failure_code="EXIT_NONZERO")
    # 미리보기: 이어서 추가 notes·meta·권장 개수
    cont = {"kind": "sobol", "count": 8, "continue_from": b1}
    pv = _preview(client, sid, cont).json()
    assert pv["problems"] == [] and pv["count"] == 8
    assert {"code": "SEQUENCE_CONTINUED", "message": "B-001과 합치면 16개(균형 유지)"} in pv["notes"]
    m = pv["sampling"]["meta"]
    assert (m["offset"], m["seed"], m["count"]) == (8, 5, 8) and m["continue_from"] == {"batch_id": b1, "label": "B-001"}
    assert pv["sampling"]["recommended_count"] == 8
    both = _preview(client, sid, {"kind": "sobol", "count": 16, "seed": 5}).json()["rows"]
    assert [r["values"] for r in pv["rows"]] == [r["values"] for r in both[8:]]          # 두 배치 값이 겹치지 않고 이어짐
    # 생성 끝까지: DB 행·offset·목록 요약
    r = _batch(client, sid, cont, me=2)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["params"]["source"]["offset"] == 8 and job["params"]["source"]["continue_from"] == {"batch_id": b1, "label": "B-001"}
    b2 = job["params"]["batch_id"]
    with engine.connect() as conn:
        runs = pb_repo.runs(conn, b2)
    assert [x["values"] for x in runs] == [x["values"] for x in pv["rows"]] and [x["doe_no"] for x in runs] == list(range(1, 9))
    lst = {x["id"]: x for x in client.get(f"{API}/studies/{sid}/predict-batches", headers=P).json()}
    assert lst[b2]["sampling"] == {"kind": "sobol", "method": "SOBOL", "label": "Sobol(스크램블 QMC)", "count": 8, "seed": 5, "offset": 8}
    _end(engine, job["id"], "FAILED", failure_code="EXIT_NONZERO")
    # 이어서 추가한 배치를 다시 이어서(offset 16) + 균형 아님 안내
    pv3 = _preview(client, sid, {"kind": "sobol", "count": 4, "continue_from": b2}).json()
    assert pv3["problems"] == [] and pv3["sampling"]["meta"]["offset"] == 16
    assert any("합계는 균형 아님" in n["message"] and "20개" in n["message"] for n in pv3["notes"])
    # 거부: seed·ranges 함께, 나누어떨어지지 않음, 다른 종류, 없는 배치, 변조
    for body, reason in [({**cont, "seed": 2}, "시드·범위를 그대로"), ({**cont, "ranges": {"THK_1": [2, 3]}}, "시드·범위를 그대로"),
                         ({**cont, "count": 16}, "나누어떨어지게"), ({**cont, "continue_from": "no-such"}, "찾을 수 없습니다")]:
        bad = _preview(client, sid, body).json()
        assert [p["code"] for p in bad["problems"]] == ["CONTINUE_INVALID"] and reason in bad["problems"][0]["message"], body
    other = _batch(client, sid, {"kind": "pb"}).json()
    ob = other["params"]["batch_id"]
    _end(engine, other["id"], "FAILED", failure_code="EXIT_NONZERO")
    bad = _preview(client, sid, {**cont, "continue_from": ob}).json()
    assert bad["problems"][0]["code"] == "CONTINUE_INVALID" and bad["problems"][0]["message"] == "Sobol 배치가 아닙니다"
    with engine.begin() as conn:                                                           # 저장 값 변조
        conn.execute(text("""update predict_batch_runs set "values" = jsonb_set("values", '{THK_1}', '9.99'::jsonb)"""
                          " where batch_id=:b and doe_no=2"), {"b": b1})
    bad = _preview(client, sid, cont).json()
    assert [p["code"] for p in bad["problems"]] == ["SEQUENCE_MISMATCH"]
    g = _batch(client, sid, cont)
    assert g.status_code == 422 and g.json()["detail"]["problems"][0]["code"] == "SEQUENCE_MISMATCH"


def test_v3_s15_8_detail_influence_owned_and_train_doe(client, loaded_config, worker_factory, engine, monkeypatch):
    from physicsai_api.services import predict_batches as svc

    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, _ps = _setup(client, worker_factory(), ai)
    job = _batch(client, sid, {"kind": "lhs", "count": 6, "seed": 2}).json()
    bid = job["params"]["batch_id"]

    def cls(**kw):
        d = client.get(f"{API}/predict-batches/{bid}", headers=P).json()
        return d["sampling"]["influence_class"], d["sampling"]["influence_note"]

    # 최적화 소유: EXPLORE는 그 배치 kind대로(LHS formal), VERIFY·FINAL은 reference(kind보다 우선)
    monkeypatch.setattr(svc.so_repo, "owned_iter_of_batch", lambda conn, b: {"kind": "EXPLORE", "opt_id": "o", "opt_no": 1})
    assert cls() == ("formal", None)
    for kind in ("VERIFY", "FINAL"):
        monkeypatch.setattr(svc.so_repo, "owned_iter_of_batch", lambda conn, b, k=kind: {"kind": k, "opt_id": "o", "opt_no": 1})
        assert cls() == ("reference", "최적화 검증 배치 — 최적점 근처에 모인 표본이라 영향도는 참고용입니다")
    monkeypatch.undo()
    assert cls() == ("formal", None)                                                       # 재사용(소유 아님) = kind대로

    # TRAIN_DOE: ① 유형을 따른다 / DOE 없음 = reference
    with engine.begin() as conn:
        conn.execute(text("update predict_batches set source_kind='TRAIN_DOE', source_meta=cast(:m as jsonb) where id=:b"),
                     {"m": json.dumps({"doe_id": "doe-x"}), "b": bid})
    assert cls() == ("reference", "원본 ① DOE 정보를 찾을 수 없어 영향도는 참고용입니다")
    doe = {"doe_type": "TYPE_SOBOL", "options": {}}
    monkeypatch.setattr(svc.train_repo, "get_doe", lambda conn, i: doe if i == "doe-x" else None)
    assert cls() == ("formal", None)
    doe.update(doe_type="TYPE_FRACFACT", options={"RESOLUTION": "3"})
    assert cls() == ("reference", "부분 요인(해상도 III) — 주효과가 2인자 교호작용과 교락되어 영향도는 참고용입니다")
    doe.update(options={"RESOLUTION": "5"})
    assert cls()[1].startswith("부분 요인(해상도 V)")
    d = client.get(f"{API}/predict-batches/{bid}", headers=P).json()["sampling"]
    assert (d["kind"], d["method"], d["desc_id"]) == ("train_doe", "TRAIN_DOE", "train_doe")


def test_v3_s15_8_openapi_schema_and_operation_ids():
    from physicsai_api.export_openapi import build_openapi

    spec = build_openapi()
    comps = spec["components"]["schemas"]
    for name in ("BatchSourceLhsOpt", "BatchSourceSobol", "BatchSourceFullfact", "BatchSourceFracfact", "BatchSourcePb",
                 "BatchSourceBbd", "BatchSourceCcd", "BatchNote", "SamplingInfo", "SamplingSummary", "DoeResultSampling"):
        assert name in comps, name
    assert {"notes", "sampling"} <= set(comps["PredictBatchPreview"]["properties"])
    assert "sampling" in comps["PredictBatch"]["properties"] and "sampling" in comps["PredictBatchSummary"]["properties"]
    assert {"desc_id", "recommended", "influence_class"} <= set(comps["DoeType"]["properties"])
    assert {"sampling", "influence_class", "influence_note", "influence_ok"} <= set(comps["DoeResultTable"]["properties"])
    union = comps["PredictBatchPreviewRequest"]["properties"]["source"]
    kinds = set(union["discriminator"]["mapping"])
    assert kinds == {"lhs", "lhs_opt", "sobol", "fullfact", "fracfact", "pb", "bbd", "ccd", "table", "train_doe"}
    committed = json.loads((Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8"))
    assert committed == spec


# ---- V3-S15-10 ① doe-types · result-table ------------------------------------------------------------------------


def test_v3_s15_10_doe_types_decoration(p2_env, engine, fake_dashboard):
    c, _mk, _ai, _lc, d = p2_env
    types = c.get(f"{API}/train/doe-types", headers=P).json()
    by = {t["value"]: t for t in types}
    assert [t["label"] for t in types] == ["FullFact", "FracFact", "LatinHyperCube", "Sobol"]            # 정의 파일 그대로(원본 순서)
    assert {v: t["desc_id"] for v, t in by.items()} == {"TYPE_FULLFACT": "hs_fullfact", "TYPE_FRACFACT": "hs_fracfact",
                                                         "TYPE_LATINHYPERCUBE": "hs_lhs", "TYPE_SOBOL": "hs_sobol"}
    assert {v: t["influence_class"] for v, t in by.items()} == {"TYPE_FULLFACT": "formal", "TYPE_FRACFACT": "reference",
                                                                "TYPE_LATINHYPERCUBE": "formal", "TYPE_SOBOL": "formal"}
    assert [t["value"] for t in types if t["recommended"]] == ["TYPE_LATINHYPERCUBE"]                    # 기본 추천 LHS
    assert by["TYPE_FRACFACT"]["fields"][0]["key"] == "RESOLUTION" and by["TYPE_SOBOL"]["default_runs"] == 7  # 기존 필드 무변경
    for rec, want in [("TYPE_SOBOL", ["TYPE_SOBOL"]), ("TYPE_NOT_THERE", []), ("", [])]:
        with _client(d, engine, fake_dashboard, train_data={"recommended_doe_type": rec}) as (c2, lc2):
            assert lc2.settings.train_data.recommended_doe_type == rec
            got = c2.get(f"{API}/train/doe-types", headers=P).json()
            assert [t["value"] for t in got if t["recommended"]] == want, rec


def test_v3_s15_10_result_table_influence_class(p2_env, engine):
    name = "RTI"
    c, ai, _sid, doe_id = _prep(p2_env, name, runs=7)
    keys = [r["run_key"] for r in c.get(f"{API}/train-does/{doe_id}/samples", headers=P).json()["rows"]]

    def table():
        r = c.get(_url(doe_id), headers=GP)
        assert r.status_code == 200, r.text
        return r.json()

    def set_type(t: str, options: dict | None = None):
        from physicsai_core.db.repositories import train as train_repo

        with engine.begin() as conn:
            train_repo.set_doe(conn, doe_id, doe_type=t, **({"options": options} if options is not None else {}))

    # off: 응답 없음
    d = table()
    assert (d["influence_class"], d["influence_ok"]) == ("off", False) and d["influence_note"] == "응답이 없어 영향도를 계산할 수 없습니다"
    assert d["sampling"]["method"] == "TYPE_LATINHYPERCUBE" and d["sampling"]["label"] == "LatinHyperCube"
    assert d["sampling"]["desc_id"] == "hs_lhs" and isinstance(d["sampling"]["options"], dict)
    # off: 유효 run 부족(p+2 또는 5 중 큰 값)
    need = max(5, len(d["parameters"]) + 2)
    few = "run_key,MaxStress\n" + "".join(f"{k},{10 + i}\n" for i, k in enumerate(keys[:need - 1]))
    _write_responses(engine, ai, name, doe_id, few)
    d = table()
    assert d["counts"]["usable"] == need - 1
    assert (d["influence_class"], d["influence_ok"]) == ("off", False)
    assert d["influence_note"] == f"영향도에는 유효 run이 {need}개 이상 필요합니다(현재 {need - 1}개)"
    # formal: LHS·Sobol·FullFact
    full = "run_key,MaxStress\n" + "".join(f"{k},{10 + i}\n" for i, k in enumerate(keys))
    _write_responses(engine, ai, name, doe_id, full)
    _set_states(engine, doe_id, {k: "COLLECTED" for k in keys})
    for t, desc in [("TYPE_LATINHYPERCUBE", "hs_lhs"), ("TYPE_SOBOL", "hs_sobol"), ("TYPE_FULLFACT", "hs_fullfact")]:
        set_type(t)
        d = table()
        assert (d["influence_class"], d["influence_note"], d["influence_ok"]) == ("formal", None, True), t
        assert d["sampling"]["method"] == t and d["sampling"]["desc_id"] == desc
    # reference: FracFact는 RESOLUTION별 문구
    for res, head in [("3", "부분 요인(해상도 III)"), ("4", "부분 요인(해상도 IV)"), ("5", "부분 요인(해상도 V)")]:
        set_type("TYPE_FRACFACT", {"RESOLUTION": res})
        d = table()
        assert (d["influence_class"], d["influence_ok"]) == ("reference", True), res
        assert d["influence_note"].startswith(head) and "참고용" in d["influence_note"]
        assert d["sampling"] == {"method": "TYPE_FRACFACT", "label": "FracFact", "desc_id": "hs_fracfact",
                                 "options": {"RESOLUTION": res}}
    # reference: 모르는 유형
    set_type("TYPE_MYSTERY", {})
    d = table()
    assert (d["influence_class"], d["influence_ok"], d["influence_note"]) == ("reference", True, "표본 방식을 알 수 없어 영향도는 참고용입니다")
    assert d["sampling"]["desc_id"] is None and d["sampling"]["label"] == "TYPE_MYSTERY"
    # influence_ok = class != off, V3-S14-1의 나머지(응답 표·counts)는 그대로
    assert d["counts"] == {"total": 7, "usable": 7, "no_response": 0} and [r["run_id"] for r in d["rows"]] == keys
    assert pytest.approx(d["rows"][0]["responses"]["MaxStress"]) == 10.0
