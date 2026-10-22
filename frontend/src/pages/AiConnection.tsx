// mcp.md §23: 상단 바 "AI 연결(MCP)"(features.mcp일 때만) — 한 페이지: ① 상태 ② 토큰(#tokens) ③ AI 도구에 등록하기 ④ 도구 목록(접힘) ⑤ 연결 시험.
// 발급 직후 평문은 이 페이지 컴포넌트 상태(useState)에만 둔다(③ 채움용) — localStorage·sessionStorage·전역 상태·URL·로그에 쓰지 않고, 페이지를 떠나면 사라진다.
import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage, type McpConnection, type McpTools } from "../api";
import { useApp } from "../app/AppContext";
import { Card } from "../components/ui";
import { Grid } from "../design/Grid";
import { ROLE_LABEL } from "../lib/format";
import { MCP_TABS, NODE_NOTE, TOKEN_PLACEHOLDER, buildConfigs, sameOrigin, scopeAllows, toolSummaryKo, type McpTab } from "../lib/mcpSetup";
import { TopBar } from "../shell/TopBar";
import { MyTokensPanel, Off, SCOPE_LABEL, scopeReasons, tokenError, useMcpEnabled, type IssuedToken } from "./ApiTokens";

/** 복사: Clipboard API → (없거나 실패하면) 선택 영역 복사 폴백. 성공했을 때만 true — 실패하면 "복사됨"을 띄우지 않는다 */
export async function copyText(text: string, el?: HTMLElement | null): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 폴백으로 */
  }
  try {
    if (el) {
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
    }
    return typeof document.execCommand === "function" && document.execCommand("copy");
  } catch {
    return false;
  }
}

function CopyBlock({ text, label, testId }: { text: string; label: string; testId: string }) {
  const [copied, setCopied] = useState(false);
  const pre = useRef<HTMLPreElement>(null);
  return (
    <div className="mcp-copy">
      <pre className="mcp-code mono" ref={pre} data-testid={testId}>{text}</pre>
      <button
        type="button"
        className="btn small"
        onClick={async () => {
          if (await copyText(text, pre.current)) {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }
        }}
      >
        {copied ? "복사됨" : `${label} 복사`}
      </button>
    </div>
  );
}

function roleSummary(me: ReturnType<typeof useApp>["me"]): string {
  if (me.is_global_admin) return "전역 관리자";
  const n: Record<string, number> = {};
  for (const r of Object.values(me.roles)) n[r] = (n[r] ?? 0) + 1;
  const parts = (["admin", "power", "general"] as const).filter((r) => n[r]).map((r) => `${ROLE_LABEL[r]} ${n[r]}개`);
  return parts.length ? `프로젝트별 역할: ${parts.join(" · ")}` : "프로젝트 멤버 아님";
}

function StatusCard({ conn, error }: { conn: McpConnection | null; error: string | null }) {
  const { me } = useApp();
  const reasons = scopeReasons(me);
  const scopes = (["read", "run", "admin"] as const).filter((s) => !reasons[s]);
  return (
    <Card span={12} title="① 상태">
      {error && <p className="error-text small" role="alert">{error}</p>}
      <dl className="kv mcp-status" data-testid="mcp-status">
        <dt>MCP</dt>
        <dd>{conn ? <span className={`pill ${conn.enabled ? "ok" : "bad"}`}>{conn.enabled ? "켜짐" : "꺼짐"}</span> : "–"}</dd>
        <dt>HTTP 연결</dt>
        <dd>{conn ? <span className={`pill ${conn.http_enabled ? "ok" : "warn"}`}>{conn.http_enabled ? "켜짐" : "꺼짐"}</span> : "–"}</dd>
        <dt>서버 주소</dt>
        <dd>
          {conn ? (
            <>
              <code className="mono" data-testid="mcp-url">{conn.url}</code>{" "}
              {conn.url_source === "guess" && (
                <span className="pill warn" data-testid="url-guess" title="서버 설정 mcp.public_url이 없어 접속 주소로 짐작한 값입니다">
                  짐작 — 관리자에게 mcp.public_url 설정 요청
                </span>
              )}
            </>
          ) : (
            "–"
          )}
        </dd>
        <dt>내 역할</dt>
        <dd data-testid="mcp-role">{roleSummary(me)}</dd>
        <dt>발급 가능 범위</dt>
        <dd data-testid="mcp-scopes">{scopes.map((s) => SCOPE_LABEL[s]).join(" · ")}</dd>
      </dl>
      {conn && !conn.http_enabled && (
        <p className="warn-text small" data-testid="http-off">
          HTTP 연결이 꺼져 있어 stdio(physicsai-mcp) 방식만 쓸 수 있습니다.{me.is_global_admin ? " 켜려면 설정 mcp.server.http_enabled: true 후 백엔드를 재시작하세요." : " 필요하면 관리자에게 요청하세요."}
        </p>
      )}
    </Card>
  );
}

function RegisterCard({ conn, token }: { conn: McpConnection | null; token: string | null }) {
  const [tab, setTab] = useState<McpTab>("claudeCode");
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const url = conn?.url ?? `${origin}/physicsai/mcp`;
  const api_ = conn?.api_base ?? `${origin}/physicsai`;
  const cfg = useMemo(() => buildConfigs({ url, api: api_, token }), [url, api_, token]);
  const meta = MCP_TABS.find((t) => t.key === tab)!;
  const main = cfg[tab];
  const filled = !!token;
  return (
    <Card span={12} title="③ AI 도구에 등록하기" aside={<span className="muted small">완성된 설정을 복사해 붙여 넣습니다{filled ? " — 방금 발급한 토큰이 채워져 있습니다" : ` — 토큰 자리는 ${TOKEN_PLACEHOLDER}(발급하면 채워짐)`}</span>}>
      <div className="tabs" role="tablist" aria-label="AI 도구">
        {MCP_TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <div key={tab} role="tabpanel" aria-label={meta.label} className="mcp-pane" data-testid={`mcp-pane-${tab}`}>
        <p className="small">{meta.where}</p>
        <CopyBlock text={main} label={meta.label} testId={`cfg-${tab}`} />
        <p className="warn-text small" data-testid="plain-warning">
          이 설정을 저장하면 토큰이 설정 파일에 평문으로 남습니다 — 공유 PC·저장소에 올리지 마세요. 유출되면 바로 폐기하세요.
        </p>
        <p className="muted small" data-testid="node-note">{NODE_NOTE}</p>
        <details className="advanced" data-testid="alt-details">
          <summary>대안 — Node.js를 쓸 수 없는 PC(physicsai-mcp 실행기·토큰 파일 방식, 설정 파일에 토큰을 남기지 않음)</summary>
          <div className="advanced-body">
            <p className="small" data-testid="stdio-hint">
              <code>physicsai-mcp</code> 실행기가 필요합니다.
              {conn?.stdio_hint?.command_path ? <> 서버 PC: <code className="mono">{conn.stdio_hint.command_path}</code>.</> : null}{" "}
              {conn?.stdio_hint?.install ?? "Node.js를 쓸 수 없는 PC: 관리자에게 오프라인 묶음 wheels를 받아 설치하세요."} 설정의 <code>command</code>에는 전체 경로를 써도 됩니다.
            </p>
            <p className="small">토큰을 한 줄 파일(<code>{"<토큰 파일 경로>"}</code>)에 저장하고 설정에는 경로만 둡니다.</p>
            {tab === "claudeCode" && (
              <>
                <p className="muted small">HTTP — 프로젝트 <code>.mcp.json</code>(환경변수 <code>PHYSICSAI_MCP_TOKEN</code>에 토큰)</p>
                <CopyBlock text={cfg.alt.claudeCodeJson} label=".mcp.json" testId="alt-claudeCode-json" />
                <p className="muted small">stdio</p>
                <CopyBlock text={cfg.alt.claudeCodeStdio} label="stdio 명령" testId="alt-claudeCode-stdio" />
              </>
            )}
            {tab === "desktop" && (
              <>
                <p className="muted small">stdio(브리지 항목과 서버 이름이 같으므로 둘 중 하나만 둡니다)</p>
                <CopyBlock text={cfg.alt.desktop} label="항목" testId="alt-desktop" />
              </>
            )}
            {tab === "codex" && <CopyBlock text={cfg.alt.codex} label="TOML" testId="alt-codex" />}
            {tab === "gemini" && (
              <>
                <p className="muted small">stdio(브리지 항목과 서버 이름이 같으므로 둘 중 하나만 둡니다)</p>
                <CopyBlock text={cfg.alt.gemini} label="항목" testId="alt-gemini" />
              </>
            )}
          </div>
        </details>
      </div>
    </Card>
  );
}

function ToolsCard({ scopeDefault }: { scopeDefault: "read" | "run" | "admin" }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<McpTools | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState<"read" | "run" | "admin">(scopeDefault);
  useEffect(() => setScope(scopeDefault), [scopeDefault]);
  useEffect(() => {
    if (open && !data) api.mcpTools().then(setData).catch((e) => setError(tokenError(e)));
  }, [open, data]);
  const visible = data ? new Set(data.visible ?? data.tools.map((t) => t.name)) : null;
  const rows = data?.tools.filter((t) => (!visible || visible.has(t.name)) && scopeAllows(scope, t.annotations?.["x-risk"])) ?? [];
  return (
    <Card span={6} title="④ 사용 가능한 도구">
      <details className="advanced" data-testid="tools-details" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
        <summary>도구 목록 보기{data ? ` (${rows.length}개)` : ""}</summary>
        <div className="advanced-body">
          <label className="inline-field small">
            토큰 범위 기준
            <select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)} aria-label="도구 범위 기준">
              {(["read", "run", "admin"] as const).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          {error && <p className="error-text small" role="alert">{error}</p>}
          {!data && !error && <p className="muted small">불러오는 중…</p>}
          <ul className="plain mcp-tools" data-testid="tools-list">
            {rows.map((t) => (
              <li key={t.name}>
                <code className="mono">{t.name}</code> <span className="muted small">{toolSummaryKo(t.description)}</span>
              </li>
            ))}
          </ul>
          <p className="muted small">표시용 구분입니다 — 실제 권한은 서버가 토큰 범위로 판정합니다.</p>
        </div>
      </details>
    </Card>
  );
}

type TestResult = { tone: "ok" | "bad" | "warn"; text: string };

function TestCard({ conn, token }: { conn: McpConnection | null; token: string | null }) {
  const { me } = useApp();
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<TestResult[]>([]);
  const run = async () => {
    setBusy(true);
    const out: TestResult[] = [];
    try {
      const [c, p] = await Promise.all([api.mcpConnection(), api.mcpPing()]);
      out.push({ tone: "ok", text: `서버 정상 — ${me.display_name}(${roleSummary(me)}) · 서버 ${p.server_version} · 도구 ${p.tools_count}개 · HTTP ${c.http_enabled ? "켜짐" : "꺼짐"}` });
      const url = c.url;
      if (token && sameOrigin(url, window.location.origin)) {
        try {
          const res = await fetch(url, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
            body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "physicsai-web-test", version: "1" } } }),
          });
          if (res.ok) out.push({ tone: "ok", text: "토큰으로 MCP 연결 정상" });
          else if (res.status === 401) out.push({ tone: "bad", text: "토큰 문제(401) — 만료·폐기됐거나 잘못된 토큰입니다. 새로 발급하세요" });
          else if (res.status === 404) out.push({ tone: "bad", text: "MCP가 꺼져 있습니다(404)" });
          else out.push({ tone: "warn", text: `MCP 응답 ${res.status}` });
        } catch {
          out.push({ tone: "warn", text: "토큰 시험을 보내지 못했습니다(네트워크)" });
        }
      } else {
        out.push({ tone: "warn", text: "토큰으로 하는 시험은 방금 발급한 토큰이 이 화면에 있고 서버 주소가 같은 곳일 때만 됩니다 — AI 도구에서 ping 도구를 불러 확인하세요" });
      }
    } catch (e) {
      out.push({ tone: "bad", text: `서버 확인 실패 — ${e instanceof Error ? tokenError(e) : errorMessage(e)}` });
    } finally {
      setLines(out);
      setBusy(false);
    }
  };
  return (
    <Card span={6} title="⑤ 연결 시험">
      <div className="run-action-row">
        <button type="button" className="btn primary" disabled={busy || !conn} onClick={() => void run()}>
          {busy ? "확인 중…" : "연결 시험"}
        </button>
        <span className="muted small">서버 상태와, 방금 발급한 토큰이 있으면 그 토큰으로 MCP 연결을 한 번 확인합니다.</span>
      </div>
      <ul className="plain mcp-test" data-testid="test-result" aria-live="polite">
        {lines.map((l, i) => (
          <li key={i} className={l.tone === "ok" ? "" : l.tone === "bad" ? "error-text" : "warn-text"}>
            <span className={`pill ${l.tone}`}>{l.tone === "ok" ? "정상" : l.tone === "bad" ? "실패" : "안내"}</span> <span className="small">{l.text}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** "AI 연결(MCP)" 페이지(/me/ai-connection) */
export function AiConnection() {
  const enabled = useMcpEnabled();
  const [conn, setConn] = useState<McpConnection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedToken | null>(null);
  useEffect(() => {
    if (enabled) api.mcpConnection().then(setConn).catch((e) => setError(tokenError(e)));
  }, [enabled]);
  useEffect(() => {
    if (enabled && window.location.hash === "#tokens") document.getElementById("tokens")?.scrollIntoView?.();
  }, [enabled]);
  return (
    <div className="page">
      <TopBar crumbs={[{ label: "AI 연결(MCP)" }]} />
      <main className="page-main token-page" aria-label="AI 연결(MCP)">
        <h1 className="T">AI 연결(MCP)</h1>
        {!enabled ? (
          <Off />
        ) : (
          <Grid>
            <>
              <StatusCard conn={conn} error={error} />
              <MyTokensPanel onIssued={setIssued} />
              <RegisterCard conn={conn} token={issued?.token ?? null} />
              <ToolsCard scopeDefault={issued?.scope ?? "read"} />
              <TestCard conn={conn} token={issued?.token ?? null} />
            </>
          </Grid>
        )}
      </main>
    </div>
  );
}
