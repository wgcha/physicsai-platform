// ④ 새 FEM 검증 카드(phase3 §21.3.11): ① 검증 대상 → ② 조립 원본 → ③ 고급(접힘) → ④ preview problems·warnings + "FEM 검증 실행".
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, errorMessage, type ViewKey } from "../../../api";
import { femVerifyApi, type FemAssemblyReq, type FemPreview, type FemSourceReq, type FemVerifyCreate } from "../../../api/femVerify";
import { useStudy } from "../../../app/StudyContext";
import { Advanced, Card } from "../../../components/ui";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { fmtNum } from "../../../lib/format";
import { DEFAULT_VIEWS, VIEW_KEYS, viewLabel } from "../../../lib/views";
import { mdHm } from "../history/runListText";
import { AssemblySourcePicker, type AssemblyChoice } from "./AssemblySourcePicker";
import { checkFemField, parseComps } from "./verifyRules";

const bodyOf = (c: AssemblyChoice): FemAssemblyReq | null =>
  c.kind === "predict_input" ? { kind: "predict_input" } : c.kind === "train_doe" ? (c.doeId ? { kind: "train_doe", doe_id: c.doeId } : null) : c.confirmedPath ? { kind: "custom", path: c.confirmedPath } : null;

export function VerifyNew({ source, base }: { source: FemSourceReq; base: string }) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const navigate = useNavigate();
  const [choice, setChoice] = useState<AssemblyChoice>({ kind: "predict_input", doeId: null, path: "", confirmedPath: null });
  const [touched, setTouched] = useState(false);
  const [baseP, setBaseP] = useState<FemPreview | null>(null);
  const [prev, setPrev] = useState<FemPreview | null>(null);
  const [error, setError] = useState<{ message: string; problems: { code: string; message: string }[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<{ message: string; problems: { code: string; message: string }[] } | null>(null);
  // 고급
  const [field, setField] = useState("");
  const [comps, setComps] = useState("");
  const [views, setViews] = useState<ViewKey[]>(DEFAULT_VIEWS);
  const [viewsTouched, setViewsTouched] = useState(false);
  const [legend, setLegend] = useState<{ mode: "auto" | "fixed"; min: string; max: string }>({ mode: "auto", min: "", max: "" });
  const [ncpus, setNcpus] = useState("");

  const sourceKey = JSON.stringify(source);
  const assembly = touched ? bodyOf(choice) : null;
  const assemblyKey = JSON.stringify(assembly);
  const waitingPath = touched && choice.kind === "custom" && !choice.confirmedPath;
  const compsP = parseComps(comps);
  const fieldErr = checkFemField(field);
  const legendErr = legend.mode === "fixed" && !(Number.isFinite(Number(legend.min)) && Number.isFinite(Number(legend.max)) && legend.min !== "" && legend.max !== "" && Number(legend.min) < Number(legend.max)) ? "고정 범례는 최소 < 최대" : null;
  const cpuErr = ncpus.trim() && !(Number.isInteger(Number(ncpus)) && Number(ncpus) >= 1) ? "CPU 수는 1 이상의 정수" : null;

  const makeBody = (asm: FemAssemblyReq | null): FemVerifyCreate => ({
    source,
    assembly: asm,
    fem: { field: field.trim() || null, component: null, comps: compsP.list },
    display: viewsTouched || legend.mode === "fixed" ? { views, legend: legend.mode === "fixed" ? { mode: "fixed", min: Number(legend.min), max: Number(legend.max) } : { mode: "auto", min: null, max: null } } : null,
    hpc: ncpus.trim() ? { queue: null, ncpus: Number(ncpus), walltime: null } : null,
  });
  const optsRef = useRef(makeBody);
  optsRef.current = makeBody;

  useEffect(() => {
    setTouched(false);
    setBaseP(null);
    setChoice({ kind: "predict_input", doeId: null, path: "", confirmedPath: null });
  }, [sourceKey]);

  useEffect(() => {
    if (waitingPath) {
      setPrev(null);
      return;
    }
    let alive = true;
    setError(null);
    femVerifyApi
      .preview(study.id, optsRef.current(assembly))
      .then((r) => {
        if (!alive) return;
        setPrev(r);
        if (assembly === null) setBaseP(r);
      })
      .catch((e) => {
        if (!alive) return;
        setPrev(null);
        setError({ message: errorMessage(e), problems: e instanceof ApiError ? ((e.detail.problems as { code: string; message: string }[] | undefined) ?? []) : [] });
      });
    return () => {
      alive = false;
    };
    // 출처·조립 원본이 바뀔 때만 다시 미리보기(고급 값은 요청 때 반영)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [study.id, sourceKey, assemblyKey, waitingPath]);

  const predictInputOk = baseP?.assembly?.kind === "predict_input" && !baseP.problems.some((p) => p.code === "INPUT_MESH_ONLY");
  const effective: AssemblyChoice = touched ? choice : { ...choice, kind: baseP?.assembly?.kind === "train_doe" ? "train_doe" : "predict_input" };
  const problems = prev?.problems ?? [];
  const localErr = compsP.error ?? fieldErr ?? legendErr ?? cpuErr;
  const ok = !!prev && !problems.length && !waitingPath && !localErr && canExec;
  const mode = prev?.hpc_mode === "scx" ? "SCX" : prev?.hpc_mode === "command" ? "PBS" : "";

  const run = async () => {
    setBusy(true);
    setCreateError(null);
    try {
      const r = await femVerifyApi.create(study.id, makeBody(assembly));
      navigate(`${base}/verify/${r.id}`);
    } catch (e) {
      setCreateError({ message: errorMessage(e), problems: e instanceof ApiError ? ((e.detail.problems as { code: string; message: string }[] | undefined) ?? []) : [] });
    } finally {
      setBusy(false);
    }
  };

  const design = prev?.design;
  const names = useMemo(() => Object.keys(design?.values ?? {}), [design]);
  const viewKeys = [...VIEW_KEYS, ...views.filter((v) => !VIEW_KEYS.includes(v))];

  return (
    <Card span={9} title="새 FEM 검증" className="fv-new" aside={<Link className="small" to={`${base}/verify`}>← FEM 검증 목록</Link>}>
      <div className="fv-new-grid">
        <section className="fv-section" aria-label="검증 대상">
          <span className="field-label">검증 대상</span>
          {error && (
            <div role="alert">
              <p className="error-text small">{error.message}</p>
              {error.problems.map((p, i) => (
                <p key={i} className="muted small" data-code={p.code}>
                  {p.message}
                </p>
              ))}
            </div>
          )}
          {!prev && !error && <p className="muted small">불러오는 중…</p>}
          {prev && (
            <>
              <p className="small" data-testid="fv-source">
                <b>{prev.source_label}</b>
                {design?.param_set && <span className="muted"> · 템플릿 {design.param_set.label ?? design.param_set.id}</span>}
                {design?.model && <span className="muted"> · 모델 {design.model.name} v{design.model.version}</span>}
              </p>
              {names.length > 0 && (
                <div className="table-wrap">
                  <table className="table compact" aria-label="설계점">
                    <thead>
                      <tr>
                        <th>파라미터</th>
                        <th className="num">입력값</th>
                        <th className="num">반영값</th>
                        <th>범위 밖</th>
                      </tr>
                    </thead>
                    <tbody>
                      {names.map((n) => (
                        <tr key={n}>
                          <td className="mono">{n}</td>
                          <td className="num">{fmtNum(design!.values[n])}</td>
                          <td className="num">{fmtNum(design!.applied_values?.[n] ?? design!.values[n])}</td>
                          <td className="small">{design!.out_of_range.includes(n) ? <span className="warn-text">범위 밖</span> : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="muted small" data-testid="fv-predict-note">
                {prev.predict.reuse ? `기존 예측 사용 — ${mdHm(prev.predict.created_at)}` : "같은 값의 예측이 없어 예측을 먼저 실행합니다"}
              </p>
            </>
          )}
        </section>

        <AssemblySourcePicker value={effective} onChange={(v) => (setTouched(true), setChoice(v))} predictInputOk={predictInputOk} canEdit={canExec} />

        <Advanced label="고급">
          <div className="fv-adv">
            <label className="field">
              <span className="field-label">FEM 결과 이름</span>
              <input type="text" className="mono" aria-label="FEM 결과 이름" value={field} placeholder={prev?.fem_field ?? ""} spellCheck={false} onChange={(e) => setField(e.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">격리 부품</span>
              <input type="text" className="mono" aria-label="격리 부품" value={comps} placeholder={prev?.comps_auto.length ? `자동: ${prev.comps_auto.join(", ")}` : "없음"} spellCheck={false} onChange={(e) => setComps(e.target.value)} />
            </label>
            <fieldset className="field">
              <legend className="field-label">방향</legend>
              <div className="checks">
                {viewKeys.map((k) => (
                  <label key={k} className="check small">
                    <input
                      type="checkbox"
                      checked={views.includes(k)}
                      onChange={(e) => {
                        setViewsTouched(true);
                        setViews(e.target.checked ? [...views, k] : views.filter((x) => x !== k));
                      }}
                    />
                    {viewLabel(k)}
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="field">
              <legend className="field-label">범례</legend>
              <div className="seg" role="group" aria-label="범례">
                <button type="button" className={legend.mode === "auto" ? "on" : ""} aria-pressed={legend.mode === "auto"} onClick={() => setLegend({ ...legend, mode: "auto" })}>
                  자동 맞춤
                </button>
                <button type="button" className={legend.mode === "fixed" ? "on" : ""} aria-pressed={legend.mode === "fixed"} onClick={() => setLegend({ ...legend, mode: "fixed" })}>
                  고정
                </button>
              </div>
              {legend.mode === "fixed" && (
                <span className="run-action-row">
                  <input type="text" inputMode="decimal" aria-label="범례 최소" value={legend.min} onChange={(e) => setLegend({ ...legend, min: e.target.value })} />
                  <span className="muted">~</span>
                  <input type="text" inputMode="decimal" aria-label="범례 최대" value={legend.max} onChange={(e) => setLegend({ ...legend, max: e.target.value })} />
                </span>
              )}
            </fieldset>
            <label className="field">
              <span className="field-label">CPU 수</span>
              <input type="text" inputMode="numeric" aria-label="CPU 수" value={ncpus} placeholder="기본" onChange={(e) => setNcpus(e.target.value)} />
            </label>
          </div>
          {localErr && <p className="error-text small" role="alert">{localErr}</p>}
        </Advanced>

        <section className="fv-section" aria-label="실행">
          {(problems.length > 0 || (prev?.warnings.length ?? 0) > 0) && (
            <ul className="fv-notes" data-testid="fv-preview-notes">
              {[...problems, ...(prev?.warnings ?? [])].map((p, i) => (
                <li key={i} className="muted small" data-code={p.code}>
                  {p.message}
                </li>
              ))}
            </ul>
          )}
          {createError && (
            <div role="alert">
              <p className="error-text small">{createError.message}</p>
              {createError.problems.map((p, i) => (
                <p key={i} className="muted small" data-code={p.code}>
                  {p.message}
                </p>
              ))}
            </div>
          )}
          <div className="run-action-row">
            {canExec ? (
              <button type="button" className="btn primary" disabled={!ok || busy} onClick={() => void run()} title={!prev ? "검증 대상을 불러오는 중입니다" : problems.length ? "아래 문제를 먼저 해결하세요" : waitingPath ? "조립 원본 경로를 확인하세요" : undefined}>
                {busy ? "요청 중…" : `FEM 검증 실행${mode ? `(${mode})` : ""}`}
              </button>
            ) : (
              <span className="muted small">조회 전용 — 실행 권한(power 이상)이 필요합니다</span>
            )}
          </div>
        </section>
      </div>
    </Card>
  );
}
