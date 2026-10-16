// ④ B "일괄 예측(DOE)" 설정(phase3.md §14.5·§14.8, 시안 03):
// 1 템플릿·조합(LHS 범위·개수·시드 / 표 붙여넣기·CSV / ① 학습 DOE 재사용 → preview) · 2 조합 미리보기 · 3 실행 방식(동시 실행 수·모델·실행 1개).
import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api, errorMessage, type BatchPreview as BP, type BatchProblem, type BatchSource, type BatchSourceKind, type ParamSet, type PredictBatchParams, type PredictBatchSummary, type TrainDoe } from "../../../api";
import { useApp } from "../../../app/AppContext";
import { useStudy } from "../../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../../hooks/useJobRunner";
import { FeatureGate, FeatureOffNote, useFeature } from "../../../components/FeatureGate";
import { Card, RunAction } from "../../../components/ui";
import { fmtNum, fmtTime } from "../../../lib/format";
import { TemplatePicker, inputKindOf, templateName, useTemplateChoice } from "../TemplatePicker";
import { ModelLine, useModelChoice } from "../predictRun";
import { BatchPreview } from "./BatchPreview";
import { BATCH_STATUS_LABEL } from "./batchTable";
import { BatchCaptureOptions, captureParam, type CaptureChoice } from "./BatchCaptureOptions";
import { DEFAULT_VIEWS } from "../../../lib/views";

const METHODS: { key: BatchSourceKind; label: string }[] = [
  { key: "lhs", label: "범위·개수로 자동(LHS)" },
  { key: "table", label: "표 붙여넣기 / CSV" },
  { key: "train_doe", label: "① 학습 DOE 그대로 재사용" },
];
export const RUN_LABEL = "입력 생성 + 일괄 예측 실행";

/** /status.limits.configured.max_multi_execution(설정 train_data.max_multi_execution) — 없으면 8(기본값) */
export function maxMultiExecution(status: { limits?: { configured?: Record<string, unknown> } } | null | undefined): number {
  const v = Number(status?.limits?.configured?.max_multi_execution);
  return Number.isInteger(v) && v >= 1 ? v : 8;
}

type Ranges = Record<string, [string, string]>;
/** 선택 숫자: 빈 값 null, 잘못된 값 undefined */
const optNum = (s: string): number | null | undefined => (s.trim() === "" ? null : Number.isFinite(Number(s)) ? Number(s) : undefined);
const defaultRanges = (ps: ParamSet | null): Ranges => Object.fromEntries((ps?.parameters ?? []).map((p) => [p.name, [String(p.min), String(p.max)]]));

export function BatchSetup() {
  const { status } = useApp();
  const { study } = useStudy();
  const navigate = useNavigate();
  const canExec = useCanExecute();
  const { list, ps, setPicked } = useTemplateChoice();
  const kind = ps ? inputKindOf(ps) : "assembly";
  const tplFeature = kind === "mesh_only" ? "predict_mesh_only" : "predict_parametric";
  const tplF = useFeature(tplFeature);
  const maxMulti = maxMultiExecution(status);

  const [method, setMethod] = useState<BatchSourceKind>("lhs");
  const [ranges, setRanges] = useState<Ranges>(() => defaultRanges(ps));
  const [count, setCount] = useState("20");
  const [seed, setSeed] = useState("1");
  const [text, setText] = useState("");
  const [does, setDoes] = useState<TrainDoe[]>([]);
  const [doeId, setDoeId] = useState("");
  const [preview, setPreview] = useState<BP | null>(null);
  const [previewSource, setPreviewSource] = useState<BatchSource | null>(null);
  const [problems, setProblems] = useState<BatchProblem[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [multi, setMulti] = useState(String(Math.min(4, maxMulti)));
  const [recent, setRecent] = useState<PredictBatchSummary[]>([]);
  // S10: 범례 범위 고정(run 비교용) — min·max는 선택
  const [legendFixed, setLegendFixed] = useState(false);
  const [legendLo, setLegendLo] = useState("");
  const [legendHi, setLegendHi] = useState("");
  // D3-53: 컨투어 캡처 옵션(기본 = 템플릿 display.views → config capture.views, 영상 = config capture.video)
  const defViews = ps?.display?.views?.length ? ps.display.views : status?.capture?.views?.length ? status.capture.views : DEFAULT_VIEWS;
  const defVideo = status?.capture?.video ?? true;
  const [cap, setCap] = useState<CaptureChoice>({ enabled: true, views: defViews, video: defVideo });
  useEffect(() => setCap((c) => ({ ...c, views: defViews })), [defViews.join(",")]);
  useEffect(() => setCap((c) => ({ ...c, video: defVideo })), [defVideo]);
  const choice = useModelChoice();
  const runner = useJobRunner("PREDICT_BATCH");

  useEffect(() => {
    api.trainDoes(study.id).then((l) => {
      const ready = l.filter((d) => d.status === "READY" && (d.sample_status === "PARSED" || d.sample_status === "PARTIAL"));
      setDoes(ready);
      setDoeId((v) => v || ready[0]?.id || "");
    }).catch(() => setDoes([]));
    api.batches(study.id).then(setRecent).catch(() => setRecent([]));
  }, [study.id]);

  // 템플릿·조합 입력이 바뀌면 미리보기는 무효(실행 body = 미리본 조합)
  const clear = () => {
    setPreview(null);
    setPreviewSource(null);
    setProblems([]);
    setPreviewError(null);
  };
  useEffect(() => {
    setRanges(defaultRanges(ps));
    clear();
  }, [ps?.id]);

  const source = useMemo((): BatchSource | null => {
    if (method === "lhs") {
      const r: Record<string, [number, number]> = {};
      for (const [n, [lo, hi]] of Object.entries(ranges)) r[n] = [Number(lo), Number(hi)];
      return { kind: "lhs", count: Number(count), seed: Number(seed), ranges: r };
    }
    if (method === "table") return text.trim() ? { kind: "table", text } : null;
    return doeId ? { kind: "train_doe", doe_id: doeId } : null;
  }, [method, ranges, count, seed, text, doeId]);

  const make = async () => {
    if (!ps || !source) return;
    setBusy(true);
    clear();
    try {
      const p = await api.batchPreview(study.id, { param_set_id: ps.id, source });
      setPreview(p);
      setProblems(p.problems);
      if (!p.problems.length && p.count > 0) setPreviewSource(source);
    } catch (e) {
      const det = e instanceof ApiError ? (e.detail.problems as BatchProblem[] | undefined) : undefined;
      if (det?.length) setProblems(det);
      else setPreviewError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const multiN = Number(multi);
  const multiOk = Number.isInteger(multiN) && multiN >= 1 && multiN <= maxMulti;
  const lgLo = optNum(legendLo);
  const lgHi = optNum(legendHi);
  const legendOk = !legendFixed || (lgLo !== undefined && lgHi !== undefined && (lgLo === null || lgHi === null || lgLo < lgHi));
  const capOk = !cap.enabled || cap.views.length > 0;
  const ready = !!ps && !!previewSource && !!preview && preview.count > 0 && multiOk && legendOk && capOk && !!choice.chosenModel && tplF.enabled;
  const run = async () => {
    if (!ps || !previewSource) return;
    const params: PredictBatchParams = { param_set_id: ps.id, model_id: choice.modelId || null, multi_execution: multiN, source: previewSource };
    if (legendFixed) params.display = { legend: { mode: "fixed", min: lgLo ?? null, max: lgHi ?? null } };
    const capture = captureParam(cap, defViews, defVideo);
    if (capture) params.capture = capture;
    const j = await runner.run({ ...params });
    const bid = (j?.params as { batch_id?: string } | undefined)?.batch_id;
    if (bid) navigate(`/p/${study.project_id}/s/${study.id}/stage/4/batch/${bid}`);
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setText(await f.text()); // 브라우저 안에서 읽기만(업로드 없음)
    clear();
  };
  const setRange = (n: string, i: 0 | 1, v: string) => {
    setRanges((r) => ({ ...r, [n]: (i === 0 ? [v, r[n][1]] : [r[n][0], v]) as [string, string] }));
    clear();
  };
  const names = ps?.parameters.map((p) => p.name) ?? [];
  const base = `/p/${study.project_id}/s/${study.id}/stage/4`;

  return (
    <>
      <Card span={3} title="1 템플릿·조합" className="batch-setup" aside={ps ? <span className="muted small">{templateName(ps)}</span> : undefined}>
        <TemplatePicker list={list} value={ps?.id ?? ""} onChange={setPicked} compact />
        {!ps && <p className="muted small">등록된 템플릿이 없습니다 — "템플릿 값 입력"의 템플릿 관리에서 등록하세요.</p>}
        <fieldset className="radio-list">
          <legend className="field-label">조합 만들기</legend>
          {METHODS.map((m) => (
            <label key={m.key} className="radio-line">
              <input
                type="radio"
                name="batch-method"
                value={m.key}
                checked={method === m.key}
                onChange={() => {
                  setMethod(m.key);
                  clear();
                }}
              />
              {m.label}
            </label>
          ))}
        </fieldset>
        {method === "lhs" && ps && (
          <>
            <table className="table compact" aria-label="파라미터 범위">
              <thead>
                <tr>
                  <th>파라미터</th>
                  <th className="num">최소</th>
                  <th className="num">최대</th>
                </tr>
              </thead>
              <tbody>
                {ps.parameters.map((p) => (
                  <tr key={p.name}>
                    <td>
                      {p.name} <span className="muted small">{p.unit}</span>
                    </td>
                    <td className="num">
                      <input className="num-input" inputMode="decimal" aria-label={`${p.name} 최소`} value={ranges[p.name]?.[0] ?? ""} onChange={(e) => setRange(p.name, 0, e.target.value)} />
                    </td>
                    <td className="num">
                      <input className="num-input" inputMode="decimal" aria-label={`${p.name} 최대`} value={ranges[p.name]?.[1] ?? ""} onChange={(e) => setRange(p.name, 1, e.target.value)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="fill-row">
              <label className="inline-field">
                조합 수
                <input className="num-input" inputMode="numeric" value={count} onChange={(e) => (setCount(e.target.value), clear())} />
              </label>
              <label className="inline-field">
                시드
                <input className="num-input" inputMode="numeric" value={seed} onChange={(e) => (setSeed(e.target.value), clear())} />
              </label>
            </div>
          </>
        )}
        {method === "table" && (
          <>
            <label className="field">
              <span className="field-label">조합 표(첫 줄 = 파라미터 이름, 탭·쉼표 구분)</span>
              <textarea
                className="mono batch-text"
                rows={6}
                value={text}
                placeholder={names.length ? `${names.join("\t")}\n${(ps?.parameters ?? []).map((p) => p.nominal).join("\t")}` : ""}
                onChange={(e) => (setText(e.target.value), clear())}
              />
            </label>
            <label className="field">
              <span className="field-label">CSV 파일 열기</span>
              <input type="file" accept=".csv,.tsv,.txt" onChange={onFile} />
            </label>
          </>
        )}
        {method === "train_doe" && (
          <label className="field">
            <span className="field-label">① 학습 DOE</span>
            <select value={doeId} onChange={(e) => (setDoeId(e.target.value), clear())} disabled={!does.length}>
              {!does.length && <option value="">준비된 DOE 없음</option>}
              {does.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.doe_label} · run {d.run_count} · {fmtTime(d.created_at)}
                </option>
              ))}
            </select>
          </label>
        )}
        <button type="button" className="btn" onClick={make} disabled={!ps || !source || busy}>
          {busy ? "만드는 중…" : "조합 만들기"}
        </button>
      </Card>

      <BatchPreview preview={preview} names={names} problems={problems} error={previewError} />

      <Card span={9} title="3 실행 방식" className="batch-run">
        <div className="batch-run-grid">
          <ol className="batch-flow" aria-label="실행 방식">
            <li>
              <span className="R">단계 1 · ① 방식</span>
              <span>입력 생성(run 폴더마다 동시 실행)</span>
              <span className="muted small">{kind === "mesh_only" ? "SimLab m_1 → EPS_mesh (메시 단독 — m_2·m_3 없음)" : "SimLab m_1 → EPS_mesh · HyperMesh m_2 → include · m_3 조립"}</span>
            </li>
            <li>
              <span className="R">단계 2 · 준비된 입력 방식</span>
              <span>run 폴더마다 예측(PhysicsAI edspy)</span>
              <span className="muted small">대기열 1슬롯으로 순서대로</span>
            </li>
            <li>
              <span className="R">단계 3</span>
              <span>응답 추출 → 비교 표</span>
              <span className="muted small">응답 그래프·커브 겹쳐보기</span>
            </li>
          </ol>
          <div className="batch-run-side">
            <label className="inline-field">
              입력 생성 동시 실행 수
              <input className="num-input" type="number" min={1} max={maxMulti} value={multi} onChange={(e) => setMulti(e.target.value)} aria-invalid={!multiOk} />
              <span className="muted small">1–{maxMulti}</span>
            </label>
            <div className="legend-fix">
              <label className="check">
                <input type="checkbox" checked={legendFixed} onChange={(e) => setLegendFixed(e.target.checked)} />
                범례 범위 고정(run 비교용)
              </label>
              {legendFixed && (
                <span className="fill-row">
                  <label className="inline-field">
                    최소
                    <input className="num-input" inputMode="decimal" aria-label="범례 최소" value={legendLo} placeholder="선택" onChange={(e) => setLegendLo(e.target.value)} aria-invalid={lgLo === undefined} />
                  </label>
                  <label className="inline-field">
                    최대
                    <input className="num-input" inputMode="decimal" aria-label="범례 최대" value={legendHi} placeholder="선택" onChange={(e) => setLegendHi(e.target.value)} aria-invalid={lgHi === undefined} />
                  </label>
                </span>
              )}
            </div>
            <BatchCaptureOptions value={cap} onChange={setCap} runs={preview && previewSource ? preview.count : null} />
            <ModelLine choice={choice} />
            {preview?.estimate_min != null && previewSource && <p className="muted small">예상 소요 약 {fmtNum(preview.estimate_min, 3)}분</p>}
            <FeatureGate feature="predict">
              {(enabled) => (
                <RunAction
                  canExecute={canExec}
                  label={RUN_LABEL}
                  onRun={() => void run()}
                  job={runner.job && runner.job.state !== "SUCCEEDED" ? runner.job : null}
                  disabled={!enabled || !ready || runner.submitting}
                  disabledReason={!enabled || !tplF.enabled ? undefined : !previewSource ? "먼저 조합을 만드세요" : !multiOk ? `동시 실행 수는 1~${maxMulti}` : !legendOk ? "범례 최소 < 최대인 숫자(비우면 미지정)" : !capOk ? "캡처 방향을 1개 이상 고르세요" : !choice.chosenModel ? "Final 모델이 필요합니다" : undefined}
                  error={runner.error}
                />
              )}
            </FeatureGate>
            {!tplF.enabled && <FeatureOffNote feature={tplFeature} f={tplF} />}
          </div>
        </div>
        <p className="muted small">입력 생성은 동시 실행으로 빠르게, 예측은 대기열 1슬롯으로 순서대로. 실행 중에도 다른 사용자 작업은 대기열 뒤에 섭니다.</p>
        {recent.length > 0 && (
          <p className="small recent-batches">
            이전 일괄 예측:{" "}
            {recent.slice(0, 6).map((b, i) => (
              <span key={b.id}>
                {i > 0 && " · "}
                <Link to={`${base}/batch/${b.id}`}>{b.label}</Link> <span className="muted">{BATCH_STATUS_LABEL[b.status]} · {b.run_count} run</span>
              </span>
            ))}
          </p>
        )}
      </Card>
    </>
  );
}
