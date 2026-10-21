import { useState, type ChangeEvent } from "react";
import { api, errorMessage, type Engine, type ParamSetDiscover } from "../../api";
import { BrowseButton } from "../../components/BrowseButton";
import { EngineSelect, useGeometryStatus } from "../../components/EngineSelect";
import { JobInline } from "../../components/ui";
import { useLatestJob } from "../../hooks/useLatestJob";
import { isTerminal } from "../../lib/format";

type Choice = { cad: string; radioss_assem: string };
/** 조립 폴더 "없음" 선택값(S9 §14.4: choice.radioss_assem = null → mesh_only) */
export const ASSEM_NONE = "__none__";
export const ASSEM_NONE_LABEL = "없음(쿠션만 — 메시로 바로 예측)";
export const ASSEM_ZERO_TEXT = "조립 폴더 없음 — 메시 단독 템플릿으로 등록됩니다";
/** geometry-engine.md §8: native는 조립 폴더(기준 메시) 필수 */
export const NATIVE_ASSEM_TEXT = "기준 메시 104_replace_node_elem.inc 필요";

/** phase3 §13 S8: 프로젝트 폴더 1개 → 플랫폼이 tpl·CAD·조립 폴더·파라미터를 찾아 구성(읽기만). 후보가 여러 개면 드롭다운.
 *  S9 §14.4: 조립 폴더는 선택 항목 — 드롭다운 끝 "없음" 또는 후보 0개면 메시 단독(mesh_only) 템플릿 */
export function ParamSetDiscoverForm({ studyId, label, onDone }: { studyId: string; label: string; onDone: () => Promise<void> }) {
  const [path, setPath] = useState("");
  const [found, setFound] = useState<ParamSetDiscover | null>(null);
  const [choice, setChoice] = useState<Choice>({ cad: "", radioss_assem: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { engineDefault } = useGeometryStatus();
  const [engine, setEngine] = useState<Engine>(engineDefault);
  const native = engine === "native";
  // native 등록 = 202 작업(PARAM_SET_NATIVE) — 기존 작업 진행 표시(JobInline)로 보이고 성공하면 목록을 다시 읽는다
  const nativeJob = useLatestJob(studyId, "PARAM_SET_NATIVE", (j) => j.state === "SUCCEEDED" && void onDone());
  const changePath = (v: string) => {
    setPath(v);
    setFound(null);
  };
  const changeEngine = (e: Engine) => {
    setEngine(e);
    setFound(null);
  };

  const find = async (tpl?: string | null) => {
    setBusy(true);
    setError(null);
    try {
      const d = await api.discoverParamSet(studyId, path.trim(), tpl, engine);
      setFound(d);
      // 후보가 1개면 그것, 여러 개면 사용자가 고른다(자동 선택 없음)
      setChoice({ cad: d.cad.length === 1 ? d.cad[0].rel : "", radioss_assem: d.radioss_assem.length === 1 ? d.radioss_assem[0].rel : "" });
    } catch (e) {
      setFound(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const register = async () => {
    if (native) return registerNative();
    if (!found?.selected_tpl) return;
    setBusy(true);
    setError(null);
    try {
      await api.registerParamSet(studyId, found.path, {
        mode: "discover",
        choice: { tpl: found.selected_tpl, cad: choice.cad, radioss_assem: meshOnly ? null : choice.radioss_assem },
        label: label.trim() || null,
      });
      await onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const registerNative = async () => {
    if (!found) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.registerParamSet(studyId, found.path, {
        mode: "discover",
        engine: "native",
        choice: { cad: choice.cad, radioss_assem: choice.radioss_assem },
        label: label.trim() || null,
      });
      if ("job_id" in r) nativeJob.track(await api.job(r.job_id));
      else await onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const meshOnly = !native && !!found && (found.radioss_assem.length === 0 || choice.radioss_assem === ASSEM_NONE);
  const nativeBusy = !!nativeJob.job && !isTerminal(nativeJob.job.state);
  const ready = native
    ? !!found && !!choice.cad && !!choice.radioss_assem && found.problems.length === 0 && !nativeBusy
    : !!found && !!found.selected_tpl && !!choice.cad && (meshOnly || !!choice.radioss_assem) && found.problems.length === 0;
  const pick = (key: keyof Choice) => (e: ChangeEvent<HTMLSelectElement>) => setChoice((c) => ({ ...c, [key]: e.target.value }));

  return (
    <div className="ps-register" data-testid="ps-discover">
      <EngineSelect value={engine} onChange={changeEngine} disabled={busy} />
      <div className="pathinput">
        <span className="field-label">프로젝트 폴더</span>
        <div className="pathinput-row">
          <input
            type="text"
            className="mono"
            value={path}
            placeholder="E:/shared/AI_WORK/cushion/00_inbox/project"
            aria-label="프로젝트 폴더 경로"
            spellCheck={false}
            onChange={(e) => changePath(e.target.value)}
          />
          {/* 찾아보기(phase3 §12 S7): discover는 allowed_roots(imports=True)라 추가 허용 폴더도 보인다(aiOnly 아님) */}
          <BrowseButton mode="dir" value={path} onPick={changePath} disabled={busy} title="프로젝트 폴더 선택" />
          <button type="button" className="btn" onClick={() => find()} disabled={busy || !path.trim()}>
            {busy && !found ? "찾는 중…" : "찾기"}
          </button>
        </div>
        <span className="small muted">
          {native
            ? `하위 폴더에서 STEP·Radioss 조립 폴더(${NATIVE_ASSEM_TEXT})를 찾습니다. 원본은 읽기만 합니다.`
            : "하위 폴더에서 tpl·CAD·Radioss 조립 폴더·파라미터를 찾습니다. 원본은 읽기만 합니다."}
        </span>
      </div>
      {found && (
        <div className={found.problems.length ? "inspect bad" : "inspect ok"} data-testid="ps-discover-result">
          <dl className="kv small">
            {!native && <dt>tpl</dt>}
            {!native && <dd>
              {found.tpl.length > 1 ? (
                <select aria-label="tpl 선택" value={found.selected_tpl ?? ""} onChange={(e) => e.target.value && find(e.target.value)}>
                  <option value="">선택하세요 ({found.tpl.length}개)</option>
                  {found.tpl.map((t) => (
                    <option key={t.rel} value={t.rel}>
                      {t.rel} · 파라미터 {t.parameter_count}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="mono">{found.tpl[0]?.rel ?? "없음"}</span>
              )}
            </dd>}
            <dt>{native ? "CAD(STEP)" : "CAD"}</dt>
            <dd>
              {found.cad.length > 1 ? (
                <select aria-label="CAD 선택" value={choice.cad} onChange={pick("cad")}>
                  <option value="">선택하세요 ({found.cad.length}개)</option>
                  {found.cad.map((c) => (
                    <option key={c.rel} value={c.rel}>
                      {c.rel}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="mono">{found.cad[0]?.rel ?? (native || found.selected_tpl ? "없음" : "tpl을 고르면 찾습니다")}</span>
              )}
            </dd>
            <dt>조립 폴더</dt>
            <dd>
              {found.radioss_assem.length ? (
                <select aria-label="조립 폴더 선택" value={choice.radioss_assem} onChange={pick("radioss_assem")}>
                  {found.radioss_assem.length > 1 && <option value="">선택하세요 ({found.radioss_assem.length}개)</option>}
                  {found.radioss_assem.map((a) => (
                    <option key={a.rel} value={a.rel}>
                      {a.rel} · {a.starter}
                    </option>
                  ))}
                  {!native && <option value={ASSEM_NONE}>{ASSEM_NONE_LABEL}</option>}
                </select>
              ) : (
                <span className="muted" data-testid="assem-zero">
                  {native ? `조립 폴더 없음 — ${NATIVE_ASSEM_TEXT}` : ASSEM_ZERO_TEXT}
                </span>
              )}
            </dd>
            <dt>입력 종류</dt>
            <dd data-testid="ps-discover-kind">{native ? "조립 포함(assembly) — Native 형상 준비(피처 추출·경계 노드 분류) 후 등록" : found.selected_tpl ? (meshOnly ? "메시 단독(mesh_only) — 형상 생성 → 예측" : "조립 포함(assembly) — 형상 생성 → 메시 연결 → 조립 → 예측") : "—"}</dd>
            <dt>파라미터</dt>
            <dd data-testid="ps-discover-params">
              {native
                ? found.parameters.length
                  ? `${found.parameters.length}개 · 파일(${found.parameters_file ?? "parameters.json"})`
                  : "형상 준비에서 피처로 만듭니다"
                : found.selected_tpl
                ? `${found.parameters.length}개 · ${found.parameters_source === "file" ? `파일(${found.parameters_file})` : "tpl에서 생성 — 단위 없음"}`
                : "—"}
            </dd>
            {(found.samples || found.responses) && (
              <>
                <dt>선택 파일</dt>
                <dd className="mono">{[found.samples, found.responses].filter(Boolean).join(" · ")}</dd>
              </>
            )}
          </dl>
          {found.problems.length > 0 && (
            <ul className="problems small">
              {found.problems.map((p, i) => (
                <li key={i}>{p.message}</li>
              ))}
            </ul>
          )}
          {found.notes.length > 0 && (
            <ul className="problems small muted">
              {found.notes.map((p, i) => (
                <li key={i}>{p.message}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="run-action-row">
        <button type="button" className="btn primary" disabled={!ready || busy} onClick={register}>
          {busy && found ? "등록 중…" : "등록"}
        </button>
        {native && nativeJob.job && <JobInline job={nativeJob.job} />}
        {error && (
          <span className="error-text small" role="alert">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
