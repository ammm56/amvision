"""高度图固定布局的流式值域核验；不复制外部格式解析或分配完整格数组。"""

from hashlib import sha256

import numpy as np

from backend.service.application.errors import InvalidRequestError


class HeightMapBytesValidator:
    """逐字段校验长度、空格掩码与 CSR 一致性，工作空间只随读取块增长。"""

    def __init__(self, asset):
        self.evidence = asset.height_map
        self.source_count = asset.original_observation()[1]
        self.layout = iter(self.evidence.layout())
        self.current = None
        self.tail = b""
        self.total = 0
        self.previous = None
        self.count_sum = 0
        self.occupied = 0
        self.masks = {k: sha256() for k in ("heights", "minimum", "maximum", "counts")}
        self.count_digest, self.offset_digest = sha256(), sha256()
        self._advance()

    def _advance(self):
        self.current = next(self.layout, None)
        self.remaining = 0 if self.current is None else self.current[2]

    def check(self, data, offset):
        """消费原始 LE 字节，允许任意分块边界和合法空数组。"""
        if offset != self.total:
            raise InvalidRequestError("高度图数据块顺序错误")
        self.total += len(data)
        joined = self.tail + data
        cursor = 0
        while self.current is not None:
            name, dtype, _ = self.current
            dtype = np.dtype(dtype).newbyteorder("<")
            count = min(self.remaining, (len(joined) - cursor) // dtype.itemsize)
            if self.remaining and not count:
                break
            if count:
                values = np.frombuffer(joined, dtype=dtype, count=count, offset=cursor)
                self._values(name, values)
                self.remaining -= count
                cursor += count * dtype.itemsize
            if not self.remaining:
                self._advance()
        self.tail = joined[cursor:]
        if not data:
            if (
                self.current is not None
                or self.tail
                or self.total != self.evidence.byte_length()
            ):
                raise InvalidRequestError("高度图数组截断或含尾字节")
            if len({v.digest() for v in self.masks.values()}) != 1:
                raise InvalidRequestError("高度图空格与统计掩码不一致")
            if self.count_digest.digest() != self.offset_digest.digest():
                raise InvalidRequestError("高度图贡献偏移与逐格计数不一致")
            members = self.evidence.input_count - self.evidence.outside_count
            if (self.count_sum, self.occupied, self.previous) != (
                members,
                self.evidence.occupied_count,
                members,
            ):
                raise InvalidRequestError("高度图贡献总数或非空格数不一致")

    def _values(self, name, values):
        """严格值域与计数核对；数值范围交叉核验在运行期有界读回完成。"""
        if name in ("heights", "minimum", "maximum"):
            if np.isinf(values).any():
                raise InvalidRequestError("高度图包含无限高度")
            self.masks[name].update(np.isfinite(values).astype("u1").tobytes())
        elif name == "counts":
            if np.any(values > self.evidence.input_count):
                raise InvalidRequestError("高度图格贡献数越界")
            self.count_sum += sum(map(int, values))
            self.occupied += int(np.count_nonzero(values))
            self.masks[name].update((values > 0).astype("u1").tobytes())
            self.count_digest.update(values.tobytes())
        elif name == "member_offsets":
            if self.previous is None:
                if values[0] != 0:
                    raise InvalidRequestError("高度图 CSR 必须从零开始")
                self.previous = 0
                values = values[1:]
            if len(values):
                if values[0] < self.previous or np.any(values[1:] < values[:-1]):
                    raise InvalidRequestError("高度图 CSR 不能倒序")
                delta = np.empty_like(values)
                delta[0] = values[0] - self.previous
                delta[1:] = values[1:] - values[:-1]
                self.offset_digest.update(delta.tobytes())
                self.previous = int(values[-1])
        else:
            limit = (
                self.evidence.input_count if name == "input_rows" else self.source_count
            )
            if np.any(values >= limit):
                raise InvalidRequestError("高度图贡献行号越界")
