// 스위스 격자 디자인 규칙(docs/design/swiss-grid-mockup.html, 2026-10-14) 정적 시험.
// 글자 크기·모서리·그림자 값은 design/(토큰·글자 역할·격자)에만 둔다. 화면 CSS·컴포넌트 TSX는 역할 유틸(.D .T .B .R)·var(--font-*)만 쓴다.
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

describe("디자인 규칙(스위스 격자)", () => {
  it("검사 대상 파일을 찾는다", () => {
    expect(Object.keys(css).length).toBeGreaterThan(5);
    expect(Object.keys(tsx).length).toBeGreaterThan(30);
    expect(Object.keys(design).sort()).toEqual(["../design/fonts.css", "../design/grid.css", "../design/tokens.css", "../design/typography.css"]);
  });

  it("화면 CSS에 임의 font-size·border-radius·box-shadow·숫자 font 단축 속성이 없다", () => {
    expect(hits(css, /font-size\s*:|border-radius\s*:|box-shadow\s*:|\bfont\s*:\s*\d/)).toEqual([]);
  });

  it("컴포넌트 TSX 인라인 스타일에 글자 크기·모서리·그림자가 없다", () => {
    expect(hits(tsx, /fontSize|borderRadius|boxShadow|font-size|border-radius|box-shadow/)).toEqual([]);
  });

  it("CSS에 Google Fonts 등 외부 글꼴 주소가 없다(폐쇄망 번들)", () => {
    expect(hits({ ...css, ...design }, /fonts\.googleapis|fonts\.gstatic|@import\s+url\(\s*["']?https?:/)).toEqual([]);
  });

  it("글자 역할은 4단계(Display 44/48·Title 18/24·Body 15/24·Reference 12/16)만 정의한다", () => {
    const tokens = design["../design/tokens.css"];
    const sizes = [...tokens.matchAll(/--([dtbr])-size:\s*(\d+)px/g)].map((m) => `${m[1]}${m[2]}`);
    expect(sizes).toEqual(["d44", "t18", "b15", "r12"]);
    const lines = [...tokens.matchAll(/--([dtbr])-line:\s*(\d+)px/g)].map((m) => Number(m[2]));
    expect(lines).toEqual([48, 24, 24, 16]);
    expect(lines.every((l) => l % 8 === 0)).toBe(true);
    expect(tokens).toMatch(/--row:\s*176px/);
  });

  it("색 토큰은 라이트·다크(prefers-color-scheme와 data-theme 두 곳) 모두 정의한다", () => {
    const tokens = design["../design/tokens.css"];
    for (const k of ["paper", "cell", "ink", "ink-2", "ink-3", "rule", "rule-soft", "red"]) {
      expect(tokens.match(new RegExp(`--${k}:`, "g"))?.length, k).toBe(3);
    }
    expect(tokens).toMatch(/prefers-color-scheme:\s*dark/);
    expect(tokens).toMatch(/:root\[data-theme="dark"\]/);
  });
});
