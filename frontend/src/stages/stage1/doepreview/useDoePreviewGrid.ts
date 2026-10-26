// DOE 형상 그리드 요청·폴링(doe-preview.md §6.6): POST(200 전부 캐시 | 202) → 진행 중 페이지만 GET 1초 폴링 → 종료 시 멈춤.
// 정렬·변수가 바뀌면 처음부터(reset), [다음 24개]는 offset을 더해 페이지를 덧붙인다. 새 요청은 이전 폴링 결과를 버린다.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, errorMessage, type DoePreview, type DoePreviewOrder, type DoePreviewSource } from "../../../api";
import { POLL } from "../../../lib/poll";
import { PAGE_SIZE, PREVIEW_ERROR_TEXT, buildReq, isActive } from "./gridModel";

export interface GridInput {
  source: DoePreviewSource;
  sampling: Record<string, unknown> | null;
}
export interface GridSelect {
  order: DoePreviewOrder;
  var: string | null;
  desc: boolean;
}
export interface GridPage {
  offset: number;
  pv: DoePreview;
}

const errText = (e: unknown): string => (e instanceof ApiError && PREVIEW_ERROR_TEXT[e.code]) || errorMessage(e);

export function useDoePreviewGrid(studyId: string) {
  const [pages, setPages] = useState<GridPage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const gen = useRef(0);
  const last = useRef<{ input: GridInput; sel: GridSelect } | null>(null);
  useEffect(
    () => () => {
      gen.current++;
    },
    [],
  );

  const post = useCallback(
    async (offset: number): Promise<GridPage | null> => {
      const l = last.current;
      if (!l) return null;
      const my = gen.current;
      setBusy(true);
      try {
        const pv = await api.createDoePreview(studyId, buildReq(l.input.source, l.input.sampling, { ...l.sel, offset, limit: PAGE_SIZE }));
        return my === gen.current ? { offset, pv } : null;
      } catch (e) {
        if (my === gen.current) setError(errText(e));
        return null;
      } finally {
        if (my === gen.current) setBusy(false);
      }
    },
    [studyId],
  );

  /** 처음부터(첫 페이지 offset 0) */
  const load = useCallback(
    async (input: GridInput, sel: GridSelect) => {
      gen.current++;
      last.current = { input, sel };
      setError(null);
      setPages([]);
      const p = await post(0);
      if (p) setPages([p]);
    },
    [post],
  );

  const next = useCallback(async () => {
    const offset = pages.length * PAGE_SIZE;
    const p = await post(offset);
    if (p) setPages((x) => (x.some((y) => y.offset === offset) ? x : [...x, p].sort((a, b) => a.offset - b.offset)));
  }, [post, pages.length]);

  /** 한 페이지 다시 요청(오류 셀·만료 PNG) */
  const retry = useCallback(
    async (offset: number) => {
      const p = await post(offset);
      if (p) setPages((x) => x.map((y) => (y.offset === offset ? p : y)));
    },
    [post],
  );

  const cancel = useCallback(async () => {
    const ids = pages.filter((p) => isActive(p.pv)).map((p) => p.pv.id);
    for (const id of ids) {
      try {
        const pv = await api.cancelDoePreview(id);
        setPages((x) => x.map((y) => (y.pv.id === id ? { ...y, pv } : y)));
      } catch (e) {
        setError(errText(e));
      }
    }
  }, [pages]);

  const reset = useCallback(() => {
    gen.current++;
    last.current = null;
    setPages([]);
    setError(null);
    setBusy(false);
  }, []);

  // 진행 중 페이지 폴링(1초) — 종료되면 멈춘다
  const activeKey = pages.filter((p) => isActive(p.pv)).map((p) => p.pv.id).join(",");
  useEffect(() => {
    if (!activeKey) return;
    const my = gen.current;
    const t = setInterval(async () => {
      for (const id of activeKey.split(",")) {
        try {
          const pv = await api.doePreview(id);
          if (my !== gen.current) return;
          setPages((x) => x.map((y) => (y.pv.id === id ? { ...y, pv } : y)));
        } catch (e) {
          if (my === gen.current) setError(errText(e));
        }
      }
    }, POLL.doePreview);
    return () => clearInterval(t);
  }, [activeKey]);

  return { pages, error, busy, load, next, retry, cancel, reset, input: last.current?.input ?? null, select: last.current?.sel ?? null };
}
