// ④ native 세트 "검사 기준(고급)"(geometry-engine.md §8·§4.9): 접힘 1개(기본 닫힘). 칸 placeholder = 유효값(기본값),
// 저장 = PATCH geom_options(덮어쓰기 부분 객체), "기본값으로" = 해당 키 제거. 422 GEOM_OPTIONS_INVALID problems는 칸 옆에.
import { useState } from "react";
import { ApiError, api, errorMessage, type ParamSet } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { Advanced } from "../../../components/ui";
import { GEOM_OPT_FIELDS, getOpt, optKey, optProblems, parseOpt, setOpt, type OptField } from "../../../lib/geometry";

const toText = (v: unknown) => (v === undefined || v === null ? "" : String(v));

export function GeomOptionsForm({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { reloadParamSets } = useStudy();
  const all = GEOM_OPT_FIELDS.flatMap((g) => g.fields);
  const init = () => Object.fromEntries(all.map((f) => [optKey(f.path), toText(getOpt(ps.geom_options, f.path))]));
  const [draft, setDraft] = useState<Record<string, string>>(init);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const dirty = all.some((f) => draft[optKey(f.path)] !== toText(getOpt(ps.geom_options, f.path)));

  const set = (k: string, v: string) => {
    setDraft((d) => ({ ...d, [k]: v }));
    setSaved(false);
  };

  const save = async () => {
    setError(null);
    setSaved(false);
    let next = ps.geom_options ?? {};
    const local: Record<string, string> = {};
    for (const f of all) {
      const r = parseOpt(f, draft[optKey(f.path)]);
      if ("error" in r) local[optKey(f.path)] = r.error;
      else next = setOpt(next, f.path, r.value);
    }
    setProblems(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      await api.patchParamSet(ps.id, { geom_options: Object.keys(next).length ? next : null });
      await reloadParamSets();
      setSaved(true);
    } catch (e) {
      if (e instanceof ApiError && e.code === "GEOM_OPTIONS_INVALID") setProblems(optProblems(e.detail));
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Advanced label="검사 기준(고급)">
      <div className="geom-opts" data-testid="geom-options">
        {GEOM_OPT_FIELDS.map((g) => (
          <fieldset key={g.group} className="geom-opt-group">
            <legend className="field-label">{g.group}</legend>
            {g.fields.map((f) => (
              <OptInput
                key={optKey(f.path)}
                f={f}
                value={draft[optKey(f.path)]}
                placeholder={toText(getOpt(ps.geom_options_effective, f.path))}
                problem={problems[optKey(f.path)]}
                disabled={!canEdit || busy}
                onChange={(v) => set(optKey(f.path), v)}
              />
            ))}
          </fieldset>
        ))}
        {canEdit && (
          <div className="run-action-row">
            <button type="button" className="btn small primary" disabled={!dirty || busy} onClick={() => void save()}>
              {busy ? "저장 중…" : "저장"}
            </button>
            {saved && <span className="muted small">저장했습니다 — 다음 샘플 생성부터 적용</span>}
            {error && (
              <span className="error-text small" role="alert">
                {error}
              </span>
            )}
          </div>
        )}
      </div>
    </Advanced>
  );
}

function OptInput({ f, value, placeholder, problem, disabled, onChange }: { f: OptField; value: string; placeholder: string; problem?: string; disabled: boolean; onChange: (v: string) => void }) {
  const label = f.label;
  return (
    <label className="field geom-opt">
      <span className="field-label">{label}</span>
      <span className="run-action-row">
        {f.kind === "number" ? (
          <input className="num-input" aria-label={label} value={value} placeholder={placeholder || "미사용"} inputMode="decimal" disabled={disabled} onChange={(e) => onChange(e.target.value)} />
        ) : (
          <select aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
            <option value="">기본({f.kind === "bool" ? (placeholder === "true" ? "예" : placeholder === "false" ? "아니오" : placeholder) : f.options?.find(([k]) => k === placeholder)?.[1] ?? placeholder})</option>
            {(f.kind === "bool" ? ([["true", "예"], ["false", "아니오"]] as [string, string][]) : f.options ?? []).map(([k, t]) => (
              <option key={k} value={k}>
                {t}
              </option>
            ))}
          </select>
        )}
        {value !== "" && !disabled && (
          <button type="button" className="btn small ghost" onClick={() => onChange("")}>
            기본값으로
          </button>
        )}
      </span>
      {problem && <span className="error-text small">{problem}</span>}
    </label>
  );
}
