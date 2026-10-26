// 계약 §10 엔드포인트 함수. 화면 코드는 fetch를 직접 쓰지 않고 이 객체만 쓴다.
import { API_PREFIX, fetchBlob, fetchBuffer, request, requestPage } from "./client";
import type {
  Artifact,
  BatchCurves,
  BatchPreview,
  BatchPreviewRequest,
  BatchRetryFailed,
  CaptureRequest,
  ContourDisplay,
  JobMedia,
  ParamSetResponsesPut,
  PredictBatch,
  PredictBatchSummary,
  Curation,
  CurationFile,
  CurationSource,
  DoeType,
  EnvCheck,
  EnvCheckSummary,
  FsList,
  FsRoots,
  Optimization,
  ResponseCandidates,
  SpdmImport,
  TrainDoe,
  TrainRun,
  TrainSetup,
  Dataset,
  HpcJob,
  HpcResolveAction,
  Job,
  JobSummary,
  JobType,
  LogChunk,
  Me,
  Model,
  NotificationList,
  ParamSet,
  ParamSetCreate,
  ParamSetDiscover,
  Engine,
  GeomOptions,
  DoePreview,
  DoePreviewReq,
  NativeFeatures,
  NativeVars,
  ApiToken,
  ApiTokenAdmin,
  ApiTokenCreate,
  ApiTokenCreated,
  McpConnection,
  McpPing,
  McpTools,
  NativeVarsUpdate,
  ShellProps,
  ShellPropsUpdate,
  BaselineAddRequest,
  ParamMapRemapRequest,
  ParamMap,
  MapRowDecision,
  PathInspectResult,
  PathPurpose,
  PredictCheck,
  Project,
  QueueInfo,
  Resources,
  SamplePage,
  StatusInfo,
  StorageReport,
  Study,
  StudyDetail,
  GeomView,
  AsmMatch,
  AsmMatchCreate,
  AsmRowsPut,
  GeomPreview,
  GeomPreviewCreate,
  Contour3d,
  Contour3dCreate,
  VersionInfo,
  ReleasesResponse,
} from "./types";

export const api = {
  // §10.2 셸·상태
  me: () => request<Me>("GET", "/me"),
  /** mcp.md §4.4 API 토큰(세션 전용). 평문 token은 발급 응답에서 한 번만 온다 */
  myApiTokens: () => request<ApiToken[]>("GET", "/me/api-tokens"),
  createApiToken: (body: ApiTokenCreate) => request<ApiTokenCreated>("POST", "/me/api-tokens", { body }),
  revokeMyApiToken: (id: string) => request<void>("DELETE", `/me/api-tokens/${encodeURIComponent(id)}`),
  adminApiTokens: (q: { user_id?: string | null; active?: boolean | null } = {}) => request<ApiTokenAdmin[]>("GET", "/admin/api-tokens", { query: q }),
  adminRevokeApiToken: (id: string) => request<ApiTokenAdmin>("POST", `/admin/api-tokens/${encodeURIComponent(id)}/revoke`),
  /** mcp.md §23: "AI 연결(MCP)" 페이지 — 연결 안내(세션 전용)·연결 점검·도구 목록(visible) */
  mcpConnection: () => request<McpConnection>("GET", "/mcp/connection"),
  mcpPing: () => request<McpPing>("GET", "/mcp/ping"),
  mcpTools: () => request<McpTools>("GET", "/mcp/tools", { query: { format: "mcp", visible: true } }),
  projects: () => request<Project[]>("GET", "/projects"),
  status: () => request<StatusInfo>("GET", "/status"),
  queue: () => request<QueueInfo>("GET", "/queue"),
  moveQueue: (jobId: string, position: number) =>
    request<QueueInfo>("POST", `/queue/${jobId}/move`, { body: { position } }),
  resources: () => request<Resources>("GET", "/resources"),
  // 버전 표시·버전 게시판: 조회만(작성·수정·삭제 없음 — 배포로만 기록)
  version: () => request<VersionInfo>("GET", "/version"),
  releases: () => request<ReleasesResponse>("GET", "/releases"),

  // §10.3 Study·경로
  studies: (projectId: string, status?: string) =>
    request<Study[]>("GET", "/studies", { query: { project_id: projectId, status } }),
  createStudy: (body: { project_id: string; folder_name: string; title: string }) =>
    request<Study>("POST", "/studies", { body }),
  study: (id: string) => request<StudyDetail>("GET", `/studies/${id}`),
  /** phase3.md §3.2: 표시 이름 변경(CAS), 보관·보관 해제(멱등) */
  patchStudy: (id: string, body: { version: number; title: string }) => request<Study>("PATCH", `/studies/${id}`, { body }),
  archiveStudy: (id: string) => request<Study>("POST", `/studies/${id}/archive`),
  unarchiveStudy: (id: string) => request<Study>("POST", `/studies/${id}/unarchive`),
  /** phase3.md §5.6: 용량·정리 보고서(계산·정리 실행은 createJob STUDY_STORAGE_SCAN·STUDY_CLEANUP) */
  studyStorage: (id: string) => request<StorageReport>("GET", `/studies/${id}/storage`),
  /** phase2.md §12.4: RESULT_FOLDER는 doe_id 선택 키 */
  inspectPath: (studyId: string, purpose: PathPurpose, path: string, extra?: { doe_id?: string; engine?: Engine }) =>
    request<PathInspectResult>("POST", `/studies/${studyId}/paths/inspect`, { body: { purpose, path, ...(extra ?? {}) } }),

  /** phase3.md §12 S7: 서버 경로 탐색(이름·크기·mtime만, 실행 권한) */
  fsRoots: () => request<FsRoots>("GET", "/fs/roots"),
  fsList: (path: string, exts?: string[]) =>
    request<FsList>("GET", "/fs/list", { query: { path, exts: exts && exts.length ? exts.join(",") : undefined } }),

  // §10.4 데이터셋·모델·파라미터 세트
  datasets: (studyId: string) => request<Dataset[]>("GET", `/studies/${studyId}/datasets`),
  /** phase3.md §4.1: 모델 비교 메타(데이터셋별 1회) */
  dataset: (id: string) => request<Dataset>("GET", `/datasets/${id}`),
  models: (studyId: string, status?: string) =>
    request<Model[]>("GET", `/studies/${studyId}/models`, { query: { status } }),
  model: (id: string) => request<Model>("GET", `/models/${id}`),
  setFinalModel: (studyId: string, modelId: string | null) =>
    request<Study>("PUT", `/studies/${studyId}/final-model`, { body: { model_id: modelId } }),
  /** §15.4 폴더 등록. mode="discover" = 프로젝트 폴더에서 자동 구성(phase3 §13 S8) */
  /** engine:"native" → 202 {job_id}(PARAM_SET_NATIVE, geometry-engine.md §7.3.4), altair → 201 ParamSet */
  registerParamSet: (studyId: string, path: string, opts: Omit<ParamSetCreate, "path"> = {}) =>
    request<ParamSet | { job_id: string }>("POST", `/studies/${studyId}/param-sets`, { body: { path, ...opts } }),
  /** asmMatch = 조립 매칭을 쓸 것(asm-match.md AM-C2 12): 서버가 BASELINE_INC_MISSING·RENUM_CSV_MISSING을 제외한다 */
  discoverParamSet: (studyId: string, path: string, tpl?: string | null, engine?: Engine, asmMatch?: boolean) =>
    request<ParamSetDiscover>("POST", `/studies/${studyId}/param-sets/discover`, { body: { path, ...(tpl ? { tpl } : {}), ...(engine ? { engine } : {}), ...(asmMatch ? { asm_match: true } : {}) } }),
  /** label·geom_options(§7.4 부분 객체, 422 GEOM_OPTIONS_INVALID problems) */
  patchParamSet: (id: string, body: { label?: string | null; geom_options?: GeomOptions | null }) => request<ParamSet>("PATCH", `/param-sets/${id}`, { body }),
  /** §7.6 native: 형상 준비 다시(202 job), 피처 요약 */
  nativePrepare: (id: string) => request<{ job_id: string }>("POST", `/param-sets/${id}/native-prepare`),
  paramSetFeatures: (id: string) => request<NativeFeatures>("GET", `/param-sets/${id}/features`),
  /** native-vars.md §6.1: 세트 변수 정의(풀·범위·리비전). model_id = 학습 범위, revision = 특정 리비전(읽기) */
  nativeVars: (id: string, q: { model_id?: string | null; revision?: number | null } = {}) => request<NativeVars>("GET", `/param-sets/${id}/variables`, { query: q }),
  putNativeVars: (id: string, body: NativeVarsUpdate) => request<NativeVars>("PUT", `/param-sets/${id}/variables`, { body }),
  /** 3S 쉘 두께(§11.1): 스캔(202 job PARAM_SET_NATIVE props_scan) → GET 목록·선택 → PUT 선택 전체 교체(응답 = 갱신된 ParamSet) */
  scanShellProps: (id: string) => request<{ job_id: string }>("POST", `/param-sets/${id}/props/scan`),
  shellProps: (id: string) => request<ShellProps>("GET", `/param-sets/${id}/props`),
  putShellProps: (id: string, body: ShellPropsUpdate) => request<ParamSet>("PUT", `/param-sets/${id}/props`, { body }),
  /** 4B 다중 baseline(§7.3.8): 추가·다시 매칭 = 202 job(PARAM_SET_NATIVE add_baseline·remap), 삭제·끄기 = 갱신된 ParamSet */
  addBaseline: (id: string, body: BaselineAddRequest) => request<{ job_id: string }>("POST", `/param-sets/${id}/baselines`, { body }),
  deleteBaseline: (id: string, bid: string) => request<ParamSet>("DELETE", `/param-sets/${id}/baselines/${encodeURIComponent(bid)}`),
  disableBaselines: (id: string) => request<ParamSet>("POST", `/param-sets/${id}/baselines/disable`),
  remapParamSet: (id: string, body: ParamMapRemapRequest = {}) => request<{ job_id: string }>("POST", `/param-sets/${id}/remap`, { body }),
  paramMap: (id: string) => request<ParamMap>("GET", `/param-sets/${id}/param-map`),
  putParamMap: (id: string, decisions: MapRowDecision[]) => request<ParamMap>("PUT", `/param-sets/${id}/param-map`, { body: { decisions } }),
  confirmParamMap: (id: string) => request<ParamMap>("POST", `/param-sets/${id}/param-map/confirm`),
  /** geometry-view.md §6.5: 공칭 3D 뷰(GLB·manifest artifact id) · 미리보기(200 캐시 적중 | 202) · 미리보기 상태 */
  paramSetView: (id: string) => request<GeomView>("GET", `/param-sets/${id}/view`),
  createPreview: (id: string, body: GeomPreviewCreate) => request<GeomPreview>("POST", `/param-sets/${id}/previews`, { body }),
  preview: (id: string) => request<GeomPreview>("GET", `/previews/${id}`),
  /** doe-preview.md §6.6 DOE 표본 형상 그리드: 200 전부 캐시 | 202(job) · 상태(1초 폴링) · 취소 */
  createDoePreview: (studyId: string, body: DoePreviewReq) => request<DoePreview>("POST", `/studies/${studyId}/doe-previews`, { body }),
  doePreview: (id: string) => request<DoePreview>("GET", `/doe-previews/${id}`),
  cancelDoePreview: (id: string) => request<DoePreview>("POST", `/doe-previews/${id}/cancel`),
  /** asm-match.md §6.3 조립 매칭: 목록 읽기 202 · 조회 · 행 저장(초안) · 검사 202 · 확정 */
  asmMatchCreate: (studyId: string, body: AsmMatchCreate) => request<{ match_id: string; job_id: string }>("POST", `/studies/${studyId}/asm-matches`, { body }),
  asmMatch: (id: string) => request<AsmMatch>("GET", `/asm-matches/${id}`),
  /** Study의 매칭 목록(최신순, 항목 = AsmMatch) — 화면이 마지막 매칭을 다시 찾는다 */
  asmMatches: (studyId: string, q: { source?: "train" | "path"; latest?: boolean; limit?: number } = {}) =>
    request<{ items: AsmMatch[] }>("GET", `/studies/${studyId}/asm-matches`, { query: q }),
  putAsmRows: (id: string, body: AsmRowsPut) => request<AsmMatch>("PUT", `/asm-matches/${id}/rows`, { body }),
  checkAsmMatch: (id: string) => request<{ job_id: string }>("POST", `/asm-matches/${id}/check`),
  confirmAsmMatch: (id: string) => request<AsmMatch>("POST", `/asm-matches/${id}/confirm`),
  /** 진행 중인 목록 읽기·검사 작업 취소(power) — 검사는 시간 제한이 없어 사용자가 직접 멈춘다(AM-C3) */
  cancelAsmMatch: (id: string) => request<AsmMatch>("POST", `/asm-matches/${id}/cancel`),
  /** §13.5 결과 3D 컨투어(열 때 생성): 200 적중 | 202 생성 중(progress) · 상태 · 취소 */
  createContour3d: (body: Contour3dCreate) => request<Contour3d>("POST", "/contour3d", { body }),
  contour3d: (id: string) => request<Contour3d>("GET", `/contour3d/${id}`),
  cancelContour3d: (id: string) => request<Contour3d>("POST", `/contour3d/${id}/cancel`),
  /** GLB·프레임 바이너리(`/artifacts/{id}/media`, Range 지원 — 410 = 캐시 정리됨) · manifest JSON(`/content`) */
  artifactBuffer: (id: string, range?: [number, number], onProgress?: (loaded: number) => void) => fetchBuffer(`/artifacts/${id}/media`, range, onProgress),
  artifactJson: <T,>(id: string) => request<T>("GET", `/artifacts/${id}/content`),
  paramSets: (studyId: string) => request<ParamSet[]>("GET", `/studies/${studyId}/param-sets`),
  paramSet: (id: string) => request<ParamSet>("GET", `/param-sets/${id}`),
  samples: (id: string, limit = 200, cursor?: string | null) =>
    request<SamplePage>("GET", `/param-sets/${id}/samples`, { query: { limit, cursor } }),
  predictCheck: (studyId: string, body: { param_set_id?: string | null; values: Record<string, number> }) =>
    request<PredictCheck>("POST", `/studies/${studyId}/predict/check`, { body }),

  // phase3.md §14.7 S9 일괄 예측·템플릿 응답(타입은 생성 스키마 기반, api/types.ts)
  /** 조합 미리보기(동기, member 이상). 생성은 createJob("PREDICT_BATCH") */
  batchPreview: (studyId: string, body: BatchPreviewRequest) =>
    request<BatchPreview>("POST", `/studies/${studyId}/predict-batches/preview`, { body }),
  batches: (studyId: string) => request<PredictBatchSummary[]>("GET", `/studies/${studyId}/predict-batches`),
  batch: (id: string) => request<PredictBatch>("GET", `/predict-batches/${id}`),
  /** UTF-8 BOM CSV(doe_no,run_key,folder,<파라미터>,<응답>,state) */
  batchCsv: (id: string) => fetchBlob(`/predict-batches/${id}/table.csv`),
  batchCurves: (id: string, q: { name?: string | null; max_points?: number } = {}) =>
    request<BatchCurves>("GET", `/predict-batches/${id}/curves`, { query: { name: q.name, max_points: q.max_points ?? 500 } }),
  cancelBatch: (id: string) => request<PredictBatch>("POST", `/predict-batches/${id}/cancel`),
  retryFailedBatch: (id: string) => request<BatchRetryFailed>("POST", `/predict-batches/${id}/retry-failed`),
  /** 템플릿 응답 정의 저장(power) */
  putParamSetResponses: (id: string, body: ParamSetResponsesPut) => request<ParamSet>("PUT", `/param-sets/${id}/responses`, { body }),

  /** S17 §22.3.5 끝난 배치의 H3D 성능 다시 추출(power) → 작업 PB_RESP_EXTRACT */
  extractBatchResponses: (id: string) => request<Job>("POST", `/predict-batches/${id}/extract-responses`),

  // §10.5 작업·로그·산출물
  createJob: (studyId: string, job_type: JobType, params: Record<string, unknown>) =>
    request<Job>("POST", `/studies/${studyId}/jobs`, { body: { job_type, params } }),
  jobs: (q: { study_id?: string; state?: string; mine?: boolean; job_type?: JobType; limit?: number }) =>
    request<JobSummary[]>("GET", "/jobs", { query: q }),
  job: (id: string) => request<Job>("GET", `/jobs/${id}`, { etag: true }),
  jobLog: (id: string, cursor = 0, limit = 65536) =>
    request<LogChunk>("GET", `/jobs/${id}/log`, { query: { cursor, limit } }),
  cancelJob: (id: string) => request<Job>("POST", `/jobs/${id}/cancel`),
  retryJob: (id: string, from_step?: number) =>
    request<Job>("POST", `/jobs/${id}/retry`, { body: from_step ? { from_step } : {} }),
  /** run별 HPC 행(phase2 §12, phase3 §16.9 scx 필드) */
  hpcJobs: (jobId: string) => request<HpcJob[]>("GET", `/jobs/${jobId}/hpc-jobs`),
  /** phase3 §16.5: SCX 제출 결과 모름 조치(202, 워커가 다음 확인 때 처리). version = 행 version */
  resolveHpcJob: (jobId: string, hid: string, body: { action: HpcResolveAction; external_job_id?: string; version: number }) =>
    request<HpcJob>("POST", `/jobs/${jobId}/hpc-jobs/${hid}/resolve`, { body }),
  artifacts: (jobId: string) => request<Artifact[]>("GET", `/jobs/${jobId}/artifacts`),
  artifactBlob: (id: string) => fetchBlob(`/artifacts/${id}/content`),
  // S10 컨투어 캡처(phase3.md §15.4)
  /** 방향별 PNG·동영상 목록(items[].image/video.url = /artifacts/{id}/media, 동영상 Range 지원) */
  jobMedia: (jobId: string) => request<JobMedia>("GET", `/jobs/${jobId}/media`),
  /** 다시 캡처(power) → 201 CONTOUR_RECAPTURE 작업 */
  captureJob: (jobId: string, body: CaptureRequest) => request<Job>("POST", `/jobs/${jobId}/capture`, { body }),
  /** 템플릿 컨투어 표시 설정 저장(power, null = 지움) */
  putParamSetDisplay: (id: string, display: ContourDisplay | null) => request<ParamSet>("PUT", `/param-sets/${id}/display`, { body: { display } }),
  /** 산출물 URL(서버가 준 내려받기 경로)을 fetch로 받기 — 목 서버도 같은 경로로 응답 */
  mediaBlob: (url: string) => fetchBlob(url.startsWith(API_PREFIX) ? url.slice(API_PREFIX.length) : url),

  /** B16: ④ 입력파일 zip (409 INPUT_NOT_READY) */
  inputZip: (jobId: string) => fetchBlob(`/jobs/${jobId}/artifacts/input.zip`),

  /** phase2.md §10: 오류 묶음 zip(본인·전역 관리자) */
  errorBundle: (jobId: string) => fetchBlob(`/jobs/${jobId}/error-bundle.zip`),

  // ---- 2차(phase2.md §12) ----
  // §12.5 ① 학습데이터
  train: (studyId: string) => request<TrainSetup>("GET", `/studies/${studyId}/train`),
  saveTrainParams: (
    studyId: string,
    body: { version: number; parameters: { name: string; min: number | null; max: number | null; use: boolean; format?: string; unit?: string }[] },
  ) => request<TrainSetup>("PUT", `/studies/${studyId}/train/params`, { body }),
  generateTpl: (studyId: string, version: number) => request<TrainSetup>("POST", `/studies/${studyId}/train/tpl`, { body: { version } }),
  doeTypes: () => request<DoeType[]>("GET", "/train/doe-types"),
  /** geometry-engine.md §7.3.1: ① native 추출 피처(종류·범위·그룹·하이라이트 PNG artifact id) */
  /** geometry-view.md §6.9: ①-1·①-2 공칭 3D 뷰(preview_available=false) */
  trainView: (studyId: string) => request<GeomView>("GET", `/studies/${studyId}/train/view`),
  trainFeatures: (studyId: string) => request<NativeFeatures>("GET", `/studies/${studyId}/train/features`),
  trainDoes: (studyId: string) => request<TrainDoe[]>("GET", `/studies/${studyId}/train/does`),
  trainDoe: (id: string) => request<TrainDoe>("GET", `/train-does/${id}`),
  /** ①-3 표본표 재사용: DOE 샘플 표(columns = run_key + 파라미터 이름 + 응답) */
  doeSamples: (id: string, limit = 1) => request<SamplePage>("GET", `/train-does/${id}/samples`, { query: { limit } }),
  trainRuns: (doeId: string, q: { state?: string; limit?: number; cursor?: string | null } = {}) =>
    requestPage<TrainRun[]>(`/train-does/${doeId}/runs`, { limit: q.limit ?? 200, state: q.state, cursor: q.cursor }),
  paramSetFromTrain: (studyId: string, body: { doe_id: string; runs?: "collected" | "all"; unit_system?: string; label?: string | null; tpl_source?: "doe" | "current" }) =>
    request<ParamSet>("POST", `/studies/${studyId}/param-sets/from-train`, { body }),

  // §12.6 ② 데이터 정리
  curationSources: (studyId: string) => request<CurationSource[]>("GET", `/studies/${studyId}/curation-sources`),
  curations: (studyId: string, kind?: "H3D" | "T01") => request<Curation[]>("GET", `/studies/${studyId}/curations`, { query: { kind } }),
  curation: (id: string) => request<Curation>("GET", `/curations/${id}`),
  curationFiles: (id: string, q: { ok?: boolean; limit?: number; cursor?: string | null } = {}) =>
    request<{ items: CurationFile[]; next_cursor: string | null }>("GET", `/curations/${id}/files`, { query: { ok: q.ok, limit: q.limit ?? 200, cursor: q.cursor } }),
  spdmImports: (studyId: string) => request<SpdmImport[]>("GET", `/studies/${studyId}/spdm-imports`),

  // §12.8 ⑤ 최적화
  optimizations: (studyId: string) => request<Optimization[]>("GET", `/studies/${studyId}/optimizations`),
  optimization: (id: string) => request<Optimization>("GET", `/optimizations/${id}`),
  responseCandidates: (studyId: string, modelId?: string | null) =>
    request<ResponseCandidates>("GET", `/studies/${studyId}/optimize/response-candidates`, { query: { model_id: modelId } }),

  // §12.2 환경 점검(전역 관리자)
  runEnvCheck: () => request<EnvCheck>("POST", "/admin/env-checks"),
  envChecks: (limit = 20) => requestPage<EnvCheckSummary[]>("/admin/env-checks", { limit }),
  envCheck: (id: string) => request<EnvCheck>("GET", `/admin/env-checks/${id}`),
  latestEnvCheck: () => request<EnvCheck>("GET", "/admin/env-checks/latest"),

  // §10.7 알림
  notifications: (afterSeq?: number, limit = 50) =>
    request<NotificationList>("GET", "/notifications", { query: { after_seq: afterSeq, limit } }),
  unreadCount: () => request<{ unread_count: number; max_seq: number }>("GET", "/notifications/unread-count"),
  markRead: (body: { seqs: number[] } | { all: true }) =>
    request<{ unread_count: number }>("POST", "/notifications/read", { body }),
};

export type Api = typeof api;
