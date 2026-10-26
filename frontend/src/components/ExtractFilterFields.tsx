// native ①-1·④ 등록 폼 공용 "찾을 종류 + 조건(선택)" 블록(extract-filter.md §8). 문구·칸이 두 곳에서 같다.
// 체크 6개(그룹) → 조건 접힘(체크한 그룹의 칸만, 빈칸 = 제한 없음) → 고급(구배 허용각). 검사는 클라이언트(§6.1 문구)와 서버 422 problems 모두 칸 아래에 보인다.
import { Fragment, useEffect, useState } from "react";
import type { ExtractGroup, ExtractProblem } from "../api/types";
import { COND_FIELDS, DRAFT_LABEL, DRAFT_NOTE, EXTRACT_GROUPS, conditionCount, problemsFor, validateForm, type FilterForm } from "../lib/extractFilter";

const PLACEHOLDER = "비우면 조건 없음";

export function ExtractFilterFields({
  value,
  onChange,
  serverProblems = [],
  disabled,
  readOnly,
  wide,
  testId = "extract-filter",
}: {
  value: FilterForm;
  onChange: (next: FilterForm) => void;
  /** 422 EXTRACT_FILTER_INVALID problems(요청 뒤) — 칸을 고치면 부모가 비운다 */
  serverProblems?: ExtractProblem[];
  disabled?: boolean;
  /** 값을 보이되 바꿀 수 없음(①-1 조건 가져오기) */
  readOnly?: boolean;
  /** ①-1 가로 배치: 체크 한 줄 + 오른쪽 끝 [조건], 펼치면 조건 칸 전부 한 줄(구배 포함·고급 접힘 없음, 좁으면 줄바꿈) */
  wide?: boolean;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [adv, setAdv] = useState(false);
  const locked = disabled || readOnly;
  const client = validateForm(value);
  const problems = [...client, ...serverProblems.filter((s) => !client.some((c) => c.key === s.key))];
  const condProblem = problems.some((p) => p.key !== "groups");
  const draftProblem = problemsFor(problems, "draft_max_deg").length > 0;
  // 조건 칸의 문제는 접혀 있어도 보이게 펼친다(펼친 뒤에는 사용자가 닫을 때까지 유지)
  useEffect(() => {
    if (condProblem) setOpen(true);
  }, [condProblem]);
  useEffect(() => {
    if (draftProblem) setAdv(true);
  }, [draftProblem]);
  const count = conditionCount(value);
  const shown = open;

  const toggle = (g: ExtractGroup, on: boolean) => onChange({ ...value, groups: on ? [...value.groups, g] : value.groups.filter((x) => x !== g) });
  const setCell = (k: string, s: string) => onChange({ ...value, v: { ...value.v, [k]: s } });
  const err = (row: string) =>
    problemsFor(problems, row).map((m, i) => (
      <span key={i} className="error-text small" role="alert">
        {m}
      </span>
    ));

  return (
    <div className={`extract-filter${wide ? " wide" : ""}`} data-testid={testId}>
      <div className="field">
        <span className="field-label">찾을 종류</span>
        <div className="checks extract-groups" role="group" aria-label="찾을 종류">
          {EXTRACT_GROUPS.map((g) => (
            <Fragment key={g.key}>
              <label className="check">
                <input type="checkbox" checked={value.groups.includes(g.key)} disabled={locked} onChange={(e) => toggle(g.key, e.target.checked)} />
                {g.label}
              </label>
              {g.help && (
                <span className="extract-help" title={g.help} aria-label={g.help} data-testid={`help-${g.key}`}>
                  ⓘ
                </span>
              )}
            </Fragment>
          ))}
        </div>
        {err("groups")}
      </div>
      <div className="extract-cond-head">
        <button type="button" className={`btn small ghost ${shown ? "on" : ""}`} aria-expanded={shown} onClick={() => setOpen((v) => !v)}>
          조건(선택) {shown ? "▾" : "▸"}
        </button>
        {!shown && count > 0 && <span className="muted small">조건 {count}개 지정됨</span>}
      </div>
      {shown && (
        <div className={`extract-cond${wide ? " wide" : ""}`} data-testid={`${testId}-cond`}>
          {COND_FIELDS.filter((f) => value.groups.includes(f.group)).map((f) => (
            <div key={f.id} className="field">
              <span className="field-label">{f.label}</span>
              {f.kind === "range" ? (
                <span className="run-action-row">
                  <input className="num-input" aria-label={`${f.label} 최소`} placeholder={wide ? "최소" : `최소 · ${PLACEHOLDER}`} inputMode="decimal" disabled={locked} value={value.v[`${f.id}.min`] ?? ""} onChange={(e) => setCell(`${f.id}.min`, e.target.value)} />
                  <span className="muted">~</span>
                  <input className="num-input" aria-label={`${f.label} 최대`} placeholder={wide ? "최대" : `최대 · ${PLACEHOLDER}`} inputMode="decimal" disabled={locked} value={value.v[`${f.id}.max`] ?? ""} onChange={(e) => setCell(`${f.id}.max`, e.target.value)} />
                </span>
              ) : (
                <input className="num-input" aria-label={f.label} placeholder={PLACEHOLDER} inputMode="decimal" disabled={locked} value={value.v[f.id] ?? ""} onChange={(e) => setCell(f.id, e.target.value)} />
              )}
              {err(f.id)}
            </div>
          ))}
          {wide ? (
            <div className="field">
              <span className="field-label">
                {DRAFT_LABEL} <span className="extract-help" title={DRAFT_NOTE} aria-label={DRAFT_NOTE}>ⓘ</span>
              </span>
              <input className="num-input" aria-label={DRAFT_LABEL} placeholder="기본값 3" inputMode="decimal" disabled={locked} value={value.v.draft_max_deg ?? ""} onChange={(e) => setCell("draft_max_deg", e.target.value)} />
              {err("draft_max_deg")}
            </div>
          ) : (
            <div className="field extract-adv">
              <button type="button" className="btn small ghost" aria-expanded={adv} onClick={() => setAdv((v) => !v)}>
                고급 {adv ? "▾" : "▸"}
              </button>
              {adv && (
                <>
                  <span className="field-label">{DRAFT_LABEL}</span>
                  <input className="num-input" aria-label={DRAFT_LABEL} placeholder="기본값 3" inputMode="decimal" disabled={locked} value={value.v.draft_max_deg ?? ""} onChange={(e) => setCell("draft_max_deg", e.target.value)} />
                  <span className="field-hint">{DRAFT_NOTE}</span>
                  {err("draft_max_deg")}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
