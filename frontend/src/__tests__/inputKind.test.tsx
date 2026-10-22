// v0.2.7 input-kind.md V-IK-9(화면): 템플릿 배지 3종 · `입력: 조립|쿠션` 세그먼트(능력 밖 비활성+이유·기본 서버 규칙·쿠션 안내) · 422 INPUT_KIND_UNSUPPORTED 표시 ·
// 요청 body `input` · 실행 목록 열·상세 배지·경고(응답 행) · 단건 predict_input 한 줄 · FEM 검증 출처 세그먼트 · ① "조립 기준" · ③ 출처 열(①·③에 입력 선택 없음).
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { TemplateBadge, InputBadge } from "../components/InputKindSelect";
import { badgeOf, capabilityOf, defaultInput, inputKindError } from "../lib/inputKind";
import { baseJob, iso } from "../mock/data";
import { seedParamSet } from "../mock/seed";
import type { MockServer } from "../mock/server";
import { SINGLE_TAB_KEY } from "../stages/stage4/history/SingleTabs";
import { SO_TAB_KEY } from "../stages/stage5/surrogate/soRules";

const MODE_KEY = "physicsai.stage4.inputMode";
const BATCH_TAB = "physicsai.stage4.batchTab";
type Rec = { m: string; p: string; b: Record<string, unknown> | null };
function record(server: MockServer, re: RegExp, method = "POST"): Rec[] {
  const out: Rec[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h, r) => {
    if (m === method && re.test(p)) out.push({ m, p, b: b as Rec["b"] });
    return orig(m, p, q, b, h, r);
  };
  return out;
}
/** 응답을 가로채 본문을 고친다(경고 주입 등) */
function patchGet(server: MockServer, re: RegExp, fn: (b: Record<string, unknown>) => void) {
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h, r) => {
    const res = orig(m, p, q, b, h, r);
    if (m === "GET" && re.test(p) && res.body) fn(res.body as Record<string, unknown>);
    return res;
  };
}
const seg = (name = "입력 종류") => screen.getByRole("radiogroup", { name });
const rad = (name: string, group = "입력 종류") => within(seg(group)).getByRole("radio", { name }) as HTMLButtonElement;

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("순수 규칙", () => {
  it("능력 → 기본값·배지 종류, 서버가 능력을 안 주면 저장 입력 종류에서", () => {
    expect(capabilityOf({ input_capability: ["assembly", "cushion"], input_kind: "assembly" })).toEqual(["assembly", "cushion"]);
    expect(capabilityOf({ input_kind: "mesh_only" })).toEqual(["cushion"]);
    expect(capabilityOf({ input_kind: "assembly" })).toEqual(["assembly"]);
    expect(defaultInput(["assembly", "cushion"])).toBe("assembly");
    expect(defaultInput(["cushion"])).toBe("cushion");
    expect([["assembly", "cushion"], ["cushion"], ["assembly"]].map((c) => badgeOf(c as never))).toEqual(["both", "cushion_only", "assembly_only"]);
  });
  it("422 INPUT_KIND_UNSUPPORTED만 세그먼트 옆 문구로", () => {
    expect(inputKindError({ code: "INPUT_KIND_UNSUPPORTED", message: "이 템플릿은 쿠션 입력을 쓸 수 없습니다(쉘)" })).toBe("이 템플릿은 쿠션 입력을 쓸 수 없습니다(쉘)");
    expect(inputKindError({ code: "OTHER", message: "x" })).toBeNull();
    expect(inputKindError(null)).toBeNull();
  });
});

describe("템플릿 배지 3종", () => {
  it.each([
    ["조립·쿠션 가능", { input_capability: ["assembly", "cushion"], input_kind: "assembly" }, "both"],
    ["쿠션만", { input_capability: ["cushion"], input_capability_reason: "쿠션만 가능한 템플릿(조립 폴더 없음)", input_kind: "mesh_only" }, "cushion_only"],
    ["조립만", { input_capability: ["assembly"], input_capability_reason: "관리자 설정 필요: commands.paicad_cushion_write", input_kind: "assembly" }, "assembly_only"],
  ] as const)("%s", (text, ps, kind) => {
    const { unmount } = render(<TemplateBadge ps={ps as never} />);
    const b = screen.getByTestId("template-badge");
    expect(b.textContent).toBe(text);
    expect(b.getAttribute("data-kind")).toBe(kind);
    expect(b.title).toBe(("input_capability_reason" in ps ? ps.input_capability_reason : "") ?? "");
    unmount();
  });
  it("실행 입력 배지: 조립 / 쿠션 / 모르면 –", () => {
    const { unmount } = render(<><InputBadge input="assembly" /><InputBadge input="cushion" /><InputBadge input={undefined} /></>);
    expect(screen.getAllByTestId("input-badge").map((x) => x.textContent)).toEqual(["조립", "쿠션"]);
    unmount();
  });
  it("④ 템플릿 칸: 조립 가능 템플릿 = '조립·쿠션 가능', 쿠션 단독 = '쿠션만', 쉘 등 조립만 = '조립만'(회색 메타 줄 없음)", async () => {
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      s.paramSets.push({ ...seedParamSet(), id: "ps-3", label: "판금 비드 v1", is_current: false, input_capability: ["assembly"], input_capability_reason: "쉘 템플릿에는 쿠션 바디가 없습니다" });
    });
    const sel = async () => within(await screen.findByRole("region", { name: "템플릿" })).getByLabelText("형상 템플릿") as HTMLSelectElement;
    await waitFor(() => expect(within(screen.getByRole("region", { name: "템플릿" })).getByTestId("template-badge").textContent).toBe("조립·쿠션 가능"));
    fireEvent.change(await sel(), { target: { value: "ps-2" } });
    await waitFor(() => expect(within(screen.getByRole("region", { name: "템플릿" })).getByTestId("template-badge").textContent).toBe("쿠션만"));
    fireEvent.change(await sel(), { target: { value: "ps-3" } });
    await waitFor(() => expect(within(screen.getByRole("region", { name: "템플릿" })).getByTestId("template-badge").textContent).toBe("조립만"));
    expect(within(screen.getByRole("region", { name: "템플릿" })).getByTestId("template-badge").title).toBe("쉘 템플릿에는 쿠션 바디가 없습니다");
  });
});

describe("④ 단건 예측 — 입력 세그먼트", () => {
  it("기본 = 조립(서버 규칙), 쿠션 고르면 한 줄 안내, 안 골랐으면 body에 input 없음 / 골랐으면 input: cushion → 서버가 template_kind mesh_only 기록", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const jobs = record(server, /\/studies\/[^/]+\/jobs$/);
    const card = await screen.findByRole("region", { name: "템플릿" });
    expect(rad("조립").getAttribute("aria-checked")).toBe("true");
    expect(rad("쿠션").disabled).toBe(false);
    expect(within(card).queryByTestId("cushion-note")).toBeNull();
    const run = within(card).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(rad("쿠션"));
    expect(rad("쿠션").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("cushion-note").textContent).toBe("m1 쿠션 메시로 예측 — GPU 메모리 적음 · 제품 부품 응답은 값이 없을 수 있음");
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect((jobs[0].b!.params as Record<string, unknown>).input).toBe("cushion");
    const job = server.jobs.find((j) => j.job_type === "PREDICT" && (j.params as { input?: string }).input === undefined && (j.params as { template_kind?: string }).template_kind === "mesh_only");
    expect(job).toBeTruthy();
    // 진행 표시는 쿠션 체인(메시 연결·조립 단계 없음)
    await waitFor(() => expect(within(screen.getByRole("list", { name: "예측 실행 단계" })).getAllByRole("listitem")).toHaveLength(3));
  });

  it("쿠션만 템플릿: 조립 비활성 + 이유(툴팁·문구), 기본 = 쿠션, body에 input 없음", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const jobs = record(server, /\/studies\/[^/]+\/jobs$/);
    const card = await screen.findByRole("region", { name: "템플릿" });
    fireEvent.change(within(card).getByLabelText("형상 템플릿"), { target: { value: "ps-2" } });
    await waitFor(() => expect(rad("쿠션").getAttribute("aria-checked")).toBe("true"));
    expect(rad("조립").disabled).toBe(true);
    expect(rad("조립").title).toBe("쿠션만 가능한 템플릿(조립 폴더 없음)");
    expect(screen.getByTestId("input-reason").textContent).toBe("조립 입력 불가: 쿠션만 가능한 템플릿(조립 폴더 없음)");
    const run = within(await screen.findByRole("region", { name: "템플릿" })).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect("input" in (jobs[0].b!.params as object)).toBe(false);
  });

  it("조립만 템플릿(쉘·Native 쿠션 명령 미설정): 쿠션 비활성 + 이유", async () => {
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      Object.assign(s.paramSets[0], { input_capability: ["assembly"], input_capability_reason: "관리자 설정 필요: commands.paicad_cushion_write" });
    });
    await screen.findByRole("region", { name: "템플릿" });
    await waitFor(() => expect(rad("쿠션").disabled).toBe(true));
    expect(rad("쿠션").title).toBe("관리자 설정 필요: commands.paicad_cushion_write");
    expect(rad("조립").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("input-reason").textContent).toContain("쿠션 입력 불가");
  });

  it("422 INPUT_KIND_UNSUPPORTED: 서버 문구를 세그먼트 옆에 표시(실행 줄에 중복 표시 없음)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const card = await screen.findByRole("region", { name: "템플릿" });
    const run = within(card).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(rad("쿠션"));
    // 화면이 낡은 능력으로 그려진 뒤 서버 쪽 능력이 바뀐 경우
    Object.assign(server.paramSets[0], { input_capability: ["assembly"], input_capability_reason: "쉘 템플릿에는 쿠션 바디가 없습니다" });
    fireEvent.click(run);
    const e = await screen.findByTestId("input-error");
    expect(e.textContent).toBe("이 템플릿은 쿠션 입력을 쓸 수 없습니다(쉘 템플릿에는 쿠션 바디가 없습니다)");
    expect(within(await screen.findByRole("region", { name: "템플릿" })).getAllByRole("alert")).toHaveLength(1);
    // 다시 고르면 오류가 지워진다
    fireEvent.click(rad("조립"));
    expect(screen.queryByTestId("input-error")).toBeNull();
  });
});

describe("④ 일괄 예측", () => {
  const setupBatch = async (opts: Parameters<typeof renderApp>[1] = { user: "power" }) => {
    localStorage.setItem(MODE_KEY, "batch");
    const r = renderApp(`${STUDY}/4`, opts);
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    return { ...r, setup };
  };
  it("세그먼트 → 미리보기·실행 body에 input: cushion, 결과 화면에 입력 배지(쿠션), 실행 목록에 입력 열", async () => {
    const { server, setup } = await setupBatch();
    const previews = record(server, /\/predict-batches\/preview$/);
    const jobs = record(server, /\/studies\/[^/]+\/jobs$/);
    expect(within(setup).getByTestId("template-badge").textContent).toBe("조립·쿠션 가능");
    expect(screen.getByText("SimLab m_1 → EPS_mesh · HyperMesh m_2 → include · m_3 조립")).toBeTruthy();
    fireEvent.click(rad("쿠션"));
    expect(screen.getByText("SimLab m_1 → EPS_mesh (쿠션 rad만 — m_2·m_3 없음)")).toBeTruthy();
    expect(screen.getByTestId("cushion-note")).toBeTruthy();
    fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: "4" } });
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await screen.findByRole("table", { name: "조합 미리보기" });
    expect(previews[0].b!.input).toBe("cushion");
    const run = screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect((jobs[0].b!.params as Record<string, unknown>).input).toBe("cushion");
    const batch = server.batches.find((b) => b.batch_no === 3)!;
    expect(batch.input_kind).toBe("mesh_only");
    // 결과 화면: 파일 위치 칸에 입력 배지
    const loc = await screen.findByRole("region", { name: "파일 위치" });
    expect(within(loc).getByTestId("input-badge").textContent).toBe("쿠션");
  });

  it("안 골랐으면 body에 input 없음(서버 기본), 입력 능력 밖(422) 문구는 세그먼트 옆", async () => {
    const { server, setup } = await setupBatch();
    const previews = record(server, /\/predict-batches\/preview$/);
    fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: "4" } });
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await screen.findByRole("table", { name: "조합 미리보기" });
    expect("input" in previews[0].b!).toBe(false);
    fireEvent.click(rad("쿠션"));
    Object.assign(server.paramSets[0], { input_capability: ["assembly"], input_capability_reason: "쉘 두께 값이 있는 템플릿은 조립 입력만" });
    fireEvent.click(within(await screen.findByRole("region", { name: "1 템플릿·조합" })).getByRole("button", { name: "조합 만들기" }));
    expect((await screen.findByTestId("input-error")).textContent).toContain("쿠션 입력을 쓸 수 없습니다(쉘 두께 값이 있는 템플릿은 조립 입력만)");
  });

  it("실행 목록: 입력 열(조립 / 쿠션 배지)", async () => {
    localStorage.setItem(MODE_KEY, "batch");
    localStorage.setItem(BATCH_TAB, "list");
    const a = renderApp(`${STUDY}/4`, { user: "power" });
    const table = await screen.findByRole("table", { name: "일괄 예측 실행 목록" });
    expect(within(table).getAllByRole("columnheader").map((c) => c.textContent)).toContain("입력");
    expect(within(table).getAllByTestId("input-badge").map((b) => b.getAttribute("data-input"))).toEqual(["assembly"]);
    a.unmount();
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      s.batches[0].input_kind = "mesh_only";
    });
    const t2 = await screen.findByRole("table", { name: "일괄 예측 실행 목록" });
    expect(within(t2).getByTestId("input-badge").textContent).toBe("쿠션");
  });

  it("상세: INPUT_CUSHION_RESPONSES 경고는 결과 표 위(응답 행 자리)에 보이고 막지 않는다", async () => {
    renderApp(`${STUDY}/4/batch/pb-2`, { user: "power" }, (s) => {
      s.batches.find((b) => b.id === "pb-2")!.input_kind = "mesh_only";
      patchGet(s, /\/predict-batches\/pb-2$/, (b) => {
        b.warnings = [{ code: "INPUT_CUSHION_RESPONSES", message: "쿠션 입력에서 값이 없는 응답: MaxStress — 쿠션 입력은 쿠션 메시의 예측 결과만 있습니다" }];
      });
    });
    const w = await screen.findByTestId("input-warning");
    expect(w.textContent).toContain("MaxStress");
    expect(w.closest("section")!.getAttribute("aria-label")).toMatch(/^결과 표/);
    expect(await screen.findByRole("table", { name: "일괄 예측 결과" })).toBeTruthy();
  });
});

describe("④ 단일 예측 실행 목록·상세", () => {
  const extra = (s: MockServer) =>
    s.jobs.push(
      baseJob({
        id: "j-cu1", study_id: "s-cushion", project_id: "p-cushion", study_title: "쿠션 두께·리브 예측", job_type: "PREDICT", state: "SUCCEEDED",
        created_at: iso(5), started_at: iso(4), finished_at: iso(2),
        params: { param_set_id: "ps-1", model_id: null, values: { THK_TOP: 0.5 }, value_source: "manual", source_run_key: null, template_kind: "mesh_only" },
      }),
    );
  it("목록: 입력 열(쿠션 실행 = 쿠션, 템플릿 조립 실행 = 조립, 준비된 입력은 starter로 판정)", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "list");
    renderApp(`${STUDY}/4`, { user: "power", predictRuns: "history" }, extra);
    const t = await screen.findByRole("table", { name: "단일 예측 실행 목록" });
    const cell = async (id: string) => within(await within(t).findByTestId(`run-${id}`)).getByTestId("input-badge").textContent;
    expect(await cell("j-cu1")).toBe("쿠션");
    expect(await cell("j-h3")).toBe("조립");
  });
  it("상세: 입력 배지 + predict_input 한 줄(starter·파일 수·크기) + 경고", async () => {
    renderApp(`${STUDY}/4?job=j-cu1`, { user: "power", predictRuns: "history" }, (s) => {
      extra(s);
      patchGet(s, /\/predict-runs\/j-cu1$/, (b) => {
        b.input_warnings = [{ code: "INPUT_CUSHION_RESPONSES", message: "쿠션 입력에서 값이 없는 응답: MaxStress — 제품 부품 응답은 값이 없을 수 있습니다" }];
      });
    });
    const inputs = await screen.findByRole("region", { name: "입력·경로" });
    await waitFor(() => expect(within(inputs).getByTestId("predict-input")).toBeTruthy());
    const line = within(inputs).getByTestId("predict-input").textContent!;
    expect(line).toContain("EPS_mesh_0000.rad");
    expect(line).toContain("파일 1개");
    expect(line).toMatch(/3\.2 MB/);
    expect(within(inputs).getAllByTestId("input-badge")[0].textContent).toBe("쿠션");
    expect(within(inputs).getByTestId("input-warning").textContent).toContain("MaxStress");
  });
});

describe("⑥ 내장 최적화", () => {
  it("설정: 템플릿 칸에 배지 + 입력 세그먼트, 쿠션 → 미리보기·시작 body input: cushion, 목록 입력 열·상세 배지", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const previews = record(server, /\/surrogate-opts\/preview$/);
    const starts = record(server, /\/studies\/s-cushion\/surrogate-opts$/);
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    const tpl = await screen.findByRole("region", { name: "템플릿·모델" });
    expect(within(tpl).getByTestId("template-badge").textContent).toBe("조립·쿠션 가능");
    expect(rad("조립").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(rad("쿠션"));
    expect(within(tpl).getByTestId("cushion-note")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("MaxStress 역할"), { target: { value: "min" } });
    await waitFor(() => expect(previews.length).toBeGreaterThan(0));
    expect(previews[previews.length - 1].b!.input).toBe("cushion");
    await waitFor(() => expect((screen.getByRole("button", { name: "최적화 시작" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "최적화 시작" }));
    expect(await screen.findByTestId("so-status")).toBeTruthy();
    expect(starts[0].b!.input).toBe("cushion");
    expect(server.surrogate[server.surrogate.length - 1].settings.input).toBe("cushion");
    const head = screen.getByRole("region", { name: /^내장 최적화 SO-/ });
    expect(within(head).getByTestId("input-badge").textContent).toBe("쿠션");
  });

  it("실행 목록에 입력 열 · 경고(INPUT_CUSHION_RESPONSES)·입력 배지는 상세 머리에", async () => {
    localStorage.setItem(SO_TAB_KEY, "list");
    renderApp(`${STUDY}/5`, { user: "power" }, (s) => {
      patchGet(s, /\/surrogate-opts\/[^/]+$/, (b) => {
        b.input = "cushion";
        b.warnings = [{ code: "INPUT_CUSHION_RESPONSES", message: "쿠션 입력에서 값이 없는 응답: MaxStress — 쿠션 입력은 쿠션 메시의 예측 결과만 있습니다" }];
      });
    });
    const list = await screen.findByRole("table", { name: "내장 최적화 실행 목록" });
    expect(within(list).getAllByRole("columnheader").map((c) => c.textContent)).toContain("입력");
    expect(within(list).getAllByTestId("input-badge")[0].textContent).toBe("쿠션"); // 시드 최적화는 쿠션 단독 템플릿(ps-2) 기준
    fireEvent.click(within(list).getAllByRole("row")[1]);
    expect((await screen.findByTestId("input-warning")).textContent).toContain("MaxStress");
    expect(within(screen.getByRole("region", { name: /^내장 최적화 SO-/ })).getByTestId("input-badge").textContent).toBe("쿠션");
  });

  it("422 INPUT_KIND_UNSUPPORTED: 시작을 눌렀을 때 서버 문구를 세그먼트 옆에", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    await screen.findByRole("region", { name: "템플릿·모델" });
    fireEvent.change(screen.getByLabelText("MaxStress 역할"), { target: { value: "min" } });
    fireEvent.click(rad("쿠션"));
    Object.assign(server.paramSets[0], { input_capability: ["assembly"], input_capability_reason: "쉘 템플릿에는 쿠션 바디가 없습니다" });
    // 미리보기가 같은 422를 받아 세그먼트 옆에 표시 — 설정 칸 오류 줄에는 중복 표시하지 않는다
    await waitFor(() => expect(screen.getByTestId("input-error").textContent).toBe("이 템플릿은 쿠션 입력을 쓸 수 없습니다(쉘 템플릿에는 쿠션 바디가 없습니다)"));
    expect(screen.queryAllByRole("alert").filter((a) => a.getAttribute("data-testid") !== "input-error")).toHaveLength(0);
  });
});

describe("FEM 검증 출처", () => {
  const VALUES = `${STUDY}/4/verify?new=1&kind=values&param_set_id=ps-1&values=${encodeURIComponent(JSON.stringify({ THK_TOP: 0.5, THK_FOAM: 2, E_FOAM: 9.5, RIB_N: 5 }))}`;
  const O = { user: "power" as const, hpcConfigured: true, femVerify: "demo" as const };
  it("값 출처: 입력 세그먼트 1개(쿠션 선택 → 미리보기·생성 body source.input, design 입력 배지), 예측 출처는 읽기 전용 배지", async () => {
    const { server } = renderApp(VALUES, O);
    const previews = record(server, /\/fem-verifications\/preview$/);
    await screen.findByTestId("fv-source");
    expect(rad("조립").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(rad("쿠션"));
    await waitFor(() => expect(previews.some((p) => (p.b!.source as { input?: string }).input === "cushion")).toBe(true));
    expect(screen.getByTestId("cushion-note")).toBeTruthy();
  });
  it("예측 출처(predict_job): 세그먼트 없이 설계의 입력 배지만", async () => {
    renderApp(`${STUDY}/4/verify?new=1&kind=predict_job&job_id=j-pred`, O);
    await screen.findByTestId("fv-source");
    expect(screen.queryByRole("radiogroup", { name: "입력 종류" })).toBeNull();
    expect((await screen.findByTestId("fv-input")).textContent).toContain("조립");
  });
});

describe("① 조립 기준 · ③ 출처 (P3 — 선택 UI 없음)", () => {
  it("① 머리에 '조립 기준(학습 데이터)'·안내, 입력 세그먼트는 없다", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const b = await screen.findByTestId("stage1-basis");
    expect(within(b).getByTestId("assembly-basis").textContent).toBe("조립 기준(학습 데이터)");
    expect(b.textContent).toContain("④ 예측·⑥ 최적화에서 고릅니다");
    expect(screen.queryByRole("radiogroup", { name: "입력 종류" })).toBeNull();
  });
  it("③ 데이터셋 목록: 출처 열 — ① DOE(조립) / 외부 폴더, 입력 세그먼트는 없다", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    expect((await screen.findByTestId("ds-source-ds-2")).textContent).toBe("① DOE D-001(조립)");
    expect(screen.getByTestId("ds-source-ds-1").textContent).toBe("외부 폴더");
    expect(screen.queryByRole("radiogroup", { name: "입력 종류" })).toBeNull();
  });
});
