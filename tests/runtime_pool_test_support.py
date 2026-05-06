"""YOLOX runtime pool 逻辑测试共享辅助模块。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionDetection,
    YoloXPredictionExecutionResult,
    YoloXPredictionRequest,
)
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo


def create_test_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建 runtime pool 逻辑测试使用的本地文件存储。

    参数：
    - tmp_path：pytest 提供的临时目录。

    返回：
    - LocalDatasetStorage：测试使用的本地文件存储。
    """

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))


def build_test_runtime_target(
    *,
    dataset_storage: LocalDatasetStorage,
    runtime_backend: str,
    device_name: str,
    runtime_precision: str,
    runtime_artifact_file_name: str,
    runtime_artifact_file_type: str,
) -> RuntimeTargetSnapshot:
    """构造 runtime pool 逻辑测试使用的最小 RuntimeTargetSnapshot。

    参数：
    - dataset_storage：测试使用的本地文件存储。
    - runtime_backend：目标 runtime backend。
    - device_name：目标 device 名称。
    - runtime_precision：目标 precision。
    - runtime_artifact_file_name：测试产物文件名。
    - runtime_artifact_file_type：测试产物文件类型。

    返回：
    - RuntimeTargetSnapshot：可直接喂给 runtime pool 的最小运行时快照。
    """

    storage_uri = f"projects/project-1/models/runtime-pool-builds/{runtime_artifact_file_name}"
    artifact_path = dataset_storage.resolve(storage_uri)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b"fake-runtime-artifact")
    return RuntimeTargetSnapshot(
        project_id="project-1",
        model_id="model-1",
        model_version_id="model-version-1",
        model_build_id="model-build-1",
        model_name="yolox-nano-runtime-pool",
        model_scale="nano",
        task_type="object-detection",
        source_kind="training-output",
        runtime_profile_id=None,
        runtime_backend=runtime_backend,
        device_name=device_name,
        runtime_precision=runtime_precision,
        input_size=(64, 64),
        labels=("bolt",),
        runtime_artifact_file_id="build-file-1",
        runtime_artifact_storage_uri=storage_uri,
        runtime_artifact_path=artifact_path,
        runtime_artifact_file_type=runtime_artifact_file_type,
    )


def build_test_execution_result(
    *,
    runtime_target: RuntimeTargetSnapshot,
    output_dtype: str = "float32",
) -> YoloXPredictionExecutionResult:
    """构造 fake runtime session 返回的预测结果。

    参数：
    - runtime_target：当前测试使用的运行时快照。
    - output_dtype：输出张量 dtype。

    返回：
    - YoloXPredictionExecutionResult：固定预测结果。
    """

    return YoloXPredictionExecutionResult(
        detections=(
            YoloXPredictionDetection(
                bbox_xyxy=(8.0, 8.0, 24.0, 24.0),
                score=0.95,
                class_id=0,
                class_name="bolt",
            ),
        ),
        latency_ms=1.5,
        image_width=64,
        image_height=64,
        preview_image_bytes=None,
        runtime_session_info=YoloXRuntimeSessionInfo(
            backend_name=runtime_target.runtime_backend,
            model_uri=runtime_target.runtime_artifact_storage_uri,
            device_name=runtime_target.device_name,
            input_spec=RuntimeTensorSpec(name="images", shape=(1, 3, 64, 64), dtype="float32"),
            output_spec=RuntimeTensorSpec(name="predictions", shape=(1, 1, 6), dtype=output_dtype),
            metadata={
                "runtime_execution_mode": (
                    f"{runtime_target.runtime_backend}:{runtime_target.runtime_precision}:{runtime_target.device_name}"
                ),
                "compiled_runtime_precision": runtime_target.runtime_precision,
            },
        ),
    )


class FakePredictionSession:
    """记录预测请求并返回固定结果的 fake runtime session。"""

    def __init__(self, *, execution_result: YoloXPredictionExecutionResult) -> None:
        """初始化 fake runtime session。

        参数：
        - execution_result：predict 固定返回的执行结果。
        """

        self.execution_result = execution_result
        self.requests: list[YoloXPredictionRequest] = []
        self.pinned_output_buffer_enabled: bool | None = None
        self.pinned_output_buffer_max_bytes: int | None = None

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """记录请求并返回固定执行结果。

        参数：
        - request：当前预测请求。

        返回：
        - YoloXPredictionExecutionResult：固定执行结果。
        """

        self.requests.append(request)
        return self.execution_result


class FailingPredictionSession:
    """在 predict 时抛错的 fake runtime session。"""

    def __init__(self, *, error_message: str) -> None:
        """初始化 predict 失败的 fake runtime session。

        参数：
        - error_message：predict 抛出的错误消息。
        """

        self.error_message = error_message
        self.pinned_output_buffer_enabled: bool | None = None
        self.pinned_output_buffer_max_bytes: int | None = None

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """抛出固定错误，验证 runtime pool 的失败处理路径。

        参数：
        - request：当前预测请求。

        返回：
        - 无。
        """

        del request
        raise RuntimeError(self.error_message)


def build_recording_session_loader(
    *,
    load_requests: list[tuple[LocalDatasetStorage, RuntimeTargetSnapshot]],
    session: FakePredictionSession,
) -> SimpleNamespace:
    """构造会记录 load 请求并返回固定 session 的 loader stub。

    参数：
    - load_requests：用于记录 load 入参的列表。
    - session：load 返回的 fake session。

    返回：
    - SimpleNamespace：带有 load 方法的 stub 对象。
    """

    def load(
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> FakePredictionSession:
        del pinned_output_buffer_enabled
        del pinned_output_buffer_max_bytes
        load_requests.append((dataset_storage, runtime_target))
        return session

    return SimpleNamespace(load=load)


def build_failing_session_loader(*, error_message: str) -> SimpleNamespace:
    """构造会返回 predict 失败 session 的 loader stub。

    参数：
    - error_message：predict 抛出的错误消息。

    返回：
    - SimpleNamespace：带有 load 方法的 stub 对象。
    """

    def load(
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> FailingPredictionSession:
        del dataset_storage
        del runtime_target
        del pinned_output_buffer_enabled
        del pinned_output_buffer_max_bytes
        return FailingPredictionSession(error_message=error_message)

    return SimpleNamespace(load=load)


def build_recording_model_runtime(
    *,
    load_requests: list[tuple[LocalDatasetStorage, RuntimeTargetSnapshot, bool | None, int | None]],
    session: FakePredictionSession,
) -> SimpleNamespace:
    """构造会记录 load_session 请求并返回固定 session 的 ModelRuntime stub。

    参数：
    - load_requests：用于记录 load_session 入参的列表。
    - session：load_session 返回的 fake session。

    返回：
    - SimpleNamespace：带有 load_session 方法的 stub 对象。
    """

    def load_session(
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> FakePredictionSession:
        session.pinned_output_buffer_enabled = pinned_output_buffer_enabled
        session.pinned_output_buffer_max_bytes = pinned_output_buffer_max_bytes
        load_requests.append(
            (
                dataset_storage,
                runtime_target,
                pinned_output_buffer_enabled,
                pinned_output_buffer_max_bytes,
            )
        )
        return session

    return SimpleNamespace(load_session=load_session)


def build_failing_model_runtime(*, error_message: str) -> SimpleNamespace:
    """构造会返回 predict 失败 session 的 ModelRuntime stub。

    参数：
    - error_message：predict 抛出的错误消息。

    返回：
    - SimpleNamespace：带有 load_session 方法的 stub 对象。
    """

    def load_session(
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> FailingPredictionSession:
        del dataset_storage
        del runtime_target
        del pinned_output_buffer_enabled
        del pinned_output_buffer_max_bytes
        return FailingPredictionSession(error_message=error_message)

    return SimpleNamespace(load_session=load_session)