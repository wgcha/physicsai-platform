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
        "/version", "/releases",  # 버전 표시·버전 게시판(읽기 전용)
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
        # 3차(phase3 §18.6 S13 내장 최적화, D3-60)
        "/studies/{study_id}/surrogate-opts/preview", "/studies/{study_id}/surrogate-opts", "/surrogate-opts/{opt_id}",
        "/surrogate-opts/{opt_id}/runs.csv", "/surrogate-opts/{opt_id}/cancel", "/surrogate-opts/{opt_id}/resume",
        # 3차(phase3 §19.5 S14 결과분석 입력, D3-62)
        "/train-does/{doe_id}/result-table",
        # 3차(phase3 §21.2 S16 V1 단일 예측 실행 목록, D3-64)
        "/studies/{study_id}/predict-runs", "/predict-runs/{job_id}",
        # 3차(phase3 §21.3.8 S16 V2 조립 FEM 검증, D3-64)
        "/studies/{study_id}/fem-verifications/preview", "/studies/{study_id}/fem-verifications", "/fem-verifications/{fid}",
        "/fem-verifications/{fid}/media", "/fem-verifications/{fid}/curves", "/fem-verifications/{fid}/table.csv",
        "/fem-verifications/{fid}/cancel", "/fem-verifications/{fid}/rerun",
        # 3차(phase3 §22.10 S17 성능 다시 추출·추가 검증, D3-65)
        "/predict-batches/{batch_id}/extract-responses", "/surrogate-opts/{opt_id}/verify",
        # geometry-engine.md §7.6 native 형상 엔진
        "/param-sets/{ps_id}/native-prepare", "/param-sets/{ps_id}/features",
        # geometry-engine.md §11.1 단계 3S 쉘 두께 · §7.3.8 단계 4B 다중 baseline · ① native 피처 조회
        "/param-sets/{ps_id}/props/scan", "/param-sets/{ps_id}/props", "/param-sets/{ps_id}/baselines",
        "/param-sets/{ps_id}/baselines/disable", "/param-sets/{ps_id}/baselines/{baseline_id}", "/param-sets/{ps_id}/remap",
        "/param-sets/{ps_id}/param-map", "/param-sets/{ps_id}/param-map/confirm", "/studies/{study_id}/train/features",
        # geometry-view.md §6.5·§6.9·§13.5: 형상 3D 보기·미리보기·결과 3D 컨투어
        "/param-sets/{ps_id}/view", "/param-sets/{ps_id}/previews", "/previews/{preview_id}", "/studies/{study_id}/train/view",
        "/contour3d", "/contour3d/{contour_id}", "/contour3d/{contour_id}/cancel",
        # equiv-check.md §6: ⑤ 등가성 판정 레시피·판정 이력
        "/equiv/recipes", "/equiv/recipes/{key}", "/equiv/recipes/{key}/versions", "/equiv/recipes/{key}/restore",
        "/studies/{study_id}/equiv-checks/preview", "/studies/{study_id}/equiv-checks", "/equiv-checks/{eq_id}",
        "/equiv-checks/{eq_id}/curves", "/equiv-checks/{eq_id}/table.csv",
        # mcp.md §4.4·§5.2·§6.2·§7·§9·§10: API 토큰 관리(세션 전용)·공통 작업 계약·요약·감사·용어집·도구 스펙·ping
        "/me/api-tokens", "/me/api-tokens/{token_id}", "/admin/api-tokens", "/admin/api-tokens/{token_id}/revoke",
        "/mcp/ping", "/mcp/job-kinds", "/mcp/job-kinds/{kind}", "/mcp/jobs/plan", "/mcp/jobs", "/mcp/jobs/{job_id}",
        "/mcp/jobs/{job_id}/summary", "/mcp/jobs/{job_id}/cancel", "/mcp/summary/{entity}/{id}", "/mcp/system", "/mcp/audit",
        "/mcp/glossary", "/mcp/tools", "/mcp/connection",
        # native-vars.md §6.1: Native 템플릿 변수 정의(선택·범위)
        "/param-sets/{ps_id}/variables",
        # upload-report.md §4: 브라우저 분할 업로드(청크 PUT octet-stream, x-mcp exclude)
        "/uploads/config", "/studies/{study_id}/uploads", "/uploads/{upload_id}", "/uploads/{upload_id}/files",
        "/uploads/{upload_id}/files/{index}", "/uploads/{upload_id}/complete", "/admin/uploads/cleanup-stale",
        # upload-report.md §9.4: HTML 결과 요약 보고서(서버가 요청 시 생성, 저장 없음)
        "/reports/analysis", "/reports/{target}/{target_id}",
        # asm-match.md §6.3(AM-C2): 조립 매칭(생성·목록·조회·행 저장·검사·확정)
        "/studies/{study_id}/asm-matches", "/asm-matches/{match_id}", "/asm-matches/{match_id}/rows", "/asm-matches/{match_id}/check",
        "/asm-matches/{match_id}/confirm",
    }
    assert {p.removeprefix("/physicsai/api") for p in paths} == expected
