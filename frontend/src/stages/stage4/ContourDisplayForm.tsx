// S10 템플릿 관리 "컨투어 표시" 절: 예측 끝 HyperView 캡처에 쓸 결과 종류·성분(⑤ response-candidates 재사용)·평균 방식·
// 부품 이름 목록·범례(자동/고정 min·max)·방향 → PUT /param-sets/{id}/display (power).
import { useEffect, useState } from "react";
import { ApiError, api, errorMessage, type ContourDisplay, type ParamSet, type ResponseCandidates, type ViewKey } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { AVG_MODES, DEFAULT_VIEWS, VIEW_KEYS, viewLabel } from "../../lib/views";

const EMPTY: ContourDisplay = { field: "", component: "", avgmode: "simple", comps: [], legend: { mode: "auto", min: null, max: null }, views: DEFAULT_VIEWS };

/** 숫자 입력 문자열 → number | null */
const num = (s: string): number | null => (s.trim() === "" || !Number.isFinite(Number(s)) ? null : Number(s));

export function ContourDisplayForm({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { study, reloadParamSets } = useStudy();
  const init = ps.display ?? EMPTY;
  const [field, setField] = useState(init.field);
  const [component, setComponent] = useState(init.component);
  const [avgmode, setAvgmode] = useState(init.avgmode);
  const [comps, setComps] = useState(init.comps.join(", "));
  const [fixed, setFixed] = useState(init.legend.mode === "fixed");
  const [lo, setLo] = useState(init.legend.min == null ? "" : String(init.legend.min));
  const [hi, setHi] = useState(init.legend.max == null ? "" : String(init.legend.max));
  const [views, setViews] = useState<ViewKey[]>(init.views);
  const [cands, setCands] = useState<ResponseCandidates | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api.responseCandidates(study.id).then(setCands).catch(() => setCands(null));
  }, [study.id]);

  // 결과 종류·성분 목록: subcase를 가로지른 datatype 합집합
  const dts = new Map<string, string[]>();
  for (const sc of cands?.h3d?.subcases ?? []) for (const d of sc.datatypes) dts.set(d.name, [...new Set([...(dts.get(d.name) ?? []), ...d.components])]);
  const fieldOpts = dts.size ? [...dts.keys()] : null;
  const fieldVal = fieldOpts ? (fieldOpts.includes(field) ? field : fieldOpts[0]) : field;
  const compOpts = fieldOpts ? dts.get(fieldVal) ?? [] : null;
  const compVal = compOpts ? (compOpts.includes(component) ? component : compOpts[0] ?? "") : component;

  const body = (): ContourDisplay => ({
    field: fieldVal.trim(),
    component: compVal.trim(),
    avgmode,
    comps: comps.split(/[,\n]/).map((x) => x.trim()).filter(Boolean),
    legend: fixed ? { mode: "fixed", min: num(lo), max: num(hi) } : { mode: "auto", min: null, max: null },
    views: VIEW_KEYS.filter((k) => views.includes(k)),
  });

  const save = async () => {
    setError(null);
    setSaved(false);
    const b = body();
    if (!b.field) return setError("결과 종류를 정하세요");
    if (!b.views.length) return setError("방향을 1개 이상 고르세요");
    if (fixed && (b.legend.min == null || b.legend.max == null || !(b.legend.min < b.legend.max))) return setError("고정 범례는 최소 < 최대인 숫자");
    setBusy(true);
    try {
      await api.putParamSetDisplay(ps.id, b);
      await reloadParamSets();
      setSaved(true);
    } catch (e) {
      const p = e instanceof ApiError ? (e.detail.problems as { message: string }[] | undefined) : undefined;
      setError(p?.length ? p.map((x) => x.message).join(" · ") : errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const sel = (label: string, value: string, opts: string[] | null, onChange: (v: string) => void) =>
    opts ? (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {opts.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    ) : (
      <input aria-label={label} value={value} placeholder={label} onChange={(e) => onChange(e.target.value)} />
    );

  return (
    <div className="resp-defs" data-testid="contour-display">
    <fieldset className="contour-display" disabled={!canEdit}>
      <legend className="field-label">컨투어 표시</legend>
      <div className="form-grid">
        <label className="field">
          <span className="field-label">결과 종류</span>
          {sel("결과 종류", fieldVal, fieldOpts, setField)}
        </label>
        <label className="field">
          <span className="field-label">성분</span>
          {sel("성분", compVal, compOpts, setComponent)}
        </label>
        <label className="field">
          <span className="field-label">평균 방식</span>
          <select aria-label="평균 방식" value={avgmode} onChange={(e) => setAvgmode(e.target.value)}>
            {AVG_MODES.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">부품 이름(쉼표 구분, 비우면 전체)</span>
          <input aria-label="부품 이름 목록" className="mono" value={comps} placeholder="CUSHION_TOP, FOAM" onChange={(e) => setComps(e.target.value)} />
        </label>
      </div>
      <div className="fill-row">
        <span className="field-label">범례</span>
        <label className="radio-line">
          <input type="radio" name={`legend-${ps.id}`} checked={!fixed} onChange={() => setFixed(false)} />
          자동
        </label>
        <label className="radio-line">
          <input type="radio" name={`legend-${ps.id}`} checked={fixed} onChange={() => setFixed(true)} />
          고정
        </label>
        <label className="inline-field">
          최소
          <input className="num-input" inputMode="decimal" aria-label="범례 최소" value={lo} disabled={!fixed} onChange={(e) => setLo(e.target.value)} />
        </label>
        <label className="inline-field">
          최대
          <input className="num-input" inputMode="decimal" aria-label="범례 최대" value={hi} disabled={!fixed} onChange={(e) => setHi(e.target.value)} />
        </label>
      </div>
      <div className="fill-row" role="group" aria-label="캡처 방향">
        <span className="field-label">방향</span>
        <span className="checks">
          {VIEW_KEYS.map((k) => (
            <label key={k} className="check small">
              <input type="checkbox" checked={views.includes(k)} onChange={(e) => setViews(e.target.checked ? [...views, k] : views.filter((x) => x !== k))} />
              {viewLabel(k)}
            </label>
          ))}
        </span>
      </div>
      {canEdit && (
        <div className="run-action-row">
          <button type="button" className="btn" disabled={busy} onClick={save}>
            {busy ? "저장 중…" : "표시 설정 저장"}
          </button>
          {saved && <span className="muted small">저장했습니다 — 다음 예측부터 적용</span>}
          {error && (
            <span className="error-text small" role="alert">
              {error}
            </span>
          )}
        </div>
      )}
    </fieldset>
    </div>
  );
}
