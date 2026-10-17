// ⑤ 설계공간 지도(phase3.md §17 S12 → §19 S14 이동): run마다 변수 벡터(반영값)를 PLS(기본)·PCA로 2차원에 투영하거나 평행 좌표로 펼치고,
// 색 = 고른 값(기본 "선택 커브의 최대값", 해석 DOE는 첫 응답). 표·커브 겹쳐보기와 같은 선택 모델(selected = run 번호), 커브 계열은 화면(StageAnalysis)과 공유.
// 입력은 결과 표(analysis/resultTable) — 대표값(커브·RESP)은 ④ 어댑터가 design-map API에서 가져와 표에 실어 둔다. 계산 규칙은 designMapData·linalg 그대로.
// 겹쳐 보기(other): 두 표를 한 DesignMap으로 합쳐 같은 축·색 범위(합집합)로 그린다(tableMap.ts).
import { useEffect, useMemo, useState } from "react";
import { colorScale } from "./colormap";
import { Colorbar } from "./Colorbar";
import { buildMapData, METHODS, metricLabel, noteLines, parallelAxes, pickMetric, project, readPrefs, TEXT, writePrefs, type Method } from "./designMapData";
import { ParallelCoords } from "./ParallelCoords";
import { ProjectionPlot } from "./ProjectionPlot";
import { designMapOf, mergedDesignMap, tagMerged } from "./tableMap";
import { SourceLegend } from "../SourceLegend";
import { NO_COMMON_RESP_TEXT } from "../../compare";
import type { ResultTable } from "../../resultTable";
import "../../../styles/designMap.css";

export function DesignMap({ table, other, selected, onSelect, series, onSeries }: { table: ResultTable; other?: ResultTable | null; selected: number | null; onSelect: (doe: number) => void; series: string | null; onSeries: (s: string) => void }) {
  const [prefs] = useState(readPrefs);
  const [method, setMethod] = useState<Method>(prefs.method ?? "pls");
  const [metricId, setMetricId] = useState<string | undefined>(prefs.metric);
  const [arrows, setArrows] = useState<boolean>(prefs.arrows ?? true);
  const dm = useMemo(() => (other ? mergedDesignMap(table, other) : designMapOf(table)), [table, other]);
  // 저장된 계열이 이 표에 있으면 공유 계열로(커브 겹쳐보기도 따라감)
  useEffect(() => {
    if (series === null && prefs.series && prefs.series !== dm.series[0] && dm.series.includes(prefs.series)) onSeries(prefs.series);
  }, [dm]);

  const metric = pickMetric(dm.metrics, metricId);
  const curSeries = series && dm.series.includes(series) ? series : dm.series[0] ?? null;
  const data = useMemo(() => {
    if (!metric) return null;
    const d = buildMapData(dm, metric.id, metric.needs_series ? curSeries : null);
    return other ? tagMerged(d, table.source === "solver", other.source === "solver") : d;
  }, [dm, metric?.id, curSeries, other, table.source]);
  const label = metricLabel(metric);
  const proj = useMemo(() => (data && method !== "pc" ? project(data, method, label) : null), [data, method, label]);
  const axes = useMemo(() => (data && method === "pc" ? parallelAxes(data, label) : []), [data, method, label]);
  useEffect(() => {
    if (metric) writePrefs({ method, metric: metric.id, series: curSeries, arrows });
  }, [method, metric?.id, curSeries, arrows]);

  if (!metric || !data)
    return (
      <p className="muted small" data-testid="dm-message">
        {other ? NO_COMMON_RESP_TEXT : TEXT.noMetric}
      </p>
    );
  const colorOf = colorScale(data.vmin, data.vmax);
  const oneVar = proj?.kind === "scatter1d" && proj.disableMethods;
  const notes = noteLines(data, method);
  return (
    <div className="design-map" data-testid="design-map">
      <div className="dm-head">
        <div className="seg" role="group" aria-label="지도 방법">
          {METHODS.map((x) => (
            <button key={x.key} type="button" className={method === x.key ? "on" : ""} aria-pressed={method === x.key} disabled={oneVar && x.key !== "pc"} onClick={() => setMethod(x.key)}>
              {x.label}
            </button>
          ))}
        </div>
        <label className="inline-field small">
          색 값
          <select value={metric.id} onChange={(e) => setMetricId(e.target.value)}>
            {dm.metrics.map((x) => (
              <option key={x.id} value={x.id}>
                {metricLabel(x)}
              </option>
            ))}
          </select>
        </label>
        {metric.needs_series && dm.series.length > 1 && (
          <label className="inline-field small">
            커브
            <select value={curSeries ?? ""} onChange={(e) => onSeries(e.target.value)}>
              {dm.series.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        )}
        {method !== "pc" && (
          <label className="inline-field small">
            <input type="checkbox" checked={arrows} onChange={(e) => setArrows(e.target.checked)} />
            변수 화살표
          </label>
        )}
      </div>
      {method === "pc" && !data.runs.length ? (
        <p className="muted small" data-testid="dm-message">
          {TEXT.noRun}
        </p>
      ) : proj?.kind === "message" ? (
        <p className="muted small" data-testid="dm-message">
          {proj.message}
        </p>
      ) : (
        <div className="dm-row">
          {method === "pc" ? (
            <ParallelCoords data={data} axes={axes} colorOf={colorOf} selected={selected} onSelect={onSelect} metric={metric} />
          ) : (
            proj && <ProjectionPlot proj={proj} colorOf={colorOf} showArrows={arrows} selected={selected} onSelect={onSelect} params={dm.parameters} metric={metric} />
          )}
          <Colorbar label={label} min={data.vmin} max={data.vmax} height={method === "pc" ? 200 : 240} />
        </div>
      )}
      {other && <SourceLegend items={[{ label: table.origin.label, hollow: table.source === "solver" }, { label: other.origin.label, hollow: other.source === "solver" }]} />}
      <p className="muted small dm-notes" data-testid="dm-notes">
        {proj && proj.kind !== "message" && proj.note ? <span data-testid="dm-note">{proj.note}</span> : null}
        {notes.map((t) => (
          <span key={t}>{t}</span>
        ))}
        <span>점 {data.runs.length}개</span>
        <span>{other ? `${TEXT.footer} · 색 범위 = 두 표 합집합` : TEXT.footer}</span>
      </p>
    </div>
  );
}
