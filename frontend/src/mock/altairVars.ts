// altair-vars.md 시드: Altair 전체 tpl 템플릿(ps-a1, 변수 정의 편집 가능)과 옛 부분 tpl 템플릿(ps-a2, 읽기 전용 + 재생성 안내).
// 풀 = tpl 선언 전체(사용 3 + 미사용 3: 표 범위 승계 2·범위 모름 1). 변수 GET·PUT·vars 처리는 nativeVars.ts의 공용 목이 한다.
import type { NativeVarPoolRow, ParamSet } from "../api/types";
import { iso } from "./data";
import { seedParamSet } from "./seed";
import type { MockServer } from "./server";

const row = (name: string, nominal: number, unit: string, lo: number, hi: number, o: { integer?: boolean; unset?: boolean; train?: [number, number] } = {}): NativeVarPoolRow =>
  ({
    name, type: null, body: null, nominal, unit, position: false, default_range: { min: lo, max: hi }, feasible: null, ref_locked: false, group: null,
    integer: !!o.integer, range_unset: !!o.unset, train: { min: o.train?.[0] ?? nominal, max: o.train?.[1] ?? nominal },
  }) as NativeVarPoolRow;

export const ALTAIR_POOL: NativeVarPoolRow[] = [
  row("THK_TOP", 0.6, "mm", 0.3, 1.2, { train: [0.3, 1.2] }),
  row("THK_FOAM", 2, "mm", 1, 3, { train: [1, 3] }),
  row("E_FOAM", 8, "MPa", 2, 20),
  row("RIB_N", 4, "", 2, 8, { integer: true, train: [2, 8] }),
  row("FILLET_R", 0.5, "mm", 0.475, 0.525),
  row("HOLE_D", 6, "mm", 6, 6, { unset: true }),
];
const USED = new Set(["THK_TOP", "THK_FOAM", "RIB_N"]);

function altairSet(srv: MockServer, id: string, label: string, scope: "full" | "partial"): ParamSet {
  const base = seedParamSet();
  const fmt = (n: string) => (n === "RIB_N" ? "%3i" : "%.4f");
  const declared = scope === "full" ? ALTAIR_POOL : ALTAIR_POOL.filter((p) => USED.has(p.name));
  const ps: ParamSet = {
    ...base, id, label, is_current: false, source_path: `E:/shared/AI_WORK/cushion_v1/00_inbox/${id}`, registered_at: iso(60 * 2),
    parameters: ALTAIR_POOL.filter((p) => USED.has(p.name)).map((p) => ({ name: p.name, nominal: p.nominal ?? 0, min: p.default_range.min, max: p.default_range.max, unit: p.unit })),
    tpl_params: declared.map((p, i) => ({ var: `var_${i + 1}`, name: p.name, format: fmt(p.name), used: USED.has(p.name), unit: p.unit, table_min: p.range_unset ? null : p.default_range.min, table_max: p.range_unset ? null : p.default_range.max })),
    vars_scope: scope, vars_revision: 0, vars_count: USED.size,
  };
  srv.altairPools.set(id, declared);
  return ps;
}

/** MockOptions.altairVars: ps-a1(full)·ps-a2(partial) 시드(현재 템플릿 아님) */
export function seedAltairVars(srv: MockServer) {
  srv.paramSets.push(altairSet(srv, "ps-a1", "쿠션 altair 전체 tpl", "full"), altairSet(srv, "ps-a2", "쿠션 altair 옛 tpl", "partial"));
}
