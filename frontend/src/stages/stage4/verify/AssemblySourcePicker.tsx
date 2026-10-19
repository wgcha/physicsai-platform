// FEM 검증 "조립 원본" 선택기(phase3 §21.3.3·§21.3.11): 라디오 3개 — 예측 입력 그대로(조립 상태일 때만) · ① DOE 조립 폴더 · 직접 지정(경로 + 찾아보기(SPDM 포함) + 확인).
import { useEffect, useState } from "react";
import { api, errorMessage, type TrainDoe } from "../../../api";
import { femVerifyApi, type AssemblyPlan } from "../../../api/femVerify";
import { useStudy } from "../../../app/StudyContext";
import { PathPickerDialog } from "../../../components/PathPickerDialog";
import { mdHm } from "../history/runListText";

export type AssemblyKind = "predict_input" | "train_doe" | "custom";
export interface AssemblyChoice {
  kind: AssemblyKind;
  doeId: string | null;
  /** 입력란 값 */
  path: string;
  /** 확인(paths/inspect)을 마친 경로 — 미리보기·요청은 이 값만 쓴다 */
  confirmedPath: string | null;
}

export const PREDICT_INPUT_OFF_TEXT = "쿠션 메시만 있는 예측입니다";

/** DOE 이름 "DOE-001"(Study 안 생성순) */
export function doeName(all: TrainDoe[], id: string): string {
  const i = [...all].sort((a, b) => a.created_at.localeCompare(b.created_at)).findIndex((d) => d.id === id);
  return `DOE-${String(i + 1).padStart(3, "0")}`;
}

/** 직접 지정 확인 요약 한 줄 "✓ starter X · rad N · inc M · RENUM 있음" */
export function assemblySummaryLine(p: Pick<AssemblyPlan, "starter" | "rad" | "inc_count" | "renum_csv">, ok: boolean): string {
  const head = ok && p.starter ? `✓ starter ${p.starter}` : p.starter ? p.starter : "starter 없음";
  return `${head} · rad ${p.rad.length} · inc ${p.inc_count} · RENUM ${p.renum_csv ? "있음" : "없음"}`;
}

export function AssemblySourcePicker({
  value,
  onChange,
  predictInputOk,
  canEdit,
}: {
  value: AssemblyChoice;
  onChange: (v: AssemblyChoice) => void;
  /** 이 예측 입력이 조립 상태일 때만 true */
  predictInputOk: boolean;
  canEdit: boolean;
}) {
  const { study } = useStudy();
  const [does, setDoes] = useState<TrainDoe[] | null>(null);
  const [info, setInfo] = useState<{ plan: AssemblyPlan; ok: boolean; warnings: { code: string; message: string }[]; problems: { code: string; message: string }[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [browse, setBrowse] = useState(false);

  useEffect(() => {
    api.trainDoes(study.id).then(setDoes).catch(() => setDoes([]));
  }, [study.id]);
  const ready = (does ?? []).filter((d) => d.status === "READY").sort((a, b) => b.created_at.localeCompare(a.created_at));

  const set = (p: Partial<AssemblyChoice>) => onChange({ ...value, ...p });
  const pick = (kind: AssemblyKind) => {
    if (kind === "train_doe") set({ kind, doeId: value.doeId ?? ready[0]?.id ?? null });
    else set({ kind });
  };
  const setPath = (v: string) => {
    setInfo(null);
    setError(null);
    set({ kind: "custom", path: v, confirmedPath: null });
  };
  const inspect = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await femVerifyApi.inspectAssembly(study.id, value.path.trim());
      const sum = (r.summary ?? {}) as unknown as AssemblyPlan & { warnings?: { code: string; message: string }[] };
      setInfo({ plan: sum, ok: r.ok, warnings: sum.warnings ?? [], problems: (r.problems ?? []).map((p) => ({ code: p.code, message: p.message ?? p.code })) });
      set({ kind: "custom", confirmedPath: r.ok ? value.path.trim() : null });
    } catch (e) {
      setInfo(null);
      set({ confirmedPath: null });
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <fieldset className="fv-section" data-testid="assembly-picker">
      <legend className="field-label">조립 원본</legend>
      <div className="fv-radios" role="radiogroup" aria-label="조립 원본">
        <label className={`fv-radio${predictInputOk ? "" : " off"}`}>
          <input type="radio" name="fv-assem" checked={value.kind === "predict_input"} disabled={!canEdit || !predictInputOk} onChange={() => pick("predict_input")} />
          예측 입력 그대로
          {!predictInputOk && <span className="muted small">{PREDICT_INPUT_OFF_TEXT}</span>}
        </label>

        <label className="fv-radio">
          <input type="radio" name="fv-assem" checked={value.kind === "train_doe"} disabled={!canEdit || !ready.length} onChange={() => pick("train_doe")} />
          ① DOE 조립 폴더
          <select
            aria-label="① DOE 선택"
            value={value.doeId ?? ready[0]?.id ?? ""}
            disabled={!canEdit || !ready.length}
            onChange={(e) => set({ kind: "train_doe", doeId: e.target.value })}
          >
            {!ready.length && <option value="">준비된 ① DOE 없음</option>}
            {ready.map((d) => (
              <option key={d.id} value={d.id}>
                {doeName(does ?? [], d.id)} · {mdHm(d.created_at).slice(0, 5)}
              </option>
            ))}
          </select>
        </label>

        <div className="fv-radio">
          <label className="fv-radio">
            <input type="radio" name="fv-assem" checked={value.kind === "custom"} disabled={!canEdit} onChange={() => pick("custom")} />
            직접 지정
          </label>
          {value.kind === "custom" && (
            <div className="pathinput-row">
              <input type="text" className="mono" aria-label="조립 원본 경로" value={value.path} spellCheck={false} disabled={!canEdit} placeholder="E:/shared/AI_WORK/…/assem_v2 또는 SPDM 폴더" onChange={(e) => setPath(e.target.value)} />
              <button type="button" className="btn ghost" disabled={!canEdit} onClick={() => setBrowse(true)}>
                찾아보기
              </button>
              <button type="button" className="btn" disabled={!canEdit || busy || !value.path.trim()} onClick={() => void inspect()}>
                {busy ? "확인 중…" : "확인"}
              </button>
            </div>
          )}
        </div>
      </div>
      {value.kind === "custom" && error && <div className="error-text small" role="alert">{error}</div>}
      {value.kind === "custom" && info && (
        <div data-testid="assembly-summary">
          <p className={`small prepared-summary${info.ok ? " ok" : ""}`}>{assemblySummaryLine(info.plan, info.ok)}</p>
          <ul className="fv-notes">
            {[...info.problems, ...info.warnings].map((p, i) => (
              <li key={i} className="muted small" data-code={p.code}>
                {p.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {browse && (
        <PathPickerDialog
          title="조립 원본 폴더 고르기"
          mode="dir"
          includeSpdm
          initialPath={value.path}
          onCancel={() => setBrowse(false)}
          onPick={(p) => {
            setBrowse(false);
            setPath(p);
          }}
        />
      )}
    </fieldset>
  );
}
