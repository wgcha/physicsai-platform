// S10 컨투어 캡처 화면: 방향 전환(버튼·←→ 키), 영상 토글(<video controls>), B 결과에서 run을 바꿔도 방향 유지·캡처 표시,
// 상태 문구 4종(없음·일부·실패·꺼짐), 다시 캡처 요청 body(power만), 템플릿 표시 설정 PUT body, B 설정 범례 고정 params. 목 서버(mock/capture.ts) 기준.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { MEDIA_TEXT, mediaHref } from "../stages/stage4/ContourMedia";
import type { CaptureMode } from "../mock/capture";
import { encodePng } from "../mock/png";

const KEY = "physicsai.stage4.inputMode";
const BATCH = `${STUDY}/4/batch/pb-2`;

function record(server: MockServer, re: RegExp, method = "POST") {
  const bodies: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === method && re.test(p)) bodies.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return bodies;
}
const viewButtons = (root: HTMLElement) => within(within(root).getByRole("group", { name: "방향" })).getAllByRole("button");
const pressed = (root: HTMLElement) => viewButtons(root).find((b) => b.getAttribute("aria-pressed") === "true")?.textContent;
const media = () => screen.findByTestId("contour-media");

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("S10 컨투어 미디어 — 단일 예측 결과", () => {
  it("방향 목록(버튼 그룹) → 이미지 전환, ←→ 키로도 이동, 결과 목록은 아래 접힘", async () => {
    renderApp(`${STUDY}/4`, { user: "general" });
    const m = await media();
    await waitFor(() => expect(viewButtons(m).map((b) => b.textContent)).toEqual(["등각(iso)", "정면", "윗면", "오른쪽"]));
    expect(pressed(m)).toBe("등각(iso)");
    expect(await within(m).findByAltText("예측 컨투어 — 등각(iso)")).toBeTruthy();
    fireEvent.click(within(m).getByRole("button", { name: "윗면" }));
    expect(await within(m).findByAltText("예측 컨투어 — 윗면")).toBeTruthy();
    // 키보드: → 다음(오른쪽), → 처음으로 돌아감, End 끝
    const group = within(m).getByRole("group", { name: "방향" });
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(pressed(m)).toBe("오른쪽");
    expect(document.activeElement?.textContent).toBe("오른쪽");
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(pressed(m)).toBe("등각(iso)");
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    expect(pressed(m)).toBe("오른쪽");
    // 이미지 내려받기 링크 + 결과 목록(접힘)
    expect(within(m).getByRole("link", { name: "이미지 받기" }).getAttribute("download")).toBe("contour_j-pred_right.png");
    const list = screen.getByTestId("result-list");
    expect(list.tagName).toBe("DETAILS");
    expect((list as HTMLDetailsElement).open).toBe(false);
    expect(within(list).getByText("결과 목록")).toBeTruthy();
    // 일반 사용자: 다시 캡처 없음
    expect(within(m).queryByRole("button", { name: "다시 캡처" })).toBeNull();
  });

  it("영상 토글: 같은 방향의 <video controls>(aria-label·source), 영상 받기 링크, 끄면 이미지", async () => {
    renderApp(`${STUDY}/4`, { user: "general" });
    const m = await media();
    fireEvent.click(await within(m).findByRole("button", { name: "정면" }));
    const toggle = within(m).getByRole("button", { name: "영상" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    const video = within(m).getByLabelText("컨투어 영상 — 정면") as HTMLVideoElement;
    expect(video.tagName).toBe("VIDEO");
    expect(video.hasAttribute("controls")).toBe(true);
    const src = video.querySelector("source")!.getAttribute("src")!;
    expect(src).toMatch(/^\/physicsai\/api\/artifacts\/a-\d+\/content$/);
    expect(within(m).getByRole("link", { name: "영상 받기" }).getAttribute("href")).toBe(src);
    expect(within(m).queryByRole("img", { name: /예측 컨투어/ })).toBeNull();
    // 방향을 바꿔도 영상 모드 유지 → 그 방향 영상
    fireEvent.click(within(m).getByRole("button", { name: "윗면" }));
    expect(within(m).getByLabelText("컨투어 영상 — 윗면")).toBeTruthy();
    fireEvent.click(toggle);
    expect(await within(m).findByAltText("예측 컨투어 — 윗면")).toBeTruthy();
  });

  it.each<[CaptureMode, string, string | null]>([
    ["NONE", MEDIA_TEXT.NONE, null],
    ["PARTIAL", MEDIA_TEXT.PARTIAL, "right 방향 캡처 시간 초과 · top 동영상 없음"],
    ["FAILED", MEDIA_TEXT.FAILED, "HyperView 종료코드 3 — 작업 로그를 확인하세요"],
    ["DISABLED", MEDIA_TEXT.DISABLED, "관리자 설정에서 컨투어 캡처가 꺼져 있습니다(capture.enabled)"],
  ])("상태 문구: %s", async (capture, text, message) => {
    renderApp(`${STUDY}/4`, { user: "general", capture });
    const m = await media();
    const note = await within(m).findByTestId("media-status");
    expect(note.textContent).toBe(message ? `${text} — ${message}` : text);
    expect(note.className).toContain("muted");
    if (capture === "PARTIAL") {
      expect(viewButtons(m).map((b) => b.textContent)).toEqual(["등각(iso)", "정면", "윗면"]);
      fireEvent.click(within(m).getByRole("button", { name: "윗면" }));
      expect((within(m).getByRole("button", { name: "영상" }) as HTMLButtonElement).disabled).toBe(true); // top 영상 없음
      expect(await within(m).findByAltText("예측 컨투어 — 윗면")).toBeTruthy();
    } else {
      expect(within(m).queryByRole("group", { name: "방향" })).toBeNull();
      expect(within(m).queryByRole("img")).toBeNull();
    }
  });

  it("상태 OK(전체)면 상태 문구 없음", async () => {
    renderApp(`${STUDY}/4`, { user: "general" });
    const m = await media();
    await within(m).findByAltText("예측 컨투어 — 등각(iso)");
    expect(within(m).queryByTestId("media-status")).toBeNull();
  });

  it("다시 캡처(power): 방향 체크 → POST /jobs/{id}/capture {views} → 작업이 끝나면 새 방향 목록", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const bodies = record(server, /^\/jobs\/[^/]+\/capture$/);
    const m = await media();
    await within(m).findByAltText("예측 컨투어 — 등각(iso)");
    const open = within(m).getByRole("button", { name: "다시 캡처" });
    fireEvent.click(open);
    expect(open.getAttribute("aria-expanded")).toBe("true");
    // 기본 체크 = 템플릿 표시 설정 방향(iso·front·top·right)
    const box = (n: string) => within(m).getByRole("checkbox", { name: n }) as HTMLInputElement;
    expect(["등각(iso)", "정면", "뒷면", "윗면", "아랫면", "왼쪽", "오른쪽"].map((n) => box(n).checked)).toEqual([true, true, false, true, false, false, true]);
    fireEvent.click(box("오른쪽"));
    fireEvent.click(box("왼쪽"));
    fireEvent.click(within(m).getByRole("button", { name: "캡처 요청" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ views: ["iso", "front", "top", "left"] }); // 방향 순서는 고정 목록 순
    expect(await within(m).findByText("캡처 중…")).toBeTruthy();
    const cap = server.jobs.find((j) => j.job_type === "CONTOUR_CAPTURE")!;
    expect(cap.params).toMatchObject({ predict_job_id: "j-pred", views: ["iso", "front", "top", "left"] });
    act(() => server.finishAll());
    await waitFor(() => expect(viewButtons(m).map((b) => b.textContent)).toEqual(["등각(iso)", "정면", "윗면", "왼쪽"]));
    expect(within(m).queryByText("캡처 중…")).toBeNull();
  });

  it("다시 캡처: 방향을 모두 끄면 요청 버튼 비활성", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const m = await media();
    await within(m).findByAltText("예측 컨투어 — 등각(iso)");
    fireEvent.click(within(m).getByRole("button", { name: "다시 캡처" }));
    for (const n of ["등각(iso)", "정면", "윗면", "오른쪽"]) fireEvent.click(within(m).getByRole("checkbox", { name: n }));
    expect((within(m).getByRole("button", { name: "캡처 요청" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("S10 컨투어 미디어 — B 결과", () => {
  it("행 선택 → 오른쪽 DOE 칸에 그 run의 컨투어, 방향은 run을 바꿔도 유지, 미디어 있는 행에 캡처 표시", async () => {
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    // 캡처 표시: 완료 행만(실패 5·생성 실패 12 없음)
    expect(within(screen.getByTestId("row-7")).getByRole("img", { name: "캡처 4방향" })).toBeTruthy();
    expect(within(screen.getByTestId("row-5")).queryByTestId("capture-mark")).toBeNull();
    expect(within(screen.getByTestId("row-12")).queryByTestId("capture-mark")).toBeNull();
    expect(screen.getAllByTestId("capture-mark")).toHaveLength(18);

    fireEvent.click(await screen.findByRole("button", { name: "DOE #7 선택" }));
    let panel = await screen.findByRole("region", { name: "DOE #7" });
    await waitFor(() => expect(within(panel).getAllByRole("button", { name: "윗면" })).toHaveLength(1));
    fireEvent.click(within(panel).getByRole("button", { name: "윗면" }));
    expect(await within(panel).findByAltText("예측 컨투어 — 윗면")).toBeTruthy();
    const firstSrc = within(panel).getByRole("link", { name: "이미지 받기" }).getAttribute("download");
    expect(firstSrc).toMatch(/_top\.png$/);

    fireEvent.click(screen.getByRole("button", { name: "DOE #8 선택" }));
    panel = await screen.findByRole("region", { name: "DOE #8" });
    await waitFor(() => expect(pressed(panel)).toBe("윗면"));
    expect(await within(panel).findByAltText("예측 컨투어 — 윗면")).toBeTruthy();
    // 결과 목록은 접힘으로 아래 유지
    await waitFor(() => expect(within(panel).getByTestId("result-list").textContent).toContain("num_time_step: 5"));
    expect(within(panel).getByRole("button", { name: "다시 캡처" })).toBeTruthy();

    // 실패 run → 컨투어 대신 상태 안내, 다시 성공 run으로 오면 같은 방향
    fireEvent.click(screen.getByRole("button", { name: "DOE #5 선택" }));
    panel = await screen.findByRole("region", { name: "DOE #5" });
    expect(within(panel).queryByTestId("contour-media")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "DOE #9 선택" }));
    panel = await screen.findByRole("region", { name: "DOE #9" });
    await waitFor(() => expect(pressed(panel)).toBe("윗면"));
  });

  it("고른 방향이 그 run에 없으면 안내(선택은 유지)", async () => {
    renderApp(BATCH, { user: "general" }, (srv) => {
      // DOE #8은 iso만 캡처된 run으로
      const b = srv.batches.find((x) => x.id === "pb-2")!;
      const j = srv.jobs.find((x) => x.id === b.runs[7].predict_job_id)!;
      const r = j.result as { media: { view: string }[] };
      r.media = r.media.filter((x) => x.view === "iso");
    });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    fireEvent.click(await screen.findByRole("button", { name: "DOE #7 선택" }));
    let panel = await screen.findByRole("region", { name: "DOE #7" });
    fireEvent.click(await within(panel).findByRole("button", { name: "오른쪽" }));
    fireEvent.click(screen.getByRole("button", { name: "DOE #8 선택" }));
    panel = await screen.findByRole("region", { name: "DOE #8" });
    expect(await within(panel).findByText(`${MEDIA_TEXT.MISSING_VIEW} (오른쪽)`)).toBeTruthy();
    expect(within(screen.getByTestId("row-8")).getByRole("img", { name: "캡처 1방향" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "DOE #9 선택" }));
    panel = await screen.findByRole("region", { name: "DOE #9" });
    await waitFor(() => expect(pressed(panel)).toBe("오른쪽"));
  });
});

describe("S10 템플릿 컨투어 표시 설정·B 범례 고정", () => {
  it("템플릿 관리 '컨투어 표시': 결과 종류·성분(응답 후보 재사용)·평균·부품·범례 고정·방향 → PUT body", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const puts = record(server, /^\/param-sets\/[^/]+\/display$/, "PUT");
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const sec = await screen.findByTestId("contour-display");
    const field = within(sec).getByLabelText("결과 종류") as HTMLSelectElement;
    await waitFor(() => expect(Array.from(field.options).map((o) => o.value)).toEqual(["Stress", "Displacement"]));
    expect(field.value).toBe("Stress");
    fireEvent.change(field, { target: { value: "Displacement" } });
    const comp = within(sec).getByLabelText("성분") as HTMLSelectElement;
    expect(Array.from(comp.options).map((o) => o.value)).toEqual(["X", "Y", "Z", "Mag"]);
    fireEvent.change(comp, { target: { value: "Mag" } });
    fireEvent.change(within(sec).getByLabelText("평균 방식"), { target: { value: "advanced" } });
    expect((within(sec).getByLabelText("부품 이름 목록") as HTMLInputElement).value).toBe("CUSHION_TOP, FOAM");
    fireEvent.change(within(sec).getByLabelText("부품 이름 목록"), { target: { value: "CUSHION_TOP, RIB_1 ,, FOAM" } });
    expect((within(sec).getByLabelText("범례 최소") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(within(sec).getByRole("radio", { name: "고정" }));
    fireEvent.change(within(sec).getByLabelText("범례 최소"), { target: { value: "5" } });
    fireEvent.change(within(sec).getByLabelText("범례 최대"), { target: { value: "1" } });
    const views = within(sec).getByRole("group", { name: "캡처 방향" });
    fireEvent.click(within(views).getByRole("checkbox", { name: "오른쪽" }));
    fireEvent.click(within(views).getByRole("checkbox", { name: "왼쪽" }));
    const save = within(sec).getByRole("button", { name: "표시 설정 저장" });
    fireEvent.click(save);
    expect(within(sec).getByRole("alert").textContent).toBe("고정 범례는 최소 < 최대인 숫자");
    expect(puts).toHaveLength(0);
    fireEvent.change(within(sec).getByLabelText("범례 최대"), { target: { value: "250" } });
    fireEvent.click(save);
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({
      field: "Displacement",
      component: "Mag",
      avgmode: "advanced",
      comps: ["CUSHION_TOP", "RIB_1", "FOAM"],
      legend: { mode: "fixed", min: 5, max: 250 },
      views: ["iso", "front", "top", "left"],
    });
    expect(await within(sec).findByText(/저장했습니다/)).toBeTruthy();
    expect(server.paramSets.find((p) => p.id === "ps-1")!.display!.views).toEqual(["iso", "front", "top", "left"]);
  });

  it("템플릿 표시 설정: 일반 사용자에게는 템플릿 관리(표시 설정)가 없다", async () => {
    renderApp(`${STUDY}/4`, { user: "general" });
    await media();
    expect(screen.queryByRole("button", { name: "템플릿 관리" })).toBeNull();
    expect(screen.queryByTestId("contour-display")).toBeNull();
  });

  it("B 설정: '범례 범위 고정(run 비교용)' 체크 + min/max(선택) → PREDICT_BATCH params.display.legend, 끄면 키 없음", async () => {
    localStorage.setItem(KEY, "batch");
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const jobs = record(server, /\/studies\/[^/]+\/jobs$/);
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: "3" } });
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await screen.findByRole("table", { name: "조합 미리보기" });
    const run = screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    const fix = screen.getByRole("checkbox", { name: "범례 범위 고정(run 비교용)" }) as HTMLInputElement;
    expect(fix.checked).toBe(false);
    expect(screen.queryByLabelText("범례 최소")).toBeNull();
    fireEvent.click(fix);
    fireEvent.change(screen.getByLabelText("범례 최소"), { target: { value: "abc" } });
    await waitFor(() => expect(run.disabled).toBe(true));
    fireEvent.change(screen.getByLabelText("범례 최소"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("범례 최대"), { target: { value: "300" } });
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect((jobs[0].params as Record<string, unknown>).display).toEqual({ legend: { mode: "fixed", min: 0, max: 300 } });
  });

  it("B 설정: 범례 고정 min/max를 비우면 null(선택), 체크 안 하면 display 없음", async () => {
    localStorage.setItem(KEY, "batch");
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const jobs = record(server, /\/studies\/[^/]+\/jobs$/);
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await screen.findByRole("table", { name: "조합 미리보기" });
    const run = screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(screen.getByRole("checkbox", { name: "범례 범위 고정(run 비교용)" }));
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect((jobs[0].params as Record<string, unknown>).display).toEqual({ legend: { mode: "fixed", min: null, max: null } });
  });
});

describe("S10 목·도움 함수", () => {
  it("mediaHref: API 접두어 없으면 붙이고, 있으면 그대로", () => {
    expect(mediaHref("/physicsai/api/artifacts/a-1/content")).toBe("/physicsai/api/artifacts/a-1/content");
    expect(mediaHref("/artifacts/a-1/content")).toBe("/physicsai/api/artifacts/a-1/content");
    expect(mediaHref("artifacts/a-1/content")).toBe("/physicsai/api/artifacts/a-1/content");
  });

  it("목 PNG: 시그니처·IHDR 크기, 산출물 내용은 image/png 바이트(데이터 URL 아님)", async () => {
    const png = encodePng(3, 2, () => [255, 0, 0]);
    expect(Array.from(png.slice(0, 8))).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
    expect(Array.from(png.slice(16, 24))).toEqual([0, 0, 0, 3, 0, 0, 0, 2]);
    const { server } = renderApp(`${STUDY}/4`, { user: "general" });
    const m = server.handle("GET", "/jobs/j-pred/media", new URLSearchParams(), null, new Headers());
    const body = m.body as { status: string; views: { view: string; image_url: string; video_url: string | null; video_type: string | null }[] };
    expect(body.status).toBe("OK");
    expect(body.views.map((v) => v.view)).toEqual(["iso", "front", "top", "right"]);
    expect(body.views[0].video_type).toBe("image/png"); // 목: 동영상 대체 정적 PNG
    const r = server.handle("GET", body.views[0].image_url.replace("/physicsai/api", ""), new URLSearchParams(), null, new Headers());
    expect(r.contentType).toBe("image/png");
    expect(Array.from(r.bytes!.slice(1, 4))).toEqual([80, 78, 71]);
    // 다시 캡처: general은 403, 실행 중이 아닌 PREDICT만
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    expect(server.handle("POST", "/jobs/j-pred/capture", new URLSearchParams(), { views: ["iso"] }, h).status).toBe(403);
    server.user = "power";
    expect(server.handle("POST", "/jobs/j-pred/capture", new URLSearchParams(), { views: ["sideways"] }, h).status).toBe(422);
    expect(server.handle("POST", "/jobs/j-q1/capture", new URLSearchParams(), {}, h).status).toBe(409);
    expect(server.handle("POST", "/jobs/j-pred/capture", new URLSearchParams(), {}, h).status).toBe(202);
  });
});
