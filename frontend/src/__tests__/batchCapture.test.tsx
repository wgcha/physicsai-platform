// D3-53: B 일괄 예측 설정 "컨투어 캡처"·방향·"영상 포함" → PREDICT_BATCH params.capture(기본과 같으면 키 없음), 예상 참고 1줄.
import { afterEach, describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { captureEstimate, captureParam } from "../stages/stage4/batch/BatchCaptureOptions";

const KEY = "physicsai.stage4.inputMode";

function record(server: MockServer, re: RegExp, method = "POST") {
  const bodies: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === method && re.test(p)) bodies.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return bodies;
}

async function ready(count = "3") {
  localStorage.setItem(KEY, "batch");
  const r = renderApp(`${STUDY}/4`, { user: "power" });
  const jobs = record(r.server, /\/studies\/[^/]+\/jobs$/);
  const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
  fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: count } });
  fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
  await screen.findByRole("table", { name: "조합 미리보기" });
  const run = screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement;
  await waitFor(() => expect(run.disabled).toBe(false));
  return { ...r, jobs, run };
}

describe("B 컨투어 캡처 옵션 (D3-53)", () => {
  afterEach(() => localStorage.clear());

  it("기본: 캡처·영상 켬, 방향 = 기본 4개, 참고 1줄 → 바꾸지 않으면 params에 capture 없음", async () => {
    const { jobs, run } = await ready("3");
    const box = screen.getByTestId("batch-capture");
    expect((within(box).getByRole("checkbox", { name: "컨투어 캡처" }) as HTMLInputElement).checked).toBe(true);
    expect((within(box).getByRole("checkbox", { name: "영상 포함" }) as HTMLInputElement).checked).toBe(true);
    const views = within(within(box).getByRole("group", { name: "캡처 방향" })).getAllByRole("checkbox") as HTMLInputElement[];
    expect(views.filter((v) => v.checked)).toHaveLength(4);
    expect(within(box).getByText(/캡처 예상: run 3 × 방향 4 = 이미지 12장 \+ 영상 12개/)).toBeTruthy();
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect("capture" in (jobs[0].params as Record<string, unknown>)).toBe(false);
  });

  it("방향·영상 바꾸면 params.capture{enabled, views, video}, 하위 결과는 그 방향만", async () => {
    const { server, jobs, run } = await ready("2");
    const box = screen.getByTestId("batch-capture");
    fireEvent.click(within(box).getByRole("checkbox", { name: "정면" }));
    fireEvent.click(within(box).getByRole("checkbox", { name: "오른쪽" }));
    fireEvent.click(within(box).getByRole("checkbox", { name: "영상 포함" }));
    expect(within(box).getByText(/run 2 × 방향 2 = 이미지 4장 ·/)).toBeTruthy();
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect((jobs[0].params as Record<string, unknown>).capture).toEqual({ enabled: true, views: ["iso", "top"], video: false });
    act(() => server.finishAll());
    const b = server.batches[0];
    const kid = server.jobs.find((j) => j.id === b.runs[0].predict_job_id)!;
    expect(((kid.result as { media: { view: string }[] }).media).map((m) => m.view)).toEqual(["iso", "top"]);
  });

  it("방향을 모두 끄면 실행 불가, 캡처를 끄면 {enabled:false}·방향 목록 숨김·하위 캡처 없음", async () => {
    const { server, jobs, run } = await ready("2");
    const box = screen.getByTestId("batch-capture");
    for (const name of ["등각(iso)", "정면", "윗면", "오른쪽"]) fireEvent.click(within(box).getByRole("checkbox", { name }));
    await waitFor(() => expect(run.disabled).toBe(true));
    fireEvent.click(within(box).getByRole("checkbox", { name: "컨투어 캡처" }));
    expect(within(box).queryByRole("group", { name: "캡처 방향" })).toBeNull();
    expect(within(box).queryByText(/캡처 예상/)).toBeNull();
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect((jobs[0].params as Record<string, unknown>).capture).toEqual({ enabled: false });
    act(() => server.finishAll());
    const kid = server.jobs.find((j) => j.id === server.batches[0].runs[0].predict_job_id)!;
    expect((kid.result as { media: unknown[] }).media).toEqual([]);
  });

  it("captureParam·captureEstimate", () => {
    const d = ["iso", "front"];
    expect(captureParam({ enabled: true, views: d, video: true }, d, true)).toBeUndefined();
    expect(captureParam({ enabled: true, views: d, video: false }, d, true)).toEqual({ enabled: true, video: false });
    expect(captureParam({ enabled: true, views: ["iso"], video: true }, d, true)).toEqual({ enabled: true, views: ["iso"] });
    expect(captureParam({ enabled: false, views: d, video: true }, d, true)).toEqual({ enabled: false });
    expect(captureEstimate(10, { enabled: true, views: d, video: false })).toBe("캡처 예상: run 10 × 방향 2 = 이미지 20장 · 디스크 약 6 MB · 시간 약 7분 추가(가정값 기준 참고)");
  });
});
