// S17 ⑥ 내장 최적화 "성능" 표(phase3.md §22.12): 템플릿 성능 정의(H3D·커브)를 보고 편집하고, 행마다 역할(목적·제약·관찰)과 값을 정한다.
// 열(원본 ⑥ ResponseTable 순서): 이름 · 출처 · Subcase · DataType(커브면 계열) · Component · Layer · Stat · 단위 · 역할 · 값 · (재사용) 값 있는 run n/N.
// 정의 편집 = 행 추가·삭제 + "성능 정의 저장(템플릿)"(PUT /param-sets/{id}/responses). 저장 전 행은 역할을 고를 수 없다("저장된 성능만 역할 지정").
import { useEffect, useMemo, useState } from "react";
import { ApiError, api, errorMessage, type ParamSet, type ResponseCandidates, type TemplateResponse } from "../../../api";
import type { SoProblem, SurrogateOptPreview } from "../../../api/surrogateOpt";
import { useStudy } from "../../../app/StudyContext";
import { ResponseAdd } from "../../stage4/ResponseDefs";
import {
  CRITERIA_HELP, isDraftDirty, parseWeight, WEIGHT_HELP, weightsIssue, isObjectiveRole, MULTI_NOTE, NO_ROLE, perfId, perfLabel, perfRows, ROLE_LABEL, ROLES, roleBlocked, roleCounts,
  roleValueIssue, SAVE_FIRST_TEXT, specCells, SRC_LABEL, type Limits, type PerfRow, type Role, type RoleSel, type SaveState,
} from "./perfRules";

interface ViewRow {
  row: PerfRow;
  state: SaveState;
}

export function PerfTable({ ps, canEdit, sels, onSel, weights, onWeight, limits, preview, reuse, problems, seriesHints, onExtract, extractNote, extractBusy }: {
  ps: ParamSet;
  canEdit: boolean;
  sels: Record<string, RoleSel>;
  onSel: (name: string, s: RoleSel) => void;
  weights: Record<string, number>;
  onWeight: (name: string, v: number | undefined) => void;
  limits: Limits;
  preview: SurrogateOptPreview | null;
  reuse: boolean;
  problems: SoProblem[];
  seriesHints: string[];
  onExtract: (batchId: string) => void;
  extractNote: string | null;
  extractBusy: boolean;
}) {
  const { study, reloadParamSets } = useStudy();
  const [draft, setDraft] = useState<TemplateResponse[]>(ps.responses);
  const [cands, setCands] = useState<ResponseCandidates | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => setDraft(ps.responses), [ps]);
  useEffect(() => {
    if (!canEdit) return;
    api.responseCandidates(study.id).then(setCands).catch(() => setCands(null));
  }, [study.id, canEdit]);

  const savedRows = useMemo(() => perfRows(ps.responses), [ps.responses]);
  const draftRows = useMemo(() => perfRows(draft), [draft]);
  const view: ViewRow[] = useMemo(() => {
    const out: ViewRow[] = savedRows.map((row) => {
      const d = draftRows.find((x) => x.name === row.name);
      return { row: d ?? row, state: !d ? "removed" : JSON.stringify(d.spec) === JSON.stringify(row.spec) ? "saved" : "new" };
    });
    for (const d of draftRows) if (!savedRows.some((s) => s.name === d.name)) out.push({ row: d, state: "new" });
    return out;
  }, [savedRows, draftRows]);
  const usable = view.filter((v) => v.state === "saved").map((v) => v.row.name);
  const counts = roleCounts(sels, usable);
  const dirty = isDraftDirty(ps.responses, draft);
  const objNames = usable.filter((n) => isObjectiveRole(sels[n]?.role ?? "none"));
  const info = new Map((preview?.performances ?? []).map((p) => [p.id, p]));

  const remove = (name: string) => {
    setDraft(draft.filter((r) => r.name !== name));
    onSel(name, NO_ROLE);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api.putParamSetResponses(ps.id, { responses: draft.map((r) => ({ name: r.name, unit: r.unit ?? "", spec: r.spec ?? null })) });
      await reloadParamSets();
      setSaved(true);
    } catch (e) {
      const probs = e instanceof ApiError ? (e.detail.problems as { message: string }[] | undefined) : undefined;
      setError([errorMessage(e), ...(probs ?? []).map((p) => p.message)].join(" — "));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="perf-table" data-testid="perf-table">
      <div className="table-wrap">
        <table className="table compact resp-table" aria-label="성능">
          <thead>
            <tr>
              <th>이름</th><th>출처</th><th className="num">Subcase</th><th>DataType · 커브 계열</th><th>Component</th><th>Layer</th><th>Stat</th><th>단위</th>
              <th>역할</th><th>값</th>{reuse && <th className="num">값 있는 run</th>}{canEdit && <th />}
            </tr>
          </thead>
          <tbody>
            {!view.length && (
              <tr><td colSpan={9 + (reuse ? 1 : 0) + (canEdit ? 1 : 0)} className="muted small" data-testid="perf-empty">
                성능 정의가 없습니다{canEdit ? " — 아래에서 H3D 또는 커브 성능을 추가하고 저장하세요" : ""}.
              </td></tr>
            )}
            {view.map(({ row, state }) => {
              const sel = sels[row.name] ?? NO_ROLE;
              const c = specCells(row.spec);
              const issue = state === "saved" ? roleValueIssue(sel) : null;
              const inf = info.get(perfId(row.name));
              const miss = problems.find((p) => p.code === "PERF_MISSING_IN_BATCH" && p.performance === row.name);
              return (
                <tr key={row.name} data-testid={`perf-${row.name}`} className={state === "removed" ? "so-removed" : ""}>
                  <td className="mono" title={perfLabel(row)}>{row.name}</td>
                  <td className="small">{SRC_LABEL[row.source]}</td>
                  <td className="num">{c.subcase || "—"}</td>
                  <td>{c.datatype}</td>
                  <td>{c.component}</td>
                  <td>{c.layer}</td>
                  <td>{c.stat}</td>
                  <td className="small">{row.unit}</td>
                  <td>
                    {state === "saved" ? (
                      <select value={sel.role} aria-label={`${row.name} 역할`} onChange={(e) => onSel(row.name, { ...sel, role: e.target.value as Role })}>
                        {ROLES.map((r) => (
                          <option key={r} value={r} disabled={roleBlocked(r, sel.role, counts, limits)}>{ROLE_LABEL[r]}</option>
                        ))}
                      </select>
                    ) : (
                      <span className="muted small" data-testid={`perf-unsaved-${row.name}`}>{state === "removed" ? "삭제 예정(저장 필요)" : SAVE_FIRST_TEXT}</span>
                    )}
                  </td>
                  <td>
                    {state === "saved" && (sel.role === "le" || sel.role === "ge") && (
                      <input className="num narrow" inputMode="decimal" value={sel.a} aria-label={`${row.name} 값`} onChange={(e) => onSel(row.name, { ...sel, a: e.target.value })} />
                    )}
                    {state === "saved" && sel.role === "range" && (
                      <span className="so-range-inputs">
                        <input className="num narrow" inputMode="decimal" value={sel.a} aria-label={`${row.name} 하한`} onChange={(e) => onSel(row.name, { ...sel, a: e.target.value })} />
                        <span className="muted"> ~ </span>
                        <input className="num narrow" inputMode="decimal" value={sel.b} aria-label={`${row.name} 상한`} onChange={(e) => onSel(row.name, { ...sel, b: e.target.value })} />
                      </span>
                    )}
                    {issue && <span className="muted small" data-testid={`perf-issue-${row.name}`}> {issue}</span>}
                  </td>
                  {reuse && (
                    <td className="num small" data-testid={`perf-avail-${row.name}`}>
                      {inf?.available != null ? `${inf.available}/${inf.total ?? "—"}` : <span className="muted">—</span>}
                      {inf?.spec_changed ? <span className="muted"> · 정의 바뀜 {inf.spec_changed}</span> : null}
                      {miss && (
                        <div className="muted small so-miss" data-testid={`perf-miss-${row.name}`}>
                          {miss.message}
                          {miss.action === "extract" && miss.batch_id && canEdit && (
                            <button type="button" className="btn small" disabled={extractBusy} onClick={() => onExtract(miss.batch_id as string)}>성능 다시 추출</button>
                          )}
                        </div>
                      )}
                    </td>
                  )}
                  {canEdit && (
                    <td>
                      {state !== "removed" && (
                        <button type="button" className="icon-btn" aria-label={`${row.name} 삭제`} onClick={() => remove(row.name)}>✕</button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small" data-testid="criteria-help">{CRITERIA_HELP}</p>
      {extractNote && <p className="muted small" data-testid="extract-note">{extractNote}</p>}
      {canEdit && (
        <>
          <ResponseAdd candidates={cands} rows={draft} seriesHints={seriesHints} onAdd={(r) => setDraft([...draft, r])} />
          <div className="run-action-row">
            <button type="button" className="btn" disabled={!dirty || busy} onClick={() => void save()}>{busy ? "저장 중…" : "성능 정의 저장(템플릿)"}</button>
            {saved && !dirty && <span className="muted small">저장했습니다</span>}
            {dirty && <span className="muted small">저장하면 ④ 예측마다 이 정의로 추출합니다</span>}
            {error && <span className="error-text small" role="alert" data-testid="perf-save-error">{error}</span>}
          </div>
        </>
      )}
      {objNames.length > 1 && (
        <div className="so-weight-inputs" data-testid="weight-inputs">
          <div className="field-label">가중치</div>
          {objNames.map((n) => (
            <label key={n} className="so-weight-input small">
              <span className="mono">{n}</span>
              <input className="num narrow" inputMode="decimal" value={weights[n] === undefined ? "" : String(weights[n])} aria-label={`${n} 가중치`}
                onChange={(e) => onWeight(n, parseWeight(e.target.value))} />
            </label>
          ))}
          {weightsIssue(objNames, weights) && <p className="muted small" data-testid="weight-issue">{weightsIssue(objNames, weights)}</p>}
          <p className="muted small" data-testid="weight-help">{WEIGHT_HELP}</p>
          <p className="muted small" data-testid="multi-note">{MULTI_NOTE}</p>
        </div>
      )}
    </div>
  );
}
