"""几何节点参数适配；不复制算法契约或 Workflow 参数绑定机制。"""

from typing import Annotated, Literal, Self

from pydantic import Field, RootModel, model_validator

from backend.contracts.workflows.geometry3d import (
    BuildFrameParameters,
    CropCloudParameters,
    FitPlaneParameters,
    Roi3d,
)
from backend.contracts.workflows.metrology import Contract, unique_ids


class RoiPayload(RootModel[Roi3d]):
    """公开 roi3d.v1 保持原联合对象形状，不包额外 value。"""


class ParameterRoiSource(Contract):
    """目标与有限边界均来自显式配方。"""

    kind: Literal["parameters"]
    roi: Roi3d
    bounds: Annotated[tuple[Roi3d, ...], Field(max_length=8191)] = ()

    @model_validator(mode="after")
    def check_dependencies(self) -> Self:
        """复用裁剪算法的完整坐标、重复 ID 和依赖校验。"""
        CropCloudParameters(roi_id=self.roi.roi_id, rois=(self.roi, *self.bounds))
        return self


class InputRoiSource(Contract):
    """目标只从 roi 端口接收，所有依赖边界仍固定在配方中。"""

    kind: Literal["input"]
    bounds: Annotated[tuple[Roi3d, ...], Field(max_length=8191)] = ()

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        """边界自身必须闭合；目标输入不能替依赖补隐式边界。"""
        unique_ids([roi.roi_id for roi in self.bounds], "bounds")
        if self.bounds:
            CropCloudParameters(roi_id=self.bounds[0].roi_id, rois=self.bounds)
        return self


class CropNodeParameters(Contract):
    """来源显式互斥，整个 source 由同一个受信参数编辑器维护。"""

    source: Annotated[ParameterRoiSource | InputRoiSource, Field(discriminator="kind")]


class PlaneNodeParameters(Contract):
    """一份算法配置对应一个原子编辑草稿。"""

    settings: FitPlaneParameters


class FrameNodeParameters(Contract):
    """基准、方向、原点和质量策略作为一个配置原子提交。"""

    settings: BuildFrameParameters


class TransformNodeParameters(Contract):
    """变换完全来自 pose，不提供第二个手填矩阵或默认位姿。"""
