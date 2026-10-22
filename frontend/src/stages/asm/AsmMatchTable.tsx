// 조립 매칭 표(asm-match.md §3.2): 행 = STEP 바디, 옆 열 = 조립 component(다중 선택 1:N, TETRA4만), 판정·거리(검사 후).
import type { AsmMatch } from "../../api";
import { EXCLUDE_LABEL, addPart, bodySummary, distText, excludeBlock, partChoice, partLabel, removePart, rowVerdict, setExcluded, type Draft } from "../../lib/asmMatch";

const VERDICT: Record<ReturnType<typeof rowVerdict>, { text: string; cls: string }> = {
  none: { text: "—", cls: "muted" },
  need: { text: "검사 필요", cls: "warn-text" },
  pass: { text: "일치", cls: "ok-text" },
  fail: { text: "불일치", cls: "error-text" },
};

export function AsmMatchTable({
  match, draft, onChange, readOnly, usedParams, selected, onSelect, dirty,
}: {
  match: AsmMatch;
  draft: Draft;
  onChange: (d: Draft) => void;
  readOnly: boolean;
  usedParams: string[];
  selected: string | null;
  onSelect: (body: string) => void;
  /** 마지막 검사 뒤 표를 바꿨는가 */
  dirty: boolean;
}) {
  const rec = new Set(match.recommend.flatMap((r) => r.pids));
  const parts = new Map(match.parts.map((p) => [p.pid, p]));
  return (
    <table className="asm-table" aria-label="조립 매칭 표">
      <thead>
        <tr>
          <th>STEP 바디</th>
          <th>조립 component</th>
          <th>판정</th>
          <th>거리</th>
        </tr>
      </thead>
      <tbody>
        {match.bodies.map((b) => {
          const pids = draft.pids[b.body] ?? [];
          const excluded = draft.excluded.includes(b.body);
          const v = VERDICT[rowVerdict(match, b.body, pids, dirty)];
          const cr = match.check?.rows.find((r) => r.body === b.body);
          const block = excludeBlock(b.body, usedParams);
          return (
            <tr key={b.body} className={selected === b.body ? "on" : undefined} onClick={() => onSelect(b.body)} data-testid={`asm-row-${b.body}`}>
              <td>
                <div className="mono">{b.body}</div>
                <div className="muted small">{bodySummary(b)}</div>
              </td>
              <td>
                <div className="asm-chips" data-testid={`asm-chips-${b.body}`}>
                  {pids.map((pid) => (
                    <span key={pid} className="asm-chip">
                      {parts.get(pid) ? partLabel(parts.get(pid)!, rec.has(pid)) : `PART ${pid}`}
                      {!readOnly && (
                        <button type="button" className="link small" aria-label={`${b.body}에서 PART ${pid} 빼기`} onClick={() => onChange(removePart(draft, b.body, pid))}>
                          ×
                        </button>
                      )}
                    </span>
                  ))}
                  {excluded && <span className="muted small">{EXCLUDE_LABEL} — 이 바디는 형상 변경 대상에서 빠집니다</span>}
                </div>
                {!readOnly && (
                  <div className="asm-pick">
                    <select
                      aria-label={`${b.body} component 추가`}
                      value=""
                      disabled={excluded}
                      onChange={(e) => e.target.value && onChange(addPart(draft, b.body, Number(e.target.value)))}
                    >
                      <option value="">+ component</option>
                      {[...match.parts]
                        .sort((x, y) => Number(rec.has(y.pid)) - Number(rec.has(x.pid)) || x.pid - y.pid)
                        .map((p) => {
                          const c = partChoice(p, b.body, draft);
                          return (
                            <option key={p.pid} value={p.pid} disabled={c.disabled} title={c.reason ?? undefined}>
                              {partLabel(p, rec.has(p.pid))}
                              {c.reason ? ` — ${c.reason}` : ""}
                            </option>
                          );
                        })}
                    </select>
                    <label className="check small" title={block ?? undefined}>
                      <input type="checkbox" aria-label={`${b.body} ${EXCLUDE_LABEL}`} checked={excluded} disabled={!!block && !excluded} onChange={(e) => onChange(setExcluded(draft, b.body, e.target.checked))} />
                      {EXCLUDE_LABEL}
                    </label>
                    {block && !excluded && <span className="muted small">{block}</span>}
                  </div>
                )}
              </td>
              <td className={v.cls} data-testid={`asm-verdict-${b.body}`}>
                {v.text}
              </td>
              <td className="small mono" data-testid={`asm-dist-${b.body}`}>
                {cr && rowVerdict(match, b.body, pids, dirty) !== "need" ? distText(cr) : "–"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
