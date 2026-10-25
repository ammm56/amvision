"""运行内点云身份和版本化派生方法；不包含数组、系统路径或释放权限。"""

from __future__ import annotations

from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, StrictBool, StrictInt, model_validator

from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    ResourceReference,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import (
    CloudField,
    CloudSpatial,
    JsonCount,
    LengthUnit,
    PcdSourceMetadata,
    PositiveCount,
    Sha256,
    canonical_cloud_json,
)
from backend.contracts.workflows.geometry3d import (
    CropCloudParameters,
    FitPlaneParameters,
)
from backend.contracts.workflows.geometry3d_methods import TransformCloudParameters
from backend.contracts.workflows.boundary3d import (
    BoundaryTopology,
    ExtractBoundaryParameters,
    BoundarySelection,
)


class NormalizeCloudUnits(Contract):
    """单位确认与归一参数；缺省不等于猜测源单位。"""

    target_unit: Literal["mm"] = "mm"
    source_unit: LengthUnit | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="before")
    @classmethod
    def reject_null_source(cls, value):
        """未填写使用缺省；显式 null 不是已确认的单位。"""
        if (
            isinstance(value, dict)
            and "source_unit" in value
            and value["source_unit"] is None
        ):
            raise ValueError("source_unit 不能显式为 null")
        return value


class CloudSentinel(Contract):
    """精确哨兵；与字段 dtype 的可表示性在消费真实云时校验。"""

    field: Identifier
    values: Annotated[
        tuple[
            StrictInt | Finite | Annotated[str, Field(pattern=r"^(0|-?[1-9][0-9]*)$")],
            ...,
        ],
        Field(min_length=1, max_length=3),
    ]
    match: Literal["all", "any"]


class FilterCloudValid(Contract):
    """有限性过滤参数，始终包含位置并尊重 validity。"""

    finite_fields: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    sentinels: tuple[CloudSentinel, ...]

    @model_validator(mode="after")
    def check_fields(self) -> Self:
        """位置不可绕过，重复字段不是第二种过滤策略。"""
        unique_ids(self.finite_fields, "finite_fields")
        if "positions" not in self.finite_fields:
            raise ValueError("finite_fields 必须包含 positions")
        return self


class CloudInvalidCounts(Contract):
    """各原因计数可重叠，不相加作为删除点数。"""

    mask: JsonCount
    non_finite: JsonCount
    sentinel: JsonCount


class FilterCloudSummary(Contract):
    """过滤节点的关闭结构，不用于产品公差判断。"""

    state: Literal["ready", "unavailable"]
    reason: Identifier | None
    input_count: JsonCount | None
    kept_count: JsonCount | None
    removed_count: JsonCount | None
    invalid_counts: CloudInvalidCounts | None

    @model_validator(mode="after")
    def check_counts(self) -> Self:
        """区分缺测和真实空云，保证输出计数可核对。"""
        counts = (
            self.input_count,
            self.kept_count,
            self.removed_count,
            self.invalid_counts,
        )
        if self.state == "unavailable":
            if self.reason is None or any(value is not None for value in counts):
                raise ValueError("unavailable 过滤摘要不能伪造计数")
        elif self.reason is not None or any(value is None for value in counts):
            raise ValueError("ready 过滤摘要缺少计数")
        elif (
            self.kept_count + self.removed_count != self.input_count
            or any(
                value > self.removed_count
                for value in self.invalid_counts.model_dump().values()
            )
            or self.removed_count > sum(self.invalid_counts.model_dump().values())
        ):
            raise ValueError("过滤计数不一致")
        return self


class NormalizeCloudMethod(Contract):
    """实际单位归一方法的封闭版本及参数。"""

    method_id: Literal["normalize-units"]
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    parameters: NormalizeCloudUnits
    parameters_sha256: Sha256


class FilterCloudMethod(Contract):
    """实际稳定顺序过滤方法的封闭版本及参数。"""

    method_id: Literal["filter-valid"]
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    parameters: FilterCloudValid
    parameters_sha256: Sha256


class CropCloudMethod(Contract):
    """闭边界裁剪及全部 ROI 参数的不可变方法身份。"""

    method_id: Literal["crop-roi"]
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    parameters: CropCloudParameters
    parameters_sha256: Sha256


class PlaneSupportMethod(Contract):
    """稳健支持视图；indices_sha256 覆盖递增父逻辑行号的 LE 字节。"""

    method_id: Literal["fit-plane-support"]
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    parameters: FitPlaneParameters
    parameters_sha256: Sha256
    indices_sha256: Sha256


class TransformCloudMethod(Contract):
    """刚体变换记录实际矩阵和位姿摘要，不依赖可变配方。"""

    method_id: Literal["transform-cloud"]
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    parameters: TransformCloudParameters
    parameters_sha256: Sha256


class BoundaryCloudMethod(Contract):
    """边界参数和实际来源布局摘要共同绑定派生内容。"""

    method_id: Literal["extract-boundary"]
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    parameters: ExtractBoundaryParameters
    parameters_sha256: Sha256
    vertices_sha256: Sha256


class BoundarySelectionMethod(Contract):
    """按明确段 ID 选择连接，保留实测或生成顶点来源。"""

    method_id: Literal["select-boundary"]
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    parameters: BoundarySelection
    parameters_sha256: Sha256


CloudMethod = Annotated[
    NormalizeCloudMethod
    | FilterCloudMethod
    | CropCloudMethod
    | PlaneSupportMethod
    | TransformCloudMethod
    | BoundaryCloudMethod
    | BoundarySelectionMethod,
    Field(discriminator="method_id"),
]


class CloudParent(Contract):
    """同一次运行中的不可变父身份。"""

    cloud_id: Identifier
    revision: PositiveCount


class CloudFileSource(Contract):
    """文件仍使用现有 file-ref 契约，由既有 validator 校验。"""

    kind: Literal["file"]
    file: dict[str, JsonValue]
    source_observation_id: Identifier | None


class CloudLocalSource(Contract):
    """同机输入保存布局及载荷摘要，不传输 Broker receipt。"""

    kind: Literal["local-array"]
    content_sha256: Sha256
    descriptor_sha256: Sha256
    source_observation_id: Identifier | None


class CloudDerivedSource(Contract):
    """资源依赖引用同 run 父云；位姿值对象快照归入变换方法。"""

    kind: Literal["derived"]
    parents: Annotated[tuple[CloudParent, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_parents(self) -> Self:
        """父身份集合不能重复。"""
        unique_ids([parent.cloud_id for parent in self.parents], "parents")
        return self


class CloudAssetSource(Contract):
    """本次读取的完整持久资源身份；历史运行 ID 不取得当前访问权。"""

    kind: Literal["asset"]
    reference: ResourceReference

    @model_validator(mode="after")
    def check_kind(self) -> Self:
        """持久来源只能是点云资源。"""
        if self.reference.kind != "point-cloud":
            raise ValueError("点云来源必须引用点云资产")
        return self


CloudSource = Annotated[
    CloudFileSource | CloudLocalSource | CloudDerivedSource | CloudAssetSource,
    Field(discriminator="kind"),
]


class CloudProvenance(Contract):
    """方法参数正文与来源状态；运行内可访问不等于已经持久保存。"""

    method: CloudMethod | None
    parents: tuple[CloudParent, ...]
    source_retained: StrictBool

    @model_validator(mode="after")
    def check_method(self) -> Self:
        """派生必须有方法与父身份，摘要绑定严格参数正文。"""
        unique_ids([parent.cloud_id for parent in self.parents], "parents")
        if (self.method is None) != (not self.parents):
            raise ValueError("原始输入和派生方法的父身份不一致")
        if self.method is not None:
            digest = sha256(
                canonical_cloud_json(self.method.parameters.model_dump(mode="json"))
            ).hexdigest()
            if digest != self.method.parameters_sha256:
                raise ValueError("点云方法参数摘要不一致")
        return self


class CloudReference(Contract):
    """公开结构只描述运行身份；访问权仍须通过当前 registry 完整核对。"""

    format_id: Literal["amvision.point-cloud-ref.v1"]
    state: Literal["ready", "unavailable"]
    reason: Identifier | None
    run_id: Identifier
    observation_id: Identifier
    cloud_id: Identifier | None
    revision: PositiveCount | None
    point_count: JsonCount | None
    fields: tuple[CloudField, ...] | None
    spatial: CloudSpatial
    source: CloudSource
    source_metadata: PcdSourceMetadata | None
    provenance: CloudProvenance
    sample_origin: Literal["measured", "interpolated", "extrapolated", "mixed"] | None
    vertex_kind: Literal["source", "generated"] | None
    topology: BoundaryTopology | None

    @model_validator(mode="after")
    def check_state(self) -> Self:
        """缺测不分配假资源；空派生云仍是有真实身份的 ready。"""
        identity = (
            self.cloud_id,
            self.revision,
            self.point_count,
            self.fields,
            self.sample_origin,
            self.vertex_kind,
        )
        if self.state == "unavailable":
            if self.reason is None or any(
                value is not None
                for value in (*identity, self.source_metadata, self.topology)
            ):
                raise ValueError("unavailable 不能携带点云资源")
        else:
            if self.reason is not None or any(value is None for value in identity):
                raise ValueError("ready 点云缺少资源身份或字段")
            names = [field.name for field in self.fields]
            unique_ids(names, "fields")
            if "positions" not in names:
                raise ValueError("点云必须包含 positions")
            if self.sample_origin == "mixed" and "sample_origin" not in names:
                raise ValueError("mixed 必须有逐点来源")
            if self.vertex_kind == "generated" and (
                names != ["positions"] or self.sample_origin != "interpolated"
            ):
                raise ValueError("生成顶点只保存坐标，不自动插值原始属性")
            if (
                self.topology is not None
                and self.topology.point_count != self.point_count
            ):
                raise ValueError("边界连接与点云数量不一致")
            if (
                self.source_metadata is not None
                and self.source_metadata.width * self.source_metadata.height
                != self.point_count
            ):
                raise ValueError("PCD 组织信息与点数不一致")
        if isinstance(self.source, CloudDerivedSource):
            if self.source.parents != self.provenance.parents:
                raise ValueError("派生来源与追溯父身份不一致")
        elif self.provenance.method is not None or self.provenance.parents:
            raise ValueError("原始输入不能带派生方法")
        return self
