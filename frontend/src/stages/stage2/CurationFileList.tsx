import { useEffect, useState } from "react";
import { api, type CurationFile } from "../../api";

export function CurationFileList({ curationId, onlyFailed }: { curationId: string; onlyFailed?: boolean }) {
  const [items, setItems] = useState<CurationFile[] | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .curationFiles(curationId, { ok: onlyFailed ? false : undefined, limit: 200 })
      .then((r) => alive && setItems(r.items))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [curationId, onlyFailed]);
  if (!items) return <span className="muted small">불러오는 중…</span>;
  if (!items.length) return <span className="muted small">없음</span>;
  return (
    <table className="table compact" aria-label="결과 파일 목록">
      <thead>
        <tr>
          <th>run 폴더</th>
          <th>입력</th>
          <th>출력</th>
          <th className="num">종료코드</th>
        </tr>
      </thead>
      <tbody>
        {items.map((f) => (
          <tr key={`${f.run_folder}/${f.input_name}`}>
            <td className="mono small">{f.run_folder}</td>
            <td className="mono small">{f.input_name}</td>
            <td className="mono small">{f.output_name ?? <span className="error-text">없음</span>}</td>
            <td className="num small">{f.exit_code ?? "–"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
