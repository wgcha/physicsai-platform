// SM-C7 hold ρ·b 고급 입력(접힘, 숫자 2개) — ①-2 파라미터 표·④ 피처 표가 같이 쓴다. 빈칸 = 기본(3·8), 키를 보내지 않는다.
import { Advanced } from "../../components/ui";
import { HOLD_DEFAULTS, HOLD_PARAM_LABEL, parseHoldNum, type HoldKey } from "../../lib/shellPolicy";

export const HOLD_KEYS: HoldKey[] = ["ring_mm", "blend_mm"];
export const holdParamError = (key: HoldKey, raw: string): string | null => {
  const r = parseHoldNum(raw, key);
  return "error" in r ? r.error : null;
};

export function HoldParams({ values, onChange, disabled }: { values: Record<HoldKey, string>; onChange: (k: HoldKey, v: string) => void; disabled: boolean }) {
  return (
    <Advanced label="체결 보스 고정 옵션">
      <div className="run-action-row" data-testid="hold-params">
        {HOLD_KEYS.map((k) => {
          const err = holdParamError(k, values[k]);
          return (
            <label key={k} className="field">
              <span className="field-label">{HOLD_PARAM_LABEL[k]}</span>
              <input className="num-input" aria-label={HOLD_PARAM_LABEL[k]} inputMode="decimal" value={values[k]} placeholder={`기본 ${HOLD_DEFAULTS[k]}`} disabled={disabled} onChange={(e) => onChange(k, e.target.value)} />
              {err && <span className="error-text small">{err}</span>}
            </label>
          );
        })}
      </div>
    </Advanced>
  );
}
