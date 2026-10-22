// S18 ①-3 플랫폼 생성 입력(phase3 §23.9): 표본 방식 드롭다운(8종) + 설명 상자(td_*) + 방식별 입력 + "실제 run N개".
// 상태는 DoeGenCard가 들고(PlatformState) 값이 바뀌면 onChange로 알린다. ④ SamplingPicker와 같은 마크업·클래스를 쓴다(S15 재사용).
import type { ChangeEvent, ReactNode } from "react";
import { SamplingDescription } from "../../components/SamplingDescription";
import { RECOMMENDED_KIND, SAMPLING_LABEL, calcNote, isPlatformKind, siteGroups, sobolCounts, tdDescId, unavailableNote, type NameRanges, type SamplingKind, type SiteId } from "../../lib/sampling";
import { REUSE_LABEL } from "./ReuseDoePicker";
import { countText, fullfactLevels, hasSeed, isFreeCount, levelOf, minCount, platformRuns, tableCheck, type PlatformState } from "./doeGenParams";

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
  /** "다른 DOE 표본표 재사용" 선택지(켜면 방식별 입력 대신 panel을 보인다). blocked = 선택 불가 사유 */
  reuse?: { on: boolean; setOn: (on: boolean) => void; panel: ReactNode; blocked?: string | null };
  /** 방식 목록을 정하는 지점(doe-methods.md §3 SITE_KINDS). 기본 train_platform */
  site?: SiteId;
  /** 목록에는 두되 이 밖의 방식은 회색(선택 불가)으로 둔다 — 다중 baseline 세트(DM-C4) */
  allowed?: SamplingKind[];
  blockedReason?: string;
  /** 표 붙여넣기(table)의 학습 범위(변수 이름 → [최소, 최대]). 이 밖이면 막는다(TABLE_OUT_OF_RANGE) */
  ranges?: NameRanges | null;
  tableMaxBytes?: number;
}

export function DoePlatformFields({ state, onChange, names, maxRuns, disabled, reuse, site = "train_platform", allowed, blockedReason, ranges = null, tableMaxBytes }: DoePlatformFieldsProps) {
  const set = (patch: Partial<PlatformState>) => onChange({ ...state, ...patch });
  const kind = state.kind;
  const k = names.length;
  const levels = kind === "fullfact" ? fullfactLevels(state, names, maxRuns) : undefined;
  const calc = calcNote(kind, k, { resolution: state.resolution, levels, maxRuns });
  const tbl = { ranges, maxBytes: tableMaxBytes };
  const runs = platformRuns(state, names, maxRuns, tbl);
  const tcheck = kind === "table" ? tableCheck(state, names, maxRuns, tbl) : null;
  const recommended = kind === RECOMMENDED_KIND && site === "train_platform";
  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) set({ text: await f.text() }); // 브라우저 안에서 읽기만(업로드 없음)
  };
  const sobolOpts = sobolCounts(maxRuns);
  const sobolValue = Number(countText(state, k, maxRuns));

  return (
    <div className="samp-pick" data-testid="doe-platform">
      <label className="field">
        <span className="field-label">표본 방식</span>
        <select
          value={reuse?.on ? "train_doe" : kind}
          aria-label="표본 방식"
          disabled={disabled}
          onChange={(e) => {
            if (e.target.value === "train_doe") return reuse?.setOn(true);
            if (!isPlatformKind(e.target.value)) return;
            reuse?.setOn(false);
            onChange({ ...state, kind: e.target.value, count: null });
          }}
        >
          {siteGroups(site).map((g) => (
            <optgroup key={g.label} label={g.label}>
              {g.kinds.map((m) => {
                if (m === "train_doe") {
                  if (!reuse) return null;
                  return (
                    <option key={m} value={m} disabled={!!reuse.blocked} title={reuse.blocked ?? undefined}>
                      {REUSE_LABEL}
                      {reuse.blocked ? " — 사용 불가" : ""}
                    </option>
                  );
                }
                const blocked = !!allowed && !allowed.includes(m);
                const note = blocked ? "— 사용 불가" : unavailableNote(m, names.length, maxRuns);
                return (
                  <option key={m} value={m} disabled={!!note && m !== kind} title={blocked ? blockedReason : undefined}>
                    {SAMPLING_LABEL[m]}
                    {m === RECOMMENDED_KIND && site === "train_platform" ? " · 추천" : ""}
                    {note ? ` ${note}` : ""}
                  </option>
                );
              })}
            </optgroup>
          ))}
        </select>
      </label>
      {reuse?.on ? (
        reuse.panel
      ) : (
        <>
      <SamplingDescription id={tdDescId(kind)} recommended={recommended} calc={calc} />

      <div className="fill-row">
        {(kind === "lhs" || kind === "lhs_opt" || kind === "halton" || kind === "random") && (
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
        {hasSeed(kind) && (
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

      {kind === "table" && (
        <div className="samp-sub" data-testid="td-table">
          <label className="field">
            <span className="field-label">조합 표(첫 줄 = 사용 파라미터 이름 전부, 탭·쉼표 구분, 값은 학습 범위 안)</span>
            <textarea className="mono batch-text" rows={6} aria-label="표 붙여넣기" value={state.text} disabled={disabled} placeholder={names.join("\t")} onChange={(e) => set({ text: e.target.value })} />
          </label>
          <label className="field">
            <span className="field-label">CSV 파일 열기</span>
            <input type="file" accept=".csv,.tsv,.txt" aria-label="CSV 파일 열기" disabled={disabled} onChange={onFile} />
          </label>
          {state.text.trim() !== "" && tcheck && tcheck.problems.length > 0 && (
            <ul className="problems small error-text" data-testid="td-table-problems" role="alert">
              {tcheck.problems.slice(0, 3).map((p, i) => (
                <li key={i} data-code={p.code}>
                  {p.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="small samp-note" data-testid="td-runs">
        {runs.n !== null ? (
          <>
            실제 run <b>{runs.n}</b>개
            {runs.over && <span className="muted"> (상한 {maxRuns}개 초과{kind === "fullfact" ? " — 수준을 줄이세요" : ""})</span>}
          </>
        ) : kind === "table" ? (
          <span className="muted">표를 붙여넣으면 행 수가 run 수가 됩니다(2~{maxRuns}행)</span>
        ) : isFreeCount(kind) ? (
          <span className="muted">run 수를 확인하세요(정수, {minCount(kind)} 이상, {maxRuns} 이하)</span>
        ) : (
          <span className="muted">변수 수가 이 방식의 지원 범위 밖입니다</span>
        )}
      </p>
        </>
      )}
    </div>
  );
}
