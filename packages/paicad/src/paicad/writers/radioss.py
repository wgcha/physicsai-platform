"""Radioss include writer: section 6.4 fixed-width rewrite of /NODE coordinate fields only."""

from __future__ import annotations

import numpy as np

from ..common import PaicadError
from ..mesh.radioss import parse_text, rewrite_nodes
from . import radioss_cushion


class RadiossWriter:
    name = "radioss"
    output_name = "morphed.inc"

    def write(self, base_bytes: bytes, base_mesh, moved: dict) -> bytes:
        data = rewrite_nodes(base_bytes, moved)
        m2 = parse_text(data.decode("latin-1"))
        same = np.array_equal(m2.node_ids, base_mesh.node_ids) and len(m2.blocks) == len(base_mesh.blocks)
        if same:
            for a, b in zip(base_mesh.blocks, m2.blocks):
                if a.keyword != b.keyword or a.part_id != b.part_id or not np.array_equal(a.ids, b.ids) or not np.array_equal(a.conn, b.conn):
                    same = False
                    break
        if not same:
            raise PaicadError("GEOM_INTERNAL", "morphed include changed node ids, element ids, connectivity or counts")
        return data

    def write_cushion(self, inc, renum, assem_dir, out_name: str):
        """Cushion-only starter rad (input-kind.md section 5.2): returns ``radioss_cushion.CushionRad``."""
        return radioss_cushion.build(inc, renum, assem_dir, out_name)

    def write_cushion_asm(self, src, patch, out_name: str):
        """Assembly-match cushion rad (asm-match.md section 5.5): returns ``radioss_cushion.CushionRad``."""
        return radioss_cushion.build_asm(src, patch, out_name)
