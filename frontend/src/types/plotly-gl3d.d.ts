// plotly.js-gl3d-dist-min@2.35.2(npm 번들, 동적 import로 별도 청크 — CDN 없음): 쓰는 함수만 최소 선언(phase3.md §14.8).
declare module "plotly.js-gl3d-dist-min" {
  interface PlotlyEvent {
    points: { customdata?: unknown; pointNumber?: number }[];
  }
  interface PlotlyElement extends HTMLElement {
    on?: (event: "plotly_click", cb: (e: PlotlyEvent) => void) => void;
    removeAllListeners?: (event: string) => void;
  }
  const Plotly: {
    react: (el: HTMLElement, data: Record<string, unknown>[], layout: Record<string, unknown>, config?: Record<string, unknown>) => Promise<PlotlyElement>;
    purge: (el: HTMLElement) => void;
  };
  export default Plotly;
}
