// 형상 엔진 2단 선택 [SimLab | native](geometry-engine.md §8): 기본 = /status.geometry.engine_default, native 불가면 비활성 + 사유.
import type { Engine, ParamSet } from "../api";
import { useApp } from "../app/AppContext";
import { ENGINE_LABEL } from "../lib/geometry";

export function useGeometryStatus(): { engineDefault: Engine; nativeAvailable: boolean; reason: string | null } {
  const g = useApp().status?.geometry;
  const nativeAvailable = g ? !!g.native_available : false;
  const def: Engine = g?.engine_default === "native" && nativeAvailable ? "native" : "altair";
  return { engineDefault: def, nativeAvailable, reason: g?.reason ?? (g ? null : "서버가 native 형상 엔진을 지원하지 않습니다") };
}

export function EngineSelect({ value, onChange, disabled }: { value: Engine; onChange: (e: Engine) => void; disabled?: boolean }) {
  const { nativeAvailable, reason } = useGeometryStatus();
  return (
    <div className="field">
      <span className="field-label">형상 엔진</span>
      <div className="run-action-row">
        <div className="seg" role="radiogroup" aria-label="형상 엔진">
          {(["altair", "native"] as Engine[]).map((e) => (
            <button
              key={e}
              type="button"
              role="radio"
              aria-checked={value === e}
              className={value === e ? "on" : ""}
              disabled={disabled || (e === "native" && !nativeAvailable)}
              title={e === "native" && !nativeAvailable ? reason ?? undefined : undefined}
              onClick={() => onChange(e)}
            >
              {ENGINE_LABEL[e]}
            </button>
          ))}
        </div>
        {!nativeAvailable && reason && <span className="muted small" data-testid="native-off-reason">native 불가: {reason}</span>}
      </div>
    </div>
  );
}

/** 엔진 배지(§7.7 세트·데이터셋·모델 목록). 엔진을 모르면(null) 표시 없음 */
export function EngineBadge({ engine }: { engine: Engine | null | undefined }) {
  if (!engine) return null;
  return (
    <span className={`pill${engine === "native" ? " run" : ""}`} data-testid="engine-badge">
      {ENGINE_LABEL[engine]}
    </span>
  );
}

/** 엔진 혼용 안내(§7.7): 모델 engine이 NULL이 아니고 템플릿 engine과 다르면 서버가 409 ENGINE_MISMATCH */
export function EngineMismatchNote({ modelEngine, ps }: { modelEngine: Engine | null | undefined; ps: Pick<ParamSet, "engine"> | null }) {
  if (!ps || !modelEngine || modelEngine === ps.engine) return null;
  return (
    <p className="warn-text small" role="note" data-testid="engine-mismatch">
      모델({ENGINE_LABEL[modelEngine]})과 템플릿({ENGINE_LABEL[ps.engine]})의 형상 엔진이 다릅니다 — 같은 엔진의 모델·템플릿을 고르세요.
    </p>
  );
}
