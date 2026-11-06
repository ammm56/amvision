"""B06 标定标量栅格；深度、物理高度和显示图片不能相互冒充。"""

from math import fsum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import (
    ORTHOGONAL_TOLERANCE,
    Point3,
    Positive,
    require_unit,
)
from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import (
    FIELD_WIDTHS,
    MAX_POINT_CLOUD_INPUT_BYTES,
    CloudSpatial,
    CloudField,
    PositiveCount,
    Sha256,
    ShortText,
)

RasterDtype = Literal[
    "uint8", "uint16", "int16", "uint32", "int32", "float32", "float64"
]


class PinholeDepth(Contract):
    """已去畸变、零 skew 的针孔模型；像素中心使用整数列/行坐标。"""

    kind: Literal["rectified-pinhole"]
    depth_kind: Literal["axial-z", "ray-range"]
    fx: Positive
    fy: Positive
    cx: Finite
    cy: Finite


class OrthographicHeight(Contract):
    """原点是第零行列像素的零高位置；行列与高度方向均显式声明。"""

    kind: Literal["orthographic-height"]
    origin: Point3
    column_direction: Point3
    row_direction: Point3
    height_direction: Point3
    column_step: Positive
    row_step: Positive

    @model_validator(mode="after")
    def check_basis(self) -> Self:
        """轴必须正交且为单位向量；不代替调用方归一化或改正方向。"""
        vectors = (self.column_direction, self.row_direction, self.height_direction)
        for i, axis in enumerate(vectors):
            require_unit(axis)
            for other in vectors[i + 1 :]:
                if abs(fsum(a * b for a, b in zip(axis, other))) > ORTHOGONAL_TOLERANCE:
                    raise ValueError("高度网格的行、列和高度方向必须正交")
        return self


RasterProjection = Annotated[
    PinholeDepth | OrthographicHeight, Field(discriminator="kind")
]


class RasterValidity(Contract):
    """原始哨兵在缩放前判断，物理范围在缩放后判断；无默认阈值。"""

    invalid_raw_values: tuple[Finite, ...]
    minimum: Finite | None
    maximum: Finite | None

    @model_validator(mode="after")
    def check_range(self) -> Self:
        """边界均包含；负高度合法，正深度另由针孔定义校验。"""
        if len(set(self.invalid_raw_values)) != len(self.invalid_raw_values):
            raise ValueError("原始无效值不能重复")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("标量物理范围倒置")
        return self


class CalibratedRaster(Contract):
    """完整标定正文随来源保存；ID/版本是追溯标签，不授予资产访问权。"""

    format_id: Literal["amvision.calibrated-raster.v1"]
    width: PositiveCount
    height: PositiveCount
    dtype: RasterDtype
    calibration_id: Identifier
    calibration_revision: Identifier
    spatial: CloudSpatial
    projection: RasterProjection
    value_scale: Positive
    value_offset: Finite
    validity: RasterValidity
    position_dtype: Literal["float32", "float64"]

    @model_validator(mode="after")
    def check_input(self) -> Self:
        """像素身份可精确表达；文件载荷和解码预算由各自入口独立准入。"""
        if self.point_count() > 2**53 - 1:
            raise ValueError("标量网格原始总数超过公开整数精度")
        if self.spatial.length_unit is None or self.spatial.axes.handedness != "right":
            raise ValueError("标定网格必须明确长度单位和右手输出坐标")
        if isinstance(self.projection, PinholeDepth) and (
            self.spatial.axes.axis_labels != ("X", "Y", "Z")
        ):
            raise ValueError("针孔输出必须明确 X 向右、Y 向下、Z 向前的相机坐标")
        return self

    def point_count(self) -> int:
        """无效像素也占原始记录，后续筛选不得改变此源总数。"""
        return self.width * self.height

    def cloud_fields(self, *, has_mask: bool) -> tuple[CloudField, ...]:
        """无损输出字段，也是来源恢复时的完整类型约束。"""
        definitions = [
            ("positions", "position", self.position_dtype, 3, None),
            ("raw_samples", "scalar", self.dtype, 1, "1"),
            ("validity", "validity", "uint8", 1, "1"),
            ("sample_status", "scalar", "uint8", 1, "1"),
        ]
        if has_mask:
            definitions.append(("input_mask", "scalar", "uint8", 1, "1"))
        return tuple(
            CloudField(name=n, semantic=s, dtype=d, components=c, unit=u)
            for n, s, d, c, u in definitions
        )


class RasterBufferDescriptor(Contract):
    """同机 LE 连续 HW 标量及可选紧随其后的 uint8 掩码，不携带租约。"""

    format_id: Literal["amvision.raster-buffer.v1"]
    raster: CalibratedRaster
    has_mask: bool = Field(strict=True)
    content_length: Annotated[
        int, Field(strict=True, gt=0, le=MAX_POINT_CLOUD_INPUT_BYTES)
    ]

    @model_validator(mode="after")
    def check_length(self) -> Self:
        """完整长度必须匹配，不接受行 padding、额外尾部或隐式颜色通道。"""
        expected = self.raster.point_count() * (
            FIELD_WIDTHS[self.raster.dtype] + self.has_mask
        )
        if expected != self.content_length:
            raise ValueError("网格二进制载荷与标量/掩码布局不一致")
        return self


class RasterFileInput(Contract):
    """文件由节点持有完整标定，不依赖文件名猜测格式或单位。"""

    kind: Literal["file"]
    file_format: Literal["npy", "png", "tiff"]
    raster: CalibratedRaster


class RasterLocalInput(Contract):
    """同机输入只使用 PREPARE 中已固定的标定，不允许参数覆盖。"""

    kind: Literal["local-array"]


class RasterToCloudParameters(Contract):
    """公开节点显式二选一，切换来源时不得保留另一来源参数。"""

    settings: Annotated[RasterFileInput | RasterLocalInput, Field(discriminator="kind")]


class RasterSource(Contract):
    """持久可携带的标定正文及原载荷身份，不包含系统路径或租约。"""

    kind: Literal["calibrated-raster"]
    raster: CalibratedRaster
    input_format: Literal["array", "npy", "png", "tiff"]
    content_length: Annotated[
        int, Field(strict=True, gt=0, le=MAX_POINT_CLOUD_INPUT_BYTES)
    ]
    content_sha256: Sha256
    file_name: ShortText | None
    has_mask: bool = Field(strict=True)

    @model_validator(mode="after")
    def check_source(self) -> Self:
        """数组具有固定布局；文件名仅为标签，不具有访问权限。"""
        if self.input_format == "array":
            if self.file_name is not None:
                raise ValueError("数组来源不能携带文件名")
            RasterBufferDescriptor(
                format_id="amvision.raster-buffer.v1",
                raster=self.raster,
                has_mask=self.has_mask,
                content_length=self.content_length,
            )
        elif (
            self.has_mask
            or self.file_name is None
            or any(c in self.file_name for c in "/\\:")
            or self.file_name in (".", "..")
        ):
            raise ValueError("标量文件来源名称或掩码不合法")
        return self

    def check_cloud(self, count, spatial, fields) -> None:
        """只校验原始转换云，派生子集在其独立索引来源保留原始总数。"""
        if count != self.raster.point_count() or spatial != self.raster.spatial:
            raise ValueError("标定来源与完整像素点云不一致")
        actual = tuple(
            CloudField.model_validate(
                f.model_dump(include=set(CloudField.model_fields))
            )
            for f in fields
        )
        if actual != self.raster.cloud_fields(has_mask=self.has_mask):
            raise ValueError("标定来源缺少完整原始字段或类型不一致")
