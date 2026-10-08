// mock 모드 화면 스크린샷(③, ④) — 1920x1080, 3840x2160 (+ 1280 폭 확인용).
// 사용: npm run build:mock && npm run screenshots
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

const out = path.join(root, "screenshots");
mkdirSync(out, { recursive: true });
const base = `http://127.0.0.1:${port}/physicsai`;
const shots = [
  { name: "stage3", url: `${base}/p/p-cushion/s/s-cushion/stage/3?shot=1&freeze=1&mockUser=admin` },
  { name: "stage4", url: `${base}/p/p-cushion/s/s-cushion/stage/4?shot=1&freeze=1&mockUser=admin` },
];
const sizes = [
  { w: 1920, h: 1080 },
  { w: 3840, h: 2160 },
  { w: 1280, h: 800 },
];

const browser = await chromium.launch();
const report = [];
try {
  for (const s of sizes) {
    const ctx = await browser.newContext({ viewport: { width: s.w, height: s.h }, deviceScaleFactor: 1, locale: "ko-KR" });
    const page = await ctx.newPage();
    for (const shot of shots) {
      await page.goto(shot.url, { waitUntil: "load" });
      await page.waitForSelector(".workarea .card", { timeout: 15000 });
      await page.waitForTimeout(1200);
      const file = path.join(out, `${shot.name}_${s.w}x${s.h}.png`);
      await page.screenshot({ path: file, fullPage: false });
      if (s.w === 1920) await page.screenshot({ path: file.replace(".png", "_full.png"), fullPage: true });
      const m = await page.evaluate(() => ({
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
        panelW: document.querySelector(".rightpanel")?.getBoundingClientRect().width ?? 0,
      }));
      report.push({ file: path.relative(root, file), hScroll: m.scrollW > m.clientW, panelW: Math.round(m.panelW) });
    }
    await ctx.close();
  }
} finally {
  await browser.close();
  server.kill();
}
console.table(report);
process.exit(report.some((r) => r.hScroll) ? 1 : 0);
