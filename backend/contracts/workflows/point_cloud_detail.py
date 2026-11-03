"""已保存点云的可重建显示索引；不是新的点云资产或测量结果。"""

from typing import Literal
from typing import Annotated
from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import SupportBounds
from backend.contracts.workflows.metrology import Contract, ResourceReference
from backend.contracts.workflows.point_cloud import (
    CloudField,
    CloudSpatial,
    JsonCount,
    PositiveCount,
    Sha256,
    FIELD_WIDTHS,
)


class DetailField(CloudField):
    """原始字段在紧密行记录中的偏移，数据精度不变。"""

    offset: JsonCount


class DetailBlock(Contract):
    """一块有限数量的实测或生成顶点，摘要绑定实际字节。"""

    block_id: JsonCount
    count: PositiveCount
    bounds: SupportBounds
    byte_length: PositiveCount
    sha256: Sha256


class CloudDetailIndex(Contract):
    """全资产范围与叶块范围分开；不包含运行引用或本地路径。"""

    format_id: Literal["amvision.point-cloud-detail.v1"] = (
        "amvision.point-cloud-detail.v1"
    )
    source: ResourceReference
    generation: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$", strict=True)]
    spatial: CloudSpatial
    vertex_kind: Literal["source", "generated"]
    point_count: PositiveCount
    source_point_count: PositiveCount
    valid_count: PositiveCount
    excluded_count: JsonCount
    bounds: SupportBounds
    fields: tuple[DetailField, ...]
    row_bytes: PositiveCount
    logical_offset: JsonCount
    identity_offset: JsonCount
    leaf_limit: PositiveCount
    blocks: tuple[DetailBlock, ...]

    @model_validator(mode="after")
    def validate_layout(self):
        """拒绝字段重叠、大小伪报、缺块和来源计数不一致。"""
        if (
            self.source.kind != "point-cloud"
            or self.valid_count + self.excluded_count != self.point_count
        ):
            raise ValueError("点云细节来源或计数无效")
        offset = 0
        names = set()
        for field in self.fields:
            if field.offset != offset or field.name in names:
                raise ValueError("点云细节字段布局无效")
            names.add(field.name)
            offset += FIELD_WIDTHS[field.dtype] * field.components
        if "positions" not in names or (
            self.logical_offset,
            self.identity_offset,
            self.row_bytes,
        ) != (offset, offset + 8, offset + 16):
            raise ValueError("点云细节行布局无效")
        if (
            not self.blocks
            or sum(block.count for block in self.blocks) != self.valid_count
        ):
            raise ValueError("点云细节块不完整")
        for index, block in enumerate(self.blocks):
            if (
                block.block_id != index
                or block.count > self.leaf_limit
                or block.byte_length != block.count * self.row_bytes
            ):
                raise ValueError("点云细节块长度无效")
            if any(
                a < low or b > high
                for a, b, low, high in zip(
                    block.bounds.min, block.bounds.max, self.bounds.min, self.bounds.max
                )
            ):
                raise ValueError("点云细节块越界")
        return self
