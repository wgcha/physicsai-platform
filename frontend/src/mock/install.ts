// npm run dev:mock 전용: window.fetch를 목 서버로 바꾸고 2초마다 작업을 진행시킨다.
// ?mockUser=admin|power|general|anon 으로 사용자 전환(localStorage에 기억), ?hpc=1 이면 PBS 구성됨, ?demo=1 이면 시연 모드,
// ?batch=running 이면 진행 중 일괄 예측 B-003 시드(S9). ?hpc=scx 이면 SCX 게이트웨이(D3-58), &scx=unknown 이면 결과 모름 run 1개.
// ?geom=native|multi 이면 native 세트 ps-n1 시드(multi = baseline B2·매칭표 초안, geometry-engine.md §8).
// ?train=native 이면 ① 학습 설정을 native 추출 결과로(①-2 공칭 3D 뷰 시연, geometry-view.md §6.9).
// ?altair=vars&cur=ps-a1|ps-a2 이면 Altair 변수 표 시연(전체 tpl·옛 tpl).
// ?queue=demo 이면 GPU·CPU 대기열 시드(job-queues.md), ?queue=legacy 이면 옛 응답(gpu·cpu 없음).
// ?upload=0 이면 업로드 꺼짐(경로 칸에 "내 PC에서 올리기" 탭 없음, 기본 켜짐 — upload-report.md).
// ?c3d=hold|fail|expire 이면 결과 3D 컨투어 생성 시연(대기 안내에서 멈춤·결과 실패·첫 프레임 410, geometry-view.md §13.6).
// ?c3d=jobfail|toolarge|toolarge_comps|toolarge_glb|toolarge_frames = 작업 실패·크기 상한 결과 실패(대체 사유 한 줄, contour3d-field §12).
// ?dp=hold|error|clean 이면 ①-3 DOE 형상 그리드 미리보기 시연(?train=native 와 함께, 진행 중 멈춤·오류 셀·실패 없음, doe-preview.md).
// ?c3=lod|nodisp|v1|large 이면 컨투어 데이터 시나리오(저해상도 메시·변위 없음·schema 1·대형 합성 약 81만 노드 + LOD, contour3d-field).
import { MockServer, createMockFetch } from "./server";
import { setGvMode, type GvMode } from "./geomView";
import { setDpMode } from "./doePreview";
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
  const server = new MockServer({ upload: params.get("upload") !== "0", user: user ?? "admin", hpcConfigured: params.get("hpc") === "1" || params.get("hpc") === "scx", hpcMode: params.get("hpc") === "scx" ? "scx" : undefined, scxUnknown: params.get("scx") === "unknown", predictRuns: params.get("runs") === "history" ? "history" : undefined, femVerify: params.get("fv") === "demo" ? "demo" : undefined, altairVars: params.get("altair") === "vars", geometry: params.get("geom") === "native" || params.get("geom") === "multi" ? (params.get("geom") as "native" | "multi") : undefined, demo: params.get("demo") === "1", queue: params.get("queue") === "demo" || params.get("queue") === "legacy" ? (params.get("queue") as "demo" | "legacy") : undefined, batchDemo: ["running", "sobol", "bbd"].includes(params.get("batch") ?? "") ? (params.get("batch") as "running" | "sobol" | "bbd") : undefined, configWarnings: params.get("warn") === "1" ? ["resources.extract_minmax_tcl 미설정(⑤ 비활성)", "commands.response_extract 미설정(①-6 비활성)"] : [] });
  // ?altair=vars 이면 Altair 전체 tpl(ps-a1)·옛 부분 tpl(ps-a2) 시드, ?cur=<세트 id>로 현재 템플릿 지정(altair-vars.md)
  const cur = params.get("cur");
  if (cur) server.paramSets.forEach((p) => (p.is_current = p.id === cur));
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
  if (c3d && ["hold", "fail", "expire", "jobfail", "toolarge", "toolarge_comps", "toolarge_glb", "toolarge_frames"].includes(c3d)) setGvMode(server, { c3d: c3d as NonNullable<GvMode["c3d"]> });
  const c3 = params.get("c3");
  if (c3 === "lod") setGvMode(server, { c3data: { lod: true } });
  else if (c3 === "nodisp") setGvMode(server, { c3data: { disp: false } });
  else if (c3 === "v1") setGvMode(server, { c3data: { schema: 1 } });
  else if (c3 === "large") setGvMode(server, { c3data: { nx: 900, ny: 900, frames: 8, lod: true } });
  // ?dp=hold|error|clean 이면 DOE 형상 그리드 미리보기 시연(진행 중에서 멈춤·오류 셀 1개·실패 셀 없음, doe-preview.md §7). 기본 = 실패 셀 2·잘림 1 포함 24셀
  const dp = params.get("dp");
  if (dp === "hold") setDpMode(server, { hold: true });
  else if (dp === "error") setDpMode(server, { error: true });
  else if (dp === "clean") setDpMode(server, { clean: true });
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
