// phase3.md §12 S7(D3-46) 서버 경로 탐색 목: GET /fs/roots, GET /fs/list. 메모리 안 가짜 폴더 나무.
// 규칙(백엔드와 같은 모양): 폴더 먼저·이름순, 최대 500개, exts는 파일만 거름, 루트 위로 못 감(parent=null),
// _backup·_platform(대소문자 무시)·점으로 시작하는 항목 숨김, 루트 밖·'..'·UNC 거부(422), 조회 전용 사용자 403.
import type { FsEntry, Me } from "../api/types";
import { err, ok, type MockResp, type Route } from "./route";

/** server.ts MOCK_AI_ROOT와 같은 값(server.ts가 이 모듈을 import하므로 순환을 피해 따로 둔다) */
const MOCK_AI_ROOT = "E:\\shared\\AI_WORK";
export const MOCK_IMPORT_ROOT = "F:\\hpc_results";
const MAX = 500;

/** 이름 → 하위(폴더) 또는 크기(파일) */
type Tree = { [name: string]: Tree | number };

const TREE: Record<string, Tree> = {
  [MOCK_AI_ROOT]: {
    cushion: {
      "00_inbox": {
        h3d: { run_001: { "ANIM_001.h3d": 81_234_112 }, run_002: { "ANIM_002.h3d": 80_991_232 } },
        model_v3: { "cushion_TNS.psmdl": 12_582_912, "train.log": 20_480 },
        params: { "parameters.csv": 1_024, "samples.csv": 40_960, radioss_assem: { "Face_Drop_0000.rad": 4_096 } },
        case_A: { "Face_Drop_0000.rad": 4_096, "Face_Drop_0001.rad": 182_400, "part.inc": 9_120_000, nested_old: {} },
        cad: { "cushion_parametric_modeling.prt": 2_310_144 },
      },
      "03_model": {},
      _backup: { old: {} },
    },
    inbox: {
      case_B: { "Side_Drop_0000.rad": 4_100, "Side_Drop_0001.rad": 180_000, "mesh.inc": 8_000_000 },
      "from_pc2.hm": 48_234_112,
      "readme.txt": 300,
    },
    _platform: {},
    _BACKUP: {},
    ".cache": {},
  },
  [MOCK_IMPORT_ROOT]: { model_v4: { "cushion_TNS.psmdl": 12_000_000, "train.log": 10_000 } },
};

export const MOCK_INBOX = `${MOCK_AI_ROOT}\\inbox`;
/** 화면 안내용 공유 경로(목) */
export const MOCK_SHARE_HINT = "\\\\AI-SERVER\\physicsai-inbox";

const sep = "\\";
const norm = (p: string) => p.replace(/\//g, sep).replace(/\\+$/, "");
const fold = (p: string) => norm(p).toLowerCase();
const HIDDEN = (n: string) => n.startsWith(".") || ["_backup", "_platform"].includes(n.toLowerCase());

const canBrowse = (me: Me) => me.is_global_admin || Object.values(me.roles).some((r) => r === "power" || r === "admin");

function resolve(path: string): { root: string; node: Tree; rel: string[] } | MockResp {
  if (/^(\\\\|\/\/)/.test(path)) return err(422, "PATH_UNSAFE", "네트워크(UNC) 경로는 쓸 수 없습니다. 서버의 드라이브 경로를 쓰세요");
  if (/\s/.test(path)) return err(422, "PATH_UNSAFE", "경로에 공백를 쓸 수 없습니다");
  const p = norm(path);
  const parts = p.split(sep);
  if (parts.includes("..") || parts.slice(1).includes(".")) return err(422, "PATH_UNSAFE", "경로에 '..' 또는 '.'을 쓸 수 없습니다");
  const root = Object.keys(TREE).find((r) => fold(p) === fold(r) || fold(p).startsWith(fold(r) + sep));
  if (!root) return err(422, "PATH_OUTSIDE_ROOT", "허용된 루트(AI 루트) 밖의 경로입니다");
  const rel = p.slice(root.length).split(sep).filter(Boolean);
  if (rel.some((x) => x.toLowerCase() === "_backup")) return err(422, "PATH_UNSAFE", "_backup 폴더 아래 경로는 쓸 수 없습니다");
  if (rel[0]?.toLowerCase() === "_platform") return err(422, "PATH_UNSAFE", "플랫폼 폴더(_platform)는 입력 경로로 쓸 수 없습니다");
  let node: Tree | number = TREE[root];
  for (const name of rel) {
    const next: Tree | number | undefined = typeof node === "number" ? undefined : node[name];
    if (next === undefined) return err(422, "PATH_NOT_FOUND", "폴더가 없습니다");
    node = next;
  }
  if (typeof node === "number") return err(422, "PATH_NOT_FOUND", "폴더가 없습니다");
  return { root, node, rel };
}

export const fsRoutes: Route = (_srv, c) => {
  if (c.seg[0] !== "fs" || c.method !== "GET") return null;
  if (!canBrowse(c.me)) return err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다", { required: "power" });
  if (c.seg[1] === "roots") {
    return ok({
      roots: [
        { key: "ai_root", label: "AI 루트", path: MOCK_AI_ROOT },
        { key: "inbox", label: "받은 파일(공유 폴더)", path: MOCK_INBOX },
        { key: "import_0", label: "추가 허용 폴더", path: MOCK_IMPORT_ROOT },
      ],
      inbox_share_hint: MOCK_SHARE_HINT,
    });
  }
  if (c.seg[1] !== "list") return null;
  const r = resolve(c.query.get("path") ?? "");
  if ("status" in r) return r;
  const exts = (c.query.get("exts") ?? "").split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
  const mtime = "2026-10-16T01:00:00Z";
  const rows: FsEntry[] = Object.entries(r.node)
    .filter(([n]) => !HIDDEN(n))
    .filter(([n, v]) => typeof v !== "number" || !exts.length || exts.some((e) => n.toLowerCase().endsWith(e)))
    .map(([n, v]) => (typeof v === "number" ? { name: n, type: "file" as const, size: v, mtime } : { name: n, type: "dir" as const, mtime }))
    .sort((a, b) => (a.type === b.type ? a.name.toLowerCase().localeCompare(b.name.toLowerCase()) : a.type === "dir" ? -1 : 1));
  const path = [r.root, ...r.rel].join(sep);
  const parent = r.rel.length ? [r.root, ...r.rel.slice(0, -1)].join(sep) : null;
  return ok({ path, parent, entries: rows.slice(0, MAX), truncated: rows.length > MAX });
};
