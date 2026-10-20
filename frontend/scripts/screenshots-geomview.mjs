// 형상 3D 뷰·미리보기·결과 3D 컨투어 스크린샷(geometry-view.md §7·§13.6) — 목 서버 + 가상 GLB를 실제 WebGL(SwiftShader)로 렌더.
// 사용: npm run build:mock && node scripts/screenshots-geomview.mjs   → screenshots/geometry/view_*.png (1920×1080, 다크)
// Playwright는 설치하지 않고 환경의 것을 쓴다(PLAYWRIGHT_BROWSERS_PATH, 전역 playwright 모듈 — screenshots.mjs와 같음).
import { createRequire } from "node:module";
import { spawn, execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const require = createRequire(import.meta.url);
function loadPlaywright() {
  const c = [process.env.PLAYWRIGHT_MODULE, "playwright"].filter(Boolean);
  try {
    c.push(path.join(execSync("npm root -g").toString().trim(), "playwright"));
  } catch {
    /* 무시 */
  }
  for (const x of c) {
    try {
      return require(x);
    } catch {
      /* 다음 */
    }
  }
  throw new Error("playwright 모듈을 찾을 수 없습니다(PLAYWRIGHT_MODULE로 경로 지정).");
}
const { chromium } = loadPlaywright();
const port = 5175;
const server = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
for (const deadline = Date.now() + 30000; ; ) {
  try {
    if ((await fetch(`http://127.0.0.1:${port}/physicsai/`)).ok) break;
  } catch {
    /* 아직 */
  }
  if (Date.now() > deadline) throw new Error("preview 서버 시작 시간 초과");
  await new Promise((r) => setTimeout(r, 300));
}

const out = process.env.SHOT_OUT || path.join(root, "screenshots", "geometry");
mkdirSync(out, { recursive: true });
const S = `http://127.0.0.1:${port}/physicsai/p/p-cushion/s/s-cushion/stage`;
const q = "shot=1&freeze=1&mockUser=admin";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const center = (sel) => (p) => p.evaluate((s) => document.querySelector(s)?.scrollIntoView({ block: "center" }), sel);

/** ④ native 세트: 템플릿 ps-n1 고르기 → 템플릿 관리 → 행 선택 */
async function nativeDetail(page, row) {
  await page.locator(".template-card select").first().selectOption("ps-n1");
  await page.getByRole("button", { name: "템플릿 관리" }).click();
  await page.waitForSelector('[data-testid="gv-panel"] canvas', { timeout: 20000 });
  await page.getByRole("table", { name: "형상 피처 표" }).getByText(row, { exact: true }).click();
  await wait(800);
}
async function preview(page, row, value) {
  await nativeDetail(page, row);
  await page.getByLabel(`${row} 미리보기 값`).fill(String(value));
  await page.getByRole("button", { name: "미리보기", exact: true }).click();
  await page.waitForSelector('[data-testid="preview-ok"], [data-testid="preview-fail"]', { timeout: 20000 });
  await wait(1200);
}
async function contour(page, sel) {
  await page.getByRole("button", { name: "3D 컨투어" }).click();
  await page.waitForSelector(sel, { timeout: 20000 });
  await wait(1000);
}

const shots = [
  {
    name: "view_native_detail_3d",
    url: `${S}/4?${q}&geom=native`,
    act: async (p) => (await nativeDetail(p, "CUSH_L_THK_1"), center('[data-testid="gv-panel"]')(p)),
  },
  {
    name: "view_face_pick_choices",
    url: `${S}/4?${q}&geom=native`,
    act: async (p) => {
      await nativeDetail(p, "CUSH_L_HOLE_U_1");
      await center('[data-testid="gv-panel"]')(p);
      // 두께 이동 면 = 포켓 고정 면(윗면) 클릭 → 선택 목록
      const box = await p.locator('[data-testid="gv-panel"] canvas').boundingBox();
      await p.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.42);
      await wait(800);
    },
  },
  {
    name: "view_preview_ok",
    url: `${S}/4?${q}&geom=native`,
    act: async (p) => (await preview(p, "CUSH_L_THK_1", 9), center('[data-testid="preview-panel"]')(p)),
  },
  {
    name: "view_preview_fail",
    url: `${S}/4?${q}&geom=native`,
    act: async (p) => (await preview(p, "CUSH_L_THK_1", 20), center('[data-testid="preview-panel"]')(p)),
  },
  {
    name: "view_stage1_params_3d",
    url: `${S}/1?${q}&train=native`,
    act: async (p) => {
      await p.waitForSelector('[data-testid="gv-panel"] canvas', { timeout: 20000 });
      await p.getByRole("table", { name: "파라미터 표" }).getByText("CUSH_L_POCKET_D_1", { exact: true }).click();
      await wait(800);
      await center('[data-testid="gv-panel"]')(p);
    },
  },
  {
    name: "view_contour_wait",
    url: `${S}/4?${q}&c3d=hold`,
    act: async (p) => (await contour(p, '[data-testid="contour3d-wait"]'), center('[data-testid="contour3d-wait"]')(p)),
  },
  {
    name: "view_contour_viewer",
    url: `${S}/4?${q}`,
    act: async (p) => {
      await contour(p, '[data-testid="contour-viewer"] canvas');
      await p.getByLabel("타임스텝").fill("16");
      await p.getByLabel("변형 배율").selectOption("5");
      await wait(1200);
      await center('[data-testid="contour-viewer"]')(p);
    },
  },
];

const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"] });
const report = [];
try {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, locale: "ko-KR" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("request", (r) => {
    const u = r.url();
    if (!u.startsWith(`http://127.0.0.1:${port}/`) && !u.startsWith("blob:") && !u.startsWith("data:")) errors.push(`외부 요청: ${u}`);
  });
  for (const shot of shots) {
    await page.goto(shot.url, { waitUntil: "load" });
    await page.waitForSelector(".workarea .card", { timeout: 15000 });
    await shot.act(page);
    const gl = await page.evaluate(() => !!document.createElement("canvas").getContext("webgl2"));
    const file = path.join(out, `${shot.name}_1920.png`);
    await page.screenshot({ path: file, fullPage: false });
    report.push({ file: path.relative(root, file), webgl2: gl, canvases: await page.locator("canvas").count() });
  }
  if (errors.length) console.error(errors.join("\n"));
  await ctx.close();
} finally {
  await browser.close();
  server.kill();
}
console.table(report);
