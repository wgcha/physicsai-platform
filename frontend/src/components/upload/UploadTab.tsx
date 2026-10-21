// "내 PC에서 올리기" 탭(upload-report.md §3.2; esl UploadPanel 일반화): 파일·폴더 선택/끌어다 놓기 → 미리 검사(제외·이름 위반) → 분할 업로드
// (진행률·속도·남은 시간·멈춤/이어 올리기·취소) → complete → 경로 칸에 채움. 업로드는 "경로 만들기"일 뿐이다 — 이후 흐름은 기존 확인·작업 생성 그대로.
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { errorMessage, type PathInspectResult } from "../../api";
import type { UploadConfig, UploadPurpose } from "../../api/uploads";
import { fmtBytes } from "../../lib/format";
import { ASSUMED_BPS, Uploader, etaText, hasSavedSession, type UploadProgress } from "../../lib/uploader";
import { modeOf, patternsFor, precheck, relFromFile, rootName, sessionName, type PickedItem } from "./uploadRules";
import "../../styles/upload.css";

/** 대용량 purpose 안내(§3.2) */
export const BIG_NOTE = "h3d 30 GB ≈ 1 Gbps 약 5분, 100 Mbps 약 45분. 끊겨도 같은 폴더를 다시 고르면 받은 데부터 이어서 보냅니다. 탭을 닫지 마세요.";
const BIG_PURPOSES: UploadPurpose[] = ["RESULT_FOLDER", "DATASET_INPUT", "CURATION_INPUT"];
export const RENAME_HINT = "이름을 바꿔 다시 선택하세요";

const PHASE_TEXT: Record<string, string> = {
  uploading: "올리는 중",
  paused: "멈춤 — '이어 올리기'로 계속",
  error: "실패 — '이어 올리기'로 받은 데부터 다시 보냅니다",
  uploaded: "올리기 완료",
  completing: "서버에서 확인 중…",
  done: "올리기·확인 완료",
  canceled: "취소됨",
};

type Picked = { file: File; path?: string };

/** 끌어다 놓은 항목(폴더 포함)을 [파일, 상대경로]로 펼친다 */
async function filesFromDrop(e: DragEvent): Promise<Picked[]> {
  const items = [...(e.dataTransfer.items ?? [])];
  const entries = items.map((it) => (typeof it.webkitGetAsEntry === "function" ? it.webkitGetAsEntry() : null)).filter(Boolean) as FileSystemEntry[];
  if (!entries.length) return [...(e.dataTransfer.files ?? [])].map((file) => ({ file }));
  const out: Picked[] = [];
  async function walk(en: FileSystemEntry, prefix: string): Promise<void> {
    if (en.isFile) {
      const file = await new Promise<File>((res, rej) => (en as FileSystemFileEntry).file(res, rej));
      out.push({ file, path: prefix + en.name });
    } else if (en.isDirectory) {
      const reader = (en as FileSystemDirectoryEntry).createReader();
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const c of batch) await walk(c, `${prefix}${en.name}/`);
      }
    }
  }
  for (const en of entries) await walk(en, "");
  return out;
}

const acceptOf = (patterns: string[]) => patterns.filter((p) => /^\*\.[a-z0-9]+$/i.test(p)).map((p) => p.slice(1)).join(",") || undefined;
const listLimit = (n: number) => (n > 200 ? 200 : n);

export function UploadTab({
  studyId,
  purpose,
  engine,
  cfg,
  canExecute,
  onDone,
  uploaderOpts,
}: {
  studyId: string;
  purpose: UploadPurpose;
  engine?: "native" | "altair" | null;
  cfg: UploadConfig;
  canExecute: boolean;
  /** complete 가 COMPLETED 로 끝났을 때: 경로 칸에 채울 path 와 서버가 본 inspect(없으면 null) */
  onDone: (path: string, inspect: PathInspectResult | null, summary: { files: number; bytes: number }) => void;
  uploaderOpts?: ConstructorParameters<typeof Uploader>[3];
}) {
  const [items, setItems] = useState<PickedItem[]>([]);
  const [root, setRoot] = useState<string | null>(null);
  const [prog, setProg] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<{ code?: string; message?: string | null; file?: string | null }[] | null>(null);
  const [over, setOver] = useState(false);
  const up = useRef<Uploader | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const addRef = useRef<HTMLInputElement>(null);
  const mode = modeOf(cfg, purpose);
  const patterns = patternsFor(cfg, purpose, engine);
  const started = !!up.current;
  const busy = prog?.phase === "uploading" || prog?.phase === "completing";

  useEffect(() => {
    dirRef.current?.setAttribute("webkitdirectory", "");
    dirRef.current?.setAttribute("directory", "");
  }, [mode]);
  // 페이지 이탈 경고(업로드·확인 중에만) — 탭을 닫으면 받은 데까지는 서버에 남아 이어 올릴 수 있다
  useEffect(() => {
    if (!busy) return;
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [busy]);
  // 화면이 사라지면(경로 이동) 보내던 것은 멈춘다 — 세션은 서버·localStorage 에 남아 이어 올릴 수 있다
  useEffect(() => () => up.current?.stop(), []);

  const checked = useMemo(() => precheck(items, cfg, purpose, engine), [items, cfg, purpose, engine]);
  const saved = useMemo(() => !started && checked.ok.length > 0 && hasSavedSession(studyId, purpose, checked.ok.map((x) => ({ file: x.file, rel: x.rel }))), [started, checked, studyId, purpose]);

  const reset = () => {
    up.current?.stop();
    up.current = null;
    setItems([]);
    setRoot(null);
    setProg(null);
    setError(null);
    setProblems(null);
  };

  const pick = (list: Picked[]) => {
    if (!list.length || started) return;
    const next: PickedItem[] = list.map(({ file, path }) => ({ file, rel: relFromFile(file, path) }));
    // 파일 선택은 이전 선택에 더하고(이름이 같으면 교체), 폴더 선택·끌어다 놓기는 새 선택
    const folder = list.some(({ file, path }) => rootName(file, path) !== null);
    setItems(folder || mode === "file" ? next : [...items.filter((x) => !next.some((n) => n.rel === x.rel)), ...next]);
    setRoot(folder ? rootName(list[0].file, list[0].path) : null);
    setError(null);
  };

  const finish = async (u: Uploader) => {
    try {
      const r = await u.complete();
      if (r.state === "COMPLETED" && r.path) {
        onDone(r.path, r.inspect ?? null, { files: u.files.length, bytes: u.total() });
        reset();
      } else {
        // inspect 실패: OPEN 유지 — 파일을 더 올리고 다시 확인할 수 있다
        setProblems([...(r.inspect?.problems ?? []), ...(r.problems ?? [])]);
      }
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const start = async () => {
    setError(null);
    setProblems(null);
    if (!up.current) {
      const files = checked.ok.map((x) => ({ file: x.file, rel: x.rel }));
      up.current = new Uploader({ studyId, purpose, name: sessionName(root, files[0]?.file.name), engine }, files, setProg, uploaderOpts);
    }
    if (prog?.phase === "uploaded") await finish(up.current);
    else if (await up.current.run()) await finish(up.current);
  };

  const cancel = async () => {
    const u = up.current;
    if (!u) return reset();
    try {
      await u.cancel();
      reset();
    } catch (e) {
      setError(errorMessage(e));
      reset();
    }
  };

  const addMore = async (list: FileList | null) => {
    const u = up.current;
    if (!list || !u) return;
    const more = precheck([...list].map((file) => ({ file, rel: file.name })), cfg, purpose, engine);
    if (more.bad.length) return setError(`이름 규칙 위반: ${more.bad.map((b) => b.rel).join(", ")} — ${RENAME_HINT}`);
    if (!more.ok.length) return setError("올릴 수 있는 파일이 없습니다");
    setError(null);
    setProblems(null);
    setItems((x) => [...x, ...more.ok]);
    try {
      if (await u.add(more.ok.map((x) => ({ file: x.file, rel: x.rel })))) await finish(u);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const total = checked.bytes;
  const sent = prog?.sent ?? 0;
  const frac = prog?.total ? sent / prog.total : 0;
  const rate = prog?.rate ?? null;
  const reason = !canExecute ? "실행 권한(power 이상)이 필요합니다" : checked.bad.length ? RENAME_HINT : checked.shape;
  const resumable = prog && (prog.phase === "error" || prog.phase === "paused");
  const label = resumable || saved ? "이어 올리기" : prog?.phase === "uploaded" ? "다시 확인" : "올리기";
  const cur = prog && items.length ? checked.ok[Math.min(prog.current, checked.ok.length - 1)] : null;
  const curFrac = prog && cur && cur.file.size ? Math.min(1, (prog.received[prog.current] ?? 0) / cur.file.size) : 0;
  const lock = !canExecute || started;

  return (
    <div className="upload-panel" data-testid="upload-tab">
      <div
        className={`dropzone${over ? " over" : ""}${items.length ? " has" : ""}`}
        data-testid="upload-drop"
        onDragOver={(e) => {
          e.preventDefault();
          if (!lock) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={async (e) => {
          e.preventDefault();
          setOver(false);
          if (!lock) pick(await filesFromDrop(e));
        }}
      >
        <div className="actions">
          {mode !== "file" && (
            <button type="button" className="btn small" disabled={lock} onClick={() => dirRef.current?.click()}>
              폴더 선택
            </button>
          )}
          <button type="button" className="btn small" disabled={lock} onClick={() => fileRef.current?.click()}>
            파일 선택
          </button>
          <span className="small muted">또는 여기로 끌어다 놓기{mode === "file" ? " — 파일 1개" : ""}</span>
        </div>
        <div className="small muted">올릴 수 있는 파일: <span className="mono">{patterns.join(" ")}</span></div>
        <input ref={fileRef} type="file" multiple={mode !== "file"} hidden aria-label="올릴 파일" accept={acceptOf(patterns)} onChange={(e) => (pick([...(e.target.files ?? [])].map((file) => ({ file, path: file.name }))), (e.target.value = ""))} />
        {mode !== "file" && <input ref={dirRef} type="file" multiple hidden aria-label="올릴 폴더" onChange={(e) => (pick([...(e.target.files ?? [])].map((file) => ({ file }))), (e.target.value = ""))} />}
      </div>
      {BIG_PURPOSES.includes(purpose) && <div className="small muted">{BIG_NOTE}</div>}

      {checked.bad.length > 0 && (
        <div className="upload-bad" role="alert" data-testid="upload-bad">
          <b>이름 규칙 위반 {checked.bad.length}개 — {RENAME_HINT}</b>
          <ul className="small">
            {checked.bad.slice(0, 20).map((b) => (
              <li key={b.rel}>
                <span className="mono">{b.rel}</span> — {b.reason}
              </li>
            ))}
            {checked.bad.length > 20 && <li>… 외 {checked.bad.length - 20}개</li>}
          </ul>
          <span className="small muted">공백·괄호·&amp; ; , = ' 등은 이후 작업 경로 규칙상 쓸 수 없습니다(파일 안 참조가 깨져 자동 이름 바꾸기는 하지 않습니다).</span>
        </div>
      )}
      {items.length > 0 && (
        <div className="upload-summary" data-testid="upload-summary">
          <span>
            올릴 파일 {checked.ok.length}개 · {fmtBytes(total)}
            {checked.excluded.length > 0 && <> · 제외 {checked.excluded.length}개</>}
          </span>
          <span className="muted small">
            {prog && rate && prog.phase === "uploading" ? `${fmtBytes(rate)}/s · 남은 시간 약 ${etaText(prog.total - sent, rate)}` : !prog && total > 0 ? `예상 약 ${etaText(total, ASSUMED_BPS)} (30 MB/s 기준)` : null}
          </span>
          <span className="spacer" />
          {reason && !busy && prog?.phase !== "done" && (
            <span className="small warn-text" data-testid="upload-start-reason">
              {reason}
            </span>
          )}
          {!busy && (
            <button type="button" className="btn" disabled={!!reason || checked.ok.length === 0} title={reason ?? undefined} onClick={() => void start()}>
              {label}
            </button>
          )}
          {prog?.phase === "uploading" && (
            <button type="button" className="btn ghost" onClick={() => up.current?.stop()}>
              멈춤
            </button>
          )}
          {started ? (
            <button type="button" className="btn ghost" onClick={() => void cancel()} disabled={prog?.phase === "completing"}>
              취소
            </button>
          ) : (
            <button type="button" className="btn ghost" onClick={reset}>
              지우기
            </button>
          )}
        </div>
      )}
      {saved && !prog && <div className="small muted" data-testid="upload-resume-hint">이전에 올리던 같은 파일 묶음이 있습니다 — 서버가 받은 데부터 이어서 보냅니다.</div>}
      {prog && (
        <div className="upload-progress" aria-label="올리기 진행">
          <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(frac * 100)}>
            <div className="progress-fill" style={{ width: `${(frac * 100).toFixed(1)}%` }} />
          </div>
          <div className="small" data-testid="upload-overall">
            <b>{Math.floor(frac * 100)}%</b> {fmtBytes(sent)} / {fmtBytes(prog.total)} · {PHASE_TEXT[prog.phase] ?? prog.phase}
            {prog.resumed && <span className="muted"> · 이어 올리기</span>}
            {prog.retries > 0 && <span className="muted"> · 재시도 {prog.retries}회</span>}
          </div>
          {cur && prog.phase !== "uploaded" && prog.phase !== "done" && (
            <div className="small muted" data-testid="upload-current">
              파일 {Math.min(prog.current + 1, checked.ok.length)}/{checked.ok.length} · <span className="mono">{cur.rel}</span> {Math.floor(curFrac * 100)}%
            </div>
          )}
          {prog.error && <div className="small error-text" role="alert">{prog.error}</div>}
        </div>
      )}
      {error && <div className="small error-text" role="alert">{error}</div>}
      {problems && (
        <div className="inspect bad" aria-label="올린 파일 확인 결과" data-testid="upload-problems">
          <b>올린 파일 확인 결과 보완이 필요합니다</b>
          <ul className="problems">
            {problems.map((p, i) => (
              <li key={i}>
                {p.code && <code>{p.code}</code>} {p.message ?? ""} {p.file && <span className="mono small">{p.file}</span>}
              </li>
            ))}
          </ul>
          <div className="actions">
            <button type="button" className="btn small" onClick={() => addRef.current?.click()}>
              빠진 파일 추가
            </button>
            <span className="small muted">파일을 골라 올리면 다시 확인합니다.</span>
          </div>
        </div>
      )}
      <input ref={addRef} type="file" multiple hidden aria-label="추가로 올릴 파일" onChange={(e) => (void addMore(e.target.files), (e.target.value = ""))} />
      {items.length > 0 && (
        <details className="upload-files">
          <summary>올릴 파일 목록 ({checked.ok.length})</summary>
          <div className="table-wrap scroll">
            <table className="table compact" aria-label="올릴 파일">
              <thead>
                <tr><th>파일</th><th className="num">크기</th><th className="num">받음</th></tr>
              </thead>
              <tbody>
                {checked.ok.slice(0, listLimit(checked.ok.length)).map((f, i) => {
                  const rec = prog?.received[i] ?? 0;
                  return (
                    <tr key={f.rel}>
                      <td className="mono">{f.rel}</td>
                      <td className="num">{fmtBytes(f.file.size)}</td>
                      <td className="num">{rec >= f.file.size && f.file.size > 0 ? "✓" : rec ? `${Math.floor((rec / f.file.size) * 100)}%` : "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {checked.ok.length > 200 && <p className="small muted">앞 200개만 표시합니다.</p>}
          </div>
        </details>
      )}
      {checked.excluded.length > 0 && (
        <details className="upload-excluded" data-testid="upload-excluded">
          <summary>제외 {checked.excluded.length}개 (펼쳐 보기)</summary>
          <ul className="small">
            {checked.excluded.slice(0, 100).map((x) => (
              <li key={x.rel}>
                <span className="mono">{x.rel}</span> — {x.reason}
              </li>
            ))}
            {checked.excluded.length > 100 && <li>… 외 {checked.excluded.length - 100}개</li>}
          </ul>
        </details>
      )}
    </div>
  );
}
