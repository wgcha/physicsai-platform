// 경로 칸 공통 탭 "내 PC에서 올리기 | 서버 경로"(upload-report.md §3.2). 서버 경로 탭 = 기존 화면(children) 그대로.
// 업로드가 꺼져 있거나(GET /uploads/config enabled=false·실패)·실행 권한이 없거나·업로드 대상 purpose 가 아니면 탭 없이 children 만 그린다.
import { useState, type ReactNode } from "react";
import type { PathInspectResult } from "../../api";
import type { UploadPurpose } from "../../api/uploads";
import { UploadTab } from "./UploadTab";
import { useUploadConfig } from "./useUploadConfig";

export const PATH_SOURCE_KEY = "pai.pathSource";
type Src = "pc" | "server";

function read(): Src {
  try {
    return localStorage.getItem(PATH_SOURCE_KEY) === "server" ? "server" : "pc";
  } catch {
    return "pc";
  }
}

export function PathSourceTabs({
  studyId,
  purpose,
  engine,
  canExecute,
  onUploaded,
  children,
}: {
  studyId: string;
  /** 업로드 purpose(paths/inspect purpose 와 같은 이름 + DISCOVER). SPDM_IMPORT 등 목록에 없는 값은 탭 없음 */
  purpose: string;
  engine?: "native" | "altair" | null;
  canExecute: boolean;
  /** 업로드 완료(COMPLETED): complete 응답의 path·inspect — 부모가 경로 칸에 채운다. 이어서 서버 경로 탭으로 넘어간다 */
  onUploaded: (path: string, inspect: PathInspectResult | null) => void;
  children: ReactNode;
}) {
  const cfg = useUploadConfig();
  const [tab, setTab] = useState<Src>(read);
  if (!cfg || !canExecute || !cfg.purposes[purpose]) return <>{children}</>;
  const choose = (t: Src) => {
    setTab(t);
    try {
      localStorage.setItem(PATH_SOURCE_KEY, t);
    } catch {
      /* 저장소 없음 */
    }
  };
  return (
    <div className="path-source" data-testid="path-source">
      <div className="tabs" role="tablist" aria-label="입력 위치">
        <button type="button" role="tab" aria-selected={tab === "pc"} onClick={() => choose("pc")}>
          내 PC에서 올리기
        </button>
        <button type="button" role="tab" aria-selected={tab === "server"} onClick={() => choose("server")}>
          서버 경로
        </button>
      </div>
      <div className="path-source-pane" hidden={tab !== "pc"}>
        <UploadTab
          studyId={studyId}
          purpose={purpose as UploadPurpose}
          engine={engine}
          cfg={cfg}
          canExecute={canExecute}
          onDone={(path, inspect) => {
            onUploaded(path, inspect);
            setTab("server");
          }}
        />
      </div>
      <div className="path-source-pane" hidden={tab !== "server"}>
        {children}
      </div>
    </div>
  );
}
