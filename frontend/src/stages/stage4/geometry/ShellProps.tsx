// 단계 3S 쉘 두께 PROP 선택(geometry-engine.md §11.1): 스캔(POST props/scan → 작업) → 목록(GET props) → 선택 저장(PUT props → ParamSet).
// /PROP/TYPE1만 선택 가능, TYPE9·10·11은 '미지원'(목록만), 요소별·PART 두께가 덮어쓰는 PROP은 선택 불가(reason_code),
// 여러 PART가 공유하면 경고(전부 바뀜). 범위 기본 ±5%(props.json range), 하한·상한 편집. 선택 행은 파라미터 표에 source "prop"으로 합쳐진다.
import { useEffect, useState } from "react";
import { api, errorMessage, type ParamSet, type ShellProps as ShellPropsDoc } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { JobInline } from "../../../components/ui";
import { useLatestJob } from "../../../hooks/useLatestJob";
import { isTerminal } from "../../../lib/format";
import { GEOM_ERROR_TEXT, geomErrorText } from "../../../lib/geometry";

type Sel = Record<string, { on: boolean; min: string; max: string }>;
type Problem = { code?: string; parameter?: string; message?: string };

const rangeOf = (r: unknown): { min?: number; max?: number } => (r && typeof r === "object" ? (r as { min?: number; max?: number }) : {});

export function ShellProps({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { study, reloadParamSets } = useStudy();
  const [doc, setDoc] = useState<ShellPropsDoc | null>(null);
  const [sel, setSel] = useState<Sel>({});
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const job = useLatestJob(study.id, "PARAM_SET_NATIVE", (j) => {
    if (j.state === "SUCCEEDED" && (j.params as { mode?: string } | null)?.mode === "props_scan") {
      setTick((t) => t + 1);
      void reloadParamSets();
    }
  });

  const load = (d: ShellPropsDoc) => {
    setDoc(d);
    const s: Sel = {};
    for (const p of d.props) {
      if (!p.parameter) continue;
      const rg = rangeOf(p.range);
      s[p.parameter] = { on: p.selected, min: String(p.min ?? rg.min ?? ""), max: String(p.max ?? rg.max ?? "") };
    }
    setSel(s);
  };
  useEffect(() => {
    let alive = true;
    api
      .shellProps(ps.id)
      .then((d) => alive && load(d))
      .catch(() => alive && setDoc(null));
    return () => {
      alive = false;
    };
  }, [ps.id, tick]);

  if (!doc) return null;
  const scanning = !!job.job && !isTerminal(job.job.state) && (job.job.params as { mode?: string } | null)?.mode === "props_scan";
  const scan = async () => {
    setError(null);
    try {
      const r = await api.scanShellProps(ps.id);
      job.track(await api.job(r.job_id));
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const chosen = Object.values(sel).filter((x) => x.on).length;
  const save = async () => {
    setError(null);
    setProblems([]);
    setBusy(true);
    try {
      const selected = doc.props
        .filter((p) => p.parameter && sel[p.parameter]?.on)
        .map((p) => ({ name: p.parameter as string, min: Number(sel[p.parameter as string].min), max: Number(sel[p.parameter as string].max) }));
      await api.putShellProps(ps.id, { selected, include_geometry: doc.include_geometry });
      load(await api.shellProps(ps.id));
      await reloadParamSets();
    } catch (e) {
      setError(errorMessage(e));
      const d = (e as { detail?: { problems?: Problem[] } }).detail;
      setProblems(Array.isArray(d?.problems) ? d.problems : []);
    } finally {
      setBusy(false);
    }
  };
  const patch = (name: string, p: Partial<Sel[string]>) => setSel((s) => ({ ...s, [name]: { ...s[name], ...p } }));
  const probOf = (name: string | null | undefined) => problems.find((p) => p.parameter === name)?.message ?? null;

  return (
    <details className="advanced" data-testid="shell-props">
      <summary>{doc.scanned ? `쉘 두께(PROP) — 선택 ${chosen} / 후보 ${doc.props.filter((p) => p.selectable).length}` : "쉘 두께(PROP) — 스캔 전"}</summary>
      <div className="advanced-body">
        {canEdit && (
          <div className="run-action-row">
            <button type="button" className={`btn small${doc.scanned ? " ghost" : ""}`} disabled={scanning} onClick={() => void scan()}>
              {doc.scanned ? "PROP 다시 스캔" : "PROP 스캔"}
            </button>
            {job.job && (job.job.params as { mode?: string } | null)?.mode === "props_scan" && (job.job.params as { param_set_id?: string }).param_set_id === ps.id && <JobInline job={job.job} />}
          </div>
        )}
        {!doc.scanned ? (
          <p className="muted small">조립 폴더의 /PROP/TYPE1(쉘) 두께를 찾아 파라미터로 추가할 수 있습니다.</p>
        ) : !doc.props.length ? (
          <p className="muted small">조립 폴더에 쉘 PROP이 없습니다.</p>
        ) : (
          <div className="table-wrap">
            <table className="table compact" aria-label="쉘 두께 PROP">
              <thead>
                <tr>
                  <th>선택</th>
                  <th>PROP</th>
                  <th>파라미터</th>
                  <th className="num">두께</th>
                  <th className="num">하한</th>
                  <th className="num">상한</th>
                  <th>사용 PART</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {doc.props.map((p, i) => {
                  const key = p.parameter ?? "";
                  const s = p.parameter ? sel[p.parameter] : undefined;
                  const shared = p.parts.length > 1;
                  const why = p.reason_code ? GEOM_ERROR_TEXT[p.reason_code] ?? p.reason_code : null;
                  const label = `PROP ${p.id ?? i}`;
                  return (
                    <tr key={`${p.id}-${i}`} className={p.selectable ? "" : "unused"}>
                      <td>
                        <input type="checkbox" aria-label={`${label} 선택`} checked={!!s?.on} disabled={!canEdit || !p.selectable || !p.parameter} onChange={(e) => patch(key, { on: e.target.checked })} />
                      </td>
                      <td className="small">
                        <span className="mono">{p.id ?? "–"}</span> {p.title} <span className="muted">{p.keyword || p.type}</span>
                        {!p.supported && <span className="pill">미지원</span>}
                      </td>
                      <td className="mono small">{p.parameter ?? "–"}</td>
                      <td className="num mono">{p.thickness ?? "–"}</td>
                      <td className="num">
                        <input className="num-input" aria-label={`${label} 하한`} value={s?.min ?? ""} disabled={!canEdit || !s?.on} inputMode="decimal" onChange={(e) => patch(key, { min: e.target.value })} />
                      </td>
                      <td className="num">
                        <input className="num-input" aria-label={`${label} 상한`} value={s?.max ?? ""} disabled={!canEdit || !s?.on} inputMode="decimal" onChange={(e) => patch(key, { max: e.target.value })} />
                      </td>
                      <td className="small" title={p.parts.map((x) => `${x.id ?? ""} ${x.title}`).join(", ")}>
                        {p.parts.map((x) => x.title || x.id).join(", ")}
                        {shared && <span className="pill warn">공유 PART {p.parts.length}개</span>}
                      </td>
                      <td className="muted small row-note">{probOf(p.parameter) ?? why ?? (shared ? GEOM_ERROR_TEXT.PROP_SHARED_BY_PARTS : null)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {doc.scanned && doc.warnings.some((w) => w.prop == null) && (
          <ul className="problems small muted" aria-label="PROP 경고">
            {doc.warnings
              .filter((w) => w.prop == null)
              .map((w, i) => (
                <li key={i}>{geomErrorText(w.code, w.message)}</li>
              ))}
          </ul>
        )}
        {canEdit && doc.scanned && doc.props.length > 0 && (
          <div className="run-action-row">
            <button type="button" className="btn small primary" disabled={busy} onClick={() => void save()}>
              {busy ? "저장 중…" : "선택 저장"}
            </button>
          </div>
        )}
        {error && (
          <div className="error-text small" role="alert">
            {error}
          </div>
        )}
      </div>
    </details>
  );
}
