"""体素质心的完整原始成员 CSR；复用现有云来源所有权。"""

from types import MappingProxyType

import numpy as np

from backend.service.application.errors import InvalidRequestError


def voxel_lineage_shapes(point_count, member_count, source_dtype):
    """固定 LE 布局；行号宽度不经过浮点转换。"""
    return {
        "voxel_keys": ((point_count, 3), "<i8"),
        "member_offsets": ((point_count + 1, 1), "<u8"),
        "source_rows": ((member_count, 1), np.dtype(source_dtype).newbyteorder("<")),
    }


def validate_voxel_lineage(arrays, *, point_count, source_point_count, policy, cancel):
    """检查非空成员区间、源范围和全局唯一贡献，不把重复坐标当重复行。"""
    if set(arrays) != set(voxel_lineage_shapes(0, 0, "uint32")):
        raise InvalidRequestError("体素来源字段不完整")
    members = arrays["source_rows"]
    dtype = "uint32" if source_point_count <= 2**32 else "uint64"
    for name, (shape, expected) in voxel_lineage_shapes(
        point_count, len(members), dtype
    ).items():
        value = arrays[name]
        if value.shape != shape or value.dtype != expected or value.flags.writeable:
            raise InvalidRequestError("体素来源形状、精度或只读状态无效")
    offsets = arrays["member_offsets"][:, 0]
    if offsets[0] != 0 or offsets[-1] != len(members):
        raise InvalidRequestError("体素成员首尾区间无效")
    rows = min(policy.chunk_rows, policy.max_working_bytes // 96)
    if (
        rows < 1
        or len(members) * (np.dtype(dtype).itemsize + 1) > policy.max_working_bytes
    ):
        raise InvalidRequestError("体素来源唯一性校验超过工作预算")
    previous = None
    for start in range(0, point_count, rows):
        cancel()
        stop = min(start + rows, point_count)
        if np.any(offsets[start + 1 : stop + 1] <= offsets[start:stop]):
            raise InvalidRequestError("体素必须有非空实测成员")
        keys = arrays["voxel_keys"][start:stop]
        for key in keys:
            current = tuple(map(int, key))
            if previous is not None and current <= previous:
                raise InvalidRequestError("体素键必须唯一且按字典序排列")
            previous = current
    for start in range(0, len(members), rows):
        cancel()
        if np.any(members[start : start + rows] >= source_point_count):
            raise InvalidRequestError("体素来源行号越界")
    cancel()
    ordered = np.sort(members[:, 0])
    for start in range(0, max(0, len(ordered) - 1), rows):
        cancel()
        stop = min(len(ordered) - 1, start + rows)
        if np.any(ordered[start:stop] == ordered[start + 1 : stop + 1]):
            raise InvalidRequestError("体素来源重复计入同一原始行")


def voxel_lineage_chunk(arrays, selected, *, max_working_bytes):
    """逻辑子集重建 CSR，源行号保持原值。"""
    selected = np.asarray(selected, dtype=np.uint64)
    offsets = arrays["member_offsets"][:, 0]
    counts = offsets[selected + 1] - offsets[selected]
    total = sum(map(int, counts))
    cost = len(selected) * 64 + 8 + total * arrays["source_rows"].dtype.itemsize
    if cost > max_working_bytes:
        raise InvalidRequestError("体素来源访问超过工作预算")
    result = {
        "voxel_keys": arrays["voxel_keys"][selected],
        "member_offsets": np.empty((len(selected) + 1, 1), dtype="<u8"),
        "source_rows": np.empty((total, 1), dtype=arrays["source_rows"].dtype),
    }
    result["member_offsets"][0, 0] = 0
    cursor = 0
    for i, row in enumerate(selected):
        first, last = int(offsets[row]), int(offsets[row + 1])
        result["source_rows"][cursor : cursor + last - first] = arrays["source_rows"][
            first:last
        ]
        cursor += last - first
        result["member_offsets"][i + 1, 0] = cursor
    for value in result.values():
        value.setflags(write=False)
    return MappingProxyType(result)
