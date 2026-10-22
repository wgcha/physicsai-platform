// API 타입(R-F 분할) — S9 템플릿 예측·DOE 일괄 예측·응답 추출(phase3.md §14). `api/types`가 재노출.
import type { S, Override } from "./typesBase";
import type { ContourLegend, ViewKey } from "./types";

// ---------------------------------------------------------------------------
// S9 템플릿 예측·DOE 일괄 예측·응답 추출(phase3.md §14) — 생성 타입 기반, 열거형·dict 필드만 계약 값으로 좁힘
// ---------------------------------------------------------------------------

/** 템플릿 입력 종류: 조립 폴더 포함(assembly) / 쿠션 단독 메시(mesh_only) */
export type InputKind = "mesh_only" | "assembly";
/** input-kind.md IK-1: 실행 단위 예측 입력 종류(공개 값). 저장 값 InputKind(assembly|mesh_only)와 구분 */
export type PredictInput = "assembly" | "cushion";
/** ④ 화면 입력 방식(localStorage `physicsai.stage4.inputMode`) */
export type InputMode = "template" | "batch" | "prepared";

export type ResponseStat = "MAX" | "MIN" | "ABSMAX";
/** 응답 정의 spec(§14.6, ⑤ OPTIMIZE.responses의 H3D 형식, goal·bound 없음) */
export interface H3dResponseSpec {
  source: "H3D";
  subcase: number;
  datatype: string;
  component: string;
  layer: string;
  stat: ResponseStat;
}
/** S17 §22.3.1 성능 정의 CURVE: 예측 run curve.json 계열 1개의 대표값. series null = 그 run의 첫 계열 */
export interface CurveResponseSpec {
  source: "CURVE";
  series: string | null;
  stat: ResponseStat;
}
export type ResponseSpec = H3dResponseSpec | CurveResponseSpec;
/** spec은 백엔드 스키마가 dict라 계약 형식으로 좁힌다. spec null = 이름·단위만(추출 안 함, D3-51) */
export type TemplateResponse = Override<S["ResponseDef"], { unit: string; spec?: ResponseSpec | null }>;
/** PUT /param-sets/{id}/responses 본문(백엔드 스키마는 dict 목록). spec null = 이름·단위만(추출 안 함) */
export interface ParamSetResponsesPut {
  responses: { name: string; unit: string; spec: ResponseSpec | null }[];
}

/** S15(§20.6)·doe-methods.md: 12개 kind(+ halton·random) — 생성 타입의 discriminated union */
export type BatchSource = S["PredictBatchPreviewRequest"]["source"];
export type BatchSourceKind = BatchSource["kind"];

/** 영향도 등급(§20.7): formal 정식 · reference 참고용(회색 안내) · off 비활성(사유) */
export type InfluenceClass = S["DoeResultTable"]["influence_class"];
/** 표본 방식 요약(미리보기·배치 상세 `sampling`). 서버가 등급을 정한다(formal·reference) */
export type BatchSampling = S["SamplingInfo"];
/** GET /studies/{id}/predict-batches 행의 `sampling` */
export type BatchSamplingBrief = S["SamplingSummary"];
/** 미리보기 `notes[]`(막지 않는 안내, §20.9) */
export type BatchNote = S["BatchNote"];

/** POST /studies/{id}/predict-batches/preview 본문 */
export type BatchPreviewRequest = Override<S["PredictBatchPreviewRequest"], { param_set_id: string; source: BatchSource }>;
export type BatchPreviewRow = S["BatchPreviewRow"];
export type BatchProblemCode =
  | "TABLE_HEADER" | "TABLE_VALUE" | "TEXT_TOO_LARGE" | "TOO_MANY_ROWS" | "TOO_FEW_ROWS" | "RANGE_INVALID" | "DOE_PARAM_MISMATCH"
  | "COUNT_NOT_POW2" | "CONTINUE_INVALID" | "SEQUENCE_MISMATCH" | "LEVELS_INVALID" | "DESIGN_UNSUPPORTED" | "GENERATOR_UNAVAILABLE"
  | "VAR_RANGE_INVALID" | "TABLE_OUT_OF_RANGE";
export type BatchProblem = S["BatchProblem"];
/** estimate_min = 최근 성공 PREDICT 5개 중앙값×N(분), 없으면 null */
export type BatchPreview = S["PredictBatchPreview"];
/** PREDICT_BATCH 생성 params(POST /studies/{id}/jobs) — 작업 params는 dict라 생성 타입 없음(phase3.md §14.5·§15.3) */
export interface PredictBatchParams {
  param_set_id: string;
  model_id: string | null;
  multi_execution: number;
  source: BatchSource;
  /** S10 §15.3: 배치 단위 표시 설정(범례 fixed로 run끼리 비교) */
  display?: { legend: ContourLegend } | null;
  /** D3-53: 하위 예측 컨투어 캡처 옵션(없으면 기본 — 템플릿 display.views·config capture) */
  capture?: PredictBatchCapture | null;
  /** native-vars.md §6.3: Native 템플릿 변수 그 자리 편집(이 실행에만 적용) */
  vars?: { add?: string[]; exclude?: string[] } | null;
  /** input-kind.md IK-1: 생략 = 서버 기본(조립 가능 → assembly, 쿠션 전용 → cushion) */
  input?: PredictInput;
}
/** D3-53: enabled false → 하위 CONTOUR_CAPTURE SKIPPED. views·video 생략 = 기본 */
export interface PredictBatchCapture {
  enabled: boolean;
  views?: ViewKey[];
  video?: boolean;
}

export type BatchStatus = "GENERATING" | "PREDICTING" | "DONE" | "FAILED" | "CANCELED";
export type PredictBatchSummary = Override<S["PredictBatchSummary"], { status: BatchStatus }>;
export type BatchRowState = "GEN_PENDING" | "GENERATING" | "GEN_FAILED" | "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELED";
/** media_views = S10 캡처된 방향(없으면 빈 배열) */
export type PredictBatchRow = Override<S["BatchRunRow"], { state: BatchRowState; media_views?: ViewKey[] }>;
export type PredictBatch = Override<S["PredictBatch"], { status: BatchStatus; rows: PredictBatchRow[] }>;
/** GET /predict-batches/{bid}/curves */
export type BatchCurves = S["BatchCurves"];
/** POST /predict-batches/{bid}/retry-failed → 201 */
export type BatchRetryFailed = S["BatchRetryFailed"];
