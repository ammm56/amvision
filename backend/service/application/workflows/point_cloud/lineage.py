"""生成顶点的有界来源访问；数组仍由既有 OwnedCloudArrays/Scope 持有。"""

from types import MappingProxyType

import numpy as np

from backend.service.application.errors import InvalidRequestError


def lineage_shapes(point_count, face_count):
    """固定 LE 布局同时用于运行校验与资产读写，不另建序列化协议。"""
    return {
        "source_edges": ((point_count, 2), "<u8"),
        "weights": ((point_count, 2), "<f8"),
        "face_offsets": ((point_count + 1, 1), "<u8"),
        "source_faces": ((face_count, 3), "<u8"),
    }


def validate_lineage(arrays, *, point_count, source_point_count, policy, cancel):
    """验证原始行号、插值和 CSR；不把邻面多次出现误判为重复数据。"""
    if set(arrays) != set(lineage_shapes(0, 0)):
        raise InvalidRequestError("生成顶点来源字段不完整")
    faces = arrays["source_faces"]
    for name, (shape, dtype) in lineage_shapes(point_count, len(faces)).items():
        value = arrays[name]
        if (
            value.shape != shape
            or value.dtype != np.dtype(dtype)
            or value.flags.writeable
        ):
            raise InvalidRequestError("生成顶点来源形状、精度或只读状态无效")
    offsets = arrays["face_offsets"][:, 0]
    if offsets[0] != 0 or offsets[-1] != len(faces):
        raise InvalidRequestError("生成顶点邻面区间无效")
    rows = min(policy.chunk_rows, policy.max_working_bytes // 128)
    if rows < 1:
        raise InvalidRequestError("来源校验工作预算不能容纳一行")
    for start in range(0, point_count, rows):
        cancel()
        stop = min(start + rows, point_count)
        edges, weights = (
            arrays["source_edges"][start:stop],
            arrays["weights"][start:stop],
        )
        if np.any(edges >= source_point_count):
            raise InvalidRequestError("生成顶点源边行号越界")
        if (
            not np.isfinite(weights).all()
            or np.any(weights < 0)
            or np.any(weights > 1)
            or not np.allclose(
                weights.sum(axis=1), 1, rtol=0, atol=8 * np.finfo(float).eps
            )
        ):
            raise InvalidRequestError("生成顶点插值权重无效")
        if np.any(offsets[start + 1 : stop + 1] <= offsets[start:stop]):
            raise InvalidRequestError("每个生成顶点必须保留实际支持面")
    for start in range(0, len(faces), rows):
        cancel()
        block = faces[start : start + rows]
        if (
            np.any(block >= source_point_count)
            or np.any(block[:, 0] == block[:, 1])
            or np.any(block[:, 1] == block[:, 2])
            or np.any(block[:, 0] == block[:, 2])
        ):
            raise InvalidRequestError("生成顶点源面无效")
        owners = np.searchsorted(
            offsets[1:],
            np.arange(start, start + len(block), dtype=np.uint64),
            side="right",
        )
        edges = arrays["source_edges"][owners]
        if not (
            (block == edges[:, 0, None]).any(axis=1)
            & (block == edges[:, 1, None]).any(axis=1)
        ).all():
            raise InvalidRequestError("生成顶点源边不属于记录的支持面")


def lineage_chunk(arrays, selected, *, max_working_bytes):
    """按当前逻辑行重建有界 CSR，裁剪和变换不改变最初来源行号。"""
    selected = np.asarray(selected, dtype=np.uint64)
    offsets = arrays["face_offsets"][:, 0]
    counts = offsets[selected + 1] - offsets[selected]
    face_count = sum(int(value) for value in counts)
    cost = len(selected) * 96 + (len(selected) + 1) * 8 + face_count * 24
    if cost > max_working_bytes:
        raise InvalidRequestError("生成顶点来源访问超过工作预算")
    result = {
        "source_edges": arrays["source_edges"][selected],
        "weights": arrays["weights"][selected],
        "face_offsets": np.empty((len(selected) + 1, 1), dtype="<u8"),
        "source_faces": np.empty((face_count, 3), dtype="<u8"),
    }
    cursor = 0
    result["face_offsets"][0, 0] = 0
    for i, row in enumerate(selected):
        first, last = int(offsets[row]), int(offsets[row + 1])
        result["source_faces"][cursor : cursor + last - first] = arrays["source_faces"][
            first:last
        ]
        cursor += last - first
        result["face_offsets"][i + 1, 0] = cursor
    for value in result.values():
        value.setflags(write=False)
    return MappingProxyType(result)
