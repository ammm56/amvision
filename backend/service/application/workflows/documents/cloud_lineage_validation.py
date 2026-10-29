"""无整块载入的生成来源资产校验，固定布局与运行校验共用。"""

import numpy as np

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.lineage import lineage_shapes
from backend.service.application.workflows.point_cloud.profile_lineage import (
    profile_lineage_shapes,
)
from backend.contracts.workflows.point_cloud_assets import AssetProfileLineage


class LineageBytesValidator:
    """分块校验数值与 CSR 首尾，保留不足一条记录的尾部。"""

    def __init__(self, asset):
        """只保存字段布局及一个记录尾，不为点数分配数组。"""
        self.asset = asset
        self.fields = []
        offset = 0
        self.profile = isinstance(asset.lineage, AssetProfileLineage)
        shapes = (
            profile_lineage_shapes(
                asset.point_count, asset.lineage.cell_count, asset.lineage.source_count
            )
            if self.profile
            else lineage_shapes(asset.point_count, asset.lineage.face_count)
        )
        for name, (shape, dtype) in shapes.items():
            size = int(np.prod(shape)) * np.dtype(dtype).itemsize
            self.fields.append((name, offset, offset + size, shape[1], dtype))
            offset += size
        self.tail = b""
        self.previous = None
        self.previous_cell = None

    def check(self, data, offset):
        """源行号不经浮点；权重、面退化和偏移反向均拒绝。"""
        for name, start, stop, width, dtype in self.fields:
            low, high = max(start, offset), min(stop, offset + len(data))
            if low >= high:
                continue
            joined = self.tail + data[low - offset : high - offset]
            row_bytes = width * np.dtype(dtype).itemsize
            end = len(joined) // row_bytes * row_bytes
            values = np.frombuffer(joined[:end], dtype=dtype).reshape(-1, width)
            self.tail = joined[end:]
            if name in ("source_edges", "source_faces", "cell_sources") and np.any(
                values >= self.asset.lineage.source_point_count
            ):
                raise InvalidRequestError("生成来源行号越界")
            if name == "source_faces" and (
                np.any(values[:, 0] == values[:, 1])
                or np.any(values[:, 1] == values[:, 2])
                or np.any(values[:, 0] == values[:, 2])
            ):
                raise InvalidRequestError("生成来源面退化")
            if name in ("weights", "profile_weights") and (
                not np.isfinite(values).all()
                or np.any(values < 0)
                or np.any(values > 1)
                or not np.allclose(
                    values.sum(axis=1), 1, rtol=0, atol=8 * np.finfo(float).eps
                )
            ):
                raise InvalidRequestError("生成来源权重无效")
            if name in ("face_offsets", "cell_offsets") and len(values):
                total = (
                    self.asset.lineage.source_count
                    if self.profile
                    else self.asset.lineage.face_count
                )
                flat = values[:, 0]
                if (
                    (self.previous is None and flat[0] != 0)
                    or (self.previous is not None and flat[0] <= self.previous)
                    or np.any(flat[1:] <= flat[:-1])
                    or flat[-1] > total
                ):
                    raise InvalidRequestError("生成来源邻面区间无效")
                self.previous = int(flat[-1])
                if high == stop and self.previous != total:
                    raise InvalidRequestError("生成来源邻面尾部无效")
            if name == "cell_indices" and len(values):
                pairs = [tuple(map(int, row)) for row in values]
                if (
                    self.previous_cell is not None and pairs[0] <= self.previous_cell
                ) or any(a >= b for a, b in zip(pairs, pairs[1:])):
                    raise InvalidRequestError("格注册表重复或倒序")
                self.previous_cell = pairs[-1]
            if name == "cell_heights" and not np.isfinite(values).all():
                raise InvalidRequestError("格聚合高度必须有限")
            if name == "profile_cells" and np.any(
                values >= self.asset.lineage.cell_count
            ):
                raise InvalidRequestError("格剖面单元引用越界")
            if name in ("profile_sides", "profile_kinds") and np.any(values > 3):
                raise InvalidRequestError("格剖面侧向或来源种类无效")
            if high == stop and self.tail:
                raise InvalidRequestError("生成来源字段截断")
