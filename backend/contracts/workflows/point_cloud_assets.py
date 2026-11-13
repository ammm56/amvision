"""点云持久资产契约；不包含运行句柄、内存权限或本机路径。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.metrology import (
    Contract,
    Identifier,
    ResourceReference,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import (
    CloudField,
    CloudFieldMapping,
    CloudFileOptions,
    CloudSpatial,
    FIELD_WIDTHS,
    JsonCount,
    PcdSourceMetadata,
    Sha256,
    ShortText,
)
from backend.contracts.workflows.point_cloud_runtime import (
    CloudMethod,
    ResampleCloudMethod,
)
from backend.contracts.workflows.cloud_voxel import CloudVoxelGrid
from backend.contracts.workflows.cloud_normal_info import CloudNormalInfo
from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from hashlib import sha256
from backend.contracts.workflows.boundary3d_observations import BoundaryEvidence
from backend.contracts.workflows.dimension3d_evidence import CircleSnapshot
from backend.contracts.workflows.arc3d_evidence import ArcEvidenceItem
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.raster3d import RasterSource
from backend.contracts.workflows.profile3d import ProfileSource
from backend.contracts.workflows.height_map_evidence import HeightMapEvidence
from backend.contracts.workflows.edge_sampling_evidence import SamplingEvidence
from backend.contracts.workflows.edge_evidence import EdgeEvidence
from backend.contracts.workflows.relation3d_assets import RelationAsset


class CloudBlob(Contract):
    """仅允许格式规定的成员，实际对象键由服务生成。"""

    role: Literal[
        "original",
        "data",
        "indices",
        "lineage",
        "profile-rows",
        "height-map",
        "sampling",
        "edge",
        "relation",
    ]
    name: Literal[
        "original.bin",
        "data.bin",
        "source-indices.bin",
        "lineage.bin",
        "profile-rows.bin",
        "height-map.bin",
        "sampling.bin",
        "edge.bin",
        "relation.bin",
    ]
    content_length: JsonCount
    sha256: Sha256

    @model_validator(mode="after")
    def check_name(self) -> Self:
        """角色与名称不可交叉或变成任意路径。"""
        if (
            self.name
            != {
                "original": "original.bin",
                "data": "data.bin",
                "indices": "source-indices.bin",
                "lineage": "lineage.bin",
                "profile-rows": "profile-rows.bin",
                "height-map": "height-map.bin",
                "sampling": "sampling.bin",
                "edge": "edge.bin",
                "relation": "relation.bin",
            }[self.role]
        ):
            raise ValueError("点云数据块角色与名称不一致")
        return self


class CloudAssetField(CloudField):
    """持久连续属性块允许合法的零点派生结果。"""

    count: JsonCount
    offset_bytes: JsonCount
    byte_length: JsonCount


class CloudSourceNames(Contract):
    """规范字段到原始列的可逆映射，不承担路径职责。"""

    name: Identifier
    source_names: Annotated[tuple[ShortText, ...], Field(min_length=1)]


class AssetFileSource(Contract):
    """已核验原始文件来源。"""

    kind: Literal["file"]
    file_name: ShortText
    content_length: JsonCount
    content_sha256: Sha256
    profile_id: str
    profile_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    source_observation_id: Identifier | None


class AssetLocalSource(Contract):
    """冻结的同机来源摘要，不携带 arena 身份。"""

    kind: Literal["local-array"]
    content_sha256: Sha256
    descriptor_sha256: Sha256
    source_observation_id: Identifier | None


class AssetDerivedSource(Contract):
    """派生来源只通过持久追溯表达。"""

    kind: Literal["derived"]


AssetSource = Annotated[
    AssetFileSource
    | AssetLocalSource
    | AssetDerivedSource
    | RasterSource
    | ProfileSource,
    Field(discriminator="kind"),
]


class AssetParent(Contract):
    """未保存的父描述仅供审计，不授予数据读取权。"""

    content_sha256: Sha256
    reference: ResourceReference | None

    @model_validator(mode="after")
    def check_reference(self) -> Self:
        """有持久引用时采用资源内容摘要，不混用文件摘要。"""
        if self.reference is not None and (
            self.reference.kind != "point-cloud"
            or self.reference.sha256 != self.content_sha256
        ):
            raise ValueError("点云父资源与内容摘要不一致")
        return self


class AssetProvenance(Contract):
    """保存完整方法参数而不是旧 run/cloud ID。"""

    method: CloudMethod | None
    parents: tuple[AssetParent, ...]
    source_retained: StrictBool

    @model_validator(mode="after")
    def check_method(self) -> Self:
        """方法和父描述共同存在，参数摘要必须匹配。"""
        if (self.method is None) != (not self.parents):
            raise ValueError("点云持久方法与父来源不一致")
        unique_ids([p.content_sha256 for p in self.parents], "parents")
        if (
            self.method is not None
            and sha256(
                canonical_cloud_json(self.method.parameters.model_dump(mode="json"))
            ).hexdigest()
            != self.method.parameters_sha256
        ):
            raise ValueError("点云方法参数摘要不一致")
        return self


class AssetIndices(Contract):
    """独立物化数据的原始行号；不能用作父资源访问权限。"""

    dtype: Literal["uint32", "uint64"]
    count: JsonCount
    source_point_count: JsonCount
    source: AssetSource

    @model_validator(mode="after")
    def check_raster_count(self) -> Self:
        """过滤之后仍以完整像素网格作为原始行号范围。"""
        if (
            isinstance(self.source, RasterSource)
            and self.source_point_count != self.source.raster.point_count()
        ):
            raise ValueError("标量资产原始总点数不一致")
        return self


class AssetGeneratedLineage(Contract):
    """固定布局：u64 源边、f64 权重、u64 CSR 偏移及 u64 源面。"""

    kind: Literal["surface"] = "surface"
    source_point_count: JsonCount
    face_count: JsonCount
    source: AssetSource

    def byte_length(self, point_count: int) -> int:
        """来源块精确长度；生成位置单独保存在 data 块。"""
        return point_count * 32 + (point_count + 1) * 8 + self.face_count * 24


class AssetProfileLineage(Contract):
    """格表、原始支持 CSR 和逐顶点运算；不冒用源面布局。"""

    kind: Literal["grid-profile"]
    source_point_count: JsonCount
    cell_count: JsonCount
    source_count: JsonCount
    source: AssetSource

    def byte_length(self, point_count: int) -> int:
        """LE 格索引/偏移/高度与顶点格对/权重/种类/站位/侧序的总长度。"""
        return self.cell_count * 32 + 8 + self.source_count * 8 + point_count * 42


class AssetVoxelLineage(Contract):
    """体素键、成员 CSR 与最初源行号，不把质心伪装成原点。"""

    kind: Literal["voxel-aggregate"]
    source_point_count: JsonCount
    member_count: JsonCount
    source_dtype: Literal["uint32", "uint64"]
    source: AssetSource
    aggregation: ResampleCloudMethod
    grid: CloudVoxelGrid

    @model_validator(mode="after")
    def check_dtype(self) -> Self:
        """源行宽度与最初总点数一致，成员不得多于最初记录数。"""
        if self.source_dtype != (
            "uint32" if self.source_point_count <= 2**32 else "uint64"
        ):
            raise ValueError("体素源行号宽度与原始点数不一致")
        if self.member_count > self.source_point_count:
            raise ValueError("体素成员不能重复计权")
        if self.aggregation.parameters.settings.kind != "voxel-centroid":
            raise ValueError("体素来源必须保存原质心聚合方法")
        return self

    def byte_length(self, point_count: int) -> int:
        """LE 坐标格键与 CSR 的精确长度。"""
        return (
            point_count * 24
            + (point_count + 1) * 8
            + self.member_count * FIELD_WIDTHS[self.source_dtype]
        )


class CloudAssetBase(Contract):
    """两种存储表达的共同内容，所有字段参与内容摘要。"""

    format_id: Literal["amvision.point-cloud-asset.v1"]
    kind: Literal["point-cloud"]
    source: AssetSource
    spatial: CloudSpatial
    provenance: AssetProvenance
    blobs: Annotated[tuple[CloudBlob, ...], Field(min_length=1, max_length=7)]
    source_field_names: tuple[CloudSourceNames, ...]
    parent_assets: tuple[ResourceReference, ...]
    point_count: JsonCount
    source_metadata: PcdSourceMetadata | None
    vertex_kind: Literal["source", "generated"]
    topology: BoundaryTopology | None
    boundary: BoundaryEvidence | None = None
    circle: CircleSnapshot | None = Field(default=None, exclude_if=lambda v: v is None)
    arc_evidence: tuple[ArcEvidenceItem, ...] = Field(
        default=(), max_length=8192, exclude_if=lambda v: not v
    )
    normal_info: CloudNormalInfo | None = None
    height_map: HeightMapEvidence | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    sampling: SamplingEvidence | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    edge: EdgeEvidence | None = Field(default=None, exclude_if=lambda v: v is None)
    relation: RelationAsset | None = Field(default=None, exclude_if=lambda v: v is None)

    def original_observation(self) -> tuple[AssetSource, int]:
        """返回持久内容中的原始观测及记录总数，不解析外部父资产。"""
        return self.source, self.point_count

    @model_validator(mode="after")
    def check_common(self) -> Self:
        """不允许遗漏属性映射、伪造父保留或组织点数。"""
        unique_ids([b.role for b in self.blobs], "blobs")
        relation_blob = next((b for b in self.blobs if b.role == "relation"), None)
        if (self.relation is None) != (relation_blob is None):
            raise ValueError("关系证据与派生数据块不一致")
        if self.relation is not None and (
            self.representation != "array-blocks"
            or relation_blob.content_length != self.relation.byte_length()
        ):
            raise ValueError("关系资产必须保存原云数组和完整派生链")
        if self.relation is not None:
            if any(
                (
                    self.boundary,
                    self.circle,
                    self.arc_evidence,
                    self.height_map,
                    self.sampling,
                    self.edge,
                )
            ):
                raise ValueError("关系资产不能混入绑定其他输入的附属输出")
            members = (self, *(step.state for step in self.relation.steps))
            primary = members[self.relation.primary]
            for stored in self.relation.items:
                p = stored.evidence.method.parameters
                if (p.frame_id, p.length_unit) != (
                    primary.spatial.frame_id,
                    primary.spatial.length_unit,
                ):
                    raise ValueError("关系资产主输入与测量空间不一致")
                for side, member in zip(stored.evidence.support, stored.members):
                    if member is not None and (
                        side.point_count != members[member].point_count
                        or members[member].spatial != primary.spatial
                    ):
                        raise ValueError("关系支持数量或空间与保存成员不一致")
        edge_blob = next((b for b in self.blobs if b.role == "edge"), None)
        if (self.edge is None) != (edge_blob is None):
            raise ValueError("实测边证据与数据块不一致")
        if self.edge is not None:
            e = self.edge
            if (
                self.representation != "array-blocks"
                or self.vertex_kind != "source"
                or e.input_count != self.point_count
                or (e.evaluation.frame_id, e.evaluation.length_unit)
                != (self.spatial.frame_id, self.spatial.length_unit)
                or edge_blob.content_length != e.byte_length()
                or (e.method.kind == "height-jump" and self.height_map is None)
                or (e.method.kind == "normal-crease" and self.normal_info is None)
            ):
                raise ValueError("实测边必须随同一完整输入及评价来源保存")
        sampling_blob = next((b for b in self.blobs if b.role == "sampling"), None)
        if (self.sampling is None) != (sampling_blob is None):
            raise ValueError("采样诊断证据与数据块不一致")
        if self.sampling is not None and (
            self.representation != "array-blocks"
            or self.normal_info is None
            or self.sampling.input_count != self.point_count
            or self.sampling.vertex_kind != self.vertex_kind
            or sampling_blob.content_length != self.sampling.byte_length()
        ):
            raise ValueError("采样诊断必须与参与计算的完整点云及法向一同保存")
        height_blob = next((b for b in self.blobs if b.role == "height-map"), None)
        if (self.height_map is None) != (height_blob is None):
            raise ValueError("高度图证据与数据块不一致")
        if self.height_map is not None:
            h = self.height_map
            dtype = next((f.dtype for f in self.fields if f.name == "positions"), None)
            source_frame = (
                h.pose.source_frame_id
                if h.pose is not None
                else h.parameters.frame.frame_id
            )
            if (
                h.input_count,
                h.vertex_kind,
                h.dtype,
                h.parameters.length_unit,
                source_frame,
            ) != (
                self.point_count,
                self.vertex_kind,
                dtype,
                self.spatial.length_unit,
                self.spatial.frame_id,
            ) or height_blob.content_length != h.byte_length():
                raise ValueError("高度图与保存输入、坐标或布局不一致")
            if self.representation != "array-blocks":
                raise ValueError("高度图必须与参与计算的完整数组一同保存")
        if self.topology is not None and self.topology.point_count != self.point_count:
            raise ValueError("资产边界连接与数量不一致")
        if self.arc_evidence:
            if self.circle is None:
                raise ValueError("圆弧证据需要同资产圆模型")
            MeasurementEvidence3d(
                observation_id=self.circle.quality.metrics.observation_id,
                frame_id=self.spatial.frame_id,
                length_unit=self.spatial.length_unit,
                items=self.arc_evidence,
            )
            if any(
                len(i.support) != 1
                or i.support[0].feature != self.circle
                or i.support[0].topology != self.topology
                or i.support[0].point_count != self.point_count
                for i in self.arc_evidence
            ):
                raise ValueError("圆弧证据与资产模型或完整支持不一致")
        if self.boundary is not None:
            evaluation = self.boundary.method.parameters.evaluation
            if (
                not self.boundary.valid
                or self.boundary.geometry != self.topology
                or (evaluation.frame_id, evaluation.length_unit)
                != (self.spatial.frame_id, self.spatial.length_unit)
            ):
                raise ValueError("资产边界证据与保存点云不一致")
        if self.circle is not None:
            circle = self.circle
            metrics = {m.item_id: m.value for m in circle.quality.metrics.items}
            evaluation = circle.method.evaluation
            if (
                self.boundary is not None
                or self.representation != "array-blocks"
                or self.edge is not None
                or self.topology is None
                or evaluation is None
                or circle.method.boundary is None
                or circle.method.boundary.geometry is None
                or (evaluation.frame_id, evaluation.length_unit)
                != (self.spatial.frame_id, self.spatial.length_unit)
                or (circle.valid and metrics["support_count"] != self.point_count)
                or tuple(s.segment_id for s in self.topology.segments)
                != circle.method.resolved_segment_ids
            ):
                raise ValueError("资产圆模型必须对应唯一完整拟圆支持")
            original = {
                s.segment_id: s for s in circle.method.boundary.geometry.segments
            }
            if any(
                original[s.segment_id].model_dump(exclude={"start"})
                != s.model_dump(exclude={"start"})
                for s in self.topology.segments
            ):
                raise ValueError("资产圆支持拓扑与拟圆来源不一致")
        if self.normal_info is not None:
            self.normal_info.check_fields(
                self.fields, self.spatial, generated=self.vertex_kind == "generated"
            )
        if (
            self.normal_info is None
            and self.vertex_kind == "generated"
            and [f.name for f in self.fields] != ["positions"]
        ):
            raise ValueError("生成顶点不得伪造原始属性")
        unique_ids([m.name for m in self.source_field_names], "source_field_names")
        unique_ids(
            [s for m in self.source_field_names for s in m.source_names], "source_names"
        )
        keys = [r.model_dump_json() for r in self.parent_assets]
        unique_ids(keys, "parent_assets")
        refs = [p.reference for p in self.provenance.parents if p.reference is not None]
        if set(keys) != {r.model_dump_json() for r in refs} or any(
            r.kind != "point-cloud" for r in self.parent_assets
        ):
            raise ValueError("点云父资源列表与追溯不一致")
        if self.source.kind == "derived":
            if self.provenance.method is None or (
                self.provenance.source_retained
                and len(refs) != len(self.provenance.parents)
            ):
                raise ValueError("派生点云缺少已保存来源或方法")
        elif self.provenance.method is not None:
            raise ValueError("原始点云不能带派生方法")
        if (
            self.source_metadata is not None
            and self.source_metadata.width * self.source_metadata.height
            != self.point_count
        ):
            raise ValueError("点云组织信息与数量不一致")
        unique_ids([f.name for f in self.fields], "fields")
        fields = {f.name: f for f in self.fields}
        if isinstance(self.source, (RasterSource, ProfileSource)):
            self.source.check_cloud(self.point_count, self.spatial, self.fields)
            if (
                self.source_metadata is not None
                or self.topology is not None
                or self.normal_info is not None
            ):
                raise ValueError("标定原始资产不能混入 PCD 视点或派生几何信息")
        if self.source_field_names and set(fields) != {
            m.name for m in self.source_field_names
        }:
            raise ValueError("点云原字段映射必须覆盖全部已存字段")
        for mapping in self.source_field_names:
            if len(mapping.source_names) != fields[mapping.name].components:
                raise ValueError("点云源字段分量数不一致")
        return self


class OriginalCloudAsset(CloudAssetBase):
    """保存完整原始文件及已通过解析验证的读取参数。"""

    representation: Literal["file-original"]
    original_format: Literal["ply", "pcd", "xyz"]
    original_file_name: ShortText
    profile_id: str
    profile_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    fields: Annotated[tuple[CloudField, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_original(self) -> Self:
        """原件字节摘要、文件名、格式与全部读取参数必须一致。"""
        if (
            len(self.blobs) != 1
            or self.blobs[0].role != "original"
            or not isinstance(self.source, AssetFileSource)
            or self.vertex_kind != "source"
            or self.topology is not None
            or self.normal_info is not None
        ):
            raise ValueError("原文件资产需要唯一 original 数据块及文件来源")
        blob = self.blobs[0]
        if (
            blob.content_length,
            blob.sha256,
            self.original_file_name,
            self.profile_id,
            self.profile_version,
        ) != (
            self.source.content_length,
            self.source.content_sha256,
            self.source.file_name,
            self.source.profile_id,
            self.source.profile_version,
        ):
            raise ValueError("原文件资产与来源不一致")
        if any(
            c in self.original_file_name for c in ("/", "\\", ":")
        ) or self.original_file_name in (".", ".."):
            raise ValueError("原文件名不能包含路径")
        options = self.file_options()
        if (
            self.original_format
            != (
                "ply"
                if options.profile_id.startswith("ply-")
                else "pcd"
                if options.profile_id.startswith("pcd-")
                else "xyz"
            )
            or self.point_count == 0
        ):
            raise ValueError("原文件格式或点数无效")
        return self

    def file_options(self) -> CloudFileOptions:
        """恢复同一严格解码参数，不根据文件后缀猜测。"""
        names = {m.name: m.source_names for m in self.source_field_names}
        if set(names) != {f.name for f in self.fields}:
            raise ValueError("原件缺少完整字段映射")
        return CloudFileOptions(
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            spatial=self.spatial,
            field_mapping=tuple(
                CloudFieldMapping(
                    source_names=names[f.name],
                    target_name=f.name,
                    **f.model_dump(exclude={"name"}),
                )
                for f in self.fields
            ),
        )


class RasterCloudAsset(CloudAssetBase):
    """逐字节保存原标量文件，重读使用同一标定与无效规则。"""

    representation: Literal["raster-original"]
    fields: Annotated[tuple[CloudField, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_original(self) -> Self:
        """不把数组源或计算点云伪装成原始文件。"""
        if (
            not isinstance(self.source, RasterSource)
            or self.source.input_format == "array"
            or len(self.blobs) != 1
            or self.blobs[0].role != "original"
            or self.vertex_kind != "source"
            or self.topology is not None
            or self.normal_info is not None
            or self.boundary is not None
            or self.source_metadata is not None
            or self.source_field_names
            or not self.provenance.source_retained
        ):
            raise ValueError("标量原件必须保留完整原文件和标定")
        if (self.blobs[0].content_length, self.blobs[0].sha256) != (
            self.source.content_length,
            self.source.content_sha256,
        ):
            raise ValueError("标量原件与内容摘要不一致")
        return self


class ArrayCloudAsset(CloudAssetBase):
    """所有字段按 little-endian 连续块无损存储。"""

    representation: Literal["array-blocks"]
    fields: Annotated[tuple[CloudAssetField, ...], Field(min_length=1)]
    content_length: JsonCount
    indices: AssetIndices | None
    lineage: AssetGeneratedLineage | AssetProfileLineage | AssetVoxelLineage | None

    def original_observation(self) -> tuple[AssetSource, int]:
        """源点索引和生成关系均沿用最初观测，不把派生点数当原始总数。"""
        origin = self.lineage if self.lineage is not None else self.indices
        return (
            (origin.source, origin.source_point_count)
            if origin is not None
            else super().original_observation()
        )

    @model_validator(mode="after")
    def check_layout(self) -> Self:
        """允许零点但不接受多余尾字节、重叠块或错误索引说明。"""
        origin, source_count = self.original_observation()
        if (
            isinstance(origin, RasterSource)
            and source_count != origin.raster.point_count()
        ):
            raise ValueError("标量资产原始总点数不一致")
        row_blob = next((b for b in self.blobs if b.role == "profile-rows"), None)
        if isinstance(origin, ProfileSource):
            if (
                source_count != origin.profiles.point_count
                or row_blob is None
                or row_blob.content_length != origin.profiles.row_bytes()
                or row_blob.sha256 != origin.row_table_sha256
            ):
                raise ValueError("轮廓原始总数、行表布局或摘要不一致")
        elif row_blob is not None:
            raise ValueError("非轮廓观测不能携带轮廓行表")
        unique_ids([f.name for f in self.fields], "fields")
        if "positions" not in {f.name for f in self.fields}:
            raise ValueError("资产必须有 positions")
        cursor = 0
        for field in self.fields:
            width = FIELD_WIDTHS[field.dtype]
            aligned = (cursor + width - 1) // width * width
            if (
                field.count != self.point_count
                or field.offset_bytes != aligned
                or field.byte_length != field.count * field.components * width
            ):
                raise ValueError("资产字段布局不一致")
            cursor = aligned + field.byte_length
        blobs = {b.role: b for b in self.blobs}
        if (
            cursor != self.content_length
            or "original" in blobs
            or "data" not in blobs
            or blobs["data"].content_length != cursor
        ):
            raise ValueError("资产数据长度不一致")
        if (self.indices is None) != ("indices" not in blobs):
            raise ValueError("资产索引说明与块不一致")
        if self.indices is not None and (
            self.indices.count != self.point_count
            or blobs["indices"].content_length
            != self.point_count * FIELD_WIDTHS[self.indices.dtype]
        ):
            raise ValueError("资产索引长度不一致")
        if (self.lineage is None) != ("lineage" not in blobs):
            raise ValueError("生成来源说明与数据块不一致")
        if self.vertex_kind == "generated":
            if self.lineage is None or self.indices is not None:
                raise ValueError("生成顶点必须保存来源而不是原始行号")
        elif self.lineage is not None:
            raise ValueError("源点资产不能携带生成来源")
        if self.lineage is not None and blobs[
            "lineage"
        ].content_length != self.lineage.byte_length(self.point_count):
            raise ValueError("生成来源数据长度不一致")
        if isinstance(self.lineage, AssetVoxelLineage) and (
            self.lineage.member_count < self.point_count
            or (self.point_count == 0) != (self.lineage.member_count == 0)
        ):
            raise ValueError("体素成员数必须覆盖每个非空体素")
        return self


class ProfileCloudAsset(CloudAssetBase):
    """NPZ 原件保留完整轮廓、空行和原标定；重读时重新严格解码。"""

    representation: Literal["profiles-original"]
    fields: Annotated[tuple[CloudField, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_original(self) -> Self:
        """只允许有完整原件来源的资产，不接受数组冒充文件。"""
        if (
            not isinstance(self.source, ProfileSource)
            or self.source.input_format != "npz"
            or len(self.blobs) != 1
            or self.blobs[0].role != "original"
            or self.vertex_kind != "source"
            or self.topology is not None
            or self.normal_info is not None
            or self.boundary is not None
            or self.source_metadata is not None
            or self.source_field_names
            or not self.provenance.source_retained
        ):
            raise ValueError("轮廓原件必须保留完整 NPZ 与标定")
        if (self.blobs[0].content_length, self.blobs[0].sha256) != (
            self.source.content_length,
            self.source.content_sha256,
        ):
            raise ValueError("轮廓原件与输入摘要不一致")
        return self


PointCloudAsset = Annotated[
    OriginalCloudAsset | ArrayCloudAsset | RasterCloudAsset | ProfileCloudAsset,
    Field(discriminator="representation"),
]
