import { useState } from "react";
import { PathPickerDialog, type PickMode } from "./PathPickerDialog";

/** 경로 입력란 옆 "찾아보기" 버튼 + 대화상자(입력란은 그대로 둔다) */
export function BrowseButton({
  mode,
  exts,
  aiOnly,
  value,
  onPick,
  disabled,
  title,
}: {
  mode: PickMode;
  exts?: string[];
  aiOnly?: boolean;
  value?: string;
  onPick: (path: string) => void;
  disabled?: boolean;
  title?: string;
}) {
  const [opened, setOpened] = useState(false);
  return (
    <>
      <button type="button" className="btn ghost" onClick={() => setOpened(true)} disabled={disabled}>
        찾아보기
      </button>
      {opened && (
        <PathPickerDialog
          title={title}
          mode={mode}
          exts={exts}
          aiOnly={aiOnly}
          initialPath={value}
          onCancel={() => setOpened(false)}
          onPick={(p) => {
            setOpened(false);
            onPick(p);
          }}
        />
      )}
    </>
  );
}
