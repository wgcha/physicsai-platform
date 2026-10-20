// S16 V2 목(phase3 §21.3, R-F 분할): 상태 동기화(종료 훅 흉내)·해석값 비교(buildCompare)·미디어·완료 처리.
import type { Job } from "../api/types";
import type { FemCompare } from "../api/femVerify";
import { curveJson, responseFn } from "./data";
import { contourPng } from "./png";
import type { MockServer } from "./server";
import { DEFAULT_VIEWS } from "../lib/views";
import { fvLabel, latest, newJob } from "./femVerifyRec";
import type { FemRec } from "./femVerifyRec";
import { activeOf } from "./femVerifyCreate";

// ------------------------------------------------------------------ 상태 동기화(종료 훅 흉내)
export function syncFem(srv: MockServer) {
  for (const r of srv.fems) {
    const s = srv.studies.find((x) => x.id === r.study_id);
    if (!s || !activeOf(r)) continue;
    const by = { id: r.created_by, name: r.created_by_name };
    if (r.status === "WAITING_PREDICT") {
      const pj = latest(srv, r.predict_job_id);
      if (!pj) continue;
      r.predict_job_id = pj.id;
      if (pj.state === "SUCCEEDED") {
        r.job_id = newJob(srv, s, "FEM_VERIFY", { fem_verify_id: r.id, fv_no: r.fv_no, hpc: null }, by).id;
        r.status = "RUNNING";
      } else if (pj.state === "FAILED" || pj.state === "INTERRUPTED") fail(r, "PREDICT_FAILED", "함께 실행한 예측이 실패했습니다");
      else if (pj.state === "CANCELED") r.status = "CANCELED";
      continue;
    }
    const fj = latest(srv, r.job_id);
    if (!fj) continue;
    r.job_id = fj.id;
    if (fj.state === "SUCCEEDED") done(srv, r, fj);
    else if (fj.state === "FAILED" || fj.state === "INTERRUPTED") fail(r, fj.failure_code ?? "EXIT_NONZERO", fj.failure_message ?? "FEM 검증 작업이 실패했습니다");
    else if (fj.state === "CANCELED") r.status = "CANCELED";
    if (!activeOf(r)) r.finished_at ??= new Date().toISOString();
  }
}

function fail(r: FemRec, code: string, message: string) {
  r.status = "FAILED";
  r.failure = { code, message };
  r.finished_at = new Date().toISOString();
}

const FEM_FACTOR: Record<string, number> = { MaxStress: 1.072, MaxDisp: 0.968, Energy: 1.031 };

/** 비교 결과(수치만) 만들기 — 응답 정의가 있는 것만(spec 없는 응답은 비교 안 함) */
export function buildCompare(srv: MockServer, r: FemRec): FemCompare {
  const ps = srv.paramSets.find((x) => x.id === r.param_set_id) ?? srv.paramSets[0];
  const base = responseFn(r.applied_values);
  const rows = ps.responses
    .filter((x) => x.spec)
    .map((x) => {
      const pv = base[x.name];
      const fv = pv * (FEM_FACTOR[x.name] ?? 1.05);
      const diff = pv - fv;
      return {
        name: x.name, unit: x.unit, stat: x.spec?.stat ?? "MAX", pred_min: Number((pv * 0.012).toPrecision(5)), pred_max: Number(pv.toPrecision(5)), fem_min: Number((fv * 0.009).toPrecision(5)), fem_max: Number(fv.toPrecision(5)),
        pred_value: Number(pv.toPrecision(5)), fem_value: Number(fv.toPrecision(5)), diff: Number(diff.toPrecision(4)), diff_pct: Number(((diff / Math.abs(fv)) * 100).toFixed(2)), note: null as string | null,
      };
    });
  const worst = rows.reduce<(typeof rows)[number] | null>((a, b) => (!a || Math.abs(b.diff_pct ?? 0) > Math.abs(a.diff_pct ?? 0) ? b : a), null);
  const maxS = base.MaxStress;
  return {
    responses: rows,
    max_abs_diff_pct: worst ? Math.abs(worst.diff_pct ?? 0) : null,
    worst: worst?.name ?? null,
    legend: { mode: "fixed", min: 0, max: Number((maxS * 1.05).toFixed(1)), source: "minmax", note: null },
    curve: { status: "OK", message: null, names: curveJson(r.applied_values).series.map((x) => x.name), unmatched_pred: [], unmatched_fem: ["Node 30001 변위 [mm]"] },
    media: { pred_status: "OK", fem_status: "OK" },
  };
}

export function makeMedia(srv: MockServer, r: FemRec, job: Job) {
  const ps = srv.paramSets.find((x) => x.id === r.param_set_id);
  const views = ps?.display?.views?.length ? ps.display.views : DEFAULT_VIEWS;
  r.media = views.map((view) => {
    const mk = (side: "pred" | "fem", k: number): [string, string | null] => [
      srv.addPngArtifact(job.id, job.study_id, "CONTOUR_IMAGE", `04_verify/${fvLabel(r.fv_no)}/a1/media/${side}/${view}.png`, () => contourPng(view, r.applied_values, k)),
      srv.addPngArtifact(job.id, job.study_id, "CONTOUR_VIDEO", `04_verify/${fvLabel(r.fv_no)}/a1/media/${side}/${view}_anim.png`, () => contourPng(view, r.applied_values, k * 0.7)),
    ];
    return { view, pred: mk("pred", 1), fem: mk("fem", 1.08) };
  });
}

function done(srv: MockServer, r: FemRec, job: Job) {
  r.status = "DONE";
  r.compare = buildCompare(srv, r);
  makeMedia(srv, r, job);
  r.finished_at = new Date().toISOString();
  if (!r.notified) {
    r.notified = true;
    const c = r.compare;
    const msg = c.worst ? `FEM 검증 ${fvLabel(r.fv_no)} 완료 — 최대 오차 ${c.max_abs_diff_pct}% (${c.worst})` : `FEM 검증 ${fvLabel(r.fv_no)} 완료 — 응답 비교 없음`;
    srv.notify(r.created_by, "FEM_VERIFY_DONE", job, msg);
  }
}
