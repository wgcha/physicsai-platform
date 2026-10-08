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
    }
    assert {p.removeprefix("/physicsai/api") for p in paths} == expected
