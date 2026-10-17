// 목록에 없어도 직접 입력하는 칸(입력란 + <datalist> 후보, D3-53). 결과 종류·성분·datatype·component 공용.
/** PhysicsAI 예측 h3d 응력 결과 이름(HyperView `hwc result scalar load type=CornerStress`) — config capture.default_field 기본과 같다 */
export const DEFAULT_RESULT_FIELD = "CornerStress";
/** D3-54: CornerStress의 성분(사용자 확인) — config capture.default_component 기본과 같다 */
export const DEFAULT_RESULT_COMPONENT = "vonMises";

/** 결과 종류가 기본(CornerStress)이면 성분 후보에 vonMises를 넣는다(없을 때만, 맨 앞) */
export function componentOptions(field: string, options: string[], defField = DEFAULT_RESULT_FIELD, defComp = DEFAULT_RESULT_COMPONENT): string[] {
  return field.trim() === defField && defComp && !options.includes(defComp) ? [defComp, ...options] : options;
}

export function ComboInput({ id, label, value, options, onChange, placeholder, className }: {
  id: string;
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const listId = `${id}-list`;
  return (
    <>
      <input aria-label={label} className={className} value={value} list={listId} placeholder={placeholder ?? label} onChange={(e) => onChange(e.target.value)} />
      <datalist id={listId} data-testid={listId}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </>
  );
}
