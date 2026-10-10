import { useEffect, useState } from "react";
import { api, type ParamSet, type SampleRow } from "../../api";

const MAX_SAMPLE_ROWS = 5000;

export function useSamples(ps: ParamSet | null) {
  const [rows, setRows] = useState<SampleRow[]>([]);
  useEffect(() => {
    setRows([]);
    if (!ps || ps.sample_count === 0) return;
    let alive = true;
    (async () => {
      const all: SampleRow[] = [];
      let cursor: string | null | undefined = undefined;
      do {
        const page = await api.samples(ps.id, 200, cursor);
        all.push(...page.rows);
        cursor = page.next_cursor;
      } while (cursor && all.length < MAX_SAMPLE_ROWS && alive);
      if (alive) setRows(all);
    })().catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [ps?.id]);
  return rows;
}
