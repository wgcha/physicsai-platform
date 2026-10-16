// 커브 다운샘플(phase3.md §14.7 curves): 구간별 최소·최대를 보존해 점 수를 maxPoints 이하로 줄인다.
// 목 서버(curves API)와 화면(커브 겹쳐보기 상한 방어)이 같이 쓴다.

/** x 순서를 유지하며 구간마다 y 최소·최대 점(같으면 1개)만 남긴다. 처음·끝 점은 항상 남긴다 */
export function downsampleMinMax(x: number[], y: number[], maxPoints: number): { x: number[]; y: number[] } {
  const n = Math.min(x.length, y.length);
  if (n <= maxPoints || maxPoints < 4) return { x: x.slice(0, n), y: y.slice(0, n) };
  const buckets = Math.max(1, Math.floor((maxPoints - 2) / 2));
  const idx: number[] = [0];
  const inner = n - 2;
  for (let b = 0; b < buckets; b++) {
    const lo = 1 + Math.floor((b * inner) / buckets);
    const hi = 1 + Math.floor(((b + 1) * inner) / buckets);
    if (hi <= lo) continue;
    let iMin = lo;
    let iMax = lo;
    for (let i = lo; i < hi; i++) {
      if (y[i] < y[iMin]) iMin = i;
      if (y[i] > y[iMax]) iMax = i;
    }
    if (iMin === iMax) idx.push(iMin);
    else idx.push(Math.min(iMin, iMax), Math.max(iMin, iMax));
  }
  idx.push(n - 1);
  return { x: idx.map((i) => x[i]), y: idx.map((i) => y[i]) };
}
