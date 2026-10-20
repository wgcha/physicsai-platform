// 미리보기 입력·실행·상태(geometry-view.md §7.3, ④만): 선택 행 숫자 입력 + 슬라이더(범위 = feasible, 띠 = 사용자 범위, envelope/추정 표시),
// [미리보기] 버튼 1개(슬라이더 이동만으로는 요청하지 않음) · FE 메시·검사 포함 체크 · [공칭으로] · 진행/캐시/실패 배지.
import { useEffect, useState } from "react";
import { failureBadge, fmtVal, outsideFeasible, previewPhase, rowNominal, sliderSpec, type ViewManifest } from "./viewerCore";
import type { GeomPreviewState } from "./useGeomPreview";

export function PreviewPanel({
  manifest,
  row,
  userRange,
  edits,
  onEdit,
  fe,
  onFe,
  state,
  canRun,
  onRun,
  onReset,
}: {
  manifest: ViewManifest;
  row: string | null;
  userRange: { min?: number | null; max?: number | null } | null;
  edits: Record<string, number>;
  onEdit: (row: string, v: number | null) => void;
  fe: boolean;
  onFe: (on: boolean) => void;
  state: GeomPreviewState;
  canRun: boolean;
  onRun: () => void;
  onReset: () => void;
}) {
  const f = row ? manifest.features.find((x) => x.name === row) ?? manifest.features.find((x) => x.parameter === row) : undefined;
  const spec = f ? sliderSpec(f, userRange) : null;
  const nominal = row ? rowNominal(manifest, row) : null;
  const value = row ? edits[row] ?? nominal : null;
  const [raw, setRaw] = useState<string>(value == null ? "" : String(value));
  useEffect(() => setRaw(value == null ? "" : String(value)), [row, value]);
  const phase = previewPhase(state.preview);
  const running = state.since != null;
  const elapsed = useElapsed(state.since);
  const changed = Object.entries(edits);
  const pct = (v: number) => (spec ? ((v - spec.min) / (spec.max - spec.min)) * 100 : 0);

  return (
    <div className="gv-preview" data-testid="preview-panel">
      {f && spec && value != null ? (
        <div className="gv-input">
          <span className="mono small">{row}</span>
          <input
            className="num-input"
            aria-label={`${row} 미리보기 값`}
            inputMode="decimal"
            value={raw}
            onChange={(e) => {
              setRaw(e.target.value);
              const n = Number(e.target.value);
              if (e.target.value.trim() !== "" && Number.isFinite(n)) onEdit(row!, n);
            }}
          />
          <span className="muted small">{f.unit}</span>
          <div className="gv-slider">
            {spec.band && (
              <div
                className="gv-band"
                style={{ left: `${Math.max(0, pct(spec.band.min))}%`, width: `${Math.max(0, Math.min(100, pct(spec.band.max)) - Math.max(0, pct(spec.band.min)))}%` }}
                title="사용자 범위"
              />
            )}
            <input type="range" aria-label={`${row} 슬라이더`} min={spec.min} max={spec.max} step={spec.step} value={Math.min(spec.max, Math.max(spec.min, value))} onChange={(e) => onEdit(row!, Number(e.target.value))} />
          </div>
          <span className="muted small" data-testid="slider-range">
            모핑 가능 {fmtVal(spec.min)}~{fmtVal(spec.max)}({spec.sourceText}){spec.band ? ` · 사용자 범위 ${fmtVal(spec.band.min)}~${fmtVal(spec.band.max)}` : ""}
          </span>
          {outsideFeasible(f, value) && <span className="warn-text small">모핑 가능 범위 밖 — 실패할 수 있음</span>}
        </div>
      ) : (
        <p className="muted small">{row ? "이 행은 미리보기 값을 바꿀 수 없습니다" : "행을 고르면 값을 바꿔 미리볼 수 있습니다"}</p>
      )}
      {changed.length > 0 && (
        <div className="gv-changed small">
          변경:
          {changed.map(([k, v]) => (
            <span key={k} className="pill">
              <span className="mono">{k}</span> {fmtVal(v)}
              <button type="button" className="link small" aria-label={`${k} 공칭으로`} onClick={() => onEdit(k, null)}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="run-action-row">
        <button type="button" className="btn small primary" disabled={!canRun || running} onClick={onRun} title={canRun ? undefined : "실행 권한(power 이상)이 필요합니다"}>
          미리보기
        </button>
        <label className="check small" title="morph·검사까지 실행합니다(느림)">
          <input type="checkbox" checked={fe} onChange={(e) => onFe(e.target.checked)} />
          FE 메시·검사 포함(느림)
        </label>
        <button type="button" className="btn small ghost" disabled={!changed.length && !state.preview} onClick={onReset}>
          공칭으로
        </button>
        <PreviewStatus state={state} phase={phase} elapsed={elapsed} onRetry={onRun} />
      </div>
    </div>
  );
}

function PreviewStatus({ state, phase, elapsed, onRetry }: { state: GeomPreviewState; phase: ReturnType<typeof previewPhase>; elapsed: number; onRetry: () => void }) {
  const p = state.preview;
  if (state.error)
    return (
      <span className="error-text small" role="alert">
        미리보기를 만들지 못했습니다 — {state.error}{" "}
        <button type="button" className="link small" onClick={onRetry}>
          다시
        </button>
      </span>
    );
  if (state.since != null)
    return (
      <span className="pill run" data-testid="preview-running">
        {p?.status === "QUEUED" ? "대기 중" : "만드는 중"} {elapsed}초
      </span>
    );
  if (!p) return null;
  if (phase === "fail")
    return (
      <span className="gv-fail small" data-testid="preview-fail">
        <span className="pill bad">{failureBadge(p.category, p.code)}</span> {p.message_ko ?? p.code} <span className="mono muted">{p.code}</span>
      </span>
    );
  if (phase === "error" || phase === "expired")
    return (
      <span className="error-text small" role="alert">
        미리보기를 만들지 못했습니다 — {p.message_ko ?? p.code ?? p.status}{" "}
        <button type="button" className="link small" onClick={onRetry}>
          다시
        </button>
      </span>
    );
  return (
    <span className="small muted" data-testid="preview-ok">
      {p.cache_hit ? <span className="pill">캐시 결과</span> : <span className="pill ok">완료</span>} {p.fe === "check" ? (p.fe_status ? `FE 검사 ${p.fe_status === "PASS" ? "통과" : p.fe_status}${p.fe_code ? ` (${p.fe_code})` : ""}` : "") : "형상만 — 검사 생략"}
      {p.timing?.total_s != null ? ` · ${p.timing.total_s}초` : ""}
    </span>
  );
}

function useElapsed(since: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (since == null) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [since]);
  return since == null ? 0 : Math.max(0, Math.floor((now - since) / 1000));
}
