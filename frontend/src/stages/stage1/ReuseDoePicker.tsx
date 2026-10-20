// ①-3 "다른 DOE 표본표 재사용"(equiv-check.md EQ-C1 4): 같은 스터디 DOE 목록에서 고른다.
// 파라미터 이름 집합이 지금 대상과 같은 DOE만 활성 — 다르면 비활성 + 사유. 이름은 DOE 샘플 표(columns)에서 읽는다.
import { useEffect, useState } from "react";
import { api, type TrainDoe } from "../../api";
import { fmtTime } from "../../lib/format";
import { reuseParamNames, reuseState } from "./doeGenParams";

export const REUSE_LABEL = "다른 DOE 표본표 재사용";

/** 후보 DOE들의 파라미터 이름(샘플 표 columns). 읽는 중 = 키 없음, 읽을 수 없음 = null */
export function useDoeParamNames(does: TrainDoe[]): Record<string, string[] | null> {
  const [cols, setCols] = useState<Record<string, string[] | null>>({});
  useEffect(() => {
    let alive = true;
    for (const d of does) {
      if (d.status !== "READY" || !(d.sample_status === "PARSED" || d.sample_status === "PARTIAL") || d.id in cols) continue;
      api
        .doeSamples(d.id, 1)
        .then((p) => alive && setCols((c) => ({ ...c, [d.id]: reuseParamNames(p.columns) })))
        .catch(() => alive && setCols((c) => ({ ...c, [d.id]: null })));
    }
    return () => {
      alive = false;
    };
  }, [does]); // eslint-disable-line react-hooks/exhaustive-deps
  return cols;
}

export function ReuseDoePicker({ does, names, doeId, onChange, disabled, blocked }: { does: TrainDoe[]; names: string[]; doeId: string; onChange: (id: string) => void; disabled: boolean; blocked?: string | null }) {
  const cols = useDoeParamNames(does);
  return (
    <div data-testid="doe-reuse">
      <label className="field">
        <span className="field-label">표본표를 가져올 DOE</span>
        <select aria-label="재사용할 DOE" value={doeId} disabled={disabled || !!blocked} onChange={(e) => onChange(e.target.value)}>
          <option value="">DOE를 고르세요</option>
          {does.map((d) => {
            const st = reuseState(d, cols[d.id], names);
            return (
              <option key={d.id} value={d.id} disabled={!st.ok}>
                {d.doe_label} · run {d.run_count ?? "–"}개 · {fmtTime(d.created_at)}
                {st.reason ? ` — ${st.reason}` : ""}
              </option>
            );
          })}
        </select>
      </label>
      {blocked && <p className="warn-text small" data-testid="reuse-blocked">{blocked}</p>}
      {does.length === 0 && <p className="muted small">이 스터디에 만든 DOE가 없습니다.</p>}
      <p className="muted small" data-testid="reuse-help">
        ⑤ 등가성 판정에서 같은 입력으로 A·B를 비교할 때 씁니다 — 원본의 표본값과 run 이름을 그대로 가져옵니다(파라미터 이름 집합이 같아야 함).
      </p>
    </div>
  );
}
