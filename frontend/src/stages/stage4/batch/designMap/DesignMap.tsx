// ④ B 설계공간 지도(phase3.md §17 S12, D3-59): run마다 변수 벡터(반영값)를 PLS(기본)·PCA로 2차원에 투영하거나 평행 좌표로 펼치고,
// 색 = 고른 값(기본 "선택 커브의 최대값"). 표·커브 겹쳐보기와 같은 선택 모델(selected = doe_no), 커브 계열은 BatchResult와 공유.
// 대표값은 GET /predict-batches/{bid}/design-map(백엔드 계산), 투영은 여기(linalg.ts). 다시 받기는 version(완료 수·상태)이 바뀔 때만.
import { useEffect, useMemo, useState } from "react";
import { errorMessage } from "../../../../api";
import { designMapApi, type DesignMap as DM } from "../../../../api/designMap";
import { colorScale } from "./colormap";
import { Colorbar } from "./Colorbar";
import { buildMapData, METHODS, metricLabel, noteLines, parallelAxes, pickMetric, project, readPrefs, TEXT, writePrefs, type Method } from "./designMapData";
import { ParallelCoords } from "./ParallelCoords";
import { ProjectionPlot } from "./ProjectionPlot";
import "../../../../styles/designMap.css";

export function DesignMap({ batchId, version, selected, onSelect, series, onSeries }: { batchId: string; version: string; selected: number | null; onSelect: (doe: number) => void; series: string | null; onSeries: (s: string) => void }) {
  const [dm, setDm] = useState<DM | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prefs] = useState(readPrefs);
  const [method, setMethod] = useState<Method>(prefs.method ?? "pls");
  const [metricId, setMetricId] = useState<string | undefined>(prefs.metric);
  const [arrows, setArrows] = useState<boolean>(prefs.arrows ?? true);
  useEffect(() => {
    let alive = true;
    designMapApi
      .get(batchId)
      .then((d) => alive && (setDm(d), setError(null)))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [batchId, version]);
  // 저장된 계열이 이 배치에 있으면 공유 계열로(커브 겹쳐보기도 따라감)
  useEffect(() => {
    if (dm && series === null && prefs.series && prefs.series !== dm.series[0] && dm.series.includes(prefs.series)) onSeries(prefs.series);
  }, [dm]);

  const metric = dm ? pickMetric(dm.metrics, metricId) : undefined;
  const curSeries = dm ? (series && dm.series.includes(series) ? series : dm.series[0] ?? null) : null;
  const data = useMemo(() => (dm && metric ? buildMapData(dm, metric.id, metric.needs_series ? curSeries : null) : null), [dm, metric?.id, curSeries]);
  const label = metricLabel(metric);
  const proj = useMemo(() => (data && method !== "pc" ? project(data, method, label) : null), [data, method, label]);
  const axes = useMemo(() => (data && method === "pc" ? parallelAxes(data, label) : []), [data, method, label]);
  useEffect(() => {
    if (dm && metric) writePrefs({ method, metric: metric.id, series: curSeries, arrows });
  }, [dm, method, metric?.id, curSeries, arrows]);

  if (error && !dm) return <p className="error-text small">{error}</p>;
  if (!dm) return <p className="muted small">불러오는 중…</p>;
  if (!metric || !data)
    return (
      <p className="muted small" data-testid="dm-message">
        {TEXT.noMetric}
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
      <p className="muted small dm-notes" data-testid="dm-notes">
        {proj && proj.kind !== "message" && proj.note ? <span data-testid="dm-note">{proj.note}</span> : null}
        {notes.map((t) => (
          <span key={t}>{t}</span>
        ))}
        <span>점 {data.runs.length}개</span>
        <span>{TEXT.footer}</span>
      </p>
    </div>
  );
}
