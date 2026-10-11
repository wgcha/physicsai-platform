"""Study 폴더 걷기·집계(phase3 §5.3 SS_WALK). 순수 파일 시스템 로직 — DB·작업 레일을 모른다.

- 링크·junction·reparse point는 따라가지 않고 개수만 센다(`skipped_links`). 링크가 든 범주 항목은 표시(`links`).
- 권한 오류·사라진 파일은 건너뛰고 `errors` 증가.
- 항목 수가 `max_entries`에 닿으면 멈추고 `partial=True`.
- 삭제·쓰기 호출 없음.
"""

from __future__ import annotations

import heapq
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..paths import is_link_or_reparse
from .categories import BACKUP_KEY, FOLDER_KEYS, OTHER_KEY, match_item

PROGRESS_EVERY = 10000


@dataclass
class ItemAgg:
    bytes: int = 0
    files: int = 0
    links: int = 0


@dataclass
class ScanTree:
    total_bytes: int = 0
    total_files: int = 0
    skipped_links: int = 0
    errors: int = 0
    entries: int = 0
    partial: bool = False
    folders: dict[str, list[int]] = field(default_factory=dict)  # key → [bytes, files]
    top: list[tuple[int, str, float]] = field(default_factory=list)  # 최소 힙 (bytes, rel, mtime)
    items: dict[str, ItemAgg] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """jobs.result에 넣을 StorageScan 일부(경로·크기·개수만)."""
        b = self.folders.get(BACKUP_KEY, [0, 0])
        order = {k: i for i, k in enumerate((*FOLDER_KEYS, OTHER_KEY))}
        return {
            "partial": self.partial, "total_bytes": self.total_bytes, "total_files": self.total_files,
            "skipped_links": self.skipped_links, "errors": self.errors, "backup_bytes": b[0], "backup_files": b[1],
            "folders": [{"key": k, "bytes": v[0], "files": v[1]}
                        for k, v in sorted(self.folders.items(), key=lambda kv: order.get(kv[0], 99))],
            "top_files": [
                {"rel": rel, "bytes": n, "in_backup": rel.split("/", 1)[0] == BACKUP_KEY,
                 "modified_at": datetime.fromtimestamp(mt, timezone.utc).isoformat()}
                for n, rel, mt in sorted(self.top, key=lambda t: (-t[0], t[1]))
            ],
        }

    def items_json(self) -> dict[str, list[int]]:
        return {k: [v.bytes, v.files, v.links] for k, v in self.items.items()}


class _Stop(Exception):
    pass


def walk(root: str, *, max_entries: int, top_n: int, on_progress: Callable[[int], None] | None = None,
         checkpoint: Callable[[], None] | None = None) -> ScanTree:
    """`root`(Study 폴더) 전체를 걸어 ScanTree를 만든다. on_progress(n)은 항목 PROGRESS_EVERY개마다."""
    t = ScanTree()
    stack: list[tuple[str, tuple[str, ...]]] = [(root, ())]

    def count() -> None:
        t.entries += 1
        if t.entries % PROGRESS_EVERY == 0:
            if checkpoint:
                checkpoint()
            if on_progress:
                on_progress(t.entries)
        if t.entries >= max_entries:
            t.partial = True
            raise _Stop()

    try:
        while stack:
            d, parts = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                t.errors += 1
                continue
            with it:
                for e in it:
                    p = (*parts, e.name)
                    try:
                        if is_link_or_reparse(e.path):
                            t.skipped_links += 1
                            for rel in match_item(p):
                                t.items.setdefault(rel, ItemAgg()).links += 1
                            # 링크가 범주 항목의 상위(예: logs 자체)면 그 아래 항목은 보이지 않는다(걷지 않음)
                        elif e.is_dir(follow_symlinks=False):
                            stack.append((e.path, p))
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            _add_file(t, p, st.st_size, st.st_mtime, top_n)
                    except OSError:
                        t.errors += 1
                    count()
    except _Stop:
        pass
    return t


def _add_file(t: ScanTree, p: tuple[str, ...], size: int, mtime: float, top_n: int) -> None:
    t.total_bytes += size
    t.total_files += 1
    key = p[0] if len(p) > 1 and p[0] in FOLDER_KEYS else OTHER_KEY
    f = t.folders.setdefault(key, [0, 0])
    f[0] += size
    f[1] += 1
    rel = "/".join(p)
    if top_n > 0:
        if len(t.top) < top_n:
            heapq.heappush(t.top, (size, rel, mtime))
        elif size > t.top[0][0]:
            heapq.heapreplace(t.top, (size, rel, mtime))
    for item in match_item(p):
        a = t.items.setdefault(item, ItemAgg())
        a.bytes += size
        a.files += 1
