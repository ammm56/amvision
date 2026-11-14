"""关系资产的同根派生链；保存数据和来源，不保存历史运行访问身份。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.contracts.workflows.cloud_normal_info import CloudNormalInfo
from backend.contracts.workflows.cloud_voxel import CloudVoxelGrid
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import (
    CloudField,
    CloudSpatial,
    FIELD_WIDTHS,
    FieldDtype,
    JsonCount,
    PcdSourceMetadata,
)
from backend.contracts.workflows.point_cloud_runtime import (
    CloudMethod,
    ResampleCloudMethod,
)
from backend.contracts.workflows.relation3d_evidence import RelationEvidenceItem
from backend.contracts.workflows.deviation3d_evidence import DeviationEvidenceItem


class StoredCloudState(Contract):
    """派生记录的语义字段；恢复时与现有 Runtime 登记结果逐字段核对。"""

    point_count: JsonCount
    fields: tuple[CloudField, ...]
    spatial: CloudSpatial
    source_metadata: PcdSourceMetadata | None
    sample_origin: Literal[
        "measured", "interpolated", "extrapolated", "mixed", "estimated"
    ]
    vertex_kind: Literal["source", "generated"]
    topology: BoundaryTopology | None
    lineage_kind: Literal["surface", "grid-profile", "voxel-aggregate"] | None
    voxel_aggregation: ResampleCloudMethod | None
    voxel_grid: CloudVoxelGrid | None
    normal_info: CloudNormalInfo | None


class StoredCloudArray(Contract):
    """已有只读数组的连续 LE 布局，不新增外部解析器或可执行载荷。"""

    group: Literal["owner", "indices", "lineage"]
    name: Identifier
    dtype: FieldDtype
    rows: JsonCount
    columns: Annotated[int, Field(strict=True, ge=1, le=64)]

    def byte_length(self):
        """准确计费，包括零长度数组。"""
        return self.rows * self.columns * FIELD_WIDTHS[self.dtype]


class StoredCloudStep(Contract):
    """父节点先于子节点；索引和生成点仍通过原登记接口恢复。"""

    parent: JsonCount
    kind: Literal["subset", "ordered", "materialized", "generated"]
    method: CloudMethod
    state: StoredCloudState
    arrays: Annotated[tuple[StoredCloudArray, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def check_arrays(self) -> Self:
        """拒绝重复数组与不符合存储类型的数据组。"""
        keys = [(a.group, a.name) for a in self.arrays]
        if len(set(keys)) != len(keys):
            raise ValueError("关系支持数组重复")
        groups = {a.group for a in self.arrays}
        expected = {
            "subset": {"indices"},
            "ordered": {"indices"},
            "materialized": {"owner"},
            "generated": {"owner", "lineage"},
        }[self.kind]
        if groups != expected:
            raise ValueError("关系派生类型与数组组不一致")
        if self.kind in {"subset", "ordered"}:
            a = self.arrays[0]
            if (
                len(self.arrays) != 1
                or a.name != "indices"
                or a.columns != 1
                or a.dtype not in {"uint32", "uint64"}
                or a.rows != self.state.point_count
            ):
                raise ValueError("关系支持索引布局无效")
        else:
            fields = {f.name: f for f in self.state.fields}
            data = {a.name: a for a in self.arrays if a.group == "owner"}
            if fields.keys() != data.keys() or any(
                (data[k].rows, data[k].columns, data[k].dtype)
                != (self.state.point_count, f.components, f.dtype)
                for k, f in fields.items()
            ):
                raise ValueError("关系支持字段缺失或精度不一致")
        return self


class RelationAssetItem(Contract):
    """每项 A/B 指向完整派生支持；空引用只表达真正不可用的支持。"""

    evidence: Annotated[
        RelationEvidenceItem | DeviationEvidenceItem, Field(discriminator="kind")
    ]
    members: tuple[JsonCount | None, JsonCount | None]

    @model_validator(mode="after")
    def check_members(self) -> Self:
        """不能用空引用丢掉失败模型仍然拥有的实际支持。"""
        if any(
            (member is None) != (side.point_count is None)
            for member, side in zip(self.members, self.evidence.support)
        ):
            raise ValueError("关系成员与完整支持状态不一致")
        return self


class RelationAsset(Contract):
    """共同原云为成员 0；一次资产提交绑定全部分支和结果。"""

    primary: JsonCount
    steps: Annotated[tuple[StoredCloudStep, ...], Field(max_length=8192)]
    items: Annotated[
        tuple[RelationAssetItem, ...], Field(min_length=1, max_length=8192)
    ]

    @model_validator(mode="after")
    def check_graph(self) -> Self:
        """有序无环、无孤立成员，质量的旧观测必须一致但不作为运行权限。"""
        count = len(self.steps)
        if self.primary > count or any(
            step.parent >= index for index, step in enumerate(self.steps, 1)
        ):
            raise ValueError("关系资产派生链越界或形成环")
        seen = {self.primary}
        ids = set()
        observations = set()
        for item in self.items:
            if item.evidence.item_id in ids:
                raise ValueError("关系资产量值 ID 重复")
            ids.add(item.evidence.item_id)
            observations.add(item.evidence.quality.metrics.observation_id)
            for member in item.members:
                if member is not None:
                    if member > count:
                        raise ValueError("关系支持成员越界")
                    seen.add(member)
        if len(observations) != 1:
            raise ValueError("关系资产混入不同观测")
        for index in range(count, 0, -1):
            if index in seen:
                seen.add(self.steps[index - 1].parent)
        if seen != set(range(count + 1)):
            raise ValueError("关系资产含未使用的派生成员")
        return self

    def byte_length(self):
        """全派生链的实际字节；原云沿现有 data 块另计。"""
        return sum(array.byte_length() for step in self.steps for array in step.arrays)
