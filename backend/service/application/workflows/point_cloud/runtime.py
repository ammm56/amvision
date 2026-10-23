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


class CloudView:
    """一次借用中的有界字段访问；逻辑子集不伪装成连续原数组。"""

    def __init__(
        self,
        *,
        reference: CloudReference,
        arrays: Mapping[str, np.ndarray],
        selectors: tuple[np.ndarray, ...],
        origin_selectors: tuple[np.ndarray, ...],
        policy: PointCloudIoPolicy,
    ) -> None:
        """selectors 由叶到根排列；引用与父数组已由 Runtime 验证。"""
        self.reference = reference
        self._arrays = arrays
        self._selectors = selectors
        self._origin_selectors = origin_selectors
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
        values = {name: value[selected] for name, value in self._arrays.items()}
        for value in values.values():
            value.setflags(write=False)
        return MappingProxyType(values)

    def source_indices(self, start: int, stop: int) -> np.ndarray:
        """取得稳定源行号，显示证据不得把其当新的测量数据。"""
        if not self._active:
            raise RuntimeError("点云借用已结束")
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
            if id(owner) in self._owners:
                raise InvalidRequestError("同一原始 owner 已登记，不允许改写来源")
            self._validate_arrays(owner, point_count, fields, cancel)
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
            )
            self._publish(
                reference,
                _CloudRecord(
                    canonical_cloud_json(reference.model_dump(mode="json")),
                    owner,
                    file_options=file_options,
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

    def register_asset(self, *, owner, document, indices, cancel) -> CloudReference:
        """已验证资产恢复新的运行身份，历史行号与数组所有权仍归当前 Scope。"""
        from backend.contracts.workflows.point_cloud_assets import ArrayCloudAsset

        with self._lock:
            self._require_open()
            cloud = document.content.point_cloud
            fields = tuple(
                CloudField.model_validate(
                    f.model_dump(include=set(CloudField.model_fields))
                )
                for f in cloud.fields
            )
            self._validate_arrays(owner, cloud.point_count, fields, cancel)
            if id(owner) in self._owners:
                raise InvalidRequestError("同一资产 owner 已登记")
            if indices is not None and not self.storage_scope.owns(indices):
                raise InvalidRequestError("点云资产索引未归属当前运行")
            origin = (
                "mixed" if "sample_origin" in {f.name for f in fields} else "measured"
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
            )
            if (indices is not None) != (
                isinstance(cloud, ArrayCloudAsset) and cloud.indices is not None
            ):
                raise InvalidRequestError("资产索引与内容说明不一致")
            self._publish(
                reference,
                _CloudRecord(
                    canonical_cloud_json(reference.model_dump(mode="json")),
                    owner,
                    indices=indices,
                    source_point_count=(
                        cloud.indices.source_point_count
                        if isinstance(cloud, ArrayCloudAsset)
                        and cloud.indices is not None
                        else cloud.point_count
                    ),
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
                    if len(block) and (
                        int(block[0]) <= previous
                        or int(block[-1]) >= parent.point_count
                        or np.any(block[1:] <= block[:-1])
                    ):
                        raise InvalidRequestError("点云子集索引必须在源范围内严格递增")
                    if len(block):
                        previous = int(block[-1])
                count = len(values)
            reference = self._derived_reference(
                parent,
                method,
                point_count=count,
                fields=parent.fields,
                spatial=parent.spatial,
                source_metadata=None,
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
                ancestor = record
                while ancestor is not None:
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
                    policy=self.policy,
                )
                yield view
        finally:
            if view is not None:
                view._active = False
                view._arrays = {}
                view._selectors = ()
                view._origin_selectors = ()
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

    def _derived_reference(self, parent, method, **changes):
        """父身份固定且不形成环，内容变化使用新的 cloud_id。"""
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
