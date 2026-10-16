// phase3 §13 S8: ④ 파라미터 세트 "프로젝트 폴더에서 찾기"(찾기 → 후보 선택 → 등록) + 표시 이름(label)
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { MockServer } from "../mock/server";
import specJson from "../../../backend/openapi.json";
import { MOCK_INBOX } from "../mock/fs";

const ROOT = "E:/shared/AI_WORK/cushion/00_inbox";

function recordRegister(server: MockServer) {
  const bodies: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && /\/studies\/[^/]+\/param-sets$/.test(p)) bodies.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return bodies;
}

/** 템플릿 칸의 "템플릿 관리"를 펼친다(S9: 관리는 펼칠 때만) */
async function openManage() {
  fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
  return screen.findByRole("region", { name: "템플릿 관리" });
}

async function openDiscover(path: string) {
  const card = await openManage();
  fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
  expect(within(card).getByRole("button", { name: "프로젝트 폴더에서 찾기" }).getAttribute("aria-pressed")).toBe("true"); // 기본
  const form = within(card).getByTestId("ps-discover");
  fireEvent.change(within(form).getByLabelText("프로젝트 폴더 경로"), { target: { value: path } });
  fireEvent.click(within(form).getByRole("button", { name: "찾기" }));
  return { card, form };
}

describe("④ 프로젝트 폴더에서 찾기 (phase3 §13 S8)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("후보 1개씩: 찾기 → 요약 → 이름 붙여 등록", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const bodies = recordRegister(server);
    const { card, form } = await openDiscover(`${ROOT}/project`);
    fireEvent.change(within(card).getByLabelText("템플릿 이름"), { target: { value: "쿠션 v2" } });
    expect((await within(form).findByTestId("ps-discover-params")).textContent).toBe("4개 · tpl에서 생성 — 단위 없음");
    expect(within(form).getByText("01_CAD/cushion_base.x_t")).toBeTruthy();
    expect(within(form).getByText("RADIOSS_ASSEM · cushion_0000.rad")).toBeTruthy();
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    await waitFor(() => expect(server.paramSets[0].label).toBe("쿠션 v2"));
    expect(bodies[0]).toEqual({
      path: `${ROOT}/project`, mode: "discover", label: "쿠션 v2",
      choice: { tpl: "simlab_parametered_mesh.tpl", cad: "01_CAD/cushion_base.x_t", radioss_assem: "RADIOSS_ASSEM" },
    });
    expect(await within(card).findByText("쿠션 v2")).toBeTruthy();
  });

  it("후보 여러 개: 고르기 전에는 등록 불가, 드롭다운으로 고른 값을 보낸다", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const bodies = recordRegister(server);
    const { form } = await openDiscover(`${ROOT}/multi`);
    const reg = within(form).getByRole("button", { name: "등록" }) as HTMLButtonElement;
    const tplSel = (await within(form).findByLabelText("tpl 선택")) as HTMLSelectElement;
    expect(tplSel.value).toBe("");
    expect(reg.disabled).toBe(true);
    fireEvent.change(tplSel, { target: { value: "TEMAPLATE_simlab_parametered_mesh.tpl" } });
    const cadSel = (await within(form).findByLabelText("CAD 선택")) as HTMLSelectElement;
    fireEvent.change(cadSel, { target: { value: "old/cushion_base.x_t" } });
    expect(reg.disabled).toBe(true);
    fireEvent.change(within(form).getByLabelText("조립 폴더 선택"), { target: { value: "case_B/radioss" } });
    await waitFor(() => expect(reg.disabled).toBe(false));
    fireEvent.click(reg);
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(bodies[0].choice).toEqual({ tpl: "TEMAPLATE_simlab_parametered_mesh.tpl", cad: "old/cushion_base.x_t", radioss_assem: "case_B/radioss" });
    expect(bodies[0].label).toBeNull();
  });

  it("하나도 없으면 무엇이 없는지 표시하고 등록 불가", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const { form } = await openDiscover(`${ROOT}/empty`);
    expect(await within(form).findByText(/tpl\(\*\.tpl\)을 찾지 못했습니다/)).toBeTruthy();
    expect(within(form).getByText(/조립 폴더 없음 — m1 메시로 바로 예측합니다/)).toBeTruthy(); // S9: 조립 0개는 문제가 아니라 안내
    expect((within(form).getByRole("button", { name: "등록" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("찾아보기(§12 S7): 추가 허용 폴더까지 보이고, 고른 폴더가 프로젝트 폴더 입력란에 들어간다", async () => {
    localStorage.clear();
    renderApp(`${STUDY}/4`, { user: "power" });
    const card = await openManage();
    fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
    const form = within(card).getByTestId("ps-discover");
    fireEvent.click(within(form).getByRole("button", { name: "찾아보기" }));
    const d = await screen.findByRole("dialog");
    expect(within(d).getByRole("button", { name: "추가 허용 폴더" })).toBeTruthy(); // imports=True 용도(aiOnly 아님)
    await waitFor(() => expect(within(d).getByTestId("picker-target").textContent).toBe(MOCK_INBOX));
    fireEvent.click(within(d).getByRole("button", { name: "선택" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((within(form).getByLabelText("프로젝트 폴더 경로") as HTMLInputElement).value).toBe(MOCK_INBOX);
    localStorage.clear();
  });

  it("기존 세트 이름 변경", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const card = await openManage();
    expect(within(card).getByTestId("ps-label").textContent).toContain("이름 없음");
    fireEvent.click(within(card).getByRole("button", { name: "이름 변경" }));
    fireEvent.change(within(card).getByLabelText("새 이름"), { target: { value: "쿠션 템플릿" } });
    fireEvent.click(within(card).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(server.paramSets[0].label).toBe("쿠션 템플릿"));
    expect(await within(card).findByText("쿠션 템플릿")).toBeTruthy();
  });

  it("목 discover 응답이 openapi 필수 필드를 갖는다", () => {
    const schemas = (specJson as unknown as { components: { schemas: Record<string, { required?: string[] }> } }).components.schemas;
    const srv = new MockServer({ user: "power" });
    for (const name of ["project", "multi", "empty"]) {
      const r = srv.handle("POST", "/studies/s-cushion/param-sets/discover", new URLSearchParams(), { path: `${ROOT}/${name}` }, new Headers({ "X-PhysicsAI-Request": "1" }));
      expect(r.status).toBe(200);
      const body = r.body as Record<string, unknown>;
      expect((schemas.ParamSetDiscoverResponse.required ?? []).filter((k) => !(k in body))).toEqual([]);
    }
  });

  it("조회 전용 사용자는 템플릿 관리·이름 변경 버튼이 없다(고르기만)", async () => {
    renderApp(`${STUDY}/4`, { user: "general" });
    const card = await screen.findByRole("region", { name: "템플릿" });
    expect(within(card).getByText("관리자가 등록 · 사용자는 고르기만")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "템플릿 관리" })).toBeNull();
    expect(screen.queryByRole("button", { name: "이름 변경" })).toBeNull();
  });
});
