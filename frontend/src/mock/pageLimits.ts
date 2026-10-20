// 목 서버 공통: GET 경로의 query `limit`이 backend/openapi.json의 maximum을 넘으면 실제 서버처럼 422로 거부한다.
// (실제 서버: FastAPI le=… 위반 → RequestValidationError → 422 INVALID_PARAMS. 500으로 호출해도 목에서는 통과해
//  run 목록 422가 화면 시험에서 안 보이던 사고의 재발 방지)
import specJson from "../../../backend/openapi.json";
import { err, type MockResp } from "./route";

type Schema = { maximum?: number; minimum?: number; anyOf?: Schema[] };
type Spec = { paths: Record<string, Record<string, { parameters?: { name: string; in: string; schema?: Schema }[] }>> };

const PREFIX = "/physicsai/api";

interface LimitRule {
  re: RegExp;
  max: number;
  min: number;
}

let rules: LimitRule[] | null = null;

function build(): LimitRule[] {
  const out: LimitRule[] = [];
  for (const [p, ops] of Object.entries((specJson as unknown as Spec).paths)) {
    const lim = ops.get?.parameters?.find((q) => q.in === "query" && q.name === "limit");
    const s = lim?.schema;
    if (!s) continue;
    const bound = s.anyOf?.find((x) => x.maximum !== undefined) ?? s;
    if (bound.maximum === undefined) continue;
    const path = p.startsWith(PREFIX) ? p.slice(PREFIX.length) : p;
    const re = new RegExp("^" + path.split(/\{[^}]*\}/).map((x) => x.replace(/[.*+?^$()|[\]\\]/g, "\\$&")).join("[^/]+") + "$");
    out.push({ re, max: bound.maximum, min: bound.minimum ?? 1 });
  }
  return out;
}

/** 위반이면 422 응답, 아니면 null (path는 /physicsai/api 뒤의 경로) */
export function checkLimit(method: string, path: string, query: URLSearchParams): MockResp | null {
  if (method !== "GET" || !query.has("limit")) return null;
  rules ??= build();
  const rule = rules.find((r) => r.re.test(path));
  if (!rule) return null;
  const v = Number(query.get("limit"));
  if (Number.isInteger(v) && v >= rule.min && v <= rule.max) return null;
  return err(422, "INVALID_PARAMS", "요청 값이 올바르지 않습니다", {
    errors: [{ loc: ["query", "limit"], msg: `limit은 ${rule.min} 이상 ${rule.max} 이하여야 합니다` }],
  });
}
