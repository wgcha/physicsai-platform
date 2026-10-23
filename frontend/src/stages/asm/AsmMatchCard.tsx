// 조립 매칭 카드(asm-match.md §3·§6.5, ①-2와 ①-3 사이·④ 등록 폼 공용):
// 조립 폴더 지정 → [목록 읽기](ASM_MATCH 작업) → 추천으로 채운 매칭 표(확인·수정) → [저장].
// 경계 검사(AM-C3)는 "고급"(기본 접힘) 안의 선택 기능: [검사]·진행률·[취소]·판정·거리·3D(거리 색·worst). 불합격이어도 저장은 막지 않는다.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, errorMessage, type AsmMatch, type AsmMatchCreate, type Job } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute } from "../../hooks/useJobRunner";
import { usePolling } from "../../hooks/usePolling";
import { Card, JobInline } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { isTerminal } from "../../lib/format";
import { POLL } from "../../lib/poll";
import {
  ASM_FIRST_TEXT, CHECK_SLOW_TEXT, asmCodeText, checkBlock, checkNotice, draftProblems, emptyDraft, failLines, initialDraft, isAsmMissing, problemsOf, putKey, recommendDraft,
  rowNotes, saveBlock, stateLabel, toPut, type Draft, type RowNotes,
} from "../../lib/asmMatch";
import { AsmMatchTable } from "./AsmMatchTable";
import { AsmMatchViewer } from "./AsmMatchViewer";

const NO_NOTES: RowNotes = { byBody: {}, general: [] };
const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
const base = (p: string) => p.replace(/\\/g, "/").split("/").pop() ?? "";

export function AsmMatchCard({
  cad, assemPath, embedded = false, onConfirmed,
}: {
  /** CAD 출처: ① = 학습 설정의 ①-1 추출(train), ④ 등록 = 고른 STEP 파일 경로(path) */
  cad: AsmMatchCreate["cad"];
  /** 조립 폴더를 이미 정했을 때(④ 등록 폼) — 폴더 입력 없이 이 경로로 읽는다 */
  assemPath?: string;
  /** Card 껍데기 없이 본문만(④ 등록 폼 안) */
  embedded?: boolean;
  /** 저장(확정)된 매칭이 바뀔 때(없어지면 null) */
  onConfirmed?: (m: AsmMatch | null) => void;
}) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const [path, setPath] = useState(assemPath ?? "");
  const [pathOk, setPathOk] = useState(!!assemPath);
  const [match, setMatch] = useState<AsmMatch | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [fromRec, setFromRec] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [advOpen, setAdvOpen] = useState(false); // 고급(경계 검사) 접힘 — 기본 접힘
  const [notes, setNotes] = useState<RowNotes>(NO_NOTES);
  const confirmedCb = useRef(onConfirmed);
  confirmedCb.current = onConfirmed;

  /** 서버 상태를 읽어 화면에 반영. reset = 표 초안을 서버 표(없으면 추천)로 다시 채움 */
  const load = useCallback(async (id: string, reset: boolean) => {
    const m = await api.asmMatch(id);
    setMatch(m);
    if (reset) {
      const d = initialDraft(m);
      setDraft(d.draft);
      setFromRec(d.fromRecommend);
    }
    confirmedCb.current?.(m.state === "CONFIRMED" ? m : null);
    return m;
  }, []);

  // 작업 진행: 끝나면 매칭을 다시 읽는다(목록 읽기 뒤에는 표를 새로 채움, 검사 뒤에는 편집 중인 표 유지)
  const following = useRef<{ id: string; reset: boolean } | null>(null);
  const follow = async (jobId: string, id: string, reset: boolean) => {
    following.current = { id, reset };
    setJob(await api.job(jobId));
  };

  // 처음 열 때: 서버 목록 API로 이 Study의 마지막 매칭을 다시 찾는다(localStorage 없음). ④는 같은 조립 폴더·STEP의 매칭만 이어 쓴다
  const cadKey = cad.kind === "path" ? cad.path ?? "" : "";
  useEffect(() => {
    let alive = true;
    api
      .asmMatches(study.id, { source: cad.kind, latest: true, limit: 1 })
      .then((r) => {
        const m = r.items.find((x) => cad.kind === "train" || (!!assemPath && norm(x.assem.display_path) === norm(assemPath) && x.source.cad_name === base(cadKey)));
        if (!m || !alive) return;
        const d = initialDraft(m);
        setMatch(m);
        setDraft(d.draft);
        setFromRec(d.fromRecommend);
        if (!assemPath) {
          setPath(m.assem.display_path);
          setPathOk(true);
        }
        confirmedCb.current?.(m.state === "CONFIRMED" ? m : null);
        const lj = m.last_job;
        if (m.state === "CHECKING") setAdvOpen(true); // 진행 중인 검사가 있으면 진행률·[취소]가 보이게 펼친다
        if (lj && (m.state === "SCANNING" || m.state === "CHECKING")) void follow(lj.id, m.match_id, lj.mode === "parts");
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [study.id, cad.kind, cadKey, assemPath]);

  const pollJob = useCallback(async () => {
    const f = following.current;
    if (!job || !f) return;
    const j = await api.job(job.id);
    setJob(j);
    if (isTerminal(j.state)) {
      following.current = null;
      await load(f.id, f.reset);
    }
  }, [job, load]);
  usePolling(pollJob, job && !isTerminal(job.state) && following.current ? (job.state === "QUEUED" ? POLL.jobQueued : POLL.jobActive) : null, false, [job?.id, job?.state]);

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError) {
        // 422 ASM_ROW_INVALID problems[] → 행 옆 안내(코드별 한국어), 바디 없는 사유는 아래 한 줄
        const n = rowNotes(problemsOf(e.detail));
        setNotes(n);
        setError(isAsmMissing(e.detail) ? ASM_FIRST_TEXT : [asmCodeText(e.code, e.message), ...n.general].join(" — "));
      } else setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const scan = () =>
    guard(async () => {
      const r = await api.asmMatchCreate(study.id, { radioss_assem_path: path.trim(), cad });
      setSelected(null);
      setNotes(NO_NOTES);
      setDraft(emptyDraft());
      confirmedCb.current?.(null);
      await load(r.match_id, false);
      await follow(r.job_id, r.match_id, true);
    });

  /** 고급: 경계 검사(선택). 표를 초안으로 저장한 뒤 검사한다 — 검사는 서버에 저장된 표 기준 */
  const check = () =>
    guard(async () => {
      if (!match) return;
      const put = toPut(match, draft);
      setNotes(NO_NOTES);
      setAdvOpen(true);
      if (putKey(put) !== putKey({ rows: match.rows, excluded_bodies: match.excluded_bodies }) || match.state !== "DRAFT") setMatch(await api.putAsmRows(match.match_id, put));
      const r = await api.checkAsmMatch(match.match_id);
      await load(match.match_id, false);
      await follow(r.job_id, match.match_id, false);
    });

  /** 고급: 진행 중인 검사 취소(power — 작업 취소 API는 관리자 전용이라 전용 경로). 작업이 CANCELED로 끝나면 표는 그대로 다시 읽는다 */
  const cancelCheck = () =>
    guard(async () => {
      if (!match) return;
      setMatch(await api.cancelAsmMatch(match.match_id));
    });

  /** 저장 = 확정. 검사는 필요 없다(AM-C3) — 바뀐 표는 먼저 저장(PUT)하고 확정한다. 검사 불합격·낡음은 응답 warnings로만 알린다 */
  const save = () =>
    guard(async () => {
      if (!match) return;
      const put = toPut(match, draft);
      setNotes(NO_NOTES);
      if (putKey(put) !== putKey({ rows: match.rows, excluded_bodies: match.excluded_bodies })) await api.putAsmRows(match.match_id, put);
      const m = await api.confirmAsmMatch(match.match_id);
      setMatch(m);
      confirmedCb.current?.(m);
    });

  const running = !!job && !isTerminal(job.state);
  const state = match?.state ?? null;
  const readOnly = !canExec || running || state === "CONFIRMED" || state === "SCANNING" || state === "CHECKING";
  const serverKey = match ? putKey({ rows: match.rows, excluded_bodies: match.excluded_bodies }) : "";
  const dirty = !!match && putKey(toPut(match, draft)) !== serverKey;
  const problems = match ? draftProblems(match, draft) : [];
  const cBlock = !match ? null : checkBlock(match, draft);
  const sBlock = !match ? null : saveBlock(match, draft);
  const unmatched = match ? match.parts.length - Object.values(draft.pids).reduce((n, l) => n + l.length, 0) : 0;
  const notice = match ? checkNotice(match, draft) : null;
  const failRows = match?.check?.rows.filter((r) => r.status === "FAIL") ?? [];
  const lines = failRows.flatMap((r) => failLines(r).map((t) => ({ body: r.body, text: t })));
  const tetra = match?.parts.filter((p) => p.solid_ok).length ?? 0;

  const lj = match?.last_job;
  const jobFailed = !!lj && lj.state === "FAILED" && !running;
  const checking = state === "CHECKING";

  const content = (
    <>
      {!assemPath && <PathInput
        studyId={study.id}
        purpose="RADIOSS_ASSEM"
        label="조립 폴더"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/radioss_assem"
        value={path}
        onChange={setPath}
        canExecute={canExec}
        onInspected={(r) => setPathOk(!!r?.ok)}
        renderSummary={(r) => (
          <div className="summary-line">
            starter <b className="mono">{((r.summary.starter as string[]) ?? []).join(", ") || "없음"}</b> · include {String(r.summary.inc_count ?? 0)}개
          </div>
        )}
      />}
      <div className="run-action-row">
        {canExec && (
          <button type="button" className="btn primary" onClick={() => void scan()} disabled={busy || running || !pathOk} title={!pathOk ? "조립 폴더를 입력하고 확인하세요" : undefined}>
            목록 읽기
          </button>
        )}
        {canExec && !pathOk && !assemPath && <span className="muted small">조립 폴더를 입력하고 확인하세요</span>}
        {job && <JobInline job={job} />}
        {match && (
          <span className="pill" data-testid="asm-state">
            {stateLabel(match)}
          </span>
        )}
      </div>
      {error && (
        <p className="error-text small" role="alert" data-testid="asm-error">
          {error}
        </p>
      )}
      {match && (state === "FAILED" || state === "STALE" || jobFailed) && (
        <p className="error-text small" role="alert" data-testid="asm-failed">
          {state === "STALE" ? asmCodeText("ASM_MATCH_STALE") : asmCodeText(lj?.failure_code, lj?.failure_message)}
        </p>
      )}
      {match && match.warnings.length > 0 && (
        <ul className="problems small muted" data-testid="asm-warnings">
          {match.warnings.map((w, i) => (
            <li key={i}>{asmCodeText(w.code, w.message)}</li>
          ))}
        </ul>
      )}
      {match && match.bodies.length > 0 && state !== "FAILED" && (
        <>
          <div className="summary-line small" data-testid="asm-summary">
            starter <b className="mono">{match.assem.starter}</b> · 파일 {match.assem.files}개 · component {match.parts.length}개(TETRA4 {tetra}개) · STEP 바디 {match.bodies.length}개
          </div>
          <AsmMatchTable match={match} draft={draft} onChange={(d) => (setDraft(d), setFromRec(false), setNotes(NO_NOTES))} readOnly={readOnly} notes={notes} selected={selected} onSelect={setSelected} dirty={dirty} showCheck={advOpen} />
          <p className="muted small">매칭하지 않은 component {Math.max(0, unmatched)}개는 바꾸지 않습니다(간섭 검사 대상).</p>
          {fromRec && state === "DRAFT" && <p className="muted small" data-testid="asm-recommended">추천으로 미리 채웠습니다 — 확인하고 고친 뒤 [저장]을 누르세요(저장 전에는 확정되지 않습니다).</p>}
          {notes.general.length > 0 && (
            <ul className="problems small error-text" data-testid="asm-notes-general" role="alert">
              {notes.general.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
          {notice && (
            <p className="warn-text small" data-testid="asm-check-warning" data-code={notice.code}>
              {notice.text}
            </p>
          )}
          {problems.length > 0 && (
            <ul className="problems small error-text" data-testid="asm-problems" role="alert">
              {problems.map((p, i) => (
                <li key={i}>{p.message}</li>
              ))}
            </ul>
          )}
          {canExec && state !== "CONFIRMED" && (
            <div className="run-action-row">
              <button type="button" className="btn" disabled={readOnly || match.recommend.length === 0} onClick={() => (setDraft(recommendDraft(match)), setFromRec(true))}>
                추천 적용
              </button>
              <button type="button" className="btn primary" disabled={readOnly || busy || !!sBlock} title={sBlock ?? undefined} onClick={() => void save()}>
                저장
              </button>
              {sBlock && !running && <span className="muted small" data-testid="asm-block">{sBlock}</span>}
            </div>
          )}
          {state === "CONFIRMED" && (
            <p className="ok-text small" data-testid="asm-confirmed">
              저장됨 — {cad.kind === "train" ? "①-3 DOE가" : "템플릿 등록이"} 이 매칭을 씁니다. 바꾸려면 [목록 읽기]로 다시 매칭하세요.
            </p>
          )}
          <details className="advanced asm-advanced" data-testid="asm-advanced" open={advOpen} onToggle={(e) => setAdvOpen((e.currentTarget as HTMLDetailsElement).open)}>
            <summary>고급 — 경계 검사(선택)</summary>
            <div className="advanced-body">
              <p className="muted small" data-testid="asm-check-note">
                매칭한 component의 외곽 노드가 CAD 경계면과 맞는지 미리 확인합니다. 추천·표 확인만으로 저장할 수 있으며, 검사가 불합격이어도 저장은 막지 않습니다. {CHECK_SLOW_TEXT}
              </p>
              <div className="run-action-row">
                {canExec && state !== "CONFIRMED" && (
                  <button type="button" className="btn" disabled={readOnly || busy || !!cBlock} title={cBlock ?? undefined} onClick={() => void check()}>
                    검사
                  </button>
                )}
                {canExec && checking && running && (
                  <button type="button" className="btn" disabled={busy || !!job?.cancel_requested} onClick={() => void cancelCheck()}>
                    취소
                  </button>
                )}
                {cBlock && !running && state !== "CONFIRMED" && <span className="muted small" data-testid="asm-check-block">{cBlock}</span>}
              </div>
              {match.check && lines.length > 0 && (
                <ul className="problems small" data-testid="asm-fail-lines">
                  {lines.map((l, i) => (
                    <li key={i} className="error-text">
                      <span className="mono">{l.body}</span> {l.text}
                    </li>
                  ))}
                </ul>
              )}
              {match.check ? <AsmMatchViewer check={match.check} selected={selected} /> : <p className="muted small">[검사] 뒤에 CAD 경계와의 거리를 3D로 보여줍니다.</p>}
            </div>
          </details>
        </>
      )}
    </>
  );
  return embedded ? (
    <div className="asm-card asm-embedded" data-testid="asm-embedded">
      {content}
    </div>
  ) : (
    <Card span={12} step="①-2" title="조립 매칭" className="asm-card">
      {content}
    </Card>
  );
}
