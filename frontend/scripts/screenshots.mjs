// mock 모드 화면 스크린샷 — 1920x1080, 3840x2160 (+ 1280 폭 확인용).
// 사용: npm run build:mock && npm run screenshots            (1차 ③④ → screenshots/)
//       npm run build:mock && npm run screenshots:phase2     (2차 ①②⑤·환경 점검 → screenshots/phase2/)
//       npm run build:mock && npm run screenshots:phase3     (3차 ③-5 모델 비교·프로젝트 목록·Study 목록/관리·SPDM 가져오기 → screenshots/phase3/)
//       npm run build:mock && node scripts/screenshots.mjs tone   (대시보드 톤 D3-55·D3-56: ④·④ 일괄 결과·③·상태 서랍, 다크·라이트, 1920·1280
//                                                                 → SHOT_OUT 또는 screenshots/tone/)
//       npm run build:mock && node scripts/screenshots.mjs scx    (S11 SCX D3-58: ① 확인 필요 행·조치, ④ 검증 해석(SCX), 다크·라이트
//                                                                 → SHOT_OUT 또는 screenshots/scx/)
//       npm run build:mock && node scripts/screenshots.mjs designmap  (S12 설계공간 지도 D3-59: ④ 일괄 결과 PLS·평행 좌표, 다크·라이트 1920
//                                                                 → SHOT_OUT 또는 screenshots/designmap/)
//       npm run build:mock && node scripts/screenshots.mjs analysis  (S14 D3-62: ⑤ 결과분석 — 변수–응답·설계공간 지도·영향도, 6버튼 메뉴, 다크·라이트 1920 + 1280·1100 폭
//                                                                 → SHOT_OUT 또는 screenshots/analysis/)
//       npm run build:mock && node scripts/screenshots.mjs sampling  (S15 D3-63: ④ 표본 방식(최적화 LHS 기본·Sobol 이어서 추가·전체 요인 수준), ① DOE 설명, ⑤ 영향도 참고용 문구, 다크·라이트 1920
//                                                                 → SHOT_OUT 또는 screenshots/sampling/)
// 확인: 가로 스크롤 없음, 카드 수(대시보드 톤 2026-10-17 — 행 높이 고정 격자 측정은 없앴다).
// Playwright는 설치하지 않고 환경의 것을 쓴다(PLAYWRIGHT_BROWSERS_PATH, 전역 playwright 모듈).
import { createRequire } from "node:module";
import { spawn, execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const require = createRequire(import.meta.url);

function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_MODULE, "playwright"].filter(Boolean);
  try {
    candidates.push(path.join(execSync("npm root -g").toString().trim(), "playwright"));
  } catch {
    /* 무시 */
  }
  for (const c of candidates) {
    try {
      return require(c);
    } catch {
      /* 다음 */
    }
  }
  throw new Error("playwright 모듈을 찾을 수 없습니다(PLAYWRIGHT_MODULE로 경로 지정).");
}

const { chromium } = loadPlaywright();
const port = 5175;
const server = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"], {
  cwd: root,
  stdio: "pipe",
});
// 서버 준비 대기(HTTP 폴링)
{
  let exited = null;
  server.on("exit", (c) => (exited = c));
  const deadline = Date.now() + 30000;
  for (;;) {
    if (exited !== null) throw new Error(`preview 종료 ${exited}`);
    try {
      const r = await fetch(`http://127.0.0.1:${port}/physicsai/`);
      if (r.ok) break;
    } catch {
      /* 아직 */
    }
    if (Date.now() > deadline) throw new Error("preview 서버 시작 시간 초과");
    await new Promise((r) => setTimeout(r, 300));
  }
}

const phase2 = process.argv.includes("phase2");
const phase3 = process.argv.includes("phase3");
const tone = process.argv.includes("tone");
const scx = process.argv.includes("scx");
const designmap = process.argv.includes("designmap");
const analysis = process.argv.includes("analysis");
const sampling = process.argv.includes("sampling");
const out = sampling ? process.env.SHOT_OUT || path.join(root, "screenshots", "sampling") : analysis ? process.env.SHOT_OUT || path.join(root, "screenshots", "analysis") : designmap ? process.env.SHOT_OUT || path.join(root, "screenshots", "designmap") : scx ? process.env.SHOT_OUT || path.join(root, "screenshots", "scx") : tone ? process.env.SHOT_OUT || path.join(root, "screenshots", "tone") : path.join(root, "screenshots", phase2 ? "phase2" : phase3 ? "phase3" : "");
mkdirSync(out, { recursive: true });
const base = `http://127.0.0.1:${port}/physicsai`;
const S = `${base}/p/p-cushion/s/s-cushion/stage`;
const q = "shot=1&freeze=1&mockUser=admin";
// phase3: ③-5 모델 비교 — 4개 선택(데이터셋 다름·곡선 없음 포함) 후 패널을 화면 위쪽에 맞춘다
async function openCompare(page) {
  for (const n of ["cushion_TNS v1", "cushion_TNS v2", "cushion_TNS v3", "cushion_GNN v1"]) await page.getByLabel(`${n} 비교 선택`).check();
  await page.getByRole("button", { name: /^선택 비교/ }).click();
  await page.waitForSelector(".model-compare .compare-table");
  await page.evaluate(() => document.querySelector(".model-compare")?.scrollIntoView({ block: "start" }));
}
// tone: 일괄 결과에서 DOE 행 하나를 고른다 / 상태 서랍을 연다
async function pickRow(page) {
  await page.locator('[data-testid^="row-"] button.link').nth(2).click();
  await page.waitForTimeout(600);
}
// scx: 확인 필요 행(조치 3개)을 화면 가운데로
async function showUnknown(page) {
  await page.waitForSelector('[data-testid="hpc-resolve"]', { timeout: 15000 });
  await page.evaluate(() => document.querySelector('[data-testid="hpc-resolve"]')?.scrollIntoView({ block: "center" }));
}
// designmap: 그래프 카드 "설계공간 지도" 탭 → (평행 좌표) → DOE 하나 고르고 카드를 화면에 맞춘다
async function openMap(page, method) {
  await page.getByRole("tab", { name: "설계공간 지도" }).click();
  await page.waitForSelector('[data-testid="design-map"] svg');
  if (method) await page.getByRole("group", { name: "지도 방법" }).getByRole("button", { name: method }).click();
  await page.locator('[data-testid^="row-"] button.link').nth(2).click();
  await page.evaluate(() => document.querySelector(".batch-plot")?.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(400);
}
// analysis: ⑤ 그래프 카드 탭을 열고 카드를 화면에 맞춘다
const openTab = (name) => async (page) => {
  await page.getByRole("tab", { name }).click();
  await page.waitForTimeout(500);
  await page.evaluate(() => document.querySelector(".analysis-plot")?.scrollIntoView({ block: "center" }));
};
// sampling: ④ 일괄 예측(DOE) 설정 카드를 화면에 맞추고 방식을 고른다
const setupCard = (page) => page.evaluate(() => (document.querySelector(".batch-setup")?.scrollIntoView({ block: "start" }), window.scrollBy(0, -90)));
async function samplingDefault(page) {
  await page.getByRole("button", { name: "조합 만들기" }).click();
  await page.waitForSelector('[data-testid="preview-sampling"]');
  await setupCard(page);
}
async function samplingSobolContinue(page) {
  await page.getByLabel("표본 방식").selectOption("sobol");
  await page.getByRole("checkbox", { name: "이전 Sobol 배치에 이어서 추가" }).check();
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "조합 만들기" }).click();
  await page.waitForSelector('[data-testid="preview-note"]');
  await setupCard(page);
}
async function samplingFullfact(page) {
  await page.getByLabel("표본 방식").selectOption("fullfact");
  await page.getByLabel("RIB_N 수준").fill("2");
  await page.getByRole("button", { name: "조합 만들기" }).click();
  await page.waitForSelector('[data-testid="preview-sampling"]');
  await setupCard(page);
}
async function doeCard(page) {
  await page.waitForSelector('[data-testid="hs-note"]');
  await page.evaluate(() => document.querySelector('[data-testid="hs-note"]')?.scrollIntoView({ block: "end" }));
}
async function openDrawer(page) {
  await page.getByTestId("chip-queue").click();
  await page.waitForSelector('[role="dialog"][aria-modal="true"] .qrow');
}
const shots = sampling
  ? [
      { name: "stage4_sampling_lhsopt", url: `${S}/4?${q}`, wait: ".batch-setup", act: samplingDefault, noFull: true },
      { name: "stage4_sampling_sobol_continue", url: `${S}/4?${q}&batch=sobol`, wait: ".batch-setup", act: samplingSobolContinue, noFull: true },
      { name: "stage4_sampling_fullfact", url: `${S}/4?${q}`, wait: ".batch-setup", act: samplingFullfact, noFull: true },
      { name: "stage1_doe_desc", url: `${S}/1?${q}`, wait: '[data-testid="hs-note"]', act: doeCard, noFull: true },
      { name: "stage_analysis_influence_ref", url: `${S}/analysis?${q}&batch=bbd&source=batch&id=pb-3`, wait: ".analysis-table", act: openTab("영향도"), noFull: true },
    ]
  : analysis
  ? [
      { name: "stage_analysis", url: `${S}/analysis?${q}&source=batch&id=pb-2`, wait: ".analysis-table", act: (p) => p.waitForSelector('[data-testid="plot2d"]') },
      { name: "stage_analysis_map", url: `${S}/analysis?${q}&source=batch&id=pb-2`, wait: ".analysis-table", act: async (p) => (await openTab("설계공간 지도")(p), p.waitForSelector('[data-testid="design-map"] svg')), noFull: true },
      { name: "stage_analysis_influence", url: `${S}/analysis?${q}&source=batch&id=pb-2`, wait: ".analysis-table", act: openTab("영향도"), noFull: true },
    ]
  : designmap
  ? [
      { name: "stage4_batch_map_pls", url: `${S}/analysis?${q}&source=batch&id=pb-2`, wait: ".analysis-table", act: (p) => openMap(p, null), noFull: true },
      { name: "stage4_batch_map_pc", url: `${S}/analysis?${q}&source=batch&id=pb-2`, wait: ".analysis-table", act: (p) => openMap(p, "평행 좌표"), noFull: true },
    ]
  : scx
  ? [
      { name: "stage1_scx_unknown", url: `${S}/1?${q}&hpc=scx&scx=unknown`, wait: ".workarea .card", act: showUnknown, noFull: true },
      { name: "stage4_scx", url: `${S}/4?${q}&hpc=scx`, wait: ".workarea .card" },
    ]
  : tone
  ? [
      { name: "stage4", url: `${S}/4?${q}`, wait: ".workarea .card" },
      { name: "stage4_batch", url: `${S}/4/batch/pb-2?${q}`, wait: ".batch-table-card", act: pickRow },
      { name: "stage3", url: `${S}/3?${q}`, wait: ".workarea .card" },
      { name: "stage4_drawer", url: `${S}/4?${q}&batch=running`, wait: ".workarea .card", act: openDrawer, noFull: true },
    ]
  : phase3
  ? [
      { name: "stage3_compare", url: `${S}/3?${q}`, wait: ".workarea .card", act: openCompare, noFull: true },
      { name: "projects", url: `${base}/?${q}`, wait: ".tile-list .cell" },
      { name: "study-list", url: `${base}/p/p-cushion?${q}&demo=1`, wait: ".study-table table" },
      { name: "study-manage", url: `${base}/p/p-cushion/s/s-cushion/manage?${q}`, wait: ".manage-page .card" },
      { name: "import", url: `${base}/import?${q}&spdm_path=${encodeURIComponent("\\\\spdm\\master\\FD-X\\Case_0012\\Scene 03")}&project_id=p-cushion`, wait: ".card" },
    ]
  : phase2
  ? [
      { name: "stage1", url: `${S}/1?${q}&hpc=1`, wait: ".workarea .card" },
      { name: "stage1_pbs-none", url: `${S}/1?${q}`, wait: ".workarea .card" },
      { name: "stage2", url: `${S}/2?${q}`, wait: ".workarea .card" },
      { name: "stage5", url: `${S}/5?${q}`, wait: ".workarea .card" },
      { name: "env-check", url: `${base}/admin/env-check?${q}&warn=1`, wait: ".env-table" },
    ]
  : [
      { name: "stage3", url: `${S}/3?${q}`, wait: ".workarea .card" },
      { name: "stage4", url: `${S}/4?${q}`, wait: ".workarea .card" },
    ];
const sizes = sampling
  ? [{ w: 1920, h: 1080 }]
  : analysis
  ? [
      { w: 1920, h: 1080 },
      { w: 1280, h: 800 },
      { w: 1100, h: 800 },
    ]
  : designmap
  ? [{ w: 1920, h: 1080 }]
  : tone || scx
  ? [
      { w: 1920, h: 1080 },
      { w: 1280, h: 800 },
    ]
  : [
      { w: 1920, h: 1080 },
      { w: 3840, h: 2160 },
      { w: 1280, h: 800 },
    ];
// 테마(대시보드 localStorage 키) — tone은 다크·라이트 둘 다, 나머지는 기본(dark)
const themes = tone || scx || designmap || analysis || sampling ? ["dark", "light"] : [null];

const browser = await chromium.launch();
const report = [];
try {
  for (const s of sizes) for (const theme of themes) {
    const ctx = await browser.newContext({ viewport: { width: s.w, height: s.h }, deviceScaleFactor: 1, locale: "ko-KR" });
    if (theme) await ctx.addInitScript((t) => localStorage.setItem("simdashboard.workspace.theme.v1", t), theme);
    if (sampling) await ctx.addInitScript(() => localStorage.setItem("physicsai.stage4.inputMode", "batch")); // ④ 일괄 예측(DOE)로 연다
    const page = await ctx.newPage();
    for (const shot of shots) {
      await page.goto(shot.url, { waitUntil: "load" });
      await page.waitForSelector(shot.wait, { timeout: 15000 });
      if (shot.act) await shot.act(page);
      await page.waitForTimeout(1200);
      const file = path.join(out, `${shot.name}${theme ? `_${theme}` : ""}_${s.w}x${s.h}.png`);
      await page.screenshot({ path: file, fullPage: false });
      if (s.w === 1920 && !shot.noFull) await page.screenshot({ path: file.replace(".png", "_full.png"), fullPage: true });
      const m = await page.evaluate(() => {
        const cells = [...document.querySelectorAll(".grid > .cell, .grid > .grid-contents > .cell")];
        const cols = document.querySelector(".grid") ? getComputedStyle(document.querySelector(".grid")).gridTemplateColumns.split(" ").length : 0;
        return { scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth, cells: cells.length, cols, theme: document.documentElement.dataset.theme ?? "" };
      });
      report.push({ file: path.relative(root, file), theme: m.theme, hScroll: m.scrollW > m.clientW, cols: m.cols, cells: m.cells });
    }
    await ctx.close();
  }
} finally {
  await browser.close();
  server.kill();
}
console.table(report);
process.exit(report.some((r) => r.hScroll) ? 1 : 0);
