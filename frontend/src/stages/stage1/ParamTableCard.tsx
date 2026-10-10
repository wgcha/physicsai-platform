import { useEffect, useMemo, useState } from "react";
import { api, ApiError, errorMessage, type TrainParam } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { fmtTime } from "../../lib/format";
import { useTrain } from "./TrainContext";

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

  useEffect(() => {
    setRows((setup?.parameters ?? []).map(toRow));
    setServerProblems({});
  }, [setup?.version, setup?.parameters]);

  const set = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
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
  const dirty = useMemo(() => {
    const orig = (setup?.parameters ?? []).map(toRow);
    return JSON.stringify(orig.map((r) => [r.min, r.max, r.use, r.format, r.unit])) !== JSON.stringify(rows.map((r) => [r.min, r.max, r.use, r.format, r.unit]));
  }, [rows, setup?.parameters]);

  return (
    <Card
      step="①-2"
      title="파라미터 표"
      aside={
        rows.length > 0 ? (
          <button type="button" className={`btn small ghost ${showAdv ? "on" : ""}`} aria-pressed={showAdv} onClick={() => setShowAdv((v) => !v)}>
            고급 {showAdv ? "▾" : "▸"}
          </button>
        ) : undefined
      }
    >
      {!rows.length ? (
        <p className="muted">①-1에서 CAD 파라미터를 먼저 추출하세요.</p>
      ) : (
        <div className="table-wrap">
          <table className="table compact param-table" aria-label="파라미터 표">
            <thead>
              <tr>
                <th>사용</th>
                <th>이름</th>
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
                const note = serverProblems[r.name] ?? issues[i] ?? (!r.valid ? r.problems.join(" · ") || "사용 불가" : null);
                return (
                  <tr key={r.name} className={r.use ? "" : "unused"}>
                    <td>
                      <input type="checkbox" aria-label={`${r.name} 사용`} checked={r.use} disabled={!canExec || !r.valid || r.nominal === null} onChange={(e) => set(i, { use: e.target.checked })} />
                    </td>
                    <td className="mono">{r.name}</td>
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
      )}
      <FeatureGate feature="train_tpl">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label={busy ? "생성 중…" : "tpl 생성"}
            onRun={() => void generate()}
            disabled={!enabled || busy || !rows.length || hasIssue}
            disabledReason={enabled ? (!rows.length ? "추출된 파라미터가 없습니다" : used.length === 0 ? "사용 파라미터가 1개 이상 필요합니다" : "표의 회색 문구를 확인하세요") : undefined}
            error={error}
          />
        )}
      </FeatureGate>
      {tpl && (
        <div className="tpl-state small" data-testid="tpl-state">
          <div>
            tpl 생성됨 · 사용 <b>{tpl.params.length}</b>개 · {fmtTime(tpl.generated_at)}
          </div>
          {(tpl.stale || dirty) && <div className="warn-text">표가 바뀌었습니다 — tpl을 다시 생성하세요</div>}
          {tpl.warnings.map((w, i) => (
            <div key={i} className="muted">
              {w.message}
            </div>
          ))}
        </div>
      )}
      <p className="muted small">단위계 mm-ton-s. 사용하지 않는 파라미터는 tpl에서 빠지고 CAD 공칭값이 유지됩니다.</p>
    </Card>
  );
}
