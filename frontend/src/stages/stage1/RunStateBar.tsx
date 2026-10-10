import { type TrainDoe, type TrainRunState } from "../../api";

const BAR: { key: string; label: string; states: TrainRunState[] }[] = [
  { key: "gen", label: "생성", states: ["GENERATED"] },
  { key: "sub", label: "제출", states: ["SUBMITTED"] },
  { key: "solved", label: "해석 완료", states: ["SOLVED"] },
  { key: "fail", label: "실패", states: ["SOLVE_FAILED", "COLLECT_FAILED"] },
  { key: "col", label: "회수", states: ["COLLECTED"] },
];

export function RunStateBar({ doe }: { doe: TrainDoe }) {
  const c = doe.run_state_counts;
  const total = Object.values(c).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="runbar-wrap">
      <div className="runbar" role="img" aria-label="run 상태 막대">
        {BAR.map((b) => {
          const n = b.states.reduce((a, s) => a + (c[s] ?? 0), 0);
          return n ? <span key={b.key} className={`runbar-seg ${b.key}`} style={{ flexGrow: n }} title={`${b.label} ${n}`} /> : null;
        })}
      </div>
      <div className="runbar-legend small">
        {BAR.map((b) => {
          const n = b.states.reduce((a, s) => a + (c[s] ?? 0), 0);
          return (
            <span key={b.key} data-testid={`runbar-${b.key}`}>
              <span className={`lg runbar-seg ${b.key}`} /> {b.label} <b>{n}</b>
            </span>
          );
        })}
        <span className="muted">/ {total}</span>
      </div>
    </div>
  );
}

/** PBS 제출 표: run · PBS job · 상태 · 경과 · (전역 관리자) 취소/재제출 */
