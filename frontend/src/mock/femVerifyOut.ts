// S16 V2 목(phase3 §21.3, R-F 분할): 응답 모양(요약·상세·미디어·커브·CSV)·취소·다시 실행.
import type { Job } from "../api/types";
import type { FemMedia, FemVerification, FemVerifySummary, FvStatus } from "../api/femVerify";
import { curveJson } from "./data";
import { file as mediaFile } from "./capture";
import { type MockResp } from "./route";
import type { MockServer } from "./server";
import { viewLabel } from "../lib/views";
import { JOB_STATE_LABEL } from "../lib/format";
import { TERMINAL, fvLabel, latest, newJob } from "./femVerifyRec";
import type { FemRec } from "./femVerifyRec";
import { activeOf } from "./femVerifyCreate";

// ------------------------------------------------------------------ 출력
const STATUS_TEXT: Record<FvStatus, string> = { WAITING_PREDICT: "예측 실행 중", RUNNING: "실행 중", DONE: "완료", FAILED: "실패", CANCELED: "취소됨" };

export function summaryOf(r: FemRec): FemVerifySummary {
  return {
    id: r.id, label: fvLabel(r.fv_no), status: r.status, source_label: r.source_label, source_kind: r.source_kind, links: r.links,
    max_abs_diff_pct: r.compare?.max_abs_diff_pct ?? null, worst: r.compare?.worst ?? null, created_at: r.created_at, created_by_name: r.created_by_name, finished_at: r.finished_at, values: r.values,
  };
}

export function detailOf(srv: MockServer, r: FemRec): FemVerification {
  const job = latest(srv, r.job_id);
  const pj = latest(srv, r.predict_job_id);
  const me = srv.me;
  const s = srv.studies.find((x) => x.id === r.study_id)!;
  const ps = srv.paramSets.find((x) => x.id === r.param_set_id) ?? null;
  const model = srv.models.find((m) => m.id === r.model_id);
  const dir = srv.disp(r.study_id, `04_verify/${fvLabel(r.fv_no)}`);
  const a = `${dir}\\a${r.attempt_no}`;
  const owner = !!me && (me.is_global_admin || me.user_id === r.created_by);
  const power = !!me && ["power", "admin"].includes(srv.role(s.project_id) ?? "");
  const text = r.status === "RUNNING" && job ? (job.state === "WAITING_HPC" || job.state === "COLLECTING" ? (r.hpc_mode === "scx" ? "해석 대기(SCX)" : "해석 대기(PBS)") : `${JOB_STATE_LABEL[job.state]}`) : STATUS_TEXT[r.status];
  return {
    ...summaryOf(r),
    status_text: text,
    source: { kind: r.source_kind, label: r.source_label },
    design: {
      param_set: ps ? { id: ps.id, label: ps.label ?? (ps.source_path.split(/[\\/]/).filter(Boolean).pop() ?? null), input_kind: ps.input_kind } : null,
      model: model ? { id: model.id, name: model.name, version: model.version } : null,
      values: r.values, applied_values: r.applied_values, out_of_range: r.out_of_range,
    },
    predict: { job_id: pj?.id ?? r.predict_job_id, state: pj?.state ?? null, companion: r.companion, reuse: !r.companion, will_run: r.companion && r.status === "WAITING_PREDICT" },
    assembly: { kind: r.assem_kind, label: r.assem_label, path: r.assem_path, snapshot_dir: r.job_id ? `${a}\\assem` : null },
    input_mode: r.input_mode,
    attempt_no: r.attempt_no,
    dir,
    paths: {
      input_dir: r.job_id ? `${a}\\input` : null, result_dir: r.status === "DONE" ? `${a}\\result` : null, starter: r.job_id ? "Face_Drop_0000.rad" : null,
      remote_dir: r.hpc_mode === "scx" && r.job_id ? `/Users/vd.dashboard/cushion/04_${fvLabel(r.fv_no)}_20261019T101500` : null,
    },
    job: job ? ({ ...job, steps: undefined } as never) : null,
    compare: r.compare,
    warnings: r.warnings,
    failure: r.failure,
    can_cancel: activeOf(r) && owner && power,
    can_rerun: (r.status === "FAILED" || r.status === "CANCELED") && power,
    hpc_mode: r.hpc_mode,
  };
}

export function mediaOf(srv: MockServer, r: FemRec): FemMedia {
  const side = (ids: [string, string | null], view: string) => ({ image: mediaFile(srv, ids[0]), video: ids[1] ? mediaFile(srv, ids[1], view, true) : null, video_error: ids[1] ? null : "파일이 만들어지지 않았습니다(HyperView 성공 보고)" });
  return {
    status: r.status === "DONE" ? "OK" : "NONE",
    display: srv.paramSets.find((x) => x.id === r.param_set_id)?.display ?? null,
    legend: r.compare?.legend ?? null,
    items: r.media.map((m) => ({ view: m.view, label: viewLabel(m.view), pred: side(m.pred, m.view), fem: side(m.fem, m.view) })),
  };
}

export function curvesOf(r: FemRec, name: string | null) {
  const c = curveJson(r.applied_values);
  const names = c.series.map((x) => x.name);
  const pick = name && names.includes(name) ? name : names[0];
  const s = c.series.find((x) => x.name === pick)!;
  return {
    names, name: pick, downsampled: false,
    pred: { x: s.x, y: s.y },
    fem: { x: s.x, y: s.y.map((v, i) => Number((v * (1.06 + 0.02 * Math.sin(i / 5)) + 0.01).toFixed(4))) },
  };
}

export function csvOf(r: FemRec): string {
  const head = "name,unit,stat,pred_min,pred_max,fem_min,fem_max,pred_value,fem_value,diff,diff_pct";
  const lines = (r.compare?.responses ?? []).map((x) => [x.name, x.unit ?? "", x.stat, x.pred_min, x.pred_max, x.fem_min, x.fem_max, x.pred_value, x.fem_value, x.diff, x.diff_pct].join(","));
  return "﻿" + [head, ...lines].join("\n") + "\n";
}

export function cancelJob(srv: MockServer, j: Job | null) {
  if (!j || TERMINAL.includes(j.state)) return;
  if (j.state === "QUEUED") {
    j.state = "CANCELED";
    j.finished_at = new Date().toISOString();
    srv.queueOrder.delete(j.id);
  } else j.cancel_requested = true;
  srv.bump(j);
}

export function rerun(srv: MockServer, r: FemRec, by: { id: string; name: string }): MockResp {
  const s = srv.studies.find((x) => x.id === r.study_id)!;
  const pj = latest(srv, r.predict_job_id);
  if (r.companion && pj && pj.state !== "SUCCEEDED") {
    const nj = newJob(srv, s, "PREDICT", { ...pj.params }, by, pj.id);
    r.predict_job_id = nj.id;
    r.status = "WAITING_PREDICT";
  } else {
    const fj = latest(srv, r.job_id);
    const failedIdx = fj?.steps.findIndex((x) => x.state === "FAILED") ?? -1;
    if (failedIdx < 0 || failedIdx <= 5) r.attempt_no++;
    r.job_id = newJob(srv, s, "FEM_VERIFY", { fem_verify_id: r.id, fv_no: r.fv_no, hpc: null }, by, fj?.id ?? null).id;
    r.status = "RUNNING";
  }
  r.failure = null;
  r.finished_at = null;
  return { status: 201, body: detailOf(srv, r) };
}
