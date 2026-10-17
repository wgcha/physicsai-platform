// ④ B "2 조합 미리보기"(phase3.md §14.8, 시안 03): DOE # ↔ 입력 폴더(run__0000N) ↔ 값. 처음 20행 + "… N개 더", 범위 밖 값 옆 작은 회색 점.
import type { BatchPreview as BP, BatchProblem } from "../../../api";
import { Card } from "../../../components/ui";
import { fmtNum } from "../../../lib/format";

export const PREVIEW_ROWS = 20;
export const OUT_OF_RANGE_TIP = "학습 범위 밖";

export function OutDot({ on }: { on: boolean }) {
  return on ? <span className="oor-dot" title={OUT_OF_RANGE_TIP} aria-label={OUT_OF_RANGE_TIP} /> : null;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
/** sampling.meta.quality → "최소 거리 0.21 · 최대 상관 0.08"(있는 것만) */
export function qualityText(meta: Record<string, unknown> | undefined): string | null {
  const q = meta?.quality as Record<string, unknown> | undefined;
  const d = num(q?.min_dist);
  const c = num(q?.max_abs_corr);
  const parts = [d !== null ? `최소 거리 ${d}` : null, c !== null ? `최대 상관 ${c}` : null].filter((x): x is string => !!x);
  return parts.length ? parts.join(" · ") : null;
}

export function BatchPreview({ preview, names, problems, error }: { preview: BP | null; names: string[]; problems: BatchProblem[]; error: string | null }) {
  const rows = preview?.rows ?? [];
  return (
    <Card
      span={6}
      title="2 조합 미리보기"
      className="batch-preview"
      aside={preview && preview.count > 0 ? <span className="muted small">{preview.count}개 · DOE 번호 = 입력 폴더 run 번호</span> : undefined}
    >
      {error && (
        <p className="error-text small" role="alert">
          {error}
        </p>
      )}
      {problems.length > 0 && (
        <ul className="problems small muted" data-testid="batch-problems">
          {problems.map((p, i) => (
            <li key={i}>{p.row ? `${p.row}행 · ` : ""}{p.message}</li>
          ))}
        </ul>
      )}
      {preview?.sampling && (
        <div className="samp-head small" data-testid="preview-sampling">
          <p>
            <b>
              실제 run {preview.count}개 · {preview.sampling.label}
            </b>
            {qualityText(preview.sampling.meta) && <span className="muted" data-testid="preview-quality"> · {qualityText(preview.sampling.meta)}</span>}
          </p>
          {(preview.notes ?? []).map((n, i) => (
            <p key={i} className="muted" data-testid="preview-note">
              {n.message}
            </p>
          ))}
        </div>
      )}
      {!preview && !error && !problems.length && <p className="muted">조합을 만들면 여기에 DOE 번호·입력 폴더·값이 나옵니다.</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table compact batch-preview-table" aria-label="조합 미리보기">
            <thead>
              <tr>
                <th>DOE #</th>
                <th>입력 폴더</th>
                {names.map((n) => (
                  <th key={n} className="num">
                    {n}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, PREVIEW_ROWS).map((r) => (
                <tr key={r.doe_no}>
                  <td className="strong">{r.doe_no}</td>
                  <td className="mono small">{r.run_key}</td>
                  {names.map((n) => (
                    <td key={n} className="num">
                      {fmtNum(r.applied_values[n] ?? r.values[n])}
                      <OutDot on={r.out_of_range.includes(n)} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > PREVIEW_ROWS && <p className="muted more-rows">… {rows.length - PREVIEW_ROWS}개 더</p>}
        </div>
      )}
    </Card>
  );
}
