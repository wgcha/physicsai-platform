// phase3.md §12 S7(D3-46): 서버 경로 탐색 대화상자 — 진입·위로·루트 전환·선택 시 입력 채움, 확장자 필터, 마지막 위치 기억
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { BrowseButton } from "../components/BrowseButton";
import { PICKER_LAST_KEY, type PickMode } from "../components/PathPickerDialog";
import { MockServer, createMockFetch } from "../mock/server";
import { MOCK_IMPORT_ROOT, MOCK_INBOX, MOCK_SHARE_HINT } from "../mock/fs";
import { renderApp, STUDY } from "../test/render";

const AI = "E:\\shared\\AI_WORK";

function Host({ mode, exts, aiOnly }: { mode: PickMode; exts?: string[]; aiOnly?: boolean }) {
  const [v, setV] = useState("");
  return (
    <div>
      <input aria-label="경로" value={v} onChange={(e) => setV(e.target.value)} />
      <BrowseButton mode={mode} exts={exts} aiOnly={aiOnly} value={v} onPick={setV} />
    </div>
  );
}

function mount(props: { mode: PickMode; exts?: string[]; aiOnly?: boolean }, user: "power" | "general" = "power") {
  vi.stubGlobal("fetch", createMockFetch(new MockServer({ user })));
  render(<Host {...props} />);
}

const dialog = () => screen.findByRole("dialog");
const rowNames = (d: HTMLElement) => within(within(d).getByRole("listbox")).queryAllByRole("option").map((o) => o.querySelector(".picker-name")!.textContent);
const target = (d: HTMLElement) => within(d).getByTestId("picker-target").textContent;
const crumbs = (d: HTMLElement) => within(d).getByRole("navigation", { name: "현재 경로" }).textContent;

async function openPicker() {
  fireEvent.click(screen.getByRole("button", { name: "찾아보기" }));
  const d = await dialog();
  await waitFor(() => expect(within(d).queryAllByRole("option").length).toBeGreaterThan(0));
  return d;
}

describe("서버 경로 탐색 대화상자 (phase3 §12 S7)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("받은 파일 폴더에서 시작 → 폴더 진입 → 위로 → 루트 전환 → 선택하면 입력란에 절대경로", async () => {
    mount({ mode: "dir" });
    const d = await openPicker();
    // 처음엔 받은 파일(공유 폴더). 숨김·_backup·_platform 없음, 폴더 먼저
    expect(crumbs(d)).toContain("받은 파일(공유 폴더)");
    expect(rowNames(d)).toEqual(["case_B", "from_pc2.hm", "readme.txt"]);
    expect(within(d).getByTestId("picker-share-hint").textContent).toContain(MOCK_SHARE_HINT);
    expect(target(d)).toBe(MOCK_INBOX); // 아무것도 고르지 않으면 현재 폴더
    // 폴더 더블클릭 진입
    fireEvent.doubleClick(within(d).getByRole("option", { name: /case_B/ }));
    await waitFor(() => expect(rowNames(d)).toEqual(["mesh.inc", "Side_Drop_0000.rad", "Side_Drop_0001.rad"]));
    expect(crumbs(d)).toContain("case_B");
    // 위로 → 받은 파일 → 위로 → AI 루트(루트 위로는 못 감)
    fireEvent.click(within(d).getByRole("button", { name: /위로/ }));
    await waitFor(() => expect(rowNames(d)).toContain("case_B"));
    fireEvent.click(within(d).getByRole("button", { name: /위로/ }));
    await waitFor(() => expect(rowNames(d)).toEqual(["cushion", "inbox"]));
    expect(within(d).getByRole("button", { name: "AI 루트" }).getAttribute("aria-pressed")).toBe("true");
    expect((within(d).getByRole("button", { name: /위로/ }) as HTMLButtonElement).disabled).toBe(true);
    // 루트 전환
    fireEvent.click(within(d).getByRole("button", { name: "추가 허용 폴더" }));
    await waitFor(() => expect(rowNames(d)).toEqual(["model_v4"]));
    fireEvent.click(within(d).getByRole("option", { name: /model_v4/ }));
    expect(target(d)).toBe(`${MOCK_IMPORT_ROOT}\\model_v4`);
    fireEvent.click(within(d).getByRole("button", { name: "선택" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((screen.getByLabelText("경로") as HTMLInputElement).value).toBe(`${MOCK_IMPORT_ROOT}\\model_v4`);
    expect(localStorage.getItem(PICKER_LAST_KEY)).toBe(MOCK_IMPORT_ROOT);
  });

  it("파일 모드 + 확장자 필터: 폴더는 항상, 파일은 그 확장자만. 파일 더블클릭으로 바로 선택. 다시 열면 마지막 위치", async () => {
    mount({ mode: "dir_or_file", exts: [".rad", ".hm"] });
    let d = await openPicker();
    expect(rowNames(d)).toEqual(["case_B", "from_pc2.hm"]);
    fireEvent.doubleClick(within(d).getByRole("option", { name: /from_pc2\.hm/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((screen.getByLabelText("경로") as HTMLInputElement).value).toBe(`${MOCK_INBOX}\\from_pc2.hm`);
    // 입력란 값(파일)의 폴더에서 다시 연다
    d = await openPicker();
    expect(crumbs(d)).toContain("받은 파일(공유 폴더)");
    fireEvent.click(within(d).getByRole("button", { name: "취소" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("file 모드는 파일을 고르기 전에는 선택 비활성, Esc로 닫힘", async () => {
    mount({ mode: "file" });
    const d = await openPicker();
    const choose = within(d).getByRole("button", { name: "선택" }) as HTMLButtonElement;
    expect(choose.disabled).toBe(true);
    fireEvent.click(within(d).getByRole("option", { name: /case_B/ }));
    expect(choose.disabled).toBe(true);
    fireEvent.click(within(d).getByRole("option", { name: /readme\.txt/ }));
    expect(choose.disabled).toBe(false);
    fireEvent.keyDown(d, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("AI 루트 전용 용도는 추가 허용 폴더를 숨긴다. localStorage가 막혀도 동작", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    mount({ mode: "dir", aiOnly: true });
    const d = await openPicker();
    expect(within(d).queryByRole("button", { name: "추가 허용 폴더" })).toBeNull();
    expect(within(d).getByRole("button", { name: "AI 루트" })).toBeTruthy();
    fireEvent.click(within(d).getByRole("button", { name: "선택" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((screen.getByLabelText("경로") as HTMLInputElement).value).toBe(MOCK_INBOX);
  });

  it("거부된 경로(루트 밖)는 오류만 보이고 목록은 유지", async () => {
    mount({ mode: "dir" });
    const d = await openPicker();
    const srvFetch = globalThis.fetch;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/fs/list") ? srvFetch(String(input).replace(/path=[^&]+/, "path=C%3A%5Cwindows"), init) : srvFetch(input, init),
    );
    fireEvent.doubleClick(within(d).getByRole("option", { name: /case_B/ }));
    expect((await within(d).findByRole("alert")).textContent).toContain("허용된 루트");
    expect(rowNames(d)).toContain("case_B");
  });
});

describe("경로 입력란의 찾아보기 적용", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("③-4 모델 등록: 찾아보기로 폴더를 고르면 입력란이 채워진다", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const input = (await screen.findByLabelText("모델 폴더 경로 (.psmdl·로그, .pscfg는 선택)")) as HTMLInputElement;
    const row = input.closest(".pathinput-row") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "찾아보기" }));
    const d = await dialog();
    await waitFor(() => expect(rowNames(d).length).toBeGreaterThan(0));
    fireEvent.click(within(d).getByRole("button", { name: "추가 허용 폴더" }));
    await waitFor(() => expect(rowNames(d)).toEqual(["model_v4"]));
    fireEvent.doubleClick(within(d).getByRole("option", { name: /model_v4/ }));
    await waitFor(() => expect(rowNames(d)).toEqual(["cushion_TNS.psmdl", "train.log"]));
    fireEvent.click(within(d).getByRole("button", { name: "선택" }));
    await waitFor(() => expect(input.value).toBe(`${MOCK_IMPORT_ROOT}\\model_v4`));
  });

  it("③ 데이터셋 입력(h3d 폴더)은 AI 루트 전용 — 추가 허용 폴더 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    // ② 큐레이션 결과가 있으면 그것이 기본 — "다른 폴더 지정"으로 경로 입력을 연다
    fireEvent.click(await screen.findByRole("button", { name: "다른 폴더 지정" }));
    const input = (await screen.findByLabelText("h3d 폴더 경로 (AI 루트 하위)")) as HTMLInputElement;
    fireEvent.click(within(input.closest(".pathinput-row") as HTMLElement).getByRole("button", { name: "찾아보기" }));
    const d = await dialog();
    await waitFor(() => expect(rowNames(d).length).toBeGreaterThan(0));
    expect(within(d).queryByRole("button", { name: "추가 허용 폴더" })).toBeNull();
    fireEvent.click(within(d).getByRole("button", { name: "AI 루트" }));
    await waitFor(() => expect(rowNames(d)).toEqual(["cushion", "inbox"]));
    fireEvent.doubleClick(within(d).getByRole("option", { name: /cushion/ }));
    await waitFor(() => expect(rowNames(d)).toEqual(["00_inbox", "03_model"]));
    fireEvent.doubleClick(within(d).getByRole("option", { name: /00_inbox/ }));
    await waitFor(() => expect(rowNames(d)).toContain("h3d"));
    fireEvent.click(within(d).getByRole("option", { name: /^h3d/ }));
    fireEvent.click(within(d).getByRole("button", { name: "선택" }));
    await waitFor(() => expect(input.value).toBe(`${AI}\\cushion\\00_inbox\\h3d`));
  });

  it("조회 전용 사용자는 찾아보기 비활성", async () => {
    renderApp(`${STUDY}/3`, { user: "general" });
    const input = (await screen.findByLabelText("모델 폴더 경로 (.psmdl·로그, .pscfg는 선택)")) as HTMLInputElement;
    const btn = within(input.closest(".pathinput-row") as HTMLElement).getByRole("button", { name: "찾아보기" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
