// S15 ④ B "조합 만들기" 표본 방식(phase3.md §20.10): 방식 드롭다운(묶음·순서 §20.4) + 설명 상자 + 방식별 입력.
// 표·① DOE 입력은 BatchSetup이 그린다(기존 그대로). 상태는 BatchSetup이 들고(SamplingState), 값이 바뀌면 onChange로 알린다.
import type { ParamSet } from "../../../api";
import { SamplingDescription } from "../../../components/SamplingDescription";
import { DEFAULT_MAX_RUNS, MULTI_BASELINE_REASON, RECOMMENDED_KIND, SAMPLING_LABEL, SITE_KINDS, calcNote, isSamplingKind, siteGroups, sobolCounts } from "../../../lib/sampling";
import { NativeBatchVars, type NativeBatch } from "./NativeBatchVars";
import { activeNames, contTotal, countText, fullfactRuns, levelOf, sobolDefaultCont, type ContinueCand, type Ranges, type SamplingState } from "./samplingSource";

function Seg<T extends string | number>({ label, value, options, onChange }: { label: string; value: T; options: { key: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.key)} type="button" className={value === o.key ? "on" : ""} aria-pressed={value === o.key} onClick={() => value !== o.key && onChange(o.key)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export interface SamplingPickerProps {
  ps: ParamSet | null;
  state: SamplingState;
  onChange: (next: SamplingState) => void;
  maxRuns?: number;
  /** 이어서 추가 후보(같은 템플릿 Sobol 배치) */
  cands: ContinueCand[];
  /** 고른 후보의 이전 범위(상세 sampling.meta.ranges) — 비활성 입력에 보여 준다 */
  contRanges?: Ranges | null;
  /** Native 템플릿(단일 baseline): 범위 표를 공용 변수 표로 바꾼다(native-vars.md §7.3). 없으면 기존 표. ps는 유효 변수 기준 템플릿 */
  native?: NativeBatch | null;
  /** Native 변수 정의를 불러오는 중 — 기존 표를 잠깐도 보이지 않는다 */
  nativePending?: boolean;
}

export function SamplingPicker({ ps, state, onChange, maxRuns = DEFAULT_MAX_RUNS, cands, contRanges, native, nativePending }: SamplingPickerProps) {
  const set = (patch: Partial<SamplingState>) => onChange({ ...state, ...patch });
  const kind = state.kind;
  const multiBaseline = (ps?.baselines?.length ?? 0) > 1;
  const names = activeNames(ps, state.ranges);
  const k = names.length;
  const cand = state.cont ? (cands.find((c) => c.id === state.contId) ?? null) : null;
  const locked = kind === "sobol" && state.cont; // 이전 시드·범위를 그대로 쓴다
  const isDesign = kind !== "table" && kind !== "train_doe";
  const ff = kind === "fullfact" ? fullfactRuns(state, ps, maxRuns) : null;
  const calc = isDesign && !locked ? calcNote(kind, k, { resolution: state.resolution, levels: ff?.levels, maxRuns }) : null;
  const shown = locked && contRanges ? contRanges : state.ranges;

  const pick = (v: string) => {
    if (!isSamplingKind(v)) return;
    const next: SamplingState = { ...state, kind: v, count: null };
    if (v === "sobol" && state.cont && !cands.length) next.cont = false;
    onChange(next);
  };
  const setRange = (n: string, i: 0 | 1, v: string) => {
    const cur = state.ranges[n] ?? ["", ""];
    set({ ranges: { ...state.ranges, [n]: (i === 0 ? [v, cur[1]] : [cur[0], v]) as [string, string] } });
  };
  const sobolOpts = sobolCounts(maxRuns).filter((n) => !cand || contTotal(cand) % n === 0);
  const sobolValue = Number(countText(state, k, cand, maxRuns));

  return (
    <div className="samp-pick">
      <label className="field">
        <span className="field-label">표본 방식</span>
        <select value={kind} aria-label="표본 방식" onChange={(e) => pick(e.target.value)}>
          {siteGroups("batch").map((g) => (
            <optgroup key={g.label} label={g.label}>
              {g.kinds.map((m) => {
                const blocked = multiBaseline && !SITE_KINDS.batch_multi.includes(m); // DM-C4: 다중 baseline 세트는 층 안 생성기만
                return (
                  <option key={m} value={m} disabled={blocked && m !== kind} title={blocked ? MULTI_BASELINE_REASON : undefined}>
                    {SAMPLING_LABEL[m]}
                    {m === RECOMMENDED_KIND ? " · 추천" : ""}
                    {blocked ? " — 사용 불가" : ""}
                  </option>
                );
              })}
            </optgroup>
          ))}
        </select>
      </label>
      <SamplingDescription id={kind} recommended={kind === RECOMMENDED_KIND} calc={calc} />

      {native && ps && kind === "table" && (
        <div className="samp-sub">
          <NativeBatchVars native={native} ranges={shown} locked onRange={setRange} note={<p className="muted small samp-note">표의 첫 줄은 사용 중인 변수 이름 전부여야 합니다(최소·최대는 쓰지 않음).</p>} />
        </div>
      )}
      {native && ps && kind === "train_doe" && (
        <p className="muted small samp-note" data-testid="vars-from-doe">① DOE의 변수 구성을 그대로 씁니다</p>
      )}
      {isDesign && ps && (
        <div className="samp-sub">
          {nativePending ? (
            <p className="muted small">변수 정의를 불러오는 중…</p>
          ) : native ? (
            <NativeBatchVars
              native={native} ranges={shown} locked={locked} onRange={setRange}
              extra={kind === "fullfact" ? [{ head: "수준", cell: (r) => (names.includes(r.name) ? (
                <input className="num-input" type="number" min={2} max={10} aria-label={`${r.name} 수준`} value={state.levels[r.name] ?? String(levelOf(state, r.name, k, maxRuns))} onChange={(e) => set({ levels: { ...state.levels, [r.name]: e.target.value } })} />
              ) : <span className="muted small">고정</span>) }] : undefined}
            />
          ) : (
            <table className="table compact" aria-label="파라미터 범위">
              <thead>
                <tr>
                  <th>파라미터</th>
                  <th className="num">최소</th>
                  <th className="num">최대</th>
                  {kind === "fullfact" && <th className="num">수준</th>}
                </tr>
              </thead>
              <tbody>
                {ps.parameters.map((p) => (
                  <tr key={p.name}>
                    <td>
                      {p.name} <span className="muted small">{p.unit}</span>
                    </td>
                    <td className="num">
                      <input className="num-input" inputMode="decimal" aria-label={`${p.name} 최소`} value={shown[p.name]?.[0] ?? ""} disabled={locked} onChange={(e) => setRange(p.name, 0, e.target.value)} />
                    </td>
                    <td className="num">
                      <input className="num-input" inputMode="decimal" aria-label={`${p.name} 최대`} value={shown[p.name]?.[1] ?? ""} disabled={locked} onChange={(e) => setRange(p.name, 1, e.target.value)} />
                    </td>
                    {kind === "fullfact" && (
                      <td className="num">
                        {names.includes(p.name) ? (
                          <input
                            className="num-input"
                            type="number"
                            min={2}
                            max={10}
                            aria-label={`${p.name} 수준`}
                            value={state.levels[p.name] ?? String(levelOf(state, p.name, k, maxRuns))}
                            onChange={(e) => set({ levels: { ...state.levels, [p.name]: e.target.value } })}
                          />
                        ) : (
                          <span className="muted small">고정</span>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {kind === "fullfact" && ff && (
            <p className="small samp-note" data-testid="fullfact-runs">
              run 수 = {ff.levels.length ? ff.levels.join(" × ") : "–"} = <b>{ff.product}</b>
              {ff.product > maxRuns && <span className="muted"> (상한 {maxRuns}개 초과 — 수준을 줄이세요)</span>}
            </p>
          )}

          <div className="fill-row">
            {(kind === "lhs" || kind === "lhs_opt" || kind === "halton" || kind === "random") && (
              <label className="inline-field">
                조합 수
                <input className="num-input" inputMode="numeric" value={countText(state, k, null, maxRuns)} onChange={(e) => set({ count: e.target.value })} />
              </label>
            )}
            {kind === "sobol" && (
              <label className="inline-field">
                run 수
                <select value={String(sobolValue)} aria-label="run 수" onChange={(e) => set({ count: e.target.value })}>
                  {!sobolOpts.includes(sobolValue) && <option value={String(sobolValue)}>{sobolValue}</option>}
                  {sobolOpts.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {(kind === "lhs" || kind === "lhs_opt" || kind === "halton" || kind === "random" || kind === "sobol") && (
              <label className="inline-field">
                시드
                <input className="num-input" inputMode="numeric" value={locked ? (cand?.seed != null ? String(cand.seed) : "") : state.seed} disabled={locked} onChange={(e) => set({ seed: e.target.value })} />
              </label>
            )}
            {kind === "lhs_opt" && (
              <Seg
                label="최적화 기준"
                value={state.criterion}
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
                options={[
                  { key: "face", label: "면중심" },
                  { key: "inscribed", label: "내접" },
                ]}
                onChange={(v) => set({ alpha: v })}
              />
            )}
          </div>

          {kind === "sobol" && (
            <div className="samp-sub">
              <label className="check">
                <input
                  type="checkbox"
                  checked={state.cont}
                  disabled={!cands.length}
                  onChange={(e) => {
                    const on = e.target.checked;
                    set({ cont: on, contId: on ? (state.contId && cands.some((c) => c.id === state.contId) ? state.contId : (cands[0]?.id ?? "")) : "", count: null });
                  }}
                />
                이전 Sobol 배치에 이어서 추가
              </label>
              {!cands.length && <p className="muted small samp-note">같은 템플릿의 Sobol 배치가 없습니다.</p>}
              {state.cont && cands.length > 0 && (
                <>
                  <label className="inline-field">
                    이어서 추가할 배치
                    <select value={state.contId} aria-label="이어서 추가할 배치" onChange={(e) => set({ contId: e.target.value, count: null })}>
                      {cands.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.label} · {c.count}개 · 시드 {c.seed ?? "–"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="muted small samp-note">이전 배치의 시드·범위를 그대로 씁니다(입력 비활성){cand ? ` · 이전 합계 ${contTotal(cand)} → 권장 ${sobolDefaultCont(cand, maxRuns)}` : ""}.</p>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
