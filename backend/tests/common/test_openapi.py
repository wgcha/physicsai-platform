"""V-API-3: backend/openapi.json이 생성 결과와 같다."""

from physicsai_test_support import REPO


def test_openapi_up_to_date():
    from physicsai_api.export_openapi import render

    committed = (REPO / "backend" / "openapi.json").read_text(encoding="utf-8")
    assert committed == render(), "python -m physicsai_api.export_openapi 로 다시 생성하세요"


def test_all_routes_prefixed():
    from physicsai_api.export_openapi import build_openapi

    paths = build_openapi()["paths"]
    assert paths and all(p.startswith("/physicsai/api/") for p in paths)
    expected = {
        "/health", "/me", "/projects", "/status", "/queue", "/queue/{job_id}/move", "/resources", "/studies",
        "/studies/{study_id}", "/studies/{study_id}/archive", "/studies/{study_id}/paths/inspect",
        "/studies/{study_id}/datasets", "/datasets/{dataset_id}", "/studies/{study_id}/models", "/models/{model_id}",
        "/studies/{study_id}/final-model", "/studies/{study_id}/param-sets", "/param-sets/{ps_id}",
        "/param-sets/{ps_id}/samples", "/studies/{study_id}/predict/check", "/studies/{study_id}/jobs", "/jobs",
        "/jobs/{job_id}", "/jobs/{job_id}/log", "/jobs/{job_id}/steps/{step_no}/log", "/jobs/{job_id}/cancel",
        "/jobs/{job_id}/retry", "/jobs/{job_id}/artifacts", "/jobs/{job_id}/artifacts/input.zip", "/artifacts/{artifact_id}/content", "/jobs/{job_id}/hpc-jobs",
        "/notifications", "/notifications/unread-count", "/notifications/read", "/admin/config",
        # 2차(phase2 §12)
        "/admin/env-checks", "/admin/env-checks/latest", "/admin/env-checks/{check_id}", "/jobs/{job_id}/error-bundle.zip",
        "/studies/{study_id}/train", "/studies/{study_id}/train/params", "/studies/{study_id}/train/tpl", "/train/doe-types",
        "/studies/{study_id}/train/does", "/train-does/{doe_id}", "/train-does/{doe_id}/runs", "/train-does/{doe_id}/samples",
        "/studies/{study_id}/curation-sources", "/studies/{study_id}/curations", "/curations/{curation_id}",
        "/curations/{curation_id}/files", "/studies/{study_id}/spdm-imports", "/studies/{study_id}/optimizations",
        "/optimizations/{optimization_id}", "/studies/{study_id}/optimize/response-candidates",
        "/studies/{study_id}/param-sets/from-train",
        # 3차(phase3 §3.2)
        "/studies/{study_id}/unarchive",
        # 3차(phase3 §5.6)
        "/studies/{study_id}/storage",
        # 3차(phase3 §12 S7, D3-46)
        "/fs/roots", "/fs/list",
        # 3차(phase3 §13 S8, D3-47)
        "/studies/{study_id}/param-sets/discover",
        # 3차(phase3 §14.7 S9, D3-49)
        "/studies/{study_id}/predict-batches/preview", "/studies/{study_id}/predict-batches", "/predict-batches/{batch_id}",
        "/predict-batches/{batch_id}/table.csv", "/predict-batches/{batch_id}/curves", "/predict-batches/{batch_id}/cancel",
        "/predict-batches/{batch_id}/retry-failed", "/param-sets/{ps_id}/responses",
        # 3차(phase3 §15 S10)
        "/jobs/{job_id}/media", "/artifacts/{artifact_id}/media", "/jobs/{job_id}/capture", "/param-sets/{ps_id}/display",
        # 3차(phase3 §16.5 S11 SCX 결과 모름 조치, D3-57)
        "/jobs/{job_id}/hpc-jobs/{hpc_job_id}/resolve",
        # 3차(phase3 §17.4 S12 설계공간 지도, D3-59)
        "/predict-batches/{batch_id}/design-map",
    }
    assert {p.removeprefix("/physicsai/api") for p in paths} == expected
