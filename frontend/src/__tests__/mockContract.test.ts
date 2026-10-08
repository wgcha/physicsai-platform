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

const cases: [string, string, string][] = [
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
];

describe("목 서버 ↔ openapi.json", () => {
  for (const [url, p, m] of cases) {
    it(`${m.toUpperCase()} ${p}`, () => {
      const server = new MockServer({ user: "power" });
      const u = new URL(url, "http://x");
      const r = server.handle(m.toUpperCase(), u.pathname, u.searchParams, null, new Headers());
      expect(r.status).toBe(200);
      expect(problems(r.body, responseSchema(p, m), p)).toEqual([]);
    });
  }

  it("input.zip: 준비 전 409 INPUT_NOT_READY", () => {
    const server = new MockServer({ user: "power" });
    const r = server.handle("GET", "/jobs/j-q2/artifacts/input.zip", new URLSearchParams(), null, new Headers());
    expect(r.status).toBe(409);
    expect((r.body as { detail: { code: string } }).detail.code).toBe("INPUT_NOT_READY");
  });
});
