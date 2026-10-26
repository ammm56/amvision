"""三维测量证据集合；基础方向测量不依赖尺寸或边界，避免嵌套循环。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.measurement3d_directional import (
    MeasurementEvidenceItem,
)
from backend.contracts.workflows.dimension3d_evidence import (
    EdgePairEvidenceItem,
    ExtentsEvidenceItem,
    HoleEvidenceItem,
)
from backend.contracts.workflows.metrology import (
    Contract,
    Identifier,
    NumericItem,
    NumericTable,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import LengthUnit


class MeasurementEvidence3d(Contract):
    """三维量值证据；可独立落盘，支持摘要不是历史运行访问引用。"""

    format_id: Literal["amvision.measurement-evidence3d.v1"] = (
        "amvision.measurement-evidence3d.v1"
    )
    observation_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit
    items: Annotated[
        tuple[
            Annotated[
                MeasurementEvidenceItem
                | ExtentsEvidenceItem
                | EdgePairEvidenceItem
                | HoleEvidenceItem,
                Field(discriminator="kind"),
            ],
            ...,
        ],
        Field(max_length=8192),
    ]

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        """证据与质量处于同一次观测及评价空间。"""
        unique_ids([item.item_id for item in self.items], "items")
        for item in self.items:
            p = item.method.parameters
            if (p.frame_id, p.length_unit, item.quality.metrics.observation_id) != (
                self.frame_id,
                self.length_unit,
                self.observation_id,
            ):
                raise ValueError("测量证据空间或观测不一致")
        groups = {}
        for item in self.items:
            if isinstance(item, MeasurementEvidenceItem):
                continue
            groups.setdefault(item.method.parameters_sha256, []).append(item)
        for siblings in groups.values():
            first = siblings[0]
            if {i.item_id for i in siblings} != {
                o.item_id for o in first.method.parameters.outputs
            }:
                raise ValueError("同一尺寸测量的启用输出必须完整保存")
            common = first.model_dump(exclude={"item_id", "component", "value"})
            if any(
                i.model_dump(exclude={"item_id", "component", "value"}) != common
                for i in siblings[1:]
            ):
                raise ValueError("同一尺寸测量的几何、质量和支持必须一致")
        return self

    def numeric_table(self) -> NumericTable:
        """同一结果生成现有 NumericTable，避免量值与证据各算一次。"""
        return NumericTable(
            observation_id=self.observation_id,
            items=tuple(
                NumericItem(
                    item_id=i.item_id,
                    unit=self.length_unit,
                    value=i.value,
                    valid=i.valid,
                    reason=i.reason,
                )
                for i in self.items
            ),
        )
