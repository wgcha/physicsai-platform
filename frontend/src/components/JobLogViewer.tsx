import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { usePolling } from "../hooks/usePolling";
import { POLL } from "../lib/poll";

/** 로그 뷰어: 열면 커서 폴링(실행 중일 때 2초), 자동 스크롤 토글(§16.3) */
export function JobLogViewer({ jobId, running }: { jobId: string; running: boolean }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const cursor = useRef(0);
  const pre = useRef<HTMLPreElement>(null);

  useEffect(() => {
    cursor.current = 0;
    setText("");
  }, [jobId]);

  const load = useCallback(async () => {
    try {
      let eof = false;
      let guard = 0;
      while (!eof && guard++ < 8) {
        const c = await api.jobLog(jobId, cursor.current);
        if (c.text) setText((t) => (t + c.text).slice(-400_000));
        cursor.current = c.next_cursor;
        eof = c.eof;
      }
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [jobId]);

  usePolling(load, running ? POLL.log : 3_600_000, true, [jobId]);

  useEffect(() => {
    if (follow && pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [text, follow]);

  return (
    <div className="logview">
      <div className="logview-bar">
        <label className="check small">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> 자동 스크롤
        </label>
        {error && <span className="error-text small">{error}</span>}
      </div>
      <pre ref={pre}>{text || "로그 없음"}</pre>
    </div>
  );
}
