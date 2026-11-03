"""源字段布局计划；复用 NumPy 只读视图，必须换字节序或重排时才分配。"""

import numpy as np
from numpy.lib.recfunctions import structured_to_unstructured

from backend.contracts.workflows.point_cloud import CloudFieldMapping


def can_view_field(source_dtype: np.dtype, mapping: CloudFieldMapping) -> bool:
    """标量字段类型及等间隔偏移完全符合目标时，无需第二份属性数组。"""
    target = np.dtype(mapping.dtype).newbyteorder("<")
    fields = [source_dtype.fields[name] for name in mapping.source_names]
    if any(dtype != target for dtype, *_ in fields):
        return False
    offsets = [item[1] for item in fields]
    if len(offsets) < 2:
        return True
    stride = offsets[1] - offsets[0]
    return stride != 0 and all(
        current - previous == stride for previous, current in zip(offsets, offsets[1:])
    )


def readonly_records(data: np.ndarray) -> np.ndarray:
    """readonly buffer 保留解码内存所有权，不能通过字段视图恢复可写标志。"""
    return np.frombuffer(
        memoryview(data).toreadonly(), dtype=data.dtype, count=len(data)
    )


def field_view(data: np.ndarray, mapping: CloudFieldMapping) -> np.ndarray:
    """计划已确认可零复制；库行为不符立即报错，不静默分配或降精度。"""
    value = structured_to_unstructured(
        data[list(mapping.source_names)],
        dtype=np.dtype(mapping.dtype).newbyteorder("<"),
        copy=False,
        casting="no",
    )
    if not np.shares_memory(value, data) or value.flags.writeable:
        raise RuntimeError("点云字段只读视图与已准入布局不一致")
    return value
