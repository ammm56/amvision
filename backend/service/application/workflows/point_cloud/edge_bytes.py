"""B09 固定块逐字段校验；与现有 CheckedBlobStream 共用事务读取。"""

import numpy as np

from backend.service.application.errors import InvalidRequestError


class EdgeBytesValidator:
    """仅保存不足一个标量的尾部，不按载荷大小构造副本。"""

    def __init__(self, asset):
        self.evidence = asset.edge
        self.asset = asset
        self.layout = self.evidence.layout()
        self.index = self.used = self.offset = 0
        self.tail = b""
        self.supported = self.paired = 0

    def check(self, data, offset):
        """校验每个连续字段的值域、数值类型及精确结束位置。"""
        if offset != self.offset:
            raise InvalidRequestError("实测边数据流偏移不连续")
        self.offset += len(data)
        cursor = 0
        while self.index < len(self.layout):
            group, name, dtype, rows, width = self.layout[self.index]
            size = np.dtype(dtype).itemsize
            length = rows * width * size
            if self.used == length:
                if self.tail:
                    raise InvalidRequestError("实测边字段截断")
                self.index += 1
                self.used = 0
                continue
            if cursor == len(data):
                break
            take = min(length - self.used, len(data) - cursor)
            joined = self.tail + data[cursor : cursor + take]
            end = len(joined) // size * size
            values = np.frombuffer(joined[:end], dtype=dtype)
            self._values(group, name, values)
            self.tail = joined[end:]
            self.used += take
            cursor += take
        if cursor != len(data) or (not data and self.index != len(self.layout)):
            raise InvalidRequestError("实测边数据块截断或含多余字节")
        if not data and (
            self.supported != self.evidence.supported_count
            or self.paired != self.evidence.pair_count * 2
        ):
            raise InvalidRequestError("实测边数据计数与正文不一致")

    def _values(self, group, name, values):
        """外部包不可用越界索引、未知原因位或无穷数绕过内容校验。"""
        e = self.evidence
        normal = e.method.kind == "normal-crease"
        if group == "candidates" and name == "reason":
            self.supported += int(np.count_nonzero(values == 0))
        if group == "pairs" and name == "status":
            self.paired += int(np.count_nonzero(values == 0))
        limit = None
        low = 0
        if name == "input_rows":
            limit = e.input_count
        elif name == "source_rows":
            limit = self.asset.original_observation()[1]
        elif name == "partners":
            low, limit = -1, e.record_count
        elif name == "first_pair_candidate":
            low, limit = -1, e.candidate_count
        elif name in ("pair_rows", "other_rows"):
            limit = e.record_count
        elif name in ("chain_rows", "segment_rows", "isolated"):
            limit = e.vertex_count
        elif name == "edges":
            limit = e.input_count if group == "pairs" else e.vertex_count
        elif name == "pairs":
            limit = e.input_count
        elif name == "cells":
            h = self.asset.height_map
            limit = h.parameters.width * h.parameters.height
        elif name == "reason":
            limit = 8
        elif name == "status":
            limit = 5 if group == "candidates" else 14
        elif name == "sides":
            limit = 4
        elif name == "closed":
            limit = 2
        elif name == "reason_bits":
            limit = 1 << 14
        if limit is not None and (np.any(values < low) or np.any(values >= limit)):
            raise InvalidRequestError(f"实测边 {group}.{name} 超出合法范围")
        if values.dtype.kind == "f":
            if np.isinf(values).any() or (
                name in ("positions", "angle", "delta")
                and not np.isfinite(values).all()
            ):
                raise InvalidRequestError("实测边数值包含非法非有限值")
            if name in ("angle", "delta", "rms", "maximum") and np.any(values < 0):
                raise InvalidRequestError("实测边距离或残差为负")
        if normal and name == "neighbors" and np.any(values > e.input_count):
            raise InvalidRequestError("法向邻居数量超过完整输入")
