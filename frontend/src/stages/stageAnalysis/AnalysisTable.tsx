// ⑤ 결과 표 카드(phase3.md §19.7; ④ BatchResult의 결과 표에서 이동): 정렬·행 선택·열 이름의 체크(변수)·동그라미(응답)로 그래프 고르기.
// 선택 모델 selected = run 번호(표·그래프·지도·커브 공유). 파일 위치·경로 복사·단일 예측으로 열기·FEM 검증은 선택한 행으로 시작한다(§19.2 A7).
import { useMemo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Card } from "../../components/ui";
import { fmtNum } from "../../lib/format";
import { isFin, isOkState, type ResultTable, type RtRow } from "../../analysis/resultTable";
import { useFemVerifyButton } from "../stage4/verify/useFemVerifyButton";
import { ROW_STATE_LABEL } from "../stage4/batch/batchTable";

export type SortKey = string; // "doe" | "<응답>:asc|desc"

export const SOLVER_STATE_LABEL: Record<string, string> = {
  GENERATED: "입력 생성",
  SUBMITTED: "해석 제출",
  SOLVED: "해석 완료",
  SOLVE_FAILED: "해석 실패",
  COLLECTED: "수집 완료",
  COLLECT_FAILED: "수집 실패",
  SUCCEEDED: "완료",
  UNKNOWN: "상태 불명",
};
export const stateLabel = (s: string): string => (ROW_STATE_LABEL as Record<string, string>)[s] ?? SOLVER_STATE_LABEL[s] ?? s;
export const stateTone = (s: string): string => (isOkState(s) ? "ok" : /FAILED/.test(s) ? "bad" : s === "RUNNING" || s === "SUBMITTED" || s === "GENERATING" ? "run" : "");

export function sortOptionList(responses: string[], labels: Record<string, string> = {}): { key: SortKey; label: string }[] {
  return [...responses.flatMap((r) => [{ key: `${r}:asc`, label: `${labels[r] ?? r} 낮은 순` }, { key: `${r}:desc`, label: `${labels[r] ?? r} 높은 순` }]), { key: "doe", label: "DOE # 순" }];
}

/** 응답 정렬은 값 없는 행을 뒤로, 같으면 번호 순 */
export function sortRtRows(rows: RtRow[], key: SortKey): RtRow[] {
  const out = [...rows];
  if (key === "doe") return out.sort((a, b) => a.no - b.no);
  const i = key.lastIndexOf(":");
  const name = key.slice(0, i);
  const dir = key.slice(i + 1) === "desc" ? -1 : 1;
  const val = (r: RtRow) => (isFin(r.responses[name]) ? (r.responses[name] as number) : null);
  return out.sort((a, b) => {
    const va = val(a);
    const vb = val(b);
    if (va === null && vb === null) return a.no - b.no;
    if (va === null) return 1;
    if (vb === null) return -1;
    return va === vb ? a.no - b.no : (va - vb) * dir;
  });
}

export function AnalysisTable({ table, sort, onSort, pickVars, onToggleVar, pickResp, onPickResp, selectable, selected, onSelect, openHref, report }: { table: ResultTable; sort: SortKey; onSort: (k: SortKey) => void; pickVars: string[]; onToggleVar: (n: string) => void; pickResp: string | null; onPickResp: (n: string) => void; selectable?: string[]; selected: number | null; onSelect: (no: number) => void; openHref: string | null; report?: ReactNode }) {
  const respNames = table.responses.map((r) => r.name);
  const labelMap = Object.fromEntries(table.responses.filter((r) => r.label).map((r) => [r.name, r.label as string]));
  // §21.3.10: 예측 배치 표에서 고른 행(예측 출처)만 FEM 검증 진입. 해석(DOE) 출처 표는 이미 해석 값이라 대상이 아니다.
  const selRow = table.origin.kind === "predict_batch" ? table.rows.find((r) => r.no === selected) ?? null : null;
  const fem = useFemVerifyButton(selRow ? { kind: "batch_run", batch_id: table.origin.id, doe_no: selRow.no } : null, !!selRow && isOkState(selRow.state));
  const rows = useMemo(() => sortRtRows(table.rows, sort), [table, sort]);
  return (
    <Card
      span={6}
      title={`결과 표 — ${table.origin.label}`}
      className="batch-table-card analysis-table"
      aside={
        <span className="run-action-row">
          {selRow && fem.button}
          {report}
          {openHref && (
            <Link to={openHref} className="small">
              ④에서 열기
            </Link>
          )}
          <label className="inline-field small">
            정렬
            <select value={sort} onChange={(e) => onSort(e.target.value)}>
              {sortOptionList(respNames, labelMap).map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </span>
      }
    >
      {selRow && fem.notes}
      {table.notes.map((n) => (
        <p key={n} className="muted small" data-testid="table-note">
          {n}
        </p>
      ))}
      {!respNames.length && (
        <p className="muted small" data-testid="no-resp">
          {table.source === "predict" ? "응답 추출 미구성" : "응답 없음"}
        </p>
      )}
      <div className="table-wrap">
        <table className="table compact batch-table" aria-label="결과 표">
          <thead>
            <tr>
              <th>DOE #</th>
              <th>폴더</th>
              {table.parameters.map((p) => (
                <th key={p.name} className="num">
                  <label className="th-pick" title="응답 그래프 변수로 쓰기">
                    <input type="checkbox" checked={pickVars.includes(p.name)} onChange={() => onToggleVar(p.name)} />
                    {p.name}
                  </label>
                  {p.unit && <span className="muted"> {p.unit}</span>}
                </th>
              ))}
              {table.responses.map((r) => (
                <th key={r.name} className="num">
                  <label className="th-pick" title={selectable && !selectable.includes(r.name) ? "비교 표에 없는 응답 — 겹쳐 보기에서는 고를 수 없습니다" : "응답 그래프 응답으로 쓰기"}>
                    <input type="radio" name={`plot-resp-${table.origin.id}`} checked={pickResp === r.name} disabled={!!selectable && !selectable.includes(r.name)} onChange={() => onPickResp(r.name)} />
                    {r.label ?? r.name}
                  </label>
                  {r.unit && <span className="muted"> {r.unit}</span>}
                </th>
              ))}
              <th className="num">상태</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const on = r.no === selected;
              return (
                <tr key={r.no} className={`clickable${on ? " selected" : ""}`} onClick={() => onSelect(r.no)} data-testid={`row-${r.no}`}>
                  <td>
                    <button type="button" className={on ? "link strong accent" : "link strong"} aria-pressed={on} aria-label={`DOE #${r.no} 선택`} onClick={(e) => (e.stopPropagation(), onSelect(r.no))}>
                      {r.no}
                    </button>
                  </td>
                  <td className="mono small">{r.run_id}</td>
                  {table.parameters.map((p) => (
                    <td key={p.name} className="num">
                      {fmtNum(r.params[p.name])}
                    </td>
                  ))}
                  {table.responses.map((x) => {
                    const why = r.why?.[x.name];
                    const empty = !isFin(r.responses[x.name]);
                    return (
                      <td key={x.name} className={on ? "num strong" : "num"} title={empty && why ? (table.reasonText?.[why] ?? why) : undefined}>
                        {empty ? <span className="muted">—</span> : fmtNum(r.responses[x.name])}
                        {empty && why === "SPEC_CHANGED" && (
                          <span className="muted small" data-testid={`spec-changed-${r.no}-${x.name}`}>
                            {" "}
                            정의 변경
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td className={`num row-state ${r.state.toLowerCase()}`}>
                    <span className={`pill ${stateTone(r.state)}`}>{stateLabel(r.state)}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        행을 누르면 그래프·지도·커브에서 그 run이 강조됩니다(그래프 점을 눌러도 같습니다). 열 이름의 체크(변수)·동그라미(응답)로 변수–응답 그래프와 영향도의 응답을 고릅니다.
        {table.source === "predict" ? " 값은 AI 예측값(반영값)입니다." : " 값은 해석 결과입니다."}
      </p>
    </Card>
  );
}
