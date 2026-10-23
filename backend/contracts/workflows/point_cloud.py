"""三维点云的严格字段和同机二进制布局；不承载数组或 Broker 权限。"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    unique_ids,
)


def canonical_cloud_json(value: object) -> bytes:
    """点云描述与几何方法共用规范 JSON，拒绝非有限数。"""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


MAX_POINT_CLOUD_INPUT_BYTES = 1_000_000_000
JsonCount = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
PositiveCount = Annotated[int, Field(strict=True, gt=0, le=2**53 - 1)]
Sha256 = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
LengthUnit = Literal["m", "mm", "um"]
FieldDtype = Literal[
    "int8",
    "uint8",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "int64",
    "uint64",
    "float32",
    "float64",
]
FieldSemantic = Literal[
    "position", "normal", "color-rgb", "validity", "sample-origin", "scalar"
]
FIELD_WIDTHS = {
    "int8": 1,
    "uint8": 1,
    "int16": 2,
    "uint16": 2,
    "int32": 4,
    "uint32": 4,
    "int64": 8,
    "uint64": 8,
    "float32": 4,
    "float64": 8,
}
ShortText = Annotated[str, Field(strict=True, min_length=1, max_length=128)]


class CloudAxes(Contract):
    """轴语义声明；标签不是隐含的坐标变换。"""

    handedness: Literal["right", "left", "unknown"]
    axis_labels: tuple[ShortText, ShortText, ShortText]
    definition_source: Literal["metadata", "configuration", "unknown"]

    @model_validator(mode="after")
    def check_unknown(self) -> Self:
        """未知轴不能携带已确认手性。"""
        if (self.handedness == "unknown") != (self.definition_source == "unknown"):
            raise ValueError("轴定义来源与手性声明不一致")
        return self


class CloudSpatial(Contract):
    """点云长度单位、坐标系和轴定义。"""

    length_unit: LengthUnit | None
    unit_source: Literal["metadata", "configuration", "unknown"]
    frame_id: Identifier
    axes: CloudAxes

    @model_validator(mode="after")
    def check_unit(self) -> Self:
        """未知单位不得宣称来自已确认元数据。"""
        if (self.length_unit is None) != (self.unit_source == "unknown"):
            raise ValueError("长度单位与声明来源不一致")
        return self


class CloudField(Contract):
    """逻辑点属性；标量的 unit 必须显式给出，允许未知。"""

    name: Identifier
    semantic: FieldSemantic
    dtype: FieldDtype
    components: Annotated[int, Field(strict=True, ge=1, le=3)]
    unit: Identifier | None

    @model_validator(mode="after")
    def check_semantic(self) -> Self:
        """保留字段不能被普通标量冒充，也不隐式转换颜色。"""
        reserved = {
            "positions": ("position", 3, ("float32", "float64"), None),
            "normals": ("normal", 3, ("float32", "float64"), "1"),
            "colors": ("color-rgb", 3, ("uint8",), "1"),
            "validity": ("validity", 1, ("uint8",), "1"),
            "sample_origin": ("sample-origin", 1, ("uint8",), "1"),
        }
        if self.name in reserved:
            semantic, components, dtypes, unit = reserved[self.name]
            if (
                self.semantic != semantic
                or self.components != components
                or self.dtype not in dtypes
                or self.unit != unit
            ):
                raise ValueError(f"保留字段 {self.name} 的语义、分量、类型或单位不合法")
        elif self.semantic != "scalar" or self.components != 1:
            raise ValueError("普通属性必须是单分量 scalar")
        return self


class CloudBufferField(CloudField):
    """little-endian 连续属性块；偏移由整体布局校验。"""

    count: PositiveCount
    offset_bytes: JsonCount
    byte_length: PositiveCount


class PcdSourceMetadata(Contract):
    """原始 PCD 的组织、视点及其原坐标声明，不自动应用视点。"""

    format: Literal["pcd"]
    width: PositiveCount
    height: PositiveCount
    viewpoint: tuple[Finite, Finite, Finite, Finite, Finite, Finite, Finite]
    organized: StrictBool
    source_spatial: CloudSpatial

    @model_validator(mode="after")
    def check_organization(self) -> Self:
        """organized 只能表示源文件真实的二维组织。"""
        if self.organized != (self.height > 1):
            raise ValueError("organized 与 PCD height 不一致")
        return self


class CloudBufferDescriptor(Contract):
    """同机完整输入的描述，不包含 writer token 或运行内 cloud_id。"""

    format_id: Literal["amvision.point-cloud-buffer.v1"]
    point_count: PositiveCount
    content_length: Annotated[
        int, Field(strict=True, gt=0, le=MAX_POINT_CLOUD_INPUT_BYTES)
    ]
    fields: Annotated[tuple[CloudBufferField, ...], Field(min_length=1)]
    spatial: CloudSpatial
    source_observation_id: Identifier | None = None
    source_metadata: PcdSourceMetadata | None = None

    @model_validator(mode="after")
    def check_layout(self) -> Self:
        """严格紧密排列；只允许 dtype 对齐间隙，不接受额外尾部。"""
        unique_ids([field.name for field in self.fields], "fields")
        if not any(field.name == "positions" for field in self.fields):
            raise ValueError("点云必须声明 positions")
        cursor = 0
        for field in self.fields:
            if field.semantic == "sample-origin":
                raise ValueError("外部输入不能伪造派生 sample_origin")
            width = FIELD_WIDTHS[field.dtype]
            aligned = ((cursor + width - 1) // width) * width
            if (
                field.count != self.point_count
                or field.offset_bytes != aligned
                or field.byte_length != self.point_count * field.components * width
            ):
                raise ValueError(f"字段 {field.name} 的长度、顺序或对齐不合法")
            cursor = aligned + field.byte_length
        if cursor != self.content_length:
            raise ValueError("点云长度与完整布局不一致")
        if self.source_metadata is not None:
            if (
                self.source_metadata.width * self.source_metadata.height
                != self.point_count
            ):
                raise ValueError("PCD 组织尺寸与点数不一致")
        return self


class CloudFieldMapping(Contract):
    """文件字段到逻辑属性的显式映射；禁止猜测或丢弃列。"""

    source_names: Annotated[tuple[ShortText, ...], Field(min_length=1)]
    target_name: Identifier
    semantic: FieldSemantic
    dtype: FieldDtype
    components: Annotated[int, Field(strict=True, ge=1, le=3)]
    unit: Identifier | None

    @model_validator(mode="after")
    def check_mapping(self) -> Self:
        """每个分量必须有且只有一个源列。"""
        unique_ids(self.source_names, "source_names")
        if len(self.source_names) != self.components:
            raise ValueError("源列数必须等于目标分量数")
        self.to_field()
        return self

    def to_field(self) -> CloudField:
        """构造同一语义的运行字段。"""
        return CloudField(
            name=self.target_name,
            semantic=self.semantic,
            dtype=self.dtype,
            components=self.components,
            unit=self.unit,
        )


class CloudFileOptions(Contract):
    """严格文件 profile、空间声明及全部字段映射。"""

    profile_id: Literal[
        "ply-ascii",
        "ply-binary-le",
        "ply-binary-be",
        "pcd-ascii",
        "pcd-binary",
        "pcd-binary-compressed",
        "xyz-whitespace",
        "xyzn-whitespace",
        "xyzi-whitespace",
        "xyzrgb-whitespace",
    ]
    profile_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    spatial: CloudSpatial
    field_mapping: Annotated[tuple[CloudFieldMapping, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_fields(self) -> Self:
        """目标唯一且位置存在；源列不能被重复消费。"""
        names = [field.target_name for field in self.field_mapping]
        unique_ids(names, "target_name")
        unique_ids(
            [name for field in self.field_mapping for name in field.source_names],
            "源列",
        )
        if "positions" not in names:
            raise ValueError("文件映射必须包含 positions")
        if any(field.semantic == "sample-origin" for field in self.field_mapping):
            raise ValueError("外部文件不能伪造派生来源")
        layouts = {
            "xyz-whitespace": (("positions", ("x", "y", "z")),),
            "xyzn-whitespace": (
                ("positions", ("x", "y", "z")),
                ("normals", ("nx", "ny", "nz")),
            ),
            "xyzi-whitespace": (
                ("positions", ("x", "y", "z")),
                ("intensity", ("intensity",)),
            ),
            "xyzrgb-whitespace": (
                ("positions", ("x", "y", "z")),
                ("colors", ("r", "g", "b")),
            ),
        }
        if self.profile_id in layouts:
            actual = tuple(
                (field.target_name, field.source_names) for field in self.field_mapping
            )
            if actual != layouts[self.profile_id]:
                raise ValueError("文本 profile 的字段映射或列顺序不一致")
            if any(
                field.target_name != "colors"
                and field.dtype not in ("float32", "float64")
                for field in self.field_mapping
            ):
                raise ValueError("XYZ 文本非颜色字段必须声明 float32 或 float64")
        return self
