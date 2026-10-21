import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, errorMessage, type Engine, type PathInspectResult, type PathPurpose } from "../api";
import { BrowseButton } from "./BrowseButton";
import type { PickMode } from "./PathPickerDialog";
import { PathSourceTabs } from "./upload/PathSourceTabs";

/** 용도별 "찾아보기" 설정(phase3 §12 S7). aiOnly = 백엔드가 AI 루트만 허용하는 용도. SPDM은 탐색 루트 밖이라 없음 */
export const BROWSE_OF: Partial<Record<PathPurpose, { mode: PickMode; exts?: string[]; aiOnly?: boolean }>> = {
  DATASET_INPUT: { mode: "dir", aiOnly: true },
  MODEL_FOLDER: { mode: "dir" },
  PARAM_SET: { mode: "dir", aiOnly: true },
  CAD_FILE: { mode: "file" },
  RADIOSS_ASSEM: { mode: "dir" },
  RESULT_FOLDER: { mode: "dir" },
  CURATION_INPUT: { mode: "dir", aiOnly: true },
  PREDICT_INPUT: { mode: "dir_or_file", exts: [".rad", ".hm"] },
};

/** 경로 입력 + "찾아보기"(서버 폴더 탐색) + "확인"(paths/inspect, 디스크 읽기만) */
export function PathInput({
  studyId,
  purpose,
  label,
  placeholder,
  value,
  onChange,
  onInspected,
  canExecute,
  renderSummary,
  extra,
}: {
  studyId: string;
  purpose: PathPurpose;
  label: string;
  placeholder?: string;
  value: string;
  onChange: (v: string) => void;
  onInspected?: (r: PathInspectResult | null) => void;
  canExecute: boolean;
  renderSummary?: (r: PathInspectResult) => ReactNode;
  /** 확인 요청 body에 덧붙는 선택 키: RESULT_FOLDER의 doe_id(phase2.md §12.4), CAD_FILE의 engine(확장자 검사 기준). 값이 바뀌면 이미 확인한 경로를 다시 확인한다 */
  extra?: { doe_id?: string; engine?: Engine };
}) {
  const [result, setResult] = useState<PathInspectResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0); // 늦게 도착한 이전 응답이 최신 확인 결과를 덮지 않게 한다
  const asked = useRef(false); // 현재 경로에 확인 요청을 보낸 적이 있는가(경로를 고치면 false)

  const browse = BROWSE_OF[purpose];
  const setPath = (v: string) => {
    onChange(v);
    asked.current = false;
    seq.current++; // 진행 중이던 이전 경로의 응답은 버린다
    setBusy(false);
    if (result) {
      setResult(null);
      onInspected?.(null);
    }
  };

  const inspect = async (pathArg?: string) => {
    const my = ++seq.current;
    asked.current = true;
    setBusy(true);
    setError(null);
    try {
      const r = await api.inspectPath(studyId, purpose, (pathArg ?? value).trim(), extra);
      if (my !== seq.current) return;
      setResult(r);
      onInspected?.(r);
    } catch (e) {
      if (my !== seq.current) return;
      setResult(null);
      onInspected?.(null);
      setError(errorMessage(e));
    } finally {
      if (my === seq.current) setBusy(false);
    }
  };

  // 업로드 완료(upload-report.md §2.1·§7): complete 응답 path 를 경로 칸에 채우고, 서버가 본 inspect 를 기존 확인 표시와 같게 보인다.
  // RESULT_FOLDER 처럼 doe_id 가 필요한 확인은 complete 에서 형식만 보므로 기존대로 doe_id 를 넣어 한 번 더 확인한다
  const uploaded = (path: string, insp: PathInspectResult | null) => {
    onChange(path);
    seq.current++;
    setError(null);
    setBusy(false);
    if (insp && !extra?.doe_id) {
      asked.current = true;
      setResult(insp);
      onInspected?.(insp);
    } else {
      asked.current = false;
      setResult(null);
      onInspected?.(null);
      if (extra?.doe_id) void inspect(path);
    }
  };

  // extra(엔진 등)가 바뀌면 이전 확인 결과·진행 중 요청은 무효: 초기화하고, 확인을 요청했던 경로면 새 값으로 재확인
  const extraKey = JSON.stringify(extra ?? null);
  const prevKey = useRef(extraKey);
  useEffect(() => {
    if (prevKey.current === extraKey) return;
    prevKey.current = extraKey;
    if (!asked.current) return;
    seq.current++;
    setBusy(false);
    setResult(null);
    setError(null);
    onInspected?.(null);
    if (value.trim()) void inspect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extraKey]);

  return (
    <div className="pathinput">
      <span className="field-label">{label}</span>
      <PathSourceTabs studyId={studyId} purpose={purpose} engine={extra?.engine as "native" | "altair" | undefined} canExecute={canExecute} onUploaded={uploaded}>
        <div className="pathinput-row">
          <input
            type="text"
            className="mono"
            value={value}
            placeholder={placeholder}
            aria-label={label}
            spellCheck={false}
            onChange={(e) => setPath(e.target.value)}
            disabled={!canExecute}
          />
          {browse && (
            <BrowseButton mode={browse.mode} exts={browse.exts} aiOnly={browse.aiOnly} value={value} onPick={setPath} disabled={!canExecute} />
          )}
          <button type="button" className="btn" onClick={() => void inspect()} disabled={!canExecute || busy || !value.trim()}>
            {busy ? "확인 중…" : "확인"}
          </button>
        </div>
        {error && <div className="error-text small" role="alert">{error}</div>}
        {result && (
          <div className={result.ok ? "inspect ok" : "inspect bad"}>
            {renderSummary?.(result)}
            {result.problems.length > 0 && (
              <ul className="problems">
                {result.problems.map((p, i) => (
                  <li key={i}>
                    <code>{p.code}</code> {p.message ?? ""} {p.file && <span className="mono small">{p.file}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </PathSourceTabs>
    </div>
  );
}
