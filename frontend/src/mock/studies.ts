// §10.3 Study 목 라우트: 목록·생성, 상세(단계 상태), ③·④ 하위 경로(데이터셋·모델·파라미터 세트·예측 검사·Final·경로 검사·작업 생성).
import type { JobType, ParamSet, Study, StudyDetail } from "../api/types";
import { PROJECTS, seedParamSet } from "./data";
import { err, needPower, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";
import { datasetOut, modelOut } from "./stage3";
import { check } from "./stage4";
import { discover, discoveredParams, registerDiscovered } from "./stage4Discover";

export function studyDetail(srv: MockServer, s: Study): StudyDetail {
  const latest = (stage: number) => {
    const j = srv.jobs.filter((x) => x.study_id === s.id && x.stage === stage).sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
    return { latest_job_id: j?.id ?? null, latest_job_type: j?.job_type ?? null, latest_state: j?.state ?? null };
  };
  const final = srv.models.find((m) => m.id === s.final_model_id) ?? null;
  return {
    ...srv.studyOut(s),
    final_model: final ? modelOut(srv, final, false) : null,
    stage_status: { "1": latest(1), "2": latest(2), "3": latest(3), "4": latest(4), "5": latest(5) },
    current_param_set_id: srv.paramSets.find((p) => p.study_id === s.id && p.is_current)?.id ?? null,
  };
}

/** 1차 경로 검사(DATASET_INPUT·MODEL_FOLDER·PARAM_SET) */
export function inspectPath(purpose: string, path: string): MockResp {
  if (!path.trim()) return err(422, "PATH_NOT_FOUND", "경로를 입력하세요.");
  if (/\s|[&|<>^%!"]/.test(path)) return err(422, "PATH_UNSAFE", "경로에 공백이나 특수문자를 쓸 수 없습니다.");
  if (!/AI_WORK/i.test(path)) return err(422, "PATH_OUTSIDE_ROOT", "AI 루트 하위 경로만 지정할 수 있습니다.");
  const last = path.split(/[\\/]/).filter(Boolean).pop() ?? "model";
  if (purpose === "DATASET_INPUT")
    return { status: 200, body: { normalized_path: path, ok: true, problems: [], summary: { h3d_count: 180, sample_files: ["run_0001/cushion_0001.h3d", "run_0002/cushion_0002.h3d", "run_0003/cushion_0003.h3d"], expected_train: 162, expected_eval: 18 } } };
  if (purpose === "MODEL_FOLDER") {
    // nopscfg → pscfg 0개(선택, D3-43 — 등록 가능)
    const logs = /nolog/i.test(path) ? [] : /multi/i.test(path) ? ["train.log", "train_retry.log"] : ["train.log"];
    return { status: 200, body: { normalized_path: path, ok: true, problems: [], summary: { psmdl: [`${last.replace(/[^A-Za-z0-9_]/g, "_")}.psmdl`], pscfg: /nopscfg/i.test(path) ? [] : ["settings.pscfg"], logs } } };
  }
  return { status: 200, body: { normalized_path: path, ok: true, problems: [], summary: { parameters: 4, samples: 120, responses: 3, cad: "cushion_base.x_t", starter: "cushion_0000.rad" } } };
}

export const studyRoutes: Route = (srv, { method, path, seg, query, body, me }) => {
  if (method === "GET" && path === "/studies") {
    const pid = query.get("project_id");
    const st = query.get("status");
    return { status: 200, body: srv.studies.filter((s) => (!pid || s.project_id === pid) && (!st || s.status === st)).map((s) => srv.studyOut(s)) };
  }
  if (method === "POST" && path === "/studies") {
    const pid = String(body?.project_id ?? "");
    if (!PROJECTS.some((p) => p.id === pid)) return err(404, "PROJECT_NOT_FOUND", "프로젝트를 찾을 수 없습니다.");
    const d = needPower(srv, pid);
    if (d) return d;
    const folder = String(body?.folder_name ?? "");
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(folder)) return err(422, "INVALID_PARAMS", "폴더 이름 형식이 올바르지 않습니다.");
    if (srv.studies.some((s) => s.folder_name === folder)) return err(409, "STUDY_NAME_EXISTS", "같은 폴더 이름의 Study가 있습니다.");
    const s: Study = {
      id: srv.nid("s"), project_id: pid, folder_name: folder, title: String(body?.title ?? folder), status: "ACTIVE", final_model_id: null,
      created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), version: 1, can_execute: true,
    };
    srv.studies.unshift(s);
    return { status: 201, body: srv.studyOut(s) };
  }
  if (seg[0] === "studies" && seg[1]) {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    const sub = seg[2];
    if (method === "GET" && !sub) return { status: 200, body: studyDetail(srv, s) };
    if (method === "GET" && sub === "datasets") return { status: 200, body: srv.datasets.filter((d) => d.study_id === s.id).map((d) => datasetOut(srv, d)) };
    if (method === "GET" && sub === "models") return { status: 200, body: srv.models.filter((m) => m.study_id === s.id).map((m) => modelOut(srv, m, false)) };
    if (method === "GET" && sub === "param-sets") return { status: 200, body: srv.paramSets.filter((p) => p.study_id === s.id) };
    if (method === "POST" && sub === "predict" && seg[3] === "check") {
      const ps = srv.paramSets.find((p) => p.id === (body?.param_set_id || "") || (p.study_id === s.id && p.is_current && !body?.param_set_id));
      if (!ps) return err(404, "NOT_FOUND", "파라미터 세트가 없습니다.");
      return { status: 200, body: check(srv, ps, (body?.values ?? {}) as Record<string, number>) };
    }
    const d = needPower(srv, s.project_id);
    if (d) return d;
    if (method === "PUT" && sub === "final-model") {
      const busy = srv.manage.storage.cleanupGate(s.id); // D3-24: 권한 검사 뒤
      if (busy) return busy;
      const id = body?.model_id as string | null;
      if (id) {
        const m = srv.models.find((x) => x.id === id && x.study_id === s.id);
        if (!m) return err(404, "NOT_FOUND", "모델을 찾을 수 없습니다.");
        if (m.status !== "ACTIVE") return err(409, "MODEL_NOT_ACTIVE", "사용 가능한 모델이 아닙니다.");
      }
      s.final_model_id = id;
      s.version++;
      return { status: 200, body: srv.studyOut(s) };
    }
    if (method === "POST" && sub === "paths" && seg[3] === "inspect")
      return srv.p2.inspect(String(body?.purpose), String(body?.path ?? ""), body?.doe_id as string | undefined, body?.engine as string | undefined) ?? inspectPath(String(body?.purpose), String(body?.path ?? ""));
    if (method === "POST" && sub === "param-sets" && seg[3] === "discover") return discover(String(body?.path ?? ""), body?.tpl as string | undefined);
    if (method === "POST" && sub === "param-sets" && !seg[3]) {
      let extra: Partial<ParamSet> = {};
      if (body?.mode === "discover") {
        const d = registerDiscovered(String(body?.path ?? ""), body?.choice as Record<string, string> | undefined);
        if ("status" in d) return d;
        extra = discoveredParams(d);
      } else {
        const r = inspectPath("PARAM_SET", String(body?.path ?? ""));
        if (r.status !== 200) return r;
      }
      const label = String(body?.label ?? "").trim() || null;
      srv.paramSets.forEach((p) => p.study_id === s.id && (p.is_current = false));
      const ps: ParamSet = { ...seedParamSet(), ...extra, label, id: srv.nid("ps"), study_id: s.id, source_path: String(body?.path), registered_by_name: me.display_name, registered_at: new Date().toISOString() };
      srv.samples[ps.id] = srv.samples["ps-1"];
      srv.paramSets.unshift(ps);
      return { status: 201, body: ps };
    }
    // S9 §14.5: batch_run은 워커만 쓴다(API 생성 요청에 있으면 422)
    if (method === "POST" && sub === "jobs" && (body?.params as Record<string, unknown> | undefined)?.batch_run !== undefined)
      return err(422, "INVALID_PARAMS", "batch_run은 지정할 수 없습니다.");
    if (method === "POST" && sub === "jobs") return srv.createJob(s, String(body?.job_type) as JobType, (body?.params ?? {}) as Record<string, unknown>);
  }
  return null;
};
