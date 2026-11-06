"""通用高度图的固定格定义；不承载显示采样或隐含补洞规则。"""

from typing import Annotated, Literal, Self
import math

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import require_rotation
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import LengthUnit, PositiveCount
from backend.contracts.workflows.raster3d import OrthographicHeight


class CurrentGridFrame(Contract):
    """网格明确属于输入点云当前坐标，不自动采用包围盒。"""

    kind: Literal["current-frame"]
    frame_id: Identifier


class PoseGridFrame(Contract):
    """网格属于本次有效位姿的目标坐标，历史矩阵不是运行授权。"""

    kind: Literal["pose-frame"]
    pose_id: Identifier
    target_frame_id: Identifier


class HeightMapParameters(Contract):
    """原点为首格中心，行列步距独立；四种聚合必须主动选择。"""

    frame: Annotated[CurrentGridFrame | PoseGridFrame, Field(discriminator="kind")]
    length_unit: LengthUnit
    grid: OrthographicHeight
    width: PositiveCount
    height: PositiveCount
    aggregation: Literal["minimum", "maximum", "mean", "median"]

    @model_validator(mode="after")
    def check_grid(self) -> Self:
        """拒绝格数溢出、镜像格及无法表示的外边界，不填写容量默认值。"""
        if self.width * self.height > 2**53 - 1:
            raise ValueError("高度图格数超过公开整数范围")
        axes = (
            self.grid.column_direction,
            self.grid.row_direction,
            self.grid.height_direction,
        )
        require_rotation(axes)
        for count, step in (
            (self.width, self.grid.column_step),
            (self.height, self.grid.row_step),
        ):
            end = (count - 0.5) * step
            previous = (count - 1.5) * step
            if not math.isfinite(end) or end <= previous:
                raise ValueError("高度图边界无法以有限精度表示")
        return self

    def cell_count(self) -> int:
        """完整格数含空格；不得用有效点数替代预算口径。"""
        return self.width * self.height
