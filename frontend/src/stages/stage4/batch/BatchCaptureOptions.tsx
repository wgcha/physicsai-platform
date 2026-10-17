// ④ B 일괄 예측 컨투어 캡처 옵션(phase3.md D3-53): 켜기·방향·영상 포함 + 예상 디스크·시간 참고 1줄(회색).
// 기본값 = 템플릿 display.views → /status.capture.views, 영상 = /status.capture.video. 기본과 같으면 params에 넣지 않는다.
// 예상 문구 가정값 = /status.capture.estimate(config capture.estimate_*, D3-54).
import type { PredictBatchCapture, ViewKey } from "../../../api";
import { VIEW_KEYS, viewLabel } from "../../../lib/views";

export interface CaptureChoice {
  enabled: boolean;
  views: ViewKey[];
  video: boolean;
}

/** 참고용 가정(서버 실측 아님): 방향 1개당 이미지·영상 크기, HyperView 캡처 시간. 실제 값은 /status.capture.estimate
 * (config capture.estimate_*, D3-54) — 이 상수는 그 기본값(영상 1개당 1 MB 이내)과 같고 /status에 없을 때만 쓴다 */
export const CAPTURE_ASSUME: CaptureAssume = { imageMb: 0.3, videoMb: 1, secPerView: 20, secPerVideo: 40 };

export interface CaptureAssume {
  imageMb: number;
  videoMb: number;
  secPerView: number;
  secPerVideo: number;
}

/** /status.capture.estimate → 가정값(없으면 CAPTURE_ASSUME) */
export function captureAssume(est?: { image_mb: number; video_mb: number; sec_per_view: number; sec_per_video: number } | null): CaptureAssume {
  return est ? { imageMb: est.image_mb, videoMb: est.video_mb, secPerView: est.sec_per_view, secPerVideo: est.sec_per_video } : CAPTURE_ASSUME;
}

/** 선택 → PREDICT_BATCH params.capture(기본과 같으면 undefined, 끄면 {enabled:false}) */
export function captureParam(c: CaptureChoice, defViews: ViewKey[], defVideo: boolean): PredictBatchCapture | undefined {
  if (!c.enabled) return { enabled: false };
  const out: PredictBatchCapture = { enabled: true };
  const same = c.views.length === defViews.length && c.views.every((v, i) => v === defViews[i]);
  if (!same) out.views = c.views;
  if (c.video !== defVideo) out.video = c.video;
  return out.views || out.video !== undefined ? out : undefined;
}

const fmtMb = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`);

/** 예상 참고 문구: run 수 × 방향 수 */
export function captureEstimate(runs: number, c: CaptureChoice, a: CaptureAssume = CAPTURE_ASSUME): string {
  const n = runs * c.views.length;
  const mb = n * (a.imageMb + (c.video ? a.videoMb : 0));
  const min = (n * (a.secPerView + (c.video ? a.secPerVideo : 0))) / 60;
  return `캡처 예상: run ${runs} × 방향 ${c.views.length} = 이미지 ${n}장${c.video ? ` + 영상 ${n}개` : ""} · 디스크 약 ${fmtMb(mb)} · 시간 약 ${Math.max(1, Math.round(min))}분 추가(가정값 기준 참고)`;
}

export function BatchCaptureOptions({ value, onChange, runs, assume = CAPTURE_ASSUME }: { value: CaptureChoice; onChange: (c: CaptureChoice) => void; runs: number | null; assume?: CaptureAssume }) {
  const toggle = (v: ViewKey) => {
    const has = value.views.includes(v);
    const next = has ? value.views.filter((x) => x !== v) : VIEW_KEYS.filter((k) => k === v || value.views.includes(k));
    onChange({ ...value, views: next });
  };
  return (
    <div className="batch-capture" data-testid="batch-capture">
      <label className="check">
        <input type="checkbox" checked={value.enabled} onChange={(e) => onChange({ ...value, enabled: e.target.checked })} />
        컨투어 캡처
      </label>
      {value.enabled && (
        <>
          <span className="fill-row" role="group" aria-label="캡처 방향">
            {VIEW_KEYS.map((v) => (
              <label key={v} className="check">
                <input type="checkbox" checked={value.views.includes(v)} onChange={() => toggle(v)} />
                {viewLabel(v)}
              </label>
            ))}
          </span>
          <label className="check">
            <input type="checkbox" checked={value.video} onChange={(e) => onChange({ ...value, video: e.target.checked })} />
            영상 포함
          </label>
          {runs != null && runs > 0 && value.views.length > 0 && <p className="muted small">{captureEstimate(runs, value, assume)}</p>}
        </>
      )}
    </div>
  );
}
