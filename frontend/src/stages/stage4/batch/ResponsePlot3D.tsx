// ④ B 응답 그래프 3D(phase3.md §14.8): x·y = 변수 2개, z = 응답 산점, 체크 "보간면"(기본 끔) = Delaunay 삼각면(mesh3d delaunayaxis z).
// plotly.js-gl3d-dist-min@2.35.2를 동적 import(별도 청크, frontend-dist 포함 — CDN 없음). WebGL이 없으면 안내 한 줄.
import { useEffect, useRef, useState } from "react";

export const NO_WEBGL_TEXT = "3D 그래프를 표시할 수 없습니다(WebGL 없음)";

export interface Pt3 {
  doe_no: number;
  run_key: string;
  x: number;
  y: number;
  z: number;
}

export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl") || c.getContext("experimental-webgl"));
  } catch {
    return false;
  }
}

function cssVar(name: string, fallback: string): string {
  try {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  } catch {
    return fallback;
  }
}

export function ResponsePlot3D({ pts, labels, selected, onSelect }: { pts: Pt3[]; labels: [string, string, string]; selected: number | null; onSelect: (doe: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [surface, setSurface] = useState(false);
  const [gl] = useState(hasWebGL);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const pick = useRef(onSelect);
  pick.current = onSelect;

  useEffect(() => {
    const el = ref.current;
    if (!gl || !el) return;
    let alive = true;
    import("plotly.js-gl3d-dist-min")
      .then(async (mod) => {
        if (!alive) return;
        const Plotly = mod.default;
        const ink = cssVar("--ink", "#111111");
        const ink3 = cssVar("--ink-3", "#9a9ca0");
        const red = cssVar("--red", "#d52b1e");
        const grid = cssVar("--rule-soft", "#d9dadc");
        const size = parseFloat(cssVar("--r-size", "12px")) || 12;
        const axis = (title: string) => ({ title: { text: title }, gridcolor: grid, zerolinecolor: grid, color: ink });
        const data: Record<string, unknown>[] = [
          {
            type: "scatter3d",
            mode: "markers",
            x: pts.map((p) => p.x),
            y: pts.map((p) => p.y),
            z: pts.map((p) => p.z),
            customdata: pts.map((p) => p.doe_no),
            text: pts.map((p) => `DOE #${p.doe_no}`),
            hovertemplate: `%{text}<br>${labels[0]} %{x}<br>${labels[1]} %{y}<br>${labels[2]} %{z}<extra></extra>`,
            marker: { size: pts.map((p) => (p.doe_no === selected ? 7 : 4)), color: pts.map((p) => (p.doe_no === selected ? red : ink)) },
          },
        ];
        if (surface && pts.length >= 3)
          data.push({ type: "mesh3d", x: pts.map((p) => p.x), y: pts.map((p) => p.y), z: pts.map((p) => p.z), delaunayaxis: "z", opacity: 0.35, color: ink3, hoverinfo: "skip" });
        const layout = {
          margin: { l: 0, r: 0, t: 0, b: 0 },
          paper_bgcolor: "rgba(0,0,0,0)",
          font: { family: cssVar("--sans", "sans-serif"), size, color: ink },
          showlegend: false,
          scene: { xaxis: axis(labels[0]), yaxis: axis(labels[1]), zaxis: axis(labels[2]) },
        };
        const gd = await Plotly.react(el, data, layout, { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["toImage"] });
        if (!alive) return;
        gd.removeAllListeners?.("plotly_click");
        gd.on?.("plotly_click", (e) => {
          const d = e.points[0]?.customdata;
          if (typeof d === "number") pick.current(d);
        });
        setState("ready");
      })
      .catch(() => alive && setState("error"));
    return () => {
      alive = false;
    };
  }, [gl, pts, labels, selected, surface]);

  useEffect(() => {
    const el = ref.current;
    return () => {
      if (el) void import("plotly.js-gl3d-dist-min").then((m) => m.default.purge(el)).catch(() => undefined);
    };
  }, []);

  if (!gl)
    return (
      <p className="muted small" data-testid="plot3d-nogl">
        {NO_WEBGL_TEXT}
      </p>
    );
  return (
    <div className="rplot3d">
      <label className="inline-field small">
        <input type="checkbox" checked={surface} onChange={(e) => setSurface(e.target.checked)} />
        보간면
      </label>
      <div ref={ref} className="plot3d" data-testid="plot3d" role="img" aria-label={`응답 그래프 3D: ${labels.join(" – ")}`} />
      {state === "loading" && <p className="muted small">3D 그래프를 불러오는 중…</p>}
      {state === "error" && <p className="error-text small">3D 그래프를 불러오지 못했습니다</p>}
    </div>
  );
}
