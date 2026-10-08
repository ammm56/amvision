"""二维观测、数值表与资源引用契约；不包含 PIN 或产品判定语义。"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Identifier = Annotated[
    str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
]
Point = tuple[Finite, Finite]
Matrix3 = tuple[
    tuple[Finite, Finite, Finite],
    tuple[Finite, Finite, Finite],
    tuple[Finite, Finite, Finite],
]


class Contract(BaseModel):
    """拒绝未声明字段和非有限数；构造后不允许替换属性。"""

    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, allow_inf_nan=False
    )


def unique_ids(values, field: str) -> None:
    """校验稳定身份唯一，禁止覆盖重复条目。"""
    if len(values) != len(set(values)):
        raise ValueError(f"{field} 存在重复 ID")


def require_invertible(matrix: Matrix3) -> None:
    """按归一化行向量检查矩阵退化，不依赖计算包或图像算法。"""
    rows = []
    for row in matrix:
        norm = max(abs(x) for x in row)
        if norm == 0:
            raise ValueError("坐标变换矩阵退化")
        rows.append([x / norm for x in row])
    a, b, c = rows
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if abs(determinant) < 1e-12:
        raise ValueError("坐标变换矩阵退化")


class ImageIdentity(Contract):
    """本次输入身份：调用 ID、图像 ID、尺寸和原始矩阵类型。"""

    run_id: Identifier
    image_id: Identifier
    width: Annotated[int, Field(strict=True, ge=1, le=32768)]
    height: Annotated[int, Field(strict=True, ge=1, le=32768)]
    dtype: Literal["uint8", "uint16", "float32"]
    coordinate_space: Literal["raw-image"] = "raw-image"


class ResourceReference(Contract):
    """项目内不可变资源版本与内容摘要；不能用本地路径代替引用。"""

    project_id: Identifier
    resource_id: Identifier
    version: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    kind: Literal["planar-calibration", "localization-template"]


class PoseObservation(Contract):
    """定位结果：reference 像素到当前 raw-image 像素的刚性变换。"""

    image: ImageIdentity
    state: Literal["found", "not_found", "ambiguous", "out_of_view"]
    image_from_reference: Matrix3 | None
    reference_id: Identifier
    reference_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    reason: Identifier | None

    @model_validator(mode="after")
    def check_pose(self) -> Self:
        """有效位姿禁止尺度/镜像吸收尺寸错误；无效位姿不得携带旧矩阵。"""
        if self.state != "found":
            if self.image_from_reference is not None or self.reason is None:
                raise ValueError("无效定位必须有原因且不得携带变换")
            return self
        if self.image_from_reference is None or self.reason is not None:
            raise ValueError("有效定位必须有变换且无错误原因")
        a, b, c = self.image_from_reference
        if any(abs(x - y) > 1e-8 for x, y in zip(c, (0, 0, 1))):
            raise ValueError("定位仅支持刚性变换")
        if (
            max(
                abs(a[0] ** 2 + b[0] ** 2 - 1),
                abs(a[1] ** 2 + b[1] ** 2 - 1),
                abs(a[0] * a[1] + b[0] * b[1]),
                abs(a[0] * b[1] - a[1] * b[0] - 1),
            )
            > 1e-6
        ):
            raise ValueError("定位不能缩放、镜像或切变")
        return self


class GeometricFeature(Contract):
    """图像中的有限观测几何；采样端点限定可测范围，不代表无限直线。"""

    feature_id: Identifier
    kind: Literal["point", "edge"]
    points: Annotated[tuple[Point, ...], Field(min_length=1, max_length=257)]
    residual_px: Annotated[Finite, Field(ge=0)] = 0.0

    @model_validator(mode="after")
    def check_shape(self) -> Self:
        """点只含一个坐标，边至少含两个不同坐标。"""
        if self.kind == "point" and len(self.points) != 1:
            raise ValueError("点特征必须包含一个坐标")
        if self.kind == "edge" and (len(self.points) < 2 or len(set(self.points)) < 2):
            raise ValueError("边特征缺少有效观测范围")
        return self


class FeatureObservations(Contract):
    """一次提取产生的通用几何集，观察 ID 用于阻止错帧与错分支混接。"""

    observation_id: Identifier
    image: ImageIdentity
    reference_id: Identifier
    features: Annotated[tuple[GeometricFeature, ...], Field(max_length=6144)]

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        """特征 ID 不得重复。"""
        unique_ids([f.feature_id for f in self.features], "features")
        return self


class NumericItem(Contract):
    """通用数值项：逐项单位、有限数或 null、有效性和机器原因码。"""

    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {
                    "properties": {
                        "valid": {"const": True},
                        "value": {"type": "number"},
                        "reason": {"type": "null"},
                    }
                },
                {
                    "properties": {
                        "valid": {"const": False},
                        "value": {"type": "null"},
                        "reason": {"type": "string"},
                    }
                },
            ]
        }
    )

    item_id: Identifier
    unit: Identifier
    value: Finite | None
    valid: StrictBool
    reason: Identifier | None

    @model_validator(mode="after")
    def check_validity(self) -> Self:
        """无效项不可携带数值，有效项必须有数值。"""
        if self.valid != (self.value is not None) or self.valid != (
            self.reason is None
        ):
            raise ValueError("数值、有效性与原因不一致")
        return self


class NumericTable(Contract):
    """通用数值表，不修改旧 measurements.v1 的字段和消费者。"""

    observation_id: Identifier
    items: Annotated[tuple[NumericItem, ...], Field(max_length=8192)]

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        """值表稳定 ID 不得重复。"""
        unique_ids([x.item_id for x in self.items], "items")
        return self


class LimitRule(Contract):
    """通用上下限规则；单位精确匹配，必检集合来自保存的配置。"""

    item_id: Identifier
    unit: Identifier
    enabled: StrictBool = True
    required: StrictBool = True
    lower: Finite | None = None
    upper: Finite | None = None
    include_lower: StrictBool = True
    include_upper: StrictBool = True

    @model_validator(mode="after")
    def check_limits(self) -> Self:
        """拒绝无界规则、倒置上下限和必然为空的开区间。"""
        if self.lower is None and self.upper is None:
            raise ValueError("至少配置一个界限")
        if self.lower is not None and self.upper is not None:
            if self.lower > self.upper or (
                self.lower == self.upper
                and not (self.include_lower and self.include_upper)
            ):
                raise ValueError("上下限区间无效")
        return self


class CalibrationPointPair(Contract):
    """原始图像点及其独立参考平面坐标，随不可变标定版本保存。"""

    image: Point
    world: Point


class CalibrationEvidence(Contract):
    """分离保存拟合点与验证点；这些证据不等于参考仪器的准确度证书。"""

    control_points: Annotated[
        tuple[CalibrationPointPair, ...], Field(min_length=3, max_length=4096)
    ]
    validation_points: Annotated[
        tuple[CalibrationPointPair, ...], Field(min_length=2, max_length=4096)
    ]


class PlanarCalibration(Contract):
    """经版本化资源保存的平面映射；有效区为当前图像中的多边形。"""

    image_width: Annotated[int, Field(strict=True, ge=1, le=32768)]
    image_height: Annotated[int, Field(strict=True, ge=1, le=32768)]
    model: Literal["similarity", "affine", "homography"]
    world_from_image: Matrix3
    unit: Literal["millimeter", "meter"]
    plane_id: Identifier
    valid_polygon: Annotated[tuple[Point, ...], Field(min_length=3, max_length=128)]
    fit_rms: Annotated[Finite, Field(ge=0)]
    validation_max_error: Annotated[Finite, Field(ge=0)]
    evidence: CalibrationEvidence | None = None

    @model_validator(mode="after")
    def check_geometry(self) -> Self:
        """拒绝退化矩阵与共线有效域；更细的覆盖约束由计算实现验证。"""
        require_invertible(self.world_from_image)
        points = self.valid_polygon
        area = sum(
            a[0] * b[1] - b[0] * a[1] for a, b in zip(points, (*points[1:], points[0]))
        )
        if abs(area) < 1e-9 or len(set(points)) != len(points):
            raise ValueError("标定有效域退化")
        if any(
            not (0 <= x < self.image_width and 0 <= y < self.image_height)
            for x, y in points
        ):
            raise ValueError("标定有效域必须位于图像内")
        # 使用凸覆盖区，禁止自交和凹多边形造成不确定的覆盖判定。
        signs = []
        for i, a in enumerate(points):
            b = points[(i + 1) % len(points)]
            # 每条有向边的其他点必须同侧；仅检查相邻转角不能排除星形自交。
            signs.extend(
                (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                for j, c in enumerate(points)
                if j not in {i, (i + 1) % len(points)}
            )
        if not (all(s > 1e-10 for s in signs) or all(s < -1e-10 for s in signs)):
            raise ValueError("标定有效域必须是严格凸多边形")
        if self.model != "homography" and self.world_from_image[2] != (0, 0, 1):
            raise ValueError("非投影标定不能包含透视项")
        denominators = [
            self.world_from_image[2][0] * x
            + self.world_from_image[2][1] * y
            + self.world_from_image[2][2]
            for x, y in points
        ]
        if not (
            all(d > 1e-10 for d in denominators)
            or all(d < -1e-10 for d in denominators)
        ):
            raise ValueError("标定有效域跨越投影无穷远，不能用于测量")
        if self.model == "similarity":
            a, b, _ = self.world_from_image
            if abs(a[0] - b[1]) > 1e-10 or abs(a[1] + b[0]) > 1e-10:
                raise ValueError("相似标定不能包含各向异性比例或切变")
        return self
