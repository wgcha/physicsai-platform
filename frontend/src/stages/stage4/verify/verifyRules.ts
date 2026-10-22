// ④ FEM 검증 공용 규칙(phase3 §21.3.11): 출처 ↔ 주소 질의, 상태 문구, 진행 4단, 응답 표 행 계산. 화면 로직 없는 순수 함수.
import type { FemCompare, FemResponseRow, FemSourceReq, FemVerifySummary, FvStatus } from "../../../api/femVerify";
import type { Job, JobStep } from "../../../api/types";
import { fmtNum } from "../../../lib/format";

export const FEM_DISABLED_TEXT = "해석 연결 안 됨(관리자 설정 필요)";
export const FEM_BUTTON_LABEL = "FEM 검증";
export const ZERO_TOL = 1e-12;

export const FV_STATUS_LABEL: Record<FvStatus, string> = {
  WAITING_PREDICT: "예측 실행 중",
  RUNNING: "실행 중",
  DONE: "완료",
  FAILED: "실패",
  CANCELED: "취소됨",
};
export const fvTone = (s: FvStatus): string => (s === "DONE" ? "ok" : s === "FAILED" ? "bad" : s === "RUNNING" || s === "WAITING_PREDICT" ? "run" : "");

/** 오차 문구 "7.2%"(부호 없음 — 절댓값) */
export const pctText = (v: number | null | undefined): string => (v == null || !Number.isFinite(v) ? "–" : `${Math.abs(v).toFixed(1)}%`);

/** "FV-003 · 완료 · 최대 오차 7.2%"(진행 중·실패는 오차 없음) */
export function fvLinkText(f: Pick<FemVerifySummary, "label" | "status" | "max_abs_diff_pct">): string {
  const parts = [f.label, FV_STATUS_LABEL[f.status]];
  if (f.status === "DONE" && f.max_abs_diff_pct != null) parts.push(`최대 오차 ${pctText(f.max_abs_diff_pct)}`);
  return parts.join(" · ");
}

// ------------------------------------------------------------ 출처 ↔ 주소 질의
const SO_PICKS = ["best", "final_optimum", "surrogate_optimum", "run"] as const;

/** 진입 버튼 → `…/verify?new=1&kind=…` 질의 문자열(앞의 ? 없음) */
export function sourceToQuery(src: FemSourceReq): string {
  const q = new URLSearchParams({ new: "1", kind: src.kind });
  if (src.kind === "predict_job") q.set("job_id", src.job_id);
  else if (src.kind === "batch_run") {
    q.set("batch_id", src.batch_id);
    q.set("doe_no", String(src.doe_no));
  } else if (src.kind === "opt_design") {
    q.set("opt_id", src.opt_id);
    q.set("pick", src.pick);
    if (src.iter_no != null) q.set("iter_no", String(src.iter_no));
    if (src.doe_no != null) q.set("doe_no", String(src.doe_no));
  } else {
    q.set("param_set_id", src.param_set_id);
    q.set("values", JSON.stringify(src.values));
    if (src.model_id) q.set("model_id", src.model_id);
    if (src.input) q.set("input", src.input);
  }
  return q.toString();
}

/** 주소 질의 → 출처(잘못된 값이면 null) */
export function sourceFromQuery(sp: URLSearchParams): FemSourceReq | null {
  const kind = sp.get("kind");
  const int = (k: string) => {
    const v = sp.get(k);
    return v != null && /^\d+$/.test(v) ? Number(v) : null;
  };
  if (kind === "predict_job") {
    const job_id = sp.get("job_id");
    return job_id ? { kind, job_id } : null;
  }
  if (kind === "batch_run") {
    const batch_id = sp.get("batch_id");
    const doe_no = int("doe_no");
    return batch_id && doe_no != null ? { kind, batch_id, doe_no } : null;
  }
  if (kind === "opt_design") {
    const opt_id = sp.get("opt_id");
    const pick = sp.get("pick") as (typeof SO_PICKS)[number] | null;
    if (!opt_id || !pick || !SO_PICKS.includes(pick)) return null;
    const iter_no = int("iter_no");
    const doe_no = int("doe_no");
    if (pick === "run" && (iter_no == null || doe_no == null)) return null;
    return { kind, opt_id, pick, ...(iter_no != null ? { iter_no } : {}), ...(doe_no != null ? { doe_no } : {}) };
  }
  if (kind === "values") {
    const param_set_id = sp.get("param_set_id");
    try {
      const values = JSON.parse(sp.get("values") ?? "") as Record<string, number>;
      const input = sp.get("input");
      return param_set_id && values && typeof values === "object"
        ? { kind, param_set_id, values, model_id: sp.get("model_id"), ...(input === "assembly" || input === "cushion" ? { input } : {}) }
        : null;
    } catch {
      return null;
    }
  }
  return null;
}

/** 이 출처의 기존 검증을 찾는 목록 API 필터 */
export function lookupFilter(src: FemSourceReq): { predict_job_id?: string; batch_id?: string; opt_id?: string } | null {
  if (src.kind === "predict_job") return { predict_job_id: src.job_id };
  if (src.kind === "batch_run") return { batch_id: src.batch_id };
  if (src.kind === "opt_design") return { opt_id: src.opt_id };
  return null;
}

/** 목록 행이 이 출처와 같은 대상인지(배치 run·최적화 설계는 번호까지 비교) */
export function matchesSource(f: FemVerifySummary, src: FemSourceReq): boolean {
  if (src.kind === "predict_job") return f.links.predict_job_id === src.job_id;
  if (src.kind === "batch_run") return f.links.batch_id === src.batch_id && f.links.doe_no === src.doe_no;
  if (src.kind === "opt_design") return f.links.opt_id === src.opt_id && (src.pick !== "run" || f.links.doe_no === src.doe_no);
  return false;
}

// ------------------------------------------------------------ 진행 4단
export interface FvStage {
  key: string;
  label: string;
  state: "pending" | "running" | "done" | "skipped" | "failed" | "canceled";
}
export const FV_STATE_TEXT: Record<FvStage["state"], string> = { pending: "대기", running: "진행 중", done: "완료", skipped: "생략", failed: "실패", canceled: "취소" };

const GROUPS: { key: string; label: string; steps: string[] }[] = [
  { key: "assemble", label: "조립 입력 만들기", steps: ["FV_PREP", "FV_MESH", "FV_ASSEMBLE"] },
  { key: "solve", label: "해석", steps: ["HPC_SUBMIT", "HPC_WAIT"] },
  { key: "collect", label: "결과 회수", steps: ["COLLECT"] },
  { key: "compare", label: "비교 정리", steps: ["FV_EXTRACT", "FV_CURVE", "FV_CAPTURE", "FV_COMPARE"] },
];

function groupState(steps: JobStep[]): FvStage["state"] {
  if (!steps.length) return "pending";
  if (steps.some((s) => s.state === "FAILED")) return "failed";
  if (steps.some((s) => s.state === "RUNNING")) return "running";
  if (steps.some((s) => s.state === "CANCELED")) return "canceled";
  if (steps.every((s) => s.state === "SKIPPED")) return "skipped";
  if (steps.every((s) => s.state === "SUCCEEDED" || s.state === "SKIPPED")) return "done";
  if (steps.some((s) => s.state === "SUCCEEDED")) return "running";
  return "pending";
}

/** 진행 단: 동반 예측이 있으면 0단 "예측 실행 중"(예측 상태)이 앞에 붙는다 */
export function fvStages(job: Job | null, companion: boolean, predictState: string | null): FvStage[] {
  const out: FvStage[] = [];
  if (companion) {
    const st: FvStage["state"] = predictState === "SUCCEEDED" ? "done" : predictState === "FAILED" || predictState === "INTERRUPTED" ? "failed" : predictState === "CANCELED" ? "canceled" : predictState === "RUNNING" || predictState === "WAITING_HPC" || predictState === "COLLECTING" ? "running" : "pending";
    out.push({ key: "predict", label: "예측 실행 중", state: st });
  }
  for (const g of GROUPS) out.push({ key: g.key, label: g.label, state: job ? groupState(job.steps.filter((s) => g.steps.includes(s.step_key))) : "pending" });
  return out;
}

// ------------------------------------------------------------ 응답 표
export interface CompareRow {
  key: string;
  name: string;
  unit: string | null;
  kind: "MIN" | "MAX" | "VALUE";
  /** 구분 열 문구: MIN·MAX·판정값(stat) */
  kindText: string;
  pred: number | null;
  fem: number | null;
  diff: number | null;
  pct: number | null;
  note: string | null;
}

const NOTE_ZERO = "기준값 0";

function calc(pred: number | null, fem: number | null): { diff: number | null; pct: number | null; note: string | null } {
  if (pred == null || fem == null) return { diff: null, pct: null, note: null };
  const diff = pred - fem;
  if (Math.abs(fem) <= ZERO_TOL) return { diff, pct: null, note: NOTE_ZERO };
  return { diff, pct: (diff / Math.abs(fem)) * 100, note: null };
}

/** 응답마다 MIN·MAX·판정값 3행(MIN·MAX 오차는 같은 식으로 계산) */
export function compareRows(r: FemResponseRow): CompareRow[] {
  const mn = calc(r.pred_min, r.fem_min);
  const mx = calc(r.pred_max, r.fem_max);
  return [
    { key: `${r.name}-min`, name: r.name, unit: r.unit, kind: "MIN", kindText: "MIN", pred: r.pred_min, fem: r.fem_min, ...mn },
    { key: `${r.name}-max`, name: r.name, unit: r.unit, kind: "MAX", kindText: "MAX", pred: r.pred_max, fem: r.fem_max, ...mx },
    { key: `${r.name}-val`, name: r.name, unit: r.unit, kind: "VALUE", kindText: `판정값(${r.stat})`, pred: r.pred_value, fem: r.fem_value, diff: r.diff, pct: r.diff_pct, note: r.note },
  ];
}

/** 오차 % 절댓값 내림차순(없는 값은 뒤) */
export function sortResponses(rows: FemResponseRow[], byDiff: boolean): FemResponseRow[] {
  if (!byDiff) return rows;
  return [...rows].sort((a, b) => Math.abs(b.diff_pct ?? -1) - Math.abs(a.diff_pct ?? -1));
}

/** 컨투어 범례 한 줄 */
export function legendText(c: FemCompare["legend"] | null | undefined): string {
  if (!c) return "";
  if (c.mode === "fixed" && c.min != null && c.max != null) return `같은 범례 ${fmtNum(c.min)} ~ ${fmtNum(c.max)}${c.source === "minmax" ? " (두 결과 최대·최소)" : ""}`;
  return c.note ? c.note : "범례 자동(이미지마다)";
}

// ------------------------------------------------------------ 고급 입력 검증
/** §15.3 금지 문자(" { } [ ] $ \ ; |·제어문자), 64자 */
const BAD_CHARS = /["{}[\]$\;|\u0000-\u001f]/;
export function parseComps(text: string): { list: string[] | null; error: string | null } {
  const list = text.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);
  if (!list.length) return { list: null, error: null };
  if (list.length > 50) return { list: null, error: "격리 부품은 50개까지입니다" };
  const bad = list.find((x) => x.length > 64 || BAD_CHARS.test(x));
  return bad ? { list: null, error: `격리 부품 이름을 확인하세요(${bad.slice(0, 20)})` } : { list, error: null };
}
export function checkFemField(v: string): string | null {
  const t = v.trim();
  return t && (t.length > 64 || BAD_CHARS.test(t)) ? "FEM 결과 이름을 확인하세요" : null;
}
