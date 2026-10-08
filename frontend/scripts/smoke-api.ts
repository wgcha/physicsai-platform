// 실제 백엔드 대상 스모크: 프런트 API 클라이언트(src/api)로 주요 GET/POST를 호출하고
// 응답이 openapi.json 스키마의 required 필드를 갖는지 확인한다.
// 사용: SMOKE_BASE=http://127.0.0.1:8100 npx vite-node scripts/smoke-api.ts  (보통 scripts/smoke-backend.sh가 호출)
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { api, ApiError } from "../src/api";

const base = process.env.SMOKE_BASE ?? "http://127.0.0.1:8100";
const realFetch = globalThis.fetch;
globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  return realFetch(url.startsWith("/") ? base + url : url, init);
}) as typeof fetch;

const spec = JSON.parse(readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../backend/openapi.json"), "utf-8"));
const schemas = spec.components.schemas as Record<string, { required?: string[] }>;

let failures = 0;
function checkShape(name: string, schema: string, value: unknown) {
  const req = schemas[schema]?.required ?? [];
  const items = Array.isArray(value) ? value : [value];
  for (const it of items) {
    const missing = req.filter((k) => !(it && typeof it === "object" && k in (it as object)));
    if (missing.length) {
      failures++;
      console.log(`FAIL ${name}: ${schema} 필수 필드 없음 ${missing.join(",")}`);
      return;
    }
  }
  console.log(`ok   ${name} (${schema}${Array.isArray(value) ? ` ×${value.length}` : ""})`);
}

async function step<T>(name: string, schema: string, fn: () => Promise<T>, expected: string[] = []): Promise<T | null> {
  try {
    const v = await fn();
    checkShape(name, schema, v);
    return v;
  } catch (e) {
    if (e instanceof ApiError && (e.code === "NO_SAMPLE" || expected.includes(e.code))) {
      console.log(`ok   ${name} (${e.status} ${e.code} — 예상됨)`);
      return null;
    }
    failures++;
    console.log(`FAIL ${name}: ${e instanceof ApiError ? `${e.status} ${e.code} ${e.message}` : String(e)}`);
    return null;
  }
}

const me = await step("GET /me", "Me", () => api.me());
const status = await step("GET /status", "StatusResponse", () => api.status());
if (status) console.log(`     ui.poll_queue_ms=${status.ui.poll_queue_ms} auth.login_url=${status.auth.login_url}`);
const projects = await step("GET /projects", "Project", () => api.projects());
await step("GET /queue", "QueueResponse", () => api.queue());
await step("GET /resources", "ResourcesResponse", () => api.resources());
await step("GET /notifications/unread-count", "UnreadCount", () => api.unreadCount());
await step("GET /notifications", "NotificationList", () => api.notifications());
const projectId = projects?.[0]?.id ?? "dev";
const folder = `smoke_${Date.now().toString(36)}`;
const created = await step("POST /studies", "Study", () => api.createStudy({ project_id: projectId, folder_name: folder, title: "스모크" }));
if (created) {
  console.log(`     folder_display_path=${created.folder_display_path}`);
  await step("GET /studies", "Study", () => api.studies(projectId));
  const detail = await step("GET /studies/{id}", "StudyDetail", () => api.study(created.id));
  if (detail) console.log(`     stage_status=${JSON.stringify(detail.stage_status)}`);
  await step("GET /studies/{id}/datasets", "Dataset", () => api.datasets(created.id));
  await step("GET /studies/{id}/models", "Model", () => api.models(created.id));
  await step("GET /studies/{id}/param-sets", "ParamSet", () => api.paramSets(created.id));
  await step("GET /jobs", "JobSummary", () => api.jobs({ study_id: created.id }));
  // ---- 2차(phase2.md §12) 주요 GET ----
  const train = await step("GET /studies/{id}/train", "TrainSetup", () => api.train(created.id));
  if (train) console.log(`     parameters=${train.parameters.length} tpl=${train.tpl ? "있음" : "없음"} version=${train.version}`);
  // 예시 설정의 resources는 이 PC에 없으므로 409 RESOURCE_NOT_CONFIGURED / 503 CONFIG_INVALID도 계약상 정상
  await step("GET /train/doe-types", "DoeType", () => api.doeTypes(), ["RESOURCE_NOT_CONFIGURED", "CONFIG_INVALID"]);
  await step("GET /studies/{id}/train/does", "TrainDoe", () => api.trainDoes(created.id));
  await step("GET /studies/{id}/curation-sources", "CurationSource", () => api.curationSources(created.id));
  await step("GET /studies/{id}/curations", "Curation", () => api.curations(created.id));
  await step("GET /studies/{id}/spdm-imports", "SpdmImport", () => api.spdmImports(created.id));
  await step("GET /studies/{id}/optimizations", "Optimization", () => api.optimizations(created.id));
  await step("GET /studies/{id}/optimize/response-candidates", "ResponseCandidates", () => api.responseCandidates(created.id));
  if (status) {
    const f = status.features ?? {};
    console.log(`     features 비활성: ${Object.entries(f).filter(([, v]) => v && !v.enabled).map(([k]) => k).join(", ") || "없음"} · collect_mode=${status.hpc.collect_mode}`);
  }
  try {
    await api.inspectPath(created.id, "SPDM_IMPORT", "/definitely/not/spdm");
    console.log("FAIL paths/inspect SPDM_IMPORT: SPDM 루트 밖 경로가 거부되지 않음");
    failures++;
  } catch (e) {
    console.log(`ok   POST paths/inspect SPDM_IMPORT 루트 밖 → ${(e as ApiError).status} ${(e as ApiError).code}`);
  }
  try {
    await api.inspectPath(created.id, "DATASET_INPUT", "/definitely/outside/root");
    console.log("FAIL paths/inspect: 루트 밖 경로가 거부되지 않음");
    failures++;
  } catch (e) {
    console.log(`ok   POST paths/inspect 루트 밖 → ${(e as ApiError).status} ${(e as ApiError).code}`);
  }
}
// 환경 점검(전역 관리자 전용): 관리자가 아니면 403이 정상
if (me?.is_global_admin) {
  const list = await step("GET /admin/env-checks", "EnvCheckSummary", async () => (await api.envChecks(20)).items);
  if (list?.length) await step("GET /admin/env-checks/{id}", "EnvCheck", () => api.envCheck(list[0].id));
  else await step("GET /admin/env-checks/latest", "EnvCheck", () => api.latestEnvCheck(), ["NOT_FOUND"]);
} else {
  try {
    await api.envChecks(1);
    console.log("FAIL GET /admin/env-checks: 비관리자에게 열림");
    failures++;
  } catch (e) {
    console.log(`ok   GET /admin/env-checks 비관리자 → ${(e as ApiError).status} ${(e as ApiError).code}`);
  }
}
console.log(me ? `\n사용자 ${me.display_name}, 실패 ${failures}건` : `\n실패 ${failures}건`);
process.exit(failures ? 1 : 0);
