/** 작은 CSV 표 보기(따옴표 처리 포함, 최대 500행) */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      cell = "";
      if (row.some((x) => x !== "")) rows.push(row);
      row = [];
    } else cell += c;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    if (row.some((x) => x !== "")) rows.push(row);
  }
  return rows;
}

export function CsvView({ text, maxRows = 500, label = "CSV" }: { text: string; maxRows?: number; label?: string }) {
  const rows = parseCsv(text);
  if (!rows.length) return <p className="muted small">빈 파일</p>;
  const [head, ...body] = rows;
  return (
    <div className="table-wrap csv-view">
      <table className="table compact" aria-label={label}>
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.slice(0, maxRows).map((r, i) => (
            <tr key={i}>
              {head.map((_, j) => (
                <td key={j} className={/^-?[\d.]+(e[-+]?\d+)?$/i.test(r[j] ?? "") ? "num" : ""}>
                  {r[j] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {body.length > maxRows && <p className="muted small">앞 {maxRows}행만 표시</p>}
    </div>
  );
}
