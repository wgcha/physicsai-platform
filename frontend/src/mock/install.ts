// npm run dev:mock 전용: window.fetch를 목 서버로 바꾸고 2초마다 작업을 진행시킨다.
// ?mockUser=admin|power|general|anon 으로 사용자 전환(localStorage에 기억), ?hpc=1 이면 PBS 구성됨, ?demo=1 이면 시연 모드,
// ?batch=running 이면 진행 중 일괄 예측 B-003 시드(S9). ?hpc=scx 이면 SCX 게이트웨이(D3-58), &scx=unknown 이면 결과 모름 run 1개.
// ?geom=native|multi 이면 native 세트 ps-n1 시드(multi = baseline B2·매칭표 초안, geometry-engine.md §8).
// ?train=native 이면 ① 학습 설정을 native 추출 결과로(①-2 공칭 3D 뷰 시연, geometry-view.md §6.9).
// ?c3d=hold|fail|expire 이면 결과 3D 컨투어 생성 시연(대기 안내에서 멈춤·결과 실패·첫 프레임 410, geometry-view.md §13.6).
import { MockServer, createMockFetch } from "./server";
import { setGvMode } from "./geomView";
import { nativeTrainParams } from "./geometry";
import { mockSummary, normalizeFilter } from "./extractFilter";
import type { MockUserKey } from "./data";

const KEY = "physicsai.mockUser";

export function installMockFetch() {
  const params = new URLSearchParams(window.location.search);
  let user = params.get("mockUser") as MockUserKey | null;
  try {
    if (user) localStorage.setItem(KEY, user);
    else user = localStorage.getItem(KEY) as MockUserKey | null;
  } catch {
    /* 저장소 없음 */
  }
  const server = new MockServer({ user: user ?? "admin", hpcConfigured: params.get("hpc") === "1" || params.get("hpc") === "scx", hpcMode: params.get("hpc") === "scx" ? "scx" : undefined, scxUnknown: params.get("scx") === "unknown", predictRuns: params.get("runs") === "history" ? "history" : undefined, femVerify: params.get("fv") === "demo" ? "demo" : undefined, geometry: params.get("geom") === "native" || params.get("geom") === "multi" ? (params.get("geom") as "native" | "multi") : undefined, demo: params.get("demo") === "1", batchDemo: ["running", "sobol", "bbd"].includes(params.get("batch") ?? "") ? (params.get("batch") as "running" | "sobol" | "bbd") : undefined, configWarnings: params.get("warn") === "1" ? ["resources.extract_minmax_tcl 미설정(⑤ 비활성)", "commands.response_extract 미설정(①-6 비활성)"] : [] });
  // S16: ?vt=top:video/x-msvideo,iso:video/mp4 — 방향별 영상 content-type(avi 안내 시연)
  for (const kv of (params.get("vt") ?? "").split(",").filter(Boolean)) {
    const [view, ct] = kv.split(":");
    if (view && ct) server.videoTypes[view] = ct;
  }
  if (params.get("train") === "native" && server.p2.setups["s-cushion"]) {
    // ?trainRows=248: 실물 규모(수백 행) 표 시연 — 3D 대응이 없는 가짜 행을 덧붙인다
    const extra = Math.max(0, Math.min(1000, Number(params.get("trainRows")) || 0));
    const parameters = nativeTrainParams();
    for (let i = 0; i < extra; i++) parameters.push({ name: `MOCK_FEAT_${String(i + 1).padStart(3, "0")}`, raw_nominal: "1 mm", nominal: 1, min: 0.9, max: 1.1, use: false, format: "%.4f", unit: "mm", valid: true, problems: [] });
    // ?filter=1: 마지막 사용 추출 조건 + 추출 요약 시연(①-1 미리 채움·①-2 적용 조건 줄)
    const filter = params.get("filter") === "1" ? normalizeFilter({ groups: ["thickness", "position", "fillet"], conditions: { thickness_mm: { min: 2, max: 30 }, face_area_min_mm2: 50, position_min_size_mm: 3, fillet_radius_min_mm: 1 } }).norm : null;
    Object.assign(server.p2.setups["s-cushion"], { engine: "native", parameters, tpl: null, extract_filter: filter, extract_summary: filter ? mockSummary([{ type: "THICKNESS" }, { type: "HOLE_POS_U" }, { type: "FILLET_RADIUS" }], filter) : null });
  }
  const c3d = params.get("c3d");
  if (c3d === "hold" || c3d === "fail" || c3d === "expire") setGvMode(server, { c3d });
  const real = window.fetch.bind(window);
  window.fetch = createMockFetch(server, real);
  const freeze = params.get("freeze") === "1";
  if (!freeze) setInterval(() => server.tick(), 2000);
  (window as unknown as { __physicsaiMock: MockServer }).__physicsaiMock = server;

  if (params.get("shot") !== "1") {
    const box = document.createElement("div");
    box.style.cssText =
      "position:fixed;left:8px;bottom:8px;z-index:9999;font:var(--font-r);background:var(--color-surface-raised);color:var(--color-text);border:1px solid var(--color-border);border-radius:var(--radius-md);padding:4px 8px";
    box.innerHTML = `목 모드 · 사용자 <select aria-label="목 사용자">
      ${["admin", "power", "general", "anon"].map((u) => `<option ${u === server.user ? "selected" : ""}>${u}</option>`).join("")}
    </select>`;
    box.querySelector("select")!.addEventListener("change", (e) => {
      try {
        localStorage.setItem(KEY, (e.target as HTMLSelectElement).value);
      } catch {
        /* 무시 */
      }
      window.location.reload();
    });
    document.addEventListener("DOMContentLoaded", () => document.body.appendChild(box));
    if (document.readyState !== "loading") document.body.appendChild(box);
  }
}
