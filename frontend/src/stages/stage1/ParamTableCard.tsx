import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, errorMessage, type NativeFeature, type RibRow, type TrainParam } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { fmtTime } from "../../lib/format";
import { tplSummaryNotes, tplSummaryText } from "../../lib/altairVars";
import { useTrain } from "./TrainContext";
import { isAbsRangeType, isPitchType, pitchTip, typeLabel } from "../../lib/geometry";
import { GeomView3DLazy as GeomView3D } from "../stage4/geomview/GeomView3DLazy";
import { ViewSplit } from "../stage4/geomview/ViewSplit";
import { useRowSelection, bulkTargets } from "../stage4/geomview/selection";
import { AppliedFilter } from "../../components/AppliedFilter";
import { BulkUseBar } from "../../components/BulkUseBar";

// ---------------------------------------------------------------- ①-2
interface Row {
  name: string;
  raw: string;
  nominal: number | null;
  min: string;
  max: string;
  use: boolean;
  format: string;
  unit: string;
  valid: boolean;
  problems: string[];
}

const toRow = (p: TrainParam): Row => ({
  name: p.name, raw: p.raw_nominal, nominal: p.nominal ?? null, min: p.min == null ? "" : String(p.min), max: p.max == null ? "" : String(p.max),
  use: p.use, format: p.format, unit: p.unit, valid: p.valid, problems: p.problems,
});
const num = (s: string): number | null => (s.trim() === "" || !Number.isFinite(Number(s)) ? null : Number(s));

/** 클라이언트 표시용 행 문제(서버 검증과 같은 규칙, §6.3) */
function rowIssue(r: Row): string | null {
  if (!r.use) return null;
  const lo = num(r.min);
  const hi = num(r.max);
  if (lo === null || hi === null) return "하한·상한을 입력하세요";
  if (!(lo < hi)) return "하한 < 상한";
  if (r.nominal !== null && (r.nominal < lo || r.nominal > hi)) return "공칭값이 범위 밖";
  if (!/^%[-0-9.]*[idfeEgG]$/.test(r.format)) return "형식 오류";
  return null;
}

export function ParamTableCard() {
  const { study } = useStudy();
  const { setup, setSetup } = useTrain();
  const canExec = useCanExecute();
  const [rows, setRows] = useState<Row[]>([]);
  const [showAdv, setShowAdv] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [serverProblems, setServerProblems] = useState<Record<string, string>>({});
  // geometry-engine.md §8 ①-2: native는 tpl 없음 — 표 저장만, 피처 종류·하이라이트 PNG = GET /studies/{id}/train/features(§7.3.1)
  const native = setup?.engine === "native";
  const [features, setFeatures] = useState<Map<string, NativeFeature>>(new Map());
  const [ribRows, setRibRows] = useState<RibRow[] | null>(null); // rib-gap.md §3.4 피치 행 툴팁용 열 정보
  const sel = useRowSelection(useMemo(() => rows.map((r) => r.name), [rows]));
  const rp = sel.rowProps;
  useEffect(() => {
    if (!native) return;
    let alive = true;
    api
      .trainFeatures(study.id)
      .then((d) => {
        if (!alive) return;
        setFeatures(new Map(d.features.map((f) => [f.name, f])));
        setRibRows(d.rib_rows ?? null);
      })
      .catch(() => alive && setFeatures(new Map()));
    return () => {
      alive = false;
    };
  }, [native, study.id, setup?.extract_job_id]);
  // geometry-view.md §6.9: ①-2 공칭 3D 뷰(같은 뷰어, 미리보기 없음) — 항상 떠 있는 단일 창, 선택 행(다중) = 하이라이트
  const loadView = useCallback(() => api.trainView(study.id), [study.id]);

  useEffect(() => {
    setRows((setup?.parameters ?? []).map(toRow));
    setServerProblems({});
  }, [setup?.version, setup?.parameters]);

  const set = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const canUse = (r: Row) => r.valid && r.nominal !== null;
  /** 대상 행(이름)의 '사용'을 한꺼번에 — 체크는 사용할 수 없는 행(무효·공칭 없음)을 건너뛴다 */
  const setUse = (names: string[], use: boolean) => setRows((rs) => rs.map((r) => (names.includes(r.name) && (!use || canUse(r)) ? { ...r, use } : r)));
  /** 엑셀식: 선택된 행의 체크박스를 누르면 선택 행 전체가 같은 상태로, 선택 밖 행은 그 행만 */
  const toggleUse = (name: string, use: boolean) => setUse(bulkTargets(sel.rows, name), use);
  const used = rows.filter((r) => r.use);
  const issues = rows.map(rowIssue);
  const hasIssue = issues.some(Boolean) || used.length === 0;

  /** §14.2: PUT 저장 → POST 생성. 저장 실패 시 생성하지 않는다 */
  const generate = async () => {
    if (!setup) return;
    setBusy(true);
    setError(null);
    setServerProblems({});
    try {
      const saved = await api.saveTrainParams(study.id, {
        version: setup.version,
        parameters: rows.map((r) => ({ name: r.name, min: num(r.min), max: num(r.max), use: r.use, format: r.format, unit: r.unit })),
      });
      setSetup(saved);
      if (native) return;
      try {
        setSetup(await api.generateTpl(study.id, saved.version));
      } catch (e) {
        setError(errorMessage(e));
      }
    } catch (e) {
      if (e instanceof ApiError && Array.isArray((e.detail as { problems?: unknown }).problems)) {
        const m: Record<string, string> = {};
        for (const p of (e.detail as unknown as { problems: { name: string; message: string }[] }).problems) m[p.name] = p.message;
        setServerProblems(m);
      }
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const tpl = setup?.tpl;
  const fixedInTpl = useMemo(() => new Set((tpl?.params ?? []).filter((p) => p.used === false).map((p) => p.name)), [tpl]);
  const summary = setup?.tpl_summary;
  const dirty = useMemo(() => {
    const orig = (setup?.parameters ?? []).map(toRow);
    return JSON.stringify(orig.map((r) => [r.min, r.max, r.use, r.format, r.unit])) !== JSON.stringify(rows.map((r) => [r.min, r.max, r.use, r.format, r.unit]));
  }, [rows, setup?.parameters]);

  return (
    <Card span={native ? 12 : 6} foot={
        <>
          <p className="muted small">
            {native
              ? `Native · 피처 ${rows.length}개. 사용하지 않는 피처는 공칭값이 유지됩니다(위치형은 mm 범위).`
              : "단위계 mm-ton-s. 사용 = 학습 데이터(DOE)에서 움직일 파라미터. 미사용도 tpl에 공칭 고정으로 들어가며, 예측·최적화 변수는 ④ 템플릿에서 따로 정합니다."}
          </p>
          <FeatureGate feature={native ? "geometry_native" : "train_tpl"}>
            {(enabled) => (
              <RunAction
                canExecute={canExec}
                label={busy ? (native ? "저장 중…" : "생성 중…") : native ? "표 저장" : "tpl 생성"}
                onRun={() => void generate()}
                disabled={!enabled || busy || !rows.length || hasIssue}
                disabledReason={enabled ? (!rows.length ? "추출된 파라미터가 없습니다" : used.length === 0 ? "사용 파라미터가 1개 이상 필요합니다" : "표의 회색 문구를 확인하세요") : undefined}
                error={error}
              />
            )}
          </FeatureGate>
        </>
      }
      step="①-2"
      title="파라미터 표"
      aside={
        rows.length > 0 ? (
          <>
            <button type="button" className={`btn small ghost ${showAdv ? "on" : ""}`} aria-pressed={showAdv} onClick={() => setShowAdv((v) => !v)}>
              고급 {showAdv ? "▾" : "▸"}
            </button>
          </>
        ) : undefined
      }
    >
      {!rows.length ? (
        <p className="muted">①-1에서 CAD 파라미터를 먼저 추출하세요.</p>
      ) : (
        <>
        {native && <AppliedFilter filter={setup?.extract_filter} summary={setup?.extract_summary} />}
        {native && <BulkUseBar count={sel.rows.length} disabled={!canExec} onCheck={() => setUse(sel.rows, true)} onUncheck={() => setUse(sel.rows, false)} onClear={sel.clear} />}
        <ViewSplit
          view={
            native ? (
              <GeomView3D
                loadKey={`${study.id}:${setup?.extract_job_id ?? ""}`}
                load={loadView}
                rows={sel.rows}
                hover={sel.hover}
                onRows={sel.from3d}
                pngOf={(r) => features.get(r)?.png_artifact_id ?? null}
                firstRow={rows[0]?.name ?? null}
              />
            ) : null
          }
          table={
        <div className="table-wrap" ref={sel.tableRef}>
          <table className="table compact param-table" aria-label="파라미터 표">
            <thead>
              <tr>
                <th>사용</th>
                <th>이름</th>
                {native && <th>종류</th>}
                <th className="num">공칭</th>
                <th className="num">하한</th>
                <th className="num">상한</th>
                {showAdv && <th>형식</th>}
                {showAdv && <th>단위</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const note = serverProblems[r.name] ?? issues[i] ?? (!r.valid ? r.problems.join(" · ") || "사용 불가" : null) ?? (!native && !r.use && fixedInTpl.has(r.name) ? "tpl에 공칭 고정" : null);
                return (
                  <tr key={r.name} {...(native ? rp(r.name) : { "data-row": r.name })} className={`${r.use ? "" : "unused"}${native ? ` ${rp(r.name).className}` : ""}`}>
                    <td>
                      <input type="checkbox" aria-label={`${r.name} 사용`} checked={r.use} disabled={!canExec || !r.valid || r.nominal === null} onChange={(e) => (native ? toggleUse(r.name, e.target.checked) : set(i, { use: e.target.checked }))} />
                    </td>
                    <td className="mono">{r.name}</td>
                    {native && (
                      <td className="small" title={isPitchType(features.get(r.name)?.type) ? pitchTip(features.get(r.name), ribRows) : undefined}>
                        {typeLabel(features.get(r.name)?.type)}
                        {isAbsRangeType(features.get(r.name)?.type) && <span className="muted"> · mm 범위</span>}
                      </td>
                    )}
                    <td className="num mono">{r.raw}</td>
                    <td className="num">
                      <input className="num-input" aria-label={`${r.name} 하한`} value={r.min} disabled={!canExec || !r.use} inputMode="decimal" onChange={(e) => set(i, { min: e.target.value })} />
                    </td>
                    <td className="num">
                      <input className="num-input" aria-label={`${r.name} 상한`} value={r.max} disabled={!canExec || !r.use} inputMode="decimal" onChange={(e) => set(i, { max: e.target.value })} />
                    </td>
                    {showAdv && (
                      <td>
                        <input className="fmt-input mono" aria-label={`${r.name} 형식`} value={r.format} disabled={!canExec || !r.use} onChange={(e) => set(i, { format: e.target.value })} />
                      </td>
                    )}
                    {showAdv && (
                      <td>
                        <input className="unit-input" aria-label={`${r.name} 단위`} value={r.unit} maxLength={16} disabled={!canExec} onChange={(e) => set(i, { unit: e.target.value })} />
                      </td>
                    )}
                    <td className="muted small row-note">{note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
          }
        />
        </>
      )}
      {tpl && !native && (
        <div className="tpl-state small" data-testid="tpl-state">
          <div>
            tpl 생성됨 · {summary ? tplSummaryText(summary) : `사용 ${tpl.params.length}개`} · {fmtTime(tpl.generated_at)}
          </div>
          {summary && tplSummaryNotes(summary).map((t, i) => (
            <div key={i} className="warn-text" data-testid="tpl-summary-note">
              {t}
            </div>
          ))}
          {(tpl.stale || dirty) && <div className="warn-text">표가 바뀌었습니다 — tpl을 다시 생성하세요</div>}
          {tpl.warnings.filter((w) => !w.names?.length).map((w, i) => (
            <div key={i} className="muted">
              {w.message}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
