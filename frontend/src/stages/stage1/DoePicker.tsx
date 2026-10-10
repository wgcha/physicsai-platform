import { Field } from "../../components/ui";
import { fmtTime } from "../../lib/format";
import { useTrain } from "./TrainContext";

export function DoePicker({ label = "DOE" }: { label?: string }) {
  const { does, doe, selectDoe } = useTrain();
  const ready = does.filter((d) => d.status === "READY");
  if (!ready.length) return <p className="muted">준비된 DOE가 없습니다. ①-3에서 입력을 먼저 생성하세요.</p>;
  return (
    <Field label={label}>
      <select value={doe?.id ?? ""} onChange={(e) => selectDoe(e.target.value)} aria-label={label}>
        {ready.map((d) => (
          <option key={d.id} value={d.id}>
            {d.doe_label} · run {d.run_count} · {fmtTime(d.created_at)}
          </option>
        ))}
      </select>
    </Field>
  );
}

/** run 상태 막대(§14.2 ①-4) */
