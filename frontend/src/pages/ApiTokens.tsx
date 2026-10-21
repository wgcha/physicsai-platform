// mcp.md §4.5: "내 API 토큰"(사용자 메뉴, /status features.mcp가 true일 때만) + 관리자 "API 토큰 관리". 평문 토큰은 발급 직후 한 번만
// 화면 상태(useState)에 두고 닫으면 지운다 — localStorage·전역 상태·로그에 남기지 않는다.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, errorMessage, type ApiToken, type ApiTokenAdmin, type ApiTokenScope } from "../api";
import { useApp } from "../app/AppContext";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Card, Field } from "../components/ui";
import { Grid } from "../design/Grid";
import { fmtTime } from "../lib/format";
import { TopBar } from "../shell/TopBar";

export const MAX_EXPIRY_DAYS = 30;
export const SCOPE_LABEL: Record<ApiTokenScope, string> = { read: "read (조회)", run: "run (작업 실행)", admin: "admin (관리)" };
export const TOKEN_STATUS_LABEL: Record<ApiToken["status"], string> = { active: "유효", expired: "만료", revoked: "폐기", stale: "권한 변경됨" };
const STATUS_TONE: Record<ApiToken["status"], string> = { active: "ok", expired: "", revoked: "bad", stale: "warn" };
const TOKEN_ERROR_TEXT: Record<string, string> = {
  API_TOKEN_LIMIT: "유효한 토큰 수가 한도에 도달했습니다 — 쓰지 않는 토큰을 폐기하세요",
  API_TOKEN_NAME_EXISTS: "같은 이름의 토큰이 이미 있습니다",
  API_TOKEN_SCOPE: "이 범위의 토큰을 발급할 권한이 없습니다",
  API_TOKEN_EXPIRY_TOO_LONG: `토큰 만료는 최대 ${MAX_EXPIRY_DAYS}일입니다 — 만료 전에 새 토큰을 발급해 교체하세요`,
  MCP_DISABLED: "MCP 기능이 꺼져 있습니다(관리자 설정 mcp.enabled)",
};
/** 서버 문구(한국어)가 있으면 그대로, 없으면 코드 표 */
export function tokenError(e: unknown): string {
  if (e instanceof ApiError) return /[가-힣]/.test(e.message) && !e.message.startsWith("요청 실패") ? e.message : TOKEN_ERROR_TEXT[e.code] ?? e.message;
  return errorMessage(e);
}
const NAME_RE = /^[0-9A-Za-z가-힣 _.-]{1,64}$/;

/** 사용자 메뉴·페이지 노출 조건: /status features.mcp.enabled === true(없으면 숨김) */
export function useMcpEnabled(): boolean {
  const { status } = useApp();
  return status?.features?.mcp?.enabled === true;
}

const dayLeft = (iso: string) => Math.ceil((Date.parse(iso) - Date.now()) / 86400000);
function expiryText(t: Pick<ApiToken, "expires_at" | "status">): string {
  const left = dayLeft(t.expires_at);
  return `${fmtTime(t.expires_at).split(" ")[0]}${t.status === "active" ? ` (${left}일 남음)` : ""}`;
}

function StatusPill({ s }: { s: ApiToken["status"] }) {
  return (
    <span className={`pill ${STATUS_TONE[s]}`} data-testid="token-status" title={s === "stale" ? "발급 때의 권한이 바뀌었습니다 — 새 토큰을 발급하세요" : undefined}>
      {TOKEN_STATUS_LABEL[s]}
    </span>
  );
}

/** 발급 직후 평문 1회 표시 — 닫으면 부모가 상태를 지운다 */
function TokenOnce({ token, name, onClose }: { token: string; name: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
    } catch {
      /* 복사 실패 — 직접 선택해서 복사 */
    }
  };
  return (
    <div className="token-once" role="alertdialog" aria-label="발급된 토큰" data-testid="token-once">
      <p>
        <b>{name}</b> 토큰이 발급되었습니다. 지금 복사해 토큰 파일이나 환경변수에 저장하세요.
      </p>
      <div className="token-once-row">
        <code className="token-value mono" data-testid="token-plain">{token}</code>
        <button type="button" className="btn small" onClick={() => void copy()}>
          {copied ? "복사됨" : "복사"}
        </button>
      </div>
      <p className="error-text small" role="alert">이 창을 닫으면 다시 볼 수 없습니다 — 잃어버리면 폐기하고 새로 발급하세요.</p>
      <button type="button" className="btn small primary" onClick={onClose}>
        닫기(다시 볼 수 없음)
      </button>
    </div>
  );
}

function IssueForm({ onIssued }: { onIssued: (r: { token: string; name: string }) => void }) {
  const { me } = useApp();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<ApiTokenScope>("read");
  const [days, setDays] = useState(String(MAX_EXPIRY_DAYS));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const power = me.is_global_admin || Object.values(me.roles).some((r) => r === "power" || r === "admin");
  const reason: Record<ApiTokenScope, string | null> = {
    read: null,
    run: power ? null : "어느 프로젝트든 power 이상 권한이 있어야 합니다",
    admin: me.is_global_admin ? null : "전역 관리자만 발급할 수 있습니다",
  };
  const d = Number(days);
  const daysOk = Number.isInteger(d) && d >= 1 && d <= MAX_EXPIRY_DAYS;
  const nameOk = NAME_RE.test(name.trim());
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.createApiToken({ name: name.trim(), scope, expires_in_days: d });
      onIssued({ token: r.token, name: r.api_token.name });
      setName("");
    } catch (e) {
      setError(tokenError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="token-form" data-testid="token-form">
      <Field label="이름" hint="1~64자: 영숫자·한글·공백·_.-">
        <input value={name} onChange={(e) => setName(e.target.value)} aria-label="토큰 이름" maxLength={64} placeholder="예: codex-내PC" />
      </Field>
      <div className="field">
        <span className="field-label">범위</span>
        <div role="radiogroup" aria-label="토큰 범위" className="token-scopes">
          {(["read", "run", "admin"] as const).map((s) => (
            <label key={s} className={`check${reason[s] ? " disabled" : ""}`} title={reason[s] ?? undefined}>
              <input type="radio" name="token-scope" checked={scope === s} disabled={!!reason[s]} onChange={() => setScope(s)} /> {SCOPE_LABEL[s]}
              {reason[s] && <span className="muted small" data-testid={`scope-reason-${s}`}> — {reason[s]}</span>}
            </label>
          ))}
        </div>
      </div>
      <Field label={`만료(일, 최대 ${MAX_EXPIRY_DAYS})`}>
        <input className="num-input" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.replace(/[^0-9]/g, ""))} aria-label="만료일 수" aria-invalid={!daysOk} />
      </Field>
      <div className="run-action-row">
        <button type="button" className="btn primary" disabled={busy || !nameOk || !daysOk} onClick={() => void submit()}>
          {busy ? "발급 중…" : "발급"}
        </button>
        {error && <span className="error-text small" role="alert">{error}</span>}
      </div>
    </div>
  );
}

function TokenGuide() {
  const url = `${window.location.origin}/physicsai/mcp`;
  return (
    <details className="advanced" data-testid="token-guide">
      <summary>연결 안내(Claude Code · Codex · Gemini)</summary>
      <div className="advanced-body small">
        <p>
          서버 URL: <code className="mono" data-testid="mcp-url">{url}</code> — 인증은 <code>Authorization: Bearer 토큰</code>. 토큰은 설정 파일에 쓰지 말고 환경변수 <code>PHYSICSAI_MCP_TOKEN</code>(또는 토큰 파일)에 두세요.
        </p>
        <ul className="plain">
          <li>
            <b>Claude Code</b>: <code>claude mcp add --transport http physicsai {url} --header 'Authorization: Bearer ${"{PHYSICSAI_MCP_TOKEN}"}'</code>
          </li>
          <li>
            <b>Codex CLI</b>(<code>~/.codex/config.toml</code>): <code>[mcp_servers.physicsai]</code> · <code>url = "{url}"</code> · <code>bearer_token_env_var = "PHYSICSAI_MCP_TOKEN"</code>
          </li>
          <li>
            <b>Gemini CLI</b>(<code>settings.json</code>): <code>"physicsai": {"{"} "httpUrl": "{url}", "headers": {"{"} "Authorization": "Bearer $PHYSICSAI_MCP_TOKEN" {"}"} {"}"}</code>
          </li>
        </ul>
        <p className="muted">자세한 설정·stdio 방식·문제 해결은 가이드 docs/manual/mcp-clients.md를 보세요. 만료 전에 새 토큰을 발급해 교체하고, 유출이 의심되면 바로 폐기하세요.</p>
      </div>
    </details>
  );
}

type Row = ApiToken & { username?: string };

function TokenTable({ rows, admin, onRevoke }: { rows: Row[]; admin?: boolean; onRevoke: (t: Row) => void }) {
  return (
    <div className="table-wrap">
      <table className="table compact" aria-label={admin ? "API 토큰 관리" : "내 API 토큰"}>
        <thead>
          <tr>
            {admin && <th>사용자</th>}
            <th>이름</th>
            <th>범위</th>
            <th>접두</th>
            <th>만료</th>
            <th>마지막 사용</th>
            <th>상태</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id} data-testid={`token-${t.id}`} className={t.status === "active" ? "" : "unused"}>
              {admin && <td className="mono small">{t.username}</td>}
              <td>{t.name}</td>
              <td className="mono small">{t.scope}</td>
              <td className="mono small">{t.token_prefix}</td>
              <td className="small">{expiryText(t)}</td>
              <td className="small">{t.last_used_at ? fmtTime(t.last_used_at) : "–"}</td>
              <td><StatusPill s={t.status} /></td>
              <td>
                {t.status !== "revoked" && (
                  <button type="button" className="btn small ghost danger" onClick={() => onRevoke(t)}>
                    폐기
                  </button>
                )}
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={admin ? 8 : 7} className="muted small">토큰이 없습니다</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Off() {
  return <div className="empty" role="alert" data-testid="mcp-off">MCP 기능이 꺼져 있습니다 — 관리자가 mcp.enabled를 켜면 API 토큰을 쓸 수 있습니다</div>;
}

/** 사용자 메뉴 "내 API 토큰" */
export function MyApiTokens() {
  const enabled = useMcpEnabled();
  const [rows, setRows] = useState<ApiToken[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<{ token: string; name: string } | null>(null);
  const [asking, setAsking] = useState<ApiToken | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const load = useCallback(() => api.myApiTokens().then(setRows).catch((e) => setError(tokenError(e))), []);
  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);
  return (
    <div className="page">
      <TopBar crumbs={[{ label: "내 API 토큰" }]} />
      <main className="page-main token-page" aria-label="내 API 토큰">
        <h1 className="T">내 API 토큰</h1>
        {!enabled ? (
          <Off />
        ) : (
          <Grid>
            <>
              <Card span={12} title="토큰" aside={<span className="muted small">LLM 클라이언트(MCP)가 내 권한으로 PhysicsAI를 부를 때 쓰는 열쇠 — 최대 {MAX_EXPIRY_DAYS}일</span>}>
                {issued && <TokenOnce token={issued.token} name={issued.name} onClose={() => setIssued(null)} />}
                {error && <p className="error-text small" role="alert">{error}</p>}
                {rows && <TokenTable rows={rows} onRevoke={(t) => (setRevokeError(null), setAsking(t))} />}
                <TokenGuide />
              </Card>
              <Card span={12} title="발급">
                <IssueForm onIssued={(r) => (setIssued(r), void load())} />
              </Card>
            </>
          </Grid>
        )}
        {asking && (
          <ConfirmDialog
            title="토큰 폐기"
            body={`'${asking.name}'(${asking.token_prefix}) 토큰을 폐기합니다.\n이 토큰을 쓰는 클라이언트는 즉시 연결이 끊기고, 되돌릴 수 없습니다.`}
            confirmLabel="폐기"
            danger
            error={revokeError}
            onCancel={() => setAsking(null)}
            onConfirm={async () => {
              try {
                await api.revokeMyApiToken(asking.id);
                setAsking(null);
                await load();
              } catch (e) {
                setRevokeError(tokenError(e));
                throw e;
              }
            }}
          />
        )}
      </main>
    </div>
  );
}

/** 전역 관리자 "API 토큰 관리": user_id·유효 여부 필터 + 폐기 */
export function AdminApiTokens() {
  const { me } = useApp();
  const enabled = useMcpEnabled();
  const [uid, setUid] = useState("");
  const [active, setActive] = useState<"" | "true" | "false">("");
  const [rows, setRows] = useState<ApiTokenAdmin[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState<ApiTokenAdmin | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const load = useCallback(
    () => api.adminApiTokens({ user_id: uid.trim() || null, active: active === "" ? null : active === "true" }).then((r) => (setRows(r), setError(null))).catch((e) => setError(tokenError(e))),
    [uid, active],
  );
  useEffect(() => {
    if (enabled && me.is_global_admin) void load();
  }, [enabled, me.is_global_admin, load]);
  return (
    <div className="page">
      <TopBar crumbs={[{ label: "관리" }, { label: "API 토큰 관리" }]} />
      <main className="page-main token-page" aria-label="API 토큰 관리">
        <h1 className="T">API 토큰 관리</h1>
        {!me.is_global_admin ? (
          <div className="empty" role="alert">관리자 전용입니다</div>
        ) : !enabled ? (
          <Off />
        ) : (
          <Card span={12} title="전체 토큰" aside={<span className="muted small">폐기하면 즉시 차단됩니다(토큰 값은 볼 수 없음)</span>}>
            <div className="run-action-row">
              <label className="inline-field">
                user_id
                <input value={uid} onChange={(e) => setUid(e.target.value)} aria-label="사용자 id 필터" placeholder="전체" />
              </label>
              <label className="inline-field">
                상태
                <select value={active} onChange={(e) => setActive(e.target.value as "" | "true" | "false")} aria-label="유효 필터">
                  <option value="">전체</option>
                  <option value="true">유효만</option>
                  <option value="false">유효 아님</option>
                </select>
              </label>
            </div>
            {error && <p className="error-text small" role="alert">{error}</p>}
            {rows && <TokenTable rows={rows} admin onRevoke={(t) => (setRevokeError(null), setAsking(rows.find((x) => x.id === t.id) ?? null))} />}
          </Card>
        )}
        {asking && (
          <ConfirmDialog
            title="토큰 폐기(관리자)"
            body={`${asking.username}의 '${asking.name}'(${asking.token_prefix}) 토큰을 폐기합니다.\n즉시 차단되며 되돌릴 수 없습니다.`}
            confirmLabel="폐기"
            danger
            error={revokeError}
            onCancel={() => setAsking(null)}
            onConfirm={async () => {
              try {
                await api.adminRevokeApiToken(asking.id);
                setAsking(null);
                await load();
              } catch (e) {
                setRevokeError(tokenError(e));
                throw e;
              }
            }}
          />
        )}
      </main>
    </div>
  );
}
