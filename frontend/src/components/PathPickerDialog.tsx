import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, errorMessage, type FsEntry, type FsList, type FsRoot } from "../api";
import { fmtBytes } from "../lib/format";

/**
 * 서버 폴더 탐색 대화상자(phase3.md §12 S7, D3-46). 경로를 복사·붙여넣기 하지 않고 서버의 허용 루트 안에서 고른다.
 * 상단 루트 버튼 + 경로(breadcrumb), 목록(폴더 더블클릭 진입·"위로"), "선택" → onPick(절대경로).
 * 마지막 위치는 localStorage(try/catch)에 기억한다. 목록·검사는 서버(/fs/list)가 하고 파일 내용은 읽지 않는다.
 */
export type PickMode = "dir" | "file" | "dir_or_file";

export const PICKER_LAST_KEY = "physicsai.pathPicker.last";

const readLast = (): string | null => {
  try {
    return window.localStorage.getItem(PICKER_LAST_KEY);
  } catch {
    return null;
  }
};
const writeLast = (p: string) => {
  try {
    window.localStorage.setItem(PICKER_LAST_KEY, p);
  } catch {
    /* 저장 불가(사생활 보호 모드 등) — 기억만 못 한다 */
  }
};

const sepOf = (p: string) => (p.includes("\\") ? "\\" : "/");
export const joinPath = (dir: string, name: string) => {
  const s = sepOf(dir);
  return dir.endsWith(s) ? dir + name : dir + s + name;
};
const fold = (p: string) => p.replace(/[\\/]+$/, "").toLowerCase().replace(/\//g, "\\");
const under = (p: string, root: string) => fold(p) === fold(root) || fold(p).startsWith(fold(root) + "\\");

/** 현재 경로를 담는 루트 중 가장 깊은 것(받은 파일 폴더는 AI 루트 하위) */
function rootOf(path: string, roots: FsRoot[]): FsRoot | null {
  return roots.filter((r) => under(path, r.path)).sort((a, b) => b.path.length - a.path.length)[0] ?? null;
}

const MODE_TEXT: Record<PickMode, string> = { dir: "폴더", file: "파일", dir_or_file: "파일 또는 폴더" };

export function PathPickerDialog({
  title,
  mode,
  exts,
  aiOnly,
  initialPath,
  onPick,
  onCancel,
}: {
  title?: string;
  mode: PickMode;
  /** 파일 확장자 필터(예 [".rad", ".hm"]). 폴더는 항상 보인다 */
  exts?: string[];
  /** AI 루트 안만 허용하는 용도면 "추가 허용 폴더" 루트를 숨긴다 */
  aiOnly?: boolean;
  /** 입력란의 현재 값. 열 수 있는 폴더면 거기서 시작 */
  initialPath?: string;
  onPick: (path: string) => void;
  onCancel: () => void;
}) {
  const [roots, setRoots] = useState<FsRoot[]>([]);
  const [hint, setHint] = useState<string | null>(null);
  const [list, setList] = useState<FsList | null>(null);
  const [sel, setSel] = useState<FsEntry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const boxRef = useRef<HTMLDivElement>(null);
  const extKey = (exts ?? []).join(",");

  const open = useCallback(
    async (path: string): Promise<boolean> => {
      setBusy(true);
      try {
        const r = await api.fsList(path, exts);
        setList(r);
        setSel(null);
        setError(null);
        return true;
      } catch (e) {
        setError(errorMessage(e));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [extKey],
  );

  useEffect(() => {
    let alive = true;
    const prev = document.activeElement as HTMLElement | null;
    (async () => {
      try {
        const r = await api.fsRoots();
        if (!alive) return;
        const rs = aiOnly ? r.roots.filter((x) => !x.key.startsWith("import_")) : r.roots;
        setRoots(rs);
        setHint(r.inbox_share_hint ?? null);
        const init = initialPath?.trim();
        const tries = [
          init,
          init ? init.replace(/[\\/][^\\/]*$/, "") : undefined, // 파일 경로면 그 폴더
          readLast() ?? undefined,
          rs.find((x) => x.key === "inbox")?.path,
          rs[0]?.path,
        ].filter((x): x is string => !!x && !!rootOf(x, rs));
        for (const p of tries) {
          if (!alive) return;
          if (await open(p)) return;
        }
        setBusy(false);
      } catch (e) {
        if (alive) {
          setError(errorMessage(e));
          setBusy(false);
        }
      }
    })();
    boxRef.current?.focus();
    return () => {
      alive = false;
      prev?.focus?.();
    };
    // 처음 열 때 한 번
  }, []);

  const cur = list?.path ?? null;
  const activeRoot = cur ? rootOf(cur, roots) : null;
  const crumbs: { label: string; path: string }[] = [];
  if (cur && activeRoot) {
    crumbs.push({ label: activeRoot.label, path: activeRoot.path });
    const rest = cur.slice(activeRoot.path.replace(/[\\/]+$/, "").length).split(/[\\/]/).filter(Boolean);
    let p = activeRoot.path;
    for (const name of rest) {
      p = joinPath(p, name);
      crumbs.push({ label: name, path: p });
    }
  }

  const target: string | null = (() => {
    if (!cur) return null;
    if (sel) {
      if (sel.type === "file") return mode === "dir" ? null : joinPath(cur, sel.name);
      return mode === "file" ? null : joinPath(cur, sel.name);
    }
    return mode === "file" ? null : cur;
  })();

  const pick = (p: string | null) => {
    if (!p || !cur) return;
    writeLast(cur);
    onPick(p);
  };

  const activate = (e: FsEntry) => {
    if (!cur) return;
    if (e.type === "dir") void open(joinPath(cur, e.name));
    else if (mode !== "dir") pick(joinPath(cur, e.name));
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onCancel();
      return;
    }
    if (e.key !== "Tab" || !boxRef.current) return;
    const items = Array.from(boxRef.current.querySelectorAll<HTMLElement>("button:not(:disabled)"));
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const titleId = "path-picker-title";
  const filterText = exts && exts.length ? ` · ${exts.join(" ")}만 표시` : "";
  return (
    <div className="dialog-backdrop">
      <div
        className="dialog picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={boxRef}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        data-testid="path-picker"
      >
        <h2 id={titleId} className="dialog-title">
          {title ?? `서버에서 ${MODE_TEXT[mode]} 고르기`}
        </h2>
        <div className="picker-roots" role="group" aria-label="시작 위치">
          {roots.map((r) => (
            <button
              key={r.key}
              type="button"
              className={`btn small${activeRoot?.key === r.key ? " on" : " ghost"}`}
              aria-pressed={activeRoot?.key === r.key}
              title={r.path}
              onClick={() => void open(r.path)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="picker-bar">
          <button type="button" className="btn small ghost" onClick={() => list?.parent && void open(list.parent)} disabled={!list?.parent || busy}>
            ↑ 위로
          </button>
          <nav className="picker-crumbs mono small" aria-label="현재 경로">
            {crumbs.map((c, i) => (
              <span key={c.path}>
                {i > 0 && <span className="muted"> › </span>}
                {i === crumbs.length - 1 ? (
                  <b>{c.label}</b>
                ) : (
                  <button type="button" className="link" onClick={() => void open(c.path)}>
                    {c.label}
                  </button>
                )}
              </span>
            ))}
          </nav>
        </div>
        <div className="picker-list" role="listbox" aria-label="폴더 내용" aria-busy={busy}>
          {list && list.entries.length === 0 && <p className="muted small picker-empty">비어 있습니다{filterText}</p>}
          {list?.entries.map((e) => (
            <button
              key={`${e.type}:${e.name}`}
              type="button"
              role="option"
              aria-selected={sel?.name === e.name && sel.type === e.type}
              className={`picker-row${sel?.name === e.name && sel.type === e.type ? " on" : ""}`}
              onClick={() => setSel(e)}
              onDoubleClick={() => activate(e)}
              onKeyDown={(k) => {
                if (k.key === "Enter") {
                  k.preventDefault();
                  activate(e);
                }
              }}
            >
              <span className="picker-kind" aria-hidden="true">
                {e.type === "dir" ? "▸" : "·"}
              </span>
              <span className="picker-name mono">{e.name}</span>
              <span className="picker-meta muted small">{e.type === "file" ? fmtBytes(e.size ?? 0) : "폴더"}</span>
            </button>
          ))}
        </div>
        {list?.truncated && <p className="muted small">항목이 많아 앞의 500개만 보입니다. 하위 폴더로 들어가 찾으세요.</p>}
        {error && (
          <div className="error-text small" role="alert">
            {error}
          </div>
        )}
        <p className="small picker-target">
          <span className="muted">선택: </span>
          <span className="mono" data-testid="picker-target">
            {target ?? (mode === "file" ? "파일을 고르세요" : "—")}
          </span>
        </p>
        {hint && (
          <p className="muted small" data-testid="picker-share-hint">
            다른 PC에서는 <span className="mono">{hint}</span>에 파일을 복사한 뒤 여기서 고르세요
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>
            취소
          </button>
          <button type="button" className="btn primary" onClick={() => pick(target)} disabled={!target || busy}>
            선택
          </button>
        </div>
      </div>
    </div>
  );
}
