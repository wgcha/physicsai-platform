import { DatasetCreateCard, HpcTrainingNotice, PackageExportCard } from "./DatasetCards";
import { EvaluateCard } from "./EvaluateCard";
import { ModelRegisterCard } from "./ModelRegisterCard";

/** ③ 데이터셋·모델: ③-1 → ③-2 → ③-3 → ③-4 → ③-5 (§16.4) */
export function Stage3() {
  return (
    <>
      <DatasetCreateCard />
      <PackageExportCard />
      <HpcTrainingNotice />
      <ModelRegisterCard />
      <EvaluateCard />
    </>
  );
}
