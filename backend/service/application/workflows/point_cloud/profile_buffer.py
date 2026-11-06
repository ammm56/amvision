"""轮廓块布局适配现有 LocalBuffer guard；不创建 Broker 或另一套运行所有权。"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping

import numpy as np

from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.contracts.workflows.profile3d import ProfileBufferDescriptor
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)


@dataclass(frozen=True)
class BorrowedProfiles:
    """只读临时借用，退出清空全部字段；不向调用方转移释放权限。"""

    descriptor: ProfileBufferDescriptor
    descriptor_sha256: str
    content_sha256: str
    arrays: Mapping[str, np.ndarray]


def profile_descriptor_sha256(descriptor: ProfileBufferDescriptor) -> str:
    """标定、行数、字段布局和有效标记均参与入口固定摘要。"""
    return sha256(canonical_cloud_json(descriptor.model_dump(mode="json"))).hexdigest()


@contextmanager
def borrow_profile_buffer(
    *, descriptor, expected_descriptor_sha256, acquire_view, policy, budget, cancel
):
    """映射前准入，在读 guard 内保留原始行表，不把变长轮廓套进 HW 网格。"""
    cancel()
    digest = profile_descriptor_sha256(descriptor)
    if digest != expected_descriptor_sha256:
        raise InvalidRequestError("轮廓布局与固定摘要不一致")
    if budget.limit != policy.max_live_array_bytes:
        raise ValueError("轮廓预算与运行策略不一致")
    if descriptor.content_length > policy.max_decoded_bytes:
        raise InvalidRequestError("轮廓载荷超过解码预算")
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
                    raise InvalidRequestError("轮廓输入必须为受保护的只读连续字节")
                if view.nbytes != descriptor.content_length:
                    raise InvalidRequestError("轮廓输入长度与声明不一致")
                content = sha256()
                for start in range(0, view.nbytes, policy.chunk_bytes):
                    cancel()
                    with view[start : start + policy.chunk_bytes] as chunk:
                        content.update(chunk)
                offset = 0
                for name, dtype_name, shape in descriptor.profiles.input_layout(
                    has_validity=descriptor.has_validity
                ):
                    cancel()
                    dtype = np.dtype(dtype_name).newbyteorder("<")
                    count = shape[0] * (shape[1] if len(shape) == 2 else 1)
                    arrays[name] = np.frombuffer(
                        view, dtype=dtype, count=count, offset=offset
                    ).reshape(shape)
                    offset += count * dtype.itemsize
                cancel()
                yield BorrowedProfiles(
                    descriptor, digest, content.hexdigest(), MappingProxyType(arrays)
                )
            except BaseException as error:
                release_exception_frames(error)
                raise
            finally:
                arrays.clear()
        finally:
            release_budget = False
            guard.__exit__(None, None, None)
            release_budget = True
    finally:
        if release_budget:
            reservation.close()
