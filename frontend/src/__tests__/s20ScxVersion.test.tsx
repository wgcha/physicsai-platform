// V3-S20-6(D3-68): "Radioss 버전" 칸 — scx일 때만 보임, 초기값 = /status hpc.scx_version, 그대로면 null 전송,
// 바꾸면 자른 값 전송, 잘못된 값이면 오류 문구 + 제출 버튼 비활성. ①-4 SolveCard·④ VerifyNew.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { HPC_VERSION_ERROR, hpcVersionError, hpcVersionPayload } from "../lib/hpcVersion";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

type Body = Record<string, unknown>;
function record(server: MockServer, match: (m: string, p: string) => boolean): Body[] {
  const out: Body[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (match(m, p)) out.push(b as Body);
    return orig(m, p, q, b, h);
  };
  return out;
}

// ---------------------------------------------------------------- ①-4
const idleSolve = (s: MockServer) => {
  const j = s.jobs.find((x) => x.id === "j-solve");
  if (j) Object.assign(j, { state: "SUCCEEDED", finished_at: new Date().toISOString() });
};
const SCX1 = { user: "admin" as const, hpcConfigured: true, hpcMode: "scx" as const };
const PBS1 = { user: "admin" as const, hpcConfigured: true };

async function solveCard(opts: typeof SCX1 | typeof PBS1) {
  const { server } = renderApp(`${STUDY}/1`, opts, idleSolve);
  const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
  const btn = (await within(card).findByRole("button", { name: "PBS 제출" })) as HTMLButtonElement;
  await waitFor(() => expect(btn.disabled).toBe(false));
  const bodies = record(server, (m, p) => m === "POST" && /\/studies\/[^/]+\/jobs$/.test(p));
  return { server, card, btn, bodies };
}
const solveHpc = (bodies: Body[]) => ((bodies[0].params as Body).hpc as Body);

describe("V3-S20-6 규칙", () => {
  it("pattern·trim·초기값 비교", () => {
    expect(hpcVersionError("26.1")).toBeNull();
    expect(hpcVersionError(" 2026 R2 ")).toBeNull();
    for (const bad of ["", "  ", "-1", "26;1", "버전", "a".repeat(65)]) expect(hpcVersionError(bad)).toBe(HPC_VERSION_ERROR);
    expect(hpcVersionPayload("26.1", "26.1")).toBeNull();
    expect(hpcVersionPayload(" 26.1 ", "26.1")).toBeNull();
    expect(hpcVersionPayload(" 2026.2 ", "26.1")).toBe("2026.2");
  });
});

describe("V3-S20-6 ①-4 SolveCard", () => {
  it("scx: 칸 표시·초기값 = scx_version, 그대로면 version null 전송", async () => {
    const { card, btn, bodies } = await solveCard(SCX1);
    const input = within(card).getByLabelText("Radioss 버전") as HTMLInputElement;
    expect(input.value).toBe("26.1");
    fireEvent.click(btn);
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(solveHpc(bodies).version).toBeNull();
  });

  it("scx: 바꾸면 자른 값 전송(목 서버도 그 값 저장)", async () => {
    const { server, card, btn, bodies } = await solveCard(SCX1);
    fireEvent.change(within(card).getByLabelText("Radioss 버전"), { target: { value: " 2026.2 " } });
    fireEvent.click(btn);
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(solveHpc(bodies).version).toBe("2026.2");
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "TD_SOLVE" && (j.params.hpc as Body | null)?.version === "2026.2")).toBe(true));
  });

  it("scx: 잘못된 값이면 오류 문구 + PBS 제출 비활성, 고치면 다시 활성", async () => {
    const { card, btn } = await solveCard(SCX1);
    const input = within(card).getByLabelText("Radioss 버전");
    fireEvent.change(input, { target: { value: "26;1" } });
    expect(within(card).getAllByText(HPC_VERSION_ERROR).length).toBeGreaterThan(0);
    expect(btn.disabled).toBe(true);
    fireEvent.change(input, { target: { value: "" } });
    expect(btn.disabled).toBe(true);
    fireEvent.change(input, { target: { value: "26.2" } });
    expect(btn.disabled).toBe(false);
    expect(within(card).queryByText(HPC_VERSION_ERROR)).toBeNull();
  });

  it("command(PBS): 칸 없음, version null", async () => {
    const { card, btn, bodies } = await solveCard(PBS1);
    expect(within(card).queryByLabelText("Radioss 버전")).toBeNull();
    fireEvent.click(btn);
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(solveHpc(bodies).version).toBeNull();
  });
});

// ---------------------------------------------------------------- ④ 새 FEM 검증
const NEW = `${STUDY}/4/verify?new=1&kind=predict_job&job_id=j-pred`;
const FV = { user: "power" as const, hpcConfigured: true, femVerify: "demo" as const };

async function verifyCard(opts: typeof FV & { hpcMode?: "scx" }) {
  const { server } = renderApp(NEW, opts);
  const bodies = record(server, (m, p) => m === "POST" && p.endsWith("/fem-verifications"));
  const card = await screen.findByRole("region", { name: "새 FEM 검증" });
  const picker = await within(card).findByTestId("assembly-picker");
  fireEvent.click(within(picker).getAllByRole("radio")[2]);
  fireEvent.change(await within(picker).findByLabelText("조립 원본 경로"), { target: { value: "S:\\SPDM\\cushion\\assem_v7" } });
  fireEvent.click(within(picker).getByRole("button", { name: "확인" }));
  await within(picker).findByTestId("assembly-summary");
  const run = within(card).getByRole("button", { name: /FEM 검증 실행/ }) as HTMLButtonElement;
  await waitFor(() => expect(run.disabled).toBe(false));
  return { server, card, run, bodies };
}

describe("V3-S20-6 ④ VerifyNew", () => {
  it("scx: 초기값 그대로면 hpc null, 바꾸면 hpc.version 전송·작업 params 반영", async () => {
    const a = await verifyCard({ ...FV, hpcMode: "scx" });
    const input = within(a.card).getByLabelText("Radioss 버전") as HTMLInputElement;
    expect(input.value).toBe("26.1");
    fireEvent.change(input, { target: { value: "2026 R2 " } });
    fireEvent.click(a.run);
    await screen.findByRole("region", { name: /^FV-004/ }, { timeout: 3000 });
    expect(a.bodies[0].hpc).toEqual({ queue: null, ncpus: null, walltime: null, version: "2026 R2" });
    const fv = a.server.jobs.find((j) => j.job_type === "FEM_VERIFY" && (j.params.hpc as Body | null)?.version === "2026 R2");
    expect(fv).toBeTruthy();
  });

  it("scx: 그대로 실행하면 hpc null", async () => {
    const a = await verifyCard({ ...FV, hpcMode: "scx" });
    fireEvent.click(a.run);
    await screen.findByRole("region", { name: /^FV-004/ }, { timeout: 3000 });
    expect(a.bodies[0].hpc).toBeNull();
  });

  it("scx: 잘못된 값이면 오류 + 실행 비활성", async () => {
    const a = await verifyCard({ ...FV, hpcMode: "scx" });
    fireEvent.change(within(a.card).getByLabelText("Radioss 버전"), { target: { value: "-x" } });
    expect(within(a.card).getByText(HPC_VERSION_ERROR)).toBeTruthy();
    expect(a.run.disabled).toBe(true);
  });

  it("command: 칸 없음", async () => {
    const a = await verifyCard(FV);
    expect(within(a.card).queryByLabelText("Radioss 버전")).toBeNull();
  });
});

// ---------------------------------------------------------------- V3-S20-8 보강 1: scx면 queue·walltime 칸 없음
describe("V3-S20-8 ①-4 queue·walltime 칸", () => {
  it("scx: 칸 없음(ncpus·Radioss 버전만), queue·walltime null 전송", async () => {
    const { card, btn, bodies } = await solveCard(SCX1);
    expect(within(card).queryByLabelText("queue")).toBeNull();
    expect(within(card).queryByLabelText("walltime")).toBeNull();
    expect(within(card).getByLabelText("ncpus")).toBeTruthy();
    expect(within(card).getByLabelText("Radioss 버전")).toBeTruthy();
    fireEvent.change(within(card).getByLabelText("ncpus"), { target: { value: "8" } });
    fireEvent.click(btn);
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(solveHpc(bodies)).toMatchObject({ queue: null, walltime: null, ncpus: 8 });
  });

  it("command(PBS): queue·walltime 칸 있음, 값 전송", async () => {
    const { card, btn, bodies } = await solveCard(PBS1);
    fireEvent.change(within(card).getByLabelText("queue"), { target: { value: "gpuq" } });
    fireEvent.change(within(card).getByLabelText("walltime"), { target: { value: "24:00:00" } });
    fireEvent.click(btn);
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(solveHpc(bodies)).toMatchObject({ queue: "gpuq", walltime: "24:00:00" });
  });
});
