import { useState, type ReactNode } from "react";
import { api, errorMessage, type PathInspectResult, type PathPurpose } from "../api";
import { BrowseButton } from "./BrowseButton";
import type { PickMode } from "./PathPickerDialog";

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
  /** phase2.md §12.4 RESULT_FOLDER의 doe_id 등 */
  extra?: { doe_id?: string };
}) {
  const [result, setResult] = useState<PathInspectResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const browse = BROWSE_OF[purpose];
  const setPath = (v: string) => {
    onChange(v);
    if (result) {
      setResult(null);
      onInspected?.(null);
    }
  };

  const inspect = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.inspectPath(studyId, purpose, value.trim(), extra);
      setResult(r);
      onInspected?.(r);
    } catch (e) {
      setResult(null);
      onInspected?.(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pathinput">
      <span className="field-label">{label}</span>
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
        <button type="button" className="btn" onClick={inspect} disabled={!canExecute || busy || !value.trim()}>
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
    </div>
  );
}
