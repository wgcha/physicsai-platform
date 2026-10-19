// S16 V3(§21.4.6): 영상 1개 표시. gif → <img>, avi·playable=false → 재생 시도 없이 안내 + 받기,
// 그 밖 → <video controls> — 재생 오류(video·마지막 source·metadata 전 error)가 나면 같은 안내로 바꾼다(포스터는 남김).
import { useEffect, useState } from "react";
import { API_PREFIX, type MediaFile } from "../api";

export const VIDEO_UNPLAYABLE = "브라우저가 이 형식을 재생하지 못합니다 — 받기";

/** 서버가 준 내려받기 경로 → 브라우저 주소(API 접두어 없으면 붙인다) */
export function mediaHref(url: string): string {
  if (/^https?:\/\//.test(url) || url.startsWith(API_PREFIX)) return url;
  return API_PREFIX + (url.startsWith("/") ? url : `/${url}`);
}

export function isUnplayable(file: MediaFile): boolean {
  return file.content_type === "video/x-msvideo" || file.playable === false;
}

export function MediaVideo({ file, poster, label, downloadName, className = "contour-img" }: { file: MediaFile; poster?: string | null; label: string; downloadName?: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [file.url]);

  if (file.content_type === "image/gif") return <img src={mediaHref(file.url)} alt={`컨투어 영상 — ${label}`} className={className} />;

  if (failed || isUnplayable(file)) {
    return (
      <div className="media-video-fail" data-testid="video-unplayable">
        {poster && <img src={poster} alt={`컨투어 — ${label}`} className={className} />}
        <p className="muted small">
          브라우저가 이 형식을 재생하지 못합니다 —{" "}
          <a href={mediaHref(file.download_url)} download={downloadName ?? true}>
            받기
          </a>
        </p>
      </div>
    );
  }

  return (
    <video
      key={file.url}
      className={className}
      controls
      preload="metadata"
      poster={poster ?? undefined}
      aria-label={`컨투어 영상 — ${label}`}
      onError={() => setFailed(true)}
    >
      <source src={mediaHref(file.url)} type={file.content_type ?? undefined} onError={() => setFailed(true)} />
    </video>
  );
}
