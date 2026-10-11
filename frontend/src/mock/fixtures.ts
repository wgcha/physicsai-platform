// 목 산출물 본문(컨투어 SVG·곡선 JSON·미리보기·학습 명령). data.ts가 재노출.
import { responseFn } from "./seed";

export function contourSvg(values: Record<string, number>): string {
  const t = values.THK_TOP ?? 0.6;
  const n = Math.round(values.RIB_N ?? 4);
  const ribs = Array.from({ length: n }, (_, i) => 70 + (i * 460) / Math.max(1, n - 1));
  const maxS = responseFn(values).MaxStress;
  const legend = ["#1d3fbf", "#1f7fd6", "#22b3c9", "#3cc76a", "#c9d62a", "#f2a81d", "#e5521b", "#c0151b"];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="560" viewBox="0 0 960 560">
<defs>
<radialGradient id="g" cx="${42 + t * 10}%" cy="48%" r="62%">
<stop offset="0" stop-color="#c0151b"/><stop offset="0.16" stop-color="#e5521b"/><stop offset="0.3" stop-color="#f2a81d"/>
<stop offset="0.44" stop-color="#c9d62a"/><stop offset="0.58" stop-color="#3cc76a"/><stop offset="0.72" stop-color="#22b3c9"/>
<stop offset="0.86" stop-color="#1f7fd6"/><stop offset="1" stop-color="#1d3fbf"/></radialGradient>
<pattern id="mesh" width="14" height="14" patternUnits="userSpaceOnUse"><path d="M14 0H0V14" fill="none" stroke="#000" stroke-opacity="0.14" stroke-width="0.6"/></pattern>
</defs>
<rect width="960" height="560" fill="#f4f5f7"/>
<g transform="translate(110 120)">
<rect x="0" y="0" width="600" height="300" rx="34" fill="url(#g)"/>
${ribs.map((x) => `<rect x="${x - 6}" y="18" width="12" height="264" rx="4" fill="#000" fill-opacity="0.12"/>`).join("")}
<rect x="0" y="0" width="600" height="300" rx="34" fill="url(#mesh)"/>
<rect x="0" y="0" width="600" height="300" rx="34" fill="none" stroke="#333" stroke-width="1.5"/>
</g>
<g transform="translate(800 110)" font-family="sans-serif" font-size="13" fill="#222">
<text x="0" y="-14" font-weight="600">von Mises [MPa]</text>
${legend
  .slice()
  .reverse()
  .map((c, i) => `<rect x="0" y="${i * 38}" width="26" height="38" fill="${c}"/><text x="34" y="${i * 38 + 5}">${((maxS * (8 - i)) / 8).toFixed(1)}</text>`)
  .join("")}
<text x="34" y="${8 * 38 + 4}">0.0</text>
</g>
<text x="110" y="470" font-family="sans-serif" font-size="13" fill="#555">Subcase 1 · Simulation 41 (t = 0.0120 s) · 예측 (목 이미지)</text>
</svg>`;
}

export function curveJson(values: Record<string, number>) {
  const r = responseFn(values);
  const x: number[] = [];
  const y: number[] = [];
  const y2: number[] = [];
  for (let i = 0; i <= 60; i++) {
    const tt = (i / 60) * 0.012;
    x.push(Number(tt.toFixed(5)));
    y.push(Number((r.MaxDisp * (1 - Math.exp(-i / 9)) * (1 + 0.08 * Math.sin(i / 3))).toFixed(4)));
    y2.push(Number((r.MaxDisp * 0.62 * (1 - Math.exp(-i / 14))).toFixed(4)));
  }
  return { file: "cushion_0000_pred_T01.xy", series: [{ name: "Node 10234 변위 [mm]", x, y }, { name: "Node 20811 변위 [mm]", x, y: y2 }], note: null };
}

export const PREVIEW_JSON = {
  file: "cushion_0000_pred.h3d",
  subcases: [{ name: "Subcase 1", simulations: 42, datatypes: ["Displacement", "Stress (von Mises)", "Plastic Strain"] }],
};

export const COMMANDS_TXT = `# PhysicsAI 학습 명령 예시 (HPC에서 직접 실행)
# 단위계: mm-ton-s. 이 폴더의 dataset_train.psdata는 학습용입니다(평가용 홀드아웃 제외).
edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg > train.log 2>&1
# 전이학습:
edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg --pretrained-model <PRETRAINED>.psmdl > train.log 2>&1
# 학습이 끝나면 .psmdl, 사용한 .pscfg, train.log를 한 폴더에 모아 플랫폼 ③-4 "모델 등록"에서 그 폴더 경로를 지정하세요.
# 로그의 loss 줄 예: "epoch=   1/1500  loss=1.03956e+02"
`;
