import { useEffect, useMemo, useState } from "react";
import { api, type Artifact, type Job, type Optimization, type OptResponse } from "../../api";
import { useArtifactJson } from "../../hooks/useArtifact";
import { CodeLine } from "../../components/ui";
import { Chart } from "../../components/Chart";
import { CsvView } from "../../components/CsvView";
import { JsonTree } from "../../components/JsonTree";
import { fmtBytes, fmtNum, fmtTime, isTerminal } from "../../lib/format";

// ---------------------------------------------------------------- ⑤-4
interface SummaryTable {
  columns: string[];
  rows: unknown[][];
}

/** summary.json(C14): csv_table `{parser, kind, file_rel, columns, rows}`(rows는 문자열 배열) / json_passthrough `{…, data}` */
function toTable(data: unknown): SummaryTable | null {
  const d = data as { columns?: unknown; rows?: unknown };
  if (!d || !Array.isArray(d.columns) || !Array.isArray(d.rows)) return null;
  const columns = d.columns.map(String);
  const rows = d.rows.map((r) => (Array.isArray(r) ? r : columns.map((c) => (r as Record<string, unknown>)?.[c])));
  return { columns, rows };
}

function fileEntries(data: unknown): { rel: string; size: number | null }[] {
  const arr = Array.isArray(data) ? data : Array.isArray((data as { files?: unknown })?.files) ? (data as { files: unknown[] }).files : [];
  return arr.map((f) =>
    typeof f === "string" ? { rel: f, size: null } : { rel: String((f as { rel?: string; path?: string; name?: string }).rel ?? (f as { path?: string }).path ?? (f as { name?: string }).name ?? ""), size: Number((f as { size?: number }).size ?? NaN) || null },
  );
}

/** 설계 이력 차트: 행 번호(설계) × 선택 열, 목적이 MINIMIZE/MAXIMIZE면 최적값 추이 함께 */
function HistoryChart({ table, responses }: { table: SummaryTable; responses: OptResponse[] }) {
  const numericCols = table.columns.filter((_c, i) => i > 0 && table.rows.some((r) => Number.isFinite(Number(r[i]))));
  const objective = responses.find((r) => (r.goal === "MINIMIZE" || r.goal === "MAXIMIZE") && numericCols.includes(r.name));
  const [col, setCol] = useState(objective?.name ?? numericCols[0] ?? "");
  const ci = table.columns.indexOf(col);
  if (ci < 0) return null;
  const goal = responses.find((r) => r.name === col)?.goal;
  const pts: [number, number][] = table.rows.map((r, i) => [i + 1, Number(r[ci])] as [number, number]).filter(([, y]) => Number.isFinite(y));
  const best: [number, number][] = [];
  if (goal === "MINIMIZE" || goal === "MAXIMIZE") {
    let b = goal === "MINIMIZE" ? Infinity : -Infinity;
    for (const [x, y] of pts) {
      b = goal === "MINIMIZE" ? Math.min(b, y) : Math.max(b, y);
      best.push([x, b]);
    }
  }
  return (
    <div className="history">
      <div className="history-head">
        <span className="field-label">설계 이력</span>
        <select value={col} onChange={(e) => setCol(e.target.value)} aria-label="이력 열">
          {numericCols.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        {best.length > 0 && (
          <span className="small muted">
            최적 {fmtNum(best[best.length - 1][1])} ({goal === "MINIMIZE" ? "최소" : "최대"})
          </span>
        )}
      </div>
      <Chart
        height={220}
        aspect={0.3}
        maxHeight={520}
        ariaLabel="설계 이력"
        xLabel="설계"
        yLabel={col}
        lines={best.length ? [{ name: "best", pts: best, className: "chart-line s1" }] : []}
        points={pts.map(([x, y]) => ({ x, y, className: "chart-pt", title: `설계 ${x}: ${y}` }))}
      />
      {best.length > 0 && (
        <div className="legend small">
          <span>
            <span className="lg sample" /> 설계별 값
          </span>
          <span>
            <span className="lg line s1" /> 최적값 추이
          </span>
        </div>
      )}
    </div>
  );
}

export function OptResult({ opt, job }: { opt: Optimization | null; job: Job | null }) {
  const summary = useArtifactJson<unknown>(opt?.summary_status === "PARSED" ? opt.summary_artifact_id : null);
  const fileList = useArtifactJson<unknown>(opt?.file_list_artifact_id);
  const [viewable, setViewable] = useState<Artifact[]>([]);
  const [view, setView] = useState<{ name: string; text: string; csv: boolean } | null>(null);
  const table = useMemo(() => toTable(summary), [summary]);

  useEffect(() => {
    setViewable([]);
    setView(null);
    if (!opt || opt.status !== "DONE") return;
    let alive = true;
    api
      .artifacts(opt.job_id)
      .then((a) => alive && setViewable(a.filter((x) => x.kind === "OPT_FILE")))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [opt?.job_id, opt?.status]);

  const open = async (a: Artifact) => {
    const text = await (await api.artifactBlob(a.id)).text();
    setView({ name: a.file_name, text, csv: /\.csv$/i.test(a.file_name) || a.content_type === "text/csv" });
  };

  if (!opt) return <p className="muted">최적화 결과가 없습니다.</p>;
  const running = opt.status === "RUNNING" || (!!job && !isTerminal(job.state) && job.id === opt.job_id);
  const n = opt.runs_started;
  const progress = opt.approach === "DOE" ? `run ${n ?? 0} 시작` : `run ${n ?? 0} / ${opt.max_designs} 시작`;
  const files = fileEntries(fileList);

  return (
    <div className="opt-result">
      <div className="result-head small" data-testid="opt-progress">
        {opt.approach} {opt.approach === "OPT" ? `· ${opt.opt_method}` : ""} · {opt.model_name} · {fmtTime(opt.created_at)} · {running ? progress : opt.status === "DONE" ? `완료 · ${progress.replace(" 시작", "")}` : "실패"}
      </div>
      {opt.status === "DONE" &&
        (table ? (
          <>
            <HistoryChart table={table} responses={opt.responses} />
            <details className="advanced">
              <summary>요약 표 ({table.rows.length}행)</summary>
              <div className="table-wrap summary-table">
                <table className="table compact" aria-label="결과 요약 표">
                  <thead>
                    <tr>
                      {table.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {table.rows.slice(0, 1000).map((r, i) => (
                      <tr key={i}>
                        {table.columns.map((_, j) => {
                          const v = r[j];
                          const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
                          return (
                            <td key={j} className={Number.isFinite(n) ? "num" : ""}>
                              {Number.isFinite(n) ? fmtNum(n, 5) : String(v ?? "")}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        ) : summary && (summary as { kind?: string }).kind === "json_passthrough" ? (
          <div data-testid="summary-json">
            <div className="field-label">결과 요약 ({String((summary as { file_rel?: string }).file_rel ?? "")})</div>
            <JsonTree data={(summary as { data?: unknown }).data} />
          </div>
        ) : (
          <p className="muted" data-testid="summary-unknown">
            결과 요약 형식 미확인 — 원본 파일 목록을 확인하세요
          </p>
        ))}
      {opt.status === "DONE" && (
        <details className="advanced" open={!table}>
          <summary>원본 파일 목록 ({opt.file_count ?? files.length})</summary>
          <ul className="file-list small">
            {files.map((f) => {
              const a = viewable.find((v) => f.rel.endsWith(v.file_name));
              return (
                <li key={f.rel}>
                  {a ? (
                    <button type="button" className="link mono" onClick={() => void open(a)}>
                      {f.rel}
                    </button>
                  ) : (
                    <span className="mono">{f.rel}</span>
                  )}
                  <span className="muted"> {fmtBytes(f.size)}</span>
                </li>
              );
            })}
          </ul>
          {view && (
            <div className="file-view">
              <div className="field-label">
                {view.name}{" "}
                <button type="button" className="link small" onClick={() => setView(null)}>
                  닫기
                </button>
              </div>
              {view.csv ? <CsvView text={view.text} label={view.name} /> : <pre className="textview">{view.text.slice(0, 200_000)}</pre>}
            </div>
          )}
        </details>
      )}
      <CodeLine text={opt.folder_display_path} />
    </div>
  );
}
