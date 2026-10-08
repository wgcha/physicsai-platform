/** 작은 JSON 트리(접힘). 형식 미확인 산출물 표시용 */
export function JsonTree({ data, depth = 0 }: { data: unknown; depth?: number }) {
  if (data === null || typeof data !== "object") return <span className="mono">{String(data)}</span>;
  const entries = Array.isArray(data) ? data.map((v, i) => [String(i), v] as const) : Object.entries(data as Record<string, unknown>);
  return (
    <ul className="tree">
      {entries.slice(0, 200).map(([k, v]) => (
        <li key={k}>
          {v !== null && typeof v === "object" ? (
            <details open={depth < 1}>
              <summary className="mono">{k}</summary>
              <JsonTree data={v} depth={depth + 1} />
            </details>
          ) : (
            <span>
              <span className="mono muted">{k}: </span>
              <span className="mono">{String(v)}</span>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
