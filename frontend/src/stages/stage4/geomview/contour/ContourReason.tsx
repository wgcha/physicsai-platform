// 3D 대신 PNG·빈 칸이 나오는 칸의 사유 한 줄(contour3d-field §12): 칸 맨 위, 작은 회색, 길면 말줄임 + title 전체.
export function ReasonLine({ text, testid, tone }: { text: string; testid?: string; tone?: "error" }) {
  return (
    <p className={`contour-slot-reason small ${tone === "error" ? "error-text" : "muted"}`} title={text} data-testid={testid ?? "contour-slot-reason"}>
      {text}
    </p>
  );
}
