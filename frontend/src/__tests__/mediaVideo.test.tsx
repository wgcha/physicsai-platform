// V3-S16-25: MediaVideo — gif → <img>, avi·playable=false → 안내 + 받기(video 없음), video/source error → 안내 전환·포스터 유지, ContourMedia video_error 문구.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MediaVideo } from "../components/MediaVideo";
import { MEDIA_TEXT } from "../stages/stage4/ContourMedia";
import type { MediaFile } from "../api/types";
import { renderApp, STUDY } from "../test/render";

const f = (o: Partial<MediaFile> = {}): MediaFile => ({ artifact_id: "a-1", content_type: "video/mp4", size: 10, url: "/physicsai/api/artifacts/a-1/media", download_url: "/physicsai/api/artifacts/a-1/media?download=true", ...o });

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("V3-S16-25 MediaVideo", () => {
  it("mp4: <video controls> + source", () => {
    const { container } = render(<MediaVideo file={f()} label="정면" />);
    const v = container.querySelector("video")!;
    expect(v.hasAttribute("controls")).toBe(true);
    expect(v.querySelector("source")!.getAttribute("src")).toBe("/physicsai/api/artifacts/a-1/media");
  });

  it("gif → <img>(video 없음)", () => {
    const { container } = render(<MediaVideo file={f({ content_type: "image/gif" })} label="정면" />);
    expect(container.querySelector("video")).toBeNull();
    expect(screen.getByRole("img", { name: "컨투어 영상 — 정면" })).toBeTruthy();
  });

  it.each([
    ["avi", { content_type: "video/x-msvideo" }],
    ["playable=false", { playable: false }],
  ])("%s → 재생 시도 없이 안내 + 받기", (_n, o) => {
    const { container } = render(<MediaVideo file={f(o as Partial<MediaFile>)} label="정면" poster="blob:x" />);
    expect(container.querySelector("video")).toBeNull();
    const box = screen.getByTestId("video-unplayable");
    expect(box.textContent).toContain("브라우저가 이 형식을 재생하지 못합니다 —");
    expect(within(box).getByRole("link", { name: "받기" }).getAttribute("href")).toBe("/physicsai/api/artifacts/a-1/media?download=true");
    expect(within(box).getByRole("img").getAttribute("src")).toBe("blob:x");
  });

  it("video error 이벤트 → 안내로 전환, 포스터 유지", () => {
    const { container } = render(<MediaVideo file={f()} label="정면" poster="blob:p" />);
    fireEvent.error(container.querySelector("video")!);
    expect(container.querySelector("video")).toBeNull();
    const box = screen.getByTestId("video-unplayable");
    expect(within(box).getByRole("img").getAttribute("src")).toBe("blob:p");
    expect(within(box).getByRole("link", { name: "받기" })).toBeTruthy();
  });

  it("source error 이벤트 → 같은 안내", () => {
    const { container } = render(<MediaVideo file={f()} label="정면" />);
    fireEvent.error(container.querySelector("source")!);
    expect(screen.getByTestId("video-unplayable")).toBeTruthy();
  });

  it("상수 문구", () => {
    expect(MEDIA_TEXT.VIDEO_UNPLAYABLE).toBe("브라우저가 이 형식을 재생하지 못합니다 — 받기");
  });
});

describe("V3-S16-25 ContourMedia", () => {
  it("PARTIAL: 영상 없는 방향은 video_error 문구·버튼 title", async () => {
    renderApp(`${STUDY}/4`, { user: "general", capture: "PARTIAL" });
    const m = await screen.findByTestId("contour-media");
    fireEvent.click(await within(m).findByRole("button", { name: "윗면" }));
    expect(within(m).getByTestId("video-error").textContent).toContain("영상 없음 — 파일이 만들어지지 않았습니다(HyperView 성공 보고)");
    const btn = within(m).getByRole("button", { name: "영상" });
    expect(btn.hasAttribute("disabled")).toBe(true);
    expect(btn.getAttribute("title")).toContain("영상 없음 — 파일이");
  });

  it("avi 방향: 영상 토글 → 안내 + 받기, video 요소 없음", async () => {
    renderApp(`${STUDY}/4`, { user: "general" }, (s) => {
      s.videoTypes = { front: "video/x-msvideo" };
    });
    const m = await screen.findByTestId("contour-media");
    fireEvent.click(await within(m).findByRole("button", { name: "정면" }));
    fireEvent.click(within(m).getByRole("button", { name: "영상" }));
    expect(within(m).getByTestId("video-unplayable")).toBeTruthy();
    expect(m.querySelector("video")).toBeNull();
  });
});
