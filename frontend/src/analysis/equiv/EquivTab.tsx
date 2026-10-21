// ⑤ 결과분석 탭 "등가성 판정"(equiv-check.md §7, 라우트 ?tab=equiv[&eq=<id>]):
// 비교 대상 A(기준)·B(비교) → 레시피(시스템 기본·이 Study·전역, 편집 접힘, 저장·불러오기) → 판정 실행(EQ_CHECK 작업) → 결과 → 이력.
// 응답 연결은 사용자가 고른다 — 사용 중인 지표가 미연결이면 실행 비활성(서버도 422 METRIC_UNBOUND).
// 시스템 기본은 제안값(읽기 전용) — 복제·확인한 사용자 레시피만 실행(서버도 422 RECIPE_NOT_CONFIRMED).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, errorMessage, type Job, type PredictBatchSummary, type TrainDoe } from "../../api";
import { equivApi, SYSTEM_RECIPE_KEY, type EqCheck, type EqCheckCreate, type EqCheckListItem, type EqDefinition, type EqPairingMode, type EqPreview, type EqRecipeListItem } from "../../api/equivCheck";
import { femVerifyApi, type FemVerifySummary } from "../../api/femVerify";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute } from "../../hooks/useJobRunner";
import { usePolling } from "../../hooks/usePolling";
import { JobInline } from "../../components/ui";
import { NOT_READY_TEXT, ReportButton } from "../../components/ReportButton";
import { reportApi } from "../../api/reports";
import { isTerminal } from "../../lib/format";
import { POLL } from "../../lib/poll";
import { HistoryList } from "./HistoryList";
import { RecipeEditor } from "./RecipeEditor";
import { ResultView } from "./ResultView";
import { emptySide, SidePicker, toSideReq, type SideSel } from "./SidePicker";
import { isSystemRef, readRecipeKey, recipeBody, toRows, unboundMetrics, versionNote, writeRecipeKey, type EditRow } from "./recipeState";

export const UNBOUND_TEXT = "응답이 연결되지 않은 지표가 있습니다 — 성능 정의(응답)를 선택하거나 사용 체크를 해제하세요";
export const SYSTEM_RUN_TEXT = "시스템 기본은 제안값이라 그대로 실행할 수 없습니다 — 편집 → 다른 이름으로 저장해 지표·허용오차·필수/참고를 확인한 레시피로 실행하세요.";
export const RECIPE_HINT = "시스템 기본은 제안값(읽기 전용)입니다. 복제(다른 이름으로 저장)해서 허용오차·필수 여부를 정하세요.";
const GROUPS: { scope: EqRecipeListItem["scope"]; label: string }[] = [
  { scope: "system", label: "시스템 기본" },
  { scope: "study", label: "이 Study" },
  { scope: "global", label: "전역" },
];

interface LoadedRecipe {
  /** null = 1회용(adhoc) 이력 스냅숏(원 레시피 없음) */
  ref: { key: string; version: number } | null;
  item: EqRecipeListItem | null;
  definition: EqDefinition;
  /** 이력에서 불러온 스냅숏이면 안내 문구 */
  note: string | null;
}

export function EquivTab({ initialA, initialB, initialEq }: { initialA: { kind: "batch" | "doe"; id: string } | null; initialB: { kind: "batch" | "doe"; id: string } | null; initialEq: string | null }) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const [batches, setBatches] = useState<PredictBatchSummary[]>([]);
  const [does, setDoes] = useState<TrainDoe[]>([]);
  const [fems, setFems] = useState<FemVerifySummary[]>([]);
  const [recipes, setRecipes] = useState<EqRecipeListItem[] | null>(null);
  const toSel = (s: { kind: "batch" | "doe"; id: string } | null, fallback: SideSel["kind"]): SideSel => (s ? { kind: s.kind === "batch" ? "predict_batch" : "train_doe", id: s.id, paths: "" } : emptySide(fallback));
  const [sideA, setSideA] = useState<SideSel>(() => toSel(initialA, "train_doe"));
  const [sideB, setSideB] = useState<SideSel>(() => toSel(initialB, "predict_batch"));
  const [mode, setMode] = useState<EqPairingMode>("by_name");
  const [manual, setManual] = useState("");
  const [loaded, setLoaded] = useState<LoadedRecipe | null>(null);
  const [rows, setRows] = useState<EditRow[]>([]);
  const [pairRule, setPairRule] = useState<EqDefinition["pair_rule"]>({ mode: "all" });
  const [adhoc, setAdhoc] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [saveAs, setSaveAs] = useState<{ name: string; scope: "study" | "global"; description: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [recipeError, setRecipeError] = useState<string | null>(null);
  const [preview, setPreview] = useState<EqPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [runningEq, setRunningEq] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [current, setCurrent] = useState<EqCheck | null>(null);
  const [history, setHistory] = useState<EqCheckListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [histLoading, setHistLoading] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- 목록 ----
  useEffect(() => {
    let alive = true;
    api.batches(study.id).then((x) => alive && setBatches(x)).catch(() => alive && setBatches([]));
    api.trainDoes(study.id).then((x) => alive && setDoes(x)).catch(() => alive && setDoes([]));
    femVerifyApi.list(study.id, { status: "DONE", limit: 200 }).then((r) => alive && setFems(r.items)).catch(() => alive && setFems([]));
    return () => {
      alive = false;
    };
  }, [study.id]);

  const loadHistory = useCallback(
    async (more = false) => {
      setHistLoading(true);
      try {
        const r = await equivApi.list(study.id, { limit: 20, cursor: more ? cursor : null });
        setHistory((h) => (more ? [...h, ...r.items] : r.items));
        setCursor(r.nextCursor);
      } finally {
        setHistLoading(false);
      }
    },
    [study.id, cursor],
  );
  useEffect(() => {
    void loadHistory(false);
  }, [study.id]);

  const applyDefinition = (ref: { key: string; version: number } | null, item: EqRecipeListItem | null, def: EqDefinition, noteText: string | null) => {
    setLoaded({ ref, item, definition: def, note: noteText });
    setRows(toRows(def));
    setPairRule(def.pair_rule);
    setAdhoc(false);
    setRecipeError(null);
  };
  const pickRecipe = useCallback(
    async (key: string, version?: number | null, list?: EqRecipeListItem[]) => {
      try {
        const r = await equivApi.recipe(key, version);
        const item = (list ?? recipes ?? []).find((x) => x.key === key) ?? { ...r };
        applyDefinition({ key: r.key, version: r.version }, item, r.definition, null);
        writeRecipeKey(key);
      } catch (e) {
        setRecipeError(errorMessage(e));
      }
    },
    [recipes],
  );
  useEffect(() => {
    let alive = true;
    equivApi
      .recipes(study.id)
      .then((list) => {
        if (!alive) return;
        setRecipes(list);
        const saved = readRecipeKey();
        const key = list.some((r) => r.key === saved) ? saved! : SYSTEM_RECIPE_KEY;
        void pickRecipe(key, null, list);
      })
      .catch((e) => alive && setRecipeError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [study.id]);

  // ---- 미리보기(디바운스) ----
  const reqA = toSideReq(sideA);
  const reqB = toSideReq(sideB);
  const bodyWithRule = useMemo((): EqCheckCreate | null => {
    if (!reqA || !reqB || !loaded) return null;
    const pairs = mode === "manual" ? manual.split(/\r?\n/).map((l) => l.split(/[,\t]/).map((x) => x.trim())).filter((p) => p.length >= 2 && p[0] && p[1]).map((p) => ({ a: p[0], b: p[1] })) : null;
    return { side_a: reqA, side_b: reqB, pairing: { mode, pairs }, ...recipeBody(loaded.definition, rows, loaded.ref, pairRule), note: note.trim() || null };
  }, [JSON.stringify(reqA), JSON.stringify(reqB), mode, manual, loaded, JSON.stringify(rows), JSON.stringify(pairRule), note]);
  useEffect(() => {
    if (!bodyWithRule) {
      setPreview(null);
      return;
    }
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      equivApi
        .preview(study.id, bodyWithRule)
        .then((p) => (setPreview(p), setPreviewError(null)))
        .catch((e) => (setPreview(null), setPreviewError(errorMessage(e))));
    }, POLL.checkDebounce);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [study.id, JSON.stringify(bodyWithRule)]);

  // ---- 실행·작업 추적 ----
  const unbound = unboundMetrics(rows);
  const isSystem = isSystemRef(loaded?.ref ?? null, SYSTEM_RECIPE_KEY);
  const modified = !!bodyWithRule?.recipe_inline && !!loaded?.ref;
  const canRun = canExec && !!bodyWithRule && !isSystem && !!preview?.can_run && unbound.length === 0 && !(job && !isTerminal(job.state));
  const run = async () => {
    if (!bodyWithRule) return;
    setRunError(null);
    try {
      const r = await equivApi.create(study.id, bodyWithRule);
      setRunningEq(r.eq_id);
      setCurrent(null);
      setJob(await api.job(r.job_id));
      void loadHistory(false);
    } catch (e) {
      setRunError(e instanceof ApiError && Array.isArray(e.detail.problems) ? `${e.message} — ${(e.detail.problems as { message: string }[]).map((p) => p.message).join("; ")}` : errorMessage(e));
    }
  };
  const openCheck = useCallback(async (id: string) => {
    try {
      setCurrent(await equivApi.get(id));
    } catch (e) {
      setRunError(errorMessage(e));
    }
  }, []);
  usePolling(
    async () => {
      if (!job || isTerminal(job.state)) return;
      const j = await api.job(job.id);
      setJob(j);
      if (isTerminal(j.state) && runningEq) {
        await openCheck(runningEq);
        void loadHistory(false);
      }
    },
    job && !isTerminal(job.state) ? POLL.jobActive : null,
    false,
    [job?.id, job?.state],
  );
  useEffect(() => {
    if (initialEq) void openCheck(initialEq);
  }, [initialEq, openCheck]);

  // ---- 레시피 저장·삭제·불러오기 ----
  const currentDef = (): EqDefinition => ({ ...(loaded?.definition ?? { schema_version: 1, verdict_rule: "required_all", pair_rule: { mode: "all" }, metrics: [] }), metrics: rows.filter((r) => r.use).map(({ use: _u, ...m }) => m), pair_rule: pairRule });
  const refreshRecipes = async (selectKey?: string) => {
    const list = await equivApi.recipes(study.id);
    setRecipes(list);
    if (selectKey) await pickRecipe(selectKey, null, list);
  };
  const saveVersion = async () => {
    if (!loaded?.item || loaded.item.readonly) return;
    setRecipeError(null);
    try {
      if (!loaded.ref) return;
      const r = await equivApi.updateRecipe(loaded.ref.key, { base_version: loaded.item.version, definition: currentDef() });
      await refreshRecipes(r.key);
    } catch (e) {
      setRecipeError(errorMessage(e));
    }
  };
  const doSaveAs = async () => {
    if (!saveAs || !saveAs.name.trim()) return;
    setRecipeError(null);
    try {
      const r = await equivApi.createRecipe({ name: saveAs.name.trim(), description: saveAs.description, scope: saveAs.scope, study_id: saveAs.scope === "study" ? study.id : null, definition: currentDef() });
      setSaveAs(null);
      await refreshRecipes(r.key);
    } catch (e) {
      setRecipeError(errorMessage(e));
    }
  };
  const doDelete = async () => {
    if (!loaded?.item || loaded.item.readonly || !loaded.ref) return;
    try {
      await equivApi.deleteRecipe(loaded.ref.key);
      setConfirmDelete(false);
      await refreshRecipes(SYSTEM_RECIPE_KEY);
    } catch (e) {
      setRecipeError(errorMessage(e));
    }
  };
  const loadFromHistory = async (id: string) => {
    try {
      const d = await equivApi.get(id);
      const snap = d.recipe_snapshot;
      const def: EqDefinition = { schema_version: snap.schema_version, metrics: snap.metrics, pair_rule: snap.pair_rule, verdict_rule: snap.verdict_rule };
      const key = d.recipe.key ?? (d.recipe.source === "system" ? SYSTEM_RECIPE_KEY : null);
      const item = key ? (recipes ?? []).find((r) => r.key === key) ?? null : null;
      const ref = key ? { key, version: d.recipe.version ?? item?.version ?? 1 } : null;
      applyDefinition(ref, item, def, versionNote(d.recipe) ?? `${d.label}의 레시피 스냅숏을 불러왔습니다`);
      setEditorOpen(true);
    } catch (e) {
      setRecipeError(errorMessage(e));
    }
  };

  const perfNames = useMemo(() => Array.from(new Set([...(preview?.side_a.responses ?? []), ...(preview?.side_b.responses ?? [])])), [preview]);
  const selectedKey = loaded?.ref?.key ?? "";
  const readonly = !canExec || !loaded;
  const canEditRecipe = !!loaded?.item && !loaded.item.readonly && loaded.item.can_edit;
  return (
    <div className="eq-tab" data-testid="equiv-tab">
      <section className="eq-section" aria-label="비교 대상">
        <h4 className="eq-h">1. 비교 대상</h4>
        <SidePicker slot="A(기준)" sel={sideA} onChange={setSideA} batches={batches} does={does} fems={fems} disabled={!canExec} />
        <SidePicker slot="B(비교)" sel={sideB} onChange={setSideB} batches={batches} does={does} fems={fems} disabled={!canExec} />
        <div className="eq-row">
          <div className="seg" role="group" aria-label="쌍 방식">
            {(["by_name", "by_params", "manual"] as EqPairingMode[]).map((m) => (
              <button key={m} type="button" className={mode === m ? "on" : ""} aria-pressed={mode === m} disabled={!canExec} onClick={() => setMode(m)}>
                {m === "by_name" ? "이름" : m === "by_params" ? "파라미터 값" : "직접 지정"}
              </button>
            ))}
          </div>
          {mode === "manual" && <textarea aria-label="쌍 직접 지정" rows={2} placeholder={"A run, B run (줄마다 1쌍)"} value={manual} onChange={(e) => setManual(e.target.value)} />}
          {preview && (
            <span className="muted small" data-testid="eq-pair-preview">
              쌍 {preview.pairing.n_pairs} · 짝 없음 A {preview.unmatched_a.length}{preview.unmatched_a.length ? `(${preview.unmatched_a.slice(0, 5).join(", ")}${preview.unmatched_a.length > 5 ? " …" : ""})` : ""} / B {preview.unmatched_b.length}
              {preview.unmatched_b.length ? `(${preview.unmatched_b.slice(0, 5).join(", ")}${preview.unmatched_b.length > 5 ? " …" : ""})` : ""}
              {preview.extract.h3d_runs + preview.extract.t01_runs > 0 ? ` · 추출 필요 h3d ${preview.extract.h3d_runs}·T01 ${preview.extract.t01_runs}` : " · 기존 값 재사용"}
            </span>
          )}
          {previewError && <span className="error-text small" role="alert">{previewError}</span>}
        </div>
        {preview && preview.problems.length > 0 && (
          <ul className="error-text small eq-problems" data-testid="eq-problems">
            {preview.problems.map((p, i) => (
              <li key={`${p.code}-${i}`}>{p.message}</li>
            ))}
          </ul>
        )}
        {preview && preview.warnings.length > 0 && (
          <ul className="muted small eq-warnings" data-testid="eq-preview-warnings">
            {preview.warnings.slice(0, 6).map((w, i) => (
              <li key={`${w.code}-${i}`}>{w.message}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="eq-section" aria-label="레시피">
        <h4 className="eq-h">2. 레시피</h4>
        <div className="eq-row">
          <select aria-label="레시피 선택" value={selectedKey} disabled={!recipes} onChange={(e) => void pickRecipe(e.target.value)}>
            {!selectedKey && <option value="">(이력 스냅숏 — 저장 안 됨)</option>}
            {GROUPS.map((g) => {
              const items = (recipes ?? []).filter((r) => r.scope === g.scope);
              return items.length ? (
                <optgroup key={g.scope} label={g.label}>
                  {items.map((r) => (
                    <option key={r.key} value={r.key}>
                      {r.name} · v{r.version}
                    </option>
                  ))}
                </optgroup>
              ) : null;
            })}
          </select>
          {loaded?.item?.readonly && <span className="muted small">{RECIPE_HINT}</span>}
          {loaded?.note && <span className="muted small" data-testid="eq-recipe-note">{loaded.note}</span>}
          {modified && <span className="pill warn" data-testid="eq-modified">수정됨{adhoc ? " · 이번만 사용" : ""}</span>}
          <button type="button" className="btn ghost small" aria-expanded={editorOpen} onClick={() => setEditorOpen((o) => !o)}>
            편집
          </button>
        </div>
        {editorOpen && loaded && (
          <div className="eq-editor-wrap" data-testid="eq-editor-open">
            <RecipeEditor rows={rows} onChange={(r) => (setRows(r), setAdhoc(false))} perfNames={perfNames} readonly={readonly} pairRule={pairRule} onPairRule={setPairRule} />
            <div className="eq-row eq-recipe-actions">
              <button type="button" className="btn ghost small" disabled={!modified || isSystem} title={isSystem ? SYSTEM_RUN_TEXT : undefined} onClick={() => (setAdhoc(true), setEditorOpen(false))}>
                이번만 사용
              </button>
              <button type="button" className="btn ghost small" disabled={!canEditRecipe || !modified} title={loaded.item?.readonly ? "시스템 기본은 수정할 수 없습니다 — 다른 이름으로 저장" : undefined} onClick={() => void saveVersion()}>
                새 버전 저장
              </button>
              <button type="button" className="btn ghost small" disabled={!canExec} onClick={() => setSaveAs({ name: loaded.item?.readonly ? "" : `${loaded.item?.name ?? "레시피"} 복제`, scope: "study", description: "" })}>
                다른 이름으로 저장
              </button>
              {confirmDelete ? (
                <>
                  <button type="button" className="btn danger small" onClick={() => void doDelete()}>
                    정말 삭제
                  </button>
                  <button type="button" className="btn ghost small" onClick={() => setConfirmDelete(false)}>
                    취소
                  </button>
                </>
              ) : (
                <button type="button" className="btn ghost small" disabled={!canEditRecipe} onClick={() => setConfirmDelete(true)}>
                  삭제
                </button>
              )}
            </div>
            {saveAs && (
              <div className="eq-row eq-saveas" data-testid="eq-saveas">
                <input aria-label="레시피 이름" placeholder="레시피 이름(60자 이내)" maxLength={60} value={saveAs.name} onChange={(e) => setSaveAs({ ...saveAs, name: e.target.value })} />
                <div className="seg" role="group" aria-label="저장 범위">
                  {(["study", "global"] as const).map((s) => (
                    <button key={s} type="button" className={saveAs.scope === s ? "on" : ""} aria-pressed={saveAs.scope === s} onClick={() => setSaveAs({ ...saveAs, scope: s })}>
                      {s === "study" ? "이 Study" : "전역"}
                    </button>
                  ))}
                </div>
                <input aria-label="레시피 설명" placeholder="설명(선택)" maxLength={500} value={saveAs.description} onChange={(e) => setSaveAs({ ...saveAs, description: e.target.value })} />
                <button type="button" className="btn small" disabled={!saveAs.name.trim()} onClick={() => void doSaveAs()}>
                  저장
                </button>
                <button type="button" className="btn ghost small" onClick={() => setSaveAs(null)}>
                  취소
                </button>
              </div>
            )}
          </div>
        )}
        {recipeError && <p className="error-text small" role="alert">{recipeError}</p>}
        {isSystem && (
          <p className="eq-unbound small" data-testid="eq-system-block">
            {SYSTEM_RUN_TEXT}
          </p>
        )}
        {unbound.length > 0 && (
          <p className="eq-unbound small" data-testid="eq-unbound">
            {UNBOUND_TEXT}: {unbound.map((r) => r.label).join(", ")}
          </p>
        )}
      </section>

      <section className="eq-section" aria-label="실행">
        <h4 className="eq-h">3. 실행</h4>
        <div className="eq-row">
          <input aria-label="메모" placeholder="메모(선택, 500자)" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} disabled={!canExec} />
          <button type="button" className="btn" disabled={!canRun} title={!canExec ? "실행 권한(power 이상)이 필요합니다" : isSystem ? SYSTEM_RUN_TEXT : unbound.length ? UNBOUND_TEXT : undefined} onClick={() => void run()}>
            판정 실행
          </button>
          {job && <JobInline job={job} />}
        </div>
        {runError && <p className="error-text small" role="alert">{runError}</p>}
      </section>

      <section className="eq-section" aria-label="결과">
        <h4 className="eq-h">4. 결과</h4>
        {current && (
          <div className="run-action-row">
            <ReportButton load={() => reportApi.byTarget("equiv-check", current.id)} fallbackName={`PAI_${study.folder_name}_equiv-check_${current.id.slice(0, 8)}.html`} notReady={current.status === "RUNNING" ? `진행 중 — ${NOT_READY_TEXT}` : null} resetKey={`${current.id}:${current.status}`} />
          </div>
        )}
        {current ? <ResultView check={current} onNoteSaved={(n) => (setCurrent({ ...current, note: n }), void loadHistory(false))} /> : <p className="muted small">판정을 실행하거나 이력에서 열면 여기 보입니다.</p>}
      </section>

      <section className="eq-section" aria-label="이력">
        <h4 className="eq-h">5. 이력</h4>
        <HistoryList items={history} onOpen={(id) => void openCheck(id)} onLoadRecipe={(id) => void loadFromHistory(id)} nextCursor={cursor} onMore={() => void loadHistory(true)} loading={histLoading} />
      </section>
    </div>
  );
}
