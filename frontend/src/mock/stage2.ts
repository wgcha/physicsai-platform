// 2차 ②(phase2.md §7) 큐레이션·SPDM 가져오기: 시드, 미리보기 산출물, 작업 훅, ② 라우트.
import type { CurationSourceRef, Job, JobType } from "../api/types";
import { iso } from "./data";
import { err, ok, type MockResp, type Route } from "./route";
import type { Phase2Mock, SeedJob } from "./phase2";
import type { RunRec } from "./stage1";

const H3D_INFO: Record<string, string[]> = {
  Stress: ["vonMises", "P1 (major)", "Max Abs Principal"],
  Displacement: ["X", "Y", "Z", "Mag"],
  "Plastic Strain": ["Plastic Strain"],
  "Element Energy": ["Total Energy Density", "Extreme Value"],
};

/** 원본 to_cfg_datacomp(GUI:711-734) 사용 가능 판정: 1~2단어, Extreme 시작 제외 */
export function usableComponent(c: string): boolean {
  const w = c.trim().split(/\s+/);
  return !c.startsWith("Extreme") && w.length >= 1 && w.length <= 2;
}

const T01_PREVIEW = {
  dataTypes: [
    { name: "Rigid Body", requests: [{ name: "RBODY 1", components: ["F-Mag", "F-X", "F-Y", "F-Z"] }, { name: "RBODY 2", components: ["F-Mag", "M-Mag"] }] },
    { name: "Nodal", requests: [{ name: "Node 100", components: ["DX", "DY", "DZ"] }] },
  ],
};

function curveSeries() {
  const x: number[] = [];
  const y: number[] = [];
  for (let i = 0; i <= 50; i++) {
    x.push(Number((i * 0.0002).toFixed(4)));
    y.push(Number((1850 * Math.sin((i / 50) * Math.PI) * (1 - Math.exp(-i / 6))).toFixed(1)));
  }
  return { series: [{ name: "RBODY 1 F-Mag [N]", x, y }] };
}

/** SPDM 가져오기·② 미리보기·큐레이션 시드(원래 seed 순서 그대로) */
export function seedCuration(p2: Phase2Mock, J: SeedJob, sid: string, doeId: string, runs: RunRec[]) {
  // SPDM 가져오기
  p2.imports.push({
    id: "imp-1", study_id: sid, job_id: "j-spdm", status: "READY", spdm_path: "\\\\spdm\\master\\FD-X\\Case_0012\\Scene 03", file_count: 48, total_bytes: 9_800_000_000, renamed_count: 2,
    dest_display_path: p2.s.disp(sid, "02_import/imp-1"), created_by_name: "김연구", created_at: iso(60 * 2 + 40),
  });
  J({ id: "j-spdm", job_type: "SPDM_IMPORT", state: "SUCCEEDED", created_at: iso(60 * 2 + 40), params: { spdm_path: "\\\\spdm\\master\\FD-X\\Case_0012\\Scene 03" } });

  // ② 미리보기·큐레이션
  const src: CurationSourceRef = { kind: "TRAIN_DOE", doe_id: doeId };
  J({ id: "j-h3dprev", job_type: "CU_H3D_PREVIEW", state: "SUCCEEDED", created_at: iso(60 * 2 + 20), params: { source: src, sample_file: null } });
  previewArtifacts(p2, "j-h3dprev", sid, src);
  J({ id: "j-cur1", job_type: "CU_H3D_CURATE", state: "SUCCEEDED", created_at: iso(60 * 2), params: { source: src, preview_job_id: "j-h3dprev", selection: { items: [{ datatype: "Stress", component: "vonMises" }], parts: { shell: [1, 2], solid: [], rbody: [] }, time_increment: 2 }, exclude_files: [] }, warnings: [{ code: "PARTIAL_OUTPUT", message: "24개 중 1개 실패" }] });
  p2.curations.push({
    id: "cur-1", study_id: sid, job_id: "j-cur1", kind: "H3D", status: "READY", source: src, source_label: "① DOE doe-1 · LatinHyperCube 30", preview_job_id: "j-h3dprev",
    selection: { items: [{ datatype: "Stress", component: "vonMises" }], parts: { shell: [1, 2], solid: [], rbody: [] }, time_increment: 2, time_steps_count: 21 },
    target_count: 24, ok_count: 23, failed_count: 1, missing_runs: runs.slice(24).map((x) => x.run_key),
    output_display_path: p2.s.disp(sid, "02_curated/cur-1/CURATED_DATA"), used_by_dataset_ids: [], created_by_name: "김연구", created_at: iso(60 * 2),
  });
  p2.curationFiles["cur-1"] = runs.slice(0, 24).map((rr, i) => ({
    run_folder: rr.run_key, run_key: rr.run_key, input_name: "cushion_0000.h3d", output_name: i === 16 ? null : "cushion_0000.h3d", size: i === 16 ? null : 38_000_000 + i * 120_000, ok: i !== 16, exit_code: i === 16 ? 1 : 0,
  }));
  J({ id: "j-t01prev", job_type: "CU_T01_PREVIEW", state: "SUCCEEDED", created_at: iso(60 + 50), params: { source: src, sample_file: null } });
  p2.s.addArtifact("j-t01prev", sid, "PREVIEW_JSON", "02_preview/j-t01prev/PREVIEW_T01.json", "application/json", JSON.stringify(T01_PREVIEW));
  J({ id: "j-cur2", job_type: "CU_T01_CURVES", state: "SUCCEEDED", created_at: iso(60 + 40), params: { source: src, curves: [{ type: "Rigid Body", request: "RBODY 1", component: "F-Mag" }], exclude_files: [] } });
  p2.curations.push({
    id: "cur-2", study_id: sid, job_id: "j-cur2", kind: "T01", status: "READY", source: src, source_label: "① DOE doe-1 · LatinHyperCube 30", preview_job_id: null,
    selection: { curves: [{ type: "Rigid Body", request: "RBODY 1", component: "F-Mag" }] }, target_count: 24, ok_count: 24, failed_count: 0, missing_runs: [],
    output_display_path: p2.s.disp(sid, "02_curated/cur-2/CURVES"), used_by_dataset_ids: [], created_by_name: "김연구", created_at: iso(60 + 40),
  });
  p2.s.addArtifact("j-cur2", sid, "CURVE_JSON", "02_curated/cur-2/CURVES/run__00001/cushion_0000_curves.json", "application/json", JSON.stringify(curveSeries()));
}

function previewArtifacts(p2: Phase2Mock, jobId: string, studyId: string, source: CurationSourceRef) {
  const files = sourceFiles(p2, studyId, source);
  const raw = { datatype_info: H3D_INFO, lst_cid_shell: [1, 2, 5, 7], lst_cid_solid: [3, 4], lst_cid_rbody: [9], num_time_step: 41 };
  const usable = Object.fromEntries(Object.entries(H3D_INFO).map(([k, v]) => [k, v.filter(usableComponent)]));
  p2.s.addArtifact(jobId, studyId, "PREVIEW_JSON", `02_preview/${jobId}/PREVIEW_H3D.json`, "application/json", JSON.stringify(raw));
  // 변경 메모 C14 형식
  const summary = {
    datatypes: Object.entries(H3D_INFO).map(([name, components]) => ({ name, components, usable: usable[name] })),
    parts: { shell: raw.lst_cid_shell, solid: raw.lst_cid_solid, rbody: raw.lst_cid_rbody },
    num_time_step: raw.num_time_step,
    sample_file: files[0] ?? null,
    source_file_count: files.length,
    files: files.map((rel) => ({ rel, run_folder: rel.split("/")[0], size: 38_000_000 })),
  };
  p2.s.addArtifact(jobId, studyId, "PREVIEW_JSON", `02_preview/${jobId}/preview_summary.json`, "application/json", JSON.stringify(summary));
}

function sourceFiles(p2: Phase2Mock, studyId: string, source: CurationSourceRef): string[] {
  if (source.kind === "TRAIN_DOE") return (p2.runs[source.doe_id] ?? []).filter((r) => r.state === "COLLECTED").map((r) => `${r.run_key}/m_3/cushion_0000.h3d`);
  if (source.kind === "SPDM_IMPORT") return Array.from({ length: 12 }, (_, i) => `Case_0012/Scene_03/sub_${String(i + 1).padStart(2, "0")}/result.h3d`);
  void studyId;
  return Array.from({ length: 8 }, (_, i) => `case_${i + 1}/model.h3d`);
}

function sourceLabel(p2: Phase2Mock, src: CurationSourceRef): string {
  if (src.kind === "TRAIN_DOE") {
    const d = p2.does.find((x) => x.id === src.doe_id);
    return `① DOE ${src.doe_id} · ${d?.doe_label ?? ""} ${d?.run_count ?? ""}`.trim();
  }
  if (src.kind === "SPDM_IMPORT") return `SPDM 가져오기 ${src.import_id}`;
  return src.path;
}

export function precheckCuration(p2: Phase2Mock, type: JobType, params: Record<string, unknown>): MockResp | null {
  if (type === "CU_H3D_CURATE") {
    const pj = p2.s.jobs.find((x) => x.id === params.preview_job_id && x.job_type === "CU_H3D_PREVIEW" && x.state === "SUCCEEDED");
    if (!pj) return err(409, "CURATION_PREVIEW_REQUIRED", "h3d 미리보기를 먼저 실행하세요.");
  }
  return null;
}

export function onCreateCuration(p2: Phase2Mock, j: Job, me: { display_name: string }) {
  const p = j.params as Record<string, unknown>;
  const sid = j.study_id;
  const now = j.created_at;
  if (j.job_type === "CU_H3D_CURATE" || j.job_type === "CU_T01_CURVES") {
    const id = p2.s.nid("cur");
    p.curation_id = id;
    p2.curations.unshift({
      id, study_id: sid, job_id: j.id, kind: j.job_type === "CU_H3D_CURATE" ? "H3D" : "T01", status: "BUILDING", source: p.source as CurationSourceRef, source_label: sourceLabel(p2, p.source as CurationSourceRef),
      preview_job_id: (p.preview_job_id as string) ?? null, selection: (p.selection as Record<string, unknown>) ?? { curves: p.curves }, target_count: 0, ok_count: 0, failed_count: 0, missing_runs: [],
      output_display_path: p2.s.disp(sid, `02_curated/${id}/${j.job_type === "CU_H3D_CURATE" ? "CURATED_DATA" : "CURVES"}`), used_by_dataset_ids: [], created_by_name: me.display_name, created_at: now,
    });
  }
  if (j.job_type === "SPDM_IMPORT") {
    const id = p2.s.nid("imp");
    p.import_id = id;
    p2.imports.unshift({ id, study_id: sid, job_id: j.id, status: "BUILDING", spdm_path: String(p.spdm_path), file_count: null, total_bytes: null, renamed_count: null, dest_display_path: p2.s.disp(sid, `02_import/${id}`), created_by_name: me.display_name, created_at: now });
  }
}

/** ② 완료 처리. ② 작업이 아니면 undefined */
export function finishCuration(p2: Phase2Mock, j: Job): "done" | undefined {
  const p = j.params as Record<string, unknown>;
  const sid = j.study_id;
  switch (j.job_type) {
    case "CU_H3D_PREVIEW": {
      previewArtifacts(p2, j.id, sid, p.source as CurationSourceRef);
      j.result = { sample_file: null, datatype_count: 4, part_counts: { shell: 4, solid: 2, rbody: 1 }, num_time_step: 41, source_file_count: sourceFiles(p2, sid, p.source as CurationSourceRef).length };
      return "done";
    }
    case "CU_T01_PREVIEW": {
      p2.s.addArtifact(j.id, sid, "PREVIEW_JSON", `02_preview/${j.id}/PREVIEW_T01.json`, "application/json", JSON.stringify(T01_PREVIEW));
      return "done";
    }
    case "CU_H3D_CURATE":
    case "CU_T01_CURVES": {
      const c = p2.curations.find((x) => x.id === p.curation_id)!;
      const files = sourceFiles(p2, sid, c.source).filter((f) => !((p.exclude_files as string[]) ?? []).includes(f));
      const failIdx = c.kind === "H3D" && files.length > 3 ? 2 : -1;
      p2.curationFiles[c.id] = files.map((f, i) => {
        const rf = f.split("/")[0];
        return { run_folder: rf, run_key: /^run__/.test(rf) ? rf : null, input_name: f.split("/").pop()!, output_name: i === failIdx ? null : c.kind === "H3D" ? f.split("/").pop()! : `${rf}_curves.json`, size: i === failIdx ? null : 30_000_000, ok: i !== failIdx, exit_code: i === failIdx ? 1 : 0 };
      });
      Object.assign(c, {
        status: "READY", target_count: files.length, ok_count: files.length - (failIdx >= 0 ? 1 : 0), failed_count: failIdx >= 0 ? 1 : 0,
        missing_runs: c.source.kind === "TRAIN_DOE" ? (p2.runs[c.source.doe_id] ?? []).filter((r) => r.state !== "COLLECTED").map((r) => r.run_key) : [],
      });
      if (failIdx >= 0) j.warnings = [{ code: "PARTIAL_OUTPUT", message: `${files.length}개 중 1개 실패` }];
      if (c.kind === "T01") p2.s.addArtifact(j.id, sid, "CURVE_JSON", `02_curated/${c.id}/CURVES/first_curves.json`, "application/json", JSON.stringify(curveSeries()));
      j.result = { curation_id: c.id, target_count: c.target_count, ok_count: c.ok_count, failed_count: c.failed_count, missing_run_count: c.missing_runs.length, output_display_path: c.output_display_path };
      return "done";
    }
    case "SPDM_IMPORT": {
      const im = p2.imports.find((x) => x.id === p.import_id);
      if (im) Object.assign(im, { status: "READY", file_count: 12, total_bytes: 2_400_000_000, renamed_count: 1 });
      return "done";
    }
    default:
      return undefined;
  }
}

/** ② 라우트: 큐레이션·파일 목록, Study 큐레이션 원천·목록·SPDM 가져오기 */
export const curationRoutes: Route = (srv, { method, seg, query }) => {
  const p2 = srv.p2;
  if (seg[0] === "curations" && seg[1]) {
    const c = p2.curations.find((x) => x.id === seg[1]);
    if (!c) return err(404, "NOT_FOUND", "큐레이션을 찾을 수 없습니다.");
    if (method === "GET" && !seg[2]) return ok(c);
    if (method === "GET" && seg[2] === "files") {
      let files = p2.curationFiles[c.id] ?? [];
      const okq = query.get("ok");
      if (okq !== null) files = files.filter((f) => String(f.ok) === okq);
      return ok({ items: files.slice(0, Number(query.get("limit") ?? 200)), next_cursor: null });
    }
  }
  if (seg[0] === "studies" && seg[1]) {
    const s = p2.s.studies.find((x) => x.id === seg[1]);
    if (!s) return null;
    const sub = seg.slice(2).join("/");
    if (method === "GET" && sub === "curation-sources") {
      const out: unknown[] = [];
      for (const d of p2.does.filter((x) => x.study_id === s.id && x.status === "READY")) {
        const n = (p2.runs[d.id] ?? []).filter((r) => r.state === "COLLECTED").length;
        if (n) out.push({ kind: "TRAIN_DOE", ref_id: d.id, label: `① DOE ${d.doe_label} · ${d.run_count} run`, display_path: d.results_display_path, h3d_count: n, t01_count: n, runs_expected: d.run_count, created_at: d.created_at });
      }
      for (const im of p2.imports.filter((x) => x.study_id === s.id && x.status === "READY"))
        out.push({ kind: "SPDM_IMPORT", ref_id: im.id, label: `SPDM ${im.spdm_path.split("\\").slice(-2).join("\\")}`, display_path: im.dest_display_path, h3d_count: 12, t01_count: 12, runs_expected: null, created_at: im.created_at });
      return ok(out);
    }
    if (method === "GET" && sub === "curations") {
      const kind = query.get("kind");
      return ok(p2.curations.filter((c) => c.study_id === s.id && (!kind || c.kind === kind)));
    }
    if (method === "GET" && sub === "spdm-imports") return ok(p2.imports.filter((x) => x.study_id === s.id));
  }
  return null;
};
