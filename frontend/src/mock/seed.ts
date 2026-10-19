// 목 1차 시드(Study·데이터셋·모델·파라미터 세트·알림)와 가짜 응답·손실 곡선. data.ts가 재노출.
import type { Dataset, Model, NotificationItem, ParamSet, SampleRow, Study } from "../api/types";
import { T0, iso, rng } from "./base";

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

/** 응답 정의(S9 §14.6: spec = H3D 추출 정의. Energy는 옛 responses.json처럼 spec 없음) */
export const RESPONSES = [
  { name: "MaxStress", unit: "MPa", spec: { source: "H3D" as const, subcase: 1, datatype: "Stress", component: "vonMises", layer: "Max", stat: "MAX" as const } },
  { name: "MaxDisp", unit: "mm", spec: { source: "H3D" as const, subcase: 1, datatype: "Displacement", component: "Mag", layer: "", stat: "MAX" as const } },
  { name: "Energy", unit: "mJ", spec: null },
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
    // phase3.md §4.4 V3-S2-5: 데이터셋이 다른 모델 비교용(기존 시드 뒤에 추가)
    {
      id: "ds-0a7c41e2", study_id: "s-cushion", job_id: "j-ds0", status: "READY",
      source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/h3d_r1", h3d_count: 180, train_count: 162, eval_count: 18,
      holdout_ratio: 0.1, seed: 20261001, split_group: "file",
      options: { extract_faces: true, extract_mdi: false, extract_time_history_vectors: false },
      package_ready: false, created_by_name: "김연구", created_at: iso(60 * 24 * 4),
    },
  ];
}

export function seedModels(): Model[] {
  const c1 = lossCurve(1, 1500, 0.9);
  const c2 = lossCurve(2, 2000, 0.62);
  const c4 = lossCurve(4, 1000, 1.1);
  const c5 = lossCurve(5, 1180, 1.6);
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
    // phase3.md §4.4 V3-S2-5: metrics 키가 다른 모델(m-4: RMSE 추가·다른 데이터셋, m-5: MaxErr) — 기존 시드 뒤에 추가
    {
      ...common, id: "m-4", name: "cushion_TNS", version: 3, label: "lr 3e-4, 1000ep", dataset_id: "ds-0a7c41e2",
      source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/model_v3",
      log_status: "PARSED", epochs_total: 1000, last_epoch: 1000, ...curveStats(c4), loss_curve: c4, curve_points: c4.length,
      eval_status: "DONE", eval_score: { status: "PARSED", metrics: { R2: 0.948, MAE: 2.07, RMSE: 2.71 }, score_rel: "03_model/score/m-4/j-ev4/cushion_TNS.psscr" },
      is_final: false, registered_at: iso(60 * 30),
    },
    {
      ...common, id: "m-5", name: "cushion_MLP", version: 1, source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/model_mlp",
      log_status: "PARSED", epochs_total: 1200, last_epoch: 1180, ...curveStats(c5), loss_curve: c5, curve_points: c5.length,
      eval_status: "DONE", eval_score: { status: "PARSED", metrics: { MAE: 2.41, MaxErr: 7.9 }, score_rel: "03_model/score/m-5/j-ev5/cushion_MLP.psscr" },
      is_final: false, registered_by_name: "이해석", registered_at: iso(60 * 12),
    },
  ];
}

export function seedParamSet(): ParamSet {
  return {
    id: "ps-1", study_id: "s-cushion", source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/params", engine: "altair",
    unit_system: "mm-ton-s", parameters: PARAMS, responses: RESPONSES, sample_count: 120, sample_has_measured: true,
    cad_file_name: "cushion_base.x_t", starter_name: "cushion_0000.rad", input_kind: "assembly", assem_rel: "radioss_assem",
    // S10 컨투어 표시 설정
    display: { field: "Stress", component: "vonMises", avgmode: "simple", comps: ["CUSHION_TOP", "FOAM"], legend: { mode: "auto", min: null, max: null }, views: ["iso", "front", "top", "right"] },
    tpl_params: [
      { var: "var_1", name: "THK_TOP", format: "%.4f" },
      { var: "var_2", name: "THK_FOAM", format: "%.4f" },
      { var: "var_3", name: "E_FOAM", format: "%.3f" },
      { var: "var_4", name: "RIB_N", format: "%3i" },
    ],
    is_current: true, origin: "FOLDER", train_doe_id: null, registered_by_name: "김연구", registered_at: iso(60 * 5),
  };
}

/** S9: 조립 폴더 없는 템플릿(쿠션 단독 메시 — m1 EPS_mesh로 바로 예측) */
export function seedMeshOnlyParamSet(): ParamSet {
  return {
    ...seedParamSet(), id: "ps-2", label: "쿠션 단독 v1", source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/cushion_only",
    input_kind: "mesh_only", assem_rel: null, starter_name: null, sample_count: 0, sample_has_measured: false,
    responses: RESPONSES.slice(0, 2), is_current: false, registered_at: iso(60 * 3),
  };
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
