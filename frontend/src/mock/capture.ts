// S10 목: 예측 끝에 HyperView 배치로 방향별 PNG + 애니메이션 동영상 저장(흉내), GET /jobs/{id}/media, POST /jobs/{id}/capture(→ 202 CONTOUR_CAPTURE),
// PUT /param-sets/{id}/display. 동영상은 목에서 정적 PNG로 대체(video_type "image/png" — 화면은 <video poster>로 이미지가 보인다).
// MockOptions.capture로 상태를 고른다: OK(기본)·PARTIAL(right 실패·top 동영상 없음)·FAILED·DISABLED·NONE(캡처 전 결과, media 없음).
import type { ContourDisplay, Job, JobMedia, MediaStatus, ParamSet, ResultMedia, ViewKey } from "../api/types";
import { AVG_MODES, DEFAULT_VIEWS, VIEW_KEYS, viewLabel } from "../lib/views";
import { contourPng } from "./png";
import { err, needPower, ok, type Route } from "./route";
import type { MockServer } from "./server";

export type CaptureMode = MediaStatus | "NONE";

export const DEFAULT_DISPLAY: ContourDisplay = {
  field: "Stress",
  component: "vonMises",
  avgmode: "simple",
  comps: [],
  legend: { mode: "auto", min: null, max: null },
  views: [...DEFAULT_VIEWS],
};

const MESSAGE: Partial<Record<MediaStatus, string>> = {
  PARTIAL: "right 방향 캡처 시간 초과 · top 동영상 없음",
  FAILED: "HyperView 종료코드 3 — 작업 로그를 확인하세요",
  DISABLED: "관리자 설정에서 컨투어 캡처가 꺼져 있습니다(capture.enabled)",
};

/** 예측 결과 media 만들기. 상태는 srv.mediaInfo(작업별)에 둔다 */
export function captureMedia(srv: MockServer, job: Job, values: Record<string, number>, views?: ViewKey[] | null, mode: CaptureMode = srv.capture): ResultMedia[] | null {
  if (mode === "NONE") {
    srv.mediaInfo.delete(job.id);
    return null;
  }
  srv.mediaInfo.set(job.id, { status: mode, message: MESSAGE[mode] ?? null });
  if (mode === "FAILED" || mode === "DISABLED") return [];
  const ps = srv.paramSets.find((p) => p.id === (job.params as { param_set_id?: string }).param_set_id);
  let want = views?.length ? views : ps?.display?.views?.length ? ps.display.views : DEFAULT_VIEWS;
  if (mode === "PARTIAL") want = want.filter((v) => v !== "right");
  return want.map((view) => {
    const img = srv.addPngArtifact(job.id, job.study_id, "CONTOUR_IMAGE", `04_predict/${job.id}/media/contour_${view}.png`, () => contourPng(view, values));
    const noVideo = mode === "PARTIAL" && view === "top";
    // 목: 동영상(mp4) 대신 다른 프레임의 정적 PNG
    const vid = noVideo ? null : srv.addPngArtifact(job.id, job.study_id, "CONTOUR_VIDEO", `04_predict/${job.id}/media/contour_${view}_anim.png`, () => contourPng(view, values, 0.7));
    return { view, image_artifact_id: img, video_artifact_id: vid };
  });
}

const url = (id: string) => `/physicsai/api/artifacts/${id}/content`;

export function mediaOut(srv: MockServer, j: Job): JobMedia {
  const media = (j.result as { media?: ResultMedia[] | null } | null)?.media ?? [];
  const info = srv.mediaInfo.get(j.id);
  return {
    status: info?.status ?? "OK",
    message: info?.message ?? null,
    views: media.map((m) => ({
      view: m.view,
      label: viewLabel(m.view),
      image_url: url(m.image_artifact_id),
      video_url: m.video_artifact_id ? url(m.video_artifact_id) : null,
      video_type: m.video_artifact_id ? srv.artifacts.find((a) => a.id === m.video_artifact_id)?.content_type ?? null : null,
    })),
  };
}

/** 다시 캡처 작업 완료: 원래 예측 작업의 media 교체 */
export function finishCapture(srv: MockServer, j: Job) {
  const p = j.params as { predict_job_id: string; views?: ViewKey[] };
  const pj = srv.jobs.find((x) => x.id === p.predict_job_id);
  if (!pj?.result) return;
  const r = pj.result as { applied_values?: Record<string, number>; values?: Record<string, number>; media?: ResultMedia[] | null };
  r.media = captureMedia(srv, pj, r.applied_values ?? r.values ?? {}, p.views, "OK");
  srv.bump(pj);
  j.result = { predict_job_id: pj.id, views: (r.media ?? []).map((m) => m.view) };
}

function validDisplay(body: Record<string, unknown> | null): { display: ContourDisplay } | { problems: { code: string; message: string }[] } {
  const problems: { code: string; message: string }[] = [];
  const b = (body ?? {}) as Partial<ContourDisplay>;
  if (!String(b.field ?? "").trim()) problems.push({ code: "FIELD", message: "결과 종류가 필요합니다" });
  if (!AVG_MODES.some((m) => m.key === b.avgmode)) problems.push({ code: "AVGMODE", message: "평균 방식을 확인하세요" });
  const views = Array.isArray(b.views) ? b.views : [];
  if (!views.length || views.some((v) => !VIEW_KEYS.includes(v))) problems.push({ code: "VIEWS", message: "방향을 1개 이상 고르세요" });
  const lg = b.legend;
  if (!lg || (lg.mode !== "auto" && lg.mode !== "fixed")) problems.push({ code: "LEGEND", message: "범례 방식은 auto·fixed" });
  else if (lg.mode === "fixed" && (lg.min == null || lg.max == null || !(Number(lg.min) < Number(lg.max)))) problems.push({ code: "LEGEND_RANGE", message: "고정 범례는 최소 < 최대" });
  if (problems.length) return { problems };
  return {
    display: {
      field: String(b.field),
      component: String(b.component ?? ""),
      avgmode: String(b.avgmode),
      comps: (Array.isArray(b.comps) ? b.comps : []).map(String).filter(Boolean),
      legend: { mode: lg!.mode, min: lg!.min ?? null, max: lg!.max ?? null },
      views,
    },
  };
}

export const captureRoutes: Route = (srv, { method, seg, body }) => {
  if (seg[0] === "jobs" && seg[1] && (seg[2] === "media" || seg[2] === "capture")) {
    const j = srv.jobs.find((x) => x.id === seg[1]);
    if (!j) return err(404, "NOT_FOUND", "작업을 찾을 수 없습니다.");
    if (method === "GET" && seg[2] === "media") return ok(mediaOut(srv, j));
    if (method === "POST" && seg[2] === "capture") {
      const d = needPower(srv, j.project_id);
      if (d) return d;
      if (j.job_type !== "PREDICT" || j.state !== "SUCCEEDED") return err(409, "JOB_NOT_SUCCEEDED", "끝난 예측만 다시 캡처할 수 있습니다.");
      const views = (body?.views as ViewKey[] | undefined) ?? undefined;
      if (views !== undefined && (!Array.isArray(views) || !views.length || views.some((v) => !VIEW_KEYS.includes(v)))) return err(422, "INVALID_PARAMS", "views를 확인하세요.");
      const s = srv.studies.find((x) => x.id === j.study_id)!;
      const r = srv.createJob(s, "CONTOUR_CAPTURE", { predict_job_id: j.id, views: views ?? null, display: body?.display ?? null });
      return r.status === 201 ? { ...r, status: 202 } : r;
    }
    return null;
  }
  if (method === "PUT" && seg[0] === "param-sets" && seg[1] && seg[2] === "display") {
    const ps: ParamSet | undefined = srv.paramSets.find((p) => p.id === seg[1]);
    if (!ps) return err(404, "NOT_FOUND", "파라미터 세트를 찾을 수 없습니다.");
    const s = srv.studies.find((x) => x.id === ps.study_id)!;
    const d = needPower(srv, s.project_id);
    if (d) return d;
    const v = validDisplay(body);
    if ("problems" in v) return err(422, "DISPLAY_INVALID", "표시 설정을 확인하세요", { problems: v.problems });
    ps.display = v.display;
    return ok(ps);
  }
  return null;
};
