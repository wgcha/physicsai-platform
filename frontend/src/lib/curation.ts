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
  /** 원천 루트 기준 파일 목록(preview_summary.json `files[].rel`, C14) — exclude_files에 그대로 쓴다 */
  files: string[] | null;
}

const numList = (v: unknown): number[] => (Array.isArray(v) ? v.map(Number).filter(Number.isFinite) : []);

/**
 * h3d 미리보기 → 화면용. 우선 preview_summary.json(변경 메모 C14:
 * `{datatypes:[{name, components, usable}], parts:{shell,solid,rbody}, num_time_step, sample_file, source_file_count, files:[{rel, run_folder, size}]}`),
 * 없으면 원문 PREVIEW_H3D.json(`datatype_info`, `lst_cid_*`, `num_time_step`)에서 usable을 직접 계산. 둘 다 형식이 맞지 않으면 null
 */
export function parseH3dPreview(files: Record<string, unknown>): H3dPreview | null {
  const summary = files["preview_summary.json"] as Record<string, unknown> | undefined;
  if (summary && Array.isArray(summary.datatypes)) {
    const parts = (summary.parts ?? {}) as Record<string, unknown>;
    return {
      datatypes: (summary.datatypes as Record<string, unknown>[]).map((d) => {
        const components = Array.isArray(d.components) ? d.components.map(String) : [];
        return { name: String(d.name ?? ""), components, usable: Array.isArray(d.usable) ? d.usable.map(String) : components.filter(isUsableComponent) };
      }),
      parts: { shell: numList(parts.shell), solid: numList(parts.solid), rbody: numList(parts.rbody) },
      numSteps: Number(summary.num_time_step) || 0,
      sampleFile: (summary.sample_file as string) ?? null,
      files: Array.isArray(summary.files)
        ? (summary.files as unknown[]).map((f) => (typeof f === "string" ? f : String((f as { rel?: unknown }).rel ?? ""))).filter(Boolean)
        : null,
    };
  }
  const raw = files["PREVIEW_H3D.json"] as Record<string, unknown> | undefined;
  const info = raw?.datatype_info as Record<string, unknown> | undefined;
  if (!raw || !info || typeof info !== "object") return null;
  return {
    datatypes: Object.entries(info).map(([name, comps]) => {
      const components = Array.isArray(comps) ? comps.map(String) : [];
      return { name, components, usable: components.filter(isUsableComponent) };
    }),
    parts: { shell: numList(raw.lst_cid_shell), solid: numList(raw.lst_cid_solid), rbody: numList(raw.lst_cid_rbody) },
    numSteps: Number(raw.num_time_step) || 0,
    sampleFile: null,
    files: null,
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
