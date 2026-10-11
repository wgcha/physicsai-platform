import { useState } from "react";
import type { StorageScan } from "../../api";
import { fmtBytes, fmtTime } from "../../lib/format";
import { groupFolders } from "./storage";

/** phase3.md §5.8 단계별 막대(크기 비례 + 수치 라벨, 펼치면 폴더 세부) */
export function StorageBars({ scan }: { scan: StorageScan }) {
  const groups = groupFolders(scan.folders);
  const max = Math.max(1, ...groups.map((g) => g.bytes));
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="storage-bars" aria-label="단계별 용량">
      {groups.map((g) => (
        <div key={g.key} className="storage-bar-row">
          <button
            type="button"
            className="storage-bar-label btn ghost small"
            aria-expanded={open === g.key}
            disabled={!g.folders.length}
            onClick={() => setOpen(open === g.key ? null : g.key)}
          >
            {g.label}
          </button>
          <div className="storage-bar-track" aria-hidden="true">
            <div className={`storage-bar-fill${g.key === "backup" ? " is-backup" : ""}`} style={{ width: `${(100 * g.bytes) / max}%` }} />
          </div>
          <span className="storage-bar-value">
            {fmtBytes(g.bytes)} · {g.files}개
          </span>
          {open === g.key && (
            <ul className="storage-bar-detail">
              {g.folders.map((f) => (
                <li key={f.key}>
                  <span className="mono">{f.key}</span> {fmtBytes(f.bytes)} · {f.files}개
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

export function TopFiles({ files }: { files: StorageScan["top_files"] }) {
  if (!files.length) return null;
  return (
    <div className="table-wrap">
      <table className="table compact" aria-label="큰 파일">
        <thead>
          <tr>
            <th>상대경로</th>
            <th>크기</th>
            <th>수정 시각</th>
          </tr>
        </thead>
        <tbody>
          {files.map((f) => (
            <tr key={f.rel}>
              <td className="ellipsis mono" title={f.rel}>
                {f.in_backup && <span className="storage-tag">백업</span>} {f.rel}
              </td>
              <td>{fmtBytes(f.bytes)}</td>
              <td>{fmtTime(f.modified_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
