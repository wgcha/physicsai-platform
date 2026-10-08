// npm run dev:mock 전용: window.fetch를 목 서버로 바꾸고 2초마다 작업을 진행시킨다.
// ?mockUser=admin|power|general|anon 으로 사용자 전환(localStorage에 기억), ?hpc=1 이면 PBS 구성됨, ?demo=1 이면 시연 모드.
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
  const server = new MockServer({ user: user ?? "admin", hpcConfigured: params.get("hpc") === "1", demo: params.get("demo") === "1" });
  const real = window.fetch.bind(window);
  window.fetch = createMockFetch(server, real);
  const freeze = params.get("freeze") === "1";
  if (!freeze) setInterval(() => server.tick(), 2000);
  (window as unknown as { __physicsaiMock: MockServer }).__physicsaiMock = server;

  if (params.get("shot") !== "1") {
    const box = document.createElement("div");
    box.style.cssText =
      "position:fixed;left:8px;bottom:8px;z-index:9999;font:12px system-ui;background:#fff8e1;border:1px solid #e0c060;border-radius:6px;padding:4px 8px;opacity:.9";
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
