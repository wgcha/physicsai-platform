// V3-S13-9: ⑤ 모드 세그먼트·저장, 원본 모드 mesh_only 막기, 새 내장 최적화 폼(재사용 지표 = design-map metrics·범위 검증·고정·정수·
// 요청 본문·미리보기 문구), 결과 화면(수렴 그래프·품질 등급·검증 run 표·CSV·최적 설계 링크·취소·이어서 실행 조건), 순수 규칙.
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import { ASSEMBLY_REQUIRED_TEXT } from "../stages/stage5/Stage5";
import { SO_MODE_KEY, boundNote, buildBody, compareRows, convergence, previewText, qualityGrade, rowIssue, varRows, type SoForm } from "../stages/stage5/surrogate/soRules";
import { perfRows } from "../stages/stage5/surrogate/perfRules";
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

  it("assembly여도 조립 폴더·starter가 없으면 원본 실행 막기(서버 needs_assembly_block과 같은 판정)", async () => {
    localStorage.setItem(SO_MODE_KEY, "original");
    renderApp(`${STUDY}/5`, { user: "power" }, (s) => {
      const ps = s.paramSets.find((p) => p.id === "ps-1")!;
      ps.starter_name = null;
    });
    expect((await screen.findByTestId("assembly-required")).textContent).toBe(ASSEMBLY_REQUIRED_TEXT);
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
    // S17 §22.12: ③ 성능 표 — 역할(목적·제약)을 행마다 고른다
    fireEvent.change(screen.getByLabelText("MaxStress 역할"), { target: { value: "min" } });
    expect(await screen.findByTestId("so-preview")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("so-preview").textContent).toBe("예측 최대 24 run(탐색 12 + 3 × 4) · 예상 53분"));
    fireEvent.change(screen.getByLabelText("MaxDisp 역할"), { target: { value: "le" } });
    fireEvent.change(screen.getByLabelText("MaxDisp 값"), { target: { value: "14" } });
    fireEvent.click(radio("대리모델", "RBF"));
    await waitFor(() => expect((screen.getByRole("button", { name: "최적화 시작" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "최적화 시작" }));
    expect(await screen.findByTestId("so-status")).toBeTruthy();
    expect(posts[0]).toMatchObject({
      param_set_id: "ps-1", explore: { kind: "new", count: null, seed: 1 }, objectives: [{ metric: "perf:MaxStress", series: null, sense: "min" }],
      constraints: [{ metric: "perf:MaxDisp", series: null, op: "<=", value: 14 }], observe: [], bounds: { THK_TOP: [0.3, 1], E_FOAM: [8, 8] },
      surrogate: "rbf", iterations: 3, candidates: 4, tol_rel: 0.01, capture: false,
    });
    expect(screen.getByTestId("so-progress").textContent).toMatch(/^탐색 B-/);
    expect(screen.getByRole("button", { name: "일괄 취소" })).toBeTruthy();
  });

  it("재사용: 같은 템플릿 DONE 배치 드롭다운, design-map 읽기(커브 계열 후보), 성능 표에 값 있는 run n/N", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const calls = recordCalls(server);
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    fireEvent.click(await screen.findByRole("radio", { name: "기존 배치 재사용" }));
    const sel = (await screen.findByLabelText("재사용 배치")) as HTMLSelectElement;
    expect(sel.options[0].textContent).toMatch(/^B-002 · 20 run · /);
    await waitFor(() => expect(calls.some((c) => /GET \/predict-batches\/.+\/design-map/.test(c))).toBe(true));
    fireEvent.change(await screen.findByLabelText("MaxStress 역할"), { target: { value: "min" } });
    await waitFor(() => expect(screen.getByTestId("perf-avail-MaxStress").textContent).toMatch(/^\d+\/\d+/));
  });

  it("결과 화면: 최적 설계·링크, 수렴 그래프, 품질 등급, 검증 run 표·CSV, 완료면 취소·이어서 실행 없음", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    const calls = recordCalls(server);
    expect((await screen.findByTestId("so-status")).textContent).toBe("완료");
    expect(screen.getByTestId("so-progress").textContent).toMatch(/^완료 — /);
    const best = screen.getByRole("region", { name: "최적안 — 기준안 대비" });
    expect(within(best).getByTestId("so-best-link").getAttribute("href")).toMatch(/\/stage\/4\/batch\/b-so-so-1-\d$/);
    expect(within(best).getByText(/FEM 검증 버튼으로 조립 상태 해석/)).toBeTruthy();
    // D3-61: 변수마다 학습 범위·기준안(nominal)·최적안·변화
    const cmp = within(best).getByRole("table", { name: "기준안 대비" });
    expect(within(cmp).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["변수", "범위(학습)", "기준안", "최적안", "변화"]);
    const o = server.surrogate[0];
    const top = within(cmp).getByTestId("cmp-THK_TOP");
    expect(top.textContent).toContain("0.6"); // nominal
    const bestTop = (o.final!.best!.values as Record<string, number>).THK_TOP;
    if (bestTop >= 1.2) expect(within(best).getByTestId("bound-note").textContent).toContain("THK_TOP(상한)");
    // 결과 요약 타일: 목적(기준안 대비 %)·제약·품질·소요
    const kp = screen.getByTestId("so-kpis");
    expect(kp.textContent).toMatch(/vs 기준안/);
    expect(kp.textContent).toMatch(/제약 ≤ 14/);
    expect(kp.textContent).toMatch(/Q² /);
    expect(kp.textContent).toMatch(/예측/);
    // 컨투어 비교: 기준안·최적안 둘, 같은 범례 문구
    const cc = screen.getByRole("region", { name: "컨투어 비교 — 기준안 · 최적안" });
    expect(within(cc).getByText(/같은 범례\(0–/)).toBeTruthy();
    expect(within(cc).getByTestId("contour-기준안")).toBeTruthy();
    expect(within(cc).getByTestId("contour-최적안")).toBeTruthy();
    expect(within(cc).getAllByTestId("contour-media")).toHaveLength(2);
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

  it("마무리 캡처 없음(미구성·실패) → '캡처 없음 — 사유', 진행 중 → 캡처 중 문구", async () => {
    const r1 = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => {
      s.surrogate[0].final = { status: "SKIPPED", reason: "컨투어 캡처가 구성되지 않았습니다(commands.contour_capture)", baseline_values: { THK_TOP: 0.6 } };
    });
    expect((await screen.findByTestId("contour-none")).textContent).toBe("캡처 없음 — 컨투어 캡처가 구성되지 않았습니다(commands.contour_capture)");
    expect(screen.getByTestId("so-kpis").textContent).toContain("기준안 값 없음");
    r1.unmount();
    const r2 = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => {
      s.surrogate[0].final = { ...s.surrogate[0].final!, legend: null, legend_note: "목적 지표가 컨투어 결과 종류(Stress)의 값이 아니라 이미지마다 자동 범례" };
    });
    expect(await screen.findByText(/^범례 개별 — 목적 지표가 컨투어 결과 종류/)).toBeTruthy();
    r2.unmount();
    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => {
      Object.assign(s.surrogate[0], { status: "FINALIZING", final: { ...s.surrogate[0].final, status: "PENDING", baseline: null, best: null } });
    });
    expect((await screen.findByTestId("contour-none")).textContent).toMatch(/^기준안·최적안 컨투어를 캡처하는 중입니다/);
    expect(screen.getByTestId("so-status").textContent).toBe("마무리(캡처)");
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

  it("순수 규칙: 기준안 대비 행·범위 끝 안내", () => {
    const rows = compareRows([{ name: "A", nominal: 1, min: 0, max: 2, unit: "mm" }, { name: "B", nominal: 5, min: 2, max: 8, unit: "" }], null, { A: 2, B: 4 });
    expect(rows[0]).toMatchObject({ base: 1, opt: 2, delta: 1, bound: "upper", basePos: 0.5, optPos: 1 });
    expect(rows[1]).toMatchObject({ base: 5, opt: 4, delta: -1, bound: null });
    expect(boundNote(rows)).toBe("A(상한)이(가) 학습 범위 끝에 닿았습니다 — 범위를 넓혀 학습하면 추가 개선 여지가 있습니다");
    expect(boundNote(rows.slice(1))).toBeNull();
  });

  it("순수 규칙: 본문(바뀐 범위·고정만), 행 검증, 미리보기 문구, 품질 등급, 수렴 자료", () => {
    const ps = { ...seedParamSet() };
    const rows = varRows(ps);
    expect(rows.find((r) => r.name === "RIB_N")!.integer).toBe(true);
    const f: SoForm = {
      paramSetId: "ps-1", modelId: null, explore: "reuse", count: "", exploreSeed: "1", batchId: "b-1",
      sels: { MaxStress: { role: "max", a: "", b: "" }, MaxDisp: { role: "le", a: "", b: "" } }, weights: {},
      rows: rows.map((r) => (r.name === "RIB_N" ? { ...r, fixed: true, lo: "4" } : r)),
      surrogate: "gp", iterations: "2", candidates: "3", tolPct: "0.5", seed: "7", multi: "2", capture: true,
    };
    const perfs = perfRows(ps.responses);
    expect(buildBody(f, perfs)).toEqual({
      param_set_id: "ps-1", model_id: null, explore: { kind: "reuse", batch_id: "b-1" }, objectives: [{ metric: "perf:MaxStress", series: null, sense: "max" }],
      constraints: [], observe: [], bounds: { RIB_N: [4, 4] }, surrogate: "gp", iterations: 2, candidates: 3, tol_rel: 0.005, seed: 7, multi_execution: 2, capture: true,
    });
    expect(rowIssue({ ...rows[3], lo: "3.2", hi: "3.8" })).toBe("정수가 없습니다");
    expect(rowIssue({ ...rows[0], lo: "1", hi: "0.5" })).toBe("하한 ≤ 상한");
    expect(rowIssue(rows[0])).toBeNull();
    expect(previewText({ explore_count: 20, max_total_runs: 32, estimate_min: 70 }, 3, 4)).toBe("예측 최대 32 run(탐색 20 + 3 × 4) · 예상 70분");
    expect(previewText({ explore_count: 0, max_total_runs: 12, estimate_min: null }, 3, 4)).toBe("예측 최대 12 run(재사용 + 3 × 4)");
    expect(previewText({ explore_count: 20, max_total_runs: 32, estimate_min: 70 }, 3, 4, 2)).toBe("예측 최대 32 run(탐색 20 + 3 × 4) · 예상 70분 · 목적 2개(다목적)");
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
