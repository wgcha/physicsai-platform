// npm run dev:mock 전용: window.fetch를 목 서버로 바꾸고 2초마다 작업을 진행시킨다.
// ?mockUser=admin|power|general|anon 으로 사용자 전환(localStorage에 기억), ?hpc=1 이면 PBS 구성됨, ?demo=1 이면 시연 모드,
// ?batch=running 이면 진행 중 일괄 예측 B-003 시드(S9). ?hpc=scx 이면 SCX 게이트웨이(D3-58), &scx=unknown 이면 결과 모름 run 1개.
import { MockServer, createMockFetch } from "./server";
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
  const server = new MockServer({ user: user ?? "admin", hpcConfigured: params.get("hpc") === "1" || params.get("hpc") === "scx", hpcMode: params.get("hpc") === "scx" ? "scx" : undefined, scxUnknown: params.get("scx") === "unknown", predictRuns: params.get("runs") === "history" ? "history" : undefined, femVerify: params.get("fv") === "demo" ? "demo" : undefined, demo: params.get("demo") === "1", batchDemo: ["running", "sobol", "bbd"].includes(params.get("batch") ?? "") ? (params.get("batch") as "running" | "sobol" | "bbd") : undefined, configWarnings: params.get("warn") === "1" ? ["resources.extract_minmax_tcl 미설정(⑤ 비활성)", "commands.response_extract 미설정(①-6 비활성)"] : [] });
  // S16: ?vt=top:video/x-msvideo,iso:video/mp4 — 방향별 영상 content-type(avi 안내 시연)
  for (const kv of (params.get("vt") ?? "").split(",").filter(Boolean)) {
    const [view, ct] = kv.split(":");
    if (view && ct) server.videoTypes[view] = ct;
  }
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
