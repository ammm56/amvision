"""现有 ResourceScope 内的点云引用解析；不创建数据面或跨运行缓存。"""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import Callable, Iterator, Mapping
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.point_cloud import (
    CloudField,
    CloudFileOptions,
    CloudSpatial,
    PcdSourceMetadata,
)
from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    CloudSource,
    CloudProvenance,
    CloudParent,
    CloudDerivedSource,
    CloudMethod,
    CloudLocalSource,
    CloudAssetSource,
    BoundaryCloudMethod,
    BoundarySelectionMethod,
    ResampleCloudMethod,
)
from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.service.application.workflows.point_cloud.lineage import (
    lineage_chunk,
    validate_lineage,
)
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.nodes.core_nodes.support.file_payloads import require_file_ref_payload
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from backend.service.application.workflows.point_cloud.mapped_arrays import (
    MappedCloudArrays,
)
from backend.service.application.workflows.point_cloud.policy import PointCloudIoPolicy


@dataclass(frozen=True)
class _CloudRecord:
    """可信引用快照及实际数组依赖；只存在于当前 Scope。"""

    reference: bytes
    owner: OwnedCloudArrays | MappedCloudArrays | None
    parent: _CloudRecord | None = None
    indices: OwnedCloudArrays | None = None
    file_options: CloudFileOptions | None = None
    source_point_count: int | None = None
    lineage: OwnedCloudArrays | None = None
    raster_spec: bytes | None = None
    profile_source: bytes | None = None
    profile_rows: OwnedCloudArrays | None = None


class CloudView:
    """一次借用中的有界字段访问；逻辑子集不伪装成连续原数组。"""

    def __init__(
        self,
        *,
        reference: CloudReference,
        arrays: Mapping[str, np.ndarray],
        selectors: tuple[np.ndarray, ...],
        origin_selectors: tuple[np.ndarray, ...],
        lineage: Mapping[str, np.ndarray] | None,
        policy: PointCloudIoPolicy,
    ) -> None:
        """selectors 由叶到根排列；引用与父数组已由 Runtime 验证。"""
        self.reference = reference
        self._arrays = arrays
        self._selectors = selectors
        self._origin_selectors = origin_selectors
        self._lineage = lineage
        self._policy = policy
        self._active = True

    def chunk(self, start: int, stop: int) -> Mapping[str, np.ndarray]:
        """返回所需逻辑区间；索引物化严格受显式工作块容量约束。"""
        if not self._active:
            raise RuntimeError("点云借用已结束")
        if (
            type(start) is not int
            or type(stop) is not int
            or not 0 <= start <= stop <= self.reference.point_count
        ):
            raise InvalidRequestError("点云访问区间不合法")
        row_bytes = sum(
            value.dtype.itemsize * value.shape[1] for value in self._arrays.values()
        )
        # 二级索引同时存在旧、新索引；不得将整个子集隐式 gather 为整云副本。
        if (
            stop - start > self._policy.chunk_rows
            or (stop - start) * (row_bytes + 16) > self._policy.max_working_bytes
        ):
            raise InvalidRequestError("点云访问块超过显式工作预算")
        if not self._selectors:
            return MappingProxyType(
                {name: value[start:stop] for name, value in self._arrays.items()}
            )
        selected = self._selectors[0][start:stop, 0]
        for selector in self._selectors[1:]:
            selected = selector[selected, 0]
        # 全保留过滤或连续子集不必 gather 复制；仍检查实际索引，不能假设有序视图连续。
        if len(selected) and (
            int(selected[-1]) - int(selected[0]) == len(selected) - 1
            and np.all(selected[1:] == selected[:-1] + 1)
        ):
            first, last = int(selected[0]), int(selected[-1]) + 1
            values = {name: value[first:last] for name, value in self._arrays.items()}
        else:
            values = {name: value[selected] for name, value in self._arrays.items()}
        for value in values.values():
            value.setflags(write=False)
        return MappingProxyType(values)

    def source_indices(self, start: int, stop: int) -> np.ndarray:
        """取得稳定源行号，显示证据不得把其当新的测量数据。"""
        if not self._active:
            raise RuntimeError("点云借用已结束")
        if self.reference.vertex_kind != "source":
            raise InvalidRequestError("生成顶点没有唯一原始行号，应读取来源关系")
        if (
            type(start) is not int
            or type(stop) is not int
            or not 0 <= start <= stop <= self.reference.point_count
        ):
            raise InvalidRequestError("点云索引区间不合法")
        if (
            stop - start > self._policy.chunk_rows
            or (stop - start) * 16 > self._policy.max_working_bytes
        ):
            raise InvalidRequestError("点云索引块超过显式工作预算")
        if self._origin_selectors:
            result = self._origin_selectors[0][start:stop, 0]
            for selector in self._origin_selectors[1:]:
                result = selector[result, 0]
        else:
            dtype = "uint32" if self.reference.point_count <= 2**32 else "uint64"
            result = np.arange(start, stop, dtype=dtype)
        result.setflags(write=False)
        return result

    def gather(
        self, logical: np.ndarray
    ) -> tuple[Mapping[str, np.ndarray], np.ndarray]:
        """有界随机读复用当前父链；返回属性与真实身份，不扩展借用生命周期。"""
        if not self._active:
            raise RuntimeError("点云借用已结束")
        rows = np.asarray(logical)
        row_bytes = sum(
            value.dtype.itemsize * value.shape[1] for value in self._arrays.values()
        )
        if (
            rows.ndim != 1
            or rows.dtype.kind not in "iu"
            or len(rows) > self._policy.chunk_rows
            or len(rows) * (row_bytes + 32) > self._policy.max_working_bytes
            or np.any(rows < 0)
            or np.any(rows >= self.reference.point_count)
        ):
            raise InvalidRequestError("点云随机访问索引或预算无效")
        selected = rows
        for selector in self._selectors:
            selected = selector[selected, 0]
        values = {name: value[selected] for name, value in self._arrays.items()}
        identity = rows.copy()
        if self.reference.vertex_kind == "source":
            for selector in self._origin_selectors:
                identity = selector[identity, 0]
        for value in (*values.values(), identity):
            value.setflags(write=False)
        return MappingProxyType(values), identity

    def lineage_chunk(self, start: int, stop: int) -> Mapping[str, np.ndarray]:
        """生成顶点仅暴露有界来源副本，不授予父资源访问或释放权限。"""
        if not self._active:
            raise RuntimeError("点云借用已结束")
        if self._lineage is None or self.reference.vertex_kind != "generated":
            raise InvalidRequestError("源点视图没有生成顶点来源")
        if (
            type(start) is not int
            or type(stop) is not int
            or not 0 <= start <= stop <= self.reference.point_count
        ):
            raise InvalidRequestError("生成顶点来源区间无效")
        if (
            stop - start > self._policy.chunk_rows
            or (stop - start) * 96 > self._policy.max_working_bytes
        ):
            raise InvalidRequestError("生成顶点来源访问超过工作预算")
        if self._origin_selectors:
            selected = self._origin_selectors[0][start:stop, 0]
            for selector in self._origin_selectors[1:]:
                selected = selector[selected, 0]
        else:
            selected = np.arange(start, stop, dtype=np.uint64)
        return lineage_chunk(
            self._lineage,
            selected,
            max_working_bytes=self._policy.max_working_bytes,
            kind=self.reference.lineage_kind,
        )

    def profile_lineage_snapshot(self):
        """资产保存需要去重格表；完整快照限于半个工作预算，不绕过 Scope 借用。"""
        if not self._active or self._lineage is None:
            raise RuntimeError("点云借用已结束或缺少生成来源")
        if self.reference.lineage_kind != "grid-profile":
            raise InvalidRequestError("当前点云不是格剖面来源")
        n = self.reference.point_count
        if n * 256 > self._policy.max_working_bytes // 2:
            raise InvalidRequestError("格剖面保存快照超过工作预算")
        selected = np.arange(n, dtype=np.uint64)
        for selector in self._origin_selectors:
            selected = selector[selected, 0]
        return lineage_chunk(
            self._lineage,
            selected,
            max_working_bytes=self._policy.max_working_bytes // 2,
            kind="grid-profile",
        )

    def voxel_metadata(self, start: int, stop: int):
        """显示只读取有界格键和成员数，不为拾取复制完整成员列表。"""
        if not self._active or self._lineage is None:
            raise RuntimeError("点云借用已结束或缺少来源")
        if self.reference.lineage_kind != "voxel-aggregate" or not (
            type(start) is int
            and type(stop) is int
            and 0 <= start <= stop <= self.reference.point_count
            and stop - start <= self._policy.chunk_rows
            and (stop - start) * 64 <= self._policy.max_working_bytes
        ):
            raise InvalidRequestError("体素显示区间或来源无效")
        return self.voxel_metadata_rows(np.arange(start, stop, dtype=np.uint64))

    def voxel_metadata_rows(self, rows):
        """细节叶块随机访问复用同一来源映射，不复制完整成员 CSR。"""
        if not self._active or self._lineage is None:
            raise RuntimeError("点云借用已结束或缺少来源")
        selected = np.asarray(rows)
        if (
            self.reference.lineage_kind != "voxel-aggregate"
            or selected.ndim != 1
            or selected.dtype.kind not in "iu"
            or len(selected) > self._policy.chunk_rows
            or len(selected) * 64 > self._policy.max_working_bytes
            or np.any(selected < 0)
            or np.any(selected >= self.reference.point_count)
        ):
            raise InvalidRequestError("体素显示行号或预算无效")
        for selector in self._origin_selectors:
            selected = selector[selected, 0]
        offsets = self._lineage["member_offsets"][:, 0]
        keys = self._lineage["voxel_keys"][selected]
        counts = offsets[selected + 1] - offsets[selected]
        keys.setflags(write=False)
        counts.setflags(write=False)
        return keys, counts


class CloudRuntime:
    """每个 run 一个注册表，父云与索引在同一作用域逆序释放。"""

    def __init__(self, *, run_id: str, policy: PointCloudIoPolicy) -> None:
        """所有生产容量来自显式策略，不填默认值。"""
        from pydantic import TypeAdapter
        from backend.contracts.workflows.metrology import Identifier

        self.run_id = TypeAdapter(Identifier).validate_python(run_id)
        self.policy = policy
        self.budget = CloudArrayBudget(policy.max_live_array_bytes)
        self.storage_scope = ResourceScope(kind="point-cloud-storage")
        self._lock = RLock()
        self._records: dict[str, _CloudRecord] = {}
        self._owners: dict[int, str] = {}
        self._borrows = 0
        self._closed = False
        self._close_error = None

    def register_source(
        self,
        *,
        owner: OwnedCloudArrays | MappedCloudArrays,
        point_count: int,
        fields: tuple[CloudField, ...],
        spatial: CloudSpatial,
        source: CloudSource,
        source_metadata: PcdSourceMetadata | None,
        cancel: Callable[[], None],
        file_options: CloudFileOptions | None = None,
        profile_rows: OwnedCloudArrays | None = None,
    ) -> CloudReference:
        """入口完成全量校验后发布；owner 必须已由 storage_scope 持有。"""
        with self._lock:
            self._require_open()
            if isinstance(source, CloudDerivedSource) or point_count <= 0:
                raise InvalidRequestError("原始点云必须非空且有原始来源")
            if source.kind == "file":
                require_file_ref_payload(source.file)
                if (
                    file_options is None
                    or file_options.spatial != spatial
                    or tuple(field.to_field() for field in file_options.field_mapping)
                    != fields
                ):
                    raise InvalidRequestError("文件来源缺少一致的完整读取参数")
            elif file_options is not None:
                raise InvalidRequestError("同机数组不能携带文件读取参数")
            if (
                source.kind in ("calibrated-raster", "calibrated-profiles")
                and source.file is not None
            ):
                require_file_ref_payload(source.file)
            if id(owner) in self._owners:
                raise InvalidRequestError("同一原始 owner 已登记，不允许改写来源")
            self._validate_arrays(owner, point_count, fields, cancel)
            self._validate_profile_observation(
                source, profile_rows, owner, point_count, None, "source", cancel
            )
            reference = CloudReference(
                format_id="amvision.point-cloud-ref.v1",
                state="ready",
                reason=None,
                run_id=self.run_id,
                observation_id=uuid4().hex,
                cloud_id=uuid4().hex,
                revision=1,
                point_count=point_count,
                fields=fields,
                spatial=spatial,
                source=source,
                source_metadata=source_metadata,
                provenance=CloudProvenance(
                    method=None, parents=(), source_retained=False
                ),
                sample_origin="measured",
                vertex_kind="source",
                topology=None,
            )
            self._publish(
                reference,
                _CloudRecord(
                    canonical_cloud_json(reference.model_dump(mode="json")),
                    owner,
                    file_options=file_options,
                    raster_spec=canonical_cloud_json(
                        source.raster.model_dump(mode="json")
                    )
                    if source.kind == "calibrated-raster"
                    else None,
                    profile_source=canonical_cloud_json(
                        source.model_dump(mode="json", exclude={"file"})
                    )
                    if source.kind == "calibrated-profiles"
                    else None,
                    profile_rows=profile_rows,
                ),
            )
            self._owners[id(owner)] = reference.cloud_id
            return reference

    def original_source(
        self, reference: CloudReference
    ) -> tuple[CloudReference, CloudFileOptions | None]:
        """沿实际依赖返回仍被本 run 持有的原件，不按文件名重新寻找数据。"""
        with self._lock:
            record = self._resolve(reference)
            while record.parent is not None:
                record = record.parent
            return CloudReference.model_validate_json(
                record.reference
            ), record.file_options

    def parent_reference(self, reference: CloudReference) -> CloudReference | None:
        """从真实依赖取父引用，用于冻结内容追溯，不信任外部 cloud_id。"""
        with self._lock:
            record = self._resolve(reference)
            return (
                CloudReference.model_validate_json(record.parent.reference)
                if record.parent
                else None
            )

    def raster_source(self, reference: CloudReference):
        """从可信父链返回标定快照；资产重读后不丢失原始像素身份。"""
        from backend.contracts.workflows.raster3d import CalibratedRaster

        with self._lock:
            record = self._resolve(reference)
            while record.parent is not None:
                record = record.parent
            return (
                CalibratedRaster.model_validate_json(record.raster_spec)
                if record.raster_spec
                else None
            )

    def source_point_count(self, reference: CloudReference) -> int:
        """返回最初输入总点数；资产恢复使用已冻结索引来源，不以子集点数代替。"""
        with self._lock:
            record = self._resolve(reference)
            while record.parent is not None:
                record = record.parent
            return (
                record.source_point_count
                if record.source_point_count is not None
                else CloudReference.model_validate_json(record.reference).point_count
            )

    def profile_source(self, reference: CloudReference):
        """返回当前可信父链的原始标定，不暴露外部资产读取权限。"""
        from backend.contracts.workflows.profile3d import ProfileSource

        with self._lock:
            record = self._resolve(reference)
            while record.parent is not None:
                record = record.parent
            return (
                ProfileSource.model_validate_json(record.profile_source)
                if record.profile_source
                else None
            )

    @contextmanager
    def borrow_profile_rows(self, reference: CloudReference):
        """原始行表随运行所有者借用；关闭 Run 时不得抢先回收。"""
        with self.producing():
            with self._lock:
                record = self._resolve(reference)
                while record.parent is not None:
                    record = record.parent
                if record.profile_rows is None:
                    raise InvalidRequestError("当前观测没有原始轮廓行表")
                owner = record.profile_rows
            with owner.borrow() as arrays:
                yield arrays

    def _validate_profile_observation(
        self, source, rows, owner, count, indices, vertex_kind, cancel
    ):
        """发布前统一验证来源、行表摘要及原记录身份，不信任调用方模型副本。"""
        from backend.service.application.workflows.point_cloud.profile_rows import (
            row_digest,
            validate_profile_rows,
            validate_profile_points,
        )

        if (source.kind == "calibrated-profiles") != (rows is not None):
            raise InvalidRequestError("轮廓来源与行表所有权不一致")
        if rows is None:
            return
        if not self.storage_scope.owns(rows):
            raise InvalidRequestError("轮廓行表不属于当前运行")
        with rows.borrow() as table, owner.borrow() as arrays, ExitStack() as stack:
            if set(table) != {name for name, _, _ in source.profiles.row_layout()}:
                raise InvalidRequestError("轮廓行表包含未声明字段")
            validate_profile_rows(
                table, source.profiles, policy=self.policy, cancel=cancel
            )
            if (
                row_digest(table, source.profiles, policy=self.policy, cancel=cancel)
                != source.row_table_sha256
            ):
                raise InvalidRequestError("轮廓原行表摘要不一致")
            if vertex_kind == "source":
                origin_indices = (
                    stack.enter_context(indices.borrow())["indices"]
                    if indices
                    else None
                )
                validate_profile_points(
                    arrays,
                    table,
                    source,
                    count=count,
                    indices=origin_indices,
                    policy=self.policy,
                    cancel=cancel,
                )

    def register_asset(
        self, *, owner, document, indices, cancel, lineage=None, profile_rows=None
    ) -> CloudReference:
        """已验证资产恢复新的运行身份，历史行号与数组所有权仍归当前 Scope。"""
        from backend.contracts.workflows.point_cloud_assets import (
            ArrayCloudAsset,
        )

        with self._lock:
            self._require_open()
            cloud = document.content.point_cloud
            origin_source, source_count = cloud.original_observation()
            fields = tuple(
                CloudField.model_validate(
                    f.model_dump(include=set(CloudField.model_fields))
                )
                for f in cloud.fields
            )
            self._validate_arrays(owner, cloud.point_count, fields, cancel)
            if cloud.vertex_kind == "generated":
                self._validate_generated_positions(owner, cancel)
            if id(owner) in self._owners:
                raise InvalidRequestError("同一资产 owner 已登记")
            if indices is not None and not self.storage_scope.owns(indices):
                raise InvalidRequestError("点云资产索引未归属当前运行")
            origin = (
                "estimated"
                if isinstance(cloud, ArrayCloudAsset)
                and cloud.lineage is not None
                and cloud.lineage.kind != "surface"
                else "interpolated"
                if cloud.vertex_kind == "generated"
                else "mixed"
                if "sample_origin" in {f.name for f in fields}
                else "measured"
            )
            if (lineage is not None) != (
                isinstance(cloud, ArrayCloudAsset) and cloud.lineage is not None
            ):
                raise InvalidRequestError("生成来源与资产说明不一致")
            if lineage is not None:
                if not self.storage_scope.owns(lineage):
                    raise InvalidRequestError("生成来源未归属当前运行")
                with lineage.borrow() as arrays:
                    validate_lineage(
                        arrays,
                        point_count=cloud.point_count,
                        source_point_count=cloud.lineage.source_point_count,
                        policy=self.policy,
                        cancel=cancel,
                        kind=cloud.lineage.kind,
                    )
            reference = CloudReference(
                format_id="amvision.point-cloud-ref.v1",
                state="ready",
                reason=None,
                run_id=self.run_id,
                observation_id=uuid4().hex,
                cloud_id=uuid4().hex,
                revision=1,
                point_count=cloud.point_count,
                fields=fields,
                spatial=cloud.spatial,
                source=CloudAssetSource(kind="asset", reference=document.reference),
                source_metadata=cloud.source_metadata,
                provenance=CloudProvenance(
                    method=None, parents=(), source_retained=True
                ),
                sample_origin=origin,
                vertex_kind=cloud.vertex_kind,
                topology=cloud.topology,
                lineage_kind=cloud.lineage.kind
                if isinstance(cloud, ArrayCloudAsset) and cloud.lineage
                else None,
                voxel_aggregation=cloud.lineage.aggregation
                if isinstance(cloud, ArrayCloudAsset)
                and cloud.lineage is not None
                and cloud.lineage.kind == "voxel-aggregate"
                else None,
                normal_info=cloud.normal_info,
                voxel_grid=cloud.lineage.grid
                if isinstance(cloud, ArrayCloudAsset)
                and cloud.lineage is not None
                and cloud.lineage.kind == "voxel-aggregate"
                else None,
            )
            self._validate_normals(owner, reference, cancel)
            if (indices is not None) != (
                isinstance(cloud, ArrayCloudAsset) and cloud.indices is not None
            ):
                raise InvalidRequestError("资产索引与内容说明不一致")
            self._validate_profile_observation(
                origin_source,
                profile_rows,
                owner,
                cloud.point_count,
                indices,
                cloud.vertex_kind,
                cancel,
            )
            self._publish(
                reference,
                _CloudRecord(
                    canonical_cloud_json(reference.model_dump(mode="json")),
                    owner,
                    indices=indices,
                    source_point_count=source_count,
                    lineage=lineage,
                    raster_spec=canonical_cloud_json(
                        origin_source.raster.model_dump(mode="json")
                    )
                    if origin_source.kind == "calibrated-raster"
                    else None,
                    profile_source=canonical_cloud_json(
                        origin_source.model_dump(mode="json")
                    )
                    if origin_source.kind == "calibrated-profiles"
                    else None,
                    profile_rows=profile_rows,
                ),
            )
            self._owners[id(owner)] = reference.cloud_id
            return reference

    @contextmanager
    def producing(self) -> Iterator[None]:
        """引用发布前的解码同样持有运行生命周期，不允许提前删除输入。"""
        with self._lock:
            self._require_open()
            self._borrows += 1
        try:
            yield
        finally:
            with self._lock:
                self._borrows -= 1

    def open_local(
        self,
        *,
        descriptor,
        expected_descriptor_sha256: str,
        acquire_view,
        cancel: Callable[[], None],
    ) -> CloudReference:
        """一个同机输入只获取一次 guard，全部下游节点借用同一 owner。"""
        with self._lock:
            self._require_open()
            owner = MappedCloudArrays()
            self.storage_scope.register(
                ("mapped", uuid4().hex), owner, lambda value: value.close()
            )
            result = owner.open(
                descriptor=descriptor,
                expected_descriptor_sha256=expected_descriptor_sha256,
                acquire_view=acquire_view,
                policy=self.policy,
                budget=self.budget,
                cancel=cancel,
            )
            fields = tuple(
                CloudField.model_validate(
                    field.model_dump(exclude={"count", "offset_bytes", "byte_length"})
                )
                for field in descriptor.fields
            )
            return self.register_source(
                owner=owner,
                point_count=descriptor.point_count,
                fields=fields,
                spatial=descriptor.spatial,
                source_metadata=descriptor.source_metadata,
                source=CloudLocalSource(
                    kind="local-array",
                    content_sha256=result.content_sha256,
                    descriptor_sha256=result.descriptor_sha256,
                    source_observation_id=descriptor.source_observation_id,
                ),
                cancel=cancel,
            )

    def register_derived(
        self,
        *,
        parent: CloudReference,
        method: CloudMethod,
        owner: OwnedCloudArrays,
        fields: tuple[CloudField, ...],
        spatial: CloudSpatial,
        cancel: Callable[[], None],
    ) -> CloudReference:
        """单位转换产生独立数组，仍保留父云以支持显式保存原件。"""
        with self._lock:
            parent_record = self._resolve(parent)
            self._validate_arrays(owner, parent.point_count, fields, cancel)
            reference = self._derived_reference(
                parent,
                method,
                point_count=parent.point_count,
                fields=fields,
                spatial=spatial,
                source_metadata=parent.source_metadata,
            )
            self._validate_normals(owner, reference, cancel)
            self._publish(
                reference,
                _CloudRecord(
                    canonical_cloud_json(reference.model_dump(mode="json")),
                    owner,
                    parent_record,
                ),
            )
            return reference

    def register_subset(
        self,
        *,
        parent: CloudReference,
        method: CloudMethod,
        indices: OwnedCloudArrays,
        cancel: Callable[[], None],
    ) -> CloudReference:
        """稳定序号子集只持有索引和父 owner，不复制所有点属性。"""
        return self._register_view(
            parent=parent,
            method=method,
            indices=indices,
            cancel=cancel,
            topology=None,
            ordered=False,
        )

    def register_ordered(
        self,
        *,
        parent: CloudReference,
        method: BoundaryCloudMethod | BoundarySelectionMethod,
        indices: OwnedCloudArrays,
        topology: BoundaryTopology,
        cancel: Callable[[], None],
    ) -> CloudReference:
        """边界有序源点保留全部属性，索引顺序由已验证的连接定义。"""
        if not isinstance(method, (BoundaryCloudMethod, BoundarySelectionMethod)) or (
            isinstance(method, BoundaryCloudMethod) and parent.vertex_kind != "source"
        ):
            raise InvalidRequestError("有序源点必须来自原始点视图及边界方法")
        return self._register_view(
            parent=parent,
            method=method,
            indices=indices,
            cancel=cancel,
            topology=topology,
            ordered=True,
        )

    def _register_view(self, *, parent, method, indices, cancel, topology, ordered):
        """两种视图共用所有权和范围校验；普通裁剪明确清除连接信息。"""
        with self._lock:
            parent_record = self._resolve(parent)
            if not self.storage_scope.owns(indices):
                raise InvalidRequestError("点云索引未归属当前运行")
            with indices.borrow() as arrays:
                if set(arrays) != {"indices"}:
                    raise InvalidRequestError("点云子集只能持有源行索引")
                values = arrays["indices"]
                expected_dtype = np.dtype(
                    "uint32" if parent.point_count <= 2**32 else "uint64"
                )
                if (
                    values.ndim != 2
                    or values.shape[1] != 1
                    or values.dtype != expected_dtype
                    or values.flags.writeable
                ):
                    raise InvalidRequestError("点云子集索引类型或形状不合法")
                previous = -1
                rows = min(self.policy.chunk_rows, self.policy.max_working_bytes)
                for start in range(0, len(values), rows):
                    cancel()
                    block = values[start : start + rows, 0]
                    if ordered and np.any(block >= parent.point_count):
                        raise InvalidRequestError("有序点云索引越界")
                    if (
                        not ordered
                        and len(block)
                        and (
                            int(block[0]) <= previous
                            or int(block[-1]) >= parent.point_count
                            or np.any(block[1:] <= block[:-1])
                        )
                    ):
                        raise InvalidRequestError("点云子集索引必须在源范围内严格递增")
                    if len(block):
                        previous = int(block[-1])
                count = len(values)
                if ordered and (topology is None or topology.point_count != count):
                    raise InvalidRequestError("有序点云连接与数量不一致")
            reference = self._derived_reference(
                parent,
                method,
                point_count=count,
                fields=parent.fields,
                spatial=parent.spatial,
                source_metadata=None,
                topology=topology,
            )
            self._publish(
                reference,
                _CloudRecord(
                    canonical_cloud_json(reference.model_dump(mode="json")),
                    None,
                    parent_record,
                    indices,
                ),
            )
            return reference

    def register_generated(
        self,
        *,
        parent: CloudReference,
        method: BoundaryCloudMethod | ResampleCloudMethod,
        owner: OwnedCloudArrays,
        lineage: OwnedCloudArrays,
        point_count: int,
        fields: tuple[CloudField, ...],
        topology: BoundaryTopology | None,
        cancel: Callable[[], None],
    ) -> CloudReference:
        """生成位置及原始行号来源共用 Scope，不把生成序号伪装成源行号。"""
        with self._lock:
            parent_record = self._resolve(parent)
            if parent.vertex_kind != "source" or not (
                isinstance(method, BoundaryCloudMethod)
                or isinstance(method, ResampleCloudMethod)
                and method.parameters.settings.kind == "voxel-centroid"
            ):
                raise InvalidRequestError("边界生成只能使用有原始行号的支持点")
            kind = (
                "voxel-aggregate"
                if isinstance(method, ResampleCloudMethod)
                else "grid-profile"
                if method.parameters.method.kind == "visible-envelope"
                else "surface"
            )
            if kind == "voxel-aggregate" and topology is not None:
                raise InvalidRequestError("体素质心不能伪造边界拓扑")
            if not self.storage_scope.owns(lineage) or lineage is owner:
                raise InvalidRequestError("生成来源必须独立归属当前运行")
            self._validate_arrays(owner, point_count, fields, cancel)
            with lineage.borrow() as arrays:
                validate_lineage(
                    arrays,
                    point_count=point_count,
                    source_point_count=self.source_point_count(parent),
                    policy=self.policy,
                    cancel=cancel,
                    kind=kind,
                )
            self._validate_generated_positions(owner, cancel)
            reference = self._derived_reference(
                parent,
                method,
                point_count=point_count,
                fields=fields,
                source_metadata=None,
                vertex_kind="generated",
                sample_origin="estimated" if kind != "surface" else "interpolated",
                topology=topology,
                lineage_kind=kind,
                voxel_aggregation=method if kind == "voxel-aggregate" else None,
                normal_info=None,
                voxel_grid=dict(
                    origin=method.parameters.settings.grid_origin,
                    axes=(np.eye(3) * method.parameters.settings.voxel_size).tolist(),
                )
                if kind == "voxel-aggregate"
                else None,
            )
            self._publish(
                reference,
                _CloudRecord(
                    canonical_cloud_json(reference.model_dump(mode="json")),
                    owner,
                    parent_record,
                    lineage=lineage,
                ),
            )
            return reference

    @contextmanager
    def borrow(self, reference: CloudReference) -> Iterator[CloudView]:
        """全量核对引用，不信任调用方修改过的字段、数量或来源。"""
        with self._lock:
            record = self._resolve(reference)
            self._borrows += 1
        view = None
        try:
            with ExitStack() as stack:
                selectors = []
                origin_selectors = []
                index_arrays = {}
                lineage = None
                ancestor = record
                while ancestor is not None:
                    if ancestor.lineage is not None:
                        lineage = stack.enter_context(ancestor.lineage.borrow())
                        break
                    if ancestor.indices is not None:
                        index = stack.enter_context(ancestor.indices.borrow())[
                            "indices"
                        ]
                        index_arrays[id(ancestor)] = index
                        origin_selectors.append(index)
                    ancestor = ancestor.parent
                current = record
                while current.owner is None:
                    selectors.append(index_arrays[id(current)])
                    current = current.parent
                arrays = stack.enter_context(current.owner.borrow())
                view = CloudView(
                    reference=CloudReference.model_validate_json(record.reference),
                    arrays=arrays,
                    selectors=tuple(selectors),
                    origin_selectors=tuple(origin_selectors),
                    lineage=lineage,
                    policy=self.policy,
                )
                yield view
        finally:
            if view is not None:
                view._active = False
                view._arrays = {}
                view._selectors = ()
                view._origin_selectors = ()
                view._lineage = None
            with self._lock:
                self._borrows -= 1

    def close(self) -> None:
        """先禁止新借用；活跃借用或 owner 关闭失败交给既有进程隔离。"""
        with self._lock:
            if self._closed:
                return
            if self._close_error is not None:
                raise RuntimeError("点云运行关闭失败，禁止复用") from self._close_error
            try:
                if self._borrows:
                    raise RuntimeError("点云运行仍有活跃借用")
                errors = self.storage_scope.close()
                if errors:
                    raise ServiceConfigurationError(
                        "点云存储未完整释放",
                        details={"errors": [error.to_dict() for error in errors]},
                    )
            except BaseException as error:
                self._close_error = error
                raise
            self._records.clear()
            self._owners.clear()
            self._closed = True

    def _require_open(self) -> None:
        """拒绝已关闭或清理失败的运行，不能恢复使用部分资源。"""
        if (
            self._closed
            or self._close_error is not None
            or self.storage_scope.closed
            or self.storage_scope.close_errors
        ):
            raise RuntimeError("点云运行资源不可用")

    def _resolve(self, reference: CloudReference) -> _CloudRecord:
        """完整引用快照是身份的一部分，单独猜中 cloud_id 不取得访问权。"""
        self._require_open()
        record = self._records.get(reference.cloud_id)
        if (
            reference.run_id != self.run_id
            or record is None
            or canonical_cloud_json(reference.model_dump(mode="json"))
            != record.reference
        ):
            raise InvalidRequestError("点云引用不属于当前运行或内容已改变")
        return record

    def _publish(self, reference: CloudReference, record: _CloudRecord) -> None:
        """成功后才登记可解析身份；返回对象变更不影响内部快照。"""
        self._records[reference.cloud_id] = record

    def _validate_arrays(self, owner, point_count, fields, cancel):
        """核验可信存储与逻辑字段，不做隐式 reshape、cast 或字段丢弃。"""
        if not self.storage_scope.owns(owner):
            raise InvalidRequestError("点云数组未归属当前运行")
        with owner.borrow() as arrays:
            if set(arrays) != {field.name for field in fields}:
                raise InvalidRequestError("点云存储字段与引用不一致")
            for field in fields:
                cancel()
                value = arrays[field.name]
                if (
                    value.shape != (point_count, field.components)
                    or value.dtype != np.dtype(field.dtype).newbyteorder("<")
                    or value.flags.writeable
                ):
                    raise InvalidRequestError(
                        "点云存储形状、精度或只读状态不一致",
                        details={"field": field.name},
                    )

    def _validate_generated_positions(self, owner, cancel):
        """生成点不是传感器缺测占位，发布前拒绝非有限坐标。"""
        rows = min(self.policy.chunk_rows, self.policy.max_working_bytes // 3)
        if rows < 1:
            raise InvalidRequestError("生成坐标校验预算不足")
        with owner.borrow() as arrays:
            values = arrays["positions"]
            for start in range(0, len(values), rows):
                cancel()
                if not np.isfinite(values[start : start + rows]).all():
                    raise InvalidRequestError("生成顶点坐标必须有限")

    def _validate_normals(self, owner, reference, cancel):
        """新计算和资产重读共用同一逐点状态校验；普通外部法向不伪造质量。"""
        from backend.service.application.workflows.point_cloud.normal_fields import (
            validate_normal_arrays,
        )

        if reference.normal_info is not None:
            width = sum(
                np.dtype(f.dtype).itemsize * f.components for f in reference.fields
            )
            rows = min(
                self.policy.chunk_rows,
                self.policy.max_working_bytes // (width * 2 + 128),
            )
            if rows < 1:
                raise InvalidRequestError("法向状态校验预算不足一行")
            with owner.borrow() as arrays:
                validate_normal_arrays(
                    arrays, reference.normal_info, chunk_rows=rows, cancel=cancel
                )

    def _derived_reference(self, parent, method, **changes):
        """父身份固定且不形成环，内容变化使用新的 cloud_id。"""
        from backend.service.application.workflows.point_cloud.normal_fields import (
            derived_normal_info,
        )

        if "normal_info" not in changes:
            changes["normal_info"] = derived_normal_info(parent, method)
        if parent.voxel_grid is not None and "voxel_grid" not in changes:
            origin = np.asarray(parent.voxel_grid.origin, dtype=np.float64)
            axes = np.asarray(parent.voxel_grid.axes, dtype=np.float64)
            if method.method_id == "transform-cloud":
                matrix = np.asarray(
                    method.parameters.transform.matrix, dtype=np.float64
                )
                origin = matrix[:3, :3] @ origin + matrix[:3, 3]
                axes = axes @ matrix[:3, :3].T
            elif method.method_id == "normalize-units":
                scale = {"m": 1000.0, "mm": 1.0, "um": 0.001}[
                    parent.spatial.length_unit
                ]
                origin, axes = origin * scale, axes * scale
            changes["voxel_grid"] = dict(origin=origin.tolist(), axes=axes.tolist())
        parents = (CloudParent(cloud_id=parent.cloud_id, revision=parent.revision),)
        return CloudReference.model_validate(
            {
                **parent.model_dump(mode="python"),
                **changes,
                "cloud_id": uuid4().hex,
                "revision": 1,
                "source": CloudDerivedSource(kind="derived", parents=parents),
                "provenance": CloudProvenance(
                    method=method, parents=parents, source_retained=False
                ),
            }
        )


def get_cloud_runtime(
    scope: ResourceScope, *, run_id: str, policy: PointCloudIoPolicy
) -> CloudRuntime:
    """复用现有 Scope；点云借用先于外部 lease/临时文件清理结束。"""
    runtime = scope.get_or_create(
        "point-cloud-runtime",
        lambda: CloudRuntime(run_id=run_id, policy=policy),
        lambda value: value.close(),
        before_external_cleanup=True,
    )
    if runtime.run_id != run_id or runtime.policy != policy:
        raise InvalidRequestError("同一作用域不能切换点云运行身份或预算策略")
    return runtime
