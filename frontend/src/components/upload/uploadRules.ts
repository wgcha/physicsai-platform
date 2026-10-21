// 업로드 미리 검사(upload-report.md §3.1·§5): 네트워크 전에 패턴 제외·이름 규칙 위반을 걸러 보여 준다. 서버 규칙과 같은 표(physicsai_core/path_names.py·uploads.py).
// 위반이 1개라도 있으면 올리기 비활성 — 자동 이름 바꾸기는 하지 않는다(파일 안 참조가 깨짐).
import type { UploadConfig } from "../../api/uploads";

export type PurposeMode = "file" | "dir" | "dir_or_file";

/** 항상 거부(설정으로 풀 수 없음, 서버 응답 always_denied 가 없을 때의 기본) */
export const DEFAULT_DENIED = ["*.pscfg", "*.psdata", "*.exe", "*.dll", "*.pyd", "*.so", "*.bat", "*.cmd", "*.ps1", "*.vbs", "*.js", "*.py", "*.lnk", "*.scr", "*.msi", "*.part"];
const META = new Set(['&', '|', '<', '>', '^', '%', '!', '"', ";", ",", "=", "(", ")", "'"]);
const FS_FORBIDDEN = new Set(["*", "?", "\\"]);
const RESERVED = /^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$/i;
const MAX_SEG = 255;
const MAX_REL = 400;

const globRe = (g: string) => new RegExp("^" + g.toLowerCase().replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$");
export const matchesAny = (name: string, patterns: string[]): boolean => {
  const low = name.toLowerCase();
  return patterns.some((p) => globRe(p).test(low));
};

/** 이름 1개(성분)의 쓸 수 없는 문자·형식 설명. 문제 없으면 null */
export function nameProblem(seg: string): string | null {
  const bad = new Set<string>();
  for (const c of seg) {
    const code = c.codePointAt(0)!;
    if (/\s/u.test(c) || /\p{Z}/u.test(c)) bad.add("공백");
    else if (code < 0x20 || code === 0x7f || /\p{C}/u.test(c)) bad.add("제어문자");
    else if (META.has(c) || FS_FORBIDDEN.has(c)) bad.add(c);
  }
  if (bad.size) {
    const words = [...bad].filter((x) => x.length > 1).sort();
    const chars = [...bad].filter((x) => x.length === 1).sort();
    return `쓸 수 없는 문자(${[...words, ...chars].join(" ")})`;
  }
  if (seg === "." || seg === "..") return "'.'·'..' 이름";
  if (seg.length > MAX_SEG) return `이름이 너무 깁니다(${MAX_SEG}자 이하)`;
  if (seg.includes(":")) return "':' 문자";
  if (/[. ]$/.test(seg)) return "끝 마침표·공백";
  if (RESERVED.test(seg)) return "Windows 예약 이름";
  return null;
}

/** rel(선택 폴더 기준 상대경로) 전체 검사: 성분마다 이름 규칙 + 길이 + 첫 성분 */
export function relProblem(rel: string): string | null {
  if (!rel || rel.length > MAX_REL) return `경로가 비었거나 ${MAX_REL}자를 넘습니다`;
  const segs = rel.split("/");
  for (const s of segs) {
    const p = nameProblem(s);
    if (p) return `${p}${segs.length > 1 && s !== segs[segs.length - 1] ? " — 폴더 이름" : ""}`;
  }
  const first = segs[0].toLowerCase();
  if (first === "_backup" || first === "_platform" || first.startsWith(".")) return "_backup·_platform·'.' 으로 시작할 수 없습니다";
  return null;
}

export interface PickedItem {
  file: File;
  /** 선택 폴더 기준 상대경로(폴더 선택이 아니면 파일 이름) */
  rel: string;
}

export interface Checked {
  /** 올릴 파일(패턴 통과·이름 규칙 통과) */
  ok: PickedItem[];
  /** 패턴·항상 거부로 제외(올리지 않음 — 위반 아님) */
  excluded: { rel: string; reason: string }[];
  /** 이름 규칙 위반 — 1개라도 있으면 올릴 수 없다 */
  bad: { rel: string; reason: string }[];
  /** 모양 오류(CAD 는 파일 1개 등) */
  shape: string | null;
  bytes: number;
}

/** purpose 의 허용 패턴: CAD_FILE 은 engine 별 */
export function patternsFor(cfg: UploadConfig, purpose: string, engine?: string | null): string[] {
  const info = cfg.purposes[purpose];
  if (!info) return [];
  const ep = info.engine_patterns;
  if (ep && engine && ep[engine]) return ep[engine];
  return info.patterns;
}

export const modeOf = (cfg: UploadConfig, purpose: string): PurposeMode => (cfg.purposes[purpose]?.mode ?? "dir") as PurposeMode;

export function precheck(items: PickedItem[], cfg: UploadConfig, purpose: string, engine?: string | null): Checked {
  const patterns = patternsFor(cfg, purpose, engine);
  const denied = cfg.always_denied?.length ? cfg.always_denied : DEFAULT_DENIED;
  const mode = modeOf(cfg, purpose);
  const out: Checked = { ok: [], excluded: [], bad: [], shape: null, bytes: 0 };
  for (const it of items) {
    const name = it.rel.slice(it.rel.lastIndexOf("/") + 1);
    if (matchesAny(name, denied)) {
      out.excluded.push({ rel: it.rel, reason: /\.pscfg$/i.test(name) ? "pscfg(pickle)는 올릴 수 없습니다" : "올릴 수 없는 종류(항상 거부)" });
      continue;
    }
    if (!matchesAny(name, patterns)) {
      out.excluded.push({ rel: it.rel, reason: "이 용도에서 쓰지 않는 파일" });
      continue;
    }
    const why = relProblem(it.rel);
    if (why) {
      out.bad.push({ rel: it.rel, reason: why });
      continue;
    }
    out.ok.push(it);
  }
  const seen = new Map<string, string>();
  out.ok = out.ok.filter((it) => {
    const k = it.rel.toLowerCase();
    if (!seen.has(k)) return seen.set(k, it.rel), true;
    out.bad.push({ rel: it.rel, reason: `대소문자만 다른 같은 이름(${seen.get(k)})` });
    return false;
  });
  if (mode === "file" && out.ok.length > 0 && (out.ok.length !== 1 || out.ok[0].rel.includes("/"))) out.shape = "이 용도는 파일 1개만 올릴 수 있습니다";
  if (!out.ok.length) out.shape = out.shape ?? (items.length ? "올릴 수 있는 파일이 없습니다" : null);
  out.bytes = out.ok.reduce((s, x) => s + x.file.size, 0);
  return out;
}

/** 폴더 선택(webkitRelativePath)이면 선택 폴더 이름을 떼고, 아니면 파일 이름만 */
export function relFromFile(file: File, path?: string): string {
  const p = (path ?? (file as File & { webkitRelativePath?: string }).webkitRelativePath ?? "").replace(/\\/g, "/");
  return p.includes("/") ? p.split("/").slice(1).join("/") || file.name : file.name;
}

/** 폴더 선택의 폴더 이름(없으면 null) */
export function rootName(file: File, path?: string): string | null {
  const p = (path ?? (file as File & { webkitRelativePath?: string }).webkitRelativePath ?? "").replace(/\\/g, "/");
  return p.includes("/") ? p.split("/")[0] : null;
}

/** 세션 이름(서버 폴더 이름 일부): 영문·숫자·_·-·한글만, 60자 */
export function sessionName(root: string | null, firstFile: string | undefined): string {
  const base = (root ?? (firstFile ?? "upload").replace(/\.[^.]*$/, "")).replace(/[^A-Za-z0-9_\-가-힣]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
  return base || "upload";
}
