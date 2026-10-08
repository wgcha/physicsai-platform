// 목 데이터(백엔드 없이 화면 개발·시험·스크린샷용). 운영 빌드에는 포함되지 않는다.
import { JOB_STAGE } from "../lib/format";
import type {
  Dataset,
  Job,
  JobStep,
  JobType,
  Me,
  Model,
  NotificationItem,
  ParamSet,
  Project,
  SampleRow,
  Study,
} from "../api/types";

export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type MockUserKey = "admin" | "power" | "general" | "anon";

export const USERS: Record<Exclude<MockUserKey, "anon">, Me> = {
  admin: { user_id: "u-admin", username: "admin01", display_name: "박관리", is_global_admin: true, roles: {} },
  power: { user_id: "u-power", username: "kim.res", display_name: "김연구", is_global_admin: false, roles: { "p-cushion": "power", "p-hinge": "general" } },
  general: { user_id: "u-general", username: "lee.view", display_name: "이조회", is_global_admin: false, roles: { "p-cushion": "general" } },
};

export const PROJECTS: Project[] = [
  { id: "p-cushion", name: "폴더블 쿠션 구조", product_name: "FD-X 2027" },
  { id: "p-hinge", name: "힌지 내구 해석", product_name: "FD-X 2027" },
  { id: "p-battery", name: "배터리 낙하 충격", product_name: "BR-S" },
];

const T0 = Date.parse("2026-10-08T09:00:00+09:00");
export const iso = (minAgo: number, base = Date.now()) => new Date(base - minAgo * 60_000).toISOString();

export const STEP_CHAINS: Record<JobType, { key: string; kind: JobStep["kind"] }[]> = {
  DATASET_CREATE: [
    { key: "DS_SCAN", kind: "INTERNAL" },
    { key: "DS_YAML", kind: "INTERNAL" },
    { key: "EDSPY_DATASET_TRAIN", kind: "LOCAL" },
    { key: "EDSPY_DATASET_EVAL", kind: "LOCAL" },
    { key: "DS_REGISTER", kind: "INTERNAL" },
  ],
  PACKAGE_EXPORT: [
    { key: "PKG_COPY", kind: "INTERNAL" },
    { key: "PKG_TEXT", kind: "INTERNAL" },
  ],
  MODEL_REGISTER: [
    { key: "MR_VALIDATE", kind: "INTERNAL" },
    { key: "MR_COPY", kind: "INTERNAL" },
    { key: "MR_PARSE_LOG", kind: "INTERNAL" },
    { key: "MR_REGISTER", kind: "INTERNAL" },
  ],
  EVALUATE: [
    { key: "EV_PREP", kind: "INTERNAL" },
    { key: "EDSPY_SCORE", kind: "LOCAL" },
    { key: "EV_PARSE", kind: "INTERNAL" },
  ],
  PREDICT: [
    { key: "PR_PREP", kind: "INTERNAL" },
    { key: "TPL_RENDER", kind: "INTERNAL" },
    { key: "GEOM_UPDATE", kind: "LOCAL" },
    { key: "MESH", kind: "LOCAL" },
    { key: "RAD_ASSEMBLE", kind: "INTERNAL" },
    { key: "EDSPY_PREDICT", kind: "LOCAL" },
    { key: "CONTOUR_PREVIEW", kind: "LOCAL" },
    { key: "CURVE_PICK", kind: "INTERNAL" },
    { key: "RESPONSE_EXTRACT", kind: "LOCAL" },
    { key: "RESPONSE_TABLE", kind: "INTERNAL" },
  ],
  PREDICT_VERIFY: [
    { key: "PV_PREP", kind: "INTERNAL" },
    { key: "HPC_SUBMIT", kind: "HPC_SUBMIT" },
    { key: "HPC_WAIT", kind: "HPC_WAIT" },
    { key: "COLLECT", kind: "COLLECT" },
    { key: "PV_EXTRACT", kind: "LOCAL" },
    { key: "PV_TABLE", kind: "INTERNAL" },
  ],
  // phase2.md §6.1
  TD_EXTRACT_PARAMS: [
    { key: "TX_PREP", kind: "INTERNAL" },
    { key: "SIMLAB_EXTRACT", kind: "LOCAL" },
    { key: "TX_PARSE", kind: "INTERNAL" },
  ],
  TD_DOE_GEN: [
    { key: "DG_PREP", kind: "INTERNAL" },
    { key: "HST_GEN_RADIOSS", kind: "LOCAL" },
    { key: "DG_SCAN", kind: "INTERNAL" },
  ],
  TD_SOLVE: [
    { key: "TS_PREP", kind: "INTERNAL" },
    { key: "HPC_SUBMIT", kind: "HPC_SUBMIT" },
    { key: "HPC_WAIT", kind: "HPC_WAIT" },
    { key: "COLLECT", kind: "COLLECT" },
    { key: "TS_REGISTER", kind: "INTERNAL" },
  ],
  TD_RESULT_IMPORT: [
    { key: "RI_SCAN", kind: "INTERNAL" },
    { key: "RI_COPY", kind: "INTERNAL" },
    { key: "RI_REGISTER", kind: "INTERNAL" },
  ],
  TD_RESP_EXTRACT: [
    { key: "RX_PREP", kind: "INTERNAL" },
    { key: "RESPONSE_EXTRACT_RUNS", kind: "LOCAL" },
    { key: "RX_TABLE", kind: "INTERNAL" },
  ],
  CU_H3D_PREVIEW: [
    { key: "CP_PREP", kind: "INTERNAL" },
    { key: "HW_PREVIEW_H3D", kind: "LOCAL" },
    { key: "CP_PARSE", kind: "INTERNAL" },
  ],
  CU_H3D_CURATE: [
    { key: "HC_PREP", kind: "INTERNAL" },
    { key: "HVTRANS_CURATE", kind: "LOCAL" },
    { key: "HC_REGISTER", kind: "INTERNAL" },
  ],
  CU_T01_PREVIEW: [
    { key: "TP_PREP", kind: "INTERNAL" },
    { key: "HW_PREVIEW_T01", kind: "LOCAL" },
    { key: "TP_PARSE", kind: "INTERNAL" },
  ],
  CU_T01_CURVES: [
    { key: "TC_PREP", kind: "INTERNAL" },
    { key: "HW_CURVE_EXPORT", kind: "LOCAL" },
    { key: "TC_REGISTER", kind: "INTERNAL" },
  ],
  SPDM_IMPORT: [
    { key: "SI_SCAN", kind: "INTERNAL" },
    { key: "SI_COPY", kind: "INTERNAL" },
    { key: "SI_REGISTER", kind: "INTERNAL" },
  ],
  OPTIMIZE: [
    { key: "OP_PREP", kind: "INTERNAL" },
    { key: "HST_OPTIMIZE", kind: "LOCAL" },
    { key: "OP_SUMMARY", kind: "INTERNAL" },
  ],
};

/** step_key → 한국어 표시(백엔드 current_step_label 흉내) */
export const STEP_LABEL: Record<string, string> = {
  DS_SCAN: "h3d 확인", DS_YAML: "설정 작성", EDSPY_DATASET_TRAIN: "학습 데이터 변환", EDSPY_DATASET_EVAL: "평가 데이터 변환", DS_REGISTER: "등록",
  PKG_COPY: "복사", PKG_TEXT: "명령 작성", MR_VALIDATE: "검사", MR_COPY: "복사", MR_PARSE_LOG: "로그 해석", MR_REGISTER: "등록",
  EV_PREP: "준비", EDSPY_SCORE: "점수 계산", EV_PARSE: "결과 해석",
  PR_PREP: "준비", TPL_RENDER: "tpl 렌더", GEOM_UPDATE: "형상 갱신", MESH: "메싱", RAD_ASSEMBLE: "입력파일", EDSPY_PREDICT: "예측", CONTOUR_PREVIEW: "컨투어", CURVE_PICK: "커브", RESPONSE_EXTRACT: "응답 추출", RESPONSE_TABLE: "응답 표",
  PV_PREP: "준비", HPC_SUBMIT: "PBS 제출", HPC_WAIT: "PBS 대기", COLLECT: "결과 회수", PV_EXTRACT: "응답 추출", PV_TABLE: "응답 표",
  TX_PREP: "CAD 복사", SIMLAB_EXTRACT: "SimLab 추출", TX_PARSE: "XML 해석",
  DG_PREP: "입력 준비", HST_GEN_RADIOSS: "HyperStudy 입력 생성", DG_SCAN: "run 확인",
  TS_PREP: "run 준비", TS_REGISTER: "회수 등록",
  RI_SCAN: "run 매칭", RI_COPY: "복사", RI_REGISTER: "등록",
  RX_PREP: "준비", RESPONSE_EXTRACT_RUNS: "run 응답 추출", RX_TABLE: "표 작성",
  CP_PREP: "준비", HW_PREVIEW_H3D: "h3d 구조 읽기", CP_PARSE: "해석",
  HC_PREP: "cfg 작성", HVTRANS_CURATE: "hvtrans 큐레이션", HC_REGISTER: "등록",
  TP_PREP: "준비", HW_PREVIEW_T01: "T01 구조 읽기", TP_PARSE: "해석",
  TC_PREP: "준비", HW_CURVE_EXPORT: "곡선 내보내기", TC_REGISTER: "등록",
  SI_SCAN: "SPDM 확인", SI_COPY: "복사", SI_REGISTER: "등록",
  OP_PREP: "준비", HST_OPTIMIZE: "HyperStudy 최적화", OP_SUMMARY: "결과 정리",
};

/** 1차 기본 설정에서 SKIPPED가 되는 step(템플릿 null) */
export const SKIPPED_BY_DEFAULT = new Set(["MESH", "RESPONSE_EXTRACT"]);

export function lossCurve(seed: number, epochs: number, floor: number): [number, number][] {
  const r = rng(seed);
  const pts: [number, number][] = [];
  const n = Math.min(400, epochs);
  for (let i = 0; i < n; i++) {
    const e = Math.round(1 + (i / (n - 1)) * (epochs - 1));
    const base = 104 * Math.exp(-e / (epochs * 0.09)) + floor * (1 + 2.5 * Math.exp(-e / (epochs * 0.4)));
    pts.push([e, base * (1 + (r() - 0.5) * 0.12)]);
  }
  return pts;
}

export function curveStats(c: [number, number][]) {
  let min = c[0];
  for (const p of c) if (p[1] < min[1]) min = p;
  return { final_loss: c[c.length - 1][1], min_loss: min[1], min_loss_epoch: min[0] };
}

export const PARAMS = [
  { name: "THK_TOP", nominal: 0.6, min: 0.3, max: 1.2, unit: "mm" },
  { name: "THK_FOAM", nominal: 2.0, min: 1.0, max: 3.0, unit: "mm" },
  { name: "E_FOAM", nominal: 8.0, min: 2.0, max: 20.0, unit: "MPa" },
  { name: "RIB_N", nominal: 4, min: 2, max: 8, unit: "" },
];

export const RESPONSES = [
  { name: "MaxStress", unit: "MPa" },
  { name: "MaxDisp", unit: "mm" },
  { name: "Energy", unit: "mJ" },
];

/** 가짜 응답 함수(목 전용) */
export function responseFn(v: Record<string, number>): Record<string, number> {
  const t = v.THK_TOP ?? 0.6, f = v.THK_FOAM ?? 2, e = v.E_FOAM ?? 8, n = Math.round(v.RIB_N ?? 4);
  return {
    MaxStress: 182 / (t * 1.6 + 0.2) + 2.1 * e - 3.2 * f + 1.4 * n,
    MaxDisp: 2.4 / (t + 0.3) + 3.1 / Math.sqrt(e) + 0.35 * f - 0.08 * n,
    Energy: 48 * f + 2.6 * e * t + 6.5 * n,
  };
}

export function makeSamples(count: number): SampleRow[] {
  const r = rng(42);
  const rows: SampleRow[] = [];
  for (let i = 0; i < count; i++) {
    const values: Record<string, number> = {};
    for (const p of PARAMS) {
      const raw = p.min + r() * (p.max - p.min);
      values[p.name] = p.name === "RIB_N" ? Math.round(raw) : Number(raw.toFixed(3));
    }
    const resp = responseFn(values);
    const measured: Record<string, number> = {};
    for (const k of Object.keys(resp)) measured[k] = Number((resp[k] * (1 + (r() - 0.5) * 0.06)).toFixed(3));
    rows.push({ run_key: `run_${String(i + 1).padStart(4, "0")}`, values, measured });
  }
  return rows;
}

export function seedStudies(): Study[] {
  const base = {
    created_by: "u-power",
    created_by_name: "김연구",
    version: 3,
    can_execute: false,
  };
  return [
    { ...base, id: "s-cushion", project_id: "p-cushion", folder_name: "cushion_v1", title: "쿠션 두께·리브 예측", status: "ACTIVE", final_model_id: "m-1", created_at: iso(60 * 24 * 9, T0), updated_at: iso(40, T0) },
    { ...base, id: "s-cushion-old", project_id: "p-cushion", folder_name: "cushion_pilot", title: "쿠션 파일럿", status: "ARCHIVED", final_model_id: null, created_at: iso(60 * 24 * 40, T0), updated_at: iso(60 * 24 * 30, T0) },
    { ...base, id: "s-hinge", project_id: "p-hinge", folder_name: "hinge_cycle", title: "힌지 반복 굽힘", status: "ACTIVE", final_model_id: null, created_by: "u-other", created_by_name: "최해석", created_at: iso(60 * 24 * 3, T0), updated_at: iso(90, T0) },
  ];
}

export function seedDatasets(): Dataset[] {
  return [
    {
      id: "ds-2", study_id: "s-cushion", job_id: "j-ds2", status: "READY",
      source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/h3d_r2", h3d_count: 240, train_count: 216, eval_count: 24,
      holdout_ratio: 0.1, seed: 20261008, split_group: "file",
      options: { extract_faces: true, extract_mdi: false, extract_time_history_vectors: false },
      package_ready: true, created_by_name: "김연구", created_at: iso(60 * 26),
    },
    {
      id: "ds-1", study_id: "s-cushion", job_id: "j-ds1", status: "FAILED",
      source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/h3d", h3d_count: 240, train_count: null, eval_count: null,
      holdout_ratio: 0.1, seed: 20261008, split_group: "file",
      options: { extract_faces: true, extract_mdi: false, extract_time_history_vectors: false },
      package_ready: false, created_by_name: "김연구", created_at: iso(60 * 30),
    },
  ];
}

export function seedModels(): Model[] {
  const c1 = lossCurve(1, 1500, 0.9);
  const c2 = lossCurve(2, 2000, 0.62);
  const common = {
    study_id: "s-cushion", label: null, dataset_id: "ds-2", log_parser: "default", status: "ACTIVE" as const,
    registered_by_name: "김연구", row_version: 1,
  };
  return [
    {
      ...common, id: "m-1", name: "cushion_TNS", version: 1, source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/model_v1",
      log_status: "PARSED", epochs_total: 1500, last_epoch: 1500, ...curveStats(c1), loss_curve: c1, curve_points: c1.length,
      eval_status: "DONE", eval_score: { status: "PARSED", metrics: { R2: 0.962, MAE: 1.84 }, score_rel: "03_model/score/m-1/j-ev1/cushion_TNS.psscr" },
      is_final: true, registered_at: iso(60 * 20),
    },
    {
      ...common, id: "m-2", name: "cushion_TNS", version: 2, label: "lr 1e-4, 2000ep", source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/model_v2",
      log_status: "PARSED", epochs_total: 2000, last_epoch: 2000, ...curveStats(c2), loss_curve: c2, curve_points: c2.length,
      eval_status: "DONE", eval_score: { status: "PARSED", metrics: { R2: 0.971, MAE: 1.52 }, score_rel: "03_model/score/m-2/j-ev2/cushion_TNS.psscr" },
      is_final: false, registered_at: iso(60 * 6),
    },
    {
      ...common, id: "m-3", name: "cushion_GNN", version: 1, source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/model_gnn",
      log_status: "UNRECOGNIZED", log_parser: null, epochs_total: null, last_epoch: null, final_loss: null, min_loss: null, min_loss_epoch: null,
      loss_curve: null, curve_points: 0, eval_status: "NONE", eval_score: null, is_final: false, registered_at: iso(50),
    },
  ];
}

export function seedParamSet(): ParamSet {
  return {
    id: "ps-1", study_id: "s-cushion", source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/params",
    unit_system: "mm-ton-s", parameters: PARAMS, responses: RESPONSES, sample_count: 120, sample_has_measured: true,
    cad_file_name: "cushion_base.x_t", starter_name: "cushion_0000.rad",
    tpl_params: [
      { var: "var_1", name: "THK_TOP", format: "%.4f" },
      { var: "var_2", name: "THK_FOAM", format: "%.4f" },
      { var: "var_3", name: "E_FOAM", format: "%.3f" },
      { var: "var_4", name: "RIB_N", format: "%3i" },
    ],
    is_current: true, origin: "FOLDER", train_doe_id: null, registered_by_name: "김연구", registered_at: iso(60 * 5),
  };
}

export function makeSteps(type: JobType, doneCount: number, runningIdx: number | null, opts: { failedIdx?: number } = {}): JobStep[] {
  return STEP_CHAINS[type].map((s, i) => {
    let state: JobStep["state"] = "PENDING";
    if (opts.failedIdx !== undefined && i === opts.failedIdx) state = "FAILED";
    else if (opts.failedIdx !== undefined && i > opts.failedIdx) state = "SKIPPED";
    else if (i < doneCount) state = SKIPPED_BY_DEFAULT.has(s.key) ? "SKIPPED" : "SUCCEEDED";
    else if (runningIdx !== null && i === runningIdx) state = "RUNNING";
    return {
      step_no: i + 1, step_key: s.key, kind: s.kind, state,
      progress_pct: state === "RUNNING" ? null : null, progress_label: null,
      started_at: state === "PENDING" ? null : iso(5), finished_at: state === "SUCCEEDED" ? iso(1) : null,
      exit_code: state === "SUCCEEDED" && s.kind === "LOCAL" ? 0 : null,
      failure_code: state === "FAILED" ? "EXIT_NONZERO" : null, failure_message: state === "FAILED" ? "종료코드 1" : null,
    };
  });
}

export function baseJob(p: Partial<Job> & Pick<Job, "id" | "study_id" | "project_id" | "study_title" | "job_type" | "state">): Job {
  const lane = ["PACKAGE_EXPORT", "MODEL_REGISTER", "TD_RESULT_IMPORT", "SPDM_IMPORT"].includes(p.job_type) ? "LIGHT" : "SLOT";
  return {
    stage: JOB_STAGE[p.job_type],
    lane,
    created_by: "u-power",
    created_by_name: "김연구",
    queue_position: null,
    progress_pct: null,
    progress_label: null,
    cancel_requested: false,
    created_at: iso(10),
    started_at: null,
    params: {},
    result: null,
    warnings: [],
    steps: makeSteps(p.job_type, 0, null),
    failure_code: null,
    failure_message: null,
    finished_at: null,
    retry_of_job_id: null,
    version: 1,
    can_cancel: false,
    can_retry: false,
    ...p,
  } as Job;
}

export function seedNotifications(): NotificationItem[] {
  const mk = (seq: number, user: string, event: NotificationItem["event"], title: string, body: string, minAgo: number, read: boolean, job: string | null = null, study = "s-cushion", project = "p-cushion"): NotificationItem & { user_id: string } => ({
    seq, user_id: user, event, job_id: job, study_id: study, project_id: project, title, body,
    created_at: iso(minAgo), read_at: read ? iso(minAgo - 1) : null,
  });
  return [
    mk(1, "u-power", "JOB_SUCCEEDED", "완료: 데이터셋 생성 (쿠션 두께·리브 예측)", "학습 216 / 평가 24", 60 * 26, true, "j-ds2"),
    mk(2, "u-power", "JOB_SUCCEEDED", "완료: 학습 패키지 내보내기 (쿠션 두께·리브 예측)", "", 60 * 25, true, "j-pkg"),
    mk(3, "u-power", "JOB_SUCCEEDED", "완료: 예측 (쿠션 두께·리브 예측)", "", 30, false, "j-pred"),
    mk(4, "u-admin", "JOB_FAILED", "실패: 데이터셋 생성 (쿠션 두께·리브 예측) — EXIT_NONZERO", "EDSPY_DATASET_TRAIN 종료코드 1", 60 * 30, true, "j-ds1"),
    mk(5, "u-admin", "JOB_SUCCEEDED", "완료: 예측 (쿠션 두께·리브 예측)", "", 30, false, "j-pred"),
    mk(6, "u-admin", "MY_TURN_NEXT", "다음 차례입니다: 평가 (쿠션 두께·리브 예측)", "", 8, false, "j-q1"),
    mk(7, "u-general", "JOB_SUCCEEDED", "완료: 예측 (쿠션 두께·리브 예측)", "", 30, false, "j-pred"),
  ];
}

export function contourSvg(values: Record<string, number>): string {
  const t = values.THK_TOP ?? 0.6;
  const n = Math.round(values.RIB_N ?? 4);
  const ribs = Array.from({ length: n }, (_, i) => 70 + (i * 460) / Math.max(1, n - 1));
  const maxS = responseFn(values).MaxStress;
  const legend = ["#1d3fbf", "#1f7fd6", "#22b3c9", "#3cc76a", "#c9d62a", "#f2a81d", "#e5521b", "#c0151b"];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="560" viewBox="0 0 960 560">
<defs>
<radialGradient id="g" cx="${42 + t * 10}%" cy="48%" r="62%">
<stop offset="0" stop-color="#c0151b"/><stop offset="0.16" stop-color="#e5521b"/><stop offset="0.3" stop-color="#f2a81d"/>
<stop offset="0.44" stop-color="#c9d62a"/><stop offset="0.58" stop-color="#3cc76a"/><stop offset="0.72" stop-color="#22b3c9"/>
<stop offset="0.86" stop-color="#1f7fd6"/><stop offset="1" stop-color="#1d3fbf"/></radialGradient>
<pattern id="mesh" width="14" height="14" patternUnits="userSpaceOnUse"><path d="M14 0H0V14" fill="none" stroke="#000" stroke-opacity="0.14" stroke-width="0.6"/></pattern>
</defs>
<rect width="960" height="560" fill="#f4f5f7"/>
<g transform="translate(110 120)">
<rect x="0" y="0" width="600" height="300" rx="34" fill="url(#g)"/>
${ribs.map((x) => `<rect x="${x - 6}" y="18" width="12" height="264" rx="4" fill="#000" fill-opacity="0.12"/>`).join("")}
<rect x="0" y="0" width="600" height="300" rx="34" fill="url(#mesh)"/>
<rect x="0" y="0" width="600" height="300" rx="34" fill="none" stroke="#333" stroke-width="1.5"/>
</g>
<g transform="translate(800 110)" font-family="sans-serif" font-size="13" fill="#222">
<text x="0" y="-14" font-weight="600">von Mises [MPa]</text>
${legend
  .slice()
  .reverse()
  .map((c, i) => `<rect x="0" y="${i * 38}" width="26" height="38" fill="${c}"/><text x="34" y="${i * 38 + 5}">${((maxS * (8 - i)) / 8).toFixed(1)}</text>`)
  .join("")}
<text x="34" y="${8 * 38 + 4}">0.0</text>
</g>
<text x="110" y="470" font-family="sans-serif" font-size="13" fill="#555">Subcase 1 · Simulation 41 (t = 0.0120 s) · 예측 (목 이미지)</text>
</svg>`;
}

export function curveJson(values: Record<string, number>) {
  const r = responseFn(values);
  const x: number[] = [];
  const y: number[] = [];
  const y2: number[] = [];
  for (let i = 0; i <= 60; i++) {
    const tt = (i / 60) * 0.012;
    x.push(Number(tt.toFixed(5)));
    y.push(Number((r.MaxDisp * (1 - Math.exp(-i / 9)) * (1 + 0.08 * Math.sin(i / 3))).toFixed(4)));
    y2.push(Number((r.MaxDisp * 0.62 * (1 - Math.exp(-i / 14))).toFixed(4)));
  }
  return { file: "cushion_0000_pred_T01.xy", series: [{ name: "Node 10234 변위 [mm]", x, y }, { name: "Node 20811 변위 [mm]", x, y: y2 }], note: null };
}

export const PREVIEW_JSON = {
  file: "cushion_0000_pred.h3d",
  subcases: [{ name: "Subcase 1", simulations: 42, datatypes: ["Displacement", "Stress (von Mises)", "Plastic Strain"] }],
};

export const COMMANDS_TXT = `# PhysicsAI 학습 명령 예시 (HPC에서 직접 실행)
# 단위계: mm-ton-s. 이 폴더의 dataset_train.psdata는 학습용입니다(평가용 홀드아웃 제외).
edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg > train.log 2>&1
# 전이학습:
edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg --pretrained-model <PRETRAINED>.psmdl > train.log 2>&1
# 학습이 끝나면 .psmdl, 사용한 .pscfg, train.log를 한 폴더에 모아 플랫폼 ③-4 "모델 등록"에서 그 폴더 경로를 지정하세요.
# 로그의 loss 줄 예: "epoch=   1/1500  loss=1.03956e+02"
`;
