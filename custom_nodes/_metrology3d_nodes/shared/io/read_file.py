"""读取不可变 ObjectStore 文件，成功后才向当前执行作用域交接数组。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Callable
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.point_cloud import (
    MAX_POINT_CLOUD_INPUT_BYTES,
    CloudField,
    CloudFileOptions,
    CloudSpatial,
    PcdSourceMetadata,
)
from backend.contracts.workflows.point_cloud_runtime import (
    CloudFileSource,
    CloudReference,
)
from backend.service.application.errors import InvalidRequestError, WorkflowInputError
from backend.service.application.ports.object_store import ObjectStore
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.input_contracts import WorkflowInputValidator
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from backend.service.application.workflows.point_cloud.policy import PointCloudIoPolicy
from backend.service.application.workflows.point_cloud.runtime import CloudRuntime
from custom_nodes._metrology3d_nodes.shared.io.formats import inspect_cloud_file
from custom_nodes._metrology3d_nodes.shared.io.input_errors import parsing_input


@dataclass(frozen=True)
class ReadCloudResult:
    """已验证文件结果；仅内部传递，不作为公开 payload 或持久引用。"""

    point_count: int
    fields: tuple[CloudField, ...]
    spatial: CloudSpatial
    source_metadata: PcdSourceMetadata | None
    source_file: dict[str, object]
    options: CloudFileOptions
    arrays: OwnedCloudArrays
    non_finite_positions: int


def read_file_reference(
    *,
    runtime: CloudRuntime,
    object_store: ObjectStore,
    project_id: str,
    file: object,
    options: CloudFileOptions,
    cancel: Callable[[], None],
) -> CloudReference:
    """使用同一个文件解码入口，成功后发布当前 run 的不可变引用。"""
    with runtime.producing():
        result = read_cloud_file(
            object_store=object_store,
            project_id=project_id,
            file=file,
            options=options,
            policy=runtime.policy,
            budget=runtime.budget,
            scope=runtime.storage_scope,
            cancel=cancel,
        )
        return runtime.register_source(
            owner=result.arrays,
            point_count=result.point_count,
            fields=result.fields,
            spatial=result.spatial,
            source_metadata=result.source_metadata,
            source=CloudFileSource(
                kind="file", file=result.source_file, source_observation_id=None
            ),
            file_options=result.options,
            cancel=cancel,
        )


def read_cloud_file(
    *,
    object_store: ObjectStore,
    project_id: str,
    file: object,
    options: CloudFileOptions,
    policy: PointCloudIoPolicy,
    budget: CloudArrayBudget,
    scope: ResourceScope,
    cancel: Callable[[], None],
) -> ReadCloudResult:
    """有界读取并保持源字段精度；所有分配共用当前 run 的预算。"""
    if scope.closed:
        raise RuntimeError("运行资源作用域已关闭")
    if budget.limit != policy.max_live_array_bytes:
        raise ValueError("点云预算与本次执行策略不一致")
    cancel()
    payload = WorkflowInputValidator(object_store=object_store).validate_file_reference(
        payload=file,
        project_id=project_id,
        max_file_bytes=MAX_POINT_CLOUD_INPUT_BYTES,
        binding_id="file",
    )
    if payload["content_length"] == 0:
        raise InvalidRequestError("点云输入文件不能为空")
    with object_store.open_read_snapshot(
        str(payload["object_key"]),
        expected_version=str(payload["immutable_version"]),
        expected_checksum=str(payload["checksum"]),
    ) as snapshot:
        if (
            not snapshot.metadata.is_immutable
            or snapshot.metadata.content_length != payload["content_length"]
        ):
            raise InvalidRequestError("点云输入不是声明的不可变快照")
        # 元数据校验不等于字节校验；同一个快照分块核对后回到文件开头。
        digest = sha256()
        length = 0
        while True:
            cancel()
            block = snapshot.stream.read(policy.chunk_bytes)
            if not block:
                break
            length += len(block)
            if length > int(payload["content_length"]):
                raise InvalidRequestError("点云快照实际长度超过声明")
            digest.update(block)
        del block
        if (
            length != payload["content_length"]
            or digest.hexdigest() != payload["checksum"]
        ):
            raise InvalidRequestError("点云快照实际字节与摘要不一致")
        snapshot.stream.seek(0)
        with parsing_input(options.profile_id, "header"):
            inspected = inspect_cloud_file(snapshot.stream, options, policy, cancel)
        if inspected.count <= 0:
            raise InvalidRequestError("点云输入必须包含点")
        names = tuple(
            name for field in options.field_mapping for name in field.source_names
        )
        if set(names) != set(inspected.dtype.names or ()):
            raise WorkflowInputError(
                "点云字段映射必须完整覆盖源字段",
                code="workflow_input_point_cloud_field_mapping_invalid",
                details={
                    "stage": "field_mapping",
                    "profile_id": options.profile_id,
                    "unmapped_fields": sorted(
                        set(inspected.dtype.names or ()) - set(names)
                    ),
                    "unknown_fields": sorted(
                        set(names) - set(inspected.dtype.names or ())
                    ),
                },
            )
        fields = tuple(field.to_field() for field in options.field_mapping)
        for mapping in options.field_mapping:
            target = np.dtype(mapping.dtype)
            if any(
                inspected.dtype[name].newbyteorder("=") != target
                for name in mapping.source_names
            ):
                raise WorkflowInputError(
                    "点云字段类型与文件声明不一致",
                    code="workflow_input_point_cloud_field_type_mismatch",
                    details={
                        "stage": "field_mapping",
                        "profile_id": options.profile_id,
                        "field": mapping.target_name,
                        "expected_dtype": mapping.dtype,
                        "source_dtypes": {
                            name: inspected.dtype[name].name
                            for name in mapping.source_names
                        },
                    },
                )
        decoded_bytes = inspected.count * inspected.dtype.itemsize
        if decoded_bytes > policy.max_decoded_bytes:
            raise InvalidRequestError("点云解码数组超过显式预算")
        normalized_bytes = inspected.count * sum(
            np.dtype(field.dtype).itemsize * field.components for field in fields
        )
        # 临时块允许缩小，不改变数据；工作预算至少容纳一行文本和转换数组。
        column_count = len(names)
        row_work_bytes = max(inspected.dtype.itemsize * 2, column_count * 8 * 2) + 4
        available_work = policy.max_working_bytes - policy.chunk_bytes
        rows = min(policy.chunk_rows, inspected.count, available_work // row_work_bytes)
        if rows < 1:
            raise InvalidRequestError("点云工作预算不能容纳一个解码块")
        if rows != policy.chunk_rows:
            # 重新使用同一受控 header 入口构造有界正文读取器，不替换 parser。
            snapshot.stream.seek(0)
            effective_policy = PointCloudIoPolicy.model_validate(
                {**policy.model_dump(), "chunk_rows": rows}
            )
            with parsing_input(options.profile_id, "header"):
                inspected = inspect_cloud_file(
                    snapshot.stream, options, effective_policy, cancel
                )
        # 结构数组与规范属性在重排时同时存在，不能只给最终数组计费。
        reservation = budget.reserve(decoded_bytes + normalized_bytes)
        data = None
        value = None
        arrays: dict[str, np.ndarray] = {}
        owner = None
        try:
            with parsing_input(options.profile_id, "data"):
                data = inspected.read()
            if data.shape != (inspected.count,) or data.dtype != inspected.dtype:
                raise InvalidRequestError("解析结果不符合预检布局")
            invalid = 0
            for mapping in options.field_mapping:
                cancel()
                value = np.empty(
                    (inspected.count, mapping.components),
                    dtype=np.dtype(mapping.dtype).newbyteorder("<"),
                )
                arrays[mapping.target_name] = value
                for start in range(0, inspected.count, rows):
                    cancel()
                    stop = min(start + rows, inspected.count)
                    for column, name in enumerate(mapping.source_names):
                        value[start:stop, column] = data[name][start:stop]
                    if mapping.target_name == "validity" and np.any(
                        value[start:stop] > 1
                    ):
                        raise InvalidRequestError("validity 只能包含 0/1")
                    if mapping.target_name == "positions":
                        invalid += int(
                            np.count_nonzero(
                                ~np.isfinite(value[start:stop]).all(axis=1)
                            )
                        )
            value = None
            data = None
            reservation.shrink(normalized_bytes)
            cancel()
            owner = OwnedCloudArrays(arrays, reservation)
            arrays.clear()
            result = ReadCloudResult(
                inspected.count,
                fields,
                options.spatial,
                inspected.source_metadata,
                payload,
                options,
                owner,
                invalid,
            )
            scope.register(
                ("point-cloud-arrays", uuid4().hex), owner, lambda value: value.close()
            )
            return result
        except BaseException as error:
            data = None
            value = None
            arrays.clear()
            # traceback 可被任务错误记录长期持有；移除已退栈解码器中的大数组。
            release_exception_frames(error)
            if owner is not None:
                owner.close()
            else:
                reservation.close()
            raise
