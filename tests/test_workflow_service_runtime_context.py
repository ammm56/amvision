"""Workflow service node 运行时上下文测试。"""

from __future__ import annotations

import sys

from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)


def test_injected_published_inference_gateway_avoids_loading_service_builders() -> None:
    """验证已注入 gateway 的模型热链不会加载完整 service builders。"""

    module_name = "backend.service.application.workflows.service_runtime.builders"
    existing_module = sys.modules.pop(module_name, None)
    gateway = object()
    try:
        context = WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
            published_inference_gateway=gateway,
        )

        assert context.build_published_inference_gateway() is gateway
        assert module_name not in sys.modules
    finally:
        if existing_module is not None:
            sys.modules[module_name] = existing_module
