// ③ 데이터 점검 목(data-health.md §6.2·§8): DATA_HEALTH 작업 완료 시 report.json(계약 모양)·CSV 산출물을 만들고
// GET /jobs/{id}/data-health가 돌려준다(미완료 409 REPORT_NOT_READY, DATA_HEALTH 아님 404).
// 시나리오 12 run: 제외 필수 2(프레임·종료 시각) · 추천 3(① FAIL·견고 z·kNN) · 3σ만 1 · 프레임 확인 불가 2 · 정상 4.
import type { DataHealthReport, DhRun, DhValue, Job } from "../api/types";
import { err, ok, type Route } from "./route";
import type { MockServer } from "./server";

const v = (x: number | string | null, o: Partial<DhValue> = {}): DhValue => ({ v: x, ...o });
const NA = (code: string): DhValue => ({ v: null, na: code });

function run(i: number, o: Partial<DhRun> & { sound?: Partial<DhRun["sound"]> } = {}): DhRun {
  const n = String(i).padStart(3, "0");
  const { sound, ...rest } = o;
  return {
    file_rel: `run_${n}/cushion_${n}.h3d`, run_key: `D-001#${i}`, required: false, recommended: false, score: 0.2 + (i % 5) / 10, sigma_only: false,
    sound: { term: v("NORMAL"), energy_err_pct: v(-1.2), added_mass: v(0.004), frames: v(22), t_last: v(0.012), ...sound },
    values: { volume: v(1000 + i, { z: 0.1, zr: 0.2, s: 0.3 }), mass_total: v(5.1, { z: -0.2, zr: -0.1 }) },
    reasons: [], ...rest,
  };
}

export function dataHealthReport(): DataHealthReport {
  const runs: DhRun[] = [
    run(1, { required: true, recommended: true, score: 100, sound: { frames: v(18, { fail: true }) }, reasons: [{ code: "CONSISTENCY_FRAMES", message: "프레임 수 18 — 기준 22와 다름" }] }),
    run(2, { required: true, recommended: true, score: 100, sound: { t_last: v(0.006, { fail: true }) }, reasons: [{ code: "CONSISTENCY_TEND", message: "마지막 시각 0.006 s — 기준 0.012 s 미달" }] }),
    run(3, { recommended: true, score: 2, sound: { term: v("ERROR", { fail: true }) }, reasons: [{ code: "SOUND_TERM", metric: "term", message: "정상 종료 아님 — 오류 종료" }] }),
    run(4, {
      recommended: true, score: 1.49, values: { volume: v(1210, { z: 3.4, zr: 5.2, s: 0.4 }), mass_total: v(5.1, { z: 0, zr: 0 }) },
      reasons: [{ code: "ROBUST_Z", metric: "volume", zr: 5.2, message: "쿠션 부피 견고 z 5.2(값 1210, 중앙값 1005, MAD 26)" }],
    }),
    run(5, {
      recommended: true, score: 1.4, values: { volume: v(1006, { z: 0.1, zr: 0.1, s: -4.9 }), mass_total: v(5.1, { z: 0, zr: 0 }) },
      reasons: [{ code: "KNN_JUMP", metric: "volume", s: -4.9, message: "이웃 대비 튐 쿠션 부피 점수 −4.9" }],
    }),
    run(6, { sigma_only: true, score: 0.8, values: { volume: v(1100, { z: 3.2, zr: 2.1, s: 0.2 }), mass_total: v(5.1, { z: 0, zr: 0 }) } }),
    run(7, { sound: { frames: NA("FRAMES_PROBE_UNAVAILABLE") } }),
    run(8, { sound: { frames: NA("FRAMES_PROBE_UNAVAILABLE") } }),
    run(9), run(10), run(11), run(12),
  ];
  return {
    summary: {
      n_runs: 12, n_required: 2, n_frames_unknown: 2, n_recommended: 5, n_sigma_only: 1, n_sound_fail: 1, frames_ref: 22, t_end_ref: 0.012, ref_source: "mode",
      n_na_by_metric: { "resp:MAX_ACC": 12 }, thresholds: { robust_z: 3.5, knn_z: 3.5, sigma_z: 3 }, limited: false,
      warnings: [{ code: "DH_RESP_NOT_EXTRACTED", message: "①-6 run 응답 추출을 먼저 실행하면 응답 지표를 함께 봅니다" }],
    },
    metrics: [
      { id: "volume", label: "쿠션 부피", unit: "mm³", group: "attr", n: 12, mean: 1050, std: 60, median: 1005, mad: 26, skipped: null },
      { id: "mass_total", label: "모델 총질량", unit: "t", group: "attr", n: 12, mean: 5.1, std: 0.02, median: 5.1, mad: 0.01, skipped: null },
      { id: "resp:MAX_ACC", label: "응답 MAX_ACC", unit: null, group: "resp", n: 0, skipped: "SKIP_SMALL_N" },
    ],
    runs,
  };
}

export function finishDataHealth(srv: MockServer, j: Job) {
  const rep = dataHealthReport();
  const s = rep.summary;
  j.result = { ...(j.params as object), n_runs: s.n_runs, n_required: s.n_required, n_frames_unknown: s.n_frames_unknown, n_recommended: s.n_recommended, warnings: s.warnings };
  const dir = `03_dataset/_health/${j.id}`;
  srv.addArtifact(j.id, j.study_id, "DATA_HEALTH_REPORT", `${dir}/report.json`, "application/json", JSON.stringify(rep));
  srv.addArtifact(j.id, j.study_id, "DATA_HEALTH_CSV", `${dir}/runs.csv`, "text/csv", "file_rel,recommended,score\n" + rep.runs.map((r) => `${r.file_rel},${r.recommended},${r.score}`).join("\n"));
}

export const dataHealthRoutes: Route = (srv, { method, seg }) => {
  if (method !== "GET" || seg[0] !== "jobs" || seg[2] !== "data-health" || seg.length !== 3) return null;
  const j = srv.jobs.find((x) => x.id === seg[1]);
  if (!j || j.job_type !== "DATA_HEALTH") return err(404, "NOT_FOUND", "점검 작업을 찾을 수 없습니다.");
  if (j.state !== "SUCCEEDED") return err(409, "REPORT_NOT_READY", "점검이 아직 끝나지 않았습니다.");
  const a = srv.artifacts.find((x) => x.job_id === j.id && x.kind === "DATA_HEALTH_REPORT");
  return a ? ok(JSON.parse(a.body as string)) : err(404, "REPORT_MISSING", "점검 보고서 파일이 없습니다.");
};
