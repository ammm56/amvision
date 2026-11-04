"""点云预处理方法参数；生产邻域和剔除阈值必须显式配置。"""

from typing import Annotated, Literal

from pydantic import Field

from backend.contracts.workflows.metrology import Contract, Finite


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
