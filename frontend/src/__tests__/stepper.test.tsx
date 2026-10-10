// phase2.md §20 V2-FE-1 (+③④ FeatureGate) (컴포넌트 시험, 목 서버)
import { describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { FeatureGate } from "../components/FeatureGate";
import { AppContext } from "../app/AppContext";
import { clearApiCache, type StatusInfo } from "../api";
import { USERS } from "../mock/data";

describe("V2-FE-1 스텝퍼·FeatureGate", () => {
  it("설정이 비면 버튼 비활성 + '관리자 설정 필요: <키>'", async () => {
    renderApp(`${STUDY}/1`, { user: "power", disabledFeatures: ["train_extract"] });
    const card = await screen.findByRole("region", { name: "CAD 파라미터 추출" });
    const note = await within(card).findByTestId("feature-off-train_extract");
    expect(note.textContent).toBe("관리자 설정 필요: resources.pyd_dir, commands.simlab_extract_params");
    expect((within(card).getByRole("button", { name: "파라미터 추출" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("FeatureGate: features가 없으면(1차 백엔드) 활성, enabled=false면 키 3개까지", () => {
    const status = { features: { optimize: { enabled: false, missing: ["a", "b", "c", "d"] } } } as unknown as StatusInfo;
    const ui = (st: StatusInfo | null) => (
      <AppContext.Provider value={{ me: USERS.power, projects: [], status: st }}>
        <FeatureGate feature="optimize">{(en) => <button disabled={!en}>실행</button>}</FeatureGate>
      </AppContext.Provider>
    );
    const { rerender } = render(ui(null));
    expect((screen.getByRole("button", { name: "실행" }) as HTMLButtonElement).disabled).toBe(false);
    rerender(ui(status));
    expect((screen.getByRole("button", { name: "실행" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("feature-off-optimize").textContent).toBe("관리자 설정 필요: a, b, c 외");
  });
});

describe("③-1·③-5·④ FeatureGate(features.dataset_create/evaluate/predict)", () => {
  it("비활성이면 버튼 비활성 + 설정 필요 안내, 관리자에게만 환경 점검 링크", async () => {
    const off = ["dataset_create", "evaluate", "predict"] as const;
    const p = renderApp(`${STUDY}/3`, { user: "power", disabledFeatures: [...off] });
    const ds = await screen.findByRole("region", { name: "데이터셋 생성" });
    expect((await within(ds).findByTestId("feature-off-dataset_create")).textContent).toBe("관리자 설정 필요: altair.edspy_path");
    expect((within(ds).getByRole("button", { name: "데이터셋 생성" }) as HTMLButtonElement).disabled).toBe(true);
    const ev = screen.getByRole("region", { name: "평가 · Final 지정" });
    expect(within(ev).getByTestId("feature-off-evaluate")).toBeTruthy();
    expect((within(ev).getByRole("button", { name: "평가" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("feature-off-link-dataset_create")).toBeNull();
    p.unmount();
    clearApiCache();
    renderApp(`${STUDY}/4`, { user: "admin", disabledFeatures: [...off] });
    expect(await screen.findByTestId("feature-off-predict")).toBeTruthy();
    await waitFor(() => expect((screen.getByRole("button", { name: "예측 실행" }) as HTMLButtonElement).disabled).toBe(true));
    expect(screen.getByTestId("feature-off-link-predict").getAttribute("href")).toBe("/admin/env-check");
  });

  it("활성(기본)이면 안내 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    await screen.findByRole("region", { name: "데이터셋 생성" });
    expect(screen.queryByTestId("feature-off-dataset_create")).toBeNull();
    expect(screen.queryByTestId("feature-off-evaluate")).toBeNull();
  });
});
