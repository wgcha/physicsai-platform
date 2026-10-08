// 목 서버 응답이 backend/openapi.json 스키마(required 필드, 중첩 $ref 포함)와 맞는지 확인
import { describe, expect, it } from "vitest";
import { MockServer } from "../mock/server";
import specJson from "../../../backend/openapi.json";

// 스키마 탐색용 느슨한 타입
const spec = specJson as unknown as { paths: Record<string, Record<string, any>>; components: { schemas: Record<string, any> } };
type Sch = { $ref?: string; required?: string[]; properties?: Record<string, Sch>; items?: Sch; anyOf?: Sch[]; type?: string };
const resolve = (s: Sch): Sch => (s.$ref ? spec.components.schemas[s.$ref.split("/").pop()!] : s);

function problems(value: unknown, s0: Sch, at: string): string[] {
  const s = resolve(s0);
  if (s.anyOf) {
    if (value === null && s.anyOf.some((x) => x.type === "null")) return [];
    const opts = s.anyOf.filter((x) => x.type !== "null");
    return opts.length ? problems(value, opts[0], at) : [];
  }
  if (Array.isArray(value)) return s.items ? value.flatMap((v, i) => problems(v, s.items!, `${at}[${i}]`)) : [];
  if (value && typeof value === "object" && s.properties) {
    const o = value as Record<string, unknown>;
    const out = (s.required ?? []).filter((k) => !(k in o)).map((k) => `${at}.${k} 없음`);
    for (const [k, ps] of Object.entries(s.properties)) if (k in o && o[k] !== undefined) out.push(...problems(o[k], ps, `${at}.${k}`));
    return out;
  }
  return [];
}

function responseSchema(p: string, method: string): Sch {
  const op = spec.paths[`/physicsai/api${p}`][method];
  const r = op.responses["200"] ?? op.responses["201"] ?? op.responses["202"];
  return r.content["application/json"].schema;
}

const cases: [string, string, string, ("power" | "admin")?, { hpcConfigured?: boolean }?][] = [
  ["/me", "/me", "get"],
  ["/status", "/status", "get"],
  ["/projects", "/projects", "get"],
  ["/queue", "/queue", "get"],
  ["/resources", "/resources", "get"],
  ["/studies?project_id=p-cushion", "/studies", "get"],
  ["/studies/s-cushion", "/studies/{study_id}", "get"],
  ["/studies/s-cushion/datasets", "/studies/{study_id}/datasets", "get"],
  ["/studies/s-cushion/models", "/studies/{study_id}/models", "get"],
  ["/models/m-1", "/models/{model_id}", "get"],
  ["/studies/s-cushion/param-sets", "/studies/{study_id}/param-sets", "get"],
  ["/param-sets/ps-1/samples?limit=5", "/param-sets/{ps_id}/samples", "get"],
  ["/jobs?study_id=s-cushion", "/jobs", "get"],
  ["/jobs/j-pred", "/jobs/{job_id}", "get"],
  ["/jobs/j-pred/artifacts", "/jobs/{job_id}/artifacts", "get"],
  ["/notifications", "/notifications", "get"],
  ["/notifications/unread-count", "/notifications/unread-count", "get"],
  // 2차(phase2.md §12)
  ["/status", "/status", "get", "admin"],
  ["/queue", "/queue", "get", "power", { hpcConfigured: true }],
  ["/jobs/j-solve", "/jobs/{job_id}", "get", "power", { hpcConfigured: true }],
  ["/jobs/j-opt", "/jobs/{job_id}", "get"],
  ["/studies/s-cushion/train", "/studies/{study_id}/train", "get"],
  ["/train/doe-types", "/train/doe-types", "get"],
  ["/studies/s-cushion/train/does", "/studies/{study_id}/train/does", "get"],
  ["/train-does/doe-1", "/train-does/{doe_id}", "get"],
  ["/train-does/doe-1/runs?limit=50", "/train-does/{doe_id}/runs", "get", "power", { hpcConfigured: true }],
  ["/train-does/doe-1/samples", "/train-does/{doe_id}/samples", "get"],
  ["/studies/s-cushion/curation-sources", "/studies/{study_id}/curation-sources", "get"],
  ["/studies/s-cushion/curations", "/studies/{study_id}/curations", "get"],
  ["/curations/cur-1", "/curations/{curation_id}", "get"],
  ["/curations/cur-1/files", "/curations/{curation_id}/files", "get"],
  ["/studies/s-cushion/spdm-imports", "/studies/{study_id}/spdm-imports", "get"],
  ["/studies/s-cushion/optimizations", "/studies/{study_id}/optimizations", "get"],
  ["/optimizations/opt-1", "/optimizations/{optimization_id}", "get"],
  ["/studies/s-cushion/optimize/response-candidates", "/studies/{study_id}/optimize/response-candidates", "get"],
  ["/admin/env-checks", "/admin/env-checks", "get", "admin"],
  ["/admin/env-checks/latest", "/admin/env-checks/latest", "get", "admin"],
  ["/admin/env-checks/ec-3", "/admin/env-checks/{check_id}", "get", "admin"],
];

describe("목 서버 ↔ openapi.json", () => {
  for (const [url, p, m, user = "power", opts = {}] of cases) {
    it(`${m.toUpperCase()} ${url} (${user})`, () => {
      const server = new MockServer({ user, ...opts });
      const u = new URL(url, "http://x");
      const r = server.handle(m.toUpperCase(), u.pathname, u.searchParams, null, new Headers());
      expect(r.status).toBe(200);
      expect(problems(r.body, responseSchema(p, m), p)).toEqual([]);
    });
  }

  it("2차 쓰기 응답: PUT train/params, POST train/tpl, POST env-checks, POST from-train", () => {
    const power = new MockServer({ user: "power" });
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    const v = power.p2.setups["s-cushion"].version;
    const params = power.p2.setups["s-cushion"].parameters.map((x) => ({ name: x.name, min: x.min, max: x.max, use: x.use }));
    const put = power.handle("PUT", "/studies/s-cushion/train/params", new URLSearchParams(), { version: v, parameters: params }, h);
    expect(put.status).toBe(200);
    expect(problems(put.body, responseSchema("/studies/{study_id}/train/params", "put"), "PUT params")).toEqual([]);
    const tpl = power.handle("POST", "/studies/s-cushion/train/tpl", new URLSearchParams(), { version: v + 1 }, h);
    expect(problems(tpl.body, responseSchema("/studies/{study_id}/train/tpl", "post"), "POST tpl")).toEqual([]);
    const ps = power.handle("POST", "/studies/s-cushion/param-sets/from-train", new URLSearchParams(), { doe_id: "doe-1" }, h);
    expect(ps.status).toBe(201);
    expect(problems(ps.body, responseSchema("/studies/{study_id}/param-sets/from-train", "post"), "from-train")).toEqual([]);
    const admin = new MockServer({ user: "admin" });
    const ec = admin.handle("POST", "/admin/env-checks", new URLSearchParams(), null, h);
    expect(ec.status).toBe(202);
    expect(problems(ec.body, responseSchema("/admin/env-checks", "post"), "POST env-checks")).toEqual([]);
  });

  it("목 서버의 2차 경로가 모두 openapi에 있다", () => {
    const paths = Object.keys(spec.paths);
    for (const p of ["/train/doe-types", "/train-does/{doe_id}/runs", "/curations/{curation_id}/files", "/admin/env-checks/{check_id}", "/jobs/{job_id}/error-bundle.zip", "/studies/{study_id}/param-sets/from-train"])
      expect(paths).toContain(`/physicsai/api${p}`);
  });

  it("C18: 취소 실패 작업(WAITING_HPC + attention_code)·HPC_CANCEL_FAILED 알림이 스키마에 맞다", () => {
    const s = new MockServer({ user: "power", hpcConfigured: true, hpcCancelFails: true });
    s.jobs.find((j) => j.id === "j-solve")!.cancel_requested = true;
    s.tick();
    const job = s.handle("GET", "/jobs/j-solve", new URLSearchParams(), null, new Headers());
    expect((job.body as { attention_code: string }).attention_code).toBe("HPC_CANCEL_FAILED");
    expect(problems(job.body, responseSchema("/jobs/{job_id}", "get"), "job")).toEqual([]);
    const n = s.handle("GET", "/notifications", new URLSearchParams(), null, new Headers());
    expect(problems(n.body, responseSchema("/notifications", "get"), "notifications")).toEqual([]);
    expect((n.body as { items: { event: string }[] }).items.some((i) => i.event === "HPC_CANCEL_FAILED")).toBe(true);
    const q = s.handle("GET", "/queue", new URLSearchParams(), null, new Headers());
    expect(problems(q.body, responseSchema("/queue", "get"), "queue")).toEqual([]);
  });

  it("input.zip: 준비 전 409 INPUT_NOT_READY", () => {
    const server = new MockServer({ user: "power" });
    const r = server.handle("GET", "/jobs/j-q2/artifacts/input.zip", new URLSearchParams(), null, new Headers());
    expect(r.status).toBe(409);
    expect((r.body as { detail: { code: string } }).detail.code).toBe("INPUT_NOT_READY");
  });
});
