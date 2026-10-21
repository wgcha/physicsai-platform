// upload-report.md §3.2·§13.1(V-UP-10·12): 경로 칸 두 탭 — 꺼짐이면 숨김, 미리 검사(제외·이름 위반 시 올리기 비활성), 진행·취소·이어 올리기,
// 완료 후 경로 칸 채움 + inspect 요약(기존 확인 표시와 같음), inspect 실패 시 파일 추가 후 재확인, 이탈 경고. 목 서버(mock/uploads.ts) 기준.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import { err } from "../mock/route";
import { resetUploadConfig } from "../components/upload/useUploadConfig";
import { PATH_SOURCE_KEY } from "../components/upload/PathSourceTabs";
import { RENAME_HINT } from "../components/upload/UploadTab";
import type { MockOptions } from "../mock/server";

const mkFile = (name: string, text = "x", rel?: string) => {
  const f = new File([text], name);
  if (rel) Object.defineProperty(f, "webkitRelativePath", { value: rel });
  return f;
};
const O: MockOptions = { user: "power", upload: true };

async function openModelCard(opts: MockOptions = O) {
  const utils = renderApp(`${STUDY}/3`, opts);
  const card = await screen.findByRole("region", { name: "모델 등록" });
  return { ...utils, card };
}
const pickFolder = (card: HTMLElement, files: File[]) => fireEvent.change(within(card).getByLabelText("올릴 폴더"), { target: { files } });
const upBtn = (card: HTMLElement, name = "올리기") => within(card).getByRole("button", { name }) as HTMLButtonElement;
const pathBox = (card: HTMLElement) => within(card).getByLabelText(/모델 폴더 경로/) as HTMLInputElement;
const GOOD = () => [mkFile("train_v3.psmdl", "model-bytes", "model_v3/train_v3.psmdl"), mkFile("train.log", "log", "model_v3/train.log")];

describe("경로 칸 두 탭: 내 PC에서 올리기 | 서버 경로 (V-UP-10·12)", () => {
  beforeEach(() => {
    localStorage.clear();
    resetUploadConfig();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("업로드 꺼짐(config.enabled=false·기본 목)이면 탭을 숨기고 지금과 같은 서버 경로 입력만", async () => {
    const quiet = async (card: HTMLElement) => {
      await new Promise((r) => setTimeout(r, 40)); // config 응답이 도착할 시간
      expect(within(card).queryByRole("tablist", { name: "입력 위치" })).toBeNull();
      expect(within(card).queryByTestId("upload-tab")).toBeNull();
      expect(within(card).getByRole("textbox", { name: /모델 폴더 경로/ })).toBeTruthy();
    };
    const a = await openModelCard({ user: "power" }); // 목 기본 = 꺼짐
    await quiet(a.card);
    a.unmount();
    resetUploadConfig();
    renderApp(`${STUDY}/3`, O, (s) => (s.up.enabled = false)); // 설정 null/점검 실패 = enabled=false
    await quiet(await screen.findByRole("region", { name: "모델 등록" }));
  });

  it("실행 권한이 없으면(general) 켜져 있어도 탭 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "general", upload: true });
    const card = await screen.findByRole("region", { name: "모델 등록" });
    await new Promise((r) => setTimeout(r, 40));
    expect(within(card).queryByRole("tablist", { name: "입력 위치" })).toBeNull();
  });

  it("처음엔 '내 PC에서 올리기', 고른 탭은 localStorage(pai.pathSource)에 기억", async () => {
    const { card, unmount } = await openModelCard();
    const tabs = await within(card).findByRole("tablist", { name: "입력 위치" });
    expect(within(tabs).getByRole("tab", { name: "내 PC에서 올리기" }).getAttribute("aria-selected")).toBe("true");
    expect(within(card).getByTestId("upload-tab").closest("[hidden]")).toBeNull();
    fireEvent.click(within(tabs).getByRole("tab", { name: "서버 경로" }));
    expect(localStorage.getItem(PATH_SOURCE_KEY)).toBe("server");
    expect(pathBox(card)).toBeTruthy();
    unmount();
    resetUploadConfig();
    const again = await openModelCard();
    const t2 = await within(again.card).findByRole("tablist", { name: "입력 위치" });
    expect(within(t2).getByRole("tab", { name: "서버 경로" }).getAttribute("aria-selected")).toBe("true");
  });

  it("폴더를 올리면 청크 PUT → complete → 경로 칸에 path 가 채워지고 서버 경로 탭에서 기존 확인 요약(psmdl·로그)이 보인다", async () => {
    const { card, server } = await openModelCard();
    const calls = recordCalls(server);
    await within(card).findByTestId("upload-tab");
    pickFolder(card, GOOD());
    expect((await within(card).findByTestId("upload-summary")).textContent).toContain("올릴 파일 2개");
    fireEvent.click(upBtn(card));
    await waitFor(() => expect(pathBox(card).value).toMatch(/AI_WORK\\uploads\\.+_model_v3$/));
    expect(server.up.items[0]).toMatchObject({ state: "COMPLETED", purpose: "MODEL_FOLDER", name: "model_v3" });
    expect(server.up.items[0].files.map((f) => f.rel)).toEqual(["train_v3.psmdl", "train.log"]); // 선택 폴더 기준 rel
    expect(calls.filter((c) => c.startsWith("PUT ")).length).toBe(2);
    expect(within(card).getByRole("tab", { name: "서버 경로" }).getAttribute("aria-selected")).toBe("true");
    expect(within(card).getByText(/model_v3\.psmdl/)).toBeTruthy(); // 기존 renderSummary(psmdl 목록)
    expect(upBtn(card, "모델 등록")).toBeTruthy();
  });

  it("미리 검사: 이름 규칙 위반(공백·괄호)이 하나라도 있으면 목록을 보이고 올리기 비활성, 네트워크 요청 없음", async () => {
    const { card, server } = await openModelCard();
    const calls = recordCalls(server);
    await within(card).findByTestId("upload-tab");
    pickFolder(card, [mkFile("ok.psmdl", "a", "m/ok.psmdl"), mkFile("model (1).psmdl", "a", "m/model (1).psmdl"), mkFile("my log.log", "a", "m/sub/my log.log")]);
    const bad = await within(card).findByTestId("upload-bad");
    expect(bad.textContent).toContain("이름 규칙 위반 2개");
    expect(bad.textContent).toContain("model (1).psmdl");
    expect(bad.textContent).toContain("공백");
    expect(bad.textContent).toContain(RENAME_HINT);
    expect(upBtn(card).disabled).toBe(true);
    expect(within(card).getByTestId("upload-start-reason").textContent).toBe(RENAME_HINT);
    fireEvent.click(upBtn(card));
    expect(calls.filter((c) => /uploads/.test(c) && c !== "GET /uploads/config")).toEqual([]);
  });

  it("패턴 밖·pscfg 는 '제외'로 접어 보여 주고(위반 아님) 나머지만 올린다", async () => {
    const { card, server } = await openModelCard();
    await within(card).findByTestId("upload-tab");
    pickFolder(card, [mkFile("a.psmdl", "1", "m/a.psmdl"), mkFile("a.pscfg", "1", "m/a.pscfg"), mkFile("readme.docx", "1", "m/readme.docx")]);
    const ex = await within(card).findByTestId("upload-excluded");
    expect(ex.textContent).toContain("제외 2개");
    expect(ex.textContent).toContain("pscfg(pickle)");
    expect(within(card).queryByTestId("upload-bad")).toBeNull();
    fireEvent.click(upBtn(card));
    await waitFor(() => expect(server.up.items[0]?.state).toBe("COMPLETED"));
    expect(server.up.items[0].files.map((f) => f.rel)).toEqual(["a.psmdl"]);
  });

  it("업로드 실패 → '이어 올리기'(같은 세션) → 완료, 오류 문구는 서버 한국어 메시지", async () => {
    const { card, server } = await openModelCard();
    await within(card).findByTestId("upload-tab");
    pickFolder(card, GOOD());
    server.up.faults.push(err(507, "INSUFFICIENT_STORAGE", "디스크 공간이 부족합니다 — 공간을 확보한 뒤 같은 파일을 이어 올리세요"));
    fireEvent.click(upBtn(card));
    expect(await within(card).findByText(/디스크 공간이 부족합니다/)).toBeTruthy();
    fireEvent.click(upBtn(card, "이어 올리기"));
    await waitFor(() => expect(pathBox(card).value).toMatch(/uploads/));
    expect(server.up.items).toHaveLength(1);
  });

  it("취소: 서버 세션 DELETE(CANCELED) 후 선택이 지워지고 경로 칸은 비어 있다", async () => {
    const { card, server } = await openModelCard();
    const calls = recordCalls(server);
    await within(card).findByTestId("upload-tab");
    pickFolder(card, GOOD());
    server.up.faults.push(err(422, "CHUNK_OVERFLOW", "선언한 크기를 넘는 청크입니다"));
    fireEvent.click(upBtn(card));
    await within(card).findByText(/선언한 크기를 넘는 청크입니다/);
    fireEvent.click(upBtn(card, "취소"));
    await waitFor(() => expect(within(card).queryByTestId("upload-summary")).toBeNull());
    expect(server.up.items[0].state).toBe("CANCELED");
    expect(calls).toContain(`DELETE /uploads/${server.up.items[0].upload_id}`);
    fireEvent.click(within(card).getByRole("tab", { name: "서버 경로" }));
    expect(pathBox(card).value).toBe("");
  });

  it("complete 검사 실패(psmdl 누락) → OPEN 유지·문제 목록 → '빠진 파일 추가' → 다시 확인 통과 후 경로 채움", async () => {
    const { card, server } = await openModelCard();
    await within(card).findByTestId("upload-tab");
    pickFolder(card, [mkFile("train.log", "1", "m/train.log")]);
    server.up.failNextComplete = true;
    fireEvent.click(upBtn(card));
    const probs = await within(card).findByTestId("upload-problems");
    expect(probs.textContent).toContain("MODEL_PSMDL_MISSING");
    expect(server.up.items[0].state).toBe("OPEN");
    expect(pathBox(card).value).toBe(""); // 아직 채우지 않음
    fireEvent.change(within(card).getByLabelText("추가로 올릴 파일"), { target: { files: [mkFile("train_v3.psmdl", "model")] } });
    await waitFor(() => expect(server.up.items[0].state).toBe("COMPLETED"));
    expect(server.up.items[0].files.map((f) => f.rel)).toEqual(["train.log", "train_v3.psmdl"]);
    await waitFor(() => expect(pathBox(card).value).toMatch(/uploads/));
  });

  it("CAD(①-1): 엔진이 요청에 실리고 파일 경로가 채워진다 — 파일 1개 모양", async () => {
    const { server } = renderApp(`${STUDY}/1`, { ...O, geometry: "native", geometryDefault: "native" });
    const card = await screen.findByRole("region", { name: "CAD 파라미터 추출" });
    const bodies: Record<string, unknown>[] = [];
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h, r) => (m === "POST" && /\/uploads$/.test(p) && bodies.push(b as Record<string, unknown>), orig(m, p, q, b, h, r));
    await within(card).findByTestId("upload-tab");
    expect(within(card).queryByLabelText("올릴 폴더")).toBeNull(); // 파일 1개 purpose 는 폴더 선택 없음
    fireEvent.change(within(card).getByLabelText("올릴 파일"), { target: { files: [mkFile("base.step", "cad")] } });
    fireEvent.click(upBtn(card));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ purpose: "CAD_FILE", engine: "native", files: [{ rel: "base.step", size: 3 }] });
    await waitFor(() => expect((within(card).getByLabelText(/CAD 파일 경로/) as HTMLInputElement).value).toMatch(/uploads\\.+_base\\base\.step$/));
  });

  it("업로드·확인 중에는 beforeunload 경고를 걸고 끝나면 푼다", async () => {
    const add = vi.spyOn(window, "addEventListener");
    const rm = vi.spyOn(window, "removeEventListener");
    const { card, server } = await openModelCard();
    await within(card).findByTestId("upload-tab");
    pickFolder(card, GOOD());
    fireEvent.click(upBtn(card));
    await waitFor(() => expect(server.up.items[0]?.state).toBe("COMPLETED"));
    await waitFor(() => expect(add.mock.calls.some((c) => c[0] === "beforeunload")).toBe(true));
    await waitFor(() => expect(rm.mock.calls.some((c) => c[0] === "beforeunload")).toBe(true));
  });

  it("진행률: 파일 번호·전체 바이트·속도 표시와 청크 sha256 헤더", async () => {
    const { card, server } = await openModelCard();
    server.up.chunkSize = 4;
    await within(card).findByTestId("upload-tab");
    pickFolder(card, [mkFile("a.psmdl", "0123456789", "m/a.psmdl")]);
    fireEvent.click(upBtn(card));
    await waitFor(() => expect(server.up.items[0]?.state).toBe("COMPLETED"));
    expect(server.up.chunks.map((c) => c.offset)).toEqual([0, 4, 8]);
    for (const c of server.up.chunks) expect(c.sha === null || /^[0-9a-f]{64}$/.test(c.sha)).toBe(true);
  });
});
