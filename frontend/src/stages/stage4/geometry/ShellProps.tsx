// 단계 3S 쉘 두께 PROP 선택(geometry-engine.md §11.1): /PROP/TYPE1만 선택 가능, TYPE9·10·11은 '미지원'(목록만),
// 요소별 두께가 덮어쓰는 PROP은 선택 불가, 여러 PART가 공유하면 경고(전부 바뀜). 범위 기본 ±5%, 하한·상한 편집.
// API는 백엔드 병합 전 목 라우트(GET·PUT /param-sets/{id}/props) — openapi 병합 후 gen:api 타입으로 교체.
import { useEffect, useState } from "react";
import { api, errorMessage, type ParamSet, type ShellPropsDoc } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { GEOM_ERROR_TEXT } from "../../../lib/geometry";

type Sel = Record<number, { on: boolean; min: string; max: string }>;

export function ShellProps({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { reloadParamSets } = useStudy();
  const [doc, setDoc] = useState<ShellPropsDoc | null>(null);
  const [sel, setSel] = useState<Sel>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = (d: ShellPropsDoc) => {
    setDoc(d);
    const s: Sel = {};
    for (const p of d.props) {
      const cur = d.selected.find((x) => x.prop_id === p.id);
      s[p.id] = { on: !!cur, min: String(cur?.min ?? p.range?.min ?? ""), max: String(cur?.max ?? p.range?.max ?? "") };
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
  }, [ps.id]);

  if (!doc || !doc.props.length) return null;
  const chosen = Object.values(sel).filter((x) => x.on).length;
  const save = async () => {
    setError(null);
    setBusy(true);
    try {
      const body = doc.props
        .filter((p) => sel[p.id]?.on)
        .map((p) => ({ prop_id: p.id, name: p.parameter ?? `PROP${p.id}_SHELL_T`, min: Number(sel[p.id].min), max: Number(sel[p.id].max) }));
      load(await api.putShellProps(ps.id, body));
      await reloadParamSets();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const patch = (id: number, p: Partial<Sel[number]>) => setSel((s) => ({ ...s, [id]: { ...s[id], ...p } }));

  return (
    <details className="advanced" data-testid="shell-props">
      <summary>
        쉘 두께(PROP) — 선택 {chosen} / 후보 {doc.props.filter((p) => p.selectable).length}
      </summary>
      <div className="advanced-body">
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
              {doc.props.map((p) => {
                const s = sel[p.id];
                const shared = p.parts.length > 1;
                const why = !p.supported ? GEOM_ERROR_TEXT.PROP_UNSUPPORTED_TYPE : p.element_overrides > 0 ? GEOM_ERROR_TEXT.PROP_OVERRIDDEN_BY_ELEMENT : !p.selectable ? GEOM_ERROR_TEXT.PROP_THICKNESS_INVALID : null;
                return (
                  <tr key={p.id} className={p.selectable ? "" : "unused"}>
                    <td>
                      <input type="checkbox" aria-label={`PROP ${p.id} 선택`} checked={!!s?.on} disabled={!canEdit || !p.selectable} onChange={(e) => patch(p.id, { on: e.target.checked })} />
                    </td>
                    <td className="small">
                      <span className="mono">{p.id}</span> {p.title ?? ""} <span className="muted">{p.keyword ?? p.type}</span>
                      {!p.supported && <span className="pill">미지원</span>}
                    </td>
                    <td className="mono small">{p.parameter ?? "–"}</td>
                    <td className="num mono">{p.thickness ?? "–"}</td>
                    <td className="num">
                      <input className="num-input" aria-label={`PROP ${p.id} 하한`} value={s?.min ?? ""} disabled={!canEdit || !s?.on} inputMode="decimal" onChange={(e) => patch(p.id, { min: e.target.value })} />
                    </td>
                    <td className="num">
                      <input className="num-input" aria-label={`PROP ${p.id} 상한`} value={s?.max ?? ""} disabled={!canEdit || !s?.on} inputMode="decimal" onChange={(e) => patch(p.id, { max: e.target.value })} />
                    </td>
                    <td className="small" title={p.parts.map((x) => `${x.id} ${x.title ?? ""}`).join(", ")}>
                      {p.parts.map((x) => x.title ?? x.id).join(", ")}
                      {shared && <span className="pill warn">공유 PART {p.parts.length}개</span>}
                    </td>
                    <td className="muted small row-note">{why ?? (shared ? GEOM_ERROR_TEXT.PROP_SHARED_BY_PARTS : null)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {canEdit && (
          <div className="run-action-row">
            <button type="button" className="btn small primary" disabled={busy} onClick={() => void save()}>
              {busy ? "저장 중…" : "선택 저장"}
            </button>
            {error && (
              <span className="error-text small" role="alert">
                {error}
              </span>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
