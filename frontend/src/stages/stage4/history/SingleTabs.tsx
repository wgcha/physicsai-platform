// ④ 템플릿 값 입력·준비된 입력 파일 아래 하위 탭 "새 예측 | 실행 목록"(phase3 §21.2.3). 선택은 브라우저별로 기억(try/catch).
import { Card } from "../../../components/ui";

export type SingleTab = "new" | "list";
export const SINGLE_TAB_KEY = "physicsai.stage4.singleTab";
const TABS: { key: SingleTab; label: string }[] = [
  { key: "new", label: "새 예측" },
  { key: "list", label: "실행 목록" },
];

export function readSingleTab(): SingleTab | null {
  try {
    const v = globalThis.localStorage?.getItem(SINGLE_TAB_KEY);
    return v === "list" || v === "new" ? v : null;
  } catch {
    return null;
  }
}

export function writeSingleTab(t: SingleTab) {
  try {
    globalThis.localStorage?.setItem(SINGLE_TAB_KEY, t);
  } catch {
    /* 저장 실패는 무시 */
  }
}

export function SingleTabs({ tab, onChange }: { tab: SingleTab; onChange: (t: SingleTab) => void }) {
  return (
    <Card span={9} title="단일 예측" className="single-tabs">
      <div className="tabs" role="tablist" aria-label="단일 예측">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={tab === t.key ? "on" : ""} onClick={() => onChange(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
    </Card>
  );
}
