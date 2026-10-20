import { useEffect, useState } from "react";
import { api, errorMessage, type ReleasesResponse } from "../api";
import { TopBar } from "../shell/TopBar";
import { isNewVersion, readLastSeen, writeLastSeen } from "../lib/releases";

/** 버전 게시판(읽기 전용): 버전별 날짜·주요 기능. 기록은 배포(RELEASES.md)로만 — 이 화면에는 작성·수정·삭제가 없다 */
export function ReleaseBoard() {
  const [data, setData] = useState<ReleasesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastSeen] = useState<string | null>(() => readLastSeen()); // 들어올 때의 값으로 '새' 표시(본 기록이 없으면 최신만)
  useEffect(() => {
    let alive = true;
    api
      .releases()
      .then((r) => {
        if (!alive) return;
        setData(r);
        const top = r.releases[0]?.version ?? r.current_version;
        if (top) writeLastSeen(top);
      })
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, []);
  return (
    <div className="page">
      <TopBar crumbs={[{ label: "버전 게시판" }]} />
      <main className="page-main release-page" aria-label="버전 게시판">
        <h1 className="T">버전 게시판</h1>
        {data && <p className="muted small">현재 버전 v{data.current_version} · 배포할 때만 기록됩니다(읽기 전용)</p>}
        {error && <div className="empty" role="alert">{error}</div>}
        {data && data.releases.length === 0 && <div className="empty">버전 기록이 없습니다</div>}
        {data && data.releases.length > 0 && (
          <ol className="release-list">
            {data.releases.map((r, i) => (
              <li key={r.version} className={`release-item${i === 0 ? " latest" : ""}`} data-testid={`release-${r.version}`}>
                <div className="release-head">
                  <strong className="release-version">v{r.version}</strong>
                  <span className="muted">{r.date}</span>
                  {i === 0 && <span className="release-tag latest">최신</span>}
                  {r.version === data.current_version && i !== 0 && <span className="release-tag">사용 중</span>}
                  {(lastSeen === null ? i === 0 : isNewVersion(r.version, lastSeen)) && <span className="release-tag new">새 버전</span>}
                </div>
                <ul className="release-items">
                  {r.items.map((it, k) => (
                    <li key={k}>{it}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )}
      </main>
    </div>
  );
}
