// S10 "컨투어" 칸: 예측 끝에 저장된 방향별 스크린샷(PNG)·애니메이션 동영상을 목록에서 골라 본다.
// 위 방향 버튼 그룹(←→ 키) · 이미지 / "영상" 토글 시 <video controls>(같은 방향) · 내려받기 · 상태 회색 문구 · 다시 캡처(power 이상).
// 방향은 부모가 쥘 수 있다(B 결과: run을 바꿔도 같은 방향으로 비교).
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { API_PREFIX, ApiError, TERMINAL_STATES, api, errorMessage, type CaptureRequest, type Job, type JobMedia, type ViewKey } from "../../api";
import { usePolling } from "../../hooks/usePolling";
import { POLL } from "../../lib/poll";
import { DEFAULT_VIEWS, VIEW_KEYS, viewLabel } from "../../lib/views";

export const MEDIA_TEXT = {
  NONE: "저장된 컨투어 스크린샷·영상이 없습니다",
  PARTIAL: "일부 방향만 캡처되었습니다",
  FAILED: "컨투어 캡처에 실패했습니다",
  DISABLED: "컨투어 캡처가 꺼져 있습니다(관리자 설정)",
  SKIPPED: "컨투어 캡처를 하지 않았습니다(표시 설정 없음)",
  MISSING_VIEW: "이 결과에는 고른 방향의 캡처가 없습니다",
} as const;

/** 서버가 준 내려받기 경로 → 브라우저 주소(API 접두어 없으면 붙인다) */
export function mediaHref(url: string): string {
  if (/^https?:\/\//.test(url) || url.startsWith(API_PREFIX)) return url;
  return API_PREFIX + (url.startsWith("/") ? url : `/${url}`);
}

/** 이미지는 fetch → blob URL(목 서버·쿠키 인증 모두 같은 길) */
function useMediaImage(url: string | null): string | null {
  const [obj, setObj] = useState<string | null>(null);
  useEffect(() => {
    setObj(null);
    if (!url) return;
    let alive = true;
    let made: string | null = null;
    api
      .mediaBlob(url)
      .then((b) => {
        if (!alive) return;
        made = URL.createObjectURL(b);
        setObj(made);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url]);
  return obj;
}

export function ContourMedia({
  jobId,
  view: viewProp,
  onView,
  canCapture,
  captureViews,
}: {
  jobId: string;
  /** 부모가 쥔 방향(null = 첫 방향) */
  view?: ViewKey | null;
  onView?: (v: ViewKey) => void;
  canCapture: boolean;
  /** 다시 캡처 체크 기본값(없으면 지금 방향들 → 기본 4방향) */
  captureViews?: ViewKey[] | null;
}) {
  const [media, setMedia] = useState<JobMedia | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [localView, setLocalView] = useState<ViewKey | null>(null);
  const [video, setVideo] = useState(false);
  const groupRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setMedia(await api.jobMedia(jobId));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMedia({ job_id: jobId, items: [], status: "NONE", capture_enabled: false, can_recapture: false });
      else setError(errorMessage(e));
    }
  }, [jobId]);
  useEffect(() => {
    setMedia(null);
    setError(null);
    void load();
  }, [load]);

  const views = media?.items ?? [];
  const want = viewProp !== undefined ? viewProp : localView;
  const curKey = want ?? views[0]?.view ?? null;
  const cur = views.find((v) => v.view === curKey) ?? null;
  const img = useMediaImage(cur?.image.url ?? null);
  const videoUrl = cur?.video?.url ?? null;
  const showVideo = video && !!videoUrl;

  const pick = (v: ViewKey) => {
    setLocalView(v);
    onView?.(v);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key) || !views.length) return;
    e.preventDefault();
    const i = Math.max(0, views.findIndex((v) => v.view === curKey));
    const n = e.key === "Home" ? 0 : e.key === "End" ? views.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + views.length) % views.length;
    pick(views[n].view);
    groupRef.current?.querySelectorAll("button")[n]?.focus();
  };

  const label = cur?.label || (curKey ? viewLabel(curKey) : "");
  const note = !media
    ? null
    : !media.capture_enabled && !views.length
      ? MEDIA_TEXT.DISABLED
      : media.status === "SKIPPED" && !views.length
        ? MEDIA_TEXT.SKIPPED
        : media.status === "FAILED"
        ? MEDIA_TEXT.FAILED
          : media.status === "PARTIAL"
            ? MEDIA_TEXT.PARTIAL
            : !views.length
              ? MEDIA_TEXT.NONE
              : null;

  return (
    <div className="contour contour-media" data-testid="contour-media">
      <div className="cm-head">
        <span className="field-label">컨투어</span>
        {views.length > 0 && (
          <div className="seg cm-views" role="group" aria-label="방향" ref={groupRef} onKeyDown={onKey}>
            {views.map((v) => (
              <button key={v.view} type="button" className={v.view === curKey ? "on" : ""} aria-pressed={v.view === curKey} onClick={() => pick(v.view)}>
                {v.label || viewLabel(v.view)}
              </button>
            ))}
          </div>
        )}
        {views.length > 0 && (
          <button
            type="button"
            className={`btn small${showVideo ? " on" : ""}`}
            aria-pressed={showVideo}
            disabled={!videoUrl}
            title={videoUrl ? "같은 방향의 애니메이션 영상" : "이 방향은 영상이 없습니다"}
            onClick={() => setVideo((x) => !x)}
          >
            영상
          </button>
        )}
      </div>

      {!media && !error && <div className="empty small">불러오는 중…</div>}
      {error && (
        <p className="error-text small" role="alert">
          {error}
        </p>
      )}
      {note && (
        <p className="muted small" data-testid="media-status">
          {note}
          {media?.message ? ` — ${media.message}` : ""}
        </p>
      )}

      {cur ? (
        showVideo ? (
          <video key={videoUrl} className="contour-img" controls preload="metadata" poster={img ?? undefined} aria-label={`컨투어 영상 — ${label}`}>
            <source src={mediaHref(videoUrl!)} type={cur.video?.content_type ?? undefined} />
          </video>
        ) : img ? (
          <img src={img} alt={`예측 컨투어 — ${label}`} className="contour-img" />
        ) : (
          <div className="empty small">불러오는 중…</div>
        )
      ) : (
        views.length > 0 && <p className="muted small">{MEDIA_TEXT.MISSING_VIEW} ({viewLabel(String(curKey))})</p>
      )}

      {cur && (
        <div className="run-action-row">
          <a className="btn small ghost" href={img ?? mediaHref(cur.image.download_url)} download={`contour_${jobId.slice(0, 8)}_${cur.view}.png`}>
            이미지 받기
          </a>
          {cur.video && (
            <a className="btn small ghost" href={mediaHref(cur.video.download_url)} download>
              영상 받기
            </a>
          )}
        </div>
      )}

      {canCapture && media && (media.can_recapture || !!media.recapture?.active) && <Recapture jobId={jobId} serverBusy={!!media.recapture?.active} initial={captureViews?.length ? captureViews : views.length ? views.map((v) => v.view) : media.display?.views?.length ? media.display.views : DEFAULT_VIEWS} onDone={load} />}
    </div>
  );
}

/** 다시 캡처: 방향 체크 → POST /jobs/{id}/capture {views} → 201 CONTOUR_RECAPTURE 작업이 끝나면 목록을 다시 읽는다 */
function Recapture({ jobId, initial, serverBusy, onDone }: { jobId: string; initial: ViewKey[]; serverBusy: boolean; onDone: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState<ViewKey[]>(initial);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keys = [...VIEW_KEYS, ...checked.filter((v) => !VIEW_KEYS.includes(v))];
  const running = !!job && !TERMINAL_STATES.includes(job.state);

  usePolling(
    async () => {
      if (!job) return;
      const j = await api.job(job.id);
      setJob(j);
      if (TERMINAL_STATES.includes(j.state)) {
        if (j.state !== "SUCCEEDED") setError(`다시 캡처 ${j.state === "CANCELED" ? "취소" : "실패"}${j.failure_message ? ` — ${j.failure_message}` : ""}`);
        await onDone();
      }
    },
    running ? POLL.jobActive : null,
    false,
    [job?.id],
  );

  const request = async () => {
    setBusy(true);
    setError(null);
    try {
      setJob(await api.captureJob(jobId, { views: keys.filter((k) => checked.includes(k)) as CaptureRequest["views"] }));
      setOpen(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cm-capture">
      <div className="run-action-row">
        <button type="button" className="btn small" aria-expanded={open} disabled={running || serverBusy} onClick={() => setOpen((x) => !x)}>
          다시 캡처
        </button>
        {(running || (serverBusy && !job)) && <span className="muted small">캡처 중…</span>}
        {error && (
          <span className="error-text small" role="alert">
            {error}
          </span>
        )}
      </div>
      {open && (
        <fieldset className="cm-capture-form">
          <legend className="field-label">캡처할 방향</legend>
          <div className="checks">
            {keys.map((k) => (
              <label key={k} className="check small">
                <input type="checkbox" checked={checked.includes(k)} onChange={(e) => setChecked(e.target.checked ? [...checked, k] : checked.filter((x) => x !== k))} />
                {viewLabel(k)}
              </label>
            ))}
          </div>
          <div className="run-action-row">
            <button type="button" className="btn small primary" disabled={!checked.length || busy} onClick={request}>
              {busy ? "요청 중…" : "캡처 요청"}
            </button>
            <span className="muted small">HyperView로 방향별 이미지·영상을 다시 저장합니다</span>
          </div>
        </fieldset>
      )}
    </div>
  );
}
