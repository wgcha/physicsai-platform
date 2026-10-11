import { describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import type { MockServer } from "../mock/server";
import { STORAGE_POLL } from "../pages/manage/StorageSection";
import { BACKUP_NOTICE } from "../pages/manage/storage";

const MANAGE = "/p/p-cushion/s/s-cushion/manage";

/** 시드의 대기·실행 작업을 끝내 Study를 조용하게 만든다(낡음 규칙 2 회피) */
function quiet(s: MockServer) {
  s.jobs.forEach((j) => {
    if (j.study_id === "s-cushion" && !["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state)) {
      j.state = "CANCELED";
      j.finished_at = "2026-01-01T00:00:00Z";
    }
  });
  STORAGE_POLL.ms = 60;
}

/** 관리 화면에서 "다시 계산" → 목 작업 완료 → 요약 표시까지 */
async function scanned(user: "power" | "general" = "power") {
  const r = renderApp(MANAGE, { user }, quiet);
  const card = await screen.findByRole("region", { name: "용량·정리" });
  await within(card).findByText("아직 계산하지 않았습니다");
  if (user === "power") {
    fireEvent.click(within(card).getByRole("button", { name: "다시 계산" }));
    await waitFor(() => expect(r.server.jobs.some((j) => j.job_type === "STUDY_STORAGE_SCAN")).toBe(true));
    act(() => r.server.finishAll());
    await within(card).findByText(/전체 .* · 파일 \d+개 · 백업/, {}, { timeout: 3000 });
  }
  return { ...r, card };
}

describe("V3-S3-10 용량·정리", () => {
  it("계산 전 안내·_backup 안내 항상, 다시 계산 → 스캔 작업 1회 → 요약·막대·큰 파일", async () => {
    const { server } = renderApp(MANAGE, { user: "power" }, quiet);
    const card = await screen.findByRole("region", { name: "용량·정리" });
    await within(card).findByText("아직 계산하지 않았습니다");
    expect(within(card).getByTestId("backup-notice").textContent).toBe(BACKUP_NOTICE);
    const calls = recordCalls(server);
    fireEvent.click(within(card).getByRole("button", { name: "다시 계산" }));
    await waitFor(() => expect(calls.filter((c) => c === "POST /studies/s-cushion/jobs")).toHaveLength(1));
    act(() => server.finishAll());
    await within(card).findByText(/전체 .* · 파일 \d+개 · 백업/, {}, { timeout: 3000 });
    expect(within(card).getByLabelText("단계별 용량").textContent).toContain("① 학습데이터");
    expect(within(card).getByRole("table", { name: "큰 파일" })).toBeTruthy();
    expect(within(card).getByTestId("backup-notice")).toBeTruthy();
    expect(server.notifs.some((n) => n.job_id && server.jobs.find((j) => j.id === n.job_id)?.job_type === "STUDY_STORAGE_SCAN")).toBe(false);
  });

  it("범주 체크 → 미리보기 총량, 확인 대화상자 영향 안내, 옮기기 → POST STUDY_CLEANUP 1회", async () => {
    const { server, card } = await scanned();
    const pkg = await within(card).findByRole("checkbox", { name: /학습 패키지 사본/ });
    const logs = within(card).getByRole("checkbox", { name: /작업 로그/ });
    expect((within(card).getByRole("checkbox", { name: /미리보기 산출/ }) as HTMLInputElement).disabled).toBe(true);
    const btn = within(card).getByRole("button", { name: "백업 폴더로 옮기기" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(pkg);
    fireEvent.click(logs);
    expect(within(card).getByTestId("cleanup-total").textContent).toBe("선택 3개 · 2.4 GB");
    expect(within(card).getByRole("table", { name: "작업 로그 항목" }).textContent).toContain("logs/j-old1");
    expect(btn.disabled).toBe(false);
    const scanId = server.jobs.filter((j) => j.job_type === "STUDY_STORAGE_SCAN" && j.state === "SUCCEEDED").pop()!.id;
    const calls: unknown[] = [];
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) => {
      if (m === "POST" && p.endsWith("/jobs")) calls.push(b);
      return orig(m, p, q, b, h);
    };
    fireEvent.click(btn);
    const d = screen.getByRole("dialog");
    expect(within(d).getByRole("heading").textContent).toBe("Study 정리");
    expect(d.textContent).toContain("선택한 3개 항목(2.4 GB)을 _backup 폴더로 옮깁니다. 파일은 삭제되지 않습니다.");
    expect(d.textContent).toContain("옮기는 동안 이 Study에서 다른 작업을 실행할 수 없습니다.");
    expect(d.textContent).toContain("학습 패키지 사본(psdata): 학습 패키지가 '없음'으로 바뀝니다.");
    expect(d.textContent).toContain("작업 로그: 해당 작업의 로그 보기");
    fireEvent.click(within(d).getByRole("button", { name: "옮기기" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls).toEqual([{ job_type: "STUDY_CLEANUP", params: { scan_job_id: scanId, categories: ["PACKAGE_PSDATA", "JOB_LOGS"] } }]);
    act(() => server.finishAll());
    const last = await within(card).findByTestId("last-cleanup", {}, { timeout: 3000 });
    expect(last.textContent).toContain("3개");
    expect(within(card).getByTestId("backup-notice")).toBeTruthy();
  });

  it("비활성 사유: 낡음·활성 작업·권한", async () => {
    const { server, card } = await scanned();
    fireEvent.click(await within(card).findByRole("checkbox", { name: /학습 패키지 사본/ }));
    const btn = within(card).getByRole("button", { name: "백업 폴더로 옮기기" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    // 스캔 뒤 다른 작업이 끝남 → 낡음
    act(() => {
      server.createJob(server.studies[0], "MODEL_REGISTER", { model_path: "x" });
      server.finishAll();
    });
    fireEvent.click(within(card).getByRole("button", { name: "다시 계산" }));
    // 활성 작업(스캔 실행 중) → 비활성 + 사유
    await waitFor(() =>
      expect(within(card).getByRole("button", { name: "백업 폴더로 옮기기" }).parentElement!.getAttribute("title")).toBe("용량 계산이 진행 중입니다"),
    );
    act(() => {
      const j = server.jobs.find((x) => x.job_type === "STUDY_STORAGE_SCAN" && x.state === "QUEUED")!;
      j.state = "CANCELED";
      j.finished_at = new Date().toISOString();
    });
    await waitFor(() => expect(within(card).getByText(/주의: 스캔 뒤 작업/)).toBeTruthy(), { timeout: 3000 });
    const b2 = () => within(card).getByRole("button", { name: "백업 폴더로 옮기기" }) as HTMLButtonElement;
    await waitFor(() => expect(b2().parentElement!.getAttribute("title")).toContain("다시 계산한 뒤 정리하세요"), { timeout: 3000 });
    expect(b2().disabled).toBe(true);
  });

  it("조회 사용자: 계산·정리 버튼 비활성·권한 안내", async () => {
    const { card } = await scanned("general");
    expect(within(card).queryByRole("button", { name: "다시 계산" })).toBeNull();
    expect(within(card).getByText(/계산·정리: 실행 권한/)).toBeTruthy();
  });
});
