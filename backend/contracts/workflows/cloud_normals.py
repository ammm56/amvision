"""法向估计的显式邻域、质量和定向参数，不提供生产阈值。"""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import LengthUnit

Positive = Annotated[Finite, Field(gt=0)]
Cosine = Annotated[Finite, Field(gt=0, le=1)]
Count = Annotated[int, Field(strict=True, ge=1, le=2**31 - 2)]


class UnrestrictedSupport(Contract):
    """主动选择无距离截断；仍受显式工作预算约束。"""

    kind: Literal["unrestricted"]


class BoundedSupport(Contract):
    """包含距离等号的有限支持。"""

    kind: Literal["bounded"]
    max_distance: Positive


class KnnNormals(Contract):
    """k 是其他邻居数，自身按逻辑身份排除一次。"""

    kind: Literal["knn"]
    neighbors: Count
    support: Annotated[
        UnrestrictedSupport | BoundedSupport, Field(discriminator="kind")
    ]


class RadiusNormals(Contract):
    """闭球全部邻居，不隐式截断密集支持。"""

    kind: Literal["radius"]
    radius: Positive


class HybridNormals(Contract):
    """闭球内最多指定数量的其他邻居，显式区别于全部半径支持。"""

    kind: Literal["hybrid"]
    radius: Positive
    max_neighbors: Count


class NormalQuality(Contract):
    """支持含查询点；数值退化硬条件不由质量参数关闭。"""

    min_support_points: Annotated[int, Field(strict=True, ge=3, le=2**31 - 1)]
    min_normal_gap: Annotated[Finite, Field(ge=0, le=1)]
    max_rms: Annotated[Finite, Field(ge=0)]
    max_surface_variation: Annotated[Finite, Field(ge=0, le=1 / 3)]


class UnorientedNormal(Contract):
    """只声明无符号法向轴，不宣称方向正确。"""

    kind: Literal["unoriented"]


class DirectionNormal(Contract):
    """方向在输入坐标系中定义，正交时保持未定向。"""

    kind: Literal["direction"]
    direction: tuple[Finite, Finite, Finite]
    min_abs_cosine: Cosine

    @model_validator(mode="after")
    def nonzero(self):
        """禁止零方向，归一采用缩放避免有限大值溢出。"""
        if not any(self.direction):
            raise ValueError("参考方向不能为零")
        return self


class ViewpointNormal(Contract):
    """观测点与输入单位/坐标一致，不默认相机原点。"""

    kind: Literal["viewpoint"]
    position: tuple[Finite, Finite, Finite]
    facing: Literal["toward", "away"]
    min_abs_cosine: Cosine


NormalOrientation = Annotated[
    UnorientedNormal | DirectionNormal | ViewpointNormal, Field(discriminator="kind")
]


class EstimateNormalsParameters(Contract):
    """同一完整输入空间索引；每项策略均需配方明确选择。"""

    neighborhood: Annotated[
        KnnNormals | RadiusNormals | HybridNormals, Field(discriminator="kind")
    ]
    quality: NormalQuality
    orientation: NormalOrientation
    frame_id: Identifier
    length_unit: LengthUnit
    existing_normals: Literal["reject", "replace"]
    diagnostics: StrictBool

    @model_validator(mode="after")
    def support_capacity(self):
        """不接受永远无法满足的有限邻居/最小支持组合。"""
        n = self.neighborhood
        maximum = (
            n.neighbors
            if n.kind == "knn"
            else n.max_neighbors
            if n.kind == "hybrid"
            else None
        )
        if maximum is not None and self.quality.min_support_points > maximum + 1:
            raise ValueError("最小支持点数超过邻域允许数量")
        return self
