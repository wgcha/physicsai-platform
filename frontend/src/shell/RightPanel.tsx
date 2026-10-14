import { QueuePanel } from "../panels/QueuePanel";
import { WorkerResourcePanel } from "../panels/WorkerResourcePanel";
import { ModelPanel } from "../panels/ModelPanel";
import { Rail, RailSlot } from "../design/Grid";

/** 공통 칸 3종: 별도 사이드바가 아니라 작업 격자의 10~12열 띠(1280 미만은 본문 뒤 칸) */
export function RightPanel() {
  return (
    <aside className="rightpanel grid-contents" aria-label="공통 패널">
      <Rail>
        <RailSlot index={0}>
          <QueuePanel />
        </RailSlot>
        <RailSlot index={1}>
          <WorkerResourcePanel />
        </RailSlot>
        <RailSlot index={2}>
          <ModelPanel />
        </RailSlot>
      </Rail>
    </aside>
  );
}
