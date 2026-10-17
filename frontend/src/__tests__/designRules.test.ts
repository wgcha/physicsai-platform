// 디자인 규칙(대시보드 톤, 2026-10-17 — 스위스 격자 규칙 대체) 정적 시험.
// 글자 크기·모서리·그림자 값은 design/(토큰·글자 역할·격자)에만 둔다. 화면 CSS는 var(--font-*)·var(--radius-*)·var(--shadow-*)만 쓴다.
// 색은 대시보드(simdashboard theme.css)와 같은 다크·라이트 세트, 본문 글자 대비 4.5:1 이상.
import { describe, expect, it } from "vitest";

const css = import.meta.glob(["../**/*.css", "!../design/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const tsx = import.meta.glob(["../**/*.tsx", "!../design/**", "!../__tests__/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const design = import.meta.glob("../design/*.css", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** 주석을 빼고 규칙 위반 줄을 모은다 */
function hits(files: Record<string, string>, re: RegExp): string[] {
  const out: string[] = [];
  for (const [f, src] of Object.entries(files)) {
    const body = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    body.split("\n").forEach((line, i) => {
      if (re.test(line)) out.push(`${f}:${i + 1}: ${line.trim()}`);
    });
  }
  return out;
}

const tokens = () => design["../design/tokens.css"];

/** 테마 블록 하나에서 --color-* 값 */
function themeColors(theme: "dark" | "light"): Record<string, string> {
  const src = tokens().replace(/\/\*[\s\S]*?\*\//g, "");
  const sel = theme === "dark" ? /:root,\s*:root\[data-theme="dark"\]\s*\{([^}]*)\}/ : /:root\[data-theme="light"\]\s*\{([^}]*)\}/;
  const block = src.match(sel)?.[1] ?? "";
  return Object.fromEntries([...block.matchAll(/--color-([a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

function lum(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string): number {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

describe("디자인 규칙(대시보드 톤)", () => {
  it("검사 대상 파일을 찾는다", () => {
    expect(Object.keys(css).length).toBeGreaterThan(5);
    expect(Object.keys(tsx).length).toBeGreaterThan(30);
    expect(Object.keys(design).sort()).toEqual(["../design/fonts.css", "../design/grid.css", "../design/tokens.css", "../design/typography.css"]);
  });

  it("화면 CSS: font-size·숫자 font 단축 속성 없음, 모서리·그림자는 토큰(var(--radius-*)·var(--shadow-*)·50%)만", () => {
    expect(hits(css, /font-size\s*:|\bfont\s*:\s*\d/)).toEqual([]);
    expect(hits(css, /border-radius\s*:(?!\s*(var\(--radius-[a-z]+\)|50%|0|[0-9.]+px);)/)).toEqual([]);
    // 픽셀 모서리는 막대 끝 둥글림(1~3px)만
    expect(hits(css, /border-radius\s*:\s*([4-9]|\d{2,})px/)).toEqual([]);
    expect(hits(css, /box-shadow\s*:(?!\s*(var\(--shadow-[a-z]+\)|none|inset\s))/)).toEqual([]);
  });

  it("컴포넌트 TSX 인라인 스타일에 글자 크기·모서리·그림자가 없다", () => {
    expect(hits(tsx, /fontSize|borderRadius|boxShadow|font-size|border-radius|box-shadow/)).toEqual([]);
  });

  it("CSS에 Google Fonts·CDN 글꼴 주소가 없다(폐쇄망 번들), 글꼴은 Pretendard(npm) + 대시보드와 같은 스택", () => {
    expect(hits({ ...css, ...design }, /fonts\.googleapis|fonts\.gstatic|cdn\.jsdelivr|@import\s+url\(\s*["']?https?:/)).toEqual([]);
    expect(design["../design/fonts.css"]).toMatch(/@import\s+"pretendard\/dist\/web\/variable\/pretendardvariable-dynamic-subset\.css"/);
    expect(tokens()).toContain(`--sans: "Pretendard Variable", Pretendard, "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", "Segoe UI", sans-serif;`);
    expect(hits({ ...css, ...design }, /IBM Plex/)).toEqual([]);
  });

  it("글자 역할 5단계(Display 24·Title 18·Body 14·Control 13·Reference 12), 모서리 4/8/12, 간격 4~32, 컨트롤 32/38/44, 행 40", () => {
    const t = tokens();
    expect([...t.matchAll(/--([dtbcr])-size:\s*(\d+)px/g)].map((m) => `${m[1]}${m[2]}`)).toEqual(["d24", "t18", "b14", "c13", "r12"]);
    expect([...t.matchAll(/--radius-(sm|md|lg):\s*(\d+)px/g)].map((m) => Number(m[2]))).toEqual([4, 8, 12]);
    expect([...t.matchAll(/--space-\d:\s*(\d+)px/g)].map((m) => Number(m[1]))).toEqual([4, 8, 12, 16, 24, 32]);
    expect([...t.matchAll(/--control-h-(sm|md|lg):\s*(\d+)px/g)].map((m) => Number(m[2]))).toEqual([32, 38, 44]);
    expect(t).toMatch(/--row-h:\s*40px/);
    expect(design["../design/grid.css"]).toMatch(/gap:\s*var\(--gap\)/);
    expect(t).toMatch(/--gap:\s*16px/);
  });

  it("색: 대시보드 다크·라이트 세트를 [data-theme]로 정의(같은 이름, 기본 dark)", () => {
    const dark = themeColors("dark");
    const light = themeColors("light");
    const need = [
      "app-bg", "app-background", "surface-1", "surface-2", "surface-3", "border", "border-strong", "text", "text-strong", "text-muted", "accent",
      "danger", "success", "warning", "danger-surface", "success-surface", "warning-surface", "danger-border", "success-border", "warning-border",
      "focus", "chart-grid", "chart-axis", "chart-series-1", "chart-series-2", "chart-series-3", "chart-series-4", "chart-series-5", "chart-series-target", "shadow", "overlay",
    ];
    for (const k of need) {
      expect(dark[k], `dark ${k}`).toBeTruthy();
      expect(light[k], `light ${k}`).toBeTruthy();
    }
    expect(Object.keys(dark).sort()).toEqual(Object.keys(light).sort());
    // 대시보드 원본 대표값
    expect(dark["app-bg"]).toBe("#07111d");
    expect(dark.accent).toBe("#51d3ff");
    expect(light.accent).toBe("#034ea2");
    expect(light["surface-1"]).toBe("#ffffff");
  });

  it("대비 4.5:1 이상(다크·라이트): 본문·보조 글자·상태색·accent 글자, accent 채움 위 글자", () => {
    for (const theme of ["dark", "light"] as const) {
      const c = themeColors(theme);
      const pairs: [string, string][] = [
        ["text", "surface-1"], ["text", "app-bg"], ["text", "surface-2"], ["text-strong", "surface-1"],
        ["text-muted", "surface-1"], ["text-muted", "app-bg"], ["text-muted", "surface-2"],
        ["accent", "surface-1"], ["accent", "surface-selected"], ["accent", "info-surface"],
        ["danger", "surface-1"], ["danger", "danger-surface"],
        ["success", "surface-1"], ["success", "success-surface"],
        ["warning", "surface-1"], ["warning", "warning-surface"],
        ["text-on-accent", "accent"], ["text", "surface-interactive"],
      ];
      for (const [fg, bg] of pairs) expect(contrast(c[fg], c[bg]), `${theme} ${fg}/${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
