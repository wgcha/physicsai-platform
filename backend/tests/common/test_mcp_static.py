"""mcp.md 정적 시험: V-MCP-5(감사 insert 인자 고정)·V-MCP-6(x-mcp)·V-MCP-7(작업 종류)·V-MCP-8(요약 봉투)·
V-MCP-9(생성기)·V-MCP-10(용어집)."""

from __future__ import annotations

import ast
import json
import re
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from physicsai_test_support import REPO

API_MCP = REPO / "backend" / "physicsai_api" / "mcp"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    from physicsai_api.export_openapi import build_openapi

    return build_openapi()


def _ops(spec):
    return [(p, m, o) for p, it in spec["paths"].items() for m, o in it.items() if isinstance(o, dict)]


def _deref(spec, node):
    ref = node.get("$ref") if isinstance(node, dict) else None
    return spec["components"]["schemas"][ref.rsplit("/", 1)[1]] if ref else node


def _numeric(ps: dict[str, Any]) -> bool:
    types = {ps.get("type")} | {x.get("type") for x in ps.get("anyOf") or [] if isinstance(x, dict)}
    return bool(types & {"integer", "number"})


def _bounded(ps: dict[str, Any]) -> bool:
    cands = [ps, *[x for x in ps.get("anyOf") or [] if isinstance(x, dict)]]
    return any(k in c for c in cands for k in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "enum")) \
        or "~" in str(ps.get("description") or "")


def _has_unit(ps: dict[str, Any]) -> bool:
    return "x-unit" in ps or bool(re.search(r"\[[^\]]+\]", str(ps.get("description") or "")))


# ---- V-MCP-6 -----------------------------------------------------------------------------------------


def test_v_mcp_6_every_operation_marked_or_frozen(spec):
    from physicsai_api.mcp.route_policy import LEGACY_UNMARKED, RISKS

    ids = set()
    missing = []
    for path, method, op in _ops(spec):
        oid = op["operationId"]
        ids.add(oid)
        x = op.get("x-mcp")
        if x is None:
            if oid not in LEGACY_UNMARKED:
                missing.append(f"{method} {path}")
            continue
        assert oid not in LEGACY_UNMARKED, f"x-mcp가 붙은 {oid}는 동결 목록에서 지우세요"
        if "tool" in x:
            assert x["risk"] in RISKS and x["confirm"] in ("never", "by_kind", "always") and isinstance(x["version"], int), oid
            assert x.get("summary_ko") and x.get("summary_en"), oid
        else:
            assert isinstance(x.get("exclude"), str) and x["exclude"].strip(), f"{oid}: 제외 사유 필수"
    assert missing == [], f"x-mcp 누락(새 operation): {missing}"
    assert sorted(LEGACY_UNMARKED - ids) == [], "동결 목록에 없는 operationId — 목록에서 지우세요"
    tools = [o["x-mcp"]["tool"] for _, _, o in _ops(spec) if "tool" in (o.get("x-mcp") or {})]
    assert len(tools) == len(set(tools))


def test_v_mcp_6_tool_operation_requirements(spec):
    problems = []
    for path, method, op in _ops(spec):
        x = op.get("x-mcp") or {}
        if "tool" not in x:
            continue
        t = x["tool"]
        if not op.get("summary") or not op.get("description"):
            problems.append(f"{t}: summary·description")
        for prm in op.get("parameters") or []:
            sch = prm.get("schema") or {}
            if not prm.get("description"):
                problems.append(f"{t}: 인자 {prm['name']} description")
            if _numeric(sch) and not (_bounded(sch) and _has_unit({**sch, "description": prm.get("description")})):
                problems.append(f"{t}: 수치 인자 {prm['name']} 단위·범위")
        body = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema")
        if body:
            b = _deref(spec, body)
            if not b.get("examples"):
                problems.append(f"{t}: 요청 examples")
            for name, ps in (b.get("properties") or {}).items():
                if not ps.get("description"):
                    problems.append(f"{t}: 본문 {name} description")
                if _numeric(ps) and not (_bounded(ps) and _has_unit(ps)):
                    problems.append(f"{t}: 본문 수치 {name} 단위·범위")
        ok = [c for c in ("200", "201", "202") if c in op.get("responses", {})]
        if not ok or not (op["responses"][ok[0]].get("content") or {}).get("application/json", {}).get("schema"):
            problems.append(f"{t}: 응답 모델")
        if not any(str(c).startswith("4") and op["responses"][c].get("description") for c in op.get("responses", {})):
            problems.append(f"{t}: 오류 code 목록")
    assert problems == []


def test_v_mcp_6_contract_tool_list(spec):
    tools = sorted(o["x-mcp"]["tool"] for _, _, o in _ops(spec) if "tool" in (o.get("x-mcp") or {}))
    assert tools == sorted(["whoami", "system_status", "list_studies", "get_summary", "get_glossary", "check_prediction_input",
                            "list_job_kinds", "describe_job_kind", "plan_job", "run_job", "list_jobs", "job_status", "job_summary",
                            "cancel_job", "list_audit", "ping", "get_native_vars"])
    by = {o["x-mcp"]["tool"]: o for _, _, o in _ops(spec) if "tool" in (o.get("x-mcp") or {})}
    assert by["run_job"]["x-mcp"]["risk"] == "run" and by["cancel_job"]["x-mcp"]["risk"] == "run"
    assert by["list_audit"]["x-mcp"]["risk"] == "admin" and by["plan_job"]["x-mcp"]["risk"] == "read"
    # 기존 operationId 불변(도구 이름은 x-mcp가 단일 출처)
    assert by["whoami"]["operationId"] == "me_physicsai_api_me_get"
    assert by["plan_job"]["operationId"] == "plan_job"


# ---- V-MCP-7 -----------------------------------------------------------------------------------------


def test_v_mcp_7_job_types_covered():
    from physicsai_api.mcp.job_kinds import JOB_KINDS, MCP_JOB_EXCLUDED
    from physicsai_api.mcp.summaries import SUMMARIES
    from physicsai_core.job_types import JOB_TYPES

    covered = {jt for k in JOB_KINDS.values() for jt in k.job_types}
    assert set(JOB_TYPES) - covered - set(MCP_JOB_EXCLUDED) == set(), "새 job_type은 JOB_KINDS 등록 또는 MCP_JOB_EXCLUDED+사유"
    assert covered & set(MCP_JOB_EXCLUDED) == set() and set(MCP_JOB_EXCLUDED) <= set(JOB_TYPES)
    assert all(v.strip() for v in MCP_JOB_EXCLUDED.values())
    assert set(JOB_KINDS) == {"doe_generate", "solve_pbs", "predict", "predict_batch", "surrogate_opt", "surrogate_opt_verify",
                              "equiv_check", "fem_verify", "geom_preview"}
    for k in JOB_KINDS.values():
        assert callable(k.plan_fn) and callable(k.create_fn) and k.summary_entity in SUMMARIES, k.kind
        assert k.cost in ("heavy", "light") and k.version >= 1 and k.label_ko and k.stage
        props = k.params_model.model_json_schema().get("properties") or {}
        assert props, k.kind
        for name, ps in props.items():
            assert ps.get("description"), f"{k.kind}.{name} 설명"
            if _numeric(ps):
                assert _bounded(ps) and _has_unit(ps), f"{k.kind}.{name} 단위·범위"
        k.params_model.model_validate(k.example)  # 예시가 스키마를 통과


class _Fake:
    """가짜 서비스 모듈: 모든 속성 호출을 기록하고 정해 둔 값을 돌려준다."""

    def __init__(self, name: str, log: list[str], returns: dict[str, Any]) -> None:
        self._name, self._log, self._ret = name, log, returns

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)

        def fn(*a: Any, **kw: Any) -> Any:
            self._log.append(f"{self._name}.{attr}")
            v = self._ret.get(f"{self._name}.{attr}", self._ret.get(attr, {}))
            return v(*a, **kw) if callable(v) else v
        return fn


def test_v_mcp_7_plan_and_create_call_existing_services(monkeypatch):
    """plan_fn·create_fn은 기존 서비스 함수만 호출(가짜 서비스 주입)."""
    from physicsai_api.mcp import job_kinds as jk
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import studies as studies_repo
    from physicsai_core.db.repositories import surrogate_opts as so_repo
    from physicsai_core.db.repositories import train as train_repo

    log: list[str] = []
    returns = {
        "parse_params": lambda jt, p: SimpleNamespace(**p),
        "prepare": ({"num_runs": 4, "multi_execution": 2, "doe_id": "d1", "run_keys": ["r1", "r2"]}, None, []),
        "create_job": {"id": "job-1", "result": {"doe_id": "d1", "batch_id": "b1"}, "params": {}},
        "preview": {"count": 3, "estimate_min": 1.5, "problems": [], "notes": [], "max_total_runs": 9, "pairing": {"n_pairs": 2},
                    "extract": {"copy_bytes": 10}, "source_label": "x", "hpc_mode": "none", "input_kind": "assembly"},
        "create": {"id": "ent-1", "current_job_id": "job-2", "job_id": "job-3", "eq_id": "eq-1", "job": {"id": "job-4"}},
        "verify": {"job_id": "job-5"},
        "get_opt": {"label": "OPT-1", "status": "DONE", "param_set": {}},
        "get_param_set": {"study_id": "s1", "engine": "native", "label": "ps"},
        "create_preview": ({"id": "pv-1", "job_id": "job-6", "status": "QUEUED"}, 202),
        "predict_check": {"out_of_range": []},
        "_estimate_min": 2.0,
    }
    monkeypatch.setattr(jk, "_svc", lambda name: _Fake(name, log, returns))
    monkeypatch.setattr(studies_repo, "get", lambda conn, sid: {"id": sid, "title": "S"})
    monkeypatch.setattr(train_repo, "runs_for_doe", lambda conn, d: [])
    monkeypatch.setattr(train_repo, "get_doe", lambda conn, d: {"doe_label": "L"})
    monkeypatch.setattr(jobs_repo, "list_with_study_title", lambda conn, **kw: [])
    monkeypatch.setattr(so_repo, "get", lambda conn, oid: {"study_id": "s1"})

    @contextmanager
    def cm():
        yield SimpleNamespace()

    s = SimpleNamespace(train_data=SimpleNamespace(max_multi_execution=8), surrogate_opt=SimpleNamespace(max_extra_points=50),
                        mcp=SimpleNamespace(require_confirm_for_token=True))
    ctx = SimpleNamespace(settings=s, engine=SimpleNamespace(connect=cm, begin=cm),
                          hpc=SimpleNamespace(availability=lambda: SimpleNamespace(mode="none")))
    for k in jk.JOB_KINDS.values():
        p = k.params_model.model_validate(k.example)
        log.clear()
        frag = k.plan_fn(ctx, SimpleNamespace(), "s1", p)
        assert isinstance(frag, dict) and "problems" in frag and log, k.kind
        assert all(x.split(".")[0] in ("job_params", "job_params.study_manage", "predict_batches", "surrogate_opts", "equiv_check",
                                       "fem_verify", "stage4_predict") for x in log), (k.kind, log)
        log.clear()
        out, job_id, _ent = k.create_fn(ctx, SimpleNamespace(), "s1", p, "rid", None)
        assert job_id and log, (k.kind, log)
        assert any(x.endswith((".create_job", ".create", ".verify", ".create_preview")) for x in log), (k.kind, log)


# ---- V-MCP-8 -----------------------------------------------------------------------------------------


def test_v_mcp_8_envelope_and_truncation():
    from physicsai_api.mcp import summaries as sm
    from physicsai_api.mcp.job_kinds import JOB_KINDS

    assert {k.summary_entity for k in JOB_KINDS.values()} <= set(sm.SUMMARIES)
    assert set(sm.SUMMARIES) == {"study", "param_set", "train_doe", "predict_run", "predict_batch", "surrogate_opt", "equiv_check",
                                 "fem_verify", "geom_preview", "job"}
    rows = [{"run_key": f"run__{i}", "values": {"THK_1": i * 0.1, "RIB_T": 2.0}, "responses": {"MASS": 1.0 + i}, "path": "/abs/x"}
            for i in range(5000)]
    facts = sm.facts_of({"title": "t", "dir": "D:\\AI\\x", "note": "/home/u/a", "n": 3, "nested": {"a": 1}})
    assert facts == {"title": "t", "n": 3}
    env = sm.envelope("predict_batch", "b1", "배치", "DONE", facts,
                      [sm.table("runs", rows, 500, expand=("values", "responses"), units={"THK_1": "mm", "MASS": "kg"})])
    out = sm.fit(env, 8192)
    js = json.dumps(out, ensure_ascii=False, default=str)
    assert out["truncated"] is True and out["bytes"] <= 8192 and len(js.encode()) <= 8192
    assert "/abs/x" not in js and out["tables"][0]["total_rows"] == 5000
    assert "THK_1[mm]" in out["tables"][0]["columns"] and set(out) == {"entity", "id", "title", "state", "as_of", "facts", "tables",
                                                                         "links", "truncated", "bytes"}
    small = sm.fit(sm.envelope("job", "j", "t", "QUEUED", {"a": 1}), 8192)
    assert small["truncated"] is False and 0 < small["bytes"] < 8192


# ---- V-MCP-9 -----------------------------------------------------------------------------------------


def test_v_mcp_9_generator_deterministic_and_fresh():
    from physicsai_api.mcp import toolspec as ts

    a, b = ts.generate(), ts.generate()
    assert a == b
    disk = ts.read_disk()
    assert {f: disk[f] for f in ts.FILES} == a, "python scripts/gen_tool_specs.py 로 다시 생성하세요"
    oai = json.loads(a["tools.openai.json"])
    names = [f["function"]["name"] for f in oai]
    assert names == sorted(names) and len(names) == 17
    for f in oai:
        params = f["function"]["parameters"]
        assert not ({"oneOf", "anyOf", "allOf"} & set(params)) and params["type"] == "object" and f["function"]["strict"] is False
    plan = next(f for f in oai if f["function"]["name"] == "plan_job")["function"]["parameters"]["properties"]
    assert "params" not in plan and plan["params_json"]["type"] == "string"  # 자유 객체 → params_json 문자열(§9)
    mcp = json.loads(a["tools.mcp.json"])
    assert mcp["schema_version"] == 1 and mcp["generated_from"].startswith("openapi ")
    assert all(set(t) == {"name", "description", "inputSchema", "annotations", "x-http"} for t in mcp["tools"])
    run_http = next(t for t in mcp["tools"] if t["name"] == "run_job")["x-http"]
    assert run_http["json_string_fields"] == {"params_json": "params"} and run_http["path"] == "/api/mcp/jobs"
    assert "/home/" not in a["tools.mcp.json"] and "T0" not in mcp["generated_from"]


def test_v_mcp_9_compat_rules():
    from physicsai_api.mcp import toolspec as ts

    def doc(props, req, deprecated=False, name="t"):
        return {"tools": [{"name": name, "inputSchema": {"properties": props, "required": req},
                           "annotations": {"x-deprecated": deprecated}}]}

    base = doc({"a": {"type": "string"}, "b": {"type": "integer"}}, ["a"])
    assert ts.compat_problems(base, base) == []
    assert ts.compat_problems(base, doc({"a": {"type": "string"}, "b": {"type": "integer"}, "c": {"type": "string"}}, ["a"])) == []
    assert any("새 필수" in p for p in ts.compat_problems(base, doc({"a": {"type": "string"}, "b": {"type": "integer"}}, ["a", "b"])))
    assert any("제거" in p for p in ts.compat_problems(base, doc({"a": {"type": "string"}}, ["a"])))
    assert any("타입" in p for p in ts.compat_problems(base, doc({"a": {"type": "string"}, "b": {"type": "string"}}, ["a"])))
    assert any("삭제" in p for p in ts.compat_problems(base, {"tools": []}))
    renamed = {"tools": [doc({"a": {"type": "string"}}, ["a"], deprecated=True)["tools"][0],
                         doc({"a": {"type": "string"}, "b": {"type": "string"}}, ["a", "b"], name="t_v2")["tools"][0]]}
    dep = doc({"a": {"type": "string"}, "b": {"type": "integer"}}, ["a"], deprecated=True)
    assert ts.compat_problems(dep, {"tools": []}) == []  # deprecated 도구는 다음 릴리스에 삭제 가능
    assert ts.compat_problems(base, {"tools": [base["tools"][0], renamed["tools"][1]]}) == []  # 새 이름은 통과
    ok = {"kinds": {"k": {"params_schema": {"properties": {"x": {"type": "integer"}}, "required": []}}}}
    bad = {"kinds": {"k": {"params_schema": {"properties": {"x": {"type": "integer"}}, "required": ["x"]}}}}
    assert ts.compat_problems({"tools": []}, {"tools": []}, ok, bad) and not ts.compat_problems({"tools": []}, {"tools": []}, ok, ok)


def test_v_mcp_9_input_schema_conflict_fails():
    from physicsai_api.mcp import toolspec as ts

    spec = {"paths": {}, "components": {"schemas": {"B": {"properties": {"job_id": {"type": "string"}}}}}}
    op = {"x-mcp": {"tool": "x"}, "parameters": [{"in": "path", "name": "job_id", "required": True, "schema": {"type": "string"}}],
          "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/B"}}}}}
    with pytest.raises(ts.SpecError):
        ts.input_schema(spec, op, "x")


# ---- V-MCP-10 ----------------------------------------------------------------------------------------


def test_v_mcp_10_glossary(spec):
    from physicsai_api.mcp import glossary as g
    from physicsai_core.job_types import JOB_TYPES

    gen = g.extract(spec)
    expect: set[str] = set()
    for rel in g.PAICAD_ABBR_FILES:  # 독립 확인: 정규식으로 TYPE_ABBR 값
        src = (REPO / rel).read_text(encoding="utf-8")
        block = re.search(r"^TYPE_ABBR\s*=\s*\{(.*?)\}", src, re.S | re.M).group(1)
        expect |= set(re.findall(r'"[A-Z_]+"\s*:\s*"([A-Z_]+)"', block))
    assert set(gen["feature_abbr"]) == expect and {"THK", "RIB_T", "BEAD_D"} <= expect
    assert set(gen["job_types"]) == set(JOB_TYPES)
    assert gen["error_codes"]["CONFIRM_REQUIRED"]["status"] == 428 and "STUDY_JOB_BUSY" in gen["error_codes"]
    assert gen["error_codes"]["API_TOKEN_STALE"]["sources"] == ["backend/physicsai_api/auth_tokens.py"]
    assert gen["error_codes"]["RATE_LIMITED"]["status"] == 429
    so = next(s for s in gen["stages"] if s["job_type"] == "SURROGATE_OPT")
    assert so == {"job_type": "SURROGATE_OPT", "internal": "⑤", "screen": "⑥"}
    assert g.check_terms(gen, g.terms()) == []
    bad = {"terms": [{"key": "feature:NOPE", "ko": "x"}], "error_hints": {"NOPE_CODE": "x"}}
    probs = g.check_terms(gen, bad)
    assert any("NOPE" in p for p in probs) and any("feature:THK의 ko" in p for p in probs)
    # 플랫폼은 paicad를 import하지 않는다
    for f in API_MCP.rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in n.names] + [getattr(n, "module", None) or ""]
                assert not any(x.split(".")[0] == "paicad" for x in names), f


# ---- V-MCP-5(정적) ------------------------------------------------------------------------------------


def test_v_mcp_5_audit_insert_columns_fixed():
    from physicsai_core.db.repositories.api_audit import AUDIT_COLUMNS

    assert AUDIT_COLUMNS == ("user_id", "username", "api_token_id", "token_prefix", "operation_id", "tool", "method", "route",
                             "target_type", "target_id", "study_id", "kind", "job_id", "plan_id", "status_code", "result_code",
                             "duration_ms", "request_id", "client_ip", "params_sha256")
    tree = ast.parse((API_MCP / "audit_mw.py").read_text(encoding="utf-8"))
    keys = [tuple(k.value for k in n.value.keys) for n in ast.walk(tree)
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "values" for t in n.targets)
            and isinstance(n.value, ast.Dict)]
    assert keys == [AUDIT_COLUMNS]
    from physicsai_core.db.tables import api_audit

    assert {c.name for c in api_audit.columns} == {"id", "occurred_at", *AUDIT_COLUMNS}
