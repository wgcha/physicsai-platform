// ④ B 커브 겹쳐보기(phase3.md §14.8): 완료 run의 같은 이름 커브를 한 그래프에 — 모두 흐리게(불투명 0.25), 고른 run만 진하게.
// 상한: run 200개(서버 curve_max_runs, 넘으면 앞쪽만 + truncated), 계열당 점 ≤ max_points(구간 최소·최대 보존 다운샘플). 화면도 같은 상한으로 한 번 더 막는다.
// 계열(name)은 BatchResult가 갖는다(S12 §17.6 — 설계공간 지도의 "커브" 선택과 공유, null = 서버 기본 첫 계열).
import { useEffect, useMemo, useState } from "react";
import { api, type BatchCurves } from "../../../api";
import { Chart } from "../../../components/Chart";
import { downsampleMinMax } from "../../../lib/downsample";

export const CURVE_MAX_RUNS = 200;
export const CURVE_MAX_POINTS = 500;

export function overlayLines(c: BatchCurves | null, selected: number | null) {
  if (!c) return [];
  const series = c.series.slice(0, CURVE_MAX_RUNS);
  // 고른 run을 마지막에 그려 위에 오게
  const ordered = [...series.filter((s) => s.doe_no !== selected), ...series.filter((s) => s.doe_no === selected)];
  return ordered.map((s) => {
    const d = downsampleMinMax(s.x, s.y, CURVE_MAX_POINTS);
    return { name: s.run_key, pts: d.x.map((x, i) => [x, d.y[i]] as [number, number]), className: s.doe_no === selected ? "chart-line overlay on" : "chart-line overlay" };
  });
}

export function CurveOverlay({ batchId, selected, version, name, onName }: { batchId: string; selected: number | null; version: number; name: string | null; onName: (n: string) => void }) {
  const [data, setData] = useState<BatchCurves | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .batchCurves(batchId, { name, max_points: CURVE_MAX_POINTS })
      .then((c) => alive && (setData(c), setError(null)))
      .catch((e) => alive && setError(String(e?.message ?? e)));
    return () => {
      alive = false;
    };
  }, [batchId, name, version]);
  const lines = useMemo(() => overlayLines(data, selected), [data, selected]);
  if (error) return <p className="error-text small">{error}</p>;
  if (!data) return <p className="muted small">불러오는 중…</p>;
  if (!data.series.length) return <p className="muted small">완료된 run의 커브가 아직 없습니다.</p>;
  return (
    <div className="curve-overlay" data-testid="curve-overlay">
      {data.names.length > 1 && (
        <label className="inline-field">
          계열
          <select value={data.name ?? ""} onChange={(e) => onName(e.target.value)}>
            {data.names.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      )}
      <Chart height={220} aspect={0.6} maxHeight={420} ariaLabel={`커브 겹쳐보기: ${data.name ?? ""}`} lines={lines} />
      <p className="muted small">
        run {Math.min(data.series.length, CURVE_MAX_RUNS)}개{data.truncated ? ` — 앞쪽 ${CURVE_MAX_RUNS}개만 표시` : ""}
        {data.downsampled ? " · 점 줄임(구간 최소·최대 보존)" : ""} · 고른 run만 진하게
      </p>
    </div>
  );
}
