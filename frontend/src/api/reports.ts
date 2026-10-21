// HTML 결과 요약 보고서(upload-report.md §9.4) — 서버가 요청 시 만들어 파일로 응답한다. 화면은 현재 선택 상태를 쿼리로 넘기고 blob 을 내려받는다.
import { fetchFile } from "./client";

export type ReportTarget = "surrogate-opt" | "optimization" | "equiv-check";

export interface AnalysisReportQuery {
  source: "batch" | "doe";
  id: string;
  compare_source?: "batch" | "doe" | null;
  compare_id?: string | null;
  vars?: string[];
  resp?: string | null;
}

/** analysis 쿼리: vars 는 반복 키(vars=A&vars=B), 빈 값은 생략(서버가 화면과 같은 기본값 규칙으로 채움) */
export function analysisQuery(q: AnalysisReportQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set("source", q.source);
  p.set("id", q.id);
  if (q.compare_source && q.compare_id) {
    p.set("compare_source", q.compare_source);
    p.set("compare_id", q.compare_id);
  }
  for (const v of q.vars ?? []) p.append("vars", v);
  if (q.resp) p.set("resp", q.resp);
  p.set("download", "1");
  return p;
}

export const reportApi = {
  analysis: (q: AnalysisReportQuery) => fetchFile("/reports/analysis", analysisQuery(q)),
  byTarget: (target: ReportTarget, id: string) => fetchFile(`/reports/${target}/${encodeURIComponent(id)}`, { download: 1 }),
};
