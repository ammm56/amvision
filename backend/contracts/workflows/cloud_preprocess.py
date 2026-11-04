"""点云预处理方法参数；生产邻域和剔除阈值必须显式配置。"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import LengthUnit


class StatisticalDenoise(Contract):
    """K 个其他点的平均距离，按全云均值加总体标准差倍数保留。"""

    kind: Literal["statistical"]
    neighbors: Annotated[int, Field(strict=True, ge=1)]
    std_ratio: Annotated[Finite, Field(gt=0)]


class RadiusDenoise(Contract):
    """闭球内其他点数量，不把查询点自身算作一个邻居。"""

    kind: Literal["radius"]
    radius: Annotated[Finite, Field(gt=0)]
    min_neighbors: Annotated[int, Field(strict=True, ge=1)]


DenoiseSettings = Annotated[
    StatisticalDenoise | RadiusDenoise, Field(discriminator="kind")
]


class DenoiseCloudParameters(Contract):
    """距离沿输入已确认的物理单位，不隐式归一或设置工件默认值。"""

    settings: DenoiseSettings


class StrideResample(Contract):
    """按当前逻辑行抽取；offset 不是原始文件行号。"""

    kind: Literal["stride"]
    every_k_points: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
    offset: Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]

    @model_validator(mode="after")
    def check_offset(self):
        """起始相位必须在一个行间隔内。"""
        if self.offset >= self.every_k_points:
            raise ValueError("offset 必须小于 every_k_points")
        return self


class VoxelGrid(Contract):
    """固定相位轴对齐格；单位和坐标身份必须与实际输入一致。"""

    voxel_size: Annotated[Finite, Field(gt=0)]
    grid_origin: tuple[Finite, Finite, Finite]
    frame_id: Identifier
    length_unit: LengthUnit


class VoxelRepresentative(VoxelGrid):
    """每格选距质心最近的原点，所有属性逐位保留。"""

    kind: Literal["voxel-representative"]


class VoxelCentroid(VoxelGrid):
    """等权质心仅生成坐标，误差上限采用输入物理单位。"""

    kind: Literal["voxel-centroid"]
    max_position_error: Annotated[Finite, Field(gt=0)]
    attributes: Literal["positions-only"]


ResampleSettings = Annotated[
    StrideResample | VoxelRepresentative | VoxelCentroid, Field(discriminator="kind")
]


class ResampleCloudParameters(Contract):
    """三种明确重采样方法，不包含自动回退或隐式去噪。"""

    settings: ResampleSettings
