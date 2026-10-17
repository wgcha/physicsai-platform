const pptxgen = require('pptxgenjs');
const { applyTheme } = require('/mnt/skills/public/pptx/scripts/apply_theme.js');

const THEME = {
  name: 'PoC Report',
  headFontFace: 'Malgun Gothic',
  bodyFontFace: 'Malgun Gothic',
  colors: {
    dk1: '1E2328', lt1: 'FFFFFF', dk2: '1F3A4D', lt2: 'F2F4F6',
    accent1: 'D9771E', accent2: '2E7D6B', accent3: '5B7083', accent4: 'B8862B',
    accent5: '8A3B3B', accent6: '9AA7B2', hlink: '1F3A4D', folHlink: '5B7083',
  },
};
const HEX = { ink: '1E2328', navy: '1F3A4D', orange: 'D9771E', green: '2E7D6B', slate: '5B7083', light: 'F2F4F6', gray: '9AA7B2', amber: 'B8862B', white: 'FFFFFF' };

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = 'AI 기반 포장 예측 기술 플랫폼 개발 PoC 성과보고';
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: 'TITLE',
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: 'title', type: 'title', x: 0.8, y: 2.4, w: 11.7, h: 1.4, fontSize: 36, bold: true, color: C.background1, valign: 'bottom', align: 'left' }, text: '' } },
    { placeholder: { options: { name: 'body', type: 'body', x: 0.8, y: 4.0, w: 11.7, h: 1.2, fontSize: 18, color: C.background2, valign: 'top' }, text: '' } },
  ],
});
pres.defineSlideMaster({
  title: 'CONTENT',
  background: { color: C.background1 },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: 'title', type: 'title', x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 26, bold: true, color: C.text2, valign: 'middle', align: 'left', margin: 0 }, text: '' } },
    { text: { text: 'AI 기반 포장 예측 기술 플랫폼 PoC 성과보고', options: { x: 0.6, y: 7.0, w: 8, h: 0.3, fontSize: 10, color: C.accent3, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent3, align: 'right' },
});

const T = (slide, text, opt) => slide.addText(text, Object.assign({ isTextBox: true, margin: 0, color: C.text1, fontSize: 14, valign: 'top' }, opt));
const card = (slide, x, y, w, h, fill, name) => slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill || C.background2 }, line: { color: fill || C.background2 }, objectName: name });
const badge = (slide, x, y, n, color) => {
  slide.addShape(pres.shapes.OVAL, { x, y, w: 0.5, h: 0.5, fill: { color: color || C.accent1 }, line: { color: color || C.accent1 } });
  T(slide, String(n), { x, y, w: 0.5, h: 0.5, fontSize: 16, bold: true, color: C.background1, align: 'center', valign: 'middle' });
};
const imgSlot = (slide, x, y, w, h, label, sub) => {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.06, fill: { color: C.background2 }, line: { color: HEX.gray, width: 1.25, dashType: 'dash' }, objectName: label });
  T(slide, label, { x: x + 0.2, y: y + h / 2 - 0.35, w: w - 0.4, h: 0.35, fontSize: 14, bold: true, color: C.accent3, align: 'center', valign: 'middle' });
  if (sub) T(slide, sub, { x: x + 0.2, y: y + h / 2 + 0.02, w: w - 0.4, h: 0.6, fontSize: 11, color: C.accent3, align: 'center' });
};
const arrowR = (slide, x, y, w) => slide.addShape(pres.shapes.LINE, { x, y, w, h: 0, line: { color: HEX.gray, width: 1.5, endArrowType: 'triangle' } });
const arrowD = (slide, x, y, h, dash) => slide.addShape(pres.shapes.LINE, { x, y, w: 0, h, line: { color: HEX.gray, width: 1.5, endArrowType: 'triangle', dashType: dash ? 'dash' : 'solid' } });
const content = (sec, title) => { const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: sec }); s.addText(title, { placeholder: 'title' }); return s; };

// 1. Title
pres.addSection({ title: '표지' });
let s = pres.addSlide({ masterName: 'TITLE', sectionTitle: '표지' });
s.addText('AI 기반 포장 예측 기술 플랫폼 개발', { placeholder: 'title' });
s.addText('PoC 성과보고  |  2026. 10  |  차완기', { placeholder: 'body' });
s.addShape(pres.shapes.OVAL, { x: 0.8, y: 1.6, w: 0.5, h: 0.5, fill: { color: C.accent1 }, line: { color: C.accent1 } });
s.addNotes('표지. 보고 일자와 소속은 확정 후 수정.');

// 2. Summary
pres.addSection({ title: '본문' });
s = content('본문', 'DOE 입력 작성 시간 93% 저감, 설계탐색 기술 확보');
card(s, 0.6, 1.5, 4.6, 5.0, C.text2, 'summary-stat');
T(s, '93%', { x: 0.9, y: 2.0, w: 4.0, h: 1.4, fontSize: 72, bold: true, color: C.accent1 });
T(s, 'DOE 해석 입력 작성 시간 저감', { x: 0.9, y: 3.5, w: 4.0, h: 0.5, fontSize: 18, bold: true, color: C.background1 });
T(s, '케이스당 210분(수작업) → 15분(자동)', { x: 0.9, y: 4.05, w: 4.0, h: 0.4, fontSize: 14, color: C.background2 });
T(s, '동일 시간 기준 14배 많은 형상 검토 가능', { x: 0.9, y: 4.5, w: 4.0, h: 0.4, fontSize: 14, color: C.background2 });
const sumRows = [
  ['확보 기술', '형상 DOE 자동 생성부터 AI 예측·최적화까지 설계탐색 전 단계를 웹 플랫폼으로 연결'],
  ['적용 사례', 'TV 포장 쿠션 낙하 충격 성능 검증에 전 과정 적용'],
  ['향후 계획', '사내 드라이브·HPC 연동 완료 후 VD 메카그룹 해석 업무로 확산'],
];
sumRows.forEach((r, i) => {
  const y = 1.5 + i * 1.75;
  card(s, 5.6, y, 7.1, 1.5, C.background2, 'summary-' + i);
  badge(s, 5.85, y + 0.5, i + 1);
  T(s, r[0], { x: 6.6, y: y + 0.3, w: 5.8, h: 0.4, fontSize: 17, bold: true, color: C.text2 });
  T(s, r[1], { x: 6.6, y: y + 0.75, w: 5.8, h: 0.6, fontSize: 14 });
});
s.addNotes('요약 1장. 93% 저감 수치와 확보 기술, 적용 사례, 향후 계획.');

// 3. Background
s = content('본문', '기존 단일 FEM 검증 방식의 3가지 한계');
T(s, '설계안 1개를 FEM으로 해석해 불량 여부를 판정하는 방식', { x: 0.6, y: 1.35, w: 12.1, h: 0.4, fontSize: 16, color: C.accent3 });
const lim = [
  ['탐색 불가', '해석 1건당 설계안 1개만 검증 가능', '더 나은 형상 탐색 시 해석 반복 필요'],
  ['입력 작성 부담', '형상 변경 시마다 해석 입력 수작업 작성', '케이스당 약 210분 소요'],
  ['결과 분산', '해석 결과가 개인 작업 폴더에 분산', '재활용 및 AI 학습 데이터 활용 곤란'],
];
lim.forEach((r, i) => {
  const x = 0.6 + i * 4.15;
  card(s, x, 2.0, 3.8, 3.4, C.background2, 'limit-' + i);
  badge(s, x + 0.3, 2.3, i + 1, C.text2);
  T(s, r[0], { x: x + 0.3, y: 3.0, w: 3.2, h: 0.5, fontSize: 20, bold: true, color: C.text2 });
  T(s, [{ text: r[1], options: { bullet: true, breakLine: true } }, { text: r[2], options: { bullet: true } }], { x: x + 0.3, y: 3.65, w: 3.3, h: 1.5, fontSize: 14, paraSpaceAfter: 6 });
});
card(s, 0.6, 5.75, 12.1, 0.85, C.text2, 'goal');
T(s, '목표: 자동화와 AI 예측으로 세 한계를 해소, 설계 초기 단계에서 다수 형상을 신속 비교하는 체계 구축', { x: 0.9, y: 5.75, w: 11.5, h: 0.85, fontSize: 15, bold: true, color: C.background1, valign: 'middle' });
s.addNotes('추진 배경. 과제 기간은 확인 필요.');

// 4. Results
s = content('본문', '케이스당 210분 → 15분, 동일 시간 14배 형상 검토');
const stats = [['93%', 'DOE 입력 작성 시간 저감'], ['14배', '동일 시간 내 준비 가능한 형상 수'], ['162.5시간', 'DOE 50건 기준 절감 (175h → 12.5h)']];
stats.forEach((r, i) => {
  const x = 0.6 + i * 4.15;
  card(s, x, 1.4, 3.8, 1.5, C.background2, 'stat-' + i);
  T(s, r[0], { x: x + 0.3, y: 1.5, w: 3.2, h: 0.8, fontSize: 40, bold: true, color: C.accent1 });
  T(s, r[1], { x: x + 0.3, y: 2.3, w: 3.3, h: 0.45, fontSize: 13, color: C.accent3 });
});
const flowBox = (x, y, name, sub, hi) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 2.1, h: 0.9, rectRadius: 0.08, fill: { color: hi ? 'FBEBDC' : C.background1 }, line: { color: hi ? HEX.orange : HEX.gray, width: hi ? 2 : 1 } });
  T(s, name, { x, y: y + 0.12, w: 2.1, h: 0.35, fontSize: 14, bold: true, color: C.text1, align: 'center' });
  T(s, sub, { x, y: y + 0.5, w: 2.1, h: 0.3, fontSize: 12, bold: !!hi, color: hi ? C.text1 : C.accent3, align: 'center' });
};
T(s, '기존: 설계안 1개를 FEM 1회로 검증', { x: 0.6, y: 3.3, w: 8, h: 0.35, fontSize: 14, bold: true, color: C.accent3 });
[['설계안 1개', '형상 고정'], ['해석 입력 작성', '수작업 210분/건'], ['FEM 해석', '1회'], ['불량 판정', '1개 설계만 검증']].forEach((r, i) => {
  const x = 0.6 + i * 2.5; flowBox(x, 3.75, r[0], r[1], false); if (i < 3) arrowR(s, x + 2.12, 4.2, 0.36);
});
T(s, '개선: N개 형상을 자동 생성·학습해 최적 형상 탐색', { x: 0.6, y: 5.0, w: 8, h: 0.35, fontSize: 14, bold: true, color: C.text2 });
[['설계 변수 범위', '지정'], ['N개 형상 DOE', '자동 15분/건'], ['해석·수집', 'HPC 일괄 실행'], ['AI 학습', '예측 모델'], ['예측·최적화', '최적 형상 도출']].forEach((r, i) => {
  const x = 0.6 + i * 2.5; flowBox(x, 5.45, r[0], r[1], i === 1); if (i < 4) arrowR(s, x + 2.12, 5.9, 0.36);
});
s.addNotes('50건은 환산 예시. 실제 적용 케이스 수로 대체. 1일 8시간 기준.');

// 5. Technologies
s = content('본문', '설계탐색 전 단계를 하나의 웹 플랫폼으로 연결');
const lvl = { '검증 완료': HEX.green, '구현 완료': HEX.navy, '연동 검증 중': HEX.amber, '수동 운영': HEX.slate, '운영 중': HEX.green };
const techRows = [
  ['형상 DOE 해석 입력 자동 생성', '설계 변수 범위 지정 시 N개 형상과 해석 입력 일괄 생성', '검증 완료', '형상 변수가 있는 충격·낙하 해석 전반'],
  ['해석 실행·결과 수집', '생성된 입력을 HPC에 제출, 결과 자동 회수', '연동 검증 중', '사내 HPC 사용 해석 업무'],
  ['학습 데이터 큐레이션', '해석 결과를 학습용 데이터셋으로 정리', '구현 완료', 'AI 예측 적용 해석 업무'],
  ['AI 학습', '큐레이션 데이터로 예측 모델 학습 (HPC 수행)', '수동 운영', '동일'],
  ['AI 예측·최적화', '신규 형상 응답(contour, 곡선) 즉시 예측, 최적 형상 탐색', '구현 완료', '동일'],
  ['해석 결과 자산화·보고 자동화', '결과 통합 조회, Final 표준 저장, 보고서 자동 생성, SPDM 연계 (별첨)', '운영 중', '전 해석 업무'],
];
const hdr = ['기술', '내용', '수준', '재사용 범위'].map(t => ({ text: t, options: { bold: true, color: HEX.white, fill: { color: HEX.navy }, fontSize: 13 } }));
const body = techRows.map(r => [
  { text: r[0], options: { bold: true, fontSize: 13 } },
  { text: r[1], options: { fontSize: 13 } },
  { text: r[2], options: { bold: true, fontSize: 12, color: HEX.white, fill: { color: lvl[r[2]] }, align: 'center' } },
  { text: r[3], options: { fontSize: 12, color: HEX.slate } },
]);
s.addTable([hdr, ...body], { x: 0.6, y: 1.45, w: 12.1, colW: [2.9, 5.0, 1.5, 2.7], rowH: 0.62, valign: 'middle', border: { type: 'solid', pt: 0.75, color: 'D5DBE0' }, fontFace: 'Malgun Gothic', color: HEX.ink, margin: 0.08 });
T(s, '수준: 검증 완료(실업무 적용 확인) · 구현 완료(기능 동작 확인) · 연동 검증 중(사내 시스템 연결 시험 중) · 수동 운영(자동화 전) · 운영 중', { x: 0.6, y: 6.05, w: 12.1, h: 0.5, fontSize: 11, color: C.accent3 });
s.addNotes('확보 기술 6종과 수준. 그림 3-1 PhysicsAI 메인 화면은 필요 시 별도 장 추가.');

// 6. Case process
s = content('본문', 'TV 포장 쿠션 낙하에 전 과정 적용');
const steps = [['설계 변수 정의', '쿠션 형상 변수·범위 지정'], ['DOE 생성', 'N개 형상 해석 입력 자동 생성'], ['해석·수집', '낙하 해석 수행, 결과 수집'], ['학습', '해석 결과 기반 예측 모델'], ['예측·최적화', '충격 응답 예측, 최적 형상 탐색']];
steps.forEach((r, i) => {
  const x = 0.6 + i * 2.5;
  badge(s, x + 0.8, 1.45, i + 1);
  if (i < 4) arrowR(s, x + 1.4, 1.7, 1.8);
  T(s, r[0], { x, y: 2.1, w: 2.1, h: 0.4, fontSize: 15, bold: true, color: C.text2, align: 'center' });
  T(s, r[1], { x, y: 2.5, w: 2.1, h: 0.6, fontSize: 12, color: C.accent3, align: 'center' });
});
imgSlot(s, 0.6, 3.4, 7.2, 3.3, '[그림 4-1] DOE 형상 샘플', '자동 생성된 쿠션 형상 N개를 격자로 배열');
card(s, 8.1, 3.4, 4.6, 3.3, C.text2, 'perf');
T(s, '예측 성능', { x: 8.4, y: 3.65, w: 4.0, h: 0.4, fontSize: 17, bold: true, color: C.background1 });
T(s, [
  { text: 'FEM 대비 오차: [확인 필요]', options: { bullet: true, breakLine: true } },
  { text: '예측 1회: [확인 필요]초', options: { bullet: true, breakLine: true } },
  { text: 'FEM 해석 1회: [확인 필요]시간', options: { bullet: true, breakLine: true } },
  { text: 'DOE 케이스 수 N: [확인 필요]', options: { bullet: true } },
], { x: 8.4, y: 4.2, w: 4.1, h: 2.3, fontSize: 14, color: C.background1, paraSpaceAfter: 8 });
s.addNotes('적용 사례. 수치는 확인 후 기재.');

// 7. Demo screens
s = content('본문', '예측·최적화 결과 시연');
imgSlot(s, 0.6, 1.4, 5.9, 2.6, '[그림 4-2] 예측 contour vs FEM contour', '동일 형상의 AI 예측과 FEM 결과를 좌우 배치');
imgSlot(s, 6.8, 1.4, 5.9, 2.6, '[그림 4-3] 충격 응답 곡선 비교', '예측 곡선과 FEM 곡선 중첩');
imgSlot(s, 0.6, 4.25, 5.9, 2.6, '[그림 4-4] 최적화 결과 화면', '최적 형상과 기존 형상의 성능 비교');
imgSlot(s, 6.8, 4.25, 5.9, 2.6, '[시연 영상] 삽입 위치', '변수 입력 → 실행 → 예측 결과, 약 1~2분 (삽입 > 비디오)');
s.addNotes('시연 영상은 PowerPoint에서 삽입 > 비디오 > 이 디바이스로 넣고 자동 재생 설정.');

// 8. Next
s = content('본문', '실업무 정착을 위한 과제와 확산 계획');
const plan = [
  ['해석 실행 연동', '사내 드라이브·HPC 연동 시험 중', '연동 검증 후 DOE부터 결과 회수까지 자동화'],
  ['AI 학습', '해석 SDK 미지원으로 HPC에서 수동 수행', '학습 절차 표준화와 자동화 검토'],
  ['데이터 축적', '학습 데이터가 과제 범위 안에서만 생성', '대시보드 축적 대표 결과를 학습 데이터로 연계'],
  ['적용 범위', 'TV 포장 쿠션 1건 적용', 'VD 메카그룹 해석 업무로 확산'],
];
T(s, '현재 한계', { x: 3.3, y: 1.35, w: 4.0, h: 0.35, fontSize: 13, bold: true, color: C.accent3 });
T(s, '향후 계획', { x: 8.3, y: 1.35, w: 4.0, h: 0.35, fontSize: 13, bold: true, color: C.accent1 });
plan.forEach((r, i) => {
  const y = 1.8 + i * 1.2;
  card(s, 0.6, y, 2.4, 1.0, C.text2, 'plan-k-' + i);
  T(s, r[0], { x: 0.6, y, w: 2.4, h: 1.0, fontSize: 15, bold: true, color: C.background1, align: 'center', valign: 'middle' });
  card(s, 3.2, y, 4.3, 1.0, C.background2, 'plan-a-' + i);
  T(s, r[1], { x: 3.45, y, w: 3.9, h: 1.0, fontSize: 14, valign: 'middle' });
  arrowR(s, 7.6, y + 0.5, 0.5);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.2, y, w: 4.5, h: 1.0, rectRadius: 0.08, fill: { color: 'FBEBDC' }, line: { color: 'FBEBDC' } });
  T(s, r[2], { x: 8.45, y, w: 4.1, h: 1.0, fontSize: 14, bold: true, valign: 'middle' });
});
s.addNotes('한계와 향후 계획.');

// 9. Appendix dashboard
pres.addSection({ title: '별첨' });
s = content('별첨', '[별첨] 해석 결과 대시보드: 후처리·DB 축적·SPDM 연계');
const stack = (y, name, sub, hi) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y, w: 5.4, h: 1.05, rectRadius: 0.08, fill: { color: hi ? 'FBEBDC' : C.background1 }, line: { color: hi ? HEX.orange : HEX.gray, width: hi ? 2 : 1 } });
  T(s, name, { x: 0.85, y: y + 0.15, w: 5.0, h: 0.35, fontSize: 15, bold: true });
  T(s, sub, { x: 0.85, y: y + 0.55, w: 5.0, h: 0.4, fontSize: 12, color: C.accent3 });
};
stack(1.45, 'SPDM · 사내 드라이브', '의뢰 폴더 생성, 해석 입력·결과 원본 보관', false);
stack(3.25, '해석 결과 대시보드', '후처리 + 해석 DB 축적', true);
stack(5.05, 'PhysicsAI 플랫폼', 'DOE 생성, 학습, 예측·최적화', false);
arrowD(s, 1.9, 2.52, 0.7); T(s, '폴더 자동 동기화', { x: 2.05, y: 2.7, w: 1.9, h: 0.3, fontSize: 11, color: C.accent3 });
s.addShape(pres.shapes.LINE, { x: 4.4, y: 2.52, w: 0, h: 0.7, flipV: true, line: { color: HEX.gray, width: 1.5, endArrowType: 'triangle' } });
T(s, 'Final 자동 수집', { x: 4.55, y: 2.7, w: 1.6, h: 0.3, fontSize: 11, color: C.accent3 });
arrowD(s, 1.9, 4.32, 0.7, true); T(s, '학습 데이터 연계 (향후)', { x: 2.05, y: 4.5, w: 3.0, h: 0.3, fontSize: 11, color: C.accent3 });
const roles = [
  ['후처리', 'Case 전체 결과를 한 화면에서 조회(contour·영상·차트), PPTX/HTML 보고서 자동 생성', '운영 중'],
  ['해석 DB 축적', 'Final 지정 시 입력·결과는 Final/CAE, 보고서는 Final/Report에 표준 저장, 이력 누적', '운영 중'],
  ['SPDM 연계', 'SPDM 의뢰 폴더 기준 자동 등록, 주기 동기화·알림, Final 폴더 SPDM 자동 수집', '연동 검증 중'],
];
roles.forEach((r, i) => {
  const y = 1.45 + i * 1.8;
  card(s, 6.5, y, 6.2, 1.6, C.background2, 'role-' + i);
  T(s, r[0], { x: 6.8, y: y + 0.2, w: 3.5, h: 0.4, fontSize: 16, bold: true, color: C.text2 });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 10.9, y: y + 0.2, w: 1.55, h: 0.38, rectRadius: 0.19, fill: { color: lvl[r[2]] }, line: { color: lvl[r[2]] } });
  T(s, r[2], { x: 10.9, y: y + 0.2, w: 1.55, h: 0.38, fontSize: 11, bold: true, color: C.background1, align: 'center', valign: 'middle' });
  T(s, r[1], { x: 6.8, y: y + 0.7, w: 5.7, h: 0.8, fontSize: 13 });
});
s.addNotes('대시보드는 본 과제 AI 학습 데이터의 지속 공급 기반.');

// 10. Appendix screens
s = content('별첨', '[별첨] 대시보드 화면');
imgSlot(s, 0.6, 1.4, 3.85, 5.3, '[그림 1] 결과 조회 화면', '경로바와 결과 뷰');
imgSlot(s, 4.75, 1.4, 3.85, 5.3, '[그림 2] Final 지정 화면', '대표 Case 지정과 표준 저장');
imgSlot(s, 8.9, 1.4, 3.8, 5.3, '[그림 3] 보고서 생성 화면', 'PPTX/HTML 자동 생성');

(async () => {
  await pres.writeFile({ fileName: 'PoC_성과보고_초안.pptx' });
  await applyTheme('PoC_성과보고_초안.pptx', THEME);
  console.log('ok');
})();
