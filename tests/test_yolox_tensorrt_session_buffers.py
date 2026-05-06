"""YOLOX TensorRT session 输出缓冲逻辑测试。"""

from __future__ import annotations

import ctypes
from types import SimpleNamespace

import numpy as np

from backend.service.application.runtime.yolox_predictor import TensorRTYoloXRuntimeSession
from backend.service.domain.files.yolox_file_types import YOLOX_TENSORRT_ENGINE_FILE
from tests.runtime_pool_test_support import build_test_runtime_target, create_test_dataset_storage


class _FakeCudaRt:
    """描述 pinned host buffer 测试使用的最小 cudart fake。

    属性：
    - host_buffers：当前仍被 session 持有的 host buffer。
    - freed_host_ptrs：已经释放的 host pointer 列表。
    - freed_device_ptrs：已经释放的 device pointer 列表。
    """

    def __init__(self) -> None:
        """初始化测试使用的 fake cudart。"""

        self._next_device_ptr = 4096
        self.host_buffers: dict[int, ctypes.Array[ctypes.c_char]] = {}
        self.device_buffers: dict[int, int] = {}
        self.freed_host_ptrs: list[int] = []
        self.freed_device_ptrs: list[int] = []

    def cudaSetDevice(self, device_index: int) -> tuple[int]:
        """模拟切换 CUDA device。"""

        _ = device_index
        return (0,)

    def cudaMalloc(self, byte_size: int) -> tuple[int, int]:
        """模拟分配 device memory。"""

        pointer = int(self._next_device_ptr)
        self._next_device_ptr += max(256, int(byte_size) + 1)
        self.device_buffers[pointer] = int(byte_size)
        return (0, pointer)

    def cudaFree(self, pointer: int) -> tuple[int]:
        """模拟释放 device memory。"""

        self.device_buffers.pop(int(pointer), None)
        self.freed_device_ptrs.append(int(pointer))
        return (0,)

    def cudaMallocHost(self, byte_size: int) -> tuple[int, int]:
        """模拟分配 pinned host memory。"""

        buffer = ctypes.create_string_buffer(max(1, int(byte_size)))
        pointer = int(ctypes.addressof(buffer))
        self.host_buffers[pointer] = buffer
        return (0, pointer)

    def cudaFreeHost(self, pointer: int) -> tuple[int]:
        """模拟释放 pinned host memory。"""

        self.host_buffers.pop(int(pointer), None)
        self.freed_host_ptrs.append(int(pointer))
        return (0,)


def test_tensorrt_session_reuses_pinned_output_host_buffer_and_releases_it_on_close(tmp_path) -> None:
    """验证 TensorRT session 会复用 pinned output host buffer，并在 close 时释放。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="tensorrt",
        device_name="cuda:0",
        runtime_precision="fp32",
        runtime_artifact_file_name="fake-model.engine",
        runtime_artifact_file_type=YOLOX_TENSORRT_ENGINE_FILE,
    )
    fake_cudart = _FakeCudaRt()
    session = TensorRTYoloXRuntimeSession(
        dataset_storage=dataset_storage,
        runtime_target=runtime_target,
        imports=SimpleNamespace(cv2=None, np=np, cudart=fake_cudart),
        tensorrt_module=SimpleNamespace(__version__="10.13.2.6"),
        logger=None,
        runtime=None,
        engine=None,
        context=None,
        device_name="cuda:0",
        input_name="images",
        output_name="predictions",
        input_dtype_name="float32",
        output_dtype_name="float32",
        stream=None,
        execute_start_event=None,
        execute_end_event=None,
    )
    input_array = np.zeros((1, 3, 64, 64), dtype=np.float32)

    output_array = session._ensure_io_buffers(
        input_array=input_array,
        resolved_output_shape=(1, 8400, 7),
    )
    first_host_ptr = int(session.output_host_ptr)

    assert first_host_ptr > 0
    assert output_array.dtype == np.float32
    assert tuple(int(dim) for dim in output_array.shape) == (1, 8400, 7)
    assert int(output_array.ctypes.data) == first_host_ptr

    reused_output_array = session._ensure_io_buffers(
        input_array=input_array,
        resolved_output_shape=(1, 8400, 7),
    )

    assert int(session.output_host_ptr) == first_host_ptr
    assert int(reused_output_array.ctypes.data) == first_host_ptr
    assert fake_cudart.freed_host_ptrs == []

    resized_output_array = session._ensure_io_buffers(
        input_array=input_array,
        resolved_output_shape=(1, 8400, 8),
    )
    second_host_ptr = int(session.output_host_ptr)

    assert first_host_ptr in fake_cudart.freed_host_ptrs
    assert session.output_host_capacity_bytes == int(resized_output_array.nbytes)
    assert tuple(int(dim) for dim in resized_output_array.shape) == (1, 8400, 8)
    assert int(resized_output_array.ctypes.data) == second_host_ptr

    session.close()

    assert session.output_host_ptr is None
    assert session.output_host_array is None
    assert second_host_ptr in fake_cudart.freed_host_ptrs


def test_tensorrt_session_falls_back_to_pageable_output_buffer_when_output_exceeds_limit(tmp_path) -> None:
    """验证输出超过 pinned 上限时会自动回退 pageable memory，并释放旧的 pinned buffer。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="tensorrt",
        device_name="cuda:0",
        runtime_precision="fp32",
        runtime_artifact_file_name="fake-model.engine",
        runtime_artifact_file_type=YOLOX_TENSORRT_ENGINE_FILE,
    )
    fake_cudart = _FakeCudaRt()
    session = TensorRTYoloXRuntimeSession(
        dataset_storage=dataset_storage,
        runtime_target=runtime_target,
        imports=SimpleNamespace(cv2=None, np=np, cudart=fake_cudart),
        tensorrt_module=SimpleNamespace(__version__="10.13.2.6"),
        logger=None,
        runtime=None,
        engine=None,
        context=None,
        device_name="cuda:0",
        input_name="images",
        output_name="predictions",
        input_dtype_name="float32",
        output_dtype_name="float32",
        stream=None,
        execute_start_event=None,
        execute_end_event=None,
        pinned_output_buffer_enabled=True,
        pinned_output_buffer_max_bytes=4096,
    )
    input_array = np.zeros((1, 3, 64, 64), dtype=np.float32)

    pinned_output_array = session._ensure_io_buffers(
        input_array=input_array,
        resolved_output_shape=(1, 100, 7),
    )
    pinned_host_ptr = int(session.output_host_ptr)

    assert pinned_host_ptr > 0
    assert session.output_host_memory_kind == "pinned"
    assert int(pinned_output_array.ctypes.data) == pinned_host_ptr

    session.pinned_output_buffer_max_bytes = 64
    pageable_output_array = session._ensure_io_buffers(
        input_array=input_array,
        resolved_output_shape=(1, 100, 7),
    )

    assert session.output_host_ptr is None
    assert session.output_host_capacity_bytes == 0
    assert session.output_host_memory_kind == "pageable"
    assert pinned_host_ptr in fake_cudart.freed_host_ptrs
    assert pinned_host_ptr not in fake_cudart.host_buffers
    assert tuple(int(dim) for dim in pageable_output_array.shape) == (1, 100, 7)