"""标量网格复用 LocalBuffer reader guard；不创建 Broker 或转移租约。"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping

import numpy as np

from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.contracts.workflows.raster3d import RasterBufferDescriptor
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)


@dataclass(frozen=True)
class BorrowedRaster:
    """上下文退出清空属性；调用方不能延长 mmap 的实际读取权限。"""

    descriptor: RasterBufferDescriptor
    descriptor_sha256: str
    content_sha256: str
    arrays: Mapping[str, np.ndarray]


def raster_descriptor_sha256(descriptor: RasterBufferDescriptor) -> str:
    """标定、类型和掩码布局共同参与固定摘要。"""
    return sha256(canonical_cloud_json(descriptor.model_dump(mode="json"))).hexdigest()


@contextmanager
def borrow_raster_buffer(
    *, descriptor, expected_descriptor_sha256, acquire_view, policy, budget, cancel
):
    """已准入调用借用只读字节，原所有者在此借用结束后释放租约。"""
    cancel()
    digest = raster_descriptor_sha256(descriptor)
    if digest != expected_descriptor_sha256:
        raise InvalidRequestError("标量网格布局与固定摘要不一致")
    if budget.limit != policy.max_live_array_bytes:
        raise ValueError("标量网格预算与运行策略不一致")
    if descriptor.content_length > policy.max_decoded_bytes:
        raise InvalidRequestError("标量网格超过解码预算")
    reservation = budget.reserve(descriptor.content_length)
    arrays = {}
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
                    raise InvalidRequestError("网格输入必须为受保护的连续只读字节视图")
                if view.nbytes != descriptor.content_length:
                    raise InvalidRequestError("网格输入长度与声明不一致")
                digest_content = sha256()
                for start in range(0, view.nbytes, policy.chunk_bytes):
                    cancel()
                    with view[start : start + policy.chunk_bytes] as block:
                        digest_content.update(block)
                raster = descriptor.raster
                dtype = np.dtype(raster.dtype).newbyteorder("<")
                shape = (raster.height, raster.width)
                arrays["samples"] = np.frombuffer(
                    view, dtype=dtype, count=raster.point_count()
                ).reshape(shape)
                if descriptor.has_mask:
                    arrays["mask"] = np.frombuffer(
                        view, dtype="u1", offset=raster.point_count() * dtype.itemsize
                    ).reshape(shape)
                    rows = min(policy.chunk_rows, policy.max_working_bytes)
                    for start in range(0, raster.point_count(), rows):
                        cancel()
                        if np.any(arrays["mask"].reshape(-1)[start : start + rows] > 1):
                            raise InvalidRequestError("网格掩码只能包含 0/1")
                cancel()
                yield BorrowedRaster(
                    descriptor,
                    digest,
                    digest_content.hexdigest(),
                    MappingProxyType(arrays),
                )
            except BaseException as error:
                release_exception_frames(error)
                raise
            finally:
                arrays.clear()
        finally:
            # guard 关闭失败时不能宣称内存已回收，复用平台故障恢复语义。
            release_budget = False
            guard.__exit__(None, None, None)
            release_budget = True
    finally:
        if release_budget:
            reservation.close()
