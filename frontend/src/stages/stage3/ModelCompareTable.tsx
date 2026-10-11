// ③-5 모델 비교: 점수 표(행=지표, 열=모델, 최고 강조) + 메타 표 + 열 머리 Final 지정(phase3.md §4.3)
import { useState, type ReactNode } from "react";
import type { Dataset, Model } from "../../api";
import { fmtNum } from "../../lib/format";
import { LogStatusText } from "./ModelRegisterCard";
import { bestIndices, epochText, evalStatusText, fmtDateTime, loadDirection, metricRows, saveDirection, type Direction } from "./compare";

export interface CompareColumn {
  id: string;
  /** 1~5, CSS `--series-n` */
  color: number;
  model: Model | null;
  fallbackName: string;
  /** 404·조회 실패 문구 */
  problem: string | null;
  dataset: Dataset | null;
  datasetFailed: boolean;
}

const DIR_TEXT: Record<Direction, string> = { lower: "↓ 낮을수록", higher: "↑ 높을수록" };

function ColumnHead({ c, canExec, onSetFinal, actions }: { c: CompareColumn; canExec: boolean; onSetFinal: (id: string) => void; actions: boolean }) {
  const m = c.model;
  const status = m ? evalStatusText(m) : null;
  return (
    <th scope="col" className="cmp-col">
      <span className={`swatch cmp-${c.color}`} aria-hidden="true" />
      <b>{m ? `${m.name} v${m.version}` : c.fallbackName}</b>
      {m?.label && <div className="muted small">{m.label}</div>}
      {c.problem && <div className="error-text small">{c.problem}</div>}
      {actions && status && <div className="muted small">{status}</div>}
      {actions && m && (
        <div className="cmp-final">
          {m.is_final ? (
            <span className="final-badge">Final</span>
          ) : canExec && m.status === "ACTIVE" ? (
            <button type="button" className="btn small ghost" onClick={() => onSetFinal(m.id)}>
              Final 지정
            </button>
          ) : null}
        </div>
      )}
    </th>
  );
}

function datasetText(c: CompareColumn): string {
  const id = c.model?.dataset_id;
  if (!id) return "없음(평가 불가)";
  const short = id.slice(0, 8);
  if (c.dataset) return `${short} 학습 ${c.dataset.train_count ?? "—"} · 평가 ${c.dataset.eval_count ?? "—"}`;
  return c.datasetFailed ? `${short} (조회 실패)` : short;
}

export function ModelCompareTable({ columns, canExec, onSetFinal }: { columns: CompareColumn[]; canExec: boolean; onSetFinal: (id: string) => void }) {
  const rows = metricRows(columns.map((c) => c.model));
  const [dirs, setDirs] = useState<Record<string, Direction>>({});
  const dirOf = (key: string): Direction => dirs[key] ?? loadDirection(key);
  const flip = (key: string) => {
    const next: Direction = dirOf(key) === "lower" ? "higher" : "lower";
    saveDirection(key, next);
    setDirs((d) => ({ ...d, [key]: next }));
  };
  const colName = (c: CompareColumn) => (c.model ? `${c.model.name} v${c.model.version}` : c.fallbackName);
  const meta: [string, (c: CompareColumn) => ReactNode][] = [
    ["등록일", (c) => fmtDateTime(c.model?.registered_at)],
    ["등록자", (c) => c.model?.registered_by_name ?? "—"],
    ["epoch 수", (c) => (c.model ? epochText(c.model) : "—")],
    ["최소 loss epoch", (c) => c.model?.min_loss_epoch ?? "—"],
    ["데이터셋", (c) => (c.model ? datasetText(c) : "—")],
    ["로그 상태", (c) => (c.model ? <LogStatusText m={c.model} /> : "—")],
  ];

  return (
    <div className="compare-tables">
      <div className="table-wrap">
        <table className="table compare-table" aria-label="모델 비교 점수">
          <thead>
            <tr>
              <th scope="col">지표</th>
              {columns.map((c) => (
                <ColumnHead key={c.id} c={c} canExec={canExec} onSetFinal={onSetFinal} actions />
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const dir: Direction = r.kind === "loss" ? "lower" : dirOf(r.key);
              const best = new Set(bestIndices(r.values, dir));
              return (
                <tr key={r.key}>
                  <th scope="row" className="cmp-metric">
                    <span>{r.label}</span>
                    {r.kind === "loss" ? (
                      <span className="muted small dir-fixed">{DIR_TEXT.lower}</span>
                    ) : (
                      <button type="button" className="link small dir-toggle" onClick={() => flip(r.key)} title="좋은 방향 바꾸기" aria-label={`${r.label} 좋은 방향: ${DIR_TEXT[dir]}`}>
                        {DIR_TEXT[dir]}
                      </button>
                    )}
                  </th>
                  {r.values.map((v, i) => {
                    const isBest = best.has(i);
                    const text = v === null ? "—" : fmtNum(v);
                    return (
                      <td key={columns[i].id} className={`num${isBest ? " best" : ""}`} aria-label={`${r.label} ${colName(columns[i])} ${text}${isBest ? " (최고)" : ""}`}>
                        {text}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="table-wrap">
        <table className="table compare-meta" aria-label="모델 메타">
          <thead>
            <tr>
              <th scope="col">항목</th>
              {columns.map((c) => (
                <ColumnHead key={c.id} c={c} canExec={canExec} onSetFinal={onSetFinal} actions={false} />
              ))}
            </tr>
          </thead>
          <tbody>
            {meta.map(([label, get]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                {columns.map((c) => (
                  <td key={c.id} className="small">
                    {get(c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
