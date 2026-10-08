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

async function step<T>(name: string, schema: string, fn: () => Promise<T>): Promise<T | null> {
  try {
    const v = await fn();
    checkShape(name, schema, v);
    return v;
  } catch (e) {
    if (e instanceof ApiError && e.code === "NO_SAMPLE") {
      console.log(`ok   ${name} (404 NO_SAMPLE — 워커 없음, 예상됨)`);
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
  try {
    await api.inspectPath(created.id, "DATASET_INPUT", "/definitely/outside/root");
    console.log("FAIL paths/inspect: 루트 밖 경로가 거부되지 않음");
    failures++;
  } catch (e) {
    console.log(`ok   POST paths/inspect 루트 밖 → ${(e as ApiError).status} ${(e as ApiError).code}`);
  }
}
console.log(me ? `\n사용자 ${me.display_name}, 실패 ${failures}건` : `\n실패 ${failures}건`);
process.exit(failures ? 1 : 0);
