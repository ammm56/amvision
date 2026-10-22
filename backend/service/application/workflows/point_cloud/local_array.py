"""在既有 LocalBuffer guard 内校验并借用点云，不持久保存运行期视图。"""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Callable, Iterator, Mapping

import numpy as np

from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.contracts.workflows.point_cloud_runtime import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from backend.service.application.workflows.point_cloud.policy import PointCloudIoPolicy


@dataclass(frozen=True)
class BorrowedCloudBuffer:
    """仅在借用区间有效；数组不得逃逸到下次运行或 guard 之外。"""

    descriptor: CloudBufferDescriptor
    descriptor_sha256: str
    content_sha256: str
    non_finite_positions: int
    arrays: Mapping[str, np.ndarray]


def cloud_descriptor_sha256(descriptor: CloudBufferDescriptor) -> str:
    """固定描述按 UTF-8 规范 JSON 摘要，包含显式 null，不包含载荷。"""
    content = canonical_cloud_json(descriptor.model_dump(mode="json"))
    return sha256(content).hexdigest()


@contextmanager
def borrow_cloud_buffer(
    *,
    descriptor: CloudBufferDescriptor,
    expected_descriptor_sha256: str,
    acquire_view: Callable[[], AbstractContextManager[memoryview]],
    policy: PointCloudIoPolicy,
    budget: CloudArrayBudget,
    cancel: Callable[[], None],
) -> Iterator[BorrowedCloudBuffer]:
    """由调用者提供既有 reader guard；一次运行共享此借用，不为每节点重开。

    此入口不转移或释放 Broker lease；租约仍由既有运行所有者管理。
    调用方须先完成准入及 owner 交接，并在本上下文结束后才能释放租约。
    """
    cancel()
    digest = cloud_descriptor_sha256(descriptor)
    if digest != expected_descriptor_sha256:
        raise InvalidRequestError("点云布局与已固定的描述摘要不一致")
    if budget.limit != policy.max_live_array_bytes:
        raise ValueError("点云预算与本次执行策略不一致")
    if descriptor.content_length > policy.max_decoded_bytes:
        raise InvalidRequestError("点云数组超过显式预算")
    rows = min(policy.chunk_rows, policy.max_working_bytes // 4)
    if rows < 1:
        raise InvalidRequestError("点云工作预算不能容纳有效性扫描")
    reservation = budget.reserve(descriptor.content_length)
    arrays: dict[str, np.ndarray] = {}
    value = None
    release_budget = True
    try:
        guard = acquire_view()
        view = guard.__enter__()
        try:
            try:
                if (
                    not view.readonly
                    or view.ndim != 1
                    or view.format != "B"
                    or not view.c_contiguous
                ):
                    raise InvalidRequestError("点云输入必须为受保护的连续只读字节视图")
                if view.nbytes != descriptor.content_length:
                    raise InvalidRequestError("点云实际载荷长度与描述不一致")
                content = sha256()
                for start in range(0, view.nbytes, policy.chunk_bytes):
                    cancel()
                    with view[start : start + policy.chunk_bytes] as block:
                        content.update(block)
                end = 0
                invalid = 0
                for field in descriptor.fields:
                    cancel()
                    # 契约只允许 dtype 对齐填充，每次最多检查七个字节。
                    if any(
                        view[index] != 0 for index in range(end, field.offset_bytes)
                    ):
                        raise InvalidRequestError("点云对齐填充必须为零")
                    # frombuffer 保留 readonly memoryview；ndarray(buffer=...) 可绕回可写 mmap base。
                    value = np.frombuffer(
                        view,
                        dtype=np.dtype(field.dtype).newbyteorder("<"),
                        count=field.count * field.components,
                        offset=field.offset_bytes,
                    ).reshape(field.count, field.components)
                    arrays[field.name] = value
                    for start in range(0, field.count, rows):
                        cancel()
                        stop = min(start + rows, field.count)
                        if field.name == "positions":
                            invalid += int(
                                np.count_nonzero(
                                    ~np.isfinite(value[start:stop]).all(axis=1)
                                )
                            )
                        elif field.name == "validity" and np.any(value[start:stop] > 1):
                            raise InvalidRequestError("validity 只能包含 0/1")
                    end = field.offset_bytes + field.byte_length
                value = None
                yield BorrowedCloudBuffer(
                    descriptor,
                    digest,
                    content.hexdigest(),
                    invalid,
                    MappingProxyType(arrays),
                )
            finally:
                # 先移除 ndarray 的 mmap 别名，再退出既有 reader guard。
                value = None
                arrays.clear()
        finally:
            # guard 关闭失败不能假报容量已归还；上层必须走既有故障恢复。
            release_budget = False
            guard.__exit__(None, None, None)
            release_budget = True
    finally:
        if release_budget:
            reservation.close()
