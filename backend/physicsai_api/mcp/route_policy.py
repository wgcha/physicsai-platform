"""operation 정책(mcp.md §8): 동결 목록 `LEGACY_UNMARKED`와 라우트의 `x-mcp` 판독.

- `LEGACY_UNMARKED` = 구현 기준(v0.2.3, migration 0019) 기존 operationId 중 `x-mcp`를 붙이지 않은 것(웹 전용, 토큰 요청 불가 — 허용 목록 밖).
  **줄기만 한다**: 새 operation은 반드시 `x-mcp`(도구 또는 제외 사유)를 단다. 없는 id가 남아 있으면 정적 시험(V-MCP-6) 실패.
  native-vars·upload-report가 추가하는 operation은 이 목록에 넣지 않고 각 계약의 x-mcp 표기를 따른다(mcp.md §8).
- `x-mcp` 모양: 도구 `{tool, risk, confirm, version, summary_en, summary_ko, deprecated}` 또는 제외 `{exclude: 사유, session_only?, token_risk?}`.
"""

from __future__ import annotations

from typing import Any

RISKS = ("read", "run", "admin")
RISK_RANK = {"read": 0, "run": 1, "admin": 2}

LEGACY_UNMARKED: frozenset[str] = frozenset({
    "admin_config_physicsai_api_admin_config_get",
    "archive_study_physicsai_api_studies__study_id__archive_post",
    "baseline_add_physicsai_api_param_sets__ps_id__baselines_post",
    "baseline_delete_physicsai_api_param_sets__ps_id__baselines__baseline_id__delete",
    "baseline_disable_physicsai_api_param_sets__ps_id__baselines_disable_post",
    "batch_curves_physicsai_api_predict_batches__batch_id__curves_get",
    "batch_design_map_physicsai_api_predict_batches__batch_id__design_map_get",
    "batch_table_csv_physicsai_api_predict_batches__batch_id__table_csv_get",
    "cancel_batch_physicsai_api_predict_batches__batch_id__cancel_post",
    "cancel_contour3d_physicsai_api_contour3d__contour_id__cancel_post",
    "cancel_fem_verification_physicsai_api_fem_verifications__fid__cancel_post",
    "cancel_physicsai_api_jobs__job_id__cancel_post",
    "cancel_surrogate_opt_physicsai_api_surrogate_opts__opt_id__cancel_post",
    "candidates_physicsai_api_studies__study_id__optimize_response_candidates_get",
    "content_physicsai_api_artifacts__artifact_id__content_get",
    "create_contour3d_physicsai_api_contour3d_post",
    "create_equiv_check_physicsai_api_studies__study_id__equiv_checks_post",
    "create_equiv_recipe_physicsai_api_equiv_recipes_post",
    "create_fem_verification_physicsai_api_studies__study_id__fem_verifications_post",
    "create_job_physicsai_api_studies__study_id__jobs_post",
    "create_physicsai_api_admin_env_checks_post",
    "create_preview_physicsai_api_param_sets__ps_id__previews_post",
    "create_study_physicsai_api_studies_post",
    "create_surrogate_opt_physicsai_api_studies__study_id__surrogate_opts_post",
    "delete_equiv_recipe_physicsai_api_equiv_recipes__key__delete",
    "discover_physicsai_api_studies__study_id__param_sets_discover_post",
    "doe_result_table_physicsai_api_train_does__doe_id__result_table_get",
    "doe_types_physicsai_api_train_doe_types_get",
    "equiv_check_curves_physicsai_api_equiv_checks__eq_id__curves_get",
    "equiv_check_table_csv_physicsai_api_equiv_checks__eq_id__table_csv_get",
    "equiv_recipe_versions_physicsai_api_equiv_recipes__key__versions_get",
    "error_bundle_physicsai_api_jobs__job_id__error_bundle_zip_get",
    "extract_batch_responses_physicsai_api_predict_batches__batch_id__extract_responses_post",
    "fem_verification_curves_physicsai_api_fem_verifications__fid__curves_get",
    "fem_verification_media_physicsai_api_fem_verifications__fid__media_get",
    "fem_verification_table_csv_physicsai_api_fem_verifications__fid__table_csv_get",
    "files_physicsai_api_curations__curation_id__files_get",
    "from_train_physicsai_api_studies__study_id__param_sets_from_train_post",
    "fs_list_physicsai_api_fs_list_get",
    "fs_roots_physicsai_api_fs_roots_get",
    "generate_tpl_physicsai_api_studies__study_id__train_tpl_post",
    "get_batch_physicsai_api_predict_batches__batch_id__get",
    "get_check_physicsai_api_admin_env_checks__check_id__get",
    "get_contour3d_physicsai_api_contour3d__contour_id__get",
    "get_curation_physicsai_api_curations__curation_id__get",
    "get_dataset_physicsai_api_datasets__dataset_id__get",
    "get_doe_physicsai_api_train_does__doe_id__get",
    "get_equiv_check_physicsai_api_equiv_checks__eq_id__get",
    "get_equiv_recipe_physicsai_api_equiv_recipes__key__get",
    "get_fem_verification_physicsai_api_fem_verifications__fid__get",
    "get_job_physicsai_api_jobs__job_id__get",
    "get_model_physicsai_api_models__model_id__get",
    "get_opt_physicsai_api_optimizations__optimization_id__get",
    "get_predict_run_physicsai_api_predict_runs__job_id__get",
    "get_preview_physicsai_api_previews__preview_id__get",
    "get_set_physicsai_api_param_sets__ps_id__get",
    "get_setup_physicsai_api_studies__study_id__train_get",
    "get_study_physicsai_api_studies__study_id__get",
    "get_study_storage_physicsai_api_studies__study_id__storage_get",
    "get_surrogate_opt_physicsai_api_surrogate_opts__opt_id__get",
    "health_physicsai_api_health_get",
    "hpc_jobs_physicsai_api_jobs__job_id__hpc_jobs_get",
    "input_zip_physicsai_api_jobs__job_id__artifacts_input_zip_get",
    "inspect_physicsai_api_studies__study_id__paths_inspect_post",
    "job_log_physicsai_api_jobs__job_id__log_get",
    "job_media_physicsai_api_jobs__job_id__media_get",
    "latest_physicsai_api_admin_env_checks_latest_get",
    "list_artifacts_physicsai_api_jobs__job_id__artifacts_get",
    "list_batches_physicsai_api_studies__study_id__predict_batches_get",
    "list_checks_physicsai_api_admin_env_checks_get",
    "list_curations_physicsai_api_studies__study_id__curations_get",
    "list_datasets_physicsai_api_studies__study_id__datasets_get",
    "list_does_physicsai_api_studies__study_id__train_does_get",
    "list_equiv_checks_physicsai_api_studies__study_id__equiv_checks_get",
    "list_equiv_recipes_physicsai_api_equiv_recipes_get",
    "list_fem_verifications_physicsai_api_studies__study_id__fem_verifications_get",
    "list_imports_physicsai_api_studies__study_id__spdm_imports_get",
    "list_jobs_physicsai_api_jobs_get",
    "list_models_physicsai_api_studies__study_id__models_get",
    "list_notifications_physicsai_api_notifications_get",
    "list_opts_physicsai_api_studies__study_id__optimizations_get",
    "list_predict_runs_physicsai_api_studies__study_id__predict_runs_get",
    "list_runs_physicsai_api_train_does__doe_id__runs_get",
    "list_sets_physicsai_api_studies__study_id__param_sets_get",
    "list_surrogate_opts_physicsai_api_studies__study_id__surrogate_opts_get",
    "media_content_physicsai_api_artifacts__artifact_id__media_get",
    "move_physicsai_api_queue__job_id__move_post",
    "native_features_physicsai_api_param_sets__ps_id__features_get",
    "native_prepare_physicsai_api_param_sets__ps_id__native_prepare_post",
    "param_map_confirm_physicsai_api_param_sets__ps_id__param_map_confirm_post",
    "param_map_get_physicsai_api_param_sets__ps_id__param_map_get",
    "param_map_put_physicsai_api_param_sets__ps_id__param_map_put",
    "param_map_remap_physicsai_api_param_sets__ps_id__remap_post",
    "param_set_view_physicsai_api_param_sets__ps_id__view_get",
    "patch_equiv_check_physicsai_api_equiv_checks__eq_id__patch",
    "patch_model_physicsai_api_models__model_id__patch",
    "patch_set_physicsai_api_param_sets__ps_id__patch",
    "patch_study_physicsai_api_studies__study_id__patch",
    "preview_batch_physicsai_api_studies__study_id__predict_batches_preview_post",
    "preview_equiv_check_physicsai_api_studies__study_id__equiv_checks_preview_post",
    "preview_fem_verification_physicsai_api_studies__study_id__fem_verifications_preview_post",
    "preview_surrogate_opt_physicsai_api_studies__study_id__surrogate_opts_preview_post",
    "projects_physicsai_api_projects_get",
    "props_get_physicsai_api_param_sets__ps_id__props_get",
    "props_put_physicsai_api_param_sets__ps_id__props_put",
    "props_scan_physicsai_api_param_sets__ps_id__props_scan_post",
    "put_display_physicsai_api_param_sets__ps_id__display_put",
    "put_final_physicsai_api_studies__study_id__final_model_put",
    "put_params_physicsai_api_studies__study_id__train_params_put",
    "put_responses_physicsai_api_param_sets__ps_id__responses_put",
    "queue_physicsai_api_queue_get",
    "read_physicsai_api_notifications_read_post",
    "recapture_physicsai_api_jobs__job_id__capture_post",
    "register_physicsai_api_studies__study_id__param_sets_post",
    "releases_physicsai_api_releases_get",
    "rerun_fem_verification_physicsai_api_fem_verifications__fid__rerun_post",
    "resolve_hpc_job_physicsai_api_jobs__job_id__hpc_jobs__hpc_job_id__resolve_post",
    "resources_physicsai_api_resources_get",
    "restore_equiv_recipe_physicsai_api_equiv_recipes__key__restore_post",
    "resume_surrogate_opt_physicsai_api_surrogate_opts__opt_id__resume_post",
    "retry_failed_batch_physicsai_api_predict_batches__batch_id__retry_failed_post",
    "retry_physicsai_api_jobs__job_id__retry_post",
    "samples_physicsai_api_param_sets__ps_id__samples_get",
    "samples_physicsai_api_train_does__doe_id__samples_get",
    "sources_physicsai_api_studies__study_id__curation_sources_get",
    "status_physicsai_api_status_get",
    "step_log_physicsai_api_jobs__job_id__steps__step_no__log_get",
    "surrogate_opt_runs_csv_physicsai_api_surrogate_opts__opt_id__runs_csv_get",
    "train_features_physicsai_api_studies__study_id__train_features_get",
    "train_view_physicsai_api_studies__study_id__train_view_get",
    "unarchive_study_physicsai_api_studies__study_id__unarchive_post",
    "unread_physicsai_api_notifications_unread_count_get",
    "update_equiv_recipe_physicsai_api_equiv_recipes__key__put",
    "verify_surrogate_opt_physicsai_api_surrogate_opts__opt_id__verify_post",
    "version_physicsai_api_version_get",
})


def x_mcp_of(route: Any) -> dict[str, Any] | None:
    """FastAPI APIRoute의 openapi_extra["x-mcp"](없으면 None)."""
    extra = getattr(route, "openapi_extra", None) or {}
    x = extra.get("x-mcp")
    return x if isinstance(x, dict) else None


def operation_id_of(route: Any) -> str | None:
    return getattr(route, "operation_id", None) or getattr(route, "unique_id", None)


def token_risk(x: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """토큰 요청 허용 판정 → (필요 범위, 거부 코드). 도구면 risk, 제외 + token_risk면 그 범위, 세션 전용·그 밖은 거부."""
    if x is None:
        return None, "API_TOKEN_OPERATION_NOT_ALLOWED"
    if x.get("tool"):
        return str(x.get("risk") or "read"), None
    if x.get("session_only"):
        return None, "SESSION_REQUIRED"
    if x.get("token_risk") in RISKS:
        return str(x["token_risk"]), None
    return None, "API_TOKEN_OPERATION_NOT_ALLOWED"
