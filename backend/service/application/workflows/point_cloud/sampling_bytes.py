"""既有资产流中的采样诊断固定记录验证，不解析外部点云格式。"""

import numpy as np

from backend.service.application.errors import InvalidRequestError

SAMPLING_DTYPE = np.dtype(
    [
        ("identity_rows", "<u8"),
        ("neighbors", "<u8"),
        ("status", "u1"),
        ("candidate", "u1"),
        ("context", "u1"),
    ]
)


def validate_records(records, evidence, source_count, *, start):
    """检查位域、候选/状态关系、邻域门禁及源行范围，不重算分类。"""
    p = evidence.parameters
    ids, counts = records["identity_rows"], records["neighbors"]
    state, candidate, context = (records[k] for k in ("status", "candidate", "context"))
    if (
        np.any(counts > evidence.input_count)
        or np.any(counts == 0)
        or np.any(state > 31)
        or np.any(candidate > 1)
        or np.any(context > 31)
        or np.any((candidate == 1) & (state != 0))
        or np.any((candidate != 0) != (context != 0))
        or np.any(((context & 1) != 0) & (context != 1))
        or np.any(((state & 2) != 0) != (counts < p.min_neighbors + 1))
        or np.any(((state & 4) != 0) != (counts > p.max_neighbors))
    ):
        raise InvalidRequestError("采样诊断状态、邻点数量或分类不一致")
    if evidence.vertex_kind == "source":
        if np.any(ids >= source_count):
            raise InvalidRequestError("采样诊断原始行号越界")
    elif not np.array_equal(
        ids, np.arange(start, start + len(records), dtype="uint64")
    ):
        raise InvalidRequestError("生成点诊断必须沿当前逻辑行号绑定来源")


class SamplingBytesValidator:
    """任意分块下保持记录边界与计数核对，不持有整云或完整位域。"""

    def __init__(self, asset):
        self.evidence = asset.sampling
        self.source_count = asset.original_observation()[1]
        self.tail = b""
        self.bytes = self.rows = self.candidates = 0

    def check(self, data, offset):
        """顺序读取，EOF 时拒绝截断、多余字节和候选总数不一致。"""
        if offset != self.bytes:
            raise InvalidRequestError("采样诊断流读取顺序错误")
        self.bytes += len(data)
        joined = self.tail + data
        end = len(joined) // SAMPLING_DTYPE.itemsize * SAMPLING_DTYPE.itemsize
        records = np.frombuffer(joined[:end], dtype=SAMPLING_DTYPE)
        validate_records(records, self.evidence, self.source_count, start=self.rows)
        self.rows += len(records)
        self.candidates += int(records["candidate"].sum())
        self.tail = joined[end:]
        if not data and (
            self.tail
            or self.bytes != self.evidence.byte_length()
            or self.rows != self.evidence.input_count
            or self.candidates != self.evidence.candidate_count
        ):
            raise InvalidRequestError("采样诊断长度或候选总数不一致")
