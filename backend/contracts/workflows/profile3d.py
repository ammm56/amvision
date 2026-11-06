"""B07 已标定变长轮廓与显式扫描位移，不读取设备或求解标定。"""

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
    CloudField,
    CloudSpatial,
    FIELD_WIDTHS,
    JsonCount,
    MAX_POINT_CLOUD_INPUT_BYTES,
    PositiveCount,
    Sha256,
    ShortText,
)


class FixedProfileStep(Contract):
    """原采集行号对应位移；origin_line_id 的位置为扫描零点。"""

    kind: Literal["fixed-step"]
    origin_line_id: JsonCount
    step: Positive


class EncoderProfilePositions(Contract):
    """原编码器位置经显式尺度和零点换算，方向由 scan_direction 给定。"""

    kind: Literal["encoder-positions"]
    dtype: Literal["float32", "float64"]
    scale: Positive
    origin: Finite


class CalibratedProfiles(Contract):
    """轮廓 X/高度已按 spatial 单位标定；扫描位置是独立物理量。"""

    format_id: Literal["amvision.calibrated-profiles.v1"]
    point_count: PositiveCount
    profile_count: PositiveCount
    dtype: Literal["float32", "float64"]
    calibration_id: Identifier
    calibration_revision: Identifier
    spatial: CloudSpatial
    origin: Point3
    x_direction: Point3
    scan_direction: Point3
    height_direction: Point3
    displacement: Annotated[
        FixedProfileStep | EncoderProfilePositions, Field(discriminator="kind")
    ]
    position_dtype: Literal["float32", "float64"]

    @model_validator(mode="after")
    def check_basis(self) -> Self:
        """只接已确认的正交坐标；不隐式归一化、不复制空行或缩小位移。"""
        if self.spatial.length_unit is None or self.spatial.axes.handedness != "right":
            raise ValueError("轮廓标定必须明确长度单位和右手输出坐标")
        axes = (self.x_direction, self.scan_direction, self.height_direction)
        for index, axis in enumerate(axes):
            require_unit(axis)
            for other in axes[index + 1 :]:
                if abs(fsum(a * b for a, b in zip(axis, other))) > ORTHOGONAL_TOLERANCE:
                    raise ValueError("轮廓 X、扫描及高度方向必须正交")
        return self

    def input_layout(self, *, has_validity: bool):
        """NPZ 成员和同机连续块共用字段、形状与类型，不包含 pickle 对象。"""
        layout = [
            ("profiles", self.dtype, (self.point_count, 2)),
            ("line_offsets", "uint64", (self.profile_count + 1,)),
            ("line_ids", "uint64", (self.profile_count,)),
        ]
        if isinstance(self.displacement, EncoderProfilePositions):
            layout.append(
                ("encoder_positions", self.displacement.dtype, (self.profile_count,))
            )
        if has_validity:
            layout.append(("validity", "uint8", (self.point_count,)))
        return tuple(layout)

    def input_bytes(self, *, has_validity: bool) -> int:
        """总载荷包括行表；不能只检查 XYZ 或轮廓记录大小。"""
        return sum(
            FIELD_WIDTHS[dtype] * shape[0] * (shape[1] if len(shape) == 2 else 1)
            for _, dtype, shape in self.input_layout(has_validity=has_validity)
        )

    def row_layout(self):
        """完整采集行表；空轮廓同样占一行，不与点字段混排。"""
        return tuple(
            item
            for item in self.input_layout(has_validity=False)
            if item[0] != "profiles"
        )

    def row_bytes(self) -> int:
        """无 padding 的 little-endian 原始行表长度。"""
        return sum(
            FIELD_WIDTHS[dtype] * shape[0] for _, dtype, shape in self.row_layout()
        )

    def cloud_fields(self, *, has_validity: bool) -> tuple[CloudField, ...]:
        """实测记录身份逐点保留；原采集行号不是连续点索引。"""
        definitions = [
            ("positions", "position", self.position_dtype, 3, None),
            ("raw_profile_x", "scalar", self.dtype, 1, self.spatial.length_unit),
            ("raw_profile_height", "scalar", self.dtype, 1, self.spatial.length_unit),
            ("acquisition_line_id", "scalar", "uint64", 1, "1"),
            ("profile_sample_index", "scalar", "uint64", 1, "1"),
            ("validity", "validity", "uint8", 1, "1"),
            ("sample_status", "scalar", "uint8", 1, "1"),
        ]
        if isinstance(self.displacement, EncoderProfilePositions):
            definitions.append(
                ("raw_encoder_position", "scalar", self.displacement.dtype, 1, "1")
            )
        if has_validity:
            definitions.append(("input_mask", "scalar", "uint8", 1, "1"))
        return tuple(
            CloudField(name=n, semantic=s, dtype=d, components=c, unit=u)
            for n, s, d, c, u in definitions
        )


class ProfileBufferDescriptor(Contract):
    """同机 little-endian 连续块，固定顺序、无 padding，标定由载荷固定。"""

    format_id: Literal["amvision.profile-buffer.v1"]
    profiles: CalibratedProfiles
    has_validity: bool = Field(strict=True)
    content_length: Annotated[
        int, Field(strict=True, gt=0, le=MAX_POINT_CLOUD_INPUT_BYTES)
    ]

    @model_validator(mode="after")
    def check_length(self) -> Self:
        """完整长度精确匹配，包括缺行身份和编码器行表。"""
        if self.content_length != self.profiles.input_bytes(
            has_validity=self.has_validity
        ):
            raise ValueError("轮廓二进制载荷长度与声明不一致")
        return self


class ProfileFileInput(Contract):
    """NPZ 不携带另一套标定；文件模式标定以节点参数为唯一来源。"""

    kind: Literal["file"]
    file_format: Literal["npz"]
    profiles: CalibratedProfiles
    has_validity: bool = Field(strict=True)


class ProfileLocalInput(Contract):
    """数组模式不允许节点覆写调用方固定的标定。"""

    kind: Literal["local-array"]


class ProfilesToCloudParameters(Contract):
    """轮廓节点的两种显式入口；不用于规则标量网格。"""

    settings: Annotated[
        ProfileFileInput | ProfileLocalInput, Field(discriminator="kind")
    ]


class ProfileSource(Contract):
    """可持久化的原始轮廓观测；行表摘要绑定空行及其编码器位置。"""

    kind: Literal["calibrated-profiles"]
    profiles: CalibratedProfiles
    input_format: Literal["npz", "array"]
    content_length: Annotated[
        int, Field(strict=True, gt=0, le=MAX_POINT_CLOUD_INPUT_BYTES)
    ]
    content_sha256: Sha256
    row_table_sha256: Sha256
    file_name: ShortText | None
    has_validity: bool = Field(strict=True)

    @model_validator(mode="after")
    def check_source(self) -> Self:
        """数组必须匹配完整布局，文件名不是访问路径或权限。"""
        if self.input_format == "array":
            if self.file_name is not None:
                raise ValueError("轮廓数组不能携带文件名")
            ProfileBufferDescriptor(
                format_id="amvision.profile-buffer.v1",
                profiles=self.profiles,
                has_validity=self.has_validity,
                content_length=self.content_length,
            )
        elif (
            self.file_name is None
            or self.file_name in (".", "..")
            or any(c in self.file_name for c in "/\\:")
        ):
            raise ValueError("轮廓文件名无效")
        return self

    def check_cloud(self, count, spatial, fields) -> None:
        """原始转换不能省略原值字段；派生云由索引/生成来源说明原始身份。"""
        actual = tuple(
            CloudField.model_validate(
                f.model_dump(include=set(CloudField.model_fields))
            )
            for f in fields
        )
        if (
            count != self.profiles.point_count
            or spatial != self.profiles.spatial
            or actual != self.profiles.cloud_fields(has_validity=self.has_validity)
        ):
            raise ValueError("轮廓观测与完整原始点云不一致")
