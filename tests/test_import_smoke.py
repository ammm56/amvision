"""backend 导入冒烟测试。"""

from __future__ import annotations

import importlib

import pytest


# 需要验证可导入性的 backend 模块列表。
BACKEND_MODULES: tuple[str, ...] = (
    "backend.bootstrap.core",
    "backend.bootstrap.settings",
    "backend.contracts.datasets.exports.coco_detection_export",
    "backend.contracts.datasets.exports.dataset_formats",
    "backend.contracts.datasets.exports.voc_detection_export",
    "backend.contracts.nodes.node_pack_manifest",
    "backend.contracts.workflows.workflow_graph",
    "backend.maintenance.bootstrap",
    "backend.maintenance.settings",
    "backend.nodes.core_catalog",
    "backend.nodes.core_nodes",
    "backend.nodes.core_runtime_handlers",
    "backend.nodes.local_node_pack_loader",
    "backend.nodes.node_catalog_registry",
    "backend.nodes.node_pack_loader",
    "backend.nodes.runtime_support",
    "backend.queue.local_file_queue",
    "backend.service.api.app",
    "backend.service.api.deps.auth",
    "backend.service.api.deps.db",
    "backend.service.api.deps.nodes",
    "backend.service.api.deps.queue",
    "backend.service.api.error_handlers",
    "backend.service.api.rest.router",
    "backend.service.api.rest.v1.routes.dataset_exports",
    "backend.service.api.rest.v1.routes.workflows",
    "backend.service.api.rest.v1.routes.yolox_conversion_tasks",
    "backend.service.api.ws.router",
    "backend.service.application.errors",
    "backend.service.application.tasks.task_service",
    "backend.service.application.workflows.graph_executor",
    "backend.service.application.workflows.runtime_registry_loader",
    "backend.service.application.workflows.workflow_service",
    "backend.service.application.unit_of_work",
    "backend.contracts.files.yolox_model_files",
    "backend.service.application.conversions.yolox_conversion_planner",
    "backend.service.application.conversions.yolox_conversion_task_service",
    "backend.service.application.datasets.dataset_import",
    "backend.service.application.datasets.dataset_export",
    "backend.service.application.datasets.dataset_export_delivery",
    "backend.service.application.deployments.yolox_deployment_binding",
    "backend.service.application.models.yolox_model_service",
    "backend.service.application.models.yolox_training_service",
    "backend.service.api.deps.storage",
    "backend.service.domain.datasets.dataset_export",
    "backend.service.domain.datasets.dataset_export_repository",
    "backend.service.domain.datasets.dataset_import",
    "backend.service.domain.datasets.dataset_import_repository",
    "backend.service.domain.datasets.dataset_version",
    "backend.service.domain.datasets.dataset_version_repository",
    "backend.service.domain.files.yolox_file_types",
    "backend.service.domain.files.model_file",
    "backend.service.domain.files.model_file_repository",
    "backend.service.domain.models.model_records",
    "backend.service.domain.models.model_repository",
    "backend.service.domain.models.yolox_model_spec",
    "backend.service.domain.tasks.resource_profile_repository",
    "backend.service.domain.tasks.task_records",
    "backend.service.domain.tasks.task_repository",
    "backend.service.domain.tasks.yolox_task_specs",
    "backend.service.infrastructure.db.session",
    "backend.service.infrastructure.db.unit_of_work",
    "backend.service.infrastructure.persistence.base",
    "backend.service.infrastructure.persistence.dataset_export_orm",
    "backend.service.infrastructure.persistence.dataset_export_repository",
    "backend.service.infrastructure.persistence.dataset_import_orm",
    "backend.service.infrastructure.persistence.dataset_import_repository",
    "backend.service.infrastructure.persistence.dataset_orm",
    "backend.service.infrastructure.persistence.dataset_repository",
    "backend.service.infrastructure.object_store.local_dataset_storage",
    "backend.service.infrastructure.persistence.model_file_orm",
    "backend.service.infrastructure.persistence.model_file_repository",
    "backend.service.infrastructure.persistence.model_orm",
    "backend.service.infrastructure.persistence.model_repository",
    "backend.service.infrastructure.persistence.resource_profile_repository",
    "backend.service.infrastructure.persistence.task_orm",
    "backend.service.infrastructure.persistence.task_repository",
    "backend.workers.bootstrap",
    "backend.workers.conversion.yolox_conversion_runner",
    "backend.workers.conversion.yolox_conversion_queue_worker",
    "backend.workers.datasets.dataset_export_runner",
    "backend.workers.datasets.dataset_export_queue_worker",
    "backend.workers.datasets.dataset_import_runner",
    "backend.workers.datasets.dataset_import_queue_worker",
    "backend.workers.inference.yolox_inference_runner",
    "backend.workers.main",
    "backend.workers.settings",
    "backend.workers.shared.yolox_runtime_contracts",
    "backend.workers.task_manager",
    "backend.workers.training.yolox_trainer_runner",
    "backend.workers.training.yolox_training_queue_worker",
)


@pytest.mark.parametrize("module_name", BACKEND_MODULES)
def test_backend_modules_can_be_imported(module_name: str) -> None:
    """验证 backend 骨架模块可以被成功导入。

    参数：
    - module_name：要导入的模块名。
    """

    imported_module = importlib.import_module(module_name)

    assert imported_module is not None