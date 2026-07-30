"""Workflow Application 的 Prompt Mask 文件生命周期测试。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.workflows.documents.applications import (
    WorkflowApplicationDocumentStore,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_save_cleanup_prunes_only_unreferenced_prompt_masks(tmp_path) -> None:
    """节点从当前模板删除后清理其 Mask，同时保留仍被引用的 Mask。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    document_store = WorkflowApplicationDocumentStore(
        dataset_storage=dataset_storage,
        template_documents=None,  # type: ignore[arg-type]
    )
    referenced_key = (
        "projects/project-1/inputs/workflow-applications/app-1/"
        "prompt-masks/mask-editor-kept/kept.png"
    )
    removed_key = (
        "projects/project-1/inputs/workflow-applications/app-1/"
        "prompt-masks/mask-editor-removed/removed.png"
    )
    dataset_storage.write_bytes(referenced_key, b"kept")
    dataset_storage.write_bytes(removed_key, b"removed")
    template = WorkflowGraphTemplate.model_validate(
        {
            "format_id": "amvision.workflow-graph-template.v1",
            "template_id": "mask-lifecycle",
            "template_version": "0.1.3",
            "display_name": "Mask Lifecycle",
            "nodes": [
                {
                    "node_id": "mask-editor-kept",
                    "node_type_id": "core.input.mask-editor",
                    "parameters": {"mask_object_key": referenced_key},
                    "metadata": {},
                }
            ],
            "edges": [],
            "template_inputs": [],
            "template_outputs": [],
            "metadata": {},
        }
    )

    document_store._prune_unreferenced_prompt_masks(
        project_id="project-1",
        application_id="app-1",
        template=template,
    )

    assert dataset_storage.resolve(referenced_key).is_file()
    assert not dataset_storage.resolve(removed_key).exists()


def test_delete_application_removes_prompt_mask_root(tmp_path) -> None:
    """删除应用时一并删除该应用独占的全部 Prompt Mask。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    document_store = WorkflowApplicationDocumentStore(
        dataset_storage=dataset_storage,
        template_documents=None,  # type: ignore[arg-type]
    )
    application_key = "workflows/projects/project-1/applications/app-1/application.json"
    prompt_mask_key = (
        "projects/project-1/inputs/workflow-applications/app-1/"
        "prompt-masks/mask-editor-1/mask.png"
    )
    dataset_storage.write_json(application_key, {})
    dataset_storage.write_bytes(prompt_mask_key, b"mask")

    document_store.delete_application(
        project_id="project-1",
        application_id="app-1",
    )

    assert not dataset_storage.resolve(application_key).exists()
    assert not dataset_storage.resolve(prompt_mask_key).exists()
