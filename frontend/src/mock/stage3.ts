// 1차 ③(데이터셋·학습 패키지·모델·평가) 목: 출력 변환, 완료 처리, 데이터셋·모델 라우트(§10.4).
import type { Dataset, Job, Model } from "../api/types";
import { COMMANDS_TXT, curveStats, lossCurve } from "./data";
import { err, type Route } from "./route";
import type { MockServer } from "./server";

export function datasetOut(srv: MockServer, d: Dataset): Dataset {
  return {
    ...d,
    dataset_display_path: srv.disp(d.study_id, `03_dataset/${d.id}`),
    package_rel: d.package_ready ? `03_package/${d.id}/` : null,
    package_display_path: d.package_ready ? srv.disp(d.study_id, `03_package/${d.id}`) : null,
  };
}

export function modelOut(srv: MockServer, m: Model, withCurve: boolean): Model {
  const study = srv.studies.find((s) => s.id === m.study_id);
  const out = { ...m, is_final: study?.final_model_id === m.id, stored_display_path: srv.disp(m.study_id, `03_model/models/${m.id}`) };
  if (!withCurve) delete out.loss_curve;
  return out;
}

/** ③ 작업 완료 처리(DATASET_CREATE·PACKAGE_EXPORT·MODEL_REGISTER·EVALUATE) */
export function finishStage3(srv: MockServer, j: Job) {
  const p = j.params as Record<string, unknown>;
  const now = new Date().toISOString();
  switch (j.job_type) {
    case "DATASET_CREATE": {
      const ds = srv.datasets.find((d) => d.job_id === j.id);
      if (ds) Object.assign(ds, { status: "READY", h3d_count: 180, train_count: 162, eval_count: 18 });
      const cur = srv.p2.curations.find((c) => c.id === p.curation_id);
      if (cur && ds) cur.used_by_dataset_ids.push(ds.id);
      j.result = { dataset_id: ds?.id, h3d_count: 180, train_count: 162, eval_count: 18 };
      break;
    }
    case "PACKAGE_EXPORT": {
      const ds = srv.datasets.find((d) => d.id === p.dataset_id);
      if (ds) ds.package_ready = true;
      srv.addArtifact(j.id, j.study_id, "PACKAGE_COMMANDS", `03_package/${p.dataset_id}/COMMANDS.txt`, "text/plain", COMMANDS_TXT);
      break;
    }
    case "MODEL_REGISTER": {
      const path = String(p.model_path);
      const name = String(p.name || path.split(/[\\/]/).pop() || "model");
      const ver = Math.max(0, ...srv.models.filter((m) => m.study_id === j.study_id && m.name === name).map((m) => m.version)) + 1;
      const status = /nolog/i.test(path) ? "MISSING" : /raw|unknown/i.test(path) ? "UNRECOGNIZED" : "PARSED";
      const curve = status === "PARSED" ? lossCurve(srv.idn, 1200, 0.7) : null;
      const ds = (p.dataset_id as string) || srv.datasets.find((d) => d.study_id === j.study_id && d.status === "READY")?.id || null;
      const m: Model = {
        id: srv.nid("m"), study_id: j.study_id, name, version: ver, label: (p.label as string) ?? null, dataset_id: ds, source_path: path,
        log_status: status, log_parser: status === "PARSED" ? "default" : null, epochs_total: curve ? 1200 : null, last_epoch: curve ? 1200 : null,
        ...(curve ? curveStats(curve) : { final_loss: null, min_loss: null, min_loss_epoch: null }),
        loss_curve: curve, curve_points: curve?.length ?? 0, eval_status: "NONE", eval_score: null, status: "ACTIVE", is_final: false,
        registered_by_name: j.created_by_name, registered_at: now, row_version: 1,
      };
      srv.models.unshift(m);
      j.result = { model_id: m.id };
      break;
    }
    case "EVALUATE": {
      const m = srv.models.find((x) => x.id === p.model_id);
      if (m) {
        m.eval_status = "DONE";
        m.eval_score = { status: "PARSED", metrics: { R2: 0.95 + (srv.idn % 40) / 1000, MAE: 1.4 + (srv.idn % 7) / 10 }, score_rel: "" };
        m.row_version++;
      }
      break;
    }
  }
}

/** §10.4 데이터셋·모델 단건 */
export const datasetModelRoutes: Route = (srv, { method, seg }) => {
  if (method === "GET" && seg[0] === "models" && seg[1]) {
    const m = srv.models.find((x) => x.id === seg[1]);
    return m ? { status: 200, body: modelOut(srv, m, true) } : err(404, "NOT_FOUND", "모델을 찾을 수 없습니다.");
  }
  if (method === "GET" && seg[0] === "datasets" && seg[1] && !seg[2]) {
    const d = srv.datasets.find((x) => x.id === seg[1]);
    return d ? { status: 200, body: datasetOut(srv, d) } : err(404, "NOT_FOUND", "데이터셋을 찾을 수 없습니다.");
  }
  return null;
};
