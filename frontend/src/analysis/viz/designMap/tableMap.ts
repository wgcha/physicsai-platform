// S14 결과 표 → 설계공간 지도 자료(phase3.md §19.4·§19.6): 결과 표를 기존 DesignMap(§17.4 모양)으로 바꿔 계산 코드(designMapData·linalg)를 그대로 쓴다.
// 단독 보기: predict 출처는 design-map 원본(§17.2 지표 전체), solver는 응답마다 tbl:<이름> 지표. 겹쳐 보기: 두 표를 한 DesignMap으로 합쳐(같은 축·같은 색 범위 = 합집합) 같은 투영을 적용하고
// 비교 표의 점은 other 표시(선택 불가), 해석(solver)은 hollow(속 빈 원·점선).
import type { DesignMap, DesignMapMetric, DesignMapParameter, DesignMapRun } from "../../../api/designMap";
import { commonResponses } from "../../compare";
import { isFin, isOkState, paramRange, type ResultTable } from "../../resultTable";
import type { MapData } from "./designMapData";

/** 비교 표 run 번호에 더하는 값(합친 표에서 번호가 겹치지 않게, 투영 뒤 원래 번호로 되돌림) */
export const OTHER_BASE = 1_000_000;

export function synthDesignMap(rt: ResultTable): DesignMap {
  const parameters: DesignMapParameter[] = rt.parameters.map((p) => {
    const r = paramRange(rt, p.name) ?? [0, 0];
    return { name: p.name, integer: p.integer, min: r[0], max: r[1] };
  });
  const series: string[] = [];
  for (const row of rt.rows) for (const k of Object.keys(row.curve ?? {})) if (!series.includes(k)) series.push(k);
  const metrics: DesignMapMetric[] = [];
  if (series.length)
    metrics.push(
      { id: "curve:max", label: "커브 최대값", unit: null, needs_series: true },
      { id: "curve:min", label: "커브 최소값", unit: null, needs_series: true },
      { id: "curve:absmax", label: "커브 |최대|", unit: null, needs_series: true },
    );
  for (const r of rt.responses) {
    if (rt.rows.some((x) => isFin(x.responses[r.name]))) metrics.push({ id: `tbl:${r.name}`, label: rt.source === "solver" ? r.name : `${r.name}(결과 표)`, unit: r.unit, needs_series: false });
  }
  const runs: DesignMapRun[] = rt.rows.map((x) => ({
    doe_no: x.no,
    run_key: x.run_id,
    state: isOkState(x.state) ? "SUCCEEDED" : x.state,
    values: Object.fromEntries(rt.parameters.flatMap((p) => (isFin(x.params[p.name]) ? [[p.name, x.params[p.name] as number]] : []))),
    curve: x.curve,
    resp: null,
    tbl: isOkState(x.state) ? x.responses : null,
  }));
  const succ = runs.filter((r) => r.state === "SUCCEEDED").length;
  return { batch_id: rt.origin.id, label: rt.origin.label, status: "DONE", parameters, series, metrics, runs, counts: { total: runs.length, succeeded: succ, no_curve: 0, no_resp: 0, spec_changed: 0 }, reason_text: {} };
}

/** 단독 보기용 DesignMap */
export function designMapOf(rt: ResultTable): DesignMap {
  return rt.designMap ?? synthDesignMap(rt);
}

/** 겹쳐 보기용: 공통 응답(tbl:<이름>)만 색 값으로, 커브 지표 없음. 공통 응답이 없으면 metrics 빈 목록 */
export function mergedDesignMap(a: ResultTable, b: ResultTable): DesignMap {
  const da = synthDesignMap(a);
  const db = synthDesignMap(b);
  const common = new Set(commonResponses(a, b));
  const metrics = da.metrics.filter((m) => m.id.startsWith("tbl:") && common.has(m.id.slice(4)));
  const shift = (r: DesignMapRun): DesignMapRun => ({ ...r, doe_no: r.doe_no + OTHER_BASE });
  return { ...da, series: [], metrics, runs: [...da.runs, ...db.runs.map(shift)], counts: { ...da.counts, total: da.runs.length + db.runs.length } };
}

/** 합친 표로 만든 MapData의 run에 other·hollow 표시를 달고 번호를 되돌린다(계산에는 영향 없음) */
export function tagMerged(data: MapData, hollowBase: boolean, hollowOther: boolean): MapData {
  return {
    ...data,
    runs: data.runs.map((r) => (r.doe_no >= OTHER_BASE ? { ...r, doe_no: r.doe_no - OTHER_BASE, other: true, hollow: hollowOther } : { ...r, hollow: hollowBase })),
  };
}
