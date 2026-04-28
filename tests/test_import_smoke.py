"""backend 导入冒烟测试。"""

from __future__ import annotations

import importlib

import pytest


# 需要验证可导入性的 backend 模块列表。
BACKEND_MODULES: tuple[str, ...] = (
    "backend.contracts.datasets.exports.coco_detection_export",
    "backend.contracts.datasets.exports.dataset_formats",
    "backend.service.api.app",
    "backend.service.api.deps.auth",
    "backend.service.api.rest.router",
    "backend.service.api.ws.router",
    "backend.contracts.files.yolox_model_files",
    "backend.service.application.conversions.yolox_conversion_planner",
    "backend.service.application.datasets.dataset_export",
    "backend.service.application.deployments.yolox_deployment_binding",
    "backend.service.application.models.yolox_model_service",
    "backend.service.domain.datasets.dataset_version",
    "backend.service.domain.files.yolox_file_types",
    "backend.service.domain.files.model_file",
    "backend.service.domain.models.model_records",
    "backend.service.domain.models.yolox_model_spec",
    "backend.service.domain.tasks.yolox_task_specs",
    "backend.service.infrastructure.db.session",
    "backend.workers.conversion.yolox_conversion_runner",
    "backend.workers.inference.yolox_inference_runner",
    "backend.workers.shared.yolox_runtime_contracts",
    "backend.workers.training.yolox_trainer_runner",
)


@pytest.mark.parametrize("module_name", BACKEND_MODULES)
def test_backend_modules_can_be_imported(module_name: str) -> None:
    """验证 backend 骨架模块可以被成功导入。

    参数：
    - module_name：要导入的模块名。
    """

    imported_module = importlib.import_module(module_name)

    assert imported_module is not None