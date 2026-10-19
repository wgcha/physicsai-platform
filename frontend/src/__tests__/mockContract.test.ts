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

const cases: [string, string, string, ("power" | "admin")?, ConstructorParameters<typeof MockServer>[0]?][] = [
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
  ["/datasets/ds-2", "/datasets/{dataset_id}", "get"],
  ["/studies/s-cushion/param-sets", "/studies/{study_id}/param-sets", "get"],
  ["/param-sets/ps-1/samples?limit=5", "/param-sets/{ps_id}/samples", "get"],
  ["/jobs?study_id=s-cushion", "/jobs", "get"],
  ["/jobs/j-pred", "/jobs/{job_id}", "get"],
  ["/jobs/j-pred/artifacts", "/jobs/{job_id}/artifacts", "get"],
  ["/notifications", "/notifications", "get"],
  ["/notifications/unread-count", "/notifications/unread-count", "get"],
  // 2차(phase2.md §12)
  ["/status", "/status", "get", "admin"],
  ["/status", "/status", "get", "admin", { configWarnings: ["resources.extract_minmax_tcl 미설정"], disabledFeatures: ["dataset_create", "evaluate", "predict"] }],
  ["/queue", "/queue", "get", "power", { hpcConfigured: true }],
  ["/jobs/j-solve", "/jobs/{job_id}", "get", "power", { hpcConfigured: true }],
  ["/jobs/j-opt", "/jobs/{job_id}", "get"],
  // 3차 §16 S11 SCX(D3-58): hpc-jobs scx 필드
  ["/jobs/j-solve/hpc-jobs", "/jobs/{job_id}/hpc-jobs", "get", "power", { hpcConfigured: true, hpcMode: "scx", scxUnknown: true }],
  ["/jobs/j-solve/hpc-jobs", "/jobs/{job_id}/hpc-jobs", "get", "power", { hpcConfigured: true }],
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
  // 3차 §12 S7 서버 경로 탐색
  ["/fs/roots", "/fs/roots", "get"],
  ["/fs/list?path=E%3A%5Cshared%5CAI_WORK%5Cinbox&exts=.rad,.hm", "/fs/list", "get"],
  // geometry-engine.md §7.6 native 세트·피처·상태
  ["/param-sets/ps-n1", "/param-sets/{ps_id}", "get", "power", { geometry: "native" }],
  ["/param-sets/ps-n1/features", "/param-sets/{ps_id}/features", "get", "power", { geometry: "native" }],
  ["/studies/s-cushion/param-sets", "/studies/{study_id}/param-sets", "get", "power", { geometry: "multi" }],
  ["/status", "/status", "get", "power", { disabledFeatures: ["geometry_native"] }],
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

  it("S15 표본 방식 응답(V3-S15-8·10 모양): 미리보기 10개 kind·배치 상세·목록 sampling·doe-types·result-table", () => {
    const power = new MockServer({ user: "power", batchDemo: "sobol" });
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    const q = new URLSearchParams();
    const previewSchema = responseSchema("/studies/{study_id}/predict-batches/preview", "post");
    const sources: Record<string, unknown>[] = [
      { kind: "lhs", count: 6, seed: 1 }, { kind: "lhs_opt", count: 6, seed: 1, criterion: "maximin" }, { kind: "sobol", count: 8, seed: 1 }, { kind: "sobol", count: 8, continue_from: "pb-3" },
      { kind: "fullfact", levels: { THK_TOP: 2, THK_FOAM: 2, E_FOAM: 2, RIB_N: 2 } }, { kind: "fracfact", resolution: 4 }, { kind: "pb" }, { kind: "bbd" }, { kind: "ccd", alpha: "inscribed" },
      { kind: "table", text: "THK_TOP\tTHK_FOAM\tE_FOAM\tRIB_N\n0.5\t2\t8\t4\n" }, { kind: "train_doe", doe_id: "doe-1" },
    ];
    for (const source of sources) {
      const r = power.handle("POST", "/studies/s-cushion/predict-batches/preview", q, { param_set_id: "ps-1", source }, h);
      expect(r.status, JSON.stringify(source)).toBe(200);
      expect(problems(r.body, previewSchema, `preview ${String(source.kind)}`)).toEqual([]);
      const body = r.body as { sampling: { kind: string; influence_class: string }; rows: unknown[]; count: number };
      expect(body.sampling.kind).toBe(source.kind);
      expect(["formal", "reference"]).toContain(body.sampling.influence_class);
      expect(body.count).toBe(body.rows.length);
    }
    const detail = power.handle("GET", "/predict-batches/pb-3", q, null, h);
    expect(problems(detail.body, responseSchema("/predict-batches/{batch_id}", "get"), "detail")).toEqual([]);
    expect((detail.body as { sampling: { kind: string } }).sampling.kind).toBe("sobol");
    const list = power.handle("GET", "/studies/s-cushion/predict-batches", q, null, h);
    expect(problems(list.body, responseSchema("/studies/{study_id}/predict-batches", "get"), "list")).toEqual([]);
    expect((list.body as { sampling: { kind: string } }[]).every((b) => b.sampling !== null)).toBe(true);
    const types = power.handle("GET", "/train/doe-types", q, null, h);
    expect(problems(types.body, responseSchema("/train/doe-types", "get"), "doe-types")).toEqual([]);
    expect((types.body as { value: string; recommended: boolean }[]).filter((t) => t.recommended).map((t) => t.value)).toEqual(["TYPE_LATINHYPERCUBE"]);
    const rt = power.handle("GET", "/train-does/doe-1/result-table", q, null, h);
    expect(problems(rt.body, responseSchema("/train-does/{doe_id}/result-table", "get"), "result-table")).toEqual([]);
  });

  it("S18 플랫폼 DOE(V3-S18-10): TD_DOE_GEN platform 생성 → 목록·상세·result-table 모양, /status 설정값·기능", () => {
    const s = new MockServer({ user: "power" });
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    const q = new URLSearchParams();
    const st = s.handle("GET", "/status", q, null, h);
    expect(problems(st.body, responseSchema("/status", "get"), "status")).toEqual([]);
    const sb = st.body as { limits: { configured: Record<string, unknown> }; features: Record<string, { enabled: boolean }> };
    expect(sb.limits.configured).toMatchObject({ doe_generator_default: "platform", doe_platform_parallel_default: 4, doe_platform_max_runs: 500 });
    expect(sb.features.train_doe_platform.enabled).toBe(true);
    // 금지 조합 422(INVALID_PARAMS) 5종, 표본 조합 오류 422(DOE_SAMPLING_INVALID)
    const post = (params: Record<string, unknown>) => s.handle("POST", "/studies/s-cushion/jobs", q, { job_type: "TD_DOE_GEN", params }, h);
    const code = (r: { status: number; body?: unknown }) => `${r.status} ${(r.body as { detail: { code: string } }).detail.code}`;
    const base = { radioss_assem_path: "E:/shared/AI_WORK/cushion/00_inbox/radioss_assem" };
    const samp = { kind: "lhs_opt", count: 12, seed: 1, criterion: "maximin" };
    expect(code(post({ ...base, generator: "platform" }))).toBe("422 INVALID_PARAMS");
    expect(code(post({ ...base, generator: "platform", sampling: samp, doe_label: "LatinHyperCube" }))).toBe("422 INVALID_PARAMS");
    expect(code(post({ ...base, generator: "platform", sampling: samp, options: {} }))).toBe("422 INVALID_PARAMS");
    expect(code(post({ ...base, generator: "hyperstudy", doe_label: "LatinHyperCube", sampling: samp }))).toBe("422 INVALID_PARAMS");
    expect(code(post({ ...base, doe_label: "LatinHyperCube", on_run_failure: "fail" }))).toBe("422 INVALID_PARAMS");
    const bad = post({ ...base, sampling: { kind: "bbd" }, multi_execution: 4 });
    expect(bad.status).toBe(201); // generator 생략 + sampling = platform(G10), 변수 4개라 bbd 가능
    s.finishAll();
    const toomany = post({ ...base, generator: "platform", sampling: { kind: "lhs", count: 501, seed: 1 } });
    expect(code(toomany)).toBe("422 DOE_SAMPLING_INVALID");
    expect((toomany.body as { detail: { problems: { code: string }[] } }).detail.problems.map((x) => x.code)).toEqual(["TOO_MANY_ROWS"]);
    const r = post({ ...base, generator: "platform", sampling: samp, multi_execution: 4, on_run_failure: "continue" });
    expect(r.status).toBe(201);
    s.finishAll();
    const list = s.handle("GET", "/studies/s-cushion/train/does", q, null, h);
    expect(problems(list.body, responseSchema("/studies/{study_id}/train/does", "get"), "does")).toEqual([]);
    const does = list.body as { id: string; generator: string; gen: { total: number; done: number } | null; sampling: { desc_id: string } | null }[];
    const plat = does.filter((d) => d.generator === "platform");
    expect(plat.map((d) => d.sampling?.desc_id).sort()).toEqual(["td_bbd", "td_lhs_opt"]);
    expect(plat.every((d) => d.gen !== null && d.gen.done === d.gen.total)).toBe(true);
    expect(does.find((d) => d.generator === "hyperstudy")!.gen).toBeNull();
    const detail = s.handle("GET", `/train-does/${plat[0].id}`, q, null, h);
    expect(problems(detail.body, responseSchema("/train-does/{doe_id}", "get"), "doe")).toEqual([]);
    const rt = s.handle("GET", `/train-does/${plat[0].id}/result-table`, q, null, h);
    expect(problems(rt.body, responseSchema("/train-does/{doe_id}/result-table", "get"), "result-table")).toEqual([]);
    expect((rt.body as { sampling: { desc_id: string } }).sampling.desc_id).toMatch(/^td_/);
  });

  it("native 3S·4B·① 피처(geometry-engine.md §7.6): props scan 202·GET·PUT → ParamSet, baselines·remap 202·delete·disable, param-map GET·PUT·confirm, train/features, 배치 gen_category", () => {
    const s = new MockServer({ user: "power", geometry: "multi" });
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    const q = new URLSearchParams();
    const call = (m: string, url: string, body: Record<string, unknown> | null = null) => s.handle(m, url, q, body, h);
    const check = (r: { status: number; body?: unknown }, p: string, m: string, status = 200) => {
      expect(r.status).toBe(status);
      expect(problems(r.body, responseSchema(p, m), p)).toEqual([]);
    };
    const reqOk = (p: string, m: string, body: unknown) => {
      const sch = spec.paths[`/physicsai/api${p}`][m].requestBody.content["application/json"].schema;
      expect(problems(body, sch, `${p} body`)).toEqual([]);
    };
    // 3S
    const before = call("GET", "/param-sets/ps-n1/props");
    check(before, "/param-sets/{ps_id}/props", "get");
    expect((before.body as { scanned: boolean }).scanned).toBe(false);
    check(call("POST", "/param-sets/ps-n1/props/scan"), "/param-sets/{ps_id}/props/scan", "post", 202);
    s.finishAll();
    const after = call("GET", "/param-sets/ps-n1/props");
    check(after, "/param-sets/{ps_id}/props", "get");
    expect((after.body as { props: unknown[] }).props.length).toBe(4);
    const putBody = { selected: [{ name: "TRAY_SHELL_T", min: 0.76, max: 0.84 }], include_geometry: true };
    reqOk("/param-sets/{ps_id}/props", "put", putBody);
    const put = call("PUT", "/param-sets/ps-n1/props", putBody);
    check(put, "/param-sets/{ps_id}/props", "put");
    expect((put.body as { parameters: { name: string; source?: string; prop_id?: number }[] }).parameters.find((p) => p.source === "prop")).toMatchObject({ name: "TRAY_SHELL_T", prop_id: 102 });
    expect(call("PUT", "/param-sets/ps-n1/props", { selected: [{ name: "LABEL_SHELL_T" }] }).status).toBe(422);
    // 4B 매칭표
    check(call("GET", "/param-sets/ps-n1/param-map"), "/param-sets/{ps_id}/param-map", "get");
    const dec = { decisions: [{ row_id: "r2", decision: { action: "accept" } }, { row_id: "r1", decision: { action: "split", parts: [{ name: "T_B1", map: { B1: "CUSH_L_THK_1" } }, { name: "T_B2", map: { B2: "CUSH_L_THK_1" } }] } }] };
    reqOk("/param-sets/{ps_id}/param-map", "put", dec);
    const pm = call("PUT", "/param-sets/ps-n1/param-map", dec);
    check(pm, "/param-sets/{ps_id}/param-map", "put");
    expect((pm.body as { variables: string[] }).variables).toEqual(["T_B1", "T_B2", "CUSH_POCKET_D", "CUSH_RIB_T", "CUSH_HOLE_U"]);
    const conflict = call("PUT", "/param-sets/ps-n1/param-map", { decisions: [{ row_id: "r3", decision: { action: "rename", name: "CUSH_HOLE_U", map: { B1: "CUSH_L_RIB_T_2" } } }, { row_id: "r4", decision: { action: "accept" } }] });
    expect(`${conflict.status} ${(conflict.body as { detail: { code: string } }).detail.code}`).toBe("422 PARAM_NAME_CONFLICT");
    const cf = call("POST", "/param-sets/ps-n1/param-map/confirm");
    check(cf, "/param-sets/{ps_id}/param-map/confirm", "post");
    expect((cf.body as { status: string; undecided_count: number }).status).toBe("confirmed");
    const ps = call("GET", "/param-sets/ps-n1");
    check(ps, "/param-sets/{ps_id}", "get");
    expect((ps.body as { param_map_status: string; baselines: { rel: string }[] }).param_map_status).toBe("confirmed");
    // baseline 추가·다시 매칭(202), 2개면 삭제 409 → disable
    const add = { id: "B3", path: "E:/shared/AI_WORK/cushion/00_inbox/rib7_project", choice: { cad: null, radioss_assem: null }, usage: "topology" };
    reqOk("/param-sets/{ps_id}/baselines", "post", add);
    expect(`${call("DELETE", "/param-sets/ps-n1/baselines/B2").status}`).toBe("409");
    expect(`${call("DELETE", "/param-sets/ps-n1/baselines/B1").status}`).toBe("409");
    check(call("POST", "/param-sets/ps-n1/remap", {}), "/param-sets/{ps_id}/remap", "post", 202);
    s.finishAll();
    check(call("POST", "/param-sets/ps-n1/baselines", add), "/param-sets/{ps_id}/baselines", "post", 202);
    s.finishAll();
    check(call("DELETE", "/param-sets/ps-n1/baselines/B3"), "/param-sets/{ps_id}/baselines/{baseline_id}", "delete");
    check(call("POST", "/param-sets/ps-n1/baselines/disable"), "/param-sets/{ps_id}/baselines/disable", "post");
    expect(call("GET", "/param-sets/ps-n1/param-map").status).toBe(409);
    // ① train/features: native 추출 전 409, 후 NativeFeatures
    expect(call("GET", "/studies/s-cushion/train/features").status).toBe(409);
    s.p2.setups["s-cushion"].engine = "native";
    check(call("GET", "/studies/s-cushion/train/features"), "/studies/{study_id}/train/features", "get");
    // 배치 행 gen_category
    Object.assign(s.batches.find((b) => b.id === "pb-2")!.runs[11], { gen_code: "GEOM_TIE_PROJECTION", gen_message: "tie 투영 실패" });
    const pb = call("GET", "/predict-batches/pb-2");
    check(pb, "/predict-batches/{batch_id}", "get");
    expect((pb.body as { rows: { doe_no: number; gen_category: string | null }[] }).rows.find((r) => r.doe_no === 12)!.gen_category).toBe("TIE");
  });

  it("3차 쓰기 응답(V3-S1-5): PATCH study, archive, unarchive, retry", () => {
    const power = new MockServer({ user: "power" });
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    const q = new URLSearchParams();
    const v = power.studies.find((x) => x.id === "s-cushion")!.version;
    const patch = power.handle("PATCH", "/studies/s-cushion", q, { version: v, title: "새 이름" }, h);
    expect(patch.status).toBe(200);
    expect(problems(patch.body, responseSchema("/studies/{study_id}", "patch"), "PATCH study")).toEqual([]);
    expect(power.handle("PATCH", "/studies/s-cushion", q, { version: v, title: "x" }, h).status).toBe(409);
    const un = power.handle("POST", "/studies/s-cushion-old/unarchive", q, null, h);
    expect(un.status).toBe(200);
    expect((un.body as { status: string }).status).toBe("ACTIVE");
    expect(problems(un.body, responseSchema("/studies/{study_id}/unarchive", "post"), "unarchive")).toEqual([]);
    const ar = power.handle("POST", "/studies/s-cushion-old/archive", q, null, h);
    expect(problems(ar.body, responseSchema("/studies/{study_id}/archive", "post"), "archive")).toEqual([]);
    const r = power.handle("POST", "/jobs/j-ds1/retry", q, {}, h); // 본인 실패 작업
    expect(r.status).toBe(201);
    expect(problems(r.body, responseSchema("/jobs/{job_id}/retry", "post"), "retry")).toEqual([]);
    expect((r.body as { retry_of_job_id: string }).retry_of_job_id).toBe("j-ds1");
    expect(new MockServer({ user: "general" }).handle("POST", "/jobs/j-ds1/retry", q, {}, h).status).toBe(403);
    expect(new MockServer({ user: "general" }).handle("POST", "/studies/s-cushion/unarchive", q, null, h).status).toBe(403);
    expect(Object.keys(spec.paths)).toContain("/physicsai/api/studies/{study_id}/unarchive");
    expect(spec.paths["/physicsai/api/studies/{study_id}/unarchive"].post.operationId).toBe("unarchive_study_physicsai_api_studies__study_id__unarchive_post");
  });

  it("3차 S3 용량·정리(V3-S3-10): GET storage(계산 전·후·정리 후), POST 스캔·정리 Job, 정리 중 409", () => {
    const s = new MockServer({ user: "power" });
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    const q = new URLSearchParams();
    s.jobs.forEach((j) => j.study_id === "s-cushion" && !["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state) && (j.state = "CANCELED"));
    const get = () => s.handle("GET", "/studies/s-cushion/storage", q, null, h);
    const sch = responseSchema("/studies/{study_id}/storage", "get");
    expect(problems(get().body, sch, "storage(empty)")).toEqual([]);
    const scan = s.handle("POST", "/studies/s-cushion/jobs", q, { job_type: "STUDY_STORAGE_SCAN", params: {} }, h);
    expect(scan.status).toBe(201);
    expect(problems(scan.body, responseSchema("/studies/{study_id}/jobs", "post"), "scan job")).toEqual([]);
    s.finishAll();
    const rep = get().body as { scan: { job_id: string } };
    expect(rep.scan.job_id).toBe((scan.body as { id: string }).id);
    expect(problems(rep, sch, "storage(scan)")).toEqual([]);
    const cl = s.handle("POST", "/studies/s-cushion/jobs", q, { job_type: "STUDY_CLEANUP", params: { scan_job_id: rep.scan.job_id, categories: ["JOB_LOGS"] } }, h);
    expect(cl.status).toBe(201);
    const busy = s.handle("POST", "/studies/s-cushion/jobs", q, { job_type: "EVALUATE", params: { model_id: "m-1" } }, h);
    expect((busy.body as { detail: { code: string } }).detail.code).toBe("STUDY_CLEANUP_RUNNING");
    s.finishAll();
    expect(problems(get().body, sch, "storage(cleanup)")).toEqual([]);
    expect((get().body as { last_cleanup: { moved_count: number } }).last_cleanup.moved_count).toBe(2);
    expect(spec.paths["/physicsai/api/studies/{study_id}/storage"].get.operationId).toBe("get_study_storage_physicsai_api_studies__study_id__storage_get");
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

  it("3차 §16.5 SCX resolve(D3-58): 202 HpcJob(resolve_pending), 409 HPC_RESOLVE_PENDING·HPC_NOT_UNKNOWN·VERSION_CONFLICT", () => {
    const srv = new MockServer({ user: "admin", hpcConfigured: true, hpcMode: "scx", scxUnknown: true });
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    const q = new URLSearchParams();
    const rows = srv.handle("GET", "/jobs/j-solve/hpc-jobs", q, null, h).body as { id: string; state: string; submission_unknown: boolean; version: number }[];
    const unk = rows.find((r) => r.submission_unknown)!;
    const other = rows.find((r) => !r.submission_unknown)!;
    const url = (id: string) => `/jobs/j-solve/hpc-jobs/${id}/resolve`;
    expect((srv.handle("POST", url(unk.id), q, { action: "recheck", version: unk.version + 1 }, h).body as { detail: { code: string } }).detail.code).toBe("VERSION_CONFLICT");
    const ok = srv.handle("POST", url(unk.id), q, { action: "recheck", version: unk.version }, h);
    expect(ok.status).toBe(202);
    expect((ok.body as { resolve_pending: boolean }).resolve_pending).toBe(true);
    expect(problems(ok.body, responseSchema("/jobs/{job_id}/hpc-jobs/{hpc_job_id}/resolve", "post"), "resolve")).toEqual([]);
    const again = srv.handle("POST", url(unk.id), q, { action: "recheck", version: unk.version + 1 }, h);
    expect((again.body as { detail: { code: string } }).detail.code).toBe("HPC_RESOLVE_PENDING");
    const no = srv.handle("POST", url(other.id), q, { action: "recheck", version: other.version }, h);
    expect(no.status).toBe(409);
    expect((no.body as { detail: { code: string } }).detail.code).toBe("HPC_NOT_UNKNOWN");
  });
});
