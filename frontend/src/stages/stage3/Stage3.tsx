import { DatasetCreateCard, HpcTrainingNotice, PackageExportCard } from "./DatasetCards";
import { EvaluateCard } from "./EvaluateCard";
import { ModelRegisterCard } from "./ModelRegisterCard";
import { ModelPanel } from "../../panels/ModelPanel";

/** ③ 데이터셋·모델: ③-1 → ③-2 → ③-3 → ③-4 → ③-5 + 모델 목록·Final(레이아웃 A, ③-5 오른쪽 4열) (§16.4) */
export function Stage3() {
  return (
    <>
      <DatasetCreateCard />
      <PackageExportCard />
      <HpcTrainingNotice />
      <ModelRegisterCard />
      <EvaluateCard />
      <ModelPanel />
    </>
  );
}
