"""TensorRT engine capability 元数据与部署 profile 校验测试。"""

from __future__ import annotations

import pytest

from backend.service.application.deployments.deployment_instance_service import (
    _validate_runtime_configuration,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    TensorRtRuntimeOptions,
)
from backend.service.domain.models.tensorrt_engine_capabilities import (
    TensorRtOptimizationProfile,
    TensorRtOptimizationProfileInput,
    build_single_input_tensorrt_engine_capabilities,
    build_tensorrt_engine_capabilities,
    parse_tensorrt_engine_capabilities,
)


def test_static_engine_capabilities_are_explicit_and_use_profile_zero() -> None:
    """验证静态 engine 仍明确登记固定 shape 和 profile 0。"""

    metadata = build_single_input_tensorrt_engine_capabilities(
        input_shape_mode="static",
        input_name="images",
        min_shape=(1, 3, 640, 640),
        opt_shape=(1, 3, 640, 640),
        max_shape=(1, 3, 640, 640),
    )

    assert metadata == {
        "input_shape_mode": "static",
        "optimization_profile_count": 1,
        "optimization_profiles": [
            {
                "index": 0,
                "inputs": [
                    {
                        "input_name": "images",
                        "min_shape": [1, 3, 640, 640],
                        "opt_shape": [1, 3, 640, 640],
                        "max_shape": [1, 3, 640, 640],
                    }
                ],
            }
        ],
    }
    capabilities = parse_tensorrt_engine_capabilities(metadata)
    assert capabilities is not None
    assert capabilities.input_shape_mode == "static"
    assert capabilities.optimization_profile_count == 1


def test_dynamic_engine_capabilities_support_multiple_profiles_and_inputs() -> None:
    """验证标准元数据可表达动态 engine 的多 profile、多输入范围。"""

    profiles = tuple(
        TensorRtOptimizationProfile(
            index=index,
            inputs=(
                TensorRtOptimizationProfileInput(
                    input_name="images",
                    min_shape=minimum,
                    opt_shape=optimum,
                    max_shape=maximum,
                ),
                TensorRtOptimizationProfileInput(
                    input_name="scale",
                    min_shape=(1, 2),
                    opt_shape=(1, 2),
                    max_shape=(1, 2),
                ),
            ),
        )
        for index, minimum, optimum, maximum in (
            (0, (1, 3, 320, 320), (1, 3, 640, 640), (4, 3, 640, 640)),
            (1, (1, 3, 640, 640), (2, 3, 960, 960), (8, 3, 1280, 1280)),
        )
    )
    metadata = build_tensorrt_engine_capabilities(
        input_shape_mode="dynamic",
        profiles=profiles,
    )

    capabilities = parse_tensorrt_engine_capabilities(metadata)
    assert capabilities is not None
    assert capabilities.input_shape_mode == "dynamic"
    assert capabilities.optimization_profile_count == 2
    assert capabilities.optimization_profiles[1].inputs[0].max_shape == (
        8,
        3,
        1280,
        1280,
    )


def test_capability_parser_rejects_inconsistent_profile_metadata() -> None:
    """验证部分字段、错误计数和非法 shape 范围不会被静默接受。"""

    with pytest.raises(ValueError, match="不完整"):
        parse_tensorrt_engine_capabilities({"input_shape_mode": "static"})

    with pytest.raises(ValueError, match="数量不一致"):
        parse_tensorrt_engine_capabilities(
            {
                "input_shape_mode": "dynamic",
                "optimization_profile_count": 2,
                "optimization_profiles": [
                    {
                        "index": 0,
                        "inputs": [
                            {
                                "input_name": "images",
                                "min_shape": [1, 3, 640, 640],
                                "opt_shape": [1, 3, 640, 640],
                                "max_shape": [1, 3, 640, 640],
                            }
                        ],
                    }
                ],
            }
        )


def test_deployment_profile_validation_uses_selected_model_build_metadata() -> None:
    """验证部署创建只接受具体 engine 已声明的 profile index。"""

    metadata = build_tensorrt_engine_capabilities(
        input_shape_mode="dynamic",
        profiles=tuple(
            TensorRtOptimizationProfile(
                index=index,
                inputs=(
                    TensorRtOptimizationProfileInput(
                        input_name="images",
                        min_shape=(1, 3, size, size),
                        opt_shape=(1, 3, size, size),
                        max_shape=(4, 3, size, size),
                    ),
                ),
            )
            for index, size in enumerate((640, 1280))
        ),
    )

    _validate_runtime_configuration(
        DeploymentRuntimeConfiguration(
            backend_options=TensorRtRuntimeOptions(optimization_profile_index=1)
        ),
        runtime_backend="tensorrt",
        device_name="cuda:0",
        model_build_metadata=metadata,
    )

    with pytest.raises(InvalidRequestError, match="有效范围"):
        _validate_runtime_configuration(
            DeploymentRuntimeConfiguration(
                backend_options=TensorRtRuntimeOptions(optimization_profile_index=2)
            ),
            runtime_backend="tensorrt",
            device_name="cuda:0",
            model_build_metadata=metadata,
        )


def test_static_or_unregistered_engine_only_accepts_profile_zero() -> None:
    """验证静态 engine 和未登记能力的 engine 都不能选择非零 profile。"""

    static_metadata = build_single_input_tensorrt_engine_capabilities(
        input_shape_mode="static",
        input_name="images",
        min_shape=(1, 3, 640, 640),
        opt_shape=(1, 3, 640, 640),
        max_shape=(1, 3, 640, 640),
    )
    for metadata in (static_metadata, {}):
        with pytest.raises(InvalidRequestError):
            _validate_runtime_configuration(
                DeploymentRuntimeConfiguration(
                    backend_options=TensorRtRuntimeOptions(optimization_profile_index=1)
                ),
                runtime_backend="tensorrt",
                device_name="cuda:0",
                model_build_metadata=metadata,
            )
