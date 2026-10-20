// ⑥ 새 최적화 ⑤ 설정의 알고리즘·검증 방식·고급 옵션(opt-native §10): 알고리즘 드롭다운(목적 수에 맞지 않으면 비활성 + 툴팁),
// 검증 방식 라디오(대리모델만이면 안내 한 줄), 고급 옵션 <details>(GA·NSGA-II일 때만, 자리표시자 = /status 기본값, 기본값으로).
import { Field } from "../../../components/ui";
import {
  ALGO_LABEL, EMPTY_ALGO, NONE_NOTE, algoTip, defaultPopSize,
  type AlgoDefaults, type AlgoForm, type Algorithm, type Verification,
} from "./soRules";

const ALGOS: Algorithm[] = ["ego", "ga", "nsga2"];

export function AlgorithmField({ value, nObj, onChange, note }: { value: Algorithm; nObj: number; onChange: (a: Algorithm) => void; note: string | null }) {
  return (
    <Field label="알고리즘" hint={note ? <span className="muted" data-testid="algo-revert-note">{note}</span> : undefined}>
      <select value={value} onChange={(e) => onChange(e.target.value as Algorithm)} aria-label="알고리즘" data-testid="algo-select">
        {ALGOS.map((a) => {
          const tip = algoTip(a, nObj);
          return (
            <option key={a} value={a} disabled={!!tip} title={tip ?? undefined}>
              {ALGO_LABEL[a]}{tip ? ` — ${tip}` : ""}
            </option>
          );
        })}
      </select>
    </Field>
  );
}

export function VerificationField({ value, onChange }: { value: Verification; onChange: (v: Verification) => void }) {
  return (
    <Field label="검증 방식">
      <div className="seg" role="radiogroup" aria-label="검증 방식">
        {(["loop", "none"] as const).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>
            {k === "loop" ? "반복 검증(기본)" : "대리모델만(검증 없음)"}
          </button>
        ))}
      </div>
    </Field>
  );
}

export function NoneNote() {
  return <p className="muted small" data-testid="none-note">{NONE_NOTE}</p>;
}

const FIELDS: { key: keyof AlgoForm; label: string }[] = [
  { key: "pop_size", label: "집단 크기" },
  { key: "generations", label: "세대 수" },
  { key: "crossover_prob", label: "교차 확률" },
  { key: "mutation_prob", label: "변이 확률" },
  { key: "eta_c", label: "η_c(SBX)" },
  { key: "eta_m", label: "η_m(다항 변이)" },
];

/** 고급 옵션(기본 접힘). defs = /status.surrogate_opt.algo_defaults[algorithm], nG = 자유 변수 수(집단·변이 기본 식) */
export function AlgoOptions({ algorithm, value, onChange, defs, nG, issues }: {
  algorithm: Algorithm; value: AlgoForm; onChange: (f: AlgoForm) => void; defs: AlgoDefaults | undefined; nG: number; issues: string[];
}) {
  if (algorithm === "ego") return null;
  const ph: Record<keyof AlgoForm, string> = {
    pop_size: String(defs?.pop_size ?? defaultPopSize(algorithm, Math.max(nG, 1))),
    generations: String(defs?.generations ?? (algorithm === "ga" ? 150 : 200)),
    crossover_prob: String(defs?.crossover_prob ?? 0.9),
    mutation_prob: defs?.mutation_prob != null ? String(defs.mutation_prob) : `1/n${nG ? ` = ${(1 / nG).toFixed(3)}` : ""}`,
    eta_c: String(defs?.eta_c ?? (algorithm === "ga" ? 15 : 20)),
    eta_m: String(defs?.eta_m ?? 20),
  };
  return (
    <details className="advanced" data-testid="algo-options">
      <summary>고급 옵션({algorithm === "ga" ? "GA" : "NSGA-II"})</summary>
      <div className="advanced-body">
        <div className="form-grid">
          {FIELDS.map((f) => (
            <Field key={f.key} label={f.label}>
              <input className="num" value={value[f.key]} placeholder={ph[f.key]} aria-label={f.label}
                onChange={(e) => onChange({ ...value, [f.key]: e.target.value.trim() })} />
            </Field>
          ))}
        </div>
        <div className="run-action-row">
          <button type="button" className="btn small" onClick={() => onChange({ ...EMPTY_ALGO })}>기본값으로</button>
          <span className="muted small">빈칸 = 기본값(변이 확률 빈칸 = 1/변수 수)</span>
        </div>
        {issues.map((m, i) => <p key={i} className="error-text small" data-testid="algo-issue">{m}</p>)}
      </div>
    </details>
  );
}
