// 계약 §10을 흉내 내는 메모리 목 서버. fetch를 가로채 /physicsai/api/* 에 응답한다.
import type {
  Artifact,
  Dataset,
  FeatureKey,
  Job,
  JobSummary,
  JobType,
  Me,
  Model,
  NotificationItem,
  ParamSet,
  PredictCheck,
  SampleRow,
  Study,
  StudyDetail,
} from "../api/types";
import {
  COMMANDS_TXT,
  PREVIEW_JSON,
  PROJECTS,
  STEP_CHAINS,
  SKIPPED_BY_DEFAULT,
  STEP_LABEL,
  USERS,
  baseJob,
  contourSvg,
  curveJson,
  curveStats,
  iso,
  lossCurve,
  makeSamples,
  makeSteps,
  responseFn,
  seedDatasets,
  seedModels,
  seedNotifications,
  seedParamSet,
  seedStudies,
  type MockUserKey,
} from "./data";
import { Phase2Mock } from "./phase2";
import { JOB_TYPE_LABEL } from "../lib/format";

type Notif = NotificationItem & { user_id: string };
interface ArtifactRec extends Artifact {
  body: string;
}
export interface MockResp {
  status: number;
  body?: unknown;
  text?: string;
  contentType?: string;
  headers?: Record<string, string>;
}

export interface MockOptions {
  user?: MockUserKey;
  hpcConfigured?: boolean;
  /** 실행 중 작업이 tick마다 진행되는 정도(%) */
  speed?: number;
  /** /status.ui 값(B1). 시험에서 짧은 주기를 주입 */
  ui?: Record<string, number>;
  /** 2차: 비활성 기능(/status.features enabled=false). 기본 ["train_resp"](response_extract 템플릿 null) */
  disabledFeatures?: FeatureKey[];
  /** C18: PBS 취소 명령 실패 흉내 */
  hpcCancelFails?: boolean;
  /** /status.demo(시연 모드) */
  demo?: boolean;
}

export const MOCK_AI_ROOT = "E:\\shared\\AI_WORK";
export const DEFAULT_UI = {
  max_artifact_bytes: 20971520,
  poll_job_running_ms: 2000,
  poll_job_queued_ms: 5000,
  poll_job_waiting_hpc_ms: 15000,
  poll_log_ms: 2000,
  poll_queue_ms: 5000,
  poll_resources_ms: 10000,
  poll_notifications_ms: 10000,
  poll_status_ms: 30000,
};

const JOB_LABEL = JOB_TYPE_LABEL;

const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResp => ({
  status,
  body: { detail: { code, message, ...extra } },
});

export class MockServer {
  user: MockUserKey;
  hpcConfigured: boolean;
  hpcCancelFails: boolean;
  demo: boolean;
  ui: Record<string, number>;
  speed: number;
  studies: Study[] = seedStudies();
  datasets: Dataset[] = seedDatasets();
  models: Model[] = seedModels();
  paramSets: ParamSet[] = [seedParamSet()];
  samples: Record<string, SampleRow[]> = { "ps-1": makeSamples(120) };
  jobs: Job[] = [];
  artifacts: ArtifactRec[] = [];
  notifs: Notif[] = seedNotifications() as Notif[];
  seq = 0;
  queueSeq = 100;
  queueOrder = new Map<string, number>();
  idn = 1000;
  p2: Phase2Mock;

  constructor(opts: MockOptions = {}) {
    this.user = opts.user ?? "admin";
    this.hpcConfigured = opts.hpcConfigured ?? false;
    this.hpcCancelFails = opts.hpcCancelFails ?? false;
    this.demo = opts.demo ?? false;
    this.speed = opts.speed ?? 9;
    this.ui = { ...DEFAULT_UI, ...(opts.ui ?? {}) };
    this.seq = Math.max(...this.notifs.map((n) => n.seq));
    this.seedJobs();
    this.p2 = new Phase2Mock(this, opts.disabledFeatures);
  }

  get me(): Me | null {
    return this.user === "anon" ? null : USERS[this.user];
  }

  nid(prefix: string) {
    return `${prefix}-${++this.idn}`;
  }

  private seedJobs() {
    const st = "쿠션 두께·리브 예측";
    const pred = baseJob({
      id: "j-pred", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "PREDICT", state: "SUCCEEDED",
      created_at: iso(34), started_at: iso(33), finished_at: iso(30), steps: makeSteps("PREDICT", 10, null), progress_pct: 100,
      params: { param_set_id: "ps-1", model_id: null, values: { THK_TOP: 0.55, THK_FOAM: 2.2, E_FOAM: 9.5, RIB_N: 5 }, value_source: "manual", source_run_key: null },
    });
    pred.result = this.predictResult(pred, pred.params.values as Record<string, number>, "m-1", "ps-1");
    this.jobs.push(
      baseJob({ id: "j-ds1", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "DATASET_CREATE", state: "FAILED", created_at: iso(60 * 30), finished_at: iso(60 * 30 - 4), steps: makeSteps("DATASET_CREATE", 2, null, { failedIdx: 2 }), failure_code: "EXIT_NONZERO", failure_message: "EDSPY_DATASET_TRAIN 종료코드 1", params: { input_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/h3d" } }),
      baseJob({ id: "j-ds2", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "DATASET_CREATE", state: "SUCCEEDED", created_at: iso(60 * 26 + 30), finished_at: iso(60 * 26), steps: makeSteps("DATASET_CREATE", 5, null), progress_pct: 100, params: { input_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/h3d_r2" }, result: { dataset_id: "ds-2", h3d_count: 240, train_count: 216, eval_count: 24 } }),
      baseJob({ id: "j-pkg", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "PACKAGE_EXPORT", state: "SUCCEEDED", created_at: iso(60 * 25 + 5), finished_at: iso(60 * 25), steps: makeSteps("PACKAGE_EXPORT", 2, null), progress_pct: 100, params: { dataset_id: "ds-2" } }),
      baseJob({ id: "j-mr", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "MODEL_REGISTER", state: "SUCCEEDED", created_at: iso(52), finished_at: iso(50), steps: makeSteps("MODEL_REGISTER", 4, null), progress_pct: 100, params: { model_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/model_gnn" }, result: { model_id: "m-3" } }),
      pred,
      baseJob({ id: "j-run", study_id: "s-hinge", project_id: "p-hinge", study_title: "힌지 반복 굽힘", job_type: "DATASET_CREATE", state: "RUNNING", lane: "SLOT", created_by: "u-other", created_by_name: "최해석", created_at: iso(30), started_at: iso(24), progress_pct: 62, progress_label: "Extracting results 148/240", steps: makeSteps("DATASET_CREATE", 2, 2) }),
      baseJob({ id: "j-q1", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "EVALUATE", state: "QUEUED", created_at: iso(12), params: { model_id: "m-2" } }),
      baseJob({ id: "j-q2", study_id: "s-hinge", project_id: "p-hinge", study_title: "힌지 반복 굽힘", job_type: "PREDICT", state: "QUEUED", created_by: "u-other", created_by_name: "최해석", created_at: iso(6) }),
    );
    (this.jobs.find((j) => j.id === "j-run") as Job & { _speed?: number })._speed = 1;
    this.queueOrder.set("j-q1", ++this.queueSeq);
    this.queueOrder.set("j-q2", ++this.queueSeq);
    this.addArtifact("j-pkg", "s-cushion", "PACKAGE_COMMANDS", "03_package/ds-2/COMMANDS.txt", "text/plain", COMMANDS_TXT);
    this.models.find((m) => m.id === "m-2")!.eval_status = "DONE";
  }

  addArtifact(jobId: string, studyId: string, kind: Artifact["kind"], rel: string, ct: string, body: string): string {
    const id = this.nid("a");
    this.artifacts.push({ id, study_id: studyId, job_id: jobId, kind, file_name: rel.split("/").pop()!, size: body.length, sha256: null, content_type: ct, created_at: new Date().toISOString(), body });
    return id;
  }

  private predictResult(job: Job, values: Record<string, number>, modelId: string, psId: string) {
    const ps = this.paramSets.find((p) => p.id === psId)!;
    const chk = this.check(ps, values);
    const pred = responseFn({ ...values, RIB_N: Math.round(values.RIB_N ?? 4) });
    const img = this.addArtifact(job.id, job.study_id, "PREVIEW_IMAGE", `04_predict/${job.id}/contour.png`, "image/svg+xml", contourSvg(values));
    const pj = this.addArtifact(job.id, job.study_id, "PREVIEW_JSON", `04_predict/${job.id}/H3D_PREVIEW.json`, "application/json", JSON.stringify(PREVIEW_JSON));
    const cj = this.addArtifact(job.id, job.study_id, "CURVE_JSON", `04_predict/${job.id}/curve.json`, "application/json", JSON.stringify(curveJson(values)));
    const applied = { ...values };
    for (const r of chk.rounded) applied[r.name] = r.applied;
    return {
      model_id: modelId,
      param_set_id: psId,
      values,
      applied_values: applied,
      out_of_range: chk.out_of_range.map((o) => o.name),
      nearest: chk.nearest ? { run_key: chk.nearest.run_key, distance: chk.nearest.distance } : null,
      preview_json_artifact_id: pj,
      image_artifact_ids: [img],
      curve_artifact_id: cj,
      response_table_artifact_id: null as string | null,
      response_table: ps.responses.map((r) => {
        const p = pred[r.name] ?? null;
        const m = chk.nearest?.measured?.[r.name] ?? null;
        return { name: r.name, unit: r.unit, predicted: p, nearest_measured: m, diff_pct: p != null && m ? ((p - m) / m) * 100 : null };
      }),
    };
  }

  check(ps: ParamSet, values: Record<string, number>): PredictCheck {
    const out_of_range = ps.parameters.filter((p) => values[p.name] < p.min || values[p.name] > p.max).map((p) => ({ name: p.name, value: values[p.name], min: p.min, max: p.max }));
    const ints = ps.tpl_params.filter((t) => /^%[-0-9.]*[id]$/.test(t.format)).map((t) => t.name);
    const rounded = ints.filter((n) => Number.isFinite(values[n])).map((n) => ({ name: n, value: values[n], applied: Math.floor(values[n] + 0.5) }));
    const rows = this.samples[ps.id] ?? [];
    let best: { row: SampleRow; d: number } | null = null;
    for (const row of rows) {
      let s = 0;
      for (const p of ps.parameters) {
        if (p.max === p.min) continue;
        s += ((values[p.name] - row.values[p.name]) / (p.max - p.min)) ** 2;
      }
      const d = Math.sqrt(s);
      if (!best || d < best.d || (d === best.d && row.run_key < best.row.run_key)) best = { row, d };
    }
    return {
      out_of_range,
      rounded,
      nearest: best ? { run_key: best.row.run_key, distance: best.d, values: best.row.values, measured: ps.sample_has_measured ? best.row.measured : null } : null,
    };
  }

  // ---------- 알림 ----------
  notify(userId: string, event: NotificationItem["event"], job: Job | null, title: string, body = "") {
    this.notifs.push({
      seq: ++this.seq, user_id: userId, event, job_id: job?.id ?? null, study_id: job?.study_id ?? null, project_id: job?.project_id ?? null,
      title, body, created_at: new Date().toISOString(), read_at: null,
    });
  }

  notifyJob(job: Job, event: NotificationItem["event"]) {
    const t = `${JOB_LABEL[job.job_type]} (${job.study_title})`;
    const title =
      event === "JOB_STARTED" ? `실행 시작: ${t}` :
      event === "JOB_SUCCEEDED" ? `완료: ${t}` :
      event === "JOB_FAILED" ? `실패: ${t} — ${job.failure_code}` :
      event === "JOB_CANCELED" ? "관리자가 작업을 취소했습니다" :
      event === "MY_TURN_NEXT" ? `다음 차례입니다: ${t}` : t;
    this.notify(job.created_by, event, job, title, event === "JOB_CANCELED" ? t : "");
  }

  // ---------- 대기열 ----------
  private queued(lane: "SLOT" | "LIGHT") {
    return this.jobs
      .filter((j) => j.state === "QUEUED" && j.lane === lane)
      .sort((a, b) => (this.queueOrder.get(a.id) ?? 0) - (this.queueOrder.get(b.id) ?? 0));
  }

  private refreshPositions() {
    for (const lane of ["SLOT", "LIGHT"] as const) this.queued(lane).forEach((j, i) => (j.queue_position = i + 1));
    for (const j of this.jobs) if (j.state !== "QUEUED") j.queue_position = null;
  }

  bump(j: Job) {
    j.version++;
  }

  /** 시간 1단계 진행: claim → 진행 → 완료 */
  tick() {
    for (const j of this.jobs.filter((x) => x.state === "RUNNING")) {
      if (j.cancel_requested) {
        j.state = "CANCELED";
        j.finished_at = new Date().toISOString();
        j.steps.forEach((s) => s.state === "RUNNING" && (s.state = "CANCELED"));
        this.bump(j);
        this.notifyJob(j, "JOB_CANCELED");
        continue;
      }
      const sp = (j as Job & { _speed?: number })._speed ?? (j.lane === "LIGHT" ? 50 : this.speed);
      const prev = (j as Job & { _pct?: number })._pct ?? j.progress_pct ?? 0;
      j.progress_pct = Math.min(100, prev + sp);
      (j as Job & { _pct?: number })._pct = j.progress_pct;
      const chain = STEP_CHAINS[j.job_type];
      const done = Math.min(chain.length, Math.floor(((j.progress_pct ?? 0) / 100) * chain.length));
      j.steps = makeSteps(j.job_type, done, done < chain.length ? done : null);
      const cur = chain[done];
      j.progress_label = cur ? `${cur.key} …` : null;
      this.p2.onProgress(j);
      if (((j as Job & { _pct?: number })._pct ?? 0) >= 100) this.finish(j);
      this.bump(j);
    }
    // claim
    for (const lane of ["SLOT", "LIGHT"] as const) {
      if (this.jobs.some((j) => j.state === "RUNNING" && j.lane === lane)) continue;
      const next = this.queued(lane)[0];
      if (!next) continue;
      next.state = "RUNNING";
      next.started_at = new Date().toISOString();
      next.progress_pct = 0;
      next.steps = makeSteps(next.job_type, 0, 0);
      this.queueOrder.delete(next.id);
      this.bump(next);
      this.notifyJob(next, "JOB_STARTED");
      if (next.job_type === "EVALUATE") {
        const m = this.models.find((x) => x.id === (next.params.model_id as string));
        if (m) m.eval_status = "RUNNING";
      }
      if (lane === "SLOT") {
        const first = this.queued("SLOT")[0] as (Job & { _notified?: boolean }) | undefined;
        if (first && !first._notified) {
          first._notified = true;
          this.notifyJob(first, "MY_TURN_NEXT");
        }
      }
    }
    this.p2.tick();
    this.refreshPositions();
  }

  /** 시험·데모용: 실행 중 작업을 바로 끝낸다 */
  finishAll() {
    for (let i = 0; i < 40 && this.jobs.some((j) => j.state === "RUNNING" || j.state === "QUEUED"); i++) {
      for (const j of this.jobs) if (j.state === "RUNNING") (j as Job & { _pct?: number })._pct = 100;
      this.tick();
    }
  }

  private finish(j: Job) {
    const r2 = this.p2.finish(j);
    if (r2 === "waiting") {
      j.state = "WAITING_HPC";
      j.progress_pct = null;
      return;
    }
    j.state = "SUCCEEDED";
    j.finished_at = new Date().toISOString();
    j.progress_pct = 100;
    j.progress_label = null;
    j.steps = makeSteps(j.job_type, STEP_CHAINS[j.job_type].length, null);
    const p = j.params as Record<string, unknown>;
    const now = new Date().toISOString();
    switch (j.job_type) {
      case "DATASET_CREATE": {
        const ds = this.datasets.find((d) => d.job_id === j.id);
        if (ds) Object.assign(ds, { status: "READY", h3d_count: 180, train_count: 162, eval_count: 18 });
        const cur = this.p2.curations.find((c) => c.id === p.curation_id);
        if (cur && ds) cur.used_by_dataset_ids.push(ds.id);
        j.result = { dataset_id: ds?.id, h3d_count: 180, train_count: 162, eval_count: 18 };
        break;
      }
      case "PACKAGE_EXPORT": {
        const ds = this.datasets.find((d) => d.id === p.dataset_id);
        if (ds) ds.package_ready = true;
        this.addArtifact(j.id, j.study_id, "PACKAGE_COMMANDS", `03_package/${p.dataset_id}/COMMANDS.txt`, "text/plain", COMMANDS_TXT);
        break;
      }
      case "MODEL_REGISTER": {
        const path = String(p.model_path);
        const name = String(p.name || path.split(/[\\/]/).pop() || "model");
        const ver = Math.max(0, ...this.models.filter((m) => m.study_id === j.study_id && m.name === name).map((m) => m.version)) + 1;
        const status = /nolog/i.test(path) ? "MISSING" : /raw|unknown/i.test(path) ? "UNRECOGNIZED" : "PARSED";
        const curve = status === "PARSED" ? lossCurve(this.idn, 1200, 0.7) : null;
        const ds = (p.dataset_id as string) || this.datasets.find((d) => d.study_id === j.study_id && d.status === "READY")?.id || null;
        const m: Model = {
          id: this.nid("m"), study_id: j.study_id, name, version: ver, label: (p.label as string) ?? null, dataset_id: ds, source_path: path,
          log_status: status, log_parser: status === "PARSED" ? "default" : null, epochs_total: curve ? 1200 : null, last_epoch: curve ? 1200 : null,
          ...(curve ? curveStats(curve) : { final_loss: null, min_loss: null, min_loss_epoch: null }),
          loss_curve: curve, curve_points: curve?.length ?? 0, eval_status: "NONE", eval_score: null, status: "ACTIVE", is_final: false,
          registered_by_name: j.created_by_name, registered_at: now, row_version: 1,
        };
        this.models.unshift(m);
        j.result = { model_id: m.id };
        break;
      }
      case "EVALUATE": {
        const m = this.models.find((x) => x.id === p.model_id);
        if (m) {
          m.eval_status = "DONE";
          m.eval_score = { status: "PARSED", metrics: { R2: 0.95 + (this.idn % 40) / 1000, MAE: 1.4 + (this.idn % 7) / 10 }, score_rel: "" };
          m.row_version++;
        }
        break;
      }
      case "PREDICT": {
        const ps = (p.param_set_id as string) || this.paramSets.find((x) => x.study_id === j.study_id && x.is_current)?.id || "ps-1";
        const study = this.studies.find((s) => s.id === j.study_id)!;
        const nominal = Object.fromEntries(this.paramSets.find((x) => x.id === ps)!.parameters.map((x) => [x.name, x.nominal]));
        j.result = this.predictResult(j, (p.values as Record<string, number>) ?? nominal, (p.model_id as string) || study.final_model_id || "m-1", ps);
        break;
      }
      case "PREDICT_VERIFY": {
        const pj = this.jobs.find((x) => x.id === p.predict_job_id);
        const vals = (pj?.params.values ?? {}) as Record<string, number>;
        const r = responseFn(vals);
        j.result = { verify_values: Object.fromEntries(Object.entries(r).map(([k, v]) => [k, Number((v * 1.02).toFixed(3))])) };
        break;
      }
    }
    this.notifyJob(j, "JOB_SUCCEEDED");
  }

  // ---------- 요약 변환 ----------
  private summary(j: Job): JobSummary {
    const { id, study_id, project_id, study_title, job_type, stage, lane, state, created_by, created_by_name, queue_position, progress_pct, progress_label, cancel_requested, created_at, started_at } = j;
    return { id, study_id, project_id, study_title, job_type, stage, lane, state, created_by, created_by_name, queue_position, progress_pct, progress_label, cancel_requested, created_at, started_at, ...this.p2.summaryExtra(j) };
  }

  stepLabel(key: string): string {
    return STEP_LABEL[key] ?? key;
  }

  /** phase2.md §6.13 F: ① 결과로 파라미터 세트 */
  addParamSetFromTrain(s: Study, doeId: string, sampleCount: number): ParamSet {
    const me = this.me!;
    this.paramSets.forEach((p) => p.study_id === s.id && (p.is_current = false));
    const base = seedParamSet();
    const ps: ParamSet = {
      ...base, id: this.nid("ps"), study_id: s.id, source_path: `① DOE ${doeId.slice(0, 8)}`, sample_count: sampleCount, sample_has_measured: false,
      parameters: base.parameters.filter((p) => p.name !== "E_FOAM"), origin: "TRAIN_DOE", train_doe_id: doeId,
      registered_by_name: me.display_name, registered_at: new Date().toISOString(),
    };
    this.samples[ps.id] = (this.p2.doeSamples[doeId] ?? []).slice(0, sampleCount);
    this.paramSets.unshift(ps);
    return ps;
  }

  role(projectId: string) {
    const me = this.me!;
    if (me.is_global_admin) return "admin";
    return me.roles[projectId] ?? null;
  }

  disp(studyId: string, rel: string): string {
    const st = this.studies.find((x) => x.id === studyId);
    return [MOCK_AI_ROOT, st?.folder_name ?? studyId, ...rel.split("/").filter(Boolean)].join("\\");
  }

  private studyOut(s: Study): Study {
    const r = this.role(s.project_id);
    return { ...s, can_execute: r === "power" || r === "admin", folder_display_path: this.disp(s.id, "") };
  }

  private studyDetail(s: Study): StudyDetail {
    const latest = (stage: number) => {
      const j = this.jobs.filter((x) => x.study_id === s.id && x.stage === stage).sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
      return { latest_job_id: j?.id ?? null, latest_job_type: j?.job_type ?? null, latest_state: j?.state ?? null };
    };
    const final = this.models.find((m) => m.id === s.final_model_id) ?? null;
    return {
      ...this.studyOut(s),
      final_model: final ? this.modelOut(final, false) : null,
      stage_status: { "1": latest(1), "2": latest(2), "3": latest(3), "4": latest(4), "5": latest(5) },
      current_param_set_id: this.paramSets.find((p) => p.study_id === s.id && p.is_current)?.id ?? null,
    };
  }

  private datasetOut(d: Dataset): Dataset {
    return {
      ...d,
      dataset_display_path: this.disp(d.study_id, `03_dataset/${d.id}`),
      package_rel: d.package_ready ? `03_package/${d.id}/` : null,
      package_display_path: d.package_ready ? this.disp(d.study_id, `03_package/${d.id}`) : null,
    };
  }

  private modelOut(m: Model, withCurve: boolean): Model {
    const study = this.studies.find((s) => s.id === m.study_id);
    const out = { ...m, is_final: study?.final_model_id === m.id, stored_display_path: this.disp(m.study_id, `03_model/models/${m.id}`) };
    if (!withCurve) delete out.loss_curve;
    return out;
  }

  private inputReady(j: Job): boolean {
    return j.job_type === "PREDICT" && j.steps.some((x) => x.step_key === "RAD_ASSEMBLE" && (x.state === "SUCCEEDED" || x.state === "SKIPPED"));
  }

  private jobOut(j: Job): Job {
    const me = this.me;
    const failedish = ["FAILED", "CANCELED", "INTERRUPTED"].includes(j.state) || !!j.attention_code;
    return {
      ...j,
      ...this.p2.summaryExtra(j),
      attention_code: j.attention_code ?? null,
      input_display_path: this.inputReady(j) ? this.disp(j.study_id, `04_predict/${j.id}/INPUT`) : null,
      can_download_error_bundle: !!me && failedish && (me.is_global_admin || j.created_by === me.user_id),
    };
  }

  // ---------- 라우팅 ----------
  handle(method: string, path: string, query: URLSearchParams, body: Record<string, unknown> | null, headers: Headers): MockResp {
    if (path === "/health") return { status: 200, body: { status: "ok", version: "mock" } };
    const me = this.me;
    if (!me) return err(401, "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.");
    if (method !== "GET" && headers.get("X-PhysicsAI-Request") !== "1") return err(403, "CSRF_HEADER_REQUIRED", "요청 헤더가 없습니다.");
    const seg = path.split("/").filter(Boolean);
    const needPower = (projectId: string) => {
      const r = this.role(projectId);
      return r === "power" || r === "admin" ? null : err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
    };
    const needAdmin = () => (me.is_global_admin ? null : err(403, "PERMISSION_DENIED", "전역 관리자만 할 수 있습니다.", { required: "global_admin" }));

    // §10.2
    if (method === "GET" && path === "/me") return { status: 200, body: me };
    if (method === "GET" && path === "/projects") return { status: 200, body: PROJECTS };
    if (method === "GET" && path === "/status")
      return {
        status: 200,
        body: {
          config: { ok: true, errors: [] },
          worker: { online: true, worker_id: "PHYSICS-PC:4412:mock", last_seen_at: new Date().toISOString(), limiter: "windows_job" },
          hpc: this.hpcConfigured ? { mode: "command", configured: true, message: "PBS command 모드", collect_mode: "in_place" } : { mode: "none", configured: false, message: "PBS 연결 안 됨", collect_mode: "in_place" },
          altair: [{ key: "edspy_path", ok: true }, { key: "simlab_path", ok: true }, { key: "hw_exe_path", ok: true }],
          templates: [{ key: "geom_update", configured: true }, { key: "mesh", configured: false }, { key: "response_extract", configured: false }],
          limits: { configured: {}, detected: {}, effective: {} },
          ui: this.ui,
          auth: { mode: "dashboard", login_url: "/" },
          demo: this.demo,
          ...this.p2.status(me.is_global_admin),
        },
      };
    if (method === "GET" && path === "/queue") {
      this.refreshPositions();
      const running = this.jobs.find((j) => j.state === "RUNNING" && j.lane === "SLOT") ?? null;
      const lightRun = this.jobs.find((j) => j.state === "RUNNING" && j.lane === "LIGHT") ?? null;
      return {
        status: 200,
        body: {
          slot: { holder_job_id: running?.id ?? null, since: running?.started_at ?? null },
          running: running ? this.summary(running) : null,
          queued: this.queued("SLOT").map((j) => this.summary(j)),
          light: { running: lightRun ? this.summary(lightRun) : null, queued: this.queued("LIGHT").map((j) => this.summary(j)) },
          waiting_hpc: this.jobs.filter((j) => j.state === "WAITING_HPC").map((j) => this.summary(j)),
          collecting: this.jobs.filter((j) => j.state === "COLLECTING").map((j) => this.summary(j)),
        },
      };
    }
    if (method === "POST" && seg[0] === "queue" && seg[2] === "move") {
      const d = needAdmin();
      if (d) return d;
      const list = this.queued("SLOT");
      const idx = list.findIndex((j) => j.id === seg[1]);
      if (idx < 0) return err(409, "JOB_NOT_QUEUED", "대기 중인 작업이 아닙니다.");
      const pos = Number(body?.position);
      if (!Number.isInteger(pos) || pos < 1) return err(422, "INVALID_PARAMS", "position은 1 이상입니다.");
      const [j] = list.splice(idx, 1);
      list.splice(Math.min(pos - 1, list.length), 0, j);
      list.forEach((x) => this.queueOrder.set(x.id, ++this.queueSeq));
      this.refreshPositions();
      return this.handle("GET", "/queue", query, null, headers);
    }
    if (method === "GET" && path === "/resources") {
      const t = Date.now() / 1000;
      return {
        status: 200,
        body: {
          sampled_at: new Date().toISOString(),
          cpu_pct: 46 + 18 * Math.sin(t / 17),
          ram_used_gb: 41.5 + 6 * Math.sin(t / 23),
          ram_total_gb: 128,
          gpu: [{ name: "NVIDIA RTX A6000", util_pct: 71 + 12 * Math.sin(t / 11), mem_used_mb: 30720, mem_total_mb: 49152 }],
          job: { job_id: "j-run", cpu_time_s: 5520, peak_memory_gb: 22.4 },
          limits: { cores: 32, cpu_rate: 5000, memory_gb: 64, priority: "below_normal", cpu_cap_enforced: true },
        },
      };
    }

    // 2차(phase2.md §12)
    const r2 = this.p2.handle(method, path, query, body);
    if (r2) return r2;

    // §10.3
    if (method === "GET" && path === "/studies") {
      const pid = query.get("project_id");
      const st = query.get("status");
      return { status: 200, body: this.studies.filter((s) => (!pid || s.project_id === pid) && (!st || s.status === st)).map((s) => this.studyOut(s)) };
    }
    if (method === "POST" && path === "/studies") {
      const pid = String(body?.project_id ?? "");
      if (!PROJECTS.some((p) => p.id === pid)) return err(404, "PROJECT_NOT_FOUND", "프로젝트를 찾을 수 없습니다.");
      const d = needPower(pid);
      if (d) return d;
      const folder = String(body?.folder_name ?? "");
      if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(folder)) return err(422, "INVALID_PARAMS", "폴더 이름 형식이 올바르지 않습니다.");
      if (this.studies.some((s) => s.folder_name === folder)) return err(409, "STUDY_NAME_EXISTS", "같은 폴더 이름의 Study가 있습니다.");
      const s: Study = {
        id: this.nid("s"), project_id: pid, folder_name: folder, title: String(body?.title ?? folder), status: "ACTIVE", final_model_id: null,
        created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), version: 1, can_execute: true,
      };
      this.studies.unshift(s);
      return { status: 201, body: this.studyOut(s) };
    }
    if (seg[0] === "studies" && seg[1]) {
      const s = this.studies.find((x) => x.id === seg[1]);
      if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
      const sub = seg[2];
      if (method === "GET" && !sub) return { status: 200, body: this.studyDetail(s) };
      if (method === "GET" && sub === "datasets") return { status: 200, body: this.datasets.filter((d) => d.study_id === s.id).map((d) => this.datasetOut(d)) };
      if (method === "GET" && sub === "models") return { status: 200, body: this.models.filter((m) => m.study_id === s.id).map((m) => this.modelOut(m, false)) };
      if (method === "GET" && sub === "param-sets") return { status: 200, body: this.paramSets.filter((p) => p.study_id === s.id) };
      if (method === "POST" && sub === "predict" && seg[3] === "check") {
        const ps = this.paramSets.find((p) => p.id === (body?.param_set_id || "") || (p.study_id === s.id && p.is_current && !body?.param_set_id));
        if (!ps) return err(404, "NOT_FOUND", "파라미터 세트가 없습니다.");
        return { status: 200, body: this.check(ps, (body?.values ?? {}) as Record<string, number>) };
      }
      const d = needPower(s.project_id);
      if (d) return d;
      if (method === "PUT" && sub === "final-model") {
        const id = body?.model_id as string | null;
        if (id) {
          const m = this.models.find((x) => x.id === id && x.study_id === s.id);
          if (!m) return err(404, "NOT_FOUND", "모델을 찾을 수 없습니다.");
          if (m.status !== "ACTIVE") return err(409, "MODEL_NOT_ACTIVE", "사용 가능한 모델이 아닙니다.");
        }
        s.final_model_id = id;
        s.version++;
        return { status: 200, body: this.studyOut(s) };
      }
      if (method === "POST" && sub === "paths" && seg[3] === "inspect")
        return this.p2.inspect(String(body?.purpose), String(body?.path ?? ""), body?.doe_id as string | undefined) ?? this.inspect(String(body?.purpose), String(body?.path ?? ""));
      if (method === "POST" && sub === "param-sets") {
        const r = this.inspect("PARAM_SET", String(body?.path ?? ""));
        if (r.status !== 200) return r;
        this.paramSets.forEach((p) => p.study_id === s.id && (p.is_current = false));
        const ps: ParamSet = { ...seedParamSet(), id: this.nid("ps"), study_id: s.id, source_path: String(body?.path), registered_by_name: me.display_name, registered_at: new Date().toISOString() };
        this.samples[ps.id] = this.samples["ps-1"];
        this.paramSets.unshift(ps);
        return { status: 201, body: ps };
      }
      if (method === "POST" && sub === "jobs") return this.createJob(s, String(body?.job_type) as JobType, (body?.params ?? {}) as Record<string, unknown>);
    }

    // §10.4
    if (method === "GET" && seg[0] === "models" && seg[1]) {
      const m = this.models.find((x) => x.id === seg[1]);
      return m ? { status: 200, body: this.modelOut(m, true) } : err(404, "NOT_FOUND", "모델을 찾을 수 없습니다.");
    }
    if (method === "GET" && seg[0] === "param-sets" && seg[1]) {
      const ps = this.paramSets.find((p) => p.id === seg[1]);
      if (!ps) return err(404, "NOT_FOUND", "파라미터 세트를 찾을 수 없습니다.");
      if (seg[2] === "samples") {
        const rows = this.samples[ps.id] ?? [];
        const limit = Math.min(200, Number(query.get("limit") ?? 50));
        const start = Number(query.get("cursor") ?? 0);
        const next = start + limit < rows.length ? String(start + limit) : null;
        return { status: 200, body: { columns: ["run_key", ...ps.parameters.map((p) => p.name)], rows: rows.slice(start, start + limit), next_cursor: next } };
      }
      return { status: 200, body: ps };
    }

    // §10.5
    if (method === "GET" && path === "/jobs") {
      let list = [...this.jobs];
      const sid = query.get("study_id");
      const jt = query.get("job_type");
      const st = query.get("state");
      if (sid) list = list.filter((j) => j.study_id === sid);
      if (jt) list = list.filter((j) => j.job_type === jt);
      if (st) list = list.filter((j) => j.state === st);
      if (query.get("mine") === "true") list = list.filter((j) => j.created_by === me.user_id);
      list.sort((a, b) => b.created_at.localeCompare(a.created_at));
      return { status: 200, body: list.slice(0, Number(query.get("limit") ?? 50)).map((j) => this.summary(j)) };
    }
    if (seg[0] === "jobs" && seg[1]) {
      const j = this.jobs.find((x) => x.id === seg[1]);
      if (!j) return err(404, "NOT_FOUND", "작업을 찾을 수 없습니다.");
      if (method === "GET" && !seg[2]) {
        const etag = `"${j.id}:${j.version}:0"`;
        if (headers.get("If-None-Match") === etag) return { status: 304, headers: { ETag: etag } };
        const own = j.created_by === me.user_id;
        return {
          status: 200,
          headers: { ETag: etag },
          body: { ...this.jobOut(j), can_cancel: me.is_global_admin && !["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state), can_retry: (own || me.is_global_admin) && (j.state === "FAILED" || j.state === "INTERRUPTED") },
        };
      }
      if (method === "GET" && seg[2] === "error-bundle.zip") {
        if (!(me.is_global_admin || j.created_by === me.user_id)) return err(403, "PERMISSION_DENIED", "작업 등록자 또는 전역 관리자만 받을 수 있습니다.", { required: "owner_or_global_admin" });
        if (!(["FAILED", "CANCELED", "INTERRUPTED"].includes(j.state) || j.attention_code)) return err(409, "ERROR_BUNDLE_NOT_AVAILABLE", "실패·중단된 작업만 오류 묶음을 받을 수 있습니다.");
        return { status: 200, text: "PK\u0003\u0004 (mock error bundle)", contentType: "application/zip" };
      }
      if (method === "GET" && seg[2] === "log") return { status: 200, body: this.log(j, Number(query.get("cursor") ?? 0)) };
      if (method === "GET" && seg[2] === "artifacts" && seg[3] === "input.zip") {
        if (!this.inputReady(j)) return err(409, "INPUT_NOT_READY", "입력파일이 아직 준비되지 않았습니다.");
        return { status: 200, text: "PK\u0003\u0004 (mock zip)", contentType: "application/zip" };
      }
      if (method === "GET" && seg[2] === "artifacts") return { status: 200, body: this.artifacts.filter((a) => a.job_id === j.id).map(({ body: _b, ...a }) => a) };
      if (method === "POST" && seg[2] === "cancel") {
        const d = needAdmin();
        if (d) return d;
        if (["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state)) return err(409, "JOB_TERMINAL", "이미 끝난 작업입니다.");
        if (j.state === "QUEUED") {
          j.state = "CANCELED";
          j.finished_at = new Date().toISOString();
          this.queueOrder.delete(j.id);
          this.notifyJob(j, "JOB_CANCELED");
        } else j.cancel_requested = true;
        this.bump(j);
        this.refreshPositions();
        return { status: 202, body: j };
      }
    }
    if (method === "GET" && seg[0] === "artifacts" && seg[2] === "content") {
      const a = this.artifacts.find((x) => x.id === seg[1]);
      return a ? { status: 200, text: a.body, contentType: a.content_type } : err(404, "NOT_FOUND", "산출물을 찾을 수 없습니다.");
    }

    // §10.7
    if (seg[0] === "notifications") {
      const mine = this.notifs.filter((n) => n.user_id === me.user_id);
      const unread = () => this.notifs.filter((n) => n.user_id === me.user_id && !n.read_at).length;
      const maxSeq = Math.max(0, ...mine.map((n) => n.seq));
      if (method === "GET" && seg[1] === "unread-count") return { status: 200, body: { unread_count: unread(), max_seq: maxSeq } };
      if (method === "GET" && !seg[1]) {
        const after = query.get("after_seq");
        const limit = Number(query.get("limit") ?? 50);
        let items = [...mine].sort((a, b) => b.seq - a.seq);
        if (after !== null) items = items.filter((n) => n.seq > Number(after));
        return { status: 200, body: { items: items.slice(0, limit).map(({ user_id: _u, ...n }) => n), max_seq: maxSeq, unread_count: unread() } };
      }
      if (method === "POST" && seg[1] === "read") {
        const now = new Date().toISOString();
        if (body?.all) mine.forEach((n) => (n.read_at ??= now));
        else for (const s of (body?.seqs as number[]) ?? []) {
          const n = mine.find((x) => x.seq === s);
          if (n) n.read_at ??= now;
        }
        return { status: 200, body: { unread_count: unread() } };
      }
    }
    return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} ${path}`);
  }

  private inspect(purpose: string, path: string): MockResp {
    if (!path.trim()) return err(422, "PATH_NOT_FOUND", "경로를 입력하세요.");
    if (/\s|[&|<>^%!"]/.test(path)) return err(422, "PATH_UNSAFE", "경로에 공백이나 특수문자를 쓸 수 없습니다.");
    if (!/AI_WORK/i.test(path)) return err(422, "PATH_OUTSIDE_ROOT", "AI 루트 하위 경로만 지정할 수 있습니다.");
    const last = path.split(/[\\/]/).filter(Boolean).pop() ?? "model";
    if (purpose === "DATASET_INPUT")
      return { status: 200, body: { normalized_path: path, ok: true, problems: [], summary: { h3d_count: 180, sample_files: ["run_0001/cushion_0001.h3d", "run_0002/cushion_0002.h3d", "run_0003/cushion_0003.h3d"], expected_train: 162, expected_eval: 18 } } };
    if (purpose === "MODEL_FOLDER") {
      const logs = /nolog/i.test(path) ? [] : /multi/i.test(path) ? ["train.log", "train_retry.log"] : ["train.log"];
      return { status: 200, body: { normalized_path: path, ok: true, problems: [], summary: { psmdl: [`${last.replace(/[^A-Za-z0-9_]/g, "_")}.psmdl`], pscfg: ["settings.pscfg"], logs } } };
    }
    return { status: 200, body: { normalized_path: path, ok: true, problems: [], summary: { parameters: 4, samples: 120, responses: 3, cad: "cushion_base.x_t", starter: "cushion_0000.rad" } } };
  }

  private createJob(s: Study, type: JobType, params: Record<string, unknown>): MockResp {
    if (s.status !== "ACTIVE") return err(409, "STUDY_ARCHIVED", "보관된 Study입니다.");
    if (!STEP_CHAINS[type]) return err(422, "INVALID_PARAMS", "알 수 없는 작업 유형입니다.");
    if (this.jobs.some((j) => j.study_id === s.id && j.job_type === type && !["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state)))
      return err(409, "STUDY_JOB_BUSY", "같은 종류의 작업이 이미 실행 중이거나 대기 중입니다.");
    if (type === "PREDICT" && !params.model_id && !s.final_model_id) return err(409, "FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요.");
    if (type === "PREDICT_VERIFY" && !this.hpcConfigured) return err(409, "HPC_NOT_CONFIGURED", "PBS 연결이 설정되지 않았습니다.");
    const pre = this.p2.precheck(s, type, params);
    if (pre) return pre;
    if (type === "DATASET_CREATE" && params.curation_id && params.input_path) return err(422, "INVALID_PARAMS", "curation_id와 input_path는 함께 쓸 수 없습니다.");
    if (type === "PACKAGE_EXPORT" && !this.datasets.some((d) => d.id === params.dataset_id && d.status === "READY"))
      return err(409, "PREREQUISITE_MISSING", "준비된 데이터셋이 필요합니다.", { missing: ["dataset"] });
    const me = this.me!;
    const j = baseJob({
      id: this.nid("j"), study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: type, state: "QUEUED",
      created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), params,
    });
    this.jobs.push(j);
    this.queueOrder.set(j.id, ++this.queueSeq);
    this.p2.onCreate(j, me);
    if (type === "DATASET_CREATE") {
      const cur = this.p2.curations.find((c) => c.id === params.curation_id);
      this.datasets.unshift({
        id: this.nid("ds"), study_id: s.id, job_id: j.id, status: "BUILDING", source_path: cur ? cur.output_display_path ?? "" : String(params.input_path), curation_id: cur?.id ?? null, h3d_count: null, train_count: null, eval_count: null,
        holdout_ratio: 0.1, seed: Number(params.seed ?? 20261008), split_group: (params.split_group as "file") ?? "file",
        options: (params.options as Dataset["options"]) ?? { extract_faces: true, extract_mdi: false, extract_time_history_vectors: false },
        package_ready: false, created_by_name: me.display_name, created_at: j.created_at,
      });
    }
    this.refreshPositions();
    return { status: 201, body: j };
  }

  private log(j: Job, cursor: number) {
    const lines = j.steps
      .filter((s) => s.state !== "PENDING")
      .map((s) => `[${s.step_no.toString().padStart(2, "0")} ${s.step_key}] ${s.state}${SKIPPED_BY_DEFAULT.has(s.step_key) && s.state === "SKIPPED" ? " (템플릿 미구성)" : ""}`);
    const text = lines.join("\n") + (lines.length ? "\n" : "");
    const slice = text.slice(cursor);
    return { text: slice, next_cursor: text.length, eof: true, size: text.length };
  }
}

/** fetch 대체 함수 생성 */
export function createMockFetch(server: MockServer, realFetch?: typeof fetch): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://mock.local");
    const prefix = "/physicsai/api";
    if (!url.pathname.startsWith(prefix)) {
      if (realFetch) return realFetch(input, init);
      return new Response("not found", { status: 404 });
    }
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    let body: Record<string, unknown> | null = null;
    if (typeof init?.body === "string") body = JSON.parse(init.body);
    const r = server.handle(method, url.pathname.slice(prefix.length) || "/", url.searchParams, body, headers);
    const h = new Headers(r.headers);
    if (r.status === 304) return new Response(null, { status: 304, headers: h });
    if (r.text !== undefined) {
      h.set("Content-Type", r.contentType ?? "text/plain");
      return new Response(r.text, { status: r.status, headers: h });
    }
    h.set("Content-Type", "application/json");
    return new Response(JSON.stringify(r.body ?? null), { status: r.status, headers: h });
  };
}
