// phase3.md §18 S13·§22 S17 목(R-F 분할): 지표 값(목 함수)·표본 뽑기·제약·run 추가·전선·최적 run·HV·최적값 갱신.
import type { SoRun } from "../api/surrogateOpt";
import { responseFn } from "./data";
import { nonDominated, recommend, type Sense } from "../stages/stage5/surrogate/pareto";
import { fin } from "./surrogateOptRec";
import type { Cons, SoRec } from "./surrogateOptRec";

export function metricValue(metric: string, v: Record<string, number>): number {
  const r = responseFn(v) as Record<string, number>;
  const m = /^resp:(.+)_(MIN|MAX)$/.exec(metric);
  if (m) return m[2] === "MAX" ? r[m[1]] ?? r.MaxStress : (r[m[1]] ?? r.MaxStress) * -0.02;
  if (metric.startsWith("curve:")) return r.MaxStress * 1.08;
  if (metric.startsWith("perf:")) {
    const name = metric.slice(5);
    if (r[name] != null) return r[name];
    return 28 * (v.THK_TOP ?? 0.6) + 0.9 * (v.E_FOAM ?? 8) + 55 / ((v.THK_FOAM ?? 2) + 0.5);
  }
  return r[metric.slice(4)] ?? r.MaxStress;
}
export const val = (metric: string, v: Record<string, number>) => Number(metricValue(metric, v).toPrecision(6));

export function sample(o: SoRec, rnd: () => number, near?: Record<string, number>, spread = 1): Record<string, number> {
  const v: Record<string, number> = {};
  for (const n of o.settings.names) {
    const [lo, hi] = o.settings.bounds[n];
    let x = near ? near[n] + (rnd() - 0.5) * (hi - lo) * 0.25 * spread : lo + rnd() * (hi - lo);
    x = Math.min(hi, Math.max(lo, x));
    v[n] = o.settings.integer.includes(n) ? Math.round(x) : Number(x.toPrecision(5));
  }
  return v;
}

function consOk(c: Cons, v: number | null): boolean {
  if (v == null) return false;
  if (c.op === "range") return v >= (c.lo ?? -Infinity) && v <= (c.hi ?? Infinity);
  return c.op === "<=" ? v <= (c.value ?? Infinity) : v >= (c.value ?? -Infinity);
}
const feasible = (o: SoRec, cons: (number | null)[]) => o.settings.constraints.every((c, i) => consOk(c, cons[i]));

export function addRun(o: SoRec, iter: number, doe: number, v: Record<string, number>, predicted: number | null, kind: string, fail = false) {
  const s = o.settings;
  const objectives = s.objectives.map((x) => (fail ? null : val(x.metric, v)));
  const cons = s.constraints.map((c) => (fail ? null : val(c.metric, v)));
  const observed = Object.fromEntries(s.observe.map((x) => [x.metric, fail ? null : val(x.metric, v)]));
  o.runs.push({
    iter_no: iter, batch_id: `b-so-${o.id}-${iter}`, batch_label: `B-${String(o.batch_no + iter).padStart(3, "0")}`, doe_no: doe,
    run_key: `run__${String(doe).padStart(5, "0")}`, job_id: fail ? null : `j-so-${o.id}-${iter}-${doe}`, values: v, objective: objectives[0] ?? null, objectives, observed,
    constraints: cons, predicted, feasible: fail ? null : feasible(o, cons), state: fail ? "FAILED" : "SUCCEEDED", kind, on_front: false, reason: null,
  });
}

export const senseOf = (o: SoRec): Sense[] => o.settings.objectives.map((x) => x.sense);
const okRuns = (o: SoRec, upto = Infinity) => o.runs.filter((r) => r.iter_no <= upto && (r.objectives ?? []).length && (r.objectives ?? []).every(fin));

/** 다목적: 만족 유효 run의 비지배 집합 */
export function frontRuns(o: SoRec, upto = Infinity): SoRun[] {
  const pool = okRuns(o, upto).filter((r) => r.feasible);
  const idx = nonDominated(pool.map((r) => r.objectives as number[]), senseOf(o));
  return idx.map((i) => pool[i]);
}

export function bestRun(o: SoRec, upto: number): SoRun | null {
  if (o.settings.mode === "multi") {
    const f = frontRuns(o, upto);
    if (!f.length) return null;
    const rec = recommend(f.map((r) => ({ key: `${r.iter_no}:${r.doe_no}`, f: r.objectives as number[], iter_no: r.iter_no, doe_no: r.doe_no })), senseOf(o), o.settings.weights);
    return rec.index >= 0 ? f[rec.index] : null;
  }
  const s = o.settings.objective.sense === "max" ? -1 : 1;
  const ok_ = o.runs.filter((r) => r.iter_no <= upto && r.objective != null);
  const feas = ok_.filter((r) => r.feasible);
  const pool = feas.length ? feas : ok_;
  return pool.length ? pool.reduce((a, b) => (s * (b.objective as number) < s * (a.objective as number) ? b : a)) : null;
}

/** HV(정규화 틀: 반복 0 자료의 ideal·nadir, 기준점 1.1). 2D 정확, 3D는 고정 격자 근사(목 전용) */
function hvOf(o: SoRec, runs: SoRun[]): number {
  const fr = o.frame;
  if (!fr) return 0;
  const m = fr.ideal.length;
  const pts = runs.map((r) => (r.objectives as number[]).map((x, i) => {
    const q = senseOf(o)[i] === "max" ? -x : x;
    const lo = senseOf(o)[i] === "max" ? -fr.nadir[i] : fr.ideal[i];
    const hi = senseOf(o)[i] === "max" ? -fr.ideal[i] : fr.nadir[i];
    return (q - lo) / Math.max(1e-12, hi - lo);
  })).filter((p) => p.every((x) => x <= 1.1));
  const R = 1.1;
  if (m === 2) {
    const s = [...pts].sort((a, b) => a[0] - b[0]);
    let area = 0;
    let bestY = R;
    let prevX = 0;
    for (const p of s) {
      if (p[1] < bestY) {
        if (prevX) area += (p[0] - prevX) * (R - bestY);
        bestY = p[1];
        prevX = p[0];
      }
    }
    area += prevX ? (R - prevX) * (R - bestY) : 0;
    return Number(area.toFixed(4));
  }
  const N = 14;
  let hit = 0;
  for (let a = 0; a < N; a++) for (let b = 0; b < N; b++) for (let c = 0; c < N; c++) {
    const q = [((a + 0.5) / N) * R, ((b + 0.5) / N) * R, ((c + 0.5) / N) * R];
    if (pts.some((p) => p[0] <= q[0] && p[1] <= q[1] && p[2] <= q[2])) hit++;
  }
  return Number(((hit / N ** 3) * R ** 3).toFixed(4));
}

export function updateBest(o: SoRec, t: number) {
  const it = o.iters.find((x) => x.iter_no === t);
  if (!it) return;
  const b = bestRun(o, t);
  it.best_value = b?.objective ?? null;
  it.best_feasible = b ? !!b.feasible : null;
  if (o.settings.mode === "multi") {
    if (t === 0) {
      const pool = okRuns(o, 0);
      o.frame = {
        ideal: o.settings.objectives.map((x, i) => (x.sense === "max" ? Math.max : Math.min)(...pool.map((r) => r.objectives![i] as number))),
        nadir: o.settings.objectives.map((x, i) => (x.sense === "max" ? Math.min : Math.max)(...pool.map((r) => r.objectives![i] as number))),
      };
    }
    const f = frontRuns(o, t);
    it.hv = hvOf(o, f);
    it.front_size = f.length;
    const prev = o.iters.find((x) => x.iter_no === t - 1);
    it.improvement_rel = t >= 1 && prev?.hv ? (it.hv - prev.hv) / prev.hv : null;
    return;
  }
  const prev = t >= 1 ? bestRun(o, t - 1) : null;
  if (prev && b) {
    const s = o.settings.objective.sense === "max" ? -1 : 1;
    const a = s * (prev.objective as number), c = s * (b.objective as number);
    it.improvement_rel = (a - c) / Math.max(Math.abs(a), 1e-12);
  }
}
