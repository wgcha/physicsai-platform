// 재발 방지: 서버 list 경로의 limit 상한(openapi query 파라미터 maximum)을 넘는 값을 운영 코드가 보내지 않는지 정적 검사.
// (과거 사고: trainRuns를 limit=500으로 호출 → 서버 le=200 → 422 → run 목록이 비어 '제출할 run이 없습니다')
// 경로 매핑은 src/api/*.ts 의 endpoint 정의(템플릿 문자열) 기준 정규식 — 완벽한 파서가 아니다.
import specJson from "../../../backend/openapi.json";

const API_PREFIX = "/physicsai/api";

type Schema = { maximum?: number; anyOf?: Schema[] };
const spec = specJson as unknown as { paths: Record<string, Record<string, { parameters?: { name: string; in: string; schema?: Schema }[] }>> };

const norm = (p: string) => p.replace(/\?.*$/, "").replace(/\$\{[^}]*\}|\{[^}]*\}/g, "{}");

/** 경로(정규화) → limit maximum (GET만) */
function limitMaxima(): Map<string, number> {
  const m = new Map<string, number>();
  for (const [p, ops] of Object.entries(spec.paths)) {
    const params = ops.get?.parameters ?? [];
    const lim = params.find((q) => q.in === "query" && q.name === "limit");
    if (!lim?.schema) continue;
    const max = lim.schema.maximum ?? lim.schema.anyOf?.find((s) => s.maximum !== undefined)?.maximum;
    if (max !== undefined) m.set(norm(p.startsWith(API_PREFIX) ? p.slice(API_PREFIX.length) : p), max);
  }
  return m;
}

const apiFiles = import.meta.glob("../api/*.ts", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const srcFiles = import.meta.glob(
  ["../**/*.ts", "../**/*.tsx", "!../mock/**", "!../__tests__/**", "!../test/**", "!../api/generated/**"],
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

/** 최상위 쉼표로 분리(괄호·중괄호·꺾쇠·문자열 안은 무시) */
function splitTop(s: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  let q: string | null = null;
  for (const ch of s) {
    if (q) {
      cur += ch;
      if (ch === q) q = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") q = ch;
    if ("([{<".includes(ch)) depth++;
    if (")]}>".includes(ch)) depth--;
    if (ch === "," && depth === 0) {
      out.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

/** open 위치(여는 괄호 다음)부터 짝이 맞는 닫는 괄호 직전까지 */
function balanced(src: string, from: number): string {
  let depth = 1;
  for (let i = from; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")" && --depth === 0) return src.slice(from, i);
  }
  return src.slice(from);
}

interface Endpoint {
  key: string; // obj.name
  path: string; // 정규화 경로
  limitIndex: number; // 위치 인자로 limit을 받는 자리(-1: 없음)
  literals: number[]; // 정의 안의 limit 기본값·리터럴
}

function endpoints(): Endpoint[] {
  const out: Endpoint[] = [];
  for (const [file, src] of Object.entries(apiFiles)) {
    if (/\/(types\w*|index)\.ts$/.test(file)) continue;
    let obj = "";
    let name = "";
    let buf: string[] = [];
    const flush = () => {
      if (!obj || !name) return;
      const text = buf.join("\n");
      const m =
        /\brequestPage\b[^(]*\(\s*([`"][^`"]*[`"])/.exec(text) ?? /\brequest\b[^(]*\(\s*"GET",\s*([`"][^`"]*[`"])/.exec(text);
      if (!m) return;
      const arrow = text.indexOf("=>");
      const head = arrow > 0 ? text.slice(text.indexOf("(") + 1, arrow) : "";
      const params = splitTop(head.replace(/\)\s*$/, ""));
      const limitIndex = params.findIndex((p) => /^limit\b/.test(p));
      const literals = [...text.matchAll(/\blimit\s*(?:=|\?\?|:)\s*(\d+)\b/g)].map((x) => Number(x[1]));
      out.push({ key: `${obj}.${name}`, path: norm(m[1].slice(1, -1)), limitIndex, literals });
    };
    for (const line of src.split("\n")) {
      const o = /^export const (\w+)\s*(?::[^=]+)?=\s*\{/.exec(line);
      if (o) {
        flush();
        obj = o[1];
        name = "";
        buf = [];
        continue;
      }
      const e = /^ {2}(\w+):\s/.exec(line);
      if (e) {
        flush();
        name = e[1];
        buf = [line];
      } else if (/^\};?$/.test(line)) {
        flush();
        obj = "";
        name = "";
      } else buf.push(line);
    }
    flush();
  }
  return out;
}

interface Use {
  where: string;
  path: string;
  value: number;
}

function collect(): { uses: Use[]; maxima: Map<string, number> } {
  const maxima = limitMaxima();
  const eps = endpoints();
  const byKey = new Map(eps.map((e) => [e.key, e]));
  const uses: Use[] = [];
  // 1) endpoint 정의 안의 기본값·리터럴
  for (const e of eps) for (const v of e.literals) uses.push({ where: `endpoint ${e.key}`, path: e.path, value: v });
  // 2) 호출부: obj.name(...{ limit: N|CONST }...) 또는 위치 인자
  for (const [file, src] of Object.entries(srcFiles)) {
    const consts = new Map([...src.matchAll(/\bconst ([A-Z_][A-Z0-9_]*)\s*=\s*(\d+)\b/g)].map((x) => [x[1], Number(x[2])]));
    for (const m of src.matchAll(/\b(\w+)\.(\w+)\(/g)) {
      const ep = byKey.get(`${m[1]}.${m[2]}`);
      if (!ep) continue;
      const args = balanced(src, (m.index ?? 0) + m[0].length);
      const where = `${file.replace("../", "src/")} ${m[1]}.${m[2]}`;
      for (const x of args.matchAll(/\blimit\s*:\s*(\d+|[A-Z_][A-Z0-9_]*)\b/g)) {
        const v = /^\d+$/.test(x[1]) ? Number(x[1]) : consts.get(x[1]);
        if (v !== undefined) uses.push({ where, path: ep.path, value: v });
      }
      if (ep.limitIndex >= 0) {
        const a = splitTop(args)[ep.limitIndex];
        if (a && /^\d+$/.test(a)) uses.push({ where, path: ep.path, value: Number(a) });
      }
    }
  }
  return { uses, maxima };
}

describe("list 경로 limit ≤ openapi maximum (정적)", () => {
  const { uses, maxima } = collect();

  it("검사 대상이 비어 있지 않다(정규식이 깨져 공전하지 않음)", () => {
    expect(maxima.get("/train-does/{}/runs")).toBe(200);
    expect(uses.some((u) => u.where.includes("TrainContext") && u.path === "/train-does/{}/runs")).toBe(true);
    expect(uses.some((u) => u.where === "endpoint api.trainRuns")).toBe(true);
    expect(uses.length).toBeGreaterThanOrEqual(8);
  });

  it("운영 코드가 보내는 limit이 서버 상한 이하다", () => {
    const bad = uses
      .filter((u) => maxima.has(u.path) && u.value > (maxima.get(u.path) as number))
      .map((u) => `${u.where}: ${u.path} limit=${u.value} > maximum ${maxima.get(u.path)}`);
    expect(bad).toEqual([]);
  });

  it("limit을 쓰는 GET 경로는 모두 openapi에 있다(경로 매핑 누락 방지)", () => {
    const missing = [...new Set(uses.map((u) => u.path))].filter((p) => !maxima.has(p));
    expect(missing).toEqual([]);
  });
});
