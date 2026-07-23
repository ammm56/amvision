"""Deployment runtime configuration 领域与 runtime adapter 测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.service.api.rest.v1.routes.detection_deployments.schemas import (
    DetectionDeploymentInstanceCreateRequestBody,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.runtime.deployment import runtime_capabilities
from backend.service.application.runtime.deployment import cpu_device_resource_manager
from backend.service.application.runtime.deployment.cpu_device_resource_manager import (
    CpuDeviceResourceManager,
)
from backend.service.application.runtime.support.openvino_execution import (
    compile_openvino_model,
    get_openvino_runtime_diagnostics,
)
from backend.service.application.runtime.support.tensorrt_execution import (
    activate_tensorrt_optimization_profile,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentExecutionPolicy,
    DeploymentLifecycleOptions,
    DeploymentRuntimeConfiguration,
    OpenVinoCpuRuntimeOptions,
    OpenVinoGpuRuntimeOptions,
    OpenVinoNpuRuntimeOptions,
    deserialize_deployment_runtime_configuration,
    serialize_deployment_runtime_configuration,
)


def test_runtime_configuration_round_trip_uses_only_current_schema() -> None:
    """验证当前配置结构可无损持久化。"""

    configuration = DeploymentRuntimeConfiguration(
        execution=DeploymentExecutionPolicy(instance_count=2),
        backend_options=OpenVinoCpuRuntimeOptions(
            inference_num_threads=4,
            num_streams=1,
        ),
    )

    payload = serialize_deployment_runtime_configuration(configuration)

    assert deserialize_deployment_runtime_configuration(payload) == configuration
    with pytest.raises(ValueError, match="execution"):
        deserialize_deployment_runtime_configuration({"instance_count": 2})
    with pytest.raises(ValidationError, match="instance_count"):
        DetectionDeploymentInstanceCreateRequestBody.model_validate(
            {
                "project_id": "project-1",
                "model_type": "yolox",
                "model_version_id": "model-version-1",
                "instance_count": 2,
            }
        )


@pytest.mark.parametrize(
    ("configuration", "message"),
    [
        (
            DeploymentRuntimeConfiguration(
                execution=DeploymentExecutionPolicy(instance_count=True),
                backend_options=OpenVinoCpuRuntimeOptions(),
            ),
            "execution.instance_count 必须是整数",
        ),
        (
            DeploymentRuntimeConfiguration(
                lifecycle=DeploymentLifecycleOptions(warmup_dummy_image_size=(0, 640)),
                backend_options=OpenVinoCpuRuntimeOptions(),
            ),
            r"warmup_dummy_image_size\[0\]",
        ),
        (
            DeploymentRuntimeConfiguration(
                lifecycle=DeploymentLifecycleOptions(
                    keep_warm_resume_delay_seconds=-0.1
                ),
                backend_options=OpenVinoCpuRuntimeOptions(),
            ),
            "keep_warm_resume_delay_seconds 必须大于或等于 0",
        ),
        (
            DeploymentRuntimeConfiguration(
                backend_options=OpenVinoCpuRuntimeOptions(num_streams=0),
            ),
            "backend_options.num_streams 不能小于 1",
        ),
    ],
)
def test_runtime_configuration_domain_validation_rejects_invalid_direct_inputs(
    configuration: DeploymentRuntimeConfiguration,
    message: str,
) -> None:
    """验证非 HTTP 入口也不能绕过运行时配置约束。"""

    with pytest.raises(ValueError, match=message):
        serialize_deployment_runtime_configuration(configuration)


def test_host_default_uses_physical_core_count_without_enforcing_cpu_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 OpenVINO CPU 默认线程数来自物理核心，超额预算只产生告警。"""

    monkeypatch.setattr(
        runtime_capabilities,
        "_read_cpu_hardware_summary",
        lambda: {
            "cpu_physical_core_count": 6,
            "cpu_logical_processor_count": 12,
        },
    )
    configuration = runtime_capabilities.build_host_default_runtime_configuration(
        runtime_backend="openvino",
        device_name="cpu",
    )

    assert isinstance(configuration.backend_options, OpenVinoCpuRuntimeOptions)
    assert configuration.backend_options.inference_num_threads == 6

    oversubscribed = DeploymentRuntimeConfiguration(
        execution=DeploymentExecutionPolicy(instance_count=2),
        backend_options=OpenVinoCpuRuntimeOptions(
            inference_num_threads=4,
            num_streams=1,
        ),
    )
    warnings = runtime_capabilities.evaluate_runtime_configuration_warnings(
        oversubscribed
    )

    assert len(warnings) == 1
    assert "8" in warnings[0]
    assert "6" in warnings[0]


def test_cpu_device_resource_manager_aggregates_running_deployments_without_rejecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证全局 CPU 预算只聚合和告警，不承担启动拒绝。"""

    monkeypatch.setattr(
        cpu_device_resource_manager,
        "read_cpu_hardware_summary",
        lambda: {
            "cpu_physical_core_count": 8,
            "cpu_logical_processor_count": 16,
        },
    )
    manager = CpuDeviceResourceManager()
    configuration = DeploymentRuntimeConfiguration(
        execution=DeploymentExecutionPolicy(instance_count=2),
        backend_options=OpenVinoCpuRuntimeOptions(
            inference_num_threads=3,
            num_streams=1,
        ),
    )

    manager.activate(
        owner_id="sync-supervisor",
        deployment_instance_id="deployment-1",
        runtime_mode="sync",
        runtime_configuration=configuration,
    )
    manager.activate(
        owner_id="async-supervisor",
        deployment_instance_id="deployment-2",
        runtime_mode="async",
        runtime_configuration=configuration,
    )

    snapshot = manager.snapshot()
    assert snapshot["active_deployment_count"] == 2
    assert snapshot["estimated_thread_demand"] == 12
    assert snapshot["oversubscribed"] is True
    assert len(manager.warnings()) == 1

    manager.deactivate_owner("async-supervisor")
    assert manager.snapshot()["estimated_thread_demand"] == 6
    assert manager.warnings() == ()


def test_openvino_compile_filters_unsupported_properties_and_records_effective_values() -> (
    None
):
    """验证统一 OpenVINO 编译入口记录 requested/effective 配置。"""

    compiled_model = _FakeCompiledModel(
        {
            "PERFORMANCE_HINT": "LATENCY",
            "NUM_STREAMS": 1,
        }
    )
    core = _FakeOpenVinoCore(compiled_model)
    openvino_module = _build_fake_openvino_module(core)
    configuration = DeploymentRuntimeConfiguration(
        backend_options=OpenVinoCpuRuntimeOptions(
            inference_num_threads=8,
            num_streams=1,
        )
    )

    session = compile_openvino_model(
        openvino_module=openvino_module,
        model_path="model.xml",
        device_name="CPU",
        base_properties={"CACHE_DIR": "cache"},
        runtime_configuration=configuration,
    )
    diagnostics = get_openvino_runtime_diagnostics(session)

    assert core.compile_properties["CACHE_DIR"] == "cache"
    assert core.compile_properties["PERFORMANCE_HINT"] == "LATENCY"
    assert isinstance(core.compile_properties["NUM_STREAMS"], _FakeStreamsNum)
    assert core.compile_properties["NUM_STREAMS"].value == 1
    assert diagnostics is not None
    assert diagnostics.requested["compile_properties"] == {
        "PERFORMANCE_HINT": "LATENCY",
        "INFERENCE_NUM_THREADS": 8,
        "NUM_STREAMS": 1,
    }
    assert diagnostics.effective["compile_properties"] == {
        "PERFORMANCE_HINT": "LATENCY",
        "NUM_STREAMS": 1,
    }
    assert any("INFERENCE_NUM_THREADS" in warning for warning in diagnostics.warnings)


def test_openvino_gpu_num_streams_uses_openvino_typed_value() -> None:
    """验证 GPU NUM_STREAMS 在编译边界转换为 OpenVINO 强类型值。"""

    compiled_model = _FakeCompiledModel(
        {
            "PERFORMANCE_HINT": "LATENCY",
            "NUM_STREAMS": 1,
        }
    )
    core = _FakeOpenVinoGpuCore(compiled_model)
    configuration = DeploymentRuntimeConfiguration(
        backend_options=OpenVinoGpuRuntimeOptions(num_streams=1)
    )

    session = compile_openvino_model(
        openvino_module=_build_fake_openvino_module(core),
        model_path="model.xml",
        device_name="GPU",
        base_properties={},
        runtime_configuration=configuration,
    )

    assert isinstance(core.compile_properties["NUM_STREAMS"], _FakeStreamsNum)
    assert core.compile_properties["NUM_STREAMS"].value == 1
    diagnostics = get_openvino_runtime_diagnostics(session)
    assert diagnostics is not None
    assert diagnostics.requested["compile_properties"]["NUM_STREAMS"] == 1
    assert diagnostics.effective["compile_properties"]["NUM_STREAMS"] == 1


def test_openvino_npu_capabilities_and_compile_properties_are_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证无 NPU 测试机也能覆盖 capability 和编译属性映射。"""

    compiled_properties = {
        "PERFORMANCE_HINT": "LATENCY",
        "PERFORMANCE_HINT_NUM_REQUESTS": 2,
        "INFERENCE_PRECISION_HINT": "f16",
        "NPU_TURBO": True,
        "NPU_TILES": 2,
        "NPU_COMPILATION_MODE_PARAMS": "optimization-level=1",
    }
    core = _FakeOpenVinoNpuCore(_FakeCompiledModel(compiled_properties))
    openvino_module = SimpleNamespace(Core=lambda: core)
    monkeypatch.setattr(runtime_capabilities.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        runtime_capabilities,
        "import_module",
        lambda _name: openvino_module,
    )

    capabilities = runtime_capabilities.inspect_deployment_runtime_capabilities(
        runtime_backend="openvino",
        device_name="npu",
    )

    assert capabilities["available"] is True
    assert capabilities["supported_backend_fields"] == [
        "performance_hint",
        "num_requests",
        "inference_precision",
        "turbo",
        "tiles",
        "compilation_mode_params",
    ]
    assert capabilities["read_only_properties"]["npu_max_tiles"] == 2
    assert (
        capabilities["default_runtime_configuration"]["backend_options"]["kind"]
        == "openvino-npu"
    )

    configuration = DeploymentRuntimeConfiguration(
        backend_options=OpenVinoNpuRuntimeOptions(
            performance_hint="latency",
            num_requests=2,
            inference_precision="f16",
            turbo=True,
            tiles=2,
            compilation_mode_params="optimization-level=1",
        )
    )
    session = compile_openvino_model(
        openvino_module=openvino_module,
        model_path="model.xml",
        device_name="NPU",
        base_properties={},
        runtime_configuration=configuration,
    )

    assert core.compile_properties == compiled_properties
    diagnostics = get_openvino_runtime_diagnostics(session)
    assert diagnostics is not None
    assert diagnostics.effective["compile_properties"] == compiled_properties
    assert diagnostics.warnings == ()


def test_tensorrt_profile_activation_validates_engine_range() -> None:
    """验证 TensorRT profile 使用 engine 声明的范围。"""

    context = _FakeTensorRtContext()
    engine = SimpleNamespace(num_optimization_profiles=2)

    activate_tensorrt_optimization_profile(
        engine=engine,
        context=context,
        stream=17,
        profile_index=1,
    )

    assert context.calls == [(1, 17)]
    with pytest.raises(ServiceConfigurationError, match="超出 engine 范围"):
        activate_tensorrt_optimization_profile(
            engine=engine,
            context=context,
            stream=17,
            profile_index=2,
        )


class _FakeCompiledModel:
    """提供 effective property 查询的 OpenVINO CompiledModel fake。"""

    def __init__(self, properties: dict[str, object]) -> None:
        self.properties = properties

    def get_property(self, name: str) -> object:
        return self.properties[name]


class _FakeStreamsNum:
    """模拟 OpenVINO properties.streams.Num 强类型值。"""

    def __init__(self, value: int) -> None:
        self.value = value


def _build_fake_openvino_module(core: object) -> SimpleNamespace:
    """构建带 streams.Num 类型入口的 OpenVINO module fake。"""

    return SimpleNamespace(
        Core=lambda: core,
        properties=SimpleNamespace(
            streams=SimpleNamespace(Num=_FakeStreamsNum),
        ),
    )


class _FakeOpenVinoCore:
    """提供 capability 查询和 compile_model 的 OpenVINO Core fake。"""

    def __init__(self, compiled_model: _FakeCompiledModel) -> None:
        self.compiled_model = compiled_model
        self.compile_properties: dict[object, object] = {}

    def get_property(self, device_name: str, name: str) -> list[str]:
        assert device_name == "CPU"
        assert name == "SUPPORTED_PROPERTIES"
        return ["PERFORMANCE_HINT", "NUM_STREAMS"]

    def compile_model(
        self,
        model_path: str,
        device_name: str,
        properties: dict[object, object],
    ) -> _FakeCompiledModel:
        assert model_path == "model.xml"
        assert device_name == "CPU"
        self.compile_properties = properties
        return self.compiled_model


class _FakeOpenVinoGpuCore(_FakeOpenVinoCore):
    """提供 GPU capability 查询和 compile_model 的 OpenVINO Core fake。"""

    def get_property(self, device_name: str, name: str) -> list[str]:
        assert device_name == "GPU"
        assert name == "SUPPORTED_PROPERTIES"
        return ["PERFORMANCE_HINT", "NUM_STREAMS"]

    def compile_model(
        self,
        model_path: str,
        device_name: str,
        properties: dict[object, object],
    ) -> _FakeCompiledModel:
        assert model_path == "model.xml"
        assert device_name == "GPU"
        self.compile_properties = properties
        return self.compiled_model


class _FakeOpenVinoNpuCore:
    """提供 NPU capability、只读属性和编译行为。"""

    available_devices = ["CPU", "NPU"]

    def __init__(self, compiled_model: _FakeCompiledModel) -> None:
        self.compiled_model = compiled_model
        self.compile_properties: dict[object, object] = {}

    def get_property(self, device_name: str, name: str) -> object:
        assert device_name == "NPU"
        if name == "SUPPORTED_PROPERTIES":
            return [
                "PERFORMANCE_HINT",
                "PERFORMANCE_HINT_NUM_REQUESTS",
                "INFERENCE_PRECISION_HINT",
                "NPU_TURBO",
                "NPU_TILES",
                "NPU_COMPILATION_MODE_PARAMS",
                "NPU_MAX_TILES",
            ]
        if name == "NPU_MAX_TILES":
            return 2
        raise RuntimeError(f"unsupported property: {name}")

    def compile_model(
        self,
        model_path: str,
        device_name: str,
        properties: dict[object, object],
    ) -> _FakeCompiledModel:
        assert model_path == "model.xml"
        assert device_name == "NPU"
        self.compile_properties = properties
        return self.compiled_model


class _FakeTensorRtContext:
    """记录 TensorRT optimization profile 激活调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def set_optimization_profile_async(self, profile_index: int, stream: int) -> bool:
        self.calls.append((profile_index, stream))
        return True
