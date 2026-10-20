// S18 ①-3 플랫폼 생성 입력(phase3 §23.9): 표본 방식 드롭다운(8종) + 설명 상자(td_*) + 방식별 입력 + "실제 run N개".
// 상태는 DoeGenCard가 들고(PlatformState) 값이 바뀌면 onChange로 알린다. ④ SamplingPicker와 같은 마크업·클래스를 쓴다(S15 재사용).
import { SamplingDescription } from "../../components/SamplingDescription";
import { PLATFORM_GROUPS, RECOMMENDED_KIND, SAMPLING_LABEL, calcNote, isPlatformKind, sobolCounts, tdDescId } from "../../lib/sampling";
import { countText, fullfactLevels, isFreeCount, levelOf, minCount, platformRuns, type PlatformState } from "./doeGenParams";

export function Seg<T extends string | number>({ label, value, options, onChange, disabled }: { label: string; value: T; options: { key: T; label: string; disabled?: boolean; title?: string }[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.key)} type="button" className={value === o.key ? "on" : ""} aria-pressed={value === o.key} disabled={disabled || o.disabled} title={o.title} onClick={() => value !== o.key && onChange(o.key)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export interface DoePlatformFieldsProps {
  state: PlatformState;
  onChange: (next: PlatformState) => void;
  /** ①-2 사용 변수 이름(템플릿 순서) */
  names: string[];
  /** 플랫폼 run 상한 R(`/status.limits.configured.doe_platform_max_runs`) */
  maxRuns: number;
  disabled: boolean;
}

export function DoePlatformFields({ state, onChange, names, maxRuns, disabled }: DoePlatformFieldsProps) {
  const set = (patch: Partial<PlatformState>) => onChange({ ...state, ...patch });
  const kind = state.kind;
  const k = names.length;
  const levels = kind === "fullfact" ? fullfactLevels(state, names, maxRuns) : undefined;
  const calc = calcNote(kind, k, { resolution: state.resolution, levels, maxRuns });
  const runs = platformRuns(state, names, maxRuns);
  const sobolOpts = sobolCounts(maxRuns);
  const sobolValue = Number(countText(state, k, maxRuns));

  return (
    <div className="samp-pick" data-testid="doe-platform">
      <label className="field">
        <span className="field-label">표본 방식</span>
        <select value={kind} aria-label="표본 방식" disabled={disabled} onChange={(e) => isPlatformKind(e.target.value) && onChange({ ...state, kind: e.target.value, count: null })}>
          {PLATFORM_GROUPS.map((g) => (
            <optgroup key={g.label} label={g.label}>
              {g.kinds.map((m) => (
                <option key={m} value={m}>
                  {SAMPLING_LABEL[m]}
                  {m === RECOMMENDED_KIND ? " · 추천" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <SamplingDescription id={tdDescId(kind)} recommended={kind === RECOMMENDED_KIND} calc={calc} />

      <div className="fill-row">
        {(kind === "lhs" || kind === "lhs_opt") && (
          <label className="inline-field">
            run 수
            <input className="num-input" inputMode="numeric" aria-label="run 수" value={countText(state, k, maxRuns)} disabled={disabled} onChange={(e) => set({ count: e.target.value.replace(/[^0-9]/g, "") })} />
          </label>
        )}
        {kind === "sobol" && (
          <label className="inline-field">
            run 수
            <select value={String(sobolValue)} aria-label="run 수" disabled={disabled} onChange={(e) => set({ count: e.target.value })}>
              {!sobolOpts.includes(sobolValue) && <option value={String(sobolValue)}>{sobolValue}</option>}
              {sobolOpts.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        )}
        {(kind === "lhs" || kind === "lhs_opt" || kind === "sobol") && (
          <label className="inline-field">
            시드
            <input className="num-input" inputMode="numeric" aria-label="시드" value={state.seed} disabled={disabled} onChange={(e) => set({ seed: e.target.value.replace(/[^0-9]/g, "") })} />
          </label>
        )}
        {kind === "lhs_opt" && (
          <Seg
            label="최적화 기준"
            value={state.criterion}
            disabled={disabled}
            options={[
              { key: "maximin", label: "최소 거리" },
              { key: "corr", label: "상관 최소" },
            ]}
            onChange={(v) => set({ criterion: v })}
          />
        )}
        {kind === "fracfact" && (
          <Seg
            label="해상도"
            value={state.resolution}
            disabled={disabled}
            options={[
              { key: 5, label: "V" },
              { key: 4, label: "IV" },
            ]}
            onChange={(v) => set({ resolution: v })}
          />
        )}
        {kind === "ccd" && (
          <Seg
            label="CCD α"
            value={state.alpha}
            disabled={disabled}
            options={[
              { key: "face", label: "면중심" },
              { key: "inscribed", label: "내접" },
            ]}
            onChange={(v) => set({ alpha: v })}
          />
        )}
        {kind === "fullfact" &&
          names.map((n) => (
            <label key={n} className="inline-field">
              {n} 수준
              <input
                className="num-input"
                type="number"
                min={2}
                max={10}
                aria-label={`${n} 수준`}
                value={state.levels[n] ?? String(levelOf(state, n, k, maxRuns))}
                disabled={disabled}
                onChange={(e) => set({ levels: { ...state.levels, [n]: e.target.value } })}
              />
            </label>
          ))}
      </div>

      <p className="small samp-note" data-testid="td-runs">
        {runs.n !== null ? (
          <>
            실제 run <b>{runs.n}</b>개
            {runs.over && <span className="muted"> (상한 {maxRuns}개 초과{kind === "fullfact" ? " — 수준을 줄이세요" : ""})</span>}
          </>
        ) : isFreeCount(kind) ? (
          <span className="muted">run 수를 확인하세요(정수, {minCount(kind)} 이상)</span>
        ) : (
          <span className="muted">변수 수가 이 방식의 지원 범위 밖입니다</span>
        )}
      </p>
    </div>
  );
}
