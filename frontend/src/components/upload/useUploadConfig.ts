// GET /uploads/config 를 한 번만 읽어 모든 경로 칸이 공유한다. 실패(미구현·권한)·enabled=false 면 null = PC 탭 숨김(지금과 같은 화면).
import { useEffect, useState } from "react";
import { uploadApi, type UploadConfig } from "../../api/uploads";

let cached: Promise<UploadConfig | null> | null = null;

export function resetUploadConfig() {
  cached = null;
}

function load(): Promise<UploadConfig | null> {
  if (!cached) {
    const p: Promise<UploadConfig | null> = uploadApi
      .config()
      .then((c) => (c.enabled ? c : null))
      .catch(() => {
        if (cached === p) cached = null; // 실패는 캐시하지 않는다(다음 화면에서 다시 시도)
        return null;
      });
    cached = p;
  }
  return cached;
}

/** undefined = 확인 중, null = 업로드 꺼짐·사용 불가, 값 = 사용 가능 */
export function useUploadConfig(): UploadConfig | null | undefined {
  const [cfg, setCfg] = useState<UploadConfig | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    void load().then((c) => alive && setCfg(c));
    return () => {
      alive = false;
    };
  }, []);
  return cfg;
}
