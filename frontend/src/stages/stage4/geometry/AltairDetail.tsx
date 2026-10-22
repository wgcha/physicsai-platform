// ④ Altair 템플릿 변수 정의(altair-vars.md §5·§7): 전체 tpl 세트는 Native와 같은 변수 표(사용·하한·상한, 리비전·저장·되돌리기·409 충돌)로 편집하고,
// 옛 부분 tpl 세트는 같은 표를 읽기 전용 + 재생성 안내로 보여 준다. Native 전용 열(종류·바디·모핑 가능 범위·기준면)은 없다.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, errorMessage, type NativeVars, type ParamSet } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { NV_ERROR_TEXT, detailRows, putBody, reasonText, rowError, signature, type NativeRow } from "../../../lib/nativeVars";
import { NativeVarsTable } from "./NativeVarsTable";

export function AltairDetail({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { reloadParamSets } = useStudy();
  const [vars, setVars] = useState<NativeVars | null>(null);
  const [rows, setRows] = useState<NativeRow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const apply = useCallback((v: NativeVars) => {
    setVars(v);
    setRows(detailRows(v));
  }, []);
  const clear = () => {
    setError(null);
    setProblems([]);
    setConflict(false);
  };
  const reload = useCallback(async () => {
    clear();
    apply(await api.nativeVars(ps.id));
  }, [ps.id, apply]);
  useEffect(() => {
    let alive = true;
    api
      .nativeVars(ps.id)
      .then((v) => alive && apply(v))
      .catch((e) => alive && setLoadError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [ps.id]);
  if (loadError) return <p className="muted small">{loadError}</p>;
  if (!vars) return <p className="muted small">변수 정의 불러오는 중…</p>;
  const editable = canEdit && vars.editable;
  const dirty = signature(rows) !== signature(detailRows(vars));
  const rowIssues = rows.some((r) => rowError(r));
  const used = rows.filter((r) => r.use).length;
  const patch = (name: string, p: Partial<Pick<NativeRow, "use" | "lo" | "hi">>) => setRows((rs) => rs.map((r) => (r.name === name ? { ...r, ...p } : r)));
  const bulkUse = (names: string[], use: boolean) => setRows((rs) => rs.map((r) => (names.includes(r.name) ? { ...r, use } : r)));
  const save = async () => {
    setBusy(true);
    clear();
    try {
      apply(await api.putNativeVars(ps.id, putBody(rows, vars.revision)));
      await reloadParamSets();
    } catch (e) {
      if (e instanceof ApiError && e.code === "NATIVE_VARS_CONFLICT") {
        setConflict(true);
        setError(NV_ERROR_TEXT.NATIVE_VARS_CONFLICT);
      } else {
        setError(e instanceof ApiError ? NV_ERROR_TEXT[e.code] ?? errorMessage(e) : errorMessage(e));
        const pr = e instanceof ApiError ? (e.detail.problems as { code?: string; name?: string; message?: string }[] | undefined) : undefined;
        setProblems((pr ?? []).map((x) => `${x.name ? `${x.name}: ` : ""}${x.message ?? (x.code && NV_ERROR_TEXT[x.code]) ?? x.code ?? ""}`));
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="feature-block" data-testid="altair-detail">
      <div className="run-action-row small" data-testid="vars-head">
        <span>
          변수 정의 rev <b>{vars.revision}</b> · 사용 <b>{used}</b>/{rows.length}
        </span>
        {editable && (
          <>
            <button type="button" className="btn small primary" disabled={!dirty || busy || rowIssues} onClick={() => void save()}>
              {busy ? "저장 중…" : "저장"}
            </button>
            <button type="button" className="btn small ghost" disabled={!dirty || busy} onClick={() => apply(vars)}>
              되돌리기
            </button>
          </>
        )}
        {conflict && (
          <button type="button" className="btn small" onClick={() => void reload().catch((e) => setError(errorMessage(e)))}>
            새로 불러오기
          </button>
        )}
      </div>
      {!vars.editable && vars.reason && (
        <p className="warn-text small" data-testid="vars-reason">
          {reasonText(vars.reason)}
        </p>
      )}
      <NativeVarsTable label="템플릿 변수 표" engine="altair" rows={rows} canEdit={editable} words={{ name: "이름", lo: "하한", hi: "상한" }} showTrain={false} onPatch={patch} onBulkUse={bulkUse} notes={vars.warnings} testIdPrefix="av" />
      {error && (
        <div className="error-text small" role="alert">
          {error}
        </div>
      )}
      {problems.length > 0 && (
        <ul className="problems small" aria-label="변수 정의 오류">
          {problems.map((m, i) => (
            <li key={i}>{m}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
