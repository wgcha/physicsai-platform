import { useMemo } from "react";
import type { ParamDef, PredictCheck, SampleRow } from "../../api";
import { fmtNum } from "../../lib/format";
import { Chart } from "../../components/Chart";

/** 학습 샘플 분포 눈금(슬라이더 아래) */
export function SampleTicks({ values, min, max, current }: { values: number[]; min: number; max: number; current: number }) {
  const span = max - min || 1;
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - min) / span) * 100));
  const outside = values.filter((v) => v < min || v > max).length;
  return (
    <div className="ticks" aria-label="학습 샘플 분포">
      <svg width="100%" height="12" preserveAspectRatio="none" viewBox="0 0 100 12">
        {values.map((v, i) => (
          <line key={i} x1={pos(v)} x2={pos(v)} y1={2} y2={11} className="tick" vectorEffect="non-scaling-stroke" />
        ))}
        {Number.isFinite(current) && current >= min && current <= max && (
          <line x1={pos(current)} x2={pos(current)} y1={0} y2={12} className="tick-current" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      {outside > 0 && <span className="muted small">범위 밖 샘플 {outside}</span>}
    </div>
  );
}

export function ParamInputTable({
  params,
  values,
  samples,
  integerNames,
  onChange,
  readOnly,
}: {
  params: ParamDef[];
  values: Record<string, number>;
  samples: SampleRow[];
  integerNames: Set<string>;
  onChange: (name: string, v: number) => void;
  readOnly: boolean;
}) {
  const byParam = useMemo(() => {
    const out: Record<string, number[]> = {};
    for (const p of params) out[p.name] = samples.map((s) => s.values[p.name]).filter((v) => Number.isFinite(v));
    return out;
  }, [params, samples]);

  return (
    <table className="table params" aria-label="파라미터 입력">
      <thead>
        <tr>
          <th>파라미터</th>
          <th>단위</th>
          <th className="num">하한</th>
          <th className="num">공칭</th>
          <th className="num">상한</th>
          <th className="slider-col">입력값 · 학습 샘플 분포</th>
          <th className="num">값</th>
        </tr>
      </thead>
      <tbody>
        {params.map((p) => {
          const v = values[p.name];
          const isInt = integerNames.has(p.name);
          const step = isInt ? 1 : (p.max - p.min) / 200 || 0.01;
          return (
            <tr key={p.name}>
              <td className="mono">
                {p.name}
                {isInt && <span className="int-tag" title="입력 파일에 정수로 반영됩니다(반올림)">정수</span>}
              </td>
              <td className="small">{p.unit ?? ""}</td>
              <td className="num">{fmtNum(p.min)}</td>
              <td className="num">{fmtNum(p.nominal)}</td>
              <td className="num">{fmtNum(p.max)}</td>
              <td className="slider-col">
                <input
                  type="range"
                  min={p.min}
                  max={p.max}
                  step={step}
                  value={Number.isFinite(v) ? Math.max(p.min, Math.min(p.max, v)) : p.nominal}
                  onChange={(e) => onChange(p.name, Number(e.target.value))}
                  disabled={readOnly}
                  aria-label={`${p.name} 슬라이더`}
                />
                <SampleTicks values={byParam[p.name] ?? []} min={p.min} max={p.max} current={v} />
              </td>
              <td className="num">
                <input
                  type="number"
                  className="num-input"
                  value={Number.isFinite(v) ? v : ""}
                  step="any"
                  onChange={(e) => {
                    const n = e.target.value === "" ? NaN : Number(e.target.value);
                    onChange(p.name, n);
                  }}
                  disabled={readOnly}
                  aria-label={`${p.name} 값`}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** §8.8: 경고 배지 없이 작은 참고 문구 한 줄 */
export function RangeNote({ check }: { check: PredictCheck | null }) {
  if (!check) return <p className="range-note muted small">&nbsp;</p>;
  const out = check.out_of_range.length > 0;
  const nearest = check.nearest;
  let text: string;
  if (out) text = `학습 범위 밖${nearest ? ` · 최근접 ${nearest.run_key}` : ""}`;
  else if (nearest) text = `최근접 ${nearest.run_key} (거리 ${nearest.distance.toFixed(2)})`;
  else text = "학습 샘플 없음";
  return (
    <p className="range-note muted small" data-testid="range-note">
      {text}
      {out && <span className="range-names"> ({check.out_of_range.map((o) => o.name).join(", ")})</span>}
    </p>
  );
}

export function RoundingNote({ check }: { check: PredictCheck | null }) {
  const r = check?.rounded.filter((x) => x.value !== x.applied) ?? [];
  if (!r.length) return null;
  return (
    <p className="muted small" data-testid="rounding-note">
      정수 파라미터는 반올림해 반영됩니다: {r.map((x) => `${x.name} ${fmtNum(x.value)} → ${x.applied}`).join(", ")}
    </p>
  );
}

export function ParamScatter({
  params,
  samples,
  values,
  nearestRun,
  xName,
  yName,
  onAxes,
}: {
  params: ParamDef[];
  samples: SampleRow[];
  values: Record<string, number>;
  nearestRun: string | null;
  xName: string;
  yName: string;
  onAxes: (x: string, y: string) => void;
}) {
  const px = params.find((p) => p.name === xName) ?? params[0];
  const py = params.find((p) => p.name === yName) ?? params[1] ?? params[0];
  if (!px || !py) return null;
  const pts = samples
    .filter((s) => Number.isFinite(s.values[px.name]) && Number.isFinite(s.values[py.name]))
    .map((s) => ({
      x: s.values[px.name],
      y: s.values[py.name],
      className: s.run_key === nearestRun ? "chart-pt nearest" : "chart-pt sample",
      r: s.run_key === nearestRun ? 5 : 2.6,
      title: s.run_key,
    }));
  const nearestPts = pts.filter((p) => p.className.includes("nearest"));
  const cur = values[px.name];
  const cury = values[py.name];
  const curPt = Number.isFinite(cur) && Number.isFinite(cury) ? [{ x: cur, y: cury, className: "chart-pt current", r: 6, title: "현재 입력" }] : [];
  const unit = (p: ParamDef) => (p.unit ? ` [${p.unit}]` : "");
  return (
    <div className="scatter">
      <div className="scatter-axes">
        <label className="inline-field">
          X
          <select value={px.name} onChange={(e) => onAxes(e.target.value, py.name)} aria-label="X축 파라미터">
            {params.map((p) => (
              <option key={p.name}>{p.name}</option>
            ))}
          </select>
        </label>
        <label className="inline-field">
          Y
          <select value={py.name} onChange={(e) => onAxes(px.name, e.target.value)} aria-label="Y축 파라미터">
            {params.map((p) => (
              <option key={p.name}>{p.name}</option>
            ))}
          </select>
        </label>
        <span className="legend small">
          <span className="lg sample" /> 학습 샘플 {pts.length}
          <span className="lg nearest" /> 최근접
          <span className="lg current" /> 현재 입력
          <span className="lg band" /> 학습 범위
        </span>
      </div>
      <Chart
        height={300} aspect={0.42} maxHeight={720}
        ariaLabel="파라미터 산점도"
        xLabel={px.name + unit(px)}
        yLabel={py.name + unit(py)}
        band={{ x: [px.min, px.max], y: [py.min, py.max] }}
        points={[...pts.filter((p) => !p.className.includes("nearest")), ...nearestPts, ...curPt]}
      />
    </div>
  );
}
