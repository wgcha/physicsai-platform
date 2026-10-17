// ⑤ 영향도 탭(phase3.md §19.6): 색 값(응답) 1개의 PRCC·표준화 회귀계수 표 + |PRCC| 막대 + R² 한 줄. 값만(유의성 없음).
// 비활성 사유(비 LHS 해석 DOE·n 부족 등)는 회색 문구, 출처 (a) 비 LHS 배치는 "참고용" 회색 안내. 부호 불일치·선형 근사 약함은 회색 한 줄(아이콘 없음).
import { fmtNum } from "../../lib/format";
import { influenceFor, MISMATCH_TEXT, REF_ONLY_TEXT, WEAK_R2_TEXT } from "../../analysis/influence";
import type { ResultTable } from "../../analysis/resultTable";

export const UNCOMPUTABLE = "계산 불가";

export function InfluencePanel({ table, resp, title }: { table: ResultTable; resp: string | null; title?: string }) {
  const v = influenceFor(table, resp);
  return (
    <div className="influence" data-testid="influence">
      {title && <div className="strong small">{title}</div>}
      {v.disabled || !v.result ? (
        <p className="muted small" data-testid="influence-off">
          {v.disabled}
        </p>
      ) : (
        <>
          <div className="head-row small">
            <span>
              응답 <b>{resp}</b> · 유효 run {v.result.n}개
            </span>
            <span data-testid="influence-r2">R² {v.result.r2 === null ? "–" : v.result.r2.toFixed(2)}</span>
          </div>
          <div className="table-wrap">
            <table className="table compact" aria-label="영향도">
              <thead>
                <tr>
                  <th>변수</th>
                  <th className="num">PRCC</th>
                  <th className="num">SRC</th>
                  <th>|PRCC|</th>
                </tr>
              </thead>
              <tbody>
                {v.rows.map((r) => (
                  <tr key={r.name} data-testid={`inf-${r.name}`}>
                    <td>{r.name}</td>
                    <td className="num">{r.prcc === null ? <span className="muted">{UNCOMPUTABLE}</span> : r.prcc.toFixed(3)}</td>
                    <td className="num">{r.src === null ? <span className="muted">{UNCOMPUTABLE}</span> : r.src.toFixed(3)}</td>
                    <td>
                      <span className="influence-bar" aria-hidden="true">
                        <i className={r.prcc !== null && r.prcc < 0 ? "neg" : ""} style={{ width: `${Math.min(100, Math.abs(r.prcc ?? 0) * 100)}%` }} />
                      </span>
                      <span className="sr-only">{r.prcc === null ? UNCOMPUTABLE : fmtNum(Math.abs(r.prcc))}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small influence-notes" data-testid="influence-notes">
            {v.weak && <span data-testid="influence-weak">{WEAK_R2_TEXT}</span>}
            {v.mismatch.length > 0 && <span data-testid="influence-mismatch"> {MISMATCH_TEXT(v.mismatch)}</span>}
            {v.refOnly && <span data-testid="influence-ref"> {REF_ONLY_TEXT}</span>}
          </p>
        </>
      )}
    </div>
  );
}
