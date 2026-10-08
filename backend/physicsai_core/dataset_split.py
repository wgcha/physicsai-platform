"""③-1 h3d 수집·홀드아웃 분할(§8.4 DS_SCAN, DS_YAML)."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass


def collect_h3d(root: str) -> list[str]:
    """재귀 수집(대소문자 무시) → 정렬·중복 제거(원본 1_create_dataset.py:17-48). 링크 폴더는 따라가지 않는다."""
    found: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for f in filenames:
            if f.lower().endswith(".h3d"):
                found.add(os.path.normpath(os.path.join(dirpath, f)))
    return sorted(found)


@dataclass(frozen=True)
class Split:
    train: list[str]
    eval: list[str]
    n_groups: int


def n_eval_groups(n_groups: int, ratio: float) -> int:
    return max(1, round(n_groups * ratio))


def split_files(files: list[str], ratio: float, seed: int, group: str = "file") -> Split:
    """그룹 정렬 → random.Random(seed).shuffle → 앞에서 n_eval 그룹이 eval."""
    if group not in ("file", "parent_dir"):
        raise ValueError("split_group")
    groups: dict[str, list[str]] = {}
    for f in sorted(files):
        key = f if group == "file" else os.path.dirname(f)
        groups.setdefault(key, []).append(f)
    keys = sorted(groups)
    if len(keys) < 2:
        return Split([], [], len(keys))
    random.Random(seed).shuffle(keys)
    k = n_eval_groups(len(keys), ratio)
    k = min(k, len(keys) - 1)
    ev = sorted(f for key in keys[:k] for f in groups[key])
    tr = sorted(f for key in keys[k:] for f in groups[key])
    return Split(tr, ev, len(keys))


def dataset_yaml(files: list[str], hooks_dir: str, options: dict[str, bool]) -> str:
    """원본 generate_dataset_yaml(1_create_dataset.py:50-80) 형식 그대로."""
    lines = ["files:"]
    lines += [f"- {f}" for f in files]
    lines.append("interface: hw")
    lines.append("options:")
    lines.append(f"  extract_faces: {str(bool(options.get('extract_faces', True))).lower()}")
    lines.append("  extract_files: true")
    lines.append(f"  extract_mdi: {str(bool(options.get('extract_mdi', False))).lower()}")
    lines.append("  extract_results: true")
    lines.append(
        f"  extract_time_history_vectors: {str(bool(options.get('extract_time_history_vectors', False))).lower()}"
    )
    lines.append(f"  hooks_dir: {hooks_dir}")
    lines.append("  selection: {}")
    return "\n".join(lines) + "\n"
