// ④ native 세트 상세(geometry-engine.md §8): 준비 상태 배지 + "형상 준비 다시", 피처 표(행 클릭 = 하이라이트 PNG),
// 대칭 그룹 분리·묶기(§6.2 symmetry_split), 고급 접힘 2개(검사 기준·다중 baseline) + 쉘 두께 PROP(3S).
// v0.2.4 native-vars.md §7.1: 표 = 풀 전체(사용·하한·상한·학습 범위 없음·모핑 가능 범위·경고) — 다중 선택 일괄 사용 체크·해제, 저장(리비전, 409 충돌), 변경 이력.
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api, errorMessage, type NativeFeatures, type NativeVars, type ParamSet } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { JobInline } from "../../../components/ui";
import { useLatestJob } from "../../../hooks/useLatestJob";
import { fmtTime, isTerminal } from "../../../lib/format";
import { PREP_LABEL, PREP_TONE, geomErrorText, isPitchType, isPositionType, isSplit, pitchTip, toggleSplit } from "../../../lib/geometry";
import { NV_ERROR_TEXT, detailRows, generalNotes, noteText, putBody, rowBounds, rowError, signature, type NativeRow } from "../../../lib/nativeVars";
import { NativeVarsTable } from "./NativeVarsTable";
import { GeomOptionsForm } from "./GeomOptionsForm";
import { ShellProps } from "./ShellProps";
import { MultiBaseline } from "./MultiBaseline";
import { GeomView3DLazy as GeomView3D } from "../geomview/GeomView3DLazy";
import { ViewSplit } from "../geomview/ViewSplit";
import { useRowSelection } from "../geomview/selection";
import { AppliedFilter } from "../../../components/AppliedFilter";

export function NativeDetail({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { study, reloadParamSets } = useStudy();
  const prep = ps.native?.prep_status ?? "MISSING";
  const job = useLatestJob(study.id, "PARAM_SET_NATIVE", (j) => j.state === "SUCCEEDED" && void reloadParamSets());
  const [error, setError] = useState<string | null>(null);
  const reprep = async () => {
    setError(null);
    try {
      const r = await api.nativePrepare(ps.id);
      job.track(await api.job(r.job_id));
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const running = !!job.job && !isTerminal(job.job.state);
  return (
    <div className="native-detail" data-testid="native-detail">
      <div className="run-action-row">
        <span className={`pill ${PREP_TONE[prep]}`} data-testid="prep-status">
          {PREP_LABEL[prep]}
        </span>
        {ps.native?.prep_reason && <span className="muted small">{ps.native.prep_reason}</span>}
        {canEdit && (
          <button type="button" className={`btn small${prep === "READY" ? " ghost" : ""}`} disabled={running} onClick={() => void reprep()}>
            형상 준비 다시
          </button>
        )}
        {job.job && (running || job.job.params?.param_set_id === ps.id) && <JobInline job={job.job} />}
        {error && (
          <span className="error-text small" role="alert">
            {error}
          </span>
        )}
      </div>
      <FeatureTable key={`${ps.id}-${prep}`} ps={ps} canEdit={canEdit} />
      <ShellProps key={`p-${ps.id}`} ps={ps} canEdit={canEdit} />
      <GeomOptionsForm key={`o-${ps.id}`} ps={ps} canEdit={canEdit} />
      <MultiBaseline key={`b-${ps.id}`} ps={ps} canEdit={canEdit} />
    </div>
  );
}

/** 변수 정의를 못 불러왔을 때(구버전 서버 등): 피처·세트 값으로 읽기 전용 표를 만든다 */
function fallbackVars(ps: ParamSet, data: NativeFeatures, reason: string): NativeVars {
  const used = new Map(ps.parameters.filter((p) => p.source !== "prop").map((p) => [p.name, p]));
  return {
    revision: 0, editable: false, reason,
    variables: [...used.values()].map((p) => ({ name: p.name, min: p.min, max: p.max })),
    pool: data.features.map((f) => ({
      name: f.name, type: f.type, body: f.body, nominal: f.nominal ?? 0, unit: f.unit ?? "mm", position: isPositionType(f.type),
      default_range: { min: f.min ?? 0, max: f.max ?? 0 }, feasible: f.feasible ?? null, ref_locked: !!f.ref_locked, group: f.group ?? null,
    })),
  } as NativeVars;
}

function FeatureTable({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { reloadParamSets } = useStudy();
  const [data, setData] = useState<NativeFeatures | null>(null);
  const [vars, setVars] = useState<NativeVars | null>(null);
  const [rows, setRows] = useState<NativeRow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revView, setRevView] = useState<{ revision: number; items: { name: string; min: number; max: number }[] } | null>(null);
  const order = useMemo(() => rows.map((r) => r.name), [rows]);
  const sel = useRowSelection(order); // 행 클릭 = 단일, Ctrl/⌘ = 추가, Shift = 범위 · 3D 면 클릭 → 행 선택·표 내부 스크롤(geometry-view.md §7.2)
  const loadView = useCallback(() => api.paramSetView(ps.id), [ps.id]);
  const applyVars = useCallback((v: NativeVars) => {
    setVars(v);
    setRows(detailRows(v));
  }, []);
  const reloadVars = useCallback(async () => {
    setError(null);
    setProblems([]);
    setConflict(false);
    applyVars(await api.nativeVars(ps.id));
  }, [ps.id, applyVars]);
  useEffect(() => {
    let alive = true;
    api
      .paramSetFeatures(ps.id)
      .then(async (d) => {
        if (!alive) return;
        setData(d);
        try {
          const v = await api.nativeVars(ps.id);
          if (alive) applyVars(v);
        } catch (e) {
          if (alive) applyVars(fallbackVars(ps, d, `변수 정의를 불러오지 못했습니다 — 읽기 전용(${errorMessage(e)})`));
        }
      })
      .catch((e) => alive && setLoadError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [ps.id]);
  if (loadError) return <p className="muted small">{loadError}</p>;
  if (!data || !vars) return <p className="muted small">피처 불러오는 중…</p>;
  const editable = canEdit && vars.editable;
  const groups = new Map(data.groups.map((g) => [g.id ?? "", g]));
  const dirty = signature(rows) !== signature(detailRows(vars));
  const rowIssues = rows.some((r) => rowError(r));
  const used = rows.filter((r) => r.use).length;
  const split = async (gid: string) => {
    setError(null);
    try {
      const next = toggleSplit(ps.geom_options, gid);
      await api.patchParamSet(ps.id, { geom_options: Object.keys(next).length ? next : null });
      await reloadParamSets();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const patch = (name: string, p: Partial<Pick<NativeRow, "use" | "lo" | "hi">>) => setRows((rs) => rs.map((r) => (r.name === name ? { ...r, ...p } : r)));
  const bulkUse = (names: string[], use: boolean) => setRows((rs) => rs.map((r) => (names.includes(r.name) ? { ...r, use } : r)));
  const save = async () => {
    setBusy(true);
    setError(null);
    setProblems([]);
    setConflict(false);
    try {
      applyVars(await api.putNativeVars(ps.id, putBody(rows, vars.revision)));
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
  const showRev = async (n: number) => {
    setError(null);
    try {
      const v = await api.nativeVars(ps.id, { revision: n });
      setRevView({ revision: n, items: v.variables });
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const userRanges: Record<string, { min: number; max: number }> = {};
  for (const r of rows) {
    const b = r.use ? rowBounds(r) : null;
    if (b) userRanges[r.name] = { min: b[0], max: b[1] };
  }
  const cols = [
    {
      head: "대칭 그룹",
      cell: (r: NativeRow) => {
        const g = r.group ? groups.get(r.group) : undefined;
        const gSplit = isSplit(ps.geom_options, r.group);
        return r.group ? (
          <span className="run-action-row">
            <span className="mono">{r.group}</span>
            {g && <span className="muted">{gSplit ? "분리됨" : `${g.members.length}개 묶음`}</span>}
            {canEdit && (
              <button type="button" className="btn small ghost" onClick={() => void split(r.group!)}>
                {gSplit ? "묶기" : "분리"}
              </button>
            )}
          </span>
        ) : (
          "–"
        );
      },
    },
    { head: "기준면", cell: (r: NativeRow) => (r.refLocked ? "변경 불가(양면 접촉)" : "자동") },
  ];
  return (
    <div className="feature-block">
      <AppliedFilter filter={ps.native?.extract_filter ?? data.filter} note="조건을 바꾸려면 새 세트로 등록하세요" />
      <div className="run-action-row small" data-testid="vars-head">
        <span>
          변수 정의 rev <b>{vars.revision}</b> · 사용 <b>{used}</b>/{rows.length}
        </span>
        {editable && (
          <>
            <button type="button" className="btn small primary" disabled={!dirty || busy || rowIssues} onClick={() => void save()}>
              {busy ? "저장 중…" : "저장"}
            </button>
            <button type="button" className="btn small ghost" disabled={!dirty || busy} onClick={() => applyVars(vars)}>
              되돌리기
            </button>
          </>
        )}
        {!sel.rows.length ? null : !editable && (
          <button type="button" className="btn small ghost" onClick={sel.clear}>
            선택 해제
          </button>
        )}
        {conflict && (
          <button type="button" className="btn small" onClick={() => void reloadVars().catch((e) => setError(errorMessage(e)))}>
            새로 불러오기
          </button>
        )}
      </div>
      {!vars.editable && vars.reason && (
        <p className="muted small" data-testid="vars-reason">
          {vars.reason}
        </p>
      )}
      <div className="small muted">
        자동 후보 피처 <b>{data.features.length}</b>개{data.engine_version ? ` · paicad ${data.engine_version}` : ""} — 행을 누르면 3D에 표시(Ctrl/⌘ = 추가, Shift = 범위){editable ? " · 선택 후 사용 체크·해제를 한꺼번에" : ""}. 목록에 없는 변수는 추출 조건을 바꿔 새 템플릿으로 등록하세요
      </div>
      <ViewSplit
        view={
          <GeomView3D
            loadKey={ps.id}
            load={loadView}
            rows={sel.rows}
            hover={sel.hover}
            onRows={sel.from3d}
            pngOf={(r) => data.features.find((f) => f.name === r)?.png_artifact_id ?? null}
            firstRow={data.features[0]?.name ?? null}
            paramSetId={ps.id}
            userRanges={userRanges}
            canPreview={canEdit}
          />
        }
        table={<NativeVarsTable label="형상 피처 표" rows={rows} canEdit={editable} words={{ name: "이름", lo: "하한", hi: "상한" }} showBody showTrain={false} sel={sel} typeTip={(r) => (isPitchType(r.type) ? pitchTip(data.features.find((f) => f.name === r.name), data.rib_rows) : undefined)} onPatch={patch} onBulkUse={bulkUse} notes={vars.warnings} extra={cols} testIdPrefix="nv" />}
      />
      {generalNotes(vars.warnings).length > 0 && (
        <ul className="problems small warn-text" aria-label="변수 경고" data-testid="vars-general-notes">
          {generalNotes(vars.warnings).map((n, i) => (
            <li key={i}>{noteText(n)}</li>
          ))}
        </ul>
      )}
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
      {data.warnings.length > 0 && (
        <ul className="problems small muted" aria-label="피처 경고">
          {data.warnings.map((w, i) => (
            <li key={i}>
              {w.feature ? <span className="mono">{w.feature}</span> : null} {geomErrorText(w.code, w.message)}
            </li>
          ))}
        </ul>
      )}
      {vars.history && vars.history.length > 0 && (
        <details className="advanced" data-testid="vars-history">
          <summary>변경 이력 {vars.history.length}건</summary>
          <div className="advanced-body">
            <ul className="plain small">
              {vars.history.map((h) => (
                <li key={h.revision}>
                  rev {h.revision} · {h.saved_at ? fmtTime(h.saved_at) : "–"} · {h.saved_by_name ?? "–"} · 변수 {h.count}개{" "}
                  <button type="button" className="btn small ghost" onClick={() => void showRev(h.revision)}>
                    보기
                  </button>
                </li>
              ))}
            </ul>
            {revView && (
              <div data-testid="vars-rev-view">
                <p className="small">
                  rev {revView.revision}의 변수(읽기 전용){" "}
                  <button type="button" className="btn small ghost" onClick={() => setRevView(null)}>
                    닫기
                  </button>
                </p>
                <table className="table compact" aria-label={`rev ${revView.revision} 변수`}>
                  <thead>
                    <tr>
                      <th>변수</th>
                      <th className="num">하한</th>
                      <th className="num">상한</th>
                    </tr>
                  </thead>
                  <tbody>
                    {revView.items.map((v) => (
                      <tr key={v.name}>
                        <td className="mono">{v.name}</td>
                        <td className="num mono">{v.min}</td>
                        <td className="num mono">{v.max}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}
