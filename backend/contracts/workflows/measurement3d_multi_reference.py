"""同一查询线的多基准参数；每项仍展开为既有独立测量契约。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.measurement3d_parameters import (
    DirectionalPolicy,
    MeasureStepParameters,
)
from backend.contracts.workflows.measurement3d_query import MeasurementQuery
from backend.contracts.workflows.metrology import Contract, Identifier, unique_ids
from backend.contracts.workflows.point_cloud import LengthUnit


class ReferenceMeasurement(DirectionalPolicy):
    """独立量项与基准支持策略，不共享较宽松的质量条件。"""

    item_id: Identifier
    reference_feature_id: Identifier


class MultiReferenceMode(Contract):
    """顶面和查询线显式共用，参考平面按行配置。"""

    kind: Literal["directional-references"]
    target_feature_id: Identifier
    query: MeasurementQuery
    items: Annotated[
        tuple[ReferenceMeasurement, ...], Field(min_length=1, max_length=8192)
    ]


class MultiReferenceStepParameters(Contract):
    """仅减少重复接线，不更改每项算法、数值和证据格式。"""

    frame_id: Identifier
    length_unit: LengthUnit
    mode: MultiReferenceMode

    def measurements(self) -> tuple[MeasureStepParameters, ...]:
        """复用单项严格校验及原参数快照，顺序与配方一致。"""
        return tuple(
            MeasureStepParameters(
                item_id=item.item_id,
                frame_id=self.frame_id,
                length_unit=self.length_unit,
                mode=dict(
                    kind="directional-planes",
                    target_feature_id=self.mode.target_feature_id,
                    query=self.mode.query,
                    **item.model_dump(exclude={"item_id"}),
                ),
            )
            for item in self.mode.items
        )

    @model_validator(mode="after")
    def check_items(self) -> Self:
        """禁止重名量项和遗漏质量限值，失败不隐式删行。"""
        unique_ids([item.item_id for item in self.mode.items], "items")
        self.measurements()
        return self
