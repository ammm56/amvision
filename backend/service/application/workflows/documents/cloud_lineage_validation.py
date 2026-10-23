"""无整块载入的生成来源资产校验，固定布局与运行校验共用。"""

import numpy as np

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.lineage import lineage_shapes


class LineageBytesValidator:
    """分块校验数值与 CSR 首尾，保留不足一条记录的尾部。"""

    def __init__(self, asset):
        """只保存字段布局及一个记录尾，不为点数分配数组。"""
        self.asset = asset
        self.fields = []
        offset = 0
        for name, (shape, dtype) in lineage_shapes(
            asset.point_count, asset.lineage.face_count
        ).items():
            size = int(np.prod(shape)) * 8
            self.fields.append((name, offset, offset + size, shape[1], dtype))
            offset += size
        self.tail = b""
        self.previous = None

    def check(self, data, offset):
        """源行号不经浮点；权重、面退化和偏移反向均拒绝。"""
        for name, start, stop, width, dtype in self.fields:
            low, high = max(start, offset), min(stop, offset + len(data))
            if low >= high:
                continue
            joined = self.tail + data[low - offset : high - offset]
            end = len(joined) // (width * 8) * (width * 8)
            values = np.frombuffer(joined[:end], dtype=dtype).reshape(-1, width)
            self.tail = joined[end:]
            if name in ("source_edges", "source_faces") and np.any(
                values >= self.asset.lineage.source_point_count
            ):
                raise InvalidRequestError("生成来源行号越界")
            if name == "source_faces" and (
                np.any(values[:, 0] == values[:, 1])
                or np.any(values[:, 1] == values[:, 2])
                or np.any(values[:, 0] == values[:, 2])
            ):
                raise InvalidRequestError("生成来源面退化")
            if name == "weights" and (
                not np.isfinite(values).all()
                or np.any(values < 0)
                or np.any(values > 1)
                or not np.allclose(
                    values.sum(axis=1), 1, rtol=0, atol=8 * np.finfo(float).eps
                )
            ):
                raise InvalidRequestError("生成来源权重无效")
            if name == "face_offsets" and len(values):
                flat = values[:, 0]
                if (
                    (self.previous is None and flat[0] != 0)
                    or (self.previous is not None and flat[0] <= self.previous)
                    or np.any(flat[1:] <= flat[:-1])
                    or flat[-1] > self.asset.lineage.face_count
                ):
                    raise InvalidRequestError("生成来源邻面区间无效")
                self.previous = int(flat[-1])
                if high == stop and self.previous != self.asset.lineage.face_count:
                    raise InvalidRequestError("生成来源邻面尾部无效")
            if high == stop and self.tail:
                raise InvalidRequestError("生成来源字段截断")
