import { QueuePanel } from "../panels/QueuePanel";
import { WorkerResourcePanel } from "../panels/WorkerResourcePanel";
import { ModelPanel } from "../panels/ModelPanel";

export function RightPanel() {
  return (
    <aside className="rightpanel" aria-label="공통 패널">
      <QueuePanel />
      <WorkerResourcePanel />
      <ModelPanel />
    </aside>
  );
}
