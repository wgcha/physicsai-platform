// 조립 매칭 순수 로직(asm-match.md §3.2·§4.3·§6.3): 표 초안 편집·N:1 차단·추천 채움·검사 결과 문구·오류 코드 한국어. 화면 없이 시험한다.
import type { AsmBody, AsmCheckRow, AsmMatch, AsmMatchState, AsmPart, AsmRowProblem, AsmRowsPut, AsmSuggest } from "../api/typesAsmMatch";

/** 계약 코드표(§6.1·§6.3)의 코드 → 한국어. 서버 문구가 한국어면 그것을 먼저 쓴다(asmCodeText) */
export const ASM_ERROR_TEXT: Record<string, string> = {
  ASM_BOUNDARY_MISMATCH: "외곽 노드가 CAD 경계면과 맞지 않습니다",
  ASM_SHARED_NODES: "다른 PART와 노드를 공유합니다",
  ASM_OFFSET_SUSPECT: "CAD와 조립의 원점이 어긋나 있습니다",
  ASM_UNIT_SUSPECT: "CAD와 조립의 단위가 다른 것으로 보입니다",
  ASM_INCLUDE_OUTSIDE: "조립 폴더 밖 파일을 include하고 있습니다",
  ASM_INCLUDE_MISSING: "include한 파일이 조립 폴더에 없습니다",
  ASM_NO_SOLID_PART: "조립에 TETRA4 PART가 없습니다",
  ASM_TOO_MANY_PARTS: "조립의 PART 수가 상한을 넘었습니다",
  ASM_MATCH_INVALID: "조립 매칭 파일이 올바르지 않거나 조립 내용과 다릅니다 — 다시 매칭하세요",
  ASM_ROW_INVALID: "매칭 표가 올바르지 않습니다",
  ASM_ROWS_INCOMPLETE: "모든 바디를 component에 연결하거나 '매칭 안 함'으로 두세요",
  ASM_CHECK_FAILED_WARN: "경계 검사에서 불합격한 행이 있는 채로 저장했습니다 — 고급 영역의 검사 결과를 확인하세요",
  ASM_CHECK_STALE_WARN: "마지막 경계 검사가 현재 매칭 표와 다릅니다 — 검사 결과는 참고만 하세요",
  ASM_MATCH_CONFIRMED: "이미 저장된 매칭입니다 — 바꾸려면 다시 매칭하세요",
  ASM_MATCH_STALE: "조립 폴더 또는 STEP이 바뀌었습니다 — 목록을 다시 읽고 매칭하세요",
  ASM_MATCH_UNSUPPORTED: "이 구성은 조립 매칭을 지원하지 않습니다(쉘 판금·다중 baseline·STEP 폴더·FEM 검증 재조립)",
  ASM_MATCH_BUSY: "조립 매칭 작업이 진행 중입니다 — 끝난 뒤 다시 시도하세요",
  ASM_FACE_UNCOVERED: "CAD 면 일부에 맞는 노드가 없습니다(판정에는 영향 없음)",
  ASM_DUPLICATE_PART: "다른 행과 같은 위치의 component가 있습니다",
  ASM_FILE_UNUSED: "include되지 않은 파일은 읽지 않았습니다",
  GEOM_UNSUPPORTED_ELEMENT: "TETRA4가 아닌 요소가 있습니다",
  GEOM_INPUT_INVALID: "조립 입력이 올바르지 않습니다(노드 중복 정의·include 순환 등)",
  TEMPLATE_NOT_CONFIGURED: "관리자 설정이 필요합니다(commands.paicad_asm_parts)",
};

const HANGUL = /[가-힣]/;
export function asmCodeText(code: string | null | undefined, message?: string | null): string {
  if (message && HANGUL.test(message)) return message;
  return (code && ASM_ERROR_TEXT[code]) || message || code || "";
}

/** 409 PREREQUISITE_MISSING(missing에 ASM_MATCH): 확정된 조립 매칭이 없다 */
export const ASM_FIRST_TEXT = "조립 매칭을 먼저 하세요";
export const isAsmMissing = (detail: { code?: string; missing?: unknown } | null | undefined): boolean =>
  detail?.code === "PREREQUISITE_MISSING" && Array.isArray(detail.missing) && (detail.missing as unknown[]).includes("ASM_MATCH");

/** 422 ASM_ROW_INVALID problems[].code → 행 옆 안내(AM-C2 10) */
export const ASM_PROBLEM_TEXT: Record<string, string> = {
  USE_PARAM: "선택한 파라미터가 이 바디에 있어 '매칭 안 함'으로 둘 수 없습니다",
  UNKNOWN_BODY: "이 STEP에 없는 바디입니다",
  BODY_DUPLICATE: "이 바디가 두 행(또는 제외)에 있습니다",
  UNKNOWN_PID: "조립에 없는 PART입니다",
  PID_DUPLICATE: "다른 행이 이미 쓰는 component입니다",
  NOT_SOLID: "TETRA4만 가진 component가 아닙니다",
  BODY_MISSING: "component를 고르거나 '매칭 안 함'으로 두세요",
  ROWS_EMPTY: "매칭한 바디가 1개 이상 필요합니다",
};

export interface RowNotes {
  /** 바디 이름 → 그 행 옆 안내 */
  byBody: Record<string, string[]>;
  /** 바디가 없는 사유(ROWS_EMPTY 등) */
  general: string[];
}

/** 422 ASM_ROW_INVALID의 problems[]를 행별 안내로. 모르는 코드는 서버 문구 */
export function rowNotes(problems: AsmRowProblem[] | null | undefined): RowNotes {
  const out: RowNotes = { byBody: {}, general: [] };
  for (const p of problems ?? []) {
    const base = ASM_PROBLEM_TEXT[p.code] ?? p.message ?? p.code;
    const text = p.pid != null && p.code !== "BODY_MISSING" ? `PART ${p.pid}: ${base}` : base;
    if (p.body) (out.byBody[p.body] ??= []).push(text);
    else out.general.push(text);
  }
  return out;
}

export function problemsOf(detail: { code?: string; problems?: unknown } | null | undefined): AsmRowProblem[] {
  return detail?.code === "ASM_ROW_INVALID" && Array.isArray(detail.problems) ? (detail.problems as AsmRowProblem[]) : [];
}

export const STATE_TEXT: Record<AsmMatchState, string> = {
  SCANNING: "목록 읽는 중",
  DRAFT: "초안 — 저장 전",
  CHECKING: "경계 검사 중",
  CHECKED: "검사 통과 — 저장 전",
  CONFIRMED: "저장됨",
  FAILED: "목록 읽기 실패",
  STALE: "입력이 바뀜 — 다시 읽기 필요",
};

/** 상태 알약 문구: 서버 상태 그대로 + DRAFT일 때 최신 검사가 불합격이면 구분(저장은 막지 않는다, AM-C3) */
export function stateLabel(m: Pick<AsmMatch, "state" | "check">): string {
  if (m.state === "DRAFT" && m.check?.current && m.check.status !== "PASS") return "초안 — 경계 검사 불합격(저장은 가능)";
  return STATE_TEXT[m.state];
}

export const CHECK_STALE_TEXT = "경계 검사가 최신이 아님 — 고급 영역에서 다시 검사할 수 있습니다";
export const CHECK_FAIL_TEXT = "경계 검사에서 불합격한 행이 있습니다 — 저장은 막지 않지만 CAD와 조립이 맞는지 고급 영역의 결과를 확인하세요";
/** 고급 [검사] 안내(AM-C3: 시간 제한 없음, 취소 가능) */
export const CHECK_SLOW_TEXT = "오래 걸릴 수 있음(대형 모델은 수십 분) — 진행 중에도 [취소]할 수 있고, 검사는 저장에 필요하지 않습니다.";

export const EXCLUDE_LABEL = "매칭 안 함";

// ---------------------------------------------------------------- 표 초안

/** 편집 중인 표: 바디 → component(PART id) 목록(1:N), 매칭 안 함 바디 */
export interface Draft {
  pids: Record<string, number[]>;
  excluded: string[];
}

export const emptyDraft = (): Draft => ({ pids: {}, excluded: [] });

/** 추천(1:1 초안)으로 채운 표. 이미 쓴 PART는 다시 쓰지 않는다(N:1 금지) */
export function recommendDraft(m: Pick<AsmMatch, "bodies" | "parts" | "recommend">): Draft {
  const ok = new Set(m.parts.filter((p) => p.solid_ok).map((p) => p.pid));
  const used = new Set<number>();
  const pids: Record<string, number[]> = {};
  const bodies = new Set(m.bodies.map((b) => b.body));
  for (const r of m.recommend) {
    if (!bodies.has(r.body)) continue;
    const list = r.pids.filter((p) => ok.has(p) && !used.has(p));
    if (!list.length) continue;
    list.forEach((p) => used.add(p));
    pids[r.body] = list;
  }
  return { pids, excluded: [] };
}

/** 서버 표(저장된 초안)가 있으면 그것, 없으면 추천으로 미리 채운다 */
export function initialDraft(m: AsmMatch): { draft: Draft; fromRecommend: boolean } {
  if (m.rows.length > 0 || m.excluded_bodies.length > 0) {
    const pids: Record<string, number[]> = {};
    m.rows.forEach((r) => (pids[r.body] = [...r.pids]));
    return { draft: { pids, excluded: [...m.excluded_bodies] }, fromRecommend: false };
  }
  const draft = recommendDraft(m);
  return { draft, fromRecommend: Object.keys(draft.pids).length > 0 };
}

/** 그 PART를 이미 쓰는 행(다른 행이면 선택 불가 — N:1 금지) */
export function usedBy(d: Draft, pid: number): string | null {
  for (const [body, list] of Object.entries(d.pids)) if (list.includes(pid)) return body;
  return null;
}

export interface PartChoice {
  disabled: boolean;
  /** 회색 사유(선택 가능이면 null) */
  reason: string | null;
}

/** component 드롭다운 항목(§3.2): TETRA4가 아니면 회색+사유, 다른 행에서 쓰면 회색("X 행에서 사용"), 이 행에서 이미 고른 것도 제외 */
export function partChoice(p: AsmPart, body: string, d: Draft): PartChoice {
  if (!p.solid_ok) {
    const other = Object.entries(p.elems).filter(([k]) => k !== "TETRA4");
    return { disabled: true, reason: `TETRA4가 아님${other.length ? `: /${other[0][0]} ${other[0][1].toLocaleString()}개` : ""}` };
  }
  const by = usedBy(d, p.pid);
  if (by === body) return { disabled: true, reason: "이 행에서 선택함" };
  if (by) return { disabled: true, reason: `${by} 행에서 사용` };
  return { disabled: false, reason: null };
}

/** 행에 PART 추가(N:1이면 막고 그대로 돌려준다) */
export function addPart(d: Draft, body: string, pid: number): Draft {
  if (usedBy(d, pid)) return d;
  return { pids: { ...d.pids, [body]: [...(d.pids[body] ?? []), pid] }, excluded: d.excluded.filter((b) => b !== body) };
}

export function removePart(d: Draft, body: string, pid: number): Draft {
  const list = (d.pids[body] ?? []).filter((p) => p !== pid);
  const pids = { ...d.pids };
  if (list.length) pids[body] = list;
  else delete pids[body];
  return { pids, excluded: d.excluded };
}

/** "매칭 안 함" 토글: 켜면 그 행의 component를 비운다 */
export function setExcluded(d: Draft, body: string, on: boolean): Draft {
  const pids = { ...d.pids };
  if (on) delete pids[body];
  return { pids, excluded: on ? [...new Set([...d.excluded, body])] : d.excluded.filter((b) => b !== body) };
}

/** "매칭 안 함" 불가 사유: 서버가 알려준 `use_bodies`(use=true 파라미터가 있는 바디)이면 선택 불가 */
export function excludeBlock(body: string, useBodies: string[]): string | null {
  return useBodies.includes(body) ? "선택한 파라미터가 있는 바디라 '매칭 안 함'으로 둘 수 없습니다" : null;
}

export interface DraftProblem {
  code: "ASM_ROW_INVALID";
  body: string;
  message: string;
}

/** 저장 전 화면 검증(서버 422 ASM_ROW_INVALID 사유와 같은 것): 모르는 바디·PART, PART 중복(N:1), TETRA4 아님 */
export function draftProblems(m: Pick<AsmMatch, "bodies" | "parts">, d: Draft): DraftProblem[] {
  const out: DraftProblem[] = [];
  const bodies = new Set(m.bodies.map((b) => b.body));
  const parts = new Map(m.parts.map((p) => [p.pid, p]));
  const seen = new Map<number, string>();
  for (const [body, list] of Object.entries(d.pids)) {
    if (!bodies.has(body)) out.push({ code: "ASM_ROW_INVALID", body, message: `${body}: 이 STEP에 없는 바디입니다` });
    for (const pid of list) {
      const p = parts.get(pid);
      if (!p) out.push({ code: "ASM_ROW_INVALID", body, message: `${body}: PART ${pid}은(는) 조립에 없습니다` });
      else if (!p.solid_ok) out.push({ code: "ASM_ROW_INVALID", body, message: `${body}: PART ${pid}은(는) TETRA4가 아닙니다` });
      const prev = seen.get(pid);
      if (prev && prev !== body) out.push({ code: "ASM_ROW_INVALID", body, message: `PART ${pid}이(가) ${prev}·${body} 두 행에 있습니다 — component는 한 행에만 쓸 수 있습니다` });
      seen.set(pid, body);
    }
  }
  return out;
}

/** 미결정 바디(component도 '매칭 안 함'도 아님) */
export function undecidedBodies(m: Pick<AsmMatch, "bodies">, d: Draft): string[] {
  return m.bodies.map((b) => b.body).filter((b) => !(d.pids[b]?.length) && !d.excluded.includes(b));
}

export function toPut(m: Pick<AsmMatch, "bodies">, d: Draft): AsmRowsPut {
  return {
    rows: m.bodies.filter((b) => d.pids[b.body]?.length).map((b) => ({ body: b.body, pids: [...d.pids[b.body]] })),
    excluded_bodies: m.bodies.filter((b) => d.excluded.includes(b.body)).map((b) => b.body),
  };
}

export const putKey = (p: AsmRowsPut): string => JSON.stringify([p.rows.map((r) => [r.body, [...r.pids].sort((a, b) => a - b)]), [...p.excluded_bodies].sort()]);

/** [검사] 사유(가능하면 null): 모든 바디가 선택 또는 매칭 안 함 + 매칭 행 ≥ 1 + 화면 검증 통과 */
export function checkBlock(m: AsmMatch, d: Draft): string | null {
  if (m.state === "CONFIRMED") return "이미 저장된 매칭입니다 — 다시 매칭하세요";
  if (m.state === "SCANNING" || m.state === "CHECKING") return "작업이 진행 중입니다";
  if (m.state === "FAILED" || m.state === "STALE") return "목록을 다시 읽으세요";
  const un = undecidedBodies(m, d);
  if (un.length) return `component를 고르지 않은 바디: ${un.join(", ")}`;
  if (!m.bodies.some((b) => d.pids[b.body]?.length)) return "매칭한 바디가 1개 이상 필요합니다";
  const bad = draftProblems(m, d)[0];
  return bad ? bad.message : null;
}

/** [저장] 사유(가능하면 null): 검사는 필요 없다(AM-C3) — 모든 바디가 선택 또는 매칭 안 함 + 매칭 행 ≥ 1 + 화면 검증 통과 + 작업 중 아님 */
export function saveBlock(m: AsmMatch, d: Draft): string | null {
  if (m.state === "CONFIRMED") return "이미 저장되었습니다";
  return checkBlock(m, d);
}

export interface CheckNotice {
  code: "ASM_CHECK_FAILED_WARN" | "ASM_CHECK_STALE_WARN";
  text: string;
}

/** 저장 전 화면 경고(검사를 실행한 적이 있을 때만): 표가 검사 뒤 바뀌었으면 낡음, 같은데 불합격이면 불합격. 저장은 막지 않는다 */
export function checkNotice(m: Pick<AsmMatch, "check" | "bodies" | "rows" | "excluded_bodies" | "state">, d: Draft): CheckNotice | null {
  if (!m.check || m.state === "SCANNING" || m.state === "CHECKING" || m.state === "CONFIRMED") return null;
  const changed = putKey(toPut(m, d)) !== putKey({ rows: m.rows, excluded_bodies: m.excluded_bodies });
  if (!m.check.current || changed) return { code: "ASM_CHECK_STALE_WARN", text: CHECK_STALE_TEXT };
  return m.check.status !== "PASS" ? { code: "ASM_CHECK_FAILED_WARN", text: CHECK_FAIL_TEXT } : null;
}

// ---------------------------------------------------------------- 표시 문구

/** 부피(mm³ → cm³, 유효 3자리) */
export function fmtVolume(mm3: number | null | undefined): string {
  return mm3 == null ? "–" : `${Number((mm3 / 1000).toPrecision(3)).toLocaleString()} cm³`;
}

/** bbox [xmin,ymin,zmin,xmax,ymax,zmax] → `X×Y×Z mm` */
export function fmtBbox(b: number[] | null | undefined): string {
  if (!b || b.length < 6) return "–";
  const d = [b[3] - b[0], b[4] - b[1], b[5] - b[2]].map((v) => Number(v.toFixed(1)).toLocaleString());
  return `${d.join("×")} mm`;
}

export const fmtMm = (v: number): string => (v >= 1 ? v.toFixed(2) : v.toFixed(3));
/** 일치율: 소수 첫째 자리 내림(100.0%는 전부 일치일 때만) */
export const fmtPct = (r: number): string => `${(Math.floor(r * 1000 + 1e-9) / 10).toFixed(1)}%`;

export function bodySummary(b: AsmBody): string {
  return `${fmtVolume(b.volume)} · ${fmtBbox(b.bbox)}`;
}

export function partLabel(p: AsmPart, recommended: boolean): string {
  return `PART ${p.pid} · ${p.title || `PART:${p.pid}`} · TETRA4 ${(p.elems.TETRA4 ?? 0).toLocaleString()}개${recommended ? " · 추천" : ""}`;
}

/** 원점·단위 진단 한 줄(§3.2, 진행 막음) */
export function suggestText(s: AsmSuggest): string {
  if (s.code === "ASM_OFFSET_SUSPECT") {
    const ax = (["X", "Y", "Z"] as const).map((n, i) => [n, s.translate_mm[i]] as const).filter(([, v]) => Math.abs(v) >= 0.005);
    const at = ax.map(([n, v]) => `${n} ${v.toFixed(1)}`).join(" · ");
    return `CAD가 조립보다 ${at || "원점"} mm 어긋나 있습니다 — CAD를 조립과 같은 원점·mm로 다시 내보내세요(저장 불가)`;
  }
  return `CAD와 조립의 크기가 ×${s.factor} 배 차이입니다(단위 의심) — CAD를 조립과 같은 원점·mm로 다시 내보내세요(저장 불가)`;
}

/** 검사 FAIL 행의 안내 줄들(상태 문구 + 공유 노드 + 원점·단위) */
export function failLines(r: AsmCheckRow): string[] {
  if (r.status === "PASS") return [];
  const out: string[] = [];
  if (r.code === "ASM_SHARED_NODES" || r.shared.nodes > 0) {
    const first = r.shared.parts[0];
    const who = first ? `PART ${first.pid}(${first.title || `PART:${first.pid}`})${r.shared.parts.length > 1 ? " 등" : ""}과 ` : "다른 PART와 ";
    out.push(`${who}노드 ${r.shared.nodes.toLocaleString()}개 공유 — ${ASM_ERROR_TEXT.ASM_SHARED_NODES}`);
  }
  if (r.code === "ASM_BOUNDARY_MISMATCH" || (r.code == null && r.shared.nodes === 0)) {
    const bits = [r.match_ratio != null ? `일치율 ${fmtPct(r.match_ratio)}` : null, r.dist_mm ? `최대 ${fmtMm(r.dist_mm.max)} mm` : null].filter(Boolean);
    out.push(`${ASM_ERROR_TEXT.ASM_BOUNDARY_MISMATCH}${bits.length ? ` — ${bits.join(", ")}` : ""}`);
  } else if (r.code && r.code !== "ASM_SHARED_NODES") out.push(asmCodeText(r.code));
  if (r.suggest) out.push(suggestText(r.suggest));
  return out;
}

/** 거리 열 한 줄(검사 후): `최대 x.xxx · p95 x.xxx mm · 일치율 99.6% (허용 0.05 mm)` */
export function distText(r: AsmCheckRow): string {
  if (!r.dist_mm) return "–";
  const ratio = r.match_ratio != null ? ` · 일치율 ${fmtPct(r.match_ratio)}` : "";
  const tol = r.tol_mm != null ? ` · 허용 ${r.tol_mm} mm` : "";
  return `최대 ${fmtMm(r.dist_mm.max)} · p95 ${fmtMm(r.dist_mm.p95)} mm${ratio}${tol}`;
}

/** 판정 열: 검사 전 — · 행이 바뀌었거나 검사 결과에 없으면 검사 필요 · 일치 · 불일치 */
export function rowVerdict(m: Pick<AsmMatch, "check">, body: string, pids: number[], stale: boolean): "none" | "need" | "pass" | "fail" {
  if (!m.check) return "none";
  const r = m.check.rows.find((x) => x.body === body);
  if (!r) return pids.length ? "need" : "none";
  if (stale || !m.check.current || [...r.pids].sort().join() !== [...pids].sort().join()) return "need";
  return r.status === "PASS" ? "pass" : "fail";
}

/** 3D 색 상한(mm): 허용오차와 최대 거리 중 큰 값 */
export function distScale(r: AsmCheckRow | null): number | null {
  if (!r?.dist_mm) return null;
  return Math.max(r.dist_mm.max, r.tol_mm ?? 0) || null;
}

/** 3D에 찍을 worst 점: 행의 `worst.points`(거리 내림차순). 첫 점 = 최대(글자), 모든 점에 툴팁(node id·거리) */
export function worstPoints(row: Pick<AsmCheckRow, "body" | "worst"> | null | undefined): { xyz: [number, number, number]; label: string; title: string }[] {
  return (row?.worst?.points ?? []).map((p, i) => ({
    xyz: p.xyz,
    label: i === 0 ? `${row!.body} 최대 ${p.dist_mm.toFixed(2)} mm` : "",
    title: `node ${p.node_id} · ${fmtMm(p.dist_mm)} mm`,
  }));
}
