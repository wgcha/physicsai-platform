// V3-S13-9: ⑤ 모드 세그먼트·저장, 원본 모드 mesh_only 막기, 새 내장 최적화 폼(재사용 지표 = design-map metrics·범위 검증·고정·정수·
// 요청 본문·미리보기 문구), 결과 화면(수렴 그래프·품질 등급·검증 run 표·CSV·최적 설계 링크·취소·이어서 실행 조건), 순수 규칙.
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import { ASSEMBLY_REQUIRED_TEXT } from "../stages/stage5/Stage5";
import { SO_MODE_KEY, buildBody, convergence, previewText, qualityGrade, rowIssue, varRows, type SoForm } from "../stages/stage5/surrogate/soRules";
import { seedParamSet } from "../mock/seed";
import type { MockServer } from "../mock/server";

const radio = (group: string, name: string) => within(screen.getByRole("radiogroup", { name: group })).getByRole("radio", { name }) as HTMLButtonElement;

function bodyOf(server: MockServer, path: string) {
  const out: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && p === path) out.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return out;
}

describe("V3-S13-9 ⑤ 플랫폼 내장 최적화 화면", () => {
  afterEach(() => localStorage.clear());

  it("모드: 기본 내장, 원본으로 바꾸면 기억 · mesh_only 템플릿이면 원본 실행 막기 문구·버튼 비활성", async () => {
    renderApp(`${STUDY}/5`, { user: "power" }, (s) => {
      s.paramSets.forEach((p) => (p.is_current = p.id === "ps-2")); // 쿠션 단독(mesh_only)
    });
    expect((await screen.findByRole("radio", { name: "플랫폼 내장(쿠션만 가능)" })).getAttribute("aria-checked")).toBe("true");
    expect(await screen.findByRole("tab", { name: /실행 목록/ })).toBeTruthy();
    fireEvent.click(radio("최적화 방식", "원본 최적화(조립 필요)"));
    expect(localStorage.getItem(SO_MODE_KEY)).toBe("original");
    expect((await screen.findByTestId("assembly-required")).textContent).toBe(ASSEMBLY_REQUIRED_TEXT);
    const run = screen.getByRole("region", { name: "실행" });
    expect((within(run).getByRole("button", { name: "최적화 실행" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(run).getByRole("button", { name: "플랫폼 내장으로" }));
    expect(localStorage.getItem(SO_MODE_KEY)).toBe("builtin");
  });

  it("optimize_builtin 꺼짐 → 내장 버튼 비활성·사유, 원본 모드로 시작", async () => {
    renderApp(`${STUDY}/5`, { user: "power", disabledFeatures: ["optimize_builtin"] });
    const b = await screen.findByRole("radio", { name: "플랫폼 내장(쿠션만 가능)" });
    expect((b as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("opt-mode-hint").textContent).toContain("python.numpy");
    expect(screen.getByRole("radio", { name: "원본 최적화(조립 필요)" }).getAttribute("aria-checked")).toBe("true");
  });

  it("새 최적화: 변수 표(정수·고정·범위 검증)·미리보기 문구·시작 요청 본문 → 결과 화면", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const posts = bodyOf(server, "/studies/s-cushion/surrogate-opts");
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    const vars = await screen.findByRole("table", { name: "변수 범위" });
    expect(within(vars).getByTestId("var-RIB_N").textContent).toContain("정수");
    fireEvent.change(within(vars).getByLabelText("THK_TOP 상한"), { target: { value: "9" } });
    expect(within(vars).getByTestId("var-THK_TOP").textContent).toContain("학습 범위 0.3~1.2 안");
    const start = screen.getByRole("button", { name: "최적화 시작" }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    fireEvent.change(within(vars).getByLabelText("THK_TOP 상한"), { target: { value: "1.0" } });
    fireEvent.click(within(vars).getByLabelText("E_FOAM 고정"));
    fireEvent.change(within(vars).getByLabelText("E_FOAM 하한"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("목적 지표"), { target: { value: "resp:MaxStress_MAX" } });
    expect(await screen.findByTestId("so-preview")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("so-preview").textContent).toBe("예측 최대 24 run(탐색 12 + 3 × 4) · 예상 53분"));
    fireEvent.click(screen.getByRole("button", { name: "제약 추가" }));
    fireEvent.change(screen.getByLabelText("제약 1 지표"), { target: { value: "resp:MaxDisp_MAX" } });
    fireEvent.change(screen.getByLabelText("제약 1 값"), { target: { value: "14" } });
    fireEvent.click(radio("대리모델", "RBF"));
    await waitFor(() => expect((screen.getByRole("button", { name: "최적화 시작" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "최적화 시작" }));
    expect(await screen.findByTestId("so-status")).toBeTruthy();
    expect(posts[0]).toMatchObject({
      param_set_id: "ps-1", explore: { kind: "new", count: null, seed: 1 }, objective: { metric: "resp:MaxStress_MAX", sense: "min" },
      constraints: [{ metric: "resp:MaxDisp_MAX", op: "<=", value: 14 }], bounds: { THK_TOP: [0.3, 1], E_FOAM: [8, 8] },
      surrogate: "rbf", iterations: 3, candidates: 4, tol_rel: 0.01, capture: false,
    });
    expect(screen.getByTestId("so-progress").textContent).toMatch(/^탐색 B-/);
    expect(screen.getByRole("button", { name: "일괄 취소" })).toBeTruthy();
  });

  it("재사용: 같은 템플릿 DONE 배치 드롭다운, 지표 목록 = design-map metrics, 커브 지표면 계열 선택", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const calls = recordCalls(server);
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    fireEvent.click(await screen.findByRole("radio", { name: "기존 배치 재사용" }));
    const sel = (await screen.findByLabelText("재사용 배치")) as HTMLSelectElement;
    expect(sel.options[0].textContent).toMatch(/^B-002 · 20 run · /);
    await waitFor(() => expect(calls.some((c) => /GET \/predict-batches\/.+\/design-map/.test(c))).toBe(true));
    const dm = server.handle("GET", `/predict-batches/${sel.value}/design-map`, new URLSearchParams(), null, new Headers()).body as {
      metrics: { id: string }[]; series: string[];
    };
    const metric = screen.getByLabelText("목적 지표") as HTMLSelectElement;
    await waitFor(() => expect([...metric.options].map((o) => o.value)).toEqual(dm.metrics.map((m) => m.id)));
    expect(metric.value).toBe("curve:max");
    if (dm.series.length > 1) expect((screen.getByLabelText("커브 계열") as HTMLSelectElement).options.length).toBe(dm.series.length);
    fireEvent.change(metric, { target: { value: dm.metrics.find((m) => m.id.startsWith("resp:"))!.id } });
    expect(screen.queryByLabelText("커브 계열")).toBeNull();
  });

  it("결과 화면: 최적 설계·링크, 수렴 그래프, 품질 등급, 검증 run 표·CSV, 완료면 취소·이어서 실행 없음", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    const calls = recordCalls(server);
    expect((await screen.findByTestId("so-status")).textContent).toBe("완료");
    expect(screen.getByTestId("so-progress").textContent).toMatch(/^완료 — /);
    const best = screen.getByRole("region", { name: "최적 설계" });
    expect(within(best).getByTestId("so-best-link").getAttribute("href")).toMatch(/\/stage\/4\/batch\/b-so-so-1-\d$/);
    expect(within(best).getByText(/PBS 검증 해석/)).toBeTruthy();
    expect(screen.getByRole("img", { name: "수렴 그래프" })).toBeTruthy();
    const q = screen.getByRole("table", { name: "대리모델 품질" });
    expect(within(q).getAllByRole("row")).toHaveLength(4); // 머리 + 반복 1~3
    expect(within(q).getByTestId("fit-1").textContent).toMatch(/좋음|보통|낮음/);
    const runs = screen.getByRole("table", { name: "검증 run" });
    expect(within(runs).getAllByRole("row").length).toBe(1 + 16 + 12);
    expect(screen.queryByRole("button", { name: "일괄 취소" })).toBeNull();
    expect(screen.queryByRole("button", { name: "이어서 실행" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "CSV 받기" }));
    await waitFor(() => expect(calls).toContain("GET /surrogate-opts/so-1/runs.csv"));
    expect(screen.getByTestId("so-dir").textContent).toContain("05_opt\\surrogate\\SO-001");
  });

  it("진행 중 → 일괄 취소(확인) → 취소됨, 실패면 이어서 실행", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => {
      const o = s.surrogate[0];
      o.status = "VERIFYING";
    });
    fireEvent.click(await screen.findByRole("button", { name: "일괄 취소" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "일괄 취소" }));
    await waitFor(() => expect(screen.getByTestId("so-status").textContent).toBe("취소"));
    expect(server.surrogate[0].stop_reason).toBe("CANCELED");
  });

  it("실패면 이어서 실행 → 다시 진행, 조회 권한(general)은 버튼 없음", async () => {
    const fail = (s: MockServer) => Object.assign(s.surrogate[0], { status: "FAILED", stop_reason: "ROUND_FAILED" });
    const r1 = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, fail);
    fireEvent.click(await screen.findByRole("button", { name: "이어서 실행" }));
    await waitFor(() => expect(screen.getByTestId("so-status").textContent).toBe("대리모델 학습"));
    r1.unmount();
    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "general" }, fail);
    expect((await screen.findByTestId("so-status")).textContent).toBe("실패");
    expect(screen.queryByRole("button", { name: "이어서 실행" })).toBeNull();
  });

  it("순수 규칙: 본문(바뀐 범위·고정만), 행 검증, 미리보기 문구, 품질 등급, 수렴 자료", () => {
    const ps = { ...seedParamSet() };
    const rows = varRows(ps);
    expect(rows.find((r) => r.name === "RIB_N")!.integer).toBe(true);
    const f: SoForm = {
      paramSetId: "ps-1", modelId: null, explore: "reuse", count: "", exploreSeed: "1", batchId: "b-1", metric: "curve:max", series: "Node 100 / Z",
      sense: "max", constraints: [{ metric: "", op: "<=", value: "" }], rows: rows.map((r) => (r.name === "RIB_N" ? { ...r, fixed: true, lo: "4" } : r)),
      surrogate: "gp", iterations: "2", candidates: "3", tolPct: "0.5", seed: "7", multi: "2", capture: true,
    };
    expect(buildBody(f)).toEqual({
      param_set_id: "ps-1", model_id: null, explore: { kind: "reuse", batch_id: "b-1" }, objective: { metric: "curve:max", series: "Node 100 / Z", sense: "max" },
      constraints: [], bounds: { RIB_N: [4, 4] }, surrogate: "gp", iterations: 2, candidates: 3, tol_rel: 0.005, seed: 7, multi_execution: 2, capture: true,
    });
    expect(rowIssue({ ...rows[3], lo: "3.2", hi: "3.8" })).toBe("정수가 없습니다");
    expect(rowIssue({ ...rows[0], lo: "1", hi: "0.5" })).toBe("하한 ≤ 상한");
    expect(rowIssue(rows[0])).toBeNull();
    expect(previewText({ explore_count: 20, max_total_runs: 32, estimate_min: 70 }, 3, 4)).toBe("예측 최대 32 run(탐색 20 + 3 × 4) · 예상 70분");
    expect(previewText({ explore_count: 0, max_total_runs: 12, estimate_min: null }, 3, 4)).toBe("예측 최대 12 run(재사용 + 3 × 4)");
    expect([qualityGrade(0.95).label, qualityGrade(0.8).label, qualityGrade(0.5).label, qualityGrade(null).label]).toEqual(["좋음", "보통", "낮음", "—"]);
    expect(qualityGrade(0.5).hint).toBe("탐색 run을 늘리세요");
    const c = convergence({
      settings: { iterations: 3 },
      runs: [{ iter_no: 0, batch_id: "b", batch_label: "B-1", doe_no: 1, run_key: "r", values: {}, objective: 5, constraints: [], state: "SUCCEEDED" },
        { iter_no: 1, batch_id: "b2", batch_label: "B-2", doe_no: 1, run_key: "r", values: {}, objective: null, constraints: [], state: "FAILED" }],
      iterations: [{ iter_no: 0, kind: "EXPLORE", best_value: 5 }, { iter_no: 1, kind: "VERIFY", best_value: 4, candidates: [{ doe_no: 1, values: {}, predicted: 3.5 }] }],
    } as never);
    expect(c.verified).toHaveLength(1);
    expect(c.predicted.map((p) => [p.x, p.y])).toEqual([[1, 3.5]]);
    expect(c.best).toEqual([[0, 5], [1, 4]]);
    expect(c.xMax).toBe(3);
  });
});
