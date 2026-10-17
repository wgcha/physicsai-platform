// phase3.md §5.8 용량·정리 화면 순수 함수(표시 묶음·선택 합계·비활성 사유·확인 문구).
import type { CategoryKey, StorageCategory, StorageReport, StorageScan } from "../../api";
import { fmtBytes } from "../../lib/format";

/** 단계 묶음(§5.3 끝): ①=01_*, ②=02_*, ③=03_*, ④=04_*, ⑤=05_*, 공통=logs·00_inbox·(기타), 백업=_backup */
export const STORAGE_GROUPS = [
  { key: "s1", label: "① 학습데이터", match: (k: string) => k.startsWith("01_") },
  { key: "s2", label: "② 데이터 정리", match: (k: string) => k.startsWith("02_") },
  { key: "s3", label: "③ 데이터셋·모델", match: (k: string) => k.startsWith("03_") },
  { key: "s4", label: "④ 예측", match: (k: string) => k.startsWith("04_") },
  { key: "s5", label: "⑥ 최적화", match: (k: string) => k.startsWith("05_") },
  { key: "common", label: "공통", match: (k: string) => k === "logs" || k === "00_inbox" || k === "(기타)" },
  { key: "backup", label: "백업", match: (k: string) => k === "_backup" },
] as const;

export interface StorageGroup {
  key: string;
  label: string;
  bytes: number;
  files: number;
  folders: StorageScan["folders"];
}

export function groupFolders(folders: StorageScan["folders"]): StorageGroup[] {
  return STORAGE_GROUPS.map((g) => {
    const fs = folders.filter((f) => g.match(f.key));
    return { key: g.key, label: g.label, folders: fs, bytes: fs.reduce((a, f) => a + f.bytes, 0), files: fs.reduce((a, f) => a + f.files, 0) };
  });
}

export function selectionTotals(cats: StorageCategory[], selected: Set<CategoryKey>): { count: number; bytes: number } {
  const chosen = cats.filter((c) => selected.has(c.key));
  return { count: chosen.reduce((a, c) => a + c.item_count, 0), bytes: chosen.reduce((a, c) => a + c.total_bytes, 0) };
}

/** "백업 폴더로 옮기기" 비활성 사유(없으면 null). 권한은 호출부가 따로 본다. */
export function cleanupBlockReason(rep: StorageReport, count: number): string | null {
  if (rep.active_cleanup_job_id) return "정리가 진행 중입니다";
  if (rep.active_scan_job_id) return "용량 계산이 진행 중입니다";
  if (!rep.scan) return "먼저 용량을 계산하세요";
  if (rep.scan.partial) return "부분 스캔 결과로는 정리할 수 없습니다. 다시 계산하세요";
  if (rep.stale) return `${rep.stale_reason ?? "계산 결과가 최신이 아닙니다"} — 다시 계산한 뒤 정리하세요`;
  if (count < 1) return "옮길 항목을 고르세요";
  return null;
}

export function cleanupDialogBody(cats: StorageCategory[], selected: Set<CategoryKey>): string {
  const { count, bytes } = selectionTotals(cats, selected);
  const impacts = cats.filter((c) => selected.has(c.key)).map((c) => `· ${c.label}: ${c.impact}`);
  return [
    `선택한 ${count}개 항목(${fmtBytes(bytes)})을 _backup 폴더로 옮깁니다. 파일은 삭제되지 않습니다.`,
    "옮기는 동안 이 Study에서 다른 작업을 실행할 수 없습니다.",
    ...impacts,
  ].join("\n");
}

export const BACKUP_NOTICE =
  "_backup 폴더는 앱에서 비우지 않습니다. 필요 없으면 탐색기에서 직접 삭제하세요. 되돌리려면 _backup/<시각>_<작업ID>/ 아래 파일을 원래 위치로 옮기면 됩니다.";
