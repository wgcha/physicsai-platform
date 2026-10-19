// FEM 검증 "컨투어" 탭(phase3 §21.3.11): 두 열 예측 | FEM, 방향 버튼·영상 토글 공유, 범례 한 줄, 이미지·영상 받기. 영상은 MediaVideo(V3).
import { useCallback, useEffect, useState } from "react";
import { errorMessage, type ViewKey } from "../../../api";
import { femVerifyApi, type FemCompare, type FemMedia, type FemMediaSide } from "../../../api/femVerify";
import { MediaVideo, mediaHref } from "../../../components/MediaVideo";
import { viewLabel } from "../../../lib/views";
import { useMediaImage } from "../ContourMedia";
import { legendText } from "./verifyRules";

function Side({ title, side, view, video, label, dl }: { title: string; side: FemMediaSide | null; view: string; video: boolean; label: string; dl: string }) {
  const img = useMediaImage(side?.image.url ?? null);
  const showVideo = video && !!side?.video;
  return (
    <div data-testid={`fv-side-${title}`}>
      <div className="fv-side-head">
        <b>{title}</b>
      </div>
      {!side ? (
        <p className="muted small">이 결과에는 고른 방향의 캡처가 없습니다 ({viewLabel(view)})</p>
      ) : showVideo ? (
        <MediaVideo file={side.video!} poster={img} label={`${title} ${label}`} downloadName={`${dl}_${title}_${view}`} />
      ) : img ? (
        <img src={img} alt={`${title} 컨투어 — ${label}`} className="contour-img" />
      ) : (
        <div className="empty small">불러오는 중…</div>
      )}
      {side && !side.video && side.video_error && (
        <p className="muted small" data-testid="video-error">
          영상 없음 — {side.video_error}
        </p>
      )}
      {side && (
        <div className="run-action-row">
          <a className="btn small ghost" href={img ?? mediaHref(side.image.download_url)} download={`${dl}_${title}_${view}.png`}>
            이미지 받기
          </a>
          {side.video && (
            <a className="btn small ghost" href={mediaHref(side.video.download_url)} download>
              영상 받기
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export function ContourCompare({ fid, label, legend }: { fid: string; label: string; legend: FemCompare["legend"] }) {
  const [media, setMedia] = useState<FemMedia | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewKey | null>(null);
  const [video, setVideo] = useState(false);
  const load = useCallback(async () => {
    try {
      setMedia(await femVerifyApi.media(fid));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [fid]);
  useEffect(() => {
    setMedia(null);
    void load();
  }, [load]);

  const items = media?.items ?? [];
  const curKey = view ?? items[0]?.view ?? null;
  const cur = items.find((i) => i.view === curKey) ?? null;
  const hasVideo = !!(cur?.pred?.video || cur?.fem?.video);
  const lg = legendText(media?.legend ?? legend);

  return (
    <div className="fv-section" data-testid="fv-contours">
      <div className="cm-head">
        {items.length > 0 && (
          <div className="seg cm-views" role="group" aria-label="방향">
            {items.map((i) => (
              <button key={i.view} type="button" className={i.view === curKey ? "on" : ""} aria-pressed={i.view === curKey} onClick={() => setView(i.view)}>
                {i.label || viewLabel(i.view)}
              </button>
            ))}
          </div>
        )}
        {items.length > 0 && (
          <button type="button" className={`btn small${video && hasVideo ? " on" : ""}`} aria-pressed={video && hasVideo} disabled={!hasVideo} title={hasVideo ? "같은 방향의 애니메이션 영상" : "이 방향은 영상이 없습니다"} onClick={() => setVideo((x) => !x)}>
            영상
          </button>
        )}
        {lg && (
          <span className="muted small" data-testid="fv-legend">
            {lg}
          </span>
        )}
      </div>
      {error && <p className="error-text small" role="alert">{error}</p>}
      {!media && !error && <div className="empty small">불러오는 중…</div>}
      {media && !items.length && <p className="muted small">저장된 컨투어가 없습니다{media.status === "NONE" ? "" : ` (${media.status})`}.</p>}
      {cur && (
        <div className="fv-compare">
          <Side title="예측" side={cur.pred} view={cur.view} video={video} label={cur.label || viewLabel(cur.view)} dl={label} />
          <Side title="FEM" side={cur.fem} view={cur.view} video={video} label={cur.label || viewLabel(cur.view)} dl={label} />
        </div>
      )}
    </div>
  );
}
