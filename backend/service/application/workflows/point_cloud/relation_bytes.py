"""关系派生块复用现有字段与来源校验，工作内存只保留当前记录尾部。"""

from types import SimpleNamespace

import numpy as np

from backend.contracts.workflows.point_cloud_assets import (
    AssetGeneratedLineage,
    AssetProfileLineage,
    AssetVoxelLineage,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.documents.cloud_lineage_validation import (
    LineageBytesValidator,
)


class RelationBytesValidator:
    """对一次同根派生链逐块检查，索引上限使用真实父成员点数。"""

    def __init__(self, asset):
        """预编译有界布局；源行号上限仍取最初输入，不取派生点数。"""
        origin, source_count = asset.original_observation()
        self.fields, self.validators = [], []
        self.tail, self.previous = b"", None
        cursor = 0
        counts = [asset.point_count]
        for step in asset.relation.steps:
            lineage_fields = []
            for array in step.arrays:
                stop = cursor + array.byte_length()
                field = (
                    array.name,
                    cursor,
                    stop,
                    array.columns,
                    np.dtype(array.dtype).newbyteorder("<"),
                )
                if array.group == "lineage":
                    lineage_fields.append(field)
                elif array.group == "indices":
                    self.fields.append(
                        (*field, counts[step.parent], step.kind == "subset")
                    )
                else:
                    maximum = {"validity": 1, "sample_origin": 2}.get(array.name)
                    if step.state.normal_info is not None:
                        maximum = {
                            "normal_valid": 1,
                            "normal_oriented": 1,
                            "normal_reason": 5,
                        }.get(array.name, maximum)
                    if maximum is not None:
                        self.fields.append((*field, maximum + 1, False))
                cursor = stop
            if lineage_fields:
                arrays = {a.name: a for a in step.arrays if a.group == "lineage"}
                common = dict(source=origin, source_point_count=source_count)
                try:
                    if step.state.lineage_kind == "surface":
                        lineage = AssetGeneratedLineage(
                            **common, face_count=arrays["source_faces"].rows
                        )
                    elif step.state.lineage_kind == "grid-profile":
                        lineage = AssetProfileLineage(
                            **common,
                            kind="grid-profile",
                            cell_count=arrays["cell_indices"].rows,
                            source_count=arrays["cell_sources"].rows,
                        )
                    elif step.state.lineage_kind == "voxel-aggregate":
                        lineage = AssetVoxelLineage(
                            **common,
                            kind="voxel-aggregate",
                            member_count=arrays["source_rows"].rows,
                            source_dtype=arrays["source_rows"].dtype,
                            aggregation=step.state.voxel_aggregation,
                            grid=step.state.voxel_grid,
                        )
                    else:
                        raise InvalidRequestError("关系生成来源类型缺失")
                    self.validators.append(
                        LineageBytesValidator(
                            SimpleNamespace(
                                point_count=step.state.point_count, lineage=lineage
                            ),
                            layouts=lineage_fields,
                        )
                    )
                except (KeyError, ValueError) as error:
                    raise InvalidRequestError("关系生成来源布局无效") from error
            counts.append(step.state.point_count)

    def check(self, data, offset):
        """不解码整云；跨块校验索引顺序及字段枚举，来源沿用原校验器。"""
        for validator in self.validators:
            validator.check(data, offset)
        for _, start, stop, width, dtype, upper, ordered in self.fields:
            low, high = max(start, offset), min(stop, offset + len(data))
            if low >= high:
                continue
            joined = self.tail + data[low - offset : high - offset]
            row_bytes = width * dtype.itemsize
            end = len(joined) // row_bytes * row_bytes
            values = np.frombuffer(joined[:end], dtype=dtype)
            self.tail = joined[end:]
            if np.any(values >= upper) or np.any(values < 0):
                raise InvalidRequestError("关系派生索引或标记越界")
            if ordered and len(values):
                if (self.previous is not None and values[0] <= self.previous) or np.any(
                    values[1:] <= values[:-1]
                ):
                    raise InvalidRequestError("关系子集索引重复或倒序")
                self.previous = int(values[-1])
            if high == stop:
                if self.tail:
                    raise InvalidRequestError("关系派生字段截断")
                self.previous = None
