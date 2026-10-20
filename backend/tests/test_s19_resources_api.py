"""S19 설정·/resources(phase3 §24.3·§24.6, V3-S19-1·4): GPU 조회 새 키 3개 기본값·범위 오류,
gpu_backoff_max_s 0 허용·base 미만 거부, 예시 yaml, /resources 새 필드 통과·옛 표본 null(GPU 레인 B-LANE 철회 — 레인 키 없음)."""

from __future__ import annotations

import yaml

from physicsai_test_support import API, REPO, H

P = H("tok-power")

WORKER_DEFAULTS = {"gpu_query_timeout_s": 15, "gpu_backoff_after": 3, "gpu_backoff_max_s": 300}


def _load(d):
    from physicsai_core.config import load_config_dict

    return load_config_dict(d, environ={})


def _with(d, sect, **kw):
    return {**d, sect: {**(d.get(sect) or {}), **kw}}


def _err(lc, key):
    return [i.message for i in lc.issues if i.key == key]


# ---- V3-S19-1 설정 ---------------------------------------------------------------------------------------------


def test_v3_s19_1_defaults(settings_dict):
    lc = _load(settings_dict)
    assert lc.ok, lc.issues
    w = lc.settings.worker.model_dump()
    assert {k: w[k] for k in WORKER_DEFAULTS} == WORKER_DEFAULTS
    assert "predict_parallel_max" not in lc.settings.predict_batch.model_dump()


def test_v3_s19_1_ranges(settings_dict):
    bad = [("worker", "gpu_query_timeout_s", 0, "1~120"), ("worker", "gpu_query_timeout_s", 121, "1~120"),
           ("worker", "gpu_backoff_after", 0, "1~100"), ("worker", "gpu_backoff_after", 101, "1~100")]
    for sect, k, v, msg in bad:
        lc = _load(_with(settings_dict, sect, **{k: v}))
        assert lc.error_keys() == [f"{sect}.{k}"] and _err(lc, f"{sect}.{k}") == [msg], (k, v, lc.issues)


def test_v3_s19_1_backoff_max(settings_dict):
    # 시험 설정 resource_sample_interval_s = 0.5
    assert _load(_with(settings_dict, "worker", gpu_backoff_max_s=0)).ok                              # 0 = 늘리지 않음
    assert _load(_with(settings_dict, "worker", gpu_backoff_max_s=0.5)).ok
    assert _load(_with(settings_dict, "worker", gpu_backoff_max_s=3600)).ok
    lc = _load(_with(settings_dict, "worker", gpu_backoff_max_s=5, resource_sample_interval_s=10))  # base 미만
    assert lc.error_keys() == ["worker.gpu_backoff_max_s"]
    assert _err(lc, "worker.gpu_backoff_max_s") == ["0(늘리지 않음) 또는 resource_sample_interval_s(10)~3600"]
    assert _load(_with(settings_dict, "worker", gpu_backoff_max_s=3601)).error_keys() == ["worker.gpu_backoff_max_s"]


def test_v3_s19_1_example_yaml(tmp_path):
    text = (REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    data["storage"]["ai_root"] = str(tmp_path)
    lc = _load(data)
    assert lc.ok, lc.issues
    assert {k: lc.settings.worker.model_dump()[k] for k in WORKER_DEFAULTS} == WORKER_DEFAULTS
    for k in WORKER_DEFAULTS:                                                       # 키마다 주석 한 줄
        line = next(ln for ln in text.splitlines() if ln.strip().startswith(f"{k}:"))
        assert "#" in line, k


# ---- V3-S19-4 /resources ---------------------------------------------------------------------------------------


def _heartbeat(engine, resources):
    from physicsai_core.db.repositories import workers as workers_repo

    with engine.begin() as conn:
        workers_repo.upsert(conn, worker_id="w-1", host="h", pid=1, app_version="x", limiter="null",
                            effective_limits={"cores": 4}, resources=resources)


def test_v3_s19_4_resources_new_fields(client, engine):
    base = {"sampled_at": "2026-10-19T00:00:00+00:00", "cpu_pct": 1.0, "ram_used_gb": 1.0, "ram_total_gb": 2.0,
            "gpu": [], "job": None}
    _heartbeat(engine, {**base, "gpu_status": "ERROR", "gpu_message": "nvidia-smi 응답 시간 초과(15초): C:/x/nvidia-smi.exe",
                        "gpu_fail_streak": 4, "gpu_sampled_at": "2026-10-19T00:00:10+00:00",
                        "gpu_next_query_at": "2026-10-19T00:00:50+00:00"})
    r = client.get(f"{API}/resources", headers=P).json()
    assert r["gpu_status"] == "ERROR" and r["gpu_fail_streak"] == 4 and r["gpu_message"].startswith("nvidia-smi 응답 시간 초과")
    assert r["gpu_sampled_at"].startswith("2026-10-19T00:00:10") and r["gpu_next_query_at"].startswith("2026-10-19T00:00:50")
    _heartbeat(engine, {**base, "gpu_status": "OK", "gpu_message": "/usr/bin/nvidia-smi"})        # 옛 워커 표본(키 없음)
    r = client.get(f"{API}/resources", headers=P).json()
    assert r["gpu_message"] == "/usr/bin/nvidia-smi"
    assert r["gpu_fail_streak"] is None and r["gpu_sampled_at"] is None and r["gpu_next_query_at"] is None


def test_v3_s19_4_heartbeat_ok_message_is_exe(client, worker_factory, loaded_config):
    w = worker_factory()
    w.heartbeat_once()                                                                                # 스레드 없음 → 직접 조회
    r = client.get(f"{API}/resources", headers=P).json()
    assert r["gpu_status"] == "OK" and r["gpu_message"] == loaded_config.settings.worker.gpu_query[0]
    assert r["gpu_fail_streak"] == 0 and r["gpu_sampled_at"] and r["gpu_next_query_at"] is None


def test_v3_s19_4_openapi_fields():
    from physicsai_api.export_openapi import build_openapi

    props = build_openapi()["components"]["schemas"]["ResourcesResponse"]["properties"]
    assert {"gpu_fail_streak", "gpu_sampled_at", "gpu_next_query_at"} <= set(props)


def test_v3_s19_4_no_lane_fields(client, engine):
    """B-LANE 철회: /queue·/status·/resources에 레인 필드가 없다(S18과 같은 모양)."""
    _heartbeat(engine, {"gpu": [], "gpu_status": "OK", "gpu_message": "x"})
    assert "gpu_lane" not in client.get(f"{API}/resources", headers=P).json()
    assert "predict_parallel_max" not in client.get(f"{API}/status", headers=P).json()["limits"]["configured"]
    assert "running_parallel" not in client.get(f"{API}/queue", headers=P).json()
