import { AsmMatchCard } from "../asm/AsmMatchCard";
import { useTrain } from "./TrainContext";

/** ①-2와 ①-3 사이 조립 매칭 카드(asm-match.md §3.2): Native 솔리드 학습 설정(①-1 Native 추출 결과)일 때만 */
export function AsmMatchSlot() {
  const { setup, setAsm } = useTrain();
  if (setup?.engine !== "native" || !setup.parameters.length) return null;
  return <AsmMatchCard cad={{ kind: "train" }} scope="train" usedParams={setup.parameters.filter((p) => p.use).map((p) => p.name)} onConfirmed={setAsm} />;
}
