import { useEffect, useState } from "react";
import { api, errorMessage, type CategoryKey, type StorageCategory, type StorageReport } from "../../api";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { NO_PERMISSION_TIP } from "../../components/ui";
import { fmtBytes } from "../../lib/format";
import { cleanupBlockReason, cleanupDialogBody, selectionTotals } from "./storage";

/** phase3.md §5.8 정리: 범주 선택 → 미리보기 → 확인 대화상자 → STUDY_CLEANUP 작업 생성 */
export function CleanupPreview({
  studyId,
  report,
  canExecute,
  onStarted,
}: {
  studyId: string;
  report: StorageReport;
  canExecute: boolean;
  onStarted: () => void;
}) {
  const cats = report.scan?.categories ?? [];
  const [selected, setSelected] = useState<Set<CategoryKey>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scanId = report.scan?.job_id ?? null;

  useEffect(() => setSelected(new Set()), [scanId]);

  const toggle = (k: CategoryKey) => {
    const n = new Set(selected);
    if (n.has(k)) n.delete(k);
    else n.add(k);
    setSelected(n);
  };
  const { count, bytes } = selectionTotals(cats, selected);
  const reason = canExecute ? cleanupBlockReason(report, count) : NO_PERMISSION_TIP;

  const run = async () => {
    setError(null);
    try {
      await api.createJob(studyId, "STUDY_CLEANUP", { scan_job_id: scanId, categories: cats.filter((c) => selected.has(c.key)).map((c) => c.key) });
      setConfirming(false);
      onStarted();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  if (!report.scan) return null;
  return (
    <div className="cleanup">
      <h4 className="cleanup-title">정리</h4>
      <ul className="cleanup-cats">
        {cats.map((c) => (
          <li key={c.key}>
            <label className={c.item_count ? undefined : "muted"}>
              <input type="checkbox" checked={selected.has(c.key)} disabled={!c.item_count} onChange={() => toggle(c.key)} />
              <strong>{c.label}</strong> <span className="muted small">{c.item_count}개 · {fmtBytes(c.total_bytes)}</span>
            </label>
            <div className="muted small cleanup-impact">{c.impact}</div>
          </li>
        ))}
      </ul>
      {count > 0 && <PreviewTable cats={cats.filter((c) => selected.has(c.key))} />}
      <div className="run-action-row">
        <span data-testid="cleanup-total">
          선택 {count}개 · {fmtBytes(bytes)}
        </span>
        <span className="spacer" />
        <span title={reason ?? undefined}>
          <button type="button" className="btn primary" disabled={!!reason} onClick={() => setConfirming(true)}>
            백업 폴더로 옮기기
          </button>
        </span>
      </div>
      {reason && count > 0 && <div className="muted small">{reason}</div>}
      {confirming && (
        <ConfirmDialog
          title="Study 정리"
          body={cleanupDialogBody(cats, selected)}
          confirmLabel="옮기기"
          onConfirm={run}
          onCancel={() => {
            setConfirming(false);
            setError(null);
          }}
          error={error}
        />
      )}
    </div>
  );
}

function PreviewTable({ cats }: { cats: StorageCategory[] }) {
  return (
    <div className="cleanup-preview" aria-label="정리 미리보기">
      {cats.map((c) => (
        <details key={c.key} open>
          <summary>
            {c.label} — {c.item_count}개 · {fmtBytes(c.total_bytes)}
            {c.truncated && <span className="warn-text small"> · 상위 {c.item_count}개만 표시·이동됩니다</span>}
          </summary>
          <div className="table-wrap">
            <table className="table compact" aria-label={`${c.label} 항목`}>
              <thead>
                <tr>
                  <th>상대경로</th>
                  <th>크기</th>
                  <th>비고</th>
                </tr>
              </thead>
              <tbody>
                {c.items.map((it) => (
                  <tr key={it.rel}>
                    <td className="ellipsis mono" title={it.rel}>
                      {it.rel}
                    </td>
                    <td>{fmtBytes(it.bytes)}</td>
                    <td className="small">{it.note ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}
    </div>
  );
}
