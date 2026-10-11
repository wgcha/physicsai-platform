// phase3.md §4.4 S2 모델 비교 (V3-S2-1~5)
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import { seedModels } from "../mock/data";
import type { Model } from "../api";
import { bestIndices, canUseLog, distinctDatasetIds, epochText, loadDirection, metricRows, saveDirection, seriesFor, toggleSelection } from "../stages/stage3/compare";

const mk = (p: Partial<Model> & { id: string }): Model =>
  ({
    study_id: "s", name: "M", version: 1, source_path: "", log_status: "PARSED", eval_status: "DONE", status: "ACTIVE",
    is_final: false, registered_by_name: "x", registered_at: "2026-10-01T00:00:00Z", row_version: 1, label: null,
    eval_score: null, final_loss: null, min_loss: null, min_loss_epoch: null, loss_curve: null, curve_points: 0, dataset_id: null,
    ...p,
  }) as Model;

afterEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* 무시 */
  }
});

describe("compare.ts 순수 함수 (V3-S2-2)", () => {
  it("bestIndices: 낮을수록·높을수록·동률·값 1개·null 섞임", () => {
    expect(bestIndices([3, 1, 2], "lower")).toEqual([1]);
    expect(bestIndices([3, 1, 2], "higher")).toEqual([0]);
    expect(bestIndices([1, 2, 1], "lower")).toEqual([0, 2]);
    expect(bestIndices([null, 5, null], "lower")).toEqual([]);
    expect(bestIndices([5], "higher")).toEqual([]);
    expect(bestIndices([null, 4, undefined, 2, NaN], "lower")).toEqual([3]);
    expect(bestIndices([null, 4, undefined, 2], "higher")).toEqual([1]);
    expect(bestIndices([], "lower")).toEqual([]);
  });

  it("metricRows: loss 두 행 뒤 metrics 합집합 사전순, 값 없음 null, UNRECOGNIZED·평가 전은 값 없음", () => {
    const a = mk({ id: "a", final_loss: 0.5, min_loss: 0.4, eval_score: { status: "PARSED", metrics: { R2: 0.9, MAE: 1 }, score_rel: "" } });
    const b = mk({ id: "b", final_loss: 0.7, eval_score: { status: "PARSED", metrics: { RMSE: 2, MAE: 1.5 }, score_rel: "" } });
    const c = mk({ id: "c", eval_score: { status: "UNRECOGNIZED", metrics: { ZZZ: 1 }, score_rel: "" } });
    const d = mk({ id: "d", eval_status: "NONE", eval_score: { status: "PARSED", metrics: { OLD: 1 }, score_rel: "" } });
    const rows = metricRows([a, b, c, d, null]);
    expect(rows.map((r) => r.key)).toEqual(["final_loss", "min_loss", "MAE", "R2", "RMSE"]);
    expect(rows.map((r) => r.kind)).toEqual(["loss", "loss", "metric", "metric", "metric"]);
    expect(rows[0].values).toEqual([0.5, 0.7, null, null, null]);
    expect(rows[1].values).toEqual([0.4, null, null, null, null]);
    expect(rows[2].values).toEqual([1, 1.5, null, null, null]);
    expect(rows[4].values).toEqual([null, 2, null, null, null]);
  });

  it("seriesFor·canUseLog·distinctDatasetIds·toggleSelection", () => {
    const a = mk({ id: "a", name: "TNS", version: 2, label: "lr", loss_curve: [[1, 2], [2, 1], [3, 1.5]], dataset_id: "ds-1" });
    const b = mk({ id: "b", dataset_id: "ds-2" });
    const c = mk({ id: "c", loss_curve: [[1, 1], [2, 0]], dataset_id: "ds-1" });
    const s = seriesFor([a, b, null, c]);
    expect(s[0]).toMatchObject({ id: "a", name: "TNS v2 (lr)", color: 1, min: { x: 2, y: 1 } });
    expect(s[1]).toMatchObject({ id: "b", color: 2, pts: [], min: null });
    expect(s[2]).toBeNull();
    expect(s[3]!.color).toBe(4);
    expect(canUseLog([a, b, null])).toBe(true);
    expect(canUseLog([a, c])).toBe(false);
    expect(distinctDatasetIds([a, b, c, null])).toEqual(["ds-1", "ds-2"]);
    expect(toggleSelection(["1", "2"], "1")).toEqual(["2"]);
    expect(toggleSelection(["1", "2", "3", "4", "5"], "6")).toEqual(["1", "2", "3", "4", "5"]);
    expect(toggleSelection(["2"], "1")).toEqual(["2", "1"]);
    expect(epochText({ last_epoch: 1180, epochs_total: 1200 })).toBe("1180/1200");
  });

  it("지표 방향은 이름별로 기억(기본 낮을수록)", () => {
    expect(loadDirection("R2")).toBe("lower");
    saveDirection("R2", "higher");
    expect(loadDirection("R2")).toBe("higher");
    expect(localStorage.getItem("physicsai.metricDirection.R2")).toBe("higher");
  });
});

describe("목 데이터 (V3-S2-5)", () => {
  it("metrics 키가 다른 모델 3개와 곡선 없는 모델이 있다", () => {
    const ms = seedModels();
    const sets = new Set(ms.filter((m) => m.eval_score?.status === "PARSED").map((m) => Object.keys(m.eval_score!.metrics).sort().join(",")));
    expect(sets.size).toBeGreaterThanOrEqual(3);
    expect(ms.some((m) => (m.curve_points ?? 0) === 0)).toBe(true);
    expect(ms.slice(0, 3).map((m) => m.id)).toEqual(["m-1", "m-2", "m-3"]);
  });
});

async function openCard() {
  const r = renderApp(`${STUDY}/3`, { user: "power" });
  const card = await screen.findByRole("region", { name: "평가 · Final 지정" });
  await within(card).findByLabelText("cushion_TNS v1 비교 선택");
  return { ...r, card };
}
const box = (card: HTMLElement, name: string) => within(card).getByLabelText(`${name} 비교 선택`) as HTMLInputElement;
const cmpBtn = (card: HTMLElement) => within(card).getByRole("button", { name: /^선택 비교/ }) as HTMLButtonElement;

describe("③-5 모델 비교 화면", () => {
  it("V3-S2-1: 선택 2~5 제약, 열 때 모델 수 + 데이터셋 수만큼만 조회", async () => {
    const { card, server } = await openCard();
    expect(cmpBtn(card).disabled).toBe(true);
    fireEvent.click(box(card, "cushion_TNS v1"));
    expect(cmpBtn(card).textContent).toBe("선택 비교 (1)");
    expect(cmpBtn(card).disabled).toBe(true);
    expect(cmpBtn(card).title).toBe("2개 이상 선택하세요");
    for (const n of ["cushion_TNS v2", "cushion_GNN v1", "cushion_TNS v3", "cushion_MLP v1"]) fireEvent.click(box(card, n));
    expect(cmpBtn(card).textContent).toBe("선택 비교 (5)");

    const calls = recordCalls(server);
    fireEvent.click(cmpBtn(card));
    const panel = await within(card).findByRole("region", { name: "모델 비교" });
    await within(panel).findByText(/ds-0a7c4 학습 162/);
    await waitFor(() => expect(within(panel).queryByText("불러오는 중…")).toBeNull());
    const gets = calls.filter((x) => x.startsWith("GET /models/") || x.startsWith("GET /datasets/"));
    expect(gets.filter((x) => x.startsWith("GET /models/")).sort()).toEqual(["GET /models/m-1", "GET /models/m-2", "GET /models/m-3", "GET /models/m-4", "GET /models/m-5"]);
    expect(gets.filter((x) => x.startsWith("GET /datasets/")).sort()).toEqual(["GET /datasets/ds-0a7c41e2", "GET /datasets/ds-2"]);
  });

  it("6번째 체크박스는 비활성 + 안내, INVALID 모델은 선택 불가", async () => {
    const r = renderApp(`${STUDY}/3`, { user: "power" }, (s) => {
      s.models.push({ ...s.models[0], id: "m-6", name: "cushion_X", version: 1, is_final: false });
      s.models.push({ ...s.models[0], id: "m-7", name: "cushion_BAD", version: 1, is_final: false, status: "INVALID" });
    });
    const card = await screen.findByRole("region", { name: "평가 · Final 지정" });
    await within(card).findByLabelText("cushion_X v1 비교 선택");
    expect(box(card, "cushion_BAD v1").disabled).toBe(true);
    for (const n of ["cushion_TNS v1", "cushion_TNS v2", "cushion_GNN v1", "cushion_TNS v3", "cushion_MLP v1"]) fireEvent.click(box(card, n));
    expect(box(card, "cushion_X v1").disabled).toBe(true);
    expect(box(card, "cushion_X v1").title).toBe("최대 5개까지 비교할 수 있습니다");
    fireEvent.click(box(card, "cushion_MLP v1"));
    expect(box(card, "cushion_X v1").disabled).toBe(false);
    fireEvent.click(within(card).getByRole("button", { name: "선택 지우기" }));
    expect(cmpBtn(card).textContent).toBe("선택 비교 (0)");
    void r;
  });

  it("V3-S2-3·4: 로그 토글, 곡선 없음 범례, 점수 표 강조·방향, 데이터셋 경고, Final 지정", async () => {
    const { card, server } = await openCard();
    for (const n of ["cushion_TNS v2", "cushion_TNS v3", "cushion_GNN v1"]) fireEvent.click(box(card, n));
    fireEvent.click(cmpBtn(card));
    const panel = await within(card).findByRole("region", { name: "모델 비교" });
    await waitFor(() => expect(within(panel).queryByText("불러오는 중…")).toBeNull());

    // 로그 기본 켬, 곡선 없는 모델 범례
    const log = within(panel).getByLabelText("로그 스케일") as HTMLInputElement;
    expect(log.checked).toBe(true);
    expect(log.disabled).toBe(false);
    const legend = within(panel).getByRole("list", { name: "범례" });
    expect(within(legend).getByText(/곡선 없음\(로그 없음\/형식 미확인\)/).closest("li")!.textContent).toContain("cushion_GNN v1");
    expect(within(legend).getByText("cushion_TNS v2 (lr 1e-4, 2000ep)")).toBeTruthy();
    expect(within(panel).getByRole("img", { name: "loss 곡선 비교" })).toBeTruthy();

    // 데이터셋 다름 경고
    expect(within(panel).getByText("평가 데이터셋이 서로 다릅니다 — 점수를 직접 비교하기 어렵습니다")).toBeTruthy();

    // 점수 표: 행 순서, 평가 전 열 머리, 최고 강조
    const table = within(panel).getByRole("table", { name: "모델 비교 점수" });
    const rowHeads = within(table).getAllByRole("rowheader").map((h) => h.firstChild!.textContent);
    expect(rowHeads).toEqual(["최종 loss", "최소 loss", "MAE", "R2", "RMSE"]);
    expect(within(table).getByText("평가 전")).toBeTruthy();
    // MAE: 낮을수록 기본 → v2(1.52) 최고
    expect(within(table).getByLabelText("MAE cushion_TNS v2 1.52 (최고)").className).toContain("best");
    // R2: 기본 낮을수록 → v3(0.948), 방향 바꾸면 v2(0.971)
    expect(within(table).getByLabelText("R2 cushion_TNS v3 0.948 (최고)")).toBeTruthy();
    fireEvent.click(within(table).getByRole("button", { name: "R2 좋은 방향: ↓ 낮을수록" }));
    expect(within(table).getByLabelText("R2 cushion_TNS v2 0.971 (최고)")).toBeTruthy();
    expect(within(table).getByLabelText("R2 cushion_TNS v3 0.948")).toBeTruthy();
    expect(localStorage.getItem("physicsai.metricDirection.R2")).toBe("higher");
    // 값이 1개뿐인 RMSE 행은 강조 없음
    expect(within(table).getByLabelText("RMSE cushion_TNS v3 2.71")).toBeTruthy();

    // 메타
    const meta = within(panel).getByRole("table", { name: "모델 메타" });
    expect(within(meta).getByText("2000/2000")).toBeTruthy();
    expect(within(meta).getAllByText("ds-2 학습 216 · 평가 24")).toHaveLength(2);
    expect(within(meta).getByText("ds-0a7c4 학습 162 · 평가 18")).toBeTruthy();

    // Final 지정(열 머리) → PUT 1회, 배지 이동, 패널 유지
    const calls = recordCalls(server);
    const v2Head = within(table).getAllByRole("columnheader").find((h) => h.textContent?.includes("cushion_TNS v2"))!;
    fireEvent.click(within(v2Head).getByRole("button", { name: "Final 지정" }));
    await waitFor(() => expect(within(v2Head).getByText("Final")).toBeTruthy());
    expect(calls.filter((c) => c === "PUT /studies/s-cushion/final-model")).toHaveLength(1);
    expect(server.studies.find((s) => s.id === "s-cushion")!.final_model_id).toBe("m-2");
    expect(within(card).getByRole("region", { name: "모델 비교" })).toBeTruthy();

    fireEvent.click(within(panel).getByRole("button", { name: "닫기" }));
    expect(within(card).queryByRole("region", { name: "모델 비교" })).toBeNull();
  });

  it("0 이하 loss가 있으면 로그 토글 비활성, 404 모델은 열에 문구", async () => {
    const { card, server } = await openCard();
    const m2 = server.models.find((m) => m.id === "m-2")!;
    m2.loss_curve = [...m2.loss_curve!, [2001, 0]];
    for (const n of ["cushion_TNS v1", "cushion_TNS v2", "cushion_MLP v1"]) fireEvent.click(box(card, n));
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) => (m === "GET" && p === "/models/m-5" ? orig(m, "/models/none", q, b, h) : orig(m, p, q, b, h));
    fireEvent.click(cmpBtn(card));
    const panel = await within(card).findByRole("region", { name: "모델 비교" });
    await waitFor(() => expect(within(within(panel).getByRole("table", { name: "모델 비교 점수" })).getByText("모델을 찾을 수 없습니다")).toBeTruthy());
    const log = within(panel).getByLabelText("로그 스케일") as HTMLInputElement;
    expect(log.disabled).toBe(true);
    expect(log.checked).toBe(false);
    expect(within(panel).getByText("0 이하 loss가 있어 선형 축으로 표시")).toBeTruthy();
  });
});
