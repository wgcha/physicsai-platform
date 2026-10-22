// 조립 매칭 카드(asm-match.md §3·§6.5, ①-2와 ①-3 사이·④ 등록 폼 공용):
// 조립 폴더 지정 → [목록 읽기](ASM_MATCH 작업) → 매칭 표(추천은 초안, 확정은 사용자) → [검사](경계 일치) → 3D(거리 색·worst) → [저장].
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
  STATE_TEXT, asmCodeText, checkBlock, draftProblems, emptyDraft, failLines, initialDraft, putKey, recommendDraft, saveBlock, toPut, type Draft,
} from "../../lib/asmMatch";
import { AsmMatchTable } from "./AsmMatchTable";
import { AsmMatchViewer } from "./AsmMatchViewer";

const storeKey = (studyId: string, scope: string) => `physicsai.asmMatch.${studyId}.${scope}`;
const readStore = (k: string): string | null => {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
};
const writeStore = (k: string, v: string | null) => {
  try {
    if (v) localStorage.setItem(k, v);
    else localStorage.removeItem(k);
  } catch {
    /* 저장소 없음 */
  }
};

export function AsmMatchCard({
  cad, scope, usedParams = [], onConfirmed,
}: {
  /** CAD 출처: ① = 학습 설정의 ①-1 추출(train), ④ 등록 = 고른 STEP 경로 */
  cad: AsmMatchCreate["cad"];
  /** 마지막 매칭 id를 기억하는 자리(Study 안에서 ①·④를 구분) */
  scope: string;
  /** use=true 파라미터 이름(그 바디는 '매칭 안 함' 불가) */
  usedParams?: string[];
  /** 저장(확정)된 매칭이 바뀔 때(없어지면 null) */
  onConfirmed?: (m: AsmMatch | null) => void;
}) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const [path, setPath] = useState("");
  const [pathOk, setPathOk] = useState(false);
  const [match, setMatch] = useState<AsmMatch | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [fromRec, setFromRec] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const key = storeKey(study.id, scope);
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

  // 처음 열 때: 이 Study에서 마지막으로 다루던 매칭을 다시 읽는다(없어졌으면 잊는다)
  useEffect(() => {
    const id = readStore(key);
    if (!id) return;
    let alive = true;
    load(id, true)
      .then((m) => alive && (setPath(m.assem.display_path), setPathOk(true), setJob(null)))
      .catch(() => writeStore(key, null));
    return () => {
      alive = false;
    };
  }, [key, load]);

  // 작업 진행: 끝나면 매칭을 다시 읽는다(목록 읽기 뒤에는 표를 새로 채움, 검사 뒤에는 편집 중인 표 유지)
  const following = useRef<{ id: string; reset: boolean } | null>(null);
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
      setError(e instanceof ApiError ? asmCodeText(e.code, e.message) : errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const follow = async (jobId: string, id: string, reset: boolean) => {
    following.current = { id, reset };
    setJob(await api.job(jobId));
  };

  const scan = () =>
    guard(async () => {
      const r = await api.asmMatchCreate(study.id, { radioss_assem_path: path.trim(), cad });
      writeStore(key, r.match_id);
      setSelected(null);
      setDraft(emptyDraft());
      confirmedCb.current?.(null);
      await load(r.match_id, false);
      await follow(r.job_id, r.match_id, true);
    });

  const check = () =>
    guard(async () => {
      if (!match) return;
      const put = toPut(match, draft);
      // 표를 저장(초안)한 뒤 검사한다 — 검사는 서버에 저장된 표 기준
      if (putKey(put) !== putKey({ rows: match.rows, excluded_bodies: match.excluded_bodies }) || match.state !== "DRAFT") setMatch(await api.putAsmRows(match.match_id, put));
      const r = await api.checkAsmMatch(match.match_id);
      await load(match.match_id, false);
      await follow(r.job_id, match.match_id, false);
    });

  const save = () =>
    guard(async () => {
      if (!match) return;
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
  const failRows = match?.check?.rows.filter((r) => r.status === "FAIL") ?? [];
  const lines = failRows.flatMap((r) => failLines(r).map((t) => ({ body: r.body, text: t })));
  const tetra = match?.parts.filter((p) => p.solid_ok).length ?? 0;

  return (
    <Card span={12} step="①-2" title="조립 매칭" className="asm-card">
      <PathInput
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
      />
      <div className="run-action-row">
        {canExec && (
          <button type="button" className="btn primary" onClick={() => void scan()} disabled={busy || running || !pathOk} title={!pathOk ? "조립 폴더를 입력하고 확인하세요" : undefined}>
            목록 읽기
          </button>
        )}
        {canExec && !pathOk && <span className="muted small">조립 폴더를 입력하고 확인하세요</span>}
        {job && <JobInline job={job} />}
        {match && (
          <span className="pill" data-testid="asm-state">
            {STATE_TEXT[match.state]}
          </span>
        )}
      </div>
      {error && (
        <p className="error-text small" role="alert" data-testid="asm-error">
          {error}
        </p>
      )}
      {match && (state === "FAILED" || state === "STALE") && (
        <p className="error-text small" role="alert" data-testid="asm-failed">
          {state === "STALE" ? asmCodeText("ASM_MATCH_STALE") : asmCodeText(match.code, match.message)}
        </p>
      )}
      {match && match.bodies.length > 0 && state !== "FAILED" && (
        <>
          <div className="summary-line small" data-testid="asm-summary">
            starter <b className="mono">{match.assem.starter}</b> · 파일 {match.assem.files}개 · component {match.parts.length}개(TETRA4 {tetra}개) · STEP 바디 {match.bodies.length}개
          </div>
          <div className="asm-split">
            <div className="asm-left">
              <AsmMatchTable match={match} draft={draft} onChange={(d) => (setDraft(d), setFromRec(false))} readOnly={readOnly} usedParams={usedParams} selected={selected} onSelect={setSelected} dirty={dirty} />
              <p className="muted small">매칭하지 않은 component {Math.max(0, unmatched)}개는 바꾸지 않습니다(간섭 검사 대상).</p>
              {fromRec && state === "DRAFT" && <p className="muted small" data-testid="asm-recommended">추천으로 미리 채웠습니다 — 확인하고 고치세요(저장 전에는 확정되지 않습니다).</p>}
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
                  <button type="button" className="btn primary" disabled={readOnly || busy || !!cBlock} title={cBlock ?? undefined} onClick={() => void check()}>
                    검사
                  </button>
                  <button type="button" className="btn primary" disabled={readOnly || busy || !!sBlock} title={sBlock ?? undefined} onClick={() => void save()}>
                    저장
                  </button>
                  {(cBlock ?? sBlock) && !running && <span className="muted small" data-testid="asm-block">{state === "CHECKED" || match.check ? sBlock : cBlock}</span>}
                </div>
              )}
              {state === "CONFIRMED" && (
                <p className="ok-text small" data-testid="asm-confirmed">
                  저장됨 — ①-3 DOE가 이 매칭을 씁니다. 바꾸려면 [목록 읽기]로 다시 매칭하세요.
                </p>
              )}
              {match.check && lines.length > 0 && (
                <ul className="problems small" data-testid="asm-fail-lines">
                  {lines.map((l, i) => (
                    <li key={i} className="error-text">
                      <span className="mono">{l.body}</span> {l.text}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="asm-right">{match.check ? <AsmMatchViewer check={match.check} selected={selected} /> : <p className="muted small">[검사] 뒤에 CAD 경계와의 거리를 3D로 보여줍니다.</p>}</div>
          </div>
        </>
      )}
    </Card>
  );
}
