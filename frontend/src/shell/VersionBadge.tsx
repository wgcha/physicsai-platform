import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { LAST_SEEN_EVENT, isNewVersion, readLastSeen } from "../lib/releases";

/** 상단 바 버전 배지(v0.2.0) → 버전 게시판. 마지막으로 본 버전보다 새로우면 '새' 점. 조회 실패면 숨김 */
export function VersionBadge() {
  const [version, setVersion] = useState<string | null>(null);
  const [lastSeen, setLastSeen] = useState<string | null>(() => readLastSeen());
  useEffect(() => {
    const on = () => setLastSeen(readLastSeen());
    window.addEventListener(LAST_SEEN_EVENT, on);
    return () => window.removeEventListener(LAST_SEEN_EVENT, on);
  }, []);
  useEffect(() => {
    let alive = true;
    api
      .version()
      .then((v) => alive && setVersion(v.platform_version))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  if (!version) return null;
  const fresh = isNewVersion(version, lastSeen);
  return (
    <Link to="/releases" className="version-badge R" data-testid="version-badge" title={fresh ? "새 버전 — 버전 게시판에서 주요 기능 보기" : "버전 게시판"}>
      v{version}
      {fresh && <span className="version-new" data-testid="version-new" aria-label="새 버전" />}
    </Link>
  );
}
