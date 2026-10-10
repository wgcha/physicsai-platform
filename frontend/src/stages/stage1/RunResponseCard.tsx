import { useState } from "react";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { useTrain } from "./TrainContext";

// ---------------------------------------------------------------- ①-6 (선택)
interface RespRow {
  name: string;
  unit: string;
  spec: string;
}

export function RunResponseCard() {
  const { doe } = useTrain();
  const canExec = useCanExecute();
  const rx = useJobRunner("TD_RESP_EXTRACT");
  const [rows, setRows] = useState<RespRow[]>([{ name: "MaxStress", unit: "MPa", spec: "{}" }]);
  const parsed = rows.map((r) => {
    try {
      return { name: r.name.trim(), unit: r.unit.trim(), spec: JSON.parse(r.spec || "{}") as unknown };
    } catch {
      return null;
    }
  });
  const valid = parsed.every((p) => p && /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(p.name));
  return (
    <Card step="①-6" title="run 응답 추출 (선택)" className="optional-card">
      <details className="advanced">
        <summary>열기</summary>
        <div className="advanced-body grid-gap">
          <table className="table compact" aria-label="응답 정의">
            <thead>
              <tr>
                <th>이름</th>
                <th>단위</th>
                <th>spec (JSON)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input className="mono" value={r.name} aria-label="응답 이름" onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                  </td>
                  <td>
                    <input className="unit-input" value={r.unit} aria-label="응답 단위" onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, unit: e.target.value } : x)))} />
                  </td>
                  <td>
                    <input className="mono" value={r.spec} aria-label="spec" onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, spec: e.target.value } : x)))} />
                  </td>
                  <td>
                    <button type="button" className="icon-btn" aria-label="행 삭제" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="btn small ghost" onClick={() => setRows([...rows, { name: "", unit: "", spec: "{}" }])}>
            행 추가
          </button>
          <FeatureGate feature="train_resp">
            {(enabled) => (
              <RunAction
                canExecute={canExec}
                label="run 응답 추출"
                onRun={() => doe && void rx.run({ doe_id: doe.id, responses: parsed })}
                job={rx.job}
                disabled={!enabled || !doe || !rows.length || !valid || !(doe.run_state_counts.COLLECTED > 0)}
                disabledReason={enabled ? "회수된 run과 올바른 응답 정의가 필요합니다" : undefined}
                error={rx.error}
              />
            )}
          </FeatureGate>
          {doe?.has_run_responses && <p className="small">run 응답 표 있음</p>}
        </div>
      </details>
    </Card>
  );
}
