// ② 데이터 정리 화면 보조 규칙(phase2.md §6.7·§6.8, 원본 GUI 규칙의 화면 쪽 사본)

/** 원본 to_cfg_datacomp(GUI:711-734): 단어 1~2개만 사용 가능, 3개 이상·"Extreme" 시작은 불가 */
export function isUsableComponent(c: string): boolean {
  const words = c.trim().split(/\s+/).filter(Boolean);
  return words.length >= 1 && words.length <= 2 && !c.trim().startsWith("Extreme");
}

/** time step 목록(원본 GUI:327-336) */
export function timeSteps(numSteps: number, increment: number): number[] {
  const inc = Math.max(1, Math.floor(increment) || 1);
  const out: number[] = [];
  for (let s = 1; s <= numSteps; s += inc) out.push(s);
  return out;
}

/** "Steps (N개): 1, 3, 5 …" 미리보기(80자 자름, 원본 GUI:338-348) */
export function timeStepsText(numSteps: number, increment: number, max = 80): string {
  const st = timeSteps(numSteps, increment);
  const text = `Steps (${st.length}개): ${st.join(", ")}`;
  return text.length > max ? `${text.slice(0, max - 1).replace(/,\s*\d*$/, "")} …` : text;
}

export interface H3dPreview {
  datatypes: { name: string; components: string[]; usable: string[] }[];
  parts: { shell: number[]; solid: number[]; rbody: number[] };
  numSteps: number;
  sampleFile: string | null;
  /** 원천 파일 목록(preview_summary.json에 있을 때만 — 계약 미확정) */
  files: string[] | null;
}

/** PREVIEW_H3D.json(원문)·preview_summary.json → 화면용. 키 검증 실패면 null */
export function parseH3dPreview(files: Record<string, unknown>): H3dPreview | null {
  const summary = (files["preview_summary.json"] ?? null) as Record<string, unknown> | null;
  const raw = (files["PREVIEW_H3D.json"] ?? summary) as Record<string, unknown> | null;
  if (!raw || typeof raw !== "object") return null;
  const info = raw.datatype_info as Record<string, unknown> | undefined;
  if (!info || typeof info !== "object") return null;
  const usableMap = (summary?.usable ?? null) as Record<string, string[]> | null;
  const ids = (k: string) => (Array.isArray(raw[k]) ? (raw[k] as unknown[]).map(Number).filter(Number.isFinite) : []);
  return {
    datatypes: Object.entries(info).map(([name, comps]) => {
      const components = Array.isArray(comps) ? comps.map(String) : [];
      return { name, components, usable: usableMap?.[name] ?? components.filter(isUsableComponent) };
    }),
    parts: { shell: ids("lst_cid_shell"), solid: ids("lst_cid_solid"), rbody: ids("lst_cid_rbody") },
    numSteps: Number(raw.num_time_step) || 0,
    sampleFile: (summary?.sample_file as string) ?? null,
    files: Array.isArray(summary?.files) ? (summary!.files as unknown[]).map(String) : null,
  };
}

export interface T01Tree {
  name: string;
  requests: { name: string; components: string[] }[];
}

/** PREVIEW_T01.json `dataTypes:[{name, requests:[{name, components}]}]`(원본 GUI:259-289) */
export function parseT01Preview(data: unknown): T01Tree[] | null {
  const d = (data as { dataTypes?: unknown })?.dataTypes;
  if (!Array.isArray(d)) return null;
  return d.map((t) => ({
    name: String((t as { name?: unknown }).name ?? ""),
    requests: (((t as { requests?: unknown }).requests as unknown[]) ?? []).map((r) => ({
      name: String((r as { name?: unknown }).name ?? ""),
      components: (((r as { components?: unknown }).components as unknown[]) ?? []).map(String),
    })),
  }));
}
