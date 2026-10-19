// FEM 검증 "응답" 탭(phase3 §21.3.11): 응답 | 구분(MIN/MAX/판정값) | 예측 | FEM | 차이 | 오차%. 판정값 행 굵게, 오차 큰 순 정렬 선택, CSV 받기, 경고 회색.
import { useState } from "react";
import { errorMessage } from "../../../api";
import { femVerifyApi, type FemCompare, type FemProblem } from "../../../api/femVerify";
import { fmtNum } from "../../../lib/format";
import { compareRows, pctText, sortResponses } from "./verifyRules";

export function ResponseCompareTable({ fid, label, compare, warnings }: { fid: string; label: string; compare: FemCompare; warnings: FemProblem[] }) {
  const [byDiff, setByDiff] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rows = sortResponses(compare.responses, byDiff).flatMap(compareRows);
  const csv = async () => {
    setError(null);
    try {
      const blob = await femVerifyApi.tableCsv(fid);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${label}_responses.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return (
    <div className="fv-section" data-testid="fv-responses">
      <div className="run-action-row">
        {compare.max_abs_diff_pct != null && (
          <span className="small">
            최대 오차 <b data-testid="fv-max-diff">{pctText(compare.max_abs_diff_pct)}</b>
            {compare.worst ? <span className="muted"> ({compare.worst})</span> : null}
          </span>
        )}
        <label className="check small">
          <input type="checkbox" checked={byDiff} onChange={(e) => setByDiff(e.target.checked)} />
          오차 큰 순
        </label>
        <button type="button" className="btn small" onClick={() => void csv()}>
          CSV 받기
        </button>
        {error && <span className="error-text small" role="alert">{error}</span>}
      </div>
      {!rows.length ? (
        <p className="muted small">응답 비교 없음 — 템플릿에 응답 정의가 없습니다.</p>
      ) : (
        <div className="table-wrap">
          <table className="table compact" aria-label="FEM 응답 비교">
            <thead>
              <tr>
                <th>응답</th>
                <th>구분</th>
                <th className="num">예측</th>
                <th className="num">FEM</th>
                <th className="num">차이</th>
                <th className="num">오차%</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className={r.kind === "VALUE" ? "fv-value" : "fv-minmax"} data-testid={`fv-row-${r.key}`}>
                  <td className="mono">{r.kind === "MIN" ? `${r.name}${r.unit ? ` [${r.unit}]` : ""}` : ""}</td>
                  <td className="small">{r.kindText}</td>
                  <td className="num mono">{fmtNum(r.pred)}</td>
                  <td className="num mono">{fmtNum(r.fem)}</td>
                  <td className="num mono">{fmtNum(r.diff)}</td>
                  <td className="num mono">{r.pct == null ? <span className="muted small">{r.note ?? "–"}</span> : pctText(r.pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {warnings.length > 0 && (
        <ul className="fv-notes" data-testid="fv-warnings">
          {warnings.map((w, i) => (
            <li key={i} className="muted small" data-code={w.code}>
              {w.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
