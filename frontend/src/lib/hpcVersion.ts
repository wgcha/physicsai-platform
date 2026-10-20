// S20(D3-68): SCX Radioss 버전 작업별 입력 — 백엔드 HpcOverrides·FvHpc.version과 같은 규칙.
export const HPC_VERSION_RE = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$/;
export const HPC_VERSION_DEFAULT = "26.1";
export const HPC_VERSION_ERROR = "버전은 영문·숫자·공백·._- 64자 이내";

/** 화면 값 → 오류 문구(없으면 null). 앞뒤 공백은 자르고 본다(필수 입력이라 빈 값도 오류). */
export function hpcVersionError(v: string): string | null {
  return HPC_VERSION_RE.test(v.trim()) ? null : HPC_VERSION_ERROR;
}

/** 전송 값: 초기값 그대로면 null(설정 변경이 따라가도록), 바꿨으면 자른 값. */
export function hpcVersionPayload(v: string, initial: string): string | null {
  const t = v.trim();
  return !t || t === initial.trim() ? null : t;
}
