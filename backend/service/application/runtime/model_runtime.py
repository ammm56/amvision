"""模型运行时稳定边界定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.runtime.yolox_predictor import (
    OpenVINOYoloXRuntimeSession,
    OnnxRuntimeYoloXRuntimeSession,
    PyTorchYoloXRuntimeSession,
    TensorRTYoloXRuntimeSession,
    YoloXPredictionExecutionResult,
    YoloXPredictionRequest,
)
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class ModelRuntimeSession(Protocol):
    """定义单个模型会话需要满足的最小协议。"""

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """执行一次预测。

        参数：
        - request：预测请求。

        返回：
        - YoloXPredictionExecutionResult：预测执行结果。
        """

        ...


class ModelRuntime(Protocol):
    """定义运行时加载器需要满足的最小协议。"""

    def load_session(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> ModelRuntimeSession:
        """按运行时快照加载模型会话。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：已经固化的运行时快照。
        - pinned_output_buffer_enabled：TensorRT pinned output host buffer 开关覆盖值。
        - pinned_output_buffer_max_bytes：TensorRT pinned output host buffer 大小覆盖值。

        返回：
        - ModelRuntimeSession：已完成模型加载的运行时会话。
        """

        ...


class DefaultYoloXModelRuntime:
    """基于当前 YOLOX runtime target 解析结果加载具体模型会话。"""

    def load_session(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> ModelRuntimeSession:
        """按 runtime backend 选择当前已接通的具体模型会话实现。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：已经固化的运行时快照。
        - pinned_output_buffer_enabled：TensorRT pinned output host buffer 开关覆盖值。
        - pinned_output_buffer_max_bytes：TensorRT pinned output host buffer 大小覆盖值。

        返回：
        - ModelRuntimeSession：已完成模型加载的运行时会话。
        """

        if runtime_target.runtime_backend == "pytorch":
            return PyTorchYoloXRuntimeSession.load(
                dataset_storage=dataset_storage,
                runtime_target=runtime_target,
            )
        if runtime_target.runtime_backend == "onnxruntime":
            return OnnxRuntimeYoloXRuntimeSession.load(
                dataset_storage=dataset_storage,
                runtime_target=runtime_target,
            )
        if runtime_target.runtime_backend == "openvino":
            return OpenVINOYoloXRuntimeSession.load(
                dataset_storage=dataset_storage,
                runtime_target=runtime_target,
            )
        if runtime_target.runtime_backend == "tensorrt":
            return TensorRTYoloXRuntimeSession.load(
                dataset_storage=dataset_storage,
                runtime_target=runtime_target,
                pinned_output_buffer_enabled=pinned_output_buffer_enabled,
                pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
            )
        raise ValueError(f"unsupported runtime backend: {runtime_target.runtime_backend}")