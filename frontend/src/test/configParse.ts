// 시험용 설정 문법 검사기(V-MCP-23): TOML 간이 파서·셸 분해. 앱 코드에서는 쓰지 않는다.
/** TOML 간이 파서 — [a.b.c] 표, key = "문자열" | [] 만(이 설정이 쓰는 문법) */
export function parseToml(text: string): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  let cur = root;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const tbl = /^\[([A-Za-z0-9_.]+)\]$/.exec(line);
    if (tbl) {
      cur = root;
      for (const k of tbl[1].split(".")) cur = (cur[k] ??= {}) as Record<string, unknown>;
      continue;
    }
    const kv = /^([A-Za-z0-9_]+) = (.+)$/.exec(line);
    if (!kv) throw new Error(`TOML 문법 오류: ${line}`);
    const v = kv[2];
    if (v === "[]") cur[kv[1]] = [];
    else if (/^"(?:[^"\\]|\\.)*"$/.test(v)) cur[kv[1]] = JSON.parse(v); // TOML 기본 문자열 이스케이프는 JSON과 같은 부분집합
    else throw new Error(`TOML 값 오류: ${line}`);
  }
  return root;
}
/** 큰따옴표·역슬래시 이스케이프를 아는 셸 분해 */
export function shellSplit(cmd: string): string[] {
  const out: string[] = [];
  let cur = "";
  let q = false;
  let has = false;
  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i];
    if (c === "\\" && q && i + 1 < cmd.length) {
      cur += cmd[++i];
      has = true;
    } else if (c === '"') {
      q = !q;
      has = true;
    } else if (/\s/.test(c) && !q) {
      if (has) out.push(cur);
      cur = "";
      has = false;
    } else {
      cur += c;
      has = true;
    }
  }
  if (q) throw new Error("따옴표가 닫히지 않음");
  if (has) out.push(cur);
  return out;
}
