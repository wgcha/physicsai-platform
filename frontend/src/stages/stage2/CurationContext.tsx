import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type Curation, type CurationSource, type CurationSourceRef, type SpdmImport } from "../../api";
import { useStudy } from "../../app/StudyContext";

export type SourceMode = "TRAIN_DOE" | "SPDM_IMPORT" | "FOLDER";

export interface CurationData {
  sources: CurationSource[];
  imports: SpdmImport[];
  curations: Curation[];
  mode: SourceMode;
  setMode: (m: SourceMode) => void;
  doeId: string;
  setDoeId: (id: string) => void;
  importId: string;
  setImportId: (id: string) => void;
  folder: { path: string; ok: boolean; h3d: number; t01: number };
  setFolder: (f: { path: string; ok: boolean; h3d: number; t01: number }) => void;
  /** 선택한 원천(§4.4). 아직 고르지 않았거나 확인 전이면 null */
  source: CurationSourceRef | null;
  sourceInfo: { h3d: number; t01: number; runsExpected: number | null; label: string } | null;
  reload: () => Promise<void>;
}

const Ctx = createContext<CurationData | null>(null);

export function useCuration(): CurationData {
  const v = useContext(Ctx);
  if (!v) throw new Error("CurationProvider 없음");
  return v;
}

/** 원천 객체 비교(미리보기 작업이 지금 원천의 것인지) */
export function sameSource(a: unknown, b: CurationSourceRef | null): boolean {
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

export function CurationProvider({ children }: { children: ReactNode }) {
  const { study } = useStudy();
  const [params] = useSearchParams();
  const importJob = params.get("import_job");
  const [sources, setSources] = useState<CurationSource[]>([]);
  const [imports, setImports] = useState<SpdmImport[]>([]);
  const [curations, setCurations] = useState<Curation[]>([]);
  const [mode, setMode] = useState<SourceMode>(importJob ? "SPDM_IMPORT" : "TRAIN_DOE");
  const [doeId, setDoeId] = useState("");
  const [importId, setImportId] = useState("");
  const [folder, setFolder] = useState({ path: "", ok: false, h3d: 0, t01: 0 });

  const reload = useCallback(async () => {
    const [s, i, c] = await Promise.all([
      api.curationSources(study.id).catch(() => [] as CurationSource[]),
      api.spdmImports(study.id).catch(() => [] as SpdmImport[]),
      api.curations(study.id).catch(() => [] as Curation[]),
    ]);
    setSources(s);
    setImports(i);
    setCurations(c);
    setDoeId((cur) => cur || s.find((x) => x.kind === "TRAIN_DOE")?.ref_id || "");
    setImportId((cur) => {
      if (cur) return cur;
      const fromLink = importJob ? i.find((x) => x.job_id === importJob) : undefined;
      return fromLink?.id ?? s.find((x) => x.kind === "SPDM_IMPORT")?.ref_id ?? "";
    });
  }, [study.id, importJob]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const value = useMemo<CurationData>(() => {
    let source: CurationSourceRef | null = null;
    let sourceInfo: CurationData["sourceInfo"] = null;
    if (mode === "TRAIN_DOE" && doeId) {
      source = { kind: "TRAIN_DOE", doe_id: doeId };
      const s = sources.find((x) => x.kind === "TRAIN_DOE" && x.ref_id === doeId);
      sourceInfo = s ? { h3d: s.h3d_count, t01: s.t01_count, runsExpected: s.runs_expected, label: s.label } : null;
    } else if (mode === "SPDM_IMPORT" && importId) {
      const im = imports.find((x) => x.id === importId);
      const s = sources.find((x) => x.kind === "SPDM_IMPORT" && x.ref_id === importId);
      if (im?.status === "READY" || s) {
        source = { kind: "SPDM_IMPORT", import_id: importId };
        sourceInfo = s ? { h3d: s.h3d_count, t01: s.t01_count, runsExpected: null, label: s.label } : { h3d: 0, t01: 0, runsExpected: null, label: im?.spdm_path ?? importId };
      }
    } else if (mode === "FOLDER" && folder.ok) {
      source = { kind: "FOLDER", path: folder.path.trim() };
      sourceInfo = { h3d: folder.h3d, t01: folder.t01, runsExpected: null, label: folder.path };
    }
    return { sources, imports, curations, mode, setMode, doeId, setDoeId, importId, setImportId, folder, setFolder, source, sourceInfo, reload };
  }, [sources, imports, curations, mode, doeId, importId, folder, reload]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
