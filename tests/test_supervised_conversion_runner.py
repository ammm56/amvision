"""受监督 Conversion attempt 与 staging 发布测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import pickle
from types import SimpleNamespace

import pytest

from backend.service.application.backends import (
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
    DetectionConversionPlanStep,
)
from backend.service.application.errors import (
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.device_leases import (
    CudaDeviceResource,
    DeviceLeaseMode,
    DeviceLeaseProvider,
    DeviceLeaseProviderConfig,
    DeviceLeaseUnavailableError,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.workers.conversion.supervised_conversion_runner import (
    SupervisedConversionRunner,
)
from backend.workers.shared.process_tree_supervisor import ProcessTreeResult


class _StaticCudaResolver:
    """不依赖测试机 CUDA 硬件的稳定资源解析器。"""

    resource = CudaDeviceResource(
        cuda_index=0,
        device_name="cuda:0",
        resource_key="GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    def list_visible_devices(self, *, torch_module: object | None = None):
        return (self.resource,)

    def resolve(self, device_name: str, *, torch_module: object | None = None):
        assert device_name == "cuda:0"
        return self.resource


def test_supervised_conversion_runner_publishes_validated_staging_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证子进程只写 staging，成功门禁后才发布最终不可变 builds。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    runner = SupervisedConversionRunner(
        runner_kind="yolox",
        dataset_storage=storage,
        workspace_dir=tmp_path / "worker",
        timeout_seconds=30.0,
        helper_timeout_seconds=12.0,
    )
    request = _build_request()
    captured: dict[str, object] = {}

    def fake_run(
        self: object,
        command: list[str],
        **kwargs: object,
    ) -> ProcessTreeResult:
        """模拟 attempt 子进程完成 ONNX 数值校验并写出 staging 文件。"""

        request_path = Path(command[command.index("--request-path") + 1])
        result_path = Path(command[command.index("--result-path") + 1])
        with request_path.open("rb") as stream:
            staged_request = pickle.load(stream)  # noqa: S301
        staged_uri = f"{staged_request.output_object_prefix}/artifacts/builds/model.onnx"
        storage.write_bytes(staged_uri, b"valid-onnx")
        result = ConversionBackendRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=(
                ConversionBackendOutput(
                    target_format="onnx",
                    object_uri=staged_uri,
                    file_type="onnx-model",
                    runtime_backend="onnxruntime",
                    runtime_precision="fp32",
                    metadata={
                        "object_uri": staged_uri,
                        "validation_summary": {
                            "allclose": True,
                            "finite": True,
                            "strict_numeric_validation": True,
                        },
                    },
                ),
            ),
            metadata={
                "validation_summary": {
                    "allclose": True,
                    "finite": True,
                    "strict_numeric_validation": True,
                }
            },
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        with result_path.open("wb") as stream:
            pickle.dump({"ok": True, "result": result}, stream)
        captured.update(kwargs)
        captured["env"] = kwargs["env"]
        return ProcessTreeResult(
            command=tuple(command),
            returncode=0,
            stdout="done",
            stderr="",
            duration_seconds=0.1,
        )

    monkeypatch.setattr(
        "backend.workers.conversion.supervised_conversion_runner.ProcessTreeSupervisor.run",
        fake_run,
    )

    result = runner.run_conversion(request)

    final_uri = "projects/project-1/conversions/task-1/artifacts/builds/model.onnx"
    assert result.outputs[0].object_uri == final_uri
    assert result.outputs[0].metadata["object_uri"] == final_uri
    assert storage.resolve(final_uri).read_bytes() == b"valid-onnx"
    assert result.metadata["conversion_attempt_id"].startswith("conversion-attempt-")
    assert result.metadata["attempt_timeout_seconds"] == 30.0
    publication_object_key = result.metadata["publication_record_object_key"]
    assert isinstance(publication_object_key, str)
    publication_record = storage.read_json(publication_object_key)
    assert publication_record["state"] == "published_pending_registration"
    assert publication_record["conversion_task_id"] == request.conversion_task_id
    process_env = captured["env"]
    assert isinstance(process_env, dict)
    assert process_env["AMVISION_WORKER_CONVERSION__HELPER_TIMEOUT_SECONDS"] == "12.0"


def test_supervised_conversion_runner_never_publishes_timed_out_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 timeout 时不创建最终 builds，staging 与日志仍可供回收和诊断。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    runner = SupervisedConversionRunner(
        runner_kind="yolox",
        dataset_storage=storage,
        workspace_dir=tmp_path / "worker",
        timeout_seconds=0.1,
    )

    def fake_run(self: object, command: list[str], **kwargs: object) -> ProcessTreeResult:
        raise OperationTimeoutError(
            "conversion 子进程树执行超时",
            details={"timeout_seconds": 0.1},
        )

    monkeypatch.setattr(
        "backend.workers.conversion.supervised_conversion_runner.ProcessTreeSupervisor.run",
        fake_run,
    )

    with pytest.raises(OperationTimeoutError):
        runner.run_conversion(_build_request())

    assert not storage.resolve(
        "projects/project-1/conversions/task-1/artifacts/builds"
    ).exists()


@pytest.mark.parametrize(
    ("target_formats", "source_device"),
    [
        (("tensorrt-engine",), None),
        (("onnx",), "cuda:0"),
    ],
)
def test_cuda_conversion_acquires_exclusive_gpu_before_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_formats: tuple[str, ...],
    source_device: str | None,
) -> None:
    """TensorRT 或 CUDA 来源 attempt 启动前必须先取得 exclusive GPU lease。"""

    lock_root = tmp_path / "leases"
    resolver = _StaticCudaResolver()
    deployment_provider = DeviceLeaseProvider(root_dir=lock_root, resolver=resolver)
    conversion_provider = DeviceLeaseProvider(root_dir=lock_root, resolver=resolver)
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    runner = SupervisedConversionRunner(
        runner_kind="yolox",
        dataset_storage=storage,
        workspace_dir=tmp_path / "worker",
        timeout_seconds=30.0,
        device_lease_config=DeviceLeaseProviderConfig(
            root_dir=str(lock_root),
            exclusive_acquire_timeout_seconds=0.0,
            conversion_cuda_device="cuda:0",
        ),
        device_lease_provider=conversion_provider,
    )
    request = replace(
        _build_request(),
        target_formats=target_formats,
        source_runtime_target=SimpleNamespace(
            model_version_id="model-version-1",
            device_name=source_device or "cpu",
        ),
    )
    process_started = False

    def fail_if_started(*args: object, **kwargs: object) -> object:
        nonlocal process_started
        process_started = True
        raise AssertionError("GPU busy 时不得启动 conversion attempt")

    monkeypatch.setattr(
        "backend.workers.conversion.supervised_conversion_runner.ProcessTreeSupervisor.run",
        fail_if_started,
    )
    with deployment_provider.acquire_resource(
        resolver.resource,
        requested_device="cuda:0",
        mode=DeviceLeaseMode.SHARED,
        purpose="deployment",
        owner_id="deployment-1",
        timeout_seconds=0.0,
    ):
        with pytest.raises(DeviceLeaseUnavailableError):
            runner.run_conversion(request)
    assert process_started is False


def test_supervised_conversion_runner_preserves_child_timeout_state(
    tmp_path: Path,
) -> None:
    """验证 helper timeout 穿过 attempt 进程边界后仍是正式 timeout。"""

    result_path = tmp_path / "result.pkl"
    with result_path.open("wb") as stream:
        pickle.dump(
            {
                "ok": False,
                "error": {
                    "error_type": "OperationTimeoutError",
                    "error_message": "helper 超时",
                    "details": {"timeout_seconds": 1.0},
                },
                "traceback": "traceback",
            },
            stream,
        )

    with pytest.raises(OperationTimeoutError, match="helper 超时"):
        SupervisedConversionRunner._read_attempt_payload(
            result_path=result_path,
            process_returncode=1,
            stdout_tail="stdout",
            stderr_tail="stderr",
        )


def test_supervised_conversion_runner_requires_runtime_smoke_for_runtime_artifact() -> None:
    """验证 OpenVINO/TensorRT 产物没有真实 runtime smoke 时不能发布。"""

    output = ConversionBackendOutput(
        target_format="openvino-ir",
        object_uri="attempt/staging/artifacts/builds/model.xml",
        file_type="openvino-ir",
        runtime_backend="openvino",
        runtime_precision="fp32",
        metadata={
            "validation_summary": {
                "allclose": True,
                "finite": True,
                "strict_numeric_validation": True,
            },
        },
    )

    with pytest.raises(ServiceConfigurationError, match="smoke"):
        SupervisedConversionRunner._validate_output_gate(output)


def test_supervised_conversion_runner_rejects_non_strict_numeric_drift() -> None:
    """验证非 strict 任务也必须提供 allclose 或模型专用 accepted 门禁。"""

    output = ConversionBackendOutput(
        target_format="onnx",
        object_uri="attempt/staging/artifacts/builds/model.onnx",
        file_type="onnx-model",
        runtime_backend="onnxruntime",
        runtime_precision="fp32",
        metadata={
            "validation_summary": {
                "allclose": False,
                "finite": True,
                "strict_numeric_validation": False,
            },
        },
    )

    with pytest.raises(ServiceConfigurationError, match="数值一致性"):
        SupervisedConversionRunner._validate_output_gate(output)


def _build_request() -> ConversionBackendRunRequest:
    """构建不依赖真实模型加载的最小 conversion 请求。"""

    return ConversionBackendRunRequest(
        conversion_task_id="task-1",
        source_runtime_target=SimpleNamespace(model_version_id="model-version-1"),
        target_formats=("onnx",),
        plan_steps=(
            DetectionConversionPlanStep(
                kind="export-onnx",
                source_format="pytorch",
                target_format="onnx",
                required_file_type="checkpoint",
                produced_file_type="onnx-model",
            ),
        ),
        output_object_prefix="projects/project-1/conversions/task-1",
        model_type="yolox",
        task_type="detection",
    )
