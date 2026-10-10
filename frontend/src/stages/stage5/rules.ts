import { type OptResponse } from "../../api";

export type Method = "ARSM" | "GRSM" | "SQP";
/** 원본 GUI:110-114 METHOD_DEFAULTS */
export const METHOD_DEFAULTS: Record<Method, { max_designs: number; dv: number }> = {
  ARSM: { max_designs: 25, dv: 0.001 },
  GRSM: { max_designs: 50, dv: 0.001 },
  SQP: { max_designs: 25, dv: 0.0 },
};

export interface RunSettings {
  approach: "OPT" | "DOE";
  method: Method;
  maxDesigns: string;
  runNominal: boolean;
  studyFolder: string;
  abs: string;
  rel: string;
  dv: string;
  onFailed: "IGNORE" | "TERMINATE";
}

/** 원본 GUI:799-811 사용 가능 규칙 */
export function activeRules(s: Pick<RunSettings, "approach" | "method">) {
  const opt = s.approach === "OPT";
  return { method: opt, absRel: opt && s.method === "ARSM", dv: opt && (s.method === "ARSM" || s.method === "SQP"), onFailed: opt };
}

/** 계약 §6.12: CONSTRAINT가 아니면 bound·value 제거, 소스별 키만 */
export function cleanResponses(rows: OptResponse[]): OptResponse[] {
  return rows.map((r) => {
    const base = { name: r.name, source: r.source, component: r.component, stat: r.stat, goal: r.goal };
    const src = r.source === "H3D" ? { subcase: r.subcase, datatype: r.datatype, layer: r.layer ?? "" } : { request: r.request };
    const cons = r.goal === "CONSTRAINT" ? { bound: r.bound ?? "<=", value: r.value } : {};
    return { ...base, ...src, ...cons } as OptResponse;
  });
}
